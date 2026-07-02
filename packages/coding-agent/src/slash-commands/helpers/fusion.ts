import { formatModelString, getModelMatchPreferences, resolveModelRoleValue } from "../../config/model-resolver";
import type { ExtensionUISelectItem } from "../../extensibility/extensions";
import type { InteractiveModeContext } from "../../modes/types";
import {
	FUSION_POOL_MAX_TIER,
	FUSION_POOL_MIN_TIER,
	formatFusionPoolEntries,
	parseFusionPoolEntries,
} from "../../session/fusion-router";
import { computeFusionTokenSplit } from "../../session/fusion-usage";
import type { ParsedSlashCommand, SlashCommandResult, SlashCommandRuntime } from "../types";
import { commandConsumed, parseSubcommand, usage } from "./parse";

/** Valid `fusion.mode` values, mirrored from the settings schema enum. */
const FUSION_MODES = ["off", "delegate", "escalate"] as const;
type FusionModeValue = (typeof FUSION_MODES)[number];

function isFusionMode(value: string): value is FusionModeValue {
	return (FUSION_MODES as readonly string[]).includes(value);
}

/** Best-effort model-selector resolution note so typos surface immediately. */
function resolutionNote(selector: string, runtime: SlashCommandRuntime): string {
	const resolved = resolveModelRoleValue(selector, runtime.session.modelRegistry.getAvailable(), {
		settings: runtime.settings,
		matchPreferences: getModelMatchPreferences(runtime.settings),
		modelRegistry: runtime.session.modelRegistry,
	}).model;
	return resolved
		? ` (resolves to ${resolved.provider}/${resolved.id})`
		: " (warning: does not resolve to an available model right now)";
}

/** One-line tier listing used by `/fusion status` and the pool verbs. */
function describePoolTiers(runtime: SlashCommandRuntime): string[] {
	const pool = parseFusionPoolEntries(runtime.settings.get("fusion.modelPool") ?? []);
	const lines: string[] = [];
	for (let tier = FUSION_POOL_MIN_TIER; tier <= FUSION_POOL_MAX_TIER; tier++) {
		const entry = pool.find(t => t.tier === tier);
		lines.push(`  ${tier}. ${entry ? entry.selector : "(unassigned)"}`);
	}
	return lines;
}

/** Full fusion status block shared by `/fusion` (text mode) and `/fusion status`. */
export function buildFusionStatusText(runtime: SlashCommandRuntime): string {
	const enabled = runtime.settings.get("fusion.enabled") === true;
	const mode = runtime.settings.get("fusion.mode");
	const dynamicRouting = runtime.settings.get("fusion.dynamicRouting") === true;
	const sidekick = runtime.settings.get("fusion.sidekickModel") || "pi/smol";
	const strong = runtime.settings.get("fusion.sidekickStrongModel")?.trim();
	const compact = runtime.settings.get("fusion.compactModel")?.trim();
	const pool = parseFusionPoolEntries(runtime.settings.get("fusion.modelPool") ?? []);

	const active = enabled && mode !== "off";
	const header = `Fusion is ${active ? "ON" : "OFF"}${enabled && mode === "off" ? ' (enabled, but fusion.mode is "off")' : ""}`;
	const lines = [
		header,
		`  Mode:            ${mode}`,
		`  Sidekick model:  ${sidekick}`,
		`  Strong sidekick: ${strong || "(unset)"}`,
		`  Compact model:   ${compact || "(unset)"}`,
		`  Dynamic routing: ${dynamicRouting ? "on" : "off"}`,
	];
	const poolStatus =
		pool.length >= 2
			? dynamicRouting && active
				? "active"
				: "configured, waiting on fusion enabled + dynamic routing"
			: pool.length === 1
				? "needs at least 2 tiers to route"
				: "empty";
	lines.push(`  Pool (${poolStatus}):`);
	lines.push(...describePoolTiers(runtime));
	const { share, sidekickTokens } = computeFusionTokenSplit(runtime.session.getFusionUsageSplit());
	if (active && sidekickTokens > 0) {
		lines.push(`  Delegated:       ${share.toFixed(1)}% of billable tokens to the sidekick`);
	}
	if (!active) {
		lines.push("Enable with /fusion on.");
	}
	return lines.join("\n");
}

/**
 * Pool verbs shared by `/fusion pool …` and the legacy `/fusion-pool` alias.
 * `usagePrefix` keeps usage strings honest for whichever spelling invoked it.
 */
