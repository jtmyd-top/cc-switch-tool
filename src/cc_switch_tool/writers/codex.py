from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import tomlkit

from .common import (
    atomic_write_text,
    extract_env_keys_with_prefix,
    http_get,
    shell_export,
    update_active_env,
)


CONFIG_PATH = Path("~/.codex/config.toml")
ENV_PATH = Path("~/.cc-switch-tool/codex.env")
ACTIVE_ENV_PATH = Path("~/.cc-switch-tool/active.env")
ENV_KEY_PREFIX = "CODEX_API_KEY_"
LEGACY_ENV_KEY = "OPENAI_API_KEY"


def _sanitize_for_env(name: str) -> str:
    """Convert a profile name into the suffix of a POSIX env var name.

    Non-ASCII or all-symbol names (e.g. pure Chinese) collapse to nothing under
    the ASCII-only regex; fall back to a short hash so each profile still maps
    to a unique env var.
    """
    upper = re.sub(r"[^A-Z0-9_]", "_", name.upper())
    collapsed = re.sub(r"_+", "_", upper).strip("_")
    if collapsed:
        return collapsed
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8].upper()
    return f"X{digest}"


def env_key_for_profile(profile_name: str) -> str:
    """Per-profile env var name — stable for a given profile name.

    Each codex profile gets its own env_key so all keys can coexist permanently
    in the shell environment. Switching active profile then becomes a config.toml
    pointer change with no shell-env mutation required, making ``ccs use codex``
    take effect immediately in any already-open terminal.
    """
    return f"{ENV_KEY_PREFIX}{_sanitize_for_env(profile_name)}"


def _read_config() -> tomlkit.TOMLDocument:
    resolved = CONFIG_PATH.expanduser()
    if not resolved.exists():
        return tomlkit.document()
    return tomlkit.parse(resolved.read_text(encoding="utf-8"))


def apply_profile(
    profile: dict[str, str],
    profile_name: str,
    all_profiles: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """Apply ``profile_name`` as the active codex provider.

    When ``all_profiles`` is supplied, every codex profile's
    ``[model_providers.<provider>]`` block is rewritten so its ``env_key`` points
    at the per-profile env var name, and every profile's key is written to
    ``active.env``. This lets codex's built-in provider picker switch between
    providers without re-sourcing the shell.
    """
    if all_profiles:
        _check_env_key_uniqueness(all_profiles)

    provider = profile.get("provider") or profile_name
    env_key = env_key_for_profile(profile_name)

    config = _read_config()
    config["model_provider"] = provider
    if profile.get("model"):
        config["model"] = profile["model"]

    providers = config.get("model_providers")
    if providers is None:
        providers = tomlkit.table()
        config["model_providers"] = providers

    _write_provider_table(providers, provider, profile["base_url"], env_key)

    if all_profiles:
        for other_name, other_profile in all_profiles.items():
            if other_name == profile_name:
                continue
            other_provider = other_profile.get("provider") or other_name
            _write_provider_table(
                providers,
                other_provider,
                other_profile["base_url"],
                env_key_for_profile(other_name),
            )

    atomic_write_text(CONFIG_PATH, tomlkit.dumps(config), mode=0o600)
    atomic_write_text(
        ENV_PATH,
        shell_export(LEGACY_ENV_KEY, profile["api_key"]) + "\n",
        mode=0o600,
    )

    exports = env_exports(profile, profile_name, all_profiles)
    remove_keys = _stale_codex_env_keys(exports)
    active_env = update_active_env(exports, remove_keys=remove_keys)
    return [str(CONFIG_PATH.expanduser()), str(ENV_PATH.expanduser()), active_env]


def _write_provider_table(
    providers: tomlkit.items.Table,
    provider: str,
    base_url: str,
    env_key: str,
) -> None:
    table = providers.get(provider)
    if table is None:
        table = tomlkit.table()
        providers[provider] = table
    table["name"] = provider
    table["base_url"] = base_url
    table["env_key"] = env_key


def env_exports(
    profile: dict[str, str],
    profile_name: str | None = None,
    all_profiles: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    """Env-var assignments for codex.

    - ``OPENAI_API_KEY`` = active profile's key (kept for backward compat with
      the openai SDK and other tools that hard-code this name).
    - ``CODEX_API_KEY_<NAME>`` = each profile's own key. Once these are in the
      shell environment, switching between codex providers does not require
      mutating any env var — config.toml's per-provider ``env_key`` already
      points at the right one.
    """
    exports: dict[str, str] = {LEGACY_ENV_KEY: profile["api_key"]}
    if profile_name:
        exports[env_key_for_profile(profile_name)] = profile["api_key"]
    if all_profiles:
        for other_name, other_profile in all_profiles.items():
            exports[env_key_for_profile(other_name)] = other_profile["api_key"]
    return exports


def _stale_codex_env_keys(current: dict[str, str]) -> tuple[str, ...]:
    """Find ``CODEX_API_KEY_*`` keys in active.env that ``current`` no longer has."""
    existing = extract_env_keys_with_prefix(ACTIVE_ENV_PATH, ENV_KEY_PREFIX)
    return tuple(key for key in existing if key not in current)


def _check_env_key_uniqueness(all_profiles: dict[str, dict[str, str]]) -> None:
    """Raise if two profile names sanitize to the same env var.

    Sanitization is uppercase + ASCII-only, so e.g. ``Factory`` and ``factory``
    collide. Better to fail loudly here than to silently overwrite one key
    with another's value.
    """
    seen: dict[str, str] = {}
    for name in all_profiles:
        key = env_key_for_profile(name)
        if key in seen:
            raise ValueError(
                f"codex profiles {seen[key]!r} and {name!r} both map to env var "
                f"{key}. Rename one of them (env vars are case-insensitive and "
                f"non-ASCII characters collapse to underscores)."
            )
        seen[key] = name


def shell_needs_reload(profile_name: str, expected_key: str) -> bool:
    """True if the parent shell hasn't loaded the per-profile env var yet.

    Returning True is the cue for the CLI/TUI to print a one-time reminder.
    After the user opens a new shell (or sources active.env once), all
    ``CODEX_API_KEY_*`` vars stay in env for the session and this returns False
    forever after — until a new profile is added.
    """
    return os.environ.get(env_key_for_profile(profile_name)) != expected_key


def test_profile(profile: dict[str, str], timeout: float = 10.0) -> dict:
    base = profile["base_url"].rstrip("/")
    url = base + ("/models" if base.endswith("/v1") else "/v1/models")
    headers = {"Authorization": f"Bearer {profile['api_key']}"}
    return http_get(url, headers=headers, timeout=timeout)
