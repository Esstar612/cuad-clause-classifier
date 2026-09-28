"""Fine-tuned transformer (Step 6a).

  python -m src.transformer fetch                     pin the encoders' hub revisions
  python -m src.transformer tokens                    token lengths on train and val (decides nothing)
  python -m src.transformer probe --encoder KEY       timing and MPS allocator pool size on train segments only
  python -m src.transformer train --encoder KEY       fixed recipe on train; weights and loss only
  python -m src.transformer validate                  all encoders: validation inference, Rule B
  python -m src.transformer select                    pre-registered rule; domain comparison
  python -m src.transformer heldout                   selected encoder only, test and shift, once

No validation output of any encoder exists until every encoder is trained (validate refuses before).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("PYTORCH_MPS_HIGH_WATERMARK_RATIO", "1.0")  # MPS raises OOM instead of swapping
os.environ.setdefault("PYTORCH_MPS_LOW_WATERMARK_RATIO", "0.8")  # must not exceed the high ratio
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

from src import config
from src.baseline import BATCH_NOTE, _now, indicator, load_data, single_segment_latency
from src.bootstrap import f1_metrics, paired_difference, per_contract_counts, resample_weights
from src.evaluate import load_predictions
from src.metrics import per_label, summary
from src.predictions import to_prediction_frame, write_predictions
from src.thresholds import apply_thresholds, pooled_labels, tune_thresholds

RUN_FILES = {"run.json", "train_log.csv", "trained.json", "train_started.json", "probe.json", "failed.json"}
ALLOW = ["*.json", "*.txt", "*.model", "*.safetensors", "pytorch_model.bin"]  # no TF, Flax or Rust weights


def device() -> torch.device:
    return torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def sources() -> dict:
    return json.loads((config.TRANSFORMER_DIR / "sources.json").read_text())


def fetch() -> None:
    from huggingface_hub import HfApi, snapshot_download
    out = {}
    for key, hub_id in config.TRANSFORMER_ENCODERS.items():
        rev = HfApi().model_info(hub_id).sha
        snapshot_download(hub_id, revision=rev, allow_patterns=ALLOW)
        out[key] = {"hub_id": hub_id, "revision": rev}
        print(f"{key:11s} {hub_id:34s} revision {rev}", flush=True)
    config.TRANSFORMER_DIR.mkdir(parents=True, exist_ok=True)
    (config.TRANSFORMER_DIR / "sources.json").write_text(json.dumps(out, indent=2))
    print(f"Wrote {config.TRANSFORMER_DIR / 'sources.json'}")


def snapshot_path(key: str) -> str:
    """The pinned local snapshot fetched earlier; never contacts the hub."""
    from huggingface_hub import snapshot_download
    src = sources()[key]
    return snapshot_download(src["hub_id"], revision=src["revision"], allow_patterns=ALLOW,
                             local_files_only=True)


def load_encoder(key: str, num_labels: int):
    path = snapshot_path(key)
    tok = AutoTokenizer.from_pretrained(path)
    torch.manual_seed(config.SEED)
    model = AutoModelForSequenceClassification.from_pretrained(
        path, num_labels=num_labels, problem_type="multi_label_classification").float()
    return tok, model


def encode(tok, texts) -> tuple[list[list[int]], int]:
    full = tok(list(texts), truncation=False)["input_ids"]
    n_truncated = sum(len(ids) > config.TRANSFORMER_MAX_TOKENS for ids in full)
    ids = tok(list(texts), truncation=True, max_length=config.TRANSFORMER_MAX_TOKENS)["input_ids"]
    return ids, n_truncated


def _batch(tok, ids, rows):
    return tok.pad({"input_ids": [ids[i] for i in rows]}, return_tensors="pt").to(device())


def encoder_parameters(model) -> int:
    """Pretrained encoder parameters, excluding the classification head."""
    return sum(p.numel() for p in model.base_model.parameters())


def _dtype(model) -> str:
    return str(next(model.parameters()).dtype)


class FailedRun(Exception):
    pass


def train_model(model, tok, texts, Y: np.ndarray, epochs: int, lr: float | None = None,
                pos_weight: np.ndarray | None = None, on_epoch_end=None) -> list[dict]:
    """Per-epoch mean loss. Raises FailedRun on a non-finite loss. Defaults give the 6a recipe."""
    ids, _ = encode(tok, texts)
    n, bs, acc = len(ids), config.TRANSFORMER_BATCH_SIZE, config.TRANSFORMER_ACCUMULATION
    micro = bs // acc
    total = epochs * math.ceil(n / bs)
    model.to(device()).train()  # before the optimizer, so it holds the device parameters
    opt = torch.optim.AdamW(model.parameters(), lr=config.TRANSFORMER_LR if lr is None else lr,
                            weight_decay=config.TRANSFORMER_WEIGHT_DECAY)
    sched = get_linear_schedule_with_warmup(opt, int(config.TRANSFORMER_WARMUP * total), total)
    loss_fn = torch.nn.BCEWithLogitsLoss(
        reduction="sum",
        pos_weight=None if pos_weight is None else torch.as_tensor(pos_weight, dtype=torch.float32, device=device()))
    gen = torch.Generator().manual_seed(config.SEED)
    log, step, t0 = [], 0, time.perf_counter()
    for epoch in range(epochs):
        perm = torch.randperm(n, generator=gen).tolist()
        epoch_loss, seen = 0.0, 0
        for start in range(0, n, bs):
            rows = perm[start:start + bs]
            step_loss = 0.0
            for m in range(0, len(rows), micro):
                part = rows[m:m + micro]
                logits = model(**_batch(tok, ids, part)).logits
                target = torch.as_tensor(Y[part], dtype=torch.float32, device=device())
                loss = loss_fn(logits, target) / (len(rows) * Y.shape[1])  # mean over the full batch
                loss.backward()
                step_loss += loss.item()
            if not math.isfinite(step_loss):
                raise FailedRun({"epoch": epoch + 1, "batch_start": start, "loss": step_loss})
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            epoch_loss += step_loss * len(rows)
            seen += len(rows)
            step += 1
            if step % 200 == 0 or step == total:
                elapsed = time.perf_counter() - t0
                print(f"  epoch {epoch + 1} step {step}/{total} mean loss {epoch_loss / seen:.5f} "
                      f"elapsed {elapsed / 60:.1f} min, remaining about {elapsed / step * (total - step) / 60:.1f} min",
                      flush=True)
        log.append({"epoch": epoch + 1, "mean_loss": epoch_loss / seen})
        if on_epoch_end is not None:
            on_epoch_end(epoch + 1, model)
    return log


@torch.no_grad()
def predict_proba(model, tok, texts, warm: bool = True) -> tuple[np.ndarray, int, float]:
    """Probabilities in input order (length-sorted batches). The timer includes tokenization,
    as the baseline's includes TF-IDF featurization. With warm, one untimed warm-up batch runs first."""
    model.to(device()).eval()
    if warm:
        model(**tok(list(texts)[:2], return_tensors="pt", padding=True, truncation=True,
                    max_length=config.TRANSFORMER_MAX_TOKENS).to(device())).logits.cpu()  # waits for MPS
    t0 = time.perf_counter()
    ids, n_truncated = encode(tok, texts)
    order = np.argsort([len(x) for x in ids], kind="stable")
    out = np.empty((len(ids), model.config.num_labels), dtype=np.float64)
    for start in range(0, len(ids), config.TRANSFORMER_INFER_BATCH):
        rows = order[start:start + config.TRANSFORMER_INFER_BATCH]
        out[rows] = torch.sigmoid(model(**_batch(tok, ids, rows)).logits).cpu().double().numpy()
    return out, n_truncated, (time.perf_counter() - t0) * 1000 / max(len(ids), 1)


