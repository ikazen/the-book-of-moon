from __future__ import annotations

from dataclasses import replace

from lawcorpus.types import Chunk


def rrf_fuse(
    *ranked_lists: list[Chunk],
    k: int = 60,
    top_n: int = 30,
) -> list[Chunk]:
    """Reciprocal Rank Fusion of N ranked lists.

    Score(d) = sum_over_lists( 1 / (k + rank(d)) )
    chunk_id로 dedup, 어떤 리스트에 없으면 그 리스트 순위 = len+1.

    반환 chunk의 score는 원본 검색 점수(코사인/ts_rank 등)가 아니라 RRF 점수로
    교체된다(pot-of-greed #9) — 이종 스케일 점수가 호출부에서 그대로 비교되던 문제와,
    리랭커의 인플레이스 `chunk.score = ...` mutation이 원본 vec/kw 결과 리스트로 새던
    문제를 dataclasses.replace(새 객체 생성)로 함께 해결한다.
    """
    rank_maps = [{c.chunk_id: i + 1 for i, c in enumerate(lst)} for lst in ranked_lists]
    misses = [len(lst) + 1 for lst in ranked_lists]

    all_chunks: dict[str, Chunk] = {}
    for lst in ranked_lists:
        for c in lst:
            all_chunks.setdefault(c.chunk_id, c)

    scored: list[tuple[float, Chunk]] = []
    for chunk_id, chunk in all_chunks.items():
        rrf_score = sum(
            1.0 / (k + rank_map.get(chunk_id, miss))
            for rank_map, miss in zip(rank_maps, misses)
        )
        scored.append((rrf_score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [replace(chunk, score=rrf_score) for rrf_score, chunk in scored[:top_n]]
