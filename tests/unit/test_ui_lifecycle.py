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
2. **跨席计数钉**：T.plotCard( == 16 / T.drawEChart( == 0 / mode:"convergence"
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
        # 原四个直接 init 面（远场极坐标/Smith/场切片/远场 3D 热图）W3-S12 起
        # 已整体迁 plotCard 逃生舱（壳内建 resize 去重）——绑定调用清零，
        # 存量消费=tools 页 A3-A 一处
        assert _SRC.count("bindChartResize(el); // P0-5") == 0
        assert _SRC.count("bindChartResize(el); // aurora72 A3-A") == 1

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
        # ✗ 错误提示全令牌化（图表深色调色板数组的 #e57373 属系列色主题
        # 分档，归 a11y 钉口径，不在本钉范围）。
        # aurora_f W2-S5：gallery 闭式计算失败点迁 kitErrorPanel（R1 #8
        # 三态批1），✗ 余量 6→5 同笔。
        # aurora_g W14-S2：playground×2/profile/tools 内联 ✗ span 迁
        # kitErrorPanel（R2 Top10 #4 归一波），✗ 余量 5→1 同笔
        #（余 1=queue 豁免点，跨席注释在档）。
        assert _SRC.count("color:var(--err)'>✗") == 1


class TestCrossSeatCountPins:
    """跨席计数钉（与 test_ui_plotcard 迁移钉同源）：生命周期包装不得打破
    plotCard 迁移不变量；此钉先红即指因本席改动面。"""

    def test_plotcard_migration_invariants_hold(self):
        # 12（W2 收口）+ 4（W3-S12 四管线逃生舱迁移：polar/Smith/场切片/远场3D）
        # + 2（aurora_i W3-S2：画廊对照曲线节 + S 参数页对照卡）
        assert _SRC.count("T.plotCard(") == 18
        assert _SRC.count("T.drawEChart(") == 0
        assert _SRC.count('mode: "convergence"') == 2
        # + 6 aurora_j W3-S9（数值读数类开十字线：playground/timeline×2/
        # calibration×2/optstack）
        assert _SRC.count("crosshair: true") == 12


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


# ────────── R-1 页面生命周期协议 + F-4 降噪（aurora72 W1-S3 席位钉） ──────────

class TestPageLifecycleProtocol:
    """R-1（aurora72 W1-S3，R6 审计 R-1）：PageContext 增量钩子协议。

    形态：VIEWS 键→渲染函数（=enter 面）不动；router.js PAGE_CTX 只登记
    { refresh?, leave? } 增量——palette 刷新走 ctx.refresh（未登记页回退
    showPage 整页重进）、showPage 离页调 prev.leave（先于激活，best-effort）。
    试点批（W1-S3）=dashboard（静态）+loopboard（懒加载 _lazyCtx）；波2
    （aurora_e W2-S7）=tune/detail/runs/campaign/reports 五页（懒加载
    _lazyCtx）；波3 第二组（aurora_e W3-S12）=sparams/calibration/queue/
    gallery/optstack/timeline 六页（全 refresh-only）；波4 收尾（aurora_e
    W4-S17）=solvers/profile/datasets/anchors/uq/playground/farfield/field/
    agent/recipe/tools 十一页（全 refresh-only；guide/import 两页按"有数据面
    才迁"原则跳过——纯静态壳/无进页数据面）。_POLLS 托管语义保留
    （上方 TestPollingLifecycle 全套钉继续有效=协议与轮询托管共存的前提）。"""

    def test_registry_and_query_surface_in_router(self):
        router = (_STATIC / "pages" / "router.js").read_text(encoding="utf-8")
        assert "export const PAGE_CTX = {};" in router
        assert "export function pageContextFor(v)" in router
        # 查询器：未登记页返回 null（hasOwnProperty 防 Object.prototype 撞键）
        body = re.search(
            r"export function pageContextFor\(v\) \{(.*?)\n\}", router, re.S)
        assert body and "hasOwnProperty.call(PAGE_CTX, v)" in body.group(1)

    def test_showpage_leave_wiring_before_activate(self):
        router = (_STATIC / "pages" / "router.js").read_text(encoding="utf-8")
        m = re.search(r"export function showPage\(v\) \{(.*?)\n\}", router, re.S)
        assert m, "showPage 函数体缺失"
        body = m.group(1)
        assert "const prev = getActiveView();" in body  # 离页=激活前视图
        assert "if (prev !== v) {" in body  # 同页重入不触发离页收束
        assert 'typeof prevCtx.leave === "function"' in body
        assert "try { prevCtx.leave(); } catch" in body  # #105 best-effort 不阻切页
        # 离页收束先于激活（旧页停表后才落新页）
        assert body.find("prevCtx.leave()") < body.find("setActiveView(v)")

    def test_palette_refresh_prefers_ctx_with_fallback(self):
        pal = (_STATIC / "palette.js").read_text(encoding="utf-8")
        assert "pageContextFor(v)" in pal
        assert 'typeof ctx.refresh === "function"' in pal  # 局部刷新入口
        assert "showPage(v);" in pal  # 未登记页回退整页重进（旧行为）

    def test_pilot_pages_registered(self):
        pages = (_STATIC / "pages.js").read_text(encoding="utf-8")
        assert "dashboard: dashboardCtx," in pages
        assert '_lazyCtx("view_loopboard.js", "loopboardCtx")' in pages
        # VIEWS 注册面零迁移（r12 注册序字节钉的前提：dashboard 仍 pageDashboard）
        assert "dashboard: pageDashboard, import: pageImport" in pages


class TestLoopboardRenderDedup:
    """F-4（aurora72 W1-S3，R6 审计 F-4=R1 P1-11 清偿）：2s 全量重绘降噪。

    pollBoard 以 payload 序列化串为键比对，无变化跳过全部 DOM 写面——
    此前每 tick 重建里程碑+步骤两表（文本选区打断+闪烁根因）。"""

    def test_payload_cache_short_circuit_before_dom_writes(self):
        lb = (_STATIC / "pages" / "view_loopboard.js").read_text(encoding="utf-8")
        m = re.search(r"async function pollBoard\(\) \{(.*?)\n\}", lb, re.S)
        assert m, "pollBoard 函数体缺失"
        body = m.group(1)
        assert 'JSON.stringify(b)' in body  # payload 序列化比对键
        assert 'loopSelected + "\\u0000" +' in body  # 键含 board_id（换板失效）
        assert "if (key === _lastBoardKey) return;" in body  # 无变化跳过渲染
        # 五处写面（lb-status/lb-current/两表 tbody/lb-best）全部在跳过检查之后
        assert body.count(".innerHTML") == 5
        assert body.find("if (key === _lastBoardKey)") < body.find(".innerHTML")

    def test_error_payload_invalidates_cache(self):
        lb = (_STATIC / "pages" / "view_loopboard.js").read_text(encoding="utf-8")
        m = re.search(r"async function pollBoard\(\) \{(.*?)\n\}", lb, re.S)
        body = m.group(1)
        # 错误响应清缓存：恢复后即使 payload 回到旧串也强制重绘（不留陈旧错误态）
        assert body.find("_lastBoardKey = null") < body.find("if (key === _lastBoardKey)")

    def test_ctx_hooks_delegate_and_leave_stops_poll(self):
        lb = (_STATIC / "pages" / "view_loopboard.js").read_text(encoding="utf-8")
        m = re.search(r"export const loopboardCtx = \{(.*?)\n\};", lb, re.S)
        assert m, "loopboardCtx 缺失"
        body = m.group(1)
        assert "refresh: () => pollBoard()" in body  # 立即拉一次（不重进）
        assert 'leave: () => _pollStop("loopboard")' in body  # 离页停表（非终态）
        # _pollVisible 双守卫仍在回调首行（轮询托管语义保留）
        assert 'if (!_pollVisible("loopboard")) return;' in lb


class TestPageLifecycleWave2:
    """R-1 波2（aurora_e W2-S7，R6 审计 R-1 余页迁移）：tune/detail/runs/
    campaign/reports 五页 PageContext 登记。形态同 W1 试点——懒加载页经
    pages.js _lazyCtx 包装，钩子实体在各 view_*.js 导出的 xxCtx。"""

    def test_five_pages_registered_in_pages_js(self):
        pages = (_STATIC / "pages.js").read_text(encoding="utf-8")
        for key, file, name in (
            ("tune", "view_tune.js", "tuneCtx"),
            ("detail", "view_detail.js", "detailCtx"),
            ("runs", "view_runs.js", "runsCtx"),
            ("campaign", "view_campaign.js", "campaignCtx"),
            ("reports", "view_reports.js", "reportsCtx"),
        ):
            assert f'{key}: _lazyCtx("{file}", "{name}")' in pages, key
        # W1 试点两行原样保留（注册表只增不减）
        assert "dashboard: dashboardCtx," in pages
        assert '_lazyCtx("view_loopboard.js", "loopboardCtx")' in pages

    def test_tune_ctx_hooks_and_poll_semantics_untouched(self):
        tune = (_STATIC / "pages" / "view_tune.js").read_text(encoding="utf-8")
        m = re.search(r"export const tuneCtx = \{(.*?)\n\};", tune, re.S)
        assert m, "tuneCtx 缺失"
        body = m.group(1)
        assert "refresh: () => tuneRefresh()" in body  # 立即拉状态+trials
        assert 'leave: () => _pollStop("tune")' in body  # 非终态停表（fn 保留）
        assert re.search(r'leave:.*_pollStop\("tune",\s*true\)', body) is None
        # 终态停语义原位保留（tuneRefresh 内，登记面不得挪走）
        assert '_pollStop("tune", true)' in tune
        # 轮询托管三钉原样（_pollVisible 守卫逐字 + 注册行 + 渲染体模块级共用）
        assert 'if (!_pollVisible("tune")) return;' in tune
        assert '_pollRegister("tune", "tune", pollTune, 3000)' in tune

    def test_detail_ctx_refresh_rerenders_current_run(self):
        det = (_STATIC / "pages" / "view_detail.js").read_text(encoding="utf-8")
        m = re.search(r"export const detailCtx = \{(.*?)\n\};", det, re.S)
        assert m, "detailCtx 缺失"
        assert "refresh: () => showRun(S.currentRunId)" in m.group(1)

    def test_wave3_six_pages_registered_in_pages_js(self):
        # R-1 波3 第二组（aurora_e W3-S12）：sparams/calibration/queue/
        # gallery/optstack/timeline 六页登记（全 refresh-only，无轮询面
        # =无 leave 需求；_lazyCtx 包装形态与波2 同构）。
        pages = (_STATIC / "pages.js").read_text(encoding="utf-8")
        for key, file, name in (
            ("sparams", "view_sparams.js", "sparamsCtx"),
            ("calibration", "view_calibration.js", "calibrationCtx"),
            ("queue", "view_queue.js", "queueCtx"),
            ("gallery", "view_gallery.js", "galleryCtx"),
            ("optstack", "view_optstack.js", "optstackCtx"),
            ("timeline", "view_timeline.js", "timelineCtx"),
        ):
            assert f'{key}: _lazyCtx("{file}", "{name}")' in pages, key

    def test_sparams_ctx_uses_reload_ref_with_guard(self):
        sp = (_STATIC / "pages" / "view_sparams.js").read_text(encoding="utf-8")
        m = re.search(r"export const sparamsCtx = \{(.*?)\n\};", sp, re.S)
        assert m, "sparamsCtx 缺失"
        # load 闭包经模块级引用转发 + 未进页 null 守卫（campaignCtx 同款模式）
        assert "const f = _sparamsReload; if (f) f();" in m.group(1)
        assert "let _sparamsReload = null;" in sp
        assert "_sparamsReload = load;" in sp

    def test_sparams_run_dropdown_fetches_large_limit_and_restores_deeplink(self):
        # W7-S35 走查 P2-1 回归钉：run 下拉此前裸调 /api/runs（服务端缺省
        # limit=50 截断，较老带 Touchstone run 不可达）；且深链 run 不在
        # 选项集时 sel.value 赋值静默失败回退首项。
        # W4-S13（P8-9 收口）同笔：T.api→apiFetch 统一请求层，limit=500
        # 语义钉原样保留（字面随调用形态同笔更新）。
        sp = (_STATIC / "pages" / "view_sparams.js").read_text(encoding="utf-8")
        assert 'apiFetch("/api/runs?limit=500"' in sp,             "sparams run 下拉必须显式带大 limit（缺省 50 截断面）"
        # W6-S21 i18n 扩面：占位文案=原始 id 前缀+词表后缀段（t 烘焙）
        assert 't("sparams.deeplink_suffix")' in sp and "hasOpt" in sp,             "sparams 深链 run 缺项必须注入占位选项（禁静默回退首项）"

    def test_campaign_ctx_uses_reload_ref_with_guard(self):
        camp = (_STATIC / "pages" / "view_campaign.js").read_text(encoding="utf-8")
        m = re.search(r"export const campaignCtx = \{(.*?)\n\};", camp, re.S)
        assert m, "campaignCtx 缺失"
        # loadDash 是 pageCampaign 闭包——模块级引用转发 + 未进页 null 守卫
        assert "const f = _campaignReload; if (f) f();" in m.group(1)
        assert "let _campaignReload = null;" in camp
        assert "_campaignReload = loadDash;" in camp

    def test_runs_and_reports_ctx_delegate_page_renderers(self):
        runs = (_STATIC / "pages" / "view_runs.js").read_text(encoding="utf-8")
        m = re.search(r"export const runsCtx = \{(.*?)\n\};", runs, re.S)
        assert m and "refresh: () => pageRuns()" in m.group(1)
        rep = (_STATIC / "pages" / "view_reports.js").read_text(encoding="utf-8")
        m = re.search(r"export const reportsCtx = \{(.*?)\n\};", rep, re.S)
        assert m and "refresh: () => pageReports()" in m.group(1)

    def test_wave4_eleven_pages_registered_in_pages_js(self):
        # R-1 波4 收尾（aurora_e W4-S17）：solvers/profile/datasets/anchors/
        # uq/playground/farfield/field/agent/recipe/tools 十一页登记（全
        # refresh-only，无轮询面=无 leave 需求；_lazyCtx 包装形态与波2/3 同构；
        # view_data/view_fieldviz 两模块文件各承载两个键）。
        pages = (_STATIC / "pages.js").read_text(encoding="utf-8")
        for key, file, name in (
            ("solvers", "view_solvers.js", "solversCtx"),
            ("profile", "view_profile.js", "profileCtx"),
            ("datasets", "view_data.js", "datasetsCtx"),
            ("anchors", "view_data.js", "anchorsCtx"),
            ("uq", "view_data.js", "uqCtx"),
            ("playground", "view_playground.js", "playgroundCtx"),
            ("farfield", "view_fieldviz.js", "farfieldCtx"),
            ("field", "view_fieldviz.js", "fieldCtx"),
            ("agent", "view_agent.js", "agentCtx"),
            ("recipe", "view_recipe.js", "recipeCtx"),
            ("tools", "view_tools.js", "toolsCtx"),
        ):
            assert f'{key}: _lazyCtx("{file}", "{name}")' in pages, key

    def test_wave4_delegate_ctx_hooks(self):
        # 九页 refresh=各自 page 函数整体重拉（幂等：壳判 innerHTML 已在即
        # 跳过，或整页重建无交互态）。无轮询面=无 leave 钩子（与波3 同口径）。
        for fname, ctx, page in (
            ("view_solvers.js", "solversCtx", "pageSolvers"),
            ("view_profile.js", "profileCtx", "pageProfile"),
            ("view_data.js", "datasetsCtx", "pageDatasets"),
            ("view_data.js", "anchorsCtx", "pageAnchors"),
            ("view_data.js", "uqCtx", "pageUq"),
            ("view_playground.js", "playgroundCtx", "pagePlayground"),
            ("view_fieldviz.js", "farfieldCtx", "pageFarfield"),
            ("view_recipe.js", "recipeCtx", "pageRecipe"),
            ("view_tools.js", "toolsCtx", "pageTools"),
        ):
            src = (_STATIC / "pages" / fname).read_text(encoding="utf-8")
            m = re.search(rf"export const {ctx} = \{{(.*?)\n\}};", src, re.S)
            assert m, f"{ctx} 缺失"
            assert f"refresh: () => {page}()" in m.group(1), ctx

    def test_wave4_reload_ref_ctx_hooks_with_guard(self):
        # field/agent 两页 refresh=闭包经模块级引用转发（sparams/campaign
        # 同款模式）+ 未进页 null 守卫：field 走 load（切片滑条索引与 run/
        # dump 选择态保留）；agent 只重拉数据面板（对话浮窗气泡 append 非幂
        # 等，整页重跑会重复追加——浮窗与气泡历史不动）。
        fv = (_STATIC / "pages" / "view_fieldviz.js").read_text(encoding="utf-8")
        m = re.search(r"export const fieldCtx = \{(.*?)\n\};", fv, re.S)
        assert m, "fieldCtx 缺失"
        assert "const f = _fieldReload; if (f) f();" in m.group(1)
        assert "let _fieldReload = null;" in fv
        assert "_fieldReload = load;" in fv
        ag = (_STATIC / "pages" / "view_agent.js").read_text(encoding="utf-8")
        m = re.search(r"export const agentCtx = \{(.*?)\n\};", ag, re.S)
        assert m, "agentCtx 缺失"
        assert "const f = _agentReload; if (f) f();" in m.group(1)
        assert "let _agentReload = null;" in ag
        assert "_agentReload = async () => {" in ag

    def test_ctx_exports_importable_node_smoke(self):
        """node 真执行：PAGE_CTX 24 键齐（W4-S17 收口后仅 guide/import 未登记）、
        钩子函数形态（懒加载包装）。"""
        if _NODE is None:
            pytest.skip("本机无 node")
        js = (
            "const p = await import('./pages.js');\n"
            "const r = await import('./pages/router.js');\n"
            "const keys = Object.keys(r.PAGE_CTX).sort();\n"
            "const want = ['agent','anchors','calibration','campaign','dashboard','datasets',"
            "'detail','farfield','field','gallery','loopboard','optstack','playground',"
            "'profile','queue','recipe','reports','runs','solvers','sparams','timeline',"
            "'tools','tune','uq'];\n"
            "if (JSON.stringify(keys) !== JSON.stringify(want)) throw new Error('PAGE_CTX 键集漂移: ' + keys);\n"
            "for (const k of want) {\n"
            "  const c = r.PAGE_CTX[k];\n"
            "  if (typeof c.refresh !== 'function') throw new Error(k + '.refresh 缺失');\n"
            "  if (k !== 'dashboard' && typeof c.leave !== 'function') throw new Error(k + '.leave 缺失');\n"
            "}\n"
            "const all = ['dashboard','import','recipe','tune','loopboard','runs','detail','agent',"
            "'guide','solvers','calibration','sparams','timeline','reports','tools','playground',"
            "'farfield','field','optstack','datasets','anchors','uq','gallery','campaign','profile','queue'];\n"
            "const unreg = all.filter((k) => !r.pageContextFor(k));\n"
            "if (JSON.stringify(unreg) !== JSON.stringify(['import','guide']))\n"
            "  throw new Error('未登记页漂移: ' + unreg);\n"
            "console.log('ok:wave2');\n"
        )
        r = subprocess.run([_NODE, "--input-type=module", "-e", js],
                           capture_output=True, text=True, timeout=60,
                           cwd=str(_STATIC))
        assert r.returncode == 0, r.stderr[-2000:]
        assert "ok:wave2" in r.stdout
