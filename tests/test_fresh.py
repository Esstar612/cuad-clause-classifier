"""Step 9a fresh set: sourcing, conversion, labeling tool offsets, label build, agreement. Offline, synthetic."""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import config
from src.bootstrap import resample_weights
from src.fresh import build, source
from src.fresh import config as F
from src.fresh.agreement import cohen_kappa, presence_agreement, span_f1
from src.fresh.edgar import Edgar, EdgarError
from src.fresh.text import html_to_text, sha256

TEST_COUNTS = {"License": 7, "Service": 5, "Supply": 3, "Agency": 2, "Affiliate": 2}


def _words(seed: int, n: int) -> str:
    rng = np.random.default_rng(seed)
    words = [f"w{x}" for x in rng.integers(0, 10**9, size=n)]
    return " ".join(w + ("." if i % 20 == 19 else "") for i, w in enumerate(words))  # 20-word sentences


def _candidates(per_type: dict[str, int]) -> pd.DataFrame:
    rows = [{"accession": f"0000-26-{t[:3]}{i:03d}", "file_name": f"ex10_{i}.htm", "cik": "123", "file_date": "2026-05-01",
             "file_type": "EX-10.1", "file_description": f"{t} agreement", "form": "8-K", "type": t, "type_status": "one"}
            for t, n in per_type.items() for i in range(n)]
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- allocation and draw

def test_allocate_sums_breaks_ties_and_moves_shortfall():
    full = {t: 100 for t in TEST_COUNTS}
    a = source.allocate(TEST_COUNTS, 10, full)
    assert sum(a.values()) == 10 and a == source.allocate(dict(reversed(TEST_COUNTS.items())), 10, full)
    # quotas 3.684, 2.632, 1.579, 1.053, 1.053: floors 3, 2, 1, 1, 1; remainders .684 (License), .632 (Service)
    assert a == {"License": 4, "Service": 3, "Supply": 1, "Agency": 1, "Affiliate": 1}
    short = source.allocate(TEST_COUNTS, 10, {**full, "License": 2})
    assert short["License"] == 2 and sum(short.values()) == 10
    with pytest.raises(SystemExit, match="not enough"):
        source.allocate(TEST_COUNTS, 10, {t: 1 for t in TEST_COUNTS})
    tie = source.allocate({"B": 1, "A": 1}, 1, {"A": 5, "B": 5})
    assert tie == {"A": 1, "B": 0}


def test_draw_is_order_free_and_reallocates_without_revisiting():
    cands = _candidates({t: 6 for t in TEST_COUNTS})
    seen = []

    def check(row, picked):
        seen.append((row["accession"], row["file_name"]))
        bad = row["type"] == "License" and not row["accession"].endswith(("000", "001"))
        return ("too_short", {"chars": 10}) if bad else (None, {"chars": 9000})

    picked, log = source.draw(cands, TEST_COUNTS, 10, check)
    assert len(picked) == 10 and (picked["type"] == "License").sum() == 2
    assert len(seen) == len(set(seen)) == len(log)
    assert (pd.DataFrame(log)["reason"] == "too_short").sum() == 4
    again, _ = source.draw(cands.sample(frac=1, random_state=1), TEST_COUNTS, 10,
                           lambda r, p: check(r, p))
    assert again[["accession", "file_name"]].equals(picked[["accession", "file_name"]])


# ----------------------------------------------------------------------------- frame

def test_classify_one_none_ambiguous():
    assert source.classify("EXCLUSIVE LICENSE AGREEMENT") == ("License", "one")
    assert source.classify("EX-10.1") == (None, "none")
    assert source.classify(None) == (None, "none")
    assert source.classify("Hosting Services Agreement") == ("Hosting", "one")
    assert source.classify("Master Services Agreement") == ("Service", "one")
    assert source.classify("Co-Branding and Marketing Agreement") == (None, "ambiguous")


def test_month_windows_cover_the_range():
    assert source.month_windows("2026-04-15", "2026-06-02") == [
        ("2026-04-15", "2026-04-30"), ("2026-05-01", "2026-05-31"), ("2026-06-01", "2026-06-02")]


