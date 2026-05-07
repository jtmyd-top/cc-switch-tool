from __future__ import annotations

import argparse
import getpass
import json
import sys
from typing import Callable

from .i18n import t, set_lang
from .store import ProfileStore, StoreError, TOOLS
from .upgrade import installed_version
from .writers import claude, codex, gemini
from .writers.common import redact, shell_export


WRITERS = {
    "claude": claude,
    "codex": codex,
    "gemini": gemini,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cc-switch",
        description=t(
            "Switch relay endpoint profiles for Claude Code, Codex CLI, and Gemini CLI. "
            "Run without arguments for an interactive menu."
        ),
    )
    parser.add_argument(
        "--lang",
        choices=("zh", "en"),
        default=None,
        help="language / 语言 (default: zh, or set CCS_LANG env)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {installed_version() or 'unknown'}",
    )
    subparsers = parser.add_subparsers(dest="command")

    menu = subparsers.add_parser("menu", help=t("open the interactive TUI (default with no args)"))
    menu.set_defaults(func=cmd_menu)

    upgrade = subparsers.add_parser("upgrade", help=t("upgrade cc-switch-tool itself"))
    upgrade.add_argument(
        "--method",
        choices=("auto", "pipx", "pip"),
        default="auto",
        help=t("upgrade method (default: auto)"),
    )
    upgrade.add_argument(
        "--project-url",
        default=None,
        help=t("pip-installable project URL or path"),
    )
    upgrade.set_defaults(func=cmd_upgrade)

    add = subparsers.add_parser("add", help=t("add or update a profile"))
    add.add_argument("tool", choices=TOOLS)
    add.add_argument("name")
    add.add_argument("--base-url", required=True)
    add.add_argument("--api-key", required=True)
    add.add_argument("--provider", help=t("Codex provider id; defaults to profile name"))
    add.add_argument("--model", help=t("model name (Codex writes to config.toml, Claude sets ANTHROPIC_MODEL)"))
    add.set_defaults(func=cmd_add)

    use = subparsers.add_parser("use", help=t("activate a profile and write tool config"))
    use.add_argument("tool", choices=TOOLS)
    use.add_argument("name")
    use.set_defaults(func=cmd_use)

    edit = subparsers.add_parser(
        "edit",
        help=t("modify an existing profile (any subset of fields)"),
    )
    edit.add_argument("tool", choices=TOOLS)
    edit.add_argument("name")
    edit.add_argument("--base-url")
    edit.add_argument("--api-key")
    edit.add_argument("--provider", help=t("Codex provider id (use --clear-provider to drop)"))
    edit.add_argument("--model", help=t("model name (use --clear-model to drop)"))
    edit.add_argument("--clear-provider", action="store_true")
    edit.add_argument("--clear-model", action="store_true")
    edit.set_defaults(func=cmd_edit)

    list_cmd = subparsers.add_parser("list", help=t("list profiles"))
    list_cmd.add_argument("tool", nargs="?", choices=TOOLS)
    list_cmd.set_defaults(func=cmd_list)

    current = subparsers.add_parser("current", help=t("show active profile"))
    current.add_argument("tool", nargs="?", choices=TOOLS)
    current.set_defaults(func=cmd_current)

    remove = subparsers.add_parser("remove", help=t("remove a profile"))
    remove.add_argument("tool", choices=TOOLS)
    remove.add_argument("name")
    remove.set_defaults(func=cmd_remove)

    show = subparsers.add_parser("show", help=t("show a profile with the API key redacted"))
    show.add_argument("tool", choices=TOOLS)
    show.add_argument("name")
    show.set_defaults(func=cmd_show)

    env = subparsers.add_parser("env", help=t("print shell exports for a profile"))
    env.add_argument("tool", choices=TOOLS)
    env.add_argument("name", nargs="?")
    env.set_defaults(func=cmd_env)

    cloud = subparsers.add_parser(
        "cloud",
        aliases=["sync"],
        help=t("WebDAV cloud backup / restore (encrypted credentials at rest)"),
    )
    cloud.set_defaults(func=cmd_cloud_help, _cloud_parser=cloud)
    cloud_sub = cloud.add_subparsers(dest="cloud_command")

    cloud_setup = cloud_sub.add_parser(
        "setup",
        help=t("configure WebDAV endpoint (interactive prompts for any missing fields)"),
    )
    cloud_setup.add_argument("--url", help=t("WebDAV base URL, e.g. https://dav.example.com/dav/"))
    cloud_setup.add_argument("--user", help=t("WebDAV username"))
    cloud_setup.add_argument("--password", help=t("WebDAV password (omit to be prompted)"))
    cloud_setup.add_argument(
        "--remote-dir",
        help=t("remote directory for backups (default /cc-switch/)"),
    )
    cloud_setup.add_argument(
        "--remote-filename",
        help=t("remote filename (default profiles.json)"),
    )
    cloud_setup.add_argument(
        "--insecure",
        action="store_true",
        help=t("skip TLS certificate verification (use only for self-signed staging servers)"),
    )
    cloud_setup.add_argument(
        "--pull-dir",
        help=t("remote directory where the GUI cc-switch app backs up (for 'cloud pull')"),
    )
    cloud_setup.set_defaults(func=cmd_cloud_setup)

    cloud_test = cloud_sub.add_parser("test", help=t("probe the WebDAV endpoint with current credentials"))
    cloud_test.set_defaults(func=cmd_cloud_test)

    cloud_backup = cloud_sub.add_parser("backup", help=t("upload local profiles.json to WebDAV"))
    cloud_backup.add_argument(
        "--encrypt",
        action="store_true",
        help=t("encrypt the upload with a passphrase (prompted) so the server only sees ciphertext"),
    )
    cloud_backup.add_argument(
        "--passphrase",
        help=t("passphrase for --encrypt (omit to be prompted)"),
    )
    cloud_backup.set_defaults(func=cmd_cloud_backup)

    cloud_restore = cloud_sub.add_parser(
        "restore",
        help=t("download remote profiles.json and replace local"),
    )
    cloud_restore.add_argument(
        "--passphrase",
        help=t("passphrase for --encrypt'd backups (omit to be prompted if needed)"),
    )
    cloud_restore.add_argument(
        "--force",
        action="store_true",
        help=t("overwrite local even if it has profiles missing on the remote"),
    )
    cloud_restore.set_defaults(func=cmd_cloud_restore)

    cloud_status = cloud_sub.add_parser("status", help=t("show cloud config and last sync info"))
    cloud_status.set_defaults(func=cmd_cloud_status)

    cloud_forget = cloud_sub.add_parser(
        "forget",
        help=t("remove local WebDAV credentials and sync state"),
    )
    cloud_forget.add_argument(
        "--yes",
        action="store_true",
        help=t("skip the confirmation prompt"),
    )
    cloud_forget.set_defaults(func=cmd_cloud_forget)

    cloud_pull = cloud_sub.add_parser(
        "pull",
        help=t("import profiles from a cc-switch desktop app backup (db.sql format)"),
    )
    cloud_pull.add_argument(
        "url",
        nargs="?",
        default=None,
        help=t("URL to db.sql (optional; if omitted, uses configured WebDAV + pull_dir)"),
    )
    cloud_pull.add_argument(
        "--overwrite",
        action="store_true",
        help=t("overwrite existing local profiles with the same name"),
    )
    cloud_pull.add_argument(
        "--pull-dir",
        help=t("override the pull directory for this invocation"),
    )
    cloud_pull.set_defaults(func=cmd_cloud_pull)

    return parser


