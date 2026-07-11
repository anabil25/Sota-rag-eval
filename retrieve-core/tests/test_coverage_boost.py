"""Extra tests to push coverage above 90% — blob upload, search index helpers, orchestrator."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import ResourceNotFoundError

from retrieve.ingest.manifest import build_manifest_entry, write_corpus_manifest
from retrieve.ingest.plugin import ConvertedDoc
from retrieve.ingest.run import save_doc


def test_blob_credential_binds_hosted_user_assigned_identity(monkeypatch):
    import retrieve.indexing.blob_upload as blob_upload

    monkeypatch.setenv("AZURE_CLIENT_ID", "client-123")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://identity.internal")
    managed = MagicMock()
    cli = MagicMock()
    chain = MagicMock()
    monkeypatch.setattr(blob_upload, "ManagedIdentityCredential", managed)
    monkeypatch.setattr(blob_upload, "AzureCliCredential", cli)
    monkeypatch.setattr(blob_upload, "ChainedTokenCredential", chain)

    blob_upload._build_credential()

    managed.assert_called_once_with(client_id="client-123")
    chain.assert_called_once_with(managed.return_value, cli.return_value)


class TestBlobUpload:
    @staticmethod
    def _write_generation(root: Path, docs: list[ConvertedDoc]) -> dict:
        root.mkdir(parents=True, exist_ok=True)
        entries = []
        for doc in docs:
            output = save_doc(doc, root)
            entries.append(build_manifest_entry(doc, output, root))
        return write_corpus_manifest(root, entries)

    @patch("retrieve.indexing.blob_upload.BlobServiceClient")
    @patch("retrieve.indexing.blob_upload._build_credential")
    def test_upload_corpus(self, mock_cred, mock_blob):
        tmpdir = tempfile.mkdtemp()
        corpus = Path(tmpdir) / "corpus"
        self._write_generation(
            corpus,
            [
                ConvertedDoc("100", "Doc 1", "", "https://example.test/100.htm", "Content 1"),
                ConvertedDoc("101", "Doc 2", "", "https://example.test/101.htm", "Content 2"),
            ],
        )

        mock_container = MagicMock()
        mock_container.download_blob.side_effect = ResourceNotFoundError("not found")
        mock_blob.return_value.get_container_client.return_value = mock_container

        from retrieve.indexing.blob_upload import upload_corpus

        count = upload_corpus(str(corpus), "teststore")
        assert count == 2
        assert mock_container.upload_blob.call_count == 3
        uploaded_names = {call.kwargs["name"] for call in mock_container.upload_blob.call_args_list}
        assert uploaded_names == {
            "100/100_doc_1.md",
            "101/101_doc_2.md",
            "_retrieve/corpus-manifest.json",
        }
        mock_container.delete_blob.assert_not_called()

    @patch("retrieve.indexing.blob_upload.BlobServiceClient")
    @patch("retrieve.indexing.blob_upload._build_credential")
    def test_upload_corpus_dry_run_plans_manifest_bounded_mirror(
        self,
        mock_cred,
        mock_blob,
        tmp_path,
    ):
        shared = ConvertedDoc("100", "Shared", "", "https://example.test/100.htm", "Unchanged")
        remote_root = tmp_path / "remote"
        remote_manifest = self._write_generation(
            remote_root,
            [
                shared,
                ConvertedDoc("099", "Stale", "", "https://example.test/099.htm", "Old"),
            ],
        )
        local_root = tmp_path / "local"
        self._write_generation(
            local_root,
            [
                shared,
                ConvertedDoc("101", "New", "", "https://example.test/101.htm", "New"),
            ],
        )

        mock_container = mock_blob.return_value.get_container_client.return_value
        mock_container.download_blob.return_value.readall.return_value = json.dumps(
            remote_manifest
        ).encode("utf-8")

        from retrieve.indexing.blob_upload import BlobMirrorPlan, upload_corpus

        plan = upload_corpus(str(local_root), "teststore", dry_run=True)

        assert isinstance(plan, BlobMirrorPlan)
        assert plan.uploads == ("101/101_new.md",)
        assert plan.deletes == ("099/099_stale.md",)
        assert plan.unchanged == ("100/100_shared.md",)
        mock_container.upload_blob.assert_not_called()
        mock_container.delete_blob.assert_not_called()

        with pytest.raises(ValueError, match="require an exact dry-run plan"):
            upload_corpus(str(local_root), "teststore")

        synchronized = upload_corpus(
            str(local_root),
            "teststore",
            expected_plan=plan,
        )

        assert synchronized == 2
        mock_container.delete_blob.assert_called_once_with(
            "099/099_stale.md",
            delete_snapshots="include",
        )
        uploaded_names = [call.kwargs["name"] for call in mock_container.upload_blob.call_args_list]
        assert uploaded_names == ["101/101_new.md", "_retrieve/corpus-manifest.json"]

    def test_upload_corpus_rejects_unmanifested_markdown(self, tmp_path):
        (tmp_path / "doc.md").write_text("unmanaged", encoding="utf-8")

        from retrieve.indexing.blob_upload import upload_corpus

        with pytest.raises(ValueError, match="manifest not found"):
            upload_corpus(str(tmp_path), "teststore")

    @patch("retrieve.indexing.blob_upload.BlobServiceClient")
    @patch("retrieve.indexing.blob_upload._build_credential")
    def test_remote_unmanaged_markdown_blocks_mirror(
        self,
        mock_cred,
        mock_blob,
        tmp_path,
    ):
        from types import SimpleNamespace

        local_root = tmp_path / "local"
        self._write_generation(
            local_root,
            [ConvertedDoc("100", "Policy", "", "https://example.test/100.htm", "Body")],
        )
        container = mock_blob.return_value.get_container_client.return_value
        container.download_blob.side_effect = ResourceNotFoundError("not found")
        container.list_blobs.return_value = [SimpleNamespace(name="historical-stale.md")]

        from retrieve.indexing.blob_upload import BlobMirrorPlan, upload_corpus

        plan = upload_corpus(str(local_root), "teststore", dry_run=True)
        assert isinstance(plan, BlobMirrorPlan)
        assert plan.unmanaged == ("historical-stale.md",)

        with pytest.raises(ValueError, match="unmanaged Markdown"):
            upload_corpus(str(local_root), "teststore")
        container.upload_blob.assert_not_called()
        container.delete_blob.assert_not_called()

    def test_upload_corpus_missing_dir(self):
        from retrieve.indexing.blob_upload import upload_corpus

        count = upload_corpus("/nonexistent/path", "teststore")
        assert count == 0

    @patch("retrieve.indexing.blob_upload.BlobServiceClient")
    @patch("retrieve.indexing.blob_upload._build_credential")
    def test_upload_corpus_no_files(self, mock_cred, mock_blob):
        tmpdir = tempfile.mkdtemp()
        from retrieve.indexing.blob_upload import upload_corpus

        count = upload_corpus(tmpdir, "teststore")
        assert count == 0


class TestSearchIndexWaitForIndexer:
    @patch("retrieve.indexing.search_index._search_rest_get")
    @patch("retrieve.indexing.search_index.DefaultAzureCredential")
    def test_wait_for_indexer_success(self, mock_cred, mock_rest_get):
        mock_rest_get.return_value = {
            "lastResult": {
                "status": "success",
                "itemCount": 100,
                "failedItemCount": 0,
                "errors": [],
            }
        }

        from retrieve.indexing.search_index import wait_for_indexer

        result = wait_for_indexer("https://test.search.windows.net", "test-indexer", timeout=5)
        assert result["status"] == "success"
        assert result["item_count"] == 100

    @patch("retrieve.indexing.search_index._search_rest_get")
    @patch("retrieve.indexing.search_index.DefaultAzureCredential")
    def test_wait_for_indexer_timeout(self, mock_cred, mock_rest_get):
        mock_rest_get.return_value = {"lastResult": {"status": "inProgress"}}

        from retrieve.indexing.search_index import wait_for_indexer

        wait_for_indexer("https://test.search.windows.net", "test-indexer", timeout=1)


class TestTeardownEdgeCases:
    def test_teardown_all_kept(self):
        from retrieve.config import RetrieveConfig
        from retrieve.db import RetrieveDB
        from retrieve.provision.teardown import teardown

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        db = RetrieveDB(db_path)
        db.register_architecture("hybrid", {"search_endpoint": "x", "index_name": "x"})
        db.conn.execute("UPDATE architectures SET status = 'provisioned'")
        db.conn.commit()
        db.close()

        cfg = RetrieveConfig()
        cfg.db_path = db_path
        cfg.architectures = ["hybrid"]
        teardown(keep=["hybrid"], cfg=cfg)  # Nothing to tear down


class TestHTMLPluginEdgeCases:
    def test_get_with_waf_block(self):
        from retrieve.ingest.html_plugin import HtmlPlugin

        with patch("retrieve.ingest.html_plugin.requests.Session") as MockSession:
            mock_session = MagicMock()
            resp = MagicMock()
            resp.text = "Request Rejected"
            mock_session.get.return_value = resp
            MockSession.return_value = mock_session

            plugin = HtmlPlugin(max_retries=1)
            plugin._session = mock_session
            result = plugin._get("http://example.com")
            assert result is None

    def test_get_with_exception(self):
        import requests

        from retrieve.ingest.html_plugin import HtmlPlugin

        with patch("retrieve.ingest.html_plugin.requests.Session") as MockSession:
            mock_session = MagicMock()
            mock_session.get.side_effect = requests.RequestException("timeout")
            MockSession.return_value = mock_session

            plugin = HtmlPlugin(max_retries=1)
            plugin._session = mock_session
            result = plugin._get("http://example.com")
            assert result is None
