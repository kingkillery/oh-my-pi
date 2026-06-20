const GITHUB_RAW_BASE = "https://raw.githubusercontent.com/kingkillery/oh-my-pi/main/scripts";

export default {
	async fetch(request) {
		const url = new URL(request.url);
		let target;
		switch (url.pathname) {
			case "/install.sh":
			case "/install":
			case "/":
				target = `${GITHUB_RAW_BASE}/install.sh`;
				break;
			case "/install.ps1":
				target = `${GITHUB_RAW_BASE}/install.ps1`;
				break;
			default:
				return new Response("Not found", { status: 404 });
		}

		const response = await fetch(target, {
			headers: {
				"User-Agent": "oh-my-pi-install-redirect",
			},
		});
		if (!response.ok) {
			return new Response(`Failed to fetch installer: ${response.status}`, { status: 502 });
		}

		const headers = new Headers(response.headers);
		headers.set("Cache-Control", "public, max-age=60");
		headers.set("Access-Control-Allow-Origin", "*");
		return new Response(response.body, {
			status: response.status,
			headers,
		});
	},
};
