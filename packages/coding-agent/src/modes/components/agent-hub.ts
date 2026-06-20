/**
 * Agent Hub overlay component.
 *
 * One overlay, two views:
 * - Table view: every registered agent except Main (Main IS the ambient
 *   chat), live from the global AgentRegistry — status, unread irc count,
 *   current/last task, last activity. Select with j/k, Enter focuses/opens one,
 *   `r` revives a parked agent, and Ctrl+X twice removes one.
 * - Chat view: per-agent transcript (incremental session-file tail, absorbed
 *   from the old session observer overlay) plus an input line. Submitting
 *   revives a parked agent, then prompts/steers it; the message lands in the
 *   agent's persisted history via the normal prompt path.
 *
 * Replaces the old SessionObserverOverlayComponent (ctrl+s observer).
 */
import * as fs from "node:fs";
import * as path from "node:path";
import type { AgentTool } from "@pk-nerdsaver-ai/pi-agent-core";
import { Container, Ellipsis, matchesKey, type OverlayHandle, type TUI } from "@pk-nerdsaver-ai/pi-tui";
import { formatAge, getProjectDir, logger } from "@pk-nerdsaver-ai/pi-utils";
import { ADVISOR_TRANSCRIPT_FILENAME } from "../../advisor";
import type { KeyId } from "../../config/keybindings";
import type { MessageRenderer } from "../../extensibility/extensions/types";
import { IrcBus } from "../../irc/bus";
import { AgentLifecycleManager } from "../../registry/agent-lifecycle";
import { type AgentRef, AgentRegistry, type AgentStatus, MAIN_AGENT_ID } from "../../registry/agent-registry";
import { USER_INTERRUPT_LABEL } from "../../session/messages";
import { replaceTabs, shortenPath, TRUNCATE_LENGTHS, truncateToWidth } from "../../tools/render-utils";
import type { ObservableSession, SessionObserverRegistry } from "../session-observer-registry";
import { isValidThemeColor, type ThemeColor, theme } from "../theme/theme";
import { matchesSelectDown, matchesSelectUp } from "../utils/keybinding-matchers";
import { AgentTranscriptViewer } from "./agent-transcript-viewer";
import { DynamicBorder } from "./dynamic-border";

/** Refresh cadence for the relative-time column */
const AGE_TICK_MS = 5_000;
/** Double-tap window for the table's left-left "close hub" gesture. */
const LEFT_TAP_WINDOW_MS = 500;
/** Double-tap window for Ctrl+X "remove agent" gesture. */
const REMOVE_TAP_WINDOW_MS = 2000;
/** Compute the max content width for the current terminal, accounting for chrome. */
function contentWidth(): number {
	return Math.max(TRUNCATE_LENGTHS.SHORT, (process.stdout.columns || 80) - 6);
}

/** Sanitize a line for TUI display: replace tabs, then truncate to viewport width. */
function sanitizeLine(text: string, maxWidth?: number): string {
	const singleLine = replaceTabs(text).replace(/[\r\n]+/g, " ");
	return truncateToWidth(singleLine, maxWidth ?? contentWidth());
}

function clampHubLine(line: string, width: number): string {
	return truncateToWidth(line.replace(/[\r\n]+/g, " "), Math.max(1, width - 2), Ellipsis.Omit);
}

const STATUS_ORDER: Record<AgentStatus, number> = { running: 0, idle: 1, parked: 2, aborted: 3 };

function rosterColor(color: string | undefined): ThemeColor | undefined {
	return color && isValidThemeColor(color) ? color : undefined;
}

/**
 * One flattened tree row: an {@link AgentRef} plus its depth (Main root = 0,
 * top-level children = 1) and the pre-built connector prefix that renders the
 * `├─`/`└─` branch and the `│`/space ancestor-continuation columns.
 */
interface HubRow {
	ref: AgentRef;
	depth: number;
	prefix: string;
}

/** Glyph + status word, colored per theme status conventions. */
function statusBadge(status: AgentStatus): string {
	switch (status) {
		case "running":
			return theme.fg("accent", `${theme.status.running} running`);
		case "idle":
			return theme.fg("success", `${theme.status.enabled} idle`);
		case "parked":
			return theme.fg("muted", `${theme.status.shadowed} parked`);
		case "aborted":
			return theme.fg("error", `${theme.status.aborted} aborted`);
	}
}

