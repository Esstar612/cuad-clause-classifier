"""Step 9a: source the fresh test set from SEC EDGAR (rules in src/fresh/config.py and BUILD_LOG Step 9).

  python -m src.fresh.source list       EFTS listing, saved once to data/fresh/candidates.parquet
  python -m src.fresh.source draw       seeded draw with exclusions -> contracts.parquet, draw_log.csv, texts
  python -m src.fresh.source describe   label-free: segment counts and lengths next to CUAD test
  python -m src.fresh.source bundle [--cuad-train ID]   labeling-tool bundle (the fresh set, or one CUAD train contract)

Nobody reads a fresh contract body before labeling: these commands print counts, codes and numbers only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zlib
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from src import config
from src.fresh import config as F
from src.fresh.edgar import Edgar, EdgarError, document_url
from src.fresh.text import decode, html_to_text, sha256

SNAPSHOT_COLUMNS = ["accession", "file_name", "cik", "file_date", "file_type", "file_description", "form",
                    "type", "type_status"]


# ----------------------------------------------------------------------------- frame

def classify(description: str | None) -> tuple[str | None, str]:
    """(type, status): status is 'one', 'none' or 'ambiguous'. A phrase inside a longer matched phrase of another
    type does not count: "hosting services agreement" is Hosting, not also Service."""
    d = description.lower() if isinstance(description, str) else ""   # pandas turns a missing one into NaN
    matched = {t: [p for p in phrases if p in d] for t, (_, phrases) in F.TYPES.items()}
    longer = [(t, q) for t, qs in matched.items() for q in qs]
    hits = sorted(t for t, ps in matched.items()
                  if any(not any(p in q and p != q for u, q in longer if u != t) for p in ps))
    if len(hits) == 1:
        return hits[0], "one"
    return None, "ambiguous" if hits else "none"


def month_windows(start: str, end: str) -> list[tuple[str, str]]:
    d, stop, out = date.fromisoformat(start), date.fromisoformat(end), []
    while d <= stop:
        nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        out.append((d.isoformat(), min(nxt - timedelta(days=1), stop).isoformat()))
        d = nxt
    return out


def hit_row(hit: dict) -> dict:
    s = hit["_source"]
    accession, file_name = hit["_id"].split(":", 1)
    return {"accession": accession, "file_name": file_name, "cik": str((s.get("ciks") or [""])[0]),
            "file_date": s.get("file_date"), "file_type": s.get("file_type") or "",
            "file_description": s.get("file_description"), "form": s.get("form")}


def list_frame(edgar: Edgar, start: str, end: str) -> tuple[pd.DataFrame, dict]:
    rows, queries = [], {}
    for t, (phrase, _) in sorted(F.TYPES.items()):
        for ws, we in month_windows(start, end):
            offset, total = 0, None
            while True:
                hits = edgar.search(phrase, ws, we, offset)
                total = hits["total"]
                rows += [hit_row(h) for h in hits["hits"]]
                offset += len(hits["hits"])
                if not hits["hits"] or offset >= min(total["value"], F.EFTS_MAX_FROM + F.EFTS_PAGE):
                    break
            queries[f"{t} | {ws}"] = {"phrase": phrase, "hits": total["value"], "relation": total["relation"],
                                      "truncated": total["relation"] != "eq" or total["value"] > F.EFTS_MAX_FROM
                                      + F.EFTS_PAGE}
    df = pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS[:-2]).drop_duplicates(["accession", "file_name"])
    ex10 = df[df["file_type"].str.upper().str.startswith(F.EXHIBIT_PREFIX)].copy()
    assigned = ex10["file_description"].map(classify)
    ex10["type"], ex10["type_status"] = assigned.str[0], assigned.str[1]
    ex10 = ex10.sort_values(["accession", "file_name"]).reset_index(drop=True)
    status = ex10["type_status"].value_counts()
    report = {"frame_start": start, "frame_end": end, "listed_utc": datetime.now(timezone.utc).isoformat(
        timespec="seconds"), "unique_documents": int(len(df)), "ex10_documents": int(len(ex10)),
        "ex10_by_status": {k: int(status.get(k, 0)) for k in ("one", "none", "ambiguous")},
        "ex10_share_by_status": {k: float(status.get(k, 0) / max(len(ex10), 1)) for k in ("one", "none", "ambiguous")},
        "in_frame_by_type": {k: int(v) for k, v in ex10.loc[ex10["type_status"] == "one", "type"]
                             .value_counts().sort_index().items()},
        "truncated_queries": sorted(k for k, q in queries.items() if q["truncated"]), "queries": queries}
    return ex10[SNAPSHOT_COLUMNS], report


# ----------------------------------------------------------------------------- allocation and draw

def test_type_counts() -> dict[str, int]:
    splits = pd.read_csv(config.SPLITS_CSV)
    return {str(k): int(v) for k, v in splits.loc[splits["split"] == "test", "contract_type"].value_counts().items()}


def allocate(test_counts: dict[str, int], slots: int, capacity: dict[str, int]) -> dict[str, int]:
    """Largest remainder over the CUAD test mix; ties by test count, then name; shortfall moves on."""
    total = sum(test_counts.values())
    quota = {t: slots * n / total for t, n in test_counts.items()}
    alloc = {t: min(int(q), capacity.get(t, 0)) for t, q in quota.items()}
    order = sorted(test_counts, key=lambda t: (-(quota[t] - int(quota[t])), -test_counts[t], t))
    while sum(alloc.values()) < slots:
        open_ = [t for t in order if alloc[t] < capacity.get(t, 0)]
        if not open_:
            raise SystemExit("not enough eligible candidates to fill the frame")
        alloc[open_[0]] += 1
        order = open_[1:] + open_[:1]
    return alloc


def type_stream(t: str) -> np.random.Generator:
    return np.random.default_rng([config.SEED, zlib.crc32(f"fresh_source/{t}".encode())])


def draw(candidates: pd.DataFrame, test_counts: dict[str, int], slots: int, check) -> tuple[pd.DataFrame, list[dict]]:
    """check(row, picked) -> (reason code or None, measured numbers). Every candidate is checked at most once."""
    pools, cursor, picked, log, n_ok = {}, {}, [], [], Counter()
    for t in test_counts:
        pool = candidates[candidates["type"] == t].sort_values(["accession", "file_name"]).reset_index(drop=True)
        pools[t], cursor[t] = pool.iloc[type_stream(t).permutation(len(pool))], 0
    capacity = {t: len(pools[t]) for t in test_counts}
    alloc = allocate(test_counts, slots, capacity)
    while True:
        for t in sorted(alloc):
            while n_ok[t] < alloc[t] and cursor[t] < len(pools[t]):
                row = pools[t].iloc[cursor[t]]
                cursor[t] += 1
                reason, numbers = check(row, picked)
                log.append({"type": t, "accession": row["accession"], "file_name": row["file_name"],
                            "reason": reason or "accepted", **numbers})
                if reason is None:
                    picked.append(row.to_dict())
                    n_ok[t] += 1
            if cursor[t] == len(pools[t]):
                capacity[t] = n_ok[t]
        if len(picked) == sum(alloc.values()):
            return pd.DataFrame(picked), log
        alloc = allocate(test_counts, slots, capacity)
        if any(alloc[t] < n_ok[t] for t in alloc):
            raise SystemExit("re-allocation went below an accepted count")


# ----------------------------------------------------------------------------- exclusions

def shingle_hashes(text: str, k: int = F.SHINGLE_WORDS) -> np.ndarray:
    words = re.findall(r"\w+", text.lower())
    grams = {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}
    return np.unique(np.fromiter((int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "little")
                                  for g in grams), dtype=np.uint64, count=len(grams)))


def containment(a: str, b: str, k: int = F.SHINGLE_WORDS) -> float:
    sa, sb = shingle_hashes(a, k), shingle_hashes(b, k)
    return two_sided(len(np.intersect1d(sa, sb, assume_unique=True)), len(sa), len(sb))


def two_sided(inter: int, na: int, nb: int) -> float:
    return max(inter / max(na, 1), inter / max(nb, 1))


class ShingleIndex:
    """Hashed shingles of every CUAD text, sorted once; containment against all of them in one pass."""

    def __init__(self, texts: dict[int, str], k: int = F.SHINGLE_WORDS):
        hashes = {cid: shingle_hashes(t, k) for cid, t in texts.items()}
        self.k, self.sizes = k, {cid: len(h) for cid, h in hashes.items()}
        self.h = np.concatenate(list(hashes.values()))
        self.ids = np.concatenate([np.full(len(h), cid) for cid, h in hashes.items()])

    def max_containment(self, text: str) -> float:
        q = shingle_hashes(text, self.k)
        counts = Counter(self.ids[np.isin(self.h, q)].tolist())
        return max((two_sided(n, len(q), self.sizes[cid]) for cid, n in counts.items()), default=0.0)


def is_amendment(description: str | None, text: str) -> bool:
    s = f"{description or ''} {text[:F.AMENDMENT_HEAD_CHARS]}".lower()
    return bool(F.AMENDMENT.search(s)) and F.RESTATED not in s


def blank_markers(text: str) -> int:
    return len(F.BLANK_PARTY.findall(text[:F.BLANK_HEAD_CHARS]))


def redaction_rate(text: str) -> float:
    return 1000 * len(F.REDACTION.findall(text)) / max(len(text), 1)


def prior_sentences(text: str, n: int = F.PRIOR_SENTENCES) -> list[str]:
    """The n longest sentences of 15 to 40 words (ties by position), as plain words for a phrase query."""
    out = []
    for i, s in enumerate(re.split(r"(?<=[.;:!?])\s+|\n+", text)):
        words = re.findall(r"[A-Za-z0-9]+", s)
        if F.PRIOR_MIN_WORDS <= len(words) <= F.PRIOR_MAX_WORDS:
            out.append((-len(words), i, " ".join(words)))
    return [s for _, _, s in sorted(out)[:n]]


def prior_before(edgar: Edgar):
    end = (date.fromisoformat(F.FRAME_START) - timedelta(days=1)).isoformat()

    def hits(sentence: str) -> int:
        return int(edgar.search(sentence, F.PRIOR_START, end)["total"]["value"])
    return hits


def make_check(edgar: Edgar, cuad: ShingleIndex, texts: dict, prior_hits):
    """Exclusions in the pre-registered order. texts[(accession, file_name)] keeps each fetched text."""

    def check(row, picked) -> tuple[str | None, dict]:
        if not row["file_name"].lower().endswith((".htm", ".html")):
            return "not_html", {}
        raw_path = F.RAW_DIR / f"{row['accession']}_{row['file_name']}"
        try:
            raw = raw_path.read_bytes() if raw_path.exists() else edgar.document(row["cik"], row["accession"],
                                                                                row["file_name"])
        except (EdgarError, ValueError):   # ValueError: a hit without a CIK
            return "fetch_error", {}
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)
        try:
            text = html_to_text(decode(raw))
        except ValueError:
            return "conversion_error", {}
        numbers = {"chars": len(text)}
        if len(text) < F.MIN_CHARS:
            return "too_short", numbers
        if len(text) > F.MAX_CHARS:
            return "too_long", numbers
        if is_amendment(row["file_description"], text):
            return "amendment", numbers
        numbers["blank_markers"] = blank_markers(text)
        if numbers["blank_markers"] > F.BLANK_MAX:
            return "form_or_template", numbers
        numbers["redaction_per_1000"] = redaction_rate(text)
        if numbers["redaction_per_1000"] > F.REDACTION_MAX_PER_1000:
            return "redacted", numbers
        numbers["cuad_containment"] = cuad.max_containment(text)
        if numbers["cuad_containment"] >= F.CUAD_OVERLAP_MAX:
            return "cuad_overlap", numbers
        numbers["duplicate_containment"] = max((containment(text, texts[(p["accession"], p["file_name"])])
                                                for p in picked), default=0.0)
        if numbers["duplicate_containment"] >= F.DUPLICATE_MAX:
            return "duplicate", numbers
        sentences = prior_sentences(text)
        try:
            found = [prior_hits(s) for s in sentences]
        except EdgarError:
            return "efts_error", numbers
        numbers["prior_sentences"], numbers["prior_sentences_hit"] = len(sentences), sum(n > 0 for n in found)
        if len(sentences) == F.PRIOR_SENTENCES and all(n > 0 for n in found):
            return "prior_appearance", numbers
        texts[(row["accession"], row["file_name"])] = text
        return None, numbers
    return check


# ----------------------------------------------------------------------------- commands

def cmd_list(_args) -> None:
    if F.CANDIDATES.exists():
        raise SystemExit(f"{F.CANDIDATES} exists: the frame is listed once and every draw reads that snapshot")
    end = date.today().isoformat()
    frame, report = list_frame(Edgar(), F.FRAME_START, end)
    F.FRESH_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(F.CANDIDATES, index=False)
    F.LIST_REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "queries"}, indent=2))
    print(f"Wrote {F.CANDIDATES} ({len(frame)} EX-10 documents) and {F.LIST_REPORT}")


def cmd_draw(_args) -> None:
    if F.CONTRACTS.exists():
        raise SystemExit(f"{F.CONTRACTS} exists: the draw runs once")
    from src.data import load_contexts, load_raw_json
    candidates = pd.read_parquet(F.CANDIDATES)
    frame = candidates[candidates["type_status"] == "one"]
    edgar = Edgar()
    print("Indexing CUAD texts...", flush=True)
    cuad = ShingleIndex(load_contexts(load_raw_json()))
    texts: dict = {}
    picked, log = draw(frame, test_type_counts(), F.SLOTS, make_check(edgar, cuad, texts, prior_before(edgar)))
    picked = picked.reset_index(drop=True)
    picked.insert(0, "contract_id", range(F.CONTRACT_ID_START, F.CONTRACT_ID_START + len(picked)))
    F.TEXT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in picked.itertuples():
        text = texts[(r.accession, r.file_name)]
        (F.TEXT_DIR / f"{r.contract_id}.txt").write_text(text, encoding="utf-8")
        raw = (F.RAW_DIR / f"{r.accession}_{r.file_name}").read_bytes()
        rows.append({"chars": len(text), "text_sha256": sha256(text), "html_sha256": sha256(raw),
                     "url": document_url(r.cik, r.accession, r.file_name)})
    contracts = pd.concat([picked, pd.DataFrame(rows)], axis=1).rename(columns={"type": "contract_type"})
    contracts.drop(columns=["type_status"]).to_parquet(F.CONTRACTS, index=False)
    log_df = pd.DataFrame(log)
    log_df.to_csv(F.DRAW_LOG, index=False)
    print(f"Accepted {len(picked)} of {len(log_df)} checked. Reasons:")
    print(log_df["reason"].value_counts().to_string())
    print("\nPer type (accepted / checked):")
    print(log_df.assign(ok=log_df["reason"] == "accepted").groupby("type")["ok"].agg(["sum", "size"]).to_string())
    print(f"\nWrote {F.CONTRACTS}, {F.DRAW_LOG} and {len(picked)} texts under {F.TEXT_DIR}")


def load_texts(contracts: pd.DataFrame) -> dict[int, str]:
    out = {}
    for r in contracts.itertuples():
        text = (F.TEXT_DIR / f"{r.contract_id}.txt").read_text(encoding="utf-8")
        if sha256(text) != r.text_sha256:
            raise SystemExit(f"{r.contract_id}: stored text does not match its hash")
        out[r.contract_id] = text
    return out


def cmd_describe(_args) -> None:
    from src.segment import segment_text
    contracts = pd.read_parquet(F.CONTRACTS)
    texts = load_texts(contracts)
    fresh = pd.DataFrame([{"contract_id": cid, "chars": e - s}
                          for cid, t in texts.items()
                          for s, e in ((g.start, g.end) for g in segment_text(t, config.SEGMENT_MIN_CHARS,
                                                                              config.SEGMENT_MAX_CHARS))])
    seg = pd.read_parquet(config.PROCESSED_DIR / "segments.parquet", columns=["contract_id", "split", "start", "end"])
    test = seg[seg["split"] == "test"].assign(chars=lambda d: d["end"] - d["start"])
    q = [0.1, 0.25, 0.5, 0.75, 0.9]
    rows = {}
    for name, df in (("CUAD test", test), ("fresh", fresh)):
        per = df.groupby("contract_id").size()
        rows[name] = {"contracts": per.size, "segments": len(df),
                      **{f"segments/contract p{int(x * 100)}": per.quantile(x) for x in q},
                      **{f"segment chars p{int(x * 100)}": df["chars"].quantile(x) for x in q},
                      "contract chars median": df.groupby("contract_id")["chars"].sum().median()}
    print("Label-free segmentation comparison (frozen settings):")
    print(pd.DataFrame(rows).round(1).to_string())


def cmd_bundle(args) -> None:
    if args.cuad_train is not None:
        from src.data import load_contexts, load_raw_json
        splits = pd.read_csv(config.SPLITS_CSV).set_index("contract_id")["split"]
        if splits.get(args.cuad_train) != "train":
            raise SystemExit("the tool trial uses a CUAD train contract only")
        text = load_contexts(load_raw_json())[args.cuad_train]
        items = [{"contract_id": args.cuad_train, "text": text, "text_sha256": sha256(text)}]
    else:
        contracts = pd.read_parquet(F.CONTRACTS)
        texts = load_texts(contracts)
        items = [{"contract_id": int(r.contract_id), "text": texts[r.contract_id], "text_sha256": r.text_sha256}
                 for r in contracts.itertuples()]
    from src.fresh.build import categories_36
    bundle = {"guide_version": F.GUIDE_VERSION, "categories": categories_36(), "contracts": items}
    F.BUNDLE.write_text("window.BUNDLE = " + json.dumps(bundle, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"Wrote {F.BUNDLE} ({len(items)} contracts). Open tools/labeler/index.html in a browser.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("list", "draw", "describe"):
        sub.add_parser(name)
    b = sub.add_parser("bundle")
    b.add_argument("--cuad-train", type=int)
    args = parser.parse_args()
    {"list": cmd_list, "draw": cmd_draw, "describe": cmd_describe, "bundle": cmd_bundle}[args.cmd](args)


if __name__ == "__main__":
    main()
