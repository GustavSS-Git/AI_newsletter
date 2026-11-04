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


def api_key_problem() -> str | None:
    """Describe what's wrong with ANTHROPIC_API_KEY, or None if it looks valid.
    Never includes the key itself. Surrounding whitespace is stripped in place."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key.strip():
        return "ANTHROPIC_API_KEY is not set (looked in the environment, .env.local and .env)"
    stripped = key.strip()
    if stripped != key:
        os.environ["ANTHROPIC_API_KEY"] = stripped
    if any(c.isspace() for c in stripped) or stripped.startswith(("curl", '"', "'")) or "=" in stripped:
        return ("ANTHROPIC_API_KEY contains spaces, line breaks, quotes or '=': it should be only the key "
                "itself (one line starting with 'sk-ant-'), not a curl command or 'NAME=value'")
    if not stripped.startswith("sk-ant-"):
        return "ANTHROPIC_API_KEY does not start with 'sk-ant-'; check that the whole key was copied"
    return None
