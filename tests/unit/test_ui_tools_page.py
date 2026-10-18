"""aurora72 A2-B 席位回归钉：微波工具箱分组+搜索选择器与 #/tools/<key> 深链。

对象：src/rfauto/ui/static/pages.js 工具箱页（pageTools 及其纯函数助手）。
app.js / index.html / palette.js / plotcard.js 归他席——本文件只读，不动。

三层：
1. **源码钉（免 node）**：
   - 分组+搜索选择器：搜索框 #tool-search（键名/中文名/用途三字段过滤）+
     分组 optgroup 装配 + 匹配计数 #tool-count；交互形态=optgroup+搜索
     （R5 §② 落点，弃分类侧栏）；
   - group 契约回退：calcGroup 消费 c.group（A2-A 席并行落地），缺字段回退
     "实验态→键名前缀粗映射→其他"；回退表为前缀粗映射，不复刻 133 键全表；
   - 深链：toolsDeepLinkKey 纯解析 + toolsSelectKey 导出入口 +
     replaceState 同步 + hashchange 自查装配（app.js 页级路由 _VALID_PAGES
     不认 "tools/<key>" 形态，key 段归本席）；
   - 帮助文案：E4 时代平铺清单（"π/T 衰减器"等）退场；组清单改由 API 数据
     实时生成（#tool-help-groups 单源，杜绝三犯陈旧）；三壳同源句保留；
   - 微交互：#tool-run disabled loading + finally 恢复、tool-fade 参数表
     淡入 + prefers-reduced-motion 降级、样式页自注入（index.html 零改动）。
2. **跨席计数钉复述**（与 test_ui_lifecycle / test_ui_dashboard_widgets
   同源；先红=pages.js 生命周期/导出不变量被误改，先于合流门暴露）。
3. **行为钉（node 在才跑，否则诚实 skip）**：calcGroup / groupCalcList /
   toolFilterMatch / toolsDeepLinkKey 纯函数行为 + node --check 语法自检。

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

_INDEX = (_STATIC / "index.html").read_text(encoding="utf-8")


def _tools() -> str:
    """pageTools 函数体切片（起于函数声明，止于下一区块注释）。
    UI-R2：pageTools 收于 view_tools.js 模块尾——并集序中下一区块注释
    （校准工作台）在 view_calibration.js，切片边界改"模块尾"，钉语义不变。"""
    src = (_STATIC / "pages" / "view_tools.js").read_text(encoding="utf-8")
    m = re.search(r"async function pageTools\(\) \{(.*)", src, re.S)
    assert m, "pageTools 函数体缺失"
    return m.group(1)


# ────────────────────────── 1. 源码钉 ──────────────────────────

class TestGroupedSearchSelector:
    """分组 optgroup + 搜索框（交互形态钉：弃平铺 select 与分类侧栏）。"""

    def test_search_box_present(self):
        tools = _tools()
        assert "id='tool-search'" in tools  # 搜索框落 toolbar
        assert "search.oninput = rebuildOptions" in tools  # 实时过滤
        assert "id='tool-count'" in tools  # 匹配计数 N/M

    def test_grouped_optgroup_assembly(self):
        tools = _tools()
        assert "<optgroup label=" in tools  # 按组装配（平铺 innerHTML 退场）
        assert "groupCalcList(vis)" in tools  # 过滤后再分组
        assert "escAttr(g.group)" in tools  # optgroup label 属性语境转义
        assert "escAttr(c.name)" in tools and "esc(calcZhName(c))" in tools

    def test_three_field_filter_single_source(self):
        # 键名/中文名/用途三字段匹配单源在 toolFilterMatch（node 行为钉同源）
        assert "export function toolFilterMatch(" in _SRC
        body = re.search(r"export function toolFilterMatch\(c, q\) \{(.*?)\n\}", _SRC, re.S)
        assert body, "toolFilterMatch 函数体缺失"
        assert "c.name" in body.group(1)
        assert "calcZhName(" in body.group(1)  # 中文名（含 CALC_ZH 兜底）
        assert "c.description" in body.group(1)  # 用途

    def test_group_badge_in_desc_panel(self):
        tools = _tools()
        # 详情面板组徽章消费 calcGroup（A2-A group 字段经回退链归一后的展示面）
        assert "T.badge(calcGroup(cal), \"muted\")" in tools
        # 实验态徽章保持
        assert "实验态（默认不放行）" in tools
        assert 'c.experimental ? " [实验]"' in tools  # 选项内标记保持


class TestGroupFieldContractFallback:
    """group 契约：消费 c.group，缺字段回退，页面不炸。"""

    def test_calc_group_consumes_api_field_first(self):
        assert "export function calcGroup(c)" in _SRC
        body = re.search(r"export function calcGroup\(c\) \{(.*?)\n\}", _SRC, re.S)
        assert body, "calcGroup 函数体缺失"
        b = body.group(1)
        assert 'typeof c.group === "string"' in b  # 字段存在才消费
        assert "c.group.trim()" in b  # 空白值不采信
        assert "c.experimental" in b  # 回退 1：实验态
        assert "TOOL_GROUP_FALLBACK" in b  # 回退 2：前缀粗映射
        assert "TOOL_GROUP_OTHER" in b  # 回退 3：其他

    def test_fallback_table_is_coarse_not_full_catalog(self):
        # 回退表=组名→键名前缀粗映射，不复刻 133 键全表（条目数远小于键数）
        rows = re.findall(r"^\s*\[\".+\", /.+/\],?$", _SRC, re.M)
        assert 5 <= len(rows) <= 30, f"回退表条目数异常: {len(rows)}"

    def test_group_order_table_and_tail_rule(self):
        assert "TOOL_GROUP_ORDER" in _SRC
        assert 'TOOL_GROUP_EXPERIMENTAL = "实验"' in _SRC
        assert 'TOOL_GROUP_OTHER = "其他"' in _SRC


class TestToolsDeepLink:
    """#/tools/<key> 深链：pages.js 侧自查（app.js 页级路由不认 key 段）。"""

    def test_pure_parser_exported(self):
        assert "export function toolsDeepLinkKey(hash)" in _SRC
        assert re.search(r"match\(/\^#\\/tools\\/\(\.\+\)\$/\)", _SRC), \
            "#/tools/<key> 前缀解析正则缺失"

    def test_entry_point_exported_and_wired(self):
        assert "export function toolsSelectKey(key)" in _SRC
        # 装配点在 initPages（幂等 + node import 零 DOM 依赖守卫同 W4-C 惯例）
        assert "_bindToolsDeepLink(); // aurora72 A2-B" in _SRC
        body = re.search(r"function _bindToolsDeepLink\(\) \{(.*?)\n\}", _SRC, re.S)
        assert body, "_bindToolsDeepLink 函数体缺失"
        b = body.group(1)
        assert "_toolsDeepLinkBound" in b  # 幂等守卫
        assert 'typeof window === "undefined"' in b  # node import 零 DOM 依赖
        # 初次载入兜底（app.js boot 的 _applyHash 对 key 深链视而不见）
        assert "setTimeout" in b

    def test_hashchange_listener_single(self):
        # 本文件唯一 hashchange 监听（tools 深链自查）；页级路由在 app.js
        assert _SRC.count('window.addEventListener("hashchange"') == 1

    def test_selector_syncs_hash_via_replacestate(self):
        tools = _tools()
        assert 'history.replaceState(null, "", want)' in tools  # 不产历史条目
        assert '"#/tools/" + encodeURIComponent(sel.value)' in tools
        assert "sel.onchange = () => { renderParams(); syncToolHash(); }" in tools

    def test_deep_key_consumed_with_fallback_to_head(self):
        tools = _tools()
        # 待选 key（编程入口）优先，location.hash 自查兜底；键不存在回落列表头
        assert "_toolsPendingKey || toolsDeepLinkKey(location.hash)" in tools
        assert "cals.some((c) => c.name === dk)" in tools
        assert "rebuildOptions(); // 列表头兜底初选" in tools


