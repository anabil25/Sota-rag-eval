"""Tests for thin azd preprovision and postprovision hook workers."""

from __future__ import annotations

import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from retrieve.graphrag_worker.protocol import format_job_result
from retrieve.ingest.manifest import (
    build_manifest_entry,
    load_corpus_manifest,
    write_corpus_manifest,
)
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
    monkeypatch.setenv("RETRIEVE_PROTECTED_RESOURCE_GROUPS", "rg-protected-live")
    hook = _load_script("preprovision")
    monkeypatch.setattr(
        hook,
        "get_value",
        lambda name: "protected-live" if name == "AZURE_ENV_NAME" else "",
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


def test_postprovision_seeds_verified_manifest_in_azure(monkeypatch, tmp_path):
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
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "rg-test")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-test")
    monkeypatch.setenv("AZURE_GRAPHRAG_JOB_NAME", "azgrjtest")
    commands = []
    starts = []
    persisted = {}

    def run(command, operation, **_kwargs):
        commands.append((command, operation))
        return SimpleNamespace(stdout=json.dumps({"properties": {"status": "Succeeded"}}))

    def start(**kwargs):
        starts.append(kwargs)
        return "seed-execution"

    monkeypatch.setattr(hook, "_run_with_auth_retry", run)
    monkeypatch.setattr(hook, "start_container_job", start)
    monkeypatch.setattr(
        hook,
        "_job_logs",
        lambda *_args: format_job_result(
            {
                "kind": "seed",
                "state": "succeeded",
                "document_count": 1,
                "corpus_fingerprint": manifest["corpus_fingerprint"],
            }
        ),
    )
    monkeypatch.setattr(hook, "set_azd_value", persisted.__setitem__)

    hook.upload_canonical_corpus(delays=())

    assert "GRAPH_WORKER_MODE=seed" in starts[0]["environment"]
    assert starts[0]["subscription_id"] == "sub-test"
    assert commands[0][1] == "Azure-side corpus seed status"
    assert persisted["RETRIEVE_CORPUS_FINGERPRINT"] == manifest["corpus_fingerprint"]


def test_postprovision_retries_failed_corpus_seed(monkeypatch, tmp_path):
    hook = _load_script("postprovision")
    document = ConvertedDoc(
        policy_id="100",
        title="Policy",
        parent="",
        source_url="https://example.test/100.htm",
        markdown="Policy body",
    )
    output = save_doc(document, tmp_path)
    write_corpus_manifest(
        tmp_path,
        [build_manifest_entry(document, output, tmp_path)],
    )
    manifest = load_corpus_manifest(tmp_path)
    monkeypatch.setenv("RETRIEVE_CORPUS_DIR", str(tmp_path))
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "rg-test")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-test")
    monkeypatch.setenv("AZURE_GRAPHRAG_JOB_NAME", "azgrjtest")
    starts = iter(("seed-one", "seed-two"))
    statuses = iter(("Failed", "Succeeded"))
    persisted = {}
    sleeps = []

    monkeypatch.setattr(hook, "start_container_job", lambda **_kwargs: next(starts))
    monkeypatch.setattr(
        hook,
        "_json_command",
        lambda *_args, **_kwargs: {"properties": {"status": next(statuses)}},
    )
    log_calls = iter(
        (
            "No replicas found",
            format_job_result(
                {
                    "kind": "seed",
                    "state": "succeeded",
                    "document_count": 1,
                    "corpus_fingerprint": manifest["corpus_fingerprint"],
                }
            ),
        )
    )
    monkeypatch.setattr(hook, "_job_logs", lambda *_args: next(log_calls))
    monkeypatch.setattr(hook, "set_azd_value", persisted.__setitem__)
    monkeypatch.setattr(hook.time, "sleep", sleeps.append)

    hook.upload_canonical_corpus(delays=(), retry_delays=(7,))

    assert sleeps == [7]
    assert "RETRIEVE_CORPUS_FINGERPRINT" in persisted


