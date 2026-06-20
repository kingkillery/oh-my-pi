import { afterEach, describe, expect, it, vi } from "bun:test";
import { SelectorController } from "@pk-nerdsaver-ai/pi-coding-agent/modes/controllers/selector-controller";
import type { InteractiveModeContext } from "@pk-nerdsaver-ai/pi-coding-agent/modes/types";
import * as backgroundAgentName from "@pk-nerdsaver-ai/pi-coding-agent/utils/background-agent-name";

function createContext() {
	const backgroundCurrentSession = vi.fn(async (_name: string) => true);
	const newSession = vi.fn(async () => true);
	const session = {
		newSession,
		backgroundCurrentSession,
		sessionId: "session-1",
		modelRegistry: {},
		agent: { metadataForProvider: vi.fn(() => undefined) },
	};
	const ctx = {
		clearTransientSessionUi: vi.fn(),
		session,
		sessionManager: {
			getSessionName: vi.fn(() => undefined),
			getCwd: vi.fn(() => "/tmp/project"),
		},
		settings: {},
		titleSystemPrompt: undefined,
		updateEditorBorderColor: vi.fn(),
		chatContainer: { clear: vi.fn() },
		renderInitialMessages: vi.fn(),
		reloadTodos: vi.fn(async () => undefined),
		showStatus: vi.fn(),
		onInputCallback: undefined,
		editor: { setText: vi.fn() },
	} as unknown as InteractiveModeContext;
	return { ctx, session, backgroundCurrentSession, newSession };
}

afterEach(() => {
	vi.restoreAllMocks();
});

describe("SelectorController background naming", () => {
	it("derives a generated name before promoting a new background session", async () => {
		const harness = createContext();
		vi.spyOn(backgroundAgentName, "generateBackgroundAgentName").mockResolvedValue("Debug npm replication lag");
		const controller = new SelectorController(harness.ctx);

		await controller.handleNewBackgroundSession("Investigate why npm packages are not visible immediately");

		expect(backgroundAgentName.generateBackgroundAgentName).toHaveBeenCalledWith(
			"Investigate why npm packages are not visible immediately",
			harness.session,
			harness.ctx.settings,
			undefined,
		);
		expect(harness.newSession).toHaveBeenCalledTimes(1);
		expect(harness.backgroundCurrentSession).toHaveBeenCalledWith("Debug npm replication lag");
		expect(harness.ctx.showStatus).toHaveBeenCalledWith("Started new background agent: Debug npm replication lag");
	});
});
