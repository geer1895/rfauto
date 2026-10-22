"""aurora36 W7-C（UI P2 清扫批）回归钉。

落地面（本席只动 pages.js / index.html / 本测试，零 commit）：
1. P2-11 窄屏策略：900px 断点块（main 收距 / 页头换行 / 面板横滚 /
   KPI 卡 minmax 150px）+ run_id 首列截断省略（CSS 三表）+ 渲染侧 title
   悬停全名 + fs-browser max-width:94vw（640px 定宽窄屏溢出收账）。
2. P2-6 魔数 z-index 收编：fs-browser 60→var(--z-modal)、chat-float
   50→var(--z-fixed)（#msg 的 calc(var(--z-overlay)+10) 既有不动）。
3. 微交互一致性：.minor/.danger/.chipbtn 补 :active 下压（.act/.primary
   既有状态面不动）；加载态缺口补齐（chat 发送钮 / 收件箱批准钮 fetch
   期间 disabled+文案，失败路径恢复）。
4. R1 P1-6 搭车：Run 详情失败写内联错误面板（badge+run_id+错误串+重试钮），
   不再只弹 toast 留骨架空壳；msg 双通道保留。
5. guide 未落残余：P2-3 入场交错阶梯（50ms×5 档+n+6 封顶，
   reduced-motion delay 归零）/ P2-5 @supports not backdrop-filter 降级 /
   P2-8 .pk-hint 死类补样式 / P2-9 重复 .bubble.md 样式块删除 /
   P2-15 表头 scope="col"（原跨席字面钉豁免的战役座位表 2 处已由
   aurora_d UI-R4 清偿挂 scope，全域零裸表头）/ P1-14 残余 nav .ico
   aria-hidden(26) / P2-4 残余 logo 升 h1。

零改动项（核查结论钉住，防未来漂移）：
- msg() 一致性：pages.js 全部 T.msg(...) 调用第二参显式（true/false/
  !!r.ok/r.ok），全站四 JS 零 alert/confirm/prompt——错误走 msg(false)、
  成功走 msg(true)（4s 自消）既有口径本批核查零改动。
- 数字格式化：toPrecision(8) 零存在（W3-B 已清）；toPrecision(4) 仅 canvas
  标签/轴与导入 bounds 建议档（任务书口径=合理不动）；toPrecision(6) 仅
  参数滑条/params k=v 串（跨量级参数语义，非 cost 指标），cost 列一律
  fmtNum(·,4)——R1 P1-10 点名的唯一离群已由 W3-B 清偿，本批零改动。

跨席计数钉自查（与 test_ui_lifecycle/test_ui_tables_sort 等既有门同源复述，
先红即指本批扰动）：T.plotCard==12 / window.echarts.init(==1 /
resize 监听==1 / chartExportTools==4 / bindChartResize P0-5==4 /
disposeChartsIn==4 / setInterval==2 / index.html data-v==26 / 内联脚本==2。

工程注记：node --check 对 ESM 语法错误可能假绿（本批实证：引号类破损
--check 放行、真 ESM import 才红）——本文件行为钉走 --input-type=module
真 import，不依赖 node --check。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
# aurora_d UI-R2（2026-10-14）：pages.js 拆分为薄入口 + pages/ 域模块（零构建
# ESM）——源码钉读"入口+全部域模块"并集，行为断言逐字不变（拆分前=单文件）。
def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)

_PAGES = _pages_union_text()

_INDEX = (_STATIC / "index.html").read_text(encoding="utf-8")
_NODE = shutil.which("node")

_INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)


def _media900() -> str:
    m = re.search(r"@media \(max-width: 900px\)\s*\{(.*?)\n\}", _INDEX, re.S)
    assert m, "900px 窄屏策略块缺失（P2-11 回归）"
    return m.group(1)


# ────────────────────────── 1. P2-11 响应式 ──────────────────────────

class TestP11Responsive:
    def test_narrow_breakpoint_block(self):
        body = _media900()
        assert "main { padding:" in body, "窄屏 main 内距收缩"
        assert ".pagehead { flex-wrap: wrap;" in body, "页头允许换行"
        assert ".panel { overflow-x: auto; }" in body, "面板横滚容器"
        assert "minmax(150px, 1fr)" in body, "KPI 卡窄屏最小宽 150px"

    def test_run_id_first_cell_truncation(self):
        body = _media900()
        for sel in ("#runs-table td:first-child", "#cal-table td:first-child",
                    ".wbody table td:first-child"):
            assert sel in body, f"run_id 首列截断缺 {sel}"
        assert "text-overflow: ellipsis" in body

    def test_truncated_columns_have_hover_title(self):
        # 渲染侧 title 补全（textContent/属性赋值，无插值面）
        assert 'tr.children[0].title = r.run_id || ""' in _PAGES, "runs 表"
        assert 'tr.title = tr.dataset.id || ""' in _PAGES, "dashboard 最近 Run"
        assert 'tr.title = tr.dataset.rid || ""' in _PAGES, "校准表"

    def test_fs_browser_not_fixed_width_overflow(self):
        assert "width:640px;max-width:94vw" in _PAGES, "fs-browser 窄屏溢出收账"

    def test_no_sidebar_cq_regression(self):
        # 既有 W2-A CQ 侧栏折叠不被本批扰动
        assert "container: sidebar / inline-size" in _INDEX
        assert "@supports (container-type: inline-size)" in _INDEX


# ────────────────────────── 2. P2-6 z-index 收编 ──────────────────────────

class TestP6ZIndexTokens:
    def test_no_magic_zindex_in_pages(self):
        assert "z-index:60" not in _PAGES, "fs-browser 魔数 60 未收编"
        assert "z-index:50" not in _PAGES, "chat-float 魔数 50 未收编"
        assert "z-index:var(--z-modal)" in _PAGES
        assert "z-index:var(--z-fixed)" in _PAGES

    def test_msg_overlay_token_untouched(self):
        # 既有口径：msg 在 --z-overlay 上偏移（W2 已收编），不得回退魔数
        assert "calc(var(--z-overlay) + 10)" in _INDEX


# ────────────────────────── 3. 微交互一致性 ──────────────────────────

class TestMicroInteraction:
    def test_press_feedback_unified(self):
        assert re.search(
            r"button\.minor:active,\s*button\.danger:active,\s*\.chipbtn:active"
            r"\s*\{\s*transform:\s*translateY\(1px\);", _INDEX), "下压反馈规则"
        # transform 必须在三类的过渡链上（否则下压瞬跳无过渡）
        for sel in (r"button\.minor\s*\{[^}]*\}", r"button\.danger\s*\{[^}]*\}",
                    r"\.chipbtn\s*\{[^}]*\}"):
            m = re.search(sel, _INDEX, re.S)
            assert m and "transform var(--transition-fast)" in m.group(0), sel

    def test_primary_and_act_states_untouched(self):
        # 既有 .act/.primary 状态面不被本批扰动（W2-A 钉复述）
        for state in (":hover", ":active", ":disabled"):
            assert re.search(rf"button\.act{re.escape(state)}\s*\{{", _INDEX), state
            assert re.search(rf"button\.primary{re.escape(state)}\s*\{{", _INDEX), state

    def test_chat_send_loading_state(self):
        # 人性化三批（2026-10-19，审计 ⚠4）：两守卫拆分——防重入静默保留，
        # 空输入不再无声（toast 提示后返回）。
        assert 'if (btn && btn.disabled) return;' in _PAGES, "发送中防重入"
        assert 'if (!text) { T.msg(t("agent.empty_input"), false); return; }' in _PAGES
        # W8-S32 i18n 批 3：发送/发送中文案迁词表 t() 烘焙（disabled 结构不变）
        assert 'btn.disabled = true; btn.textContent = t("agent.chat_sending")' in _PAGES
        assert 'if (btn) { btn.disabled = false; btn.textContent = t("agent.chat_send"); }' in _PAGES
        # finally 恢复（异常路径不卡死按钮）
        m = re.search(r"if \(btn\) \{ btn\.disabled = true;.*?\} finally \{", _PAGES, re.S)
        assert m, "chat 发送 disabled 须在 try/finally 恢复结构内"

    def test_inbox_approve_loading_state(self):
        assert "approveBtn.disabled = true;" in _PAGES, "批准钮防双击"
        assert "if (!r.ok) approveBtn.disabled = false;" in _PAGES, "失败路径恢复"


# ────────────────────────── 4. R1 P1-6 详情失败内联面板 ──────────────────────────

class TestRunDetailInlineError:
    def test_failure_writes_inline_panel_with_retry(self):
        m = re.search(r"if \(!d\.ok\) \{(.*?)\n  \}\n  T\.\$\(\"detail-id\"\)", _PAGES, re.S)
        assert m, "showRun 失败分支缺内联面板"
        body = m.group(1)
        assert 'T.msg((d.errors || []).join("; "), false)' in body, "msg 双通道保留"
        # 人性化三批（2026-10-19，审计 ✗1/✗2）：错误卡收编 kitApiErrorHtml
        # 统一错误卡；h2 动态段（small#detail-id）同步置"加载失败"——
        # 不再残留上一个 run id（run 间误读面清偿）。
        assert 'kitApiErrorHtml(d, { title: t("detail.load_failed"), hint: "" })' in body
        assert 'if (idEl) idEl.textContent = t("detail.load_failed");' in body
        assert "${esc(id)}" in body, "run_id 内联可见"
        assert 'id="detail-retry"' in body and "showRun(id)" in body, "重试钮"

    def test_success_path_untouched(self):
        assert 'T.$("detail-id").textContent = d.run_id;' in _PAGES


# ────────────────────────── 5. guide 未落残余 ──────────────────────────

class TestGuideLeftovers:
    def test_p2_3_staggered_entry(self):
        delays = re.findall(r"\.panel:nth-child\((?:\d|n\+6)\)\s*\{\s*"
                            r"animation-delay:\s*(\d+)ms;", _INDEX)
        assert len(delays) == 5, f"交错阶梯 5 档，实得 {len(delays)}"
        assert [int(x) for x in delays] == [50, 100, 150, 200, 250]
        assert ".panel:nth-child(n+6) { animation-delay: 250ms; }" in _INDEX, "6 档封顶"

    def test_p2_3_reduced_motion_delay_reset(self):
        m = re.search(r"prefers-reduced-motion: reduce\)\s*\{(.*?)\n\}", _INDEX, re.S)
        assert m and "animation-delay: 0ms !important" in m.group(1), \
            "交错阶梯在 reduced-motion 下须归零（否则延迟窗空白）"

    def test_p2_5_backdrop_filter_fallback(self):
        m = re.search(r"@supports not \(\(backdrop-filter: blur\(1px\)\) or "
                      r"\(-webkit-backdrop-filter: blur\(1px\)\)\)\s*\{(.*?)\}", _INDEX, re.S)
        assert m, "@supports not backdrop-filter 降级块缺失（P2-5）"
        assert re.search(r"aside,\s*#palette\s*\{\s*background:\s*var\(--panel-solid\);",
                         m.group(1))

    def test_p2_8_pk_hint_class_styled(self):
        assert re.search(r"\.pk-hint\s*\{[^}]*var\(--muted2\)", _INDEX), \
            ".pk-hint 死类须有样式（P2-8）"
        assert '<span class="pk-hint">Ctrl+K</span>' in _INDEX, "消费点仍在"

    def test_p2_9_duplicate_bubble_block_removed(self):
        assert _INDEX.count(".bubble.md p { margin: 4px 0; }") == 1, \
            ".bubble.md 规则重复块未删净"
        assert _INDEX.count(".bubble.md th, .bubble.md td") == 1

    def test_p2_15_all_th_have_scope(self):
        # UI-R4（aurora_d）清偿 A6 P2-9：原 X2 席裸字面钉豁免的战役 trial 表
        # PASS/FAIL 两分支 2 处已挂 scope=col（test_x2_pr68_ui /
        # test_ui_kit 同笔更新）——pages/ 全域零裸表头，新增一律挂 scope。
        # 人性化 R3 文案批：列头文案迁词表（campaign.th_seat），钉改键引用形态。
        bare = [m.start() for m in re.finditer(r"<th>", _PAGES)]
        assert len(bare) == 0, f"裸表头应已清零（A6 P2-9），实得 {len(bare)}"
        assert _PAGES.count('<th scope="col">${t("campaign.th_seat")}</th>') == 2, \
            "trial 表 scope 口径"
        assert _PAGES.count("scope=") >= 28, "scope=col 覆盖面"
        assert _PAGES.count('scope="col"') + _PAGES.count("scope='col'") >= 28

    def test_p1_14_nav_icons_aria_hidden(self):
        plain = _INDEX.count('<span class="ico">')
        marked = _INDEX.count('<span class="ico" aria-hidden="true">')
        assert plain == 0, f"{plain} 个 nav .ico 未挂 aria-hidden（读屏朗读 Unicode）"
        assert marked == 26, f"nav .ico aria-hidden 应 26 个，实得 {marked}"

    def test_p2_4_logo_is_h1(self):
        assert "<h1 class=\"logo\">" in _INDEX, "logo 应升 h1（页面主标题）"
        assert '<div class="logo">' not in _INDEX
        assert re.search(r"aside \.logo\s*\{[^}]*margin:\s*0;", _INDEX), \
            "h1 缺省外距须归零"


# ────────────────────────── 6. 零改动项结论钉（如实核查） ──────────────────────────

class TestMsgAndNumberConsistencyHonest:
    def test_every_msg_call_has_explicit_ok_flag(self):
        # T.msg(payload, ok) 二参显式：true/false/!!r.ok/r.ok。
        # 括号配平扫描取完整实参串（正则交替对多层嵌套会截断——
        # "promote 被拒: " + (r.error || (r.errors||[]).join...) 两层嵌套实证）。
        calls, i = [], 0
        while True:
            i = _PAGES.find("T.msg(", i)
            if i < 0:
                break
            j = i + len("T.msg(")
            depth = 1
            while j < len(_PAGES) and depth:
                depth += (_PAGES[j] == "(") - (_PAGES[j] == ")")
                j += 1
            calls.append(_PAGES[i + len("T.msg("):j - 1])
            i = j
        assert len(calls) >= 20, f"T.msg 调用面应 ≥20，实得 {len(calls)}"
        for idx, args in enumerate(calls):
            assert re.search(r",\s*(true|false|!!r\.ok|r\.ok)\s*$", args.strip()), \
                f"第 {idx} 个 T.msg 调用缺显式 ok 二参：...{args[-60:]!r}"

    def test_no_blocking_dialogs_anywhere(self):
        for name in ("pages.js", "app.js", "palette.js", "plotcard.js"):
            src = (_STATIC / name).read_text(encoding="utf-8")
            for fn in ("alert(", "confirm(", "prompt("):
                assert fn not in src, f"{name} 出现阻塞式对话框 {fn}"

    def test_number_format_no_outlier(self):
        assert "toPrecision(8)" not in _PAGES, "8 位有效数字离群（W3-B 已清）勿回潮"
        assert _PAGES.count("toPrecision(4)") >= 6, "canvas 标签/轴口径（合理不动）"
        assert "fmtNum(row.cost, 4)" in _PAGES, "campaign cost 列 4dp 口径"
        assert "export function fmtNum(v, d = 4)" in _PAGES, "fmtNum 单源在位"


# ────────────────────────── 7. 跨席计数钉自查（既有门同源复述） ──────────────────────────

class TestCrossSeatPinSelfCheck:
    def test_pages_js_count_pins(self):
        assert _PAGES.count("T.plotCard(") == 18  # 12 + W3-S12 四管线逃生舱迁移 + aurora_i W3-S2 画廊对照图两处
        assert _PAGES.count("window.echarts.init(") == 1
        assert _PAGES.count('window.addEventListener("resize"') == 1
        assert _PAGES.count("setInterval(") == 2
        assert _PAGES.count("chartExportTools(el.parentElement, el, {") == 0  # W3-S12 四管线入壳
        assert _PAGES.count("bindChartResize(el); // P0-5") == 0  # W3-S12 随壳内建去重
        assert _PAGES.count("disposeChartsIn(") == 4

    def test_index_html_count_pins(self):
        assert len(re.findall(r'data-v="', _INDEX)) == 26
        assert len(re.findall(r'id="view-', _INDEX)) == 26
        inline = _INLINE_SCRIPT_RE.findall(_INDEX)
        assert len(inline) == 2, f"内联脚本数变 {len(inline)}（CSP 哈希钉联动面）"

    def test_sortable_table_pins(self):
        assert "<table id='runs-table' data-sortable>" in _PAGES
        assert "<table id='cal-table' data-sortable>" in _PAGES
        assert "<table data-sortable>" in _PAGES
        assert _PAGES.count("data-sortable") >= 3


# ────────────────────────── 8. 行为钉（node 真 ESM 解析） ──────────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestEsmParseBehavioral:
    def test_pages_js_real_esm_import(self):
        # node --check 对 ESM 语法错误可能假绿（本批实证）；真 import 才是门
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e",
             "await import('file:///" + str(_STATIC / "pages.js").replace("\\", "/") + "');"
             "console.log('esm-ok')"],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
        )
        assert r.returncode == 0, f"pages.js ESM 解析失败:\n{r.stderr[-1500:]}"
        assert "esm-ok" in r.stdout

    def test_index_html_style_blocks_parse_hint(self):
        # 轻量护栏：style 块花括号配平（CSS 语法破损早发现）。先剥 CSS 注释
        # ——既有注释含字面 `{`（_vars 正则 body\.light\s*\{ 口径注记）。
        for m in re.finditer(r"<style>(.*?)</style>", _INDEX, re.S):
            css = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
            assert css.count("{") == css.count("}"), "style 块花括号失配"
