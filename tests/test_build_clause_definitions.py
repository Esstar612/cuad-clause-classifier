import json

import pytest

from src import config

from scripts.build_clause_definitions import definitions


def _qa(category, detail):
    q = f'Highlight the parts (if any) of this contract related to "{category}". Details: {detail}'
    return {"id": f"DOC__{category}", "question": q}


def _raw(*qas):
    return {"data": [{"paragraphs": [{"qas": list(qas)}]}]}


def test_definitions_take_the_cuad_details_and_merge_affiliate_license():
    raw = _raw(_qa("Governing Law", "Which  state's law\n governs?"), _qa("Document Name", "The name"),
               _qa("Affiliate License-Licensor", "Licensor side."), _qa("Affiliate License-Licensee", "Licensee side."))
    out = definitions(raw, ["Affiliate License", "Governing Law"])
    assert out["Governing Law"] == "Which state's law governs?"
    assert out["Affiliate License"] == "Licensee: Licensee side. Licensor: Licensor side."
    assert set(out) == {"Affiliate License", "Governing Law"}


def test_a_label_without_a_description_is_refused():
    with pytest.raises(SystemExit, match="no CUAD description"):
        definitions(_raw(_qa("Governing Law", "x")), ["Governing Law", "Insurance"])


def test_committed_definitions_match_the_served_label_order():
    labels = config.BASELINE_DIR / "labels.json"
    if not labels.exists():
        pytest.skip("needs the local baseline labels")
    web = json.loads((config.ROOT_DIR / "web" / "clauses.json").read_text())
    assert web["label_order"] == json.loads(labels.read_text())["label_order"]
    assert set(web["definitions"]) == set(web["label_order"]) and all(web["definitions"].values())
