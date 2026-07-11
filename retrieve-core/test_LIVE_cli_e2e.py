"""Full end-to-end test — the complete Retrieve vision.

Ingest → Generate eval set → Provision → Index → Run eval → Compare → Teardown

Everything automated via the existing codebase APIs. No manual az CLI calls.
The test calls the same functions that the CLI wraps.

Prerequisites:
  copilot login
  az login
  pip install -e .
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.observability import configure_observability

configure_observability()

POLICIES_DIR = str(Path(__file__).parent.parent / "corpus")
RESULTS: list[dict] = []


def log(step: str, msg: str, status: str = "INFO"):
    print(f"[{status}] {step}: {msg}")
    RESULTS.append({"step": step, "message": msg, "status": status})


def build_config(tmpdir: str) -> RetrieveConfig:
    cfg = RetrieveConfig()
    cfg.db_path = os.path.join(tmpdir, "e2e.db")
    cfg.azure.resource_group = "retrieve-e2e-test"
    cfg.azure.name_prefix = "retve2e"
    cfg.azure.location = "southcentralus"
    cfg.architectures = ["keyword", "hybrid"]
    cfg.corpus.output_dir = os.path.join(tmpdir, "corpus")
    cfg.copilot.model = "gpt-4.1"
    cfg.copilot.timeout = 120.0
    return cfg


def step_1_ingest(cfg: RetrieveConfig):
    """Ingest real Alaska policy corpus via markdown passthrough."""
    log("1_INGEST", f"Ingesting from {POLICIES_DIR}...")
    from retrieve.ingest import run_ingest
    stats = run_ingest(
        source=POLICIES_DIR,
        plugin_name="markdown",
        output_dir=cfg.corpus.output_dir,
    )
    assert stats.doc_count > 0
    log("1_INGEST", f"{stats.doc_count} docs, avg {stats.avg_doc_length:.0f} chars, xref {stats.cross_ref_density:.1f}", "PASS")
    return stats


def step_2_generate(cfg: RetrieveConfig):
    """Generate eval set via real Copilot CLI (10 chunk sample)."""
    log("2_GENERATE", "Generating eval questions via Copilot CLI (10 chunk sample)...")

    # Use a 10-doc sample for speed
    sample_dir = os.path.join(os.path.dirname(cfg.corpus.output_dir), "sample")
    os.makedirs(sample_dir, exist_ok=True)
    all_md = sorted(Path(cfg.corpus.output_dir).rglob("*.md"))[:10]
    for f in all_md:
        rel = f.relative_to(cfg.corpus.output_dir)
        dest = Path(sample_dir) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

    from retrieve.eval.generate import generate_eval_set
    eval_set_id = generate_eval_set(
        corpus_dir=sample_dir,
        version_label="e2e-full-v1",
        cfg=cfg,
        mode="sample",
    )
    assert eval_set_id > 0

    db = RetrieveDB(cfg.db_path)
    questions = db.get_questions(eval_set_id)
    db.close()

    log("2_GENERATE", f"{len(questions)} questions generated across {len(set(q['category'] for q in questions))} categories", "PASS")
    return eval_set_id


def step_3_provision(cfg: RetrieveConfig):
    """Provision Azure resources via the provision orchestrator."""
    log("3_PROVISION", "Provisioning Azure resources...")
    from retrieve.provision import provision_architectures
    provision_architectures(cfg)
    log("3_PROVISION", "Provisioning complete", "PASS")


def step_4_index(cfg: RetrieveConfig):
    """Upload corpus + create search indexes via the indexing orchestrator."""
    log("4_INDEX", "Uploading corpus and creating search indexes...")
    from retrieve.indexing import index_corpus
    index_corpus(cfg)
    log("4_INDEX", "Indexing complete", "PASS")


def step_5_eval_run(cfg: RetrieveConfig):
    """Run the eval set against all provisioned architectures."""
    log("5_EVAL_RUN", "Running evaluation against live search indexes...")
    from retrieve.eval.runner import run_evaluation
    run_evaluation(eval_set_version="e2e-full-v1", cfg=cfg)

    db = RetrieveDB(cfg.db_path)
    runs = db.get_all_completed_runs()
    db.close()

    for r in runs:
        m = r["aggregate_metrics"]
        log("5_EVAL_RUN",
            f"{r['architecture_name']}: nDCG@10={m.get('ndcg_at_10', 0):.3f} "
            f"MRR@10={m.get('mrr_at_10', 0):.3f} "
            f"Recall@10={m.get('recall_at_10', 0):.3f} "
            f"Latency={m.get('avg_latency_ms', 0):.0f}ms",
            "PASS")

    log("5_EVAL_RUN", f"{len(runs)} eval runs completed", "PASS")
    return runs


def step_6_compare(cfg: RetrieveConfig, tmpdir: str):
    """Compare results and export."""
    log("6_COMPARE", "Generating comparison dashboard...")
    from retrieve.eval.compare import compare_runs

    export_path = os.path.join(tmpdir, "comparison.json")
    compare_runs(export_path=export_path, cfg=cfg)

    data = json.loads(Path(export_path).read_text())
    log("6_COMPARE", f"Comparison exported: {len(data)} runs", "PASS")
    return data


def step_7_teardown(cfg: RetrieveConfig):
    """Tear down search resources."""
    log("7_TEARDOWN", "Tearing down search resources...")
    from retrieve.provision.teardown import teardown
    teardown(keep=None, cfg=cfg)
    log("7_TEARDOWN", "Search resources torn down", "PASS")


def step_8_delete_rg(cfg: RetrieveConfig):
    """Delete the entire resource group."""
    log("8_CLEANUP", "Deleting resource group...")
    from retrieve.provision.teardown import delete_resource_group
    delete_resource_group(cfg)
    log("8_CLEANUP", "Resource group deletion initiated", "PASS")


if __name__ == "__main__":
    tmpdir = tempfile.mkdtemp(prefix="retrieve_full_e2e_")
    print(f"\n{'='*60}")
    print(f"RETRIEVE — FULL END-TO-END TEST")
    print(f"{'='*60}")
    print(f"Working dir: {tmpdir}")
    print(f"{'='*60}\n")

    cfg = build_config(tmpdir)

    import traceback

    steps = [
        ("1_INGEST",    lambda: step_1_ingest(cfg)),
        ("2_GENERATE",  lambda: step_2_generate(cfg)),
        ("3_PROVISION", lambda: step_3_provision(cfg)),
        ("4_INDEX",     lambda: step_4_index(cfg)),
        ("5_EVAL_RUN",  lambda: step_5_eval_run(cfg)),
        ("6_COMPARE",   lambda: step_6_compare(cfg, tmpdir)),
        ("7_TEARDOWN",  lambda: step_7_teardown(cfg)),
        ("8_CLEANUP",   lambda: step_8_delete_rg(cfg)),
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

    # Save
    results_path = Path(__file__).parent / "e2e_live_results.json"
    with open(results_path, "w") as f:
        json.dump({"results": RESULTS, "tmpdir": tmpdir, "passes": passes, "fails": fails}, f, indent=2)
    print(f"\n  Results: {results_path}")