class FakeSearch:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def search(self, phrase, start, end, offset=0):
        self.calls.append((phrase, start, offset))
        return self.pages(phrase, start, offset)


def test_list_frame_keeps_ex10_dedupes_and_reports(monkeypatch):
    monkeypatch.setattr(F, "TYPES", {"License": ("license agreement", ("license agreement",)),
                                     "Supply": ("supply agreement", ("supply agreement",))})

    def pages(phrase, start, offset):
        if offset:
            return {"total": {"value": 3, "relation": "eq"}, "hits": []}
        hits = [{"_id": "0001-26-1:a.htm", "_source": {"ciks": ["0000123"], "file_type": "EX-10.1",
                                                        "file_description": "License Agreement"}},
                {"_id": "0001-26-2:b.htm", "_source": {"ciks": ["7"], "file_type": "EX-99",
                                                        "file_description": "press release"}},
                {"_id": "0001-26-3:c.htm", "_source": {"ciks": ["8"], "file_type": "EX-10.2",
                                                        "file_description": None}}]
        return {"total": {"value": 3, "relation": "eq"}, "hits": hits}

    search = FakeSearch(pages)
    frame, report = source.list_frame(search, "2026-04-01", "2026-04-30")
    assert [c[2] for c in search.calls] == [0, 0]
    assert list(frame["accession"]) == ["0001-26-1", "0001-26-3"]
    assert report["ex10_by_status"] == {"one": 1, "none": 1, "ambiguous": 0}
    assert report["in_frame_by_type"] == {"License": 1} and report["truncated_queries"] == []


# ----------------------------------------------------------------------------- exclusions

def test_containment_is_symmetric_in_effect():
    small = _words(1, 400)
    big = small + " " + _words(2, 4000)
    assert source.containment(small, big) == pytest.approx(1.0)
    assert source.containment(big, small) == pytest.approx(1.0)
    assert source.containment(_words(3, 400), _words(4, 400)) == 0.0
    idx = source.ShingleIndex({0: small, 1: _words(5, 400)})
    assert idx.max_containment(big) == pytest.approx(1.0)
    assert idx.max_containment(_words(6, 400)) == 0.0


def test_rule_helpers():
    assert source.is_amendment("First Amendment to License Agreement", "")
    assert not source.is_amendment("Amended and Restated License Agreement", "amendment")
    assert source.is_amendment(None, "This side letter ...")
    assert not source.is_amendment("License Agreement", "x" * 600 + " amendment")
    assert source.blank_markers("By: ______ Name: [Name of Party] Date: [●]") == 3
    assert source.redaction_rate("a" * 1997 + "[***]") == pytest.approx(1000 / 2002)
    assert source.redaction_rate("[***] *** [*]") > 0 and len(F.REDACTION.findall("[***] *** [*]")) == 3
    s = source.prior_sentences("Short one. " + " ".join(["alpha"] * 20) + ". " + " ".join(["beta"] * 41) + ".", n=3)
    assert s == [" ".join(["alpha"] * 20)]


class FakeEdgar:
    def __init__(self, docs):
        self.docs = docs

    def document(self, cik, accession, file_name):
        doc = self.docs[accession]
        if isinstance(doc, Exception):
            raise doc
        return doc.encode()


def _html(text):
    return "<html><body>" + "".join(f"<p>{p}</p>" for p in text.split("\n")) + "</body></html>"


