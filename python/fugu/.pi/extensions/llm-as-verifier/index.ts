import { complete, StringEnum } from "@mariozechner/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { withFileMutationQueue } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const TOOL_NAME = "llm_as_verifier";
const SKILL_DIR = [".agents", "skills", "llm-as-verifier"];
const SCRIPT_PATH = [...SKILL_DIR, "scripts", "lav_runner.py"];
const EXAMPLE_PATH = [...SKILL_DIR, "examples", "code-patch-selection.json"];
const ENSEMBLE_EXAMPLE_PATH = [...SKILL_DIR, "examples", "weighted-ensemble-selection.json"];
const DEFAULT_GROUND_TRUTH_NOTE =
	"Prefer concrete evidence, observed outputs, tests, and explicit artifacts over polished narration or self-reported success.";
const GRANULARITY = 20;
const LETTERS = Array.from({ length: GRANULARITY }, (_value, index) => String.fromCharCode(65 + index));
const VALID_TOKENS = Object.fromEntries(
	LETTERS.flatMap((letter, index) => [
		[letter, GRANULARITY - index],
		[letter.toLowerCase(), GRANULARITY - index],
	]),
) as Record<string, number>;
const DEFAULT_ENSEMBLE_MODEL_SPECS = [
	"kimi:kimi-for-coding",
	"minimax.io:minimax-m3",
	"openai:gpt-5.5",
] as const;

const stripLeadingAt = (value: string): string => (value.startsWith("@") ? value.slice(1) : value);
const resolveUserPath = (cwd: string, value: string): string => path.resolve(cwd, stripLeadingAt(value));
const normalizeKey = (value: string): string => value.toLowerCase().replace(/[^a-z0-9]+/g, "");

const truncate = (text: string, maxChars: number): { text: string; truncated: boolean } => {
	if (text.length <= maxChars) return { text, truncated: false };
	return { text: `${text.slice(0, Math.max(0, maxChars - 18))}\n... (truncated)`, truncated: true };
};

type CandidateInput = {
	id: string;
	path?: string;
	content?: string;
	summary?: string;
	evidencePaths?: string[];
	evidenceText?: string;
};

type CriterionInput = {
	id?: string;
	name: string;
	description: string;
};

type ModelWeightInput = {
	model: string;
	weight: number;
};

type Backend = "gemini-python" | "zai-coding-plan" | "pi-model-ensemble";

type EvidenceBlock = {
	label: string;
	content: string;
	source: string;
	truncated: boolean;
};

type NormalizedCandidate = {
	id: string;
	summary: string;
	content: string;
	source: string;
	truncated: boolean;
	evidence: Array<{ label: string; content: string }>;
	evidenceSources: EvidenceBlock[];
};

type ResolvedPiModel = {
	spec: string;
	provider: string;
	id: string;
	display: string;
	model: any;
};

type ResolvedModelWeight = {
	model: string;
	weight: number;
};

type CompareRepetition = {
	rep: number;
	order: "original" | "swapped";
	model: string;
	weight: number;
	score_a: number;
	score_b: number;
	canonical_score_a: number;
	canonical_score_b: number;
	source_a: "text" | "fallback" | "mock";
	source_b: "text" | "fallback" | "mock";
	response_excerpt: string;
};

type AuditRepetition = {
	rep: number;
	model: string;
	weight: number;
	score: number;
	source: "text" | "fallback" | "mock";
	response_excerpt: string;
};

type VerifierConfig = {
	mode: "compare" | "audit";
	backend: Backend;
	task: string;
	context: string;
	groundTruthNote: string;
	criteria: Array<{ id: string; name: string; description: string }>;
	candidates: NormalizedCandidate[];
	nVerifications: number;
	granularity: number;
	mock: boolean;
	models: ResolvedPiModel[];
	modelWeights: ResolvedModelWeight[];
};

const MODEL_ALIASES: Record<string, { provider: string; id: string }> = {
	[normalizeKey("gpt-5.4")]: { provider: "openai", id: "gpt-5.4" },
	[normalizeKey("openai:gpt-5.4")]: { provider: "openai", id: "gpt-5.4" },
	[normalizeKey("gpt-5.5")]: { provider: "openai", id: "gpt-5.5" },
	[normalizeKey("openai:gpt-5.5")]: { provider: "openai", id: "gpt-5.5" },
	[normalizeKey("codex:gpt-5.5")]: { provider: "openai", id: "gpt-5.5" },
	[normalizeKey("gpt-5-codex")]: { provider: "openai", id: "gpt-5-codex" },
	[normalizeKey("openai:gpt-5-codex")]: { provider: "openai", id: "gpt-5-codex" },
	[normalizeKey("kimi-for-coding")]: { provider: "kimi", id: "kimi-for-coding" },
	[normalizeKey("kimi:kimi-for-coding")]: { provider: "kimi", id: "kimi-for-coding" },
	[normalizeKey("kimi-k2")]: { provider: "kimi", id: "kimi-for-coding" },
	[normalizeKey("kimi:kimi-k2")]: { provider: "kimi", id: "kimi-for-coding" },
	[normalizeKey("gemini")]: { provider: "google", id: "gemini-2.5-flash" },
	[normalizeKey("gemini-2.5-flash")]: { provider: "google", id: "gemini-2.5-flash" },
	[normalizeKey("google:gemini-2.5-flash")]: { provider: "google", id: "gemini-2.5-flash" },
	[normalizeKey("minimax-m2.7-highspeed")]: { provider: "minimax", id: "MiniMax-M2.7-highspeed" },
	[normalizeKey("minimax:MiniMax-M2.7-highspeed")]: { provider: "minimax", id: "MiniMax-M2.7-highspeed" },
	[normalizeKey("minimax-m3")]: { provider: "minimax.io", id: "minimax-m3" },
	[normalizeKey("minimax.io:minimax-m3")]: { provider: "minimax.io", id: "minimax-m3" },
	[normalizeKey("minimax:minimax-m3")]: { provider: "minimax.io", id: "minimax-m3" },
	[normalizeKey("glm-5.1")]: { provider: "zai", id: "glm-5.1" },
	[normalizeKey("zai:glm-5.1")]: { provider: "zai", id: "glm-5.1" },
};

