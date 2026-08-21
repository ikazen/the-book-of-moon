from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from lawcorpus.ingest.law_api import parse_eflaw_xml, parse_lsstmd_xml

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "law_api"


def _parse(name: str) -> ET.Element:
    return ET.parse(_FIXTURES / name).getroot()


def test_parse_eflaw_xml_basic_fields():
    law = parse_eflaw_xml(_parse("eflaw_detail.xml"))

    assert law.law_id == "001586"
    assert law.law_name == "국세기본법"
    assert law.law_type == "법률"
    assert law.ministry_code == "1053000"
    assert law.promulgated_on == "20260811"
    assert law.enforced_on == "20260811"


def test_parse_eflaw_xml_includes_revision_reason_from_moleg():
    """기재부 PDF 없이도 법제처가 제개정이유를 이미 제공한다(the-book-of-moon #23)."""
    law = parse_eflaw_xml(_parse("eflaw_detail.xml"))

    assert "개정이유 및 주요내용" in law.revision_reason


def test_parse_eflaw_xml_separates_headings_from_real_articles():
    law = parse_eflaw_xml(_parse("eflaw_detail.xml"))

    headings = [a for a in law.articles if a.is_heading]
    real = [a for a in law.articles if not a.is_heading]
    assert len(headings) > 0
    assert len(real) > 0
    assert any(a.title for a in real)  # 삭제된 조문 등은 제목이 없을 수 있다


def test_parse_eflaw_xml_branch_article_no():
    law = parse_eflaw_xml(_parse("eflaw_detail.xml"))

    branch_articles = [a for a in law.articles if a.branch_no > 0]
    assert branch_articles, "가지번호 조문이 없으면 실측 fixture가 바뀐 것"


def test_parse_eflaw_xml_clause_hierarchy_ho_mok():
    law = parse_eflaw_xml(_parse("eflaw_detail.xml"))

    article_2 = next(a for a in law.articles if a.art_no == 2 and not a.is_heading)
    assert len(article_2.clauses) == 1  # 항번호 없는 단일 문단
    sub_clauses = article_2.clauses[0].sub_clauses
    assert len(sub_clauses) >= 6
    first_ho_items = sub_clauses[0].items
    assert [i.no for i in first_ho_items][:3] == ["가", "나", "다"]


def test_parse_eflaw_xml_clause_no_normalized_from_circled_numbers():
    law = parse_eflaw_xml(_parse("eflaw_detail.xml"))

    article_3 = next(a for a in law.articles if a.art_no == 3 and not a.is_heading)
    assert [c.no for c in article_3.clauses] == ["1", "2"]


def test_parse_eflaw_xml_addenda_multiline_cdata_concatenated():
    law = parse_eflaw_xml(_parse("eflaw_detail.xml"))

    assert len(law.addenda) > 0
    first = law.addenda[0]
    assert first.promulgated_at
    assert "시행일" in first.body


def test_parse_lsstmd_xml_returns_law_decree_rule_chain():
    hierarchy = parse_lsstmd_xml(_parse("lsstmd_detail.xml"))

    types = [e.law_type for e in hierarchy.entries]
    assert types == ["법률", "대통령령", "재정경제부령"]
    names = [e.law_name for e in hierarchy.entries]
    assert names == ["국세기본법", "국세기본법 시행령", "국세기본법 시행규칙"]
