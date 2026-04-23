import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services import browser_agent_service


class BrowserAgentServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tasks_path = Path(self.tmpdir.name) / "browser_tasks.json"
        browser_agent_service._TASKS_CACHE = None

    def tearDown(self):
        browser_agent_service._TASKS_CACHE = None
        self.tmpdir.cleanup()

    def test_run_browser_task_persists_and_summarizes_deadlines(self):
        responses = {
            "open_url": {"action": "open_url", "status": "ok", "data": {"url": "https://portal.example.edu"}},
            "health": {
                "action": "health",
                "status": "ok",
                "data": {"active_tab_url": "https://portal.example.edu/dashboard"},
            },
            "ocr": {
                "action": "ocr",
                "status": "ok",
                "data": {"text": "Dashboard\nAssignments due tomorrow", "source": "page_text"},
            },
            "extract_deadline": {
                "action": "extract_deadline",
                "status": "ok",
                "data": {
                    "count": 1,
                    "items": [
                        {
                            "text": "Assignments due tomorrow",
                            "matched_keyword": "due",
                            "page_title": "Dashboard",
                            "source": "page_text",
                        }
                    ],
                },
            },
        }

        def fake_request(action, params=None, task_id=None):
            return responses[action]

        with patch.object(browser_agent_service, "BROWSER_AGENT_TASKS_PATH", str(self.tasks_path)), patch.object(
            browser_agent_service,
            "request_browser_action",
            side_effect=fake_request,
        ):
            result = browser_agent_service.run_browser_agent_task(
                42,
                "去 https://portal.example.edu 找 ddl",
                source_skill="browser_agent",
            )

        self.assertEqual(result["status"], "completed")
        self.assertIn("已找到 1 条 DDL", result["reply"])
        saved = self.tasks_path.read_text(encoding="utf-8")
        self.assertIn("portal.example.edu", saved)
        self.assertIn("completed", saved)

    def test_cancel_and_continue_use_recent_task(self):
        with patch.object(browser_agent_service, "BROWSER_AGENT_TASKS_PATH", str(self.tasks_path)):
            created = browser_agent_service._new_task(7, "portal ddl", "browser_agent")
            browser_agent_service._update_task(created, status="manual_attention", last_step="manual_attention")

            cancelled = browser_agent_service.run_browser_agent_task(7, "取消任务", source_skill="browser_agent")
            self.assertEqual(cancelled["status"], "cancelled")

            with patch.object(
                browser_agent_service,
                "_run_agent_loop",
                return_value={"status": "completed", "reply": "已恢复并完成。", "task": created},
            ):
                resumed = browser_agent_service.run_browser_agent_task(7, "继续任务", source_skill="browser_agent")

        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["reply"], "已恢复并完成。")


if __name__ == "__main__":
    unittest.main()
