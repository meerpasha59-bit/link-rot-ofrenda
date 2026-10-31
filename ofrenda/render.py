"""Render the ofrenda as one self-contained static HTML file (no JS, no CDN)."""
from __future__ import annotations

import html
from datetime import datetime, timezone

CSS = r"""
:root{--night:#1b1030;--plum:#2d1748;--marigold:#f5a524;--marigold2:#ff7b00;--bone:#f6ecd9;
--rose:#e2457a;--teal:#2bb3a3;--ink:#2a1a12}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(ellipse at top,#3a1f5c 0%,var(--night) 60%) fixed;color:var(--bone);
font:17px/1.55 Georgia,'Iowan Old Style','Palatino Linotype',serif}
.papel{display:flex;justify-content:center;gap:0;height:70px;overflow:hidden}
.papel span{flex:1;max-width:110px;height:64px;clip-path:polygon(0 0,100% 0,100% 72%,85% 100%,70% 72%,50% 100%,30% 72%,15% 100%,0 72%);
-webkit-mask:radial-gradient(circle at 50% 38%,transparent 9px,#000 10px);mask:radial-gradient(circle at 50% 38%,transparent 9px,#000 10px)}
.papel span:nth-child(5n+1){background:var(--rose)}.papel span:nth-child(5n+2){background:var(--marigold)}
.papel span:nth-child(5n+3){background:var(--teal)}.papel span:nth-child(5n+4){background:#9b5de5}.papel span:nth-child(5n){background:var(--marigold2)}
header{text-align:center;padding:28px 20px 8px}
h1{font-size:clamp(2rem,5vw,3.4rem);margin:.2em 0;color:var(--marigold);letter-spacing:.02em;text-shadow:0 0 18px rgba(245,165,36,.45)}
.sub{max-width:760px;margin:0 auto;color:#e9d9bf;font-style:italic}
.stats{margin:18px auto 0;color:#cdb8e6;font-size:.95rem}
.altar{max-width:1100px;margin:28px auto 40px;padding:0 18px;display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:46px 22px}
.card{position:relative;background:linear-gradient(180deg,#fff8ea,#f3e3c4);color:var(--ink);border-radius:14px;padding:26px 22px 18px;
box-shadow:0 10px 30px rgba(0,0,0,.45),0 0 0 3px var(--marigold) inset}
.card:before{content:"";position:absolute;inset:-10px;border-radius:20px;z-index:-1;
background:repeating-radial-gradient(circle at 10px 10px,var(--marigold) 0 6px,var(--marigold2) 7px 9px,transparent 10px 20px);opacity:.9}
.candle{position:absolute;top:-30px;right:22px;width:16px;height:34px;background:var(--bone);border-radius:3px;box-shadow:0 0 0 2px #d8c7a6 inset}
.candle:after{content:"";position:absolute;left:3px;top:-16px;width:10px;height:16px;border-radius:50% 50% 50% 50%/60% 60% 40% 40%;
background:radial-gradient(circle at 50% 70%,#fff6b0,#ffb703 45%,#ff6b00 80%);box-shadow:0 0 16px 6px rgba(255,170,0,.55);animation:flick 2.4s infinite ease-in-out}
.unlit .candle:after{display:none}
@keyframes flick{0%,100%{transform:scale(1) rotate(-2deg)}50%{transform:scale(1.08,.94) rotate(2deg)}}
.name{font-size:1.25rem;margin:0 0 2px;color:#5a1d3c}
.url{font:13px/1.3 ui-monospace,Menlo,Consolas,monospace;color:#7a5a46;word-break:break-all}
.dates{font-size:.85rem;color:#7b4b2a;margin:8px 0 10px;letter-spacing:.03em}
.epitaph{font-size:1.12rem;font-style:italic;color:#3b1530;border-left:4px solid var(--rose);padding:2px 0 2px 12px;margin:10px 0}
.summary{font-size:.98rem;margin:8px 0}
.own{font-size:.95rem;margin:8px 0;color:#4d3324}
.own b{font-variant:small-caps}
.meta{display:flex;flex-wrap:wrap;gap:6px 10px;font-size:.78rem;color:#6d5141;margin-top:12px;border-top:1px dashed #cfb48a;padding-top:10px}
.tag{background:#fde2b8;border-radius:999px;padding:1px 9px}
.tag.ok{background:#cdeedd}.tag.warn{background:#ffd3c9}
.card a{color:#a2361b}
.unlit{background:linear-gradient(180deg,#e8e1d6,#cfc6b8);filter:saturate(.6)}
.unlit:before{opacity:.25}
.refusal{font-style:italic;color:#3d3a36}
.afterlife{font-size:.88rem;margin:8px 0 0;color:#4d3324}
.afterlife a{display:inline-block;margin-right:8px}
.who{font-size:.74rem;color:#7a5a46;margin-top:6px;font-family:ui-monospace,Menlo,Consolas,monospace}
.objection{font-size:.8rem;color:#8a2b1b;margin:4px 0}
footer{max-width:820px;margin:0 auto 50px;padding:0 18px;color:#cdb8e6;font-size:.9rem;text-align:center}
footer a{color:var(--marigold)}
"""


