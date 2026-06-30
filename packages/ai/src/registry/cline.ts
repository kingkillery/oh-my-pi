/**
 * Cline account login (cline.bot).
 *
 * Mirrors the default flow in Cline's own SDK/CLI
 * (`sdk/packages/core/src/auth/cline.ts`): a WorkOS device-authorization grant
 * followed by a Cline token registration call. The device flow is headless-
 * friendly (no localhost callback server), so it works over SSH the same way
 * the Kilo device flow does.
 *
 * 1. `POST https://api.workos.com/user_management/authorize/device` →
 *    `{ device_code, user_code, verification_uri(_complete), expires_in, interval }`
 * 2. Show the verification URL + user code; poll
 *    `POST https://api.workos.com/user_management/authenticate` with the
 *    device-code grant until WorkOS returns `{ access_token, refresh_token }`.
 * 3. Exchange the WorkOS tokens for Cline credentials at
 *    `POST https://api.cline.bot/api/v1/auth/register`.
 *
 * The resulting `access` token is sent as `Authorization: Bearer <token>` to the
 * OpenAI-compatible gateway at `https://api.cline.bot/api/v1`.
 */

import type { FetchImpl } from "../types";
import type { OAuthController, OAuthCredentials } from "./oauth/types";
import type { ProviderDefinition } from "./types";

const CLINE_API_BASE_URL = "https://api.cline.bot";
const WORKOS_API_BASE_URL = "https://api.workos.com";
/** Public WorkOS client id for Cline production (sdk/packages/shared cline-environment.ts). */
const WORKOS_CLIENT_ID = "client_01K3A541FN8TA3EPPHTD2325AR";
const DEVICE_AUTHORIZATION_URL = `${WORKOS_API_BASE_URL}/user_management/authorize/device`;
const WORKOS_AUTHENTICATE_URL = `${WORKOS_API_BASE_URL}/user_management/authenticate`;
const CLINE_REGISTER_URL = `${CLINE_API_BASE_URL}/api/v1/auth/register`;
const CLINE_REFRESH_URL = `${CLINE_API_BASE_URL}/api/v1/auth/refresh`;
const DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code";
const HTTP_TIMEOUT_MS = 30_000;
const DEFAULT_EXPIRES_IN_SECONDS = 300;
const DEFAULT_POLL_INTERVAL_SECONDS = 5;
const FALLBACK_TOKEN_TTL_MS = 60 * 60 * 1000;

interface WorkOSDeviceAuthorizationResponse {
	device_code?: string;
	user_code?: string;
	verification_uri?: string;
	verification_uri_complete?: string;
	expires_in?: number;
	interval?: number;
	error?: string;
	error_description?: string;
}

interface WorkOSTokenResponse {
	access_token?: string;
	refresh_token?: string;
	token_type?: string;
	error?: string;
	error_description?: string;
}

interface ClineAuthApiUser {
	email?: string;
	clineUserId?: string | null;
}

interface ClineAuthResponseData {
	accessToken?: string;
	refreshToken?: string;
	tokenType?: string;
	expiresAt?: string;
	userInfo?: ClineAuthApiUser;
}

interface ClineTokenResponse {
	success?: boolean;
	data?: ClineAuthResponseData;
}

function toPositiveSeconds(value: unknown, fallback: number): number {
	return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}

function toExpiryEpochMs(expiresAt: string | undefined): number {
	if (expiresAt) {
		const epoch = Date.parse(expiresAt);
		if (!Number.isNaN(epoch)) {
			return epoch;
		}
	}
	return Date.now() + FALLBACK_TOKEN_TTL_MS;
}

function toClineCredentials(data: ClineAuthResponseData, fallback?: OAuthCredentials): OAuthCredentials {
	const access = data.accessToken;
	if (!access) {
		throw new Error("Cline token response did not include an access token");
	}
	const refresh = data.refreshToken ?? fallback?.refresh;
	if (!refresh) {
		throw new Error("Cline token response did not include a refresh token");
	}
	return {
		access,
		refresh,
		expires: toExpiryEpochMs(data.expiresAt),
		email: data.userInfo?.email ?? fallback?.email,
		accountId: data.userInfo?.clineUserId ?? fallback?.accountId,
	};
}

async function requestDeviceAuthorization(fetchImpl: FetchImpl): Promise<{
	deviceCode: string;
	userCode: string;
	verificationUri: string;
	verificationUriComplete?: string;
	expiresInSeconds: number;
	pollIntervalSeconds: number;
}> {
	const response = await fetchImpl(DEVICE_AUTHORIZATION_URL, {
		method: "POST",
		headers: { "Content-Type": "application/x-www-form-urlencoded" },
		body: new URLSearchParams({ client_id: WORKOS_CLIENT_ID }),
		signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
	});
	const json = (await response.json().catch(() => ({}))) as WorkOSDeviceAuthorizationResponse;
	if (!response.ok) {
		const detail = json.error_description ? ` - ${json.error_description}` : "";
		throw new Error(`Cline device authorization failed: ${response.status}${detail}`);
	}
	if (!json.device_code || !json.user_code || !json.verification_uri) {
		throw new Error("Cline device authorization response missing required fields");
	}
	return {
		deviceCode: json.device_code,
		userCode: json.user_code,
		verificationUri: json.verification_uri,
		verificationUriComplete: json.verification_uri_complete,
		expiresInSeconds: toPositiveSeconds(json.expires_in, DEFAULT_EXPIRES_IN_SECONDS),
		pollIntervalSeconds: toPositiveSeconds(json.interval, DEFAULT_POLL_INTERVAL_SECONDS),
	};
}