class TestHelpTextRefreshed:
    """帮助文案：E4 平铺清单退场 → 注册表实时生成（R5 §⑥ 单源化）。"""

    def test_stale_e4_catalog_gone(self):
        assert "微带/CPW/带状线正反解" not in _SRC
        assert "π/T 衰减器" not in _SRC

    def test_group_summary_generated_from_api(self):
        tools = _tools()
        assert "id='tool-help-groups'" in tools  # 数据驱动挂载点
        assert "groups.map((g) => g.group).join" in tools  # 组清单实时生成
        assert "键 · ${groups.length} 组" in tools

    def test_three_shell_sentence_kept(self):
        # 三壳同源说明保留（CLI rfauto calc / MCP run_calculator / 本 UI）
        assert "三壳一个内核" in _SRC
        assert "rfauto calc" in _SRC and "run_calculator" in _SRC

    def test_deeplink_hint_in_help(self):
        assert "#/tools/&lt;键名&gt;" in _SRC  # 转义后的深链示例


class TestMicroInteractions:
    """参数表淡入 + 计算按钮 loading 态。"""

    def test_run_button_disabled_loading_with_finally_restore(self):
        tools = _tools()
        assert "runBtn.disabled = true" in tools
        assert "runBtn.textContent = \"计算中...\"" in tools
        assert "finally" in tools
        assert "runBtn.disabled = false" in tools  # 请求异常也得恢复
        assert "runBtn.textContent = runLabel" in tools

    def test_params_fade_in_with_reduced_motion_guard(self):
        tools = _tools()
        assert 'classList.remove("tool-fade")' in tools  # 重触发（重排后再加回）
        assert "void tp.offsetWidth" in tools
        assert 'classList.add("tool-fade")' in tools
        assert "toolFade" in _SRC  # keyframes（页自注入样式）
        assert "prefers-reduced-motion" in _SRC  # 系统减动效降级
        assert 'id = "tools-page-style"' in _SRC  # 幂等注入，不动 index.html

    def test_index_html_untouched(self):
        # 席位文件面隔离：工具箱新面（搜索/计数/样式）不进 index.html
        assert "tool-search" not in _INDEX
        assert "tools-page-style" not in _INDEX
        assert "tool-help-groups" not in _INDEX


