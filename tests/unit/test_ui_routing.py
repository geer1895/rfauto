"""架构批 A4-C 席位回归钉：UI 两级 hash 路由参数化（R6 审计 R-2）。

对象：src/rfauto/ui/static/app.js（两级分发器 _applyHash + routeDispatch 桥）
与 src/rfauto/ui/static/pages.js（parseRoute 纯解析 + _ROUTE_OPENERS 注册表 +
openRun/openCampaign 深链落地 + showRun 空态）。index.html / palette.js /
plotcard.js / server.py 归他席——本文件只读，不动。

解决的两个 R6 证据：
1. 刷新/分享丢 run：openRun 与 campaign 选择器落地 #/detail/<id>、
   #/campaign/<id>（replaceState 不产历史条目不触 hashchange）；
2. 冷加载 #/detail 白页：带参形态经路由分发器交 openRun（数据拉取+W7-C
   错误面板）；裸形态铺诚实空态引导（原静默早退清偿）。

三层（与 test_ui_tools_page / test_ui_lifecycle 同惯例）：
1. **源码钉（免 node）**：两级协议形态、opener 注册表、旧形态兼容回落、
   深链落地调用点、showRun 空态、hashchange 单源收编（app.js 归零 +
   pages.js 恒 1）。
2. **跨席计数钉复述**（任务书清单；先红=本批扰动生命周期/图表不变量）。
3. **行为钉（node 在才跑，否则诚实 skip）**：parseRoute 两级/非法/回落
   纯函数实测 + 注册表查询/分发 false 路径 + 与 toolsDeepLinkKey 的 tools
   形态向后兼容对拍 + node --check 双文件 + pages.js 真 ESM import
   （app.js 顶层 import "three"+DOM，node 无 importmap 只做 --check 语法门）。

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
_APP = (_STATIC / "app.js").read_text(encoding="utf-8")
# 架构批 UI-R2（2026-10-14）：pages.js 拆分为薄入口 + pages/ 域模块（零构建
# ESM）——源码钉读"入口+全部域模块"并集，行为断言逐字不变（拆分前=单文件）。
def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)

_SRC = _pages_union_text()



def _app_body(sig: str) -> str:
    m = re.search(sig + r" \{(.*?)\n\}", _APP, re.S)
    assert m, f"app.js 函数体缺失: {sig}"
    return m.group(1)


# ────────────────────────── 1. pages.js：两级解析与 opener 注册表 ──────────────────────────

class TestParseRouteProtocol:
    """parseRoute：#/page 与 #/page/<arg> 两级单源解析（纯函数）。"""

    def test_exported_with_anchored_two_group_regex(self):
        assert "export function parseRoute(hash)" in _SRC
        # 锚定两级：页名段不含 /，arg 段贪婪取到串尾（arg 内可含编码后 /）
        assert r'/^#\/([^/]+)(?:\/(.+))?$/' in _SRC, "两级解析正则缺失或形态漂移"

    def test_decode_guard_no_throw(self):
        # decodeURIComponent 非法序列守卫（toolsDeepLinkKey 同款纪律）
        body = re.search(r"export function parseRoute\(hash\) \{(.*?)\n\}", _SRC, re.S)
        assert body, "parseRoute 函数体缺失"
        b = body.group(1)
        assert "decodeURIComponent(m[2])" in b
        assert "catch { arg = m[2]; }" in b

    def test_empty_arg_form_rejected_consistently(self):
        # "#/page/"（尾斜杠空参）不匹配 → null，与 toolsDeepLinkKey("#/tools/") 同判
        body = re.search(r"export function parseRoute\(hash\) \{(.*?)\n\}", _SRC, re.S)
        assert body and "String(hash || \"\")" in body.group(1)


class TestRouteOpenerRegistry:
    """_ROUTE_OPENERS：detail/tools/campaign 三席登记 + 查询/分发入口。"""

    def test_registry_rows(self):
        assert "const _ROUTE_OPENERS = {" in _SRC
        for row in ("detail: (arg) => openRun(arg),",
                    "tools: (arg) => toolsSelectKey(arg),",
                    "campaign: (arg) => openCampaign(arg),"):
            assert row in _SRC, row

    def test_lookup_and_dispatch_exported(self):
        assert "export function routeOpenerFor(page)" in _SRC
        assert "Object.prototype.hasOwnProperty.call(_ROUTE_OPENERS, page)" in _SRC
        assert "export function routeOpen(page, arg)" in _SRC
        body = re.search(r"export function routeOpen\(page, arg\) \{(.*?)\n\}", _SRC, re.S)
        assert body, "routeOpen 函数体缺失"
        b = body.group(1)
        assert "if (!op) return false;" in b  # 页未收参 → false（调用方回落裸页）
        assert "return true;" in b

    def test_registry_uses_in_module_functions_not_injection(self):
        # 三个 opener 均为本模块函数（openRun/toolsSelectKey/openCampaign），
        # 注册表零注入面——桥=app.js 直接消费 parseRoute/routeOpen 导出
        for fn in ("export function openRun(", "export function toolsSelectKey(",
                   "export function openCampaign("):
            assert fn in _SRC, fn


