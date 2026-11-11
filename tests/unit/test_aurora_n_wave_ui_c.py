"""aurora_n wave_ui_c 席位回归钉：前端引导线 C+D 合席（文案打磨+CLI help 分组）。

对应 runs/aurora_n/ui_recon/TOUR_FINDINGS.md 五发现（P3-1..P3-5 + P2-4）：

- P3-1 verdict 术语解释入口+状态词统一：概念速查表补 verdict 行
  （PASS/PARTIAL/FAIL/UNKNOWN 四值含义单源）；dashboard 状态环旁可点
  跳转注记（词表锚）；最近活动徽章 other 桶改中文词「其他」+原始英文
  状态串进 title（中文主导+英文对照 tooltip，审计建议口径）。
- P3-2 工具箱缺省：缺省选中 microstrip_synthesis（原=注册表首键
  circular_waveguide_mode_prop 冷门）+缺省说明一行。
- P3-3 tune 启动前置校验：启动前 /api/fs/list 只读探测路径存在
  （#105 best-effort：探测失败=unknown 放行；确认不存在才拦+自查卡）；
  toast 措辞改「已提交，正在校验…」（不再秒发"已启动"假成功）；配方
  信息行随输入 debounce 刷新（原只挂 change 失焦才刷）。
- P3-4 文件浏览器扩展名过滤（纯前端）：fileBrowser 第三形参 exts 只滤
  文件条目（目录恒可见）+工具条「仅显示 …」徽章（过滤语义用户可感知）
  +全滤空态说明行；fsFilterEntries 纯函数单源。服务端 /api/fs/list 契约
  零变化（审计原案"后端加 param"不采——本席红线）。
- P3-5 列表语义：dom.js help() 壳单点兜底——正文连续 <li> 游程自动包
  <ul>（26 调用点零改动获得读屏列表语义；已含 <ul> 的正文原样透传）；
  view_guide FAQ/next 两块模板显式补 <ul>。
- P2-4 CLI --help 按域分组：cli/help_groups.py HELP_PANEL_OF 8 域映射 +
  apply_help_panels 注册后补挂 rich_help_panel（typer 原生 rich 面板，
  最小侵入形态）——渲染面变化、注册面零变化（注册序金快照/leaf 计数/
  zero-shadow 不受影响；D-06 字符纪律同守：面板名零裸 [ 零 %）。

变异验证（移除修复必红，开发期逐钉实测记录于 runs/aurora_n/wave_ui_c/
MUTATION_LOG.md）：源码钉关键串即修复本体（删除即断言红）；node 行为钉
消费导出纯函数（删除导出/import undefined 即红）；D1 摘除 apply_help_
panels 挂钩 → 面板消失/缺省 Commands 面板回归即红。

不依赖 runs/ 真实湖、不读网络、不启动服务器；node 面缺 node 诚实 skip；
不 commit。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")


def _src(name: str) -> str:
    return (_STATIC / "pages" / name).read_text(encoding="utf-8")


def _run_node_js(js: str) -> dict:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    import json

    return json.loads(r.stdout.strip().splitlines()[-1])


# ══════════════════ P3-1 verdict 术语解释入口+状态词统一 ══════════════════


class TestVerdictGlossary:
    def test_guide_glossary_verdict_row(self):
        """概念速查补 verdict 行：词条键在 i18n（zh/en 双语）且被 guide 引用；
        四个取值 PASS/PARTIAL/FAIL/UNKNOWN 逐词在档。"""
        src = _src("view_guide.js")
        assert '<tr><td>verdict</td><td>${t("guide.gl_verdict_d")}</td></tr>' in src
        i18n = _src("i18n.js")
        assert '"guide.gl_verdict_d"' in i18n
        for term in ("PASS", "PARTIAL", "FAIL", "UNKNOWN"):
            assert term in i18n, f"verdict 词条缺 {term}"

    def test_dashboard_status_mix_gloss_link(self):
        """状态环旁解释入口：注记行键在词表 + data-go='guide' 可点跳转
        （bindClickRows 单源形态接线在位）。"""
        src = _src("view_dashboard.js")
        assert 't("dashboard.mix_gloss_hint")' in src
        assert 't("dashboard.mix_gloss_link")' in src
        assert "data-go='guide'" in src
        assert 'bindClickRows(gloss, (row) => showPage(row.dataset.go), "[data-go]")' in src
        for key in ("dashboard.mix_gloss_hint", "dashboard.mix_gloss_link",
                    "dashboard.mix_gloss_link_aria"):
            assert f'"{key}"' in _src("i18n.js")

    def test_activity_badge_unified_zh_with_raw_tooltip(self):
        """最近活动徽章统一：other 桶改词表词「其他」，原始状态串进 title
        （activity_raw_tip_tpl 插值）；空状态仍走 activity_unknown（原键
        不死）。"""
        src = _src("view_dashboard.js")
        assert 't("dashboard.activity_other")' in src
        assert ('t("dashboard.activity_raw_tip_tpl", '
                '{ status: rawStatus })') in src
        assert 't("dashboard.activity_unknown")' in src  # 空状态兜底键不死
        for key in ("dashboard.activity_other", "dashboard.activity_raw_tip_tpl"):
            assert f'"{key}"' in _src("i18n.js")

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_verdict_glossary_bilingual_content(self):
        """词条内容行为钉：zh 主导四值齐全 + en 对照；t() 插值面可用。"""
        out = _run_node_js(
            "const m = await import('./pages/i18n.js');\n"
            "const zh = m.LOCALES['guide.gl_verdict_d'].zh;\n"
            "const en = m.LOCALES['guide.gl_verdict_d'].en;\n"
            "const r = {\n"
            "  zhAll: ['PASS','PARTIAL','FAIL','UNKNOWN'].every(w => zh.includes(w)),\n"
            "  enAll: ['PASS','PARTIAL','FAIL','UNKNOWN'].every(w => en.includes(w)),\n"
            "  otherZh: m.t('dashboard.activity_other'),\n"
            "  tipTpl: m.t('dashboard.activity_raw_tip_tpl', { status: 'running' }),\n"
            "  badgeTpl: m.t('fs.filter_badge_tpl', { list: '.aedt' }),\n"
            "};\n"
            "console.log(JSON.stringify(r));\n")
        assert out["zhAll"] is True and out["enAll"] is True
        assert out["otherZh"] == "其他"
        assert "running" in out["tipTpl"]


# ══════════════════ P3-2 工具箱缺省选中 ══════════════════


class TestToolsDefault:
    def test_default_selection_prefers_microstrip_synthesis(self):
        """rebuildOptions 三分支：重建前取 prev（innerHTML 重置防御）——
        空=新手缺省 microstrip_synthesis（缺席回落首项）；仍在可见集=恢复
        用户选择；被滤掉=回落首个可见项（原语义）。deep link/待选键优先级
        在其后不变。"""
        src = _src("view_tools.js")
        assert "const prev = sel.value;" in src
        assert 'const pref = vis.find((c) => c.name === "microstrip_synthesis");' in src
        assert "sel.value = (pref || vis[0]).name;" in src
        assert "sel.value = vis[0].name; // 当前选择被滤掉：回落首个可见项（原语义）" in src
        # 深链消费优先级原文不动（审计好面清单不回退）
        assert "_toolsPendingKey || toolsDeepLinkKey(location.hash)" in src

    def test_default_hint_copy(self):
        """缺省说明一行：词表键 + data-i18n 双注入口。"""
        src = _src("view_tools.js")
        assert "data-i18n='tools.default_hint'" in src
        assert 't("tools.default_hint")' in src
        assert '"tools.default_hint"' in _src("i18n.js")


# ══════════════════ P3-3 tune 启动前置校验 ══════════════════


class TestTunePrecheck:
    def test_start_calls_existence_gate_and_missing_card(self):
        """startTune 前置校验接线：探测→false 拦下+自查卡+否定 toast；
        unknown/true 放行原链路。"""
        src = _src("view_tune.js")
        assert "const _exists = await recipeFileExists(_p);" in src
        assert "if (_exists === false) {" in src
        assert "tunePathMissingCard(_p)" in src
        assert 'T.msg(t("tune.path_missing_toast"), false);' in src
        # 启动 POST 原文形态不动（路径消费收口 _p 单源）
        assert "body: JSON.stringify({ path: _p," in src

    def test_path_input_debounce_refresh(self):
        """配方信息行随输入刷新：input 挂 debounce 300ms→showRecipeInfo
        （change 通路保留）。"""
        src = _src("view_tune.js")
        assert "_tunePathEl.oninput = () => {" in src
        assert "setTimeout(showRecipeInfo, 300)" in src
        assert 'T.$("tune-path").onchange = showRecipeInfo;' in src

    def test_toast_reworded(self):
        """toast 措辞：不再"调参已启动"假成功——改"已提交，正在校验…"。"""
        i18n = _src("i18n.js")
        assert '"tune.started": { zh: "已提交，正在校验…"' in i18n
        assert "调参已启动" not in i18n  # 旧措辞退役（事件名 tune_started 是
        # 服务端事件标识符非文案，不在本钉作用域）

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_split_recipe_path_windows_and_posix(self):
        out = _run_node_js(
            "const m = await import('./pages/view_tune.js');\n"
            "const a = m.splitRecipePath('recipes/wilkinson_pd_v1.yaml');\n"
            "const b = m.splitRecipePath('E:\\\\proj\\\\my.yaml');\n"
            "const c = m.splitRecipePath('plain.yaml');\n"
            "const d = m.splitRecipePath('  ');\n"
            "console.log(JSON.stringify({a, b, c, d}));\n")
        assert out["a"] == {"dir": "recipes", "name": "wilkinson_pd_v1.yaml"}
        assert out["b"] == {"dir": "E:\\proj", "name": "my.yaml"}
        assert out["c"] == {"dir": "", "name": "plain.yaml"}
        assert out["d"] == {"dir": "", "name": ""}

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_recipe_file_exists_three_branches(self):
        """探测三分支（桩 fetch）：在盘=true / 不在=false / 信封不 ok=null
        （放行）；空路径=null。"""
        out = _run_node_js(
            "const m = await import('./pages/view_tune.js');\n"
            "const entries = [{ name: 'mkdocs.yml', kind: 'file' },\n"
            "  { name: 'wilkinson_pd_v1.yaml', kind: 'file' },\n"
            "  { name: 'recipes', kind: 'dir' }];\n"
            "globalThis.fetch = async (url) => ({ json: async () => {\n"
            "  if (String(url).includes('boom')) return { ok: false, errors: ['x'] };\n"
            "  return { ok: true, entries };\n"
            "} });\n"
            "const r = {};\n"
            "r.found = await m.recipeFileExists('recipes/wilkinson_pd_v1.yaml');\n"
            "r.missing = await m.recipeFileExists('recipes/nope.yaml');\n"
            "r.dirNotFile = await m.recipeFileExists('recipes');\n"
            "r.apiFail = await m.recipeFileExists('boom/x.yaml');\n"
            "r.emptyPath = await m.recipeFileExists('  ');\n"
            "console.log(JSON.stringify(r));\n")
        assert out == {"found": True, "missing": False, "dirNotFile": False,
                       "apiFail": None, "emptyPath": None}

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_missing_card_escapes_path_and_has_checklist(self):
        out = _run_node_js(
            "const m = await import('./pages/view_tune.js');\n"
            "const i18n = await import('./pages/i18n.js');\n"
            "const h = m.tunePathMissingCard('recipes/<b>x</b>.yaml');\n"
            "console.log(JSON.stringify({\n"
            "  escaped: !h.includes('<b>x</b>'),\n"
            "  hasCode: h.includes('<code>'),\n"
            "  role: h.includes('role=\"status\"'),\n"
            "  title: h.includes(i18n.t('tune.path_missing_title')),\n"
            "}));\n")
        assert out == {"escaped": True, "hasCode": True, "role": True,
                       "title": True}


# ══════════════════ P3-4 文件浏览器扩展名过滤 ══════════════════


class TestFileBrowserFilter:
    def test_fs_filter_entries_source_pin(self):
        """过滤单源导出 + fileBrowser 第三形参 + 徽章/空态接线在位。"""
        src = _src("filebrowser.js")
        assert "export function fsFilterEntries(entries, exts)" in src
        assert "export function fileBrowser(startPath, onPick, exts)" in src
        assert "const entries = fsFilterEntries(all, _exts);" in src
        assert 't("fs.filter_badge_tpl"' in src
        assert 't("fs.filter_empty")' in src
        assert 'import { t } from "./i18n.js";' in src

    def test_call_sites_pass_exts(self):
        """两读面调用点传扩展名（工程导入=.aedt；S 参数外部=.s1p..s8p）；
        导出另存路径选择器不过滤（写面原语义）。"""
        imp = _src("view_import.js")
        assert 'fileBrowser("", (p) => { T.$("imp-project").value = p; }, [".aedt"])' in imp
        sp = _src("view_sparams.js")
        assert '".s1p", ".s2p", ".s3p", ".s4p", ".s5p", ".s6p", ".s7p", ".s8p"' in sp

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_fs_filter_entries_truth_table(self):
        """纯函数真值表：目录恒保留/大小写不敏感后缀/exts 空=原样透传/
        恶输入不炸。"""
        out = _run_node_js(
            "const m = await import('./pages/filebrowser.js');\n"
            "const es = [{ name: 'proj.aedt', kind: 'file' },\n"
            "  { name: 'MKDOCS.YML', kind: 'file' },\n"
            "  { name: 'sub', kind: 'dir' },\n"
            "  null];\n"
            "const r = {};\n"
            "r.aedt = m.fsFilterEntries(es, ['.aedt']).map(e => e && e.name);\n"
            "r.caseInsensitive = m.fsFilterEntries(es, ['.YML']).map(e => e && e.name);\n"
            "r.noFilter = m.fsFilterEntries(es, null).length;\n"
            "r.emptyExts = m.fsFilterEntries(es, []).length;\n"
            "r.badInput = m.fsFilterEntries(null, ['.aedt']).length;\n"
            "console.log(JSON.stringify(r));\n")
        assert out["aedt"] == ["proj.aedt", "sub", None]
        assert out["caseInsensitive"] == ["MKDOCS.YML", "sub", None]
        assert out["noFilter"] == 4
        assert out["emptyExts"] == 4
        assert out["badInput"] == 0


# ══════════════════ P3-5 列表语义（ul 修正）══════════════════


class TestHelpListSemantics:
    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_help_wraps_bare_li_runs(self):
        """help() 单点兜底：连续 <li> 游程包 <ul>；跨段标点/富 HTML 不破；
         <summary> 壳原形态不变。"""
        out = _run_node_js(
            "const d = await import('./pages/dom.js');\n"
            "const h = d.help('<li>a</li>\\n<li>b</li>');\n"
            "const mixed = d.help('<p>x</p><li>c</li><li>d</li><p>y</p>');\n"
            "const preUl = d.help('<ul><li>z</li></ul>');\n"
            "const r = {\n"
            "  wrappedOnce: (h.match(/<ul>/g) || []).length === 1"
            " && h.includes('<ul><li>a</li>\\n<li>b</li></ul>'),\n"
            "  summaryShell: h.startsWith('<details class=\"help\"><summary>'),\n"
            "  mixedTwo: (mixed.match(/<ul>/g) || []).length === 1"
            " && mixed.includes('<p>x</p><ul><li>c</li><li>d</li></ul><p>y</p>'),\n"
            "  preUlUntouched: preUl === preUl && (preUl.match(/<ul>/g) || []).length === 1,\n"
            "  wrapFnSame: d.helpWrapListItems('<li>q</li>').startsWith('<ul>'),\n"
            "};\n"
            "console.log(JSON.stringify(r));\n")
        assert out == {"wrappedOnce": True, "summaryShell": True,
                       "mixedTwo": True, "preUlUntouched": True,
                       "wrapFnSame": True}

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_legacy_shell_pin_still_green(self):
        """既有钉（test_ui_modules_behavior::test_help_shell_template）同形
        断言本地复验——includes('<li>x</li>') 在包裹后仍真。"""
        out = _run_node_js(
            "const d = await import('./pages/dom.js');\n"
            "const h = d.help('<li>x</li>');\n"
            "console.log(JSON.stringify({ open: "
            "h.startsWith('<details class=\"help\"><summary>'),"
            " close: h.endsWith('</details>'), pass: h.includes('<li>x</li>') }));\n")
        assert out == {"open": True, "close": True, "pass": True}

    def test_guide_faq_and_next_explicit_ul(self):
        """view_guide 页体两块裸 li（FAQ/next，非 help() 域）显式补 <ul>。"""
        src = _src("view_guide.js")
        assert "<ul>\n      <li><b>${t(\"guide.faq1_q\")}</b>" in src
        assert "<ul>\n      <li>${t(\"guide.next_1_lead\")}" in src

    def test_no_bare_li_outside_ul_in_page_files(self):
        """全站棘轮：pages/*.js 模板内 <li> 语义合法当且仅当——(a) 处于
        help(`…`) 模板域（dom.js helpWrapListItems 渲染期兜底包 <ul>），
        或 (b) 源码显式 <ul> 语境。逐文件静态判定：剥出 help 模板域后，
        剩余文本的每个 <li> 必须在显式 <ul>…</ul> 内（view_guide FAQ/next
        显式块在档；dom.js=兜底本体豁免）。"""
        bad = []
        for p in sorted(_STATIC.glob("pages/*.js")):
            if p.name == "dom.js":
                continue  # 兜底本体（helpWrapListItems 单源）
            s = p.read_text(encoding="utf-8")
            if "<li" not in s:
                continue
            # 剥出 help(`…`) 模板域（反引号配对；仓内 help 实参无嵌套反引号）
            out, i = [], 0
            while True:
                j = s.find("help(`", i)
                if j < 0:
                    out.append(s[i:])
                    break
                out.append(s[i:j])
                k = s.find("`", j + 6)
                assert k > 0, f"{p.name}: help 模板反引号未闭合"
                i = k + 1
            rest = "".join(out)
            # 剥块注释（文档性 <li> 字样在头注出现——view_guide 实证）；
            # 行注释保留（// 后无模板标记语义，不影响判定）。
            rest = re.sub(r"/\*.*?\*/", "", rest, flags=re.S)
            depth, k, ok = 0, 0, True
            while k < len(rest):
                if rest.startswith("<ul", k):
                    depth += 1
                    k += 3
                elif rest.startswith("</ul>", k):
                    depth -= 1
                    k += 5
                elif rest.startswith("<li", k) and depth <= 0:
                    ok = False
                    break
                else:
                    k += 1
            if not ok:
                bad.append(p.name)
        assert bad == [], f"裸 <li>（help 域外且无显式 <ul>）: {bad}"


