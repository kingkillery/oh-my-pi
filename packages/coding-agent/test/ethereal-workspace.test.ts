import { afterEach, describe, expect, it } from "bun:test";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { parseArgs } from "@pk-nerdsaver-ai/pi-coding-agent/cli/args";
import { Settings } from "@pk-nerdsaver-ai/pi-coding-agent/config/settings";
import { runRootCommand } from "@pk-nerdsaver-ai/pi-coding-agent/main";
import type { CreateAgentSessionOptions, CreateAgentSessionResult } from "@pk-nerdsaver-ai/pi-coding-agent/sdk";
import type { AgentSession } from "@pk-nerdsaver-ai/pi-coding-agent/session/agent-session";
import { AuthStorage } from "@pk-nerdsaver-ai/pi-coding-agent/session/auth-storage";
import {
	createEtherealWorkspace,
	type ResolvedWorkspaceOptions,
	redactSecretLikeValues,
} from "@pk-nerdsaver-ai/pi-coding-agent/workspace";
import { isEnoent, normalizePathForComparison, pathIsWithin, setProjectDir, TempDir } from "@pk-nerdsaver-ai/pi-utils";

const originalProjectDir = process.cwd();

afterEach(() => {
	setProjectDir(originalProjectDir);
});

async function exists(filePath: string): Promise<boolean> {
	try {
		await fs.stat(filePath);
		return true;
	} catch (error) {
		if (isEnoent(error)) return false;
		throw error;
	}
}

async function runGit(cwd: string, args: readonly string[]): Promise<string> {
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
	if (exitCode !== 0) {
		throw new Error(`git ${args.join(" ")} failed: ${stderr.trim() || stdout.trim()}`);
	}
	return stdout;
}

function createFakeSessionResult(): CreateAgentSessionResult {
	return {
		session: {} as unknown as AgentSession,
		extensionsResult: {
			extensions: [],
			runtime: { flagValues: new Map() },
		},
		setToolUIContext: () => {},
		eventBus: {},
	} as unknown as CreateAgentSessionResult;
}

async function makeSourceRepo(root: string): Promise<string> {
	const source = path.join(root, "source repo");
	await fs.mkdir(path.join(source, "src"), { recursive: true });
	await Bun.write(path.join(source, "README.md"), "# demo\n");
	await Bun.write(path.join(source, "src", "index.ts"), "export const value = 1;\n");
	await Bun.write(path.join(source, ".env"), "OPENAI_API_KEY=sk-secret\n");
	await Bun.write(path.join(source, ".env.local"), "LOCAL_TOKEN=secret\n");
	await fs.mkdir(path.join(source, "node_modules", "pkg"), { recursive: true });
	await Bun.write(path.join(source, "node_modules", "pkg", "index.js"), "module.exports = 1;\n");
	await fs.mkdir(path.join(source, ".cache"), { recursive: true });
	await Bun.write(path.join(source, ".cache", "artifact.txt"), "cache\n");
	return source;
}

async function makeGitSourceRepo(root: string): Promise<string> {
	const source = await makeSourceRepo(root);
	await runGit(source, ["init", "-q"]);
	await runGit(source, ["config", "user.email", "ethereal@example.test"]);
	await runGit(source, ["config", "user.name", "Ethereal Test"]);
	await runGit(source, ["add", "README.md", "src/index.ts"]);
	await runGit(source, ["commit", "-qm", "init"]);
	return source;
}

function workspaceOptions(root: string, overrides: Partial<ResolvedWorkspaceOptions> = {}): ResolvedWorkspaceOptions {
	return {
		enabled: true,
		mode: "copy",
		root,
		preserve: false,
		copyEnv: false,
		envFiles: [],
		secretFiles: [],
		secretAllowlist: undefined,
		exportPatch: undefined,
		name: undefined,
		...overrides,
	};
}

