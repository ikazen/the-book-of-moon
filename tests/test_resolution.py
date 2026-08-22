from __future__ import annotations

from datetime import date

import pytest

from lawcorpus.resolution import require_as_of, get_article, get_effective_law, parse_citation, resolve_citation

_LAW_NAMES = [
    "국세기본법", "국세기본법 시행령", "소득세법", "법인세법", "부가가치세법",
    "상속세 및 증여세법", "상속세 및 증여세법 시행령", "조세특례제한법", "조세특례제한법 시행령",
    "조특법", "국기법",
]


# --- require_as_of ---

def testrequire_as_of_accepts_date():
    d = date(2020, 1, 1)
    assert require_as_of(d) is d


def testrequire_as_of_rejects_none():
    with pytest.raises(TypeError):
        require_as_of(None)


def testrequire_as_of_rejects_string():
    with pytest.raises(TypeError):
        require_as_of("2020-01-01")


# --- parse_citation ---

def test_parse_citation_simple():
    result = parse_citation("소득세법 제89조에 따르면", _LAW_NAMES)
    assert result == {"law": "소득세법", "art_no": 89, "branch_no": 0, "historical_date": None}


def test_parse_citation_branch_article():
    result = parse_citation("법인세법 제18조의3에 따르면", _LAW_NAMES)
    assert result["law"] == "법인세법"
    assert result["art_no"] == 18
    assert result["branch_no"] == 3


def test_parse_citation_law_name_with_space():
    """"상속세 및 증여세법"처럼 정식 명칭에 공백이 있어도 매칭돼야 한다."""
    result = parse_citation("상속세 및 증여세법 제16조에 따르면", _LAW_NAMES)
    assert result["law"] == "상속세 및 증여세법"
    assert result["art_no"] == 16


def test_parse_citation_subordinate_legislation():
    result = parse_citation("국세기본법 시행령 제2조", _LAW_NAMES)
    assert result["law"] == "국세기본법 시행령"
    assert result["art_no"] == 2


def test_parse_citation_abbreviation_normalized():
    result = parse_citation("조특법 제10조", _LAW_NAMES)
    assert result["law"] == "조세특례제한법"


def test_parse_citation_old_prefix_without_detail_no_historical_date():
    result = parse_citation("구 국세기본법 제5조", _LAW_NAMES)
    assert result["law"] == "국세기본법"
    assert result["historical_date"] is None


def test_parse_citation_old_with_explicit_historical_detail():
    """실측(detc_detail.xml) 기준 실제 판례 인용 표기."""
    text = ("구 상속세 및 증여세법(1996. 12. 30. 법률 제5193호로 전부개정되고, "
            "2003. 12. 30. 법률 제7010호로 개정되기 전의 것) 제14조 제2항")
    result = parse_citation(text, _LAW_NAMES)
    assert result["law"] == "상속세 및 증여세법"
    assert result["art_no"] == 14
    assert result["historical_date"] == date(1996, 12, 30)


def test_parse_citation_unknown_law_returns_none():
    assert parse_citation("존재하지않는법 제1조", _LAW_NAMES) is None


def test_parse_citation_no_article_number_returns_none():
    assert parse_citation("소득세법에 따르면", _LAW_NAMES) is None


def test_parse_citation_empty_law_names_returns_none():
    assert parse_citation("소득세법 제89조", []) is None


def test_parse_citation_longest_name_preferred_over_prefix():
    """"국세기본법 시행령"이 "국세기본법"의 부분 매칭으로 잘리면 안 된다."""
    result = parse_citation("국세기본법 시행령 제10조", _LAW_NAMES)
    assert result["law"] == "국세기본법 시행령"


# --- DB 연동 (실 DB 스모크 — CI에서 접속 불가 시 자동 skip) ---

async def _pg_reachable(dsn: str) -> bool:
    try:
        import asyncpg
        conn = await asyncpg.connect(dsn=dsn, timeout=3)
        await conn.close()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_get_article_and_resolve_citation_against_real_db():
    from lawcorpus.config import get_settings
    from lawcorpus.db.pg import close_pg, init_pg

    settings = get_settings()
    if not await _pg_reachable(settings.pg_dsn):
        pytest.skip("실 DB(ops-vm)에 연결할 수 없음")

    await init_pg(settings.pg_dsn)
    try:
        version = await get_article("국세기본법", 2, 0, date.today())
        assert version is not None
        assert version.valid_from <= date.today()
        assert version.valid_to is None or version.valid_to > date.today()

        resolved = await resolve_citation("국세기본법 제2조")
        assert resolved is not None
        assert resolved.article_id == version.article_id

        law_versions = await get_effective_law("국세기본법", date.today())
        assert len(law_versions) > 100  # 국세기본법 조문 수 규모
    finally:
        await close_pg()
