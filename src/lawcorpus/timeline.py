"""시계열 조회 — 한 조문의 버전 이력, 두 버전 사이 diff, 누적 임계값.
retrieval/context_expand.py(v0.x, 삭제됨)를 대체한다 — 시점 필터가 조회 시점(as_of)으로
넘어갔으니 "과거 버전 확장"은 더 이상 별도 함수가 아니라 get_article_timeline이 전부 준다.
"""

from __future__ import annotations

import json

from lawcorpus.db.pg import get_pool
from lawcorpus.resolution import row_to_article_version
from lawcorpus.types import ArticleDiff, ArticleVersion, Threshold


async def get_article_timeline(article_id: int) -> list[ArticleVersion]:
    """한 조문의 전체 버전 이력을 valid_from 순으로 반환한다. 전부개정으로 조문번호가
    바뀐 경우는 article_rewrite_map을 타고 넘어가지 않는다 — 그건 호출부가 명시적으로
    article_rewrite_map을 참조해서 이어붙일 몫이다(자동으로 이어붙이면 "같은 조문"이라는
    암묵적 가정이 생겨 위험하다)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM article_version WHERE article_id = $1 ORDER BY valid_from", article_id
        )
    return [row_to_article_version(r) for r in rows]


def _row_to_diff(row) -> ArticleDiff:
    diff = row["diff"]
    thresholds_raw = row["added_thresholds"]
    return ArticleDiff(
        from_version=row["from_version"],
        to_version=row["to_version"],
        diff=json.loads(diff) if isinstance(diff, str) else diff,
        added_thresholds=tuple(
            Threshold(**t) for t in (json.loads(thresholds_raw) if isinstance(thresholds_raw, str) else thresholds_raw)
        ),
        reason_text=row["reason_text"],
        reason_source=row["reason_source"],
    )


async def diff_articles(v_from: int, v_to: int) -> ArticleDiff:
    """두 article_key 사이의 diff. build-diffs(#28)가 이미 계산해뒀으면 그 행을 그대로 쓰고,
    없으면(예: 인접하지 않은 두 버전을 직접 비교하고 싶은 경우) 즉석에서 계산한다."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM article_diff WHERE from_version = $1 AND to_version = $2", v_from, v_to
        )
        if row is not None:
            return _row_to_diff(row)

        versions = await conn.fetch(
            "SELECT article_key, tree, revision_reason FROM article_version WHERE article_key = ANY($1)",
            [v_from, v_to],
        )
    by_key = {r["article_key"]: r for r in versions}
    if v_from not in by_key or v_to not in by_key:
        raise ValueError(f"article_key {v_from} 또는 {v_to}를 찾을 수 없습니다")

    from lawcorpus.ingest.diff import added_thresholds, diff_trees

    def _tree(raw) -> dict:
        return json.loads(raw) if isinstance(raw, str) else raw

    diff = diff_trees(_tree(by_key[v_from]["tree"]), _tree(by_key[v_to]["tree"]))
    thresholds = tuple(added_thresholds(diff))
    return ArticleDiff(
        from_version=v_from, to_version=v_to, diff=diff, added_thresholds=thresholds,
        reason_text=by_key[v_to]["revision_reason"], reason_source="법제처" if by_key[v_to]["revision_reason"] else None,
    )


async def find_thresholds(article_id: int) -> list[Threshold]:
    """이 조문의 개정 역사 전체에서 신설된 임계값을 누적해 반환한다 — article_diff에
    이미 계산돼 저장된 added_thresholds를 그대로 모은다(설계문서: "이 DB의 가장 독자적인 자산")."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ad.added_thresholds FROM article_diff ad
            JOIN article_version av ON av.article_key = ad.to_version
            WHERE av.article_id = $1
            ORDER BY av.valid_from
            """,
            article_id,
        )

    thresholds: list[Threshold] = []
    for row in rows:
        raw = row["added_thresholds"]
        items = json.loads(raw) if isinstance(raw, str) else raw
        thresholds.extend(Threshold(**t) for t in items)
    return thresholds
