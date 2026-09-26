"""Validate one LLM response against the call that produced it (Step 3).

A response is valid only if it finished normally, is JSON with "segments" (a list, or an object keyed by target id), and covers
every target id exactly once with known labels and confidences in [0, 1]. Valid entries are
kept even when other entries fail, so the caller can salvage them after the one retry.
Labels listed below the confidence floor are dropped, so they score the same as unlisted
labels (Rule D).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from src import config


@dataclass
class Parsed:
    scores: dict[str, dict[str, float]]  # local target id -> {label: confidence}, valid ids only
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _valid_confidence(c) -> bool:
    return (isinstance(c, (int, float)) and not isinstance(c, bool)
            and not math.isnan(c) and 0.0 <= c <= 1.0)


def parse_response(text: str | None, finish: str, target_ids: list[str], labels: set[str],
                   floor: float = config.LLM_CONFIDENCE_FLOOR, dense: bool = False) -> Parsed:
    targets = set(target_ids)
    if finish != "ok":  # max_tokens, refusal, or anything unexpected
        return Parsed({}, [f"finish={finish}"])
    try:
        data = json.loads(text or "")
    except json.JSONDecodeError as e:
        return Parsed({}, [f"invalid JSON: {e.msg}"])
    segs = data.get("segments") if isinstance(data, dict) else None
    if isinstance(segs, dict):
        entries = list(segs.items())
    elif isinstance(segs, list):
        entries = [(e.get("id"), e.get("labels")) if isinstance(e, dict) else (None, None) for e in segs]
    else:
        return Parsed({}, ["missing 'segments'"])

    errors, scores, seen, bad = [], {}, set(), set()
    for sid, items in entries:
        if not isinstance(sid, str) or sid not in targets:
            errors.append(f"unexpected id {sid!r}")  # a context segment or an invented id
            continue
        if sid in seen:
            errors.append(f"duplicate id {sid}")
            bad.add(sid)
            continue
        seen.add(sid)
        if dense:
            if not isinstance(items, dict) or set(items) != labels:
                errors.append(f"{sid}: dense answer must score exactly the {len(labels)} labels")
                bad.add(sid)
                continue
            invalid = [lab for lab, c in items.items() if not _valid_confidence(c)]
            if invalid:
                errors.append(f"{sid}: confidence {items[invalid[0]]!r} for {invalid[0]}")
                bad.add(sid)
                continue
            scores[sid] = {lab: float(c) for lab, c in items.items()}
            continue
        if not isinstance(items, list):
            errors.append(f"{sid}: labels is not a list")
            bad.add(sid)
            continue
        conf: dict[str, float] = {}
        for item in items:
            lab = item.get("label") if isinstance(item, dict) else None
            c = item.get("confidence") if isinstance(item, dict) else None
            if lab not in labels:
                errors.append(f"{sid}: unknown label {lab!r}")
                bad.add(sid)
                break
            if not _valid_confidence(c):
                errors.append(f"{sid}: confidence {c!r} for {lab}")
                bad.add(sid)
                break
            conf[lab] = max(conf.get(lab, 0.0), float(c))  # a repeated label keeps its max
        else:
            scores[sid] = {lab: c for lab, c in conf.items() if c >= floor}  # Rule D: below floor = unlisted
    errors += [f"missing id {sid}" for sid in sorted(targets - seen)]
    for sid in bad:
        scores.pop(sid, None)
    return Parsed(scores, errors)
