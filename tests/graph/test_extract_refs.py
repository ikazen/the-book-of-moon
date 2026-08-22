from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from lawcorpus.graph.extract_refs import extract_defines, extract_delegation_edges

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "law_api"


def _lsdelegated_root() -> ET.Element:
    return ET.parse(_FIXTURES / "lsdelegated_detail.xml").getroot()


# --- extract_delegation_edges ---

def test_extract_delegation_edges_splits_by_kind():
    edges = extract_delegation_edges(_lsdelegated_root())

    kinds = {e.edge_type for e in edges}
    assert kinds == {"DELEGATES", "REFERS_TO", "MUTATIS"}


def test_extract_delegation_edges_decree_delegation():
    edges = extract_delegation_edges(_lsdelegated_root())

    decree_edges = [e for e in edges if e.edge_type == "DELEGATES" and e.target_law_title == "국세기본법 시행령"]
    assert decree_edges
    e = decree_edges[0]
    assert e.source_art_no == 2
    assert e.target_art_no == 1
    assert e.target_branch_no == 2


def test_extract_delegation_edges_mutatis_from_source_article_title():
    """제25조의2(연대납세의무에 관한 「민법」의 준용) 밑의 인용법령은 MUTATIS로 분류돼야 한다.
    (국세기본법에는 제80조의2 등 다른 준용 조문도 있어 이 조문만 있는 게 아니다.)"""
    edges = extract_delegation_edges(_lsdelegated_root())

    mutatis = [e for e in edges if e.edge_type == "MUTATIS"]
    assert mutatis
    from_25_2 = [e for e in mutatis if e.source_art_no == 25 and e.source_branch_no == 2]
    assert from_25_2
    assert all(e.target_law_title == "민법" for e in from_25_2)


def test_extract_delegation_edges_refers_to_excludes_mutatis_source():
    """준용 조문(제25조의2) 아래 엣지는 REFERS_TO에 섞이면 안 된다."""
    edges = extract_delegation_edges(_lsdelegated_root())

    refers_to_from_mutatis_source = [
        e for e in edges if e.edge_type == "REFERS_TO" and e.source_art_no == 25 and e.source_branch_no == 2
    ]
    assert refers_to_from_mutatis_source == []


def test_extract_delegation_edges_skips_admrul_delegation():
    """위임행정규칙(훈령/고시)은 article 그래프 대상이 아니라 스킵돼야 한다."""
    edges = extract_delegation_edges(_lsdelegated_root())

    assert all(e.target_law_title != "홈택스 이용에 관한 규정" for e in edges)


def test_extract_delegation_edges_johang_preserved():
    edges = extract_delegation_edges(_lsdelegated_root())

    assert any(e.source_johang == "제2조제20호가목" for e in edges)


# --- extract_defines ---

def test_extract_defines_ran_pattern():
    text = '1. "국세"(國稅)란 국가가 부과하는 조세 중 다음 각 목의 것을 말한다.'
    assert extract_defines(text) == ["국세"]


def test_extract_defines_iha_pattern():
    text = '그 밖의 단체(이하 "법인 아닌 단체"라 한다)는 이 법을 적용할 때 법인으로 본다.'
    assert extract_defines(text) == ["법인 아닌 단체"]


def test_extract_defines_multiple_terms_dedup_and_order():
    text = '"국세"란 ... "세법"이란 ... "국세"란 이미 정의된 용어를 다시 언급'
    assert extract_defines(text) == ["국세", "세법"]


def test_extract_defines_no_match_returns_empty():
    assert extract_defines("보유기간 2년 이상이 필요하다.") == []


def test_extract_defines_against_real_article_body():
    """실측 eflaw 제2조(정의) 본문 전체에서 여러 용어가 뽑혀야 한다."""
    from lawcorpus.ingest.law_api import parse_eflaw_xml

    law = parse_eflaw_xml(ET.parse(_FIXTURES / "eflaw_detail.xml").getroot())
    article_2 = next(a for a in law.articles if a.art_no == 2 and not a.is_heading)

    terms = extract_defines(article_2.body)
    for clause in article_2.clauses:
        terms.extend(extract_defines(clause.text))
        for sub in clause.sub_clauses:
            terms.extend(extract_defines(sub.text))

    assert "국세" in terms
    assert "세법" in terms