@pytest.fixture
def checker(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "RAW_DIR", tmp_path / "raw")
    cuad_text = _words(10, 3000)
    long_ok = _words(11, 1500)
    docs = {
        "ok": _html(long_ok), "pdf": "", "short": _html(_words(12, 50)),
        "long": _html(_words(13, 60_000)),
        "amend": _html("FIRST AMENDMENT. " + _words(14, 1500)),
        "form": _html("______ ______ [Name of Licensee] " + _words(15, 1500)),
        "redact": _html(" ".join([_words(16, 1500)] + ["[***]"] * 200)),
        "cuad": _html(cuad_text[:20_000]),
        "dup": _html(long_ok), "fetch": EdgarError("HTTP 404"), "efts": _html(_words(17, 1500)),
        "prior": _html(_words(18, 1500)), "script": "<p>" + _words(19, 1500) + "<script>var x;",
    }
    failing = set(source.prior_sentences(html_to_text(docs["efts"])))
    seen_before = set(source.prior_sentences(html_to_text(docs["prior"])))
    assert len(failing) == len(seen_before) == F.PRIOR_SENTENCES

    def prior_hits(sentence):
        if sentence in failing:
            raise EdgarError("HTTP 500")
        return 5 if sentence in seen_before else 0

    check = source.make_check(FakeEdgar(docs), source.ShingleIndex({0: cuad_text}), {}, prior_hits)

    def run(acc, picked=(), file_name="x.htm"):
        return check(pd.Series({"accession": acc, "file_name": file_name, "cik": "1",
                                "file_description": "License Agreement"}), list(picked))
    return run


def test_every_exclusion_and_a_text_free_log(checker):
    assert checker("pdf", file_name="x.pdf")[0] == "not_html"
    expected = {"short": "too_short", "long": "too_long", "amend": "amendment", "form": "form_or_template",
                "redact": "redacted", "cuad": "cuad_overlap", "fetch": "fetch_error", "efts": "efts_error",
                "prior": "prior_appearance", "script": "conversion_error"}
    log = []
    for acc, reason in expected.items():
        got, numbers = checker(acc)
        assert got == reason, acc
        log.append({"type": "License", "accession": acc, "file_name": "x.htm", "reason": got, **numbers})
    assert checker("ok")[0] is None
    got, numbers = checker("dup", picked=[{"accession": "ok", "file_name": "x.htm"}])
    assert got == "duplicate" and numbers["duplicate_containment"] == 1.0
    log.append({"type": "License", "accession": "dup", "file_name": "x.htm", "reason": got, **numbers})
    for row in log:
        for k, v in row.items():
            assert k in ("type", "accession", "file_name", "reason") or isinstance(v, (int, float)), (k, v)


def test_edgar_client_paces_retries_and_needs_a_user_agent(monkeypatch):
    import httpx

    calls, sleeps, clock = [], [], iter(range(1000))

    def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200, json={"hits": {"total": {"value": 0}, "hits": []}})

    e = Edgar(httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append,
              clock=lambda: next(clock) * 0.01)
    assert e.search("license agreement", "2026-04-01", "2026-04-30")["hits"] == []
    assert len(calls) == 2 and calls[0].url.params["q"] == '"license agreement"' and sleeps[0] == 1
    assert any(0 < s <= F.EDGAR_MIN_INTERVAL_S for s in sleeps[1:])
    gone = Edgar(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))), sleep=lambda s: None)
    with pytest.raises(EdgarError, match="404"):
        gone.document("0000123", "0001-26-1", "a.htm")
    monkeypatch.setattr("src.fresh.edgar.load_dotenv", lambda: None)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(SystemExit, match="SEC_USER_AGENT"):
        Edgar()


# ----------------------------------------------------------------------------- text and tool

def test_conversion_is_deterministic_and_separates_cells_and_items():
    html = ("<table><tr><td>Name</td><td>Address</td></tr></table><ul><li>one</li><li>two</li></ul>"
            "<p>A&nbsp;&amp;&nbsp;B\r\n  spaced</p><br/><style>p{}</style><script>x()</script><div>end</div>")
    text = html_to_text(html)
    assert text == html_to_text(html) == "Name\n\nAddress\n\none\n\ntwo\n\nA & B\nspaced\n\nend\n"
    with pytest.raises(ValueError, match="unclosed"):
        html_to_text("<p>a</p><script>never closed")
    assert html_to_text("<p>a</p></script><p>b</p>") == "a\n\nb\n"


