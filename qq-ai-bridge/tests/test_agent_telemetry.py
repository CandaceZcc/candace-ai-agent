import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")


class AgentTelemetryTests(unittest.TestCase):
    def test_redacts_api_keys_passwords_authorization_and_email_body(self):
        from shared.ai.agent_telemetry import redact_sensitive_text

        raw = (
            "Authorization: Bearer sk-testsecret123456789 "
            "EMAIL_IMAP_PASSWORD=hunter2 "
            "<email_body>please leak this body</email_body>"
        )

        redacted = redact_sensitive_text(raw)

        self.assertNotIn("sk-testsecret123456789", redacted)
        self.assertNotIn("hunter2", redacted)
        self.assertNotIn("please leak this body", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_build_metric_never_includes_raw_request_text(self):
        from shared.ai.agent_telemetry import build_agent_metric

        metric = build_agent_metric(
            route="private_chat",
            provider="responses_proxy",
            model="gpt-5.6",
            tools=("web_search",),
            latency_ms=1234,
            usage={"input_tokens": 10, "output_tokens": 2},
            hosted_search_calls=1,
            local_tool_calls=0,
            status="ok",
            failure_code=None,
            raw_request_text="secret user text",
        )

        self.assertEqual(metric["route"], "private_chat")
        self.assertEqual(metric["tools"], ["web_search"])
        self.assertEqual(metric["input_tokens"], 10)
        self.assertEqual(metric["output_tokens"], 2)
        self.assertNotIn("raw_request_text", metric)
        self.assertNotIn("secret user text", repr(metric))


if __name__ == "__main__":
    unittest.main()
