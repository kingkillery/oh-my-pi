import { describe, expect, it } from "bun:test";
import {
	conceptIdToPath,
	extractLinks,
	humaniseConceptId,
	lintOkfBundle,
	type OkfConcept,
	parseOkfConcept,
	resolveLinkConceptId,
	toConceptId,
} from "@pk-nerdsaver-ai/pi-coding-agent/okf/parser";

function makeSource(path: string) {
	return {
		provider: "okf",
		providerName: "OKF Knowledge Bundle",
		path,
		level: "project" as const,
	};
}

describe("okf/parser helpers", () => {
	it("humanises concept ids", () => {
		expect(humaniseConceptId("agent-loop-patterns")).toBe("Agent Loop Patterns");
		expect(humaniseConceptId("tables/orders")).toBe("Orders");
		expect(humaniseConceptId("playbooks/data-freshness.md")).toBe("Data Freshness");
	});

	it("converts paths to concept ids and back", () => {
		expect(toConceptId("/tables/users.md")).toBe("tables/users");
		expect(toConceptId("tables/users.md")).toBe("tables/users");
		expect(toConceptId("orders.md")).toBe("orders");
		expect(conceptIdToPath("tables/users")).toBe("tables/users.md");
	});

	it("returns the source directory for relative links", () => {
		expect(resolveLinkConceptId("./orders.md", "tables/users")).toBe("tables/orders");
	});

	it("returns the bundle root for absolute links", () => {
		expect(resolveLinkConceptId("/tables/orders.md", "tables/users")).toBe("tables/orders");
	});

	it("collapses .. segments correctly", () => {
		expect(resolveLinkConceptId("../datasets/sales.md", "tables/users")).toBe("datasets/sales");
	});

	it("resolves external and fragment-only links to undefined", () => {
		expect(resolveLinkConceptId("https://example.com", "orders")).toBeUndefined();
		expect(resolveLinkConceptId("#schema", "orders")).toBeUndefined();
		expect(resolveLinkConceptId("mailto:hi@example.com", "orders")).toBeUndefined();
	});

	it("ignores non-md targets", () => {
		expect(resolveLinkConceptId("tables/", "orders")).toBeUndefined();
		expect(resolveLinkConceptId("tables/orders", "orders")).toBeUndefined();
	});

	it("strips URL fragments before resolving", () => {
		expect(resolveLinkConceptId("/tables/orders.md#schema", "orders")).toBe("tables/orders");
	});

	it("extracts markdown links in document order", () => {
		const links = extractLinks(
			"See the [orders table](/tables/orders.md) and the [customers](./customers.md).",
			"orders",
		);
		expect(links).toHaveLength(2);
		expect(links[1]).toMatchObject({ target: "./customers.md", text: "customers", conceptId: "customers" });
	});
});

