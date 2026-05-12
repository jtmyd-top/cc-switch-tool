"""Interactive TUI for cc-switch using questionary.

Launched when ``cc-switch`` is invoked without arguments. Provides arrow-key
navigation for picking a tool, switching profiles, and adding/removing
profiles inline. All persistence and config-file writes go through the same
``ProfileStore`` and writer modules used by the CLI subcommands.
"""

from __future__ import annotations

import sys
from typing import Any

from .store import ProfileStore, StoreError, TOOLS
from .writers import claude, codex, gemini
from .writers.common import ensure_shell_env_loader, redact
from .i18n import t


WRITERS = {
    "claude": claude,
    "codex": codex,
    "gemini": gemini,
}


class TUIUnavailable(RuntimeError):
    """Raised when questionary is missing or stdio is not a TTY."""


def _require_questionary():
    try:
        import questionary  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise TUIUnavailable(
            t("questionary is required for the interactive TUI. "
              "Reinstall with: pipx install --force cc-switch-tool")
        ) from exc
    return questionary


def _profile_label(name: str, profile: dict[str, str], active: bool) -> str:
    marker = "● " if active else "  "
    extras: list[str] = []
    if profile.get("provider"):
        extras.append(f"provider={profile['provider']}")
    if profile.get("model"):
        extras.append(f"model={profile['model']}")
    suffix = f"  [{' '.join(extras)}]" if extras else ""
    return (
        f"{marker}{name}  "
        f"{profile.get('base_url', '')}  "
        f"key={redact(profile.get('api_key', ''))}{suffix}"
    )


def _tool_label(tool: str, store: ProfileStore) -> str:
    active = store.get_active_name(tool) or "-"
    count = len(store.list_profiles(tool)[tool])
    return f"{tool:<7}  active: {active}  ({count} profile{'s' if count != 1 else ''})"


def _apply_profile(
    tool: str,
    name: str,
    profile: dict[str, str],
    store: ProfileStore | None = None,
) -> list[str]:
    writer = WRITERS[tool]
    if tool == "codex":
        all_profiles = (
            store.list_profiles("codex")["codex"] if store is not None else None
        )
        changed = writer.apply_profile(profile, name, all_profiles=all_profiles)
    else:
        changed = writer.apply_profile(profile)
    changed.extend(ensure_shell_env_loader())
    return changed


def _apply_all_active_profiles(store: ProfileStore) -> list[str]:
    changed: list[str] = []
    for tool in TOOLS:
        active = store.get_active_name(tool)
        if not active:
            continue
        profile = store.get_profile(tool, active)
        changed.extend(_apply_profile(tool, active, profile, store=store))
    return changed


def _print_codex_shell_reminder(q, profile_name: str, profile: dict[str, str]) -> None:
    if not codex.shell_needs_reload(profile_name, profile["api_key"]):
        return
    env_var = codex.env_key_for_profile(profile_name)
    q.print("")
    q.print(
        t(
            "Heads up: your current shell has not loaded {var} yet, so codex "
            "would still see the old/missing key.",
            var=env_var,
        ),
        style="fg:#ffd75f",
    )
    q.print(t("  Run once to take effect now:"), style="fg:#ffd75f")
    q.print("      source ~/.cc-switch-tool/active.env", style="fg:#ffd75f")
    q.print(
        t("  Or open a new terminal. After that, switching is instant forever."),
        style="fg:#ffd75f",
    )


def _ask_text(q, message: str, *, default: str = "", required: bool = True) -> str | None:
    def _validate(value: str) -> bool | str:
        if required and not value.strip():
            return t("Cannot be empty")
        return True

    answer = q.text(message, default=default, validate=_validate).ask()
    if answer is None:
        return None
    return answer.strip()


