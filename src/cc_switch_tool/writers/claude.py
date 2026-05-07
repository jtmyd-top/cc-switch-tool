from __future__ import annotations

from pathlib import Path

from .common import http_get, read_json, set_nested, write_json


SETTINGS_PATH = Path("~/.claude/settings.json")


def apply_profile(profile: dict[str, str]) -> list[str]:
    settings = read_json(SETTINGS_PATH, default={})
    set_nested(settings, ("env", "ANTHROPIC_API_KEY"), profile["api_key"])
    set_nested(settings, ("env", "ANTHROPIC_BASE_URL"), profile["base_url"])
    write_json(SETTINGS_PATH, settings, mode=0o600)
    return [str(SETTINGS_PATH.expanduser())]


def env_exports(profile: dict[str, str]) -> dict[str, str]:
    return {
        "ANTHROPIC_API_KEY": profile["api_key"],
        "ANTHROPIC_BASE_URL": profile["base_url"],
    }


def test_profile(profile: dict[str, str], timeout: float = 10.0) -> dict:
    base = profile["base_url"].rstrip("/")
    url = base + ("/models" if base.endswith("/v1") else "/v1/models")
    headers = {
        "x-api-key": profile["api_key"],
        "anthropic-version": "2023-06-01",
        "Authorization": f"Bearer {profile['api_key']}",
    }
    return http_get(url, headers=headers, timeout=timeout)