const SUCCESS_HINTS = [
	"pass",
	"passed",
	"success",
	"succeeded",
	"fixed",
	"verified",
	"green",
	"expected output",
	"report generated",
];
const ERROR_HINTS = [
	"error",
	"failed",
	"failure",
	"traceback",
	"exception",
	"command not found",
	"no such file",
	"segmentation fault",
	"not created",
];
const PARTIAL_HINTS = ["partial", "some tests", "not verified", "uncertain", "partial progress"];

const clamp = (value: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, value));
const normalizedFromRaw = (rawValue: number): number => (rawValue - 1) / (GRANULARITY - 1);
const rawFromNormalized = (score: number): number => 1 + clamp(score, 0, 1) * (GRANULARITY - 1);
const letterFromNormalized = (score: number): string => LETTERS[clamp(Math.round(GRANULARITY - rawFromNormalized(score)), 0, GRANULARITY - 1)];
const average = (values: number[]): number => (values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0);

const weightedMean = <T>(items: T[], getValue: (item: T) => number, getWeight: (item: T) => number): number => {
	const totalWeight = items.reduce((sum, item) => sum + Math.max(0, getWeight(item)), 0);
	if (totalWeight <= 0) return items.length ? average(items.map(getValue)) : 0;
	return items.reduce((sum, item) => sum + getValue(item) * Math.max(0, getWeight(item)), 0) / totalWeight;
};

const weightedStdDev = <T>(items: T[], getValue: (item: T) => number, getWeight: (item: T) => number, mean?: number): number => {
	if (!items.length) return 0;
	const resolvedMean = mean ?? weightedMean(items, getValue, getWeight);
	const totalWeight = items.reduce((sum, item) => sum + Math.max(0, getWeight(item)), 0);
	if (totalWeight <= 0) {
		const simpleMean = average(items.map(getValue));
		const variance = average(items.map((item) => (getValue(item) - simpleMean) ** 2));
		return Math.sqrt(variance);
	}
	const variance =
		items.reduce((sum, item) => sum + Math.max(0, getWeight(item)) * (getValue(item) - resolvedMean) ** 2, 0) / totalWeight;
	return Math.sqrt(variance);
};

const heuristicScore = (text: string): number => {
	const lowered = text.toLowerCase();
	const success = SUCCESS_HINTS.reduce((sum, token) => sum + lowered.split(token).length - 1, 0);
	const errors = ERROR_HINTS.reduce((sum, token) => sum + lowered.split(token).length - 1, 0);
	const partial = PARTIAL_HINTS.reduce((sum, token) => sum + lowered.split(token).length - 1, 0);
	return clamp(0.55 + 0.06 * success - 0.08 * errors - 0.03 * partial, 0.05, 0.95);
};

const extractTextSource = async (
	cwd: string,
	label: string,
	input: { path?: string; content?: string },
	maxChars: number,
): Promise<{ text: string; source: string; truncated: boolean }> => {
	if (input.path) {
		const absolutePath = resolveUserPath(cwd, input.path);
		const content = await readFile(absolutePath, "utf8");
		const clipped = truncate(content, maxChars);
		return { text: clipped.text, source: absolutePath, truncated: clipped.truncated };
	}

	if (typeof input.content === "string" && input.content.trim()) {
		const clipped = truncate(input.content.trim(), maxChars);
		return { text: clipped.text, source: `${label}:inline`, truncated: clipped.truncated };
	}

	throw new Error(`${label} requires either path or content.`);
};

const readEvidenceBlocks = async (cwd: string, paths: string[] | undefined, maxChars: number): Promise<EvidenceBlock[]> => {
	if (!paths?.length) return [];
	const blocks: EvidenceBlock[] = [];
	for (const rawPath of paths) {
		const absolutePath = resolveUserPath(cwd, rawPath);
		const content = await readFile(absolutePath, "utf8");
		const clipped = truncate(content, maxChars);
		blocks.push({
			label: path.basename(absolutePath),
			content: clipped.text,
			source: absolutePath,
			truncated: clipped.truncated,
		});
	}
	return blocks;
};

const slugify = (value: string): string =>
	value
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "-")
		.replace(/^-+|-+$/g, "") || "criterion";

async function runPython(pi: ExtensionAPI, scriptPath: string, args: string[], signal?: AbortSignal) {
	const attempts: Array<{ command: string; args: string[] }> = [
		{ command: "python", args: [scriptPath, ...args] },
		{ command: "py", args: ["-3", scriptPath, ...args] },
	];

	let lastError = "";
	for (const attempt of attempts) {
		const result = await pi.exec(attempt.command, attempt.args, { signal, timeout: 600000 });
		if (result.code === 0) return result;
		lastError = [result.stdout, result.stderr].filter(Boolean).join("\n").trim();
	}

	throw new Error(lastError || "Failed to execute Python runner. Ensure python or py -3 is available.");
}

const formatEvidenceBlocks = (evidence: Array<{ label: string; content: string }>): string => {
	if (!evidence.length) return "";
	return ["Evidence:", ...evidence.map((item) => `- ${item.label}:\n${item.content}`)].join("\n");
};

const formatCandidate = (candidate: NormalizedCandidate, label: string): string => {
	const parts = [`## ${label} — ${candidate.id}`];
	if (candidate.summary) parts.push(`Summary:\n${candidate.summary}`);
	parts.push(`Content:\n${candidate.content}`);
	const evidenceBlock = formatEvidenceBlocks(candidate.evidence);
	if (evidenceBlock) parts.push(evidenceBlock);
	return parts.join("\n\n");
};

const createComparePrompt = (
	config: VerifierConfig,
	candidateA: NormalizedCandidate,
	candidateB: NormalizedCandidate,
	criterion: { id: string; name: string; description: string },
): string => {
	const parts = [
		"You are an expert verifier choosing between two candidate solutions.",
		config.groundTruthNote,
		`Task:\n${config.task}`,
	];
	if (config.context) parts.push(`Shared context:\n${config.context}`);
	parts.push(
		formatCandidate(candidateA, "Candidate A"),
		formatCandidate(candidateB, "Candidate B"),
		`Criterion: ${criterion.name}\n${criterion.description}`,
		[
			"Rate each candidate on a 20-point scale using letters A through T:",
			"  A = clearly and completely best / strongest",
			"  B-D = very strong with only minor concerns",
			"  E-G = above average, mostly correct with some issues",
			"  H-J = mixed, leans positive",
			"  K-M = mixed, leans negative",
			"  N-P = below average, significant issues remain",
			"  Q-S = weak with only partial value",
			"  T = clearly and completely weakest / failed",
		].join("\n"),
		"Evaluate BOTH candidates only on the named criterion. Ignore unrelated aspects.",
		EVIDENCE_INSTRUCTION,
		"<evidence_A>1. ... 2. ... 3. ...</evidence_A>",
		"<evidence_B>1. ... 2. ... 3. ...</evidence_B>",
		"Then output final scores exactly in this format:",
		"<score_A>LETTER_A_TO_T</score_A>",
		"<score_B>LETTER_A_TO_T</score_B>",
	);
	return parts.join("\n\n");
};

