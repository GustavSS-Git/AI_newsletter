"""Assemble the edition dict, save it as JSON, and render the static site."""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import ROOT
from .enrich import StoryContext
from .models import Cluster
from .schema import SCHEMA_VERSION
from .select import Selection

CATEGORY_LABELS = {
    "models": "Models", "products": "Products", "research": "Research",
    "business/funding": "Business & Funding", "policy/regulation": "Policy & Regulation", "other": "Other",
}


def edition_number(editions_dir: Path, today: date) -> int:
    """Re-running a day keeps its number; otherwise number = previous editions + 1."""
    existing = editions_dir / f"{today.isoformat()}.json"
    if existing.exists():
        try:
            return int(json.loads(existing.read_text(encoding="utf-8"))["edition_number"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
    earlier = 0
    for f in editions_dir.glob("*.json"):
        try:
            if date.fromisoformat(f.stem) < today:
                earlier += 1
        except ValueError:
            continue
    return earlier + 1


def _entry(c: Cluster, ctx: StoryContext, w: dict, brief: bool) -> dict:
    e = {
        "id": c.id,
        "headline": w.get("headline", "").strip(),
        "summary": w.get("summary", "").strip(),
        "sources": ctx.links,
        "importance": c.importance,
        "material": ctx.text_source,
        "item_urls": [i.url for i in c.items],
        "item_titles": [i.title for i in c.items],
    }
    if not brief:
        e["category"] = w.get("category") or c.category
    return e


def build_edition(*, today: date, now: datetime, cfg: dict, selection: Selection,
                  contexts: dict[str, StoryContext], written: dict[str, dict],
                  clusters: list[Cluster], editions_dir: Path, stats: dict) -> dict:
    def entry(c, brief=False):
        return _entry(c, contexts[c.id], written.get(c.id, {}), brief)

    records = []
    for c in sorted(clusters, key=lambda c: (-c.importance, c.id)):
        r = c.to_record()
        r["section"] = selection.section_of(c.id)
        records.append(r)

    return {
        "schema_version": SCHEMA_VERSION,
        "publication": cfg["publication"]["name"],
        "date": today.isoformat(),
        "edition_number": edition_number(editions_dir, today),
        "generated_at": now.isoformat(timespec="seconds"),
        "lead": entry(selection.lead),
        "main": [entry(c) for c in selection.main],
        "europe_brief": [entry(c, brief=True) for c in selection.europe],
        "finance_brief": [entry(c, brief=True) for c in selection.finance],
        "clusters": records,
        "models": {"triage": cfg["models"]["triage"], "write": cfg["models"]["write"]},
        "stats": stats,
    }


def save_edition(edition: dict, editions_dir: Path) -> Path:
    editions_dir.mkdir(parents=True, exist_ok=True)
    path = editions_dir / f"{edition['date']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(edition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def render_site(edition: dict, cfg: dict, site_dir: Path, templates_dir: Path | None = None) -> Path:
    templates_dir = templates_dir or ROOT / "templates"
    env = Environment(loader=FileSystemLoader(templates_dir), autoescape=select_autoescape(["html", "j2"]))
    env.filters["category_label"] = lambda c: CATEGORY_LABELS.get(c, c)
    env.filters["long_date"] = lambda d: date.fromisoformat(d).strftime("%A, %B %-d, %Y")
    html = env.get_template("edition.html.j2").render(edition=edition, pub=cfg["publication"])
    site_dir.mkdir(parents=True, exist_ok=True)
    out = site_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    shutil.copyfile(templates_dir / "style.css", site_dir / "style.css")
    return out