def model_version(key: str, root: Path | None = None) -> str:
    """Hash of every file that determines predictions: weights, HF config, tokenizer files,
    thresholds and labels (run bookkeeping and hidden files excluded)."""
    d = (config.TRANSFORMER_DIR if root is None else root) / key
    h = hashlib.sha256()
    for p in sorted(p for p in d.iterdir()
                    if p.is_file() and p.name not in RUN_FILES and not p.name.startswith(".")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return f"{key}|{h.hexdigest()[:12]}"


def recipe() -> dict:
    return {k: getattr(config, k) for k in (
        "TRANSFORMER_MAX_TOKENS", "TRANSFORMER_EPOCHS", "TRANSFORMER_BATCH_SIZE", "TRANSFORMER_ACCUMULATION",
        "TRANSFORMER_LR", "TRANSFORMER_WEIGHT_DECAY", "TRANSFORMER_WARMUP", "TRANSFORMER_INFER_BATCH")}


def check_recipe(stored: dict, key: str) -> None:
    """Inference settings are part of the recipe; refuse when the current config or seed differs from training."""
    if stored["recipe"] != recipe() or stored["seed"] != config.SEED:
        raise SystemExit(f"{key}: current settings {recipe()}, seed {config.SEED} differ from the trained "
                         f"recipe {stored['recipe']}, seed {stored['seed']}")


def tokens() -> None:
    segments, _, _, _ = load_data()
    print(f"Token lengths per encoder, train and validation only (truncation above "
          f"{config.TRANSFORMER_MAX_TOKENS}); decides nothing. Test and shift counts are recorded by heldout.")
    for key in config.TRANSFORMER_ENCODERS:
        tok = AutoTokenizer.from_pretrained(snapshot_path(key))
        for split in ("train", "val"):
            texts = segments.loc[segments["split"] == split, "text"]
            n = np.array([len(x) for x in tok(list(texts), truncation=False)["input_ids"]])
            print(f"{key:11s} {split:6s} segments {len(n):6d}  median {np.median(n):6.0f}  "
                  f"p99 {np.percentile(n, 99):6.0f}  max {n.max():5d}  "
                  f"above {config.TRANSFORMER_MAX_TOKENS}: {int((n > config.TRANSFORMER_MAX_TOKENS).sum())}")


def probe(key: str) -> None:
    """Timing and MPS allocator pool size on train segments only; no weights kept."""
    segments, _, _, label_order = load_data()
    train = segments[segments["split"] == "train"]
    sample = train.sample(n=config.TRANSFORMER_PROBE_SEGMENTS, random_state=config.SEED)
    tok, model = load_encoder(key, len(label_order))
    lengths = pd.Series([len(x) for x in tok(list(train["text"]), truncation=False)["input_ids"]],
                        index=train.index)
    longest = train.loc[lengths.nlargest(config.TRANSFORMER_BATCH_SIZE).index]
    if device().type == "mps":
        torch.mps.empty_cache()
    t0 = time.perf_counter()
    train_model(model, tok, longest["text"], indicator(longest["labels"], label_order), epochs=1)
    worst_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    train_model(model, tok, sample["text"], indicator(sample["labels"], label_order), epochs=1)
    s_per_seg = (time.perf_counter() - t0) / len(sample)
    _, _, infer_ms = predict_proba(model, tok, sample["text"])
    pool = torch.mps.driver_allocated_memory() if device().type == "mps" else None  # allocator pool, not a true peak
    limit = torch.mps.recommended_max_memory() if device().type == "mps" else None
    result = {"encoder": key, "device": str(device()), "probe_segments": len(sample),
              "worst_batch_seconds": worst_s, "train_seconds_per_segment": s_per_seg,
              "projected_train_hours": s_per_seg * len(train) * config.TRANSFORMER_EPOCHS / 3600,
              "infer_ms_per_segment": infer_ms, "mps_allocator_pool_bytes_at_end": pool,
              "mps_recommended_max_bytes": limit,
              "parameters": sum(p.numel() for p in model.parameters()),
              "encoder_parameters": encoder_parameters(model), "dtype": _dtype(model),
              "mps_watermark_ratios": {k: os.environ.get(f"PYTORCH_MPS_{k.upper()}_WATERMARK_RATIO")
                                       for k in ("high", "low")},
              "recipe": recipe(), "created_utc": _now()}
    d = config.TRANSFORMER_DIR / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "probe.json").write_text(json.dumps(result, indent=2))
    print(f"\n=== Probe {key} (train segments only, no weights kept) ===")
    for k, v in result.items():
        if k != "recipe":
            print(f"{k:34s} {v}")
    print(f"Wrote {d / 'probe.json'}")


