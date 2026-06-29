import { describe, expect, it } from "bun:test";
import type { Context, Model, SimpleStreamOptions } from "@pk-nerdsaver-ai/pi-ai";
import { createMockModel } from "@pk-nerdsaver-ai/pi-ai/providers/mock";
import { Agent } from "../src/agent";
import { createMoaStreamFn } from "../src/moa";

function context(): Context {
	return {
		systemPrompt: ["System"],
		messages: [{ role: "user", content: "Solve it", timestamp: 1 }],
		tools: [
			{
				name: "read",
				description: "Read files",
				parameters: { type: "object", properties: {}, additionalProperties: false },
			},
		],
	};
}

describe("MOA stream composition", () => {
	it("runs references without tools before the aggregator sees their private advice", async () => {
		const reference = createMockModel({
			id: "reference-a",
			responses: [{ content: ["Check edge cases."] }],
		});
		const aggregator = createMockModel({
			id: "aggregator",
			handler: ctx => {
				const advice = ctx.messages.at(-1);
				return { content: [`final:${typeof advice?.content === "string" ? advice.content : "missing"}`] };
			},
		});
		const moaStream = createMoaStreamFn(
			(model: Model, ctx: Context, options?: SimpleStreamOptions) => {
				if (model.id === reference.model.id) return reference.stream(reference.model, ctx, options);
				return aggregator.stream(aggregator.model, ctx, options);
			},
			{ lanes: [{ model: reference.model, label: "ref-a" }] },
		);
		const result = await (await moaStream(aggregator.model, context())).result();

		expect(reference.calls[0]?.context.tools).toBeUndefined();
		expect(reference.calls[0]?.options?.toolChoice).toBe("none");
		expect(aggregator.calls[0]?.context.tools?.map(tool => tool.name)).toEqual(["read"]);
		expect(result.content).toEqual([
			{
				type: "text",
				text: expect.stringContaining("### ref-a\nCheck edge cases."),
			},
		]);
	});

	it("passes through directly when no reference models are configured", async () => {
		const model = createMockModel({ responses: [{ content: ["direct"] }] });
		const moaStream = createMoaStreamFn(model.stream, { lanes: [] });
		const result = await (await moaStream(model.model, context())).result();

		expect(model.calls.length).toBe(1);
		expect(result.content).toEqual([{ type: "text", text: "direct" }]);
	});

	it("Agent option turns the configured model into the aggregator", async () => {
		const reference = createMockModel({ id: "reference", responses: [{ content: ["Prefer concise output."] }] });
		const aggregator = createMockModel({ id: "aggregator", responses: [{ content: ["aggregated"] }] });
		const agent = new Agent({
			initialState: { model: aggregator.model, messages: [] },
			streamFn: (model: Model, ctx: Context, options?: SimpleStreamOptions) => {
				if (model.id === reference.model.id) return reference.stream(reference.model, ctx, options);
				return aggregator.stream(aggregator.model, ctx, options);
			},
			moa: { lanes: [{ model: reference.model }] },
		});

		await agent.prompt("Summarize");

		expect(reference.calls.length).toBe(1);
		expect(aggregator.calls[0]?.context.messages.at(-1)?.role).toBe("developer");
		expect(agent.state.messages.at(-1)).toMatchObject({ role: "assistant", model: "aggregator" });
	});
});
