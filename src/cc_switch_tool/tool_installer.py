from __future__ import annotations

import re
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass

from .i18n import t


@dataclass(frozen=True)
class CliTool:
    name: str
    command: str
    npm_package: str
    min_node_major: int


@dataclass(frozen=True)
class ToolInstallResult:
    tool: CliTool
    before_version: str
    after_version: str
    returncode: int


class ToolInstallError(RuntimeError):
    pass


class NodeInstallUnsupported(ToolInstallError):
    pass


CLI_TOOLS: tuple[CliTool, ...] = (
    CliTool("Codex CLI", "codex", "@openai/codex", 18),
    CliTool("Claude Code", "claude", "@anthropic-ai/claude-code", 18),
    CliTool("Gemini CLI", "gemini", "@google/gemini-cli", 20),
)


def required_node_major(tools: tuple[CliTool, ...] = CLI_TOOLS) -> int:
    return max(tool.min_node_major for tool in tools)


def node_version() -> str:
    node = shutil.which("node")
    if not node:
        return ""
    try:
        proc = subprocess.run(
            [node, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return ""
    return proc.stdout.strip()


def node_major(version: str) -> int:
    match = re.search(r"(\d+)", version)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def npm_path() -> str:
    return shutil.which("npm") or ""


def check_prerequisites(tools: tuple[CliTool, ...] = CLI_TOOLS) -> tuple[str, str]:
    npm = npm_path()
    if not npm:
        raise ToolInstallError(t("npm was not found on PATH."))

    version = node_version()
    major = node_major(version)
    required = required_node_major(tools)
    if major < required:
        found = version or t("not found")
        raise ToolInstallError(
            t(
                "Node.js {required}+ is required for these tools; found {found}.",
                required=required,
                found=found,
            )
        )
    return npm, version


def needs_node_install(tools: tuple[CliTool, ...] = CLI_TOOLS) -> bool:
    return not npm_path() or node_major(node_version()) < required_node_major(tools)


def install_nodejs() -> int:
    commands = node_install_commands()
    rc = 1
    for command in commands:
        rc = subprocess.call(command)
        if rc != 0:
            return rc
    return rc


def node_install_commands() -> list[list[str]]:
    system = platform.system()
    if system == "Darwin" and shutil.which("brew"):
        return [["brew", "install", "node"]]

    if system == "Windows" and shutil.which("winget"):
        return [["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS"]]

    if system == "Linux":
        if shutil.which("apt-get"):
            return _apt_node_install_commands()
        if shutil.which("dnf"):
            return [_with_sudo(["dnf", "install", "-y", "nodejs", "npm"])]
        if shutil.which("yum"):
            return [_with_sudo(["yum", "install", "-y", "nodejs", "npm"])]
        if shutil.which("pacman"):
            return [_with_sudo(["pacman", "-Sy", "--noconfirm", "nodejs", "npm"])]
        if shutil.which("zypper"):
            return [_with_sudo(["zypper", "--non-interactive", "install", "nodejs", "npm"])]
        if shutil.which("apk"):
            return [_with_sudo(["apk", "add", "nodejs", "npm"])]

    raise NodeInstallUnsupported(
        t("Automatic Node.js installation is not supported on this system.")
    )


def _apt_node_install_commands() -> list[list[str]]:
    """Install Node.js 20+ on apt systems instead of distro-old nodejs packages."""
    setup_script = (
        "set -e; "
        "mkdir -p /etc/apt/keyrings; "
        "curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key "
        "| gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg; "
        "chmod 644 /etc/apt/keyrings/nodesource.gpg; "
        "echo 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] "
        f"https://deb.nodesource.com/node_{required_node_major()}.x nodistro main' "
        "> /etc/apt/sources.list.d/nodesource.list"
    )
    return [
        _with_sudo(["apt-get", "update"]),
        _with_sudo(["apt-get", "install", "-y", "ca-certificates", "curl", "gnupg"]),
        _with_sudo(["bash", "-c", setup_script]),
        _with_sudo(["apt-get", "update"]),
        _with_sudo(["apt-get", "install", "-y", "nodejs"]),
    ]


def _with_sudo(command: list[str]) -> list[str]:
    if os.name == "nt":
        return command
    geteuid = getattr(os, "geteuid", None)
    if geteuid is not None and geteuid() == 0:
        return command
    sudo = shutil.which("sudo")
    if sudo:
        return [sudo] + command
    return command


def format_command(command: list[str]) -> str:
    return " ".join(command)


def installed_tool_version(command: str) -> str:
    executable = shutil.which(command)
    if not executable:
        return ""
    try:
        proc = subprocess.run(
            [executable, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return " ".join(proc.stdout.strip().split())


def install_or_update_tool(tool: CliTool, npm: str) -> ToolInstallResult:
    before = installed_tool_version(tool.command)
    command = [npm, "install", "-g", f"{tool.npm_package}@latest"]
    rc = subprocess.call(command)
    after = installed_tool_version(tool.command)
    return ToolInstallResult(tool=tool, before_version=before, after_version=after, returncode=rc)


def install_or_update_all() -> list[ToolInstallResult]:
    npm, _ = check_prerequisites()
    return [install_or_update_tool(tool, npm) for tool in CLI_TOOLS]


def format_version(version: str) -> str:
    return version or t("not installed")
