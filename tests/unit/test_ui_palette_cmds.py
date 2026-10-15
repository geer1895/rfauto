"""W3-D（aurora36）palette 命令面扩展 + SVG 图标基座 回归钉。

钉四件事：
1. 命令目录（palette.js commandCatalog，纯函数 node 真执行，缺 node skip）：
   总数 14（主题 4 + 页面跳转 7 + 动作 3）、mode/subtitle/中文标题契约、
   "当前"提示只在当前主题、run() 动作面真被调用且参数与 id 对齐；
2. 跳转命令与 showPage 的 data-v 对齐：go-* 目标 ⊆ index.html nav data-v
   全集（跨文件核对，防目录漂移出死命令）；
3. SVG sprite 基座（index.html）：display:none 容器、10 个 symbol 全在档、
   线性口径（fill=none + stroke=currentColor）；palette 引用的 icon 名 ⊆
   symbol 集（防 <use> 悬空）；nav 按钮不重复挂 <use>（席规：已有 .ico
   Unicode 图标的按钮不加第二图标）；
4. palette 行图标挂载：aria-hidden="true"（装饰性不进读屏，guide §11.2）。

不依赖 runs/、不读网络、不启动服务器；index.html/palette.js 只读。
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
_PALETTE = (_STATIC / "palette.js").read_text(encoding="utf-8")

# sprite 基座 symbol 全集（9 席位任务书列名 + refresh=刷新动作命令）
_EXPECTED_SYMBOLS = {
    "dashboard", "runs", "campaign", "tune", "recipe", "tools",
    "gallery", "profile", "settings", "refresh",
}


def _symbol_ids() -> set[str]:
    return set(re.findall(r'<symbol id="icon-([\w-]+)"', _INDEX))


def _nav_block() -> str:
    m = re.search(r'<nav id="nav".*?</nav>', _INDEX, re.S)
    assert m, "index.html #nav 缺失"
    return m.group(0)


def _nav_data_v() -> set[str]:
    return set(re.findall(r'data-v="([\w-]+)"', _nav_block()))


# ────────────────────────── 1. sprite 基座（源码钉） ──────────────────────────

class TestSpriteBase:
    def test_hidden_container_exists(self):
        m = re.search(r'<svg[^>]*style="display:none"[^>]*>', _INDEX)
        assert m, "index.html 缺 display:none 的 SVG sprite 容器"
        assert "aria-hidden" in m.group(0), "sprite 容器应 aria-hidden（纯资源定义）"

    def test_all_symbols_present_and_linear(self):
        ids = _symbol_ids()
        missing = _EXPECTED_SYMBOLS - ids
        assert not missing, f"sprite 缺 symbol: {sorted(missing)}"
        for sid in sorted(ids):
            attrs = re.search(rf'<symbol id="icon-{sid}"[^>]*>', _INDEX).group(0)
            assert 'fill="none"' in attrs, f"{sid} 应为线性口径（fill=none）"
            assert 'stroke="currentColor"' in attrs, f"{sid} 应随主题色（currentColor）"

    def test_nav_buttons_not_double_iconed(self):
        # 席规：nav 按钮已有 .ico Unicode 图标，sprite 基座不得重复挂 <use>
        assert "<use " not in _nav_block(), "nav 按钮已有图标，不得重复挂 <use>"

    def test_icon_map_targets_in_sprite(self):
        # palette.js 视图→图标映射不得引用不存在的 symbol（防 <use> 悬空）
        m = re.search(r"const _ICON_BY_VIEW = \{(.*?)\};", _PALETTE, re.S)
        assert m, "_ICON_BY_VIEW 映射缺失"
        targets = set(re.findall(r':\s*"([\w-]+)"', m.group(1)))
        dangling = targets - _symbol_ids()
        assert not dangling, f"图标映射悬空（sprite 无此 symbol）: {sorted(dangling)}"

    def test_icon_mount_is_aria_hidden_use_ref(self):
        # 行图标：aria-hidden 装饰性 + href="#icon-*" sprite 引用
        assert 'setAttribute("aria-hidden", "true")' in _PALETTE
        assert re.search(r'setAttribute\("href",\s*`#icon-\$\{', _PALETTE)


# ────────────────────────── 2. 命令目录（node 行为钉） ──────────────────────────

def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2000:]}"
    return r.stdout


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestCommandCatalog:
    def test_count_contract_actions_and_alignment(self):
        out = _run_node_js(
            "const m = await import('./palette.js');\n"
            "const calls = { setTheme: [], showPage: [], refresh: 0, help: 0 };\n"
            "const act = {\n"
            "  setTheme: (x) => calls.setTheme.push(x),\n"
            "  showPage: (x) => calls.showPage.push(x),\n"
            "  refresh: () => { calls.refresh++; },\n"
            "  help: () => { calls.help++; },\n"
            "};\n"
            "const cat = m.commandCatalog('midnight', act);\n"
            "if (cat.length !== 14) throw new Error('命令总数=' + cat.length);\n"
            "const cjk = /[\\u4e00-\\u9fff]/;\n"
            "for (const it of cat) {\n"
            "  if (it.mode !== 'cmd') throw new Error('mode: ' + it.id);\n"
            "  if (it.subtitle !== '命令') throw new Error('subtitle: ' + it.id);\n"
            "  if (!cjk.test(it.title)) throw new Error('中文标题: ' + it.title);\n"
            "  if (typeof it.run !== 'function') throw new Error('run: ' + it.id);\n"
            "}\n"
            "const byId = Object.fromEntries(cat.map((it) => [it.id, it]));\n"
            "if (byId['theme-midnight'].hint !== '当前') throw new Error('当前主题应提示');\n"
            "if (byId['theme-ocean'].hint === '当前') throw new Error('非当前主题误提示');\n"
            "for (const [id, mode] of [\n"
            "  ['theme-midnight', 'midnight'], ['theme-ocean', 'ocean'],\n"
            "  ['theme-light', 'light'], ['theme-system', 'system'],\n"
            "]) {\n"
            "  byId[id].run();\n"
            "  if (calls.setTheme[calls.setTheme.length - 1] !== mode) throw new Error(id);\n"
            "}\n"
            "const goIds = cat.map((it) => it.id).filter((id) => id.startsWith('go-'));\n"
            "if (goIds.length !== 7) throw new Error('跳转命令数=' + goIds.length);\n"
            "const goViews = [];\n"
            "for (const id of goIds) {\n"
            "  const before = calls.showPage.length;\n"
            "  byId[id].run();\n"
            "  if (calls.showPage.length !== before + 1) throw new Error(id + ' 未调 showPage');\n"
            "  const v = calls.showPage[calls.showPage.length - 1];\n"
            "  if ('go-' + v !== id) throw new Error(id + ' 与 data-v 不对齐: ' + v);\n"
            "  goViews.push(v);\n"
            "}\n"
            "byId['act-refresh'].run();\n"
            "if (calls.refresh !== 1) throw new Error('act-refresh 未调 refresh');\n"
            "byId['act-palette-help'].run();\n"
            "if (calls.help !== 1) throw new Error('act-palette-help 未调 help');\n"
            "const icons = [...new Set(cat.map((it) => it.icon).filter(Boolean))];\n"
            "console.log('ok:' + cat.length + ':' + goViews.join(',') + ':' + icons.join(','));\n")
        assert "ok:14:" in out
        parts = out.strip().split(":")
        # go 目标与 index.html nav data-v 全集对齐（showPage 单源对齐钉）
        go_views = set(parts[2].split(","))
        assert go_views <= _nav_data_v(), f"跳转目标不在 nav 注册表: {go_views - _nav_data_v()}"
        # 图标引用 ⊆ sprite symbol 集（防 <use> 悬空）
        icons = set(parts[3].split(","))
        assert icons <= _symbol_ids(), f"命令图标悬空: {icons - _symbol_ids()}"
