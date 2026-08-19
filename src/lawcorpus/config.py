from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class LawCorpusSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LAWCORPUS_", env_file=".env", env_file_encoding="utf-8")

    # databases
    pg_dsn: str
    neo4j_uri: str
    neo4j_user: str = "neo4j"
    neo4j_password: str

    # ollama — 임베딩 + 리랭킹
    ollama_base_url: str
    embedding_model: str = "qwen3-embedding:8b"
    embedding_dim: int = 1024
    reranker_model: str = "bge-reranker-v2-m3"

    # law.go.kr OPEN API (법제처 국가법령정보 공동활용)
    law_api_base_url: str = "http://www.law.go.kr/DRF"
    law_api_oc: str = ""

    # retrieval 노브
    retrieve_top_k: int = 30
    rerank_top_k: int = 5
    rrf_k: int = 60


@lru_cache
def get_settings() -> LawCorpusSettings:
    return LawCorpusSettings()