export async function handleFusionPoolArgs(
	args: string,
	runtime: SlashCommandRuntime,
	usagePrefix = "/fusion pool",
): Promise<SlashCommandResult> {
	const { verb, rest } = parseSubcommand(args);
	const pool = parseFusionPoolEntries(runtime.settings.get("fusion.modelPool") ?? []);
	const describePool = (): string => {
		if (pool.length === 0) {
			return `Fusion pool is empty. Assign tiers with ${usagePrefix} set <1-5> <model> (1 = most powerful, 5 = least intelligent).`;
		}
		const status =
			pool.length >= 2
				? runtime.settings.get("fusion.dynamicRouting") === true && runtime.settings.get("fusion.enabled") === true
					? "active"
					: "configured, but needs fusion.enabled + fusion.dynamicRouting to route"
				: "needs at least 2 tiers to route";
		return `Fusion routing pool (1 = most powerful … 5 = least intelligent) — ${status}:\n${describePoolTiers(runtime).join("\n")}`;
	};
	if (!verb || verb === "list" || verb === "status") {
		await runtime.output(describePool());
		return commandConsumed();
	}
	if (verb === "clear") {
		runtime.settings.set("fusion.modelPool", []);
		await runtime.output("Fusion pool cleared.");
		return commandConsumed();
	}
	if (verb === "set") {
		const { verb: tierArg, rest: selector } = parseSubcommand(rest);
		const tier = Number.parseInt(tierArg, 10);
		if (!Number.isInteger(tier) || tier < FUSION_POOL_MIN_TIER || tier > FUSION_POOL_MAX_TIER || !selector.trim()) {
			return usage(
				`Usage: ${usagePrefix} set <1-5> <model-or-alias>  (1 = most powerful, 5 = least intelligent)`,
				runtime,
			);
		}
		const trimmedSelector = selector.trim();
		const next = formatFusionPoolEntries([...pool.filter(t => t.tier !== tier), { tier, selector: trimmedSelector }]);
		runtime.settings.set("fusion.modelPool", next);
		const note = resolutionNote(trimmedSelector, runtime);
		const poolSize = next.length;
		const inactive: string[] = [];
		if (runtime.settings.get("fusion.enabled") !== true) inactive.push("fusion.enabled");
		if (runtime.settings.get("fusion.dynamicRouting") !== true) inactive.push("fusion.dynamicRouting");
		const activation =
			poolSize < 2
				? "\nPool needs at least 2 assigned tiers before routing kicks in."
				: inactive.length > 0
					? `\nConfigured but inactive until ${inactive.join(" and ")} ${inactive.length > 1 ? "are" : "is"} enabled.`
					: "";
		await runtime.output(`Tier ${tier} → ${trimmedSelector}${note}${activation}`);
		return commandConsumed();
	}
	if (verb === "remove" || verb === "rm") {
		const tier = Number.parseInt(rest.trim(), 10);
		if (!Number.isInteger(tier) || tier < FUSION_POOL_MIN_TIER || tier > FUSION_POOL_MAX_TIER) {
			return usage(`Usage: ${usagePrefix} remove <1-5>`, runtime);
		}
		if (!pool.some(t => t.tier === tier)) {
			await runtime.output(`Tier ${tier} is not assigned.`);
			return commandConsumed();
		}
		runtime.settings.set("fusion.modelPool", formatFusionPoolEntries(pool.filter(t => t.tier !== tier)));
		await runtime.output(`Tier ${tier} unassigned.`);
		return commandConsumed();
	}
	return usage(`Usage: ${usagePrefix} [list|set <1-5> <model>|remove <1-5>|clear]`, runtime);
}

/**
 * Enable fusion: flips `fusion.enabled` on and bumps `fusion.mode` off "off"
 * (to the schema default "escalate") so the toggle actually activates the
 * feature instead of leaving it gated by a second setting.
 * Returns the message to show; the TUI wrapper additionally spawns the sidekick.
 */
export function enableFusion(runtime: SlashCommandRuntime): string {
	runtime.settings.set("fusion.enabled", true);
	const parts = ["Fusion enabled."];
	if (runtime.settings.get("fusion.mode") === "off") {
		runtime.settings.set("fusion.mode", "escalate");
		parts.push('fusion.mode was "off" — set to "escalate".');
	}
	const sidekick = runtime.settings.get("fusion.sidekickModel") || "pi/smol";
	parts.push(`Sidekick model: ${sidekick}.`);
	return parts.join(" ");
}

/** Disable fusion. A live sidekick is left running; it stops being advertised next turn. */
export function disableFusion(runtime: SlashCommandRuntime): string {
	runtime.settings.set("fusion.enabled", false);
	return "Fusion disabled. A running sidekick stays alive but is no longer advertised to the main model.";
}

