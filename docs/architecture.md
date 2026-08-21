# 아키텍처

## 저장소 역할 분담

| 저장소 | 역할 |
|---|---|
| PostgreSQL + pgvector | 벡터(hnsw) + 키워드(tsvector/gin) 하이브리드 검색, 조문/판례 원문, validity_flag |
| Neo4j | 인용(CITES), 준용(REFERS_TO*), 판례변경(OVERRULED_BY), 개정이력(AMENDED_BY) 그래프 탐색 |
| 온프레미스 Ollama | 임베딩 + 리랭킹 (모델은 `LawCorpusSettings`로 교체 가능) |

*REFERS_TO는 조회 코드(`retrieval/graph_expand.py`)만 있고 생성 코드가 아직 없다 — 스펙만 존재하는 미구현 gap.

pgvector와 Neo4j를 둘 다 유지하는 이유: 조문번호/판례번호 정확매칭 + 의미 벡터검색(→ pgvector),
인용/준용/판례변경 관계 탐색(→ Neo4j). 역할이 겹치지 않는다.

## 데이터 모델

**`article_chunks`** — 조(條)는 parent(clause_path=NULL), 항(項)은 child(parent_chunk_id로 연결).
small-to-big 청킹: 검색은 항 단위로 되지만 `context_expand.expand_to_parents`로 조 전체를 붙여 반환할 수 있다.
`effective_from`/`effective_to`/`is_current`로 법령 개정 시점을 추적한다.

**`case_chunks`** — `validity_flag`(`valid`/`overruled`/`law_amended`/`uncertain`)로 판례 유효성을 3층
처리 중 1층(인덱싱 시점, 기계적 판정)을 담당한다. 2층(시점 정합 필터)은 `retrieval/graph_expand.py::
filter_by_transaction_date`. 3층(법리 판단)은 LLM이 필요해 이 repo 밖(소비처)의 몫이다.

**Neo4j 레이블**: `CorpusArticle`, `CorpusCase`, `CorpusAmendment` (Community Edition 단일 그래프이므로
`Corpus` 프리픽스로 워크로드 격리 — 다른 워크로드와 같은 Neo4j 인스턴스를 공유할 때 레이블 충돌 방지).

chunk_id 규약 (조문):
```
조:   art_<법령명>_<조번호>          예) art_소득세법_14
가지: art_<법령명>_<조번호>의<가지번호>  예) art_법인세법_18의3
항:   art_<법령명>_<조번호>_<항번호>  예) art_소득세법_14_1
```

시행령/시행규칙은 `<법령명>`에 공백이 포함된다(예) `art_소득세법 시행령_10`. PG/Neo4j 모두
공백을 그대로 허용하므로 문제 없다 — `refs.py`의 인용 검증도 같은 형식("XXX법 시행령")으로
재조립해 비교한다(the-book-of-moon #12).

## 검색 (`retrieval/`, `search.py`)

원자 함수: `vector_search`(코사인 hnsw) / `keyword_search`(tsvector, `'simple'` config — 한국어 형태소
분석기 없음, 알려진 제약) / `rrf_fuse`(RRF) / `rerank`(Ollama `/api/rerank`) / `expand_1hop`·`expand_2hop`
(Neo4j 그래프 확장) / `expand_to_parents`(small-to-big).

`search.py::hybrid_search`는 이 원자 함수들을 조합한 기본 파이프라인: embed → (vector ∥ keyword) →
RRF → rerank → 1hop 그래프 확장 → parent 확장. LLM 호출이 없다 — HyDE·질의분해가 필요한 복잡 검색은
소비처가 이 함수들을 가져다 직접 조합한다.
