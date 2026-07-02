/**
 * Open Knowledge Format (OKF) v0.1 parser.
 *
 * Pure functions that turn a markdown document + its bundle-relative path into
 * an {@link OkfConcept} (or a typed parse error). No filesystem, no side effects.
 *
 * Spec: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
 */
import { parseFrontmatter } from "@pk-nerdsaver-ai/pi-utils";
import {
	OKF_RESERVED_FILENAMES,
	OKF_VERSION,
	type OkfConcept,
	type OkfFrontmatter,
	type OkfLink,
} from "../capability/okf";

export type { OkfConcept, OkfFrontmatter, OkfLink } from "../capability/okf";

const MARKDOWN_LINK_RE = /\[([^\]]*)\]\(([^)]+)\)/g;
const ISO_8601_RE = /^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/;

export type OkfParseResult = { concept: OkfConcept } | { error: string; reason: "invalid" };

const KNOWN_FRONTMATTER_KEYS = new Set([
	"type",
	"title",
	"description",
	"resource",
	"tags",
	"timestamp",
	"okf_version",
]);

/** Convert a kebab-case slug like `agent-loop-patterns` to `Agent loop patterns`. */
export function humaniseConceptId(id: string): string {
	const stem = id.split("/").pop() ?? id;
	return stem
		.replace(/\.md$/, "")
		.replace(/[-_]+/g, " ")
		.replace(/\b\w/g, char => char.toUpperCase());
}

/** Convert a bundle-relative path (with or without leading `/`) to a concept ID. */
export function toConceptId(relativePath: string): string {
	return relativePath.replace(/^\/+/, "").replace(/\.md$/, "");
}

/** Convert a concept ID back to the bundle-relative path with a `.md` suffix. */
export function conceptIdToPath(conceptId: string): string {
	return `${conceptId.replace(/\.md$/, "")}.md`;
}

/** True when the markdown link target is a non-network URI we should treat as an in-bundle link. */
function isInternalLinkTarget(target: string): boolean {
	if (target.startsWith("http://") || target.startsWith("https://")) return false;
	if (target.startsWith("mailto:") || target.startsWith("tel:")) return false;
	if (target.startsWith("#")) return false;
	return true;
}

/** Strip the URL fragment from a markdown link target. */
function stripFragment(target: string): string {
	const hash = target.indexOf("#");
	return hash === -1 ? target : target.slice(0, hash);
}

/**
 * Resolve an in-bundle link to a concept ID when the target is a `.md` file.
 *
 * - Bundle-relative targets (`/tables/users.md`) anchor on the bundle root.
 * - Relative targets (`./other.md`, `sibling.md`) anchor on the source concept's directory.
 * - Directory targets (`tables/`) return the directory as a synthetic ID with no `.md`.
 * - Targets without a `.md` suffix resolve to `undefined` (external or section).
 */
export function resolveLinkConceptId(target: string, sourceId: string): string | undefined {
	if (!isInternalLinkTarget(target)) return undefined;
	const cleaned = stripFragment(target);
	if (cleaned === "" || cleaned.endsWith("/")) return undefined;
	if (!cleaned.endsWith(".md")) return undefined;

	if (cleaned.startsWith("/")) {
		return toConceptId(cleaned);
	}

	const sourceDir = sourceId.includes("/") ? sourceId.slice(0, sourceId.lastIndexOf("/")) : "";
	const segments = sourceDir.length > 0 ? sourceDir.split("/") : [];
	for (const part of cleaned.split("/")) {
		if (part === "" || part === ".") continue;
		if (part === "..") {
			segments.pop();
			continue;
		}
		segments.push(part);
	}
	return segments.join("/").replace(/\.md$/, "");
}

/** Extract in-bundle links from a markdown body, preserving document order. */
export function extractLinks(body: string, sourceId: string): OkfLink[] {
	const links: OkfLink[] = [];
	// Reset the regex state for each call — `g` flag carries `.lastIndex` between runs.
	const re = new RegExp(MARKDOWN_LINK_RE.source, "g");
	for (const match of body.matchAll(re)) {
		const text = match[1] ?? "";
		const target = match[2] ?? "";
		links.push({
			target,
			text,
			conceptId: resolveLinkConceptId(target, sourceId),
		});
	}
	return links;
}

