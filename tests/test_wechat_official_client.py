"""RP-003 official API client tests using an injected HTTP transport."""
from __future__ import annotations

import asyncio

import httpx

from app.platform_adapter.wechat_official import WechatOfficialClient


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/cgi-bin/token":
        return httpx.Response(200, json={"access_token": "token-1", "expires_in": 7200})
    if path == "/cgi-bin/material/batchget_material":
        return httpx.Response(200, json={"item": [{
            "media_id": "media-1",
            "content": {"news_item": [{"title": "标题", "digest": "摘要", "url": "https://example.test/a"}]},
        }]})
    if path == "/datacube/getarticlesummary":
        return httpx.Response(200, json={"list": [{"ref_date": "2026-07-16", "int_page_read_count": 12}]})
    if path == "/datacube/getusercumulate":
        return httpx.Response(200, json={"list": [{"ref_date": "2026-07-16", "new_user": 3}]})
    if path == "/cgi-bin/draft/add":
        return httpx.Response(200, json={"media_id": "draft-1"})
    if path == "/cgi-bin/freepublish/submit":
        return httpx.Response(200, json={"publish_id": "publish-1"})
    return httpx.Response(404, json={"errcode": 404})


async def run() -> None:
    client = WechatOfficialClient(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert (await client.check_account("app", "secret", cache_key="ref"))["ok"]
    assert len(await client.fetch_articles("app", "secret", cache_key="ref")) == 1
    assert await client.create_draft("app", "secret", cache_key="ref", article={"title": "x"}) == "draft-1"
    assert await client.submit_publish("app", "secret", cache_key="ref", media_id="draft-1") == "publish-1"
    await client.close()
    print("wechat_official_client: ok")


if __name__ == "__main__":
    asyncio.run(run())
