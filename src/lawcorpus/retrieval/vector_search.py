from __future__ import annotations

from lawcorpus.db.pg import get_pool
from lawcorpus.types import Chunk


async def vector_search(
    embedding: list[float],
    top_k: int = 30,
    only_current: bool = True,
) -> list[Chunk]:
    pool = get_pool()
    current_filter = "AND is_current = TRUE" if only_current else ""

    article_sql = f"""
        SELECT chunk_id, text, law_name, article_no, clause_path, is_current,
               1 - (embedding <=> $1::vector) AS score
        FROM article_chunks
        WHERE embedding IS NOT NULL {current_filter}
        ORDER BY embedding <=> $1::vector
        LIMIT $2
    """
    case_sql = """
        SELECT chunk_id, text, case_no, court, validity_flag, decided_at,
               1 - (embedding <=> $1::vector) AS score
        FROM case_chunks
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> $1::vector
        LIMIT $2
    """
    vec = embedding
    async with pool.acquire() as conn:
        art_rows = await conn.fetch(article_sql, vec, top_k)
        case_rows = await conn.fetch(case_sql, vec, top_k)

    results: list[Chunk] = []
    for row in art_rows:
        results.append(Chunk(
            chunk_id=row["chunk_id"],
            table="article",
            text=row["text"],
            score=float(row["score"]),
            meta={
                "law_name": row["law_name"],
                "article_no": row["article_no"],
                "clause_path": row["clause_path"],
                "is_current": row["is_current"],
            },
        ))
    for row in case_rows:
        results.append(Chunk(
            chunk_id=row["chunk_id"],
            table="case",
            text=row["text"],
            score=float(row["score"]),
            meta={
                "case_no": row["case_no"],
                "court": row["court"],
                "validity_flag": row["validity_flag"],
                "decided_at": str(row["decided_at"]),
            },
        ))
    return sorted(results, key=lambda c: c.score, reverse=True)[:top_k]


async def hydrate_by_ids(chunk_ids: list[str]) -> list[Chunk]:
    """chunk_id 목록으로 PG에서 본문을 직접 fetch (검색 없이).

    그래프 확장(expand_1hop/2hop)으로 새로 발견됐지만 벡터/키워드 검색 후보 풀엔
    없던 chunk를 채우는 용도(pot-of-greed #8) — 이게 없으면 풀 밖에서 그래프로만
    발견한 청크는 본문을 가져올 방법이 없어 통째로 드롭된다.
    score=0.0 (검색 랭크가 없음 — expand_to_parents의 parent chunk와 동일 관례).
    """
    if not chunk_ids:
        return []

    pool = get_pool()
    async with pool.acquire() as conn:
        art_rows = await conn.fetch(
            "SELECT chunk_id, text, law_name, article_no, clause_path, is_current "
            "FROM article_chunks WHERE chunk_id = ANY($1)",
            chunk_ids,
        )
        case_rows = await conn.fetch(
            "SELECT chunk_id, text, case_no, court, validity_flag, decided_at "
            "FROM case_chunks WHERE chunk_id = ANY($1)",
            chunk_ids,
        )

    results: list[Chunk] = []
    for row in art_rows:
        results.append(Chunk(
            chunk_id=row["chunk_id"],
            table="article",
            text=row["text"],
            score=0.0,
            meta={
                "law_name": row["law_name"],
                "article_no": row["article_no"],
                "clause_path": row["clause_path"],
                "is_current": row["is_current"],
            },
        ))
    for row in case_rows:
        results.append(Chunk(
            chunk_id=row["chunk_id"],
            table="case",
            text=row["text"],
            score=0.0,
            meta={
                "case_no": row["case_no"],
                "court": row["court"],
                "validity_flag": row["validity_flag"],
                "decided_at": str(row["decided_at"]),
            },
        ))
    return results
