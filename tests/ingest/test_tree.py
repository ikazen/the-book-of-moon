from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from lawcorpus.ingest.law_api import parse_eflaw_xml
from lawcorpus.ingest.models import RawArticleUnit, RawEfClause, RawEfSubClause, RawItem
from lawcorpus.ingest.tree import build_tree, iter_chunks

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "law_api"


def _eflaw():
    root = ET.parse(_FIXTURES / "eflaw_detail.xml").getroot()
    return parse_eflaw_xml(root)


def test_build_tree_article_without_clause_no():
    """제2조는 항번호 없는 단일 문단 + 호/목 계층(실측 fixture 기준)."""
    law = _eflaw()
    article_2 = next(a for a in law.articles if a.art_no == 2 and not a.is_heading)

    tree = build_tree(article_2)

    assert len(tree["clauses"]) == 1
    clause = tree["clauses"][0]
    assert clause["no"] == ""
    assert len(clause["sub_clauses"]) >= 6
    assert clause["sub_clauses"][0]["items"][0]["no"] == "가"


def test_build_tree_article_with_numbered_clauses():
    law = _eflaw()
    article_3 = next(a for a in law.articles if a.art_no == 3 and not a.is_heading)

    tree = build_tree(article_3)

    assert [c["no"] for c in tree["clauses"]] == ["1", "2"]


def test_build_tree_article_without_any_clause():
    unit = RawArticleUnit(
        jomun_key="x", art_no=1, branch_no=0, is_heading=False, title="목적",
        body="이 법은 ...", effective_from="20260101", revision_type="제정",
        changed=False, moved_from="", moved_to="", clauses=(),
    )

    tree = build_tree(unit)

    assert tree["clauses"] == []


def test_iter_chunks_unnumbered_clause_still_yielded():
    """항번호가 없어도 본문 전체가 청크로 남아야 한다 — 통째로 드롭되면 검색에서 사라진다."""
    unit = RawArticleUnit(
        jomun_key="x", art_no=2, branch_no=0, is_heading=False, title="정의",
        body="...", effective_from="20260101", revision_type="일부개정",
        changed=False, moved_from="", moved_to="",
        clauses=(
            RawEfClause(no="", text="용어의 뜻은 다음과 같다.", sub_clauses=(
                RawEfSubClause(no="1", text="국세란...", items=(
                    RawItem(no="가", text="소득세"),
                )),
            )),
        ),
    )

    chunks = list(iter_chunks(build_tree(unit)))

    assert len(chunks) == 1
    path, text = chunks[0]
    assert path == ""
    assert "소득세" in text


def test_iter_chunks_numbered_clauses_get_article_prefixed_path():
    unit = RawArticleUnit(
        jomun_key="x", art_no=3, branch_no=0, is_heading=False, title="관계",
        body="...", effective_from="20260101", revision_type="일부개정",
        changed=False, moved_from="", moved_to="",
        clauses=(
            RawEfClause(no="1", text="첫째 조항"),
            RawEfClause(no="2", text="둘째 조항"),
        ),
    )

    chunks = list(iter_chunks(build_tree(unit)))

    assert [c[0] for c in chunks] == ["제1항", "제2항"]
    assert chunks[0][1] == "첫째 조항"
