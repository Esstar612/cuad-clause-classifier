"""Tuned legal-BERT successor (Step 6c) on the tiny local BERT from test_transformer: CPU only, no downloads."""

import json

import numpy as np
import pandas as pd
import pytest
import torch

from src import config, transformer
from src import transformer_tuned as tuned
from src.fresh import build as fresh_build
from src.predictions import write_predictions
from tests.test_evaluate import _toy_compare_setup
from tests.test_transformer import LABELS, _Y, world  # noqa: F401  (world is a fixture)

RUNS = tuple(config.TUNED_RUNS)


@pytest.fixture
def grid(world, monkeypatch):  # noqa: F811
    root, seg = world
    seg = seg.copy()
    train_rows = seg.index[seg["split"] == "train"]
    for i, idx in enumerate(train_rows):  # every label gets a train positive, so weights are finite
        seg.at[idx, "labels"] = [LABELS[j] for j in range(33) if j % len(train_rows) == i]
    monkeypatch.setattr(transformer, "load_data", lambda: (seg, None, None, LABELS))
    for name, value in (("TUNED_DIR", root / "tuned"), ("TUNED_EPOCHS", 2),
                        ("TUNED_CANDIDATE_PREDICTIONS_DIR", root / "pred" / "transformer-tuned-candidates")):
        monkeypatch.setattr(config, name, value)
    return root, seg


def _train_all(runs=RUNS):
    for r in runs:
        tuned.train(r, restart=False)


def _fail_after_first_epoch(monkeypatch):
    real = transformer.train_model

    def fail(model, tok, texts, Y, epochs, lr=None, pos_weight=None, on_epoch_end=None):
        real(model, tok, texts, Y, 1, lr=lr, pos_weight=pos_weight, on_epoch_end=on_epoch_end)
        raise transformer.FailedRun({"epoch": 2, "batch_start": 0, "loss": float("nan")})
    monkeypatch.setattr(transformer, "train_model", fail)


def test_train_model_pos_weight_lr_and_epoch_callback(grid, monkeypatch):
    _, seg = grid
    tr = seg[seg["split"] == "train"]
    Y = _Y(tr)

    def losses(**kw):
        tok, model = transformer.load_encoder("bert", 33)
        return [r["mean_loss"] for r in transformer.train_model(model, tok, tr["text"], Y, 2, **kw)]

    plain = losses()
    assert np.allclose(plain, losses(pos_weight=np.ones(33)), rtol=1e-5)
    assert not np.allclose(plain, losses(pos_weight=np.full(33, 5.0)))
    seen, calls = [], []
    real = torch.optim.AdamW
    monkeypatch.setattr(transformer.torch.optim, "AdamW", lambda params, lr, **kw: seen.append(lr) or real(params, lr=lr, **kw))
    losses(lr=5e-5, on_epoch_end=lambda e, m: calls.append(e))
    assert seen == [5e-5] and calls == [1, 2]


def test_positive_weights_formula_and_refusal():
    Y = np.array([[1, 0], [0, 1], [0, 0], [0, 0]])
    assert np.allclose(tuned.positive_weights(Y, ["A", "B"]), [np.sqrt(3), np.sqrt(3)])
    with pytest.raises(SystemExit, match=r"no train positives for \['B'\]"):
        tuned.positive_weights(np.array([[1, 0], [0, 0]]), ["A", "B"])


def test_model_version_root_is_backward_compatible(grid):
    root, _ = grid
    for d, text in ((root / "transformer" / "x", "a"), (root / "tuned" / "x", "b")):
        d.mkdir(parents=True)
        (d / "config.json").write_text(text)
    assert transformer.model_version("x") == transformer.model_version("x", config.TRANSFORMER_DIR)
    assert transformer.model_version("x", config.TUNED_DIR) != transformer.model_version("x")


def test_train_writes_checkpoints_markers_and_uses_train_rows_only(grid, monkeypatch):
    root, seg = grid
    seen = []
    real = transformer.train_model
    monkeypatch.setattr(transformer, "train_model",
                        lambda m, t, texts, *a, **k: seen.extend(list(texts)) or real(m, t, texts, *a, **k))
    tuned.train("w-lr5e-5", restart=False)
    d = root / "tuned" / "w-lr5e-5"
    assert set(seen) <= set(seg.loc[seg["split"] == "train", "text"])
    for e in (1, 2):
        assert {"model.safetensors", "config.json", "tokenizer.json"} <= {p.name for p in (d / f"epoch-{e}").iterdir()}
    t = json.loads((d / "trained.json").read_text())
    assert t["recipe"]["TRANSFORMER_LR"] == 5e-5 and t["recipe"]["pos_weight"] is True and len(t["pos_weight"]) == 33
    assert (d / "train_log.csv").exists() and not (root / "pred").exists()
    with pytest.raises(SystemExit, match="already trained"):
        tuned.train("w-lr5e-5", restart=False)

    tuned.train("u-lr2e-5", restart=False)
    assert json.loads((root / "tuned" / "u-lr2e-5" / "trained.json").read_text())["pos_weight"] is None

    c = root / "tuned" / "u-lr5e-5"
    (c / "epoch-7").mkdir(parents=True)
    (c / "train_started.json").write_text("{}")
    with pytest.raises(SystemExit, match="did not finish"):
        tuned.train("u-lr5e-5", restart=False)
    tuned.train("u-lr5e-5", restart=True)
    assert not (c / "epoch-7").exists() and (c / "trained.json").exists()

    _fail_after_first_epoch(monkeypatch)
    with pytest.raises(SystemExit, match="contributes no candidates"):
        tuned.train("w-lr2e-5", restart=False)
    with pytest.raises(SystemExit, match="never retried"):
        tuned.train("w-lr2e-5", restart=True)


