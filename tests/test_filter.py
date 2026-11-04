from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from newsletter.filter import (
    assign_ids, covered_index, dedupe, drop_covered, load_recent_editions, normalize_url,
    titles_match, within_window,
)
from tests.conftest import NOW, make_item

THRESHOLD = 88  # config.yaml pipeline.title_similarity
WINDOW_H = 30   # config.yaml pipeline.window_hours


# ---------------------------------------------------------------- normalize_url

class TestNormalizeUrl:
    def test_strips_utm_params(self):
        assert normalize_url("https://example.com/a?utm_source=x&utm_medium=rss&utm_campaign=y") \
            == "https://example.com/a"

    @pytest.mark.parametrize("param", ["fbclid=abc", "ref=hn", "gclid=1", "mkt_tok=z", "ref_src=twsrc"])
    def test_strips_other_tracking_params(self, param):
        assert normalize_url(f"https://example.com/a?{param}") == "https://example.com/a"

    def test_keeps_and_sorts_non_tracking_params(self):
        assert normalize_url("https://example.com/a?z=1&utm_source=x&a=2&fbclid=q") \
            == "https://example.com/a?a=2&z=1"
        assert normalize_url("https://example.com/a?b=1&a=2") == normalize_url("https://example.com/a?a=2&b=1")

    def test_keeps_meaningful_id_param(self):
        assert normalize_url("https://news.ycombinator.com/item?id=123") \
            != normalize_url("https://news.ycombinator.com/item?id=456")

    def test_trailing_slash(self):
        assert normalize_url("https://example.com/a/") == normalize_url("https://example.com/a")
        assert normalize_url("https://example.com/") == "https://example.com"

    def test_www_and_host_case(self):
        assert normalize_url("https://www.Example.COM/a") == "https://example.com/a"

    def test_fragment_removed(self):
        assert normalize_url("https://example.com/a#section-2") == "https://example.com/a"

    def test_http_equals_https(self):
        assert normalize_url("http://example.com/a") == normalize_url("https://example.com/a")

    def test_default_ports_removed(self):
        assert normalize_url("http://example.com:80/a") == normalize_url("https://example.com:443/a") \
            == "https://example.com/a"

    def test_path_case_preserved(self):
        assert normalize_url("https://example.com/A") != normalize_url("https://example.com/a")

    def test_empty(self):
        assert normalize_url("") == ""

    def test_combined(self):
        assert normalize_url("http://www.example.com/news/story/?utm_source=x&page=2#top") \
            == "https://example.com/news/story?page=2"


# ---------------------------------------------------------------- titles_match

class TestTitlesMatch:
    def test_identical(self):
        assert titles_match("OpenAI launches GPT-6", "OpenAI launches GPT-6", THRESHOLD)

    def test_case_whitespace_and_quote_insensitive(self):
        assert titles_match("OpenAI’s new   model  ships", "openai's new model ships", THRESHOLD)

    def test_near_duplicate(self):
        assert titles_match(
            "OpenAI launches GPT-6 for enterprises",
            "OpenAI launches GPT-6 for enterprise",
            THRESHOLD,
        )

    def test_near_duplicate_punctuation(self):
        assert titles_match(
            "Anthropic raises $5B at a $200B valuation",
            "Anthropic raises $5B at $200B valuation",
            THRESHOLD,
        )

    def test_different_stories(self):
        assert not titles_match(
            "OpenAI launches GPT-6 for enterprises",
            "Mistral raises €1B in new funding round",
            THRESHOLD,
        )

    def test_same_company_different_story(self):
        assert not titles_match(
            "Nvidia reports record quarterly revenue",
            "Nvidia unveils new Blackwell Ultra chip",
            THRESHOLD,
        )

    def test_short_subset_guard(self):
        assert not titles_match("OpenAI", "OpenAI launches GPT-6 for enterprises", THRESHOLD)
        assert not titles_match("OpenAI launches GPT-6 for enterprises", "OpenAI", THRESHOLD)

    def test_empty_never_matches(self):
        assert not titles_match("", "", THRESHOLD)
        assert not titles_match("", "OpenAI", THRESHOLD)


# ---------------------------------------------------------------- within_window

class TestWithinWindow:
    def _run(self, delta: timedelta):
        it = make_item(published=NOW - delta)
        return within_window([it], NOW, WINDOW_H)

    def test_just_inside_kept(self):
        assert len(self._run(timedelta(hours=29, minutes=59))) == 1

    def test_just_outside_dropped(self):
        assert self._run(timedelta(hours=30, minutes=1)) == []

    def test_exact_boundary_dropped(self):
        assert self._run(timedelta(hours=30)) == []

    def test_now_kept(self):
        assert len(self._run(timedelta(0))) == 1

    def test_slightly_future_kept(self):
        assert len(self._run(timedelta(hours=-1))) == 1

    def test_preserves_order_and_filters_mixed(self):
        a = make_item("a", published=NOW - timedelta(hours=1))
        b = make_item("b", published=NOW - timedelta(hours=40))
        c = make_item("c", published=NOW - timedelta(hours=10))
        assert within_window([a, b, c], NOW, WINDOW_H) == [a, c]


