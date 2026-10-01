"""Reference for the service's per-document input statistic (Step 7).

  python -m src.service_reference     out-of-vocabulary rate of each validation contract

The rate uses drift's definition (Step 5): unigrams of the frozen baseline analyzer that are not in
its vocabulary. The service reports a document's rate as a percentile of these; descriptive only,
since the calibrated drift monitor works on batches of contracts.
"""

from __future__ import annotations

import json

import numpy as np

from src import config
from src.baseline import load_frozen_pipeline, model_version
from src.build_segments import load_segments

REFERENCE = config.SERVICE_DIR / "reference.json"


def oov_rate(texts, vectorizer) -> float:
    analyzer, vocab = vectorizer.build_analyzer(), vectorizer.vocabulary_
    grams = [g for t in texts for g in analyzer(t) if " " not in g]
    return sum(g not in vocab for g in grams) / max(len(grams), 1)


def load_reference(vocab_version: str) -> list[float]:
    ref = json.loads(REFERENCE.read_text())
    if ref["vocab_version"] != vocab_version:
        raise SystemExit("service reference was built with another baseline vocabulary")
    return ref["oov_rates"]


def main() -> None:
    vectorizer = load_frozen_pipeline().named_steps["tfidf"]
    val = load_segments()
    val = val[val["split"] == "val"]
    ids = sorted(val["contract_id"].unique())
    rates = [oov_rate(val.loc[val["contract_id"] == c, "text"], vectorizer) for c in ids]
    config.SERVICE_DIR.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(json.dumps({"vocab_version": model_version(), "contract_ids": [int(c) for c in ids],
                                     "oov_rates": rates}, indent=2))
    q = np.percentile(rates, [0, 25, 50, 75, 95, 100])
    print(f"Validation contracts: {len(ids)}; OOV rate min {q[0]:.4f}, 25% {q[1]:.4f}, median {q[2]:.4f}, "
          f"75% {q[3]:.4f}, 95% {q[4]:.4f}, max {q[5]:.4f}")
    print(f"Wrote {REFERENCE}")


if __name__ == "__main__":
    main()
