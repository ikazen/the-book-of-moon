"""시점 해소 — 모든 조회의 관문. refs.py를 대체한다.

as_of 없이 법령 상태를 묻는 건 허용하지 않는다(결정 H) — 과거 거래에 현행법을 적용하는
사고가 조용히 섞이는 걸 막는다. Python은 타입힌트를 런타임에 강제하지 않으므로
require_as_of가 그 역할을 대신한다.

resolve_citation은 설계문서 9절이 "최대 난관"이라 부른 부분이다: "구 OO법(1996.12.30.
법률 제5193호로 전부개정되고, 2003.12.30. 법률 제7010호로 개정되기 전의 것)"처럼 판례가
인용하는 법령은 현행이 아니라 판결 당시(또는 그보다 더 이전) 버전을 가리킬 수 있다.
법령명 매칭은 정적 정규식이 아니라 실제 적재된 statute.name/abbreviations에서 동적으로
구성한다 — "상속세 및 증여세법"처럼 공백이 낀 정식 명칭도 정확히 잡을 수 있다.
"""

from __future__ import annotations

import json
import re
from datetime import date

from lawcorpus.db.pg import get_pool
from lawcorpus.types import ArticleVersion

_LAW_ABBREV = {
    "조특법": "조세특례제한법",
    "국기법": "국세기본법",
}
# "(1996. 12. 30. 법률 제5193호로 전부개정되고, ...)" 괄호 안에서 첫 날짜만 뽑는다 —
# "개정되기 전의 것" 기준으로는 그 첫 날짜 시점의 버전을 찾는 게 목적에 맞는다.
_HISTORICAL_DATE_RE = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.")
_ARTICLE_NO_PATTERN = r"제(?P<art_no>\d+)조(?:의(?P<branch_no>\d+))?"


def require_as_of(as_of: date) -> date:
    if not isinstance(as_of, date):
        raise TypeError("as_of는 date 필수 — 기본값 today 금지(결정 H)")
    return as_of


def row_to_article_version(row) -> ArticleVersion:
    tree = row["tree"]
    return ArticleVersion(
        article_key=row["article_key"],
        moleg_article_key=row["moleg_article_key"],
        article_id=row["article_id"],
        title=row["title"],
        body=row["body"],
        tree=tree if isinstance(tree, dict) else json.loads(tree),
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        promulgated_on=row["promulgated_on"],
        promulgation_no=row["promulgation_no"],
        revision_type=row["revision_type"],
        is_full_rewrite=row["is_full_rewrite"],
        revision_reason=row["revision_reason"],
        ingested_at=row["ingested_at"],
    )


async def get_article(statute: str, art_no: int, branch_no: int, as_of: date) -> ArticleVersion | None:
    as_of = require_as_of(as_of)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT av.* FROM article_version av
            JOIN article a ON a.article_id = av.article_id
            JOIN statute s ON s.statute_id = a.statute_id
            WHERE s.name = $1 AND a.art_no = $2 AND a.art_branch_no = $3
              AND av.valid_from <= $4 AND (av.valid_to IS NULL OR av.valid_to > $4)
            """,
            statute, art_no, branch_no, as_of,
        )
    return row_to_article_version(row) if row else None


async def get_article_by_id(article_id: int, as_of: date) -> ArticleVersion | None:
    """article_id(논리 조문, 그래프 질의 결과 등에서 얻은 값)로 시점 해소한다.
    get_article은 (statute, art_no, branch_no)로 사람이 알아보는 식별자를 받지만
    그래프 질의는 article_id만 돌려주므로 이 경로가 따로 필요하다."""
    as_of = require_as_of(as_of)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM article_version
            WHERE article_id = $1 AND valid_from <= $2 AND (valid_to IS NULL OR valid_to > $2)
            """,
            article_id, as_of,
        )
    return row_to_article_version(row) if row else None


async def get_effective_law(statute: str, as_of: date) -> list[ArticleVersion]:
    as_of = require_as_of(as_of)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT av.* FROM article_version av
            JOIN article a ON a.article_id = av.article_id
            JOIN statute s ON s.statute_id = a.statute_id
            WHERE s.name = $1
              AND av.valid_from <= $2 AND (av.valid_to IS NULL OR av.valid_to > $2)
            ORDER BY a.art_no, a.art_branch_no
            """,
            statute, as_of,
        )
    return [row_to_article_version(r) for r in rows]


def _build_citation_regex(law_names: list[str]) -> re.Pattern:
    # 긴 이름을 먼저 시도해야 짧은 이름이 부분 매칭으로 가로채지 않는다
    ordered = sorted(set(law_names), key=len, reverse=True)
    law_alt = "|".join(re.escape(n) for n in ordered)
    return re.compile(
        rf"(?P<old>구\s*)?(?P<law>{law_alt})"
        rf"(?:\s*\((?P<detail>[^)]*)\))?"
        rf"\s*{_ARTICLE_NO_PATTERN}"
    )


def parse_citation(text: str, law_names: list[str]) -> dict | None:
    """text에서 (law, art_no, branch_no, historical_date)를 추출한다.

    law_names: 매칭 대상 법령명/약칭 목록(보통 실제 적재된 statute.name/abbreviations).
    반환값이 None이면 알려진 법령명을 못 찾았거나 조문번호가 없는 것 — 호출부가
    보수적으로 "인용 해소 실패"로 처리해야 한다.
    """
    if not law_names:
        return None
    m = _build_citation_regex(law_names).search(text)
    if not m:
        return None

    law = _LAW_ABBREV.get(m.group("law"), m.group("law"))
    historical_date = None
    detail = m.group("detail")
    if detail:
        date_match = _HISTORICAL_DATE_RE.search(detail)
        if date_match:
            year, month, day = map(int, date_match.groups())
            historical_date = date(year, month, day)

    return {
        "law": law,
        "art_no": int(m.group("art_no")),
        "branch_no": int(m.group("branch_no")) if m.group("branch_no") else 0,
        "historical_date": historical_date,
    }


async def _known_law_names(conn) -> list[str]:
    rows = await conn.fetch("SELECT name, abbreviations FROM statute")
    names: set[str] = set(_LAW_ABBREV.keys())
    for row in rows:
        names.add(row["name"])
        names.update(row["abbreviations"] or [])
    return list(names)


async def resolve_citation(text: str, decided_on: date | None = None) -> ArticleVersion | None:
    """인용 텍스트를 판결/해석 당시(또는 인용문 자체가 명시한 더 이전 시점) 유효 버전으로 해소한다.

    decided_on이 None이면 "현재" 기준으로 해소한다 — as_of 필수 규칙(결정 H)과 모순되지
    않는다: 이건 인자를 생략한 게 아니라 호출부가 "결정일 모름 = 지금 기준"이라고
    명시적으로 선택한 것이다.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        law_names = await _known_law_names(conn)

    parsed = parse_citation(text, law_names)
    if parsed is None:
        return None

    anchor = parsed["historical_date"] or decided_on or date.today()
    return await get_article(parsed["law"], parsed["art_no"], parsed["branch_no"], anchor)
