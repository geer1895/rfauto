"""架构批 A5-B（R6 审计 R-4）：UI 主题档单源 theme.js 回归钉。

R-4 收编前：pages.js 22 处 body.light 判定 + 30 处 `light ? "#…" : "#…"`
双档三元、app.js CHART_COLORS 表 + pages.js timeline 整档镜像、热图色带
三份字面量各自为政（"本层不可 import"的被迫镜像纪律）。收编后单源在
theme.js（零依赖、零顶层 DOM 执行，node 无 DOM 可 import——palette.js
先例），app.js/pages.js 同源消费。本钉三层：

1. **单源棘轮（源码文本，免 node）**：body.light 判定/双档三元/调色板
   字面量在 pages.js/app.js 归零（app.js SCENE3D 一处豁免=跨席源码钉
   test_ui_nav_focus 逐字钉住其消费位，A5-B 不动）；CHART_COLORS/HEAT_BAND/
   THEME_COLORS 双档值全 static 只出现一次（theme.js）。
2. **行为钉（node 真执行，缺 node skip）**：theme.js 无 DOM 环境真值表
   + 无 DOM 守卫（applyThemeDom→null / bodyIsLight→false）+ pages.js
   re-export 绑定同一性（消费面 import 自 pages.js 的历史口径不破）。
3. **双写单源钉**：applyThemeDom 的 html[data-theme]+body.light 双写与
   setThemeMode/initPages 持久化路径仍走 THEME_KEY（与 index.html head
   防闪 boot 同键，test_ui_theme_boot 互证）。

不依赖 runs/、不读网络、不启动服务器；index.html/boot 内联脚本零改动
（CSP 哈希钉 test_w1e_ui_csp 不受扰）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

# 架构批 UI-R2（2026-10-14）：pages.js 拆分为薄入口 + pages/ 域模块（零构建
# ESM）——源码钉读"入口+全部域模块"并集，行为断言逐字不变（拆分前=单文件）。
def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)

_FILES = {name: (_STATIC / name).read_text(encoding="utf-8")
          for name in ("app.js", "pages.js", "palette.js", "plotcard.js", "theme.js")}
_FILES["pages.js"] = _pages_union_text()  # UI-R2：入口+域模块并集


# ────────────────────────── 1. 单源棘轮（源码文本） ──────────────────────────

class TestSingleSourceRatchet:
    # app.js 唯一豁免位：SCENE3D 两档 3D 场景色消费（跨席源码钉
    # test_ui_nav_focus::test_draw_boxes_consumes_body_light 逐字钉住，
    # A5-B 不动该行；其余判定必须走 theme.js bodyIsLight）
    _APP_EXEMPT = (
        r'SCENE3D\[document\.body\.classList\.contains\("light"\)'
        r'\s*\?\s*"light"\s*:\s*"dark"\]'
    )

    def test_theme_js_exists_and_zero_dependency(self):
        src = _FILES["theme.js"]
        assert "export function themeIsLight(" in src
        assert "export function applyThemeDom(" in src
        assert "export function bodyIsLight(" in src
        assert "export function chartPalette(" in src
        assert "export function themePick(" in src
        assert "export const THEME_COLORS" in src
        assert "export const HEAT_BAND" in src
        assert 'export const THEME_KEY = "rfauto-theme"' in src
        assert "export const THEME_MODES" in src
        assert "export const THEME_LABEL" in src
        # 零依赖：theme.js 不得 import 任何模块（node 裸 import 的前提）
        assert not re.search(r'(^|\n)\s*import[\s{(]', src), "theme.js 必须零 import"
        assert 'from "' not in src

    def test_body_light_judgments_collapsed(self):
        # pages.js 判定归零（22→0）；app.js 仅剩 SCENE3D 豁免位（3→1）；
        # palette.js/plotcard.js 本就无判定（plotcard 禁改面，A5-B 不触）
        assert 'document.body.classList.contains("light")' not in _FILES["pages.js"]
        assert 'document.body.classList.contains("light")' not in _FILES["palette.js"]
        n_app = _FILES["app.js"].count('document.body.classList.contains("light")')
        assert n_app == 1, f"app.js body.light 判定应仅剩 SCENE3D 豁免 1 处，实测 {n_app}"
        assert re.search(self._APP_EXEMPT, _FILES["app.js"]), "SCENE3D 豁免位漂移"

    def test_light_ternary_mirrors_collapsed(self):
        # `light ? "#…"` / `contains(...) ? "#…"` 双档三元在 pages.js/app.js 归零
        #（值面收编 THEME_COLORS/chartPalette/HEAT_BAND）
        for name in ("pages.js", "app.js"):
            src = _FILES[name]
            assert not re.search(r'light\s*\?\s*"#', src), f"{name} 残留 light 三元"
            assert not re.search(r'contains\("light"\)\s*\?\s*"#', src), \
                f"{name} 残留内联判定三元"

    def test_chart_colors_single_copy(self):
        # CHART_COLORS 表全 static 唯一（旧 app.js 表 + pages.js timeline
        # 整档镜像 + wStatusMix pass/fail/other 镜像全收编）
        hits = [n for n, s in _FILES.items() if re.search(r"const\s+CHART_COLORS\s*=", s)]
        assert hits == ["theme.js"], f"CHART_COLORS 定义面: {hits}"
        # 档位取值统一走 chartPalette（含 app.js 三消费点与 pages.js timeline）
        assert _FILES["app.js"].count("chartPalette(light)") >= 3
        assert "chartPalette(bodyIsLight())" in _FILES["pages.js"]
        # Smith 第 6 档走 smithPalette 单源（drawSmith 旧六色三元镜像收编）
        assert _FILES["pages.js"].count("smithPalette(light)") == 1
        assert "export function smithPalette(" in _FILES["theme.js"]
        # 旧 timeline/Smith 整档镜像字面量不得回流（五/六色组只在 theme.js）
        for hex6 in ("#0277bd", "#b26a00", "#276b2c", "#c62828", "#6a1b9a",
                     "#0e8f74", "#fff176",
                     "#4fc3f7", "#ffb74d", "#81c784", "#e57373", "#ba68c8"):
            for name in ("pages.js", "app.js"):
                if hex6 == "#ffb74d" and name == "app.js":
                    # 豁免：3D 端口锥/标签标记色（SCENE3D 家族、主题无关），
                    # 与 dark 档系列色同值——钉唯一出现位防扩散
                    assert _FILES[name].count(hex6) == 1
                    continue
                assert hex6 not in _FILES[name], f"{name} 回流系列色 {hex6}"

    def test_theme_colors_pairs_single_copy(self):
        # 双档色对逐对只在 theme.js（"#ffffff" 豁免：pages.js field 切片
        # levelColors 等高线色是主题无关三档，非双档镜像；plotcard.js:24
        # 的 fg 同值镜像属禁改面，A5-B 范围外如实留账——只查 pages.js/app.js
        # 双档镜像值归零）
        for hex6 in ("#1b2330", "#0d1118", "#dde3ec", "#1c2331",
                     "#7f899d", "#5b6780", "#e7ebf2", "#b8c2d2", "#3a4458",
                     "#b26a00", "#0e8f74", "#b3261e", "#ef5350", "#e5e9f0",
                     "#1a2130"):
            for name in ("pages.js", "app.js"):
                assert hex6 not in _FILES[name], f"{name} 残留双档色 {hex6}"
        # fg 深档值旧 app.js makeLabelSprite 缺省分支已收编（THEME_COLORS.fg.dark）；
        # plotcard.js:24 的一处既有镜像（禁改面）如实登记，不扩散
        assert "THEME_COLORS.fg.dark" in _FILES["app.js"]
        assert "#dce3ee" in _FILES["theme.js"]
        assert "#dce3ee" not in _FILES["app.js"]

    def test_heat_band_single_copy(self):
        band = '"#0d1118", "#1e3a8a", "#2563eb", "#22c55e", "#facc15", "#ef4444", "#ffffff"'
        hits = [n for n, s in _FILES.items() if band in s]
        assert hits == ["theme.js"], f"热图色带定义面: {hits}"
        assert _FILES["pages.js"].count("color: HEAT_BAND") == 3  # 工具页/场切片/远场 3D

    def test_constants_single_source_and_reexport(self):
        t, p = _FILES["theme.js"], _FILES["pages.js"]
        assert 'THEME_KEY = "rfauto-theme"' in t
        assert 'THEME_KEY = "rfauto-theme"' not in p  # 键面字面量不在 pages.js（防双源）
        assert re.search(r'THEME_MODES = \["midnight", "ocean", "light", "system"\]', t)
        assert not re.search(r'THEME_MODES = \["midnight"', p)
        assert re.search(
            r'export \{ THEME_KEY, THEME_MODES, THEME_LABEL, themeIsLight \};', p)
        # THEME_LABEL 四态标签单源（pages.js 旧内联字面量收编）
        assert 'midnight: "🌌 Midnight"' in t
        assert 'midnight: "🌌 Midnight"' not in p
        # 持久化路径仍走 THEME_KEY（palette/主题钮消费面不变）
        assert "localStorage.setItem(THEME_KEY, mode)" in p  # setThemeMode 兜底
        assert "localStorage.setItem(THEME_KEY, m)" in p     # _themeCtl.set
        assert "localStorage.getItem(THEME_KEY)" in p        # getThemeMode/读档

    def test_apply_theme_dom_dual_write_single_source(self):
        src = _FILES["theme.js"]
        assert "document.documentElement.dataset.theme = r;" in src
        assert 'document.body.classList.toggle("light", r === "light");' in src
        # system 态解算口径单源（light/midnight 二值，与 boot 同口径）
        assert 'mode === "system" ? (systemPrefersLight() ? "light" : "midnight") : mode' in src
        # pages.js 旧双写实现已拆（apply/setThemeMode 兜底均调 applyThemeDom）
        p = _FILES["pages.js"]
        assert "applyThemeDom(mode)" in p
        assert not re.search(r"function _applyThemeDom\(", p)
        assert not re.search(r"function _sysLight\(", p)


# ────────────────────────── 2. 行为钉（node 真执行） ──────────────────────────

def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2000:]}"
    return r.stdout


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestThemeNodeBehavioral:
    def test_theme_js_imports_without_dom_and_truth_table(self):
        out = _run_node_js(
            "const t = await import('./theme.js');\n"
            "if (t.applyThemeDom('light') !== null) throw new Error('apply 非 null');\n"
            "if (t.applyThemeDom('system') !== null) throw new Error('apply sys 非 null');\n"
            "if (t.bodyIsLight() !== false) throw new Error('body 非 false');\n"
            "if (t.systemPrefersLight() !== false) throw new Error('sys 非 false');\n"
            "const rows = [\n"
            "  ['dark', false, false], ['dark', true, false],\n"
            "  ['light', false, true], ['light', true, true],\n"
            "  ['system', false, false], ['system', true, true],\n"
            "  ['junk', true, true],\n];\n"
            "for (const [m, s, w] of rows)\n"
            "  if (t.themeIsLight(m, s) !== w) throw new Error('truth ' + m);\n"
            "const d = t.chartPalette(false), l = t.chartPalette(true);\n"
            "if (d.join() !== '#4fc3f7,#ffb74d,#81c784,#e57373,#ba68c8') throw new Error('dark 档');\n"
            "if (l.join() !== '#0277bd,#b26a00,#276b2c,#c62828,#6a1b9a') throw new Error('light 档');\n"
            "if (t.themePick(true, t.THEME_COLORS.fg) !== '#1b2330') throw new Error('pick light');\n"
            "if (t.themePick(false, t.THEME_COLORS.fg) !== '#dce3ee') throw new Error('pick dark');\n"
            "if (t.HEAT_BAND.length !== 7) throw new Error('heatband');\n"
            "const sp = t.smithPalette(false);\n"
            "if (sp.length !== 6 || sp[5] !== '#fff176') throw new Error('smith 档');\n"
            "if (t.smithPalette(true)[5] !== '#0e8f74') throw new Error('smith light 档');\n"
            "console.log('ok:theme-node');\n")
        assert "ok:theme-node" in out

    def test_pages_reexport_binding_identity(self):
        out = _run_node_js(
            "const p = await import('./pages.js');\n"
            "const t = await import('./theme.js');\n"
            "if (p.themeIsLight !== t.themeIsLight) throw new Error('themeIsLight 非同一绑定');\n"
            "if (p.THEME_KEY !== t.THEME_KEY) throw new Error('THEME_KEY 漂移');\n"
            "if (p.THEME_MODES !== t.THEME_MODES) throw new Error('THEME_MODES 漂移');\n"
            "if (p.setThemeMode('bogus') !== false) throw new Error('非法 mode 应 false');\n"
            "// getThemeMode 的 localStorage 兜底分支在裸 node 本就抛 ReferenceError\n"
            "//（既有行为，palette.js 消费侧有 try/catch）——不在本钉范围\n"
            "console.log('ok:reexport');\n")
        assert "ok:reexport" in out

    def test_node_check_theme_js(self):
        r = subprocess.run([_NODE, "--check", str(_STATIC / "theme.js")],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]
