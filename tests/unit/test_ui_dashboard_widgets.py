"""架构批 W4-C 席位回归钉：dashboard 组件深化（R1 §1.3 活动日志/新鲜度环/
甜甜圈）+ palette act-export-chart 事件桥。

对象：src/rfauto/ui/static/pages.js（本席独占文件面；app.js/palette.js 只读）。

三层：
1. **源码钉（免 node）**：
   - widget 注册表：activity（最近活动）/status_mix（pass/fail 分布）进
     WIDGETS + WIDGET_DEFAULTS + renderers 装配面；
   - 活动日志：数据源=本页已拉取的 /api/runs（_dashData.runs=W6-S2 S 收编
     降级名，零新增端点/零新增 fetch）、最近 10 条、openRun 单入口跳详情、
     esc/escAttr/badge 转义纪律、行键盘可达（Enter/Space）；
   - 新鲜度环：纯 SVG 串（token 三档 --ok/--warn/--muted2 + escAttr 属性
     语境 + title 悬浮），挂在 wKpi 首卡右上角，零定时器（重绘只挂 dashboard
     既有渲染时机）；
   - 甜甜圈：echarts pie ring 形态走 W2-B 缓存基建（echartsInitCached +
     bindChartResize）+ W3-B chartExportTools 导出面（refEl=null append，
     不扰动既有四挂接点跨席计数钉）；空态文案；
   - 事件桥：window 级 "rfauto:export-chart" 监听唯一一处；W4-S17（W3-S12
     建议①）桥登记面迁 plotCard 壳——plotcard.js registerRecentChartExport/
     fireRecentChartExport 共享注册表（WeakRef 弱可达语义随迁），
     chartExportTools（甜甜圈）与 plotCard 首绘/复用渲染同喂一表；监听装配
     在 initPages 且幂等守卫（typeof window 钉零顶层 DOM 依赖）；
   - 跨席计数钉复述（本席改动最易打破的面，先红=本席文件面被误改，先于
     52 分钟门暴露）。
2. **行为钉（node 在才跑，否则诚实 skip）**：relTime/freshnessTier/
   freshnessRingSvg/statusBucket 纯函数数值钉（含边界、未来时间戳钳零、
   非法输入、XSS 恶意 ts 零回声）+ node --check + import 冒烟。

不依赖 runs/、不读网络、不启动服务器。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")
# 架构批 UI-R2（2026-10-14）：pages.js 拆分为薄入口 + pages/ 域模块（零构建
# ESM）——源码钉读"入口+全部域模块"并集，行为断言逐字不变（拆分前=单文件）。
def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)

_SRC = _pages_union_text()



def _body(func_sig: str, close_indent: str = "") -> str:
    """取函数体（起于 function 声明行，止于首个指定缩进的收括号）。

    顶层函数 close_indent=""（列 0 收括号）；pageDashboard 内嵌套的 widget
    渲染器 close_indent="  "（2 空格缩进收括号）。
    """
    m = re.search(func_sig + r" \{(.*?)\n" + close_indent + r"\}", _SRC, re.S)
    assert m, f"函数体缺失: {func_sig}"
    return m.group(1)


def _w4c_block() -> str:
    """W4-C 模块块文本（组件深化头注释 → 块结束标记）。
    UI-R2：W4-C 块拆分跨 dashboard_util.js（纯函数四件）与 charts.js
    （导出事件桥+块结束标记）——两模块并读，钉语义（零自由定时器）不变。"""
    t = "".join((_STATIC / "pages" / n).read_text(encoding="utf-8")
                for n in ("dashboard_util.js", "charts.js"))
    m = re.search(r"架构批 W4-C：dashboard 组件深化(.*?)架构批 W4-C 块结束",
                  t, re.S)
    assert m, "W4-C 块缺失"
    return m.group(1)


# ────────────────────────── 1. 源码钉 ──────────────────────────

class TestWidgetRegistry:
    """活动日志/甜甜圈两 widget 进注册表+缺省面+渲染装配。"""

    def test_widgets_registered_and_defaulted(self):
        # W6-S21 i18n 扩面：注册表 title 字面迁 tk 词表键（渲染期 t() 烘焙）
        assert re.search(r"activity:\s*\{ tk: \"dashboard\.w_activity\"", _SRC)
        assert re.search(r"status_mix:\s*\{ tk: \"dashboard\.w_status_mix\"", _SRC)
        dm = re.search(r"const WIDGET_DEFAULTS = \[(.*?)\];", _SRC, re.S)
        assert dm, "WIDGET_DEFAULTS 缺失"
        defaults = dm.group(1)
        assert '"activity"' in defaults
        assert '"status_mix"' in defaults

    def test_renderers_wired(self):
        assert "activity: wActivity" in _SRC
        assert "status_mix: wStatusMix" in _SRC


class TestActivityFeed:
    """R1 §1.3 活动日志：最近活动卡片。"""

    def test_data_source_existing_runs_no_new_fetch(self):
        body = _body(r"async function wActivity\(el\)", "  ")
        assert "_dashData.runs.slice(0, 10)" in body  # 最近 10 条
        # （W6-S2 S 状态收编：原 S.dashData 单模块私有键降级模块级 _dashData，
        # 行为等价搬家——钉面同笔，语义不变=复用进页已拉取数据。）
        assert "T.api(" not in body  # 零新增 fetch（复用本页已拉取数据）
        # W8-S32 i18n 批 3：空态文案单源迁词表 t() 烘焙（zh 值同笔迁 i18n.js）
        assert 't("dashboard.activity_empty")' in body

    def test_rows_click_openrun_and_keyboard(self):
        body = _body(r"async function wActivity\(el\)", "  ")
        assert "openRun(row.dataset.id)" in body  # 复用 run 详情单入口
        # UI-R4（架构批，A6 P1-5 清偿）：本组件=R1 P1-2 手写试点原位点，
        # 键盘可达三件套收编 kitClickRow 单源（role=link→button 缺省口径，
        # Enter/Space 接线在 kit bindClickRows；行为钉 test_ui_a11y_rows）
        # S4 发布令批：行标签迁词表 t() 烘焙（zh 值同笔 runs.open_detail_aria）
        assert 'kitClickRowAttrs({ label: t("runs.open_detail_aria") + (r.run_id || "") })' in body
        assert 'bindClickRows(el, (row) => openRun(row.dataset.id), "[data-id]");' in body

    def test_escape_and_badge_discipline(self):
        body = _body(r"async function wActivity\(el\)", "  ")
        assert "escAttr(r.run_id)" in body  # 属性语境
        assert "esc(r.run_id || \"\")" in body  # 文本语境
        assert "esc(relTime(r.timestamp, now))" in body  # 相对时间文本语境
        assert "T.badge(label, cls)" in body  # 状态徽章（badge 内部 esc）
        assert "statusBucket(r.status)" in body  # 分桶单源


class TestFreshnessRing:
    """R1 §1.3 数据新鲜度环：KPI 卡角落 SVG 三档圆环。"""

    def test_svg_builder_exported_pure(self):
        assert "export function freshnessRingSvg(ts, now)" in _SRC
        assert "export function freshnessTier(ts, now)" in _SRC

    def test_three_tiers_on_tokens(self):
        body = _body(r"export function freshnessRingSvg\(ts, now\)")
        assert 'tier === "ok" ? "var(--ok)"' in body
        assert 'tier === "warn" ? "var(--warn)"' in body
        assert '"var(--muted2)"' in body
        assert "stroke-dasharray" in body  # SVG 圆环进度弧

    def test_hover_title_escapes(self):
        body = _body(r"export function freshnessRingSvg\(ts, now\)")
        assert 'aria-label="${escAttr(label)}" title="${escAttr(label)}"' in body
        assert "<title>${esc(label)}</title>" in body  # SVG 原生 tooltip 兜底
        assert "relTime(ts, now)" in body  # 悬浮显示具体时间

    def test_mounted_in_kpi_first_card_corner(self):
        body = _body(r"async function wKpi\(el\)", "  ")
        assert "freshnessRingSvg(list.length ? list[0].timestamp : null, Date.now())" in body
        assert "position:absolute;top:8px;right:10px" in body  # 卡角落

    def test_zero_free_timers_in_w4c(self):
        # 禁新增自由定时器：W4-C 全块零 setInterval/setTimeout/requestAnimationFrame
        block = _w4c_block()
        for t in ("setInterval(", "setTimeout(", "requestAnimationFrame("):
            assert t not in block, t


class TestDonut:
    """R1 §1.3 SVG 甜甜圈：pass/fail 分布环形图。"""

    def test_pie_ring_via_cached_infra(self):
        body = _body(r"async function wStatusMix\(el\)", "  ")
        assert "echartsInitCached(holder)" in body  # W2-B 实例缓存守卫
        assert 'type: "pie"' in body
        assert 'radius: ["52%", "78%"]' in body  # 环形（donut）形态
        assert "bindChartResize(holder)" in body  # W2-B resize 去重
        assert "}, true);" in body  # notMerge：复用路径整体替换

    def test_export_tools_with_null_refel(self):
        # refEl=null=append（不插图表前）——保持既有四管线挂接点的跨席计数钉
        # 字面（chartExportTools(el.parentElement, el, { 恒 4）不被扰动
        body = _body(r"async function wStatusMix\(el\)", "  ")
        assert "chartExportTools(el.parentElement, null, {" in body
        assert 'name: "dashboard-status-mix"' in body
        assert "getCsvSeries:" in body

    def test_palette_theme_tiers_mirror_chart_colors(self):
        # A5-B（R6 R-4）：CHART_COLORS 单源迁 theme.js 后，wStatusMix 的
        # light/dark 双档字面量镜像收编为 chartPalette 对应位取值——
        # PASS=绿档[2] / FAIL=红档[3] / 其他=紫档[4]（#276b2c/#c62828/
        # #6a1b9a 与 #81c784/#e57373/#ba68c8 的取值正确性由
        # test_ui_nav_focus/test_ui_a11y_theme 对 --plot-bg 的对比度钉守值）
        body = _body(r"async function wStatusMix\(el\)", "  ")
        assert "chartPalette(light)" in body
        assert "pass: _pal[2]" in body and "fail: _pal[3]" in body and "other: _pal[4]" in body

    def test_status_bucket_single_source_and_empty_state(self):
        assert "export function statusBucket(status)" in _SRC
        body = _body(r"async function wStatusMix\(el\)", "  ")
        assert "statusBucket(r.status)" in body  # 分桶单源（与活动徽章共用）
        # W8-S32 i18n 批 3：空态文案单源迁词表 t() 烘焙（zh 值同笔迁 i18n.js）
        assert 't("dashboard.mix_empty")' in body


class TestExportChartEventBridge:
    """palette act-export-chart 事件桥（契约：event=rfauto:export-chart，无 payload）。"""

    # UI-R11（uir8 P2-5）桥行为胶水：createElement 桩跑 chartExportTools +
    # _bindExportChartEvent 全链（免 jsdom；png.click 覆写为计数器——
    # 只测"桥→最近装配钮"接线与离场解除，不测导出本体）。
    _GLUE = r"""