# ────────────────────────── 2. 跨席计数钉复述 ──────────────────────────

class TestCrossSeatPinsHold:
    """跨席计数钉自查（任务书钉；与 test_ui_lifecycle/test_ui_dashboard_widgets
    同源复述）。口径勘准：任务书 `mode:"convergence"`==2 在 pages.js 的实际
    形态为 `mode: "convergence"`（带空格，2 处；无空格形态只在 plotcard.js，
    归他席文件）——按 pages.js 实测口径钉。"""

    def test_counts_untouched(self):
        assert _SRC.count("T.plotCard(") == 16  # 12 + W3-S12 四管线逃生舱迁移
        assert _SRC.count("window.echarts.init(") == 1  # 唯一入口=echartsInitCached
        assert _SRC.count('window.addEventListener("resize"') == 1
        assert _SRC.count("chartExportTools(el.parentElement, el, {") == 0  # W3-S12 四管线入壳
        assert _SRC.count("bindChartResize(el); // P0-5") == 0  # W3-S12 随壳内建去重
        assert _SRC.count("disposeChartsIn(") == 4
        assert _SRC.count("setInterval(") == 2  # 仅轮询托管器两处（本席零新增）
        assert _SRC.count('mode: "convergence"') == 2  # 口径勘准见类 docstring

    def test_data_v_count_in_index_html_untouched(self):
        assert _INDEX.count("data-v=") == 26  # index.html 本席零改动


