"""CLI 서브커맨드 구현. asyncpg/neo4j 커넥션을 직접 열고 닫는다(lawcorpus.db 풀은 장수명 서버용)."""

from __future__ import annotations

import csv
import dataclasses
import json
from datetime import date

import asyncpg

from lawcorpus.ingest.addendum_parser import parse_addendum
from lawcorpus.ingest.diff import added_thresholds, diff_trees
from lawcorpus.ingest.ruling_mapper import MappedRuling, map_ruling
from lawcorpus.ingest.law_api import (
    fetch_eflaw,
    fetch_law_hierarchy,
    fetch_ruling,
    list_eflaws,
    list_rulings,
)
from lawcorpus.ingest.statute_mapper import MappedStatute, map_eflaw


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
                     promulgated_on, promulgation_no, revision_type, is_full_rewrite, revision_reason)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (article_id, valid_from) DO NOTHING
                """,
                v.moleg_article_key, article_id, v.title, v.body, json.dumps(v.tree),
                v.valid_from, v.promulgated_on, v.promulgation_no, v.revision_type, v.is_full_rewrite,
                v.revision_reason,
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
# ingest-addenda
# ---------------------------------------------------------------------------

async def _insert_addendum_items(conn: asyncpg.Connection, statute_id: int, ef_law) -> int:
    inserted = 0
    async with conn.transaction():
        for unit in ef_law.addenda:
            for item in parse_addendum(unit):
                result = await conn.execute(
                    """
                    INSERT INTO addendum
                        (statute_id, promulgation_no, clause_no, body, kind, applies_from, target_articles)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (statute_id, promulgation_no, clause_no) DO NOTHING
                    """,
                    statute_id, item.promulgation_no, item.clause_no, item.body,
                    item.kind, item.applies_from, [],
                )
                if result == "INSERT 0 1":
                    inserted += 1
    return inserted


async def ingest_addenda(laws: list[str], settings) -> None:
    """이미 ingest_statutes로 적재된 법령의 현행 스냅샷에서 부칙만 추가로 파싱해 적재한다.
    target_articles(조문 인용)는 아직 채우지 않는다 — resolve_citation(#30) 완료 후 별도 백필."""
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

                ef_law = await fetch_eflaw(current.mst, settings)
                statute_id = int(ef_law.law_id)
                inserted = await _insert_addendum_items(conn, statute_id, ef_law)
                print(f"[{law_name}] 부칙 {len(ef_law.addenda)}단위 처리, 항목 신규 {inserted}건")
            except Exception as exc:
                print(f"[{law_name}] 오류: {exc}")

        total = await conn.fetchval("SELECT count(*) FROM addendum")
        print(f"\n완료. addendum 전체: {total}행")
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# build-diffs
# ---------------------------------------------------------------------------

async def _diffable_pairs(conn: asyncpg.Connection, statute_id: int) -> list[tuple[dict, dict]]:
    """statute의 각 조문에서 valid_from 순으로 인접한 (from_version, to_version) 행 쌍을 찾는다."""
    rows = await conn.fetch(
        """
        SELECT av.article_key, av.article_id, av.tree, av.valid_from, av.revision_reason
        FROM article_version av
        JOIN article a ON a.article_id = av.article_id
        WHERE a.statute_id = $1
        ORDER BY av.article_id, av.valid_from
        """,
        statute_id,
    )
    by_article: dict[int, list] = {}
    for row in rows:
        by_article.setdefault(row["article_id"], []).append(row)

    return [
        (versions[i], versions[i + 1])
        for versions in by_article.values()
        for i in range(len(versions) - 1)
    ]


def _load_tree(raw: object) -> dict:
    return json.loads(raw) if isinstance(raw, str) else raw


async def build_diffs(laws: list[str], settings) -> None:
    """이미 적재된 조문 버전들 사이에서 연속된 쌍마다 diff + added_thresholds를 계산한다.
    현재 버전이 1개뿐인 조문은 비교 대상이 없어 건너뛴다 — 역사 스냅샷을 더 적재해야 diff가 생긴다."""
    conn = await asyncpg.connect(dsn=settings.pg_dsn)
    try:
        for law_name in laws:
            row = await conn.fetchrow("SELECT statute_id FROM statute WHERE name = $1", law_name)
            if row is None:
                print(f"[{law_name}] statute를 찾지 못함(ingest-statutes 선행 필요), 건너뜀")
                continue

            pairs = await _diffable_pairs(conn, row["statute_id"])
            inserted = 0
            async with conn.transaction():
                for from_row, to_row in pairs:
                    diff = diff_trees(_load_tree(from_row["tree"]), _load_tree(to_row["tree"]))
                    thresholds = [dataclasses.asdict(t) for t in added_thresholds(diff)]
                    result = await conn.execute(
                        """
                        INSERT INTO article_diff
                            (from_version, to_version, diff, added_thresholds, reason_text, reason_source)
                        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)
                        ON CONFLICT (from_version, to_version) DO NOTHING
                        """,
                        from_row["article_key"], to_row["article_key"], json.dumps(diff),
                        json.dumps(thresholds), to_row["revision_reason"], "법제처",
                    )
                    if result == "INSERT 0 1":
                        inserted += 1
            print(f"[{law_name}] 비교 가능 쌍 {len(pairs)}건, diff 신규 {inserted}건")

        total = await conn.fetchval("SELECT count(*) FROM article_diff")
        print(f"\n완료. article_diff 전체: {total}행")
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# ingest-rulings (prec/expc/detc/admrul 통합)
# ---------------------------------------------------------------------------

def _try_parse_yyyymmdd(raw: str) -> date | None:
    s = raw.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


async def _upsert_ruling(conn: asyncpg.Connection, mapped: MappedRuling) -> bool:
    result = await conn.execute(
        """
        INSERT INTO ruling
            (ruling_id, source, case_no, decided_on, outcome, gist, body,
             body_available, anti_avoidance, raw_uri)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (ruling_id) DO NOTHING
        """,
        mapped.ruling_id, mapped.source, mapped.case_no, mapped.decided_on, mapped.outcome,
        mapped.gist, mapped.body, mapped.body_available, list(mapped.anti_avoidance), mapped.raw_uri,
    )
    return result == "INSERT 0 1"


async def ingest_rulings(target: str, queries: list[str], settings, *, max_pages: int = 10) -> None:
    """prec/expc/detc/admrul target으로 검색해 상세를 가져와 ruling 테이블에 적재한다.
    조문 인용(cited_articles/cited_article_ids)은 아직 채우지 않는다 —
    resolve_citation(#30) 완료 후 별도 백필."""
    if not settings.law_api_oc:
        raise SystemExit("LAWCORPUS_LAW_API_OC가 설정되지 않았습니다.")

    conn = await asyncpg.connect(dsn=settings.pg_dsn)
    try:
        seen_ids: set[str] = set()
        inserted = 0
        for query in queries:
            items = await list_rulings(target, query, settings, max_pages=max_pages)
            for item in items:
                if item.ruling_id in seen_ids:
                    continue
                seen_ids.add(item.ruling_id)
                try:
                    raw = await fetch_ruling(target, item.ruling_id, settings)
                    mapped = map_ruling(raw)
                    if mapped is None:
                        decided_on = _try_parse_yyyymmdd(item.decided_at)
                        if decided_on is None:
                            print(f"[{target}:{item.ruling_id}] 상세 조회 실패 + 날짜 없음, 건너뜀")
                            continue
                        # 상세 조회 실패(예: "일치하는 판례가 없습니다") — 목록 메타데이터만으로
                        # body_available=False 행을 남긴다(완전히 드롭하면 존재 자체를 잊는다).
                        mapped = MappedRuling(
                            ruling_id=item.ruling_id, source=item.source, case_no=item.case_no or None,
                            decided_on=decided_on, outcome=None, gist=item.title,
                            body="", body_available=False, anti_avoidance=(), raw_uri="",
                        )
                    if await _upsert_ruling(conn, mapped):
                        inserted += 1
                except Exception as exc:
                    print(f"[{target}:{item.ruling_id}] 오류: {exc}")

        print(f"\n완료. 조회 {len(seen_ids)}건, 신규 {inserted}건")
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# eval-citations
# ---------------------------------------------------------------------------

_EVAL_LAW_NAMES = [
    "국세기본법", "국세기본법 시행령", "소득세법", "법인세법", "부가가치세법",
    "상속세 및 증여세법", "상속세 및 증여세법 시행령", "조세특례제한법", "조세특례제한법 시행령",
    "조특법", "국기법",  # resolve_citation의 실제 경로는 _known_law_names가 _LAW_ABBREV.keys()도
                          # 후보에 넣는다 — 여기서도 같은 후보 집합으로 맞춰야 파서 자체의
                          # 정확도가 정확히 측정된다(약칭 누락은 파서 결함이 아니라 후보 목록 결함).
]


async def eval_citations(golden_path: str, settings) -> None:
    """resolve_citation의 핵심(parse_citation)을 골든셋으로 정확도 측정한다.

    설계문서 9절: "5단계에서 정확도를 반드시 수치로 측정하고 넘어간다." DB 접속 없이
    파싱 단계만 측정한다 — 법령명 인식/조문번호 추출이 이 문제의 핵심이고, 시점 해소는
    이미 적재된 코퍼스 범위에 따라 결과가 달라져 "파서 자체의 정확도"와 분리해서 봐야 한다.
    """
    from pathlib import Path

    from lawcorpus.resolution import parse_citation

    tp = fp = fn = tn = 0
    for line in Path(golden_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        expected = case["expected"]
        result = parse_citation(case["text"], _EVAL_LAW_NAMES)
        predicted = (
            {"law": result["law"], "art_no": result["art_no"], "branch_no": result["branch_no"]}
            if result is not None else None
        )

        if expected is None and predicted is None:
            tn += 1
        elif expected is None and predicted is not None:
            fp += 1
        elif expected is not None and predicted is None:
            fn += 1
        elif predicted == expected:
            tp += 1
        else:
            fp += 1
            fn += 1  # 엉뚱한 조문을 정답처럼 반환 — 정밀도와 재현율 둘 다 깎는다

    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    print(f"총 {total}건: TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"precision={precision:.3f} recall={recall:.3f}")


# ---------------------------------------------------------------------------
# load-rewrite-map
# ---------------------------------------------------------------------------

async def _resolve_article_id(conn: asyncpg.Connection, statute_name: str, art_no: int, branch_no: int) -> int | None:
    return await conn.fetchval(
        """
        SELECT a.article_id FROM article a JOIN statute s ON s.statute_id = a.statute_id
        WHERE s.name = $1 AND a.art_no = $2 AND a.art_branch_no = $3
        """,
        statute_name, art_no, branch_no,
    )


async def load_rewrite_map(csv_path: str, settings) -> None:
    """전부개정으로 조문번호가 갈아엎어진 경우의 수작업 매핑을 CSV에서 읽어 적재한다.

    CSV는 article_id(내부 serial) 대신 사람이 알 수 있는 (법령명, 조번호, 가지번호)로
    적는다 — 로더가 article_id로 해소한다. 컬럼: statute_name,from_art_no,from_branch_no,
    to_art_no,to_branch_no,note
    """
    conn = await asyncpg.connect(dsn=settings.pg_dsn)
    try:
        inserted = 0
        skipped = 0
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                from_id = await _resolve_article_id(
                    conn, row["statute_name"], int(row["from_art_no"]), int(row.get("from_branch_no") or 0)
                )
                to_id = await _resolve_article_id(
                    conn, row["statute_name"], int(row["to_art_no"]), int(row.get("to_branch_no") or 0)
                )
                if from_id is None or to_id is None:
                    print(f"매핑 실패(조문을 찾을 수 없음): {row}")
                    skipped += 1
                    continue
                result = await conn.execute(
                    "INSERT INTO article_rewrite_map (from_article_id, to_article_id, note) "
                    "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                    from_id, to_id, row.get("note", ""),
                )
                if result == "INSERT 0 1":
                    inserted += 1
        print(f"완료. 신규 {inserted}건, 실패 {skipped}건")
    finally:
        await conn.close()
