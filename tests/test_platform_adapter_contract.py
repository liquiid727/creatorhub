"""Contract checks for the platform adapter boundary.

Run directly with:
    python3 tests/test_platform_adapter_contract.py
"""
from types import SimpleNamespace

from app.platform_adapter import default_registry, list_capabilities
from app.platform_adapter.normalizers import normalize_aweme, normalize_comment


def test_builtin_capability_matrix_is_explicit():
    records = {r.platform.value: r for r in list_capabilities()}
    assert {"douyin", "xhs", "kuaishou", "shipinhao"}.issubset(records)
    assert records["xhs"].capabilities.keyword_search is True
    assert records["shipinhao"].capabilities.public_content_monitor is False
    assert records["douyin"].capabilities.publish is True
    assert records["kuaishou"].capabilities.supports_browser_runtime is True


def test_registry_rejects_unsupported_capability():
    try:
        default_registry.require_capability("shipinhao", "public_content_monitor")
    except ValueError as exc:
        assert "shipinhao" in str(exc)
        assert "public_content_monitor" in str(exc)
    else:
        raise AssertionError("shipinhao should not support public_content_monitor")


def test_aweme_normalizer_uses_platform_neutral_names():
    aweme = SimpleNamespace(
        aweme_id="123",
        desc="hello",
        create_time=1710000000,
        author_name="creator",
        media_type="video",
        medias=[SimpleNamespace(url="https://example.com/a.mp4", kind="video", ext="mp4", index=0)],
        like_count=7,
        comment_count=2,
        platform="douyin",
        quality_label="",
        cover="",
        duration=0,
    )
    item = normalize_aweme(aweme)
    data = item.to_dict()
    assert data["platform_content_id"] == "123"
    assert "aweme_id" not in data
    assert data["metrics"]["likes"] == 7
    assert data["media_assets"][0]["kind"] == "video"


def test_comment_normalizer_uses_platform_comment_id():
    data = normalize_comment(
        {"comment_id": "c1", "text": "nice", "user_nickname": "u", "like_count": 1},
        "douyin",
        "123",
    )
    assert data["platform_comment_id"] == "c1"
    assert data["platform_content_id"] == "123"
    assert "comment_id" not in data


def _run_all():
    test_builtin_capability_matrix_is_explicit()
    test_registry_rejects_unsupported_capability()
    test_aweme_normalizer_uses_platform_neutral_names()
    test_comment_normalizer_uses_platform_comment_id()
    print("platform_adapter_contract: ok")


if __name__ == "__main__":
    _run_all()