def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def card(entry: dict) -> str:
    if not entry.get("snapshot"):
        return f"""
<article class="card unlit">
  <div class="candle" aria-hidden="true"></div>
  <h2 class="name">{_e(entry.get('label') or entry['url'])}</h2>
  <div class="url">{_e(entry['url'])}</div>
  <div class="dates">no snapshot in the Internet Archive</div>
  <p class="refusal">We found no memory of this page, so we will not invent one.
  This candle stays unlit until someone brings a real photograph.</p>
  <div class="meta"><span class="tag">{_e(entry.get('cause', ''))}</span></div>
</article>"""
    snap = entry["snapshot"]
    mem = entry.get("memory", {})
    w = mem.get("witness") or {}
    if mem.get("verified"):
        summary = f'<p class="summary">{_e(mem["summary"])}</p>'
        badge = f'<span class="tag ok" title="share of summary words found in the archived text">grounded {int(mem["grounding"]*100)}%</span>'
        if w.get("verdict") == "supported":
            badge += f' <span class="tag ok" title="an independent open-weight model found every claim in the archived text">witness agrees</span>'
    elif mem.get("budget"):
        quote = entry.get("own_words") or "(the archived text was too thin to quote)"
        summary = f'<p class="own"><b>In its own words:</b> &ldquo;{_e(quote.strip())}&rdquo;</p>'
        badge = '<span class="tag warn" title="the spend limit was reached before a model was asked">budget reached: no model text</span>'
    elif w.get("verdict") == "unsupported":
        quote = entry.get("own_words") or "(the archived text was too thin to quote)"
        summary = (f'<p class="own"><b>In its own words:</b> &ldquo;{_e(quote.strip())}&rdquo;</p>'
                   f'<p class="objection">The witness ({_e(w.get("model"))}) objected to: '
                   + "; ".join(f"&ldquo;{_e(x)}&rdquo;" for x in w.get("unsupported", [])) + '</p>')
        badge = '<span class="tag warn" title="a second model found claims the archived text does not support">summary withheld by the witness</span>'
    else:
        quote = entry.get("own_words") or "(the archived text was too thin to quote)"
        summary = f'<p class="own"><b>In its own words:</b> &ldquo;{_e(quote.strip())}&rdquo;</p>'
        badge = '<span class="tag warn" title="the model drifted from the source, so we quote the page instead">model summary withheld</span>'
    first = ""
    if snap.get("first_seen"):
        first = f"address first archived {_e(snap['first_seen_pretty'])} &middot; "
    span = ""
    if entry.get("span"):
        span = (f' &middot; <span title="computed in Otari\'s code sandbox and re-checked locally">'
                f'archived across {_e(entry["span"]["words"])}</span>')
    links = (entry.get("afterlife") or {}).get("links") or []
    afterlife = ""
    if links:
        afterlife = ('<p class="afterlife"><b>Its story lives on:</b> '
                     + " ".join(f'<a href="{_e(l["url"])}" title="found by Otari web search: {_e(l["url"])}">{_e(l["title"] or l["url"])}</a>'
                                for l in links) + '</p>')
    sb = mem.get("served_by") or {}
    who = ""
    if sb.get("model"):
        who = (f'<div class="who">written by {_e(sb["model"])} on {_e(sb.get("provider"))} via Otari'
               + (" (fallback)" if sb.get("fallback") else "")
               + (f' &middot; checked by {_e(w.get("model"))}' if w.get("model") and w.get("verdict") != "unavailable" else "")
               + '</div>')
    found = '<span class="tag">found via Internet Archive MCP</span>' if entry.get("found_via") else ""
    offering = mem.get("offering", "").rstrip(".")
    if len(offering.split()) > 4:  # the prompt asks for 1-3 words; skip rambling ones
        offering = ""
    return f"""
<article class="card">
  <div class="candle" aria-hidden="true"></div>
  <h2 class="name">{_e(entry.get('label') or entry.get('title') or entry['url'])}</h2>
  <div class="url">{_e(entry['url'])}</div>
  <div class="dates">{first}last remembered {_e(snap['pretty'])}{span}</div>
  {'<p class="epitaph">' + _e(mem.get('epitaph')) + '</p>' if mem.get('epitaph') else ''}
  {summary}
  {afterlife}
  <div class="meta">
    {'<span class="tag">offering: ' + _e(offering) + '</span>' if offering else ''}
    {badge}
    <span class="tag">{_e(entry.get('cause', ''))}</span>
    {found}
    <a href="{_e(snap['view_url'])}">visit the snapshot &rarr;</a>
  </div>
  {who}
</article>"""


