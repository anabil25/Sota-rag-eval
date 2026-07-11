"""Tests for eval/compare.py — dashboard output and export."""

import json
import tempfile
import os
from pathlib import Path
import pytest
from retrieve.db import RetrieveDB
from retrieve.eval.compare import compare_runs, _export_csv, _export_json


@pytest.fixture
def populated_db():
    """DB with two completed runs for comparison testing."""
    path = os.path.join(tempfile.gettempdir(), f"test_compare_{os.getpid()}.db")
    db = RetrieveDB(path)

    eid = db.create_eval_set("v1")
    q1 = db.add_question(eid, "What form?", "direct_lookup", ["100::0"])
    q2 = db.add_question(eid, "How long?", "process_procedure", ["101::0"])
    q3 = db.add_question(eid, "Who qualifies?", "cross_document", ["102::0", "103::0"])
    db.update_eval_set_counts(eid)

    # Run 1: keyword
    r1 = db.create_run(eid, "keyword", "test")
    db.add_result(r1, q1, ["100::0"], {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 1.0}, 8.0)
    db.add_result(r1, q2, ["999::0"], {"recall_at_5": 0.0, "recall_at_10": 0.0, "mrr_at_10": 0.0, "ndcg_at_10": 0.0}, 7.0, failure_type="vocabulary_mismatch")
    db.add_result(r1, q3, ["999::0"], {"recall_at_5": 0.0, "recall_at_10": 0.0, "mrr_at_10": 0.0, "ndcg_at_10": 0.0}, 9.0, failure_type="cross_ref_miss")
    db.complete_run(r1, {
        "recall_at_5": 0.33, "recall_at_10": 0.33, "mrr_at_10": 0.33, "ndcg_at_10": 0.33,
        "avg_latency_ms": 8.0, "failure_count": 2, "total_questions": 3,
    })

    # Run 2: hybrid
    r2 = db.create_run(eid, "hybrid", "test")
    db.add_result(r2, q1, ["100::0"], {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 1.0}, 45.0)
    db.add_result(r2, q2, ["101::0"], {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 1.0}, 50.0)
    db.add_result(r2, q3, ["102::0"], {"recall_at_5": 0.5, "recall_at_10": 0.5, "mrr_at_10": 1.0, "ndcg_at_10": 0.5}, 55.0)
    db.complete_run(r2, {
        "recall_at_5": 0.83, "recall_at_10": 0.83, "mrr_at_10": 1.0, "ndcg_at_10": 0.83,
        "avg_latency_ms": 50.0, "failure_count": 0, "total_questions": 3,
    })

    yield db, r1, r2

    db.close()
    try:
        os.unlink(path)
    except OSError:
        pass


class TestExportCSV:
    def test_csv_has_headers_and_rows(self, populated_db):
        db, r1, r2 = populated_db
        runs = db.get_all_completed_runs()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        _export_csv(runs, path)
        content = Path(path).read_text(encoding="utf-8")
        lines = [l for l in content.strip().split("\n") if l.strip()]
        assert len(lines) == 3  # header + 2 runs
        assert "Architecture" in lines[0]
        assert "nDCG@10" in lines[0]
        assert "Est. Monthly Cost" in lines[0]
        assert "keyword" in lines[1]
        assert "hybrid" in lines[2]
        os.unlink(path)


class TestExportJSON:
    def test_json_structure(self, populated_db):
        db, r1, r2 = populated_db
        runs = db.get_all_completed_runs()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        _export_json(runs, path)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["architecture_name"] == "keyword"
        assert data[1]["architecture_name"] == "hybrid"
        assert "aggregate_metrics" in data[0]
        os.unlink(path)


class TestPerCategoryScores:
    def test_categories_computed(self, populated_db):
        db, r1, r2 = populated_db
        cats = db.get_per_category_scores(r2)
        assert "direct_lookup" in cats
        assert "process_procedure" in cats
        assert cats["direct_lookup"]["ndcg_at_10"] == pytest.approx(1.0)


class TestFailureRetrieval:
    def test_failures_returned_for_keyword(self, populated_db):
        db, r1, r2 = populated_db
        failures = db.get_failures_for_run(r1)
        assert len(failures) == 2
        types = {f["failure_type"] for f in failures}
        assert "vocabulary_mismatch" in types
        assert "cross_ref_miss" in types

    def test_no_failures_for_hybrid(self, populated_db):
        db, r1, r2 = populated_db
        failures = db.get_failures_for_run(r2)
        assert len(failures) == 0
