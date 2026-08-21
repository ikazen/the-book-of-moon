# 설치 / 실행

## 사전 요건

- Python 3.12+
- PostgreSQL 16+ with pgvector extension
- Neo4j 5.x
- Ollama (`qwen3-embedding:8b`, `bge-reranker-v2-m3`)

## 설정

```bash
pip install -e ".[dev]"
cp .env.example .env
```

필수 설정값은 [`.env.example`](../.env.example) 참조 — `LAWCORPUS_PG_DSN`, `LAWCORPUS_NEO4J_URI`,
`LAWCORPUS_NEO4J_PASSWORD`, `LAWCORPUS_OLLAMA_BASE_URL`, `LAWCORPUS_LAW_API_OC`(법제처
[open.law.go.kr](https://open.law.go.kr) 신청 ID, 인제스트 전 필수)가 필수.

## DB 스키마 적용

```bash
lawcorpus apply-schema
```

PG DDL(`schema/schema.sql`) + Neo4j 제약(`schema/neo4j_schema.cypher`)을 멱등 적용한다.

## 데이터 수집 (결정 D)

`LAWCORPUS_LAW_API_OC` 설정 후 순서대로 실행:

```bash
lawcorpus ingest-laws \
  --law 소득세법 --law "소득세법 시행령" --law "소득세법 시행규칙" \
  --law 법인세법 --law "법인세법 시행령" --law "법인세법 시행규칙" \
  --law 부가가치세법 --law "부가가치세법 시행령" --law "부가가치세법 시행규칙" \
  --law 국세기본법 --law "국세기본법 시행령" \
  --law 조세특례제한법 --law "조세특례제한법 시행령"
lawcorpus ingest-cases --query 소득세 --query 법인세 --query 부가가치세 \
                       --query 국세기본법 --query 조세특례
lawcorpus backfill                # 임베딩 채우기
lawcorpus update-validity         # validity_flag 계산
```

법령/검색어는 소비처마다 다를 수 있어 CLI 인자로 받는다 — pot-of-greed는 세무 3법이지만
다른 소비처는 다른 법령이 필요할 수 있다.

## validity_flag 갱신

```bash
lawcorpus update-validity
```

Neo4j 그래프를 읽어 `case_chunks.validity_flag`를 계산·업데이트한다. 데이터 변경 시 재실행.

## 테스트

```bash
pytest
```

실 DB 불필요 — `get_pool`/`get_driver` 심볼을 monkeypatch로 대체한다.
