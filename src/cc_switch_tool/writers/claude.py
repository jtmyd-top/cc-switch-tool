from __future__ import annotations

from pathlib import Path

from .common import http_get, read_json, set_nested, update_active_env, write_json


SETTINGS_PATH = Path("~/.claude/settings.json")
ENV_KEYS = (
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
)


def _choose_token_key(api_key: str) -> str:
    """Pick exactly one of ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN.

    Claude Code refuses to start when both are set. Use the key prefix as a
    hint: official API keys use ANTHROPIC_API_KEY; OAuth tokens and any
    third-party relay key default to ANTHROPIC_AUTH_TOKEN (Bearer auth).
    """
    if api_key.startswith("sk-ant-api"):
        return "ANTHROPIC_API_KEY"
    return "ANTHROPIC_AUTH_TOKEN"


def apply_profile(profile: dict[str, str]) -> list[str]:
    settings = read_json(SETTINGS_PATH, default={})
    # Remove apiKeyHelper to avoid "two keys" warning from Claude Code
    settings.pop("apiKeyHelper", None)
    token_key = _choose_token_key(profile["api_key"])
    other_key = (
        "ANTHROPIC_AUTH_TOKEN" if token_key == "ANTHROPIC_API_KEY" else "ANTHROPIC_API_KEY"
    )
    set_nested(settings, ("env", token_key), profile["api_key"])
    env = settings.get("env")
    if isinstance(env, dict):
        env.pop(other_key, None)
    set_nested(settings, ("env", "ANTHROPIC_BASE_URL"), profile["base_url"])
    if profile.get("model"):
        set_nested(settings, ("env", "ANTHROPIC_MODEL"), profile["model"])
    else:
        env = settings.get("env")
        if isinstance(env, dict):
            env.pop("ANTHROPIC_MODEL", None)
    write_json(SETTINGS_PATH, settings, mode=0o600)
    active_env = update_active_env(env_exports(profile), remove_keys=ENV_KEYS)
    return [str(SETTINGS_PATH.expanduser()), active_env]


def env_exports(profile: dict[str, str]) -> dict[str, str]:
    token_key = _choose_token_key(profile["api_key"])
    exports = {
        token_key: profile["api_key"],
        "ANTHROPIC_BASE_URL": profile["base_url"],
    }
    if profile.get("model"):
        exports["ANTHROPIC_MODEL"] = profile["model"]
    return exports


def test_profile(profile: dict[str, str], timeout: float = 10.0) -> dict:
    base = profile["base_url"].rstrip("/")
    url = base + ("/models" if base.endswith("/v1") else "/v1/models")
    headers = {
        "x-api-key": profile["api_key"],
        "anthropic-version": "2023-06-01",
        "Authorization": f"Bearer {profile['api_key']}",
    }
    return http_get(url, headers=headers, timeout=timeout)
