"""Overall (micro) precision and recall on test and shift, from the saved predictions. Descriptive, post-hoc.

  python -m scripts.micro_pr | tee data/processed/micro_pr.txt

Never loads or reruns a model. Uses the flags, label scopes and contract resamples of
`python -m src.evaluate model NAME`, and stops if its micro-F1 differs from data/eval/NAME.json.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src import config
from src.bootstrap import percentile_ci
from src.evaluate import build_parts, label_sets, load_predictions
from src.report import MODELS

SCOPES = {"test": ("Rule A", "all"), "shift": ("Rule C",)}


def micro(counts: dict, W: np.ndarray, label_idx) -> tuple[np.ndarray, ...]:
    TP, FP, FN = (W @ counts[k][:, label_idx] for k in ("tp", "fp", "fn"))
    keep = (TP + FN) > 0  # labels with support in the resample, as micro-F1 counts them
    tp, fp, fn = ((X * keep).sum(1) for X in (TP, FP, FN))
    precision = np.where(tp + fp > 0, tp / np.maximum(tp + fp, 1), 0.0)  # same convention as f1_metrics
    recall = np.where(tp + fn > 0, tp / np.maximum(tp + fn, 1), np.nan)
    f1 = np.where(2 * tp + fp + fn > 0, 2 * tp / np.maximum(2 * tp + fp + fn, 1), 0.0)
    return precision, recall, f1, tp, fp, fn


def _show(point: float, samples: np.ndarray) -> str:
    lo, hi, _ = percentile_ci(samples)
    return f"{point:.4f} [{lo:.4f}, {hi:.4f}]"


def main() -> None:
    contracts = pd.read_parquet(config.PROCESSED_DIR / "contracts.parquet")
    print(f"Micro precision and recall, point [95% CI], {config.BOOTSTRAP_RESAMPLES} contract-level resamples "
          "on the src.evaluate streams. Post-hoc: computed after every model's single held-out run; no claims.")
    for name in MODELS:
        evaluated = json.loads((config.EVAL_DIR / f"{name}.json").read_text())
        recorded = evaluated["scopes"]
        for split, scopes in SCOPES.items():
            loaded = load_predictions(name, split)
            versions = set(loaded[0]["model_version"])
            if versions != {evaluated["model_version"]}:
                raise SystemExit(f"{name} {split}: predictions {sorted(versions)} are not the evaluated "
                                 f"version {evaluated['model_version']!r}")
            sets = label_sets(loaded[1])
            part = dict(build_parts(loaded, contracts, split, with_ap=False))[split]
            for scope in scopes:
                p, r, f, tp, fp, fn = micro(part.counts, part.ones, sets[scope])
                want = recorded[f"{split} | {scope}"]["micro_f1"]["point"]
                if not np.isclose(f[0], want, rtol=0, atol=1e-12):
                    raise SystemExit(f"{name} {split} | {scope}: micro-F1 {f[0]!r} differs from recorded {want!r}")
                bp, br, *_ = micro(part.counts, part.W, sets[scope])
                print(f"{name:20s} {split} | {scope:6s}  precision {_show(p[0], bp)}  recall {_show(r[0], br)}  "
                      f"micro-F1 {f[0]:.4f} (matches data/eval)  tp {tp[0]:.0f} fp {fp[0]:.0f} fn {fn[0]:.0f}")


if __name__ == "__main__":
    main()
