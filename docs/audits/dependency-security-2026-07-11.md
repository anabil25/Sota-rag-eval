# Dependency Security Review — 2026-07-11

## Results

- `npm audit --audit-level=high`: 0 vulnerabilities after upgrading Vite to 8.1.2.
- Python environment: `pip==26.1.2`; all declared requirements pass `pip check`.
- `pip-audit` reports `PYSEC-2026-113` (`CVE-2026-25087`) against `pyarrow==22.0.0`.

## PyArrow disposition

GraphRAG 3.1.0 and `graphrag-vectors` require `pyarrow~=22.0`, while the advisory is fixed in 23.0.1. Upgrading PyArrow independently breaks the pinned GraphRAG dependency contract.

The advisory describes a use-after-free in Arrow C++ when an application explicitly calls `RecordBatchFileReader::PreBufferMetadata` while reading a crafted IPC file. The advisory states that pre-buffering is disabled by default and that the functionality is not exposed by the Python, Ruby, or C GLib bindings, so those bindings are not vulnerable.

Retrieve uses the Python GraphRAG/PyArrow bindings and does not expose arbitrary Arrow IPC-file ingestion or call the C++ pre-buffer API. The finding is therefore not applicable to the deployed Python path and is explicitly ignored in CI until GraphRAG supports a fixed PyArrow release.

## Required follow-up

- Keep GraphRAG pinned at the audited version until its API migration is intentional.
- Re-evaluate this exception whenever GraphRAG or PyArrow changes.
- Remove the `PYSEC-2026-113` ignore as soon as GraphRAG permits PyArrow 23.0.1 or later.
- Do not add an Arrow IPC-file upload surface without reopening this threat assessment.
