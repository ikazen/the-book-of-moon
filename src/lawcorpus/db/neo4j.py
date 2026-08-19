from __future__ import annotations

from neo4j import AsyncGraphDatabase, AsyncDriver

_driver: AsyncDriver | None = None


async def init_neo4j(uri: str, user: str, password: str) -> None:
    global _driver
    _driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    await _driver.verify_connectivity()


async def close_neo4j() -> None:
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


def get_driver() -> AsyncDriver:
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialised")
    return _driver


async def ping_neo4j() -> bool:
    async with get_driver().session() as session:
        result = await session.run("RETURN 1 AS n")
        record = await result.single()
        return record is not None and record["n"] == 1
