"""SQLite data layer — schema, migrations, and query helpers."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 4


class ActiveOperationJobError(RuntimeError):
    """Raised when another environment mutation already owns admission."""


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused with a different request."""


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS eval_sets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    version_label   TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    question_count  INTEGER NOT NULL DEFAULT 0,
    category_counts TEXT NOT NULL DEFAULT '{}',  -- JSON
    notes           TEXT,
    parent_eval_set_id INTEGER REFERENCES eval_sets(id),
    build_mode      TEXT NOT NULL DEFAULT 'extend',
    steering_state  TEXT NOT NULL DEFAULT '{}',  -- JSON
    operator_context TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS eval_questions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_set_id           INTEGER NOT NULL REFERENCES eval_sets(id),
    question_text         TEXT NOT NULL,
    category              TEXT NOT NULL,
    ground_truth_chunk_ids TEXT NOT NULL DEFAULT '[]',  -- JSON array
    source_doc_id         TEXT,
    metadata              TEXT NOT NULL DEFAULT '{}',  -- JSON
    answer_text           TEXT NOT NULL DEFAULT '',
    question_type         TEXT NOT NULL DEFAULT 'direct_lookup',
    persona               TEXT NOT NULL DEFAULT 'domain_user',
    intent_family         TEXT NOT NULL DEFAULT 'general',
    difficulty            TEXT NOT NULL DEFAULT 'medium',
    expected_search_challenge TEXT NOT NULL DEFAULT '',
    evidence_summary      TEXT NOT NULL DEFAULT '',
    status                TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_eq_eval_set ON eval_questions(eval_set_id);
