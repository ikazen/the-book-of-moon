# 세법 솔루션 발굴 시스템 — 데이터 레이어 설계

> 범위: AI 층 이전, 적재 대상 / 스토리지 / 인터페이스 확정.
> 목표 세목(1차): 상속세및증여세법, 조세특례제한법(상증 관련 편), 소득세법(양도 편), 국세기본법.

---

## 0. 설계 전제

### 문제의 성격

"솔루션 발굴"은 검색 문제가 아니라 **탐색(search) 문제**다. 개구멍은 조문 A와 조문 B 사이의 빈틈에 있고, 어떤 문서에도 한 문단으로 쓰여 있지 않다. 따라서 데이터 레이어의 목표는 "질문에 답할 문장을 찾는 것"이 아니라 **조합 탐색이 가능한 구조화된 법령 상태 공간을 만드는 것**이다.

### 3층 구조

| 층 | 역할 | 이 문서의 범위 |
|---|---|---|
| 지식층 | 법령/판례를 시점 정합적으로 조회 | 전부 |
| 생성층 | 조합·변형으로 후보 생성 | 인터페이스 계약만 |
| 검증층 | 부인 리스크 평가, 인용 검증 | 데이터 소스 확보까지 |

### 핵심 불변식

1. **모든 조회는 `as_of` 시점을 필수 인자로 받는다.** 기본값 `today`를 허용하는 순간 과거 거래에 현행법을 적용하는 사고가 조용히 섞인다.
2. **PostgreSQL이 단일 진실 원천(SoT)이다.** Neo4j와 벡터 인덱스는 전량 재생성 가능한 파생물이다.
3. **모든 원본(XML/PDF/HTML)은 오브젝트 스토리지에 그대로 보관한다.** 파서는 반드시 여러 번 고쳐 쓰게 된다.

---

## 1. 적재 대상

우선순위 순. 1~2만으로도 "미개정 생존 구멍 탐지"가 동작한다.

| # | 도메인 | 내용 | 없으면 못 하는 것 |
|---|---|---|---|
| 1 | 법령 본문 | 조문 트리(조-항-호-목), 부칙, 별표 | 전부 |
| 2 | 개정 이력 | 조문별 버전, 신구대조, 공포일/시행일 | 생존 판정, 시점 정합성 |
| 3 | 쟁송 | 판례, 조세심판원 결정례 | 부인 리스크 평가 |
| 4 | 해석 | 국세청 예규·서면질의, 법제처 법령해석례 | 무위험 구멍 탐지 |
| 5 | 입법 의도 | 기재부 세법개정안 개정이유, 국회 의안 | 패턴 taxonomy |

국세기본법은 세목이 아니지만 **필수**다. 실질과세(제14조), 부당행위계산부인의 근거가 여기 있고, 모든 부인 리스크 판정의 기준점이 된다.

### 라벨 체계

판례에서 뽑아야 할 것은 개별 사례가 아니라 **생존 여부**다.

| 납세자 승소 이후 | status | 용도 |
|---|---|---|
| 개정됨 | `patched` | 패턴 학습 + 경정청구(5년) |
| 개정 안 됨 | `alive` | 즉시 적용 대상 |
| 개정 발의됐으나 계류/폐기 | `pending` | 우선순위 최상, 시한부 |
| 개정됐으나 범위가 좁음 | `partial` | 변형 여지 |

---

## 2. 인바운드 인터페이스

### 2.1 법제처 Open API (법령 · 판례 · 해석례)

가장 확실한 소스. 목록조회로 일련번호를 얻어 본문조회를 호출하는 2단 구조.

```
GET https://www.law.go.kr/DRF/lawSearch.do    # 목록
GET https://www.law.go.kr/DRF/lawService.do   # 본문
  ?OC={인증키}&target={target}&type=XML
```

| target | 대상 | 비고 |
|---|---|---|
| `law` | 현행법령(공포일 기준) | |
| `eflaw` | 현행법령(시행일 기준) | 미래 시행분 포함 — 1차 수집원 |
| `lawjosub` | 조항호목 단위 | 조문 단위 정밀 수집 |
| `admrul` | 행정규칙 | 국세청 훈령·고시 |
| `prec` | 판례 | `search=2`로 판시요지·내용 검색 |
| `expc` | 법령해석례 | |
| `detc` | 헌재결정례 | |

