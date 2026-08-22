from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from lawcorpus.ingest.addendum_parser import parse_addendum
from lawcorpus.ingest.law_api import parse_eflaw_xml
from lawcorpus.ingest.models import RawAddendumUnit

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "law_api"


def _eflaw():
    return parse_eflaw_xml(ET.parse(_FIXTURES / "eflaw_detail.xml").getroot())


def test_parse_addendum_first_item_is_enforcement_date():
    first = _eflaw().addenda[0]

    items = parse_addendum(first)

    assert items[0].kind == "시행일"
    assert items[0].applies_from == date(1975, 1, 1)


def test_parse_addendum_dong_jeon_inherits_previous_kind():
    """"동전"(同前)은 표제가 없는 게 아니라 "앞 항목과 같음"이라는 뜻 — 분류를 이어받아야 한다."""
    first = _eflaw().addenda[0]

    items = parse_addendum(first)

    dong_jeon_items = [i for i in items if i.body.startswith("이 법 시행전에 세법") or i.body.startswith("이 법 시행당시")]
    assert dong_jeon_items
    assert all(i.kind == "경과조치" for i in dong_jeon_items)


def test_parse_addendum_unmatched_label_falls_back_to_teukrye():
    first = _eflaw().addenda[0]

    items = parse_addendum(first)

    repeal_item = next(i for i in items if "폐지" in i.body)
    assert repeal_item.kind == "특례"


def test_parse_addendum_applyrye_suffix_matched_by_substring():
    law = _eflaw()
    matched = None
    for unit in law.addenda:
        for item in parse_addendum(unit):
            if "적용례" in item.body or item.kind == "적용례":
                matched = item
                break
        if matched:
            break
    assert matched is not None
    assert matched.kind == "적용례"


def test_parse_addendum_no_circled_number_falls_back_to_single_item():
    unit = RawAddendumUnit(addendum_key="x", promulgated_at="20200101", promulgation_no="1234", body="이 법은 공포한 날부터 시행한다.")

    items = parse_addendum(unit)

    assert len(items) == 1
    assert items[0].clause_no == "1"


def test_parse_addendum_empty_body_returns_no_items():
    unit = RawAddendumUnit(addendum_key="x", promulgated_at="20200101", promulgation_no="1234", body="")

    assert parse_addendum(unit) == []


def test_parse_addendum_promulgation_no_parsed_as_int():
    first = _eflaw().addenda[0]

    items = parse_addendum(first)

    assert items[0].promulgation_no == 2679
