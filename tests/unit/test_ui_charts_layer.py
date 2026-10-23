"""aurora_d UI-R5 图表能力统一深化回归钉（2026-10-14）。

对象：static/plotcard.js + static/chart_export.js（新，根位与 plotcard.js
同层）+ static/pages/charts.js + pages.js 接线 + view_detail/view_fieldviz
工厂消费点。四块：

1. **降采样保形（node 真执行，缺 node skip）**：min-max 包络抽稀
   （minmaxIndices=保形默认档）基线 + downsamplePlotSeries 合成 S 参数型
   曲线（20001 点三谷一峰）**特征峰/谷位置与数值逐位保持** + 首末点/单调/
   预算上界 + 共享 x 网多迹线同索引集 + band 随组抽 + convergence 整跳 +
   props.maxPoints 覆盖 + setDefaultMaxPoints 往返 + plotCardOption 接缝
   （buildEChartOption 不动——golden 钉在 test_ui_plotcard 不受扰）；
   LTTB 对照（感知档会整桶错过次深谷——保形默认选 min-max 的实证）。
2. **导出统一（node+源码）**：exportStampName 文件名规范
   `视图_指标_YYYYMMDD_HHMMSS.<ext>`（消毒/缺省兜底/时间注入）；
   chartToSvgText 经 vendored echarts SSR 出**矢量** SVG（守卫：缺 echarts/
   已弃置返 null）；plotCard 与 chartExportTools 双装配面走统一出口（源码钉）。
3. **主题联动（node+源码）**：refreshThemeCharts 对存活 plotCard 壳以新档
   重放 option（notMerge+chartPalette 深档）+ 同档零动作去重 + 弃置壳跳过；
   MutationObserver 盯 body.light 在 initPages 装配一次（源码钉）。
4. **调用面归一（源码）**：plotCardCached=零破坏薄委托（单行 T.plotCard）；
   plotCard 内建同容器复用守卫（plotcard.js，W2-B 接口诉求闭合）；绘参选项
   工厂（sparamChartProps/smithChartTheme/heatColormap）在 charts 层且有
   真实消费点；计数复述（T.plotCard==12 等，跨席钉同源）。

不依赖 runs/、不读网络、不启动服务器；不 commit。
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


def _read(name: str) -> str:
    if name == "pages.js":  # 入口+域模块并集（UI-R2 拆分读法）
        parts = [_STATIC / name, *sorted((_STATIC / "pages").glob("*.js"))]
        return "\n".join(p.read_text(encoding="utf-8") for p in parts)
    return (_STATIC / name).read_text(encoding="utf-8")


def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2000:]}"
    return r.stdout


# ────────────────────────── 1. 降采样保形（node） ──────────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestDownsampleShape:
    """min-max 包络抽稀保形钉：特征峰/谷位置与数值逐位保持。"""

    _JS = """
const m = await import('./plotcard.js');
const N = 20001;
const xs = Array.from({ length: N }, (_, i) => 1 + (i * 9) / (N - 1));
const g = (f, f0, w) => Math.exp(-((f - f0) * (f - f0)) / (w * w));
// 三谷一峰：2.4/5.1/8.2 GHz 谷（宽 7-11 样本）+ 3.3 GHz 峰
const ys = xs.map((f) =>
  -2 + 0.4 * Math.sin(f * 6) - 38 * g(f, 2.4, 0.004)
       - 25 * g(f, 5.1, 0.005) - 31 * g(f, 8.2, 0.003) + 12 * g(f, 3.3, 0.004));
const featIdx = [2.4, 5.1, 8.2, 3.3].map((f0) => {
  let best = 0;
  for (let i = 1; i < N; i++) if (Math.abs(xs[i] - f0) < Math.abs(xs[best] - f0)) best = i;
  return best;
});
const CAP = 2000;
const ds = m.downsamplePlotSeries([{ name: 'S11', x: xs, y: ys }], CAP)[0];
const featOk = featIdx.map((i) =>
  ds.y.includes(ys[i]) && ds.x[ds.y.indexOf(ys[i])] === xs[i]);
