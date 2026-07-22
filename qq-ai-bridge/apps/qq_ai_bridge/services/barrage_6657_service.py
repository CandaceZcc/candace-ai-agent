"""6657 弹幕库的同步、存储、匹配与发送记账。"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import requests

from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR

DEFAULT_6657_DB_PATH = str(Path(BASE_DATA_DIR) / "memes" / "6657.sqlite3")
DEFAULT_6657_BASE_URL = "https://hguofichp.cn:10086"
DEFAULT_PAGE_SIZE = 100
DEFAULT_CONTEXT_MESSAGES = 5
DEFAULT_MIN_CONFIDENCE = 0.45
DEFAULT_COOLDOWN_SECONDS = 240
DEFAULT_DAILY_LIMIT = 20
_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+")
_RISK_PATTERN = re.compile(
    r"(法轮|六四|8964|习近平|炸群|开盒|人肉|身份证|银行卡|自杀教程|爆破群)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BarrageCandidate:
    """A sendable 6657 barrage candidate."""

    barrage_id: int
    text: str
    tags: tuple[str, ...]
    tag_labels: tuple[str, ...]
    copy_count: int
    submit_time: str = ""
    hot_score: int = 0


@dataclass(frozen=True)
class BarrageMatchResult:
    """Result of trying to match one group-chat turn to a 6657 barrage."""

    matched: bool
    reason: str
    candidate: BarrageCandidate | None = None
    confidence: float = 0.0


class RequestsJsonClient:
    """Small JSON GET client for the official sb6657 backend."""

    def __init__(self, *, base_url: str = DEFAULT_6657_BASE_URL, timeout_seconds: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        response = requests.get(url, params=params or {}, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.json()


class SyncClient:
    """Official 6657 API wrapper."""

    def __init__(self, http_client: RequestsJsonClient) -> None:
        self.http_client = http_client

    def fetch_tags(self) -> list[dict[str, Any]]:
        payload = self.http_client.get_json("/machine/dictList")
        _ensure_ok(payload, "/machine/dictList")
        return list(payload.get("data") or [])

    def fetch_page(self, *, page_num: int, page_size: int) -> dict[str, Any]:
        payload = self.http_client.get_json(
            "/machine/Page",
            {"pageNum": int(page_num), "pageSize": int(page_size)},
        )
        _ensure_ok(payload, "/machine/Page")
        return dict(payload.get("data") or {})

    def fetch_hot(self, window: str) -> list[dict[str, Any]]:
        if window == "24h":
            path = "/machine/hotBarrageOf24H"
        elif window == "7d":
            path = "/machine/hotBarrageOf7Day"
        else:
            raise ValueError(f"unsupported hot window: {window}")
        payload = self.http_client.get_json(path)
        _ensure_ok(payload, path)
        return list(payload.get("data") or [])


class Barrage6657Store:
    """SQLite persistence for 6657 barrages and send accounting."""

    def __init__(self, db_path: str = DEFAULT_6657_DB_PATH) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists tags (
                    tag_value text primary key,
                    label text not null,
                    dict_type text not null default '',
                    icon_url text not null default '',
                    updated_at integer not null
                );

                create table if not exists barrages (
                    barrage_id integer primary key,
                    text text not null,
                    copy_count integer not null default 0,
                    submit_time text not null default '',
                    risk_level text not null default 'normal',
                    updated_at integer not null
                );

                create table if not exists barrage_tags (
                    barrage_id integer not null,
                    tag_value text not null,
                    primary key (barrage_id, tag_value)
                );

                create table if not exists hot_barrages (
                    barrage_id integer not null,
                    window text not null,
                    hot_count integer not null default 0,
                    hot_date_time text not null default '',
                    captured_at integer not null,
                    primary key (barrage_id, window, hot_date_time)
                );

                create table if not exists send_log (
                    id integer primary key autoincrement,
                    group_id text not null,
                    barrage_id integer not null,
                    confidence real not null,
                    sent_at integer not null
                );

                create index if not exists idx_barrage_tags_tag on barrage_tags(tag_value);
                create index if not exists idx_barrages_copy on barrages(copy_count desc);
                create index if not exists idx_send_log_group_time on send_log(group_id, sent_at);
                """
            )

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_tags(self, tags: Iterable[dict[str, Any]]) -> int:
        rows = []
        now = int(time.time())
        for item in tags:
            value = str(item.get("dictValue") or "").strip()
            label = str(item.get("dictLabel") or "").strip()
            if not value or not label:
                continue
            rows.append(
                (
                    value,
                    label,
                    str(item.get("dictType") or ""),
                    str(item.get("iconUrl") or ""),
                    now,
                )
            )
        with self.connect() as conn:
            conn.executemany(
                """
                insert into tags(tag_value, label, dict_type, icon_url, updated_at)
                values (?, ?, ?, ?, ?)
                on conflict(tag_value) do update set
                    label=excluded.label,
                    dict_type=excluded.dict_type,
                    icon_url=excluded.icon_url,
                    updated_at=excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def upsert_barrages(
        self,
        barrages: Iterable[dict[str, Any]],
        *,
        preserve_existing: bool = False,
    ) -> int:
        now = int(time.time())
        rows = []
        tag_rows = []
        barrage_ids = []
        for item in barrages:
            barrage_id = _parse_int(item.get("id") or item.get("barrageId"))
            text = str(item.get("barrage") or "")
            if barrage_id <= 0 or not text.strip():
                continue
            tags = _split_tags(item.get("tags"))
            barrage_ids.append((barrage_id,))
            rows.append(
                (
                    barrage_id,
                    text,
                    _parse_int(item.get("cnt")),
                    str(item.get("submitTime") or ""),
                    _risk_level(text),
                    now,
                )
            )
            tag_rows.extend((barrage_id, tag) for tag in tags)
        with self.connect() as conn:
            conn.executemany("delete from barrage_tags where barrage_id = ?", barrage_ids)
            if preserve_existing:
                statement = """
                insert into barrages(
                    barrage_id, text, copy_count, submit_time, risk_level, updated_at
                )
                values (?, ?, ?, ?, ?, ?)
                on conflict(barrage_id) do nothing
                """
            else:
                statement = """
                insert into barrages(
                    barrage_id, text, copy_count, submit_time, risk_level, updated_at
                )
                values (?, ?, ?, ?, ?, ?)
                on conflict(barrage_id) do update set
                    text=excluded.text,
                    copy_count=excluded.copy_count,
                    submit_time=excluded.submit_time,
                    risk_level=excluded.risk_level,
                    updated_at=excluded.updated_at
                """
            conn.executemany(statement, rows)
            conn.executemany(
                "insert or ignore into barrage_tags(barrage_id, tag_value) values (?, ?)",
                tag_rows,
            )
        return len(rows)

    def upsert_hot_barrages(self, window: str, barrages: Iterable[dict[str, Any]]) -> int:
        now = int(time.time())
        hot_rows = []
        for item in barrages:
            barrage_id = _parse_int(item.get("barrageId") or item.get("id"))
            if barrage_id <= 0:
                continue
            hot_rows.append(
                (
                    barrage_id,
                    window,
                    _parse_int(item.get("cnt")),
                    str(item.get("hotDateTime") or ""),
                    now,
                )
            )
        with self.connect() as conn:
            conn.executemany(
                """
                insert or replace into hot_barrages(
                    barrage_id, window, hot_count, hot_date_time, captured_at
                )
                values (?, ?, ?, ?, ?)
                """,
                hot_rows,
            )
        return len(hot_rows)

    def list_candidates(
        self,
        *,
        allowed_tags: Iterable[str] = (),
        blocked_tags: Iterable[str] = (),
        limit: int = 300,
    ) -> list[BarrageCandidate]:
        allowed = tuple(str(tag).strip() for tag in allowed_tags if str(tag).strip())
        blocked = tuple(str(tag).strip() for tag in blocked_tags if str(tag).strip())
        params: list[Any] = []
        where = ["b.risk_level = 'normal'"]
        if allowed:
            placeholders = ",".join("?" for _ in allowed)
            where.append(
                "exists (select 1 from barrage_tags bt "
                "where bt.barrage_id = b.barrage_id "
                f"and bt.tag_value in ({placeholders}))"
            )
            params.extend(allowed)
        if blocked:
            placeholders = ",".join("?" for _ in blocked)
            where.append(
                "not exists (select 1 from barrage_tags bt "
                "where bt.barrage_id = b.barrage_id "
                f"and bt.tag_value in ({placeholders}))"
            )
            params.extend(blocked)
        params.append(max(1, int(limit)))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                select
                    b.barrage_id,
                    b.text,
                    b.copy_count,
                    b.submit_time,
                    coalesce(sum(h.hot_count), 0) as hot_score
                from barrages b
                left join hot_barrages h on h.barrage_id = b.barrage_id
                where {" and ".join(where)}
                group by b.barrage_id
                order by hot_score desc, b.copy_count desc, b.barrage_id desc
                limit ?
                """,
                params,
            ).fetchall()
            return [self._row_to_candidate(conn, row) for row in rows]

    def find_matching_tags(self, text: str) -> tuple[str, ...]:
        normalized = normalize_query_text(text).casefold()
        if not normalized:
            return ()
        with self.connect() as conn:
            rows = conn.execute("select tag_value, label from tags").fetchall()
        return tuple(
            str(row["tag_value"])
            for row in rows
            if len(str(row["label"]).strip()) >= 2
            and str(row["label"]).strip().casefold() in normalized
        )

    def last_sent_at(self, group_id: int | str) -> int | None:
        with self.connect() as conn:
            row = conn.execute(
                "select max(sent_at) as sent_at from send_log where group_id = ?",
                (str(group_id),),
            ).fetchone()
        if not row or row["sent_at"] is None:
            return None
        return int(row["sent_at"])

    def sent_count_since(self, group_id: int | str, since_ts: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "select count(*) as total from send_log where group_id = ? and sent_at >= ?",
                (str(group_id), int(since_ts)),
            ).fetchone()
        return int(row["total"] or 0)

    def recently_sent_ids(self, group_id: int | str, *, limit: int = 20) -> tuple[int, ...]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select barrage_id
                from send_log
                where group_id = ?
                order by sent_at desc, id desc
                limit ?
                """,
                (str(group_id), max(1, int(limit))),
            ).fetchall()
        return tuple(int(row["barrage_id"]) for row in rows)

    def get_stats(self) -> dict[str, int]:
        with self.connect() as conn:
            row = conn.execute(
                """
                select
                    (select count(*) from tags) as tags,
                    (select count(*) from barrages) as barrages,
                    (select count(*) from hot_barrages) as hot_snapshots
                """
            ).fetchone()
        return {
            "tags": int(row["tags"] or 0),
            "barrages": int(row["barrages"] or 0),
            "hot_snapshots": int(row["hot_snapshots"] or 0),
        }

    def record_send(
        self,
        *,
        group_id: int | str,
        candidate: BarrageCandidate,
        confidence: float,
        now: float | None = None,
    ) -> int:
        """预记一次发送并返回日志行 ID，供发送失败时精确回滚。"""
        with self.connect() as conn:
            cursor = conn.execute(
                """
                insert into send_log(group_id, barrage_id, confidence, sent_at)
                values (?, ?, ?, ?)
                """,
                (
                    str(group_id),
                    candidate.barrage_id,
                    float(confidence),
                    int(time.time() if now is None else now),
                ),
            )
            return int(cursor.lastrowid)

    def delete_send(self, *, send_log_id: int) -> None:
        """按行 ID 撤销尚未完成的发送记账。"""
        with self.connect() as conn:
            conn.execute("delete from send_log where id = ?", (int(send_log_id),))

    def _row_to_candidate(self, conn: sqlite3.Connection, row: sqlite3.Row) -> BarrageCandidate:
        tag_rows = conn.execute(
            """
            select bt.tag_value, coalesce(t.label, bt.tag_value) as label
            from barrage_tags bt
            left join tags t on t.tag_value = bt.tag_value
            where bt.barrage_id = ?
            order by bt.tag_value
            """,
            (row["barrage_id"],),
        ).fetchall()
        return BarrageCandidate(
            barrage_id=int(row["barrage_id"]),
            text=str(row["text"]),
            tags=tuple(str(item["tag_value"]) for item in tag_rows),
            tag_labels=tuple(str(item["label"]) for item in tag_rows),
            copy_count=int(row["copy_count"] or 0),
            submit_time=str(row["submit_time"] or ""),
            hot_score=int(row["hot_score"] or 0),
        )


class BarrageMatcher:
    """Pick one 6657 barrage for group-friend-style interjections."""

    def __init__(self, store: Barrage6657Store) -> None:
        self.store = store

    def match(
        self,
        text: str,
        context_lines: Iterable[str] | None,
        group_config: dict[str, Any] | None,
        *,
        group_id: int | str,
        now: float | None = None,
    ) -> BarrageMatchResult:
        cfg = group_config or {}
        if not cfg.get("enable_6657_barrage", False):
            return BarrageMatchResult(matched=False, reason="disabled")
        current = float(now or time.time())
        cooldown = max(0, _parse_int(cfg.get("6657_cooldown_seconds"), DEFAULT_COOLDOWN_SECONDS))
        last_sent_at = self.store.last_sent_at(group_id)
        if last_sent_at is not None and current - last_sent_at < cooldown:
            return BarrageMatchResult(matched=False, reason="cooldown")
        daily_limit = max(0, _parse_int(cfg.get("6657_daily_limit"), DEFAULT_DAILY_LIMIT))
        if (
            daily_limit
            and self.store.sent_count_since(group_id, _start_of_local_day_ts(current))
            >= daily_limit
        ):
            return BarrageMatchResult(matched=False, reason="daily_limit")

        merged_text = "\n".join([*(context_lines or []), text])
        query = normalize_query_text(merged_text).lower()
        allowed_tags = _config_list(cfg.get("6657_allowed_tags"))
        blocked_tags = _config_list(cfg.get("6657_blocked_tags"))
        context_tags = self.store.find_matching_tags(query)
        candidate_tags = context_tags
        if allowed_tags:
            if context_tags:
                allowed_set = set(allowed_tags)
                candidate_tags = tuple(tag for tag in context_tags if tag in allowed_set)
                if not candidate_tags:
                    return BarrageMatchResult(matched=False, reason="tag_not_allowed")
            else:
                candidate_tags = allowed_tags
        candidates = self.store.list_candidates(
            allowed_tags=candidate_tags, blocked_tags=blocked_tags
        )
        if not candidates:
            return BarrageMatchResult(matched=False, reason="empty_library")
        recent_ids = set(self.store.recently_sent_ids(group_id))
        fresh_candidates = [
            candidate for candidate in candidates if candidate.barrage_id not in recent_ids
        ]
        if fresh_candidates:
            candidates = fresh_candidates

        best: tuple[float, BarrageCandidate] | None = None
        for candidate in candidates:
            score = _score_candidate(query, candidate)
            if best is None or score > best[0]:
                best = (score, candidate)
        if best is None:
            return BarrageMatchResult(matched=False, reason="no_candidate")
        min_confidence = _parse_float(cfg.get("6657_min_confidence"), DEFAULT_MIN_CONFIDENCE)
        confidence = min(1.0, best[0])
        if confidence < min_confidence:
            return BarrageMatchResult(
                matched=False, reason="low_confidence", candidate=best[1], confidence=confidence
            )
        return BarrageMatchResult(
            matched=True, reason="matched", candidate=best[1], confidence=confidence
        )


def sync_6657_barrages(
    store: Barrage6657Store | None = None,
    client: SyncClient | None = None,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
) -> dict[str, int]:
    """Synchronize official 6657 tags, barrages and hot snapshots into SQLite."""
    store = store or Barrage6657Store()
    client = client or SyncClient(RequestsJsonClient())
    stats = {"tags": 0, "barrages": 0, "hot_items": 0, "pages": 0}
    stats["tags"] = store.upsert_tags(client.fetch_tags())
    page_num = 1
    while True:
        data = client.fetch_page(page_num=page_num, page_size=page_size)
        items = list(data.get("list") or [])
        if not items:
            break
        stats["barrages"] += store.upsert_barrages(items)
        stats["pages"] += 1
        if data.get("lastPage") or (max_pages is not None and page_num >= max_pages):
            break
        page_num += 1
    for window in ("24h", "7d"):
        hot_items = client.fetch_hot(window)
        store.upsert_barrages(_hot_to_barrage_items(hot_items), preserve_existing=True)
        stats["hot_items"] += store.upsert_hot_barrages(window, hot_items)
    return stats


def sync_6657_barrages_safely(*, max_pages: int | None = None, log=print) -> dict[str, Any]:
    """Best-effort sync wrapper for startup/admin/scheduler paths."""
    try:
        stats = sync_6657_barrages(max_pages=max_pages)
        log(f"[6657] sync_ok {json.dumps(stats, ensure_ascii=False)}")
        return {"ok": True, "stats": stats}
    except Exception as exc:
        log(f"[6657] sync_failed error={exc}")
        return {"ok": False, "error": str(exc)}


def _hot_to_barrage_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        result.append(
            {
                "id": item.get("barrageId") or item.get("id"),
                "barrage": item.get("barrage"),
                "cnt": item.get("cnt"),
                "tags": item.get("tags"),
                "submitTime": item.get("submitTime") or item.get("hotDateTime") or "",
            }
        )
    return result


def _score_candidate(query: str, candidate: BarrageCandidate) -> float:
    tag_hit = any(tag.lower() in query for tag in candidate.tag_labels if len(tag) >= 2)
    text_tokens = set(_tokens(candidate.text))
    query_tokens = set(_tokens(query))
    overlap = len(text_tokens & query_tokens)
    overlap_score = min(0.42, overlap * 0.14)
    tag_score = 0.48 if tag_hit else 0.0
    hot_score = min(0.16, candidate.hot_score / 500.0)
    copy_score = min(0.16, candidate.copy_count / 5000.0)
    direct_text_hit = 0.26 if normalize_query_text(candidate.text).lower() in query else 0.0
    return tag_score + overlap_score + hot_score + copy_score + direct_text_hit


def _tokens(text: str) -> list[str]:
    normalized = normalize_query_text(text).lower()
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(normalized):
        value = match.group(0)
        if re.fullmatch(r"[\u4e00-\u9fff]+", value):
            if len(value) == 1:
                tokens.append(value)
            else:
                tokens.extend(value[index : index + 2] for index in range(len(value) - 1))
        else:
            tokens.append(value)
    return tokens


def _split_tags(raw: Any) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(raw or "").split(",") if item.strip())


def _parse_int(raw: Any, default: int = 0) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _parse_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _config_list(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return tuple(item.strip() for item in raw.split(",") if item.strip())
    if isinstance(raw, (list, tuple, set)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()


def _risk_level(text: str) -> str:
    if len(text) > 700:
        return "too_long"
    if _RISK_PATTERN.search(text):
        return "blocked"
    return "normal"


def _start_of_local_day_ts(now: float) -> int:
    dt = datetime.fromtimestamp(now)
    return int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def _ensure_ok(payload: dict[str, Any], path: str) -> None:
    if payload.get("code") != 200:
        raise RuntimeError(
            f"6657 api failed path={path} code={payload.get('code')} msg={payload.get('msg')}"
        )
