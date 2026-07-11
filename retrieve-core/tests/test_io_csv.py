"""Tests for eval CSV import/export with full lineage tracking."""

from __future__ import annotations

import csv
import json
import os
import tempfile

import pytest

from retrieve.db import RetrieveDB
from retrieve.eval.io_csv import CSV_COLUMNS, export_eval_set_to_csv, import_eval_set_from_csv


@pytest.fixture
def db():
    path = os.path.join(tempfile.gettempdir(), f"test_io_csv_{os.getpid()}.db")
    d = RetrieveDB(path)
    yield d
    d.close()
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# ── helpers ───────────────────────────────────────────────────────────

def _seed_eval_set(db: RetrieveDB, version: str = "v1", n: int = 3) -> int:
    eid = db.create_eval_set(version, notes="seed")
    for i in range(n):
        db.add_question(
            eval_set_id=eid,
            question_text=f"Question {i}?",
            category="direct_lookup",
            ground_truth_chunk_ids=[f"doc{i}::0"],
            answer_text=f"Answer {i}.",
            question_type="operator_lookup",
            persona="domain_user",
            intent_family="policy_lookup",
            difficulty="medium",
        )
    db.update_eval_set_counts(eid)
    return eid


# ── column contract ───────────────────────────────────────────────────

class TestCSVColumns:
    def test_lineage_columns_present(self):
        assert "csv_source_file" in CSV_COLUMNS
        assert "csv_source_row" in CSV_COLUMNS
        assert "csv_eval_set_id" in CSV_COLUMNS
        assert "csv_imported_at" in CSV_COLUMNS

    def test_core_columns_present(self):
        for col in ["question_text", "answer_text", "category", "question_type",
                    "persona", "intent_family", "status"]:
            assert col in CSV_COLUMNS


# ── export ────────────────────────────────────────────────────────────

class TestExport:
    def test_export_row_count(self, db, tmp_dir):
        eid = _seed_eval_set(db, n=4)
        out = os.path.join(tmp_dir, "out.csv")
        count = export_eval_set_to_csv(db, eid, out)
        assert count == 4

    def test_export_headers(self, db, tmp_dir):
        eid = _seed_eval_set(db)
        out = os.path.join(tmp_dir, "out.csv")
        export_eval_set_to_csv(db, eid, out)
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert set(CSV_COLUMNS).issubset(set(reader.fieldnames or []))

    def test_export_lineage_eval_set_id(self, db, tmp_dir):
        eid = _seed_eval_set(db)
        out = os.path.join(tmp_dir, "out.csv")
        export_eval_set_to_csv(db, eid, out)
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                assert row["csv_eval_set_id"] == str(eid)

    def test_export_lineage_imported_at_is_iso(self, db, tmp_dir):
        eid = _seed_eval_set(db)
        out = os.path.join(tmp_dir, "out.csv")
        export_eval_set_to_csv(db, eid, out)
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = row["csv_imported_at"]
                assert "T" in ts and len(ts) > 10

    def test_export_no_prior_lineage_leaves_source_file_blank(self, db, tmp_dir):
        """LLM-generated questions have no csv_source_file."""
        eid = _seed_eval_set(db)
        out = os.path.join(tmp_dir, "out.csv")
        export_eval_set_to_csv(db, eid, out)
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                assert row["csv_source_file"] == ""

    def test_export_carries_forward_prior_lineage(self, db, tmp_dir):
        """When a question was previously imported from CSV, lineage column is preserved."""
        eid = db.create_eval_set("v1")
        db.add_question(
            eval_set_id=eid,
            question_text="Was this imported?",
            category="direct_lookup",
            ground_truth_chunk_ids=["x::0"],
            metadata={"reasoning": "", "csv_source_file": "original.csv", "csv_source_row": 7},
        )
        db.update_eval_set_counts(eid)

        out = os.path.join(tmp_dir, "out.csv")
        export_eval_set_to_csv(db, eid, out)
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert row["csv_source_file"] == "original.csv"
        assert row["csv_source_row"] == "7"


# ── import ────────────────────────────────────────────────────────────