const checks = {
  size: ds.y.length <= CAP + 2,
  feat: featOk.every(Boolean),
  ends: ds.x[0] === xs[0] && ds.x[ds.x.length - 1] === xs[xs.length - 1],
  mono: ds.y.every((_, i) => i === 0 || ds.x[i] > ds.x[i - 1]),
};
console.log('DS:' + JSON.stringify({ checks, n: ds.y.length, featOk }));
// LTTB 对照：感知档对次深谷的保形缺口（默认档选 min-max 的实证）
const lttb = m.lttbIndices(ys, CAP);
console.log('LTTB-Feat:' + JSON.stringify(featIdx.map((i) => lttb.includes(i))));
console.log('MM-Baseline:' + JSON.stringify(m.minmaxIndices([5, 1, 9, 2, 8, 0, 3, 7, 4, 6], 6)));
"""

    def test_minmax_preserves_feature_peaks_and_valleys(self):
        out = _run_node_js(self._JS)
        ds_line = next(ln for ln in out.splitlines() if ln.startswith("DS:"))
        payload = json.loads(ds_line[3:])
        assert payload["checks"] == {
            "size": True, "feat": True, "ends": True, "mono": True,
        }, payload
        assert payload["n"] <= 2002

    def test_lttb_comparison_misses_secondary_valleys(self):
        # 对照钉：纯 LTTB 至少漏一个次深谷（min-max 全保）——保形默认档选型实证
        out = _run_node_js(self._JS)
        lttb = json.loads(next(
            ln for ln in out.splitlines()
            if ln.startswith("LTTB-Feat:")).split(":", 1)[1])
        mm = json.loads(next(
            ln for ln in out.splitlines()
            if ln.startswith("MM-Baseline:")).split(":", 1)[1])
        assert not all(lttb), f"LTTB 应至少漏一个特征（对照失真?）: {lttb}"
        assert mm == [0, 1, 2, 4, 5, 6, 7, 9]

    def test_shared_grid_multi_series_same_index_set(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const n = 9000;\n"
            "const xs = Array.from({ length: n }, (_, i) => i / 10);\n"
            "const mk = (a, b, f0) => xs.map((x) => a - b * "
            "Math.exp(-((x - f0) * (x - f0)) / 0.0004));\n"
            "const ss = [{ name: 'S11', x: xs, y: mk(-3, 30, 2.4) }, "
            "{ name: 'S21', x: xs, y: mk(-6, 20, 5.1) }, "
            "{ name: 'S22', x: xs, y: mk(-9, 25, 8.2) }];\n"
            "const ds = m.downsamplePlotSeries(ss, 2000);\n"
            "const lenOk = ds.every((s) => s.y.length === ds[0].y.length);\n"
            "const gridOk = ds.every((s) => s.x[5] === ds[0].x[5] && "
            "s.x[s.x.length - 1] === ds[0].x[ds[0].x.length - 1]);\n"
            "// 各迹线特征（不同位置的谷）全保形\n"
            "const featOk = [[2.4, 0], [5.1, 1], [8.2, 2]].every(([f0, k]) => {\n"
            "  let bi = 0;\n"
            "  for (let i = 1; i < n; i++) if (Math.abs(xs[i] - f0) < "
            "Math.abs(xs[bi] - f0)) bi = i;\n"
            "  return ds[k].y.includes(ss[k].y[bi]);\n"
            "});\n"
            "console.log(JSON.stringify({ lenOk, gridOk, featOk, "
            "n: ds[0].y.length }));\n"
        )
        payload = json.loads(out.strip())
        assert payload["lenOk"] is True
        assert payload["gridOk"] is True
        assert payload["featOk"] is True
        assert payload["n"] <= 2000 + 6  # 上界 cap + 2·迹线数

    def test_band_and_scatter_semantics(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const n = 8000;\n"
            "const xs = Array.from({ length: n }, (_, i) => i);\n"
            "const ys = xs.map((x) => Math.sin(x / 40));\n"
            "const lo = ys.map((v) => v - 1), up = ys.map((v) => v + 1);\n"
            "const scatter = { name: 'pts', type: 'scatter', "
            "data: xs.slice(0, 50).map((x) => [x, ys[x]]) };\n"
            "const ds = m.downsamplePlotSeries([\n"
            "  { name: 'mean', x: xs, y: ys },\n"
            "  { name: 'b', type: 'band', x: xs, lower: lo, upper: up },\n"
            "  scatter,\n"
            "], 2000);\n"
            "// band 与 mean 同索引集；scatter 原样不参与\n"
            "const sync = ds[1].x.length === ds[0].y.length &&\n"
            "  ds[1].lower.length === ds[0].y.length;\n"
            "console.log(JSON.stringify({ sync, scatterKept: "
            "ds[2].data.length === 50, n: ds[0].y.length }));\n"
        )
        payload = json.loads(out.strip())
        assert payload["sync"] is True
        assert payload["scatterKept"] is True

    def test_convergence_skip_and_threshold_config(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const n = 5000;\n"
            "const xs = Array.from({ length: n }, (_, i) => i);\n"
            "const ys = xs.map((x) => Math.sin(x / 30));\n"
            "const th = m.getDefaultMaxPoints();\n"
            "const o1 = m.plotCardOption({ series: [{ name: 'c', x: xs, "
            "y: ys }], mode: 'convergence' }, {});\n"
            "const o2 = m.plotCardOption({ series: [{ name: 'a', x: xs, "
            "y: ys }], maxPoints: 300 }, {});\n"
            "const set = m.setDefaultMaxPoints(500);\n"
            "const o3 = m.plotCardOption({ series: [{ name: 'a', x: xs, "
            "y: ys }] }, {});\n"
            "m.setDefaultMaxPoints(th); // 还原全站缺省\n"
            "console.log(JSON.stringify({ th, conv: o1.series[0].data.length, "
            "ovr: o2.series[0].data.length, set, "
            "def: o3.series[0].data.length }));\n"
        )
        payload = json.loads(out.strip())
        assert payload["th"] == 2000
        assert payload["conv"] == 5000  # convergence 整跳
        assert 300 <= payload["ovr"] <= 302  # 显式覆盖（min-max 上界 target+2）
        assert payload["set"] == 500
        assert 500 <= payload["def"] <= 502  # setDefaultMaxPoints 生效

    def test_below_threshold_is_noop(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "const s = [{ name: 'a', x: [1, 2, 3], y: [4, 5, 6] }];\n"
            "const ds = m.downsamplePlotSeries(s, 2000);\n"
            "console.log(JSON.stringify(ds[0].y) === JSON.stringify(s[0].y) && "
            "ds[0].x === s[0].x);\n"
        )
        assert json.loads(out.strip()) is True


# ────────────────────────── 2. 导出统一（node+源码） ──────────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestExportUnification:
    """文件名规范 `视图_指标_时间戳` + SVG 矢量出口（vendored echarts SSR）。"""

    def test_export_stamp_name_spec(self):
        out = _run_node_js(
            "const m = await import('./chart_export.js');\n"
            "const t = new Date(2026, 9, 14, 15, 30, 45);\n"
            "const a = m.exportStampName('sparams-S11', 'csv', t);\n"
            "const b = m.exportStampName('run sparams/S11?', 'png', t);\n"
            "const c = m.exportStampName('', 'svg', t);\n"
            "const ok = a === 'sparams-S11_20261014_153045.csv' &&\n"
            "  b === 'run-sparams-S11_20261014_153045.png' &&\n"
            "  c === 'plotcard_20261014_153045.svg';\n"
            "console.log(JSON.stringify({ ok, a, b, c }));\n"
        )
        payload = json.loads(out.strip())
        assert payload["ok"] is True, payload

    def test_chart_to_svg_text_is_vector_via_ssr(self):
        out = _run_node_js(
            "const req = (await import('node:module')).createRequire("
            "process.cwd() + '/chart_export.js');\n"
            "const echarts = req('./vendor/echarts.min.js');\n"
            "globalThis.window = { echarts };\n"
            "const m = await import('./chart_export.js');\n"
            "const p = await import('./plotcard.js');\n"
            "const theme = { light: false, palette: ['#4fc3f7'] };\n"
            "const opt = p.buildEChartOption("
            "[{ name: 'S11', x: [1, 2, 3], y: [-1, -9, -4] }], "
            "{ xlabel: 'GHz', ylabel: 'dB', crosshair: true }, theme);\n"
            "const fake = { isDisposed: () => false, getWidth: () => 600, "
            "getHeight: () => 300, getOption: () => "
            "JSON.parse(JSON.stringify(opt)) };\n"
            "const svg = m.chartToSvgText(fake);\n"
            "const vector = svg.startsWith('<svg') && "
            "svg.includes('xmlns') && !svg.includes('<image');\n"
            "globalThis.window = {};\n"
            "const noEcs = m.chartToSvgText(fake);\n"
            "globalThis.window = { echarts };\n"
            "console.log(JSON.stringify({ vector, noEcs, bg: "
            "svg.includes('#0d1118') }));\n"
            "process.exit(0);\n"
        )
        payload = json.loads(out.strip())
        assert payload == {"vector": True, "noEcs": None, "bg": True}

    def test_svg_export_strips_script_segments(self):
        # UI-R11（uir8 P2-8 信息级→出口纵深防御）：SSR 产物出口剥 <script>
        # 段——正常 SVG 逐字节不变（echarts 不产 script，替换零触发）；含
        # script 的异常产物（闭合段/自闭合残段）剥离后返回，导出件喂给其他
        # 渲染器也不带脚本。echartsLike 注入免 vendored echarts。
        out = _run_node_js(
            "const m = await import('./chart_export.js');\n"
            "const fake = { isDisposed: () => false, getWidth: () => 600, "
            "getHeight: () => 300, getOption: () => ({}) };\n"
            "const ecs = (svg) => ({ init: () => ({ setOption() {}, "
            "renderToSVGString: () => svg, isDisposed: () => false, "
            "dispose() {} }) });\n"
            "const dirty = m.chartToSvgText(fake, ecs("
            "'<svg><rect/><script>alert(1)</script></svg>'));\n"
            "const unclosed = m.chartToSvgText(fake, ecs("
            "'<svg><rect/><script src=x onerror=y></svg>'));\n"
            "const cleanIn = '<svg><g><text>S11</text></g></svg>';\n"
            "const clean = m.chartToSvgText(fake, ecs(cleanIn));\n"
            "console.log(JSON.stringify({ dirty, unclosed, "
            "byteIdentical: clean === cleanIn }));\n"
        )
        p = json.loads(out.strip())
        assert p["dirty"] == "<svg><rect/></svg>"
        assert p["unclosed"] == "<svg><rect/></svg>"
        assert p["byteIdentical"] is True

    def test_unified_exit_wiring_source_pins(self):
        # plotCard 工具条与 chartExportTools 双装配面都走 chart_export 统一出口
        pc = _read("plotcard.js")
        ch = _read("pages/charts.js")
        ce = _read("chart_export.js")
        assert 'import { mkExportButtons } from "./chart_export.js";' in pc
        assert "mkExportButtons({" in pc
        assert "data-export-kind" in ce  # 钮标记（复用路径/定位单源）
        for needle in (
            "exportCsvText(", "exportChartFile(",
        ):
            assert needle in ch, needle
        assert 'from "../chart_export.js"' in ch
        assert "exportStampName(" in ce  # 命名单源在出口模块（ch 经出口间接消费）
        # 时间戳命名规范在出口单源（两装配面不再各自拼 name + ".csv"）
        assert 'name + ".csv"' not in ch
        assert "exportStampName(base, \"csv\")" in ce


# ────────────────────────── 3. 主题联动（node+源码） ──────────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestThemeLinkage:
    """四态切换 → body.light 翻转 → 存活 plotCard 壳重放新档配色。"""

    def test_refresh_replays_alive_shells_with_new_palette(self):
        out = _run_node_js(
            "const p = await import('./plotcard.js');\n"
            "const c = await import('./pages/charts.js');\n"
            "const el = {};\n"
            "const calls = [];\n"
            "const fakeChart = { isDisposed: () => false, getDom: () => ({}), "
            "setOption: (o, nm) => calls.push([o, nm]) };\n"
            "p.registerPlotCardShell(el, { chart: fakeChart, "
            "props: { series: [{ name: 'a', x: [1, 2], y: [3, 4] }] }, "
            "ctx: { light: true, palette: ['#0277bd'] } });\n"
            "const n1 = c.refreshThemeCharts();\n"
            "const replayed = n1 === 1 && calls[0][1] === true &&\n"
            "  JSON.stringify(calls[0][0].color) === "
            "'[\"#4fc3f7\",\"#ffb74d\",\"#81c784\",\"#e57373\",\"#ba68c8\"]';\n"
            "const n2 = c.refreshThemeCharts(); // 同档（node 恒深档）零动作\n"
            "let disp = false;\n"
            "const el2 = {};\n"
            "p.registerPlotCardShell(el2, { chart: { isDisposed: () => disp, "
            "getDom: () => ({}), setOption() {} }, props: { series: [] }, "
            "ctx: {} });\n"
            "disp = true;\n"
            "const alive = p.plotCardShellEntries().length === 2;\n"
            "console.log(JSON.stringify({ replayed, n2, alive }));\n"
        )
        payload = json.loads(out.strip())
        assert payload == {"replayed": True, "n2": 0, "alive": True}

    def test_binding_wiring_source_pins(self):
        ch = _read("pages/charts.js")
        pg = _read("pages.js")
        assert "export function _bindThemeRefresh(" in ch
        assert 'attributeFilter: ["class"]' in ch  # 盯 body.light 翻转
        assert "plotCardShellEntries()" in ch  # 遍历面=plotcard.js WeakRef 单源
        # initPages 装配一次（与轮询/SSE/导出桥同一装配点；并集上唯一调用位）
        assert "_bindThemeRefresh(); // aurora_d UI-R5" in pg
        assert pg.count("_bindThemeRefresh(); //") == 1


# ────────────────────────── 4. 调用面归一（源码） ──────────────────────────

class TestCallSiteUnification:
    """plotCardCached 薄委托 + plotCard 单一入口复用 + 选项工厂消费。"""

    def test_plotcard_cached_is_thin_delegate(self):
        ch = _read("pages/charts.js")
        m = re.search(r"export function plotCardCached\(el, props\) \{(.*?)\n\}",
                      ch, re.S)
        assert m, "plotCardCached 函数体缺失"
        body = m.group(1)
        assert body.count("T.plotCard(") == 1
        assert "return T.plotCard(el, props);" in body
        assert "_plotCards" not in ch  # 旧复用 WeakMap 已随归一删除

    def test_plotcard_builtin_reuse_guards(self):
        # W2-B 接口诉求在 plotcard.js 落地：同容器存活壳 setOption 复用
        pc = _read("plotcard.js")
        m = re.search(r"export function plotCard\(el, props = \{\}, ctx = \{\}\) \{(.*?)\n\}",
                      pc, re.S)
        assert m, "plotCard 函数体缺失"
        body = m.group(1)
        assert "prevShell.chart.isDisposed()" in body  # 复用守卫：存活才复用
        assert "el.contains(prevShell.chart.getDom())" in body
        assert "prevShell.chart.setOption(plotCardOption(props, shell.ctx), true);" in body
        assert "registerPlotCardShell(el, shell)" in body or \
            "_plotShells.set(el, shell);" in body

    def test_option_factory_exists_and_consumed(self):
        ch = _read("pages/charts.js")
        for needle in (
            "export const SPARAM_MODES",
            "export const SPARAM_YLABEL",
            "export function sparamSeries(",
            "export function sparamChartProps(",
            "export function smithChartTheme(",
            "export function heatColormap(",
            "crosshair: true, exportName,",  # S 参数预设单源
        ):
            assert needle in ch, needle
        # 真实消费点：view_detail S 参数卡走工厂；drawSmith 色对走工厂
        vd = _read("pages/view_detail.js")
        assert "sparamChartProps({" in vd
        vf = _read("pages/view_fieldviz.js")
        assert "smithChartTheme(light)" in vf
        # 阈值配置面 re-export（charts 层统一出口）
        assert "export {" in ch and "minmaxIndices" in ch

    def test_cross_seat_counts_hold(self):
        src = _read("pages.js")
        # 12（W2 收口）+ 4（W3-S12 四管线逃生舱迁移）= 16
        assert src.count("T.plotCard(") == 18
        assert src.count("T.drawEChart(") == 0
        assert src.count('mode: "convergence"') == 2
        # crosshair: view_detail(0, 收编工厂) + sparams 2 + reports 1 + 工厂 1
        # + 2 aurora_i W3-S2 cred_curves 对照图 + 6 aurora_j W3-S9（数值读数
        # 类开十字线：playground/timeline×2/calibration×2/optstack）
        assert src.count("crosshair: true") == 12

    def test_downsample_seam_in_plot_card_option(self):
        pc = _read("plotcard.js")
        m = re.search(r"export function plotCardOption\(props, theme\) \{(.*?)\n\}",
                      pc, re.S)
        assert m, "plotCardOption 函数体缺失"
        body = m.group(1)
        assert "downsamplePlotSeries(" in body
        assert 'props.mode === "convergence"' in body  # 阶梯语义整跳
        assert "getDefaultMaxPoints()" in body  # 全站缺省阈值单源