def cmd_add(args: argparse.Namespace, store: ProfileStore) -> None:
    store.add_profile(
        args.tool,
        args.name,
        args.base_url,
        args.api_key,
        provider=args.provider,
        model=args.model,
    )
    print(t("Added {tool}/{name}", tool=args.tool, name=args.name))


def cmd_use(args: argparse.Namespace, store: ProfileStore) -> None:
    profile = store.set_active(args.tool, args.name)
    writer = WRITERS[args.tool]
    if args.tool == "codex":
        changed = writer.apply_profile(profile, args.name)
    else:
        changed = writer.apply_profile(profile)
    print(t("Using {tool}/{name}", tool=args.tool, name=args.name))
    for path in changed:
        print(t("Updated {path}", path=path))
    if args.tool == "codex":
        print(t("Run this in your shell if Codex does not already have OPENAI_API_KEY:"))
        print(f'eval "$(cc-switch env codex)"')


def cmd_edit(args: argparse.Namespace, store: ProfileStore) -> None:
    if not any(
        [
            args.base_url,
            args.api_key,
            args.provider,
            args.model,
            args.clear_provider,
            args.clear_model,
        ]
    ):
        raise StoreError(
            t("edit needs at least one of --base-url, --api-key, --provider, --model, --clear-provider, --clear-model")
        )
    profile = store.update_profile(
        args.tool,
        args.name,
        base_url=args.base_url,
        api_key=args.api_key,
        provider=args.provider,
        model=args.model,
        clear_provider=args.clear_provider,
        clear_model=args.clear_model,
    )
    print(t("Updated {tool}/{name}", tool=args.tool, name=args.name))
    if store.get_active_name(args.tool) == args.name:
        writer = WRITERS[args.tool]
        if args.tool == "codex":
            changed = writer.apply_profile(profile, args.name)
        else:
            changed = writer.apply_profile(profile)
        print(t("Re-applied active profile {tool}/{name}", tool=args.tool, name=args.name))
        for path in changed:
            print(t("  updated {path}", path=path))


