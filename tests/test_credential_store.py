"""RP-005 encrypted storage contract tests (offline)."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from app.db import init_db
from app.security import CredentialStore, LocalFileKeyProvider


def main() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        init_db(str(root / "test.db"))
        store = CredentialStore(LocalFileKeyProvider(str(root / "master.key")))
        created = store.create(
            platform="wechat_mp", account_id=1, kind="official_api",
            secret={"app_id": "wx-test", "app_secret": "never-in-api"},
        )
        assert created["status"] == "active"
        assert store.resolve(created["ref_id"])["app_secret"] == "never-in-api"
        rotated = store.rotate(created["ref_id"], {"app_id": "wx-test", "app_secret": "next"})
        assert rotated["active_version"] == 2
        assert store.resolve(created["ref_id"])["app_secret"] == "next"
        store.revoke(created["ref_id"])
        try:
            store.resolve(created["ref_id"])
        except ValueError as exc:
            assert str(exc) == "CREDENTIAL_REVOKED"
        else:
            raise AssertionError("revoked credential resolved")
        assert b"never-in-api" not in (root / "master.key").read_bytes()
    print("credential_store: ok")


if __name__ == "__main__":
    main()
