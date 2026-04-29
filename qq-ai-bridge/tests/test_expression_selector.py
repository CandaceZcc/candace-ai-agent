import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.expression_selector import select_group_expression


class ExpressionSelectorTests(unittest.TestCase):
    def test_select_group_expression_rewrites_flat_image_reply(self):
        result = select_group_expression(
            "我看到了",
            "你看看这图",
            group_config={"persona_intensity": 60},
        )

        self.assertNotEqual(result, "")
        self.assertIn(result, {"何意味", "懂你意思", "顺", "？"})


if __name__ == "__main__":
    unittest.main()
