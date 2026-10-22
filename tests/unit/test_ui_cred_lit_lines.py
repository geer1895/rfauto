"""aurora_i 人性化三批 R2 席位回归钉：对照图表增强（文献参考线 + 卡面
可信度盾牌徽章 + 图下白话教学行）。

新面三件（零新端点、零 service 改动）：
- lit_refs.js：文献/官方例验收参考值前端常量单文件——值逐条转录自
  docs/rf_template_references.md 验收基准节（#97 数字口径：本文件钉值
  + 原文 grep 双证，转录漂移即红）；
- view_gallery.js：卡面盾牌徽章（/api/anchors 家族专属锚 verdict 态聚合，
  worst-of 先红后绿 #122；'*' 全局锚不计入）+ 抽屉对照曲线第三线 +
  图下教学行；
- view_sparams.js：对照卡第三线 + 教学行（gallery.cred_howto 同键复用）。

钉四层（test_ui_cred_curves 风格：node 真执行，缺 node skip）：
1. lit_refs 数据：注册表键值钉（wilkinson -40/-3/-43、branchline×2/
   lange -3.01、ratrace S21/S41 -3.01、cline_coupler -10.045/-23.3/-32.9）
   + 每条 source 指回源文档节号 + 原文数值 grep 复核（防 docs 漂移）。
2. litSeriesFor 行为：过滤到图内已有同名曲线（缺席不画悬空线）/采样网=
   首曲线 x 同引用（plotCard category 轴形态学）/常值 y/seriesTeal 双档
   色/未注册·零曲线·坏轴网·无命中→[]/labelOf 烘焙。
3. 渲染接线源码钉：第三线追加在引擎系列之后（.concat(lit...) 两视图）/
   教学行双视图/卡面徽章（盾牌 SVG+worst-of 聚合 DISAGREE 先判+'*' 排除
   +待验证灰字）/详情补拉单点缓存守卫（防 settle 自激循环）。
4. i18n 新键 zh/en 双语齐全 + node --check 全部触面文件。

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
_DOCS = Path(__file__).resolve().parents[2] / "docs" / "rf_template_references.md"

_LIT = (_STATIC / "pages" / "lit_refs.js").read_text(encoding="utf-8")
_GAL = (_STATIC / "pages" / "view_gallery.js").read_text(encoding="utf-8")
_SP = (_STATIC / "pages" / "view_sparams.js").read_text(encoding="utf-8")
_I18N = (_STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")


def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return r.stdout


# ═══ 1. 文献参考值数据（转录钉，#97 口径）════════════════════════════


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestLitRefsData:
    def test_registry_values_pinned(self):
        """注册表键值钉：值必须等于 docs 面原文转录（人造数值即红）。"""
        out = _run_node_js(
            "const m = await import('./pages/lit_refs.js');\n"
            "const flat = {};\n"
            "for (const [t, e] of Object.entries(m.LIT_REFS))\n"
            "  for (const p of e.points) flat[t + '|' + p.curve] = p.db;\n"
            "console.log(JSON.stringify(flat));\n")
        flat = __import__("json").loads(out.strip())
        want = {
            "wilkinson|S11": -40, "wilkinson|S31": -3, "wilkinson|S32": -43,
            "branchline|S21": -3.01, "branchline|S31": -3.01,
            "branchline_2sect|S21": -3.01, "branchline_2sect|S31": -3.01,
            "ratrace|S21": -3.01, "ratrace|S41": -3.01,
            "lange|S21": -3.01, "lange|S31": -3.01,
            "cline_coupler|S31": -10.045, "cline_coupler|S41": -23.3,
            "cline_coupler|S11": -32.9,
        }
        assert flat == want, f"文献值漂移: {flat}"

    def test_sources_point_to_reference_doc(self):
        out = _run_node_js(
            "const m = await import('./pages/lit_refs.js');\n"
            "const src = Object.entries(m.LIT_REFS)\n"
            "  .map(([t, e]) => t + '=' + e.source).join('\\n');\n"
            "console.log(src);\n")
        lines = out.strip().splitlines()
        assert len(lines) == 6, f"注册模板数={len(lines)}"
        for ln in lines:
            assert "docs/rf_template_references.md" in ln, ln
            assert re.search(r"sec\.\d", ln), f"缺节号出处: {ln}"

    def test_values_exist_in_reference_doc(self):
        """原文 grep 复核（R3 设计 §5：构建期断言钉'值在原文存在'）。"""
        text = _DOCS.read_text(encoding="utf-8").replace("\u2212", "-")
        for needle in (
            "S11=-40dB", "S32 隔离=-43dB", "S31=-3dB",        # §1 Wilkinson
            "−10.045dB".replace("\u2212", "-"),               # §13.1 cline
            "S41=−23.3dB".replace("\u2212", "-"),
            "S11=−32.9dB".replace("\u2212", "-"),
            "-3.01dB",                                        # §13.3 Lange
            "S21=−j/√2、S31=−1/√2".replace("\u2212", "-"),    # §13.2 单节
        ):
            assert needle in text, f"rf_template_references.md 原文无数值: {needle}"


# ═══ 2. litSeriesFor 行为（node 真执行）══════════════════════════════


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestLitSeriesFor:
    def test_series_shape_sampling_and_colors(self):
        out = _run_node_js(
            "const m = await import('./pages/lit_refs.js');\n"
            "const th = await import('./theme.js');\n"
            "const errs = [];\n"
            "const curves = [\n"
            "  { engine: 'hfss', name: 'S11', x: [2.0, 2.5, 3.0], y: [-1, -2, -3] },\n"
            "  { engine: 'hfss', name: 'S31', x: [2.0, 2.5, 3.0], y: [-3, -3, -3] },\n"
            "  { engine: 'openems', name: 'S11', x: [2.0, 2.5, 3.0], y: [-1.1, -2.1, -3.1] },\n"
            "];\n"
            "const s = m.litSeriesFor('wilkinson', curves, (p) => 'L·' + p.curve + '·' + p.db, false);\n"
            "// 图内只有 S11/S31 → 两条参考线（S32 缺席不画悬空线）\n"
            "if (s.length !== 2) errs.push('series 数=' + s.length);\n"
            "if (s[0].name !== 'L·S11·-40') errs.push('label: ' + s[0].name);\n"
            "if (s[0].x !== curves[0].x) errs.push('采样网应=首曲线 x 同引用');\n"
            "if (JSON.stringify(s[0].y) !== JSON.stringify([-40, -40, -40])) errs.push('常值 y');\n"
            "if (s[0].color !== th.THEME_COLORS.seriesTeal.dark) errs.push('dark 档色');\n"
            "const sl = m.litSeriesFor('wilkinson', curves, (p) => 'L', true);\n"
            "if (sl[0].color !== th.THEME_COLORS.seriesTeal.light) errs.push('light 档色');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:shape');\n")
        assert "ok:shape" in out

    def test_empty_paths(self):
        out = _run_node_js(
            "const m = await import('./pages/lit_refs.js');\n"
            "const errs = [];\n"
            "const c1 = [{ engine: 'hfss', name: 'S11', x: [1, 2], y: [0, 0] }];\n"
            "if (m.litSeriesFor('gysel', c1, null, false).length !== 0) errs.push('未注册模板应空');\n"
            "if (m.litSeriesFor(null, c1, null, false).length !== 0) errs.push('null 模板应空');\n"
            "if (m.litSeriesFor('wilkinson', [], null, false).length !== 0) errs.push('零曲线应空');\n"
            "if (m.litSeriesFor('wilkinson', null, null, false).length !== 0) errs.push('null 曲线应空');\n"
            "// 曲线名无命中（branchline 参考 S21/S31，图内只有 S33）\n"
            "if (m.litSeriesFor('branchline', c1, null, false).length !== 0) errs.push('无命中应空');\n"
            "// 轴网形态不合（含非数）整批拒绝\n"
            "const bad = [{ engine: 'hfss', name: 'S11', x: [1, NaN], y: [0, 0] }];\n"
            "if (m.litSeriesFor('wilkinson', bad, null, false).length !== 0) errs.push('坏轴网应空');\n"
            "// labelOf 缺席回退曲线名（零抛）\n"
            "const fb = m.litSeriesFor('wilkinson', c1, null, false);\n"
            "if (fb.length !== 1 || fb[0].name !== 'S11') errs.push('labelOf 缺席回退');\n"
            "if (m.litRefOf('nosuch') !== null) errs.push('未注册 litRefOf');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:empty');\n")
        assert "ok:empty" in out


# ═══ 3. 渲染接线源码钉 ═══════════════════════════════════════════════


class TestWiringSourcePins:
    def test_third_line_appended_after_engines_both_views(self):
        """第三线必须追加在引擎系列之后（plotCard category 轴=series[0].x
        ——首系列定轴网，引擎线在前的既有次序不动）。"""
        for src, fname in ((_GAL, "view_gallery"), (_SP, "view_sparams")):
            assert 'from "./lit_refs.js"' in src, fname
            assert "litSeriesFor(" in src, fname
            m = re.search(r"credSeriesLabeled\([^)]*\)\s*\.concat\(lit", src)
            assert m, f"{fname}: 引擎系列后追加文献线（.concat(lit)）缺席"

    def test_howto_line_both_views(self):
        """教学行（任务3）：抽屉对照曲线节 + S 参数对照卡同键复用。"""
        assert 't("gallery.cred_howto")' in _GAL
        assert 't("gallery.cred_howto")' in _SP
        # 教学行在图表容器之后（图下方语义：gal-cred-chart 容器在前）
        gpos = _GAL.index("gal-cred-chart")
        hpos = _GAL.index('t("gallery.cred_howto")')
        assert gpos < hpos, "教学行应在图表容器之后"
        # 对照卡教学行槽（sp-compare-howto）在图容器之后
        spos = _SP.index("sp-chart-compare")
        howpos = _SP.index("sp-compare-howto")
        assert spos < howpos

    def test_lit_source_footprint(self):
        """文献出处行：有登记文献值的模板才显示（litRefOf 门）。"""
        assert "litRefOf(" in _GAL and "litRefOf(" in _SP
        assert "gallery.cred_lit_source_tpl" in _GAL
        assert "gallery.cred_lit_source_tpl" in _SP

    def test_card_badge_honesty_discipline(self):
        """卡面徽章（任务2）四钉：盾牌 SVG/worst-of 先红后绿/'*' 全局锚
        不计入/无锚灰色待验证。"""
        # 盾牌内联 SVG（无 emoji 字体依赖，currentColor 随主题）
        assert "_SHIELD_SVG" in _GAL and "<svg" in _GAL
        # 聚合：DISAGREE 先判（#122 先红后绿——长串态内并列 AGREE 字样
        # 防误绿；聚合器与 anchorVerdictOf 同纪律）
        agg = re.search(r"function cardCredBadgeHtml\(.*?\n\}", _GAL, re.S)
        assert agg, "卡面徽章聚合函数缺席"
        body = agg.group(0)
        assert body.index("DISAGREE") < body.index("AGREE"), (
            "卡面徽章聚合须 DISAGREE 先判")
        # '*' 全局锚不计入（mmt 全局锚恒真——计入=72 卡全盖已验证章）
        fam = re.search(r"function isFamilySpecificAnchor\(.*?\n\}", _GAL, re.S)
        assert fam, "家族专属锚判定缺席"
        assert 'fams.indexOf("*") < 0' in fam.group(0)
        # 无锚=灰色待验证小字（任务口径）
        assert "gallery.cred_badge_none" in _GAL
        # 徽章 tip 走 escAttr（title 属性注入面）
        assert "escAttr(t(" in body

    def test_detail_fetch_single_source_no_self_loop(self):
        """详情补拉单点 + 防自激：缓存命中跳过 settle 附加（否则
        resolve 后 .then(settle) 微任务自激重铺死循环）。"""
        fn = re.search(r"function fetchAnchorDetail\(.*?\n\}", _GAL, re.S)
        assert fn, "fetchAnchorDetail 单点缺席"
        # 渲染循环保留缓存/在途双守卫（跳过已缓存锚的 settle 附加）
        loop = re.search(
            r"for \(const a of matched\) \{.*?fetchAnchorDetail\(id\)\.then\(settle\);",
            _GAL, re.S)
        assert loop, "可信度节补拉循环未走单点"
        assert "_anchorProv.has(id) || _anchorInFlight.has(id)" in loop.group(0)
        # 卡面预取同走单点（零重发）
        pre = re.search(r"function prefetchAnchorBadges\(.*?\n\}", _GAL, re.S)
        assert pre and "fetchAnchorDetail" in pre.group(0)

    def test_verdict_prefetch_rerender_wiring(self):
        """清单晚到→卡面补铺链在位：_galRender 注入 + rerenderGalleryCards
        守卫（_galCards 未到/壳未建=零操作）。"""
        assert "let _galRender = null;" in _GAL
        assert "_galRender = render;" in _GAL
        rr = re.search(r"function rerenderGalleryCards\(.*?\n\}", _GAL, re.S)
        assert rr and "_galCards" in rr.group(0), "卡面重铺守卫缺席"
        assert "prefetchAnchorBadges();" in _GAL


# ═══ 4. i18n 键与语法 ════════════════════════════════════════════════


class TestI18nAndSyntax:
    def test_new_keys_bilingual(self):
        """新键 zh/en 双语齐全（完整互证在 test_ui_i18n，此处快检）。"""
        keys = [
            "gallery.cred_howto", "gallery.cred_lit_series_tpl",
            "gallery.cred_lit_source_tpl", "gallery.cred_badge_agree",
            "gallery.cred_badge_disagree", "gallery.cred_badge_unknown",
            "gallery.cred_badge_none", "gallery.cred_badge_tip_tpl",
            "gallery.cred_badge_none_tip",
        ]
        for k in keys:
            assert f'"{k}"' in _I18N, f"词表缺键: {k}"

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_new_keys_load_bilingual(self):
        out = _run_node_js(
            "const m = await import('./pages/i18n.js');\n"
            "const keys = ['gallery.cred_howto','gallery.cred_lit_series_tpl',\n"
            "  'gallery.cred_lit_source_tpl','gallery.cred_badge_agree',\n"
            "  'gallery.cred_badge_disagree','gallery.cred_badge_unknown',\n"
            "  'gallery.cred_badge_none','gallery.cred_badge_tip_tpl',\n"
            "  'gallery.cred_badge_none_tip'];\n"
            "const bad = keys.filter((k) => !m.LOCALES[k]\n"
            "  || typeof m.LOCALES[k].zh !== 'string' || !m.LOCALES[k].zh\n"
            "  || typeof m.LOCALES[k].en !== 'string' || !m.LOCALES[k].en);\n"
            "if (bad.length) throw new Error('缺半边: ' + bad.join(','));\n"
            "console.log('ok:i18n');\n")
        assert "ok:i18n" in out

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    @pytest.mark.parametrize("name", [
        "lit_refs.js", "view_gallery.js", "view_sparams.js", "i18n.js",
    ])
    def test_node_check(self, name):
        r = subprocess.run([_NODE, "--check", str(_STATIC / "pages" / name)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"node --check {name}:\n{r.stderr[-2000:]}"
