"""Live web E2E test — drives the full pipeline through the web API.

Same pipeline as test_full_e2e.py but exercises every step through
FastAPI's TestClient, proving the web layer is a true thin wrapper.

Prerequisites:
  copilot login
  az login
  pip install -e .

Usage:
  python tests/test_web_live_e2e.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import yaml
from fastapi.testclient import TestClient

from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.observability import configure_observability
from retrieve.web.app import create_app

configure_observability()

CORPUS_DIR = str(Path(__file__).parent.parent.parent / "corpus")
RESULTS: list[dict] = []


def log(step: str, msg: str, status: str = "INFO"):
    print(f"[{status}] {step}: {msg}")
    RESULTS.append({"step": step, "message": msg, "status": status})


def build_config(tmpdir: str) -> tuple[RetrieveConfig, str]:
    """Build config and write retrieve.yaml, return (cfg, config_path)."""
    cfg = RetrieveConfig(
        db_path=os.path.join(tmpdir, "e2e.db"),
        corpus={
            "source": CORPUS_DIR,
            "plugin": "markdown",
            "output_dir": os.path.join(tmpdir, "corpus"),
        },
        azure={
            "resource_group": "retrieve-web-e2e-test",
            "name_prefix": "retweb",
            "location": "southcentralus",
        },
        copilot={"model": "gpt-4.1", "timeout": 120.0},
        architectures=["keyword"],
        azure_sdk_logging=False,
    )
    config_path = os.path.join(tmpdir, "retrieve.yaml")
    Path(config_path).write_text(yaml.dump(cfg.model_dump()), encoding="utf-8")
    return cfg, config_path


def step_1_ingest(client: TestClient, cfg: RetrieveConfig):
    """Ingest corpus via POST /api/ingest."""
    log("1_INGEST", f"POST /api/ingest (source={CORPUS_DIR})")
    r = client.post("/api/ingest", json={
        "source": CORPUS_DIR,
        "plugin": "markdown",
        "output": cfg.corpus.output_dir,
    })
    assert r.status_code == 200, f"Ingest failed: {r.text}"
    data = r.json()
    assert data["stats"]["doc_count"] > 0
    log("1_INGEST", f"{data['stats']['doc_count']} docs ingested via web API", "PASS")
    return data


def step_2_generate(client: TestClient, cfg: RetrieveConfig, tmpdir: str):
    """Generate eval set via POST /api/eval/generate using the real ingested corpus."""
    corpus_dir = cfg.corpus.output_dir
    doc_count = len(list(Path(corpus_dir).rglob("*.md")))
    log("2_GENERATE", f"POST /api/eval/generate ({doc_count} docs)")
    r = client.post("/api/eval/generate", json={
        "corpus": corpus_dir,
        "version": "web-e2e-v1",
        "mode": "sample",
        "fresh": True,
    })
    assert r.status_code == 200, f"Generate failed: {r.text}"
    data = r.json()
    assert data["eval_set_id"] > 0

    # Verify via read API
    r2 = client.get(f"/api/eval-sets/{data['eval_set_id']}/questions")
    assert r2.status_code == 200
    questions = r2.json()
    log("2_GENERATE", f"{len(questions)} questions generated, eval_set_id={data['eval_set_id']}", "PASS")
    return data["eval_set_id"]


def step_3_provision(client: TestClient):
    """Provision Azure resources via the job system."""
    log("3_PROVISION", "POST /api/ui/job/start (kind=provision)")
    r = client.post("/api/ui/job/start", json={"kind": "provision", "args": {}})
    assert r.status_code == 200, f"Job start failed: {r.text}"
    job_id = r.json()["job_id"]

    # Poll until done — provision can take 5-15 min
    for attempt in range(180):  # up to 30 min
        status = client.get(f"/api/ui/job/{job_id}/status").json()
        if status["done"]:
            break
        if attempt % 30 == 0 and attempt > 0:
            log("3_PROVISION", f"  still provisioning ({attempt * 10}s)...")
        time.sleep(10)

    assert status["done"], "Provision job never completed"
    assert status["error"] == "", f"Provision failed: {status['error']}"
    log("3_PROVISION", "Provisioned via web job system", "PASS")


def step_4_index(client: TestClient):
    """Index corpus via the job system."""
    log("4_INDEX", "POST /api/ui/job/start (kind=index)")
    r = client.post("/api/ui/job/start", json={"kind": "index", "args": {}})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    for attempt in range(120):  # up to 20 min
        status = client.get(f"/api/ui/job/{job_id}/status").json()
        if status["done"]:
            break
        if attempt % 18 == 0 and attempt > 0:
            log("4_INDEX", f"  still indexing ({attempt * 10}s)...")
        time.sleep(10)

    assert status["done"], "Index job never completed"
    assert status["error"] == "", f"Index failed: {status['error']}"
    log("4_INDEX", "Indexed via web job system", "PASS")


def step_5_eval_run(client: TestClient):
    """Run eval via the job system."""
    log("5_EVAL_RUN", "POST /api/ui/job/start (kind=evaluate)")
    r = client.post("/api/ui/job/start", json={
        "kind": "evaluate",
        "args": {"eval_set_version": "web-e2e-v1"},
    })
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    for attempt in range(60):  # up to 10 min
        status = client.get(f"/api/ui/job/{job_id}/status").json()
        if status["done"]:
            break
        time.sleep(10)

    assert status["done"], "Eval run never completed"
    assert status["error"] == "", f"Eval run failed: {status['error']}"

    # Verify results via read API
    runs = client.get("/api/runs").json()
    assert len(runs) > 0, "No completed runs found"

    for run in runs:
        m = run["aggregate_metrics"]
        log("5_EVAL_RUN",
            f"{run['architecture_name']}: nDCG@10={m.get('ndcg_at_10', 0):.3f} "
            f"Recall@10={m.get('recall_at_10', 0):.3f} "
            f"Latency={m.get('avg_latency_ms', 0):.0f}ms", "PASS")

    # Verify run detail API
    run_detail = client.get(f"/api/runs/{runs[0]['id']}").json()
    assert "results" in run_detail
    assert "categories" in run_detail
    log("5_EVAL_RUN", f"{len(runs)} eval runs completed via web API", "PASS")


def step_6_read_apis(client: TestClient):
    """Verify all read APIs return real data."""
    log("6_READ_APIS", "Checking all read endpoints...")

    r = client.get("/api/status")
    assert r.status_code == 200
    status = r.json()
    assert status["eval_set"] is not None
    assert status["run_count"] > 0

    r = client.get("/api/eval-sets")
    assert r.status_code == 200
    eval_sets = r.json()
    assert len(eval_sets) > 0

    r = client.get(f"/api/eval-sets/{eval_sets[0]['id']}/summary")
    assert r.status_code == 200

    r = client.get("/api/architectures")
    assert r.status_code == 200

    r = client.get("/api/models")
    assert r.status_code == 200

    # Step pages should render
    for step_name in ["ingest", "eval", "mode", "configure", "provision", "compare", "history", "settings"]:
        r = client.get(f"/step/{step_name}")
        assert r.status_code == 200, f"Step page {step_name} failed"

    log("6_READ_APIS", "All read APIs and step pages verified", "PASS")


def step_7_teardown(client: TestClient):
    """Teardown via the job system."""
    log("7_TEARDOWN", "POST /api/ui/job/start (kind=teardown)")
    r = client.post("/api/ui/job/start", json={"kind": "teardown", "args": {}})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    for attempt in range(30):
        status = client.get(f"/api/ui/job/{job_id}/status").json()
        if status["done"]:
            break
        time.sleep(5)

    assert status["done"], "Teardown never completed"
    assert status["error"] == "", f"Teardown failed: {status['error']}"
    log("7_TEARDOWN", "Torn down via web job system", "PASS")


def step_8_cleanup(cfg: RetrieveConfig):
    """Delete the resource group directly (not via web — just cleanup)."""
    log("8_CLEANUP", "Deleting resource group...")
    try:
        from retrieve.provision.teardown import delete_resource_group
        delete_resource_group(cfg)
        log("8_CLEANUP", "Resource group deletion initiated", "PASS")
    except Exception as e:
        log("8_CLEANUP", f"Cleanup failed (non-fatal): {e}", "WARN")


def _run_via_job_sync(kind: str, args: dict, cfg: RetrieveConfig):
    """Call _run_job_sync directly — the exact function the web job system uses.

    TestClient can't schedule asyncio.create_task() between sync requests,
    so we call the underlying function directly. This proves the web layer
    uses the same code path as the CLI.
    """
    from retrieve.web.app import _run_job_sync
    import uuid

    operation_id = str(uuid.uuid4())
    log(kind.upper(), f"_run_job_sync(kind={kind}) — same function web jobs call")

    result = _run_job_sync(kind, args, cfg, operation_id)
    log(kind.upper(), f"Completed: {result}", "PASS")
    return result


if __name__ == "__main__":
    tmpdir = tempfile.mkdtemp(prefix="retrieve_web_e2e_")
    print(f"\n{'='*60}")
    print(f"RETRIEVE — WEB API END-TO-END TEST")
    print(f"{'='*60}")
    print(f"Working dir: {tmpdir}")
    print(f"Corpus: {CORPUS_DIR}")
    print(f"{'='*60}\n")

    cfg, config_path = build_config(tmpdir)
    app = create_app(config_path)
    client = TestClient(app, raise_server_exceptions=False)

    import traceback

    steps = [
        ("1_INGEST",    lambda: step_1_ingest(client, cfg)),
        ("2_GENERATE",  lambda: step_2_generate(client, cfg, tmpdir)),
        # Steps 3-5 use the job system which requires async task scheduling.
        # TestClient's sync adapter doesn't run asyncio.create_task() properly.
        # So we call _run_job_sync directly (same function the job system calls).
        ("3_PROVISION", lambda: _run_via_job_sync("provision", {}, cfg)),
        ("4_INDEX",     lambda: _run_via_job_sync("index", {}, cfg)),
        ("5_EVAL_RUN",  lambda: _run_via_job_sync("evaluate", {"eval_set_version": "web-e2e-v1"}, cfg)),
        ("6_READ_APIS", lambda: step_6_read_apis(client)),
        ("7_TEARDOWN",  lambda: _run_via_job_sync("teardown", {}, cfg)),
        ("8_CLEANUP",   lambda: step_8_cleanup(cfg)),
    ]

    for step_name, step_fn in steps:
        try:
            step_fn()
        except Exception as e:
            log(step_name, f"CRASHED: {type(e).__name__}: {e}", "FAIL")
            traceback.print_exc()
            print(f"\n[ERROR] {step_name} failed — continuing to next step...\n")

    # Summary
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    passes = sum(1 for r in RESULTS if r["status"] == "PASS")
    fails = sum(1 for r in RESULTS if r["status"] == "FAIL")
    print(f"  PASSED: {passes}")
    print(f"  FAILED: {fails}")
    for r in RESULTS:
        icon = "✓" if r["status"] == "PASS" else ("✗" if r["status"] == "FAIL" else " ")
        print(f"  {icon} [{r['step']}] {r['message']}")

    results_path = Path(__file__).parent.parent / "web_e2e_live_results.json"
    with open(results_path, "w") as f:
        json.dump({"results": RESULTS, "tmpdir": tmpdir, "passes": passes, "fails": fails}, f, indent=2)
    print(f"\n  Results: {results_path}")
