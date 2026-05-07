"""Minimal WebDAV client built on :mod:`urllib`.

WebDAV is just HTTP with a handful of extra methods, so we don't pull in
``webdavclient3`` or ``requests``. We only need:

* ``PUT``     — upload a file
* ``GET``     — download a file
* ``MKCOL``   — create a collection (directory)
* ``PROPFIND``— probe a path (used by ``sync test``)
* ``DELETE``  — used by ``sync forget --remote`` (kept for future use)

Auth is HTTP Basic. Errors are normalised into :class:`WebDAVError` so the
caller can show a coherent message regardless of which urllib exception
fired.
"""

from __future__ import annotations

import base64
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Mapping

from ..i18n import t


_DEFAULT_TIMEOUT = 15.0
_BODY_SNIPPET_LIMIT = 400


class WebDAVError(RuntimeError):
    """Raised when a WebDAV request fails (network error or non-2xx status)."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        url: str | None = None,
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.url = url
        self.body = body

    def __str__(self) -> str:  # pragma: no cover - trivial
        base = super().__str__()
        if self.status is not None:
            base = f"{base} (HTTP {self.status})"
        if self.body:
            base = f"{base}\n  body: {self.body[:200]}"
        return base


@dataclass(frozen=True)
class WebDAVResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class WebDAVClient:
    """Tiny WebDAV client. One instance per WebDAV endpoint."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        verify_tls: bool = True,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        # Always end the base in '/' so urljoin behaves; we also tolerate
        # users who paste the full URL of a directory.
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.username = username
        self.password = password
        self.timeout = timeout
        self.verify_tls = verify_tls

    # ------------------------------------------------------------------ helpers

    def _absolute(self, remote_path: str) -> str:
        # Strip leading slash so urljoin treats remote_path as relative.
        rel = remote_path.lstrip("/")
        # Quote each path segment but keep '/' so directories survive.
        quoted = urllib.parse.quote(rel, safe="/:@")
        return urllib.parse.urljoin(self.base_url, quoted)

    def _headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
        headers = {
            "Authorization": f"Basic {token}",
            "User-Agent": "cc-switch-tool/0.1 webdav",
        }
        if extra:
            headers.update(extra)
        return headers

    def _ssl_context(self) -> ssl.SSLContext | None:
        if self.verify_tls:
            return None  # default context = verify
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _request(
        self,
        method: str,
        remote_path: str,
        *,
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        accept_statuses: tuple[int, ...] = (),
    ) -> WebDAVResponse:
        url = self._absolute(remote_path)
        request = urllib.request.Request(url, data=data, method=method, headers=self._headers(headers))
        try:
            with urllib.request.urlopen(  # noqa: S310 — explicit URL chosen by user
                request,
                timeout=self.timeout,
                context=self._ssl_context(),
            ) as response:
                body = response.read()
                resp_headers = {k: v for k, v in response.headers.items()}
                return WebDAVResponse(
                    status=response.status,
                    headers=resp_headers,
                    body=body,
                    url=url,
                )
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read() or b""
            except Exception:
                body = b""
            if exc.code in accept_statuses:
                return WebDAVResponse(
                    status=exc.code,
                    headers={k: v for k, v in (exc.headers or {}).items()},
                    body=body,
                    url=url,
                )
            raise WebDAVError(
                _http_message(exc.code, exc.reason),
                status=exc.code,
                url=url,
                body=_decode_snippet(body),
            ) from exc
        except urllib.error.URLError as exc:
            raise WebDAVError(
                f"network error: {exc.reason}",
                url=url,
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise WebDAVError(
                f"timeout after {self.timeout:g}s",
                url=url,
            ) from exc

    # -------------------------------------------------------------------- verbs

    def put(self, remote_path: str, data: bytes, *, content_type: str = "application/octet-stream") -> WebDAVResponse:
        return self._request(
            "PUT",
            remote_path,
            data=data,
            headers={"Content-Type": content_type, "Content-Length": str(len(data))},
        )

    def get(self, remote_path: str) -> WebDAVResponse:
        return self._request("GET", remote_path)

    def mkcol(self, remote_path: str, *, exist_ok: bool = True) -> WebDAVResponse:
        # 201 = created, 405 = already a collection, 409 = parent missing.
        accept = (405,) if exist_ok else ()
        if not remote_path.endswith("/"):
            remote_path = remote_path + "/"
        return self._request("MKCOL", remote_path, accept_statuses=accept)

    def propfind(self, remote_path: str, *, depth: str = "0") -> WebDAVResponse:
        body = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<d:propfind xmlns:d="DAV:"><d:prop>'
            b'<d:resourcetype/><d:getcontentlength/><d:getlastmodified/><d:getetag/>'
            b'</d:prop></d:propfind>'
        )
        return self._request(
            "PROPFIND",
            remote_path,
            data=body,
            headers={"Depth": depth, "Content-Type": "application/xml"},
            accept_statuses=(207,),
        )

    def delete(self, remote_path: str, *, missing_ok: bool = False) -> WebDAVResponse:
        accept = (404,) if missing_ok else ()
        return self._request("DELETE", remote_path, accept_statuses=accept)

    # ---------------------------------------------------------------- composite

    def ensure_directory(self, remote_path: str) -> None:
        """Create every missing collection along ``remote_path``.

        ``remote_path`` should be a directory path (we add a trailing slash
        if missing). We try ``MKCOL`` from the deepest level and walk up if
        the parent is missing — most servers return 409 in that case.
        """
        if not remote_path.endswith("/"):
            remote_path = remote_path + "/"
        parts = [p for p in remote_path.strip("/").split("/") if p]
        if not parts:
            return
        accumulated = ""
        for segment in parts:
            accumulated += "/" + segment
            try:
                self.mkcol(accumulated + "/", exist_ok=True)
            except WebDAVError as exc:
                # 409 typically means a parent path conflict; keep walking
                # because the next iteration will deepen, and the retry of
                # earlier levels with exist_ok handles re-runs idempotently.
                if exc.status == 409:
                    continue
                raise


def _http_message(status: int, reason: str | None) -> str:
    if status == 401:
        return t("401 Unauthorized — check WebDAV username/password")
    if status == 403:
        return t("403 Forbidden — the account is authenticated but cannot access this path")
    if status == 404:
        return t("404 Not Found — the remote file or directory doesn't exist")
    if status == 405:
        return t("405 Method Not Allowed — endpoint may not be a WebDAV server")
    if status == 507:
        return t("507 Insufficient Storage — the WebDAV server reported it is full")
    return f"HTTP {status} {reason or ''}".strip()


def _decode_snippet(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = repr(raw)
    return text.strip().replace("\n", " ")[:_BODY_SNIPPET_LIMIT]