const listeners = {};
globalThis.window = { addEventListener: (t, f) => { listeners[t] = f; } };
const mkEl = (tag) => ({ tag, className: "", title: "", _txt: "",
  dataset: {}, children: [],
  get textContent() { return this._txt; },
  set textContent(v) { this._txt = v; },
  setAttribute() {},
  appendChild(c) { this.children.push(c); },
  onclick: null,
  click() { if (this.onclick) this.onclick(); } });
let contains = true;
globalThis.document = { contains: () => contains, createElement: (t) => mkEl(t) };
const charts = await import('./pages/charts.js');
charts._bindExportChartEvent();
const host = { insertBefore: (n) => { host.tool = n; } };
charts.chartExportTools(host, null, { name: "t",
  getChart: () => ({ isDisposed: () => true }), getCsvSeries: () => [] });
const png = host.tool.children.find((b) => b.dataset.exportKind === "png");
let clicked = 0;
png.click = () => { clicked += 1; };
listeners["rfauto:export-chart"](); // 桥派发 → 最近装配 PNG 钮
const afterLive = clicked;
contains = false; // 工具条随页换血离场
listeners["rfauto:export-chart"](); // 离场：不 click + 解除登记
listeners["rfauto:export-chart"](); // 登记已清：零动作零抛
console.log(JSON.stringify({ afterLive, afterDetach: clicked }));
"""

    def test_listener_single_and_contract_name(self):
        assert _SRC.count('window.addEventListener("rfauto:export-chart"') == 1

    def test_factory_registers_last_assembly(self):
        body = _body(r"function chartExportTools\(host, refEl, opts\)")
        assert "const pngBtn = mk(\"PNG\"" in body  # PNG 钮捕获
        # W4-S17（W3-S12 建议①登记面收窄）：自有 WeakRef 闭包退役，PNG 钮
        # 装配后委托 plotcard.js 共享登记面（WeakRef 弱可达语义随迁，
        # 触发面/离场解除钉迁 test_plotcard_registry_face）
        assert "registerRecentChartExport(pngBtn);" in body
        assert "new WeakRef" not in body  # 旧自有登记闭包零残留
        assert "_lastChartExport" not in _SRC  # 旧登记名全仓退役

    def test_plotcard_registry_face(self):
        # W4-S17：登记面单源在 plotcard.js——首绘装配与复用换代两路径都
        # 登记（桥目标=最近渲染的 plotCard 壳），触发/解除闭包同模块。
        pc = (_STATIC / "plotcard.js").read_text(encoding="utf-8")
        assert "export function registerRecentChartExport(btn)" in pc
        assert "export function fireRecentChartExport()" in pc
        assert "new WeakRef(btn)" in pc  # 弱可达登记（UI-R11 uir8 P2-5 语义随迁）
        assert "document.contains(b)" in pc  # 离场探针 → else 分支清登记
        m = re.search(r"export function plotCard\(el, props = \{\}, ctx = \{\}\) \{(.*?)\n\}",
                      pc, re.S)
        assert m, "plotCard 函数体缺失"
        body = m.group(1)
        assert 'button[data-export-kind="png"]' in body  # 壳工具条 PNG 钮定位
        assert body.count("registerRecentChartExport(") == 2  # 首绘+复用两路径

    def test_binding_guarded_and_idempotent_in_initpages(self):
        body = _body(r"function _bindExportChartEvent\(\)")
        assert "typeof window === \"undefined\"" in body  # node import 零 DOM 依赖
        assert "_exportEvtBound" in body  # 幂等守卫（装配一次）
        assert "fireRecentChartExport();" in body  # W4-S17：消费共享登记面
        # 监听在 initPages 装配（与 W2-B 轮询监听同一浏览器侧装配点）
        assert "_bindExportChartEvent(); // 架构批 W4-C" in _SRC

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_bridge_weakref_deregisters_on_toolbar_detach(self):
        # UI-R11（uir8 P2-5）行为钉：桥派发→最近装配的 PNG 钮 click 一次；
        # 工具条随页换血离场（document.contains=false）后派发不再 click 且
        # 登记解除（旧强引用形态会对离场钮继续 click：afterDetach=2）。
        # W4-S17：链路改为 chartExportTools→plotcard.js 共享登记面→
        # fireRecentChartExport 触发，外部行为与本钉逐字节同。
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e", self._GLUE],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, cwd=str(_STATIC))
        assert r.returncode == 0, r.stderr[-2000:]
        payload = json.loads(r.stdout.strip().splitlines()[-1])
        assert payload == {"afterLive": 1, "afterDetach": 1}, (
            "离场后必须停点且解除登记（旧强引用形态 afterDetach=2）")

    _REGISTRY = r"""
