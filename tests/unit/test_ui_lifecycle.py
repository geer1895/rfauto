"""aurora36 W2-B 席位回归钉：UI 前端资源生命周期（R1 审计 P0-4/P0-5/P2-13/P0-6）。

对象：src/rfauto/ui/static/pages.js（app.js/plotcard.js 归 W2-C，本文件只读）。

三层：
1. **源码钉（免 node）**：
   - echarts.init 调用点实例缓存守卫——window.echarts.init 全文件仅
     echartsInitCached 一处（同容器存活实例复用 + 容器换血先 dispose）；
   - window resize 监听去重——_resizeBound WeakSet 标记，全文件仅
     bindChartResize 一处挂监听；
   - tune 页 plotCard 容器级复用（UI-R5 归一：plotCardCached 薄委托，
     setOption 复用 + 导出钮 handlers 现取防陈旧数据 + aria 同步在
     plotcard.js plotCard 单一入口内建）；
   - 轮询生命周期托管——tune/loopboard 回调 _pollVisible 当前页+
     visibilityState 双守卫（不可见跳过 fetch 定时器保留）、visibilitychange
     隐藏暂停/恢复立即拉一次、终态停不得复活；
   - WebGL 防御式释放——T.drawBoxes 两调用侧前置 releaseWebGLIn
     （WEBGL_lose_context 强制弃置上下文）+ drawIsoMesh 自登记 renderer
     完全释放 + 接口诉求注释在档（drawBoxes 返回 renderer 句柄+dispose，
     合流转 W2-C）；
   - 内联错误色令牌化（color:#e57373 归零，API 错误提示走 var(--err)）。
2. **跨席计数钉**：T.plotCard( == 12 / T.drawEChart( == 0 / mode:"convergence"
   == 2（与 test_ui_plotcard 迁移钉同源复述；本文件先红 = 生命周期包装被误改，
   先于 52 分钟门暴露）。
3. **行为钉（node 在才跑，否则诚实 skip）**：node --check 语法自检 +
   pages.js→plotcard.js 循环 import 冒烟（W2-B 新增依赖，函数级消费）。

不依赖 runs/、不读网络、不启动服务器。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")
# aurora_d UI-R2（2026-10-14）：pages.js 拆分为薄入口 + pages/ 域模块（零构建
# ESM）——源码钉读"入口+全部域模块"并集，行为断言逐字不变（拆分前=单文件）。
def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)

_SRC = _pages_union_text()



def _body(func_sig: str) -> str:
    """取顶层函数体（起于 function 声明行，止于首个列 0 收括号）。"""
    m = re.search(func_sig + r" \{(.*?)\n\}", _SRC, re.S)
    assert m, f"函数体缺失: {func_sig}"
    return m.group(1)


# ────────────────────────── 1. 源码钉 ──────────────────────────

class TestChartInstanceCache:
    """P0-5：echarts 实例缓存守卫 + resize 监听去重。"""

    def test_echarts_init_single_guarded_entry(self):
        # 全文件只允许一处 window.echarts.init（实例缓存守卫内部）——
        # 新调用面一律走 echartsInitCached，杜绝"每渲染一新实例"
        assert _SRC.count("window.echarts.init(") == 1
        body = _body(r"function echartsInitCached\(el\)")
        assert "_liveCharts.get(el)" in body  # 实例缓存守卫
        assert "isDisposed()" in body  # 存活判定
        assert "prev.dispose()" in body  # 容器换血先释放旧实例
        assert "_liveCharts.set(el, chart)" in body  # 新实例登记

    def test_resize_listener_dedup(self):
        # 全文件只允许一处 window resize 挂监听（去重标记内部）
        assert _SRC.count('window.addEventListener("resize"') == 1
        assert "_resizeBound = new WeakSet()" in _SRC  # 去重标记（WeakSet）
        assert re.search(r"if \(_resizeBound\.has\(el\)\) return;", _SRC)
        # 四个直接 init 面（远场极坐标/Smith/场切片/远场 3D 热图）都走去重绑定
        assert _SRC.count("bindChartResize(el); // P0-5") == 4

    def test_subtree_regen_disposes_charts_first(self):
        # 容器 innerHTML 换血前必须先释放旧实例（缓存键随元素走）
        assert _SRC.count("disposeChartsIn(") == 4  # 1 定义 + 3 调用
        assert _SRC.count("disposeChartsIn(box); // P0-5") == 2  # 远场/场切片
        assert "disposeChartsIn(pEl); // P0-5" in _SRC  # 远场 3D 热图


class TestTunePlotCardReuse:
    """P0-5 → UI-R5 归一：tune 3s 轮询容器级复用。

    UI-R5（2026-10-14）起复用实现下沉 plotcard.js plotCard 单一入口（W2-B
    接口诉求闭合），plotCardCached 降级零破坏薄委托——本类断言随迁：包装
    钉单行委托；复用守卫/CSV-aria 刷新钉读 plotcard.js（源码钉惯例，node
    不可驱同前）。"""

    def test_tune_call_site_uses_cached_wrapper(self):
        assert 'plotCardCached(T.$("tune-trials-chart")' in _SRC

    def test_wrapper_is_thin_delegate_and_reuse_lives_in_plotcard(self):
        body = _body(r"function plotCardCached\(el, props\)")
        # 零破坏薄委托：单一入口直连（复用语义在 plotCard 内建）
        assert body.count("T.plotCard(") == 1
        assert "return T.plotCard(el, props);" in body
        # 复用守卫钉（plotcard.js）：存活 + DOM 还挂在容器里 + notMerge 整体替换
        pc = (_STATIC / "plotcard.js").read_text(encoding="utf-8")
        m = re.search(
            r"export function plotCard\(el, props = \{\}, ctx = \{\}\) \{(.*?)\n\}",
            pc, re.S)
        assert m, "plotCard 函数体缺失"
        pbody = m.group(1)
        assert "prevShell.chart.isDisposed()" in pbody  # 复用守卫：存活才复用
        assert "el.contains(prevShell.chart.getDom())" in pbody  # 且壳还挂容器里
        assert re.search(
            r"prevShell\.chart\.setOption\(plotCardOption\(props, shell\.ctx\), true\);",
            pbody,
        ), "setOption 复用（notMerge 整体替换）缺失"  # 同容器复用不走新 init

    def test_wrapper_refreshes_csv_button_and_aria(self):
        # 导出钮 handlers 读 shell 现取（props 换代后闭包不陈旧——数据诚实面）
        # + aria 随数据刷新（复用路径与首渲染同构单源 _ariaLabel）
        pc = (_STATIC / "plotcard.js").read_text(encoding="utf-8")
        assert "toCsv(shell.props.series)" in pc
        assert "getCsv: () => \"\\ufeff\" + toCsv(shell.props.series)," in pc
        assert 'getDom().setAttribute("aria-label", _ariaLabel(props));' in pc
        assert "function _ariaLabel(props)" in pc  # 单源（首渲染/复用共用）

    def test_recipe_render_debounced(self):
        # P0-4 改法：参数 oninput 每键一渲染 → 250ms 防抖（playground 同款）
        assert "clearTimeout(r3dDebounce)" in _SRC
        assert "setTimeout(r3dDraw, 250)" in _SRC


class TestPollingLifecycle:
    """P2-13：轮询离页空转治理（当前页+可见性守卫 / 隐藏暂停 / 恢复即拉）。"""

    def test_poll_callbacks_have_view_and_visibility_guard(self):
        # 回调先查当前页 + document.visibilityState：不可见跳过 fetch（定时器保留）
        assert 'if (!_pollVisible("tune")) return;' in _SRC
        assert 'if (!_pollVisible("loopboard")) return;' in _SRC
        body = _body(r"function _pollVisible\(view\)")
        assert 'style.display !== "none"' in body  # 当前页守卫
        assert 'document.visibilityState !== "hidden"' in body  # 可见性守卫

    def test_poll_registration_and_terminal_stop(self):
        assert '_pollRegister("tune", "tune", pollTune, 3000)' in _SRC
        assert '_pollRegister("loopboard", "loopboard", pollBoard, 2000)' in _SRC
        assert '_pollStop("tune", true)' in _SRC  # 终态停：清 fn 不得复活

    def test_free_floating_timers_gone(self):
        # 旧的自由定时器变量/直挂形态必须清零（防回归离页空转）
        assert "tuneTimer" not in _SRC
        assert "loopTimer" not in _SRC
        assert "setInterval(pollTune" not in _SRC
        assert "setInterval(pollBoard" not in _SRC
        # setInterval 只允许出现在轮询托管器（注册 + 恢复重启）两处
        assert _SRC.count("setInterval(") == 2

    def test_visibilitychange_pause_and_resume(self):
        body = _body(r"function _bindVisibilityPolling\(\)")
        assert 'document.addEventListener("visibilitychange"' in body
        assert 'document.visibilityState === "hidden"' in body
        assert "clearInterval(p.timer)" in body  # 隐藏：暂停定时器
        assert "setInterval(p.fn, p.intervalMs)" in body  # 恢复：重启定时器
        assert "p.fn(); // 恢复可见：立即拉一次" in body  # 恢复立即拉一次
        # 监听在 initPages 装配（模块顶层零 DOM 依赖，node 行为钉可 import）
        assert "_bindVisibilityPolling(); // aurora36 W2-B" in _SRC
        # 页面激活态由 showPage 单源写入
        assert 'let _activeView = "dashboard";' in _SRC
        assert "_activeView = v; // aurora36 W2-B" in _SRC


class TestWebGLDefensiveRelease:
    """P0-4：WebGL 上下文泄漏的调用侧防御 + W2-C 接口诉求在档。"""

    def test_drawboxes_call_sites_release_first(self):
        assert 'releaseWebGLIn(T.$("recipe-3d"));' in _SRC
        assert 'releaseWebGLIn(T.$("detail-3d"));' in _SRC
        # 顺序钉：释放必须先于绘制
        for rid in ("recipe-3d", "detail-3d"):
            rm = re.search(rf'releaseWebGLIn\(T\.\$\("{rid}"\)\);', _SRC)
            dm = re.search(rf'T\.drawBoxes\(T\.\$\("{rid}"\)', _SRC)
            assert rm and dm and rm.start() < dm.start(), rid

    def test_lose_context_defense_and_interface_request(self):
        assert 'getExtension("WEBGL_lose_context")' in _SRC
        assert "loseContext()" in _SRC
        # 接口诉求注释在档（合流转 W2-C：drawBoxes 返回 renderer 句柄 + dispose）
        assert "接口诉求" in _SRC
        assert "返回 renderer 句柄" in _SRC

    def test_drawisomesh_self_tracked_renderer(self):
        # pages.js 自有 3D 管线完全自愈：停循环 → dispose → forceContextLoss
        assert "_isoRenderers = new WeakMap()" in _SRC
        body = re.search(
            r"function drawIsoMesh\(container, iso\) \{(.*?)renderer\.setAnimationLoop",
            _SRC, re.S)
        assert body, "drawIsoMesh 函数体缺失"
        b = body.group(1)
        assert "prevR.setAnimationLoop(null)" in b
        assert "prevR.dispose()" in b
        assert "prevR.forceContextLoss()" in b
        assert "_isoRenderers.set(container, renderer)" in b

    def test_field_page_regen_releases_before_rebuild(self):
        # 等值面容器换血前释放旧 renderer/上下文（pageField.load）
        rm = re.search(r"releaseWebGLIn\(isoEl\); // P0-4", _SRC)
        im = re.search(r"isoEl\.innerHTML =", _SRC)
        assert rm and im and rm.start() < im.start()


class TestErrorColorToken:
    """P0-6：API 错误提示内联色走令牌（--err），禁 hex 直写。"""

    def test_no_inline_hardcoded_error_hex(self):
        assert "color:#e57373" not in _SRC
        # 6 处 ✗ 错误提示全令牌化（本席改 3 + 既有 3；图表深色调色板数组的
        # #e57373 属系列色主题分档，归 a11y 钉口径，不在本钉范围）
        assert _SRC.count("color:var(--err)'>✗") == 6


class TestCrossSeatCountPins:
    """跨席计数钉（与 test_ui_plotcard 迁移钉同源）：生命周期包装不得打破
    plotCard 迁移不变量；此钉先红即指因本席改动面。"""

    def test_plotcard_migration_invariants_hold(self):
        assert _SRC.count("T.plotCard(") == 12
        assert _SRC.count("T.drawEChart(") == 0
        assert _SRC.count('mode: "convergence"') == 2
        assert _SRC.count("crosshair: true") == 4


# ────────────────────────── 2. 行为钉（node 在才跑） ──────────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestNodeBehavioral:
    def test_node_check_pages_js(self):
        r = subprocess.run([_NODE, "--check", str(_STATIC / "pages.js")],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]

    def test_pages_plotcard_cycle_import_smoke(self):
        # W2-B 新增 pages.js → plotcard.js 静态依赖（plotCardOption/toCsv，
        # 函数级消费、零顶层执行）：与既有 plotcard.js → pages.js（esc）构成
        # 循环引用，node ESM 必须可解析（浏览器同规则）
        js = (
            "const p = await import('./pages.js');\n"
            "if (typeof p.themeIsLight !== 'function') throw new Error('pages 导出缺失');\n"
            "if (typeof p.showPage !== 'function') throw new Error('showPage 缺失');\n"
            "const pc = await import('./plotcard.js');\n"
            "if (typeof pc.plotCardOption !== 'function') throw new Error('plotcard 导出缺失');\n"
            "console.log('ok:cycle');\n"
        )
        r = subprocess.run([_NODE, "--input-type=module", "-e", js],
                           capture_output=True, text=True, timeout=60,
                           cwd=str(_STATIC))
        assert r.returncode == 0, r.stderr[-2000:]
        assert "ok:cycle" in r.stdout


# ────────── 跨席合流件：drawBoxes 容器级句柄（主代理落 W2-B 接口诉求） ──────────

def test_drawboxes_returns_renderer_handle():
    js = (_STATIC / "app.js").read_text(encoding="utf-8")
    assert "_boxRenderers" in js, "app.js 缺容器级 renderer 登记"
    assert "_prev.forceContextLoss" in js, "重建前未强制弃置旧上下文"
    assert "return renderer;" in js, "drawBoxes 未返回句柄"
