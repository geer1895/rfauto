"""W2-C a11y 焦点管理与全局兜错 回归钉（aurora36 R1 审计 P1-1/P1-3/P1-5/
P2-4 项，2026-10-11 批）。

源码钉（免 node DOM；node --check 保语法，风格对齐 test_ui_a11y_theme.py）：
1. 全局 api() 兜错：try/catch 包住 fetch+json、{ok:false,error,errors}
   兜底形状、失败经 msg() 可见。
2. 切页焦点管理：activate 聚焦新页 h2.page（动态 tabindex=-1）+ aria-live
   页名公告 region。
3. 灯箱弹层焦点三件套：焦点入层、Tab 回绕、Esc/遮罩关闭还焦。
4. palette.js 同模式存续（最小面，完整断言在 test_ui_a11y_theme.py）。
5. 跳过链接行为绑定（锚点本体在 index.html，归 W2-A 席；本钉只钉 app.js
   行为面，锚点缺席时绑定代码必须零副作用）。
6. ocean 主题图表色对比度：自含 WCAG 相对亮度实现，dark 档对 ocean
   --plot-bg（#091525）逐色 >=3:1（R1 审计未核项，本批补账；与
   runs/pr1_contrast/ 互为独立来源，#118 裁判不单源自证）。

不读网络、不启动服务器；index.html 只读。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_APP = (_STATIC / "app.js").read_text(encoding="utf-8")
_PALETTE = (_STATIC / "palette.js").read_text(encoding="utf-8")
_INDEX = (_STATIC / "index.html").read_text(encoding="utf-8")
# aurora72 A5-B（R6 R-4）：CHART_COLORS 单源迁 theme.js（app.js 经
# chartPalette 消费）——对比度钉换地址不换值
_THEME = (_STATIC / "theme.js").read_text(encoding="utf-8")
_NODE = shutil.which("node")


def _api_body() -> str:
    m = re.search(r"export const api = async \(url, opts\) => \{(.*?)\n\};", _APP, re.S)
    assert m, "api() 实体丢失"
    return m.group(1)


# ────────────────────────── 1. 全局 api() 兜错（P1-5） ──────────────────────────

class TestGlobalApiGuard:
    def test_fetch_and_json_inside_try(self):
        body = _api_body()
        assert "try" in body and "catch" in body, "api() 必须 try/catch 兜错"
        assert re.search(r"await\s+fetch\(", body), "fetch 须在 try 内"
        # await 必须留在 try 内：裸 `return r.json()` 的 rejection 不入 catch
        assert re.search(r"return\s+await\s+r\.json\(\)", body), \
            "r.json() 必须 return await——否则解析 rejection 绕过 catch"

    def test_failure_shape_matches_consumer_contract(self):
        # pages.js 消费面两种判法：`!d.ok` + d.error / (d.errors||[]).join("; ")
        body = _api_body()
        assert re.search(r"ok:\s*false", body)
        assert re.search(r"error:\s*m\b", body)
        assert re.search(r"errors:\s*\[\s*m\s*\]", body), \
            "errors 数组与 (d.errors||[]).join 消费面契约对齐"

    def test_failure_visible_via_msg(self):
        # 失败必须可见（审计口径：不只返回形状），经既有 msg() 呈现
        assert re.search(r"msg\(\s*m\s*,\s*false\s*\)", _api_body())

    def test_palette_lazy_fetch_keeps_own_catch(self):
        # palette.js 自带 api（不消费 app.js 版），其懒取链必须有 catch 降级
        assert re.search(r"\.catch\(\s*\(\)\s*=>\s*\{", _PALETTE)


# ────────────────────────── 2. 切页焦点管理（P1-1） ──────────────────────────

class TestPageSwitchFocus:
    def test_activate_focuses_new_page_heading(self):
        # activate 切页后焦点随页走：新页 h2.page 动态补 tabindex=-1 聚焦
        assert re.search(r"#view-['\"]\s*\+\s*v\s*\+\s*['\"] h2\.page", _APP), \
            "activate 须查询新页 h2.page"
        assert 'h.setAttribute("tabindex", "-1")' in _APP
        assert "preventScroll: true" in _APP

    def test_focus_scheduled_after_view_render(self):
        # showPage 先 activate 后同步渲染视图——聚焦必须 setTimeout(0) 延后
        m = re.search(r"setTimeout\(\(\)\s*=>\s*\{[^}]*h2\.page", _APP, re.S)
        assert m, "切页聚焦须宏任务延后（视图 innerHTML 在 activate 之后渲染）"

    def test_page_name_announced_via_live_region(self):
        # 页名公告走自建视觉隐藏 live region（#msg 是 toast 面，不挪用）
        assert re.search(r"function announce\(", _APP)
        assert 'setAttribute("aria-live", "polite")' in _APP
        assert "clip:rect(0 0 0 0)" in _APP, "live region 须视觉隐藏"


# ────────────────────────── 3. 灯箱弹层三件套（P1-3） ──────────────────────────

class TestLightboxModalTrio:
    def test_focus_saved_and_restored(self):
        assert re.search(r"_lbSavedFocus\s*=\s*document\.activeElement", _APP)
        assert re.search(r"_lbSavedFocus\.focus\(\)", _APP), "关闭须还焦触发元素"
        m = re.search(r"function lightboxClose\(\)\s*\{(.*?)\n\}", _APP, re.S)
        assert m, "lightboxClose 单源关闭入口丢失"
        assert 'classList.remove("show")' in m.group(1)

    def test_focus_moves_into_modal_on_open(self):
        # 灯箱内常无可聚焦元素——焦点落弹层本体（动态 tabindex=-1）
        m = re.search(r"export function lightboxContent\(.*?\n\}", _APP, re.S)
        assert m, "lightboxContent 丢失"
        assert 'lb.setAttribute("tabindex", "-1")' in m.group(0)
        assert re.search(r"lb\.focus\(", m.group(0))

    def test_escape_closes(self):
        m = re.search(r'if \(e\.key === "Escape"\)\s*\{', _APP)
        assert m, "灯箱 Esc 关闭缺失"
        assert re.search(
            r'if \(e\.key === "Escape"\)\s*\{\s*e\.preventDefault\(\);\s*lightboxClose\(\);',
            _APP, re.S)

    def test_tab_wraps_inside_modal(self):
        # Tab 回绕：可聚焦元素首尾循环 + 无可聚焦元素时焦点钉在弹层本体
        assert re.search(r"\[tabindex\]:not\(\[tabindex=['\"]-1['\"]\]\)", _APP)
        assert re.search(r"e\.shiftKey\s*\?\s*focusables\[focusables\.length - 1\]", _APP)
        assert re.search(r"if \(!focusables\.length\)\s*\{ lb\.focus\(", _APP)


# ────────────────────────── 4. palette 同模式存续（最小面） ──────────────────────────

class TestPalettePatternParity:
    def test_palette_keeps_focus_trio(self):
        # 完整断言在 test_ui_a11y_theme.py（W2-A 席）——此处只钉同模式存续，
        # 防本批灯箱改造后两处模式漂移
        assert "savedFocus = doc.activeElement" in _PALETTE
        assert '"Escape"' in _PALETTE
        assert "savedFocus.focus()" in _PALETTE


# ────────────────────────── 5. 跳过链接行为绑定（P2-4） ──────────────────────────

class TestSkipLinkBinding:
    def test_app_binds_skip_link_defensively(self):
        # 锚点与目标 id 本体在 index.html（W2-A 席诉求：<a class="skip-link">
        # + <main id="main-content">）；app.js 只绑行为且锚点缺席时零副作用
        assert re.search(r'document\.querySelector\("a\.skip-link"\)', _APP)
        assert re.search(r'getElementById\("main-content"\)', _APP)
        assert re.search(r"if \(_skip\)\s*\{", _APP), "锚点缺席必须静默不绑"

    def test_binding_focuses_target_with_tabindex(self):
        m = re.search(r"const _skip = document\.querySelector.*?\n\}", _APP, re.S)
        assert m, "跳过链接绑定块丢失"
        assert 'target.setAttribute("tabindex", "-1")' in m.group(0)
        assert "preventDefault" in m.group(0)
        assert re.search(r"target\.focus\(", m.group(0))


# ────────────────────────── 6. ocean 主题图表色对比度（自含 WCAG） ──────────────────────────

def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hx: str) -> float:
    r, g, b = (int(hx[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _chart_palette(tier: str) -> list[str]:
    m = re.search(r"const\s+CHART_COLORS\s*=\s*\{(.*?)\n\};", _THEME, re.S)
    assert m, "CHART_COLORS 丢失"
    mm = re.search(rf"{tier}\s*:\s*\[(.*?)\]", m.group(1), re.S)
    assert mm, f"CHART_COLORS.{tier} 档丢失"
    colors = re.findall(r'"(#[0-9a-fA-F]{6})"', mm.group(1))
    assert len(colors) >= 5, f"{tier} 档色数"
    return colors


def _theme_var(block_re: str, var: str) -> str:
    m = re.search(block_re, _INDEX, re.S)
    assert m, f"CSS 块缺失: {block_re}"
    v = re.search(rf"{re.escape(var)}\s*:\s*(#[0-9a-fA-F]{{6}})", m.group(1))
    assert v, f"变量缺失: {var}"
    return v.group(1)


class TestOceanChartPaletteContrast:
    """R1 审计未核项补账：ocean 底色下 dark 档系列色 >=3:1（WCAG 图形）。

    两暗主题（midnight/ocean）下 body.light 均不置位 → 共用 dark 档；
    ocean --plot-bg=#091525 实测最低 #ba68c8=5.15:1，第三档不必要。"""

    def test_dark_tier_vs_ocean_plot_bg(self):
        plot = _theme_var(r'html\[data-theme="ocean"\]\s*\{(.*?)\}', "--plot-bg")
        assert plot.lower() == "#091525", f"ocean --plot-bg 变更须复核本钉: {plot}"
        for c in _chart_palette("dark"):
            r = _ratio(c, plot)
            assert r >= 3.0, f"ocean 图表色 {c} 对 {plot} = {r:.3f} < 3.0"

    def test_dark_tier_vs_midnight_plot_bg(self):
        # 缺省主题顺带钉（theme.js 注释口径 #0d1322，A5-B 单源迁移）
        plot = _theme_var(r":root\s*\{(.*?)\}", "--plot-bg")
        assert plot.lower() == "#0d1322", f"midnight --plot-bg 变更须复核本钉: {plot}"
        for c in _chart_palette("dark"):
            r = _ratio(c, plot)
            assert r >= 3.0, f"midnight 图表色 {c} 对 {plot} = {r:.3f} < 3.0"

    def test_light_tier_vs_light_plot_bg(self):
        plot = _theme_var(r"body\.light\s*\{(.*?)\}", "--plot-bg")
        for c in _chart_palette("light"):
            r = _ratio(c, plot)
            assert r >= 3.0, f"light 图表色 {c} 对 {plot} = {r:.3f} < 3.0"