const p = await import('./plotcard.js');
let clicked = 0;
const btn = { dataset: {}, click() { clicked += 1; } };
// 未登记：fire 零动作零抛
p.fireRecentChartExport();
// WeakRef 缺席环境（桩掉 WeakRef）：登记降级 null，fire 零动作
const RealWR = globalThis.WeakRef;
globalThis.WeakRef = undefined;
p.registerRecentChartExport(btn);
p.fireRecentChartExport();
globalThis.WeakRef = RealWR;
// 正常登记：document.contains=true → 代点一次
let contains = true;
globalThis.document = { contains: () => contains };
p.registerRecentChartExport(btn);
p.fireRecentChartExport();
const afterLive = clicked;
// 离场：不 click + 解除登记；再 fire=已清零动作
contains = false;
p.fireRecentChartExport();
const afterDetach = clicked;
p.fireRecentChartExport();
const afterCleared = clicked;
delete globalThis.document;
console.log(JSON.stringify({ afterLive, afterDetach, afterCleared }));
"""

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_plotcard_registry_fire_and_weakref_deref(self):
        # W4-S17 行为钉（plotcard.js 共享登记面）：fire=解引用代点在场钮一次；
        # 离场→停点+解除登记；WeakRef 缺席→登记降级零动作（#105 best-effort）。
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e", self._REGISTRY],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, cwd=str(_STATIC))
        assert r.returncode == 0, r.stderr[-2000:]
        payload = json.loads(r.stdout.strip().splitlines()[-1])
        assert payload == {"afterLive": 1, "afterDetach": 1, "afterCleared": 1}


class TestCrossSeatPinsHold:
    """跨席计数钉复述（本席改动最易打破的面；先红=pages.js 生命周期/导出
    不变量被误改，先于 52 分钟门暴露；与 test_ui_lifecycle/test_ui_tables_sort
    同源复述）。"""

    def test_counts_untouched(self):
        assert _SRC.count("T.plotCard(") == 16  # 12 + W3-S12 四管线逃生舱迁移
        assert _SRC.count("window.echarts.init(") == 1  # 唯一入口=echartsInitCached
        assert _SRC.count('window.addEventListener("resize"') == 1
        assert _SRC.count("setInterval(") == 2  # 仅轮询托管器两处
        # W3-S12：四管线（polar/Smith/场切片/远场3D）已迁 plotCard 逃生舱，
        # el 形态挂接清零；本席 null 形态（甜甜圈 refEl=null append）保留
        assert _SRC.count("chartExportTools(el.parentElement, el, {") == 0
        assert _SRC.count("chartExportTools(el.parentElement, null, {") == 1
        assert _SRC.count("bindChartResize(el); // P0-5") == 0  # 四管线随壳内建去重
        assert _SRC.count("disposeChartsIn(") == 4

    def test_pure_helpers_exported(self):
        for fn in ("relTime", "freshnessTier", "freshnessRingSvg", "statusBucket"):
            assert f"export function {fn}(" in _SRC, fn


# ────────── R-1 dashboard 局部刷新试点（架构批 W1-S3 席位钉） ──────────

def _view_src(name: str) -> str:
    """单视图模块源码（R-1 席位钉：文件面收敛读，并集钉归并集口径）。"""
    return (_STATIC / "pages" / name).read_text(encoding="utf-8")


class TestLocalRefreshPilot:
    """R-1（架构批 W1-S3，R6 审计 R-1）：widget 增删/拖拽局部刷新。

    此前增删/拖拽任一变更递归整页渲染函数=全量 refetch /api/runs?limit=200
    + /api/solvers（R6 审计旧单体 pages.js:696/724/746 三处）；现收敛到
    refreshDashboard → renderDashboardGrid（数据面零 fetch）。"""

    def test_view_file_split_and_wiring(self):
        dash = _view_src("view_dashboard.js")
        assert "export async function refreshDashboard()" in dash
        assert "async function renderDashboardGrid()" in dash
        assert "export const dashboardCtx = { refresh: () => refreshDashboard() };" in dash

    def test_mutations_use_local_refresh_not_full_reentry(self):
        dash = _view_src("view_dashboard.js")
        # 三处变更点（添加菜单 chip/组件 close/拖拽 drop）全走局部刷新——
        # W5-S23（同笔改针）：chip/close 改经 refreshGridKeepingFocus
        # （内部 await refreshDashboard() 完成后还焦=焦点保持批次），
        # drop 保持直呼；字面消费面=直呼 1 + 包装器内 1 = 2。
        assert dash.count("refreshDashboard();") == 2
        assert dash.count("refreshGridKeepingFocus(") == 3  # 定义 1 + chip/close 消费 2
        assert "persistWidgets(); pageDashboard();" not in dash  # 全量重拉递归退场
        # 旧全量路径调用点仅剩 refreshDashboard 的无壳回退一处（另一处=定义行）
        assert dash.count("return pageDashboard();") == 1

    def test_refresh_path_is_fetch_free(self):
        body = _body(r"export async function refreshDashboard\(\)")
        assert "apiFetch" not in body and "T.api(" not in body  # 数据面零 fetch
        assert "_dashData" in body  # 复用进页已拉取数据（W6-S2 S 收编降级名）
        assert "renderDashboardGrid()" in body
        assert "return pageDashboard();" in body  # 壳未就绪回退全量路径

    def test_enter_path_keeps_full_fetch(self):
        body = _body(r"async function pageDashboard\(\)")
        assert "/api/runs?limit=200" in body and "/api/solvers" in body  # 进页全量拉取不变
        assert "renderDashboardGrid()" in body  # 渲染面收敛单源


# ────────────────────────── 2. 行为钉（node 在才跑） ──────────────────────────

_NODE_GLUE = r"""
const p = await import('./pages.js');
const A = (cond, msg) => { if (!cond) throw new Error("assert: " + msg); };
const NOW = Date.parse("2026-10-11T12:00:00Z");
const iso = (ms) => new Date(ms).toISOString();

