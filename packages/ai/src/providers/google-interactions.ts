/**
 * Google Interactions API provider.
 *
 * Implements the Gemini Interactions API (`POST /v1beta/interactions`) which
 * powers agentic workflows with built-in tools like Computer Use, Google
 * Search, Code Execution, and URL Context.
 *
 * Unlike `generateContent`, the Interactions API returns typed execution steps
 * (function_call / model_output) and supports multi-turn agent loops via
 * `previous_interaction_id`.
 *
 * @see https://ai.google.dev/gemini-api/docs/interactions-overview
 * @see https://ai.google.dev/gemini-api/docs/computer-use
 */

import { calculateCost } from "@pk-nerdsaver-ai/pi-catalog/models";
import { ProviderHttpError } from "../errors";
import { getEnvApiKey } from "../stream";
import type { Api, AssistantMessage, Context, Model, StreamOptions, TextContent, ToolCall } from "../types";
import { AssistantMessageEventStream } from "../utils/event-stream";
import type {
	ComputerUseEnvironment,
	FunctionCallStep,
	InputPart,
	InteractionsRequest,
	InteractionsResponse,
	InteractionsTool,
	ModelOutputStep,
} from "./google-interactions-types";

// ---------------------------------------------------------------------------
// Options
// ---------------------------------------------------------------------------

