# Retrieve — SvelteKit 5 Conversion Plan and UI Conventions

This file adapts the Blog-Svelte rules for this repository. Retrieve is an eval-driven retrieval architecture tool with a Python/FastAPI core, a SQLite run database, Azure AI Search integration, and a current Jinja/HTMX wizard UI. The SvelteKit conversion should make the interface easier to evolve without moving retrieval logic out of the tested Python modules.

Primary goal: build a SvelteKit 5 frontend that feels like an operational workbench for policy-search evaluation, not a marketing site or blog. It should make ingestion, eval generation, architecture selection, provisioning, indexing, comparison, and history review calm, dense, scannable, and hard to break with spacing changes.

## Source of Truth

- Svelte and SvelteKit guidance must come from the Svelte MCP/docs when in doubt.
- The current repo source of truth for business behavior remains `retrieve-core/src/retrieve/`.
- The current web API contract lives in `retrieve-core/src/retrieve/web/app.py`.
- Do not duplicate retrieval, eval, provisioning, or indexing logic in SvelteKit. The UI calls the API or server-side proxy wrappers, and the API continues to call the same core functions as the CLI.

## Recommended Target Shape

Create the SvelteKit app as a new frontend package, keeping `retrieve-core/` intact:

```text
retrieve/
  retrieve-core/                 # existing Python package and FastAPI API
  apps/
    retrieve-ui/                 # new SvelteKit 5 app
      src/
        lib/
          api/                   # typed client helpers for FastAPI/SvelteKit endpoints
          components/            # reusable UI components
          components/workflow/   # ingest/eval/mode/configure/provision/compare widgets
          components/results/    # runs, metrics, failures, evidence panels
          components/forms/      # shared form controls
          server/                # server-only API proxy/auth/config modules
          styles/global.css      # tokens, reset, layers, layout utilities
        routes/
          +layout.svelte
          +layout.server.ts
          +page.server.ts
          +page.svelte
          flow/[step]/+page.server.ts
          flow/[step]/+page.svelte
          runs/+page.server.ts
          runs/+page.svelte
          runs/[id]/+page.server.ts
          runs/[id]/+page.svelte
          eval-sets/+page.server.ts
          eval-sets/[id]/+page.server.ts
          corpus/+page.server.ts
          settings/+page.server.ts
      static/
      tests/
      package.json
      svelte.config.js
      vite.config.ts
```

Use this route map unless product needs change:

| Route             | Purpose                                                         | Current API/Data Source                                |
| ----------------- | --------------------------------------------------------------- | ------------------------------------------------------ |
| `/`               | Dashboard redirect or status overview                           | `/api/status`                                          |
| `/flow/[step]`    | Wizard steps: ingest, eval, mode, configure, provision, compare | `/api/ui/session`, `/api/ui/job/*`, existing read APIs |
| `/runs`           | Completed run table and comparison entry                        | `/api/runs`                                            |
| `/runs/[id]`      | Per-run metrics, category scores, failures, retrieved chunks    | `/api/runs/{run_id}`                                   |
| `/eval-sets`      | Eval set inventory                                              | `/api/eval-sets`                                       |
| `/eval-sets/[id]` | Eval summary and question browser                               | `/api/eval-sets/{id}/summary`, `/questions/browse`     |
| `/corpus`         | Corpus file inventory and policy preview when added             | current corpus output directory or future API          |
| `/settings`       | Config, Azure resource group/location, model defaults           | `/api/status`, `/api/models`, config API if added      |

## SvelteKit Setup

Use SvelteKit with TypeScript and official tooling:

```powershell
cd apps
npx sv create retrieve-ui --template minimal --types ts --add eslint prettier playwright vitest sveltekit-adapter
cd retrieve-ui
npm install
npx sv add mcp
npm run check
npm run build
```

Notes:

- Use `npx sv create` for a new SvelteKit app. Use `npx sv migrate svelte-5` only if importing an older Svelte codebase.
- Add the MCP integration so future Svelte changes can be checked against the current docs.
- Prefer plain CSS with design tokens for this app. Do not add Tailwind unless the project deliberately chooses it and maps every spacing/color token into Tailwind config.
- Use adapter-node if SvelteKit will run beside FastAPI in a container or VM. Use a static adapter only if all server-side proxy/auth needs are removed.

## Svelte 5 Rules

