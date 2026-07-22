import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.barrage_6657_service import (
    Barrage6657Store,
    BarrageCandidate,
    BarrageMatcher,
    SyncClient,
    sync_6657_barrages,
)


class FakeHttpClient:
    def __init__(self):
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        if path == "/machine/dictList":
            return {
                "code": 200,
                "data": [
                    {
                        "dictLabel": "NiKo",
                        "dictValue": "07",
                        "dictType": "machine_tags",
                        "iconUrl": "",
                    },
                    {
                        "dictLabel": "DOTA",
                        "dictValue": "17",
                        "dictType": "machine_tags",
                        "iconUrl": "",
                    },
                    {
                        "dictLabel": "群魔乱舞",
                        "dictValue": "06",
                        "dictType": "machine_tags",
                        "iconUrl": "",
                    },
                ],
            }
        if path == "/machine/Page":
            page_num = int((params or {}).get("pageNum", 1))
            pages = {
                1: [
                    {
                        "id": 3,
                        "barrage": "NiKo你说实话，你到底借了多少分",
                        "cnt": "120",
                        "tags": "07",
                        "submitTime": "2026-07-20T10:00:00",
                    },
                    {
                        "id": 2,
                        "barrage": "刀区一哥在播CSGO",
                        "cnt": "30",
                        "tags": "17",
                        "submitTime": "2026-07-19T10:00:00",
                    },
                ],
                2: [
                    {
                        "id": 1,
                        "barrage": "哦？哦？哦？哦？",
                        "cnt": "600",
                        "tags": "06",
                        "submitTime": "2026-07-18T10:00:00",
                    },
                ],
            }
            return {
                "code": 200,
                "data": {
                    "list": pages.get(page_num, []),
                    "total": 3,
                    "lastPage": page_num >= 2,
                },
            }
        if path == "/machine/hotBarrageOf7Day":
            return {
                "code": 200,
                "data": [
                    {
                        "barrageId": "3",
                        "barrage": "NiKo你说实话，你到底借了多少分",
                        "cnt": "8",
                        "tags": "07",
                        "hotDateTime": "2026-07-21T10:00:00",
                    }
                ],
            }
        if path == "/machine/hotBarrageOf24H":
            return {"code": 200, "data": []}
        raise AssertionError(f"unexpected path {path}")


