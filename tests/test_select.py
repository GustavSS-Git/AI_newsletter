from __future__ import annotations

import pytest

from newsletter.select import is_paywalled, select
from tests.conftest import make_cluster, make_item

PAYWALLED = ["wsj.com", "ft.com", "bloomberg.com", "theinformation.com", "economist.com",
             "nytimes.com", "businessinsider.com", "barrons.com", "di.se", "wired.com"]

PARAMS = dict(n_main=6, threshold=5, brief_max=2, paywalled=PAYWALLED,
              followup_min=7, headline_only_min=8)


def run(clusters, **over):
    return select(clusters, **{**PARAMS, **over})


def ids(cs):
    return [c.id for c in cs]


class TestTopN:
    def test_lead_is_highest_and_main_excludes_it(self):
        cs = [make_cluster(f"c{k:02d}", importance=imp)
              for k, imp in enumerate([3, 9, 6, 10, 4, 7, 8, 5, 2], 1)]
        sel = run(cs)
        assert sel.lead.id == "c04"  # importance 10
        assert ids(sel.main) == ["c02", "c07", "c06", "c03", "c08"]  # 9, 8, 7, 6, 5
        assert len([sel.lead] + sel.main) == 6
        assert sel.lead not in sel.main
        assert sel.section_of("c04") == "lead"
        assert sel.section_of("c02") == "main"
        assert sel.section_of("c09") is None

    def test_tie_break_by_publishers(self):
        a = make_cluster("c01", importance=8, n_publishers=1)
        b = make_cluster("c02", importance=8, n_publishers=3)
        c = make_cluster("c03", importance=8, n_publishers=2)
        sel = run([a, b, c])
        assert sel.lead.id == "c02"
        assert ids(sel.main) == ["c03", "c01"]

    def test_publishers_counted_via_also_in(self):
        it = make_item("x", publisher="Verge", extra={"also_in": [
            {"source": "GN", "role": "press", "publisher": "Reuters"},
            {"source": "GN2", "role": "press", "publisher": "AP"}]})
        a = make_cluster("c01", importance=8, n_publishers=2)
        b = make_cluster("c02", importance=8, items=[it])
        assert run([a, b]).lead.id == "c02"

    def test_tie_break_by_curator(self):
        a = make_cluster("c01", importance=8, n_publishers=2, curator=False)
        b = make_cluster("c02", importance=8, n_publishers=2, curator=True)
        assert run([a, b]).lead.id == "c02"

    def test_curator_via_also_in(self):
        it = make_item("x", publisher="Verge", extra={"also_in": [
            {"source": "Techmeme", "role": "curator", "publisher": "Verge"}]})
        a = make_cluster("c01", importance=8, n_publishers=1)
        b = make_cluster("c02", importance=8, items=[it])
        assert run([a, b]).lead.id == "c02"

    def test_importance_beats_breadth(self):
        a = make_cluster("c01", importance=7, n_publishers=5, curator=True)
        b = make_cluster("c02", importance=8, n_publishers=1)
        assert run([a, b]).lead.id == "c02"

    def test_fewer_clusters_than_n(self):
        cs = [make_cluster("c01", importance=4), make_cluster("c02", importance=9)]
        sel = run(cs)
        assert sel.lead.id == "c02"
        assert ids(sel.main) == ["c01"]
        assert sel.europe == [] and sel.finance == []

    def test_no_clusters(self):
        sel = run([])
        assert sel.lead is None and sel.main == [] and sel.all == []

    def test_exclude(self):
        cs = [make_cluster("c01", importance=10), make_cluster("c02", importance=9),
              make_cluster("c03", importance=8)]
        sel = run(cs, exclude={"c01"})
        assert sel.lead.id == "c02"
        assert ids(sel.main) == ["c03"]
        assert "c01" not in ids(sel.all)

    def test_exclude_applies_to_briefs(self):
        cs = [make_cluster(f"m{k}", importance=9) for k in range(6)]
        cs.append(make_cluster("eu", importance=6, european=True))
        assert run(cs, exclude={"eu"}).europe == []


def _fill_main(n=6, importance=9):
    return [make_cluster(f"m{k}", importance=importance) for k in range(n)]


