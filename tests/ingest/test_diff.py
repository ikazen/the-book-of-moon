from __future__ import annotations

from lawcorpus.ingest.diff import added_thresholds, diff_trees, extract_thresholds
from lawcorpus.types import Threshold


def _tree(clauses: list[dict]) -> dict:
    return {"clauses": clauses}


def _clause(no: str, text: str, sub_clauses: list[dict] | None = None) -> dict:
    return {"no": no, "text": text, "sub_clauses": sub_clauses or []}


# --- extract_thresholds ---

def test_extract_thresholds_ratio_via_100_bunui():
    result = extract_thresholds("지분율이 100분의 30 이상인 경우")
    assert result == [Threshold(kind="ratio", op=">=", value=30.0, unit="%")]


def test_extract_thresholds_ratio_via_percent_sign():
    result = extract_thresholds("보유비율 30% 이상")
    assert Threshold(kind="ratio", op=">=", value=30.0, unit="%") in result


def test_extract_thresholds_amount_with_op():
    result = extract_thresholds("과세표준이 3억원 이하인 경우")
    assert result == [Threshold(kind="amount", op="<=", value=3.0, unit="억원")]


def test_extract_thresholds_amount_without_op_not_matched():
    """금액 뒤에 이상/초과/이하/미만이 없으면 임계값이 아니라 그냥 금액 언급이므로 매칭하지 않는다."""
    result = extract_thresholds("납부세액은 3억원으로 한다")
    assert result == []


def test_extract_thresholds_period():
    result = extract_thresholds("보유기간이 2년 이상인 경우")
    assert result == [Threshold(kind="period", op=">=", value=2.0, unit="년")]


def test_extract_thresholds_period_does_not_match_bare_year():
    """"2020년"처럼 연산자 없는 연도 표기는 기간 임계값으로 오인되면 안 된다."""
    result = extract_thresholds("2020년에 개정되었다")
    assert result == []


def test_extract_thresholds_headcount():
    result = extract_thresholds("상시근로자 5명 이상을 고용한 경우")
    assert result == [Threshold(kind="headcount", op=">=", value=5.0, unit="명")]


def test_extract_thresholds_multiple_in_one_text():
    result = extract_thresholds("지분 100분의 30 이상을 2년 이상 보유한 경우")
    kinds = {t.kind for t in result}
    assert kinds == {"ratio", "period"}


# --- diff_trees ---

def test_diff_trees_added_clause():
    from_tree = _tree([_clause("1", "첫째")])
    to_tree = _tree([_clause("1", "첫째"), _clause("2", "둘째")])

    diff = diff_trees(from_tree, to_tree)

    assert diff["added"] == {"제2항": "둘째"}
    assert diff["removed"] == {}
    assert diff["changed"] == {}


def test_diff_trees_removed_clause():
    from_tree = _tree([_clause("1", "첫째"), _clause("2", "둘째")])
    to_tree = _tree([_clause("1", "첫째")])

    diff = diff_trees(from_tree, to_tree)

    assert diff["removed"] == {"제2항": "둘째"}


def test_diff_trees_changed_clause():
    from_tree = _tree([_clause("1", "지분 100분의 20 이상")])
    to_tree = _tree([_clause("1", "지분 100분의 30 이상")])

    diff = diff_trees(from_tree, to_tree)

    assert diff["changed"] == {"제1항": {"from": "지분 100분의 20 이상", "to": "지분 100분의 30 이상"}}


def test_diff_trees_unchanged_clause_not_reported():
    from_tree = _tree([_clause("1", "동일")])
    to_tree = _tree([_clause("1", "동일")])

    diff = diff_trees(from_tree, to_tree)

    assert diff == {"added": {}, "removed": {}, "changed": {}}


# --- added_thresholds ---

def test_added_thresholds_from_new_clause():
    from_tree = _tree([_clause("1", "요건 없음")])
    to_tree = _tree([_clause("1", "요건 없음"), _clause("2", "지분 100분의 30 이상")])

    diff = diff_trees(from_tree, to_tree)
    thresholds = added_thresholds(diff)

    assert thresholds == [Threshold(kind="ratio", op=">=", value=30.0, unit="%")]


def test_added_thresholds_excludes_preexisting_threshold_in_changed_clause():
    """조문 문구가 바뀌어도 임계값 자체가 그대로면 '신설'이 아니다."""
    from_tree = _tree([_clause("1", "지분 100분의 30 이상이고 기타 요건 A")])
    to_tree = _tree([_clause("1", "지분 100분의 30 이상이고 기타 요건 B")])

    diff = diff_trees(from_tree, to_tree)
    thresholds = added_thresholds(diff)

    assert thresholds == []


def test_added_thresholds_detects_genuinely_new_threshold_in_changed_clause():
    from_tree = _tree([_clause("1", "지분 100분의 30 이상인 경우")])
    to_tree = _tree([_clause("1", "지분 100분의 30 이상이고 보유기간 2년 이상인 경우")])

    diff = diff_trees(from_tree, to_tree)
    thresholds = added_thresholds(diff)

    assert thresholds == [Threshold(kind="period", op=">=", value=2.0, unit="년")]