export interface GoogleInteractionsOptions extends StreamOptions {
	apiKey?: string;
	headers?: Record<string, string>;
	environment?: ComputerUseEnvironment;
	enablePromptInjectionDetection?: boolean;
	previousInteractionId?: string;
	screenshotBase64?: string;
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class GoogleInteractionsApiError extends ProviderHttpError {
	override readonly name = "GoogleInteractionsApiError";
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta";

// ---------------------------------------------------------------------------
// Request builder
// ---------------------------------------------------------------------------

function buildInteractionsRequest(
	model: Model<"google-interactions">,
	context: Context,
	options: GoogleInteractionsOptions,
): InteractionsRequest {
	const lastUserMessage = context.messages.findLast(m => m.role === "user");
	const userText = lastUserMessage?.content ?? "";

	const tools: InteractionsTool[] = [];
	const environment = options.environment ?? "browser";
	tools.push({
		type: "computer_use",
		environment,
		...(options.enablePromptInjectionDetection ? { enable_prompt_injection_detection: true } : {}),
	});

	const input: InputPart[] = [];
	if (typeof userText === "string" && userText.length > 0) {
		input.push({ type: "text", text: userText });
	}
	if (options.screenshotBase64) {
		input.push({
			type: "image",
			data: options.screenshotBase64,
			mime_type: "image/png",
		});
	}

	return {
		model: model.requestModelId ?? model.id,
		input: input.length > 0 ? input : typeof userText === "string" ? userText : "",
		tools,
		...(options.previousInteractionId ? { previous_interaction_id: options.previousInteractionId } : {}),
	};
}

// ---------------------------------------------------------------------------
// Response -> AssistantMessage mapping
// ---------------------------------------------------------------------------

function mapInteractionsResponse(
	response: InteractionsResponse,
	model: Model<"google-interactions">,
): {
	content: AssistantMessage["content"];
	stopReason: AssistantMessage["stopReason"];
	usage: AssistantMessage["usage"];
	interactionId: string;
} {
	const content: AssistantMessage["content"] = [];

	for (const step of response.steps) {
		if (step.type === "model_output") {
			const outputStep = step as ModelOutputStep;
			for (const block of outputStep.content) {
				if (block.type === "text" && block.text.trim().length > 0) {
					content.push({ type: "text", text: block.text } as TextContent);
				}
			}
		} else if (step.type === "function_call") {
			const callStep = step as FunctionCallStep;
			const toolCall: ToolCall = {
				type: "toolCall",
				id: callStep.id,
				name: callStep.name,
				arguments: callStep.arguments as Record<string, any>,
			};
			content.push(toolCall);
		}
	}

	const hasToolCalls = content.some(c => c.type === "toolCall");
	const stopReason: AssistantMessage["stopReason"] = hasToolCalls ? "toolUse" : "stop";

	const cachedTokens = response.usage_metadata?.cached_content_token_count ?? 0;
	const thinkingTokens = response.usage_metadata?.thoughts_token_count ?? 0;
	const usage: AssistantMessage["usage"] = {
		input: (response.usage_metadata?.prompt_token_count ?? 0) - cachedTokens,
		output: (response.usage_metadata?.candidates_token_count ?? 0) + thinkingTokens,
		cacheRead: cachedTokens,
		cacheWrite: 0,
		totalTokens: response.usage_metadata?.total_token_count ?? 0,
		...(thinkingTokens > 0 ? { reasoningTokens: thinkingTokens } : {}),
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
	};
	calculateCost(model, usage);

	return { content, stopReason, usage, interactionId: response.id };
}

// ---------------------------------------------------------------------------
// Stream function
// ---------------------------------------------------------------------------

export const streamGoogleInteractions = (
	model: Model<"google-interactions">,
	context: Context,
	options?: GoogleInteractionsOptions,
): AssistantMessageEventStream => {
	const stream = new AssistantMessageEventStream();

	const run = async () => {
		const opts = options ?? {};
		const apiKey = opts.apiKey || getEnvApiKey(model.provider);
		if (!apiKey) {
			throw new Error("Google Interactions API requires an API key (GEMINI_API_KEY or options.apiKey).");
		}

		const base = model.baseUrl?.trim() || DEFAULT_BASE_URL;
		const url = `${base}/interactions`;
		const body = buildInteractionsRequest(model, context, opts);

		const fetchFn = opts.fetch ?? globalThis.fetch;
		const headers: Record<string, string> = {
			"Content-Type": "application/json",
			"x-goog-api-key": apiKey,
			...(model.headers ?? {}),
			...(opts.headers ?? {}),
		};

		const output: AssistantMessage = {
			role: "assistant",
			content: [],
			api: "google-interactions" as Api,
			provider: model.provider,
			model: model.id,
			usage: {
				input: 0,
				output: 0,
				cacheRead: 0,
				cacheWrite: 0,
				totalTokens: 0,
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
			},
			stopReason: "stop",
			timestamp: Date.now(),
		};

		stream.push({ type: "start", partial: output });

		const response = await fetchFn(url, {
			method: "POST",
			headers,
			body: JSON.stringify(body),
			signal: opts.signal,
		});

		if (!response.ok) {
			const errorText = await response.text().catch(() => "");
			const message = extractErrorMessage(errorText) || `HTTP ${response.status}`;
			throw new GoogleInteractionsApiError(`Google Interactions API error: ${message}`, response.status);
		}

		const json = (await response.json()) as InteractionsResponse;

		if (json.error) {
			const detail = json.error.message || json.error.status || "unknown error";
			throw new GoogleInteractionsApiError(`Google Interactions API error: ${detail}`, json.error.code ?? 500);
		}

		const result = mapInteractionsResponse(json, model);
		output.content = result.content;
		output.stopReason = result.stopReason;
		output.usage = result.usage;
		(output as AssistantMessage & { interactionId?: string }).interactionId = result.interactionId;

		let contentIndex = 0;
		for (const block of output.content) {
			if (block.type === "text") {
				stream.push({ type: "text_start", contentIndex, partial: output });
				stream.push({
					type: "text_delta",
					contentIndex,
					delta: block.text,
					partial: output,
				});
				stream.push({
					type: "text_end",
					contentIndex,
					content: block.text,
					partial: output,
				});
			} else if (block.type === "toolCall") {
				stream.push({ type: "toolcall_start", contentIndex, partial: output });
				stream.push({
					type: "toolcall_delta",
					contentIndex,
					delta: JSON.stringify(block.arguments),
					partial: output,
				});
				stream.push({
					type: "toolcall_end",
					contentIndex,
					toolCall: block,
					partial: output,
				});
			}
			contentIndex++;
		}

		stream.push({ type: "done", reason: output.stopReason as "stop" | "length" | "toolUse", message: output });
	};

	run().catch(error => {
		const output: AssistantMessage = {
			role: "assistant",
			content: [],
			api: "google-interactions" as Api,
			provider: model.provider,
			model: model.id,
			stopReason: "error",
			errorMessage: error instanceof Error ? error.message : String(error),
			usage: {
				input: 0,
				output: 0,
				cacheRead: 0,
				cacheWrite: 0,
				totalTokens: 0,
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
			},
			timestamp: Date.now(),
		};
		stream.push({ type: "error", reason: "error", error: output });
	});

	return stream;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractErrorMessage(errorText: string): string {
	try {
		const parsed = JSON.parse(errorText);
		return parsed?.error?.message || parsed?.message || "";
	} catch {
		return errorText.slice(0, 200);
	}
}
