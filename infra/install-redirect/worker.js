/**
 * oh-my-pi.pkking.computer install redirector.
 *
 * Super-light Cloudflare Worker that 302-redirects the install one-liners to the
 * fork's raw scripts on GitHub. Mirrors the upstream omp.sh/install behaviour so
 * `curl -fsSL https://oh-my-pi.pkking.computer/install.sh | sh` and
 * `irm https://oh-my-pi.pkking.computer/install.ps1 | iex` resolve to the
 * kingkillery/oh-my-pi sources. No auth, no key: it is a stateless redirect.
 */
const RAW_BASE = "https://raw.githubusercontent.com/kingkillery/oh-my-pi/main/scripts";

const ROUTES = {
	"/install": `${RAW_BASE}/install.sh`,
	"/install.sh": `${RAW_BASE}/install.sh`,
	"/install.ps1": `${RAW_BASE}/install.ps1`,
};

export default {
	/** @param {Request} request */
	fetch(request) {
		const { pathname } = new URL(request.url);
		const target = ROUTES[pathname];
		if (!target) {
			return new Response("Not found\n", { status: 404, headers: { "content-type": "text/plain" } });
		}
		return Response.redirect(target, 302);
	},
};
