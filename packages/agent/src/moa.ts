import type {
	AssistantMessage,
	Context,
	Message,
	Model,
	SimpleStreamOptions,
	TextContent,
} from "@pk-nerdsaver-ai/pi-ai";
import { AssistantMessageEventStream } from "@pk-nerdsaver-ai/pi-ai/utils/event-stream";
import type { StreamFn } from "./types";

export interface MoaReadOnlyLane {
	readonly model: Model;
	readonly label?: string;
}

export interface MoaConfig {
	readonly lanes: readonly MoaReadOnlyLane[];
}

export function createMoaStreamFn(baseStream: StreamFn, config: MoaConfig): StreamFn {
	return (model, context, options) => {
		if (config.lanes.length === 0) {
			return baseStream(model, context, options);
		}
		const stream = new AssistantMessageEventStream();
		void runMoaStream(stream, baseStream, model, context, config, options);
		return stream;
	};
}

async function runMoaStream(
	stream: AssistantMessageEventStream,
	baseStream: StreamFn,
	synthesizer: Model,
	context: Context,
	config: MoaConfig,
	options: SimpleStreamOptions | undefined,
): Promise<void> {
	try {
		const advice = await collectReferenceAdvice(baseStream, context, config, options);
		const synthesizerStream = await baseStream(synthesizer, withMoaAdvice(context, advice), options);
		for await (const event of synthesizerStream) {
			stream.push(event);
		}
	} catch (err) {
		stream.fail(err);
	}
}

async function collectReferenceAdvice(
	baseStream: StreamFn,
	context: Context,
	config: MoaConfig,
	options: SimpleStreamOptions | undefined,
): Promise<readonly MoaAdvice[]> {
	const referenceContext = withoutTools(context);
	return Promise.all(
		config.lanes.map(async lane => ({
			label: lane.label ?? `${lane.model.provider}/${lane.model.id}`,
			message: await (await baseStream(lane.model, referenceContext, referenceOptions(options))).result(),
		})),
	);
}

function withoutTools(context: Context): Context {
	return {
		systemPrompt: context.systemPrompt,
		messages: context.messages,
	};
}

function referenceOptions(options: SimpleStreamOptions | undefined): SimpleStreamOptions | undefined {
	return options ? { ...options, toolChoice: "none" } : { toolChoice: "none" };
}

interface MoaAdvice {
	readonly label: string;
	readonly message: AssistantMessage;
}

function withMoaAdvice(context: Context, advice: readonly MoaAdvice[]): Context {
	return {
		...context,
		messages: [...context.messages, buildMoaAdviceMessage(advice)],
	};
}

function buildMoaAdviceMessage(advice: readonly MoaAdvice[]): Message {
	return {
		role: "developer",
		content: renderMoaAdvice(advice),
		timestamp: Date.now(),
	};
}

function renderMoaAdvice(advice: readonly MoaAdvice[]): string {
	const sections = advice.map(entry => `### ${entry.label}\n${assistantText(entry.message)}`);
	return [
		"<moa_reference_advice>",
		"Private advice from read-only candidate lanes. Use it as non-authoritative input; the synthesizer/verifier remains responsible for tool calls and the final response.",
		...sections,
		"</moa_reference_advice>",
	].join("\n\n");
}

function assistantText(message: AssistantMessage): string {
	const texts = message.content
		.filter((item): item is TextContent => item.type === "text")
		.map(item => item.text.trim());
	return texts.length > 0 ? texts.join("\n\n") : "(no text advice)";
}
