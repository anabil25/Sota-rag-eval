<script lang="ts">
	import RouteHeader from '$lib/components/RouteHeader.svelte';

	let { data, form } = $props();

	function settingValue(key: string) {
		const value = data.session[key];
		return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
	}

	function isSelected(key: string, value: string) {
		return settingValue(key) === value;
	}

	function openAiEmbeddingEntries() {
		return Object.entries(data.models.embedding).filter(([, model]) => {
			const provider = typeof model.provider === 'string' ? model.provider : '';
			return provider === 'azure_openai' || provider === 'openai';
		});
	}

	function embeddingLabel(key: string, model: { name?: string; provider?: string }) {
		return `${model.name ?? key}${model.provider ? ` · ${model.provider}` : ''}`;
	}

	const nativeEmbedding = $derived(openAiEmbeddingEntries()[0]?.[0] ?? 'text-embedding-3-large');
	const nativeCopilotTimeout = $derived(String(data.config.copilot.timeout ?? 120));
</script>

<section class="route-shell">
	<div class="content-wide route-stack">
		<RouteHeader
			title="Settings"
			subtitle="Shared defaults for the workflow. Leave fields blank to use Retrieve's native config, or override them per run."
		/>

		{#if form?.message}
			<p class="panel notice" role="status">{form.message}</p>
		{/if}

		<form class="settings-form" method="POST" action="?/save">
			<section class="settings-hero panel">
				<div>
					<p class="eyebrow">How settings work</p>
					<h2>Defaults, not hard requirements</h2>
					<p class="muted">
						Use this page for reusable preferences: corpus location, eval defaults, Azure deploy
						target, and Copilot behavior. Every run step can still override these.
					</p>
				</div>
				<button class="button primary" type="submit">Save Settings</button>
			</section>

			<section class="settings-group" aria-labelledby="preferred-heading">
				<div class="group-copy">
					<p class="eyebrow">Preferred saved things</p>
					<h2 id="preferred-heading">Workflow defaults</h2>
					<p class="muted">
						These are the inputs you otherwise re-enter during Ingest, Eval, Configure, and Run.
					</p>
				</div>

				<div class="settings-grid">
					<article class="settings-card">
						<header>
							<span class="status-pill">Corpus</span>
							<h3>Corpus defaults</h3>
							<p>Where source material comes from and where generated markdown lands.</p>
						</header>
						<div class="field-grid">
							<label>
								<span>Source URL or path</span>
								<input
									name="source"
									value={settingValue('source')}
									placeholder={data.config.corpus.source || 'Use native corpus source'}
								/>
								<small>Blank uses the configured Retrieve corpus source.</small>
							</label>
							<label>
								<span>Plugin</span>
								<select name="plugin">
									<option value="" selected={!settingValue('plugin')}
										>Use native plugin ({data.config.corpus.plugin || 'auto'})</option
									>
									<option value="html" selected={isSelected('plugin', 'html')}
										>HTML crawl & convert</option
									>
									<option value="markdown" selected={isSelected('plugin', 'markdown')}
										>Markdown folder</option
									>
								</select>
							</label>
							<label>
								<span>Corpus output folder</span>
								<input
									name="output"
									value={settingValue('output')}
									placeholder={data.config.corpus.output_dir || 'corpus'}
								/>
							</label>
							<label>
								<span>Request delay seconds</span>
								<input
									name="delay"
									type="number"
									min="0"
									step="0.1"
									value={settingValue('delay')}
									placeholder="0.5"
								/>
							</label>
						</div>
					</article>

					<article class="settings-card">
						<header>
							<span class="status-pill">Eval</span>
							<h3>Golden eval defaults</h3>
							<p>Reusable defaults for building or curating the common eval set.</p>
						</header>
						<div class="field-grid">
							<label>
								<span>Generation mode</span>
								<select name="eval_mode">
									<option value="" selected={!settingValue('eval_mode')}
										>Use native mode ({data.config.eval.mode || 'sample'})</option
									>
									<option value="sample" selected={isSelected('eval_mode', 'sample')}
										>Sample (~25 questions)</option
									>
									<option value="full" selected={isSelected('eval_mode', 'full')}
										>Full corpus coverage</option
									>
								</select>
							</label>
							<label>
								<span>Eval corpus folder</span>
								<input
									name="eval_corpus"
									value={settingValue('eval_corpus')}
									placeholder="corpus"
								/>
							</label>
							<label>
								<span>Base eval set</span>
								<input
									name="base_eval_set"
									value={settingValue('base_eval_set')}
									placeholder={data.status.eval_set?.version_label ?? 'latest'}
								/>
							</label>
							<label class="wide-field">
								<span>Operator context</span>
								<textarea
									name="operator_context"
									rows="5"
									placeholder="Describe your domain, scenario, user persona, and question style."
									>{settingValue('operator_context')}</textarea
								>
								<small>Used by Eval generation; can still be changed from the Eval step.</small>
							</label>
						</div>
					</article>

					<article class="settings-card">
						<header>
							<span class="status-pill">Retrieval</span>
							<h3>Retrieval defaults</h3>
							<p>Preferred model choices for vector, hybrid, graph, and agentic candidates.</p>
						</header>
						<div class="field-grid">
							<label class="wide-field">
								<span>Embedding model</span>
								<select name="selected_embedding">
									<option value="" selected={!settingValue('selected_embedding')}
										>Use native embedding ({nativeEmbedding})</option
									>
									{#each openAiEmbeddingEntries() as [key, model] (key)}
										<option value={key} selected={isSelected('selected_embedding', key)}
											>{embeddingLabel(key, model)}</option
										>
									{/each}
								</select>
							</label>
							<label>
								<span>Vectorizer</span>
								<select name="selected_vectorizer">
									<option value="" selected={!settingValue('selected_vectorizer')}
										>Use native vectorizer (Azure OpenAI)</option
									>
									<option
										value="azure_openai"
										selected={isSelected('selected_vectorizer', 'azure_openai')}
										>Azure OpenAI / OpenAI</option
									>
								</select>
							</label>
						</div>
					</article>
				</div>
			</section>

			<section class="settings-group azure-group" aria-labelledby="azure-heading">
				<div class="group-copy">
					<p class="eyebrow">Azure settings</p>
					<h2 id="azure-heading">Deployment defaults</h2>
					<p class="muted">
						These are only defaults for Provision & Index. The deploy step remains the boundary
						where resources are actually created.
					</p>
				</div>

				<div class="settings-grid three-up">
					<label class="settings-card field-card">
						<span>Resource group</span>
						<input
							name="resource_group"
							value={settingValue('resource_group')}
							placeholder={data.config.azure.resource_group || 'rg-retrieve-dev'}
						/>
						<small>Blank uses the configured Azure resource group.</small>
					</label>
					<label class="settings-card field-card">
						<span>Region</span>
						<input
							name="location"
							value={settingValue('location')}
							placeholder={data.config.azure.location || 'eastus'}
						/>
					</label>
					<label class="settings-card field-card">
						<span>Name prefix</span>
						<input
							name="name_prefix"
							value={settingValue('name_prefix')}
							placeholder={data.config.azure.name_prefix || 'retrieve'}
						/>
					</label>
				</div>
			</section>

			<section class="settings-group" aria-labelledby="copilot-heading">
				<div class="group-copy">
					<p class="eyebrow">Copilot settings</p>
					<h2 id="copilot-heading">Assistant defaults</h2>
					<p class="muted">
						Defaults for Copilot-assisted generation and analysis. Leave blank to use the configured
						provider.
					</p>
				</div>

				<div class="settings-grid three-up">
					<label class="settings-card field-card">
						<span>Model</span>
						<input
							name="copilot_model"
							value={settingValue('copilot_model')}
							placeholder={data.config.copilot.model}
						/>
					</label>
					<label class="settings-card field-card">
						<span>Provider type</span>
						<input
							name="copilot_provider_type"
							value={settingValue('copilot_provider_type')}
							placeholder={data.config.copilot.provider_type ?? 'signed-in-user'}
						/>
					</label>
					<label class="settings-card field-card">
						<span>Timeout seconds</span>
						<input
							name="copilot_timeout"
							type="number"
							min="1"
							step="1"
							value={settingValue('copilot_timeout')}
							placeholder={nativeCopilotTimeout}
						/>
					</label>
				</div>
			</section>

			<div class="settings-footer">
				<button class="button primary" type="submit">Save Settings</button>
			</div>
		</form>
	</div>
</section>

<style>
	.notice {
		border-color: color-mix(in oklab, var(--color-success) 50%, var(--color-border));
		color: var(--color-success);
	}

	h2 {
		font-size: clamp(1.3rem, 2vw, 1.8rem);
		letter-spacing: -0.01em;
	}

	h3 {
		font-size: 1.15rem;
		letter-spacing: -0.005em;
	}

	.eyebrow {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2xs);
		color: var(--color-accent);
		font-size: 0.72rem;
		letter-spacing: 0.08em;
	}

	.eyebrow::before {
		content: '';
		inline-size: 1.4rem;
		block-size: 2px;
		border-radius: 999rem;
		background: linear-gradient(
			90deg,
			var(--color-accent),
			color-mix(in oklab, var(--color-accent) 20%, transparent)
		);
	}

	.settings-form,
	.settings-group,
	.settings-card,
	.field-card,
	.group-copy,
	.settings-hero {
		display: grid;
		gap: var(--space-md);
	}

	.settings-group {
		gap: var(--space-sm);
	}

	.settings-hero {
		grid-template-columns: minmax(0, 1fr) auto;
		align-items: center;
		padding: var(--space-lg);
		border: var(--rule-size) solid var(--color-border-strong);
		background:
			radial-gradient(
				120% 140% at 0% 0%,
				color-mix(in oklab, var(--color-accent) 14%, transparent),
				transparent 55%
			),
			color-mix(in oklab, var(--color-surface-raised) 92%, transparent);
	}

	.group-copy {
		gap: var(--space-2xs);
		padding-inline-start: var(--space-sm);
		border-inline-start: 3px solid color-mix(in oklab, var(--color-accent) 60%, transparent);
	}

	.azure-group .group-copy {
		border-inline-start-color: color-mix(in oklab, var(--color-accent-strong) 70%, transparent);
	}

	.settings-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr));
		gap: var(--space-md);
	}

	.three-up {
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
	}

	.settings-card {
		padding: var(--space-md);
		border: var(--rule-size) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		box-shadow: var(--shadow-panel, 0 1px 2px rgb(0 0 0 / 0.25));
		transition: border-color 0.15s ease;
	}

	.settings-card:focus-within {
		border-color: color-mix(in oklab, var(--color-accent) 55%, var(--color-border-strong));
	}

	.azure-group .settings-card {
		border-color: color-mix(in oklab, var(--color-accent) 32%, var(--color-border-strong));
	}

	.settings-card header {
		display: grid;
		gap: var(--space-2xs);
		padding-block-end: var(--space-xs);
		border-block-end: var(--rule-size) solid var(--color-border);
	}

	.settings-card header p,
	label small {
		color: var(--color-muted);
		font-weight: 500;
	}

	.field-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-sm);
	}

	label {
		display: grid;
		gap: var(--space-2xs);
		color: var(--color-text);
		font-weight: 700;
		font-size: 0.9rem;
	}

	.wide-field {
		grid-column: 1 / -1;
	}

	input,
	select,
	textarea {
		inline-size: 100%;
		min-block-size: var(--tap-target);
		padding: var(--space-xs) var(--space-sm);
		border: var(--rule-size) solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		font-weight: 500;
		transition:
			border-color 0.15s ease,
			box-shadow 0.15s ease;
	}

	input:focus-visible,
	select:focus-visible,
	textarea:focus-visible {
		outline: none;
		border-color: var(--color-accent);
		box-shadow: 0 0 0 3px color-mix(in oklab, var(--color-accent) 30%, transparent);
	}

	textarea {
		resize: vertical;
	}

	.status-pill {
		justify-self: start;
		border-color: color-mix(in oklab, var(--color-accent) 40%, var(--color-border));
		background: color-mix(in oklab, var(--color-accent) 14%, transparent);
		color: var(--color-accent-strong);
	}

	.settings-footer {
		position: sticky;
		inset-block-end: var(--space-sm);
		display: flex;
		justify-content: flex-end;
		padding: var(--space-sm);
		border: var(--rule-size) solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: color-mix(in oklab, var(--color-surface-raised) 92%, transparent);
		backdrop-filter: blur(12px);
	}

	@media (max-width: 48rem) {
		.settings-hero,
		.field-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