def train(key: str, restart: bool) -> None:
    d = config.TRANSFORMER_DIR / key
    src = sources()[key]  # read first: nothing after training can fail on it
    if (d / "trained.json").exists():
        raise SystemExit(f"Refusing: {key} is already trained; one run per encoder")
    if (d / "failed.json").exists():
        raise SystemExit(f"Refusing: {key} failed ({(d / 'failed.json').read_text().strip()}); "
                         "a failed run is decided with the user, never retried by a flag")
    if (d / "train_started.json").exists() and not restart:
        raise SystemExit(f"Refusing: an earlier {key} run started and did not finish. No validation output "
                         "exists yet, so --restart-after-crash reruns training from scratch; log it.")
    segments, _, _, label_order = load_data()
    tr = segments[segments["split"] == "train"].reset_index(drop=True)
    d.mkdir(parents=True, exist_ok=True)
    (d / "train_started.json").write_text(json.dumps({"started_utc": _now(), "restart": restart}))
    tok, model = load_encoder(key, len(label_order))
    print(f"Training {key} on {len(tr)} train segments, device {device()}, recipe {recipe()}", flush=True)
    t0 = time.perf_counter()
    try:
        log = train_model(model, tok, tr["text"], indicator(tr["labels"], label_order), config.TRANSFORMER_EPOCHS)
    except FailedRun as e:
        (d / "failed.json").write_text(json.dumps({**e.args[0], "failed_utc": _now()}))
        raise SystemExit(f"{key}: non-finite loss {e.args[0]}; failed run recorded, decide with the user")
    hours = (time.perf_counter() - t0) / 3600
    model.save_pretrained(d, safe_serialization=True)
    tok.save_pretrained(d)
    pd.DataFrame(log).to_csv(d / "train_log.csv", index=False)
    (d / "trained.json").write_text(json.dumps({
        "encoder": key, "source": src, "seed": config.SEED, "device": str(device()),
        "recipe": recipe(), "parameters": sum(p.numel() for p in model.parameters()),
        "encoder_parameters": encoder_parameters(model), "dtype": _dtype(model),
        "train_segments": len(tr), "train_hours": hours,
        "mps_watermark_ratios": {k: os.environ.get(f"PYTORCH_MPS_{k.upper()}_WATERMARK_RATIO")
                                 for k in ("high", "low")},
        "epoch_mean_loss": log, "completed_utc": _now()}, indent=2))
    print(f"\n{key}: trained in {hours:.2f} h; per-epoch mean loss:")
    for row in log:
        print(f"  epoch {row['epoch']}: {row['mean_loss']:.5f}")
    print(f"Wrote weights and {d / 'trained.json'} (no validation output)")


