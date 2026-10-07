"""PR-3 PlotCard 组件化回归钉（规格 §D-8，2026-10-02 批）。

三层：
1. **等价金钉（node 真执行，缺 node skip）**：迁移前 app.js drawEChart 的
   option 构造固化为 5 案例快照（harness=runs/pr34/golden_option_harness.mjs，
   Math.random 钉 0.42——band stack id 随机量；快照值内嵌本文件，runs/ 是
   gitignored 证据面，测试不依赖）。迁移后 plotcard.js buildEChartOption
   对同输入同主题必须 **逐字节相等**——「同数据同 option 快照等价」的机器
   可执行版（app.js drawEChart 与 plotCard 共用该 builder，等价由单源保证）。
2. **增量行为钉（node）**：bestSoFar 阶梯 / toCsv 宽长两态+CSV 引号 /
   y2 双轴（yAxis 数组+yAxisIndex）/ crosshair（axisPointer，缺省不带）/
   convergence 增量（best-so-far step 线+终值 markLine+末点 markPoint，
   xvalue 时末点 coord 取 x 值）/ plotCardOption 与 builder base 路径同物。
3. **源码钉（免 node）**：pages.js 全部 drawEChart 调用点换壳 T.plotCard
   （T.drawEChart 调用清零）；声明增量点位计数（crosshair/convergence）；
   app.js 注入面；index.html print 面与 plotcard/toc 样式块。

迁移点清单（11 处迁移 + 1 处新增，2026-10-02 实测；规格写 12 系含定义/
导出行的历史口径——当日 grep T.drawEChart( 调用=11）：
  L294 总览 S11 趋势 / L787 调参 trial 收敛（convergence）/ L900 run 详情
  S 参数（crosshair）/ L1430 校准 ρ 演化 / L1490 校准散点 / L1574 S 参数
  分文件（crosshair）/ L1587 S 参数叠加（crosshair）/ L1708 playground
  探索（band）/ L1794 成本时间线 / L1805 调参收敛（convergence）/
  L2562 Pareto 前沿。base 路径 option 与迁移前逐字节等价（金钉）；
  convergence(2)/crosshair(3+叠图 1) 为规格声明的增量。
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

# 迁移前 option 快照（runs/pr34/golden_option_harness.mjs 产出，2026-10-02；
# valueFormatter 等函数 JSON.stringify 不含——等价断言即 JSON 逐字节口径）。
_GOLDEN_JSON = r"""
{
  "line_category": "{\"backgroundColor\":\"transparent\",\"color\":[\"#4fc3f7\",\"#ffb74d\",\"#81c784\",\"#e57373\",\"#ba68c8\"],\"tooltip\":{\"trigger\":\"axis\"},\"legend\":{\"top\":0,\"textStyle\":{\"color\":\"#dce3ee\"},\"type\":\"scroll\"},\"grid\":{\"left\":52,\"right\":20,\"top\":34,\"bottom\":44},\"xAxis\":{\"type\":\"category\",\"data\":[1.1,2.2,3.3],\"axisLine\":{\"lineStyle\":{\"color\":\"#5f6a80\"}},\"axisLabel\":{\"color\":\"#8391a7\"},\"splitLine\":{\"lineStyle\":{\"color\":\"#1c2331\"}},\"name\":\"GHz\",\"nameTextStyle\":{\"color\":\"#dce3ee\"}},\"yAxis\":{\"type\":\"value\",\"scale\":true,\"axisLine\":{\"lineStyle\":{\"color\":\"#5f6a80\"}},\"axisLabel\":{\"color\":\"#8391a7\"},\"splitLine\":{\"lineStyle\":{\"color\":\"#1c2331\"}},\"name\":\"dB\",\"nameTextStyle\":{\"color\":\"#dce3ee\"}},\"dataZoom\":[{\"type\":\"inside\"},{\"type\":\"slider\",\"height\":18,\"bottom\":6}],\"series\":[{\"name\":\"S11 (dB)\",\"type\":\"line\",\"data\":[-4.5,-12.3,-8.1],\"showSymbol\":false,\"lineStyle\":{\"width\":1.6},\"itemStyle\":{}}]}",
  "scatter_xvalue_markline": "{\"backgroundColor\":\"transparent\",\"color\":[\"#4fc3f7\",\"#ffb74d\",\"#81c784\",\"#e57373\",\"#ba68c8\"],\"tooltip\":{\"trigger\":\"item\"},\"legend\":{\"top\":0,\"textStyle\":{\"color\":\"#dce3ee\"},\"type\":\"scroll\"},\"grid\":{\"left\":52,\"right\":20,\"top\":34,\"bottom\":44},\"xAxis\":{\"type\":\"value\",\"scale\":true,\"axisLine\":{\"lineStyle\":{\"color\":\"#5f6a80\"}},\"axisLabel\":{\"color\":\"#8391a7\"},\"splitLine\":{\"lineStyle\":{\"color\":\"#1c2331\"}},\"name\":\"样本量\",\"nameTextStyle\":{\"color\":\"#dce3ee\"}},\"yAxis\":{\"type\":\"value\",\"scale\":true,\"axisLine\":{\"lineStyle\":{\"color\":\"#5f6a80\"}},\"axisLabel\":{\"color\":\"#8391a7\"},\"splitLine\":{\"lineStyle\":{\"color\":\"#1c2331\"}},\"name\":\"ρ\",\"nameTextStyle\":{\"color\":\"#dce3ee\"}},\"dataZoom\":[],\"series\":[{\"name\":\"样本点\",\"type\":\"scatter\",\"data\":[[9,0.83],[12,0.86]],\"itemStyle\":{\"color\":\"#4fc3f7\",\"opacity\":0.85},\"symbolSize\":12,\"markLine\":{\"silent\":true,\"symbol\":\"none\",\"lineStyle\":{\"type\":\"dashed\",\"color\":\"#ffb74d\"},\"data\":[{\"yAxis\":0.8}]}}]}",
  "band_series": "{\"backgroundColor\":\"transparent\",\"color\":[\"#4fc3f7\",\"#ffb74d\",\"#81c784\",\"#e57373\",\"#ba68c8\"],\"tooltip\":{\"trigger\":\"item\"},\"legend\":{\"top\":0,\"textStyle\":{\"color\":\"#dce3ee\"},\"type\":\"scroll\"},\"grid\":{\"left\":52,\"right\":20,\"top\":34,\"bottom\":44},\"xAxis\":{\"type\":\"value\",\"scale\":true,\"axisLine\":{\"lineStyle\":{\"color\":\"#5f6a80\"}},\"axisLabel\":{\"color\":\"#8391a7\"},\"splitLine\":{\"lineStyle\":{\"color\":\"#1c2331\"}},\"name\":\"x\",\"nameTextStyle\":{\"color\":\"#dce3ee\"}},\"yAxis\":{\"type\":\"value\",\"scale\":true,\"axisLine\":{\"lineStyle\":{\"color\":\"#5f6a80\"}},\"axisLabel\":{\"color\":\"#8391a7\"},\"splitLine\":{\"lineStyle\":{\"color\":\"#1c2331\"}},\"name\":\"y\",\"nameTextStyle\":{\"color\":\"#dce3ee\"}},\"dataZoom\":[{\"type\":\"inside\"},{\"type\":\"slider\",\"height\":18,\"bottom\":6}],\"series\":[{\"name\":\"mean\",\"type\":\"line\",\"data\":[1,2,3],\"showSymbol\":false,\"lineStyle\":{\"width\":1.6},\"itemStyle\":{}},{\"type\":\"line\",\"stack\":\"band-f4bipx\",\"data\":[0.5,1.5,2.5],\"showSymbol\":false,\"silent\":true,\"lineStyle\":{\"opacity\":0},\"emphasis\":{\"disabled\":true},\"tooltip\":{\"show\":false}},{\"name\":\"±1σ\",\"type\":\"line\",\"stack\":\"band-f4bipx\",\"data\":[1,1,1],\"showSymbol\":false,\"silent\":true,\"lineStyle\":{\"opacity\":0},\"emphasis\":{\"disabled\":true},\"areaStyle\":{\"color\":\"#0277bd\",\"opacity\":0.18},\"tooltip\":{\"show\":false}}]}",
  "band_marks": "{\"backgroundColor\":\"transparent\",\"color\":[\"#4fc3f7\",\"#ffb74d\",\"#81c784\",\"#e57373\",\"#ba68c8\"],\"tooltip\":{\"trigger\":\"axis\"},\"legend\":{\"top\":0,\"textStyle\":{\"color\":\"#dce3ee\"},\"type\":\"scroll\"},\"grid\":{\"left\":52,\"right\":20,\"top\":34,\"bottom\":44},\"xAxis\":{\"type\":\"category\",\"data\":[1,2,3],\"axisLine\":{\"lineStyle\":{\"color\":\"#5f6a80\"}},\"axisLabel\":{\"color\":\"#8391a7\"},\"splitLine\":{\"lineStyle\":{\"color\":\"#1c2331\"}},\"name\":\"GHz\",\"nameTextStyle\":{\"color\":\"#dce3ee\"}},\"yAxis\":{\"type\":\"value\",\"scale\":true,\"axisLine\":{\"lineStyle\":{\"color\":\"#5f6a80\"}},\"axisLabel\":{\"color\":\"#8391a7\"},\"splitLine\":{\"lineStyle\":{\"color\":\"#1c2331\"}},\"name\":\"dB\",\"nameTextStyle\":{\"color\":\"#dce3ee\"}},\"dataZoom\":[{\"type\":\"inside\"},{\"type\":\"slider\",\"height\":18,\"bottom\":6}],\"series\":[{\"name\":\"S21\",\"type\":\"line\",\"data\":[1,2,3],\"showSymbol\":false,\"lineStyle\":{\"width\":1.6},\"itemStyle\":{},\"markLine\":{\"silent\":true,\"symbol\":\"none\",\"lineStyle\":{\"type\":\"dashed\",\"color\":\"#ffb74d\"},\"label\":{\"color\":\"#ffb74d\",\"formatter\":\"带内\"},\"data\":[{\"xAxis\":2.3},{\"xAxis\":2.5}]}}]}",
  "empty_series": "{\"backgroundColor\":\"transparent\",\"color\":[\"#4fc3f7\",\"#ffb74d\",\"#81c784\",\"#e57373\",\"#ba68c8\"],\"tooltip\":{\"trigger\":\"axis\"},\"legend\":{\"top\":0,\"textStyle\":{\"color\":\"#dce3ee\"},\"type\":\"scroll\"},\"grid\":{\"left\":52,\"right\":20,\"top\":34,\"bottom\":44},\"xAxis\":{\"type\":\"category\",\"data\":[],\"axisLine\":{\"lineStyle\":{\"color\":\"#5f6a80\"}},\"axisLabel\":{\"color\":\"#8391a7\"},\"splitLine\":{\"lineStyle\":{\"color\":\"#1c2331\"}},\"name\":\"run\",\"nameTextStyle\":{\"color\":\"#dce3ee\"}},\"yAxis\":{\"type\":\"value\",\"scale\":true,\"axisLine\":{\"lineStyle\":{\"color\":\"#5f6a80\"}},\"axisLabel\":{\"color\":\"#8391a7\"},\"splitLine\":{\"lineStyle\":{\"color\":\"#1c2331\"}},\"name\":\"dB\",\"nameTextStyle\":{\"color\":\"#dce3ee\"}},\"dataZoom\":[{\"type\":\"inside\"},{\"type\":\"slider\",\"height\":18,\"bottom\":6}],\"series\":[]}"
}
"""
_GOLDEN = json.loads(_GOLDEN_JSON)


def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2000:]}"
    return r.stdout


# 案例输入与 runs/pr34/golden_option_harness.mjs 逐字一致（含 Math.random 钉）。
_CASES_JS = """
const cases = {
  line_category: {
    series: [{ x: [1.1, 2.2, 3.3], y: [-4.5, -12.3, -8.1], name: "S11 (dB)" }],
    opts: { height: "320px", xlabel: "GHz", ylabel: "dB" },
  },
  scatter_xvalue_markline: {
    series: [{ name: "样本点", type: "scatter", symbolSize: 12,
               color: "#4fc3f7", data: [[9, 0.83], [12, 0.86]] }],
    opts: { xvalue: true, xlabel: "样本量", ylabel: "ρ", zoom: false,
            height: "300px", markline: [{ yAxis: 0.8 }] },
  },
  band_series: {
    series: [
      { name: "mean", x: [1, 2, 3], y: [1, 2, 3] },
      { name: "±1σ", type: "band", x: [1, 2, 3], color: "#0277bd",
        lower: [0.5, 1.5, 2.5], upper: [1.5, 2.5, 3.5] },
    ],
    opts: { xvalue: true, xlabel: "x", ylabel: "y", height: "300px" },
  },
  band_marks: {
    series: [{ name: "S21", x: [1, 2, 3], y: [1, 2, 3] }],
    opts: { xlabel: "GHz", ylabel: "dB", band: [2.3, 2.5] },
  },
  empty_series: { series: [], opts: { height: "240px", xlabel: "run", ylabel: "dB" } },
};
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestGoldenEquivalence:
    """迁移前后 option 快照等价（金钉：JSON 逐字节）。"""

    def test_build_option_matches_pre_refactor_snapshot(self):
        out = _run_node_js(
            "Math.random = () => 0.42;\n"
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, "
            "palette: ['#4fc3f7', '#ffb74d', '#81c784', '#e57373', '#ba68c8'] };\n"
            + _CASES_JS +
            "const out = {};\n"
            "for (const [k, c] of Object.entries(cases))\n"
            "  out[k] = JSON.stringify(m.buildEChartOption(c.series, c.opts, theme));\n"
            "console.log(JSON.stringify(out));\n"
        )
        got = json.loads(out.strip())
        assert got == _GOLDEN

    def test_plot_card_option_delegates_to_builder(self):
        out = _run_node_js(
            "Math.random = () => 0.42;\n"
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, palette: ['#4fc3f7'] };\n"
            "const p = { series: [{ x: [1, 2], y: [3, 4], name: 'n' }], "
            "xlabel: 'x', ylabel: 'y' };\n"
            "const a = JSON.stringify(m.plotCardOption(p, theme));\n"
            "const b = JSON.stringify(m.buildEChartOption(p.series, p, theme));\n"
            "console.log(JSON.stringify(a === b));\n"
        )
        assert json.loads(out.strip()) is True


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestIncrementBehavior:
    """gated 增量：convergence / y2 / crosshair / CSV / bestSoFar。"""

    def test_best_so_far_staircase(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const bs = m.bestSoFar([3, 1, 4, 1, 5, 9, 2, 6]);\n"
            "if (JSON.stringify(bs) !== JSON.stringify([3, 1, 1, 1, 1, 1, 1, 1])) "
            "throw new Error('staircase');\n"
            "if (JSON.stringify(m.bestSoFar([])) !== '[]') throw new Error('empty');\n"
            "console.log('ok:bsf');\n"
        )
        assert "ok:bsf" in out

    def test_to_csv_wide_long_and_quoting(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const wide = m.toCsv([{ name: 'a', x: ['1', '2'], y: [1, 2] }, "
            "{ name: 'b', x: ['1', '2'], y: [3, 4] }]);\n"
            "if (wide !== 'x,a,b\\r\\n1,1,3\\r\\n2,2,4') throw new Error('wide: ' + wide);\n"
            "const long = m.toCsv([{ name: 'p', data: [[1, 2], [3, 4]] }]);\n"
            "if (long !== 'series,x,y\\r\\np,1,2\\r\\np,3,4') throw new Error('long');\n"
            "const mixed = m.toCsv([{ name: 'a', x: [1, 2], y: [1, 2] }, "
            "{ name: 'b', x: [1, 3], y: [5, 6] }]);\n"
            "if (!mixed.startsWith('series,x,y')) throw new Error('x 网不齐应转长表');\n"
            "if (m.toCsv([{ type: 'band', x: [1], lower: [0], upper: [1] }]) !== '') "
            "throw new Error('band 不导出');\n"
            "const q = m.toCsv([{ name: 'x\"y,z', x: ['a'], y: [1] }]);\n"
            "if (!q.includes('\"x\"\"y,z\"')) throw new Error('quoting');\n"
            "console.log('ok:csv');\n"
        )
        assert "ok:csv" in out

    def test_y2_crosshair_gated(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, palette: ['#4fc3f7'] };\n"
            "const o3 = m.buildEChartOption("
            "[{ name: 'a', x: [1, 2], y: [1, 2] }, "
            "{ name: 'b', x: [1, 2], y: [10, 20], y2: true }], "
            "{ y2: '效率', xlabel: 'x' }, theme);\n"
            "if (!Array.isArray(o3.yAxis) || o3.yAxis.length !== 2 || "
            "o3.yAxis[1].name !== '效率') throw new Error('y2 数组');\n"
            "if (o3.series[1].yAxisIndex !== 1 || o3.series[0].yAxisIndex !== undefined) "
            "throw new Error('yAxisIndex');\n"
            "const o4 = m.buildEChartOption([{ name: 'a', x: [1], y: [1] }], "
            "{ crosshair: true }, theme);\n"
            "if (o4.tooltip.axisPointer.type !== 'cross') throw new Error('cross');\n"
            "const o5 = m.buildEChartOption([{ name: 'a', x: [1], y: [1] }], {}, theme);\n"
            "if (o5.tooltip.axisPointer) throw new Error('缺省不得带 cross');\n"
            "if (Array.isArray(o5.yAxis)) throw new Error('缺省单 yAxis');\n"
            "console.log('ok:extras');\n"
        )
        assert "ok:extras" in out

    def test_convergence_mode_increments(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, palette: ['#4fc3f7'] };\n"
            "const o = m.buildEChartOption("
            "[{ name: 'cost', x: [0, 1, 2], y: [3, 1, 2] }], "
            "{ mode: 'convergence', xlabel: 'trial' }, theme);\n"
            "if (o.series.length !== 2) throw new Error('基础系列+阶梯系列');\n"
            "const best = o.series[1];\n"
            "if (best.step !== 'end' || !best.name.includes('best-so-far')) "
            "throw new Error('step 线');\n"
            "if (JSON.stringify(best.data) !== JSON.stringify([3, 1, 1])) "
            "throw new Error('阶梯值');\n"
            "if (o.series[0].markLine.data[0].yAxis !== 1) throw new Error('终值 markLine');\n"
            "if (!o.series[0].markPoint || "
            "o.series[0].markPoint.data[0][1] !== 2) throw new Error('末点');\n"
            "const o2 = m.buildEChartOption("
            "[{ name: 'c', x: [5, 6, 7], y: [3, 1, 2] }], "
            "{ mode: 'convergence', xvalue: true }, theme);\n"
            "if (o2.series[0].markPoint.data[0][0] !== 7) "
            "throw new Error('xvalue 末点 coord 取 x 值');\n"
            "console.log('ok:convergence');\n"
        )
        assert "ok:convergence" in out


