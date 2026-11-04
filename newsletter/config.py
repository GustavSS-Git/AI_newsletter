"""Config and environment loading."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path | str | None = None) -> dict:
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_env() -> None:
    """Load the API key from .env.local, then .env (first one wins). Never logs values."""
    for name in (".env.local", ".env"):
        p = ROOT / name
        if p.exists():
            load_dotenv(p, override=False)


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
