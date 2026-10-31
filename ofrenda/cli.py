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
    ap.add_argument("--archivist", default=os.environ.get("OFRENDA_ARCHIVIST", "alibaba/qwen3-235b-a22b-instruct-2507"),
                    help="otari only: open-weight model that uses Otari web search to find where a dead page's "
                         "story lives now ('none' to skip)")
    ap.add_argument("--lookup", choices=["cdx", "mcp"], default="cdx",
                    help="otari only: 'cdx' asks the Wayback CDX API first and the Internet Archive MCP server "
                         "(through Otari) only if that fails; 'mcp' asks the MCP server first")
    ap.add_argument("--ia-mcp", default=os.environ.get("OFRENDA_IA_MCP", "https://internet-archive.caseyjhand.com/mcp"),
                    help="otari only: Streamable-HTTP URL of an Internet Archive MCP server")
    ap.add_argument("--reckoner", default=os.environ.get("OFRENDA_RECKONER", "openai/gpt-oss-120b"),
                    help="otari only: open-weight model that computes each page's span in Otari's code "
                         "sandbox; every number is re-checked locally ('none' to skip)")
    ap.add_argument("--max-spend", type=float, default=float(os.environ.get("OFRENDA_MAX_SPEND", "0.25")),
                    help="otari only: stop asking models once this run has spent this many USD (as reported by "
                         "Otari per call). Your workspace budget/ceiling in the Otari dashboard applies too.")
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
        client = Otari(session_label=f"ofrenda-{time.strftime('%Y%m%d-%H%M%S')}", max_spend=a.max_spend)
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
    budget_hit = None  # set once Otari (or --max-spend) says the money is spent
    from .otari import OtariError
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
            snap = None if (client is not None and a.lookup == "mcp") else find_snapshot(url, item["alive_until"])
            if snap is None and client is not None and a.archivist != "none" and not budget_hit:
                from .ia_mcp import lookup_via_mcp
                try:
                    lead, how = lookup_via_mcp(client, a.archivist, url, item["alive_until"], a.ia_mcp)
                except OtariError as e:
                    budget_hit, lead, how = e.detail[:120], None, {"error": "budget reached"}
                if lead is not None:
                    try:  # the MCP answer is a lead; believe it only if the snapshot really loads
                        page_check = fetch_archived_html(lead)
                    except Exception:
                        page_check = ""
                    if len(page_check) > 200:
                        snap = lead
                        entry["found_via"] = "Internet Archive MCP server via Otari"
                        print(c(GREY, f"      MCP lead       : {lead.timestamp} from {how.get('model')} -> verified by fetching it"))
                    else:
                        print(c(ROSE, f"      MCP lead       : {lead.timestamp} did not load; ignored"))
                else:
                    print(c(GREY, "      MCP lookup     : no successful capture reported"
                                  + (f" ({how['error'][:60]})" if how.get("error") else "")))
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
        try:
            if budget_hit:
                raise OtariError(402, budget_hit)
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
            if client is not None and a.archivist != "none":
                from .afterlife import find_afterlife
                akey = cache / ("afterlife-" + hashlib.sha1(url.encode()).hexdigest()[:16] + ".json")
                if akey.exists():
                    after = json.loads(akey.read_text(encoding="utf-8"))
                else:
                    after = find_afterlife(client, a.archivist, item["label"] or info["title"] or url, url,
                                           pretty_ts(snap.timestamp))
                    if after.get("links"):
                        akey.write_text(json.dumps(after), encoding="utf-8")
                entry["afterlife"] = after
                for link in after.get("links", []):
                    print(c(GREEN, f"      lives on at    : {link['url']}") + c(DIM, f"  ({link['title'][:50]})"))
                if not after.get("links"):
                    print(c(GREY, "      lives on at    : nothing verifiable found; leaving it blank"
                                  + (f" ({after['error'][:60]})" if after.get("error") else "")))
        except OtariError as e:
            if not e.budget_exhausted:
                raise
            budget_hit = budget_hit or e.detail[:120]
            mem = {"summary": "", "epitaph": "", "offering": "", "grounding": 0.0, "suspects": [],
                   "verified": False, "budget": budget_hit}
            print(c(ROSE, f"      budget reached : {budget_hit}. No model asked; the page speaks for itself."))
        entry["memory"] = mem
        status = c(GREEN, "grounded") if mem.get("verified") else c(ROSE, "withheld, quoting the page instead")
        print(c(ROSE, f"      epitaph        : {mem.get('epitaph', '')}"))
        if mem.get("verified"):
            print(f"      summary        : {mem['summary']}")
        print(c(GREY, f"      check          : {int(mem.get('grounding', 0) * 100)}% of summary words found in source"
                      f"{', suspects ' + ', '.join(mem['suspects']) if mem.get('suspects') else ''} -> ") + status
              + c(DIM, f"  ({time.time() - t:.1f}s)") + "\n")
        entries.append(entry)

    reckoning = None
    if client is not None and a.reckoner != "none" and not budget_hit:
        from .reckoner import reckon, span_words
        try:
            reckoning = reckon(client, a.reckoner, entries)
        except OtariError as e:
            reckoning = {"status": "skipped", "error": e.detail[:120]}
        for pid, days in (reckoning.get("agreed") or {}).items():
            entries[int(pid)]["span"] = {"days": days, "words": span_words(days)}
        if reckoning.get("status") == "checked":
            print(c(GREY, f"   reckoner: {reckoning['model']} computed {len(reckoning['agreed']) + len(reckoning['disagreed'])} spans in Otari's "
                          f"code sandbox; {len(reckoning['agreed'])} match a local check"
                          + (f", {len(reckoning['disagreed'])} disagreed and were dropped" if reckoning["disagreed"] else "")))
        else:
            print(c(GREY, f"   reckoner: {reckoning.get('status')} {reckoning.get('error', '')}"))

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(entries, a.model, a.title), encoding="utf-8")
    json_path = Path(a.json) if a.json else out.with_name("ofrenda.json")
    json_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    lit = sum(1 for e in entries if e.get("snapshot"))
    if client is not None:
        print(c(DIM, f"   Otari: {len(client.calls)} gateway calls, ${client.spent:.4f} spent this run"
                     f" (cap ${a.max_spend:g})" + (f"; stopped early: {budget_hit}" if budget_hit else "")))
        ledger_path = out.with_name("otari-ledger.json")
        ledger_path.write_text(json.dumps({"spent_usd": client.spent, "max_spend_usd": a.max_spend,
                                           "budget_hit": budget_hit, "reckoning": reckoning,
                                           "calls": client.ledger()}, indent=2), encoding="utf-8")
    print(c(MARIGOLD, f"🕯️  {lit} candles lit, {len(entries) - lit} unlit.") +
          f" Wrote {out} and {json_path} in {time.time() - t0:.0f}s.")
    return 0
