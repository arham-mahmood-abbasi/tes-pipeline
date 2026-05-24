"""Generate the 420-500 word Tes marketplace description for a worksheet.

Rewritten from v1's ``tes_description.py``:
- Length target raised from 100-150 to 420-500 words (spec §6.2).
- Persona-strict (full persona block prepended; was generic in v1).
- ``Teachers Pay Teachers`` wording removed (spec §17 step 2) — this is for
  the Tes marketplace, not TPT.
"""

from __future__ import annotations

from pipeline import content_cleaner, gemini_api_helper, personas

VALID_SUBJECTS: frozenset[str] = frozenset({"science", "math", "english"})

# Cap how much of the concept body we include in the prompt to keep the prompt
# token count predictable. ~1500 chars is enough for the model to grasp the
# topic without leaking the whole worksheet into the description prompt.
_CONCEPT_PREVIEW_MAX_CHARS = 1500


class DescriptionGenerationError(RuntimeError):
    """Raised when Gemini fails to produce a usable description."""


def generate_description(
    subject: str,
    topic: str,
    grade: int,
    concept_preview: str,
) -> str:
    """Return a 420-500 word description for the Tes listing.

    ``concept_preview`` is the worksheet's concept overview (or a slice of it);
    it primes the model so the description accurately reflects what's inside.
    """
    if subject not in VALID_SUBJECTS:
        raise ValueError(f"subject must be one of {sorted(VALID_SUBJECTS)}; got {subject!r}")

    prompt = _build_prompt(
        subject=subject, topic=topic, grade=grade, concept_preview=concept_preview
    )
    result = gemini_api_helper.call_gemini(prompt)
    if not result.success:
        raise DescriptionGenerationError(f"Gemini description call failed: {result.error}")

    return content_cleaner.clean_content(result.text).strip()


# ---- internal helpers ----------------------------------------------------


def _build_prompt(*, subject: str, topic: str, grade: int, concept_preview: str) -> str:
    persona_block = personas.get_active_persona()
    grade_label = personas.get_grade_label(grade)
    preview = (concept_preview or "")[:_CONCEPT_PREVIEW_MAX_CHARS]

    task_block = (
        f"Write a description for the Tes listing of this worksheet.\n\n"
        f"Subject: {subject}\n"
        f"Topic: {topic}\n"
        f"Year/Grade: {grade_label}\n"
        f"Concept preview (for accuracy, not to quote verbatim):\n"
        f"{preview}\n\n"
        "Length: 420 to 500 words. Stay strictly in that range.\n\n"
        "Tone: conversational, accurate, written in your own voice as the "
        "teacher you are. Open with what the worksheet covers, then describe "
        "the activities (concept overview, question types, answer key), then "
        "say who it's for and how to use it in class. Close with a short line "
        "about why a teacher might find it useful.\n\n"
        "Hard rules:\n"
        "- No em dashes, no en dashes.\n"
        "- No phrases like 'comprehensive', 'delve', 'leverage', 'robust', "
        "'furthermore', 'in conclusion'.\n"
        "- No meta-commentary about the description itself.\n"
        "- No promotional/pricing language.\n"
        "- Output only the description text. No headings, no bullet points, "
        "no labels, no quotes."
    )

    return f"{persona_block}\n\n{task_block}"
