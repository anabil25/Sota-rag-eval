"""Ingestion orchestrator — runs a plugin pipeline and saves Markdown files with frontmatter."""

from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path

import yaml
from rich.console import Console
from rich.progress import Progress

from retrieve.config import RetrieveConfig
from retrieve.ingest.manifest import (
    build_manifest_entry,
    content_sha256,
    logical_source_id,
    write_corpus_manifest,
)
from retrieve.ingest.plugin import ConvertedDoc, CorpusStats, IngestPlugin
from retrieve.observability import emit_error, emit_progress, step

log = logging.getLogger(__name__)
console = Console()

PLUGINS: dict[str, type[IngestPlugin]] = {}


def _register_plugins():
    """Lazily import and register built-in plugins."""
    if PLUGINS:
        return
    from retrieve.ingest.html_plugin import HtmlPlugin
    from retrieve.ingest.markdown_plugin import MarkdownPlugin
    from retrieve.ingest.pdf_plugin import PdfPlugin

    PLUGINS["html"] = HtmlPlugin
    PLUGINS["markdown"] = MarkdownPlugin
    PLUGINS["pdf"] = PdfPlugin


def get_plugin(name: str, **kwargs) -> IngestPlugin:
    _register_plugins()
    if name not in PLUGINS:
        raise ValueError(f"Unknown plugin '{name}'. Available: {', '.join(PLUGINS)}")
    return PLUGINS[name](**kwargs)


def validate_source_output_paths(source: str, output_dir: str) -> None:
    """Reject local source/output overlap before any generated files are written.

    Resolving both paths catches aliases through symlinks and existing junctions.
    Remote sources are ignored because they do not identify a local filesystem
    path that the ingestion pipeline could recursively rediscover.
    """
    source_path = Path(source).expanduser()
    if not source_path.exists():
        return

    resolved_source = source_path.resolve()
    resolved_output = Path(output_dir).expanduser().resolve()
    if (
        resolved_source == resolved_output
        or resolved_source in resolved_output.parents
        or resolved_output in resolved_source.parents
    ):
        raise ValueError(
            "Ingestion source and output paths overlap after resolution: "
            f"source={resolved_source}, output={resolved_output}. "
            "Use separate sibling directories to prevent recursive ingestion."
        )


