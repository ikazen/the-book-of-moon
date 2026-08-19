from __future__ import annotations

from lawcorpus.ingest.case_mapper import _ref_article_to_chunk_id


def test_ref_article_to_chunk_id_plain():
    assert _ref_article_to_chunk_id("소득세법 제14조") == "art_소득세법_14"


def test_ref_article_to_chunk_id_with_clause():
    assert _ref_article_to_chunk_id("법인세법 제52조 제1항") == "art_법인세법_52_1"


def test_ref_article_to_chunk_id_no_space_clause():
    assert _ref_article_to_chunk_id("법인세법 제52조제1항") == "art_법인세법_52_1"


def test_ref_article_to_chunk_id_branch():
    """가지번호 참조조문("제18조의3")도 law_mapper와 동일한 chunk_id를 만들어야 한다."""
    assert _ref_article_to_chunk_id("법인세법 제18조의3") == "art_법인세법_18의3"


def test_ref_article_to_chunk_id_branch_with_clause():
    assert _ref_article_to_chunk_id("법인세법 제18조의3 제1항") == "art_법인세법_18의3_1"
