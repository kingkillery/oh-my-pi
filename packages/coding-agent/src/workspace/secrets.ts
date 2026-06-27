import * as fs from "node:fs/promises";
import * as path from "node:path";
import { isEnoent, pathIsWithin } from "@pk-nerdsaver-ai/pi-utils";
import { resolveToCwd } from "../tools/path-utils";
import { defaultEnvFileRecord, sanitizeWorkspaceName, toPosixRelative } from "./paths";
import { redactedSecretList } from "./redaction";
import type { ResolvedWorkspaceOptions } from "./types";
import { type CopiedSecretsResult, DEFAULT_ENV_FILES, ETHEREAL_DIR, ETHEREAL_SECRETS_DIR } from "./types";

interface CopyOneResult {
	readonly manifestPath: string;
	readonly relativePath: string;
}

interface Allowlist {
	readonly relative: Record<string, true>;
	readonly absolute: Record<string, true>;
}

export async function copyAllowedSecrets(
	sourceRoot: string,
	workspacePath: string,
	options: ResolvedWorkspaceOptions,
): Promise<CopiedSecretsResult> {
	const allowlist = await readAllowlist(sourceRoot, options.secretAllowlist);
	const copiedEnv: string[] = [];
	const copiedSecretRelatives: string[] = [];
	const sensitiveRelativePaths: string[] = [];

	if (options.copyEnv) {
		for (const request of DEFAULT_ENV_FILES) {
			const copied = await copyOne(sourceRoot, workspacePath, request, allowlist, true);
			if (!copied) continue;
			copiedEnv.push(copied.manifestPath);
			sensitiveRelativePaths.push(copied.relativePath);
		}
	}
	for (const request of options.envFiles) {
		const copied = await copyOne(sourceRoot, workspacePath, request, allowlist, false);
		if (!copied) continue;
		copiedEnv.push(copied.manifestPath);
		sensitiveRelativePaths.push(copied.relativePath);
	}
	for (const request of options.secretFiles) {
		const copied = await copyOne(sourceRoot, workspacePath, request, allowlist, false);
		if (!copied) continue;
		copiedSecretRelatives.push(copied.relativePath);
		sensitiveRelativePaths.push(copied.relativePath);
	}

	return {
		copiedEnvFiles: copiedEnv,
		copiedSecretFiles: redactedSecretList(copiedSecretRelatives.length),
		sensitiveRelativePaths,
	};
}

async function copyOne(
	sourceRoot: string,
	workspacePath: string,
	request: string,
	allowlist: Allowlist | undefined,
	allowMissing: boolean,
): Promise<CopyOneResult | null> {
	const sourcePath = resolveRequestedPath(sourceRoot, request);
	if (allowlist && !allowlistAllows(sourceRoot, sourcePath, allowlist)) {
		throw new Error(`Ethereal workspace refused to copy ${request}: not present in secret allowlist`);
	}
	const insideRelative = lexicalRelativePathFromRoot(sourceRoot, sourcePath);
	try {
		const stat = await fs.stat(sourcePath);
		if (!stat.isFile()) throw new Error(`Ethereal workspace can only copy files: ${request}`);
		// A repo-relative request must resolve to a file that still lives inside the
		// source repository. pathIsWithin resolves symlinks on both sides (realpath), so
		// this also rejects a file reached through a symlinked intermediate directory.
		if (insideRelative && insideRelative.length > 0 && !pathIsWithin(sourceRoot, sourcePath)) {
			throw new Error(
				`Ethereal workspace refused to follow ${request}: symlink target escapes the source repository`,
			);
		}
	} catch (error) {
		if (isEnoent(error)) {
			if (allowMissing && defaultEnvFileRecord()[request] === true) return null;
			throw new Error(`Ethereal workspace file does not exist: ${request}`);
		}
		throw error;
	}

	const relativePath = insideRelative && insideRelative.length > 0 ? insideRelative : secretDestination(sourcePath);
	const targetPath = path.join(workspacePath, relativePath);
	await fs.mkdir(path.dirname(targetPath), { recursive: true });
	await fs.copyFile(sourcePath, targetPath);
	return {
		manifestPath: insideRelative && insideRelative.length > 0 ? insideRelative : "<redacted>",
		relativePath: toPosixRelative(relativePath),
	};
}

function resolveRequestedPath(sourceRoot: string, request: string): string {
	const resolved = path.resolve(resolveToCwd(request, sourceRoot));
	const segments = request.split(/[\\/]+/);
	if (!path.isAbsolute(request) && segments.includes("..") && !pathIsWithin(sourceRoot, resolved)) {
		throw new Error(`Ethereal workspace path escapes the source repository: ${request}`);
	}
	return resolved;
}

async function readAllowlist(sourceRoot: string, allowlistPath: string | undefined): Promise<Allowlist | undefined> {
	if (!allowlistPath) return undefined;
	const resolved = resolveRequestedPath(sourceRoot, allowlistPath);
	const text = await Bun.file(resolved).text();
	const relative: Record<string, true> = {};
	const absolute: Record<string, true> = {};
	for (const rawLine of text.split("\n")) {
		const line = rawLine.trim();
		if (!line || line.startsWith("#")) continue;
		if (path.isAbsolute(line)) {
			absolute[path.resolve(line)] = true;
		} else {
			relative[toPosixRelative(path.normalize(line))] = true;
		}
	}
	return { relative, absolute };
}

function allowlistAllows(sourceRoot: string, sourcePath: string, allowlist: Allowlist): boolean {
	const insideRelative = lexicalRelativePathFromRoot(sourceRoot, sourcePath);
	if (insideRelative && allowlist.relative[insideRelative] === true) return true;
	return allowlist.absolute[path.resolve(sourcePath)] === true;
}

function lexicalRelativePathFromRoot(root: string, candidate: string): string | null {
	const resolvedRoot = path.resolve(root);
	const resolvedCandidate = path.resolve(candidate);
	const relative = path.relative(resolvedRoot, resolvedCandidate);
	if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) return null;
	return toPosixRelative(relative);
}

function secretDestination(sourcePath: string): string {
	return toPosixRelative(
		path.join(ETHEREAL_DIR, ETHEREAL_SECRETS_DIR, sanitizeWorkspaceName(path.basename(sourcePath))),
	);
}
