"""架构批 A8-A（R6 审计 P-2/P-3/P-4/P-6 打磨批）UI 微交互四面钉。

落地面（pages.js + index.html，两文件）：
1. **骨架屏（P-2）**：dashboard 首拉 / detail openRun 首建壳 / runs 表首拉
   三处占位（kitSkeleton / kitSkeletonRows）；shimmer 纯 transform（translateX
   高光带扫过，§7.2 合规），prefers-reduced-motion 显式降级=静态灰块。
2. **空态三件式（P-3）**：kitEmptyState（图标+一句话+下一步动作钮）落 4 页
   （dashboard activity / runs 无匹配 / tune trials / queue 空）+ detail 裸页
   空态补形（钉面 id="detail-goto-runs" 与绑定形态原样保留——同
   test_ui_routing 口径，本席不清偿他席钉）。
3. **错误态动作化（P-4 面）**：kitErrorPanel（badge+错误串+重试钮，W7-C
   detail 内联面板模式推广）落 datasets / anchors 两处高频 API 失败点；
   queue ✗ 点按跨席计数钉如实豁免（余量随归一批顺移：6→5=架构批 W2-S5，
   5→1=架构批 W14-S2 playground/profile/tools 迁 kitErrorPanel，见
   TestErrorPanelPins 类注）；W7-C 原点不动（钉在 test_w7c_ui_p2_sweep）。
4. **微动效收敛（P-6 面）**：.card .v KPI 数字 tabular-nums 防跳动；三个
   高频图表容器 min-height 高度锚（#splot-echart/#tune-trials-chart/
   #cal-evolution，与 plotCard 传参同值）。

两层钉（同 test_ui_kit 口径）：源码钉（免 node）+ 行为钉（node 动态 import
真执行 kit 五件：形态/数量/XSS 转义/node 零 DOM 依赖）。跨席计数钉
（T.plotCard==12 等）由 test_ui_sse/test_ui_lifecycle 复述面守着，本文件
只钉本批新增面。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
# 架构批 UI-R2（2026-10-14）：pages.js 拆分为薄入口 + pages/ 域模块（零构建
# ESM）——源码钉读"入口+全部域模块"并集，行为断言逐字不变（拆分前=单文件）。
def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)

_PAGES = _pages_union_text()

_INDEX = _STATIC / "index.html"

_NODE = shutil.which("node")


def _body(func_sig: str, close_indent: str = "") -> str:
    """取函数体（起于 function 声明行，止于首个指定缩进的收括号）——同
    test_ui_dashboard_widgets 的 _body 口径。"""
    src = _PAGES
    m = re.search(func_sig + r" \{(.*?)\n" + re.escape(close_indent) + r"\}", src, re.S)
    assert m, f"函数体缺失: {func_sig}"
    return m.group(1)


def _a8a_css_block() -> str:
    """A8-A 打磨批 CSS 块（骨架屏注释头 → 图表高度锚段尾）。"""
    src = _INDEX.read_text(encoding="utf-8")
    m = re.search(r"A8-A（R6 审计 P-2/P-3/P-4 打磨批）(.*?)#cal-evolution \{ min-height: 300px; \}", src, re.S)
    assert m, "A8-A CSS 块缺失"
    return m.group(0)


# ────────────────────────── 1. 骨架屏（P-2） ──────────────────────────

class TestSkeletonPins:
    def test_kit_helpers_single_source(self):
        src = _PAGES
        for fn in ("kitSkeleton", "kitSkeletonRows", "kitEmptyState",
                   "bindEmptyStates", "kitErrorPanel"):
            assert src.count(f"export function {fn}(") == 1, fn

    def test_three_wiring_sites(self):
        # dashboard 首拉：组件清单占位壳（含 aria status 语义）
        # W8-S32 i18n 批 3：骨架 aria 文案迁词表 t() 烘焙（zh 值同笔）
        dash = _body(r"async function pageDashboard\(\)")
        assert "kitSkeleton(3)" in dash
        assert 'aria-label="${t("dashboard.loading_aria")}"' in dash
        assert "role=\"status\"" in dash
        # detail openRun 首建壳：head 面板占位（aria 同批迁词表 detail.loading_aria）
        run = _body(r"async function showRun\(runId\)")
        assert "kitSkeleton(4)" in run
        assert 'aria-label="${t("detail.loading_aria")}"' in run
        # runs 表首拉：表体占位行（5×6 与列数一致）
        runs = _body(r"async function pageRuns\(\)")
        assert "kitSkeletonRows(5, 6)" in runs

    def test_shimmer_is_transform_only(self):
        """§7.2 红线：shimmer 动画只走 transform（translateX 扫过），
        不动画 width/left/background-position 等布局/绘制属性。"""
        css = _a8a_css_block()
        assert "@keyframes skeleton-sweep" in css
        kf = re.search(r"@keyframes skeleton-sweep \{ (.*?)\}", css, re.S)
        assert kf and "transform: translateX(100%);" in kf.group(1)
        # .skeleton::after 初帧 translateX(-100%)（animation 简写在其后）
        after = re.search(r"\.skeleton::after \{(.*?)\}", css, re.S)
        assert after and "transform: translateX(-100%);" in after.group(1)
        assert "animation: skeleton-sweep" in after.group(1)

    def test_no_new_backdrop_filter_and_no_new_inline_script(self):
        """§7.2 红线复述：backdrop-filter 功能声明不新增（基线 12 处冻结）；
        index.html 内联 <script> 恒 2（主题防闪 boot + importmap，CSP 哈希钉
        ——test_w1e_ui_csp 同源复述）。"""
        idx = _INDEX.read_text(encoding="utf-8")
        assert idx.count("backdrop-filter:") == 12
        assert len(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", idx)) == 2

    def test_reduced_motion_static_fallback(self):
        """prefers-reduced-motion 显式降级：shimmer 置 none → ::after 停在
        初帧 translateX(-100%)（出画）→ 骨架条=静态灰块。"""
        src = _INDEX.read_text(encoding="utf-8")
        m = re.search(r"prefers-reduced-motion: reduce\)\s*\{(.*?)\n\}", src, re.S)
        assert m, "reduced-motion 块缺失"
        assert ".skeleton::after { animation: none; }" in m.group(1)


# ────────────────────────── 2. 空态三件式（P-3） ──────────────────────────

class TestEmptyStatePins:
    def test_four_kit_sites(self):
        # dashboard activity：文案单源迁词表 t() 烘焙（W8-S32 i18n 批 3，
        # runs/queue 空态先例同口径——zh 字面同笔迁 pages/i18n.js）+ 动作=去工程导入
        act = _body(r"async function wActivity\(el\)")
        assert 'kitEmptyState(t("dashboard.activity_empty")' in act
        assert "暂无活动——去「工程导入」跑第一个 run" in (
            _STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")
        assert 'view: "import"' in act
        assert "bindEmptyStates(el)" in act
        # runs 无匹配：colspan 行包 empty-state（表体语境合法形态）+ 清除筛选
        # W6-S21 i18n 扩面：文案单源迁词表 t() 烘焙（zh 字面同笔迁
        # pages/i18n.js，此处钉接线形态——queue 空态先例同口径）
        runs = _body(r"async function pageRuns\(\)")
        assert 'kitEmptyState(t("runs.empty_filter")' in runs
        assert "无匹配 run——调整筛选条件试试" in (
            _STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")
        assert 'id: "runs-empty-clear"' in runs
        assert "rc.onclick = () => fc.click();" in runs
        # tune trials 空：动作转触既有「启动调参」钮（架构批 W2-S7 起
        # tuneRefresh 提升模块级，kitEmptyState 装配随迁 view_tune.js 模块层
        # ——钉语义不变，作用域从 pageTune 函数体放宽到 view_tune.js 全文）
        # 发布令 S3 残量清：文案单源迁词表 t() 烘焙（runs/queue 空态先例
        # 同口径——zh 字面同笔迁 pages/i18n.js，此处钉接线形态）
        tune = (_STATIC / "pages" / "view_tune.js").read_text(encoding="utf-8")
        assert 'kitEmptyState(t("tune.empty_hint")' in tune
        assert "暂无 trial 数据（启动调参后这里实时出点）" in (
            _STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")
        assert 'id: "tune-empty-go"' in tune
        assert "teg.onclick = () => tgo.click();" in tune
        # queue 空：引导去战役仪表盘（W1-S2 架构批 i18n 试点：文案单源迁
        # 词表 t() 烘焙——zh 字面同笔迁 pages/i18n.js，此处钉接线形态）
        q = _body(r"async function pageQueue\(\)")
        assert 'kitEmptyState(t("queue.empty")' in q
        assert 'runs/ 下暂无 campaign.plan.json（先立战役）' in (
            _STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")
        assert 'view: "campaign"' in q
        assert "bindEmptyStates(el)" in q

    def test_detail_bare_form_three_piece_without_breaking_seat_pins(self):
        """detail 裸页空态补形：图标锚+一句话+动作钮三件式；他席钉字面
        （id="detail-goto-runs" / go.onclick 绑定形态 / 转义深链提示）原样
        在位——test_ui_routing::test_showrun_bare_form_honest_empty_state 同笔。"""
        run = _body(r"async function showRun\(runId\)")
        assert 'id="detail-goto-runs"' in run
        assert 'go.onclick = () => showPage("runs");' in run
        # S2 发布令批：转义深链提示迁词表（兜底烘焙钉在此；词表值钉在
        # test_ui_routing 同笔——实体形态以字符 〈run_id〉 承载渲染保真）
        assert '${t("detail.empty_no_run")}' in run
        assert 'class="empty-ico" aria-hidden="true"' in run
        assert 'class="empty-txt"' in run

    def test_bind_empty_states_guarded_and_idempotent(self):
        body = _body(r"export function bindEmptyStates\(root\)")
        assert 'typeof document === "undefined"' in body  # node import 零 DOM 依赖
        assert "!root" in body  # 容器缺席静默返回
        assert 'btn.getAttribute("data-empty-view")' in body


# ────────────────────────── 3. 错误态动作化（P-4 面） ──────────────────────────

class TestErrorPanelPins:
    def test_two_sites_with_retry_wiring(self):
        src = _PAGES
        # datasets：重试=整页重进（v.innerHTML 全量重建页）
        assert 'kitErrorPanel((d.errors || []).join("; "), "ds-retry")' in src
        assert "rb.onclick = () => pageDatasets();" in src
        # anchors：重试=本页 load() 局部重拉（壳不重建）
        assert 'kitErrorPanel((d.errors || []).join("; "), "an-retry")' in src
        an = _body(r"async function pageAnchors\(\)")
        assert "if (rb) rb.onclick = load;" in an

    def test_queue_error_site_exempt_by_cross_seat_pin(self):
        """queue ✗ 错误点如实不迁：跨席计数钉 "color:var(--err)'>✗"==1
        （test_ui_lifecycle / test_ui_tools_page 双钉）——queue 保持
        ✗ 形态并以注释登记豁免缘由。
        架构批 W2-S5（R1 #8 三态批1）：gallery 闭式计算失败点迁
        kitErrorPanel（原 ✗ span 形态②清偿），余量 6→5 同笔更新三钉。
        架构批 W14-S2（R2 Top10 #4 归一波）：playground×2/profile/tools
        内联 ✗ span 迁 kitErrorPanel，余量 5→1 同笔更新三钉
        （余 1=queue 豁免点本身）。"""
        src = _PAGES
        assert src.count("color:var(--err)'>✗") == 1
        assert 'kitErrorPanel((d.errors || []).join("; "), "q-retry")' not in src
        qbody = _body(r"async function pageQueue\(\)")
        assert "如实不清偿" in qbody

    def test_w7c_detail_panel_untouched(self):
        """W7-C 原点（showRun 失败分支）零扰动——W6-S21 i18n 扩面仅文案
        单源迁词表 t() 烘焙（结构/esc(id)/重试钮形态不变）。"""
        src = _PAGES
        assert '<span class="badge err">${t("detail.load_failed")}</span> <code>${esc(id)}</code>' in src
        assert "加载失败" in (_STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")
        assert 'id="detail-retry"' in src and "showRun(id)" in src


# ────────────────────────── 4. 微动效收敛（P-6 面） ──────────────────────────

class TestMicroMotionPins:
    def test_kpi_tabular_nums(self):
        src = _INDEX.read_text(encoding="utf-8")
        m = re.search(r"\.card \.v \{([^}]*)\}", src)
        assert m and "font-variant-numeric: tabular-nums;" in m.group(1), \
            "KPI 数字等宽（刷新/轮询位宽不抖）"

    def test_chart_containers_min_height(self):
        src = _INDEX.read_text(encoding="utf-8")
        # 与 plotCard 传参同值（detail 320 / tune 220 / calibration 300）
        assert "#splot-echart { min-height: 320px; }" in src
        assert "#tune-trials-chart { min-height: 220px; }" in src
        assert "#cal-evolution { min-height: 300px; }" in src

    def test_a8a_block_no_backdrop_filter(self):
        assert "backdrop-filter" not in _a8a_css_block().replace(
            "不新增 backdrop-filter", ""), "A8-A 新增面零 backdrop-filter"


# ────────────────────────── 5. 行为钉（node 真执行） ──────────────────────────

_NODE_GLUE = r"""
const m = await import('./pages.js');
const A = (cond, msg) => { if (!cond) throw new Error("assert: " + msg); };

