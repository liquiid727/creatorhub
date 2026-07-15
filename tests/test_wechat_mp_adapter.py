"""Offline contract tests for the WeChat Official Account adapter."""
import asyncio

from app.platform_adapter import PlatformId, default_registry
from app.platform_adapter.adapters import WechatMpAdapter, WechatMpMode


def test_wechat_mp_adapter_is_registered_with_restricted_defaults():
    adapter = default_registry.get("wechat_mp")
    assert isinstance(adapter, WechatMpAdapter)
    assert adapter.platform == PlatformId.WECHAT_MP
    assert adapter.capabilities.publish is False
    assert adapter.capabilities_for_mode(WechatMpMode.OFFICIAL).publish is True
    default_registry.require_capability("wechat_mp", "publish", mode="official")
    try:
        default_registry.require_capability("wechat_mp", "publish")
    except ValueError:
        pass
    else:
        raise AssertionError("restricted mode must not expose publish")

    records = {
        record.platform.value: record.to_dict()
        for record in default_registry.capability_records()
    }
    assert records["wechat_mp"]["capability_modes"]["official"]["publish"] is True


def test_account_target_resolution_is_network_free():
    adapter = WechatMpAdapter()
    ref = asyncio.run(adapter.resolve_target("gh_creator_fairy"))
    assert ref.platform == PlatformId.WECHAT_MP
    assert ref.target_kind == "account"
    assert ref.platform_target_id == "gh_creator_fairy"

    try:
        asyncio.run(adapter.resolve_target(
            "https://mp.weixin.qq.com/profile?access_token=secret-token&lang=zh_CN"
        ))
    except ValueError as exc:
        assert "不得包含" in str(exc)
    else:
        raise AssertionError("credential-bearing account URLs must be rejected")

    try:
        asyncio.run(adapter.resolve_target(
            "https://api.weixin.qq.com/cgi-bin/token?appid=wx123&secret=APPSECRET"
        ))
    except ValueError:
        pass
    else:
        raise AssertionError("WeChat app-secret URLs must be rejected")

    try:
        asyncio.run(adapter.resolve_target(
            "https://mp.weixin.qq.com/profile?next=access_token%3Dencoded-secret"
        ))
    except ValueError:
        pass
    else:
        raise AssertionError("percent-encoded credential URLs must be rejected")

    try:
        asyncio.run(adapter.resolve_target(
            "https://admin:password@mp.weixin.qq.com/profile"
        ))
    except ValueError:
        pass
    else:
        raise AssertionError("URL userinfo credentials must be rejected")

    for unsafe_url in (
        "HTTPS://admin:password@mp.weixin.qq.com/profile",
        "//admin:password@mp.weixin.qq.com/profile",
    ):
        try:
            asyncio.run(adapter.resolve_target(unsafe_url))
        except ValueError:
            pass
        else:
            raise AssertionError("URL scheme variants with userinfo must be rejected")


def test_article_and_metrics_normalization():
    adapter = WechatMpAdapter()
    item = adapter.normalize_article({
        "media_id": "article-1",
        "title": "Creator OS 周报",
        "digest": "本周内容复盘",
        "thumb_url": "https://img.example/cover.jpg?token=cover-secret&size=large",
        "publish_time": 1710000000000,
        "int_page_read_count": "120",
        "share_count": 8,
        "favorite_count": 4,
        "access_token": "must-not-be-copied",
        "url": "https://mp.example/article?access_token=secret-token&lang=zh_CN",
    })
    data = item.to_dict()
    assert data["platform"] == "wechat_mp"
    assert data["platform_content_id"] == "article-1"
    assert data["content_type"] == "article"
    assert data["metrics"]["views"] == 120
    assert "access_token" not in data["platform_extra"]
    assert "secret-token" not in data["platform_extra"]["source_url"]
    assert data["platform_extra"]["source_url"] == "[REDACTED]"
    assert "cover-secret" not in data["cover_url"]
    assert "cover-secret" not in data["media_assets"][0]["url"]
    assert data["cover_url"] == "[REDACTED]"

    content_only = adapter.normalize_article({
        "article_id": "article-2",
        "content": "正文 https://mp.example/debug?access_token=content-secret&lang=zh_CN",
    }).to_dict()
    assert "content-secret" not in content_only["description"]
    assert content_only["description"] == "[REDACTED]"

    metrics = adapter.normalize_account_metrics(
        {"read_count": "1e309", "new_user": str(10**100)}, "2026-07-16")
    assert metrics["read_count"] == 0
    assert metrics["new_user"] == 0

    metrics = adapter.normalize_account_metrics(
        {"new_user": "12", "cancel_user": 2, "read_count": 300}, "2026-07-15")
    assert metrics == {
        "platform": "wechat_mp",
        "metric_date": "2026-07-15",
        "read_count": 300,
        "share_count": 0,
        "favorite_count": 0,
        "new_user": 12,
        "cancel_user": 2,
    }


def test_multi_article_push_preserves_per_article_identity():
    adapter = WechatMpAdapter()
    items = adapter.normalize_articles([
        {"msgid": "push-1", "idx": 1, "title": "头条"},
        {"msgid": "push-1", "idx": 2, "title": "次条"},
    ])
    assert [item.platform_content_id for item in items] == ["push-1:1", "push-1:2"]


def _run_all():
    test_wechat_mp_adapter_is_registered_with_restricted_defaults()
    test_account_target_resolution_is_network_free()
    test_article_and_metrics_normalization()
    test_multi_article_push_preserves_per_article_identity()
    print("wechat_mp_adapter: ok")


if __name__ == "__main__":
    _run_all()
