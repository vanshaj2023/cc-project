import base64
import io
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional, Union

import fitz
import numpy as np
from docx import Document
from PIL import Image, ImageDraw
from rapidocr_onnxruntime import RapidOCR

from .patterns import find_matches
from .redaction_service import (
    DocumentNeedsReviewError,
    DocumentProcessingError,
    Identifier,
    RedactionService,
)
from .vision_detection import AiHit, Box, find_image_identifiers

PDF_PREVIEW_ZOOM = 1.6
MAX_PDF_PAGES = 60
BLOCK_CHAR = "█"
OCR_MIN_SIDE = 1600
AI_PAGE_WORKERS = 4
DUPLICATE_OVERLAP = 0.6
AI_ERRORS = (DocumentProcessingError, DocumentNeedsReviewError)

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
    rgb = image.convert("RGB")
    scale = max(1.0, OCR_MIN_SIDE / max(rgb.size))
    if scale > 1.0:
        rgb = rgb.resize((round(rgb.width * scale), round(rgb.height * scale)), Image.LANCZOS)
    result, _ = _ocr()(np.array(rgb))
    return [([[x / scale, y / scale] for x, y in box], text) for box, text, _score in (result or [])]


def _ai_enabled() -> bool:
    return bool(os.environ.get("REDACTION_MODEL"))


def _is_duplicate(box: Box, page: int, existing: list["Detection"]) -> bool:
    area = (box[2] - box[0]) * (box[3] - box[1])
    for other in existing:
        if other.page != page or other.box is None:
            continue
        width = min(box[2], other.box[2]) - max(box[0], other.box[0])
        height = min(box[3], other.box[3]) - max(box[1], other.box[1])
        if width <= 0 or height <= 0:
            continue
        other_area = (other.box[2] - other.box[0]) * (other.box[3] - other.box[1])
        if width * height / min(area, other_area) > DUPLICATE_OVERLAP:
            return True
    return False


def _hits_to_detections(
    hits: list[AiHit], page_index: int, existing: list["Detection"], warnings: list[str]
) -> list["Detection"]:
    detections: list[Detection] = []
    unlocated = 0
    for hit in hits:
        if not hit.boxes:
            unlocated += 1
            continue
        for box in hit.boxes:
            if _is_duplicate(box, page_index, existing + detections):
                continue
            detections.append(Detection(page=page_index, text=hit.text, category=hit.category.lower(), box=box))
    if unlocated:
        warnings.append(f"{unlocated} AI-detected item(s) could not be located. Draw boxes over them.")
    return detections


def _locate_text_identifiers(
    pdf_page: fitz.Page,
    page_index: int,
    identifiers: list[Identifier],
    existing: list["Detection"],
    warnings: list[str],
) -> list["Detection"]:
    page_width, page_height = pdf_page.rect.width, pdf_page.rect.height
    unique: dict[str, str] = {}
    for identifier in identifiers:
        unique.setdefault(identifier.text, identifier.category)

    detections: list[Detection] = []
    missed = 0
    for text, category in unique.items():
        rects = pdf_page.search_for(text)
        if not rects:
            missed += 1
            continue
        for rect in rects:
            box = (rect.x0 / page_width, rect.y0 / page_height, rect.x1 / page_width, rect.y1 / page_height)
            if _is_duplicate(box, page_index, existing + detections):
                continue
            detections.append(Detection(page=page_index, text=text, category=category.lower(), box=box))
    if missed:
        warnings.append(f"{missed} AI-detected item(s) could not be located. Draw boxes over them.")
    return detections


def _detect_from_ocr(
    image: Image.Image,
    page_index: int,
    categories: set[str],
    keywords: list[str],
    lines: list[tuple[list[list[float]], str]],
) -> list[Detection]:
    width, height = image.size
    detections: list[Detection] = []
    for points, text in lines:
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
    lines = _ocr_lines(rgb)
    detections = _detect_from_ocr(rgb, 0, categories, keywords, lines)
    warnings: list[str] = []
    if _ai_enabled():
        try:
            hits = find_image_identifiers(rgb, lines)
        except AI_ERRORS as error:
            warnings.append(f"AI detection failed: {error}")
        else:
            detections.extend(_hits_to_detections(hits, 0, detections, warnings))
    return _payload("image", [page], detections, warnings)


