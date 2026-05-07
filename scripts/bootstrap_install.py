#!/usr/bin/env python3
"""Bootstrap installer for cc-switch-tool.

This script is intentionally stdlib-only and compatible with old Python 3
versions, because its first job is to find or install a Python 3.9+ runtime.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys


MIN_PYTHON = (3, 9)
DEFAULT_PROJECT_URL = "git+https://github.com/jtmyd-top/cc-switch-tool.git"
VENV_DIR = os.path.expanduser("~/.local/share/cc-switch-tool/venv")


def main():
    parser = argparse.ArgumentParser(
        description="Install cc-switch-tool after checking for Python 3.9+."
    )
    parser.add_argument(
        "--method",
        choices=("auto", "pipx", "pip-user", "venv"),
        default="auto",
        help="installation method (default: auto)",
    )
    parser.add_argument(
        "--project-url",
        default=os.environ.get("CCS_INSTALL_URL", DEFAULT_PROJECT_URL),
        help="pip-installable project URL or path",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="answer yes to prompts")
    args = parser.parse_args()

    # When piped (curl | python3), stdin is not a tty — auto-confirm prompts
    if not sys.stdin.isatty():
        args.yes = True

    py = find_compatible_python()
    if not py:
        print("cc-switch-tool requires Python 3.9+.")
        if not confirm("No compatible Python was found. Try to install Python 3.9+ now?", args.yes):
            print("Install Python 3.9+ first, then rerun this script.")
            return 1
        if not install_python():
            print("Automatic Python installation failed or is unsupported on this system.")
            print("Please install Python 3.9+ manually, then rerun this script.")
            return 1
        py = find_compatible_python()
        if not py:
            print("Python 3.9+ still was not found after installation.")
            return 1

    version = python_version(py)
    print("Using Python: {0} ({1})".format(format_cmd(py), version or "unknown version"))

    method = args.method
    if method == "auto":
        method = "pipx" if shutil.which("pipx") else "pip-user"

    if method == "pipx":
        return install_with_pipx(py, args.project_url, args.yes)
    if method == "pip-user":
        return run(py + ["-m", "pip", "install", "--user", args.project_url])
    if method == "venv":
        return install_with_venv(py, args.project_url)
    raise AssertionError("unknown method: {0}".format(method))


def find_compatible_python():
    # If the current interpreter is good enough, use it directly.
    if sys.version_info >= MIN_PYTHON and sys.executable:
        return [sys.executable]

    candidates = []
    for name in (
        "python3.13",
        "python3.12",
        "python3.11",
        "python3.10",
        "python3.9",
        "python3",
        "python",
    ):
        path = shutil.which(name)
        if path:
            candidates.append([path])

    if platform.system() == "Windows" and shutil.which("py"):
        for version in ("3.13", "3.12", "3.11", "3.10", "3.9"):
            candidates.append(["py", "-{0}".format(version)])

    seen = set()
    for candidate in candidates:
        key = tuple(candidate)
        if key in seen:
            continue
        seen.add(key)
        if is_compatible_python(candidate):
            return candidate
    return None


def is_compatible_python(cmd):
    code = (
        "import sys; "
        "raise SystemExit(0 if sys.version_info >= ({0}, {1}) else 1)"
    ).format(MIN_PYTHON[0], MIN_PYTHON[1])
    return run_quiet(cmd + ["-c", code]) == 0


def python_version(cmd):
    code = "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    proc = subprocess.Popen(cmd + ["-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, _ = proc.communicate()
    if proc.returncode != 0:
        return ""
    return out.decode("utf-8", "replace").strip()


def install_python():
    system = platform.system()
    if system == "Darwin" and shutil.which("brew"):
        return run(["brew", "install", "python@3.12"]) == 0

    if system == "Windows" and shutil.which("winget"):
        return run(["winget", "install", "-e", "--id", "Python.Python.3.12"]) == 0

    if system == "Linux":
        if shutil.which("apt-get"):
            if run(with_sudo(["apt-get", "update"])) != 0:
                return False
            for packages in (
                ["python3.12", "python3.12-venv", "python3-pip"],
                ["python3.11", "python3.11-venv", "python3-pip"],
                ["python3.10", "python3.10-venv", "python3-pip"],
                ["python3.9", "python3.9-venv", "python3-pip"],
                ["python3", "python3-venv", "python3-pip"],
            ):
                if run(with_sudo(["apt-get", "install", "-y"] + packages)) == 0:
                    return True
            return False
        if shutil.which("dnf"):
            return run(with_sudo(["dnf", "install", "-y", "python3", "python3-pip"])) == 0
        if shutil.which("yum"):
            return run(with_sudo(["yum", "install", "-y", "python3", "python3-pip"])) == 0
        if shutil.which("pacman"):
            return run(with_sudo(["pacman", "-Sy", "--noconfirm", "python"])) == 0
        if shutil.which("zypper"):
            return run(with_sudo(["zypper", "--non-interactive", "install", "python3", "python3-pip"])) == 0
        if shutil.which("apk"):
            return run(with_sudo(["apk", "add", "python3", "py3-pip"])) == 0

    return False


def install_with_pipx(py, project_url, assume_yes):
    if len(py) != 1:
        print("pipx needs a Python executable path; falling back to pip --user.")
        return run(py + ["-m", "pip", "install", "--user", project_url])
    pipx = shutil.which("pipx")
    if not pipx:
        print("pipx was not found.")
        if not confirm("Install pipx with '{0} -m pip install --user pipx'?".format(format_cmd(py)), assume_yes):
            return 1
        rc = run(py + ["-m", "pip", "install", "--user", "pipx"])
        if rc != 0:
            return rc
        pipx = shutil.which("pipx") or os.path.expanduser("~/.local/bin/pipx")
        if not os.path.exists(pipx):
            print("pipx installed, but it is not on PATH. Falling back to pip --user.")
            return run(py + ["-m", "pip", "install", "--user", project_url])
    return run([pipx, "install", "--python", py[0], project_url])


def install_with_venv(py, project_url):
    rc = run(py + ["-m", "venv", VENV_DIR])
    if rc != 0:
        return rc
    pip = os.path.join(VENV_DIR, "Scripts" if platform.system() == "Windows" else "bin", "pip")
    rc = run([pip, "install", "--upgrade", "pip"])
    if rc != 0:
        return rc
    rc = run([pip, "install", project_url])
    if rc == 0:
        bin_dir = os.path.dirname(pip)
        print("Installed in: {0}".format(VENV_DIR))
        print("Add this directory to PATH: {0}".format(bin_dir))
        print("Command path: {0}".format(os.path.join(bin_dir, "cc-switch")))
    return rc


def confirm(prompt, assume_yes):
    if assume_yes:
        return True
    try:
        answer = input("{0} [y/N]: ".format(prompt)).strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def with_sudo(cmd):
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() != 0 and shutil.which("sudo"):
        return ["sudo"] + cmd
    return cmd


def run(cmd):
    print("+ {0}".format(format_cmd(cmd)))
    try:
        return subprocess.call(cmd)
    except OSError as exc:
        print("failed to run {0}: {1}".format(format_cmd(cmd), exc))
        return 1


def run_quiet(cmd):
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.communicate()
        return proc.returncode
    except OSError:
        return 1


def format_cmd(cmd):
    if len(cmd) == 1:
        return cmd[0]
    return " ".join(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
