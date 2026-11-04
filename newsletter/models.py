"""Shared data structures."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class Item:
    id: str                 # short stable id used in LLM prompts, e.g. "i012"
    title: str
    url: str                # link as given by the source (may be a Google News redirect)
    source: str             # source name from config, e.g. "TechCrunch AI"
    role: str               # curator | primary | press
    published: datetime     # timezone-aware UTC
    snippet: str = ""
    publisher: str = ""     # actual outlet (differs from source for Google News / Techmeme / HN)
    publisher_url: str = "" # outlet homepage/domain, when known
    tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)  # points, upvotes, etc.

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat()
        return d


CATEGORIES = ("models", "products", "research", "business/funding", "policy/regulation", "other")


@dataclass
class Cluster:
    id: str                       # "c01" …
    label: str                    # short neutral description of the event (from triage)
    importance: int               # 1–10
    category: str
    european: bool
    finance_consulting: bool
    reason: str
    items: list[Item] = field(default_factory=list)
    covered_before: bool = False  # triage: same event as a recent edition's story
    new_development: bool = False # triage: …but with a substantial new development

    @property
    def publishers(self) -> set[str]:
        pubs = set()
        for it in self.items:
            pubs.add(it.publisher or it.source)
            pubs.update(a["publisher"] or a["source"] for a in it.extra.get("also_in", []))
        return pubs

    @property
    def has_curator(self) -> bool:
        return any(
            it.role == "curator" or any(a["role"] == "curator" for a in it.extra.get("also_in", []))
            for it in self.items
        )

    def to_record(self) -> dict:
        return {
            "id": self.id, "label": self.label, "importance": self.importance,
            "category": self.category, "european": self.european,
            "finance_consulting": self.finance_consulting, "reason": self.reason,
            "covered_before": self.covered_before, "new_development": self.new_development,
            "n_items": len(self.items), "n_publishers": len(self.publishers),
            "items": [{"title": i.title, "url": i.url, "source": i.source, "publisher": i.publisher}
                      for i in self.items],
        }
