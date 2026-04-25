import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services import private_chat_service
from apps.qq_ai_bridge.services.private_chat_service import _PRIVATE_CHAT_STATES, _handle_private_emoji_request, enqueue_private_text


class PrivateChatServiceTests(unittest.TestCase):
    @patch("apps.qq_ai_bridge.services.response_action.react_message_with_multiple_emojis")
    @patch("apps.qq_ai_bridge.services.response_action.send_private_msg")
    @patch("apps.qq_ai_bridge.services.private_chat_service.send_private_msg")
    def test_handle_private_emoji_request_prefers_message_reaction_when_explicit(
        self, mock_direct_send, mock_fallback_send, mock_react
    ):
        mock_react.return_value = {"ok": True, "applied_count": 2}

        result = _handle_private_emoji_request(
            user_id=123,
            merged_text="消息上面多贴几个表情",
            current_message_ts=1,
            message_id=9988,
        )

        self.assertTrue(result["handled"])
        self.assertEqual(result["mode"], "reaction")
        mock_react.assert_called_once()
        self.assertEqual(mock_react.call_args.kwargs["preferred_order"][:2], ("button_marker", "laugh_cry"))
        self.assertTrue(mock_react.call_args.kwargs["preserve_order"])
        mock_fallback_send.assert_called_once()
        mock_direct_send.assert_not_called()

    @patch("apps.qq_ai_bridge.services.response_action.react_message_with_multiple_emojis")
    @patch("apps.qq_ai_bridge.services.response_action.send_private_msg")
    @patch("apps.qq_ai_bridge.services.private_chat_service.send_private_msg")
    def test_handle_private_emoji_request_prefers_message_reaction_for_message_phrase_variant(
        self, mock_direct_send, mock_fallback_send, mock_react
    ):
        mock_react.return_value = {"ok": True, "applied_count": 2}

        result = _handle_private_emoji_request(
            user_id=123,
            merged_text="给我消息贴几个常用表情",
            current_message_ts=1,
            message_id=9988,
        )

        self.assertTrue(result["handled"])
        self.assertEqual(result["mode"], "reaction")
        mock_react.assert_called_once()
        mock_fallback_send.assert_called_once()
        mock_direct_send.assert_not_called()

    @patch("apps.qq_ai_bridge.services.response_action.react_message_with_multiple_emojis")
    @patch("apps.qq_ai_bridge.services.private_chat_service.send_private_msg")
    def test_handle_private_emoji_request_ignores_generic_face_fallback(self, mock_send, mock_react):
        result = _handle_private_emoji_request(
            user_id=123,
            merged_text="给我贴个表情",
            current_message_ts=1,
            message_id=9988,
        )

        self.assertFalse(result["handled"])
        mock_react.assert_not_called()
        mock_send.assert_not_called()

    @patch("apps.qq_ai_bridge.services.response_action.react_message_with_multiple_emojis")
    @patch("apps.qq_ai_bridge.services.private_chat_service.send_private_msg")
    def test_handle_private_emoji_request_falls_back_to_named_cq_face(self, mock_send, mock_react):
        result = _handle_private_emoji_request(
            user_id=123,
            merged_text="给我贴个笑哭表情",
            current_message_ts=1,
            message_id=9988,
        )

        self.assertTrue(result["handled"])
        self.assertEqual(result["mode"], "face_fallback")
        mock_react.assert_not_called()
        mock_send.assert_called_once()

    @patch("apps.qq_ai_bridge.services.private_chat_service.append_private_history")
    @patch("apps.qq_ai_bridge.services.private_chat_service.append_private_style_sample")
    @patch("apps.qq_ai_bridge.services.private_chat_service.prepare_private_ai_prompt")
    @patch("apps.qq_ai_bridge.services.private_chat_service.get_user_workspace")
    @patch("apps.qq_ai_bridge.services.response_action.react_message_with_multiple_emojis")
    @patch("apps.qq_ai_bridge.services.response_action.send_private_msg")
    @patch("apps.qq_ai_bridge.services.private_chat_service.send_private_msg")
    def test_private_worker_simulates_explicit_message_reaction(
        self,
        mock_direct_send,
        mock_fallback_send,
        mock_react,
        _mock_workspace,
        mock_prompt,
        _mock_style,
        mock_history,
    ):
        old_debounce = private_chat_service.DEBOUNCE_MS
        private_chat_service.DEBOUNCE_MS = 0
        _PRIVATE_CHAT_STATES.clear()
        mock_prompt.return_value = {
            "prompt": "unused",
            "context_gap_seconds": 0,
            "context_policy": "full",
            "context_reason": "test",
            "prompt_mode": "test",
            "query_len": 1,
            "history_chars": 0,
            "history_items": 0,
            "instruction_chars": 0,
            "prompt_chars": 1,
        }
        mock_react.return_value = {"ok": True, "applied_count": 2}

        try:
            result = enqueue_private_text(123, "消息上面多贴几个表情", timestamp=1, message_id=9988)
            deadline = time.time() + 2
            while time.time() < deadline and _PRIVATE_CHAT_STATES[str(123)].worker_running:
                time.sleep(0.01)
        finally:
            private_chat_service.DEBOUNCE_MS = old_debounce

        self.assertTrue(result["queued"])
        mock_react.assert_called_once()
        self.assertEqual(mock_react.call_args.kwargs["preferred_order"][:2], ("button_marker", "laugh_cry"))
        self.assertTrue(mock_react.call_args.kwargs["preserve_order"])
        mock_fallback_send.assert_called_once()
        mock_direct_send.assert_not_called()
        mock_history.assert_called_once()


if __name__ == "__main__":
    unittest.main()
