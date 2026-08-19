from __future__ import annotations

from lawcorpus.db.pg import get_pool
from lawcorpus.types import Chunk


async def expand_to_parents(chunks: list[Chunk]) -> list[Chunk]:
    """small-to-big: 항/호 child chunk 를 소속 조(parent) chunk 로 확장.

    선별된 child(항/호)의 parent_chunk_id 로 조 전체 청크를 1쿼리로 fetch 한다.
    이미 입력에 있는 조 청크는 중복 제외. 판례(table != "article")는 계층이 없으므로 통과.
    반환값은 추가된 parent 청크만 — 호출부에서 기존 chunk 뒤에 덧붙인다.
    """
    child_ids = [c.chunk_id for c in chunks if c.table == "article"]
    if not child_ids:
        return []

    present = {c.chunk_id for c in chunks}

    pool = get_pool()
    sql = """
        SELECT DISTINCT p.chunk_id, p.text, p.law_name, p.article_no,
               p.clause_path, p.is_current
        FROM article_chunks c
        JOIN article_chunks p ON p.chunk_id = c.parent_chunk_id
        WHERE c.chunk_id = ANY($1)
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, child_ids)

    parents: list[Chunk] = []
    for row in rows:
        if row["chunk_id"] in present:
            continue
        present.add(row["chunk_id"])
        parents.append(Chunk(
            chunk_id=row["chunk_id"],
            table="article",
            text=row["text"],
            score=0.0,
            meta={
                "law_name": row["law_name"],
                "article_no": row["article_no"],
                "clause_path": row["clause_path"],
                "is_current": row["is_current"],
                "context_role": "parent",
            },
        ))
    return parents
