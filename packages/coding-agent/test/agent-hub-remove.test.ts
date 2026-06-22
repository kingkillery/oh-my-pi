/**
 * Agent Hub destructive action contract: Ctrl+X is a per-agent confirmation,
 * not a global timer. Moving the selection after the warning must cancel it so
 * users cannot remove a different row than the one named in the warning.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from "bun:test";
import { IrcBus } from "@pk-nerdsaver-ai/pi-coding-agent/irc/bus";
import { AgentHubOverlayComponent } from "@pk-nerdsaver-ai/pi-coding-agent/modes/components/agent-hub";
import { SessionObserverRegistry } from "@pk-nerdsaver-ai/pi-coding-agent/modes/session-observer-registry";
import { initTheme } from "@pk-nerdsaver-ai/pi-coding-agent/modes/theme/theme";
import type { AgentLifecycleManager } from "@pk-nerdsaver-ai/pi-coding-agent/registry/agent-lifecycle";
import { AgentRegistry } from "@pk-nerdsaver-ai/pi-coding-agent/registry/agent-registry";

describe("Agent hub removal confirmation", () => {
	beforeAll(async () => {
		await initTheme();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("requires the second Ctrl+X to target the same selected agent", async () => {
		const now = vi.spyOn(Date, "now");
		const agents = new AgentRegistry();
		now.mockReturnValue(2000);
		agents.register({ id: "A", displayName: "Alpha", kind: "sub", session: null, status: "parked", cwd: "repo" });
		now.mockReturnValue(1000);
		agents.register({ id: "B", displayName: "Beta", kind: "sub", session: null, status: "parked", cwd: "repo" });
		const released = Promise.withResolvers<void>();
		const release = vi.fn(async () => {
			released.resolve();
		});
		const hub = new AgentHubOverlayComponent({
			observers: new SessionObserverRegistry(),
			hubKeys: [],
			onDone: () => {},
			requestRender: () => {},
			registry: agents,
			lifecycle: { release } as unknown as AgentLifecycleManager,
			irc: new IrcBus(agents),
			focusAgent: async () => {},
			cwd: "repo",
		});

		// Current session lane is row 0. Move selection down to subagent A (row 1).
		hub.handleInput("j");
		hub.handleInput("\x18");
		expect(Bun.stripANSI(hub.render(120).join("\n"))).toContain('Press x again (or Ctrl+X) to remove agent "A"');

		// Move selection down to subagent B (row 2).
		hub.handleInput("j");
		hub.handleInput("\x18");
		expect(release).not.toHaveBeenCalled();
		expect(Bun.stripANSI(hub.render(120).join("\n"))).toContain('Press x again (or Ctrl+X) to remove agent "B"');

		hub.handleInput("\x18");
		await released.promise;

		expect(release).toHaveBeenCalledWith("B");
		hub.dispose();
	});
});