describe("parseArgs — Ethereal Workspaces flags", () => {
	it("parses workspace flags without leaking values into the prompt", () => {
		const result = parseArgs([
			"--ethereal",
			"--workspace-mode",
			"copy",
			"--workspace-root=/tmp/omp workspaces",
			"--preserve-workspace",
			"--copy-env",
			"--env-file",
			".env.local",
			"--copy-secret",
			"~/.npmrc",
			"--secret-allowlist",
			"secrets.allow",
			"--export-patch",
			"out.patch",
			"--workspace-name",
			"fix tests",
			"hello",
		]);

		expect(result.ethereal).toBe(true);
		expect(result.workspaceMode).toBe("copy");
		expect(parseArgs(["--workspace-mode", "auto"]).workspaceMode).toBe("auto");
		expect(parseArgs(["--workspace-mode", "worktree"]).workspaceMode).toBe("worktree");
		expect(result.workspaceRoot).toBe("/tmp/omp workspaces");
		expect(result.preserveWorkspace).toBe(true);
		expect(result.copyEnv).toBe(true);
		expect(result.envFiles).toEqual([".env.local"]);
		expect(result.secretFiles).toEqual(["~/.npmrc"]);
		expect(result.secretAllowlist).toBe("secrets.allow");
		expect(result.exportPatch).toBe("out.patch");
		expect(result.workspaceName).toBe("fix tests");
		expect(result.messages).toEqual(["hello"]);
	});
});

