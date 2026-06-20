import { describe, expect, it } from "bun:test";
import * as path from "node:path";
import {
	clampRemoteSessionLimit,
	DEFAULT_REMOTE_SESSION_LIMIT,
	findLoadableRemoteSession,
	MAX_REMOTE_SESSION_LIMIT,
	selectRemoteSessions,
	toRemoteSessionSnapshot,
} from "../src/collab/remote-control";
import type { SessionInfo } from "../src/session/session-listing";

function session(overrides: Partial<SessionInfo>): SessionInfo {
	return {
		path: path.join("sessions", "one.jsonl"),
		id: "one",
		cwd: path.join("repo", "one"),
		title: "One",
		created: new Date("2026-06-20T00:00:00.000Z"),
		modified: new Date("2026-06-20T01:00:00.000Z"),
		messageCount: 2,
		size: 128,
		firstMessage: "first prompt",
		allMessagesText: "first prompt response",
		status: "complete",
		...overrides,
	};
}

describe("remote-control session helpers", () => {
	it("serializes session dates and lifecycle status for wire clients", () => {
		const snapshot = toRemoteSessionSnapshot(session({ status: "interrupted" }));

		expect(snapshot).toMatchObject({
			id: "one",
			created: "2026-06-20T00:00:00.000Z",
			modified: "2026-06-20T01:00:00.000Z",
			status: "interrupted",
			firstMessage: "first prompt",
		});
	});

	it("caps remote session lists to a bounded recent window", () => {
		const sessions = Array.from({ length: MAX_REMOTE_SESSION_LIMIT + 1 }, (_, index) =>
			session({ path: path.join("sessions", `${index}.jsonl`), id: String(index) }),
		);

		expect(clampRemoteSessionLimit(undefined)).toBe(DEFAULT_REMOTE_SESSION_LIMIT);
		expect(clampRemoteSessionLimit(-4)).toBe(1);
		expect(clampRemoteSessionLimit(MAX_REMOTE_SESSION_LIMIT + 10)).toBe(MAX_REMOTE_SESSION_LIMIT);
		expect(selectRemoteSessions(sessions, 3).map(item => item.id)).toEqual(["0", "1", "2"]);
	});

	it("only resolves load requests to known session paths", () => {
		const known = session({ path: path.join("sessions", "known.jsonl") });
		const sessions = [known];

		expect(findLoadableRemoteSession(sessions, path.join("sessions", "known.jsonl"))).toBe(known);
		expect(findLoadableRemoteSession(sessions, path.join("sessions", "missing.jsonl"))).toBeUndefined();
	});
});
