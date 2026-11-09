import json
import os
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .extraction import extract_pages
from .patterns import CATEGORIES, parse_keywords
from .redaction_service import (
    DocumentNeedsReviewError,
    DocumentProcessingError,
    RedactionService,
    render_document,
    verify_redaction,
)
from .processors import (
    analyze_docx,
    analyze_image,
    analyze_pdf,
    redact_docx,
    redact_image,
    redact_pdf,
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

app = FastAPI(title="Redactor API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Redaction-Counts"],
)


@app.exception_handler(HTTPException)
async def http_error_handler(_request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


def _file_kind(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        return "pdf"
    if extension == ".docx":
        return "docx"
    if extension in IMAGE_EXTENSIONS:
        return "image"
    raise HTTPException(status_code=415, detail="Unsupported file type. Use PDF, DOCX, PNG, JPG or WEBP.")


async def _read_upload(upload: UploadFile) -> bytes:
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 25 MB.")
    return data


def _parse_json_list(raw: str, label: str) -> list:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail=f"{label} must be valid JSON.")
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail=f"{label} must be a list.")
    return value


@app.post("/api/redact-text")
async def redact_text(file: UploadFile = File(...)) -> Response:
    kind = _file_kind(file.filename or "")
    data = await _read_upload(file)

    try:
        result = await run_in_threadpool(_redact_to_text, data, kind)
    except DocumentNeedsReviewError as error:
        raise HTTPException(status_code=422, detail=f"NEEDS_REVIEW: {error}")
    except DocumentProcessingError as error:
        raise HTTPException(status_code=502, detail=str(error))
    except Exception:
        raise HTTPException(status_code=422, detail="Could not read this file. It may be corrupted or protected.")

    output, counts = result
    stem = Path(file.filename or "document").stem
    return Response(
        content=output,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}-redacted.txt"',
            "X-Redaction-Counts": json.dumps(counts),
        },
    )


def _redact_to_text(data: bytes, kind: str) -> tuple[str, dict[str, int]]:
    pages = extract_pages(data, kind)
    result = RedactionService().redact_pages(pages)
    failure = verify_redaction(pages, result.pages, result.page_identifiers)
    if failure:
        raise DocumentNeedsReviewError(failure)
    return render_document([], result.pages), dict(result.counts)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    categories: str = Form(",".join(CATEGORIES)),
    keywords: str = Form(""),
) -> dict[str, object]:
    kind = _file_kind(file.filename or "")
    data = await _read_upload(file)
    selected = {item for item in categories.split(",") if item in CATEGORIES}
    custom_terms = parse_keywords(keywords)

    handlers: dict[str, Callable[[bytes, set[str], list[str]], dict[str, object]]] = {
        "pdf": analyze_pdf,
        "docx": analyze_docx,
        "image": analyze_image,
    }
    try:
        return await run_in_threadpool(handlers[kind], data, selected, custom_terms)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=422, detail="Could not read this file. It may be corrupted or protected.")


@app.post("/api/redact")
async def redact(
    file: UploadFile = File(...),
    boxes: str = Form("[]"),
    terms: str = Form("[]"),
) -> Response:
    kind = _file_kind(file.filename or "")
    data = await _read_upload(file)
    parsed_boxes = _parse_json_list(boxes, "boxes")
    parsed_terms = [str(term) for term in _parse_json_list(terms, "terms")]

    try:
        if kind == "pdf":
            output, mime, extension = redact_pdf(data, parsed_boxes)
        elif kind == "docx":
            output, mime, extension = redact_docx(data, parsed_terms)
        else:
            output, mime, extension = redact_image(data, parsed_boxes)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid redaction regions.")
    except Exception:
        raise HTTPException(status_code=422, detail="Redaction failed for this file.")

    stem = Path(file.filename or "document").stem
    return Response(
        content=output,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{stem}-redacted.{extension}"'},
    )
