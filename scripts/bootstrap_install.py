#!/usr/bin/env python3
"""Bootstrap installer for cc-switch-tool.

This script is intentionally stdlib-only and compatible with old Python 3
versions, because its first job is to find or install a Python 3.9+ runtime.
"""

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys


MIN_PYTHON = (3, 9)
DEFAULT_PROJECT_URL = "git+https://github.com/jtmyd-top/cc-switch-tool.git"
VENV_DIR = os.path.expanduser("~/.local/share/cc-switch-tool/venv")

NODE_REQUIRED_MAJOR = 20
NPM_PACKAGES = (
    ("Codex CLI", "codex", "@openai/codex"),
    ("Claude Code", "claude", "@anthropic-ai/claude-code"),
    ("Gemini CLI", "gemini", "@google/gemini-cli"),
)


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
    parser.add_argument(
        "--skip-clis",
        action="store_true",
        help="skip installing the bundled AI CLI tools (codex, claude, gemini)",
    )
    parser.add_argument(
        "--only-clis",
        action="store_true",
        help="only install/update Node.js and the bundled AI CLI tools",
    )
    args = parser.parse_args()

    # When piped (curl | python3), stdin is not a tty — auto-confirm prompts
    if not sys.stdin.isatty():
        args.yes = True

    if args.only_clis:
        install_node_clis(args.yes)
        return 0

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
        rc = install_with_pipx(py, args.project_url, args.yes)
    elif method == "pip-user":
        rc = pip_install_user(py, args.project_url)
    elif method == "venv":
        rc = install_with_venv(py, args.project_url)
    else:
        raise AssertionError("unknown method: {0}".format(method))

    if rc != 0:
        if not args.skip_clis:
            print("")
            print("cc-switch-tool installation failed; continuing with AI CLI tools.")
            install_node_clis(args.yes)
        return rc

    post_install_fixup()
    if not args.skip_clis:
        install_node_clis(args.yes)
    return 0


def post_install_fixup():
    """Remove stale copies and ensure installed commands stay usable."""
    user_bin = os.path.expanduser("~/.local/bin")

    # Remove old copies in system paths that would shadow the new install
    for stale in ("/usr/local/bin/ccs", "/usr/local/bin/cc-switch"):
        if os.path.exists(stale):
            real = os.path.realpath(stale)
            new_copy = os.path.join(user_bin, os.path.basename(stale))
            if os.path.exists(new_copy) and os.path.realpath(new_copy) != real:
                print("Removing stale {0} (shadowed by {1})".format(stale, new_copy))
                try:
                    os.remove(stale)
                except OSError:
                    run_quiet(with_sudo(["rm", "-f", stale]))

    ensure_system_links(user_bin)
    ensure_user_bin_on_path(user_bin)

    # Verify installation
    for cmd_name in ("ccs", "cc-switch"):
        found = shutil.which(cmd_name)
        if found:
            print("Installed: {0}".format(found))
        else:
            print("Warning: {0} not found on PATH.".format(cmd_name))


def ensure_system_links(user_bin):
    """Expose commands through a stable system PATH directory when possible."""
    if os.name == "nt":
        return

    for system_bin in candidate_system_bins():
        if not os.path.isdir(system_bin):
            continue
        linked_any = False
        for cmd_name in ("ccs", "cc-switch"):
            source = os.path.join(user_bin, cmd_name)
            target = os.path.join(system_bin, cmd_name)
            if not os.path.exists(source):
                continue
            if os.path.islink(target) and os.path.realpath(target) == os.path.realpath(source):
                linked_any = True
                continue
            if os.path.exists(target) and not os.path.islink(target):
                print("Skipping existing non-symlink command: {0}".format(target))
                continue
            rc = run_quiet(with_sudo(["ln", "-sf", source, target]))
            if rc == 0:
                linked_any = True
                print("Linked: {0} -> {1}".format(target, source))
        if linked_any:
            break


def ensure_user_bin_on_path(user_bin):
    """Make ~/.local/bin available now and in future shell sessions."""
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if user_bin not in path_dirs:
        os.environ["PATH"] = user_bin + os.pathsep + os.environ.get("PATH", "")
        print("Added {0} to PATH for this session.".format(user_bin))

    block = (
        "# cc-switch-tool\n"
        'case ":$PATH:" in\n'
        '  *":$HOME/.local/bin:"*) ;;\n'
        '  *) export PATH="$HOME/.local/bin:$PATH" ;;\n'
        "esac"
    )
    profile_d_path = "/etc/profile.d/cc-switch-tool.sh"
    if write_system_profile_block(profile_d_path, block):
        return

    for profile_path in ("~/.profile", "~/.bash_profile", "~/.bashrc"):
        append_shell_block(os.path.expanduser(profile_path), block)