- Always use Svelte 5 runes syntax: `$state`, `$props`, `$derived`, `$effect`, `onclick`, `class:`, snippets, and `{@render}`.
- Never use `<svelte:component>`, `createEventDispatcher`, `on:click`, `export let`, `$$props`, legacy slots, or `$app/stores` in new code.
- Key every `{#each}` block with a stable id: `{#each runs as run (run.id)}`.
- Type route props with generated SvelteKit types where useful: `let { data } = $props();` in Svelte files and `PageServerLoad`/`LayoutServerLoad` in server modules.
- Use `<a>` for route navigation. Use `<button>` only for actions.
- Keep `$effect` for browser side effects only: EventSource wiring, focus management, charts, measurements, or third-party libraries. Data fetching belongs in `load`, form actions, or API helpers.

## SvelteKit Data Boundaries

Keep the backend boundary boring and explicit:

- `+page.server.ts` loads page data from FastAPI or server-only SvelteKit helpers.
- `$lib/server/*` is the only place for private env vars, backend base URLs, auth tokens, or filesystem access.
- Svelte components receive data and render UI. They should not know FastAPI hostnames or secrets.
- Mutations that correspond to native forms should use SvelteKit form actions or call a server-side wrapper.
- JSON-only commands can use `fetch` from server modules or client actions, but keep request/response shapes typed.
- Server-Sent Events for long-running jobs should use `EventSource` in a focused component such as `JobProgressStream.svelte`, pointed at `/api/ui/job/{job_id}/stream` or a SvelteKit proxy endpoint.
- Do not import Python-generated artifacts directly into SvelteKit. Use API responses, generated JSON snapshots, or explicit build-time exports.

Recommended env names:

```text
PRIVATE_RETRIEVE_API_BASE=http://127.0.0.1:8000
PUBLIC_APP_NAME=Retrieve
```

## UI Product Principles

Retrieve is an operator console. The first screen should be useful, not a landing page.

- Optimize for repeated work: running evals, comparing architectures, finding failures, and choosing what to deploy.
- Favor dense but breathable layouts: tables, split panes, metric strips, filters, evidence drawers, and progress logs.
- Use cards only for repeated items or genuinely framed panels. Do not put cards inside cards.
- Prefer data tables for runs/questions/models, definition lists for metric summaries, and details/summary for expandable failure evidence.
- Keep controls close to the data they affect. Avoid giant hero sections, marketing copy, decorative blobs, or oversized headings.
- Make the winning architecture, metric deltas, failures, and cost/risk tradeoffs visually easy to scan.

## Semantic HTML Policies

Use platform semantics before custom interaction patterns:

- App frame: `<nav>` for the step/sidebar navigation, `<main>` for route content, `<aside>` for filters or evidence panes, `<header>` for page-level titles/actions.
- Wizard steps: use ordered lists for step progress when appropriate; use `aria-current="step"` on the current step.
- Forms: use real `<form>`, `<fieldset>`, `<legend>`, `<label>`, `input`, `select`, `textarea`, and `<button type="submit">`.
- Progress: use `<progress>` for determinate progress, `role="status"` or `aria-live="polite"` for job log updates, and `aria-busy` on regions loading job output.
- Metrics: use `<dl>` for labeled values such as recall, MRR, nDCG, latency, cost, and failure count.
- Runs/questions: use `<table>` for tabular comparison data. Do not fake tables with divs.
- Evidence and failures: use `<article>` for retrieved policy snippets, `<blockquote>` for quoted policy text, `<mark>` for matched terms, and `<details>`/`<summary>` for expandable reasoning/failure classification.
- Dates and durations: use `<time datetime="...">` when values represent real timestamps.
- Commands: icon buttons must have accessible names. Destructive actions need explicit labels and confirmation.

## CSS Architecture

Use modern CSS deliberately. The goal is to avoid padding and spacing drift by making layout ownership visible in code.

All global CSS lives in `src/lib/styles/global.css`, imported once from the root layout. Organize it with cascade layers:

```css
@layer reset, tokens, base, layout, components, utilities;
```

Layer rules:

- `reset`: box sizing, sensible form defaults, media defaults, reduced motion defaults.
- `tokens`: design tokens only, usually under `:root` and theme attributes.
- `base`: body, headings, links, tables, forms, focus-visible, selection.
- `layout`: app shell, route shell, stacks, grids, split panes, clusters.
- `components`: shared global component classes only when a Svelte component is not a better owner.
- `utilities`: tiny one-purpose helpers such as visually-hidden or content constraints.

Use scoped `<style>` blocks for component-specific internals. Use `:global` sparingly and only from `global.css` or a component that intentionally owns a child subtree.

## Tokens: Single Source of Truth

All spacing, layout sizing, reusable measures, and structural colors live in `:root` in `src/lib/styles/global.css`. Do not create one-off structural spacing values in routes or components.

Start with this token set and extend only with semantic tokens:

