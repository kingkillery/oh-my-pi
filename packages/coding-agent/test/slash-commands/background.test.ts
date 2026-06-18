import { describe, expect, it, vi } from "bun:test";
import type { InteractiveModeContext } from "@oh-my-pi/pi-coding-agent/modes/types";
import { executeBuiltinSlashCommand } from "@oh-my-pi/pi-coding-agent/slash-commands/builtin-registry";

function createRuntimeHarness() {
	const setText = vi.fn();
	const backgroundCurrentSession = vi.fn(async (_name: string) => true);
	const showBackgroundInstanceSelector = vi.fn(async () => undefined);
	const showStatus = vi.fn();
	const showWarning = vi.fn();
	const sessionManager = { getSessionName: vi.fn((): string | undefined => undefined) };
	const ctx = {
		editor: { setText },
		session: { backgroundCurrentSession, sessionManager },
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
		runtime: { ctx } as Parameters<typeof executeBuiltinSlashCommand>[1],
	};
}

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

	it("opens the background switcher from /backgrounds and /agents without promoting a session", async () => {
		const harness = createRuntimeHarness();

		expect(await executeBuiltinSlashCommand("/backgrounds", harness.runtime)).toBe(true);
		expect(await executeBuiltinSlashCommand("/agents", harness.runtime)).toBe(true);

		expect(harness.backgroundCurrentSession).not.toHaveBeenCalled();
		expect(harness.showBackgroundInstanceSelector).toHaveBeenCalledTimes(2);
		expect(harness.setText).toHaveBeenCalledWith("");
	});
});
