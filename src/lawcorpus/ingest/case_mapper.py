"""
RawCase → case_chunks DB row + Neo4j 노드/관계 매핑.

관계 방향:
  (CorpusCase)-[:CITES]->(CorpusArticle)
  (CorpusCase)-[:BASED_ON]->(CorpusArticle)
  (older_case)-[:OVERRULED_BY]->(newer_case)  -- 구판례가 신판례에 의해 폐기

세무 스코핑 책임은 호출부(ingest-cases CLI)에 있음.
매퍼는 주어진 RawCase를 변환하고, 스코프 집합(known_article_ids)으로 유효 관계만 필터한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from lawcorpus.ingest.models import RawCase


@dataclass
class CaseRow:
    chunk_id: str
    case_no: str
    court: str
    decided_at: date
    is_en_banc: bool
    validity_flag: str   # 초기값 'valid' — update-validity가 수정
    text: str


@dataclass
class MappedCase:
    case_row: CaseRow
    cites: list[tuple[str, str]] = field(default_factory=list)     # (case_id, article_id)
    based_on: list[tuple[str, str]] = field(default_factory=list)  # subset of cites
    case_refs: list[tuple[str, str]] = field(default_factory=list) # (current, ref_case)
    overruled_by: list[tuple[str, str]] = field(default_factory=list)  # (old, current)


# ---------------------------------------------------------------------------
# 참조조문 텍스트 → chunk_id
# ---------------------------------------------------------------------------

def _ref_article_to_chunk_id(text: str) -> str | None:
    """
    "법인세법 제52조 제1항"    → "art_법인세법_52_1"
    "소득세법 제14조"          → "art_소득세법_14"
    "법인세법 제52조제1항"     → "art_법인세법_52_1"    (공백 없는 형태도 처리)
    "법인세법 제18조의3"       → "art_법인세법_18의3"   (가지번호, pot-of-greed #40)
    "법인세법 제18조의3 제1항" → "art_법인세법_18의3_1"
    """
    t = text.strip()
    # 가지번호 + 항 포함
    m = re.match(r"(.+?)\s*제(\d+)조의(\d+)\s*제(\d+)항", t)
    if m:
        law, art, branch, clause = m.groups()
        return f"art_{law.strip()}_{art}의{branch}_{clause}"
    # 가지번호만
    m = re.match(r"(.+?)\s*제(\d+)조의(\d+)", t)
    if m:
        law, art, branch = m.groups()
        return f"art_{law.strip()}_{art}의{branch}"
    # 항 포함
    m = re.match(r"(.+?)\s*제(\d+)조\s*제(\d+)항", t)
    if m:
        law, art, clause = m.groups()
        return f"art_{law.strip()}_{art}_{clause}"
    # 조만
    m = re.match(r"(.+?)\s*제(\d+)조", t)
    if m:
        law, art = m.groups()
        return f"art_{law.strip()}_{art}"
    return None


# ---------------------------------------------------------------------------
# 참조판례 텍스트 → 사건번호
# ---------------------------------------------------------------------------

_CASE_NO_RE = re.compile(r"선고\s+(\S+)\s+판결")
_CASE_NO_FALLBACK_RE = re.compile(r"\b(\d{4}[가-힣]+\d+)\b")


def _ref_case_to_no(text: str) -> str | None:
    m = _CASE_NO_RE.search(text)
    if m:
        return m.group(1)
    m = _CASE_NO_FALLBACK_RE.search(text)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# OVERRULED_BY 추출 — 본문 "...판결을 변경한다" 패턴
# ---------------------------------------------------------------------------

_OVERRULE_RE = re.compile(r"선고\s+(\S+)\s+판결을\s+변경한다")


def _extract_overruled_case_nos(body: str) -> list[str]:
    return _OVERRULE_RE.findall(body)


# ---------------------------------------------------------------------------
# is_en_banc 판정
# ---------------------------------------------------------------------------

def _detect_en_banc(case_type: str, body: str) -> bool:
    return "전원합의체" in case_type or "전원합의체" in body


# ---------------------------------------------------------------------------
# 메인 매퍼
# ---------------------------------------------------------------------------

def map_case(raw: RawCase, known_article_ids: set[str]) -> MappedCase | None:
    """
    known_article_ids: PG에 적재된 article chunk_id 집합.
    참조조문이 하나도 매칭되지 않으면 세무 스코프 밖 → None 반환.
    """
    case_id = f"case_{raw.case_no}"

    # 참조조문 → CITES/BASED_ON (스코프 필터)
    cites: list[tuple[str, str]] = []
    for ref in raw.ref_articles:
        chunk_id = _ref_article_to_chunk_id(ref)
        if chunk_id and chunk_id in known_article_ids:
            cites.append((case_id, chunk_id))

    if not cites:
        return None  # 세무 스코프 밖

    # BASED_ON = 첫 번째 참조조문 (핵심 근거)
    based_on = cites[:1]

    # 참조판례 → case_refs
    case_refs: list[tuple[str, str]] = []
    for ref in raw.ref_cases:
        ref_no = _ref_case_to_no(ref)
        if ref_no:
            case_refs.append((case_id, f"case_{ref_no}"))

    # OVERRULED_BY (구판례 → 현재 판례 방향)
    overruled_by: list[tuple[str, str]] = []
    for old_no in _extract_overruled_case_nos(raw.body):
        overruled_by.append((f"case_{old_no}", case_id))

    # 판례 text = 판시사항 + 판결요지 + 판례내용
    parts = [p for p in [raw.holding, raw.summary, raw.body] if p.strip()]
    text = "\n".join(parts)

    decided_at = date(
        int(raw.decided_at[:4]),
        int(raw.decided_at[4:6]),
        int(raw.decided_at[6:8]),
    )

    return MappedCase(
        case_row=CaseRow(
            chunk_id=case_id,
            case_no=raw.case_no,
            court=raw.court,
            decided_at=decided_at,
            is_en_banc=_detect_en_banc(raw.case_type, raw.body),
            validity_flag="valid",
            text=text,
        ),
        cites=cites,
        based_on=based_on,
        case_refs=case_refs,
        overruled_by=overruled_by,
    )
