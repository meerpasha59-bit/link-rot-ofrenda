"""Turn archived HTML into a small amount of plain, readable text (stdlib only)."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "svg", "head", "iframe", "form", "nav", "footer"}
BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "td",
         "section", "article", "blockquote", "dd", "dt", "header", "pre"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self._in_title = False
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta" and (a.get("name") or a.get("property") or "").lower() in (
                "description", "og:description"):
            self.description = self.description or (a.get("content") or "").strip()
        if tag in SKIP:
            self._skip += 1
        if tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in SKIP and self._skip:
            self._skip -= 1
        if tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def extract(page_html: str, max_chars: int = 1800) -> dict:
    p = _TextParser()
    try:
        p.feed(page_html)
    except Exception:
        pass
    text = "".join(p.parts)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", html.unescape(line)).strip()
        # keep lines that look like prose or headings, drop menu crumbs
        if len(line) >= 25 or (len(line) >= 4 and len(line.split()) >= 2 and line[0].isupper()):
            lines.append(line)
    body = "\n".join(dict.fromkeys(lines))  # de-duplicate, keep order
    return {
        "title": re.sub(r"\s+", " ", p.title).strip()[:160],
        "description": p.description[:400],
        "text": body[:max_chars],
    }
