import * as fs from "node:fs/promises";
import * as path from "node:path";
import { isEnoent, pathIsWithin, Snowflake } from "@pk-nerdsaver-ai/pi-utils";
import { createFallbackBaseline, resolveSourceRepository } from "./copy";
import { readManifest, updateManifestStatus, writeManifest } from "./manifest";
import { materializeWorkspace, removeMaterializedWorkspace, type WorkspaceCleanup } from "./materialize";
import { exportWorkspacePatch, initializeGitBaseline } from "./patch";
import { sanitizeWorkspaceName, toPosixRelative } from "./paths";
import { summarizeAgentCommand } from "./redaction";
import { copyAllowedSecrets } from "./secrets";
import {
	type ActiveEtherealWorkspace,
	type CreateEtherealWorkspaceRequest,
	DEFAULT_EXCLUDED_PATHS,
	ETHEREAL_BASELINE_DIR,
	ETHEREAL_DIR,
	type EtherealFinishResult,
	type WorkspaceManifest,
} from "./types";

export async function createEtherealWorkspace(
	request: CreateEtherealWorkspaceRequest,
): Promise<ActiveEtherealWorkspace> {
	const { sourceRoot, sourceRelativeCwd } = await resolveSourceRepository(request.sourceCwd);
	const workspaceRoot = path.resolve(request.options.root);
	const id = createWorkspaceId();
	const workspacePath = path.join(workspaceRoot, `${id}-${sanitizeWorkspaceName(request.options.name)}`);
	const etherealPath = path.join(workspacePath, ETHEREAL_DIR);
	const baselinePath = path.join(etherealPath, ETHEREAL_BASELINE_DIR);
	const createdAt = new Date().toISOString();
	let sensitiveRelativePaths: readonly string[] = [];
	let workspaceCleanup: WorkspaceCleanup = { kind: "directory" };
	let forceFallbackPatch = false;
	let finishResult: EtherealFinishResult | undefined;
	await fs.mkdir(etherealPath, { recursive: true });
	await writeManifest(workspacePath, initialManifest(id, createdAt, sourceRoot, workspacePath, request, "copy"));
	try {
		const materialized = await materializeWorkspace({
			sourceRoot,
			workspaceRoot,
			workspacePath,
			mode: request.options.mode,
		});
		workspaceCleanup = materialized.cleanup;
		await writeManifest(
			workspacePath,
			initialManifest(id, createdAt, sourceRoot, workspacePath, request, materialized.actualMode),
		);
		forceFallbackPatch = materialized.forceFallbackPatch;
		if (request.options.exportPatch) {
			if (forceFallbackPatch) {
				await fs.mkdir(baselinePath, { recursive: true });
				await createFallbackBaseline(workspacePath, baselinePath, materialized.copiedFiles);
			} else {
				const hasGitBaseline = await initializeGitBaseline(workspacePath);
				if (!hasGitBaseline) {
					await fs.mkdir(baselinePath, { recursive: true });
					await createFallbackBaseline(workspacePath, baselinePath, materialized.copiedFiles);
					forceFallbackPatch = true;
				}
			}
		}
		const secrets = await copyAllowedSecrets(sourceRoot, workspacePath, request.options);
		sensitiveRelativePaths = secrets.sensitiveRelativePaths;
		await writeManifest(workspacePath, {
			...initialManifest(id, createdAt, sourceRoot, workspacePath, request, materialized.actualMode),
			copiedEnvFiles: secrets.copiedEnvFiles,
			copiedSecretFiles: secrets.copiedSecretFiles,
			status: "running",
		});
	} catch (error) {
		await safeRemoveWorkspace(workspaceRoot, workspacePath, workspaceCleanup);
		throw error;
	}

	const runCwd = sourceRelativeCwd ? path.join(workspacePath, sourceRelativeCwd) : workspacePath;
	return {
		id,
		sourceCwd: path.resolve(request.sourceCwd),
		sourceRoot,
		workspaceRoot,
		workspacePath,
		runCwd,
		finish: async status => {
			if (finishResult) return finishResult;
			await updateManifestStatus(workspacePath, status);
			let patchPath: string | undefined;
			let patchError: unknown;
			try {
				patchPath = await exportWorkspacePatch(
					workspacePath,
					path.resolve(request.sourceCwd),
					request.options,
					sensitiveRelativePaths,
					forceFallbackPatch,
				);
			} catch (error) {
				patchError = error instanceof Error ? error : new Error(String(error));
			}
			if (request.options.preserve) {
				await updateManifestStatus(workspacePath, "preserved");
				finishResult = { workspacePath, patchPath, preserved: true };
			} else {
				await updateManifestStatus(workspacePath, "cleaned");
				await safeRemoveWorkspace(workspaceRoot, workspacePath, workspaceCleanup);
				finishResult = { workspacePath, patchPath, preserved: false };
			}
			if (patchError) throw patchError;
			return finishResult;
		},
	};
}

function initialManifest(
	id: string,
	createdAt: string,
	sourceRoot: string,
	workspacePath: string,
	request: CreateEtherealWorkspaceRequest,
	actualMode: WorkspaceManifest["actualWorkspaceMode"],
): WorkspaceManifest {
	return {
		id,
		createdAt,
		sourceRepo: sourceRoot,
		workspacePath,
		workspaceMode: request.options.mode,
		actualWorkspaceMode: actualMode,
		preserveWorkspace: request.options.preserve,
		copiedEnvFiles: [],
		copiedSecretFiles: [],
		excludedPaths: [...DEFAULT_EXCLUDED_PATHS],
		agentCommand: summarizeAgentCommand(request.rawArgs),
		status: "created",
	};
}

function createWorkspaceId(): string {
	const date = new Date().toISOString().slice(0, 10).replaceAll("-", "");
	return `ethereal-${date}-${Snowflake.next().slice(-6)}`;
}

async function safeRemoveWorkspace(
	workspaceRoot: string,
	workspacePath: string,
	workspaceCleanup: WorkspaceCleanup,
): Promise<void> {
	if (!pathIsWithin(workspaceRoot, workspacePath) || path.resolve(workspaceRoot) === path.resolve(workspacePath)) {
		throw new Error(`Refusing to delete unsafe Ethereal workspace path: ${workspacePath}`);
	}
	const manifest = await readManifest(workspacePath).catch(error => {
		if (isEnoent(error)) return null;
		throw error;
	});
	if (!manifest) return;
	if (!manifest.id.startsWith("ethereal-")) {
		throw new Error(`Refusing to delete workspace without Ethereal manifest: ${workspacePath}`);
	}
	await removeMaterializedWorkspace(workspacePath, workspaceCleanup);
}

export function formatEtherealSummary(result: EtherealFinishResult): string {
	const patchLine = result.patchPath ? result.patchPath : "none";
	return [
		"Ethereal workspace completed.",
		`Workspace: ${toPosixRelative(result.workspacePath)}`,
		`Patch: ${toPosixRelative(patchLine)}`,
		`Preserved: ${result.preserved ? "true" : "false"}`,
		"",
	].join("\n");
}
