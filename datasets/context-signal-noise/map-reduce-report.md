# Context Signal-to-Noise Dataset — Agentic MapReduce Report
Generated: 2026-07-02T15:32:34.102618+00:00

## Method
Followed Cognition's Agentic MapReduce shape: Plan selectors, Shard deterministically, Map bounded batches in parallel, Reduce worker findings into a single curated dataset, then Verify artifacts. Source: https://devin.ai/blog/agentic-map-reduce

## Artifacts
- `datasets/context-signal-noise/selectors.json`
- `datasets/context-signal-noise/signals.jsonl`
- `datasets/context-signal-noise/curated.jsonl`
- `datasets/context-signal-noise/curated.csv`
- `datasets/context-signal-noise/curated-summary.json`
- `datasets/context-signal-noise/shards/*.json`

## Coverage
- Records: 300
- Shards: {'agent_rules_and_skills.json': 78, 'noise_and_negatives.json': 41, 'repo_docs.json': 162, 'residual_context.json': 0, 'vault_project_wikis.json': 19}
- Initial labels: {'high_signal': 138, 'mixed_signal': 92, 'low_signal_or_noise': 70}
- Curated labels: {'high_signal': 146, 'mixed_signal': 100, 'low_signal_or_noise': 54}
- Map-reducer label decisions: 37
- Actual label changes: 36
- Duplicate content records: 8

## Final schema additions
- `duplicate_of`
- `path_role`
- `kind`
- `is_routing_anchor`
- `under_test_or_fixture`
- `has_contract_structure`
- `enumerate_density`
- `agent_relevance`
- `label_confidence`
- `label_source`

## Reducer findings
- `initial_label` is a selector prior, not ground truth. Map workers found package READMEs, wire-format specs, and curated vault skill notes that need promotion.
- `noise_hits` often measures useful enumeration density: token IDs, archive members, keybindings, command paths, and API lists. Use `enumerate_density` before down-ranking.
- Routing anchors (`AGENTS.md`, `SKILL.md`, ADR/context/glossary companions) should stay available even when prose SNR is mixed. Use `is_routing_anchor` as an orthogonal feature.
- Fixture and template examples are not always garbage: several are synthetic negatives useful for classifier contrast. Keep `under_test_or_fixture` and `kind` rather than deleting them.

