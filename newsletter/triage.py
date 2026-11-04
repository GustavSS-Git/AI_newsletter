"""LLM call 1: cluster items and score importance (cheap model)."""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Literal

import anthropic
from pydantic import BaseModel

from .filter import cap_items
from .llm import Usage, count_tokens, load_prompt, parse_call
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


def fit_token_budget(items: list[Item], today: date, recent_headlines: list[str], *, cfg: dict,
                     client: anthropic.Anthropic) -> list[Item]:
    """Trim the lowest-priority items until the triage prompt fits max_triage_input_tokens
    (keeps Haiku in its cheaper <=100K-token price tier). count_tokens is free."""
    budget = cfg["pipeline"].get("max_triage_input_tokens")
    if not budget:
        return items
    model, system = cfg["models"]["triage"], load_prompt("triage.md")
    for _ in range(5):
        n_tok = count_tokens(client, model, system, build_user_message(items, today, recent_headlines))
        if n_tok <= budget:
            log.info("triage input: %d items, %d tokens (budget %d)", len(items), n_tok, budget)
            return items
        target = max(1, int(len(items) * budget / n_tok * 0.97))
        log.warning("triage input %d tokens > budget %d; trimming %d → %d items", n_tok, budget, len(items), target)
        items = cap_items(items, target)
    return items


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