def validate() -> None:
    """Runs only when every encoder is trained, so no validation result exists before training ends."""
    missing = [k for k in config.TRANSFORMER_ENCODERS
               if not (config.TRANSFORMER_DIR / k / "trained.json").exists()]
    if missing:
        raise SystemExit(f"Refusing: not trained yet: {missing}")
    trained = [json.loads((config.TRANSFORMER_DIR / k / "trained.json").read_text())
               for k in config.TRANSFORMER_ENCODERS]
    if len({json.dumps((t["recipe"], t["seed"]), sort_keys=True) for t in trained}) != 1:
        raise SystemExit("Refusing: encoders were trained with different recipes or seeds")
    check_recipe(trained[0], "validate")
    segments, spans, splits, label_order = load_data()
    pooled = pooled_labels(spans, splits, label_order)
    supported = [lab for lab in label_order if lab not in pooled]
    val = segments[segments["split"] == "val"].reset_index(drop=True)
    y_val = indicator(val["labels"], label_order)
    for key in config.TRANSFORMER_ENCODERS:
        d = config.TRANSFORMER_DIR / key
        if (d / "run.json").exists():
            print(f"{key}: already validated; files are frozen")
            continue
        tok = AutoTokenizer.from_pretrained(d)
        model = AutoModelForSequenceClassification.from_pretrained(d).float()
        proba, n_trunc, batch_ms = predict_proba(model, tok, val["text"])
        thresholds = tune_thresholds(y_val, proba, label_order, pooled)
        pred = apply_thresholds(proba, label_order, thresholds)
        (d / "thresholds.json").write_text(json.dumps(thresholds, indent=2, sort_keys=True))
        (d / "labels.json").write_text(json.dumps({"label_order": label_order, "pooled": pooled}, indent=2))
        version = model_version(key)
        single = single_segment_latency(lambda t: predict_proba(model, tok, t, warm=False)[0], val,
                                        f"local {device().type}")  # model already warm from the batch run
        s_all = summary(y_val, pred, proba, label_order)
        s_sup = summary(y_val, pred, proba, label_order, labels=supported)
        write_predictions(to_prediction_frame(val, proba, pred, label_order, f"transformer-{key}", version,
                                              batch_ms, 0.0),
                          config.PREDICTIONS_DIR / f"transformer-{key}_val.parquet", label_order,
                          {"latency_ms": BATCH_NOTE})
        (d / "run.json").write_text(json.dumps({  # written last: marks this encoder validated
            **json.loads((d / "trained.json").read_text()), "model_version": version,
            "validation_all33": s_all, "validation_supported28": s_sup,
            "validation_truncated_segments": n_trunc,
            "validation_note": "thresholds tuned on this same validation set, so F1 is optimistic",
            "latency": {"batch_amortized_ms_per_segment": batch_ms, "single_segment": single},
            "validated_utc": _now()}, indent=2))
        print(f"\n=== {key} ({version}), validation, Rule B thresholds tuned here (optimistic) ===")
        print(f"All 33 labels: { {k: round(v, 4) if isinstance(v, float) else v for k, v in s_all.items()} }")
        print(f"28 per-class labels: { {k: round(v, 4) if isinstance(v, float) else v for k, v in s_sup.items()} }")
        print(f"Truncated segments: {n_trunc}; batch {batch_ms:.3f} ms/segment; single-segment median "
              f"{single['median_ms']:.2f} ms, p95 {single['p95_ms']:.2f} ms")
        table = per_label(y_val, pred, proba, label_order)
        table["threshold"] = table["label"].map(thresholds)
        print(table.sort_values("f1").round(3).to_string(index=False))


