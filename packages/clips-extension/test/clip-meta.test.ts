/**
 * Clip metadata contract: Whisper output normalization (the part that crosses a
 * network boundary and varies by model) and the agent-readable briefing that
 * agents consume from `/clip/<id>/agent`.
 */
import { describe, expect, it } from "bun:test";
import { type ClipMeta, parseWhisperResult, renderAgentContext } from "../src/clip-meta";

describe("parseWhisperResult", () => {
	it("prefers explicit segments with start times", () => {
		const t = parseWhisperResult({
			text: "hello world",
			segments: [
				{ start: 0, text: "hello" },
				{ start: 1.5, text: "world" },
			],
		});
		expect(t.segments).toEqual([
			{ start: 0, text: "hello" },
			{ start: 1.5, text: "world" },
		]);
	});

	it("falls back to parsing a WebVTT body when no segments array is present", () => {
		const vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nfirst line\n\n00:00:02.000 --> 00:00:04.000\nsecond line";
		const t = parseWhisperResult({ vtt });
		expect(t.segments.map(s => s.text)).toEqual(["first line", "second line"]);
		expect(t.segments[1]?.start).toBe(2);
	});

	it("falls back to a single whole-text segment", () => {
		const t = parseWhisperResult({ text: "just one blob of text" });
		expect(t.segments).toEqual([{ start: 0, text: "just one blob of text" }]);
	});

	it("returns an empty transcript for unusable input", () => {
		expect(parseWhisperResult(null)).toEqual({ text: "", segments: [] });
		expect(parseWhisperResult({})).toEqual({ text: "", segments: [] });
	});
});

describe("renderAgentContext", () => {
	const meta: ClipMeta = {
		id: "abc123",
		title: "Bug repro",
		description: "Login button does nothing",
		timestamp: "2026-06-22T00:00:00.000Z",
		transcript: { text: "click login", segments: [{ start: 3, text: "I click the login button" }] },
		frames: [
			{ timestamp: 0, filename: "frame_0.jpg" },
			{ timestamp: 4, filename: "frame_1.jpg" },
		],
	};

	it("emits timestamped transcript lines and absolute frame URLs an agent can fetch", () => {
		const md = renderAgentContext(meta, "https://gopk.xyz");
		expect(md).toContain("# Clip: Bug repro");
		expect(md).toContain("[00:03] I click the login button");
		// Frame URLs must be absolute and indexed so an agent can pull the screen at a moment.
		expect(md).toContain("https://gopk.xyz/clip/abc123/frame/0");
		expect(md).toContain("[00:04] https://gopk.xyz/clip/abc123/frame/1");
		expect(md).toContain("https://gopk.xyz/clip/abc123/video");
	});

	it("notes absent speech and screenshots rather than emitting empty sections", () => {
		const empty: ClipMeta = { ...meta, transcript: { text: "", segments: [] }, frames: [] };
		const md = renderAgentContext(empty, "https://gopk.xyz");
		expect(md).toContain("_(no speech detected)_");
		expect(md).toContain("_(no screenshots captured)_");
	});
});