## Map-reducer label decisions
- `.omp/skills/codebase-design/DEEPENING.md`: `mixed_signal` → `high_signal` — Mapper: codebase-design DEEPENING companion has high SNR and graph value.
- `.omp/skills/domain-modeling/ADR-FORMAT.md`: `mixed_signal` → `high_signal` — Mapper: ADR format is a domain-modeling routing companion with high SNR.
- `.omp/skills/prototype/SKILL.md`: `mixed_signal` → `high_signal` — Mapper: prototype SKILL.md is a routed skill with high SNR.
- `.omp/skills/triage/OUT-OF-SCOPE.md`: `mixed_signal` → `high_signal` — Mapper: triage OUT-OF-SCOPE is a high-signal companion to triage skill.
- `docs/adding-a-provider.md`: `mixed_signal` → `high_signal` — Mapper: provider-registration procedure.
- `docs/arktype-guide.md`: `mixed_signal` → `high_signal` — Mapper: focused schema runtime reference; promote if present.
- `docs/compaction.md`: `high_signal` → `high_signal` — Mapper: canonical compaction and branch-summarization contract.
- `docs/natives-rust-task-cancellation.md`: `mixed_signal` → `high_signal` — Mapper: native task-cancellation contract.
- `docs/theme.md`: `mixed_signal` → `high_signal` — Mapper: comprehensive theme reference with many headings and high SNR.
- `packages/verifier-extension/skills/llm-as-verifier/references/research-notes.md`: `mixed_signal` → `high_signal` — Mapper: verifier research notes have high SNR and low noise; promote.
- `python/fugu/.agents/skills/llm-as-verifier/references/research-notes.md`: `mixed_signal` → `high_signal` — Mapper: duplicate verifier research notes should share promoted label.
- `python/fugu/docs/model-options-reference.md`: `mixed_signal` → `high_signal` — Mapper: fugu distillation model-options reference.
- `python/omp-rpc/README.md`: `mixed_signal` → `high_signal` — Mapper: OMP RPC bridge contract.
- `vault:Projects/IX-Dashboard-2026/Interconnection Dash Wiki 6-9/skill-conversation-obsidian-capture-discipline.md`: `mixed_signal` → `high_signal` — Mapper: curated Obsidian capture-discipline skill note with durable facts, fast path, failure modes, and provenance.
- `vault:Projects/IX-Dashboard-2026/Interconnection Dash Wiki 6-9/skill-ix-dash-report-accuracy-fast-path.md`: `mixed_signal` → `high_signal` — Mapper: report-accuracy fast-path skill note is an operational post-refresh gate with validated provenance.
- `.omp/skills/diagnosing-bugs/SKILL.md`: `high_signal` → `mixed_signal` — Mapper: diagnosing-bugs is valuable but procedural/noise-heavy; mixed label with routing-anchor feature.
- `.omp/skills/system-prompts/SKILL.md`: `high_signal` → `mixed_signal` — Mapper: system-prompts skill is routing-useful but imperative/template-heavy, so not pure high-signal body context.
- `.omp/skills/tool-prompt-optimization/SKILL.md`: `high_signal` → `mixed_signal` — Mapper: tool-prompt-optimization has high keyword density but lower SNR; mixed is more honest.
- `docs/keybindings.md`: `low_signal_or_noise` → `mixed_signal` — Mapper: canonical keybinding action-ID namespace is small but unique.
- `docs/skills/authoring-marketplaces.md`: `high_signal` → `mixed_signal` — Mapper: authoring-marketplaces is useful but CLI/schema-heavy; noise score is much higher than adjacent authoring docs.
- `packages/agent/CHANGELOG.md`: `low_signal_or_noise` → `mixed_signal` — Noise mapper: large changelog contains release-relevant integration knowledge; not pure noise.
- `packages/ai/CHANGELOG.md`: `low_signal_or_noise` → `mixed_signal` — Noise mapper: large changelog contains model/provider integration knowledge; not pure noise.
- `packages/clips-extension/README.md`: `low_signal_or_noise` → `mixed_signal` — Mapper: clips extension command/integration surface is exclusive context.
- `packages/coding-agent/CHANGELOG.md`: `low_signal_or_noise` → `mixed_signal` — Noise mapper: coding-agent changelog includes feature and policy evolution relevant to context selection.
- `packages/coding-agent/README.md`: `low_signal_or_noise` → `mixed_signal` — Mapper: primary package README is a workspace anchor despite short link-heavy body.
- `packages/coding-agent/test/fixtures/skills/invalid-name-chars/SKILL.md`: `low_signal_or_noise` → `mixed_signal` — Mapper: invalid-name fixture is a useful synthetic negative, not arbitrary noise.
- `packages/coding-agent/test/fixtures/skills/unknown-field/SKILL.md`: `low_signal_or_noise` → `mixed_signal` — Mapper: unknown-field fixture is a useful synthetic negative, not arbitrary noise.
- `packages/hashline/README.md`: `low_signal_or_noise` → `mixed_signal` — Mapper: hashline patch-format README is compact contract context.
- `packages/snapcompact/CHANGELOG.md`: `low_signal_or_noise` → `mixed_signal` — Noise mapper: snapcompact changelog can inform context/compaction history.
- `packages/utils/README.md`: `low_signal_or_noise` → `mixed_signal` — Mapper: utility package namespace is cross-package context; link-list shape underweights it.
- `packages/verifier-extension/CHANGELOG.md`: `low_signal_or_noise` → `mixed_signal` — Noise mapper: verifier skill/orchestrator changes are policy-relevant.
- `packages/verifier-extension/skills/llm-as-verifier/SKILL.md`: `high_signal` → `mixed_signal` — Mapper: verifier skill doubles as reference material; use mixed label and rely on routing-anchor feature.
- `packages/wire/README.md`: `low_signal_or_noise` → `mixed_signal` — Mapper: compact wire contract README is exclusive context despite low initial label.
- `python/fugu/.agents/skills/llm-as-verifier/SKILL.md`: `high_signal` → `mixed_signal` — Mapper: duplicate verifier skill under fugu should share label with canonical copy.
- `python/fugu/prompts/pro/README.md`: `low_signal_or_noise` → `mixed_signal` — Mapper: pro prompt index is a context-selection map.
- `vault:Notes/README.md`: `low_signal_or_noise` → `mixed_signal` — Noise mapper: vault README has the strongest SNR in the negative shard and acts as an index.
- `vault:pk-agent-templates/Template-pk-agent.md`: `low_signal_or_noise` → `mixed_signal` — Noise mapper: template contains a worked agent example, useful as contrast/sample context.

