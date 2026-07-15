"""Contract checks for the Xiaohongshu platform adapter.

Run directly with:
    python3 tests/test_xiaohongshu_adapter.py
"""
from app.platform_adapter import PlatformId, default_registry
from app.platform_adapter.adapters import XiaohongshuAdapter


def test_xhs_adapter_is_registered_as_concrete_adapter():
    adapter = default_registry.get("xhs")
    assert isinstance(adapter, XiaohongshuAdapter)
    assert adapter.platform == PlatformId.XHS
    assert adapter.capabilities.keyword_search is True
    assert adapter.capabilities.publish is True


def test_xhs_keyword_resolves_without_network():
    import asyncio

    adapter = XiaohongshuAdapter()
    ref = asyncio.run(adapter.resolve_target("AI 写作", target_kind="keyword"))
    assert ref.platform == PlatformId.XHS
    assert ref.target_kind == "keyword"
    assert ref.platform_target_id == "AI 写作"
    assert ref.display_name == "#AI 写作"
    assert ref.to_dict()["platform_extra"] == {}


def test_xhs_to_legacy_aweme_bridge_keeps_downloader_shape():
    adapter = XiaohongshuAdapter()
    note_card = {
        "note_id": "64f000000000000000000001",
        "title": "标题",
        "desc": "正文",
        "time": 1710000000000,
        "type": "normal",
        "user": {"nickname": "作者"},
        "interact_info": {"liked_count": "1.2万", "comment_count": "34"},
        "image_list": [
            {"info_list": [{"image_scene": "WB_DFT", "url": "https://img.example/a.jpg"}]}
        ],
    }
    item = adapter.normalize_note_card(note_card, {"note_id": "64f000000000000000000001", "xsec_token": "tok"})
    data = item.to_dict()
    assert data["platform"] == "xhs"
    assert data["platform_content_id"] == "64f000000000000000000001"
    assert data["content_type"] == "image_set"
    assert data["metrics"]["likes"] == 12000
    assert data["metrics"]["comments"] == 34
    assert data["media_assets"][0]["kind"] == "image"
    assert data["platform_extra"]["xsec_token"] == "tok"
    legacy = adapter.to_legacy_aweme(item)
    assert legacy.aweme_id == "64f000000000000000000001"
    assert legacy.media_type == "images"
    assert legacy.medias[0].url == "https://img.example/a.jpg"


def test_xhs_normalizes_comment_tree():
    adapter = XiaohongshuAdapter()
    comments = [
        {
            "id": "c1",
            "content": "一级",
            "user_info": {"nickname": "甲"},
            "like_count": "2",
            "create_time": 1710000000000,
            "sub_comments": [
                {
                    "id": "c2",
                    "content": "二级",
                    "user_info": {"nickname": "乙"},
                    "target_comment": {"id": "c1"},
                }
            ],
        }
    ]
    data = adapter.normalize_comments(comments, "n1")
    assert [c["platform_comment_id"] for c in data] == ["c1", "c2"]
    assert data[1]["parent_comment_id"] == "c1"
    assert data[0]["platform_content_id"] == "n1"


def _run_all():
    test_xhs_adapter_is_registered_as_concrete_adapter()
    test_xhs_keyword_resolves_without_network()
    test_xhs_to_legacy_aweme_bridge_keeps_downloader_shape()
    test_xhs_normalizes_comment_tree()
    print("xiaohongshu_adapter: ok")


if __name__ == "__main__":
    _run_all()
