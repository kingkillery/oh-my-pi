/**
 * Built-in MOA (Mixture-of-Agents) presets.
 *
 * Each preset maps a friendly name to a list of read-only lane selectors plus
 * the active agent's model remains the tool-capable synthesizer/verifier.
 *
 * Selectors resolve through {@link resolveModelFromString} so users can mix
 * concrete `provider/id`, role aliases (`pi/slow`), and `pi/<role>` paths.
 */
export interface MoaPresetDef {
	laneSelectors: readonly string[];
}

export const MOA_PRESET_IDS = ["off", "balanced", "diverse", "code"] as const;
export type MoaPresetId = (typeof MOA_PRESET_IDS)[number];

export const MOA_PRESETS: Record<MoaPresetId, MoaPresetDef> = {
	off: {
		laneSelectors: [],
	},
	balanced: {
		laneSelectors: ["pi/smol", "pi/slow"],
	},
	diverse: {
		laneSelectors: ["pi/smol", "pi/slow", "anthropic/claude-sonnet-4-5", "openai/gpt-4o"],
	},
	code: {
		laneSelectors: ["pi/slow", "openai/gpt-5.3-codex"],
	},
};

export function isMoaPresetId(value: string): value is MoaPresetId {
	return (MOA_PRESET_IDS as readonly string[]).includes(value);
}

export function getMoaPreset(name: MoaPresetId | string): MoaPresetDef {
	if (isMoaPresetId(name)) return MOA_PRESETS[name];
	return MOA_PRESETS.off;
}
