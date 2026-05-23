# tes-pipeline

A daily Cloud Run Job that generates three educational worksheets (Science,
Math, English) for the UK or US market, packages them as upload-ready ZIPs, and
delivers them to a Google Drive folder with a summary email.

## What it does

Once per day, on a Cloud Scheduler cron:

1. Loads the last 60 days of topic history from Google Cloud Storage.
2. For each of Science, Math, English:
   - Picks a fresh topic (Gemini, persona-aware, history-excluded).
   - Generates worksheet content (Gemini, persona-strict, with a rotating
     format profile so daily output stays varied).
   - Validates the content (word counts, question structure, banned phrases,
     em/en-dash bans, market-appropriate spelling, SEO title rules).
   - Generates a cover image (HuggingFace SDXL, with a Pillow fallback).
   - Builds a PDF (WeasyPrint, with a ReportLab fallback).
   - Generates a 420–500 word Tes description.
   - Packages everything as a ZIP containing the PDF, cover image,
     description, and a tags JSON.
3. Uploads the three ZIPs to a shared Google Drive folder.
4. Appends the day's topics to `topic_history.json` in GCS.
5. Sends a Gmail summary with the Drive links.

The user reviews and manually publishes each worksheet to Tes; the pipeline
deliberately does **not** auto-publish.

## Architecture

```
Cloud Scheduler (daily cron)
        │
        ▼
Cloud Run Job (Python 3.12, ~5–8 min per run)
   ├── Gemini      (topic, content, description)
   ├── HF SDXL     (cover image, Pillow fallback)
   ├── WeasyPrint / ReportLab (PDF)
   └── Outputs:
         ├── Google Drive  (daily ZIPs)
         ├── GCS           (topic_history.json + ZIP fallback)
         └── Gmail         (summary email)
```

## Local development

Requires Python 3.12+ and the WeasyPrint system dependencies
([Cairo, Pango, GDK-Pixbuf](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation)).

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
pre-commit install

# Lint + format check
ruff check .
ruff format --check .

cp .env.example .env
# Edit .env with your own values — NEVER commit a populated copy.

pytest
```

## Secrets policy

This repository **must never** contain real API keys, OAuth client secrets, or
service-account JSON files. `.env` is gitignored; `gitleaks` runs in both
`pre-commit` and CI to enforce this.

If you find a leaked secret in this repo or its history, see
[SECURITY.md](SECURITY.md).

## Deployment

The pipeline runs as a Cloud Run Job triggered by Cloud Scheduler. The
container image is built from `Dockerfile` via Cloud Build. The full one-time
GCP setup runbook will land in `docs/gcp-setup.md` as part of Phase 6.

## Project status

Pre-1.0. The repo is being built in phases — see commits on `main` for
progress.

- [x] Phase 0 — Repo bootstrap and security baseline
- [x] Phase 1 — Domain primitives (personas, config, utils, validator)
- [ ] Phase 2 — Content generation (Gemini-backed)
- [ ] Phase 3 — Artifact builders (image, PDF, packager)
- [ ] Phase 4 — Cloud I/O (GCS history, Drive, Gmail)
- [ ] Phase 5 — Orchestration
- [ ] Phase 6 — Containerization and GCP deployment

## Licence

MIT — see [LICENSE](LICENSE).
