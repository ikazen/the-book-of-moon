// v0.x Corpus* 레이블 + 고아 레이블(PotOfGreedCase/PotOfGreedAmendment, 0노드) 제거.
// apply_neo4j_schema(..., drop=True)에서 neo4j_schema.cypher 적용 전에 실행.

MATCH (n)
WHERE n:CorpusArticle OR n:CorpusCase OR n:CorpusAmendment
   OR n:PotOfGreedCase OR n:PotOfGreedAmendment
DETACH DELETE n;

DROP CONSTRAINT corpus_article_chunk_id IF EXISTS;
DROP CONSTRAINT corpus_case_chunk_id IF EXISTS;
DROP CONSTRAINT corpus_amendment_id IF EXISTS;
DROP INDEX corpus_article_law_article IF EXISTS;
DROP INDEX corpus_case_case_no IF EXISTS;
DROP INDEX corpus_case_validity IF EXISTS;

// pot-of-greed 분리 이전(Corpus 리네임 전) 잔존 제약 — 노드는 이미 0개이지만 제약 토큰은 남아있었다
DROP CONSTRAINT poc_amendment_id IF EXISTS;
DROP CONSTRAINT poc_case_chunk_id IF EXISTS;
DROP INDEX poc_case_case_no IF EXISTS;
DROP INDEX poc_case_validity IF EXISTS;
