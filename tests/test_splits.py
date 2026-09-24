"""Split integrity: no contract in two splits, shift set isolated, reproducible with the config seed."""

from itertools import combinations

import pandas as pd
import pytest

from src import config
from src.splits import assign_splits

SPLITS = ("train", "val", "test", "shift")
CONTRACTS_PATH = config.PROCESSED_DIR / "contracts.parquet"
SPLITS_PATH = config.PROCESSED_DIR / "splits.parquet"


def synthetic_contracts() -> pd.DataFrame:
    """Deterministic toy data: a large type, a mid type, a tiny type, and every shift type."""
    sizes = {"TypeA": 30, "TypeB": 12, "TypeC": 3}
    sizes.update({t: 8 for t in config.SHIFT_TYPES})
    rows = []
    for ctype, n in sizes.items():
        start = len(rows)  # evaluate once; inside the generator len(rows) grows as rows are added
        rows.extend({"contract_id": start + i, "contract_type": ctype} for i in range(n))
    return pd.DataFrame(rows)


def real_contracts() -> pd.DataFrame:
    if not CONTRACTS_PATH.exists():
        pytest.skip("data/processed/contracts.parquet missing; run python -m src.data")
    return pd.read_parquet(CONTRACTS_PATH)


def test_synthetic_fixture_ids_are_unique():
    assert synthetic_contracts()["contract_id"].is_unique


@pytest.fixture(params=["synthetic", "real"])
def contracts(request) -> pd.DataFrame:
    return synthetic_contracts() if request.param == "synthetic" else real_contracts()


def test_every_contract_assigned_exactly_once(contracts):
    out = assign_splits(contracts)
    assert out["contract_id"].is_unique
    assert set(out["contract_id"]) == set(contracts["contract_id"])
    assert set(out["split"]) <= set(SPLITS)


def test_no_contract_in_two_splits_including_shift(contracts):
    out = assign_splits(contracts)
    ids = {s: set(out.loc[out["split"] == s, "contract_id"]) for s in SPLITS}
    for a, b in combinations(SPLITS, 2):
        assert not ids[a] & ids[b], f"contracts in both {a} and {b}: {sorted(ids[a] & ids[b])[:5]}"


def test_shift_is_exactly_the_shift_types(contracts):
    out = assign_splits(contracts)
    is_shift_type = out["contract_type"].isin(config.SHIFT_TYPES)
    assert (out.loc[is_shift_type, "split"] == "shift").all()
    assert (out.loc[~is_shift_type, "split"] != "shift").all()


def test_reproducible_with_config_seed(contracts):
    a = assign_splits(contracts, seed=config.SEED)
    b = assign_splits(contracts, seed=config.SEED)
    pd.testing.assert_frame_equal(a, b)


def test_different_seed_changes_assignment(contracts):
    a = assign_splits(contracts, seed=config.SEED)
    b = assign_splits(contracts, seed=config.SEED + 1)
    assert not a["split"].equals(b["split"])


def test_independent_of_input_row_order(contracts):
    reordered = contracts.iloc[::-1].reset_index(drop=True)
    pd.testing.assert_frame_equal(assign_splits(contracts), assign_splits(reordered))


def test_stratified_within_one_contract_per_type(contracts):
    out = assign_splits(contracts)
    in_dist = out[out["split"] != "shift"]
    for ctype, group in in_dist.groupby("contract_type"):
        n = len(group)
        for split, frac in zip(("train", "val", "test"), config.SPLIT_FRACTIONS):
            count = (group["split"] == split).sum()
            assert abs(count - frac * n) <= 1, f"{ctype}: {split} has {count} of {n}"


def test_val_and_test_balanced_within_one_contract(contracts):
    out = assign_splits(contracts)
    counts = out["split"].value_counts()
    assert abs(counts.get("val", 0) - counts.get("test", 0)) <= 1
    for ctype, group in out[out["split"] != "shift"].groupby("contract_type"):
        per_type = group["split"].value_counts()
        assert abs(per_type.get("val", 0) - per_type.get("test", 0)) <= 1, ctype


def test_train_is_rounded_share_per_type(contracts):
    out = assign_splits(contracts)
    train_frac = config.SPLIT_FRACTIONS[0]
    for ctype, group in out[out["split"] != "shift"].groupby("contract_type"):
        assert (group["split"] == "train").sum() == int(len(group) * train_frac + 0.5), ctype


def test_saved_splits_match_config_seed():
    if not SPLITS_PATH.exists():
        pytest.skip("data/processed/splits.parquet missing; run python -m src.splits")
    saved = pd.read_parquet(SPLITS_PATH)
    pd.testing.assert_frame_equal(saved, assign_splits(real_contracts()))


def test_contract_splits_csv_matches_parquet_and_config_seed():
    if not (config.SPLITS_CSV.exists() and SPLITS_PATH.exists()):
        pytest.skip("contract_splits.csv or splits.parquet missing; run python -m src.splits")
    csv = pd.read_csv(config.SPLITS_CSV)
    assert list(csv.columns) == ["contract_id", "contract_type", "split"]
    assert len(csv) == 510 and csv["contract_id"].is_unique
    saved = pd.read_parquet(SPLITS_PATH)[["contract_id", "contract_type", "split"]]
    expected = saved.sort_values("contract_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(csv, expected, check_dtype=False)
    fresh = assign_splits(real_contracts()).sort_values("contract_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(csv, fresh[["contract_id", "contract_type", "split"]], check_dtype=False)