function registerPersistedSubagents(registry: AgentRegistry, sessionFile: string | null | undefined): void {
	if (!sessionFile?.endsWith(".jsonl")) return;
	const root = sessionFile.slice(0, -6);
	registerPersistedSubagentsFromDir(registry, root, undefined);
}

function registerPersistedSubagentsFromDir(registry: AgentRegistry, dir: string, parentId: string | undefined): void {
	let entries: fs.Dirent[];
	try {
		entries = fs.readdirSync(dir, { withFileTypes: true });
	} catch {
		return;
	}
	for (const entry of entries) {
		if (!entry.isFile() || !entry.name.endsWith(".jsonl") || entry.name.includes(".bak")) continue;
		const sessionFile = path.join(dir, entry.name);
		// The advisor transcript is observability-only: register it as a non-peer
		// `advisor` kind under its owning session so the Hub can show its read-only
		// transcript, but it never joins agent-facing rosters and is not revivable.
		if (entry.name === ADVISOR_TRANSCRIPT_FILENAME) {
			const owner = parentId ?? MAIN_AGENT_ID;
			const advisorId = `${owner}/advisor`;
			const existing = registry.get(advisorId);
			// Never clobber a non-advisor ref that happens to share this id (a freak
			// user task literally named `<owner>/advisor`): leave it, skip the advisor.
			if (existing && existing.kind !== "advisor") continue;
			if (existing?.sessionFile !== sessionFile) {
				// The id is reused across `/new`; refresh it to the current session's file.
				if (existing) registry.unregister(advisorId);
				registry.register({
					id: advisorId,
					displayName: "advisor",
					kind: "advisor",
					parentId: owner,
					session: null,
					sessionFile,
					status: "parked",
				});
			}
			continue;
		}
		const id = entry.name.slice(0, -6);
		if (!registry.get(id)) {
			registry.register({
				id,
				displayName: id,
				kind: "sub",
				parentId: parentId ?? MAIN_AGENT_ID,
				session: null,
				sessionFile,
				status: "parked",
			});
		}
		registerPersistedSubagentsFromDir(registry, path.join(dir, id), id);
	}
}

/** Guest-side proxy for hub actions executed on the collab host. */
export interface AgentHubRemote {
	chat(id: string, text: string): void;
	kill(id: string): void;
	revive(id: string): void;
	/** Mirrors readFileIncremental: text from fromByte (complete JSONL lines), newSize = next fromByte base; null = unavailable. */
	readTranscript(id: string, fromByte: number): Promise<{ text: string; newSize: number } | null>;
}

export interface AgentHubDeps {
	/** Progress/status snapshot source (task lifecycle + progress channels). */
	observers: SessionObserverRegistry;
	/** Keys that toggle the hub closed from inside (app.agents.hub + app.session.observe). */
	hubKeys: KeyId[];
	onDone: () => void;
	requestRender: () => void;
	/** Injectable for tests; defaults to the process-global registry. */
	registry?: AgentRegistry;
	/** Injectable for tests; defaults to the process-global lifecycle manager. */
	lifecycle?: AgentLifecycleManager;
	/** Injectable for tests; defaults to the process-global bus. */
	irc?: IrcBus;
	/** TUI handle for transcript components; tests omit it and get a render-only stub. */
	ui?: TUI;
	/** Tool lookup for transcript renderers (labels, custom render functions). */
	getTool?: (name: string) => AgentTool | undefined;
	/** Extension message renderers for custom messages in the transcript. */
	getMessageRenderer?: (customType: string) => MessageRenderer | undefined;
	/** Cwd used by tool renderers for path shortening; defaults to the project dir. */
	cwd?: string;
	/** Mirrors the main transcript's thinking-block visibility. */
	hideThinkingBlock?: () => boolean;
	/** Keys toggling tool output expansion (app.tools.expand). */
	expandKeys?: KeyId[];
	/** Focus the main view on this agent's live session (ctx.focusAgentSession). When absent (collab guest, tests), Enter opens the in-hub chat view instead. */
	focusAgent?: (id: string) => Promise<void>;
	/** Current main session file; used to seed parked historical subagents after restart. */
	sessionFile?: string | null;
	/** Collab guest: route actions/transcripts to the host instead of local sessions. */
	remote?: AgentHubRemote;
}

