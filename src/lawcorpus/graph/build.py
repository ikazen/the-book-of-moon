"""Neo4j 전량 재생성. PG(SoT)에서 읽어 그래프를 통째로 다시 만든다 — 증분 동기화 버그를
원천 차단하는 전략(설계문서 3.3). 규모가 작아 수 분이면 끝난다.

DELEGATES/REFERS_TO/MUTATIS 엣지는 아직 PG에 저장돼 있지 않아(#31은 추출 함수만 만들었다)
이 빌더가 statute별로 lsDelegated를 다시 조회해서 즉석 반영한다 — "PG만으로 재생성"
원칙에서 벗어나는 임시 타협이다. 엣지의 valid_from/valid_to는 lsDelegated가 현재 스냅샷
기준이라 statute.enforced_on ~ NULL(열림)로 근사한다 — 정밀한 시점 이력은 다중 스냅샷을
적재해야 가능하다.
"""

from __future__ import annotations

import asyncpg
from neo4j import AsyncGraphDatabase

from lawcorpus.graph.extract_refs import extract_defines, extract_delegation_edges
from lawcorpus.ingest.law_api import fetch_law_delegations

_MANAGED_LABELS = (
    "Statute", "Article", "Version", "Addendum", "Ruling",
    "Term", "Doctrine", "Pattern", "Loophole",
)


async def _wipe_managed_labels(session) -> None:
    label_match = " OR ".join(f"n:{label}" for label in _MANAGED_LABELS)
    await session.run(f"MATCH (n) WHERE {label_match} DETACH DELETE n")


async def _build_statutes(pg_conn: asyncpg.Connection, session) -> list[dict]:
    rows = await pg_conn.fetch("SELECT statute_id, name, law_type, parent_id, current_mst, enforced_on FROM statute")
    for row in rows:
        await session.run(
            "MERGE (s:Statute {statute_id: $id}) SET s.name = $name, s.law_type = $law_type",
            id=row["statute_id"], name=row["name"], law_type=row["law_type"],
        )
    for row in rows:
        if row["parent_id"] is not None:
            await session.run(
                """
                MATCH (child:Statute {statute_id: $cid}), (parent:Statute {statute_id: $pid})
                MERGE (child)-[:DELEGATES_TO]->(parent)
                """,
                cid=row["statute_id"], pid=row["parent_id"],
            )
    return [dict(r) for r in rows]


async def _build_articles(pg_conn: asyncpg.Connection, session) -> list[dict]:
    rows = await pg_conn.fetch("SELECT article_id, statute_id, art_no, art_branch_no FROM article")
    for row in rows:
        await session.run(
            """
            MERGE (a:Article {article_id: $id})
            SET a.statute_id = $sid, a.art_no = $art_no, a.branch_no = $branch_no
            """,
            id=row["article_id"], sid=row["statute_id"], art_no=row["art_no"], branch_no=row["art_branch_no"],
        )
    return [dict(r) for r in rows]


async def _build_versions(pg_conn: asyncpg.Connection, session) -> None:
    rows = await pg_conn.fetch(
        "SELECT article_key, article_id, valid_from, valid_to, title "
        "FROM article_version ORDER BY article_id, valid_from"
    )
    previous_key: dict[int, int] = {}
    for row in rows:
        await session.run(
            """
            MERGE (v:Version {article_key: $key})
            SET v.valid_from = $valid_from, v.valid_to = $valid_to, v.title = $title
            """,
            key=row["article_key"],
            valid_from=str(row["valid_from"]),
            valid_to=str(row["valid_to"]) if row["valid_to"] else None,
            title=row["title"],
        )
        await session.run(
            "MATCH (a:Article {article_id: $aid}), (v:Version {article_key: $key}) MERGE (a)-[:HAS_VERSION]->(v)",
            aid=row["article_id"], key=row["article_key"],
        )
        prior = previous_key.get(row["article_id"])
        if prior is not None:
            # newer 버전이 older 버전을 SUPERSEDES(대체)한다
            await session.run(
                "MATCH (older:Version {article_key: $prior}), (newer:Version {article_key: $key}) "
                "MERGE (newer)-[:SUPERSEDES]->(older)",
                prior=prior, key=row["article_key"],
            )
        previous_key[row["article_id"]] = row["article_key"]


