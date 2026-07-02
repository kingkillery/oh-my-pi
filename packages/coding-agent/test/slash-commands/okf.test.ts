import { afterEach, describe, expect, it } from "bun:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { handleOkfSlashCommand } from "@pk-nerdsaver-ai/pi-coding-agent/slash-commands/helpers/okf";
import type { SlashCommandRuntime } from "@pk-nerdsaver-ai/pi-coding-agent/slash-commands/types";

const tempRoots: string[] = [];

function makeBundle(): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "okf-slash-test-"));
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
		.map(([k, v]) => (typeof v === "string" ? `${k}: ${JSON.stringify(v)}` : `${k}: ${String(v)}`))
		.join("\n");
	fs.writeFileSync(fullPath, `---\n${yaml}\n---\n\n${body}\n`, "utf8");
}

afterEach(() => {
	for (const dir of tempRoots.splice(0)) {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});

function makeRuntime(cwd: string): { runtime: SlashCommandRuntime; outputs: string[] } {
	const outputs: string[] = [];
	const runtime = {
		cwd,
		output: (text: string) => {
			outputs.push(text);
		},
	} as unknown as SlashCommandRuntime;
	return { runtime, outputs };
}

describe("/okf slash command", () => {
	it("defaults to listing concepts when no subcommand is given", async () => {
		const projectRoot = makeBundle();
		writeConcept(
			path.join(projectRoot, ".wiki"),
			"tables/orders.md",
			{ type: "BigQuery Table", title: "Orders" },
			"body",
		);
		const { runtime, outputs } = makeRuntime(projectRoot);

		await handleOkfSlashCommand("", runtime);

		expect(outputs).toHaveLength(1);
		expect(outputs[0]).toContain("tables/orders");
		expect(outputs[0]).toContain("Orders");
	});

	it("shows a concept's body and links for `/okf show <id>`", async () => {
		const projectRoot = makeBundle();
		writeConcept(
			path.join(projectRoot, ".wiki"),
			"tables/orders.md",
			{ type: "BigQuery Table", title: "Orders" },
			"See [customers](/tables/customers.md).",
		);
		writeConcept(path.join(projectRoot, ".wiki"), "tables/customers.md", { type: "BigQuery Table" }, "body");
		const { runtime, outputs } = makeRuntime(projectRoot);

		await handleOkfSlashCommand("show tables/orders", runtime);

		expect(outputs[0]).toContain("Orders");
		expect(outputs[0]).toContain("See [customers]");
		expect(outputs[0]).toContain("tables/customers");
	});

	it("reports a usage message when `show` is given no id", async () => {
		const projectRoot = makeBundle();
		const { runtime, outputs } = makeRuntime(projectRoot);

		await handleOkfSlashCommand("show", runtime);

		expect(outputs[0]).toContain("Usage: /okf show");
	});

	it("reports OKF v0.1 conformance for `/okf lint` on a valid bundle", async () => {
		const projectRoot = makeBundle();
		writeConcept(path.join(projectRoot, ".wiki"), "tables/orders.md", { type: "BigQuery Table" }, "body");
		const { runtime, outputs } = makeRuntime(projectRoot);

		await handleOkfSlashCommand("lint", runtime);

		expect(outputs[0]).toContain("conform to OKF v0.1");
	});

	it("surfaces conformance errors for `/okf lint` on a broken concept", async () => {
		const projectRoot = makeBundle();
		fs.mkdirSync(path.join(projectRoot, ".wiki"), { recursive: true });
		fs.writeFileSync(path.join(projectRoot, ".wiki/broken.md"), "---\ntitle: no type\n---\nbody", "utf8");
		const { runtime, outputs } = makeRuntime(projectRoot);

		await handleOkfSlashCommand("lint", runtime);

		expect(outputs[0]).toContain("missing required");
	});

	it("rejects an unknown subcommand with a usage hint", async () => {
		const projectRoot = makeBundle();
		const { runtime, outputs } = makeRuntime(projectRoot);

		await handleOkfSlashCommand("bogus", runtime);

		expect(outputs[0]).toContain('Unknown /okf subcommand "bogus"');
	});
});
