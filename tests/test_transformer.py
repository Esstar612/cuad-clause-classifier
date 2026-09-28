"""Fine-tuned transformer (Step 6a) on a tiny local BERT: CPU only, no downloads. The real
load_encoder, seeding, training loop, markers, selection rule and held-out guard run on toy files."""

import json

import numpy as np
import pandas as pd
import pytest
import torch
from transformers import BertConfig, BertModel, BertTokenizerFast

from src import config, transformer
from src.predictions import to_prediction_frame, write_predictions

LABELS = [f"L{i:02d}" for i in range(33)]
WORDS = "license grant royalty territory term party agreement notice fee carrier freight service".split()
KEYS = ("legal-bert", "bert", "deberta-v3")


def _tiny_hub(path):
    path.mkdir()
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"] + WORDS
    (path / "vocab.txt").write_text("\n".join(vocab))
    BertTokenizerFast(vocab_file=str(path / "vocab.txt")).save_pretrained(path)
    cfg = BertConfig(vocab_size=len(vocab), hidden_size=32, num_hidden_layers=2, num_attention_heads=2,
                     intermediate_size=37, max_position_embeddings=128, hidden_dropout_prob=0.0,
                     attention_probs_dropout_prob=0.0)
    torch.manual_seed(config.SEED)
    BertModel(cfg).save_pretrained(path)
    return str(path)


def _segments():
    rng = np.random.default_rng(config.SEED)
    rows, cid = [], 0
    for split, n_contracts in (("train", 4), ("val", 6), ("test", 3), ("shift", 3)):
        for c in range(n_contracts):
            cid += 1
            for i in range(4):
                labs = [LABELS[(c + i) % 5]] if i % 2 == 0 else []
                rows.append({"segment_id": f"{cid}_{i}", "contract_id": cid,
                             "contract_type": "License" if c % 2 else "Service", "split": split,
                             "start": 0, "end": 1, "labels": labs,
                             "text": " ".join(rng.choice(WORDS, size=5 + 3 * i))})
    return pd.DataFrame(rows)


@pytest.fixture
def world(tmp_path, monkeypatch):
    hub = _tiny_hub(tmp_path / "hub")
    seg = _segments()
    for name, value in (("TRANSFORMER_DIR", tmp_path / "transformer"), ("PREDICTIONS_DIR", tmp_path / "pred"),
                        ("PROCESSED_DIR", tmp_path / "processed"), ("TRANSFORMER_EPOCHS", 1),
                        ("TRANSFORMER_BATCH_SIZE", 4), ("TRANSFORMER_INFER_BATCH", 5),
                        ("TRANSFORMER_PROBE_SEGMENTS", 6), ("TRANSFORMER_MAX_TOKENS", 32),
                        ("TRANSFORMER_ENCODERS", {k: f"toy/{k}" for k in KEYS}), ("BOOTSTRAP_RESAMPLES", 200)):
        monkeypatch.setattr(config, name, value)
    (tmp_path / "transformer").mkdir()
    (tmp_path / "processed").mkdir()
    (tmp_path / "transformer" / "sources.json").write_text(
        json.dumps({k: {"hub_id": f"toy/{k}", "revision": "r"} for k in KEYS}))
    seg.drop_duplicates("contract_id")[["contract_id", "contract_type"]].to_parquet(
        tmp_path / "processed" / "contracts.parquet")
    monkeypatch.setattr(transformer, "device", lambda: torch.device("cpu"))
    monkeypatch.setattr(transformer, "snapshot_path", lambda key: hub)
    monkeypatch.setattr(transformer, "load_data", lambda: (seg, None, None, LABELS))
    monkeypatch.setattr(transformer, "pooled_labels", lambda *_: LABELS[-5:])
    return tmp_path, seg


def _Y(seg):
    return np.array([[lab in labs for lab in LABELS] for labs in seg["labels"]])


def test_load_encoder_is_seeded_fp32_and_encode_counts_truncation(world):
    _, seg = world
    tok, m1 = transformer.load_encoder("bert", 33)
    _, m2 = transformer.load_encoder("bert", 33)
    assert all(p.dtype == torch.float32 for p in m1.parameters())
    assert torch.equal(m1.classifier.weight, m2.classifier.weight)
    ids, n_trunc = transformer.encode(tok, [" ".join(["license"] * 60), "grant"])
    assert len(ids[0]) == config.TRANSFORMER_MAX_TOKENS and n_trunc == 1


