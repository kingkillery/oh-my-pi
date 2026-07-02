/**
 * Open Knowledge Format (OKF) Capability
 *
 * Loads OKF v0.1 concept documents from `.wiki/` knowledge bundles (or any
 * `index.md` / `*.md` tree that declares `okf_version: "0.1"` in its root
 * `index.md` frontmatter).
 *
 * See https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
 */
import { defineCapability } from ".";
import type { SourceMeta } from "./types";

/** Parsed frontmatter for an OKF v0.1 concept document. */
export interface OkfFrontmatter {
	/** REQUIRED by the OKF spec: short string identifying the kind of concept. */
	type?: string;
	title?: string;
	description?: string;
	resource?: string;
	tags?: string[];
	timestamp?: string;
	/** Producer-defined extras — preserved verbatim for round-tripping. */
	extra?: Record<string, unknown>;
}

/** Cross-link parsed from a concept body. Bundle-relative or markdown-relative. */
export interface OkfLink {
	/** Raw link target as written in the markdown. */
	target: string;
	/** Resolved concept ID, if the link is bundle-relative and points to a `.md`. */
	conceptId: string | undefined;
	/** Link text shown to the reader. */
	text: string;
}

/**
 * A single OKF v0.1 concept document.
 *
 * The concept ID is the file path inside the bundle, with the `.md` suffix
 * removed (e.g. `tables/users.md` -> `tables/users`).
 */
export interface OkfConcept {
	/** Stable concept ID = bundle-relative path without `.md`. */
	id: string;
	/** Absolute path to the source file. */
	path: string;
	/** Bundle root (absolute) the concept was loaded from. */
	bundleRoot: string;
	/** Concept type (`type` frontmatter field). */
	type: string;
	/** Optional display name from `title` frontmatter; defaults to a humanised ID. */
	title: string;
	/** Optional one-line summary from `description` frontmatter. */
	description?: string;
	/** Optional canonical resource URI the concept describes. */
	resource?: string;
	/** Optional producer-supplied tags. */
	tags: readonly string[];
	/** Optional ISO 8601 timestamp of last meaningful change. */
	timestamp?: string;
	/** OKF v0.1 spec version declared by the bundle (only present on the root `index.md`). */
	okfVersion?: string;
	/** Markdown body, with the frontmatter block stripped. */
	body: string;
	/** Cross-links parsed from the body, in document order. */
	links: readonly OkfLink[];
	/** Producer-defined extras preserved verbatim for round-tripping. */
	extra?: Record<string, unknown>;
	/** Source metadata. */
	_source: SourceMeta;
}

/** Reserved filenames defined by the OKF v0.1 spec (§3.1). */
export const OKF_RESERVED_FILENAMES: Record<string, true> = {
	"index.md": true,
	"log.md": true,
};

/** OKF v0.1 spec version this capability targets. */
export const OKF_VERSION = "0.1";

/** Type guard for OKF reserved filenames. */
export function isOkfReservedFileName(fileName: string): boolean {
	return OKF_RESERVED_FILENAMES[fileName] === true;
}

export const okfCapability = defineCapability<OkfConcept>({
	id: "okf-concepts",
	displayName: "OKF Concepts",
	description: "Open Knowledge Format (OKF) v0.1 concept documents loaded from knowledge bundles",
	key: concept => `${concept.bundleRoot}::${concept.id}`,
	toExtensionId: concept => `okf:${concept.bundleRoot}::${concept.id}`,
	validate: concept => {
		if (!concept.id) return "Missing concept id";
		if (!concept.path) return "Missing concept path";
		if (!concept.type) return "Missing required `type` frontmatter field";
		if (!concept.bundleRoot) return "Missing bundle root";
		return undefined;
	},
});
