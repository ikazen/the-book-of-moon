# 결정 기록

이 문서는 living document다 — 과거 결정은 언제든 정당화 없이 뒤집을 수 있다. 이력은 "수정" 블록으로 누적한다.

## A. LLM 비의존 원칙

**결정**: 이 repo는 LLM을 호출하는 코드를 포함하지 않는다. 임베딩(Ollama `/api/embed`)과
리랭킹(Ollama `/api/rerank`)은 예외 — 생성이 아니라 벡터/스코어를 반환하는 결정론적 호출이라
"검색 원자 연산"으로 취급한다.

**왜**: [pot-of-greed](https://github.com/ikazen/pot-of-greed)에서 세법/판례 코퍼스 계층을 분리하며
발견한 제약 — `search_complex`(질의 분해 + HyDE)는 LLM 호출이 두 군데(`app.agent.decompose`,
`app.rag.hyde`) 있어 이 repo로 가져오면 특정 LLM 프로바이더 추상화에 종속된다. 소비처가 여러
프로젝트일 수 있고 각자 다른 LLM 스택을 쓸 수 있으므로, 이 repo는 `hybrid_search`(임베딩+벡터+
키워드+RRF+리랭크+그래프확장, LLM 미호출)까지만 제공하고 HyDE·질의분해·RAG 오케스트레이션은
소비처 몫으로 남긴다. pot-of-greed 쪽 근거는 `docs/decisions.md` 결정 O 참조.

---

## B. 키워드 검색 엔진

**결정**: PG tsvector, `'simple'` config.

**왜**: 조문번호·판례번호 정확매칭이 핵심이고 tsvector로 충분. 자연어 키워드 재현율 부족 시
형태소 분석기(은전한닢)/ES 추후 도입 검토. `'simple'` config는 한국어 형태소 분석을 하지 않고
공백 토큰화만 한다 — 알려진 제약으로 남겨둔다.

인용 존재검증(`refs.py::verify_refs_exist`)은 tsvector가 아니라 `law_name`+`article_no`/`case_no`
컬럼 동등성 질의를 쓴다 — tsvector는 토큰 AND 매칭이라 "법명은 오귀속, 번호만 실재"인 인용도
통과시키는 오탐이 있었다(pot-of-greed adversarial review, BON-215).

*pot-of-greed 결정 B에서 이관.*

---

## C. 임베딩 모델

**결정**: `qwen3-embedding:8b`, 1024차원.

**왜**: 온프레미스에서 운용 중인 모델. 인덱싱과 쿼리에 반드시 동일 모델·버전 사용(벡터 공간 일치).
`LawCorpusSettings.embedding_model`/`embedding_dim` 단일 참조로 강제 — DDL의 `VECTOR(1024)`와
동기화 필요.

*pot-of-greed 결정 C에서 이관.*

---

## D. 데이터 수집 / 그래프 구축

**결정**: 법제처 OPEN API(open.law.go.kr) 1차 수입. 참조조문/참조판례 구조화 필드로 판례→조문
그래프를 LLM 추출 없이 수입.

**왜**: 법제처 DRF API가 조/항/호 + 연혁/시행일자/참조조문/참조판례를 구조화 XML로 제공 → LLM
추출 없이 필드 매핑만으로 그래프까지 구성 가능.

**조문 가지번호 저장 형식**: `article_no`는 `제N조의M`(정상 한국 법령 인용 표기)로 저장한다.
`제N의M조`(조립 순서가 뒤바뀐 오표기)는 인용 검증 정규식과 어긋나 가지번호 조문 인용이 전부
환각으로 오판되는 버그였다(pot-of-greed #40 — 2026-08-20, article_chunks 869행 + Neo4j 704노드
백필로 수정). `ingest/law_mapper.py`가 `art.no.partition("의")`로 분해해 조립한다.

*pot-of-greed 결정 D에서 이관.*

---

## E. DB 구성

**결정**: 2-DB 유지 (pgvector + Neo4j).

**왜**: pgvector = 하이브리드 검색(벡터+키워드 RRF). Neo4j = 관계 탐색(인용/준용/판례변경/개정이력).
역할이 겹치지 않아 단일화 시 품질 손실.

*pot-of-greed 결정 G에서 이관.*

---

## F. Hierarchical 청킹 / small-to-big

**결정**: 계층 = 조문 한정. 검색 child = 항/호, 컨텍스트 parent = 조. 계층 표현은 pgvector
`parent_chunk_id` fetch만 사용(그래프에 계층 엣지 없음). 판례는 계층 미적용.

**왜**: 항/호로 검색해야 임베딩 희석 없이 정밀 매칭되고, 조 전체를 parent로 끌어와야 리랭커·LLM이
세법 문맥을 오독 없이 본다(small-to-big). 계층을 그래프에 넣으면 Neo4j가 관계 탐색과 계층 탐색
두 역할을 지게 되므로, 단순 fetch로 충분한 계층은 PG 한 컬럼(`parent_chunk_id`)에 두고 그래프는
인용/준용 관계에만 집중시킨다.

*pot-of-greed 결정 I에서 이관.*