def _add_profile_flow(q, store: ProfileStore, tool: str) -> str | None:
    name = _ask_text(q, t("Profile name for {tool}:", tool=tool))
    if name is None:
        return None
    base_url = _ask_text(q, t("Base URL:"))
    if base_url is None:
        return None
    api_key = q.password(t("API key:")).ask()
    if api_key is None:
        return None
    api_key = api_key.strip()
    if not api_key:
        q.print(t("API key cannot be empty."), style="fg:#ff5555")
        return None

    provider: str | None = None
    model: str | None = None
    if tool == "codex":
        provider_in = _ask_text(
            q,
            t("Provider id (blank = use profile name):"),
            required=False,
        )
        provider = provider_in or None
    if tool in ("codex", "claude"):
        model_in = _ask_text(q, t("Model (optional):"), required=False)
        model = model_in or None

    try:
        store.add_profile(tool, name, base_url, api_key, provider=provider, model=model)
    except StoreError as exc:
        q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
        return None
    q.print(t("Added {tool}/{name}", tool=tool, name=name), style="fg:#5fd75f")
    return name


def _edit_profile_flow(q, store: ProfileStore, tool: str) -> str | None:
    profiles = store.list_profiles(tool)[tool]
    if not profiles:
        q.print(f"No {tool} profiles to edit.", style="fg:#ffd75f")
        return None
    active = store.get_active_name(tool)
    choices = [
        q.Choice(
            title=_profile_label(name, profile, name == active),
            value=name,
        )
        for name, profile in sorted(profiles.items())
    ]
    choices.append(q.Choice(title=t("« cancel"), value="__cancel__"))
    target = q.select(t("Edit which {tool} profile?", tool=tool), choices=choices).ask()
    if target is None or target == "__cancel__":
        return None

    current = store.get_profile(tool, target)

    base_url = _ask_text(
        q,
        t("New base URL (leave empty to keep current):"),
        default=current.get("base_url", ""),
    )
    if base_url is None:
        return None

    q.print(
        f"  current key: {redact(current.get('api_key', ''))}  "
        "(leave blank to keep)",
        style="fg:#888888",
    )
    new_key = q.password(t("New API key (leave empty to keep current):")).ask()
    if new_key is None:
        return None
    new_key = new_key.strip()
    api_key_arg = new_key if new_key else None

    provider_arg: str | None = None
    model_arg: str | None = None
    if tool == "codex":
        provider_in = _ask_text(
            q,
            t("New provider (leave empty to keep current):"),
            default=current.get("provider", ""),
            required=False,
        )
        if provider_in is None:
            return None
        provider_arg = provider_in
    if tool in ("codex", "claude"):
        model_in = _ask_text(
            q,
            t("New model (leave empty to keep current):"),
            default=current.get("model", ""),
            required=False,
        )
        if model_in is None:
            return None
        model_arg = model_in

    try:
        updated = store.update_profile(
            tool,
            target,
            base_url=base_url,
            api_key=api_key_arg,
            provider=provider_arg,
            model=model_arg,
        )
    except StoreError as exc:
        q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
        return None
    q.print(t("Updated {tool}/{name}", tool=tool, name=target), style="fg:#5fd75f")

    if store.get_active_name(tool) == target:
        try:
            changed = _apply_profile(tool, target, updated, store=store)
        except StoreError as exc:
            q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
            return target
        q.print(t("Re-applied active profile {tool}/{name}", tool=tool, name=target), style="fg:#5fd75f")
        for path in changed:
            q.print(t("  updated {path}", path=path))
        if tool == "codex":
            _print_codex_shell_reminder(q, target, updated)
    return target


def _remove_profile_flow(q, store: ProfileStore, tool: str) -> None:
    profiles = store.list_profiles(tool)[tool]
    if not profiles:
        q.print(f"No {tool} profiles to remove.", style="fg:#ffd75f")
        return
    active = store.get_active_name(tool)
    choices = [
        q.Choice(
            title=_profile_label(name, profile, name == active),
            value=name,
        )
        for name, profile in sorted(profiles.items())
    ]
    choices.append(q.Choice(title=t("« cancel"), value="__cancel__"))
    target = q.select(t("Remove which {tool} profile?", tool=tool), choices=choices).ask()
    if target is None or target == "__cancel__":
        return
    confirm = q.confirm(
        t("Really remove {tool}/{target}?", tool=tool, target=target),
        default=False,
    ).ask()
    if not confirm:
        return
    try:
        store.remove_profile(tool, target)
    except StoreError as exc:
        q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
        return
    q.print(t("Removed {tool}/{name}", tool=tool, name=target), style="fg:#5fd75f")
    if tool == "codex":
        active = store.get_active_name("codex")
        if active:
            try:
                _apply_profile(
                    "codex",
                    active,
                    store.get_profile("codex", active),
                    store=store,
                )
            except StoreError as exc:
                q.print(t("Error: {error}", error=exc), style="fg:#ff5555")


