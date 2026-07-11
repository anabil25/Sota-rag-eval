"""Structured GraphRAG 3.1 query and evidence adapter."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

import yaml
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from retrieve.graphrag.settings import validate_graphrag_settings

GraphRagQueryMode = Literal["local", "global", "drift", "basic"]
_IMMUTABLE_RUN_PREFIX = re.compile(
    r"^runs/(?P<fingerprint>[0-9a-f]{64})/(?P<job_id>[A-Za-z0-9-]{3,128})$"
)


@dataclass(frozen=True)
class GraphRagCitation:
    """One selected GraphRAG text unit mapped to a canonical corpus document."""

    text_unit_id: str
    document_id: str
    graphrag_document_id: str
    relative_path: str
    source_url: str
    text: str


@dataclass(frozen=True)
class GraphRagQueryResult:
    """GraphRAG answer plus structured, non-fabricated source evidence."""

    answer: str
    mode: GraphRagQueryMode
    text_unit_ids: tuple[str, ...]
    document_ids: tuple[str, ...]
    citations: tuple[GraphRagCitation, ...]
    context: dict[str, Any]
    latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "mode": self.mode,
            "text_unit_ids": list(self.text_unit_ids),
            "document_ids": list(self.document_ids),
            "citations": [asdict(citation) for citation in self.citations],
            "context": self.context,
            "latency_ms": self.latency_ms,
        }


def load_successful_graphrag_run_config(
    *,
    storage_account: str,
    output_container: str,
    artifact_prefix: str,
    corpus_fingerprint: str,
    search_endpoint: str,
    credential: Any | None = None,
) -> Any:
    """Load and boundary-check one immutable, successful GraphRAG run."""
    normalized_prefix = artifact_prefix.strip("/")
    match = _IMMUTABLE_RUN_PREFIX.fullmatch(normalized_prefix)
    if not match or match.group("fingerprint") != corpus_fingerprint:
        raise ValueError("artifact_prefix is not an immutable run for this corpus fingerprint")
    if not storage_account or not output_container or not search_endpoint:
        raise ValueError("Blob-backed GraphRAG queries require storage and Search endpoints")

    blob_service = BlobServiceClient(
        account_url=f"https://{storage_account}.blob.core.windows.net",
        credential=credential
        or DefaultAzureCredential(exclude_interactive_browser_credential=True),
    )
    container = blob_service.get_container_client(output_container)
    job_id = match.group("job_id")
    try:
        status_payload = container.download_blob(f"jobs/{job_id}/status.json").readall()
        status = json.loads(bytes(status_payload).decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"GraphRAG run status is unavailable for {job_id}") from exc
    if not isinstance(status, dict):
        raise ValueError("GraphRAG run status must be a JSON object")
    if status.get("state") != "succeeded" or status.get("artifact_prefix") != normalized_prefix:
        raise ValueError("GraphRAG query requires a successful immutable run")

    try:
        settings_payload = container.download_blob(
            f"{normalized_prefix}/settings.yaml"
        ).readall()
        settings = yaml.safe_load(bytes(settings_payload).decode("utf-8"))
    except Exception as exc:
        raise ValueError("Persisted GraphRAG settings are unavailable") from exc
    if not isinstance(settings, dict):
        raise ValueError("Persisted GraphRAG settings must be a YAML mapping")
    config = validate_graphrag_settings(settings)

    expected_account_url = f"https://{storage_account}.blob.core.windows.net"
    expected_output_dir = f"{normalized_prefix}/output"
    if (
        config.output_storage.type != "blob"
        or config.output_storage.account_url != expected_account_url
        or config.output_storage.container_name != output_container
        or config.output_storage.base_dir != expected_output_dir
    ):
        raise ValueError("Persisted GraphRAG output storage is outside the approved run boundary")
    if (
        config.vector_store.type != "azure_ai_search"
        or config.vector_store.url != search_endpoint
        or config.vector_store.api_key
    ):
        raise ValueError(
            "Persisted GraphRAG vector storage is outside the approved Search boundary"
        )
    return config


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    if hasattr(value, "tolist"):
        converted = value.tolist()
        return _as_list(converted)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [stripped]
        return _as_list(parsed)
    return [str(value)]


def _selected_frame(frame: Any) -> Any:
    if "in_context" in frame.columns:
        selected = frame[frame["in_context"].fillna(False).astype(bool)]
        if not selected.empty:
            return selected
    return frame


def _iter_context_frames(value: Any, name: str = "context"):
    import pandas as pd

    if isinstance(value, pd.DataFrame):
        yield name.lower(), value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_context_frames(item, str(key))
    elif isinstance(value, list):
        for item in value:
            yield from _iter_context_frames(item, name)


def _row_lookup(frame: Any, *keys: str) -> dict[str, Any]:
    lookup: dict[str, Any] = {}
    if frame is None:
        return lookup
    for position, (_, row) in enumerate(frame.iterrows()):
        lookup[str(position)] = row
        for key in keys:
            if key in frame.columns and row.get(key) is not None:
                lookup[str(row.get(key))] = row
    return lookup


def _context_text_unit_ids(context: Any, tables: dict[str, Any]) -> list[str]:
    text_units = tables.get("text_units")
    if text_units is None:
        return []

    text_lookup = _row_lookup(text_units, "id", "human_readable_id")
    entity_lookup = _row_lookup(tables.get("entities"), "id", "human_readable_id")
    relationship_lookup = _row_lookup(
        tables.get("relationships"), "id", "human_readable_id"
    )
    report_lookup = _row_lookup(
        tables.get("community_reports"),
        "id",
        "human_readable_id",
        "community",
    )
    community_lookup = _row_lookup(tables.get("communities"), "id", "community")

    selected_ids: list[str] = []

    def add(values: Any) -> None:
        for value in _as_list(values):
            if value not in selected_ids:
                selected_ids.append(value)

    for context_name, original_frame in _iter_context_frames(context):
        frame = _selected_frame(original_frame)
        if frame.empty:
            continue
        identifiers = frame["id"].tolist() if "id" in frame.columns else []
        normalized_name = context_name.lower()
        if normalized_name in {"sources", "source", "text_units", "text unit"}:
            for identifier in identifiers:
                row = text_lookup.get(str(identifier))
                if row is not None:
                    add(row.get("id"))
        elif normalized_name in {"entities", "entity"}:
            for identifier in identifiers:
                row = entity_lookup.get(str(identifier))
                if row is not None:
                    add(row.get("text_unit_ids"))
        elif normalized_name in {"relationships", "relationship"}:
            for identifier in identifiers:
                row = relationship_lookup.get(str(identifier))
                if row is not None:
                    add(row.get("text_unit_ids"))
        elif normalized_name in {"reports", "report", "communities", "community"}:
            for identifier in identifiers:
                report = report_lookup.get(str(identifier))
                community_id = report.get("community") if report is not None else identifier
                community = community_lookup.get(str(community_id))
                if community is not None:
                    add(community.get("text_unit_ids"))

        if "text_unit_ids" in frame.columns:
            for values in frame["text_unit_ids"].tolist():
                add(values)

    return selected_ids


def _json_safe(value: Any) -> Any:
    import pandas as pd

    if isinstance(value, pd.DataFrame):
        return [_json_safe(record) for record in value.to_dict(orient="records")]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def build_graphrag_evidence(
    context: Any,
    tables: dict[str, Any],
    corpus_manifest: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[GraphRagCitation, ...]]:
    """Map selected GraphRAG context rows to canonical corpus evidence."""
    text_units = tables.get("text_units")
    if text_units is None:
        return (), (), ()
    text_lookup = _row_lookup(text_units, "id", "human_readable_id")
    manifest_lookup = {
        str(document["graphrag_document_id"]): document
        for document in corpus_manifest["documents"]
    }

    selected_text_unit_ids = _context_text_unit_ids(context, tables)
    citations: list[GraphRagCitation] = []
    document_ids: list[str] = []
    raw_text_unit_ids: list[str] = []
    for selected_id in selected_text_unit_ids:
        row = text_lookup.get(str(selected_id))
        if row is None:
            continue
        text_unit_id = str(row.get("id"))
        graphrag_document_id = str(row.get("document_id") or "")
        manifest_document = manifest_lookup.get(graphrag_document_id)
        if manifest_document is None:
            raise RuntimeError(
                "GraphRAG selected evidence whose document ID is absent from the "
                f"canonical corpus manifest: {graphrag_document_id or '<empty>'}"
            )
        canonical_id = str(manifest_document["document_id"])
        if text_unit_id not in raw_text_unit_ids:
            raw_text_unit_ids.append(text_unit_id)
        if canonical_id not in document_ids:
            document_ids.append(canonical_id)
        if all(citation.text_unit_id != text_unit_id for citation in citations):
            citations.append(
                GraphRagCitation(
                    text_unit_id=text_unit_id,
                    document_id=canonical_id,
                    graphrag_document_id=graphrag_document_id,
                    relative_path=str(manifest_document["relative_path"]),
                    source_url=str(manifest_document["source_url"]),
                    text=str(row.get("text") or ""),
                )
            )

    return tuple(raw_text_unit_ids), tuple(document_ids), tuple(citations)


async def _load_query_tables(config: Any, mode: GraphRagQueryMode) -> dict[str, Any]:
    from graphrag.data_model.data_reader import DataReader
    from graphrag_storage import create_storage
    from graphrag_storage.tables.table_provider_factory import create_table_provider

    storage = create_storage(config.output_storage)
    table_provider = create_table_provider(config.table_provider, storage=storage)
    reader = DataReader(table_provider)
    required_by_mode = {
        "local": [
            "entities",
            "communities",
            "community_reports",
            "text_units",
            "relationships",
        ],
        "global": ["entities", "communities", "community_reports", "text_units"],
        "drift": [
            "entities",
            "communities",
            "community_reports",
            "text_units",
            "relationships",
        ],
        "basic": ["text_units"],
    }
    tables = {
        name: await getattr(reader, name)()
        for name in required_by_mode[mode]
    }
    if mode == "local" and await table_provider.has("covariates"):
        tables["covariates"] = await reader.covariates()
    else:
        tables["covariates"] = None
    return tables


async def execute_graphrag_query(
    *,
    config: Any,
    corpus_manifest: dict[str, Any],
    query: str,
    mode: GraphRagQueryMode = "local",
    response_type: str = "Multiple Paragraphs",
    community_level: int = 2,
    dynamic_community_selection: bool = False,
) -> GraphRagQueryResult:
    """Load persisted GraphRAG tables and execute a public query API."""
    import graphrag.api as api

    started = time.perf_counter()
    tables = await _load_query_tables(config, mode)
    if mode == "local":
        answer, context = await api.local_search(
            config=config,
            entities=tables["entities"],
            communities=tables["communities"],
            community_reports=tables["community_reports"],
            text_units=tables["text_units"],
            relationships=tables["relationships"],
            covariates=tables["covariates"],
            community_level=community_level,
            response_type=response_type,
            query=query,
        )
    elif mode == "global":
        answer, context = await api.global_search(
            config=config,
            entities=tables["entities"],
            communities=tables["communities"],
            community_reports=tables["community_reports"],
            community_level=community_level,
            dynamic_community_selection=dynamic_community_selection,
            response_type=response_type,
            query=query,
        )
    elif mode == "drift":
        answer, context = await api.drift_search(
            config=config,
            entities=tables["entities"],
            communities=tables["communities"],
            community_reports=tables["community_reports"],
            text_units=tables["text_units"],
            relationships=tables["relationships"],
            community_level=community_level,
            response_type=response_type,
            query=query,
        )
    else:
        answer, context = await api.basic_search(
            config=config,
            text_units=tables["text_units"],
            response_type=response_type,
            query=query,
        )

    text_unit_ids, document_ids, citations = build_graphrag_evidence(
        context,
        tables,
        corpus_manifest,
    )
    answer_text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    return GraphRagQueryResult(
        answer=answer_text,
        mode=mode,
        text_unit_ids=text_unit_ids,
        document_ids=document_ids,
        citations=citations,
        context=_json_safe(context),
        latency_ms=(time.perf_counter() - started) * 1_000,
    )
