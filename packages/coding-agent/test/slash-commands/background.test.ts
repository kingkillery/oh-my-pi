import { afterEach, describe, expect, it, vi } from "bun:test";
import type { InteractiveModeContext } from "@pk-nerdsaver-ai/pi-coding-agent/modes/types";
import { executeBuiltinSlashCommand } from "@pk-nerdsaver-ai/pi-coding-agent/slash-commands/builtin-registry";
import * as backgroundAgentName from "@pk-nerdsaver-ai/pi-coding-agent/utils/background-agent-name";

function createRuntimeHarness() {
	const setText = vi.fn();
	const backgroundCurrentSession = vi.fn(async (_name: string) => true);
	const showBackgroundInstanceSelector = vi.fn(async () => undefined);
	const showStatus = vi.fn();
	const showWarning = vi.fn();
	const sessionManager = {
		getSessionName: vi.fn((): string | undefined => undefined),
		getEntries: vi.fn(() => []),
	};
	const session = {
		backgroundCurrentSession,
		sessionManager,
		sessionId: "session-1",
		modelRegistry: {},
		agent: { metadataForProvider: vi.fn(() => undefined) },
	};
	const ctx = {
		editor: { setText },
		session,
		settings: {},
		titleSystemPrompt: undefined,
		showBackgroundInstanceSelector,
		showStatus,
		showWarning,
	} as unknown as InteractiveModeContext;

	return {
		setText,
		backgroundCurrentSession,
		showBackgroundInstanceSelector,
		showStatus,
		showWarning,
		sessionManager,
		session,
		runtime: { ctx } as Parameters<typeof executeBuiltinSlashCommand>[1],
	};
}

afterEach(() => {
	vi.restoreAllMocks();
});

describe("/background slash commands", () => {
	it("backgrounds the current session and opens the switcher", async () => {
		const harness = createRuntimeHarness();

		expect(await executeBuiltinSlashCommand("/background api-worker", harness.runtime)).toBe(true);

		expect(harness.backgroundCurrentSession).toHaveBeenCalledWith("api-worker");
		expect(harness.setText).toHaveBeenCalledWith("");
		expect(harness.showStatus).toHaveBeenCalledWith("Backgrounded session as api-worker");
		expect(harness.showBackgroundInstanceSelector).toHaveBeenCalledTimes(1);
	});

	it("reports sanitized-name failure without opening the switcher", async () => {
		const harness = createRuntimeHarness();
		harness.backgroundCurrentSession.mockResolvedValueOnce(false);

		expect(await executeBuiltinSlashCommand("/background api-worker", harness.runtime)).toBe(true);

		expect(harness.showWarning).toHaveBeenCalledWith(
			"Could not background session: name is empty after sanitization.",
		);
		expect(harness.showBackgroundInstanceSelector).not.toHaveBeenCalled();
		expect(harness.setText).toHaveBeenCalledWith("");
	});

	it("derives a better name from the latest user prompt when the session is unnamed", async () => {
		const harness = createRuntimeHarness();
		harness.sessionManager.getEntries.mockReturnValue([
			{
				type: "message",
				message: { role: "user", content: "Investigate why npm publish succeeds but npm view returns 404" },
			},
		]);
		vi.spyOn(backgroundAgentName, "generateBackgroundAgentName").mockResolvedValue(
			"Investigate npm publish visibility",
		);

		expect(await executeBuiltinSlashCommand("/background", harness.runtime)).toBe(true);

		expect(backgroundAgentName.generateBackgroundAgentName).toHaveBeenCalledWith(
			"Investigate why npm publish succeeds but npm view returns 404",
			harness.session,
			harness.runtime.ctx.settings,
			undefined,
		);
		expect(harness.backgroundCurrentSession).toHaveBeenCalledWith("Investigate npm publish visibility");
		expect(harness.showStatus).toHaveBeenCalledWith("Backgrounded session as Investigate npm publish visibility");
	});

	it("opens the background switcher from /backgrounds and /agents without promoting a session", async () => {
		const harness = createRuntimeHarness();

		expect(await executeBuiltinSlashCommand("/backgrounds", harness.runtime)).toBe(true);
		expect(await executeBuiltinSlashCommand("/agents", harness.runtime)).toBe(true);

		expect(harness.backgroundCurrentSession).not.toHaveBeenCalled();
		expect(harness.showBackgroundInstanceSelector).toHaveBeenCalledTimes(2);
		expect(harness.setText).toHaveBeenCalledWith("");
	});
});
