import base64
import io
import uuid
from dataclasses import dataclass, field
from typing import Optional

import fitz
import numpy as np
from docx import Document
from PIL import Image, ImageDraw
from rapidocr_onnxruntime import RapidOCR

from .patterns import find_matches

PDF_PREVIEW_ZOOM = 1.6
MAX_PDF_PAGES = 60
BLOCK_CHAR = "█"

_ocr_engine: Optional[RapidOCR] = None


def _ocr() -> RapidOCR:
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = RapidOCR()
    return _ocr_engine


@dataclass
class Detection:
    page: int
    text: str
    category: str
    box: Optional[tuple[float, float, float, float]] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "page": self.page,
            "text": self.text,
            "category": self.category,
            "box": list(self.box) if self.box else None,
        }


@dataclass
class Page:
    index: int
    width: int
    height: int
    image: str

    def as_dict(self) -> dict[str, object]:
        return {"index": self.index, "width": self.width, "height": self.height, "image": self.image}


def _png_data_url(image_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")


def _ocr_lines(image: Image.Image) -> list[tuple[list[list[float]], str]]:
    result, _ = _ocr()(np.array(image.convert("RGB")))
    return [(box, text) for box, text, _score in (result or [])]


def _detect_from_ocr(
    image: Image.Image, page_index: int, categories: set[str], keywords: list[str]
) -> list[Detection]:
    width, height = image.size
    detections: list[Detection] = []
    for points, text in _ocr_lines(image):
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
        line_width = right - left
        if not text:
            continue
        for match in find_matches(text, categories, keywords):
            x0 = left + line_width * (match.start / len(text))
            x1 = left + line_width * (match.end / len(text))
            detections.append(
                Detection(
                    page=page_index,
                    text=match.text,
                    category=match.category,
                    box=(x0 / width, top / height, x1 / width, bottom / height),
                )
            )
    return detections


def analyze_image(data: bytes, categories: set[str], keywords: list[str]) -> dict[str, object]:
    image = Image.open(io.BytesIO(data))
    image.load()
    rgb = image.convert("RGB")
    buffer = io.BytesIO()
    rgb.save(buffer, format="PNG")
    page = Page(0, rgb.width, rgb.height, _png_data_url(buffer.getvalue()))
    detections = _detect_from_ocr(rgb, 0, categories, keywords)
    return _payload("image", [page], detections)


def analyze_pdf(data: bytes, categories: set[str], keywords: list[str]) -> dict[str, object]:
    document = fitz.open(stream=data, filetype="pdf")
    pages: list[Page] = []
    detections: list[Detection] = []
    matrix = fitz.Matrix(PDF_PREVIEW_ZOOM, PDF_PREVIEW_ZOOM)

    for index in range(min(document.page_count, MAX_PDF_PAGES)):
        pdf_page = document[index]
        pixmap = pdf_page.get_pixmap(matrix=matrix, alpha=False)
        pages.append(Page(index, pixmap.width, pixmap.height, _png_data_url(pixmap.tobytes("png"))))
        detections.extend(_detect_pdf_page(pdf_page, pixmap, index, categories, keywords))

    document.close()
    return _payload("pdf", pages, detections)


def _detect_pdf_page(
    pdf_page: fitz.Page,
    pixmap: fitz.Pixmap,
    index: int,
    categories: set[str],
    keywords: list[str],
) -> list[Detection]:
    text = pdf_page.get_text("text")
    if not text.strip():
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        return _detect_from_ocr(image, index, categories, keywords)

    page_width, page_height = pdf_page.rect.width, pdf_page.rect.height
    detections: list[Detection] = []
    seen: set[str] = set()
    for match in find_matches(text, categories, keywords):
        needle = match.text
        if needle in seen:
            continue
        seen.add(needle)
        for rect in pdf_page.search_for(needle):
            detections.append(
                Detection(
                    page=index,
                    text=needle,
                    category=match.category,
                    box=(
                        rect.x0 / page_width,
                        rect.y0 / page_height,
                        rect.x1 / page_width,
                        rect.y1 / page_height,
                    ),
                )
            )
    return detections


def _docx_paragraphs(document: Document) -> list:
    paragraphs = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    for section in document.sections:
        paragraphs.extend(section.header.paragraphs)
        paragraphs.extend(section.footer.paragraphs)
    return paragraphs


def analyze_docx(data: bytes, categories: set[str], keywords: list[str]) -> dict[str, object]:
    document = Document(io.BytesIO(data))
    detections: list[Detection] = []
    preview: list[str] = []
    seen: set[str] = set()

    for paragraph in _docx_paragraphs(document):
        text = paragraph.text
        if not text.strip():
            continue
        preview.append(text)
        for match in find_matches(text, categories, keywords):
            if match.text in seen:
                continue
            seen.add(match.text)
            detections.append(Detection(page=0, text=match.text, category=match.category))

    payload = _payload("docx", [], detections)
    payload["paragraphs"] = preview
    return payload


def _payload(kind: str, pages: list[Page], detections: list[Detection]) -> dict[str, object]:
    return {
        "kind": kind,
        "pages": [page.as_dict() for page in pages],
        "detections": [detection.as_dict() for detection in detections],
    }


def redact_image(data: bytes, boxes: list[dict[str, float]]) -> tuple[bytes, str, str]:
    source = Image.open(io.BytesIO(data))
    source.load()
    image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    for box in boxes:
        draw.rectangle(
            [
                box["x0"] * image.width,
                box["y0"] * image.height,
                box["x1"] * image.width,
                box["y1"] * image.height,
            ],
            fill=(0, 0, 0),
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), "image/png", "png"


def redact_pdf(data: bytes, boxes: list[dict[str, float]]) -> tuple[bytes, str, str]:
    document = fitz.open(stream=data, filetype="pdf")
    by_page: dict[int, list[fitz.Rect]] = {}
    for box in boxes:
        page_index = int(box["page"])
        if not 0 <= page_index < document.page_count:
            continue
        rect = document[page_index].rect
        by_page.setdefault(page_index, []).append(
            fitz.Rect(
                box["x0"] * rect.width,
                box["y0"] * rect.height,
                box["x1"] * rect.width,
                box["y1"] * rect.height,
            )
        )

    for page_index, rects in by_page.items():
        pdf_page = document[page_index]
        for rect in rects:
            pdf_page.add_redact_annot(rect, fill=(0, 0, 0))
        pdf_page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)

    document.set_metadata({})
    document.scrub()
    output = document.tobytes(garbage=4, deflate=True)
    document.close()
    return output, "application/pdf", "pdf"


