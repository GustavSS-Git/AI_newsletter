"""LLM call 2: write headlines and summaries for the selected stories (stronger model)."""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Literal

import anthropic
from pydantic import BaseModel

from .enrich import StoryContext
from .llm import Usage, count_tokens, load_prompt, parse_call
from .select import Selection

log = logging.getLogger(__name__)

Category = Literal["models", "products", "research", "business/funding", "policy/regulation", "other"]
SECTION_NAMES = {"lead": "lead", "main": "main", "europe": "europe", "finance": "finance"}


class WrittenStory(BaseModel):
    story_id: str
    headline: str
    summary: str
    why_it_matters: str
    category: Category


class WrittenBrief(BaseModel):
    story_id: str
    headline: str
    summary: str


class WriteOutput(BaseModel):
    stories: list[WrittenStory]
    briefs: list[WrittenBrief]


def build_user_message(selection: Selection, contexts: dict[str, StoryContext], today: date) -> str:
    stories = []
    for c in selection.all:
        ctx = contexts[c.id]
        sources = [{"publisher": t["publisher"], "text": t["text"]} for t in ctx.texts]
        if ctx.text_source != "fulltext":
            sources += [{"publisher": s["publisher"], "snippet": s["snippet"]} for s in ctx.snippets]
        stories.append({
            "story_id": c.id,
            "section": selection.section_of(c.id),
            "category": c.category,
            "editor_label": c.label,
            "material": ctx.text_source,
            "sources": sources,
            "headlines": ctx.headlines[:12],
        })
    return json.dumps({"today": today.isoformat(), "stories": stories}, ensure_ascii=False, indent=1)


def estimate_write_cost(selection: Selection, contexts: dict[str, StoryContext], cfg: dict,
                        client: anthropic.Anthropic, today: date | None = None) -> float:
    """Exact input tokens via count_tokens (free); output assumed ≤ 1,200 tokens per story
    including thinking — deliberately pessimistic."""
    m = cfg["models"]
    model = m["write"]
    user = build_user_message(selection, contexts, today or date.today())
    n_in = count_tokens(client, model, load_prompt("write.md"), user)
    n_out = 1200 * len(selection.all)
    pin, pout = m.get("pricing", {}).get(model, (0.0, 0.0))
    return n_in / 1e6 * pin + n_out / 1e6 * pout


def write_edition(selection: Selection, contexts: dict[str, StoryContext], *, cfg: dict,
                  client: anthropic.Anthropic, usage: Usage, today: date | None = None
                  ) -> dict[str, dict]:
    """Returns {cluster_id: {headline, summary, why_it_matters?, category?}}."""
    m = cfg["models"]
    out = parse_call(
        client=client, model=m["write"], system=load_prompt("write.md"),
        user=build_user_message(selection, contexts, today or date.today()),
        schema=WriteOutput, effort=m.get("write_effort", "medium"), max_tokens=64000,
        step="write", usage=usage, pricing=m.get("pricing", {}),
    )
    written: dict[str, dict] = {}
    for s in out.stories:
        written[s.story_id] = s.model_dump()
    for b in out.briefs:
        written.setdefault(b.story_id, b.model_dump())
    missing = [c.id for c in selection.all if c.id not in written]
    if missing:
        log.warning("writer omitted stories: %s", missing)
    return written