const createAuditPrompt = (
	config: VerifierConfig,
	candidate: NormalizedCandidate,
	criterion: { id: string; name: string; description: string },
): string => {
	const parts = [
		"You are an expert verifier scoring a single candidate solution.",
		config.groundTruthNote,
		`Task:\n${config.task}`,
	];
	if (config.context) parts.push(`Shared context:\n${config.context}`);
	parts.push(
		formatCandidate(candidate, "Candidate"),
		`Criterion: ${criterion.name}\n${criterion.description}`,
		[
			"Rate the candidate on a 20-point scale using letters A through T:",
			"  A = clearly and completely best / strongest",
			"  B-D = very strong with only minor concerns",
			"  E-G = above average, mostly correct with some issues",
			"  H-J = mixed, leans positive",
			"  K-M = mixed, leans negative",
			"  N-P = below average, significant issues remain",
			"  Q-S = weak with only partial value",
			"  T = clearly and completely weakest / failed",
		].join("\n"),
		"Evaluate the candidate only on the named criterion.",
		EVIDENCE_INSTRUCTION,
		"<evidence>1. ... 2. ... 3. ...</evidence>",
		"Then output the final score exactly in this format:",
		"<score>LETTER_A_TO_T</score>",
	);
	return parts.join("\n\n");
};

const extractTextFromAssistantMessage = (message: any): string => {
	if (!Array.isArray(message?.content)) return "";
	return message.content
		.filter((item: any) => item?.type === "text" && typeof item.text === "string")
		.map((item: any) => item.text)
		.join("\n")
		.trim();
};

const extractTaggedScore = (text: string, tag: string): { score: number; source: "text" | "fallback" | "mock" } => {
	const tagName = tag.replace(/[<>]/g, "");
	const match = text.match(new RegExp(`<${tagName}>\\s*([A-Ta-t])\\s*</${tagName}>`));
	if (!match) return { score: 0.5, source: text.includes("Mock verifier response") ? "mock" : "fallback" };
	const raw = VALID_TOKENS[match[1]];
	if (!raw) return { score: 0.5, source: text.includes("Mock verifier response") ? "mock" : "fallback" };
	return { score: normalizedFromRaw(raw), source: text.includes("Mock verifier response") ? "mock" : "text" };
};

const buildMockCompareText = (prompt: string, candidateA: NormalizedCandidate, candidateB: NormalizedCandidate): string => {
	const scoreA = heuristicScore(`${candidateA.summary}\n${candidateA.content}`);
	const scoreB = heuristicScore(`${candidateB.summary}\n${candidateB.content}`);
	return [
		"Mock verifier response.",
		`Prompt excerpt: ${truncate(prompt, 120).text}`,
		`<score_A>${letterFromNormalized(scoreA)}</score_A>`,
		`<score_B>${letterFromNormalized(scoreB)}</score_B>`,
	].join("\n");
};

const buildMockAuditText = (prompt: string, candidate: NormalizedCandidate): string => {
	const score = heuristicScore(`${candidate.summary}\n${candidate.content}`);
	return [
		"Mock verifier response.",
		`Prompt excerpt: ${truncate(prompt, 120).text}`,
		`<score>${letterFromNormalized(score)}</score>`,
	].join("\n");
};

const resolveModelAlias = (spec: string): { provider: string; id: string } | undefined => {
	return MODEL_ALIASES[normalizeKey(spec)];
};

const resolveVerifierModel = (ctx: ExtensionContext, spec: string): ResolvedPiModel => {
	const alias = resolveModelAlias(spec);
	if (alias) {
		const model = ctx.modelRegistry.find(alias.provider, alias.id);
		if (!model) {
			throw new Error(`Configured alias '${spec}' resolved to ${alias.provider}:${alias.id}, but that model was not found in Pi's model registry.`);
		}
		return {
			spec,
			provider: alias.provider,
			id: alias.id,
			display: `${alias.provider}:${alias.id}`,
			model,
		};
	}

	const colonIndex = spec.indexOf(":");
	if (colonIndex > 0) {
		const provider = spec.slice(0, colonIndex).trim();
		const id = spec.slice(colonIndex + 1).trim();
		const model = ctx.modelRegistry.find(provider, id);
		if (!model) {
			throw new Error(`Model not found: ${provider}:${id}`);
		}
		return { spec, provider, id, display: `${provider}:${id}`, model };
	}

	const normalizedSpec = normalizeKey(spec);
	const matches = ctx.modelRegistry.getAll().filter((model: any) => {
		const keys = [
			normalizeKey(model.id ?? ""),
			normalizeKey(model.name ?? ""),
			normalizeKey(`${model.provider}:${model.id}`),
			normalizeKey(`${model.provider}/${model.id}`),
		];
		return keys.includes(normalizedSpec);
	});

	if (!matches.length) {
		throw new Error(`Could not resolve model spec '${spec}'. Use provider:id form like openai:gpt-5.4.`);
	}

	const preferredProviders = ["openai", "openai-codex", "kimi", "minimax.io", "minimax", "google", "zai", "github-copilot"];
	matches.sort((left: any, right: any) => {
		const leftRank = preferredProviders.indexOf(left.provider);
		const rightRank = preferredProviders.indexOf(right.provider);
		return (leftRank === -1 ? 999 : leftRank) - (rightRank === -1 ? 999 : rightRank);
	});

	const winner = matches[0];
	return {
		spec,
		provider: winner.provider,
		id: winner.id,
		display: `${winner.provider}:${winner.id}`,
		model: winner,
	};
};

