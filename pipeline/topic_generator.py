"""Pick a fresh worksheet topic for a given subject, persona-aware (spec §6.3).

The prompt has three layered blocks: active persona, the task description,
and (when history is non-empty) an exclusion list. The Gemini response is
cleaned and de-noised before being returned to the orchestrator.
"""

from __future__ import annotations

import re

from pipeline import content_cleaner, gemini_api_helper, personas

VALID_SUBJECTS: frozenset[str] = frozenset({"science", "math", "english"})

_SUBJECT_TASK_HINTS: dict[str, str] = {
    "science": (
        "an age-appropriate science topic suitable for a worksheet with a "
        "concept overview and 5 to 8 questions"
    ),
    "math": (
        "an age-appropriate maths topic suitable for a worksheet with a worked "
        "example and 5 to 8 practice problems"
    ),
    "english": (
        "an age-appropriate English/Language Arts topic suitable for a worksheet "
        "with either a reading passage, grammar focus, or vocabulary block"
    ),
}


class TopicGenerationError(RuntimeError):
    """Raised when Gemini fails to return a usable topic."""


def pick_topic(subject: str, grade: int, history: list[str] | None = None) -> str:
    """Return a fresh topic for ``subject`` at ``grade``.

    ``history`` is the list of recent topics for this subject. Anything in it
    (and near-synonyms) must be avoided per spec §6.3.
    """
    if subject not in VALID_SUBJECTS:
        raise ValueError(f"subject must be one of {sorted(VALID_SUBJECTS)}; got {subject!r}")

    prompt = _build_prompt(subject, grade, history or [])
    result = gemini_api_helper.call_gemini(prompt)
    if not result.success:
        raise TopicGenerationError(f"Gemini topic call failed: {result.error}")

    return _clean_topic_response(result.text)


# ---- internal helpers ----------------------------------------------------


def _build_prompt(subject: str, grade: int, history: list[str]) -> str:
    persona_block = personas.get_active_persona()
    grade_label = personas.get_grade_label(grade)
    task_hint = _SUBJECT_TASK_HINTS[subject]

    task_block = (
        f"Pick ONE {task_hint}.\n"
        f"The target audience is {grade_label} (subject: {subject}).\n"
        "Return ONLY the topic name as a single short phrase (3 to 8 words). "
        "No quotes, no numbering, no explanation."
    )

    if not history:
        return f"{persona_block}\n\n{task_block}"

    exclusion_block = (
        "Do not pick a topic from this list, and do not pick a near-synonym "
        "(e.g., if 'Photosynthesis' is in the list, also avoid 'How Plants Make Food'):\n"
        + "\n".join(f"- {topic}" for topic in history)
    )
    return f"{persona_block}\n\n{task_block}\n\n{exclusion_block}"


def _clean_topic_response(text: str) -> str:
    text = content_cleaner.clean_content(text)
    # Take the first non-empty line — sometimes the model adds a second line.
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    # Strip surrounding quotes.
    first_line = first_line.strip().strip('"').strip("'").strip()
    # Strip leading numbering like "1. " or "1) ".
    first_line = re.sub(r"^\d+[.)]\s*", "", first_line)
    # Strip "Topic:" prefix.
    first_line = re.sub(r"^topic:\s*", "", first_line, flags=re.IGNORECASE)
    return first_line.strip()
