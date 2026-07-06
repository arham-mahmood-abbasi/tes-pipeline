"""Generate worksheet body (concept + questions) via Gemini JSON mode.

Per spec §6.1 each subject cycles through three format profiles, selected by
``day_of_year % 3``. The format profile varies the *concept* style (passage,
diagram, investigation, worked example, and so on) so the daily output stays
fresh, while the question set is fixed: every worksheet carries a full bank of
40 questions split evenly across four types (see :data:`QUESTION_TYPES`).
"""

from __future__ import annotations

import json
from typing import Any

from pipeline import content_cleaner, gemini_api_helper, personas

VALID_SUBJECTS: frozenset[str] = frozenset({"science", "math", "english"})
VALID_FORMAT_PROFILES: frozenset[int] = frozenset({0, 1, 2})

# The four question groups every worksheet must contain, in the order they are
# presented, and how many of each. These are the single source of truth: the
# prompt, the normaliser, the validator, and the PDF renderers all key off them.
QUESTION_TYPES: tuple[str, ...] = ("mcq", "short", "truefalse", "fill")
REQUIRED_PER_TYPE: int = 10

# Human phrasings the model sometimes emits for the ``type`` field. Mapped back
# to our canonical keys so a stray "Multiple Choice" doesn't fail validation.
_TYPE_ALIASES: dict[str, str] = {
    "mcq": "mcq",
    "multiple choice": "mcq",
    "multiple-choice": "mcq",
    "multiplechoice": "mcq",
    "short": "short",
    "short answer": "short",
    "short-answer": "short",
    "free": "short",
    "free-response": "short",
    "truefalse": "truefalse",
    "true/false": "truefalse",
    "true false": "truefalse",
    "true-false": "truefalse",
    "tf": "truefalse",
    "fill": "fill",
    "fill in the blank": "fill",
    "fill-in-the-blank": "fill",
    "fillintheblank": "fill",
    "blank": "fill",
}


_FORMAT_PROFILE_BRIEFS: dict[tuple[str, int], str] = {
    ("science", 0): (
        "Concept overview (150-220 words) explaining the topic clearly with a "
        "real-world example a child would recognise."
    ),
    ("science", 1): (
        "Describe a labelled diagram in words (150-220 words) so students can "
        "picture the parts and how they fit together."
    ),
    ("science", 2): (
        "Investigation style (150-220 words): pose a question, describe a "
        "simple test, and explain what to look out for."
    ),
    ("math", 0): ("Concept overview with one fully worked example, step by step (150-220 words)."),
    ("math", 1): (
        "Explain the topic through real-life word problems (shopping, sport, "
        "cooking) in 150-220 words."
    ),
    ("math", 2): (
        "Concept overview covering the topic's varied operations with short "
        "examples (150-220 words)."
    ),
    ("english", 0): (
        "Short reading passage (180-220 words) that the comprehension questions below will draw on."
    ),
    ("english", 1): ("Grammar focus. Explain the rule clearly with examples (150-220 words)."),
    ("english", 2): (
        "Vocabulary overview: introduce 8-10 target words with their meanings "
        "woven into a 150-220 word explanation."
    ),
}


class ContentGenerationError(RuntimeError):
    """Raised when Gemini fails or returns content that cannot be parsed."""


def profile_for_day(day_of_year: int) -> int:
    """Per spec §6.1 — deterministically pick a profile from the day of the year."""
    return day_of_year % 3


