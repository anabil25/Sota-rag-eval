"""HTML / RoboHelp ingestion plugin.

Ported from alaska-policy-eval/ingest.py — discovers pages via TOC JS files,
fetches .htm pages, converts to Markdown with YAML frontmatter.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from retrieve.ingest.plugin import (
    ConvertedDoc,
    DiscoveredPage,
    FetchedPage,
    IngestPlugin,
)

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


class HtmlPlugin(IngestPlugin):
    """Ingestion plugin for RoboHelp-style HTML policy sites."""

    name = "html"

    def __init__(self, delay: float = 0.5, max_retries: int = 3, timeout: int = 30):
        self.delay = delay
        self.max_retries = max_retries
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _get(self, url: str) -> requests.Response | None:
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
                if "Request Rejected" in resp.text:
                    log.warning("WAF blocked %s (attempt %d)", url, attempt)
                    time.sleep(2**attempt)
                    continue
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding or "utf-8"
                return resp
            except requests.RequestException as e:
                log.warning("Attempt %d/%d failed for %s: %s", attempt, self.max_retries, url, e)
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
        return None

    # ── discover ──────────────────────────────────────────────────────

    def discover(self, source: str) -> list[DiscoveredPage]:
        """Walk RoboHelp TOC JS data tree to find all .htm pages."""
        pages: dict[str, DiscoveredPage] = {}
        visited: set[str] = set()
        queue: list[str] = ["toc"]

        # Set referer for WAF
        self._session.headers["Referer"] = source

        while queue:
            key = queue.pop(0)
            if key in visited:
                continue
            visited.add(key)

            url = f"{source}whxdata/{key}.new.js"
            resp = self._get(url)
            if resp is None:
                continue

            entries = self._parse_toc_js(resp.text)
            for entry in entries:
                name = entry.get("name", "")
                href = entry.get("url", "")
                child_key = entry.get("key", "")

                if href and href.endswith(".htm") and href not in pages:
                    pages[href] = DiscoveredPage(href=href, title=name)

                if child_key and child_key not in visited:
                    queue.append(child_key)

            log.info("TOC %s → %d entries", key, len(entries))
            time.sleep(0.15)

        # Build parent map
        parent_titles: dict[str, str] = {}
        for page in pages.values():
            pid = self._derive_policy_id(page.href, page.title)
            if pid and "-" not in pid:
                parent_titles[pid] = page.title

        for page in pages.values():
            pid = self._derive_policy_id(page.href, page.title)
            if pid and "-" in pid:
                parent_id = pid.split("-")[0]
                page.parent = parent_titles.get(parent_id, parent_id)
            else:
                page.parent = "Administrative Procedures Manual"

        return list(pages.values())

    def _parse_toc_js(self, text: str) -> list[dict]:
        m = re.search(r"var\s+toc\s*=\s*(\[.*?\])\s*;", text, re.DOTALL)
        if not m:
            return []
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            entries = []
            for item in re.finditer(r"\{[^}]*\"name\"\s*:\s*\"([^\"]+)\"[^}]*\}", text):
                block = item.group(0)
                name_m = re.search(r'"name"\s*:\s*"([^"]+)"', block)
                url_m = re.search(r'"url"\s*:\s*"([^"]+)"', block)
                key_m = re.search(r'"key"\s*:\s*"([^"]+)"', block)
                entry: dict = {}
                if name_m:
                    entry["name"] = name_m.group(1)
                if url_m:
                    entry["url"] = url_m.group(1)
                if key_m:
                    entry["key"] = key_m.group(1)
                entries.append(entry)
            return entries

    # ── fetch ─────────────────────────────────────────────────────────

    def fetch(self, page: DiscoveredPage, source: str) -> FetchedPage | None:
        url = urljoin(source, page.href)
        resp = self._get(url)
        if resp is None:
            return None

        return FetchedPage(
            href=page.href,
            title=page.title,
            parent=page.parent,
            raw_content=resp.text,
            source_url=url,
        )

    # ── convert ───────────────────────────────────────────────────────

    def convert(self, page: FetchedPage) -> ConvertedDoc | None:
        content_html = self._extract_content(page.raw_content)
        if not content_html:
            return None

        cross_refs = self._extract_cross_references(content_html)
        markdown = self._convert_to_markdown(content_html)
        if not markdown:
            return None

        policy_id = self._derive_policy_id(page.href, page.title)
        # Filter self-references
        cross_refs = [ref for ref in cross_refs if ref != policy_id]

        return ConvertedDoc(
            policy_id=policy_id,
            title=page.title,
            parent=page.parent,
            source_url=page.source_url,
            markdown=markdown,
            cross_references=cross_refs,
        )

    def _extract_content(self, raw_html: str) -> str:
        soup = BeautifulSoup(raw_html, "html.parser")
        body = soup.find("body")
        if not body:
            return ""
        for tag in body.find_all(["script", "style", "meta", "link"]):
            tag.decompose()
        return str(body)

    def _extract_cross_references(self, content_html: str) -> list[str]:
        refs: set[str] = set()
        soup = BeautifulSoup(content_html, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if href.startswith(("http", "#", "mailto")):
                continue
            page = href.split("#")[0]
            if page.endswith(".htm"):
                fname = Path(page).stem
                m = re.match(r"^(\d+(?:-\d+)?)", fname)
                if m:
                    refs.add(m.group(1))
        return sorted(refs)

    def _convert_to_markdown(self, content_html: str) -> str:
        soup = BeautifulSoup(content_html, "html.parser")
        # Rewrite .htm links to .md
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if not href.startswith("http") and ".htm" in href:
                a_tag["href"] = re.sub(r"\.htm(#|$)", r".md\1", href)

        markdown = md(str(soup), heading_style="ATX", strip=["img"], bullets="-")
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        markdown = re.sub(r"[ \t]+\n", "\n", markdown)
        return markdown.strip()

    @staticmethod
    def _derive_policy_id(href: str, title: str) -> str:
        fname = Path(href).stem
        m = re.match(r"^(\d+(?:-\d+)?)", fname)
        if m:
            return m.group(1)
        m = re.match(r"^(\d+(?:-\d+)?)\s", title)
        if m:
            return m.group(1)
        return fname
