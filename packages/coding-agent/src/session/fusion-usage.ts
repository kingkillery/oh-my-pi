import type { UsageStatistics } from "./session-entries";

/** Frontier-vs-sidekick token split for the Fusion meter. */
export interface UsageSplit {
	readonly total: UsageStatistics;
	readonly frontier: UsageStatistics;
	readonly sidekick: UsageStatistics;
}

export interface FusionTokenSplit {
	/** Sidekick/cheap-model share of billable tokens, from 0 to 100. */
	readonly share: number;
	/** Billable tokens handled by the sidekick/cheap model. */
	readonly sidekickTokens: number;
	/** Billable tokens handled by the main/frontier model. */
	readonly frontierTokens: number;
	readonly totalTokens: number;
}

export function emptyFusionUsage(): UsageStatistics {
	return { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, premiumRequests: 0, cost: 0 };
}

export function sumFusionUsage(frontier: UsageStatistics, sidekick: UsageStatistics): UsageStatistics {
	return {
		input: frontier.input + sidekick.input,
		output: frontier.output + sidekick.output,
		cacheRead: frontier.cacheRead + sidekick.cacheRead,
		cacheWrite: frontier.cacheWrite + sidekick.cacheWrite,
		premiumRequests: frontier.premiumRequests + sidekick.premiumRequests,
		cost: frontier.cost + sidekick.cost,
	};
}

export function billableFusionTokens(usage: Pick<UsageStatistics, "input" | "output" | "cacheWrite">): number {
	return usage.input + usage.output + usage.cacheWrite;
}

export function computeFusionTokenSplit(split: Pick<UsageSplit, "frontier" | "sidekick">): FusionTokenSplit {
	const sidekickTokens = billableFusionTokens(split.sidekick);
	const frontierTokens = billableFusionTokens(split.frontier);
	const totalTokens = frontierTokens + sidekickTokens;
	const share = totalTokens > 0 ? (sidekickTokens / totalTokens) * 100 : 0;
	return { share, sidekickTokens, frontierTokens, totalTokens };
}