# ────────────────────────── 3. 行为钉（node 在才跑） ──────────────────────────

_NODE_GLUE = r"""
const p = await import('./pages.js');
const A = (cond, msg) => { if (!cond) throw new Error("assert: " + msg); };

// ── toolsDeepLinkKey：#/tools/<key> 解析 ──
A(p.toolsDeepLinkKey("#/tools/albersheim_detection_snr") === "albersheim_detection_snr", "dl basic");
A(p.toolsDeepLinkKey("#/tools/vswr%5Fconvert") === "vswr_convert", "dl percent-decode");
A(p.toolsDeepLinkKey("#/tools") === null, "dl page-level -> null");
A(p.toolsDeepLinkKey("#/tools/") === null, "dl trailing-slash -> null");
A(p.toolsDeepLinkKey("#/runs") === null, "dl other-page -> null");
A(p.toolsDeepLinkKey("") === null && p.toolsDeepLinkKey(null) === null, "dl empty -> null");
A(p.toolsDeepLinkKey("#/tools/%zz") === "%zz", "dl malformed no-throw");

// ── calcGroup：契约回退链（group 字段 > 实验态 > 前缀粗映射 > 其他）──
A(p.calcGroup({ name: "vswr_convert", group: "匹配·功分·衰减·耦合" }) === "匹配·功分·衰减·耦合", "group field wins");
A(p.calcGroup({ name: "vswr_convert", group: "  " }) === "匹配·功分·衰减·耦合", "blank group -> prefix map");
A(p.calcGroup({ name: "microstrip_synthesis" }) === "传输线正反解", "prefix map hit");
A(p.calcGroup({ name: "microstrip_loss_heat" }) === "热·功率·可靠性", "specific prefix ordered first");
A(p.calcGroup({ name: "patch_f0_symbolic_e13", experimental: true }) === "实验", "experimental -> 实验");
A(p.calcGroup({ name: "totally_unknown_thing" }) === "其他", "unknown -> 其他");
A(p.calcGroup({}) === "其他" && p.calcGroup(null) === "其他", "missing -> 其他");

// ── groupCalcList：组序（已知组按序 → 未知组 → 实验/其他殿后）──
const cals = [
  { name: "zeta_unknown_thing" },
  { name: "vswr_convert", group: "匹配·功分·衰减·耦合" },
  { name: "cpw_analysis" },
  { name: "patch_f0_symbolic_e13", experimental: true, group: "实验" },
];
const gl = p.groupCalcList(cals);
A(gl.map((g) => g.group).join("|") === "传输线正反解|匹配·功分·衰减·耦合|实验|其他", "group order");
A(gl[0].items.length === 1 && gl[0].items[0].name === "cpw_analysis", "items bucketed");
A(p.groupCalcList([]).length === 0, "empty list -> empty groups");
const gl2 = p.groupCalcList([
  { name: "x", group: "新组甲" }, { name: "y", group: "新组乙" }, { name: "z" },
]);
const gl2names = gl2.map((g) => g.group);
A(gl2names[gl2names.length - 1] === "其他", "other stays last");
A(gl2names.includes("新组甲") && gl2names.includes("新组乙"), "unknown groups present");

// ── toolFilterMatch：键名/中文名/用途三字段（大小写不敏感）──
const cal = { name: "albersheim_detection_snr",
  description: "Albersheim 检测因子经验式三量互算：SNR=..." };
A(p.toolFilterMatch(cal, "") === true, "empty query matches all");
A(p.toolFilterMatch(cal, "ALBERSHEIM") === true, "name match case-insensitive");
A(p.toolFilterMatch(cal, "检测因子") === true, "zh head match");
A(p.toolFilterMatch(cal, "经验式") === true, "description body match");
A(p.toolFilterMatch(cal, "不存在的词") === false, "no match");
A(p.toolFilterMatch(null, "x") === false, "null calc no crash");
const zhCal = { name: "patch_length", description: "long head without zh prefix" };
A(p.toolFilterMatch(zhCal, "贴片") === true, "CALC_ZH fallback name match");

console.log("ok:tools");
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestNodeBehavioral:
    def test_tools_pure_helpers_end_to_end(self):
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e", _NODE_GLUE],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC))
        assert r.returncode == 0, r.stderr[-2000:]
        assert "ok:tools" in r.stdout

    def test_node_check_pages_js(self):
        r = subprocess.run([_NODE, "--check", str(_STATIC / "pages.js")],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]


# ═══════════════ 4. aurora72 A3-A：结果可视化 + 扫参 + 公式面板 ═══════════════
# 对象：pages.js 工具箱页 A3-A 增量（R5 审计 §③§④§⑤ 落地面）。沿用本文件
# 三层惯例：源码钉（免 node）→ 跨席计数钉复述 → node 行为钉（合成数据实测）。

class TestResultVisualizationPins:
    """结果可视化（R5 §③ ~33 键数组/曲线形态）：通用探测器 + 生命周期基建复用。"""

    def test_detector_pure_functions_exported(self):
        for sig in ("toolIsNumList(v, minLen = 2)", "toolDetectCurves(result)",
                    "toolDetectMatrix(result)", "toolResultCellText(val)"):
            assert f"export function {sig}" in _SRC, sig

    def test_axis_regex_anchored_segments(self):
        # 轴名判别分段锚定（^|_…_|$）——防 "box"/"max" 类子串误命中（不硬猜）
        assert ('_TOOL_AXIS_RE = '
                '/(^|_)(x|freq|theta|tau|ebn0|pbo|t_grid|electric|omega|aspect|time)(_|$)/i') in _SRC

    def test_resultchart_reuses_lifecycle_infra(self):
        # 新画图必须复用 echartsInitCached/bindChartResize（不得直呼 init）
        body = re.search(r"function resultChart\(host, result\) \{(.*?)\n\}", _SRC, re.S)
        assert body, "resultChart 函数体缺失"
        b = body.group(1)
        assert "echartsInitCached(el)" in b
        assert "bindChartResize(el); // aurora72 A3-A" in b  # 独立注释尾，不扰 P0-5 计数钉
        assert "window.echarts.init(" not in b
        # 实例自持句柄：innerHTML 换血前自释放（不新增 disposeChartsIn 装配点）
        assert "_toolResultCharts" in b
        assert "disposeChartsIn" not in b

    def test_curve_first_matrix_mutual_exclusion(self):
        # 曲线优先：有曲线不画矩阵（coupling_matrix_response 的 nfreq×2 复数表
        # 与 S 曲线重复；矩阵热图家族键均无 x-y 曲线，互斥不丢覆盖）
        body = re.search(r"function resultChart\(host, result\) \{(.*?)\n\}", _SRC, re.S)
        assert body and "curves.length ? null : toolDetectMatrix(result)" in body.group(1)

    def test_run_handler_chart_plus_json_table(self):
        tools = _tools()
        # 图在前、JSON 键值表并列保留（数据诚实），长数组展示级折叠
        assert 'box.innerHTML = ""' in tools
        assert "resultChart(box, r.result)" in tools
        assert "toolResultCellText(val)" in tools

    def test_detection_caps(self):
        assert "_TOOL_CHART_CAP = 4" in _SRC  # 单结果最多 4 图（防病态刷屏）
        assert "_TOOL_SERIES_CAP = 12" in _SRC  # 单图最多 12 系列


class TestSweepPins:
    """扫参模式（R5 §⑤）：开关→选数值参数→起止点数→逐点串行→指标提取→画曲线。"""

    def test_toggle_and_controls(self):
        tools = _tools()
        assert "id='tool-sweep-on'" in tools  # 开关
        assert "type='checkbox'" in tools
        assert "id='tool-sweep-param'" in tools  # 数值参数下拉（float/int）
        assert "/^(float|int)/i.test(String(p.desc" in tools  # 数值参数筛子
        assert "value='21'" in tools  # 缺省 21 点
        assert "max='101'" in tools

    def test_points_cap_enforced(self):
        tools = _tools()
        assert "Number.isInteger(nPts)" in tools
        assert "nPts > 101" in tools  # 点数上限 101（防滥用）
        assert "nPts < 2" in tools

    def test_serial_loop_and_metric_extraction(self):
        tools = _tools()
        assert "for (let i = 0; i < nPts; i++)" in tools  # 逐点
        assert "toolPickSweepMetric(r.result, pName)" in tools  # 指标提取单源
        body = re.search(r"const runSweep = async \(cal\) => \{(.*?)\n  \};", _SRC, re.S)
        assert body, "runSweep 函数体缺失"
        assert "await T.api" in body.group(1)  # 循环体内 await（串行非并发）
        # 失败点如实跳过标记（不静默丢弃）
        assert "跳过：" in tools
        assert "color:var(--err)'>跳过：" in tools

    def test_no_metric_downgrades_to_table_only(self):
        # 探测不到响应指标就不出曲线只出表格（如实降级不硬猜）
        tools = _tools()
        assert "不出曲线只出表格" in tools
        assert "seriesRows.length >= 2" in tools

    def test_sweep_chart_uses_cached_wrapper(self):
        # 复用 plotCardCached（不新增 T.plotCard 调用点——计数钉 12 不变）
        assert 'plotCardCached(T.$("tool-sweep-chart")' in _SRC

    def test_collect_params_single_source(self):
        # 单点计算与扫参共用参数收集（口径漂移防线）
        tools = _tools()
        assert "const collectParams = (cal)" in tools
        assert tools.count("collectParams(cal)") >= 2

    def test_sweep_out_container_persistent(self):
        # #tool-sweep-out 骨架常驻（图表容器不随 renderParams 换血
        # → plotCardCached 同容器实例可复用）；换计算器只收起不销毁
        tools = _tools()
        assert "id='tool-sweep-out'" in tools
        assert 'T.$("tool-sweep-out").style.display = "none"' in tools


class TestFormulaPanelPins:
    """公式面板（R5 §④）：description 全文等宽 pre，特征探测不到不显示。"""

    def test_details_block_with_feature_probe(self):
        tools = _tools()
        assert 'const descFull = String(cal.description || "")' in tools
        assert "toolDescHasFormula(descFull)" in tools  # 特征探测单源
        assert "<details class='tool-formula'>" in tools
        assert "公式与出处" in tools
        assert "<pre>${esc(descFull)}</pre>" in tools  # 全文 + esc（XSS 反向扫描口径）

    def test_formula_probe_pure_exported(self):
        assert "export function toolDescHasFormula(desc)" in _SRC
        body = re.search(r"export function toolDescHasFormula\(desc\) \{(.*?)\n\}", _SRC, re.S)
        assert body, "toolDescHasFormula 函数体缺失"
        b = body.group(1)
        assert 'indexOf("=")' in b  # "=" 特征
        assert "[：:]" in b  # "：" 特征

    def test_style_appended_to_page_injected_style(self):
        # 样式进页自注入（A2-B tools-page-style 追加，不动 index.html）
        assert ".tool-formula pre{white-space:pre-wrap" in _SRC
        assert "monospace" in _SRC
        assert "tool-formula" not in _INDEX


class TestA3ACrossSeatPinsHold:
    """A3-A 增量后的跨席计数钉复述（新画图全部走缓存基建，钉不红）。"""

    def test_counts_untouched_after_a3a(self):
        assert _SRC.count("T.plotCard(") == 16  # 扫参图走 plotCardCached 包装（12+W3-S12 四管线）
        assert _SRC.count("window.echarts.init(") == 1  # 唯一入口=echartsInitCached
        assert _SRC.count('window.addEventListener("resize"') == 1
        assert _SRC.count("chartExportTools(el.parentElement, el, {") == 0  # W3-S12 四管线入壳
        assert _SRC.count("bindChartResize(el); // P0-5") == 0  # W3-S12 随壳内建去重
        assert _SRC.count("bindChartResize(el); // aurora72 A3-A") == 1  # 本席 1 面
        assert _SRC.count("disposeChartsIn(") == 4  # 本席零新增（_toolResultCharts 自持）
        assert _SRC.count("setInterval(") == 2  # 扫参逐点 await，零新定时器
        assert _SRC.count("color:var(--err)'>✗") == 6  # 本席错误标记用「跳过：」不用 ✗
        assert _SRC.count("echartsInitCached(el)") == 2  # 定义+本席 draw()（W3-S12 四管线入壳后）
        assert _SRC.count("plotCardCached(") == 3  # 定义+tune+本席扫参


# A3-A node 行为钉 glue（独立于既有 _NODE_GLUE，不动既有断言；断言消息
# ASCII——Windows 下 subprocess 文本管道解码失败会掩盖真实断言）。
_NODE_GLUE_A3A = r"""
const p = await import('./pages.js');
const A = (cond, msg) => { if (!cond) throw new Error("assert: " + msg); };

