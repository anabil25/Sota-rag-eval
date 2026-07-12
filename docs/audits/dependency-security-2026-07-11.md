# Dependency Security Review — 2026-07-12

## Results

- `npm audit --omit=dev --audit-level=high`: 0 vulnerabilities.
- Full Python environment audit was reconciled against Retrieve's declared dependency graph.
- Fixed minimums now require `cryptography>=48.0.1,<49`, `PyJWT>=2.13.0`,
	`python-multipart>=0.0.31`, `soupsieve>=2.8.4`, `pygments>=2.20.0`, and
	`pytest>=9.0.3`.
- The LightRAG extra now requires `aiohttp>=3.14.1`.
- Resolver dry-run confirms these versions are compatible with the installed
	GraphRAG 3.1.0 and LightRAG 1.5.0 stack.
- `pip check`: no broken requirements after installing the fixed floors.
- Project-scoped `pip-audit retrieve-core` reports no known vulnerabilities after
	applying only the documented Starlette compatibility exceptions below.
- Flask, Werkzeug, Pydantic Settings, and related findings belong to unrelated
	globally installed tooling and are not Retrieve dependencies.
- Two upstream exceptions remain: PyArrow under GraphRAG and NLTK with no fixed release.

## PyArrow disposition

GraphRAG 3.1.0 and `graphrag-vectors` require `pyarrow~=22.0`, while the advisory is fixed in 23.0.1. Upgrading PyArrow independently breaks the pinned GraphRAG dependency contract.

The advisory describes a use-after-free in Arrow C++ when an application explicitly calls `RecordBatchFileReader::PreBufferMetadata` while reading a crafted IPC file. The advisory states that pre-buffering is disabled by default and that the functionality is not exposed by the Python, Ruby, or C GLib bindings, so those bindings are not vulnerable.

Retrieve uses the Python GraphRAG/PyArrow bindings and does not expose arbitrary Arrow IPC-file ingestion or call the C++ pre-buffer API. The finding is therefore not applicable to the deployed Python path and is explicitly ignored in CI until GraphRAG supports a fixed PyArrow release.

## Required follow-up

- Keep GraphRAG pinned at the audited version until its API migration is intentional.
- Re-evaluate this exception whenever GraphRAG or PyArrow changes.
- Remove the `PYSEC-2026-113` ignore as soon as GraphRAG permits PyArrow 23.0.1 or later.
- Do not add an Arrow IPC-file upload surface without reopening this threat assessment.

## NLTK disposition

`pip-audit` reports `PYSEC-2026-597` against NLTK 3.9.4 with no fixed release.
NLTK is pulled only by the optional pinned GraphRAG runtime. It is not used by the
selected production winner, and the deployed GraphRAG job/environment/registry were
removed after evaluation. Keep monitoring upstream and rebuild future GraphRAG images
when a fixed NLTK release becomes available.

## Starlette disposition

The shared environment reports 2026 Starlette advisories whose listed fixed versions
are outside the compatibility range of the current FastAPI release. Retrieve binds its
control API to loopback, requires authorization for mutations, constrains uploads/paths,
and does not deploy FastAPI publicly. Re-evaluate when FastAPI supports the fixed
Starlette line; do not expose the local operation API as a public service meanwhile.
