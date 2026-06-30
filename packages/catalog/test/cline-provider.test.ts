import { describe, expect, test } from "bun:test";
import {
	DEFAULT_MODEL_PER_PROVIDER,
	PROVIDER_DESCRIPTORS,
} from "@pk-nerdsaver-ai/pi-catalog/provider-models/descriptors";
import {
	buildClineStaticSeed,
	clineModelManagerOptions,
} from "@pk-nerdsaver-ai/pi-catalog/provider-models/openai-compat";

describe("cline catalog provider", () => {
	test("descriptor wires the Cline gateway with an OAuth-backed default model", () => {
		const descriptor = PROVIDER_DESCRIPTORS.find(d => d.providerId === "cline");
		expect(descriptor).toBeDefined();
		expect(descriptor?.defaultModel).toBe("anthropic/claude-sonnet-4-6");
		// Catalog generation refreshes the OAuth credential for live discovery.
		expect(descriptor?.catalogDiscovery?.oauthProvider).toBe("cline");
		// The factory carries the provider identity through.
		expect(descriptor?.createModelManagerOptions({ apiKey: "k" }).providerId).toBe("cline");
		expect(DEFAULT_MODEL_PER_PROVIDER.cline).toBe("anthropic/claude-sonnet-4-6");
	});

	test("static seed targets the cline gateway base URL and includes the default model", () => {
		const seed = buildClineStaticSeed();
		expect(seed.map(model => model.id)).toContain("anthropic/claude-sonnet-4-6");
		for (const model of seed) {
			expect(model.provider).toBe("cline");
			expect(model.baseUrl).toBe("https://api.cline.bot/api/v1");
			expect(model.api).toBe("openai-completions");
		}
	});

	test("model manager seeds the picker statically and still exposes live discovery", () => {
		const options = clineModelManagerOptions({ apiKey: "k" });
		expect(options.providerId).toBe("cline");
		expect(options.staticModels?.length ?? 0).toBeGreaterThan(0);
		expect(typeof options.fetchDynamicModels).toBe("function");
	});
});
