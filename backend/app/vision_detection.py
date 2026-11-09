import base64
import io
import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from PIL import Image

from .redaction_service import (
    CATEGORIES,
    FALLBACK_CATEGORY,
    MAX_ATTEMPTS,
    DocumentNeedsReviewError,
    DocumentProcessingError,
    RedactionService,
)

Box = tuple[float, float, float, float]
OcrLine = tuple[list[list[float]], str]

MIN_SIDE = 1600
MAX_SIDE = 2048
FUZZY_RATIO = 0.7
MIN_FUZZY_LENGTH = 3
PAD_X = 0.004
PAD_Y = 0.006

VISION_PROMPT = (
    "You find personal identifiers in an image of a document (scan, photo or handwritten note).\n"
    "Text can be handwritten, blurry or in any script (for example Malayalam, Hindi, Arabic). "
    "Read it carefully.\n"
    "List EVERY identifier you can see: names of patients, doctors and relatives, organizations, "
    "hospitals and clinics, addresses, locations, phone numbers, emails, dates of birth, "
    "registration, ID and health card numbers, and URLs.\n"
    "Rules:\n"
    '- "text" is copied exactly as written, in its original script.\n'
    '- "box" is [x0,y0,x1,y1] as integers from 0 to 1000 relative to the whole image, '
    "origin top left, tightly around that text only.\n"
    "- List each occurrence separately. If unsure whether something is an identifier, list it.\n"
    f"- category is one of: {', '.join(CATEGORIES)}.\n"
    'Reply with JSON only: {"identifiers":[{"text":"...","category":"...","box":[0,0,0,0]}]}'
)


@dataclass(frozen=True)
class AiHit:
    text: str
    category: str
    boxes: tuple[Box, ...]


def _image_data_url(image: Image.Image) -> str:
    rgb = image.convert("RGB")
    longest = max(rgb.size)
    scale = MIN_SIDE / longest if longest < MIN_SIDE else MAX_SIDE / longest if longest > MAX_SIDE else 1.0
    if scale != 1.0:
        rgb = rgb.resize((round(rgb.width * scale), round(rgb.height * scale)), Image.LANCZOS)
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _parse_box(raw: object) -> Optional[Box]:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    if not all(isinstance(value, (int, float)) for value in raw):
        return None
    x0, y0, x1, y1 = (min(max(value / 1000, 0.0), 1.0) for value in raw)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def parse_vision_identifiers(raw: str) -> list[tuple[str, str, Optional[Box]]]:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    payload = json.loads(raw[start : end + 1])
    items = payload.get("identifiers") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("identifiers must be a list")

    parsed: list[tuple[str, str, Optional[Box]]] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ValueError("malformed identifier entry")
        text = item["text"].strip()
        if not text:
            continue
        category = str(item.get("category", "")).upper()
        parsed.append((text, category if category in CATEGORIES else FALLBACK_CATEGORY, _parse_box(item.get("box"))))
    return parsed


def _squash(text: str) -> str:
    return re.sub(r"[\s:.,;|_\-]+", "", text.lower())


def _line_boxes(ocr_lines: list[OcrLine], width: int, height: int) -> list[tuple[str, Box]]:
    boxes: list[tuple[str, Box]] = []
    for points, text in ocr_lines:
        if not text:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        boxes.append((text, (min(xs) / width, min(ys) / height, max(xs) / width, max(ys) / height)))
    return boxes


def _intersects(first: Box, second: Box) -> bool:
    return first[0] < second[2] and second[0] < first[2] and first[1] < second[3] and second[1] < first[3]


def _union(first: Box, second: Box) -> Box:
    return (min(first[0], second[0]), min(first[1], second[1]), max(first[2], second[2]), max(first[3], second[3]))


def _merge_overlapping(boxes: list[Box]) -> list[Box]:
    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        for first_index in range(len(merged)):
            for second_index in range(first_index + 1, len(merged)):
                if _intersects(merged[first_index], merged[second_index]):
                    merged[first_index] = _union(merged[first_index], merged[second_index])
                    del merged[second_index]
                    changed = True
                    break
            if changed:
                break
    return merged


def _pad(box: Box) -> Box:
    return (
        max(box[0] - PAD_X, 0.0),
        max(box[1] - PAD_Y, 0.0),
        min(box[2] + PAD_X, 1.0),
        min(box[3] + PAD_Y, 1.0),
    )


def _locate(text: str, model_box: Optional[Box], lines: list[tuple[str, Box]]) -> tuple[Box, ...]:
    needle = text.lower()
    squashed = _squash(text)
    boxes: list[Box] = []

    for line_text, (x0, y0, x1, y1) in lines:
        position = line_text.lower().find(needle)
        if position != -1:
            width = x1 - x0
            boxes.append(
                (
                    x0 + width * position / len(line_text),
                    y0,
                    x0 + width * (position + len(text)) / len(line_text),
                    y1,
                )
            )
            continue
        squashed_line = _squash(line_text)
        if len(squashed) < MIN_FUZZY_LENGTH or not squashed_line:
            continue
        if squashed in squashed_line or SequenceMatcher(None, squashed, squashed_line).ratio() >= FUZZY_RATIO:
            boxes.append((x0, y0, x1, y1))

    if model_box:
        boxes.append(model_box)
    return tuple(_pad(box) for box in _merge_overlapping(boxes))


def find_image_identifiers(
    image: Image.Image,
    ocr_lines: list[OcrLine],
    service: Optional[RedactionService] = None,
) -> list[AiHit]:
    model = os.environ.get("REDACTION_MODEL")
    if not model:
        raise DocumentProcessingError("REDACTION_MODEL is not set.")

    runner = service or RedactionService()
    content = [
        {"type": "text", "text": VISION_PROMPT},
        {"type": "image_url", "image_url": {"url": _image_data_url(image)}},
    ]
    lines = _line_boxes(ocr_lines, image.width, image.height)

    for _attempt in range(MAX_ATTEMPTS):
        reply = runner.complete(content, model)
        try:
            parsed = parse_vision_identifiers(reply)
        except ValueError:
            continue
        return [AiHit(text, category, _locate(text, box, lines)) for text, category, box in parsed]
    raise DocumentNeedsReviewError("The model reply could not be parsed.")
