import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, "qq-ai-bridge")


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "email"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


class EmailParserTests(unittest.TestCase):
    def parse(self, fixture: str, *, max_body_chars: int = 20000):
        from apps.qq_ai_bridge.services.email_parser import parse_email

        return parse_email(fixture_bytes(fixture), max_body_chars=max_body_chars)

    def test_decodes_encoded_headers(self):
        envelope = self.parse("plain.eml")

        self.assertEqual(envelope.subject, "校园通知")
        self.assertEqual(envelope.sender, "测试老师 <teacher@example.invalid>")

    def test_prefers_plain_text_body(self):
        envelope = self.parse("multipart_attachment.eml")

        self.assertIn("Preferred plain text body.", envelope.body_text)
        self.assertNotIn("HTML body should not replace", envelope.body_text)

    def test_converts_html_to_readable_text(self):
        envelope = self.parse("html_only.eml")

        self.assertIn("Registration notice", envelope.body_text)
        self.assertIn(
            "course guide (https://portal.example.invalid/guide)",
            envelope.body_text,
        )

    def test_drops_script_style_and_tracking_resources(self):
        body = self.parse("html_only.eml").body_text

        self.assertNotIn("alert('unsafe')", body)
        self.assertNotIn("display: none", body)
        self.assertNotIn("tracker.example.invalid", body)
        self.assertNotIn("tracking fallback", body)
        self.assertNotIn("javascript:", body)
        self.assertNotIn("data:", body)

    def test_does_not_return_attachment_bytes(self):
        envelope = self.parse("multipart_attachment.eml")

        self.assertEqual(len(envelope.attachments), 1)
        self.assertEqual(envelope.attachments[0].content_type, "application/pdf")
        self.assertEqual(envelope.attachments[0].size_bytes, len(b"Synthetic PDF"))
        self.assertFalse(hasattr(envelope.attachments[0], "content"))
        self.assertNotIn("Synthetic PDF", envelope.body_text)

    def test_sanitizes_attachment_filename(self):
        attachment = self.parse("multipart_attachment.eml").attachments[0]

        self.assertEqual(attachment.filename, "report.pdf")
        self.assertNotIn("/", attachment.filename)
        self.assertNotIn("\\", attachment.filename)

    def test_caps_body_characters(self):
        envelope = self.parse("plain.eml", max_body_chars=18)

        self.assertEqual(len(envelope.body_text), 18)

    def test_malformed_headers_do_not_crash(self):
        envelope = self.parse("malformed_headers.eml")

        self.assertTrue(envelope.subject)
        self.assertIn("broken@example.invalid", envelope.sender)
        self.assertIsNone(envelope.sent_at)
        self.assertIn("Malformed headers", envelope.body_text)

    def test_message_id_fallback_is_deterministic(self):
        raw_message = fixture_bytes("malformed_headers.eml")

        first = self.parse("malformed_headers.eml")
        second = self.parse("malformed_headers.eml")

        self.assertEqual(first.message_id, second.message_id)
        self.assertEqual(first.message_id, f"sha256:{hashlib.sha256(raw_message).hexdigest()}")


if __name__ == "__main__":
    unittest.main()
