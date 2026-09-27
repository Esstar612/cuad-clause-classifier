"""Model-agnostic evaluation from saved predictions (Step 4a). Never loads or reruns a model.

  python -m src.evaluate model NAME          test + shift metrics with contract-bootstrap CIs,
                                             calibration on test, error analysis on validation
  python -m src.evaluate compare NAME_A NAME_B   paired differences on identical resamples

Reads data/predictions/{NAME}_{val,test,shift}.parquet (shared format) and writes
data/eval/{NAME}.json or data/eval/compare_{A}_vs_{B}.json.
"""

from __future__ import annotations

import argparse
import json
import warnings

import numpy as np
import pandas as pd

from src import config
from src.bootstrap import (ap_metrics, f1_metrics, paired_difference, per_contract_counts,
                           percentile_ci, resample_weights)
from src.calibration import ece_from_bins, per_contract_bins, reliability_table
from src.labels import SHIFT_MEASURABLE_LABELS
from src.metrics import contracts_per_label, per_label
from src.predictions import read_label_order, read_notes

FAIL_F1 = 0.30  # same failure rule as the baseline search: F1 below this, or zero recall
SCOPE_METRICS = ("macro_f1", "micro_f1", "macro_ap", "none_fp_rate", "parse_failure_rate")
METHOD = (f"{config.BOOTSTRAP_RESAMPLES} contract-level bootstrap resamples, stratified by "
          f"contract type, percentile {int(config.CI_LEVEL * 100)}% intervals, seed {config.SEED}")
COMPARE_METRICS = ("macro_f1", "micro_f1", "none_fp_rate", "parse_failure_rate")
ADJUSTED_LEVEL = 1 - (1 - config.CI_LEVEL) / config.COMPARE_FAMILY_SIZE
COMPARE_METHOD = (f"{config.BOOTSTRAP_RESAMPLES_COMPARE} contract-level bootstrap resamples, stratified by contract "
                  f"type, percentile {config.CI_LEVEL:.0%} intervals, seed {config.SEED}; paired (identical "
                  f"resamples); primary rows also Bonferroni-adjusted over a family of {config.COMPARE_FAMILY_SIZE} "
                  f"(adjusted level {ADJUSTED_LEVEL:.3%})")


def indicator(label_lists, label_order: list[str]) -> np.ndarray:
    col = {lab: j for j, lab in enumerate(label_order)}
    y = np.zeros((len(label_lists), len(label_order)), dtype=bool)
    for i, labs in enumerate(label_lists):
        for lab in labs:
            y[i, col[lab]] = True
    return y


def load_predictions(name: str, split: str):
    path = config.PREDICTIONS_DIR / f"{name}_{split}.parquet"
    df = pd.read_parquet(path)
    label_order = read_label_order(path)
    y_true = indicator(df["true_labels"], label_order)
    y_pred = indicator([[d["label"] for d in preds] for preds in df["pred_labels"]], label_order)
    proba = np.vstack(df["proba"].to_numpy())
    if "parse_failure" not in df.columns:  # files written before Step 3 (baseline)
        df = df.assign(parse_failure=False)
    return df, label_order, y_true, y_pred, proba


def sparse_scores(name: str, split: str) -> bool:
    """True when the model lists only plausible labels (unlisted score 0): AP is a lower bound."""
    notes = read_notes(config.PREDICTIONS_DIR / f"{name}_{split}.parquet")
    return str(notes.get("scores", "")).startswith("sparse")


def _ci(point, samples) -> dict:
    lo, hi, n = percentile_ci(samples)
    return {"point": float(point), "ci_low": lo, "ci_high": hi, "n_resamples": n}


def _show(d: dict) -> str:
    return f"{d['point']:.4f} [{d['ci_low']:.4f}, {d['ci_high']:.4f}]"