def _tool_menu(q, store: ProfileStore, tool: str) -> None:
    """Profile-level menu for a single tool. Loops until the user goes back."""
    while True:
        profiles = store.list_profiles(tool)[tool]
        active = store.get_active_name(tool)

        choices: list[Any] = []
        for name, profile in sorted(profiles.items()):
            choices.append(
                q.Choice(
                    title=_profile_label(name, profile, name == active),
                    value=("use", name),
                )
            )
        if choices:
            choices.append(q.Separator())
        choices.append(q.Choice(title=t("+ add new profile"), value=("add", None)))
        if profiles:
            choices.append(q.Choice(title=t("~ edit profile"), value=("edit", None)))
            choices.append(q.Choice(title=t("- remove profile"), value=("remove", None)))
        choices.append(q.Choice(title=t("« back"), value=("back", None)))

        action = q.select(
            t("{tool} profiles  (active: {active})", tool=tool, active=active or '-'),
            choices=choices,
            use_shortcuts=False,
        ).ask()
        if action is None or action[0] == "back":
            return

        kind, value = action
        if kind == "add":
            new_name = _add_profile_flow(q, store, tool)
            if new_name and q.confirm(
                t("Activate {tool}/{name} now?", tool=tool, name=new_name), default=True
            ).ask():
                _activate(q, store, tool, new_name)
        elif kind == "edit":
            _edit_profile_flow(q, store, tool)
        elif kind == "remove":
            _remove_profile_flow(q, store, tool)
        elif kind == "use":
            _activate(q, store, tool, value)


def _activate(q, store: ProfileStore, tool: str, name: str) -> None:
    try:
        profile = store.set_active(tool, name)
        changed = _apply_profile(tool, name, profile, store=store)
    except StoreError as exc:
        q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
        return
    q.print(t("Using {tool}/{name}", tool=tool, name=name), style="fg:#5fd75f")
    for path in changed:
        q.print(t("  updated {path}", path=path))
    if tool == "codex":
        _print_codex_shell_reminder(q, name, profile)


# ----------------------------------------------------------------- cloud sync


def _cloud_summary_label(store: ProfileStore) -> str:
    from .sync.manager import SyncManager

    manager = SyncManager(store)
    if not manager.is_configured():
        return t("☁ cloud sync (WebDAV)    [not configured]")
    try:
        config = manager.load_config()
    except StoreError as exc:
        return t("☁ cloud sync (WebDAV)    [error: {error}]", error=exc)
    state = manager.status()
    last = state.get("last_backup") or state.get("last_restore") or "—"
    return t(
        "☁ cloud sync (WebDAV)    url={url}  user={user}  last={last}",
        url=config.base_url, user=config.username, last=last,
    )


