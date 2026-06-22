-- Migration 002: email + email verification.
ALTER TABLE users ADD COLUMN email TEXT;
ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS verifications (
	token TEXT PRIMARY KEY,
	user_id TEXT NOT NULL,
	expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verifications_user ON verifications(user_id);

-- Remove leftover test accounts (no real users existed before email verification).
DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'tester%' OR username LIKE 'dbg%');
DELETE FROM clips WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'tester%' OR username LIKE 'dbg%');
DELETE FROM users WHERE username LIKE 'tester%' OR username LIKE 'dbg%';
