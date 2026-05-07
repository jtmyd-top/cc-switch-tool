"""Lightweight gettext-style i18n for cc-switch-tool.

The translation key IS the English source string. Lookup falls back to the
key itself when no translation is registered, so a missing zh entry simply
prints English rather than crashing.

Language is chosen, in order:

1. ``CCS_LANG`` env var (``zh`` / ``en``).
2. ``~/.cc-switch-tool/settings.json`` → ``lang`` field.
3. Default: ``zh`` (the tool's primary audience).

Use :func:`t` for static strings and :func:`tf` (or pass ``**kwargs``) for
strings with ``str.format``-style placeholders.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_VALID_LANGS = ("zh", "en")
_SETTINGS_PATH = Path("~/.cc-switch-tool/settings.json")


def _read_saved_lang() -> str | None:
    try:
        data = json.loads(_SETTINGS_PATH.expanduser().read_text(encoding="utf-8"))
        lang = str(data.get("lang", "")).strip().lower()
        if lang in _VALID_LANGS:
            return lang
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return None


def _detect_lang() -> str:
    raw = (os.environ.get("CCS_LANG") or "").strip().lower()
    if raw in _VALID_LANGS:
        return raw
    if raw.startswith("zh"):
        return "zh"
    if raw.startswith("en"):
        return "en"
    saved = _read_saved_lang()
    if saved:
        return saved
    return "zh"


def save_lang(lang: str) -> None:
    """Persist language choice to settings.json."""
    path = _SETTINGS_PATH.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    data["lang"] = lang
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


LANG = _detect_lang()


# ----------------------------------------------------------------- translations
# Keys are the English source string. Keep them in sync with the call sites.

_ZH: dict[str, str] = {
    # ----------- argparse top-level
    "Switch relay endpoint profiles for Claude Code, Codex CLI, and Gemini CLI. "
    "Run without arguments for an interactive menu.":
        "切换 Claude Code / Codex CLI / Gemini CLI 的中转站点配置。"
        "不带参数运行可进入交互式菜单。",
    "open the interactive TUI (default with no args)":
        "打开交互式菜单（不带参数时的默认行为）",
    "add or update a profile": "添加或更新一个站点配置",
    "Codex provider id; defaults to profile name":
        "Codex 的 provider id；不填则使用配置名",
    "model name (Codex writes to config.toml, Claude sets ANTHROPIC_MODEL)":
        "模型名（Codex 写入 config.toml，Claude 设置 ANTHROPIC_MODEL）",
    "activate a profile and write tool config": "启用某个配置并写入对应工具的设置",
    "modify an existing profile (any subset of fields)":
        "修改已有配置（任意字段子集）",
    "Codex provider id (use --clear-provider to drop)":
        "Codex 的 provider id（用 --clear-provider 清除）",
    "model name (use --clear-model to drop)":
        "模型名（用 --clear-model 清除）",
    "list profiles": "列出全部配置",
    "show active profile": "显示当前生效的配置",
    "remove a profile": "删除一个配置",
    "show a profile with the API key redacted": "显示某个配置（API key 已脱敏）",
    "print shell exports for a profile": "打印某个配置的环境变量（用于 eval）",

    # ----------- argparse cloud sync
    "WebDAV cloud backup / restore (encrypted credentials at rest)":
        "WebDAV 云备份 / 恢复（凭据本地加密存储）",
    "configure WebDAV endpoint (interactive prompts for any missing fields)":
        "配置 WebDAV 端点（缺失字段会以交互方式询问）",
    "WebDAV base URL, e.g. https://dav.example.com/dav/":
        "WebDAV 根 URL，如 https://dav.example.com/dav/",
    "WebDAV username": "WebDAV 用户名",
    "WebDAV password (omit to be prompted)": "WebDAV 密码（不填会交互询问）",
    "remote directory for backups (default /cc-switch/)":
        "备份用的远端目录（默认 /cc-switch/）",
    "remote filename (default profiles.json)":
        "远端文件名（默认 profiles.json）",
    "skip TLS certificate verification (use only for self-signed staging servers)":
        "跳过 TLS 证书校验（仅用于自签名/测试服务器）",
    "probe the WebDAV endpoint with current credentials":
        "用当前凭据探测 WebDAV 端点",
    "upload local profiles.json to WebDAV": "把本地 profiles.json 上传到 WebDAV",
    "encrypt the upload with a passphrase (prompted) so the server only sees ciphertext":
        "用 passphrase 加密后再上传，服务端只能看到密文（会交互询问 passphrase）",
    "passphrase for --encrypt (omit to be prompted)":
        "--encrypt 用的 passphrase（不填会交互询问）",
    "download remote profiles.json and replace local":
        "从远端下载 profiles.json 并覆盖本地",
    "passphrase for --encrypt'd backups (omit to be prompted if needed)":
        "已加密备份的 passphrase（必要时会交互询问）",
    "overwrite local even if it has profiles missing on the remote":
        "即使本地有远端没有的配置也强制覆盖",
    "show cloud config and last sync info": "显示云端配置和最近的同步信息",
    "remove local WebDAV credentials and sync state":
        "删除本地的 WebDAV 凭据和同步状态",
    "skip the confirmation prompt": "跳过确认提示",

    # ----------- cli outputs (cmd_*)
    "Added {tool}/{name}": "已添加 {tool}/{name}",
    "Using {tool}/{name}": "已切换到 {tool}/{name}",
    "Updated {path}": "已更新 {path}",
    "Run this in your shell if Codex does not already have OPENAI_API_KEY:":
        "如果当前 shell 还没有 OPENAI_API_KEY，请运行：",
    "Re-applied active profile {tool}/{name}":
        "已重新应用生效配置 {tool}/{name}",
    "  updated {path}": "  已更新 {path}",
    "Removed {tool}/{name}": "已删除 {tool}/{name}",
    "  (cannot be empty)": "  （不能为空）",
    "missing value for '{message}' and stdin is not interactive; pass it on the command line":
        "缺少 '{message}' 的值，且当前 stdin 不是交互式；请在命令行直接传入",
    "missing value for '{message}' and stdin is not interactive; pass --password on the command line":
        "缺少 '{message}' 的值，且当前 stdin 不是交互式；请在命令行用 --password 传入",
    "edit needs at least one of --base-url, --api-key, --provider, --model, --clear-provider, --clear-model":
        "edit 至少需要 --base-url、--api-key、--provider、--model、--clear-provider、--clear-model 之一",

    # cloud cli outputs
    "cloud: not configured. Run 'cc-switch cloud setup'.":
        "云同步：尚未配置。请运行 'cc-switch cloud setup'。",
    "cloud: error — {error}": "云同步：错误 — {error}",
    "cloud: configured": "云同步：已配置",
    "Saved WebDAV config (encrypted at rest):": "已保存 WebDAV 配置（落盘加密）：",
    "Run 'cc-switch cloud test' to verify connectivity.":
        "可运行 'cc-switch cloud test' 验证连通性。",
    "WebDAV reachable. Probed {path} (HTTP {status}).":
        "WebDAV 可达。已探测 {path}（HTTP {status}）。",
    "Backed up {bytes} bytes to {path}{suffix}.":
        "已备份 {bytes} 字节到 {path}{suffix}。",
    " (encrypted)": "（已加密）",
    "Restored {bytes} bytes from {path}{suffix}.":
        "已从 {path} 恢复 {bytes} 字节{suffix}。",
    " (decrypted)": "（已解密）",
    "  Previous local profiles archived at: {path}":
        "  原本地配置已归档到：{path}",
    "Aborted.": "已取消。",
    "Removed:": "已删除：",
    "Nothing to remove (no cloud config on disk).":
        "无可删除内容（磁盘上没有云端配置）。",

    # cli prompts
    "WebDAV base URL": "WebDAV 根 URL",
    "Username": "用户名",
    "Password": "密码",
    "Reuse stored password? [Y/n]": "继续使用已保存的密码？[Y/n]",
    "Remote directory": "远端目录",
    "Remote filename": "远端文件名",
    "Encrypt passphrase": "加密 passphrase",
    "Backup passphrase": "备份的 passphrase",
    "Remove stored WebDAV credentials and sync state? [y/N]":
        "删除本地的 WebDAV 凭据和同步状态？[y/N]",

    # ----------- TUI labels and prompts
    "questionary is required for the interactive TUI. "
    "Reinstall with: pipx install --force cc-switch-tool":
        "交互式菜单需要 questionary。请重装：pipx install --force cc-switch-tool",
    "interactive TUI requires a TTY": "交互式菜单需要在 TTY 终端中运行",
    "API key cannot be empty.": "API key 不能为空。",
    "Cannot be empty": "不能为空",
    "Profile name for {tool}:": "为 {tool} 起一个配置名：",
    "Base URL:": "Base URL：",
    "API key:": "API key：",
    "Provider id (blank = use profile name):":
        "Provider id（留空 = 用配置名）：",
    "Model (optional):": "模型名（可选）：",
    "Remove which {tool} profile?": "删除哪个 {tool} 配置？",
    "Really remove {tool}/{target}?": "真的要删除 {tool}/{target} 吗？",
    "Activate {tool}/{name} now?": "现在启用 {tool}/{name}？",
    "+ add new profile": "+ 新增配置",
    "~ edit profile": "~ 编辑配置",
    "- remove profile": "- 删除配置",
    "« back": "« 返回",
    "« cancel": "« 取消",
    "{tool} profiles  (active: {active})": "{tool} 配置  （当前：{active}）",
    "Error: {error}": "错误：{error}",
    'hint: run  eval "$(cc-switch env codex)"  '
    "if your shell does not have OPENAI_API_KEY yet":
        '提示：如果当前 shell 还没有 OPENAI_API_KEY，'
        '运行  eval "$(cc-switch env codex)"',
    "cc-switch — pick a tool": "cc-switch — 选择一个工具",
    "quit": "退出",

    # TUI edit-profile prompts
    "New base URL (leave empty to keep current):":
        "新的 Base URL（留空表示不改）：",
    "New API key (leave empty to keep current):":
        "新的 API key（留空表示不改）：",
    "New provider (leave empty to keep current):":
        "新的 provider（留空表示不改）：",
    "New model (leave empty to keep current):":
        "新的 model（留空表示不改）：",
    "Edit which {tool} profile?": "编辑哪个 {tool} 配置？",
    "Updated {tool}/{name}": "已更新 {tool}/{name}",

    # TUI cloud sync labels
    "☁ cloud sync (WebDAV)    [not configured]":
        "☁ 云同步 (WebDAV)    [未配置]",
    "☁ cloud sync (WebDAV)    [error: {error}]":
        "☁ 云同步 (WebDAV)    [错误：{error}]",
    "☁ cloud sync (WebDAV)    url={url}  user={user}  last={last}":
        "☁ 云同步 (WebDAV)    url={url}  用户={user}  上次同步={last}",
    "☁ cloud sync": "☁ 云同步",
    "☁ cloud sync — {url} (user={user})": "☁ 云同步 — {url}（用户={user}）",
    "☁ cloud sync — error: {error}": "☁ 云同步 — 错误：{error}",
    "  warning: existing config unreadable ({error})":
        "  警告：现有配置无法读取（{error}）",
    "WebDAV base URL:": "WebDAV 根 URL：",
    "Username:": "用户名：",
    "Keep stored password?": "继续使用已保存的密码？",
    "Password:": "密码：",
    "Password cannot be empty.": "密码不能为空。",
    "Remote directory:": "远端目录：",
    "Remote filename:": "远端文件名：",
    "Verify TLS certificates?": "校验 TLS 证书？",
    "Saved (encrypted at rest).": "已保存（落盘加密）。",
    "Encrypt the upload with a passphrase? (recommended for shared servers)":
        "是否用 passphrase 加密后再上传？（共享服务器场景推荐）",
    "Passphrase:": "Passphrase：",
    "Confirm passphrase:": "再输一次 passphrase：",
    "Passphrase cannot be empty.": "passphrase 不能为空。",
    "Passphrases did not match.": "两次输入的 passphrase 不一致。",
    "Restore will overwrite local profiles.json (a timestamped backup is kept). Continue?":
        "恢复会覆盖本地的 profiles.json（会留一个带时间戳的备份），继续？",
    "Force overwrite even if local has profiles missing on the remote?":
        "本地有远端没有的配置时也强制覆盖？",
    "Backup passphrase:": "备份的 passphrase：",
    "Remove stored WebDAV credentials and sync state?":
        "删除本地的 WebDAV 凭据和同步状态？",
    "Nothing to remove.": "无可删除内容。",
    "not configured": "未配置",
    "error: {error}": "错误：{error}",
    "↑ backup now": "↑ 立即备份",
    "↓ restore (overwrite local)": "↓ 恢复（覆盖本地）",
    "✓ test connection": "✓ 测试连接",
    "i status": "i 状态",
    "✎ edit settings": "✎ 编辑配置",
    "✗ forget settings": "✗ 忘记配置",
    "+ setup WebDAV": "+ 配置 WebDAV",

    # TUI status keys
    "  {key}: {value}": "  {key}: {value}",

    # TUI add-profile success
    "Added {tool}/{name}": "已添加 {tool}/{name}",
    "Removed {tool}/{name}": "已删除 {tool}/{name}",

    # ----------- store.py errors
    "Unsupported tool: {tool}. Choose one of: {tools}":
        "不支持的工具：{tool}。可选：{tools}",
    "Profile name cannot be empty": "配置名不能为空",
    "--base-url is required": "--base-url 必填",
    "--api-key is required": "--api-key 必填",
    "Profile not found: {tool}/{name}": "找不到配置：{tool}/{name}",
    "No active profile for {tool}": "{tool} 没有生效中的配置",

    # ----------- writers/common.py
    "{path} must contain a JSON object": "{path} 必须是一个 JSON 对象",

    # ----------- sync errors (manager.py / config.py / crypto.py / webdav.py)
    "Remote backup is encrypted; pass --passphrase (or enter it in the TUI).":
        "远端备份是加密的；请加 --passphrase（或在 TUI 里输入）。",
    "Remote payload is not valid JSON. If you encrypted the backup, pass --passphrase.":
        "远端内容不是合法的 JSON。如果是加密备份，请加 --passphrase。",
    "Remote payload is JSON but not an object; refusing to restore.":
        "远端内容是 JSON 但不是对象，已拒绝恢复。",
    "Local profiles not present in the remote backup: {missing}{more}. "
    "Re-run with --force to overwrite anyway, "
    "or run 'cc-switch sync backup' first to push them up.":
        "本地有这些配置不在远端备份中：{missing}{more}。"
        "加 --force 可强制覆盖，或先运行 'cc-switch sync backup' 把它们推上去。",
    "WebDAV is not configured yet. Run 'cc-switch sync setup' first.":
        "尚未配置 WebDAV。请先运行 'cc-switch sync setup'。",
    "webdav.enc is empty; re-run 'cc-switch sync setup'.":
        "webdav.enc 为空；请重新运行 'cc-switch sync setup'。",
    "decrypted webdav.enc is not valid JSON":
        "解密后的 webdav.enc 不是合法 JSON",
    "missing required field: {field}": "缺少必填字段：{field}",

    "The 'cryptography' package is required for cloud sync. "
    "Reinstall with: pipx install --force cc-switch-tool":
        "云同步需要 'cryptography' 包。请重装：pipx install --force cc-switch-tool",
    "Cannot decrypt with the current machine key. "
    "If you moved the keyring or changed hosts, run "
    "'cc-switch sync setup' again.":
        "无法用当前机器密钥解密。如果换了机器或挪动过 keyring，"
        "请重新运行 'cc-switch sync setup'。",
    "Wrong passphrase or corrupted ciphertext.":
        "passphrase 错误，或密文已损坏。",

    "401 Unauthorized — check WebDAV username/password":
        "401 未授权 — 请检查 WebDAV 用户名/密码",
    "403 Forbidden — the account is authenticated but cannot access this path":
        "403 禁止访问 — 账号已通过认证但无权访问该路径",
    "404 Not Found — the remote file or directory doesn't exist":
        "404 未找到 — 远端文件或目录不存在",
    "405 Method Not Allowed — endpoint may not be a WebDAV server":
        "405 方法不被允许 — 端点可能不是 WebDAV 服务器",
    "507 Insufficient Storage — the WebDAV server reported it is full":
        "507 存储空间不足 — WebDAV 服务器报告空间已满",
    "network error: {reason}": "网络错误：{reason}",
    "timeout after {seconds:g}s": "{seconds:g}s 后超时",
    "WebDAV test failed: {error}": "WebDAV 测试失败：{error}",
    "WebDAV backup failed: {error}": "WebDAV 备份失败：{error}",
    "WebDAV restore failed: {error}": "WebDAV 恢复失败：{error}",

    # ----------- list/current/show output
    "{tool}:": "{tool}：",
    "  (none)": "  （无）",
    "{tool}: (none)": "{tool}：（无）",

    # ----------- cloud pull
    "import profiles from a cc-switch desktop app backup (db.sql format)":
        "从 cc-switch 桌面版备份（db.sql 格式）导入配置",
    "URL to db.sql (optional; if omitted, uses configured WebDAV + pull_dir)":
        "db.sql 的 URL（可选；不填则使用已配置的 WebDAV + pull_dir）",
    "overwrite existing local profiles with the same name":
        "覆盖本地同名配置",
    "override the pull directory for this invocation":
        "本次临时指定 pull 目录",
    "remote directory where the GUI cc-switch app backs up (for 'cloud pull')":
        "GUI 版 cc-switch 的备份目录（用于 'cloud pull'）",
    "GUI cc-switch pull directory (blank = skip)":
        "GUI 版 cc-switch 的 pull 目录（留空跳过）",
    "No pull directory configured. Either:\n"
    "  1. Run 'cc-switch cloud setup' and set the pull directory, or\n"
    "  2. Pass --pull-dir /path/on/webdav/, or\n"
    "  3. Pass a direct URL: cc-switch cloud pull <url>":
        "未配置 pull 目录。请选择：\n"
        "  1. 运行 'cc-switch cloud setup' 设置 pull 目录，或\n"
        "  2. 传 --pull-dir /webdav上的路径/，或\n"
        "  3. 直接传 URL：cc-switch cloud pull <url>",
    "Failed to download db.sql: {error}": "下载 db.sql 失败：{error}",
    "Failed to download {path}: {error}": "下载 {path} 失败：{error}",
    "Added ({count}):": "已添加（{count}）：",
    "Updated ({count}):": "已更新（{count}）：",
    "Active profiles set:": "已设为当前生效：",
    "Skipped ({count}):": "已跳过（{count}）：",
    "Done. {count} profile(s) imported. Run cc-switch list to see them.":
        "完成。已导入 {count} 个配置。运行 'cc-switch list' 查看。",
    "No new profiles imported.": "没有新配置被导入。",
    # ----------- cloud pull TUI
    "↙ pull from GUI backup": "↙ 从 GUI 备份导入",
    "Pull directory not configured. Edit settings to set it.":
        "未配置 pull 目录。请编辑设置填写。",
    "Overwrite existing profiles with the same name?":
        "覆盖同名的已有配置？",
    "No new profiles to import.": "没有新配置可导入。",
    "Pull path reachable: {path} (HTTP {status})":
        "Pull 路径可达：{path}（HTTP {status}）",
    "Pull path failed: {path} — {error}":
        "Pull 路径失败：{path} — {error}",
    # ----------- language menu
    "⚙ language / 语言: {lang}": "⚙ 语言 / language: {lang}",
    "Select language / 选择语言": "选择语言 / Select language",
    "Language set to: {lang}": "语言已设为：{lang}",
}


_TABLES: dict[str, dict[str, str]] = {
    "zh": _ZH,
    "en": {},
}


def t(key: str, **kwargs: Any) -> str:
    """Translate ``key`` for the active language and apply ``str.format``.

    Falls back to the key (English source) when the lang has no entry.
    """
    table = _TABLES.get(LANG, _TABLES["en"])
    template = table.get(key, key)
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        # Defensive: bad placeholder in translation should never crash the CLI.
        return key.format(**kwargs)


def set_lang(lang: str) -> None:
    """Test/runtime helper to flip language without re-importing the module."""
    global LANG
    if lang in _VALID_LANGS:
        LANG = lang