async def _build_delegation_edges(
    pg_conn: asyncpg.Connection, session, statutes: list[dict], settings,
) -> int:
    mst_to_statute = {row["current_mst"]: row for row in statutes if row["current_mst"]}
    article_lookup: dict[tuple[int, int, int], int] = {}
    for row in await pg_conn.fetch("SELECT article_id, statute_id, art_no, art_branch_no FROM article"):
        article_lookup[(row["statute_id"], row["art_no"], row["art_branch_no"])] = row["article_id"]

    edge_count = 0
    for statute in statutes:
        if not statute["current_mst"]:
            continue
        try:
            root = await fetch_law_delegations(statute["current_mst"], settings)
        except Exception as exc:
            print(f"[{statute['name']}] lsDelegated 조회 실패, 건너뜀: {exc}")
            continue

        valid_from = str(statute["enforced_on"]) if statute["enforced_on"] else None
        for edge in extract_delegation_edges(root):
            source_id = article_lookup.get((statute["statute_id"], edge.source_art_no, edge.source_branch_no))
            target_statute = mst_to_statute.get(edge.target_law_mst)
            if source_id is None or target_statute is None or edge.target_art_no is None:
                continue
            target_id = article_lookup.get(
                (target_statute["statute_id"], edge.target_art_no, edge.target_branch_no)
            )
            if target_id is None:
                continue

            await session.run(
                f"""
                MATCH (src:Article {{article_id: $sid}}), (dst:Article {{article_id: $did}})
                MERGE (src)-[r:{edge.edge_type}]->(dst)
                SET r.valid_from = $valid_from, r.valid_to = NULL
                """,
                sid=source_id, did=target_id, valid_from=valid_from,
            )
            edge_count += 1
    return edge_count


async def _build_defines_edges(pg_conn: asyncpg.Connection, session) -> int:
    rows = await pg_conn.fetch(
        "SELECT DISTINCT ON (article_id) article_id, body FROM article_version "
        "WHERE valid_to IS NULL ORDER BY article_id, valid_from DESC"
    )
    edge_count = 0
    for row in rows:
        for term in extract_defines(row["body"]):
            await session.run(
                "MERGE (t:Term {name: $term}) "
                "WITH t MATCH (a:Article {article_id: $aid}) MERGE (a)-[:DEFINES]->(t)",
                term=term, aid=row["article_id"],
            )
            edge_count += 1
    return edge_count


async def _build_patterns(pg_conn: asyncpg.Connection, session) -> None:
    rows = await pg_conn.fetch("SELECT code, description FROM pattern_type")
    for row in rows:
        await session.run(
            "MERGE (p:Pattern {pattern_type: $code}) SET p.description = $desc",
            code=row["code"], desc=row["description"],
        )


async def build_graph(settings) -> None:
    pg_conn = await asyncpg.connect(dsn=settings.pg_dsn)
    driver = AsyncGraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    try:
        async with driver.session() as session:
            await _wipe_managed_labels(session)

            statutes = await _build_statutes(pg_conn, session)
            print(f"Statute {len(statutes)}건")

            articles = await _build_articles(pg_conn, session)
            print(f"Article {len(articles)}건")

            await _build_versions(pg_conn, session)
            version_count = await pg_conn.fetchval("SELECT count(*) FROM article_version")
            print(f"Version {version_count}건 (HAS_VERSION/SUPERSEDES 포함)")

            edge_count = await _build_delegation_edges(pg_conn, session, statutes, settings)
            print(f"DELEGATES/REFERS_TO/MUTATIS {edge_count}건")

            defines_count = await _build_defines_edges(pg_conn, session)
            print(f"DEFINES {defines_count}건")

            await _build_patterns(pg_conn, session)
            print("Pattern 재생성 완료")
    finally:
        await pg_conn.close()
        await driver.close()
