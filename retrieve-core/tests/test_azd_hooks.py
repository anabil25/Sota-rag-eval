"""Tests for thin azd preprovision and postprovision hook workers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from retrieve.ingest.manifest import build_manifest_entry, write_corpus_manifest
from retrieve.ingest.plugin import ConvertedDoc
from retrieve.ingest.run import save_doc

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"retrieve_hook_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preprovision_reuses_persisted_whole_stack_region(monkeypatch):
    hook = _load_script("preprovision")
    values = {
        "AZURE_ENV_NAME": "retrieve-dev",
        "AZURE_LOCATION": "eastus2",
        "RETRIEVE_DEPLOYMENT_REGION": "westus3",
    }
    writes = {}
    monkeypatch.setattr(hook, "get_value", lambda name: values.get(name, ""))
    monkeypatch.setattr(hook, "set_value", writes.__setitem__)

    hook.main()

    assert writes == {"AZURE_LOCATION": "westus3"}


def test_preprovision_rejects_live_resource_group(monkeypatch):
    hook = _load_script("preprovision")
    monkeypatch.setattr(
        hook,
        "get_value",
        lambda name: "ret-test2" if name == "AZURE_ENV_NAME" else "",
    )

    with pytest.raises(RuntimeError, match="protected live resource group"):
        hook.main()


def test_preprovision_persists_selected_region(monkeypatch):
    hook = _load_script("preprovision")
    values = {
        "AZURE_ENV_NAME": "retrieve-dev",
        "AZURE_LOCATION": "centralus",
    }
    writes = {}
    monkeypatch.setattr(hook, "get_value", lambda name: values.get(name, ""))
    monkeypatch.setattr(hook, "set_value", writes.__setitem__)
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    hook.main()

    assert writes["RETRIEVE_DEPLOYMENT_REGION"] == "westus3"
    assert writes["AZURE_LOCATION"] == "westus3"
    assert writes["RETRIEVE_REGION_CANDIDATES"].split(",") == list(hook.REGIONS)


def test_postprovision_skips_when_manifest_is_absent(monkeypatch, tmp_path, capsys):
    hook = _load_script("postprovision")
    monkeypatch.setenv("RETRIEVE_CORPUS_DIR", str(tmp_path))

    hook.upload_canonical_corpus()

    assert "skipping corpus upload" in capsys.readouterr().out


def test_postprovision_uploads_verified_manifest(monkeypatch, tmp_path):
    hook = _load_script("postprovision")
    document = ConvertedDoc(
        policy_id="100",
        title="Policy",
        parent="",
        source_url="https://example.test/100.htm",
        markdown="Policy body",
    )
    output = save_doc(document, tmp_path)
    manifest = write_corpus_manifest(
        tmp_path,
        [build_manifest_entry(document, output, tmp_path)],
    )
    monkeypatch.setenv("RETRIEVE_CORPUS_DIR", str(tmp_path))
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_NAME", "teststore")
    monkeypatch.setenv("AZURE_STORAGE_CORPUS_CONTAINER", "corpus")
    calls = {}
    monkeypatch.setattr(
        hook,
        "upload_corpus",
        lambda corpus, account, container: calls.update(
            corpus=corpus,
            account=account,
            container=container,
        )
        or 1,
    )
    monkeypatch.setattr(hook, "set_azd_value", calls.__setitem__)

    hook.upload_canonical_corpus()

    assert calls["account"] == "teststore"
    assert calls["container"] == "corpus"
    assert calls["RETRIEVE_CORPUS_FINGERPRINT"] == manifest["corpus_fingerprint"]