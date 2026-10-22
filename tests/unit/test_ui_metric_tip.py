"""指标词典前端悬浮说明钉（aurora_i W2-S2，R3 设计 M2）。

两层钉（同 test_ui_kit.py 口径）：
1. **行为钉（node 真执行）**：动态 import pages.js，对 kit 三件
   （metricGateVerdict/metricTipText/metricBadgeHtml/metricValueHtml）
   做字节形态断言——着色三态（good→var(--ok)/bad→var(--err)/无判据→
   var(--fg) 中性）、词条缺席降级原徽章逐字节同形、转义与双语回退。
   缺 node 时 skip（源码钉层仍生效）。
2. **源码钉（免 node）**：kit 新块单源在位 + 消费点挂点在位（view_detail
   指标行走 metricBadgeHtml、view_runs 带内 S11 列头 data-mkey+单元格
   metricValueHtml）+ 数据加载单源（metric_glossary.js 会话级缓存）+
   CSS 纯 tooltip 块在位（index.html .m-tip，零内联脚本 CSP 同律）。
   与 service 判定内核的同构由 test_metric_glossary.py 判定类交叉钉
   （两端 op 表分离落地，漂移各自可测）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")


def _run_node_js(js: str) -> str:
    """node 子进程跑一段 JS（stdout 返回；非零退出抛 AssertionError）。"""
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60,
        cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2000:]}"
    return r.stdout


# 词条夹具（与 knowledge/metric_glossary.yaml 首词条同构的测试最小集）
_ENTRY = ("{metric_key: 's11_db_max_in_band', "
          "plain_zh: '带内回波损耗最差点', plain_en: 'Worst in-band RL', "
          "unit: 'dB', good_when: ' <= -10 dB', "
          "pitfall_refs: ['#195', '#370'], "
          "gate: {op: 'max_below', good: -10}}")


@pytest.mark.skipif(_NODE is None, reason="本机无 node，行为钉退源码钉层")
class TestMetricTipNode:
    """kit 指标词典三件行为钉（node 真执行）。"""

    def test_gate_verdict_tri_state(self):
        js = (
            "const m = await import('./pages.js');\n"
            "const g = {op: 'max_below', good: -10};\n"
            "const out = [m.metricGateVerdict(g, -15.2),\n"
            "             m.metricGateVerdict(g, -5),\n"
            "             m.metricGateVerdict(g, -10),\n"
            "             m.metricGateVerdict(null, -5),\n"
            "             m.metricGateVerdict({op: 'unknown_op', good: 1}, 0),\n"
            "             m.metricGateVerdict(g, 'n/a'),\n"
            "             m.metricGateVerdict({op: 'abs_le', good: 0.5}, 0.2),\n"
            "             m.metricGateVerdict({op: 'abs_le', good: 0.5}, 0.71),\n"
            "             m.metricGateVerdict({op: 'bool_true'}, true),\n"
            "             m.metricGateVerdict({op: 'bool_true'}, 'false')];\n"
            "console.log(JSON.stringify(out));\n"
        )
        assert json.loads(_run_node_js(js)) == [
            "good", "bad", "good", "", "", "", "good", "bad", "good", "bad"]

    def test_badge_with_entry_tip_and_color(self):
        js = (
            f"const m = await import('./pages.js');\n"
            f"const e = {_ENTRY};\n"
            "console.log(m.metricBadgeHtml('s11_db_max_in_band', -15.234, e, 'zh'));\n"
        )
        html = _run_node_js(js).strip()
        # 悬浮挂点+判据文本+达标绿三件在位（tip 文本经 escAttr 五字符集转义）
        assert html.startswith('<span class="m-tip" tabindex="0" data-tip="')
        assert "带内回波损耗最差点" in html
        assert "健康判据： &lt;= -10 dB" in html
        assert "常见坑：#195 #370" in html
        assert '<b style="color:var(--ok)">-15.2340</b>' in html

    def test_badge_over_bound_colors_red(self):
        js = (
            f"const m = await import('./pages.js');\n"
            f"const e = {_ENTRY};\n"
            "console.log(m.metricBadgeHtml('s11_db_max_in_band', -3, e, 'zh'));\n"
        )
        assert '<b style="color:var(--err)">-3.0000</b>' in _run_node_js(js)

    def test_badge_without_entry_byte_fallback(self):
        """词条缺席→与 view_detail 迁移前徽章模板逐字节同形（#105 降级）。"""
        js = (
            "const m = await import('./pages.js');\n"
            "console.log(m.metricBadgeHtml('k', -15.234, null, 'zh'));\n"
        )
        assert _run_node_js(js).strip() == (
            '<span class="badge muted" style="margin-right:8px">'
            'k: <b style="color:var(--fg)">-15.2340</b></span>')
        # 字符串值同样走 esc（原模板 esc(v2) 口径）
        js2 = (
            "const m = await import('./pages.js');\n"
            "console.log(m.metricBadgeHtml('k', '<b>', null, 'zh'));\n"
        )
        assert "&lt;b&gt;" in _run_node_js(js2)

    def test_tip_text_bilingual_and_fallback(self):
        js = (
            f"const m = await import('./pages.js');\n"
            f"const e = {_ENTRY};\n"
            "const zh = m.metricTipText(e, 'zh');\n"
            "const en = m.metricTipText(e, 'en');\n"
            "console.log(JSON.stringify([zh, en, m.metricTipText(null, 'zh')]));\n"
        )
        zh, en, none_tip = json.loads(_run_node_js(js))
        assert zh.split("\n")[0] == "带内回波损耗最差点"
        assert en.split("\n")[0] == "Worst in-band RL"
        assert none_tip == ""

    def test_value_cell_format_and_neutral(self):
        js = (
            f"const m = await import('./pages.js');\n"
            f"const e = {_ENTRY};\n"
            "const fmt = (x) => x.toFixed(2) + ' dB';\n"
            "console.log(JSON.stringify([\n"
            "  m.metricValueHtml(e, -15.234, fmt, 'zh'),\n"
            "  m.metricValueHtml(e, -3, fmt, 'zh'),\n"
            "  m.metricValueHtml(null, -15.234, fmt, 'zh'),\n"
            "  m.metricValueHtml(null, undefined, fmt, 'zh')]));\n"
        )
        good, bad, neutral, missing = json.loads(_run_node_js(js))
        assert good == ('<span class="m-tip" tabindex="0" data-tip="'
                        '带内回波损耗最差点\n健康判据： &lt;= -10 dB\n常见坑：'
                        '#195 #370" style="color:var(--ok)">-15.23 dB</span>')
        assert 'style="color:var(--err)">-3.00 dB' in bad
        assert neutral == "<span>-15.23 dB</span>"
        assert missing == "<span>-</span>"


