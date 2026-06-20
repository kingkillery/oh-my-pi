import type { AgentMessage } from "@pk-nerdsaver-ai/pi-agent-core";
import type { Api, ImageContent, Model, TextContent } from "@pk-nerdsaver-ai/pi-ai";
import { truncateToWidth } from "@pk-nerdsaver-ai/pi-tui";
import type { ModelRegistry } from "../config/model-registry";
import type { Settings } from "../config/settings";
import type { SessionEntry } from "../session/session-entries";
import { generateSessionTitle } from "./title-generator";

const DEFAULT_BACKGROUND_AGENT_NAME = "Background agent";
const MAX_BACKGROUND_AGENT_NAME_WIDTH = 40;

interface BackgroundNameSessionContext {
	modelRegistry: ModelRegistry;
	sessionId: string;
	model?: Model<Api>;
	agent: {
		metadataForProvider(provider: string): Record<string, unknown> | undefined;
	};
}

function messageContentToText(content: string | readonly (TextContent | ImageContent)[]): string {
	if (typeof content === "string") return content.trim();
	const parts: string[] = [];
	for (const block of content) {
		if (block.type !== "text") continue;
		parts.push(block.text);
	}
	return parts.join("\n").trim();
}

function fallbackBackgroundAgentName(seed: string | undefined): string {
	return truncateToWidth(seed?.trim() || DEFAULT_BACKGROUND_AGENT_NAME, MAX_BACKGROUND_AGENT_NAME_WIDTH);
}

export function extractLatestUserPromptText(entries: readonly SessionEntry[]): string | undefined {
	for (let i = entries.length - 1; i >= 0; i--) {
		const entry = entries[i];
		if (entry.type !== "message") continue;
		const message = entry.message as AgentMessage;
		if (message.role !== "user") continue;
		const text = messageContentToText(message.content as string | readonly (TextContent | ImageContent)[]);
		if (text) return text;
	}
	return undefined;
}

export async function generateBackgroundAgentName(
	seed: string | undefined,
	session: BackgroundNameSessionContext,
	settings: Settings,
	customSystemPrompt?: string,
): Promise<string> {
	const trimmed = seed?.trim();
	if (!trimmed) return fallbackBackgroundAgentName(undefined);
	const generated = await generateSessionTitle(
		trimmed,
		session.modelRegistry,
		settings,
		session.sessionId,
		session.model,
		provider => session.agent.metadataForProvider(provider),
		customSystemPrompt,
	);
	return fallbackBackgroundAgentName(generated ?? trimmed);
}