class TestDeepLinkLanding:
    """深链落地：openRun/openCampaign 写 hash；全站打开点收编单入口。"""

    def test_openrun_syncs_route_hash(self):
        body = re.search(r"export function openRun\(runId\) \{(.*?)\n\}", _SRC, re.S)
        assert body, "openRun 函数体缺失"
        b = body.group(1)
        assert 'S.currentRunId = runId;' in b
        assert '_syncRouteHash("detail", runId);' in b
        assert 'showPage("detail");' in b

    def test_sync_route_hash_replacestate_discipline(self):
        body = re.search(r"function _syncRouteHash\(page, arg\) \{(.*?)\n\}", _SRC, re.S)
        assert body, "_syncRouteHash 函数体缺失"
        b = body.group(1)
        # 与 nav/tools syncToolHash 同款：replaceState 不产历史条目不触 hashchange
        assert 'history.replaceState(null, "", want)' in b
        assert '"#/" + page + "/" + encodeURIComponent(String(arg))' in b
        assert 'location.hash !== want' in b  # 同值不重写（幂等）
        assert "typeof location" in b  # node import 零 DOM 依赖守卫

    def test_three_inline_detail_open_sites_absorbed(self):
        # runs 表行 / dashboard 最近 Run / tune 完成跳转——三处内联形态收编。
        # UI-R4（架构批，A6 P1-5 清偿）：前两处行点击接线再收编 kit
        # bindClickRows 单源（键盘可达同笔落地；openRun 单入口深链语义不变）。
        assert 'bindClickRows(tb, (tr) => openRun(tr.dataset.id), "tr.clickable");' in _SRC  # runs 表（R6 R-2 证据页）
        assert 'bindClickRows(el, (tr) => openRun(tr.dataset.id), "tr.clickable");' in _SRC  # dashboard wRecentRuns
        assert "openRun(run.run_id);" in _SRC  # tune 保存并运行完成跳转
        # 内联双行形态不得回潮（单入口=hash 深链同步的前提）
        assert "S.currentRunId = r.run_id; showPage(\"detail\")" not in _SRC
        assert "S.currentRunId = tr.dataset.id; showPage(\"detail\")" not in _SRC
        assert "S.currentRunId = run.run_id; showPage(\"detail\")" not in _SRC

    def test_campaign_deep_link_entry_and_consumption(self):
        assert "export function openCampaign(runId)" in _SRC
        assert "_campaignPendingId = String(runId || \"\");" in _SRC
        # 列表命中才选，未命中回落表头；消费即清（tools 深链同款待选纪律）
        assert "if (_campaignPendingId && runs.some((r) => r.run_id === _campaignPendingId))" in _SRC
        assert "_campaignPendingId = null;" in _SRC
        assert "sel.onchange = () => { syncCampaignHash(); loadDash(); };" in _SRC
        assert "syncCampaignHash(); // A4-C：初载/深链消费后 hash 对齐" in _SRC

    def test_showrun_bare_form_honest_empty_state(self):
        # 裸 #/detail 冷加载：诚实空态引导替代静默早退白页（R6 R-2 证据）
        assert 'id="detail-goto-runs"' in _SRC
        assert 'go.onclick = () => showPage("runs");' in _SRC
        # S2 发布令批：深链用法提示迁词表（detail.empty_no_run zh 值同笔——
        # 原实体 &lt;run_id&gt; 兜底形态在词表侧以字符 〈run_id〉 承载，渲染
        # 保真；_SRC=pages/ 并集含 i18n.js，兜底烘焙与词表值同源可断）
        assert '${t("detail.empty_no_run")}' in _SRC
        assert "#/detail/〈run_id〉" in _SRC
        # W7-C 失败面板不受扰动（重试钮/内联面板钉在 test_w7c_ui_p2_sweep）


# ────────────────────────── 2. app.js：两级分发器与单源收编 ──────────────────────────