| Token                                           | Value                         | Purpose                                               |
| ----------------------------------------------- | ----------------------------- | ----------------------------------------------------- |
| `--app-sidebar-width`                           | `clamp(14rem, 18vw, 17rem)`   | Primary workflow/sidebar width                        |
| `--app-header-min-block`                        | `clamp(4rem, 8cqi, 5.5rem)`   | Route header rhythm                                   |
| `--gutter`                                      | `clamp(1rem, 3vw, 2.5rem)`    | Page side padding                                     |
| `--space-page-block`                            | `clamp(1rem, 2vw, 1.5rem)`    | Top/bottom content breathing room inside app frame    |
| `--space-section`                               | `clamp(1.75rem, 4vw, 3.5rem)` | Gap between major route sections                      |
| `--content-max`                                 | `min(100%, 86rem)`            | Main operational content width                        |
| `--content-narrow`                              | `min(100%, 58rem)`            | Forms, prose, settings panels                         |
| `--space-2xs` to `--space-3xl`                  | fluid `clamp()` scale         | Component spacing and internal rhythm                 |
| `--gap-tight`, `--gap-normal`, `--gap-spacious` | aliases for the spacing scale | Reusable flex/grid gaps                               |
| `--grid-gap-row`, `--grid-gap-column`           | fluid gap scale               | Intrinsic grids                                       |
| `--metric-card-min`                             | `min(100%, 12rem)`            | Metric summary grid minimum                           |
| `--result-card-min`                             | `min(100%, 18rem)`            | Result/evidence grid minimum                          |
| `--evidence-panel-min`                          | `min(100%, 24rem)`            | Split-pane evidence minimum                           |
| `--filter-panel-width`                          | `clamp(16rem, 24vw, 22rem)`   | Filter/sidebar panel width                            |
| `--table-min`                                   | `48rem`                       | Horizontal scroll threshold for dense tables          |
| `--tap-target`                                  | `2.75rem`                     | Minimum comfortable interactive target                |
| `--rule-size`                                   | `1px`                         | Hairlines and separators                              |
| `--radius-sm`                                   | `4px`                         | Inputs, badges, tiny controls                         |
| `--radius-md`                                   | `8px`                         | Cards and panels; do not exceed unless design changes |

Color tokens should be semantic, not tied to one hue:

```css
:root {
	color-scheme: dark light;
	--color-bg: #0b0f14;
	--color-surface: #111820;
	--color-surface-raised: #17212b;
	--color-border: color-mix(in oklab, CanvasText 18%, transparent);
	--color-text: #eef3f8;
	--color-muted: #a9b6c3;
	--color-accent: #63b3ed;
	--color-success: #4ade80;
	--color-warning: #fbbf24;
	--color-danger: #fb7185;
}
```

Avoid a one-note palette. The current dark blue/purple UI can be refined, but do not let the app become all purple-blue gradients. Use accent colors to encode status and reserve strong color for action, state, and comparison deltas.

## Spacing Ownership Rules

1. Never hard-code structural `padding`, `gap`, `margin`, `inline-size`, `max-inline-size`, grid min widths, or positioning offsets as raw pixels. Use tokens, `clamp()`, `min()`, `max()`, container units, intrinsic grid sizing, or a new semantic token.
2. Fixed pixel values are allowed for hairlines, icon strokes, borders, and tiny optical details only.
3. Each spacing axis has one owner:
   - App sidebar width -> `.app-shell`.
   - Page side gutters -> `.route-shell` via `padding-inline: var(--gutter)`.
   - Page top/bottom breathing -> `.route-shell` via `padding-block: var(--space-page-block)`.
   - Between route sections -> `.route-stack` via `gap: var(--space-section)`.
   - Inside a component -> that component's own grid/flex gap.
4. Components do not set outside margins to push away siblings. Parents own sibling spacing with `gap`.
5. Routes do not add ad hoc wrappers just to get padding. Use shared layout primitives.
6. No mobile media queries for spacing. Fluid tokens handle spacing. Media/container queries change layout only.
7. Use logical properties: `padding-inline`, `margin-block`, `inset-inline-start`, `border-block-end`, `inline-size`, `block-size`.
8. Prefer intrinsic layouts: `repeat(auto-fit, minmax(min(100%, var(--metric-card-min)), 1fr))`, `minmax(0, 1fr)`, `fit-content`, `aspect-ratio`, and `subgrid` where useful.
9. Use container queries for component responsiveness. Use viewport media queries only for app-frame behavior such as collapsing the sidebar.
10. Define stable dimensions for fixed-format elements: step rails, toolbar buttons, metric cells, status badges, tables, and progress rows.

