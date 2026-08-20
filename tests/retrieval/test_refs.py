from __future__ import annotations

import pytest


def test_extract_refs_from_article_text():
    from lawcorpus.refs import extract_refs
    text = "소득세법 제89조에 따르면 1세대1주택은 비과세된다."
    refs = extract_refs(text)
    assert "소득세법 제89조" in refs


def test_extract_refs_from_case_text():
    from lawcorpus.refs import extract_refs
    text = "대법원 2018두12345 판결에서 이 기준을 확립했다."
    refs = extract_refs(text)
    assert "2018두12345" in refs


def test_extract_refs_empty_when_no_refs():
    from lawcorpus.refs import extract_refs
    assert extract_refs("보유기간 2년 이상이 필요하다.") == []


def test_extract_refs_ignores_date_expressions():
    """날짜 표현("2018년6월15일")이 판례번호로 오탐되어선 안 된다."""
    from lawcorpus.refs import extract_refs
    text = "양도일이 2018년6월15일인 경우 소득세법 제89조가 적용된다."
    refs = extract_refs(text)
    assert "소득세법 제89조" in refs
    assert "2018년6" not in refs
    assert not any(r.startswith("2018년") for r in refs)


def test_extract_refs_various_case_type_codes():
    """사건부호 화이트리스트가 실무에서 흔한 부호들을 계속 인식하는지 확인."""
    from lawcorpus.refs import extract_refs
    text = "2015다12345, 2020도6789, 2019헌가1 판결을 참고하라."
    refs = extract_refs(text)
    assert "2015다12345" in refs
    assert "2020도6789" in refs
    assert "2019헌가1" in refs


def test_extract_refs_branch_article():
    """가지번호 조문("제18조의3")도 하나의 조문 인용으로 추출되어야 한다."""
    from lawcorpus.refs import extract_refs
    text = "법인세법 제18조의3에 따르면 수입배당금은 익금불산입된다."
    refs = extract_refs(text)
    assert "법인세법 제18조의3" in refs


def test_extract_refs_enforcement_decree():
    from lawcorpus.refs import extract_refs
    text = "소득세법 시행령 제10조에 구체적 기준이 있다."
    refs = extract_refs(text)
    assert "소득세법 시행령 제10조" in refs


def test_extract_refs_enforcement_rule():
    from lawcorpus.refs import extract_refs
    text = "법인세법 시행규칙 제3조를 참고하라."
    refs = extract_refs(text)
    assert "법인세법 시행규칙 제3조" in refs


class _FakeConn:
    """article_chunks/case_chunks 동등 매칭을 시뮬레이션하는 fake connection.

    시드는 (law_name, article_no) 튜플 집합과 case_no 집합으로 구성.
    실행된 (sql, params)를 기록해 어떤 컬럼으로 질의했는지 assert 가능.
    """

    def __init__(self, articles: set[tuple[str, str]], cases: set[str]):
        self.articles = articles
        self.cases = cases
        self.calls: list[tuple[str, tuple]] = []

    async def fetchval(self, sql: str, *params):
        self.calls.append((sql, params))
        if "article_chunks" in sql:
            return 1 if tuple(params) in self.articles else None
        return 1 if params[0] in self.cases else None


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


def _patch_pool(monkeypatch, articles=frozenset(), cases=frozenset()):
    conn = _FakeConn(set(articles), set(cases))
    pool = _FakePool(conn)

    import lawcorpus.refs as refs_mod
    monkeypatch.setattr(refs_mod, "get_pool", lambda: pool)
    return conn


@pytest.mark.asyncio
async def test_verify_refs_exist_existing(monkeypatch):
    _patch_pool(monkeypatch, articles={("소득세법", "제89조")})

    from lawcorpus.refs import verify_refs_exist
    result = await verify_refs_exist(["소득세법 제89조"])
    assert result["소득세법 제89조"] is True


@pytest.mark.asyncio
async def test_verify_refs_exist_hallucinated(monkeypatch):
    _patch_pool(monkeypatch)

    from lawcorpus.refs import verify_refs_exist
    result = await verify_refs_exist(["존재하지않는법 제9999조"])
    assert result["존재하지않는법 제9999조"] is False


