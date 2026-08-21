-- v0.x 플랫 청크 스토어 제거. apply_schema(settings, drop=True)에서 schema.sql 적용 전에 실행.

DROP TRIGGER IF EXISTS article_chunks_tsv_trigger ON article_chunks;
DROP TRIGGER IF EXISTS case_chunks_tsv_trigger ON case_chunks;
DROP FUNCTION IF EXISTS article_chunks_tsv_update();
DROP FUNCTION IF EXISTS case_chunks_tsv_update();
DROP TABLE IF EXISTS article_chunks CASCADE;
DROP TABLE IF EXISTS case_chunks CASCADE;
