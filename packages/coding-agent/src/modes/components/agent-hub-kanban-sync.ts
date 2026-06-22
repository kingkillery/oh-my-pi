import type { AgentRef } from "../../registry/agent-registry";

const DEFAULT_KANBAN_COMMAND = Bun.env.OMP_KANBAN_CLI?.trim() || "pk-kanban";
const TASK_KEY_PREFIX = "omp-agent-hub";

export interface KanbanCliRunOptions {
	cwd: string;
}

export interface KanbanCliRunResult {
	exitCode: number;
	stdout: string;
	stderr: string;
}

export interface KanbanCliRunner {
	run(command: string, args: string[], options: KanbanCliRunOptions): Promise<KanbanCliRunResult>;
}

export interface AgentHubKanbanSyncOptions {
	/** Kanban workspace/project path. Defaults to the Agent Hub cwd. */
	projectPath: string;
	/** Command or absolute executable path. Defaults to OMP_KANBAN_CLI or pk-kanban. */
	command?: string;
	/** Process cwd for the Kanban CLI. Defaults to projectPath. */
	cwd?: string;
	runner?: KanbanCliRunner;
}

export interface AgentHubKanbanSyncResult {
	agentId: string;
	idempotencyKey: string;
	taskId: string | undefined;
	created: boolean;
	updated: boolean;
	ok: boolean;
	error: string | undefined;
}

interface OmpBackgroundAgentSnapshot {
	id: string;
	displayName: string;
	kind: string;
	status: string;
	activity?: string;
	cwd?: string;
	sessionFile?: string;
}

interface KanbanOmpBackgroundSyncPayload {
	ok?: boolean;
	results?: Array<{
		agentId?: string;
		idempotencyKey?: string;
		taskId?: string;
		created?: boolean;
		updated?: boolean;
	}>;
}

class BunKanbanCliRunner implements KanbanCliRunner {
	async run(command: string, args: string[], options: KanbanCliRunOptions): Promise<KanbanCliRunResult> {
		const proc = Bun.spawn([command, ...args], {
			cwd: options.cwd,
			stdin: "ignore",
			stdout: "pipe",
			stderr: "pipe",
			windowsHide: true,
		});
		const stdout = await new Response(proc.stdout).text();
		const stderr = await new Response(proc.stderr).text();
		const exitCode = await proc.exited;
		return { exitCode, stdout, stderr };
	}
}

export class AgentHubKanbanSync {
	#projectPath: string;
	#command: string;
	#cwd: string;
	#runner: KanbanCliRunner;

	constructor(options: AgentHubKanbanSyncOptions) {
		this.#projectPath = options.projectPath;
		this.#command = options.command?.trim() || DEFAULT_KANBAN_COMMAND;
		this.#cwd = options.cwd ?? options.projectPath;
		this.#runner = options.runner ?? new BunKanbanCliRunner();
	}

	async syncAgent(agent: AgentRef): Promise<AgentHubKanbanSyncResult> {
		const results = await this.syncAgents([agent]);
		const result = results[0];
		if (result) return result;
		return this.#failedResult(agent, "Kanban sync returned no result for selected agent.");
	}

	async syncAgents(agents: AgentRef[]): Promise<AgentHubKanbanSyncResult[]> {
		if (agents.length === 0) return [];
		try {
			const payload = await this.#runJson<KanbanOmpBackgroundSyncPayload>([
				"task",
				"sync-omp-background",
				"--project-path",
				this.#projectPath,
				"--agents-json",
				JSON.stringify(agents.map(agent => toOmpBackgroundAgentSnapshot(agent))),
			]);
			return agents.map(agent => this.#resultForAgent(agent, payload));
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			return agents.map(agent => this.#failedResult(agent, message));
		}
	}

	idempotencyKey(agentId: string): string {
		return `${TASK_KEY_PREFIX}:${this.#projectPath}:${agentId}`;
	}

	async #runJson<T>(args: string[]): Promise<T> {
		const result = await this.#runner.run(this.#command, args, { cwd: this.#cwd });
		if (result.exitCode !== 0) {
			const detail = result.stderr.trim() || result.stdout.trim() || `exit ${result.exitCode}`;
			throw new Error(`Kanban sync failed: ${detail}`);
		}
		try {
			return JSON.parse(result.stdout) as T;
		} catch (error) {
			throw new Error(
				`Kanban sync returned invalid JSON: ${error instanceof Error ? error.message : String(error)}`,
			);
		}
	}

	#resultForAgent(agent: AgentRef, payload: KanbanOmpBackgroundSyncPayload): AgentHubKanbanSyncResult {
		const result = payload.results?.find(candidate => candidate.agentId === agent.id);
		if (!payload.ok || !result) {
			return this.#failedResult(agent, "Kanban sync returned no result for agent.");
		}
		return {
			agentId: agent.id,
			idempotencyKey: result.idempotencyKey ?? this.idempotencyKey(agent.id),
			taskId: result.taskId,
			created: result.created === true,
			updated: result.updated === true,
			ok: true,
			error: undefined,
		};
	}

	#failedResult(agent: AgentRef, error: string): AgentHubKanbanSyncResult {
		return {
			agentId: agent.id,
			idempotencyKey: this.idempotencyKey(agent.id),
			taskId: undefined,
			created: false,
			updated: false,
			ok: false,
			error,
		};
	}
}

export function renderKanbanPrompt(agent: AgentRef): string {
	return renderOmpBackgroundAgentSnapshotPrompt(toOmpBackgroundAgentSnapshot(agent));
}

function toOmpBackgroundAgentSnapshot(agent: AgentRef): OmpBackgroundAgentSnapshot {
	return {
		id: agent.id,
		displayName: agent.displayName,
		kind: agent.kind,
		status: agent.status,
		activity: agent.activity,
		cwd: agent.cwd,
		sessionFile: agent.sessionFile ?? undefined,
	};
}

function renderOmpBackgroundAgentSnapshotPrompt(agent: OmpBackgroundAgentSnapshot): string {
	const lines = [
		`[OMP background agent] ${agent.displayName} (${agent.id})`,
		"",
		`Status: ${agent.status}`,
		`Kind: ${agent.kind}`,
	];
	if (agent.activity) lines.push(`Activity: ${agent.activity}`);
	if (agent.cwd) lines.push(`CWD: ${agent.cwd}`);
	if (agent.sessionFile) lines.push(`Session file: ${agent.sessionFile}`);
	return lines.join("\n");
}