- OC 인증키는 open.law.go.kr에서 무료 발급.
- **체계도 부가서비스를 함께 신청**할 것. 법령서비스 신청 시 추가 신청 없이 이용 가능하며, 상하위법 위임 관계를 직접 파싱할 필요가 없어진다.
- `type=XML`이 필드가 더 풍부한 경우가 있으므로 XML 수집 후 파싱을 권장.
- 페이징: `display=100`, `page=N`. 판례는 `prncYd={시작}~{종료}`로 기간 분할.

**결정적 사실**: 본문 XML의 `<조문단위>`는 `조문키`, `조문번호`, `조문가지번호`, `조문시행일자`를 개별 보유한다. 즉 시행일이 법령 단위가 아니라 **조문 단위**로 관리된다. bitemporal 모델링의 기반이므로 뭉개지 말 것.

`조문가지번호`는 "제30조의5"의 `5`. `(art_no, branch_no)` 복합키로 다루지 않으면 정렬과 매칭이 깨진다.

일부 출처는 본문을 제공하지 않고 목록 메타데이터만 반환한다. `body_available` 플래그로 결측을 명시 관리할 것.

### 2.2 그 외 소스

| 소스 | 인터페이스 | 난이도 | 비고 |
|---|---|---|---|
| 조세심판원 결정례 | 법제처에 일부 포함, 전량은 tt.go.kr 크롤링 | 중 | 연 수천 건, 최신 쟁점 |
| 국세청 예규·서면질의 | taxlaw.nts.go.kr, 공식 API 없음 | 중 | 과세관청 공인 = 무위험 |
| 기재부 세법개정안 개정이유 | 보도자료 PDF | 상 | "OO 이용한 조세회피 방지"가 명시됨 |
| 국회 의안 | 의안정보시스템 Open API | 하 | `pending` 판정용 |

전량 크롤링은 불필요하다. **쟁점 조문 화이트리스트(수백 개)를 먼저 확정**하고, 그 조문을 인용한 건만 역으로 수집하면 규모가 관리 가능해진다.

---

## 3. 스토리지 배치

### 3.1 역할 분담

| 스토어 | 담당 | 이유 |
|---|---|---|
| PostgreSQL | 원장(SoT), 조문 본문, 버전·시점, 부칙, 판례 메타 | 트랜잭션, bitemporal 범위 질의, 배열/jsonb |
| Neo4j | 참조·위임·준용 그래프, 인용 네트워크, 패턴 인스턴스 | 가변 깊이 순회, 경로 탐색 |
| pgvector | 조문·항 단위 임베딩, 판례 요지 임베딩 | 의미 검색 진입점 |

### 3.2 성능에 대한 판단

**이 도메인은 데이터가 작다.** 성능은 병목이 아니다.

| 항목 | 1차 세목 4개 | 국세 전체 확장 시 |
|---|---|---|
| 조문(논리) | 3~5천 | 3~5만 |
| 조문 버전 | 3~5만 | 30~50만 |
| 참조 엣지 | 2~3만 | 20~30만 |
| 벡터 청크(항 단위) | 2~3만 | 20~30만 |

Neo4j 기준 전량이 페이지 캐시에 올라가는 규모이고, 2-hop 순회는 ms 단위다. pgvector HNSW도 여유. **실제 병목은 파싱 품질과 시점 정합성이지 조회 성능이 아니다.**

3-스토어 구성의 진짜 비용은 조회가 아니라 **동기화 일관성**이다. `as_of` 필터가 세 스토어에 걸쳐 동일하게 적용되지 않으면 결과가 조용히 어긋난다. 아래 3.3의 동기화 규칙을 지킬 것.

### 3.3 동기화

```
법제처 API / 크롤러
        |
        v
  raw object storage  (원본 불변 보관)
        |
        v
   PostgreSQL (SoT)
        |
        +---> Neo4j        (배치 재생성 또는 CDC)
        +---> pgvector      (조문 버전 변경분만 재임베딩)
```

- Neo4j는 **전량 재생성을 기본 전략**으로 삼는다. 규모가 작아서 수 분이면 끝나고, 증분 동기화 버그를 원천 차단한다. 일 1회 배치로 충분(법령 개정 빈도를 생각하면 과할 정도다).
- 임베딩은 `article_version.article_key` 기준 증분. 신규 버전만 재임베딩.
- 세 스토어 모두 동일한 `article_key`를 조인 키로 공유한다.

