"""Tests for ingest/html_plugin.py — HTML ingestion with mocked HTTP."""

from unittest.mock import MagicMock, patch

from retrieve.ingest.html_plugin import HtmlPlugin
from retrieve.ingest.plugin import DiscoveredPage, FetchedPage


class TestHtmlPluginDiscover:
    @patch.object(HtmlPlugin, "_get")
    def test_discover_parses_toc(self, mock_get):
        """Simulates TOC JS discovery."""
        toc_js = """(function() { var toc = [
            {"name": "100 General", "url": "100/100_general.htm"},
            {"name": "100-1 Prudent", "url": "100/100-1_prudent.htm"},
            {"name": "Child Section", "key": "toc_child"}
        ]; window.rh.model.publish(rh.consts("KEY_TEMP_DATA"), toc); })();"""

        child_js = """(function() { var toc = [
            {"name": "101 Applications", "url": "101/101_apps.htm"}
        ]; })();"""

        def side_effect(url):
            resp = MagicMock()
            if "toc.new.js" in url:
                resp.text = toc_js
            elif "toc_child" in url:
                resp.text = child_js
            else:
                return None
            return resp

        mock_get.side_effect = side_effect

        plugin = HtmlPlugin()
        pages = plugin.discover("http://example.com/manuals/admin/")
        assert len(pages) >= 2
        hrefs = {p.href for p in pages}
        assert "100/100_general.htm" in hrefs
        assert "100/100-1_prudent.htm" in hrefs

    @patch.object(HtmlPlugin, "_get")
    def test_discover_handles_no_response(self, mock_get):
        mock_get.return_value = None
        plugin = HtmlPlugin()
        pages = plugin.discover("http://example.com/")
        assert pages == []


class TestHtmlPluginFetch:
    @patch.object(HtmlPlugin, "_get")
    def test_fetch_returns_page(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><h1>Title</h1><p>Content</p></body></html>"
        mock_get.return_value = mock_resp

        plugin = HtmlPlugin()
        page = DiscoveredPage(href="100/100_general.htm", title="General")
        fetched = plugin.fetch(page, "http://example.com/")
        assert fetched is not None
        assert "Content" in fetched.raw_content

    @patch.object(HtmlPlugin, "_get")
    def test_fetch_returns_none_on_failure(self, mock_get):
        mock_get.return_value = None
        plugin = HtmlPlugin()
        page = DiscoveredPage(href="missing.htm", title="Missing")
        assert plugin.fetch(page, "http://example.com/") is None


class TestHtmlPluginConvert:
    def test_converts_html_to_markdown(self):
        plugin = HtmlPlugin()
        fetched = FetchedPage(
            href="100/100-3_confidentiality.htm",
            title="100-3 Confidentiality",
            parent="100 General",
            raw_content="""<html><body>
                <h1>100-3 Confidentiality</h1>
                <p>All case information is confidential.</p>
                <p>See <a href="100-4_civil_rights.htm">100-4</a> for more.</p>
                <script>alert('x')</script>
            </body></html>""",
            source_url="http://example.com/100/100-3_confidentiality.htm",
        )
        doc = plugin.convert(fetched)
        assert doc is not None
        assert doc.policy_id == "100-3"
        assert "confidential" in doc.markdown.lower()
        assert "alert" not in doc.markdown  # scripts stripped
        assert "100-4" in doc.cross_references

    def test_convert_empty_body(self):
        plugin = HtmlPlugin()
        fetched = FetchedPage(
            href="empty.htm",
            title="Empty",
            parent="",
            raw_content="<html></html>",
            source_url="",
        )
        assert plugin.convert(fetched) is None


class TestHtmlPluginDerivePolicy:
    def test_from_filename(self):
        assert HtmlPlugin._derive_policy_id("100/100-3_conf.htm", "") == "100-3"
        assert HtmlPlugin._derive_policy_id("100/100_general.htm", "") == "100"

    def test_from_title_fallback(self):
        assert HtmlPlugin._derive_policy_id("page.htm", "101-5 Where To Submit") == "101-5"

    def test_fallback_to_stem(self):
        assert HtmlPlugin._derive_policy_id("custom_page.htm", "Custom") == "custom_page"


class TestHtmlPluginParserHelpers:
    def test_extract_cross_references(self):
        plugin = HtmlPlugin()
        html = """<a href="100-4_civil.htm">link</a>
                  <a href="http://external.com">ext</a>
                  <a href="#anchor">anchor</a>
                  <a href="101-2_forms.htm#section">forms</a>"""
        refs = plugin._extract_cross_references(html)
        assert "100-4" in refs
        assert "101-2" in refs
        assert len(refs) == 2  # no external or anchor

    def test_convert_to_markdown_rewrites_links(self):
        plugin = HtmlPlugin()
        html = '<body><p>See <a href="100-4.htm">link</a></p></body>'
        md = plugin._convert_to_markdown(html)
        assert ".md" in md
        assert ".htm" not in md
