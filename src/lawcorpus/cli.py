from __future__ import annotations

import argparse
import asyncio

from lawcorpus import commands
from lawcorpus.config import get_settings
from lawcorpus.schema.apply import apply_schema


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lawcorpus")
    sub = parser.add_subparsers(dest="command", required=True)

    p_schema = sub.add_parser("apply-schema", help="PG DDL + Neo4j 제약을 멱등 적용")
    p_schema.add_argument("--drop", action="store_true", help="적용 전 구 스키마/레이블 DROP (파괴적)")
    p_schema.add_argument("--yes-i-mean-it", action="store_true", dest="confirm_drop",
                           help="--drop 실행에 필요한 명시적 확인")

    p_laws = sub.add_parser("ingest-laws", help="법제처 OPEN API에서 법령 조문 수집")
    p_laws.add_argument("--law", action="append", required=True, dest="laws", help="법령명 (반복 가능)")

    p_statutes = sub.add_parser("ingest-statutes", help="target=eflaw 현행 스냅샷을 bitemporal 스키마로 적재")
    p_statutes.add_argument("--law", action="append", required=True, dest="laws", help="법령명 (반복 가능)")
    p_statutes.add_argument("--include-subordinate", action="store_true",
                             help="체계도(lsStmd)로 시행령/시행규칙도 함께 적재")

    p_addenda = sub.add_parser("ingest-addenda", help="이미 적재된 법령의 부칙을 파싱해 적재")
    p_addenda.add_argument("--law", action="append", required=True, dest="laws", help="법령명 (반복 가능)")

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
        if args.drop and not args.confirm_drop:
            raise SystemExit("--drop은 파괴적 작업입니다. --yes-i-mean-it을 함께 지정하세요.")
        asyncio.run(apply_schema(settings, drop=args.drop))
    elif args.command == "ingest-laws":
        asyncio.run(commands.ingest_laws(args.laws, settings))
    elif args.command == "ingest-statutes":
        asyncio.run(commands.ingest_statutes(args.laws, settings, include_subordinate=args.include_subordinate))
    elif args.command == "ingest-addenda":
        asyncio.run(commands.ingest_addenda(args.laws, settings))
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
