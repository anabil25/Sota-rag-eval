"""End-to-end test — ingest → generate → run → compare flow.

Uses the real Alaska policy corpus (markdown passthrough) and
mocked Copilot SDK + Azure Search for the LLM/cloud parts.
"""

import json
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.ingest.run import run_ingest
from retrieve.eval.generate import generate_eval_set
from retrieve.eval.runner import run_evaluation
from retrieve.eval.compare import compare_runs


@pytest.fixture
def e2e_corpus():
    """Create a minimal test corpus with 5 documents."""
    tmpdir = tempfile.mkdtemp()
    corpus = Path(tmpdir) / "corpus"
    corpus.mkdir()

    docs = [
        ("100", "General Information", "APM", "Overview of the program.\n\n# Eligibility\n\nMust be a resident."),
        ("100-1", "Prudent Person", "100 General", "Workers must exercise judgment in all decisions."),
        ("100-3", "Confidentiality", "100 General", "All case information is confidential.\n\nViolations may result in termination."),
        ("101", "Application Process", "APM", "# How to Apply\n\nSubmit form DPA-1.\n\n# Deadlines\n\nWithin 30 days."),
        ("101-1", "Definitions", "101 Applications", "Applicant means a person who has filed an application.\n\nHousehold means all persons living together."),
    ]

    for policy_id, title, parent, content in docs:
        section = policy_id.split("-")[0]
        d = corpus / section
        d.mkdir(exist_ok=True)
        safe = title.lower().replace(" ", "_")
        (d / f"{policy_id}_{safe}.md").write_text(
            f'---\npolicy_id: "{policy_id}"\ntitle: "{title}"\nparent: "{parent}"\n---\n\n{content}',
            encoding="utf-8",
        )

    return tmpdir, str(corpus)


class TestEndToEnd:
    def test_full_pipeline(self, e2e_corpus):
        """Ingest → Generate (mocked) → Run (mocked) → Compare."""
        tmpdir, corpus_dir = e2e_corpus
        db_path = os.path.join(tmpdir, "e2e.db")

        cfg = RetrieveConfig()
        cfg.db_path = db_path
        cfg.architectures = ["keyword", "hybrid"]
        cfg.azure.name_prefix = "test"

        # ── Step 1: Ingest (real — markdown passthrough) ──────────────
        output_dir = os.path.join(tmpdir, "output")
        stats = run_ingest(
            source=corpus_dir,
            plugin_name="markdown",
            output_dir=output_dir,
            cfg=cfg,
        )
        assert stats.doc_count == 5
        assert stats.avg_doc_length > 0

        # ── Step 2: Generate eval set (mocked Copilot SDK) ───────────
        mock_questions = [
            {"question": "What form do I submit to apply?", "category": "direct_lookup",
             "ground_truth_chunk_ids": ["101::1"], "source_doc_id": "101", "reasoning": "Form DPA-1"},
            {"question": "What is the prudent person concept?", "category": "direct_lookup",
             "ground_truth_chunk_ids": ["100-1::0"], "source_doc_id": "100-1", "reasoning": "Defined in the chunk"},
            {"question": "Is case information confidential?", "category": "process_procedure",
             "ground_truth_chunk_ids": ["100-3::0"], "source_doc_id": "100-3", "reasoning": "Confidentiality policy"},
            {"question": "What is the deadline to apply?", "category": "process_procedure",
             "ground_truth_chunk_ids": ["101::2"], "source_doc_id": "101", "reasoning": "30 days"},
            {"question": "Who qualifies as a household member?", "category": "eligibility",
             "ground_truth_chunk_ids": ["101-1::0"], "source_doc_id": "101-1", "reasoning": "Definition"},
        ]

        with patch("retrieve.eval.generate._generate_for_batch", return_value=mock_questions):
            eval_set_id = generate_eval_set(
                corpus_dir=output_dir,
                version_label="e2e-v1",
                questions_per_chunk=1,
                cfg=cfg,
            )
        assert eval_set_id > 0

        # Verify eval set
        db = RetrieveDB(db_path)
        es = db.get_eval_set_by_version("e2e-v1")
        assert es["question_count"] == 5
        cats = json.loads(es["category_counts"])
        assert cats["direct_lookup"] == 2
        assert cats["process_procedure"] == 2
        assert cats["eligibility"] == 1
        db.close()

        # ── Step 3: Run evaluation (mocked search) ────────────────────
        def mock_search(endpoint, index_name, query, **kwargs):
            # Simulate: keyword finds exact matches, misses semantic
            if "keyword" in index_name:
                if "form" in query.lower() or "deadline" in query.lower():
                    return (["101::1", "101::2"], 8.0)
                return (["999::0"], 10.0)
            else:  # hybrid
                return (["101::1", "100-1::0", "100-3::0", "101::2", "101-1::0"], 45.0)

        with patch("retrieve.eval.runner.query_ai_search", side_effect=mock_search), \
             patch("retrieve.eval.runner._classify_misses", new_callable=AsyncMock, return_value=[]):
            run_evaluation(eval_set_version="e2e-v1", cfg=cfg)

        # ── Step 4: Compare ───────────────────────────────────────────
        db = RetrieveDB(db_path)
        runs = db.get_all_completed_runs()
        assert len(runs) == 2

        kw_run = next(r for r in runs if r["architecture_name"] == "keyword")
        hy_run = next(r for r in runs if r["architecture_name"] == "hybrid")

        # Keyword should be worse
        assert kw_run["aggregate_metrics"]["ndcg_at_10"] < hy_run["aggregate_metrics"]["ndcg_at_10"]
        # Hybrid should have near-perfect recall since we return all ground truths
        assert hy_run["aggregate_metrics"]["recall_at_5"] > 0.5

        # Category scores
        kw_cats = db.get_per_category_scores(kw_run["id"])
        hy_cats = db.get_per_category_scores(hy_run["id"])
        assert "direct_lookup" in kw_cats
        assert "direct_lookup" in hy_cats

        # Keyword should have missed queries (low recall)
        assert kw_run["aggregate_metrics"]["miss_count"] > 0 or kw_run["aggregate_metrics"]["recall_at_10"] < 1.0

        db.close()

        # Compare should not crash
        compare_runs(cfg=cfg)

        # Export works
        export_path = os.path.join(tmpdir, "comparison.json")
        compare_runs(export_path=export_path, cfg=cfg)
        data = json.loads(Path(export_path).read_text())
        assert len(data) == 2

    def test_ingest_then_generate_empty_result(self, e2e_corpus):
        """Test that empty generation doesn't crash the pipeline."""
        tmpdir, corpus_dir = e2e_corpus
        db_path = os.path.join(tmpdir, "e2e2.db")
        cfg = RetrieveConfig()
        cfg.db_path = db_path

        with patch("retrieve.eval.generate._generate_for_batch", return_value=[]):
            result = generate_eval_set(
                corpus_dir=corpus_dir,
                version_label="empty",
                questions_per_chunk=1,
                cfg=cfg,
            )
        assert result == -1
