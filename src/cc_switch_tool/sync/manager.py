"""High-level WebDAV backup/restore orchestration."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..store import ProfileStore, StoreError
from ..writers.common import atomic_write_text, expand, redact
from . import config as cfg
from .crypto import (
    CryptoUnavailable,
    DecryptError,
    decrypt_bytes,
    encrypt_bytes,
    looks_like_fernet_token,
)
from .webdav import WebDAVClient, WebDAVError


# Re-exported so callers can `except SyncError` without grabbing every
# underlying exception class.
class SyncError(StoreError):
    """User-facing sync failure."""


@dataclass(frozen=True)
class SyncResult:
    action: str  # "backup" | "restore" | "test" | "setup" | "forget"
    remote_path: str
    bytes_transferred: int = 0
    encrypted: bool = False
    extra: dict[str, Any] | None = None
    backup_local_path: str | None = None


class SyncManager:
    """Orchestrates WebDAV interactions on top of :class:`ProfileStore`."""

    def __init__(self, store: ProfileStore | None = None) -> None:
        self.store = store or ProfileStore()

    # ----------------------------------------------------------------- config

    def is_configured(self) -> bool:
        return cfg.config_exists()

    def load_config(self) -> cfg.WebDAVConfig:
        try:
            return cfg.load_config()
        except cfg.ConfigError as exc:
            raise SyncError(str(exc)) from exc
        except DecryptError as exc:
            raise SyncError(str(exc)) from exc
        except CryptoUnavailable as exc:
            raise SyncError(str(exc)) from exc

    def save_config(self, config: cfg.WebDAVConfig) -> SyncResult:
        try:
            cfg.save_config(config)
        except CryptoUnavailable as exc:
            raise SyncError(str(exc)) from exc
        cfg.update_state(last_setup=cfg.now_iso())
        return SyncResult(action="setup", remote_path=config.remote_path)

    def forget(self) -> SyncResult:
        removed = cfg.forget_config()
        return SyncResult(
            action="forget",
            remote_path="",
            extra={"removed_paths": removed},
        )

    # --------------------------------------------------------------- runtime

    def _client(self, config: cfg.WebDAVConfig) -> WebDAVClient:
        return WebDAVClient(
            base_url=config.base_url,
            username=config.username,
            password=config.password,
            verify_tls=config.verify_tls,
        )

    def test(self) -> SyncResult:
        config = self.load_config()
        client = self._client(config)
        try:
            client.ensure_directory(config.remote_dir)
            response = client.propfind(config.remote_dir, depth="0")
        except WebDAVError as exc:
            raise SyncError(f"WebDAV test failed: {exc}") from exc
        return SyncResult(
            action="test",
            remote_path=config.remote_dir,
            extra={"status": response.status},
        )

    def backup(self, *, passphrase: str | None = None) -> SyncResult:
        config = self.load_config()
        local_path = expand(self.store.path)
        if not local_path.exists():
            # ProfileStore lazily creates this on first save; force a save
            # so we always have something to upload.
            self.store.save()
        payload = local_path.read_bytes()
        encrypted = passphrase is not None
        if encrypted:
            try:
                payload = encrypt_bytes(payload, passphrase=passphrase)
            except CryptoUnavailable as exc:
                raise SyncError(str(exc)) from exc

        client = self._client(config)
        try:
            client.ensure_directory(config.remote_dir)
            response = client.put(
                config.remote_path,
                payload,
                content_type=("application/octet-stream" if encrypted else "application/json"),
            )
        except WebDAVError as exc:
            raise SyncError(f"WebDAV backup failed: {exc}") from exc

        cfg.update_state(
            last_backup=cfg.now_iso(),
            last_backup_size=len(payload),
            last_backup_encrypted=encrypted,
            last_backup_etag=response.headers.get("ETag", ""),
        )
        return SyncResult(
            action="backup",
            remote_path=config.remote_path,
            bytes_transferred=len(payload),
            encrypted=encrypted,
        )

    def restore(
        self,
        *,
        passphrase: str | None = None,
        force: bool = False,
    ) -> SyncResult:
        config = self.load_config()
        client = self._client(config)
        try:
            response = client.get(config.remote_path)
        except WebDAVError as exc:
            raise SyncError(f"WebDAV restore failed: {exc}") from exc

        body = response.body
        was_encrypted = looks_like_fernet_token(body)
        if was_encrypted:
            if passphrase is None:
                raise SyncError(
                    "Remote backup is encrypted; pass --passphrase (or enter it in the TUI)."
                )
            try:
                body = decrypt_bytes(body, passphrase=passphrase)
            except DecryptError as exc:
                raise SyncError(str(exc)) from exc
            except CryptoUnavailable as exc:
                raise SyncError(str(exc)) from exc

        # Validate JSON before clobbering local state.
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SyncError(
                "Remote payload is not valid JSON. "
                "If you encrypted the backup, pass --passphrase."
            ) from exc
        if not isinstance(data, dict):
            raise SyncError("Remote payload is JSON but not an object; refusing to restore.")

        local_path = expand(self.store.path)
        backup_local: str | None = None
        if local_path.exists():
            ts = cfg.now_iso().replace(":", "").replace("-", "")
            backup_local_path = local_path.with_name(f"{local_path.name}.bak.{ts}")
            shutil.copy2(local_path, backup_local_path)
            backup_local = str(backup_local_path)
            if not force:
                # Sanity check: refuse to overwrite if local has profiles the
                # remote doesn't. The user can re-run with --force to opt in.
                _refuse_if_local_has_unique_profiles(local_path, data)

        local_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            local_path,
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            mode=0o600,
        )

        cfg.update_state(
            last_restore=cfg.now_iso(),
            last_restore_size=len(body),
            last_restore_encrypted=was_encrypted,
        )
        return SyncResult(
            action="restore",
            remote_path=config.remote_path,
            bytes_transferred=len(body),
            encrypted=was_encrypted,
            backup_local_path=backup_local,
        )

    # ---------------------------------------------------------------- status

    def status(self) -> dict[str, Any]:
        if not self.is_configured():
            return {"configured": False}
        try:
            config = self.load_config()
        except SyncError as exc:
            return {"configured": True, "error": str(exc)}
        state = cfg.load_state()
        return {
            "configured": True,
            "base_url": config.base_url,
            "username": config.username,
            "password": redact(config.password),
            "remote_path": config.remote_path,
            "verify_tls": config.verify_tls,
            "last_backup": state.get("last_backup"),
            "last_restore": state.get("last_restore"),
            "last_backup_size": state.get("last_backup_size"),
            "last_backup_encrypted": state.get("last_backup_encrypted", False),
            "last_backup_etag": state.get("last_backup_etag"),
        }


def _refuse_if_local_has_unique_profiles(local_path: Path, remote_data: dict[str, Any]) -> None:
    """Refuse restore if local has profiles missing on the remote.

    Forcing restore is a destructive overwrite, so we err on the side of
    not silently dropping data the user might still want. They can pass
    ``--force`` to override.
    """
    try:
        local_data = json.loads(local_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(local_data, dict):
        return
    local_profiles = local_data.get("profiles") or {}
    remote_profiles = remote_data.get("profiles") or {}
    missing: list[str] = []
    if isinstance(local_profiles, dict) and isinstance(remote_profiles, dict):
        for tool, profiles in local_profiles.items():
            if not isinstance(profiles, dict):
                continue
            remote_for_tool = remote_profiles.get(tool) or {}
            if not isinstance(remote_for_tool, dict):
                remote_for_tool = {}
            for name in profiles:
                if name not in remote_for_tool:
                    missing.append(f"{tool}/{name}")
    if missing:
        joined = ", ".join(sorted(missing)[:8])
        more = "" if len(missing) <= 8 else f" (+{len(missing) - 8} more)"
        raise SyncError(
            "Local profiles not present in the remote backup: "
            f"{joined}{more}. Re-run with --force to overwrite anyway, "
            "or run 'cc-switch sync backup' first to push them up."
        )