---

## 4. PostgreSQL 스키마

```sql
-- 법령
CREATE TABLE statute (
  statute_id      bigint PRIMARY KEY,          -- 법령ID
  name            text   NOT NULL,
  short_name      text,
  law_type        text   NOT NULL,             -- 법률/대통령령/부령/고시
  ministry_code   text,
  parent_id       bigint REFERENCES statute    -- 시행령 -> 법률
);

-- 조문 논리 식별자 (버전 무관)
CREATE TABLE article (
  article_id      bigserial PRIMARY KEY,
  statute_id      bigint NOT NULL REFERENCES statute,
  art_no          int    NOT NULL,             -- 30
  art_branch_no   int    NOT NULL DEFAULT 0,   -- 의5
  UNIQUE (statute_id, art_no, art_branch_no)
);

-- 조문 버전 (bitemporal 핵심)
CREATE TABLE article_version (
  article_key     bigint PRIMARY KEY,          -- 법제처 조문키
  article_id      bigint NOT NULL REFERENCES article,
  title           text,
  body            text   NOT NULL,
  tree            jsonb  NOT NULL,             -- 항-호-목 계층
  valid_from      date   NOT NULL,             -- 조문시행일자
  valid_to        date,                        -- NULL = 현재 유효
  promulgated_on  date   NOT NULL,
  promulgation_no int,
  revision_type   text,                        -- 제정/일부개정/전부개정
  is_full_rewrite boolean NOT NULL DEFAULT false,
  ingested_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON article_version (article_id, valid_from DESC);
CREATE INDEX ON article_version USING gist (
  daterange(valid_from, coalesce(valid_to, 'infinity'::date), '[)')
);
```

`valid_from/valid_to`가 거래 시점 축, `promulgated_on/ingested_at`이 인지 시점 축이다.

```sql
-- 개정 diff
CREATE TABLE article_diff (
  from_version     bigint REFERENCES article_version,
  to_version       bigint REFERENCES article_version,
  diff             jsonb,      -- 항/호 단위 added/removed/changed
  added_thresholds jsonb,      -- [{kind:'ratio', op:'>=', value:30, unit:'%'}]
  reason_text      text,       -- 기재부 개정이유
  reason_source    text,
  PRIMARY KEY (from_version, to_version)
);
```

`added_thresholds`는 이 DB에서 가장 독자적인 자산이 될 항목이다. 개정으로 새로 생긴 수치·기간·비율 조건이 곧 새 경계선이다(지분율 30% 요건을 넣으면 29.9%가 열린다).

```sql
-- 부칙 경과조치 (별도 취급 필수)
CREATE TABLE addendum (
  addendum_id     bigserial PRIMARY KEY,
  statute_id      bigint NOT NULL REFERENCES statute,
  promulgation_no int,
  clause_no       text,
  body            text NOT NULL,
  kind            text,       -- 시행일/적용례/경과조치/특례
  applies_from    date,
  target_articles bigint[]    -- article_id[]
);

-- 쟁송 + 해석 통합
CREATE TABLE ruling (
  ruling_id       text PRIMARY KEY,
  source          text NOT NULL,   -- 대법원/조세심판원/국세청예규/법제처해석례
  case_no         text,
  decided_on      date NOT NULL,
  outcome         text,            -- 납세자승/납세자패/일부인용
  gist            text,
  body            text,
  body_available  boolean NOT NULL DEFAULT false,
  cited_articles  bigint[],        -- article_key[] (시점 해소 완료분)
  anti_avoidance  text[],          -- 실질과세/부당행위계산부인/단계거래
  raw_uri         text NOT NULL
);
CREATE INDEX ON ruling USING gin (cited_articles);

-- 생존 라벨 (파생)
CREATE TABLE loophole_candidate (
  id              bigserial PRIMARY KEY,
  article_id      bigint NOT NULL REFERENCES article,
  origin_ruling   text REFERENCES ruling,
  status          text NOT NULL,   -- alive/patched/partial/pending
  patched_by      bigint,          -- to_version
  patched_on      date,
  pattern_type    text,            -- 아래 패턴 taxonomy
  claim_deadline  date,            -- 경정청구 만료일
  risk_score      numeric(4,3),
  confirmed_by    text,            -- 세무사 검증 결과
  note            text
);

-- 임베딩
CREATE TABLE article_embedding (
  chunk_id        bigserial PRIMARY KEY,
  article_key     bigint NOT NULL REFERENCES article_version,
  chunk_path      text   NOT NULL,   -- '제1항제3호'
  chunk_text      text   NOT NULL,
  embedding       vector(1024),
  is_current      boolean NOT NULL   -- 현행 유효분 사전 필터용
);
CREATE INDEX ON article_embedding
  USING hnsw (embedding vector_cosine_ops) WHERE is_current;
```

