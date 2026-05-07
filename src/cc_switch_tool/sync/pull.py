"""Pull profiles from a cc-switch (Tauri/desktop) WebDAV backup.

The desktop app (github.com/farion1231/cc-switch) backs up three files:
  - manifest.json  (integrity metadata)
  - db.sql         (SQLite dump with providers table)
  - skills.zip     (ignored here)

This module downloads db.sql, parses the INSERT statements for the
``providers`` table, and converts each row into the local profile format.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..store import ProfileStore, StoreError, TOOLS


@dataclass
class PullResult:
    added: list[str]
    updated: list[str]
    skipped: list[str]
    active_set: list[str]


def _parse_sql_inserts(sql: str) -> list[dict[str, Any]]:
    """Extract rows from INSERT INTO "providers" statements."""
    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r'INSERT INTO "providers"\s*\(([^)]+)\)\s*VALUES\s*\((.+)\);',
        re.IGNORECASE,
    )
    for match in pattern.finditer(sql):
        cols_raw = match.group(1)
        vals_raw = match.group(2)
        columns = [c.strip().strip('"') for c in cols_raw.split(",")]
        values = _parse_sql_values(vals_raw)
        if len(columns) == len(values):
            rows.append(dict(zip(columns, values)))
    return rows


def _parse_sql_values(raw: str) -> list[Any]:
    """Parse a SQL VALUES tuple, handling quoted strings with escaped quotes."""
    values: list[Any] = []
    i = 0
    n = len(raw)
    while i < n:
        if raw[i] in (" ", ","):
            i += 1
            continue
        if raw[i] == "'":
            # String literal
            i += 1
            parts: list[str] = []
            while i < n:
                if raw[i] == "'" and i + 1 < n and raw[i + 1] == "'":
                    parts.append("'")
                    i += 2
                elif raw[i] == "'":
                    i += 1
                    break
                else:
                    parts.append(raw[i])
                    i += 1
            values.append("".join(parts))
        elif raw[i:i+4].upper() == "NULL":
            values.append(None)
            i += 4
        else:
            # Number or boolean
            j = i
            while j < n and raw[j] not in (",", ")"):
                j += 1
            token = raw[i:j].strip()
            if token.isdigit():
                values.append(int(token))
            else:
                try:
                    values.append(float(token))
                except ValueError:
                    values.append(token)
            i = j
    return values


def _extract_profile_claude(settings_config: dict) -> dict[str, str] | None:
    """Convert a claude provider's settings_config to a local profile dict."""
    env = settings_config.get("env", {})
    base_url = env.get("ANTHROPIC_BASE_URL", "")
    api_key = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY", "")
    if not base_url or not api_key:
        return None
    return {"base_url": base_url, "api_key": api_key}


def _extract_profile_codex(settings_config: dict) -> dict[str, str] | None:
    """Convert a codex provider's settings_config to a local profile dict."""
    auth = settings_config.get("auth", {})
    api_key = auth.get("OPENAI_API_KEY") or auth.get("auth_mode", "")
    if not api_key or api_key == "apikey":
        api_key = auth.get("OPENAI_API_KEY", "")
    config_str = settings_config.get("config", "")
    base_url = ""
    model = ""
    if config_str:
        # Parse base_url from TOML-like config
        m = re.search(r'base_url\s*=\s*"([^"]+)"', config_str)
        if m:
            base_url = m.group(1)
        m = re.search(r'^model\s*=\s*"([^"]+)"', config_str, re.MULTILINE)
        if m:
            model = m.group(1)
    if not base_url or not api_key:
        return None
    profile: dict[str, str] = {"base_url": base_url, "api_key": api_key}
    if model:
        profile["model"] = model
    return profile


def _extract_profile_gemini(settings_config: dict) -> dict[str, str] | None:
    """Convert a gemini provider's settings_config to a local profile dict."""
    env = settings_config.get("env", {})
    base_url = env.get("GOOGLE_GEMINI_BASE_URL") or env.get("GEMINI_BASE_URL", "")
    api_key = env.get("GEMINI_API_KEY", "")
    if not base_url or not api_key:
        return None
    profile: dict[str, str] = {"base_url": base_url, "api_key": api_key}
    model = env.get("GEMINI_MODEL", "")
    if model:
        profile["model"] = model
    return profile


_EXTRACTORS = {
    "claude": _extract_profile_claude,
    "codex": _extract_profile_codex,
    "gemini": _extract_profile_gemini,
}


def pull_from_sql(sql: str, store: ProfileStore, *, overwrite: bool = False) -> PullResult:
    """Parse db.sql and import providers into the local ProfileStore."""
    rows = _parse_sql_inserts(sql)
    added: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    active_set: list[str] = []

    for row in rows:
        app_type = row.get("app_type", "")
        name = row.get("name", "")
        if app_type not in TOOLS or not name:
            continue

        settings_raw = row.get("settings_config", "")
        try:
            settings_config = json.loads(settings_raw) if settings_raw else {}
        except json.JSONDecodeError:
            skipped.append(f"{app_type}/{name} (invalid settings_config JSON)")
            continue

        extractor = _EXTRACTORS.get(app_type)
        if not extractor:
            continue
        profile = extractor(settings_config)
        if not profile:
            skipped.append(f"{app_type}/{name} (missing base_url or api_key)")
            continue

        label = f"{app_type}/{name}"
        existing = store.data["profiles"][app_type].get(name)
        if existing and not overwrite:
            skipped.append(label)
            continue

        if existing:
            updated.append(label)
        else:
            added.append(label)
        store.data["profiles"][app_type][name] = profile

        is_current = row.get("is_current")
        if is_current and is_current not in (0, "0", False):
            store.data["active"][app_type] = name
            active_set.append(label)

    store.save()
    return PullResult(added=added, updated=updated, skipped=skipped, active_set=active_set)
