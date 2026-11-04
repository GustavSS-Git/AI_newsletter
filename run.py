"""Run the daily pipeline: ingest → filter → triage → select → enrich → write → validate → render.

    python run.py              # full run for today (UTC)
    python run.py --dry-run    # ingest → filter → triage, print ranked clusters, no writing model
    python run.py --date 2026-11-04
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from newsletter import filter as flt
from newsletter.config import ROOT, has_api_key, load_config, load_env
from newsletter.ingest import fetch_all
from newsletter.llm import Usage
from newsletter.select import has_open_source, select

log = logging.getLogger("run")


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpx2", "anthropic", "urllib3", "trafilatura", "charset_normalizer", "htmldate"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def print_clusters(clusters, selection=None, limit: int = 40) -> None:
    print(f"\n{'#':>3} {'score':>5} {'cat':18} {'EU':2} {'FI':2} {'pubs':>4}  label / reason")
    print("-" * 110)
    for n, c in enumerate(sorted(clusters, key=lambda c: (-c.importance, -len(c.publishers)))[:limit], 1):
        sec = selection.section_of(c.id) if selection else None
        flag = f"[{sec}]" if sec else ("[covered]" if c.covered_before else "")
        print(f"{n:>3} {c.importance:>5} {c.category:18} {'x' if c.european else '':2} "
              f"{'x' if c.finance_consulting else '':2} {len(c.publishers):>4}  {c.label} {flag}")
        print(f"{'':39}  ↳ {c.reason}")
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="stop after triage; print ranked clusters")
    ap.add_argument("--date", help="edition date YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--config", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose)
    load_env()
    cfg = load_config(args.config)
    p = cfg["pipeline"]
    now = datetime.now(timezone.utc)
    today = date.fromisoformat(args.date) if args.date else now.date()
    editions_dir = ROOT / "editions"

    if not has_api_key():
        log.error("ANTHROPIC_API_KEY not set (looked in .env.local and .env)")
        return 2

    import anthropic
    client = anthropic.Anthropic()
    usage = Usage()

    # 1. Ingest -----------------------------------------------------------------
    results = fetch_all(cfg, now)
    failures = [r for r in results if r.error]
    items = [it for r in results for it in r.items]

    # 2. Filter -----------------------------------------------------------------
    in_window = flt.within_window(items, now, p["window_hours"])
    previous = flt.load_recent_editions(editions_dir, today, p["covered_lookback_editions"])
    cov_urls, cov_titles, cov_headlines = flt.covered_index(previous)
    kept, covered = flt.drop_covered(in_window, cov_urls, cov_titles, p["title_similarity"])
    deduped = flt.dedupe(kept, p["title_similarity"])
    # Safety cap: prefer curators/primary and items with snippets if over the limit.
    n_deduped = len(deduped)
    deduped = flt.cap_items(deduped, p["max_items_to_triage"])
    flt.assign_ids(deduped)

    per_source = Counter(it.source for it in in_window)
    log.info("ingest: %d items from %d sources (%d failed); %d in %dh window; %d already covered; %d after dedupe"
             "%s", len(items), len(results), len(failures), len(in_window), p["window_hours"], len(covered), n_deduped,
             f"; capped to {len(deduped)}" if len(deduped) < n_deduped else "")
    for r in failures:
        log.warning("  source failed: %s — %s", r.name, r.error)

    # 3. Triage -----------------------------------------------------------------
    from newsletter.triage import fit_token_budget, triage
    deduped = fit_token_budget(deduped, today, cov_headlines, cfg=cfg, client=client)
    clusters = triage(deduped, today, cov_headlines, cfg=cfg, client=client, usage=usage)
    log.info("triage: %d clusters from %d items (cost so far $%.4f)", len(clusters), len(deduped), usage.total_cost)

    sel_kwargs = dict(
        n_main=p["main_stories"], threshold=p["brief_threshold"], brief_max=p["brief_max"],
        paywalled=cfg["paywalled_domains"], followup_min=p["followup_min_score"],
        headline_only_min=p["headline_only_min_score"],
        headline_only_min_publishers=p.get("headline_only_min_publishers", 1),
        brief_min_publishers=p.get("brief_headline_only_min_publishers", 1),
    )

    if args.dry_run:
        selection = select(clusters, **sel_kwargs)
        print_clusters(clusters, selection)
        print("Items in window per source:")
        for r in results:
            print(f"  {r.name:38} {per_source.get(r.name, 0):>4}" + (f"  FAILED: {r.error}" if r.error else ""))
        print(f"\nCost: ${usage.total_cost:.4f}  {usage.calls}")
        return 0

    # 4–5. Select + enrich (re-select if a story turns out unusable) -------------
    from newsletter.enrich import enrich_selection
    exclude: set[str] = set()
    enrich_cache: dict = {}
    for _ in range(5):
        selection = select(clusters, exclude=exclude, **sel_kwargs)
        contexts, unusable = enrich_selection(selection, cfg, enrich_cache)
        if not unusable:
            break
        log.info("enrich: %d stories unusable (headline-only, fails the headline-only gate); re-selecting", len(unusable))
        exclude |= unusable
    else:
        log.warning("enrich: still unusable stories after retries; dropping them")
        selection = select(clusters, exclude=exclude, **sel_kwargs)
        contexts, _ = enrich_selection(selection, cfg, enrich_cache)
    if selection.lead is None:
        log.error("no eligible stories today")
        return 1

    for c in selection.all:
        ctx = contexts[c.id]
        log.info("selected [%s] %d  %s — %s (text: %s)", selection.section_of(c.id), c.importance, c.label,
                 c.reason, ctx.text_source)

    # 6. Write ------------------------------------------------------------------
    from newsletter.write import estimate_write_cost, write_edition
    est = usage.total_cost + estimate_write_cost(selection, contexts, cfg, client, today)
    log.info("estimated total run cost before writing: $%.3f", est)
    if est > p["cost_stop_usd"]:
        log.error("estimated cost $%.2f exceeds cost_stop_usd=$%.2f — stopping before the write call",
                  est, p["cost_stop_usd"])
        return 3
    written = write_edition(selection, contexts, cfg=cfg, client=client, usage=usage, today=today)

    # 7. Assemble + validate -----------------------------------------------------
    from newsletter.render import build_edition, render_site, save_edition
    from newsletter.validate import validate_edition
    edition = build_edition(
        today=today, now=now, cfg=cfg, selection=selection, contexts=contexts, written=written,
        clusters=clusters, editions_dir=editions_dir,
        stats={
            "items_fetched": len(items), "items_in_window": len(in_window),
            "items_already_covered": len(covered), "items_triaged": len(deduped),
            "clusters": len(clusters), "per_source": dict(per_source),
            "failed_sources": {r.name: r.error for r in failures}, "llm_calls": usage.calls,
            "cost_usd": round(usage.total_cost, 4),
        },
    )
    yesterday = flt.load_recent_editions(editions_dir, today, 1)
    errors = validate_edition(edition, cfg, previous=yesterday[0] if yesterday else None)
    if errors:
        for e in errors:
            log.error("validation: %s", e)
        log.error("validation failed — edition NOT written")
        return 1

    # 8. Save + render -------------------------------------------------------------
    path = save_edition(edition, editions_dir)
    out = render_site(edition, cfg, ROOT / "site")
    log.info("wrote %s and %s", path.relative_to(ROOT), out.relative_to(ROOT))
    log.info("run cost: $%.4f (%s)", usage.total_cost,
             ", ".join(f"{c['step']} {c['model']} {c['input_tokens']}in/{c['output_tokens']}out" for c in usage.calls))
    return 0


if __name__ == "__main__":
    sys.exit(main())