const resolveVerifierModels = (ctx: ExtensionContext, specs: string[]): ResolvedPiModel[] => {
	if (!specs.length) {
		throw new Error("At least one verifier model must be configured.");
	}
	return specs.map((spec) => resolveVerifierModel(ctx, spec));
};

const resolveModelWeights = (
	resolvedModels: ResolvedPiModel[],
	weightInputs: ModelWeightInput[] | undefined,
): ResolvedModelWeight[] => {
	const defaults = new Map(resolvedModels.map((model) => [model.display, 1]));
	for (const entry of weightInputs ?? []) {
		const matched = resolvedModels.find(
			(model) => model.display === entry.model || model.spec === entry.model || normalizeKey(model.display) === normalizeKey(entry.model),
		);
		if (!matched) {
			continue;
		}
		defaults.set(matched.display, Math.max(0, entry.weight));
	}
	return resolvedModels.map((model) => ({ model: model.display, weight: defaults.get(model.display) ?? 1 }));
};

const getWeightForModel = (weights: ResolvedModelWeight[], modelDisplay: string): number => {
	return weights.find((entry) => entry.model === modelDisplay)?.weight ?? 1;
};

const selectModelForAttempt = (models: ResolvedPiModel[], repIndex: number): ResolvedPiModel => {
	return models[repIndex % models.length];
};

const chooseWinner = (scoreA: number, scoreB: number, tieThreshold = 0.05): "candidate_a" | "candidate_b" | "tie" => {
	if (Math.abs(scoreA - scoreB) < tieThreshold) return "tie";
	return scoreA > scoreB ? "candidate_a" : "candidate_b";
};

const EVIDENCE_INSTRUCTION =
	"Before assigning any score, list exactly 3 evidence observations. Each observation must quote or paraphrase a concrete fact from the candidate, evidence, logs, tests, or task requirements. Do not count style, fluency, or confidence as evidence unless the criterion is explicitly about style. After the 3 observations, output the final score tag exactly as requested.";

const buildCompareBreakdown = (repetitions: CompareRepetition[]) => {
	const scoreA = weightedMean(repetitions, (item) => item.canonical_score_a, (item) => item.weight);
	const scoreB = weightedMean(repetitions, (item) => item.canonical_score_b, (item) => item.weight);
	const meanDiff = weightedMean(
		repetitions,
		(item) => item.canonical_score_a - item.canonical_score_b,
		(item) => item.weight,
	);
	const disagreement = clamp(
		weightedStdDev(
			repetitions,
			(item) => item.canonical_score_a - item.canonical_score_b,
			(item) => item.weight,
			meanDiff,
		),
		0,
		1,
	);
	const confidence = clamp(Math.abs(meanDiff) * (1 - disagreement), 0, 1);

	let swapDiffSum = 0;
	let swapPairCount = 0;
	for (let index = 0; index + 1 < repetitions.length; index += 2) {
		const left = repetitions[index];
		const right = repetitions[index + 1];
		if (left.order === right.order) continue;
		const leftMargin = left.canonical_score_a - left.canonical_score_b;
		const rightMargin = right.canonical_score_a - right.canonical_score_b;
		swapDiffSum += Math.abs(leftMargin - rightMargin);
		swapPairCount += 1;
	}
	const meanSwapDiff = swapPairCount > 0 ? swapDiffSum / swapPairCount : 0;
	const swapConsistency = 1 - clamp(meanSwapDiff, 0, 1);

	const grouped = new Map<string, CompareRepetition[]>();
	for (const repetition of repetitions) {
		const bucket = grouped.get(repetition.model) ?? [];
		bucket.push(repetition);
		grouped.set(repetition.model, bucket);
	}
	const modelBreakdown = Array.from(grouped.entries()).map(([model, items]) => ({
		model,
		weight: items[0]?.weight ?? 1,
		repetitions: items.length,
		score_a: weightedMean(items, (item) => item.canonical_score_a, (item) => item.weight),
		score_b: weightedMean(items, (item) => item.canonical_score_b, (item) => item.weight),
		margin: weightedMean(items, (item) => item.canonical_score_a - item.canonical_score_b, (item) => item.weight),
	}));
	return {
		score_a: scoreA,
		score_b: scoreB,
		margin: scoreA - scoreB,
		disagreement,
		confidence,
		swap_consistency: swapConsistency,
		model_breakdown: modelBreakdown,
	};
};

const buildAuditBreakdown = (repetitions: AuditRepetition[]) => {
	const score = weightedMean(repetitions, (item) => item.score, (item) => item.weight);
	const meanDelta = weightedMean(repetitions, (item) => item.score - 0.5, (item) => item.weight);
	const disagreement = clamp(weightedStdDev(repetitions, (item) => item.score, (item) => item.weight, score) * 2, 0, 1);
	const confidence = clamp(Math.abs(meanDelta) * 2 * (1 - disagreement), 0, 1);

	let positive = 0;
	let negative = 0;
	for (const repetition of repetitions) {
		if (repetition.score >= 0.7) positive += 1;
		else if (repetition.score <= 0.3) negative += 1;
	}
	const nonAbstain = positive + negative;
	const voteMargin = nonAbstain > 0 ? Math.max(positive, negative) / nonAbstain : 0;

	const grouped = new Map<string, AuditRepetition[]>();
	for (const repetition of repetitions) {
		const bucket = grouped.get(repetition.model) ?? [];
		bucket.push(repetition);
		grouped.set(repetition.model, bucket);
	}
	const modelBreakdown = Array.from(grouped.entries()).map(([model, items]) => ({
		model,
		weight: items[0]?.weight ?? 1,
		repetitions: items.length,
		score: weightedMean(items, (item) => item.score, (item) => item.weight),
		confidence: clamp(
			Math.abs(weightedMean(items, (item) => item.score - 0.5, (item) => item.weight)) * 2 *
				(1 - clamp(weightedStdDev(items, (item) => item.score, (item) => item.weight) * 2, 0, 1)),
			0,
			1,
		),
	}));
	return {
		score,
		disagreement,
		confidence,
		vote_margin: voteMargin,
		model_breakdown: modelBreakdown,
	};
};

