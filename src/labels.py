"""Map CUAD categories to model labels and label segments from lawyer spans.

Rules are documented in docs/labeling_schema.md.
"""

from __future__ import annotations

from collections import defaultdict

from src.segment import Segment, segment_text

EXTRACTION = frozenset({"Document Name", "Parties", "Agreement Date", "Effective Date"})
RARE_DROPPED = frozenset({"Source Code Escrow", "Price Restrictions",
                          "Unlimited/All-You-Can-Eat-License"})
MERGED = {"Affiliate License-Licensor": "Affiliate License",
          "Affiliate License-Licensee": "Affiliate License"}
FLAGGED = frozenset({"Warranty Duration"})  # GitHub issue #23

# Pre-registered (2026-09-23, from data/processed/shift_coverage.txt, before any model
# was trained): labels with at least 10 shift-set contracts. Per-label shift results are
# reported only for these; the other kept labels are listed as not measurable on shift.
SHIFT_MEASURABLE_LABELS = frozenset({
    "Governing Law", "Expiration Date", "Anti-Assignment", "Insurance", "Renewal Term",
    "Cap On Liability", "Minimum Commitment", "Audit Rights", "Non-Compete",
    "Notice Period To Terminate Renewal", "Revenue/Profit Sharing", "Volume Restriction",
    "License Grant", "Exclusivity", "Post-Termination Services", "Covenant Not To Sue",
    "Liquidated Damages",
})


def model_label(category: str) -> str | None:
    """Model label for a CUAD category, or None if it carries no clause label."""
    if category in EXTRACTION or category in RARE_DROPPED:
        return None
    return MERGED.get(category, category)


def label_set(categories) -> list[str]:
    return sorted({lab for c in categories if (lab := model_label(c))})


def merge_intervals(intervals) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def matched_categories(seg: Segment, merged_by_cat, min_coverage: float) -> set[str]:
    """Categories whose merged span covers >= min_coverage of the span or of the segment."""
    hits = set()
    seg_len = seg.end - seg.start
    for cat, intervals in merged_by_cat.items():
        covered = 0
        for s, e in intervals:
            overlap = min(e, seg.end) - max(s, seg.start)
            if overlap <= 0:
                continue
            covered += overlap
            if overlap / (e - s) >= min_coverage:
                hits.add(cat)
                break
        if covered / seg_len >= min_coverage:
            hits.add(cat)
    return hits


def assign(raw_categories: set[str]) -> tuple[frozenset[str], bool]:
    """(labels, exclude). Extraction-only segments get no labels (none).
    Segments whose only clause labels are rare-dropped ones are excluded."""
    labels = frozenset(lab for c in raw_categories if (lab := model_label(c)))
    exclude = not labels and bool(raw_categories & RARE_DROPPED)
    return labels, exclude


def label_contract(text: str, spans, min_chars: int, max_chars: int, min_coverage: float):
    """spans: iterable of (category, start, end) for one contract.
    Returns (segment rows, merged intervals by category)."""
    by_cat = defaultdict(list)
    for cat, s, e in spans:
        by_cat[cat].append((int(s), int(e)))
    merged = {c: merge_intervals(iv) for c, iv in by_cat.items()}
    rows = []
    for i, seg in enumerate(segment_text(text, min_chars, max_chars)):
        raw = matched_categories(seg, merged, min_coverage)
        labels, exclude = assign(raw)
        rows.append({"seg_idx": i, "start": seg.start, "end": seg.end, "text": seg.text,
                     "labels": sorted(labels), "raw_categories": sorted(raw),
                     "exclude": exclude})
    return rows, merged
