"""Grounded query-smoke validation for evaluation candidates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from retrieve.config import RetrieveConfig
from retrieve.db import RetrieveDB
from retrieve.eval.runner import (
    _canonical_doc_id,
    _retrieval_questions,
    build_query_runtime_kwargs,
    query_ai_search,
)
from retrieve.ingest.manifest import build_document_id_aliases, load_corpus_manifest


def validate_architecture_readiness(
    db: RetrieveDB,
    cfg: RetrieveConfig,
    architecture_names: list[str],
) -> dict[str, dict[str, Any]]:
    """Persist one current-eval grounded smoke result per requested architecture."""
    session = db.get_generation_preferences("ui_session") or {}
    active_version = str(session.get("active_eval_set") or "").strip()
    eval_set = (
        db.get_eval_set_by_version(active_version)
        if active_version
        else db.get_latest_eval_set()
    )
    if not eval_set:
        raise ValueError("No eval set is available for candidate readiness validation")
    questions = _retrieval_questions(db.get_questions(int(eval_set["id"])))
    if not questions:
        raise ValueError("The active eval set has no grounded active question")

    manifest = load_corpus_manifest(cfg.corpus.output_dir)
    corpus_fingerprint = str(manifest["corpus_fingerprint"])
    aliases = build_document_id_aliases(manifest)
    question = questions[0]
    expected_ids = list(
        dict.fromkeys(
            _canonical_doc_id(str(value), aliases)
            for value in question["ground_truth_chunk_ids"]
        )
    )
    results: dict[str, dict[str, Any]] = {}

    for architecture_name in architecture_names:
        architecture = db.get_architecture(architecture_name)
        if not architecture:
            results[architecture_name] = {"state": "failed", "error": "not provisioned"}
            continue
        config = dict(architecture.get("config") or {})
        existing = config.get("query_smoke") or {}
        representative = config.get("graphrag_representative_100") or {}
        legacy_graph_smoke = representative.get("query_smoke") or {}
        if (
            architecture.get("status") == "active"
            and (
                (
                    existing.get("state") == "succeeded"
                    and existing.get("eval_set_id") == int(eval_set["id"])
                    and existing.get("corpus_fingerprint") == corpus_fingerprint
                )
                or (
                    architecture_name == "graphrag"
                    and legacy_graph_smoke.get("state") == "succeeded"
                    and legacy_graph_smoke.get("recall_at_10") == 1
                    and representative.get("eval_set") == str(eval_set["version_label"])
                    and config.get("corpus_fingerprint") == corpus_fingerprint
                )
            )
        ):
            results[architecture_name] = dict(existing or legacy_graph_smoke)
            results[architecture_name]["reused"] = True
            continue

        try:
            retrieved_ids, latency_ms = query_ai_search(
                endpoint=str(config.get("search_endpoint") or ""),
                index_name=str(config.get("index_name") or ""),
                query=str(question["question_text"]),
                arch_name=architecture_name,
                corpus_dir=cfg.corpus.output_dir,
                **build_query_runtime_kwargs(config),
            )
            canonical_ids = list(
                dict.fromkeys(_canonical_doc_id(str(value), aliases) for value in retrieved_ids)
            )
            expected_rank = next(
                (
                    canonical_ids.index(expected_id) + 1
                    for expected_id in expected_ids
                    if expected_id in canonical_ids
                ),
                None,
            )
            passed = expected_rank is not None and expected_rank <= 10
            smoke = {
                "state": "succeeded" if passed else "failed",
                "validated_at": datetime.now(UTC).isoformat(),
                "eval_set_id": int(eval_set["id"]),
                "eval_set_version": str(eval_set["version_label"]),
                "corpus_fingerprint": corpus_fingerprint,
                "question_id": int(question["id"]),
                "expected_document_ids": expected_ids,
                "retrieved_document_ids": canonical_ids[:20],
                "expected_rank": expected_rank,
                "recall_at_10": int(passed),
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            smoke = {
                "state": "failed",
                "validated_at": datetime.now(UTC).isoformat(),
                "eval_set_id": int(eval_set["id"]),
                "eval_set_version": str(eval_set["version_label"]),
                "corpus_fingerprint": corpus_fingerprint,
                "question_id": int(question["id"]),
                "expected_document_ids": expected_ids,
                "error": str(exc),
            }
        config["query_smoke"] = smoke
        db.conn.execute(
            "UPDATE architectures SET config = ?, status = ? WHERE id = ?",
            (
                json.dumps(config),
                "active" if smoke["state"] == "succeeded" else "provisioned",
                int(architecture["id"]),
            ),
        )
        db.conn.commit()
        results[architecture_name] = smoke

    return results