const callPiModelPrompt = async (
	ctx: ExtensionContext,
	signal: AbortSignal | undefined,
	resolvedModel: ResolvedPiModel,
	prompt: string,
): Promise<string> => {
	const auth = await ctx.modelRegistry.getApiKeyAndHeaders(resolvedModel.model);
	if (!auth.ok) {
		throw new Error(`${resolvedModel.display}: ${auth.error}`);
	}
	if (!auth.apiKey) {
		throw new Error(`No API key configured for ${resolvedModel.display}.`);
	}

	const options: Record<string, unknown> = {
		apiKey: auth.apiKey,
		headers: auth.headers,
		signal,
		maxTokens: 2048,
		temperature: 0.7,
	};
	if (resolvedModel.model.reasoning) {
		options.reasoningEffort = "high";
	}

	const response = await complete(
		resolvedModel.model,
		{
			messages: [
				{
					role: "user",
					content: [{ type: "text", text: prompt }],
					timestamp: Date.now(),
				},
			],
		},
		options as any,
	);

	return extractTextFromAssistantMessage(response);
};

const runPiCompare = async (ctx: ExtensionContext, signal: AbortSignal | undefined, config: VerifierConfig) => {
	const wins = new Map(config.candidates.map((candidate) => [candidate.id, 0]));
	const pairTotals = new Map(config.candidates.map((candidate) => [candidate.id, [] as number[]]));
	const pairConfidences = new Map(config.candidates.map((candidate) => [candidate.id, [] as number[]]));
	const pairwise: any[] = [];
	let estimatedCalls = 0;

	for (let left = 0; left < config.candidates.length; left += 1) {
		for (let right = left + 1; right < config.candidates.length; right += 1) {
			const candidateA = config.candidates[left];
			const candidateB = config.candidates[right];
			const criteriaResults: any[] = [];
			const votes = new Map<string, number>([
				[candidateA.id, 0],
				[candidateB.id, 0],
			]);

			for (const criterion of config.criteria) {
				const repetitions: CompareRepetition[] = [];
				for (let rep = 0; rep < config.nVerifications; rep += 1) {
					const orderEntries: Array<{
						order: "original" | "swapped";
						first: NormalizedCandidate;
						second: NormalizedCandidate;
					}> = [
						{ order: "original", first: candidateA, second: candidateB },
						{ order: "swapped", first: candidateB, second: candidateA },
					];
					for (const entry of orderEntries) {
						estimatedCalls += 1;
						const selectedModel = selectModelForAttempt(config.models, rep * 2 + (entry.order === "swapped" ? 1 : 0));
						const weight = getWeightForModel(config.modelWeights, selectedModel.display);
						const prompt = createComparePrompt(config, entry.first, entry.second, criterion);
						const text = config.mock
							? buildMockCompareText(prompt, entry.first, entry.second)
							: await callPiModelPrompt(ctx, signal, selectedModel, prompt);
						const scoreA = extractTaggedScore(text, "<score_A>");
						const scoreB = extractTaggedScore(text, "<score_B>");
						const isSwapped = entry.order === "swapped";
						repetitions.push({
							rep: rep + 1,
							order: entry.order,
							model: selectedModel.display,
							weight,
							score_a: scoreA.score,
							score_b: scoreB.score,
							canonical_score_a: isSwapped ? scoreB.score : scoreA.score,
							canonical_score_b: isSwapped ? scoreA.score : scoreB.score,
							source_a: scoreA.source,
							source_b: scoreB.source,
							response_excerpt: truncate(text, 500).text,
						});
					}
				}

				const breakdown = buildCompareBreakdown(repetitions);
				criteriaResults.push({
					criterion,
					...breakdown,
					repetitions,
				});
			}

			const scoreA = average(criteriaResults.map((result) => result.score_a));
			const scoreB = average(criteriaResults.map((result) => result.score_b));
			const confidence = average(criteriaResults.map((result) => result.confidence));
			const disagreement = average(criteriaResults.map((result) => result.disagreement));
			const modelBreakdown = Array.from(
				criteriaResults
					.flatMap((result) => result.repetitions as CompareRepetition[])
					.reduce((map, repetition) => {
						const bucket = map.get(repetition.model) ?? [];
						bucket.push(repetition);
						map.set(repetition.model, bucket);
						return map;
					}, new Map<string, CompareRepetition[]>()),
			).map(([model, repetitions]) => ({
				model,
				weight: repetitions[0]?.weight ?? 1,
				repetitions: repetitions.length,
				score_a: weightedMean(repetitions, (item) => item.canonical_score_a, (item) => item.weight),
				score_b: weightedMean(repetitions, (item) => item.canonical_score_b, (item) => item.weight),
				confidence: buildCompareBreakdown(repetitions).confidence,
			}));

			for (const result of criteriaResults) {
				for (const repetition of result.repetitions as CompareRepetition[]) {
					if (repetition.canonical_score_a > repetition.canonical_score_b) {
						votes.set(candidateA.id, (votes.get(candidateA.id) ?? 0) + 1);
					} else if (repetition.canonical_score_b > repetition.canonical_score_a) {
						votes.set(candidateB.id, (votes.get(candidateB.id) ?? 0) + 1);
					} else {
						votes.set(candidateA.id, (votes.get(candidateA.id) ?? 0) + 0.5);
						votes.set(candidateB.id, (votes.get(candidateB.id) ?? 0) + 0.5);
					}
				}
			}
			const totalVotes = (votes.get(candidateA.id) ?? 0) + (votes.get(candidateB.id) ?? 0);
			const voteMargin = totalVotes > 0
				? Math.max(votes.get(candidateA.id) ?? 0, votes.get(candidateB.id) ?? 0) / totalVotes
				: 0;

			const candidateWinner = voteMargin >= 0.7 ? chooseWinner(scoreA, scoreB, 0.05) : "tie";
			let winner: string;
			if (candidateWinner === "candidate_a") {
				wins.set(candidateA.id, (wins.get(candidateA.id) ?? 0) + 1);
				winner = candidateA.id;
			} else if (candidateWinner === "candidate_b") {
				wins.set(candidateB.id, (wins.get(candidateB.id) ?? 0) + 1);
				winner = candidateB.id;
			} else {
				wins.set(candidateA.id, (wins.get(candidateA.id) ?? 0) + 0.5);
				wins.set(candidateB.id, (wins.get(candidateB.id) ?? 0) + 0.5);
				winner = "tie";
			}

			pairTotals.get(candidateA.id)?.push(scoreA);
			pairTotals.get(candidateB.id)?.push(scoreB);
			pairConfidences.get(candidateA.id)?.push(confidence);
			pairConfidences.get(candidateB.id)?.push(confidence);
			pairwise.push({
				candidate_a: candidateA.id,
				candidate_b: candidateB.id,
				score_a: scoreA,
				score_b: scoreB,
				margin: scoreA - scoreB,
				confidence,
				disagreement,
				vote_margin: voteMargin,
				winner,
				model_breakdown: modelBreakdown,
				criteria: criteriaResults,
			});
		}
	}

	const ranking = config.candidates
		.map((candidate) => {
			const pairScores = pairTotals.get(candidate.id) ?? [];
			const confidences = pairConfidences.get(candidate.id) ?? [];
			return {
				id: candidate.id,
				wins: wins.get(candidate.id) ?? 0,
				mean_pair_score: pairScores.length ? average(pairScores) : 0.5,
				mean_pair_confidence: confidences.length ? average(confidences) : 0,
				summary: candidate.summary,
			};
		})
		.sort(
			(a, b) =>
				(b.wins - a.wins) ||
				(b.mean_pair_score - a.mean_pair_score) ||
				(b.mean_pair_confidence - a.mean_pair_confidence) ||
				a.id.localeCompare(b.id),
		);

	return {
		mode: "compare",
		winner: ranking[0] ?? null,
		ranking,
		pairwise,
		estimated_calls: estimatedCalls,
	};
};

