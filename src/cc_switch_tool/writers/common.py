from __future__ import annotations

import json
import os
import shlex
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable


JsonObject = dict[str, Any]


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