export const FUSION_USAGE =
	"Usage: /fusion [on|off|status|mode <off|delegate|escalate>|routing <on|off>|sidekick <model>|strong <model|clear>|compact <model|clear>|pool <list|set|remove|clear>]";

/** Model-role settings `/fusion` can assign. Table keeps the verb handler and TUI menu in lockstep. */
export const FUSION_MODEL_ROLES = {
	sidekick: { setting: "fusion.sidekickModel", label: "Sidekick model", fallback: "pi/smol", clearable: false },
	strong: { setting: "fusion.sidekickStrongModel", label: "Strong sidekick model", fallback: "", clearable: true },
	compact: { setting: "fusion.compactModel", label: "Compact model", fallback: "", clearable: true },
} as const;
export type FusionModelRole = keyof typeof FUSION_MODEL_ROLES;

/** Shared show/clear/assign flow for the three model-role settings. */
async function handleModelRoleVerb(
	role: FusionModelRole,
	rest: string,
	runtime: SlashCommandRuntime,
): Promise<SlashCommandResult> {
	const { setting, label, fallback, clearable } = FUSION_MODEL_ROLES[role];
	const selector = rest.trim();
	if (!selector) {
		const current = runtime.settings.get(setting)?.trim() || fallback;
		await runtime.output(
			`${label}: ${current || "(unset)"}. Usage: /fusion ${role} <model-or-alias${clearable ? "|clear" : ""}>`,
		);
		return commandConsumed();
	}
	if (clearable && selector.toLowerCase() === "clear") {
		runtime.settings.set(setting, "");
		await runtime.output(`${label} cleared.`);
		return commandConsumed();
	}
	runtime.settings.set(setting, selector);
	await runtime.output(`${label} → ${selector}${resolutionNote(selector, runtime)}`);
	return commandConsumed();
}

/**
 * Text/ACP handler for `/fusion`. Bare invocation prints status (the TUI
 * dispatcher intercepts bare `/fusion` earlier and shows the menu instead).
 */
export async function handleFusionCommand(
	command: ParsedSlashCommand,
	runtime: SlashCommandRuntime,
): Promise<SlashCommandResult> {
	const { verb, rest } = parseSubcommand(command.args);
	switch (verb) {
		case "":
		case "status":
			await runtime.output(buildFusionStatusText(runtime));
			return commandConsumed();
		case "on":
			await runtime.output(enableFusion(runtime));
			return commandConsumed();
		case "off":
			await runtime.output(disableFusion(runtime));
			return commandConsumed();
		case "toggle": {
			const enabled = runtime.settings.get("fusion.enabled") === true;
			await runtime.output(enabled ? disableFusion(runtime) : enableFusion(runtime));
			return commandConsumed();
		}
		case "mode": {
			const value = rest.trim().toLowerCase();
			if (!value) {
				await runtime.output(
					`fusion.mode is "${runtime.settings.get("fusion.mode")}". Usage: /fusion mode <off|delegate|escalate>`,
				);
				return commandConsumed();
			}
			if (!isFusionMode(value)) {
				return usage("Usage: /fusion mode <off|delegate|escalate>", runtime);
			}
			runtime.settings.set("fusion.mode", value);
			await runtime.output(`fusion.mode set to "${value}".`);
			return commandConsumed();
		}
		case "routing": {
			const value = rest.trim().toLowerCase();
			if (value !== "on" && value !== "off") {
				return usage("Usage: /fusion routing <on|off>  (fusion.dynamicRouting)", runtime);
			}
			runtime.settings.set("fusion.dynamicRouting", value === "on");
			await runtime.output(`Dynamic routing ${value}.`);
			return commandConsumed();
		}
		case "sidekick":
		case "strong":
		case "compact":
			return handleModelRoleVerb(verb, rest, runtime);
		case "pool":
			return handleFusionPoolArgs(rest, runtime);
		default:
			return usage(FUSION_USAGE, runtime);
	}
}

/**
 * TUI path for `/fusion <args>`: run the shared verb handler with buffered
 * output, apply the TUI-only side effects (sidekick spawn on enable, live
 * sidekick reconcile on reassignment), and flush one status line.
 */
