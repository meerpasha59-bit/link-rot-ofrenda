"""Second route to the archive: the Internet Archive MCP server, called through Otari.

The direct Wayback CDX API is sometimes slow or briefly unreachable, and then
the ofrenda used to leave the candle unlit. Now Otari is asked to connect a
public, keyless Internet Archive MCP server (``ia_find_snapshots`` tool,
https://github.com/cyanheads/internet-archive-mcp-server) and an open-weight
model looks the page up through it.

The MCP answer is a lead, not a fact: a snapshot is accepted only after we
fetch it from web.archive.org ourselves and get a real archived page back.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from .otari import Otari, OtariError
from .wayback import Snapshot

DEFAULT_MCP = "https://internet-archive.caseyjhand.com/mcp"

TMPL = """Call ia_find_snapshots once for the URL {url} using the closest-timestamp mode near {near}.
Then reply with JSON only, copied exactly from the tool result:
{{"timestamp": "<14-digit YYYYMMDDhhmmss of a capture with HTTP status 200>", "original": "<the archived URL>"}}
or {{"timestamp": null}} if the archive has no successful capture."""

_TS = re.compile(r"^\d{14}$")


def lookup_via_mcp(client: Otari, model: str, url: str, alive_until: Optional[str],
                   mcp_url: str = DEFAULT_MCP) -> tuple[Optional[Snapshot], dict]:
    near = (alive_until or "2010")[:4] + "-06-01"
    try:
        data, call = client.chat(
            "archive-mcp", model,
            [{"role": "user", "content": TMPL.format(url=url, near=near)}],
            mcp_servers=[{"name": "internet-archive", "url": mcp_url,
                          "allowed_tools": ["ia_find_snapshots"],
                          "purpose_hint": "Look up Wayback Machine captures of a URL."}],
            max_tool_iterations=3, temperature=0, max_tokens=300)
    except OtariError as e:
        if e.budget_exhausted:
            raise
        return None, {"error": e.detail[:160]}
    m = re.search(r"\{.*\}", Otari.text(data), re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    ts, original = str(d.get("timestamp") or ""), d.get("original") or url
    info = {"model": call.served_model or model, "claimed": d}
    if not _TS.match(ts):
        return None, info
    if isinstance(original, str) and original.startswith("https://web.archive.org/web/"):
        original = original.split("/", 5)[-1]  # a full Wayback link: keep the original URL part
    return Snapshot(original, ts), info
