"""쿼리 라우팅 — 조문번호 인용이 명시적인 질의는 벡터/키워드 검색을 우회해 직접 조회한다.

"국세기본법 제14조" 같은 질의는 임베딩 유사도로 찾을 이유가 없다 — resolve_citation과
같은 파싱 로직(parse_citation)으로 정확히 그 조문 버전을 as_of 시점 기준으로 바로 반환한다.
"""

from __future__ import annotations

from datetime import date

from lawcorpus.db.pg import get_pool
from lawcorpus.resolution import _known_law_names, get_article, parse_citation, require_as_of
from lawcorpus.types import ArticleVersion


async def route_direct(query: str, as_of: date) -> ArticleVersion | None:
    """query가 명시적 조문 인용이면 해당 시점의 버전을 반환한다. 아니면 None
    (호출부가 검색 파이프라인으로 계속 진행해야 한다는 뜻)."""
    as_of = require_as_of(as_of)

    pool = get_pool()
    async with pool.acquire() as conn:
        law_names = await _known_law_names(conn)

    parsed = parse_citation(query, law_names)
    if parsed is None:
        return None

    anchor = parsed["historical_date"] or as_of
    return await get_article(parsed["law"], parsed["art_no"], parsed["branch_no"], anchor)