def test_worker_seed_enforces_manifest_bounded_mirror(monkeypatch, tmp_path):
    from retrieve.graphrag_worker import run_job

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
    plan = run_job.BlobMirrorPlan(
        corpus_fingerprint=manifest["corpus_fingerprint"],
        document_count=1,
        uploads=("100/100_policy.md",),
        deletes=(),
        unchanged=(),
        unmanaged=(),
        remote_manifest_found=False,
    )
    calls = []

    def upload(*args, **kwargs):
        calls.append((args, kwargs))
        return plan if kwargs.get("dry_run") else 1

    monkeypatch.setenv("BUNDLED_CORPUS_DIR", str(tmp_path))
    monkeypatch.setenv("STORAGE_ACCOUNT_NAME", "teststore")
    monkeypatch.setenv("CORPUS_CONTAINER_NAME", "corpus")
    monkeypatch.setattr(run_job, "upload_corpus", upload)

    result = run_job.seed_canonical_corpus()

    assert result["state"] == "succeeded"
    assert result["corpus_fingerprint"] == manifest["corpus_fingerprint"]
    assert calls[1][1]["expected_plan"] == plan


def test_postprovision_approves_search_storage_private_link(monkeypatch):
    hook = _load_script("postprovision")
    values = {
        "AZURE_RESOURCE_GROUP": "rg-test",
        "AZURE_SUBSCRIPTION_ID": "sub-test",
        "AZURE_SEARCH_SERVICE_NAME": "azsrtest",
        "AZURE_STORAGE_ACCOUNT_NAME": "azsttest",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    shared_link_reads = 0
    approvals = []

    def run(command, operation, **_kwargs):
        nonlocal shared_link_reads
        if "shared-private-link-resource" in command:
            shared_link_reads += 1
            status = "Pending" if shared_link_reads == 1 else "Approved"
            return SimpleNamespace(
                stdout=json.dumps(
                    {"properties": {"provisioningState": "Succeeded", "status": status}}
                )
            )
        if "list" in command:
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        {
                            "id": "/storage/privateEndpointConnections/search",
                            "properties": {
                                "privateLinkServiceConnectionState": {"status": "Pending"}
                            },
                        }
                    ]
                )
            )
        approvals.append((command, operation))
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(hook, "_run_with_auth_retry", run)
    monkeypatch.setattr(hook.time, "sleep", lambda _delay: None)

    hook.approve_search_storage_private_link(delays=(0,))

    assert approvals[0][1] == "Search Storage private endpoint approval"


