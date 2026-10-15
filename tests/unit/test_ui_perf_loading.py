"""W4-D（aurora36）首屏加载性能钉：vendor 预取 + palette 导出图表事件桥。

钉三件事：
1. index.html head 预取基座（R1 审计 P1-12 方案 Y 保底）：three 用
   <link rel="modulepreload">（importmap 消费的 ES module 提前入模块缓存，
   首屏 1.27MB 前移到 head 解析即取）、echarts 用 <link rel="preload"
   as="script">（body 尾经典 script 提前首字节，执行位置/顺序不变）。
   方案 X（three 改动态 import）被否：pages.js drawIsoMesh 同步消费
   app.js 注入的 T.THREE（pages.js:2831 `const THREE = T.THREE;`），动态化
   需要 pages.js 调用侧 await/守卫配合，而 pages.js 归并行席禁改——详见
   W4-D 席位报告。
2. 预取 href 与消费点单源一致：modulepreload href == importmap 里 three
   的目标；preload href == body 尾 echarts <script src>——防预取 URL 漂移
   落空成第二份下载。
3. palette act-export-chart（W4-D）：命令总数 14（同步钉
   test_ui_palette_cmds）；发射端 fireExportChart——window 缺席环境（node）
   静默守卫不抛；window 在场时派发 CustomEvent，事件名恒
   "rfauto:export-chart"、无 payload（CustomEvent 规范缺省 detail=null，
   与 pages.js 侧监听端契约对齐）。

零内联脚本增量自证：index.html 内联 <script> 仍只有主题防闪 boot +
importmap 两个——server.py:CSP_VALUE 哈希钉无需同步（test_w1e_ui_csp）。

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

_HEAD = re.search(r"<head>(.*?)</head>", _INDEX, re.S).group(1)


# ────────────────────────── 1. vendor 预取（源码钉） ──────────────────────────

class TestVendorPreload:
    def test_modulepreload_three_in_head(self):
        m = re.search(r'<link\s+rel="modulepreload"\s+href="([^"]+)"', _HEAD)
        assert m, "head 缺 three modulepreload（R1 P1-12 方案 Y 预取基座）"
        href = m.group(1)
        im = re.search(r'"three"\s*:\s*"([^"]+)"', _INDEX)
        assert im, "importmap 缺 three 映射"
        assert href == im.group(1), (
            f"modulepreload href {href!r} 与 importmap three 目标 "
            f"{im.group(1)!r} 不一致——预取落空成第二份下载")

    def test_preload_echarts_in_head_matches_body_script(self):
        m = re.search(r'<link\s+rel="preload"\s+as="script"\s+href="([^"]+)"', _HEAD)
        assert m, "head 缺 echarts preload as=script"
        body_src = re.findall(r'<script src="([^"]*echarts[^"]*)"></script>', _INDEX)
        assert body_src == [m.group(1)], (
            f"preload href {m.group(1)!r} 与 body 尾 echarts script src "
            f"{body_src!r} 不一致")

    def test_inline_script_count_unchanged_csp_untouched(self):
        # 内联脚本仍 = 主题防闪 boot + importmap（外部 importmap 浏览器不支持）。
        # 新增内联必须同步 server.py:CSP_VALUE 哈希钉（test_w1e_ui_csp 抓）。
        inline = re.findall(
            r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", _INDEX, re.S)
        assert len(inline) == 2, (
            f"index.html 内联脚本数变为 {len(inline)}——若为新增内联，"
            "必须同步 server.py:CSP_VALUE 哈希钉")


# ────────────────────────── 2. act-export-chart（node 行为钉） ──────────────────────────

def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2000:]}"
    return r.stdout


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestExportChartCommand:
    def test_palette_source_pins(self):
        # 发射端在档且守卫先行；生产装配把 exportChart 出口接到发射端
        assert "export function fireExportChart" in _PALETTE, "缺事件桥发射端"
        assert 'typeof window === "undefined"' in _PALETTE, "window 缺席守卫缺失"
        assert "exportChart: fireExportChart" in _PALETTE, "生产动作面未接发射端"

    def test_catalog_contract_event_bridge_and_window_guard(self):
        out = _run_node_js(
            "const m = await import('./palette.js');\n"
            "const calls = { exportChart: 0 };\n"
            "const act = {\n"
            "  setTheme() {}, showPage() {}, refresh() {}, help() {},\n"
            "  exportChart() { calls.exportChart++; },\n"
            "};\n"
            "const cat = m.commandCatalog('midnight', act);\n"
            "if (cat.length !== 14) throw new Error('命令总数=' + cat.length);\n"
            "const cjk = /[\\u4e00-\\u9fff]/;\n"
            "for (const it of cat) {\n"
            "  if (it.mode !== 'cmd') throw new Error('mode: ' + it.id);\n"
            "  if (it.subtitle !== '命令') throw new Error('subtitle: ' + it.id);\n"
            "  if (!cjk.test(it.title)) throw new Error('中文标题: ' + it.title);\n"
            "}\n"
            "const it = cat.find((c) => c.id === 'act-export-chart');\n"
            "if (!it) throw new Error('缺 act-export-chart');\n"
            "if (it.title !== '导出当前页图表') throw new Error('标题: ' + it.title);\n"
            "if (it.hint !== '动作') throw new Error('hint: ' + it.hint);\n"
            "if (!/导出/.test(it.haystack) || !/图表/.test(it.haystack))\n"
            "  throw new Error('关键词: ' + it.haystack);\n"
            "const acts = cat.filter((c) => c.id.startsWith('act-'));\n"
            "if (acts.length !== 3) throw new Error('动作命令数=' + acts.length);\n"
            "it.run();\n"
            "if (calls.exportChart !== 1) throw new Error('未调 act.exportChart');\n"
            # ① window 缺席（node 原生）：发射端守卫静默不抛
            "if (typeof window !== 'undefined')\n"
            "  throw new Error('测试前置失败：node 不应有 window');\n"
            "m.fireExportChart();\n"
            # ② window 在场（桩）：派发 CustomEvent，事件名恒此、无 payload
            "globalThis.CustomEvent = class CustomEvent {\n"
            "  constructor(type, params) { this.type = type;\n"
            "    this.detail = params ? params.detail : null; }\n"
            "};\n"
            "const got = [];\n"
            "globalThis.window = { dispatchEvent: (e) => got.push(e) };\n"
            "m.fireExportChart();\n"
            "if (got.length !== 1) throw new Error('未派发事件');\n"
            "if (got[0].type !== 'rfauto:export-chart')\n"
            "  throw new Error('事件名漂移: ' + got[0].type);\n"
            "if (got[0].detail !== null) throw new Error('应无 payload');\n"
            "console.log('ok:export-chart:' + cat.length);\n")
        assert "ok:export-chart:14" in out
