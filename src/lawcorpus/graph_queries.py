"""그래프 질의 — Neo4j(파생 그래프)에서 논리 관계를 훑고, PG(SoT)로 시점 해소해 되돌린다.
retrieval/graph_expand.py(v0.x, 삭제됨)를 대체한다.

설계문서 5.4절의 4개 Cypher 질의를 그대로 구현 기반으로 삼는다 — "정의 불일치", "준용
사슬의 끝", "미개정 생존 구멍", "리스크 이웃"은 관계형으로 어렵고 그래프 순회가 자연스러운
부류라 Neo4j를 두는 값이 여기서 나온다.
"""

from __future__ import annotations

import asyncpg
from datetime import date

from lawcorpus.db.neo4j import get_driver
from lawcorpus.db.pg import get_pool
from lawcorpus.resolution import get_article_by_id, require_as_of
from lawcorpus.types import Article, ArticleVersion, Subgraph, TermDefinition, UnpatchedCandidate

_EXPAND_TYPES_DEFAULT = ("DELEGATES", "REFERS_TO", "MUTATIS")
_VALID_AT_CLAUSE = (
    "(rel.valid_from IS NULL OR date(rel.valid_from) <= date($as_of)) AND "
    "(rel.valid_to IS NULL OR date(rel.valid_to) > date($as_of))"
)


async def _fetch_article(conn: asyncpg.Connection, article_id: int) -> Article | None:
    row = await conn.fetchrow(
        "SELECT article_id, statute_id, art_no, art_branch_no, chapter_title FROM article WHERE article_id = $1",
        article_id,
    )
    return Article(**dict(row)) if row else None


async def expand_refs(
    article_id: int,
    as_of: date,
    hops: int = 2,
    types: tuple[str, ...] = _EXPAND_TYPES_DEFAULT,
) -> Subgraph:
    """DELEGATES/REFERS_TO/MUTATIS를 최대 hops까지 확장한다. as_of 시점에 유효한 엣지만 탄다."""
    as_of = require_as_of(as_of)
    rel_pattern = "|".join(types)
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            f"""
            MATCH path = (a:Article {{article_id: $id}})-[rels:{rel_pattern}*1..{hops}]->(other:Article)
            WHERE ALL(rel IN relationships(path) WHERE {_VALID_AT_CLAUSE})
            RETURN DISTINCT other.article_id AS article_id,
                   [rel IN relationships(path) |
                       [startNode(rel).article_id, type(rel), endNode(rel).article_id]] AS hops
            """,
            id=article_id, as_of=str(as_of),
        )
        records = [record async for record in result]

    article_ids = {article_id}
    edges: set[tuple[int, str, int]] = set()
    for record in records:
        article_ids.add(record["article_id"])
        for src, etype, dst in record["hops"]:
            edges.add((src, etype, dst))

    return Subgraph(article_ids=tuple(sorted(article_ids)), edges=tuple(sorted(edges)))


async def get_delegation_chain(article_id: int, as_of: date) -> list[ArticleVersion]:
    """법률 -> 시행령 -> 시행규칙처럼 위임을 타고 내려가는 가장 긴 경로를 시점 해소해 반환한다."""
    as_of = require_as_of(as_of)
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH path = (a:Article {article_id: $id})-[:DELEGATES*1..3]->(next:Article)
            RETURN [n IN nodes(path)[1..] | n.article_id] AS chain
            ORDER BY length(path) DESC LIMIT 1
            """,
            id=article_id,
        )
        record = await result.single()

    if record is None:
        return []

    versions = []
    for target_id in record["chain"]:
        version = await get_article_by_id(target_id, as_of)
        if version is not None:
            versions.append(version)
    return versions


async def get_mutatis_terminals(article_id: int, as_of: date) -> list[ArticleVersion]:
    """준용(MUTATIS) 사슬을 타고 들어가면 도달하는, 더 이상 준용하지 않는 실효 조문들."""
    as_of = require_as_of(as_of)
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH p = (a:Article {article_id: $id})-[:MUTATIS*1..4]->(end:Article)
            WHERE NOT (end)-[:MUTATIS]->()
            RETURN DISTINCT end.article_id AS article_id
            """,
            id=article_id,
        )
        records = [record async for record in result]

    versions = []
    for record in records:
        version = await get_article_by_id(record["article_id"], as_of)
        if version is not None:
            versions.append(version)
    return versions


async def find_term_conflicts(term: str, as_of: date) -> list[TermDefinition]:
    """같은 용어를 정의하는 조문들 — 서로 다른 법률에서 정의가 갈리는지는 statute_id로 판별한다."""
    require_as_of(as_of)
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (t:Term {name: $term})<-[:DEFINES]-(a:Article) "
            "RETURN DISTINCT a.article_id AS article_id, a.statute_id AS statute_id",
            term=term,
        )
        records = [record async for record in result]

    return [TermDefinition(term=term, article_id=r["article_id"], statute_id=r["statute_id"]) for r in records]


async def get_risk_neighbors(article_id: int) -> list[tuple[Article, int]]:
    """이 조문과 함께 인용되며 납세자가 패소한 조문 — 부인 리스크가 옮아 붙는 이웃."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (a:Article {article_id: $id})<-[:CITES]-(r:Ruling)-[:CITES]->(b:Article)
            WHERE r.outcome = '납세자패'
            RETURN b.article_id AS article_id, count(r) AS n ORDER BY n DESC
            """,
            id=article_id,
        )
        records = [record async for record in result]

    pool = get_pool()
    neighbors = []
    async with pool.acquire() as conn:
        for record in records:
            article = await _fetch_article(conn, record["article_id"])
            if article is not None:
                neighbors.append((article, record["n"]))
    return neighbors


async def find_unpatched(since: date) -> list[UnpatchedCandidate]:
    """납세자가 승소했는데 그 근거가 된 조문이 아직도 그대로 살아있는 경우 — 미개정 생존 구멍.
    실제 loophole_candidate 행으로 굳히는 건 #37(status/risk_score 배정)의 몫이다."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (r:Ruling)-[:CITES]->(a:Article)-[:HAS_VERSION]->(v:Version)
            WHERE r.outcome = '납세자승' AND date(r.decided_on) >= date($since)
              AND date(v.valid_from) <= date(r.decided_on) AND v.valid_to IS NULL
            RETURN DISTINCT a.article_id AS article_id, r.ruling_id AS ruling_id, r.decided_on AS decided_on
            ORDER BY r.decided_on DESC
            """,
            since=str(since),
        )
        records = [record async for record in result]

    return [
        UnpatchedCandidate(
            article_id=r["article_id"], ruling_id=r["ruling_id"],
            decided_on=date.fromisoformat(str(r["decided_on"])),
        )
        for r in records
    ]
