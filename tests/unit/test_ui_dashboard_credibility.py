"""aurora_i W3.5-K1 席位回归钉：M7 总览页可信度 KPI 卡 + 首访三步导览。

对象：src/rfauto/ui/static/pages/view_dashboard.js（本席独占文件面；
i18n.js 词表追加段只读消费）+ pages/i18n.js 的 dashboard.cred_*/onboard_*
键段（本席 append 面）。

设计依据=内部证据档 §2②（锚对照卡数据面）与
M7 行（首页 KPI 徽章）；数据源零新端点=/api/anchors 摘要（engine_pair
.referee=hfss 过滤，现役 17 条）+ /api/anchors/{id} 详情既有字段
（verdict_state 只在详情——画廊 W2-S1 同款两段取数）。

钉四层（test_ui_dashboard_widgets 同风格）：
1. **源码钉（免 node）**：
   - credibility widget 进 WIDGETS 注册表 + WIDGET_DEFAULTS + renderers
     装配面（标题走 tk 词表键）；
   - 数据源零新端点：wCredibility 只消费 /api/anchors 与 /api/anchors/{id}
     （encodeURIComponent 转义），全文件零 /api/credibility 引用（对照
     曲线端点属 W3-S2 画廊面，KPI 卡不越面）；
   - 呈现红线（#122 家族）：verdict 三分类 DISAGREE 先于 AGREE（先红后绿
     防长串态误绿）、AGREE 占比=x/总数 分数形态（不折百分比凑绿）、
     分歧/待判/其他注记行在位；
   - 首访导览：ONBOARD_KEY 字面、pageDashboard 装配（onboardSeen 守卫+
     bindOnboard 接线）、dismiss=写档+摘卡；
   - 跳画廊通路：showPage("gallery") + getActiveView 离场守卫 + 代点
     data-gal 既有钮 + credibility 节 scrollIntoView（禁改他页——本文件
     零 view_gallery import）；
   - i18n 纪律：纯函数导出面在位（node 行为钉入口）；文案全走 t() 词表。
2. **词表钉（node 真执行，缺 node skip）**：dashboard.cred_*/onboard_* 14
   键 zh/en 双语齐全（键命名契约由 test_ui_i18n 全局双向互证覆盖，此处钉
   本席键段存在性与双语完整性）。
3. **行为钉（node）**：credVerdictClass 真值表（空/AGREE 族/DISAGREE/
   REJUDGE_PASS/BRANCH_A 含 AGREE 字样长串态）/credStats 统计（"*" 通配
   不落族、template_family 数组/标量/缺席三形态、Map 缺席=待判）/onboard
   Seen+markOnboardSeen 注入 store 真值表（抛异常 store 诚实降级、node
   无 localStorage 缺省路）。
4. **语法兜底**：node --check view_dashboard.js（i18n.js 由 test_ui_i18n
   同笔覆盖）。

不依赖 runs/、不读网络（fetch 全零——纯函数+源码钉）、不启动服务器。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

_DASH = (_STATIC / "pages" / "view_dashboard.js").read_text(encoding="utf-8")
_I18N = (_STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")


def _body(func_sig: str, close_indent: str = "") -> str:
    """取函数体（test_ui_dashboard_widgets 同款；close_indent=嵌套缩进）。"""
    m = re.search(func_sig + r" \{(.*?)\n" + close_indent + r"\}", _DASH, re.S)
    assert m, f"函数体缺失: {func_sig}"
    return m.group(1)


# ────────────────────────── 1. 源码钉 ──────────────────────────

class TestCredWidgetRegistry:
    """credibility widget 进注册表+缺省面+渲染装配。"""

    def test_registered_defaulted_and_wired(self):
        assert re.search(r"credibility:\s*\{ tk: \"dashboard\.w_credibility\"",
                         _DASH)
        dm = re.search(r"const WIDGET_DEFAULTS = \[(.*?)\];", _DASH, re.S)
        assert dm and '"credibility"' in dm.group(1)
        assert "credibility: wCredibility" in _DASH

    def test_data_source_existing_anchor_endpoints_only(self):
        body = _body(r"async function wCredibility\(el\)", "  ")
        assert 'apiFetch("/api/anchors"' in body  # 摘要面
        # 仲裁口径单源：裁判=HFSS 过滤（注册表现役 17 条）
        assert 'a.engine_pair.referee === "hfss"' in body
        # 详情面既有字段（verdict_state 只在 /api/anchors/{id}——画廊 W2-S1
        # 同款两段取数；id 走 encodeURIComponent 属性语境转义）
        det = _body(r"function ensureCredVerdicts\(el\)")
        assert '"/api/anchors/" + encodeURIComponent(id)' in det
        assert "provenance" in det and "verdict_state" in det
        # 零越面：KPI 卡不消费 W3-S2 对照曲线端点（属画廊抽屉面）
        assert "/api/credibility" not in _DASH

    def test_honesty_pins_score_form_and_note_line(self):
        body = _body(r"function credRenderBody\(el\)")
        # AGREE 占比=x/总数 分数形态（不折百分比凑绿）
        assert 's.agree + "/" + s.nArb' in body
        # 分歧/待判/其他注记行（#122 家族：如实呈现）
        assert 't("dashboard.cred_note_tpl"' in body
        # 补拉在途="…"占位（诚实区分"没拉到"与"拉到了但无判定"）
        assert '"…"' in body

    def test_verdict_class_disagree_before_agree(self):
        # 先红后绿防误绿（长串态内可能并列"AGREE_JUDGE 单项不救总态"字样）
        body = _body(r"export function credVerdictClass\(state\)")
        assert body.index("DISAGREE") < body.index("AGREE")

    def test_abort_discipline(self):
        # UI-R12 同款：切页取消/面板离场不写隐藏区；补拉 abort 不定局
        body = _body(r"async function wCredibility\(el\)", "  ")
        assert "viewSignal(\"dashboard\")" in body
        assert "aborted" in body and "el.isConnected" in body
        det = _body(r"function ensureCredVerdicts\(el\)")
        assert "rs.some((r) => r.aborted)" in det  # 不定局不缓存（回页重拉）


class TestOnboardPins:
    """首访三步导览：localStorage 记忆已读不再弹。"""

    def test_key_and_page_wiring(self):
        assert 'const ONBOARD_KEY = "rfauto-onboard-v1"' in _DASH
        page = _body(r"export async function pageDashboard\(\)")
        assert "onboardSeen()" in page  # 首访守卫（已读不弹）
        assert "onboardCardHtml()" in page  # 卡片进壳（pagehead 与格网之间）
        assert "bindOnboard(v)" in page  # 接线（跳页+dismiss）

    def test_dismiss_writes_and_removes(self):
        body = _body(r"function bindOnboard\(v\)")
        assert "markOnboardSeen()" in body  # 写 localStorage（已读记忆）
        assert "card.remove()" in body  # 摘卡（零整页重渲）

    def test_steps_keyboard_reachable(self):
        # 步骤行=kitClickRow 单源（role/tabindex/aria）+ bindClickRows
        # （click 与 Enter/Space 同一激活——UI-R4 纪律）
        body = _body(r"function onboardCardHtml\(\)")
        assert body.count("kitClickRowAttrs(") == 3
        assert 'data-go=\'tune\'' in body
        assert 'data-go=\'runs\'' in body
        assert 'data-go=\'gallery\'' in body
        wiring = _body(r"function bindOnboard\(v\)")
        assert 'bindClickRows(card, (row) => showPage(row.dataset.go), "[data-go]")' in wiring

    def test_i18n_literal_keys_no_dynamic_concat(self):
        # data-i18n 键字面逐一落模板（动态拼键会逃逸 _PAGE_KEY_LIT 扫描）
        for k in ("dashboard.onboard_title", "dashboard.onboard_s1_desc",
                  "dashboard.onboard_s2_desc", "dashboard.onboard_s3_desc",
                  "nav.tune", "nav.runs", "nav.gallery"):
            assert f"data-i18n='{k}'" in _DASH


class TestGalleryJumpPins:
    """点卡跳画廊抽屉 credibility 节（禁改他页通路）。"""

    def test_jump_path_and_guards(self):
        body = _body(r"function openGalleryCredibility\(\)")
        assert 'showPage("gallery")' in body  # 画廊单入口
        assert 'getActiveView() !== "gallery"' in body  # 离场放弃代点
        assert '[data-gal]' in body  # 代点既有详情钮（openDrawer 私有）
        assert 'data-slot=credibility' in body  # 滚到可信度节
        assert "scrollIntoView" in body
        assert "setTimeout(tick, 100)" in body  # 网格未到轮询（上限 ~6s）

    def test_no_cross_page_import(self):
        # 禁改他页的结构面证据：本文件零 view_gallery 依赖（纯 DOM 通路；
        # 注释里的"view_gallery 的抽屉开函私有"注记不算依赖面）
        assert re.search(r'from "\./view_gallery|import\("\./pages/view_gallery',
                         _DASH) is None


# ────────────────────────── 2. 词表钉（node） ──────────────────────────

_K1_KEYS = [
    "dashboard.w_credibility", "dashboard.cred_k_anchors",
    "dashboard.cred_k_agree", "dashboard.cred_k_fams",
    "dashboard.cred_note_tpl", "dashboard.cred_open",
    "dashboard.cred_stats_aria", "dashboard.cred_load_fail",
    "dashboard.onboard_title", "dashboard.onboard_s1_desc",
    "dashboard.onboard_s2_desc", "dashboard.onboard_s3_desc",
    "dashboard.onboard_dismiss", "dashboard.onboard_aria",
]


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestI18nKeysBilingual:
    def test_k1_key_block_bilingual_complete(self):
        out = subprocess.run(
            [_NODE, "--input-type=module", "-e",
             "const m = await import('./pages/i18n.js');\n"
             "const keys = " + repr(_K1_KEYS).replace("'", '"') + ";\n"
             "const errs = [];\n"
             "for (const k of keys) {\n"
             "  const e = m.LOCALES[k];\n"
             "  if (!e) { errs.push('缺键: ' + k); continue; }\n"
             "  if (typeof e.zh !== 'string' || !e.zh) errs.push('zh 缺: ' + k);\n"
             "  if (typeof e.en !== 'string' || !e.en) errs.push('en 缺: ' + k);\n"
             "}\n"
             "if (errs.length) throw new Error(errs.join('; '));\n"
             "console.log('ok:k1-keys:' + keys.length);\n"],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC))
        assert out.returncode == 0, out.stderr[-2000:]
        assert "ok:k1-keys:14" in out.stdout


# ────────────────────────── 3. 行为钉（node） ──────────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestK1PureFunctions:
    def test_verdict_class_truth_table(self):
        out = subprocess.run(
            [_NODE, "--input-type=module", "-e",
             "const m = await import('./pages/view_dashboard.js');\n"
             "const cases = [\n"
             "  [null, 'pending'], ['', 'pending'], ['   ', 'pending'],\n"
             "  ['AGREE_OPENEMS', 'agree'], ['AGREE_JUDGE', 'agree'],\n"
             "  ['AGREE_HFSS', 'agree'], ['DISAGREE', 'disagree'],\n"
             "  ['REJUDGE_PASS（离线复判模型一致性 PASS）', 'other'],\n"
             "  // 长串态含 AGREE 字样（收敛仲裁 AGREE）→ 先红后绿纪律下归 agree\n"
             "  // W4-R2 P3-1 裁决：BRANCH 主 token 是部分收敛态（括注内的单支\n"
             "  // 一致判定不抬总态）——落 other 中性灰，不并入 AGREE 占比分子\n"
             "  ['BRANCH_A_OPENEMS_ENGINE_FAITHFUL（收敛仲裁 AGREE：G-branch 过）', 'other'],\n"
             "  // DISAGREE 优先：并列字样先红\n"
             "  ['x DISAGREE 与 AGREE 并列', 'disagree'],\n"
             "];\n"
             "for (const [inp, want] of cases)\n"
             "  if (m.credVerdictClass(inp) !== want)\n"
             "    throw new Error('verdictClass ' + String(inp) + ' -> ' +\n"
             "      m.credVerdictClass(inp) + ' want ' + want);\n"
             "console.log('ok:verdict-class');\n"],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC))
        assert out.returncode == 0, out.stderr[-2000:]
        assert "ok:verdict-class" in out.stdout

    def test_cred_stats_truth_table(self):
        out = subprocess.run(
            [_NODE, "--input-type=module", "-e",
             "const m = await import('./pages/view_dashboard.js');\n"
             "const arb = [\n"
             "  { anchor_id: 'a', template_family: ['wilkinson'] },\n"
             "  { anchor_id: 'b', template_family: '*' },\n"
             "  { anchor_id: 'c', template_family: 'patch' },\n"
             "  { anchor_id: 'd', template_family: null },\n"
             "];\n"
             "const v = new Map([['a', 'AGREE_OPENEMS'], ['b', 'DISAGREE'],\n"
             "  ['c', ''], ['d', 'REJUDGE_PASS（x）']]);\n"
             "const s = m.credStats(arb, v);\n"
             "const errs = [];\n"
             "if (s.nArb !== 4) errs.push('nArb=' + s.nArb);\n"
             "if (JSON.stringify(s.fams) !== JSON.stringify(['patch', 'wilkinson']))\n"
             "  errs.push('fams（* 通配不落族）: ' + JSON.stringify(s.fams));\n"
             "if (s.agree !== 1 || s.disagree !== 1 || s.other !== 1 || s.pending !== 1)\n"
             "  errs.push('counts ' + JSON.stringify(s));\n"
             "const s2 = m.credStats(arb, new Map());\n"
             "if (s2.pending !== 4) errs.push('Map 缺席=待判');\n"
             "const s3 = m.credStats(null, null);\n"
             "if (s3.nArb !== 0 || s3.fams.length !== 0) errs.push('空入参');\n"
             "if (errs.length) throw new Error(errs.join('; '));\n"
             "console.log('ok:cred-stats');\n"],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC))
        assert out.returncode == 0, out.stderr[-2000:]
        assert "ok:cred-stats" in out.stdout

    def test_onboard_seen_store_injection(self):
        out = subprocess.run(
            [_NODE, "--input-type=module", "-e",
             "const m = await import('./pages/view_dashboard.js');\n"
             "const errs = [];\n"
             "const store = new Map();\n"
             "const rd = { getItem: (k) => (store.has(k) ? store.get(k) : null) };\n"
             "const wr = { setItem: (k, val) => store.set(k, val) };\n"
             "if (m.onboardSeen(rd)) errs.push('写档前应未读');\n"
             "m.markOnboardSeen(wr);\n"
             "if (!m.onboardSeen(rd)) errs.push('写档后应已读');\n"
             "if (m.onboardSeen({ getItem: () => { throw new Error('x'); } }))\n"
             "  errs.push('抛异常 store 应诚实降级 false');\n"
             "m.markOnboardSeen({ setItem: () => { throw new Error('x'); } }); // 不抛\n"
             "if (m.onboardSeen()) errs.push('node 无 localStorage 应 false');\n"
             "m.markOnboardSeen(); // 不抛\n"
             "if (errs.length) throw new Error(errs.join('; '));\n"
             "console.log('ok:onboard');\n"],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC))
        assert out.returncode == 0, out.stderr[-2000:]
        assert "ok:onboard" in out.stdout

    def test_module_import_clean_in_node(self):
        # 模块级缓存 let 不得引入顶层 DOM 执行（R2 雷区表惯例复述）
        out = subprocess.run(
            [_NODE, "--input-type=module", "-e",
             "await import('./pages/view_dashboard.js');\n"
             "console.log('ok:import');\n"],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC))
        assert out.returncode == 0, out.stderr[-2000:]
        assert "ok:import" in out.stdout


# ────────────────────────── 4. 语法兜底 ──────────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestSyntax:
    def test_node_check_view_dashboard(self):
        r = subprocess.run([_NODE, "--check", str(_STATIC / "pages" / "view_dashboard.js")],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]
