import type { Usage } from "@pk-nerdsaver-ai/pi-ai";
import { Container, Spacer, Text } from "@pk-nerdsaver-ai/pi-tui";
import { formatNumber } from "@pk-nerdsaver-ai/pi-utils";
import { theme } from "../../modes/theme/theme";

export function createUsageRowBlock(usage: Usage): Container {
	const totalInput = usage.input + usage.cacheWrite;
	const parts: string[] = [];
	parts.push(`${theme.icon.input} ${formatNumber(totalInput)}`);
	parts.push(`${theme.icon.output} ${formatNumber(usage.output)}`);
	if (usage.cacheRead > 0) {
		parts.push(`cache: ${formatNumber(usage.cacheRead)}`);
	}
	const block = new Container();
	block.addChild(new Spacer(1));
	block.addChild(new Text(theme.fg("dim", parts.join("  ")), 1, 0));
	return block;
}
