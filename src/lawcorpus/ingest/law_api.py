"""
법제처 국가법령정보 공동활용 DRF API 클라이언트.

엔드포인트:
  검색: GET /lawSearch.do?OC=&target={law|prec}&type=XML&query=&page=
  상세: GET /lawService.do?OC=&target={law|prec}&type=XML&MST=  (법령)
        GET /lawService.do?OC=&target={law|prec}&type=XML&ID=   (판례)

OC(신청 ID)는 settings.law_api_oc. 미발급 시 호출 자체가 오류 — fixture로 단위 검증.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from dataclasses import replace
from typing import Any

import httpx

from lawcorpus.ingest.models import (
    RawArticle,
    RawArticleUnit,
    RawAddendumUnit,
    RawCase,
    RawCaseListItem,
    RawClause,
    RawEfClause,
    RawEfLaw,
    RawEfSubClause,
    RawHistoryEntry,
    RawItem,
    RawLaw,
    RawLawHierarchy,
    RawLawHierarchyEntry,
    RawLawListItem,
    RawSubClause,
)

_RATE_LIMIT_SLEEP = 0.5   # 요청 간 최소 대기(초)
_MAX_RETRIES = 3
_PAGE_SIZE = 20
_TIMEOUT = 30.0


def _txt(elem: ET.Element | None, default: str = "") -> str:
    if elem is None or elem.text is None:
        return default
    return elem.text.strip()


async def _get_xml(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> ET.Element:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = await client.get(url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            await asyncio.sleep(_RATE_LIMIT_SLEEP)
            try:
                return ET.fromstring(resp.content)
            except ET.ParseError as exc:
                # 점검 중인 API가 HTML "시스템 점검" 페이지를 200으로 돌려주는 경우가 있다 —
                # 응답 앞부분을 남겨야 원인 파악이 된다.
                preview = resp.content[:200].decode("utf-8", errors="replace")
                raise ET.ParseError(f"{exc} — 응답 미리보기: {preview!r}") from exc
        except (httpx.HTTPStatusError, httpx.TimeoutException, ET.ParseError) as exc:
            last_exc = exc
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"API 요청 실패 ({url}): {last_exc}")


# ---------------------------------------------------------------------------
# 법령
# ---------------------------------------------------------------------------

def _parse_law_list(root: ET.Element) -> list[RawLawListItem]:
    items: list[RawLawListItem] = []
    for law in root.findall("law"):
        items.append(
            RawLawListItem(
                law_id=_txt(law.find("법령ID")),
                law_name=_txt(law.find("법령명한글")),
                # 실제 API: <MST> 태그 없음. <법령일련번호>가 lawService.do?MST= 에 쓰는 키
                mst=_txt(law.find("법령일련번호")),
                effective_date=_txt(law.find("시행일자")),
                is_current=_txt(law.find("현행연혁코드")) == "현행",
            )
        )
    return items


async def list_laws(law_name: str, settings) -> list[RawLawListItem]:
    base = settings.law_api_base_url
    results: list[RawLawListItem] = []
    page = 1
    async with httpx.AsyncClient() as client:
        while True:
            root = await _get_xml(
                client,
                f"{base}/lawSearch.do",
                {"OC": settings.law_api_oc, "target": "law", "type": "XML",
                 "query": law_name, "page": page, "display": _PAGE_SIZE},
            )
            items = _parse_law_list(root)
            results.extend(items)
            total = int(_txt(root.find("totalCnt"), "0"))
            if len(results) >= total or len(items) < _PAGE_SIZE:
                break
            page += 1
    return results


def _normalize_clause_no(s: str) -> str:
    """항번호 정규화: ①②③... → 1,2,3..."""
    s = s.strip()
    if s and "①" <= s[0] <= "⑳":  # ①=U+2460 ~ ⑳=U+2473
        return str(ord(s[0]) - 0x245F)
    return s.strip(".()")


def _normalize_sub_no(s: str) -> str:
    """호번호 정규화: "1." → "1", "가." → "가" """
    return s.strip().rstrip(".")


def _article_no(unit: ET.Element) -> str:
    """조문번호 + 가지번호 조합: 조=1, 가지=2 → "1의2" """
    no = _txt(unit.find("조문번호"))
    branch = _txt(unit.find("조문가지번호"))
    return f"{no}의{branch}" if branch else no


def parse_law_xml(root: ET.Element) -> RawLaw:
    info = root.find("기본정보") or root
    law_name = _txt(info.find("법령명_한글")) or _txt(info.find("법령명한글"))
    law_id = _txt(info.find("법령ID"))
    effective_from = _txt(info.find("시행일자"))

    articles: list[RawArticle] = []
    for unit in root.findall(".//조문단위"):
        # 전문(preamble) 및 부칙 제외
        kind = _txt(unit.find("조문여부"))
        if kind not in ("조문", ""):
            continue

        no = _article_no(unit)
        title = _txt(unit.find("조문제목"))
        text = _txt(unit.find("조문내용"))
        # 실제 API: 조문시행일자 (fixture: 시행일자)
        eff = _txt(unit.find("조문시행일자")) or _txt(unit.find("시행일자")) or effective_from

        clauses: list[RawClause] = []
        for clause_el in unit.findall("항"):
            sub_clauses = [
                RawSubClause(
                    no=_normalize_sub_no(_txt(h.find("호번호"))),
                    text=_txt(h.find("호내용")),
                )
                for h in clause_el.findall("호")
            ]
            clauses.append(
                RawClause(
                    no=_normalize_clause_no(_txt(clause_el.find("항번호"))),
                    text=_txt(clause_el.find("항내용")),
                    sub_clauses=sub_clauses,
                )
            )
        if not no:
            continue
        articles.append(RawArticle(no=no, title=title, text=text, effective_from=eff, clauses=clauses))

    history: list[RawHistoryEntry] = []
    for entry in root.findall(".//법령연혁"):
        history.append(
            RawHistoryEntry(
                promulgated_at=_txt(entry.find("공포일자")),
                effective_at=_txt(entry.find("시행일자")),
                law_id=_txt(entry.find("법령ID")),
            )
        )

    return RawLaw(
        law_name=law_name,
        law_id=law_id,
        mst="",  # 목록 조회 시 법령일련번호로 획득 — 상세 응답에는 없음
        effective_from=effective_from,
        articles=articles,
        history=history,
    )


async def fetch_law(mst: str, settings) -> RawLaw:
    async with httpx.AsyncClient() as client:
        root = await _get_xml(
            client,
            f"{settings.law_api_base_url}/lawService.do",
            {"OC": settings.law_api_oc, "target": "law", "type": "XML", "MST": mst},
        )
    return parse_law_xml(root)


# ---------------------------------------------------------------------------
# target=eflaw (시행일 기준 현행법령) — bitemporal 인제스트
# ---------------------------------------------------------------------------

async def list_eflaws(law_name: str, settings) -> list[RawLawListItem]:
    """법령명으로 검색 — 과거/현행/시행예정 스냅샷을 전부 포함해 반환한다(연혁 조회를 겸함)."""
    base = settings.law_api_base_url
    results: list[RawLawListItem] = []
    page = 1
    async with httpx.AsyncClient() as client:
        while True:
            root = await _get_xml(
                client,
                f"{base}/lawSearch.do",
                {"OC": settings.law_api_oc, "target": "eflaw", "type": "XML",
                 "query": law_name, "page": page, "display": _PAGE_SIZE},
            )
            items = _parse_law_list(root)
            results.extend(items)
            total = int(_txt(root.find("totalCnt"), "0"))
            if len(results) >= total or len(items) < _PAGE_SIZE:
                break
            page += 1
    return results


def _parse_ef_clause(clause_el: ET.Element) -> RawEfClause:
    sub_clauses = tuple(
        RawEfSubClause(
            no=_normalize_sub_no(_txt(h.find("호번호"))),
            text=_txt(h.find("호내용")),
            items=tuple(
                RawItem(no=_txt(m.find("목번호")).rstrip("."), text=_txt(m.find("목내용")))
                for m in h.findall("목")
            ),
        )
        for h in clause_el.findall("호")
    )
    return RawEfClause(
        no=_normalize_clause_no(_txt(clause_el.find("항번호"))),
        text=_txt(clause_el.find("항내용")),
        sub_clauses=sub_clauses,
    )


def _parse_article_unit(unit: ET.Element) -> RawArticleUnit:
    return RawArticleUnit(
        jomun_key=unit.get("조문키", ""),
        art_no=int(_txt(unit.find("조문번호"), "0")),
        branch_no=int(_txt(unit.find("조문가지번호"), "0") or "0"),
        is_heading=_txt(unit.find("조문여부")) == "전문",
        title=_txt(unit.find("조문제목")),
        body=_txt(unit.find("조문내용")),
        effective_from=_txt(unit.find("조문시행일자")),
        revision_type=_txt(unit.find("조문제개정유형")),
        changed=_txt(unit.find("조문변경여부")) == "Y",
        moved_from=_txt(unit.find("조문이동이전")),
        moved_to=_txt(unit.find("조문이동이후")),
        clauses=tuple(_parse_ef_clause(c) for c in unit.findall("항")),
    )


def parse_eflaw_xml(root: ET.Element) -> RawEfLaw:
    info = root.find("기본정보")
    if info is None:
        info = root

    articles = tuple(_parse_article_unit(unit) for unit in root.findall(".//조문단위"))
    addenda = tuple(
        RawAddendumUnit(
            addendum_key=unit.get("부칙키", ""),
            promulgated_at=_txt(unit.find("부칙공포일자")),
            promulgation_no=_txt(unit.find("부칙공포번호")),
            body=_txt(unit.find("부칙내용")),
        )
        for unit in root.findall(".//부칙단위")
    )
    revision_reason = _txt(root.find(".//제개정이유내용"))

    return RawEfLaw(
        law_id=_txt(info.find("법령ID")),
        mst=_txt(info.find("법령일련번호")),
        law_name=_txt(info.find("법령명_한글")) or _txt(info.find("법령명한글")),
        law_type=_txt(info.find("법종구분")),
        ministry_code=info.find("소관부처").get("소관부처코드", "") if info.find("소관부처") is not None else "",
        promulgated_on=_txt(info.find("공포일자")),
        promulgation_no=_txt(info.find("공포번호")),
        revision_type=_txt(info.find("제개정구분")),
        enforced_on=_txt(info.find("시행일자")),
        articles=articles,
        addenda=addenda,
        revision_reason=revision_reason,
    )


async def fetch_eflaw(mst: str, settings) -> RawEfLaw:
    async with httpx.AsyncClient() as client:
        root = await _get_xml(
            client,
            f"{settings.law_api_base_url}/lawService.do",
            {"OC": settings.law_api_oc, "target": "eflaw", "type": "XML", "MST": mst},
        )
    ef_law = parse_eflaw_xml(root)
    # eflaw 상세 응답의 <기본정보>에는 법령일련번호(MST) 태그 자체가 없다 — 요청 인자로 채운다
    return replace(ef_law, mst=mst)


# ---------------------------------------------------------------------------
# target=lsStmd (법령체계도) — 법률 -> 시행령 -> 시행규칙 -> 행정규칙 위임관계
# ---------------------------------------------------------------------------

def _parse_lsstmd_entry(info_el: ET.Element) -> RawLawHierarchyEntry:
    law_type_el = info_el.find("법종구분")
    return RawLawHierarchyEntry(
        law_id=_txt(info_el.find("법령ID")),
        mst=_txt(info_el.find("법령일련번호")),
        law_name=_txt(info_el.find("법령명")),
        law_type=_txt(law_type_el) if law_type_el is not None else "",
        enforced_on=_txt(info_el.find("시행일자")),
    )


def parse_lsstmd_xml(root: ET.Element) -> RawLawHierarchy:
    """법률 -> 시행령 -> 시행규칙 3단만 추출한다.

    행정규칙(훈령/고시)도 응답에 포함되지만 시행령/시행규칙 밑에 중복 나열되는 구조라
    이 함수로는 신뢰성 있게 못 뽑는다 — 행정규칙 발굴은 admrul 검색(#29)으로 별도 처리.
    """
    top_info = root.find("기본정보")
    entries: list[RawLawHierarchyEntry] = []

    law_el = root.find("상하위법/법률")
    if law_el is not None:
        info = law_el.find("기본정보")
        if info is not None:
            entries.append(_parse_lsstmd_entry(info))
        # 시행규칙은 시행령 밑에 중첩된다: 법률 > 시행령 > 시행규칙
        decree_el = law_el.find("시행령")
        if decree_el is not None:
            decree_info = decree_el.find("기본정보")
            if decree_info is not None:
                entries.append(_parse_lsstmd_entry(decree_info))
            rule_info = decree_el.find("시행규칙/기본정보")
            if rule_info is not None:
                entries.append(_parse_lsstmd_entry(rule_info))

    return RawLawHierarchy(
        law_id=_txt(top_info.find("법령ID")) if top_info is not None else "",
        mst=_txt(top_info.find("법령일련번호")) if top_info is not None else "",
        law_name=_txt(top_info.find("법령명")) if top_info is not None else "",
        entries=tuple(entries),
    )


async def fetch_law_hierarchy(mst: str, settings) -> RawLawHierarchy:
    async with httpx.AsyncClient() as client:
        root = await _get_xml(
            client,
            f"{settings.law_api_base_url}/lawService.do",
            {"OC": settings.law_api_oc, "target": "lsStmd", "type": "XML", "MST": mst},
        )
    return parse_lsstmd_xml(root)


# ---------------------------------------------------------------------------
# 판례
# ---------------------------------------------------------------------------

def _parse_case_list(root: ET.Element) -> list[RawCaseListItem]:
    items: list[RawCaseListItem] = []
    for prec in root.findall("prec"):
        items.append(
            RawCaseListItem(
                case_id=_txt(prec.find("판례일련번호")),
                case_no=_txt(prec.find("사건번호")),
                court=_txt(prec.find("법원명")),
                decided_at=_txt(prec.find("선고일자")),
                case_type=_txt(prec.find("사건종류명")),
            )
        )
    return items


def _split_refs(text: str) -> list[str]:
    """참조조문/참조판례 원문을 개별 항목으로 분리."""
    if not text:
        return []
    import re
    parts = re.split(r"[,，\n]", text)
    return [p.strip() for p in parts if p.strip()]


async def list_cases(query: str, settings, max_pages: int = 10) -> list[RawCaseListItem]:
    base = settings.law_api_base_url
    results: list[RawCaseListItem] = []
    page = 1
    async with httpx.AsyncClient() as client:
        while page <= max_pages:
            root = await _get_xml(
                client,
                f"{base}/lawSearch.do",
                {"OC": settings.law_api_oc, "target": "prec", "type": "XML",
                 "query": query, "page": page, "display": _PAGE_SIZE},
            )
            items = _parse_case_list(root)
            results.extend(items)
            total = int(_txt(root.find("totalCnt"), "0"))
            if len(results) >= total or len(items) < _PAGE_SIZE:
                break
            page += 1
    return results


def parse_case_xml(root: ET.Element) -> RawCase:
    holding = _txt(root.find("판시사항"))
    summary = _txt(root.find("판결요지"))
    body = _txt(root.find("판례내용"))

    return RawCase(
        case_id=_txt(root.find("판례정보일련번호")),
        case_no=_txt(root.find("사건번호")),
        court=_txt(root.find("법원명")),
        decided_at=_txt(root.find("선고일자")),
        case_type=_txt(root.find("사건종류명")),
        holding=holding,
        summary=summary,
        body=body,
        ref_articles=_split_refs(_txt(root.find("참조조문"))),
        ref_cases=_split_refs(_txt(root.find("참조판례"))),
    )


async def fetch_case(case_id: str, settings) -> RawCase:
    async with httpx.AsyncClient() as client:
        root = await _get_xml(
            client,
            f"{settings.law_api_base_url}/lawService.do",
            {"OC": settings.law_api_oc, "target": "prec", "type": "XML", "ID": case_id},
        )
    return parse_case_xml(root)