# ---------------------------------------------------------------- dedupe

class TestDedupe:
    def test_same_normalized_url_merged(self):
        a = make_item("OpenAI launches GPT-6", "https://www.techcrunch.com/gpt6/?utm_source=rss",
                      source="TechCrunch AI", publisher="TechCrunch AI")
        b = make_item("Totally different headline wording", "http://techcrunch.com/gpt6#comments",
                      source="Techmeme", role="curator", publisher="techcrunch.com")
        out = dedupe([a, b], THRESHOLD)
        assert len(out) == 1
        assert out[0] is a  # non-curator preferred
        assert out[0].extra["also_in"] == [{"source": "Techmeme", "role": "curator", "publisher": "techcrunch.com"}]

    def test_near_identical_titles_prefer_direct_over_google_news(self):
        gn = make_item("Anthropic releases Claude 6 with new agent features",
                       "https://news.google.com/rss/articles/CBMiXYZ", source="Google News: Anthropic",
                       role="primary", publisher="Reuters", publisher_url="reuters.com",
                       extra={"google_news": True})
        direct = make_item("Anthropic releases Claude 6 with new agent features",
                           "https://www.theverge.com/ai/claude-6", source="The Verge AI",
                           publisher="The Verge AI", publisher_url="theverge.com")
        out = dedupe([gn, direct], THRESHOLD)
        assert len(out) == 1
        rep = out[0]
        assert rep is direct
        assert not rep.extra.get("google_news")
        assert rep.extra["also_in"] == [{"source": "Google News: Anthropic", "role": "primary",
                                         "publisher": "Reuters"}]

    def test_also_in_no_duplicates(self):
        title = "Mistral raises €1B Series D led by ASML"
        rep = make_item(title, "https://sifted.eu/mistral", source="Sifted", publisher="Sifted",
                        snippet="long snippet here")
        dup1 = make_item(title, "https://news.google.com/a1", source="Google News: Mistral AI",
                         publisher="Reuters", extra={"google_news": True})
        dup2 = make_item(title, "https://news.google.com/a2", source="Google News: Mistral AI",
                         publisher="Reuters", extra={"google_news": True})
        dup3 = make_item(title, "https://news.google.com/a3", source="Google News: artificial intelligence",
                         publisher="Reuters", extra={"google_news": True})
        dup_self = make_item(title, "https://sifted.eu/mistral?utm_source=x", source="Sifted",
                             publisher="Sifted")
        out = dedupe([dup1, rep, dup2, dup3, dup_self], THRESHOLD)
        assert len(out) == 1
        assert out[0] is rep
        also = out[0].extra["also_in"]
        pairs = [(a["source"], a["publisher"]) for a in also]
        assert len(pairs) == len(set(pairs))
        assert set(pairs) == {("Google News: Mistral AI", "Reuters"),
                              ("Google News: artificial intelligence", "Reuters")}
        assert ("Sifted", "Sifted") not in pairs

    def test_tags_unioned(self):
        title = "EU AI Act enforcement begins for general-purpose models"
        a = make_item(title, "https://a.example/x", tags=["europe"])
        b = make_item(title, "https://b.example/y", source="Finextra", tags=["finance", "europe"])
        out = dedupe([a, b], THRESHOLD)
        assert len(out) == 1
        assert out[0].tags == ["europe", "finance"]

    def test_points_carried_from_merged_duplicate(self):
        title = "Show HN: an open-source LLM inference engine"
        a = make_item(title, "https://github.com/x/y", source="TechCrunch AI", snippet="longer snippet")
        b = make_item(title, "https://github.com/x/y", source="Hacker News", role="curator",
                      extra={"points": 420})
        out = dedupe([b, a], THRESHOLD)
        assert out[0] is a
        assert out[0].extra["points"] == 420

    def test_distinct_stories_kept_separate(self):
        a = make_item("OpenAI launches GPT-6 for enterprises", "https://a.example/1")
        b = make_item("Mistral raises €1B in new funding round", "https://b.example/2")
        c = make_item("Google DeepMind unveils Gemini 4 Ultra", "https://c.example/3")
        out = dedupe([a, b, c], THRESHOLD)
        assert out == [a, b, c]
        assert all(o.extra["also_in"] == [] for o in out)

    def test_same_event_different_articles_not_merged(self):
        a = make_item("OpenAI launches GPT-6", "https://a.example/1")
        b = make_item("Hands-on: GPT-6 is faster but still hallucinates", "https://b.example/2")
        assert len(dedupe([a, b], THRESHOLD)) == 2

    def test_empty(self):
        assert dedupe([], THRESHOLD) == []


def test_assign_ids():
    items = [make_item(str(k)) for k in range(12)]
    out = assign_ids(items)
    assert out is items
    assert [i.id for i in items][:3] == ["i001", "i002", "i003"]
    assert items[-1].id == "i012"
    assert assign_ids([]) == []


# ---------------------------------------------------------------- editions

