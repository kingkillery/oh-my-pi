import { describe, expect, it } from "bun:test";
import type { Settings } from "@pk-nerdsaver-ai/pi-coding-agent/config/settings";
import type { AgentSession } from "@pk-nerdsaver-ai/pi-coding-agent/session/agent-session";
import {
	emptyFusionUsage,
	sumFusionUsage,
	type UsageSplit,
} from "@pk-nerdsaver-ai/pi-coding-agent/session/fusion-usage";
import type { UsageStatistics } from "@pk-nerdsaver-ai/pi-coding-agent/session/session-entries";
import type { SlashCommandRuntime } from "@pk-nerdsaver-ai/pi-coding-agent/slash-commands/types";
import { buildUsageReportText } from "../src/slash-commands/helpers/usage-report";

type UsageReportSettingKey = "fusion.enabled" | "fusion.mode" | "fusion.showSavings";

function makeSplit(overrides: {
	readonly frontier?: Partial<UsageStatistics>;
	readonly sidekick?: Partial<UsageStatistics>;
}): UsageSplit {
	const frontier = { ...emptyFusionUsage(), ...overrides.frontier };
	const sidekick = { ...emptyFusionUsage(), ...overrides.sidekick };
	return { total: sumFusionUsage(frontier, sidekick), frontier, sidekick };
}

function createRuntime(split: UsageSplit): SlashCommandRuntime {
	const settings = {
		get(key: UsageReportSettingKey) {
			switch (key) {
				case "fusion.enabled":
					return true;
				case "fusion.mode":
					return "escalate";
				case "fusion.showSavings":
					return true;
			}
		},
	} as unknown as Settings;
	const session = {
		settings,
		getFusionUsageSplit() {
			return split;
		},
	} as unknown as AgentSession;
	return {
		session,
		sessionManager: {} as SlashCommandRuntime["sessionManager"],
		settings,
		cwd: ".",
		output() {},
		refreshCommands() {},
		reloadPlugins() {
			return Promise.resolve();
		},
	};
}

describe("usage report Fusion token split", () => {
	it("reports delegated and main/frontier token counts without Fusion dollar savings", async () => {
		const split = makeSplit({
			frontier: { input: 100_000, output: 50_000, cacheWrite: 10_000, cost: 1.23 },
			sidekick: { input: 30_000, output: 15_000, cacheWrite: 5_000, cost: 0.04 },
		});

		const text = await buildUsageReportText(createRuntime(split));

		expect(text).toContain("Fusion (token split)");
		expect(text).toContain("Main/frontier tokens: 160,000");
		expect(text).toContain("Sidekick tokens: 50,000 (23.8% delegated; cache reads excluded)");
		expect(text).toContain("Total billable tokens: 210,000");
		const fusionSection = text.split("Fusion (token split)")[1] ?? "";
		expect(fusionSection).not.toContain("$");
		expect(fusionSection).not.toContain("Cost");
		expect(text).not.toContain("Est. savings");
		expect(text).not.toContain("Frontier cost");
	});
});
