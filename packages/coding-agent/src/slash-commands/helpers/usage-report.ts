import type { UsageLimit, UsageReport } from "@pk-nerdsaver-ai/pi-ai";
import type { OAuthAccountIdentity } from "../../session/auth-storage";
import type { SlashCommandRuntime } from "../types";
import { reportMatchesActiveAccount } from "./active-oauth-account";
import { formatDuration, renderAsciiBar } from "./format";

function formatProviderName(provider: string): string {
	return provider
		.split(/[-_]/g)
		.map(part => (part ? part[0].toUpperCase() + part.slice(1) : ""))
		.join(" ");
}

function formatUsageAmount(limit: UsageLimit): string {
	const amount = limit.amount;
	const used = amount.used ?? (amount.usedFraction !== undefined ? amount.usedFraction * 100 : undefined);
	const remainingFraction =
		amount.remainingFraction ??
		(amount.usedFraction !== undefined ? Math.max(0, 1 - amount.usedFraction) : undefined);
	const unit = amount.unit === "percent" ? "%" : ` ${amount.unit}`;
	const usedText = used === undefined ? "unknown used" : `${used.toFixed(2)}${unit} used`;
	const remainingText = remainingFraction === undefined ? "" : ` (${(remainingFraction * 100).toFixed(1)}% left)`;
	return `${usedText}${remainingText}`;
}

function formatUsageReportAccount(report: UsageReport, limit: UsageLimit, index: number): string {
	const email = report.metadata?.email;
	if (typeof email === "string" && email) return email;
	const accountId = report.metadata?.accountId ?? limit.scope.accountId;
	if (typeof accountId === "string" && accountId) return accountId;
	const projectId = report.metadata?.projectId ?? limit.scope.projectId;
	if (typeof projectId === "string" && projectId) return projectId;
	return `account ${index + 1}`;
}

function renderUsageReports(
	reports: UsageReport[],
	nowMs: number,
	resolveActiveAccount?: (provider: string) => OAuthAccountIdentity | undefined,
): string {
	const latestFetchedAt = Math.max(...reports.map(report => report.fetchedAt ?? 0));
	const lines = [`Usage${latestFetchedAt ? ` (${formatDuration(nowMs - latestFetchedAt)} ago)` : ""}`];
	const grouped = new Map<string, UsageReport[]>();
	for (const report of reports) {
		const providerReports = grouped.get(report.provider) ?? [];
		providerReports.push(report);
		grouped.set(report.provider, providerReports);
	}

	for (const [provider, providerReports] of [...grouped.entries()].sort(([left], [right]) =>
		left.localeCompare(right),
	)) {
		lines.push("", formatProviderName(provider));
		const activeAccount = resolveActiveAccount?.(provider);
		for (const report of providerReports) {
			const inUse = reportMatchesActiveAccount(report, activeAccount);
			const savedResets = report.resetCredits?.availableCount ?? 0;
			if (savedResets > 0) {
				const resetLabel =
					typeof report.metadata?.email === "string"
						? report.metadata.email
						: typeof report.metadata?.accountId === "string"
							? report.metadata.accountId
							: "account";
				lines.push(
					`- ${resetLabel}: ${savedResets} saved rate-limit reset${savedResets === 1 ? "" : "s"} available — /usage reset to spend`,
				);
			}
			if (report.limits.length === 0) {
				const email = typeof report.metadata?.email === "string" ? report.metadata.email : "account";
				lines.push(`- ${email}: no limits reported`);
				continue;
			}
			for (let index = 0; index < report.limits.length; index++) {
				const limit = report.limits[index]!;
				const window = limit.window?.label ?? limit.scope.windowId;
				const tier = limit.scope.tier ? ` (${limit.scope.tier})` : "";
				lines.push(`- ${limit.label}${tier}${window ? ` — ${window}` : ""}`);
				lines.push(
					`  ${formatUsageReportAccount(report, limit, index)}: ${formatUsageAmount(limit)}${inUse ? "  ← in use by this session" : ""}`,
				);
				lines.push(`  ${renderAsciiBar(limit.amount.usedFraction)}`);
				if (limit.window?.resetsAt && limit.window.resetsAt > nowMs) {
					lines.push(`  resets in ${formatDuration(limit.window.resetsAt - nowMs)}`);
				}
				if (limit.notes && limit.notes.length > 0) lines.push(`  ${limit.notes.join(" • ")}`);
			}
		}
	}
	return ["```", ...lines, "```"].join("\n");
}

/**
 * Build the `/usage` ACP-mode text. Prefers provider-reported limits when the
 * session exposes `fetchUsageReports`; otherwise falls back to the local
 * session-manager tallies.
 */
export async function buildUsageReportText(runtime: SlashCommandRuntime): Promise<string> {
	const provider = runtime.session as SlashCommandRuntime["session"] & {
		fetchUsageReports?: () => Promise<UsageReport[] | null>;
	};
	if (provider.fetchUsageReports) {
		const reports = await provider.fetchUsageReports();
		if (reports && reports.length > 0) {
			const currentProvider = runtime.session.model?.provider;
			const activeAccount = currentProvider
				? runtime.session.modelRegistry.authStorage.getOAuthAccountIdentity(
						currentProvider,
						runtime.session.sessionId,
					)
				: undefined;
			return renderUsageReports(reports, Date.now(), providerId =>
				providerId === currentProvider ? activeAccount : undefined,
			);
		}
	}

	const settings = runtime.session.settings;
	const fusionActive =
		settings.get("fusion.enabled") === true &&
		settings.get("fusion.mode") !== "off" &&
		settings.get("fusion.showSavings") === true;
	const split = runtime.session.getFusionUsageSplit();
	const billable = (u: typeof split.total): number => u.input + u.output + u.cacheWrite;
	const lines = [
		"Usage",
		`Input tokens: ${split.total.input}`,
		`Output tokens: ${split.total.output}`,
		`Cache read tokens: ${split.total.cacheRead}`,
		`Cache write tokens: ${split.total.cacheWrite}`,
		`Premium requests: ${split.total.premiumRequests}`,
		`Cost: $${split.total.cost.toFixed(6)}`,
	];
	const sidekickTokens = billable(split.sidekick);
	if (fusionActive && sidekickTokens > 0) {
		const frontierTokens = billable(split.frontier);
		const totalTokens = frontierTokens + sidekickTokens;
		const share = totalTokens > 0 ? (sidekickTokens / totalTokens) * 100 : 0;
		lines.push(
			"",
			"Fusion (cost mode)",
			`Frontier tokens: ${frontierTokens}`,
			`Sidekick tokens: ${sidekickTokens} (${share.toFixed(1)}% of billable tokens)`,
			`Frontier cost: $${split.frontier.cost.toFixed(6)} · Sidekick cost: $${split.sidekick.cost.toFixed(6)}`,
		);
		// Self-calibrated estimate: price the sidekick's tokens at the frontier's own
		// observed blended $/token. Only meaningful when the frontier actually billed
		// (flat-rate / OAuth tiers report ~0 cost, so the estimate is suppressed).
		const frontierRate = frontierTokens > 0 && split.frontier.cost > 0 ? split.frontier.cost / frontierTokens : 0;
		if (frontierRate > 0) {
			const estSavings = Math.max(0, sidekickTokens * frontierRate - split.sidekick.cost);
			lines.push(`Est. savings vs all-frontier: $${estSavings.toFixed(6)}`);
		}
	}
	return lines.join("\n");
}
