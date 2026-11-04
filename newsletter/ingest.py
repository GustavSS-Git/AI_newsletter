"""Fetch items from every configured source. One failing source never crashes the run."""
from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse

import feedparser
import requests

from .models import Item

log = logging.getLogger(__name__)

TAG_RE = re.compile(r"<[^>]+>")
# Used by HN and by sources with `ai_filter: true` (general-interest feeds).
AI_KEYWORDS = [
    "AI", "A.I.", "artificial intelligence", "artificiell intelligens", "LLM", "LLMs", "GPT", "ChatGPT",
    "OpenAI", "Anthropic", "Claude", "Gemini", "DeepMind", "Mistral", "Llama", "machine learning",
    "neural", "generative", "genAI", "chatbot", "Copilot", "Nvidia", "AGI", "agentic", "AI Act",
    "maskininlärning", "språkmodell",
]


def keyword_pattern(keywords: list[str]) -> re.Pattern:
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(k) for k in keywords) + r")s?(?!\w)", re.I)


AI_PATTERN = keyword_pattern(AI_KEYWORDS)
HREF_RE = re.compile(r'href="([^"]+)"')


@dataclass
class SourceResult:
    name: str
    role: str
    items: list[Item] = field(default_factory=list)
    error: str | None = None
    raw_count: int = 0      # entries returned before any filtering
    newest: datetime | None = None
    kept_count: int = 0     # after future-date guard and optional ai_filter


def clean_text(s: str, limit: int = 500) -> str:
    s = html.unescape(TAG_RE.sub(" ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit].rsplit(" ", 1)[0] + "…" if len(s) > limit else s


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t:  # feedparser normalizes *_parsed to UTC struct_time
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def _get(url: str, cfg: dict, **kw) -> requests.Response:
    http = cfg.get("http", {})
    r = requests.get(
        url,
        timeout=http.get("timeout_seconds", 20),
        headers={"User-Agent": http.get("user_agent", "AI-Daily/0.1")},
        **kw,
    )
    r.raise_for_status()
    return r


# ---------------------------------------------------------------- source types

def fetch_rss(src: dict, cfg: dict) -> list[Item]:
    resp = _get(src["url"], cfg)
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"unparseable feed: {feed.bozo_exception}")
    items = []
    for e in feed.entries:
        ts = _entry_time(e)
        if not ts or not e.get("title") or not e.get("link"):
            continue
        link = e.link
        summary = e.get("summary", "") or ""
        publisher, publisher_url = src["name"], domain_of(link)
        if src["name"] == "Techmeme":
            # Techmeme items link to a techmeme permalink; the original article is in the description.
            for href in HREF_RE.findall(summary):
                if "techmeme.com" not in href:
                    link = html.unescape(href)
                    publisher_url = domain_of(link)
                    publisher = publisher_url
                    break
        items.append(Item(
            id="", title=clean_text(e.title, 300), url=link, source=src["name"], role=src["role"],
            published=ts, snippet=clean_text(summary), publisher=publisher,
            publisher_url=publisher_url, tags=list(src.get("tags", [])),
        ))
    return items


def fetch_google_news(src: dict, cfg: dict) -> list[Item]:
    q = f'{src["query"]} when:2d'
    hl, gl = src.get("locale", "en-US:US").split(":")
    lang = hl.split("-")[0]
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl={hl}&gl={gl}&ceid={gl}:{lang}"
    resp = _get(url, cfg)
    feed = feedparser.parse(resp.content)
    items = []
    for e in feed.entries:
        ts = _entry_time(e)
        if not ts:
            continue
        src_meta = e.get("source") or {}
        publisher = src_meta.get("title", "") if hasattr(src_meta, "get") else ""
        publisher_url = domain_of(src_meta.get("href", "")) if hasattr(src_meta, "get") else ""
        title = e.title
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3]
        items.append(Item(
            id="", title=clean_text(title, 300), url=e.link, source=src["name"], role=src["role"],
            published=ts, snippet="", publisher=publisher, publisher_url=publisher_url,
            tags=list(src.get("tags", [])), extra={"google_news": True},
        ))
    return items


def fetch_hn(src: dict, cfg: dict, now: datetime) -> list[Item]:
    since = int((now - timedelta(hours=48)).timestamp())
    url = (
        "https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=500"
        f"&numericFilters=points>{src.get('min_points', 100)},created_at_i>{since}"
    )
    hits = _get(url, cfg).json().get("hits", [])
    pattern = keyword_pattern(src["keywords"]) if src.get("keywords") else AI_PATTERN
    items = []
    for h in hits:
        title = h.get("title") or ""
        if not pattern.search(title):
            continue
        hn_url = f"https://news.ycombinator.com/item?id={h['objectID']}"
        link = h.get("url") or hn_url
        items.append(Item(
            id="", title=title, url=link, source=src["name"], role=src["role"],
            published=datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
            snippet="", publisher=domain_of(link), publisher_url=domain_of(link),
            extra={"points": h.get("points"), "comments": h.get("num_comments"), "hn_url": hn_url},
        ))
    return items


def fetch_hf_papers(src: dict, cfg: dict) -> list[Item]:
    data = _get(src.get("url", "https://huggingface.co/api/daily_papers"), cfg).json()
    data = sorted(data, key=lambda d: d.get("paper", {}).get("upvotes", 0), reverse=True)
    items = []
    for d in data[: src.get("top_n", 10)]:
        p = d.get("paper", {})
        ts_raw = p.get("submittedOnDailyAt") or d.get("publishedAt")
        if not ts_raw or not p.get("id"):
            continue
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        items.append(Item(
            id="", title=d.get("title") or p.get("title", ""), url=f"https://huggingface.co/papers/{p['id']}",
            source=src["name"], role=src["role"], published=ts,
            snippet=clean_text(p.get("ai_summary") or p.get("summary", "")),
            publisher="Hugging Face Papers", publisher_url="huggingface.co",
            extra={"upvotes": p.get("upvotes", 0), "arxiv": f"https://arxiv.org/abs/{p['id']}"},
        ))
    return items


# ---------------------------------------------------------------- driver

def fetch_source(src: dict, cfg: dict, now: datetime | None = None) -> SourceResult:
    now = now or datetime.now(timezone.utc)
    res = SourceResult(name=src["name"], role=src["role"])
    try:
        kind = src.get("type", "rss")
        if kind == "rss":
            items = fetch_rss(src, cfg)
        elif kind == "google_news":
            items = fetch_google_news(src, cfg)
        elif kind == "hn_algolia":
            items = fetch_hn(src, cfg, now)
        elif kind == "hf_daily_papers":
            items = fetch_hf_papers(src, cfg)
        else:
            raise ValueError(f"unknown source type {kind!r}")
        res.raw_count = len(items)
        # Drop entries dated in the future (event listings, bad clocks): >2h ahead of now.
        items = [i for i in items if i.published <= now + timedelta(hours=2)]
        if src.get("ai_filter"):
            items = [i for i in items if AI_PATTERN.search(f"{i.title} {i.snippet}")]
        res.items = items
        res.newest = max((i.published for i in items), default=None)
        res.kept_count = len(items)
    except Exception as exc:  # noqa: BLE001 — one bad source must never crash the run
        res.error = f"{type(exc).__name__}: {exc}"[:200]
        log.warning("source %s failed: %s", src["name"], res.error)
    return res


def fetch_all(cfg: dict, now: datetime | None = None, workers: int = 8) -> list[SourceResult]:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda s: fetch_source(s, cfg, now), cfg["sources"]))
