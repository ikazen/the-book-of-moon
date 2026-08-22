# Changelog

## v1.1.0 (2026-08-23)

M6(1차 데이터 생성)에서 상속세및증여세법/국세기본법/조세특례제한법/소득세법 이력 전량 적재
(article_version 308,329행) 후, M7(검색/임베딩)에서 실제 검색 파이프라인을 완성했다.

**추가**:

- `router.py` — 명시적 조문 인용 질의는 벡터/키워드 검색을 우회해 직접 조회
- `retrieval/keyword_search.py` — pg_trgm 기반 키워드 검색(결정 M), as_of 시점 필터 포함
- `retrieval/vector_search.py` — pgvector 코사인 유사도, is_current HNSW 경로 + 과거 시점 경로
- `embed-backfill` CLI — 현행 조문 버전만 항 단위로 청킹해 임베딩(결정 P, 9,634개 청크)
- `search(query, as_of, settings)` — 라우터→RRF융합→그래프확장→시점해소→부수컨텍스트→재순위
  전체 파이프라인 (v0.x `hybrid_search`/`promotion_score`를 대체, 설계문서 6절)

**M6/M7 진행 중 발견해 수정한 버그**:

- `article_version_no_overlap` EXCLUDE 제약이 IMMEDIATE라 이력 백필이 전건 실패하던 문제 —
  DEFERRABLE로 변경
- `close_versions`/`build_diffs`의 INSERT가 건당 개별 왕복이라 이력이 깊은 법령에서 O(n^2)로
  느려지던 성능 문제 — executemany/윈도우 함수 SQL로 배치화
- `ruling.cited_articles`/`cited_article_ids`가 컬럼만 있고 채워지지 않던 문제 — 백필 로직 신규
- 판례 outcome 분류가 1심 스타일만 인식하고 대법원/항소심 스타일("상고기각"+상고비용 부담자,
  "파기환송"+상고이유 인용 주체)을 놓치던 문제
- Neo4j UNWIND 배치 결과를 consume()하지 않아 트랜잭션 메모리가 회수 안 되던 문제, 레이블
  전체 wipe를 배치 없이 한 번에 DETACH DELETE하다 메모리 초과하던 문제
- **`statute.current_mst`가 이력 백필 루프에서 마지막으로 처리한 과거 MST로 덮어써지던 문제** —
  이 때문에 DELEGATES/REFERS_TO/MUTATIS 엣지가 946개(국세기본법만) 추출 가능한데도 그래프에
  0건으로 들어가고 있었다. 전체 12개 법령의 `current_mst`가 전부 손상돼 있었음(실측 확인 후
  복구), `_upsert_statute`에 `is_current` 플래그 추가로 근본 수정

**인프라**: Neo4j가 pot-of-greed-api와 실제로 공유 중임을 확인, 결정 K 재고 트리거 발동
(GitHub #74로 추적).

## v1.0.0 (2026-08-22)

플랫 청크 스토어(v0.x)를 폐기하고 bitemporal 법령 상태 공간으로 전면 재구축. 세법 "개구멍"
발굴은 문장 검색이 아니라 조문 간 시점차익·정의불일치를 조합 탐색하는 문제라, 조문 논리
식별자와 시행일자별 버전을 분리한 구조가 필요했다 — 설계 근거는 [`docs/spec.md`](spec.md),
결정 근거는 [`docs/decisions.md`](decisions.md) 결정 G~O.

**제거** (이관 아닌 폐기 — 스코프가 달라 v0.x 데이터는 재사용 대상이 아님):

- PG: `article_chunks`(13,611행), `case_chunks`(116행) 및 관련 트리거
- Neo4j: `Corpus*`, `PotOfGreedCase`, `PotOfGreedAmendment` 레이블 전부
- 코드: `refs.py`, `search.py`의 `hybrid_search`/`promotion_score`, `retrieval/graph_expand.py`,
  `retrieval/context_expand.py`, `ingest/law_mapper.py`, `ingest/case_mapper.py`
- 타입: `Chunk`, `GraphChunk`, `ValidityFlag`
- CLI: `ingest-laws`, `ingest-cases`, `backfill`, `update-validity`, `load-sample`

**추가**:

- PG 스키마: `statute`, `article`, `article_version`, `article_diff`, `addendum`, `ruling`,
  `loophole_candidate`, `article_embedding`, `pattern_type` (bitemporal, `btree_gist` EXCLUDE로
  버전 겹침 방지)
- Neo4j: `Statute`/`Article`/`Version`/`Addendum`/`Ruling`/`Term`/`Doctrine`/`Pattern`/`Loophole`
  노드, 무프리픽스(결정 K)
- 아웃바운드 API 16함수: `resolution.py`(시점해소), `graph_queries.py`(그래프질의+개구멍탐지),
  `timeline.py`(시계열), `risk.py`(리스크)
- `storage/raw_store.py` — 원본 XML MinIO 불변보관(fs 폴백)
- CLI: `apply-schema [--drop --yes-i-mean-it]`, `ingest-statutes`, `ingest-addenda`,
  `build-diffs`, `ingest-rulings --target prec|expc|detc|admrul`, `build-graph`,
  `eval-citations --golden`, `load-rewrite-map --csv`, `find-unpatched --since`

**pot-of-greed는 이 릴리스에서 완전히 깨진다** — 호환 shim 없음, 별도 재작성 프로젝트(계획 밖).

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
