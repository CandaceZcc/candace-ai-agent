import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.email_preference_service import EmailPreferenceStore


class EmailPreferenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.profile_path = root / "profile.json"
        self.feedback_path = root / "learned-feedback.json"
        self.store = EmailPreferenceStore(self.profile_path, self.feedback_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_profile_contains_approved_interests(self):
        profile = self.store.load()

        for term in ("computer science", "ai", "robotics", "embedded", "year 3", "2024级"):
            self.assertIn(term, profile.interest_terms + profile.cohort_terms)
        self.assertEqual(profile.profile_version, 1)

    def test_private_files_use_mode_0600(self):
        self.store.load()

        self.assertEqual(stat.S_IMODE(self.profile_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.feedback_path.stat().st_mode), 0o600)

    def test_manual_adjustment_overrides_learned_weight(self):
        self.store.load()
        payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
        payload["score_adjustments"] = {"category:research": 18}
        self.profile_path.write_text(json.dumps(payload), encoding="utf-8")
        self.store.apply_feedback(
            "E-1042",
            "ignore",
            {"category": "research"},
        )

        profile = self.store.load()

        self.assertEqual(profile.score_for("category:research"), 18)

    def test_invalid_manual_file_keeps_last_valid_profile(self):
        valid = self.store.load()
        self.profile_path.write_text("{broken-json", encoding="utf-8")

        fallback = self.store.load()

        self.assertEqual(fallback, valid)
        self.assertEqual(self.store.last_error_code, "invalid_profile")

    def test_feedback_weights_are_bounded(self):
        self.store.load()
        for number in range(20):
            self.store.apply_feedback(
                f"E-{2000 + number}",
                "useful",
                {"category": "robotics"},
            )

        profile = self.store.load()

        self.assertEqual(profile.score_for("category:robotics"), 20)

    def test_feedback_can_be_reversed(self):
        self.store.load()
        self.store.apply_feedback(
            "E-1042",
            "ignore",
            {"domain": "example.invalid", "category": "routine_event"},
        )
        self.assertLess(self.store.load().score_for("category:routine_event"), 0)

        removed = self.store.undo_feedback("E-1042")

        self.assertTrue(removed)
        self.assertEqual(self.store.load().score_for("category:routine_event"), 0)
        self.assertFalse(self.store.undo_feedback("E-1042"))

    def test_ignore_similar_remains_reversible_and_is_not_hard_ignore(self):
        self.store.load()
        self.store.apply_feedback(
            "E-1042",
            "ignore_similar",
            {"category": "routine_event"},
        )

        profile = self.store.load()

        self.assertLess(profile.score_for("category:routine_event"), 0)
        self.assertEqual(profile.hard_ignore_rules, ())

    def test_summary_returns_counts_without_private_values(self):
        self.store.load()
        payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
        payload["watched_senders"] = ["private-person@example.invalid"]
        self.profile_path.write_text(json.dumps(payload), encoding="utf-8")

        summary = self.store.summary()

        self.assertIn("关注发件人：1", summary)
        self.assertNotIn("private-person", summary)
        self.assertNotIn("example.invalid", summary)


if __name__ == "__main__":
    unittest.main()
