import { describe, expect, it } from "bun:test";
import * as path from "node:path";
import { APP_NAME } from "@pk-nerdsaver-ai/pi-utils";
import {
	installProfileAlias,
	readProfileAliasConfigFile,
	resolveProfileAliasCommandFromProcess,
} from "../src/cli/profile-alias";

// The production code resolves config paths with Node's path.join/path.resolve,
// which emit OS-native separators (backslashes on Windows). The mock filesystem
// is keyed by whatever path the code passes to writeFile, but the assertions use
// POSIX literals, so on Windows the keys never match. Normalizing every key (and
// every direct path assertion) to forward slashes keeps the test host-agnostic
// without touching the production source, which is correct for real use because
// the host OS always equals the simulated `platform`.
const norm = (p: string) => p.replaceAll("\\", "/");

function mockFs(seed: Array<[string, string]> = []) {
	const files = new Map<string, string>(seed.map(([k, v]) => [norm(k), v]));
	return {
		files,
		readFile: async (p: string) => files.get(norm(p)) ?? "",
		writeFile: async (p: string, content: string) => {
			files.set(norm(p), content);
		},
		get: (p: string) => files.get(norm(p)),
	};
}

// Mirror the (unexported) quoting helpers in src/cli/profile-alias.ts so the
// source-invocation expectations stay correct regardless of which separators the
// host's path module produces.
const quoteForShell = (p: string) => `'${p.replace(/'/g, `'"'"'`)}'`;
const quoteForPowerShell = (p: string) => `'${p.replace(/'/g, `''`)}'`;

