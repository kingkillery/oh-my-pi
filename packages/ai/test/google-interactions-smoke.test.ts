/**
 * Smoke test for the Google Interactions API provider (Computer Use).
 *
 * Sends a simple text-only request to verify the Interactions API endpoint
 * is reachable and the response parsing works. Does NOT require a real
 * browser/screen — just validates the API roundtrip.
 *
 * Requires GEMINI_API_KEY to be set.
 */
import { describe, expect, it } from "bun:test";
import {
	type GoogleInteractionsOptions,
	streamGoogleInteractions,
} from "@pk-nerdsaver-ai/pi-ai/providers/google-interactions";
import type { AssistantMessage, AssistantMessageEvent, Context, Model } from "@pk-nerdsaver-ai/pi-ai/types";
import { buildModel } from "@pk-nerdsaver-ai/pi-catalog/build";

const API_KEY = process.env.GEMINI_API_KEY;

const model: Model<"google-interactions"> = buildModel({
	id: "gemini-3.5-flash",
	name: "Gemini 3.5 Flash",
	api: "google-interactions",
	provider: "google-interactions",
	baseUrl: "https://generativelanguage.googleapis.com/v1beta",
	reasoning: true,
	input: ["text", "image"],
	cost: { input: 1.5, output: 9, cacheRead: 0.15, cacheWrite: 0 },
	contextWindow: 1048576,
	maxTokens: 65536,
});

function makeContext(text: string): Context {
	return {
		messages: [{ role: "user", content: [{ type: "text", text }], timestamp: Date.now() }],
		tools: [],
	};
}

async function collectStream(stream: AsyncIterable<AssistantMessageEvent>): Promise<AssistantMessage> {
	for await (const event of stream) {
		if (event.type === "done") return event.message;
		if (event.type === "error") {
			throw new Error(event.error.errorMessage ?? "Stream error");
		}
	}
	throw new Error("Stream ended without done/error event");
}

describe.skipIf(!API_KEY)("Google Interactions API", () => {
	it("sends a basic text request and gets a response", async () => {
		const context = makeContext("What is 2 + 2? Answer in one word.");
		const options: GoogleInteractionsOptions = { apiKey: API_KEY! };

		const stream = streamGoogleInteractions(model, context, options);
		const result = await collectStream(stream);

		expect(result.role).toBe("assistant");
		expect(result.content.length).toBeGreaterThan(0);
		expect(result.stopReason).toBe("stop");

		const textBlocks = result.content.filter(b => b.type === "text");
		expect(textBlocks.length).toBeGreaterThan(0);

		const fullText = textBlocks.map(b => (b as any).text).join("");
		console.log("Response text:", fullText);
		expect(fullText.toLowerCase()).toContain("four");
	}, 30_000);

	it("sends a computer_use browser request and gets function calls", async () => {
		const context = makeContext("Navigate to https://example.com and describe what you see.");
		const options: GoogleInteractionsOptions = {
			apiKey: API_KEY!,
			environment: "browser",
			enablePromptInjectionDetection: true,
		};

		const stream = streamGoogleInteractions(model, context, options);
		const result = await collectStream(stream);

		expect(result.role).toBe("assistant");
		expect(result.content.length).toBeGreaterThan(0);

		const hasToolCall = result.content.some(b => b.type === "toolCall");
		const hasText = result.content.some(b => b.type === "text");
		console.log(
			"Computer Use response:",
			hasToolCall ? "has tool calls" : "no tool calls",
			hasText ? "has text" : "no text",
		);
		console.log(
			"Content types:",
			result.content.map(b => b.type),
		);
		console.log("Stop reason:", result.stopReason);

		if (hasToolCall) {
			const toolCalls = result.content.filter(b => b.type === "toolCall") as any[];
			for (const tc of toolCalls) {
				console.log(`  Tool call: ${tc.name}`, JSON.stringify(tc.arguments));
			}
		}

		expect(hasToolCall || hasText).toBe(true);
	}, 60_000);
});
