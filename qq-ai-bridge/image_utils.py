import os
import re
import time
import uuid
from urllib.parse import parse_qs, urlparse

import requests


SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def extract_image_inputs(message_payload) -> dict:
    text_parts = []
    image_urls = []
    seen_texts = set()

    def add_text_part(value: str) -> None:
        normalized = normalize_text(value)
        if not normalized or normalized in seen_texts:
            return
        seen_texts.add(normalized)
        text_parts.append(normalized)

    raw_message = message_payload.get("message")
    if isinstance(raw_message, str):
        image_urls.extend(_extract_image_urls_from_cq_string(raw_message))
        image_urls.extend(_extract_direct_image_urls(raw_message))
        text_without_cq = re.sub(r"\[CQ:image,[^\]]+\]", " ", raw_message)
        text_without_cq = re.sub(r"\[CQ:[^\]]+\]", " ", text_without_cq)
        text_without_cq = re.sub(r"https?://\S+\.(?:jpg|jpeg|png|webp)(?:\?\S+)?", " ", text_without_cq, flags=re.IGNORECASE)
        add_text_part(text_without_cq)

    if isinstance(raw_message, list):
        for seg in raw_message:
            if not isinstance(seg, dict):
                continue
            seg_type = seg.get("type")
            data = seg.get("data", {})
            if seg_type == "text":
                add_text_part(data.get("text", ""))
            elif seg_type == "image":
                url = (
                    data.get("url")
                    or data.get("file_url")
                    or data.get("fileUrl")
                    or data.get("download_url")
                )
                if url:
                    image_urls.append(url)

    elements = message_payload.get("elements", [])
    if isinstance(elements, list):
        for elem in elements:
            if not isinstance(elem, dict):
                continue

            text_elem = elem.get("textElement")
            if isinstance(text_elem, dict):
                for key in ("content", "text"):
                    before_count = len(text_parts)
                    add_text_part(text_elem.get(key, ""))
                    if len(text_parts) != before_count:
                        break

            image_elem = elem.get("picElement") or elem.get("imageElement")
            if isinstance(image_elem, dict):
                url = (
                    image_elem.get("originImageUrl")
                    or image_elem.get("downloadUrl")
                    or image_elem.get("sourcePath")
                    or image_elem.get("url")
                    or image_elem.get("fileUrl")
                )
                if url:
                    image_urls.append(url)

    raw_obj = message_payload.get("raw", {})
    raw_elements = raw_obj.get("elements", [])
    if isinstance(raw_elements, list):
        for elem in raw_elements:
            if not isinstance(elem, dict):
                continue
            image_elem = elem.get("picElement") or elem.get("imageElement")
            if isinstance(image_elem, dict):
                url = (
                    image_elem.get("originImageUrl")
                    or image_elem.get("downloadUrl")
                    or image_elem.get("sourcePath")
                    or image_elem.get("url")
                    or image_elem.get("fileUrl")
                )
                if url:
                    image_urls.append(url)

            text_elem = elem.get("textElement")
            if isinstance(text_elem, dict):
                for key in ("content", "text"):
                    before_count = len(text_parts)
                    add_text_part(text_elem.get(key, ""))
                    if len(text_parts) != before_count:
                        break

    cleaned_urls = []
    seen = set()
    for url in image_urls:
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        cleaned_urls.append(url)

    return {
        "has_image": bool(cleaned_urls),
        "image_urls": cleaned_urls,
        "text": normalize_text(" ".join(text_parts))
    }


def _extract_image_urls_from_cq_string(raw_message: str):
    urls = []
    for match in re.finditer(r"\[CQ:image,([^\]]+)\]", raw_message or ""):
        params_raw = match.group(1)
        url_match = re.search(r"url=([^,\]]+)", params_raw)
        if url_match:
            urls.append(url_match.group(1))
    return urls


def _extract_direct_image_urls(raw_message: str):
    return re.findall(r"https?://\S+\.(?:jpg|jpeg|png|webp)(?:\?\S+)?", raw_message or "", flags=re.IGNORECASE)


def download_image(url, save_dir="tmp/images") -> str:
    ensure_dir(save_dir)

    parsed = urlparse(url)
    ext = os.path.splitext(parsed.path)[1].lower()
    if ext not in SUPPORTED_IMAGE_EXTS:
        query_ext = ""
        if parsed.query:
            query = parse_qs(parsed.query)
            for value in query.values():
                if not value:
                    continue
                query_ext = os.path.splitext(str(value[0]))[1].lower()
                if query_ext in SUPPORTED_IMAGE_EXTS:
                    ext = query_ext
                    break
        if ext not in SUPPORTED_IMAGE_EXTS:
            ext = ".jpg"

    filename = f"{int(time.time())}-{uuid.uuid4().hex}{ext}"
    local_path = os.path.join(save_dir, filename)

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    with open(local_path, "wb") as f:
        f.write(resp.content)
    return local_path