def paired_macro(keys, val, contracts, label_order, versions: dict) -> dict:
    """Validation macro- and micro-F1 resample distributions per encoder on identical resamples."""
    ids, W = resample_weights(contracts, "transformer:select")
    pos = pd.Index(ids).get_indexer(val["contract_id"])
    assert (pos >= 0).all()
    idx = list(range(len(label_order)))
    out = {}
    for k in keys:
        df, order, y_true, y_pred, _ = load_predictions(f"transformer-{k}", "val")
        if (order != label_order or list(df["segment_id"]) != list(val["segment_id"])
                or not np.array_equal(y_true, indicator(val["labels"], label_order))):
            raise SystemExit(f"{k}: validation predictions do not match the validation segments and labels")
        if set(df["model_name"]) != {f"transformer-{k}"} or set(df["model_version"]) != {versions[k]}:
            raise SystemExit(f"{k}: validation predictions are not from the validated model")
        counts = per_contract_counts(y_true, y_pred, pos, len(ids))
        pt, bs = f1_metrics(counts, np.ones((1, len(ids))), idx), f1_metrics(counts, W, idx)
        out[k] = {m: (float(pt[m][0]), bs[m]) for m in ("macro_f1", "micro_f1")}
    return out


def select() -> None:
    runs = {k: json.loads((config.TRANSFORMER_DIR / k / "run.json").read_text())
            for k in config.TRANSFORMER_ENCODERS}
    for k, r in runs.items():
        if model_version(k) != r["model_version"]:
            raise SystemExit(f"{k}: artifacts changed since validation")
        check_recipe(r, k)
    labels = {k: json.loads((config.TRANSFORMER_DIR / k / "labels.json").read_text()) for k in runs}
    if len({json.dumps(v, sort_keys=True) for v in labels.values()}) != 1:
        raise SystemExit("encoders disagree on label order or pooled labels")
    label_order = next(iter(labels.values()))["label_order"]
    segments, *_ = load_data()
    val = segments[segments["split"] == "val"].reset_index(drop=True)
    contracts = pd.read_parquet(config.PROCESSED_DIR / "contracts.parquet")
    contracts = contracts[contracts["contract_id"].isin(set(val["contract_id"]))]
    dist = paired_macro(list(runs), val, contracts, label_order, {k: r["model_version"] for k, r in runs.items()})
    best = max(runs, key=lambda k: dist[k]["macro_f1"][0])
    diffs = {k: paired_difference(dist[best]["macro_f1"][1], dist[k]["macro_f1"][1],
                                  dist[best]["macro_f1"][0], dist[k]["macro_f1"][0])
             for k in runs if k != best}
    eligible = [best] + [k for k, d in diffs.items() if d["ci_low"] <= 0 <= d["ci_high"]]
    size = {k: runs[k]["encoder_parameters"] for k in eligible}
    m_min = min(size.values())
    smallest = [k for k in eligible if (size[k] - m_min) / m_min <= config.TRANSFORMER_SIZE_TOLERANCE]
    winner = max(smallest, key=lambda k: dist[k]["micro_f1"][0])
    a, b = config.TRANSFORMER_DOMAIN_PAIR
    domain = {m: paired_difference(dist[a][m][1], dist[b][m][1], dist[a][m][0], dist[b][m][0])
              for m in ("macro_f1", "micro_f1")}
    domain["macro_ap_points"] = {k: runs[k]["validation_all33"]["macro_ap"] for k in (a, b)}
    selected = {"encoder": winner, "model_version": runs[winner]["model_version"], "best_macro_f1": best,
                "differences_from_best": diffs, "eligible": eligible, "smallest_size_group": smallest,
                "encoder_parameters": {k: r["encoder_parameters"] for k, r in runs.items()},
                "validation": {k: r["validation_all33"] for k, r in runs.items()},
                "domain_comparison": domain, "selected_utc": _now()}
    (config.TRANSFORMER_DIR / "selected.json").write_text(json.dumps(selected, indent=2))
    df = pd.read_parquet(config.PREDICTIONS_DIR / f"transformer-{winner}_val.parquet")
    write_predictions(df.assign(model_name="transformer"), config.PREDICTIONS_DIR / "transformer_val.parquet",
                      label_order, {"latency_ms": BATCH_NOTE})

    print("=== Validation, 33 labels, Rule B thresholds tuned on validation (optimistic) ===")
    for k, r in runs.items():
        v = r["validation_all33"]
        print(f"{k:11s} macro-F1 {v['macro_f1']:.4f}  micro-F1 {v['micro_f1']:.4f}  macro-AP {v['macro_ap']:.4f}  "
              f"encoder parameters {r['encoder_parameters']:,}")
    print(f"\nBest macro-F1: {best}")
    for k, d in diffs.items():
        print(f"  {best} minus {k}: {d['difference']:+.4f} [{d['ci_low']:+.4f}, {d['ci_high']:+.4f}]")
    print(f"Eligible (interval includes zero): {eligible}")
    print(f"Smallest-size group (within {config.TRANSFORMER_SIZE_TOLERANCE:.0%} of {m_min:,}): {smallest}")
    print(f"Selected: {winner} ({selected['model_version']})")
    print(f"\n=== Domain comparison, {a} minus {b} (validation; better-controlled, not causal) ===")
    for m in ("macro_f1", "micro_f1"):
        d = domain[m]
        print(f"{m}: {d['difference']:+.4f} [{d['ci_low']:+.4f}, {d['ci_high']:+.4f}]")
    print(f"macro-AP points: {domain['macro_ap_points']}")
    print(f"\nWrote {config.TRANSFORMER_DIR / 'selected.json'} and {config.PREDICTIONS_DIR / 'transformer_val.parquet'}")