class Part:
    """One evaluated set of contracts with fixed resamples; `key` names the random stream."""

    def __init__(self, key: str, df: pd.DataFrame, y_true, y_pred, proba, contracts: pd.DataFrame,
                 n_resamples: int = config.BOOTSTRAP_RESAMPLES, with_ap: bool = True):
        self.key = key
        sub = contracts[contracts["contract_id"].isin(set(df["contract_id"]))]
        ids, self.W = resample_weights(sub, stream=key, n_resamples=n_resamples)
        col = {cid: i for i, cid in enumerate(ids)}
        self.seg_pos = df["contract_id"].map(col).to_numpy()
        self.ones = np.ones((1, len(ids)))
        self.y_true, self.y_pred, self.proba = y_true, y_pred, proba
        self.n_contracts, self.n_segments = len(ids), len(df)
        self.counts = per_contract_counts(y_true, y_pred, self.seg_pos, self.n_contracts,
                                          parse_failure=df["parse_failure"].to_numpy())
        self.ap_point = self.ap_samples = None
        if with_ap:
            all_idx = list(range(y_true.shape[1]))
            print(f"  bootstrapping AP for '{key}' ({self.n_contracts} contracts, "
                  f"{self.n_segments} segments)...", flush=True)
            self.ap_point = ap_metrics(y_true, proba, self.seg_pos, self.ones, all_idx)[0]
            self.ap_samples = ap_metrics(y_true, proba, self.seg_pos, self.W, all_idx)

    def scope(self, label_idx) -> tuple[dict, dict]:
        """(summary with CIs, raw resample arrays) for macro/micro F1, none FP and parse-failure
        rates, and macro-AP when AP was bootstrapped."""
        pt = f1_metrics(self.counts, self.ones, label_idx)
        bs = f1_metrics(self.counts, self.W, label_idx)
        f1_keys = ("macro_f1", "micro_f1", "none_fp_rate", "parse_failure_rate")
        points = {m: pt[m][0] for m in f1_keys}
        samples = {m: bs[m] for m in f1_keys}
        if self.ap_point is not None:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN rows give NaN, as intended
                points["macro_ap"] = np.nanmean(self.ap_point[label_idx])
                samples["macro_ap"] = np.nanmean(self.ap_samples[:, label_idx], axis=1)
        out = {"n_labels": int((~np.isnan(pt["per_f1"][0])).sum()),
               "contracts": self.n_contracts, "segments": self.n_segments}
        out.update({m: _ci(points[m], samples[m]) for m in SCOPE_METRICS if m in points})
        return out, samples

    def per_label(self, label_idx, label_order: list[str]) -> list[dict]:
        if self.ap_point is None:
            raise ValueError("per_label reports AP; build the Part with with_ap=True")
        pt = f1_metrics(self.counts, self.ones, label_idx)
        bs = f1_metrics(self.counts, self.W, label_idx)
        has_label = (self.counts["tp"] + self.counts["fn"]) > 0
        rows = []
        for k, j in enumerate(label_idx):
            rows.append({"label": label_order[j], "contracts": int(has_label[:, j].sum()),
                         "segments": int(self.y_true[:, j].sum()),
                         "precision": float(pt["per_precision"][0, k]),
                         "recall": float(pt["per_recall"][0, k]),
                         "f1": _ci(pt["per_f1"][0, k], bs["per_f1"][:, k]),
                         "ap": _ci(self.ap_point[j], self.ap_samples[:, j])})
        return rows


def label_sets(label_order: list[str]) -> dict[str, list[int]]:
    spans = pd.read_parquet(config.PROCESSED_DIR / "spans.parquet")
    splits = pd.read_parquet(config.PROCESSED_DIR / "splits.parquet")
    test_contracts = contracts_per_label(spans, splits, "test")
    idx = {lab: j for j, lab in enumerate(label_order)}
    rule_a = [lab for lab in label_order
              if test_contracts.get(lab, 0) >= config.PER_LABEL_MIN_TEST_CONTRACTS]
    return {"Rule A": [idx[lab] for lab in rule_a],
            "Rule C": [idx[lab] for lab in sorted(SHIFT_MEASURABLE_LABELS)],
            "all": list(range(len(label_order)))}