export class AgentHubOverlayComponent extends Container {
	#registry: AgentRegistry;
	#observers: SessionObserverRegistry;
	#irc: IrcBus;
	#lifecycle: () => AgentLifecycleManager;
	#onDone: () => void;
	#requestRender: () => void;
	#hubKeys: KeyId[];
	#unsubscribers: Array<() => void> = [];
	#ageTimer: NodeJS.Timeout | undefined;
	#remote: AgentHubRemote | undefined;

	// Table state
	/** Selectable subagent rows in Main→children tree order (Main itself is the non-selectable root header). */
	#rows: HubRow[] = [];
	#selectedRow = 0;
	#notice: string | undefined;
	/** First-seen order per agent id; freezes sibling order while the hub is open. */
	#rowOrder: Map<string, number> | undefined;
	/** Double-tap window state for the table's left-left "close hub" gesture. */
	#lastLeftTap = 0;
	/** Agent-specific Ctrl+X confirmation state. */
	#pendingRemove: { id: string; at: number } | undefined;
	// Transcript-viewer launch deps (passed through to AgentTranscriptViewer).
	#ui: TUI;
	#getTool: ((name: string) => AgentTool | undefined) | undefined;
	#getMessageRenderer: ((customType: string) => MessageRenderer | undefined) | undefined;
	#cwd: string;
	#hideThinkingBlock: (() => boolean) | undefined;
	#expandKeys: KeyId[];
	#focusAgent: ((id: string) => Promise<void>) | undefined;

	// Fullscreen transcript overlay opened by openChat(), if any.
	#transcriptOverlay: OverlayHandle | undefined;
	#transcriptViewer: AgentTranscriptViewer | undefined;

