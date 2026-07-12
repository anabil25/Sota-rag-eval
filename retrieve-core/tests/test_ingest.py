"""Tests for ingest/ — plugin interface, markdown plugin, and orchestrator."""

import hashlib
import tempfile
from pathlib import Path

import pytest
import yaml

from retrieve.ingest.manifest import (
    build_manifest_entry,
    content_sha256,
    load_corpus_manifest,
    logical_source_id,
    write_corpus_manifest,
)
from retrieve.ingest.markdown_plugin import MarkdownPlugin
from retrieve.ingest.plugin import (
    ConvertedDoc,
    DiscoveredPage,
    FetchedPage,
    IngestPlugin,
)
from retrieve.ingest.run import (
    compute_stats,
    get_plugin,
    run_ingest,
    save_doc,
    validate_source_output_paths,
)


class TestPluginInterface:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            IngestPlugin()

    def test_discovered_page_defaults(self):
        p = DiscoveredPage(href="test.htm", title="Test")
        assert p.parent == ""
        assert p.metadata == {}

    def test_converted_doc_defaults(self):
        d = ConvertedDoc(
            policy_id="100",
            title="Test",
            parent="Root",
            source_url="http://example.com",
            markdown="Content",
        )
        assert d.cross_references == []
        assert d.metadata == {}


class TestMarkdownPlugin:
    def test_discover(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "doc1.md").write_text("# Doc 1\nContent", encoding="utf-8")
            (Path(tmpdir) / "sub").mkdir()
            (Path(tmpdir) / "sub" / "doc2.md").write_text("# Doc 2\nContent", encoding="utf-8")

            plugin = MarkdownPlugin()
            pages = plugin.discover(tmpdir)
            assert len(pages) == 2
            hrefs = {p.href for p in pages}
            assert "doc1.md" in hrefs

    def test_discover_reads_frontmatter_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "doc.md").write_text(
                '---\ntitle: "My Custom Title"\n---\n\nContent',
                encoding="utf-8",
            )
            plugin = MarkdownPlugin()
            pages = plugin.discover(tmpdir)
            assert pages[0].title == "My Custom Title"

    def test_discover_not_directory(self):
        plugin = MarkdownPlugin()
        pages = plugin.discover("nonexistent_path")
        assert pages == []

    def test_fetch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "doc.md").write_text("Content here", encoding="utf-8")
            plugin = MarkdownPlugin()
            page = DiscoveredPage(href="doc.md", title="Doc")
            fetched = plugin.fetch(page, tmpdir)
            assert fetched is not None
            assert fetched.raw_content == "Content here"
            assert fetched.source_url == "doc.md"

    def test_fetch_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = MarkdownPlugin()
            page = DiscoveredPage(href="missing.md", title="Missing")
            assert plugin.fetch(page, tmpdir) is None

    def test_convert_with_frontmatter(self):
        plugin = MarkdownPlugin()
        fetched = FetchedPage(
            href="100_general.md",
            title="General",
            parent="",
            raw_content=(
                '---\npolicy_id: "100"\nparent: "APM"\n'
                'cross_references:\n  - "101"\n---\n\nBody text.'
            ),
            source_url="/path/to/100_general.md",
        )
        doc = plugin.convert(fetched)
        assert doc is not None
        assert doc.policy_id == "100"
        assert doc.parent == "APM"
        assert doc.cross_references == ["101"]
        assert doc.markdown == "Body text."

    def test_convert_without_frontmatter(self):
        plugin = MarkdownPlugin()
        fetched = FetchedPage(
            href="100-3_something.md",
            title="Something",
            parent="",
            raw_content="Just plain content.",
            source_url="/path",
        )
        doc = plugin.convert(fetched)
        assert doc is not None
        assert doc.policy_id == "100-3"  # derived from filename
        assert doc.markdown == "Just plain content."

    def test_convert_rejects_malformed_frontmatter(self):
        plugin = MarkdownPlugin()
        fetched = FetchedPage(
            href="broken.md",
            title="Broken",
            parent="",
            raw_content='---\nsource_url: "C:\\Users\\policy\\source.md"\n---\n\nBody text.',
            source_url="/path/to/broken.md",
        )

        assert plugin.convert(fetched) is None


