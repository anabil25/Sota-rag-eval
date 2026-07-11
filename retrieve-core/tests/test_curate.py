"""Tests for eval/curate.py — curation, steering, and regeneration."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.eval.curate import (
    _build_steering_prompt,
    regenerate_eval_set,
    show_eval_set_summary,
)


@pytest.fixture
def seeded_db():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    corpus_dir = os.path.join(tmpdir, "corpus")
    os.makedirs(corpus_dir)
    (Path(corpus_dir) / "doc.md").write_text(
        '---\npolicy_id: "100"\ntitle: "Test"\n---\n\n# Section\n\nContent here.',
        encoding="utf-8",
    )

    db = RetrieveDB(db_path)
    eid = db.create_eval_set("v1", notes="original")
    db.add_question(eid, "What form?", "direct_lookup", ["100::0"], "100")
    db.add_question(eid, "Another lookup?", "direct_lookup", ["100::0"], "100")
    db.add_question(eid, "What form 2?", "direct_lookup", ["100::0"], "100")
    db.add_question(eid, "What form 3?", "direct_lookup", ["100::0"], "100")
    db.add_question(eid, "How long?", "process_procedure", ["100::1"], "100")
    db.add_question(eid, "What steps?", "process_procedure", ["100::1"], "100")
    db.add_question(eid, "Who qualifies?", "eligibility", ["100::0"], "100")
    db.add_question(eid, "Cross ref?", "cross_document", ["100::0", "100::1"], "100")
    db.update_eval_set_counts(eid)
    db.close()

    return tmpdir, db_path, corpus_dir


class TestShowSummary:
    def test_shows_summary(self, seeded_db):
        tmpdir, db_path, _ = seeded_db
        cfg = RetrieveConfig()
        cfg.db_path = db_path
        result = show_eval_set_summary("v1", cfg)
        assert result is not None
        assert result["version_label"] == "v1"

    def test_missing_eval_set(self, seeded_db):
        tmpdir, db_path, _ = seeded_db
        cfg = RetrieveConfig()
        cfg.db_path = db_path
        result = show_eval_set_summary("nonexistent", cfg)
        assert result is None


class TestBuildSteeringPrompt:
    def test_builds_instructions(self):
        cats = {"direct_lookup": 10, "cross_document": 5}
        steering = {
            "more": ["cross_document"],
            "fewer": ["direct_lookup"],
            "add_categories": ["fraud_referrals"],
            "remove_categories": [],
            "notes": "More DV questions",
        }
        prompt = _build_steering_prompt(cats, steering)
        assert "MORE" in prompt
        assert "FEWER" in prompt
        assert "fraud_referrals" in prompt
        assert "DV" in prompt

    def test_empty_steering(self):
        prompt = _build_steering_prompt({}, {})
        assert "No steering changes" in prompt


class TestRegenerateEvalSet:
    @patch("retrieve.eval.curate._generate_steered_questions", new_callable=AsyncMock)
    def test_regenerate_fewer(self, mock_gen, seeded_db):
        mock_gen.return_value = []
        tmpdir, db_path, corpus_dir = seeded_db
        cfg = RetrieveConfig()
        cfg.db_path = db_path

        steering = {
            "more": [],
            "fewer": ["direct_lookup"],
            "add_categories": [],
            "remove_categories": [],
            "notes": "",
        }

        new_id = regenerate_eval_set("v1", "v2", steering, corpus_dir, cfg)
        assert new_id > 0

        db = RetrieveDB(db_path)
        new_es = db.get_eval_set_by_version("v2")
        new_cats = json.loads(new_es["category_counts"])
        # direct_lookup should be halved (4 → 2)
        assert new_cats.get("direct_lookup", 0) <= 2
        # Other categories unchanged
        assert new_cats.get("process_procedure", 0) == 2
        assert new_cats.get("eligibility", 0) == 1
        db.close()

    @patch("retrieve.eval.curate._generate_steered_questions", new_callable=AsyncMock)
    def test_regenerate_remove_category(self, mock_gen, seeded_db):
        mock_gen.return_value = []
        tmpdir, db_path, corpus_dir = seeded_db
        cfg = RetrieveConfig()
        cfg.db_path = db_path

        steering = {
            "more": [],
            "fewer": [],
            "add_categories": [],
            "remove_categories": ["eligibility"],
            "notes": "",
        }

        new_id = regenerate_eval_set("v1", "v2-no-elig", steering, corpus_dir, cfg)
        assert new_id > 0

        db = RetrieveDB(db_path)
        new_es = db.get_eval_set_by_version("v2-no-elig")
        new_cats = json.loads(new_es["category_counts"])
        assert "eligibility" not in new_cats
        assert new_es["question_count"] == 7  # 8 - 1 eligibility
        db.close()

    @patch("retrieve.eval.curate._generate_steered_questions", new_callable=AsyncMock)
    def test_regenerate_add_more(self, mock_gen, seeded_db):
        mock_gen.return_value = [
            {
                "question": "New cross-doc Q?",
                "category": "cross_document",
                "ground_truth_chunk_ids": ["100::0"],
                "source_doc_id": "100",
            },
            {
                "question": "Another cross Q?",
                "category": "cross_document",
                "ground_truth_chunk_ids": ["100::1"],
                "source_doc_id": "100",
            },
        ]
        tmpdir, db_path, corpus_dir = seeded_db
        cfg = RetrieveConfig()
        cfg.db_path = db_path

        steering = {
            "more": ["cross_document"],
            "fewer": [],
            "add_categories": [],
            "remove_categories": [],
            "notes": "More cross-doc questions",
        }

        new_id = regenerate_eval_set("v1", "v2-more-xref", steering, corpus_dir, cfg)
        assert new_id > 0

        db = RetrieveDB(db_path)
        new_es = db.get_eval_set_by_version("v2-more-xref")
        new_cats = json.loads(new_es["category_counts"])
        # cross_document: original 1 + 2 new = 3
        assert new_cats.get("cross_document", 0) == 3
        assert new_es["question_count"] == 10  # 8 + 2
        db.close()

    def test_regenerate_missing_source(self, seeded_db):
        tmpdir, db_path, corpus_dir = seeded_db
        cfg = RetrieveConfig()
        cfg.db_path = db_path

        result = regenerate_eval_set("nonexistent", "v2", {}, corpus_dir, cfg)
        assert result == -1

    @patch("retrieve.eval.curate._generate_steered_questions", new_callable=AsyncMock)
    def test_versioning_preserves_original(self, mock_gen, seeded_db):
        """Original eval set should be untouched after regeneration."""
        mock_gen.return_value = []
        tmpdir, db_path, corpus_dir = seeded_db
        cfg = RetrieveConfig()
        cfg.db_path = db_path

        regenerate_eval_set("v1", "v2", {"fewer": ["direct_lookup"]}, corpus_dir, cfg)

        db = RetrieveDB(db_path)
        original = db.get_eval_set_by_version("v1")
        assert original["question_count"] == 8  # unchanged
        db.close()
