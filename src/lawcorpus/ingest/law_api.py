"""
법제처 국가법령정보 공동활용 DRF API 클라이언트.

엔드포인트:
  검색: GET /lawSearch.do?OC=&target={eflaw|prec|expc|detc|admrul}&type=XML&query=&page=
  상세: GET /lawService.do?OC=&target={eflaw|lsStmd|lsDelegated}&type=XML&MST=
        GET /lawService.do?OC=&target={prec|expc|detc|admrul}&type=XML&ID=

OC(신청 ID)는 settings.law_api_oc. 미발급 시 호출 자체가 오류 — fixture로 단위 검증.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from dataclasses import replace
from typing import Any

import httpx

from lawcorpus.ingest.models import (
    RawArticleUnit,
    RawAddendumUnit,
    RawEfClause,
    RawEfLaw,
    RawEfSubClause,
    RawItem,
    RawLawHierarchy,
    RawLawHierarchyEntry,
    RawLawListItem,
    RawRuling,
    RawRulingListItem,
)
from lawcorpus.storage.raw_store import put_raw

_RATE_LIMIT_SLEEP = 0.5   # 요청 간 최소 대기(초)
_MAX_RETRIES = 3
_PAGE_SIZE = 20
_TIMEOUT = 30.0


def _txt(elem: ET.Element | None, default: str = "") -> str:
    if elem is None or elem.text is None:
        return default
    return elem.text.strip()


async def _get_xml_raw(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> tuple[ET.Element, bytes]:
    """파싱된 root와 원본 bytes를 함께 반환한다 — 원본 오브젝트 스토리지 보관용(결정 L)."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = await client.get(url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            await asyncio.sleep(_RATE_LIMIT_SLEEP)
            try:
                return ET.fromstring(resp.content), resp.content
            except ET.ParseError as exc:
                # 점검 중인 API가 HTML "시스템 점검" 페이지를 200으로 돌려주는 경우가 있다 —
                # 응답 앞부분을 남겨야 원인 파악이 된다.
                preview = resp.content[:200].decode("utf-8", errors="replace")
                raise ET.ParseError(f"{exc} — 응답 미리보기: {preview!r}") from exc
        except (httpx.HTTPStatusError, httpx.TimeoutException, ET.ParseError) as exc:
            last_exc = exc
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"API 요청 실패 ({url}): {last_exc}")


