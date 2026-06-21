import { describe, expect, it } from "bun:test";
import { parseLoopLimitArgs } from "../loop-limit";

describe("parseLoopLimitArgs", () => {
	it("parses explicit spiral mode with an iteration limit and prompt", () => {
		expect(parseLoopLimitArgs("--spiral 3 improve the task")).toEqual({
			mode: "spiral",
			limit: { kind: "iterations", iterations: 3 },
			prompt: "improve the task",
		});
	});

	it("parses wall-climb as a spiral alias", () => {
		expect(parseLoopLimitArgs("--wall-climb 10m finish the plan")).toEqual({
			mode: "spiral",
			limit: { kind: "duration", durationMs: 600_000 },
			prompt: "finish the plan",
		});
	});

	it("parses --mode before the loop limit", () => {
		expect(parseLoopLimitArgs("--mode compact 2m summarize progress")).toEqual({
			mode: "compact",
			limit: { kind: "duration", durationMs: 120_000 },
			prompt: "summarize progress",
		});
	});

	it("parses --mode=value before the loop limit", () => {
		expect(parseLoopLimitArgs("--mode=reset 2 rebuild from scratch")).toEqual({
			mode: "reset",
			limit: { kind: "iterations", iterations: 2 },
			prompt: "rebuild from scratch",
		});
	});

	it("keeps prose prompts beginning with mode words unchanged", () => {
		expect(parseLoopLimitArgs("spiral through the codebase")).toEqual({ prompt: "spiral through the codebase" });
		expect(parseLoopLimitArgs("compact this explanation")).toEqual({ prompt: "compact this explanation" });
	});

	it("rejects unknown explicit mode values", () => {
		expect(parseLoopLimitArgs("--mode turbo 3 improve")).toBe("Loop mode must be prompt, compact, reset, or spiral.");
		expect(parseLoopLimitArgs("--mode=turbo 3 improve")).toBe("Loop mode must be prompt, compact, reset, or spiral.");
	});
});
