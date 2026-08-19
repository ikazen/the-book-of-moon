"""
법제처 OPEN API 응답을 담는 raw dataclass.

API 응답 XML 필드를 최대한 그대로 보존하고, 매퍼(law_mapper/case_mapper)에서
DB row 형태로 변환한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawLawListItem:
    law_id: str       # 법령ID
    law_name: str     # 법령명한글
    mst: str          # MST (법령 마스터 ID — fetch_law에 사용)
    effective_date: str  # 시행일자 YYYYMMDD
    is_current: bool  # 현행연혁코드 == "현행"


@dataclass
class RawSubClause:   # 호(号)
    no: str           # 호번호 "1"
    text: str         # 호내용


@dataclass
class RawClause:      # 항(項)
    no: str           # 항번호 "1"
    text: str         # 항내용
    sub_clauses: list[RawSubClause] = field(default_factory=list)


@dataclass
class RawArticle:     # 조문단위 — 조(條) 레벨
    no: str           # 조문번호 "14"
    title: str        # 조문제목
    text: str         # 조문내용 (전문, 조번호 포함)
    effective_from: str   # 시행일자 YYYYMMDD
    clauses: list[RawClause] = field(default_factory=list)


@dataclass
class RawHistoryEntry:   # 연혁 항목
    promulgated_at: str  # 공포일자 YYYYMMDD
    effective_at: str    # 시행일자 YYYYMMDD
    law_id: str          # 해당 버전 법령ID


@dataclass
class RawLaw:
    law_name: str
    law_id: str
    mst: str
    effective_from: str          # 기본정보 시행일자 YYYYMMDD
    articles: list[RawArticle] = field(default_factory=list)
    history: list[RawHistoryEntry] = field(default_factory=list)


@dataclass
class RawCaseListItem:
    case_id: str     # 판례일련번호
    case_no: str     # 사건번호
    court: str       # 법원명
    decided_at: str  # 선고일자 YYYYMMDD
    case_type: str   # 사건종류명


@dataclass
class RawCase:
    case_id: str       # 판례일련번호
    case_no: str       # 사건번호
    court: str         # 법원명
    decided_at: str    # 선고일자 YYYYMMDD
    case_type: str     # 사건종류명
    holding: str       # 판시사항
    summary: str       # 판결요지
    body: str          # 판례내용
    ref_articles: list[str]  # 참조조문 (세미콜론/쉼표 분리 후 strip)
    ref_cases: list[str]     # 참조판례 (줄/세미콜론 분리 후 strip)
