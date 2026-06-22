/**
 * gopk.xyz Clips Worker — multi-user, account-gated.
 *
 * Auth: username/password accounts in D1. Browsers use an HttpOnly session
 * cookie; agents/CLI use a per-user API token (Bearer / ?t=). Every clip's
 * binaries live in R2 under `u/<userId>/<clipId>/…`, and a `clips` row in D1 is
 * the source of truth for ownership/title/transcript — so a user only ever
 * reaches their own data.
 */
import { type ClipMeta, parseWhisperResult, renderAgentContext, type Transcript } from "../../src/clip-meta";
import uiHtml from "./ui.html";

interface UserRow {
	id: string;
	username: string;
	email: string | null;
	email_verified: number;
	password_hash: string;
	api_token: string;
	created_at: number;
}

interface ClipRow {
	id: string;
	user_id: string;
	title: string;
	description: string;
	video_type: string;
	transcript_json: string;
	frames_json: string;
	created_at: number;
}

const HTML_HEADERS = { "content-type": "text/html; charset=utf-8" } as const;
const JSON_HEADERS = { "content-type": "application/json; charset=utf-8" } as const;
const SESSION_COOKIE = "gopk_session";
const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const PBKDF2_ITERATIONS = 100_000; // Cloudflare Workers caps PBKDF2 at 100k iterations.
const USERNAME_RE = /^[a-z0-9_.-]{3,32}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const VERIFICATION_TTL_MS = 24 * 60 * 60 * 1000;
const EMAIL_FROM = { email: "noreply@gopk.xyz", name: "Clips" };
const RL_LIMIT = 20;
const RL_WINDOW_MS = 60_000;

function json(body: unknown, status = 200, headers?: HeadersInit): Response {
	return new Response(JSON.stringify(body), { status, headers: { ...JSON_HEADERS, ...headers } });
}

/** Fixed-window per-key limiter (D1-backed). Checked before expensive work like password hashing. */
async function rateLimited(env: Env, key: string): Promise<boolean> {
	const now = Date.now();
	const row = await env.DB.prepare(
		`INSERT INTO rate_limits (k, count, window_start) VALUES (?1, 1, ?2)
		 ON CONFLICT(k) DO UPDATE SET
		   count = CASE WHEN rate_limits.window_start <= ?3 THEN 1 ELSE rate_limits.count + 1 END,
		   window_start = CASE WHEN rate_limits.window_start <= ?3 THEN ?2 ELSE rate_limits.window_start END
		 RETURNING count`,
	)
		.bind(key, now, now - RL_WINDOW_MS)
		.first<{ count: number }>();
	return (row?.count ?? 1) > RL_LIMIT;
}

// ─── crypto ──────────────────────────────────────────────────────────────────

function bytesToB64(bytes: Uint8Array): string {
	let str = "";
	for (const b of bytes) str += String.fromCharCode(b);
	return btoa(str);
}

function b64ToBytes(value: string): Uint8Array {
	return Uint8Array.from(atob(value), c => c.charCodeAt(0));
}

function randomToken(byteLength = 32): string {
	const bytes = crypto.getRandomValues(new Uint8Array(byteLength));
	let hex = "";
	for (const b of bytes) hex += b.toString(16).padStart(2, "0");
	return hex;
}

async function deriveBits(password: string, salt: Uint8Array, iterations: number): Promise<Uint8Array> {
	const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, [
		"deriveBits",
	]);
	const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", salt, iterations, hash: "SHA-256" }, key, 256);
	return new Uint8Array(bits);
}

async function hashPassword(password: string): Promise<string> {
	const salt = crypto.getRandomValues(new Uint8Array(16));
	const bits = await deriveBits(password, salt, PBKDF2_ITERATIONS);
	return `pbkdf2$${PBKDF2_ITERATIONS}$${bytesToB64(salt)}$${bytesToB64(bits)}`;
}

function timingSafeEqual(a: string, b: string): boolean {
	if (a.length !== b.length) return false;
	let diff = 0;
	for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
	return diff === 0;
}

async function verifyPassword(password: string, stored: string): Promise<boolean> {
	const parts = stored.split("$");
	if (parts.length !== 4 || parts[0] !== "pbkdf2") return false;
	const iterations = Number(parts[1]);
	if (!Number.isFinite(iterations) || iterations < 1) return false;
	const bits = await deriveBits(password, b64ToBytes(parts[2]!), iterations);
	return timingSafeEqual(bytesToB64(bits), parts[3]!);
}

