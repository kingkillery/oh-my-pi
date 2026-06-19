/**
 * Open background agent switcher directly from CLI.
 */
import { Command } from "@oh-my-pi/pi-utils/cli";
import { parseArgs } from "../cli/args";
import { runRootCommand } from "../main";

export default class Bg extends Command {
	static description = "Open background agent switcher";
	static hidden = false;

	static examples = ["# Open background agent selector\n  omp bg"];

	async run(): Promise<void> {
		const parsed = parseArgs(this.argv);
		parsed.openBackgrounds = true;
		await runRootCommand(parsed, []);
	}
}