## Top high-signal examples
- `docs/skills/authoring-hooks.md` (skill, score=96, noise=2)
- `docs/skills/authoring-extensions.md` (skill, score=92, noise=2)
- `.omp/skills/mattpocock-skills/writing-great-skills/SKILL.md` (skill, score=78, noise=0)
- `packages/verifier-extension/skills/pk-subagent-orchestrator/SKILL.md` (skill, score=78, noise=0)
- `packages/verifier-extension/skills/pk-dynamic-workflows/SKILL.md` (skill, score=78, noise=1)
- `python/robomp/AGENTS.md` (agent_rules, score=77, noise=4)
- `AGENTS.md` (agent_rules, score=77, noise=15)
- `.omp/skills/tdd/SKILL.md` (skill, score=75, noise=1)
- `.omp/skills/triage/SKILL.md` (skill, score=75, noise=3)
- `.omp/skills/improve-codebase-architecture/SKILL.md` (skill, score=74, noise=0)
- `.omp/skills/domain-modeling/SKILL.md` (skill, score=71, noise=0)
- `.omp/skills/mattpocock-skills/writing-great-skills/GLOSSARY.md` (skill, score=70, noise=0)
- `.omp/skills/triage/AGENT-BRIEF.md` (skill, score=70, noise=3)
- `vault:Projects/IX-Dashboard-2026/Interconnection Dash Wiki 6-9/README.md` (readme, score=67, noise=3)
- `.omp/skills/code-review/SKILL.md` (skill, score=64, noise=0)
- `.omp/skills/codebase-design/SKILL.md` (skill, score=64, noise=0)
- `vault:Projects/IX-Dashboard-2026/Interconnection Dash Wiki 6-9/skill-g-stack-skill-boundary-triage.md` (vault_project_note, score=64, noise=0)
- `vault:Projects/IX-Dashboard-2026/Interconnection Dash Wiki 6-9/Agent-Runtime.md` (vault_project_note, score=64, noise=2)
- `vault:Projects/IX-Dashboard-2026/Interconnection Dash Wiki 6-9/Architecture.md` (vault_project_note, score=64, noise=3)
- `vault:Projects/IX-Dashboard-2026/Interconnection Dash Wiki 6-9/Decisions-Log.md` (vault_project_note, score=64, noise=5)

## Confirmed low-signal/noise examples
- `packages/coding-agent/test/fixtures/apply-patch/scenarios/001_add_file/expected/bar.md` (test_fixture, score=0, noise=57)
- `vault:Notes/README_v4.md` (vault_note, score=2, noise=57)
- `vault:Notes/README_v5.md` (vault_note, score=2, noise=57)
- `vault:Notes/README_v7.md` (vault_note, score=2, noise=57)
- `vault:Notes/README_v9.md` (vault_note, score=2, noise=57)
- `vault:Notes/README_v2.md` (vault_note, score=3, noise=57)
- `packages/ai/src/dialect/prompt-template.md` (other_context, score=4, noise=57)
- `vault:Notes/README_v8.md` (vault_note, score=4, noise=57)
- `vault:Notes/README_v6.md` (vault_note, score=6, noise=59)
- `vault:Notes/README_v3.md` (vault_note, score=6, noise=57)
- `.github/PULL_REQUEST_TEMPLATE.md` (other_context, score=7, noise=58)
- `packages/swarm-extension/CHANGELOG.md` (changelog, score=8, noise=58)
- `packages/coding-agent/test/marketplace/fixtures/valid-marketplace/plugins/hello-plugin/commands/hello.md` (test_fixture, score=8, noise=57)
- `packages/coding-agent/test/marketplace/fixtures/valid-marketplace/plugins/hello-plugin/agents/reviewer.md` (test_fixture, score=10, noise=57)
- `vault:Notes/Log Capture Template.md` (vault_note, score=11, noise=59)
- `vault:Notes/Doc Template.md` (vault_note, score=12, noise=58)
- `vault:Notes/Function Template.md` (vault_note, score=12, noise=58)
- `vault:Notes/Incident Template.md` (vault_note, score=12, noise=58)
- `vault:Notes/Project Template.md` (vault_note, score=13, noise=58)
- `vault:Notes/Runbook Template.md` (vault_note, score=15, noise=58)

## Residual risks
- Curated labels are reducer outputs from sampled map-worker audits, not a gold human-labeled dataset.
- SNR is directional only: wire-format specs and tool docs can look noisy because enumerations are useful contract content.
- Vault paths are machine-local; records should preserve root provenance and not assume cross-machine path stability.
- Duplicate skills/docs should be deduplicated by content_sha256 before training to avoid frequency bias.
