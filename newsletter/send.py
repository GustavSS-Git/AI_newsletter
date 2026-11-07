"""Send (or draft) an edition through the Buttondown API.

Docs (checked 2026-11-05): https://docs.buttondown.com/api-emails-create,
api-emails-list, api-idempotency-keys, api-versioning, drafting-emails-via-the-api.
"""
from __future__ import annotations

import logging
import os
import uuid

import requests

from .email import build_email, web_url

log = logging.getLogger(__name__)

API = "https://api.buttondown.com/v1"
API_VERSION = "2026-04-01"


class SendError(RuntimeError):
    pass


def _headers(key: str, idempotency_key: str | None = None) -> dict:
    h = {"Authorization": f"Token {key}", "X-API-Version": API_VERSION, "Content-Type": "application/json"}
    if idempotency_key:
        h["X-Idempotency-Key"] = idempotency_key
    return h


def find_existing(edition_date: str, key: str, session=requests) -> dict | None:
    """An email already created for this edition (draft or sent, not deleted), if any.
    Matched on metadata.edition, which we set on every email we create."""
    r = session.get(f"{API}/emails", headers=_headers(key), timeout=30, params={
        "creation_date__start": edition_date, "-status": "deleted", "source": "api",
        "excluded_fields": "body", "ordering": "-creation_date",
    })
    if r.status_code >= 400:
        raise SendError(f"listing emails failed: HTTP {r.status_code}: {r.text[:200]}")
    for e in r.json().get("results", []):
        if (e.get("metadata") or {}).get("edition") == edition_date:
            return e
    return None


def send_edition(edition: dict, cfg: dict, *, mode: str, key: str | None = None, session=requests) -> dict | None:
    """mode: 'draft' creates a draft for review; 'send' sends to all subscribers now.
    Idempotent per edition date: returns the existing email instead of creating a second one."""
    if mode not in ("draft", "send"):
        raise ValueError(f"unknown email mode {mode!r}")
    key = key or os.environ.get("BUTTONDOWN_API_KEY", "").strip()
    if not key:
        raise SendError("BUTTONDOWN_API_KEY is not set")

    existing = find_existing(edition["date"], key, session)
    if existing:
        log.info("email for %s already exists (id %s, status %s); not creating another",
                 edition["date"], existing.get("id"), existing.get("status"))
        return existing

    subject, body = build_email(edition, cfg)
    payload = {
        "subject": subject,
        "body": body,
        "status": "draft" if mode == "draft" else "about_to_send",
        "archival_mode": "disabled",          # our own archive lives at news.slanesens.com
        "canonical_url": web_url(edition, cfg),
        "description": edition["lead"]["headline"],
        "metadata": {"edition": edition["date"], "edition_number": edition["edition_number"]},
    }
    # The idempotency key guards against duplicate creates within one run (network retries).
    # Across runs, find_existing() above prevents duplicates. The key must differ per run:
    # Buttondown stores the response for a key, error responses included, and replays it. A
    # retried run that reused a date-only key just got the first run's 400 back (2026-11-07).
    run = os.environ.get("GITHUB_RUN_ID") or uuid.uuid4().hex[:12]
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    headers = _headers(key, idempotency_key=f"ai-daily-{edition['date']}-{mode}-{run}-{attempt}")
    if mode == "send":
        # Buttondown refuses the first live send from a new API key without this header
        # (error "sending_requires_confirmation", seen 2026-11-07). Sending it every time is harmless.
        headers["X-Buttondown-Live-Dangerously"] = "true"
    r = session.post(f"{API}/emails", json=payload, timeout=60, headers=headers)
    if r.status_code >= 400:
        raise SendError(f"creating email failed: HTTP {r.status_code}: {r.text[:300]}")
    email = r.json()
    log.info("email %s for %s: id %s, status %s", "drafted" if mode == "draft" else "sent",
             edition["date"], email.get("id"), email.get("status"))
    return email
