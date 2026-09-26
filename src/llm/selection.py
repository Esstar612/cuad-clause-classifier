"""Selection rules and Rule B thresholds for the LLM classifiers (Step 3).

Prompt versions and batch sizes are compared on the iteration sample by micro-F1 at 0.5 with
a paired contract bootstrap. The bootstrap is unstratified there: most contract types have a
single contract in the sample, and a stratified bootstrap always redraws a single-contract
stratum, which would make the intervals too narrow.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import config
from src.bootstrap import f1_metrics, paired_difference, per_contract_counts, resample_weights
from src.evaluate import indicator
from src.thresholds import pooled_labels, tune_thresholds


def unstratified_weights(contract_ids, stream: str = "iteration",
                         n_resamples: int = config.BOOTSTRAP_RESAMPLES, seed: int = config.SEED):
    """Resample contracts with every contract in one stratum (no stratification)."""
    c = pd.DataFrame({"contract_id": sorted({int(x) for x in contract_ids}), "contract_type": "all"})
    return resample_weights(c, stream=stream, n_resamples=n_resamples, seed=seed)


def _predicted(frame: pd.DataFrame, label_order: list[str]) -> np.ndarray:
    return indicator([[d["label"] for d in ps] for ps in frame["pred_labels"]], label_order)


def paired_micro_f1(a: pd.DataFrame, b: pd.DataFrame, label_order: list[str]) -> dict:
    """A minus B on the same segments, paired over identical unstratified contract resamples.
    micro-F1 decides; macro-F1 is reported only. Parse failures are empty predictions."""
    if set(a["segment_id"]) != set(b["segment_id"]):
        raise ValueError("the two runs cover different segments")
    b = b.set_index("segment_id").loc[a["segment_id"]].reset_index()
    ids, W = unstratified_weights(a["contract_id"])
    col = {cid: i for i, cid in enumerate(ids)}
    seg_pos = a["contract_id"].map(col).to_numpy()
    y = indicator(a["true_labels"], label_order)
    idx, ones = list(range(len(label_order))), np.ones((1, len(ids)))
    out = {"contracts": len(ids), "segments": len(a)}
    for metric in ("micro_f1", "macro_f1"):
        point, samples = [], []
        for frame in (a, b):
            counts = per_contract_counts(y, _predicted(frame, label_order), seg_pos, len(ids),
                                         parse_failure=frame["parse_failure"].to_numpy())
            point.append(float(f1_metrics(counts, ones, idx)[metric][0]))
            samples.append(f1_metrics(counts, W, idx)[metric])
        out[metric] = {"a": point[0], "b": point[1],
                       **paired_difference(samples[0], samples[1], point[0], point[1])}
    out["a_better"] = bool(out["micro_f1"]["ci_low"] > 0)
    return out


def llm_thresholds(val: pd.DataFrame, label_order: list[str]) -> tuple[dict[str, float], list[str]]:
    """Rule B exactly as for the baseline: per-class thresholds for labels with at least 10
    validation contracts, one pooled threshold for the rest, all tuned on full validation.
    Unlisted labels and parse failures carry score 0."""
    spans = pd.read_parquet(config.PROCESSED_DIR / "spans.parquet")
    splits = pd.read_parquet(config.PROCESSED_DIR / "splits.parquet")
    pooled = pooled_labels(spans, splits, label_order)
    y = indicator(val["true_labels"], label_order)
    proba = np.vstack(val["proba"].to_numpy())
    return tune_thresholds(y, proba, label_order, pooled), pooled