def render(entries: list[dict], model_name: str, title: str = "Link Rot Ofrenda",
           backend: str = "local", spent: float | None = None) -> str:
    lit = sum(1 for e in entries if e.get("snapshot"))
    when = datetime.now(timezone.utc).strftime("%d %b %Y")
    cards = "\n".join(card(e) for e in entries)
    papel = "<span></span>" * 14
    if backend == "otari":
        intro = ("<p class=\"sub\">For the pages that are gone. Each one is remembered from its last snapshot in the "
                 "Internet Archive. Open-weight models reached through <a href=\"https://otari.ai\" style=\"color:var(--marigold)\">Otari</a>, "
                 "Mozilla.ai's AI gateway, did the work: Gemma wrote, a second model checked every summary against the archived text, "
                 "a third searched the web for where each story lives now, and the numbers were computed in a sandbox and re-checked. "
                 "Nothing here was written from memory.</p>")
    else:
        intro = (f"<p class=\"sub\">For the pages that are gone. Each one is remembered from its last snapshot in the "
                 f"Internet Archive, and the words were written by <b>{_e(model_name)}</b>, an open-weight model running "
                 f"locally on a CPU, using only what the archive kept.</p>")
    otari_note = (" Models served through <a href=\"https://github.com/mozilla-ai/otari\">Otari</a>; "
                  "every link under &ldquo;its story lives on&rdquo; came from Otari's web search results, never from a model's memory."
                  if backend == "otari" else "")
    cost = f" &middot; ${spent:.4f} of model time via Otari" if spent is not None else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="An ofrenda for web pages that died, remembered from the Internet Archive by a local open-weight model.">
<style>{CSS}</style></head>
<body>
<div class="papel" aria-hidden="true">{papel}</div>
<header>
  <h1>&#127804; {_e(title)} &#127804;</h1>
  {intro}
  <p class="stats">{lit} candles lit &middot; {len(entries) - lit} left unlit for lack of memory &middot; built {when}{cost}</p>
</header>
<main class="altar">
{cards}
</main>
<footer>
  <p>Made with <a href="https://github.com/meerpasha59-bit/link-rot-ofrenda">link-rot-ofrenda</a>.
  Snapshots courtesy of the <a href="https://web.archive.org/">Internet Archive's Wayback Machine</a>.
  Summaries are checked against the archived text; where the model strayed, the page speaks in its own words instead.{otari_note}</p>
</footer>
</body></html>"""