def test_labeler_offsets_with_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node not installed")
    out = subprocess.run([node, str(Path(__file__).parent / "labeler_offsets.js")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


# ----------------------------------------------------------------------------- label build

TEXT = ("1. Governing Law. This agreement is governed by the laws of Delaware without regard to conflicts.\n\n"
        "2. Term. The initial term ends on December 31, 2030 unless terminated earlier by either party.\n\n"
        "3. Escrow. Licensor shall deposit the source code with an escrow agent within thirty days.\n")


def _contract(text=TEXT):
    return pd.Series({"contract_id": 1000, "contract_type": "License", "text_sha256": sha256(text)})


def _export(spans, text=TEXT):
    marked = {s["category"] for s in spans}
    return {"contract_id": 1000, "text_sha256": sha256(text), "spans": spans,
            "checklist": {c: "marked" if c in marked else "not present" for c in build.categories_36()}}


def test_categories_are_the_33_scored_plus_3_rare():
    assert len(build.categories_36()) == 36 and "Affiliate License" in build.categories_36()
    assert {"Source Code Escrow", "Price Restrictions", "Unlimited/All-You-Can-Eat-License"} <= set(build.categories_36())


def test_build_round_trip_at_frozen_settings():
    gl = TEXT.index("1."), TEXT.index("\n\n2.")
    escrow = TEXT.index("3."), len(TEXT) - 1
    spans = [{"category": "Governing Law", "start": gl[0], "end": gl[1]},
             {"category": "Source Code Escrow", "start": escrow[0], "end": escrow[1]}]
    df = build.contract_segments(TEXT, _export(spans), _contract())
    assert list(df.columns) == build.COLUMNS and (df["split"] == "fresh").all()
    assert df["segment_id"].tolist() == [f"1000_{i}" for i in range(len(df))]
    assert df["contract_id"].dtype.kind == "i"
    by_text = {r.text.split(".")[0]: r for r in df.itertuples()}
    assert list(by_text["1"].labels) == ["Governing Law"]
    assert list(by_text["2"].labels) == [] and not by_text["2"].exclude
    assert by_text["3"].exclude and list(by_text["3"].raw_categories) == ["Source Code Escrow"]


@pytest.mark.parametrize("mutate,match", [
    (lambda e: e.update(text_sha256="0" * 64), "different text"),
    (lambda e: e["checklist"].pop("Insurance"), "checklist incomplete"),
    (lambda e: e["checklist"].update(Insurance="maybe"), "checklist incomplete"),
    (lambda e: e["spans"].append({"category": "Not A Type", "start": 0, "end": 5}), "bad span"),
    (lambda e: e["spans"].append({"category": "Insurance", "start": 0.0, "end": 5}), "bad span"),
    (lambda e: e["spans"].append({"category": "Insurance", "start": True, "end": 5}), "bad span"),
    (lambda e: e["spans"].append({"category": "Insurance", "start": 5, "end": 5}), "bad span"),
    (lambda e: e["spans"].append({"category": "Insurance", "start": 0, "end": len(TEXT) + 1}), "bad span"),
    (lambda e: e["checklist"].update(Insurance="marked"), "spans disagree"),
    (lambda e: e["checklist"].update({"Governing Law": "not present"}), "spans disagree"),
])
def test_build_refuses_bad_exports(mutate, match):
    export = _export([{"category": "Governing Law", "start": 0, "end": 40}])
    mutate(export)
    with pytest.raises(SystemExit, match=match):
        build.contract_segments(TEXT, export, _contract())


def test_contracts_per_label_maps_and_skips_rare():
    exports = {1: {"spans": [{"category": "Affiliate License"}, {"category": "Source Code Escrow"}]},
               2: {"spans": [{"category": "Affiliate License"}, {"category": "Affiliate License"}]}}
    assert build.contracts_per_label(exports) == {"Affiliate License": 2}


# ----------------------------------------------------------------------------- agreement and bootstrap

def test_span_f1_lenient_strict_and_empty():
    assert np.isnan(span_f1([], []))
    assert span_f1([(0, 10)], []) == 0.0
    assert span_f1([(0, 10)], [(0, 10)]) == 1.0
    assert span_f1([(0, 10)], [(0, 100)]) == 1.0           # covers all of the short span
    assert span_f1([(0, 10)], [(0, 100)], strict=True) == 0.0
    assert span_f1([(0, 10), (20, 30)], [(0, 10)]) == pytest.approx(2 / 3)
    assert span_f1([(0, 10), (2, 12)], [(0, 12)]) == pytest.approx(2 / 3)   # one to one


def test_kappa_and_presence_by_hand():
    x = np.array([1, 1, 0, 0, 1, 0, 0, 0, 0, 0])
    y = np.array([1, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    # po = 0.8; pe = 0.3 * 0.3 + 0.7 * 0.7 = 0.58; kappa = 0.22 / 0.42
    assert cohen_kappa(x, y) == pytest.approx(0.22 / 0.42)
    assert np.isnan(cohen_kappa(np.zeros(4), np.zeros(4)))
    assert cohen_kappa(np.zeros(4), np.array([0, 1, 0, 0])) == 0.0
    assert presence_agreement({"A", "B"}, {"A"}, ["A", "B", "C", "D"]) == 0.75


def test_resample_weights_plain_option_and_unchanged_default():
    c = pd.DataFrame({"contract_id": [5, 1, 3, 2], "contract_type": ["X", "Y", "X", "Y"]})
    ids, w = resample_weights(c, "test", n_resamples=50)
    ids_t, w_t = resample_weights(c, "test", n_resamples=50, stratify=True)
    assert np.array_equal(ids, ids_t) and np.array_equal(w, w_t)
    assert (w[:, ids_t.tolist().index(5)] + w[:, ids_t.tolist().index(3)] == 2).all()
    pids, pw = resample_weights(c, "fresh", n_resamples=200, stratify=False)
    assert pids.tolist() == [1, 2, 3, 5] and (pw.sum(axis=1) == 4).all()
    ref = resample_weights(c.assign(contract_type="all"), "fresh", n_resamples=200)
    assert np.array_equal(pw, ref[1])
    assert not (pw[:, [2, 3]].sum(axis=1) == 2).all()


# ----------------------------------------------------------------------------- fresh runs stay separate

def test_heldout_sets_reads_only_the_fresh_file(tmp_path, monkeypatch):
    seg = pd.DataFrame({"segment_id": ["1000_0", "1000_1"], "exclude": [False, True], "labels": [["A"], []]})
    monkeypatch.setattr(F, "SEGMENTS", tmp_path / "fresh_segments.parquet")
    seg.to_parquet(F.SEGMENTS)
    sets = build.heldout_sets(pd.DataFrame({"split": ["test"]}), fresh=True)
    assert [k for k, _ in sets] == ["fresh"] and sets[0][1]["segment_id"].tolist() == ["1000_0"]
    assert [k for k, _ in build.heldout_sets(pd.DataFrame({"split": ["test", "shift", "val"]}), False)] == [
        "test", "shift"]


def test_baseline_fresh_refuses_an_existing_marker(tmp_path, monkeypatch):
    from src import baseline
    marker = tmp_path / "fresh_run.json"
    marker.write_text("{}")
    monkeypatch.setitem(baseline.ARTIFACTS, "fresh_run.json", marker)
    with pytest.raises(SystemExit, match="fresh set already evaluated.*reruns-fresh"):
        baseline.heldout(force=False, fresh=True)


def test_llm_fresh_guard_names_the_fresh_set(tmp_path):
    from src.llm.run import heldout_guard
    marker = tmp_path / "fresh_run.json"
    marker.write_text(json.dumps({"completed_utc": "x"}))
    with pytest.raises(SystemExit, match="fresh set already evaluated.*reruns-fresh"):
        heldout_guard(marker, "abc", force=False, what="fresh")


def test_fresh_config_constants():
    assert config.PER_LABEL_MIN_FRESH_CONTRACTS == 10
    assert F.CONTRACT_ID_START > 509 and F.FRAME_START == "2026-04-01"
    assert set(TEST_COUNTS) <= set(F.TYPES)


def test_evaluate_fresh_scores_rule_f_with_plain_resampling(tmp_path, monkeypatch):
    from src import evaluate
    from src.predictions import to_prediction_frame, write_predictions

    monkeypatch.setattr(config, "PREDICTIONS_DIR", tmp_path / "pred")
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(F, "CONTRACTS", tmp_path / "contracts.parquet")
    monkeypatch.setattr(F, "RULE_F", tmp_path / "rule_f.json")
    labels = ["A", "B"]
    pd.DataFrame({"contract_id": [1000, 1001, 1002], "contract_type": ["License", "License", "Supply"]}).to_parquet(
        F.CONTRACTS)
    F.RULE_F.write_text(json.dumps({"rule_f": ["A"]}))

    def write(cids):
        seg = pd.DataFrame([{"segment_id": f"{c}_{i}", "contract_id": c, "split": "fresh", "start": 0, "end": 1,
                             "labels": labs} for c in cids for i, labs in enumerate((["A"], ["B"], []))])
        y = np.array([["A" in labs, "B" in labs] for labs in seg["labels"]])
        write_predictions(to_prediction_frame(seg, y.astype(float), y, labels, "m", "t", 0.0, 0.0),
                          tmp_path / "pred" / "m_fresh.parquet", labels)

    write([1000, 1001, 1002])
    evaluate.evaluate_fresh("m")
    out = json.loads((tmp_path / "eval" / "m_fresh.json").read_text())
    assert out["method"] == evaluate.FRESH_METHOD and "not stratified" in out["method"]
    assert out["scopes"]["fresh | Rule F"]["n_labels"] == 1 and out["scopes"]["fresh | all"]["n_labels"] == 2
    assert out["scopes"]["fresh | all"]["micro_f1"]["point"] == 1.0
    assert [r["main_table"] for r in out["per_label_fresh"]] == [True, False]
    write([1000, 7])
    with pytest.raises(SystemExit, match="outside the fresh set"):
        evaluate.evaluate_fresh("m")


def test_list_frame_pages_by_hits_returned():
    hits = [{"_id": f"0001-26-{i}:a.htm", "_source": {"ciks": ["1"], "file_type": "EX-10.1",
                                                       "file_description": "Supply Agreement"}} for i in range(25)]
    search = FakeSearch(lambda phrase, start, offset: {"total": {"value": 25, "relation": "eq"},
                                                       "hits": hits[offset:offset + 10]})
    frame, _ = source.list_frame(search, "2026-04-01", "2026-04-30")
    assert len(frame) == 25 and {c[2] for c in search.calls} == {0, 10, 20}


def test_guide_example_is_seeded_and_within_the_interquartile_range():
    from src.fresh.guide import example

    g = pd.DataFrame({"contract_id": range(8), "answer_start": 0,
                      "answer_text": ["x" * n for n in (10, 20, 30, 40, 50, 60, 70, 80)]})
    g["chars"] = g["answer_text"].str.len()
    cid, text = example(g, "Insurance")
    assert (cid, text) == example(g.sample(frac=1, random_state=3), "Insurance")
    assert 27.5 <= len(text) <= 62.5


def test_tool_trial_bundle_takes_a_cuad_train_contract_only(tmp_path, monkeypatch):
    import argparse

    splits = tmp_path / "splits.csv"
    pd.DataFrame({"contract_id": [1, 2], "contract_type": ["License", "Service"], "split": ["train", "val"]}).to_csv(
        splits, index=False)
    monkeypatch.setattr(config, "SPLITS_CSV", splits)
    monkeypatch.setattr(F, "BUNDLE", tmp_path / "bundle.js")
    monkeypatch.setattr("src.data.load_raw_json", lambda: {})
    monkeypatch.setattr("src.data.load_contexts", lambda raw: {1: "train text", 2: "val text"})
    for cid in (2, 7):
        with pytest.raises(SystemExit, match="train contract only"):
            source.cmd_bundle(argparse.Namespace(cuad_train=cid))
    assert not F.BUNDLE.exists()
    source.cmd_bundle(argparse.Namespace(cuad_train=1))
    bundle = json.loads(F.BUNDLE.read_text().removeprefix("window.BUNDLE = ").rstrip().rstrip(";"))
    assert bundle["contracts"] == [{"contract_id": 1, "text": "train text", "text_sha256": sha256("train text")}]
    assert len(bundle["categories"]) == 36
