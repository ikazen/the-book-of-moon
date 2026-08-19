"""PG DDL + Neo4j 제약을 멱등 적용."""

from __future__ import annotations

import importlib.resources

import asyncpg
from neo4j import AsyncGraphDatabase
from pgvector.asyncpg import register_vector


def _read_resource(name: str) -> str:
    return (importlib.resources.files("lawcorpus.schema") / name).read_text()


async def apply_pg_schema(dsn: str) -> None:
    conn = await asyncpg.connect(dsn=dsn)
    await register_vector(conn)
    try:
        await conn.execute(_read_resource("schema.sql"))
    finally:
        await conn.close()


async def apply_neo4j_schema(uri: str, user: str, password: str) -> None:
    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    try:
        async with driver.session() as session:
            for stmt in _read_resource("neo4j_schema.cypher").split(";"):
                stmt = stmt.strip()
                if stmt and not stmt.startswith("//"):
                    await session.run(stmt)
    finally:
        await driver.close()


async def apply_schema(settings) -> None:
    await apply_pg_schema(settings.pg_dsn)
    await apply_neo4j_schema(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
