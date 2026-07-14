"""账号设备/网络画像(Identity)。

多账号防关联的核心:每个账号一套**独立且永久固定**的浏览器画像 ——
持久化 profile 目录、固定 UA / 视口 / 时区、专属代理、确定性指纹种子。
画像在登录/建号时生成一次,之后不再变化(指纹漂移本身也是风控信号)。
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# 真实机型 User-Agent 池(Windows/Mac Chrome,版本接近主流)。
# 一号选定一条后固定;切勿频繁变更。
UA_POOL: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

# 常见桌面分辨率(视口)
VIEWPORTS = [(1280, 800), (1366, 768), (1440, 900), (1536, 864), (1600, 900), (1920, 1080)]

# 国内账号统一东八区,务必与代理 IP 地区一致(别 IP 在国内、时区在美洲)
DEFAULT_TZ = "Asia/Shanghai"
DEFAULT_LOCALE = "zh-CN"


@dataclass
class Identity:
    """一个账号的完整浏览器画像。account_id=None 表示匿名(未绑定账号的公开抓取)。"""
    account_id: Optional[int]
    profile_dir: str
    proxy: str = ""
    ua: str = ""
    viewport_w: int = 1280
    viewport_h: int = 800
    timezone_id: str = DEFAULT_TZ
    locale: str = DEFAULT_LOCALE
    fp_seed: str = ""
    # 迁移桥:首次为存量账号创建持久 profile 时,把这些登录态 Cookie 注入进去。
    bridge_states: tuple = ()

    @property
    def key(self):
        return self.account_id if self.account_id is not None else "_anon"

    @classmethod
    def from_account(cls, acc, profiles_root: str, default_ua: str) -> "Identity":
        pdir = acc.profile_dir or str(Path(profiles_root) / f"acc_{acc.id}")
        bridge = tuple(s for s in (getattr(acc, "storage_state", ""),
                                   getattr(acc, "creator_storage_state", "")) if s)
        return cls(
            account_id=acc.id, profile_dir=pdir, proxy=acc.proxy or "",
            ua=acc.ua or default_ua,
            viewport_w=acc.viewport_w or 1280, viewport_h=acc.viewport_h or 800,
            timezone_id=acc.timezone_id or DEFAULT_TZ,
            locale=acc.locale or DEFAULT_LOCALE,
            fp_seed=acc.fp_seed or seed_from_id(acc.id),
            bridge_states=bridge,
        )


def seed_from_id(account_id) -> str:
    """没有显式种子时,用账号 id 派生一个稳定种子(保证同账号每次指纹一致)。"""
    return hashlib.md5(f"creatorhub-acc-{account_id}".encode()).hexdigest()


def generate_identity_fields() -> dict:
    """生成一套全新的画像字段(建号/登录时调用一次,写库后永久固定)。"""
    seed = uuid.uuid4().hex
    rnd = random.Random(seed)
    w, h = rnd.choice(VIEWPORTS)
    return {
        "ua": rnd.choice(UA_POOL),
        "viewport_w": w, "viewport_h": h,
        "timezone_id": DEFAULT_TZ, "locale": DEFAULT_LOCALE,
        "fp_seed": seed,
    }


# 真实 GPU 的 WebGL vendor/renderer(按平台分,ANGLE/Metal 形态),按 seed 固定挑一条。
_WEBGL_WIN = [
    ("Google Inc. (NVIDIA)",
     "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)",
     "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Intel)",
     "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (AMD)",
     "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
]
_WEBGL_MAC = [
    ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)"),
    ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)"),
    ("Google Inc. (Intel Inc.)",
     "ANGLE (Intel Inc., Intel(R) Iris(TM) Plus Graphics OpenGL Engine, OpenGL 4.1)"),
]


def _platform_bits(ua: str):
    """由 UA 推断 navigator.platform / userAgentData.platform / WebGL 池(保持内部一致)。"""
    if "Mac OS" in ua:
        return "MacIntel", "macOS", _WEBGL_MAC
    if "Linux" in ua and "Android" not in ua:
        return "Linux x86_64", "Linux", _WEBGL_WIN
    return "Win32", "Windows", _WEBGL_WIN


def fingerprint_script(seed: str, ua: str = "") -> str:
    """基于 seed 确定性派生的指纹注入脚本(add_init_script),同账号每次一致。
    覆盖:navigator.webdriver / hardwareConcurrency / deviceMemory,
    navigator.platform + userAgentData(与 UA 一致),WebGL vendor/renderer,
    canvas 与 AudioContext 的固定微噪声(幂等,不改动源画布/缓冲,避免多次读取不一致)。
    """
    rnd = random.Random(seed)
    hw = rnd.choice([4, 6, 8, 12, 16])
    mem = rnd.choice([4, 8, 16])
    noise = [rnd.randint(0, 7) for _ in range(8)]           # canvas 像素低位偏移
    noise_js = json.dumps(noise)
    audio_noise = rnd.uniform(1e-7, 1e-6)                   # AudioContext 极小扰动
    platform, ua_data_plat, webgl_pool = _platform_bits(ua)
    gl_vendor, gl_renderer = rnd.choice(webgl_pool)
    v = "0"
    m = re.search(r"Chrome/(\d+)", ua or "")
    if m:
        v = m.group(1)
    is_edge = "Edg/" in ua
    if is_edge:
        brands_js = (f'[{{"brand":"Chromium","version":"{v}"}},'
                     f'{{"brand":"Microsoft Edge","version":"{v}"}},'
                     f'{{"brand":"Not?A_Brand","version":"99"}}]')
    else:
        brands_js = (f'[{{"brand":"Chromium","version":"{v}"}},'
                     f'{{"brand":"Google Chrome","version":"{v}"}},'
                     f'{{"brand":"Not?A_Brand","version":"99"}}]')
    return f"""
