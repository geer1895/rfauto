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
  W3-S12（aurora_e，R6 审计 P-5）+4：远场极坐标/Smith/场切片/远场 3D 热图
  四管线经 props.option 逃生舱接入壳（TestOptionEscapeHatch 钉 gated 语义：
  直通/ctx 现取/base 逐字节不变），全站调用点 12→16。
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
  "band_series": "{\"backgroundColor\":\"transparent\",\"color\":[\"#4fc3f7\",\"#ffb74d\",\"#81c784\",\"#e57373\",\"#ba68c8\"],\"tooltip\":{\"trigger\":\"item\"},\"legend\":{\"top\":0,\"textStyle\":{\"color\":\"#dce3ee\"},\"type\":\"scroll\"},\"grid\":{\"left\":52,\"right\":20,\"top\":34,\"bottom\":44},\"xAxis\":{\"type\":\"value\",\"scale\":true,\"axisLine\":{\"lineStyle\":{\"color\":\"#5f6a80\"}},\"axisLabel\":{\"color\":\"#8391a7\"},\"splitLine\":{\"lineStyle\":{\"color\":\"#1c2331\"}},\"name\":\"x\",\"nameTextStyle\":{\"color\":\"#dce3ee\"}},\"yAxis\":{\"type\":\"value\",\"scale\":true,\"axisLine\":{\"lineStyle\":{\"color\":\"#5f6a80\"}},\"axisLabel\":{\"color\":\"#8391a7\"},\"splitLine\":{\"lineStyle\":{\"color\":\"#1c2331\"}},\"name\":\"y\",\"nameTextStyle\":{\"color\":\"#dce3ee\"}},\"dataZoom\":[{\"type\":\"inside\"},{\"type\":\"slider\",\"height\":18,\"bottom\":6}],\"series\":[{\"name\":\"mean\",\"type\":\"line\",\"data\":[[1,1],[2,2],[3,3]],\"showSymbol\":false,\"lineStyle\":{\"width\":1.6},\"itemStyle\":{}},{\"type\":\"line\",\"stack\":\"band-f4bipx\",\"data\":[[1,0.5],[2,1.5],[3,2.5]],\"showSymbol\":false,\"silent\":true,\"lineStyle\":{\"opacity\":0},\"emphasis\":{\"disabled\":true},\"tooltip\":{\"show\":false}},{\"name\":\"±1σ\",\"type\":\"line\",\"stack\":\"band-f4bipx\",\"data\":[[1,1],[2,1],[3,1]],\"showSymbol\":false,\"silent\":true,\"lineStyle\":{\"opacity\":0},\"emphasis\":{\"disabled\":true},\"areaStyle\":{\"color\":\"#0277bd\",\"opacity\":0.18},\"tooltip\":{\"show\":false}}]}",
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
# aurora_j W1-S1（2026-10-23）：band_series 案例含 xvalue+等长 x/y 的 line+band
# 组合，命中新增的值轴 [x,y] 对门——该条期望值按新门再生（mean/带线 data 变
# [x,y] 对）；其余四案例（line_category/band_marks/empty_series=category base
# 路径 + scatter_xvalue=散点分支未动）逐字节未动——"门不满足路径=base 等价"
# 的机器口径不变。
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
            "o.series[0].markPoint.data[0].coord[1] !== 2 || "
            "o.series[0].markPoint.data[0].value !== 2) throw new Error('末点');\n"
            "const o2 = m.buildEChartOption("
            "[{ name: 'c', x: [5, 6, 7], y: [3, 1, 2] }], "
            "{ mode: 'convergence', xvalue: true }, theme);\n"
            "if (o2.series[0].markPoint.data[0].coord[0] !== 7) "
            "throw new Error('xvalue 末点 coord 取 x 值');\n"
            "console.log('ok:convergence');\n"
        )
        assert "ok:convergence" in out


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestXvalueLineValueAxis:
    """aurora_j W1-S1（双引擎叠加图异栅根治）：xvalue 值轴下 line 族
    [x,y] 对数据。

    双引擎可信度对照（cred_curves）两引擎 freq_ghz 频网点数/间距可不同——
    category 轴按索引共享 series[0].x 会把第二引擎按索引拉伸错位。值轴下
    每条迹线自持 [x,y] 网（散点 data=[[x,y]] 先例同构）；门不满足/
    convergence 组合的路径逐字节现状（golden 钉不变）。"""

    def test_xvalue_line_pairs_per_trace_grids(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, palette: ['#4fc3f7'] };\n"
            "// 异栅两迹线：hfss 3 点 / openems 4 点（频网不同）\n"
            "const o = m.buildEChartOption([\n"
            "  { name: 'HFSS·S11', x: [2.0, 2.4, 2.8], y: [-1, -12, -2] },\n"
            "  { name: 'openEMS·S11', x: [2.0, 2.2, 2.4, 2.8],\n"
            "    y: [-1.1, -6, -13, -2.1] },\n"
            "], { xvalue: true, xlabel: 'GHz', ylabel: 'dB' }, theme);\n"
            "const errs = [];\n"
            "if (o.xAxis.type !== 'value') errs.push('xAxis 应值轴');\n"
            "if (o.tooltip.trigger !== 'item') errs.push('tooltip 应 item');\n"
            "if (JSON.stringify(o.series[0].data) !== "
            "JSON.stringify([[2, -1], [2.4, -12], [2.8, -2]])) "
            "errs.push('迹线1 对数据: ' + JSON.stringify(o.series[0].data));\n"
            "if (JSON.stringify(o.series[1].data) !== "
            "JSON.stringify([[2, -1.1], [2.2, -6], [2.4, -13], [2.8, -2.1]])) "
            "errs.push('迹线2 对数据: ' + JSON.stringify(o.series[1].data));\n"
            "// 各迹线自持频网（第二引擎不被拉伸到首迹线索引集）\n"
            "if (o.series[1].data.length !== 4) errs.push('异栅点数应各自保留');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:xy-pairs');\n"
        )
        assert "ok:xy-pairs" in out

    def test_xvalue_fallback_paths_unchanged(self):
        # 门不满足（无 x / 长度不齐）与 convergence+xvalue 组合（明确不支持）
        # → data 仍=原 y（同引用直通，逐字节现状；golden 钉口径）
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, palette: ['#4fc3f7'] };\n"
            "const errs = [];\n"
            "const yA = [1, 2, 3];\n"
            "const o1 = m.buildEChartOption([{ name: 'a', y: yA }], "
            "{ xvalue: true }, theme);\n"
            "if (o1.series[0].data !== yA) errs.push('无 x 应原样 y');\n"
            "const yB = [1, 2, 3];\n"
            "const o2 = m.buildEChartOption("
            "[{ name: 'b', x: [1, 2], y: yB }], { xvalue: true }, theme);\n"
            "if (o2.series[0].data !== yB) errs.push('长度不齐应原样 y');\n"
            "const yC = [3, 1, 2];\n"
            "const o3 = m.buildEChartOption("
            "[{ name: 'c', x: [5, 6, 7], y: yC }], "
            "{ mode: 'convergence', xvalue: true }, theme);\n"
            "if (o3.series[0].data !== yC) errs.push('convergence 组合应原样 y');\n"
            "if (o3.series[0].markPoint.data[0].coord[0] !== 7) "
            "errs.push('convergence 末点 coord 现状应保持');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:fallback');\n"
        )
        assert "ok:fallback" in out

    def test_xvalue_band_pairs_align_with_line(self):
        # 值轴下带线与同图 line 族同门出 [x,·] 对（否则均值线落真 x 而带线
        # 落 0..n-1 索引，带与线错位）；两 stack 线共用同一 s.x。
        out = _run_node_js(
            "Math.random = () => 0.42;\n"
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, palette: ['#4fc3f7'] };\n"
            "const o = m.buildEChartOption([\n"
            "  { name: 'mean', x: [1, 2, 3], y: [1, 2, 3] },\n"
            "  { name: '±1σ', type: 'band', x: [1, 2, 3], color: '#0277bd',\n"
            "    lower: [0.5, 1.5, 2.5], upper: [1.5, 2.5, 3.5] },\n"
            "], { xvalue: true }, theme);\n"
            "const errs = [];\n"
            "if (JSON.stringify(o.series[1].data) !== "
            "JSON.stringify([[1, 0.5], [2, 1.5], [3, 2.5]])) "
            "errs.push('带下沿线应对数据: ' + JSON.stringify(o.series[1].data));\n"
            "if (JSON.stringify(o.series[2].data) !== "
            "JSON.stringify([[1, 1], [2, 1], [3, 1]])) "
            "errs.push('带差值线应对数据: ' + JSON.stringify(o.series[2].data));\n"
            "// 非 xvalue 路径带线现状（plain 数组）\n"
            "const o2 = m.buildEChartOption([\n"
            "  { name: 'b', type: 'band', x: [1, 2, 3],\n"
            "    lower: [0.5, 1.5, 2.5], upper: [1.5, 2.5, 3.5] },\n"
            "], {}, theme);\n"
            "if (JSON.stringify(o2.series[0].data) !== "
            "JSON.stringify([0.5, 1.5, 2.5])) errs.push('非值轴带线应现状');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:band-pairs');\n"
        )
        assert "ok:band-pairs" in out

    def test_xvalue_pairs_render_in_echarts_ssr(self):
        # 渲染级冒烟：值轴 [x,y] 对线族+带经 vendored echarts SSR 满管线
        # setOption 不抛、无 NaN（形态层 JSON 断言抓不到的渲染期故障）。
        out = _run_node_js(
            "const req = (await import('node:module')).createRequire("
            "process.cwd() + '/plotcard.js');\n"
            "const echarts = req('./vendor/echarts.min.js');\n"
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, palette: ['#4fc3f7', '#0277bd'] };\n"
            "const o = m.buildEChartOption([\n"
            "  { name: 'HFSS', x: [2.0, 2.4, 2.8], y: [-1, -12, -2] },\n"
            "  { name: 'openEMS', x: [2.0, 2.2, 2.4, 2.8], "
            "y: [-1.1, -6, -13, -2.1] },\n"
            "  { name: '±1σ', type: 'band', x: [2.0, 2.2, 2.4, 2.8], "
            "lower: [-2, -7, -14, -3], upper: [0, -5, -12, -1] },\n"
            "], { xvalue: true, xlabel: 'GHz', ylabel: 'dB' }, theme);\n"
            "const c = echarts.init(null, null, "
            "{ renderer: 'svg', ssr: true, width: 600, height: 300 });\n"
            "try {\n"
            "  c.setOption(o);\n"
            "  const svg = c.renderToSVGString();\n"
            "  if (svg.includes('NaN')) console.log('BAD: svg 含 NaN');\n"
            "  else console.log('ok:ssr-xy-pairs');\n"
            "} catch (e) { console.log('BAD: ' + e.message); }\n"
            "process.exit(0);\n"
        )
        assert out.strip().startswith("ok:"), out

    def test_xvalue_skips_downsample_unless_max_points(self):
        # 接缝语义：xvalue 整跳分组降采样（值轴异栅下共享索引集抽稀不适用；
        # cred 曲线 201/401 点量级无需降采样）；显式 maxPoints 仍最高优先。
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const n = 5000;\n"
            "const xs = Array.from({ length: n }, (_, i) => i / 10);\n"
            "const ys = xs.map((x) => Math.sin(x / 30));\n"
            "const o1 = m.plotCardOption({ series: [{ name: 'a', x: xs, "
            "y: ys }], xvalue: true }, {});\n"
            "const o2 = m.plotCardOption({ series: [{ name: 'a', x: xs, "
            "y: ys }], xvalue: true, maxPoints: 300 }, {});\n"
            "console.log(JSON.stringify({ xv: o1.series[0].data.length, "
            "ovr: o2.series[0].data.length }));\n"
        )
        payload = json.loads(out.strip())
        assert payload["xv"] == 5000  # xvalue 整跳
        assert 300 <= payload["ovr"] <= 302  # 显式覆盖仍生效


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestDataTableAssembly:
    """aurora_j W3-S9（echarts 数据表文本替代，a11y W5-S23 建议④）：
    buildDataTable 宽/长两态组装纯函数 + toCsv 单源委托（表格≡CSV 导出）。

    形态选择：共享 x 网 → 宽表（列=系列名，行=共享索引对齐）；散点
    [[x,y]] 或异栅 x 网（xvalue 双引擎频网点数/间距可不同）→ 长表
    [series,x,y]（各系列 x 逐点保留不失真）；band 是合成阴影带不进表；
    零系列 → headers=[] 空态（DOM 侧渲染 i18n 空提示）。"""

    def test_build_data_table_wide_shared_grid(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const d = m.buildDataTable([\n"
            "  { name: 'S11', x: ['1', '2'], y: [1, 2] },\n"
            "  { name: 'S21', x: ['1', '2'], y: [3, 4] },\n"
            "]);\n"
            "if (JSON.stringify(d.headers) !== JSON.stringify(['x', 'S11', 'S21'])) "
            "throw new Error('headers: ' + JSON.stringify(d.headers));\n"
            "if (JSON.stringify(d.rows) !== "
            "JSON.stringify([['1', 1, 3], ['2', 2, 4]])) "
            "throw new Error('rows: ' + JSON.stringify(d.rows));\n"
            "console.log('ok:dt-wide');\n"
        )
        assert "ok:dt-wide" in out

    def test_build_data_table_long_scatter_and_uneven_grids(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const errs = [];\n"
            "// 散点 [[x,y]] → 长表\n"
            "const d1 = m.buildDataTable([{ name: 'p', data: [[1, 2], [3, 4]] }]);\n"
            "if (JSON.stringify(d1.headers) !== JSON.stringify(['series', 'x', 'y'])) "
            "errs.push('散点 headers');\n"
            "if (JSON.stringify(d1.rows) !== "
            "JSON.stringify([['p', 1, 2], ['p', 3, 4]])) errs.push('散点 rows');\n"
            "// 异栅（xvalue 双引擎频网不齐）→ 长表，各系列 x 逐点保留\n"
            "const d2 = m.buildDataTable([\n"
            "  { name: 'hfss', x: [2.0, 2.4, 2.8], y: [-1, -12, -2] },\n"
            "  { name: 'openems', x: [2.0, 2.2, 2.4, 2.8], y: [-1.1, -6, -13, -2.1] },\n"
            "]);\n"
            "if (d2.headers[0] !== 'series') errs.push('异栅应转长表');\n"
            "if (d2.rows.length !== 7) errs.push('异栅行数=' + d2.rows.length);\n"
            "if (JSON.stringify(d2.rows[4]) !== JSON.stringify(['openems', 2.2, -6])) "
            "errs.push('第二引擎自有频点保留: ' + JSON.stringify(d2.rows[4]));\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:dt-long');\n"
        )
        assert "ok:dt-long" in out

    def test_build_data_table_band_excluded_and_empty(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const errs = [];\n"
            "// band 不进表（与 toCsv 同口径）\n"
            "const d1 = m.buildDataTable([\n"
            "  { name: 'mean', x: [1], y: [1] },\n"
            "  { name: '±1σ', type: 'band', x: [1], lower: [0], upper: [2] },\n"
            "]);\n"
            "if (d1.headers.length !== 2 || d1.rows.length !== 1) "
            "errs.push('band 应排除');\n"
            "// 零系列/全 band → 空态\n"
            "if (JSON.stringify(m.buildDataTable([])) !== "
            "JSON.stringify({ headers: [], rows: [] })) errs.push('空数组');\n"
            "if (m.buildDataTable("
            "[{ type: 'band', x: [1], lower: [0], upper: [1] }]).headers.length !== 0) "
            "errs.push('全 band 应空态');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:dt-empty');\n"
        )
        assert "ok:dt-empty" in out

    def test_to_csv_delegates_to_build_data_table(self):
        # toCsv 消费 buildDataTable（宽/长分派单源）：同输入下 CSV 行集
        # = headers+rows 的引号平铺（表格与导出永一致的机器口径）。
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const errs = [];\n"
            "const wide = [{ name: 'a', x: ['1', '2'], y: [1, 2] }, "
            "{ name: 'b', x: ['1', '2'], y: [3, 4] }];\n"
            "const d = m.buildDataTable(wide);\n"
            "const q = (v) => { const s = v == null ? '' : String(v); "
            "return /[\",\\n]/.test(s) ? '\"' + s.replace(/\"/g, '\"\"') + '\"' : s; };\n"
            "const expect = [d.headers, ...d.rows].map((r) => r.map(q).join(','))"
            ".join('\\r\\n');\n"
            "if (m.toCsv(wide) !== expect) errs.push('宽表不一致');\n"
            "// 引号转义面行为现状保持（既有钉同款案例）\n"
            "const qd = m.toCsv([{ name: 'x\"y,z', x: ['a'], y: [1] }]);\n"
            "if (!qd.includes('\"x\"\"y,z\"')) errs.push('quoting');\n"
            "if (m.toCsv([{ type: 'band', x: [1], lower: [0], upper: [1] }]) !== '') "
            "errs.push('band 不导出');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:dt-csv');\n"
        )
        assert "ok:dt-csv" in out

    def test_crosshair_xvalue_combination_option(self):
        # W3-S9：crosshair+xvalue 组合 option 钉（数值读数类消费面的确切
        # 形态——cred 对照卡/扫参/收敛/校准/前沿六处开启的组合）：tooltip
        # trigger=item（xvalue 值轴语义不变）+ axisPointer.type=cross 同体
        # 共存；缺省仍不带 cross（既有 gated 钉口径不变）。
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, palette: ['#4fc3f7'] };\n"
            "const o = m.buildEChartOption(\n"
            "  [{ name: 'HFSS', x: [2.0, 2.4], y: [-1, -12] },\n"
            "   { name: 'openEMS', x: [2.0, 2.2, 2.4], y: [-1.1, -6, -13] }],\n"
            "  { xvalue: true, crosshair: true, xlabel: 'GHz', ylabel: 'dB' }, theme);\n"
            "const errs = [];\n"
            "if (o.tooltip.trigger !== 'item') errs.push('trigger 应保持 item');\n"
            "if (o.tooltip.axisPointer.type !== 'cross') errs.push('应带 cross');\n"
            "if (o.xAxis.type !== 'value') errs.push('xAxis 应值轴');\n"
            "// 非 xvalue（category 轴）+ crosshair 组合同样合法（tl-cost 形态）\n"
            "const o2 = m.buildEChartOption([{ name: 'a', x: ['t1'], y: [1] }], "
            "{ crosshair: true }, theme);\n"
            "if (o2.tooltip.trigger !== 'axis' || "
            "o2.tooltip.axisPointer.type !== 'cross') errs.push('category+cross');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:cross-value');\n"
        )
        assert "ok:cross-value" in out


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestOptionEscapeHatch:
    """W3-S12（R6 审计 P-5）：props.option 逃生舱（gated 纯增量）。

    非笛卡尔管线（polar/Smith/custom/heatmap）自带完整 option 直通接入
    plotCard 壳；不传 option 的调用路径逐字节不变（base 金钉不受扰）。"""

    def test_option_passthrough_object_and_function(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, palette: ['#4fc3f7'] };\n"
            "const custom = { backgroundColor: 'transparent', polar: {}, series: [{ type: 'line', coordinateSystem: 'polar' }] };\n"
            "const a = m.plotCardOption({ option: custom }, theme);\n"
            "if (a !== custom) throw new Error('对象形态须同引用直通');\n"
            "let seen = null;\n"
            "const fn = (ctx) => { seen = ctx; return custom; };\n"
            "const b = m.plotCardOption({ option: fn }, theme);\n"
            "if (b !== custom || seen !== theme) throw new Error('函数形态须以 ctx 现取');\n"
            "console.log('ok:option-passthrough');\n"
        )
        assert "ok:option-passthrough" in out

    def test_option_mode_skips_series_consumption(self):
        # option 直通优先：series 缺席/畸形不进降采样与 base 构造（CSV 数据面
        # 与渲染 option 解耦——四管线 series 只喂 toCsv）
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, palette: [] };\n"
            "const o = m.plotCardOption({ option: { series: [{ type: 'heatmap' }] } }, theme);\n"
            "if (o.series[0].type !== 'heatmap') throw new Error('直通被改写');\n"
            "console.log('ok:option-no-series');\n"
        )
        assert "ok:option-no-series" in out

    def test_base_path_byte_identical_when_option_absent(self):
        # 不传 option：plotCardOption 走 base 单源构造，输出与迁移前 golden
        # 快照逐字节相等（逃生舱 gated 纯增量的直接证据）
        out = _run_node_js(
            "Math.random = () => 0.42;\n"
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, "
            "palette: ['#4fc3f7', '#ffb74d', '#81c784', '#e57373', '#ba68c8'] };\n"
            + _CASES_JS +
            "const out = {};\n"
            "for (const [k, c] of Object.entries(cases)) {\n"
            "  const p = Object.assign({}, c.opts, { series: c.series });\n"
            "  out[k] = JSON.stringify(m.plotCardOption(p, theme));\n"
            "}\n"
            "console.log(JSON.stringify(out));\n"
        )
        got = json.loads(out.strip())
        assert got == _GOLDEN