def test_validate_waits_for_every_run_and_excludes_a_failed_run(grid, monkeypatch):
    root, _ = grid
    with pytest.raises(SystemExit, match="neither trained nor failed"):
        tuned.validate()
    _train_all(RUNS[:3])
    with monkeypatch.context() as m:
        _fail_after_first_epoch(m)
        with pytest.raises(SystemExit, match="contributes no candidates"):
            tuned.train(RUNS[3], restart=False)
    failed = root / "tuned" / RUNS[3]
    assert (failed / "epoch-1" / "model.safetensors").exists()

    trained = root / "tuned" / RUNS[0] / "trained.json"
    original = trained.read_text()
    trained.write_text(json.dumps({**json.loads(original), "seed": 7}))
    with pytest.raises(SystemExit, match="differ from the trained recipe"):
        tuned.validate()
    trained.write_text(json.dumps({**json.loads(original), "source": {"hub_id": "toy/x", "revision": "old"}}))
    with pytest.raises(SystemExit, match="current pinned source"):
        tuned.validate()
    trained.write_text(original)

    tuned.validate()
    for key in tuned.candidates(list(RUNS[:3])):
        assert {"run.json", "thresholds.json", "labels.json"} <= {p.name for p in (root / "tuned" / key).iterdir()}
    assert not (failed / "epoch-1" / "run.json").exists()
    cands = {p.name for p in config.TUNED_CANDIDATE_PREDICTIONS_DIR.iterdir()}
    assert len(cands) == 6 and not any(n.startswith(RUNS[3]) for n in cands)
    assert not any(p.suffix == ".parquet" for p in (root / "pred").iterdir())

    first = root / "tuned" / tuned.candidates(list(RUNS[:3]))[0] / "run.json"
    stamp = first.read_text()
    tuned.validate()
    assert first.read_text() == stamp


def test_validate_refuses_when_every_run_failed(grid, monkeypatch):
    _fail_after_first_epoch(monkeypatch)
    for r in RUNS:
        with pytest.raises(SystemExit):
            tuned.train(r, restart=False)
    with pytest.raises(SystemExit, match="every run failed"):
        tuned.validate()


def test_choose_macro_ap_then_macro_f1_then_simpler():
    def rows(*r):
        return pd.DataFrame([dict(zip(("candidate", "epoch", "pos_weight", "lr", "macro_ap", "macro_f1"), x))
                             for x in r])
    assert tuned.choose(rows(("a", 1, False, 2e-5, 0.60, 0.9), ("b", 1, False, 2e-5, 0.50, 0.1))) == "a"
    assert tuned.choose(rows(("a", 1, False, 2e-5, 0.600, 0.4), ("b", 1, False, 2e-5, 0.597, 0.5))) == "b"
    assert tuned.choose(rows(("a", 3, False, 2e-5, 0.6, 0.5), ("b", 2, True, 5e-5, 0.6, 0.5))) == "b"
    assert tuned.choose(rows(("a", 2, True, 2e-5, 0.6, 0.5), ("b", 2, False, 5e-5, 0.6, 0.5))) == "b"
    assert tuned.choose(rows(("a", 2, False, 5e-5, 0.6, 0.5), ("b", 2, False, 2e-5, 0.6, 0.5))) == "b"


