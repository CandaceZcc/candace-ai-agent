"""File extraction and upload handling services."""

import mimetypes
import os
import shutil
import stat
import zipfile
import xml.etree.ElementTree as ET

import requests

from apps.qq_ai_bridge.adapters.napcat_client import fetch_napcat_file_download_info, send_group_msg, send_private_msg
from apps.qq_ai_bridge.config.settings import (
    ALLOWED_PRIVATE_USER,
    GROUP_UPLOAD_DIR,
    MAX_ARCHIVE_LISTING,
    MAX_ARCHIVE_PREVIEW_FILES,
    MAX_FILE_CONTENT_LEN,
    OFFICE_XML_EXTS,
    PRIVATE_UPLOAD_DIR,
    TEXT_LIKE_EXTS,
)
from shared.ai.llm_client import call_ai


def extract_file_info(event_data):
    """Extract file info from NapCat / OneBot message payloads."""
    raw_message = event_data.get("message")
    raw_obj = event_data.get("raw", {})
    elements = raw_obj.get("elements", [])
    if isinstance(elements, list):
        for elem in elements:
            if not isinstance(elem, dict):
                continue

            file_elem = elem.get("fileElement")
            if isinstance(file_elem, dict):
                file_info = {
                    "name": file_elem.get("fileName") or file_elem.get("name"),
                    "url": file_elem.get("downloadUrl") or file_elem.get("url") or file_elem.get("fileUrl"),
                    "size": file_elem.get("fileSize"),
                    "uuid": file_elem.get("fileUuid") or file_elem.get("fileId"),
                    "sub_id": file_elem.get("fileSubId"),
                    "path": file_elem.get("filePath"),
                    "raw": file_elem,
                }
                print(f"[FILE] extract_file_info 命中 raw.elements: {file_info}")
                return file_info

    if isinstance(raw_message, list):
        for seg in raw_message:
            if not isinstance(seg, dict):
                continue
            if seg.get("type") == "file":
                data = seg.get("data", {})
                file_info = {
                    "name": data.get("name") or data.get("file_name") or data.get("file"),
                    "url": data.get("url"),
                    "size": data.get("file_size") or data.get("size"),
                    "uuid": data.get("file_id"),
                    "sub_id": data.get("file_sub_id"),
                    "path": data.get("path") or data.get("file_path"),
                    "raw": data,
                }
                print(f"[FILE] extract_file_info 命中 message.file: {file_info}")
                return file_info

    print("[FILE] extract_file_info 未找到文件信息")
    return None


def resolve_file_download_info(file_info):
    """Resolve file download URL from event or NapCat file API."""
    direct_url = file_info.get("url")
    if direct_url:
        print(f"[FILE_API] 使用事件自带 URL: {direct_url}")
        return direct_url, "url_from_event"

    resolved_url, reason = fetch_napcat_file_download_info(file_info)
    if resolved_url:
        file_info["url"] = resolved_url
        print(f"[FILE_API] 解析下载地址成功: {resolved_url}")
        return resolved_url, reason

    print(f"[FILE_API] 解析下载地址失败: {reason}")
    return None, reason


def safe_filename(name: str) -> str:
    """Convert a potentially unsafe filename into a safe local filename."""
    if not name:
        return "unknown_file"
    return name.replace("/", "_").replace("\\", "_").strip()


def describe_fs_entry(path):
    """Return a human-readable description of a filesystem entry."""
    try:
        st = os.stat(path)
        mode = stat.filemode(st.st_mode)
        return (
            f"path={path!r}, mode={mode}, uid={st.st_uid}, gid={st.st_gid}, "
            f"size={st.st_size}, readable={os.access(path, os.R_OK)}"
        )
    except Exception as e:
        return f"path={path!r}, stat_failed={e}"


