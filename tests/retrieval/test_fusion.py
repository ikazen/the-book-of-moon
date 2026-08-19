from __future__ import annotations

from lawcorpus.retrieval.fusion import rrf_fuse
from lawcorpus.types import Chunk


def _chunk(chunk_id, score=0.5, table="article"):
    return Chunk(chunk_id=chunk_id, table=table, text=f"text-{chunk_id}", score=score, meta={})


def test_rrf_fuse_basic_two_way_ranking():
    vec = [_chunk("a", 0.9), _chunk("b", 0.8)]
    kw = [_chunk("b", 0.05), _chunk("a", 0.03)]

    result = rrf_fuse(vec, kw, k=60, top_n=10)

    ids = [c.chunk_id for c in result]
    # a: rank1(vec)+rank2(kw), b: rank2(vec)+rank1(kw) -> 대칭이라 동점, 원 순서 유지 여부는
    # 안정 정렬에 의존하므로 점수만 검증
    assert set(ids) == {"a", "b"}
    assert result[0].score == result[1].score


def test_rrf_fuse_returns_rrf_score_not_original():
    """반환 chunk의 score가 원본 검색 점수가 아니라 RRF 점수여야 한다."""
    vec = [_chunk("a", 0.9)]
    kw: list[Chunk] = []

    result = rrf_fuse(vec, kw, k=60, top_n=10)

    assert result[0].chunk_id == "a"
    # vec rank1: 1/(60+1). kw는 빈 리스트라 miss=len([])+1=1 -> 1/(60+1)도 더해짐.
    assert result[0].score == 1.0 / (60 + 1) + 1.0 / (60 + 1)
    assert result[0].score != 0.9


def test_rrf_fuse_three_way_no_rank_offset_penalty():
    """3-way 융합에서 세 번째 리스트 단독 1위 chunk가 앞선 리스트 길이만큼 페널티를
    받지 않아야 한다 — 구 concat 방식(vec_direct+vec_hyde 이어붙이기)과 직접 대조."""
    vec_direct = [_chunk(f"d{i}") for i in range(5)]
    vec_hyde = [_chunk("only_in_hyde")]  # HyDE에서만 발견, 자기 리스트에서는 rank=1
    kw: list[Chunk] = []

    three_way = rrf_fuse(vec_direct, vec_hyde, kw, k=60, top_n=10)
    old_style_concat = rrf_fuse(vec_direct + vec_hyde, kw, k=60, top_n=10)  # 구 버그 재현

    three_way_score = next(c.score for c in three_way if c.chunk_id == "only_in_hyde")
    concat_score = next(c.score for c in old_style_concat if c.chunk_id == "only_in_hyde")

    # 3-way: vec_hyde 안에서 rank=1. concat: vec_direct(5개) 뒤에 붙어 rank=6으로 밀림.
    assert three_way_score > concat_score


def test_rrf_fuse_dedup_keeps_first_seen_chunk():
    a_from_vec = _chunk("a", score=0.9)
    a_from_kw = _chunk("a", score=0.05)

    result = rrf_fuse([a_from_vec], [a_from_kw], k=60, top_n=10)

    assert len(result) == 1
    assert result[0].chunk_id == "a"
    assert result[0].text == a_from_vec.text  # 첫 발견(vec) chunk 기준


def test_rrf_fuse_returns_new_object_not_same_identity():
    """dataclasses.replace로 새 객체를 만들어 리랭커의 인플레이스 mutation이 원본
    리스트(vec_results/kw_results)로 새지 않아야 한다."""
    original = _chunk("a", score=0.9)
    vec = [original]

    result = rrf_fuse(vec, [], k=60, top_n=10)

    assert result[0] is not original
    result[0].score = 999.0  # 리랭커가 하는 인플레이스 mutation 시뮬레이션
    assert original.score == 0.9  # 원본은 영향 없음


def test_rrf_fuse_top_n_limits_result_count():
    vec = [_chunk(f"v{i}", score=1.0 - i * 0.01) for i in range(5)]
    result = rrf_fuse(vec, [], k=60, top_n=2)
    assert len(result) == 2


def test_rrf_fuse_empty_lists_returns_empty():
    assert rrf_fuse([], [], k=60, top_n=10) == []
