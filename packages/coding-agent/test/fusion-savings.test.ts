import { describe, expect, it } from "bun:test";
import {
	computeFusionTokenSplit,
	emptyFusionUsage,
	sumFusionUsage,
	type UsageSplit,
} from "@pk-nerdsaver-ai/pi-coding-agent/session/fusion-usage";
import type { UsageStatistics } from "@pk-nerdsaver-ai/pi-coding-agent/session/session-entries";

function makeSplit(overrides: {
	frontier?: Partial<UsageStatistics>;
	sidekick?: Partial<UsageStatistics>;
}): UsageSplit {
	const frontier = { ...emptyFusionUsage(), ...overrides.frontier };
	const sidekick = { ...emptyFusionUsage(), ...overrides.sidekick };
	return { total: sumFusionUsage(frontier, sidekick), frontier, sidekick };
}

describe("fusion token split", () => {
	it("zero sidekick share when no sidekick work done", () => {
		const split = makeSplit({
			frontier: { input: 100_000, output: 50_000, cacheWrite: 10_000 },
		});
		const result = computeFusionTokenSplit(split);
		expect(result.share).toBe(0);
		expect(result.sidekickTokens).toBe(0);
		expect(result.frontierTokens).toBe(160_000);
		expect(result.totalTokens).toBe(160_000);
	});

	it("returns sidekick share and raw token counts for typical session", () => {
		// Given: 160K billable main-model tokens and 50K sidekick/cheap-model tokens.
		const split = makeSplit({
			frontier: { input: 100_000, output: 50_000, cacheWrite: 10_000 },
			sidekick: { input: 30_000, output: 15_000, cacheWrite: 5_000 },
		});
		// When: Fusion token split is computed.
		const result = computeFusionTokenSplit(split);
		// Then: 50K / (160K + 50K) = 23.8% of billable tokens left the main model.
		expect(result.share).toBeCloseTo(23.8, 1);
		expect(result.sidekickTokens).toBe(50_000);
		expect(result.frontierTokens).toBe(160_000);
		expect(result.totalTokens).toBe(210_000);
	});

	it("cacheRead tokens are not counted in billable", () => {
		const split = makeSplit({
			frontier: { input: 50_000, output: 25_000, cacheRead: 100_000, cacheWrite: 5_000 },
			sidekick: { input: 10_000, output: 5_000, cacheRead: 50_000, cacheWrite: 1_000 },
		});
		const result = computeFusionTokenSplit(split);
		// Frontier billable: 80K; sidekick billable: 16K; share = 16K / 96K.
		expect(result.share).toBeCloseTo(16.7, 1);
		expect(result.sidekickTokens).toBe(16_000);
		expect(result.frontierTokens).toBe(80_000);
		expect(result.totalTokens).toBe(96_000);
	});

	it("heavy delegation reports high sidekick share", () => {
		const split = makeSplit({
			frontier: { input: 10_000, output: 5_000, cacheWrite: 1_000 },
			sidekick: { input: 30_000, output: 10_000, cacheWrite: 2_000 },
		});
		const result = computeFusionTokenSplit(split);
		// Frontier billable: 16K; sidekick billable: 42K; share = 42K / 58K.
		expect(result.share).toBeCloseTo(72.4, 1);
		expect(result.sidekickTokens).toBe(42_000);
		expect(result.frontierTokens).toBe(16_000);
		expect(result.totalTokens).toBe(58_000);
	});

	it("zero total tokens produces 0 share", () => {
		const split = makeSplit({});
		const result = computeFusionTokenSplit(split);
		expect(result.share).toBe(0);
		expect(result.sidekickTokens).toBe(0);
		expect(result.frontierTokens).toBe(0);
		expect(result.totalTokens).toBe(0);
	});

	it("sidekick-only work is 100% share with zero main-model tokens", () => {
		const split = makeSplit({
			sidekick: { input: 50_000, output: 25_000, cacheWrite: 5_000 },
		});
		const result = computeFusionTokenSplit(split);
		expect(result.share).toBe(100);
		expect(result.sidekickTokens).toBe(80_000);
		expect(result.frontierTokens).toBe(0);
		expect(result.totalTokens).toBe(80_000);
	});

	it("frontier-only work is 0% share", () => {
		const split = makeSplit({
			frontier: { input: 200_000, output: 100_000, cacheWrite: 20_000 },
		});
		const result = computeFusionTokenSplit(split);
		expect(result.share).toBe(0);
		expect(result.sidekickTokens).toBe(0);
		expect(result.frontierTokens).toBe(320_000);
	});
});