def cmd_list(args: argparse.Namespace, store: ProfileStore) -> None:
    profiles_by_tool = store.list_profiles(args.tool)
    for tool, profiles in profiles_by_tool.items():
        active = store.get_active_name(tool)
        print(t("{tool}:", tool=tool))
        if not profiles:
            print(t("  (none)"))
            continue
        for name, profile in sorted(profiles.items()):
            marker = "*" if name == active else " "
            provider = f" provider={profile['provider']}" if profile.get("provider") else ""
            model = f" model={profile['model']}" if profile.get("model") else ""
            print(f"  {marker} {name} base_url={profile['base_url']} key={redact(profile['api_key'])}{provider}{model}")


def cmd_current(args: argparse.Namespace, store: ProfileStore) -> None:
    tools = (args.tool,) if args.tool else TOOLS
    for tool in tools:
        active = store.get_active_name(tool)
        if not active:
            print(t("{tool}: (none)", tool=tool))
            continue
        profile = store.get_profile(tool, active)
        print(f"{tool}: {active} base_url={profile['base_url']} key={redact(profile['api_key'])}")


def cmd_remove(args: argparse.Namespace, store: ProfileStore) -> None:
    store.remove_profile(args.tool, args.name)
    print(t("Removed {tool}/{name}", tool=args.tool, name=args.name))


