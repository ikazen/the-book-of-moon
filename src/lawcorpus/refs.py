from __future__ import annotations

import re

from lawcorpus.db.pg import get_pool

# 조문 번호: "XXX법(시행령/시행규칙 포함) 제N조" 또는 가지번호 포함 "...제N조의M" 형식
# (pot-of-greed #40, the-book-of-moon #12)
_RE_ARTICLE = re.compile(
    r"(?P<law>[\w가-힣]+(?:법|법률))(?:\s*(?P<sub>시행령|시행규칙))?"
    r"\s*(?P<article>제\d+조(?:의\d+)?)(?:\s*제\d+항)?"
)
# 실무에서 흔한 법령 약칭 → article_chunks.law_name 저장형 정규화
_LAW_ABBREV = {
    "조특법": "조세특례제한법",
    "국기법": "국세기본법",
}
# 판례 번호: 연도+사건부호(화이트리스트)+번호 (예: 2018두12345, 2021도1234)
# 사건부호로 한정하지 않으면 "2018년6월15일" 같은 날짜 표현의 "2018년6"이
# 오탐된다(pot-of-greed #6).
_RE_CASE = re.compile(
    r"\d{2,4}(?:두|도|다|누|나|가합|가단|고합|고단|구합|구단|재두|후|허|헌[가-마])\d+"
)


def extract_refs(text: str) -> list[str]:
    matches = list(_RE_ARTICLE.finditer(text)) + list(_RE_CASE.finditer(text))
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        r = m.group(0).strip()
        if r not in seen:
            seen.add(r)
            result.append(r)
    return result


def parse_ref(ref: str) -> tuple[str, tuple[str, ...]] | None:
    """ref 문자열 → 구조적 동등 매칭용 (kind, params).

    ("article", (law_name, article_no)) | ("case", (case_no,)) | None(파싱 불가).
    추출(extract_refs)과 같은 정규식을 써서 divergence를 방지한다.
    항(제N항)은 소비만 하고 존재 판정은 조 단위로 한다.
    """
    ref = ref.strip()
    m = _RE_ARTICLE.match(ref)
    if m:
        law = _LAW_ABBREV.get(m.group("law"), m.group("law"))
        if m.group("sub"):
            law = f"{law} {m.group('sub')}"
        return "article", (law, m.group("article"))
    if _RE_CASE.fullmatch(ref):
        return "case", (ref,)
    return None


async def verify_refs_exist(refs: list[str]) -> dict[str, bool]:
    """조문/판례 번호 목록을 구조적 동등 매칭으로 코퍼스 존재 확인.

    LLM·의미검색·tsvector 랭킹 없음 — law_name+article_no 또는 case_no의
    정확한 컬럼 동등성만 본다. FTS 토큰 AND 매칭은 "법명은 틀리고 번호만
    실재하는" 오귀속 인용을 통과시키므로 사용하지 않는다.
    반환: {ref: 존재여부}. 구조 파싱 불가 ref는 보수적으로 False.
    """
    if not refs:
        return {}

    pool = get_pool()
    out: dict[str, bool] = {}
    async with pool.acquire() as conn:
        for ref in refs:
            parsed = parse_ref(ref)
            if parsed is None:
                out[ref] = False
                continue
            kind, params = parsed
            if kind == "article":
                row = await conn.fetchval(
                    "SELECT 1 FROM article_chunks WHERE law_name = $1 AND article_no = $2 LIMIT 1",
                    *params,
                )
            else:
                row = await conn.fetchval(
                    "SELECT 1 FROM case_chunks WHERE case_no = $1 LIMIT 1",
                    *params,
                )
            out[ref] = row is not None
    return out
