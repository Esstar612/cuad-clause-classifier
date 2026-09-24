"""None downsampling touches train only, keeps every positive, and is reproducible with the seed."""

import pandas as pd
import pytest

from src import config
from src.baseline import downsample_none


def _segments(split="train", n_pos=20, n_none=200) -> pd.DataFrame:
    labels = [["A"]] * n_pos + [[]] * n_none
    return pd.DataFrame({"segment_id": [f"s{i}" for i in range(len(labels))],
                         "split": split, "labels": labels})


def test_keeps_every_positive_and_ratio_times_none():
    df = _segments()
    out = downsample_none(df, 3)
    assert (out["labels"].map(len) > 0).sum() == 20
    assert (out["labels"].map(len) == 0).sum() == 60


def test_reproducible_with_config_seed():
    df = _segments()
    assert downsample_none(df, 3).index.equals(downsample_none(df, 3).index)


def test_different_seed_changes_sample():
    df = _segments()
    a = downsample_none(df, 3, seed=config.SEED)
    b = downsample_none(df, 3, seed=config.SEED + 1)
    assert not a.index.equals(b.index)


def test_ratio_none_keeps_everything_and_large_ratio_caps_at_available():
    df = _segments()
    assert len(downsample_none(df, None)) == len(df)
    assert len(downsample_none(df, 100)) == len(df)


@pytest.mark.parametrize("split", ["val", "test", "shift"])
def test_refuses_to_downsample_evaluation_splits(split):
    with pytest.raises(ValueError):
        downsample_none(_segments(split=split), 3)