def generate_worksheet_content(
    subject: str,
    topic: str,
    grade: int,
    format_profile: int,
) -> dict:
    """Return a dict with ``concept`` and ``questions`` keys.

    ``questions`` is a list of ``{type, text, options, answer}`` dicts. ``type``
    is one of :data:`QUESTION_TYPES`; ``options`` is a 4-element list of the
    written-out answer choices for ``mcq`` questions and ``None`` for every
    other type. A well-formed worksheet holds :data:`REQUIRED_PER_TYPE` of each
    type (40 questions total); the returned list is normalised toward that shape.
    """
    if subject not in VALID_SUBJECTS:
        raise ValueError(f"subject must be one of {sorted(VALID_SUBJECTS)}; got {subject!r}")
    if format_profile not in VALID_FORMAT_PROFILES:
        raise ValueError(f"format_profile must be 0, 1, or 2; got {format_profile!r}")

    prompt = _build_prompt(subject=subject, topic=topic, grade=grade, format_profile=format_profile)
    result = gemini_api_helper.call_gemini(prompt, json_mode=True)
    if not result.success:
        raise ContentGenerationError(f"Gemini content call failed: {result.error}")

    try:
        payload = json.loads(result.text)
    except json.JSONDecodeError as exc:
        raise ContentGenerationError(f"Gemini returned invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ContentGenerationError(f"Expected JSON object, got {type(payload).__name__}")

    cleaned = content_cleaner.clean_dict(payload)
    raw_questions = cleaned.get("questions")
    cleaned["questions"] = _normalize_questions(
        raw_questions if isinstance(raw_questions, list) else []
    )
    return cleaned


# ---- internal helpers ----------------------------------------------------


def infer_question_type(question: dict[str, Any]) -> str:
    """Map a question to one of :data:`QUESTION_TYPES`.

    Uses the model-supplied ``type`` field (canonicalising common phrasings),
    falling back to structure: anything with options is an MCQ, otherwise it is
    treated as short-answer. Shared with the renderers so the PDF groups the
    same way the validator counts.
    """
    declared = str(question.get("type", "")).strip().lower()
    if declared in _TYPE_ALIASES:
        return _TYPE_ALIASES[declared]
    if question.get("options"):
        return "mcq"
    return "short"


def _normalize_questions(questions: list[Any]) -> list[dict[str, Any]]:
    """Tag every question with a canonical ``type`` and cap each type at 10.

    The model occasionally overshoots (11-12 of a type); trimming the surplus
    keeps a lightly-over response valid instead of forcing a full regenerate.
    Under-counts are left as-is so the validator can catch them and retry.
    """
    normalized: list[dict[str, Any]] = []
    counts: dict[str, int] = dict.fromkeys(QUESTION_TYPES, 0)
    for q in questions:
        if not isinstance(q, dict):
            continue
        qtype = infer_question_type(q)
        if counts.get(qtype, 0) >= REQUIRED_PER_TYPE:
            continue  # trim overshoot for this type
        normalized.append({**q, "type": qtype})
        counts[qtype] = counts.get(qtype, 0) + 1
    return normalized


def _build_prompt(*, subject: str, topic: str, grade: int, format_profile: int) -> str:
    persona_block = personas.get_active_persona()
    grade_label = personas.get_grade_label(grade)
    format_brief = _FORMAT_PROFILE_BRIEFS[(subject, format_profile)]

    task_block = (
        f"Write a {grade_label} {subject} worksheet about the topic: {topic!r}.\n\n"
        f"Concept style for today: {format_brief}\n\n"
        "The worksheet must contain exactly 40 questions, split into four "
        "groups of 10:\n"
        '- 10 multiple-choice questions (type "mcq"), each with exactly 4 '
        "options.\n"
        '- 10 short-answer questions (type "short").\n'
        '- 10 true/false questions (type "truefalse").\n'
        '- 10 fill-in-the-blank questions (type "fill"), each showing the gap '
        "as ____ (four underscores) inside the sentence.\n\n"
        "Output a single JSON object with this exact shape:\n"
        "{\n"
        '  "concept": "<the explanation or passage>",\n'
        '  "questions": [\n'
        '    {"type": "mcq", "text": "<question>", '
        '"options": ["<full answer one>", "<full answer two>", '
        '"<full answer three>", "<full answer four>"], "answer": "<A, B, C or D>"},\n'
        '    {"type": "short", "text": "<question>", "options": null, '
        '"answer": "<expected answer>"},\n'
        '    {"type": "truefalse", "text": "<statement>", "options": null, '
        '"answer": "True or False"},\n'
        '    {"type": "fill", "text": "<sentence with ____ gap>", '
        '"options": null, "answer": "<word that fills the gap>"}\n'
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Exactly 10 questions of each type; 40 in total.\n"
        "- MCQ options must be the real answer choices spelled out in full. "
        'Never use bare letters like "A" as an option, and never prefix an '
        'option with its own letter (no "A) ...", no "B. ...").\n'
        '- Each MCQ "answer" is just the letter (A, B, C or D) of the correct '
        "option.\n"
        "- Every question must have a non-empty answer in the same object.\n"
        "- Do not include any prose outside the JSON object."
    )

    return f"{persona_block}\n\n{task_block}"
