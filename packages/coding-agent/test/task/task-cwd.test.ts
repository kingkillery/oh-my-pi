import { afterEach, describe, expect, it, vi } from "bun:test";
import * as path from "node:path";
import { Settings } from "@pk-nerdsaver-ai/pi-coding-agent/config/settings";
import { TaskTool } from "@pk-nerdsaver-ai/pi-coding-agent/task";
import * as discoveryModule from "@pk-nerdsaver-ai/pi-coding-agent/task/discovery";
import * as executorModule from "@pk-nerdsaver-ai/pi-coding-agent/task/executor";
import type { AgentDefinition, SingleResult, TaskParams } from "@pk-nerdsaver-ai/pi-coding-agent/task/types";
import { taskItemSchema, taskSchema } from "@pk-nerdsaver-ai/pi-coding-agent/task/types";
import type { ToolSession } from "@pk-nerdsaver-ai/pi-coding-agent/tools";

// Contract: `cwd` lets each task spawn run in its own working directory.
// Flat calls carry it top-level; batch calls carry it per item. Missing `cwd`
// inherits the parent session cwd, and relative paths resolve against it.

const taskAgent: AgentDefinition = {
	name: "task",
	description: "General-purpose task agent",
	systemPrompt: "You are a task agent.",
	source: "bundled",
};

function createSession(options: { settings?: Record<string, unknown> } = {}): ToolSession {
	return {
		cwd: path.resolve("/tmp/project-root"),
		hasUI: false,
		settings: Settings.isolated(options.settings ?? {}),
		getSessionFile: () => null,
		getSessionSpawns: () => "*",
	} as unknown as ToolSession;
}

function makeResult(id: string, overrides: Partial<SingleResult> = {}): SingleResult {
	return {
		index: 0,
		id,
		agent: "task",
		agentSource: "bundled",
		task: "task prompt",
		assignment: "Do the thing.",
		exitCode: 0,
		output: "All done.",
		stderr: "",
		truncated: false,
		durationMs: 5,
		tokens: 0,
		requests: 1,
		...overrides,
	};
}

describe("task cwd parameter", () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	describe("schema validation", () => {
		it("accepts cwd on flat task schema", () => {
			const parsed = taskSchema({
				agent: "explore",
				assignment: "Map the module.",
				cwd: "/custom/path",
			});
			expect(parsed).not.toBeInstanceOf(Error);
			if (!(parsed instanceof Error)) {
				expect(parsed.cwd).toBe("/custom/path");
			}
		});

		it("accepts cwd on batch task items", () => {
			const itemParsed = taskItemSchema({
				id: "A",
				assignment: "Work in subdir",
				cwd: "./packages/web",
			});
			expect(itemParsed).not.toBeInstanceOf(Error);
			if (!(itemParsed instanceof Error)) {
				expect(itemParsed.cwd).toBe("./packages/web");
			}
		});

		it("cwd is optional on flat schema", () => {
			const parsed = taskSchema({
				agent: "explore",
				assignment: "Map the module.",
			});
			expect(parsed).not.toBeInstanceOf(Error);
			if (!(parsed instanceof Error)) {
				expect(parsed.cwd).toBeUndefined();
			}
		});

		it("cwd is optional on batch items", () => {
			const itemParsed = taskItemSchema({
				id: "A",
				assignment: "Work here",
			});
			expect(itemParsed).not.toBeInstanceOf(Error);
			if (!(itemParsed instanceof Error)) {
				expect(itemParsed.cwd).toBeUndefined();
			}
		});
	});

	describe("executor cwd routing", () => {
		async function createTool(settings?: Record<string, unknown>): Promise<TaskTool> {
			vi.spyOn(discoveryModule, "discoverAgents").mockResolvedValue({
				agents: [taskAgent],
				projectAgentsDir: null,
			});
			return TaskTool.create(createSession({ settings }));
		}

		it("passes explicit flat cwd to runSubprocess", async () => {
			const runSpy = vi.spyOn(executorModule, "runSubprocess").mockImplementation(async options => {
				return makeResult(options.id ?? "?");
			});
			const tool = await createTool({ "task.batch": false });

			await tool.execute("tc-cwd", {
				agent: "task",
				id: "TestAgent",
				assignment: "Test work",
				cwd: path.resolve("/custom/work/dir"),
			} as TaskParams);

			expect(runSpy).toHaveBeenCalledTimes(1);
			expect(runSpy.mock.calls[0][0].cwd).toBe(path.resolve("/custom/work/dir"));
		});

		it("resolves relative flat cwd against parent session cwd", async () => {
			const runSpy = vi.spyOn(executorModule, "runSubprocess").mockImplementation(async options => {
				return makeResult(options.id ?? "?");
			});
			const session = createSession({ settings: { "task.batch": false } });
			vi.spyOn(discoveryModule, "discoverAgents").mockResolvedValue({
				agents: [taskAgent],
				projectAgentsDir: null,
			});
			const tool = await TaskTool.create(session);

			await tool.execute("tc-relative-cwd", {
				agent: "task",
				id: "TestAgent",
				assignment: "Test work",
				cwd: "packages/web",
			} as TaskParams);

			expect(runSpy).toHaveBeenCalledTimes(1);
			expect(runSpy.mock.calls[0][0].cwd).toBe(path.resolve(session.cwd, "packages/web"));
		});

		it("uses parent session cwd when omitted", async () => {
			const runSpy = vi.spyOn(executorModule, "runSubprocess").mockImplementation(async options => {
				return makeResult(options.id ?? "?");
			});
			const session = createSession({ settings: { "task.batch": false } });
			vi.spyOn(discoveryModule, "discoverAgents").mockResolvedValue({
				agents: [taskAgent],
				projectAgentsDir: null,
			});
			const tool = await TaskTool.create(session);

			await tool.execute("tc-no-cwd", {
				agent: "task",
				id: "TestAgent",
				assignment: "Test work",
			} as TaskParams);

			expect(runSpy).toHaveBeenCalledTimes(1);
			expect(runSpy.mock.calls[0][0].cwd).toBe(session.cwd);
		});

		it("passes per-item batch cwd values to runSubprocess", async () => {
			const runSpy = vi.spyOn(executorModule, "runSubprocess").mockImplementation(async options => {
				return makeResult(options.id ?? "?");
			});
			const session = createSession({ settings: { "task.batch": true } });
			vi.spyOn(discoveryModule, "discoverAgents").mockResolvedValue({
				agents: [taskAgent],
				projectAgentsDir: null,
			});
			const tool = await TaskTool.create(session);

			await tool.execute("tc-cwd-batch", {
				agent: "task",
				context: "Shared context",
				tasks: [
					{ id: "Agent1", assignment: "Work A", cwd: path.resolve("/dir/a") },
					{ id: "Agent2", assignment: "Work B", cwd: path.resolve("/dir/b") },
				],
			} as TaskParams);

			expect(runSpy).toHaveBeenCalledTimes(2);
			const cwdValues = runSpy.mock.calls.map(call => call[0].cwd).sort();
			expect(cwdValues).toEqual([path.resolve("/dir/a"), path.resolve("/dir/b")].sort());
		});
	});
});
