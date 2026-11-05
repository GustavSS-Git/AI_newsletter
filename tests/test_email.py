from newsletter.email import build_email, subject_for
from tests.conftest import make_edition

CFG = {"publication": {"name": "AI Daily", "tagline": "Tagline.", "footer": "Curated and summarized with AI",
                       "base_url": "https://news.example.com"}}


def test_subject_is_name_and_date():
    ed = make_edition(date_str="2026-11-05")
    ed["lead"]["headline"] = "Acme ships Atlas 3"
    assert subject_for(ed, CFG) == "AI Daily · Thursday, November 5"


def test_email_contains_all_stories_links_and_web_url():
    ed = make_edition(n_main=3, n_europe=1, n_finance=1)
    subject, html = build_email(ed, CFG)
    for s in [ed["lead"], *ed["main"], *ed["europe_brief"], *ed["finance_brief"]]:
        assert s["headline"] in html
        for src in s["sources"]:
            assert src["url"] in html
    assert "https://news.example.com/archive/2026-11-04" in html
    assert "Europe" in html and "Business &amp; Finance" in html
    assert "<style" not in html            # inline styles only


def test_email_omits_empty_brief_sections_and_escapes():
    ed = make_edition(n_europe=0, n_finance=0)
    ed["lead"]["headline"] = "<script>x</script>"
    _, html = build_email(ed, CFG)
    assert "Business &amp; Finance" not in html and ">Europe<" not in html
    assert "<script>x" not in html
