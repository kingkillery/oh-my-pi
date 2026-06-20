import { afterEach, describe, expect, it, vi } from "bun:test";
import { getBundledModel } from "@pk-nerdsaver-ai/pi-catalog/models";
import { runCommitAgentSession } from "@pk-nerdsaver-ai/pi-coding-agent/commit/agentic/agent";
import * as toolsModule from "@pk-nerdsaver-ai/pi-coding-agent/commit/agentic/tools";
import { Settings } from "@pk-nerdsaver-ai/pi-coding-agent/config/settings";
import type { CreateAgentSessionResult } from "@pk-nerdsaver-ai/pi-coding-agent/sdk";
import * as sdkModule from "@pk-nerdsaver-ai/pi-coding-agent/sdk";
import type { PromptOptions } from "@pk-nerdsaver-ai/pi-coding-agent/session/agent-session";

describe("commit agent prompt attribution", () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("marks generated commit prompts and reminders as agent-attributed", async () => {
		const prompts: Array<{ text: string; options?: PromptOptions }> = [];
		const session = {
			prompt: async (text: string, options?: PromptOptions) => {
				prompts.push({ text, options });
			},
			subscribe: () => () => {},
			dispose: async () => {},
		};

		vi.spyOn(sdkModule, "createAgentSession").mockResolvedValue({ session } as unknown as CreateAgentSessionResult);
		vi.spyOn(toolsModule, "createCommitTools").mockReturnValue([]);

		const model = getBundledModel("anthropic", "claude-sonnet-4-5");
		if (!model) {
			throw new Error("Expected claude-sonnet-4-5 model to exist");
		}

		await runCommitAgentSession({
			cwd: "/tmp",
			model,
			settings: Settings.isolated(),
			modelRegistry: {} as never,
			authStorage: {} as never,
			changelogTargets: [],
			requireChangelog: false,
		});

		expect(prompts).toHaveLength(4);
		for (const prompt of prompts) {
			expect(prompt.options?.attribution).toBe("agent");
			expect(prompt.options?.expandPromptTemplates).toBe(false);
		}
	});
});
