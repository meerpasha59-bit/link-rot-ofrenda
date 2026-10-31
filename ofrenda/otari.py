"""Otari.ai client: open-weight models through Mozilla.ai's hosted AI gateway.

Otari (https://otari.ai, https://github.com/mozilla-ai/otari) exposes one
OpenAI-compatible API in front of many providers. This module is a small
stdlib-only client for it. It records, for every call, what the gateway
actually did (which model and provider served it, whether a fallback kicked
in, what it cost), because an ofrenda that refuses to make things up should
also be honest about who wrote each line.

The API key is read from the ``OTARI_API_KEY`` environment variable and never
written to disk, the HTML, or the JSON output.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

# Note: the hosted API lives under /api/v1 (not /v1).
DEFAULT_BASE = "https://api.otari.ai/api/v1"
APP_TAG = "link-rot-ofrenda"


class OtariError(RuntimeError):
    def __init__(self, status: int, detail: str, request_id: str | None = None):
        super().__init__(f"Otari HTTP {status}: {detail}")
        self.status = status
        self.detail = detail
        self.request_id = request_id

    @property
    def budget_exhausted(self) -> bool:
        """True when Otari refused the call because a budget or ceiling is spent."""
        d = self.detail.lower()
        return self.status in (402, 429, 403) and any(
            k in d for k in ("budget", "ceiling", "spend", "insufficient", "balance", "credit"))


@dataclass
class Call:
    """What one gateway call did, as Otari reported it."""
    role: str
    requested: str
    served_model: str | None = None
    provider: str | None = None
    fallback: bool = False
    attempts: int | None = None
    cost_usd: float = 0.0
    request_id: str | None = None
    ms: int | None = None
    tool_calls: list = field(default_factory=list)
    error: str | None = None


class Otari:
    def __init__(self, api_key: str | None = None, base: str | None = None,
                 timeout: float = 150, session_label: str | None = None):
        self.api_key = api_key or os.environ.get("OTARI_API_KEY", "")
        if not self.api_key:
            raise SystemExit("OTARI_API_KEY is not set. Create a key at https://otari.ai "
                             "(API keys tab) and export it; it is never written to disk.")
        self.base = (base or os.environ.get("OTARI_BASE_URL", DEFAULT_BASE)).rstrip("/")
        self.timeout = timeout
        self.session_label = session_label
        self.calls: list[Call] = []

    # ------------------------------------------------------------------ spend
    @property
    def spent(self) -> float:
        return round(sum(c.cost_usd for c in self.calls), 6)

    def ledger(self) -> list[dict]:
        return [c.__dict__ for c in self.calls]

    # ------------------------------------------------------------------- core
    def chat(self, role: str, model: str, messages: list[dict], **params) -> tuple[dict, Call]:
        """One chat completion. Returns (response json, Call record)."""
        body = {"model": model, "messages": messages, **params}
        # Cost attribution tags: show up on Otari's usage rows, never sent upstream.
        body.setdefault("metadata", {}).update({"app": APP_TAG, "role": role})
        if self.session_label:
            body.setdefault("session_label", self.session_label)
        req = urllib.request.Request(
            self.base + "/chat/completions", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json",
                     "User-Agent": f"{APP_TAG} (+https://github.com/meerpasha59-bit/link-rot-ofrenda)"})
        call = Call(role=role, requested=model)
        t = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                headers, data = r.headers, json.load(r)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                detail = json.loads(raw).get("detail", raw)
            except (ValueError, AttributeError):
                detail = raw
            call.error = f"{e.code}: {str(detail)[:300]}"
            call.request_id = e.headers.get("Otari-Request-Id")
            call.ms = int((time.time() - t) * 1000)
            self.calls.append(call)
            raise OtariError(e.code, str(detail), call.request_id) from None
        call.ms = int((time.time() - t) * 1000)
        call.served_model = headers.get("Otari-Model") or data.get("model")
        call.provider = headers.get("Otari-Provider")
        call.fallback = (headers.get("Otari-Fallback") or "").lower() == "true"
        call.attempts = int(headers.get("Otari-Attempt-Count") or 0) or None
        call.request_id = headers.get("Otari-Request-Id")
        try:
            call.cost_usd = float((data.get("usage") or {}).get("cost_usd") or 0)
        except (TypeError, ValueError):
            call.cost_usd = 0.0
        call.tool_calls = data.get("otari_tool_calls") or []
        self.calls.append(call)
        return data, call

    @staticmethod
    def text(data: dict) -> str:
        try:
            return data["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            return ""


class OtariModel:
    """Drop-in for ``model.LocalModel``: same ``.chat()``, served through Otari."""

    def __init__(self, client: Otari, model: str, temperature: float = 0.3,
                 max_tokens: int = 220, role: str = "scribe", system: str | None = None):
        self.client = client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.role = role
        self.system = system
        self.last: Call | None = None

    def chat(self, user: str, temperature: float | None = None) -> str:
        from .model import SYSTEM
        data, call = self.client.chat(
            self.role, self.model,
            [{"role": "system", "content": self.system or SYSTEM},
             {"role": "user", "content": user}],
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
        )
        self.last = call
        return Otari.text(data)
