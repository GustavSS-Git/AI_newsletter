"""Email the latest (or a given) edition through Buttondown.

    python scripts/send_email.py --preview          # write the email HTML to a file, no API call
    python scripts/send_email.py                    # use email.mode from config.yaml (off | draft | send)
    python scripts/send_email.py --mode draft       # override the mode
    python scripts/send_email.py --date 2026-11-05

Exit codes: 0 OK or skipped (mode off, or no API key yet), 1 sending failed.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from newsletter.config import ROOT, load_config, load_env  # noqa: E402
from newsletter.email import build_preview  # noqa: E402
from newsletter.render import load_editions  # noqa: E402
from newsletter.send import SendError, send_edition  # noqa: E402

log = logging.getLogger("send_email")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="edition date (default: latest saved edition)")
    ap.add_argument("--mode", choices=["off", "draft", "send"], help="override email.mode from config")
    ap.add_argument("--preview", nargs="?", const="email-preview.html", metavar="FILE",
                    help="write a local preview HTML file and exit (default: email-preview.html)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    load_env()
    cfg = load_config()

    editions = load_editions(ROOT / "editions")
    if args.date:
        editions = [e for e in editions if e.get("date") == args.date]
    if not editions:
        log.error("no edition found%s", f" for {args.date}" if args.date else "")
        return 1
    edition = editions[-1]

    if args.preview:
        Path(args.preview).write_text(build_preview(edition, cfg), encoding="utf-8")
        log.info("wrote preview of %s to %s", edition["date"], args.preview)
        return 0

    mode = args.mode or cfg.get("email", {}).get("mode", "off")
    if mode == "off":
        log.info("email.mode is off; not sending")
        return 0
    if not os.environ.get("BUTTONDOWN_API_KEY", "").strip():
        log.warning("BUTTONDOWN_API_KEY not set; skipping email (set the secret to enable)")
        return 0
    try:
        send_edition(edition, cfg, mode=mode)
    except SendError as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