def download_file_if_possible(file_info, save_dir):
    """Download or copy a file attachment into the target directory."""
    name = safe_filename(file_info.get("name"))
    local_path = file_info.get("path")
    target_path = os.path.join(save_dir, name)
    url, resolve_reason = resolve_file_download_info(file_info)

    if url:
        if url.startswith("/app/.config/QQ"):
            try:
                host_path = url.replace("/app/.config/QQ", os.path.expanduser("~/napcat/qq"))
                print(f"[FILE] 检测到 NapCat 容器路径: {url} -> {host_path}")
                if not os.path.exists(host_path):
                    reason = f"napcat_host_path_missing: {host_path}"
                    print(f"[FILE] 容器文件不存在: {reason}")
                    return None, reason
                if not os.access(host_path, os.R_OK):
                    reason = f"napcat_host_path_not_readable: {describe_fs_entry(host_path)}"
                    print(f"[FILE] 容器文件无读取权限: {reason}")
                    return None, reason
                shutil.copy(host_path, target_path)
                print(f"[FILE] 容器文件复制成功: {target_path}")
                return target_path, "copied_from_napcat"
            except Exception as e:
                print(f"[FILE] 容器文件复制失败: {e}")
                return None, f"copy_from_napcat_failed: {e}"
        else:
            try:
                print(f"[FILE] 通过 URL 下载: {url} -> {target_path}")
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                with open(target_path, "wb") as f:
                    f.write(r.content)
                print(f"[FILE] 下载成功: {target_path}")
                return target_path, "downloaded_by_url"
            except Exception as e:
                print(f"[FILE] URL 下载失败: {e}")
                return None, f"url_download_failed: {e}"

    print(f"[FILE] 未拿到可用下载链接，准备尝试本地路径。原因: {resolve_reason}")

    if local_path and os.path.exists(local_path):
        try:
            shutil.copy(local_path, target_path)
            print(f"[FILE] 本地复制成功: {target_path}")
            return target_path, "copied_from_local_path"
        except Exception as e:
            print(f"[FILE] 本地复制失败: {e}")
            return None, f"copy_local_path_failed: {e}"

    reason = f"no_download_url_and_local_path_unavailable: {local_path}"
    print(f"[FILE] 文件保存失败: {reason}, local_path={local_path!r}")
    return None, reason


def read_text_file(path):
    """Read a text file with fallback encodings."""
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()[:MAX_FILE_CONTENT_LEN]
        except UnicodeDecodeError as e:
            print(f"[FILE] 读取失败(编码): {e}")
            continue
        except Exception as e:
            print(f"[FILE] 读取失败: {e}")
            return ""
    return ""


def extract_pdf_text(path):
    """Best-effort PDF text extraction placeholder."""
    try:
        import fitz  # type: ignore

        doc = fitz.open(path)
        text = "\n".join(page.get_text() for page in doc)
        text = text.strip()
        if text:
            print(f"[FILE] PDF 文本提取成功: {path}")
            return text[:MAX_FILE_CONTENT_LEN], "pdf_text"
        print(f"[FILE] PDF 文本提取为空: {path}")
    except Exception as e:
        print(f"[FILE] PDF 文本提取失败: {e}")
    return None, None


def extract_docx_text(path):
    """Extract text from DOCX files."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            with zf.open("word/document.xml") as f:
                tree = ET.parse(f)
        texts = [node.text for node in tree.iter() if node.text]
        text = "\n".join(texts).strip()
        if text:
            print(f"[FILE] DOCX 文本提取成功: {path}")
            return text[:MAX_FILE_CONTENT_LEN], "docx_text"
    except Exception as e:
        print(f"[FILE] DOCX 文本提取失败: {e}")
    return None, None


def extract_pptx_text(path):
    """Extract text from PPTX files."""
    try:
        texts = []
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                    with zf.open(name) as f:
                        tree = ET.parse(f)
                    texts.extend(node.text for node in tree.iter() if node.text)
        text = "\n".join(texts).strip()
        if text:
            print(f"[FILE] PPTX 文本提取成功: {path}")
            return text[:MAX_FILE_CONTENT_LEN], "pptx_text"
    except Exception as e:
        print(f"[FILE] PPTX 文本提取失败: {e}")
    return None, None


def extract_xlsx_text(path):
    """Extract text from XLSX shared strings and worksheet XML."""
    try:
        texts = []
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(".xml") and (name.startswith("xl/sharedStrings") or name.startswith("xl/worksheets/")):
                    with zf.open(name) as f:
                        tree = ET.parse(f)
                    texts.extend(node.text for node in tree.iter() if node.text)
        text = "\n".join(texts).strip()
        if text:
            print(f"[FILE] XLSX 文本提取成功: {path}")
            return text[:MAX_FILE_CONTENT_LEN], "xlsx_text"
    except Exception as e:
        print(f"[FILE] XLSX 文本提取失败: {e}")
    return None, None


def extract_zip_summary(path):
    """Summarize a ZIP archive."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
        preview = names[:MAX_ARCHIVE_LISTING]
        summary = "ZIP 文件结构：\n" + "\n".join(preview)
        if len(names) > MAX_ARCHIVE_LISTING:
            summary += f"\n... 其余 {len(names) - MAX_ARCHIVE_LISTING} 个文件省略"
        print(f"[FILE] ZIP 结构提取成功: {path}")
        return summary[:MAX_FILE_CONTENT_LEN], "zip_summary"
    except Exception as e:
        print(f"[FILE] ZIP 结构提取失败: {e}")
    return None, None


