"""Spec §7 content validation.

Each rule is a pure function that takes a worksheet dict and returns a
``ValidationResult``. ``validate()`` runs them in order and short-circuits
on the first failure, which is the contract the orchestrator relies on to
trigger a regenerate-and-retry loop (spec §14).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pipeline import config, personas


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    failed_check: str | None = None
    excerpt: str | None = None


Worksheet = dict[str, Any]
Check = Callable[[Worksheet], ValidationResult]


# Match en dash (U+2013) or em dash (U+2014); we deliberately want the literal chars.
_EM_OR_EN_DASH_RE = re.compile("[–—]")  # noqa: RUF001
_DESCRIPTION_RANGE = (420, 500)
_CONCEPT_RANGE = (130, 280)
_QUESTION_COUNT_RANGE = (5, 8)
_MCQ_OPTION_COUNT = 4
_TITLE_MAX_LEN = 70
_MARKET_SPELLING_MIN_RATIO = 0.8


# ---- individual checks ---------------------------------------------------


def check_description_word_count(worksheet: Worksheet) -> ValidationResult:
    return _word_count_check(
        worksheet.get("description", ""),
        *_DESCRIPTION_RANGE,
        check_name="description_word_count_in_range",
    )


def check_concept_word_count(worksheet: Worksheet) -> ValidationResult:
    return _word_count_check(
        worksheet.get("concept", ""),
        *_CONCEPT_RANGE,
        check_name="concept_word_count_in_range",
    )


def check_question_count(worksheet: Worksheet) -> ValidationResult:
    qs = worksheet.get("questions", [])
    count = len(qs)
    lo, hi = _QUESTION_COUNT_RANGE
    if lo <= count <= hi:
        return ValidationResult(True)
    return ValidationResult(
        False,
        f"question_count_in_range[{lo},{hi}]",
        f"got {count} questions",
    )


def check_mcq_options(worksheet: Worksheet) -> ValidationResult:
    for i, q in enumerate(worksheet.get("questions", [])):
        options = q.get("options")
        if options is None:
            continue  # free-response, no options expected
        if len(options) != _MCQ_OPTION_COUNT:
            return ValidationResult(
                False,
                "every_mcq_has_4_options",
                f"Q{i + 1} has {len(options)} options",
            )
    return ValidationResult(True)


def check_answer_keys(worksheet: Worksheet) -> ValidationResult:
    for i, q in enumerate(worksheet.get("questions", [])):
        answer = (q.get("answer") or "").strip()
        if not answer:
            return ValidationResult(
                False,
                "every_question_has_answer_in_key",
                f"Q{i + 1} has no answer",
            )
    return ValidationResult(True)


def check_no_banned_phrases(worksheet: Worksheet) -> ValidationResult:
    text = _all_text(worksheet).lower()
    for phrase in personas.BANNED_PHRASES:
        # Word-boundary match so "comprehensive" does not flag "incomprehensible".
        pattern = rf"\b{re.escape(phrase.lower())}\b"
        match = re.search(pattern, text)
        if match:
            idx = match.start()
            excerpt = text[max(0, idx - 20) : idx + len(phrase) + 20]
            return ValidationResult(
                False,
                f"no_banned_phrases[{phrase}]",
                excerpt,
            )
    return ValidationResult(True)


def check_no_em_or_en_dashes(worksheet: Worksheet) -> ValidationResult:
    text = _all_text(worksheet)
    match = _EM_OR_EN_DASH_RE.search(text)
    if match:
        idx = match.start()
        return ValidationResult(
            False,
            "no_em_or_en_dashes",
            text[max(0, idx - 20) : idx + 20],
        )
    return ValidationResult(True)


def check_spellings_match_market(worksheet: Worksheet) -> ValidationResult:
    """At least 80% of distinctive spellings must match the active market."""
    market = config.get_market()
    if market == "UK":
        market_words, opposite_words = personas.UK_SPELLINGS, personas.US_SPELLINGS
    else:
        market_words, opposite_words = personas.US_SPELLINGS, personas.UK_SPELLINGS

    text = _all_text(worksheet).lower()
    market_hits = sum(1 for word in market_words if re.search(rf"\b{word}\b", text))
    opposite_hits = sum(1 for word in opposite_words if re.search(rf"\b{word}\b", text))
    total = market_hits + opposite_hits

    if total == 0:
        return ValidationResult(True)  # nothing distinctive used; neutral.
    if market_hits / total >= _MARKET_SPELLING_MIN_RATIO:
        return ValidationResult(True)
    return ValidationResult(
        False,
        f"spellings_match_market[{market}]",
        f"{market_hits}/{total} market-correct (need >= 80%)",
    )


def check_title_under_70_chars(worksheet: Worksheet) -> ValidationResult:
    title = worksheet.get("title", "")
    if len(title) <= _TITLE_MAX_LEN:
        return ValidationResult(True)
    return ValidationResult(
        False,
        "title_under_70_chars",
        f"length={len(title)}: {title[:60]!r}",
    )


def check_title_starts_with_keyword(worksheet: Worksheet) -> ValidationResult:
    title = worksheet.get("title", "").lower().strip()
    keyword = worksheet.get("keyword", "").lower().strip()
    if not keyword:
        return ValidationResult(True)
    if title.startswith(keyword):
        return ValidationResult(True)
    return ValidationResult(
        False,
        "title_starts_with_keyword",
        f"title={title[:60]!r}, keyword={keyword!r}",
    )


ALL_CHECKS: list[Check] = [
    check_description_word_count,
    check_concept_word_count,
    check_question_count,
    check_mcq_options,
    check_answer_keys,
    check_no_banned_phrases,
    check_no_em_or_en_dashes,
    check_spellings_match_market,
    check_title_under_70_chars,
    check_title_starts_with_keyword,
]


def validate(worksheet: Worksheet) -> ValidationResult:
    """Run every check; return the first failure or ``ValidationResult(passed=True)``."""
    for check in ALL_CHECKS:
        result = check(worksheet)
        if not result.passed:
            return result
    return ValidationResult(True)


# ---- internal helpers ----------------------------------------------------


def _word_count_check(text: str, lo: int, hi: int, *, check_name: str) -> ValidationResult:
    words = len(text.split())
    if lo <= words <= hi:
        return ValidationResult(True)
    return ValidationResult(False, f"{check_name}[{lo},{hi}]", f"got {words} words")


def _all_text(worksheet: Worksheet) -> str:
    """Concatenate every text-bearing field so content-wide checks see it."""
    parts: list[str] = [
        worksheet.get("title", ""),
        worksheet.get("concept", ""),
        worksheet.get("description", ""),
    ]
    for q in worksheet.get("questions", []):
        parts.append(q.get("text", ""))
        for opt in q.get("options") or []:
            parts.append(opt)
        parts.append(q.get("answer", ""))
    return " ".join(parts)
