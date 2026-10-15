"""UI 响应 CSP 策略单源（哈希钉常量 + 纯 ASGI 中间件）——自 ui/server.py 逐字节搬家。

装配面（middleware=[Middleware(ContentSecurityPolicyMiddleware)]）仍在
ui/server.py create_ui_app；server.py 薄 re-export CSP_HEADER/CSP_VALUE/
ContentSecurityPolicyMiddleware 保持既有引用路径（test_w1e_ui_csp）不变。
"""

from __future__ import annotations

from typing import Any

from starlette.datastructures import MutableHeaders

# D-04（2026-10-05 W1-E）：CSP 响应头——script-src 'self' + 内联脚本的
# 内容哈希钉。接地（index.html 现状）：7 个 <script> 中 5 个外链
# （3 vendor + 2 module），2 个内联：<script type="importmap">（外部
# importmap 浏览器不支持，改外链不可行）与主题防闪 boot（head，guide
# §13.1，aurora36 W2-A）；'unsafe-inline' 又会豁免全部
# 内联脚本，故按 CSP3 对内联脚本内容逐个做 sha256 哈希钉：任何内联内容
# 改动都会被浏览器拒绝加载，tests/unit/test_w1e_ui_csp.py 会同步抓出
# 哈希失配。只下 script-src 单指令、不下 default-src（index.html 有内联
# <style> 与 style="" 属性，default-src 'self' 会连带禁掉内联样式打断
# 现有渲染）；页内处理器全部是 JS 侧 .onclick= 属性赋值（非 HTML 内联
# on* 属性），不受 script-src 影响；vendor/echarts.min.js 里的 new Function
# 是 JSON.parse 守卫后的死回退分支（实测运行路径不触），无需 unsafe-eval。
_IMPORTMAP_SHA256 = "sha256-IpwqAkJYJf7czCtp9NzVZDetH2T3BlxA1lkI/4V7auk="
# aurora36 W2-A（2026-10-11）：第二个内联脚本=主题防闪 boot（index.html head，
# guide §13.1 FOUC）——同规则 sha256 哈希钉；改 boot 内容必须同步本常量
# （tests/unit/test_w1e_ui_csp.py 与 tests/unit/test_ui_theme_boot.py 双门抓失配）。
_THEME_BOOT_SHA256 = "sha256-F/hJthl5Fxg/BFdnyqcIIpWA0NcaJN8FAJ+NNYiFrpk="
CSP_HEADER = "Content-Security-Policy"
CSP_VALUE = f"script-src 'self' '{_IMPORTMAP_SHA256}' '{_THEME_BOOT_SHA256}'"


class ContentSecurityPolicyMiddleware:
    """纯 ASGI 中间件：全部 HTTP 响应附加 CSP 头（D-04）。

    setitem 覆写语义保证重复包裹/上游已有同名头时单头不叠；非 http scope
    （websocket/lifespan，如 SSE 由 http 起步不受影响）原样直通（#105：
    观测/加固面故障不得阻塞业务主路径——头写入本身不抛，异常面已由
    Starlette 响应生命周期兜住）。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_csp(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[CSP_HEADER] = CSP_VALUE
            await send(message)

        await self.app(scope, receive, send_with_csp)