// ─── auth ────────────────────────────────────────────────────────────────────

function getCookie(request: Request, name: string): string | null {
	const cookie = request.headers.get("cookie");
	if (!cookie) return null;
	for (const part of cookie.split(";")) {
		const eq = part.indexOf("=");
		if (eq !== -1 && part.slice(0, eq).trim() === name) return decodeURIComponent(part.slice(eq + 1).trim());
	}
	return null;
}

function sessionCookie(token: string, maxAgeSeconds: number): string {
	return `${SESSION_COOKIE}=${token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAgeSeconds}`;
}

async function resolveUser(request: Request, url: URL, env: Env): Promise<UserRow | null> {
	const authHeader = request.headers.get("authorization");
	const apiToken = authHeader?.startsWith("Bearer ") ? authHeader.slice(7).trim() : (url.searchParams.get("t") ?? "");
	if (apiToken) {
		const row = await env.DB.prepare("SELECT * FROM users WHERE api_token = ? AND email_verified = 1")
			.bind(apiToken)
			.first<UserRow>();
		if (row) return row;
	}
	const session = getCookie(request, SESSION_COOKIE);
	if (session) {
		const row = await env.DB.prepare(
			"SELECT u.* FROM users u JOIN sessions s ON s.user_id = u.id WHERE s.token = ? AND s.expires_at > ?",
		)
			.bind(session, Date.now())
			.first<UserRow>();
		if (row) return row;
	}
	return null;
}

async function readJsonBody(
	request: Request,
): Promise<{ username: string; password: string; email: string } | null> {
	try {
		const body: unknown = await request.json();
		if (!body || typeof body !== "object") return null;
		const username = "username" in body && typeof body.username === "string" ? body.username : "";
		const password = "password" in body && typeof body.password === "string" ? body.password : "";
		const email = "email" in body && typeof body.email === "string" ? body.email : "";
		return { username, password, email };
	} catch {
		return null;
	}
}

async function createVerification(env: Env, userId: string): Promise<string> {
	const token = randomToken();
	await env.DB.prepare("INSERT INTO verifications (token, user_id, expires_at) VALUES (?, ?, ?)")
		.bind(token, userId, Date.now() + VERIFICATION_TTL_MS)
		.run();
	return token;
}

async function sendVerificationEmail(env: Env, origin: string, email: string, token: string): Promise<void> {
	const link = `${origin}/verify?token=${token}`;
	await env.EMAIL.send({
		from: EMAIL_FROM,
		to: email,
		subject: "Verify your Clips account",
		text: `Welcome to Clips!\n\nConfirm your email to activate your account:\n${link}\n\nThis link expires in 24 hours. If you didn't sign up, ignore this email.`,
		html: `<div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto"><h2>Welcome to Clips</h2><p>Confirm your email to activate your account.</p><p><a href="${link}" style="display:inline-block;background:#0ea5e9;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:600">Verify email</a></p><p style="color:#64748b;font-size:13px">Or paste this link: ${link}<br>The link expires in 24 hours. If you didn't sign up, ignore this email.</p></div>`,
	});
}

async function startSession(env: Env, userId: string): Promise<string> {
	const token = randomToken();
	await env.DB.prepare("INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)")
		.bind(token, userId, Date.now() + SESSION_TTL_MS)
		.run();
	return token;
}

async function handleSignup(request: Request, env: Env, origin: string): Promise<Response> {
	const body = await readJsonBody(request);
	if (!body) return json({ error: "Invalid request" }, 400);
	const username = body.username.trim().toLowerCase();
	const email = body.email.trim().toLowerCase();
	if (!USERNAME_RE.test(username)) {
		return json({ error: "Username must be 3-32 chars: letters, numbers, . _ -" }, 400);
	}
	if (!EMAIL_RE.test(email)) return json({ error: "Enter a valid email address" }, 400);
	if (body.password.length < 8) return json({ error: "Password must be at least 8 characters" }, 400);

	if (await env.DB.prepare("SELECT id FROM users WHERE username = ?").bind(username).first()) {
		return json({ error: "Username is taken" }, 409);
	}
	if (await env.DB.prepare("SELECT id FROM users WHERE email = ?").bind(email).first()) {
		return json({ error: "An account with that email already exists" }, 409);
	}

	const userId = randomToken(16);
	try {
		await env.DB.prepare(
			"INSERT INTO users (id, username, email, email_verified, password_hash, api_token, created_at) VALUES (?, ?, ?, 0, ?, ?, ?)",
		)
			.bind(userId, username, email, await hashPassword(body.password), `gopk_${randomToken()}`, Date.now())
			.run();
	} catch {
		return json({ error: "Username or email is taken" }, 409);
	}
	const token = await createVerification(env, userId);
	try {
		await sendVerificationEmail(env, origin, email, token);
	} catch (error) {
		console.error("verification email failed", error);
	}
	return json({ pendingVerification: true, email });
}

