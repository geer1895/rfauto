"""explore 方差带渲染钉（B3 批：GP ±1σ 区间面积带）。

后端 `/api/playground/explore` 早已透出 mean±std（smt 族原生逐点 σ）——
缺的只是前端面积带渲染。本文件钉静态 JS 的三处增量（文本 marker 钉，
test_ui_data_anchor_uq_pages 先例）+ JS 语法自检（node --check，node 在
才跑，否则诚实 skip）：
- app.js drawEChart 支持 ``type:"band"`` 系列条目（stack 双线夹 areaStyle）；
- pages.js 探索器（DP-16 U3 runExplore）用 band 替代旧 ±1σ 两条虚线；
- 帮助文案改"±1σ 方差带"；旧虚线系列名（+1σ/−1σ 独立曲线）不再出现。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_UI = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"


def _read(name: str) -> str:
    return (_UI / name).read_text(encoding="utf-8")


class TestBandSeriesInDrawEChart:
    """图表 option 构造：band 类型条目 → stack 基线+面积带双 series。

    PR-3 PlotCard 组件化（2026-10-02 批）把 drawEChart 的 option 构造迁到
    plotcard.js buildEChartOption（app.js drawEChart 与 plotCard 共用单源
    builder）——本钉随之指向 plotcard.js（断言强度不变）。"""

    def test_band_type_branch_exists(self):
        src = _read("plotcard.js")
        assert 's.type === "band"' in src, "buildEChartOption 缺 band 类型分支"
        assert "stack:" in src, "band 未用 stack 夹 areaStyle"
        assert "areaStyle" in src
        # 既有 scatter 分支不受影响（回归守卫）
        assert 's.type === "scatter"' in src

    def test_band_branch_keeps_existing_line_path(self):
        src = _read("plotcard.js")
        # 普通线系列仍走原 data: s.y 路径（其他 drawEChart 消费面不变）
        assert "name: s.name, type: \"line\", data: s.y, showSymbol: false" \
            in src


class TestExploreUsesBand:
    """pages.js：runExplore 的 ±1σ 面积带 + 帮助文案。"""

    def test_runexplorer_pushes_band(self):
        src = _read("pages.js")
        assert 'type: "band"' in src, "runExplore 未改用 band 系列条目"
        assert "lower: cur.mean.map((m, i) => m - cur.std[i])" in src
        assert "upper: cur.mean.map((m, i) => m + cur.std[i])" in src

    def test_old_two_sigma_lines_gone(self):
        src = _read("pages.js")
        # 旧两条独立虚线系列名不再出现（band 内 lower/upper 引用除外）
        assert 'name: "+1σ"' not in src
        assert 'name: "−1σ"' not in src

    def test_help_text_mentions_variance_band(self):
        src = _read("pages.js")
        assert "±1σ 方差带" in src


class TestJsSyntax:
    """node --check 语法自检（node 在才跑；离线纯语法零执行）。"""

    @pytest.mark.parametrize("name", ["app.js", "pages.js", "plotcard.js"])
    def test_node_check(self, name):
        node = shutil.which("node")
        if not node:
            pytest.skip("node 不在 PATH——语法钉不可用（诚实 skip）")
        rc = subprocess.run([node, "--check", str(_UI / name)],
                            capture_output=True, text=True)
        assert rc.returncode == 0, rc.stderr