def build_parts(loaded, contracts: pd.DataFrame, split: str, n_resamples: int = config.BOOTSTRAP_RESAMPLES,
                with_ap: bool = True) -> list[tuple[str, Part]]:
    df, _, y_true, y_pred, proba = loaded
    parts = [(split, Part(split, df, y_true, y_pred, proba, contracts, n_resamples, with_ap))]
    if split == "shift":
        types = df["contract_id"].map(contracts.set_index("contract_id")["contract_type"])
        for ctype in config.SHIFT_TYPES:
            m = (types == ctype).to_numpy()
            key = f"shift:{ctype}"
            parts.append((key, Part(key, df[m].reset_index(drop=True), y_true[m], y_pred[m],
                                    proba[m], contracts, n_resamples, with_ap)))
    return parts


def part_scopes(key: str) -> list[str]:
    return ["Rule A", "all", "Rule C"] if key == "test" else ["Rule C", "all"]


def calibration_report(part: Part, label_order: list[str], rule_a_idx) -> dict:
    bins = per_contract_bins(part.y_true, part.proba, part.seg_pos, part.n_contracts)
    tot = {k: v.sum(axis=0) for k, v in bins.items()}
    ece_point = float(ece_from_bins(tot["count"], tot["sum_p"], tot["sum_y"]))
    ece_samples = ece_from_bins(part.W @ bins["count"], part.W @ bins["sum_p"], part.W @ bins["sum_y"])
    per = []
    for j in rule_a_idx:
        b = per_contract_bins(part.y_true, part.proba, part.seg_pos, part.n_contracts, label_idx=[j])
        t = {k: v.sum(axis=0) for k, v in b.items()}
        per.append({"label": label_order[j],
                    "ece": float(ece_from_bins(t["count"], t["sum_p"], t["sum_y"])),
                    "mean_predicted": float(part.proba[:, j].mean()),
                    "observed_rate": float(part.y_true[:, j].mean())})
    return {"pooled_ece": _ci(ece_point, ece_samples), "reliability": reliability_table(bins),
            "per_label_rule_a": per}


def error_analysis(name: str) -> dict:
    """Validation only: test errors must not inform Step 3 prompt design."""
    df, label_order, y_true, y_pred, proba = load_predictions(name, "val")
    text = (pd.read_parquet(config.PROCESSED_DIR / "segments.parquet", columns=["segment_id", "text"])
            .set_index("segment_id")["text"])
    false_pos = y_pred & ~y_true
    pairs = y_true.T.astype(np.int64) @ false_pos.astype(np.int64)
    top = sorted(((int(pairs[a, b]), label_order[a], label_order[b])
                  for a, b in zip(*np.nonzero(pairs))), key=lambda t: (-t[0], t[1], t[2]))[:15]
    no_prediction = ~y_pred.any(axis=1)
    missed = [{"label": lab, "false_negatives": int((y_true[:, j] & ~y_pred[:, j]).sum()),
               "segment_predicted_none": int((y_true[:, j] & no_prediction).sum())}
              for j, lab in enumerate(label_order)]
    table = per_label(y_true, y_pred, proba, label_order)
    failing = table.loc[(table["f1"] < FAIL_F1) | (table["recall"] == 0), "label"].tolist()
    rng = np.random.default_rng(config.SEED)
    samples = []
    for lab in failing:
        j = label_order.index(lab)
        for kind, mask in (("false_negative", y_true[:, j] & ~y_pred[:, j]),
                           ("false_positive", false_pos[:, j])):
            idx = np.flatnonzero(mask)
            pick = np.sort(rng.choice(idx, size=min(config.ERROR_SAMPLES_PER_LABEL, len(idx)),
                                      replace=False)) if len(idx) else []
            for i in pick:
                sid = df["segment_id"].iloc[i]
                samples.append({"label": lab, "kind": kind, "segment_id": sid,
                                "p": float(proba[i, j]),
                                "true": list(df["true_labels"].iloc[i]),
                                "predicted": [d["label"] for d in df["pred_labels"].iloc[i]],
                                "text": text[sid]})
    return {"split": "val", "confused_pairs": [{"true": a, "predicted": b, "segments": n}
                                               for n, a, b in top],
            "missed": missed, "failing_labels": failing, "samples": samples}


