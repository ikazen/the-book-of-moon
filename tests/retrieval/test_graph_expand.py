from __future__ import annotations

import pytest


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    async def data(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self.queries: list[tuple[str, dict]] = []

    async def run(self, query: str, **kwargs):
        self.queries.append((query, kwargs))
        return _FakeResult(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSessionCM:
    """driver.session()이 반환하는 (non-async) 컨텍스트매니저 팩토리."""

    def __init__(self, session: _FakeSession):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class _FakeDriver:
    def __init__(self, rows: list[dict]):
        self._session = _FakeSession(rows)

    def session(self):
        return _FakeSessionCM(self._session)


def _patch_driver(monkeypatch, rows: list[dict]):
    driver = _FakeDriver(rows)
    import lawcorpus.retrieval.graph_expand as ge_mod
    monkeypatch.setattr(ge_mod, "get_driver", lambda: driver)
    return driver


@pytest.mark.asyncio
async def test_expand_1hop_carries_effective_dates(monkeypatch):
    """RETURN에 effective_from/to가 있어야 시점 필터가 실제로 작동한다."""
    _patch_driver(monkeypatch, rows=[
        {
            "chunk_id": "art_법인세법_52_1_old",
            "label": "CorpusArticle",
            "validity_flag": None,
            "law_name": "법인세법",
            "article_no": "제52조",
            "court": None,
            "effective_from": "2010-01-01",
            "effective_to": "2018-12-31",
        },
    ])

    from lawcorpus.retrieval.graph_expand import expand_1hop
    result = await expand_1hop(["case_2018두12345"])

    assert len(result) == 1
    assert result[0].meta["effective_from"] == "2010-01-01"
    assert result[0].meta["effective_to"] == "2018-12-31"


@pytest.mark.asyncio
async def test_expand_2hop_carries_effective_dates(monkeypatch):
    _patch_driver(monkeypatch, rows=[
        {
            "chunk_id": "art_법인세법_52_1",
            "amendment_id": None,
            "label": "CorpusArticle",
            "validity_flag": None,
            "law_name": "법인세법",
            "article_no": "제52조",
            "effective_from": "2019-01-01",
            "effective_to": None,
        },
    ])

    from lawcorpus.retrieval.graph_expand import expand_2hop
    result = await expand_2hop(["case_2020두99999"])

    assert len(result) == 1
    assert result[0].meta["effective_from"] == "2019-01-01"
    assert "effective_to" not in result[0].meta  # None 값은 dict comprehension에서 제외


@pytest.mark.asyncio
async def test_expand_1hop_then_filter_by_transaction_date_excludes_expired(monkeypatch):
    """RETURN → meta → filter_by_transaction_date 전체 경로가 실제로 필터링하는지."""
    _patch_driver(monkeypatch, rows=[
        {
            "chunk_id": "art_법인세법_52_1_old",
            "label": "CorpusArticle",
            "validity_flag": None,
            "law_name": "법인세법",
            "article_no": "제52조",
            "court": None,
            "effective_from": "2010-01-01",
            "effective_to": "2018-12-31",
        },
        {
            "chunk_id": "art_법인세법_52_1",
            "label": "CorpusArticle",
            "validity_flag": None,
            "law_name": "법인세법",
            "article_no": "제52조",
            "court": None,
            "effective_from": "2019-01-01",
            "effective_to": None,
        },
    ])

    from lawcorpus.retrieval.graph_expand import expand_1hop, filter_by_transaction_date
    chunks = await expand_1hop(["case_x"])
    filtered = filter_by_transaction_date(chunks, "2015-06-01")

    ids = {c.chunk_id for c in filtered}
    assert ids == {"art_법인세법_52_1_old"}  # 2015년 거래는 구법(~2018-12-31)만 유효
