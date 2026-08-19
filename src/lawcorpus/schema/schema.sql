-- pgvector 확장 (DB 생성 후 최초 1회)
CREATE EXTENSION IF NOT EXISTS vector;

-- 조문 청크
CREATE TABLE IF NOT EXISTS article_chunks (
    chunk_id        TEXT PRIMARY KEY,
    law_name        TEXT NOT NULL,
    article_no      TEXT NOT NULL,
    clause_path     TEXT,
    parent_chunk_id TEXT,
    text            TEXT NOT NULL,
    effective_from  DATE NOT NULL,
    effective_to    DATE,
    is_current      BOOLEAN NOT NULL DEFAULT TRUE,
    embedding       VECTOR(1024),
    tsv             TSVECTOR
);

-- 판례 청크
CREATE TABLE IF NOT EXISTS case_chunks (
    chunk_id      TEXT PRIMARY KEY,
    case_no       TEXT NOT NULL,
    court         TEXT,
    decided_at    DATE NOT NULL,
    is_en_banc    BOOLEAN,
    validity_flag TEXT CHECK (validity_flag IN ('valid', 'overruled', 'law_amended', 'uncertain')),
    text          TEXT NOT NULL,
    embedding     VECTOR(1024),
    tsv           TSVECTOR
);

-- tsv 자동 갱신 트리거
CREATE OR REPLACE FUNCTION article_chunks_tsv_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.tsv := to_tsvector('simple', coalesce(NEW.law_name, '') || ' ' ||
                                     coalesce(NEW.article_no, '') || ' ' ||
                                     coalesce(NEW.clause_path, '') || ' ' ||
                                     coalesce(NEW.text, ''));
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER article_chunks_tsv_trigger
BEFORE INSERT OR UPDATE ON article_chunks
FOR EACH ROW EXECUTE FUNCTION article_chunks_tsv_update();

CREATE OR REPLACE FUNCTION case_chunks_tsv_update() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.tsv := to_tsvector('simple', coalesce(NEW.case_no, '') || ' ' ||
                                     coalesce(NEW.court, '') || ' ' ||
                                     coalesce(NEW.text, ''));
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER case_chunks_tsv_trigger
BEFORE INSERT OR UPDATE ON case_chunks
FOR EACH ROW EXECUTE FUNCTION case_chunks_tsv_update();

-- 벡터 인덱스 (hnsw)
CREATE INDEX IF NOT EXISTS article_chunks_embedding_idx
    ON article_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS case_chunks_embedding_idx
    ON case_chunks USING hnsw (embedding vector_cosine_ops);

-- 키워드 인덱스 (gin)
CREATE INDEX IF NOT EXISTS article_chunks_tsv_idx ON article_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS case_chunks_tsv_idx    ON case_chunks    USING gin (tsv);

-- small-to-big parent fetch 가속 (항/호 child -> 조 parent)
CREATE INDEX IF NOT EXISTS article_chunks_parent_idx ON article_chunks (parent_chunk_id);
