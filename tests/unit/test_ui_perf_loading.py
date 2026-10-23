"""W4-D（aurora36）首屏加载性能钉：vendor 预取 + palette 导出图表事件桥。

钉三件事：
1. index.html head 预取基座（R1 审计 P1-12 方案 Y → aurora_f W3-S9 P8-2
   重审改钉）：echarts 用 <link rel="preload" as="script">（body 尾经典
   script 提前首字节，执行位置/顺序不变）；**three 的 modulepreload 已删除**
   ——three 改 3D 调用点动态 import（app.js drawBoxes / view_fieldviz
   drawIsoMesh，aurora_f W3-S9；旧否决理由=monolith 时代 pages.js 同步消费
   T.THREE，现状消费面在动态 import 链内已失效），保留预取会让每个首屏都
   强制下完 1.27MB（gzip 256,743B=首屏线传 36% 单件），与懒加载目的相抵。
   改钉方向=modulepreload 缺席为常态（回流钉），importmap three 映射保留
   （动态 import 的解析单源）。
2. echarts 预取 href 与消费点单源一致：preload href == body 尾 echarts
   <script src>——防预取 URL 漂移落空成第二份下载。
3. palette act-export-chart（W4-D）：命令总数 20（同步钉；aurora_f W2-S5 act-locale 语言命令落地同笔 14→15；aurora_f W5-S17 动作扩充同笔
   15→20，动作 4→9，详见 test_ui_palette_cmds）
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
    def test_three_importmap_mapping_present_no_modulepreload(self):
        # P8-2（aurora_f W3-S9 重审改钉）：three 动态 import 的解析单源=
        # importmap 映射必须保留；modulepreload 必须**缺席**——回流即等于
        # 每个首屏强制下完 three（1.27MB/gzip 256,743B），抵消懒加载收益。
        im = re.search(r'"three"\s*:\s*"([^"]+)"', _INDEX)
        assert im, "importmap 缺 three 映射（动态 import 解析单源）"
        pre = re.findall(r'<link\s+rel="modulepreload"\s+href="([^"]+)"', _HEAD)
        assert pre == [], (
            f"head 出现 modulepreload {pre}——three 已改 3D 调用点动态 import"
            "（W3-S9 P8-2），预取回流=首屏强制下完 three，抵消懒加载")

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
            "if (cat.length !== 20) throw new Error('命令总数=' + cat.length);\n"
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
            "if (acts.length !== 9) throw new Error('动作命令数=' + acts.length);\n"
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
        assert "ok:export-chart:20" in out
