"""aurora_i W3-S2 席位回归钉：可信度对照曲线前端（画廊抽屉「对照曲线」节
+ S 参数页「对照」开关）。

数据面=cred_curves.js 纯数据模块（零 DOM 零 t()，消费 W3-S1 服务席
/api/credibility/curves 实际信封——engines.{hfss,openems} 曲线族 +
pairing.worst 偏差注记 + verdict 汇总 + provenance/notes 透传）；
渲染面=view_gallery.js（抽屉五段之四，无数据整节隐藏）+
view_sparams.js（对照开关，降级态诚实明示）。

钉六层（test_ui_modules_behavior 风格：node 真执行，缺 node skip）：
1. credNormalize 消费实信封：engines 排序/hasPair/曲线展平（频轴等长
   守卫：形态不合整条丢弃不半拉出线）/maxDev=pairing.worst/verdict
   counts/notes/provenance 透传；单引擎诚实降级（hasPair=false）。
2. credMaxDev 客户端兜底（#294 最近邻）：同栅精确 max|ΔdB|、异栅容差
   内配对、无引擎对=null。
3. credSeries/credSeriesLabeled 输出形态 {name,x,y,color}（plotCard
   契约）+ 引擎恒定配色 + 同名多文件消歧。
4. echarts 配置集成钉：credSeriesLabeled 产物喂 buildEChartOption
   （plotcard.js 单源构造器）→ line 族/数据长度/引擎色逐项核。
5. credFetch 三级缓存（桩 fetch 真跑）：命中零重发/诚实空信封缓存/
   非信封 404=routeMissing 会话短路/aborted 不落缓存。
6. 源码钉：抽屉节隐藏缺省+数据定局揭示（无数据不显示该节红线）、
   S 参数页对照开关与降级明示键、cred_curves 零 DOM 零 t() 纪律。
7. 语法兜底：node --check 三文件（cred_curves/view_gallery/view_sparams）。

不依赖 runs/、不读网络（fetch 全桩）、不启动服务器。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

_CRED = (_STATIC / "pages" / "cred_curves.js").read_text(encoding="utf-8")
_GAL = (_STATIC / "pages" / "view_gallery.js").read_text(encoding="utf-8")
_SP = (_STATIC / "pages" / "view_sparams.js").read_text(encoding="utf-8")


def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return r.stdout


# W3-S1 服务席实信封样例（shape 摘自 service/credibility_curves_service
# .credibility_curves model 命中支路；数字为测试合成值非物理登记值）。
_ENV_DUAL = r"""
const ENV = {
  ok: true, schema_version: "1.0", model: "wilkinson",
  engines: {
    hfss: { available: true,
            source: "runs/hfss_window_b2a/wilkinson/hfss_side/rung3.s3p",
            n_ports: 3, n_points: 5,
            freq_ghz: [2.0, 2.2, 2.4, 2.6, 2.8],
            curves: [ { name: "S11", s_db: [-1, -5, -12, -6, -2] },
                      { name: "S21", s_db: [-3.2, -3.1, -3.05, -3.1, -3.3] } ],
            omitted_filled: [], mask_note: null, note: null },
    openems: { available: true,
               source: "runs/hfss_window_b2a/wilkinson/oe_nominal/sparams.csv",
               n_ports: 3, n_points: 5,
               freq_ghz: [2.0, 2.2, 2.4, 2.6, 2.8],
               curves: [ { name: "S11", s_db: [-1.1, -5.4, -13.2, -6.2, -2.1] },
                         { name: "S21", s_db: [-3.4, -3.3, -3.2, -3.3, -3.5] } ],
               omitted_filled: [], mask_note: null, note: null },
  },
  pairing: { state: "paired", same_grid: true,
             match_rule: "same-grid", n_matched: 5,
             overlap_ghz: [2.0, 2.8],
             max_dev_db: { S11: { max_dev_db: 1.2, at_ghz: 2.4 },
                           S21: { max_dev_db: 0.2, at_ghz: 2.8 } },
             worst: { name: "S11", max_dev_db: 1.2, at_ghz: 2.4 } },
  verdict: { available: true, source: "runs/x/verdict.json",
             states: ["AGREE_OPENEMS"],
             counts: { agree: 1, disagree: 0, unknown: 0, total: 1 } },
  provenance: { hfss: "runs/x/rung3.s3p", openems: "runs/x/sparams.csv",
                verdict: "runs/x/verdict.json", runs_root: "runs/" },
  notes: [],
};
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestCredNormalize:
    def test_dual_engine_envelope(self):
        out = _run_node_js(
            _ENV_DUAL +
            "const m = await import('./pages/cred_curves.js');\n"
            "const v = m.credNormalize(ENV);\n"
            "const errs = [];\n"
            "const eq = (a, b, msg) => { if (JSON.stringify(a) !== JSON.stringify(b)) errs.push(msg + ': ' + JSON.stringify(a) + ' != ' + JSON.stringify(b)); };\n"
            "eq(v.engines, ['hfss', 'openems'], 'engines 排序');\n"
            "if (v.hasPair !== true) errs.push('hasPair');\n"
            "if (v.curves.length !== 4) errs.push('曲线数=' + v.curves.length);\n"
            "const c0 = v.curves[0];\n"
            "if (c0.engine !== 'hfss' || c0.name !== 'S11') errs.push('首曲线身份');\n"
            "if (c0.x.length !== 5 || c0.y.length !== 5) errs.push('频轴/值长度');\n"
            "if (JSON.stringify(c0.y) !== JSON.stringify([-1, -5, -12, -6, -2])) errs.push('y 值');\n"
            "eq(v.maxDev, { name: 'S11', dev: 1.2, freq: 2.4 }, 'maxDev=pairing.worst');\n"
            "if (v.verdict.counts.total !== 1) errs.push('verdict counts');\n"
            "if (v.sources.length !== 3) errs.push('sources=' + v.sources.length);\n"
            "if (v.notes.length !== 0) errs.push('notes');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:dual');\n")
        assert "ok:dual" in out

    def test_single_engine_and_guards(self):
        out = _run_node_js(
            _ENV_DUAL +
            "const m = await import('./pages/cred_curves.js');\n"
            "const errs = [];\n"
            "// 单引擎：OE available=false → hasPair=false、engines 只剩 hfss\n"
            "const single = JSON.parse(JSON.stringify(ENV));\n"
            "single.engines.openems.available = false;\n"
            "single.pairing = { state: 'single_engine', note: '双引擎曲线不全' };\n"
            "const v1 = m.credNormalize(single);\n"
            "if (v1.hasPair !== false) errs.push('single hasPair');\n"
            "if (JSON.stringify(v1.engines) !== JSON.stringify(['hfss'])) errs.push('single engines');\n"
            "if (v1.maxDev !== null) errs.push('single maxDev 应 null');\n"
            "if (v1.curves.length !== 2) errs.push('single 曲线数=' + v1.curves.length);\n"
            "// 频轴/曲线等长守卫：形态不合整条丢弃（不半拉出线）\n"
            "const bad = JSON.parse(JSON.stringify(ENV));\n"
            "bad.engines.openems.curves.push({ name: 'S31', s_db: [-1, -2] });\n"
            "const v2 = m.credNormalize(bad);\n"
            "if (v2.curves.some((c) => c.name === 'S31')) errs.push('等长守卫失效');\n"
            "// 未注册模板诚实空信封（engines 空）\n"
            "const v3 = m.credNormalize({ ok: true, engines: {}, pairing: null, notes: ['no data'] });\n"
            "if (v3.curves.length !== 0 || v3.hasPair !== false) errs.push('空信封');\n"
            "if (v3.notes[0] !== 'no data') errs.push('空信封 notes 透传');\n"
            "// 非信封/null 容错（零抛）\n"
            "m.credNormalize(null); m.credNormalize({});\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:single');\n")
        assert "ok:single" in out


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestCredMaxDev:
    def test_client_fallback(self):
        out = _run_node_js(
            "const m = await import('./pages/cred_curves.js');\n"
            "const errs = [];\n"
            "const eq = (a, b, msg) => { if (JSON.stringify(a) !== JSON.stringify(b)) errs.push(msg + ': ' + JSON.stringify(a) + ' != ' + JSON.stringify(b)); };\n"
            "// 同栅：max|ΔdB| 与首个达成频点\n"
            "const ca = { engine: 'hfss', name: 'S11', x: [1, 2, 3], y: [-1, -10, -2] };\n"
            "const cb = { engine: 'openems', name: 'S11', x: [1, 2, 3], y: [-2, -9, -3] };\n"
            "eq(m.credMaxDev([ca, cb]), { name: 'S11', dev: 1, freq: 1 }, '同栅 max');\n"
            "// 异栅（1% 跨度容差内最近邻）：配对成功\n"
            "const cc = { engine: 'openems', name: 'S11', x: [1.005, 1.995, 3.0], y: [-2, -9, -3] };\n"
            "const r = m.credMaxDev([ca, cc]);\n"
            "if (!r || r.name !== 'S11' || Math.abs(r.dev - 1) > 1e-12) errs.push('异栅配对: ' + JSON.stringify(r));\n"
            "// 无引擎对（同名缺失/引擎缺失）→ null\n"
            "if (m.credMaxDev([ca]) !== null) errs.push('单线应 null');\n"
            "if (m.credMaxDev([ca, { engine: 'openems', name: 'S21', x: [1, 2, 3], y: [0, 0, 0] }]) !== null) errs.push('异名应 null');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:maxdev');\n")
        assert "ok:maxdev" in out


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestCredSeriesShape:
    def test_series_shape_and_colors(self):
        out = _run_node_js(
            _ENV_DUAL +
            "const m = await import('./pages/cred_curves.js');\n"
            "const th = await import('./theme.js');\n"
            "const v = m.credNormalize(ENV);\n"
            "const series = m.credSeriesLabeled(v.curves, false);\n"
            "const errs = [];\n"
            "if (series.length !== 4) errs.push('series 数=' + series.length);\n"
            "for (const s of series) {\n"
            "  if (typeof s.name !== 'string' || !Array.isArray(s.x) || !Array.isArray(s.y)) errs.push('形态: ' + JSON.stringify(Object.keys(s)));\n"
            "  if (typeof s.color !== 'string' || !s.color.startsWith('#')) errs.push('color: ' + s.color);\n"
            "}\n"
            "if (series[0].name !== 'HFSS·S11') errs.push('图例名: ' + series[0].name);\n"
            "if (series[2].name !== 'openEMS·S11') errs.push('图例名: ' + series[2].name);\n"
            "// 色对取档（theme.js 单源）：dark 档=seriesOrange/seriesBlue\n"
            "if (series[0].color !== th.themePick(false, m.CRED_ENGINE_COLOR_PAIRS.hfss)) errs.push('HFSS 色');\n"
            "if (series[0].color !== th.THEME_COLORS.seriesOrange.dark) errs.push('HFSS 色应=seriesOrange.dark');\n"
            "if (series[2].color !== th.THEME_COLORS.seriesBlue.dark) errs.push('openEMS 色应=seriesBlue.dark');\n"
            "// 主题档：light 档取 pair.light\n"
            "const lightSeries = m.credSeriesLabeled(v.curves, true);\n"
            "if (lightSeries[0].color !== th.THEME_COLORS.seriesOrange.light) errs.push('light 档取值');\n"
            "// 同引擎同名多文件消歧（追加 file 段）\n"
            "const dup = m.credSeriesLabeled([\n"
            "  { engine: 'hfss', name: 'S11', file: 'a.s2p', x: [1], y: [1] },\n"
            "  { engine: 'hfss', name: 'S11', file: 'b.s2p', x: [1], y: [2] }], false);\n"
            "if (dup[0].name.indexOf('a.s2p') < 0 || dup[1].name.indexOf('b.s2p') < 0) errs.push('消歧: ' + dup.map((s) => s.name).join('|'));\n"
            "// 未知引擎 id 原样标签（API 数据同信任级）+ unknown 色对\n"
            "const uk = m.credSeriesLabeled([{ engine: 'xyz', name: 'S11', x: [1], y: [1] }], false);\n"
            "if (uk[0].name !== 'xyz·S11') errs.push('unknown 标签');\n"
            "if (uk[0].color !== th.themePick(false, m.CRED_ENGINE_COLOR_PAIRS.unknown)) errs.push('unknown 色');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:series');\n")
        assert "ok:series" in out

    def test_series_feed_build_echart_option(self):
        """echarts 配置集成钉：series 产物喂 plotcard.js 单源构造器。"""
        out = _run_node_js(
            _ENV_DUAL +
            "const m = await import('./pages/cred_curves.js');\n"
            "const pc = await import('./plotcard.js');\n"
            "const series = m.credSeriesLabeled(m.credNormalize(ENV).curves, false);\n"
            "const opt = pc.buildEChartOption(series, { xlabel: 'GHz', ylabel: 'dB' }, { light: false, palette: [] });\n"
            "const errs = [];\n"
            "if (opt.series.length !== series.length) errs.push('option.series 数');\n"
            "for (let i = 0; i < opt.series.length; i++) {\n"
            "  const e = opt.series[i];\n"
            "  if (e.type !== 'line') errs.push('type: ' + e.type);\n"
            "  if (e.data !== series[i].y) errs.push('data 未对齐 y');\n"
            "  if (!e.lineStyle || e.lineStyle.color !== series[i].color) errs.push('lineStyle.color');\n"
            "}\n"
            "if (JSON.stringify(opt.xAxis.data) !== JSON.stringify(series[0].x)) errs.push('category 轴=首曲线 x');\n"
            "if (!opt.legend || opt.legend.type !== 'scroll') errs.push('legend');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:echarts');\n")
        assert "ok:echarts" in out


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestCredFetchCache:
    """桩 fetch 真跑（apiFetch 链）：三级缓存语义逐案独立进程。"""

    def test_cache_hit_no_refetch(self):
        out = _run_node_js(
            _ENV_DUAL +
            "let calls = 0;\n"
            "globalThis.fetch = async () => { calls++; return { json: async () => ENV }; };\n"
            "const m = await import('./pages/cred_curves.js');\n"
            "const r1 = await m.credFetch('wilkinson');\n"
            "const r2 = await m.credFetch('wilkinson');\n"
            "const errs = [];\n"
            "if (r1.status !== 'data' || r2.status !== 'data') errs.push('status');\n"
            "if (calls !== 1) errs.push('命中应零重发: calls=' + calls);\n"
            "if (r1.view.maxDev.name !== 'S11') errs.push('view 透传');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:cache');\n")
        assert "ok:cache" in out

    def test_empty_envelope_cached(self):
        out = _run_node_js(
            "let calls = 0;\n"
            "globalThis.fetch = async () => { calls++; return { json: async () => ({ ok: true, engines: {}, pairing: null, notes: ['no data'], available_templates: ['wilkinson'] }) }; };\n"
            "const m = await import('./pages/cred_curves.js');\n"
            "const r1 = await m.credFetch('nosuch');\n"
            "await m.credFetch('nosuch');\n"
            "const errs = [];\n"
            "if (r1.status !== 'empty' || r1.aborted) errs.push('empty 态');\n"
            "if (calls !== 1) errs.push('负缓存失效: calls=' + calls);\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:empty');\n")
        assert "ok:empty" in out

    def test_error_envelope_and_route_missing(self):
        out = _run_node_js(
            "let calls = 0;\n"
            "globalThis.fetch = async () => { calls++; return { json: async () => calls === 1 ? { ok: false, errors: ['x'] } : { detail: 'Not Found' } }; };\n"
            "const m = await import('./pages/cred_curves.js');\n"
            "const r1 = await m.credFetch('wilkinson');\n"
            "const r2 = await m.credFetch('other');   // 非信封 → routeMissing\n"
            "const r3 = await m.credFetch('third');   // 短路后零请求\n"
            "const errs = [];\n"
            "if (r1.status !== 'empty') errs.push('ok:false 应 empty');\n"
            "if (r2.status !== 'empty') errs.push('非信封应 empty');\n"
            "if (calls !== 2) errs.push('routeMissing 短路失效: calls=' + calls);\n"
            "if (r3.status !== 'empty') errs.push('短路返回');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:route');\n")
        assert "ok:route" in out

    def test_aborted_not_cached(self):
        out = _run_node_js(
            _ENV_DUAL +
            "let calls = 0, fail = true;\n"
            "globalThis.fetch = async () => { calls++;\n"
            "  if (fail) throw Object.assign(new Error('cancel'), { name: 'AbortError' });\n"
            "  return { json: async () => ENV }; };\n"
            "const m = await import('./pages/cred_curves.js');\n"
            "const r1 = await m.credFetch('wilkinson');\n"
            "fail = false;\n"
            "const r2 = await m.credFetch('wilkinson');\n"
            "const errs = [];\n"
            "if (r1.status !== 'empty' || r1.aborted !== true) errs.push('aborted 形态');\n"
            "if (r2.status !== 'data') errs.push('aborted 不落缓存应重发');\n"
            "if (calls !== 2) errs.push('calls=' + calls);\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:abort');\n")
        assert "ok:abort" in out


