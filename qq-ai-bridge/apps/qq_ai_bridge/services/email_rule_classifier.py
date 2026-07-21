"""Explainable local scoring before semantic email classification."""

from __future__ import annotations

import re
from email.utils import parseaddr

from apps.qq_ai_bridge.services.email_models import EmailEnvelope, EmailRuleDecision
from apps.qq_ai_bridge.services.email_preference_service import EmailPreferenceProfile

_ACADEMIC_ACTION_TERMS = (
    "exam",
    "quiz",
    "course change",
    "class change",
    "room changed",
    "deadline",
    "please confirm",
    "please submit",
    "考试",
    "测验",
    "课程调整",
    "教室变更",
    "截止",
    "请确认",
    "请提交",
)
_RESEARCH_COMPETITION_TERMS = (
    "research",
    "competition",
    "contest",
    "hackathon",
    "challenge",
    "科研",
    "竞赛",
    "比赛",
    "大赛",
)
_GENERIC_RECRUITING_TERMS = (
    "campus recruitment",
    "graduate recruitment",
    "career fair",
    "generic internship",
    "校招",
    "招聘会",
    "实习推广",
)
_ROUTINE_EVENT_TERMS = (
    "weekly campus activity",
    "activity newsletter",
    "event newsletter",
    "annual gathering",
    "校园活动周报",
    "例行活动通知",
)
_MASS_MAIL_TERMS = (
    "all students",
    "mailing list",
    "unsubscribe",
    "群发",
    "退订",
)


class EmailRuleClassifier:
    def __init__(self, *, owner_address: str, max_body_chars: int = 4000) -> None:
        self._owner_address = str(owner_address or "").strip().lower()
        self._max_body_chars = max(0, int(max_body_chars))

    def classify(
        self,
        envelope: EmailEnvelope,
        profile: EmailPreferenceProfile,
    ) -> EmailRuleDecision:
        sender_address = parseaddr(str(envelope.sender or ""))[1].strip().lower()
        sender_domain = sender_address.rsplit("@", 1)[-1] if "@" in sender_address else ""
        subject = _normalize(envelope.subject)
        body = _normalize(str(envelope.body_text or "")[: self._max_body_chars])
        combined = " ".join(part for part in (subject, body) if part)
        is_generic_recruiting = _contains_any(combined, _GENERIC_RECRUITING_TERMS)
        is_routine_event = _contains_any(combined, _ROUTINE_EVENT_TERMS)
        is_mass_mail = _contains_any(combined, _MASS_MAIL_TERMS)
        recipients = {str(value).strip().lower() for value in envelope.recipients}
        is_broad_recipient = len(recipients) > 3 or any(
            re.search(
                r"(?:^|[-_.])(all|students|staff|faculty|announce|newsletter)(?:[-_.@]|$)",
                value,
            )
            for value in recipients
        )

        if _matches_explicit_ignore(sender_address, sender_domain, combined, profile):
            return EmailRuleDecision(0, "explicit_hard_ignore", (), ("explicit_hard_ignore",))

        score = 35
        positive: list[str] = []
        negative: list[str] = []
        categories: set[str] = set()

        if re.match(r"^\s*(?:re|aw|sv)\s*:", str(envelope.subject or ""), re.IGNORECASE):
            positive.append("direct_reply")
            score += 25

        if re.search(r"(?:^| )(?:from:|发件人[:：]|on .+ wrote:)", body, re.IGNORECASE):
            positive.append("reply_thread")
            score += 20

        if (
            self._owner_address
            and self._owner_address in recipients
            and not (
                is_generic_recruiting
                or is_routine_event
                or is_mass_mail
                or is_broad_recipient
            )
        ):
            positive.append("direct_recipient")
            score += 15

        if sender_address in profile.watched_senders:
            positive.append("watched_sender")
            score += 25
        if sender_domain in profile.watched_domains:
            positive.append("watched_domain")
            score += 20

        matched_interests = _matched_terms(combined, profile.interest_terms)
        if matched_interests:
            positive.extend(f"interest:{term}" for term in matched_interests[:4])
            score += 25
            categories.update(_interest_categories(matched_interests))

        matched_cohorts = _matched_terms(combined, profile.cohort_terms)
        if matched_cohorts:
            positive.extend(f"cohort:{term}" for term in matched_cohorts[:3])
            score += 20
            categories.add("cohort")

        if re.search(r"(?<![a-z])[a-z]{2,5}\s*\d{3,4}(?!\d)", subject, re.IGNORECASE):
            positive.append("course_code")
            score += 15
            categories.add("academic_action")

        if _contains_any(combined, _ACADEMIC_ACTION_TERMS):
            positive.append("academic_action")
            score += 25
            categories.add("academic_action")

        if _contains_any(combined, _RESEARCH_COMPETITION_TERMS):
            positive.append("research_competition")
            score += 20
            categories.add("research")

        matched_positive = _matched_terms(combined, profile.positive_terms)
        if matched_positive:
            positive.extend(f"profile_positive:{term}" for term in matched_positive[:3])
            score += 15

        if is_generic_recruiting:
            negative.append("generic_recruiting")
            score -= 25
            categories.add("recruiting")
        if is_routine_event:
            negative.append("routine_event")
            score -= 20
            categories.add("routine_event")
        if is_mass_mail:
            negative.append("mass_mail")
            score -= 20
        if is_broad_recipient and not is_mass_mail:
            negative.append("broad_recipient")
            score -= 20

        matched_negative = _matched_terms(combined, profile.negative_terms)
        if matched_negative:
            negative.extend(f"profile_negative:{term}" for term in matched_negative[:3])
            score -= 15

        score = _apply_profile_adjustments(
            score,
            positive,
            negative,
            sender_address=sender_address,
            sender_domain=sender_domain,
            categories=categories,
            profile=profile,
        )
        bounded_score = max(0, min(100, score))
        eligibility = (
            "deterministic_low_value"
            if len(negative) >= 2 and not positive and bounded_score <= 25
            else "semantic_required"
        )
        return EmailRuleDecision(
            bounded_score,
            eligibility,
            tuple(dict.fromkeys(positive)),
            tuple(dict.fromkeys(negative)),
        )


