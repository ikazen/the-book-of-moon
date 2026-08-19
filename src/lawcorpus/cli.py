from __future__ import annotations

import argparse
import asyncio

from lawcorpus import commands
from lawcorpus.config import get_settings
from lawcorpus.schema.apply import apply_schema


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lawcorpus")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("apply-schema", help="PG DDL + Neo4j 제약을 멱등 적용")

    p_laws = sub.add_parser("ingest-laws", help="법제처 OPEN API에서 법령 조문 수집")
    p_laws.add_argument("--law", action="append", required=True, dest="laws", help="법령명 (반복 가능)")

    p_cases = sub.add_parser("ingest-cases", help="법제처 OPEN API에서 판례 수집 (참조조문 스코프 필터)")
    p_cases.add_argument("--query", action="append", required=True, dest="queries", help="검색어 (반복 가능)")
    p_cases.add_argument("--max-pages", type=int, default=50)

    p_backfill = sub.add_parser("backfill", help="article_chunks/case_chunks 임베딩 NULL 행 백필")
    p_backfill.add_argument("--batch-size", type=int, default=64)
    p_backfill.add_argument("--concurrency", type=int, default=2)
    p_backfill.add_argument("--rebuild-index", action="store_true", help="백필 전 hnsw DROP → 완료 후 일괄 CREATE")

    sub.add_parser("update-validity", help="Neo4j 그래프를 읽어 case_chunks.validity_flag 갱신")

    sub.add_parser("load-sample", help="개발/검증용 소량 샘플 데이터 적재")

    return parser


def main() -> None:
    args = _build_parser().parse_args()
    settings = get_settings()

    if args.command == "apply-schema":
        asyncio.run(apply_schema(settings))
    elif args.command == "ingest-laws":
        asyncio.run(commands.ingest_laws(args.laws, settings))
    elif args.command == "ingest-cases":
        asyncio.run(commands.ingest_cases(args.queries, settings, max_pages=args.max_pages))
    elif args.command == "backfill":
        asyncio.run(commands.backfill(
            settings,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
            rebuild_index=args.rebuild_index,
        ))
    elif args.command == "update-validity":
        asyncio.run(commands.update_validity(settings))
    elif args.command == "load-sample":
        asyncio.run(commands.load_sample(settings))


if __name__ == "__main__":
    main()
