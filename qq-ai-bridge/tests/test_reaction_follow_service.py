import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services import reaction_follow_service
from apps.qq_ai_bridge.services.reaction_follow_service import (
    find_recent_group_message,
    handle_group_reaction_notice,
    parse_group_reaction_notice,
    record_group_message_for_reaction_learning,
)
from storage_utils import load_group_config_store, save_group_config_store


class ReactionFollowServiceTests(unittest.TestCase):
    def setUp(self):
        reaction_follow_service._RECENT_NOTICE_KEYS.clear()
        reaction_follow_service._RECENT_GROUP_MESSAGES.clear()

    def test_parse_group_reaction_notice_direct_fields(self):
        parsed = parse_group_reaction_notice(
            {
                "notice_type": "group_msg_emoji_like",
                "group_id": 123,
                "user_id": 456,
                "message_id": 789,
                "emoji_id": 424,
            }
        )

        self.assertEqual(parsed["group_id"], "123")
        self.assertEqual(parsed["user_id"], "456")
        self.assertEqual(parsed["message_id"], "789")
        self.assertEqual(parsed["emoji_id"], "424")

    def test_parse_group_reaction_notice_nested_like_list(self):
        parsed = parse_group_reaction_notice(
            {
                "notice_type": "group_msg_emoji_like",
                "groupId": "123",
                "messageId": "789",
                "likes": [{"userId": "456", "emojiId": "339"}],
            }
        )

        self.assertEqual(parsed["user_id"], "456")
        self.assertEqual(parsed["emoji_id"], "339")

    @patch("apps.qq_ai_bridge.services.reaction_follow_service.set_msg_emoji_like")
    def test_handle_notice_records_but_does_not_follow_when_disabled(self, mock_set_like):
        result = handle_group_reaction_notice(
            {"notice_type": "group_msg_emoji_like", "group_id": 1, "user_id": 2, "message_id": 3, "emoji_id": 4},
            group_config={"follow_group_reactions": False},
            log=None,
        )

        self.assertTrue(result["handled"])
        self.assertFalse(result["followed"])
        mock_set_like.assert_not_called()

    @patch("apps.qq_ai_bridge.services.reaction_follow_service.set_msg_emoji_like")
    def test_handle_notice_respects_bot_can_reply_disabled(self, mock_set_like):
        result = handle_group_reaction_notice(
            {"notice_type": "group_msg_emoji_like", "group_id": 1, "user_id": 2, "message_id": 3, "emoji_id": 4},
            group_config={"follow_group_reactions": True, "bot_can_reply": False},
            log=None,
        )

        self.assertTrue(result["handled"])
        self.assertFalse(result["followed"])
        self.assertEqual(result["reason"], "bot_reply_disabled")
        mock_set_like.assert_not_called()

    @patch("apps.qq_ai_bridge.services.reaction_follow_service.set_msg_emoji_like")
    def test_handle_notice_follows_same_emoji_when_enabled(self, mock_set_like):
        mock_set_like.return_value = {"ok": True}

        result = handle_group_reaction_notice(
            {"notice_type": "group_msg_emoji_like", "group_id": 1, "user_id": 2, "message_id": 3, "emoji_id": 339},
            group_config={"follow_group_reactions": True, "reaction_follow_probability": 1},
            self_id=999,
            log=None,
        )

        self.assertTrue(result["followed"])
        mock_set_like.assert_called_once_with("3", emoji_id="339", quiet=True)

    @patch("apps.qq_ai_bridge.services.reaction_follow_service.set_msg_emoji_like")
    def test_handle_notice_records_matching_message_context(self, mock_set_like):
        mock_set_like.return_value = {"ok": True}
        record_group_message_for_reaction_learning(
            group_id=1,
            message_id=3,
            user_id=5,
            sender_name="alice",
            text="睡觉了",
            raw_message="睡觉了",
            timestamp=100,
        )

        result = handle_group_reaction_notice(
            {"notice_type": "group_msg_emoji_like", "group_id": 1, "user_id": 2, "message_id": 3, "emoji_id": 182},
            group_config={"follow_group_reactions": True, "reaction_follow_probability": 1},
            self_id=999,
            log=None,
        )

        self.assertTrue(result["followed"])
        self.assertEqual(result["message_text"], "睡觉了")
        self.assertEqual(result["message_sender_name"], "alice")
        self.assertEqual(result["message_context"]["user_id"], "5")

    def test_record_and_find_recent_group_message(self):
        record_group_message_for_reaction_learning(
            group_id=1,
            message_id=3,
            user_id=5,
            sender_name="alice",
            text="豪",
            raw_message="豪",
            timestamp=100,
        )

        matched = find_recent_group_message(1, 3)

        self.assertEqual(matched["text"], "豪")
        self.assertEqual(matched["sender_name"], "alice")

    @patch("apps.qq_ai_bridge.services.reaction_follow_service.set_msg_emoji_like")
    def test_handle_notice_ignores_self_and_duplicates(self, mock_set_like):
        event = {"notice_type": "group_msg_emoji_like", "group_id": 1, "user_id": 2, "message_id": 3, "emoji_id": 339}

        self_notice = handle_group_reaction_notice(
            event,
            group_config={"follow_group_reactions": True, "reaction_follow_probability": 1},
            self_id=2,
            log=None,
        )
        first = handle_group_reaction_notice(
            event,
            group_config={"follow_group_reactions": True, "reaction_follow_probability": 1},
            self_id=999,
            log=None,
        )
        duplicate = handle_group_reaction_notice(
            event,
            group_config={"follow_group_reactions": True, "reaction_follow_probability": 1},
            self_id=999,
            log=None,
        )

        self.assertEqual(self_notice["reason"], "self_notice")
        self.assertFalse(duplicate["followed"])
        self.assertEqual(duplicate["reason"], "duplicate")
        self.assertEqual(mock_set_like.call_count, 1)
        self.assertTrue(first["handled"])

    def test_default_group_config_has_follow_reactions_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = f"{temp_dir}/groups.json"
            save_group_config_store(config_path, {"default": {}})

            store = load_group_config_store(config_path)

            self.assertFalse(store["default"]["follow_group_reactions"])
            self.assertEqual(store["default"]["reaction_follow_probability"], 0.5)

    @patch("apps.qq_ai_bridge.services.reaction_follow_service.set_msg_emoji_like")
    def test_handle_notice_probability_zero_never_follows(self, mock_set_like):
        result = handle_group_reaction_notice(
            {"notice_type": "group_msg_emoji_like", "group_id": 1, "user_id": 2, "message_id": 3, "emoji_id": 339},
            group_config={"follow_group_reactions": True, "reaction_follow_probability": 0},
            self_id=999,
            log=None,
        )

        self.assertTrue(result["handled"])
        self.assertFalse(result["followed"])
        self.assertEqual(result["reason"], "probability_skip")
        mock_set_like.assert_not_called()

    @patch("apps.qq_ai_bridge.services.reaction_follow_service.random.random", return_value=0.73)
    @patch("apps.qq_ai_bridge.services.reaction_follow_service.set_msg_emoji_like")
    def test_handle_notice_probability_skip_records_roll(self, mock_set_like, _mock_random):
        result = handle_group_reaction_notice(
            {"notice_type": "group_msg_emoji_like", "group_id": 1, "user_id": 2, "message_id": 3, "emoji_id": 339},
            group_config={"follow_group_reactions": True, "reaction_follow_probability": 0.5},
            self_id=999,
            log=None,
        )

        self.assertFalse(result["followed"])
        self.assertEqual(result["reason"], "probability_skip")
        self.assertEqual(result["probability"], 0.5)
        self.assertEqual(result["roll"], 0.73)
        mock_set_like.assert_not_called()

    @patch("apps.qq_ai_bridge.services.reaction_follow_service.random.random", return_value=0.49)
    @patch("apps.qq_ai_bridge.services.reaction_follow_service.set_msg_emoji_like")
    def test_handle_notice_probability_hit_follows(self, mock_set_like, _mock_random):
        mock_set_like.return_value = {"ok": True}

        result = handle_group_reaction_notice(
            {"notice_type": "group_msg_emoji_like", "group_id": 1, "user_id": 2, "message_id": 3, "emoji_id": 339},
            group_config={"follow_group_reactions": True, "reaction_follow_probability": 0.5},
            self_id=999,
            log=None,
        )

        self.assertTrue(result["followed"])
        self.assertEqual(result["probability"], 0.5)
        self.assertEqual(result["roll"], 0.49)
        mock_set_like.assert_called_once()


if __name__ == "__main__":
    unittest.main()