# ────────────────────────── 7. msg toast 自动撤销（W8-B P1-2） ──────────────────────────

def _msg_body() -> str:
    m = re.search(r"export function msg\(text, ok\)\s*\{(.*?)\n\}", _APP, re.S)
    assert m, "msg() 实体丢失"
    return m.group(1)


class TestMsgAutoDismiss:
    """W8-B P1-2：err toast 此前无撤销路径，一次 500 的残影跨页滞留
    >3 分钟误导当前状态。错误 8s 自动清除（ok 保持 4s）。"""

    def test_error_toast_auto_clears_8s(self):
        m = re.search(r"ok\s*\?\s*(\d+)\s*:\s*(\d+)", _msg_body())
        assert m, "ok/err 双档自动撤销定时丢失"
        assert m.group(1) == "4000" and m.group(2) == "8000", \
            "ok 须保持 4s；err 须 8s 自动清除（W8-B P1-2）"

    def test_new_message_cancels_pending_timer(self):
        # 单定时器句柄：新消息先 clearTimeout——否则先到 ok 的 4s 撤销
        # 会把后到的 err 提前清掉（双定时器并存缺陷）
        body = _msg_body()
        assert re.search(r"if\s*\(_msgTimer\)\s*clearTimeout\(_msgTimer\)", body), \
            "新消息必须先清旧定时器"
        assert re.search(r"_msgTimer\s*=\s*setTimeout\(", body), \
            "撤销定时必须挂句柄（可被后续消息取消）"


