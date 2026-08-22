"""pgvector 코사인 유사도 검색. article_embedding 대상, is_current 부분 인덱스(HNSW)가
기본 경로다 — 과거 시점 검색은 별도 경로(현재는 과거 버전을 임베딩하지 않으므로 빈 결과,
결정 P)로 분리해 기본 경로가 항상 HNSW 인덱스를 타도록 한다.
"""

from __future__ import annotations

from datetime import date

from lawcorpus.db.pg import get_pool
from lawcorpus.resolution import require_as_of
from lawcorpus.retrieval.embedder import embed_query
from lawcorpus.types import Hit


async def vector_search(query: str, as_of: date, settings, top_n: int = 30) -> list[Hit]:
    """as_of가 오늘(또는 현재 유효 범위)이면 HNSW 부분 인덱스(is_current)를 타는 빠른 경로,
    아니면 article_version 조인으로 그 시점에 유효했던 버전만 거른다(현재는 과거 버전을
    임베딩하지 않아 결과가 항상 비지만, 쿼리 자체는 시점 무관하게 정확하다)."""
    as_of = require_as_of(as_of)
    vector = await embed_query(query, settings)

    pool = get_pool()
    async with pool.acquire() as conn:
        if as_of >= date.today():
            rows = await conn.fetch(
                """
                SELECT ae.chunk_id, ae.article_key, av.article_id, ae.chunk_path, ae.chunk_text,
                       1 - (ae.embedding <=> $1) AS score
                FROM article_embedding ae
                JOIN article_version av ON av.article_key = ae.article_key
                WHERE ae.is_current
                ORDER BY ae.embedding <=> $1
                LIMIT $2
                """,
                vector, top_n,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT ae.chunk_id, ae.article_key, av.article_id, ae.chunk_path, ae.chunk_text,
                       1 - (ae.embedding <=> $1) AS score
                FROM article_embedding ae
                JOIN article_version av ON av.article_key = ae.article_key
                WHERE av.valid_from <= $2 AND (av.valid_to IS NULL OR av.valid_to > $2)
                ORDER BY ae.embedding <=> $1
                LIMIT $3
                """,
                vector, as_of, top_n,
            )

    return [
        Hit(
            article_key=r["article_key"], article_id=r["article_id"],
            chunk_path=r["chunk_path"], text=r["chunk_text"], score=r["score"],
        )
        for r in rows
    ]