def save_doc(doc: ConvertedDoc, output_dir: Path) -> Path:
    """Save a ConvertedDoc as a Markdown file with YAML frontmatter."""
    relative_path_value = str(doc.metadata.get("relative_path") or "").replace("\\", "/")
    if relative_path_value:
        relative_path = Path(relative_path_value)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative_path.suffix.lower() != ".md"
        ):
            raise ValueError(f"Unsafe Markdown output path: {relative_path_value}")
        out_path = output_dir / relative_path
    else:
        parts = doc.policy_id.split("-")
        subfolder = parts[0] if parts[0].isdigit() else ""
        safe_title = doc.title.lower().replace(" ", "_").replace("/", "_")
        safe_title = "".join(c for c in safe_title if c.isalnum() or c in "_-")
        if doc.policy_id and safe_title.startswith(doc.policy_id.lower()):
            stem = safe_title
        elif doc.policy_id == safe_title:
            stem = safe_title
        else:
            stem = f"{doc.policy_id}_{safe_title}" if doc.policy_id else safe_title
        out_path = output_dir / subfolder / f"{stem[:120]}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    document_id = str(doc.metadata.get("document_id") or doc.policy_id).strip()
    if not document_id:
        raise ValueError("Converted document requires a stable document_id or policy_id")

    # Let the YAML serializer quote paths, colons, and embedded quotes safely.
    frontmatter_data: dict[str, object] = {
        "policy_id": doc.policy_id,
        "document_id": document_id,
        "title": doc.title,
        "parent": doc.parent,
        "source_url": doc.source_url,
        "source_id": logical_source_id(doc.source_url, doc.policy_id),
        "content_sha256": content_sha256(doc.markdown),
        "last_ingested": date.today().isoformat(),
    }
    if doc.cross_references:
        frontmatter_data["cross_references"] = list(doc.cross_references)

    serialized = yaml.safe_dump(
        frontmatter_data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    if yaml.safe_load(serialized) != frontmatter_data:
        raise ValueError(f"Frontmatter failed YAML round-trip validation for {doc.policy_id}")

    frontmatter = f"---\n{serialized}---\n\n"

    out_path.write_text(frontmatter + doc.markdown, encoding="utf-8")
    return out_path


def compute_stats(docs: list[ConvertedDoc]) -> CorpusStats:
    """Compute corpus stats — used by SOTA mode to recommend a path."""
    if not docs:
        return CorpusStats()

    total_chars = sum(len(d.markdown) for d in docs)
    total_xrefs = sum(len(d.cross_references) for d in docs)
    categories: dict[str, int] = {}
    for d in docs:
        cat = d.parent or "uncategorized"
        categories[cat] = categories.get(cat, 0) + 1

    return CorpusStats(
        doc_count=len(docs),
        total_chars=total_chars,
        avg_doc_length=total_chars / len(docs),
        cross_ref_count=total_xrefs,
        cross_ref_density=total_xrefs / len(docs),
        categories=categories,
    )


def run_ingest(
    source: str,
    plugin_name: str,
    output_dir: str,
    delay: float = 0.5,
    cfg: RetrieveConfig | None = None,
) -> CorpusStats:
    """Run the full ingestion pipeline: discover → fetch → convert → save."""
    validate_source_output_paths(source, output_dir)

    plugin_kwargs = {}
    if plugin_name == "html":
        plugin_kwargs["delay"] = delay

    plugin = get_plugin(plugin_name, **plugin_kwargs)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 1. Discover
    console.print(f"\n[bold]Discovering pages from [cyan]{source}[/cyan]...[/bold]")
    with step("ingest.discover"):
        pages = plugin.discover(source)
    emit_progress(f"Discovered {len(pages)} pages", stage="ingest.discover", page_count=len(pages))
    console.print(f"  Found [green]{len(pages)}[/green] pages\n")

    if not pages:
        console.print("[red]No pages discovered. Check the source URL/path.[/red]")
        return CorpusStats()

    # 2. Fetch & convert
    docs: list[ConvertedDoc] = []
    failed: list[str] = []
    manifest_entries: list[dict[str, object]] = []

    with step("ingest.fetch_convert"), Progress() as progress:
        task = progress.add_task("Ingesting...", total=len(pages))
        for i, page in enumerate(pages, 1):
            fetched = plugin.fetch(page, source)
            if fetched is None:
                failed.append(page.href)
                emit_error(f"Failed to fetch: {page.href}", stage="ingest.fetch")
                progress.advance(task)
                continue

            doc = plugin.convert(fetched)
            if doc is None:
                failed.append(page.href)
                emit_error(f"Failed to convert: {page.href}", stage="ingest.convert")
                progress.advance(task)
                continue

            # 3. Save
            saved_path = save_doc(doc, out_path)
            docs.append(doc)
            manifest_entries.append(build_manifest_entry(doc, saved_path, out_path))
            emit_progress(
                f"Ingested {doc.policy_id or page.href}",
                stage="ingest.page",
                completed=i,
                total=len(pages),
            )
            progress.advance(task)

            if delay > 0 and plugin_name == "html":
                time.sleep(delay)

    # 4. Validate and record the exact output generation.
    with step("ingest.write_manifest"):
        manifest = write_corpus_manifest(
            out_path,
            manifest_entries,
            failed_sources=failed,
        )
    emit_progress(
        "Corpus manifest written",
        stage="ingest.manifest",
        corpus_fingerprint=manifest["corpus_fingerprint"],
        document_count=manifest["document_count"],
        status=manifest["status"],
    )

    # 5. Corpus stats
    with step("ingest.compute_stats"):
        stats = compute_stats(docs)

    console.print("\n[bold green]Ingestion complete[/bold green]")
    console.print(f"  Documents ingested: [green]{stats.doc_count}[/green]")
    console.print(f"  Avg document length: [cyan]{stats.avg_doc_length:.0f}[/cyan] chars")
    console.print(f"  Cross-references found: [cyan]{stats.cross_ref_count}[/cyan]")
    console.print(f"  Cross-ref density: [cyan]{stats.cross_ref_density:.1f}[/cyan] per doc")
    console.print(f"  Parent sections: [cyan]{len(stats.categories)}[/cyan]")

    if failed:
        console.print(f"\n  [yellow]Failed: {len(failed)} pages[/yellow]")
        emit_progress(
            f"{len(failed)} pages failed",
            stage="ingest.summary",
            failed_count=len(failed),
        )
        for f in failed[:10]:
            console.print(f"    - {f}")

    console.print(f"\n  Output: [cyan]{out_path.resolve()}[/cyan]\n")
    return stats
