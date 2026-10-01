"""PDF to text for the review service (Step 7): the text layer first, OCR for pages without one."""

from __future__ import annotations

import io
import shutil
from dataclasses import dataclass, field

import pypdf

from src import config


PAGE_SEP = "\n\n"


class PdfError(ValueError):
    """The file cannot be read as a PDF."""


@dataclass
class Extraction:
    text: str
    pages: int
    ocr_pages: list[int] = field(default_factory=list)   # 1-based
    warnings: list[str] = field(default_factory=list)
    page_starts: list[int] = field(default_factory=list)  # offset of each page in text


def _page_text(page) -> str:
    try:
        return page.extract_text() or ""
    except Exception:  # a malformed content stream: treat the page as having no text layer
        return ""


def _ocr_page(doc, index: int) -> str:
    import pytesseract

    image = doc[index].render(scale=config.PDF_OCR_DPI / 72).to_pil()
    return pytesseract.image_to_string(image)


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def extract(pdf_bytes: bytes, force_ocr: bool = False,
            max_ocr_pages: int | None = config.PDF_MAX_OCR_PAGES) -> Extraction:
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted and not reader.decrypt(""):
            raise PdfError("encrypted PDF")
        pages_in = list(reader.pages)
    except pypdf.errors.PyPdfError as e:
        raise PdfError(f"unreadable PDF: {e}") from e
    raw = [_page_text(page) for page in pages_in]
    have_ocr, doc = ocr_available(), None
    pages, ocr_pages, warnings = [], [], []
    try:
        for i, text in enumerate(raw):
            if force_ocr or len(text.strip()) < config.PDF_MIN_PAGE_CHARS:
                skip = None
                if not have_ocr:
                    skip = "Tesseract is not installed"
                elif max_ocr_pages is not None and len(ocr_pages) >= max_ocr_pages:
                    skip = "OCR page limit reached"
                else:
                    try:
                        if doc is None:
                            import pypdfium2
                            doc = pypdfium2.PdfDocument(pdf_bytes)
                        text = _ocr_page(doc, i)
                        ocr_pages.append(i + 1)
                    except Exception as e:
                        skip = f"OCR failed ({type(e).__name__}: {e})"
                if skip:
                    text = "" if force_ocr else text
                    warnings.append(f"page {i + 1}: {skip}; kept {len(text.strip())} characters of text layer")
            pages.append(text)
    finally:
        if doc is not None:
            doc.close()
    starts, offset = [], 0
    for page in pages:
        starts.append(offset)
        offset += len(page) + len(PAGE_SEP)
    return Extraction(PAGE_SEP.join(pages), len(pages), ocr_pages, warnings, starts)
