"""Contract checks for adapter task runtime.

Run directly with:
    python3 tests/test_adapter_task_runtime.py
"""
import asyncio
from types import SimpleNamespace

from app.platform_adapter.runtime import AdapterTaskRuntime


class FakeXhsAdapter:
    def client_from_state(self, state, user_agent, timeout=30.0, proxy=""):
        if not state:
            return None
        return FakeClient()

    def normalize_briefs(self, raw_items):
        return list(raw_items)

    def normalize_note_card(self, card, brief=None):
        if card.get("missing"):
            return None
        return SimpleNamespace(
            platform_content_id=brief["note_id"],
            content_type="image_set",
            description=card.get("desc", ""),
            title="",
            published_at=1,
            platform_extra={"author_name": "作者", "duration": 0},
            media_assets=[SimpleNamespace(url="https://img/a.jpg", kind="image", ext="jpeg", index=0, quality_label="")],
            metrics=SimpleNamespace(likes=3, comments=4),
            cover_url="https://img/a.jpg",
        )

    def to_legacy_aweme(self, item):
        return SimpleNamespace(
            aweme_id=item.platform_content_id,
            desc=item.description,
            create_time=item.published_at,
            author_name="作者",
            media_type="images",
            medias=[SimpleNamespace(url="https://img/a.jpg", kind="image", ext="jpeg", index=0)],
            cover=item.cover_url,
            quality_label="",
            like_count=item.metrics.likes,
            comment_count=item.metrics.comments,
            duration=0,
            platform="xhs",
        )

    def normalize_legacy_comments(self, raw_comments):
        return raw_comments

    async def creator_check(self, *args, **kwargs):
        return True

    async def self_profile(self, *args, **kwargs):
        return {"user_id": "me", "nickname": "作者"}, ""

    def parse_self_user(self, data):
        return {"nickname": data.get("nickname", ""), "sec_uid": data.get("user_id", "")}

    async def publish(self, *args, **kwargs):
        return True, "https://xhs.example/note", ""

    async def post_comment(self, *args, **kwargs):
        return True, "comment-id", ""


class FakeClient:
    async def search_notes(self, keyword):
        return [
            {"note_id": "n1", "xsec_token": "t1", "title": "one"},
            {"note_id": "known", "xsec_token": "tk", "title": "old"},
        ]

    async def notes_by_creator(self, user_id, xsec_token=""):
        return {"notes": [{"note_id": "n2", "xsec_token": "t2", "title": "two"}]}

    async def user_info(self, user_id):
        return {"nickname": "作者"}

    async def note_detail(self, note_id, xsec_token="", xsec_source=""):
        return {"note_id": note_id, "desc": "detail"}

    async def note_detail_raw(self, note_id, xsec_token="", xsec_source=""):
        return {"note_card": {"note_id": note_id}, "xsec_token": "fresh-token"}

    async def note_comments(self, note_id, xsec_token=""):
        return {"comments": [{"comment_id": "c1"}, {"comment_id": "known"}]}


class FakeRegistry:
    def __init__(self):
        self.adapter = FakeXhsAdapter()

    def get(self, platform):
        assert platform == "xhs"
        return self.adapter


def test_scan_xhs_contents_filters_known_and_normalizes():
    runtime = AdapterTaskRuntime(FakeRegistry(), user_agent="ua")
    batch = asyncio.run(runtime.scan_xhs_contents(
        state="state", proxy="", kind="keyword", keyword="kw", user_id="",
        xsec_token="", known_ids={"known"}, inter_item_delay=0))
    assert batch.error == ""
    assert batch.raw_count == 2
    assert len(batch.items) == 1
    assert batch.items[0].aweme.aweme_id == "n1"
    assert batch.items[0].xsec_token == "t1"


def test_scan_xhs_contents_reports_auth_error():
    runtime = AdapterTaskRuntime(FakeRegistry(), user_agent="ua")
    batch = asyncio.run(runtime.scan_xhs_contents(
        state="", proxy="", kind="keyword", keyword="kw", user_id="",
        xsec_token="", known_ids=set(), inter_item_delay=0))
    assert batch.auth_error is True
    assert "登录态缺少 a1" in batch.error


def test_xhs_fetch_comments_filters_known():
    runtime = AdapterTaskRuntime(FakeRegistry(), user_agent="ua")
    comments = asyncio.run(runtime.xhs_fetch_comments(FakeClient(), "n1", "", {"known"}))
    assert comments == [{"comment_id": "c1"}]


def test_runtime_publish_and_comment_delegate_to_adapter():
    runtime = AdapterTaskRuntime(FakeRegistry(), user_agent="ua")
    ok, url, err = asyncio.run(runtime.publish_xhs(None, None, "state", "images", "t", "d", []))
    assert (ok, url, err) == (True, "https://xhs.example/note", "")
    ok, result, err = asyncio.run(runtime.post_xhs_comment("state", "", "n1", "hi"))
    assert (ok, result, err) == (True, "comment-id", "")


def test_discover_xhs_comment_targets_for_keyword_and_reply():
    runtime = AdapterTaskRuntime(FakeRegistry(), user_agent="ua")
    cands, err = asyncio.run(runtime.discover_xhs_comment_targets(
        state="state", proxy="", mode="auto_comment", kind="keyword", keyword="kw",
        target_user_id="", target_note_id="", target_xsec_token="",
        account_user_id="me", account_nick="我", recent_works=5))
    assert err == ""
    assert cands[0]["aweme_id"] == "n1"
    assert cands[0]["ctx"] == {"kw": "kw"}

    cands, err = asyncio.run(runtime.discover_xhs_comment_targets(
        state="state", proxy="", mode="auto_reply", kind="self", keyword="",
        target_user_id="", target_note_id="", target_xsec_token="",
        account_user_id="me", account_nick="我", recent_works=5))
    assert err == ""
    assert cands[0]["target_comment_id"] == "c1"


def test_refresh_xhs_media_returns_legacy_aweme():
    runtime = AdapterTaskRuntime(FakeRegistry(), user_agent="ua")
    refreshed = asyncio.run(runtime.refresh_xhs_media(
        state="state", proxy="", note_id="n1", xsec_token="tok", kind="creator"))
    assert refreshed.error == ""
    assert refreshed.aweme.aweme_id == "n1"
    assert refreshed.aweme.medias[0].url == "https://img/a.jpg"


def test_runtime_profile_helpers_delegate_to_adapter():
    runtime = AdapterTaskRuntime(FakeRegistry(), user_agent="ua")
    assert asyncio.run(runtime.xhs_creator_check("state")) is True
    profile, err = asyncio.run(runtime.xhs_self_profile("state"))
    assert profile["user_id"] == "me"
    assert err == ""
    assert runtime.parse_xhs_self_user(profile)["sec_uid"] == "me"


def _run_all():
    test_scan_xhs_contents_filters_known_and_normalizes()
    test_scan_xhs_contents_reports_auth_error()
    test_xhs_fetch_comments_filters_known()
    test_runtime_publish_and_comment_delegate_to_adapter()
    test_runtime_profile_helpers_delegate_to_adapter()
    test_discover_xhs_comment_targets_for_keyword_and_reply()
    test_refresh_xhs_media_returns_legacy_aweme()
    print("adapter_task_runtime: ok")


if __name__ == "__main__":
    _run_all()
