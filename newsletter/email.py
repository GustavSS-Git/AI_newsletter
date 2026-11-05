"""Build the email version of an edition. Sending lives in newsletter/send.py."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .config import ROOT
from .render import _env

# Tells Buttondown the body is HTML, not Markdown (docs: "buttondown-editor-mode").
HTML_MARKER = "<!-- buttondown-editor-mode: fancy -->"


def subject_for(edition: dict, cfg: dict) -> str:
    """"AI Daily · Thursday, November 5". Buttondown shows the subject as the email's big title;
    the date keeps subjects unique, so mail clients don't thread every edition together.
    The lead headline goes in the preview text (`description`) instead."""
    d = date.fromisoformat(edition["date"])
    return f"{cfg['publication']['name']} · {d:%A}, {d:%B} {d.day}"


def web_url(edition: dict, cfg: dict) -> str:
    return f"{cfg['publication'].get('base_url', '').rstrip('/')}/archive/{edition['date']}"


def build_email(edition: dict, cfg: dict, templates_dir: Path | None = None) -> tuple[str, str]:
    """Return (subject, html_body) for an edition. The body is an HTML fragment for Buttondown,
    which adds its own header and unsubscribe footer. Pure: no network, no API key."""
    pub = cfg["publication"]
    base = pub.get("base_url", "").rstrip("/")
    subject = subject_for(edition, cfg)
    html = _env(templates_dir or ROOT / "templates").get_template("email.html.j2").render(
        edition=edition, pub=pub, web_url=web_url(edition, cfg), archive_url=f"{base}/archive/",
    )
    return subject, f"{HTML_MARKER}\n{html.strip()}\n"


def build_preview(edition: dict, cfg: dict) -> str:
    """A standalone HTML page approximating the received email, for checking locally."""
    subject, body = build_email(edition, cfg)
    pub = cfg["publication"]
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{subject}</title></head>
<body style="margin:0;background:#faf8f3;"><div style="max-width:600px;margin:0 auto;padding:24px 16px;">
<p style="font-family:Georgia,serif;font-size:13px;color:#888;">Preview. Subject: <b>{subject}</b>.
Buttondown adds its own header with the newsletter name and an unsubscribe footer.</p>
<p style="font-family:Georgia,serif;font-size:32px;font-weight:bold;text-align:center;margin:16px 0 4px;">{pub['name']}</p>
{body}</div></body></html>"""
