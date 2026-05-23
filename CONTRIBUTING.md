# Contributing

Thanks for your interest. Until v1.0 ships, contributions are limited to small
fixes and documentation improvements. For larger changes, please open an issue
first to discuss the approach.

## Local development setup

Requires Python 3.12+ and the WeasyPrint system dependencies (Cairo, Pango,
GDK-Pixbuf, `shared-mime-info`).

```bash
git clone <repo-url>
cd tes-pipeline

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
pre-commit install

cp .env.example .env
# Edit .env with your own keys — NEVER commit a populated copy.

pytest
```

## Code style

- `ruff check .` — lint (must pass).
- `ruff format --check .` — format (must pass; run `ruff format .` to fix).
- Type hints encouraged where they aid clarity. Not enforced project-wide.

## Tests

- Tests live in `tests/`.
- External services (Gemini, Drive, Gmail, GCS, HuggingFace) are mocked.
- Do not introduce tests that hit live APIs in CI. If you need one, mark it
  `@pytest.mark.live` and gate execution on an env var.

## Secrets

- No real API keys, OAuth client secrets, or service-account JSON files ever
  land in git. See [SECURITY.md](SECURITY.md).
- `pre-commit` and CI both run `gitleaks`. Both must pass.

## Pull requests

- One logical change per PR. Keep diffs reviewable.
- Open an issue first for anything larger than a small fix or doc tweak — the
  project is still pre-1.0 and design context isn't yet public.
