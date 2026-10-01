"""Step 7 service check against a running service: one validation contract as text and as PDF.

  uvicorn service.app:app --port 8000 --workers 1      (in another terminal)
  python -m scripts.service_check [--url URL] [--deepseek]

Local models at both operating points on both inputs; with --deepseek, one DeepSeek request
(text, balanced), which is the only call that spends money.
"""

from __future__ import annotations

import argparse

import httpx
import pandas as pd

from src import config
from src.data import load_contexts, load_raw_json
from src.extraction_eval import validation_pdfs
from src.labels import label_set

CID = 143
LOCAL = ("baseline", config.TUNED_MODEL_NAME)


def show(what: str, r: httpx.Response) -> None:
    if r.status_code != 200:
        print(f"{what}: HTTP {r.status_code} {r.text[:300]}")
        return
    j = r.json()
    flagged = sorted({lab["label"] for s in j["segments"] for lab in s["labels"]})
    print(f"{what}: segments {j['segments_total']}, flagged {j['segments_flagged']}, "
          f"not classified {j['segments_not_classified']}, cost ${j['cost_usd']:.4f}")
    print(f"  labels ({len(flagged)}): {flagged}")
    if "extraction" in j:
        print(f"  extraction: { {k: v for k, v in j['extraction'].items() if k != 'text'} }")
    if "input_check" in j:
        print(f"  OOV rate {j['input_check']['oov_rate']:.4f}, "
              f"validation percentile {j['input_check']['validation_percentile']:.1f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--deepseek", action="store_true")
    args = ap.parse_args()
    raw = load_raw_json()
    segments = pd.read_parquet(config.PROCESSED_DIR / "segments.parquet")
    if set(segments.loc[segments["contract_id"] == CID, "split"]) != {"val"}:
        raise SystemExit(f"contract {CID} is not a validation contract")
    text = load_contexts(raw)[CID]
    pdf = validation_pdfs(raw, {CID})[CID]
    pdf_bytes = pdf.read_bytes()
    spans = pd.read_parquet(config.PROCESSED_DIR / "spans.parquet")
    gold = label_set(spans.loc[(spans["contract_id"] == CID) & spans["has_answer"], "category"])
    print(f"contract {CID} ({pdf.name}); gold labels ({len(gold)}): {gold}")

    with httpx.Client(base_url=args.url, timeout=1000) as c:
        print("health:", c.get("/health").json())
        for name, info in c.get("/models").json()["served"].items():
            print(f"model {name}: {info['version']}, points {info['operating_points']}, notes {info['notes']}")
        for model in LOCAL:
            for point in ("balanced", "high_recall"):
                show(f"{model} | {point} | text",
                     c.post("/classify", json={"text": text, "model": model, "operating_point": point}))
                show(f"{model} | {point} | pdf",
                     c.post("/classify/pdf", files={"file": (pdf.name, pdf_bytes, "application/pdf")},
                            data={"model": model, "operating_point": point}))
        if args.deepseek:
            show("fireworks-deepseek | balanced | text",
                 c.post("/classify", json={"text": text, "model": "fireworks-deepseek"}))
        page = c.post("/review", data={"text": text, "model": "baseline"})
        print(f"review page: HTTP {page.status_code}, {len(page.text)} characters")


if __name__ == "__main__":
    main()