def redact_docx(data: bytes, terms: list[str]) -> tuple[bytes, str, str]:
    document = Document(io.BytesIO(data))
    ordered_terms = sorted({term for term in terms if term}, key=len, reverse=True)

    for paragraph in _docx_paragraphs(document):
        _redact_paragraph(paragraph, ordered_terms)

    core = document.core_properties
    core.author = ""
    core.last_modified_by = ""
    core.title = ""
    core.comments = ""

    buffer = io.BytesIO()
    document.save(buffer)
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return buffer.getvalue(), mime, "docx"


def _redact_paragraph(paragraph, terms: list[str]) -> None:
    for run in paragraph.runs:
        run.text = _mask(run.text, terms)
    joined = "".join(run.text for run in paragraph.runs)
    masked = _mask(joined, terms)
    if masked != joined and paragraph.runs:
        paragraph.runs[0].text = masked
        for run in paragraph.runs[1:]:
            run.text = ""


def _mask(text: str, terms: list[str]) -> str:
    result = text
    for term in terms:
        lowered = result.lower()
        needle = term.lower()
        position = lowered.find(needle)
        while position != -1:
            result = result[:position] + BLOCK_CHAR * len(term) + result[position + len(term) :]
            lowered = result.lower()
            position = lowered.find(needle, position + len(term))
    return result

