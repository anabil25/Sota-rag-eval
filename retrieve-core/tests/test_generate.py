"""Tests for eval/generate.py — eval set generation with mocked Copilot SDK."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from retrieve.config import RetrieveConfig
from retrieve.eval.chunks import Chunk
from retrieve.eval.generate import _generate_for_batch, generate_eval_set


@pytest.fixture
def corpus_dir():
    """Create a temp corpus with two markdown files."""
    tmpdir = tempfile.mkdtemp()
    d = Path(tmpdir) / "100"
    d.mkdir()
    (d / "100_general.md").write_text(
        '---\npolicy_id: "100"\ntitle: "General Information"\nparent: "APM"\n---\n\n'
        "# Overview\n\nGeneral information about the program.\n\n"
        "# Eligibility\n\nMust be a resident.",
        encoding="utf-8",
    )
    (d / "100-1_prudent.md").write_text(
        '---\npolicy_id: "100-1"\ntitle: "Prudent Person"\nparent: "100 General"\n---\n\n'
        "The prudent person concept requires workers to exercise judgment.",
        encoding="utf-8",
    )
    return tmpdir


class TestGenerateEvalSet:
    @patch("retrieve.eval.generate._generate_for_batch")
    def test_generates_and_stores(self, mock_gen, corpus_dir):
        """Test full generate_eval_set flow with mocked LLM."""
        mock_gen.return_value = [
            {
                "question": "What is the prudent person concept?",
                "category": "direct_lookup",
                "ground_truth_chunk_ids": ["100-1::0"],
                "source_doc_id": "100-1",
                "reasoning": "Directly answers from the chunk",
            },
            {
                "question": "Who is eligible for the program?",
                "category": "eligibility",
                "ground_truth_chunk_ids": ["100::2"],
                "source_doc_id": "100",
                "reasoning": "Eligibility section",
            },
        ]

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        cfg = RetrieveConfig()
        cfg.db_path = db_path

        eval_set_id = generate_eval_set(
            corpus_dir=corpus_dir,
            version_label="test-v1",
            questions_per_chunk=2,
            cfg=cfg,
        )

        assert eval_set_id > 0

        from retrieve.db import RetrieveDB

        db = RetrieveDB(db_path)
        es = db.get_eval_set_by_version("test-v1")
        assert es is not None
        assert es["question_count"] == 2

        qs = db.get_questions(eval_set_id)
        assert len(qs) == 2
        assert qs[0]["question_text"] == "What is the prudent person concept?"
        assert qs[0]["category"] == "direct_lookup"
        db.close()

    @patch("retrieve.eval.generate._generate_for_batch")
    def test_empty_corpus(self, mock_gen):
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        cfg = RetrieveConfig()
        cfg.db_path = db_path

        result = generate_eval_set(
            corpus_dir=tmpdir,
            version_label="empty",
            cfg=cfg,
        )
        assert result == -1
        mock_gen.assert_not_called()

    @patch("retrieve.eval.generate._generate_for_batch")
    def test_no_questions_generated(self, mock_gen):
        mock_gen.return_value = []

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        (Path(tmpdir) / "test.md").write_text(
            "---\npolicy_id: test\n---\nContent", encoding="utf-8"
        )

        cfg = RetrieveConfig()
        cfg.db_path = db_path

        result = generate_eval_set(
            corpus_dir=tmpdir, version_label="v1", questions_per_chunk=1, cfg=cfg
        )
        assert result == -1


class TestGenerateForBatch:
    @patch("retrieve.eval.generate.get_client")
    async def test_generates_questions(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        response_json = json.dumps(
            {
                "questions": [
                    {
                        "question": "What is this?",
                        "category": "direct_lookup",
                        "ground_truth_chunk_ids": ["test::0"],
                        "reasoning": "Direct answer",
                    }
                ]
            }
        )

        mock_response = MagicMock()
        mock_response.data.content = response_json

        mock_session = AsyncMock()
        mock_session.send_and_wait.return_value = mock_response
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_client.create_session = AsyncMock(return_value=mock_session)

        chunks = [Chunk(chunk_id="test::0", doc_id="test", doc_title="Test", content="Content")]

        cfg = RetrieveConfig()
        questions = await _generate_for_batch(
            chunks,
            1,
            1,
            cfg,
            1,
            "operator context",
            {"document_count": 1},
            {"intent_families": ["eligibility"]},
        )

        assert len(questions) == 1
        assert questions[0]["question"] == "What is this?"
        assert "test::0" in questions[0]["ground_truth_chunk_ids"]

    @patch("retrieve.eval.generate.get_client")
    async def test_handles_json_in_markdown(self, mock_get_client):
        """Model wraps JSON in ```json``` blocks."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        response_text = '```json\n{"questions": [{"question": "Q?", "category": "edge_cases", "ground_truth_chunk_ids": ["t::0"]}]}\n```'

        mock_response = MagicMock()
        mock_response.data.content = response_text

        mock_session = AsyncMock()
        mock_session.send_and_wait.return_value = mock_response
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_client.create_session = AsyncMock(return_value=mock_session)

        chunks = [Chunk(chunk_id="t::0", doc_id="t", doc_title="T", content="C")]

        cfg = RetrieveConfig()
        questions = await _generate_for_batch(
            chunks,
            1,
            1,
            cfg,
            1,
            "operator context",
            {"document_count": 1},
            {"intent_families": ["eligibility"]},
        )
        assert len(questions) == 1

    @patch("retrieve.eval.generate.get_client")
    async def test_handles_bad_json(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data.content = "not valid json at all"

        mock_session = AsyncMock()
        mock_session.send_and_wait.return_value = mock_response
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_client.create_session = AsyncMock(return_value=mock_session)

        chunks = [Chunk(chunk_id="t::0", doc_id="t", doc_title="T", content="C")]

        cfg = RetrieveConfig()
        questions = await _generate_for_batch(
            chunks,
            1,
            1,
            cfg,
            1,
            "operator context",
            {"document_count": 1},
            {"intent_families": ["eligibility"]},
        )
        assert questions == []  # No crash, just empty

    @patch("retrieve.eval.generate.get_client")
    @patch("retrieve.eval.generate.emit_progress")
    async def test_emits_heartbeat_while_waiting(self, mock_emit_progress, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data.content = json.dumps(
            {
                "questions": [
                    {
                        "question": "What is this?",
                        "category": "direct_lookup",
                        "ground_truth_chunk_ids": ["hb::0"],
                    }
                ]
            }
        )

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_client.create_session = AsyncMock(return_value=mock_session)

        chunks = [Chunk(chunk_id="hb::0", doc_id="hb", doc_title="HB", content="content")]

        # Make send_and_wait delay so the heartbeat task fires
        async def slow_send(*args, **kwargs):
            await asyncio.sleep(0.15)
            return mock_response

        mock_session.send_and_wait = slow_send

        cfg = RetrieveConfig()
        # Patch asyncio.sleep to return quickly so the heartbeat fires during the delay
        original_sleep = asyncio.sleep

        async def fast_sleep(duration):
            await original_sleep(0.05)

        with patch("retrieve.eval.generate.asyncio.sleep", new=fast_sleep):
            await _generate_for_batch(
                chunks,
                1,
                1,
                cfg,
                1,
                "operator context",
                {"document_count": 1},
                {"intent_families": ["eligibility"]},
            )

        assert any(
            call.args and call.args[0] == "Waiting on model"
            for call in mock_emit_progress.call_args_list
        )
