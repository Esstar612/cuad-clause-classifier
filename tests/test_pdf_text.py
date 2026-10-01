import sys
from types import SimpleNamespace

import pytest

from src import pdf_text
from src.pdf_text import PdfError, extract

TEXT = "This Agreement is governed by the laws of the State of Delaware."


def _pdf(page_texts) -> bytes:
    """A minimal PDF, one page per entry; None gives a page without a text layer."""
    n = len(page_texts)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {n} >>"]
    font = 3 + 2 * n
    for i, text in enumerate(page_texts):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {font} 0 R >> >> >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


@pytest.fixture
def fake_ocr(monkeypatch):
    calls = []

    class Doc:
        def close(self):
            calls.append("closed")

    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=lambda data: Doc()))
    monkeypatch.setattr(pdf_text, "ocr_available", lambda: True)
    monkeypatch.setattr(pdf_text, "_ocr_page", lambda doc, i: calls.append(i) or f"OCR text of page {i + 1}")
    return calls


def test_text_layer_is_used_without_ocr(fake_ocr):
    ex = extract(_pdf([TEXT]))
    assert "governed by the laws" in ex.text and ex.pages == 1 and ex.ocr_pages == [] and fake_ocr == []


def test_page_without_text_layer_and_forced_ocr_go_to_ocr(fake_ocr):
    ex = extract(_pdf([TEXT, None]))
    assert ex.ocr_pages == [2] and "OCR text of page 2" in ex.text and "governed" in ex.text
    ex = extract(_pdf([TEXT]), force_ocr=True)
    assert ex.ocr_pages == [1] and "governed" not in ex.text


def test_missing_tesseract_is_a_warning_not_silence(monkeypatch):
    monkeypatch.setattr(pdf_text, "ocr_available", lambda: False)
    ex = extract(_pdf([None]))
    assert ex.text == "" and "Tesseract is not installed" in ex.warnings[0]


def test_ocr_page_limit_and_no_limit(fake_ocr):
    ex = extract(_pdf([None, None, None]), max_ocr_pages=2)
    assert ex.ocr_pages == [1, 2] and "OCR page limit" in ex.warnings[0]
    ex = extract(_pdf([None, None, None]), max_ocr_pages=None)
    assert ex.ocr_pages == [1, 2, 3] and ex.warnings == []


def test_malformed_bytes_raise_pdf_error():
    with pytest.raises(PdfError):
        extract(b"this is not a pdf")


def test_page_whose_extraction_raises_is_treated_as_empty():
    class Broken:
        def extract_text(self):
            raise KeyError("/Font")

    assert pdf_text._page_text(Broken()) == ""


def test_ocr_failure_is_a_warning_not_a_crash(fake_ocr, monkeypatch):
    def broken(doc, i):
        raise RuntimeError("render failed")

    monkeypatch.setattr(pdf_text, "_ocr_page", broken)
    ex = extract(_pdf([TEXT, None]))
    assert "governed" in ex.text and ex.ocr_pages == [] and "OCR failed" in ex.warnings[0]
    assert extract(_pdf([TEXT]), force_ocr=True).text == ""


def test_short_text_layer_is_kept_when_ocr_is_unavailable(monkeypatch):
    monkeypatch.setattr(pdf_text, "ocr_available", lambda: False)
    ex = extract(_pdf(["Governing Law."]))
    assert ex.text == "Governing Law." and "kept 14 characters" in ex.warnings[0]


def test_page_starts_point_at_each_page_in_the_joined_text(fake_ocr):
    ex = extract(_pdf([TEXT, None, TEXT]))
    assert ex.page_starts[0] == 0 and len(ex.page_starts) == 3
    assert ex.text[ex.page_starts[1]:].startswith("OCR text of page 2")
    assert ex.text[ex.page_starts[2]:].startswith(TEXT[:30])
