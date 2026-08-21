"""bitemporal 법령 상태 공간의 도메인 타입. v0.x 플랫 청크 스토어의 Chunk/GraphChunk/ValidityFlag를 대체한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class Statute:
    statute_id: int
    name: str
    short_name: str | None
    law_type: str              # 법률/대통령령/부령/고시
    ministry_code: str | None
    parent_id: int | None      # 시행령 -> 법률
    current_mst: str | None
    abbreviations: tuple[str, ...]
    enforced_on: date | None


@dataclass(frozen=True, slots=True)
class Article:
    article_id: int
    statute_id: int
    art_no: int
    art_branch_no: int


@dataclass(frozen=True, slots=True)
class ArticleVersion:
    article_key: int
    moleg_article_key: str | None   # '{법령일련번호}:{조문키}'
    article_id: int
    title: str | None
    body: str
    tree: dict
    valid_from: date
    valid_to: date | None      # exclusive 상한. None = 현재 유효
    promulgated_on: date
    promulgation_no: int | None
    revision_type: str | None  # 제정/일부개정/전부개정
    is_full_rewrite: bool
    ingested_at: datetime


@dataclass(frozen=True, slots=True)
class Threshold:
    kind: str    # ratio/amount/period/headcount
    op: str      # >=, >, <=, <, ==
    value: float
    unit: str


@dataclass(frozen=True, slots=True)
class ArticleDiff:
    from_version: int
    to_version: int
    diff: dict
    added_thresholds: tuple[Threshold, ...]
    reason_text: str | None
    reason_source: str | None


@dataclass(frozen=True, slots=True)
class Addendum:
    addendum_id: int
    statute_id: int
    promulgation_no: int | None
    clause_no: str | None
    body: str
    kind: str | None           # 시행일/적용례/경과조치/특례
    applies_from: date | None
    target_articles: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Ruling:
    ruling_id: str
    source: str                # 대법원/조세심판원/국세청예규/법제처해석례
    case_no: str | None
    decided_on: date
    outcome: str | None        # 납세자승/납세자패/일부인용 (expc/detc는 None 허용)
    gist: str | None
    body: str | None
    body_available: bool
    cited_articles: tuple[int, ...]      # article_key
    cited_article_ids: tuple[int, ...]   # article_id (논리 레벨)
    anti_avoidance: tuple[str, ...]      # 실질과세/부당행위계산부인/단계거래
    raw_uri: str


@dataclass(frozen=True, slots=True)
class LoopholeCandidate:
    id: int
    article_id: int
    origin_ruling: str | None
    status: str                # alive/patched/partial/pending
    patched_by: int | None
    patched_on: date | None
    pattern_type: str | None
    claim_deadline: date | None
    risk_score: float | None
    confirmed_by: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class TermDefinition:
    term: str
    article_id: int
    statute_id: int


@dataclass(frozen=True, slots=True)
class Hit:
    """검색 결과 한 건. 재순위 등에서 score를 바꿀 때는 dataclasses.replace()로 새 인스턴스를 만든다."""

    article_key: int
    article_id: int
    chunk_path: str
    text: str
    score: float


@dataclass(frozen=True, slots=True)
class Subgraph:
    """expand_refs 등 그래프 확장 질의의 결과 — article_id(논리 조문) 기준."""

    article_ids: tuple[int, ...]
    edges: tuple[tuple[int, str, int], ...]  # (from_article_id, edge_type, to_article_id)
