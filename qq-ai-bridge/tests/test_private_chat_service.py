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

    @patch("apps.qq_ai_bridge.services.private_chat_service.append_private_history")
    @patch("apps.qq_ai_bridge.services.private_chat_service.append_private_style_sample")
    @patch("apps.qq_ai_bridge.services.private_chat_service.prepare_private_ai_prompt")
    @patch("apps.qq_ai_bridge.services.private_chat_service.get_user_workspace")
    @patch("apps.qq_ai_bridge.services.private_chat_service.execute_private_action")
    @patch("apps.qq_ai_bridge.services.private_chat_service.call_ai")
    def test_private_worker_cooldown_records_without_llm(
        self,
        mock_call_ai,
        mock_execute,
        _mock_workspace,
        mock_prompt,
        _mock_style,
        mock_history,
    ):
        old_debounce = private_chat_service.DEBOUNCE_MS
        old_cooldown = private_chat_service.PRIVATE_REPLY_COOLDOWN_SEC
        private_chat_service.DEBOUNCE_MS = 0
        private_chat_service.PRIVATE_REPLY_COOLDOWN_SEC = 8
        _PRIVATE_CHAT_STATES.clear()
        state = private_chat_service._get_private_chat_state(456)
        state.last_reply_monotonic = time.monotonic()
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

        try:
            result = enqueue_private_text(456, "别刷屏", timestamp=1, message_id=1001)
            deadline = time.time() + 2
            while time.time() < deadline and _PRIVATE_CHAT_STATES[str(456)].worker_running:
                time.sleep(0.01)
        finally:
            private_chat_service.DEBOUNCE_MS = old_debounce
            private_chat_service.PRIVATE_REPLY_COOLDOWN_SEC = old_cooldown

        self.assertTrue(result["queued"])
        mock_call_ai.assert_not_called()
        mock_execute.assert_not_called()
        mock_history.assert_called_once()
        self.assertEqual(mock_history.call_args.args[3], "[cooldown_skip]")

    @patch("apps.qq_ai_bridge.services.private_chat_service.append_private_history")
    @patch("apps.qq_ai_bridge.services.private_chat_service.append_private_style_sample")
    @patch("apps.qq_ai_bridge.services.private_chat_service.prepare_private_ai_prompt")
    @patch("apps.qq_ai_bridge.services.private_chat_service.get_user_workspace")
    @patch("apps.qq_ai_bridge.services.private_chat_service.execute_private_action")
    @patch("apps.qq_ai_bridge.services.private_chat_service.call_ai", return_value="收到")
    def test_private_worker_merges_burst_into_one_llm_call(
        self,
        mock_call_ai,
        mock_execute,
        _mock_workspace,
        mock_prompt,
        _mock_style,
        _mock_history,
    ):
        old_debounce = private_chat_service.DEBOUNCE_MS
        old_cooldown = private_chat_service.PRIVATE_REPLY_COOLDOWN_SEC
        private_chat_service.DEBOUNCE_MS = 50
        private_chat_service.PRIVATE_REPLY_COOLDOWN_SEC = 0
        _PRIVATE_CHAT_STATES.clear()
        mock_prompt.return_value = {
            "prompt": "merged prompt",
            "context_gap_seconds": 0,
            "context_policy": "full",
            "context_reason": "test",
            "prompt_mode": "test",
            "query_len": 5,
            "history_chars": 0,
            "history_items": 0,
            "instruction_chars": 0,
            "prompt_chars": 12,
        }

        try:
            enqueue_private_text(789, "一", timestamp=1, message_id=1)
            enqueue_private_text(789, "二", timestamp=2, message_id=2)
            enqueue_private_text(789, "三", timestamp=3, message_id=3)
            deadline = time.time() + 2
            while time.time() < deadline and _PRIVATE_CHAT_STATES[str(789)].worker_running:
                time.sleep(0.01)
        finally:
            private_chat_service.DEBOUNCE_MS = old_debounce
            private_chat_service.PRIVATE_REPLY_COOLDOWN_SEC = old_cooldown

        mock_call_ai.assert_called_once_with(
            "merged prompt",
            metadata={
                "user_id": 789,
                "merged_message_count": 3,
                "prompt_mode": "test",
                "query_len": 5,
                "history_chars": 0,
                "history_items": 0,
                "instruction_chars": 0,
                "prompt_chars": 12,
            },
        )
        self.assertEqual(mock_prompt.call_args.args[1], "一\n二\n三")
        mock_execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
