from __future__ import annotations

from lawcorpus.db.pg import get_pool
from lawcorpus.types import Chunk


async def keyword_search(query: str, top_k: int = 30) -> list[Chunk]:
    pool = get_pool()

    article_sql = """
        SELECT chunk_id, text, law_name, article_no, clause_path, is_current,
               ts_rank(tsv, plainto_tsquery('simple', $1)) AS score
        FROM article_chunks
        WHERE tsv @@ plainto_tsquery('simple', $1)
        ORDER BY score DESC
        LIMIT $2
    """
    case_sql = """
        SELECT chunk_id, text, case_no, court, validity_flag, decided_at,
               ts_rank(tsv, plainto_tsquery('simple', $1)) AS score
        FROM case_chunks
        WHERE tsv @@ plainto_tsquery('simple', $1)
        ORDER BY score DESC
        LIMIT $2
    """
    async with pool.acquire() as conn:
        art_rows = await conn.fetch(article_sql, query, top_k)
        case_rows = await conn.fetch(case_sql, query, top_k)

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
