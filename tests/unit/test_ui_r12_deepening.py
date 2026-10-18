"""aurora_d UI-R12 席位回归钉：前端深化三件（懒加载路由 / 统一 API 层 / CSS 变量审计）。

对象：src/rfauto/ui/static/{pages.js, app.js, pages/api.js, theme.js}、
pages/ 五个迁移视图（dashboard/runs/detail/calibration/data）与审计收编面
（view_fieldviz/view_calibration/filebrowser + index.html :root 令牌）。
index.html 内联脚本零改动（CSP 哈希钉 test_w1e_ui_csp 不受扰，本文件只读）；
既有钉面（test_ui_routing / test_ui_nav_focus / test_x2_pr68_ui /
test_ui_data_anchor_uq_pages 等）全部保持绿——注册表字节经绑定名别名保形。

三族：
1. **懒加载路由（任务1）**：pages.js 静态视图 import 收敛到 2 件
   （view_tools=router opener 静态依赖 + view_dashboard=首屏落地页），
   其余 24 个视图别名经原生 ESM 动态 import() 按需加载（26 视图键 - 2
   豁免；farfield/field 与 datasets/anchors/uq 共享模块，import 缓存命中）
   ——零构建形态；节点行为钉=从 pages.js 源提取懒加载清单逐项验导出存在
   + VIEWS.guide 桩渲染金丝雀 + 补焦桥挂起/消费闭环。
2. **统一 API 层（任务2）**：pages/api.js 单源（apiFetch 信封与 app.js
   api 同形 / setApiToken 透传 / viewSignal+abortViewSignals 视图作用域
   取消 / timeoutMs 超时）——node 桩 fetch 全链行为钉；app.js api 保形
   消费 apiRequestInit（test_ui_nav_focus 钉住的本体 needles 不动）；
   五迁移视图零 T.api 残留 + aborted 短路守卫在位；全仓 T.api 计数棘轮
   （58，只收不放）。
3. **CSS 变量审计（任务3）**：theme.js 冻结现值单源（fieldAxisLine/
   calibNullCost 同值双档 + ISO_BAND 色带）+ filebrowser 遮罩走 ：root
   令牌 --backdrop-dim + 令牌同值替换（font-size/border-radius/margin/
   padding/gap 五属性共 66 处，computed value 逐字节不变）——pages/*.js
   引号包裹 hex 字面量归零棘轮 + 无令牌同值的残余 px 清单冻结（只收不放）。

不依赖 runs/、不读网络、不启动服务器；缺 node 诚实 skip。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

_APP = (_STATIC / "app.js").read_text(encoding="utf-8")
_PAGES = (_STATIC / "pages.js").read_text(encoding="utf-8")
_API = (_STATIC / "pages" / "api.js").read_text(encoding="utf-8")
_THEME = (_STATIC / "theme.js").read_text(encoding="utf-8")
_INDEX = (_STATIC / "index.html").read_text(encoding="utf-8")


def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)


_UNION = _pages_union_text()


def _view_src(name: str) -> str:
    return (_STATIC / "pages" / name).read_text(encoding="utf-8")


def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return r.stdout


# ══════════════════ 1. 任务1：懒加载路由 ══════════════════

# 懒加载清单（pages.js 源提取）：(绑定名, VIEWS 键, 模块文件, 导出名)
_LAZY_RE = re.compile(
    r'const (\w+) = _lazyView\("([^"]+)", "([^"]+)", "([^"]+)"\);')
_LAZY = _LAZY_RE.findall(_PAGES)


class TestLazyRoutingSource:
    def test_static_view_imports_collapsed_to_two(self):
        # 全量静态 import（拆分前 21 行 view_*）收敛到 2 件豁免
        statics = re.findall(r'^import .* from "(\./pages/view_[^"]+)";$',
                             _PAGES, re.M)
        assert sorted(statics) == ["./pages/view_dashboard.js",
                                   "./pages/view_tools.js"], statics

    def test_dynamic_import_native_zero_build(self):
        # 原生 ESM 动态 import（相对说明符，浏览器直跑零构建）+ 模块缓存复用
        assert 'await import("./pages/" + file)' in _PAGES

    def test_lazy_manifest_shape(self):
        # 24 个懒加载别名（26 视图键 - tools/dashboard 两静态豁免；
        # farfield/field、datasets/anchors/uq 共享模块文件）
        assert len(_LAZY) == 24, f"懒加载别名数漂移: {len(_LAZY)}"
        # 绑定名=导出名=VIEWS 键历史口径（注册序钉保形的前提）
        for binding, _key, fname, export in _LAZY:
            assert binding == export, (binding, export)
            assert fname.startswith("view_") and fname.endswith(".js")
        # 豁免两件不在清单（tools 走静态 pageTools；dashboard 走静态导入）
        keys = {k for _b, k, _f, _e in _LAZY}
        assert "tools" not in keys and "dashboard" not in keys

    def test_views_registry_table_byteform_unchanged(self):
        # 注册表 needle（他席钉面逐字复述：x2/data 三页注册序钉的前提）
        for needle in ("dashboard: pageDashboard, import: pageImport, recipe: pageRecipe",
                       "detail: showRun", "tools: pageTools",
                       "datasets: pageDatasets, anchors: pageAnchors, uq: pageUq",
                       "campaign: pageCampaign", "queue: pageQueue"):
            assert needle in _PAGES, needle

    def test_lazy_failure_visible_not_silent(self):
        # 加载失败可见化（#105）：单页错误面板 + 全局 toast，不抛未处理 rejection
        assert "页面模块加载失败" in _PAGES
        assert 'document.getElementById("view-" + key)' in _PAGES
        assert "T.msg" in _PAGES

    def test_app_focus_bridge_wired(self):
        # 补焦桥：activate 挂起（h2 未落 DOM）→ 注入工具集 → 包装器消费
        assert "if (!h) { _lazyFocus.pending = v; return; }" in _APP
        assert "_lazyFocus, pageFocusAfterRender," in _APP
        assert "function pageFocusAfterRender(v)" in _APP
        assert "T._lazyFocus && T._lazyFocus.pending === key" in _PAGES
        assert "T.pageFocusAfterRender(key)" in _PAGES


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestLazyRoutingBehavioral:
    def test_every_lazy_module_exports_binding(self):
        # 清单逐项：模块真 import 且导出名在位（node 相对说明符=浏览器同语义）
        lines = ["const A = (c, m) => { if (!c) throw new Error('assert: ' + m); };"]
        for _binding, _key, fname, export in _LAZY:
            lines.append(
                f'const m_{export} = await import("./pages/{fname}");'
                f"A(typeof m_{export}.{export} === 'function', '{fname}:{export}');")
        lines.append(f"console.log('ok:lazy-manifest:{len(_LAZY)}');")
        out = _run_node_js("\n".join(lines))
        assert f"ok:lazy-manifest:{len(_LAZY)}" in out

    def test_views_keyset_complete(self):
        keys = ["dashboard", "import", "recipe", "tune", "loopboard", "runs",
                "detail", "agent", "guide", "solvers", "calibration", "sparams",
                "timeline", "reports", "tools", "playground", "farfield",
                "field", "optstack", "datasets", "anchors", "uq", "gallery",
                "campaign", "profile", "queue"]
        # pages.js 侧写 populates VIEWS（router.js 单源注册表，入口组装）
        out = _run_node_js(
            "await import('./pages.js');\n"
            "const r = await import('./pages/router.js');\n"
            f"const want = {keys!r};\n"
            "const got = Object.keys(r.VIEWS).sort();\n"
            "const exp = want.slice().sort();\n"
            "if (JSON.stringify(got) !== JSON.stringify(exp))\n"
            "  throw new Error('VIEWS 键集漂移: ' + got.join(','));\n"
            "for (const k of want)\n"
            "  if (typeof r.VIEWS[k] !== 'function') throw new Error('非函数: ' + k);\n"
            "console.log('ok:views-keyset:' + got.length);\n")
        assert "ok:views-keyset:26" in out

    def test_lazy_canary_renders_and_focus_bridge_consumed(self):
        # 金丝雀：VIEWS.guide（懒加载包装器）动态拉模块真渲染 + 补焦桥闭环
        out = _run_node_js(
            "const ctx = await import('./pages/context.js');\n"
            "const captured = [];\n"
            "ctx.T.$ = (id) => { const el = { id, innerHTML: '' };\n"
            "  captured.push(el); return el; };\n"
            "await import('./pages.js'); // 侧写：组装 VIEWS\n"
            "const r = await import('./pages/router.js');\n"
            "await r.VIEWS.guide();\n"
            "if (!captured[0].innerHTML.includes('使用指南'))\n"
            "  throw new Error('guide 未渲染');\n"
            "ctx.T._lazyFocus = { pending: 'guide' };\n"
            "let focused = null;\n"
            "ctx.T.pageFocusAfterRender = (k) => { focused = k; return true; };\n"
            "await r.VIEWS.guide();\n"
            "if (focused !== 'guide' || ctx.T._lazyFocus.pending !== null)\n"
            "  throw new Error('补焦桥未消费');\n"
            "console.log('ok:lazy-canary');\n")
        assert "ok:lazy-canary" in out

    def test_pages_js_still_imports_clean_in_node(self):
        # 懒加载化后 pages.js 真 ESM import 保持零 DOM 依赖（动态说明符
        # 不在顶层解析——静态时代全部视图随 import 链加载，现在只有豁免两件）
        out = _run_node_js(
            "await import('./pages.js');\nconsole.log('esm-ok');\n")
        assert "esm-ok" in out


# ══════════════════ 2. 任务2：统一 API 层 ══════════════════

_MIGRATED = {
    "view_dashboard.js": "dashboard",
    "view_runs.js": "runs",
    "view_detail.js": "detail",
    "view_calibration.js": "calibration",
    "view_data.js": None,  # 三页各族键（datasets/anchors/uq）——单独钉
}


class TestUnifiedApiSource:
    def test_api_module_single_source_surface(self):
        for needle in (
            "export function setApiToken(",
            "export function setApiNotifier(",
            "export function composeSignals(",
            "export function apiRequestInit(",
            "export async function apiFetch(",
            "export function viewSignal(",
            "export function abortViewSignals(",
            '"请求失败（网络或服务器异常）"',  # 与 app.js api 兜底同文案
        ):
            assert needle in _API, needle

    def test_app_api_delegates_shape_kept(self):
        # app.js api 本体 needles（test_ui_nav_focus 逐字钉）不动 + 委托行在位
        m = re.search(r"export const api = async \(url, opts\) => \{(.*?)\n\};",
                      _APP, re.S)
        assert m, "api() 实体丢失"
        body = m.group(1)
        assert "await fetch(url, apiRequestInit(opts))" in body
        assert "return await r.json();" in body
        assert "ok: false, error: m, errors: [m]" in body
        assert "msg(m, false)" in body

    def test_activate_aborts_view_signals_and_notifier_wired(self):
        assert "abortViewSignals(); // UI-R12" in _APP
        assert "setApiNotifier(msg); // UI-R12" in _APP
        assert 'import { apiRequestInit, abortViewSignals, setApiNotifier } from "./pages/api.js";' in _APP

    def test_migrated_views_use_unified_layer(self):
        for fname, key in _MIGRATED.items():
            src = _view_src(fname)
            assert 'import { apiFetch, viewSignal } from "./api.js";' in src, fname
            assert "T.api(" not in src, f"{fname} 残留 T.api"
            assert "aborted) return; // UI-R12" in src, fname
            if key:
                assert f'viewSignal("{key}")' in src, fname

    def test_view_data_three_view_scoped_signals(self):
        src = _view_src("view_data.js")
        for key in ("datasets", "anchors", "uq"):
            assert f'viewSignal("{key}")' in src, key

    def test_t_api_remaining_ratchet(self):
        # 渐进迁移棘轮：存量 T.api 计数只收不放（UI-R12 迁 5 视图后=58）
        n = len(re.findall(r"\bT\.api\(", _UNION))
        assert n == 58, f"T.api 存量漂移（迁移面变动须同笔更新本钉）: {n}"

    def test_non_migrated_paths_untouched(self):
        # palette 自带 fetch（nav_focus 钉）/ tools 串行 await T.api（tools_page 钉）不动
        assert "await T.api" in _view_src("view_tools.js")
        assert ".catch(" in (_STATIC / "palette.js").read_text(encoding="utf-8")


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestUnifiedApiBehavioral:
    _BOOT = (
        "const A = (c, m) => { if (!c) throw new Error('assert: ' + m); };\n"
        "const api = await import('./pages/api.js');\n"
        "let lastInit = null, lastUrl = null;\n"
        "const responses = [];\n"
        "globalThis.fetch = async (url, init) => {\n"
        "  lastUrl = url; lastInit = init;\n"
        "  const r = responses.length ? responses.shift() : { json: async () => ({ ok: true }) };\n"
        "  return r;\n"
        "};\n")

    def test_ok_path_and_passthrough(self):
        out = _run_node_js(self._BOOT +
            "const d = await api.apiFetch('/api/x');\n"
            "A(d.ok === true, 'ok path');\n"
            "A(lastInit === undefined, '无 opts 无 token → init 原样缺席');\n"
            "await api.apiFetch('/api/y', { method: 'POST' });\n"
            "A(lastInit.method === 'POST', 'opts 透传');\n"
            "console.log('ok:api-ok-path');\n")
        assert "ok:api-ok-path" in out

    def test_failure_envelope_and_notifier(self):
        out = _run_node_js(self._BOOT +
            "responses.push({ json: async () => { throw new Error('bad json'); } });\n"
            "const seen = [];\n"
            "api.setApiNotifier((t, ok) => seen.push([t, ok]));\n"
            "const d = await api.apiFetch('/api/x');\n"
            "A(d.ok === false && d.error === '请求失败（网络或服务器异常）', '信封');\n"
            "A(Array.isArray(d.errors) && d.errors.length === 1, 'errors 数组');\n"
            "A(d.aborted === undefined, '非取消形态不带 aborted');\n"
            "A(seen.length === 1 && seen[0][1] === false, 'notifier 呈现');\n"
            "console.log('ok:api-failure');\n")
        assert "ok:api-failure" in out

    def test_abort_signal_silent_envelope(self):
        out = _run_node_js(self._BOOT +
            "globalThis.fetch = async (url, init) => {\n"
            "  return new Promise((resolve, reject) => {\n"
            "    init.signal.addEventListener('abort', () =>\n"
            "      reject(Object.assign(new Error('a'), { name: 'AbortError' })));\n"
            "  });\n"
            "};\n"
            "const seen = [];\n"
            "api.setApiNotifier((t) => seen.push(t));\n"
            "const ac = new AbortController();\n"
            "const p = api.apiFetch('/api/x', { signal: ac.signal });\n"
            "ac.abort();\n"
            "const d = await p;\n"
            "A(d.ok === false && d.aborted === true, 'aborted 信封');\n"
            "A(seen.length === 0, '取消不 toast');\n"
            "console.log('ok:api-abort');\n")
        assert "ok:api-abort" in out

    def test_timeout_ms_aborts(self):
        out = _run_node_js(self._BOOT +
            "globalThis.fetch = async (url, init) => {\n"
            "  return new Promise((resolve, reject) => {\n"
            "    init.signal.addEventListener('abort', () =>\n"
            "      reject(Object.assign(new Error('t'), { name: 'AbortError' })));\n"
            "  });\n"
            "};\n"
            "const d = await api.apiFetch('/api/x', { timeoutMs: 30 });\n"
            "A(d.aborted === true, '超时入 aborted 形态');\n"
            "console.log('ok:api-timeout');\n")
        assert "ok:api-timeout" in out

    def test_token_header_passthrough_and_reset(self):
        out = _run_node_js(self._BOOT +
            "api.setApiToken('tok-1');\n"
            "await api.apiFetch('/api/x');\n"
            "A(lastInit.headers.Authorization === 'Bearer tok-1', 'token 透传');\n"
            "await api.apiFetch('/api/x', { headers: { 'Content-Type': 'application/json' } });\n"
            "A(lastInit.headers.Authorization === 'Bearer tok-1', '既有头保留');\n"
            "A(lastInit.headers['Content-Type'] === 'application/json', '业务头不动');\n"
            "api.setApiToken(null);\n"
            "await api.apiFetch('/api/x');\n"
            "A(lastInit === undefined || lastInit.headers.Authorization === undefined,\n"
            "  '复位零头（快路径 init 缺席）');\n"
            "A(api.apiTokenSet() === false, '复位查询面');\n"
            "console.log('ok:api-token');\n")
        assert "ok:api-token" in out

    def test_view_signal_lifecycle(self):
        out = _run_node_js(self._BOOT +
            "const s1 = api.viewSignal('runs');\n"
            "A(s1.aborted === false, '初始未取消');\n"
            "api.abortViewSignals();\n"
            "A(s1.aborted === true, '切页收束');\n"
            "const s2 = api.viewSignal('runs');\n"
            "A(s2.aborted === false && s2 !== s1, '重进惰性换新 controller');\n"
            "A(api.viewSignal('runs') === s2, '同页复用同一 signal');\n"
            "console.log('ok:api-view-signal');\n")
        assert "ok:api-view-signal" in out


# ══════════════════ 3. 任务3：CSS 变量审计 ══════════════════

_HEX_QUOTED = re.compile(r'["\']#[0-9a-fA-F]{3,8}["\']')


class TestCssAuditSource:
    def test_theme_freeze_pairs_single_source(self):
        # 冻结现值单源（迁移零改值铁律——两档同值=原视图对双主题同值）
        assert 'fieldAxisLine: { light: "#55607a", dark: "#55607a" }' in _THEME
        assert 'calibNullCost: { light: "#8391a7", dark: "#8391a7" }' in _THEME
        m = re.search(r"export const ISO_BAND = \[(.*?)\];", _THEME, re.S)
        assert m and re.findall(r'"(#[0-9a-fA-F]{6})"', m.group(1)) == \
            ["#ffffff", "#ffeb3b", "#ff5722"]

    def test_fieldviz_and_calibration_routed_through_theme(self):
        fv = _view_src("view_fieldviz.js")
        assert '"#55607a"' not in fv and '"#ffffff"' not in fv
        assert "THEME_COLORS.fieldAxisLine" in fv
        assert "const levelColors = ISO_BAND;" in fv
        cal = _view_src("view_calibration.js")
        assert '"#8391a7"' not in cal
        assert "THEME_COLORS.calibNullCost" in cal

    def test_filebrowser_backdrop_tokenized(self):
        fb = _view_src("filebrowser.js")
        assert "rgba(0,0,0,.6)" not in fb  # 字面量含注释面一并退役（防第二源回潮）
        assert "background:var(--backdrop-dim)" in fb
        assert "--backdrop-dim: rgba(0, 0, 0, .6);" in _INDEX

    def test_pages_quoted_hex_ratchet_zero(self):
        # pages/ 全域：引号包裹 hex 色字面量归零（canvas/echarts 色一律走
        # theme.js 单源——THEME_COLORS/chartPalette/HEAT_BAND/ISO_BAND）。
        # plotcard.js（static/ 根，golden 快照钉面）与 app.js（3D 材质色，
        # test_ui_nav_focus SCENE3D 豁免）不在本棘轮范围。
        hits = []
        for p in sorted((_STATIC / "pages").glob("*.js")):
            for m in _HEX_QUOTED.finditer(p.read_text(encoding="utf-8")):
                hits.append((p.name, m.group(0)))
        assert hits == [], f"pages/ 残留 hex 字面量: {hits}"

    def test_token_same_value_swaps_landed(self):
        # 同值替换落位（computed value 逐字节不变——:root 令牌 4/8/12/16px、
        # --text-xs 11px、--text-sm 13px、--radius-xs/sm/md 6/8/12px）
        assert len(re.findall(r'font-size:var\(--text-xs\)(?=["\';}])', _UNION)) == 6
        assert len(re.findall(r'font-size:var\(--text-sm\)(?=["\';}])', _UNION)) == 1
        assert len(re.findall(r'border-radius:var\(--radius-xs\)(?=["\';}])', _UNION)) == 4
        assert len(re.findall(r'border-radius:var\(--radius-sm\)(?=["\';}])', _UNION)) == 1
        assert len(re.findall(r'border-radius:var\(--radius-md\)(?=["\';}])', _UNION)) == 1
        assert len(re.findall(r'margin:var\(--space-2\) 0 2px', _UNION)) == 2
        assert len(re.findall(r'margin:var\(--space-2\) 0(?=["\';}])', _UNION)) == 3
        assert len(re.findall(r'padding:var\(--space-1\) 0(?=["\';}])', _UNION)) == 2
        assert len(re.findall(r'margin:var\(--space-1\) 0(?=["\';}])', _UNION)) == 1
        assert len(re.findall(r'margin-bottom:var\(--space-3\)(?=["\';}])', _UNION)) == 3
        assert len(re.findall(r'padding:var\(--space-2\) var\(--space-3\)', _UNION)) == 2
        assert len(re.findall(r'gap:var\(--space-2\)(?=["\';}])', _UNION)) == 5
        # 旧字面归零（被替换的 (属性,值) 组合不得回潮）
        for stale in ("font-size:11px", "font-size:13px", "border-radius:6px",
                      "border-radius:8px", "border-radius:12px",
                      "margin-bottom:12px", "padding:8px 12px",
                      "margin:8px 0 2px", "margin:8px 0", "padding:4px 0",
                      "margin:4px 0"):
            assert stale not in _UNION, stale

    def test_no_token_px_residual_inventory_frozen(self):
        # 残余 px 清单冻结（无同值令牌的合法残余——尺寸/定位/非 4px 网格值/
        # 含 0 分量的混排；只收不放：新增内联 px 须走令牌或同笔更新本清单）
        pat = re.compile(
            r'(font-size|border-radius|margin-top|margin-bottom|margin|padding|gap)'
            r':((?:[0-9.]+px|0)(?:\s+(?:[0-9.]+px|0))*)')
        SPACE_TOKENS = {"4px", "8px", "12px", "16px", "20px", "24px", "32px",
                        "40px", "48px"}
        FONT_TOKENS = {"11px", "13px", "14px", "16px", "20px"}
        RADIUS_TOKENS = {"6px", "8px", "12px", "16px", "20px", "24px"}
        residual = set()
        for p in sorted([*_STATIC.joinpath("pages").glob("*.js"),
                         _STATIC / "app.js"]):
            if p.name in ("theme.js", "api.js"):
                continue
            for m in pat.finditer(p.read_text(encoding="utf-8")):
                prop, val = m.group(1), m.group(2)
                comps = val.split()
                if prop == "font-size" and val in FONT_TOKENS:
                    continue
                if prop == "border-radius" and val in RADIUS_TOKENS:
                    continue
                if prop in ("margin", "margin-top", "margin-bottom", "padding",
                            "gap") and all(x in SPACE_TOKENS for x in comps):
                    continue
                residual.add(f"{prop}:{val}")
        expect = {
            "border-radius:10px", "border-radius:4px",
            "font-size:11.5px", "font-size:12px",
            "margin-top:3px", "margin-top:6px", "margin-top:10px",
            "margin-top:14px",
            "margin:6px 0", "margin:6px 0 0", "margin:10px 0 2px",
            "margin:10px 0 4px", "margin:0", "margin:0 0 4px",
            "margin-bottom:6px", "margin-bottom:10px",
            "padding:14px", "padding:10px", "padding:6px 10px", "padding:1px 8px",
            "padding:0", "padding:0 10px", "padding:0 10px 6px",
            "padding:5px 8px", "padding:3px 4px",
            "gap:6px", "gap:10px", "gap:14px",
        }
        assert residual == expect, (
            f"残余漂移: 新增={sorted(residual - expect)} "
            f"消失={sorted(expect - residual)}")


# ══════════════════ 跨席计数钉复述（三任务不扰既有面） ══════════════════

class TestCrossSeatPinsHold:
    def test_pages_union_counts_untouched(self):
        assert _UNION.count("T.plotCard(") == 16  # 12 + W3-S12 四管线逃生舱迁移
        assert _UNION.count('window.addEventListener("hashchange"') == 1
        assert _UNION.count("bindClickRows(") == 13
        assert _UNION.count("color: HEAT_BAND") == 3

    def test_index_inline_scripts_untouched(self):
        inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
                            _INDEX, re.S)
        assert len(inline) == 2  # 主题防闪 boot + importmap（CSP 哈希钉）
