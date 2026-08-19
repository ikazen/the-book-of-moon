from __future__ import annotations

import asyncpg
from pgvector.asyncpg import register_vector

_pool: asyncpg.Pool | None = None


async def init_pg(dsn: str) -> None:
    global _pool
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10, init=register_vector)


async def close_pg() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("PG pool not initialised")
    return _pool


async def ping_pg() -> bool:
    async with get_pool().acquire() as conn:
        result = await conn.fetchval("SELECT 1")
        return result == 1
