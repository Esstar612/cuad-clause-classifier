"""Load CUAD v1 and report its real structure.

I/O and inspection only: no splitting, segmentation, or labeling decisions live here.

Run: python -m src.data | tee data/processed/step1_inspect.txt
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd

from src import config

# Canonical contract types from the CUAD datasheet (section II-C), keyed by a
# normalized folder-name form. Folder names in full_contract_pdf/ are spelled
# inconsistently, so matching goes through _normalize_type_folder().
CONTRACT_TYPES = {
    "affiliate": "Affiliate",
    "agency": "Agency",
    "collaboration": "Collaboration/Cooperation",
    "cooperation": "Collaboration/Cooperation",
    "co branding": "Co-Branding",
    "cobranding": "Co-Branding",
    "consulting": "Consulting",
    "development": "Development",
    "distributor": "Distributor",
    "endorsement": "Endorsement",
    "franchise": "Franchise",
    "hosting": "Hosting",
    "ip": "IP",
    "intellectual property": "IP",
    "joint venture": "Joint Venture",
    "license": "License",
    "maintenance": "Maintenance",
    "manufacturing": "Manufacturing",
    "marketing": "Marketing",
    "non compete": "Non-Compete/No-Solicit/Non-Disparagement",
    "outsourcing": "Outsourcing",
    "promotion": "Promotion",
    "reseller": "Reseller",
    "service": "Service",
    "sponsorship": "Sponsorship",
    "supply": "Supply",
    "strategic alliance": "Strategic Alliance",
    "transportation": "Transportation",
}

REDACTION_PATTERNS = {
    "asterisks (***)": re.compile(r"\*{3,}"),
    "underscores (_____)": re.compile(r"_{5,}"),
    "<omitted>": re.compile(r"<omitted>", re.IGNORECASE),
}


def title_key(name: str) -> str:
    """Normalize a title or file stem so JSON titles, txt names, and pdf names compare."""
    s = unicodedata.normalize("NFC", name)
    s = s.strip().rstrip("-").strip()
    return s.casefold()


def _normalize_type_folder(folder: str) -> str:
    s = folder.lower().replace("_", " ")
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\bfiling\b", " ", s)
    s = re.sub(r"\bagreements?\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _map_type_folder(folder: str) -> str | None:
    norm = _normalize_type_folder(folder)
    if norm in CONTRACT_TYPES:
        return CONTRACT_TYPES[norm]
    for key, canonical in CONTRACT_TYPES.items():
        if norm.startswith(key + " ") or norm.startswith(key + "s"):
            return canonical
    return None


def load_raw_json(path: Path = config.CUAD_JSON) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def contract_ids(raw: dict) -> dict[str, int]:
    """Stable integer id per contract, from sorted normalized titles."""
    titles = sorted(unicodedata.normalize("NFC", d["title"]) for d in raw["data"])
    return {t: i for i, t in enumerate(titles)}


def load_contexts(raw: dict) -> dict[int, str]:
    ids = contract_ids(raw)
    out = {}
    for doc in raw["data"]:
        cid = ids[unicodedata.normalize("NFC", doc["title"])]
        out[cid] = "\n".join(p["context"] for p in doc["paragraphs"])
    return out


def load_spans(raw: dict) -> pd.DataFrame:
    """One row per answer span, plus one row per empty (contract, category) pair."""
    ids = contract_ids(raw)
    rows = []
    for doc in raw["data"]:
        title = unicodedata.normalize("NFC", doc["title"])
        cid = ids[title]
        for para_idx, para in enumerate(doc["paragraphs"]):
            for qa in para["qas"]:
                category = qa["id"].rsplit("__", 1)[1]
                base = {
                    "contract_id": cid,
                    "title": title,
                    "paragraph_idx": para_idx,
                    "category": category,
                    "is_impossible": bool(qa.get("is_impossible", False)),
                }
                if not qa["answers"]:
                    rows.append({**base, "has_answer": False, "answer_text": None,
                                 "answer_start": pd.NA, "answer_end": pd.NA})
                for ans in qa["answers"]:
                    start = int(ans["answer_start"])
                    rows.append({**base, "has_answer": True, "answer_text": ans["text"],
                                 "answer_start": start, "answer_end": start + len(ans["text"])})
    df = pd.DataFrame(rows)
    df["answer_start"] = df["answer_start"].astype("Int64")
    df["answer_end"] = df["answer_end"].astype("Int64")
    return df


def load_contract_types(raw: dict, pdf_dir: Path = config.CUAD_PDF_DIR):
    """Map contract_id -> canonical contract type using pdf folder names.

    Returns (types, report). report lists unmapped folders, fuzzy matches, and
    titles with no pdf, so nothing is dropped silently.
    """
    ids = contract_ids(raw)
    pdf_types: dict[str, str] = {}
    folder_names: Counter = Counter()
    unmapped_folders: set[str] = set()
    for pdf in pdf_dir.rglob("*"):
        if pdf.suffix.lower() != ".pdf":
            continue
        ctype = None
        for parent in pdf.relative_to(pdf_dir).parents:
            if parent.name == "":
                break
            ctype = _map_type_folder(parent.name)
            if ctype:
                folder_names[parent.name] += 1
                break
        if ctype is None:
            unmapped_folders.add(str(pdf.parent.relative_to(pdf_dir)))
            continue
        pdf_types[title_key(pdf.stem)] = ctype

    types: dict[int, str | None] = {}
    fuzzy, missing = [], []
    for title, cid in ids.items():
        key = title_key(title)
        if key in pdf_types:
            types[cid] = pdf_types[key]
            continue
        candidates = [k for k in pdf_types if key.startswith(k) or k.startswith(key)]
        if len(candidates) == 1:
            types[cid] = pdf_types[candidates[0]]
            fuzzy.append((title, candidates[0]))
        else:
            types[cid] = None
            missing.append(title)
    report = {
        "folder_names": folder_names,
        "unmapped_folders": sorted(unmapped_folders),
        "fuzzy_matches": fuzzy,
        "missing": missing,
        "n_pdfs": sum(1 for p in pdf_dir.rglob("*") if p.suffix.lower() == ".pdf"),
    }
    return types, report


def _txt_comparison(raw: dict, contexts: dict[int, str], txt_dir: Path = config.CUAD_TXT_DIR):
    ids = contract_ids(raw)
    txt_by_key = {title_key(p.stem): p for p in txt_dir.glob("*.txt")}
    equal = differ = missing = 0
    differ_examples = []
    for title, cid in ids.items():
        path = txt_by_key.get(title_key(title))
        if path is None:
            missing += 1
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if text == contexts[cid]:
            equal += 1
        elif text.strip() == contexts[cid].strip():
            equal += 1
        else:
            differ += 1
            if len(differ_examples) < 3:
                differ_examples.append((title, len(text), len(contexts[cid])))
    return {"n_txt_files": len(txt_by_key), "equal": equal, "differ": differ,
            "missing": missing, "differ_examples": differ_examples}


def _overlap_stats(pos: pd.DataFrame):
    """For each positive span, does it overlap a span of a different category?"""
    overlapping = 0
    pairs: Counter = Counter()
    for _, grp in pos.groupby("contract_id"):
        recs = grp[["category", "answer_start", "answer_end"]].to_numpy()
        for i, (cat_i, s_i, e_i) in enumerate(recs):
            hit = False
            for j, (cat_j, s_j, e_j) in enumerate(recs):
                if i == j or cat_i == cat_j:
                    continue
                if s_i < e_j and s_j < e_i:
                    hit = True
                    if cat_i < cat_j:
                        pairs[(cat_i, cat_j)] += 1
            overlapping += hit
    return overlapping, pairs


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 200)
    pd.set_option("display.max_colwidth", 80)

    raw = load_raw_json()
    contexts = load_contexts(raw)
    spans = load_spans(raw)
    types, type_report = load_contract_types(raw)
    pos = spans[spans["has_answer"]].copy()
    pos["span_len"] = (pos["answer_end"] - pos["answer_start"]).astype(int)

    _section("Top level")
    print(f"JSON version field: {raw.get('version')}")
    print(f"Documents in JSON: {len(raw['data'])}")
    print(f"Unique titles: {spans['title'].nunique()}")
    n_paras = Counter(len(d["paragraphs"]) for d in raw["data"])
    print(f"Paragraphs per document (count: n_docs): {dict(n_paras)}")
    qas_per_doc = spans.groupby("contract_id")["category"].nunique()
    print(f"Categories per document (count: n_docs): {dict(Counter(qas_per_doc))}")
    print(f"Unique categories: {spans['category'].nunique()}")
    print(f"Total (contract, category) pairs: {len(spans.drop_duplicates(['contract_id', 'category']))}")
    print(f"Pairs with at least one answer: {len(pos.drop_duplicates(['contract_id', 'category']))}")
    print(f"Total answer spans: {len(pos)}")
    print(f"Contracts with at least one answer: {pos['contract_id'].nunique()}")

    _section("Per category (sorted by contracts with a label)")
    per_cat = (
        pos.groupby("category")
        .agg(spans=("answer_text", "size"),
             contracts=("contract_id", "nunique"),
             median_len=("span_len", "median"),
             p90_len=("span_len", lambda s: s.quantile(0.9)),
             multiline_spans=("answer_text", lambda s: s.str.contains("\n").sum()))
        .reindex(sorted(spans["category"].unique()))
        .fillna(0)
        .astype(int)
        .sort_values("contracts", ascending=False)
    )
    print(per_cat.to_string())

    _section("Span length (characters), all categories")
    print(pos["span_len"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9, 0.99]).round(1).to_string())
    print(f"Spans containing a newline: {pos['answer_text'].str.contains(chr(10)).sum()}")
    spans_per_pair = pos.groupby(["contract_id", "category"]).size()
    print(f"Spans per non-empty (contract, category) pair: {spans_per_pair.describe().round(2).to_dict()}")

    _section("Contract types (from pdf folder names)")
    type_series = pd.Series(types, name="contract_type")
    print(type_series.value_counts(dropna=False).sort_index().to_string())
    print(f"Number of distinct types: {type_series.nunique()}")
    print(f"PDF files found: {type_report['n_pdfs']}")
    print("Raw folder names mapped (folder: n_pdfs):")
    for name, n in sorted(type_report["folder_names"].items()):
        print(f"  {name!r}: {n}  ->  {_map_type_folder(name)}")
    print(f"Unmapped folders: {type_report['unmapped_folders']}")
    print(f"Fuzzy title matches (title -> pdf key): {type_report['fuzzy_matches']}")
    print(f"Titles with no pdf match: {type_report['missing']}")

    _section("Data checks")
    bad_offsets = pos[[
        contexts[r.contract_id][r.answer_start:r.answer_end] != r.answer_text
        for r in pos.itertuples()
    ]]
    print(f"Spans where context[start:end] != answer_text: {len(bad_offsets)}")
    if len(bad_offsets):
        print(bad_offsets[["title", "category", "answer_start"]].head(5).to_string())
    qa_level = spans.groupby(["contract_id", "category"]).agg(
        impossible=("is_impossible", "first"), has_answer=("has_answer", "any"))
    print(f"is_impossible=True but has answers: {int((qa_level.impossible & qa_level.has_answer).sum())}")
    print(f"is_impossible=False but no answers: {int((~qa_level.impossible & ~qa_level.has_answer).sum())}")
    dup = pos.duplicated(["contract_id", "category", "answer_start", "answer_end"]).sum()
    print(f"Exact duplicate spans within a (contract, category): {dup}")
    same_cat_overlap = 0
    for _, grp in pos.groupby(["contract_id", "category"]):
        iv = sorted(zip(grp["answer_start"], grp["answer_end"]))
        same_cat_overlap += sum(1 for a, b in zip(iv, iv[1:]) if b[0] < a[1])
    print(f"Overlapping spans within the same (contract, category): {same_cat_overlap}")
    txt = _txt_comparison(raw, contexts)
    print(f"Context vs full_contract_txt: {txt}")
    lengths = pd.Series({cid: len(t) for cid, t in contexts.items()})
    print(f"Contract length (characters): {lengths.describe().round(0).to_dict()}")
    print("Redaction / splice markers:")
    for name, pat in REDACTION_PATTERNS.items():
        n_contracts = sum(1 for t in contexts.values() if pat.search(t))
        n_answers = int(pos["answer_text"].str.contains(pat).sum())
        print(f"  {name}: contracts containing={n_contracts}, answer spans containing={n_answers}")

    _section("Cross-category overlap (positive spans only)")
    overlapping, pairs = _overlap_stats(pos)
    print(f"Spans overlapping a span of a different category: {overlapping} of {len(pos)} "
          f"({overlapping / len(pos):.1%})")
    print("Top 15 overlapping category pairs:")
    for (a, b), n in pairs.most_common(15):
        print(f"  {n:5d}  {a}  <>  {b}")

    _section("master_clauses.csv")
    if config.CUAD_MASTER_CSV.exists():
        master = pd.read_csv(config.CUAD_MASTER_CSV)
        print(f"Shape: {master.shape}")
    else:
        print("Not found")

    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    spans.to_parquet(config.PROCESSED_DIR / "spans.parquet", index=False)
    contracts = pd.DataFrame([
        {"contract_id": cid, "title": title, "contract_type": types.get(cid),
         "n_chars": len(contexts[cid])}
        for title, cid in sorted(contract_ids(raw).items(), key=lambda kv: kv[1])
    ])
    contracts.to_parquet(config.PROCESSED_DIR / "contracts.parquet", index=False)
    _section("Wrote")
    print(config.PROCESSED_DIR / "spans.parquet", len(spans), "rows")
    print(config.PROCESSED_DIR / "contracts.parquet", len(contracts), "rows")


if __name__ == "__main__":
    main()
