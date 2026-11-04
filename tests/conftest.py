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
