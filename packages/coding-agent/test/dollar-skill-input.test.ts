import { describe, expect, it } from "bun:test";
import { parseDollarSkillInput } from "@pk-nerdsaver-ai/pi-coding-agent/modes/controllers/input-controller";

// Contract: `$<skill-name> [args]` is Codex-style explicit skill invocation, and it
// must NOT collide with the Python REPL sigils (`$ code` / `$$ code`, which require
// whitespace after `$`) or with `${…}` / `$HOME` shell-style prose.
describe("parseDollarSkillInput", () => {
	it("parses a bare skill name", () => {
		expect(parseDollarSkillInput("$ce-commit")).toEqual({ name: "ce-commit", args: "" });
	});

	it("parses a skill name with trailing args", () => {
		expect(parseDollarSkillInput("$plan migrate the service to postgres")).toEqual({
			name: "plan",
			args: "migrate the service to postgres",
		});
	});

	it("trims surrounding whitespace from args", () => {
		expect(parseDollarSkillInput("$review   spaced   args  ")).toEqual({ name: "review", args: "spaced   args" });
	});

	it("does not match the Python REPL sigils (whitespace after $)", () => {
		// `$ code` and `$$ code` are Python execution, not skill invocation.
		expect(parseDollarSkillInput("$ print(1)")).toBeNull();
		expect(parseDollarSkillInput("$$ print(1)")).toBeNull();
		expect(parseDollarSkillInput("$\tprint(1)")).toBeNull();
	});

	it("does not match curly-brace expansion or '$$' prose", () => {
		expect(parseDollarSkillInput(`$${"{HOME}"}/bin`)).toBeNull();
		expect(parseDollarSkillInput("$$")).toBeNull();
	});

	it("does not match a bare `$` or non-`$` text", () => {
		expect(parseDollarSkillInput("$")).toBeNull();
		expect(parseDollarSkillInput("hello world")).toBeNull();
		expect(parseDollarSkillInput("/skill:plan")).toBeNull();
	});

	it("parses `$HOME`-style tokens (registry lookup, not the parser, rejects non-skills)", () => {
		// The parser is permissive; the caller checks the name against the skill
		// registry, so an unregistered `$HOME` still falls through to plain text.
		expect(parseDollarSkillInput("$HOME")).toEqual({ name: "HOME", args: "" });
	});
});