/** Coerce arbitrary YAML values into the well-known OKF frontmatter fields. */
function coerceOkfFrontmatter(
	raw: Record<string, unknown>,
): OkfFrontmatter & { okfVersion?: string; extra: Record<string, unknown> } {
	const extra: Record<string, unknown> = {};
	for (const [key, value] of Object.entries(raw)) {
		if (!KNOWN_FRONTMATTER_KEYS.has(key)) extra[key] = value;
	}

	const out: OkfFrontmatter & { okfVersion?: string; extra: Record<string, unknown> } = { extra };

	if (typeof raw.type === "string" && raw.type.trim().length > 0) out.type = raw.type.trim();
	if (typeof raw.title === "string") out.title = raw.title;
	if (typeof raw.description === "string") out.description = raw.description;
	if (typeof raw.resource === "string") out.resource = raw.resource;
	if (typeof raw.timestamp === "string" && raw.timestamp.trim().length > 0) {
		out.timestamp = raw.timestamp.trim();
	}
	if (Array.isArray(raw.tags)) {
		const tags = raw.tags.filter((value): value is string => typeof value === "string" && value.trim().length > 0);
		if (tags.length > 0) out.tags = Array.from(new Set(tags.map(tag => tag.trim())));
	}
	if (typeof raw.okf_version === "string") {
		out.okfVersion = raw.okf_version.trim();
	}

	return out;
}

/**
 * Parse a single OKF v0.1 concept document.
 *
 * `bundleRoot` and `relativePath` identify the document within the bundle.
 * Reserved filenames (`index.md`, `log.md`) parse but validate as `missing type`
 * — they are directory listings, not concepts.
 *
 * `source` is the standard `SourceMeta` to attach to the resulting concept.
 */
export function parseOkfConcept(
	rawContent: string,
	opts: { bundleRoot: string; relativePath: string; source: OkfConcept["_source"] },
): OkfParseResult {
	const { frontmatter: rawFrontmatter, body } = parseFrontmatter(rawContent, { level: "off" });
	const coerced = coerceOkfFrontmatter(rawFrontmatter ?? {});

	const fileName = opts.relativePath.split("/").pop() ?? opts.relativePath;
	const isReserved = OKF_RESERVED_FILENAMES[fileName] === true;
	const conceptId = toConceptId(opts.relativePath);

	if (!isReserved && (!coerced.type || coerced.type.length === 0)) {
		return {
			error: `Concept ${conceptId} is missing required \`type\` frontmatter field`,
			reason: "invalid",
		};
	}

	const links = extractLinks(body, conceptId);
	const concept: OkfConcept = {
		id: conceptId,
		path: opts.source.path,
		bundleRoot: opts.bundleRoot,
		type: coerced.type ?? "",
		title: coerced.title?.trim() || humaniseConceptId(conceptId),
		description: coerced.description,
		resource: coerced.resource,
		tags: coerced.tags ?? [],
		timestamp: coerced.timestamp,
		okfVersion: coerced.okfVersion,
		extra: coerced.extra,
		body,
		links,
		_source: opts.source,
	};

	return { concept };
}

/**
 * Lint a list of concepts against OKF v0.1 conformance rules (§9).
 *
 * Returns a list of `OKF conformance` warnings. Reserved filenames and missing
 * `index.md` are NOT errors; OKF is intentionally permissive.
 */
export interface OkfLintWarning {
	severity: "error" | "warning";
	path: string;
	message: string;
}

export function lintOkfBundle(concepts: readonly OkfConcept[]): OkfLintWarning[] {
	const warnings: OkfLintWarning[] = [];
	const seen = new Map<string, OkfConcept>();
	for (const concept of concepts) {
		const key = `${concept.bundleRoot}::${concept.id}`;
		if (seen.has(key)) {
			warnings.push({
				severity: "error",
				path: concept.path,
				message: `Duplicate concept id \`${concept.id}\` in bundle ${concept.bundleRoot}`,
			});
			continue;
		}
		seen.set(key, concept);

		if (!concept.type) {
			warnings.push({
				severity: "error",
				path: concept.path,
				message: `Missing required \`type\` frontmatter field`,
			});
		}
		if (concept.timestamp !== undefined && !ISO_8601_RE.test(concept.timestamp)) {
			warnings.push({
				severity: "warning",
				path: concept.path,
				message: `\`timestamp\` is not a valid ISO 8601 datetime: ${concept.timestamp}`,
			});
		}
		if (concept.okfVersion && concept.okfVersion !== OKF_VERSION) {
			warnings.push({
				severity: "warning",
				path: concept.path,
				message: `bundle declares OKF version \`${concept.okfVersion}\`; this loader targets v${OKF_VERSION} (best-effort consumption per §11)`,
			});
		}
	}
	return warnings;
}
