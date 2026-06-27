export const WORKSPACE_MODES = ["auto", "copy", "worktree"] as const;
export type WorkspaceMode = (typeof WORKSPACE_MODES)[number];
export const WORKSPACE_ACTUAL_MODES = ["copy", "reflink-copy", "worktree"] as const;
export type WorkspaceActualMode = (typeof WORKSPACE_ACTUAL_MODES)[number];

export const ETHEREAL_DIR = ".ethereal";
export const ETHEREAL_SECRETS_DIR = "secrets";
export const ETHEREAL_BASELINE_DIR = "baseline";
export const ETHEREAL_MANIFEST = "manifest.json";

export const DEFAULT_ENV_FILES = [".env", ".env.local", ".env.development", ".env.test"] as const;

export const DEFAULT_EXCLUDED_PATHS = [
	".git",
	"node_modules",
	".venv",
	"venv",
	"__pycache__",
	".pytest_cache",
	".ruff_cache",
	".mypy_cache",
	"dist",
	"build",
	"target",
	"coverage",
	".next",
	".turbo",
	".cache",
	".DS_Store",
] as const;

export const DEFAULT_SECRET_BASENAMES = [".npmrc", ".pypirc", ".netrc", ".dockercfg"] as const;

export type EtherealManifestStatus = "created" | "running" | "completed" | "failed" | "cleaned" | "preserved";

export interface ResolvedWorkspaceOptions {
	readonly enabled: boolean;
	readonly mode: WorkspaceMode;
	readonly root: string;
	readonly preserve: boolean;
	readonly copyEnv: boolean;
	readonly envFiles: readonly string[];
	readonly secretFiles: readonly string[];
	readonly secretAllowlist: string | undefined;
	readonly exportPatch: string | undefined;
	readonly name: string | undefined;
}

export interface CreateEtherealWorkspaceRequest {
	readonly sourceCwd: string;
	readonly rawArgs: readonly string[];
	readonly options: ResolvedWorkspaceOptions;
}

export interface CopiedSecretsResult {
	readonly copiedEnvFiles: readonly string[];
	readonly copiedSecretFiles: readonly string[];
	readonly sensitiveRelativePaths: readonly string[];
}

export interface WorkspaceManifest {
	readonly id: string;
	readonly createdAt: string;
	readonly sourceRepo: string;
	readonly workspacePath: string;
	readonly workspaceMode: WorkspaceMode;
	readonly actualWorkspaceMode: WorkspaceActualMode;
	readonly preserveWorkspace: boolean;
	readonly copiedEnvFiles: readonly string[];
	readonly copiedSecretFiles: readonly string[];
	readonly excludedPaths: readonly string[];
	readonly agentCommand: string;
	readonly status: EtherealManifestStatus;
}

export interface EtherealFinishResult {
	readonly workspacePath: string;
	readonly patchPath: string | undefined;
	readonly preserved: boolean;
}

export interface ActiveEtherealWorkspace {
	readonly id: string;
	readonly sourceCwd: string;
	readonly sourceRoot: string;
	readonly workspaceRoot: string;
	readonly workspacePath: string;
	readonly runCwd: string;
	finish(status: "completed" | "failed"): Promise<EtherealFinishResult>;
}
