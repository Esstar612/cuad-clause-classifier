"""Diagnostic: does each saved encoder reproduce its training loss on train segments? Train data only."""
import json

import numpy as np
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from src import config
from src.transformer import indicator, load_data, predict_proba

segments, _, _, label_order = load_data()
sample = segments[segments["split"] == "train"].sample(n=2_000, random_state=config.SEED)
Y = indicator(sample["labels"], label_order)
p = Y.mean(0).clip(1e-7, 1 - 1e-7)
print(f"prior-only BCE on this sample: {-(Y * np.log(p) + (1 - Y) * np.log(1 - p)).mean():.5f}")
for key in config.TRANSFORMER_ENCODERS:
    d = config.TRANSFORMER_DIR / key
    tok = AutoTokenizer.from_pretrained(d)
    model = AutoModelForSequenceClassification.from_pretrained(d).float()
    proba = predict_proba(model, tok, sample["text"])[0].clip(1e-7, 1 - 1e-7)
    bce = -(Y * np.log(proba) + (1 - Y) * np.log(1 - proba)).mean()
    last = json.loads((d / "trained.json").read_text())["epoch_mean_loss"][-1]["mean_loss"]
    tp = ((proba >= 0.5) & (Y == 1)).sum()
    print(f"{key}: eval-mode BCE {bce:.5f} (epoch 3 training mean {last:.5f}); "
          f"positives {int(Y.sum())}, predicted at 0.5 {int((proba >= 0.5).sum())}, true positives {int(tp)}")
