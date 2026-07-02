import { describe, expect, it } from "bun:test";
import { parseRequestedBinaryTargets, planBinaryPublish } from "./publish-binaries-hf";

describe("parseRequestedBinaryTargets", () => {
	it("maps target ids to distribution filenames", () => {
		expect(parseRequestedBinaryTargets("win32-x64, linux-x64")).toEqual([
			{ id: "win32-x64", file: "omp-windows-x64.exe" },
			{ id: "linux-x64", file: "omp-linux-x64" },
		]);
	});

	it("rejects unknown targets before building", () => {
		expect(() => parseRequestedBinaryTargets("linux-riscv64")).toThrow("Unknown target");
	});
});

describe("planBinaryPublish", () => {
	it("skips build/upload for requested binaries already present under the tag", () => {
		const existing = new Set(["omp-darwin-arm64", "omp-darwin-x64", "omp-linux-arm64", "omp-windows-x64.exe"]);

		const plan = planBinaryPublish("win32-x64,linux-x64", existing, false);

		expect(plan.skippedExisting).toEqual([{ id: "win32-x64", file: "omp-windows-x64.exe" }]);
		expect(plan.toBuild).toEqual([{ id: "linux-x64", file: "omp-linux-x64" }]);
		expect(plan.missingRequiredAfterBuild).toEqual([]);
	});

	it("forces rebuilds even when the binary is already present", () => {
		const existing = new Set(["omp-windows-x64.exe"]);

		const plan = planBinaryPublish("win32-x64", existing, true);

		expect(plan.skippedExisting).toEqual([]);
		expect(plan.toBuild).toEqual([{ id: "win32-x64", file: "omp-windows-x64.exe" }]);
	});
});