def cmd_show(args: argparse.Namespace, store: ProfileStore) -> None:
    profile = store.get_profile(args.tool, args.name)
    safe_profile = dict(profile)
    safe_profile["api_key"] = redact(profile.get("api_key", ""))
    print(json.dumps(safe_profile, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_env(args: argparse.Namespace, store: ProfileStore) -> None:
    if args.name:
        profile = store.get_profile(args.tool, args.name)
    else:
        _, profile = store.get_active_profile(args.tool)
    exports = WRITERS[args.tool].env_exports(profile)
    for key, value in exports.items():
        print(shell_export(key, value))


def cmd_menu(args: argparse.Namespace, store: ProfileStore) -> None:
    # Imported lazily so that argparse-only invocations do not pay the
    # questionary import cost or fail when the optional dep is missing.
    from .tui import TUIUnavailable, run_tui

    try:
        run_tui()
    except TUIUnavailable as exc:
        raise StoreError(str(exc)) from exc


def cmd_upgrade(args: argparse.Namespace, store: ProfileStore) -> None:
    from .upgrade import PROJECT_URL, UpgradeError, run_upgrade

    try:
        rc = run_upgrade(method=args.method, project_url=args.project_url or PROJECT_URL)
    except UpgradeError as exc:
        raise StoreError(str(exc)) from exc
    if rc != 0:
        raise StoreError(t("Upgrade failed with exit code {code}", code=rc))


# ---------------------------------------------------------------- cloud sync


def _prompt_text(message: str, *, default: str | None = None, required: bool = True) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            value = input(f"{message}{suffix}: ").strip()
        except EOFError:
            if default is not None:
                return default
            if not required:
                return ""
            raise StoreError(
                f"missing value for '{message}' and stdin is not interactive; "
                "pass it on the command line"
            )
        if not value and default is not None:
            return default
        if value or not required:
            return value
        print("  (cannot be empty)", file=sys.stderr)


def _prompt_secret(message: str) -> str:
    while True:
        try:
            value = getpass.getpass(f"{message}: ")
        except EOFError:
            raise StoreError(
                f"missing value for '{message}' and stdin is not interactive; "
                "pass --password on the command line"
            )
        if value:
            return value
        print("  (cannot be empty)", file=sys.stderr)


def _print_status(status: dict[str, object]) -> None:
    if not status.get("configured"):
        print(t("cloud: not configured. Run 'cc-switch cloud setup'."))
        return
    if status.get("error"):
        print(t("cloud: error — {error}", error=status['error']))
        return
    print(t("cloud: configured"))
    for key in (
        "base_url",
        "username",
        "password",
        "remote_path",
        "verify_tls",
        "pull_dir",
        "last_backup",
        "last_backup_size",
        "last_backup_encrypted",
        "last_backup_etag",
        "last_restore",
    ):
        value = status.get(key)
        if value in (None, ""):
            continue
        print(f"  {key}: {value}")


def cmd_cloud_help(args: argparse.Namespace, store: ProfileStore) -> None:
    parser = getattr(args, "_cloud_parser", None)
    if parser is not None:
        parser.print_help()
    else:  # pragma: no cover - defensive
        print("Run: cc-switch cloud --help")


def cmd_cloud_setup(args: argparse.Namespace, store: ProfileStore) -> None:
    from .sync.config import WebDAVConfig
    from .sync.manager import SyncManager

    manager = SyncManager(store)
    existing = None
    if manager.is_configured():
        try:
            existing = manager.load_config()
        except StoreError:
            existing = None

    base_url = args.url or _prompt_text(
        t("WebDAV base URL"),
        default=existing.base_url if existing else None,
    )
    username = args.user or _prompt_text(
        t("Username"),
        default=existing.username if existing else None,
    )
    password = args.password
    if password is None:
        if existing and existing.password:
            keep = _prompt_text(
                t("Reuse stored password? [Y/n]"),
                default="y",
                required=False,
            ).lower()
            password = existing.password if keep in ("", "y", "yes") else _prompt_secret(t("Password"))
        else:
            password = _prompt_secret(t("Password"))
    remote_dir = args.remote_dir or _prompt_text(
        t("Remote directory"),
        default=(existing.remote_dir if existing else "/cc-switch/"),
        required=False,
    ) or "/cc-switch/"
    remote_filename = args.remote_filename or _prompt_text(
        t("Remote filename"),
        default=(existing.remote_filename if existing else "profiles.json"),
        required=False,
    ) or "profiles.json"
    verify_tls = (not args.insecure) if args.insecure else (existing.verify_tls if existing else True)
    pull_dir = args.pull_dir or _prompt_text(
        t("GUI cc-switch pull directory (blank = skip)"),
        default=(existing.pull_dir if existing else ""),
        required=False,
    )

    config = WebDAVConfig(
        base_url=base_url,
        username=username,
        password=password,
        remote_dir=remote_dir,
        remote_filename=remote_filename,
        verify_tls=verify_tls,
        pull_dir=pull_dir,
    )
    manager.save_config(config)
    print(t("Saved WebDAV config (encrypted at rest):"))
    for key, value in config.redacted_dict().items():
        print(f"  {key}: {value}")
    print(t("Run 'cc-switch cloud test' to verify connectivity."))


def cmd_cloud_test(args: argparse.Namespace, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    result = SyncManager(store).test()
    print(t("WebDAV reachable. Probed {path} (HTTP {status}).",
            path=result.remote_path, status=result.extra.get('status') if result.extra else '?'))


def cmd_cloud_backup(args: argparse.Namespace, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    passphrase: str | None = None
    if args.encrypt:
        passphrase = args.passphrase or _prompt_secret(t("Encrypt passphrase"))
    elif args.passphrase:
        passphrase = args.passphrase

    result = SyncManager(store).backup(passphrase=passphrase)
    suffix = t(" (encrypted)") if result.encrypted else ""
    print(t("Backed up {bytes} bytes to {path}{suffix}.",
            bytes=result.bytes_transferred, path=result.remote_path, suffix=suffix))


def cmd_cloud_restore(args: argparse.Namespace, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    manager = SyncManager(store)
    passphrase = args.passphrase
    try:
        result = manager.restore(passphrase=passphrase, force=args.force)
    except StoreError as exc:
        if "encrypted" in str(exc).lower() and passphrase is None and sys.stdin.isatty():
            passphrase = _prompt_secret(t("Backup passphrase"))
            result = manager.restore(passphrase=passphrase, force=args.force)
        else:
            raise

    suffix = t(" (decrypted)") if result.encrypted else ""
    print(t("Restored {bytes} bytes from {path}{suffix}.",
            bytes=result.bytes_transferred, path=result.remote_path, suffix=suffix))
    if result.backup_local_path:
        print(t("  Previous local profiles archived at: {path}", path=result.backup_local_path))


def cmd_cloud_status(args: argparse.Namespace, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    _print_status(SyncManager(store).status())


def cmd_cloud_forget(args: argparse.Namespace, store: ProfileStore) -> None:
    from .sync.manager import SyncManager

    if not args.yes and sys.stdin.isatty():
        confirm = _prompt_text(
            t("Remove stored WebDAV credentials and sync state? [y/N]"),
            default="n",
            required=False,
        ).lower()
        if confirm not in ("y", "yes"):
            print(t("Aborted."))
            return
    result = SyncManager(store).forget()
    removed = (result.extra or {}).get("removed_paths") or []
    if not removed:
        print(t("Nothing to remove (no cloud config on disk)."))
        return
    print(t("Removed:"))
    for path in removed:
        print(f"  {path}")


def cmd_cloud_pull(args: argparse.Namespace, store: ProfileStore) -> None:
    from .sync.pull import pull_from_sql

    if args.url:
        # Direct URL mode
        import urllib.request
        import urllib.error
        from urllib.parse import urlparse

        url = args.url.rstrip("/")
        parsed = urlparse(url)
        if "db.sql" not in parsed.path:
            url = parsed._replace(path=parsed.path.rstrip("/") + "/db.sql").geturl()

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cc-switch-tool/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                sql = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise StoreError(t("Failed to download db.sql: {error}", error=exc)) from exc
    else:
        # WebDAV mode — use configured credentials
        from .sync.manager import SyncManager
        from .sync.webdav import WebDAVError

        manager = SyncManager(store)
        config = manager.load_config()
        pull_dir = args.pull_dir or config.pull_dir
        if not pull_dir:
            raise StoreError(
                t("No pull directory configured. Either:\n"
                  "  1. Run 'cc-switch cloud setup' and set the pull directory, or\n"
                  "  2. Pass --pull-dir /path/on/webdav/, or\n"
                  "  3. Pass a direct URL: cc-switch cloud pull <url>")
            )
        remote_path = pull_dir.rstrip("/") + "/db.sql"
        client = manager._client(config)
        try:
            response = client.get(remote_path)
        except WebDAVError as exc:
            raise StoreError(t("Failed to download {path}: {error}", path=remote_path, error=exc)) from exc
        sql = response.body.decode("utf-8")

    result = pull_from_sql(sql, store, overwrite=args.overwrite)

    if result.added:
        print(t("Added ({count}):", count=len(result.added)))
        for label in result.added:
            print(f"  + {label}")
    if result.updated:
        print(t("Updated ({count}):", count=len(result.updated)))
        for label in result.updated:
            print(f"  ~ {label}")
    if result.active_set:
        print(t("Active profiles set:"))
        for label in result.active_set:
            print(f"  * {label}")
    if result.skipped:
        print(t("Skipped ({count}):", count=len(result.skipped)))
        for label in result.skipped:
            print(f"  - {label}")
    total = len(result.added) + len(result.updated)
    if total:
        print(f"\n{t('Done. {count} profile(s) imported. Run cc-switch list to see them.', count=total)}")
    else:
        print(t("No new profiles imported."))


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.lang:
        set_lang(args.lang)
    if args.command is None:
        # No subcommand: drop into the interactive TUI.
        from .tui import TUIUnavailable, run_tui

        try:
            return run_tui()
        except TUIUnavailable as exc:
            parser.exit(1, f"cc-switch: {exc}\n")
    store = ProfileStore()
    func: Callable[[argparse.Namespace, ProfileStore], None] = args.func
    try:
        func(args, store)
    except StoreError as exc:
        parser.exit(1, f"cc-switch: {exc}\n")
    except ValueError as exc:
        parser.exit(1, f"cc-switch: {exc}\n")
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
