"""부인 리스크 조회 — 조문에 걸린 쟁송 이력과 실질과세/부당행위계산부인 적용 빈도,
그리고 아직 경정청구 기한이 남은 개구멍 후보.
"""

from __future__ import annotations

from datetime import date, timedelta

from lawcorpus.db.pg import get_pool
from lawcorpus.types import LoopholeCandidate, Ruling


def _row_to_ruling(row) -> Ruling:
    return Ruling(
        ruling_id=row["ruling_id"],
        source=row["source"],
        case_no=row["case_no"],
        decided_on=row["decided_on"],
        outcome=row["outcome"],
        gist=row["gist"],
        body=row["body"],
        body_available=row["body_available"],
        cited_articles=tuple(row["cited_articles"] or ()),
        cited_article_ids=tuple(row["cited_article_ids"] or ()),
        anti_avoidance=tuple(row["anti_avoidance"] or ()),
        raw_uri=row["raw_uri"],
    )


async def get_rulings_for(article_id: int, outcome: str | None = None) -> list[Ruling]:
    pool = get_pool()
    async with pool.acquire() as conn:
        if outcome is None:
            rows = await conn.fetch(
                "SELECT * FROM ruling WHERE $1 = ANY(cited_article_ids) ORDER BY decided_on DESC", article_id
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM ruling WHERE $1 = ANY(cited_article_ids) AND outcome = $2 ORDER BY decided_on DESC",
                article_id, outcome,
            )
    return [_row_to_ruling(r) for r in rows]


async def anti_avoidance_rate(article_id: int) -> float:
    """이 조문을 인용한 판례 중 실질과세/부당행위계산부인/단계거래가 적용된 비율.
    분모가 0이면(인용 판례 자체가 없으면) 0.0 — "리스크 없음"이 아니라 "판단 재료 없음"이라
    호출부가 별도로 구분해야 하지만, float 하나로는 그 구분을 못 하므로 문서화해둔다."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE anti_avoidance != '{}') AS flagged
            FROM ruling WHERE $1 = ANY(cited_article_ids)
            """,
            article_id,
        )
    if row["total"] == 0:
        return 0.0
    return row["flagged"] / row["total"]


async def find_claimable(taxpayer_facts: dict, lookback_years: int = 5) -> list[LoopholeCandidate]:
    """경정청구(최대 5년) 기한이 아직 남은 개구멍 후보. taxpayer_facts에 article_ids가
    있으면 그 조문으로 좁히고, 없으면 살아있는 후보 전체를 반환한다.

    개별 납세자 사실관계와 후보를 정교하게 매칭하는 로직은 이 저장소의 범위 밖이다(결정 A —
    LLM 판단이 필요한 영역). 여기서는 시한 계산까지만 한다.
    """
    cutoff = date.today() - timedelta(days=365 * lookback_years)
    article_ids = taxpayer_facts.get("article_ids") if taxpayer_facts else None

    pool = get_pool()
    async with pool.acquire() as conn:
        if article_ids:
            rows = await conn.fetch(
                """
                SELECT * FROM loophole_candidate
                WHERE article_id = ANY($1::bigint[])
                  AND status IN ('alive', 'patched')
                  AND (patched_on IS NULL OR patched_on >= $2)
                  AND (claim_deadline IS NULL OR claim_deadline >= CURRENT_DATE)
                """,
                list(article_ids), cutoff,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM loophole_candidate
                WHERE status IN ('alive', 'patched')
                  AND (patched_on IS NULL OR patched_on >= $1)
                  AND (claim_deadline IS NULL OR claim_deadline >= CURRENT_DATE)
                """,
                cutoff,
            )

    return [
        LoopholeCandidate(
            id=r["id"], article_id=r["article_id"], origin_ruling=r["origin_ruling"], status=r["status"],
            patched_by=r["patched_by"], patched_on=r["patched_on"], pattern_type=r["pattern_type"],
            claim_deadline=r["claim_deadline"], risk_score=(float(r["risk_score"]) if r["risk_score"] is not None else None),
            confirmed_by=r["confirmed_by"], note=r["note"],
        )
        for r in rows
    ]
