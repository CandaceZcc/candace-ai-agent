"""Private, manually editable preferences for personalized email triage."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1
_FEEDBACK_ACTION_WEIGHTS = {
    "useful": 5,
    "ignore": -5,
    "ignore_similar": -10,
    "watch_sender": 15,
}
_DEFAULT_INTEREST_TERMS = (
    "computer science",
    "computing",
    "computer department",
    "cst",
    "计算机",
    "计算机系",
    "ai",
    "artificial intelligence",
    "machine learning",
    "large language model",
    "software engineering",
    "web",
    "app",
    "data science",
    "database",
    "cybersecurity",
    "operating system",
    "cloud computing",
    "algorithm",
    "programming contest",
    "robotics",
    "robot",
    "embedded",
    "iot",
    "automation",
    "人工智能",
    "机器学习",
    "大模型",
    "软件工程",
    "数据科学",
    "数据库",
    "网络安全",
    "操作系统",
    "云计算",
    "算法",
    "编程竞赛",
    "机器人",
    "嵌入式",
    "物联网",
    "自动化",
)
_DEFAULT_COHORT_TERMS = (
    "year 3",
    "third year",
    "2024 cohort",
    "大三",
    "2024级",
)
_DEFAULT_NEGATIVE_TERMS = (
    "campus recruitment",
    "graduate recruitment",
    "generic internship",
    "校招",
    "招聘会",
)


@dataclass(frozen=True)
class EmailPreferenceProfile:
    profile_version: int
    watched_senders: tuple[str, ...]
    ignored_senders: tuple[str, ...]
    watched_domains: tuple[str, ...]
    ignored_domains: tuple[str, ...]
    positive_terms: tuple[str, ...]
    negative_terms: tuple[str, ...]
    interest_terms: tuple[str, ...]
    cohort_terms: tuple[str, ...]
    hard_ignore_rules: tuple[str, ...]
    manual_adjustments: tuple[tuple[str, int], ...]
    learned_adjustments: tuple[tuple[str, int], ...]

    def score_for(self, signal: str) -> int:
        normalized = str(signal or "").strip().lower()
        manual = dict(self.manual_adjustments)
        if normalized in manual:
            return manual[normalized]
        return dict(self.learned_adjustments).get(normalized, 0)


class EmailPreferenceStore:
    def __init__(self, profile_path: str | Path, feedback_path: str | Path) -> None:
        self.profile_path = Path(profile_path).expanduser().resolve()
        self.feedback_path = Path(feedback_path).expanduser().resolve()
        self.last_error_code: str | None = None
        self._last_valid: EmailPreferenceProfile | None = None

    def load(self) -> EmailPreferenceProfile:
        self._ensure_files()
        try:
            manual = _load_json_object(self.profile_path)
            learned = _load_json_object(self.feedback_path)
            profile = _build_profile(manual, learned)
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError, KeyError):
            self.last_error_code = "invalid_profile"
            if self._last_valid is not None:
                return self._last_valid
            profile = _build_profile(_default_profile_payload(), _default_feedback_payload())
        self.last_error_code = None
        self._last_valid = profile
        return profile

    def summary(self) -> str:
        profile = self.load()
        feedback = _safe_feedback_records(self.feedback_path)
        return (
            f"邮件偏好版本：{profile.profile_version}\n"
            f"关注发件人：{len(profile.watched_senders)}\n"
            f"忽略发件人：{len(profile.ignored_senders)}\n"
            f"兴趣词：{len(profile.interest_terms)}\n"
            f"已学习反馈：{len(feedback)}"
        )

    def apply_feedback(self, alias: str, action: str, signals: dict[str, str]) -> None:
        normalized_alias = str(alias or "").strip().upper()
        normalized_action = str(action or "").strip().lower()
        if not re.fullmatch(r"E-\d{4,}", normalized_alias):
            raise ValueError("invalid email alias")
        if normalized_action not in _FEEDBACK_ACTION_WEIGHTS:
            raise ValueError("unsupported email feedback action")
        normalized_signals = {
            str(key).strip().lower(): str(value).strip().lower()
            for key, value in dict(signals or {}).items()
            if str(key).strip() and str(value).strip()
        }
        self._ensure_files()
        payload = _load_json_object(self.feedback_path)
        records = payload.setdefault("feedback", {})
        if not isinstance(records, dict):
            raise ValueError("invalid feedback records")
        records[normalized_alias] = {
            "action": normalized_action,
            "signals": normalized_signals,
        }
        _atomic_write_json(self.feedback_path, payload)

    def undo_feedback(self, alias: str) -> bool:
        normalized_alias = str(alias or "").strip().upper()
        self._ensure_files()
        payload = _load_json_object(self.feedback_path)
        records = payload.get("feedback", {})
        if not isinstance(records, dict) or normalized_alias not in records:
            return False
        del records[normalized_alias]
        _atomic_write_json(self.feedback_path, payload)
        return True

    def _ensure_files(self) -> None:
        if not self.profile_path.exists():
            _atomic_write_json(self.profile_path, _default_profile_payload())
        else:
            os.chmod(self.profile_path, 0o600)
        if not self.feedback_path.exists():
            _atomic_write_json(self.feedback_path, _default_feedback_payload())
        else:
            os.chmod(self.feedback_path, 0o600)


def _default_profile_payload() -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "profile_version": 1,
        "watched_senders": [],
        "ignored_senders": [],
        "watched_domains": [],
        "ignored_domains": [],
        "positive_terms": [],
        "negative_terms": list(_DEFAULT_NEGATIVE_TERMS),
        "interest_terms": list(_DEFAULT_INTEREST_TERMS),
        "cohort_terms": list(_DEFAULT_COHORT_TERMS),
        "hard_ignore_rules": [],
        "score_adjustments": {},
    }


def _default_feedback_payload() -> dict[str, Any]:
    return {"schema_version": _SCHEMA_VERSION, "feedback": {}}


def _build_profile(manual: dict[str, Any], learned: dict[str, Any]) -> EmailPreferenceProfile:
    if manual.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported profile schema")
    if learned.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported feedback schema")
    manual_adjustments = _normalize_adjustments(manual.get("score_adjustments", {}))
    learned_adjustments = _learned_adjustments(learned.get("feedback", {}))
    return EmailPreferenceProfile(
        profile_version=max(1, int(manual.get("profile_version", 1))),
        watched_senders=_normalize_strings(manual.get("watched_senders", [])),
        ignored_senders=_normalize_strings(manual.get("ignored_senders", [])),
        watched_domains=_normalize_strings(manual.get("watched_domains", [])),
        ignored_domains=_normalize_strings(manual.get("ignored_domains", [])),
        positive_terms=_normalize_strings(manual.get("positive_terms", [])),
        negative_terms=_normalize_strings(manual.get("negative_terms", [])),
        interest_terms=_normalize_strings(manual.get("interest_terms", [])),
        cohort_terms=_normalize_strings(manual.get("cohort_terms", [])),
        hard_ignore_rules=_normalize_strings(manual.get("hard_ignore_rules", [])),
        manual_adjustments=tuple(sorted(manual_adjustments.items())),
        learned_adjustments=tuple(sorted(learned_adjustments.items())),
    )


def _normalize_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("profile string collection must be a list")
    return tuple(
        dict.fromkeys(str(item).strip().lower() for item in value if str(item).strip())
    )


def _normalize_adjustments(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("score_adjustments must be an object")
    return {
        str(key).strip().lower(): max(-20, min(20, int(score)))
        for key, score in value.items()
        if str(key).strip()
    }


def _learned_adjustments(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("feedback must be an object")
    totals: dict[str, int] = {}
    for record in value.values():
        if not isinstance(record, dict):
            continue
        action = str(record.get("action", "")).strip().lower()
        weight = _FEEDBACK_ACTION_WEIGHTS.get(action)
        signals = record.get("signals", {})
        if weight is None or not isinstance(signals, dict):
            continue
        for key, signal_value in signals.items():
            signal = f"{str(key).strip().lower()}:{str(signal_value).strip().lower()}"
            if signal.endswith(":"):
                continue
            totals[signal] = max(-20, min(20, totals.get(signal, 0) + weight))
    return totals


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object")
    return payload


def _safe_feedback_records(path: Path) -> dict[str, Any]:
    try:
        payload = _load_json_object(path)
        records = payload.get("feedback", {})
        return records if isinstance(records, dict) else {}
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temp_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()


__all__ = ["EmailPreferenceProfile", "EmailPreferenceStore"]
