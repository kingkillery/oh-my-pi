import { afterEach, describe, expect, test } from "bun:test";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { buildRepoEvidence, formatRepoEvidence } from "@pk-nerdsaver-ai/pi-coding-agent/task/repo-evidence";

let tempRoots: string[] = [];

async function makeTempRepo(): Promise<string> {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "omp-repo-evidence-"));
	tempRoots.push(root);
	await fs.mkdir(path.join(root, "src"), { recursive: true });
	await Bun.write(
		path.join(root, "src", "agent.ts"),
		[
			"export function parseModelList(value: string): string[] {",
			"\treturn value.split(',').map(entry => entry.trim());",
			"}",
		].join("\n"),
	);
	await Bun.write(path.join(root, "src", "noise.ts"), "export const unrelated = true;\n");
	return root;
}

afterEach(async () => {
	const roots = tempRoots;
	tempRoots = [];
	await Promise.all(roots.map(root => fs.rm(root, { recursive: true, force: true })));
});

describe("repo evidence prefetch", () => {
	test("ranks matching code lines with file evidence", async () => {
		const root = await makeTempRepo();

		const candidates = await buildRepoEvidence({
			cwd: root,
			query: "Where is parseModelList implemented?",
			maxCandidates: 3,
		});

		expect(candidates[0]).toMatchObject({ path: "src/agent.ts", lineStart: 1 });
		expect(formatRepoEvidence(candidates)).toContain("src/agent.ts:1-2");
		expect(formatRepoEvidence(candidates)).toContain("parseModelList");
	});
});