class TestImport:
    def _write_csv(self, path: str, rows: list[dict]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            w.writeheader()
            for row in rows:
                full = {c: "" for c in CSV_COLUMNS}
                full.update(row)
                w.writerow(full)

    def test_import_fresh(self, db, tmp_dir):
        csv_path = os.path.join(tmp_dir, "import.csv")
        self._write_csv(csv_path, [
            {"question_text": "Q1?", "answer_text": "A1", "category": "direct_lookup",
             "ground_truth_chunk_ids": '["doc::0"]', "status": "active"},
            {"question_text": "Q2?", "answer_text": "A2", "category": "process_procedure",
             "ground_truth_chunk_ids": '["doc::1"]', "status": "active"},
        ])
        eid, count = import_eval_set_from_csv(db, csv_path, "v-import", fresh=True)
        assert count == 2
        qs = db.get_questions(eid)
        assert len(qs) == 2

    def test_import_records_source_file(self, db, tmp_dir):
        csv_path = os.path.join(tmp_dir, "questions.csv")
        self._write_csv(csv_path, [
            {"question_text": "Q?", "answer_text": "A", "category": "direct_lookup",
             "ground_truth_chunk_ids": '["doc::0"]', "status": "active"},
        ])
        eid, _ = import_eval_set_from_csv(db, csv_path, "v-lineage", fresh=True)
        q = db.get_questions(eid)[0]
        meta = q["metadata"]
        assert meta["csv_source_file"] == "questions.csv"

    def test_import_records_row_number(self, db, tmp_dir):
        csv_path = os.path.join(tmp_dir, "rows.csv")
        self._write_csv(csv_path, [
            {"question_text": "Row1?", "ground_truth_chunk_ids": "[]"},
            {"question_text": "Row2?", "ground_truth_chunk_ids": "[]"},
            {"question_text": "Row3?", "ground_truth_chunk_ids": "[]"},
        ])
        eid, _ = import_eval_set_from_csv(db, csv_path, "v-rows", fresh=True)
        qs = db.get_questions(eid)
        row_nums = {q["question_text"]: q["metadata"]["csv_source_row"] for q in qs}
        assert row_nums["Row1?"] == 1
        assert row_nums["Row2?"] == 2
        assert row_nums["Row3?"] == 3

    def test_import_records_timestamp(self, db, tmp_dir):
        csv_path = os.path.join(tmp_dir, "ts.csv")
        self._write_csv(csv_path, [
            {"question_text": "Stamped?", "ground_truth_chunk_ids": "[]"},
        ])
        eid, _ = import_eval_set_from_csv(db, csv_path, "v-ts", fresh=True)
        q = db.get_questions(eid)[0]
        ts = q["metadata"]["csv_imported_at"]
        assert "T" in ts

    def test_import_chains_prior_lineage(self, db, tmp_dir):
        """A row that already has csv_source_file should record that as csv_origin_file."""
        csv_path = os.path.join(tmp_dir, "chain.csv")
        self._write_csv(csv_path, [
            {
                "question_text": "Chain?",
                "ground_truth_chunk_ids": "[]",
                "csv_source_file": "first.csv",
                "csv_source_row": "5",
                "csv_eval_set_id": "1",
            },
        ])
        eid, _ = import_eval_set_from_csv(db, csv_path, "v-chain", fresh=True)
        q = db.get_questions(eid)[0]
        meta = q["metadata"]
        # Current import stamps chain.csv
        assert meta["csv_source_file"] == "chain.csv"
        # Prior origin is preserved
        assert meta["csv_origin_file"] == "first.csv"
        assert meta["csv_origin_row"] == "5"

    def test_import_deduplication(self, db, tmp_dir):
        csv_path = os.path.join(tmp_dir, "dup.csv")
        self._write_csv(csv_path, [
            {"question_text": "Same Q?", "answer_text": "Same A", "ground_truth_chunk_ids": "[]"},
            {"question_text": "Same Q?", "answer_text": "Same A", "ground_truth_chunk_ids": "[]"},
        ])
        _, count = import_eval_set_from_csv(db, csv_path, "v-dup", fresh=True)
        assert count == 1

    def test_import_extend_preserves_base_questions(self, db, tmp_dir):
        base_eid = _seed_eval_set(db, "base", n=2)
        csv_path = os.path.join(tmp_dir, "extend.csv")
        self._write_csv(csv_path, [
            {"question_text": "New Q?", "answer_text": "New A", "ground_truth_chunk_ids": "[]"},
        ])
        eid, imported = import_eval_set_from_csv(
            db, csv_path, "v-ext", base_eval_set_id=base_eid, fresh=False
        )
        assert imported == 1
        qs = db.get_questions(eid)
        # base 2 + new 1
        assert len(qs) == 3

    def test_import_missing_file_raises(self, db, tmp_dir):
        with pytest.raises(FileNotFoundError):
            import_eval_set_from_csv(db, os.path.join(tmp_dir, "nope.csv"), "v-x")

    def test_import_skips_blank_question_rows(self, db, tmp_dir):
        csv_path = os.path.join(tmp_dir, "blank.csv")
        self._write_csv(csv_path, [
            {"question_text": "", "ground_truth_chunk_ids": "[]"},
            {"question_text": "Valid?", "ground_truth_chunk_ids": "[]"},
        ])
        _, count = import_eval_set_from_csv(db, csv_path, "v-blank", fresh=True)
        assert count == 1


# ── round-trip ────────────────────────────────────────────────────────

class TestRoundTrip:
    def test_export_import_preserves_question_text(self, db, tmp_dir):
        eid = _seed_eval_set(db, "orig", n=3)
        csv_path = os.path.join(tmp_dir, "rt.csv")
        export_eval_set_to_csv(db, eid, csv_path)
        new_eid, count = import_eval_set_from_csv(db, csv_path, "rt-import", fresh=True)
        assert count == 3
        orig_qs = {q["question_text"] for q in db.get_questions(eid)}
        new_qs = {q["question_text"] for q in db.get_questions(new_eid)}
        assert orig_qs == new_qs

    def test_export_import_lineage_stamps_importer(self, db, tmp_dir):
        eid = _seed_eval_set(db, "orig")
        csv_path = os.path.join(tmp_dir, "rt.csv")
        export_eval_set_to_csv(db, eid, csv_path)
        new_eid, _ = import_eval_set_from_csv(db, csv_path, "rt-import", fresh=True)
        for q in db.get_questions(new_eid):
            assert q["metadata"]["csv_source_file"] == "rt.csv"
            assert q["metadata"]["csv_source_row"] >= 1