const runPiAudit = async (ctx: ExtensionContext, signal: AbortSignal | undefined, config: VerifierConfig) => {
	const candidate = config.candidates[0];
	let estimatedCalls = 0;
	const criteriaResults: any[] = [];

	for (const criterion of config.criteria) {
		const repetitions: AuditRepetition[] = [];
		for (let rep = 0; rep < config.nVerifications; rep += 1) {
			estimatedCalls += 1;
			const selectedModel = selectModelForAttempt(config.models, rep);
			const weight = getWeightForModel(config.modelWeights, selectedModel.display);
			const prompt = createAuditPrompt(config, candidate, criterion);
			const text = config.mock
				? buildMockAuditText(prompt, candidate)
				: await callPiModelPrompt(ctx, signal, selectedModel, prompt);
			const score = extractTaggedScore(text, "<score>");
			repetitions.push({
				rep: rep + 1,
				model: selectedModel.display,
				weight,
				score: score.score,
				source: score.source,
				response_excerpt: truncate(text, 500).text,
			});
		}
		criteriaResults.push({
			criterion,
			...buildAuditBreakdown(repetitions),
			repetitions,
		});
	}

	return {
		mode: "audit",
		candidate: { id: candidate.id, summary: candidate.summary },
		overall_score: average(criteriaResults.map((result) => result.score)),
		overall_confidence: average(criteriaResults.map((result) => result.confidence)),
		overall_vote_margin: average(criteriaResults.map((result) => result.vote_margin ?? 0)),
		criteria: criteriaResults,
		estimated_calls: estimatedCalls,
	};
};

const buildSummaryLines = (
	mode: "compare" | "audit",
	backend: string,
	models: ResolvedPiModel[],
	weights: ResolvedModelWeight[],
	result: any,
	mock: boolean,
	savedOutputPath?: string,
): string[] => {
	const lines = [`Backend: ${backend}`, `Models: ${models.map((model) => model.display).join(" -> ")}`];
	if (weights.some((entry) => entry.weight !== 1)) {
		lines.push(`Weights: ${weights.map((entry) => `${entry.model}=${entry.weight}`).join(", ")}`);
	}
	if (mode === "compare") {
		const ranking = Array.isArray(result.ranking) ? result.ranking : [];
		const winner = result.winner?.id ?? ranking[0]?.id ?? "unknown";
		const confidence = Number(result.winner?.mean_pair_confidence ?? 0).toFixed(3);
		lines.push(`Winner: ${winner}`);
		lines.push(`Winner confidence: ${confidence}`);
		const pairwise = Array.isArray(result.pairwise) ? result.pairwise : [];
		if (pairwise.length) {
			const meanSwapConsistency = average(
				pairwise.map((entry: any) =>
					average(
						Array.isArray(entry.criteria) && entry.criteria.length
							? entry.criteria.map((criterion: any) => Number(criterion.swap_consistency ?? 0))
							: [0],
					),
				),
			);
			lines.push(`Swap consistency: ${meanSwapConsistency.toFixed(3)}`);
		}
		if (ranking.length) {
			lines.push(
				"Ranking: " +
					ranking
						.map(
							(item: any, index: number) =>
								`${index + 1}) ${item.id} (wins ${Number(item.wins ?? 0).toFixed(1)}, mean ${Number(item.mean_pair_score ?? 0).toFixed(3)}, confidence ${Number(item.mean_pair_confidence ?? 0).toFixed(3)})`,
						)
						.join("; "),
			);
		}
	} else {
		lines.push(`Candidate: ${result.candidate?.id ?? "unknown"}`);
		lines.push(`Overall score: ${Number(result.overall_score ?? 0).toFixed(3)}`);
		lines.push(`Overall confidence: ${Number(result.overall_confidence ?? 0).toFixed(3)}`);
	}
	lines.push(`Estimated model calls: ${result.estimated_calls ?? 0}`);
	if (mock) lines.push("Mode: mock smoke test");
	if (savedOutputPath) lines.push(`Saved JSON: ${savedOutputPath}`);
	return lines;
};

