"""aurora_f W1-S2 席位回归钉：UI i18n 骨架 + 静态壳/三试点页（tools/gallery/queue）
+ W6-S21 扩面五页（dashboard/runs/detail/sparams/agent）
+ W8-S32 批 3（timeline 页接线=第 9 页；dashboard 控件钮/KPI/activity/图表
系列名与 help 分段深化、detail/agent 补点——键集互证按九页视图扫描）
+ W2-S1 批 4（aurora_g：view_data 三页（datasets/anchors/uq）+ view_guide
接线=11 视图扫描；kit.js 共享组件三缺省串入壳面引用集（dom.js help summary
同款口径——kit 是 11 视图错误/空态单源））
+ aurora_h W4-S1（半程三页收尾+新页壳层）：键集互证扩到 16 视图——
loopboard/tune/reports/recipe/campaign 五页入扫描域（loopboard 全清+
新四页壳层迁移，agent 全清；tools 协议组名表=刻意保留不计入文案面）
+ 发布前置 i18n 软编码批 S2：键集互证扩到 20 视图——optstack/solvers/
profile/playground 四页入扫描域（S2 席六页 optstack/solvers/profile/
playground/queue/detail 全清；queue/detail 为既有域残量清零）
+ 发布前置 i18n 软编码批 S1：键集互证扩到 23 视图——fieldviz/calibration/
import 三页入扫描域（S1 席三页全清；view_fieldviz 承 farfield/field 双页
共壳，fieldviz.* 单域；import 域键名与 ES import 语句无字面冲突——键字面
形如 "import.xxx" 仅 t()/data-i18n 注入口出现）。

规格=runs/aurora_f/R1_ui_v8_audit.md §面2（W5-S23 决议"自研词表+t()"落地）
+ runs/aurora_g/R1_ui_v9_audit.md §面2（P9-5/P9-6）。

钉五层：
1. 骨架行为（node 真执行，缺 node skip）：t() zh/en 真值表 + {name} 占位
   插值 + 缺键→键名直返 + en 缺值→zh fallback + getLocale 缺省跟随 +
   setLocale 非法档拒绝；applyI18nRoot 三注入口（[data-i18n]→textContent、
   [data-i18n-ph]→placeholder、[data-i18n-aria]→aria-label；桩 DOM）+
   非 DOM root 零副作用；LOCALES 每键 zh/en 双语齐全 + 键命名契约 +
   词表值零 HTML。
2. 键集互证（node 键集 × 源码引用，双向）：index.html + 十一视图视图
   data-i18n*/t() 引用 ⊆ LOCALES（悬空引用即红）；壳面键（nav./nav.group./
   common./palette./foot.）全部在 index.html/dom.js/kit.js 有引用（死键即红；
   共享模块消费与 index.html 引用同权）；nav.* 键集 == data-v 全集（26，
   键名=data-v 单源对齐）；各页前缀键在对应视图文件有引用（死键即红；
   跨页复用键如 nav.*/runs.th_inband_s11 归属键域页，他页复用只增引用不减）。
3. esc 共存纪律（源码钉，R1 规格写死）：i18n.js 零 innerHTML；纪律头注
   在档（"禁止 t() 包数据"）。
4. 接线存在性（源码钉）：pages.js initPages applyI18nRoot(document) 装配；
   十一视图 applyI18nRoot(v) 壳首扫。
5. 语法：node --check pages/i18n.js（test_w5s23 清单已收录，此处兜底）。
6. hardcode 棘轮（W2-S1 批 4，R1 §面2 P9-6 常驻化）：委托
   scripts/check_ui_i18n_coverage.py 对 static 树做"字面量 CJK 基线账本"
   只减不增扫描（新 hardcode 超基线即红；迁移批顺笔减账走 --update）。

不依赖 runs/、不读网络、不启动服务器。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

_I18N = (_STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")
_INDEX = (_STATIC / "index.html").read_text(encoding="utf-8")
_VIEWS = {
    "tools": (_STATIC / "pages" / "view_tools.js").read_text(encoding="utf-8"),
    "gallery": (_STATIC / "pages" / "view_gallery.js").read_text(encoding="utf-8"),
    "queue": (_STATIC / "pages" / "view_queue.js").read_text(encoding="utf-8"),
    # W6-S21 扩面五页（批 2）
    "dashboard": (_STATIC / "pages" / "view_dashboard.js").read_text(encoding="utf-8"),
    "runs": (_STATIC / "pages" / "view_runs.js").read_text(encoding="utf-8"),
    "detail": (_STATIC / "pages" / "view_detail.js").read_text(encoding="utf-8"),
    "sparams": (_STATIC / "pages" / "view_sparams.js").read_text(encoding="utf-8"),
    "agent": (_STATIC / "pages" / "view_agent.js").read_text(encoding="utf-8"),
    # W8-S32 批 3（timeline 页接线=第 9 页）
    "timeline": (_STATIC / "pages" / "view_timeline.js").read_text(encoding="utf-8"),
    # W2-S1 批 4（data=三页共壳 datasets/anchors/uq；guide=纯静态页）
    "data": (_STATIC / "pages" / "view_data.js").read_text(encoding="utf-8"),
    "guide": (_STATIC / "pages" / "view_guide.js").read_text(encoding="utf-8"),
    # aurora_h W4-S1（半程三页收尾+新页壳层五页入扫描域）
    "loopboard": (_STATIC / "pages" / "view_loopboard.js").read_text(encoding="utf-8"),
    "tune": (_STATIC / "pages" / "view_tune.js").read_text(encoding="utf-8"),
    "reports": (_STATIC / "pages" / "view_reports.js").read_text(encoding="utf-8"),
    "recipe": (_STATIC / "pages" / "view_recipe.js").read_text(encoding="utf-8"),
    "campaign": (_STATIC / "pages" / "view_campaign.js").read_text(encoding="utf-8"),
    # 发布前置 i18n 软编码批 S2（本席六页余四页入扫描域；queue/detail 已在域）
    "optstack": (_STATIC / "pages" / "view_optstack.js").read_text(encoding="utf-8"),
    "solvers": (_STATIC / "pages" / "view_solvers.js").read_text(encoding="utf-8"),
    "profile": (_STATIC / "pages" / "view_profile.js").read_text(encoding="utf-8"),
    "playground": (_STATIC / "pages" / "view_playground.js").read_text(encoding="utf-8"),
    # 发布前置 i18n 软编码批 S1（三页全清；fieldviz=farfield/field 双页共壳）
    "fieldviz": (_STATIC / "pages" / "view_fieldviz.js").read_text(encoding="utf-8"),
    "calibration": (_STATIC / "pages" / "view_calibration.js").read_text(encoding="utf-8"),
    "import": (_STATIC / "pages" / "view_import.js").read_text(encoding="utf-8"),
}
_PAGES_JS = (_STATIC / "pages.js").read_text(encoding="utf-8")
# W8-S32 批 3：help() 壳 summary 由 dom.js t() 渲染期烘焙（26 调用点单点）——
# 共享模块消费与 index.html 引用同权计入壳面引用集（死键互证口径）。
# W2-S1 批 4：kit.js 同款入集（common.empty/load_failed/retry 三缺省串，
# 11 视图错误/空态单源）。
_DOM_JS = (_STATIC / "pages" / "dom.js").read_text(encoding="utf-8")
_KIT_JS = (_STATIC / "pages" / "kit.js").read_text(encoding="utf-8")

_SHELL_PREFIXES = ("nav.", "common.", "palette.", "foot.")


def _attr_refs(src: str) -> set[str]:
    """data-i18n / data-i18n-ph / data-i18n-aria 引用键集（单双引号都收）。"""
    return set(re.findall(r"data-i18n(?:-ph|-aria)?=['\"]([^'\"]+)['\"]", src))


def _t_refs(src: str) -> set[str]:
    """t("key") 渲染期烘焙引用键集（动态容器文案走此通道）。"""
    return set(re.findall(r'\bt\("([^"]+)"', src))


# 动态映射字面量通道：视图内以页前缀形态出现的键字面（如 view_dashboard
# widget 注册表 `tk: "dashboard.w_kpi"`，渲染期 t(w.tk) 动态实参——t("字面")
# 正则抓不到，按引号字面补收，W6-S21 扩面；W8-S32 批 3 收录 timeline 域；
# aurora_h W4-S1 收录 loopboard/tune/reports/recipe/campaign 五域；
# 发布前置软编码批 S2 收录 optstack/solvers/profile/playground 四域；
# 发布前置软编码批 S1 收录 fieldviz/calibration/import 三域）。
_PAGE_KEY_LIT = re.compile(
    r"""['"]((?:tools|gallery|queue|dashboard|runs|detail|sparams|agent|timeline|loopboard|tune|reports|recipe|campaign|optstack|solvers|profile|playground|fieldviz|calibration|import)\.[a-z0-9_]+)['"]""")