def test_select_and_heldout_end_to_end_with_guards(grid, monkeypatch):
    root, seg = grid
    _train_all()
    tuned.validate()
    pred = root / "pred"
    six_a = {}
    for split in ("test", "shift"):
        (pred / f"transformer_{split}.parquet").write_bytes(split.encode())
        six_a[split] = (pred / f"transformer_{split}.parquet").read_bytes()

    relabeled = seg.copy()
    first_val = relabeled.index[relabeled["split"] == "val"][0]
    relabeled.at[first_val, "labels"] = [] if relabeled.at[first_val, "labels"] else [LABELS[0]]
    with monkeypatch.context() as m:
        m.setattr(transformer, "load_data", lambda: (relabeled, None, None, LABELS))
        with pytest.raises(SystemExit, match="segments and labels"):
            tuned.select()
    with monkeypatch.context() as m:
        m.setattr(config, "TRANSFORMER_MAX_TOKENS", 16)
        with pytest.raises(SystemExit, match="differ from the trained recipe"):
            tuned.select()

    tuned.select()
    selected = json.loads((root / "tuned" / "selected.json").read_text())
    winner = selected["candidate"]
    for key in (winner, next(k for k in tuned.candidates(list(RUNS)) if k != winner)):
        path = tuned._candidate_predictions(key)
        good = path.read_bytes()
        write_predictions(pd.read_parquet(path).assign(model_version="x|stale"), path, LABELS)
        with pytest.raises(SystemExit, match=f"{key}: validation predictions are not from the validated"):
            tuned.select()
        path.write_bytes(good)
    tuned.select()
    assert pd.read_parquet(pred / "transformer-tuned_val.parquet")["model_name"].eq("transformer-tuned").all()
    assert len(selected["table"]) == len(RUNS) * config.TUNED_EPOCHS

    loaded = []
    real = tuned.AutoModelForSequenceClassification.from_pretrained
    monkeypatch.setattr(tuned.AutoModelForSequenceClassification, "from_pretrained",
                        lambda d, *a, **k: loaded.append(str(d)) or real(d, *a, **k))
    tuned.heldout(force=False)
    assert loaded == [str(root / "tuned" / winner)]
    for split in ("test", "shift"):
        df = pd.read_parquet(pred / f"transformer-tuned_{split}.parquet")
        assert df["model_name"].eq("transformer-tuned").all() and (df["split"] == split).all()
        assert (pred / f"transformer_{split}.parquet").read_bytes() == six_a[split]
    with pytest.raises(SystemExit, match="already evaluated"):
        tuned.heldout(force=False)
    held = {p: p.read_bytes() for p in [*pred.glob("transformer*_*.parquet"), root / "tuned" / "heldout_run.json"]}
    monkeypatch.setattr(fresh_build, "load_fresh_segments",
                        lambda: seg[seg["split"] == "test"].assign(split="fresh").reset_index(drop=True))
    tuned.heldout(force=False, fresh=True)
    assert (pd.read_parquet(pred / "transformer-tuned_fresh.parquet")["split"] == "fresh").all()
    assert held == {p: p.read_bytes() for p in held}
    with pytest.raises(SystemExit, match="fresh set already evaluated"):
        tuned.heldout(force=False, fresh=True)

    labels = root / "tuned" / winner / "labels.json"
    saved = labels.read_text()
    labels.write_text(json.dumps({"label_order": LABELS[::-1], "pooled": []}))
    with pytest.raises(SystemExit, match="changed since"):
        tuned.select()
    with pytest.raises(SystemExit, match="changed since selection"):
        tuned.heldout(force=True)
    labels.write_text(saved)
    monkeypatch.setattr(transformer, "load_data", lambda: (seg, None, None, LABELS[::-1]))
    with pytest.raises(SystemExit, match="Label order differs"):
        tuned.heldout(force=True)


def test_sensitivity_rows_only_for_listed_families(tmp_path, monkeypatch):
    evaluate = _toy_compare_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "COMPARE_FAMILIES", {"toy": (("ma", "mb"), ("ma", "ma"))})

    evaluate.compare("ma", "mb")
    plain = json.loads((tmp_path / "eval" / "compare_ma_vs_mb.json").read_text())
    assert "sensitivity_family_size" not in plain
    assert not any("sensitivity_level" in d for d in plain["differences"].values())

    monkeypatch.setattr(config, "COMPARE_SENSITIVITY", {"toy": 24})
    evaluate.compare("ma", "mb")
    out = json.loads((tmp_path / "eval" / "compare_ma_vs_mb.json").read_text())
    rows = [d for d in out["differences"].values() if d.get("primary")]
    assert out["sensitivity_family_size"] == 24 and len(rows) == 4
    assert all(d["sensitivity_level"] == pytest.approx(1 - 0.05 / 24) for d in rows)
    assert all(d["sensitivity_ci_low"] <= d["adjusted_ci_low"] and d["sensitivity_ci_high"] >= d["adjusted_ci_high"]
               for d in rows)
    assert not any("sensitivity_level" in d for d in out["differences"].values() if not d.get("primary"))
    assert {k: v for k, v in out.items() if k != "sensitivity_family_size"}.keys() == plain.keys()

    evaluate.compare("ma", "ma")
    same = json.loads((tmp_path / "eval" / "compare_ma_vs_ma.json").read_text())
    assert all(d.get(k, 0) == 0 for d in same["differences"].values()
               for k in ("sensitivity_ci_low", "sensitivity_ci_high"))
    assert any("sensitivity_level" in d for d in same["differences"].values())
