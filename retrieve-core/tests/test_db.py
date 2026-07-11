"""Tests for the SQLite schema, CRUD helpers, and durable operation jobs."""

import json
import os
import sqlite3
import tempfile

import pytest

from retrieve.db import (
    ActiveOperationJobError,
    IdempotencyConflictError,
    RetrieveDB,
)


@pytest.fixture
def db():
    path = os.path.join(tempfile.gettempdir(), f"test_retrieve_{os.getpid()}.db")
    d = RetrieveDB(path)
    yield d
    d.close()
    try:
        os.unlink(path)
    except OSError:
        pass


class TestSchema:
    def test_tables_created(self, db):
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {r["name"] for r in tables}
        assert "eval_sets" in names
        assert "eval_questions" in names
        assert "runs" in names
        assert "run_results" in names
        assert "architectures" in names
        assert "operation_jobs" in names
        assert "schema_version" in names

    def test_schema_version(self, db):
        row = db.conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
        assert row["v"] == 3

    def test_foreign_keys_enabled(self, db):
        row = db.conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1


class TestEvalSets:
    def test_create_eval_set(self, db):
        eid = db.create_eval_set("v1", notes="test set")
        assert eid > 0
        es = db.get_eval_set_by_version("v1")
        assert es is not None
        assert es["version_label"] == "v1"
        assert es["notes"] == "test set"
        assert es["question_count"] == 0

    def test_unique_version_label(self, db):
        db.create_eval_set("v1")
        with pytest.raises(Exception):
            db.create_eval_set("v1")

    def test_get_latest_eval_set(self, db):
        db.create_eval_set("v1")
        db.create_eval_set("v2")
        latest = db.get_latest_eval_set()
        assert latest["version_label"] == "v2"

    def test_get_latest_eval_set_empty(self, db):
        assert db.get_latest_eval_set() is None

    def test_get_eval_set_by_version_missing(self, db):
        assert db.get_eval_set_by_version("nonexistent") is None

    def test_update_eval_set_counts(self, db):
        eid = db.create_eval_set("v1")
        db.add_question(eid, "q1", "direct_lookup", ["c1"])
        db.add_question(eid, "q2", "direct_lookup", ["c2"])
        db.add_question(eid, "q3", "cross_document", ["c1", "c2"])
        db.update_eval_set_counts(eid)
        es = db.get_eval_set_by_version("v1")
        assert es["question_count"] == 3
        cats = json.loads(es["category_counts"])
        assert cats["direct_lookup"] == 2
        assert cats["cross_document"] == 1


class TestEvalQuestions:
    def test_add_and_get_questions(self, db):
        eid = db.create_eval_set("v1")
        qid = db.add_question(eid, "What form?", "direct_lookup", ["100::0"], "100")
        assert qid > 0
        qs = db.get_questions(eid)
        assert len(qs) == 1
        assert qs[0]["question_text"] == "What form?"
        assert qs[0]["category"] == "direct_lookup"
        assert qs[0]["ground_truth_chunk_ids"] == ["100::0"]
        assert qs[0]["source_doc_id"] == "100"

    def test_get_questions_by_category(self, db):
        eid = db.create_eval_set("v1")
        db.add_question(eid, "q1", "direct_lookup", ["c1"])
        db.add_question(eid, "q2", "cross_document", ["c2"])
        db.add_question(eid, "q3", "direct_lookup", ["c3"])
        qs = db.get_questions_by_category(eid, "direct_lookup")
        assert len(qs) == 2
        assert all(q["category"] == "direct_lookup" for q in qs)

    def test_question_metadata(self, db):
        eid = db.create_eval_set("v1")
        db.add_question(eid, "q1", "direct_lookup", ["c1"], metadata={"reasoning": "obvious"})
        qs = db.get_questions(eid)
        assert qs[0]["metadata"] == {"reasoning": "obvious"}


class TestArchitectures:
    def test_register_architecture(self, db):
        aid = db.register_architecture("hybrid", {"embedding": "3-small"})
        assert aid > 0
        arch = db.get_architecture("hybrid")
        assert arch is not None
        assert arch["name"] == "hybrid"
        assert arch["config"] == {"embedding": "3-small"}
        assert arch["status"] == "registered"

    def test_get_architecture_missing(self, db):
        assert db.get_architecture("nonexistent") is None


class TestOperationJobs:
    def test_atomic_admission_and_idempotent_replay(self, db):
        admitted, replayed = db.admit_operation_job(
            job_id="job-1",
            kind="index",
            owner_id="owner-1",
            request_hash="hash-1",
            idempotency_key="request-001",
            args={"api_key": "***", "architectures": ["hybrid"]},
        )

        assert replayed is False
        assert admitted["state"] == "queued"
        assert admitted["args"]["api_key"] == "***"

        replay, replayed = db.admit_operation_job(
            job_id="ignored-new-id",
            kind="index",
            owner_id="owner-1",
            request_hash="hash-1",
            idempotency_key="request-001",
            args={},
        )
        assert replayed is True
        assert replay["id"] == "job-1"

        with pytest.raises(IdempotencyConflictError):
            db.admit_operation_job(
                job_id="job-conflict",
                kind="index",
                owner_id="owner-1",
                request_hash="different-hash",
                idempotency_key="request-001",
            )

    def test_active_job_blocks_another_admission(self, db):
        db.admit_operation_job(
            job_id="job-1",
            kind="index",
            owner_id="owner-1",
            request_hash="hash-1",
        )

        with pytest.raises(ActiveOperationJobError):
            db.admit_operation_job(
                job_id="job-2",
                kind="provision",
                owner_id="owner-2",
                request_hash="hash-2",
            )

    def test_state_transitions_and_restart_interruption(self, db):
        db.admit_operation_job(
            job_id="job-1",
            kind="index",
            owner_id="owner-1",
            request_hash="hash-1",
        )
        db.update_operation_job("job-1", state="running")
        assert db.get_active_operation_job()["id"] == "job-1"

        assert db.mark_interrupted_operation_jobs_failed() == 1
        interrupted = db.get_operation_job("job-1")
        assert interrupted["state"] == "failed"
        assert interrupted["done"] is True
        assert "restarted" in interrupted["error"]

        admitted, _ = db.admit_operation_job(
            job_id="job-2",
            kind="evaluate",
            owner_id="owner-1",
            request_hash="hash-2",
        )
        assert admitted["state"] == "queued"
        db.update_operation_job(
            "job-2",
            state="succeeded",
            result={"status": "complete"},
        )
        completed = db.get_operation_job("job-2")
        assert completed["result"] == {"status": "complete"}
        assert completed["done"] is True

    def test_newer_schema_is_rejected_before_ddl(self, tmp_path):
        path = tmp_path / "future.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version (version) VALUES (999)")
        conn.commit()
        conn.close()

        future = RetrieveDB(path)
        with pytest.raises(RuntimeError, match="newer than supported"):
            _ = future.conn
        future.close()

        check = sqlite3.connect(path)
        operation_jobs = check.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='operation_jobs'"
        ).fetchone()
        check.close()
        assert operation_jobs is None


