#!/usr/bin/env bun
/**
 * Build release binaries and publish them to the PRIVATE Hugging Face repo that
 * backs the install endpoint (oh-my-pi.pkking.computer) — no GitHub Actions, no
 * GitHub Releases, no billing.
 *
 * Layout written to the HF repo:
 *   VERSION                         -> the latest tag (e.g. "v16.1.8")
 *   <tag>/omp-linux-x64            (and the other built targets)
 *   <tag>/omp-windows-x64.exe
 *
 * The Cloudflare Worker (infra/install-redirect) serves these to installers.
 *
 * Prerequisites:
 *   - `hf` CLI:  pip install -U huggingface_hub
 *   - env HF_TOKEN  : write-scoped token for the binaries repo
 *   - env HF_REPO   : e.g. "kingkillery/oh-my-pi-binaries" (default below)
 *   - the native toolchain for each requested target (a single host usually only
 *     builds its own platform; darwin needs a Mac).
 *
 * Usage:
 *   HF_TOKEN=hf_xxx bun scripts/publish-binaries-hf.ts                 # host platform, version from package.json
 *   HF_TOKEN=hf_xxx bun scripts/publish-binaries-hf.ts --targets linux-x64,linux-arm64 --tag v16.1.8
 *   bun scripts/publish-binaries-hf.ts --dry-run
 */
import { $ } from "bun";
import * as path from "node:path";
import * as fs from "node:fs/promises";

const repoRoot = path.join(import.meta.dir, "..");
const binariesDir = path.join(repoRoot, "packages", "coding-agent", "binaries");

const isDryRun = process.argv.includes("--dry-run");
const hfRepo = Bun.env.HF_REPO ?? "kingkillery/oh-my-pi-binaries";
const hfRepoType = Bun.env.HF_REPO_TYPE ?? "model";

function arg(flag: string): string | undefined {
	const i = process.argv.indexOf(flag);
	return i >= 0 ? process.argv[i + 1] : undefined;
}

function hostTargetId(): string {
	const arch = process.arch === "arm64" ? "arm64" : "x64";
	switch (process.platform) {
		case "win32":
			return "win32-x64";
		case "darwin":
			return `darwin-${arch}`;
		case "linux":
			return `linux-${arch}`;
		default:
			throw new Error(`Unsupported host platform: ${process.platform}`);
	}
}

async function resolveTag(): Promise<string> {
	const explicit = arg("--tag");
	if (explicit) return explicit.startsWith("v") ? explicit : `v${explicit}`;
	const pkg = await Bun.file(path.join(repoRoot, "packages", "coding-agent", "package.json")).json();
	return `v${pkg.version}`;
}

async function main(): Promise<void> {
	const tag = await resolveTag();
	const targets = arg("--targets") ?? hostTargetId();

	if (!isDryRun && !Bun.env.HF_TOKEN) {
		throw new Error("HF_TOKEN is required (write-scoped Hugging Face token). See script header.");
	}

	console.log(`Publishing oh-my-pi binaries`);
	console.log(`  repo:    ${hfRepo} (${hfRepoType}, private)`);
	console.log(`  tag:     ${tag}`);
	console.log(`  targets: ${targets}`);
	console.log();

	// 1. Build the requested binaries. ci-release-build-binaries.ts writes them to
	//    packages/coding-agent/binaries/ and leaves them there (its reset only
	//    touches embedded-native/bundle source placeholders).
	console.log("Building binaries...");
	const buildArgs = ["scripts/ci-release-build-binaries.ts", "--targets", targets];
	if (isDryRun) buildArgs.push("--dry-run");
	await $`bun ${buildArgs}`.cwd(repoRoot);

	// 2. Stage a VERSION pointer next to the binaries.
	const versionFile = path.join(binariesDir, "VERSION");
	await Bun.write(versionFile, `${tag}\n`);

	const built = (await fs.readdir(binariesDir)).filter(f => f.startsWith("omp-"));
	if (!isDryRun && built.length === 0) {
		throw new Error("No omp-* binaries were produced; aborting upload.");
	}
	console.log(`\nBuilt: ${built.join(", ") || "(none)"}`);

	if (isDryRun) {
		console.log(`\nDRY RUN — would upload:`);
		for (const f of built) console.log(`  ${binariesDir}/${f} -> ${hfRepo}:${tag}/${f}`);
		console.log(`  ${versionFile} -> ${hfRepo}:VERSION`);
		return;
	}

	// 3. Upload binaries under <tag>/ and refresh the VERSION pointer. `hf upload`
	//    handles LFS for the large binaries; HF_TOKEN is read from the env.
	console.log(`\nUploading to ${hfRepo} ...`);
	for (const f of built) {
		await $`hf upload ${hfRepo} ${path.join(binariesDir, f)} ${`${tag}/${f}`} --repo-type ${hfRepoType}`.cwd(repoRoot);
	}
	await $`hf upload ${hfRepo} ${versionFile} VERSION --repo-type ${hfRepoType}`.cwd(repoRoot);

	console.log(`\n✓ Published ${tag} (${built.length} binary/binaries) to private repo ${hfRepo}.`);
	console.log(`  Installs via oh-my-pi.pkking.computer will resolve ${tag}.`);
}

await main();