describe("profile alias installer", () => {
	it("writes a bash-compatible function that forwards subcommands through oh-my-pk", async () => {
		const fs = mockFs();

		const result = await installProfileAlias({
			profile: "work",
			aliasName: "omp-work",
			shellPath: "/bin/bash",
			platform: "linux",
			homeDir: "/home/me",
			readFile: fs.readFile,
			writeFile: fs.writeFile,
		});

		expect(norm(result.configPath)).toBe("/home/me/.bashrc");
		expect(result.command).toBe(`${APP_NAME} --profile=work`);
		expect(fs.get("/home/me/.bashrc")).toContain("omp-work() {");
		expect(fs.get("/home/me/.bashrc")).toContain(`command ${APP_NAME} --profile=work "$@"`);
	});

	it("resolves source invocations without forcing the source checkout as cwd", () => {
		const command = resolveProfileAliasCommandFromProcess(["/bin/bun", "src/cli.ts"], "/repo/packages/coding-agent");

		// path.resolve prepends the current drive letter on Windows, so a POSIX
		// literal can never match; compute the expected value with the host module.
		const expectedScript = path.resolve("/repo/packages/coding-agent", "src/cli.ts");
		const expectedPosix = `${quoteForShell("/bin/bun")} ${quoteForShell(expectedScript)}`;

		expect(command.display).toBe(`/bin/bun ${expectedScript}`);
		expect(command.posix).toBe(expectedPosix);
		expect(command.fish).toBe(expectedPosix);
		expect(command.powerShell).toBe(`${quoteForPowerShell("/bin/bun")} ${quoteForPowerShell(expectedScript)}`);
	});

	it("can target the current source invocation instead of the installed omp binary", async () => {
		const fs = mockFs();

		const result = await installProfileAlias({
			profile: "work",
			aliasName: "omp-work",
			shellPath: "/bin/zsh",
			platform: "darwin",
			homeDir: "/Users/me",
			command: {
				display: "bun /repo/packages/coding-agent/src/cli.ts",
				posix: "bun '/repo/packages/coding-agent/src/cli.ts'",
				fish: "bun /repo/packages/coding-agent/src/cli.ts",
				powerShell: "bun '/repo/packages/coding-agent/src/cli.ts'",
			},
			readFile: fs.readFile,
			writeFile: fs.writeFile,
		});

		expect(result.command).toBe("bun /repo/packages/coding-agent/src/cli.ts --profile=work");
		expect(fs.get("/Users/me/.zshrc")).toContain("omp-work() {");
		expect(fs.get("/Users/me/.zshrc")).toContain(
			`command bun '/repo/packages/coding-agent/src/cli.ts' --profile=work "$@"`,
		);
	});

	it("installs the zsh alias under ZDOTDIR when set", async () => {
		const fs = mockFs();

		const result = await installProfileAlias({
			profile: "work",
			aliasName: "omp-work",
			shellPath: "/bin/zsh",
			platform: "darwin",
			homeDir: "/Users/me",
			env: { ZDOTDIR: "/Users/me/.config/zsh" },
			readFile: fs.readFile,
			writeFile: fs.writeFile,
		});

		expect(norm(result.configPath)).toBe("/Users/me/.config/zsh/.zshrc");
		expect(fs.get(result.configPath)).toContain("omp-work() {");
	});

	it("writes a fish function that forwards argv", async () => {
		const fs = mockFs();

		await installProfileAlias({
			profile: "work",
			aliasName: "omp-work",
			shellPath: "/opt/homebrew/bin/fish",
			platform: "darwin",
			homeDir: "/Users/me",
			env: {},
			readFile: fs.readFile,
			writeFile: fs.writeFile,
		});

		const content = fs.get("/Users/me/.config/fish/conf.d/omp-profiles.fish") ?? "";
		expect(content).toContain(`function omp-work --wraps ${APP_NAME}`);
		expect(content).toContain(`command ${APP_NAME} --profile=work $argv`);
	});

	it("installs the fish alias under XDG_CONFIG_HOME when set", async () => {
		const fs = mockFs();

		const result = await installProfileAlias({
			profile: "work",
			aliasName: "omp-work",
			shellPath: "/usr/bin/fish",
			platform: "linux",
			homeDir: "/home/me",
			env: { XDG_CONFIG_HOME: "/home/me/.dotfiles/config" },
			readFile: fs.readFile,
			writeFile: fs.writeFile,
		});

		expect(norm(result.configPath)).toBe("/home/me/.dotfiles/config/fish/conf.d/omp-profiles.fish");
		expect(fs.get(result.configPath)).toContain(`function omp-work --wraps ${APP_NAME}`);
	});

	it("writes a PowerShell function because aliases cannot carry arguments", async () => {
		const fs = mockFs();

		await installProfileAlias({
			profile: "work",
			aliasName: "omp-work",
			shellPath: "pwsh.exe",
			platform: "win32",
			homeDir: "C:\\Users\\me",
			readFile: fs.readFile,
			writeFile: fs.writeFile,
		});

		const content = fs.get("C:\\Users\\me/Documents/PowerShell/Microsoft.PowerShell_profile.ps1") ?? "";
		expect(content).toContain("function omp-work");
		expect(content).toContain(`& ${APP_NAME} --profile=work @args`);
	});

	it("detects pwsh from PSModulePath when SHELL is unset on Windows", async () => {
		const fs = mockFs();

		const result = await installProfileAlias({
			profile: "work",
			aliasName: "omp-work",
			platform: "win32",
			homeDir: "C:\\Users\\me",
			env: {
				PSModulePath:
					"C:\\Users\\me\\Documents\\PowerShell\\Modules;C:\\Program Files\\PowerShell\\7\\Modules;C:\\Users\\me\\Documents\\WindowsPowerShell\\Modules",
			},
			readFile: fs.readFile,
			writeFile: fs.writeFile,
		});

		expect(result.shell).toBe("pwsh");
		expect(norm(result.configPath)).toBe(norm("C:\\Users\\me/Documents/PowerShell/Microsoft.PowerShell_profile.ps1"));
		expect(fs.get(result.configPath)).toContain(`& ${APP_NAME} --profile=work @args`);
	});

	it("selects Windows PowerShell when only WindowsPowerShell modules are present", async () => {
		const fs = mockFs();

		const result = await installProfileAlias({
			profile: "work",
			aliasName: "omp-work",
			platform: "win32",
			homeDir: "C:\\Users\\me",
			env: {
				PSModulePath:
					"C:\\Users\\me\\Documents\\WindowsPowerShell\\Modules;C:\\WINDOWS\\system32\\WindowsPowerShell\\v1.0\\Modules",
			},
			readFile: fs.readFile,
			writeFile: fs.writeFile,
		});

		expect(result.shell).toBe("powershell");
		expect(norm(result.configPath)).toBe(
			norm("C:\\Users\\me/Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1"),
		);
	});

	it("treats POWERSHELL_DISTRIBUTION_CHANNEL as a pwsh hint when no module paths disambiguate", async () => {
		const fs = mockFs();

		const result = await installProfileAlias({
			profile: "work",
			aliasName: "omp-work",
			platform: "win32",
			homeDir: "C:\\Users\\me",
			env: { POWERSHELL_DISTRIBUTION_CHANNEL: "MSI:Windows 10 Pro" },
			readFile: fs.readFile,
			writeFile: fs.writeFile,
		});

		expect(result.shell).toBe("pwsh");
		expect(norm(result.configPath)).toBe(norm("C:\\Users\\me/Documents/PowerShell/Microsoft.PowerShell_profile.ps1"));
	});

	it("replaces a previous block for the same alias", async () => {
		const fs = mockFs([
			[
				"/home/me/.zshrc",
				[
					"before",
					"# >>> omp profile alias: omp-work >>>",
					"alias omp-work='command omp --profile=old'",
					"# <<< omp profile alias: omp-work <<<",
					"after",
				].join("\n"),
			],
		]);

		await installProfileAlias({
			profile: "work",
			aliasName: "omp-work",
			shellPath: "/bin/zsh",
			platform: "darwin",
			homeDir: "/home/me",
			readFile: fs.readFile,
			writeFile: fs.writeFile,
		});

		const content = fs.get("/home/me/.zshrc") ?? "";
		expect(content).toContain("before");
		expect(content).toContain("after");
		expect(content).toContain(`command ${APP_NAME} --profile=work "$@"`);
		expect(content).not.toContain("--profile=old");
	});

	it("refuses to rewrite a malformed managed block missing its end marker", async () => {
		// A start marker without its matching end marker means a previous install
		// was interrupted or hand-edited. Appending a fresh block would let the
		// *next* install splice from the stale start through the new end, deleting
		// the user config in between. Refuse and preserve the file untouched.
		const original = ["# >>> omp profile alias: omp-work >>>", "omp-work() {", "export SECRET=keepme"].join("\n");
		const fs = mockFs([["/home/me/.zshrc", original]]);
		let wrote = false;

		await expect(
			installProfileAlias({
				profile: "work",
				aliasName: "omp-work",
				shellPath: "/bin/zsh",
				platform: "darwin",
				homeDir: "/home/me",
				readFile: fs.readFile,
				writeFile: async (filePath, content) => {
					wrote = true;
					await fs.writeFile(filePath, content);
				},
			}),
		).rejects.toThrow(/without a matching/);

		expect(wrote).toBe(false);
		expect(fs.get("/home/me/.zshrc")).toBe(original);
	});

	it("refuses to shadow official command names case-insensitively", async () => {
		for (const aliasName of ["oh-my-pk", "OH-MY-PK", "omp", "OMP", "ompk", "OMPK"]) {
			await expect(
				installProfileAlias({
					profile: "work",
					aliasName,
					shellPath: "/bin/bash",
					homeDir: "/home/me",
				}),
			).rejects.toThrow("Refusing to shadow");
		}
	});

	it("rejects shell reserved words before rendering alias functions", async () => {
		for (const { aliasName, shellPath } of [
			{ aliasName: "if", shellPath: "/bin/bash" },
			{ aliasName: "end", shellPath: "/opt/homebrew/bin/fish" },
			{ aliasName: "foreach", shellPath: "pwsh.exe" },
		]) {
			await expect(
				installProfileAlias({
					profile: "work",
					aliasName,
					shellPath,
					platform: shellPath === "pwsh.exe" ? "win32" : "linux",
					homeDir: "/home/me",
				}),
			).rejects.toThrow("reserved word");
		}
	});

	it("rejects POSIX sh because it does not read bash config files", async () => {
		await expect(
			installProfileAlias({
				profile: "work",
				aliasName: "omp-work",
				shellPath: "/bin/sh",
				platform: "linux",
				homeDir: "/home/me",
			}),
		).rejects.toThrow('Unsupported shell "sh"');
	});

	it("treats missing shell config as empty but preserves other read failures", async () => {
		await expect(
			readProfileAliasConfigFile("/home/me/.bashrc", async () => {
				throw Object.assign(new Error("missing"), { code: "ENOENT" });
			}),
		).resolves.toBe("");

		await expect(
			readProfileAliasConfigFile("/home/me/.bashrc", async () => {
				throw Object.assign(new Error("denied"), { code: "EACCES" });
			}),
		).rejects.toThrow("denied");
	});

	it("validates profile names before rendering shell code", async () => {
		const fs = mockFs();

		await expect(
			installProfileAlias({
				profile: "work'; touch /tmp/pwn; #",
				aliasName: "omp-work",
				shellPath: "/bin/bash",
				platform: "linux",
				homeDir: "/home/me",
				readFile: fs.readFile,
				writeFile: fs.writeFile,
			}),
		).rejects.toThrow("Invalid OMP profile");
		expect(fs.files.size).toBe(0);
	});
});
