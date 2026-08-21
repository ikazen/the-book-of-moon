// Neo4j 제약 + 인덱스. 무프리픽스 레이블 — 이 인스턴스는 lawcorpus 전용으로 간주한다(결정 K).
// 참조 엣지(REFERS_TO/MUTATIS/DELEGATES)는 Version이 아니라 Article 논리노드 사이에 걸고
// valid_from/valid_to를 엣지 프로퍼티로 준다 — 버전마다 엣지가 곱셈으로 늘어나는 것을 막는다.

// 고유 제약 (자동 인덱스 포함)
CREATE CONSTRAINT statute_id IF NOT EXISTS
    FOR (n:Statute) REQUIRE n.statute_id IS UNIQUE;

CREATE CONSTRAINT article_id IF NOT EXISTS
    FOR (n:Article) REQUIRE n.article_id IS UNIQUE;

CREATE CONSTRAINT version_article_key IF NOT EXISTS
    FOR (n:Version) REQUIRE n.article_key IS UNIQUE;

CREATE CONSTRAINT addendum_id IF NOT EXISTS
    FOR (n:Addendum) REQUIRE n.addendum_id IS UNIQUE;

CREATE CONSTRAINT ruling_id IF NOT EXISTS
    FOR (n:Ruling) REQUIRE n.ruling_id IS UNIQUE;

CREATE CONSTRAINT term_name IF NOT EXISTS
    FOR (n:Term) REQUIRE n.name IS UNIQUE;

CREATE CONSTRAINT doctrine_name IF NOT EXISTS
    FOR (n:Doctrine) REQUIRE n.name IS UNIQUE;

CREATE CONSTRAINT pattern_type IF NOT EXISTS
    FOR (n:Pattern) REQUIRE n.pattern_type IS UNIQUE;

CREATE CONSTRAINT loophole_id IF NOT EXISTS
    FOR (n:Loophole) REQUIRE n.id IS UNIQUE;

// 조회용 인덱스
CREATE INDEX article_statute_art_no IF NOT EXISTS
    FOR (n:Article) ON (n.statute_id, n.art_no, n.branch_no);

CREATE INDEX version_valid_from IF NOT EXISTS
    FOR (n:Version) ON (n.valid_from);

CREATE INDEX ruling_outcome IF NOT EXISTS
    FOR (n:Ruling) ON (n.outcome);

CREATE INDEX ruling_decided_on IF NOT EXISTS
    FOR (n:Ruling) ON (n.decided_on);

CREATE INDEX loophole_status IF NOT EXISTS
    FOR (n:Loophole) ON (n.status);
