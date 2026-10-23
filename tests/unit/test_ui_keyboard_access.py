"""aurora_j W3-S8 席位回归钉：键盘可达性（拖拽键盘替代落地）。

背景（runs/aurora_e/w5s23_ui_a11y_audit.md 深审 a 面 + 后续批次建议2）：
- 可排序表头键盘可达已在 W5-S23 落地（th tabindex=0+Enter/Space→onThClick
  同一激活）——本文件薄钉复读其在场（本席盘点核实，零改动）；
- 「后续批次建议2：widget 拖拽排序键盘替代（方向键移动语义）」=本席落地件
  （view_dashboard 标题条 tabindex=0 + 方向键移动，widgetMoveOrder 纯函数
  导出 node 行为钉可测）；
- 本席盘点另发现 3D 轨道相机（view_fieldviz drawIsoMesh：拖拽旋转+滚轮
  缩放纯指针）同属键盘完全不可达交互——orbitCamStep 纯函数+画布
  tabindex/keydown 同批落地；
- 焦点轮廓单源=全局 :focus-visible 2px accent 环（index.html，PR-1 钉禁
  删；accent vs panel ≥3:1 对比度由 test_ui_a11y_theme.TestContrastPin
  三主题 graphic 钉守值）——本席零新 CSS，只复读在位。

对象：pages/{sortable,view_dashboard,view_fieldviz,i18n}.js + index.html。

三层（风格同 test_w5s23_ui_a11y/test_ui_a11y_theme）：
1. **源码钉**：sortable th 键盘三件复读；view_dashboard 键盘重排装配
   （tabindex/方向键/insertBefore 行引用重排/persist）+ 跨席计数钉复述
   （refreshDashboard 字面 2 / refreshGridKeepingFocus 3 / return
   pageDashboard 1——本席加行零扰动自证）；view_fieldviz 相机键盘装配。
2. **行为钉（node 真执行，缺 node skip）**：widgetMoveOrder 真值表
   （中部前/后移、首尾边界 null、缺席 id null、零步 null、Set 入参、null
   入参、其余保序）；orbitCamStep 真值表（四方向、+/-与=/_ 缩放、未知键
   null、φ 钳制 0.1-3.0、入参不可变）；新 3 词表键 zh/en 双语解析（含
   {name}/{pos}/{total} 插值）。
3. **语法**：node --check 触达 JS 文件。

不依赖 runs/、不读网络、不启动服务器。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

_INDEX = (_STATIC / "index.html").read_text(encoding="utf-8")
_SORTABLE = (_STATIC / "pages" / "sortable.js").read_text(encoding="utf-8")
_DASH = (_STATIC / "pages" / "view_dashboard.js").read_text(encoding="utf-8")
_FIELD = (_STATIC / "pages" / "view_fieldviz.js").read_text(encoding="utf-8")
_I18N = (_STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")


# ────────────────────────── 1. 源码钉 ──────────────────────────

class TestSortableKeyboardRepin:
    """W5-S23 已落地件复读（本席盘点核实：可排序表头键盘可达在位）。"""

    def test_th_focusable_and_key_activated(self):
        assert 'th.setAttribute("tabindex", "0");' in _SORTABLE
        assert 'e.key === "Enter" || e.key === " "' in _SORTABLE
        assert "onThClick(th)" in _SORTABLE
        assert 'th.title = "排序（升 → 降 → 还原；Enter 或空格）";' in _SORTABLE

    def test_focus_visible_ring_present(self):
        # 焦点轮廓单源=全局 :focus-visible（th/标题条/画布焦点环同走此环，
        # 零新 CSS；对比度 ≥3:1 由 test_ui_a11y_theme 对比度钉守值）
        assert re.search(r":focus-visible\s*\{[^}]*outline:\s*2px solid var\(--accent\)", _INDEX)


class TestWidgetKeyboardReorder:
    """W5-S23 后续建议2 落地件：widget 拖拽排序的方向键替代。"""

    def test_pure_helper_exported(self):
        assert "export function widgetMoveOrder(order, id, delta)" in _DASH
        assert "arr.splice(j, 0, arr.splice(i, 1)[0]);" in _DASH  # 保序换位

    def test_title_keydown_wiring(self):
        assert 'wtitle.setAttribute("tabindex", "0");' in _DASH
        assert 'wtitle.title = t("dashboard.dnd_kb_hint");' in _DASH
        # 方向键语义：←↑=前移、→↓=后移（delta -1/+1）
        assert '(e.key === "ArrowLeft" || e.key === "ArrowUp") ? -1' in _DASH
        assert '(e.key === "ArrowRight" || e.key === "ArrowDown") ? 1 : 0' in _DASH
        assert "e.preventDefault();" in _DASH  # 防方向键滚屏
        # 消费纯函数单源 + persist 落档
        assert "widgetMoveOrder(_widgetSet, id, delta)" in _DASH
        assert "_widgetSet = new Set(arr);" in _DASH
        assert "persistWidgets();" in _DASH

    def test_in_place_dom_move_no_grid_rebuild(self):
        # 行引用重排（sortable.js 同款纪律：图表/监听随节点走不丢）——
        # 键盘路径零全格重建（图表不销毁、焦点留在标题条随动）
        assert "grid.insertBefore(panel, prev);" in _DASH
        assert "grid.insertBefore(next, panel);" in _DASH

    def test_i18n_keys_consumed_and_label_updates(self):
        assert 't("dashboard.dnd_kb_hint")' in _DASH
        assert 't("dashboard.aria_move_tpl"' in _DASH
        # W3-S10 走查修复：位次标注全格刷新单源 syncMoveLabels（原 kbLabel
        # 在 append 循环内急切求值——初装 total 错缩成自身位次 N/N、移动后
        # 对换伙伴标注陈旧）——两调用点=初装完成后+移动后
        assert "escAttr(t(\"dashboard.aria_move_tpl\"" in _DASH  # 属性语境出口
        assert _DASH.count("syncMoveLabels();") == 2
        assert "wtitle.focus();" in _DASH  # insertBefore 必 blur 焦点节点——还焦保连续移动

    def test_cross_seat_count_pins_untouched(self):
        # 跨席计数钉复述（W5-S23/aurora72 W1-S3 同源）：本席加行零扰动
        assert _DASH.count("refreshDashboard();") == 2
        assert _DASH.count("refreshGridKeepingFocus(") == 3
        assert _DASH.count("return pageDashboard();") == 1


class TestOrbitCameraKeyboard:
    """本席盘点新增落地件：3D 轨道相机（drawIsoMesh）键盘替代。"""

    def test_pure_helper_exported(self):
        assert "export function orbitCamStep(state, key)" in _FIELD
        assert 's.phi = Math.max(0.1, Math.min(3.0, s.phi));' in _FIELD  # φ 钳制同指针口径

    def test_canvas_keydown_wiring(self):
        assert 'dom.setAttribute("tabindex", "0");' in _FIELD
        assert "orbitCamStep({ theta, phi, radius }, e.key)" in _FIELD
        assert "e.preventDefault();" in _FIELD  # 防方向键滚屏
        # hint 词表双注入口（aria-label 读屏可达名 + title 悬浮）
        assert _FIELD.count('t("fieldviz.iso_kb_hint")') == 2

    def test_i18n_key_registered(self):
        assert '"fieldviz.iso_kb_hint"' in _I18N
        assert '"dashboard.dnd_kb_hint"' in _I18N
        assert '"dashboard.aria_move_tpl"' in _I18N


# ────────────────────────── 2. 行为钉（node 真执行） ──────────────────────────

def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return r.stdout


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestKeyboardBehavioralNode:
    def test_widget_move_order_truth_table(self):
        out = _run_node_js(
            "const m = await import('./pages/view_dashboard.js');\n"
            "const eq = (a, b, msg) => { if (JSON.stringify(a) !==\n"
            "  JSON.stringify(b)) throw new Error(msg + ': ' + JSON.stringify(a)); };\n"
            "eq(m.widgetMoveOrder(['a','b','c'], 'b', -1), ['b','a','c'], '前移');\n"
            "eq(m.widgetMoveOrder(['a','b','c'], 'b', 1), ['a','c','b'], '后移');\n"
            "eq(m.widgetMoveOrder(['a','b','c'], 'a', -1), null, '首边界');\n"
            "eq(m.widgetMoveOrder(['a','b','c'], 'c', 1), null, '尾边界');\n"
            "eq(m.widgetMoveOrder(['a','b','c'], 'x', 1), null, '缺席 id');\n"
            "eq(m.widgetMoveOrder(['a','b','c'], 'b', 0), null, '零步');\n"
            "eq(m.widgetMoveOrder(new Set(['a','b']), 'a', 1), ['b','a'], 'Set 入参');\n"
            "eq(m.widgetMoveOrder(null, 'a', 1), null, 'null 入参');\n"
            "console.log('ok:move');\n")
        assert "ok:move" in out

    def test_orbit_cam_step_truth_table(self):
        out = _run_node_js(
            "const m = await import('./pages/view_fieldviz.js');\n"
            "const near = (a, b, msg) => { if (Math.abs(a - b) > 1e-9)\n"
            "  throw new Error(msg + ': ' + a + ' != ' + b); };\n"
            "const s = { theta: 0.7, phi: 1.05, radius: 100 };\n"
            "near(m.orbitCamStep(s, 'ArrowLeft').theta, 0.6, '左旋');\n"
            "near(m.orbitCamStep(s, 'ArrowRight').theta, 0.8, '右旋');\n"
            "near(m.orbitCamStep(s, 'ArrowUp').phi, 0.95, '上旋');\n"
            "near(m.orbitCamStep(s, 'ArrowDown').phi, 1.15, '下旋');\n"
            "near(m.orbitCamStep(s, '+').radius, 100 / 1.1, '放大');\n"
            "near(m.orbitCamStep(s, '=').radius, 100 / 1.1, '放大（=同键）');\n"
            "near(m.orbitCamStep(s, '-').radius, 110, '缩小');\n"
            "near(m.orbitCamStep(s, '_').radius, 110, '缩小（_同键）');\n"
            "if (m.orbitCamStep(s, 'q') !== null) throw new Error('未知键');\n"
            "if (m.orbitCamStep(s, 'Enter') !== null) throw new Error('Enter 非相机键');\n"
            # φ 钳制（与指针拖拽同口径 0.1-3.0）
            "if (m.orbitCamStep({ theta: 0, phi: 2.98, radius: 1 }, 'ArrowDown').phi !== 3.0)\n"
            "  throw new Error('φ 上钳');\n"
            "if (m.orbitCamStep({ theta: 0, phi: 0.12, radius: 1 }, 'ArrowUp').phi !== 0.1)\n"
            "  throw new Error('φ 下钳');\n"
            # 纯函数：入参不可变
            "if (s.theta !== 0.7 || s.phi !== 1.05 || s.radius !== 100)\n"
            "  throw new Error('入参被变异');\n"
            "console.log('ok:orbit');\n")
        assert "ok:orbit" in out

    def test_new_locale_keys_bilingual(self):
        out = _run_node_js(
            "const m = await import('./pages/i18n.js');\n"
            "const errs = [];\n"
            "const keys = ['dashboard.dnd_kb_hint', 'dashboard.aria_move_tpl',\n"
            "  'fieldviz.iso_kb_hint'];\n"
            "for (const k of keys) {\n"
            "  const e = m.LOCALES[k];\n"
            "  if (!e || typeof e.zh !== 'string' || !e.zh ||\n"
            "      typeof e.en !== 'string' || !e.en) errs.push('双语缺半边: ' + k);\n"
            "}\n"
            "if (m.t('dashboard.aria_move_tpl', { name: 'KPI', pos: 2, total: 9 }) !==\n"
            "  'KPI，位次 2/9；←↑ 前移一位，→↓ 后移一位') errs.push('插值 zh');\n"
            "m.setLocale('en');\n"
            "if (m.t('dashboard.aria_move_tpl', { name: 'KPI', pos: 2, total: 9 }) !==\n"
            "  'KPI, position 2/9; Left/Up moves earlier, Right/Down moves later')\n"
            "  errs.push('插值 en');\n"
            "m.setLocale('zh');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:locales');\n")
        assert "ok:locales" in out


# ────────────────────────── 3. 语法 ──────────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestSyntax:
    @pytest.mark.parametrize("name", [
        "pages/sortable.js", "pages/view_dashboard.js",
        "pages/view_fieldviz.js", "pages/i18n.js",
    ])
    def test_node_check(self, name):
        r = subprocess.run([_NODE, "--check", str(_STATIC / name)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"node --check {name}:\n{r.stderr[-2000:]}"