// -- (1) modulation_ber_curve flat shape (R5 sec.3 table A) --
const ber = { ok: true,
  ebn0_db: [0, 2, 4, 6, 8, 10],
  es_n0_db: [3.01, 5.01, 7.01, 9.01, 11.01, 13.01],
  ber: [0.0786, 0.0375, 0.0125, 0.00239, 1.9e-4, 3.9e-6],
  ber_log10: [-1.1, -1.43, -1.9, -2.62, -3.72, -5.4] };
const c1 = p.toolDetectCurves(ber);
A(c1.length === 1 && c1[0].xKey === "ebn0_db", "ber xkey");
A(c1[0].series.length === 3, "ber 3 series");
A(c1[0].series.map((s) => s.name).join(",") === "es_n0_db,ber,ber_log10", "ber names");

// -- (2) circular_cavity_mode_chart series-family shape --
const mode = { aspect_ratios: [0.2, 0.6, 1.0],
  series: [
    { mode: "TM010", f_norm: [2.6, 2.5, 2.42] },
    { mode: "TE111", f_norm: [3.9, 2.9, 2.3] } ],
  crossovers: [{ between: ["TE111", "TM010"], l_over_2a: 1.01, f_norm: 2.3 }] };
const c2 = p.toolDetectCurves(mode);
A(c2.length === 1 && c2[0].title.indexOf("曲线族") === 0, "mode family chart");
A(c2[0].xKey === "aspect_ratios", "mode xkey");
A(c2[0].series.length === 2 && c2[0].series[0].name === "TM010·f_norm", "mode series");

