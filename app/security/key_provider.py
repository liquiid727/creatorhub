"""Key-provider ports and the local self-hosted master-key provider."""
from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Protocol


class KeyProvider(Protocol):
    @property
    def key_id(self) -> str: ...

    def master_key(self) -> bytes: ...


class LocalFileKeyProvider:
    """Load a 256-bit master key from a file outside the database.

    The file is created with owner-only permissions. The provider stores a
    base64 value so operators can back it up without accidentally treating it
    as application data. KMS/keychain providers can implement the same port.
    """

    def __init__(self, path: str | None = None, key_id: str = "local-file-v1"):
        self.path = Path(path or os.environ.get(
            "CREATORHUB_MASTER_KEY_PATH", "./data/keys/master.key"
        )).expanduser()
        self._key_id = key_id
        self._cached: bytes | None = None

    @property
    def key_id(self) -> str:
        return self._key_id

    def master_key(self) -> bytes:
        if self._cached is not None:
            return self._cached
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path, 0o600)
        except FileNotFoundError:
            pass
        if self.path.exists():
            raw = base64.urlsafe_b64decode(self.path.read_bytes().strip())
            if len(raw) != 32:
                raise RuntimeError("CREATORHUB master key must be 256 bits")
            self._cached = raw
            return raw
        raw = secrets.token_bytes(32)
        encoded = base64.urlsafe_b64encode(raw) + b"\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, encoded)
        finally:
            os.close(fd)
        self._cached = raw
        return raw