def _dump(obj, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def evaluate_model(name: str) -> None:
    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 200)
    contracts = pd.read_parquet(config.PROCESSED_DIR / "contracts.parquet")
    test_loaded = load_predictions(name, "test")
    shift_loaded = load_predictions(name, "shift")
    label_order = test_loaded[1]
    if shift_loaded[1] != label_order:
        raise SystemExit("test and shift files have different label orders")
    versions = set(test_loaded[0]["model_version"]) | set(shift_loaded[0]["model_version"])
    if len(versions) != 1:
        raise SystemExit(f"test and shift files must share one model version: {sorted(versions)}")
    sets = label_sets(label_order)
    print(f"Model: {name}   version: {test_loaded[0]['model_version'].iloc[0]}\nMethod: {METHOD}")

    sparse = sparse_scores(name, "test")
    result = {"model": name, "model_version": test_loaded[0]["model_version"].iloc[0],
              "method": METHOD, "sparse_scores": sparse, "scopes": {}}
    if sparse:
        print("Scores are sparse (unlisted labels score 0): macro_ap is a lower bound, "
              "not comparable to dense-score models (pre-registered 2026-09-24).")
    rule_c_samples = {}
    parts = build_parts(test_loaded, contracts, "test") + build_parts(shift_loaded, contracts, "shift")
    test_part = parts[0][1]
    for key, part in parts:
        for scope in part_scopes(key):
            summary, samples = part.scope(sets[scope])
            result["scopes"][f"{key} | {scope}"] = summary
            if scope == "Rule C" and key in ("test", "shift"):
                rule_c_samples[key] = (summary, samples)
    result["per_label_test"] = test_part.per_label(sets["all"], label_order)
    rule_a_names = {label_order[j] for j in sets["Rule A"]}
    for row in result["per_label_test"]:
        row["main_table"] = row["label"] in rule_a_names
    result["per_label_shift_rule_c"] = parts[1][1].per_label(sets["Rule C"], label_order)

    (t_sum, t_s), (s_sum, s_s) = rule_c_samples["test"], rule_c_samples["shift"]
    result["test_minus_shift_rule_c"] = {
        m: {"difference": t_sum[m]["point"] - s_sum[m]["point"],
            **dict(zip(("ci_low", "ci_high", "n_resamples"), percentile_ci(t_s[m] - s_s[m])))}
        for m in SCOPE_METRICS}
    result["calibration_test"] = calibration_report(test_part, label_order, sets["Rule A"])
    result["error_analysis_val"] = error_analysis(name)
    _dump(result, config.EVAL_DIR / f"{name}.json")

    print("\n=== Scopes: point [95% CI]  (none_fp_rate on parsed segments only; "
          "parse failures count as empty predictions for F1) ===")
    for scope, s in result["scopes"].items():
        print(f"{scope:32s} labels={s['n_labels']:2d} contracts={s['contracts']:3d}  "
              + "  ".join(f"{m}={_show(s[m])}" for m in SCOPE_METRICS))
    print("\n=== Test minus shift, Rule C labels (independent bootstraps) ===")
    for m, d in result["test_minus_shift_rule_c"].items():
        print(f"{m:14s} {d['difference']:+.4f} [{d['ci_low']:+.4f}, {d['ci_high']:+.4f}]")
    for title, rows in (("Per-label test (all 33; main_table=False: insufficient support, not interpreted)",
                         result["per_label_test"]),
                        ("Per-label shift, Rule C labels, combined", result["per_label_shift_rule_c"])):
        print(f"\n=== {title} ===")
        flat = pd.DataFrame([{**{k: v for k, v in r.items() if k not in ("f1", "ap")},
                              "f1": r["f1"]["point"], "f1_lo": r["f1"]["ci_low"], "f1_hi": r["f1"]["ci_high"],
                              "ap": r["ap"]["point"], "ap_lo": r["ap"]["ci_low"], "ap_hi": r["ap"]["ci_high"],
                              "f1_n": r["f1"]["n_resamples"]} for r in rows])
        print(flat.sort_values("f1").round(3).to_string(index=False))

    cal = result["calibration_test"]
    print(f"\n=== Calibration on test (all segment-label pairs pooled) ===\nPooled ECE: {_show(cal['pooled_ece'])}")
    print(pd.DataFrame(cal["reliability"]).round(4).to_string(index=False))
    print("\nPer-label, Rule A labels (mean predicted vs observed positive rate):")
    print(pd.DataFrame(cal["per_label_rule_a"]).sort_values("ece", ascending=False).round(4).to_string(index=False))

    err = result["error_analysis_val"]
    print("\n=== Error analysis on VALIDATION (not test) ===")
    print("Top confused pairs (segments truly labeled A that were also predicted B, B wrong):")
    print(pd.DataFrame(err["confused_pairs"]).to_string(index=False))
    print(f"\nFailing labels on validation: {err['failing_labels']}")
    for s in err["samples"]:
        snippet = " ".join(s["text"].split())[:400]
        print(f"\n[{s['label']} | {s['kind']} | {s['segment_id']} | p={s['p']:.3f}]"
              f"\ntrue={s['true']}\npredicted={s['predicted']}\n{snippet}")
    print(f"\nWrote {config.EVAL_DIR / f'{name}.json'}")


