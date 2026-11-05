# AI Daily

A daily, AI-curated digest of general AI news, published as a single static page.

Each run collects about 30 news sources, clusters and scores the stories with a cheap model, picks the edition in plain Python, and writes short, grounded summaries with a stronger model.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env.local   # or .env; both are gitignored
```

## Usage

```bash
.venv/bin/python run.py              # full run → editions/YYYY-MM-DD.json + site/index.html
.venv/bin/python run.py --dry-run    # ingest → filter → triage, print ranked clusters (≈ $0.02)
.venv/bin/python run.py --render-only  # rebuild site/ (index, archive, 404) from saved editions, no API calls
.venv/bin/python scripts/check_feeds.py   # health check of every source
.venv/bin/python -m pytest -q        # unit tests (pure logic, no network)
```

A full run takes about 3 minutes and costs about $0.06–0.07. Exit codes:
- `0`: OK.
- `1`: validation failed or no stories. Nothing is written.
- `2`: no API key.
- `3`: estimated cost is above `cost_stop_usd`.

## Pipeline

| Step | Module | What it does |
|---|---|---|
| Ingest | `newsletter/ingest.py` | Fetches RSS, Hacker News (Algolia), HF Daily Papers and Google News searches. A failing source is logged and skipped. |
| Filter | `newsletter/filter.py` | Applies the fixed 30-hour window, drops stories already shown in the last 3 editions, normalizes URLs and merges duplicates. |
| Triage | `newsletter/triage.py` + `prompts/triage.md` | Haiku clusters items into stories and scores each: importance, category, `european`, `finance_consulting`. |
| Select | `newsletter/select.py` | Picks the top N (lead included), then the Europe and Business & Finance briefs. The quota rules are code, not prompt. |
| Enrich | `newsletter/enrich.py` | Fetches article text with trafilatura from open sources; falls back to snippets, then headline-only. Never fetches paywalled sites. |
| Write | `newsletter/write.py` + `prompts/write.md` | Sonnet writes headlines and summaries. Links come from the data, not the model. |
| Validate | `newsletter/validate.py` | Checks the schema, story count, empty fields, working links and that the edition differs from yesterday's. |
| Render | `newsletter/render.py` + `templates/` | Saves the edition JSON (with every triage score) and renders `site/index.html` with Jinja2. |

Everything tunable is in `config.yaml`: sources, N, thresholds, window, model names and the paywall list. The prompts are plain Markdown in `prompts/`. Design choices are logged in `DECISIONS.md`.

## Automation (v1)

Live at **https://news.slanesens.com**.

- `.github/workflows/daily.yml` runs at 05:00 Swedish time every day (CET/CEST; a small gate job picks the right UTC cron). It installs dependencies, runs the tests, then runs `run.py`, and commits `editions/` and `site/` back to `main`. A failed check fails the job, nothing is committed, and GitHub emails you. You can also start it by hand from the Actions tab (**Daily edition → Run workflow**), optionally as a dry run.
- Cloudflare (Workers static assets, configured in `wrangler.jsonc`) redeploys `site/` on every push to `main`.
- `.github/workflows/feed-check.yml` runs `check_feeds.py` from GitHub's servers when started by hand. Use it if a source works locally but fails in the daily job.
- `site/archive/` has one page per edition plus an index. All archive pages are rebuilt on every run, so template changes apply to old editions too.
- The API key is the `ANTHROPIC_API_KEY` repository secret (Settings → Secrets and variables → Actions).

## Email (v2)

- Each morning, after the edition is committed, the workflow runs `scripts/send_email.py`. It sends the edition through Buttondown, as set by `email.mode` in `config.yaml`:
  - `off`: no email.
  - `draft`: a Buttondown draft for review.
  - `send`: sent to all subscribers.
- It skips quietly until the `BUTTONDOWN_API_KEY` repository secret exists.
- At most one email per edition date: it checks the Buttondown API for an existing email and sends an idempotency key. Re-running the workflow is safe.
- `python scripts/send_email.py --preview` writes the email as a local HTML file, without an API call.
- Setting `email.buttondown_username` adds a signup form to the site. Buttondown sends each new subscriber a confirmation email (double opt-in).

## Roadmap

- **v3**: Week / Month / Year highlights built from stored importance scores.