(() => {{
  const def = (o, k, v) => {{ try {{
    Object.defineProperty(o, k, {{get: () => v, configurable: true}});
  }} catch (e) {{}} }};
  def(navigator, 'webdriver', false);
  def(navigator, 'hardwareConcurrency', {hw});
  def(navigator, 'deviceMemory', {mem});
  def(navigator, 'platform', {json.dumps(platform)});
  // userAgentData 与 UA / Sec-CH-UA 三者一致
  try {{
    const brands = {brands_js};
    const uad = {{
      brands: brands, mobile: false, platform: {json.dumps(ua_data_plat)},
      getHighEntropyValues: (hints) => Promise.resolve({{
        brands: brands, mobile: false, platform: {json.dumps(ua_data_plat)},
        platformVersion: "10.0.0", architecture: "x86", bitness: "64",
        uaFullVersion: "{v}.0.0.0",
        fullVersionList: brands.map(b => ({{brand: b.brand, version: b.version + '.0.0.0'}})),
      }}),
    }};
    def(navigator, 'userAgentData', uad);
  }} catch (e) {{}}
  // WebGL vendor/renderer
  try {{
    const patch = (proto) => {{
      const gp = proto.getParameter;
      proto.getParameter = function(p) {{
        if (p === 37445) return {json.dumps(gl_vendor)};   // UNMASKED_VENDOR_WEBGL
        if (p === 37446) return {json.dumps(gl_renderer)}; // UNMASKED_RENDERER_WEBGL
        return gp.apply(this, arguments);
      }};
    }};
    if (window.WebGLRenderingContext) patch(WebGLRenderingContext.prototype);
    if (window.WebGL2RenderingContext) patch(WebGL2RenderingContext.prototype);
  }} catch (e) {{}}
  // canvas 噪声:只在「读取副本」上加,不回写源画布 -> 幂等,多次读一致
  const NOISE = {noise_js};
  const addNoise = (data) => {{
    for (let i = 0; i < data.length; i += 4) {{
      data[i] = (data[i] + NOISE[(i >> 2) % NOISE.length]) & 0xff;
    }}
  }};
  const _gid = CanvasRenderingContext2D.prototype.getImageData;
  CanvasRenderingContext2D.prototype.getImageData = function() {{
    const d = _gid.apply(this, arguments);   // 源画布未被改动,每次读都是原始像素
    try {{ addNoise(d.data); }} catch (e) {{}}
    return d;
  }};
  const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function() {{
    try {{
      const w = this.width, h = this.height;
      if (w && h) {{
        const c = document.createElement('canvas');
        c.width = w; c.height = h;
        const cx = c.getContext('2d');
        cx.drawImage(this, 0, 0);
        const d = _gid.apply(cx, [0, 0, w, h]);   // 用原生 getImageData 取副本,避免二次加噪
        addNoise(d.data);
        cx.putImageData(d, 0, 0);
        return _toDataURL.apply(c, arguments);    // 源画布始终干净
      }}
    }} catch (e) {{}}
    return _toDataURL.apply(this, arguments);
  }};
  // AudioContext 噪声:每个 buffer 只扰动一次(WeakSet 记账),避免重复叠加
  try {{
    const seen = new WeakSet();
    const _gcd = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function() {{
      const d = _gcd.apply(this, arguments);
      if (!seen.has(this)) {{
        seen.add(this);
        try {{ for (let i = 0; i < d.length; i += 100) d[i] += {audio_noise:.10f}; }} catch (e) {{}}
      }}
      return d;
    }};
  }} catch (e) {{}}
}})();
"""
