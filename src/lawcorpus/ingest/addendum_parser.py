"""부칙(附則) 원문 파싱. 법제처 API는 부칙을 구조화하지 않고 CDATA 원문 그대로 준다 —
①②③... 표기와 괄호 표제(예: "①(시행일)")로 항목을 스스로 분리해야 한다.

실측(the-book-of-moon #23, 국세기본법 75개 부칙단위) 기준 표제는 "시행일"/"동전"/"폐지법률"
같은 정확히 일치하는 것도 있고 "OO에 관한 적용례"/"OO에 관한 경과조치"처럼 접미사만 일치하는
것도 있다 — 부분 문자열 매칭으로 분류한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from lawcorpus.ingest.models import RawAddendumUnit

_CIRCLED_NUM_RE = re.compile(r"[①-⑳]")
_LABEL_RE = re.compile(r"^\(([^)]+)\)\s*")
_DATE_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")


@dataclass(frozen=True, slots=True)
class MappedAddendumItem:
    clause_no: str          # "1", "2" (①→1 정규화)
    body: str
    kind: str                # 시행일/적용례/경과조치/특례
    applies_from: date | None
    promulgation_no: int | None


def _split_items(body: str) -> list[tuple[str, str, str]]:
    """(항목번호, 표제, 본문) 목록. 표제가 없으면 빈 문자열."""
    markers = list(_CIRCLED_NUM_RE.finditer(body))
    if not markers:
        return [("1", "", body.strip())] if body.strip() else []

    items: list[tuple[str, str, str]] = []
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(body)
        chunk = body[marker.end():end].strip()
        label_match = _LABEL_RE.match(chunk)
        label = label_match.group(1) if label_match else ""
        text = chunk[label_match.end():].strip() if label_match else chunk
        item_no = str(ord(marker.group()) - 0x245F)  # ①=U+2460 -> 1
        items.append((item_no, label, text))
    return items


def _classify_kind(label: str, previous_kind: str) -> str:
    if label == "동전":
        return previous_kind  # "동전"(同前) = 바로 앞 항목과 같은 분류
    if label == "시행일":
        return "시행일"
    if "적용례" in label:
        return "적용례"
    if "경과조치" in label:
        return "경과조치"
    return "특례"


def _extract_applies_from(text: str) -> date | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    year, month, day = map(int, m.groups())
    return date(year, month, day)


def _promulgation_no(raw: str) -> int | None:
    digits = raw.strip().lstrip("0")
    return int(digits) if digits.isdigit() else None


def parse_addendum(unit: RawAddendumUnit) -> list[MappedAddendumItem]:
    promulgation_no = _promulgation_no(unit.promulgation_no)
    items: list[MappedAddendumItem] = []
    previous_kind = "특례"

    for clause_no, label, text in _split_items(unit.body):
        kind = _classify_kind(label, previous_kind)
        previous_kind = kind
        applies_from = _extract_applies_from(text) if kind == "시행일" else None
        items.append(
            MappedAddendumItem(
                clause_no=clause_no,
                body=text,
                kind=kind,
                applies_from=applies_from,
                promulgation_no=promulgation_no,
            )
        )
    return items
