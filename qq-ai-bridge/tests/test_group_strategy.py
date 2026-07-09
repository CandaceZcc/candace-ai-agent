import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.group_strategy import (
    DEFAULT_GROUP_STRATEGY,
    group_strategy_decision,
    normalize_group_strategy_config,
    record_group_strategy_reply,
    reset_group_strategy_state,
)


class GroupStrategyTests(unittest.TestCase):
    def tearDown(self):
        reset_group_strategy_state()

    def test_default_strategy_is_filled(self):
        strategy = normalize_group_strategy_config({})

        self.assertEqual(strategy, DEFAULT_GROUP_STRATEGY)

    def test_default_strategy_keeps_reaction_probability_low(self):
        self.assertEqual(DEFAULT_GROUP_STRATEGY["reaction_probability"], 0.03)

    @patch("apps.qq_ai_bridge.services.group_strategy.random.uniform", return_value=0.95)
    def test_weighted_probability_can_select_reaction_for_non_filler_ambient(self, _mock_random):
        result = group_strategy_decision(
            {"text": "普通聊天", "group_id": "123", "allow_ambient": True},
            {
                "strategy": {
                    "reply_probability": 0.0,
                    "silence_probability": 0.0,
                    "reaction_probability": 1.0,
                }
            },
        )

        self.assertEqual(result["mode"], "reaction")
        self.assertEqual(result["probabilities"]["reaction"], 1.0)

    @patch("apps.qq_ai_bridge.services.group_strategy.random.uniform", return_value=0.95)
    def test_short_filler_global_message_does_not_select_reaction(self, _mock_random):
        result = group_strategy_decision(
            {"text": "哈哈", "group_id": "123", "allow_ambient": True},
            {
                "strategy": {
                    "reply_probability": 0.0,
                    "silence_probability": 0.0,
                    "reaction_probability": 1.0,
                }
            },
        )

        self.assertEqual(result["mode"], "silence")
        self.assertEqual(result["reason"], "ambient_filler_silence")

    def test_require_mention_for_reply_forces_silence(self):
        result = group_strategy_decision(
            {"text": "普通聊天", "group_id": "123", "is_mentioned": False, "allow_ambient": True},
            {"reply_all_messages": True, "strategy": {"require_mention_for_reply": True}},
        )

        self.assertEqual(result["mode"], "silence")
        self.assertEqual(result["reason"], "require_mention_for_reply")

    def test_cooldown_forces_silence(self):
        record_group_strategy_reply("123")

        result = group_strategy_decision(
            {"text": "怎么回事", "group_id": "123", "is_mentioned": True},
            {"strategy": {"cooldown_sec": 5}},
        )

        self.assertEqual(result["mode"], "silence")
        self.assertTrue(result["cooldown_hit"])
        self.assertEqual(result["reason"], "cooldown")

    @patch("apps.qq_ai_bridge.services.group_strategy.random.randint", return_value=900)
    @patch("apps.qq_ai_bridge.services.group_strategy.random.uniform", return_value=0.1)
    def test_delay_uses_configured_range(self, _mock_uniform, mock_randint):
        result = group_strategy_decision(
            {"text": "普通聊天", "group_id": "123", "allow_ambient": True},
            {
                "strategy": {
                    "reply_probability": 1.0,
                    "silence_probability": 0.0,
                    "reaction_probability": 0.0,
                    "delay_min_ms": 500,
                    "delay_max_ms": 1200,
                }
            },
        )

        self.assertEqual(result["mode"], "delay_text")
        self.assertEqual(result["delay_ms"], 900)
        mock_randint.assert_called_once_with(500, 1200)

    def test_mention_only_without_trigger_skips_probability(self):
        result = group_strategy_decision(
            {"text": "普通聊天", "group_id": "123", "allow_ambient": False},
            {
                "reply_all_messages": False,
                "strategy": {
                    "reply_probability": 1.0,
                    "silence_probability": 0.0,
                    "reaction_probability": 0.0,
                },
            },
        )

        self.assertEqual(result["mode"], "silence")
        self.assertEqual(result["reason"], "mention_only_not_triggered")


if __name__ == "__main__":
    unittest.main()
