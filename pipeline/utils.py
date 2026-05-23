"""Date helpers and filename/title/tag constructors used by the packager."""

from __future__ import annotations

from datetime import UTC, datetime

# Common English stopwords that get stripped when extracting tags from a topic.
STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "for",
        "in",
        "on",
        "to",
        "with",
        "by",
        "at",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "as",
    }
)

_TITLE_HARD_CAP = 70


def today_str() -> str:
    """Today's date as YYYY-MM-DD in UTC."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


def build_zip_filename(subject: str, topic: str, grade: str, date: str) -> str:
    """ZIP filename per spec §8: ``{Subject}_{Topic}_{GradeOrYear}_{YYYY-MM-DD}.zip``.

    Topic is camel-cased and stripped of non-alphanumerics so the result is
    safe on every filesystem.
    """
    return f"{subject}_{_camel_case(topic)}_{grade}_{date}.zip"


def build_title(topic: str, year_or_grade: str, subject: str, sub_keyword: str) -> str:
    """Title per spec §8.2: ``{Topic} Worksheet | {Year/Grade} {Subject} | {Sub-keyword}``.

    Hard-capped at 70 characters; the sub-keyword is truncated first, then
    omitted entirely if the base alone is already at the limit.
    """
    base = f"{topic} Worksheet | {year_or_grade} {subject}"
    separator = " | "
    available = _TITLE_HARD_CAP - len(base) - len(separator)
    if available <= 0:
        return base[:_TITLE_HARD_CAP].rstrip()
    if len(sub_keyword) <= available:
        return f"{base}{separator}{sub_keyword}"
    return f"{base}{separator}{sub_keyword[:available].rstrip()}"


def build_tags(
    topic: str,
    year_or_grade: str,
    subject: str,
    extra_keywords: list[str] | None = None,
    max_tags: int = 8,
) -> list[str]:
    """Tags per spec §8.3.

    Order: topic words (lowercased, stopwords removed) → ``"{year/grade} {subject}"``
    → subject → caller-supplied extras. Duplicates dropped, capped at ``max_tags``.
    """
    tags: list[str] = []

    for raw in topic.lower().split():
        word = "".join(ch for ch in raw if ch.isalnum())
        if word and word not in STOPWORDS:
            _add_unique(tags, word)

    _add_unique(tags, f"{year_or_grade.lower()} {subject.lower()}")
    _add_unique(tags, subject.lower())

    for extra in extra_keywords or []:
        cleaned = extra.lower().strip()
        if cleaned:
            _add_unique(tags, cleaned)

    return tags[:max_tags]


# ---- internal helpers ----------------------------------------------------


def _camel_case(text: str) -> str:
    """``"Adding Fractions"`` → ``"AddingFractions"``; non-alphanumerics are stripped."""
    safe = "".join(ch if ch.isalnum() else " " for ch in text)
    return "".join(word.capitalize() for word in safe.split())


def _add_unique(tags: list[str], value: str) -> None:
    if value not in tags:
        tags.append(value)
