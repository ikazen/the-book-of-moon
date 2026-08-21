from __future__ import annotations

from dataclasses import replace

import httpx

from lawcorpus.types import Hit


async def rerank(query: str, chunks: list[Hit], settings, top_k: int | None = None) -> list[Hit]:
    """Rerank hits using bge-reranker-v2-m3 via Ollama /api/rerank.

    Falls back to original order if the endpoint is unavailable.
    top_k defaults to settings.rerank_top_k (5).
    """
    if not chunks:
        return chunks

    k = top_k if top_k is not None else settings.rerank_top_k

    documents = [c.text for c in chunks]
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/rerank",
                json={
                    "model": settings.reranker_model,
                    "query": query,
                    "documents": documents,
                    "top_n": k,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPStatusError, httpx.RequestError):
        # Ollama /api/rerank 미지원 버전이면 RRF 순위 유지
        return chunks[:k]

    # 응답: {"results": [{"index": int, "relevance_score": float}, ...]}
    results = data.get("results", [])
    if not results:
        return chunks[:k]

    scored = sorted(results, key=lambda r: r["relevance_score"], reverse=True)
    reranked: list[Hit] = []
    for item in scored[:k]:
        idx = item["index"]
        if 0 <= idx < len(chunks):
            reranked.append(replace(chunks[idx], score=float(item["relevance_score"])))
    return reranked
