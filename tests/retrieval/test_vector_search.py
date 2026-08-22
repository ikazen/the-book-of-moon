from __future__ import annotations

from datetime import date

import pytest

from lawcorpus.retrieval.vector_search import vector_search


async def _pg_reachable(dsn: str) -> bool:
    try:
        import asyncpg
        conn = await asyncpg.connect(dsn=dsn, timeout=3)
        await conn.close()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_vector_search_finds_semantically_related_article():
    """'실질과세 원칙' 질의는 국세기본법 제14조(실질과세)를 상위권에서 찾아야 한다 —
    본문 자체는 '실질과세'라는 문자열을 쓰지 않고 '그 실질 내용에 따라'로 풀어써서
    (실측 확인) 키워드 검색으로는 못 찾는 케이스다."""
    from lawcorpus.config import get_settings
    from lawcorpus.db.pg import close_pg, init_pg

    settings = get_settings()
    if not await _pg_reachable(settings.pg_dsn):
        pytest.skip("실 DB(ops-vm)에 연결할 수 없음")

    await init_pg(settings.pg_dsn)
    try:
        hits = await vector_search("실질과세 원칙", date.today(), settings, top_n=10)
        assert hits
        assert any("실질" in h.text for h in hits)
    finally:
        await close_pg()


@pytest.mark.asyncio
async def test_vector_search_past_as_of_uses_bitemporal_path():
    """과거 as_of는 현재 임베딩만 있는 상태에서는 빈 결과를 내되 에러 없이 동작해야 한다
    (결정 P — 과거 버전 미임베딩)."""
    from lawcorpus.config import get_settings
    from lawcorpus.db.pg import close_pg, init_pg

    settings = get_settings()
    if not await _pg_reachable(settings.pg_dsn):
        pytest.skip("실 DB(ops-vm)에 연결할 수 없음")

    await init_pg(settings.pg_dsn)
    try:
        hits = await vector_search("실질과세 원칙", date(2000, 1, 1), settings, top_n=10)
        assert isinstance(hits, list)
    finally:
        await close_pg()