def paired_row(key: str, scope: str, metric: str, a_samples, b_samples, a_point: float, b_point: float,
               in_family: bool = True) -> dict:
    d = paired_difference(a_samples, b_samples, a_point, b_point)
    if in_family and (key, scope) in config.COMPARE_PRIMARY_SCOPES and metric in config.COMPARE_PRIMARY_METRICS:
        adj = paired_difference(a_samples, b_samples, a_point, b_point, level=ADJUSTED_LEVEL)
        d.update(primary=True, adjusted_level=ADJUSTED_LEVEL, adjusted_ci_low=adj["ci_low"],
                 adjusted_ci_high=adj["ci_high"],
                 claim="A higher" if adj["ci_low"] > 0 else "B higher" if adj["ci_high"] < 0 else "none")
    return d


def scope_verdict(claims: dict[str, str], name_a: str, name_b: str) -> str:
    named = {m: c.replace("A higher", f"{name_a} higher").replace("B higher", f"{name_b} higher")
             for m, c in claims.items()}
    both = set(named.values())
    if len(both) == 1 and both != {"none"}:
        return f"{both.pop()} on both co-primary metrics"
    return "per metric: " + ", ".join(f"{m} {c}" for m, c in named.items())


def compare(name_a: str, name_b: str) -> None:
    contracts = pd.read_parquet(config.PROCESSED_DIR / "contracts.parquet")
    print(f"Paired comparison: {name_a} minus {name_b}\nMethod: {COMPARE_METHOD}")
    in_family = (name_a, name_b) in config.COMPARE_PAIRS or name_a == name_b
    out, all_zero = {}, True
    seen = {f"{side}_{col}": set() for side in "ab" for col in ("name", "version")}
    for split in ("test", "shift"):
        a = load_predictions(name_a, split)
        b = load_predictions(name_b, split)
        if a[1] != b[1]:
            raise SystemExit(f"{split}: label orders differ")
        if not ((a[0]["split"] == split).all() and (b[0]["split"] == split).all()):
            raise SystemExit(f"{split}: a file holds rows from another split")
        if not (a[0]["segment_id"].is_unique and b[0]["segment_id"].is_unique):
            raise SystemExit(f"{split}: duplicate segment ids")
        if set(a[0]["segment_id"]) != set(b[0]["segment_id"]):
            raise SystemExit(f"{split}: the two files cover different segments")
        for side, f in (("a", a[0]), ("b", b[0])):
            for col in ("name", "version"):
                seen[f"{side}_{col}"] |= set(f[f"model_{col}"])
        order = b[0].reset_index(drop=True).set_index("segment_id").index.get_indexer(a[0]["segment_id"])
        b = (b[0].iloc[order].reset_index(drop=True), b[1], b[2][order], b[3][order], b[4][order])
        for col in ("contract_id", "start", "end"):
            if not np.array_equal(a[0][col].to_numpy(), b[0][col].to_numpy()):
                raise SystemExit(f"{split}: the two files disagree on {col}")
        if not np.array_equal(a[2], b[2]):
            raise SystemExit(f"{split}: the two files disagree on the true labels")
        sets = label_sets(a[1])
        n = config.BOOTSTRAP_RESAMPLES_COMPARE
        for (key, pa), (_, pb) in zip(build_parts(a, contracts, split, n, with_ap=False),
                                      build_parts(b, contracts, split, n, with_ap=False)):
            if not np.array_equal(pa.W, pb.W):
                raise SystemExit(f"{key}: resamples differ; comparison would not be paired")
            for scope in part_scopes(key):
                sa, samp_a = pa.scope(sets[scope])
                sb, samp_b = pb.scope(sets[scope])
                for m in COMPARE_METRICS:
                    d = paired_row(key, scope, m, samp_a[m], samp_b[m], sa[m]["point"], sb[m]["point"], in_family)
                    out[f"{key} | {scope} | {m}"] = d
                    all_zero &= all(d.get(k, 0) == 0 for k in ("difference", "ci_low", "ci_high",
                                                                "adjusted_ci_low", "adjusted_ci_high"))
    if any(len(v) != 1 for v in seen.values()):
        raise SystemExit(f"each model must have one name and one version across test and shift: {seen}")
    versions = {k: v.pop() for k, v in seen.items()}
    verdicts = {f"{k} | {s}": scope_verdict({m: out[f"{k} | {s} | {m}"]["claim"]
                                             for m in config.COMPARE_PRIMARY_METRICS}, name_a, name_b)
                for k, s in config.COMPARE_PRIMARY_SCOPES} if in_family else {}
    _dump({"a": name_a, "b": name_b, **versions, "method": COMPARE_METHOD, "family_size": config.COMPARE_FAMILY_SIZE,
           "differences": out, "verdicts": verdicts},
          config.EVAL_DIR / f"compare_{name_a}_vs_{name_b}.json")
    print(f"\n=== Primary comparisons (A minus B): point [95% CI] [{ADJUSTED_LEVEL:.3%} adjusted CI] claim ===")
    for k, d in out.items():
        if d.get("primary"):
            print(f"{k:40s} {d['difference']:+.4f} [{d['ci_low']:+.4f}, {d['ci_high']:+.4f}] "
                  f"[{d['adjusted_ci_low']:+.4f}, {d['adjusted_ci_high']:+.4f}] {d['claim']}")
    print("\n=== Verdicts, per scope ===")
    for k, v in verdicts.items():
        print(f"{k:20s} {v}")
    print("\n=== Secondary differences (A minus B), point [95% CI], no claims ===")
    for k, d in out.items():
        if not d.get("primary"):
            print(f"{k:40s} {d['difference']:+.4f} [{d['ci_low']:+.4f}, {d['ci_high']:+.4f}]")
    if name_a == name_b:
        print(f"\nSelf-comparison check, every difference, CI bound and adjusted bound exactly 0: {all_zero}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("model")
    m.add_argument("name")
    c = sub.add_parser("compare")
    c.add_argument("name_a")
    c.add_argument("name_b")
    args = parser.parse_args()
    if args.cmd == "model":
        evaluate_model(args.name)
    else:
        compare(args.name_a, args.name_b)


if __name__ == "__main__":
    main()
