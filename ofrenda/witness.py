"""A second witness: an independent open-weight model re-reads each summary.

The lexical grounding guard in ``model.py`` catches invented names, numbers
and summaries that wander off topic, but it cannot catch a fluent paraphrase
that overstates ("the page explains the reasons behind the decision" when the
page only links to a blog post). So, on the Otari backend, a *different*
open-weight model from a different lab (Qwen3 30B by default, while Gemma
writes) gets the archived text and the summary and must list every claim the
text does not support. The summary is shown only if both checks pass.

The witness can only take words away. It never writes anything that ends up
on the altar except its objection, quoted from the summary it objects to.
"""
from __future__ import annotations

import json
import re

from .otari import Otari, OtariError

WITNESS_SYSTEM = (
    "You are a strict fact-checker for an archive. You compare a short summary with the "
    "source text it was written from. A claim is supported only if the source text states "
    "it or directly implies it. General tone words (warm, beloved) are not claims. "
    "If the summary says the page explains, describes, lists or answers something, the source "
    "must actually contain that explanation or content; a heading, a question or a link pointing "
    "elsewhere does not count. "
    "Answer with JSON only."
)

WITNESS_TMPL = """SOURCE TEXT (recovered from the Internet Archive):
---
{source}
---

SUMMARY TO CHECK:
"{summary}"

Reply with JSON only: {{"unsupported": [<each phrase from the SUMMARY that the SOURCE TEXT does not support, copied exactly>], "verdict": "supported" or "unsupported"}}"""


def _parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if d.get("verdict") not in ("supported", "unsupported"):
        return None
    flagged = [p for p in d.get("unsupported") or [] if isinstance(p, str) and p.strip()]
    return {"verdict": d["verdict"], "unsupported": flagged}


def cross_examine(client: Otari, model: str, summary: str, source: str) -> dict:
    """Ask the witness model whether ``summary`` is supported by ``source``.

    Returns {"verdict": "supported"|"unsupported"|"unavailable", "unsupported": [...], "model": ...}.
    Phrases the witness flags are kept only if they really occur in the summary,
    so the witness cannot put words in the scribe's mouth either.
    """
    if not summary.strip():
        return {"verdict": "unavailable", "unsupported": [], "model": model}
    try:
        data, call = client.chat(
            "witness", model,
            [{"role": "system", "content": WITNESS_SYSTEM},
             {"role": "user", "content": WITNESS_TMPL.format(source=source[:6000], summary=summary)}],
            temperature=0, max_tokens=300, response_format={"type": "json_object"})
    except OtariError as e:
        if e.budget_exhausted:
            raise
        return {"verdict": "unavailable", "unsupported": [], "model": model, "error": e.detail[:120]}
    out = _parse(Otari.text(data))
    if out is None:
        return {"verdict": "unavailable", "unsupported": [], "model": call.served_model or model}
    low = summary.lower()
    out["unsupported"] = [p for p in out["unsupported"] if p.lower().strip(" .\"'") in low]
    if out["verdict"] == "unsupported" and not out["unsupported"]:
        out["verdict"] = "supported"  # an objection it cannot point to is not an objection
    out["model"] = call.served_model or model
    return out