class Barrage6657ServiceTests(unittest.TestCase):
    def test_store_preserves_original_barrage_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Barrage6657Store(os.path.join(tmpdir, "6657.sqlite3"))
            original = "  原封不动\n\n第二段  "

            store.upsert_barrages([{"id": 1, "barrage": original, "cnt": 1, "tags": "07"}])

            with store.connect() as conn:
                saved = conn.execute("select text from barrages where barrage_id = 1").fetchone()[
                    "text"
                ]
            self.assertEqual(saved, original)

    def test_store_reports_library_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Barrage6657Store(os.path.join(tmpdir, "6657.sqlite3"))
            store.upsert_tags([{"dictLabel": "NiKo", "dictValue": "07"}])
            store.upsert_barrages([{"id": 1, "barrage": "原弹幕", "cnt": 1, "tags": "07"}])
            store.upsert_hot_barrages("24h", [{"barrageId": 1, "cnt": 2}])

            stats = store.get_stats()

            self.assertEqual(stats["tags"], 1)
            self.assertEqual(stats["barrages"], 1)
            self.assertEqual(stats["hot_snapshots"], 1)

    def test_send_record_can_be_rolled_back_by_row_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Barrage6657Store(os.path.join(tmpdir, "6657.sqlite3"))
            candidate = BarrageCandidate(
                barrage_id=1,
                text="原弹幕",
                tags=("07",),
                tag_labels=("NiKo",),
                copy_count=1,
            )

            send_log_id = store.record_send(
                group_id=1001,
                candidate=candidate,
                confidence=0.9,
                now=1000,
            )
            store.delete_send(send_log_id=send_log_id)

            self.assertEqual(store.sent_count_since(1001, 0), 0)

    def test_sync_persists_tags_barrages_tag_links_and_hot_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "6657.sqlite3")
            store = Barrage6657Store(db_path)
            stats = sync_6657_barrages(store, SyncClient(FakeHttpClient()), page_size=2)

            self.assertEqual(stats["tags"], 3)
            self.assertEqual(stats["barrages"], 3)
            self.assertEqual(stats["hot_items"], 1)

            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("select count(*) from tags").fetchone()[0], 3)
                self.assertEqual(conn.execute("select count(*) from barrages").fetchone()[0], 3)
                self.assertEqual(conn.execute("select count(*) from barrage_tags").fetchone()[0], 3)
                self.assertEqual(conn.execute("select count(*) from hot_barrages").fetchone()[0], 1)
                copy_count, submit_time = conn.execute(
                    "select copy_count, submit_time from barrages where barrage_id = 3"
                ).fetchone()
                self.assertEqual(copy_count, 120)
                self.assertEqual(submit_time, "2026-07-20T10:00:00")

    def test_matcher_prefers_relevant_tag_candidate_from_recent_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Barrage6657Store(os.path.join(tmpdir, "6657.sqlite3"))
            store.upsert_tags(
                [
                    {
                        "dictLabel": "NiKo",
                        "dictValue": "07",
                        "dictType": "machine_tags",
                        "iconUrl": "",
                    }
                ]
            )
            store.upsert_barrages(
                [
                    {
                        "id": 3,
                        "barrage": "NiKo你说实话，你到底借了多少分",
                        "cnt": "120",
                        "tags": "07",
                        "submitTime": "2026-07-20T10:00:00",
                    },
                    {
                        "id": 4,
                        "barrage": "不相关但复制很多",
                        "cnt": "9999",
                        "tags": "07",
                        "submitTime": "2026-07-20T10:00:00",
                    },
                ]
            )
            matcher = BarrageMatcher(store)

            result = matcher.match(
                "他这个冠军又借到了吗",
                context_lines=["刚刚还在聊 NiKo 决赛"],
                group_config={
                    "enable_6657_barrage": True,
                    "6657_allowed_tags": ["07"],
                    "6657_cooldown_seconds": 0,
                    "6657_daily_limit": 20,
                },
                group_id=1001,
                now=time.time(),
            )

            self.assertTrue(result.matched)
            self.assertEqual(result.candidate.barrage_id, 3)
            self.assertEqual(result.candidate.text, "NiKo你说实话，你到底借了多少分")

    def test_matcher_searches_within_context_tag_instead_of_only_global_top_candidates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Barrage6657Store(os.path.join(tmpdir, "6657.sqlite3"))
            store.upsert_tags(
                [
                    {"dictLabel": "NiKo", "dictValue": "07"},
                    {"dictLabel": "群魔乱舞", "dictValue": "06"},
                ]
            )
            unrelated = [
                {
                    "id": item_id,
                    "barrage": f"不相关热门弹幕{item_id}",
                    "cnt": 10000 + item_id,
                    "tags": "06",
                }
                for item_id in range(1, 306)
            ]
            store.upsert_barrages(
                [
                    *unrelated,
                    {
                        "id": 999,
                        "barrage": "NiKo你说实话，你到底借了多少分",
                        "cnt": 1,
                        "tags": "07",
                    },
                ]
            )

            result = BarrageMatcher(store).match(
                "NiKo这个冠军是不是又借的",
                [],
                {"enable_6657_barrage": True, "6657_cooldown_seconds": 0},
                group_id=1001,
                now=time.time(),
            )

            self.assertTrue(result.matched)
            self.assertEqual(result.candidate.barrage_id, 999)

    def test_matcher_avoids_recently_sent_barrage_when_tag_has_another_candidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Barrage6657Store(os.path.join(tmpdir, "6657.sqlite3"))
            store.upsert_tags([{"dictLabel": "NiKo", "dictValue": "07"}])
            store.upsert_barrages(
                [
                    {"id": 1, "barrage": "NiKo借一分", "cnt": 1000, "tags": "07"},
                    {"id": 2, "barrage": "NiKo你说实话", "cnt": 100, "tags": "07"},
                ]
            )
            matcher = BarrageMatcher(store)
            config = {
                "enable_6657_barrage": True,
                "6657_cooldown_seconds": 0,
                "6657_daily_limit": 20,
            }

            first = matcher.match("NiKo又借冠军", [], config, group_id=1001, now=1000)
            store.record_send(
                group_id=1001,
                candidate=first.candidate,
                confidence=first.confidence,
                now=1000,
            )
            second = matcher.match("NiKo又借冠军", [], config, group_id=1001, now=1001)

            self.assertEqual(first.candidate.barrage_id, 1)
            self.assertTrue(second.matched)
            self.assertEqual(second.candidate.barrage_id, 2)

    def test_matcher_respects_group_switch_cooldown_and_daily_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Barrage6657Store(os.path.join(tmpdir, "6657.sqlite3"))
            store.upsert_tags(
                [
                    {
                        "dictLabel": "NiKo",
                        "dictValue": "07",
                        "dictType": "machine_tags",
                        "iconUrl": "",
                    }
                ]
            )
            store.upsert_barrages(
                [
                    {
                        "id": 3,
                        "barrage": "NiKo你说实话，你到底借了多少分",
                        "cnt": "120",
                        "tags": "07",
                        "submitTime": "2026-07-20T10:00:00",
                    }
                ]
            )
            matcher = BarrageMatcher(store)
            base_config = {
                "enable_6657_barrage": True,
                "6657_min_confidence": 0.2,
                "6657_cooldown_seconds": 240,
                "6657_daily_limit": 1,
            }

            disabled = matcher.match(
                "NiKo借冠军", [], {"enable_6657_barrage": False}, group_id=1001, now=1000
            )
            self.assertFalse(disabled.matched)
            self.assertEqual(disabled.reason, "disabled")

            first = matcher.match("NiKo借冠军", [], base_config, group_id=1001, now=1000)
            self.assertTrue(first.matched)
            store.record_send(
                group_id=1001, candidate=first.candidate, confidence=first.confidence, now=1000
            )

            cooldown = matcher.match("NiKo借冠军", [], base_config, group_id=1001, now=1100)
            self.assertFalse(cooldown.matched)
            self.assertEqual(cooldown.reason, "cooldown")

            daily = matcher.match("NiKo借冠军", [], base_config, group_id=1001, now=1300)
            self.assertFalse(daily.matched)
            self.assertEqual(daily.reason, "daily_limit")


class BarrageCandidateTests(unittest.TestCase):
    def test_candidate_keeps_original_text(self):
        candidate = BarrageCandidate(
            barrage_id=1,
            text="  原封不动  ",
            tags=("07",),
            tag_labels=("NiKo",),
            copy_count=10,
        )

        self.assertEqual(candidate.text, "  原封不动  ")


if __name__ == "__main__":
    unittest.main()
