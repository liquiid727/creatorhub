"""Encrypted credential storage and append-only audit support."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..db import get_session
from ..models import (
    AuditEventRecord,
    CredentialRefRecord,
    CredentialVersionRecord,
)
from .key_provider import KeyProvider, LocalFileKeyProvider
from .redaction import redact_mapping, redact_text


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


class AuditLogger:
    """Append-only audit chain. Metadata is redacted before persistence."""

    def append(self, *, action: str, resource_type: str, resource_id: str,
               result: str, actor_id: str = "system", account_id: int | None = None,
               platform: str = "", error_code: str = "", approval_ref: str = "",
               idempotency_key: str = "", metadata: dict[str, Any] | None = None) -> str:
        event_id = str(uuid.uuid4())
        safe = redact_mapping(metadata or {})
        with get_session() as session:
            previous = session.query(AuditEventRecord).order_by(
                AuditEventRecord.id.desc()).first()
            previous_hash = previous.event_hash if previous else ""
            body = {
                "event_id": event_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "result": result,
                "actor_id": actor_id,
                "account_id": account_id,
                "platform": platform,
                "error_code": error_code,
                "approval_ref": approval_ref,
                "idempotency_key": idempotency_key,
                "metadata": safe,
                "previous_event_hash": previous_hash,
            }
            event_hash = hashlib.sha256(
                json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            event = AuditEventRecord(
                event_id=event_id, occurred_at=_now(), action=action,
                resource_type=resource_type, resource_id=resource_id,
                result=result, actor_id=actor_id, account_id=account_id,
                platform=platform, error_code=error_code,
                approval_ref=approval_ref, idempotency_key=idempotency_key,
                metadata_json=json.dumps(safe, ensure_ascii=False),
                previous_event_hash=previous_hash, event_hash=event_hash,
            )
            session.add(event)
            session.commit()
        return event_id


class CredentialStore:
    """Store only encrypted credential versions; never exposes a reveal API."""

    def __init__(self, provider: KeyProvider | None = None,
                 audit: AuditLogger | None = None):
        self.provider = provider or LocalFileKeyProvider()
        self.audit = audit or AuditLogger()

    def _encrypt(self, value: dict[str, Any]) -> tuple[str, str, str]:
        data_key = secrets.token_bytes(32)
        data_nonce = secrets.token_bytes(12)
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        ciphertext = AESGCM(data_key).encrypt(data_nonce, payload, None)
        wrap_nonce = secrets.token_bytes(12)
        wrapped_key = AESGCM(self.provider.master_key()).encrypt(wrap_nonce, data_key, None)
        return _b64(wrapped_key), _b64(data_nonce), _b64(ciphertext + wrap_nonce)

    def _decrypt(self, version: CredentialVersionRecord) -> dict[str, Any]:
        packed = _unb64(version.ciphertext)
        wrap_nonce, ciphertext = packed[-12:], packed[:-12]
        data_key = AESGCM(self.provider.master_key()).decrypt(
            wrap_nonce, _unb64(version.encrypted_data_key), None)
        payload = AESGCM(data_key).decrypt(
            _unb64(version.nonce), ciphertext, None)
        return json.loads(payload.decode("utf-8"))

    def create(self, *, platform: str, account_id: int | None, kind: str,
               secret: dict[str, Any], expires_at: datetime | None = None,
               actor_id: str = "system") -> dict[str, Any]:
        if not isinstance(secret, dict) or not secret:
            raise ValueError("SECRET_MATERIAL_REJECTED")
        secret_json = json.dumps(secret, sort_keys=True, ensure_ascii=False)
        ref_id = str(uuid.uuid4())
        wrapped_key, nonce, ciphertext = self._encrypt(secret)
        fingerprint = hashlib.sha256(secret_json.encode()).hexdigest()[:16]
        with get_session() as session:
            ref = CredentialRefRecord(
                ref_id=ref_id, platform=platform, account_id=account_id,
                kind=kind, status="active", active_version=1,
                fingerprint=fingerprint, expires_at=expires_at,
            )
            version = CredentialVersionRecord(
                ref_id=ref_id, version=1, encrypted_data_key=wrapped_key,
                ciphertext=ciphertext, nonce=nonce,
                key_provider=self.provider.key_id, key_id=self.provider.key_id,
                algorithm="AES-256-GCM",
            )
            session.add(ref); session.add(version); session.commit()
        self.audit.append(action="credential.created", resource_type="credential_ref",
                          resource_id=ref_id, result="success", actor_id=actor_id,
                          account_id=account_id, platform=platform,
                          metadata={"kind": kind, "fingerprint": fingerprint})
        return self.metadata(ref)

    def resolve(self, ref_id: str, *, expected_kind: str | None = None) -> dict[str, Any]:
        with get_session() as session:
            ref = session.query(CredentialRefRecord).filter(
                CredentialRefRecord.ref_id == ref_id).first()
            if not ref:
                raise ValueError("CREDENTIAL_NOT_FOUND")
            if ref.status != "active":
                raise ValueError(f"CREDENTIAL_{ref.status.upper()}")
            if expected_kind and ref.kind != expected_kind:
                raise ValueError("CREDENTIAL_KIND_MISMATCH")
            version = session.query(CredentialVersionRecord).filter(
                CredentialVersionRecord.ref_id == ref_id,
                CredentialVersionRecord.version == ref.active_version).first()
            if not version:
                raise ValueError("CREDENTIAL_DECRYPT_FAILED")
            try:
                return self._decrypt(version)
            except Exception as exc:
                raise ValueError("CREDENTIAL_DECRYPT_FAILED") from exc

    def rotate(self, ref_id: str, secret: dict[str, Any], *, actor_id: str = "system") -> dict[str, Any]:
        if not secret:
            raise ValueError("SECRET_MATERIAL_REJECTED")
        wrapped_key, nonce, ciphertext = self._encrypt(secret)
        with get_session() as session:
            ref = session.query(CredentialRefRecord).filter(
                CredentialRefRecord.ref_id == ref_id).first()
            if not ref:
                raise ValueError("CREDENTIAL_NOT_FOUND")
            if ref.status == "revoked":
                raise ValueError("CREDENTIAL_REVOKED")
            next_version = ref.active_version + 1
            session.add(CredentialVersionRecord(
                ref_id=ref_id, version=next_version,
                encrypted_data_key=wrapped_key, ciphertext=ciphertext,
                nonce=nonce, key_provider=self.provider.key_id,
                key_id=self.provider.key_id,
                algorithm="AES-256-GCM", rotated_from_version=ref.active_version,
            ))
            ref.status = "active"; ref.active_version = next_version
            ref.fingerprint = hashlib.sha256(
                json.dumps(secret, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()[:16]
            session.add(ref); session.commit()
            result = self.metadata(ref)
        self.audit.append(action="credential.rotated", resource_type="credential_ref",
                          resource_id=ref_id, result="success", actor_id=actor_id,
                          account_id=ref.account_id, platform=ref.platform,
                          metadata={"version": next_version})
        return result

    def revoke(self, ref_id: str, *, actor_id: str = "system") -> dict[str, Any]:
        with get_session() as session:
            ref = session.query(CredentialRefRecord).filter(
                CredentialRefRecord.ref_id == ref_id).first()
            if not ref:
                raise ValueError("CREDENTIAL_NOT_FOUND")
            ref.status = "revoked"; ref.revoked_at = _now()
            session.add(ref); session.commit(); result = self.metadata(ref)
        self.audit.append(action="credential.revoked", resource_type="credential_ref",
                          resource_id=ref_id, result="success", actor_id=actor_id,
                          account_id=ref.account_id, platform=ref.platform)
        return result

    @staticmethod
    def metadata(ref: CredentialRefRecord) -> dict[str, Any]:
        return {
            "ref_id": ref.ref_id, "platform": ref.platform,
            "account_id": ref.account_id, "kind": ref.kind,
            "status": ref.status, "active_version": ref.active_version,
            "fingerprint": ref.fingerprint, "expires_at": ref.expires_at.isoformat() if ref.expires_at else None,
            "last_checked_at": ref.last_checked_at.isoformat() if ref.last_checked_at else None,
        }
