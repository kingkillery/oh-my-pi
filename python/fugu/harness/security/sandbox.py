from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping


SandboxMode = Literal["readonly", "readwrite"]
NetworkMode = Literal["none", "allow"]


# Env vars always safe to forward to a sandboxed subprocess (paths, locale,
# platform identifiers). Anything outside this set is treated as potentially
# secret and dropped when pass_environment=False.
_DEFAULT_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "PATHEXT",
    "COMSPEC",
)


# Env vars that route network traffic via proxies. Cleared when network="none"
# so an attacker can't bypass the network sandbox with HTTP_PROXY=http://evil/.
_PROXY_ENV_KEYS: tuple[str, ...] = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
)


@dataclass(frozen=True)
class SandboxPolicy:
    """Declarative sandbox policy for subprocess execution.

    The policy itself doesn't enforce anything — it's a configuration object
    that ``build_subprocess_env`` and the proposer tool-allowlist consume. Two
    knobs do real work today:

    * ``pass_environment=False`` (default) -> the subprocess env is reduced
      to ``env_allowlist`` plus platform paths. Anything that *looks* like a
      secret (``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ...) is dropped, so
      a malicious candidate edit cannot exfiltrate operator credentials by
      dumping ``os.environ`` inside the eval subprocess.
    * ``network="none"`` (default) -> HTTP(S) proxy env vars are cleared. The
      subprocess can still reach the loopback (and 9router, when its URL is
      on localhost) unless the caller also uses OS-level containment.

    ``mode`` is informational for now; the proposer enforces write scope at
    the tool layer (``--disallowedTools Bash`` + the editable-surface allow
    list), not at the filesystem layer.
    """

    mode: SandboxMode = "readonly"
    network: NetworkMode = "none"
    pass_environment: bool = False
    env_allowlist: tuple[str, ...] = field(default_factory=lambda: _DEFAULT_ENV_ALLOWLIST)


def build_subprocess_env(
    policy: SandboxPolicy,
    base: Mapping[str, str],
    *,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a subprocess environment honoring ``policy``.

    - ``pass_environment=False`` -> only entries from ``policy.env_allowlist``
      are forwarded; everything else (including operator API keys) is dropped.
    - ``pass_environment=True`` -> ``base`` is forwarded in full. Operators
      who opt in accept that a malicious subprocess can read those secrets.
    - ``network="none"`` -> proxy env vars are cleared so a misconfigured
      proxy can't route traffic outside the intended network boundary.
    - ``overrides`` (always applied last) let callers force specific values
      such as ``PYTHONPATH`` or ``FMH_OPTIMIZER_INPROC_EVAL`` regardless of
      the policy.
    """
    if policy.pass_environment:
        env = dict(base)
    else:
        env = {key: value for key, value in base.items() if key in policy.env_allowlist}

    if policy.network == "none":
        for key in _PROXY_ENV_KEYS:
            env.pop(key, None)

    if overrides:
        env.update(overrides)

    return env