// ── relTime：相对时间阶梯 ──
A(p.relTime(null, NOW) === "-", "relTime null -> dash");
A(p.relTime("not-a-date", NOW) === "-", "relTime invalid -> dash");
A(p.relTime(undefined, NOW) === "-", "relTime undefined -> dash");
A(p.relTime(iso(NOW - 30e3), NOW) === "刚刚", "relTime <60s");
A(p.relTime(iso(NOW - 5 * 60e3), NOW) === "5 分钟前", "relTime 5min");
A(p.relTime(iso(NOW - 3 * 3600e3), NOW) === "3 小时前", "relTime 3h");
A(p.relTime(iso(NOW - 2 * 86400e3), NOW) === "2 天前", "relTime 2d");
A(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(p.relTime(iso(NOW - 40 * 86400e3), NOW)),
  "relTime >30d falls back to absolute short date");
A(p.relTime(iso(NOW + 3600e3), NOW) === "刚刚", "relTime future clamped (no negative)");

// ── freshnessTier：三档边界 ──
A(p.freshnessTier(null, NOW).tier === "none", "tier none on missing");
A(p.freshnessTier("garbage", NOW).tier === "none", "tier none on invalid");
A(p.freshnessTier(iso(NOW - 0.5 * 3600e3), NOW).tier === "ok", "tier ok <1h");
A(p.freshnessTier(iso(NOW - 0.5 * 3600e3), NOW).hours < 1, "hours numeric");
A(p.freshnessTier(iso(NOW - 5 * 3600e3), NOW).tier === "warn", "tier warn <24h");
A(p.freshnessTier(iso(NOW - 48 * 3600e3), NOW).tier === "stale", "tier stale >=24h");
A(p.freshnessTier(iso(NOW + 86400e3), NOW).tier === "ok", "future ts clamped to 0 -> ok");

