import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.skills.base import SkillContext
from apps.qq_ai_bridge.skills.browser_agent import BrowserAgentSkill


class BrowserAgentSkillTests(unittest.TestCase):
    @patch("apps.qq_ai_bridge.skills.browser_agent.send_private_msg")
    @patch("apps.qq_ai_bridge.skills.browser_agent.run_browser_agent_task")
    def test_private_browser_request_runs_agent_task(self, mock_run, mock_send):
        mock_run.return_value = {
            "status": "completed",
            "reply": "已找到 2 条 DDL。",
            "task": {"task_id": "abc123"},
        }
        skill = BrowserAgentSkill()
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="private",
            user_id=42,
            self_id=1,
            group_id=None,
            group_config={},
            should_log=True,
            msg="帮我去 https://portal.example.edu 找 ddl",
            normalized_msg="帮我去 https://portal.example.edu 找 ddl",
            effective_text="帮我去 https://portal.example.edu 找 ddl",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args, **_kwargs: None,
            timestamp=1,
            message_id=123,
            nick="tester",
            raw_message="帮我去 https://portal.example.edu 找 ddl",
        )

        result = skill.handle(context)

        self.assertTrue(result.handled)
        mock_run.assert_called_once_with(42, "帮我去 https://portal.example.edu 找 ddl", source_skill="browser_agent")
        mock_send.assert_called_once_with(42, "已找到 2 条 DDL。")
        self.assertEqual(result.response_payload["mode"], "browser_agent")


if __name__ == "__main__":
    unittest.main()