def _view_refs(src: str) -> set[str]:
    """视图侧 i18n 键引用全集：attr 三通道 + t() 字面 + 动态映射字面量。"""
    return _attr_refs(src) | _t_refs(src) | set(_PAGE_KEY_LIT.findall(src))


_APP_JS = (_STATIC / "app.js").read_text(encoding="utf-8")


def _shell_refs() -> set[str]:
    """壳面引用集：index.html attr 三通道 + dom.js t() 烘焙（help summary）
    + kit.js t() 烘焙（common.empty/load_failed/retry 三缺省串——共享组件
    与 index.html 引用同权，W2-S1 批 4）+ app.js t() 烘焙（common.offline/
    online 离线检测提示串——壳 toast 单源消费，与 kit.js 同款口径，
    W14-S2）。"""
    return _attr_refs(_INDEX) | _t_refs(_DOM_JS) | _t_refs(_KIT_JS) | _t_refs(_APP_JS)


def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return r.stdout


# ────────────────────────── 1. 骨架行为（node 真执行） ──────────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestI18nSkeletonNode:
    def test_t_truth_table_placeholder_fallback(self):
        # node 无 localStorage/document：语言档缺省判定走 zh 兜底路径
        out = _run_node_js(
            "const m = await import('./pages/i18n.js');\n"
            "const errs = [];\n"
            "const eq = (a, b, msg) => { if (a !== b) errs.push(msg + ': ' +\n"
            "  JSON.stringify(a) + ' != ' + JSON.stringify(b)); };\n"
            "if (m.getLocale() !== 'zh') errs.push('缺省 locale=' + m.getLocale());\n"
            "eq(m.t('nav.dashboard'), '总览', 't zh');\n"
            "eq(m.t('gallery.count_tpl', { n: 3, p: 2 }), '3 个模板 · 其中 2 个支持闭式预览', '插值 zh');\n"
            "eq(m.t('dashboard.aria_span_tpl', { name: 'KPI' }), '加宽/收窄组件：KPI', 'aria tpl zh');\n"
            "if (m.setLocale('en') !== true) errs.push('setLocale en 拒绝');\n"
            "if (m.getLocale() !== 'en') errs.push('getLocale en');\n"
            "eq(m.t('nav.dashboard'), 'Dashboard', 't en');\n"
            "eq(m.t('tools.run'), 'Compute', 't en tools');\n"
            "eq(m.t('gallery.count_tpl', { n: 3, p: 2 }),\n"
            "  '3 templates · 2 of them support closed-form preview', '插值 en');\n"
            "eq(m.t('dashboard.aria_span_tpl', { name: 'KPI' }),\n"
            "  'Resize widget: KPI', 'aria tpl en');\n"
            "eq(m.t('no.such.key'), 'no.such.key', '缺键直返');\n"
            "eq(m.t('no.such.key', { a: 1 }), 'no.such.key', '缺键带参直返');\n"
            "m.LOCALES['test.only_zh'] = { zh: '中文值' };\n"
            "eq(m.t('test.only_zh'), '中文值', 'en 缺 zh fallback');\n"
            "delete m.LOCALES['test.only_zh'];\n"
            "if (m.setLocale('fr') !== false) errs.push('非法档应拒绝');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:t');\n")
        assert "ok:t" in out

    def test_apply_i18n_root_three_channels(self):
        out = _run_node_js(
            "const m = await import('./pages/i18n.js');\n"
            "m.setLocale('en');\n"
            "const txt = { text: '' };\n"
            "Object.defineProperty(txt, 'textContent', {\n"
            "  set(v) { txt.text = v; }, get() { return txt.text; } });\n"
            "txt.getAttribute = (n) => (n === 'data-i18n' ? 'nav.dashboard' : null);\n"
            "const ph = { attrs: {}, getAttribute: () => 'palette.placeholder',\n"
            "  setAttribute(n, v) { this.attrs[n] = v; } };\n"
            "const ar = { attrs: {}, getAttribute: () => 'common.aside_aria',\n"
            "  setAttribute(n, v) { this.attrs[n] = v; } };\n"
            "const root = { querySelectorAll: (sel) =>\n"
            "  sel === '[data-i18n]' ? [txt]\n"
            "  : sel === '[data-i18n-ph]' ? [ph]\n"
            "  : sel === '[data-i18n-aria]' ? [ar] : [] };\n"
            "const n = m.applyI18nRoot(root);\n"
            "const errs = [];\n"
            "if (n !== 3) errs.push('应用条数=' + n);\n"
            "if (txt.text !== 'Dashboard') errs.push('textContent=' + txt.text);\n"
            "if (ph.attrs['placeholder'] !== 'Jump to page, # search runs, > commands…')\n"
            "  errs.push('placeholder=' + ph.attrs['placeholder']);\n"
            "if (ar.attrs['aria-label'] !== 'Sidebar') errs.push('aria=' + ar.attrs['aria-label']);\n"
            "if (m.applyI18nRoot(null) !== 0) errs.push('null root');\n"
            "if (m.applyI18nRoot({}) !== 0) errs.push('空 root');\n"
            "m.setLocale('zh');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:apply');\n")
        assert "ok:apply" in out

    def test_locales_bilingual_complete_and_html_free(self):
        out = _run_node_js(
            "const m = await import('./pages/i18n.js');\n"
            "const errs = [];\n"
            "const keyRe = /^[a-z][a-z0-9_]*(\\.[a-z0-9_]+)+$/;\n"
            "const htmlRe = /<\\/?[a-zA-Z]/;\n"
            "const keys = Object.keys(m.LOCALES);\n"
            "if (keys.length < 120) errs.push('词表规模异常=' + keys.length);\n"
            "for (const k of keys) {\n"
            "  if (!keyRe.test(k)) errs.push('键命名: ' + k);\n"
            "  const e = m.LOCALES[k];\n"
            "  if (typeof e.zh !== 'string' || !e.zh) errs.push('zh 缺: ' + k);\n"
            "  if (typeof e.en !== 'string' || !e.en) errs.push('en 缺: ' + k);\n"
            "  if (htmlRe.test(e.zh) || htmlRe.test(e.en)) errs.push('值含 HTML: ' + k);\n"
            "}\n"
            "if (errs.length) throw new Error(errs.slice(0, 10).join('; '));\n"
            "console.log('ok:locales:' + keys.length);\n")
        assert "ok:locales:" in out