class TestRuns:
    def test_create_and_complete_run(self, db):
        eid = db.create_eval_set("v1")
        rid = db.create_run(eid, "hybrid", "test", {"embedding": "3-small"})
        assert rid > 0
        run = db.get_run(rid)
        assert run["status"] == "running"
        assert run["architecture_name"] == "hybrid"
        assert run["mode"] == "test"

        db.complete_run(rid, {"recall_at_5": 0.8, "ndcg_at_10": 0.75})
        run = db.get_run(rid)
        assert run["status"] == "completed"
        assert run["aggregate_metrics"]["recall_at_5"] == 0.8

    def test_fail_run(self, db):
        eid = db.create_eval_set("v1")
        rid = db.create_run(eid, "hybrid", "test")
        db.fail_run(rid)
        run = db.get_run(rid)
        assert run["status"] == "failed"

    def test_get_runs_for_eval_set(self, db):
        eid = db.create_eval_set("v1")
        db.create_run(eid, "keyword", "test")
        db.create_run(eid, "hybrid", "test")
        runs = db.get_runs_for_eval_set(eid)
        assert len(runs) == 2

    def test_get_all_completed_runs(self, db):
        eid = db.create_eval_set("v1")
        r1 = db.create_run(eid, "keyword", "test")
        db.create_run(eid, "hybrid", "test")
        db.complete_run(r1, {"ndcg_at_10": 0.5})
        # r2 still running
        completed = db.get_all_completed_runs()
        assert len(completed) == 1
        assert completed[0]["architecture_name"] == "keyword"

    def test_compare_runs(self, db):
        eid = db.create_eval_set("v1")
        r1 = db.create_run(eid, "keyword", "test")
        r2 = db.create_run(eid, "hybrid", "test")
        db.complete_run(r1, {"ndcg_at_10": 0.5})
        db.complete_run(r2, {"ndcg_at_10": 0.7})
        compared = db.compare_runs([r1, r2])
        assert len(compared) == 2


class TestRunResults:
    def test_add_and_get_results(self, db):
        eid = db.create_eval_set("v1")
        qid = db.add_question(eid, "q1", "direct_lookup", ["c1"])
        rid = db.create_run(eid, "hybrid", "test")
        db.add_result(rid, qid, ["c1", "c2"], {"recall_at_5": 1.0, "ndcg_at_10": 1.0}, 42.5)
        results = db.get_results_for_run(rid)
        assert len(results) == 1
        assert results[0]["retrieved_chunk_ids"] == ["c1", "c2"]
        assert results[0]["scores"]["recall_at_5"] == 1.0
        assert results[0]["latency_ms"] == 42.5

    def test_get_failures(self, db):
        eid = db.create_eval_set("v1")
        qid1 = db.add_question(eid, "q1", "direct_lookup", ["c1"])
        qid2 = db.add_question(eid, "q2", "cross_document", ["c2"])
        rid = db.create_run(eid, "hybrid", "test")
        db.add_result(rid, qid1, ["c1"], {"recall_at_5": 1.0}, failure_type=None)
        db.add_result(
            rid,
            qid2,
            ["c3"],
            {"recall_at_5": 0.0},
            failure_type="semantic_gap",
            failure_details="missed",
        )
        failures = db.get_failures_for_run(rid)
        assert len(failures) == 1
        assert failures[0]["failure_type"] == "semantic_gap"

    def test_per_category_scores(self, db):
        eid = db.create_eval_set("v1")
        q1 = db.add_question(eid, "q1", "direct_lookup", ["c1"])
        q2 = db.add_question(eid, "q2", "direct_lookup", ["c2"])
        q3 = db.add_question(eid, "q3", "cross_document", ["c3"])
        rid = db.create_run(eid, "hybrid", "test")
        db.add_result(rid, q1, ["c1"], {"ndcg_at_10": 1.0, "recall_at_5": 1.0})
        db.add_result(rid, q2, ["c2"], {"ndcg_at_10": 0.6, "recall_at_5": 0.5})
        db.add_result(rid, q3, ["c3"], {"ndcg_at_10": 0.3, "recall_at_5": 0.0})

        cats = db.get_per_category_scores(rid)
        assert "direct_lookup" in cats
        assert "cross_document" in cats
        assert cats["direct_lookup"]["ndcg_at_10"] == pytest.approx(0.8)
        assert cats["cross_document"]["ndcg_at_10"] == pytest.approx(0.3)
