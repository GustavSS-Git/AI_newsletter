from newsletter.enrich import display_links, pretty_publisher
from tests.conftest import make_cluster, make_item

PAYWALLED = ["wsj.com", "ft.com", "bloomberg.com"]


def test_pretty_publisher():
    assert pretty_publisher("https://www.bloomberg.com/") == "Bloomberg"
    assert pretty_publisher("https://tech-insider.org/") == "tech-insider.org"
    assert pretty_publisher("TechCrunch AI") == "TechCrunch AI"
    assert pretty_publisher("Yahoo Finance") == "Yahoo Finance"


def test_display_links_prefers_open_direct_then_paywalled_then_google_news():
    gn = make_item(title="a", url="https://news.google.com/rss/articles/x", publisher="Reuters",
                   extra={"google_news": True})
    pay = make_item(title="b", url="https://www.wsj.com/a", publisher="wsj.com", publisher_url="wsj.com")
    open_ = make_item(title="c", url="https://techcrunch.com/a", publisher="TechCrunch AI",
                      publisher_url="techcrunch.com")
    c = make_cluster("c01", items=[gn, pay, open_])
    names = [l["name"] for l in display_links(c, PAYWALLED)]
    assert names == ["TechCrunch AI", "The Wall Street Journal", "Reuters"]


def test_display_links_one_per_publisher_and_limit():
    items = [make_item(title=f"t{i}", url=f"https://ex{i % 3}.com/{i}", publisher=f"Pub{i % 3}",
                       publisher_url=f"ex{i % 3}.com") for i in range(9)]
    links = display_links(make_cluster("c01", items=items), PAYWALLED, limit=4)
    assert len(links) == 3 and len({l["name"] for l in links}) == 3


def test_clean_display_url():
    from newsletter.enrich import clean_display_url
    assert clean_display_url("https://www.bloomberg.com/a?accessToken=xyz&utm_source=x") == "https://www.bloomberg.com/a"
    assert clean_display_url("https://ex.com/a?id=5&utm_medium=rss") == "https://ex.com/a?id=5"
    gn = "https://news.google.com/rss/articles/abc?oc=5"
    assert clean_display_url(gn) == gn