def _cloud_setup_flow(q, store: ProfileStore) -> bool:
    """Returns True if config was saved."""
    from .sync.config import WebDAVConfig
    from .sync.manager import SyncManager

    manager = SyncManager(store)
    existing = None
    if manager.is_configured():
        try:
            existing = manager.load_config()
        except StoreError as exc:
            q.print(t("  warning: existing config unreadable ({error})", error=exc), style="fg:#ffd75f")

    base_url = _ask_text(
        q,
        t("WebDAV base URL:"),
        default=existing.base_url if existing else "",
    )
    if base_url is None:
        return False
    username = _ask_text(
        q,
        t("Username:"),
        default=existing.username if existing else "",
    )
    if username is None:
        return False

    if existing and existing.password:
        keep = q.confirm(t("Keep stored password?"), default=True).ask()
        if keep is None:
            return False
        if keep:
            password: str | None = existing.password
        else:
            password = q.password(t("Password:")).ask()
    else:
        password = q.password(t("Password:")).ask()
    if password is None or not password.strip():
        q.print(t("Password cannot be empty."), style="fg:#ff5555")
        return False

    remote_dir = _ask_text(
        q,
        t("Remote directory:"),
        default=(existing.remote_dir if existing else "/cc-switch/"),
        required=False,
    )
    if remote_dir is None:
        return False
    remote_filename = _ask_text(
        q,
        t("Remote filename:"),
        default=(existing.remote_filename if existing else "profiles.json"),
        required=False,
    )
    if remote_filename is None:
        return False

    verify_default = existing.verify_tls if existing else True
    verify_tls_answer = q.confirm(t("Verify TLS certificates?"), default=verify_default).ask()
    if verify_tls_answer is None:
        return False

    pull_dir = _ask_text(
        q,
        t("GUI cc-switch pull directory (blank = skip)"),
        default=(existing.pull_dir if existing else ""),
        required=False,
    )
    if pull_dir is None:
        return False

    config = WebDAVConfig(
        base_url=base_url,
        username=username,
        password=password,
        remote_dir=remote_dir or "/cc-switch/",
        remote_filename=remote_filename or "profiles.json",
        verify_tls=verify_tls_answer,
        pull_dir=pull_dir or "",
    )
    try:
        manager.save_config(config)
    except StoreError as exc:
        q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
        return False
    q.print(t("Saved (encrypted at rest)."), style="fg:#5fd75f")
    for k, v in config.redacted_dict().items():
        q.print(f"  {k}: {v}", style="fg:#888888")
    return True


def _cloud_test_flow(q, store: ProfileStore) -> None:
    from .sync.manager import SyncManager
    from .sync.webdav import WebDAVError

    manager = SyncManager(store)
    try:
        result = manager.test()
    except StoreError as exc:
        q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
        return
    status = (result.extra or {}).get("status", "?")
    q.print(t("WebDAV reachable. Probed {path} (HTTP {status}).", path=result.remote_path, status=status), style="fg:#5fd75f")

    # Also test pull_dir if configured
    try:
        config = manager.load_config()
    except StoreError:
        return
    if config.pull_dir:
        pull_path = config.pull_dir.rstrip("/") + "/db.sql"
        client = manager._client(config)
        try:
            resp = client.propfind(pull_path, depth="0")
            q.print(t("Pull path reachable: {path} (HTTP {status})", path=pull_path, status=resp.status), style="fg:#5fd75f")
        except WebDAVError as exc:
            q.print(t("Pull path failed: {path} — {error}", path=pull_path, error=exc), style="fg:#ff5555")


