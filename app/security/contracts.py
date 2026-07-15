"""Credential metadata and audit contracts.

These types intentionally contain no decryptable secret material. Encryption,
key providers, persistence, and rotation are delivered by the next RP-005 slice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .redaction import redact_mapping


class CredentialKind(str, Enum):
    OFFICIAL_API = "official_api"
    BROWSER_STATE = "browser_state"
    CREATOR_STATE = "creator_state"
    PROXY = "proxy"
    LOCAL_RUNTIME = "local_runtime"


class CredentialStatus(str, Enum):
    ACTIVE = "active"
    ROTATING = "rotating"
    REVOKED = "revoked"
    INVALID = "invalid"


@dataclass(frozen=True)
class CredentialRef:
    credential_ref_id: str
    platform: str
    account_id: str
    kind: CredentialKind
    status: CredentialStatus = CredentialStatus.ACTIVE
    active_version: int = 1
    fingerprint: str = ""
    expires_at: str = ""
    last_checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "credential_ref_id": self.credential_ref_id,
            "platform": self.platform,
            "account_id": self.account_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "active_version": self.active_version,
            "fingerprint": self.fingerprint,
            "expires_at": self.expires_at,
            "last_checked_at": self.last_checked_at,
        }


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    action: str
    resource_type: str
    resource_id: str
    result: str
    actor_id: str = ""
    account_id: str = ""
    platform: str = ""
    request_id: str = ""
    error_code: str = ""
    approval_ref: str = ""
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "result": self.result,
            "actor_id": self.actor_id,
            "account_id": self.account_id,
            "platform": self.platform,
            "request_id": self.request_id,
            "error_code": self.error_code,
            "approval_ref": self.approval_ref,
            "idempotency_key": self.idempotency_key,
            "metadata": redact_mapping(self.metadata),
        }
