import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { globPaths, isEnoent, pathIsWithin } from "@pk-nerdsaver-ai/pi-utils";
import * as git from "../utils/git";
import { defaultExcludeGlobs, shouldCopyDefaultPath, toPosixRelative } from "./paths";

export interface SourceRepository {
	readonly sourceRoot: string;
	readonly sourceRelativeCwd: string;
}

export type CopyStrategy = "copy" | "reflink";

export interface CopyRepoResult {
	readonly copiedFiles: readonly string[];
}

export async function resolveSourceRepository(sourceCwd: string): Promise<SourceRepository> {
	const resolvedCwd = path.resolve(sourceCwd);
	const sourceRoot =
		(await git.repo.root(resolvedCwd).catch(error => {
			if (error instanceof Error) return null;
			throw error;
		})) ?? resolvedCwd;
	const relative = path.relative(sourceRoot, resolvedCwd);
	return {
		sourceRoot,
		sourceRelativeCwd: relative && !relative.startsWith("..") && !path.isAbsolute(relative) ? relative : "",
	};
}

export async function copyRepository(
	sourceRoot: string,
	workspacePath: string,
	strategy: CopyStrategy = "copy",
): Promise<CopyRepoResult> {
	const files = await collectCopyableSourceFiles(sourceRoot);
	const copiedFiles: string[] = [];
	let nextIndex = 0;
	const workerCount = Math.min(32, Math.max(1, files.length));
	await Promise.all(
		Array.from({ length: workerCount }, async () => {
			while (nextIndex < files.length) {
				const relativePath = files[nextIndex++];
				if (relativePath === undefined) continue;
				const sourcePath = path.resolve(sourceRoot, relativePath);
				if (!pathIsWithin(sourceRoot, sourcePath)) continue;
				const copied = await copyFileLike(sourceRoot, sourcePath, path.join(workspacePath, relativePath), strategy);
				if (copied) copiedFiles.push(relativePath);
			}
		}),
	);
	return { copiedFiles: uniqueSorted(copiedFiles) };
}

export async function createFallbackBaseline(
	workspacePath: string,
	baselinePath: string,
	files: readonly string[],
): Promise<void> {
	for (const relativePath of files) {
		await copyFileLike(
			workspacePath,
			path.join(workspacePath, relativePath),
			path.join(baselinePath, relativePath),
			"copy",
		);
	}
}

export async function copyRepositoryFiles(
	sourceRoot: string,
	workspacePath: string,
	files: readonly string[],
	strategy: CopyStrategy = "copy",
): Promise<CopyRepoResult> {
	const selectedFiles = files.map(toPosixRelative).filter(shouldCopyDefaultPath);
	const copiedFiles: string[] = [];
	for (const relativePath of selectedFiles) {
		const sourcePath = path.resolve(sourceRoot, relativePath);
		if (!pathIsWithin(sourceRoot, sourcePath)) continue;
		const copied = await copyFileLike(sourceRoot, sourcePath, path.join(workspacePath, relativePath), strategy);
		if (copied) copiedFiles.push(relativePath);
	}
	return { copiedFiles: uniqueSorted(copiedFiles) };
}

export async function collectCopyableSourceFiles(sourceRoot: string): Promise<string[]> {
	return (await collectSourceFiles(sourceRoot)).filter(shouldCopyDefaultPath);
}

export async function supportsReflinkCopy(sourceRoot: string, workspaceRoot: string): Promise<boolean> {
	const files = await collectCopyableSourceFiles(sourceRoot);
	const probeSource = await firstRegularFile(sourceRoot, files);
	if (!probeSource) return true;
	await fs.mkdir(workspaceRoot, { recursive: true });
	const probeDir = await fs.mkdtemp(path.join(workspaceRoot, ".reflink-probe-"));
	try {
		await fs.copyFile(probeSource, path.join(probeDir, "probe"), fsSync.constants.COPYFILE_FICLONE_FORCE);
		return true;
	} catch (error) {
		if (isReflinkUnsupportedError(error)) return false;
		throw error;
	} finally {
		await fs.rm(probeDir, { recursive: true, force: true });
	}
}

async function collectSourceFiles(sourceRoot: string): Promise<string[]> {
	const gitRoot = await git.repo.root(sourceRoot).catch(error => {
		if (error instanceof Error) return null;
		throw error;
	});
	if (gitRoot && path.resolve(gitRoot) === path.resolve(sourceRoot)) {
		const tracked = await git.ls.files(sourceRoot);
		const untracked = await git.ls.untracked(sourceRoot);
		return uniqueSorted([...tracked, ...untracked].map(toPosixRelative));
	}
	const files = await globPaths("**/*", {
		cwd: sourceRoot,
		dot: true,
		gitignore: true,
		exclude: defaultExcludeGlobs(),
	});
	return uniqueSorted(files.map(toPosixRelative));
}

function uniqueSorted(values: readonly string[]): string[] {
	return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

async function copyFileLike(
	root: string,
	sourcePath: string,
	targetPath: string,
	strategy: CopyStrategy,
): Promise<boolean> {
	const stat = await fs.lstat(sourcePath).catch(error => {
		if (isEnoent(error)) return null;
		throw error;
	});
	if (!stat || stat.isDirectory()) return false;
	await fs.mkdir(path.dirname(targetPath), { recursive: true });
	if (stat.isSymbolicLink()) {
		const linkTarget = await fs.readlink(sourcePath);
		const resolvedTarget = path.resolve(path.dirname(sourcePath), linkTarget);
		if (!pathIsWithin(root, resolvedTarget)) return false;
		await fs.symlink(linkTarget, targetPath);
		return true;
	}
	if (!stat.isFile()) return false;
	await fs.copyFile(sourcePath, targetPath, copyFlagForStrategy(strategy));
	await fs.chmod(targetPath, stat.mode);
	return true;
}

async function firstRegularFile(sourceRoot: string, files: readonly string[]): Promise<string | undefined> {
	for (const relativePath of files) {
		const sourcePath = path.resolve(sourceRoot, relativePath);
		const stat = await fs.lstat(sourcePath).catch(error => {
			if (isEnoent(error)) return null;
			throw error;
		});
		if (stat?.isFile()) return sourcePath;
	}
	return undefined;
}

function copyFlagForStrategy(strategy: CopyStrategy): number | undefined {
	return strategy === "reflink" ? fsSync.constants.COPYFILE_FICLONE_FORCE : undefined;
}

function isReflinkUnsupportedError(error: unknown): boolean {
	if (!(error instanceof Error) || !("code" in error)) return false;
	const code = error.code;
	return code === "ENOTSUP" || code === "EOPNOTSUPP" || code === "ENOSYS" || code === "EINVAL" || code === "EXDEV";
}
