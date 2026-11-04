"""Shared factories for building Items and Clusters in tests."""
from __future__ import annotations

import itertools
from datetime import datetime, timezone

import pytest

from newsletter.models import Cluster, Item

NOW = datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)

_counter = itertools.count(1)


def make_item(title: str = "Some AI story", url: str | None = None, *, source: str = "TechCrunch AI",
              role: str = "press", published: datetime = NOW, snippet: str = "",
              publisher: str = "", publisher_url: str = "techcrunch.com",
              tags: list[str] | None = None, extra: dict | None = None) -> Item:
    n = next(_counter)
    return Item(
        id="", title=title, url=url or f"https://example.com/article-{n}", source=source, role=role,
        published=published, snippet=snippet, publisher=publisher, publisher_url=publisher_url,
        tags=list(tags or []), extra=dict(extra or {}),
    )


def make_cluster(cid: str, importance: int = 5, *, items: list[Item] | None = None,
                 european: bool = False, finance: bool = False, covered_before: bool = False,
                 new_development: bool = False, category: str = "products",
                 n_publishers: int = 1, curator: bool = False,
                 publisher_url: str = "techcrunch.com") -> Cluster:
    """Build a cluster. Without explicit `items`, creates `n_publishers` items from distinct
    open publishers; `curator=True` makes the first one a curator item."""
    if items is None:
        items = [
            make_item(f"{cid} story {k}", source=f"Source {cid}-{k}", publisher=f"Pub {k}",
                      publisher_url=publisher_url,
                      role="curator" if (curator and k == 0) else "press")
            for k in range(n_publishers)
        ]
    return Cluster(
        id=cid, label=f"label {cid}", importance=importance, category=category,
        european=european, finance_consulting=finance, reason="test",
        items=items, covered_before=covered_before, new_development=new_development,
    )


@pytest.fixture
def now() -> datetime:
    return NOW


# ---------------------------------------------------------------- edition dicts

def make_story(sid: str, *, headline: str | None = None, urls: list[str] | None = None,
               sources: list[dict] | None = None, category: str = "products", **overrides) -> dict:
    """A schema-valid Story dict. `urls` sets item_urls; sources default to one link per url."""
    urls = urls if urls is not None else [f"https://example.com/{sid}"]
    s = {
        "id": sid,
        "headline": headline if headline is not None else f"Headline {sid}",
        "summary": f"Summary of {sid}.",
        "category": category,
        "sources": sources if sources is not None else [{"name": f"Pub {sid}", "url": u} for u in urls],
        "importance": 7,
        "material": "fulltext",
        "item_urls": list(urls),
        "item_titles": [f"Title {sid}"] * len(urls),
    }
    s.update(overrides)
    return s


def make_brief(bid: str, **overrides) -> dict:
    """A schema-valid Brief dict (a Story without category)."""
    b = make_story(bid, **overrides)
    b.pop("category", None)
    return b


def make_cluster_record(cid: str, section: str | None = None) -> dict:
    return {
        "id": cid, "label": f"label {cid}", "importance": 6, "category": "products",
        "european": section == "europe", "finance_consulting": section == "finance",
        "reason": "test", "covered_before": False, "new_development": False,
        "n_items": 1, "n_publishers": 1, "section": section,
        "items": [{"title": f"Title {cid}", "url": f"https://example.com/{cid}"}],
    }


def make_edition(*, n_main: int = 5, n_europe: int = 1, n_finance: int = 0, prefix: str = "c",
                 date_str: str = "2026-11-04", edition_number: int = 1) -> dict:
    """A schema-valid Edition dict: lead + n_main main stories + briefs + cluster records."""
    lead = make_story(f"{prefix}0", category="models")
    main = [make_story(f"{prefix}{i}") for i in range(1, n_main + 1)]
    europe = [make_brief(f"{prefix}e{i}") for i in range(n_europe)]
    finance = [make_brief(f"{prefix}f{i}") for i in range(n_finance)]
    clusters = ([make_cluster_record(lead["id"], "lead")]
                + [make_cluster_record(s["id"], "main") for s in main]
                + [make_cluster_record(b["id"], "europe") for b in europe]
                + [make_cluster_record(b["id"], "finance") for b in finance]
                + [make_cluster_record(f"{prefix}x", None)])
    return {
        "schema_version": 1,
        "publication": "AI Daily",
        "date": date_str,
        "edition_number": edition_number,
        "generated_at": f"{date_str}T06:00:00+00:00",
        "lead": lead,
        "main": main,
        "europe_brief": europe,
        "finance_brief": finance,
        "clusters": clusters,
        "models": {"triage": "claude-haiku-5-5", "write": "claude-sonnet-5-5"},
        "stats": {"items": 42},
    }
