import * as path from "node:path";
import { pathIsWithin } from "@pk-nerdsaver-ai/pi-utils";
import { DEFAULT_ENV_FILES, DEFAULT_EXCLUDED_PATHS, DEFAULT_SECRET_BASENAMES } from "./types";

const EXCLUDED_SEGMENTS: Record<string, true> = {};
for (const item of DEFAULT_EXCLUDED_PATHS) {
	EXCLUDED_SEGMENTS[item] = true;
}

const SECRET_BASENAMES: Record<string, true> = {};
for (const item of DEFAULT_SECRET_BASENAMES) {
	SECRET_BASENAMES[item] = true;
}

export function toPosixRelative(relativePath: string): string {
	return relativePath.split(path.sep).join("/");
}

export function sanitizeWorkspaceName(name: string | undefined): string {
	if (!name) return "run";
	const sanitized = name
		.trim()
		.replace(/[^A-Za-z0-9._-]+/g, "-")
		.replace(/^-+|-+$/g, "")
		.slice(0, 80);
	return sanitized || "run";
}

export function isDefaultExcludedPath(relativePath: string): boolean {
	const normalized = toPosixRelative(relativePath);
	if (normalized === ".") return false;
	return normalized.split("/").some(part => EXCLUDED_SEGMENTS[part] === true);
}

export function isDefaultEnvFile(relativePath: string): boolean {
	const basename = path.basename(relativePath);
	return basename !== ".env.example" && (basename === ".env" || basename.startsWith(".env."));
}

export function isDefaultSecretPath(relativePath: string): boolean {
	const basename = path.basename(relativePath);
	return SECRET_BASENAMES[basename] === true || basename === "dev-secrets.json";
}

export function isImplicitSensitivePath(relativePath: string): boolean {
	return isDefaultEnvFile(relativePath) || isDefaultSecretPath(relativePath);
}

export function shouldCopyDefaultPath(relativePath: string): boolean {
	return !isDefaultExcludedPath(relativePath) && !isImplicitSensitivePath(relativePath);
}

export function defaultExcludeGlobs(): string[] {
	return DEFAULT_EXCLUDED_PATHS.flatMap(item => [item, `${item}/**`, `**/${item}`, `**/${item}/**`]);
}

export function relativePathFromRoot(root: string, candidate: string): string | null {
	if (!pathIsWithin(root, candidate)) return null;
	const relative = path.relative(root, candidate);
	return relative ? toPosixRelative(relative) : "";
}

export function defaultEnvFileRecord(): Record<string, true> {
	const record: Record<string, true> = {};
	for (const file of DEFAULT_ENV_FILES) {
		record[file] = true;
	}
	return record;
}
