#!/usr/bin/env bun
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
/**
 * Clips upload CLI — turn any recorded video file into a gopk.xyz share link.
 *
 * Record with whatever you like (Windows Win+Shift+R / Snipping Tool, macOS
 * Cmd+Shift+5, OBS, …), then:
 *
 *   bun run src/upload.ts <video-file> [--title "..."] [--host https://gopk.xyz]
 *
 * ffmpeg pulls a mono audio track (for Whisper transcription) and one JPEG
 * screenshot every 2s (so agents can see the screen at any moment), uploads
 * them with the video, prints the share link, and copies it to the clipboard.
 */
import { $ } from "bun";

const FRAME_INTERVAL_SECONDS = 2;

const VIDEO_TYPES: Record<string, string> = {
	".mp4": "video/mp4",
	".webm": "video/webm",
	".mkv": "video/x-matroska",
	".mov": "video/quicktime",
	".avi": "video/x-msvideo",
};

interface CliArgs {
	file: string;
	title?: string;
	host: string;
	token?: string;
}

function parseArgs(argv: string[]): CliArgs {
	let file: string | undefined;
	let title: string | undefined;
	let host = process.env.GOPK_CLIPS_URL?.replace(/\/+$/, "") || "https://gopk.xyz";
	let token = process.env.GOPK_CLIPS_TOKEN?.trim() || undefined;
	for (let i = 0; i < argv.length; i++) {
		const arg = argv[i];
		if (arg === "--title") title = argv[++i];
		else if (arg === "--host") host = (argv[++i] ?? host).replace(/\/+$/, "");
		else if (arg === "--token") token = argv[++i];
		else if (!arg?.startsWith("--")) file = arg;
	}
	if (!file) {
		throw new Error("Usage: bun run src/upload.ts <video-file> [--title <t>] [--host <url>] [--token <t>]");
	}
	return { file, title, host, token };
}

async function copyToClipboard(text: string): Promise<void> {
	const input = new Blob([text]);
	try {
		if (process.platform === "win32") await $`clip < ${input}`.quiet();
		else if (process.platform === "darwin") await $`pbcopy < ${input}`.quiet();
		else await $`xclip -selection clipboard < ${input}`.quiet();
	} catch {
		// No clipboard utility — the printed URL is enough.
	}
}

async function main(): Promise<void> {
	const { file, title, host, token } = parseArgs(Bun.argv.slice(2));
	const videoBytes = await Bun.file(file).bytes();
	const ext = path.extname(file).toLowerCase();
	const videoType = VIDEO_TYPES[ext] ?? "video/webm";

	const work = await fs.mkdtemp(path.join(os.tmpdir(), "clips-upload-"));
	try {
		// 1. Extract a mono 16kHz audio track for Whisper (no-op-safe if the video is silent).
		const audioPath = path.join(work, "audio.mp3");
		let hasAudio = true;
		const audioRes = await $`ffmpeg -y -i ${file} -vn -ac 1 -ar 16000 -c:a libmp3lame ${audioPath}`.quiet().nothrow();
		if (audioRes.exitCode !== 0) hasAudio = false;

		// 2. Extract one screenshot every FRAME_INTERVAL_SECONDS.
		const framePattern = path.join(work, "frame_%03d.jpg");
		await $`ffmpeg -y -i ${file} -vf fps=1/${FRAME_INTERVAL_SECONDS},scale=640:-2 -q:v 4 ${framePattern}`
			.quiet()
			.nothrow();
		const frameFiles = (await fs.readdir(work)).filter(n => n.startsWith("frame_") && n.endsWith(".jpg")).sort();

		// 3. Build the multipart upload (same contract as the browser recorder).
		const form = new FormData();
		form.append("title", title ?? path.basename(file));
		form.append("video", new Blob([videoBytes], { type: videoType }), `video${ext || ".webm"}`);
		if (hasAudio) {
			form.append("audio", new Blob([await Bun.file(audioPath).bytes()], { type: "audio/mpeg" }), "audio.mp3");
		}
		const frameMeta: { timestamp: number; filename: string }[] = [];
		for (let i = 0; i < frameFiles.length; i++) {
			const name = frameFiles[i]!;
			frameMeta.push({ timestamp: i * FRAME_INTERVAL_SECONDS, filename: name });
			form.append("files", new Blob([await Bun.file(path.join(work, name)).bytes()], { type: "image/jpeg" }), name);
		}
		form.append("frames", JSON.stringify(frameMeta));

		process.stdout.write(
			`Uploading ${path.basename(file)} (${frameFiles.length} frames${hasAudio ? ", with audio" : ", no audio"})…\n`,
		);
		const res = await fetch(`${host}/api/upload`, {
			method: "POST",
			body: form,
			headers: token ? { authorization: `Bearer ${token}` } : undefined,
		});
		if (!res.ok) throw new Error(`Upload failed: HTTP ${res.status} ${await res.text()}`);
		const parsed: unknown = await res.json();
		const url =
			typeof parsed === "object" && parsed && "url" in parsed && typeof parsed.url === "string"
				? parsed.url
				: `${host}`;

		await copyToClipboard(url);
		process.stdout.write(
			`\n✅ Clip ready: ${url}\n   (copied to clipboard — paste it to an agent or run /clip ${url})\n`,
		);
	} finally {
		await fs.rm(work, { recursive: true, force: true });
	}
}

main().catch(err => {
	process.stderr.write(`${err instanceof Error ? err.message : String(err)}\n`);
	process.exit(1);
});