class TestBriefs:
    def test_europe_brief(self):
        cs = _fill_main() + [
            make_cluster("e1", importance=7, european=True),
            make_cluster("e2", importance=5, european=True),   # exactly threshold
            make_cluster("e3", importance=6, european=True),
            make_cluster("e4", importance=4, european=True),   # below threshold
        ]
        sel = run(cs)
        assert ids(sel.europe) == ["e1", "e3"]  # brief_max=2, ranked
        assert sel.finance == []

    def test_europe_threshold_inclusive(self):
        cs = _fill_main() + [make_cluster("e2", importance=5, european=True),
                             make_cluster("e4", importance=4, european=True)]
        assert ids(run(cs).europe) == ["e2"]

    def test_european_in_main_not_repeated(self):
        cs = _fill_main(5) + [make_cluster("e1", importance=9, european=True),
                              make_cluster("e2", importance=5, european=True)]
        sel = run(cs)
        assert "e1" in ids(sel.main) or sel.lead.id == "e1"
        assert ids(sel.europe) == ["e2"]

    def test_finance_brief(self):
        cs = _fill_main() + [
            make_cluster("f1", importance=6, finance=True),
            make_cluster("f2", importance=7, finance=True),
            make_cluster("f3", importance=5, finance=True),
            make_cluster("f4", importance=3, finance=True),
        ]
        sel = run(cs)
        assert ids(sel.finance) == ["f2", "f1"]

    def test_finance_never_duplicates_europe(self):
        cs = _fill_main() + [
            make_cluster("ef1", importance=8, european=True, finance=True),
            make_cluster("ef2", importance=7, european=True, finance=True),
            make_cluster("f1", importance=6, finance=True),
        ]
        sel = run(cs)
        assert ids(sel.europe) == ["ef1", "ef2"]
        assert ids(sel.finance) == ["f1"]
        assert not set(ids(sel.europe)) & set(ids(sel.finance))

    def test_finance_takes_overflow_europe_finance_cluster(self):
        cs = _fill_main() + [
            make_cluster("e1", importance=8, european=True),
            make_cluster("e2", importance=8, european=True),
            make_cluster("ef3", importance=7, european=True, finance=True),
        ]
        sel = run(cs)
        assert ids(sel.europe) == ["e1", "e2"]
        assert ids(sel.finance) == ["ef3"]

    def test_empty_briefs_when_nothing_qualifies(self):
        cs = _fill_main() + [
            make_cluster("e1", importance=4, european=True),
            make_cluster("f1", importance=4, finance=True),
            make_cluster("x1", importance=7),
        ]
        sel = run(cs)
        assert sel.europe == [] and sel.finance == []

    def test_cluster_in_one_section_only(self):
        cs = _fill_main(4) + [make_cluster(f"ef{k}", importance=5 + k, european=True, finance=True)
                              for k in range(5)]
        sel = run(cs)
        all_ids = ids(sel.all)
        assert len(all_ids) == len(set(all_ids))


class TestEligibility:
    def test_covered_before_excluded(self):
        c = make_cluster("c01", importance=10, covered_before=True)
        sel = run([c, make_cluster("c02", importance=5)])
        assert "c01" not in ids(sel.all)

    def test_covered_before_new_development_below_followup_min(self):
        c = make_cluster("c01", importance=6, covered_before=True, new_development=True)
        assert "c01" not in ids(run([c]).all)

    @pytest.mark.parametrize("imp", [7, 9])
    def test_covered_before_new_development_at_or_above_followup_min(self, imp):
        c = make_cluster("c01", importance=imp, covered_before=True, new_development=True)
        assert run([c]).lead.id == "c01"

    def test_covered_before_in_brief_also_excluded(self):
        cs = _fill_main() + [make_cluster("e1", importance=6, european=True, covered_before=True)]
        assert run(cs).europe == []

    def test_new_development_without_covered_before_is_normal(self):
        c = make_cluster("c01", importance=3, new_development=True)
        assert run([c]).lead.id == "c01"

    def test_paywalled_only_below_headline_min_excluded(self):
        c = make_cluster("c01", importance=7, publisher_url="wsj.com", n_publishers=2)
        assert run([c]).lead is None

    def test_paywalled_subdomain_excluded(self):
        c = make_cluster("c01", importance=7, publisher_url="markets.ft.com")
        assert run([c]).lead is None

    @pytest.mark.parametrize("imp", [8, 10])
    def test_paywalled_only_at_or_above_headline_min_allowed(self, imp):
        c = make_cluster("c01", importance=imp, publisher_url="markets.ft.com")
        assert run([c]).lead.id == "c01"

    def test_paywalled_with_open_source_allowed(self):
        items = [make_item("a", publisher_url="wsj.com"), make_item("b", publisher_url="reuters.com")]
        c = make_cluster("c01", importance=5, items=items)
        assert run([c]).lead.id == "c01"

    def test_paywalled_lookalike_domain_not_paywalled(self):
        assert not is_paywalled("notft.com", PAYWALLED)
        assert not is_paywalled("ft.com.example.org", PAYWALLED)
        assert is_paywalled("FT.com", PAYWALLED)
        assert is_paywalled("www.wsj.com", PAYWALLED)
        assert not is_paywalled("", PAYWALLED)


class TestHeadlineOnlyGate:
    """Paywalled-only clusters must pass the section-specific headline-only gate."""
    GATE = dict(threshold=4, headline_only_min=6, headline_only_min_publishers=3, brief_min_publishers=2)

    def test_main_needs_score_and_publishers(self):
        weak = make_cluster("c1", 7, n_publishers=2, publisher_url="wsj.com")
        strong = make_cluster("c2", 6, n_publishers=3, publisher_url="wsj.com")
        low = make_cluster("c3", 5, n_publishers=5, publisher_url="wsj.com")
        sel = run([weak, strong, low], **self.GATE)
        assert ids(sel.all) == ["c2"]

    def test_brief_uses_publisher_gate_only(self):
        main = [make_cluster(f"m{i}", 9, n_publishers=3) for i in range(6)]
        eu_two = make_cluster("e1", 4, n_publishers=2, european=True, publisher_url="ft.com")
        eu_one = make_cluster("e2", 5, n_publishers=1, european=True, publisher_url="ft.com")
        sel = run(main + [eu_two, eu_one], **self.GATE)
        assert ids(sel.europe) == ["e1"]

    def test_headline_only_ok_helper(self):
        from newsletter.select import headline_only_ok
        c = make_cluster("c1", 6, n_publishers=3)
        kw = dict(headline_only_min=6, headline_only_min_publishers=3, brief_min_publishers=2)
        assert headline_only_ok(c, "main", **kw) and headline_only_ok(c, "lead", **kw)
        assert not headline_only_ok(make_cluster("c2", 6, n_publishers=2), "main", **kw)
        assert headline_only_ok(make_cluster("c3", 4, n_publishers=2), "finance", **kw)
        assert not headline_only_ok(make_cluster("c4", 9, n_publishers=1), "europe", **kw)
