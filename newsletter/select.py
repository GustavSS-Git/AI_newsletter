"""Pure-Python story selection. The quota rules live here, not in the prompt."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Cluster


def is_paywalled(domain: str, paywalled: list[str]) -> bool:
    domain = (domain or "").lower()
    return any(domain == p or domain.endswith("." + p) for p in paywalled)


def has_open_source(cluster: Cluster, paywalled: list[str]) -> bool:
    return any(not is_paywalled(it.publisher_url, paywalled) for it in cluster.items)


def rank_key(c: Cluster) -> tuple:
    """Sort key, best first: importance, then breadth of coverage, then curator pickup."""
    return (-c.importance, -len(c.publishers), not c.has_curator, c.id)


def is_eligible(c: Cluster, *, paywalled: list[str], followup_min: int, headline_only_min: int) -> bool:
    # Already covered in a recent edition: only back in as a substantial, high-scoring follow-up.
    if c.covered_before and not (c.new_development and c.importance >= followup_min):
        return False
    # Paywalled-only: keep headline-only if important enough, else drop.
    if not has_open_source(c, paywalled) and c.importance < headline_only_min:
        return False
    return True


@dataclass
class Selection:
    lead: Cluster | None
    main: list[Cluster] = field(default_factory=list)       # excludes the lead
    europe: list[Cluster] = field(default_factory=list)
    finance: list[Cluster] = field(default_factory=list)

    @property
    def all(self) -> list[Cluster]:
        return ([self.lead] if self.lead else []) + self.main + self.europe + self.finance

    def section_of(self, cid: str) -> str | None:
        if self.lead and self.lead.id == cid:
            return "lead"
        for name in ("main", "europe", "finance"):
            if any(c.id == cid for c in getattr(self, name)):
                return name
        return None


def select(clusters: list[Cluster], *, n_main: int, threshold: int, brief_max: int,
           paywalled: list[str], followup_min: int, headline_only_min: int,
           exclude: set[str] = frozenset()) -> Selection:
    """Top `n_main` eligible clusters (lead included) by rank; then up to `brief_max`
    european and `brief_max` finance_consulting clusters not already shown with
    importance >= threshold. A cluster appears in at most one section."""
    pool = sorted(
        (c for c in clusters if c.id not in exclude and is_eligible(
            c, paywalled=paywalled, followup_min=followup_min, headline_only_min=headline_only_min)),
        key=rank_key,
    )
    top = pool[:n_main]
    shown = {c.id for c in top}
    rest = [c for c in pool if c.id not in shown and c.importance >= threshold]

    europe = [c for c in rest if c.european][:brief_max]
    shown |= {c.id for c in europe}
    finance = [c for c in rest if c.finance_consulting and c.id not in shown][:brief_max]

    return Selection(lead=top[0] if top else None, main=top[1:], europe=europe, finance=finance)
