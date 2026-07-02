import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { type OkfCommandArgs, runOkfCommand } from "@pk-nerdsaver-ai/pi-coding-agent/cli/okf-cli";

let stdout = "";
let stderr = "";

const originalStdoutWrite = process.stdout.write.bind(process.stdout);
const originalStderrWrite = process.stderr.write.bind(process.stderr);
const originalExitCode = process.exitCode;

function captureStreams(): void {
	stdout = "";
	stderr = "";
	process.exitCode = 0;
	process.stdout.write = ((chunk: string | Uint8Array) => {
		stdout += Bun.stripANSI(chunk.toString());
		return true;
	}) as typeof process.stdout.write;
	process.stderr.write = ((chunk: string | Uint8Array) => {
		stderr += Bun.stripANSI(chunk.toString());
		return true;
	}) as typeof process.stderr.write;
}

function restoreStreams(): void {
	process.stdout.write = originalStdoutWrite;
	process.stderr.write = originalStderrWrite;
	process.exitCode = originalExitCode;
}

const tempRoots: string[] = [];

function makeBundle(): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "okf-cli-test-"));
	tempRoots.push(dir);
	return dir;
}

function writeConcept(
	bundleRoot: string,
	relativePath: string,
	frontmatter: Record<string, unknown>,
	body: string,
): void {
	const fullPath = path.join(bundleRoot, relativePath);
	fs.mkdirSync(path.dirname(fullPath), { recursive: true });
	const yaml = Object.entries(frontmatter)
		.map(([k, v]) => {
			if (Array.isArray(v)) return `${k}: [${v.map(item => JSON.stringify(item)).join(", ")}]`;
			if (typeof v === "string") return `${k}: ${JSON.stringify(v)}`;
			return `${k}: ${String(v)}`;
		})
		.join("\n");
	fs.writeFileSync(fullPath, `---\n${yaml}\n---\n\n${body}\n`, "utf8");
}

beforeEach(() => {
	tempRoots.length = 0;
	captureStreams();
});

afterEach(() => {
	restoreStreams();
	for (const dir of tempRoots.splice(0)) {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});

function argsFor(overrides: Partial<OkfCommandArgs>): OkfCommandArgs {
	return {
		action: "list",
		flags: {},
		...overrides,
	};
}

describe("okf-cli list", () => {
	it("prints every discovered concept with its title and description", async () => {
		const projectRoot = makeBundle();
		writeConcept(
			path.join(projectRoot, ".wiki"),
			"tables/orders.md",
			{ type: "BigQuery Table", title: "Orders", description: "Order rows" },
			"body",
		);

		await runOkfCommand(argsFor({ action: "list", flags: { cwd: projectRoot } }));

		expect(stdout).toContain("tables/orders");
		expect(stdout).toContain("Orders");
		expect(stdout).toContain("Order rows");
		expect(process.exitCode).toBeFalsy();
	});

	it("emits machine-readable JSON when --json is passed", async () => {
		const projectRoot = makeBundle();
		writeConcept(path.join(projectRoot, ".wiki"), "tables/orders.md", { type: "BigQuery Table" }, "body");

		await runOkfCommand(argsFor({ action: "list", flags: { cwd: projectRoot, json: true } }));

		const parsed = JSON.parse(stdout);
		expect(parsed.concepts).toHaveLength(1);
		expect(parsed.concepts[0].id).toBe("tables/orders");
	});

	it("reports no concepts found for an empty bundle", async () => {
		const projectRoot = makeBundle();

		await runOkfCommand(argsFor({ action: "list", flags: { cwd: projectRoot } }));

		expect(stdout).toContain("No OKF concepts found");
	});
});

describe("okf-cli show", () => {
	it("prints the concept body and resolved links", async () => {
		const projectRoot = makeBundle();
		writeConcept(
			path.join(projectRoot, ".wiki"),
			"tables/orders.md",
			{ type: "BigQuery Table", title: "Orders" },
			"See [customers](/tables/customers.md).",
		);
		writeConcept(path.join(projectRoot, ".wiki"), "tables/customers.md", { type: "BigQuery Table" }, "body");

		await runOkfCommand(argsFor({ action: "show", id: "tables/orders", flags: { cwd: projectRoot } }));

		expect(stdout).toContain("Orders");
		expect(stdout).toContain("See [customers]");
		expect(stdout).toContain("tables/customers");
	});

	it("throws a usage error when no id is provided", async () => {
		const projectRoot = makeBundle();
		await expect(runOkfCommand(argsFor({ action: "show", flags: { cwd: projectRoot } }))).rejects.toThrow(
			"Usage: omp okf show",
		);
	});

	it("throws a not-found error for an unknown id", async () => {
		const projectRoot = makeBundle();
		await expect(
			runOkfCommand(argsFor({ action: "show", id: "does/not-exist", flags: { cwd: projectRoot } })),
		).rejects.toThrow('No OKF concept found with id "does/not-exist"');
	});
});

describe("okf-cli lint", () => {
	it("reports clean conformance and exits 0 for a valid bundle", async () => {
		const projectRoot = makeBundle();
		writeConcept(path.join(projectRoot, ".wiki"), "tables/orders.md", { type: "BigQuery Table" }, "body");

		await runOkfCommand(argsFor({ action: "lint", flags: { cwd: projectRoot } }));

		expect(stdout).toContain("conform to OKF v0.1");
		expect(process.exitCode).toBeFalsy();
	});

	it("reports errors and sets a non-zero exit code for a missing type field", async () => {
		const projectRoot = makeBundle();
		fs.mkdirSync(path.join(projectRoot, ".wiki"), { recursive: true });
		fs.writeFileSync(path.join(projectRoot, ".wiki/broken.md"), "---\ntitle: no type\n---\nbody", "utf8");

		await runOkfCommand(argsFor({ action: "lint", flags: { cwd: projectRoot } }));

		expect(stderr).toContain("missing required");
		expect(process.exitCode).toBe(1);
	});

	it("emits machine-readable JSON with load and lint warnings", async () => {
		const projectRoot = makeBundle();
		writeConcept(
			path.join(projectRoot, ".wiki"),
			"tables/orders.md",
			{ type: "BigQuery Table", timestamp: "not-a-date" },
			"body",
		);

		await runOkfCommand(argsFor({ action: "lint", flags: { cwd: projectRoot, json: true } }));

		const parsed = JSON.parse(stdout);
		expect(parsed.lintWarnings.some((w: { message: string }) => w.message.includes("ISO 8601"))).toBe(true);
	});
});
