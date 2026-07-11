"""Markdown passthrough plugin — accepts pre-existing .md files, validates frontmatter."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from retrieve.ingest.plugin import ConvertedDoc, DiscoveredPage, FetchedPage, IngestPlugin

log = logging.getLogger(__name__)

_FRONTMATTER_START = re.compile(r"^---[ \t]*\r?\n")
_FRONTMATTER = re.compile(
    r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n",
    re.DOTALL,
)


class MarkdownPlugin(IngestPlugin):
    """Plugin for directories of existing Markdown files."""

    name = "markdown"

    def discover(self, source: str) -> list[DiscoveredPage]:
        src = Path(source)
        if not src.is_dir():
            log.error("Markdown plugin expects a directory, got: %s", source)
            return []

        pages = []
        for md_file in sorted(src.rglob("*.md")):
            rel = md_file.relative_to(src).as_posix()
            title = md_file.stem.replace("_", " ").replace("-", " ").title()

            # Try to read title from frontmatter
            try:
                text = md_file.read_text(encoding="utf-8")
                fm = self._parse_frontmatter(text)
                if fm and "title" in fm:
                    title = str(fm["title"])
            except (OSError, UnicodeError, ValueError) as exc:
                log.warning("Could not read valid frontmatter from %s: %s", md_file, exc)

            pages.append(DiscoveredPage(href=rel, title=title))

        return pages

    def fetch(self, page: DiscoveredPage, source: str) -> FetchedPage | None:
        src = Path(source) / page.href
        if not src.exists():
            return None
        return FetchedPage(
            href=page.href,
            title=page.title,
            parent=page.parent,
            raw_content=src.read_text(encoding="utf-8"),
            source_url=str(src.resolve()),
        )

    def convert(self, page: FetchedPage) -> ConvertedDoc | None:
        try:
            fm = self._parse_frontmatter(page.raw_content)
        except ValueError as exc:
            log.error("Rejecting Markdown with malformed frontmatter (%s): %s", page.href, exc)
            return None
        body = self._strip_frontmatter(page.raw_content)

        policy_id = ""
        cross_refs: list[str] = []
        parent = page.parent

        if fm:
            policy_id = fm.get("policy_id", "")
            parent = fm.get("parent", parent)
            cross_refs = fm.get("cross_references", [])

        if not policy_id:
            # Derive from filename
            stem = Path(page.href).stem
            m = re.match(r"^(\d+(?:-\d+)?)", stem)
            policy_id = m.group(1) if m else stem

        return ConvertedDoc(
            policy_id=policy_id,
            title=page.title,
            parent=parent,
            source_url=page.source_url,
            markdown=body,
            cross_references=cross_refs,
        )

    @staticmethod
    def _parse_frontmatter(text: str) -> dict | None:
        if not _FRONTMATTER_START.match(text):
            return None

        m = _FRONTMATTER.match(text)
        if not m:
            raise ValueError("frontmatter is missing a closing '---' delimiter")
        try:
            parsed = yaml.safe_load(m.group(1))
        except yaml.YAMLError as exc:
            raise ValueError(f"frontmatter is not valid YAML: {exc}") from exc
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise ValueError("frontmatter must be a YAML mapping")
        return parsed

    @staticmethod
    def _strip_frontmatter(text: str) -> str:
        return _FRONTMATTER.sub("", text, count=1).lstrip("\r\n")
