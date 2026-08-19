from __future__ import annotations

from lawcorpus.db.neo4j import get_driver
from lawcorpus.types import GraphChunk


async def expand_1hop(chunk_ids: list[str]) -> list[GraphChunk]:
    """단순 모드: 직접 인용(CITES) + 근거조문(BASED_ON) 1홉 확장.

    입력 chunk_id 목록으로 Neo4j를 탐색하여 직접 연결된 이웃 노드를 반환한다.
    입력 chunk_id 자체는 포함하지 않는다.
    """
    if not chunk_ids:
        return []

    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            UNWIND $ids AS cid
            MATCH (src {chunk_id: cid})
                  WHERE src:CorpusArticle OR src:CorpusCase
            OPTIONAL MATCH (src)-[:CITES|BASED_ON]->(neighbor)
                  WHERE neighbor:CorpusArticle OR neighbor:CorpusCase
            RETURN
                neighbor.chunk_id AS chunk_id,
                labels(neighbor)[0] AS label,
                neighbor.validity_flag AS validity_flag,
                neighbor.law_name AS law_name,
                neighbor.article_no AS article_no,
                neighbor.case_no AS case_no,
                neighbor.court AS court,
                neighbor.effective_from AS effective_from,
                neighbor.effective_to AS effective_to
            """,
            ids=chunk_ids,
        )
        records = await result.data()

    seen: set[str] = set(chunk_ids)
    chunks: list[GraphChunk] = []
    for row in records:
        cid = row.get("chunk_id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        label = row.get("label", "")
        node_type = "article" if "Article" in label else "case"
        chunks.append(GraphChunk(
            chunk_id=cid,
            node_type=node_type,
            validity_flag=row.get("validity_flag"),
            meta={k: v for k, v in row.items() if k not in ("chunk_id", "label", "validity_flag") and v},
        ))
    return chunks


async def expand_2hop(chunk_ids: list[str]) -> list[GraphChunk]:
    """복잡 모드 seam: REFERS_TO, OVERRULED_BY, AMENDED_BY까지 2홉 확장."""
    if not chunk_ids:
        return []

    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            UNWIND $ids AS cid
            MATCH (src {chunk_id: cid})
                  WHERE src:CorpusArticle OR src:CorpusCase
            OPTIONAL MATCH (src)-[:CITES|BASED_ON|REFERS_TO|OVERRULED_BY]->(n1)
                  WHERE n1:CorpusArticle OR n1:CorpusCase
            OPTIONAL MATCH (n1)-[:CITES|BASED_ON|REFERS_TO|AMENDED_BY]->(n2)
                  WHERE n2:CorpusArticle OR n2:CorpusCase OR n2:CorpusAmendment
            WITH collect(n1) + collect(n2) AS neighbors
            UNWIND neighbors AS neighbor
            WITH DISTINCT neighbor
            WHERE neighbor IS NOT NULL
            RETURN
                neighbor.chunk_id AS chunk_id,
                neighbor.amendment_id AS amendment_id,
                labels(neighbor)[0] AS label,
                neighbor.validity_flag AS validity_flag,
                neighbor.law_name AS law_name,
                neighbor.article_no AS article_no,
                neighbor.case_no AS case_no,
                neighbor.effective_from AS effective_from,
                neighbor.effective_to AS effective_to
            """,
            ids=chunk_ids,
        )
        records = await result.data()

    seen: set[str] = set(chunk_ids)
    chunks: list[GraphChunk] = []
    for row in records:
        cid = row.get("chunk_id") or row.get("amendment_id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        label = row.get("label", "")
        if "Article" in label:
            node_type = "article"
        elif "Case" in label:
            node_type = "case"
        else:
            node_type = "amendment"
        chunks.append(GraphChunk(
            chunk_id=cid,
            node_type=node_type,
            validity_flag=row.get("validity_flag"),
            meta={k: v for k, v in row.items() if k not in ("chunk_id", "amendment_id", "label", "validity_flag") and v},
        ))
    return chunks


def filter_by_transaction_date(
    chunks: list[GraphChunk],
    transaction_date: str,
) -> list[GraphChunk]:
    """2층 시점 정합: 거래시점 기준으로 조문 유효범위 필터.

    transaction_date: ISO 날짜 문자열 (예: "2018-06-01").
    effective_from/to 메타가 없으면 통과.
    """
    result: list[GraphChunk] = []
    for chunk in chunks:
        if chunk.node_type != "article":
            result.append(chunk)
            continue
        eff_from = chunk.meta.get("effective_from")
        eff_to = chunk.meta.get("effective_to")
        if eff_from and transaction_date < eff_from:
            continue
        if eff_to and transaction_date > eff_to:
            continue
        result.append(chunk)
    return result
