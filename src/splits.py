"""Contract-level train/val/test split plus a held-out contract-type shift set.

Run: python -m src.splits | tee data/processed/splits_report.txt
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import config
from src.labels import model_label

SPLIT_ORDER = ["train", "val", "test", "shift"]

def assign_splits(contracts: pd.DataFrame, seed: int = config.SEED,
                  shift_types=config.SHIFT_TYPES,
                  fractions=config.SPLIT_FRACTIONS) -> pd.DataFrame:
    """Assign every contract to exactly one of train/val/test/shift.

    All contracts of `shift_types` go to shift. The rest are split within each
    contract type (stratified), shuffled with `seed`:
      - train gets round_half_up(train_frac * n) contracts of the type;
      - the remainder is split evenly between val and test, and an odd extra goes
        to whichever of val/test is smaller so far (types in sorted order, ties to val).
    So val and test differ by at most one contract overall and within each type.
    Uses only contract counts per type, never labels. Independent of input row order.
    """
    if not np.isclose(sum(fractions), 1.0):
        raise ValueError(f"fractions must sum to 1, got {fractions}")
    train_frac, val_frac, test_frac = fractions
    if not np.isclose(val_frac, test_frac):
        raise ValueError("balanced val/test allocation requires equal val and test fractions")
    if contracts["contract_type"].isna().any():
        raise ValueError("every contract needs a contract_type")

    df = (contracts[["contract_id", "contract_type"]]
          .sort_values("contract_id").reset_index(drop=True))
    df["split"] = "shift"
    rng = np.random.default_rng(seed)
    in_dist = df[~df["contract_type"].isin(shift_types)]
    n_val = n_test = 0
    for ctype in sorted(in_dist["contract_type"].unique()):
        idx = rng.permutation(in_dist.index[in_dist["contract_type"] == ctype].to_numpy())
        n = len(idx)
        n_train = int(n * train_frac + 0.5)  # round half up
        rest = n - n_train
        v = t = rest // 2
        if rest % 2:
            if n_val <= n_test:
                v += 1
            else:
                t += 1
        n_val += v
        n_test += t
        df.loc[idx[:n_train], "split"] = "train"
        df.loc[idx[n_train:n_train + v], "split"] = "val"
        df.loc[idx[n_train + v:], "split"] = "test"
    return df


def main() -> None:
    pd.set_option("display.width", 200)
    contracts = pd.read_parquet(config.PROCESSED_DIR / "contracts.parquet")
    splits = assign_splits(contracts)
    splits.to_parquet(config.PROCESSED_DIR / "splits.parquet", index=False)

    print(f"Seed: {config.SEED}  Shift types: {config.SHIFT_TYPES}  Fractions: {config.SPLIT_FRACTIONS}")
    print("\n=== Contracts per split ===")
    print(splits["split"].value_counts().reindex(SPLIT_ORDER).to_string())
    print("\n=== Contracts per type and split ===")
    print(pd.crosstab(splits["contract_type"], splits["split"])
          .reindex(columns=SPLIT_ORDER, fill_value=0).to_string())

    spans = pd.read_parquet(config.PROCESSED_DIR / "spans.parquet")
    pos = spans[spans["has_answer"]].assign(label=lambda d: d["category"].map(model_label))
    pos = pos.dropna(subset=["label"]).merge(splits[["contract_id", "split"]], on="contract_id")
    table = (pos.groupby(["label", "split"])["contract_id"].nunique()
             .unstack(fill_value=0).reindex(columns=SPLIT_ORDER, fill_value=0))
    print("\n=== Contracts with each kept label, per split ===")
    print(table.sort_values("val").to_string())
    print(f"\nWrote {config.PROCESSED_DIR / 'splits.parquet'} ({len(splits)} rows)")


if __name__ == "__main__":
    main()
