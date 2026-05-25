# Operations runbook

How to deploy, run, change, and debug the daily worksheet pipeline.

## Architecture (one paragraph)

A GitHub Actions cron workflow (`.github/workflows/daily.yml`) runs once per
day on a fresh `ubuntu-latest` runner. It checks out this repo, installs
Python + WeasyPrint system deps, runs `python -m pipeline.pipeline`, commits
the updated `state/topic_history.json` back to the repo (with `[skip ci]`),
and uploads the generated ZIPs as a workflow artifact. The pipeline itself
emails the three ZIPs as attachments via Gmail SMTP. No cloud storage, no
service accounts, no billing.

## First-time deployment

### 1. Add secrets to GitHub

Repository → Settings → Secrets and variables → Actions → "New repository
secret". Add each of these:

| Secret | Required? | Where to get it |
|---|---|---|
| `GEMINI_API_KEY` | Yes | https://aistudio.google.com/app/apikey |
| `GMAIL_SENDER` | Yes | Your Gmail address |
| `GMAIL_RECIPIENT` | Yes | Where the daily email lands (can be the same as sender) |
| `GMAIL_APP_PASSWORD` | Yes | https://myaccount.google.com/apppasswords (requires 2FA on) |
| `FALLBACK_GEMINI_API_KEY` | Optional | A second Gemini key for rate-limit fallback |
| `HUGGINGFACE_API_KEY` | Optional | https://huggingface.co/settings/tokens — for SDXL cover images |
| `PEXELS_API_KEY` | Optional | https://www.pexels.com/api/ — for stock-photo cover fallback |

### 2. Enable workflow write permissions

Repository → Settings → Actions → General → "Workflow permissions" →
**"Read and write permissions"**. This lets the workflow commit
`topic_history.json` back to `main` after each run. (Without this, the
final commit step fails with `403 — Resource not accessible by integration`.)

### 3. Test it manually before the first cron fires

Repository → Actions → "Daily worksheet run" → "Run workflow" → "Run
workflow" button. Wait ~6 minutes. You should see:

- Green checkmark on the workflow run
- Email in your inbox with three ZIP attachments
- A new commit on `main`: `chore: update topic history [skip ci]`
- An artifact "worksheets-<run-id>" downloadable from the run page

If anything fails, see [Troubleshooting](#troubleshooting) below.

## Daily flow (what should happen each day)

1. **06:00 UTC** — cron fires; workflow starts.
2. **~6 minutes** — pipeline runs:
   - Loads `state/topic_history.json` (excludes recent topics)
   - For each of Science / Math / English:
     - Picks a fresh topic (Gemini)
     - Generates worksheet content (Gemini)
     - Generates cover image (HF → Pexels → Pillow fallback chain)
     - Generates a 420–500 word description (Gemini)
     - Builds the ZIP (worksheet.pdf + cover.png + description.txt + tags.json)
3. **Email** lands in your inbox with the three ZIPs attached.
4. **You** download each ZIP, upload to Tes manually.

## Changing things

### Change the run time

Edit `.github/workflows/daily.yml`, change the `cron:` line. Cron is in
**UTC** — convert from your local timezone. Examples:

- 06:00 UK time (BST, summer): `cron: "0 5 * * *"`
- 06:00 PKT (UTC+5): `cron: "0 1 * * *"`
- 06:00 AEDT (UTC+11): `cron: "0 19 * * *"`  (yesterday 19:00 UTC)

Commit and push — the new schedule takes effect on the next interval.

### Change the price

`PAID_PRICE_GBP` is set in the workflow's `env:` block, not in secrets.
Edit `.github/workflows/daily.yml` and bump the value. Default `0.0` ships
free; set to `2.50` when you're ready to charge.

### Change the market (UK ↔ US persona)

Same place — `MARKET: UK` in the workflow env. Flip to `MARKET: US` for
US persona + Grade naming + spellings.

### Change the default grade

The pipeline defaults to Grade 6. For a one-off run at a different grade,
trigger the workflow manually and fill in the "Grade override" input. For
a permanent change, edit `DEFAULT_GRADE` in `pipeline/pipeline.py`.

### Rotate a secret

1. Generate a new key from the relevant provider (Google AI Studio, HF,
   Pexels, or new Gmail app password).
2. GitHub → Settings → Secrets and variables → Actions → click the
   secret name → "Update".
3. Next workflow run uses the new value automatically.
4. Revoke the old key in the provider's console once you've confirmed
   the new one works.

## Troubleshooting

### CI workflow run is red

Click the failed run → click the failing step → read the logs. Match
against this table:

| Error keyword in logs | Likely cause | Fix |
|---|---|---|
| `GMAIL_APP_PASSWORD is not set` | Secret missing or misspelled in repo settings | Re-add the secret, exact spelling |
| `Username and Password not accepted` | App password wrong / 2FA disabled | Generate a new app password; confirm 2FA is on |
| `403 ... Resource not accessible by integration` | Workflow can't push to repo | Enable "Read and write permissions" (Step 2 above) |
| `Gemini content call failed: rate limit` | Daily quota hit (rare on free tier) | Wait 24 hours; or add `FALLBACK_GEMINI_API_KEY` |
| `Gemini returned invalid JSON` | Model output wasn't parseable (transient) | Re-run manually; if it persists, prompt may need tuning |
| `WeasyPrint failed to render` | Cairo/Pango system dep issue | Should never happen on `ubuntu-latest`; if so, the apt-get step regressed |
| `HF returned status 503` repeatedly | HuggingFace SDXL endpoint cold/down | Pexels or Pillow fallback will kick in automatically — check that you got an image either way |

### Pipeline succeeded but no email arrived

1. Check the GitHub Actions run logs — look for "Email sent" or "SMTP
   send failed" near the end.
2. Check spam/junk folders. Gmail occasionally flags new automated
   senders.
3. If absent, manually re-run with `workflow_dispatch` — the SMTP step
   logs include the SMTP server response.

### Email arrived but worksheets look wrong

The PDFs are inside the ZIP attachments. Open one, find the issue
(banned phrase, wrong grade, em dash, etc.). The most likely cause is
a Gemini prompt drift — open `pipeline/content_generator.py` or
`pipeline/description_generator.py` and tighten the prompt rules. Run
locally first to verify (`python test.py` or `python verify_setup.py`).

### Topic history isn't updating

After a successful run, check `state/topic_history.json` for a new
commit. If the file isn't changing:
- Workflow permissions aren't set to write (Step 2 above)
- Repo has a branch protection rule blocking bot commits

### Worksheets started repeating topics

The history file is committed to the repo, but if you ever reset the
repo or the file gets cleared, the exclusion list resets too. Restore
`state/topic_history.json` from a previous commit and the next run
will respect it.

## Manually running locally

For debugging or testing before pushing changes:

```bash
# Set env vars
cp .env.example .env
# Edit .env with your values

# Install
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Quick sanity check
python verify_setup.py

# Full pipeline run
python -m pipeline.pipeline
```

This produces ZIPs in `./output/YYYY-MM-DD/` and updates
`./state/topic_history.json`. No commits, no email needed if your
local `.env` doesn't have `GMAIL_APP_PASSWORD` set — the pipeline
will just log the SMTP failure and continue.

## Disabling the daily run temporarily

GitHub UI: Actions → "Daily worksheet run" → ••• menu → "Disable
workflow". Cron stops firing. Re-enable from the same menu when ready.

Alternatively comment out the `schedule:` block in
`.github/workflows/daily.yml` and commit. Cleaner if the pause is
long-term.
