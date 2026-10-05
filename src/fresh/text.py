"""Pinned HTML to text conversion for fresh contracts. The output is the gold text: label offsets
are code points into it, and its SHA-256 goes into every label export."""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section",
         "td", "th", "dd", "dt", "blockquote", "pre", "ul", "ol", "hr"}
SKIP = {"script", "style"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in SKIP
        if tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        self.skip = max(0, self.skip - (tag in SKIP))
        if tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    p.close()
    if p.skip != 0:
        raise ValueError("unclosed script or style")
    lines = [" ".join(line.replace("\xa0", " ").split()) for line in "".join(p.parts).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def sha256(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()