const runVerifierRequest = async (
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	params: any,
	signal?: AbortSignal,
) => {
	const cwd = ctx.cwd;
	const backend = (params.backend ?? "gemini-python") as Backend;
	const mode = params.mode ?? (params.candidates.length === 1 ? "audit" : "compare");
	if (mode === "compare" && params.candidates.length < 2) {
		throw new Error("compare mode requires at least two candidates");
	}
	if (mode === "audit" && params.candidates.length !== 1) {
		throw new Error("audit mode requires exactly one candidate");
	}

	const maxCandidateChars = params.maxCandidateChars ?? 12000;
	const maxEvidenceChars = params.maxEvidenceChars ?? 6000;
	const sharedEvidence = await readEvidenceBlocks(cwd, params.evidencePaths, maxEvidenceChars);
	const sharedContextParts: string[] = [];
	if (params.context?.trim()) sharedContextParts.push(params.context.trim());
	if (sharedEvidence.length) {
		sharedContextParts.push("Shared evidence:\n" + sharedEvidence.map((item) => `[${item.label}]\n${item.content}`).join("\n\n"));
	}

	const candidates = await Promise.all(
		(params.candidates as CandidateInput[]).map(async (candidate, index) => {
			const base = await extractTextSource(cwd, `candidate ${candidate.id || index + 1}`, candidate, maxCandidateChars);
			const evidenceBlocks = await readEvidenceBlocks(cwd, candidate.evidencePaths, maxEvidenceChars);
			if (candidate.evidenceText?.trim()) {
				const clipped = truncate(candidate.evidenceText.trim(), maxEvidenceChars);
				evidenceBlocks.push({
					label: `${candidate.id}-inline-evidence`,
					content: clipped.text,
					source: `${candidate.id}:inline-evidence`,
					truncated: clipped.truncated,
				});
			}

			return {
				id: candidate.id,
				summary: candidate.summary?.trim() || "",
				content: base.text,
				source: base.source,
				truncated: base.truncated,
				evidence: evidenceBlocks.map((item) => ({ label: item.label, content: item.content })),
				evidenceSources: evidenceBlocks,
			} satisfies NormalizedCandidate;
		}),
	);

	const requestedModelSpecs =
		backend === "pi-model-ensemble"
			? ((params.models as string[] | undefined) ?? [...DEFAULT_ENSEMBLE_MODEL_SPECS])
			: [params.model ?? (backend === "zai-coding-plan" ? "zai:glm-5.1" : "google:gemini-2.5-flash")];
	const resolvedModels = resolveVerifierModels(ctx, requestedModelSpecs);
	const resolvedWeights = resolveModelWeights(resolvedModels, params.modelWeights as ModelWeightInput[] | undefined);

	const config: VerifierConfig = {
		mode,
		backend,
		task: params.task,
		context: sharedContextParts.join("\n\n"),
		groundTruthNote: DEFAULT_GROUND_TRUTH_NOTE,
		criteria: (params.criteria as CriterionInput[]).map((criterion) => ({
			id: criterion.id?.trim() || slugify(criterion.name),
			name: criterion.name,
			description: criterion.description,
		})),
		candidates,
		nVerifications: params.nVerifications ?? (backend === "pi-model-ensemble" ? Math.max(5, resolvedModels.length) : 5),
		granularity: params.granularity ?? 20,
		mock: params.mock ?? false,
		models: resolvedModels,
		modelWeights: resolvedWeights,
	};

	let parsed: any;
	if (backend === "gemini-python") {
		const skillScriptPath = resolveUserPath(cwd, path.join(...SCRIPT_PATH));
		const tempDir = await mkdtemp(path.join(os.tmpdir(), "lav-"));
		const inputPath = path.join(tempDir, "input.json");
		const outputTempPath = path.join(tempDir, "output.json");
		try {
			const runnerInput = {
				mode: config.mode,
				task: config.task,
				context: config.context,
				criteria: config.criteria,
				candidates: config.candidates.map((candidate) => ({
					id: candidate.id,
					summary: candidate.summary,
					content: candidate.content,
					evidence: candidate.evidence,
				})),
				n_verifications: config.nVerifications,
				granularity: config.granularity,
				model: config.models[0]?.id ?? "gemini-2.5-flash",
				mock: config.mock,
			};
			await writeFile(inputPath, JSON.stringify(runnerInput, null, 2), "utf8");
			await runPython(pi, skillScriptPath, ["--input", inputPath, "--output", outputTempPath, ...(config.mock ? ["--mock"] : [])], signal);
			parsed = JSON.parse(await readFile(outputTempPath, "utf8"));
		} finally {
			await rm(tempDir, { recursive: true, force: true });
		}
		if (!parsed?.ok) {
			throw new Error(parsed?.error || "Verifier runner failed");
		}
	} else {
		const result = mode === "compare" ? await runPiCompare(ctx, signal, config) : await runPiAudit(ctx, signal, config);
		parsed = {
			ok: true,
			config: {
				mode: config.mode,
				backend: config.backend,
				models: config.models.map((model) => model.display),
				modelWeights: config.modelWeights,
				granularity: config.granularity,
				n_verifications: config.nVerifications,
				criteria: config.criteria.map((criterion) => ({ id: criterion.id, name: criterion.name })),
				candidate_ids: config.candidates.map((candidate) => candidate.id),
				mock: config.mock,
			},
			result,
		};
	}

	let savedOutputPath: string | undefined;
	if (params.outputPath) {
		savedOutputPath = resolveUserPath(cwd, params.outputPath);
		await withFileMutationQueue(savedOutputPath, async () => {
			await mkdir(path.dirname(savedOutputPath!), { recursive: true });
			await writeFile(savedOutputPath!, JSON.stringify(parsed, null, 2), "utf8");
		});
	}

	const candidateNotes = candidates.map((candidate) => ({
		id: candidate.id,
		source: candidate.source,
		truncated: candidate.truncated,
		evidenceSources: candidate.evidenceSources.map((item) => ({
			label: item.label,
			source: item.source,
			truncated: item.truncated,
		})),
	}));

	const summaryLines = buildSummaryLines(config.mode, config.backend, config.models, config.modelWeights, parsed.result, config.mock, savedOutputPath);

	return {
		backend: config.backend,
		mode: config.mode,
		parsed,
		savedOutputPath,
		candidateNotes,
		resolvedModels: config.models.map((model) => ({
			spec: model.spec,
			provider: model.provider,
			id: model.id,
			display: model.display,
		})),
		resolvedModelWeights: config.modelWeights,
		sharedEvidenceSources: sharedEvidence.map((item) => ({
			label: item.label,
			source: item.source,
			truncated: item.truncated,
		})),
		summaryLines,
	};
};

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: TOOL_NAME,
		label: "LLM as Verifier",
		description:
			"Compare or audit candidate artifacts with repeated, criteria-decomposed LLM verification inspired by the llm-as-verifier paper.",
		promptSnippet:
			"Compare 2-6 candidate patches, plans, answers, or drafts using pairwise repeated LLM verification with explicit criteria and evidence.",
		promptGuidelines: [
			"Use this tool when choosing between multiple candidate solutions and a single free-form judgment would be brittle.",
			"Prefer compare mode over audit mode whenever at least two candidates exist.",
			"Supply sharp criteria and concrete evidence such as tests, logs, patches, or spec excerpts.",
			"Use backend 'zai-coding-plan' for a single ZAI verifier model routed through Pi's model registry.",
			"Use backend 'pi-model-ensemble' to rotate across Kimi, MiniMax, and OpenAI GPT-5.5 by default; override models when the decision needs a different panel.",
			"For /delegate-generated candidates, include lane outputs as evidence and weight deterministic verification above model narration.",
		],
		parameters: Type.Object({
			backend: Type.Optional(StringEnum(["gemini-python", "zai-coding-plan", "pi-model-ensemble"] as const)),
			mode: Type.Optional(StringEnum(["compare", "audit"] as const)),
			task: Type.String({ description: "Task, requirement, or question the verifier should judge against." }),
			context: Type.Optional(Type.String({ description: "Shared background context or evidence summary." })),
			candidates: Type.Array(
				Type.Object({
					id: Type.String({ description: "Stable candidate identifier." }),
					path: Type.Optional(Type.String({ description: "Relative or absolute path to a text file for this candidate." })),
					content: Type.Optional(Type.String({ description: "Inline candidate content when no file path is used." })),
					summary: Type.Optional(Type.String({ description: "Short candidate summary, e.g. patch strategy or model name." })),
					evidencePaths: Type.Optional(Type.Array(Type.String({ description: "Text files containing candidate-specific evidence." }))),
					evidenceText: Type.Optional(Type.String({ description: "Inline candidate-specific evidence." })),
				}),
				{ minItems: 1, maxItems: 6 },
			),
			criteria: Type.Array(
				Type.Object({
					id: Type.Optional(Type.String()),
					name: Type.String(),
					description: Type.String(),
				}),
				{ minItems: 1, maxItems: 6 },
			),
			evidencePaths: Type.Optional(Type.Array(Type.String({ description: "Shared evidence files for all candidates." }))),
			nVerifications: Type.Optional(Type.Integer({ minimum: 1, maximum: 9 })),
			granularity: Type.Optional(Type.Integer({ minimum: 20, maximum: 20 })),
			model: Type.Optional(
				Type.String({
					description:
						"Single verifier model. Defaults to zai:glm-5.1 for zai-coding-plan and google:gemini-2.5-flash for gemini-python.",
				}),
			),
			models: Type.Optional(
				Type.Array(
					Type.String({
						description:
							"Verifier model specs for pi-model-ensemble, using provider:id or known aliases like kimi-for-coding, kimi-k2, minimax-m3, minimax-m2.7-highspeed, gpt-5.5, or gpt-5-codex.",
					}),
					{ minItems: 1, maxItems: 9 },
				),
			),
			modelWeights: Type.Optional(
				Type.Array(
					Type.Object({
						model: Type.String({ description: "Model spec or display name to weight." }),
						weight: Type.Number({ minimum: 0, description: "Relative weight for that model in aggregation." }),
					}),
					{ minItems: 1, maxItems: 9 },
				),
			),
			outputPath: Type.Optional(Type.String({ description: "Optional path to save the full JSON result." })),
			maxCandidateChars: Type.Optional(Type.Integer({ minimum: 1000, maximum: 40000 })),
			maxEvidenceChars: Type.Optional(Type.Integer({ minimum: 500, maximum: 20000 })),
			mock: Type.Optional(Type.Boolean({ description: "Use deterministic mock scoring for smoke tests only." })),
		}),
		async execute(_toolCallId, params, signal, _onUpdate, ctx) {
			const run = await runVerifierRequest(pi, ctx, params, signal);
			return {
				content: [{ type: "text", text: run.summaryLines.join("\n") }],
				details: {
					...run.parsed,
					savedOutputPath: run.savedOutputPath,
					candidateNotes: run.candidateNotes,
					resolvedModels: run.resolvedModels,
					resolvedModelWeights: run.resolvedModelWeights,
					sharedEvidenceSources: run.sharedEvidenceSources,
				},
			};
		},
	});

	pi.registerCommand("lav-smoke", {
		description: "Run the bundled llm-as-verifier Python example in deterministic mock mode",
		handler: async (_args, ctx) => {
			const scriptPath = resolveUserPath(ctx.cwd, path.join(...SCRIPT_PATH));
			const examplePath = resolveUserPath(ctx.cwd, path.join(...EXAMPLE_PATH));
			const tempDir = await mkdtemp(path.join(os.tmpdir(), "lav-smoke-"));
			const outputPath = path.join(tempDir, "result.json");
			try {
				const result = await runPython(pi, scriptPath, ["--input", examplePath, "--output", outputPath, "--mock"]);
				const parsed = JSON.parse(await readFile(outputPath, "utf8")) as any;
				const winner = parsed.result?.winner?.id ?? "unknown";
				const message = `LLM-as-Verifier smoke test complete. Winner: ${winner}. Output: ${outputPath}`;
				if (ctx.hasUI) ctx.ui.notify(message, "success");
				else console.log(message);
				if (result.stderr?.trim() && ctx.hasUI) ctx.ui.notify(result.stderr.trim(), "info");
			} finally {
				// Keep temp output for inspection when smoke command is used.
			}
		},
	});

	pi.registerCommand("lav-ensemble-smoke", {
		description: "Run the bundled weighted ensemble example in deterministic mock mode",
		handler: async (_args, ctx) => {
			const examplePath = resolveUserPath(ctx.cwd, path.join(...ENSEMBLE_EXAMPLE_PATH));
			const tempDir = await mkdtemp(path.join(os.tmpdir(), "lav-ensemble-smoke-"));
			const outputPath = path.join(tempDir, "result.json");
			const example = JSON.parse(await readFile(examplePath, "utf8"));
			const run = await runVerifierRequest(
				pi,
				ctx,
				{
					...example,
					mock: true,
					outputPath,
				},
			);
			const winner = run.parsed?.result?.winner?.id ?? "unknown";
			const weightSummary = run.resolvedModelWeights.map((entry) => `${entry.model}=${entry.weight}`).join(", ");
			const message = `LLM-as-Verifier ensemble smoke test complete. Winner: ${winner}. Weights: ${weightSummary}. Output: ${run.savedOutputPath}`;
			if (ctx.hasUI) ctx.ui.notify(message, "success");
			else console.log(message);
		},
	});
}