`is_current` 부분 인덱스(partial index)를 둔 이유: pgvector는 사후 필터링 시 recall이 떨어진다. **과거 시점 검색은 드물기 때문에** 현행분 전용 인덱스를 기본 경로로 두고, 과거 시점 검색은 별도 경로로 분리하는 것이 실용적이다.

### 패턴 taxonomy

`loophole_candidate.pattern_type`의 값 집합. 개별 사례는 개정되면 폐기되지만 패턴은 재사용된다.

| pattern_type | 정의 |
|---|---|
| `시점차익` | 두 조문의 시행일·판정기준일 불일치 |
| `정의불일치` | 동일 용어의 법률별 정의 차이 (소득세법 vs 조특법의 "특수관계인") |
| `분류재배치` | 거래의 법적 형식 변경으로 유리한 조문에 진입 |
| `단위조작` | 인적·물적 단위 분할/합병으로 한도·기준 회피 |
| `경과조치활용` | 부칙이 남겨둔 창 |

---

## 5. Neo4j 그래프 모델

### 5.1 노드

```cypher
(:Statute      {statute_id, name, law_type})
(:Article      {article_id, statute_id, art_no, branch_no, label})
(:Version      {article_key, valid_from, valid_to, title})
(:Addendum     {addendum_id, kind, applies_from})
(:Ruling       {ruling_id, source, decided_on, outcome})
(:Term         {name, defined_in_article_id})
(:Pattern      {pattern_type})
(:Loophole     {id, status, patched_on, claim_deadline})
```

### 5.2 엣지

```cypher
(:Statute)-[:DELEGATES_TO]->(:Statute)                      // 법률 -> 시행령
(:Article)-[:HAS_VERSION]->(:Version)
(:Version)-[:SUPERSEDES]->(:Version)                        // 버전 체인
(:Article)-[:REFERS_TO   {valid_from, valid_to}]->(:Article)
(:Article)-[:MUTATIS     {valid_from, valid_to}]->(:Article) // 준용
(:Article)-[:DELEGATES   {valid_from, valid_to}]->(:Article) // 위임
(:Article)-[:DEFINES]->(:Term)
(:Article)-[:USES]->(:Term)
(:Ruling)-[:CITES {as_of_version}]->(:Article)
(:Ruling)-[:APPLIES_DOCTRINE]->(:Doctrine)                  // 실질과세 등
(:Loophole)-[:EXPLOITS]->(:Article)
(:Loophole)-[:INSTANCE_OF]->(:Pattern)
(:Loophole)-[:PATCHED_BY]->(:Version)
```

### 5.3 핵심 설계 결정

**참조 엣지는 `Version`이 아니라 `Article`(논리 노드) 사이에 걸고, 유효기간을 엣지 프로퍼티로 준다.**

버전 노드 간에 엣지를 걸면 개정 때마다 엣지가 곱셈으로 늘어나 폭발한다. 논리 노드 간 엣지 + 시간 프로퍼티 방식이면 엣지 수가 조문 수에 선형이고, `as_of` 필터는 Cypher에서 단순 비교로 처리된다.

```cypher
// as_of 시점의 위임 체인 조회
MATCH path = (a:Article {article_id: $id})-[r:DELEGATES*1..3]->(:Article)
WHERE ALL(rel IN relationships(path) WHERE
  rel.valid_from <= date($as_of) AND
  (rel.valid_to IS NULL OR rel.valid_to > date($as_of)))
RETURN path;
```

`Version` 노드는 버전 체인 순회와 `Ruling`의 시점 앵커링에만 쓴다. 본문은 넣지 않는다(PG에만).

### 5.4 그래프가 실제로 값을 하는 질의

이 질의들이 관계형에서 어렵기 때문에 Neo4j를 두는 것이다.