async function handleLogin(request: Request, env: Env): Promise<Response> {
	const body = await readJsonBody(request);
	if (!body) return json({ error: "Invalid request" }, 400);
	const username = body.username.trim().toLowerCase();
	const user = await env.DB.prepare("SELECT * FROM users WHERE username = ?").bind(username).first<UserRow>();
	// Always run a verification to keep timing uniform whether or not the user exists.
	const ok = user
		? await verifyPassword(body.password, user.password_hash)
		: await verifyPassword(body.password, `pbkdf2$${PBKDF2_ITERATIONS}$AAAA$AAAA`);
	if (!user || !ok) return json({ error: "Invalid username or password" }, 401);
	if (!user.email_verified) return json({ error: "Please verify your email first", needsVerification: true }, 403);
	const session = await startSession(env, user.id);
	return json({ username: user.username, apiToken: user.api_token }, 200, {
		"set-cookie": sessionCookie(session, SESSION_TTL_MS / 1000),
	});
}

async function handleVerify(request: Request, env: Env, origin: string): Promise<Response> {
	const token = new URL(request.url).searchParams.get("token") ?? "";
	const row = await env.DB.prepare("SELECT user_id FROM verifications WHERE token = ? AND expires_at > ?")
		.bind(token, Date.now())
		.first<{ user_id: string }>();
	if (!row) return Response.redirect(`${origin}/clip?verify=failed`, 302);
	await env.DB.prepare("UPDATE users SET email_verified = 1 WHERE id = ?").bind(row.user_id).run();
	await env.DB.prepare("DELETE FROM verifications WHERE user_id = ?").bind(row.user_id).run();
	const session = await startSession(env, row.user_id);
	return new Response(null, {
		status: 302,
		headers: { location: `${origin}/clip?verified=1`, "set-cookie": sessionCookie(session, SESSION_TTL_MS / 1000) },
	});
}

async function handleResend(request: Request, env: Env, origin: string): Promise<Response> {
	const body = await readJsonBody(request);
	const username = (body?.username ?? "").trim().toLowerCase();
	if (username) {
		const user = await env.DB.prepare(
			"SELECT id, email FROM users WHERE username = ? AND email_verified = 0",
		)
			.bind(username)
			.first<{ id: string; email: string | null }>();
		if (user?.email) {
			await env.DB.prepare("DELETE FROM verifications WHERE user_id = ?").bind(user.id).run();
			const token = await createVerification(env, user.id);
			try {
				await sendVerificationEmail(env, origin, user.email, token);
			} catch (error) {
				console.error("resend verification failed", error);
			}
		}
	}
	// Never reveal whether the account exists.
	return json({ ok: true });
}

async function handleLogout(request: Request, env: Env): Promise<Response> {
	const session = getCookie(request, SESSION_COOKIE);
	if (session) await env.DB.prepare("DELETE FROM sessions WHERE token = ?").bind(session).run();
	return json({ ok: true }, 200, { "set-cookie": `${SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0` });
}

// ─── clips ───────────────────────────────────────────────────────────────────

function clipMetaFromRow(row: ClipRow): ClipMeta {
	let transcript: Transcript = { text: "", segments: [] };
	let frames: ClipMeta["frames"] = [];
	try {
		transcript = JSON.parse(row.transcript_json) as Transcript;
	} catch {}
	try {
		frames = JSON.parse(row.frames_json) as ClipMeta["frames"];
	} catch {}
	return {
		id: row.id,
		title: row.title,
		description: row.description,
		timestamp: new Date(row.created_at).toISOString(),
		transcript,
		frames,
		videoType: row.video_type,
	};
}

async function transcribe(env: Env, audio: ArrayBuffer): Promise<Transcript> {
	try {
		const result = await env.AI.run("@cf/openai/whisper", { audio: [...new Uint8Array(audio)] });
		return parseWhisperResult(result);
	} catch {
		return { text: "", segments: [] };
	}
}

