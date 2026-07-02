#!/usr/bin/env python3
"""Check whether the AI-Q docs-research path is configured.

Non-strict mode prints JSON diagnostics and exits 0. Strict mode exits non-zero
unless an AI-Q backend returns a 2xx response from a common health endpoint.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

DEFAULT_AIQ_URL: Final = "http://localhost:8000"
DOCS_MARKERS: Final = ("doc", "wiki", "deepwiki", "honeyhive", "knowledge")


@dataclass(frozen=True)
class HttpProbe:
    url: str
    ok: bool
    status: int | None
    error: str | None


@dataclass(frozen=True)
class ConfigProbe:
    path: str | None
    docs_servers: list[str]
    error: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check AI-Q + docs connector readiness")
    parser.add_argument("--aiq-url", default=os.environ.get("AIQ_SERVER_URL", DEFAULT_AIQ_URL))
    parser.add_argument("--mcp-config", default=None, help="Path to .omp/mcp.json or ~/.omp/agent/mcp.json")
    parser.add_argument("--strict", action="store_true", help="Fail if AI-Q is not confirmed healthy")
    parser.add_argument("--timeout", type=float, default=3.0)
    return parser.parse_args()


def candidate_mcp_paths(explicit: str | None) -> list[Path]:
    if explicit:
        return [Path(explicit).expanduser()]
    return [Path(".omp/mcp.json"), Path.home() / ".omp" / "agent" / "mcp.json"]


def find_docs_servers(config: object) -> list[str]:
    if not isinstance(config, dict):
        return []
    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        return []
    docs_servers: list[str] = []
    for name, value in servers.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            continue
        url = value.get("url")
        haystack = " ".join([name, str(url or "")]).lower()
        if any(marker in haystack for marker in DOCS_MARKERS):
            docs_servers.append(name)
    return docs_servers


def probe_config(paths: list[Path]) -> ConfigProbe:
    for path in paths:
        if not path.exists():
            continue
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ConfigProbe(path=str(path), docs_servers=[], error=f"{type(exc).__name__}: {exc}")
        return ConfigProbe(path=str(path), docs_servers=find_docs_servers(config), error=None)
    return ConfigProbe(path=None, docs_servers=[], error="no MCP config found")


def probe_http(base_url: str, timeout: float) -> HttpProbe:
    clean = base_url.rstrip("/")
    last_error = "no endpoint attempted"
    for suffix in ("/health", "/openapi.json", ""):
        url = f"{clean}{suffix}"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = int(response.status)
                if 200 <= status < 300:
                    return HttpProbe(url=url, ok=True, status=status, error=None)
                last_error = f"HTTP {status} from {url}"
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            last_error = f"HTTP {status} from {url}"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    return HttpProbe(url=clean, ok=False, status=None, error=last_error)


def main() -> int:
    args = parse_args()
    config_probe = probe_config(candidate_mcp_paths(args.mcp_config))
    aiq_probe = probe_http(str(args.aiq_url), float(args.timeout))
    result = {
        "aiq": asdict(aiq_probe),
        "mcp_config": asdict(config_probe),
        "ready": aiq_probe.ok and bool(config_probe.docs_servers),
        "notes": [
            "Set AIQ_SERVER_URL when the AI-Q backend is not http://localhost:8000.",
            "Docs connector entries are inferred from MCP server names/URLs containing doc/wiki/deepwiki/honeyhive/knowledge.",
            "Strict mode requires a 2xx AI-Q health/openapi/root response; 401/403 means reachable but not verified usable.",
        ],
    }
    print(json.dumps(result, indent=2))
    if args.strict and not aiq_probe.ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
