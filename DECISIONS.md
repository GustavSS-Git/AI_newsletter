# Decisions log

Non-trivial choices made while building v0, newest at the bottom of each section.

## Agreed with Gustav up front (2026-11-04)

- `main_stories: 6` counts the lead (lead + 5).
- `european`: a European company, institution or regulator is a principal actor, or the main effect is specifically European. UK, Switzerland, Norway and the Nordics count.
- `finance_consulting`: AI used in or changing financial services or consulting/professional services. AI-company funding rounds are `business/funding`, not finance.
- Follow-ups: triage sees the last 3 editions' headlines and flags `covered_before`; such clusters return only if `new_development` and importance ≥ 7 (`followup_min_score`).
- Reader: informed professionals who want to stay current on AI, not ML researchers.
- Work happens on branch `v0`; nothing is pushed.
- Dates are UTC. Edition number = number of earlier editions + 1 (a re-run of the same date keeps its number).
- Paywalled-only stories are kept headline-only when importance ≥ 8, otherwise dropped and replaced.
- Only *shown* stories (lead, main, briefs) count as "already covered"; unselected clusters don't.
- Validation minimum: 4 main stories (lead included). American English.

## Secrets

- `.gitignore` (ignoring `.env` and `.env.*`) was the first commit, before any code. The key is loaded from `.env.local`, then `.env`; it is never logged. `.env.example` documents the variable name.

## Sources (feed check 2026-11-04: 31/31 OK after fixes)

- **VentureBeat**: the direct feed returns 429 to scripted clients. Replaced with a Google News `site:venturebeat.com AI` search.
- **Euractiv**: euractiv.com now redirects to **Rapporteur**; the tech-section feed 404s. Using the Rapporteur main feed with `ai_filter: true`.
- **Ny Teknik**: no public RSS (all candidate URLs 404). Using a Google News `site:nyteknik.se AI` search with Swedish locale.
- `ai_filter: true` (AI keyword match on title and snippet) is applied to general-interest feeds: Sifted, tech.eu, Rapporteur, Breakit, Finextra.
- Entries dated more than 2 hours in the future are dropped at ingest (Finextra lists events with 2027 dates).
- **Google News company searches** (Anthropic, Meta AI, Mistral) are role `press`, not `primary`. They return press coverage, not the company's own posts, and the triage prompt treats `primary` as self-promotion. Labeling them `primary` also caused a real bug (see below).
- Hacker News: Algolia `search_by_date`, points > 100, last 48 hours, then filtered by an AI keyword regex on the title. The 30-hour window is applied later, as for every source.
- HF Daily Papers: the top 10 by upvotes from the daily list. They link to the HF paper page; text is fetched from arXiv.
- **Google News terms**: the RSS feed says it is for "personal, non-commercial use". Gustav confirmed the project is non-commercial and completely free (2026-11-04), so Google News searches stay in.

## Google News links

- Google News RSS links are redirect URLs. Decoding them requires getting past Google's consent page, so the pipeline does **not** decode or fetch them. Google News items are used to discover stories and count coverage. A story whose only open sources are Google News items has no text and goes through the headline-only rule. Its reader-facing links stay as Google News links, which work in a browser.

## Pipeline

- **Dedupe vs clustering**: `filter.dedupe` merges only the *same article* (same normalized URL, or near-identical title, `token_set_ratio ≥ 88` with a length guard). Grouping different articles about the same event is triage's job. Merged duplicates are recorded in `also_in`, so coverage counts are preserved.
- **Triage input cap** (`max_items_to_triage: 600`): only applies on heavy days. It keeps direct feeds first (curators, then primary, then press) and Google News results last. *Bug fixed*: the first version capped at 400 and ranked by role, and Google News company searches (then `primary`) pushed out direct press feeds. The result was a lead story built only from Google News headlines, whose numbers contradicted each other.
- **Triage output** is validated in code: unknown item ids are dropped, each item belongs to at most one cluster, and scores are clamped to 1–10. Items that triage leaves unclustered are treated as irrelevant.
- **Selection** is pure Python (`select.py`). Ranking: importance, then number of distinct publishers, then curator pickup. Briefs take only clusters not already shown, with a score ≥ threshold. Finance never repeats a Europe pick.
- **Enrich → re-select loop**: if a selected story ends up with no usable text and is below the headline-only threshold, it is excluded and selection re-runs (up to 5 times). Fetched text is cached across iterations.
- **Text source preference**: press > primary > curator. Up to 2 articles per story, each capped at 6,000 characters. Extractions under 600 characters count as failures (cookie walls, stubs). Feed snippets are used if they total ≥ 150 characters; otherwise the story is headline-only.
- **Source links are attached in code** from the cluster's items, never generated by the model. Up to 4 per story, one per publisher: open direct links first, then paywalled links, then Google News.
- **Writer gets `material`** (`fulltext` / `snippet` / `headline_only`), and the prompt adjusts what it may claim. The page shows a note on headline-only stories.
- **Cost guard**: before the write call, the exact input tokens are counted (`count_tokens`) and output is assumed to be 1,200 tokens per story. The run stops if the estimate exceeds `cost_stop_usd` ($1). Typical run so far: about $0.06–0.07.

