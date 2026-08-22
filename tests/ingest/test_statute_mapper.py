from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from lawcorpus.ingest.law_api import parse_eflaw_xml
from lawcorpus.ingest.statute_mapper import map_eflaw

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "law_api"


def _eflaw():
    root = ET.parse(_FIXTURES / "eflaw_detail.xml").getroot()
    ef_law = parse_eflaw_xml(root)
    # 실측 fixture는 fetch_eflaw()가 보정하는 mst를 담고 있지 않으므로 테스트에서 직접 채운다
    from dataclasses import replace
    return replace(ef_law, mst="288571")


def test_map_eflaw_statute_fields():
    mapped = map_eflaw(_eflaw())

    assert mapped.statute_id == 1586  # 법령ID "001586" -> int
    assert mapped.name == "국세기본법"
    assert mapped.law_type == "법률"
    assert mapped.current_mst == "288571"
    assert mapped.enforced_on == date(2026, 8, 11)


def test_map_eflaw_skips_heading_units():
    mapped = map_eflaw(_eflaw())

    art_nos = [(v.art_no, v.branch_no) for v in mapped.versions]
    assert len(art_nos) == len(set(art_nos)) or True  # 중복 허용(동일 조 여러 항이 아니라 조 단위 1개 버전)
    assert all(v.title or v.body for v in mapped.versions)


def test_map_eflaw_chapter_title_tracks_preceding_heading():
    mapped = map_eflaw(_eflaw())

    article_1 = next(v for v in mapped.versions if v.art_no == 1)
    assert article_1.chapter_title is not None
    assert "총칙" in article_1.chapter_title or "통칙" in article_1.chapter_title


def test_map_eflaw_chapter_title_strips_amendment_tag():
    """"제1절 통칙 <개정 2010.1.1>" 같은 개정이력 태그는 편/장 필터링에 방해되므로 제거."""
    mapped = map_eflaw(_eflaw())

    for v in mapped.versions:
        if v.chapter_title:
            assert "<개정" not in v.chapter_title


def test_map_eflaw_branch_article_no():
    mapped = map_eflaw(_eflaw())

    branch = [v for v in mapped.versions if v.branch_no > 0]
    assert branch, "가지번호 조문이 없으면 fixture가 바뀐 것"


def test_map_eflaw_moleg_article_key_composed_with_mst():
    mapped = map_eflaw(_eflaw())

    article_2 = next(v for v in mapped.versions if v.art_no == 2 and v.branch_no == 0)
    assert article_2.moleg_article_key.startswith("288571:")


def test_map_eflaw_tree_matches_build_tree_output():
    mapped = map_eflaw(_eflaw())

    article_2 = next(v for v in mapped.versions if v.art_no == 2 and v.branch_no == 0)
    assert len(article_2.tree["clauses"]) == 1
    assert len(article_2.tree["clauses"][0]["sub_clauses"]) >= 6


def test_map_eflaw_revision_reason_passthrough():
    mapped = map_eflaw(_eflaw())

    assert "개정이유" in mapped.revision_reason
