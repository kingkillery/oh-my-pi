const SECRET_KEY_PATTERN = /TOKEN|SECRET|KEY|PASSWORD|PASS|AUTH|COOKIE|CREDENTIAL|PRIVATE/i;
const ASSIGNMENT_PATTERN = /^([A-Za-z_][A-Za-z0-9_ .-]*)(\s*[:=]\s*)(.*)$/;
const VALUE_FLAGS: Record<string, true> = {
	"--workspace-mode": true,
	"--workspace-root": true,
	"--env-file": true,
	"--copy-secret": true,
	"--secret-allowlist": true,
	"--export-patch": true,
	"--workspace-name": true,
	"--cwd": true,
	"--config": true,
	"--model": true,
	"--provider": true,
	"--api-key": true,
};

export function isSecretLikeKey(key: string): boolean {
	return SECRET_KEY_PATTERN.test(key);
}

function redactAssignmentLine(line: string): string {
	const match = ASSIGNMENT_PATTERN.exec(line);
	if (!match) return line;
	const rawKey = match[1] ?? "";
	const key = rawKey.trim().startsWith('"') && rawKey.trim().endsWith('"') ? rawKey.trim().slice(1, -1) : rawKey;
	if (!isSecretLikeKey(key)) return line;
	return `${rawKey}${match[2] ?? "="}<redacted>`;
}

export function redactSecretLikeValues(input: string): string {
	return input.split("\n").map(redactAssignmentLine).join("\n");
}

export function redactedSecretList(count: number): string[] {
	return Array.from({ length: count }, () => "<redacted>");
}

export function summarizeAgentCommand(rawArgs: readonly string[]): string {
	let positionalCount = 0;
	const flags: string[] = [];
	let consumeNext = false;
	for (const arg of rawArgs) {
		if (consumeNext) {
			consumeNext = false;
			continue;
		}
		if (arg.startsWith("--")) {
			const equalsIndex = arg.indexOf("=");
			const flag = equalsIndex === -1 ? arg : arg.slice(0, equalsIndex);
			flags.push(flag);
			consumeNext = equalsIndex === -1 && VALUE_FLAGS[flag] === true;
			continue;
		}
		if (arg.startsWith("-")) {
			flags.push(arg);
			continue;
		}
		positionalCount += 1;
	}
	const flagSummary = flags.length > 0 ? ` ${flags.join(" ")}` : "";
	return redactSecretLikeValues(`omp${flagSummary} (${positionalCount} positional args)`);
}
