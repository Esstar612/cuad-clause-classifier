"""How much reading a PDF, rather than CUAD's gold text, costs (Step 7, pre-registered in BUILD_LOG).

  python -m src.extraction_eval     97 validation contracts; OCR forced on a seeded sample of 10

Both paths are scored the same way: segment_text on the whole text, fresh predictions from the
baseline and the tuned legal-BERT at Rule B thresholds, contract-level label sets (a label counts
if any segment is flagged) against the gold contract labels from spans.parquet. Descriptive only.
Validation contracts only; no test or shift data is read.
"""

from __future__ import annotations

import json
import zlib
from collections import Counter

import numpy as np
import pandas as pd

from src import config
from src.bootstrap import percentile_ci, resample_weights
from src.data import contract_ids, load_contexts, load_raw_json, title_key
from src.infer import load_predictors
from src.labels import model_label
from src.pdf_text import extract, ocr_available
from src.segment import segment_text
from src.thresholds import apply_thresholds

MODELS = ("baseline", config.TUNED_MODEL_NAME)
OUT = config.EVAL_DIR / "extraction.json"


def word_overlap(extracted: str, gold: str) -> tuple[int, int, int]:
    """(common, extracted, gold) word counts; lowercased, whitespace-split, as multisets."""
    e, g = Counter(extracted.lower().split()), Counter(gold.lower().split())
    return sum((e & g).values()), sum(e.values()), sum(g.values())


def label_set_counts(pred: dict, gold: dict, ids) -> np.ndarray:
    """Per contract: tp, fp, fn over the kept labels (contract-level)."""
    return np.array([[len(pred[c] & gold[c]), len(pred[c] - gold[c]), len(gold[c] - pred[c])] for c in ids])


def micro_f1(counts: np.ndarray, W: np.ndarray) -> np.ndarray:
    tp, fp, fn = (W @ counts).T
    return 2 * tp / np.maximum(2 * tp + fp + fn, 1)


def validation_pdfs(raw: dict, val_ids: set) -> dict:
    """contract_id -> PDF path: exact title_key, then a unique prefix (as load_contract_types)."""
    by_key: dict[str, list] = {}
    for pdf in config.CUAD_PDF_DIR.rglob("*"):
        if pdf.suffix.lower() == ".pdf":
            by_key.setdefault(title_key(pdf.stem), []).append(pdf)
    out = {}
    for title, cid in contract_ids(raw).items():
        if cid not in val_ids:
            continue
        key = title_key(title)
        cands = [key] if key in by_key else [k for k in by_key if key.startswith(k) or k.startswith(key)]
        if len(cands) == 1 and len(by_key[cands[0]]) == 1:
            out[cid] = by_key[cands[0]][0]
    if len(out) != len(val_ids) or len(set(out.values())) != len(out):
        raise SystemExit(f"matched {len(set(out.values()))} distinct PDFs to {len(out)} of {len(val_ids)} "
                         "validation contracts; refusing")
    return out


def label_sets(text: str, predictor) -> set:
    segs = segment_text(text)
    if not segs:
        return set()
    proba = predictor.scores([s.text for s in segs]).proba
    flags = apply_thresholds(proba, predictor.label_order, predictor.thresholds["balanced"])
    return {lab for j, lab in enumerate(predictor.label_order) if flags[:, j].any()}


def _ci(samples, point) -> dict:
    lo, hi, n = percentile_ci(samples)
    return {"point": float(point), "ci_low": lo, "ci_high": hi, "n_resamples": n}


