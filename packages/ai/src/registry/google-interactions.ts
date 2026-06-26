import type { ProviderDefinition } from "./types";

export const googleInteractionsProvider = {
	id: "google-interactions",
	name: "Google Gemini (Interactions API)",
} as const satisfies ProviderDefinition;