class TestSaveDoc:
    def test_saves_with_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            doc = ConvertedDoc(
                policy_id="100-3",
                title="Confidentiality",
                parent="100 General",
                source_url="http://example.com/100-3.htm",
                markdown="# Confidentiality\n\nPolicy text.",
                cross_references=["100-4", "100-5"],
            )
            out = save_doc(doc, Path(tmpdir))
            assert out.exists()
            content = out.read_text(encoding="utf-8")
            frontmatter = yaml.safe_load(content.split("---", 2)[1])
            assert frontmatter["policy_id"] == "100-3"
            assert frontmatter["title"] == "Confidentiality"
            assert frontmatter["cross_references"] == ["100-4", "100-5"]
            assert frontmatter["source_id"] == logical_source_id(doc.source_url, doc.policy_id)
            assert frontmatter["content_sha256"] == content_sha256(doc.markdown)
            assert "# Confidentiality" in content

    def test_windows_source_path_round_trips_through_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_url = r"C:\Policy\100-3.md"
            doc = ConvertedDoc(
                policy_id="100-3",
                title='Confidentiality: "Protected"',
                parent="100 General",
                source_url=source_url,
                markdown="Policy text.",
                cross_references=["100-4", "100-5"],
            )

            out = save_doc(doc, Path(tmpdir))
            content = out.read_text(encoding="utf-8")
            frontmatter = yaml.safe_load(content.split("---", 2)[1])

            assert frontmatter["source_url"] == source_url
            assert frontmatter["title"] == doc.title
            assert frontmatter["cross_references"] == doc.cross_references

    def test_saves_in_subfolder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            doc = ConvertedDoc(
                policy_id="101-2",
                title="Forms",
                parent="101",
                source_url="http://example.com",
                markdown="Forms content.",
            )
            out = save_doc(doc, Path(tmpdir))
            assert "101" in str(out.parent)


