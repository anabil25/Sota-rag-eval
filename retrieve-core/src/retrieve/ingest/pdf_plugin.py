"""PDF ingestion plugin — extracts text per page, splits by heading structure, converts to Markdown."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from retrieve.ingest.plugin import ConvertedDoc, DiscoveredPage, FetchedPage, IngestPlugin

log = logging.getLogger(__name__)


class PdfPlugin(IngestPlugin):
    """Plugin for ingesting PDF files from a local directory.

    Uses pdfplumber to extract text per page, then reassembles into
    Markdown with heading structure derived from font-size heuristics.
    """

    name = "pdf"

    def discover(self, source: str) -> list[DiscoveredPage]:
        src = Path(source)
        if src.is_file() and src.suffix.lower() == ".pdf":
            # Single PDF file
            title = src.stem.replace("_", " ").replace("-", " ").title()
            return [DiscoveredPage(href=src.name, title=title)]

        if not src.is_dir():
            log.error("PDF plugin expects a directory or .pdf file, got: %s", source)
            return []

        pages = []
        for pdf_file in sorted(src.rglob("*.pdf")):
            rel = pdf_file.relative_to(src).as_posix()
            title = pdf_file.stem.replace("_", " ").replace("-", " ").title()
            pages.append(DiscoveredPage(href=rel, title=title))
        return pages

    def fetch(self, page: DiscoveredPage, source: str) -> FetchedPage | None:
        src = Path(source)
        if src.is_file():
            pdf_path = src
        else:
            pdf_path = src / page.href

        if not pdf_path.exists():
            log.warning("PDF file not found: %s", pdf_path)
            return None

        try:
            import pdfplumber
        except ImportError:
            raise ImportError(
                "pdfplumber is required for PDF ingestion.\n"
                "Install it: pip install pdfplumber"
            )

        try:
            text_parts: list[str] = []
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, pdf_page in enumerate(pdf.pages, 1):
                    page_text = pdf_page.extract_text() or ""
                    if page_text.strip():
                        text_parts.append(f"<!-- page {page_num} -->\n{page_text}")

            if not text_parts:
                log.warning("No text extracted from PDF: %s", pdf_path)
                return None

            raw_content = "\n\n".join(text_parts)
            return FetchedPage(
                href=page.href,
                title=page.title,
                parent=page.parent,
                raw_content=raw_content,
                source_url=page.href,
            )
        except Exception as e:
            log.error("Failed to read PDF %s: %s", pdf_path, e)
            return None

    def convert(self, page: FetchedPage) -> ConvertedDoc | None:
        markdown = self._text_to_markdown(page.raw_content)
        cross_refs = self._extract_cross_references(page.raw_content)
        policy_id = self._derive_policy_id(page.href, page.title)

        return ConvertedDoc(
            policy_id=policy_id,
            title=page.title,
            parent=page.parent,
            source_url=page.source_url,
            markdown=markdown,
            cross_references=cross_refs,
        )

    @staticmethod
    def _text_to_markdown(raw: str) -> str:
        """Convert extracted PDF text to Markdown with heading detection.

        Heuristics for heading detection:
        - Lines that are ALL CAPS and short → H1
        - Lines that start with a numbered pattern (e.g. "1.2 Title") → H2
        - Lines that are short, title-cased, and followed by body text → H3
        """
        lines = raw.split("\n")
        result: list[str] = []
        # Strip page marker comments
        content_lines = [line for line in lines if not line.strip().startswith("<!-- page")]

        for i, line in enumerate(content_lines):
            stripped = line.strip()
            if not stripped:
                result.append("")
                continue

            # ALL CAPS heading (>3 chars, <100 chars, mostly alpha)
            if (
                len(stripped) > 3
                and len(stripped) < 100
                and stripped == stripped.upper()
                and sum(c.isalpha() for c in stripped) > len(stripped) * 0.5
            ):
                result.append(f"\n# {stripped.title()}\n")
                continue

            # Numbered section heading (e.g. "1.2 Some Title", "101-3 Policy Name")
            m = re.match(r"^(\d+(?:[.-]\d+)*)\s+(.+)$", stripped)
            if m and len(stripped) < 120:
                num, title = m.group(1), m.group(2)
                # Deeper numbers → deeper heading level
                depth = num.count(".") + num.count("-") + 1
                level = min(depth + 1, 4)  # H2-H4
                result.append(f"\n{'#' * level} {num} {title}\n")
                continue

            # Regular text
            result.append(stripped)

        text = "\n".join(result)
        # Clean up excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _extract_cross_references(text: str) -> list[str]:
        """Extract policy-style cross-references from text.

        Looks for patterns like "Section 101-3", "Policy 205", "see 100-8".
        """
        refs: set[str] = set()
        for m in re.finditer(r"(?:section|policy|see|refer to)\s+(\d+(?:-\d+)?)", text, re.IGNORECASE):
            refs.add(m.group(1))
        return sorted(refs)

    @staticmethod
    def _derive_policy_id(href: str, title: str) -> str:
        """Derive a policy ID from the filename or title."""
        stem = Path(href).stem
        # Try to extract numeric ID from filename
        m = re.match(r"^(\d+(?:-\d+)?)", stem)
        if m:
            return m.group(1)
        # Fallback to cleaned stem
        return stem.lower().replace(" ", "_")
