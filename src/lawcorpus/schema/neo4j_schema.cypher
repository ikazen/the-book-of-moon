// Neo4j 제약 + 인덱스 (Corpus 레이블 네임스페이스)
// Community Edition: 단일 그래프 — Corpus 레이블로 워크로드 격리

// 고유 제약 (자동 인덱스 포함)
CREATE CONSTRAINT corpus_article_chunk_id IF NOT EXISTS
    FOR (n:CorpusArticle) REQUIRE n.chunk_id IS UNIQUE;

CREATE CONSTRAINT corpus_case_chunk_id IF NOT EXISTS
    FOR (n:CorpusCase) REQUIRE n.chunk_id IS UNIQUE;

CREATE CONSTRAINT corpus_amendment_id IF NOT EXISTS
    FOR (n:CorpusAmendment) REQUIRE n.amendment_id IS UNIQUE;

// 조회용 인덱스
CREATE INDEX corpus_article_law_article IF NOT EXISTS
    FOR (n:CorpusArticle) ON (n.law_name, n.article_no);

CREATE INDEX corpus_case_case_no IF NOT EXISTS
    FOR (n:CorpusCase) ON (n.case_no);

CREATE INDEX corpus_case_validity IF NOT EXISTS
    FOR (n:CorpusCase) ON (n.validity_flag);