// ── freshnessRingSvg：SVG 串三档 + a11y + XSS 零回声 ──
const svgOk = p.freshnessRingSvg(iso(NOW - 0.5 * 3600e3), NOW);
A(svgOk.includes("var(--ok)"), "ring ok token");
A(svgOk.includes("stroke-dasharray="), "ring dasharray progress arc");
A(svgOk.includes('role="img"'), "ring role img");
A(svgOk.includes("title=") && svgOk.includes("<title>"), "ring title attr + svg title child");
A(svgOk.includes("1 小时内"), "ring hover label tier text");
A(svgOk.startsWith("<svg"), "ring is pure svg string");
const svgWarn = p.freshnessRingSvg(iso(NOW - 5 * 3600e3), NOW);
A(svgWarn.includes("var(--warn)") && svgWarn.includes("24 小时内"), "ring warn tier");
A(svgWarn !== svgOk, "ring output differs by tier");
const svgStale = p.freshnessRingSvg(iso(NOW - 48 * 3600e3), NOW);
A(svgStale.includes("var(--muted2)") && svgStale.includes("超过 24 小时"), "ring stale tier");
const svgNone = p.freshnessRingSvg(null, NOW);
A(svgNone.includes("暂无 run") && svgNone.includes("var(--muted2)"), "ring none gray empty");
A(!p.freshnessRingSvg('"><script>', NOW).includes("<script"), "ring never echoes raw ts (XSS)");

// ── statusBucket：分桶单源 ──
A(p.statusBucket("done") === "pass", "bucket done -> pass");
A(p.statusBucket("DONE") === "pass", "bucket case-insensitive");
A(p.statusBucket("solve_failed") === "fail", "bucket solve_failed -> fail");
A(p.statusBucket("failed") === "fail", "bucket failed -> fail");
A(p.statusBucket("running") === "other", "bucket running -> other");
A(p.statusBucket(undefined) === "other", "bucket missing -> other");
A(p.statusBucket("") === "other", "bucket empty -> other");

console.log("ok:widgets");
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestNodeBehavioral:
    def test_widget_helpers_end_to_end(self):
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e", _NODE_GLUE],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC))
        assert r.returncode == 0, r.stderr[-2000:]
        assert "ok:widgets" in r.stdout

    def test_node_check_pages_js(self):
        r = subprocess.run([_NODE, "--check", str(_STATIC / "pages.js")],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]
