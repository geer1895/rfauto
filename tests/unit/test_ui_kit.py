"""aurora72 A7-A（R6 审计 R-3 试点）UI-KIT 三件行为钉 + 逐字节等价钉。

两层钉（同 test_ui_xss_escape 口径）：
1. **行为钉（node 真执行）**：动态 import pages.js，对 kitTable/kitPanelHead/
   kitBadge 族做字节形态断言 + **逐字节等价回归**——每个迁移消费点的迁移前
   innerHTML 串由 helper 复现（试点纪律"aria/类名/结构不变才能迁"的机器可
   执行版；期望串取自迁移前源码原文）。缺 node 时 skip（源码钉层仍生效）。
   node 语境 T 未注入 → 徽章族走 _kitBadgeRaw 回退，与 T.badge 逐字节同串
   （浏览器路径恒走 app.js badge 单点，两实现同串由 test_kit_badge_fallback_
   matches_toolkit_badge 交叉验证）。
2. **源码钉（免 node）**：UI-KIT 区块单源在位 + 迁移消费点在位 + **如实不迁
   点原样在位**（runs 表行路由钉/座位表裸 th 字面钉/runs 状态列恒 muted/
   queue 阶段徽章语义/wWidget 面板头 b 内按钮形态——他席钉与语义差异点
   不清偿，见各断言注记）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
# aurora_d UI-R2（2026-10-14）：pages.js 拆分为薄入口 + pages/ 域模块（零构建
# ESM）——源码钉读"入口+全部域模块"并集，行为断言逐字不变（拆分前=单文件）。
def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)

_PAGES = _pages_union_text()


_NODE = shutil.which("node")

# ── 迁移前原文（期望串；取自迁移前 innerHTML 模板，逐字节保真）───────────

# wRecentRuns（dashboard 最近 Run 表）：一行 + 空态两形态
_WRECENTRUNS_ROW = (
    '<tr class="clickable" data-id="20260101_000000_x">'
    "<td>20260101_000000_x</td><td>fake</td><td>-15.23 dB</td></tr>"
)
_WRECENTRUNS_HEAD = (
    "<table><thead><tr><th scope=\"col\">run_id</th>"
    '<th scope="col">adapter</th><th scope="col">带内 S11</th></tr></thead><tbody>'
)
_WRECENTRUNS_FULL = _WRECENTRUNS_HEAD + _WRECENTRUNS_ROW + "</tbody></table>"
_WRECENTRUNS_EMPTY = _WRECENTRUNS_HEAD + "</tbody></table>"

# 求解器注册状态表（pageSolvers）
_SOLVERS_FULL = (
    "<table><thead><tr><th scope=\"col\">类型</th>"
    '<th scope="col">类</th><th scope="col">可用</th><th scope="col">可视化</th>'
    "</tr></thead><tbody>"
    "<tr><td><b>fake</b></td>"
    '<td class="muted">FakeAdapter</td>'
    '<td><span class="badge ok">可用</span></td><td>3</td></tr>'
    "</tbody></table>"
)

# 工具箱扫参结果表（动态首列名；kit 内 esc 与原 esc(pName) 同串）
_SWEEP_FULL = (
    '<table><thead><tr><th scope="col">line_width_mm</th>'
    '<th scope="col">响应</th><th scope="col">状态</th></tr></thead><tbody>'
    "<tr><td class='muted'>0.5</td><td><b>42.5</b></td><td>OK</td></tr>"
    "</tbody></table>"
)

# 收件箱提案 diff 表（rowsHtml 预构建行形态；空 rows=空 tbody 等价）
_PROPOSAL_FULL = (
    "<table><thead><tr><th scope=\"col\">参数</th>"
    '<th scope="col">当前值</th><th scope="col">提案值</th></tr></thead><tbody>'
    "<tr><td><b>arm_len_mm</b></td><td class=\"muted\">20.5</td>"
    "<td style=\"color:var(--warn)\">21.0 (2.4%)</td></tr>"
    "</tbody></table>"
)
_PROPOSAL_EMPTY = (
    "<table><thead><tr><th scope=\"col\">参数</th>"
    '<th scope="col">当前值</th><th scope="col">提案值</th></tr></thead><tbody>'
    "</tbody></table>"
)

# 双 run 对比两表（空态行=单引号 colspan 原样覆盖串）
_DIFF_METRICS_EMPTY = (
    "<table><thead><tr><th scope=\"col\">指标</th>"
    '<th scope="col">a</th><th scope="col">b</th><th scope="col">Δ</th>'
    "</tr></thead><tbody>"
    "<tr><td colspan='4' class='muted'>两侧均无指标</td></tr></tbody></table>"
)
_DIFF_PARAMS_EMPTY = (
    "<table><thead><tr><th scope=\"col\">路径</th>"
    '<th scope="col">类型</th><th scope="col">a</th><th scope="col">b</th>'
    "</tr></thead><tbody>"
    "<tr><td colspan='4' class='muted'>快照无差异</td></tr></tbody></table>"
)

# UQ 指标分布表（stats 空 → 单引号 colspan='5' 空态行）
_UQ_STATS_EMPTY = (
    "<table><thead><tr><th scope=\"col\">指标</th>"
    '<th scope="col">mean</th><th scope="col">std</th>'
    '<th scope="col">q05</th><th scope="col">q95</th></tr></thead><tbody>'
    "<tr><td colspan='5' class='muted'>无</td></tr></tbody></table>"
)

# Playground 预测表（动态列名数值恒等；恶意串升级为转义）
_PG_HEAD_NUM = (
    "<table><thead><tr><th scope=\"col\">指标</th>"
    '<th scope="col">代理预测</th>'
    "<th scope=\"col\">最近样本真值（归一化距离 0.0199）</th></tr></thead><tbody>"
)
_PG_HEAD_FULL = _PG_HEAD_NUM + "<tr><td class='muted'>s11_db</td></tr></tbody></table>"

# 统一空态行（缺省文案）
_DEFAULT_EMPTY_2COLS = (
    "<table><thead><tr><th scope=\"col\">a</th>"
    '<th scope="col">b</th></tr></thead><tbody>'
    '<tr><td colspan="2" class="muted">暂无数据</td></tr></tbody></table>'
)

# sortable 挂载形态
_SORTABLE_EMPTY = (
    '<table data-sortable><thead><tr><th scope="col">x</th></tr></thead><tbody>'
    "</tbody></table>"
)

# 无表头键值表形态（tools 结果/画廊结果族）
_HEADERLESS = "<table><tbody><tr><td>k</td></tr></tbody></table>"


def _run_node_js(js: str) -> str:
    """node 子进程跑一段 JS（stdout 返回；非零退出抛 AssertionError）。"""
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60,
        cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2000:]}"
    return r.stdout


def _kit_call(expr: str) -> str:
    """import pages.js 后求值 expr（应产出 HTML 串），原文返回。"""
    js = f"const m = await import('./pages.js');\nconsole.log({expr});\n"
    return _run_node_js(js).strip()


@pytest.mark.skipif(_NODE is None, reason="本机无 node，行为钉退源码钉层")
class TestKitTableNode:
    """kitTable 字节形态 + 迁移消费点逐字节等价回归。"""

    def test_wrecentruns_byte_equality(self):
        """dashboard 最近 Run 表：迁移前 innerHTML 串逐字节复现（含行模板）。"""
        js = (
            "const m = await import('./pages.js');\n"
            "const run = { run_id: '20260101_000000_x', adapter: 'fake', "
            "metrics: { s11_db_max_in_band: -15.234 } };\n"
            "const html = m.kitTable({ columns: ['run_id', 'adapter', '带内 S11'], "
            "rows: [run], empty: '',\n"
            "  rowHtml: (r) => { const m11 = r.metrics && r.metrics.s11_db_max_in_band;\n"
            "    return `<tr class=\"clickable\" data-id=\"${m.escAttr(r.run_id)}\">"
            "<td>${m.esc(r.run_id || '')}</td><td>${m.esc(r.adapter || '')}</td>"
            "<td>${m.esc(typeof m11 === 'number' ? m11.toFixed(2) + ' dB' : '-')}</td></tr>`;\n"
            "  } });\n"
            "console.log(JSON.stringify(html));\n"
        )
        assert json.loads(_run_node_js(js)) == _WRECENTRUNS_FULL

    def test_wrecentruns_empty_tbody_byte_equality(self):
        """rows=[] + empty:'' → 空 tbody（原实现无空态行的等价语义）。"""
        js = (
            "const m = await import('./pages.js');\n"
            "console.log(JSON.stringify(m.kitTable({ "
            "columns: ['run_id', 'adapter', '带内 S11'], rows: [], empty: '', "
            "rowHtml: () => '' })));"
        )
        assert json.loads(_run_node_js(js)) == _WRECENTRUNS_EMPTY

    def test_solvers_table_byte_equality(self):
        """求解器注册状态表：含 kitBoolBadge 徽章的原串复现。"""
        js = (
            "const m = await import('./pages.js');\n"
            "const html = m.kitTable({ columns: ['类型', '类', '可用', '可视化'], "
            "rows: [{ type: 'fake', class: 'FakeAdapter', available: true, "
            "n_visualizations: 3 }], empty: '',\n"
            "  rowHtml: (s) => `<tr><td><b>${m.esc(s.type)}</b></td>"
            "<td class=\"muted\">${m.esc(s.class)}</td>"
            "<td>${m.kitBoolBadge(s.available, '可用', '不可用')}</td>"
            "<td>${m.esc(s.n_visualizations)}</td></tr>` });\n"
            "console.log(JSON.stringify(html));\n"
        )
        assert json.loads(_run_node_js(js)) == _SOLVERS_FULL

    def test_dynamic_column_name_esc_equivalence(self):
        """扫参表动态首列名：kit 内 esc 与原 esc(pName) 串相等；恶意串被转义。"""
        js = (
            "const m = await import('./pages.js');\n"
            "const html = m.kitTable({ columns: ['line_width_mm', '响应', '状态'], "
            "rows: [{ x: 0.5, y: 42.5, error: null }], empty: '',\n"
            "  rowHtml: (r) => `<tr><td class='muted'>${m.esc(r.x)}</td>"
            "<td>${r.y == null ? '-' : '<b>' + m.esc(r.y) + '</b>'}</td><td>OK</td></tr>` });\n"
            "console.log(JSON.stringify(html));\n"
        )
        assert json.loads(_run_node_js(js)) == _SWEEP_FULL
        # 列名转义：kitTable 对列头文本统一 esc（动态列名安全），原串含标签
        # 时输出实体（原实现动态列走 esc 同保证；静态中文列 esc 恒等）
        out = json.loads(_run_node_js(
            "const m = await import('./pages.js');\n"
            "console.log(JSON.stringify(m.kitTable({ "
            'columns: ["<img src=x onerror=alert(1)>"], rows: [], empty: "" })));'))
        assert "<img" not in out and "&lt;img" in out

    def test_proposal_table_rowshtml_and_empty_tbody(self):
        """收件箱提案表：rowsHtml 预构建行 + 空 rows 空 tbody 两形态。"""
        js = (
            "const m = await import('./pages.js');\n"
            "const rows = `<tr><td><b>arm_len_mm</b></td>"
            '<td class="muted">20.5</td>'
            '<td style="color:var(--warn)">21.0 (2.4%)</td></tr>`;\n'
            "console.log(JSON.stringify(m.kitTable({ "
            "columns: ['参数', '当前值', '提案值'], rowsHtml: rows, empty: '' })));"
        )
        assert json.loads(_run_node_js(js)) == _PROPOSAL_FULL
        out = json.loads(_run_node_js(
            "const m = await import('./pages.js');\n"
            "console.log(JSON.stringify(m.kitTable({ "
            "columns: ['参数', '当前值', '提案值'], rowsHtml: '', empty: '' })));")
        )
        assert out == _PROPOSAL_EMPTY

    def test_run_diff_empty_override_single_quote_colspan(self):
        """双 run 对比空态行：单引号 colspan='4' 原样覆盖串逐字节保留。"""
        js = (
            "const m = await import('./pages.js');\n"
            "console.log(JSON.stringify(m.kitTable({ "
            "columns: ['指标', 'a', 'b', 'Δ'], rowsHtml: '', "
            "empty: \"<tr><td colspan='4' class='muted'>两侧均无指标</td></tr>\" })));"
        )
        assert json.loads(_run_node_js(js)) == _DIFF_METRICS_EMPTY
        js2 = (
            "const m = await import('./pages.js');\n"
            "console.log(JSON.stringify(m.kitTable({ "
            "columns: ['路径', '类型', 'a', 'b'], rowsHtml: '', "
            "empty: \"<tr><td colspan='4' class='muted'>快照无差异</td></tr>\" })));"
        )
        assert json.loads(_run_node_js(js2)) == _DIFF_PARAMS_EMPTY

    def test_uq_stats_empty_override(self):
        """UQ 指标分布空态行（colspan='5' 单引号形态）逐字节保留。"""
        out = json.loads(_kit_call(
            "JSON.stringify(m.kitTable({ columns: ['指标', 'mean', 'std', 'q05', 'q95'], "
            "rowsHtml: '', "
            'empty: "<tr><td colspan=\'5\' class=\'muted\'>无</td></tr>" }))'))
        assert out == _UQ_STATS_EMPTY

    def test_playground_dynamic_column_numeric_identity_and_escape_upgrade(self):
        """Playground 动态列名：数值域 esc 恒等（逐字节等价）；字符串升级转义。"""
        js = (
            "const m = await import('./pages.js');\n"
            "const col3 = '最近样本真值（归一化距离 ' + 0.0199 + '）';\n"
            "console.log(JSON.stringify(m.kitTable({ "
            "columns: ['指标', '代理预测', col3], "
            "rowsHtml: `<tr><td class='muted'>s11_db</td></tr>`, empty: '' })));"
        )
        assert json.loads(_run_node_js(js)) == _PG_HEAD_FULL
        # 恶意串：原实现裸插值是 XSS 面，迁移后经 kit esc 升级为惰性文本
        out = json.loads(_run_node_js(
            "const m = await import('./pages.js');\n"
            "const col3 = '最近样本真值（归一化距离 ' + "
            "'\\\"/><img src=x onerror=alert(1)>' + '）';\n"
            "console.log(JSON.stringify(m.kitTable({ "
            "columns: [col3], rows: [], empty: '' })));"))
        assert "<img" not in out and "&lt;img" in out

    def test_default_empty_row_and_sortable_and_headerless(self):
        """缺省空态行（暂无数据+colspan）/ sortable 挂载 / 无表头键值表形态。"""
        out = json.loads(_kit_call(
            "JSON.stringify(m.kitTable({ columns: ['a', 'b'], rows: [] }))"))
        assert out == _DEFAULT_EMPTY_2COLS
        out2 = json.loads(_kit_call(
            "JSON.stringify(m.kitTable({ columns: ['x'], rows: [], sortable: true, "
            "empty: '' }))"))
        assert out2 == _SORTABLE_EMPTY
        out3 = json.loads(_kit_call(
            "JSON.stringify(m.kitTable({ columns: null, "
            "rowsHtml: '<tr><td>k</td></tr>' }))"))
        assert out3 == _HEADERLESS


@pytest.mark.skipif(_NODE is None, reason="本机无 node，行为钉退源码钉层")
class TestKitPanelHeadNode:
    """kitPanelHead 字节形态 + 迁移消费点逐字节等价回归。"""

    def test_plain_head_byte_form(self):
        """无 attrs/actions 形态：收件箱面板头原串复现。"""
        out = json.loads(_kit_call(
            "JSON.stringify(m.kitPanelHead('审批收件箱（提案以参数 diff 展示）'))"))
        assert out == ("<div class='panel'><b class='title'>"
                       "审批收件箱（提案以参数 diff 展示）</b>")

    def test_attrs_and_actions_byte_form(self):
        """attrs（style 原引号形态）与 actions 续串：tune 结果面板头原串复现。"""
        out = json.loads(_kit_call(
            "JSON.stringify(m.kitPanelHead('结果', '', "
            '"id=\'tune-result\' style=\'display:none\'"))'))
        assert out == ("<div class='panel' id='tune-result' style='display:none'>"
                       "<b class='title'>结果</b>")

    def test_title_not_double_escaped(self):
        """title 语境=调用方预转义契约：esc 过的动态值原样通过（不二次转义）。"""
        out = json.loads(_kit_call(
            "JSON.stringify(m.kitPanelHead(m.esc('锚<a>')))"))
        assert out == "<div class='panel'><b class='title'>锚&lt;a&gt;</b>"

    def test_actions_passthrough_byte_form(self):
        """actions 原样续串（换行/缩进/控件按调用方字节保留）。"""
        out = json.loads(_kit_call(
            "JSON.stringify(m.kitPanelHead('里程碑（由易到难，逐项验收）', "
            "'\\n        <table id=\\'lb-ms\\'>'))"))
        assert out == ("<div class='panel'><b class='title'>"
                       "里程碑（由易到难，逐项验收）</b>\n        <table id='lb-ms'>")


@pytest.mark.skipif(_NODE is None, reason="本机无 node，行为钉退源码钉层")
class TestKitBadgeNode:
    """状态→徽章单源：类映射全键 + 回退 + 二元/布尔族字节形态。"""

    def test_status_class_map_full(self):
        """KIT_STATUS_CLS 全键口径（按各迁移点既有口径逐一登记）。"""
        cases = {
            "PASS": "ok", "FAIL": "err", "COMPLETE": "ok", "ABORTED": "err",
            "sim_ci": "warn", "calibration": "ok",
            "done": "ok", "passed": "ok", "pass": "ok",
            "fail": "err", "failed": "err", "solve_failed": "err",
            "taken_over": "err", "running": "muted", "pending": "muted",
            "other": "muted", "paused": "warn", "pause_requested": "warn",
            "active": "ok", "stale": "warn", "experimental": "warn",
            "retired": "muted", "awaiting_data": "muted",
        }
        js = (
            "const m = await import('./pages.js');\n"
            "const ks = " + json.dumps(list(cases)) + ";\n"
            "console.log(JSON.stringify(ks.map((k) => m.kitBadgeCls(k))));"
        )
        assert json.loads(_run_node_js(js)) == list(cases.values())

    def test_unknown_and_prototype_keys_fall_back_muted(self):
        """未列状态一律 muted；原型链键（constructor 等）不得漏出非类值。"""
        js = (
            "const m = await import('./pages.js');\n"
            "const ks = ['unknown_x', '', null, undefined, 'constructor', "
            "'__proto__', 'toString', 'valueOf'];\n"
            "console.log(JSON.stringify(ks.map((k) => m.kitBadgeCls(k))));"
        )
        assert json.loads(_run_node_js(js)) == ["muted"] * 8

    def test_badge_byte_forms_match_toolkit_shape(self):
        """kitBadge/kitVerdictBadge/kitBoolBadge 输出与 T.badge 同串
        （node 语境走 _kitBadgeRaw 回退；浏览器走 app.js badge 单点）。"""
        out = json.loads(_kit_call(
            "JSON.stringify([m.kitBadge('夜间回归', 'sim_ci'), "
            "m.kitBadge('run 报告', 'whatever'), "
            "m.kitVerdictBadge('PASS'), m.kitVerdictBadge('PARTIAL'), "
            "m.kitVerdictBadge(null), "
            "m.kitVerdictBadge('PASS', 'ρ=0.912 PASS'), "
            "m.kitVerdictBadge('FAIL', 'ρ=0.500 FAIL'), "
            "m.kitBoolBadge(true, '可用', '不可用'), "
            "m.kitBoolBadge(false, '可用', '不可用')])"))
        assert out == [
            '<span class="badge warn">夜间回归</span>',
            '<span class="badge muted">run 报告</span>',
            '<span class="badge ok">PASS</span>',
            '<span class="badge err">FAIL</span>',
            '<span class="badge err">FAIL</span>',
            '<span class="badge ok">ρ=0.912 PASS</span>',
            '<span class="badge err">ρ=0.500 FAIL</span>',
            '<span class="badge ok">可用</span>',
            '<span class="badge err">不可用</span>',
        ]

    def test_badge_escapes_internally(self):
        """badge 文本出口转义（与 app.js T.badge 单点同保证）。"""
        out = json.loads(_kit_call(
            "JSON.stringify(m.kitBadge('<img src=x onerror=alert(1)>', 'stale'))"))
        assert "<img" not in out and "&lt;img" in out


class TestKitSourcePins:
    """源码钉（免 node）：UI-KIT 单源在位 + 消费点迁移在位 + 如实不迁点在位。"""

    def test_helpers_single_source_exported(self):
        src = _PAGES
        for sig in (
            "export function kitTable(",
            "export function kitPanelHead(",
            "export function kitBadgeCls(",
            "export function kitBadge(",
            "export function kitVerdictBadge(",
            "export function kitBoolBadge(",
        ):
            assert sig in src, sig
        # 单源区块唯一（不建新文件；函数各只定义一次）
        assert src.count("export function kitTable(") == 1
        assert src.count("export function kitPanelHead(") == 1
        assert src.count("const KIT_STATUS_CLS = {") == 1

    def test_migrated_table_consumers_present(self):
        src = _PAGES
        # 8 面 9 调用（runDiff 两表）+ 1 定义解构签名 = 10 处 kitTable({
        assert src.count("kitTable({") == 10
        for needle in (
            'columns: ["run_id", "adapter", "带内 S11"], rows: list, empty: ""',
            'columns: ["类型", "类", "可用", "可视化"], rows: d.solvers || [], empty: ""',
            'columns: [pName, "响应", "状态"], rows, empty: ""',
            'columns: ["参数", "当前值", "提案值"], rowsHtml: rows, empty: ""',
            'columns: ["#", "决策"], rows: dl, empty: ""',
            'columns: ["指标", "a", "b", "Δ"], rowsHtml: mrows',
            'columns: ["路径", "类型", "a", "b"], rowsHtml: prows',
            'columns: ["指标", "mean", "std", "q05", "q95"]',
        ):
            assert needle in src, needle

    def test_migrated_panel_head_and_badge_consumers_present(self):
        src = _PAGES
        # 8 消费点 + 1 定义 = 9 处 kitPanelHead(
        assert src.count("kitPanelHead(") == 9
        for needle in (
            'kitPanelHead("结果", "", "id=\'tune-result\' style=\'display:none\'")',
            'kitPanelHead("审批收件箱（提案以参数 diff 展示）")',
            'kitPanelHead("双 run 对比（只读 diff + S 参数叠图）", "", '
            '"style=\'margin-top:14px\'")',
            'kitPanelHead("里程碑（由易到难，逐项验收）")',
            'kitPanelHead("注册状态")',
            # 徽章族消费点
            "kitVerdictBadge(r.verdict)",  # 校准表
            "kitVerdictBadge(g.verdict)",  # 校准详情
            'kitBoolBadge(s.available, "可用", "不可用")',  # wSolvers+pageSolvers ×2
            "kitBadge(s || \"N/A\", s)",  # loopboard boardBadge
            "kitBadge(st || \"UNKNOWN\", st)",  # anchors stBadge
            "kitBadgeCls(b)",  # wActivity statusBucket 三元
            "kitBadgeCls(c.verdict)",  # queue verdict
        ):
            assert needle in src, needle
        assert src.count('kitBoolBadge(s.available, "可用", "不可用")') == 2

    def test_honest_non_migration_pins_untouched(self):
        """如实不迁点原样在位（字节不等/语义差异，逐条注记原因）。"""
        src = _PAGES
        # ① runs 表：行点击路由钉（test_ui_routing）——UI-R4（aurora_d，A6
        #    P1-5 清偿）随 kit bindClickRows 单源收编更新本钉（键盘可达同笔；
        #    openRun 单入口深链语义不变）；状态列恒 muted（语义=次要信息非
        #    状态灯，与 KIT_STATUS_CLS.done:ok 不同）+ w7c 悬停钉不动
        assert 'bindClickRows(tb, (tr) => openRun(tr.dataset.id), "tr.clickable");' in src
        assert 'T.badge(r.status || "done", "muted")' in src
        # ② 战役座位状态表：UI-R4 清偿 A6 P2-9——原 X2 席裸字面钉 2 处挂
        #    scope=col（test_x2_pr68_ui / test_w7c_ui_p2_sweep 同笔更新）
        assert src.count('<th scope="col">座位状态</th>') == 2
        # ③ queue 阶段徽章：done/pending 之外一律 err（running 含内——与
        #    KIT_STATUS_CLS.running:muted 冲突，语义不同不迁）
        assert 's.status === "done" ? "ok" : (s.status === "pending" ? "muted" : "err")' in src
        # ④ dashboard widget 面板头：按钮在 b 元素内闭合（title 与控件同在
        #    b 内），与 kitPanelHead "</b>" 后置 actions 形态字节不等
        assert "<b class='title'>${w.title}" in src
        # ⑤ 数据集/锚/UQ 样本集清单表：列头 scope='col' 单引号形态，kitTable
        #    双引号规范形与其字节不等（候补下一批，不硬迁）
        assert "<th scope='col'>名称</th>" in src  # datasets
        assert "<th scope='col'>anchor_id</th>" in src  # anchors
        assert "<th scope='col'>文件</th>" in src  # uq assets
