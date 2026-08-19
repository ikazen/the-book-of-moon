from __future__ import annotations

import pytest


class _FakeConn:
    """article_chunks/case_chunks 조회를 시뮬레이션하는 fake connection.

    chunk_id -> row dict 매핑을 테이블별로 갖고, fetch() 호출 시 요청된
    chunk_id 목록에 해당하는 행만 반환한다.
    """

    def __init__(self, articles: dict[str, dict], cases: dict[str, dict]):
        self._articles = articles
        self._cases = cases
        self.queries: list[tuple[str, tuple]] = []

    async def fetch(self, sql: str, *params):
        self.queries.append((sql, params))
        ids = params[0]
        if "article_chunks" in sql:
            return [row for cid, row in self._articles.items() if cid in ids]
        return [row for cid, row in self._cases.items() if cid in ids]


class _FakeAcquire:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


def _patch_pool(monkeypatch, articles=None, cases=None):
    conn = _FakeConn(articles or {}, cases or {})
    pool = _FakePool(conn)
    import lawcorpus.retrieval.vector_search as vs_mod
    monkeypatch.setattr(vs_mod, "get_pool", lambda: pool)
    return conn


@pytest.mark.asyncio
async def test_hydrate_by_ids_empty_input_no_query(monkeypatch):
    conn = _patch_pool(monkeypatch)

    from lawcorpus.retrieval.vector_search import hydrate_by_ids
    result = await hydrate_by_ids([])

    assert result == []
    assert conn.queries == []


@pytest.mark.asyncio
async def test_hydrate_by_ids_fetches_article(monkeypatch):
    _patch_pool(monkeypatch, articles={
        "art_1": {
            "chunk_id": "art_1", "text": "본문", "law_name": "소득세법",
            "article_no": "제14조", "clause_path": None, "is_current": True,
        },
    })

    from lawcorpus.retrieval.vector_search import hydrate_by_ids
    result = await hydrate_by_ids(["art_1"])

    assert len(result) == 1
    chunk = result[0]
    assert chunk.chunk_id == "art_1"
    assert chunk.table == "article"
    assert chunk.text == "본문"
    assert chunk.score == 0.0  # 검색 랭크 없음
    assert chunk.meta["law_name"] == "소득세법"


@pytest.mark.asyncio
async def test_hydrate_by_ids_fetches_case_with_validity_flag(monkeypatch):
    """hydrate된 case chunk의 meta에 validity_flag가 실려야 downstream 경고 경로가
    반응할 수 있다."""
    _patch_pool(monkeypatch, cases={
        "case_1": {
            "chunk_id": "case_1", "text": "판결문", "case_no": "2018두12345",
            "court": "대법원", "validity_flag": "overruled", "decided_at": "2020-01-01",
        },
    })

    from lawcorpus.retrieval.vector_search import hydrate_by_ids
    result = await hydrate_by_ids(["case_1"])

    assert len(result) == 1
    chunk = result[0]
    assert chunk.table == "case"
    assert chunk.meta["validity_flag"] == "overruled"


@pytest.mark.asyncio
async def test_hydrate_by_ids_mixed_article_and_case(monkeypatch):
    _patch_pool(
        monkeypatch,
        articles={"art_1": {
            "chunk_id": "art_1", "text": "조문", "law_name": "법인세법",
            "article_no": "제52조", "clause_path": None, "is_current": True,
        }},
        cases={"case_1": {
            "chunk_id": "case_1", "text": "판결문", "case_no": "2018두12345",
            "court": "대법원", "validity_flag": "valid", "decided_at": "2020-01-01",
        }},
    )

    from lawcorpus.retrieval.vector_search import hydrate_by_ids
    result = await hydrate_by_ids(["art_1", "case_1"])

    ids = {c.chunk_id for c in result}
    assert ids == {"art_1", "case_1"}


@pytest.mark.asyncio
async def test_hydrate_by_ids_missing_id_silently_skipped(monkeypatch):
    """존재하지 않는 chunk_id는 그냥 결과에서 빠진다(에러 아님)."""
    _patch_pool(monkeypatch)

    from lawcorpus.retrieval.vector_search import hydrate_by_ids
    result = await hydrate_by_ids(["존재하지않는_id"])

    assert result == []
