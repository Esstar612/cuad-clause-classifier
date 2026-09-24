"""Shared prediction format (docs/plan.md). Every model writes its predictions through here."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA = pa.schema([
    ("segment_id", pa.string()),
    ("contract_id", pa.int64()),
    ("split", pa.string()),
    ("start", pa.int64()),
    ("end", pa.int64()),
    ("true_labels", pa.list_(pa.string())),
    ("pred_labels", pa.list_(pa.struct([("label", pa.string()), ("confidence", pa.float64())]))),
    ("proba", pa.list_(pa.float64())),  # one per label, in label_order (file metadata)
    ("model_name", pa.string()),
    ("model_version", pa.string()),
    ("latency_ms", pa.float64()),
    ("cost_usd", pa.float64()),
])
REQUIRED_COLUMNS = SCHEMA.names


def to_prediction_frame(segments: pd.DataFrame, proba: np.ndarray, pred: np.ndarray,
                        label_order: list[str], model_name: str, model_version: str,
                        latency_ms, cost_usd) -> pd.DataFrame:
    """Build shared-format rows. `segments` needs segment_id, contract_id, split, start,
    end, labels. latency_ms and cost_usd may be scalars or per-segment arrays."""
    proba = np.asarray(proba, dtype=float)
    pred = np.asarray(pred, dtype=bool)
    if proba.shape != (len(segments), len(label_order)) or pred.shape != proba.shape:
        raise ValueError(f"proba/pred shape {proba.shape}/{pred.shape} does not match "
                         f"{len(segments)} segments x {len(label_order)} labels")
    n = len(segments)
    return pd.DataFrame({
        "segment_id": segments["segment_id"].to_numpy(),
        "contract_id": segments["contract_id"].to_numpy(),
        "split": segments["split"].to_numpy(),
        "start": segments["start"].to_numpy(),
        "end": segments["end"].to_numpy(),
        "true_labels": [list(labs) for labs in segments["labels"]],
        "pred_labels": [
            [{"label": lab, "confidence": float(p)}
             for lab, p, on in zip(label_order, row_p, row_on) if on]
            for row_p, row_on in zip(proba, pred)
        ],
        "proba": [row.tolist() for row in proba],
        "model_name": [model_name] * n,
        "model_version": [model_version] * n,
        "latency_ms": np.broadcast_to(np.asarray(latency_ms, dtype=float), (n,)),
        "cost_usd": np.broadcast_to(np.asarray(cost_usd, dtype=float), (n,)),
    })


def write_predictions(df: pd.DataFrame, path: Path, label_order: list[str],
                      notes: dict | None = None) -> None:
    """Write with the fixed schema; label_order and notes go in the file metadata."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"prediction frame missing columns: {missing}")
    table = pa.Table.from_pandas(df[REQUIRED_COLUMNS], schema=SCHEMA, preserve_index=False)
    meta = dict(table.schema.metadata or {})
    meta[b"label_order"] = json.dumps(label_order).encode()
    meta[b"notes"] = json.dumps(notes or {}).encode()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table.replace_schema_metadata(meta), path)


def read_label_order(path: Path) -> list[str]:
    return json.loads(pq.read_schema(path).metadata[b"label_order"])
