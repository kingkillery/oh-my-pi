import { describe, expect, it } from "bun:test";
import { SessionManager } from "@oh-my-pi/pi-coding-agent/session/session-manager";
import { MemorySessionStorage } from "@oh-my-pi/pi-coding-agent/session/session-storage";

describe("background instance sessions", () => {
	it("persists an active background instance and archives it", async () => {
		const storage = new MemorySessionStorage();
		const manager = SessionManager.create("/work", "/sessions/background", storage);

		const ok = await manager.backgroundCurrentSession({
			name: "api-worker",
			model: "anthropic/claude-sonnet-4-6",
			role: "default",
		});

		expect(ok).toBe(true);
		expect(manager.getSessionName()).toBe("api-worker");
		expect(manager.getBackgroundInstance()).toEqual({
			name: "api-worker",
			status: "active",
			model: "anthropic/claude-sonnet-4-6",
			role: "default",
		});

		const entries = manager.getEntries();
		expect(entries.some(entry => entry.type === "background_instance" && entry.name === "api-worker")).toBe(true);
		expect(storage.existsSync(manager.getSessionFile() ?? "")).toBe(true);
		const sessionFile = manager.getSessionFile();
		if (!sessionFile) throw new Error("Expected session file");
		let header = JSON.parse((await storage.readText(sessionFile)).split("\n")[0]!) as Record<string, unknown>;
		expect(header.backgroundInstance).toEqual({
			name: "api-worker",
			status: "active",
			model: "anthropic/claude-sonnet-4-6",
			role: "default",
		});

		const archivedEntryId = manager.archiveBackgroundInstance();
		expect(typeof archivedEntryId).toBe("string");
		expect(manager.getBackgroundInstance()).toBeUndefined();
		header = JSON.parse((await storage.readText(sessionFile)).split("\n")[0]!) as Record<string, unknown>;
		expect(header.backgroundInstance).toEqual({
			name: "api-worker",
			status: "archived",
			model: "anthropic/claude-sonnet-4-6",
			role: "default",
		});
	});
});
