"""Encryption helpers for cc-switch-tool sync.

Two modes are supported:

* **Machine-bound** (default for stored WebDAV credentials): key is derived
  from a stable machine identifier (``/etc/machine-id`` or
  ``/var/lib/dbus/machine-id``). When neither is readable, a random 32-byte
  salt is persisted at ``~/.cc-switch-tool/.keyring`` (mode 0600) and used
  instead. Result: encrypted blobs decrypt transparently on the same host
  but cannot be moved to another machine without ``sync setup`` again. That
  matches the user's "stored encrypted locally" requirement.

* **Passphrase-bound** (opt-in for end-to-end encryption of uploaded
  ``profiles.json``): key is derived from a user-supplied passphrase plus
  the same machine salt as a domain separator. The passphrase has to be
  re-entered on the receiving machine.

The actual cipher is :class:`cryptography.fernet.Fernet` (AES-128-CBC +
HMAC-SHA256), which is the standard well-reviewed primitive for "encrypt
some bytes at rest" in the Python ecosystem.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

from ..writers.common import atomic_write_text, expand
from ..i18n import t


if TYPE_CHECKING:  # pragma: no cover - typing only
    from cryptography.fernet import Fernet


KEYRING_PATH = Path("~/.cc-switch-tool/.keyring")
_PBKDF2_ITERATIONS = 200_000
_FERNET_INFO = b"cc-switch-tool/v1"


class CryptoUnavailable(RuntimeError):
    """Raised when the optional ``cryptography`` dependency is missing."""


class DecryptError(RuntimeError):
    """Raised when a ciphertext cannot be decrypted with the current key."""


def _require_cryptography():
    try:
        from cryptography.fernet import Fernet, InvalidToken  # noqa: WPS433
        from cryptography.hazmat.primitives import hashes  # noqa: WPS433
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - import guard
        raise CryptoUnavailable(
            t("The 'cryptography' package is required for cloud sync. "
              "Reinstall with: pipx install --force cc-switch-tool")
        ) from exc
    return Fernet, InvalidToken, hashes, PBKDF2HMAC


def _read_machine_id() -> bytes | None:
    for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            data = Path(candidate).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if data:
            return data.encode("utf-8")
    return None


def _ensure_keyring_salt() -> bytes:
    """Persist (or read back) a 32-byte salt for hosts without machine-id."""
    resolved = expand(KEYRING_PATH)
    if resolved.exists():
        data = resolved.read_bytes()
        if len(data) >= 16:
            return data
    resolved.parent.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_bytes(32)
    # Reuse atomic_write_text by base64-encoding so the file stays text-clean.
    atomic_write_text(resolved, base64.b64encode(salt).decode("ascii") + "\n", mode=0o600)
    return salt


def _machine_secret() -> bytes:
    """Best-effort 32-byte machine-bound secret."""
    machine_id = _read_machine_id()
    if machine_id:
        # Hash so we don't leak the literal machine-id into the KDF input.
        return hashlib.sha256(b"cc-switch-tool/machine-id/" + machine_id).digest()
    raw = _ensure_keyring_salt()
    # File on disk may be base64 (new format) or raw bytes (legacy). Normalise.
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) >= 16:
            return hashlib.sha256(b"cc-switch-tool/keyring/" + decoded).digest()
    except (ValueError, base64.binascii.Error):
        pass
    return hashlib.sha256(b"cc-switch-tool/keyring/" + raw).digest()


def _derive_fernet_key(*, passphrase: str | None) -> bytes:
    """Return a 32-byte url-safe-b64 key suitable for ``Fernet``."""
    _Fernet, _Invalid, _hashes, PBKDF2HMAC = _require_cryptography()
    from cryptography.hazmat.primitives import hashes  # local re-import for type

    salt = _machine_secret()[:16]
    if passphrase is None:
        secret = _machine_secret() + _FERNET_INFO
    else:
        secret = passphrase.encode("utf-8") + b"|" + _FERNET_INFO

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret))


def _fernet(passphrase: str | None = None) -> "Fernet":
    Fernet, _Invalid, _hashes, _kdf = _require_cryptography()
    return Fernet(_derive_fernet_key(passphrase=passphrase))


def encrypt_bytes(plaintext: bytes, passphrase: str | None = None) -> bytes:
    """Encrypt ``plaintext`` and return a Fernet token (also bytes)."""
    return _fernet(passphrase).encrypt(plaintext)


def decrypt_bytes(token: bytes, passphrase: str | None = None) -> bytes:
    """Decrypt a Fernet token; raises :class:`DecryptError` on failure."""
    _Fernet, InvalidToken, _hashes, _kdf = _require_cryptography()
    try:
        return _fernet(passphrase).decrypt(token)
    except InvalidToken as exc:
        if passphrase is None:
            raise DecryptError(
                t("Cannot decrypt with the current machine key. "
                  "If you moved the keyring or changed hosts, run "
                  "'cc-switch sync setup' again.")
            ) from exc
        raise DecryptError(t("Wrong passphrase or corrupted ciphertext.")) from exc


def encrypt_text(plaintext: str, passphrase: str | None = None) -> str:
    return encrypt_bytes(plaintext.encode("utf-8"), passphrase=passphrase).decode("ascii")


def decrypt_text(token: str, passphrase: str | None = None) -> str:
    return decrypt_bytes(token.encode("ascii"), passphrase=passphrase).decode("utf-8")


def looks_like_fernet_token(value: bytes | str) -> bool:
    """Heuristic check used by ``restore`` to decide whether to attempt decryption."""
    if isinstance(value, bytes):
        try:
            head = value.lstrip()[:1]
        except Exception:
            return False
        return head == b"g"  # Fernet tokens always start with the version byte 0x80 → 'g' in url-safe-b64.
    if isinstance(value, str):
        stripped = value.lstrip()
        return stripped.startswith("g") and "{" not in stripped[:4]
    return False


# Re-exported so callers don't import os just for this.
def secure_remove(path: str | os.PathLike[str]) -> None:
    resolved = expand(path)
    try:
        resolved.unlink()
    except FileNotFoundError:
        return