# ────────────────────────── 8. 3D 视口主题两档（W8-B P2-2） ──────────────────────────

class TestScene3DThemeTiers:
    """W8-B P2-2：drawBoxes 的 scene.background 此前硬编码深底 0x0d1118，
    light 主题下画布近黑与页面浅底强反差。SCENE3D 两档常量 + body.light
    判定；描边/网格随档同步（源码钉，风格同 TestDrawBoxesAxisMapping）。"""

    def test_scene3d_two_tiers_present(self):
        m = re.search(r"const\s+SCENE3D\s*=\s*\{(.*?)\n\};", _APP, re.S)
        assert m, "SCENE3D 两档常量丢失"
        for tier, bg, edge, grid in (
            ("dark", "0x0d1118", "0x0a0c10", "0x242c3d"),
            ("light", "0xe8edf5", "0x2a3242", "0xb9c2d0"),
        ):
            mm = re.search(rf"{tier}\s*:\s*\{{(.*?)\}}", m.group(1), re.S)
            assert mm, f"SCENE3D.{tier} 档丢失"
            assert f"bg: {bg}" in mm.group(1), f"{tier} bg 漂移"
            assert f"edge: {edge}" in mm.group(1), f"{tier} edge 漂移"
            assert f"grid: {grid}" in mm.group(1), f"{tier} grid 漂移"

    def test_draw_boxes_consumes_body_light(self):
        assert re.search(
            r'SCENE3D\[document\.body\.classList\.contains\("light"\)'
            r'\s*\?\s*"light"\s*:\s*"dark"\]', _APP), \
            "drawBoxes 须按 body.light 现取主题档"
        assert "new THREE.Color(0x0d1118)" not in _APP, "深底硬编码不得回流"
        assert not re.search(r"GridHelper\(\d+,\s*\d+,\s*0x", _APP), \
            "GridHelper 颜色须走 th.grid 两档"
        assert not re.search(r"LineBasicMaterial\(\{\s*color:\s*0x", _APP), \
            "盒描边颜色须走 th.edge 两档"

    def test_light_tier_edge_contrast(self):
        # light 档描边对浅底 >=3:1（WCAG 图形；自含实现与 §6 同源，
        # #118：裁判独立于被测实现——数值在测试侧现算）
        m = re.search(
            r"light:\s*\{[^}]*bg:\s*0x([0-9a-fA-F]{6})[^}]*"
            r"edge:\s*0x([0-9a-fA-F]{6})", _APP, re.S)
        assert m, "light 档 bg/edge 丢失"
        r = _ratio("#" + m.group(1), "#" + m.group(2))
        assert r >= 3.0, f"light 档描边对浅底 = {r:.2f} < 3.0"


# ────────────────────────── 9. 语法门（node --check） ──────────────────────────
@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestSyntax:
    @pytest.mark.parametrize("name", ["app.js", "palette.js"])
    def test_node_check(self, name):
        r = subprocess.run([_NODE, "--check", str(_STATIC / name)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"node --check {name}:\n{r.stderr[-2000:]}"


# ────────────────── 10. 跨席合流件：跳过链接锚点（主代理落 W2-C 诉求） ──────────────────

class TestSkipLinkAnchor:
    def test_index_has_skip_link_and_main_id(self):
        html = (_STATIC / "index.html").read_text(encoding="utf-8")
        assert 'class="skip-link" href="#main-content"' in html, "index.html 缺跳过链接锚点"
        assert '<main id="main-content">' in html, "main 缺 id=main-content"
        assert ".skip-link:focus-visible" in html, "缺聚焦可见样式"