## Shared Layout Primitives

Prefer these global utilities before writing local wrapper CSS:

| Class              | Purpose                                                    |
| ------------------ | ---------------------------------------------------------- |
| `.app-shell`       | Full application frame with sidebar and main region        |
| `.app-main`        | Main content column with `min-inline-size: 0`              |
| `.route-shell`     | Route padding, content width, and page block spacing owner |
| `.route-header`    | Page title, subtitle, and command cluster layout           |
| `.route-stack`     | Vertical section stack with `--space-section` gap          |
| `.page-section`    | Semantic section reset plus scroll margin                  |
| `.content-wide`    | Centered content capped at `--content-max`                 |
| `.content-narrow`  | Centered content capped at `--content-narrow`              |
| `.cluster`         | Wrapping flex row for controls, tags, and command groups   |
| `.toolbar`         | Dense action/filter row with stable control sizing         |
| `.auto-grid`       | Intrinsic responsive grid using semantic min token         |
| `.metric-grid`     | Responsive metrics grid using `--metric-card-min`          |
| `.split-view`      | Content/evidence two-column layout with intrinsic collapse |
| `.table-scroll`    | Horizontal overflow owner for dense tables                 |
| `.prose-policy`    | Readable policy/evidence text rhythm                       |
| `.visually-hidden` | Accessible hidden text utility                             |

Route template:

```svelte
<script lang="ts">
	let { data } = $props();
</script>

<section class="route-shell">
	<div class="content-wide route-stack">
		<header class="route-header">
			<div>
				<p class="eyebrow">Retrieve</p>
				<h1>{data.title}</h1>
				<p>{data.subtitle}</p>
			</div>
			<div class="cluster" aria-label="Page actions">
				<!-- buttons/links -->
			</div>
		</header>

		<section class="page-section" aria-labelledby="section-heading">
			<h2 id="section-heading">Section</h2>
			<!-- content -->
		</section>
	</div>
</section>
```

Root layout template:

```svelte
<script lang="ts">
	import '$lib/styles/global.css';
	import AppSidebar from '$lib/components/AppSidebar.svelte';

	let { data, children } = $props();
</script>

<div class="app-shell">
	<AppSidebar steps={data.steps} />
	<main class="app-main" id="main-content">
		{@render children()}
	</main>
</div>
```

## Component Policies

- Components own internal spacing only. They expose layout through props, snippets, or CSS custom properties.
- Prefer typed props and explicit snippets over generic prop spreading.
- Use CSS custom properties for controlled component variation, for example `--metric-accent` or `--panel-density`.
- Use SVG/icon libraries only where they improve recognition. Buttons need accessible names and stable square dimensions.
- Hover must not be the only path to content. Touch/coarse-pointer users must see the same status and evidence.
- Keep headings proportional to their container. No hero-scale type inside dashboards, sidebars, cards, or tables.
- Text must not overflow buttons, badges, table cells, or cards. Use wrapping, `min-inline-size: 0`, `overflow-wrap: anywhere`, or column changes.

Recommended initial components:

| Component                     | Role                                            |
| ----------------------------- | ----------------------------------------------- |
| `AppSidebar.svelte`           | Workflow navigation and step status             |
| `RouteHeader.svelte`          | Title/subtitle/actions pattern                  |
| `StepStatusRail.svelte`       | Compact step progress for mobile/narrow layouts |
| `JobProgressStream.svelte`    | SSE progress, done/error states, log transcript |
| `MetricGrid.svelte`           | Recall/MRR/nDCG/latency/cost/failure summaries  |
| `RunsTable.svelte`            | Completed run comparison table                  |
| `RunFailureList.svelte`       | Failure classification and evidence summaries   |
| `EvalQuestionBrowser.svelte`  | Filters, pagination, question table             |
| `ArchitectureSelector.svelte` | Test-mode architecture selection                |
| `SotaPathSelector.svelte`     | SOTA path and component toggle matrix           |
| `PolicySnippet.svelte`        | Retrieved chunk display with source metadata    |

## Forms and Controls

- Use native forms for ingestion, eval generation, provisioning settings, CSV import/export, and architecture selection.
- Use segmented controls for mode selection, checkboxes/toggles for architecture options, selects for model choices, and number inputs for numeric settings.
- Keep form labels visible. Placeholder text is not a label.
- Put validation/errors adjacent to the field and connect them with `aria-describedby`.
- Disable submit buttons only while a submission is pending, and show a status region that explains the current job state.
- Long-running form submissions should start a job, then stream progress through `JobProgressStream.svelte`.

## Tables, Metrics, and Evidence