# ────────────────────────── 2. 键集互证（双向） ──────────────────────────

def _locale_keys() -> set[str]:
    out = _run_node_js(
        "const m = await import('./pages/i18n.js');\n"
        "console.log(JSON.stringify(Object.keys(m.LOCALES)));\n")
    return set(json.loads(out.strip()))


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestKeySetCrossValidation:
    def test_all_attr_refs_resolve(self):
        keys = _locale_keys()
        refs = _shell_refs()
        for src in _VIEWS.values():
            refs |= _view_refs(src)
        dangling = refs - keys
        assert not dangling, f"i18n 引用悬空（词表无此键）: {sorted(dangling)}"

    def test_shell_keys_all_referenced_no_dead_keys(self):
        keys = _locale_keys()
        dead = {k for k in keys if k.startswith(_SHELL_PREFIXES)} - _shell_refs()
        assert not dead, f"壳面死键（index.html/dom.js/kit.js 无引用）: {sorted(dead)}"
        # 视图→页前缀键域（一视图多前缀：view_data 三页共壳）
        page_prefixes = (
            ("tools", ("tools.",)), ("gallery", ("gallery.",)), ("queue", ("queue.",)),
            ("dashboard", ("dashboard.",)), ("runs", ("runs.",)),
            ("detail", ("detail.",)), ("sparams", ("sparams.",)), ("agent", ("agent.",)),
            ("timeline", ("timeline.",)),
            # W2-S1 批 4（data=datasets/anchors/uq 三页共壳；guide）
            ("data", ("datasets.", "anchors.", "uq.")), ("guide", ("guide.",)),
            # aurora_h W4-S1（半程收尾+新页壳层五页入域）
            ("loopboard", ("loopboard.",)), ("tune", ("tune.",)),
            ("reports", ("reports.",)), ("recipe", ("recipe.",)),
            ("campaign", ("campaign.",)),
            # 发布前置软编码批 S2（本席四页入域；queue/detail 既有域）
            ("optstack", ("optstack.",)), ("solvers", ("solvers.",)),
            ("profile", ("profile.",)), ("playground", ("playground.",)),
            # 发布前置软编码批 S1（三页入域；fieldviz 双页共壳单域）
            ("fieldviz", ("fieldviz.",)), ("calibration", ("calibration.",)),
            ("import", ("import.",)))
        for view, prefixes in page_prefixes:
            refs = _view_refs(_VIEWS[view])
            dead = {k for k in keys
                    if any(k.startswith(p) for p in prefixes)} - refs
            assert not dead, f"{view} 死键: {sorted(dead)}"

    def test_nav_keys_align_data_v_registry(self):
        nav_block = re.search(r'<nav id="nav".*?</nav>', _INDEX, re.S).group(0)
        data_v = set(re.findall(r'data-v="([\w-]+)"', nav_block))
        nav_refs = set(re.findall(r'data-i18n="nav\.([\w-]+)"', nav_block))
        assert len(re.findall(r'data-v="', nav_block)) == 26, "nav data-v 总数漂移"
        assert nav_refs == data_v, (
            f"nav.* 键与 data-v 注册表失配: 缺 {sorted(data_v - nav_refs)} "
            f"多 {sorted(nav_refs - data_v)}")
        # 词表侧同口径（排除 nav.group.* 分组键）
        nav_keys = {k[4:] for k in _locale_keys()
                    if k.startswith("nav.") and not k.startswith("nav.group.")}
        assert nav_keys == data_v, f"词表 nav.* 与 data-v 失配: {nav_keys ^ data_v}"