def _cloud_backup_flow(q, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    encrypt = q.confirm(
        t("Encrypt the upload with a passphrase? (recommended for shared servers)"),
        default=False,
    ).ask()
    if encrypt is None:
        return
    passphrase: str | None = None
    if encrypt:
        first = q.password(t("Passphrase:")).ask()
        if not first:
            q.print(t("Passphrase cannot be empty."), style="fg:#ff5555")
            return
        confirm_pp = q.password(t("Confirm passphrase:")).ask()
        if confirm_pp != first:
            q.print(t("Passphrases did not match."), style="fg:#ff5555")
            return
        passphrase = first
    try:
        result = SyncManager(store).backup(passphrase=passphrase)
    except StoreError as exc:
        q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
        return
    suffix = t(" (encrypted)") if result.encrypted else ""
    q.print(
        t("Backed up {bytes} bytes to {path}{suffix}.",
          bytes=result.bytes_transferred, path=result.remote_path, suffix=suffix),
        style="fg:#5fd75f",
    )


def _cloud_restore_flow(q, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    confirm = q.confirm(
        t("Restore will overwrite local profiles.json (a timestamped backup is kept). Continue?"),
        default=False,
    ).ask()
    if not confirm:
        return
    force = q.confirm(
        t("Force overwrite even if local has profiles missing on the remote?"),
        default=False,
    ).ask()
    if force is None:
        return

    manager = SyncManager(store)
    passphrase: str | None = None
    while True:
        try:
            result = manager.restore(passphrase=passphrase, force=force)
            break
        except StoreError as exc:
            msg = str(exc)
            if "encrypted" in msg.lower() and passphrase is None:
                passphrase = q.password(t("Backup passphrase:")).ask()
                if not passphrase:
                    return
                continue
            q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
            return
    suffix = t(" (decrypted)") if result.encrypted else ""
    q.print(
        t("Restored {bytes} bytes from {path}{suffix}.",
          bytes=result.bytes_transferred, path=result.remote_path, suffix=suffix),
        style="fg:#5fd75f",
    )
    if result.backup_local_path:
        q.print(t("  Previous local profiles archived at: {path}", path=result.backup_local_path), style="fg:#888888")
    store.data = store._load()
    changed = _apply_all_active_profiles(store)
    if changed:
        q.print(t("Re-applied active profiles:"), style="fg:#5fd75f")
        for path in changed:
            q.print(t("  updated {path}", path=path), style="fg:#888888")


def _cloud_forget_flow(q, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    confirm = q.confirm(
        t("Remove stored WebDAV credentials and sync state?"),
        default=False,
    ).ask()
    if not confirm:
        return
    result = SyncManager(store).forget()
    removed = (result.extra or {}).get("removed_paths") or []
    if not removed:
        q.print(t("Nothing to remove."), style="fg:#ffd75f")
        return
    q.print(t("Removed:"), style="fg:#5fd75f")
    for path in removed:
        q.print(f"  {path}", style="fg:#888888")


def _cloud_status_flow(q, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    status = SyncManager(store).status()
    if not status.get("configured"):
        q.print(t("not configured"), style="fg:#ffd75f")
        return
    if status.get("error"):
        q.print(t("error: {error}", error=status['error']), style="fg:#ff5555")
        return
    for key in (
        "base_url",
        "username",
        "password",
        "remote_path",
        "verify_tls",
        "last_backup",
        "last_backup_size",
        "last_backup_encrypted",
        "last_backup_etag",
        "last_restore",
    ):
        value = status.get(key)
        if value in (None, ""):
            continue
        q.print(f"  {key}: {value}", style="fg:#888888")


def _cloud_pull_flow(q, store: ProfileStore) -> None:
    """Pull profiles from the desktop cc-switch GUI backup via WebDAV."""
    from .sync.manager import SyncManager
    from .sync.pull import pull_from_sql
    from .sync.webdav import WebDAVError

    manager = SyncManager(store)
    try:
        config = manager.load_config()
    except StoreError as exc:
        q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
        return

    if not config.pull_dir:
        q.print(t("Pull directory not configured. Edit settings to set it."), style="fg:#ffd75f")
        return

    overwrite = q.confirm(
        t("Overwrite existing profiles with the same name?"),
        default=False,
    ).ask()
    if overwrite is None:
        return

    pull_path = config.pull_dir.rstrip("/") + "/db.sql"
    client = manager._client(config)
    try:
        response = client.get(pull_path)
    except WebDAVError as exc:
        q.print(t("Failed to download {path}: {error}", path=pull_path, error=exc), style="fg:#ff5555")
        return

    sql = response.body.decode("utf-8")
    result = pull_from_sql(sql, store, overwrite=overwrite)

    if result.added:
        q.print(t("Added ({count}):", count=len(result.added)), style="fg:#5fd75f")
        for label in result.added:
            q.print(f"  + {label}", style="fg:#5fd75f")
    if result.updated:
        q.print(t("Updated ({count}):", count=len(result.updated)), style="fg:#87afff")
        for label in result.updated:
            q.print(f"  ~ {label}", style="fg:#87afff")
    if result.active_set:
        q.print(t("Active profiles set:"), style="fg:#5fd75f")
        for label in result.active_set:
            q.print(f"  * {label}", style="fg:#5fd75f")
    if result.skipped:
        q.print(t("Skipped ({count}):", count=len(result.skipped)), style="fg:#ffd75f")
        for label in result.skipped:
            q.print(f"  - {label}", style="fg:#888888")
    if not result.added and not result.updated:
        q.print(t("No new profiles to import."), style="fg:#ffd75f")
        return
    changed = _apply_all_active_profiles(store)
    if changed:
        q.print(t("Re-applied active profiles:"), style="fg:#5fd75f")
        for path in changed:
            q.print(t("  updated {path}", path=path), style="fg:#888888")


def _cloud_menu(q, store: ProfileStore) -> None:
    """Cloud sync sub-menu. Loops until the user goes back."""
    from .sync.manager import SyncManager

    while True:
        manager = SyncManager(store)
        configured = manager.is_configured()

        choices: list[Any] = []
        if configured:
            choices.append(q.Choice(title=t("↑ backup now"), value="backup"))
            choices.append(q.Choice(title=t("↓ restore (overwrite local)"), value="restore"))
            choices.append(q.Choice(title=t("↙ pull from GUI backup"), value="pull"))
            choices.append(q.Choice(title=t("✓ test connection"), value="test"))
            choices.append(q.Choice(title=t("i status"), value="status"))
            choices.append(q.Separator())
            choices.append(q.Choice(title=t("✎ edit settings"), value="setup"))
            choices.append(q.Choice(title=t("✗ forget settings"), value="forget"))
        else:
            choices.append(q.Choice(title=t("+ setup WebDAV"), value="setup"))
        choices.append(q.Choice(title=t("« back"), value="back"))

        title = t("☁ cloud sync")
        if configured:
            try:
                cfg = manager.load_config()
                title = t("☁ cloud sync — {url} (user={user})", url=cfg.base_url, user=cfg.username)
            except StoreError as exc:
                title = t("☁ cloud sync — error: {error}", error=exc)

        action = q.select(title, choices=choices, use_shortcuts=False).ask()
        if action is None or action == "back":
            return
        if action == "setup":
            _cloud_setup_flow(q, store)
        elif action == "test":
            _cloud_test_flow(q, store)
        elif action == "backup":
            _cloud_backup_flow(q, store)
        elif action == "restore":
            _cloud_restore_flow(q, store)
        elif action == "pull":
            _cloud_pull_flow(q, store)
        elif action == "status":
            _cloud_status_flow(q, store)
        elif action == "forget":
            _cloud_forget_flow(q, store)


def _lang_label() -> str:
    from .i18n import LANG
    current = "中文" if LANG == "zh" else "English"
    return t("⚙ language / 语言: {lang}", lang=current)


def _lang_menu(q) -> None:
    from .i18n import LANG, set_lang, save_lang

    choices = [
        q.Choice(title="中文", value="zh"),
        q.Choice(title="English", value="en"),
        q.Choice(title=t("« back"), value="__cancel__"),
    ]
    answer = q.select(t("Select language / 选择语言"), choices=choices, use_shortcuts=False).ask()
    if answer is None or answer == "__cancel__":
        return
    set_lang(answer)
    save_lang(answer)
    q.print(t("Language set to: {lang}", lang="中文" if answer == "zh" else "English"), style="fg:#5fd75f")


def _upgrade_flow(q) -> None:
    from .upgrade import UpgradeError, execute_plan, plan_upgrade

    try:
        plan = plan_upgrade()
    except UpgradeError as exc:
        q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
        return

    q.print(t("Upgrade method: {method}", method=plan.method), style="fg:#87afff")
    if plan.note:
        q.print(plan.note, style="fg:#888888")
    q.print(t("Running: {command}", command=" ".join(plan.command)), style="fg:#888888")
    confirm = q.confirm(t("Run upgrade now?"), default=True).ask()
    if not confirm:
        return
    rc = execute_plan(plan)
    if rc == 0:
        q.print(t("Upgrade completed. Restart cc-switch to use the new version."), style="fg:#5fd75f")
    else:
        q.print(t("Upgrade failed with exit code {code}", code=rc), style="fg:#ff5555")


def _install_cli_tools_flow(q) -> None:
    from .tool_installer import (
        CLI_TOOLS,
        NodeInstallUnsupported,
        ToolInstallError,
        format_command,
        check_prerequisites,
        format_version,
        install_nodejs,
        install_or_update_tool,
        installed_tool_version,
        needs_node_install,
        node_install_commands,
    )

    try:
        if needs_node_install():
            q.print(t("Node.js is missing or too old."), style="fg:#ffd75f")
            q.print(t("Planned Node.js install commands:"), style="fg:#888888")
            try:
                for command in node_install_commands():
                    q.print(f"  {format_command(command)}", style="fg:#888888")
            except NodeInstallUnsupported as exc:
                q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
                return
            if not q.confirm(t("Install Node.js first, then install/update the CLI tools?"), default=True).ask():
                return
            rc = install_nodejs()
            if rc != 0:
                q.print(t("Node.js installation failed with exit code {code}.", code=rc), style="fg:#ff5555")
                return
        npm, node = check_prerequisites()
    except ToolInstallError as exc:
        q.print(t("Error: {error}", error=exc), style="fg:#ff5555")
        return

    q.print(t("Node.js: {version}", version=node), style="fg:#87afff")
    q.print(t("Installer: {path}", path=npm), style="fg:#888888")
    q.print(t("Will install/update:"), style="fg:#87afff")
    for tool in CLI_TOOLS:
        version = format_version(installed_tool_version(tool.command))
        q.print(
            t("  {name}: {version}  ({package})", name=tool.name, version=version, package=tool.npm_package),
            style="fg:#888888",
        )

    confirm = q.confirm(t("Install/update all CLI tools now?"), default=True).ask()
    if not confirm:
        return

    failed = 0
    for tool in CLI_TOOLS:
        q.print(t("Installing/updating {name}...", name=tool.name), style="fg:#87afff")
        result = install_or_update_tool(tool, npm)
        if result.returncode == 0:
            q.print(
                t(
                    "{name}: {before} -> {after}",
                    name=tool.name,
                    before=format_version(result.before_version),
                    after=format_version(result.after_version),
                ),
                style="fg:#5fd75f",
            )
        else:
            failed += 1
            q.print(
                t("{name} failed with exit code {code}", name=tool.name, code=result.returncode),
                style="fg:#ff5555",
            )

    if failed:
        q.print(
            t("{count} CLI tool(s) failed to install/update.", count=failed),
            style="fg:#ff5555",
        )
    else:
        q.print(t("All CLI tools are installed/updated."), style="fg:#5fd75f")


def run_tui() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise TUIUnavailable(t("interactive TUI requires a TTY"))
    q = _require_questionary()
    store = ProfileStore()

    while True:
        choices = [
            q.Choice(title=_tool_label(tool, store), value=("tool", tool)) for tool in TOOLS
        ]
        choices.append(q.Separator())
        choices.append(q.Choice(title=_cloud_summary_label(store), value=("cloud", None)))
        choices.append(q.Choice(title=t("⬇ install/update CLI tools"), value=("install_tools", None)))
        choices.append(q.Choice(title=t("↻ upgrade program"), value=("upgrade", None)))
        choices.append(q.Choice(title=_lang_label(), value=("lang", None)))
        choices.append(q.Separator())
        choices.append(q.Choice(title=t("quit"), value="__quit__"))
        action = q.select(
            t("cc-switch — pick a tool"),
            choices=choices,
            use_shortcuts=False,
        ).ask()
        if action is None or action == "__quit__":
            return 0
        if not isinstance(action, tuple) or len(action) != 2:
            return 0
        kind, value = action
        if kind == "tool":
            _tool_menu(q, store, value)
        elif kind == "cloud":
            _cloud_menu(q, store)
        elif kind == "install_tools":
            _install_cli_tools_flow(q)
        elif kind == "upgrade":
            _upgrade_flow(q)
        elif kind == "lang":
            _lang_menu(q)
