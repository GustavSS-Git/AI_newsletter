"""Pure-logic filtering: time window, URL normalization, dedupe, already-covered check."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from rapidfuzz import fuzz

from .models import Item

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src", "ref_url",
    "cmpid", "source", "src", "via", "smid", "ncid", "guccounter", "taid", "sr_share", "ocid",
    "__twitter_impression", "s", "spm",
}
TRACKING_PREFIXES = ("utm_", "mkt_", "pk_", "hsa_", "_hs", "oly_")


def normalize_url(url: str) -> str:
    """Canonical form for comparison: lowercase host without www, no fragment, no tracking
    params, sorted query, no trailing slash, http/https treated as equal."""
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip()
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(":80") or host.endswith(":443"):
        host = host.rsplit(":", 1)[0]
    query = [
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=False)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)
    ]
    path = p.path.rstrip("/") or ""
    return urlunparse(("https", host, path, "", urlencode(sorted(query)), ""))


def normalize_title(title: str) -> str:
    return " ".join(title.lower().replace("’", "'").split())


def titles_match(a: str, b: str, threshold: int) -> bool:
    a, b = normalize_title(a), normalize_title(b)
    if not a or not b:
        return False
    # token_set_ratio is generous with subset titles; require similar length too to avoid
    # "OpenAI" matching "OpenAI launches X" via the subset rule.
    if min(len(a), len(b)) / max(len(a), len(b)) < 0.6:
        return fuzz.ratio(a, b) >= threshold
    return fuzz.token_set_ratio(a, b) >= threshold


# ---------------------------------------------------------------- window

def within_window(items: list[Item], now: datetime, hours: float) -> list[Item]:
    """Keep items published in (now - hours, now]. Items slightly in the future (<2h,
    clock skew) are kept; ingest already drops anything further ahead."""
    start = now - timedelta(hours=hours)
    return [i for i in items if start < i.published <= now + timedelta(hours=2)]


# ---------------------------------------------------------------- dedupe

def _rep_score(item: Item) -> tuple:
    """Higher is a better representative: direct link over Google News redirect, longer snippet."""
    return (not item.extra.get("google_news", False), item.role != "curator", len(item.snippet))


def dedupe(items: list[Item], title_threshold: int) -> list[Item]:
    """Merge items that are the same article (same normalized URL, or near-identical title).
    The kept item records where else it appeared in extra['also_in'] (list of
    {source, publisher}), so triage can still count independent coverage.
    Different articles about the same event are NOT merged here — that's triage's job."""
    groups: list[list[Item]] = []
    by_url: dict[str, int] = {}
    for it in items:
        key = normalize_url(it.url)
        gi = by_url.get(key)
        if gi is None:
            for idx, g in enumerate(groups):
                if any(titles_match(it.title, o.title, title_threshold) for o in g):
                    gi = idx
                    break
        if gi is None:
            groups.append([it])
            gi = len(groups) - 1
        else:
            groups[gi].append(it)
        by_url.setdefault(key, gi)

    out = []
    for g in groups:
        rep = max(g, key=_rep_score)
        others = [o for o in g if o is not rep]
        seen = {(rep.source, rep.publisher)}
        also = []
        for o in others:
            if (o.source, o.publisher) not in seen:
                seen.add((o.source, o.publisher))
                also.append({"source": o.source, "role": o.role, "publisher": o.publisher})
        rep.extra = {**rep.extra, "also_in": also}
        rep.tags = sorted(set(rep.tags).union(*(o.tags for o in others)))
        # Keep the strongest curator signal from merged duplicates.
        for o in others:
            for k in ("points", "upvotes"):
                if o.extra.get(k) and not rep.extra.get(k):
                    rep.extra[k] = o.extra[k]
        out.append(rep)
    return out


ROLE_RANK = {"curator": 0, "primary": 1, "press": 2}


def triage_priority(item: Item) -> tuple:
    """Lower sorts first = kept first when capping: direct feeds before Google News results,
    then curators, primary, press; newest first within each group."""
    return (item.extra.get("google_news", False), ROLE_RANK.get(item.role, 3), -item.published.timestamp())


def cap_items(items: list[Item], n: int) -> list[Item]:
    """Keep the `n` highest-priority items, returned newest first. No-op if len <= n."""
    if len(items) <= n:
        return list(items)
    return sorted(sorted(items, key=triage_priority)[:n], key=lambda i: i.published, reverse=True)


def assign_ids(items: list[Item]) -> list[Item]:
    for n, it in enumerate(items, 1):
        it.id = f"i{n:03d}"
    return items


# ---------------------------------------------------------------- already covered

def load_recent_editions(editions_dir: Path | str, today: date, n: int) -> list[dict]:
    """The n most recent saved editions strictly before `today`."""
    d = Path(editions_dir)
    files = []
    for f in d.glob("*.json"):
        try:
            fdate = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if fdate < today:
            files.append((fdate, f))
    files.sort(reverse=True)
    out = []
    for _, f in files[:n]:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def shown_entries(edition: dict) -> list[dict]:
    """Every story displayed in an edition (lead, main, both briefs). Unselected clusters don't count."""
    out = []
    if edition.get("lead"):
        out.append(edition["lead"])
    for key in ("main", "europe_brief", "finance_brief"):
        out.extend(edition.get(key) or [])
    return out


def covered_index(editions: list[dict]) -> tuple[set[str], list[str], list[str]]:
    """Return (normalized urls, item titles, headlines) of everything shown in `editions`."""
    urls, titles, headlines = set(), [], []
    for ed in editions:
        for s in shown_entries(ed):
            urls.update(normalize_url(u) for u in s.get("item_urls", []))
            urls.update(normalize_url(src["url"]) for src in s.get("sources", []) if src.get("url"))
            titles.extend(s.get("item_titles", []))
            if s.get("headline"):
                headlines.append(s["headline"])
    urls.discard("")
    return urls, titles, headlines


def drop_covered(items: list[Item], covered_urls: set[str], covered_titles: list[str],
                 title_threshold: int) -> tuple[list[Item], list[Item]]:
    """Split items into (kept, dropped). An item is covered if its URL or a near-identical
    title appeared in a previous edition's shown stories. Semantic matches (same event,
    new article) are left to triage, which sees previous headlines."""
    kept, dropped = [], []
    for it in items:
        if normalize_url(it.url) in covered_urls or any(
            titles_match(it.title, t, title_threshold) for t in covered_titles
        ):
            dropped.append(it)
        else:
            kept.append(it)
    return kept, dropped