## Models and API

- Models are set in `config.yaml`: triage `claude-haiku-5-5`, writing `claude-sonnet-5-5`. These were checked against Anthropic's model list on 2026-11-04. Both run at effort `medium`, with adaptive thinking on by default.
- Structured output uses `client.messages.stream(..., output_format=PydanticModel)` (SDK `anthropic` 2.5.0), with Pydantic schemas in `triage.py` and `write.py`. Streaming avoids HTTP timeouts on long outputs.
- Pricing is in config, for the cost estimate only. Haiku 5.5 is $0.10/$0.50 per million tokens up to 100K prompt tokens, so triage input should stay under 100K. It is currently about 50K tokens for about 540 items.

## Validation

- A link "works" if the response status is below 400, or a bot-block code (401/403/405/429/451/999): the page exists for human readers. Each story needs at least one working link.
- "Identical to yesterday" means the same set of normalized item and source URLs, or the same set of headlines.
- On any error the run exits 1 and writes neither the edition nor the site.

## Front end

- Bare semantic HTML with a Georgia serif font, single column, black on off-white. The template is split into `base.html.j2`, `edition.html.j2` and `partials/story.html.j2`; CSS lives in `templates/style.css` and is copied to `site/`. The class names are stable hooks for the later redesign. The highlights (v3) and signup (v2) placeholders are present as `hidden` sections.

## Editorial review of the first edition (2026-11-04)

An independent reviewer agent checked the edition: it judged the selection, checked style, and fetched the sources of 4 or more stories to verify grounding. Applied:
- **write.md**: headline-only stories may give no figures when outlets disagree, and a claim from a single headline can't be used even with attribution. A fact may be attributed only to an outlet whose material contains it, and conflicts between sources must be stated. Headlines state the event, not a reaction ("draws scrutiny", "raises odds"). "Why it matters" may not pass on someone else's forecast.
- **triage.md**: hard limits on scores (a single outlet without a curator scores at most 5; a company's claim about itself in one or two outlets at most 5; a concrete event in 8+ outlets, or a curator plus 3+, at least 6). A floor for concrete European or finance actions. A rule to give clusters with similar evidence the same score. No grab-bag clusters. Market-bubble commentary is not `finance_consulting`.
- Display links have tracking and gift-token parameters removed. The headline-only note no longer says "paywalled", since Google-News-only stories aren't paywalled.

Effect on the re-run: both briefs filled (2 Europe, 2 finance), and headlines and "why it matters" are factual. Open, for Gustav to decide (see the v0 report): how to handle Google-News-only stories, the headline-only gate and the brief threshold.

## Follow-up decisions (2026-11-04, after the v0 report)

- **More direct press feeds** (option C), so fewer stories depend on Google News alone. There are 23 new sources, for 54 in total, and all pass `check_feeds.py`:
  - **General press:** The Guardian AI, CNBC Technology, Axios, The Register AI, The Decoder, SiliconANGLE AI, Engadget, ZDNet AI, Fortune, BBC Technology, IEEE Spectrum AI, The Next Web, Wired AI.
  - **Europe:** Politico Europe Tech, Silicon Republic, UKTN, Computer Sweden.
  - **Finance:** Finextra AI channel, PYMNTS, Banking Dive, The Fintech Times, Private Equity Wire, Insurance Journal.

  General-interest feeds use `ai_filter`. Wired stays on the paywall list: it counts toward coverage but is not fetched. Not available: Reuters (no public RSS; it stays as a Google News coverage signal), AP (403), Semafor (404), Fintech Futures (403), Consultancy.eu/.uk (no feed), American Banker and The Financial Brand (malformed XML).
- **Headline-only gate** (reviewer's suggestion, approved), now set by section:
  - **Main/lead:** score ≥ 6 and ≥ 3 distinct outlets (was score ≥ 8).
  - **Briefs:** ≥ 2 outlets.

  The rule lives in `select.headline_only_ok` and is used both before selection (paywalled-only clusters) and after enrichment (clusters with no text).
- `brief_threshold` 5 → 4 (approved).
- `max_items_to_triage` 600 → 800, for the larger source list. That keeps triage input around 75K tokens, under Haiku 5.5's 100K price tier.