def test_train_model_is_seeded_accumulation_matches_and_nan_fails(world, monkeypatch):
    _, seg = world
    tr = seg[seg["split"] == "train"]
    losses = []
    for acc in (1, 1, 2):
        monkeypatch.setattr(config, "TRANSFORMER_ACCUMULATION", acc)
        tok, model = transformer.load_encoder("bert", 33)
        losses.append([r["mean_loss"] for r in transformer.train_model(model, tok, tr["text"], _Y(tr), 1)])
    assert all(np.isfinite(losses[0])) and losses[0] == losses[1]
    assert np.allclose(losses[0], losses[2], rtol=1e-4)
    tok, model = transformer.load_encoder("bert", 33)
    bad = _Y(tr).astype(float)
    bad[0, 0] = np.nan
    with pytest.raises(transformer.FailedRun):
        transformer.train_model(model, tok, tr["text"], bad, 1)


def test_predict_proba_keeps_input_order(world):
    _, seg = world
    tok, model = transformer.load_encoder("bert", 33)
    texts = seg.loc[seg["split"] == "val", "text"].reset_index(drop=True)
    proba, _, ms = transformer.predict_proba(model, tok, texts)
    single = np.vstack([transformer.predict_proba(model, tok, [t], warm=False)[0] for t in texts])
    assert proba.shape == (len(texts), 33) and ((proba >= 0) & (proba <= 1)).all() and ms > 0
    assert np.allclose(proba, single, atol=1e-5)


def test_probe_trains_only_on_train_segments_and_keeps_no_weights(world, monkeypatch):
    root, seg = world
    seen = []
    real = transformer.train_model
    monkeypatch.setattr(transformer, "train_model",
                        lambda m, t, texts, Y, epochs: seen.extend(list(texts)) or real(m, t, texts, Y, epochs))
    transformer.probe("bert")
    assert set(seen) <= set(seg.loc[seg["split"] == "train", "text"])
    files = {p.name for p in (root / "transformer" / "bert").iterdir()}
    assert files == {"probe.json"}
    assert json.loads((root / "transformer" / "bert" / "probe.json").read_text())["dtype"] == "torch.float32"


def test_train_markers_crash_restart_and_failed_run(world, monkeypatch):
    root, _ = world
    d = root / "transformer" / "bert"
    transformer.train("bert", restart=False)
    assert {"model.safetensors", "config.json", "train_log.csv", "trained.json"} <= {p.name for p in d.iterdir()}
    assert not (root / "pred").exists()
    with pytest.raises(SystemExit, match="already trained"):
        transformer.train("bert", restart=False)

    c = root / "transformer" / "legal-bert"
    c.mkdir()
    (c / "train_started.json").write_text("{}")
    with pytest.raises(SystemExit, match="did not finish"):
        transformer.train("legal-bert", restart=False)
    transformer.train("legal-bert", restart=True)
    assert (c / "trained.json").exists()

    def boom(*_a, **_k):
        raise transformer.FailedRun({"epoch": 1, "batch_start": 0, "loss": float("nan")})
    monkeypatch.setattr(transformer, "train_model", boom)
    with pytest.raises(SystemExit, match="failed run recorded"):
        transformer.train("deberta-v3", restart=False)
    with pytest.raises(SystemExit, match="never retried"):
        transformer.train("deberta-v3", restart=True)


def test_end_to_end_validate_select_heldout_and_guards(world, monkeypatch):
    root, seg = world
    with pytest.raises(SystemExit, match="not trained yet"):
        transformer.validate()
    for k in KEYS:
        transformer.train(k, restart=False)
    trained = root / "transformer" / "deberta-v3" / "trained.json"
    original = trained.read_text()
    trained.write_text(json.dumps({**json.loads(original), "seed": 7}))
    with pytest.raises(SystemExit, match="different recipes or seeds"):
        transformer.validate()
    trained.write_text(original)

    transformer.validate()
    d = root / "transformer" / "bert"
    assert {"run.json", "thresholds.json", "labels.json"} <= {p.name for p in d.iterdir()}
    v = transformer.model_version("bert")
    (d / ".DS_Store").write_text("x")
    assert transformer.model_version("bert") == v

    monkeypatch.setattr(config, "TRANSFORMER_MAX_TOKENS", 16)
    with pytest.raises(SystemExit, match="differ from the trained recipe"):
        transformer.select()
    monkeypatch.setattr(config, "TRANSFORMER_MAX_TOKENS", 32)
    with monkeypatch.context() as m:
        m.setattr(config, "SEED", config.SEED + 1)
        with pytest.raises(SystemExit, match="differ from the trained recipe"):
            transformer.select()
    relabeled = seg.copy()
    first_val = relabeled.index[relabeled["split"] == "val"][0]
    relabeled.at[first_val, "labels"] = [] if relabeled.at[first_val, "labels"] else [LABELS[0]]
    with monkeypatch.context() as m:
        m.setattr(transformer, "load_data", lambda: (relabeled, None, None, LABELS))
        with pytest.raises(SystemExit, match="segments and labels"):
            transformer.select()
    stale = root / "pred" / "transformer-bert_val.parquet"
    good = stale.read_bytes()
    df = pd.read_parquet(stale)
    write_predictions(df.assign(model_version="bert|stale"), stale, LABELS)
    with pytest.raises(SystemExit, match="not from the validated model"):
        transformer.select()
    stale.write_bytes(good)
    transformer.select()
    selected = json.loads((root / "transformer" / "selected.json").read_text())
    assert selected["encoder"] in KEYS and set(selected["domain_comparison"]) >= {"macro_f1", "micro_f1"}
    assert pd.read_parquet(root / "pred" / "transformer_val.parquet")["model_name"].eq("transformer").all()

    transformer.heldout(force=False)
    assert (root / "pred" / "transformer_test.parquet").exists() and (root / "pred" / "transformer_shift.parquet").exists()
    with pytest.raises(SystemExit, match="already evaluated"):
        transformer.heldout(force=False)
    sel = root / "transformer" / selected["encoder"]
    labels = sel / "labels.json"
    saved = labels.read_text()
    labels.write_text(json.dumps({"label_order": LABELS[::-1], "pooled": []}))
    with pytest.raises(SystemExit, match="changed since selection"):
        transformer.heldout(force=True)
    labels.write_text(saved)
    monkeypatch.setattr(transformer, "load_data", lambda: (seg, None, None, LABELS[::-1]))
    with pytest.raises(SystemExit, match="Label order differs"):
        transformer.heldout(force=True)


