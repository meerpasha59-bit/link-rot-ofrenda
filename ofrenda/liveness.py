"""A gentle 'cause of death' check for a URL. Informational only."""
from __future__ import annotations

import socket
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (link-rot-ofrenda)"


def cause_of_death(url: str, timeout: float = 10.0) -> str:
    host = urllib.parse.urlsplit(url).hostname or ""
    if host.endswith(".invalid"):
        return "never resolvable (reserved .invalid domain)"
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror:
        return "the domain no longer resolves"
    # Try HTTPS first; plenty of old sites never had it, so fall back to HTTP.
    parts = urllib.parse.urlsplit(url)
    candidates = [parts._replace(scheme="https").geturl(), url]
    seen_error = ""
    for u in dict.fromkeys(candidates):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                final = r.geturl()
                old_host = host.removeprefix("www.")
                new_host = (urllib.parse.urlsplit(final).hostname or "").removeprefix("www.")
                if new_host and new_host != old_host:
                    return f"now redirects to {new_host}"
                return f"still answers (HTTP {r.status}); may not be dead after all"
        except urllib.error.HTTPError as e:
            seen_error = f"the server answers HTTP {e.code}"
        except Exception:
            seen_error = seen_error or "the server no longer answers"
    return seen_error or "unknown"
