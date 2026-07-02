/**
 * `/okf` slash command — inspect and validate the project's Open Knowledge
 * Format (OKF) v0.1 knowledge bundle from within a session.
 *
 * Mirrors `omp okf list|show|lint` (see `cli/okf-cli.ts`) but renders plain
 * text through `runtime.output`, since both the TUI and ACP dispatchers share
 * this path and neither wants raw ANSI color codes.
 */
import { type OkfConcept, okfCapability } from "../../capability/okf";
import { loadCapability } from "../../discovery";
import { lintOkfBundle } from "../../okf/parser";
import type { SlashCommandRuntime } from "../types";

async function loadConcepts(cwd: string): Promise<{ items: readonly OkfConcept[]; warnings: readonly string[] }> {
	const result = await loadCapability<OkfConcept>(okfCapability.id, { cwd });
	return { items: result.items, warnings: result.warnings };
}

function formatConceptSummary(concept: OkfConcept): string {
	const typeLabel = concept.type || "index/log";
	const line = `${concept.id}  [${typeLabel}]  ${concept.title}`;
	return concept.description ? `${line}\n  ${concept.description}` : line;
}

async function buildOkfListText(cwd: string): Promise<string> {
	const { items, warnings } = await loadConcepts(cwd);
	if (items.length === 0) {
		return "No OKF concepts found. Create `.wiki/index.md` to start a knowledge bundle.";
	}
	const lines = items.map(formatConceptSummary);
	lines.push("", `${items.length} concept(s) discovered.`);
	if (warnings.length > 0) {
		lines.push(`${warnings.length} load warning(s) — run \`/okf lint\` for details.`);
	}
	return lines.join("\n");
}

async function buildOkfShowText(cwd: string, id: string): Promise<string> {
	if (!id) return "Usage: /okf show <concept-id>";
	const { items } = await loadConcepts(cwd);
	const concept = items.find(item => item.id === id);
	if (!concept) {
		return `No OKF concept found with id "${id}". Run \`/okf list\` to see available ids.`;
	}

	const lines = [concept.title, `id: ${concept.id}  type: ${concept.type || "(none)"}  bundle: ${concept.bundleRoot}`];
	if (concept.description) lines.push(concept.description);
	if (concept.tags.length > 0) lines.push(`tags: ${concept.tags.join(", ")}`);
	lines.push("", concept.body);
	if (concept.links.length > 0) {
		lines.push("", "Links:");
		for (const link of concept.links) {
			const target = link.conceptId ? `${link.target} (${link.conceptId})` : link.target;
			lines.push(`  - ${link.text || link.target} -> ${target}`);
		}
	}
	return lines.join("\n");
}

async function buildOkfLintText(cwd: string): Promise<string> {
	const { items, warnings: loadWarnings } = await loadConcepts(cwd);
	const lintWarnings = lintOkfBundle(items);

	if (loadWarnings.length === 0 && lintWarnings.length === 0) {
		return `✓ ${items.length} concept(s) conform to OKF v0.1`;
	}

	const lines = [
		...loadWarnings.map(warning => `[error] ${warning}`),
		...lintWarnings.map(warning => `[${warning.severity}] ${warning.path}: ${warning.message}`),
	];
	const errorCount = lintWarnings.filter(w => w.severity === "error").length + loadWarnings.length;
	const warningCount = lintWarnings.filter(w => w.severity === "warning").length;
	lines.push("", `${errorCount} error(s), ${warningCount} warning(s) across ${items.length} concept(s).`);
	return lines.join("\n");
}

/** Handle `/okf [list|show <id>|lint]`. */
export async function handleOkfSlashCommand(args: string, runtime: SlashCommandRuntime): Promise<void> {
	const trimmed = args.trim();
	const [subcommand, ...rest] = trimmed.split(/\s+/).filter(Boolean);

	if (!subcommand || subcommand === "list") {
		await runtime.output(await buildOkfListText(runtime.cwd));
		return;
	}
	if (subcommand === "lint") {
		await runtime.output(await buildOkfLintText(runtime.cwd));
		return;
	}
	if (subcommand === "show") {
		await runtime.output(await buildOkfShowText(runtime.cwd, rest.join(" ")));
		return;
	}
	await runtime.output(`Unknown /okf subcommand "${subcommand}". Usage: /okf [list|show <id>|lint]`);
}