def build_binary_file_summary(path, filename):
    """Build a metadata-only summary for binary files."""
    mime_type, _ = mimetypes.guess_type(filename or path)
    size = os.path.getsize(path)
    print(f"[FILE] 生成二进制文件摘要: {filename!r}, mime={mime_type!r}, size={size}")
    return (
        f"这是一个二进制文件。\n文件名：{filename}\nMIME：{mime_type}\n大小：{size} 字节"
    )[:MAX_FILE_CONTENT_LEN], "binary_summary"


def extract_file_content_for_ai(path, filename):
    """Extract best-effort readable content from an uploaded file."""
    ext = os.path.splitext(filename or path)[1].lower()
    mime_type, _ = mimetypes.guess_type(filename or path)
    print(f"[FILE] 开始提取文件内容: path={path}, ext={ext!r}, mime={mime_type!r}")

    if ext in TEXT_LIKE_EXTS or (mime_type and mime_type.startswith("text/")):
        content = read_text_file(path)
        if content:
            return content, "text_direct"

    if ext == ".pdf":
        content, reason = extract_pdf_text(path)
        if content:
            return content, reason
    if ext == ".docx":
        content, reason = extract_docx_text(path)
        if content:
            return content, reason
    if ext == ".pptx":
        content, reason = extract_pptx_text(path)
        if content:
            return content, reason
    if ext == ".xlsx":
        content, reason = extract_xlsx_text(path)
        if content:
            return content, reason
    if ext == ".zip" or zipfile.is_zipfile(path):
        content, reason = extract_zip_summary(path)
        if content:
            return content, reason

    content = read_text_file(path)
    if content:
        return content, "text_fallback"
    return build_binary_file_summary(path, filename)


def handle_file_message(message_type, user_id, group_id, file_info):
    """Handle uploaded files for private or group contexts."""
    filename = file_info.get("name")
    file_url = file_info.get("url")
    file_path = file_info.get("path")
    safe_name = safe_filename(filename or "unknown_file")

    print(f"[FILE] 收到文件: name={filename!r}, url={file_url!r}, path={file_path!r}")

    if message_type == "private" and user_id != ALLOWED_PRIVATE_USER:
        print(f"[FILE] 非授权私聊用户 {user_id}，拒绝处理文件")
        return "ignore"

    if message_type == "group":
        send_group_msg(group_id, "为保护隐私，群聊模式下不会直接解析或输出文件内容，请改为私聊发送。")
        return {"status": "file_blocked_in_group"}

    if not filename:
        msg = "已检测到文件事件，但暂时没拿到文件名。"
        send_private_msg(user_id, msg)
        return {"status": "file_no_name"}

    save_dir = PRIVATE_UPLOAD_DIR if message_type == "private" else GROUP_UPLOAD_DIR
    saved_path, reason = download_file_if_possible(file_info, save_dir)

    if not saved_path:
        msg = (
            f"已识别文件：{safe_name}\n当前未能获取可用下载链接，也无法从本地路径读取。\n"
            f"原因：{reason}\n请稍后重试，或检查 NapCat 文件接口配置。"
        )
        send_private_msg(user_id, msg)
        return {"status": "file_recognized_but_not_downloaded"}

    content, extract_reason = extract_file_content_for_ai(saved_path, safe_name)
    if not content:
        send_private_msg(user_id, f"文件已保存：{safe_name}\n但当前无法提取内容。")
        return {"status": "file_read_failed"}

    query = (
        "你是一个文件阅读助手。请基于以下文件内容或文件结构信息，尽量准确说明文件是什么、主要内容是什么、有哪些值得注意的信息。"
        "如果文件本身无法完整转成纯文本，也要明确说明你是基于结构/元数据进行判断。\n\n"
        f"文件名：{safe_name}\n保存路径：{saved_path}\n文件下载方式：{reason}\n文件内容提取方式：{extract_reason}\n\n{content}"
    )
    reply = call_ai(query)
    send_private_msg(user_id, reply)
    return {"status": "file_processed_private"}
