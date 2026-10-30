"""Local open-weight model client + grounding guard.

Talks to any OpenAI-compatible chat endpoint served on your own machine:
  * llama.cpp  ``llama-server -m gemma-3-1b-it-Q4_K_M.gguf``  -> http://127.0.0.1:8080/v1
  * Ollama     ``ollama pull gemma3:1b``                      -> http://127.0.0.1:11434/v1
No API key, no cloud. stdlib only.
"""
from __future__ import annotations

import json
import re
import urllib.request

SYSTEM = (
    "You write for a Day of the Dead ofrenda that remembers web pages that have "
    "disappeared. You are given text recovered from the Internet Archive. "
    "Use ONLY facts that appear in that text. Never invent dates, people, numbers "
    "or features. If the text says little, say little. Be warm and respectful, "
    "never mocking."
)

USER_TMPL = """Archived page: {url}
Captured by the Internet Archive on: {captured}
Page title: {title}

--- recovered text (may be partial) ---
{text}
--- end ---

Reply with JSON only, with these keys:
"summary": one or two plain sentences saying what this page offered its visitors. Reuse the page's own words where you can. Add nothing that is not in the recovered text.
"epitaph": one gravestone line, under 20 words, that names {name} and the one thing it gave people, as a tender farewell. No dates or numbers.
"offering": one to three words for a small, concrete thing to leave on the altar, taken from what the page was about."""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "epitaph": {"type": "string"},
        "offering": {"type": "string"},
    },
    "required": ["summary", "epitaph", "offering"],
}

STOP = set("""a an and are as at be by for from has have in is it its of on or that the
this to was were will with you your we our their they them he she his her i my me
not no but so if than then there here what which who whom when where why how all any
each more most other some such only own same too very can just also into over out up
about after before again once page site web website visitors
users people place offered offering offers one two let lets used use using".""".split())
# Framing words describe the page rather than assert facts about it, so they
# are not counted against the model ("This page details a platform called...").
STOP |= set("""details detail describes describe described platform service called named
through content allowing allows ability provides provided provide focusing focused
primarily mainly various""".split())


class LocalModel:
    def __init__(self, endpoint: str, model: str, temperature: float = 0.3,
                 max_tokens: int = 220, timeout: float = 300):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def chat(self, user: str, temperature: float | None = None) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": user}],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
            # Constrained JSON. llama-server and Ollama both accept this shape;
            # if a server ignores it we still parse the first {...} block.
            "response_format": {"type": "json_object", "schema": SCHEMA},
        }
        req = urllib.request.Request(
            self.endpoint + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.load(r)
        return data["choices"][0]["message"]["content"]


def parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not all(isinstance(d.get(k), str) and d.get(k).strip() for k in SCHEMA["required"]):
        return None
    return {k: d[k].strip() for k in SCHEMA["required"]}


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9'\-]{2,}", s.lower())


def _stem(w: str) -> str:
    for suf in ("ations", "ation", "ated", "ings", "ing", "ion", "ure", "ies", "es", "s", "ed", "ly"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def grounding(summary: str, source: str) -> tuple[float, list[str]]:
    """Share of the summary's content words found in the source text.

    Also returns 'suspect' tokens: capitalised names or numbers in the
    summary that never occur in the source, the classic signs of invention.
    """
    src = source.lower()
    src_stems = {_stem(w) for w in _words(src)}
    content = [w for w in _words(summary) if w not in STOP]
    if not content:
        return 1.0, []
    hits = sum(1 for w in content if _stem(w) in src_stems or w in src)
    suspects = []
    for tok in re.findall(r"\b(?:[A-Z][a-zA-Z]{2,}|\d{2,})\b", summary):
        if tok.lower() not in src and tok.lower() not in STOP:
            suspects.append(tok)
    return hits / len(content), sorted(set(suspects))


def remember(model: LocalModel, url: str, captured: str, title: str, text: str,
             name: str | None = None, min_grounding: float = 0.45) -> dict:
    """Ask the model for summary/epitaph; retry cooler if it drifts from the source."""
    prompt = USER_TMPL.format(url=url, captured=captured, title=title or "(none)", text=text,
                              name=name or title or "this page")
    best = None
    for temp in (model.temperature, 0.1):
        out = parse_json(model.chat(prompt, temperature=temp))
        if not out:
            continue
        score, suspects = grounding(out["summary"], f"{name}\n{title}\n{text}\n{url}")
        out.update(grounding=round(score, 2), suspects=suspects, temperature=temp)
        if best is None or score > best["grounding"]:
            best = out
        if score >= min_grounding and not suspects:
            break
    if best is None:
        return {"summary": "", "epitaph": "", "offering": "", "grounding": 0.0,
                "suspects": [], "error": "model returned no usable JSON"}
    best["verified"] = best["grounding"] >= min_grounding and not best["suspects"]
    return best
