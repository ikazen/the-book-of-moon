# the-book-of-moon

한국 세법/판례 코퍼스 — 수집·저장·조회 공통 라이브러리. Python 3.12+ · PostgreSQL(pgvector) + Neo4j.

[pot-of-greed](https://github.com/ikazen/pot-of-greed)에서 분리됐다. 소비처가 여러 프로젝트일 수 있어
특정 앱의 LLM/RAG 스택에 종속되지 않는 순수 데이터 계층으로 유지한다 — LLM을 호출하는 검색 기법(HyDE 등)은
포함하지 않는다.

## 빠른 시작

```bash
pip install "lawcorpus @ git+https://github.com/ikazen/the-book-of-moon.git@v0.1.0"
cp .env.example .env   # LAWCORPUS_PG_DSN 등 채우기
lawcorpus apply-schema
lawcorpus ingest-laws --law 소득세법 --law 법인세법
lawcorpus backfill
```

## 구조

```
src/lawcorpus/
├── config.py       LawCorpusSettings (env prefix LAWCORPUS_)
├── types.py        Chunk, GraphChunk, ValidityFlag
├── db/             PostgreSQL(asyncpg+pgvector) / Neo4j 커넥션
├── ingest/         법제처 OPEN API 수집·매핑 (조문/판례)
├── retrieval/      벡터·키워드검색·RRF·리랭킹·그래프확장
├── refs.py         인용 추출/파싱/존재검증 (조문·판례 번호)
├── search.py       promotion_score / hybrid_search (원자 검색 조합)
├── schema/         PG DDL + Neo4j 제약 (schema.sql, neo4j_schema.cypher, apply.py)
├── commands.py     CLI 서브커맨드 구현 (ingest/backfill/update-validity/load-sample)
└── cli.py          argparse 진입점 — apply-schema/ingest-laws/ingest-cases/backfill/update-validity/load-sample
```

이 repo가 포함하지 않는 것: LLM 호출이 필요한 검색 기법(HyDE), 질의 분해, RAG 오케스트레이션.
그런 건 소비처(예: pot-of-greed의 `app/rag/`)가 이 라이브러리의 원자 함수를 조합해서 만든다 — 근거는
[결정 A](docs/decisions.md).

## 더 보기

- [`docs/architecture.md`](docs/architecture.md) — 저장소 구성, 청킹, 판례 유효성 처리
- [`docs/decisions.md`](docs/decisions.md) — 핵심 결정 기록
- [`docs/setup.md`](docs/setup.md) — DB 스키마 적용, 인제스트 순서
- [`docs/changelog.md`](docs/changelog.md) — 릴리스 이력
