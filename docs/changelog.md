# Changelog

## v0.2.0 (2026-08-21)

코퍼스 확장: 법률 3개 본문뿐이던 커버리지를 시행령/시행규칙 + 국세기본법 + 조세특례제한법으로 넓혔다.

- `refs.py` — 인용 정규식이 "XXX법 시행령"/"XXX법 시행규칙" 법령명을 인식하도록 확장, 조특법/국기법
  약칭 정규화 맵 추가 (#12) — 확장 전에는 시행령 인용이 전부 환각으로 오판되는 결함이 있었다
- 인제스트: 소득세법/법인세법/부가가치세법 시행령·시행규칙 6종 + 국세기본법(+시행령) +
  조세특례제한법(+시행령) 신규 적재 (#13) — `article_chunks` 2,395 → 13,611행
- 판례 재수집: 확장된 법령 스코프로 참조조문 매칭 폭 증가, `case_chunks` 51 → 116행,
  `validity_flag` 전량 재계산 (#14)
- `docs/architecture.md` — 시행령/시행규칙 chunk_id 공백 규약 문서화
- `docs/setup.md` — 인제스트 예시를 확장된 법령 목록으로 갱신

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
