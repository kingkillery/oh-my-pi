import { describe, expect, it } from "bun:test";
import {
	AgentHubKanbanSync,
	type KanbanCliRunner,
	renderKanbanPrompt,
} from "../src/modes/components/agent-hub-kanban-sync";
import type { AgentRef } from "../src/registry/agent-registry";

class RecordingKanbanRunner implements KanbanCliRunner {
	calls: Array<{ command: string; args: string[]; cwd: string }> = [];
	listPayload: unknown = { ok: true, tasks: [] };

	async run(
		command: string,
		args: string[],
		options: { cwd: string },
	): Promise<{ exitCode: number; stdout: string; stderr: string }> {
		this.calls.push({ command, args, cwd: options.cwd });
		if (args[0] === "task" && args[1] === "list") {
			return { exitCode: 0, stdout: JSON.stringify(this.listPayload), stderr: "" };
		}
		if (args[0] === "task" && args[1] === "create") {
			return {
				exitCode: 0,
				stdout: JSON.stringify({ ok: true, idempotent: false, task: { id: "task-new" } }),
				stderr: "",
			};
		}
		if (args[0] === "task" && args[1] === "update") {
			return { exitCode: 0, stdout: JSON.stringify({ ok: true, task: { id: "task-existing" } }), stderr: "" };
		}
		return { exitCode: 1, stdout: "", stderr: "unexpected command" };
	}
}

function createAgent(overrides: Partial<AgentRef> = {}): AgentRef {
	return {
		id: "agent-1",
		displayName: "Implementation Agent",
		kind: "sub",
		status: "running",
		session: null,
		sessionFile: "C:/tmp/agent.jsonl",
		createdAt: 1,
		lastActivity: 2,
		activity: "editing files",
		cwd: "C:/work/repo",
		...overrides,
	};
}

describe("AgentHubKanbanSync", () => {
	it("creates a Kanban task for an unsynced background agent", async () => {
		const runner = new RecordingKanbanRunner();
		const sync = new AgentHubKanbanSync({ projectPath: "C:/work/repo", command: "pk-kanban", runner });

		const result = await sync.syncAgent(createAgent());

		expect(result).toMatchObject({ agentId: "agent-1", taskId: "task-new", created: true, updated: false, ok: true });
		expect(runner.calls[0].args).toEqual(["task", "list", "--project-path", "C:/work/repo"]);
		expect(runner.calls[1].args).toContain("--idempotency-key");
		expect(runner.calls[1].args).toContain("omp-agent-hub:C:/work/repo:agent-1");
		expect(runner.calls[1].args).toContain("--workspace-path");
		expect(runner.calls[1].args).toContain("C:/work/repo");
	});

	it("updates an existing Kanban task matched by idempotency key", async () => {
		const runner = new RecordingKanbanRunner();
		runner.listPayload = {
			ok: true,
			tasks: [{ id: "task-existing", prompt: "old", idempotencyKey: "omp-agent-hub:C:/work/repo:agent-1" }],
		};
		const sync = new AgentHubKanbanSync({ projectPath: "C:/work/repo", command: "pk-kanban", runner });

		const result = await sync.syncAgent(createAgent());

		expect(result).toMatchObject({
			agentId: "agent-1",
			taskId: "task-existing",
			created: false,
			updated: true,
			ok: true,
		});
		expect(runner.calls[1].args.slice(0, 6)).toEqual([
			"task",
			"update",
			"--project-path",
			"C:/work/repo",
			"--task-id",
			"task-existing",
		]);
	});

	it("renders enough agent context for a durable Kanban card", () => {
		const prompt = renderKanbanPrompt(createAgent());

		expect(prompt).toContain("[OMP background agent] Implementation Agent (agent-1)");
		expect(prompt).toContain("Status: running");
		expect(prompt).toContain("Activity: editing files");
		expect(prompt).toContain("Session file: C:/tmp/agent.jsonl");
	});
});
