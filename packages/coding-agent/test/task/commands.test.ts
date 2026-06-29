import { describe, expect, it } from "bun:test";
import {
	clearBundledCommandsCache,
	expandCommand,
	loadBundledCommands,
	type WorkflowCommand,
} from "@pk-nerdsaver-ai/pi-coding-agent/task/commands";

function makeCommand(instructions: string): WorkflowCommand {
	return { name: "test", description: "test", instructions, source: "project", filePath: "test.md" };
}

describe("expandCommand", () => {
	it("substitutes $@ with the input", () => {
		expect(expandCommand(makeCommand("Do: $@ and again $@"), "fix the bug")).toBe(
			"Do: fix the bug and again fix the bug",
		);
	});

	it("keeps $-patterns in user input literal", () => {
		expect(expandCommand(makeCommand("Run $@"), "echo $$ $& $' $` $@")).toBe("Run echo $$ $& $' $` $@");
	});
});

describe("loadBundledCommands", () => {
	it("includes the bundled rqgm command", () => {
		clearBundledCommandsCache();
		const rqgm = loadBundledCommands().find(c => c.name === "rqgm");
		expect(rqgm).toBeDefined();
		expect(rqgm?.description).toBeTruthy();
		expect(rqgm?.instructions).toContain("rqgm search");
		clearBundledCommandsCache();
	});
});