// -- (3) nested {x:[], y:[]} value object --
const c3 = p.toolDetectCurves({ meta: "x", sweep: { x: [1, 2, 3], y: [4, 5, 6] } });
A(c3.length === 1 && c3[0].title.indexOf("sweep：") === 0, "nested title");
A(c3[0].xKey === "x" && c3[0].series[0].name === "y", "nested x/y");

// -- (4) coupling_matrix_response: omega_norm not a series; curve-first --
const cmr = { ok: true, freq_ghz: [2.0, 2.2, 2.4], omega_norm: [-1, 0, 1],
  z_ref: 50, f0_ghz: 2.2, fbw: 0.1,
  s_matrix: [[[1, 0], [0, 0]], [[0.5, 0], [0, 0]], [[0, 0], [0.7, 0]]],
  s11_db: [-0.5, -20, -1], s21_db: [-3.2, -0.2, -2.9], note: "x" };
const c4 = p.toolDetectCurves(cmr);
A(c4.length === 1 && c4[0].xKey === "freq_ghz", "cmr xkey");
A(c4[0].series.map((s) => s.name).join(",") === "s11_db,s21_db", "cmr excl omega_norm");
A(p.toolDetectMatrix(cmr) === null, "curve-first suppresses matrix");

// -- (5) honest downgrade for unrecognized shapes --
A(p.toolDetectCurves({ a: "str", b: 3, c: [1, "x", 2] }).length === 0, "non-num none");
A(p.toolDetectCurves({ t: [1, 2, 3], y1: [1, 2], y2: [1, 2, 3] }).length === 0,
  "len mismatch none");
