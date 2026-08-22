"""CLI 서브커맨드 구현. asyncpg/neo4j 커넥션을 직접 열고 닫는다(lawcorpus.db 풀은 장수명 서버용)."""

from __future__ import annotations

import asyncio
import importlib.resources
import json
from datetime import date

import asyncpg
from neo4j import AsyncGraphDatabase
from pgvector.asyncpg import register_vector

from lawcorpus.ingest.case_mapper import MappedCase, map_case
from lawcorpus.ingest.law_api import (
    fetch_case,
    fetch_eflaw,
    fetch_law,
    fetch_law_hierarchy,
    list_cases,
    list_eflaws,
    list_laws,
)
from lawcorpus.ingest.law_mapper import MappedLaw, map_law
from lawcorpus.ingest.statute_mapper import MappedStatute, map_eflaw
from lawcorpus.retrieval.embedder import embed_batch


# ---------------------------------------------------------------------------
# ingest-laws
# ---------------------------------------------------------------------------

async def _upsert_law_pg(conn: asyncpg.Connection, mapped: MappedLaw) -> int:
    inserted = 0
    async with conn.transaction():
        for row in mapped.pg_rows:
            result = await conn.execute(
                """
                INSERT INTO article_chunks
                    (chunk_id, law_name, article_no, clause_path, parent_chunk_id,
                     text, effective_from, effective_to, is_current)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (chunk_id) DO NOTHING
                """,
                row.chunk_id, row.law_name, row.article_no,
                row.clause_path, row.parent_chunk_id, row.text,
                row.effective_from, row.effective_to, row.is_current,
            )
            if result == "INSERT 0 1":
                inserted += 1
    return inserted


async def _upsert_law_neo4j(session, mapped: MappedLaw) -> None:
    for chunk_id in mapped.neo4j_chunk_ids:
        row = next(r for r in mapped.pg_rows if r.chunk_id == chunk_id)
        await session.run(
            """
            MERGE (n:CorpusArticle {chunk_id: $chunk_id})
            SET n.law_name = $law_name,
                n.article_no = $article_no,
                n.effective_from = $effective_from,
                n.effective_to = $effective_to,
                n.is_current = $is_current
            """,
            chunk_id=chunk_id, law_name=row.law_name, article_no=row.article_no,
            effective_from=str(row.effective_from),
            effective_to=str(row.effective_to) if row.effective_to else None,
            is_current=row.is_current,
        )

    for amend in mapped.amendments:
        await session.run(
            """
            MERGE (n:CorpusAmendment {amendment_id: $amendment_id})
            SET n.law_name = $law_name,
                n.article_no = $article_no,
                n.amended_at = $amended_at,
                n.summary = $summary
            """,
            amendment_id=amend.amendment_id, law_name=amend.law_name,
            article_no=amend.article_no, amended_at=amend.amended_at,
            summary=amend.summary,
        )

    for chunk_id, amend_id in mapped.amended_by:
        await session.run(
            """
            MATCH (a:CorpusArticle {chunk_id: $cid})
            MATCH (m:CorpusAmendment {amendment_id: $mid})
            MERGE (a)-[:AMENDED_BY]->(m)
            """,
            cid=chunk_id, mid=amend_id,
        )


async def _ingest_one_law(law_name: str, pg_conn, neo4j_session, settings) -> None:
    print(f"[{law_name}] 검색 중...")
    items = await list_laws(law_name, settings)
    current = next((i for i in items if i.is_current), None)
    if not current:
        if items:
            current = items[0]
        else:
            print(f"[{law_name}] 검색 결과 없음, 건너뜀")
            return

    print(f"[{law_name}] MST={current.mst} 조회 중...")
    raw = await fetch_law(current.mst, settings)
    mapped = map_law(raw)

    pg_inserted = await _upsert_law_pg(pg_conn, mapped)
    await _upsert_law_neo4j(neo4j_session, mapped)

    print(
        f"[{law_name}] 완료: PG {len(mapped.pg_rows)}행(신규 {pg_inserted}), "
        f"Neo4j {len(mapped.neo4j_chunk_ids)}노드, Amendment {len(mapped.amendments)}건"
    )


