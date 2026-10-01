import numpy as np
import pytest

from src import extraction_eval as E


def test_word_overlap_counts_a_multiset_intersection():
    assert E.word_overlap("The the Party shall", "the party SHALL pay") == (3, 4, 4)


def test_micro_f1_from_contract_counts_and_weights():
    counts = E.label_set_counts({1: {"A", "B"}, 2: set()}, {1: {"A"}, 2: {"C"}}, [1, 2])
    assert counts.tolist() == [[1, 1, 0], [0, 0, 1]]
    assert E.micro_f1(counts, np.ones((1, 2)))[0] == pytest.approx(2 / 4)
    W = np.array([[2, 0], [0, 2]])
    assert E.micro_f1(counts, W).tolist() == pytest.approx([2 / 3, 0.0])


def test_gold_minus_pdf_uses_the_same_resamples():
    gold = np.array([[1, 0, 0], [1, 0, 0]])
    pdf = np.array([[0, 0, 1], [1, 0, 0]])
    W = np.array([[1, 1], [2, 0], [0, 2]])
    diff = E.micro_f1(gold, W) - E.micro_f1(pdf, W)
    assert diff.tolist() == pytest.approx([1 - 2 / 3, 1.0, 0.0])


def test_refuses_to_run_without_tesseract(monkeypatch):
    monkeypatch.setattr(E, "ocr_available", lambda: False)
    with pytest.raises(SystemExit, match="Tesseract"):
        E.main()


def _pdf_dir(tmp_path, monkeypatch, stems, titles):
    from src import config

    for stem in stems:
        (tmp_path / f"{stem}.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(config, "CUAD_PDF_DIR", tmp_path)
    monkeypatch.setattr(E, "contract_ids", lambda raw: {t: i for i, t in enumerate(titles)})


def test_validation_pdfs_match_exact_key_then_unique_prefix(tmp_path, monkeypatch):
    _pdf_dir(tmp_path, monkeypatch, ["Alpha Agreement", "Beta Supply Agreement"], ["Alpha Agreement", "Beta Supply", "Gamma"])
    out = E.validation_pdfs({}, {0, 1})
    assert out[0].stem == "Alpha Agreement" and out[1].stem == "Beta Supply Agreement"


@pytest.mark.parametrize("stems,titles", [(["Foo"], ["Foo", "Foo Bar"]), (["Alpha"], ["Alpha", "Missing"])])
def test_validation_pdfs_refuse_shared_or_missing_pdfs(tmp_path, monkeypatch, stems, titles):
    _pdf_dir(tmp_path, monkeypatch, stems, titles)
    with pytest.raises(SystemExit, match="refusing"):
        E.validation_pdfs({}, {0, 1})