A(p.toolDetectCurves(null).length === 0 && p.toolDetectCurves([1, 2]).length === 0,
  "null/array none");

// -- (6) heatmap: complex square (coupling-matrix/gstc family) via |.| ; --
//        trajectories (pole lists / point pairs / nfreq x2) never guessed
const m1 = p.toolDetectMatrix({ coupling_matrix: [
  [[0, 0], [0.02, 0], [0, 0]],
  [[0.02, 0], [0, 0], [0.03, 0]],
  [[0, 0], [0.03, 0], [0, 0]] ] });
A(m1 && m1.complex === true && m1.rows === 3 && m1.cols === 3, "complex square");
A(Math.abs(m1.values[1][2] - 0.03) < 1e-12, "complex magnitude");
const m2 = p.toolDetectMatrix({ s_matrix: [
  [[0.5, 0.1], [0.2, 0]], [[0.2, 0], [0.5, -0.1]] ] });
A(m2 && m2.complex && m2.rows === 2, "gstc 2x2");
A(p.toolDetectMatrix({ poles: [[-1, 2], [-1, -2], [-3, 4], [-3, -4], [-5, 6]] }) === null,
  "pole list skipped (non-square)");
A(p.toolDetectMatrix({ grid: [[1, 2, 3], [4, 5, 6]] }) !== null, "numeric 2x3 ok");
A(p.toolDetectMatrix({ pts: [[1, 2], [3, 4], [5, 6]] }) === null, "point-pair skipped");
A(p.toolDetectMatrix({ s_matrix: cmr.s_matrix }) === null, "nfreq x2 complex skipped");

