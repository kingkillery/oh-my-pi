import type { Dirent } from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";

const DEFAULT_MAX_FILES = 1_500;
const DEFAULT_MAX_CANDIDATES = 10;
const MAX_FILE_BYTES = 512 * 1024;
const CONTEXT_RADIUS = 1;
const TEXT_EXTENSIONS: Record<string, true> = {
	".cjs": true,
	".cts": true,
	".go": true,
	".js": true,
	".json": true,
	".jsonc": true,
	".md": true,
	".mjs": true,
	".mts": true,
	".py": true,
	".rs": true,
	".toml": true,
	".ts": true,
	".tsx": true,
	".yaml": true,
	".yml": true,
};
const SKIPPED_DIRECTORIES: Record<string, true> = {
	".git": true,
	".next": true,
	".turbo": true,
	coverage: true,
	dist: true,
	node_modules: true,
	target: true,
};
const STOP_WORDS: Record<string, true> = {
	about: true,
	after: true,
	agent: true,
	agents: true,
	below: true,
	code: true,
	current: true,
	does: true,
	file: true,
	files: true,
	find: true,
	from: true,
	into: true,
	repo: true,
	return: true,
	show: true,
	task: true,
	that: true,
	the: true,
	this: true,
	where: true,
	with: true,
};

export interface RepoEvidenceCandidate {
	readonly path: string;
	readonly lineStart: number;
	readonly lineEnd: number;
	readonly score: number;
	readonly excerpt: string;
}

export interface BuildRepoEvidenceOptions {
	readonly cwd: string;
	readonly query: string;
	readonly maxCandidates?: number;
	readonly maxFiles?: number;
	readonly signal?: AbortSignal;
}

interface ScoredLine {
	readonly path: string;
	readonly line: number;
	readonly score: number;
}

function extractQueryTerms(query: string): readonly string[] {
	const matches = query.match(/[A-Za-z0-9_@./:-]{3,}/g) ?? [];
	const terms: string[] = [];
	const seen = new Set<string>();
	for (const match of matches) {
		const term = match.toLowerCase();
		if (STOP_WORDS[term] || seen.has(term)) continue;
		seen.add(term);
		terms.push(term);
	}
	return terms.slice(0, 24);
}

function isTextFile(filePath: string): boolean {
	return TEXT_EXTENSIONS[path.extname(filePath).toLowerCase()] === true;
}

function countTermHits(value: string, terms: readonly string[]): number {
	let hits = 0;
	const lower = value.toLowerCase();
	for (const term of terms) {
		if (lower.includes(term)) hits += 1;
	}
	return hits;
}

async function collectFiles(root: string, maxFiles: number, signal?: AbortSignal): Promise<string[]> {
	const files: string[] = [];
	const visit = async (dir: string): Promise<void> => {
		if (signal?.aborted || files.length >= maxFiles) return;
		let entries: Dirent[];
		try {
			entries = await fs.readdir(dir, { withFileTypes: true });
		} catch {
			return;
		}
		for (const entry of entries) {
			if (signal?.aborted || files.length >= maxFiles) return;
			if (entry.isDirectory()) {
				if (SKIPPED_DIRECTORIES[entry.name] !== true) {
					await visit(path.join(dir, entry.name));
				}
				continue;
			}
			if (!entry.isFile()) continue;
			const filePath = path.join(dir, entry.name);
			if (isTextFile(filePath)) files.push(filePath);
		}
	};
	await visit(root);
	return files;
}

async function scoreFile(root: string, filePath: string, terms: readonly string[]): Promise<readonly ScoredLine[]> {
	const stat = await fs.stat(filePath).catch(() => null);
	if (!stat || stat.size > MAX_FILE_BYTES) return [];
	const relPath = path.relative(root, filePath).replaceAll(path.sep, "/");
	const pathScore = countTermHits(relPath, terms);
	let text: string;
	try {
		text = await Bun.file(filePath).text();
	} catch {
		return [];
	}
	const lines = text.split(/\r?\n/);
	const scored: ScoredLine[] = [];
	for (let index = 0; index < lines.length; index++) {
		const lineScore = countTermHits(lines[index], terms) * 3;
		if (lineScore === 0) continue;
		scored.push({ path: relPath, line: index + 1, score: pathScore + lineScore });
	}
	return scored;
}

async function excerpt(root: string, candidate: ScoredLine): Promise<RepoEvidenceCandidate | undefined> {
	const filePath = path.join(root, candidate.path);
	let text: string;
	try {
		text = await Bun.file(filePath).text();
	} catch {
		return undefined;
	}
	const lines = text.split(/\r?\n/);
	const lineStart = Math.max(1, candidate.line - CONTEXT_RADIUS);
	const lineEnd = Math.min(lines.length, candidate.line + CONTEXT_RADIUS);
	const body = lines
		.slice(lineStart - 1, lineEnd)
		.map((line, offset) => `${lineStart + offset}:${line}`)
		.join("\n");
	return { path: candidate.path, lineStart, lineEnd, score: candidate.score, excerpt: body };
}

export async function buildRepoEvidence(options: BuildRepoEvidenceOptions): Promise<readonly RepoEvidenceCandidate[]> {
	const terms = extractQueryTerms(options.query);
	if (terms.length === 0) return [];
	const maxFiles = options.maxFiles ?? DEFAULT_MAX_FILES;
	const files = await collectFiles(options.cwd, maxFiles, options.signal);
	const scored: ScoredLine[] = [];
	for (const file of files) {
		if (options.signal?.aborted) break;
		scored.push(...(await scoreFile(options.cwd, file, terms)));
	}
	const unique = new Map<string, ScoredLine>();
	for (const item of scored.sort((a, b) => b.score - a.score)) {
		const key = `${item.path}:${item.line}`;
		if (!unique.has(key)) unique.set(key, item);
		if (unique.size >= (options.maxCandidates ?? DEFAULT_MAX_CANDIDATES) * 2) break;
	}
	const candidates: RepoEvidenceCandidate[] = [];
	for (const item of unique.values()) {
		const rendered = await excerpt(options.cwd, item);
		if (rendered) candidates.push(rendered);
		if (candidates.length >= (options.maxCandidates ?? DEFAULT_MAX_CANDIDATES)) break;
	}
	return candidates;
}

export function formatRepoEvidence(candidates: readonly RepoEvidenceCandidate[]): string {
	return candidates
		.map(
			candidate =>
				`- ${candidate.path}:${candidate.lineStart}-${candidate.lineEnd} (score ${candidate.score})\n${candidate.excerpt}`,
		)
		.join("\n\n");
}