class TestMetricTipSourcePins:
    """源码钉（免 node 层）：单源在位+消费点挂点+降级路径。"""

    def test_kit_block_single_source(self):
        kit = (_STATIC / "pages" / "kit.js").read_text(encoding="utf-8")
        assert kit.count("export function metricGateVerdict(") == 1
        assert kit.count("export function metricTipText(") == 1
        assert kit.count("export function metricBadgeHtml(") == 1
        assert kit.count("export function metricValueHtml(") == 1

    def test_view_detail_mounts_metric_badge(self):
        src = (_STATIC / "pages" / "view_detail.js").read_text(encoding="utf-8")
        # 主落点：详情页指标行走 kit.metricBadgeHtml（词典缓存单源）
        assert "metricGlossaryMap()" in src
        assert "metricBadgeHtml(k, v2, glossary[k], loc)" in src
        # 旧内联徽章模板已迁（单源纪律：双实现并存=漂移面）
        assert 'style="margin-right:8px">${esc(k)}' not in src

    def test_view_runs_header_and_cell(self):
        src = (_STATIC / "pages" / "view_runs.js").read_text(encoding="utf-8")
        # 结果卡：列头 data-mkey 挂点 + 单元格 metricValueHtml
        assert "data-mkey='s11_db_max_in_band'" in src
        assert "metricValueHtml(gEntry, m11," in src
        assert "mountMetricTips(v)" in src

    def test_loader_module_session_cache(self):
        src = (_STATIC / "pages" / "metric_glossary.js").read_text(
            encoding="utf-8")
        assert 'apiFetch("/api/metric-glossary")' in src
        assert "let _promise = null;" in src  # 会话级单拉缓存
        assert ".catch(() => ({}))" in src    # 失败降级空映射（#105）

    def test_css_tooltip_block_present(self):
        html = (_STATIC / "index.html").read_text(encoding="utf-8")
        assert ".m-tip:hover::after" in html
        assert "content: attr(data-tip);" in html
        assert "white-space: pre-line" in html
        # 纯 CSS 悬浮：零内联脚本（CSP 同律——tooltip 不引入新执行面）
        assert "onclick" not in html.split(".m-tip {")[1].split("}", 1)[0]

    def test_kit_zero_api_dependency_preserved(self):
        """kit.js 既有纪律：零对 api 的请求面依赖（apiFetch 不入 kit import
        面）——词典数据加载在 metric_glossary.js 单源（kit 对 api.js 仅存
        setApiErrorPresenter 注册引用，注释字面含 apiFetch 非调用）。"""
        kit = (_STATIC / "pages" / "kit.js").read_text(encoding="utf-8")
        imports = [ln.strip() for ln in kit.splitlines() if '"./api.js"' in ln]
        assert imports == ['import { setApiErrorPresenter } from "./api.js";']

    def test_service_frontend_gate_ops_isomorphic_anchor(self):
        """两端 op 表分离落地的同构锚：service op 常量集与 kit op 表键集
        各自存在（逐 op 行为等价由 TestMetricTipNode 与 test_metric_glossary
        判定类各自钉，本钉防单端删 op 静默）。"""
        svc = Path(__file__).resolve().parents[2] / "src" / "rfauto" / \
            "service" / "metric_glossary_service.py"
        text = svc.read_text(encoding="utf-8")
        assert 'METRIC_GATE_OPS = ("max_below", "min_above", "abs_le", "bool_true")' in text
        kit = (_STATIC / "pages" / "kit.js").read_text(encoding="utf-8")
        for op in ("max_below", "min_above", "abs_le"):
            assert op in kit
        assert "bool_true" in kit
