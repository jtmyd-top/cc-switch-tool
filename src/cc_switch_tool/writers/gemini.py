from __future__ import annotations

from pathlib import Path

from .common import http_get, read_json, set_nested, update_active_env, update_env_file, write_json


SETTINGS_PATH = Path("~/.gemini/settings.json")
ENV_PATH = Path("~/.gemini/.env")
ENV_KEYS = ("GEMINI_API_KEY", "GOOGLE_GEMINI_BASE_URL")


def apply_profile(profile: dict[str, str]) -> list[str]:
    settings = read_json(SETTINGS_PATH, default={})
    if profile.get("model"):
        set_nested(settings, ("model", "name"), profile["model"])
    set_nested(settings, ("security", "auth", "selectedType"), "gemini-api-key")
    write_json(SETTINGS_PATH, settings, mode=0o600)
    update_env_file(
        ENV_PATH,
        {
            "GEMINI_API_KEY": profile["api_key"],
            "GOOGLE_GEMINI_BASE_URL": profile["base_url"],
        },
        mode=0o600,
    )
    active_env = update_active_env(env_exports(profile), remove_keys=ENV_KEYS)
    return [str(SETTINGS_PATH.expanduser()), str(ENV_PATH.expanduser()), active_env]


def env_exports(profile: dict[str, str]) -> dict[str, str]:
    return {
        "GEMINI_API_KEY": profile["api_key"],
        "GOOGLE_GEMINI_BASE_URL": profile["base_url"],
    }