@dataclass
class _AiJob:
    index: int
    text: str
    image: Optional[Image.Image] = None
    lines: Optional[list[tuple[list[list[float]], str]]] = None


def analyze_pdf(data: bytes, categories: set[str], keywords: list[str]) -> dict[str, object]:
    document = fitz.open(stream=data, filetype="pdf")
    pages: list[Page] = []
    detections: list[Detection] = []
    jobs: list[_AiJob] = []
    matrix = fitz.Matrix(PDF_PREVIEW_ZOOM, PDF_PREVIEW_ZOOM)

    for index in range(min(document.page_count, MAX_PDF_PAGES)):
        pdf_page = document[index]
        pixmap = pdf_page.get_pixmap(matrix=matrix, alpha=False)
        pages.append(Page(index, pixmap.width, pixmap.height, _png_data_url(pixmap.tobytes("png"))))
        page_detections, job = _detect_pdf_page(pdf_page, pixmap, index, categories, keywords)
        detections.extend(page_detections)
        jobs.append(job)

    warnings: list[str] = []
    if _ai_enabled():
        detections.extend(_run_pdf_ai(document, jobs, detections, warnings))
    document.close()
    return _payload("pdf", pages, detections, warnings)


def _run_pdf_ai(
    document: fitz.Document, jobs: list[_AiJob], existing: list[Detection], warnings: list[str]
) -> list[Detection]:
    service = RedactionService()

    def work(job: _AiJob) -> Union[list[AiHit], list[Identifier], Exception]:
        try:
            if job.image is not None:
                return find_image_identifiers(job.image, job.lines or [])
            return service.identify_page(job.text)
        except AI_ERRORS as error:
            return error

    with ThreadPoolExecutor(max_workers=AI_PAGE_WORKERS) as pool:
        results = list(pool.map(work, jobs))

    found: list[Detection] = []
    for job, result in zip(jobs, results):
        if isinstance(result, Exception):
            warnings.append(f"AI detection failed on page {job.index + 1}: {result}")
        elif job.image is not None:
            found.extend(_hits_to_detections(result, job.index, existing + found, warnings))
        else:
            found.extend(
                _locate_text_identifiers(document[job.index], job.index, result, existing + found, warnings)
            )
    return found


def _detect_pdf_page(
    pdf_page: fitz.Page,
    pixmap: fitz.Pixmap,
    index: int,
    categories: set[str],
    keywords: list[str],
) -> tuple[list[Detection], _AiJob]:
    text = pdf_page.get_text("text")
    if not text.strip():
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        lines = _ocr_lines(image)
        return _detect_from_ocr(image, index, categories, keywords, lines), _AiJob(index, "", image, lines)

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
    return detections, _AiJob(index, text)


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

    warnings: list[str] = []
    if _ai_enabled():
        try:
            identifiers = RedactionService().identify_page("\n".join(preview))
        except AI_ERRORS as error:
            warnings.append(f"AI detection failed: {error}")
        else:
            for identifier in identifiers:
                if identifier.text in seen:
                    continue
                seen.add(identifier.text)
                detections.append(Detection(page=0, text=identifier.text, category=identifier.category.lower()))

    payload = _payload("docx", [], detections, warnings)
    payload["paragraphs"] = preview
    return payload


def _payload(
    kind: str, pages: list[Page], detections: list[Detection], warnings: Optional[list[str]] = None
) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": kind,
        "pages": [page.as_dict() for page in pages],
        "detections": [detection.as_dict() for detection in detections],
    }
    if warnings:
        payload["warning"] = " ".join(dict.fromkeys(warnings))
    return payload


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

