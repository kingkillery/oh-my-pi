import * as path from "node:path";
import { globPaths, isEnoent } from "@pk-nerdsaver-ai/pi-utils";
import { resolveToCwd } from "../tools/path-utils";
import { defaultExcludeGlobs, isDefaultExcludedPath, isImplicitSensitivePath, toPosixRelative } from "./paths";
import { ETHEREAL_BASELINE_DIR, ETHEREAL_DIR, type ResolvedWorkspaceOptions } from "./types";

interface GitResult {
	readonly exitCode: number;
	readonly stdout: string;
	readonly stderr: string;
}

export async function initializeGitBaseline(workspacePath: string): Promise<boolean> {
	const init = await runGit(workspacePath, ["init", "-q"], true);
	if (init.exitCode !== 0) return false;
	const add = await runGit(workspacePath, ["add", "-A", "--", ".", ...patchExcludePathspecs([])], true);
	return add.exitCode === 0;
}

export async function exportWorkspacePatch(
	workspacePath: string,
	sourceCwd: string,
	options: ResolvedWorkspaceOptions,
	sensitiveRelativePaths: readonly string[],
	forceFallback: boolean,
): Promise<string | undefined> {
	if (!options.exportPatch) return undefined;
	const patchPath = resolveToCwd(options.exportPatch, sourceCwd);
	const gitPatch = forceFallback ? undefined : await exportGitPatch(workspacePath, sensitiveRelativePaths);
	const patchText = gitPatch ?? (await exportFallbackPatch(workspacePath, sensitiveRelativePaths));
	await Bun.write(patchPath, patchText);
	return patchPath;
}

async function exportGitPatch(
	workspacePath: string,
	sensitiveRelativePaths: readonly string[],
): Promise<string | undefined> {
	const add = await runGit(
		workspacePath,
		["add", "-N", "--", ".", ...patchExcludePathspecs(sensitiveRelativePaths)],
		true,
	);
	if (add.exitCode !== 0) return undefined;
	const diff = await runGit(
		workspacePath,
		["diff", "--no-ext-diff", "--binary", "--", ".", ...patchExcludePathspecs(sensitiveRelativePaths)],
		true,
	);
	return diff.exitCode === 0 || diff.exitCode === 1 ? diff.stdout : undefined;
}

async function exportFallbackPatch(workspacePath: string, sensitiveRelativePaths: readonly string[]): Promise<string> {
	const baselinePath = path.join(workspacePath, ETHEREAL_DIR, ETHEREAL_BASELINE_DIR);
	const baselineFiles = await listComparableFiles(baselinePath, []);
	const currentFiles = await listComparableFiles(workspacePath, sensitiveRelativePaths);
	const allFiles = [...new Set([...baselineFiles, ...currentFiles])].sort((left, right) => left.localeCompare(right));
	const chunks: string[] = [];
	for (const relativePath of allFiles) {
		if (isPatchExcluded(relativePath, sensitiveRelativePaths)) continue;
		const oldText = await readTextIfPresent(path.join(baselinePath, relativePath));
		const newText = await readTextIfPresent(path.join(workspacePath, relativePath));
		if (oldText === newText) continue;
		chunks.push(createWholeFilePatch(relativePath, oldText, newText));
	}
	return chunks.join("");
}

async function listComparableFiles(root: string, sensitiveRelativePaths: readonly string[]): Promise<string[]> {
	const files = await globPaths("**/*", {
		cwd: root,
		dot: true,
		gitignore: false,
		exclude: [...defaultExcludeGlobs(), `${ETHEREAL_DIR}/**`, ETHEREAL_DIR],
	});
	return files.map(toPosixRelative).filter(file => !isPatchExcluded(file, sensitiveRelativePaths));
}

function isPatchExcluded(relativePath: string, sensitiveRelativePaths: readonly string[]): boolean {
	const normalized = toPosixRelative(relativePath);
	return (
		normalized === ETHEREAL_DIR ||
		normalized.startsWith(`${ETHEREAL_DIR}/`) ||
		isDefaultExcludedPath(normalized) ||
		isImplicitSensitivePath(normalized) ||
		sensitiveRelativePaths.includes(normalized)
	);
}

async function readTextIfPresent(filePath: string): Promise<string> {
	try {
		return await Bun.file(filePath).text();
	} catch (error) {
		if (isEnoent(error)) return "";
		throw error;
	}
}

function createWholeFilePatch(relativePath: string, oldText: string, newText: string): string {
	const oldLines = splitPatchLines(oldText);
	const newLines = splitPatchLines(newText);
	const oldHeader = oldLines.length === 0 ? "0,0" : `1,${oldLines.length}`;
	const newHeader = newLines.length === 0 ? "0,0" : `1,${newLines.length}`;
	const removed = oldLines.map(line => `-${line}`).join("\n");
	const added = newLines.map(line => `+${line}`).join("\n");
	const body = [removed, added].filter(Boolean).join("\n");
	return `diff --git a/${relativePath} b/${relativePath}\n--- a/${relativePath}\n+++ b/${relativePath}\n@@ -${oldHeader} +${newHeader} @@\n${body}\n`;
}

function splitPatchLines(text: string): string[] {
	if (!text) return [];
	const withoutTrailing = text.endsWith("\n") ? text.slice(0, -1) : text;
	return withoutTrailing.length === 0 ? [] : withoutTrailing.split("\n");
}

function patchExcludePathspecs(sensitiveRelativePaths: readonly string[]): string[] {
	const exact = sensitiveRelativePaths.map(relativePath => `:(exclude)${relativePath}`);
	return [
		":(exclude).ethereal",
		":(exclude).ethereal/**",
		":(glob,exclude)**/.env",
		":(glob,exclude)**/.env.*",
		":(glob,exclude)**/.npmrc",
		":(glob,exclude)**/.pypirc",
		...defaultExcludeGlobs().map(item => `:(glob,exclude)${item}`),
		...exact,
	];
}

async function runGit(cwd: string, args: readonly string[], allowFailure: boolean): Promise<GitResult> {
	const child = Bun.spawn(["git", ...args], {
		cwd,
		stdout: "pipe",
		stderr: "pipe",
		stdin: "ignore",
		windowsHide: true,
	});
	if (!child.stdout || !child.stderr) throw new Error("Failed to capture git output.");
	const [stdout, stderr, exitCode] = await Promise.all([
		new Response(child.stdout).text(),
		new Response(child.stderr).text(),
		child.exited,
	]);
	const result = { exitCode: exitCode ?? 0, stdout, stderr };
	if (!allowFailure && result.exitCode !== 0) throw new Error(stderr.trim() || `git ${args.join(" ")} failed`);
	return result;
}
