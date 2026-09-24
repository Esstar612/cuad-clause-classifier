"""Segment dataset integrity: splits follow contracts, exclusions follow the schema, offsets are exact."""

import pandas as pd
import pytest

from src import config
from src.labels import EXTRACTION, RARE_DROPPED, label_set

SEGMENTS_PATH = config.PROCESSED_DIR / "segments.parquet"


@pytest.fixture(scope="module")
def segments() -> pd.DataFrame:
    if not SEGMENTS_PATH.exists():
        pytest.skip("segments.parquet missing; run python -m src.build_segments")
    return pd.read_parquet(SEGMENTS_PATH)


def test_segment_ids_unique(segments):
    assert segments["segment_id"].is_unique


def test_every_contract_has_segments(segments):
    contracts = pd.read_parquet(config.PROCESSED_DIR / "contracts.parquet")
    assert set(segments["contract_id"]) == set(contracts["contract_id"])


def test_segment_split_is_its_contract_split(segments):
    splits = pd.read_parquet(config.PROCESSED_DIR / "splits.parquet")
    assert segments.groupby("contract_id")["split"].nunique().max() == 1
    merged = (segments[["contract_id", "split"]].drop_duplicates()
              .merge(splits[["contract_id", "split"]], on="contract_id", suffixes=("", "_contract")))
    assert (merged["split"] == merged["split_contract"]).all()


def test_excluded_segments_carry_only_rare_or_extraction_categories(segments):
    excluded = segments[segments["exclude"]]
    for raw, labels in zip(excluded["raw_categories"], excluded["labels"]):
        raw = set(raw)
        assert len(labels) == 0
        assert raw & RARE_DROPPED
        assert raw <= RARE_DROPPED | EXTRACTION


def test_labels_are_within_the_33_kept_labels(segments):
    spans = pd.read_parquet(config.PROCESSED_DIR / "spans.parquet")
    kept = set(label_set(spans["category"].unique()))
    assert len(kept) == 33
    used = {lab for labs in segments["labels"] for lab in labs}
    assert used <= kept


def test_offsets_match_contract_text(segments):
    from src.data import load_contexts, load_raw_json

    contexts = load_contexts(load_raw_json())
    sample = segments.sample(n=min(500, len(segments)), random_state=config.SEED)
    for r in sample.itertuples():
        assert contexts[r.contract_id][r.start:r.end] == r.text