def candidate_system_bins():
    path_dirs = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    preferred = ["/usr/local/bin", "/usr/bin"]
    seen = set()
    result = []
    for directory in preferred + path_dirs:
        if directory in seen:
            continue
        seen.add(directory)
        if directory.startswith("/usr/") and directory.endswith("/bin"):
            result.append(directory)
    return result


def write_system_profile_block(path, block):
    if os.name == "nt":
        return False
    if not os.path.isdir(os.path.dirname(path)):
        return False
    try:
        content = ""
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
            if "# cc-switch-tool" in content:
                return True
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(block + "\n")
        print("Updated system profile: {0}".format(path))
        return True
    except OSError:
        pass

    tmp_path = "/tmp/cc-switch-tool-profile.sh"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(block + "\n")
    except OSError as exc:
        print("Warning: could not prepare system profile update: {0}".format(exc))
        return False

    rc = run_quiet(with_sudo(["install", "-m", "0644", tmp_path, path]))
    try:
        os.remove(tmp_path)
    except OSError:
        pass
    if rc == 0:
        print("Updated system profile: {0}".format(path))
        return True
    return False


def append_shell_block(path, block):
    marker = "# cc-switch-tool"
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
            if marker in content:
                return
        else:
            content = ""
        with open(path, "a", encoding="utf-8") as handle:
            if content and not content.endswith("\n"):
                handle.write("\n")
            handle.write("\n{0}\n".format(block))
        print("Updated shell profile: {0}".format(path))
    except OSError as exc:
        print("Warning: could not update {0}: {1}".format(path, exc))


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
        return pip_install_user(py, project_url)

    # Old pipx (< 1.0) cannot install from git URLs. Check version first.
    pipx = shutil.which("pipx")
    if pipx and not _pipx_supports_urls(pipx):
        print("System pipx is too old for git URLs. Installing with pip --user.")
        return pip_install_user(py, project_url)

    # Try pipx via the compatible Python module (avoids old system pipx)
    pipx_via_module = _pipx_module_available(py)
    if pipx_via_module:
        rc = run(py + ["-m", "pipx", "install", project_url])
        if rc == 0:
            return 0
        print("pipx module install failed; falling back to pip --user.")
        return pip_install_user(py, project_url)

    if not pipx:
        print("pipx was not found.")
        if not confirm("Install pipx with '{0} -m pip install --user pipx'?".format(format_cmd(py)), assume_yes):
            return 1
        rc = pip_install_user(py, "pipx")
        if rc != 0:
            print("Failed to install pipx. Falling back to pip --user.")
            return pip_install_user(py, project_url)
        pipx = shutil.which("pipx") or os.path.expanduser("~/.local/bin/pipx")
        if not os.path.exists(pipx):
            print("pipx installed, but it is not on PATH. Falling back to pip --user.")
            return pip_install_user(py, project_url)

    rc = run([pipx, "install", "--python", py[0], project_url])
    if rc != 0:
        print("pipx install failed. Falling back to pip --user.")
        return pip_install_user(py, project_url)
    return 0


def _pipx_module_available(py):
    code = "import importlib; importlib.import_module('pipx')"
    return run_quiet(py + ["-c", code]) == 0


