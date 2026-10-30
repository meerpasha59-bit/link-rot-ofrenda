"""Talk to the Internet Archive's public Wayback Machine APIs (no key needed).

Two lookups are used:

* CDX search  (web.archive.org/cdx/search/cdx) to find the first and the last
  *successful* (HTTP 200, text/html) capture of a URL, optionally only up to a
  "last known alive" year, so we remember a site as it was rather than as the
  domain-parking page that replaced it.
* Availability API (archive.org/wayback/available) as a fallback when CDX is
  slow or empty.

Archived pages are fetched with the ``id_`` flag, which returns the original
bytes without the Wayback toolbar.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

USER_AGENT = "link-rot-ofrenda/0.1 (+https://github.com/meerpasha59-bit/link-rot-ofrenda)"
CDX = "https://web.archive.org/cdx/search/cdx"
AVAILABLE = "https://archive.org/wayback/available"


@dataclass
class Snapshot:
    url: str               # the original URL as the archive recorded it
    timestamp: str         # YYYYMMDDhhmmss
    first_seen: Optional[str] = None  # earliest 200 capture we know of

    @property
    def view_url(self) -> str:
        """Human-facing Wayback link (with toolbar)."""
        return f"https://web.archive.org/web/{self.timestamp}/{self.url}"

    @property
    def raw_url(self) -> str:
        """Original bytes, no toolbar."""
        return f"https://web.archive.org/web/{self.timestamp}id_/{self.url}"


def _get(url: str, timeout: float = 40.0, retries: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (OSError, TimeoutError) as e:  # URLError, HTTPError, resets
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last  # type: ignore[misc]


def _cdx(url: str, **params) -> list[list[str]]:
    q = {"url": url, "output": "json", "fl": "timestamp,original",
         "filter": ["statuscode:200", "mimetype:text/html"], **params}
    body = _get(CDX + "?" + urllib.parse.urlencode(q, doseq=True))
    if not body.strip():
        return []
    rows = json.loads(body)
    return rows[1:] if rows else []  # drop header row


def find_snapshot(url: str, alive_until: Optional[str] = None) -> Optional[Snapshot]:
    """Return the last good capture of ``url`` (up to ``alive_until`` if given).

    Returns None when the archive has never seen a successful capture: the
    caller must then refuse to describe the page.
    """
    to = {"to": alive_until} if alive_until else {}
    try:
        last = _cdx(url, limit=-1, **to)
        if last:
            ts, original = last[-1]
            try:
                first = _cdx(url, limit=1)
            except Exception:
                first = []
            return Snapshot(original, ts, first[0][0] if first else None)
    except Exception:
        pass  # fall through to the availability API

    params = {"url": url}
    if alive_until:
        params["timestamp"] = alive_until
    try:
        data = json.loads(_get(AVAILABLE + "?" + urllib.parse.urlencode(params)))
    except Exception:
        return None
    closest = data.get("archived_snapshots", {}).get("closest")
    if not closest or closest.get("status") != "200":
        return None
    # closest["url"] looks like http://web.archive.org/web/<ts>/<original>
    original = closest["url"].split("/", 5)[-1]
    return Snapshot(original, closest["timestamp"])


def fetch_archived_html(snap: Snapshot, max_bytes: int = 2_000_000) -> str:
    raw = _get(snap.raw_url, timeout=60)[:max_bytes]
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def pretty_ts(ts: Optional[str]) -> str:
    if not ts or len(ts) < 8:
        return "unknown"
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{int(ts[6:8])} {months[int(ts[4:6]) - 1]} {ts[:4]}"