# ────────────────────────── 3. esc 共存纪律（源码钉） ──────────────────────────

class TestEscCoexistenceDiscipline:
    def test_no_inner_html_and_discipline_header(self):
        # R1 规格写死：词表值永不含 HTML（三注入口 textContent/placeholder/
        # aria 零 innerHTML）；纪律头注必须在档。口径=属性访问形态
        # （.innerHTML）不得出现在源码——头注里"零 innerHTML"的字样不算违例。
        assert ".innerHTML" not in _I18N, "i18n.js 出现 innerHTML 访问（违头注纪律）"
        assert "禁止 t() 包数据" in _I18N, "esc 共存纪律头注缺失"
        assert "词表值永不含 HTML" in _I18N

    def test_view_sink_discipline(self):
        # 十一视图：data-i18n 只放静态壳；随数据重建的动态容器不得挂
        # data-i18n（setLocale 重扫会覆写动态内容——i18n.js 头注纪律）。
        for name, src in _VIEWS.items():
            assert 'from "./i18n.js"' in src, f"{name} 未接 i18n"
        assert re.search(r"id='tool-result'", _VIEWS["tools"])
        assert re.search(r"<div id='tool-desc'[^>]*data-i18n", _VIEWS["tools"]) is None
        assert re.search(r"<div id='tool-result'[^>]*data-i18n", _VIEWS["tools"]) is None
        assert re.search(r"id='gal-grid'", _VIEWS["gallery"])
        assert re.search(r"<div id='gal-grid'[^>]*data-i18n", _VIEWS["gallery"]) is None


