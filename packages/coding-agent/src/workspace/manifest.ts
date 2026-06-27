import * as path from "node:path";
import { ETHEREAL_DIR, ETHEREAL_MANIFEST, type EtherealManifestStatus, type WorkspaceManifest } from "./types";

export function manifestPath(workspacePath: string): string {
	return path.join(workspacePath, ETHEREAL_DIR, ETHEREAL_MANIFEST);
}

export async function writeManifest(workspacePath: string, manifest: WorkspaceManifest): Promise<void> {
	await Bun.write(manifestPath(workspacePath), `${JSON.stringify(manifest, null, "\t")}\n`);
}

export async function readManifest(workspacePath: string): Promise<WorkspaceManifest> {
	return (await Bun.file(manifestPath(workspacePath)).json()) as WorkspaceManifest;
}

export async function updateManifestStatus(workspacePath: string, status: EtherealManifestStatus): Promise<void> {
	const current = await readManifest(workspacePath);
	await writeManifest(workspacePath, { ...current, status });
}
