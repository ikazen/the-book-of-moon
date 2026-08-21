from __future__ import annotations

from dataclasses import replace

from lawcorpus.types import Hit


def rrf_fuse(
    *ranked_lists: list[Hit],
    k: int = 60,
    top_n: int = 30,
) -> list[Hit]:
    """Reciprocal Rank Fusion of N ranked lists.

    Score(d) = sum_over_lists( 1 / (k + rank(d)) )
    article_key로 dedup, 어떤 리스트에 없으면 그 리스트 순위 = len+1.

    반환 Hit의 score는 원본 검색 점수(코사인/trgm 등)가 아니라 RRF 점수로 교체된다
    (pot-of-greed #9) — 이종 스케일 점수가 호출부에서 그대로 비교되던 문제를
    dataclasses.replace(새 객체 생성)로 해결한다. Hit이 frozen이라 재순위 단계(reranker)도
    같은 방식으로 새 객체를 만들어야 한다 — 인플레이스 mutation은 애초에 불가능하다.
    """
    rank_maps = [{h.article_key: i + 1 for i, h in enumerate(lst)} for lst in ranked_lists]
    misses = [len(lst) + 1 for lst in ranked_lists]

    all_hits: dict[int, Hit] = {}
    for lst in ranked_lists:
        for h in lst:
            all_hits.setdefault(h.article_key, h)

    scored: list[tuple[float, Hit]] = []
    for article_key, hit in all_hits.items():
        rrf_score = sum(
            1.0 / (k + rank_map.get(article_key, miss))
            for rank_map, miss in zip(rank_maps, misses)
        )
        scored.append((rrf_score, hit))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [replace(hit, score=rrf_score) for rrf_score, hit in scored[:top_n]]
