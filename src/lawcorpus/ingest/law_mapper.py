"""
RawLaw → article_chunks DB row + Neo4j 노드/관계 매핑.

결정:
  조(條) = PG parent chunk (clause_path=None, parent_chunk_id=None) — Neo4j 제외
  항(項) = PG child chunk (parent_chunk_id=조) + Neo4j CorpusArticle 노드
  계층 표현은 PG parent_chunk_id fetch만 사용 (그래프에 계층 엣지 없음)

chunk_id 규약:
  조: art_<법령명>_<조번호>  예) art_소득세법_14
  항: art_<법령명>_<조번호>_<항번호>  예) art_소득세법_14_1
  개정: amend_<법령명>_<연도>_<공포일자>  예) amend_소득세법_20231231
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from lawcorpus.ingest.models import RawLaw


@dataclass
class ArticleRow:
    chunk_id: str
    law_name: str
    article_no: str       # "제14조"
    clause_path: str | None
    parent_chunk_id: str | None
    text: str
    effective_from: date
    effective_to: date | None
    is_current: bool


@dataclass
class AmendmentRow:
    amendment_id: str
    law_name: str
    article_no: str       # "" = 법령 전체 개정
    amended_at: str       # YYYYMMDD (Neo4j/PG 둘 다 str로 저장)
    summary: str


@dataclass
class MappedLaw:
    pg_rows: list[ArticleRow] = field(default_factory=list)
    neo4j_chunk_ids: list[str] = field(default_factory=list)   # 항 레벨만
    amendments: list[AmendmentRow] = field(default_factory=list)
    amended_by: list[tuple[str, str]] = field(default_factory=list)  # (chunk_id, amendment_id)


def _to_date(yyyymmdd: str) -> date:
    s = yyyymmdd.strip()
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def map_law(raw: RawLaw) -> MappedLaw:
    result = MappedLaw()

    # 연혁 → Amendment 노드 (법령 전체 개정 이벤트)
    amend_date_to_id: dict[str, str] = {}
    for h in raw.history:
        amend_id = f"amend_{raw.law_name}_{h.promulgated_at}"
        if amend_id not in amend_date_to_id.values():
            amend_date_to_id[h.effective_at] = amend_id
            result.amendments.append(
                AmendmentRow(
                    amendment_id=amend_id,
                    law_name=raw.law_name,
                    article_no="",
                    amended_at=h.effective_at,
                    summary=f"{raw.law_name} {h.promulgated_at} 공포, {h.effective_at} 시행",
                )
            )

    for art in raw.articles:
        # art.no는 "18의3"(가지번호 포함) 형식 — "제N조의M" 순서로 조립해야
        # 정상 표기가 된다(#40, "제18의3조"는 인용 검증 정규식과 어긋난다).
        base_no, _, branch_no = art.no.partition("의")
        art_no_label = f"제{base_no}조의{branch_no}" if branch_no else f"제{base_no}조"
        parent_id = f"art_{raw.law_name}_{art.no}"
        eff_from = _to_date(art.effective_from)

        # 조 parent — PG only
        parent_row = ArticleRow(
            chunk_id=parent_id,
            law_name=raw.law_name,
            article_no=art_no_label,
            clause_path=None,
            parent_chunk_id=None,
            text=art.text or art_no_label,
            effective_from=eff_from,
            effective_to=None,
            is_current=True,
        )
        result.pg_rows.append(parent_row)

        if art.effective_from in amend_date_to_id:
            result.amended_by.append((parent_id, amend_date_to_id[art.effective_from]))

        if art.clauses:
            for clause in art.clauses:
                # 항 text = 항내용 + 호 목록 인라인
                clause_text = clause.text
                if clause.sub_clauses:
                    sub_part = " ".join(
                        f"{s.no}. {s.text}" for s in clause.sub_clauses
                    )
                    clause_text = f"{clause_text} {sub_part}"

                child_id = f"{parent_id}_{clause.no}"
                child_row = ArticleRow(
                    chunk_id=child_id,
                    law_name=raw.law_name,
                    article_no=art_no_label,
                    clause_path=f"제{clause.no}항",
                    parent_chunk_id=parent_id,
                    text=clause_text,
                    effective_from=eff_from,
                    effective_to=None,
                    is_current=True,
                )
                result.pg_rows.append(child_row)
                result.neo4j_chunk_ids.append(child_id)

                if art.effective_from in amend_date_to_id:
                    result.amended_by.append((child_id, amend_date_to_id[art.effective_from]))
        else:
            # 항 없는 조문 — 조 자체를 Neo4j에도 등록 (참조조문 타겟이 될 수 있음)
            result.neo4j_chunk_ids.append(parent_id)

    return result
