"""Validation gate. Any error → the run exits non-zero and the edition is not written."""
from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import requests
from pydantic import ValidationError

from .filter import normalize_url, shown_entries
from .schema import Edition

log = logging.getLogger(__name__)

# Status codes that mean "the page exists but refuses scripted clients" — fine for human readers.
BOT_BLOCK_CODES = {401, 403, 405, 429, 451, 999}


def check_link(url: str, timeout: float = 15, user_agent: str = "AI-Daily/0.1") -> bool:
    headers = {"User-Agent": user_agent}
    try:
        r = requests.head(url, timeout=timeout, headers=headers, allow_redirects=True)
        if r.status_code < 400 or r.status_code in BOT_BLOCK_CODES:
            return True
        r = requests.get(url, timeout=timeout, headers=headers, allow_redirects=True, stream=True)
        r.close()
        return r.status_code < 400 or r.status_code in BOT_BLOCK_CODES
    except requests.RequestException:
        return False


def _empty_fields(entry: dict, fields: tuple[str, ...]) -> list[str]:
    return [f for f in fields if not str(entry.get(f) or "").strip()]


def story_fingerprint(edition: dict) -> frozenset[str]:
    """Identity of an edition's shown content: the set of normalized source URLs."""
    urls = set()
    for s in shown_entries(edition):
        urls.update(normalize_url(u) for u in s.get("item_urls", []))
        urls.update(normalize_url(src.get("url", "")) for src in s.get("sources", []))
    urls.discard("")
    return frozenset(urls)


def validate_edition(edition: dict, cfg: dict, previous: dict | None = None,
                     link_checker: Callable[[str], bool] | None = None) -> list[str]:
    errors: list[str] = []
    p = cfg["pipeline"]

    # 1. Schema
    try:
        Edition.model_validate(edition)
    except ValidationError as exc:
        errors.append(f"schema: {exc.error_count()} error(s): " + "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5]))
        return errors  # the remaining checks assume the schema holds

    # 2. Minimum story count (lead + main)
    n = 1 + len(edition["main"])
    if n < p["min_main_stories"]:
        errors.append(f"only {n} main stories (minimum {p['min_main_stories']})")

    # 3. No empty fields
    story_fields = ("headline", "summary", "category")
    for s in [edition["lead"], *edition["main"]]:
        for f in _empty_fields(s, story_fields):
            errors.append(f"story {s['id']}: empty field '{f}'")
    for key in ("europe_brief", "finance_brief"):
        for b in edition[key]:
            for f in _empty_fields(b, ("headline", "summary")):
                errors.append(f"{key} {b['id']}: empty field '{f}'")
    for e in shown_entries(edition):
        for src in e["sources"]:
            if not src["url"].strip() or not src["name"].strip():
                errors.append(f"{e['id']}: source with empty name or url")

    # 4. Every story has at least one working link
    checker = link_checker or (lambda u: check_link(u, cfg.get("http", {}).get("timeout_seconds", 15),
                                                    cfg.get("http", {}).get("user_agent", "AI-Daily/0.1")))
    entries = shown_entries(edition)
    urls = sorted({src["url"] for e in entries for src in e["sources"]})
    with ThreadPoolExecutor(max_workers=8) as pool:
        ok = dict(zip(urls, pool.map(checker, urls)))
    for e in entries:
        if not any(ok.get(src["url"]) for src in e["sources"]):
            errors.append(f"{e['id']}: no working link among {len(e['sources'])} source(s)")
    broken = [u for u, good in ok.items() if not good]
    if broken:
        log.warning("validate: %d link(s) failed the check (story still has another): %s", len(broken), broken[:5])

    # 5. Not identical to the previous edition
    if previous is not None:
        fp = story_fingerprint(edition)
        if fp and fp == story_fingerprint(previous):
            errors.append("edition is identical to the previous edition (same set of stories)")
        elif sorted(s["headline"] for s in shown_entries(edition)) == \
                sorted(s.get("headline") or "" for s in shown_entries(previous)):
            errors.append("edition headlines are identical to the previous edition")

    return errors
