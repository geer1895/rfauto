"""W3-D（架构批）palette 命令面扩展 + SVG 图标基座 回归钉。

钉四件事：
1. 命令目录（palette.js commandCatalog，纯函数 node 真执行，缺 node skip）：
   总数 20（主题 4 + 页面跳转 7 + 动作 9；架构批 W2-S5 语言切换命令
   act-locale 落地同笔 14→15；架构批 W5-S17 动作扩充同笔 15→20——
   act-run-search/act-run-latest/act-run-2nd/act-run-3rd/act-latest-campaign）、
   mode/subtitle/中文标题契约、"当前"提示只在当前主题、run() 动作面真被调用
   且参数与 id 对齐、act-locale 随语言档翻转提示与切换目标（zh→en / en→zh）、
   W5-S17 五新命令动作面接线（openRecentRun 收 rank 1..3 / enterRunSearch /
   openLatestCampaign）与 recentRunAt 现取（hint 携带 run id+可检索；旧
   两参 spy 缺该方法=hint 回落"直达"零抛降级）；
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
            "const calls = { setTheme: [], showPage: [], refresh: 0, help: 0, setLocale: [],\n"
            "  openRecentRun: [], enterRunSearch: 0, openLatestCampaign: 0 };\n"
            "const act = {\n"
            "  setTheme: (x) => calls.setTheme.push(x),\n"
            "  showPage: (x) => calls.showPage.push(x),\n"
            "  refresh: () => { calls.refresh++; },\n"
            "  help: () => { calls.help++; },\n"
            "  setLocale: (x) => calls.setLocale.push(x),\n"
            "  openRecentRun: (r) => calls.openRecentRun.push(r),\n"
            "  enterRunSearch: () => { calls.enterRunSearch++; },\n"
            "  openLatestCampaign: () => { calls.openLatestCampaign++; },\n"
            "};\n"
            "const cat = m.commandCatalog('midnight', act);\n"
            "if (cat.length !== 20) throw new Error('命令总数=' + cat.length);\n"
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
            "// act-locale（架构批 W2-S5）：语言档决定提示与切换目标；缺省档参数\n"
            "//（旧两参调用形态）按 zh 处理——向后兼容钉。\n"
            "if (byId['act-locale'].hint !== '切换到 English') throw new Error('zh 档提示漂移');\n"
            "byId['act-locale'].run();\n"
            "if (calls.setLocale[calls.setLocale.length - 1] !== 'en') throw new Error('zh→en 切换目标');\n"
            "const catEn = m.commandCatalog('midnight', act, 'en');\n"
            "const localeEn = catEn.find((it) => it.id === 'act-locale');\n"
            "if (localeEn.hint !== '切换到中文') throw new Error('en 档提示漂移');\n"
            "localeEn.run();\n"
            "if (calls.setLocale[calls.setLocale.length - 1] !== 'zh') throw new Error('en→zh 切换目标');\n"
            "if (catEn.length !== 20) throw new Error('en 档总数漂移');\n"
            "// W5-S17 动作扩充五件：动作面接线与 rank 参数对齐。\n"
            "const acts = cat.filter((c) => c.id.startsWith('act-'));\n"
            "if (acts.length !== 9) throw new Error('动作命令数=' + acts.length);\n"
            "byId['act-run-search'].run();\n"
            "if (calls.enterRunSearch !== 1) throw new Error('act-run-search 未调 enterRunSearch');\n"
            "for (const [id, rank] of [\n"
            "  ['act-run-latest', 1], ['act-run-2nd', 2], ['act-run-3rd', 3],\n"
            "]) {\n"
            "  byId[id].run();\n"
            "  if (calls.openRecentRun[calls.openRecentRun.length - 1] !== rank)\n"
            "    throw new Error(id + ' rank 漂移');\n"
            "}\n"
            "byId['act-latest-campaign'].run();\n"
            "if (calls.openLatestCampaign !== 1) throw new Error('act-latest-campaign 未调');\n"
            "// recentRunAt 现取：hint 携带 run id 且可检索（命令模式按 id 直达）。\n"
            "const ids = { 1: 'run_aaa', 2: 'run_bbb', 3: 'run_ccc' };\n"
            "const catIds = m.commandCatalog('midnight',\n"
            "  { ...act, recentRunAt: (r) => ids[r] || '' });\n"
            "for (const [id, rid] of [\n"
            "  ['act-run-latest', 'run_aaa'], ['act-run-2nd', 'run_bbb'],\n"
            "  ['act-run-3rd', 'run_ccc'],\n"
            "]) {\n"
            "  const it = catIds.find((c) => c.id === id);\n"
            "  if (it.hint !== rid) throw new Error(id + ' hint 未携带 run id');\n"
            "  if (!it.haystack.includes(rid)) throw new Error(id + ' 不可按 id 检索');\n"
            "}\n"
            "// 旧两参 spy 兼容：缺 recentRunAt → hint 回落'直达'，构建零抛。\n"
            "const catBare = m.commandCatalog('midnight', {\n"
            "  setTheme() {}, showPage() {}, refresh() {}, help() {}, setLocale() {},\n"
            "  openRecentRun() {}, enterRunSearch() {}, openLatestCampaign() {},\n"
            "});\n"
            "if (catBare.find((c) => c.id === 'act-run-latest').hint !== '直达')\n"
            "  throw new Error('缺 recentRunAt 时 hint 未回落直达');\n"
            "const icons = [...new Set(cat.map((it) => it.icon).filter(Boolean))];\n"
            "console.log('ok:' + cat.length + ':' + goViews.join(',') + ':' + icons.join(','));\n")
        assert "ok:20:" in out
        parts = out.strip().split(":")
        # go 目标与 index.html nav data-v 全集对齐（showPage 单源对齐钉）
        go_views = set(parts[2].split(","))
        assert go_views <= _nav_data_v(), f"跳转目标不在 nav 注册表: {go_views - _nav_data_v()}"
        # 图标引用 ⊆ sprite symbol 集（防 <use> 悬空）
        icons = set(parts[3].split(","))
        assert icons <= _symbol_ids(), f"命令图标悬空: {icons - _symbol_ids()}"
