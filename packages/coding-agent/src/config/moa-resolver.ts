/**
 * Resolve the configured MOA preset/lanes into a {@link MoaConfig} ready for the
 * Agent core. Filters selectors that do not resolve against the live model
 * registry, logging a warning per skipped entry instead of failing the session.
 */

import type { MoaConfig, MoaReadOnlyLane } from "@pk-nerdsaver-ai/pi-agent-core";
import type { Model } from "@pk-nerdsaver-ai/pi-ai";
import { logger } from "@pk-nerdsaver-ai/pi-utils";
import { getMoaPreset, type MoaPresetId } from "./moa-presets";
import { resolveModelFromString } from "./model-resolver";

export interface ResolveMoaConfigInput {
	presetId: MoaPresetId | string;
	overrideSelectors: readonly string[] | undefined;
	availableModels: readonly Model[];
	maxLanes: number;
}

export interface ResolveMoaConfigResult {
	readonly moa: MoaConfig | undefined;
	readonly skipped: readonly { selector: string; reason: string }[];
}

function isOverrideSelectors(
	presetId: MoaPresetId | string,
	overrideSelectors: readonly string[] | undefined,
): boolean {
	if (!overrideSelectors || overrideSelectors.length === 0) return false;
	return presetId === "custom" || overrideSelectors.length > 0;
}

function resolveLane(selector: string, availableModels: readonly Model[]): { lane?: MoaReadOnlyLane; reason?: string } {
	const trimmed = selector.trim();
	if (!trimmed) return { reason: "empty selector" };
	const model = resolveModelFromString(trimmed, availableModels as Model[]);
	if (!model) return { reason: `no available model matched "${trimmed}"` };
	return { lane: { model, label: `${model.provider}/${model.id}` } };
}

export function resolveMoaConfig(input: ResolveMoaConfigInput): ResolveMoaConfigResult {
	const { presetId, overrideSelectors, availableModels, maxLanes } = input;

	const useOverride = isOverrideSelectors(presetId, overrideSelectors);
	const preset = useOverride ? undefined : getMoaPreset(presetId);
	const selectors = useOverride ? (overrideSelectors ?? []) : (preset?.laneSelectors ?? []);

	const lanes: MoaReadOnlyLane[] = [];
	const skipped: { selector: string; reason: string }[] = [];

	for (const selector of selectors) {
		if (lanes.length >= maxLanes) {
			skipped.push({ selector, reason: `exceeded maxLanes (${maxLanes})` });
			continue;
		}
		const result = resolveLane(selector, availableModels);
		if (result.lane) {
			lanes.push(result.lane);
		} else {
			const reason = result.reason ?? "unknown";
			skipped.push({ selector, reason });
			logger.warn("moa: lane skipped", { selector, reason });
		}
	}

	if (lanes.length === 0) {
		return { moa: undefined, skipped };
	}

	return {
		moa: { lanes },
		skipped,
	};
}
