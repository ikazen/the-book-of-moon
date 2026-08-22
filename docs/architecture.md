# 아키텍처

설계 근거는 [`docs/spec.md`](spec.md) 참조. 이 문서는 실제 구현이 그 설계를 어떻게
채웠는지, 그리고 설계 원안에서 벗어난 지점을 기록한다.

## 저장소 역할 분담

| 저장소 | 역할 |
|---|---|
| PostgreSQL | 단일 진실 원천(SoT) — statute/article/article_version/article_diff/addendum/ruling/loophole_candidate/article_embedding |
| Neo4j | 참조(REFERS_TO)/준용(MUTATIS)/위임(DELEGATES)/정의(DEFINES)/인용(CITES) 그래프 — PG에서 전량 재생성되는 파생물 |
| 온프레미스 Ollama | 임베딩 + 리랭킹 (M7 예정) |
| MinIO(mac-server) | 원본 XML 불변 보관. intermittent 호스트라 `LAWCORPUS_RAW_DIR` fs 폴백 필수 |

## 데이터 모델

**`article`** — 조문 논리 식별자(버전 무관). `(statute_id, art_no, art_branch_no)`가 자연키 —
"제30조의5"는 `art_no=30, art_branch_no=5`. `chapter_title`은 eflaw 응답의 편/장/절 헤딩을
문서 순서로 추적해 채운다(조특법/소득세법처럼 법률 전체가 아니라 일부 편만 다룰 때의 스코프
필터용).

**`article_version`** — bitemporal 핵심. `article_key`는 서로게이트 `bigserial`이다(법제처
조문키는 `moleg_article_key`에 `{법령일련번호}:{조문키}` 형식으로 별도 보관 — 조문키 자체는
법령 문서 내에서만 유일해 전역 키로 못 쓴다). `valid_to`는 **배타적 상한**(다음 버전의
`valid_from`과 동일한 값) — `btree_gist` EXCLUDE 제약이 같은 조문의 버전 기간 겹침을 DB
레벨에서 막는다. `tree`(jsonb)는 항-호-목 계층(`ingest/tree.py::build_tree`가 생성) — 항번호가
없는 단일 문단 조문은 `clauses: []`가 아니라 `no: ""`인 clause 하나로 표현된다(내용 자체를
잃지 않기 위해).

**시행령/시행규칙**은 `statute.parent_id`로 법률에 체이닝된다(시행규칙 -> 시행령 -> 법률).
체계도(`target=lsStmd`)가 이 관계를 제공한다.

**`ruling`** — prec(판례)/expc(법령해석례)/detc(헌재결정례)/admrul(행정규칙) 통합. 실측 결과
4개 API의 응답 구조가 서로 상당히 달라(루트/항목 태그, ID 파라미터, 필드명 전부 제각각)
공통 XML 파서 하나로 못 묶고, 소스별 파서가 각각 `RawRuling`으로 수렴한다
(`ingest/law_api.py::_parse_{prec,expc,detc,admrul}_detail`). `outcome`(납세자승/납세자패
등)은 실측 기반 보수적 텍스트 분류다 — 애매하면 None으로 남긴다(잘못 단정하는 것보다 "모른다"가
`find_unpatched`의 신뢰도에 낫다). expc/admrul은 승패 개념이 없어 항상 None.

## 그래프 (`graph/`, `graph_queries.py`)

**참조 엣지는 `Version`이 아니라 `Article` 논리 노드 사이에 걸고, 유효기간을 엣지
프로퍼티로 준다** — 버전마다 엣지가 곱셈으로 늘어나는 걸 막는다.

DELEGATES/REFERS_TO/MUTATIS 엣지의 1차 소스는 자유텍스트 정규식이 아니라
`target=lsDelegated` — 법제처가 조문/항/호/목 단위로 이미 구조화해서 제공한다
(`graph/extract_refs.py::extract_delegation_edges`). **MUTATIS(준용) 판정**은 lsDelegated
자체엔 전용 구분이 없어, 출발 조문의 **조문제목**에 "준용"이 있는지로 판별한다(예: 제25조의2
"연대납세의무에 관한 「민법」의 준용"). lsDelegated의 `<위임정보>`는 (위임구분,
위임법령일련번호, 위임법령제목)을 flat sibling으로 반복하는 특이 구조라 순서 스캔으로
그룹을 나눠야 한다.

DEFINES 엣지는 조문 **tree 전체**(body만이 아니라 항/호/목 텍스트까지)에서 두 가지 패턴으로
추출한다: `"OO"란/이란` (정의 조문 표제 스타일), `(이하 "OO"라 한다)` (본문 중간 약칭 정의).

`graph/build.py::build_graph`는 **PG를 SoT로 전량 재생성**하지만, DELEGATES/REFERS_TO/MUTATIS만은
아직 PG에 캐시돼 있지 않아 statute별로 lsDelegated를 다시 조회한다 — "PG만으로 재생성" 원칙에서
벗어나는 임시 타협이다(추후 별도 테이블로 캐싱 검토). 엣지의 `valid_from`은 `statute.enforced_on`,
`valid_to`는 NULL로 근사한다 — 정밀한 시점 이력은 다중 스냅샷을 적재해야 가능하다.

## 아웃바운드 인터페이스

| 모듈 | 함수 |
|---|---|
| `resolution.py` | `get_article`, `get_effective_law`, `resolve_citation` |
| `graph_queries.py` | `expand_refs`, `get_delegation_chain`, `get_mutatis_terminals`, `find_term_conflicts`, `get_risk_neighbors`, `find_unpatched`, `materialize_unpatched` |
| `timeline.py` | `get_article_timeline`, `diff_articles`, `find_thresholds` |
| `risk.py` | `get_rulings_for`, `anti_avoidance_rate`, `find_claimable` |

`resolve_citation`은 법령명을 정적 정규식이 아니라 **실제 적재된 `statute.name`/
`abbreviations`에서 동적으로 정규식을 구성**한다 — "상속세 및 증여세법"처럼 정식 명칭에
공백이 낀 경우도 정확히 잡는다. "구 OO법(1996.12.30. 법률 제5193호로 전부개정되고, ...
개정되기 전의 것)" 같은 실제 판례 인용 표기에서 첫 날짜를 추출해 그 시점 버전으로 해소한다.
정확도는 `lawcorpus eval-citations --golden tests/fixtures/citations.jsonl`로 측정한다
(precision/recall).

`as_of`는 위치 필수 인자 + `resolution.require_as_of()` 런타임 가드로 강제한다 — Python은
타입힌트를 런타임에 강제하지 않기 때문이다.

## 알려진 제약

- `article_rewrite_map`(전부개정 수작업 매핑)은 인프라만 있고 실 데이터는 비어있다 —
  전부개정 실 사례를 아직 못 찾았다(현재 적재된 국세기본법 계열은 제정 이후 전부개정
  이력이 없다).
- `ruling.cited_article_ids`는 아직 백필 전이라 `get_risk_neighbors`/`find_unpatched`/
  `get_rulings_for`가 현재 빈 결과를 반환한다 — `resolve_citation`으로 판례 본문의 인용을
  일괄 해소하는 배치가 필요하다(M6 예정).
- 검색(`search()`, 항 단위 임베딩)은 M7 — 구조가 확정되기 전에 임베딩을 돌리면 재작업만
  늘어난다는 판단.
