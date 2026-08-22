from __future__ import annotations

from datetime import date

import pytest

from lawcorpus.retrieval.keyword_search import keyword_search


async def _pg_reachable(dsn: str) -> bool:
    try:
        import asyncpg
        conn = await asyncpg.connect(dsn=dsn, timeout=3)
        await conn.close()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_keyword_search_runs_against_real_db():
    """article_embedding이 아직 비어있어도(embed-backfill 전) 쿼리 자체는 에러 없이 빈
    리스트를 반환해야 한다 — 실제 결과 검증은 #47(임베딩 백필) 이후 별도."""
    from lawcorpus.config import get_settings
    from lawcorpus.db.pg import close_pg, init_pg

    settings = get_settings()
    if not await _pg_reachable(settings.pg_dsn):
        pytest.skip("실 DB(ops-vm)에 연결할 수 없음")

    await init_pg(settings.pg_dsn)
    try:
        hits = await keyword_search("실질과세", date.today())
        assert isinstance(hits, list)
    finally:
        await close_pg()
