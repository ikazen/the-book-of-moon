from dataclasses import dataclass, field
from enum import StrEnum


class ValidityFlag(StrEnum):
    VALID = "valid"
    OVERRULED = "overruled"
    LAW_AMENDED = "law_amended"
    UNCERTAIN = "uncertain"


@dataclass
class Chunk:
    chunk_id: str
    table: str        # "article" | "case"
    text: str
    score: float
    meta: dict


@dataclass
class GraphChunk:
    chunk_id: str
    node_type: str       # "article" | "case"
    validity_flag: str | None = None
    meta: dict = field(default_factory=dict)