export async function handleFusionCommandTui(
	command: ParsedSlashCommand,
	ctx: InteractiveModeContext,
): Promise<SlashCommandResult> {
	const messages: string[] = [];
	const runtime: SlashCommandRuntime = {
		session: ctx.session,
		sessionManager: ctx.sessionManager,
		settings: ctx.settings,
		cwd: ctx.sessionManager.getCwd(),
		output: text => {
			messages.push(text);
		},
		refreshCommands: () => ctx.refreshSlashCommandState(),
		reloadPlugins: async () => {},
	};
	const result = await handleFusionCommand(command, runtime);
	const { verb, rest } = parseSubcommand(command.args);
	const active = ctx.settings.get("fusion.enabled") === true && ctx.settings.get("fusion.mode") !== "off";
	if ((verb === "on" || verb === "toggle" || verb === "mode") && active) {
		// Mid-session enable: bring up the sidekick now instead of waiting for a
		// restart. An already-tracked sidekick may have been spawned on a model
		// assigned before this enable — reconcile it instead of trusting the
		// spawn guard (never both: reconcile itself respawns when needed).
		if (ctx.session.getFusionSidekickId()) {
			messages.push(await ctx.reconcileFusionSidekickModel());
		} else {
			void ctx.ensureFusionSidekick();
		}
	} else if (verb === "sidekick" && rest.trim() && active) {
		messages.push(await ctx.reconcileFusionSidekickModel());
	}
	ctx.showStatus(messages.filter(Boolean).join("\n"));
	ctx.editor.setText("");
	return result;
}

const CUSTOM_PICK = "(custom selector…)";
const CLEAR_PICK = "(clear)";

/**
 * Model picker submenu: available models plus a free-text selector entry (so
 * aliases like `pi/smol` stay first-class). Resolves to a selector string,
 * `"clear"`, or undefined on cancel.
 */
async function pickModelSelector(
	ctx: InteractiveModeContext,
	title: string,
	clearable: boolean,
): Promise<string | undefined> {
	const items: ExtensionUISelectItem[] = [
		{ label: CUSTOM_PICK, description: "Type any selector or alias (e.g. pi/smol)" },
		...(clearable ? [{ label: CLEAR_PICK, description: "Unset this model" }] : []),
		...ctx.session.modelRegistry
			.getAvailable()
			.map(model => ({ label: formatModelString(model), description: model.name })),
	];
	const selected = await ctx.showHookSelector(title, items);
	if (selected === undefined) return undefined;
	if (selected === CUSTOM_PICK) {
		const typed = await ctx.showHookInput(title, "provider/id or alias");
		return typed?.trim() || undefined;
	}
	if (selected === CLEAR_PICK) return "clear";
	return selected;
}

/** Mode submenu shared by the main menu and guided setup. */
async function pickFusionMode(ctx: InteractiveModeContext): Promise<string | undefined> {
	return ctx.showHookSelector("Fusion mode", [
		{ label: "escalate", description: "Downgrade at compaction, escalate back when work turns hard (default)" },
		{ label: "delegate", description: "Sidekick delegation only; the main model never downgrades" },
		{ label: "off", description: "Disable fusion behavior while keeping settings" },
	]);
}

/** Pool tier submenu: assign/unassign tiers 1-5 through the shared pool verbs. */
async function showFusionPoolMenu(
	ctx: InteractiveModeContext,
	run: (args: string) => Promise<SlashCommandResult>,
): Promise<void> {
	for (;;) {
		const pool = parseFusionPoolEntries(ctx.settings.get("fusion.modelPool") ?? []);
		const items: ExtensionUISelectItem[] = [];
		for (let tier = FUSION_POOL_MIN_TIER; tier <= FUSION_POOL_MAX_TIER; tier++) {
			const entry = pool.find(t => t.tier === tier);
			items.push({
				label: `Tier ${tier}: ${entry ? entry.selector : "(unassigned)"}`,
				description:
					tier === FUSION_POOL_MIN_TIER
						? "most powerful"
						: tier === FUSION_POOL_MAX_TIER
							? "least intelligent"
							: undefined,
			});
		}
		if (pool.length > 0) items.push({ label: "Clear all", description: "Remove every tier assignment" });
		const selected = await ctx.showHookSelector("Fusion pool (1 = most powerful … 5 = least intelligent)", items);
		if (selected === undefined) return;
		if (selected === "Clear all") {
			await run("pool clear");
			continue;
		}
		const tier = Number.parseInt(selected.slice("Tier ".length), 10);
		const assigned = pool.some(t => t.tier === tier);
		const model = await pickModelSelector(ctx, `Tier ${tier} model`, assigned);
		if (model === undefined) continue;
		await run(model === "clear" ? `pool remove ${tier}` : `pool set ${tier} ${model}`);
	}
}