// ── kitSkeleton：条数/宽度轮替/缺省/非法入参 ──
const sk = m.kitSkeleton(3);
A((sk.match(/class="skeleton"/g) || []).length === 3, "skeleton count 3");
A(sk.includes("width:92%") && sk.includes("width:76%") && sk.includes("width:84%"), "widths rotate");
A(m.kitSkeleton() === m.kitSkeleton(3), "default = 3");
A(m.kitSkeleton(0) === m.kitSkeleton(3) && m.kitSkeleton(-2) === m.kitSkeleton(3), "invalid n falls back");
A(m.kitSkeleton(2).split("</div>").length - 1 === 2, "honors n=2");

// ── kitSkeletonRows：行×列全包围 <tr>（只能进 tbody） ──
const rows = m.kitSkeletonRows(2, 3);
A((rows.match(/<tr>/g) || []).length === 2, "rows count");
A((rows.match(/<td>/g) || []).length === 6, "cells = rows*cols");
A(rows.startsWith("<tr>") && rows.endsWith("</tr>"), "tr wrapped");

// ── kitEmptyState：三件式形态 + view/id 两形态 + 无 cta ──
const es = m.kitEmptyState("一句话", { icon: "☰", label: "去列表", view: "runs" });
A(es.includes('class="empty-state"') && es.includes('class="empty-ico" aria-hidden="true"')
  && es.includes('class="empty-txt"'), "three-piece structure");
