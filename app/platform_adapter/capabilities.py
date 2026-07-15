"""Built-in capability matrix for current CreatorHub platforms."""
from __future__ import annotations

from typing import Dict, List

from .contracts import AdapterCapability, PlatformCapabilities, PlatformId


BUILTIN_CAPABILITIES: Dict[PlatformId, AdapterCapability] = {
    PlatformId.DOUYIN: AdapterCapability(
        platform=PlatformId.DOUYIN,
        display_name="抖音",
        capabilities=PlatformCapabilities(
            public_content_monitor=True,
            keyword_search=False,
            own_account_works=True,
            content_download=True,
            comment_read=True,
            comment_write=True,
            publish=True,
            follow_graph=True,
            dm=True,
            creator_center=True,
            supports_browser_runtime=True,
            supports_api_runtime=True,
            known_limits=["关键词发现暂未实现", "部分写操作需要有头浏览器兜底"],
        ),
    ),
    PlatformId.XHS: AdapterCapability(
        platform=PlatformId.XHS,
        display_name="小红书",
        capabilities=PlatformCapabilities(
            public_content_monitor=True,
            keyword_search=True,
            own_account_works=True,
            content_download=True,
            comment_read=True,
            comment_write=True,
            publish=True,
            follow_graph=True,
            dm=False,
            creator_center=True,
            requires_logged_account_for_read=True,
            supports_browser_runtime=True,
            supports_api_runtime=True,
            known_limits=["读取态与创作态可能不同", "部分接口依赖 a1 Cookie 与 xsec_token"],
        ),
    ),
    PlatformId.KUAISHOU: AdapterCapability(
        platform=PlatformId.KUAISHOU,
        display_name="快手",
        capabilities=PlatformCapabilities(
            public_content_monitor=True,
            keyword_search=False,
            own_account_works=True,
            content_download=True,
            comment_read=True,
            comment_write=True,
            publish=True,
            follow_graph=True,
            dm=True,
            creator_center=True,
            supports_browser_runtime=True,
            supports_api_runtime=False,
            known_limits=["关键词发现暂未实现", "主要依赖浏览器拦截 GraphQL"],
        ),
    ),
    PlatformId.SHIPINHAO: AdapterCapability(
        platform=PlatformId.SHIPINHAO,
        display_name="视频号",
        capabilities=PlatformCapabilities(
            public_content_monitor=False,
            keyword_search=False,
            own_account_works=True,
            content_download=False,
            comment_read=True,
            comment_write=True,
            publish=True,
            follow_graph=False,
            dm=False,
            creator_center=True,
            requires_logged_account_for_read=True,
            supports_browser_runtime=True,
            supports_api_runtime=False,
            known_limits=["仅支持创作者助手中的本账号数据", "不支持监控他人作品", "加密 CDN 不承诺下载搬运"],
        ),
    ),
    PlatformId.WECHAT_MP: AdapterCapability(
        platform=PlatformId.WECHAT_MP,
        display_name="微信公众号",
        capabilities=PlatformCapabilities(
            public_content_monitor=False,
            keyword_search=False,
            own_account_works=False,
            content_download=False,
            comment_read=False,
            comment_write=False,
            publish=False,
            follow_graph=False,
            dm=False,
            creator_center=True,
            requires_logged_account_for_read=True,
            supports_browser_runtime=False,
            supports_api_runtime=True,
            known_limits=[
                "默认 restricted 模式不声明账号数据或发布能力",
                "认证公众号的官方 API 能力需通过 CredentialRef 启用",
                "服务端不得托管 C 端普通用户 Cookie",
            ],
        ),
    ),
}


def _coerce_platform(platform: str | PlatformId) -> PlatformId:
    if isinstance(platform, PlatformId):
        return platform
    return PlatformId(platform)


def get_capabilities(platform: str | PlatformId) -> AdapterCapability:
    return BUILTIN_CAPABILITIES[_coerce_platform(platform)]


def list_capabilities() -> List[AdapterCapability]:
    return list(BUILTIN_CAPABILITIES.values())
