import pytest

from lawcorpus.schema.apply import _run_cypher_script


class _FakeSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def run(self, stmt: str) -> None:
        self.statements.append(stmt)


@pytest.mark.asyncio
async def test_leading_comment_does_not_swallow_first_statement() -> None:
    script = """\
// header comment line 1
// header comment line 2

MATCH (n)
WHERE n:Foo
DETACH DELETE n;

CREATE CONSTRAINT bar_id IF NOT EXISTS
    FOR (n:Bar) REQUIRE n.bar_id IS UNIQUE;
"""
    session = _FakeSession()
    await _run_cypher_script(session, script)

    assert len(session.statements) == 2
    assert "MATCH (n)" in session.statements[0]
    assert "DETACH DELETE n" in session.statements[0]
    assert "CREATE CONSTRAINT bar_id" in session.statements[1]
