"""Tuned legal-BERT successor (Step 6c, post-hoc; designed after the 6a validation, diagnostic and test results).

  python -m src.transformer_tuned train --run KEY     one grid run on train; a checkpoint per epoch
  python -m src.transformer_tuned validate            every candidate of every completed run: validation, Rule B
  python -m src.transformer_tuned select              pre-registered rule (macro-AP, tie, macro-F1, simpler)
  python -m src.transformer_tuned heldout             selected candidate only, test and shift, once
  python -m src.transformer_tuned fresh               selected candidate only, the Step 9 fresh set, once

No validation output of any candidate exists until every run has finished or failed (validate refuses before).
A failed run contributes no candidates.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time

import numpy as np
import pandas as pd
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from src import config
from src import transformer as T
from src.predictions import read_label_order


def recipe(run: str) -> dict:
    return {**T.recipe(), "TRANSFORMER_EPOCHS": config.TUNED_EPOCHS, "TRANSFORMER_LR": config.TUNED_RUNS[run]["lr"],
            "TUNED_ENCODER": config.TUNED_ENCODER, "run": run, "pos_weight": config.TUNED_RUNS[run]["pos_weight"]}


def check_recipe(stored: dict, run: str) -> None:
    if stored["recipe"] != recipe(run) or stored["seed"] != config.SEED:
        raise SystemExit(f"{run}: current settings {recipe(run)}, seed {config.SEED} differ from the trained "
                         f"recipe {stored['recipe']}, seed {stored['seed']}")


def positive_weights(Y: np.ndarray, label_order: list[str]) -> np.ndarray:
    """sqrt(negatives / positives) per label, from train labels."""
    pos = Y.sum(axis=0)
    if (pos == 0).any():
        raise SystemExit(f"Refusing: no train positives for {[lab for lab, p in zip(label_order, pos) if p == 0]}")
    return np.sqrt((len(Y) - pos) / pos)


def completed_runs() -> list[str]:
    status = {r: ((config.TUNED_DIR / r / "trained.json").exists(), (config.TUNED_DIR / r / "failed.json").exists())
              for r in config.TUNED_RUNS}
    pending = [r for r, (t, f) in status.items() if not (t or f)]
    if pending:
        raise SystemExit(f"Refusing: runs neither trained nor failed: {pending}")
    done = [r for r, (t, _) in status.items() if t]
    if not done:
        raise SystemExit("Refusing: every run failed; no candidates")
    return done


def candidates(runs: list[str]) -> list[str]:
    return [f"{r}/epoch-{e}" for r in runs for e in range(1, config.TUNED_EPOCHS + 1)]


def _candidate_predictions(key: str):
    return config.TUNED_CANDIDATE_PREDICTIONS_DIR / f"{key.replace('/', '_')}_val.parquet"


def train(run: str, restart: bool) -> None:
    d = config.TUNED_DIR / run
    src = T.sources()[config.TUNED_ENCODER]
    if (d / "trained.json").exists():
        raise SystemExit(f"Refusing: {run} is already trained; one run per configuration")
    if (d / "failed.json").exists():
        raise SystemExit(f"Refusing: {run} failed ({(d / 'failed.json').read_text().strip()}); "
                         "a failed run contributes no candidates and is never retried")
    if (d / "train_started.json").exists() and not restart:
        raise SystemExit(f"Refusing: an earlier {run} run started and did not finish. No validation output exists "
                         "yet, so --restart-after-crash reruns it from scratch; log it.")
    if restart:
        for p in d.glob("epoch-*"):
            shutil.rmtree(p)
    segments, _, _, label_order = T.load_data()
    tr = segments[segments["split"] == "train"].reset_index(drop=True)
    Y = T.indicator(tr["labels"], label_order)
    pw = positive_weights(Y, label_order) if config.TUNED_RUNS[run]["pos_weight"] else None
    d.mkdir(parents=True, exist_ok=True)
    (d / "train_started.json").write_text(json.dumps({"started_utc": T._now(), "restart": restart}))
    tok, model = T.load_encoder(config.TUNED_ENCODER, len(label_order))
    print(f"Training {run} ({config.TUNED_ENCODER}) on {len(tr)} train segments, device {T.device()}, "
          f"recipe {recipe(run)}", flush=True)
    if pw is not None:
        print(f"Positive weights sqrt(neg/pos): min {pw.min():.2f}, median {np.median(pw):.2f}, "
              f"max {pw.max():.2f}", flush=True)

    def save(epoch, m):
        m.save_pretrained(d / f"epoch-{epoch}", safe_serialization=True)
        tok.save_pretrained(d / f"epoch-{epoch}")

    t0 = time.perf_counter()
    try:
        log = T.train_model(model, tok, tr["text"], Y, config.TUNED_EPOCHS,
                            lr=config.TUNED_RUNS[run]["lr"], pos_weight=pw, on_epoch_end=save)
    except T.FailedRun as e:
        (d / "failed.json").write_text(json.dumps({**e.args[0], "failed_utc": T._now()}))
        raise SystemExit(f"{run}: non-finite loss {e.args[0]}; failed run recorded, it contributes no candidates")
    hours = (time.perf_counter() - t0) / 3600
    pd.DataFrame(log).to_csv(d / "train_log.csv", index=False)
    (d / "trained.json").write_text(json.dumps({
        "encoder": config.TUNED_ENCODER, "source": src, "seed": config.SEED, "device": str(T.device()),
        "recipe": recipe(run), "pos_weight": None if pw is None else pw.tolist(),
        "parameters": sum(p.numel() for p in model.parameters()),
        "encoder_parameters": T.encoder_parameters(model), "dtype": T._dtype(model),
        "train_segments": len(tr), "train_hours": hours,
        "mps_watermark_ratios": {k: os.environ.get(f"PYTORCH_MPS_{k.upper()}_WATERMARK_RATIO")
                                 for k in ("high", "low")},
        "epoch_mean_loss": log, "completed_utc": T._now()}, indent=2))
    print(f"\n{run}: trained in {hours:.2f} h (checkpoint saves included); per-epoch mean loss:")
    for row in log:
        print(f"  epoch {row['epoch']}: {row['mean_loss']:.5f}")
    print(f"Wrote epoch-1..{config.TUNED_EPOCHS} checkpoints and {d / 'trained.json'} (no validation output)")


def validate() -> None:
    """Runs only when every run has finished or failed; a failed run contributes no candidates."""
    runs = completed_runs()
    source = T.sources()[config.TUNED_ENCODER]
    for r in runs:
        trained = json.loads((config.TUNED_DIR / r / "trained.json").read_text())
        check_recipe(trained, r)
        if trained["source"] != source:
            raise SystemExit(f"{r}: trained from {trained['source']}, current pinned source {source}")
    segments, spans, splits, label_order = T.load_data()
    pooled = T.pooled_labels(spans, splits, label_order)
    supported = [lab for lab in label_order if lab not in pooled]
    val = segments[segments["split"] == "val"].reset_index(drop=True)
    y_val = T.indicator(val["labels"], label_order)
    for key in candidates(runs):
        d = config.TUNED_DIR / key
        if (d / "run.json").exists():
            print(f"{key}: already validated; files are frozen")
            continue
        run, epoch = key.split("/epoch-")
        tok = AutoTokenizer.from_pretrained(d)
        model = AutoModelForSequenceClassification.from_pretrained(d).float()
        proba, n_trunc, batch_ms = T.predict_proba(model, tok, val["text"])
        thresholds = T.tune_thresholds(y_val, proba, label_order, pooled)
        pred = T.apply_thresholds(proba, label_order, thresholds)
        (d / "thresholds.json").write_text(json.dumps(thresholds, indent=2, sort_keys=True))
        (d / "labels.json").write_text(json.dumps({"label_order": label_order, "pooled": pooled}, indent=2))
        version = T.model_version(key, config.TUNED_DIR)
        s_all = T.summary(y_val, pred, proba, label_order)
        s_sup = T.summary(y_val, pred, proba, label_order, labels=supported)
        T.write_predictions(T.to_prediction_frame(val, proba, pred, label_order,
                                                  f"{config.TUNED_MODEL_NAME}:{key}", version, batch_ms, 0.0),
                            _candidate_predictions(key), label_order, {"latency_ms": T.BATCH_NOTE})
        (d / "run.json").write_text(json.dumps({  # written last: marks this candidate validated
            "run": run, "epoch": int(epoch), "model_version": version,
            "recipe": recipe(run), "seed": config.SEED,
            "validation_all33": s_all, "validation_supported28": s_sup,
            "validation_truncated_segments": n_trunc,
            "validation_note": "thresholds tuned on this same validation set, so F1 is optimistic",
            "batch_amortized_ms_per_segment": batch_ms, "validated_utc": T._now()}, indent=2))
        print(f"{key:22s} macro-AP {s_all['macro_ap']:.4f}  macro-F1 {s_all['macro_f1']:.4f}  "
              f"micro-F1 {s_all['micro_f1']:.4f}", flush=True)
    print("\n=== Validation, 33 labels, per candidate (descriptive, one seed; F1 at Rule B thresholds tuned here) ===")
    print(_rows({k: json.loads((config.TUNED_DIR / k / "run.json").read_text())
                 for k in candidates(runs)}).round(4).to_string(index=False))


def _rows(stored: dict) -> pd.DataFrame:
    return pd.DataFrame([{"candidate": k, "run": r["run"], "epoch": r["epoch"],
                          "pos_weight": config.TUNED_RUNS[r["run"]]["pos_weight"],
                          "lr": config.TUNED_RUNS[r["run"]]["lr"],
                          **{m: r["validation_all33"][m] for m in ("macro_ap", "macro_f1", "micro_f1")}}
                         for k, r in stored.items()])


def choose(rows: pd.DataFrame) -> str:
    """Best validation macro-AP; within TUNED_SELECTION_TIE of it, higher macro-F1, then simpler
    (fewer epochs, unweighted, lower learning rate)."""
    near = rows[rows["macro_ap"] >= rows["macro_ap"].max() - config.TUNED_SELECTION_TIE]
    ranked = near.sort_values(["macro_f1", "epoch", "pos_weight", "lr"],
                              ascending=[False, True, True, True], kind="mergesort")
    return ranked["candidate"].iloc[0]


def select() -> None:
    runs = completed_runs()
    missing = [k for k in candidates(runs) if not (config.TUNED_DIR / k / "run.json").exists()]
    if missing:
        raise SystemExit(f"Refusing: candidates not validated: {missing}")
    stored = {k: json.loads((config.TUNED_DIR / k / "run.json").read_text()) for k in candidates(runs)}
    for k, r in stored.items():
        if T.model_version(k, config.TUNED_DIR) != r["model_version"]:
            raise SystemExit(f"{k}: artifacts changed since validation")
        check_recipe(r, r["run"])
    labels = {k: json.loads((config.TUNED_DIR / k / "labels.json").read_text()) for k in stored}
    if len({json.dumps(v, sort_keys=True) for v in labels.values()}) != 1:
        raise SystemExit("candidates disagree on label order or pooled labels")
    label_order = next(iter(labels.values()))["label_order"]
    rows = _rows(stored)
    winner = choose(rows)
    near = rows[rows["macro_ap"] >= rows["macro_ap"].max() - config.TUNED_SELECTION_TIE]

    segments, *_ = T.load_data()
    val = segments[segments["split"] == "val"].reset_index(drop=True)
    y_val = T.indicator(val["labels"], label_order)
    for k in stored:  # every candidate, so no metric in the table comes from stale data
        path = _candidate_predictions(k)
        df = pd.read_parquet(path)
        if (read_label_order(path) != label_order or list(df["segment_id"]) != list(val["segment_id"])
                or not np.array_equal(T.indicator(df["true_labels"], label_order), y_val)):
            raise SystemExit(f"{k}: validation predictions do not match the validation segments and labels")
        if (set(df["model_name"]) != {f"{config.TUNED_MODEL_NAME}:{k}"}
                or set(df["model_version"]) != {stored[k]["model_version"]}):
            raise SystemExit(f"{k}: validation predictions are not from the validated candidate")
    df = pd.read_parquet(_candidate_predictions(winner))
    T.write_predictions(df.assign(model_name=config.TUNED_MODEL_NAME),
                        config.PREDICTIONS_DIR / f"{config.TUNED_MODEL_NAME}_val.parquet", label_order,
                        {"latency_ms": T.BATCH_NOTE})

    d = config.TUNED_DIR / winner
    tok = AutoTokenizer.from_pretrained(d)
    model = AutoModelForSequenceClassification.from_pretrained(d).float()
    T.predict_proba(model, tok, val["text"].iloc[:config.TRANSFORMER_INFER_BATCH])  # warm-up
    single = T.single_segment_latency(lambda t: T.predict_proba(model, tok, t, warm=False)[0], val,
                                      f"local {T.device().type}")
    failed = [r for r in config.TUNED_RUNS if r not in runs]
    selected = {"candidate": winner, "model_version": stored[winner]["model_version"],
                "rule": "validation macro-AP over 33 labels; within "
                        f"{config.TUNED_SELECTION_TIE}, higher macro-F1, then fewer epochs, unweighted, lower lr",
                "near_set": near["candidate"].tolist(), "failed_runs": failed,
                "table": rows.to_dict(orient="records"),
                "latency": {"batch_amortized_ms_per_segment": stored[winner]["batch_amortized_ms_per_segment"],
                            "single_segment": single},
                "selected_utc": T._now()}
    (config.TUNED_DIR / "selected.json").write_text(json.dumps(selected, indent=2))

    print("=== Candidates by validation macro-AP (33 labels; F1 at Rule B thresholds tuned on validation) ===")
    print(rows.sort_values("macro_ap", ascending=False).round(4).to_string(index=False))
    print(f"\nWithin {config.TUNED_SELECTION_TIE} of the best macro-AP: {near['candidate'].tolist()}")
    print(f"Failed runs (no candidates): {failed or 'none'}")
    print(f"Selected: {winner} ({selected['model_version']})")
    print(f"Single-segment latency: median {single['median_ms']:.2f} ms, p95 {single['p95_ms']:.2f} ms")
    print(f"\nWrote {config.TUNED_DIR / 'selected.json'} and "
          f"{config.PREDICTIONS_DIR / (config.TUNED_MODEL_NAME + '_val.parquet')}")


def heldout(force: bool, fresh: bool = False) -> None:
    marker = config.TUNED_DIR / ("fresh_run.json" if fresh else "heldout_run.json")
    T.refuse_rerun(marker, fresh, force)
    selected = json.loads((config.TUNED_DIR / "selected.json").read_text())
    key = selected["candidate"]
    if T.model_version(key, config.TUNED_DIR) != selected["model_version"]:
        raise SystemExit("Artifacts changed since selection")
    d = config.TUNED_DIR / key
    run = json.loads((d / "run.json").read_text())
    check_recipe(run, run["run"])
    label_order = json.loads((d / "labels.json").read_text())["label_order"]
    segments, _, _, current_order = T.load_data()
    if current_order != label_order:
        raise SystemExit("Label order differs from the saved model")
    sets = T.heldout_sets(segments, fresh)
    tok = AutoTokenizer.from_pretrained(d)
    model = AutoModelForSequenceClassification.from_pretrained(d).float()
    thresholds = json.loads((d / "thresholds.json").read_text())
    started = T._now()
    marker.write_text(json.dumps({"started_utc": started, "model_version": selected["model_version"],
                                  "forced": force}))
    for split, part in sets:
        proba, n_trunc, batch_ms = T.predict_proba(model, tok, part["text"])
        pred = T.apply_thresholds(proba, label_order, thresholds)
        T.write_predictions(T.to_prediction_frame(part, proba, pred, label_order, config.TUNED_MODEL_NAME,
                                                  selected["model_version"], batch_ms, 0.0),
                            config.PREDICTIONS_DIR / f"{config.TUNED_MODEL_NAME}_{split}.parquet", label_order,
                            {"latency_ms": T.BATCH_NOTE, "truncated_segments": n_trunc})
        s = T.summary(T.indicator(part["labels"], label_order), pred, proba, label_order)
        print(f"=== {split}: {len(part)} segments, {part['contract_id'].nunique()} contracts; "
              f"truncated {n_trunc}; {batch_ms:.3f} ms/segment ===")
        print({k: round(v, 4) if isinstance(v, float) else v for k, v in s.items()})
    marker.write_text(json.dumps({"started_utc": started, "completed_utc": T._now(),
                                  "model_version": selected["model_version"], "forced": force}))
    print(f"Run `python -m src.evaluate {'fresh' if fresh else 'model'} {config.TUNED_MODEL_NAME}` for intervals.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--run", required=True, choices=list(config.TUNED_RUNS))
    t.add_argument("--restart-after-crash", action="store_true")
    sub.add_parser("validate")
    sub.add_parser("select")
    h = sub.add_parser("heldout")
    h.add_argument("--i-know-this-reruns-test", dest="force", action="store_true")
    h = sub.add_parser("fresh")
    h.add_argument("--i-know-this-reruns-fresh", dest="force", action="store_true")
    args = parser.parse_args()
    if args.cmd == "train":
        train(args.run, args.restart_after_crash)
    elif args.cmd == "validate":
        validate()
    elif args.cmd == "select":
        select()
    else:
        heldout(args.force, fresh=args.cmd == "fresh")


if __name__ == "__main__":
    main()
