import { afterEach, describe, expect, it, vi } from "bun:test";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { Settings } from "@pk-nerdsaver-ai/pi-coding-agent/config/settings";
import { TaskTool } from "@pk-nerdsaver-ai/pi-coding-agent/task";
import * as discoveryModule from "@pk-nerdsaver-ai/pi-coding-agent/task/discovery";
import * as executorModule from "@pk-nerdsaver-ai/pi-coding-agent/task/executor";
import * as repoEvidenceModule from "@pk-nerdsaver-ai/pi-coding-agent/task/repo-evidence";
import type { AgentDefinition, SingleResult, TaskParams } from "@pk-nerdsaver-ai/pi-coding-agent/task/types";
import type { ToolSession } from "@pk-nerdsaver-ai/pi-coding-agent/tools";

const exploreAgent: AgentDefinition = {
	name: "explore",
	description: "Read-only scout",
	systemPrompt: "Scout the codebase.",
	tools: ["read", "search", "find"],
	model: ["pi/smol"],
	prefetch: "repo-evidence",
	source: "bundled",
};

let tempRoots: string[] = [];

function makeSession(cwd: string, settings: Record<string, unknown>): ToolSession {
	return {
		cwd,
		hasUI: false,
		settings: Settings.isolated({ "task.batch": false, "task.isolation.mode": "none", ...settings }),
		getSessionFile: () => null,
		getSessionSpawns: () => "*",
	} as unknown as ToolSession;
}

function makeResult(options: {
	readonly id?: string;
	readonly task?: string;
	readonly assignment?: string;
}): SingleResult {
	return {
		index: 0,
		id: options.id ?? "Explore",
		agent: "explore",
		agentSource: "bundled",
		task: options.task ?? "",
		assignment: options.assignment,
		exitCode: 0,
		output: "done",
		stderr: "",
		truncated: false,
		durationMs: 1,
		tokens: 0,
		requests: 1,
	};
}

async function makeRepo(): Promise<string> {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "omp-task-prefetch-"));
	tempRoots.push(root);
	await fs.mkdir(path.join(root, "src"), { recursive: true });
	await Bun.write(path.join(root, "src", "agent.ts"), "export function parseModelList() { return []; }\n");
	return root;
}

interface RunExploreResult {
	readonly task: string;
	readonly progressText: string;
}

async function runExploreDetails(cwd: string, settings: Record<string, unknown> = {}): Promise<RunExploreResult> {
	vi.spyOn(discoveryModule, "discoverAgents").mockResolvedValue({ agents: [exploreAgent], projectAgentsDir: null });
	const runSpy = vi.spyOn(executorModule, "runSubprocess").mockImplementation(async options => makeResult(options));
	const progressLines: string[] = [];
	const tool = await TaskTool.create(makeSession(cwd, settings));
	await tool.execute(
		"tool-call",
		{
			agent: "explore",
			id: "Explore",
			assignment: "Where is parseModelList implemented?",
		} satisfies TaskParams,
		undefined,
		update => {
			for (const progress of update.details?.progress ?? []) {
				progressLines.push(...progress.recentOutput);
			}
		},
	);
	const options = runSpy.mock.calls[0]?.[0];
	return { task: options?.task ?? "", progressText: progressLines.join("\n") };
}

async function runExplore(cwd: string, settings: Record<string, unknown> = {}): Promise<string> {
	return (await runExploreDetails(cwd, settings)).task;
}

afterEach(async () => {
	vi.restoreAllMocks();
	const roots = tempRoots;
	tempRoots = [];
	await Promise.all(roots.map(root => fs.rm(root, { recursive: true, force: true })));
});

describe("task repo evidence prefetch", () => {
	it("injects prefetched evidence for opted-in agents when enabled", async () => {
		const task = await runExplore(await makeRepo());

		expect(task).toContain("<prefetched-evidence>");
		expect(task).toContain("src/agent.ts");
		expect(task).toContain("parseModelList");
	});

	it("falls back to the normal subagent prompt when disabled", async () => {
		const task = await runExplore(await makeRepo(), { "task.prefetch.enabled": false });

		expect(task).not.toContain("<prefetched-evidence>");
		expect(task).toContain("Where is parseModelList implemented?");
	});

	it("falls back to the normal subagent prompt when gather finds no evidence", async () => {
		const emptyRoot = await fs.mkdtemp(path.join(os.tmpdir(), "omp-task-prefetch-empty-"));
		tempRoots.push(emptyRoot);

		const task = await runExplore(emptyRoot);

		expect(task).not.toContain("<prefetched-evidence>");
		expect(task).toContain("Where is parseModelList implemented?");
	});

	it("reminds users how to disable prefetch when gather fails", async () => {
		vi.spyOn(repoEvidenceModule, "buildRepoEvidence").mockRejectedValue(new Error("boom"));

		const result = await runExploreDetails(await makeRepo());

		expect(result.task).not.toContain("<prefetched-evidence>");
		expect(result.task).toContain("Where is parseModelList implemented?");
		expect(result.progressText).toContain("Disable with `task.prefetch.enabled=false`");
	});
});
