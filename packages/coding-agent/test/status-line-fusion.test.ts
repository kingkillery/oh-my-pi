import { beforeAll, describe, expect, it } from "bun:test";
import { stripVTControlCharacters } from "node:util";
import { renderSegment } from "@pk-nerdsaver-ai/pi-coding-agent/modes/components/status-line/segments";
import type { SegmentContext } from "@pk-nerdsaver-ai/pi-coding-agent/modes/components/status-line/types";
import { initTheme } from "@pk-nerdsaver-ai/pi-coding-agent/modes/theme/theme";
import type { AgentSession } from "@pk-nerdsaver-ai/pi-coding-agent/session/agent-session";
import {
	emptyFusionUsage,
	sumFusionUsage,
	type UsageSplit,
} from "@pk-nerdsaver-ai/pi-coding-agent/session/fusion-usage";
import type { UsageStatistics } from "@pk-nerdsaver-ai/pi-coding-agent/session/session-entries";

type FusionModeSetting = "off" | "delegate" | "escalate";
type FusionSettingKey = "fusion.enabled" | "fusion.mode" | "fusion.sidekickRequestBudget" | "fusion.showSavings";

interface FusionCtxOptions {
	readonly enabled: boolean;
	readonly mode: FusionModeSetting;
	readonly budget?: number;
	readonly showSavings?: boolean;
	readonly split?: UsageSplit;
	readonly configured?: boolean;
}

beforeAll(async () => {
	await initTheme();
});

function makeSplit(overrides: {
	readonly frontier?: Partial<UsageStatistics>;
	readonly sidekick?: Partial<UsageStatistics>;
}): UsageSplit {
	const frontier = { ...emptyFusionUsage(), ...overrides.frontier };
	const sidekick = { ...emptyFusionUsage(), ...overrides.sidekick };
	return { total: sumFusionUsage(frontier, sidekick), frontier, sidekick };
}

function createCtx(options: FusionCtxOptions): SegmentContext {
	const session = {
		settings: {
			get(key: FusionSettingKey) {
				switch (key) {
					case "fusion.enabled":
						return options.enabled;
					case "fusion.mode":
						return options.mode;
					case "fusion.sidekickRequestBudget":
						return options.budget ?? 0;
					case "fusion.showSavings":
						return options.showSavings ?? true;
				}
			},
			isConfigured(key: FusionSettingKey) {
				return options.configured ?? (key === "fusion.enabled" || key === "fusion.mode");
			},
		},
		getFusionUsageSplit() {
			return options.split ?? makeSplit({});
		},
	} as unknown as AgentSession;
	return { session } as SegmentContext;
}

function plain(text: string): string {
	return stripVTControlCharacters(text);
}

describe("fusion status-line segments", () => {
	it("shows a muted off cue when fusion is explicitly disabled", () => {
		const rendered = renderSegment("fusion", createCtx({ enabled: false, mode: "escalate", configured: true }));
		expect(rendered.visible).toBe(true);
		expect(plain(rendered.content)).toContain("fusion off");
	});

	it("keeps default unconfigured fusion hidden to avoid status-line noise", () => {
		const rendered = renderSegment("fusion", createCtx({ enabled: false, mode: "escalate", configured: false }));
		expect(rendered.visible).toBe(false);
		expect(rendered.content).toBe("");
	});

	it("shows an active cue when fusion is enabled", () => {
		const rendered = renderSegment("fusion", createCtx({ enabled: true, mode: "escalate", budget: 12 }));
		expect(rendered.visible).toBe(true);
		expect(plain(rendered.content)).toContain("fusion on escalate");
		expect(plain(rendered.content)).toContain("cap 12");
	});

	it("renders token split instead of dollar savings", () => {
		const split = makeSplit({
			frontier: { input: 100_000, output: 50_000, cacheWrite: 10_000 },
			sidekick: { input: 30_000, output: 15_000, cacheWrite: 5_000 },
		});
		const rendered = renderSegment("fusion_savings", createCtx({ enabled: true, mode: "escalate", split }));
		const text = plain(rendered.content);
		expect(rendered.visible).toBe(true);
		expect(text).toContain("sk 24%");
		expect(text).toContain("50K");
		expect(text).toContain("main 160K");
		expect(text).not.toContain("$");
	});
});
