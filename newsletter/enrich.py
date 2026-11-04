"""Fetch article text for selected clusters from open (non-paywalled) sources.

Order of preference for text: full article text (trafilatura) → feed snippets → headline only.
Paywalled domains are never fetched. Google News redirect links are never fetched or decoded;
those items only contribute their headline and publisher.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests
import trafilatura

from .filter import normalize_url
from .models import Cluster, Item
from .select import Selection, is_paywalled

log = logging.getLogger(__name__)

ROLE_PREF = {"press": 0, "primary": 1, "curator": 2}
MIN_TEXT_CHARS = 600       # below this an extraction is treated as a failure (cookie walls, stubs)
MIN_SNIPPET_CHARS = 150    # total snippet text needed to write a summary from snippets
MAX_FETCH_PER_CLUSTER = 2


@dataclass
class StoryContext:
    cluster_id: str
    text_source: str                                   # fulltext | snippet | headline_only
    texts: list[dict] = field(default_factory=list)    # {publisher, url, text}
    snippets: list[dict] = field(default_factory=list) # {publisher, title, snippet}
    links: list[dict] = field(default_factory=list)    # {name, url} shown to readers
    headlines: list[dict] = field(default_factory=list)  # {publisher, title} for every item


def fetch_target(it: Item) -> str | None:
    """URL to fetch text from, or None if this item must not be fetched."""
    if it.extra.get("google_news"):
        return None
    if it.source == "Hugging Face Daily Papers":
        return it.extra.get("arxiv") or it.url
    if "news.ycombinator.com" in it.url:
        return None
    return it.url


def candidates(cluster: Cluster, paywalled: list[str]) -> list[tuple[Item, str]]:
    out = []
    for it in sorted(cluster.items, key=lambda i: (ROLE_PREF.get(i.role, 3), -len(i.snippet))):
        url = fetch_target(it)
        if url and not is_paywalled(it.publisher_url, paywalled) and not is_paywalled(_dom(url), paywalled):
            out.append((it, url))
    return out


def _dom(url: str) -> str:
    from .ingest import domain_of
    return domain_of(url)


def fetch_text(url: str, cfg: dict) -> str | None:
    http = cfg.get("http", {})
    try:
        r = requests.get(url, timeout=http.get("timeout_seconds", 20),
                         headers={"User-Agent": http.get("user_agent", "AI-Daily/0.1")})
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
            return None
        text = trafilatura.extract(r.text, url=url, include_comments=False, include_tables=False,
                                   favor_precision=True)
    except Exception as exc:  # noqa: BLE001
        log.debug("fetch failed %s: %s", url, exc)
        return None
    if not text or len(text) < MIN_TEXT_CHARS:
        return None
    return text


KNOWN_PUBLISHERS = {
    "bloomberg.com": "Bloomberg", "nytimes.com": "The New York Times", "wsj.com": "The Wall Street Journal",
    "ft.com": "Financial Times", "reuters.com": "Reuters", "axios.com": "Axios", "theverge.com": "The Verge",
    "techcrunch.com": "TechCrunch", "arstechnica.com": "Ars Technica", "cnbc.com": "CNBC",
    "theinformation.com": "The Information", "github.com": "GitHub", "arxiv.org": "arXiv",
    "openai.com": "OpenAI", "anthropic.com": "Anthropic", "blog.google": "Google", "politico.com": "Politico",
    "politico.eu": "Politico Europe", "wired.com": "Wired", "theguardian.com": "The Guardian",
    "businessinsider.com": "Business Insider", "semafor.com": "Semafor", "cnn.com": "CNN", "bbc.co.uk": "BBC",
    "bbc.com": "BBC", "economist.com": "The Economist", "fortune.com": "Fortune", "forbes.com": "Forbes",
}


DISPLAY_STRIP_PARAMS = {"accesstoken", "giftcode", "share", "sharetoken"}


def clean_display_url(url: str) -> str:
    """Strip tracking and gift/access-token params from links shown to readers."""
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
    from .filter import TRACKING_PARAMS, TRACKING_PREFIXES
    if "news.google.com" in url:
        return url
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if k.lower() not in TRACKING_PARAMS | DISPLAY_STRIP_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)]
    return urlunparse(p._replace(query=urlencode(q), fragment=""))


def pretty_publisher(name: str) -> str:
    """Turn 'https://www.bloomberg.com/' or 'bloomberg.com' into 'Bloomberg'; leave real names alone."""
    n = name.strip()
    if n.startswith(("http://", "https://")) or ("." in n and " " not in n):
        from .ingest import domain_of
        dom = domain_of(n if "://" in n else "https://" + n).rstrip("/")
        return KNOWN_PUBLISHERS.get(dom, dom)
    return n


def display_links(cluster: Cluster, paywalled: list[str], limit: int = 4) -> list[dict]:
    """Up to `limit` links, one per publisher: direct open links first, then paywalled
    direct links, then Google News links. Links are taken from the data, never from the LLM."""
    def pref(it: Item) -> tuple:
        return (it.extra.get("google_news", False), is_paywalled(it.publisher_url, paywalled),
                ROLE_PREF.get(it.role, 3))

    seen_pub, seen_url, out = set(), set(), []
    for it in sorted(cluster.items, key=pref):
        name = pretty_publisher(it.publisher or it.source)
        nurl = normalize_url(it.url)
        if name.lower() in seen_pub or nurl in seen_url:
            continue
        seen_pub.add(name.lower())
        seen_url.add(nurl)
        out.append({"name": name, "url": clean_display_url(it.url)})
        if len(out) >= limit:
            break
    return out


def enrich_cluster(cluster: Cluster, cfg: dict) -> StoryContext:
    paywalled = cfg["paywalled_domains"]
    max_chars = cfg["pipeline"]["enrich_max_chars"]
    ctx = StoryContext(cluster_id=cluster.id, text_source="headline_only",
                       links=display_links(cluster, paywalled),
                       headlines=[{"publisher": i.publisher or i.source, "title": i.title} for i in cluster.items])
    for it, url in candidates(cluster, paywalled):
        if len(ctx.texts) >= MAX_FETCH_PER_CLUSTER:
            break
        text = fetch_text(url, cfg)
        if text:
            ctx.texts.append({"publisher": it.publisher or it.source, "url": url, "text": text[:max_chars]})
    ctx.snippets = [{"publisher": i.publisher or i.source, "title": i.title, "snippet": i.snippet}
                    for i in cluster.items if i.snippet]
    if ctx.texts:
        ctx.text_source = "fulltext"
    elif sum(len(s["snippet"]) for s in ctx.snippets) >= MIN_SNIPPET_CHARS:
        ctx.text_source = "snippet"
    return ctx


def enrich_selection(selection: Selection, cfg: dict, cache: dict[str, StoryContext] | None = None
                     ) -> tuple[dict[str, StoryContext], set[str]]:
    """Returns (contexts by cluster id, ids of clusters that are unusable: headline-only but
    below the headline-only score threshold). Pass the same `cache` across re-selections."""
    min_score = cfg["pipeline"]["headline_only_min_score"]
    cache = {} if cache is None else cache
    clusters = selection.all
    todo = [c for c in clusters if c.id not in cache]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for c, ctx in zip(todo, pool.map(lambda c: enrich_cluster(c, cfg), todo)):
            cache[c.id] = ctx
    contexts = {c.id: cache[c.id] for c in clusters}
    unusable = {c.id for c in clusters
                if contexts[c.id].text_source == "headline_only" and c.importance < min_score}
    return contexts, unusable