def test_postprovision_publishes_content_addressed_graph_image(monkeypatch, tmp_path):
    hook = _load_script("postprovision")
    values = {
        "AZURE_CONTAINER_REGISTRY_NAME": "azcrtest",
        "AZURE_CONTAINER_REGISTRY_ENDPOINT": "azcrtest.azurecr.io",
        "AZURE_RESOURCE_GROUP": "rg-test",
        "AZURE_GRAPHRAG_JOB_NAME": "azgrjtest",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    calls = []
    persisted = {}
    monkeypatch.setattr(hook, "graph_image_tag", lambda: "abc123")
    monkeypatch.setattr(hook, "graph_build_context", lambda: nullcontext(tmp_path))
    monkeypatch.setattr(
        hook,
        "_run_with_auth_retry",
        lambda command, operation: calls.append((command, operation)),
    )
    monkeypatch.setattr(hook, "set_azd_value", persisted.__setitem__)

    hook.publish_graph_image()

    assert calls[0][0][:3] == ["az", "acr", "build"]
    assert "retrieve-graphrag:abc123" in calls[0][0]
    assert calls[0][0][-1] == str(tmp_path)
    assert calls[1][0][:4] == ["az", "containerapp", "job", "update"]
    assert persisted["RETRIEVE_GRAPHRAG_IMAGE"] == ("azcrtest.azurecr.io/retrieve-graphrag:abc123")


def test_postprovision_stages_minimal_graph_build_context(monkeypatch, tmp_path):
    hook = _load_script("postprovision")
    repo = tmp_path / "repo"
    core = repo / "retrieve-core"
    source = core / "src" / "retrieve"
    corpus = repo / "corpus"
    source.mkdir(parents=True)
    corpus.mkdir()
    (repo / ".dockerignore").write_text(".git\n", encoding="utf-8")
    (core / "Dockerfile.graphrag-job").write_text("FROM scratch\n", encoding="utf-8")
    (core / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (source / "worker.py").write_text("WORKER = True\n", encoding="utf-8")
    (corpus / "policy.md").write_text("# Policy\n", encoding="utf-8")
    (repo / "retrieve.db").write_text("local state", encoding="utf-8")
    (repo / "logs").mkdir()
    (repo / "logs" / "worker.log").write_text("local log", encoding="utf-8")
    monkeypatch.setattr(hook, "REPO_ROOT", repo)

    with hook.graph_build_context() as context:
        relative_files = {
            path.relative_to(context).as_posix()
            for path in context.rglob("*")
            if path.is_file()
        }
        assert relative_files == {
            ".dockerignore",
            "corpus/policy.md",
            "retrieve-core/Dockerfile.graphrag-job",
            "retrieve-core/pyproject.toml",
            "retrieve-core/src/retrieve/worker.py",
        }
        staged_context = context

    assert not staged_context.exists()


def test_postprovision_retries_transient_authorization(monkeypatch):
    hook = _load_script("postprovision")
    results = iter(
        [
            type("Result", (), {"returncode": 1, "stdout": "", "stderr": "AuthorizationFailed"})(),
            type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
        ]
    )
    sleeps = []
    monkeypatch.setattr(hook.subprocess, "run", lambda *args, **kwargs: next(results))
    monkeypatch.setattr(hook.time, "sleep", sleeps.append)

    hook._run_with_auth_retry(["az", "example"], "example", delays=(1,))

    assert sleeps == [1]


def test_postprovision_syncs_localhost_contract_and_selected_architectures(monkeypatch, tmp_path):
    hook = _load_script("postprovision")
    config_path = tmp_path / "retrieve.yaml"
    config_path.write_text(
        "azure:\n  resource_group: rg-old\narchitectures:\n  - hybrid\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RETRIEVE_CONFIG_PATH", str(config_path))
    outputs = {
        "AZURE_SUBSCRIPTION_ID": "sub-test",
        "AZURE_LOCATION": "northcentralus",
        "AZURE_RESOURCE_GROUP": "rg-retrieve-test",
        "AZURE_RESOURCE_TOKEN": "abc123",
        "AZURE_STORAGE_ACCOUNT_NAME": "azsttest",
        "AZURE_STORAGE_CORPUS_CONTAINER": "corpus",
        "RETRIEVE_CORPUS_FINGERPRINT": "f" * 64,
        "AZURE_STORAGE_GRAPH_CONTAINER": "graphrag",
        "AZURE_AI_SERVICES_ENDPOINT": "https://azaitest.cognitiveservices.azure.com/",
        "AZURE_SEARCH_ENDPOINT": "https://azsrtest.search.windows.net",
        "AZURE_OPENAI_CHAT_DEPLOYMENT": "gpt-4.1",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "text-embedding-3-large",
        "AZURE_GRAPHRAG_JOB_NAME": "azgrjtest",
        "AZURE_CONTAINER_APPS_ENVIRONMENT_NAME": "azcaetest",
    }
    for name, value in outputs.items():
        monkeypatch.setenv(name, value)

    from retrieve.db import RetrieveDB

    db = RetrieveDB(tmp_path / "retrieve.db")
    session = {
        "selected_architectures": ["hybrid-reranker", "graphrag"],
    }
    db.upsert_generation_preferences(session, "ui_session")
    db.close()

    hook.sync_local_runtime_contract()

    from retrieve.config import load_config

    cfg = load_config(config_path)
    assert cfg.azure.resource_group == "rg-retrieve-test"
    assert cfg.azure.graph_job_name == "azgrjtest"
    assert cfg.architectures == ["hybrid-reranker", "graphrag"]
    db = RetrieveDB(tmp_path / "retrieve.db")
    graphrag = db.get_architecture("graphrag")
    assert graphrag is not None
    assert graphrag["status"] == "provisioned"
    assert graphrag["config"]["graph_job_name"] == "azgrjtest"
    assert graphrag["config"]["corpus_fingerprint"] == "f" * 64
    assert graphrag["config"]["graph_output_container"] == "graphrag"
    assert db.get_generation_preferences("ui_session")["provision_done"] is True
    db.close()
