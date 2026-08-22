from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from lawcorpus.ingest.law_api import (
    _parse_admrul_detail,
    _parse_detc_detail,
    _parse_expc_detail,
    _parse_prec_detail,
)
from lawcorpus.ingest.models import RawRuling
from lawcorpus.ingest.ruling_mapper import map_ruling

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "law_api"


def _root(name: str) -> ET.Element:
    return ET.parse(_FIXTURES / name).getroot()


def test_map_ruling_prec_basic_fields():
    raw = _parse_prec_detail(_root("prec_detail.xml"))

    mapped = map_ruling(raw)

    assert mapped is not None
    assert mapped.source == "대법원"
    assert mapped.decided_on == date(2026, 5, 20)
    assert mapped.body_available is True


def test_map_ruling_expc_has_no_outcome():
    """법령해석례는 승패 개념이 없다 — 항상 None이어야 한다."""
    raw = _parse_expc_detail(_root("expc_detail.xml"))

    mapped = map_ruling(raw)

    assert mapped is not None
    assert mapped.source == "법제처"
    assert mapped.outcome is None


def test_map_ruling_detc_classified_as_hapheon():
    raw = _parse_detc_detail(_root("detc_detail.xml"))

    mapped = map_ruling(raw)

    assert mapped is not None
    assert mapped.outcome == "합헌"


def test_map_ruling_admrul_no_outcome_no_case_no():
    raw = _parse_admrul_detail(_root("admrul_detail.xml"))

    mapped = map_ruling(raw)

    assert mapped is not None
    assert mapped.source == "행정규칙"
    assert mapped.outcome is None
    assert mapped.case_no is None


def test_map_ruling_returns_none_when_detail_fetch_failed():
    """decided_at이 빈 응답(예: "일치하는 판례가 없습니다")은 매핑 실패로 처리한다."""
    raw = RawRuling(ruling_id="x", source="법원", case_no="", decided_at="", title="", gist="", body="")

    assert map_ruling(raw) is None


def test_classify_detc_outcome_wiheon():
    raw = RawRuling(
        ruling_id="x", source="헌법재판소", case_no="2020헌가1", decided_at="20200101",
        title="", gist="", body="[주 문]\n이 사건 법률조항은 헌법에 위반된다.\n[이 유]\n...",
    )
    mapped = map_ruling(raw)
    assert mapped.outcome == "위헌"


def test_classify_detc_outcome_hunbeop_bulhapchi():
    raw = RawRuling(
        ruling_id="x", source="헌법재판소", case_no="2020헌가1", decided_at="20200101",
        title="", gist="", body="[주 문]\n이 사건 법률조항은 헌법불합치 결정을 선고한다.\n[이 유]\n...",
    )
    mapped = map_ruling(raw)
    assert mapped.outcome == "헌법불합치"


def test_classify_prec_outcome_taxpayer_win():
    raw = RawRuling(
        ruling_id="x", source="대법원", case_no="2020두1", decided_at="20200101",
        title="", gist="원고의 청구를 인용한다.", body="",
    )
    mapped = map_ruling(raw)
    assert mapped.outcome == "납세자승"


def test_classify_prec_outcome_taxpayer_lose():
    raw = RawRuling(
        ruling_id="x", source="대법원", case_no="2020두1", decided_at="20200101",
        title="", gist="원고의 청구를 기각한다.", body="",
    )
    mapped = map_ruling(raw)
    assert mapped.outcome == "납세자패"


def test_extract_anti_avoidance_keywords():
    raw = RawRuling(
        ruling_id="x", source="대법원", case_no="2020두1", decided_at="20200101",
        title="", gist="", body="이 거래는 실질과세 원칙에 따라 부당행위계산부인 대상이다.",
    )
    mapped = map_ruling(raw)
    assert set(mapped.anti_avoidance) == {"실질과세", "부당행위계산부인"}


def test_map_ruling_body_available_false_when_body_empty():
    raw = RawRuling(
        ruling_id="x", source="법원", case_no="", decided_at="20200101", title="", gist="", body="",
    )
    mapped = map_ruling(raw)
    assert mapped.body_available is False
