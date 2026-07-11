# Retrieve UI Flow Inventory

This inventory is mirrored by `tests/comprehensive-flows.e2e.ts` and audited to `test-results/audit/ui-flow-audit.jsonl` plus `test-results/audit/mock-api-requests.jsonl`.

## Top-Level Navigation

- Dashboard `/`
  - Open Workflow -> `/flow/ingest`
  - Review Runs -> `/runs`
  - Work area links -> `/flow/eval`, `/flow/configure`, `/flow/compare`
- Sidebar workflow links
  - Ingest `/flow/ingest`
  - Eval `/flow/eval`
  - Mode `/flow/mode`
  - Configure `/flow/configure`
  - Provision `/flow/provision`
  - Index `/flow/index`
  - Run `/flow/run`
  - Compare `/flow/compare`
- Sidebar review links
  - Runs `/runs`
  - Eval Sets `/eval-sets`
  - Settings `/settings`

## Workflow Step Flows

### 1. Ingest

- HTML plugin branch
  - Shows `Source URL or path`
  - Shows `Output directory`
  - Supports request delay
  - `Save Draft` posts UI session state
  - `Start Ingest` starts `ingest` job and streams progress
- Markdown plugin branch
  - Changes source label to `Corpus Directory`
  - Hides `Output directory`
  - `Start Ingest` starts `ingest` job with markdown args

### 2. Eval

- Generate eval set
  - Version label
  - Sample vs full mode
  - Corpus directory
  - Base eval set latest or explicit version
  - Fresh checkbox
  - Operator context textarea
  - `Generate Eval Set` starts `eval_generate` job
  - `Save Steering` saves draft/session state
- Steering chat
  - Adds timestamped steering note to operator context
  - `Append + Save` persists session context
- CSV export
  - Eval set latest or explicit version
  - Output path
  - `Export CSV` posts export request
- CSV import
  - Input path
  - New version label
  - Base eval set
  - Fresh set checkbox
  - `Import CSV` posts import request
- Curation
  - Source version
  - New version
  - Corpus directory
  - More/fewer/add/remove categories
  - Question types
  - Notes
  - `Curate Eval Set` posts steering payload

### 3. Mode

- Test Mode
  - Saves selected mode as `test`
- SOTA Eval Mode
  - Saves selected mode as `sota`
  - Saves selected SOTA path
  - Shows corpus-based recommended SOTA path when available

### 4. Configure

- Test mode configuration
  - Architecture checkbox matrix
  - Embedding model selection
  - `Save Configuration` persists selected architectures/model
- SOTA mode configuration
  - SOTA path selection
  - Component option matrix with multi-select toggles
  - Variant count updates from selected options
  - `Save Configuration` persists path and toggle matrix

### 5. Provision

- Provision Azure resources
  - Resource group
  - Location
  - Keep-on-teardown list
  - `Provision` starts `provision` job
- Run indexing from provision page
  - `Run Indexing` starts `index` job
- Teardown from provision page
  - Browser confirmation can cancel the operation
  - Browser confirmation can accept and starts `teardown` job
- Architecture resource plan and status tables render selected/deployed state

### 6. Index

- Resource group
- Location
- `Build Indexes` starts `index` job

### 7. Run

- Eval set version selection
- Architecture checkbox list
- `Start Evaluation` starts `evaluate` job

### 8. Compare

- Run evaluation from latest eval set
  - Disabled when no eval set exists
  - Starts `evaluate` job when enabled
- Comparison dashboard
  - Winner checkboxes
  - Metrics table
  - SOTA delta column when session mode is SOTA
  - Per-category nDCG table
  - Failure detail expansion
  - Deployment summary and Copilot Studio HTTP action snippet
  - `Save Winners` persists winners
- Cleanup
  - Keep architectures field
  - `Start Teardown` starts `teardown` job

## Review Flows

- Runs `/runs`
  - Empty state when no runs exist
  - Metrics summary
  - Run history table
  - Link to run detail
- Run detail `/runs/:id`
  - Metric summary
  - Category score table
  - Per-question results
  - Failure detail table or no-misses state
- Eval sets `/eval-sets`
  - Empty state when no eval sets exist
  - Eval set cards
  - Link to eval set detail
- Eval set detail `/eval-sets/:id`
  - Metric summary
  - Category/type/persona/intent filters
  - Ground-truth details expansion
- Settings `/settings`
  - Operator context save
  - Capability summary
  - Current config table

## Error/Boundary Flow

- Unknown workflow step `/flow/not-a-step` returns the SvelteKit 404 page.