async def ingest_laws(laws: list[str], settings) -> None:
    if not settings.law_api_oc:
        raise SystemExit("LAWCORPUS_LAW_API_OC가 설정되지 않았습니다.")

    pg_conn = await asyncpg.connect(dsn=settings.pg_dsn)
    await register_vector(pg_conn)
    driver = AsyncGraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    try:
        async with driver.session() as neo4j_session:
            for law_name in laws:
                try:
                    await _ingest_one_law(law_name, pg_conn, neo4j_session, settings)
                except Exception as exc:
                    print(f"[{law_name}] 오류: {exc}")

        total = await pg_conn.fetchval("SELECT count(*) FROM article_chunks")
        print(f"\n완료. article_chunks 전체: {total}행")
    finally:
        await pg_conn.close()
        await driver.close()


# ---------------------------------------------------------------------------
# ingest-statutes (bitemporal 신 스키마 — 현행 스냅샷 1건 적재)
# ---------------------------------------------------------------------------

async def _upsert_statute(conn: asyncpg.Connection, mapped: MappedStatute, parent_id: int | None) -> None:
    await conn.execute(
        """
        INSERT INTO statute (statute_id, name, law_type, ministry_code, current_mst, enforced_on, parent_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (statute_id) DO UPDATE SET
            current_mst = EXCLUDED.current_mst,
            enforced_on = EXCLUDED.enforced_on,
            parent_id = COALESCE(EXCLUDED.parent_id, statute.parent_id)
        """,
        mapped.statute_id, mapped.name, mapped.law_type, mapped.ministry_code,
        mapped.current_mst, mapped.enforced_on, parent_id,
    )


