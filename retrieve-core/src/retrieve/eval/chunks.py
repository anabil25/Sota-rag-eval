"""Chunking utilities — split Markdown documents into chunks for eval generation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Chunk:
    """A chunk of a document, with metadata for ground-truth pairing."""

    chunk_id: str  # "{doc_id}::{chunk_index}"
    doc_id: str  # filename stem (e.g. "100-10_ethical_conduct")
    doc_title: str
    content: str
    heading: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter and return (frontmatter_dict, body)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    body = text[m.end() :]
    return fm, body


def chunk_by_heading(doc_id: str, doc_title: str, body: str) -> list[Chunk]:
    """Split a Markdown document into chunks by heading boundaries.

    Each top-level or second-level heading starts a new chunk.
    Content before the first heading becomes chunk 0.
    """
    chunks: list[Chunk] = []
    # Split on ## or # headings
    sections = re.split(r"(?=^#{1,2}\s)", body, flags=re.MULTILINE)

    for i, section in enumerate(sections):
        section = section.strip()
        if not section:
            continue

        # Extract heading if present
        heading = ""
        heading_match = re.match(r"^(#{1,2})\s+(.*?)$", section, re.MULTILINE)
        if heading_match:
            heading = heading_match.group(2).strip()

        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}::{i}",
                doc_id=doc_id,
                doc_title=doc_title,
                content=section,
                heading=heading,
            )
        )

    # If no headings found, return the whole doc as one chunk
    if not chunks and body.strip():
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}::0",
                doc_id=doc_id,
                doc_title=doc_title,
                content=body.strip(),
            )
        )

    return chunks


def load_corpus_chunks(corpus_dir: str | Path) -> list[Chunk]:
    """Load all Markdown files from a corpus directory and chunk them."""
    corpus_path = Path(corpus_dir)
    all_chunks: list[Chunk] = []

    for md_file in sorted(corpus_path.rglob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)

        # Prefer the source's stable logical identifier; filename stems remain
        # a compatibility fallback for corpora without identity metadata.
        doc_id = fm.get("document_id") or fm.get("doc_id") or fm.get("policy_id") or md_file.stem
        doc_title = fm.get("title", md_file.stem)

        chunks = chunk_by_heading(doc_id, doc_title, body)
        for chunk in chunks:
            chunk.metadata = {
                "parent": fm.get("parent", ""),
                "source_url": fm.get("source_url", ""),
                "cross_references": fm.get("cross_references", []),
                "file": str(md_file.relative_to(corpus_path)),
            }
        all_chunks.extend(chunks)

    return all_chunks
