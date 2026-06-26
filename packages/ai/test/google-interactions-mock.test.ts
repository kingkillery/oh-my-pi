/**
 * Unit test for Google Interactions API provider — mocked HTTP.
 * Validates request building, response parsing, and event stream mapping
 * without hitting a real API.
 */
import { describe, expect, it } from "bun:test";
import {
	type GoogleInteractionsOptions,
	streamGoogleInteractions,
} from "@pk-nerdsaver-ai/pi-ai/providers/google-interactions";
import type {
	AssistantMessage,
	AssistantMessageEvent,
	Context,
	Model,
	TextContent,
	ToolCall,
} from "@pk-nerdsaver-ai/pi-ai/types";
import { buildModel } from "@pk-nerdsaver-ai/pi-catalog/build";

const model: Model<"google-interactions"> = buildModel({
	id: "gemini-3.5-flash",
	name: "Gemini 3.5 Flash",
	api: "google-interactions",
	provider: "google-interactions",
	baseUrl: "https://fake.test",
	reasoning: true,
	input: ["text", "image"],
	cost: { input: 1.5, output: 9, cacheRead: 0.15, cacheWrite: 0 },
	contextWindow: 1048576,
	maxTokens: 65536,
});

function makeContext(text: string): Context {
	return {
		messages: [{ role: "user", content: text, timestamp: Date.now() }],
		tools: [],
	};
}

async function collectEvents(stream: AsyncIterable<AssistantMessageEvent>): Promise<AssistantMessageEvent[]> {
	const events: AssistantMessageEvent[] = [];
	for await (const event of stream) {
		events.push(event);
	}
	return events;
}

function mockFetch(body: unknown, status = 200): typeof fetch {
	return (async (_url: string | URL | Request, _init?: RequestInit) => {
		return new Response(JSON.stringify(body), {
			status,
			headers: { "content-type": "application/json" },
		});
	}) as unknown as typeof fetch;
}

const TEXT_RESPONSE = {
	id: "test-interaction-123",
	steps: [
		{
			type: "model_output",
			content: [
				{
					type: "text",
					text: "Four.",
				},
			],
		},
	],
	usage_metadata: {
		prompt_token_count: 10,
		candidates_token_count: 5,
		total_token_count: 15,
	},
};

const COMPUTER_USE_RESPONSE = {
	id: "test-interaction-456",
	steps: [
		{
			type: "function_call",
			id: "call-1",
			name: "navigate",
			arguments: { url: "https://example.com" },
		},
		{
			type: "function_call",
			id: "call-2",
			name: "take_screenshot",
			arguments: {},
		},
	],
	usage_metadata: {
		prompt_token_count: 50,
		candidates_token_count: 20,
		total_token_count: 70,
	},
};

describe("Google Interactions API (mocked)", () => {
	it("parses a text-only model_output response", async () => {
		const context = makeContext("What is 2 + 2?");
		const options: GoogleInteractionsOptions = {
			apiKey: "fake-key",
			fetch: mockFetch(TEXT_RESPONSE) as any,
		};

		const events = await collectEvents(streamGoogleInteractions(model, context, options));

		const doneEvent = events.find(e => e.type === "done");
		expect(doneEvent).toBeDefined();
		expect(doneEvent!.type).toBe("done");

		const msg = (doneEvent as any).message as AssistantMessage;
		expect(msg.role).toBe("assistant");
		expect(msg.content.length).toBeGreaterThan(0);
		expect(msg.stopReason).toBe("stop");

		const textContent = msg.content.find(b => b.type === "text") as TextContent;
		expect(textContent).toBeDefined();
		expect(textContent.text).toBe("Four.");

		expect(msg.usage.input).toBe(10);
		expect(msg.usage.output).toBe(5);
	});

	it("parses function_call steps as tool calls", async () => {
		const context = makeContext("Navigate to https://example.com");
		const options: GoogleInteractionsOptions = {
			apiKey: "fake-key",
			environment: "browser",
			fetch: mockFetch(COMPUTER_USE_RESPONSE) as any,
		};

		const events = await collectEvents(streamGoogleInteractions(model, context, options));

		const doneEvent = events.find(e => e.type === "done");
		expect(doneEvent).toBeDefined();

		const msg = (doneEvent as any).message as AssistantMessage;
		expect(msg.role).toBe("assistant");

		const toolCalls = msg.content.filter(b => b.type === "toolCall") as ToolCall[];
		expect(toolCalls.length).toBe(2);

		expect(toolCalls[0]!.name).toBe("navigate");
		expect((toolCalls[0] as any).arguments?.url).toBe("https://example.com");

		expect(toolCalls[1]!.name).toBe("take_screenshot");
	});

	it("handles HTTP errors gracefully", async () => {
		const context = makeContext("test");
		const errorBody = { error: { message: "Invalid API key", status: "UNAUTHENTICATED" } };
		const options: GoogleInteractionsOptions = {
			apiKey: "bad-key",
			fetch: mockFetch(errorBody, 401) as any,
		};

		const events = await collectEvents(streamGoogleInteractions(model, context, options));

		const errorEvent = events.find(e => e.type === "error");
		expect(errorEvent).toBeDefined();

		const errorMsg = (errorEvent as any).error as AssistantMessage;
		expect(errorMsg.errorMessage).toContain("Invalid API key");
	});

	it("verifies request body structure", async () => {
		let capturedBody: any;
		const captureFetch = (async (_url: string | URL | Request, init?: RequestInit) => {
			capturedBody = JSON.parse(init?.body as string);
			return new Response(JSON.stringify(TEXT_RESPONSE), {
				status: 200,
				headers: { "content-type": "application/json" },
			});
		}) as unknown as typeof fetch;

		const context = makeContext("Hello world");
		const options: GoogleInteractionsOptions = {
			apiKey: "fake-key",
			environment: "browser",
			enablePromptInjectionDetection: true,
			fetch: captureFetch as any,
		};

		await collectEvents(streamGoogleInteractions(model, context, options));

		expect(capturedBody).toBeDefined();
		expect(capturedBody.model).toBe("gemini-3.5-flash");
		expect(capturedBody.input).toBeDefined();

		const computerUseTool = capturedBody.tools?.find((t: any) => t.type === "computer_use");
		expect(computerUseTool).toBeDefined();
		expect(computerUseTool.environment).toBe("browser");
		expect(computerUseTool.enable_prompt_injection_detection).toBe(true);
	});

	it("maps stop reason to toolUse when function_calls present", async () => {
		const context = makeContext("click something");
		const options: GoogleInteractionsOptions = {
			apiKey: "fake-key",
			fetch: mockFetch(COMPUTER_USE_RESPONSE) as any,
		};

		const events = await collectEvents(streamGoogleInteractions(model, context, options));
		const doneEvent = events.find(e => e.type === "done") as any;
		expect(doneEvent).toBeDefined();
		expect(doneEvent.message.stopReason).toBe("toolUse");
	});
});