async def _get_or_create_article(
    conn: asyncpg.Connection, statute_id: int, art_no: int, branch_no: int, chapter_title: str | None,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO article (statute_id, art_no, art_branch_no, chapter_title)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (statute_id, art_no, art_branch_no) DO UPDATE SET
            chapter_title = COALESCE(EXCLUDED.chapter_title, article.chapter_title)
        RETURNING article_id
        """,
        statute_id, art_no, branch_no, chapter_title,
    )


async def _insert_article_versions(conn: asyncpg.Connection, mapped: MappedStatute) -> int:
    inserted = 0
    async with conn.transaction():
        for v in mapped.versions:
            article_id = await _get_or_create_article(conn, mapped.statute_id, v.art_no, v.branch_no, v.chapter_title)
            result = await conn.execute(
                """
                INSERT INTO article_version
                    (moleg_article_key, article_id, title, body, tree, valid_from,
                     promulgated_on, promulgation_no, revision_type, is_full_rewrite)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10)
                ON CONFLICT (article_id, valid_from) DO NOTHING
                """,
                v.moleg_article_key, article_id, v.title, v.body, json.dumps(v.tree),
                v.valid_from, v.promulgated_on, v.promulgation_no, v.revision_type, v.is_full_rewrite,
            )
            if result == "INSERT 0 1":
                inserted += 1
    return inserted


async def close_versions(conn: asyncpg.Connection, statute_id: int) -> int:
    """각 조문의 버전을 valid_from 순으로 훑어 valid_to(배타적 상한)를 다음 버전의
    valid_from으로 채운다. 가장 최근 버전만 valid_to=NULL(현재 유효)로 남는다."""
    rows = await conn.fetch(
        """
        SELECT av.article_key, av.article_id, av.valid_from
        FROM article_version av
        JOIN article a ON a.article_id = av.article_id
        WHERE a.statute_id = $1
        ORDER BY av.article_id, av.valid_from
        """,
        statute_id,
    )
    by_article: dict[int, list[tuple[int, date]]] = {}
    for row in rows:
        by_article.setdefault(row["article_id"], []).append((row["article_key"], row["valid_from"]))

    updated = 0
    async with conn.transaction():
        for versions in by_article.values():
            for i, (article_key, _valid_from) in enumerate(versions):
                valid_to = versions[i + 1][1] if i + 1 < len(versions) else None
                result = await conn.execute(
                    "UPDATE article_version SET valid_to = $1 WHERE article_key = $2 AND valid_to IS DISTINCT FROM $1",
                    valid_to, article_key,
                )
                if result == "UPDATE 1":
                    updated += 1
    return updated


async def _ingest_one_statute(conn: asyncpg.Connection, mst: str, settings, *, parent_id: int | None) -> MappedStatute:
    ef_law = await fetch_eflaw(mst, settings)
    mapped = map_eflaw(ef_law)
    await _upsert_statute(conn, mapped, parent_id)
    inserted = await _insert_article_versions(conn, mapped)
    await close_versions(conn, mapped.statute_id)
    print(f"[{mapped.name}] MST={mst} 완료: 조문버전 {len(mapped.versions)}건(신규 {inserted})")
    return mapped


async def ingest_statutes(laws: list[str], settings, *, include_subordinate: bool = False) -> None:
    """법령명별로 현재 시행 중인 eflaw 스냅샷 1건을 적재한다(설계문서 8절 2단계 — 이력 전량은
    별도로 각 MST에 ingest_statutes 재호출). include_subordinate=True면 체계도(lsStmd)로
    발견한 시행령/시행규칙도 같은 조문 트리 파이프라인으로 함께 적재하고, statute.parent_id를
    법률->시행령->시행규칙 순으로 체이닝한다(lsStmd 응답 자체가 이 순서로 중첩돼 있다)."""
    if not settings.law_api_oc:
        raise SystemExit("LAWCORPUS_LAW_API_OC가 설정되지 않았습니다.")

    conn = await asyncpg.connect(dsn=settings.pg_dsn)
    try:
        for law_name in laws:
            try:
                items = await list_eflaws(law_name, settings)
                current = next((i for i in items if i.is_current), None)
                if current is None:
                    print(f"[{law_name}] 현행 스냅샷을 찾지 못함, 건너뜀")
                    continue

                mapped = await _ingest_one_statute(conn, current.mst, settings, parent_id=None)

                if include_subordinate:
                    hierarchy = await fetch_law_hierarchy(current.mst, settings)
                    parent_id = mapped.statute_id
                    for entry in hierarchy.entries:
                        if entry.mst == current.mst:
                            continue
                        sub_mapped = await _ingest_one_statute(conn, entry.mst, settings, parent_id=parent_id)
                        parent_id = sub_mapped.statute_id  # 시행규칙은 시행령의 하위로 체이닝
            except Exception as exc:
                print(f"[{law_name}] 오류: {exc}")

        total = await conn.fetchval("SELECT count(*) FROM article_version")
        print(f"\n완료. article_version 전체: {total}행")
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# ingest-cases
# ---------------------------------------------------------------------------

async def _load_known_article_ids(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT chunk_id FROM article_chunks")
    return {r["chunk_id"] for r in rows}


async def _upsert_case_pg(conn: asyncpg.Connection, mapped: MappedCase) -> bool:
    r = mapped.case_row
    result = await conn.execute(
        """
        INSERT INTO case_chunks
            (chunk_id, case_no, court, decided_at, is_en_banc, validity_flag, text)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        ON CONFLICT (chunk_id) DO NOTHING
        """,
        r.chunk_id, r.case_no, r.court, r.decided_at,
        r.is_en_banc, r.validity_flag, r.text,
    )
    return result == "INSERT 0 1"


async def _upsert_case_neo4j(session, mapped: MappedCase) -> None:
    r = mapped.case_row
    await session.run(
        """
        MERGE (n:CorpusCase {chunk_id: $chunk_id})
        SET n.case_no = $case_no,
            n.court = $court,
            n.decided_at = $decided_at,
            n.is_en_banc = $is_en_banc,
            n.validity_flag = $validity_flag
        """,
        chunk_id=r.chunk_id, case_no=r.case_no, court=r.court,
        decided_at=str(r.decided_at), is_en_banc=r.is_en_banc,
        validity_flag=r.validity_flag,
    )

    for case_id, art_id in mapped.cites:
        await session.run(
            """
            MATCH (c:CorpusCase {chunk_id: $cid})
            MATCH (a:CorpusArticle {chunk_id: $aid})
            MERGE (c)-[:CITES]->(a)
            """,
            cid=case_id, aid=art_id,
        )

    for case_id, art_id in mapped.based_on:
        await session.run(
            """
            MATCH (c:CorpusCase {chunk_id: $cid})
            MATCH (a:CorpusArticle {chunk_id: $aid})
            MERGE (c)-[:BASED_ON]->(a)
            """,
            cid=case_id, aid=art_id,
        )

    # OVERRULED_BY: 구판례가 이미 Neo4j에 있을 때만 생성
    for old_id, new_id in mapped.overruled_by:
        await session.run(
            """
            MATCH (old:CorpusCase {chunk_id: $old_id})
            MATCH (new:CorpusCase {chunk_id: $new_id})
            MERGE (old)-[:OVERRULED_BY]->(new)
            """,
            old_id=old_id, new_id=new_id,
        )


async def ingest_cases(queries: list[str], settings, max_pages: int = 50) -> None:
    if not settings.law_api_oc:
        raise SystemExit("LAWCORPUS_LAW_API_OC가 설정되지 않았습니다.")

    pg_conn = await asyncpg.connect(dsn=settings.pg_dsn)
    await register_vector(pg_conn)
    driver = AsyncGraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))

    try:
        known_article_ids = await _load_known_article_ids(pg_conn)
        print(f"적재된 article_chunks: {len(known_article_ids)}건 (스코프 기준)")

        seen_case_ids: set[str] = set()
        total_inserted = 0
        total_skipped = 0

        async with driver.session() as neo4j_session:
            for query in queries:
                print(f"\n[검색: {query}] 판례 목록 조회 중...")
                items = await list_cases(query, settings, max_pages=max_pages)
                print(f"  검색 결과: {len(items)}건")

                for item in items:
                    if item.case_id in seen_case_ids:
                        continue
                    seen_case_ids.add(item.case_id)

                    try:
                        raw = await fetch_case(item.case_id, settings)
                    except Exception as exc:
                        print(f"  [SKIP] {item.case_no} 조회 오류: {exc}")
                        total_skipped += 1
                        continue

                    mapped = map_case(raw, known_article_ids)
                    if mapped is None:
                        total_skipped += 1
                        continue

                    inserted = await _upsert_case_pg(pg_conn, mapped)
                    await _upsert_case_neo4j(neo4j_session, mapped)
                    if inserted:
                        total_inserted += 1

        case_count = await pg_conn.fetchval("SELECT count(*) FROM case_chunks")
        print(
            f"\n완료. 신규 {total_inserted}건 적재, {total_skipped}건 스킵. "
            f"case_chunks 전체: {case_count}건"
        )
        print("validity_flag 갱신: lawcorpus update-validity")
    finally:
        await pg_conn.close()
        await driver.close()


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------

async def _load_hnsw_indexes() -> dict[str, tuple[str, str]]:
    """schema/schema.sql에서 테이블별 (인덱스명, DDL)을 추출 — 여기 DDL을 다시
    적으면 schema.sql의 인덱스 파라미터가 바뀔 때 조용히 어긋난다."""
    import re
    schema_sql = (importlib.resources.files("lawcorpus.schema") / "schema.sql").read_text()
    pattern = re.compile(
        r"CREATE INDEX(?: IF NOT EXISTS)?\s+(\S+)\s+ON\s+(\S+)\s+USING hnsw[^;]*;", re.DOTALL
    )
    return {
        table: (name, m.group(0).rstrip(";"))
        for m in pattern.finditer(schema_sql)
        for name, table in [(m.group(1), m.group(2))]
    }


async def _backfill_table(conn: asyncpg.Connection, table: str, batch_size: int, sem: asyncio.Semaphore, settings) -> None:
    total: int = await conn.fetchval(f"SELECT count(*) FROM {table} WHERE embedding IS NULL")
    if total == 0:
        print(f"{table}: nothing to backfill")
        return

    print(f"{table}: {total}행 백필 시작 (batch={batch_size})")
    done = 0
    while True:
        rows = await conn.fetch(
            f"SELECT chunk_id, text FROM {table} WHERE embedding IS NULL LIMIT $1",
            batch_size,
        )
        if not rows:
            break

        chunk_ids = [r["chunk_id"] for r in rows]
        texts = [r["text"] for r in rows]

        async with sem:
            embeddings = await embed_batch(texts, settings)

        async with conn.transaction():
            for chunk_id, emb in zip(chunk_ids, embeddings):
                await conn.execute(f"UPDATE {table} SET embedding = $1 WHERE chunk_id = $2", emb, chunk_id)

        done += len(rows)
        print(f"{table}: {done}/{total}")

    remaining = await conn.fetchval(f"SELECT count(*) FROM {table} WHERE embedding IS NULL")
    print(f"{table}: 완료 (미처리 잔여={remaining})")


async def backfill(settings, batch_size: int = 64, concurrency: int = 2, rebuild_index: bool = False) -> None:
    conn = await asyncpg.connect(dsn=settings.pg_dsn)
    await register_vector(conn)
    sem = asyncio.Semaphore(concurrency)
    indexes = await _load_hnsw_indexes()

    try:
        for table in ("article_chunks", "case_chunks"):
            if rebuild_index:
                idx_name, _ = indexes[table]
                await conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
                print(f"{table}: hnsw 인덱스 DROP ({idx_name})")

            await _backfill_table(conn, table, batch_size, sem, settings)

            if rebuild_index:
                _, ddl = indexes[table]
                print(f"{table}: hnsw 인덱스 빌드 중... (시간 소요)")
                await conn.execute(ddl)
                print(f"{table}: hnsw 인덱스 빌드 완료")

        for table in ("article_chunks", "case_chunks"):
            null_cnt = await conn.fetchval(f"SELECT count(*) FROM {table} WHERE embedding IS NULL")
            total_cnt = await conn.fetchval(f"SELECT count(*) FROM {table}")
            print(f"{table}: 전체 {total_cnt}행, embedding NULL {null_cnt}행")
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# update-validity
# ---------------------------------------------------------------------------

async def _compute_validity_flags(neo4j_uri: str, user: str, password: str) -> dict[str, str]:
    """판정 규칙: 1) OVERRULED_BY 있으면 overruled, 2) BASED_ON 조문이 판결 후
    개정되면 law_amended, 3) 나머지 valid."""
    driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(user, password))
    flags: dict[str, str] = {}
    try:
        async with driver.session() as session:
            r1 = await session.run(
                "MATCH (c:CorpusCase)-[:OVERRULED_BY]->() RETURN c.chunk_id AS chunk_id"
            )
            async for record in r1:
                flags[record["chunk_id"]] = "overruled"

            r2 = await session.run(
                """
                MATCH (c:CorpusCase)-[:BASED_ON]->(a:CorpusArticle)-[:AMENDED_BY]->(m:CorpusAmendment)
                WHERE m.amended_at > c.decided_at
                  AND NOT (c)-[:OVERRULED_BY]->()
                RETURN DISTINCT c.chunk_id AS chunk_id
                """
            )
            async for record in r2:
                flags.setdefault(record["chunk_id"], "law_amended")

            r3 = await session.run("MATCH (c:CorpusCase) RETURN c.chunk_id AS chunk_id")
            async for record in r3:
                flags.setdefault(record["chunk_id"], "valid")
    finally:
        await driver.close()
    return flags


async def _apply_validity_flags(dsn: str, flags: dict[str, str]) -> None:
    conn = await asyncpg.connect(dsn=dsn)
    try:
        async with conn.transaction():
            for chunk_id, flag in flags.items():
                await conn.execute(
                    "UPDATE case_chunks SET validity_flag = $1 WHERE chunk_id = $2", flag, chunk_id
                )
        print(f"Updated {len(flags)} case validity_flag(s).")
    finally:
        await conn.close()


async def update_validity(settings) -> None:
    print("Computing validity flags from Neo4j graph...")
    flags = await _compute_validity_flags(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    print(f"Applying {len(flags)} flag(s) to PG...")
    await _apply_validity_flags(settings.pg_dsn, flags)
    print("Done.")


# ---------------------------------------------------------------------------
# load-sample — 개발/검증용 소량 데이터 (임베딩은 NULL 유지, backfill로 채움)
# ---------------------------------------------------------------------------

_SAMPLE_PARENT_ARTICLES = [
    {
        "chunk_id": "art_소득세법_14", "law_name": "소득세법", "article_no": "제14조",
        "clause_path": None, "parent_chunk_id": None,
        "text": "제14조(과세표준의 계산) 거주자의 종합소득에 대한 과세표준은 종합소득금액에서 종합소득공제를 적용한 금액으로 한다.",
        "effective_from": "2010-01-01", "effective_to": None, "is_current": True,
    },
    {
        "chunk_id": "art_법인세법_52", "law_name": "법인세법", "article_no": "제52조",
        "clause_path": None, "parent_chunk_id": None,
        "text": "제52조(부당행위계산의 부인) 납세지 관할 세무서장은 내국법인의 행위 또는 소득금액의 계산이 특수관계인과의 거래로 인하여 조세의 부담을 부당하게 감소시킨 것으로 인정되는 경우 그 법인의 각 사업연도 소득금액을 다시 계산할 수 있다.",
        "effective_from": "2019-01-01", "effective_to": None, "is_current": True,
    },
    {
        "chunk_id": "art_법인세법_52_old", "law_name": "법인세법", "article_no": "제52조",
        "clause_path": None, "parent_chunk_id": None,
        "text": "제52조(부당행위계산의 부인) [2018-12-31 이전 시행] 납세지 관할 세무서장은 내국법인의 행위 또는 소득금액의 계산이 특수관계인과의 거래로 인하여 조세의 부담을 부당하게 감소시킨 것으로 인정되는 경우 그 법인의 각 사업연도 소득금액을 다시 계산할 수 있다.",
        "effective_from": "2010-01-01", "effective_to": "2018-12-31", "is_current": False,
    },
]

_SAMPLE_ARTICLES = [
    {
        "chunk_id": "art_소득세법_14_1", "law_name": "소득세법", "article_no": "제14조",
        "clause_path": "제1항", "parent_chunk_id": "art_소득세법_14",
        "text": "거주자의 종합소득에 대한 과세표준은 다음 각 호의 소득의 합계액으로 한다.",
        "effective_from": "2010-01-01", "effective_to": None, "is_current": True,
    },
    {
        "chunk_id": "art_법인세법_52_1", "law_name": "법인세법", "article_no": "제52조",
        "clause_path": "제1항", "parent_chunk_id": "art_법인세법_52",
        "text": "납세지 관할 세무서장은 특수관계인과의 거래로 조세부담을 부당하게 감소시킨 것으로 인정되는 경우 그 법인의 소득금액을 계산할 수 있다.",
        "effective_from": "2019-01-01", "effective_to": None, "is_current": True,
    },
    {
        "chunk_id": "art_법인세법_52_1_old", "law_name": "법인세법", "article_no": "제52조",
        "clause_path": "제1항", "parent_chunk_id": "art_법인세법_52_old",
        "text": "납세지 관할 세무서장은 특수관계인과의 거래로 조세부담을 부당하게 감소시킨 것으로 인정되는 경우 그 법인의 소득금액을 계산할 수 있다.",
        "effective_from": "2010-01-01", "effective_to": "2018-12-31", "is_current": False,
    },
]

_SAMPLE_CASES = [
    {
        "chunk_id": "case_2018두12345", "case_no": "2018두12345", "court": "대법원",
        "decided_at": "2020-03-15", "is_en_banc": False, "validity_flag": "law_amended",
        "text": "법인세법 제52조 제1항의 부당행위계산 부인 규정 적용에 있어서 특수관계인 간 거래가격이 시가와 다르다는 사정만으로 곧바로 부당행위계산 부인 대상이 되는 것은 아니다.",
    },
    {
        "chunk_id": "case_2015두54321", "case_no": "2015두54321", "court": "대법원",
        "decided_at": "2017-06-20", "is_en_banc": False, "validity_flag": "overruled",
        "text": "특수관계인과의 거래에서 시가와 거래가액의 차이가 있으면 원칙적으로 부당행위계산 부인 대상에 해당한다.",
    },
    {
        "chunk_id": "case_2020두99999", "case_no": "2020두99999", "court": "대법원",
        "decided_at": "2022-11-10", "is_en_banc": True, "validity_flag": "valid",
        "text": "부당행위계산 부인의 요건으로서 '조세의 부담을 부당하게 감소시킨 것'은 경제적 합리성을 결한 비정상적인 것임을 요한다.",
    },
]

_SAMPLE_CITES = [
    ("case_2018두12345", "art_법인세법_52_1_old"),
    ("case_2015두54321", "art_법인세법_52_1_old"),
    ("case_2020두99999", "art_법인세법_52_1"),
]
_SAMPLE_BASED_ON = [
    ("case_2018두12345", "art_법인세법_52_1_old"),
    ("case_2020두99999", "art_법인세법_52_1"),
]
_SAMPLE_OVERRULED_BY = [("case_2015두54321", "case_2020두99999")]
_SAMPLE_AMENDMENTS = [
    {
        "amendment_id": "amend_법인세법_52_2019", "law_name": "법인세법", "article_no": "제52조",
        "amended_at": "2019-01-01", "summary": "부당행위계산 부인 요건 명확화",
    }
]
_SAMPLE_AMENDED_BY = [("art_법인세법_52_1_old", "amend_법인세법_52_2019")]


async def load_sample(settings) -> None:
    conn = await asyncpg.connect(dsn=settings.pg_dsn)
    await register_vector(conn)
    try:
        for art in _SAMPLE_PARENT_ARTICLES + _SAMPLE_ARTICLES:
            await conn.execute(
                """
                INSERT INTO article_chunks
                    (chunk_id, law_name, article_no, clause_path, parent_chunk_id,
                     text, effective_from, effective_to, is_current)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (chunk_id) DO NOTHING
                """,
                art["chunk_id"], art["law_name"], art["article_no"],
                art["clause_path"], art["parent_chunk_id"], art["text"],
                date.fromisoformat(art["effective_from"]),
                date.fromisoformat(art["effective_to"]) if art["effective_to"] else None,
                art["is_current"],
            )
        for case in _SAMPLE_CASES:
            await conn.execute(
                """
                INSERT INTO case_chunks
                    (chunk_id, case_no, court, decided_at, is_en_banc, validity_flag, text)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT (chunk_id) DO NOTHING
                """,
                case["chunk_id"], case["case_no"], case["court"],
                date.fromisoformat(case["decided_at"]),
                case["is_en_banc"], case["validity_flag"], case["text"],
            )
        art_count = await conn.fetchval("SELECT count(*) FROM article_chunks")
        case_count = await conn.fetchval("SELECT count(*) FROM case_chunks")
        print(f"PG: article_chunks={art_count}, case_chunks={case_count}")
    finally:
        await conn.close()

    driver = AsyncGraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    try:
        async with driver.session() as session:
            for art in _SAMPLE_ARTICLES:
                await session.run(
                    """
                    MERGE (n:CorpusArticle {chunk_id: $chunk_id})
                    SET n.law_name = $law_name, n.article_no = $article_no,
                        n.effective_from = $effective_from, n.effective_to = $effective_to,
                        n.is_current = $is_current
                    """,
                    chunk_id=art["chunk_id"], law_name=art["law_name"], article_no=art["article_no"],
                    effective_from=art["effective_from"], effective_to=art["effective_to"],
                    is_current=art["is_current"],
                )
            for case in _SAMPLE_CASES:
                await session.run(
                    """
                    MERGE (n:CorpusCase {chunk_id: $chunk_id})
                    SET n.case_no = $case_no, n.court = $court, n.decided_at = $decided_at,
                        n.is_en_banc = $is_en_banc, n.validity_flag = $validity_flag
                    """,
                    chunk_id=case["chunk_id"], case_no=case["case_no"], court=case["court"],
                    decided_at=case["decided_at"], is_en_banc=case["is_en_banc"],
                    validity_flag=case["validity_flag"],
                )
            for amend in _SAMPLE_AMENDMENTS:
                await session.run(
                    """
                    MERGE (n:CorpusAmendment {amendment_id: $amendment_id})
                    SET n.law_name = $law_name, n.article_no = $article_no,
                        n.amended_at = $amended_at, n.summary = $summary
                    """,
                    **amend,
                )
            for case_id, art_id in _SAMPLE_CITES:
                await session.run(
                    "MATCH (c:CorpusCase {chunk_id: $cid}) MATCH (a:CorpusArticle {chunk_id: $aid}) "
                    "MERGE (c)-[:CITES]->(a)",
                    cid=case_id, aid=art_id,
                )
            for case_id, art_id in _SAMPLE_BASED_ON:
                await session.run(
                    "MATCH (c:CorpusCase {chunk_id: $cid}) MATCH (a:CorpusArticle {chunk_id: $aid}) "
                    "MERGE (c)-[:BASED_ON]->(a)",
                    cid=case_id, aid=art_id,
                )
            for old_id, new_id in _SAMPLE_OVERRULED_BY:
                await session.run(
                    "MATCH (old:CorpusCase {chunk_id: $old_id}) MATCH (new:CorpusCase {chunk_id: $new_id}) "
                    "MERGE (old)-[:OVERRULED_BY]->(new)",
                    old_id=old_id, new_id=new_id,
                )
            for art_id, amend_id in _SAMPLE_AMENDED_BY:
                await session.run(
                    "MATCH (a:CorpusArticle {chunk_id: $aid}) MATCH (m:CorpusAmendment {amendment_id: $mid}) "
                    "MERGE (a)-[:AMENDED_BY]->(m)",
                    aid=art_id, mid=amend_id,
                )
            result = await session.run(
                "MATCH (n) WHERE n:CorpusArticle OR n:CorpusCase OR n:CorpusAmendment RETURN count(n) AS cnt"
            )
            record = await result.single()
            print(f"Neo4j: total Corpus nodes={record['cnt']}")
    finally:
        await driver.close()