// -- (7) sweep metric: first scalar numeric key other than swept param --
A(p.toolPickSweepMetric({ f0_ghz: 2.45, length_mm: 33.9, note: "x" }, "length_mm").key
  === "f0_ghz", "metric basic");
A(p.toolPickSweepMetric({ w_mm: 1, w_mm_out: 2 }, "w_mm").key === "w_mm_out",
  "exact-name exclusion only");
A(p.toolPickSweepMetric({ arr: [1, 2], ok: true, bad: NaN }, "x") === null,
  "non-scalar null");

// -- (8) formula probe + result cell text --
A(p.toolDescHasFormula("微带线综合：目标 Z0 → 线宽（W/h=1.2）"), "formula yes");
A(!p.toolDescHasFormula("驻波换算"), "formula no");
A(p.toolResultCellText([1, 2, 3]) === "1, 2, 3", "short array");
A(p.toolResultCellText([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14])
  .endsWith("（共 14 项）"), "long array truncated");
A(p.toolResultCellText([[1, 2], [3, 4]]) === "[2×2 矩阵]", "matrix label");
A(p.toolResultCellText({ a: 1 }) === "{\"a\":1}", "object json");
A(p.toolIsNumList([1, 2]) && !p.toolIsNumList([1]) && !p.toolIsNumList([1, "x"])
  && !p.toolIsNumList("ab"), "isNumList");

console.log("ok:a3a");
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestA3ANodeBehavioral:
    def test_a3a_pure_helpers_synthetic(self):
        # 合成数据实测：任务书点名键族（modulation_ber_curve /
        # circular_cavity_mode_chart / coupling_matrix_response 家族形态）
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e", _NODE_GLUE_A3A],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, cwd=str(_STATIC))
        assert r.returncode == 0, r.stderr[-2000:]
        assert "ok:a3a" in r.stdout
