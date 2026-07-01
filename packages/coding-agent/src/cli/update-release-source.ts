/**
 * Resolve the update channel version advertised by the fork.
 */
export interface ReleaseInfo {
	readonly tag: string;
	readonly version: string;
}

export interface ReleaseSourceOptions {
	readonly distBase: string;
	readonly packageName: string;
	readonly npmRegistry: string;
}

/**
 * The distribution endpoint is the fork's canonical "latest" pointer for
 * pushed binary builds. Fall back to npm only when the endpoint is unreachable,
 * so existing package-manager installs still have a registry-backed update path
 * during distribution outages.
 */
export async function getLatestRelease(options: ReleaseSourceOptions): Promise<ReleaseInfo> {
	const distVersion = await getDistVersion(options.distBase);
	if (distVersion) return { tag: `v${distVersion}`, version: distVersion };
	return getLatestNpmRelease(options);
}

/**
 * Resolve the version the fork's distribution endpoint currently serves
 * (`<distBase>/version` -> `vX.Y.Z`). Returns undefined when unreachable so
 * callers can fall back to package-manager metadata.
 */
export async function getDistVersion(distBase: string): Promise<string | undefined> {
	try {
		const response = await fetch(`${distBase}/version`);
		if (!response.ok) return undefined;
		const version = (await response.text()).trim().replace(/^v/, "");
		return version.length > 0 ? version : undefined;
	} catch {
		return undefined;
	}
}

async function getLatestNpmRelease(options: ReleaseSourceOptions): Promise<ReleaseInfo> {
	const response = await fetch(`${options.npmRegistry}${options.packageName}/latest`);
	if (!response.ok) {
		throw new Error(`Failed to fetch release info: ${response.statusText}`);
	}

	const data: unknown = await response.json();
	if (typeof data !== "object" || data === null || !("version" in data) || typeof data.version !== "string") {
		throw new Error("Failed to fetch release info: invalid registry response");
	}

	return { tag: `v${data.version}`, version: data.version };
}
