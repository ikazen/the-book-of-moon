from __future__ import annotations

from datetime import date

import pytest

from lawcorpus.search import search


async def _pg_reachable(dsn: str) -> bool:
    try:
        import asyncpg
        conn = await asyncpg.connect(dsn=dsn, timeout=3)
        await conn.close()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_search_router_direct_citation():
    from lawcorpus.config import get_settings
    from lawcorpus.db.neo4j import close_neo4j, init_neo4j
    from lawcorpus.db.pg import close_pg, init_pg

    settings = get_settings()
    if not await _pg_reachable(settings.pg_dsn):
        pytest.skip("실 DB(ops-vm)에 연결할 수 없음")

    await init_pg(settings.pg_dsn)
    await init_neo4j(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        results = await search("국세기본법 제14조", date.today(), settings)
        assert len(results) == 1
        assert results[0].version.article_id is not None
    finally:
        await close_pg()
        await close_neo4j()


@pytest.mark.asyncio
async def test_search_mixes_statute_and_subordinate_via_delegation():
    """시행령 위임 질의는 법률+시행령 조문이 혼재해서 회수돼야 한다(설계문서 6절 검증 기준) —
    국세기본법 제2조(정의)는 시행령 제1조의2로 위임하는 DELEGATES 엣지가 있다(실측 확인)."""
    from lawcorpus.config import get_settings
    from lawcorpus.db.neo4j import close_neo4j, init_neo4j
    from lawcorpus.db.pg import close_pg, init_pg
    from lawcorpus.graph_queries import expand_refs

    settings = get_settings()
    if not await _pg_reachable(settings.pg_dsn):
        pytest.skip("실 DB(ops-vm)에 연결할 수 없음")

    await init_pg(settings.pg_dsn)
    await init_neo4j(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        import asyncpg

        conn = await asyncpg.connect(dsn=settings.pg_dsn)
        row = await conn.fetchrow(
            """
            SELECT a.article_id FROM article a JOIN statute s ON s.statute_id = a.statute_id
            WHERE s.name = '국세기본법' AND a.art_no = 2 AND a.art_branch_no = 0
            """
        )
        await conn.close()
        assert row is not None

        subgraph = await expand_refs(row["article_id"], date.today(), hops=1)
        assert len(subgraph.article_ids) > 1
        assert any(t == "DELEGATES" for _, t, _ in subgraph.edges)
    finally:
        await close_pg()
        await close_neo4j()


@pytest.mark.asyncio
async def test_search_returns_ranked_results_for_free_text_query():
    from lawcorpus.config import get_settings
    from lawcorpus.db.neo4j import close_neo4j, init_neo4j
    from lawcorpus.db.pg import close_pg, init_pg

    settings = get_settings()
    if not await _pg_reachable(settings.pg_dsn):
        pytest.skip("실 DB(ops-vm)에 연결할 수 없음")

    await init_pg(settings.pg_dsn)
    await init_neo4j(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        results = await search("실질과세 원칙", date.today(), settings, top_k=5)
        assert results
        assert all(r.version.valid_from <= date.today() for r in results)
    finally:
        await close_pg()
        await close_neo4j()
