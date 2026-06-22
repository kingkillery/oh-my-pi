/**
 * Shared clip metadata contract used by both the Cloudflare Worker and the
 * local Bun server. A clip is stored as a self-contained folder/prefix:
 *   <id>/meta.json   — this metadata (transcript + frame index)
 *   <id>/video.webm  — the screen recording
 *   <id>/audio.webm  — the voice track (fed to Whisper)
 *   <id>/frame_N.jpg — timestamped screenshots
 * No database required: the prefix IS the record.
 */

export interface TranscriptSegment {
	/** Start time in seconds from the beginning of the clip. */
	start: number;
	text: string;
}

export interface Transcript {
	text: string;
	segments: TranscriptSegment[];
}

export interface ClipFrame {
	/** Seconds from clip start when the screenshot was captured. */
	timestamp: number;
	filename: string;
}

export interface ClipMeta {
	id: string;
	title: string;
	description: string;
	/** ISO-8601 creation time. */
	timestamp: string;
	transcript: Transcript;
	frames: ClipFrame[];
	/** Content-type the recording was uploaded with (so MP4/WebM play back correctly). */
	videoType?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

/** Parse a `HH:MM:SS.mmm` or `MM:SS.mmm` WebVTT timestamp into seconds. */
function parseVttTimestamp(stamp: string): number {
	const parts = stamp.trim().split(":");
	if (parts.length === 0) return 0;
	let seconds = 0;
	for (const part of parts) seconds = seconds * 60 + Number.parseFloat(part);
	return Number.isFinite(seconds) ? seconds : 0;
}

/** Extract `[{ start, text }]` cues from a WebVTT body. */
function segmentsFromVtt(vtt: string): TranscriptSegment[] {
	const segments: TranscriptSegment[] = [];
	const blocks = vtt.split(/\r?\n\r?\n/);
	for (const block of blocks) {
		const lines = block.split(/\r?\n/).filter(line => line.trim().length > 0);
		const cueLine = lines.find(line => line.includes("-->"));
		if (!cueLine) continue;
		const start = parseVttTimestamp(cueLine.split("-->")[0] ?? "0");
		const text = lines
			.slice(lines.indexOf(cueLine) + 1)
			.join(" ")
			.trim();
		if (text) segments.push({ start, text });
	}
	return segments;
}

/**
 * Normalize a Whisper-like result (Workers AI or OpenAI) into our Transcript
 * contract. Prefers explicit `segments`, falls back to parsing `vtt`, then to a
 * single whole-text segment. Tolerant of unknown/partial shapes by design — the
 * input crosses a network boundary.
 */
export function parseWhisperResult(result: unknown): Transcript {
	if (!isRecord(result)) return { text: "", segments: [] };
	const text = typeof result.text === "string" ? result.text : "";

	// 1. Explicit segments array: [{ start, text }]
	if (Array.isArray(result.segments)) {
		const segments: TranscriptSegment[] = [];
		for (const seg of result.segments) {
			if (!isRecord(seg)) continue;
			const start = typeof seg.start === "number" ? seg.start : 0;
			const segText = typeof seg.text === "string" ? seg.text.trim() : "";
			if (segText) segments.push({ start, text: segText });
		}
		if (segments.length > 0) return { text: text || segments.map(s => s.text).join(" "), segments };
	}

	// 2. WebVTT body.
	if (typeof result.vtt === "string" && result.vtt.includes("-->")) {
		const segments = segmentsFromVtt(result.vtt);
		if (segments.length > 0) return { text: text || segments.map(s => s.text).join(" "), segments };
	}

	// 3. Whole text as one segment.
	if (text) return { text, segments: [{ start: 0, text }] };
	return { text: "", segments: [] };
}

/** Render clip metadata as a compact agent-readable markdown briefing. */
export function renderAgentContext(meta: ClipMeta, origin: string, urlSuffix = ""): string {
	const lines: string[] = [];
	lines.push(`# Clip: ${meta.title}`);
	lines.push("");
	if (meta.description) lines.push(meta.description, "");
	lines.push(`Recorded: ${meta.timestamp}`);
	lines.push(`Video: ${origin}/clip/${meta.id}/video${urlSuffix}`);
	lines.push("");
	lines.push("## Transcript");
	if (meta.transcript.segments.length > 0) {
		for (const seg of meta.transcript.segments) {
			lines.push(`- [${formatTimestamp(seg.start)}] ${seg.text}`);
		}
	} else {
		lines.push("_(no speech detected)_");
	}
	lines.push("");
	lines.push("## Screenshots (fetch any frame URL to see the screen at that moment)");
	if (meta.frames.length > 0) {
		for (let i = 0; i < meta.frames.length; i++) {
			const frame = meta.frames[i]!;
			lines.push(`- [${formatTimestamp(frame.timestamp)}] ${origin}/clip/${meta.id}/frame/${i}${urlSuffix}`);
		}
	} else {
		lines.push("_(no screenshots captured)_");
	}
	return lines.join("\n");
}

export function formatTimestamp(seconds: number): string {
	const m = Math.floor(seconds / 60)
		.toString()
		.padStart(2, "0");
	const s = Math.floor(seconds % 60)
		.toString()
		.padStart(2, "0");
	return `${m}:${s}`;
}
