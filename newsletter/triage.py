"""LLM call 1: cluster items and score importance (cheap model)."""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Literal

import anthropic
from pydantic import BaseModel

from .llm import Usage, load_prompt, parse_call
from .models import CATEGORIES, Cluster, Item

log = logging.getLogger(__name__)


class TriageCluster(BaseModel):
    item_ids: list[str]
    label: str
    importance: int
    category: Literal["models", "products", "research", "business/funding", "policy/regulation", "other"]
    european: bool
    finance_consulting: bool
    covered_before: bool
    new_development: bool
    reason: str


class TriageOutput(BaseModel):
    clusters: list[TriageCluster]


def build_user_message(items: list[Item], today: date, recent_headlines: list[str]) -> str:
    rows = []
    for it in items:
        row = {
            "id": it.id, "title": it.title, "snippet": it.snippet[:300], "source": it.source,
            "role": it.role, "publisher": it.publisher,
        }
        also = [a["publisher"] or a["source"] for a in it.extra.get("also_in", [])]
        if also:
            row["also_in"] = also
        if it.extra.get("points"):
            row["hn_points"] = it.extra["points"]
        if it.extra.get("upvotes"):
            row["hf_upvotes"] = it.extra["upvotes"]
        if it.tags:
            row["source_tags"] = it.tags
        if not row["snippet"]:
            del row["snippet"]
        rows.append(row)
    payload = {"today": today.isoformat(), "recent_headlines": recent_headlines, "items": rows}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def to_clusters(out: TriageOutput, items: list[Item]) -> list[Cluster]:
    """Validate model output against the real item list: unknown ids dropped, each item in at
    most one cluster (first wins), empty clusters dropped, scores clamped to 1–10."""
    by_id = {it.id: it for it in items}
    used: set[str] = set()
    clusters = []
    for tc in out.clusters:
        members = []
        for iid in tc.item_ids:
            if iid in by_id and iid not in used:
                used.add(iid)
                members.append(by_id[iid])
        if not members:
            continue
        clusters.append(Cluster(
            id=f"c{len(clusters) + 1:02d}",
            label=tc.label.strip(),
            importance=max(1, min(10, int(tc.importance))),
            category=tc.category if tc.category in CATEGORIES else "other",
            european=tc.european,
            finance_consulting=tc.finance_consulting,
            reason=tc.reason.strip(),
            items=members,
            covered_before=tc.covered_before,
            new_development=tc.new_development and tc.covered_before,
        ))
    unknown = sum(1 for tc in out.clusters for i in tc.item_ids if i not in by_id)
    if unknown:
        log.warning("triage referenced %d unknown item ids (ignored)", unknown)
    return clusters


def triage(items: list[Item], today: date, recent_headlines: list[str], *, cfg: dict,
           client: anthropic.Anthropic, usage: Usage) -> list[Cluster]:
    m = cfg["models"]
    out = parse_call(
        client=client, model=m["triage"], system=load_prompt("triage.md"),
        user=build_user_message(items, today, recent_headlines),
        schema=TriageOutput, effort=m.get("triage_effort", "medium"), max_tokens=64000,
        step="triage", usage=usage, pricing=m.get("pricing", {}),
    )
    return to_clusters(out, items)
