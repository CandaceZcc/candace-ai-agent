import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")


class AgentRouteServiceTests(unittest.TestCase):
    def test_normal_chat_exposes_no_tools(self):
        from apps.qq_ai_bridge.services.agent_route_service import classify_agent_route

        decision = classify_agent_route("今天有点累，陪我聊两句")

        self.assertEqual(decision.route, "private_chat")
        self.assertEqual(decision.allowed_tool_names, ())

    def test_current_news_exposes_web_search_only(self):
        from apps.qq_ai_bridge.services.agent_route_service import classify_agent_route

        decision = classify_agent_route("查一下今天 OpenAI API 有什么最新消息")

        self.assertEqual(decision.route, "current_events")
        self.assertEqual(decision.allowed_tool_names, ("web_search",))

    def test_explicit_browser_request_exposes_pc_browser_tools_only(self):
        from apps.qq_ai_bridge.services.agent_route_service import classify_agent_route

        decision = classify_agent_route("browser 打开 https://example.com 看看标题")

        self.assertEqual(decision.route, "pc_agent")
        self.assertIn("pc_agent_status", decision.allowed_tool_names)
        self.assertIn("pc_open_http_url", decision.allowed_tool_names)
        self.assertIn("pc_browser_click_text", decision.allowed_tool_names)
        self.assertNotIn("web_search", decision.allowed_tool_names)

    def test_email_command_is_not_routed_to_general_agent(self):
        from apps.qq_ai_bridge.services.agent_route_service import classify_agent_route

        decision = classify_agent_route("邮件 今天")

        self.assertEqual(decision.route, "email_command")
        self.assertFalse(decision.use_general_agent)
        self.assertEqual(decision.allowed_tool_names, ())

    def test_ambiguous_message_does_not_receive_computer_tools(self):
        from apps.qq_ai_bridge.services.agent_route_service import classify_agent_route

        decision = classify_agent_route("帮我看看这个事情怎么处理")

        self.assertEqual(decision.route, "private_chat")
        self.assertEqual(decision.allowed_tool_names, ())


if __name__ == "__main__":
    unittest.main()
