"""Thin wrapper around the Anthropic SDK: structured-output calls with usage/cost tracking."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from .config import ROOT

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def load_prompt(name: str) -> str:
    return (ROOT / "prompts" / name).read_text(encoding="utf-8")


@dataclass
class Usage:
    calls: list[dict] = field(default_factory=list)

    def add(self, step: str, model: str, usage, pricing: dict) -> None:
        pin, pout = pricing.get(model, (0.0, 0.0))
        inp = (usage.input_tokens or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0) \
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        out = usage.output_tokens or 0
        cost = inp / 1e6 * pin + out / 1e6 * pout
        self.calls.append({"step": step, "model": model, "input_tokens": inp,
                           "output_tokens": out, "cost_usd": round(cost, 5)})

    @property
    def total_cost(self) -> float:
        return sum(c["cost_usd"] for c in self.calls)


class LLMError(RuntimeError):
    pass


def parse_call(*, client: anthropic.Anthropic, model: str, system: str, user: str,
               schema: type[T], effort: str, max_tokens: int, step: str,
               usage: Usage, pricing: dict) -> T:
    """One structured-output request. Streams (long outputs), returns the validated model."""
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort},
        output_format=schema,
    ) as stream:
        msg = stream.get_final_message()
    usage.add(step, model, msg.usage, pricing)
    if msg.stop_reason == "refusal":
        raise LLMError(f"{step}: model refused ({getattr(msg.stop_details, 'category', None)})")
    if msg.stop_reason == "max_tokens":
        raise LLMError(f"{step}: output truncated at max_tokens={max_tokens}")
    parsed = getattr(msg, "parsed_output", None)
    if parsed is None:
        text = next((b.text for b in msg.content if b.type == "text"), "")
        parsed = schema.model_validate_json(text)
    return parsed


def count_tokens(client: anthropic.Anthropic, model: str, system: str, user: str) -> int:
    return client.messages.count_tokens(
        model=model, system=system, messages=[{"role": "user", "content": user}]
    ).input_tokens