@pytest.mark.asyncio
async def test_verify_refs_exist_wrong_law_name_rejected(monkeypatch):
    """법명은 오귀속이고 조번호만 실재하는 인용 — 구조적 동등 매칭에서 걸러져야 한다.

    회귀 방지: 기존 FTS AND-토큰 매칭이었다면 두 토큰이 다른 청크에서라도
    동시 등장하면 통과했던 케이스.
    """
    _patch_pool(monkeypatch, articles={("소득세법", "제89조")})

    from lawcorpus.refs import verify_refs_exist
    result = await verify_refs_exist(["법인세법 제89조"])
    assert result["법인세법 제89조"] is False


@pytest.mark.asyncio
async def test_verify_refs_exist_empty_refs():
    from lawcorpus.refs import verify_refs_exist
    result = await verify_refs_exist([])
    assert result == {}


@pytest.mark.asyncio
async def test_verify_refs_exist_multiple(monkeypatch):
    _patch_pool(monkeypatch, articles={("소득세법", "제89조")})

    from lawcorpus.refs import verify_refs_exist
    result = await verify_refs_exist(["소득세법 제89조", "없는법 제1조"])
    assert result["소득세법 제89조"] is True
    assert result["없는법 제1조"] is False


@pytest.mark.asyncio
async def test_verify_refs_exist_enforcement_decree(monkeypatch):
    """시행령 인용도 "법령명 시행령"으로 재조립되어 컬럼 동등 매칭된다(#12)."""
    _patch_pool(monkeypatch, articles={("소득세법 시행령", "제10조")})

    from lawcorpus.refs import verify_refs_exist
    result = await verify_refs_exist(["소득세법 시행령 제10조"])
    assert result["소득세법 시행령 제10조"] is True


@pytest.mark.asyncio
async def test_verify_refs_exist_case_no(monkeypatch):
    _patch_pool(monkeypatch, cases={"2018두12345"})

    from lawcorpus.refs import verify_refs_exist
    result = await verify_refs_exist(["2018두12345"])
    assert result["2018두12345"] is True


@pytest.mark.asyncio
async def test_verify_refs_exist_clause_matched_at_article_level(monkeypatch):
    """항(제N항)이 붙은 ref도 조 단위(law_name+article_no)로 매칭된다."""
    conn = _patch_pool(monkeypatch, articles={("소득세법", "제14조")})

    from lawcorpus.refs import verify_refs_exist
    result = await verify_refs_exist(["소득세법 제14조 제1항"])
    assert result["소득세법 제14조 제1항"] is True
    assert conn.calls == [
        (
            "SELECT 1 FROM article_chunks WHERE law_name = $1 AND article_no = $2 LIMIT 1",
            ("소득세법", "제14조"),
        )
    ]


class TestParseRef:
    def test_article(self):
        from lawcorpus.refs import parse_ref
        assert parse_ref("소득세법 제89조") == ("article", ("소득세법", "제89조"))

    def test_article_with_clause(self):
        from lawcorpus.refs import parse_ref
        assert parse_ref("소득세법 제14조 제1항") == ("article", ("소득세법", "제14조"))

    def test_case(self):
        from lawcorpus.refs import parse_ref
        assert parse_ref("2018두12345") == ("case", ("2018두12345",))

    def test_unparseable(self):
        from lawcorpus.refs import parse_ref
        assert parse_ref("아무말") is None

    def test_article_branch(self):
        """"제18조의3" 가지번호 조문도 article_no 전체(의N 포함)로 파싱된다."""
        from lawcorpus.refs import parse_ref
        assert parse_ref("법인세법 제18조의3") == ("article", ("법인세법", "제18조의3"))

    def test_enforcement_decree(self):
        from lawcorpus.refs import parse_ref
        assert parse_ref("소득세법 시행령 제10조") == ("article", ("소득세법 시행령", "제10조"))

    def test_enforcement_rule(self):
        from lawcorpus.refs import parse_ref
        assert parse_ref("법인세법 시행규칙 제3조") == ("article", ("법인세법 시행규칙", "제3조"))

    def test_abbreviation_normalized(self):
        from lawcorpus.refs import parse_ref
        assert parse_ref("조특법 제10조") == ("article", ("조세특례제한법", "제10조"))
