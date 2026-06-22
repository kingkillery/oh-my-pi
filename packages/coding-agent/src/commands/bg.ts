/**
 * Open the Agent Hub (background sessions + subagents) directly from the CLI.
 * Mirrors `omp join`: launch the interactive TUI and immediately open the hub.
 */
import { APP_NAME } from "@pk-nerdsaver-ai/pi-utils";
import { Command } from "@pk-nerdsaver-ai/pi-utils/cli";
import { parseArgs } from "../cli/args";
import { runRootCommand } from "../main";

export default class Bg extends Command {
	static description = "Open the Agent Hub (background sessions)";

	static examples = [`${APP_NAME} bg`];

	async run(): Promise<void> {
		if (!process.stdin.isTTY || !process.stdout.isTTY) {
			process.stderr.write(`${APP_NAME} bg requires an interactive terminal\n`);
			process.exitCode = 1;
			return;
		}
		const parsed = parseArgs([]);
		parsed.openBackgrounds = true;
		await runRootCommand(parsed, []);
	}
}
