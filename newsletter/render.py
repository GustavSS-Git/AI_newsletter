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


def _env(templates_dir: Path) -> Environment:
    env = Environment(loader=FileSystemLoader(templates_dir), autoescape=select_autoescape(["html", "j2"]))
    env.filters["category_label"] = lambda c: CATEGORY_LABELS.get(c, c)
    env.filters["long_date"] = lambda d: date.fromisoformat(d).strftime("%A, %B %-d, %Y")
    return env


def _write(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def load_editions(editions_dir: Path) -> list[dict]:
    """All saved editions, oldest first. Unreadable files are skipped."""
    out = []
    for f in sorted(editions_dir.glob("*.json")):
        try:
            date.fromisoformat(f.stem)
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            continue
    return out


def render_site(edition: dict, cfg: dict, site_dir: Path, templates_dir: Path | None = None,
                editions_dir: Path | None = None) -> Path:
    """Render index.html (this edition), style.css and 404.html. With `editions_dir`, also
    rebuild the full archive: archive/YYYY-MM-DD.html for every saved edition plus
    archive/index.html. Rebuilding everything keeps old pages in sync with template changes."""
    templates_dir = templates_dir or ROOT / "templates"
    env = _env(templates_dir)
    pub = cfg["publication"]
    username = (cfg.get("email") or {}).get("buttondown_username", "").strip()
    env.globals["signup_action"] = (
        f"https://buttondown.com/api/emails/embed-subscribe/{username}" if username else None)
    site_dir.mkdir(parents=True, exist_ok=True)

    out = site_dir / "index.html"
    _write(out, env.get_template("edition.html.j2").render(edition=edition, pub=pub, root="", canonical_path="/"))
    _write(site_dir / "404.html", env.get_template("404.html.j2").render(pub=pub, root="/"))
    shutil.copyfile(templates_dir / "style.css", site_dir / "style.css")

    if editions_dir is not None:
        editions = load_editions(editions_dir)
        # Make sure the edition being published is included even if not yet saved.
        if not any(e.get("date") == edition["date"] for e in editions):
            editions.append(edition)
            editions.sort(key=lambda e: e["date"])
        dates = [e["date"] for e in editions]
        tpl = env.get_template("edition.html.j2")
        for i, e in enumerate(editions):
            nav = {"prev": dates[i - 1] if i > 0 else None, "next": dates[i + 1] if i + 1 < len(dates) else None}
            _write(site_dir / "archive" / f"{e['date']}.html",
                   tpl.render(edition=e, pub=pub, root="../", nav=nav, canonical_path=f"/archive/{e['date']}.html"))
        listing = [{"date": e["date"], "edition_number": e.get("edition_number"),
                    "lead_headline": (e.get("lead") or {}).get("headline", "")} for e in reversed(editions)]
        _write(site_dir / "archive" / "index.html",
               env.get_template("archive.html.j2").render(editions=listing, pub=pub, root="../",
                                                          canonical_path="/archive/"))
    return out
