from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .writers.common import read_json, write_json


TOOLS = ("claude", "codex", "gemini")
STORE_PATH = Path("~/.cc-switch-tool/profiles.json")


class StoreError(Exception):
    pass


class ProfileStore:
    def __init__(self, path: Path = STORE_PATH) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        data = read_json(self.path, default={})
        if not data:
            data = {"version": 1, "active": {}, "profiles": {}}
        data.setdefault("version", 1)
        data.setdefault("active", {})
        data.setdefault("profiles", {})
        for tool in TOOLS:
            data["profiles"].setdefault(tool, {})
        return data

    def save(self) -> None:
        write_json(self.path, self.data, mode=0o600)

    def validate_tool(self, tool: str) -> None:
        if tool not in TOOLS:
            raise StoreError(f"Unsupported tool: {tool}. Choose one of: {', '.join(TOOLS)}")

    def add_profile(
        self,
        tool: str,
        name: str,
        base_url: str,
        api_key: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self.validate_tool(tool)
        if not name.strip():
            raise StoreError("Profile name cannot be empty")
        if not base_url.strip():
            raise StoreError("--base-url is required")
        if not api_key.strip():
            raise StoreError("--api-key is required")

        profile: dict[str, str] = {
            "base_url": base_url.strip(),
            "api_key": api_key.strip(),
        }
        if provider:
            profile["provider"] = provider.strip()
        if model:
            profile["model"] = model.strip()

        self.data["profiles"][tool][name] = profile
        self.save()

    def update_profile(
        self,
        tool: str,
        name: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        clear_provider: bool = False,
        clear_model: bool = False,
    ) -> dict[str, str]:
        """Patch an existing profile in place. Only fields supplied are changed.

        Pass ``clear_provider``/``clear_model`` to drop those optional keys.
        Returns the updated profile.
        """
        self.validate_tool(tool)
        profiles = self.data["profiles"][tool]
        if name not in profiles:
            raise StoreError(f"Profile not found: {tool}/{name}")
        profile = profiles[name]

        if base_url is not None:
            if not base_url.strip():
                raise StoreError("--base-url cannot be empty")
            profile["base_url"] = base_url.strip()
        if api_key is not None:
            if not api_key.strip():
                raise StoreError("--api-key cannot be empty")
            profile["api_key"] = api_key.strip()
        if provider is not None:
            stripped = provider.strip()
            if stripped:
                profile["provider"] = stripped
            else:
                profile.pop("provider", None)
        elif clear_provider:
            profile.pop("provider", None)
        if model is not None:
            stripped = model.strip()
            if stripped:
                profile["model"] = stripped
            else:
                profile.pop("model", None)
        elif clear_model:
            profile.pop("model", None)

        self.save()
        return deepcopy(profile)

    def remove_profile(self, tool: str, name: str) -> None:
        self.validate_tool(tool)
        profiles = self.data["profiles"][tool]
        if name not in profiles:
            raise StoreError(f"Profile not found: {tool}/{name}")
        del profiles[name]
        if self.data["active"].get(tool) == name:
            del self.data["active"][tool]
        self.save()

    def get_profile(self, tool: str, name: str) -> dict[str, str]:
        self.validate_tool(tool)
        try:
            profile = self.data["profiles"][tool][name]
        except KeyError as exc:
            raise StoreError(f"Profile not found: {tool}/{name}") from exc
        return deepcopy(profile)

    def get_active_name(self, tool: str) -> str | None:
        self.validate_tool(tool)
        return self.data["active"].get(tool)

    def get_active_profile(self, tool: str) -> tuple[str, dict[str, str]]:
        active = self.get_active_name(tool)
        if not active:
            raise StoreError(f"No active profile for {tool}")
        return active, self.get_profile(tool, active)

    def set_active(self, tool: str, name: str) -> dict[str, str]:
        profile = self.get_profile(tool, name)
        self.data["active"][tool] = name
        self.save()
        return profile

    def list_profiles(self, tool: str | None = None) -> dict[str, dict[str, dict[str, str]]]:
        if tool:
            self.validate_tool(tool)
            return {tool: deepcopy(self.data["profiles"][tool])}
        return deepcopy(self.data["profiles"])
