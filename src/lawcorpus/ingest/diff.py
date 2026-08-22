"""개정 diff 생성 + 신설된 수치 임계값(added_thresholds) 추출.

added_thresholds가 이 DB의 가장 독자적인 자산이다 — 개정으로 새로 생긴 수치·기간·비율
조건이 곧 새 경계선이다(지분율 30% 요건을 넣으면 29.9%가 열린다).
"""

from __future__ import annotations

import re

from lawcorpus.types import Threshold

_OP_MAP = {"이상": ">=", "초과": ">", "이하": "<=", "미만": "<"}

# (kind, unit, pattern) — amount/period/headcount는 이상/초과/이하/미만이 반드시 붙어야
# 매칭한다("2020년" 같은 날짜 표현이 기간 임계값으로 오인되는 걸 막는다). ratio는
# "100분의 30" 자체가 이미 임계값 표현이라 연산자 없이도 매칭한다.
_PATTERNS: tuple[tuple[str, str | None, re.Pattern], ...] = (
    ("ratio", "%", re.compile(r"100분의\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<op>이상|초과|이하|미만)?")),
    ("ratio", "%", re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?:퍼센트|%)\s*(?P<op>이상|초과|이하|미만)?")),
    ("amount", None, re.compile(r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>억원|만원|천원|원)\s*(?P<op>이상|초과|이하|미만)")),
    ("period", None, re.compile(r"(?P<value>\d+)\s*(?P<unit>년|개월|일)\s*(?P<op>이상|초과|이하|미만)")),
    ("headcount", None, re.compile(r"(?P<value>\d+)\s*(?P<unit>명|인)\s*(?P<op>이상|초과|이하|미만)")),
)


def extract_thresholds(text: str) -> list[Threshold]:
    thresholds: list[Threshold] = []
    for kind, fixed_unit, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            op_text = m.groupdict().get("op")
            unit = fixed_unit or m.group("unit")
            thresholds.append(
                Threshold(
                    kind=kind,
                    op=_OP_MAP.get(op_text, "=="),
                    value=float(m.group("value").replace(",", "")),
                    unit=unit,
                )
            )
    return thresholds


def _flatten_tree(tree: dict) -> dict[str, str]:
    """조문 tree를 {경로: 텍스트} 평면 dict로 — 항/호/목 단위로 added/removed/changed를 비교한다."""
    flat: dict[str, str] = {}
    for clause in tree.get("clauses", []):
        clause_path = f"제{clause['no']}항" if clause["no"] else "본문"
        flat[clause_path] = clause["text"]
        for sub in clause["sub_clauses"]:
            sub_path = f"{clause_path}제{sub['no']}호"
            flat[sub_path] = sub["text"]
            for item in sub["items"]:
                flat[f"{sub_path}{item['no']}목"] = item["text"]
    return flat


def diff_trees(from_tree: dict, to_tree: dict) -> dict:
    """두 조문 tree를 경로 단위로 비교해 added/removed/changed를 산출한다."""
    from_flat = _flatten_tree(from_tree)
    to_flat = _flatten_tree(to_tree)

    added = {path: text for path, text in to_flat.items() if path not in from_flat}
    removed = {path: text for path, text in from_flat.items() if path not in to_flat}
    changed = {
        path: {"from": from_flat[path], "to": to_flat[path]}
        for path in from_flat.keys() & to_flat.keys()
        if from_flat[path] != to_flat[path]
    }
    return {"added": added, "removed": removed, "changed": changed}


def added_thresholds(diff: dict) -> list[Threshold]:
    """diff_trees 결과의 added + changed(to) 텍스트에서 새로 생긴 임계값만 뽑는다.
    changed의 경우 from에 이미 있던 임계값은 제외해 '진짜 신설'만 남긴다."""
    result: list[Threshold] = []
    for text in diff["added"].values():
        result.extend(extract_thresholds(text))
    for delta in diff["changed"].values():
        before = set(extract_thresholds(delta["from"]))
        after = extract_thresholds(delta["to"])
        result.extend(t for t in after if t not in before)
    return result
