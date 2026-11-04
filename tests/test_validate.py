from __future__ import annotations

import copy

import pytest
import requests

from newsletter import validate as V
from newsletter.validate import check_link, validate_edition
from tests.conftest import make_edition, make_story

CFG = {"pipeline": {"min_main_stories": 4}, "http": {"timeout_seconds": 1, "user_agent": "test"}}


def fake_checker(url: str) -> bool:
    return "broken" not in url


def run(edition, previous=None):
    return validate_edition(edition, CFG, previous=previous, link_checker=fake_checker)


@pytest.fixture
def ed():
    return make_edition()


# ---------------------------------------------------------------- valid

def test_valid_edition_has_no_errors(ed):
    assert run(ed) == []


def test_valid_edition_with_finance_brief(ed):
    ed = make_edition(n_finance=2)
    assert run(ed) == []


# ---------------------------------------------------------------- schema

def _assert_schema_only(errors):
    assert len(errors) == 1
    assert errors[0].startswith("schema:")


def test_missing_top_level_field(ed):
    del ed["generated_at"]
    _assert_schema_only(run(ed))


def test_missing_story_field(ed):
    del ed["main"][0]["summary"]
    _assert_schema_only(run(ed))


def test_extra_unknown_field(ed):
    ed["lead"]["bogus"] = 1
    _assert_schema_only(run(ed))


def test_extra_unknown_top_level_field(ed):
    ed["surprise"] = True
    _assert_schema_only(run(ed))


def test_wrong_category_literal(ed):
    ed["main"][1]["category"] = "gossip"
    _assert_schema_only(run(ed))


def test_empty_sources_list(ed):
    ed["main"][2]["sources"] = []
    _assert_schema_only(run(ed))


def test_schema_failure_returns_early_without_checking_links(ed):
    calls = []
    del ed["lead"]["headline"]
    ed["main"] = []  # would also fail the count check if reached
    errors = validate_edition(ed, CFG, link_checker=lambda u: calls.append(u) or True)
    _assert_schema_only(errors)
    assert calls == []


# ---------------------------------------------------------------- story count

def test_below_min_story_count():
    ed = make_edition(n_main=2)  # lead + 2 = 3 < 4
    errors = run(ed)
    assert any("only 3 main stories" in e for e in errors)


def test_exactly_min_story_count_ok():
    assert run(make_edition(n_main=3)) == []


# ---------------------------------------------------------------- empty fields

@pytest.mark.parametrize("field", ["headline", "summary", "why_it_matters"])
@pytest.mark.parametrize("value", ["", "   \n\t"])
def test_empty_story_field(ed, field, value):
    ed["main"][0][field] = value
    errors = run(ed)
    sid = ed["main"][0]["id"]
    assert any(sid in e and field in e for e in errors), errors


def test_empty_lead_headline(ed):
    ed["lead"]["headline"] = " "
    assert any(ed["lead"]["id"] in e and "headline" in e for e in run(ed))


@pytest.mark.parametrize("field", ["headline", "summary"])
def test_empty_brief_field(ed, field):
    ed["europe_brief"][0][field] = "  "
    bid = ed["europe_brief"][0]["id"]
    errors = run(ed)
    assert any("europe_brief" in e and bid in e and field in e for e in errors), errors


def test_empty_finance_brief_field():
    ed = make_edition(n_finance=1)
    ed["finance_brief"][0]["summary"] = ""
    bid = ed["finance_brief"][0]["id"]
    assert any("finance_brief" in e and bid in e for e in run(ed))


def test_source_with_empty_url(ed):
    ed["main"][3]["sources"].append({"name": "Nobody", "url": "  "})
    sid = ed["main"][3]["id"]
    errors = run(ed)
    assert any(sid in e and "empty name or url" in e for e in errors), errors


def test_source_with_empty_name(ed):
    ed["main"][3]["sources"][0]["name"] = ""
    sid = ed["main"][3]["id"]
    assert any(sid in e and "empty name or url" in e for e in run(ed))


# ---------------------------------------------------------------- links

def test_only_link_broken(ed):
    ed["main"][0]["sources"] = [{"name": "X", "url": "https://broken.example.com/a"}]
    sid = ed["main"][0]["id"]
    errors = run(ed)
    assert any(sid in e and "no working link" in e for e in errors), errors


