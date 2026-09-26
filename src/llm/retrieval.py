"""Train examples for v3. Labels are the gold labels from segments.parquet, never baseline predictions."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from src.baseline import load_frozen_pipeline
from src.build_segments import load_segments


class TrainIndex:
    def __init__(self, segments: pd.DataFrame, vectorizer):
        if vectorizer.norm != "l2":
            raise ValueError("retrieval needs L2-normalised TF-IDF rows so that a dot product is cosine")
        pool = segments[(segments["split"] == "train") & ~segments["exclude"]]
        pool = pool.sort_values(["contract_id", "seg_idx"]).reset_index(drop=True)
        self.segment_ids = pool["segment_id"].tolist()
        self.texts = pool["text"].tolist()
        self.labels = [sorted(labs) for labs in pool["labels"]]
        self.labeled = np.array([bool(labs) for labs in self.labels])
        self.vectorizer = vectorizer
        self.matrix = vectorizer.transform(self.texts)

    def neighbours(self, text: str) -> tuple[int, int]:
        sims = (self.matrix @ self.vectorizer.transform([text]).T).toarray().ravel()
        order = np.lexsort((np.arange(len(sims)), -sims))  # ties go to the earlier pool row
        labeled = next(i for i in order if self.labeled[i])
        overall = next(i for i in order if i != labeled)
        return labeled, overall

    def examples_for(self, target_texts: list[str]) -> list[dict]:
        seen, out = set(), []
        for text in target_texts:
            for i in self.neighbours(text):
                if i not in seen:
                    seen.add(i)
                    out.append({"segment_id": self.segment_ids[i], "text": self.texts[i],
                                "labels": self.labels[i]})
        return out


@lru_cache(maxsize=1)
def train_index() -> TrainIndex:
    return TrainIndex(load_segments(include_excluded=True), load_frozen_pipeline().named_steps["tfidf"])
