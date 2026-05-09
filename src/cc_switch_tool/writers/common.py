from __future__ import annotations

import json
import os
import re
import shlex
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable


JsonObject = dict[str, Any]
ACTIVE_ENV_PATH = Path("~/.cc-switch-tool/active.env")
SHELL_LOADER_START = "# >>> cc-switch-tool env >>>"
SHELL_LOADER_END = "# <<< cc-switch-tool env <<<"


def expand(path: str | Path) -> Path:
    return Path(path).expanduser()


def read_json(path: str | Path, default: JsonObject | None = None) -> JsonObject:
    resolved = expand(path)
    if not resolved.exists():
        return {} if default is None else default.copy()
    with resolved.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{resolved} must contain a JSON object")
    return data


def atomic_write_text(path: str | Path, content: str, mode: int | None = None) -> None:
    resolved = expand(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_name(f".{resolved.name}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp, resolved)
    if mode is not None:
        os.chmod(resolved, mode)


def write_json(path: str | Path, data: JsonObject, mode: int | None = None) -> None:
    atomic_write_text(
        path,
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        mode=mode,
    )


def set_nested(data: JsonObject, keys: Iterable[str], value: Any) -> None:
    cursor = data
    key_list = list(keys)
    for key in key_list[:-1]:
        next_value = cursor.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            cursor[key] = next_value
        cursor = next_value
    cursor[key_list[-1]] = value


def redact(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def shell_export(key: str, value: str) -> str:
    return f"export {key}={shlex.quote(value)}"


def update_env_file(path: str | Path, values: dict[str, str], mode: int | None = None) -> None:
    resolved = expand(path)
    lines: list[str] = []
    seen: set[str] = set()

    if resolved.exists():
        lines = resolved.read_text(encoding="utf-8").splitlines()

    updated: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in values:
            updated.append(f"{key}={shlex.quote(values[key])}")
            seen.add(key)
        else:
            updated.append(line)

    for key, value in values.items():
        if key not in seen:
            updated.append(f"{key}={shlex.quote(value)}")

    atomic_write_text(resolved, "\n".join(updated) + "\n", mode=mode)


def update_shell_env_file(
    path: str | Path,
    values: dict[str, str],
    remove_keys: Iterable[str] = (),
    mode: int | None = None,
) -> None:
    """Update a shell-sourceable env file with exported variables."""
    resolved = expand(path)
    lines: list[str] = []
    seen: set[str] = set()
    removals = set(remove_keys)
    assignment = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")

    if resolved.exists():
        lines = resolved.read_text(encoding="utf-8").splitlines()

    updated: list[str] = []
    for line in lines:
        match = assignment.match(line)
        if not match:
            updated.append(line)
            continue
        key = match.group(1)
        if key in values:
            updated.append(f"export {key}={shlex.quote(values[key])}")
            seen.add(key)
        elif key in removals:
            continue
        else:
            updated.append(line)

    for key, value in values.items():
        if key not in seen:
            updated.append(f"export {key}={shlex.quote(value)}")

    content = "\n".join(updated).rstrip()
    atomic_write_text(resolved, (content + "\n") if content else "", mode=mode)


def update_active_env(values: dict[str, str], *, remove_keys: Iterable[str] = ()) -> str:
    update_shell_env_file(ACTIVE_ENV_PATH, values, remove_keys=remove_keys, mode=0o600)
    return str(ACTIVE_ENV_PATH.expanduser())


def ensure_shell_env_loader() -> list[str]:
    """Install a small shell startup hook for the active cc-switch env file."""
    changed: list[str] = []
    targets = [Path("~/.bashrc")]
    zshrc = Path("~/.zshrc").expanduser()
    if zshrc.exists():
        targets.append(Path("~/.zshrc"))

    block = (
        f"\n{SHELL_LOADER_START}\n"
        "# Load active cc-switch-tool API key environment variables.\n"
        'if [ -f "$HOME/.cc-switch-tool/active.env" ]; then\n'
        '    . "$HOME/.cc-switch-tool/active.env"\n'
        "fi\n"
        f"{SHELL_LOADER_END}\n"
    )

    for target in targets:
        resolved = target.expanduser()
        content = resolved.read_text(encoding="utf-8") if resolved.exists() else ""
        if SHELL_LOADER_START in content:
            continue
        atomic_write_text(resolved, content.rstrip() + block, mode=None)
        changed.append(str(resolved))
    return changed


def http_get(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """GET ``url`` and return ``{ok, status, message, url, body}``.

    Treats any 2xx response as ok. ``body`` is the first ~512 chars of the
    response, which is enough to surface error messages from relay providers
    while keeping the result printable.
    """
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    body_snippet = ""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read(512)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(512)
        except Exception:
            raw = b""
        body_snippet = _decode_snippet(raw)
        return {
            "ok": False,
            "status": exc.code,
            "url": url,
            "body": body_snippet,
            "message": f"HTTP {exc.code} {exc.reason}",
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "body": "",
            "message": f"network error: {exc.reason}",
        }
    except (socket.timeout, TimeoutError):
        return {
            "ok": False,
            "status": None,
            "url": url,
            "body": "",
            "message": f"timeout after {timeout:g}s",
        }
    except Exception as exc:  # pragma: no cover - defensive catch-all
        return {
            "ok": False,
            "status": None,
            "url": url,
            "body": "",
            "message": f"error: {exc}",
        }

    body_snippet = _decode_snippet(raw)
    return {
        "ok": 200 <= status < 300,
        "status": status,
        "url": url,
        "body": body_snippet,
        "message": f"HTTP {status}",
    }


def _decode_snippet(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = repr(raw)
    return text.strip().replace("\n", " ")[:200]
