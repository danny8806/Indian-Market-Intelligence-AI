"""Independent morning critic.

The critic is a distinct review call. When a separate OpenAI-compatible
endpoint is configured it is provider-independent; otherwise the Codex CLI is
used without tools and the audit trail records that the analyst and critic
share a provider.
"""
from __future__ import annotations

import json
import os
import time

from news_collector.codex_research import run_codex


def endpoint() -> tuple[str, str, str] | None:
    base = os.getenv("NEWS_CRITIC_BASE_URL", "").strip()
    model = os.getenv("NEWS_CRITIC_MODEL", "").strip()
    key = os.getenv("NEWS_CRITIC_API_KEY", "").strip()
    if base and model:
        return base.rstrip("/"), model, key
    return None


def describe() -> dict:
    configured = endpoint()
    if configured:
        return {"provider": "openai-compatible", "model": configured[1],
                "independent": True}
    return {"provider": "codex", "model": os.getenv("NEWS_CODEX_MODEL", "codex-cli"),
            "independent": False}


def _classify(error: str) -> str:
    text = error.lower()
    if "429" in text or "quota" in text or "rate limit" in text:
        return "QUOTA_LIMIT"
    if "401" in text or "unauthorized" in text or "authentication" in text:
        return "AUTH_REQUIRED"
    if "403" in text or "forbidden" in text:
        return "ACCESS_BLOCKED"
    if "timeout" in text or "timed out" in text:
        return "TIMEOUT"
    return "CLI_ERROR"


def _run_compatible(prompt: str, *, timeout: int) -> tuple[str, dict | None, dict]:
    base, model, key = endpoint()
    audit = {**describe(), "status": "CLI_ERROR"}
    try:
        from openai import OpenAI
    except ImportError:
        audit["status"] = "NOT_CONFIGURED"
        audit["error"] = "openai package is not installed"
        return "NOT_CONFIGURED", None, audit
    started = time.monotonic()
    try:
        client = OpenAI(base_url=base, api_key=key or "not-required", timeout=timeout)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        payload = json.loads(content)
    except Exception as exc:  # Provider errors are recorded, never retried here.
        audit.update(status=_classify(str(exc)), error=str(exc)[:300],
                     duration_seconds=round(time.monotonic() - started, 2))
        return audit["status"], None, audit
    audit.update(status="OK", duration_seconds=round(time.monotonic() - started, 2))
    return "OK", payload, audit


def run_critic(prompt: str, schema: dict, *, search: bool = False,
               timeout: int = 90) -> tuple[str, dict | None, dict]:
    """Run the configured critic and always return a provider audit record."""
    if endpoint() is None:
        status, payload = run_codex(prompt, schema, search=False, timeout=timeout)
        return status, payload, {**describe(), "status": status}
    return _run_compatible(prompt, timeout=timeout)