class TestAppDispatcher:
    """_applyHash 两级分发（唯一策略面）+ routeDispatch 桥。"""

    def test_imports_parse_route_and_route_open(self):
        # 独立 import 声明：既有 `import { initPages, showPage, esc }` 行被
        # test_ui_xss_escape 源码钉逐字（拆行不合并），本钉只认本批新增行
        assert 'import { parseRoute, routeOpen } from "./pages.js";' in _APP

    def test_two_level_dispatch_structure(self):
        body = _app_body(r"function _applyHash\(\)")
        assert 'const r = parseRoute(location.hash);' in body
        assert "if (!r) return;" in body  # 空/非法 → 保持现状
        assert "if (!_VALID_PAGES.has(r.page)) return;" in body  # 未知页 → 旧回落
        assert "if (r.arg == null) { showPage(r.page); return; }" in body  # 裸页形态
        assert "if (!routeOpen(r.page, r.arg)) showPage(r.page);" in body  # 无 opener 回落

    def test_valid_pages_authority_and_boot_dispatch(self):
        # 页名权威面仍由 nav data-v 派生（_VALID_PAGES 回落语义单源保持）
        assert "const _VALID_PAGES = new Set(" in _APP
        assert '[...document.querySelectorAll("[data-v]")]' in _APP
        assert "_applyHash(); // boot 初载分发" in _APP

    def test_route_dispatch_bridge_injected(self):
        # 单源监听在 pages.js，事件经 initPages 注入回调回注本壳策略面
        assert "routeDispatch: () => _applyHash()," in _APP

    def test_app_has_zero_hashchange_listeners(self):
        # 收编：旧 app.js 页级监听退场——全站唯一监听在 pages.js（单源）
        assert _APP.count('window.addEventListener("hashchange"') == 0

    def test_nav_replacestate_untouched(self):
        # nav 按钮 onclick 同步写 hash（replaceState 不触 hashchange）保持
        assert 'history.replaceState(null, "", "#/" + v)' in _APP


class TestPagesSingleListener:
    """pages.js hashchange 单源（收编旧 tools 自查 + app.js 页级双监听）。"""

    def test_single_listener_delegates_to_route_dispatch(self):
        assert _SRC.count('window.addEventListener("hashchange"') == 1
        body = re.search(r"function _bindToolsDeepLink\(\) \{(.*?)\n\}", _SRC, re.S)
        assert body, "_bindToolsDeepLink 函数体缺失"
        b = body.group(1)
        assert "if (T.routeDispatch) { T.routeDispatch(); return; }" in b  # 单源回注
        # 宿主缺席回退本席 tools 自查（独立加载旧行为保全）
        assert "const key = toolsDeepLinkKey(location.hash);" in b
        assert "if (key) toolsSelectKey(key);" in b

    def test_init_pages_still_binds_and_boot_fallback_kept(self):
        # 幂等装配 + 初载兜底（tools 形态向后兼容的保险丝）保持
        assert "_bindToolsDeepLink(); // 架构批 A2-B" in _SRC
        body = re.search(r"function _bindToolsDeepLink\(\) \{(.*?)\n\}", _SRC, re.S)
        assert body and "_toolsDeepLinkBound" in body.group(1)
        assert "setTimeout" in body.group(1)

    def test_tools_page_hash_sync_untouched(self):
        # syncToolHash 既有纪律不被本批扰动（他席钉：test_ui_tools_page）
        assert 'history.replaceState(null, "", want)' in _SRC
        assert '"#/tools/" + encodeURIComponent(sel.value)' in _SRC


# ────────────────────────── 3. 跨席计数钉复述 ──────────────────────────

class TestCrossSeatPinsHold:
    """任务书跨席计数钉自查（与 test_ui_lifecycle / test_ui_tools_page 同源；
    hashchange 计数变化已在 §2 单钉——本类只复述不变量）。"""

    def test_pages_js_counts_untouched(self):
        assert _SRC.count("T.plotCard(") == 16  # 12 + W3-S12 四管线逃生舱迁移
        assert _SRC.count("window.echarts.init(") == 1  # 唯一入口=echartsInitCached
        assert _SRC.count('window.addEventListener("resize"') == 1
        assert _SRC.count("chartExportTools(el.parentElement, el, {") == 0  # W3-S12 四管线入壳
        assert _SRC.count("bindChartResize(el); // P0-5") == 0  # W3-S12 随壳内建去重
        assert _SRC.count("bindChartResize(el); // 架构批 A3-A") == 1
        assert _SRC.count("disposeChartsIn(") == 4
        assert _SRC.count("setInterval(") == 2  # 仅轮询托管器两处
        assert _SRC.count("echartsInitCached(el)") == 2  # 定义 + tools 页（W3-S12 四管线入壳后）
        assert _SRC.count("plotCardCached(") == 3

    def test_export_surface_intact(self):
        # 他席消费面不被收编扰动（palette/wActivity 消费 openRun）
        assert "export function openRun(" in _SRC
        assert "openRun(row.dataset.id)" in _SRC  # dashboard wActivity 既有单入口