describe("Ethereal Workspaces lifecycle", () => {
	it("copies normal files, excludes caches, omits env files by default, writes a manifest, and cleans up", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-");
		const source = await makeSourceRepo(tempDir.path());
		const root = path.join(tempDir.path(), "workspaces");

		const workspace = await createEtherealWorkspace({
			sourceCwd: source,
			rawArgs: ["--ethereal", "--print", "inspect"],
			options: workspaceOptions(root),
		});
		const workspacePath = workspace.workspacePath;

		expect(await exists(path.join(workspacePath, "src", "index.ts"))).toBe(true);
		expect(await exists(path.join(workspacePath, "node_modules", "pkg", "index.js"))).toBe(false);
		expect(await exists(path.join(workspacePath, ".cache", "artifact.txt"))).toBe(false);
		expect(await exists(path.join(workspacePath, ".env"))).toBe(false);
		const manifest = await Bun.file(path.join(workspacePath, ".ethereal", "manifest.json")).json();
		expect(manifest.status).toBe("running");
		expect(manifest.workspaceMode).toBe("copy");
		expect(manifest.copiedEnvFiles).toEqual([]);

		await workspace.finish("completed");

		expect(await exists(workspacePath)).toBe(false);
	});

	it("uses plain copy mode for auto mode outside a Git repository", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-auto-copy-");
		const source = await makeSourceRepo(tempDir.path());
		const workspace = await createEtherealWorkspace({
			sourceCwd: source,
			rawArgs: ["--ethereal", "--workspace-mode", "auto"],
			options: workspaceOptions(path.join(tempDir.path(), "workspaces"), { mode: "auto", preserve: true }),
		});

		const manifest = await Bun.file(path.join(workspace.workspacePath, ".ethereal", "manifest.json")).json();
		expect(manifest.workspaceMode).toBe("auto");
		expect(manifest.actualWorkspaceMode).toBe("copy");

		await workspace.finish("completed");
	});

	it("materializes explicit worktree mode with dirty tracked and untracked files overlaid", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-worktree-");
		const source = await makeGitSourceRepo(tempDir.path());
		await Bun.write(path.join(source, "README.md"), "# demo\n\nsource dirty\n");
		await Bun.write(path.join(source, "src", "new.ts"), "export const added = true;\n");
		const workspace = await createEtherealWorkspace({
			sourceCwd: source,
			rawArgs: ["--ethereal", "--workspace-mode", "worktree"],
			options: workspaceOptions(path.join(tempDir.path(), "workspaces"), { mode: "worktree" }),
		});
		const workspacePath = workspace.workspacePath;

		const manifest = await Bun.file(path.join(workspacePath, ".ethereal", "manifest.json")).json();
		expect(manifest.workspaceMode).toBe("worktree");
		expect(manifest.actualWorkspaceMode).toBe("worktree");
		expect(await Bun.file(path.join(workspacePath, "README.md")).text()).toContain("source dirty");
		expect(await exists(path.join(workspacePath, "src", "new.ts"))).toBe(true);
		expect(await exists(path.join(workspacePath, ".env"))).toBe(false);

		await workspace.finish("completed");

		expect(await exists(workspacePath)).toBe(false);
	});

	it("auto mode uses a Git strategy for Git repositories and keeps the source working tree overlay", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-auto-git-");
		const source = await makeGitSourceRepo(tempDir.path());
		await Bun.write(path.join(source, "README.md"), "# demo\n\nauto dirty\n");
		await Bun.write(path.join(source, "src", "auto-untracked.ts"), "export const auto = true;\n");
		const workspace = await createEtherealWorkspace({
			sourceCwd: source,
			rawArgs: ["--ethereal", "--workspace-mode", "auto"],
			options: workspaceOptions(path.join(tempDir.path(), "workspaces"), { mode: "auto", preserve: true }),
		});

		const manifest = await Bun.file(path.join(workspace.workspacePath, ".ethereal", "manifest.json")).json();
		expect(manifest.workspaceMode).toBe("auto");
		expect(["reflink-copy", "worktree"]).toContain(manifest.actualWorkspaceMode);
		expect(await Bun.file(path.join(workspace.workspacePath, "README.md")).text()).toContain("auto dirty");
		expect(await exists(path.join(workspace.workspacePath, "src", "auto-untracked.ts"))).toBe(true);
		expect(await exists(path.join(workspace.workspacePath, ".env"))).toBe(false);

		await workspace.finish("completed");
	});

	it("copies env files only when explicitly enabled", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-env-");
		const source = await makeSourceRepo(tempDir.path());
		const workspace = await createEtherealWorkspace({
			sourceCwd: source,
			rawArgs: ["--ethereal"],
			options: workspaceOptions(path.join(tempDir.path(), "workspaces"), { copyEnv: true, preserve: true }),
		});

		expect(await exists(path.join(workspace.workspacePath, ".env"))).toBe(true);
		expect(await exists(path.join(workspace.workspacePath, ".env.local"))).toBe(true);
		const manifest = await Bun.file(path.join(workspace.workspacePath, ".ethereal", "manifest.json")).json();
		expect(manifest.copiedEnvFiles).toEqual([".env", ".env.local"]);

		await workspace.finish("completed");
	});

	it("refuses repo env symlinks that point outside the source repository", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-env-symlink-");
		const source = await makeSourceRepo(tempDir.path());
		const outsideEnv = path.join(tempDir.path(), "outside.env");
		await Bun.write(outsideEnv, "OPENAI_API_KEY=sk-outside\n");
		await fs.rm(path.join(source, ".env"));
		try {
			await fs.symlink(outsideEnv, path.join(source, ".env"));
		} catch (error) {
			if (error instanceof Error && "code" in error && (error.code === "EPERM" || error.code === "EACCES")) return;
			throw error;
		}

		await expect(
			createEtherealWorkspace({
				sourceCwd: source,
				rawArgs: ["--ethereal", "--copy-env"],
				options: workspaceOptions(path.join(tempDir.path(), "workspaces"), { copyEnv: true }),
			}),
		).rejects.toThrow("symlink target escapes");
	});

	it("refuses repo-relative secret requests reached through a symlinked directory", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-dir-symlink-");
		const source = await makeSourceRepo(tempDir.path());
		const outsideDir = path.join(tempDir.path(), "outside-config");
		await fs.mkdir(outsideDir, { recursive: true });
		await Bun.write(path.join(outsideDir, "secret.env"), "TOKEN=sk-outside\n");
		try {
			await fs.symlink(outsideDir, path.join(source, "config"), "dir");
		} catch (error) {
			if (error instanceof Error && "code" in error && (error.code === "EPERM" || error.code === "EACCES")) return;
			throw error;
		}

		await expect(
			createEtherealWorkspace({
				sourceCwd: source,
				rawArgs: ["--ethereal", "--copy-secret", "config/secret.env"],
				options: workspaceOptions(path.join(tempDir.path(), "workspaces"), {
					secretFiles: ["config/secret.env"],
				}),
			}),
		).rejects.toThrow("symlink target escapes");
	});

	it("copies allowlisted secrets and redacts them in the manifest", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-secret-");
		const source = await makeSourceRepo(tempDir.path());
		const outsideSecret = path.join(tempDir.path(), "outside-npmrc");
		const allowlist = path.join(source, "secrets.allow");
		await Bun.write(path.join(source, ".npmrc"), "//registry.npmjs.org/:_authToken=npm-secret\n");
		await Bun.write(outsideSecret, "machine api.example.com password secret\n");
		await Bun.write(allowlist, [".npmrc", outsideSecret].join("\n"));

		const workspace = await createEtherealWorkspace({
			sourceCwd: source,
			rawArgs: ["--ethereal", "--copy-secret", ".npmrc"],
			options: workspaceOptions(path.join(tempDir.path(), "workspaces"), {
				preserve: true,
				secretFiles: [".npmrc", outsideSecret],
				secretAllowlist: allowlist,
			}),
		});

		expect(await exists(path.join(workspace.workspacePath, ".npmrc"))).toBe(true);
		expect(await exists(path.join(workspace.workspacePath, ".ethereal", "secrets", "outside-npmrc"))).toBe(true);
		const manifestText = await Bun.file(path.join(workspace.workspacePath, ".ethereal", "manifest.json")).text();
		expect(manifestText).toContain('"<redacted>"');
		expect(manifestText).not.toContain("npm-secret");
		expect(manifestText).not.toContain("password secret");

		await workspace.finish("completed");
	});

	it("rejects relative traversal for env and secret paths", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-traversal-");
		const source = await makeSourceRepo(tempDir.path());
		await Bun.write(path.join(tempDir.path(), "outside.env"), "TOKEN=secret\n");

		await expect(
			createEtherealWorkspace({
				sourceCwd: source,
				rawArgs: ["--ethereal", "--env-file", "../outside.env"],
				options: workspaceOptions(path.join(tempDir.path(), "workspaces"), { envFiles: ["../outside.env"] }),
			}),
		).rejects.toThrow("escapes the source repository");
	});

	it("cleans up a worktree when post-materialization secret copying fails", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-worktree-failure-");
		const source = await makeGitSourceRepo(tempDir.path());
		const workspaceRoot = path.join(tempDir.path(), "workspaces");

		await expect(
			createEtherealWorkspace({
				sourceCwd: source,
				rawArgs: ["--ethereal", "--workspace-mode", "worktree", "--copy-secret", "missing.secret"],
				options: workspaceOptions(workspaceRoot, {
					mode: "worktree",
					secretFiles: ["missing.secret"],
				}),
			}),
		).rejects.toThrow("does not exist");

		const worktrees = await runGit(source, ["worktree", "list", "--porcelain"]);
		expect(normalizePathForComparison(worktrees)).not.toContain(normalizePathForComparison(workspaceRoot));
	});

	it("preserves a workspace when requested", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-preserve-");
		const source = await makeSourceRepo(tempDir.path());
		const workspace = await createEtherealWorkspace({
			sourceCwd: source,
			rawArgs: ["--ethereal", "--preserve-workspace"],
			options: workspaceOptions(path.join(tempDir.path(), "workspaces"), { preserve: true }),
		});

		const result = await workspace.finish("completed");
		const manifest = await Bun.file(path.join(workspace.workspacePath, ".ethereal", "manifest.json")).json();

		expect(result.preserved).toBe(true);
		expect(await exists(workspace.workspacePath)).toBe(true);
		expect(manifest.status).toBe("preserved");
	});

	it("exports patches without env or secret files", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-patch-");
		const source = await makeSourceRepo(tempDir.path());
		const patchPath = path.join(tempDir.path(), "agent-output", "fix.patch");
		const workspace = await createEtherealWorkspace({
			sourceCwd: source,
			rawArgs: ["--ethereal", "--export-patch", patchPath],
			options: workspaceOptions(path.join(tempDir.path(), "workspaces"), {
				copyEnv: true,
				exportPatch: patchPath,
				preserve: true,
			}),
		});
		await Bun.write(path.join(workspace.workspacePath, "README.md"), "# demo\n\nchanged\n");
		await Bun.write(path.join(workspace.workspacePath, ".env"), "OPENAI_API_KEY=sk-new-secret\n");

		await workspace.finish("completed");

		const patch = await Bun.file(patchPath).text();
		expect(patch).toContain("README.md");
		expect(patch).toContain("+changed");
		expect(patch).not.toContain("OPENAI_API_KEY");
		expect(patch).not.toContain("sk-new-secret");
	});

	it("exports worktree patches against the source working tree baseline", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-worktree-patch-");
		const source = await makeGitSourceRepo(tempDir.path());
		await Bun.write(path.join(source, "README.md"), "# demo\n\nsource dirty\n");
		const patchPath = path.join(tempDir.path(), "agent-output", "worktree.patch");
		const workspace = await createEtherealWorkspace({
			sourceCwd: source,
			rawArgs: ["--ethereal", "--workspace-mode", "worktree", "--export-patch", patchPath],
			options: workspaceOptions(path.join(tempDir.path(), "workspaces"), {
				mode: "worktree",
				exportPatch: patchPath,
				preserve: true,
			}),
		});
		await Bun.write(path.join(workspace.workspacePath, "agent.txt"), "agent output\n");

		await workspace.finish("completed");

		const patch = await Bun.file(patchPath).text();
		expect(patch).toContain("agent.txt");
		expect(patch).not.toContain("README.md");
		expect(patch).not.toContain("source dirty");
	});
});

