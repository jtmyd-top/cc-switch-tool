from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from .i18n import t


PROJECT_URL = "git+https://github.com/jtmyd-top/cc-switch-tool.git"
PACKAGE_NAME = "cc-switch-tool"


@dataclass(frozen=True)
class UpgradePlan:
    method: str
    command: list[str]
    note: str = ""


class UpgradeError(RuntimeError):
    pass


def plan_upgrade(method: str = "auto", project_url: str = PROJECT_URL) -> UpgradePlan:
    if method not in ("auto", "pipx", "pip"):
        raise UpgradeError(t("Unsupported upgrade method: {method}", method=method))

    if method == "pipx":
        pipx = shutil.which("pipx")
        if not pipx:
            raise UpgradeError(t("pipx was not found on PATH."))
        return UpgradePlan("pipx", [pipx, "upgrade", PACKAGE_NAME])

    if method == "pip":
        return _current_python_pip_plan(project_url)

    pipx = shutil.which("pipx")
    if pipx and _looks_like_pipx_install():
        return UpgradePlan("pipx", [pipx, "upgrade", PACKAGE_NAME])

    return _current_python_pip_plan(project_url)


def run_upgrade(method: str = "auto", project_url: str = PROJECT_URL) -> int:
    plan = plan_upgrade(method=method, project_url=project_url)
    return execute_plan(plan)


def execute_plan(plan: UpgradePlan) -> int:
    print(t("Upgrade method: {method}", method=plan.method))
    if plan.note:
        print(plan.note)
    print(t("Running: {command}", command=" ".join(plan.command)))
    return subprocess.call(plan.command)


def _current_python_pip_plan(project_url: str) -> UpgradePlan:
    command = [sys.executable, "-m", "pip", "install", "--upgrade", project_url]
    note = t("Upgrading the current Python environment.")
    if not _inside_virtualenv():
        command.insert(5, "--user")
        note = t("Upgrading the current user installation.")
    return UpgradePlan("pip", command, note)


def _inside_virtualenv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _looks_like_pipx_install() -> bool:
    prefix = os.path.normcase(os.path.abspath(sys.prefix))
    parts = set(prefix.split(os.sep))
    return "pipx" in parts and "venvs" in parts and PACKAGE_NAME in parts