/** Guided setup: enable → mode → sidekick → compact (optional) → routing → status. */
async function runFusionSetup(
	ctx: InteractiveModeContext,
	run: (args: string) => Promise<SlashCommandResult>,
): Promise<void> {
	await run("on");
	const mode = await pickFusionMode(ctx);
	if (mode) await run(`mode ${mode}`);
	const sidekick = await pickModelSelector(ctx, "Sidekick model", false);
	if (sidekick) await run(`sidekick ${sidekick}`);
	const compact = await pickModelSelector(ctx, "Compact model (optional)", true);
	if (compact) await run(compact === "clear" ? "compact clear" : `compact ${compact}`);
	const routing = await ctx.showHookSelector("Dynamic routing", [
		{ label: "on", description: "Classifier picks a tier at each compaction (needs a 2+ tier pool)" },
		{ label: "off", description: "Static one-shot downgrade to the compact model" },
	]);
	if (routing) await run(`routing ${routing}`);
	await run("status");
}

/**
 * Bare `/fusion` menu: current assignments up front, actions loop until
 * cancelled. Every mutation goes through the shared verb handler so the menu
 * and the text verbs can never drift.
 */
export async function showFusionMenu(ctx: InteractiveModeContext): Promise<void> {
	const run = (args: string) => handleFusionCommandTui({ name: "fusion", args, text: `/fusion ${args}` }, ctx);
	let cursor = 0;
	for (;;) {
		const cfg = ctx.settings;
		const enabled = cfg.get("fusion.enabled") === true;
		const pool = parseFusionPoolEntries(cfg.get("fusion.modelPool") ?? []);
		const items: ExtensionUISelectItem[] = [
			{ label: `Fusion: ${enabled ? "ON" : "OFF"}`, description: "Toggle cost mode (fusion.enabled)" },
			{ label: `Mode: ${cfg.get("fusion.mode")}`, description: "escalate | delegate | off" },
			{
				label: `Sidekick model: ${cfg.get("fusion.sidekickModel") || "pi/smol"}`,
				description: "Cheap warm subagent for menial work",
			},
			{
				label: `Strong sidekick: ${cfg.get("fusion.sidekickStrongModel")?.trim() || "(unset)"}`,
				description: "Sidekick tier for hard stretches (dynamic routing)",
			},
			{
				label: `Compact model: ${cfg.get("fusion.compactModel")?.trim() || "(unset)"}`,
				description: "Main-model downgrade at compaction boundaries",
			},
			{
				label: `Dynamic routing: ${cfg.get("fusion.dynamicRouting") === true ? "on" : "off"}`,
				description: "Classifier re-tiers at each compaction",
			},
			{
				label: `Pool: ${pool.length > 0 ? `${pool.length} tier${pool.length === 1 ? "" : "s"} assigned` : "empty"}`,
				description:
					pool.length > 0
						? formatFusionPoolEntries(pool).join("  ")
						: "Assign models to tiers 1-5 for dynamic routing",
			},
			{ label: "Setup", description: "Guided setup: enable, mode, models, routing" },
			{ label: "Settings", description: "Open the settings menu" },
			{ label: "Status", description: "Print the full fusion status" },
		];
		const selected = await ctx.showHookSelector("Fusion", items, { initialIndex: cursor });
		if (selected === undefined) return;
		cursor = Math.max(
			0,
			items.findIndex(item => typeof item !== "string" && item.label === selected),
		);
		const action = selected.split(":", 1)[0];
		switch (action) {
			case "Fusion":
				await run("toggle");
				break;
			case "Mode": {
				const mode = await pickFusionMode(ctx);
				if (mode) await run(`mode ${mode}`);
				break;
			}
			case "Sidekick model": {
				const picked = await pickModelSelector(ctx, "Sidekick model", false);
				if (picked && picked !== "clear") await run(`sidekick ${picked}`);
				break;
			}
			case "Strong sidekick": {
				const picked = await pickModelSelector(ctx, "Strong sidekick model", true);
				if (picked) await run(picked === "clear" ? "strong clear" : `strong ${picked}`);
				break;
			}
			case "Compact model": {
				const picked = await pickModelSelector(ctx, "Compact model", true);
				if (picked) await run(picked === "clear" ? "compact clear" : `compact ${picked}`);
				break;
			}
			case "Dynamic routing":
				await run(`routing ${cfg.get("fusion.dynamicRouting") === true ? "off" : "on"}`);
				break;
			case "Pool":
				await showFusionPoolMenu(ctx, run);
				break;
			case "Setup":
				await runFusionSetup(ctx, run);
				break;
			case "Settings":
				ctx.showSettingsSelector();
				return;
			case "Status":
				await run("status");
				return;
			default:
				return;
		}
	}
}