```cypher
// 1. 정의 불일치 탐지 — 같은 용어를 다르게 정의하는 조문 쌍
MATCH (t:Term)<-[:DEFINES]-(a:Article), (t2:Term)<-[:DEFINES]-(b:Article)
WHERE t.name = t2.name AND a.statute_id <> b.statute_id
RETURN t.name, collect(DISTINCT a.label);

// 2. 준용 사슬의 끝 — 준용을 타고 들어가면 도달하는 실효 요건
MATCH p = (a:Article {article_id: $id})-[:MUTATIS*1..4]->(end:Article)
WHERE NOT (end)-[:MUTATIS]->() RETURN p;

// 3. 미개정 생존 구멍
MATCH (r:Ruling {outcome: '납세자승'})-[:CITES]->(a:Article)-[:HAS_VERSION]->(v:Version)
WHERE v.valid_from <= r.decided_on AND v.valid_to IS NULL
RETURN a.label, r.case_no, r.decided_on ORDER BY r.decided_on DESC;

// 4. 리스크 이웃 — 이 조문과 함께 인용되며 부인당한 조문
MATCH (a:Article {article_id: $id})<-[:CITES]-(r:Ruling)-[:CITES]->(b:Article)
WHERE r.outcome = '납세자패' RETURN b.label, count(r) AS n ORDER BY n DESC;
```

3번이 곧 `find_unpatched()`의 구현체다. 2번의 `NOT (end)-[:MUTATIS]->()`처럼 **가변 깊이 + 종단 조건**은 재귀 CTE로 쓰면 급격히 지저분해지는 부류라, 그래프를 두는 값이 여기서 나온다.

---

## 6. 검색 파이프라인 (RAG)

```
질의
 |
 +-- [라우터] 조문번호 정규식 매칭?  --> 직접 조회 (벡터 우회)
 |
 +-- [1] 진입점 검색
 |      BM25/bigram  +  pgvector(is_current)   --> RRF 융합, top-k=20
 |
 +-- [2] 그래프 확장 (Neo4j, as_of 필터)
 |      위임 체인 / 준용 사슬 / 정의 참조 1~2 hop
 |
 +-- [3] 시점 해소 (PG)
 |      확장된 article_id --> as_of 시점 유효 버전 본문
 |
 +-- [4] 부수 컨텍스트
 |      해당 조문 관련 부칙 경과조치 + 인용 심판례 요지
 |
 +-- [5] 재순위 + 컨텍스트 조립
```

### 원칙

- **청킹은 조문 단위, 임베딩은 항 단위 이중.** 토큰 슬라이딩 윈도우는 금지. 제1항과 단서가 다른 청크로 찢어지면 결론이 뒤집힌다.
- **하이브리드는 선택이 아니라 필수.** "조세특례제한법 제30조의5" 같은 정확 매칭은 dense embedding이 못 잡는다. 조문번호 정규식 라우팅을 앞단에 둘 것.
- **한국어 전문검색**은 `pg_bigm`(설정 간단) 또는 mecab 기반 `textsearch_ko`. 법령 용어 특성상 bigram이 의외로 잘 맞는다.
- **컨텍스트에는 항상 `valid_from/valid_to`를 함께 넣는다.** LLM이 시점을 인지하지 못하면 개정 전 논리를 개정 후 사안에 적용한다.

---

## 7. 아웃바운드 인터페이스

AI 층이 붙기 전에 이 시그니처를 확정해두면, 나중에 RAG든 CBR이든 플래너든 위에 얹기만 하면 된다.

```python
# --- 시점 해소: 모든 조회의 관문 ---
get_article(statute: str, art_no: int, branch_no: int, as_of: date) -> ArticleVersion
get_effective_law(statute: str, as_of: date) -> list[ArticleVersion]

# --- 그래프 ---
expand_refs(article_id: int, as_of: date, hops: int = 2,
            types: list[str] = ["REFERS_TO", "MUTATIS", "DELEGATES"]) -> Subgraph
get_delegation_chain(article_id: int, as_of: date) -> list[ArticleVersion]
get_mutatis_terminals(article_id: int, as_of: date) -> list[ArticleVersion]
find_term_conflicts(term: str, as_of: date) -> list[TermDefinition]

# --- 시계열 ---
get_article_timeline(article_id: int) -> list[ArticleVersion]
diff_articles(v_from: int, v_to: int) -> ArticleDiff
find_thresholds(article_id: int) -> list[Threshold]

# --- 검색 ---
search(query: str, as_of: date, filters: dict) -> list[Hit]
resolve_citation(text: str, decided_on: date | None) -> ArticleVersion | None

# --- 리스크 ---
get_rulings_for(article_id: int, outcome: str | None = None) -> list[Ruling]
anti_avoidance_rate(article_id: int) -> float
get_risk_neighbors(article_id: int) -> list[tuple[Article, int]]

# --- 탐지 ---
find_unpatched(since: date) -> list[LoopholeCandidate]
find_claimable(taxpayer_facts: dict, lookback_years: int = 5) -> list[LoopholeCandidate]
```