class TestMigrationSourcePins:
    """换壳迁移面源码钉（免 node）：调用点清点 + 声明增量点位。"""

    def _read(self, name: str) -> str:
        if name == "pages.js":  # UI-R2：入口+域模块并集读（行为断言不变）
            parts = [_STATIC / name, *sorted((_STATIC / "pages").glob("*.js"))]
            return "\n".join(p.read_text(encoding="utf-8") for p in parts)
        return (_STATIC / name).read_text(encoding="utf-8")

    def test_pages_js_call_sites_fully_migrated(self):
        src = self._read("pages.js")
        assert src.count("T.drawEChart(") == 0, "仍有未迁移的 drawEChart 调用点"
        # 11 处迁移（规格写 12 系含定义/导出行的历史口径）+ 1 处新增
        # （run 对比叠图 renderRunDiff）+ 4 处 W3-S12 逃生舱迁移（远场极坐标/
        # Smith/场切片/远场 3D 热图，props.option 直通）= 16
        # + 2 处 aurora_i W3-S2（画廊抽屉对照曲线节 renderCredCurvesInto +
        # S 参数页对照卡 sp-chart-compare，cred_curves 数据面同源）= 18
        assert src.count("T.plotCard(") == 18, src.count("T.plotCard(")

    def test_declared_option_deltas_pinned(self):
        src = self._read("pages.js")
        # crosshair：run 详情 + S 参数分文件 + S 参数叠加 + run 对比叠图 = 4
        # + 2 处 aurora_i W3-S2（画廊对照曲线节 + S 参数页对照卡）= 6
        # + 6 处 aurora_j W3-S9（数值读数类开十字线：playground 扫参 +
        # timeline 成本/收敛 + calibration ρ 演化/散点 + optstack 前沿）
        assert src.count("crosshair: true") == 12
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
            "export function buildDataTable",
            "export function toCsv",
            "export function plotCardOption",
            "export function plotCard",
            "plotcard error: ${esc(e.message)}",  # 故障可见化（esc 单源）
        ):
            assert needle in src, needle
        # UI-R5：PNG/SVG 编码面收编 chart_export.js 统一出口（getDataURL/SSR
        # 矢量重渲染），文件名规范 `视图_指标_时间戳` 单源在彼处
        ce = (_STATIC / "chart_export.js").read_text(encoding="utf-8")
        for needle in ("getDataURL", "renderToSVGString", "exportStampName"):
            assert needle in ce, needle

    def test_downsample_exports_and_default_threshold(self):
        # UI-R5：降采样算法/阈值面导出（plotcard 单源实现）
        src = self._read("plotcard.js")
        for needle in (
            "export function minmaxIndices",
            "export function lttbIndices",
            "export function downsamplePlotSeries",
            "export const DEFAULT_MAX_POINTS",
            "export function setDefaultMaxPoints",
        ):
            assert needle in src, needle

    def test_data_table_face_wiring(self):
        # aurora_j W3-S9：数据表文本替代面——buildDataTable 组装单源 +
        # 工具条切换钮（kit 按钮同款类名 + aria-expanded 开合态）+ 表
        # aria-label/空态提示走 i18n 词表 + 全动态值 esc/escAttr 转义
        # （系列名/坐标=外部数据面，XSS 红线）；默认收起（hidden 起步）。
        src = self._read("plotcard.js")
        for needle in (
            "_renderDataTable",
            'dtBtn.className = "minor plotcard-btn";',
            'dtBtn.textContent = t("common.data_table");',
            'dtBtn.title = t("common.data_table_title");',
            'dtBtn.setAttribute("aria-expanded", "false");',
            "dtWrap.hidden = true;",
            'if (show) _renderDataTable(dtWrap, shell.props.series);',
            "if (prevShell.dtWrap && !prevShell.dtWrap.hidden)",
            '<table aria-label="${escAttr(t("common.data_table_caption"))}">',
            'esc(t("common.data_table_empty"))',
            "<th scope=\"col\">${esc(h)}</th>",
            "<td>${esc(v)}</td>",
        ):
            assert needle in src, needle
        # toCsv 委托 buildDataTable（表格≡CSV 导出，宽/长分派单源）
        assert "const { headers, rows } = buildDataTable(series);" in src

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


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestConvergenceRenderRegression:
    """W9-A 渲染级回归钉（2026-10-12，W8-B 视觉验收 P1-1）。

    convergence 模式 markPoint.data 曾用裸 ``[x, y]`` 数组项：echarts 5.6 的
    marker 归一化（emphasis/label 拷贝）把它当"子项列表"展开，对数字基元
    （末点索引 N）做 ``.label`` 赋值 → 严格模式 TypeError
    "Cannot create property 'label' on number 'N'"，setOption 整体失败，
    tune 收敛图降级为错误文案。该故障只在**渲染期**暴露——option 构造层
    （TestIncrementBehavior 的 JSON 断言）抓不到，故本类经 vendored echarts
    SSR（ssr:true + svg，无 DOM 依赖）跑满 setOption+布局管线。
    修复形态 = ``{value, coord: [x, y]}``（value 显式给出：coord 项不回填
    params.value，末点标注 formatter 会渲染 "NaN"，SSR 实测）。
    注意：echarts SSR 在 node 里挂常驻定时器，JS 末尾必须 process.exit，
    否则 subprocess 60s 超时（本席实测）。"""

    def test_convergence_option_renders_in_echarts_ssr(self):
        out = _run_node_js(
            "const req = (await import('node:module')).createRequire("
            "process.cwd() + '/plotcard.js');\n"
            "const echarts = req('./vendor/echarts.min.js');\n"
            "const m = await import('./plotcard.js');\n"
            "const theme = { light: false, palette: ['#4fc3f7'] };\n"
            "const ys = [3.9, 2.5, 2.1, 1.8, 1.7, 1.6, 1.5, 1.45, 1.4, 1.38, "
            "1.36, 1.34, 1.33, 1.32, 1.31];\n"
            "const o = m.buildEChartOption("
            "[{ name: 'cost', x: [...Array(15).keys()], y: ys }], "
            "{ mode: 'convergence', xlabel: 'trial', ylabel: 'cost' }, theme);\n"
            "const item = o.series[0].markPoint && o.series[0].markPoint.data[0];\n"
            "if (!item || !item.coord || item.coord[1] !== 1.31 || item.value !== 1.31) {\n"
            "  console.log('BAD: markPoint 项形态（需 {value, coord:[x,y]}）');\n"
            "  process.exit(0);\n"
            "}\n"
            "const c = echarts.init(null, null, "
            "{ renderer: 'svg', ssr: true, width: 600, height: 220 });\n"
            "try {\n"
            "  c.setOption(o);\n"
            "  const svg = c.renderToSVGString();\n"
            "  if (svg.includes('NaN')) { console.log('BAD: svg 含 NaN 标注'); }\n"
            "  else if (!svg.includes('1.310')) { console.log('BAD: 缺末点标注 1.310'); }\n"
            "  else console.log('ok:ssr-convergence');\n"
            "} catch (e) { console.log('BAD: ' + e.message); }\n"
            "process.exit(0);\n"
        )
        assert out.strip().startswith("ok:"), out
