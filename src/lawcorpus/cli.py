from __future__ import annotations

import argparse
import asyncio
from datetime import date

from lawcorpus import commands
from lawcorpus.config import get_settings
from lawcorpus.db.neo4j import close_neo4j, init_neo4j
from lawcorpus.db.pg import close_pg, init_pg
from lawcorpus.graph.build import build_graph
from lawcorpus.schema.apply import apply_schema


async def _run_find_unpatched(since_str: str, settings) -> None:
    from lawcorpus.graph_queries import materialize_unpatched

    await init_pg(settings.pg_dsn)
    await init_neo4j(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        inserted = await materialize_unpatched(date.fromisoformat(since_str))
        print(f"완료. loophole_candidate 신규 {inserted}건")
    finally:
        await close_pg()
        await close_neo4j()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lawcorpus")
    sub = parser.add_subparsers(dest="command", required=True)

    p_schema = sub.add_parser("apply-schema", help="PG DDL + Neo4j 제약을 멱등 적용")
    p_schema.add_argument("--drop", action="store_true", help="적용 전 구 스키마/레이블 DROP (파괴적)")
    p_schema.add_argument("--yes-i-mean-it", action="store_true", dest="confirm_drop",
                           help="--drop 실행에 필요한 명시적 확인")

    p_statutes = sub.add_parser("ingest-statutes", help="target=eflaw 현행 스냅샷을 bitemporal 스키마로 적재")
    p_statutes.add_argument("--law", action="append", required=True, dest="laws", help="법령명 (반복 가능)")
    p_statutes.add_argument("--include-subordinate", action="store_true",
                             help="체계도(lsStmd)로 시행령/시행규칙도 함께 적재")
    p_statutes.add_argument("--include-history", action="store_true",
                             help="과거 개정 스냅샷 전량도 함께 적재 (build-diffs 전제조건)")

    p_addenda = sub.add_parser("ingest-addenda", help="이미 적재된 법령의 부칙을 파싱해 적재")
    p_addenda.add_argument("--law", action="append", required=True, dest="laws", help="법령명 (반복 가능)")

    p_diffs = sub.add_parser("build-diffs", help="인접한 조문 버전 쌍의 diff + added_thresholds 계산")
    p_diffs.add_argument("--law", action="append", required=True, dest="laws", help="법령명 (반복 가능)")

    p_rulings = sub.add_parser("ingest-rulings", help="판례/법령해석례/헌재결정례/행정규칙 통합 수집")
    p_rulings.add_argument("--target", required=True, choices=["prec", "expc", "detc", "admrul"])
    p_rulings.add_argument("--query", action="append", required=True, dest="queries", help="검색어 (반복 가능)")
    p_rulings.add_argument("--max-pages", type=int, default=10)

    p_eval = sub.add_parser("eval-citations", help="resolve_citation 파서 정확도(precision/recall) 측정")
    p_eval.add_argument("--golden", required=True, help="골든셋 JSONL 경로")

    sub.add_parser("build-graph", help="PG(SoT)에서 읽어 Neo4j를 전량 재생성")

    p_rewrite = sub.add_parser("load-rewrite-map", help="전부개정 조문번호 수작업 매핑 CSV 적재")
    p_rewrite.add_argument("--csv", required=True, help="rewrite_map.csv 경로")

    p_unpatched = sub.add_parser("find-unpatched", help="미개정 생존 구멍 탐지 → loophole_candidate 적재")
    p_unpatched.add_argument("--since", required=True, help="YYYY-MM-DD 이후 판결만 대상")

    return parser


def main() -> None:
    args = _build_parser().parse_args()
    settings = get_settings()

    if args.command == "apply-schema":
        if args.drop and not args.confirm_drop:
            raise SystemExit("--drop은 파괴적 작업입니다. --yes-i-mean-it을 함께 지정하세요.")
        asyncio.run(apply_schema(settings, drop=args.drop))
    elif args.command == "ingest-statutes":
        asyncio.run(commands.ingest_statutes(
            args.laws, settings,
            include_subordinate=args.include_subordinate, include_history=args.include_history,
        ))
    elif args.command == "ingest-addenda":
        asyncio.run(commands.ingest_addenda(args.laws, settings))
    elif args.command == "build-diffs":
        asyncio.run(commands.build_diffs(args.laws, settings))
    elif args.command == "ingest-rulings":
        asyncio.run(commands.ingest_rulings(args.target, args.queries, settings, max_pages=args.max_pages))
    elif args.command == "eval-citations":
        asyncio.run(commands.eval_citations(args.golden, settings))
    elif args.command == "build-graph":
        asyncio.run(build_graph(settings))
    elif args.command == "load-rewrite-map":
        asyncio.run(commands.load_rewrite_map(args.csv, settings))
    elif args.command == "find-unpatched":
        asyncio.run(_run_find_unpatched(args.since, settings))


if __name__ == "__main__":
    main()
