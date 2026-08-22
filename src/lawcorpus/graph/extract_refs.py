"""참조(REFERS_TO)/준용(MUTATIS)/위임(DELEGATES) 엣지 후보 추출.

1차 소스는 target=lsDelegated(법제처가 조문/항/호/목 단위로 이미 구조화해 제공 — the-book-of-moon
#23 실측) — 자유텍스트 정규식보다 정확하다. lsDelegated 응답은 <위임정보> 안에
(위임구분, 위임법령일련번호, 위임법령제목)이 제대로 중첩되지 않고 **flat sibling로 반복**되는
특이한 구조라 순서대로 스캔하며 그룹을 나눠야 한다.

MUTATIS(준용) 판정: lsDelegated 자체엔 준용 전용 구분이 없다 — 실측 결과 "준용" 신호는
**출발 조문의 조문제목**에 있다(예: 제25조의2 "연대납세의무에 관한 「민법」의 준용"). 그 조문
밑에서 인용법령으로 걸린 엣지는 REFERS_TO가 아니라 MUTATIS로 분류한다.

위임행정규칙(훈령/고시) 엣지는 스킵한다 — admrul은 article 그래프의 노드가 아니라 ruling
테이블에 별도로 있다(#29).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from lawcorpus.ingest.models import RawDelegationEdge

# 실측(eflaw_detail.xml) 기준 두 가지 정의 표현이 흔하다:
#   "국세"(國稅)란 ... / "가산세"(加算稅)이란 ...        <- 정의 조문의 표제 스타일
#   ...(이하 "법인 아닌 단체"라 한다)                     <- 본문 중간의 약칭 정의
_RE_DEFINE_RAN = re.compile(r'["“]([^"”]{1,30})["”]\s*(?:\([^)]*\))?\s*(?:란|이란)')
_RE_DEFINE_IHA = re.compile(r'이하\s*["“]([^"”]{1,30})["”]\s*(?:라|이라)\s*한다')


def extract_defines(text: str) -> list[str]:
    """조문 본문에서 정의되는 용어를 추출한다(DEFINES 엣지 후보). 중복 제거, 등장 순서 유지."""
    seen: set[str] = set()
    result: list[str] = []
    for pattern in (_RE_DEFINE_RAN, _RE_DEFINE_IHA):
        for m in pattern.finditer(text):
            term = m.group(1).strip()
            if term and term not in seen:
                seen.add(term)
                result.append(term)
    return result


def _txt(elem: ET.Element | None) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def _iter_delegation_groups(uiim_jeongbo: ET.Element) -> list[dict]:
    """<위임정보> 안의 flat 반복 (위임구분, 위임법령일련번호, 위임법령제목, 조문정보들)을
    순서대로 스캔해 그룹으로 나눈다."""
    groups: list[dict] = []
    current: dict | None = None
    for child in uiim_jeongbo:
        if child.tag == "위임구분":
            current = {"kind": _txt(child), "law_mst": "", "law_title": "", "jo_infos": []}
            groups.append(current)
        elif current is None:
            continue
        elif child.tag == "위임법령일련번호":
            current["law_mst"] = _txt(child)
        elif child.tag == "위임법령제목":
            current["law_title"] = _txt(child)
        elif child.tag == "위임법령조문정보":
            current["jo_infos"].append(child)
    return groups


def _to_int(s: str) -> int | None:
    s = s.strip()
    return int(s) if s.isdigit() and int(s) > 0 else None


def extract_delegation_edges(root: ET.Element) -> list[RawDelegationEdge]:
    edges: list[RawDelegationEdge] = []

    for unit in root.findall(".//위임조문정보"):
        jo_info = unit.find("조정보")
        if jo_info is None:
            continue
        source_art_no = _to_int(_txt(jo_info.find("조문번호")))
        if source_art_no is None:
            continue
        source_branch_no = _to_int(_txt(jo_info.find("조문가지번호"))) or 0
        is_mutatis_source = "준용" in _txt(jo_info.find("조문제목"))

        for uiim_jeongbo in unit.findall("위임정보"):
            for group in _iter_delegation_groups(uiim_jeongbo):
                if group["kind"] in ("시행령", "시행규칙"):
                    edge_type = "DELEGATES"
                elif group["kind"] == "인용법령":
                    edge_type = "MUTATIS" if is_mutatis_source else "REFERS_TO"
                else:
                    continue  # 위임행정규칙 등 — article 그래프 대상 아님

                for target_jo in group["jo_infos"]:
                    edges.append(
                        RawDelegationEdge(
                            source_art_no=source_art_no,
                            source_branch_no=source_branch_no,
                            source_johang=_txt(target_jo.find("조항호목")),
                            edge_type=edge_type,
                            target_law_mst=group["law_mst"],
                            target_law_title=group["law_title"],
                            target_art_no=_to_int(_txt(target_jo.find("위임법령조문번호"))),
                            target_branch_no=_to_int(_txt(target_jo.find("위임법령조문가지번호"))) or 0,
                        )
                    )
    return edges
