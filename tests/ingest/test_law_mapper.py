from __future__ import annotations

from lawcorpus.ingest.law_mapper import map_law
from lawcorpus.ingest.models import RawArticle, RawLaw


def test_map_law_plain_article_no():
    raw = RawLaw(
        law_name="소득세법",
        law_id="1",
        mst="1",
        effective_from="20200101",
        articles=[RawArticle(no="14", title="", text="본문", effective_from="20200101")],
    )
    row = map_law(raw).pg_rows[0]
    assert row.article_no == "제14조"
    assert row.chunk_id == "art_소득세법_14"


def test_map_law_branch_article_no():
    """가지번호 조문은 "제N조의M" 순서로 저장되어야 한다 ("제N의M조"는 오표기)."""
    raw = RawLaw(
        law_name="법인세법",
        law_id="1",
        mst="1",
        effective_from="20200101",
        articles=[RawArticle(no="18의3", title="", text="본문", effective_from="20200101")],
    )
    row = map_law(raw).pg_rows[0]
    assert row.article_no == "제18조의3"
    assert row.chunk_id == "art_법인세법_18의3"
