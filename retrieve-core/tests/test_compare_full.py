"""Tests for eval/compare.py — CLI table outputs and HTML generation."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from retrieve.db import RetrieveDB
from retrieve.eval.compare import (
    _generate_html,
    _print_category_breakdown,
    _print_miss_analysis,
    _print_sota_mode_table,
    _print_test_mode_table,
    compare_runs,
)


@pytest.fixture
def db_with_runs():
    """DB with test and SOTA mode runs."""
    path = os.path.join(tempfile.gettempdir(), f"test_cmp_full_{os.getpid()}.db")
    db = RetrieveDB(path)

    eid = db.create_eval_set("v1")
    q1 = db.add_question(eid, "What form?", "direct_lookup", ["100::0"])
    q2 = db.add_question(eid, "How long?", "process_procedure", ["101::0"])
    db.update_eval_set_counts(eid)

    # Test mode runs
    r1 = db.create_run(eid, "keyword", "test")
    db.add_result(
        r1,
        q1,
        ["100::0"],
        {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 1.0},
        8.0,
    )
    db.add_result(
        r1,
        q2,
        ["999"],
        {"recall_at_5": 0.0, "recall_at_10": 0.0, "mrr_at_10": 0.0, "ndcg_at_10": 0.0},
        7.0,
        "vocabulary_mismatch",
        "different terms",
    )
    db.complete_run(
        r1,
        {
            "recall_at_5": 0.5,
            "recall_at_10": 0.5,
            "mrr_at_10": 0.5,
            "ndcg_at_10": 0.5,
            "avg_latency_ms": 7.5,
            "failure_count": 1,
            "total_questions": 2,
        },
    )

    r2 = db.create_run(eid, "hybrid", "test")
    db.add_result(
        r2,
        q1,
        ["100::0"],
        {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 1.0},
        45.0,
    )
    db.add_result(
        r2,
        q2,
        ["101::0"],
        {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 1.0},
        50.0,
    )
    db.complete_run(
        r2,
        {
            "recall_at_5": 1.0,
            "recall_at_10": 1.0,
            "mrr_at_10": 1.0,
            "ndcg_at_10": 1.0,
            "avg_latency_ms": 47.5,
            "failure_count": 0,
            "total_questions": 2,
        },
    )

    # SOTA mode run
    r3 = db.create_run(eid, "hybrid-no-reranker", "sota")
    db.add_result(
        r3,
        q1,
        ["100::0"],
        {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 0.9},
        30.0,
    )
    db.add_result(
        r3,
        q2,
        ["101::0"],
        {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 0.8},
        32.0,
    )
    db.complete_run(
        r3,
        {
            "recall_at_5": 1.0,
            "recall_at_10": 1.0,
            "mrr_at_10": 1.0,
            "ndcg_at_10": 0.85,
            "avg_latency_ms": 31.0,
            "failure_count": 0,
            "total_questions": 2,
        },
    )

    yield db

    db.close()
    try:
        os.unlink(path)
    except OSError:
        pass


class TestPrintTestModeTable:
    def test_prints_without_error(self, db_with_runs):
        runs = db_with_runs.get_all_completed_runs()
        test_runs = [r for r in runs if r["mode"] == "test"]
        # Should not raise
        _print_test_mode_table(test_runs)


class TestPrintSOTAModeTable:
    def test_prints_without_error(self, db_with_runs):
        runs = db_with_runs.get_all_completed_runs()
        _print_sota_mode_table(runs)

    def test_empty_runs(self):
        _print_sota_mode_table([])


class TestPrintCategoryBreakdown:
    def test_prints_without_error(self, db_with_runs):
        runs = db_with_runs.get_all_completed_runs()
        _print_category_breakdown(db_with_runs, runs)


class TestPrintFailureAnalysis:
    def test_prints_failures(self, db_with_runs):
        runs = db_with_runs.get_all_completed_runs()
        _print_miss_analysis(db_with_runs, runs)


class TestGenerateHTML:
    def test_generates_valid_html(self, db_with_runs):
        runs = db_with_runs.get_all_completed_runs()
        html = _generate_html(runs, db_with_runs)
        assert "<!DOCTYPE html>" in html
        assert "Retrieve" in html
        assert "keyword" in html
        assert "hybrid" in html
        assert "nDCG@10" in html
        assert "Per-Category" in html
        assert "Miss Analysis" in html

    def test_html_contains_delta_column(self, db_with_runs):
        runs = db_with_runs.get_all_completed_runs()
        html = _generate_html(runs, db_with_runs)
        assert "Δ nDCG" in html

    def test_html_contains_cost_column(self, db_with_runs):
        runs = db_with_runs.get_all_completed_runs()
        html = _generate_html(runs, db_with_runs)
        assert "Est. Cost" in html


class TestCompareRuns:
    def test_compare_all(self, db_with_runs):
        cfg = RetrieveConfig()
        cfg.db_path = db_with_runs.path
        compare_runs(cfg=cfg)

    def test_compare_specific_ids(self, db_with_runs):
        cfg = RetrieveConfig()
        cfg.db_path = db_with_runs.path
        compare_runs(run_ids=[1, 2], cfg=cfg)

    def test_compare_with_export_json(self, db_with_runs):
        cfg = RetrieveConfig()
        cfg.db_path = db_with_runs.path
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        compare_runs(export_path=path, cfg=cfg)
        data = json.loads(Path(path).read_text())
        assert len(data) >= 2
        os.unlink(path)

    def test_compare_with_web(self, db_with_runs):
        cfg = RetrieveConfig()
        cfg.db_path = db_with_runs.path
        with patch("webbrowser.open"):
            compare_runs(open_web=True, cfg=cfg)
            # Verify HTML file was created
            assert Path("retrieve-dashboard.html").exists()
            Path("retrieve-dashboard.html").unlink()

    def test_compare_empty_db(self):
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "empty.db")
        cfg = RetrieveConfig()
        cfg.db_path = db_path
        # Should not crash
        compare_runs(cfg=cfg)


from retrieve.config import RetrieveConfig
