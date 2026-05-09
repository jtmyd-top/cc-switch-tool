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
    before = installed_version()
    if before:
        print(t("Current version: {version}", version=before))
    print(t("Upgrade method: {method}", method=plan.method))
    if plan.note:
        print(plan.note)
    if plan.method == "pip" and not _ensure_pip_available():
        return 1
    print(t("Running: {command}", command=" ".join(plan.command)))
    rc = subprocess.call(plan.command)
    if rc != 0:
        return rc

    after = installed_version()
    if not after:
        print(t("Upgrade completed, but the installed version could not be verified."))
    elif before and before != after:
        print(t("Upgrade verified: {before} -> {after}", before=before, after=after))
    else:
        print(
            t(
                "Upgrade completed, but the version is still {version}. "
                "You may already be on the latest release, or the package version was not bumped.",
                version=after,
            )
        )
    return 0


def installed_version() -> str:
    code = (
        "import importlib.metadata as m; "
        f"print(m.version({PACKAGE_NAME!r}))"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _current_python_pip_plan(project_url: str) -> UpgradePlan:
    command = [sys.executable, "-m", "pip", "install", "--upgrade", project_url]
    note = t("Upgrading the current Python environment.")
    if not _inside_virtualenv():
        command.insert(5, "--user")
        note = t("Upgrading the current user installation.")
    return UpgradePlan("pip", command, note)


def _inside_virtualenv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _ensure_pip_available() -> bool:
    if _pip_works():
        return True

    print(t("Current Python pip is broken; trying to repair it with ensurepip."))
    command = [sys.executable, "-m", "ensurepip", "--upgrade"]
    if not _inside_virtualenv():
        command.append("--user")
    print(t("Running: {command}", command=" ".join(command)))
    rc = subprocess.call(command)
    if rc == 0 and _pip_works():
        return True

    print(t("Could not repair pip for the current Python."))
    print(t("Try reinstalling with the bootstrap installer or pipx."))
    return False


def _pip_works() -> bool:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return proc.returncode == 0


def _looks_like_pipx_install() -> bool:
    prefix = os.path.normcase(os.path.abspath(sys.prefix))
    parts = set(prefix.split(os.sep))
    return "pipx" in parts and "venvs" in parts and PACKAGE_NAME in parts
