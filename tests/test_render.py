from __future__ import annotations

import json
from datetime import date

import pytest

from newsletter.config import ROOT
from newsletter.render import edition_number, render_site, save_edition
from tests.conftest import make_edition

CFG = {"publication": {"name": "AI Daily", "tagline": "The day's most important AI news, briefly.",
                       "footer": "Curated and summarized with AI"}}
TODAY = date(2026, 11, 4)


def _write(d, name, number=None):
    p = d / name
    p.write_text(json.dumps({"edition_number": number} if number is not None else {}), encoding="utf-8")
    return p


# ---------------------------------------------------------------- edition_number

def test_edition_number_empty_dir(tmp_path):
    assert edition_number(tmp_path, TODAY) == 1


def test_edition_number_missing_dir(tmp_path):
    assert edition_number(tmp_path / "nope", TODAY) == 1


def test_edition_number_two_earlier(tmp_path):
    _write(tmp_path, "2026-11-02.json", 1)
    _write(tmp_path, "2026-11-03.json", 2)
    assert edition_number(tmp_path, TODAY) == 3


def test_edition_number_rerun_keeps_stored_number(tmp_path):
    _write(tmp_path, "2026-11-02.json", 1)
    _write(tmp_path, "2026-11-03.json", 2)
    _write(tmp_path, "2026-11-04.json", 17)
    assert edition_number(tmp_path, TODAY) == 17


def test_edition_number_rerun_with_corrupt_file_falls_back_to_count(tmp_path):
    _write(tmp_path, "2026-11-03.json", 1)
    (tmp_path / "2026-11-04.json").write_text("{not json", encoding="utf-8")
    assert edition_number(tmp_path, TODAY) == 2


def test_edition_number_ignores_later_and_non_date_files(tmp_path):
    _write(tmp_path, "2026-11-01.json", 1)
    _write(tmp_path, "2026-11-05.json", 3)
    _write(tmp_path, "2026-12-01.json", 4)
    _write(tmp_path, "latest.json")
    _write(tmp_path, "notes.txt")
    _write(tmp_path, "2026-11-02.json.tmp")
    assert edition_number(tmp_path, TODAY) == 2


# ---------------------------------------------------------------- save_edition

def test_save_edition_roundtrip(tmp_path):
    ed = make_edition()
    ed["lead"]["headline"] = "Ünïcode — “quotes” & <tags>"
    out = save_edition(ed, tmp_path / "editions")
    assert out == tmp_path / "editions" / "2026-11-04.json"
    assert json.loads(out.read_text(encoding="utf-8")) == ed
    assert not list((tmp_path / "editions").glob("*.tmp"))


def test_save_edition_overwrites(tmp_path):
    ed = make_edition()
    save_edition(ed, tmp_path)
    ed["edition_number"] = 9
    out = save_edition(ed, tmp_path)
    assert json.loads(out.read_text(encoding="utf-8"))["edition_number"] == 9


# ---------------------------------------------------------------- render_site

def _render(tmp_path, ed):
    out = render_site(ed, CFG, tmp_path / "site")
    return out, out.read_text(encoding="utf-8")


def test_render_basic(tmp_path):
    ed = make_edition()
    out, html = _render(tmp_path, ed)
    assert out == tmp_path / "site" / "index.html"
    assert "AI Daily" in html
    assert ed["lead"]["headline"] in html
    for s in ed["main"]:
        assert s["headline"] in html
    assert "Curated and summarized with AI" in html
    assert "Wednesday, November 4, 2026" in html
    assert "No. 1" in html


def test_render_copies_stylesheet(tmp_path):
    _render(tmp_path, make_edition())
    css = tmp_path / "site" / "style.css"
    assert css.exists()
    assert css.read_bytes() == (ROOT / "templates" / "style.css").read_bytes()


def test_europe_section_only_when_nonempty(tmp_path):
    _, html = _render(tmp_path, make_edition(n_europe=1))
    assert 'id="europe-h"' in html and ">Europe<" in html
    _, html = _render(tmp_path, make_edition(n_europe=0))
    assert 'id="europe-h"' not in html and ">Europe<" not in html