### 두 가지 주의

**`as_of`는 옵셔널로 두지 말 것.** 필수 인자로 강제해야 시점 누락이 컴파일 타임/호출 시점에 걸린다.

**`resolve_citation`은 나중에 AI 층의 인용 검증 하드 게이트로 그대로 재사용된다.** 존재하지 않는 조문 인용은 이 제품의 사망 원인이므로, 지금 데이터 함수로 잘 만들어두면 두 번 일하지 않는다.

---

## 8. 착수 순서

| 단계 | 작업 | 산출물 |
|---|---|---|
| 1 | OC 인증키 발급 + 체계도 부가서비스 신청 | |
| 2 | `target=eflaw`로 대상 4개 법령 현행 스냅샷 적재 | `article_version` |
| 3 | 조문 이력 전량 수집, `valid_from/valid_to` 확정, diff 생성 | `article_diff` |
| 4 | 부칙 파싱 | `addendum` |
| 5 | `resolve_citation` 구현 + 정확도 측정 | 파서 |
| 6 | 참조 그래프 추출 → Neo4j 적재 | 그래프 |
| 7 | 쟁점 조문 화이트리스트 확정 → 인용 판례·심판례 수집 | `ruling` |
| 8 | `find_unpatched` 실행 | 첫 후보 리스트 |
| 9 | 임베딩 + 하이브리드 검색 구성 | RAG |

**8번까지 가면 AI 없이 결과물이 나온다.** 그 리스트를 세무사에게 보여준 적중률이 전체 방향의 승산을 판가름한다. "이건 이미 아는 것"만 나오면 접근을 바꿔야 하고, "몰랐던 것"이 몇 개라도 나오면 계속 간다.

9번(RAG)을 뒤로 미룬 이유: 검색 품질은 데이터 구조가 잡힌 뒤에 튜닝하는 게 순서다. 구조가 흔들리는 상태에서 임베딩을 돌리면 재작업만 늘어난다.

---

## 9. 예상 난관

**인용 해소(citation resolution)가 최대 난관.** 판례 본문의 "구 상속세및증여세법 제41조의3"을 `article_key`로 매핑해야 하는데, "구 OO법"이 붙으면 **판결 당시 유효 버전**으로 해소해야 한다. 단순 문자열 매칭이 통하지 않으므로 여기에 시간을 배분할 것. 5단계에서 정확도를 반드시 수치로 측정하고 넘어간다.

**전부개정은 버전 체인을 끊는다.** 조문 번호 체계가 통째로 갈아엎어져 자동 매핑이 불가능하다. `is_full_rewrite` 플래그로 표시하고, 앞뒤 조문 매핑은 **수작업 매핑 테이블**을 두는 편이 빠르다. 세목 4개면 해당 이벤트가 많아야 몇 건이다.

**생존 편향(survivorship bias).** 판례에 남는 것은 "다툼이 생긴" 케이스뿐이다. 정말 잘 설계된 솔루션은 과세관청이 손대지 못해 애초에 소송이 나지 않는다. 즉 판례 코퍼스는 애매한 구멍들의 집합이지 좋은 구멍들의 집합이 아니다. 도메인 4(국세청 예규 긍정 회신)가 이를 부분 보완하므로 우선순위를 낮추지 말 것.

**부인 리스크 등급은 필수 필드다.** 실질과세와 부당행위계산부인은 조문 요건을 모두 만족해도 결과를 뒤집는 조항이다. `risk_score` 없이 산출물을 내보내면 "형식상 합법이지만 실제로는 부인당하는" 제안이 섞여 나간다.
