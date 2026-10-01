"""Clause type definitions for the web front end, from CUAD's own category descriptions (CC BY 4.0).

  python -m scripts.build_clause_definitions     writes web/clauses.json

Each CUAD question ends with "Details: <description>". Merged categories (Affiliate License) keep
both descriptions, each prefixed with its side.
"""

from __future__ import annotations

import json

from src import config
from src.data import load_raw_json
from src.labels import model_label

OUT = config.ROOT_DIR / "web" / "clauses.json"
SOURCE = "CUAD v1 category descriptions (Hendrycks et al., 2021), CC BY 4.0"


def definitions(raw: dict, label_order: list[str]) -> dict[str, str]:
    parts: dict[str, list[tuple[str, str]]] = {}
    for qa in raw["data"][0]["paragraphs"][0]["qas"]:
        category = qa["id"].rsplit("__", 1)[1]
        label = model_label(category)
        if label in label_order and "Details:" in qa["question"]:
            detail = " ".join(qa["question"].split("Details:", 1)[1].split())
            parts.setdefault(label, []).append((category, detail))
    missing = sorted(set(label_order) - set(parts))
    if missing:
        raise SystemExit(f"no CUAD description for {missing}")
    return {label: (parts[label][0][1] if len(parts[label]) == 1 else
                    " ".join(f"{c.rsplit('-', 1)[1]}: {d}" for c, d in sorted(parts[label])))
            for label in label_order}


def main() -> None:
    label_order = json.loads((config.BASELINE_DIR / "labels.json").read_text())["label_order"]
    out = {"source": SOURCE, "label_order": label_order, "definitions": definitions(load_raw_json(), label_order)}
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(label_order)} definitions to {OUT}")


if __name__ == "__main__":
    main()
