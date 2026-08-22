# 설치 / 실행

## 사전 요건

- Python 3.12+
- PostgreSQL 16+ with pgvector, pg_trgm, btree_gist extensions
- Neo4j 5.x (Community Edition — 이 인스턴스는 lawcorpus 전용으로 간주, 결정 K)
- MinIO(원본 XML 보관) — 미설정 시 `LAWCORPUS_RAW_DIR` fs 폴백만 사용
- Ollama (`qwen3-embedding:8b`, `bge-reranker-v2-m3`) — M7(검색)부터 필요

## 설정

```bash
pip install -e ".[dev]"
cp .env.example .env
```

필수 설정값은 [`.env.example`](../.env.example) 참조 — `LAWCORPUS_PG_DSN`, `LAWCORPUS_NEO4J_URI`,
`LAWCORPUS_NEO4J_PASSWORD`, `LAWCORPUS_LAW_API_OC`(법제처 [open.law.go.kr](https://open.law.go.kr)
신청 ID, 인제스트 전 필수)가 필수. `LAWCORPUS_RAW_S3_*`/`LAWCORPUS_RAW_DIR`은 선택(둘 다 없으면
fs 폴백 기본 경로 `./data/raw` 사용).

## DB 스키마 적용

```bash
lawcorpus apply-schema
```

PG DDL(`schema/schema.sql`) + Neo4j 제약(`schema/neo4j_schema.cypher`)을 멱등 적용한다.
기존 스키마를 지우고 새로 만들려면(파괴적):

```bash
lawcorpus apply-schema --drop --yes-i-mean-it
```

## 데이터 수집 순서

`LAWCORPUS_LAW_API_OC` 설정 후 법령 단위로 순서대로 실행한다(설계문서 8절):

```bash
# 1. 현행 + 과거 개정 스냅샷 전량 적재 (법률 + 시행령 + 시행규칙)
lawcorpus ingest-statutes --law 국세기본법 --include-subordinate --include-history

# 2. 부칙 파싱
lawcorpus ingest-addenda --law 국세기본법

# 3. 조문 버전 간 diff + 신설 임계값 추출 (여러 스냅샷이 적재된 뒤에만 실질적 결과가 생긴다)
lawcorpus build-diffs --law 국세기본법

# 4. 판례/법령해석례/헌재결정례/행정규칙 수집
lawcorpus ingest-rulings --target prec --article data/article_whitelist.txt
lawcorpus ingest-rulings --target expc --article data/article_whitelist.txt
lawcorpus ingest-rulings --target detc --article data/article_whitelist.txt
lawcorpus ingest-rulings --target admrul --article data/article_whitelist.txt

# --query로 직접 검색어를 줄 수도 있다(둘 다 지정하면 합쳐진다)
lawcorpus ingest-rulings --target prec --query 실질과세

# 5. Neo4j 그래프 재생성 (PG를 SoT로 전량 재생성)
lawcorpus build-graph

# 6. 미개정 생존 구멍 탐지 → loophole_candidate 적재
lawcorpus find-unpatched --since 2020-01-01
```

`--article` 파일의 각 줄은 조문 인용 문자열("국세기본법 제14조")이 아니라 그 조문이 실제로
다투어지는 쟁점 키워드("실질과세")다 — 법원 판례 검색은 제목/키워드 매칭이라 인용 문자열
자체는 거의 매칭되지 않는다(실측 확인). `#`으로 시작하는 줄은 주석으로 무시된다.

법령/검색어는 소비처마다 다를 수 있어 CLI 인자로 받는다. 전부개정으로 조문번호가 갈아엎어진
경우의 수작업 매핑은:

```bash
lawcorpus load-rewrite-map --csv data/rewrite_map.csv
```

## 인용 해소 정확도 측정

```bash
lawcorpus eval-citations --golden tests/fixtures/citations.jsonl
```

`resolve_citation`(법령명+조문번호 파싱)의 precision/recall을 출력한다. 골든셋은 실제 오탐/
누락이 나올 때마다 추가해서 키워나간다.

## 테스트

```bash
pytest
```

대부분은 실 DB 불필요 — `get_pool`/`get_driver` 심볼을 monkeypatch로 대체하거나 fixture
XML로 순수 함수를 검증한다. `graph/build.py`, `graph_queries.py`, `timeline.py`, `risk.py`처럼
PG+Neo4j 두 세션을 오가는 orchestration 코드는 자동 테스트 대신 실 DB 스모크로 검증했다
(각 이슈의 PR 설명 참고) — 목킹보다 실측이 신뢰도가 높다고 판단.