class TestMigrationSourcePins:
    """换壳迁移面源码钉（免 node）：调用点清点 + 声明增量点位。"""

    def _read(self, name: str) -> str:
        return (_STATIC / name).read_text(encoding="utf-8")

    def test_pages_js_call_sites_fully_migrated(self):
        src = self._read("pages.js")
        assert src.count("T.drawEChart(") == 0, "仍有未迁移的 drawEChart 调用点"
        # 11 处迁移（规格写 12 系含定义/导出行的历史口径）+ 1 处新增
        # （run 对比叠图 renderRunDiff）= 12
        assert src.count("T.plotCard(") == 12, src.count("T.plotCard(")

    def test_declared_option_deltas_pinned(self):
        src = self._read("pages.js")
        # crosshair：run 详情 + S 参数分文件 + S 参数叠加 + run 对比叠图 = 4
        assert src.count("crosshair: true") == 4
        # convergence：调参 trial 收敛 + 时间线调参收敛 = 2
        assert src.count('mode: "convergence"') == 2

    def test_app_js_single_source_wiring(self):
        app = self._read("app.js")
        assert 'from "./plotcard.js"' in app
        assert "buildEChartOption" in app
        assert "plotCard: uiPlotCard" in app  # initPages 工具面注入
        # a11y 钉兼容：容器语义留在 app.js 壳（test_ui_a11y_theme 消费）
        assert 'el.setAttribute("role", "img")' in app
        assert 'setAttribute("aria-label", opts.ariaLabel' in app

    def test_plotcard_exports_and_export_paths(self):
        src = self._read("plotcard.js")
        for needle in (
            "export function buildEChartOption",
            "export function bestSoFar",
            "export function toCsv",
            "export function plotCardOption",
            "export function plotCard",
            "getDataURL",  # PNG 导出
            "plotcard error: ${esc(e.message)}",  # 故障可见化（esc 单源）
        ):
            assert needle in src, needle

    def test_index_html_print_face(self):
        src = self._read("index.html")
        m = re.search(r"@media print\s*\{(.*?)\n  \}", src, re.S)
        assert m, "@media print 块丢失"
        block = m.group(1)
        for needle in (
            "aside", "plotcard-tools", "report-toc",  # 隐导航/工具/TOC
            "break-inside:avoid", "page-break-inside:avoid",  # 防跨页截断
            "background:#fff",  # 强制白底
        ):
            assert needle in block, f"print 面缺 {needle}"