def _matches_explicit_ignore(
    sender_address: str,
    sender_domain: str,
    combined: str,
    profile: EmailPreferenceProfile,
) -> bool:
    if sender_address and sender_address in profile.ignored_senders:
        return True
    if sender_domain and sender_domain in profile.ignored_domains:
        return True
    return any(rule in combined for rule in profile.hard_ignore_rules)


def _apply_profile_adjustments(
    score: int,
    positive: list[str],
    negative: list[str],
    *,
    sender_address: str,
    sender_domain: str,
    categories: set[str],
    profile: EmailPreferenceProfile,
) -> int:
    signals = []
    if sender_address:
        signals.append(("sender", sender_address))
    if sender_domain:
        signals.append(("domain", sender_domain))
    signals.extend(("category", category) for category in sorted(categories))
    for kind, value in signals:
        adjustment = profile.score_for(f"{kind}:{value}")
        if not adjustment:
            continue
        score += adjustment
        target = positive if adjustment > 0 else negative
        target.append(f"profile_adjustment:{kind}")
    return score


def _interest_categories(terms: tuple[str, ...]) -> set[str]:
    categories: set[str] = set()
    joined = " ".join(terms)
    if any(term in joined for term in ("robot", "机器人")):
        categories.add("robotics")
    if any(term in joined for term in ("embedded", "嵌入式")):
        categories.add("embedded")
    if any(term in joined for term in ("ai", "machine learning", "人工智能", "机器学习")):
        categories.add("ai")
    if not categories:
        categories.add("computer_science")
    return categories


def _matched_terms(value: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term for term in terms if _term_matches(value, term))


def _term_matches(value: str, term: str) -> bool:
    normalized = _normalize(term)
    if not normalized:
        return False
    if normalized.isascii() and len(normalized) <= 3:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", value))
    return normalized in value


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(_term_matches(value, term) for term in terms)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


__all__ = ["EmailRuleClassifier"]
