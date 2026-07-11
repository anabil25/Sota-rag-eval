"""CSV import/export utilities for eval sets.

These helpers let users persist and extend eval sets without forcing a fresh rebuild.
Lineage columns record origin file, row number, and source eval set so that every
imported question is fully auditable across multiple CSV round-trips.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retrieve.db import RetrieveDB

# Ordered columns that appear in every exported CSV.
# Lineage block (csv_source_file / csv_source_row / csv_eval_set_id / csv_imported_at)
# is appended so that older files without those columns still import cleanly via the
# DictReader.get() fallback.
CSV_COLUMNS = [
    "question_text",
    "answer_text",
    "category",
    "question_type",
    "persona",
    "intent_family",
    "difficulty",
    "expected_search_challenge",
    "source_doc_id",
    "ground_truth_chunk_ids",
    "evidence_summary",
    "reasoning",
    "status",
    # ── lineage ──────────────────────────────────────────
    "csv_source_file",    # filename the row was originally imported from
    "csv_source_row",     # 1-based data row index within that file
    "csv_eval_set_id",    # eval_set_id at time of export (audit trail)
    "csv_imported_at",    # ISO-8601 timestamp when the row was written
]


def export_eval_set_to_csv(db: RetrieveDB, eval_set_id: int, output_path: str | Path) -> int:
    """Export an eval set's questions to CSV. Returns row count.

    Lineage fields are populated from question metadata when present; questions
    generated (not imported) from a CSV will have empty lineage columns.
    """
    rows = db.get_questions(eval_set_id)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()

    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for q in rows:
            meta = q.get("metadata", {}) if isinstance(q.get("metadata", {}), dict) else {}
            w.writerow(
                {
                    "question_text": q.get("question_text", ""),
                    "answer_text": q.get("answer_text", ""),
                    "category": q.get("category", "direct_lookup"),
                    "question_type": q.get("question_type", "operator_lookup"),
                    "persona": q.get("persona", "alaska_dpa_operator"),
                    "intent_family": q.get("intent_family", "policy_lookup"),
                    "difficulty": q.get("difficulty", "medium"),
                    "expected_search_challenge": q.get("expected_search_challenge", ""),
                    "source_doc_id": q.get("source_doc_id", ""),
                    "ground_truth_chunk_ids": json.dumps(q.get("ground_truth_chunk_ids", [])),
                    "evidence_summary": q.get("evidence_summary", ""),
                    "reasoning": meta.get("reasoning", ""),
                    "status": q.get("status", "active"),
                    # lineage — carry forward whatever was recorded at import time,
                    # or blanks for questions that were LLM-generated
                    "csv_source_file": meta.get("csv_source_file", ""),
                    "csv_source_row": meta.get("csv_source_row", ""),
                    "csv_eval_set_id": str(eval_set_id),
                    "csv_imported_at": now,
                }
            )

    return len(rows)


def import_eval_set_from_csv(
    db: RetrieveDB,
    input_path: str | Path,
    version_label: str,
    base_eval_set_id: int | None = None,
    fresh: bool = False,
) -> tuple[int, int]:
    """Import eval questions from CSV into a new eval set.

    Every imported row records full lineage in its metadata:
      - csv_source_file: filename of the originating CSV
      - csv_source_row:  1-based data row index within that file
      - csv_eval_set_id: eval set id the row claimed at export time (if present)
      - csv_imported_at: ISO-8601 timestamp of this import run

    Lineage is forwarded during build-on so it survives multiple round-trips.

    Returns (eval_set_id, imported_count).
    """
    inp = Path(input_path)
    if not inp.exists():
        raise FileNotFoundError(f"CSV not found: {inp}")

    source_filename = inp.name
    import_ts = datetime.now(timezone.utc).isoformat()

    parent_id = None if fresh else base_eval_set_id
    new_eval_set_id = db.create_eval_set(
        version_label=version_label,
        notes=f"Imported from CSV: {source_filename}",
        parent_eval_set_id=parent_id,
        build_mode="fresh" if fresh else "extend",
        steering_state={"source": "csv-import", "csv_source_file": source_filename, "csv_imported_at": import_ts},
        operator_context="",
    )

    dedup: set[tuple[str, str]] = set()
    if base_eval_set_id and not fresh:
        for q in db.get_questions(base_eval_set_id):
            dedup.add((q.get("question_text", "").strip().lower(), q.get("answer_text", "").strip().lower()))
            # Forward existing rows, preserving whatever lineage they already carry
            db.add_question(
                eval_set_id=new_eval_set_id,
                question_text=q.get("question_text", ""),
                category=q.get("category", "direct_lookup"),
                ground_truth_chunk_ids=q.get("ground_truth_chunk_ids", []),
                source_doc_id=q.get("source_doc_id"),
                metadata=q.get("metadata", {}),
                answer_text=q.get("answer_text", ""),
                question_type=q.get("question_type", "operator_lookup"),
                persona=q.get("persona", "alaska_dpa_operator"),
                intent_family=q.get("intent_family", "policy_lookup"),
                difficulty=q.get("difficulty", "medium"),
                expected_search_challenge=q.get("expected_search_challenge", ""),
                evidence_summary=q.get("evidence_summary", ""),
                status=q.get("status", "active"),
            )

    imported = 0
    with inp.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for data_row_idx, row in enumerate(r, start=1):
            question_text = (row.get("question_text") or "").strip()
            if not question_text:
                continue
            answer_text = (row.get("answer_text") or "").strip()
            key = (question_text.lower(), answer_text.lower())
            if key in dedup:
                continue
            dedup.add(key)

            gt_raw = row.get("ground_truth_chunk_ids", "[]")
            try:
                gt = json.loads(gt_raw) if gt_raw else []
                if not isinstance(gt, list):
                    gt = []
            except json.JSONDecodeError:
                gt = []

            # Carry forward any lineage the row already has, then stamp this import
            # on top so the chain accumulates as the file is round-tripped.
            prior_source_file = (row.get("csv_source_file") or "").strip()
            prior_source_row = (row.get("csv_source_row") or "").strip()
            prior_eval_set_id = (row.get("csv_eval_set_id") or "").strip()

            meta: dict[str, Any] = {
                "reasoning": (row.get("reasoning") or "").strip(),
                # current import
                "csv_source_file": source_filename,
                "csv_source_row": data_row_idx,
                "csv_imported_at": import_ts,
            }
            # Preserve prior lineage chain when it exists
            if prior_source_file:
                meta["csv_origin_file"] = prior_source_file
            if prior_source_row:
                meta["csv_origin_row"] = prior_source_row
            if prior_eval_set_id:
                meta["csv_origin_eval_set_id"] = prior_eval_set_id

            db.add_question(
                eval_set_id=new_eval_set_id,
                question_text=question_text,
                category=(row.get("category") or "direct_lookup").strip(),
                ground_truth_chunk_ids=gt,
                source_doc_id=(row.get("source_doc_id") or "").strip() or None,
                metadata=meta,
                answer_text=answer_text,
                question_type=(row.get("question_type") or "operator_lookup").strip(),
                persona=(row.get("persona") or "alaska_dpa_operator").strip(),
                intent_family=(row.get("intent_family") or "policy_lookup").strip(),
                difficulty=(row.get("difficulty") or "medium").strip(),
                expected_search_challenge=(row.get("expected_search_challenge") or "").strip(),
                evidence_summary=(row.get("evidence_summary") or "").strip(),
                status=(row.get("status") or "active").strip(),
            )
            imported += 1

    db.update_eval_set_counts(new_eval_set_id)
    return new_eval_set_id, imported
