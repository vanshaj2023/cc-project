import io

import fitz
from docx import Document
from PIL import Image

from .processors import MAX_PDF_PAGES, PDF_PREVIEW_ZOOM, _docx_paragraphs, _ocr_lines
from .redaction_service import DocumentNeedsReviewError, count_real_words


def _ocr_text(image: Image.Image) -> str:
    return "\n".join(text for _box, text in _ocr_lines(image) if text)


def _pdf_pages(data: bytes) -> list[str]:
    document = fitz.open(stream=data, filetype="pdf")
    try:
        if document.needs_pass:
            raise DocumentNeedsReviewError("The PDF is password protected.")
        if document.page_count > MAX_PDF_PAGES:
            raise DocumentNeedsReviewError(f"The PDF has more than {MAX_PDF_PAGES} pages.")

        matrix = fitz.Matrix(PDF_PREVIEW_ZOOM, PDF_PREVIEW_ZOOM)
        pages: list[str] = []
        for pdf_page in document:
            text = pdf_page.get_text("text")
            if count_real_words(text) == 0:
                pixmap = pdf_page.get_pixmap(matrix=matrix, alpha=False)
                text = _ocr_text(Image.open(io.BytesIO(pixmap.tobytes("png"))))
            pages.append(text)
        return pages
    finally:
        document.close()


def _docx_pages(data: bytes) -> list[str]:
    document = Document(io.BytesIO(data))
    lines = [paragraph.text for paragraph in _docx_paragraphs(document) if paragraph.text.strip()]
    return ["\n".join(lines)]


def _image_pages(data: bytes) -> list[str]:
    image = Image.open(io.BytesIO(data))
    image.load()
    return [_ocr_text(image.convert("RGB"))]


def extract_pages(data: bytes, kind: str) -> list[str]:
    extractors = {"pdf": _pdf_pages, "docx": _docx_pages, "image": _image_pages}
    pages = extractors[kind](data)
    if not any(count_real_words(page) for page in pages):
        raise DocumentNeedsReviewError("No readable text could be extracted.")
    return pages
