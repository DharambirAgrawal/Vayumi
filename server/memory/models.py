from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class MemoryType(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    EVENT = "event"
    RELATIONSHIP = "relationship"
    LINK = "link"
    FILE = "file"
    IMAGE = "image"
    AUDIO = "audio"
    MEETING = "meeting"


@dataclass
class MemoryRecord:
    id: str
    type: MemoryType
    summary: str
    speaker_id: str
    created_at: datetime
    source_url: Optional[str] = None
    blob_path: Optional[str] = None
    chunk_ids: List[str] = field(default_factory=list)
    graph_node_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    memory_id: str
    content: str
    score: float
    type: MemoryType
    source: Optional[str]
    speaker_id: str
    date: Optional[str]
    blob_path: Optional[str]


@dataclass
class SearchResponse:
    context: str
    results: List[SearchResult]


@dataclass
class IngestResponse:
    memory_id: str
    store: str
    chunk_count: int
    success: bool


@dataclass
class UserModel:
    speaker_id: str
    communication_style: str
    preferred_length: str
    topics_of_interest: List[str]
    frequent_people: Dict[str, str]
    emotional_patterns: str
    last_updated: datetime
    emotional_history: List[Dict[str, Any]] = field(default_factory=list)