# ────────────────────────── 4. 接线存在性（源码钉） ──────────────────────────

class TestWiring:
    def test_pages_js_boot_scan(self):
        assert 'import { applyI18nRoot, getLocale } from "./pages/i18n.js";' in _PAGES_JS
        assert "applyI18nRoot(document);" in _PAGES_JS, "initPages 壳首扫装配缺失"

    def test_view_pages_shell_rescan(self):
        # 三试点页 + W6-S21 扩面五页 + W8-S32 批 3 timeline + W2-S1 批 4
        # data/guide：壳渲染完 applyI18nRoot(v) 首扫在位
        for name, src in _VIEWS.items():
            assert re.search(r"applyI18nRoot\(v\);", src), f"{name} 壳首扫缺失"

    def test_node_check_i18n_js(self):
        assert _NODE is not None, "本机无 node"
        r = subprocess.run([_NODE, "--check", str(_STATIC / "pages" / "i18n.js")],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"node --check i18n.js:\n{r.stderr[-2000:]}"


# ────────────────────────── 6. hardcode 棘轮（W2-S1 批 4） ──────────────────────────

class TestHardcodeRatchet:
    """R1 §面2 P9-6 常驻化：委托 scripts/check_ui_i18n_coverage.py 对 static
    树做"字面量 CJK 基线账本只减不增"对账（行注释/块注释天然豁免——只扫
    三态字面量；白名单=pages/i18n.js 词表本体+vendor/）。新 hardcode 超基线
    即红；迁移批减账走脚本 --update 重生基线同笔提交。纯 python，零 node
    依赖（与 1/2 层 node 钉独立）；static 树不可读=脚本 rc2，此处按环境类
    skip 诚实降级（#122 三分法①）。"""

    def test_ratchet_no_regrowth(self):
        script = Path(__file__).resolve().parents[2] / "scripts" / "check_ui_i18n_coverage.py"
        r = subprocess.run([sys.executable, str(script)],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        if r.returncode == 2:
            pytest.skip("static 树不可读（环境类 SKIP）")
        assert r.returncode == 0, (
            "i18n hardcode 棘轮回潮（新 CJK 字面量超基线——文案进词表，"
            f"勿手写字面）:\n{r.stdout[-2000:]}")


# ────────────────── 7. 画廊详情抽屉覆盖（R2 人性化席 2026-10-19） ──────────────────

class TestGalleryDrawerCoverage:
    """R2 人性化改造席（模板画廊用户实测批次）：72 卡全量详情抽屉的
    前端逻辑自证——

    1. 词表覆盖：每个注册模板（TEMPLATE_META 全量）都有 gallery.desc_%
       词表键且 zh/en 双语（抽屉①一句话人话说明的数据源；72/72，
       键名小写化契约 ms_array_NxN→desc_ms_array_nxn）；
    2. 视图字面表覆盖：view_gallery.js DESC_KEYS 逐一引用（动态拼键
       逃逸 _PAGE_KEY_LIT 键集互证的画廊面补强，缺一即死键/回退链）；
    3. 抽屉三件套在位：说明（cardDesc）+ 参数白话表（parseSemantics
       语义段解析+GLOSS 兜底+origin 来源列）+ 预览诚实边界
       （preview_uncovered 一行，替代满屏"未配通道"徽标）；
    4. 语法兜底：node --check view_gallery.js（同 i18n.js 层 5 口径——
       本文件原无 view 语法钉，抽屉 DOM 组装面新增后补齐）。"""

    def test_desc_keys_cover_all_templates_bilingual(self):
        from rfauto.adapters.openems_templates import TEMPLATE_META

        assert _NODE is not None, "本机无 node"
        out = _run_node_js(
            "const m = await import('./pages/i18n.js');\n"
            "const desc = {};\n"
            "for (const k of Object.keys(m.LOCALES))\n"
            "  if (k.startsWith('gallery.desc_')) {\n"
            "    const e = m.LOCALES[k];\n"
            "    desc[k] = (typeof e.zh === 'string' && e.zh\n"
            "      && typeof e.en === 'string' && e.en) ? 1 : 0;\n"
            "  }\n"
            "console.log(JSON.stringify(desc));\n")
        desc = json.loads(out.strip())
        missing = [n for n in TEMPLATE_META
                   if f"gallery.desc_{n.lower()}" not in desc
                   or desc[f"gallery.desc_{n.lower()}"] != 1]
        assert not missing, (
            "模板缺 gallery.desc_* 词表键（或 zh/en 缺半边）: "
            f"{sorted(missing)}——抽屉①说明数据源必须 72/72 全覆盖")

    def test_desc_keys_literal_table_covers_all_templates(self):
        from rfauto.adapters.openems_templates import TEMPLATE_META

        src = _VIEWS["gallery"]
        table = re.search(r"const DESC_KEYS = \{.*?\n\};", src, re.S)
        assert table, "DESC_KEYS 字面映射表缺席"
        missing = [n for n in TEMPLATE_META
                   if f'"gallery.desc_{n.lower()}"' not in table.group(0)]
        assert not missing, (
            f"DESC_KEYS 映射表缺模板（键集互证盲区补钉）: {sorted(missing)}")

    def test_drawer_surface_pins(self):
        src = _VIEWS["gallery"]
        assert "function openDrawer(" in src, "详情抽屉开函缺席"
        assert "function parseSemantics(" in src, "语义白话段解析器缺席"
        assert "data-slot='preview'" in src, "抽屉预览槽缺席"
        assert "gallery.preview_uncovered" in src, "预览诚实边界键未消费"
        assert "gallery.origin_nominal" in src, "数值来源列（名义值）缺席"
        # 卡面瘦身：参数串不再整卡平铺（旧 Object.entries 拼串形态退场，
        # 参数表折叠进抽屉——抽屉内 orderedParams 逐行消费属合法面）
        assert "Object.entries(c.nominal_params" not in src, (
            "卡面仍平铺参数串（应折叠进抽屉）")
        # 满屏"未配通道"徽标退场：no_preview 仅作卡角小标记（预览钮不再
        # 以 preview 有无二分支——详情钮全量在位）
        assert "gallery.detail_btn" in src
        assert 'data-gal=' in src

    def test_credibility_anchor_surface(self):
        """W2-S1（aurora_i，R3 设计 M1 零新端点）：抽屉可信度锚对照卡面钉。

        1. 槽与渲染单点：抽屉 data-slot='credibility' + 渲染函数在位；
        2. 过滤口径双钉：engine_pair.referee=hfss（注册表现役 17 条仲裁
           锚）× template_family 精确命中或 "*" 通配（注册表语义原样
           消费，前端不自创映射）；
        3. 诚实边界四件套：无锚诚实行 / 清单失败降级行 / 详情在途
           （pending）与无判定记录（UNKNOWN）两徽章分立 / 双值指针锚
           values 并列渲染（#122 家族：DISAGREE 不凑绿不隐藏）；
        4. verdict 三分类 DISAGREE 先判（长串态内可并列 AGREE_JUDGE
           "单项不救总态"字样——先红后绿防误绿）；
        5. 证据目录纯文本：runs/ 缺省不挂载（R2-B-05），锚卡不渲染链接。"""
        src = _VIEWS["gallery"]
        assert 'data-slot=\'credibility\'' in src, "抽屉可信度槽缺席"
        assert "function renderCredibilityInto(" in src, "可信度节渲染单点缺席"
        assert 'referee === "hfss"' in src, "仲裁锚过滤口径（referee=hfss）缺席"
        assert 'indexOf("*") >= 0' in src, "template_family * 通配匹配缺席"
        assert "gallery.anchor_none" in src, "无锚诚实行键未消费"
        assert "gallery.anchor_load_fail" in src, "清单失败降级键未消费"
        assert "gallery.anchor_verdict_pending" in src, "详情在途徽章键未消费"
        assert "gallery.anchor_verdict_unknown" in src, "UNKNOWN 徽章键未消费"
        assert "gallery.anchor_values_tpl" in src, "双值指针锚并列渲染键未消费"
        # 门/观测分裂标签二分：DISAGREE 指针锚的 uncertainty 是观测分裂
        # 幅度非预声明门——误标即把观测值当判据（#122 诚实呈现家族）；
        # 前缀 CJK 字面走 \u 转义（view_gallery 字面量 Han 基线=0 棘轮）
        assert "gallery.anchor_observed_split_tpl" in src, "观测分裂标签键未消费"
        assert "\\u89c2\\u6d4b" in src, "观测 note 前缀匹配（\\u 转义形态）缺席"
        vfn = re.search(r"function anchorVerdictOf\(.*?\n\}", src, re.S)
        assert vfn, "verdict 三分类函数缺席"
        body = vfn.group(0)
        assert body.index("DISAGREE") < body.index("AGREE"), (
            "verdict 分类须 DISAGREE 先判（长串态内并列 AGREE 字样防误绿）")
        card = re.search(r"function anchorCardHtml\(.*?\n\}", src, re.S)
        assert card, "锚卡渲染函数缺席"
        assert "<a " not in card.group(0), "锚卡证据目录不得渲染链接（runs/ 缺省不挂载）"

    def test_node_check_view_gallery_js(self):
        assert _NODE is not None, "本机无 node"
        r = subprocess.run([_NODE, "--check",
                            str(_STATIC / "pages" / "view_gallery.js")],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, (
            f"node --check view_gallery.js:\n{r.stderr[-2000:]}")
