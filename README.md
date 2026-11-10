# AI Daily

**A daily AI news digest that curates, ranks and summarizes itself.** Every morning at 05:00 Swedish time, a pipeline reads 54 news sources, groups the articles into stories, picks the most important ones and writes short, sourced summaries. The result is published as a newspaper-style web page and sent as an email newsletter. Nobody edits it by hand.

- **Live site:** [news.slanesens.com](https://news.slanesens.com), with an archive of every edition and a signup form for the newsletter.
- **Audience:** informed professionals who want to keep up with AI, not ML researchers.
- **Running cost:** about $0.07 per day in API calls. Hosting and email are on free plans.

## How it works

```
 54 sources ──► Ingest ──► Filter ──► Triage (LLM) ──► Select (code) ──► Enrich ──► Write (LLM) ──► Validate ──► Publish
 RSS, APIs      ~700 items  30-h window   cluster + score    rank + quotas     article text  summaries      quality gate   site + email
```

### 1. Collecting the news

Sources are listed in [config.yaml](config.yaml) and fall into three roles:

- **Curators:** Techmeme, Hacker News (front-page AI stories via the Algolia API) and Hugging Face Daily Papers. These signal what the field is paying attention to.
- **Primary sources:** the official blogs of OpenAI, Google DeepMind, Google Research, Hugging Face and Microsoft Research.
- **Press:** about 45 outlets and searches. These cover general tech (The Verge, TechCrunch, Ars Technica, MIT Technology Review and others), European tech (Sifted, tech.eu, Breakit and others) and finance (Finextra, Banking Dive and others), plus Google News searches for companies that have no feed.

The pipeline reads RSS feeds and public APIs. It doesn't crawl websites. Full article text is fetched only from open sites, and never from paywalled ones (WSJ, FT, Bloomberg and others are on a blocklist). A paywalled story can still be included through its headline and open coverage elsewhere.

### 2. Filtering

- Only items from the last 30 hours are kept.
- Stories already covered in the last three editions are dropped, unless there is a real new development.
- Duplicates are merged by normalized URL and fuzzy title matching.
- What remains is capped at about 750 items, and the token count is checked so the next step stays within the model's cheaper price tier.

### 3. Ranking: the model judges, the code decides

The pipeline makes two LLM calls: a cheap, fast model for triage and a stronger model for writing. Both use structured JSON output, and all model names live in the config.

- **Triage** ([prompts/triage.md](prompts/triage.md)). Claude Haiku groups the items into stories ("clusters") and scores each one from 1 to 10. It also labels the category and flags whether the story is European or about AI in finance or consulting. The prompt has explicit scoring rules. For example, a story reported by a single outlet, or a company's own claims, can score at most 5. Broad coverage across many outlets raises the minimum score.
- **Selection** ([newsletter/select.py](newsletter/select.py)) is plain Python, not a prompt, so the rules are predictable and unit-tested:
  - The top 6 stories become the lead and the main section.
  - A Europe brief and a Business & Finance brief take the best remaining stories in those areas.
  - A story with no open article text needs a high score and several independent publishers to qualify.

Every cluster's score is saved with the edition, whether or not it was selected.

### 4. Writing and quality control

- **Writing** ([prompts/write.md](prompts/write.md)). Claude Sonnet writes a headline and a 2–4 sentence summary for each story, in a Wall Street Journal-like style. It only uses facts from the fetched article text and attributes claims to their source. Links come from the data, never from the model.
- **Validation** ([newsletter/validate.py](newsletter/validate.py)) is a final gate before anything is published. It checks the schema, the minimum number of stories, empty fields and broken links, and confirms the edition isn't a repeat of yesterday's. If any check fails, nothing is published and the previous edition stays live.

## Infrastructure

| Piece | Role |
|---|---|
| **GitHub Actions** ([.github/workflows/daily.yml](.github/workflows/daily.yml)) | Runs the unit tests, then the pipeline, each morning. Commits the new edition and the rebuilt site back to the repo, then hands the email to Buttondown. API keys are stored as repository secrets. GitHub's own schedule runs hours late, so it is only a fallback: it builds an edition only if none exists yet that day. |
| **Cloudflare** ([wrangler.jsonc](wrangler.jsonc), [worker/index.js](worker/index.js)) | Serves the static site from `site/` at news.slanesens.com. It redeploys automatically on every push to `main`, so GitHub needs no Cloudflare credentials. A cron trigger on the same Worker starts the daily run at 05:00 Swedish time (following daylight saving time) through GitHub's `workflow_dispatch` API. |
| **Buttondown** ([newsletter/send.py](newsletter/send.py)) | Email delivery, the subscriber list, double opt-in and unsubscribes. The pipeline creates each email through Buttondown's API, and an idempotency check makes sure an edition is never sent twice. Mail goes out from a custom domain with SPF, DKIM and DMARC records set up. |

The repo itself is the database. Each edition is stored as a JSON file in `editions/`, so the archive and the site can be rebuilt at any time without API calls.

## Repository structure

```
├── run.py                  # entry point: runs the whole pipeline
├── config.yaml             # sources, thresholds, model names, paywall list
├── prompts/                # LLM instructions (triage.md, write.md)
├── newsletter/             # the pipeline, one module per step
│   ├── ingest.py           #   fetch RSS / APIs
│   ├── filter.py           #   time window, dedupe, already-covered check
│   ├── triage.py           #   LLM call 1: cluster + score
│   ├── select.py           #   ranking and section rules
│   ├── enrich.py           #   fetch open article text
│   ├── write.py            #   LLM call 2: headlines + summaries
│   ├── validate.py         #   quality gate
│   ├── render.py           #   HTML site + archive (Jinja2)
│   ├── email.py, send.py   #   email body + Buttondown API
│   └── schema.py           #   edition JSON schema (pydantic)
├── templates/              # HTML/CSS templates for site and email
├── scripts/                # feed health check, email sender
├── tests/                  # unit tests (pytest; no network or API calls)
├── editions/               # one JSON file per day: the stored output
├── site/                   # generated website, deployed by Cloudflare
├── .github/workflows/      # daily run + manual feed check
└── DECISIONS.md            # log of design decisions and trade-offs
```

## Running it locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env.local     # gitignored

.venv/bin/python run.py --dry-run       # ingest + triage, print the ranked stories (≈ $0.02)
.venv/bin/python run.py                 # full run: writes editions/ and site/
.venv/bin/python run.py --render-only   # rebuild the site from saved editions, no API calls
.venv/bin/python -m pytest -q           # unit tests
```

Built with Python, the Anthropic API (Claude Haiku and Sonnet), feedparser, trafilatura, Jinja2 and pydantic.