A(es.includes('data-empty-view="runs"') && es.includes(">去列表</button>"), "view form");
const es2 = m.kitEmptyState("一句话", { icon: "⚙", label: "启动", id: "x-go" });
A(es2.includes('id="x-go"') && !es2.includes("data-empty-view"), "id form");
const es3 = m.kitEmptyState("只有一句话");
A(es3.includes("empty-txt") && !es3.includes("<button"), "no cta no button");

// ── XSS：label/view/id 全走 esc/escAttr（恶意串出不来活性标签/出不了属性） ──
const es4 = m.kitEmptyState("t", { label: '<img src=x onerror=alert(1)>',
  view: 'runs" onmouseover="alert(1)', id: "a'b" });
A(!es4.includes("<img"), "label escaped");
A(!es4.includes('onmouseover="alert'), "view attr cannot break out");
A(!es4.includes("a'b"), "id escaped");

// ── kitErrorPanel：badge+esc(msg)+重试钮；无 retryId 无钮；null msg 空串 ──
const ep = m.kitErrorPanel('服务 <b>炸</b> 了', "ds-retry");
A(ep.startsWith('<div class="err-panel">'), "err wrapper");
A(ep.includes('<span class="badge err">加载失败</span>'), "badge");
A(ep.includes("&lt;b&gt;") && !ep.includes("<b>"), "msg escaped");
A(ep.includes('id="ds-retry"') && ep.includes(">重试</button>"), "retry button");
A(!m.kitErrorPanel("x").includes("重试"), "no retryId no button");
A(m.kitErrorPanel(null, "r").includes('<span class="muted"></span>'), "null msg empty");

// ── bindEmptyStates：node 语境零 DOM 依赖（document 守卫直返） ──
m.bindEmptyStates(null);
m.bindEmptyStates(undefined);

console.log("ok:polish");
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestNodeBehavioral:
    def test_polish_kit_end_to_end(self):
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e", _NODE_GLUE],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC))
        assert r.returncode == 0, r.stderr[-2000:]
        assert "ok:polish" in r.stdout
