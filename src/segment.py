"""Split raw contract text into paragraph-like segments.

Standalone: takes any string (CUAD text, PDF text layer, OCR output) and returns
character-offset segments. Nothing here knows about CUAD or labels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src import config

LINE = re.compile(r"[^\n]+")
SENTENCE_BREAK = re.compile(r"(?<=[.;:!?])\s+(?=[\"'(\[]?[A-Z0-9])")
ENDS_SENTENCE = set(".;:!?")


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    text: str


def _strip(text: str, s: int, e: int) -> tuple[int, int] | None:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return (s, e) if s < e else None


def _lines(text: str) -> list[tuple[int, int, bool]]:
    """Non-empty stripped lines as (start, end, blank_line_before)."""
    out, prev_end = [], 0
    for m in LINE.finditer(text):
        b = _strip(text, m.start(), m.end())
        if b is None:
            continue
        out.append((b[0], b[1], text.count("\n", prev_end, b[0]) >= 2))
        prev_end = b[1]
    return out


def _unwrap(text: str, lines, max_chars: int) -> list[tuple[int, int]]:
    """Join hard-wrapped lines into paragraphs.

    A line continues the previous block unless a blank line separates them or the
    previous block already ends with sentence punctuation.
    """
    blocks: list[tuple[int, int]] = []
    for s, e, blank_before in lines:
        if (blocks and not blank_before
                and text[blocks[-1][1] - 1] not in ENDS_SENTENCE
                and e - blocks[-1][0] <= max_chars):
            blocks[-1] = (blocks[-1][0], e)
        else:
            blocks.append((s, e))
    return blocks


def _pack(pieces, max_chars: int) -> list[tuple[int, int]]:
    """Greedily join consecutive pieces while the joined span stays within max_chars."""
    out: list[tuple[int, int]] = []
    for s, e in pieces:
        if out and e - out[-1][0] <= max_chars:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def _split_long(text: str, s: int, e: int, max_chars: int) -> list[tuple[int, int]]:
    """Split a block longer than max_chars at sentence breaks, then at spaces."""
    if e - s <= max_chars:
        return [(s, e)]
    pieces, cur = [], s
    for m in SENTENCE_BREAK.finditer(text, s, e):
        pieces.append((cur, m.start()))
        cur = m.end()
    pieces.append((cur, e))
    out = []
    for ps, pe in pieces:
        while pe - ps > max_chars:
            cut = text.rfind(" ", ps, ps + max_chars)
            if cut <= ps:
                cut = ps + max_chars
            out.append((ps, cut))
            ps = cut
        out.append((ps, pe))
    out = [b for b in (_strip(text, a, z) for a, z in out) if b]
    return _pack(out, max_chars)


def _merge_short(bounds, min_chars: int) -> list[tuple[int, int]]:
    """Fold segments shorter than min_chars (headings, list markers) into the next one."""
    out: list[tuple[int, int]] = []
    pending = None
    for s, e in bounds:
        if pending is not None:
            s = pending
        if e - s < min_chars:
            pending = s
            continue
        pending = None
        out.append((s, e))
    if pending is not None:
        if out:
            out[-1] = (out[-1][0], bounds[-1][1])
        else:
            out.append((pending, bounds[-1][1]))
    return out


def segment_text(text: str, min_chars: int = config.SEGMENT_MIN_CHARS,
                 max_chars: int = config.SEGMENT_MAX_CHARS) -> list[Segment]:
    """Paragraph-like segments with offsets into `text`. Empty text gives [].

    max_chars is not a hard cap: a piece shorter than min_chars (such as a heading)
    is folded into the next segment and can push it past max_chars.
    """
    bounds: list[tuple[int, int]] = []
    for s, e in _unwrap(text, _lines(text), max_chars):
        bounds.extend(_split_long(text, s, e, max_chars))
    bounds = _merge_short(bounds, min_chars)
    return [Segment(s, e, text[s:e]) for s, e in bounds]
