"""Additional coverage for wizard UI routes, SSE jobs, and stream utilities."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import types

import pytest
from fastapi.testclient import TestClient

from retrieve.db import RetrieveDB
from retrieve.web.app import create_app
from retrieve.web.stream import LogQueue, RichCapture


@pytest.fixture
def wizard_client():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    config_path = os.path.join(tmpdir, "test.yaml")

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(
            "\n".join(
                [
                    f"db_path: {db_path}",
                    "architectures:",
                    "  - hybrid",
                    "  - keyword",
                    "corpus:",
                    "  source: test-source",
                    "  plugin: html",
                    "  output_dir: corpus",
                ]
            )
        )

    db = RetrieveDB(db_path)
    for architecture in ("hybrid", "keyword", "hybrid-reranker"):
        db.register_architecture(
            architecture,
            {
                "search_endpoint": "https://test.search.windows.net",
                "index_name": f"test-{architecture}",
            },
        )
    db.conn.execute("UPDATE architectures SET status = 'active'")
    db.conn.commit()
    eval_id = db.create_eval_set("v1", notes="seed")
    q1 = db.add_question(eval_id, "Q1", "direct_lookup", ["100::0"])
    db.update_eval_set_counts(eval_id)

    run_id = db.create_run(eval_id, "hybrid", "test")
    db.add_result(
        run_id,
        q1,
        ["100::0"],
        {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 1.0},
        50.0,
    )
    db.complete_run(
        run_id,
        {
            "recall_at_5": 1.0,
            "recall_at_10": 1.0,
            "mrr_at_10": 1.0,
            "ndcg_at_10": 1.0,
            "avg_latency_ms": 50.0,
            "failure_count": 0,
            "total_questions": 1,
        },
    )
    db.close()

    app = create_app(config_path)
    with TestClient(app) as client:
        yield client


def _wait_job_done(client: TestClient, job_id: str, timeout: float = 2.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/ui/job/{job_id}/status")
        assert status.status_code == 200
        payload = status.json()
        if payload["done"]:
            return payload
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def test_step_routes_render(wizard_client: TestClient):
    steps = ["ingest", "eval", "mode", "configure", "provision", "compare", "history", "settings"]
    for step in steps:
        resp = wizard_client.get(f"/step/{step}")
        assert resp.status_code == 200
        assert "Retrieve Flow" in resp.text


def test_step_partial_hx(wizard_client: TestClient):
    resp = wizard_client.get("/step/eval", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "Generate Golden Eval Set" in resp.text
    assert "<!DOCTYPE html>" not in resp.text


def test_unknown_step_404(wizard_client: TestClient):
    resp = wizard_client.get("/step/not-a-step")
    assert resp.status_code == 404


def test_ui_session_round_trip(wizard_client: TestClient):
    up = wizard_client.post(
        "/api/ui/session",
        json={"selected_mode": "test", "configure_done": True},
    )
    assert up.status_code == 200
    data = wizard_client.get("/api/ui/session").json()
    assert data["selected_mode"] == "test"
    assert data["configure_done"] is True


def test_ui_session_validation_error(wizard_client: TestClient):
    resp = wizard_client.post("/api/ui/session", json=["bad"])
    assert resp.status_code == 400


def test_api_questions_browse_filters(wizard_client: TestClient):
    resp = wizard_client.get(
        "/api/eval-sets/1/questions/browse?category=direct_lookup&limit=10&offset=0"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1


def test_api_eval_summary_404(wizard_client: TestClient):
    resp = wizard_client.get("/api/eval-sets/999/summary")
    assert resp.status_code == 404


def test_api_eval_preferences_update_validation(wizard_client: TestClient):
    resp = wizard_client.post(
        "/api/eval/preferences",
        json={"scope_key": "default", "preferences": []},
    )
    assert resp.status_code == 400


def test_api_eval_preferences_round_trip(wizard_client: TestClient):
    resp = wizard_client.post(
        "/api/eval/preferences",
        json={"scope_key": "default", "preferences": {"coverage_target": 0.9}},
    )
    assert resp.status_code == 200
    got = wizard_client.get("/api/eval/preferences?scope_key=default")
    assert got.status_code == 200
    assert got.json().get("coverage_target") == 0.9


def test_ui_job_unknown_kind(wizard_client: TestClient):
    start = wizard_client.post("/api/ui/job/start", json={"kind": "unknown-kind", "args": {}})
    assert start.status_code == 400
    assert "unsupported job kind" in start.json()["detail"]


def test_ui_job_requires_kind(wizard_client: TestClient):
    resp = wizard_client.post("/api/ui/job/start", json={"kind": "", "args": {}})
    assert resp.status_code == 400


def test_ui_job_status_and_stream_404(wizard_client: TestClient):
    assert wizard_client.get("/api/ui/job/not-real/status").status_code == 404
    assert wizard_client.get("/api/ui/job/not-real/stream").status_code == 404


def test_ui_job_ingest_branch(monkeypatch: pytest.MonkeyPatch, wizard_client: TestClient):
    from retrieve.ingest import run as ingest_run

    class _Stats:
        doc_count = 10
        avg_doc_length = 123.0
        cross_ref_density = 0.8

    monkeypatch.setattr(ingest_run, "run_ingest", lambda **kwargs: _Stats())

    start = wizard_client.post(
        "/api/ui/job/start",
        json={"kind": "ingest", "args": {"source": "s", "plugin": "html", "output": "out"}},
    )
    job_id = start.json()["job_id"]
    done = _wait_job_done(wizard_client, job_id)
    assert done["error"] == ""
    assert done["result"]["doc_count"] == 10


def test_ui_job_eval_generate_branch(monkeypatch: pytest.MonkeyPatch, wizard_client: TestClient):
    from retrieve.eval import generate as eval_generate

    monkeypatch.setattr(eval_generate, "generate_eval_set", lambda **kwargs: 42)

    start = wizard_client.post(
        "/api/ui/job/start",
        json={"kind": "eval_generate", "args": {"version": "v2"}},
    )
    job_id = start.json()["job_id"]
    done = _wait_job_done(wizard_client, job_id)
    assert done["error"] == ""
    assert done["result"]["eval_set_id"] == 42


def test_ui_job_provision_index_eval_branches(
    monkeypatch: pytest.MonkeyPatch,
    wizard_client: TestClient,
):
    import retrieve.provision as provision
    from retrieve.eval import readiness
    from retrieve.eval import runner as eval_runner
    from retrieve.indexing import run as indexing_run

    monkeypatch.setattr(
        provision,
        "provision_architectures",
        lambda cfg, config_path="retrieve.yaml": None,
    )
    monkeypatch.setattr(indexing_run, "index_corpus", lambda cfg: None)
    monkeypatch.setattr(eval_runner, "run_evaluation", lambda **kwargs: None)
    monkeypatch.setattr(
        readiness,
        "validate_architecture_readiness",
        lambda db, cfg, architecture_names: {},
    )

    for kind in ["provision", "index", "evaluate"]:
        start = wizard_client.post("/api/ui/job/start", json={"kind": kind, "args": {}})
        assert start.status_code == 200
        job_id = start.json()["job_id"]
        done = _wait_job_done(wizard_client, job_id)
        assert done["error"] == ""
        session = wizard_client.get("/api/ui/session").json()
        if kind in {"provision", "index"}:
            assert session["provision_done"] is True
            assert session["run_done"] is False
            assert session["compare_done"] is False
        else:
            assert session["run_done"] is True
            assert session["compare_done"] is False


def test_ui_embedding_config_from_custom_vectorizer_selection():
    from retrieve.web.app import _embedding_config_from_ui

    config = _embedding_config_from_ui(
        {
            "selected_vectorizer": "custom_web_api",
            "selected_embedding": "bge-m3",
            "custom_embedding_uri": "https://embeddings.example.com/vectorize",
            "custom_embedding_dimensions": "1024",
            "custom_embedding_header_name": "x-api-key",
        }
    )

    assert config == {
        "embedding_model": "bge-m3",
        "vectorizer_source": "custom_web_api",
        "custom_embedding_uri": "https://embeddings.example.com/vectorize",
        "custom_embedding_header_name": "x-api-key",
        "custom_embedding_dimensions": 1024,
    }


def test_ui_embedding_config_from_foundry_deployed_cohere():
    from retrieve.web.app import _embedding_config_from_ui

    config = _embedding_config_from_ui(
        {
            "selected_vectorizer": "foundry_deployed",
            "selected_embedding": "cohere-embed-v3",
            "foundry_deployed_uri": "https://cohere.example.models.ai.azure.com",
            "foundry_deployed_model_name": "Cohere-embed-v3-english",
            "foundry_deployed_dimensions": "1024",
            "foundry_deployed_vectorizer_source": "foundry_cohere",
        }
    )

    assert config == {
        "embedding_model": "cohere-embed-v3",
        "vectorizer_source": "foundry_cohere",
        "cohere_uri": "https://cohere.example.models.ai.azure.com",
        "cohere_model_name": "Cohere-embed-v3-english",
    }


def test_ui_embedding_config_from_foundry_deployed_custom():
    from retrieve.web.app import _embedding_config_from_ui

    config = _embedding_config_from_ui(
        {
            "selected_vectorizer": "foundry_deployed",
            "selected_embedding": "bge-m3",
            "foundry_deployed_uri": "https://bge.example.com/vectorize",
            "foundry_deployed_model_name": "bge-m3-adapter",
            "foundry_deployed_dimensions": "1024",
            "foundry_deployed_vectorizer_source": "custom_web_api",
            "custom_embedding_header_name": "x-api-key",
        }
    )

    assert config == {
        "embedding_model": "bge-m3",
        "vectorizer_source": "custom_web_api",
        "custom_embedding_uri": "https://bge.example.com/vectorize",
        "custom_embedding_header_name": "x-api-key",
        "custom_embedding_dimensions": 1024,
    }


def test_foundry_embedding_api_routes(monkeypatch: pytest.MonkeyPatch, wizard_client: TestClient):
    import retrieve.foundry as foundry

    monkeypatch.setattr(
        foundry,
        "list_deployed_foundry_embeddings",
        lambda resource_group, workspace_name: {
            "items": [
                {
                    "name": "bge-m3-adapter",
                    "uri": "https://bge.example.com/vectorize",
                    "dimensions": 1024,
                }
            ],
            "errors": [],
        },
    )
    monkeypatch.setattr(
        foundry,
        "search_foundry_embedding_catalog",
        lambda query="": {
            "items": [
                {
                    "name": "Cohere-embed-v3-english",
                    "model_id": "azureml://registries/azureml-cohere/models/Cohere-embed-v3-english",
                    "deployable": True,
                }
            ],
            "errors": [],
        },
    )

    deployed = wizard_client.get(
        "/api/foundry/embeddings/deployed?resource_group=rg&workspace_name=ws"
    )
    assert deployed.status_code == 200
    assert deployed.json()["items"][0]["name"] == "bge-m3-adapter"

    catalog = wizard_client.get("/api/foundry/embeddings/catalog?query=cohere")
    assert catalog.status_code == 200
    assert catalog.json()["items"][0]["deployable"] is True


def test_ui_job_deploy_foundry_embedding_updates_session(
    monkeypatch: pytest.MonkeyPatch, wizard_client: TestClient
):
    import json as _json

    from retrieve.indexing import advanced as advanced_mod

    monkeypatch.setattr(
        advanced_mod,
        "deploy_foundry_catalog_model",
        lambda **kwargs: {
            "uri": "https://cohere.example.models.ai.azure.com",
            "key": "redacted",
            "model_name": "Cohere-embed-v3-english",
        },
    )

    selected = _json.dumps(
        {
            "name": "Cohere-embed-v3-english",
            "model_id": "azureml://registries/azureml-cohere/models/Cohere-embed-v3-english",
            "dimensions": 1024,
            "vectorizer_source": "foundry_cohere",
        }
    )
    start = wizard_client.post(
        "/api/ui/job/start",
        json={
            "kind": "deploy_foundry_embedding",
            "args": {
                "selected_foundry_catalog_model": selected,
                "foundry_workspace_name": "retrieve-foundry",
                "foundry_resource_group": "rg-retrieve-dev",
                "foundry_endpoint_name": "retrieve-cohere-embed-v3",
            },
        },
    )
    job_id = start.json()["job_id"]
    done = _wait_job_done(wizard_client, job_id)
    assert done["error"] == ""
    assert done["result"]["status"] == "deployed"

    session = wizard_client.get("/api/ui/session").json()
    assert session["selected_vectorizer"] == "foundry_deployed"
    assert session["foundry_deployed_vectorizer_source"] == "foundry_cohere"
    assert session["cohere_uri"] == "https://cohere.example.models.ai.azure.com"


def test_ui_job_evaluate_sota_expands_component_choices(
    monkeypatch: pytest.MonkeyPatch, wizard_client: TestClient
):
    from retrieve.eval import readiness
    from retrieve.eval import runner as eval_runner

    captured: dict = {}

    def _capture_eval(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(eval_runner, "run_evaluation", _capture_eval)
    monkeypatch.setattr(
        readiness,
        "validate_architecture_readiness",
        lambda db, cfg, architecture_names: {},
    )

    wizard_client.post(
        "/api/ui/session",
        json={
            "selected_mode": "sota",
            "selected_sota_path": "government-policy",
            "sotaToggles": {
                "semantic_reranker": ["on", "off"],
            },
        },
    )

    start = wizard_client.post("/api/ui/job/start", json={"kind": "evaluate", "args": {}})
    job_id = start.json()["job_id"]
    done = _wait_job_done(wizard_client, job_id)

    assert done["error"] == ""
    assert captured["mode"] == "sota"
    assert len(captured["variants"]) == 2
    assert {variant["toggles"]["semantic_reranker"] for variant in captured["variants"]} == {
        "on",
        "off",
    }


def test_api_ingest_eval_generate_curate_and_csv(
    monkeypatch: pytest.MonkeyPatch,
    wizard_client: TestClient,
):
    import retrieve.eval.io_csv as io_csv
    from retrieve.eval import curate as curate_mod
    from retrieve.eval import generate as gen_mod

    class _Stats:
        doc_count = 7
        avg_doc_length = 200.0
        cross_ref_density = 0.6

    monkeypatch.setattr("retrieve.ingest.run_ingest", lambda **kwargs: _Stats())
    monkeypatch.setattr(gen_mod, "generate_eval_set", lambda **kwargs: 11)
    monkeypatch.setattr(curate_mod, "regenerate_eval_set", lambda **kwargs: 12)
    monkeypatch.setattr(io_csv, "export_eval_set_to_csv", lambda db, eval_set_id, output: 3)
    monkeypatch.setattr(
        io_csv,
        "import_eval_set_from_csv",
        lambda *args, **kwargs: (13, 2),
    )

    r1 = wizard_client.post("/api/ingest", json={"source": "x", "plugin": "html", "output": "y"})
    assert r1.status_code == 200
    assert r1.json()["stats"]["doc_count"] == 7

    r2 = wizard_client.post("/api/eval/generate", json={"version": "v2"})
    assert r2.status_code == 200
    assert r2.json()["eval_set_id"] == 11

    r3 = wizard_client.post(
        "/api/eval/curate",
        json={"source_version": "latest", "new_version": "v3"},
    )
    assert r3.status_code == 200
    assert r3.json()["eval_set_id"] == 12

    r4 = wizard_client.post(
        "/api/eval/export-csv",
        json={"eval_set": "latest", "output": "out.csv"},
    )
    assert r4.status_code == 200
    assert r4.json()["rows"] == 3

    r5 = wizard_client.post(
        "/api/eval/import-csv",
        json={"input": "in.csv", "version": "v4", "base_eval_set": "latest", "fresh": False},
    )
    assert r5.status_code == 200
    assert r5.json()["eval_set_id"] == 13


def test_api_eval_import_requires_input(wizard_client: TestClient):
    resp = wizard_client.post("/api/eval/import-csv", json={"version": "v4"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_stream_log_queue_round_trip():
    q = LogQueue()
    loop = asyncio.get_running_loop()

    q.put("hello", loop)
    q.done(loop)

    msg = await q.get()
    assert msg == "hello"
    assert await q.get() is None


def test_stream_rich_capture_restores_console():
    seen = []

    class _Orig:
        def print(self, *args, **kwargs):  # noqa: ANN002, ANN003
            seen.append("orig")

    mod = types.SimpleNamespace(console=_Orig())

    def cb(line: str) -> None:
        seen.append(line)

    with RichCapture([mod], cb):
        mod.console.print("line-1")

    # During capture, callback receives the line.
    assert "line-1" in seen

    # After capture, original console is restored.
    mod.console.print("line-2")
    assert "orig" in seen