class TestSourcePins:
    """源码钉：渲染红线与接线在位。"""

    def test_gallery_drawer_section(self):
        # 抽屉五段之四：包装层 display:none 缺省（无数据整节不可见）
        assert "data-slot='credcurves-wrap'" in _GAL
        assert re.search(
            r"data-slot='credcurves-wrap'[^>]*display:none", _GAL), (
            "对照曲线节缺省应隐藏（无数据模板不显示该节）")
        assert "function renderCredCurvesInto(" in _GAL
        # 数据定局才揭示：status!=="data" 直接返回（不写隐藏区）
        body = re.search(
            r"async function renderCredCurvesInto\(.*?\n\}", _GAL, re.S)
        assert body, "渲染函数缺席"
        assert 'r.status !== "data"' in body.group(0), (
            "无对照数据应直接返回（整节保持隐藏）")
        assert "wrap.style.display" in body.group(0), "揭示单点缺席"
        # aborted/脱连守卫（UI-R12 同款：切页不写隐藏区）
        assert "r.aborted" in body.group(0) and "wrap.isConnected" in body.group(0)
        # 偏差注记三态（信封 worst/客户端兜底/频网不齐诚实行）+ 单引擎 note
        assert "gallery.cred_dev_tpl" in _GAL
        assert "gallery.cred_dev_na" in _GAL
        assert "gallery.cred_single_note_tpl" in _GAL
        # verdict 计数徽章先红后绿（#122：DISAGREE 优先判）
        vseg = re.search(r"const vd = c0\.disagree.*?anchor_verdict_unknown", _GAL, re.S)
        assert vseg, "verdict 三分类缺席"
        assert vseg.group(0).index("disagree") < vseg.group(0).index("allAgree"), (
            "verdict 分类须 DISAGREE 先判")
        # 服务端 notes/provenance 脚注（esc 通道）
        assert "gallery.cred_sources_tpl" in _GAL
        assert "notesLine" in _GAL

    def test_sparams_compare_mode(self):
        # 对照开关（模块级状态保持+整页重入同款）与 aria-pressed
        assert "let _spCompare = false;" in _SP
        assert "id='sp-compare'" in _SP and 'data-i18n=\'sparams.compare_btn\'' in _SP
        assert 'T.$("sp-compare").setAttribute("aria-pressed"' in _SP
        assert "_spCompare = !_spCompare" in _SP
        # 对照卡异步补铺：诚实降级两明示行 + 图卡入联动组
        assert "sparams.compare_no_model" in _SP
        assert "sparams.compare_none" in _SP
        assert 'connectGroup: "sparams"' in _SP
        # 对照曲线非当前 run 产物（标题诚实区分，防误读）
        assert "sparams.compare_title" in _SP
        # 偏差注记/单引擎 note 复用画廊同款词表键（跨页复用只增引用）
        assert "gallery.cred_dev_tpl" in _SP
        assert "gallery.cred_single_note_tpl" in _SP

    def test_cred_module_discipline(self):
        # 纯数据纪律：零 DOM 写面、零 i18n 依赖（键集互证页前缀死键口径；
        # t( 调用形态判定 `\bt\("`——注释/词中 t( 不计）
        assert "innerHTML" not in _CRED
        assert re.search(r"\bt\(\"", _CRED) is None, (
            "cred_curves.js 出现 t()（i18n 文案须由消费视图烘焙）")
        assert 'from "./api.js"' in _CRED, "取数须走统一请求层"
        # 查询参数（template= 单参数；model 双写在契约门 UNSENT 判定下
        # 退役——服务端路由只声明 template，W3-S1 装配后收敛项）
        assert '?template="' in _CRED
        assert "model=" not in _CRED, "model 双写已退役（契约门收敛项）"

    def test_i18n_keys_registered(self):
        """新键 zh/en 双语齐全（完整互证在 test_ui_i18n，此处快检）。"""
        src = (_STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")
        keys = [
            "gallery.cred_title", "gallery.cred_legend", "gallery.cred_dev_tpl",
            "gallery.cred_dev_na", "gallery.cred_single_note_tpl",
            "gallery.cred_verdict_counts_tpl", "gallery.cred_sources_tpl",
            "sparams.compare_btn", "sparams.compare_title",
            "sparams.compare_none", "sparams.compare_no_model",
        ]
        for k in keys:
            assert f'"{k}"' in src, f"词表缺键: {k}"


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestNodeCheck:
    @pytest.mark.parametrize("name", [
        "cred_curves.js", "view_gallery.js", "view_sparams.js",
    ])
    def test_node_check(self, name):
        r = subprocess.run([_NODE, "--check", str(_STATIC / "pages" / name)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"node --check {name}:\n{r.stderr[-2000:]}"