async function pollWorkOSTokens(
	callbacks: OAuthController,
	fetchImpl: FetchImpl,
	deviceCode: string,
	expiresInSeconds: number,
	initialPollIntervalSeconds: number,
): Promise<{ accessToken: string; refreshToken: string }> {
	const deadline = Date.now() + expiresInSeconds * 1000;
	let intervalSeconds = Math.max(1, initialPollIntervalSeconds);

	while (Date.now() <= deadline) {
		if (callbacks.signal?.aborted) {
			throw new Error("Login cancelled");
		}
		const response = await fetchImpl(WORKOS_AUTHENTICATE_URL, {
			method: "POST",
			headers: { "Content-Type": "application/x-www-form-urlencoded" },
			body: new URLSearchParams({
				grant_type: DEVICE_CODE_GRANT,
				device_code: deviceCode,
				client_id: WORKOS_CLIENT_ID,
			}),
			signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
		});
		const payload = (await response.json().catch(() => ({}))) as WorkOSTokenResponse;
		if (response.ok) {
			if (!payload.access_token || !payload.refresh_token) {
				throw new Error("Invalid WorkOS token response");
			}
			return { accessToken: payload.access_token, refreshToken: payload.refresh_token };
		}
		switch (payload.error) {
			case "authorization_pending":
				break;
			case "slow_down":
				intervalSeconds += 1;
				break;
			case "access_denied":
				throw new Error("Authorization was denied");
			case "expired_token":
				throw new Error("Authorization code expired. Please try again.");
			case "invalid_grant":
				throw new Error(payload.error_description || "WorkOS authorization failed");
			default:
				throw new Error(
					`WorkOS token polling failed: ${response.status}${payload.error_description ? ` - ${payload.error_description}` : ""}`,
				);
		}
		callbacks.onProgress?.("Waiting for browser authentication confirmation...");
		await Bun.sleep(intervalSeconds * 1000);
	}
	throw new Error("Authentication timed out. Please try again.");
}

async function registerWithCline(
	fetchImpl: FetchImpl,
	workosTokens: { accessToken: string; refreshToken: string },
): Promise<OAuthCredentials> {
	const response = await fetchImpl(CLINE_REGISTER_URL, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(workosTokens),
		signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
	});
	if (!response.ok) {
		const text = await response.text().catch(() => "");
		throw new Error(`Cline token registration failed: ${response.status}${text ? ` - ${text}` : ""}`);
	}
	const json = (await response.json()) as ClineTokenResponse;
	if (!json.success || !json.data) {
		throw new Error("Invalid Cline token registration response");
	}
	return toClineCredentials(json.data);
}

export async function loginCline(callbacks: OAuthController): Promise<OAuthCredentials> {
	const fetchImpl = (callbacks.fetch ?? fetch) as FetchImpl;
	const deviceAuthorization = await requestDeviceAuthorization(fetchImpl);

	callbacks.onAuth?.({
		url: deviceAuthorization.verificationUriComplete ?? deviceAuthorization.verificationUri,
		instructions: `Enter this code in your browser: ${deviceAuthorization.userCode}`,
	});

	const workosTokens = await pollWorkOSTokens(
		callbacks,
		fetchImpl,
		deviceAuthorization.deviceCode,
		deviceAuthorization.expiresInSeconds,
		deviceAuthorization.pollIntervalSeconds,
	);

	return registerWithCline(fetchImpl, workosTokens);
}

export async function refreshClineToken(credentials: OAuthCredentials): Promise<OAuthCredentials> {
	const response = await fetch(CLINE_REFRESH_URL, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ refreshToken: credentials.refresh, grantType: "refresh_token" }),
		signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
	});
	if (!response.ok) {
		const text = await response.text().catch(() => "");
		throw new Error(`Cline token refresh failed: ${response.status}${text ? ` - ${text}` : ""}`);
	}
	const json = (await response.json()) as ClineTokenResponse;
	if (!json.success || !json.data) {
		throw new Error("Invalid Cline token refresh response");
	}
	return toClineCredentials(json.data, credentials);
}

export const clineProvider = {
	id: "cline",
	name: "Cline",
	login: loginCline,
	refreshToken: refreshClineToken,
} as const satisfies ProviderDefinition;
