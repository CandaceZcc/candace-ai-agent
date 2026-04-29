import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.file_service import derive_filename, extract_file_info, handle_file_message


class FileServiceExtractFileInfoTests(unittest.TestCase):
    def test_extracts_snake_case_file_message_payload(self):
        payload = {
            "message": [
                {
                    "type": "file",
                    "data": {
                        "file_name": "示例.docx",
                        "file_id": "file-123",
                        "file_sub_id": "sub-1",
                    },
                }
            ]
        }

        result = extract_file_info(payload)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "示例.docx")
        self.assertEqual(result["uuid"], "file-123")
        self.assertEqual(result["sub_id"], "sub-1")

    def test_extracts_camel_case_file_message_payload(self):
        payload = {
            "message": [
                {
                    "type": "file",
                    "data": {
                        "fileName": "测试文档.docx",
                        "fileId": "camel-123",
                        "fileSubId": "camel-sub-1",
                        "downloadUrl": "https://example.com/camel.docx",
                    },
                }
            ]
        }

        result = extract_file_info(payload)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "测试文档.docx")
        self.assertEqual(result["uuid"], "camel-123")
        self.assertEqual(result["sub_id"], "camel-sub-1")
        self.assertEqual(result["url"], "https://example.com/camel.docx")

    def test_extracts_top_level_elements_file_element(self):
        payload = {
            "elements": [
                {
                    "fileElement": {
                        "fileName": "文档.docx",
                        "fileUuid": "uuid-1",
                        "fileSubId": "sub-9",
                        "filePath": "/tmp/文档.docx",
                    }
                }
            ]
        }

        result = extract_file_info(payload)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "文档.docx")
        self.assertEqual(result["uuid"], "uuid-1")
        self.assertEqual(result["sub_id"], "sub-9")
        self.assertEqual(result["path"], "/tmp/文档.docx")

    def test_extracts_event_level_elements_file_element(self):
        payload = {
            "elements": [
                {
                    "fileElement": {
                        "fileName": "事件文档.docx",
                        "fileUuid": "evt-uuid-1",
                    }
                }
            ]
        }

        result = extract_file_info(payload)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "事件文档.docx")
        self.assertEqual(result["uuid"], "evt-uuid-1")

    def test_extracts_notice_top_level_file_payload(self):
        payload = {
            "file": {
                "name": "上传文件.docx",
                "url": "https://example.com/file.docx",
                "file_id": "notice-1",
            }
        }

        result = extract_file_info(payload)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "上传文件.docx")
        self.assertEqual(result["url"], "https://example.com/file.docx")
        self.assertEqual(result["uuid"], "notice-1")

    def test_extracts_cq_file_raw_message_payload(self):
        payload = {
            "message": "[CQ:file,file=测试稿.docx,file_id=cq-1,url=https://example.com/cq.docx]"
        }

        result = extract_file_info(payload)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "测试稿.docx")
        self.assertEqual(result["uuid"], "cq-1")
        self.assertEqual(result["url"], "https://example.com/cq.docx")

    def test_derives_filename_from_url_when_name_missing(self):
        file_info = {
            "url": "https://example.com/uploads/%E6%B5%8B%E8%AF%95%E6%96%87%E6%A1%A3.docx?token=1",
            "uuid": "file-xyz",
        }

        result = derive_filename(file_info)

        self.assertEqual(result, "测试文档.docx")

    def test_derives_filename_from_uuid_when_only_uuid_exists(self):
        file_info = {"uuid": "file-only-id"}

        result = derive_filename(file_info)

        self.assertEqual(result, "file-only-id")

    @patch("apps.qq_ai_bridge.services.file_service.send_group_msg")
    @patch("apps.qq_ai_bridge.services.file_service.download_file_if_possible")
    def test_group_file_message_does_not_send_or_download(self, mock_download, mock_send_group_msg):
        result = handle_file_message(
            "group",
            user_id=1,
            group_id=123,
            file_info={"name": "demo.txt", "url": "https://example.com/demo.txt"},
        )

        self.assertEqual(result, {"status": "ignore", "reason": "group_file_disabled"})
        mock_send_group_msg.assert_not_called()
        mock_download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
