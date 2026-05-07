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
from .writers.common import redact


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
            "questionary is required for the interactive TUI. "
            "Reinstall with: pipx install --force cc-switch-tool"
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


def _apply_profile(tool: str, name: str, profile: dict[str, str]) -> list[str]:
    writer = WRITERS[tool]
    if tool == "codex":
        return writer.apply_profile(profile, name)
    return writer.apply_profile(profile)


def _ask_text(q, message: str, *, default: str = "", required: bool = True) -> str | None:
    def _validate(value: str) -> bool | str:
        if required and not value.strip():
            return "Cannot be empty"
        return True

    answer = q.text(message, default=default, validate=_validate).ask()
    if answer is None:
        return None
    return answer.strip()


def _add_profile_flow(q, store: ProfileStore, tool: str) -> str | None:
    name = _ask_text(q, f"Profile name for {tool}:")
    if name is None:
        return None
    base_url = _ask_text(q, "Base URL:")
    if base_url is None:
        return None
    api_key = q.password("API key:").ask()
    if api_key is None:
        return None
    api_key = api_key.strip()
    if not api_key:
        q.print("API key cannot be empty.", style="fg:#ff5555")
        return None

    provider: str | None = None
    model: str | None = None
    if tool == "codex":
        provider_in = _ask_text(
            q,
            "Provider id (blank = use profile name):",
            required=False,
        )
        provider = provider_in or None
        model_in = _ask_text(q, "Model (optional):", required=False)
        model = model_in or None

    try:
        store.add_profile(tool, name, base_url, api_key, provider=provider, model=model)
    except StoreError as exc:
        q.print(f"Error: {exc}", style="fg:#ff5555")
        return None
    q.print(f"Added {tool}/{name}", style="fg:#5fd75f")
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
    choices.append(q.Choice(title="« cancel", value="__cancel__"))
    target = q.select(f"Edit which {tool} profile?", choices=choices).ask()
    if target is None or target == "__cancel__":
        return None

    current = store.get_profile(tool, target)

    base_url = _ask_text(
        q,
        "Base URL:",
        default=current.get("base_url", ""),
    )
    if base_url is None:
        return None

    q.print(
        f"  current key: {redact(current.get('api_key', ''))}  "
        "(leave blank to keep)",
        style="fg:#888888",
    )
    new_key = q.password("New API key (blank = keep current):").ask()
    if new_key is None:
        return None
    new_key = new_key.strip()
    api_key_arg = new_key if new_key else None

    provider_arg: str | None = None
    model_arg: str | None = None
    if tool == "codex":
        provider_in = _ask_text(
            q,
            "Provider id (blank = drop):",
            default=current.get("provider", ""),
            required=False,
        )
        if provider_in is None:
            return None
        provider_arg = provider_in
        model_in = _ask_text(
            q,
            "Model (blank = drop):",
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
        q.print(f"Error: {exc}", style="fg:#ff5555")
        return None
    q.print(f"Updated {tool}/{target}", style="fg:#5fd75f")

    if store.get_active_name(tool) == target:
        try:
            changed = _apply_profile(tool, target, updated)
        except StoreError as exc:
            q.print(f"Error re-applying: {exc}", style="fg:#ff5555")
            return target
        q.print(f"Re-applied active {tool}/{target}", style="fg:#5fd75f")
        for path in changed:
            q.print(f"  updated {path}")
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
    choices.append(q.Choice(title="« cancel", value="__cancel__"))
    target = q.select(f"Remove which {tool} profile?", choices=choices).ask()
    if target is None or target == "__cancel__":
        return
    confirm = q.confirm(
        f"Really remove {tool}/{target}?",
        default=False,
    ).ask()
    if not confirm:
        return
    try:
        store.remove_profile(tool, target)
    except StoreError as exc:
        q.print(f"Error: {exc}", style="fg:#ff5555")
        return
    q.print(f"Removed {tool}/{target}", style="fg:#5fd75f")


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
        choices.append(q.Choice(title="+ add new profile", value=("add", None)))
        if profiles:
            choices.append(q.Choice(title="~ edit profile", value=("edit", None)))
            choices.append(q.Choice(title="- remove profile", value=("remove", None)))
        choices.append(q.Choice(title="« back", value=("back", None)))

        action = q.select(
            f"{tool} profiles  (active: {active or '-'})",
            choices=choices,
            use_shortcuts=False,
        ).ask()
        if action is None or action[0] == "back":
            return

        kind, value = action
        if kind == "add":
            new_name = _add_profile_flow(q, store, tool)
            if new_name and q.confirm(
                f"Activate {tool}/{new_name} now?", default=True
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
        changed = _apply_profile(tool, name, profile)
    except StoreError as exc:
        q.print(f"Error: {exc}", style="fg:#ff5555")
        return
    q.print(f"Using {tool}/{name}", style="fg:#5fd75f")
    for path in changed:
        q.print(f"  updated {path}")
    if tool == "codex":
        q.print(
            '  hint: run  eval "$(cc-switch env codex)"  '
            "if your shell does not have OPENAI_API_KEY yet",
            style="fg:#888888",
        )


# ----------------------------------------------------------------- cloud sync


def _cloud_summary_label(store: ProfileStore) -> str:
    from .sync.manager import SyncManager

    manager = SyncManager(store)
    if not manager.is_configured():
        return "☁ cloud sync (WebDAV)    [not configured]"
    try:
        config = manager.load_config()
    except StoreError as exc:
        return f"☁ cloud sync (WebDAV)    [error: {exc}]"
    state = manager.status()
    last = state.get("last_backup") or state.get("last_restore") or "—"
    return (
        f"☁ cloud sync (WebDAV)    "
        f"url={config.base_url}  user={config.username}  last={last}"
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
            q.print(f"  warning: existing config unreadable ({exc})", style="fg:#ffd75f")

    base_url = _ask_text(
        q,
        "WebDAV base URL:",
        default=existing.base_url if existing else "",
    )
    if base_url is None:
        return False
    username = _ask_text(
        q,
        "Username:",
        default=existing.username if existing else "",
    )
    if username is None:
        return False

    if existing and existing.password:
        keep = q.confirm("Keep stored password?", default=True).ask()
        if keep is None:
            return False
        if keep:
            password: str | None = existing.password
        else:
            password = q.password("Password:").ask()
    else:
        password = q.password("Password:").ask()
    if password is None or not password.strip():
        q.print("Password cannot be empty.", style="fg:#ff5555")
        return False

    remote_dir = _ask_text(
        q,
        "Remote directory:",
        default=(existing.remote_dir if existing else "/cc-switch/"),
        required=False,
    )
    if remote_dir is None:
        return False
    remote_filename = _ask_text(
        q,
        "Remote filename:",
        default=(existing.remote_filename if existing else "profiles.json"),
        required=False,
    )
    if remote_filename is None:
        return False

    verify_default = existing.verify_tls if existing else True
    verify_tls_answer = q.confirm("Verify TLS certificates?", default=verify_default).ask()
    if verify_tls_answer is None:
        return False

    config = WebDAVConfig(
        base_url=base_url,
        username=username,
        password=password,
        remote_dir=remote_dir or "/cc-switch/",
        remote_filename=remote_filename or "profiles.json",
        verify_tls=verify_tls_answer,
    )
    try:
        manager.save_config(config)
    except StoreError as exc:
        q.print(f"Error: {exc}", style="fg:#ff5555")
        return False
    q.print("Saved (encrypted at rest).", style="fg:#5fd75f")
    for key, value in config.redacted_dict().items():
        q.print(f"  {key}: {value}", style="fg:#888888")
    return True


def _cloud_test_flow(q, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    try:
        result = SyncManager(store).test()
    except StoreError as exc:
        q.print(f"Error: {exc}", style="fg:#ff5555")
        return
    status = (result.extra or {}).get("status", "?")
    q.print(f"WebDAV reachable. Probed {result.remote_path} (HTTP {status}).", style="fg:#5fd75f")


def _cloud_backup_flow(q, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    encrypt = q.confirm(
        "Encrypt the upload with a passphrase? (recommended for shared servers)",
        default=False,
    ).ask()
    if encrypt is None:
        return
    passphrase: str | None = None
    if encrypt:
        first = q.password("Passphrase:").ask()
        if not first:
            q.print("Passphrase cannot be empty.", style="fg:#ff5555")
            return
        confirm_pp = q.password("Confirm passphrase:").ask()
        if confirm_pp != first:
            q.print("Passphrases did not match.", style="fg:#ff5555")
            return
        passphrase = first
    try:
        result = SyncManager(store).backup(passphrase=passphrase)
    except StoreError as exc:
        q.print(f"Error: {exc}", style="fg:#ff5555")
        return
    suffix = " (encrypted)" if result.encrypted else ""
    q.print(
        f"Backed up {result.bytes_transferred} bytes to {result.remote_path}{suffix}.",
        style="fg:#5fd75f",
    )


def _cloud_restore_flow(q, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    confirm = q.confirm(
        "Restore will overwrite local profiles.json (a timestamped backup is kept). Continue?",
        default=False,
    ).ask()
    if not confirm:
        return
    force = q.confirm(
        "Force overwrite even if local has profiles missing on the remote?",
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
                passphrase = q.password("Backup passphrase:").ask()
                if not passphrase:
                    return
                continue
            q.print(f"Error: {exc}", style="fg:#ff5555")
            return
    suffix = " (decrypted)" if result.encrypted else ""
    q.print(
        f"Restored {result.bytes_transferred} bytes from {result.remote_path}{suffix}.",
        style="fg:#5fd75f",
    )
    if result.backup_local_path:
        q.print(f"  previous local archived at {result.backup_local_path}", style="fg:#888888")


def _cloud_forget_flow(q, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    confirm = q.confirm(
        "Remove stored WebDAV credentials and sync state?",
        default=False,
    ).ask()
    if not confirm:
        return
    result = SyncManager(store).forget()
    removed = (result.extra or {}).get("removed_paths") or []
    if not removed:
        q.print("Nothing to remove.", style="fg:#ffd75f")
        return
    q.print("Removed:", style="fg:#5fd75f")
    for path in removed:
        q.print(f"  {path}", style="fg:#888888")


def _cloud_status_flow(q, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    status = SyncManager(store).status()
    if not status.get("configured"):
        q.print("not configured", style="fg:#ffd75f")
        return
    if status.get("error"):
        q.print(f"error: {status['error']}", style="fg:#ff5555")
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


def _cloud_menu(q, store: ProfileStore) -> None:
    """Cloud sync sub-menu. Loops until the user goes back."""
    from .sync.manager import SyncManager

    while True:
        manager = SyncManager(store)
        configured = manager.is_configured()

        choices: list[Any] = []
        if configured:
            choices.append(q.Choice(title="↑ backup now", value="backup"))
            choices.append(q.Choice(title="↓ restore (overwrite local)", value="restore"))
            choices.append(q.Choice(title="✓ test connection", value="test"))
            choices.append(q.Choice(title="i status", value="status"))
            choices.append(q.Separator())
            choices.append(q.Choice(title="✎ edit settings", value="setup"))
            choices.append(q.Choice(title="✗ forget settings", value="forget"))
        else:
            choices.append(q.Choice(title="+ setup WebDAV", value="setup"))
        choices.append(q.Choice(title="« back", value="back"))

        title = "☁ cloud sync"
        if configured:
            try:
                cfg = manager.load_config()
                title = f"☁ cloud sync — {cfg.base_url} (user={cfg.username})"
            except StoreError as exc:
                title = f"☁ cloud sync — error: {exc}"

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
        elif action == "status":
            _cloud_status_flow(q, store)
        elif action == "forget":
            _cloud_forget_flow(q, store)


def run_tui() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise TUIUnavailable("interactive TUI requires a TTY")
    q = _require_questionary()
    store = ProfileStore()

    while True:
        choices = [
            q.Choice(title=_tool_label(tool, store), value=("tool", tool)) for tool in TOOLS
        ]
        choices.append(q.Separator())
        choices.append(q.Choice(title=_cloud_summary_label(store), value=("cloud", None)))
        choices.append(q.Separator())
        choices.append(q.Choice(title="quit", value="__quit__"))
        action = q.select(
            "cc-switch — pick a tool",
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
