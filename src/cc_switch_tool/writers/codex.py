from __future__ import annotations

from pathlib import Path

import tomlkit

from .common import atomic_write_text, http_get, shell_export, update_active_env


CONFIG_PATH = Path("~/.codex/config.toml")
ENV_PATH = Path("~/.cc-switch-tool/codex.env")
ENV_KEYS = ("OPENAI_API_KEY",)


def _read_config() -> tomlkit.TOMLDocument:
    resolved = CONFIG_PATH.expanduser()
    if not resolved.exists():
        return tomlkit.document()
    return tomlkit.parse(resolved.read_text(encoding="utf-8"))


def apply_profile(profile: dict[str, str], profile_name: str) -> list[str]:
    provider = profile.get("provider") or profile_name
    config = _read_config()
    config["model_provider"] = provider
    if profile.get("model"):
        config["model"] = profile["model"]

    providers = config.get("model_providers")
    if providers is None:
        providers = tomlkit.table()
        config["model_providers"] = providers

    provider_table = providers.get(provider)
    if provider_table is None:
        provider_table = tomlkit.table()
        providers[provider] = provider_table

    provider_table["name"] = provider
    provider_table["base_url"] = profile["base_url"]
    provider_table["env_key"] = "OPENAI_API_KEY"

    atomic_write_text(CONFIG_PATH, tomlkit.dumps(config), mode=0o600)
    atomic_write_text(ENV_PATH, shell_export("OPENAI_API_KEY", profile["api_key"]) + "\n", mode=0o600)
    active_env = update_active_env(env_exports(profile), remove_keys=ENV_KEYS)
    return [str(CONFIG_PATH.expanduser()), str(ENV_PATH.expanduser()), active_env]


def env_exports(profile: dict[str, str]) -> dict[str, str]:
    return {"OPENAI_API_KEY": profile["api_key"]}


def test_profile(profile: dict[str, str], timeout: float = 10.0) -> dict:
    base = profile["base_url"].rstrip("/")
    url = base + ("/models" if base.endswith("/v1") else "/v1/models")
    headers = {"Authorization": f"Bearer {profile['api_key']}"}
    return http_get(url, headers=headers, timeout=timeout)
