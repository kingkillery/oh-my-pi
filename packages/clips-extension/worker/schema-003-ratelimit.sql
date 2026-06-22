-- Migration 003: fixed-window rate limiting for the unauthenticated auth surface.
CREATE TABLE IF NOT EXISTS rate_limits (
	k TEXT PRIMARY KEY,
	count INTEGER NOT NULL,
	window_start INTEGER NOT NULL
);