- Use tables for comparisons. Wrap dense tables in `.table-scroll`; the table owns its minimum width with `--table-min`.
- Keep metric cards consistent: label, value, trend/delta, and supporting note. Use `<dl>` or a component that renders equivalent semantics.
- Evidence panels should support quick scanning: policy id, title, source/chunk id, score, matched terms, and quoted excerpt.
- Failure views should expose both aggregate patterns and individual examples: category score, failure type, expected chunk, retrieved chunks, and model explanation if available.
- Do not hide critical result data behind hover-only overlays.

## Migration Phases

1. Inventory and freeze the current web contract.
   - List every current Jinja route, REST endpoint, job kind, and SSE behavior from `retrieve-core/src/retrieve/web/app.py`.
   - Add or update API tests before replacing templates.

2. Scaffold `apps/retrieve-ui`.
   - Use SvelteKit 5, TypeScript, ESLint, Prettier, Vitest, Playwright, and the Svelte MCP add-on.
   - Add `src/lib/styles/global.css` with layers, tokens, base rules, and layout primitives before building screens.

3. Build the app shell first.
   - Convert the current sidebar/step flow into `+layout.svelte`, `AppSidebar.svelte`, and `flow/[step]` routes.
   - Implement shell responsiveness with container queries and one viewport query only if the app frame must collapse.

4. Add typed API access.
   - Create `$lib/server/retrieve-api.ts` for server-side calls to FastAPI.
   - Create shared TypeScript types for status, runs, eval sets, architectures, models, jobs, and question browsing.
   - Keep env/private config in `$lib/server`.

5. Convert read-only screens.
   - Status/dashboard, compare, history, runs, run detail, eval sets, settings.
   - Validate table overflow, metric grids, and evidence layouts before mutations.

6. Convert workflow mutations.
   - Ingest, eval generate/import/export, mode selection, configure, provision, index, evaluate, teardown.
   - Use forms/actions for user input and `JobProgressStream.svelte` for long-running operations.

7. Replace Jinja templates gradually.
   - Keep FastAPI serving APIs while SvelteKit serves UI.
   - Once SvelteKit covers a route, redirect or remove the old template route without changing core behavior.

8. Harden deployment.
   - Decide whether SvelteKit and FastAPI run as separate services, a reverse-proxied pair, or a single container with two processes.
   - Add CORS/proxy config only at the boundary, not inside components.

## Verification Policy

After SvelteKit changes, run:

```powershell
npm run check
npm run test:unit
npm run test:e2e
npm run build
```

For layout work, inspect these routes at mobile, tablet, and desktop widths:

- `/flow/ingest`
- `/flow/eval`
- `/flow/configure`
- `/flow/compare`
- `/runs`
- `/runs/[id]`
- `/eval-sets/[id]`
- `/settings`

Check for horizontal overflow, text overlap, table usability, sidebar collapse, keyboard navigation, visible focus, `aria-live` job updates, and touch/coarse-pointer behavior.

## What Lives Where

| Element                       | Owns                                                       | Does Not Own                             |
| ----------------------------- | ---------------------------------------------------------- | ---------------------------------------- |
| `+layout.svelte`              | App shell, sidebar/main grid, global style import          | Route-specific padding or business logic |
| `.route-shell`                | Page gutters and page block spacing                        | Component internal spacing               |
| `.route-stack`                | Vertical gaps between major sections                       | Child padding/margins                    |
| `AppSidebar.svelte`           | Sidebar internals and step navigation state                | Main content spacing                     |
| `RouteHeader.svelte`          | Header internal layout and action cluster                  | Route shell padding                      |
| `JobProgressStream.svelte`    | EventSource lifecycle, status rendering, transcript layout | Job creation or backend logic            |
| `MetricGrid.svelte`           | Metric card grid and metric semantics                      | Page section spacing                     |
| `$lib/server/retrieve-api.ts` | Backend base URL, credentials, server-side fetch wrappers  | UI rendering                             |
| `$lib/api/types.ts`           | Shared TypeScript response shapes                          | Runtime secrets                          |
| `global.css`                  | Tokens, reset, base, shared layout utilities               | One-off component internals              |

## Non-Negotiables

- SvelteKit UI must remain a thin interface over the tested Python core.
- No layout change should require chasing random padding through route files.
- No client code may contain secrets, Azure credentials, private endpoints, or filesystem assumptions.
- No unkeyed lists, legacy Svelte syntax, fake buttons, fake tables, or hover-only content.
- No decorative backgrounds that make policy text, metrics, failures, or controls harder to read.
- Every route must have a clear shell, a clear content width, and one owner for each spacing axis.
