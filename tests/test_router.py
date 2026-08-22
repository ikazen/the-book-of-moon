from __future__ import annotations

from datetime import date

import pytest

from lawcorpus.router import route_direct


async def _pg_reachable(dsn: str) -> bool:
    try:
        import asyncpg
        conn = await asyncpg.connect(dsn=dsn, timeout=3)
        await conn.close()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_route_direct_resolves_explicit_citation_against_real_db():
    from lawcorpus.config import get_settings
    from lawcorpus.db.pg import close_pg, init_pg

    settings = get_settings()
    if not await _pg_reachable(settings.pg_dsn):
        pytest.skip("실 DB(ops-vm)에 연결할 수 없음")

    await init_pg(settings.pg_dsn)
    try:
        version = await route_direct("국세기본법 제2조에 따르면", date.today())
        assert version is not None
        assert version.valid_from <= date.today()
    finally:
        await close_pg()


@pytest.mark.asyncio
async def test_route_direct_returns_none_for_non_citation_query():
    from lawcorpus.config import get_settings
    from lawcorpus.db.pg import close_pg, init_pg

    settings = get_settings()
    if not await _pg_reachable(settings.pg_dsn):
        pytest.skip("실 DB(ops-vm)에 연결할 수 없음")

    await init_pg(settings.pg_dsn)
    try:
        version = await route_direct("실질과세 원칙이 적용되는 사례", date.today())
        assert version is None
    finally:
        await close_pg()