describe("Ethereal Workspaces redaction", () => {
	it("redacts secret-looking key values", () => {
		const redacted = redactSecretLikeValues("OPENAI_API_KEY=sk-secret\nname=demo\nSESSION_COOKIE=abc");

		expect(redacted).toContain("OPENAI_API_KEY=<redacted>");
		expect(redacted).toContain("name=demo");
		expect(redacted).toContain("SESSION_COOKIE=<redacted>");
		expect(redacted).not.toContain("sk-secret");
		expect(redacted).not.toContain("abc");
	});
});

describe("runRootCommand — Ethereal Workspaces integration", () => {
	it("creates the session inside a preserved ethereal workspace", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-cli-");
		const source = await makeSourceRepo(tempDir.path());
		const workspaceRoot = path.join(tempDir.path(), "workspaces");
		const authStorage = await AuthStorage.create(path.join(tempDir.path(), "auth.db"));
		const settings = Settings.isolated({ "marketplace.autoUpdate": "off" });
		let observedOptions: CreateAgentSessionOptions | undefined;
		const rawArgs = [
			"--cwd",
			source,
			"--ethereal",
			"--workspace-root",
			workspaceRoot,
			"--preserve-workspace",
			"--print",
			"inspect",
		];
		const parsed = parseArgs(rawArgs);
		parsed.noExtensions = true;
		parsed.noSkills = true;
		parsed.noRules = true;
		parsed.noTools = true;
		parsed.noLsp = true;
		parsed.sessionDir = tempDir.path();

		try {
			await runRootCommand(parsed, rawArgs, {
				discoverAuthStorage: async () => authStorage,
				settings,
				createAgentSession: async options => {
					observedOptions = options;
					throw new Error("stop after ethereal session options");
				},
			});
		} catch (error) {
			if (!(error instanceof Error) || error.message !== "stop after ethereal session options") {
				throw error;
			}
		} finally {
			authStorage.close();
		}

		expect(observedOptions?.cwd).toBeDefined();
		expect(pathIsWithin(workspaceRoot, observedOptions?.cwd ?? "")).toBe(true);
		expect(normalizePathForComparison(process.cwd())).toBe(normalizePathForComparison(source));
		const workspacePath = observedOptions?.cwd ?? "";
		expect(await exists(path.join(workspacePath, ".ethereal", "manifest.json"))).toBe(true);
		expect(await exists(path.join(workspacePath, "README.md"))).toBe(true);
	});

	it("keeps an interactive session rooted in the Ethereal Workspace until the session exits", async () => {
		using tempDir = TempDir.createSync("@omp-ethereal-interactive-");
		const source = await makeGitSourceRepo(tempDir.path());
		const workspaceRoot = path.join(tempDir.path(), "workspaces");
		const authStorage = await AuthStorage.create(path.join(tempDir.path(), "auth.db"));
		const settings = Settings.isolated({ "marketplace.autoUpdate": "off" });
		let observedOptions: CreateAgentSessionOptions | undefined;
		let workspaceDuringSession = "";
		const rawArgs = [
			"--cwd",
			source,
			"--ethereal",
			"--workspace-mode",
			"worktree",
			"--workspace-root",
			workspaceRoot,
			"inspect",
		];
		const parsed = parseArgs(rawArgs);
		parsed.noExtensions = true;
		parsed.noSkills = true;
		parsed.noRules = true;
		parsed.noTools = true;
		parsed.noLsp = true;
		parsed.sessionDir = tempDir.path();

		try {
			await runRootCommand(parsed, rawArgs, {
				discoverAuthStorage: async () => authStorage,
				settings,
				createAgentSession: async options => {
					observedOptions = options;
					return createFakeSessionResult();
				},
				runInteractiveMode: async () => {
					workspaceDuringSession = observedOptions?.cwd ?? "";
					expect(pathIsWithin(workspaceRoot, workspaceDuringSession)).toBe(true);
					expect(await exists(path.join(workspaceDuringSession, ".ethereal", "manifest.json"))).toBe(true);
					await Bun.write(
						path.join(workspaceDuringSession, "session-marker.txt"),
						"interactive session owned this\n",
					);
				},
			});
		} finally {
			authStorage.close();
		}

		expect(workspaceDuringSession).not.toBe("");
		expect(await exists(workspaceDuringSession)).toBe(false);
		expect(normalizePathForComparison(process.cwd())).toBe(normalizePathForComparison(source));
	});
});