# ══════════════════ P2-4 CLI --help 按域分组 ══════════════════

_PANELS = ("核心工作流", "综合与设计", "分析与研究", "数据与知识",
           "报告与复现", "环境与可靠性", "自动化与协作", "运维与开发")


def _cli_top_command():
    from typer.main import get_command

    from rfauto.cli.main import app

    return get_command(app)


class TestCliHelpPanels:
    def test_help_groups_module_mapping_complete(self):
        """映射覆盖完整性：HELP_PANEL_OF 键集 == 注册树顶层命令名集
        （新命令=显式评审动作：注册序金快照与本断言双钉，缺面板即红并
        指路 help_groups.py 补表）。"""
        from rfauto.cli.help_groups import HELP_PANEL_OF

        top = _cli_top_command()
        names = set(top.commands.keys())
        assert set(HELP_PANEL_OF.keys()) == names, (
            "help 面板映射与顶层命令集失配: "
            f"缺 {sorted(names - set(HELP_PANEL_OF))} "
            f"多 {sorted(set(HELP_PANEL_OF) - names)}"
            "（新命令请同步 cli/help_groups.py HELP_PANEL_OF 补面板）")
        # 面板名闭合于 8 域 + D-06 字符纪律（rich markup 面：零裸 [ 零 %）
        assert set(HELP_PANEL_OF.values()) <= set(_PANELS)
        for panel in HELP_PANEL_OF.values():
            assert "[" not in panel and "%" not in panel

    def test_apply_panels_idempotent_and_rendered(self):
        """行为钉：全树顶层命令带面板；缺省 Commands 面板消失（全覆盖的
        可观测面）；apply_help_panels 幂等（二次调用零新增）。"""
        from typer.testing import CliRunner

        from rfauto.cli.help_groups import apply_help_panels
        from rfauto.cli.main import app

        n1 = apply_help_panels(app)
        n2 = apply_help_panels(app)
        assert n1 == 0 and n2 == 0  # main.py 导入期已挂满→重挂零新增（幂等）
        top = _cli_top_command()
        paneled = {getattr(c, "rich_help_panel", None)
                   for c in top.commands.values()}
        assert None not in paneled, "存在未挂面板的顶层命令"
        assert paneled <= set(_PANELS)
        out = CliRunner().invoke(app, ["--help"]).output
        for panel in _PANELS:
            assert panel in out, f"--help 缺面板 {panel}"
        assert "─ Commands " not in out, "缺省 Commands 面板应被 8 域全覆盖取代"

    def test_registration_face_untouched(self):
        """红线钉：分组只挂渲染注记——注册序/计数/命名零变化（与
        test_cli_registration_order 同源读面，此处钉不变性）。"""
        top = _cli_top_command()
        # 顶层命令数（check_numbers n_top 口径镜像；aurora_p G1
        # 2026-11-02 126→127 重钉——cal-wizard 顶层域入树：TRL 校准件
        # 设计向导叶（方向 G"TRL/校准件设计的用户向导面（当前只有内核
        # +CLI）"闭合：频带+介质三口径 → Thru/Reflect/Line 设计单——
        # λg/4 Line、8:1 覆盖三态核算、多 Line 等比分带、Reflect 短路/
        # 开路建议；--out-dir 落盘设计单 JSON/calkit 定义 YAML/测试连接
        # 图 .drawio 三件固定名），core/trl_design 设计数学（教科书锚+
        # 微带 εeff 走 synthesis 单源）+service/cal_wizard_service 薄壳；
        # 上锚=aurora_p F2
        # 2026-11-02 125→126 重钉——watchdog 顶层域入树：seat 粒度三证判活
        # CLI 出口（T-O12 service/watchdog_service 常驻形态接线，watch
        # 单叶双形态——一次性视图=缺省动作、--watch 常驻循环显式开启默认
        # 关），service/watchdog_service 薄壳；上锚=
        # aurora_o T-O4
        # 2026-11-01 124→125 重钉——ads-circuit 顶层域入树：ADS 前仿链人机
        # 回路三叶 diagram/run/annotate（用户核心需求"画电路图→带入 ADS
        # 仿真→人工调参回路"），service/circuit_sim_service 薄壳；上锚=
        # aurora_o T-O5 2026-11-01 123→124 重钉——design-report 顶层连字叶
        # 入树：设计回放与总结报告（六节 md，优化族报告主缺口补齐），
        # service/design_replay_report 薄壳；上锚=aurora_o T-O1 2026-10-31
        # 122→123 重钉——diagram 域入树：RF 链路框图 .drawio 生成叶 link，
        # 算画同源第一件，Friis 数字=内核单源 core/budget.py LinkBudget；
        # 再上锚=aurora_n O4 2026-10-31 119→122 重钉——O1 mo/O5 competition/
        # O4 al 三域入树，O1/O5 席漏钉本镜像红两轮，随 O4 席邻接回归一并
        # 清偿）
        # 上锚=T-Q7b（Q-W3-2 2026-11-04）loop 顶层域入树 128→129 重钉
        # （自主闭环编排器一叶 run：Proposal→既有确定性链→Quality-Checker
        # →报告阶段状态机，决策①双模 --mode+--resume 中断续作；
        # closed_loop.orchestrator 薄壳）——镜像钉随顶层命令集同笔（先例=
        # T-Q15 chat-test-connection 127→128 行注）
        # 上锚=T-Q3（Q-W5-2R 2026-11-04）anim 顶层域入树 129→130 重钉
        # （动图渲染一叶 render：typed spec JSON→SVG 动画；
        # anim_render_service 薄壳，aurora_q 方向 B）
        # 上锚=T-Q19 批 2（Q-W9-3 2026-11-06）vendor-docs 顶层域入树
        # 130→131 重钉（厂商帮助文档检索三叶 build/search/audit：
        # vendor_doc_service 薄壳，--db 必填不落缺省库位，aurora_q 方向 E）
        # 上锚=T-Q34/T-Q22/T-Q27（Q-X34/Q-X33/Q-X32 2026-11-07 同窗并行）
        # liberty/spice/skill 三顶层域入树 131→134 重钉（同窗多席计数时序：
        # 本镜像钉由在树面实测的席按序收口）
        # 上锚=T-Q36（Q-X36 2026-11-07）sdc 顶层域入树 134→135 重钉
        # （SDC 约束结构化解析两叶 parse/list：Tcl 词法+SDC 语义内核
        # core/sdc_parser 单源+service/sdc_service 薄壳，数字自动化借鉴
        # 方向）
        # 上锚=T-Q37/T-Q26e（Q-X37/Q-X39 2026-11-07 同窗并行落树）
        # exploded-view/layer-3d 两顶层域入树 135→137 重钉（爆炸视图
        # 单场景渲染/逐层 3D 渲染导出两域——本镜像钉由在树面实测的席
        # 按序收口，同窗多席计数时序先例同上）
        # 上锚=aurora_q Q-X48 2026-11-07 drc/lvs/ibis 三顶层域入树
        # 137→140 重钉（DRC 规则文件结构化解析/LVS 对比/IBIS .ibs 解析
        # 三域；drc 本席落树+2 叶，lvs/ibis 同窗并发席在树注册计数钉未
        # 动——本席按在树面实测收口如实折入，Q-X39 折 Q-X37 先例同款）
        # 上锚=aurora_q Q-X47 2026-11-07 verilog 顶层域入树 140→141 重钉
        # （Verilog 网表结构化解析两叶 parse/list：core/verilog_netlist_
        # parser 单源+service/verilog_netlist_service 薄壳，数字自动化
        # 借鉴方向——本镜像钉由在树面实测的席按序收口）
        # aurora_r 合流笔 2026-11-10：解析器集群 16 顶层组接线 141→157
        # （FINAL_AUDIT §二A：citi/sdf/gdsii/touchstone/ipc356/lefdef/stil/
        # skill_parse/odbpp/bsdl/spectre/veriloga/stdf/ibis-ami 十四独立根
        # +spef/vcd 自注册 re-export，HELP_PANEL_OF 16 行同笔补）
        # 上锚=aurora_r AM-S4 2026-11-10 aedt-migrate 顶层域入树 157→158
        # 重钉（老版本 .aedt 批量迁移三叶 run/status/report——citi 同款
        # 独立根 re-export+add_typer，HELP_PANEL_OF 归"运维与开发"：
        # AEDT 版本迁移=工具链/环境维护动作，remote/solvers 同域）
        assert len(top.commands) == 158  # v0.14.0 移除笔：loop 域摘除（专利冻结面，tri-view 后 159→158）
        assert "doctor" in top.commands and "run" in top.commands

    def test_subapp_help_unaffected(self):
        """子应用帮助页不因顶层面板变化（bench 组 --help 原样可用）。"""
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        r = CliRunner().invoke(app, ["bench", "--help"])
        assert r.exit_code == 0
        assert "Commands" in r.output  # 子应用内部仍是标准 Commands 面
