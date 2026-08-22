# the-book-of-moon

한국 세법의 bitemporal 법령 상태 공간 — 조문 논리 식별자와 시행일자별 버전을 분리해 "이 시점에
이 조문이 어떤 문구였는가"를 정확히 답하는 데이터 계층. Python 3.12+ · PostgreSQL(pgvector) + Neo4j.

v0.x는 RAG 검색용 플랫 청크 스토어였다. v1.0.0부터는 "질문에 답할 문장 찾기"가 아니라
**조합 탐색이 가능한 구조화된 법령 상태 공간**을 목표로 전면 재구축했다 — 세법 "개구멍"(조문 A와
B 사이의 시점차익·정의불일치 같은 빈틈) 발굴 시스템의 데이터 기반이자, [pot-of-greed](https://github.com/ikazen/pot-of-greed)
같은 다른 소비처가 재사용할 수 있는 일반 법령 데이터 계층이다. 자세한 설계 근거는
[`docs/spec.md`](docs/spec.md).

## 빠른 시작

```bash
pip install "lawcorpus @ git+https://github.com/ikazen/the-book-of-moon.git@v1.0.0"
cp .env.example .env   # LAWCORPUS_PG_DSN 등 채우기
lawcorpus apply-schema
lawcorpus ingest-statutes --law 국세기본법 --include-subordinate
lawcorpus ingest-addenda --law 국세기본법
lawcorpus build-diffs --law 국세기본법
lawcorpus ingest-rulings --target prec --query 국세기본법
lawcorpus build-graph
```

## 핵심 불변식

1. **모든 조회는 `as_of` 시점을 필수 인자로 받는다.** 기본값 `today`를 허용하는 순간 과거
   거래에 현행법을 적용하는 사고가 조용히 섞인다.
2. **PostgreSQL이 단일 진실 원천(SoT)이다.** Neo4j는 전량 재생성 가능한 파생물이다.
3. **원본(XML)은 오브젝트 스토리지(MinIO)에 그대로 보관한다.** 파서는 반드시 여러 번
   고쳐 쓰게 된다.

## 구조

```
src/lawcorpus/
├── config.py         LawCorpusSettings (env prefix LAWCORPUS_)
├── types.py          Statute/Article/ArticleVersion/Ruling/Threshold/... 도메인 타입
├── db/                PostgreSQL(asyncpg) / Neo4j 커넥션
├── storage/           원본 XML 보관 (MinIO 우선, fs 폴백)
├── ingest/             법제처 OPEN API 클라이언트 + 조-항-호-목 tree 빌더 + 매퍼들
│                        (statute/addendum/diff/ruling — bitemporal 인제스트)
├── graph/              참조/준용/위임 엣지 추출 + Neo4j 전량 재생성 빌더
├── schema/             PG DDL + Neo4j 제약 (schema.sql, neo4j_schema.cypher, apply.py)
├── resolution.py        시점 해소 — get_article/get_effective_law/resolve_citation
├── graph_queries.py      expand_refs/get_delegation_chain/get_mutatis_terminals/
│                          find_term_conflicts/get_risk_neighbors/find_unpatched
├── timeline.py            get_article_timeline/diff_articles/find_thresholds
├── risk.py                get_rulings_for/anti_avoidance_rate/find_claimable
├── retrieval/              임베딩/재순위(embedder.py, reranker.py) + RRF(fusion.py)
├── commands.py            CLI 서브커맨드 구현
└── cli.py                argparse 진입점
```

이 repo가 포함하지 않는 것: LLM 호출이 필요한 검색 기법(HyDE), 질의 분해, RAG 오케스트레이션,
개별 납세자 사실관계 매칭. 그런 건 소비처가 이 라이브러리의 원자 함수를 조합해서 만든다 —
근거는 [결정 A](docs/decisions.md).

## 더 보기

- [`docs/spec.md`](docs/spec.md) — 데이터 레이어 설계 원안(문제 정의, 스토리지 배치, 검색 파이프라인)
- [`docs/architecture.md`](docs/architecture.md) — 실제 모듈 배치, 저장소 역할 분담
- [`docs/decisions.md`](docs/decisions.md) — 핵심 결정 기록
- [`docs/setup.md`](docs/setup.md) — DB 스키마 적용, 인제스트 순서
- [`docs/changelog.md`](docs/changelog.md) — 릴리스 이력
