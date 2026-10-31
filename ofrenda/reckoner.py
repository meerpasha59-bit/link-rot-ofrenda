"""Reckon how long each page was remembered, in Otari's code sandbox, and check it.

Language models are bad at date arithmetic and good at sounding sure, which
is how an obituary ends up with the wrong age. So the numbers on the altar
are never *written* by a model: an open-weight model (gpt-oss-120b) is given
Otari's ``otari_code_execution`` tool and must compute the spans in Python in
the gateway's sandbox, and then we recompute every number locally with
``datetime``. A number is printed only if the two agree; otherwise it is
left off.
"""
from __future__ import annotations

import json
import re
from datetime import date

from .otari import Otari, OtariError

TMPL = """Use the code execution tool (Python) to compute, for each page below, the number of whole days
from first_seen to last_seen (both YYYYMMDD, take the first 8 characters of each timestamp). Then compute
the sum of all those day counts. Do not compute anything in your head.
Reply with JSON only: {{"days": {{"<id>": <int>, ...}}, "total_days": <int>}}

Pages (JSON):
{pages}"""


def local_days(first: str, last: str) -> int:
    f = date(int(first[:4]), int(first[4:6]), int(first[6:8]))
    l = date(int(last[:4]), int(last[4:6]), int(last[6:8]))
    return (l - f).days


def reckon(client: Otari, model: str, entries: list[dict]) -> dict:
    pages = {}
    for i, e in enumerate(entries):
        s = e.get("snapshot") or {}
        if s.get("first_seen") and s.get("timestamp"):
            pages[str(i)] = {"first_seen": s["first_seen"], "last_seen": s["timestamp"]}
    if not pages:
        return {"status": "nothing to reckon"}
    try:
        data, call = client.chat(
            "reckoner", model,
            [{"role": "user", "content": TMPL.format(pages=json.dumps(pages))}],
            tools=[{"type": "otari_code_execution"}], max_tool_iterations=3,
            temperature=0, max_tokens=1200)
    except OtariError as e:
        if e.budget_exhausted:
            raise
        return {"status": "unavailable", "error": e.detail[:160]}
    m = re.search(r"\{.*\}", Otari.text(data), re.S)
    try:
        claimed = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        claimed = {}
    agreed, disagreed = {}, []
    for pid, p in pages.items():
        mine = local_days(p["first_seen"], p["last_seen"])
        theirs = (claimed.get("days") or {}).get(pid)
        if isinstance(theirs, int) and theirs == mine:
            agreed[pid] = mine
        else:
            disagreed.append(pid)
    total_ok = claimed.get("total_days") == sum(local_days(p["first_seen"], p["last_seen"]) for p in pages.values())
    return {"status": "checked", "model": call.served_model or model, "agreed": agreed,
            "disagreed": disagreed, "total_days": claimed.get("total_days") if total_ok and not disagreed else None,
            "sandbox_cost_usd": call.cost_usd}


def span_words(days: int) -> str:
    years, rem = divmod(days, 365)
    months = rem // 30
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if months and years < 5:
        parts.append(f"{months} month{'s' if months != 1 else ''}")
    return " ".join(parts) or f"{days} days"