async def _get_xml(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> ET.Element:
    root, _raw = await _get_xml_raw(client, url, params)
    return root


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


def _normalize_clause_no(s: str) -> str:
    """항번호 정규화: ①②③... → 1,2,3..."""
    s = s.strip()
    if s and "①" <= s[0] <= "⑳":  # ①=U+2460 ~ ⑳=U+2473
        return str(ord(s[0]) - 0x245F)
    return s.strip(".()")


def _normalize_sub_no(s: str) -> str:
    """호번호 정규화: "1." → "1", "가." → "가" """
    return s.strip().rstrip(".")


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


async def fetch_eflaw(mst: str, settings, ef_yd: str | None = None) -> RawEfLaw:
    """ef_yd(효력일자 YYYYMMDD)가 필요한 경우가 있다 — 실측 결과 현행 스냅샷은 생략 가능하지만
    과거 스냅샷(list_eflaws가 돌려주는 historical MST)은 ef_yd 없이 호출하면 500 에러가 난다."""
    params = {"OC": settings.law_api_oc, "target": "eflaw", "type": "XML", "MST": mst}
    if ef_yd:
        params["efYd"] = ef_yd
    async with httpx.AsyncClient() as client:
        root, raw = await _get_xml_raw(
            client,
            f"{settings.law_api_base_url}/lawService.do",
            params,
        )
    ef_law = parse_eflaw_xml(root)
    raw_uri = await put_raw(settings, f"eflaw/{mst}.xml", raw)
    # eflaw 상세 응답의 <기본정보>에는 법령일련번호(MST) 태그 자체가 없다 — 요청 인자로 채운다
    return replace(ef_law, mst=mst, raw_uri=raw_uri)


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


async def fetch_law_delegations(mst: str, settings) -> ET.Element:
    """target=lsDelegated — 조문/항/호/목 단위 위임·인용 원문. graph/extract_refs.py가 소비한다."""
    async with httpx.AsyncClient() as client:
        root, raw = await _get_xml_raw(
            client,
            f"{settings.law_api_base_url}/lawService.do",
            {"OC": settings.law_api_oc, "target": "lsDelegated", "type": "XML", "MST": mst},
        )
    await put_raw(settings, f"lsDelegated/{mst}.xml", raw)
    return root


# ---------------------------------------------------------------------------
# 쟁송 + 해석 통합 (prec/expc/detc/admrul -> RawRuling)
#
# 실측(#23) 결과 4개 target의 목록/상세 구조가 예상보다 서로 달라(루트/항목 태그명,
# ID 파라미터, 필드명 전부 제각각) 공통 XML 태그맵 하나로는 못 묶는다 — 소스별 파서를
# 두되 전부 RawRuling으로 수렴시켜 "통합 매퍼"를 출력 타입 레벨에서 달성한다.
# ---------------------------------------------------------------------------

_RULING_LIST_CONFIG: dict[str, dict[str, str | None]] = {
    "prec":   {"item_tag": "prec",  "id_field": "판례일련번호",        "case_no_field": "사건번호", "title_field": "사건명", "date_field": "선고일자"},
    "expc":   {"item_tag": "expc",  "id_field": "법령해석례일련번호",  "case_no_field": "안건번호", "title_field": "안건명", "date_field": "회신일자"},
    "detc":   {"item_tag": "Detc",  "id_field": "헌재결정례일련번호",  "case_no_field": "사건번호", "title_field": "사건명", "date_field": "종국일자"},
    "admrul": {"item_tag": "admrul", "id_field": "행정규칙일련번호",   "case_no_field": None,      "title_field": "행정규칙명", "date_field": "발령일자"},
}
_RULING_SOURCE_NAME = {"prec": "법원", "expc": "법제처", "detc": "헌법재판소", "admrul": "행정규칙"}


async def list_rulings(target: str, query: str, settings, max_pages: int = 10) -> list[RawRulingListItem]:
    config = _RULING_LIST_CONFIG[target]
    base = settings.law_api_base_url
    results: list[RawRulingListItem] = []
    page = 1
    async with httpx.AsyncClient() as client:
        while page <= max_pages:
            root = await _get_xml(
                client,
                f"{base}/lawSearch.do",
                {"OC": settings.law_api_oc, "target": target, "type": "XML",
                 "query": query, "page": page, "display": _PAGE_SIZE},
            )
            items = root.findall(config["item_tag"])
            for item in items:
                court = _txt(item.find("법원명")) if target == "prec" else ""
                case_no_field = config["case_no_field"]
                results.append(
                    RawRulingListItem(
                        ruling_id=_txt(item.find(config["id_field"])),
                        source=court or _RULING_SOURCE_NAME[target],
                        case_no=_txt(item.find(case_no_field)) if case_no_field else "",
                        title=_txt(item.find(config["title_field"])),
                        decided_at=_txt(item.find(config["date_field"])),
                    )
                )
            total = int(_txt(root.find("totalCnt"), "0"))
            if len(results) >= total or len(items) < _PAGE_SIZE:
                break
            page += 1
    return results


def _parse_prec_detail(root: ET.Element) -> RawRuling:
    return RawRuling(
        ruling_id=_txt(root.find("판례정보일련번호")),
        source=_txt(root.find("법원명")) or "법원",
        case_no=_txt(root.find("사건번호")),
        decided_at=_txt(root.find("선고일자")),
        title=_txt(root.find("사건명")),
        gist=_txt(root.find("판시사항")),
        body="\n".join(p for p in (_txt(root.find("판결요지")), _txt(root.find("판례내용"))) if p),
        ref_articles=tuple(_split_refs(_txt(root.find("참조조문")))),
        ref_cases=tuple(_split_refs(_txt(root.find("참조판례")))),
    )


def _parse_expc_detail(root: ET.Element) -> RawRuling:
    return RawRuling(
        ruling_id=_txt(root.find("법령해석례일련번호")),
        source="법제처",
        case_no=_txt(root.find("안건번호")),
        decided_at=_txt(root.find("해석일자")),
        title=_txt(root.find("안건명")),
        gist=_txt(root.find("질의요지")),
        body="\n".join(p for p in (_txt(root.find("회답")), _txt(root.find("이유"))) if p),
    )


def _parse_detc_detail(root: ET.Element) -> RawRuling:
    return RawRuling(
        ruling_id=_txt(root.find("헌재결정례일련번호")),
        source="헌법재판소",
        case_no=_txt(root.find("사건번호")),
        decided_at=_txt(root.find("종국일자")),
        title=_txt(root.find("사건명")),
        gist=_txt(root.find("판시사항")),
        body="\n".join(p for p in (_txt(root.find("결정요지")), _txt(root.find("전문"))) if p),
        ref_articles=tuple(_split_refs(_txt(root.find("참조조문")))),
        ref_cases=tuple(_split_refs(_txt(root.find("참조판례")))),
    )


def _parse_admrul_detail(root: ET.Element) -> RawRuling:
    info = root.find("행정규칙기본정보")
    body = "\n".join(_txt(el) for el in root.findall("조문내용"))
    name = _txt(info.find("행정규칙명")) if info is not None else ""
    return RawRuling(
        ruling_id=_txt(info.find("행정규칙일련번호")) if info is not None else "",
        source="행정규칙",
        case_no="",
        decided_at=_txt(info.find("발령일자")) if info is not None else "",
        title=name,
        gist=name,
        body=body,
    )


_RULING_DETAIL_PARSERS = {
    "prec": _parse_prec_detail,
    "expc": _parse_expc_detail,
    "detc": _parse_detc_detail,
    "admrul": _parse_admrul_detail,
}


async def fetch_ruling(target: str, ruling_id: str, settings) -> RawRuling:
    async with httpx.AsyncClient() as client:
        root, raw = await _get_xml_raw(
            client,
            f"{settings.law_api_base_url}/lawService.do",
            {"OC": settings.law_api_oc, "target": target, "type": "XML", "ID": ruling_id},
        )
    raw_uri = await put_raw(settings, f"{target}/{ruling_id}.xml", raw)
    ruling = _RULING_DETAIL_PARSERS[target](root)
    return replace(ruling, raw_uri=raw_uri)


def _split_refs(text: str) -> list[str]:
    """참조조문/참조판례 원문을 개별 항목으로 분리(_parse_prec_detail/_parse_detc_detail이 사용)."""
    if not text:
        return []
    import re
    parts = re.split(r"[,，\n]", text)
    return [p.strip() for p in parts if p.strip()]