def test_brief_only_link_broken(ed):
    ed["europe_brief"][0]["sources"] = [{"name": "X", "url": "https://broken.example.com/eu"}]
    bid = ed["europe_brief"][0]["id"]
    assert any(bid in e and "no working link" in e for e in run(ed))


def test_one_broken_one_working_link_ok(ed):
    ed["main"][0]["sources"] = [{"name": "X", "url": "https://broken.example.com/a"},
                                {"name": "Y", "url": "https://fine.example.com/a"}]
    assert run(ed) == []


def test_default_checker_used_when_none_given(ed, monkeypatch):
    seen = []
    monkeypatch.setattr(V, "check_link", lambda url, timeout, ua: seen.append((url, timeout, ua)) or True)
    assert validate_edition(ed, CFG) == []
    assert seen and all(t == 1 and ua == "test" for _, t, ua in seen)


# ---------------------------------------------------------------- vs previous edition

def test_identical_to_previous(ed):
    assert any("identical" in e for e in run(ed, previous=copy.deepcopy(ed)))


def test_identical_to_previous_modulo_tracking_params_and_slash(ed):
    prev = copy.deepcopy(ed)
    for s in [prev["lead"], *prev["main"], *prev["europe_brief"]]:
        s["item_urls"] = [u + "/?utm_source=rss&fbclid=abc" for u in s["item_urls"]]
        s["headline"] = "Reworded " + s["headline"]
    errors = run(ed, previous=prev)
    assert any("identical to the previous edition" in e for e in errors), errors


def test_same_headlines_different_urls(ed):
    prev = copy.deepcopy(ed)
    for s in [prev["lead"], *prev["main"], *prev["europe_brief"]]:
        s["item_urls"] = [u.replace("example.com", "other.org") for u in s["item_urls"]]
    errors = run(ed, previous=prev)
    assert any("headlines are identical" in e for e in errors), errors


def test_different_stories_ok(ed):
    prev = make_edition(prefix="old", date_str="2026-11-03")
    assert run(ed, previous=prev) == []


def test_partial_overlap_with_previous_ok(ed):
    prev = make_edition(prefix="old", date_str="2026-11-03")
    prev["main"][0] = copy.deepcopy(ed["main"][0])
    assert run(ed, previous=prev) == []


def test_previous_none_ok(ed):
    assert run(ed, previous=None) == []


# ---------------------------------------------------------------- check_link

class Resp:
    def __init__(self, status):
        self.status_code = status
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def http(monkeypatch):
    """Configure fake requests.head/get. Returns a dict recording calls."""
    state = {"head": None, "get": None, "calls": []}

    def mk(kind):
        def f(url, **kw):
            state["calls"].append((kind, url, kw))
            r = state[kind]
            if isinstance(r, Exception):
                raise r
            if r is None:
                raise AssertionError(f"unexpected {kind} call")
            return Resp(r)
        return f

    monkeypatch.setattr(requests, "head", mk("head"))
    monkeypatch.setattr(requests, "get", mk("get"))
    return state


def test_check_link_200(http):
    http["head"] = 200
    assert check_link("https://x.test/a") is True
    assert [c[0] for c in http["calls"]] == ["head"]


def test_check_link_redirect_followed(http):
    http["head"] = 200
    check_link("https://x.test/a", timeout=3, user_agent="UA")
    _, _, kw = http["calls"][0]
    assert kw["allow_redirects"] is True and kw["timeout"] == 3 and kw["headers"]["User-Agent"] == "UA"


def test_check_link_404_then_get_404(http):
    http["head"], http["get"] = 404, 404
    assert check_link("https://x.test/a") is False
    assert [c[0] for c in http["calls"]] == ["head", "get"]


def test_check_link_head_404_get_200(http):
    http["head"], http["get"] = 404, 200
    assert check_link("https://x.test/a") is True


@pytest.mark.parametrize("code", [403, 429, 999])
def test_check_link_bot_block_counts_as_working(http, code):
    http["head"] = code
    assert check_link("https://x.test/a") is True


def test_check_link_head_500_get_403(http):
    http["head"], http["get"] = 500, 403
    assert check_link("https://x.test/a") is True


def test_check_link_connection_error(http):
    http["head"] = requests.ConnectionError("boom")
    assert check_link("https://x.test/a") is False


def test_check_link_timeout_on_get(http):
    http["head"], http["get"] = 404, requests.Timeout("slow")
    assert check_link("https://x.test/a") is False
