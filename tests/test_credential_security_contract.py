"""Contract tests for RP-005 metadata and redaction boundaries."""
from app.security import (
    AuditEvent,
    CredentialKind,
    CredentialRef,
    CredentialStatus,
    redact_mapping,
    redact_text,
)


def test_credential_ref_contains_metadata_only():
    ref = CredentialRef(
        credential_ref_id="cred-1",
        platform="wechat_mp",
        account_id="account-1",
        kind=CredentialKind.OFFICIAL_API,
        status=CredentialStatus.ACTIVE,
        fingerprint="sha256:abc",
    )
    data = ref.to_dict()
    assert data["credential_ref_id"] == "cred-1"
    assert "secret" not in data
    assert "ciphertext" not in data


def test_nested_sensitive_values_are_redacted():
    data = redact_mapping({
        "account_id": "a1",
        "app_secret": "secret-value",
        "nested": {
            "access_token": "token-value",
            "cookie": "sid=123",
            "safe": "visible",
        },
    })
    assert data["app_secret"] == "[REDACTED]"
    assert data["nested"]["access_token"] == "[REDACTED]"
    assert data["nested"]["cookie"] == "[REDACTED]"
    assert data["nested"]["safe"] == "visible"


def test_text_and_audit_metadata_are_redacted():
    text = redact_text("Authorization: Bearer abc access_token=xyz")
    assert "abc" not in text and "xyz" not in text
    basic = redact_text("https://example.test?a=1&authorization=Basic abcdef&lang=zh_CN")
    assert "abcdef" not in basic
    assert basic == "[REDACTED]"
    query_cookie = redact_text("https://example.test?a=1&cookie=sid=123&lang=zh_CN")
    assert "sid=123" not in query_cookie
    assert query_cookie == "[REDACTED]"
    header_cookie = redact_text("Cookie: sid=123; auth=secret")
    assert "sid=123" not in header_cookie and "auth=secret" not in header_cookie
    serialized = redact_text(
        "{'app_secret': 'secret-one', \"access_token\": \"secret-two\", "
        "'client_secret': 'secret-three', 'safe': 'visible'}"
    )
    assert all(secret not in serialized for secret in ("secret-one", "secret-two", "secret-three"))
    assert serialized == "[REDACTED]"
    wechat_token_url = redact_text(
        "https://api.weixin.qq.com/cgi-bin/token?appid=wx123&secret=APPSECRET&lang=zh_CN"
    )
    assert "APPSECRET" not in wechat_token_url
    assert wechat_token_url == "[REDACTED]"
    assert redact_text("password=correct horse battery staple") == "[REDACTED]"
    assert redact_text("cookie=sid=123; session=456") == "[REDACTED]"
    assert redact_text("access_token%3Dsecret-token") == "[REDACTED]"
    assert redact_text("Authorization%3A%20Bearer%20secret-token") == "[REDACTED]"
    assert redact_text("access_token%253Ddouble-encoded-secret") == "[REDACTED]"
    assert redact_text("http://user:password@proxy.local:8080") == "[REDACTED]"
    assert redact_text("request failed for //user:password@proxy.local") == "[REDACTED]"
    assert redact_text("http://token@proxy.local") == "[REDACTED]"
    assert redact_text("http://:password@proxy.local") == "[REDACTED]"
    assert redact_text("https://example.test?email=user@example.org") != "[REDACTED]"
    assert redact_text("https://example.test#contact=user@example.org") != "[REDACTED]"
    assert redact_text('{"accessToken":"abc", "apiKey":"def"}') == "[REDACTED]"
    camel_case = redact_mapping({"accessToken": "abc", "apiKey": "def", "safe": "ok"})
    assert camel_case == {
        "accessToken": "[REDACTED]",
        "apiKey": "[REDACTED]",
        "safe": "ok",
    }
    uppercase = redact_mapping({
        "API_KEY": "abc",
        "ACCESS_TOKEN": "def",
        "CLIENT_SECRET": "ghi",
        "PASSWORD": "jkl",
    })
    assert set(uppercase.values()) == {"[REDACTED]"}
    event = AuditEvent(
        event_id="evt-1",
        action="credential.check",
        resource_type="credential_ref",
        resource_id="cred-1",
        result="failed",
        metadata={"app_secret": "secret-value", "reason": "expired"},
    )
    payload = event.to_dict()
    assert payload["metadata"]["app_secret"] == "[REDACTED]"
    assert payload["metadata"]["reason"] == "expired"


def _run_all():
    test_credential_ref_contains_metadata_only()
    test_nested_sensitive_values_are_redacted()
    test_text_and_audit_metadata_are_redacted()
    print("credential_security_contract: ok")


if __name__ == "__main__":
    _run_all()