	constructor(deps: AgentHubDeps) {
		super();
		this.#registry = deps.registry ?? AgentRegistry.global();
		this.#observers = deps.observers;
		this.#irc = deps.irc ?? IrcBus.global();
		// Lazy: the lifecycle global self-constructs against the global
		// registry, so only touch it when revive/kill actually needs it.
		this.#lifecycle = () => deps.lifecycle ?? AgentLifecycleManager.global();
		this.#onDone = deps.onDone;
		this.#requestRender = deps.requestRender;
		this.#hubKeys = deps.hubKeys;
		this.#remote = deps.remote;
		this.#ui =
			deps.ui ??
			({
				requestRender: () => deps.requestRender(),
				requestComponentRender: () => deps.requestRender(),
			} as unknown as TUI);
		this.#getTool = deps.getTool;
		this.#getMessageRenderer = deps.getMessageRenderer;
		this.#cwd = deps.cwd ?? getProjectDir();
		this.#hideThinkingBlock = deps.hideThinkingBlock;
		this.#expandKeys = deps.expandKeys ?? ["ctrl+o"];
		this.#focusAgent = deps.focusAgent;

		this.#unsubscribers.push(this.#registry.onChange(() => this.#onDataChange()));
		this.#unsubscribers.push(this.#observers.onChange(() => this.#onDataChange()));
		this.#ageTimer = setInterval(() => this.#requestRender(), AGE_TICK_MS);
		this.#ageTimer.unref?.();

		if (!this.#remote) registerPersistedSubagents(this.#registry, deps.sessionFile);
		this.#refreshRows();
	}

	/**
	 * Whether the table view has no agents to show (every registered agent except
	 * Main, after the persisted-subagent scan in the constructor). The double-←
	 * gesture reads this to stay inert when there is nothing to open.
	 */
	get isEmpty(): boolean {
		return this.#rows.length === 0;
	}

	/** Tear down every subscription and timer. Called by the overlay owner on close. */
	dispose(): void {
		for (const unsubscribe of this.#unsubscribers.splice(0)) unsubscribe();
		if (this.#ageTimer) {
			clearInterval(this.#ageTimer);
			this.#ageTimer = undefined;
		}
		this.#closeTranscriptOverlay();
	}

	override render(width: number): readonly string[] {
		return this.#renderTable(width).map(line => clampHubLine(line, width));
	}

	handleInput(keyData: string): void {
		// The hub/observe keys always close the overlay (toggle semantics)
		for (const key of this.#hubKeys) {
			if (matchesKey(keyData, key)) {
				this.#onDone();
				return;
			}
		}
		this.#handleTableInput(keyData);
	}

	/**
	 * Open the fullscreen transcript viewer for an agent id (public for table Enter
	 * and tests). Mounts {@link AgentTranscriptViewer} as a `fullscreen` overlay so it
	 * owns the alternate screen; the hub table stays mounted underneath and is
	 * restored when the viewer closes. No-op without a real TUI (render-only test stub).
	 */
	openChat(id: string): void {
		if (!this.#registry.get(id)) return;
		if (typeof this.#ui.showOverlay !== "function") return;
		this.#closeTranscriptOverlay();
		this.#notice = undefined;
		const viewer = new AgentTranscriptViewer({
			agentId: id,
			registry: this.#registry,
			remote: this.#remote,
			observers: this.#observers,
			lifecycle: this.#remote ? undefined : this.#lifecycle,
			ui: this.#ui,
			getTool: this.#getTool,
			getMessageRenderer: this.#getMessageRenderer,
			cwd: this.#cwd,
			hideThinkingBlock: this.#hideThinkingBlock,
			expandKeys: this.#expandKeys,
			hubKeys: this.#hubKeys,
			requestRender: this.#requestRender,
			onClose: () => this.#closeTranscriptOverlay(),
			onHubClose: () => {
				this.#closeTranscriptOverlay();
				this.#onDone();
			},
		});
		this.#transcriptViewer = viewer;
		this.#transcriptOverlay = this.#ui.showOverlay(viewer, { width: "100%", margin: 0, fullscreen: true });
		this.#ui.setFocus(viewer);
		this.#requestRender();
	}

	/** Close and dispose the transcript overlay, restoring focus to the hub table. */
	#closeTranscriptOverlay(): void {
		this.#transcriptOverlay?.hide();
		this.#transcriptOverlay = undefined;
		this.#transcriptViewer?.dispose();
		this.#transcriptViewer = undefined;
		if (typeof this.#ui.setFocus === "function") this.#ui.setFocus(this);
		this.#requestRender();
	}

	// ========================================================================
	// Live data plumbing
	// ========================================================================

	#onDataChange(): void {
		this.#refreshRows();
		this.#requestRender();
	}

	#refreshRows(): void {
		const selectedId = this.#selectedRef()?.id;
		const refs = this.#registry.list().filter(ref => ref.id !== MAIN_AGENT_ID);

		// Freeze each agent's first-seen order so siblings keep a stable position
		// while the hub is open (agents heartbeat / bump lastActivity constantly).
		// Seed by status, then recency; new agents append at the end thereafter.
		if (!this.#rowOrder) {
			const seeded = [...refs].sort(
				(a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || b.lastActivity - a.lastActivity,
			);
			this.#rowOrder = new Map(seeded.map((ref, i) => [ref.id, i]));
		} else {
			for (const ref of refs) {
				if (!this.#rowOrder.has(ref.id)) this.#rowOrder.set(ref.id, this.#rowOrder.size);
			}
		}

		this.#rows = this.#buildTree(refs);
		const keptIndex = selectedId ? this.#rows.findIndex(row => row.ref.id === selectedId) : -1;
		this.#selectedRow = keptIndex >= 0 ? keptIndex : Math.min(this.#selectedRow, Math.max(0, this.#rows.length - 1));
	}

	/**
	 * Flatten the agent forest into Main→children tree order. Every non-Main ref
	 * is parented to its `parentId` when that agent is also present, else hoisted
	 * directly under Main; siblings keep the frozen {@link #rowOrder}. Each row
	 * carries its depth (top-level children = 1) and a pre-built connector prefix
	 * (`├─`/`└─` for the branch, `│`/spaces for each ancestor column).
	 */
	#buildTree(refs: AgentRef[]): HubRow[] {
		const known = new Set(refs.map(ref => ref.id));
		const childrenOf = new Map<string, AgentRef[]>();
		for (const ref of refs) {
			const parent =
				ref.parentId && ref.parentId !== ref.id && known.has(ref.parentId) ? ref.parentId : MAIN_AGENT_ID;
			const bucket = childrenOf.get(parent);
			if (bucket) bucket.push(ref);
			else childrenOf.set(parent, [ref]);
		}

		const order = this.#rowOrder;
		const bySibling = (a: AgentRef, b: AgentRef): number =>
			(order?.get(a.id) ?? Number.MAX_SAFE_INTEGER) - (order?.get(b.id) ?? Number.MAX_SAFE_INTEGER);
		// One indentation column is as wide as a connector ("├─ "); the ancestor
		// continuation columns must match so branches line up at every depth.
		const indent = theme.tree.branch.length + 1;
		const continuation = (last: boolean): string =>
			last
				? " ".repeat(indent)
				: `${theme.tree.vertical}${" ".repeat(Math.max(1, indent - theme.tree.vertical.length))}`;

		const rows: HubRow[] = [];
		const visited = new Set<string>();
		const walk = (parentId: string, depth: number, ancestorPrefix: string): void => {
			const kids = childrenOf.get(parentId);
			if (!kids) return;
			kids.sort(bySibling);
			kids.forEach((ref, i) => {
				if (visited.has(ref.id)) return; // defensive: never loop on a malformed parent cycle
				visited.add(ref.id);
				const last = i === kids.length - 1;
				rows.push({ ref, depth, prefix: `${ancestorPrefix}${last ? theme.tree.last : theme.tree.branch} ` });
				walk(ref.id, depth + 1, `${ancestorPrefix}${continuation(last)}`);
			});
		};
		walk(MAIN_AGENT_ID, 1, "");

		// Safety net: a ref whose parent chain never reaches Main (detached/cyclic)
		// would otherwise vanish — surface it as a top-level row so it stays selectable.
		const orphans = refs.filter(ref => !visited.has(ref.id)).sort(bySibling);
		orphans.forEach((ref, i) => {
			if (visited.has(ref.id)) return;
			visited.add(ref.id);
			const last = i === orphans.length - 1;
			rows.push({ ref, depth: 1, prefix: `${last ? theme.tree.last : theme.tree.branch} ` });
			walk(ref.id, 2, continuation(last));
		});
		return rows;
	}

	#selectedRef(): AgentRef | undefined {
		return this.#rows[this.#selectedRow]?.ref;
	}

	#observableFor(id: string): ObservableSession | undefined {
		return this.#observers.getSessions().find(s => s.id === id);
	}

	// ========================================================================
	// Table view
	// ========================================================================

	#renderTable(width: number): string[] {
		const lines: string[] = [];
		lines.push(...new DynamicBorder().render(width));
		const counts = this.#statusSummary();
		lines.push(` ${theme.fg("accent", "Agent Hub")}${counts ? theme.fg("dim", `${theme.sep.dot}${counts}`) : ""}`);
		lines.push(...new DynamicBorder().render(width));

		if (this.#rows.length === 0) {
			lines.push(` ${theme.fg("dim", "no subagents yet — task spawns appear here")}`);
		} else {
			lines.push(this.#renderMainHeader(width));
			const termHeight = process.stdout.rows || 40;
			// Chrome: 2 borders + title + Main root + notice? + blank + hints + border
			const maxVisible = Math.max(3, termHeight - 8 - (this.#notice ? 1 : 0));
			let start = 0;
			if (this.#rows.length > maxVisible) {
				start = Math.min(
					Math.max(0, this.#selectedRow - Math.floor(maxVisible / 2)),
					this.#rows.length - maxVisible,
				);
			}
			const end = Math.min(start + maxVisible, this.#rows.length);
			for (let i = start; i < end; i++) {
				lines.push(this.#renderRow(this.#rows[i], i === this.#selectedRow, width));
			}
			if (end < this.#rows.length) {
				lines.push(` ${theme.fg("dim", `… ${this.#rows.length - end} more`)}`);
			}
		}

		if (this.#notice) {
			lines.push(` ${theme.fg("error", sanitizeLine(this.#notice, Math.max(10, width - 2)))}`);
		}
		lines.push("");
		lines.push(` ${theme.fg("dim", "j/k:select  Enter:open  r:revive  ctrl+x:remove  Esc/←←:close")}`);
		lines.push(...new DynamicBorder().render(width));
		return lines;
	}

	/** Main is the tree root, rendered as a non-selectable header above its children. */
	#renderMainHeader(width: number): string {
		const main = this.#registry.get(MAIN_AGENT_ID);
		const color = rosterColor(main?.color);
		const label = color ? theme.bold(theme.fg(color, MAIN_AGENT_ID)) : theme.bold(MAIN_AGENT_ID);
		const rawLine = main ? ` ${statusBadge(main.status)} ${label}` : ` ${label}`;
		return truncateToWidth(rawLine.replace(/[\r\n]+/g, " "), Math.max(1, width - 1));
	}

	#statusSummary(): string {
		const counts: Record<AgentStatus, number> = { running: 0, idle: 0, parked: 0, aborted: 0 };
		for (const row of this.#rows) {
			counts[row.ref.status]++;
		}
		const parts: string[] = [];
		for (const status of ["running", "idle", "parked", "aborted"] as const) {
			const count = counts[status];
			if (count > 0) parts.push(`${count} ${status}`);
		}
		return parts.join(theme.sep.dot);
	}

	#renderRow(row: HubRow, selected: boolean, width: number): string {
		const { ref } = row;
		const cursor = selected ? theme.fg("accent", theme.nav.cursor) : " ";
		const color = rosterColor(ref.color);
		const idText = color ? theme.bold(theme.fg(color, replaceTabs(ref.id))) : theme.bold(replaceTabs(ref.id));
		const parts: string[] = [statusBadge(ref.status), idText];
		parts.push(theme.fg("dim", replaceTabs(ref.displayName)));
		// Parentage is conveyed by the tree connectors, so the kind stands alone.
		parts.push(theme.fg("dim", ref.kind));
		// Surface the cwd only when it diverges from the parent's (CWD-aware spawns).
		const parentCwd = this.#registry.get(ref.parentId ?? MAIN_AGENT_ID)?.cwd;
		if (ref.cwd && ref.cwd !== parentCwd) {
			parts.push(theme.fg("dim", `cwd ${replaceTabs(shortenPath(ref.cwd))}`));
		}
		const observed = this.#observableFor(ref.id);
		const task = observed?.description ?? observed?.progress?.task;
		if (task) {
			parts.push(theme.fg("muted", sanitizeLine(task, TRUNCATE_LENGTHS.TITLE)));
		}
		const unread = this.#irc.unreadCount(ref.id);
		if (unread > 0) {
			parts.push(theme.fg("warning", `⧉ ${unread}`));
		}
		parts.push(theme.fg("dim", formatAge(Math.max(1, Math.round((Date.now() - ref.lastActivity) / 1000)))));
		const rawLine = ` ${cursor} ${theme.fg("dim", row.prefix)}${parts.join(theme.sep.dot)}`;
		return truncateToWidth(rawLine.replace(/[\r\n]+/g, " "), Math.max(1, width - 1));
	}

	#clearPendingRemove(): void {
		this.#pendingRemove = undefined;
	}

	#handleTableInput(keyData: string): void {
		if (matchesKey(keyData, "escape")) {
			this.#clearPendingRemove();
			this.#onDone();
			return;
		}
		if (matchesKey(keyData, "left")) {
			this.#clearPendingRemove();
			this.#notice = undefined;
			const now = Date.now();
			if (now - this.#lastLeftTap < LEFT_TAP_WINDOW_MS) {
				this.#lastLeftTap = 0;
				this.#onDone();
			} else {
				this.#lastLeftTap = now;
			}
			return;
		}
		if (matchesKey(keyData, "ctrl+x")) {
			this.#handleRemoveTap();
			return;
		}
		if (keyData === "j" || matchesSelectDown(keyData)) {
			this.#clearPendingRemove();
			this.#notice = undefined;
			if (this.#rows.length > 0) {
				this.#selectedRow = Math.min(this.#selectedRow + 1, this.#rows.length - 1);
			}
			this.#requestRender();
			return;
		}
		if (keyData === "k" || matchesSelectUp(keyData)) {
			this.#clearPendingRemove();
			this.#notice = undefined;
			if (this.#rows.length > 0) {
				this.#selectedRow = Math.max(this.#selectedRow - 1, 0);
			}
			this.#requestRender();
			return;
		}
		if (matchesKey(keyData, "enter") || keyData === "\r" || keyData === "\n") {
			const selected = this.#selectedRef();
			if (selected) this.#activateAgent(selected);
			return;
		}
		if (keyData === "r") {
			this.#reviveSelected();
			return;
		}
		// Clear any pending remove confirmation on other keys
		this.#clearPendingRemove();
		this.#notice = undefined;
	}

	/**
	 * Enter on a row: focus the main view on the agent's live session and close
	 * the hub. The transcript then renders through the regular session pipeline —
	 * exact parity by construction. Collab guests (no local sessions) keep the
	 * in-hub chat view.
	 */
	#activateAgent(ref: AgentRef): void {
		this.#clearPendingRemove();
		this.#notice = undefined;
		const focusAgent = this.#focusAgent;
		// Advisor refs are read-only transcripts with no live/ revivable session;
		// open the in-hub chat view (file-backed) instead of trying to focus one.
		if (ref.kind === "advisor" || this.#remote || !focusAgent) {
			this.openChat(ref.id);
			return;
		}
		void (async () => {
			try {
				await focusAgent(ref.id); // ensureLive inside revives parked agents; no parking, no session files
				this.#onDone();
			} catch (error) {
				this.#notice = error instanceof Error ? error.message : String(error);
				this.#requestRender();
			}
		})();
	}

	#reviveSelected(): void {
		this.#clearPendingRemove();
		const ref = this.#selectedRef();
		if (!ref) return;
		if (ref.kind === "advisor") {
			this.#notice = `"${ref.id}" is a read-only advisor transcript — nothing to revive.`;
			this.#requestRender();
			return;
		}
		if (ref.status !== "parked") {
			this.#notice = `Agent "${ref.id}" is ${ref.status} — only parked agents can be revived.`;
			this.#requestRender();
			return;
		}
		this.#notice = undefined;
		if (this.#remote) {
			this.#remote.revive(ref.id);
			this.#requestRender();
			return;
		}
		// Fire-and-forget; failures surface as an inline notice
		this.#lifecycle()
			.ensureLive(ref.id)
			.catch((error: unknown) => {
				this.#notice = error instanceof Error ? error.message : String(error);
				this.#requestRender();
			});
		this.#requestRender();
	}

	#handleRemoveTap(): void {
		const ref = this.#selectedRef();
		if (!ref) {
			this.#clearPendingRemove();
			return;
		}

		const now = Date.now();
		const pending = this.#pendingRemove;
		if (pending?.id === ref.id && now - pending.at < REMOVE_TAP_WINDOW_MS) {
			this.#clearPendingRemove();
			this.#notice = undefined;
			this.#removeAgent(ref);
		} else {
			this.#pendingRemove = { id: ref.id, at: now };
			if (ref.kind === "advisor") {
				this.#notice = `"${ref.id}" is a read-only advisor transcript — cannot be removed.`;
				this.#clearPendingRemove();
			} else {
				this.#notice = `Press Ctrl+X again to remove agent "${ref.id}"`;
			}
		}
		this.#requestRender();
	}

	#removeAgent(ref: AgentRef): void {
		if (ref.kind === "advisor") {
			this.#notice = `"${ref.id}" is a read-only advisor transcript — cannot be removed.`;
			this.#requestRender();
			return;
		}

		if (this.#remote) {
			this.#remote.kill(ref.id);
			this.#refreshRows();
			this.#requestRender();
			return;
		}

		void (async () => {
			try {
				if (ref.status === "running" && ref.session) {
					await ref.session.abort({ reason: USER_INTERRUPT_LABEL });
				}
				await this.#lifecycle().release(ref.id);
				this.#notice = `Removed agent "${ref.id}"`;
			} catch (error) {
				logger.warn("Agent hub: remove failed", { id: ref.id, error: String(error) });
				this.#notice = error instanceof Error ? error.message : String(error);
			}
			this.#refreshRows();
			this.#requestRender();
		})();
	}
}