def _pipx_supports_urls(pipx_path):
    """Check if pipx version >= 1.0 (supports git URLs)."""
    try:
        proc = subprocess.Popen(
            [pipx_path, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        out, _ = proc.communicate()
        version_str = out.decode("utf-8", "replace").strip()
        major = int(version_str.split(".")[0])
        return major >= 1
    except (OSError, ValueError, IndexError):
        return False


def pip_install_user(py, project_url):
    """Install a package with `py -m pip install --user`, bootstrapping pip first if missing."""
    if not ensure_pip(py):
        print("Could not bootstrap pip for {0}.".format(format_cmd(py)))
        print("Install pip manually (e.g. 'sudo apt-get install python3-pip'), then rerun.")
        return 1
    return run(py + ["-m", "pip", "install", "--user", project_url])


def ensure_pip(py):
    """Make sure `py -m pip` works. Returns True on success."""
    if _pip_available(py):
        return True
    print("pip not available in {0}; attempting to bootstrap it.".format(format_cmd(py)))

    # 1. ensurepip ships with most Python builds and is the cleanest path.
    rc = run(py + ["-m", "ensurepip", "--upgrade", "--default-pip"])
    if rc == 0 and _pip_available(py):
        return True

    # 2. Try the OS package manager (covers Ubuntu's split python3.X-distutils issue).
    if _try_install_pip_via_os(py) and _pip_available(py):
        return True

    # 3. Last resort: download get-pip.py and run it.
    if _try_get_pip(py) and _pip_available(py):
        return True

    return False


def _pip_available(py):
    return run_quiet(py + ["-m", "pip", "--version"]) == 0


def _python_minor(py):
    """Return e.g. '3.9' for the given Python, or '' if undetectable."""
    ver = python_version(py)
    parts = ver.split(".") if ver else []
    if len(parts) >= 2:
        return "{0}.{1}".format(parts[0], parts[1])
    return ""


def _try_install_pip_via_os(py):
    system = platform.system()
    if system != "Linux":
        return False
    minor = _python_minor(py)  # e.g. '3.9'

    if shutil.which("apt-get"):
        # On Ubuntu, pip for python3.X often needs python3.X-distutils too.
        candidate_sets = []
        if minor:
            candidate_sets.append(["python{0}-distutils".format(minor), "python3-pip"])
            candidate_sets.append(["python{0}-pip".format(minor)])
        candidate_sets.append(["python3-pip"])
        for pkgs in candidate_sets:
            if run(with_sudo(["apt-get", "install", "-y"] + pkgs)) == 0:
                return True
        return False
    if shutil.which("dnf"):
        return run(with_sudo(["dnf", "install", "-y", "python3-pip"])) == 0
    if shutil.which("yum"):
        return run(with_sudo(["yum", "install", "-y", "python3-pip"])) == 0
    if shutil.which("pacman"):
        return run(with_sudo(["pacman", "-Sy", "--noconfirm", "python-pip"])) == 0
    if shutil.which("zypper"):
        return run(with_sudo(["zypper", "--non-interactive", "install", "python3-pip"])) == 0
    if shutil.which("apk"):
        return run(with_sudo(["apk", "add", "py3-pip"])) == 0
    return False


def _try_get_pip(py):
    """Download get-pip.py from pypa.io and execute it as a last-resort bootstrap."""
    import tempfile
    try:
        import urllib.request
    except ImportError:
        return False

    url = _get_pip_url(py)
    print("Downloading {0} ...".format(url))
    fd, tmp_path = tempfile.mkstemp(suffix="-get-pip.py")
    os.close(fd)
    try:
        urllib.request.urlretrieve(url, tmp_path)
    except Exception as exc:
        print("Failed to download get-pip.py: {0}".format(exc))
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False
    rc = run(py + [tmp_path, "--user"])
    try:
        os.remove(tmp_path)
    except OSError:
        pass
    return rc == 0


def _get_pip_url(py):
    """Return the get-pip.py URL compatible with the target Python runtime."""
    minor = _python_minor(py)
    if minor in ("3.9", "3.8", "3.7"):
        return "https://bootstrap.pypa.io/pip/{0}/get-pip.py".format(minor)
    return "https://bootstrap.pypa.io/get-pip.py"


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


def install_node_clis(assume_yes):
    """Install/update the bundled AI CLI tools (Codex / Claude Code / Gemini CLI).

    Mirrors the TUI's tool_installer flow: ensure Node 20+ is present, then
    `npm install -g <pkg>@latest` for each tool, printing before/after versions.
    Failures here are reported but do NOT fail the overall bootstrap.
    """
    print("")
    print("== Installing AI CLI tools (Codex / Claude Code / Gemini) ==")
    if not _ensure_node(assume_yes):
        print("Skipping AI CLI installation (Node.js {0}+ unavailable).".format(NODE_REQUIRED_MAJOR))
        print("Re-run later from the cc-switch TUI to install them.")
        return

    npm = shutil.which("npm")
    if not npm:
        print("npm not found after Node install; skipping.")
        return

    print("Using node {0}, npm {1}".format(_node_version() or "?", _npm_version(npm) or "?"))
    failures = 0
    for label, command, pkg in NPM_PACKAGES:
        before = _tool_version(command) or "(not installed)"
        rc = run([npm, "install", "-g", "{0}@latest".format(pkg)])
        after = _tool_version(command) or "(unknown)"
        if rc == 0:
            print("  {0}: {1}  ->  {2}".format(label, before, after))
        else:
            failures += 1
            print("  {0}: install failed (exit {1})".format(label, rc))
    if failures:
        print("{0} CLI tool(s) failed to install. You can retry from the cc-switch TUI.".format(failures))


def _ensure_node(assume_yes):
    if _node_ok():
        return True
    return _install_node(assume_yes) and _node_ok()


def _node_ok():
    if not shutil.which("npm") or not shutil.which("node"):
        return False
    return _node_major() >= NODE_REQUIRED_MAJOR


def _node_version():
    node = shutil.which("node")
    if not node:
        return ""
    try:
        proc = subprocess.Popen([node, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = proc.communicate()
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return out.decode("utf-8", "replace").strip()


def _npm_version(npm):
    try:
        proc = subprocess.Popen([npm, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = proc.communicate()
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return out.decode("utf-8", "replace").strip()


def _node_major():
    text = _node_version()
    if not text:
        return 0
    match = re.search(r"(\d+)", text)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def _install_node(assume_yes):
    commands = _node_install_commands()
    if not commands:
        print("Automatic Node.js installation is not supported on this system.")
        print("Install Node.js {0}+ manually, then re-run.".format(NODE_REQUIRED_MAJOR))
        return False

    found = _node_version() or "not installed"
    print("Node.js {0}+ is required for the AI CLI tools (current: {1}).".format(NODE_REQUIRED_MAJOR, found))
    print("Will run:")
    for command in commands:
        print("  {0}".format(format_cmd(command)))
    if not confirm("Install Node.js now?", assume_yes):
        return False

    for command in commands:
        if run(command) != 0:
            return False
    if _node_major() < NODE_REQUIRED_MAJOR:
        installed = _node_version() or "unknown"
        print(
            "Installed Node.js {0} is older than required {1}+.".format(installed, NODE_REQUIRED_MAJOR)
        )
        print("Consider installing from NodeSource: https://github.com/nodesource/distributions")
        return False
    return True


def _node_install_commands():
    system = platform.system()
    if system == "Darwin" and shutil.which("brew"):
        return [["brew", "install", "node"]]
    if system == "Windows" and shutil.which("winget"):
        return [["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS"]]
    if system == "Linux":
        if shutil.which("apt-get"):
            return _apt_node_install_commands()
        if shutil.which("dnf"):
            return [with_sudo(["dnf", "install", "-y", "nodejs", "npm"])]
        if shutil.which("yum"):
            return [with_sudo(["yum", "install", "-y", "nodejs", "npm"])]
        if shutil.which("pacman"):
            return [with_sudo(["pacman", "-Sy", "--noconfirm", "nodejs", "npm"])]
        if shutil.which("zypper"):
            return [with_sudo(["zypper", "--non-interactive", "install", "nodejs", "npm"])]
        if shutil.which("apk"):
            return [with_sudo(["apk", "add", "nodejs", "npm"])]
    return []


def _apt_node_install_commands():
    """Install Node.js 20+ on apt systems instead of distro-old nodejs packages."""
    setup_script = (
        "set -e; "
        "mkdir -p /etc/apt/keyrings; "
        "curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key "
        "| gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg; "
        "chmod 644 /etc/apt/keyrings/nodesource.gpg; "
        "echo 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] "
        "https://deb.nodesource.com/node_{0}.x nodistro main' "
        "> /etc/apt/sources.list.d/nodesource.list"
    ).format(NODE_REQUIRED_MAJOR)
    return [
        with_sudo(["apt-get", "update"]),
        with_sudo(["apt-get", "install", "-y", "ca-certificates", "curl", "gnupg"]),
        with_sudo(["bash", "-c", setup_script]),
        with_sudo(["apt-get", "update"]),
        with_sudo(["apt-get", "install", "-y", "nodejs"]),
    ]


def _tool_version(command):
    exe = shutil.which(command)
    if not exe:
        return ""
    try:
        proc = subprocess.Popen([exe, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out, _ = proc.communicate()
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    text = out.decode("utf-8", "replace").strip()
    return " ".join(text.split())


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
