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


# ---------------------------------------------------------------------------
# target=eflaw (시행일 기준 현행법령) — bitemporal 인제스트용 신규 타입.
# 실측(the-book-of-moon #23) 기반: 항/호/목 3단 계층, 조문여부="전문"인 항목은
# 편/장/절 헤딩(실제 조문이 아님), 조문키는 법령 문서 내에서만 유일하다.
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class RawItem:       # 목(目)
    no: str          # "가"
    text: str        # 목내용


@dataclass(frozen=True, slots=True)
class RawEfSubClause:  # 호(号)
    no: str            # "1"
    text: str          # 호내용
    items: tuple[RawItem, ...] = ()


@dataclass(frozen=True, slots=True)
class RawEfClause:     # 항(項)
    no: str            # "1" (①→1 정규화), 항번호 없는 단일 문단이면 ""
    text: str          # 항내용
    sub_clauses: tuple[RawEfSubClause, ...] = ()


@dataclass(frozen=True, slots=True)
class RawArticleUnit:  # 조문단위 — 실제 조문과 편/장/절 헤딩이 같은 태그를 공유한다
    jomun_key: str      # 조문키 (법령 문서 내에서만 유일 — moleg_article_key 조합에 mst와 함께 쓰임)
    art_no: int         # 조문번호
    branch_no: int      # 조문가지번호(가지 없으면 0)
    is_heading: bool    # 조문여부 == "전문" (편/장/절 헤딩 — 실제 조문 아님)
    title: str          # 조문제목
    body: str           # 조문내용 (헤딩이면 "제1장 총칙" 같은 제목 문자열)
    effective_from: str    # 조문시행일자 YYYYMMDD
    revision_type: str      # 조문제개정유형
    changed: bool           # 조문변경여부 == "Y"
    moved_from: str         # 조문이동이전 (전부개정 등으로 조문번호가 바뀐 경우)
    moved_to: str           # 조문이동이후
    clauses: tuple[RawEfClause, ...] = ()


@dataclass(frozen=True, slots=True)
class RawAddendumUnit:   # 부칙단위 — 구조화 안 된 원문(개별 항목 파싱은 addendum_parser 몫)
    addendum_key: str    # 부칙키
    promulgated_at: str  # 부칙공포일자 YYYYMMDD
    promulgation_no: str  # 부칙공포번호
    body: str             # 부칙내용 (여러 CDATA 줄을 개행으로 합친 원문)


@dataclass(frozen=True, slots=True)
class RawEfLaw:
    law_id: str            # 법령ID
    mst: str                # 법령일련번호
    law_name: str            # 법령명_한글
    law_type: str             # 법종구분 (법률/대통령령/부령 등)
    ministry_code: str         # 소관부처코드
    promulgated_on: str          # 공포일자 YYYYMMDD
    promulgation_no: str          # 공포번호
    revision_type: str              # 제개정구분
    enforced_on: str                 # 시행일자 YYYYMMDD
    articles: tuple[RawArticleUnit, ...] = ()
    addenda: tuple[RawAddendumUnit, ...] = ()
    revision_reason: str = ""   # 제개정이유내용 (기재부 PDF 대신 법제처가 이미 제공)
    raw_uri: str = ""           # 원본 XML의 storage.raw_store 저장 위치 (s3:// 또는 file://)


@dataclass(frozen=True, slots=True)
class RawLawHierarchyEntry:   # lsStmd 상하위법 트리의 한 노드
    law_id: str
    mst: str
    law_name: str
    law_type: str     # 법종구분: 법률/대통령령/부령/훈령/고시 등 (raw 그대로, 분류는 매퍼 몫)
    enforced_on: str


@dataclass(frozen=True, slots=True)
class RawLawHierarchy:    # target=lsStmd 응답 — 법률 -> 시행령 -> 시행규칙 -> 행정규칙
    law_id: str
    mst: str
    law_name: str
    entries: tuple[RawLawHierarchyEntry, ...] = ()