async function handleUpload(request: Request, env: Env, origin: string, user: UserRow): Promise<Response> {
	const form = await request.formData();
	const video = form.get("video");
	if (video === null || typeof video === "string") return new Response("Missing video", { status: 400 });

	const id = crypto.randomUUID();
	const prefix = `u/${user.id}/${id}`;
	const videoType = video.type || "video/webm";
	await env.CLIPS_BUCKET.put(`${prefix}/video.webm`, video.stream(), { httpMetadata: { contentType: videoType } });

	let transcript: Transcript = { text: "", segments: [] };
	const audio = form.get("audio");
	if (audio !== null && typeof audio !== "string") {
		const bytes = await audio.arrayBuffer();
		await env.CLIPS_BUCKET.put(`${prefix}/audio.webm`, bytes, { httpMetadata: { contentType: "audio/webm" } });
		transcript = await transcribe(env, bytes);
	}

	const frames: ClipMeta["frames"] = [];
	const framesRaw = form.get("frames");
	if (typeof framesRaw === "string") {
		const parsed: unknown = JSON.parse(framesRaw);
		if (Array.isArray(parsed)) {
			const files = form.getAll("files").filter((f): f is File => f instanceof File);
			for (let i = 0; i < parsed.length; i++) {
				const entry = parsed[i];
				const file = files[i];
				if (!entry || typeof entry !== "object" || !("timestamp" in entry) || !file) continue;
				const timestamp = typeof entry.timestamp === "number" ? entry.timestamp : 0;
				await env.CLIPS_BUCKET.put(`${prefix}/frame_${i}.jpg`, file.stream(), {
					httpMetadata: { contentType: "image/jpeg" },
				});
				frames.push({ timestamp, filename: `frame_${i}.jpg` });
			}
		}
	}

	const titleField = form.get("title");
	const descField = form.get("description");
	const title = typeof titleField === "string" && titleField.trim() ? titleField.trim() : "Untitled clip";
	const description = typeof descField === "string" ? descField : "";
	await env.DB.prepare(
		"INSERT INTO clips (id, user_id, title, description, video_type, transcript_json, frames_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
	)
		.bind(id, user.id, title, description, videoType, JSON.stringify(transcript), JSON.stringify(frames), Date.now())
		.run();

	return json({ id, url: `${origin}/clip/${id}` });
}

async function handleListClips(env: Env, user: UserRow): Promise<Response> {
	const rows = await env.DB.prepare(
		"SELECT id, title, description, frames_json, created_at FROM clips WHERE user_id = ? ORDER BY created_at DESC",
	)
		.bind(user.id)
		.all<Pick<ClipRow, "id" | "title" | "description" | "frames_json" | "created_at">>();
	const clips = rows.results.map(row => {
		let frameCount = 0;
		try {
			const f: unknown = JSON.parse(row.frames_json);
			if (Array.isArray(f)) frameCount = f.length;
		} catch {}
		return { id: row.id, title: row.title, description: row.description, createdAt: row.created_at, frameCount };
	});
	return json({ clips });
}

async function handleRename(request: Request, env: Env, user: UserRow, id: string): Promise<Response> {
	const body: unknown = await request.json().catch(() => null);
	if (!body || typeof body !== "object") return json({ error: "Invalid request" }, 400);
	const title = "title" in body && typeof body.title === "string" ? body.title.trim() : "";
	const description = "description" in body && typeof body.description === "string" ? body.description : "";
	if (!title) return json({ error: "Title is required" }, 400);
	const res = await env.DB.prepare("UPDATE clips SET title = ?, description = ? WHERE id = ? AND user_id = ?")
		.bind(title, description, id, user.id)
		.run();
	if (!res.meta.changes) return json({ error: "Clip not found" }, 404);
	return json({ ok: true });
}

async function handleDelete(env: Env, user: UserRow, id: string): Promise<Response> {
	const owned = await env.DB.prepare("SELECT id FROM clips WHERE id = ? AND user_id = ?").bind(id, user.id).first();
	if (!owned) return json({ error: "Clip not found" }, 404);
	const prefix = `u/${user.id}/${id}/`;
	const listed = await env.CLIPS_BUCKET.list({ prefix });
	if (listed.objects.length > 0) await env.CLIPS_BUCKET.delete(listed.objects.map(o => o.key));
	await env.DB.prepare("DELETE FROM clips WHERE id = ? AND user_id = ?").bind(id, user.id).run();
	return json({ ok: true });
}