class TestLoadRecentEditions:
    def _write(self, d, name, data):
        (d / name).write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")

    def test_n_most_recent_strictly_before_today(self, tmp_path):
        for day in ("2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-03",
                    "2026-11-04", "2026-11-05"):
            self._write(tmp_path, f"{day}.json", {"date": day})
        out = load_recent_editions(tmp_path, date(2026, 11, 4), 3)
        assert [e["date"] for e in out] == ["2026-11-03", "2026-11-02", "2026-11-01"]

    def test_ignores_non_date_and_invalid_json(self, tmp_path):
        self._write(tmp_path, "2026-11-03.json", "{not valid json")
        self._write(tmp_path, "2026-11-02.json", {"date": "2026-11-02"})
        self._write(tmp_path, "latest.json", {"date": "latest"})
        self._write(tmp_path, "2026-11-01.backup.json", {"date": "backup"})
        self._write(tmp_path, "2026-11-01.txt", {"date": "txt"})
        self._write(tmp_path, "2026-10-31.json", {"date": "2026-10-31"})
        out = load_recent_editions(tmp_path, date(2026, 11, 4), 3)
        assert [e["date"] for e in out] == ["2026-11-02", "2026-10-31"]

    def test_empty_or_missing_dir(self, tmp_path):
        assert load_recent_editions(tmp_path, date(2026, 11, 4), 3) == []
        assert load_recent_editions(tmp_path / "nope", date(2026, 11, 4), 3) == []


def _edition():
    return {
        "date": "2026-11-03",
        "lead": {"headline": "OpenAI ships GPT-6",
                 "item_urls": ["https://www.techcrunch.com/gpt6/?utm_source=rss"],
                 "item_titles": ["OpenAI launches GPT-6 for enterprises"],
                 "sources": [{"name": "OpenAI", "url": "https://openai.com/index/gpt-6/"}]},
        "main": [{"headline": "Nvidia earnings beat",
                  "item_urls": ["https://reuters.com/nvidia-q3"],
                  "item_titles": ["Nvidia reports record quarterly revenue on AI chip demand"]}],
        "europe_brief": [{"headline": "Mistral raises",
                          "item_urls": ["https://sifted.eu/mistral-raise"],
                          "item_titles": ["Mistral raises €1B Series D led by ASML"]}],
        "finance_brief": [{"headline": "JPMorgan AI",
                           "item_urls": ["https://finextra.com/jpm-ai"],
                           "item_titles": ["JPMorgan rolls out LLM assistant to 200,000 staff"],
                           "sources": [{"name": "x", "url": ""}]}],
        "clusters": [{"id": "c09", "label": "unselected",
                      "item_urls": ["https://example.com/unselected-story"],
                      "item_titles": ["Apple quietly acquires small AI startup"],
                      "items": [{"title": "Apple quietly acquires small AI startup",
                                 "url": "https://example.com/unselected-story"}]}],
    }


class TestCovered:
    def test_covered_index_contents(self):
        urls, titles, headlines = covered_index([_edition()])
        assert urls == {
            "https://techcrunch.com/gpt6", "https://openai.com/index/gpt-6",
            "https://reuters.com/nvidia-q3", "https://sifted.eu/mistral-raise",
            "https://finextra.com/jpm-ai",
        }
        assert "" not in urls
        assert len(titles) == 4
        assert "Apple quietly acquires small AI startup" not in titles
        assert headlines == ["OpenAI ships GPT-6", "Nvidia earnings beat", "Mistral raises", "JPMorgan AI"]

    def test_covered_index_missing_sections(self):
        assert covered_index([{"date": "x", "lead": None}]) == (set(), [], [])
        assert covered_index([]) == (set(), [], [])

    def test_drop_covered(self):
        urls, titles, _ = covered_index([_edition()])
        url_dup = make_item("A different headline entirely about something",
                            "http://techcrunch.com/gpt6#comments")
        source_url_dup = make_item("Introducing GPT-6", "https://openai.com/index/gpt-6")
        europe_dup = make_item("Unrelated words here", "https://sifted.eu/mistral-raise/?ref=home")
        title_dup = make_item("OpenAI launches GPT-6 for enterprise", "https://other.example/1")
        finance_title_dup = make_item("JPMorgan rolls out LLM assistant to 200,000 staff",
                                      "https://bank.example/2")
        unselected = make_item("Apple quietly acquires small AI startup",
                               "https://example.com/unselected-story")
        unrelated = make_item("Google DeepMind unveils Gemini 4 Ultra", "https://deepmind.google/g4")
        items = [url_dup, source_url_dup, europe_dup, title_dup, finance_title_dup, unselected, unrelated]
        kept, dropped = drop_covered(items, urls, titles, THRESHOLD)
        assert kept == [unselected, unrelated]
        assert dropped == [url_dup, source_url_dup, europe_dup, title_dup, finance_title_dup]

    def test_drop_covered_nothing_covered(self):
        items = [make_item("x story"), make_item("y story")]
        kept, dropped = drop_covered(items, set(), [], THRESHOLD)
        assert kept == items and dropped == []
