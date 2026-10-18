"""aurora_e W5-S23 席位回归钉：UI a11y 深化+体验增强批（深审 a-e 五面六件）。

对象：src/rfauto/ui/static/{index.html,app.js} + pages/{sortable,kit,
view_dashboard,view_tune,view_loopboard,view_runs,view_calibration}.js。

三层（风格同 test_ui_a11y_theme/test_ui_kit）：
1. **源码钉（免 node）**：
   - a 面：可排序表头键盘可达（th tabindex=0 + Enter/Space→onThClick 同一
     激活；P1-2 "禁 innerHTML 重建"钉在 makeSortable 体复核）；
   - b 面：表格 caption 通道（kitTable 可选 caption→sr-only caption；三
     接线点：dashboard 最近 Run/runs 表/cal 表）；轮询变迁读屏公告
     （app.js announce 升格导出+T 注入；tune 终态边沿/loopboard 状态变迁）；
   - c 面：组件增删焦点保持（refreshGridKeepingFocus 三消费面）+ wclose
     aria-label + skip-link 未定义变量修复（--text→--fg 全站唯一未定义
     var 引用清零）+ .sr-only 工具类；
   - e 面：KPI count-up（wKpi 接线 + S.kpiPrev 记忆 + W4-C 零自由定时器
     钉不涉本块复核）。
2. **行为钉（node 真执行，缺 node skip）**：count-up 纯函数数值钉
   （easeOutCubic 真值表/countUpText 夹边/animateKpiValue reduced 直出+
   raf 注入帧推进）+ kitTable caption 字节形态（有/无/恶意串转义/无表头
   忽略）+ node --check 全触达文件。
3. **跨席计数钉复核**：F-4 五写面（pollBoard .innerHTML==5）、
   refreshDashboard 字面消费 2 + refreshGridKeepingFocus 3、
   PAGE_CTX 登记面不涉（零改动自证：pages.js 本席未触）。

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

_INDEX = (_STATIC / "index.html").read_text(encoding="utf-8")
_APP = (_STATIC / "app.js").read_text(encoding="utf-8")
_SORTABLE = (_STATIC / "pages" / "sortable.js").read_text(encoding="utf-8")
_KIT = (_STATIC / "pages" / "kit.js").read_text(encoding="utf-8")
_DASH = (_STATIC / "pages" / "view_dashboard.js").read_text(encoding="utf-8")
_TUNE = (_STATIC / "pages" / "view_tune.js").read_text(encoding="utf-8")
_LB = (_STATIC / "pages" / "view_loopboard.js").read_text(encoding="utf-8")
_RUNS = (_STATIC / "pages" / "view_runs.js").read_text(encoding="utf-8")
_CAL = (_STATIC / "pages" / "view_calibration.js").read_text(encoding="utf-8")


def _body(src: str, sig: str, close: str = "") -> str:
    m = re.search(sig + r" \{(.*?)\n" + close + r"\}", src, re.S)
    assert m, f"函数体缺失: {sig}"
    return m.group(1)


# ────────────────────────── a 面：可排序表头键盘可达 ──────────────────────────

class TestSortableKeyboard:
    def test_th_focusable_and_key_activated(self):
        body = _body(_SORTABLE, r"function makeSortable\(table\)")
        assert 'th.setAttribute("tabindex", "0");' in body, "th 必须可聚焦"
        assert 'e.key === "Enter" || e.key === " "' in body
        assert "onThClick(th)" in body, "键盘与点击须同一 onThClick 激活"
        assert "e.preventDefault();" in body  # 防空格滚屏

    def test_p1_2_no_innerhtml_rebuild_preserved(self):
        # P1-2 跨席钉复核（本席加行不破）：排序走行引用重排
        body = _body(_SORTABLE, r"function makeSortable\(table\)")
        assert "body.appendChild(tr)" in body
        assert "innerHTML" not in body

    def test_click_cycle_and_aria_sort_pins_intact(self):
        body = _body(_SORTABLE, r"function makeSortable\(table\)")
        assert 'setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending")' in body
        assert 'removeAttribute("aria-sort")' in body


# ────────────────────────── b 面：caption + 轮询公告 ──────────────────────────

class TestTableCaption:
    def test_kit_table_optional_caption_param(self):
        assert "export function kitTable({ columns, rows, rowHtml, rowsHtml, empty, sortable, caption })" in _KIT
        assert '<caption class="sr-only">${esc(caption)}</caption>' in _KIT

    def test_three_wiring_sites(self):
        assert 'caption: "最近 Run 表：点行打开 run 详情，点表头排序"' in _DASH
        assert '<caption class="sr-only">Run 历史：点行打开详情，' in _RUNS
        assert '<caption class="sr-only">校准 run 清单：点行打开' in _CAL

    def test_sortable_table_prefix_pins_untouched(self):
        # 跨席钉复核：挂载点约定字面保持（caption 插在其后）
        assert "<table id='runs-table' data-sortable>" in _RUNS
        assert "<table id='cal-table' data-sortable>" in _CAL

    def test_sr_only_utility_class_present(self):
        m = re.search(r"\.sr-only\s*\{([^}]*)\}", _INDEX)
        assert m, ".sr-only 工具类缺失"
        assert "clip: rect(0 0 0 0)" in m.group(1)


class TestPollAnnounce:
    def test_announce_exported_and_injected(self):
        assert "export function announce(text)" in _APP  # 单源升格导出
        assert re.search(r"function announce\(", _APP)  # nav_focus 钉形态兼容
        assert 'setAttribute("aria-live", "polite")' in _APP
        assert "announce," in _APP  # initPages 工具集注入（T.announce 出口）

    def test_tune_terminal_edge_announce(self):
        assert "let _tuneWasRunning = false;" in _TUNE
        assert "_tuneWasRunning = !!st.running;" in _TUNE
        assert "if (wasRunning && !st.running && (st.result || st.error))" in _TUNE
        assert "announceTuneEnd(st);" in _TUNE
        body = _body(_TUNE, r"function announceTuneEnd\(st\)")
        assert 'typeof T.announce !== "function"' in body  # 缺席静默（#105）
        assert "调参已结束：出错" in body and "调参已完成" in body

    def test_loopboard_status_change_announce(self):
        assert 'T.announce("执行看板状态：" + b.status)' in _LB
        assert 'let _lastBoardStatus = "";' in _LB
        assert "b.status && b.status !== _lastBoardStatus" in _LB
        # 错误响应清状态记忆（恢复后同状态重播报一次）
        assert '_lastBoardStatus = "";' in _body(_LB, r"async function pollBoard\(\)")

    def test_f4_five_write_pin_preserved(self):
        # 跨席钉复核（本席公告走 T.announce 零 DOM 写面）
        body = _body(_LB, r"async function pollBoard\(\)")
        assert body.count(".innerHTML") == 5
        assert body.find("if (key === _lastBoardKey)") < body.find(".innerHTML")
        assert 'JSON.stringify(b)' in body  # F-4 比对键原样


# ────────────────────────── c 面：焦点保持 + skip-link 修复 ──────────────────────────

class TestWidgetFocusKeep:
    def test_refresh_grid_keeping_focus_wiring(self):
        assert "async function refreshGridKeepingFocus(widgetId, action, prevIdx)" in _DASH
        # 消费面：定义 1 + chip/close 2（drop 指针驱动不还焦）
        assert _DASH.count("refreshGridKeepingFocus(") == 3
        assert "await refreshDashboard();" in _DASH  # 包装器仍走局部刷新单源
        assert "btn.focus({ preventScroll: true });" in _DASH
        assert 'const add = T.$("w-add");' in _DASH  # 无余面板退添加菜单

    def test_wclose_aria_labels(self):
        assert 'aria-label="加宽/收窄组件：${esc(w.title)}"' in _DASH
        assert 'aria-label="移除组件：${esc(w.title)}"' in _DASH

    def test_mutation_count_pins_aligned(self):
        # 与 test_ui_dashboard_widgets 同笔对齐（直呼 1=drop + 包装器 1）
        assert _DASH.count("refreshDashboard();") == 2
        assert _DASH.count("return pageDashboard();") == 1  # 无壳回退唯一


class TestSkipLinkVarFix:
    def test_skip_link_uses_defined_var(self):
        m = re.search(r"\.skip-link\s*\{([^}]*)\}", _INDEX)
        assert m and "color: var(--fg);" in m.group(1), "skip-link 文字色须走 --fg"

    def test_no_undefined_text_var_anywhere(self):
        # 全站唯一未定义 var 引用清零（--text 只有 --text-* 字号族）
        assert not re.search(r"var\(--text\)", _INDEX), "var(--text) 未定义引用回潮"


# ────────────────────────── e 面：KPI count-up ──────────────────────────

class TestKpiCountUp:
    def test_wkpi_wiring_and_prev_memory(self):
        body = _body(_DASH, r"async function wKpi\(el\)", close="  ")
        assert "animateKpiValue(vs[0], prev.runs || 0, list.length" in body
        assert "S.kpiPrev = { runs: list.length, best, adapters };" in body
        # W4-C 既有字面钉保持（freshnessRing 挂角 + 卡角落定位）
        assert "freshnessRingSvg(list.length ? list[0].timestamp : null, Date.now())" in body
        assert "position:absolute;top:8px;right:10px" in body

    def test_w4c_zero_timer_block_untouched(self):
        # 本席 count-up 在 view_dashboard.js——W4-C 块（dashboard_util+charts）
        # 零自由定时器钉不受扰（文本级复核）
        for name in ("dashboard_util.js", "charts.js"):
            t = (_STATIC / "pages" / name).read_text(encoding="utf-8")
            if "aurora36 W4-C：dashboard 组件深化" in t:
                m = re.search(r"aurora36 W4-C：dashboard 组件深化(.*?)aurora36 W4-C 块结束", t, re.S)
                if m:
                    for timer in ("setInterval(", "setTimeout(", "requestAnimationFrame("):
                        assert timer not in m.group(1), f"{name}: {timer}"


# ────────────────────────── 行为钉（node 真执行） ──────────────────────────

def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return r.stdout


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestCountUpNode:
    def test_ease_out_cubic_truth_table(self):
        out = _run_node_js(
            "const m = await import('./pages/view_dashboard.js');\n"
            "const rows = [[0, 0], [0.5, 0.875], [1, 1]];\n"
            "for (const [t, want] of rows)\n"
            "  if (Math.abs(m.easeOutCubic(t) - want) > 1e-12) throw new Error('ease ' + t);\n"
            "console.log('ok:ease');\n")
        assert "ok:ease" in out

    def test_count_up_text_clamps(self):
        out = _run_node_js(
            "const m = await import('./pages/view_dashboard.js');\n"
            "const f = (n) => n.toFixed(1);\n"
            "const vals = [m.countUpText(0, 100, -1, f), m.countUpText(0, 100, 0.5, f),\n"
            "              m.countUpText(0, 100, 2, f), m.countUpText(10, 10, 0.5, f)];\n"
            "console.log(JSON.stringify(vals));\n")
        import json as _json
        assert _json.loads(out) == ["0.0", "87.5", "100.0", "10.0"]

    def test_animate_reduced_renders_final_directly(self):
        out = _run_node_js(
            "const m = await import('./pages/view_dashboard.js');\n"
            "const el = { textContent: '' };\n"
            "m.animateKpiValue(el, 0, 100, (n) => String(Math.round(n)), { reduced: true });\n"
            "if (el.textContent !== '100') throw new Error(el.textContent);\n"
            "m.animateKpiValue(null, 0, 100, String, { reduced: false }); // null 守卫\n"
            "console.log('ok:direct');\n")
        assert "ok:direct" in out

    def test_animate_raf_frames_progress(self):
        out = _run_node_js(
            "const m = await import('./pages/view_dashboard.js');\n"
            "const el = { textContent: '' };\n"
            "const q = []; let t = 0;\n"
            "m.animateKpiValue(el, 0, 100, (n) => String(Math.round(n)),\n"
            "  { reduced: false, raf: (cb) => q.push(cb), now: () => t });\n"
            "if (q.length !== 1) throw new Error('首帧未排程');\n"
            "t = 150; q[0]();\n"
            "if (el.textContent !== '88') throw new Error('中值 ' + el.textContent);\n"
            "if (q.length !== 2) throw new Error('次帧未排程');\n"
            "t = 300; q[1]();\n"
            "if (el.textContent !== '100') throw new Error('终值 ' + el.textContent);\n"
            "if (q.length !== 2) throw new Error('终帧后不得续排');\n"
            "console.log('ok:raf');\n")
        assert "ok:raf" in out


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestKitCaptionNode:
    def test_caption_byte_form_and_escape(self):
        import json as _json
        out = _json.loads(_run_node_js(
            "const m = await import('./pages.js');\n"
            "console.log(JSON.stringify([\n"
            "  m.kitTable({ columns: ['a', 'b'], rows: [] }),\n"
            "  m.kitTable({ columns: ['a'], rows: [], caption: '表名' }),\n"
            "  m.kitTable({ columns: ['<img src=x>'], rows: [], empty: '', caption: '<b>' }),\n"
            "  m.kitTable({ columns: null, rowsHtml: '<tr><td>k</td></tr>', caption: '忽略' }),\n"
            "]));"))
        # 无 caption=既有字节形态零变化（test_ui_kit 等价钉同口径）
        assert out[0] == ("<table><thead><tr><th scope=\"col\">a</th>"
                          "<th scope=\"col\">b</th></tr></thead><tbody>"
                          "<tr><td colspan=\"2\" class=\"muted\">暂无数据</td></tr></tbody></table>")
        assert out[1] == ("<table><caption class=\"sr-only\">表名</caption><thead><tr>"
                          "<th scope=\"col\">a</th></tr></thead><tbody>"
                          "<tr><td colspan=\"1\" class=\"muted\">暂无数据</td></tr></tbody></table>")
        # caption 走 esc 出口（恶意串实体化）；列头转义既有语义保持
        assert "<b>" not in out[2] and "&lt;b&gt;" in out[2]
        assert "<img" not in out[2] and "&lt;img" in out[2]
        # 无表头键值表形态：caption 不产出（结构分支原样）
        assert out[3] == "<table><tbody><tr><td>k</td></tr></tbody></table>"


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestSyntax:
    @pytest.mark.parametrize("name", [
        "app.js", "pages/sortable.js", "pages/kit.js", "pages/view_dashboard.js",
        "pages/view_tune.js", "pages/view_loopboard.js", "pages/view_runs.js",
        "pages/view_calibration.js",
    ])
    def test_node_check(self, name):
        r = subprocess.run([_NODE, "--check", str(_STATIC / name)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"node --check {name}:\n{r.stderr[-2000:]}"
