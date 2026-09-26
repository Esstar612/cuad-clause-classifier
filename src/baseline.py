"""TF-IDF + one-vs-rest logistic regression baseline (Step 2).

  python -m src.baseline search    grid on validation, choose by macro-AP, tune Rule B thresholds, save
  python -m src.baseline heldout   one-time test and shift predictions from the frozen model
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import Pipeline

from src import config
from src.build_segments import load_segments
from src.labels import SHIFT_MEASURABLE_LABELS, label_set
from src.metrics import contracts_per_label, per_label, summary
from src.predictions import to_prediction_frame, write_predictions
from src.thresholds import apply_thresholds, pooled_labels, tune_thresholds

MODEL_NAME = "tfidf-ovr-logreg"
FAIL_F1 = 0.30  # a label clearly fails on validation below this F1, or at zero recall
REDACTION = re.compile(r"\*{3,}|_{5,}")
ARTIFACTS = {name: config.BASELINE_DIR / name for name in
             ("model.joblib", "thresholds.json", "labels.json", "config.json",
              "search_log.csv", "heldout_run.json")}
BATCH_NOTE = "batch-amortized: one predict_proba call over the split, divided by its segment count"


def preprocess(text: str) -> str:
    """Lowercase; turn redaction runs into one token the tokenizer keeps."""
    return REDACTION.sub(" redactedtoken ", text.lower())


def load_frozen_pipeline(path=None) -> Pipeline:
    import __main__

    # model.joblib was pickled under `python -m src.baseline`, so it names __main__.preprocess
    if not hasattr(__main__, "preprocess"):
        __main__.preprocess = preprocess
    return joblib.load(path or config.MODELS_DIR / "baseline" / "model.joblib")


def indicator(label_lists, label_order: list[str]) -> np.ndarray:
    col = {lab: j for j, lab in enumerate(label_order)}
    y = np.zeros((len(label_lists), len(label_order)), dtype=bool)
    for i, labs in enumerate(label_lists):
        for lab in labs:
            y[i, col[lab]] = True
    return y


def downsample_none(train: pd.DataFrame, ratio, seed: int = config.SEED) -> pd.DataFrame:
    """All positive train segments plus ratio x as many none segments, sampled with `seed`.
    ratio=None keeps every none segment. Refuses anything but train segments."""
    if set(train["split"]) != {"train"}:
        raise ValueError("downsample_none only accepts train segments")
    if ratio is None:
        return train
    is_pos = (train["labels"].map(len) > 0).to_numpy()
    none_idx = train.index[~is_pos].to_numpy()
    n_keep = min(len(none_idx), int(ratio * is_pos.sum()))
    keep = np.random.default_rng(seed).choice(none_idx, size=n_keep, replace=False)
    return train[is_pos | train.index.isin(keep)]


def make_pipeline(ngram_range, class_weight, C: float) -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(preprocessor=preprocess, ngram_range=ngram_range,
                                  min_df=2, sublinear_tf=True)),
        ("clf", OneVsRestClassifier(
            LogisticRegression(solver="liblinear", C=C, class_weight=class_weight,
                               max_iter=1000, random_state=config.SEED))),
    ])


def grid() -> list[dict]:
    return [{"ngram_range": ng, "class_weight": cw, "C": c, "none_ratio": r}
            for ng, cw, c, r in itertools.product(
                config.BASELINE_NGRAM_RANGES, config.BASELINE_CLASS_WEIGHTS,
                config.BASELINE_C_VALUES, config.BASELINE_NONE_RATIOS)]


def select(log: pd.DataFrame) -> int:
    """Best validation macro-AP; within BASELINE_SELECTION_TIE of it, higher macro-F1,
    then simpler (lower n-gram, unweighted, lower C = stronger regularization)."""
    near = log[log["macro_ap"] >= log["macro_ap"].max() - config.BASELINE_SELECTION_TIE]
    ranked = near.sort_values(["macro_f1", "ngram_max", "weighted", "C"],
                              ascending=[False, True, True, True], kind="mergesort")
    return int(ranked["config_id"].iloc[0])


def load_data():
    segments = load_segments()
    spans = pd.read_parquet(config.PROCESSED_DIR / "spans.parquet")
    splits = pd.read_parquet(config.PROCESSED_DIR / "splits.parquet")
    return segments, spans, splits, label_set(spans["category"].unique())


def fit(train_all: pd.DataFrame, cfg: dict, label_order: list[str]):
    train = downsample_none(train_all, cfg["none_ratio"])
    pipe = make_pipeline(cfg["ngram_range"], cfg["class_weight"], cfg["C"])
    pipe.fit(train["text"].tolist(), indicator(train["labels"], label_order))
    return pipe, len(train)


def timed_proba(pipe: Pipeline, texts: list[str]):
    t0 = time.perf_counter()
    proba = pipe.predict_proba(texts)
    return proba, 1000 * (time.perf_counter() - t0) / max(len(texts), 1)


def single_segment_latency(pipe: Pipeline, val: pd.DataFrame) -> dict:
    """Fair comparison with per-call LLM latency: one predict_proba call per segment."""
    rng = np.random.default_rng(config.SEED)
    idx = rng.choice(len(val), size=min(config.LATENCY_SAMPLE_SIZE, len(val)), replace=False)
    times = []
    for i in sorted(idx):
        text = [val["text"].iloc[i]]
        t0 = time.perf_counter()
        pipe.predict_proba(text)
        times.append(1000 * (time.perf_counter() - t0))
    return {"method": "single-segment: one predict_proba call per segment, model loaded, local CPU",
            "n": len(times), "median_ms": float(np.median(times)),
            "p95_ms": float(np.percentile(times, 95))}


def model_version() -> str:
    h = hashlib.sha256()
    for name in ("model.joblib", "thresholds.json"):
        h.update(ARTIFACTS[name].read_bytes())
    return h.hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fmt(d: dict) -> dict:
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in d.items()}


def search() -> None:
    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 200)
    segments, spans, splits, label_order = load_data()
    pooled = pooled_labels(spans, splits, label_order)
    supported = [lab for lab in label_order if lab not in pooled]
    train_all = segments[segments["split"] == "train"]
    val = segments[segments["split"] == "val"].reset_index(drop=True)
    y_val = indicator(val["labels"], label_order)
    print(f"Labels: {len(label_order)}   Rule B pooled ({len(pooled)}): {pooled}")
    print(f"Train segments before downsampling: {len(train_all)} "
          f"(positive {int((train_all['labels'].map(len) > 0).sum())})   "
          f"Validation segments: {len(val)}")

    configs = grid()
    rows = []
    for i, cfg in enumerate(configs):
        t0 = time.perf_counter()
        pipe, n_train = fit(train_all, cfg, label_order)
        fit_s = time.perf_counter() - t0
        proba = pipe.predict_proba(val["text"].tolist())
        thresholds = tune_thresholds(y_val, proba, label_order, pooled)
        pred = apply_thresholds(proba, label_order, thresholds)
        s_all = summary(y_val, pred, proba, label_order)
        s_sup = summary(y_val, pred, proba, label_order, labels=supported)
        rows.append({"config_id": i, "ngram_max": cfg["ngram_range"][1],
                     "weighted": cfg["class_weight"] is not None, "C": cfg["C"],
                     "none_ratio": "all" if cfg["none_ratio"] is None else cfg["none_ratio"],
                     "train_segments": n_train,
                     "vocab": len(pipe.named_steps["tfidf"].vocabulary_),
                     "macro_ap": s_all["macro_ap"], "macro_f1": s_all["macro_f1"],
                     "micro_f1": s_all["micro_f1"], "macro_f1_28": s_sup["macro_f1"],
                     "none_fp_rate": s_all["none_fp_rate"], "fit_s": round(fit_s, 1)})
        r = rows[-1]
        print(f"[{i + 1:2d}/{len(configs)}] ngram=1-{r['ngram_max']} weighted={r['weighted']!s:5} "
              f"C={r['C']:<5} none={r['none_ratio']!s:3}  macro_AP={r['macro_ap']:.4f}  "
              f"macro_F1={r['macro_f1']:.4f}  ({r['fit_s']}s)", flush=True)

    log = pd.DataFrame(rows)
    config.BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    log.to_csv(ARTIFACTS["search_log.csv"], index=False)
    print("\n=== All configurations, sorted by validation macro-AP (selection metric) ===")
    print(log.sort_values("macro_ap", ascending=False).round(4).to_string(index=False))

    chosen_id = select(log)
    cfg = configs[chosen_id]
    pipe, n_train = fit(train_all, cfg, label_order)
    proba, batch_ms = timed_proba(pipe, val["text"].tolist())
    thresholds = tune_thresholds(y_val, proba, label_order, pooled)
    pred = apply_thresholds(proba, label_order, thresholds)

    joblib.dump(pipe, ARTIFACTS["model.joblib"])
    ARTIFACTS["thresholds.json"].write_text(json.dumps(thresholds, indent=2, sort_keys=True))
    ARTIFACTS["labels.json"].write_text(
        json.dumps({"label_order": label_order, "pooled": pooled}, indent=2))
    version = model_version()
    s_all = summary(y_val, pred, proba, label_order)
    s_sup = summary(y_val, pred, proba, label_order, labels=supported)
    latency = {"batch_amortized_ms_per_segment": batch_ms, "batch_note": BATCH_NOTE,
               "single_segment": single_segment_latency(pipe, val)}
    ARTIFACTS["config.json"].write_text(json.dumps({
        "model_name": MODEL_NAME, "model_version": version, "seed": config.SEED,
        "chosen_config_id": chosen_id,
        "chosen": {"ngram_range": list(cfg["ngram_range"]), "class_weight": cfg["class_weight"],
                   "C": cfg["C"], "none_ratio": cfg["none_ratio"], "min_df": 2,
                   "sublinear_tf": True, "solver": "liblinear"},
        "train_segments": n_train,
        "selection": "validation macro-AP over 33 labels; within 0.005, higher macro-F1, then simpler",
        "validation_all33": s_all, "validation_supported28": s_sup,
        "validation_note": "thresholds tuned on this same validation set, so F1 is optimistic",
        "latency": latency, "created_utc": _now(),
    }, indent=2))
    write_predictions(
        to_prediction_frame(val, proba, pred, label_order, MODEL_NAME, version, batch_ms, 0.0),
        config.PREDICTIONS_DIR / "baseline_val.parquet", label_order, {"latency_ms": BATCH_NOTE})

    single = latency["single_segment"]
    print(f"\nChosen config_id {chosen_id}: {cfg}")
    print(f"model_version {version}   train segments used {n_train}")
    print(f"Validation, all 33 labels: {_fmt(s_all)}")
    print(f"Validation, 28 per-class labels: {_fmt(s_sup)}")
    print(f"Latency: batch-amortized {batch_ms:.4f} ms/segment; single-segment median "
          f"{single['median_ms']:.2f} ms, p95 {single['p95_ms']:.2f} ms (n={single['n']})")
    table = per_label(y_val, pred, proba, label_order)
    table["threshold"] = table["label"].map(thresholds)
    table["pooled"] = table["label"].isin(pooled)
    table["fails"] = (table["f1"] < FAIL_F1) | (table["recall"] == 0)
    print("\n=== Per-label validation (thresholds tuned on validation, so optimistic) ===")
    print(table.sort_values("f1").round(3).to_string(index=False))
    print(f"\nFailing on validation (F1 < {FAIL_F1} or zero recall): "
          f"{table.loc[table['fails'], 'label'].tolist()}")


def _report(name, y, pred, proba, label_order, labels=None) -> None:
    print(f"{name}: {_fmt(summary(y, pred, proba, label_order, labels=labels))}")


def heldout(force: bool) -> None:
    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 200)
    marker = ARTIFACTS["heldout_run.json"]
    if marker.exists() and not force:
        raise SystemExit(f"Refusing: held-out sets already evaluated ({marker.read_text().strip()}). "
                         "Test is touched once per model. Override with "
                         "--i-know-this-reruns-test, and log it.")
    saved = json.loads(ARTIFACTS["config.json"].read_text())
    version = model_version()
    if version != saved["model_version"]:
        raise SystemExit(f"Artifacts changed since search: {version} != {saved['model_version']}")
    marker.write_text(json.dumps({"started_utc": _now(), "model_version": version, "forced": force}))

    pipe = joblib.load(ARTIFACTS["model.joblib"])
    thresholds = json.loads(ARTIFACTS["thresholds.json"].read_text())
    label_order = json.loads(ARTIFACTS["labels.json"].read_text())["label_order"]
    segments, spans, splits, current_order = load_data()
    if current_order != label_order:
        raise SystemExit("Label order differs from the saved model")
    test_contracts = contracts_per_label(spans, splits, "test")
    rule_a = [lab for lab in label_order
              if test_contracts.get(lab, 0) >= config.PER_LABEL_MIN_TEST_CONTRACTS]
    rule_c = sorted(SHIFT_MEASURABLE_LABELS)

    for split in ("test", "shift"):
        part = segments[segments["split"] == split].reset_index(drop=True)
        proba, batch_ms = timed_proba(pipe, part["text"].tolist())
        pred = apply_thresholds(proba, label_order, thresholds)
        y = indicator(part["labels"], label_order)
        write_predictions(
            to_prediction_frame(part, proba, pred, label_order, MODEL_NAME, version, batch_ms, 0.0),
            config.PREDICTIONS_DIR / f"baseline_{split}.parquet", label_order,
            {"latency_ms": BATCH_NOTE})
        print(f"\n=== {split}: {len(part)} segments, {part['contract_id'].nunique()} contracts ===")
        _report("All labels (combined)", y, pred, proba, label_order)
        table = per_label(y, pred, proba, label_order)
        if split == "test":
            _report(f"Rule A labels ({len(rule_a)})", y, pred, proba, label_order, labels=rule_a)
            table["test_contracts"] = table["label"].map(test_contracts).fillna(0).astype(int)
            table["main_table"] = table["label"].isin(rule_a)
            print("All 33 labels (main_table=False: insufficient support, not interpreted):")
            print(table.sort_values(["main_table", "f1"]).round(3).to_string(index=False))
        else:
            for ctype in config.SHIFT_TYPES:
                m = (part["contract_type"] == ctype).to_numpy()
                _report(f"{ctype}, all labels", y[m], pred[m], proba[m], label_order)
                _report(f"{ctype}, Rule C labels", y[m], pred[m], proba[m], label_order, labels=rule_c)
            _report("Combined, Rule C labels", y, pred, proba, label_order, labels=rule_c)
            print("Rule C labels, combined shift:")
            print(table[table["label"].isin(rule_c)].sort_values("f1").round(3).to_string(index=False))

    marker.write_text(json.dumps({"started_utc": json.loads(marker.read_text())["started_utc"],
                                  "completed_utc": _now(), "model_version": version,
                                  "forced": force}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("search")
    held = sub.add_parser("heldout")
    held.add_argument("--i-know-this-reruns-test", dest="force", action="store_true")
    args = parser.parse_args()
    if args.cmd == "search":
        search()
    else:
        heldout(args.force)


if __name__ == "__main__":
    main()
