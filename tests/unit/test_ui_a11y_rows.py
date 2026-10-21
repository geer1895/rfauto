"""架构批 UI-R4（A6 审查 P1-5 全域清偿 + a11y 清扫）可点行键盘可达回归钉。

**台账（2026-10-14，A6 REPORT P1-5/P2-9 + 焦点管理面）**

改造站点 12 处（clickRow 式行点击 11 站 + Run 详情可点图 1 站 → kit 三件单源）：

===========================  =============  ===============================  ==========
站点                          模块            DOM 形态 / role 口径              原状
===========================  =============  ===============================  ==========
dashboard 最近活动流          view_dashboard  div role=button（试点#1 迁kit）  手写 role=link+Enter
dashboard 最近 Run 表         view_dashboard  tr role:null（保 row 语义）      裸 onclick
Run 历史表                   view_runs       tr role:null（createElement 面） 裸 onclick
数据集清单                   view_data       tr role:null                     裸 onclick
标定锚清单                   view_data       tr role:null                     裸 onclick
UQ 样本资产                  view_data       tr role:null                     裸 onclick
配方目录                     view_recipe      div role=button                  裸 onclick
校准 run 表                  view_calibration tr role:null                    裸 onclick
报告清单                     view_reports     tr role:null                     裸 onclick
queue 决策日志锚             view_queue       a role=button（href 保留防跳动） 裸 onclick preventDefault
文件浏览器行                 filebrowser      div role=button ×2 形态          裸 onclick
Run 详情可点曲线图           view_detail      img role=button（灯箱放大动作）   裸 img.onclick
===========================  =============  ===============================  ==========

组件形态（kit.js 单源，pages.js facade re-export）：
- kitClickRowAttrs(opts)：行开标签属性串 role+tabindex+aria-label（模板面；
  role 缺省 button、tr 行传 null 保表格 row/cell 结构；label 经 escAttr 出口）；
- kitApplyClickRowAttrs(el, opts)：DOM 侧同源（createElement 面，setAttribute）；
- bindClickRows(root, onActivate, selector)：click 与 Enter/Space 同一激活
  （preventDefault 防空格滚屏与 href='#' 页顶跳动——queue 锚 A6 指控点）；
- focus-visible 焦点环零新 CSS（index.html 全局 :focus-visible 对 [tabindex]
  生效）；div.clickable 补 cursor:pointer 指针形。

新增 ARIA 面 8 类：①行 aria-label ×11 站 ②座位表 scope=col ×2（A6 P2-9
清零，pages/ 裸表头 2→0）③sparams 三模式 aria-pressed（互斥切换钮状态标注）
④自研 canvas 图像语义 ×2（campaign 成本热图 / optstack 可行性热图）⑤表单
控件 aria-label ×5 模板点（fs-path/uq-sigma/配方参数值/搜索上下界）⑥
filebrowser 焦点陷阱三件套+Esc+初始聚焦+还焦 ⑦div.clickable cursor 1 规则
⑧aria-expanded 零新增（全站折叠面均为原生 details/summary，无需装饰性
ARIA——如实不堆）。

两层钉（同 test_ui_a11y_theme / test_ui_kit 既有形态）：
1. **源码钉（免 node）**：kit 三件单源唯一 + 11 站接线在位 + 旧裸 onclick
   行接线零回潮 + tr 行 role:null 保表语义 + A6 P2-9 清零 + aria-pressed/
   canvas 图像语义/表单 aria-label/焦点陷阱在位。
2. **行为钉（node 真执行，缺 node skip）**：kitClickRowAttrs 字节形态 +
   escAttr 出口转义 + kitApplyClickRowAttrs DOM 桩逐键 + bindClickRows
   click/Enter/Space 激活与 preventDefault（桩 root 自带 querySelectorAll
   ——binder 无 document 依赖，行为钉无需 jsdom）+ 空参守卫。

不依赖 runs/ 与网络；不启动服务器。
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


def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)


_PAGES = _pages_union_text()
_ENTRY = (_STATIC / "pages.js").read_text(encoding="utf-8")
_INDEX = (_STATIC / "index.html").read_text(encoding="utf-8")


# ────────────────────────── 1. 源码钉 ──────────────────────────

class TestClickRowSourcePins:
    def test_kit_clickrow_single_source_and_facade(self):
        # kit 三件单源唯一（不建新文件；函数各只定义一次）
        assert _PAGES.count("export function kitClickRowAttrs(") == 1
        assert _PAGES.count("export function kitApplyClickRowAttrs(") == 1
        assert _PAGES.count("export function bindClickRows(") == 1
        # pages.js facade re-export（浏览器/钉单 import 路径口径）
        assert "kitClickRowAttrs, kitApplyClickRowAttrs, bindClickRows," in _ENTRY

    def test_eleven_sites_wired_count_and_needles(self):
        # 11 行站 + 详情可点图 = 12 站接线（bindClickRows 定义 1 + 站点 12 = 13）
        assert _PAGES.count("bindClickRows(") == 13, "行点击站点数漂移——迁移台账见本文件 docstring"
        # 属性串面：定义 1 + 模板站点 11（filebrowser ×2 形态）= 12
        assert _PAGES.count("kitClickRowAttrs(") == 12
        # DOM 面：定义 1 + runs 表 createElement 行 + 详情可点图 = 3
        assert _PAGES.count("kitApplyClickRowAttrs(") == 3
        for needle, why in (
            ('bindClickRows(el, (row) => openRun(row.dataset.id), "[data-id]");', "dashboard 活动流"),
            ('bindClickRows(el, (tr) => openRun(tr.dataset.id), "tr.clickable");', "dashboard 最近 Run"),
            ('bindClickRows(tb, (tr) => openRun(tr.dataset.id), "tr.clickable");', "runs 表"),
            ('bindClickRows(body, (tr) => loadPreview(tr.dataset.n), "tr.clickable");', "datasets"),
            ('bindClickRows(el, (tr) => pickAsset(tr.dataset.p), "tr.clickable");', "UQ 资产"),
            ('bindClickRows(el, (row) => { T.$("recipe-path").value = row.dataset.p; loadRecipe(); }, "[data-p]");', "配方目录"),
            ('bindClickRows(tbody, (tr) => loadCalibration(tr.dataset.rid), "tr[data-rid]");', "校准表"),
            # 架构批 W2-S5：reports 行打开链路抽具名 openReport（深链/重试
            # 同一入口），bindClickRows 收 (tr) => openReport(tr.dataset.p)。
            ('bindClickRows(tbody, (tr) => openReport(tr.dataset.p), "tr[data-p]");', "报告清单"),
            ("}, \".q-open\");", "queue 决策日志锚"),
            ("}, \".fs-row\");", "文件浏览器行"),
            ('(img) => T.lightboxImg("/" + img.dataset.fig, img.dataset.fig.split("/").pop()),', "Run 详情可点图"),
        ):
            assert needle in _PAGES, f"行点击站点未收编 kit：{why}"
        # anchors 站（async 详情回调形态）
        assert "bindClickRows(body, async (tr) => {" in _PAGES

    def test_legacy_bare_row_wiring_not_regrown(self):
        # 旧裸 onclick 行接线零回潮（UI-R4 前 6+ 处裸 onclick / 手写 keydown）；
        # "row.onkeydown" 唯一合法出现位=kit binder 定义体（1 处）
        assert _PAGES.count("row.onkeydown") == 1, "手写行 keydown 应收编 bindClickRows"
        assert "tr.onclick = () => openRun" not in _PAGES
        assert "tr.onclick = () => loadCalibration" not in _PAGES
        assert "tr.onclick = async () => {" not in _PAGES  # reports 旧形态
        assert "row.onclick = () => {" not in _PAGES  # filebrowser 旧形态
        assert "img.onclick = () => T.lightboxImg" not in _PAGES  # 详情可点图旧形态
        assert 'tr.className = "clickable";' in _PAGES  # runs 表行构建保留（类名视觉面）

    def test_tr_rows_preserve_table_semantics(self):
        # tr 行一律 role:null（role=button 会把行后代降级 presentational 毁表
        # 结构——可达性走 tabindex+aria-label+键盘激活，不覆写行语义）
        assert _PAGES.count("kitClickRowAttrs({ role: null") == 6  # wRecentRuns/datasets/anchors/uq/calibration/reports
        assert _PAGES.count("kitApplyClickRowAttrs(tr, { role: null") == 1  # runs 表
        # div/锚/图行走缺省 role=button（活动流/配方目录/filebrowser×2/queue 锚/详情图）
        assert _PAGES.count("kitClickRowAttrs({ label:") == 5
        assert _PAGES.count('kitApplyClickRowAttrs(img, { label:') == 1  # 详情可点图

    def test_row_aria_labels_present(self):
        # 行动作 aria-label 摘要（读屏可闻；label 拼接走 String concat——
        # XSS 反向扫描口径零新增，转义在 kit escAttr 出口）。
        # W2-S1 批 4：datasets/anchors/uq 三行标签迁词表 t() 模板键
        # （zh 值同笔；t() 组装后仍由 kit escAttr 出口单点转义）。
        # S4 发布令批：dashboard 活动流/最近 Run + runs 表三处行标签同款
        # 迁词表 runs.open_detail_aria（zh 值同笔；三消费面一键单源）。
        for needle in (
            't("runs.open_detail_aria") + (r.run_id || "")',  # 活动流 + 最近 Run + runs 表
            't("datasets.aria_preview_tpl", { name: (x.name || "") })',
            't("anchors.aria_detail_tpl", { name: (a.anchor_id || "") })',
            't("uq.aria_pick_tpl", { name: (it.path || "") })',
            't("recipe.row_open_aria") + (r.path || "")',  # S3 发布令批：配方目录行同款迁词表
            't("calibration.open_detail_aria") + (r.run_id || "")',  # S1 发布令批：校准行同款迁词表
            't("reports.row_open_aria") + (r.run_id || "")',  # S3 发布令批：报告清单行同款迁词表
            't("queue.open_log_aria_tpl", { n: dl.length })',  # S2 发布令批：队列行同款迁词表
            '"返回上级目录"',
            '"打开目录 " + e.name',
            't("detail.fig_zoom_lead") + f.split("/").pop()',  # 详情可点图（灯箱动作）——S2 批迁词表 lead
        ):
            assert needle in _PAGES, needle

    def test_seat_table_th_scope_cleared(self):
        # A6 P2-9 清零：pages/ 全域零裸表头；座位表两分支 scope 口径
        # （S3 发布令批：表头文案迁词表 campaign.th_seat，scope 口径钉不变）
        assert _PAGES.count("<th>") == 0
        assert _PAGES.count('<th scope="col">${t("campaign.th_seat")}</th>') == 2

    def test_sparams_mode_aria_pressed(self):
        # 三模式互斥切换钮状态标注（读屏可知当前档）
        for needle in (
            '["sp-mode-db", "db"], ["sp-mode-deg", "deg"], ["sp-mode-smith", "smith"]',
            'setAttribute("aria-pressed", String(mode === m))',
            "syncModePressed();",
        ):
            assert needle in _PAGES, needle

    def test_canvas_charts_image_semantics(self):
        # 自研 canvas 管线补 PR-1 图表容器口径（campaign 成本热图/optstack 可行性）
        assert _PAGES.count('canvas.setAttribute("role", "img")') == 2
        # S3 发布令批：campaign 热图 aria lead 迁词表（t() 拼 API 参数名，
        # String concat 口径零新增——setAttribute=单点同信任级）
        assert 'canvas.setAttribute("aria-label", t("campaign.heat_aria_lead") + d.x_param' in _PAGES
        # S2 发布令批：optstack 热图 aria lead/tail 迁词表（t() 拼 API 参数名，
        # String concat 口径零新增——setAttribute=单点同信任级）
        assert 'canvas.setAttribute("aria-label", t("optstack.heat_aria_lead") + d.x_param' in _PAGES

    def test_form_control_aria_labels(self):
        # 动态表单控件显式可闻名（A6 P2-7 a11y 面；id/name 可测试性欠账不在本席范围）
        # W2-S1 批 4：uq-sigma aria 迁词表 t()（uq.sigma_aria_tpl，zh 值同笔；
        # 数据实参 escAttr 先行转义、整体不再二次转义——W6-S21 aria tpl 先例）
        for needle in (
            "aria-label='${t(\"uq.sigma_aria_tpl\", { n: escAttr(n) })}'",  # uq-sigma
            # S3 发布令批：recipe 三处 aria 迁词表（lead/tail 分段夹 escAttr
            # 数据实参——数据不进词表，转义出口不变）
            'aria-label="${t("recipe.param_aria_lead")}${escAttr(p.name)}${t("recipe.param_aria_tail")}"',  # 配方参数值
            'aria-label="${escAttr(n)}${t("recipe.opt_low_aria")}"',  # opt-b low
            'aria-label="${escAttr(n)}${t("recipe.opt_high_aria")}"',  # opt-b high
            'aria-label="路径"',  # fs-path
        ):
            assert needle in _PAGES, needle

    def test_filebrowser_focus_trap_trio(self):
        # 模态弹层焦点管理三件套（W2-C 灯箱/命令面板同款模式）+ Esc + 初始聚焦
        for needle in (
            "const savedFocus = document.activeElement; // 焦点陷阱①：打开前的 activeElement",
            "savedFocus.focus(); // 焦点陷阱③：关闭还焦",
            'if (e.key === "Escape") { e.preventDefault(); close(); }',
            '// 焦点陷阱②：Tab 首尾回绕（弹层内可聚焦元素循环，不逃出模态）',
            'if (pathInput) pathInput.focus({ preventScroll: true });',
        ):
            assert needle in _PAGES, needle
        # dialog 语义保持（PR-1 既有钉消费位）
        assert 'modal.setAttribute("aria-modal", "true");' in _PAGES

    def test_div_clickable_cursor_and_focus_ring(self):
        # div 可点行指针形 + 全局焦点环仍在（focus-visible 焦点指示零新 CSS）
        assert "div.clickable { cursor: pointer; }" in _INDEX
        assert re.search(r":focus-visible\s*\{[^}]*outline:\s*2px solid", _INDEX)
        assert re.search(r"outline\s*:\s*(none|0)\s*;", _INDEX) is None


# ────────────────────────── 2. 行为钉（node） ──────────────────────────

def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2000:]}"
    return r.stdout


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestClickRowNodeBehavior:
    def test_attrs_byte_forms(self):
        """三形态字节钉：缺省 button / tr 行 null（保表语义）/ 无 label。"""
        out = json.loads(_run_node_js(
            "const m = await import('./pages.js');\n"
            "console.log(JSON.stringify([\n"
            "  m.kitClickRowAttrs({ label: '打开 run 详情：r1' }),\n"
            "  m.kitClickRowAttrs({ role: null, label: '预览数据集：d1' }),\n"
            "  m.kitClickRowAttrs({}),\n"
            "  m.kitClickRowAttrs(),\n"
            "]));"))
        assert out == [
            'role="button" tabindex="0" aria-label="打开 run 详情：r1"',
            'tabindex="0" aria-label="预览数据集：d1"',
            'role="button" tabindex="0"',
            'role="button" tabindex="0"',
        ]

    def test_attrs_escapes_label_via_escattr(self):
        """label 出口转义（kit escAttr——外部 run_id/文件名可达此串）。"""
        out = json.loads(_run_node_js(
            "const m = await import('./pages.js');\n"
            "console.log(JSON.stringify([\n"
            "  m.kitClickRowAttrs({ label: '<img src=x onerror=alert(1)>' }),\n"
            "  m.kitClickRowAttrs({ role: null, label: 'a\\\"b' }),\n"
            "]));"))
        assert "<img" not in out[0] and "&lt;img" in out[0]
        assert 'aria-label="a&quot;b"' in out[1]  # 双引号进实体（属性串安全）

    def test_apply_attrs_dom_stub_per_key(self):
        """kitApplyClickRowAttrs：DOM 桩逐键断言（setAttribute 字面量语境）。"""
        js = (
            "const m = await import('./pages.js');\n"
            "const mk = () => { const attrs = {}; return { attrs,\n"
            "  setAttribute: (k, v) => { attrs[k] = String(v); } }; };\n"
            "const a = mk(); m.kitApplyClickRowAttrs(a, { label: 'x<y' });\n"
            "const b = mk(); m.kitApplyClickRowAttrs(b, { role: null, label: 'tr 行' });\n"
            "const c = mk(); m.kitApplyClickRowAttrs(c, {});\n"
            "console.log(JSON.stringify([a.attrs, b.attrs, c.attrs]));\n"
        )
        out = json.loads(_run_node_js(js))
        assert out[0] == {"role": "button", "tabindex": "0", "aria-label": "x<y"}
        assert "role" not in out[1] and out[1]["tabindex"] == "0"
        assert out[1]["aria-label"] == "tr 行"  # setAttribute 语境不转义（字面量）
        assert out[2] == {"role": "button", "tabindex": "0"}

    def test_bind_click_rows_click_enter_space_same_activation(self):
        """click 与 Enter/Space 触发同一 onActivate；Space/Enter preventDefault
        （防空格滚屏与 href='#' 页顶跳动——queue 锚 A6 指控点）。"""
        js = (
            "const m = await import('./pages.js');\n"
            "const rows = [{ id: 'a' }, { id: 'b' }];\n"
            "const root = { querySelectorAll: (sel) => sel === '.row' ? rows : [] };\n"
            "const calls = [];\n"
            "m.bindClickRows(root, (row) => calls.push(row.id), '.row');\n"
            "let pd = 0;\n"
            "const ev = (key) => ({ key, preventDefault: () => { pd++; } });\n"
            "rows[0].onclick();\n"
            "rows[0].onkeydown(ev('Enter'));\n"
            "rows[1].onkeydown(ev(' '));\n"
            "rows[1].onkeydown(ev('ArrowDown'));\n"
            "rows[1].onkeydown(ev('Escape'));\n"
            "console.log(JSON.stringify({ calls, pd }));\n"
        )
        out = json.loads(_run_node_js(js))
        assert out["calls"] == ["a", "a", "b"], "click+Enter+Space 三路同一激活"
        assert out["pd"] == 2, "Enter/Space 必须 preventDefault（方向键/Esc 不拦）"

    def test_bind_click_rows_default_selector_and_guards(self):
        """缺省选择器 [data-kit-click-row]；null/无 querySelectorAll root 守卫零抛。"""
        js = (
            "const m = await import('./pages.js');\n"
            "const rows = [{ id: 'z' }];\n"
            "const root = { querySelectorAll: (sel) =>\n"
            "  sel === '[data-kit-click-row]' ? rows : [] };\n"
            "const calls = [];\n"
            "m.bindClickRows(root, (row) => calls.push(row.id));\n"
            "rows[0].onclick();\n"
            "m.bindClickRows(null, () => { throw new Error('must not fire'); });\n"
            "m.bindClickRows({}, () => { throw new Error('must not fire'); });\n"
            "console.log(JSON.stringify(calls));\n"
        )
        assert json.loads(_run_node_js(js)) == ["z"]

    def test_node_check_kit_module(self):
        r = subprocess.run([_NODE, "--check", str(_STATIC / "pages" / "kit.js")],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"node --check kit.js:\n{r.stderr[-2000:]}"
