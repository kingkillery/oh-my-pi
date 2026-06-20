import * as path from "node:path";
import type { RemoteSessionSnapshot } from "@pk-nerdsaver-ai/pi-wire";
import type { SessionInfo, SessionStatus } from "../session/session-listing";

export const DEFAULT_REMOTE_SESSION_LIMIT = 50;
export const MAX_REMOTE_SESSION_LIMIT = 200;

const REMOTE_SESSION_STATUSES: Record<SessionStatus, true> = {
	complete: true,
	interrupted: true,
	aborted: true,
	error: true,
	pending: true,
	unknown: true,
};

export function clampRemoteSessionLimit(limit: number | undefined): number {
	if (limit === undefined || !Number.isFinite(limit)) return DEFAULT_REMOTE_SESSION_LIMIT;
	return Math.min(Math.max(Math.trunc(limit), 1), MAX_REMOTE_SESSION_LIMIT);
}

export function toRemoteSessionSnapshot(session: SessionInfo): RemoteSessionSnapshot {
	return {
		path: session.path,
		id: session.id,
		cwd: session.cwd,
		title: session.title,
		created: session.created.toISOString(),
		modified: session.modified.toISOString(),
		messageCount: session.messageCount,
		size: session.size,
		firstMessage: session.firstMessage,
		status: session.status && REMOTE_SESSION_STATUSES[session.status] ? session.status : undefined,
	};
}

export function selectRemoteSessions(sessions: SessionInfo[], limit: number | undefined): RemoteSessionSnapshot[] {
	return sessions.slice(0, clampRemoteSessionLimit(limit)).map(toRemoteSessionSnapshot);
}

export function findLoadableRemoteSession(sessions: SessionInfo[], requestedPath: string): SessionInfo | undefined {
	const resolvedRequestedPath = path.resolve(requestedPath);
	return sessions.find(session => path.resolve(session.path) === resolvedRequestedPath);
}
