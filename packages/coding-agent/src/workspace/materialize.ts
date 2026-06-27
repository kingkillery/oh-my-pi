import * as fs from "node:fs/promises";
import * as path from "node:path";
import * as git from "../utils/git";
import {
	type CopyStrategy,
	collectCopyableSourceFiles,
	copyRepository,
	copyRepositoryFiles,
	supportsReflinkCopy,
} from "./copy";
import { defaultExcludeGlobs, shouldCopyDefaultPath } from "./paths";
import { ETHEREAL_DIR, type WorkspaceActualMode, type WorkspaceMode } from "./types";

export type WorkspaceCleanup =
	| { readonly kind: "directory" }
	| { readonly kind: "git-worktree"; readonly sourceRoot: string };

export interface MaterializeWorkspaceRequest {
	readonly sourceRoot: string;
	readonly workspaceRoot: string;
	readonly workspacePath: string;
	readonly mode: WorkspaceMode;
}

export interface MaterializedWorkspace {
	readonly actualMode: WorkspaceActualMode;
	readonly copiedFiles: readonly string[];
	readonly cleanup: WorkspaceCleanup;
	readonly forceFallbackPatch: boolean;
}

export async function materializeWorkspace(request: MaterializeWorkspaceRequest): Promise<MaterializedWorkspace> {
	if (request.mode === "copy") return materializeCopy(request, "copy", "copy");
	if (request.mode === "worktree") return materializeGitWorktree(request);
	return materializeAuto(request);
}

export async function removeMaterializedWorkspace(workspacePath: string, cleanup: WorkspaceCleanup): Promise<void> {
	if (cleanup.kind === "directory") {
		await fs.rm(workspacePath, { recursive: true, force: true });
		return;
	}
	const removed = await git.worktree.tryRemove(cleanup.sourceRoot, workspacePath, { force: true });
	if (removed) return;
	await fs.rm(workspacePath, { recursive: true, force: true });
	await git.worktree.prune(cleanup.sourceRoot);
}

async function materializeAuto(request: MaterializeWorkspaceRequest): Promise<MaterializedWorkspace> {
	if (!(await isGitRepositoryRoot(request.sourceRoot))) return materializeCopy(request, "copy", "copy");
	if (await supportsReflinkCopy(request.sourceRoot, request.workspaceRoot)) {
		return materializeCopy(request, "reflink", "reflink-copy");
	}
	return materializeGitWorktree(request);
}

async function materializeCopy(
	request: MaterializeWorkspaceRequest,
	strategy: CopyStrategy,
	actualMode: WorkspaceActualMode,
): Promise<MaterializedWorkspace> {
	const copyResult = await copyRepository(request.sourceRoot, request.workspacePath, strategy);
	return {
		actualMode,
		copiedFiles: copyResult.copiedFiles,
		cleanup: { kind: "directory" },
		forceFallbackPatch: false,
	};
}

async function materializeGitWorktree(request: MaterializeWorkspaceRequest): Promise<MaterializedWorkspace> {
	if (!(await isGitRepositoryRoot(request.sourceRoot))) {
		throw new Error("Ethereal workspace worktree mode requires a Git repository.");
	}
	await fs.rm(request.workspacePath, { recursive: true, force: true });
	try {
		await git.worktree.add(request.sourceRoot, request.workspacePath, "HEAD", { detach: true });
		await removeExcludedTrackedFiles(request.sourceRoot, request.workspacePath);
		await applyDirtyOverlay(request.sourceRoot, request.workspacePath);
		return {
			actualMode: "worktree",
			copiedFiles: await collectCopyableSourceFiles(request.sourceRoot),
			cleanup: { kind: "git-worktree", sourceRoot: request.sourceRoot },
			forceFallbackPatch: true,
		};
	} catch (error) {
		await git.worktree.tryRemove(request.sourceRoot, request.workspacePath, { force: true });
		await fs.rm(request.workspacePath, { recursive: true, force: true });
		throw error;
	}
}

async function isGitRepositoryRoot(sourceRoot: string): Promise<boolean> {
	const gitRoot = await git.repo.root(sourceRoot).catch(error => {
		if (error instanceof Error) return null;
		throw error;
	});
	return gitRoot !== null && path.resolve(gitRoot) === path.resolve(sourceRoot);
}

async function removeExcludedTrackedFiles(sourceRoot: string, workspacePath: string): Promise<void> {
	const tracked = await git.ls.files(sourceRoot);
	await Promise.all(
		tracked
			.filter(file => !shouldCopyDefaultPath(file))
			.map(async file => {
				await fs.rm(path.join(workspacePath, file), { recursive: true, force: true });
			}),
	);
}

async function applyDirtyOverlay(sourceRoot: string, workspacePath: string): Promise<void> {
	const pathspecs = safeGitPathspecs();
	const stagedPatch = await git.diff(sourceRoot, { binary: true, cached: true, files: pathspecs });
	await git.patch.applyText(workspacePath, stagedPatch);
	const unstagedPatch = await git.diff(sourceRoot, { binary: true, files: pathspecs });
	await git.patch.applyText(workspacePath, unstagedPatch);
	await copyRepositoryFiles(sourceRoot, workspacePath, await git.ls.untracked(sourceRoot));
}

function safeGitPathspecs(): string[] {
	return [
		".",
		`:(exclude)${ETHEREAL_DIR}`,
		`:(exclude)${ETHEREAL_DIR}/**`,
		":(glob,exclude)**/.env",
		":(glob,exclude)**/.env.*",
		":(glob,exclude)**/.npmrc",
		":(glob,exclude)**/.pypirc",
		":(glob,exclude)**/.netrc",
		":(glob,exclude)**/.dockercfg",
		":(glob,exclude)**/dev-secrets.json",
		...defaultExcludeGlobs().map(item => `:(glob,exclude)${item}`),
	];
}
