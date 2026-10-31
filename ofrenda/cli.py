"""link-rot-ofrenda command line.

    python -m ofrenda examples/lost-links.txt -o docs/index.html

Input file: one URL per line. Optional extras on the same line, separated by
" | ":  a display name, and the last year the page was known to be alive, e.g.

    http://ffffound.com/ | FFFFOUND! | 2016

Lines starting with # are ignored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from . import __version__
from .extract import extract
from .liveness import cause_of_death
from .model import LocalModel, remember
from .render import render
from .wayback import Snapshot, fetch_archived_html, find_snapshot, pretty_ts

MARIGOLD = "\033[38;5;214m"
ROSE = "\033[38;5;205m"
DIM = "\033[2m"
GREEN = "\033[38;5;114m"
GREY = "\033[38;5;245m"
RESET = "\033[0m"


def color(on: bool):
    def c(code: str, s: str) -> str:
        return f"{code}{s}{RESET}" if on else s
    return c


def parse_input(path: str) -> list[dict]:
    items = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        item = {"url": parts[0], "label": None, "alive_until": None}
        for extra in parts[1:]:
            if re.fullmatch(r"\d{4}(\d{2}){0,5}", extra):
                item["alive_until"] = extra
            elif extra:
                item["label"] = extra
        items.append(item)
    return items


def own_words(info: dict) -> str:
    """A short verbatim quote from the page, used when the model is not trusted."""
    if info.get("description"):
        return info["description"][:240]
    lines = [ln for ln in info.get("text", "").splitlines()[:20]
             if len(ln.split()) >= 5 and "©" not in ln
             and not any(k in ln.lower() for k in ("copyright", "sign in", "log in", "sign up"))]
    quote = ""
    for ln in lines[:3]:
        if len(quote) >= 60 or len(quote) + len(ln) > 240:
            break
        quote = f"{quote} {ln}".strip()
    return quote or (lines[0][:240] if lines else "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ofrenda", description="Build an ofrenda for dead links.")
    ap.add_argument("input", help="text file with one URL per line")
    ap.add_argument("-o", "--out", default="docs/index.html", help="HTML file to write")
    ap.add_argument("--json", default=None, help="also write the raw results here (default: next to --out)")
    ap.add_argument("--backend", choices=["local", "otari"], default=os.environ.get("OFRENDA_BACKEND", "local"),
                    help="local: your own llama.cpp/Ollama server. otari: open-weight models through the "
                         "Otari.ai gateway (needs OTARI_API_KEY)")
    ap.add_argument("--endpoint", default=os.environ.get("OFRENDA_ENDPOINT", "http://127.0.0.1:8080/v1"),
                    help="OpenAI-compatible local endpoint (llama-server :8080/v1, Ollama :11434/v1)")
    ap.add_argument("--model", default=os.environ.get("OFRENDA_MODEL"),
                    help="model name to request and to credit on the page (default gemma-3-1b-it locally, "
                         "google/gemma-3-27b-it on Otari; e.g. gemma3:1b for Ollama)")
    ap.add_argument("--scribe-chain", default=os.environ.get(
                        "OFRENDA_SCRIBE_CHAIN",
                        "epitaph-chain,google/gemma-3-27b-it,mistralai/ministral-3-14b"),
                    help="otari only: comma-separated models/routing policies tried in order for the epitaphs "
                         "(an Otari routing policy name first, then catalog ids as client-side fallbacks)")
    ap.add_argument("--witness", default=os.environ.get("OFRENDA_WITNESS", "alibaba/qwen3-30b-a3b-instruct-2507"),
                    help="otari only: a second open-weight model that must agree each summary is supported "
                         "by the archived text ('none' to skip)")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--cache", default=".ofrenda-cache", help="where archived pages are cached")
    ap.add_argument("--no-liveness", action="store_true", help="skip the live 'cause of death' check")
    ap.add_argument("--title", default="Link Rot Ofrenda")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    a = ap.parse_args(argv)

    c = color(not a.no_color and sys.stdout.isatty() or os.environ.get("FORCE_COLOR") == "1")
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    if a.backend == "otari":
        from .otari import FallbackModel, Otari, OtariModel
        client = Otari(session_label=f"ofrenda-{time.strftime('%Y%m%d-%H%M%S')}")
        if a.model:  # one explicit model: no chain
            llm = OtariModel(client, a.model, temperature=a.temperature)
        else:
            chain = [m.strip() for m in a.scribe_chain.split(",") if m.strip()]
            llm = FallbackModel(client, chain, temperature=a.temperature)
            a.model = " → ".join(chain)
        a.endpoint = client.base
    else:
        a.model = a.model or "gemma-3-1b-it"
        client = None
        llm = LocalModel(a.endpoint, a.model, temperature=a.temperature)
    items = parse_input(a.input)

    print(c(MARIGOLD, f"🌼 link-rot-ofrenda {__version__}") + c(DIM, f"  model={a.model} @ {a.endpoint}"))
    print(c(DIM, f"   {len(items)} lost links to remember\n"))
    t0 = time.time()
    entries = []
    for i, item in enumerate(items, 1):
        url = item["url"]
        entry = dict(item)
        print(c(MARIGOLD, f"[{i}/{len(items)}] ") + url)
        entry["cause"] = "not checked" if a.no_liveness else cause_of_death(url)
        print(c(GREY, f"      cause of death : {entry['cause']}"))

        # Snapshot lookups are cached too, so a re-run with --no-liveness
        # needs no network at all (only the local model).
        lookup = cache / ("lookup-" + hashlib.sha1(f"{url}|{item['alive_until']}".encode()).hexdigest()[:16] + ".json")
        if lookup.exists():
            saved = json.loads(lookup.read_text(encoding="utf-8"))
            snap = Snapshot(**saved) if saved else None
        else:
            snap = find_snapshot(url, item["alive_until"])
            if snap:  # never cache a miss: the archive may just have been down
                lookup.write_text(json.dumps(snap.__dict__), encoding="utf-8")
        if not snap:
            print(c(ROSE, "      no snapshot    : the archive never saw it. Candle left unlit; nothing invented.\n"))
            entries.append(entry)
            continue
        entry["snapshot"] = {
            "timestamp": snap.timestamp, "pretty": pretty_ts(snap.timestamp),
            "first_seen": snap.first_seen, "first_seen_pretty": pretty_ts(snap.first_seen),
            "view_url": snap.view_url, "original": snap.url,
        }
        print(c(GREY, f"      last snapshot  : {pretty_ts(snap.timestamp)}  ({snap.view_url})"))

        key = hashlib.sha1(snap.raw_url.encode()).hexdigest()[:16]
        cached = cache / f"{key}.html"
        from_cache = cached.exists()
        if from_cache:
            page = cached.read_text(encoding="utf-8")
        else:
            try:
                page = fetch_archived_html(snap)
            except Exception as e:  # archive hiccup: remember honestly, not at all
                print(c(ROSE, f"      fetch failed   : archive unreachable ({e}). Candle left unlit.\n"))
                entry.pop("snapshot")
                entries.append(entry)
                continue
            cached.write_text(page, encoding="utf-8")
        info = extract(page)
        entry["title"] = info["title"]
        entry["own_words"] = own_words(info)
        source = "\n".join(x for x in (info["description"], info["text"]) if x)
        print(c(GREY, f"      recovered      : {len(source)} chars, title “{info['title'][:60]}”"
                      + (" (from local cache)" if from_cache else "")))

        if len(source) < 40:
            print(c(ROSE, "      too little text: the snapshot is nearly empty; quoting nothing, inventing nothing.\n"))
            entry["memory"] = {"summary": "", "epitaph": "Here a page once stood; the archive kept only its frame.",
                               "offering": "", "grounding": 0.0, "suspects": [], "verified": False}
            entries.append(entry)
            continue

        t = time.time()
        mem = remember(llm, url, pretty_ts(snap.timestamp), info["title"], source, name=item["label"])
        if client is not None and llm.last is not None:
            mem["served_by"] = {"requested": llm.last.requested, "model": llm.last.served_model,
                                "provider": llm.last.provider, "fallback": llm.last.fallback,
                                "skipped": list(getattr(llm, "skipped", []))}
            sb = mem["served_by"]
            print(c(GREY, f"      written by     : {sb['model']} on {sb['provider']} via Otari"
                          f" (asked for {sb['requested']}{', fell back' if sb['fallback'] else ''})"))
        if client is not None and a.witness != "none" and mem.get("verified"):
            from .witness import cross_examine
            w = cross_examine(client, a.witness, mem["summary"], f"{item['label']}\n{info['title']}\n{source}")
            mem["witness"] = w
            if w["verdict"] == "unsupported":
                mem["verified"] = False
                print(c(ROSE, f"      witness        : {w['model']} objects to: "
                              + "; ".join(f"“{p}”" for p in w["unsupported"])))
            else:
                print(c(GREY, f"      witness        : {w['model']} -> {w['verdict']}"))
        entry["memory"] = mem
        status = c(GREEN, "grounded") if mem.get("verified") else c(ROSE, "withheld, quoting the page instead")
        print(c(ROSE, f"      epitaph        : {mem.get('epitaph', '')}"))
        if mem.get("verified"):
            print(f"      summary        : {mem['summary']}")
        print(c(GREY, f"      check          : {int(mem.get('grounding', 0) * 100)}% of summary words found in source"
                      f"{', suspects ' + ', '.join(mem['suspects']) if mem.get('suspects') else ''} -> ") + status
              + c(DIM, f"  ({time.time() - t:.1f}s)") + "\n")
        entries.append(entry)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(entries, a.model, a.title), encoding="utf-8")
    json_path = Path(a.json) if a.json else out.with_name("ofrenda.json")
    json_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    lit = sum(1 for e in entries if e.get("snapshot"))
    if client is not None:
        print(c(DIM, f"   Otari: {len(client.calls)} gateway calls, ${client.spent:.4f} spent this run"))
    print(c(MARIGOLD, f"🕯️  {lit} candles lit, {len(entries) - lit} unlit.") +
          f" Wrote {out} and {json_path} in {time.time() - t0:.0f}s.")
    return 0