def heldout(force: bool) -> None:
    marker = config.TRANSFORMER_DIR / "heldout_run.json"
    if marker.exists() and not force:
        raise SystemExit("Refusing: held-out sets already evaluated. Test is touched once per model. "
                         "Override with --i-know-this-reruns-test, and log it.")
    selected = json.loads((config.TRANSFORMER_DIR / "selected.json").read_text())
    key = selected["encoder"]
    if model_version(key) != selected["model_version"]:
        raise SystemExit("Artifacts changed since selection")
    check_recipe(json.loads((config.TRANSFORMER_DIR / key / "run.json").read_text()), key)
    d = config.TRANSFORMER_DIR / key
    label_order = json.loads((d / "labels.json").read_text())["label_order"]
    segments, _, _, current_order = load_data()
    if current_order != label_order:
        raise SystemExit("Label order differs from the saved model")
    started = _now()
    marker.write_text(json.dumps({"started_utc": started, "model_version": selected["model_version"],
                                  "forced": force}))
    tok = AutoTokenizer.from_pretrained(d)
    model = AutoModelForSequenceClassification.from_pretrained(d).float()
    thresholds = json.loads((d / "thresholds.json").read_text())
    for split in ("test", "shift"):
        part = segments[segments["split"] == split].reset_index(drop=True)
        proba, n_trunc, batch_ms = predict_proba(model, tok, part["text"])
        pred = apply_thresholds(proba, label_order, thresholds)
        write_predictions(to_prediction_frame(part, proba, pred, label_order, "transformer",
                                              selected["model_version"], batch_ms, 0.0),
                          config.PREDICTIONS_DIR / f"transformer_{split}.parquet", label_order,
                          {"latency_ms": BATCH_NOTE, "truncated_segments": n_trunc})
        y = indicator(part["labels"], label_order)
        s = summary(y, pred, proba, label_order)
        print(f"=== {split}: {len(part)} segments, {part['contract_id'].nunique()} contracts; "
              f"truncated {n_trunc}; {batch_ms:.3f} ms/segment ===")
        print({k: round(v, 4) if isinstance(v, float) else v for k, v in s.items()})
    marker.write_text(json.dumps({"started_utc": started, "completed_utc": _now(),
                                  "model_version": selected["model_version"], "forced": force}))
    print("Run `python -m src.evaluate model transformer` for intervals.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sub.add_parser("tokens")
    for name in ("probe", "train"):
        p = sub.add_parser(name)
        p.add_argument("--encoder", required=True, choices=list(config.TRANSFORMER_ENCODERS))
        if name == "train":
            p.add_argument("--restart-after-crash", action="store_true")
    sub.add_parser("validate")
    sub.add_parser("select")
    h = sub.add_parser("heldout")
    h.add_argument("--i-know-this-reruns-test", action="store_true")
    args = parser.parse_args()
    if args.cmd == "fetch":
        fetch()
    elif args.cmd == "tokens":
        tokens()
    elif args.cmd == "probe":
        probe(args.encoder)
    elif args.cmd == "train":
        train(args.encoder, args.restart_after_crash)
    elif args.cmd == "validate":
        validate()
    elif args.cmd == "select":
        select()
    else:
        heldout(args.i_know_this_reruns_test)


if __name__ == "__main__":
    main()
