import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, "qq-ai-bridge")


class CapabilityProbeTests(unittest.TestCase):
    def test_responses_probe_applies_reasoning_and_storage_settings(self):
        from shared.ai import capability_probe

        response = SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "OK"}],
                    }
                ]
            },
        )
        post = MagicMock(return_value=response)
        with patch.multiple(
            capability_probe,
            AGENT_MODEL_REASONING_EFFORT="high",
            AGENT_DISABLE_RESPONSE_STORAGE=True,
        ):
            result = capability_probe.run_probe(
                provider="responses_proxy",
                probe="text",
                post=post,
            )

        self.assertTrue(result.supported)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["reasoning"], {"effort": "high"})
        self.assertFalse(payload["store"])

    def test_chat_compatible_skips_hosted_probes(self):
        from shared.ai.capability_probe import interpret_probe_response

        result = interpret_probe_response(
            provider="chat_compatible",
            probe="web_search",
            status_code=200,
            payload={"output": [{"type": "web_search_call"}]},
        )

        self.assertFalse(result.supported)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("skips hosted probes", result.message)

    def test_responses_text_success_marks_responses_only(self):
        from shared.ai.capability_probe import interpret_probe_response

        result = interpret_probe_response(
            provider="responses_proxy",
            probe="text",
            status_code=200,
            payload={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "OK"}],
                    }
                ]
            },
        )

        self.assertTrue(result.supported)
        self.assertTrue(result.capabilities.responses)
        self.assertFalse(result.capabilities.hosted_web_search)
        self.assertFalse(result.capabilities.builtin_computer)

    def test_web_search_call_item_marks_search_supported(self):
        from shared.ai.capability_probe import interpret_probe_response

        result = interpret_probe_response(
            provider="responses_proxy",
            probe="web_search",
            status_code=200,
            payload={
                "output": [
                    {"type": "web_search_call", "status": "completed"},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Answer",
                                "annotations": [
                                    {"type": "url_citation", "url": "https://example.com"}
                                ],
                            }
                        ],
                    },
                ]
            },
        )

        self.assertTrue(result.supported)
        self.assertTrue(result.capabilities.hosted_web_search)

    def test_model_text_without_web_search_call_does_not_pass_search_probe(self):
        from shared.ai.capability_probe import interpret_probe_response

        result = interpret_probe_response(
            provider="responses_proxy",
            probe="web_search",
            status_code=200,
            payload={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Here is a URL: https://example.com",
                            }
                        ],
                    }
                ]
            },
        )

        self.assertFalse(result.supported)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("web_search_call", result.message)

    def test_computer_call_item_marks_computer_supported(self):
        from shared.ai.capability_probe import interpret_probe_response

        result = interpret_probe_response(
            provider="responses_proxy",
            probe="computer",
            status_code=200,
            payload={"output": [{"type": "computer_call", "call_id": "call_123"}]},
        )

        self.assertTrue(result.supported)
        self.assertTrue(result.capabilities.builtin_computer)

    def test_401_and_403_are_redacted(self):
        from shared.ai.capability_probe import interpret_probe_response

        result = interpret_probe_response(
            provider="responses_proxy",
            probe="text",
            status_code=401,
            payload={"error": {"message": "bad key sk-secret-token"}},
            response_text="Authorization: Bearer sk-secret-token",
        )

        self.assertFalse(result.supported)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("authentication", result.message)
        self.assertNotIn("sk-secret-token", result.message)
        self.assertNotIn("Authorization", result.message)

    def test_unknown_error_does_not_leak_response_body(self):
        from shared.ai.capability_probe import interpret_probe_response

        result = interpret_probe_response(
            provider="responses_proxy",
            probe="text",
            status_code=500,
            payload={"error": {"message": "stack trace with private request body"}},
            response_text="stack trace with private request body",
        )

        self.assertFalse(result.supported)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("upstream error 500", result.message)
        self.assertNotIn("private request body", result.message)


if __name__ == "__main__":
    unittest.main()
