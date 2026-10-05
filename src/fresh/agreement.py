"""Agreement between two annotators on the same fresh contract (Step 9b uses these)."""

from __future__ import annotations

import numpy as np


def span_f1(a: list[tuple[int, int]], b: list[tuple[int, int]], strict: bool = False) -> float:
    """Greedy first match in sorted order (not maximum overlap), one to one. Two spans match when the overlap
    covers at least half of either span (strict: of both). NaN when neither annotator marked the type."""
    if not a and not b:
        return float("nan")
    used, tp, bs = set(), 0, sorted(b)
    for s in sorted(a):
        for j, t in enumerate(bs):
            ov = min(s[1], t[1]) - max(s[0], t[0])
            half = (ov >= 0.5 * (s[1] - s[0]), ov >= 0.5 * (t[1] - t[0]))
            if j not in used and ov > 0 and (all(half) if strict else any(half)):
                used.add(j)
                tp += 1
                break
    return 2 * tp / (len(a) + len(b))


def presence_agreement(a: set[str], b: set[str], categories: list[str]) -> float:
    """Share of checklist items on which the two annotators agree (marked or not present)."""
    return float(np.mean([(c in a) == (c in b) for c in categories]))


def cohen_kappa(x, y) -> float:
    """Per clause type, pooled over all segments of the double-labeled contracts. Callers pass indicators
    built from raw_categories, so the 3 rare types (excluded as labels) get one too."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    po = (x == y).mean()
    pe = x.mean() * y.mean() + (1 - x.mean()) * (1 - y.mean())
    return float("nan") if pe == 1 else float((po - pe) / (1 - pe))
