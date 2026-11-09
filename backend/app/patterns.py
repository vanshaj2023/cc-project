import re
from dataclasses import dataclass

CATEGORIES = ("email", "phone", "card", "iban", "tax_id", "ssn", "date", "url", "ip", "custom")


@dataclass(frozen=True)
class Match:
    start: int
    end: int
    category: str
    text: str


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _is_card(raw: str) -> bool:
    digits = re.sub(r"\D", "", raw)
    return 13 <= len(digits) <= 19 and _luhn_valid(digits)


def _is_phone(raw: str) -> bool:
    digits = re.sub(r"\D", "", raw)
    return 9 <= len(digits) <= 15


_PATTERNS: list[tuple[str, re.Pattern[str], object]] = [
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), None),
    ("url", re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE), None),
    (
        "iban",
        re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b"),
        None,
    ),
    (
        "tax_id",
        re.compile(r"\b[A-Z]{6}\d{2}[A-EHLMPR-T]\d{2}[A-Z]\d{3}[A-Z]\b", re.IGNORECASE),
        None,
    ),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), None),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b"), _is_card),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), None),
    ("date", re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b"), None),
    (
        "phone",
        re.compile(r"(?<![\w/])(?:\+\d{1,3}[ .-]?)?(?:\(?\d{2,4}\)?[ .-]?){2,4}\d{2,4}(?![\w/])"),
        _is_phone,
    ),
]


def parse_keywords(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,\n]", raw) if item.strip()]


def find_matches(text: str, categories: set[str], keywords: list[str]) -> list[Match]:
    candidates: list[Match] = []

    for keyword in keywords:
        for found in re.finditer(re.escape(keyword), text, re.IGNORECASE):
            candidates.append(Match(found.start(), found.end(), "custom", found.group()))

    for category, pattern, validator in _PATTERNS:
        if category not in categories:
            continue
        for found in pattern.finditer(text):
            value = found.group().strip()
            if validator is not None and not validator(value):
                continue
            start = found.start() + (len(found.group()) - len(found.group().lstrip()))
            candidates.append(Match(start, start + len(value), category, value))

    return _drop_overlaps(candidates)


def _drop_overlaps(candidates: list[Match]) -> list[Match]:
    ordered = sorted(candidates, key=lambda match: (match.start, -(match.end - match.start)))
    kept: list[Match] = []
    for match in ordered:
        if kept and match.start < kept[-1].end:
            continue
        kept.append(match)
    return kept
