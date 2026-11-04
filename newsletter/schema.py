"""Edition JSON schema (pydantic). editions/YYYY-MM-DD.json must validate against `Edition`."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 2  # v2: removed why_it_matters (2026-11-04)
Category = Literal["models", "products", "research", "business/funding", "policy/regulation", "other"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Link(Strict):
    name: str
    url: str


class Story(Strict):
    id: str                       # cluster id within this edition
    headline: str
    summary: str
    category: Category
    sources: list[Link] = Field(min_length=1)
    importance: int
    material: Literal["fulltext", "snippet", "headline_only"]
    item_urls: list[str]          # all item URLs in the cluster — used by the already-covered check
    item_titles: list[str]


class Brief(Strict):
    id: str
    headline: str
    summary: str
    sources: list[Link] = Field(min_length=1)
    importance: int
    material: Literal["fulltext", "snippet", "headline_only"]
    item_urls: list[str]
    item_titles: list[str]


class ClusterRecord(Strict):
    """Every triage cluster, selected or not — v3 highlights are computed from these."""
    id: str
    label: str
    importance: int
    category: str
    european: bool
    finance_consulting: bool
    reason: str
    covered_before: bool
    new_development: bool
    n_items: int
    n_publishers: int
    section: Literal["lead", "main", "europe", "finance"] | None
    items: list[dict]


class Edition(Strict):
    schema_version: int = SCHEMA_VERSION
    publication: str
    date: str                     # YYYY-MM-DD (UTC)
    edition_number: int
    generated_at: str             # ISO timestamp UTC
    lead: Story
    main: list[Story]
    europe_brief: list[Brief]
    finance_brief: list[Brief]
    clusters: list[ClusterRecord]
    models: dict[str, str]
    stats: dict
