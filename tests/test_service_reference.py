import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from src.service_reference import oov_rate


def test_oov_rate_counts_unigrams_outside_the_vocabulary():
    vectorizer = TfidfVectorizer(ngram_range=(1, 2)).fit(["the party shall pay"])
    assert oov_rate(["the party shall indemnify", "licensor"], vectorizer) == pytest.approx(2 / 5)
    assert oov_rate([""], vectorizer) == 0.0


def test_reference_from_another_vocabulary_is_refused(tmp_path, monkeypatch):
    import json

    from src import service_reference

    monkeypatch.setattr(service_reference, "REFERENCE", tmp_path / "reference.json")
    service_reference.REFERENCE.write_text(json.dumps({"vocab_version": "v1", "oov_rates": [0.1, 0.2]}))
    assert service_reference.load_reference("v1") == [0.1, 0.2]
    with pytest.raises(SystemExit, match="another baseline vocabulary"):
        service_reference.load_reference("v2")
