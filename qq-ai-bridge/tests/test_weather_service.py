import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.weather_service import build_location_hint, normalize_cn_location


class WeatherServiceTests(unittest.TestCase):
    def test_normalize_chongqing_district(self):
        plan = normalize_cn_location("重庆沙坪坝")
        self.assertEqual(plan.normalized_query, "重庆市沙坪坝区")
        self.assertEqual(plan.candidate_queries[0], "重庆市沙坪坝区")
        self.assertIn("沙坪坝 重庆", plan.candidate_queries)

    def test_normalize_yongchuan_prefers_chongqing(self):
        plan = normalize_cn_location("永川")
        self.assertEqual(plan.guessed_region_bias, "重庆")
        self.assertEqual(plan.candidate_queries[0], "重庆市永川区")
        self.assertIn("永川 重庆", plan.candidate_queries)

    def test_hint_avoids_duplicate_municipality(self):
        self.assertEqual(build_location_hint("重庆沙坪坝"), "重庆市沙坪坝区")
        self.assertEqual(build_location_hint("重庆"), "重庆市")

    def test_beijing_municipality_normalization(self):
        plan = normalize_cn_location("北京市朝阳")
        self.assertEqual(plan.candidate_queries[0], "北京市朝阳区")
        self.assertEqual(build_location_hint("北京市朝阳"), "北京市朝阳区")

    def test_known_non_china_cjk_location_not_forced_to_china(self):
        plan = normalize_cn_location("牛津")
        self.assertFalse(plan.is_china_location)
        self.assertEqual(plan.candidate_queries, ["牛津"])


if __name__ == "__main__":
    unittest.main()
