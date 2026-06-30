import { describe, expect, it } from "bun:test";
import { agentLoop } from "@pk-nerdsaver-ai/pi-agent-core/agent-loop";
import type {
	AgentContext,
	AgentEvent,
	AgentLoopConfig,
	AgentMessage,
	AgentTool,
} from "@pk-nerdsaver-ai/pi-agent-core/types";
import type { Message } from "@pk-nerdsaver-ai/pi-ai";
import { createMockModel, type MockResponse } from "@pk-nerdsaver-ai/pi-ai/providers/mock";
import { type } from "arktype";
import { createUserMessage } from "./helpers";

function identityConverter(messages: AgentMessage[]): Message[] {
	return messages.filter(m => m.role === "user" || m.role === "assistant" || m.role === "toolResult") as Message[];
}

const noopSchema = type({});
const noopTool: AgentTool<typeof noopSchema, Record<string, never>> = {
	name: "noop",
	label: "Noop",
	description: "Noop tool",
	parameters: noopSchema,
	async execute() {
		return { content: [{ type: "text", text: "ok" }], details: {} };
	},
};

// A model that never stops asking for the tool — without a cap this loops forever.
function* toolForever(): Generator<MockResponse> {
	let i = 0;
	while (true) {
		i++;
		yield { content: [{ type: "toolCall", id: `t-${i}`, name: "noop", arguments: {} }] };
	}
}

describe("agentLoop maxModelRequestsPerRun (Fusion sidekick budget)", () => {
	it("halts after exactly N model requests when the per-run cap is set", async () => {
		const context: AgentContext = { systemPrompt: [""], messages: [], tools: [noopTool] };
		const mock = createMockModel({ responses: toolForever() });
		const config: AgentLoopConfig = {
			model: mock.model,
			convertToLlm: identityConverter,
			maxModelRequestsPerRun: 2,
		};

		const events: AgentEvent[] = [];
		const stream = agentLoop([createUserMessage("go")], context, config, undefined, mock.stream);
		for await (const event of stream) {
			events.push(event);
		}
		await stream.result();

		// The cap stops the otherwise-infinite tool loop after exactly 2 requests,
		// and ends gracefully (this is the path that bounds reused IRC-woken turns).
		expect(mock.calls).toHaveLength(2);
		expect(events.map(e => e.type)).toContain("agent_end");
	});

	it("halts after a single request when the cap is 1", async () => {
		const context: AgentContext = { systemPrompt: [""], messages: [], tools: [noopTool] };
		const mock = createMockModel({ responses: toolForever() });
		const config: AgentLoopConfig = {
			model: mock.model,
			convertToLlm: identityConverter,
			maxModelRequestsPerRun: 1,
		};

		await agentLoop([createUserMessage("go")], context, config, undefined, mock.stream).result();
		expect(mock.calls).toHaveLength(1);
	});

	it("does not interfere when the cap is unset", async () => {
		const context: AgentContext = { systemPrompt: [""], messages: [], tools: [noopTool] };
		// Finite: one tool call, then a normal completion.
		const mock = createMockModel({
			responses: [
				{ content: [{ type: "toolCall", id: "t-1", name: "noop", arguments: {} }] },
				{ content: ["done"] },
			],
		});
		const config: AgentLoopConfig = { model: mock.model, convertToLlm: identityConverter };

		const messages = await agentLoop([createUserMessage("go")], context, config, undefined, mock.stream).result();
		// Both requests run; the run finishes on the model's own stop.
		expect(mock.calls).toHaveLength(2);
		expect(messages.at(-1)?.role).toBe("assistant");
	});
});

describe("agentLoop maxModelRequestsPerRun per-prompt reset", () => {
	// Regression for #5 (Fusion sidekick budget compounding): the cap is
	// enforced at the top of each `runLoop` iteration and resets across
	// `session.prompt()` calls. Callers driving multiple prompts in one
	// assignment (e.g. the executor's yield-reminder loop) MUST consult the
	// configured cap alongside their own counter — otherwise the budget
	// compounds by N reminders.
	it("resets the counter across separate prompt() invocations on the same session", async () => {
		const context: AgentContext = { systemPrompt: [""], messages: [], tools: [noopTool] };
		const mock = createMockModel({ responses: toolForever() });
		const config: AgentLoopConfig = {
			model: mock.model,
			convertToLlm: identityConverter,
			maxModelRequestsPerRun: 2,
		};

		// First prompt: hits the cap after 2 requests, ends cleanly.
		await agentLoop([createUserMessage("first")], context, config, undefined, mock.stream).result();
		expect(mock.calls).toHaveLength(2);

		// Second prompt on a freshly-extended context also runs to its own cap.
		// If the cap were session-cumulative (incorrect), the second prompt
		// would be allowed zero requests and the test would fail with 2 total.
		const context2: AgentContext = {
			systemPrompt: [""],
			messages: [],
			tools: [noopTool],
		};
		await agentLoop([createUserMessage("second")], context2, config, undefined, mock.stream).result();
		expect(mock.calls).toHaveLength(4);
	});
});
