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

interface KanbanTaskRecord {
	id: string;
	prompt: string;
	idempotencyKey: string | null;
}

interface KanbanTaskListPayload {
	ok?: boolean;
	tasks?: KanbanTaskRecord[];
}

interface KanbanTaskMutationPayload {
	ok?: boolean;
	idempotent?: boolean;
	task?: {
		id?: string;
	};
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
		const tasks = await this.#listTasks();
		return await this.#syncAgentWithTasks(agent, tasks);
	}

	async syncAgents(agents: AgentRef[]): Promise<AgentHubKanbanSyncResult[]> {
		const tasks = await this.#listTasks();
		const results: AgentHubKanbanSyncResult[] = [];
		for (const agent of agents) {
			results.push(await this.#syncAgentWithTasks(agent, tasks));
		}
		return results;
	}

	idempotencyKey(agentId: string): string {
		return `${TASK_KEY_PREFIX}:${this.#projectPath}:${agentId}`;
	}

	async #syncAgentWithTasks(agent: AgentRef, tasks: KanbanTaskRecord[]): Promise<AgentHubKanbanSyncResult> {
		const idempotencyKey = this.idempotencyKey(agent.id);
		const existing = tasks.find(task => task.idempotencyKey === idempotencyKey);
		const prompt = renderKanbanPrompt(agent);
		if (existing) {
			const payload = await this.#runJson<KanbanTaskMutationPayload>([
				"task",
				"update",
				"--project-path",
				this.#projectPath,
				"--task-id",
				existing.id,
				"--prompt",
				prompt,
				"--idempotency-key",
				idempotencyKey,
			]);
			return {
				agentId: agent.id,
				idempotencyKey,
				taskId: payload.task?.id ?? existing.id,
				created: false,
				updated: true,
				ok: true,
				error: undefined,
			};
		}

		const createArgs = [
			"task",
			"create",
			"--project-path",
			this.#projectPath,
			"--prompt",
			prompt,
			"--idempotency-key",
			idempotencyKey,
		];
		if (agent.cwd) {
			createArgs.push("--workspace-kind", "dir", "--workspace-path", agent.cwd);
		}
		const payload = await this.#runJson<KanbanTaskMutationPayload>(createArgs);
		return {
			agentId: agent.id,
			idempotencyKey,
			taskId: payload.task?.id,
			created: payload.idempotent !== true,
			updated: payload.idempotent === true,
			ok: true,
			error: undefined,
		};
	}

	async #listTasks(): Promise<KanbanTaskRecord[]> {
		const payload = await this.#runJson<KanbanTaskListPayload>(["task", "list", "--project-path", this.#projectPath]);
		return payload.tasks ?? [];
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
}

export function renderKanbanPrompt(agent: AgentRef): string {
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
