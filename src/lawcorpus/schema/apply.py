"""PG DDL + Neo4j 제약을 멱등 적용."""

from __future__ import annotations

import importlib.resources

import asyncpg
from neo4j import AsyncGraphDatabase
from pgvector.asyncpg import register_vector


def _read_resource(name: str) -> str:
    return (importlib.resources.files("lawcorpus.schema") / name).read_text()


async def apply_pg_schema(dsn: str, *, drop: bool = False) -> None:
    conn = await asyncpg.connect(dsn=dsn)
    await register_vector(conn)
    try:
        if drop:
            await conn.execute(_read_resource("drop.sql"))
        await conn.execute(_read_resource("schema.sql"))
    finally:
        await conn.close()


async def _run_cypher_script(session, script: str) -> None:
    for stmt in script.split(";"):
        stmt = stmt.strip()
        if stmt and not stmt.startswith("//"):
            await session.run(stmt)


async def apply_neo4j_schema(uri: str, user: str, password: str, *, drop: bool = False) -> None:
    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    try:
        async with driver.session() as session:
            if drop:
                await _run_cypher_script(session, _read_resource("neo4j_drop.cypher"))
            await _run_cypher_script(session, _read_resource("neo4j_schema.cypher"))
    finally:
        await driver.close()


async def apply_schema(settings, *, drop: bool = False) -> None:
    await apply_pg_schema(settings.pg_dsn, drop=drop)
    await apply_neo4j_schema(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password, drop=drop)