# ────────────────────────── 4. 行为钉（node 在才跑） ──────────────────────────

_NODE_GLUE = r"""
const p = await import('./pages.js');
const A = (cond, msg) => { if (!cond) throw new Error("assert: " + msg); };

// -- parseRoute: two-level forms --
const r1 = p.parseRoute("#/detail/20260101_000000_x");
A(r1.page === "detail" && r1.arg === "20260101_000000_x", "two-level basic");
const r2 = p.parseRoute("#/tools");
A(r2.page === "tools" && r2.arg === null, "bare page arg null");
A(p.parseRoute("#/campaign/abc123").page === "campaign", "campaign page");
A(p.parseRoute("#/detail/a/b").arg === "a/b", "greedy arg keeps slash");

// -- parseRoute: illegal / fallback forms -> null --
A(p.parseRoute("") === null && p.parseRoute(null) === null, "empty -> null");
A(p.parseRoute("#") === null && p.parseRoute("#/") === null, "root -> null");
A(p.parseRoute("#/tools/") === null, "trailing-slash empty arg -> null");
A(p.parseRoute("dashboard") === null, "no-hash-prefix -> null");

// -- parseRoute: decode with malformed-sequence guard --
A(p.parseRoute("#/tools/x%20y").arg === "x y", "percent decode");
A(p.parseRoute("#/tools/%zz").arg === "%zz", "malformed raw no-throw");
A(p.parseRoute("#/tools/vswr%5Fconvert").arg === "vswr_convert", "underscore decode");

// -- registry lookup (structure, no opener execution) --
A(p.routeOpenerFor("detail") instanceof Function, "detail opener");
A(p.routeOpenerFor("tools") instanceof Function, "tools opener");
A(p.routeOpenerFor("campaign") instanceof Function, "campaign opener");
A(p.routeOpenerFor("runs") === null, "bare-only page -> null");
A(p.routeOpenerFor("__nope__") === null, "unknown page -> null");

// -- dispatch false path (no opener -> caller falls back to bare showPage) --
A(p.routeOpen("runs", "x") === false, "no-opener dispatch false");
A(p.routeOpen("__nope__", "") === false, "unknown dispatch false");

// -- backward compat: tools deep-link parser still agrees with new protocol --
A(p.toolsDeepLinkKey("#/tools/albersheim_detection_snr")
  === p.parseRoute("#/tools/albersheim_detection_snr").arg, "tools compat basic");
A(p.toolsDeepLinkKey("#/tools/vswr%5Fconvert")
  === p.parseRoute("#/tools/vswr%5Fconvert").arg, "tools compat decode");
A(p.toolsDeepLinkKey("#/tools") === null
  && p.parseRoute("#/tools").arg === null, "tools compat bare");
A(p.toolsDeepLinkKey("#/tools/") === null
  && p.parseRoute("#/tools/") === null, "tools compat trailing slash");
A(p.toolsDeepLinkKey("#/tools/%zz")
  === p.parseRoute("#/tools/%zz").arg, "tools compat malformed");

console.log("ok:routing");
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestNodeBehavioral:
    def test_parse_route_and_registry_synthetic(self):
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e", _NODE_GLUE],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, cwd=str(_STATIC))
        assert r.returncode == 0, r.stderr[-2000:]
        assert "ok:routing" in r.stdout

    def test_node_check_both_files(self):
        for name in ("app.js", "pages.js"):
            r = subprocess.run([_NODE, "--check", str(_STATIC / name)],
                               capture_output=True, text=True, timeout=60)
            assert r.returncode == 0, f"node --check {name}:\n{r.stderr[-2000:]}"

    def test_pages_js_real_esm_import(self):
        # node --check 对 ESM 语法错误可能假绿（W7-C 工程注记）；真 import 才是门。
        # app.js 顶层 import "three"+DOM（node 无 importmap/无 document），
        # 语法门由 test_node_check_both_files 承担，真 import 只验 pages.js。
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e",
             "await import('file:///" + str(_STATIC / "pages.js").replace("\\", "/") + "');"
             "console.log('esm-ok')"],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
        )
        assert r.returncode == 0, f"pages.js ESM 解析失败:\n{r.stderr[-1500:]}"
        assert "esm-ok" in r.stdout
