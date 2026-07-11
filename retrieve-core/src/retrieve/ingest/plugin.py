"""Ingestion plugin interface and orchestrator.

Plugins implement discover() → fetch() → convert() to transform
raw sources into structured Markdown with YAML frontmatter.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class DiscoveredPage:
    """A page discovered from the source."""

    href: str  # relative path or URL suffix
    title: str
    parent: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchedPage:
    """A fetched page with raw content."""

    href: str
    title: str
    parent: str
    raw_content: str  # HTML, PDF text, etc.
    source_url: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConvertedDoc:
    """A converted document ready to save as Markdown."""

    policy_id: str
    title: str
    parent: str
    source_url: str
    markdown: str
    cross_references: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CorpusStats:
    """Stats about the ingested corpus — used by SOTA mode to recommend a path."""

    doc_count: int = 0
    total_chars: int = 0
    avg_doc_length: float = 0.0
    cross_ref_count: int = 0
    cross_ref_density: float = 0.0  # avg cross-refs per doc
    categories: dict[str, int] = field(default_factory=dict)  # parent section → count


class IngestPlugin(ABC):
    """Base class for ingestion plugins."""

    name: str = "base"

    @abstractmethod
    def discover(self, source: str) -> list[DiscoveredPage]:
        """Discover all pages/documents from the source."""
        ...

    @abstractmethod
    def fetch(self, page: DiscoveredPage, source: str) -> FetchedPage | None:
        """Fetch the raw content of a single page."""
        ...

    @abstractmethod
    def convert(self, page: FetchedPage) -> ConvertedDoc | None:
        """Convert raw content to structured Markdown."""
        ...
