"""W5-S17（aurora_f，R1 §面3 两 watch 激活+palette 动作扩充）UI 钉面。

钉三件事：
1. runs 表行数自适应降级（虚拟滚动 watch 激活——R1 盘点「现状够用挂阈值
   watch」的本意=拿数据定案后落守卫）：view_runs.js VROWS_THRESHOLD=200
   单源 + 渲染路径 classList.toggle 消费 + index.html `#runs-table.vrows
   tbody tr` content-visibility:auto/contain-intrinsic-size 规则在档
   （零新依赖的轻量虚拟化；≤阈值旧形态逐字节不变）；
2. 跨图联动（联动 watch 激活）：plotCard props.connectGroup 透传——
   plotcard.js applyConnectGroup（首绘/复用换代两路径共用单源，window 缺席
   零抛跳过）+ view_sparams 两调用点同挂 connectGroup="sparams"
   （echarts 原生 connect，零新依赖）；node 行为钉=假 chart+假 window
   真执行挂接与守卫两态；
3. palette 动作扩充生产装配源码钉：commandItems 动作面五出口接线
   （recentRunAt/openRecentRun/enterRunSearch/openLatestCampaign）+
   _enterRunSearch 面板闭包进入器装配 + openCampaign import（命令目录纯
   函数行为钉在 test_ui_palette_cmds，此处只钉生产装配面不漂移）。

命令总数 20 的同步钉在 test_ui_palette_cmds.py / test_ui_perf_loading.py
（本文件不重复钉，改命令总数只改彼两处）。

不依赖 runs/、不读网络、不启动服务器；静态文件只读。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

_RUNS = (_STATIC / "pages" / "view_runs.js").read_text(encoding="utf-8")
_INDEX = (_STATIC / "index.html").read_text(encoding="utf-8")
_PLOTCARD = (_STATIC / "plotcard.js").read_text(encoding="utf-8")
_SPARAMS = (_STATIC / "pages" / "view_sparams.js").read_text(encoding="utf-8")
_PALETTE = (_STATIC / "palette.js").read_text(encoding="utf-8")


def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2000:]}"
    return r.stdout


# ────────────────────────── 1. runs 表 vrows（源码钉） ──────────────────────────

class TestRunsVrowsAdaptive:
    def test_threshold_single_source_and_toggle(self):
        m = re.search(r"const VROWS_THRESHOLD = (\d+);", _RUNS)
        assert m, "view_runs.js 缺 VROWS_THRESHOLD 单源"
        assert m.group(1) == "200", "阈值漂移（R1 建议档 200；改动须同笔改本钉+CSS 注释）"
        # 渲染路径按筛选后行数消费（>阈值挂类，≤阈值全量渲染旧行为）
        assert 'tb.classList.toggle("vrows", rows.length > VROWS_THRESHOLD);' in _RUNS

    def test_css_content_visibility_rule(self):
        m = re.search(r"#runs-table\.vrows tbody tr \{(.*?)\}", _INDEX, re.S)
        assert m, "index.html 缺 #runs-table.vrows CSS 规则"
        body = m.group(1)
        assert "content-visibility: auto" in body
        assert "contain-intrinsic-size: auto" in body
        # 行数阈值口径与 view_runs.js 单源一致（注释防漂移声明）
        assert "VROWS_THRESHOLD" in _INDEX


# ────────────────────────── 2. 跨图联动 connectGroup（源码钉+node 行为钉） ──────────────────────────

class TestConnectGroupLinkage:
    def test_plotcard_apply_group_wiring(self):
        # 单源函数在档且导出（node 行为钉消费）
        assert "export function applyConnectGroup(chart, group)" in _PLOTCARD
        # 首绘路径挂接（props.connectGroup 非空才动——旧行为逐字节不变）
        assert "if (props.connectGroup) applyConnectGroup(chart, props.connectGroup);" in _PLOTCARD
        # 复用换代路径：换组才重挂（同组幂等语义）
        assert "props.connectGroup !== prevGroup" in _PLOTCARD
        # window/echarts 缺席守卫（node 假环境零抛）
        assert 'typeof window === "undefined"' in _PLOTCARD
        assert "option?, connectGroup?}" in _PLOTCARD  # 壳 docstring 契约在档

    def test_sparams_both_call_sites_grouped(self):
        # sparams 页两张卡（多文件分组卡 + 叠加对比卡）同入一组——跨卡
        # 十字线/dataZoom 同步（对照工作流）；smith 模式单卡自研管线不在壳内。
        assert _SPARAMS.count('connectGroup: "sparams"') == 3, \
            _SPARAMS.count('connectGroup: "sparams"')

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_apply_connect_group_behavior(self):
        out = _run_node_js(
            "const m = await import('./plotcard.js');\n"
            "// ① window 缺席（node 原生）：零抛返回 false，chart.group 不写\n"
            "const chart = { group: null };\n"
            "if (m.applyConnectGroup(chart, 'g1') !== false)\n"
            "  throw new Error('window 缺席应返回 false');\n"
            "if (chart.group !== null) throw new Error('缺席环境误写 group');\n"
            "// ② 假 window+echarts：挂接两态真执行\n"
            "const connected = [];\n"
            "globalThis.window = { echarts: { connect: (g) => connected.push(g) } };\n"
            "const c2 = { group: null };\n"
            "if (m.applyConnectGroup(c2, 'sparams') !== true)\n"
            "  throw new Error('挂接应返回 true');\n"
            "if (c2.group !== 'sparams') throw new Error('group 未写');\n"
            "if (connected.join(',') !== 'sparams') throw new Error('connect 未调');\n"
            "// ③ 重复 connect 幂等（echarts 侧 fm[group]=true 语义）+ 空参守卫\n"
            "m.applyConnectGroup(c2, 'sparams');\n"
            "if (connected.length !== 2) throw new Error('重复挂接应仍逐次透传');\n"
            "if (m.applyConnectGroup(null, 'g') !== false) throw new Error('空 chart 守卫');\n"
            "if (m.applyConnectGroup(c2, '') !== false) throw new Error('空组守卫');\n"
            "if (c2.group !== 'sparams') throw new Error('空参守卫误清 group');\n"
            "console.log('ok:connect-group');\n")
        assert "ok:connect-group" in out


# ────────────────────────── 3. palette 动作扩充生产装配（源码钉） ──────────────────────────

class TestPaletteActionWiring:
    def test_command_items_act_factories(self):
        # 动作面五出口接线（目录纯函数行为钉在 test_ui_palette_cmds）
        for needle in (
            "recentRunAt: (rank) => {",
            "openRecentRun: (rank) => {",
            "enterRunSearch: () => { if (_enterRunSearch) _enterRunSearch(); },",
            "openLatestCampaign,",
        ):
            assert needle in _PALETTE, f"commandItems 动作面缺接线: {needle}"

    def test_run_search_opener_and_campaign_exit(self):
        # `#` 检索进入器：面板闭包单源装配（open 复位后切前缀重过滤）
        assert "_enterRunSearch = () => {" in _PALETTE
        assert 'input.value = "#";' in _PALETTE
        # 最近战役直达：pareto_runs 首项 → openCampaign 深链；空/失败回落裸页
        assert 'apiFetch("/api/pareto_runs")' in _PALETTE
        assert "openCampaign(r.run_id);" in _PALETTE
        assert "else showPage(\"campaign\");" in _PALETTE
        # openCampaign 单源 import（pages.js re-export 面）
        assert re.search(
            r'import \{[^}]*\bopenCampaign\b[^}]*\} from "\./pages\.js";', _PALETTE)

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_module_imports_clean_with_new_exports(self):
        # 新增导出/工厂落位后 import 链零破坏（node 无 DOM 环境真执行）
        out = _run_node_js(
            "const m = await import('./palette.js');\n"
            "if (typeof m.commandCatalog !== 'function') throw new Error('目录缺');\n"
            "if (typeof m.fireExportChart !== 'function') throw new Error('桥缺');\n"
            "console.log('ok:import-clean');\n")
        assert "ok:import-clean" in out
