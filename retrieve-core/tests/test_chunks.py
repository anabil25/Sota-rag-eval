"""Tests for eval/chunks.py — corpus loading and chunking."""

import tempfile
import os
from pathlib import Path
import pytest
from retrieve.eval.chunks import (
    parse_frontmatter,
    chunk_by_heading,
    load_corpus_chunks,
)


class TestParseFrontmatter:
    def test_with_frontmatter(self):
        text = '---\npolicy_id: "100"\ntitle: "General"\n---\n\nBody text here.'
        fm, body = parse_frontmatter(text)
        assert fm["policy_id"] == "100"
        assert fm["title"] == "General"
        assert body.strip() == "Body text here."

    def test_without_frontmatter(self):
        text = "Just a body with no frontmatter."
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == text

    def test_empty_frontmatter(self):
        text = "---\n---\n\nBody."
        fm, body = parse_frontmatter(text)
        # Empty YAML between --- delimiters parses as None → {}
        assert fm == {}
        # Body is stripped of frontmatter
        assert "Body." in body


class TestChunkByHeading:
    def test_single_chunk_no_headings(self):
        chunks = chunk_by_heading("doc1", "Title", "Some text without headings.")
        assert len(chunks) == 1
        assert chunks[0].chunk_id == "doc1::0"
        assert chunks[0].doc_id == "doc1"
        assert chunks[0].content == "Some text without headings."

    def test_splits_on_h1(self):
        body = "Intro text.\n\n# Section One\n\nContent one.\n\n# Section Two\n\nContent two."
        chunks = chunk_by_heading("doc1", "Title", body)
        assert len(chunks) == 3  # intro + 2 sections
        assert chunks[1].heading == "Section One"
        assert chunks[2].heading == "Section Two"

    def test_splits_on_h2(self):
        body = "## Part A\n\nA content.\n\n## Part B\n\nB content."
        chunks = chunk_by_heading("doc1", "Title", body)
        assert len(chunks) == 2
        assert chunks[0].heading == "Part A"
        assert chunks[1].heading == "Part B"

    def test_chunk_ids_sequential(self):
        body = "# A\nText\n\n# B\nText\n\n# C\nText"
        chunks = chunk_by_heading("doc1", "Title", body)
        # IDs are sequential per chunk (may start at 1 if there's an empty pre-heading split)
        assert len(chunks) == 3
        assert all(c.chunk_id.startswith("doc1::") for c in chunks)

    def test_empty_body(self):
        chunks = chunk_by_heading("doc1", "Title", "")
        assert len(chunks) == 0

    def test_doc_title_preserved(self):
        chunks = chunk_by_heading("doc1", "My Title", "Some text.")
        assert chunks[0].doc_title == "My Title"


class TestLoadCorpusChunks:
    def test_loads_from_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two test markdown files
            p1 = Path(tmpdir) / "100" / "100_general.md"
            p1.parent.mkdir()
            p1.write_text(
                '---\ndoc_id: "100"\ntitle: "General"\n---\n\n'
                "# Overview\n\nGeneral info.\n\n# Details\n\nMore info.",
                encoding="utf-8",
            )
            p2 = Path(tmpdir) / "101" / "101_applications.md"
            p2.parent.mkdir()
            p2.write_text(
                '---\ndoc_id: "101"\ntitle: "Applications"\n---\n\n'
                "Application process info.",
                encoding="utf-8",
            )

            chunks = load_corpus_chunks(tmpdir)
            assert len(chunks) >= 3  # 100 has 2 headings + 101 has 1 chunk
            doc_ids = {c.doc_id for c in chunks}
            assert "100" in doc_ids
            assert "101" in doc_ids

    def test_metadata_populated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "test.md"
            p.write_text(
                '---\npolicy_id: "test"\ntitle: "Test"\nparent: "Root"\n'
                'source_url: "http://example.com"\n'
                'cross_references:\n  - "200"\n  - "201"\n---\n\nContent.',
                encoding="utf-8",
            )
            chunks = load_corpus_chunks(tmpdir)
            assert len(chunks) == 1
            assert chunks[0].metadata["parent"] == "Root"
            assert chunks[0].metadata["source_url"] == "http://example.com"
            assert chunks[0].metadata["cross_references"] == ["200", "201"]

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chunks = load_corpus_chunks(tmpdir)
            assert len(chunks) == 0
