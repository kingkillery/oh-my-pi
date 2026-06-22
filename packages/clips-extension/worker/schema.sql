-- Clips account + clip-ownership schema (D1 / SQLite).
-- Users and sessions are first-class; clip binaries live in R2 under u/<user_id>/<clip_id>/,
-- while this DB is the source of truth for ownership, titles, and transcripts.

CREATE TABLE IF NOT EXISTS users (
	id TEXT PRIMARY KEY,
	username TEXT NOT NULL UNIQUE,
	email TEXT,
	email_verified INTEGER NOT NULL DEFAULT 0,
	password_hash TEXT NOT NULL,
	api_token TEXT NOT NULL UNIQUE,
	created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS verifications (
	token TEXT PRIMARY KEY,
	user_id TEXT NOT NULL,
	expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verifications_user ON verifications(user_id);
CREATE TABLE IF NOT EXISTS sessions (
	token TEXT PRIMARY KEY,
	user_id TEXT NOT NULL,
	expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS clips (
	id TEXT PRIMARY KEY,
	user_id TEXT NOT NULL,
	title TEXT NOT NULL,
	description TEXT NOT NULL DEFAULT '',
	video_type TEXT NOT NULL DEFAULT 'video/webm',
	transcript_json TEXT NOT NULL DEFAULT '{"text":"","segments":[]}',
	frames_json TEXT NOT NULL DEFAULT '[]',
	created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clips_user ON clips(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS rate_limits (
	k TEXT PRIMARY KEY,
	count INTEGER NOT NULL,
	window_start INTEGER NOT NULL
);