CREATE INDEX IF NOT EXISTS idx_eq_category ON eval_questions(category);
-- idx_eq_qtype, idx_eq_persona, idx_eq_intent_family are created via _run_migrations
-- so they are not listed here (new columns don't exist on upgraded v1 DBs yet)

CREATE TABLE IF NOT EXISTS architectures (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    name                  TEXT NOT NULL,
    config                TEXT NOT NULL DEFAULT '{}',  -- JSON
    resources_provisioned TEXT NOT NULL DEFAULT '{}',  -- JSON
    -- registered|provisioned|indexing|active|failed|torn_down
    status                TEXT NOT NULL DEFAULT 'registered',
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_set_id           INTEGER NOT NULL REFERENCES eval_sets(id),
    architecture_id       INTEGER REFERENCES architectures(id),
    architecture_name     TEXT NOT NULL,
    mode                  TEXT NOT NULL DEFAULT 'test',  -- test|sota
    architecture_config   TEXT NOT NULL DEFAULT '{}',  -- JSON
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    status                TEXT NOT NULL DEFAULT 'running',  -- running|completed|failed
    aggregate_metrics     TEXT NOT NULL DEFAULT '{}'   -- JSON
);
CREATE INDEX IF NOT EXISTS idx_runs_eval_set ON runs(eval_set_id);

CREATE TABLE IF NOT EXISTS run_results (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                INTEGER NOT NULL REFERENCES runs(id),
    question_id           INTEGER NOT NULL REFERENCES eval_questions(id),
    retrieved_chunk_ids   TEXT NOT NULL DEFAULT '[]',  -- JSON array
    scores                TEXT NOT NULL DEFAULT '{}',  -- JSON: recall@5, recall@10, mrr@10, ndcg@10
    latency_ms            REAL,
    -- vocabulary_mismatch|semantic_gap|cross_ref_miss|chunking_boundary
    failure_type          TEXT,
    failure_details       TEXT
);
CREATE INDEX IF NOT EXISTS idx_rr_run ON run_results(run_id);
CREATE INDEX IF NOT EXISTS idx_rr_question ON run_results(question_id);

CREATE TABLE IF NOT EXISTS generation_preferences (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_key             TEXT NOT NULL UNIQUE,
    preferences           TEXT NOT NULL DEFAULT '{}',  -- JSON
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS generation_sessions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_set_id           INTEGER REFERENCES eval_sets(id),
    session_type          TEXT NOT NULL DEFAULT 'generation',
    corpus_coverage_target REAL NOT NULL DEFAULT 0.8,
    corpus_summary_json   TEXT NOT NULL DEFAULT '{}',
    intent_map_json       TEXT NOT NULL DEFAULT '{}',
    plan_json             TEXT NOT NULL DEFAULT '{}',
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_gs_eval_set ON generation_sessions(eval_set_id);

CREATE TABLE IF NOT EXISTS operation_jobs (
    id                    TEXT PRIMARY KEY,
    kind                  TEXT NOT NULL,
    owner_id              TEXT NOT NULL,
    request_hash          TEXT NOT NULL,
    idempotency_key       TEXT NOT NULL DEFAULT '',
    args_json             TEXT NOT NULL DEFAULT '{}',
    state                 TEXT NOT NULL DEFAULT 'queued',
    result_json           TEXT NOT NULL DEFAULT '{}',
    error                 TEXT NOT NULL DEFAULT '',
    external_execution_id TEXT NOT NULL DEFAULT '',
    heartbeat_at          TEXT NOT NULL DEFAULT (datetime('now')),
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    started_at            TEXT,
    completed_at          TEXT,
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_operation_jobs_state ON operation_jobs(state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_operation_jobs_idempotency
    ON operation_jobs(owner_id, idempotency_key)
    WHERE idempotency_key <> '';

CREATE TABLE IF NOT EXISTS operation_events (
    sequence              INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id          TEXT NOT NULL,
    event_json            TEXT NOT NULL,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_operation_events_operation_sequence
    ON operation_events(operation_id, sequence);
"""


class RetrieveDB:
    """SQLite database wrapper for Retrieve."""

    def __init__(self, path: str | Path = "retrieve.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._init_schema()
        return self._conn

    def _init_schema(self):
        conn = self._conn
        if conn is None:
            raise RuntimeError("Database connection is not initialized")

        # Reject databases created by newer application versions before running
        # any DDL that could mutate them.
        version_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
        ).fetchone()
        current = 0
        if version_table:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            current = int(row[0]) if row and row[0] else 0
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {current} is newer than supported version "
                f"{SCHEMA_VERSION}"
            )

        conn.executescript(SCHEMA_SQL)
        self._run_migrations(current)
        if current < SCHEMA_VERSION:
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
        conn.commit()

    def _run_migrations(self, current_version: int):
        """Apply additive schema migrations for existing databases."""
        if current_version < 2:
            # eval_sets extensions
            self._ensure_column(
                "eval_sets",
                "parent_eval_set_id",
                "INTEGER REFERENCES eval_sets(id)",
            )
            self._ensure_column("eval_sets", "build_mode", "TEXT NOT NULL DEFAULT 'extend'")
            self._ensure_column("eval_sets", "steering_state", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column("eval_sets", "operator_context", "TEXT NOT NULL DEFAULT ''")

            # eval_questions extensions
            self._ensure_column("eval_questions", "answer_text", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                "eval_questions",
                "question_type",
                "TEXT NOT NULL DEFAULT 'direct_lookup'",
            )
            self._ensure_column("eval_questions", "persona", "TEXT NOT NULL DEFAULT 'domain_user'")
            self._ensure_column(
                "eval_questions", "intent_family", "TEXT NOT NULL DEFAULT 'general'"
            )
            self._ensure_column("eval_questions", "difficulty", "TEXT NOT NULL DEFAULT 'medium'")
            self._ensure_column(
                "eval_questions", "expected_search_challenge", "TEXT NOT NULL DEFAULT ''"
            )
            self._ensure_column("eval_questions", "evidence_summary", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("eval_questions", "status", "TEXT NOT NULL DEFAULT 'active'")

            # New tables for persistent preferences and generation artifacts
            self.conn.executescript(
                """
            CREATE TABLE IF NOT EXISTS generation_preferences (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_key             TEXT NOT NULL UNIQUE,
                preferences           TEXT NOT NULL DEFAULT '{}',
                updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS generation_sessions (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                eval_set_id           INTEGER REFERENCES eval_sets(id),
                session_type          TEXT NOT NULL DEFAULT 'generation',
                corpus_coverage_target REAL NOT NULL DEFAULT 0.8,
                corpus_summary_json   TEXT NOT NULL DEFAULT '{}',
                intent_map_json       TEXT NOT NULL DEFAULT '{}',
                plan_json             TEXT NOT NULL DEFAULT '{}',
                created_at            TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_eq_qtype ON eval_questions(question_type);
            CREATE INDEX IF NOT EXISTS idx_eq_persona ON eval_questions(persona);
            CREATE INDEX IF NOT EXISTS idx_eq_intent_family ON eval_questions(intent_family);
            CREATE INDEX IF NOT EXISTS idx_gs_eval_set ON generation_sessions(eval_set_id);
            """
            )

        if current_version < 3:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS operation_jobs (
                    id                    TEXT PRIMARY KEY,
                    kind                  TEXT NOT NULL,
                    owner_id              TEXT NOT NULL,
                    request_hash          TEXT NOT NULL,
                    idempotency_key       TEXT NOT NULL DEFAULT '',
                    args_json             TEXT NOT NULL DEFAULT '{}',
                    state                 TEXT NOT NULL DEFAULT 'queued',
                    result_json           TEXT NOT NULL DEFAULT '{}',
                    error                 TEXT NOT NULL DEFAULT '',
                    external_execution_id TEXT NOT NULL DEFAULT '',
                    heartbeat_at          TEXT NOT NULL DEFAULT (datetime('now')),
                    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
                    started_at            TEXT,
                    completed_at          TEXT,
                    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_operation_jobs_state
                    ON operation_jobs(state);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_operation_jobs_idempotency
                    ON operation_jobs(owner_id, idempotency_key)
                    WHERE idempotency_key <> '';
                """
            )

        if current_version < 4:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS operation_events (
                    sequence              INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id          TEXT NOT NULL,
                    event_json            TEXT NOT NULL,
                    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_operation_events_operation_sequence
                    ON operation_events(operation_id, sequence);
                """
            )

    def _ensure_column(self, table: str, column: str, ddl: str):
        row = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        has_col = any(r[1] == column for r in row)
        if has_col:
            return
        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Eval sets ─────────────────────────────────────────────────────

    def create_eval_set(
        self,
        version_label: str,
        notes: str | None = None,
        parent_eval_set_id: int | None = None,
        build_mode: str = "extend",
        steering_state: dict[str, Any] | None = None,
        operator_context: str = "",
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO eval_sets
               (version_label, notes, parent_eval_set_id, build_mode,
                steering_state, operator_context)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                version_label,
                notes,
                parent_eval_set_id,
                build_mode,
                json.dumps(steering_state or {}),
                operator_context,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def update_eval_set_counts(self, eval_set_id: int):
        """Recompute question_count and category_counts from eval_questions."""
        rows = self.conn.execute(
            "SELECT category, COUNT(*) as cnt FROM eval_questions "
            "WHERE eval_set_id = ? GROUP BY category",
            (eval_set_id,),
        ).fetchall()
        cats = {r["category"]: r["cnt"] for r in rows}
        total = sum(cats.values())
        self.conn.execute(
            "UPDATE eval_sets SET question_count = ?, category_counts = ? WHERE id = ?",
            (total, json.dumps(cats), eval_set_id),
        )
        self.conn.commit()

    def get_latest_eval_set(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM eval_sets ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def get_eval_set_by_version(self, version_label: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM eval_sets WHERE version_label = ?", (version_label,)
        ).fetchone()
        return dict(row) if row else None

    # ── Eval questions ────────────────────────────────────────────────

    def add_question(
        self,
        eval_set_id: int,
        question_text: str,
        category: str,
        ground_truth_chunk_ids: list[str],
        source_doc_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        answer_text: str = "",
        question_type: str = "direct_lookup",
        persona: str = "domain_user",
        intent_family: str = "policy_lookup",
        difficulty: str = "medium",
        expected_search_challenge: str = "",
        evidence_summary: str = "",
        status: str = "active",
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO eval_questions
               (eval_set_id, question_text, category, ground_truth_chunk_ids,
                source_doc_id, metadata,
                answer_text, question_type, persona, intent_family, difficulty,
                expected_search_challenge, evidence_summary, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eval_set_id,
                question_text,
                category,
                json.dumps(ground_truth_chunk_ids),
                source_doc_id,
                json.dumps(metadata or {}),
                answer_text,
                question_type,
                persona,
                intent_family,
                difficulty,
                expected_search_challenge,
                evidence_summary,
                status,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_questions(self, eval_set_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM eval_questions WHERE eval_set_id = ? ORDER BY id", (eval_set_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["ground_truth_chunk_ids"] = json.loads(d["ground_truth_chunk_ids"])
            d["metadata"] = json.loads(d["metadata"])
            result.append(d)
        return result

    def get_questions_filtered(
        self,
        eval_set_id: int,
        category: str | None = None,
        question_type: str | None = None,
        persona: str | None = None,
        intent_family: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = ["eval_set_id = ?"]
        params: list[Any] = [eval_set_id]

        if category:
            where.append("category = ?")
            params.append(category)
        if question_type:
            where.append("question_type = ?")
            params.append(question_type)
        if persona:
            where.append("persona = ?")
            params.append(persona)
        if intent_family:
            where.append("intent_family = ?")
            params.append(intent_family)

        params.extend([limit, offset])
        rows = self.conn.execute(
            f"SELECT * FROM eval_questions WHERE {' AND '.join(where)} "
            "ORDER BY id LIMIT ? OFFSET ?",
            params,
        ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            d["ground_truth_chunk_ids"] = json.loads(d["ground_truth_chunk_ids"])
            d["metadata"] = json.loads(d["metadata"])
            result.append(d)
        return result

    def count_questions_filtered(
        self,
        eval_set_id: int,
        category: str | None = None,
        question_type: str | None = None,
        persona: str | None = None,
        intent_family: str | None = None,
    ) -> int:
        where = ["eval_set_id = ?"]
        params: list[Any] = [eval_set_id]
        if category:
            where.append("category = ?")
            params.append(category)
        if question_type:
            where.append("question_type = ?")
            params.append(question_type)
        if persona:
            where.append("persona = ?")
            params.append(persona)
        if intent_family:
            where.append("intent_family = ?")
            params.append(intent_family)

        row = self.conn.execute(
            f"SELECT COUNT(*) AS cnt FROM eval_questions WHERE {' AND '.join(where)}",
            params,
        ).fetchone()
        return int(row["cnt"]) if row else 0

    def get_generation_preferences(self, scope_key: str = "default") -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT preferences FROM generation_preferences WHERE scope_key = ?",
            (scope_key,),
        ).fetchone()
        if not row:
            return {}
        try:
            return json.loads(row["preferences"])
        except json.JSONDecodeError:
            return {}

    def upsert_generation_preferences(
        self,
        preferences: dict[str, Any],
        scope_key: str = "default",
    ):
        self.conn.execute(
            """INSERT INTO generation_preferences (scope_key, preferences, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(scope_key)
               DO UPDATE SET preferences=excluded.preferences, updated_at=excluded.updated_at""",
            (scope_key, json.dumps(preferences), datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def create_generation_session(
        self,
        eval_set_id: int | None,
        session_type: str,
        corpus_coverage_target: float,
        corpus_summary: dict[str, Any],
        intent_map: dict[str, Any],
        plan: dict[str, Any],
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO generation_sessions
               (eval_set_id, session_type, corpus_coverage_target,
                corpus_summary_json, intent_map_json, plan_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                eval_set_id,
                session_type,
                corpus_coverage_target,
                json.dumps(corpus_summary),
                json.dumps(intent_map),
                json.dumps(plan),
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_questions_by_category(self, eval_set_id: int, category: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM eval_questions WHERE eval_set_id = ? AND category = ? ORDER BY id",
            (eval_set_id, category),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["ground_truth_chunk_ids"] = json.loads(d["ground_truth_chunk_ids"])
            d["metadata"] = json.loads(d["metadata"])
            result.append(d)
        return result

    # ── Architectures ─────────────────────────────────────────────────

    def register_architecture(self, name: str, config: dict[str, Any] | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO architectures (name, config) VALUES (?, ?)",
            (name, json.dumps(config or {})),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_architecture(self, name: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM architectures WHERE name = ? ORDER BY id DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row:
            d = dict(row)
            d["config"] = json.loads(d["config"])
            d["resources_provisioned"] = json.loads(d["resources_provisioned"])
            return d
        return None

    # ── Durable operation events ─────────────────────────────────────

    def append_operation_event(
        self,
        operation_id: str,
        event: dict[str, Any],
        *,
        retain: int = 2_000,
    ) -> int:
        cursor = self.conn.execute(
            "INSERT INTO operation_events (operation_id, event_json) VALUES (?, ?)",
            (operation_id, json.dumps(event, ensure_ascii=True)),
        )
        sequence = int(cursor.lastrowid)
        if retain > 0:
            self.conn.execute(
                "DELETE FROM operation_events WHERE operation_id = ? AND sequence < ("
                "SELECT COALESCE(MAX(sequence), 0) - ? FROM operation_events "
                "WHERE operation_id = ?)",
                (operation_id, retain, operation_id),
            )
        self.conn.commit()
        return sequence

    def list_operation_events(
        self,
        operation_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 2_000,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT sequence, event_json FROM operation_events "
            "WHERE operation_id = ? AND sequence > ? "
            "ORDER BY sequence LIMIT ?",
            (operation_id, after_sequence, limit),
        ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            event = json.loads(row["event_json"])
            event["event_sequence"] = int(row["sequence"])
            events.append(event)
        return events

    # ── Durable operation jobs ───────────────────────────────────────

    @staticmethod
    def _operation_job_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        job = dict(row)
        job["args"] = json.loads(job.pop("args_json"))
        job["result"] = json.loads(job.pop("result_json"))
        job["done"] = job["state"] in {
            "succeeded",
            "failed",
            "cancelled",
            "timed_out",
        }
        return job

    def admit_operation_job(
        self,
        *,
        job_id: str,
        kind: str,
        owner_id: str,
        request_hash: str,
        idempotency_key: str = "",
        args: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically replay, reject, or admit one environment mutation."""
        conn = self.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            if idempotency_key:
                existing = conn.execute(
                    "SELECT * FROM operation_jobs WHERE owner_id = ? AND idempotency_key = ?",
                    (owner_id, idempotency_key),
                ).fetchone()
                if existing:
                    existing_job = self._operation_job_dict(existing)
                    if existing_job is None:
                        raise RuntimeError("Durable idempotency lookup failed")
                    if existing_job["request_hash"] != request_hash:
                        raise IdempotencyConflictError(
                            "Idempotency-Key was reused with another request"
                        )
                    conn.commit()
                    return existing_job, True

            active = conn.execute(
                "SELECT id FROM operation_jobs WHERE state IN ('queued', 'running') "
                "ORDER BY created_at LIMIT 1"
            ).fetchone()
            if active:
                raise ActiveOperationJobError(
                    f"Another environment mutation is already running: {active['id']}"
                )

            conn.execute(
                """INSERT INTO operation_jobs
                   (id, kind, owner_id, request_hash, idempotency_key, args_json, state)
                   VALUES (?, ?, ?, ?, ?, ?, 'queued')""",
                (
                    job_id,
                    kind,
                    owner_id,
                    request_hash,
                    idempotency_key,
                    json.dumps(args or {}),
                ),
            )
            row = conn.execute(
                "SELECT * FROM operation_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            conn.commit()
            job = self._operation_job_dict(row)
            if job is None:
                raise RuntimeError("Durable operation job admission failed")
            return job, False
        except Exception:
            conn.rollback()
            raise

    def get_operation_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM operation_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        return self._operation_job_dict(row)

    def get_active_operation_job(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM operation_jobs WHERE state IN ('queued', 'running') "
            "ORDER BY created_at LIMIT 1"
        ).fetchone()
        return self._operation_job_dict(row)

    def update_operation_job(
        self,
        job_id: str,
        *,
        state: str,
        result: dict[str, Any] | None = None,
        error: str = "",
        external_execution_id: str = "",
    ) -> None:
        if state not in {
            "queued",
            "running",
            "succeeded",
            "failed",
            "cancelled",
            "timed_out",
        }:
            raise ValueError(f"Unsupported operation job state: {state}")
        started_at = "datetime('now')" if state == "running" else "started_at"
        completed_at = (
            "datetime('now')"
            if state in {"succeeded", "failed", "cancelled", "timed_out"}
            else "completed_at"
        )
        self.conn.execute(
            f"""UPDATE operation_jobs
                SET state = ?, result_json = ?, error = ?, external_execution_id = ?,
                    heartbeat_at = datetime('now'), updated_at = datetime('now'),
                    started_at = COALESCE(started_at, {started_at}),
                    completed_at = {completed_at}
                WHERE id = ?""",
            (
                state,
                json.dumps(result or {}),
                error[:8_000],
                external_execution_id,
                job_id,
            ),
        )
        self.conn.commit()

    def mark_interrupted_operation_jobs_failed(self) -> int:
        """Fail local jobs that cannot survive a backend process restart."""
        cursor = self.conn.execute(
            """UPDATE operation_jobs
               SET state = 'failed',
                   error = 'Backend restarted before job completion',
                   completed_at = datetime('now'),
                   heartbeat_at = datetime('now'),
                   updated_at = datetime('now')
               WHERE state IN ('queued', 'running')"""
        )
        self.conn.commit()
        return cursor.rowcount

    # ── Runs ──────────────────────────────────────────────────────────

    def create_run(
        self,
        eval_set_id: int,
        architecture_name: str,
        mode: str = "test",
        architecture_config: dict[str, Any] | None = None,
        architecture_id: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO runs
               (eval_set_id, architecture_id, architecture_name, mode, architecture_config)
               VALUES (?, ?, ?, ?, ?)""",
            (
                eval_set_id,
                architecture_id,
                architecture_name,
                mode,
                json.dumps(architecture_config or {}),
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def complete_run(self, run_id: int, aggregate_metrics: dict[str, Any]):
        self.conn.execute(
            "UPDATE runs SET status = 'completed', aggregate_metrics = ? WHERE id = ?",
            (json.dumps(aggregate_metrics), run_id),
        )
        self.conn.commit()

    def fail_run(self, run_id: int):
        self.conn.execute("UPDATE runs SET status = 'failed' WHERE id = ?", (run_id,))
        self.conn.commit()

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row:
            d = dict(row)
            d["architecture_config"] = json.loads(d["architecture_config"])
            d["aggregate_metrics"] = json.loads(d["aggregate_metrics"])
            return d
        return None

    def get_runs_for_eval_set(self, eval_set_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM runs WHERE eval_set_id = ? ORDER BY id", (eval_set_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["architecture_config"] = json.loads(d["architecture_config"])
            d["aggregate_metrics"] = json.loads(d["aggregate_metrics"])
            result.append(d)
        return result

    def get_all_completed_runs(self) -> list[dict[str, Any]]:
        # Only return the latest completed run per architecture name
        rows = self.conn.execute(
            """SELECT r.*, es.version_label AS eval_set_version
               FROM runs r
               LEFT JOIN eval_sets es ON es.id = r.eval_set_id
               INNER JOIN (
                   SELECT architecture_name, MAX(id) AS max_id
                   FROM runs WHERE status = 'completed'
                   GROUP BY architecture_name
               ) latest ON r.id = latest.max_id
               ORDER BY r.id"""
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["architecture_config"] = json.loads(d["architecture_config"])
            d["aggregate_metrics"] = json.loads(d["aggregate_metrics"])
            result.append(d)
        return result

    # ── Run results ───────────────────────────────────────────────────

    def add_result(
        self,
        run_id: int,
        question_id: int,
        retrieved_chunk_ids: list[str],
        scores: dict[str, float],
        latency_ms: float | None = None,
        failure_type: str | None = None,
        failure_details: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO run_results
               (run_id, question_id, retrieved_chunk_ids, scores, latency_ms,
                failure_type, failure_details)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                question_id,
                json.dumps(retrieved_chunk_ids),
                json.dumps(scores),
                latency_ms,
                failure_type,
                failure_details,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_results_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT rr.*, eq.question_text, eq.category, eq.ground_truth_chunk_ids
               FROM run_results rr
               LEFT JOIN eval_questions eq ON eq.id = rr.question_id
               WHERE rr.run_id = ?
               ORDER BY rr.id""",
            (run_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["retrieved_chunk_ids"] = json.loads(d["retrieved_chunk_ids"])
            d["scores"] = json.loads(d["scores"])
            try:
                d["ground_truth_chunk_ids"] = json.loads(d.get("ground_truth_chunk_ids") or "[]")
            except Exception:
                d["ground_truth_chunk_ids"] = []
            result.append(d)
        return result

    def get_failures_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT rr.*, eq.question_text, eq.category, eq.ground_truth_chunk_ids
               FROM run_results rr
               LEFT JOIN eval_questions eq ON eq.id = rr.question_id
               WHERE rr.run_id = ? AND rr.failure_type IS NOT NULL
               ORDER BY rr.id""",
            (run_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["retrieved_chunk_ids"] = json.loads(d["retrieved_chunk_ids"])
            d["scores"] = json.loads(d["scores"])
            try:
                gt = json.loads(d.get("ground_truth_chunk_ids") or "[]")
            except Exception:
                gt = []
            d["ground_truth_chunk_ids"] = gt
            d["expected_chunk_id"] = gt[0] if gt else None
            d["top_retrieved_id"] = (
                d["retrieved_chunk_ids"][0] if d["retrieved_chunk_ids"] else None
            )
            result.append(d)
        return result

    # ── Comparison helpers ────────────────────────────────────────────

    def compare_runs(self, run_ids: list[int]) -> list[dict[str, Any]]:
        """Get aggregate metrics for a list of runs, suitable for side-by-side comparison."""
        results = []
        for rid in run_ids:
            run = self.get_run(rid)
            if run and run["status"] == "completed":
                results.append(run)
        return results

    def get_per_category_scores(self, run_id: int) -> dict[str, dict[str, float]]:
        """Compute average scores per question category for a run."""
        rows = self.conn.execute(
            """SELECT eq.category, rr.scores
               FROM run_results rr
               JOIN eval_questions eq ON eq.id = rr.question_id
               WHERE rr.run_id = ?""",
            (run_id,),
        ).fetchall()

        cat_scores: dict[str, list[dict[str, float]]] = {}
        for r in rows:
            cat = r["category"]
            scores = json.loads(r["scores"])
            cat_scores.setdefault(cat, []).append(scores)

        averages: dict[str, dict[str, float]] = {}
        for cat, score_list in cat_scores.items():
            if not score_list:
                continue
            keys = score_list[0].keys()
            averages[cat] = {
                k: sum(s.get(k, 0) for s in score_list) / len(score_list) for k in keys
            }
        return averages