def main() -> None:
    if not ocr_available():
        raise SystemExit("Tesseract is not installed; the OCR measurement cannot run (brew install tesseract)")
    raw = load_raw_json()
    contexts = load_contexts(raw)
    splits = pd.read_parquet(config.PROCESSED_DIR / "splits.parquet")
    val_ids = set(splits.loc[splits["split"] == "val", "contract_id"].astype(int))
    pdfs = validation_pdfs(raw, val_ids)
    predictors, failed = load_predictors(MODELS)
    if failed:
        raise SystemExit(f"models failed to load: {failed}")
    label_order = predictors["baseline"].label_order
    if any(p.label_order != label_order for p in predictors.values()):
        raise SystemExit("served models disagree on label order")
    spans = pd.read_parquet(config.PROCESSED_DIR / "spans.parquet")
    pos = spans[spans["has_answer"] & spans["contract_id"].isin(val_ids)]
    gold = {c: set() for c in val_ids}
    for cid, cat in zip(pos["contract_id"], pos["category"]):
        lab = model_label(cat)
        if lab in label_order:
            gold[int(cid)].add(lab)

    contracts = pd.read_parquet(config.PROCESSED_DIR / "contracts.parquet")
    ids, W = resample_weights(contracts[contracts["contract_id"].isin(val_ids)], "extraction")
    ids = [int(c) for c in ids]
    words, pages, sets = {}, {}, {m: {"gold": {}, "pdf": {}} for m in MODELS}
    for n, cid in enumerate(ids, 1):
        ex = extract(pdfs[cid].read_bytes(), max_ocr_pages=None)
        words[cid] = word_overlap(ex.text, contexts[cid])
        pages[cid] = {"pages": ex.pages, "ocr_pages": len(ex.ocr_pages), "warnings": ex.warnings}
        for m in MODELS:
            sets[m]["gold"][cid] = label_sets(contexts[cid], predictors[m])
            sets[m]["pdf"][cid] = label_sets(ex.text, predictors[m])
        if n % 10 == 0:
            print(f"  {n}/{len(ids)} contracts", flush=True)

    ones = np.ones((1, len(ids)))
    wc = np.array([words[c] for c in ids], dtype=float)
    prec, rec = (W @ wc[:, 0]) / (W @ wc[:, 1]), (W @ wc[:, 0]) / (W @ wc[:, 2])
    report = {"contracts": len(ids), "resamples": int(W.shape[0]), "stream": "extraction",
              "text_layer": {"word_precision": _ci(prec, wc[:, 0].sum() / wc[:, 1].sum()),
                             "word_recall": _ci(rec, wc[:, 0].sum() / wc[:, 2].sum()),
                             "contracts_with_ocr_pages": sum(pages[c]["ocr_pages"] > 0 for c in ids),
                             "pages": int(sum(pages[c]["pages"] for c in ids)),
                             "ocr_pages": int(sum(pages[c]["ocr_pages"] for c in ids))},
              "label_sets": {}}
    for m in MODELS:
        g = label_set_counts(sets[m]["gold"], gold, ids)
        p = label_set_counts(sets[m]["pdf"], gold, ids)
        fg, fp = micro_f1(g, W), micro_f1(p, W)
        report["label_sets"][m] = {"gold_text": _ci(fg, micro_f1(g, ones)[0]), "pdf_text": _ci(fp, micro_f1(p, ones)[0]),
                                   "gold_minus_pdf": _ci(fg - fp, micro_f1(g, ones)[0] - micro_f1(p, ones)[0]),
                                   "contracts_with_different_sets": int(sum(sets[m]["gold"][c] != sets[m]["pdf"][c]
                                                                            for c in ids))}

    rng = np.random.default_rng([config.SEED, zlib.crc32(b"extraction_ocr")])
    sample = sorted(int(c) for c in rng.choice(sorted(ids), size=config.EXTRACTION_OCR_SAMPLE, replace=False))
    ocr_rows = []
    for cid in sample:
        ex = extract(pdfs[cid].read_bytes(), force_ocr=True, max_ocr_pages=None)
        common, n_ext, n_gold = word_overlap(ex.text, contexts[cid])
        row = {"contract_id": cid, "pages": ex.pages, "ocr_pages": len(ex.ocr_pages),
               "word_precision": common / max(n_ext, 1), "word_recall": common / max(n_gold, 1),
               "text_layer_word_recall": words[cid][0] / max(words[cid][2], 1)}
        for m in MODELS:
            ocr_set = label_sets(ex.text, predictors[m])
            for path, s in (("gold", sets[m]["gold"][cid]), ("ocr", ocr_set)):
                tp, fp, fn = label_set_counts({cid: s}, {cid: gold[cid]}, [cid])[0]
                row[f"{m}_{path}_f1"] = 2 * tp / max(2 * tp + fp + fn, 1)
        ocr_rows.append(row)
        print(f"  OCR {cid}: {ex.pages} pages", flush=True)
    report["ocr_sample"] = ocr_rows
    report["per_contract_pages"] = {str(c): pages[c] for c in ids}
    config.EVAL_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2))

    tl = report["text_layer"]
    print(f"\n=== Text layer vs gold text, {len(ids)} validation contracts (point [95% CI], "
          f"{W.shape[0]} paired contract resamples) ===")
    for k in ("word_precision", "word_recall"):
        print(f"  {k}: {tl[k]['point']:.4f} [{tl[k]['ci_low']:.4f}, {tl[k]['ci_high']:.4f}]")
    print(f"  pages {tl['pages']}; pages sent to OCR (no text layer) {tl['ocr_pages']} "
          f"in {tl['contracts_with_ocr_pages']} contracts")
    print("\n=== Contract-level label sets, micro-F1 against gold contract labels (Rule B thresholds) ===")
    for m, r in report["label_sets"].items():
        print(f"  {m}: gold text {r['gold_text']['point']:.4f} [{r['gold_text']['ci_low']:.4f}, "
              f"{r['gold_text']['ci_high']:.4f}]; PDF text {r['pdf_text']['point']:.4f} "
              f"[{r['pdf_text']['ci_low']:.4f}, {r['pdf_text']['ci_high']:.4f}]; gold minus PDF "
              f"{r['gold_minus_pdf']['point']:+.4f} [{r['gold_minus_pdf']['ci_low']:+.4f}, "
              f"{r['gold_minus_pdf']['ci_high']:+.4f}]; contracts whose set changed "
              f"{r['contracts_with_different_sets']}")
    print(f"\n=== Forced OCR, {len(sample)} seeded contracts (per contract, no interval; digitally generated "
          "PDFs, so likely optimistic against real scans) ===")
    print(pd.DataFrame(ocr_rows).round(4).to_string(index=False))
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