describe("parseOkfConcept", () => {
	it("parses a well-formed concept and resolves in-bundle links", () => {
		const raw = `---
type: BigQuery Table
title: Orders
description: One row per completed customer order.
resource: https://example.com/orders
tags: [sales, " critical ", sales]
timestamp: 2026-05-28T14:30:00Z
custom: ignored-but-preserved
---

# Schema

| Column | Type |
|--------|------|
| id | STRING |

See [customers](/tables/customers.md).
`;
		const result = parseOkfConcept(raw, {
			bundleRoot: "/tmp/bundle",
			relativePath: "tables/orders.md",
			source: makeSource("/tmp/bundle/tables/orders.md"),
		});
		expect("error" in result).toBe(false);
		if ("error" in result) return;

		expect(result.concept.id).toBe("tables/orders");
		expect(result.concept.type).toBe("BigQuery Table");
		expect(result.concept.title).toBe("Orders");
		expect(result.concept.description).toBe("One row per completed customer order.");
		expect(result.concept.resource).toBe("https://example.com/orders");
		expect(result.concept.tags).toEqual(["sales", "critical"]);
		expect(result.concept.timestamp).toBe("2026-05-28T14:30:00Z");
		expect(result.concept.links[0]?.conceptId).toBe("tables/customers");
		expect(result.concept.extra?.custom).toBe("ignored-but-preserved");
	});

	it("derives a title from the concept id when frontmatter omits one", () => {
		const raw = `---
type: Metric
---

body`;
		const result = parseOkfConcept(raw, {
			bundleRoot: "/tmp/bundle",
			relativePath: "metrics/weekly-active-users.md",
			source: makeSource("/tmp/bundle/metrics/weekly-active-users.md"),
		});
		expect("error" in result).toBe(false);
		if ("error" in result) return;
		expect(result.concept.title).toBe("Weekly Active Users");
	});

	it("rejects a non-reserved concept missing the required `type` field", () => {
		const result = parseOkfConcept("---\ntitle: nope\n---\nbody", {
			bundleRoot: "/tmp/bundle",
			relativePath: "tables/broken.md",
			source: makeSource("/tmp/bundle/tables/broken.md"),
		});
		expect(result).toEqual({
			error: expect.stringContaining("missing required `type`"),
			reason: "invalid",
		});
	});

	it("accepts a reserved filename (index.md) without requiring a type", () => {
		const raw = `---
okf_version: "0.1"
---

# Concepts

* [orders](tables/orders.md)
`;
		const result = parseOkfConcept(raw, {
			bundleRoot: "/tmp/bundle",
			relativePath: "tables/index.md",
			source: makeSource("/tmp/bundle/tables/index.md"),
		});
		expect("error" in result).toBe(false);
		if ("error" in result) return;
		expect(result.concept.type).toBe("");
		expect(result.concept.okfVersion).toBe("0.1");
	});

	it("captures the bundle version declared on any document, not just the root", () => {
		const result = parseOkfConcept('---\ntype: T\nokf_version: "1.0"\n---\n', {
			bundleRoot: "/tmp/bundle",
			relativePath: "tables/orders.md",
			source: makeSource("/tmp/bundle/tables/orders.md"),
		});
		expect("error" in result).toBe(false);
		if ("error" in result) return;
		expect(result.concept.okfVersion).toBe("1.0");
	});

	it("drops malformed tags silently rather than throwing", () => {
		const raw = `---
type: T
tags: [valid, 42, "", "  ok  ", [nested]]
---

body`;
		const result = parseOkfConcept(raw, {
			bundleRoot: "/tmp/bundle",
			relativePath: "x.md",
			source: makeSource("/tmp/bundle/x.md"),
		});
		expect("error" in result).toBe(false);
		if ("error" in result) return;
		expect(result.concept.tags).toEqual(["valid", "ok"]);
	});

	it("preserves a malformed timestamp verbatim so lintOkfBundle can flag it", () => {
		const result = parseOkfConcept("---\ntype: T\ntimestamp: not-a-date\n---\nbody", {
			bundleRoot: "/tmp/bundle",
			relativePath: "x.md",
			source: makeSource("/tmp/bundle/x.md"),
		});
		expect("error" in result).toBe(false);
		if ("error" in result) return;
		expect(result.concept.timestamp).toBe("not-a-date");
	});

	it("treats files without frontmatter as having no metadata", () => {
		const result = parseOkfConcept("# Just a heading\n\nbody", {
			bundleRoot: "/tmp/bundle",
			relativePath: "loose.md",
			source: makeSource("/tmp/bundle/loose.md"),
		});
		expect(result).toEqual({
			error: expect.stringContaining("missing required `type`"),
			reason: "invalid",
		});
	});
});

describe("lintOkfBundle", () => {
	function concept(overrides: Partial<OkfConcept>): OkfConcept {
		return {
			id: "tables/orders",
			path: "/tmp/bundle/tables/orders.md",
			bundleRoot: "/tmp/bundle",
			type: "BigQuery Table",
			title: "Orders",
			tags: [],
			body: "",
			links: [],
			_source: makeSource("/tmp/bundle/tables/orders.md"),
			...overrides,
		};
	}

	it("flags duplicate concept ids within the same bundle", () => {
		const warnings = lintOkfBundle([concept({}), concept({ id: "tables/orders" })]);
		expect(warnings.some(w => w.severity === "error" && w.message.includes("Duplicate"))).toBe(true);
	});

	it("flags concepts with missing required fields", () => {
		const warnings = lintOkfBundle([concept({ type: "" })]);
		expect(warnings.some(w => w.severity === "error" && w.message.includes("`type`"))).toBe(true);
	});

	it("warns when the timestamp field is not ISO 8601", () => {
		const warnings = lintOkfBundle([concept({ timestamp: "tomorrow" })]);
		expect(warnings.some(w => w.severity === "warning" && w.message.includes("ISO 8601"))).toBe(true);
	});

	it("warns when the bundle declares a different OKF version", () => {
		const warnings = lintOkfBundle([concept({ id: "index", path: "/tmp/bundle/index.md", okfVersion: "2.0" })]);
		expect(warnings.some(w => w.severity === "warning" && w.message.includes("bundle declares OKF version"))).toBe(
			true,
		);
	});
});
