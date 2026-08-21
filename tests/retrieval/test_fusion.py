from __future__ import annotations

import dataclasses

import pytest

from lawcorpus.retrieval.fusion import rrf_fuse
from lawcorpus.types import Hit


def _hit(article_key, score=0.5):
    return Hit(article_key=article_key, article_id=article_key, chunk_path="제1항",
               text=f"text-{article_key}", score=score)


def test_rrf_fuse_basic_two_way_ranking():
    vec = [_hit(1, 0.9), _hit(2, 0.8)]
    kw = [_hit(2, 0.05), _hit(1, 0.03)]

    result = rrf_fuse(vec, kw, k=60, top_n=10)

    keys = [h.article_key for h in result]
    # 1: rank1(vec)+rank2(kw), 2: rank2(vec)+rank1(kw) -> 대칭이라 동점, 원 순서 유지 여부는
    # 안정 정렬에 의존하므로 점수만 검증
    assert set(keys) == {1, 2}
    assert result[0].score == result[1].score


def test_rrf_fuse_returns_rrf_score_not_original():
    """반환 Hit의 score가 원본 검색 점수가 아니라 RRF 점수여야 한다."""
    vec = [_hit(1, 0.9)]
    kw: list[Hit] = []

    result = rrf_fuse(vec, kw, k=60, top_n=10)

    assert result[0].article_key == 1
    # vec rank1: 1/(60+1). kw는 빈 리스트라 miss=len([])+1=1 -> 1/(60+1)도 더해짐.
    assert result[0].score == 1.0 / (60 + 1) + 1.0 / (60 + 1)
    assert result[0].score != 0.9


def test_rrf_fuse_three_way_no_rank_offset_penalty():
    """3-way 융합에서 세 번째 리스트 단독 1위 Hit이 앞선 리스트 길이만큼 페널티를
    받지 않아야 한다 — 구 concat 방식(vec_direct+vec_hyde 이어붙이기)과 직접 대조."""
    vec_direct = [_hit(100 + i) for i in range(5)]
    vec_hyde = [_hit(999)]  # HyDE에서만 발견, 자기 리스트에서는 rank=1
    kw: list[Hit] = []

    three_way = rrf_fuse(vec_direct, vec_hyde, kw, k=60, top_n=10)
    old_style_concat = rrf_fuse(vec_direct + vec_hyde, kw, k=60, top_n=10)  # 구 버그 재현

    three_way_score = next(h.score for h in three_way if h.article_key == 999)
    concat_score = next(h.score for h in old_style_concat if h.article_key == 999)

    # 3-way: vec_hyde 안에서 rank=1. concat: vec_direct(5개) 뒤에 붙어 rank=6으로 밀림.
    assert three_way_score > concat_score


def test_rrf_fuse_dedup_keeps_first_seen_hit():
    from_vec = _hit(1, score=0.9)
    from_kw = _hit(1, score=0.05)

    result = rrf_fuse([from_vec], [from_kw], k=60, top_n=10)

    assert len(result) == 1
    assert result[0].article_key == 1
    assert result[0].text == from_vec.text  # 첫 발견(vec) 기준


def test_rrf_fuse_returns_new_object_not_same_identity():
    """Hit은 frozen이라 인플레이스 mutation 자체가 불가능하다 — dataclasses.replace로
    새 객체를 만들어야 하고, 원본은 절대 변경되지 않는다."""
    original = _hit(1, score=0.9)
    vec = [original]

    result = rrf_fuse(vec, [], k=60, top_n=10)

    assert result[0] is not original
    with pytest.raises(dataclasses.FrozenInstanceError):
        result[0].score = 999.0
    assert original.score == 0.9


def test_rrf_fuse_top_n_limits_result_count():
    vec = [_hit(100 + i, score=1.0 - i * 0.01) for i in range(5)]
    result = rrf_fuse(vec, [], k=60, top_n=2)
    assert len(result) == 2


def test_rrf_fuse_empty_lists_returns_empty():
    assert rrf_fuse([], [], k=60, top_n=10) == []
