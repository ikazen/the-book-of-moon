from __future__ import annotations

import httpx


async def embed_query(text: str, settings) -> list[float]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/embed",
            json={"model": settings.embedding_model, "input": text, "dimensions": settings.embedding_dim},
        )
        resp.raise_for_status()
    data = resp.json()
    # Ollama /api/embed 응답: {"embeddings": [[...]], ...}
    return data["embeddings"][0]


async def embed_batch(texts: list[str], settings) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/embed",
            json={"model": settings.embedding_model, "input": texts, "dimensions": settings.embedding_dim},
        )
        resp.raise_for_status()
    data = resp.json()
    return data["embeddings"]
