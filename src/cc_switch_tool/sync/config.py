"""Storage for WebDAV credentials, encrypted at rest with a machine-bound key.

The on-disk layout under ``~/.cc-switch-tool/``:

* ``webdav.enc``  — Fernet token whose plaintext is JSON serialisation of
  :class:`WebDAVConfig` minus ``remote_path`` (well, including everything;
  the data class itself is the schema).
* ``sync.json``   — non-secret state (last backup/restore timestamps, last
  uploaded size, etc.). Plain JSON to keep `cat ~/.cc-switch-tool/sync.json`
  useful for debugging.
* ``.keyring``    — random salt fallback (only if /etc/machine-id missing).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..i18n import t
from ..writers.common import atomic_write_text, expand, read_json, write_json
from .crypto import (
    DecryptError,
    decrypt_text,
    encrypt_text,
)


CONFIG_PATH = Path("~/.cc-switch-tool/webdav.enc")
STATE_PATH = Path("~/.cc-switch-tool/sync.json")


class ConfigError(RuntimeError):
    """Raised for invalid / missing / unreadable WebDAV config."""


@dataclass(frozen=True)
class WebDAVConfig:
    base_url: str
    username: str
    password: str
    remote_dir: str = "/cc-switch/"
    remote_filename: str = "profiles.json"
    verify_tls: bool = True
    pull_dir: str = ""  # directory where the GUI app backs up (db.sql + manifest.json)

    # ----------------------------------------------------------------- helpers

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebDAVConfig":
        try:
            return cls(
                base_url=str(data["base_url"]).strip(),
                username=str(data["username"]).strip(),
                password=str(data["password"]),
                remote_dir=_normalise_dir(str(data.get("remote_dir") or "/cc-switch/")),
                remote_filename=str(data.get("remote_filename") or "profiles.json").strip(),
                verify_tls=bool(data.get("verify_tls", True)),
                pull_dir=str(data.get("pull_dir") or "").strip(),
            )
        except KeyError as exc:
            raise ConfigError(t("missing required field: {field}", field=exc.args[0])) from exc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def remote_path(self) -> str:
        return _normalise_dir(self.remote_dir) + self.remote_filename.lstrip("/")

    def with_changes(self, **changes: Any) -> "WebDAVConfig":
        if "remote_dir" in changes:
            changes["remote_dir"] = _normalise_dir(str(changes["remote_dir"]))
        return replace(self, **changes)

    def redacted_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        data["password"] = "***" if self.password else ""
        return data


def _normalise_dir(value: str) -> str:
    value = value.strip()
    if not value:
        return "/"
    if not value.startswith("/"):
        value = "/" + value
    if not value.endswith("/"):
        value = value + "/"
    return value


# --------------------------------------------------------------------- file IO


def config_exists() -> bool:
    return expand(CONFIG_PATH).exists()


def load_config() -> WebDAVConfig:
    """Read and decrypt the saved WebDAV config.

    Raises :class:`ConfigError` if not configured, or
    :class:`cc_switch_tool.sync.crypto.DecryptError` if the ciphertext can't
    be decrypted (e.g. user moved hosts).
    """
    resolved = expand(CONFIG_PATH)
    if not resolved.exists():
        raise ConfigError(
            t("WebDAV is not configured yet. Run 'cc-switch sync setup' first.")
        )
    token = resolved.read_text(encoding="utf-8").strip()
    if not token:
        raise ConfigError(t("webdav.enc is empty; re-run 'cc-switch sync setup'."))
    try:
        plaintext = decrypt_text(token)
    except DecryptError:
        raise
    try:
        data = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise ConfigError(t("decrypted webdav.enc is not valid JSON")) from exc
    return WebDAVConfig.from_dict(data)


def save_config(config: WebDAVConfig) -> None:
    payload = json.dumps(config.to_dict(), ensure_ascii=False, sort_keys=True)
    token = encrypt_text(payload)
    atomic_write_text(CONFIG_PATH, token + "\n", mode=0o600)


def forget_config() -> list[str]:
    removed: list[str] = []
    for path in (CONFIG_PATH, STATE_PATH):
        resolved = expand(path)
        if resolved.exists():
            resolved.unlink()
            removed.append(str(resolved))
    return removed


# ----------------------------------------------------------------- sync state


def load_state() -> dict[str, Any]:
    return read_json(STATE_PATH, default={})


def save_state(state: dict[str, Any]) -> None:
    write_json(STATE_PATH, state, mode=0o600)


def update_state(**updates: Any) -> dict[str, Any]:
    state = load_state()
    state.update(updates)
    save_state(state)
    return state


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
