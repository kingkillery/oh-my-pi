import { afterAll, beforeAll, describe, expect, it, vi } from "bun:test";
import { SessionSelectorComponent } from "@pk-nerdsaver-ai/pi-coding-agent/modes/components/session-selector";
import { initTheme } from "@pk-nerdsaver-ai/pi-coding-agent/modes/theme/theme";
import type { SessionInfo } from "@pk-nerdsaver-ai/pi-coding-agent/session/session-listing";

beforeAll(async () => {
	await initTheme();
});

afterAll(async () => {
	await initTheme();
});

function createSession(id: string, background = false): SessionInfo {
	return {
		path: `/work/${id}.jsonl`,
		id,
		cwd: "/work",
		title: `Session ${id}`,
		created: new Date("2024-01-01T00:00:00Z"),
		modified: new Date("2024-01-02T00:00:00Z"),
		messageCount: 1,
		size: 2048,
		firstMessage: `first message ${id}`,
		allMessagesText: `first message ${id}`,
		backgroundInstance: background
			? {
					name: "api-worker",
					status: "active",
					model: "anthropic/claude-sonnet-4-6",
					role: "default",
				}
			: undefined,
	};
}

function renderPlain(sessions: SessionInfo[]): string {
	const selector = new SessionSelectorComponent(
		sessions,
		() => {},
		() => {},
		() => {},
		{ getTerminalRows: () => 100, mode: "backgroundInstances" },
	);
	return selector
		.render(140)
		.join("\n")
		.replace(/\x1b\[[0-9;]*m/g, "");
}

describe("SessionSelectorComponent background instances", () => {
	it("renders only active background sessions with model metadata", () => {
		const rendered = renderPlain([createSession("normal"), createSession("background", true)]);

		expect(rendered).toContain("Background Agents");
		expect(rendered).toContain("api-worker");
		expect(rendered).toContain("model anthropic/claude-sonnet-4-6");
		expect(rendered).not.toContain("Session normal");
	});

	it("shows the background-specific empty state", () => {
		const rendered = renderPlain([createSession("normal")]);

		expect(rendered).toContain("No background agents yet. Type a query and press Enter to launch one.");
	});

	it("wires delete for background instances", () => {
		const onDelete = vi.fn(async () => true);
		const selector = new SessionSelectorComponent(
			[createSession("background", true)],
			() => {},
			() => {},
			() => {},
			{ getTerminalRows: () => 100, mode: "backgroundInstances", onDelete },
		);

		selector.handleInput("\x1b[3~");

		expect(selector.render(140).join("\n")).toContain("Delete session?");
	});
});
