from __future__ import annotations

import asyncio

from lawcorpus.retrieval.context_expand import expand_to_parents
from lawcorpus.retrieval.embedder import embed_query
from lawcorpus.retrieval.fusion import rrf_fuse
from lawcorpus.retrieval.graph_expand import expand_1hop
from lawcorpus.retrieval.keyword_search import keyword_search
from lawcorpus.retrieval.reranker import rerank
from lawcorpus.retrieval.vector_search import hydrate_by_ids, vector_search
from lawcorpus.types import Chunk


async def promotion_score(query: str, settings) -> float:
    """벡터 top-1 코사인만 확인하는 경량 신호. 전체 hybrid_search를 돌리지 않고도
    소비처가 "이 질의는 코퍼스와 얼마나 가까운가"를 싼 값에 판정할 수 있게 한다.
    """
    embedding = await embed_query(query, settings)
    vec_chunks = await vector_search(embedding, top_k=1)
    return vec_chunks[0].score if vec_chunks else 0.0


async def parallel_search(
    embedding: list[float],
    query: str,
    top_k: int,
) -> tuple[list[Chunk], list[Chunk]]:
    vec_task = asyncio.create_task(vector_search(embedding, top_k=top_k))
    kw_task = asyncio.create_task(keyword_search(query, top_k=top_k))
    vec_chunks, kw_chunks = await asyncio.gather(vec_task, kw_task)
    return vec_chunks, kw_chunks


async def hybrid_search(query: str, settings) -> list[Chunk]:
    """벡터+키워드 RRF 융합 → 리랭크 → 1홉 그래프 확장 → parent 확장.

    LLM을 호출하지 않는다(결정 A) — HyDE·질의분해가 필요한 검색은 소비처가 이
    함수를 원자 단위로 가져다 직접 조합한다.
    """
    embedding = await embed_query(query, settings)
    vec_chunks, kw_chunks = await parallel_search(embedding, query, settings.retrieve_top_k)
    fused = rrf_fuse(vec_chunks, kw_chunks, k=settings.rrf_k, top_n=settings.retrieve_top_k)
    reranked = await rerank(query, fused, settings)
    extra_graph = await expand_1hop([c.chunk_id for c in reranked])
    extra_chunk_ids = {g.chunk_id for g in extra_graph}
    reranked_ids = {r.chunk_id for r in reranked}
    fused_ids = {c.chunk_id for c in fused}
    in_pool = [c for c in fused if c.chunk_id in extra_chunk_ids and c.chunk_id not in reranked_ids]
    # 검색 후보 풀(fused) 밖에서 그래프로만 발견된 chunk는 본문을 PG에서 직접 채운다
    # — 그렇지 않으면 id만 알고 텍스트가 없어 통째로 드롭된다(pot-of-greed #8).
    missing_ids = extra_chunk_ids - fused_ids - reranked_ids
    hydrated = await hydrate_by_ids(list(missing_ids)) if missing_ids else []
    final_chunks = reranked + in_pool + hydrated
    final_chunks += await expand_to_parents(final_chunks)
    return final_chunks
