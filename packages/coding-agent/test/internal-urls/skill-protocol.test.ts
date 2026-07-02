import { afterEach, describe, expect, it } from "bun:test";
import { resetActiveSkillsForTests, setActiveSkills } from "@pk-nerdsaver-ai/pi-coding-agent/extensibility/skills";
import { InternalUrlRouter } from "@pk-nerdsaver-ai/pi-coding-agent/internal-urls";

describe("SkillProtocolHandler bare listing", () => {
	afterEach(() => {
		resetActiveSkillsForTests();
	});

	it("lists visible skills (name + description) for bare skill://", async () => {
		setActiveSkills([
			{
				name: "alpha",
				description: "First skill",
				filePath: "/skills/alpha/SKILL.md",
				baseDir: "/skills/alpha",
				source: "test",
			},
			{
				name: "hidden-one",
				description: "Opt-in only",
				filePath: "/skills/hidden-one/SKILL.md",
				baseDir: "/skills/hidden-one",
				source: "test",
				hide: true,
			},
		]);

		const resource = await InternalUrlRouter.instance().resolve("skill://");
		expect(resource.content).toContain("# Skills (1)");
		expect(resource.content).toContain("- alpha: First skill");
		expect(resource.content).not.toContain("hidden-one");
		expect(resource.content).toContain("skill://<name>");
	});

	it("reports an empty catalog without erroring", async () => {
		setActiveSkills([]);
		const resource = await InternalUrlRouter.instance().resolve("skill://");
		expect(resource.content).toContain("(no skills available)");
	});
});
