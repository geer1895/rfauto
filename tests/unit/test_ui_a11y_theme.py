"""PR-1 a11y+主题三态 / PR-2 命令面板 回归钉（规格 §D-8，2026-10-02 批）。

三层：
1. **源码钉（免 node）**：index.html/app.js/pages.js/palette.js 的 aria 覆盖
   （aria-current/role=img/role=status/dialog+aria-modal/:focus-visible）、
   主题三态（dark|light|system+matchMedia 监听+localStorage 延续）、命令面板
   键位（Ctrl/Cmd+K、Esc、↑↓、Enter、`>`/`#` 前缀、焦点陷阱三件套）。
2. **行为钉（node 真执行，缺 node skip）**：pages.js themeIsLight 纯函数
   真值表 + palette.js modeOf/filterItems 前缀/子串匹配。
3. **对比度钉（自含 WCAG 实现）**：从 index.html 解析 :root/ocean/body.light
   三主题变量，独立重算核心对（文字 >=4.5:1 / 图形 >=3:1）——与
   runs/pr1_contrast/compute_contrast.py 互为独立来源（#118：裁判不得单源自证）。
4. **W2-A（aurora36）扩钉**：--muted2 小字正文门（P0-3）、.primary 主色变体
   完整状态面（P0-1）、静态壳错误色令牌化钉（P0-6 静态面）、guide v5 未落项
   收账（--border-angle conic 旋转边框 / CQ / :has()，含 reduced-motion 降级）。

不依赖 runs/（gitignored，干净环境可跑）；不读网络、不启动服务器。
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

# aurora_d UI-R2（2026-10-14）：pages.js 拆分为薄入口 + pages/ 域模块（零构建
# ESM）——源码钉读"入口+全部域模块"并集，行为断言逐字不变（拆分前=单文件）。
def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)

_FILES = {name: (_STATIC / name).read_text(encoding="utf-8")
          for name in ("index.html", "app.js", "pages.js", "palette.js", "theme.js")}
_FILES["pages.js"] = _pages_union_text()  # UI-R2：入口+域模块并集


def _hit(name: str, pattern: str) -> bool:
    return re.search(pattern, _FILES[name]) is not None


# ────────────────────────── 1. 源码钉 ──────────────────────────

class TestA11ySourcePins:
    def test_toast_status_semantics(self):
        assert _hit("index.html", r'id="msg"[^>]*role="status"')
        assert _hit("index.html", r'aria-live="polite"')

    def test_static_dialogs_have_modal_semantics(self):
        assert _hit("index.html", r'id="lightbox"[^>]*role="dialog"')
        assert _hit("index.html", r'id="lightbox"[^>]*aria-modal="true"')
        # 动态弹层（文件浏览器）在 pages.js 建模态
        assert _hit("pages.js", r'setAttribute\("role", "dialog"\)')
        assert _hit("pages.js", r'setAttribute\("aria-modal", "true"\)')

    def test_chart_containers_image_semantics(self):
        # drawEChart / drawLineChart / drawSmith 三类图表容器 role=img + aria-label
        assert _hit("app.js", r'el\.setAttribute\("role", "img"\)')
        assert _hit("app.js", r'canvas\.setAttribute\("role", "img"\)')
        assert _hit("pages.js", r'el\.setAttribute\("role", "img"\)')
        assert _hit("app.js", r'setAttribute\("aria-label", opts\.ariaLabel')
        assert _hit("pages.js", r"Smith 圆图：")

    def test_nav_aria_current_wiring(self):
        assert _hit("app.js", r'setAttribute\("aria-current", "page"\)')
        assert _hit("app.js", r'removeAttribute\("aria-current"\)')

    def test_focus_visible_ring_and_no_outline_removal(self):
        assert _hit("index.html", r":focus-visible\s*\{[^}]*outline:\s*2px solid")
        for name, text in _FILES.items():
            for m in re.finditer(r"outline\s*:\s*(none|0)\s*;", text):
                pytest.fail(f"{name} 出现 outline 删除: {text[m.start():m.end()]!r}")

    def test_palette_dom_skeleton_and_script(self):
        assert _hit("index.html", r'id="palette-overlay"')
        assert _hit("index.html", r'role="dialog"[^>]*aria-label="命令面板"')
        assert _hit("index.html", r'role="listbox"')
        assert _hit("index.html", r'src="/static/palette\.js"')

    def test_no_flat_dark_only_series_colors(self):
        # 页内显式系列色必须主题分档（#22d3a5 白底 ~1.9:1、#4fc3f7 ~2.0:1）
        bad = re.compile(
            r'color:\s*"(#22d3a5|#4fc3f7|#ffb74d|#81c784|#e57373|#ba68c8)"')
        for name in ("pages.js", "app.js"):
            m = bad.search(_FILES[name])
            assert m is None, f"{name} 扁平深色档系列色: {m.group(0) if m else ''}"

    def test_nav_registry_count_unchanged(self):
        # 禁改清单：22 页注册表之外不得新增/删除路由语义
        # ge8b Wave B 席B2/B3 增量：画廊/仪表盘/profile/队列四页（22→26）
        assert len(re.findall(r'data-v="', _FILES["index.html"])) == 26
        assert len(re.findall(r'id="view-', _FILES["index.html"])) == 26


class TestThemeTriStateSourcePins:
    def test_three_modes_and_matchmedia(self):
        # aurora72 A5-B（R6 R-4）：THEME_MODES 单源迁 theme.js（pages.js re-export）
        assert _hit("theme.js", r'THEME_MODES = \["midnight", "ocean", "light", "system"\]')  # v5.0 Aurora 四态（dark=旧存量别名）
        assert _hit("pages.js", r'matchMedia\("\(prefers-color-scheme: light\)"\)')
        assert _hit("pages.js", r'addEventListener\("change", onSysChange\)')

    def test_persistence_key_unchanged(self):
        # 规格纠偏：持久化已存在（localStorage rfauto-theme），键名不得改
        # （A5-B：键面单源迁 theme.js，pages.js re-export；boot 读档键钉在
        # test_ui_theme_boot 与本键互证）
        assert _hit("theme.js", r'THEME_KEY = "rfauto-theme"')
        assert _hit("pages.js", r'localStorage\.setItem\(THEME_KEY, m\)')

    def test_light_matrix_has_accent2(self):
        # 切换矩阵补洞：body.light 必须重定义 --accent2（浅色不再沿用深色青绿）
        m = re.search(r"body\.light\s*\{(.*?)\}", _FILES["index.html"], re.S)
        assert m, "body.light 块丢失"
        assert "--accent2:" in m.group(1)
        dark = re.search(r":root\s*\{(.*?)\}", _FILES["index.html"], re.S)
        assert "--accent2:" in dark.group(1)
        # 补洞后浅色 accent2 不得等于深色值（#22d3a5 白底 ~1.9:1）
        assert "#22d3a5" not in m.group(1).lower()


class TestPaletteSourcePins:
    def test_keybindings(self):
        assert _hit("palette.js", r"e\.ctrlKey \|\| e\.metaKey")
        assert _hit("palette.js", r'"k"')
        assert _hit("palette.js", r'"Escape"')
        assert _hit("palette.js", r'"ArrowDown"') and _hit("palette.js", r'"ArrowUp"')
        assert _hit("palette.js", r'"Enter"')
        assert _hit("palette.js", r'"Tab"')

    def test_focus_trap_trio(self):
        assert _hit("palette.js", r"savedFocus = doc\.activeElement")
        assert _hit("palette.js", r"focusables\[")
        assert _hit("palette.js", r"savedFocus\.focus\(\)")

    def test_prefix_modes_and_data_sources(self):
        assert _hit("palette.js", r'startsWith\(">"\)')
        assert _hit("palette.js", r'startsWith\("#"\)')
        assert _hit("palette.js", r"/api/runs\?limit=200")
        assert _hit("palette.js", r'"/api/recipes"')
        # 页面项从 nav 注册表派生（不落第二份 22 页清单）
        assert _hit("palette.js", r'querySelectorAll\("#nav button\[data-v\]"\)')
        # 出口复用：不绕开 pages.js 单源
        assert _hit("palette.js", r'from "./pages\.js"')
        assert _hit("pages.js", r"export function openRun")

    def test_no_new_api_endpoints_required(self):
        # PR-2 零新增 /api 端点（server.py 路由面不变 → 端点计数钉不受扰；
        # aurora_d UI-R1 拆分后 handler 引用带 <域>_routes. 命名空间前缀）
        server = (Path(_STATIC).parent / "server.py").read_text(encoding="utf-8")
        assert 'Route("/api/runs", runs_routes.api_runs)' in server
        assert 'Route("/api/recipes", recipes_routes.api_recipes)' in server


# ────────────────────────── 2. 行为钉（node） ──────────────────────────

def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2000:]}"
    return r.stdout


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestBehavioralNode:
    def test_theme_is_light_truth_table(self):
        out = _run_node_js(
            "const m = await import('./pages.js');\n"
            "const t = m.themeIsLight;\n"
            "const rows = [\n"
            "  ['dark', false, false], ['dark', true, false],\n"
            "  ['light', false, true], ['light', true, true],\n"
            "  ['system', false, false], ['system', true, true],\n"
            "  ['junk', true, true],  // 未知值兜底=跟随系统\n"
            "];\n"
            "for (const [mode, sys, want] of rows)\n"
            "  if (t(mode, sys) !== want) throw new Error(`fail ${mode} ${sys}`);\n"
            "console.log('ok:' + rows.length);\n")
        assert "ok:7" in out

    def test_palette_mode_and_filter(self):
        out = _run_node_js(
            "const m = await import('./palette.js');\n"
            "if (m.modeOf('dashboard') !== 'nav') throw new Error('nav');\n"
            "if (m.modeOf('>theme') !== 'cmd') throw new Error('cmd');\n"
            "if (m.modeOf('#2026') !== 'run') throw new Error('run');\n"
            "const items = [\n"
            "  { mode: 'nav', title: '总览', haystack: '总览 dashboard' },\n"
            "  { mode: 'nav', title: 'Run 历史', haystack: 'Run 历史 runs' },\n"
            "  { mode: 'cmd', title: '主题：深色', haystack: '主题：深色 theme dark' },\n"
            "  { mode: 'run', title: '20261001_120000_x', haystack: '20261001_120000_x hfss' },\n"
            "];\n"
            "if (m.filterItems(items, '总览').length !== 1) throw new Error('cjk 子串');\n"
            "if (m.filterItems(items, 'RUNS').length !== 1) throw new Error('大小写');\n"
            "if (m.filterItems(items, '>').length !== 1) throw new Error('cmd 全列');\n"
            "if (m.filterItems(items, '>DARK').length !== 1) throw new Error('cmd 匹配');\n"
            "if (m.filterItems(items, '#2026').length !== 1) throw new Error('run 匹配');\n"
            "if (m.filterItems(items, '#zzz').length !== 0) throw new Error('run 不匹配');\n"
            "if (m.filterItems(items, '').length !== 2) throw new Error('nav 全列');\n"
            "console.log('ok:palette');\n")
        assert "ok:palette" in out

    def test_node_check_all_static_js(self):
        for name in ("index.html", "app.js", "pages.js", "palette.js"):
            if name.endswith(".html"):
                continue
            r = subprocess.run([_NODE, "--check", str(_STATIC / name)],
                               capture_output=True, text=True, timeout=60)
            assert r.returncode == 0, f"node --check {name}:\n{r.stderr[-2000:]}"


# ────────────────────────── 3. 对比度钉（自含 WCAG） ──────────────────────────

def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hx: str) -> float:
    r, g, b = (int(hx[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _blend(fg: str, bg: str, alpha: float) -> str:
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    t = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#{:02x}{:02x}{:02x}".format(
        *(round(x * alpha + y * (1 - alpha)) for x, y in zip(f, t, strict=True)))


def _vars(block_re: str) -> dict[str, str]:
    m = re.search(block_re, _FILES["index.html"], re.S)
    assert m, f"CSS 块缺失: {block_re}"
    return dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", m.group(1)))


class TestContrastPin:
    """核心变量矩阵（自含实现，与 compute_contrast.py 独立双源）。

    W2-A 起三主题全覆盖（ocean=html[data-theme] 块此前无钉）。
    """

    # 三主题块（v5.0 Aurora：midnight=:root、ocean=html[data-theme]、
    # light=body.light 镜像块；html[data-theme="light"] 块与 body.light
    # 逐字一致，解析器口径沿用 body.light（历史钉原样））。
    _THEME_BLOCKS = (
        (r":root\s*\{(.*?)\}", "midnight"),
        (r'html\[data-theme="ocean"\]\s*\{(.*?)\}', "ocean"),
        (r"body\.light\s*\{(.*?)\}", "light"),
    )

    def test_three_themes_text_and_graphics(self):
        for block, theme in self._THEME_BLOCKS:
            v = _vars(block)
            bg, panel, panel2 = v["--bg"], v["--panel"], v["--panel2"]
            plot = v["--plot-bg"]
            # 正文 >=4.5:1（--muted2 用于 10-12px 小字正文：导航分组/foot/
            # 占位符/palette 提示——P0-3 收敛后同门槛钉死，防回退）
            for fgv in ("--fg", "--muted", "--muted2", "--accent",
                        "--ok", "--warn", "--err"):
                for bgv in (bg, panel, panel2):
                    r = _ratio(v[fgv], bgv)
                    assert r >= 4.5, f"{theme} {fgv} on {bgv} = {r:.3f} < 4.5"
            # badge 14% 透明底（.badge.ok/.err/.warn 以 panel 为底的混合）
            for fgv in ("--ok", "--warn", "--err"):
                r = _ratio(v[fgv], _blend(v[fgv], panel, 0.14))
                assert r >= 4.5, f"{theme} badge {fgv} = {r:.3f} < 4.5"
            # UI 图形 >=3:1（accent 焦点环/accent2 图表系列）
            assert _ratio(v["--accent"], panel) >= 3.0, f"{theme} accent graphic"
            assert _ratio(v["--accent2"], plot) >= 3.0, f"{theme} accent2 graphic"
            # 主按钮 .act：历史钉口径（accent/act2 停靠 × 深字/反白）
            btn_fg = "#ffffff" if theme == "light" else "#04121c"
            assert _ratio(btn_fg, v["--accent"]) >= 4.5, f"{theme} act 起点文字"
            assert _ratio(btn_fg, v["--act2"]) >= 4.5, f"{theme} act 尾文字"
            # 主按钮 .primary（W2-A 新增变体）：accent→accent2 停靠 ×
            # --act-fg（单源解析，替代硬编码）
            act_fg = v["--act-fg"]
            assert _ratio(act_fg, v["--accent"]) >= 4.5, f"{theme} primary 起点文字"
            assert _ratio(act_fg, v["--accent2"]) >= 4.5, f"{theme} primary 尾文字"

    def test_chart_palettes_vs_plot_bg(self):
        # A5-B（R6 R-4）：CHART_COLORS 单源迁 theme.js（app.js/pages.js 经
        # chartPalette 消费）——对比度钉换地址不换值
        m = re.search(r"const\s+CHART_COLORS\s*=\s*\{(.*?)\};", _FILES["theme.js"], re.S)
        assert m, "CHART_COLORS 丢失"
        dark_vars = _vars(r":root\s*\{(.*?)\}")
        light_vars = _vars(r"body\.light\s*\{(.*?)\}")
        for theme, vars_ in (("dark", dark_vars), ("light", light_vars)):
            mm = re.search(rf"{theme}\s*:\s*\[(.*?)\]", m.group(1), re.S)
            colors = re.findall(r'"(#[0-9a-fA-F]{6})"', mm.group(1))
            assert len(colors) >= 5, f"{theme} 调色板色数"
            for c in colors:
                r = _ratio(c, vars_["--plot-bg"])
                assert r >= 3.0, f"{theme} chart {c} = {r:.3f} < 3.0"


# ────────────────────────── 3b. W2-A 样式面钉（aurora36） ──────────────────────────

class TestW2AStylePins:
    """aurora36 W2-A（UI 样式面四项 + guide 未落两项）回归钉。

    pages.js/app.js 本席禁改——P0-1 走 index.html 补 .primary 别名选择器路线
    （审计 P0-1 给出的两路线之一）；P0-6 的 pages.js 内联三处 #e57373 属
    JS 席位面，此处只钉静态壳零硬编码错误色 + 令牌链在位。
    """

    def test_primary_button_variant_fully_styled(self):
        # P0-1：.primary 主色变体须有完整状态面（hover/active/focus-visible/
        # disabled），底色走 accent 系令牌、文字走 --act-fg 单源
        src = _FILES["index.html"]
        m = re.search(r"button\.primary\s*\{([^}]*)\}", src)
        assert m, "button.primary 规则缺失（P0-1 主按钮裸奔回归）"
        assert "--accent" in m.group(1) and "--act-fg" in m.group(1)
        for state in (":hover", ":active", ":focus-visible", ":disabled"):
            assert re.search(rf"button\.primary{re.escape(state)}\s*\{{", src), state
        # 浅色反白口径与 .act 同构
        assert re.search(r"body\.light button\.primary\s*\{[^}]*#ffffff", src)

    def test_no_hardcoded_error_hex_in_index_html(self):
        # P0-6 静态面：错误色一律走 --err 系令牌；审计点名硬编码错误色家族
        # 禁止在静态壳复活
        for hex6 in ("#e57373", "#ef5350", "#b3261e", "#ff8a80", "#f28b82"):
            assert hex6 not in _FILES["index.html"].lower(), hex6
        # 令牌链在位：三主题块均定义 --err 与 --err-bg
        for block, _theme in TestContrastPin._THEME_BLOCKS:
            text = re.search(block, _FILES["index.html"], re.S).group(1)
            assert "--err:" in text and "--err-bg:" in text

    def test_muted2_aa_gate_all_three_themes(self):
        # P0-3 显式钉（矩阵内亦含，此处单列便于失败定位）：--muted2 全主题
        # 正文级 ≥4.5:1
        for block, theme in TestContrastPin._THEME_BLOCKS:
            v = _vars(block)
            for bgv in ("--bg", "--panel", "--panel2"):
                r = _ratio(v["--muted2"], v[bgv])
                assert r >= 4.5, f"{theme} --muted2 on {bgv} = {r:.3f} < 4.5"

    def test_guide_v5_features_landed(self):
        # guide §3.9-3.11/§1.1 未落项收账（W2-A）：
        # --border-angle 死注册 → KPI 卡 hover conic 旋转边框（@property 动画）
        src = _FILES["index.html"]
        assert "conic-gradient(from var(--border-angle)" in src
        assert re.search(r"animation:\s*border-spin\b", src)
        assert "@keyframes border-spin" in src
        # CQ/:has() 渐进增强（不支持引擎对应块整体忽略=零劣化）
        assert "container: sidebar / inline-size" in src
        assert "@container sidebar" in src
        assert re.search(r"tbody tr:has\(", src)
        # reduced-motion 降级=静止（旋转边框不转）
        m = re.search(r"prefers-reduced-motion: reduce\)\s*\{(.*?)\n\}", src, re.S)
        assert m, "reduced-motion 降级块丢失"
        assert ".card::after" in m.group(1)


# ────────────────────────── 4. runs/ 证据面存在性（软钉） ──────────────────────────

def test_contrast_evidence_table_exists_locally():
    """runs/pr1_contrast/ 是 gitignored 证据面：存在时校验口径一致，缺席跳过
    （干净环境不依赖 runs/；本机开发面要求核算表在档）。"""
    evidence = Path(__file__).resolve().parents[2] / "runs" / "pr1_contrast" / "contrast_table.json"
    if not evidence.exists():
        pytest.skip("runs/pr1_contrast/contrast_table.json 不在档（开发机应先跑 compute_contrast.py）")
    d = json.loads(evidence.read_text(encoding="utf-8"))
    assert d["n_fail"] == 0
    assert d["min_text"]["ratio"] >= 4.5 and d["min_graphic"]["ratio"] >= 3.0
