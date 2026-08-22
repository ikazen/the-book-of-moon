"""RawEfLaw(법제처 eflaw 스냅샷 1건) -> statute/article/article_version DB row 매핑.

버전 이력(과거 스냅샷) 전량 처리나 valid_to 확정은 여기서 하지 않는다 — 이 모듈은 스냅샷
1건을 순수 변환만 한다. 여러 스냅샷을 적재한 뒤 valid_to를 채우는 건 commands.py의
close_versions()가 한다(설계문서 8절: 현행 스냅샷 적재 → 이력 전량 수집은 별도 단계).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from lawcorpus.ingest.models import RawArticleUnit, RawEfLaw
from lawcorpus.ingest.tree import build_tree

_TRAILING_AMENDMENT_TAG = re.compile(r"\s*<개정[^>]*>\s*$")


def _to_date(yyyymmdd: str) -> date:
    s = yyyymmdd.strip()
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _clean_heading(text: str) -> str:
    return _TRAILING_AMENDMENT_TAG.sub("", text).strip()


@dataclass(frozen=True, slots=True)
class MappedArticleVersion:
    art_no: int
    branch_no: int
    chapter_title: str | None
    title: str
    body: str
    tree: dict
    valid_from: date
    promulgated_on: date
    promulgation_no: int | None
    revision_type: str
    is_full_rewrite: bool
    revision_reason: str
    moleg_article_key: str


@dataclass
class MappedStatute:
    statute_id: int
    name: str
    law_type: str
    ministry_code: str
    current_mst: str
    enforced_on: date | None
    versions: list[MappedArticleVersion] = field(default_factory=list)
    revision_reason: str = ""


def _promulgation_no(raw: str) -> int | None:
    digits = raw.strip().lstrip("0")
    return int(digits) if digits.isdigit() else None


def map_eflaw(ef_law: RawEfLaw) -> MappedStatute:
    versions: list[MappedArticleVersion] = []
    current_chapter: str | None = None
    promulgated_on = _to_date(ef_law.promulgated_on) if ef_law.promulgated_on else None
    promulgation_no = _promulgation_no(ef_law.promulgation_no)

    for unit in ef_law.articles:
        if unit.is_heading:
            current_chapter = _clean_heading(unit.body) or current_chapter
            continue
        if not unit.effective_from:
            continue

        versions.append(
            MappedArticleVersion(
                art_no=unit.art_no,
                branch_no=unit.branch_no,
                chapter_title=current_chapter,
                title=unit.title,
                body=unit.body,
                tree=build_tree(unit),
                valid_from=_to_date(unit.effective_from),
                promulgated_on=promulgated_on or _to_date(unit.effective_from),
                promulgation_no=promulgation_no,
                revision_type=unit.revision_type,
                is_full_rewrite=unit.revision_type == "전부개정",
                revision_reason=ef_law.revision_reason,
                moleg_article_key=f"{ef_law.mst}:{unit.jomun_key}",
            )
        )

    return MappedStatute(
        statute_id=int(ef_law.law_id),
        name=ef_law.law_name,
        law_type=ef_law.law_type,
        ministry_code=ef_law.ministry_code,
        current_mst=ef_law.mst,
        enforced_on=_to_date(ef_law.enforced_on) if ef_law.enforced_on else None,
        versions=versions,
        revision_reason=ef_law.revision_reason,
    )
