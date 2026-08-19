# Changelog

## v0.1.0 (2026-08-20)

pot-of-greed에서 세법/판례 코퍼스 계층(스키마+ingest+retrieval+Neo4j 그래프)을 분리한 초기 릴리스.

- `db/` — PostgreSQL(asyncpg+pgvector) / Neo4j 커넥션
- `ingest/` — 법제처 OPEN API 클라이언트, 법령/판례 매퍼
- `retrieval/` — 벡터·키워드검색·RRF·리랭킹·그래프확장·small-to-big 확장
- `refs.py` — 조문/판례 인용 추출·파싱·존재검증
- `search.py` — `promotion_score`/`hybrid_search` (LLM 미호출 — 결정 A)
- `schema/` — PG DDL + Neo4j 제약, `apply_schema()`
- `cli.py` — `lawcorpus` 커맨드: apply-schema/ingest-laws/ingest-cases/backfill/update-validity/load-sample
- 데이터: ops-vm `lawcorpus` DB로 article_chunks 2,395행 + case_chunks 51행 이관, Neo4j 레이블
  `PotOfGreed*` → `Corpus*` (pot-of-greed 프로덕션 호환을 위해 당분간 다중 레이블 병행 — Milestone C 이후 정리)