def _select_world(root, seg, preds, sizes):
    """Toy run.json and validation predictions per encoder; preds[k] is a (n_val, 33) bool array."""
    val = seg[seg["split"] == "val"].reset_index(drop=True)
    for k in KEYS:
        d = root / "transformer" / k
        d.mkdir(exist_ok=True)
        (d / "weights.bin").write_text(k)
        (d / "labels.json").write_text(json.dumps({"label_order": LABELS, "pooled": LABELS[-5:]}))
        version = transformer.model_version(k)
        (d / "run.json").write_text(json.dumps({"model_version": version, "encoder_parameters": sizes[k],
                                                "recipe": transformer.recipe(), "seed": config.SEED,
                                                "validation_all33": {"macro_f1": 0.0, "micro_f1": 0.0,
                                                                     "macro_ap": 0.5}}))
        write_predictions(to_prediction_frame(val, preds[k].astype(float), preds[k], LABELS, f"transformer-{k}",
                                              version, 0.0, 0.0),
                          config.PREDICTIONS_DIR / f"transformer-{k}_val.parquet", LABELS)


def test_selection_rule_parsimony_and_size_tolerance(world):
    root, seg = world
    val = seg[seg["split"] == "val"].reset_index(drop=True)
    y = _Y(val)
    weak = np.zeros_like(y)
    near = y.copy()
    near[0] = False

    _select_world(root, seg, {"legal-bert": weak, "bert": weak, "deberta-v3": y},
                  {"legal-bert": 100, "bert": 100, "deberta-v3": 180})
    transformer.select()
    assert json.loads((root / "transformer" / "selected.json").read_text())["encoder"] == "deberta-v3"

    _select_world(root, seg, {"legal-bert": near, "bert": y, "deberta-v3": y},
                  {"legal-bert": 100, "bert": 100.5, "deberta-v3": 180})
    transformer.select()
    s = json.loads((root / "transformer" / "selected.json").read_text())
    assert "deberta-v3" not in s["smallest_size_group"] and s["encoder"] == "bert"

    _select_world(root, seg, {"legal-bert": near, "bert": y, "deberta-v3": y},
                  {"legal-bert": 100, "bert": 102, "deberta-v3": 180})
    transformer.select()
    s = json.loads((root / "transformer" / "selected.json").read_text())
    assert s["smallest_size_group"] == ["legal-bert"] and s["encoder"] == "legal-bert"


def test_compare_families_and_report_tables():
    from src import evaluate, report

    assert len(config.COMPARE_PAIRS) == 6 and ("transformer", "baseline") in config.COMPARE_PAIRS
    assert ("baseline", "transformer") not in config.COMPARE_PAIRS
    assert evaluate.ADJUSTED_LEVEL == pytest.approx(1 - 0.05 / 12) and "family of 12" in evaluate.COMPARE_METHOD
    row = {"difference": 0.1, "ci_low": 0.05, "ci_high": 0.15, "primary": True, "adjusted_level": 0.99583,
           "adjusted_ci_low": 0.01, "adjusted_ci_high": 0.2, "claim": "A higher"}
    comp = {"family_size": 12, "differences": {"test | Rule A | micro_f1": row}, "verdicts": {"test | Rule A": "x"}}
    md = report.comparison_tables({p: comp for p in config.COMPARE_PAIRS})
    assert "family 4b" in md and "family 6a" in md and md.count("#### Primary comparisons") == 2