async function getOwnedClip(env: Env, user: UserRow, id: string): Promise<ClipRow | null> {
	return env.DB.prepare("SELECT * FROM clips WHERE id = ? AND user_id = ?").bind(id, user.id).first<ClipRow>();
}

async function serveObject(env: Env, key: string, contentType: string): Promise<Response> {
	const object = await env.CLIPS_BUCKET.get(key);
	if (!object) return new Response("Not found", { status: 404 });
	const headers = new Headers();
	headers.set("content-type", contentType);
	headers.set("cache-control", "private, max-age=31536000, immutable");
	if (object.httpEtag) headers.set("etag", object.httpEtag);
	return new Response(object.body, { headers });
}

// ─── router ──────────────────────────────────────────────────────────────────

export default {
	async fetch(request: Request, env: Env): Promise<Response> {
		const url = new URL(request.url);
		const origin = url.origin;
		const path = url.pathname;

		if (path === "/" || path === "/record") return Response.redirect(`${origin}/clip`, 302);

		// Throttle the unauthenticated auth surface per client IP (brute-force / abuse protection).
		if (request.method === "POST" && (path === "/api/login" || path === "/api/signup" || path === "/api/resend")) {
			const ip = request.headers.get("cf-connecting-ip") ?? "unknown";
			if (await rateLimited(env, `auth:${ip}`)) {
				return json({ error: "Too many attempts. Please wait a minute and try again." }, 429);
			}
		}

		// Public auth endpoints.
		if (request.method === "POST" && path === "/api/signup") return handleSignup(request, env, origin);
		if (request.method === "POST" && path === "/api/login") return handleLogin(request, env);
		if (request.method === "POST" && path === "/api/resend") return handleResend(request, env, origin);
		if (request.method === "GET" && path === "/verify") return handleVerify(request, env, origin);

		// Page shells are public; the SPA shows the login screen when /api/me is 401.
		const clipMatch = path.match(/^\/clip(?:\/([^/]+))?(?:\/(.*))?$/);
		const id = clipMatch?.[1];
		const resource = clipMatch?.[2] ?? "";
		if (request.method === "GET" && clipMatch && resource === "") {
			return new Response(uiHtml, { headers: HTML_HEADERS });
		}

		// Everything below requires an authenticated user.
		const user = await resolveUser(request, url, env);
		if (!user) return json({ error: "Unauthorized" }, 401, { "www-authenticate": "Bearer" });

		if (request.method === "POST" && path === "/api/logout") return handleLogout(request, env);
		if (request.method === "GET" && path === "/api/me") return json({ username: user.username, apiToken: user.api_token });
		if (request.method === "POST" && path === "/api/upload") return handleUpload(request, env, origin, user);
		if (request.method === "GET" && path === "/api/clips") return handleListClips(env, user);

		const clipApi = path.match(/^\/api\/clip\/([^/]+)$/);
		if (clipApi) {
			const clipId = clipApi[1]!;
			if (request.method === "POST") return handleRename(request, env, user, clipId);
			if (request.method === "DELETE") return handleDelete(env, user, clipId);
			return new Response("Method not allowed", { status: 405 });
		}

		if (clipMatch && id) {
			if (resource === "json") {
				const row = await getOwnedClip(env, user, id);
				return row ? json(clipMetaFromRow(row)) : new Response("Not found", { status: 404 });
			}
			if (resource === "agent") {
				const row = await getOwnedClip(env, user, id);
				if (!row) return new Response("Not found", { status: 404 });
				return new Response(renderAgentContext(clipMetaFromRow(row), origin, `?t=${user.api_token}`), {
					headers: { "content-type": "text/markdown; charset=utf-8" },
				});
			}
			if (resource === "video") {
				const row = await getOwnedClip(env, user, id);
				if (!row) return new Response("Not found", { status: 404 });
				return serveObject(env, `u/${user.id}/${id}/video.webm`, row.video_type);
			}
			if (resource === "audio") return serveObject(env, `u/${user.id}/${id}/audio.webm`, "audio/webm");
			const frameMatch = resource.match(/^frame\/(\d+)$/);
			if (frameMatch) return serveObject(env, `u/${user.id}/${id}/frame_${frameMatch[1]}.jpg`, "image/jpeg");
		}

		return new Response("Not found", { status: 404 });
	},
} satisfies ExportedHandler<Env>;
