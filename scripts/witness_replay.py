"""Re-check an earlier ofrenda's summaries with the Otari witness.

    python scripts/witness_replay.py docs/ofrenda.json

docs/ofrenda.json was written by Gemma 3 1B running locally, checked only by
the lexical guard. This replays the second witness (an independent open-weight
model on Otari) over every summary the lexical guard let through, using the
cached archived text, and prints what it objects to.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ofrenda.extract import extract  # noqa: E402
from ofrenda.otari import Otari  # noqa: E402
from ofrenda.witness import cross_examine  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/ofrenda.json")
    model = os.environ.get("OFRENDA_WITNESS", "alibaba/qwen3-30b-a3b-instruct-2507")
    cache = Path(os.environ.get("OFRENDA_CACHE", ".ofrenda-cache"))
    client = Otari(session_label="witness-replay")
    for e in json.loads(path.read_text(encoding="utf-8")):
        mem, snap = e.get("memory") or {}, e.get("snapshot") or {}
        if not mem.get("verified") or not snap:
            continue
        raw = f"https://web.archive.org/web/{snap['timestamp']}id_/{snap['original']}"
        page = cache / (hashlib.sha1(raw.encode()).hexdigest()[:16] + ".html")
        if not page.exists():
            print(f"- {e.get('label')}: archived page not in cache, skipped")
            continue
        info = extract(page.read_text(encoding="utf-8"))
        source = f"{e.get('label')}\n{info['title']}\n{info['description']}\n{info['text']}"
        w = cross_examine(client, model, mem["summary"], source)
        mark = "OBJECTS" if w["verdict"] == "unsupported" else w["verdict"]
        print(f"- {e.get('label')}: {mark}")
        print(f"    summary : {mem['summary']}")
        for p in w.get("unsupported", []):
            print(f"    unsupported: “{p}”")
    print(f"\n{len(client.calls)} witness calls through Otari, ${client.spent:.5f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
