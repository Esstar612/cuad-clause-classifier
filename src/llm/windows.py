"""Fixed context windows, call batches, the iteration sample, and the casebook (Step 3).

Every segment is always shown inside the same fixed window of consecutive segments from its
contract, whatever the batch size. Batch size changes only how many of the window's segments
a call must label, never the context a segment is read in.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src import config

WINDOW = config.LLM_WINDOW_SIZE

# Step 4a validation cases (baseline error analysis on validation, never on test).
NAMED_CASES = ("169_105", "131_54", "11_59", "51_228")  # Most Favored Nation false negatives
CONFUSED_PAIRS = (("License Grant", "Exclusivity"), ("Anti-Assignment", "Change Of Control"))
CASES_PER_PAIR = 5


@dataclass(frozen=True)
class Call:
    key: str                      # stable: contract, window, batch size, first target
    contract_id: int
    window: int
    segment_ids: tuple[str, ...]  # the whole window, in document order
    texts: tuple[str, ...]
    targets: tuple[str, ...]      # the segments this call must label


def windows(segments: pd.DataFrame) -> list[tuple[int, int, pd.DataFrame]]:
    """Each contract's segments in seg_idx order, cut into consecutive windows of WINDOW
    (the last one may be shorter). No randomness: membership and order are fixed."""
    out = []
    ordered = segments.sort_values(["contract_id", "seg_idx"])
    for cid, group in ordered.groupby("contract_id", sort=True):
        group = group.reset_index(drop=True)
        for w, start in enumerate(range(0, len(group), WINDOW)):
            out.append((int(cid), w, group.iloc[start:start + WINDOW]))
    return out


def build_calls(segments: pd.DataFrame, batch_size: int) -> list[Call]:
    """batch_size == WINDOW: one call per window, every segment a target.
    batch_size == 1: one call per segment, each showing the same whole window with that
    segment as the only target. Either way each segment is labeled exactly once."""
    if batch_size not in (1, WINDOW):
        raise ValueError(f"batch size must be 1 or {WINDOW}")
    calls = []
    for cid, w, win in windows(segments):
        ids, texts = tuple(win["segment_id"]), tuple(win["text"])
        groups = [ids] if batch_size == WINDOW else [(sid,) for sid in ids]
        for targets in groups:
            calls.append(Call(f"c{cid}_w{w}_n{batch_size}_{targets[0]}", cid, w, ids, texts, targets))
    return calls


def iteration_contracts(segments: pd.DataFrame, contracts: pd.DataFrame,
                        min_segments: int = config.LLM_ITERATION_MIN_SEGMENTS,
                        seed: int = config.SEED) -> pd.DataFrame:
    """Whole validation contracts, seeded (Rule E). Shuffle contracts within each type, shuffle
    the type order, then take one contract per type, round after round, until the sample has at
    least `min_segments` segments and at least one contract from every validation type."""
    sizes = segments[segments["split"] == "val"].groupby("contract_id").size()
    c = contracts[contracts["contract_id"].isin(sizes.index)].sort_values("contract_id")
    rng = np.random.default_rng(seed)
    queues = {t: [int(x) for x in rng.permutation(g["contract_id"].to_numpy())]
              for t, g in c.groupby("contract_type", sort=True)}
    type_order = [str(t) for t in rng.permutation(sorted(queues))]
    chosen, total = [], 0

    def done() -> bool:
        return total >= min_segments and len({r["contract_type"] for r in chosen}) == len(queues)

    while not done() and any(queues.values()):
        for t in type_order:
            if done():
                break
            if queues[t]:
                cid = queues[t].pop(0)
                chosen.append({"contract_id": cid, "contract_type": t, "segments": int(sizes[cid])})
                total += int(sizes[cid])
    return pd.DataFrame(chosen)


def casebook(baseline_val: pd.DataFrame, seed: int = config.SEED) -> pd.DataFrame:
    """Starting test cases from the Step 4a validation error analysis. Reported separately;
    never a selection criterion."""
    rng = np.random.default_rng(seed)
    rows = [{"segment_id": s, "case": "Most Favored Nation (Step 4a)"} for s in NAMED_CASES]
    true = baseline_val["true_labels"].map(set)
    pred = baseline_val["pred_labels"].map(lambda ps: {d["label"] for d in ps})
    for a, b in CONFUSED_PAIRS:
        mask = (true.map(lambda t: a in t and b not in t) & pred.map(lambda p: b in p)).to_numpy()
        ids = sorted(baseline_val.loc[mask, "segment_id"])
        pick = sorted(rng.choice(ids, size=min(CASES_PER_PAIR, len(ids)), replace=False)) if ids else []
        rows += [{"segment_id": str(s), "case": f"{a} misread as {b} (baseline)"} for s in pick]
    return pd.DataFrame(rows)


N1_HALF_STREAM = b"n1-half"


def n1_half_contracts(sample: pd.DataFrame, seed: int = config.SEED) -> pd.DataFrame:
    """Seeded half of the iteration contracts, rounded up; whole contracts, unstratified (Rule E, 3u)."""
    ordered = sample.sort_values("contract_id").reset_index(drop=True)
    rng = np.random.default_rng([seed, zlib.crc32(N1_HALF_STREAM)])
    picked = rng.choice(len(ordered), size=-(-len(ordered) // 2), replace=False)
    return ordered.iloc[sorted(picked)].reset_index(drop=True)