class TestSourceOutputValidation:
    def test_rejects_same_directory(self, tmp_path):
        with pytest.raises(ValueError, match="overlap"):
            validate_source_output_paths(str(tmp_path), str(tmp_path))

    def test_rejects_output_inside_source(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()

        with pytest.raises(ValueError, match="overlap"):
            validate_source_output_paths(str(source), str(source / "generated"))

    def test_rejects_source_inside_output(self, tmp_path):
        output = tmp_path / "output"
        source = output / "source"
        source.mkdir(parents=True)

        with pytest.raises(ValueError, match="overlap"):
            validate_source_output_paths(str(source), str(output))

    def test_rejects_resolved_symlink_overlap(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        alias = tmp_path / "alias"
        try:
            alias.symlink_to(source, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"Directory symlinks are unavailable: {exc}")

        with pytest.raises(ValueError, match="overlap"):
            validate_source_output_paths(str(alias), str(source / "generated"))

    def test_allows_separate_sibling_directories(self, tmp_path):
        source = tmp_path / "source"
        output = tmp_path / "output"
        source.mkdir()

        validate_source_output_paths(str(source), str(output))


class TestCorpusManifest:
    @staticmethod
    def _save_generation(root: Path, docs: list[ConvertedDoc], failed=None):
        entries = []
        for doc in docs:
            output = save_doc(doc, root)
            entries.append(build_manifest_entry(doc, output, root))
        return write_corpus_manifest(root, entries, failed_sources=failed)

    def test_fingerprint_is_stable_across_output_roots(self, tmp_path):
        doc = ConvertedDoc(
            policy_id="100-3",
            title="Confidentiality",
            parent="100 General",
            source_url="https://example.test/100/100-3.htm#section",
            markdown="Policy text.\n",
        )
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()

        first_manifest = self._save_generation(first, [doc])
        second_manifest = self._save_generation(second, [doc])

        assert first_manifest["corpus_fingerprint"] == second_manifest["corpus_fingerprint"]
        assert (
            first_manifest["documents"][0]["graphrag_document_id"]
            == (second_manifest["documents"][0]["graphrag_document_id"])
        )
        assert len(first_manifest["documents"][0]["graphrag_document_id"]) == 128
        assert first_manifest["documents"][0]["source_url"] == (
            "https://example.test/100/100-3.htm"
        )
        assert load_corpus_manifest(first)["document_count"] == 1

    def test_graphrag_document_id_uses_text_mode_newlines(self, tmp_path):
        doc = ConvertedDoc(
            policy_id="doc-1",
            title="Document",
            parent="",
            source_url="https://example.test/doc-1",
            markdown="First line\r\nSecond line\r\n",
        )
        output = tmp_path / "doc-1.md"
        output.write_bytes(doc.markdown.encode("utf-8"))

        entry = build_manifest_entry(doc, output, tmp_path)
        expected = hashlib.sha512(
            b"First line\nSecond line\n",
            usedforsecurity=False,
        ).hexdigest()

        assert entry["graphrag_document_id"] == expected

    def test_manifest_rejects_stale_markdown(self, tmp_path):
        doc = ConvertedDoc("100", "Policy", "", "https://example.test/100.htm", "Body")
        output = save_doc(doc, tmp_path)
        (tmp_path / "stale.md").write_text("stale", encoding="utf-8")

        with pytest.raises(ValueError, match="stale/unmanaged"):
            write_corpus_manifest(
                tmp_path,
                [build_manifest_entry(doc, output, tmp_path)],
            )

    def test_manifest_rejects_duplicate_sources(self, tmp_path):
        source = "https://example.test/shared.htm"
        docs = [
            ConvertedDoc("100", "First", "", source, "First body"),
            ConvertedDoc("101", "Second", "", source, "Second body"),
        ]
        entries = []
        for doc in docs:
            output = save_doc(doc, tmp_path)
            entries.append(build_manifest_entry(doc, output, tmp_path))

        with pytest.raises(ValueError, match="duplicate source_id"):
            write_corpus_manifest(tmp_path, entries)

    def test_incomplete_manifest_cannot_be_loaded_for_upload(self, tmp_path):
        doc = ConvertedDoc("100", "Policy", "", "https://example.test/100.htm", "Body")
        self._save_generation(tmp_path, [doc], failed=["missing.htm"])

        with pytest.raises(ValueError, match="incomplete"):
            load_corpus_manifest(tmp_path)

        assert load_corpus_manifest(tmp_path, require_complete=False)["status"] == "incomplete"

    def test_manifest_detects_file_tampering(self, tmp_path):
        doc = ConvertedDoc("100", "Policy", "", "https://example.test/100.htm", "Body")
        self._save_generation(tmp_path, [doc])
        path = next(tmp_path.rglob("*.md"))
        path.write_text("tampered", encoding="utf-8")

        with pytest.raises(ValueError, match="hash mismatch"):
            load_corpus_manifest(tmp_path)

    def test_markdown_relative_paths_make_duplicate_policy_labels_unique(self, tmp_path):
        source = tmp_path / "source"
        output = tmp_path / "output"
        for relative in ("602/602-1_a.md", "602/602-1_b.md"):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                '---\npolicy_id: "602-1"\ntitle: "Eligibility"\n---\n\nBody',
                encoding="utf-8",
            )

        stats = run_ingest(str(source), "markdown", str(output), delay=0)
        manifest = load_corpus_manifest(output)

        assert stats.doc_count == 2
        assert {entry["document_id"] for entry in manifest["documents"]} == {
            "602/602-1_a",
            "602/602-1_b",
        }
        assert (output / "602" / "602-1_a.md").is_file()
        assert (output / "602" / "602-1_b.md").is_file()


class TestComputeStats:
    def test_basic_stats(self):
        docs = [
            ConvertedDoc("100", "A", "", "", "x" * 100, ["101", "102"]),
            ConvertedDoc("101", "B", "", "", "y" * 200, ["100"]),
            ConvertedDoc("102", "C", "Section", "", "z" * 300, []),
        ]
        stats = compute_stats(docs)
        assert stats.doc_count == 3
        assert stats.total_chars == 600
        assert stats.avg_doc_length == 200.0
        assert stats.cross_ref_count == 3
        assert stats.cross_ref_density == 1.0

    def test_empty_corpus(self):
        stats = compute_stats([])
        assert stats.doc_count == 0
        assert stats.avg_doc_length == 0.0


class TestGetPlugin:
    def test_get_html(self):
        plugin = get_plugin("html")
        assert plugin.name == "html"

    def test_get_markdown(self):
        plugin = get_plugin("markdown")
        assert plugin.name == "markdown"

    def test_get_unknown(self):
        with pytest.raises(ValueError, match="Unknown plugin"):
            get_plugin("nonexistent")
