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
