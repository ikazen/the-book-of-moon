"""pg_trgm 기반 키워드 검색. tsvector 'simple'(결정 B)을 대체한다(결정 M) — 이 서버에
pg_bigm이 설치 불가하다고 실측 확인됐고, 조문번호 정확매칭은 router.py가 앞단에서 처리하므로
전문검색 백엔드의 형태소 정밀도 요구가 낮다.
"""

from __future__ import annotations

from datetime import date

from lawcorpus.db.pg import get_pool
from lawcorpus.resolution import require_as_of
from lawcorpus.types import Hit


async def keyword_search(query: str, as_of: date, top_n: int = 30) -> list[Hit]:
    """article_embedding.chunk_text에 대해 pg_trgm 유사도로 검색한다. as_of 시점에
    유효한 조문 버전의 청크만 대상으로 한다(결정 H — 시점 없는 검색은 허용 안 함)."""
    as_of = require_as_of(as_of)

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ae.chunk_id, ae.article_key, av.article_id, ae.chunk_path, ae.chunk_text,
                   similarity(ae.chunk_text, $1) AS score
            FROM article_embedding ae
            JOIN article_version av ON av.article_key = ae.article_key
            WHERE ae.chunk_text % $1
              AND av.valid_from <= $2 AND (av.valid_to IS NULL OR av.valid_to > $2)
            ORDER BY score DESC
            LIMIT $3
            """,
            query, as_of, top_n,
        )

    return [
        Hit(
            article_key=r["article_key"], article_id=r["article_id"],
            chunk_path=r["chunk_path"], text=r["chunk_text"], score=r["score"],
        )
        for r in rows
    ]
