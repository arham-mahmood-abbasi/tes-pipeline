"""Generate worksheet body (concept + questions) via Gemini JSON mode.

Per spec §6.1 each subject cycles through three format profiles, selected by
``day_of_year % 3``. The format profile materially changes the structure of
the worksheet the model is asked to produce, so the daily output stays varied
even though the persona and task scaffolding are fixed.
"""

from __future__ import annotations

import json

from pipeline import content_cleaner, gemini_api_helper, personas

VALID_SUBJECTS: frozenset[str] = frozenset({"science", "math", "english"})
VALID_FORMAT_PROFILES: frozenset[int] = frozenset({0, 1, 2})


_FORMAT_PROFILE_BRIEFS: dict[tuple[str, int], str] = {
    ("science", 0): (
        "Concept overview (150-250 words) followed by 5-8 applied questions "
        "(mix of MCQs with 4 options and short-answer)."
    ),
    ("science", 1): (
        "Describe a diagram in words, then ask students to label parts or "
        "predict what happens; 5-8 questions, mostly short-answer."
    ),
    ("science", 2): (
        "Investigation style: pose a hypothesis, describe a simple test, ask "
        "students to predict, test, and explain. 5-8 questions, mostly "
        "short-answer."
    ),
    ("math", 0): (
        "One worked example followed by 5-8 practice problems progressing "
        "from easier to harder. Mix of MCQs with 4 options and calculation "
        "problems."
    ),
    ("math", 1): (
        "Word problems only. 5-8 problems anchored in real-life scenarios "
        "(shopping, sport, cooking). Show your working space."
    ),
    ("math", 2): (
        "Mixed review across the topic's varied operations. 5-8 questions, "
        "mix of calculation and multiple choice."
    ),
    ("english", 0): (
        "Short reading passage (200-250 words) followed by 5-8 comprehension "
        "questions. Mix of MCQs with 4 options and short-answer."
    ),
    ("english", 1): (
        "Grammar focus. Explain the rule in 150-200 words, then 5-8 practice "
        "items (identify, correct, fill the blank)."
    ),
    ("english", 2): (
        "Vocabulary block (8-10 target words with definitions and example "
        "sentences) followed by 5-8 questions including one creative-writing "
        "prompt."
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

    ``questions`` is a list of ``{text, options, answer}`` dicts where
    ``options`` is either a 4-element list (MCQ) or ``None`` (free-response).
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

    return content_cleaner.clean_dict(payload)


# ---- internal helpers ----------------------------------------------------


def _build_prompt(*, subject: str, topic: str, grade: int, format_profile: int) -> str:
    persona_block = personas.get_active_persona()
    grade_label = personas.get_grade_label(grade)
    format_brief = _FORMAT_PROFILE_BRIEFS[(subject, format_profile)]

    task_block = (
        f"Write a {grade_label} {subject} worksheet about the topic: {topic!r}.\n\n"
        f"Format profile for today: {format_brief}\n\n"
        "Output a single JSON object with this exact shape:\n"
        "{\n"
        '  "concept": "<the explanation or passage>",\n'
        '  "questions": [\n'
        '    {"text": "<question>", "options": ["A","B","C","D"], "answer": "<letter>"},\n'
        '    {"text": "<short-answer question>", "options": null, "answer": "<expected answer>"}\n'
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- 5 to 8 questions total.\n"
        "- Every MCQ must have exactly 4 options.\n"
        "- Every question must have a non-empty answer in the same object.\n"
        "- Do not include any prose outside the JSON object."
    )

    return f"{persona_block}\n\n{task_block}"
