"""LLM access for the research and strategy floors.

By default the agents call the LLM *through the llm-gateway project* (in-process), so every call gets retries,
fallback from gpt-oss-120b to gpt-oss-20b, a response cache and cost tracking. `HTTPLLM` talks to any
OpenAI-compatible endpoint instead, including a separately deployed gateway.

The model is asked for JSON. Anything it returns is parsed, validated and clipped by the caller; it is never trusted
to set a number that matters (size, stop, price).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass
class LLMResult:
    ok: bool
    data: dict[str, Any] | None
    model: str = ""
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    error: str = ""


class LLM(Protocol):
    name: str

    async def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> LLMResult: ...


def parse_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def _body(route: str, system: str, user: str, max_tokens: int) -> dict[str, Any]:
    return {
        "model": route,
        "temperature": 0,
        "max_tokens": max_tokens,
        "reasoning_effort": "low",
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }


class GatewayLLM:
    """Runs the llm-gateway in-process with Groq models: smart = gpt-oss-120b -> gpt-oss-20b."""

    name = "llm-gateway (in-process)"

    def __init__(self, route: str = "smart", database: str = ":memory:"):
        from llmgw.config import GatewayConfig
        from llmgw.gateway import Gateway

        cfg = GatewayConfig.model_validate(
            {
                "providers": {
                    "groq": {
                        "type": "openai",
                        "base_url": "https://api.groq.com/openai/v1",
                        "api_key_env": "GROQ_API_KEY",
                        "timeout_s": 45,
                        "models": {
                            "openai/gpt-oss-120b": {"input_per_1m": 0.15, "output_per_1m": 0.60},
                            "openai/gpt-oss-20b": {"input_per_1m": 0.075, "output_per_1m": 0.30},
                        },
                    }
                },
                "routes": {
                    "smart": ["groq/openai/gpt-oss-120b", "groq/openai/gpt-oss-20b"],
                    "fast": ["groq/openai/gpt-oss-20b", "groq/openai/gpt-oss-120b"],
                },
                "default_route": route,
                "database": database,
                "require_auth": False,
                "retry": {"attempts_per_target": 2, "backoff_s": 1.0, "max_retry_after_s": 20},
                "cache": {"enabled": True, "ttl_s": 3600},
            }
        )
        self.route = route
        self.gw = Gateway(cfg)

    async def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> LLMResult:
        from llmgw.gateway import GatewayError

        t0 = time.perf_counter()
        try:
            out = await self.gw.chat(_body(self.route, system, user, max_tokens), None)
        except GatewayError as e:
            return LLMResult(False, None, error=f"{e.status}: {e.message}"[:300], latency_ms=_ms(t0))
        text = (out.body or {}).get("choices", [{}])[0].get("message", {}).get("content", "")
        data = parse_json(text)
        return LLMResult(
            ok=data is not None,
            data=data,
            model=out.headers.get("x-gateway-target", ""),
            cost_usd=float(out.headers.get("x-gateway-cost-usd", 0) or 0),
            latency_ms=_ms(t0),
            error="" if data is not None else "model did not return JSON",
        )


class HTTPLLM:
    """Any OpenAI-compatible endpoint, e.g. a deployed llm-gateway (`LLM_BASE_URL`, `LLM_API_KEY`)."""

    name = "OpenAI-compatible HTTP"

    def __init__(self, base_url: str, api_key: str, route: str = "smart"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.route = route

    async def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> LLMResult:
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(
                    f"{self.base_url}/chat/completions",
                    json=_body(self.route, system, user, max_tokens),
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            r.raise_for_status()
        except httpx.HTTPError as e:
            return LLMResult(False, None, error=str(e)[:300], latency_ms=_ms(t0))
        body = r.json()
        data = parse_json(body.get("choices", [{}])[0].get("message", {}).get("content", ""))
        return LLMResult(
            ok=data is not None,
            data=data,
            model=r.headers.get("x-gateway-target", body.get("model", "")),
            cost_usd=float(r.headers.get("x-gateway-cost-usd", 0) or 0),
            latency_ms=_ms(t0),
            error="" if data is not None else "model did not return JSON",
        )


class ScriptedLLM:
    """Returns canned answers. Used by tests and to demonstrate how malformed or hostile output is handled."""

    name = "scripted"

    def __init__(self, answers: list[Any] | None = None, default: Any = None):
        self.answers = list(answers or [])
        self.default = default
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> LLMResult:
        self.calls.append((system, user))
        ans = self.answers.pop(0) if self.answers else self.default
        if ans is None or isinstance(ans, Exception):
            return LLMResult(False, None, error=str(ans or "no answer"))
        data = ans if isinstance(ans, dict) else parse_json(str(ans))
        return LLMResult(data is not None, data, model="scripted", error="" if data else "not JSON")


def from_env(route: str = "smart") -> LLM | None:
    """Pick an LLM from the environment, or None (rules only) when no key is configured."""
    if os.getenv("LLM_BASE_URL"):
        return HTTPLLM(os.environ["LLM_BASE_URL"], os.getenv("LLM_API_KEY", ""), route)
    if os.getenv("GROQ_API_KEY"):
        return GatewayLLM(route)
    return None


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)