def test_finance_section_only_when_nonempty(tmp_path):
    _, html = _render(tmp_path, make_edition(n_finance=0))
    assert "Business &amp; Finance" not in html and 'id="finance-h"' not in html
    ed = make_edition(n_finance=1)
    _, html = _render(tmp_path, ed)
    assert "Business &amp; Finance" in html
    assert ed["finance_brief"][0]["headline"] in html


def test_headline_is_html_escaped(tmp_path):
    ed = make_edition()
    ed["lead"]["headline"] = "Model <script>alert(1)</script> & co"
    ed["main"][0]["summary"] = '<img src=x onerror="x()">'
    _, html = _render(tmp_path, ed)
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in html
    assert "<img" not in html


def test_headline_only_note(tmp_path):
    ed = make_edition()
    ed["main"][0]["material"] = "headline_only"
    _, html = _render(tmp_path, ed)
    assert "Summary based on headlines only" in html


def test_category_label(tmp_path):
    ed = make_edition()
    ed["main"][0]["category"] = "business/funding"
    _, html = _render(tmp_path, ed)
    assert "Business &amp; Funding" in html


# ---------------------------------------------------------------- archive (v1)

def _save(ed_dir, d, n):
    ed = make_edition(date_str=d, edition_number=n)
    ed["lead"]["headline"] = f"Lead {d}"
    save_edition(ed, ed_dir)
    return ed


def test_render_site_builds_archive_and_404(tmp_path):
    ed_dir, site = tmp_path / "editions", tmp_path / "site"
    _save(ed_dir, "2026-11-03", 1)
    latest = _save(ed_dir, "2026-11-04", 2)
    render_site(latest, CFG, site, editions_dir=ed_dir)

    assert (site / "404.html").exists()
    index = (site / "index.html").read_text()
    assert "Lead 2026-11-04" in index and 'href="archive/"' in index and 'href="style.css"' in index

    listing = (site / "archive" / "index.html").read_text()
    assert listing.index("Lead 2026-11-04") < listing.index("Lead 2026-11-03")  # newest first
    assert 'href="2026-11-03.html"' in listing and 'href="../style.css"' in listing

    older = (site / "archive" / "2026-11-03.html").read_text()
    assert 'href="2026-11-04.html"' in older and "← Previous" not in older   # next only
    newer = (site / "archive" / "2026-11-04.html").read_text()
    assert 'href="2026-11-03.html"' in newer and "Next →" not in newer


def test_render_site_includes_unsaved_edition_in_archive(tmp_path):
    ed_dir, site = tmp_path / "editions", tmp_path / "site"
    _save(ed_dir, "2026-11-03", 1)
    new = make_edition()
    new["date"], new["edition_number"] = "2026-11-04", 2
    render_site(new, CFG, site, editions_dir=ed_dir)
    assert (site / "archive" / "2026-11-04.html").exists()


def test_canonical_link_uses_base_url(tmp_path):
    cfg = {"publication": {**CFG["publication"], "base_url": "https://news.example.com"}}
    ed = make_edition()
    render_site(ed, cfg, tmp_path / "site", editions_dir=tmp_path / "none")
    assert '<link rel="canonical" href="https://news.example.com/">' in (tmp_path / "site" / "index.html").read_text()


def test_signup_form_only_when_username_set(tmp_path):
    ed = make_edition()
    render_site(ed, CFG, tmp_path / "a")
    assert "embed-subscribe" not in (tmp_path / "a" / "index.html").read_text()
    cfg = {**CFG, "email": {"buttondown_username": "aidaily"}}
    render_site(ed, cfg, tmp_path / "b")
    html = (tmp_path / "b" / "index.html").read_text()
    assert 'action="https://buttondown.com/api/emails/embed-subscribe/aidaily"' in html
    assert 'name="email"' in html and 'name="embed" value="1"' in html
