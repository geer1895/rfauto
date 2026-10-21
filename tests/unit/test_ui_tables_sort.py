"""架构批 W3-B 席位回归钉：自研管线图表导出 + 可排序表格 + fmtNum（R1 §③/P1-7/P1-10）。

对象：src/rfauto/ui/static/pages.js（本席独占文件面；plotcard.js/app.js 只读）。

三层：
1. **源码钉（免 node）**：
   - 导出工具条小工厂 chartExportTools 单点定义（W3-S12 起四管线已迁
     plotCard props.option 逃生舱=导出随壳内建；工厂现存消费者=dashboard
     甜甜圈 refEl=null append 形态）、按钮类名与 plotCard 同款
     （minor plotcard-btn）、PNG=getDataURL 2x、CSV=toCsv 单源转义；
   - 可排序表格：columnIsNumeric/sortCellKey/sortCellCompare/makeSortable
     导出面 + 三个挂载点（runs-table / cal-table / queue 战役表
     data-sortable 约定）；行引用重排（appendChild，无 innerHTML 重建——
     行内 onclick 随节点走）、aria-sort 单列持值、幂等挂载守卫；
   - fmtNum：数值展示单源 + campaign 表 cost toPrecision(8) 离群点清零
     （cost=4dp 全仓口径，R1 P1-10）。
2. **行为钉（node 在才跑，否则诚实 skip）**：纯函数三件 + fmtNum 数值钉、
   makeSortable DOM 胶水全周期桩测试（升→降→还原三击循环 / aria 同步 /
   行身份保持 / 字符串 numeric collation / 混合列回退 / tbody 重渲染后
   refresh 重放 / 幂等挂载）。

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
# 架构批 UI-R2（2026-10-14）：pages.js 拆分为薄入口 + pages/ 域模块（零构建
# ESM）——源码钉读"入口+全部域模块"并集，行为断言逐字不变（拆分前=单文件）。
def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)

_SRC = _pages_union_text()



def _body(func_sig: str) -> str:
    """取顶层函数体（起于 function 声明行，止于首个列 0 收括号）。"""
    m = re.search(func_sig + r" \{(.*?)\n\}", _SRC, re.S)
    assert m, f"函数体缺失: {func_sig}"
    return m.group(1)


# ────────────────────────── 1. 源码钉 ──────────────────────────

class TestChartExportFactory:
    """R1 §③：4 处直呼 echarts.init 面（W2-B 已收编实例/resize）补 plotCard 级导出。
    W3-S12（R6 审计 P-5）演进：四管线已整体迁 plotCard props.option 逃生舱
    （导出随壳内建），本工厂现存消费者=dashboard 甜甜圈（refEl=null）。"""

    def test_factory_single_definition_shared(self):
        # 工厂单点定义保留（dashboard 甜甜圈/后续自研管线消费）；
        # el 形态挂接清零（W3-S12 四管线入壳）
        assert _SRC.count("function chartExportTools(host, refEl, opts)") == 1
        assert _SRC.count("chartExportTools(el.parentElement, el, {") == 0

    def test_factory_matches_plotcard_ui_and_exports(self):
        body = _body(r"function chartExportTools\(host, refEl, opts\)")
        assert 'className = "minor plotcard-btn"' in body  # 与 plotCard 导出钮同款 UI/类名
        assert 'toCsv(getCsvSeries())' in body  # CSV=toCsv 单源转义
        # UI-R5（2026-10-14）导出统一收编：PNG/SVG 编码与守卫迁 chart_export.js
        # 统一出口（plotCard 工具条与本工厂共用单源）——工厂体路由断言 +
        # 出口体承接原 getDataURL/pixelRatio/守卫/主题底色四钉（语义不变）
        assert 'exportChartFile("png"' in body
        assert 'exportChartFile("svg"' in body  # UI-R5 新增矢量档
        ce = (_STATIC / "chart_export.js").read_text(encoding="utf-8")
        assert "getDataURL(" in ce  # PNG=chart.getDataURL
        assert "pixelRatio: 2" in ce  # 与 plotCard PNG 同参（2x）
        assert "isDisposed()" in ce  # 实例缺失/已弃置静默跳过（plotCard PNG 守卫同口径）
        assert "backgroundColor: themePick(bodyIsLight()" in ce  # 主题底色（theme.js 单源，A5-B/R-4）

    def test_four_pipelines_keep_self_built_with_export(self):
        # 逐处"迁/留"结论落码（W3-S12 演进）：渲染管线仍自研（polar/Smith/
        # custom/heatmap 不在 plotcard builder 能力面），但整体经 plotCard
        # props.option 逃生舱接入壳——导出/同容器复用/主题联动随壳单源；
        # 各处证据=option 函数形态 + exportName 命名（与 W3-B 工厂期同值）
        assert 'option: ({ light })' in _SRC  # 逃生舱函数形态（按档现取）
        assert 'exportName: "farfield-polar-phi" + c.phi_deg' in _SRC  # 远场极坐标
        assert 'exportName: "smith-chart"' in _SRC  # Smith 圆图
        assert 'exportName: "field-slice-" + slice.axis + slice.index' in _SRC  # 场切片热图
        assert 'exportName: "farfield-3d-heatmap"' in _SRC  # 远场 3D 热图
        # 四处均为 plotCard 壳内构（工具条在卡片顶部=plotCard 壳同构：工具条在上）
        assert _SRC.count("T.plotCard(el, {") >= 3  # fieldviz 三处直呼 + Smith 复用赋值形态

    def test_no_new_echarts_init_entries(self):
        # 导出面零新 init：四管线 W3-S12 起走 plotCard 壳（echartsInitCached
        # 仍为 union 唯一直呼 init 入口）
        assert _SRC.count("window.echarts.init(") == 1


class TestSortableTables:
    """R1 P1-7（guide §12.3 核心交互，全站表格零排序）：通用可排序表格。"""

    def test_pure_helpers_exported(self):
        for fn in ("columnIsNumeric", "sortCellKey", "sortCellCompare", "makeSortable"):
            assert f"export function {fn}(" in _SRC, fn

    def test_mount_points_data_sortable_convention(self):
        # 三个挂载点：runs 列表页 + 校准列表 + queue 战役表（R1 P1-7 指名 runs，
        # 另选两个最有价值：ρ 排序的校准表、战役表的阶段进度/决策日志）
        assert _SRC.count("data-sortable") >= 3  # 属性 + 助手 docstring 注记
        assert "<table id='runs-table' data-sortable>" in _SRC
        assert "<table id='cal-table' data-sortable>" in _SRC
        assert "<table data-sortable>" in _SRC  # queue 页 innerHTML 重建表
        assert 'makeSortable(T.$("runs-table"))' in _SRC
        assert 'makeSortable(T.$("cal-table"))' in _SRC
        assert "mountSortableTables(el);" in _SRC  # queue load() 每次渲染后重扫

    def test_sort_by_row_reference_no_innerhtml(self):
        body = _body(r"function makeSortable\(table\)")
        assert "body.appendChild(tr)" in body  # 行引用重排：onclick/监听随节点走
        assert "innerHTML" not in body  # 禁 innerHTML 重建（P1-2 行点击面零破坏）

    def test_click_cycle_and_aria_sort(self):
        body = _body(r"function makeSortable\(table\)")
        assert 'dir === "asc"' in body and 'dir === "desc"' in body  # 升→降→还原循环
        assert 'setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending")' in body
        assert 'removeAttribute("aria-sort")' in body  # 还原/换列清值
        assert "dataset.sortDir" in body  # 点击态持久在 th 上
        assert "table.dataset.sortableBound" in body  # 幂等挂载守卫

    def test_natural_order_baseline_snapshot(self):
        # 自然序基线快照 + tbody 重渲染自动重取（行节点已不在 tbody）+ refresh 重放
        body = _body(r"function makeSortable\(table\)")
        assert "base.some((tr) => tr.parentNode !== body)" in body
        assert "natural().slice()" in body  # 排序在副本上做，基线保持自然序
        assert "refresh()" in body
        assert "mountSortableTables(root)" in _SRC


class TestFmtNum:
    """R1 P1-10（数字精度口径混乱）：fmtNum 单源 + campaign cost 离群点清零。"""

    def test_fmtnum_single_source(self):
        assert "export function fmtNum(v, d = 4)" in _SRC
        assert "fmtNum(row.cost, 4)" in _SRC  # campaign 表 cost 回归 4dp 全仓口径

    def test_cost_precision_outlier_gone(self):
        # toPrecision(8) 是 R1 点名的唯一反直觉离群点（8 位有效数字）
        assert "toPrecision(8)" not in _SRC
        # 其余既有一致口径未被本席扩大化替换（canvas 坐标标签等仍用 toPrecision(4)）
        assert _SRC.count("toPrecision(4)") >= 6


# ────────────────────────── 2. 行为钉（node 在才跑） ──────────────────────────

_NODE_GLUE = r"""
const p = await import('./pages.js');
const A = (cond, msg) => { if (!cond) throw new Error("assert: " + msg); };

// ── 纯函数三件 + fmtNum ──
A(p.columnIsNumeric(["1", "2", "3"]) === true, "columnIsNumeric basic");
A(p.columnIsNumeric(["1", "-", "3"]) === false, "dash breaks numeric");
A(p.columnIsNumeric(["", ""]) === false, "all-empty not numeric");
A(p.columnIsNumeric([]) === false, "empty col not numeric");
A(p.columnIsNumeric(["1.5", "-3e2", " 7 "]) === true, "float/exp/trim");
A(p.columnIsNumeric(["3/5", "2/5"]) === false, "composite col string fallback");
A(p.sortCellKey(" - ", true) === -Infinity, "missing numeric key = -Inf");
A(p.sortCellKey(" 3.50 ", true) === 3.5, "numeric key trims");
A(p.sortCellKey(null, false) === "", "null string key = empty");
A(p.sortCellCompare(1, 2, true) < 0, "numeric asc compare");
A(p.sortCellCompare("a2", "a10", false) < 0, "numeric collation a2<a10");
A(p.fmtNum(null, 4) === "-" && p.fmtNum(undefined, 2) === "-" && p.fmtNum(NaN, 4) === "-",
  "fmtNum missing -> dash");
A(p.fmtNum(1.23456, 4) === "1.2346", "fmtNum rounds");
A(p.fmtNum(0, 4) === "0.0000", "fmtNum zero is a value not missing");

// ── DOM 胶水（最小桩：tbody.rows 语义=当前行序，appendChild=摘除再追加）──
function mkTable(head, rows) {
  const ths = head.map(() => ({
    dataset: {}, style: {}, _aria: undefined, _click: null,
    setAttribute(n, v) { if (n === "aria-sort") this._aria = v; },
    removeAttribute(n) { if (n === "aria-sort") this._aria = undefined; },
    addEventListener(_t, f) { this._click = f; },
  }));
  const bodyRows = rows.map((cells) => ({
    cells: cells.map((t) => ({ textContent: t })), parentNode: null, _id: null,
  }));
  const body = {
    rows: bodyRows,
    appendChild(tr) {
      const i = this.rows.indexOf(tr);
      if (i >= 0) this.rows.splice(i, 1);
      this.rows.push(tr);
      tr.parentNode = body;
    },
  };
  for (const r of bodyRows) r.parentNode = body;
  const table = { tHead: { rows: [{ cells: ths }] }, tBodies: [body], dataset: {} };
  return { table, ths, body };
}

A(p.makeSortable({}) === null, "no thead -> null");

// 场景 1：数值列三击循环 + 行身份保持（含 "-" 的混合列走字符串回退，见纯函数钉）
let s = mkTable(["run_id", "S11"], [["r_a", "-3.5"], ["r_b", "-20.1"], ["r_c", "-0.5"], ["r_d", "-1.0"]]);
s.body.rows.forEach((r, i) => { r._id = i; });
const api = p.makeSortable(s.table);
A(api && typeof api.refresh === "function", "api returned");
A(s.table.dataset.sortableBound === "1", "bound mark set");
const th = s.ths[1];
th._click();
A(th._aria === "ascending", "aria ascending");
A(s.body.rows.map((r) => r._id).join(",") === "1,0,3,2", "asc: -20.1,-3.5,-1.0,-0.5");
th._click();
A(th._aria === "descending", "aria descending");
A(s.body.rows.map((r) => r._id).join(",") === "2,3,0,1", "desc order");
th._click();
A(th._aria === undefined && th.dataset.sortDir === undefined, "restore clears state");
A(s.body.rows.map((r) => r._id).join(",") === "0,1,2,3", "restore replays natural order");
A(new Set(s.body.rows.map((r) => r._id)).size === 4, "row identity preserved (onclick 走节点)");

// 场景 2：字符串列 numeric collation（run_id 嵌数字按数值比）
s = mkTable(["name"], [["run_a10"], ["run_a2"], ["run_a1"]]);
p.makeSortable(s.table);
s.ths[0]._click();
A(s.body.rows.map((r) => r.cells[0].textContent).join(",") === "run_a1,run_a2,run_a10",
  "collation order");

// 场景 3：混合列（"3/5" 复合进度）回退字典序
s = mkTable(["进度"], [["3/5"], ["10/5"], ["2/5"]]);
p.makeSortable(s.table);
s.ths[0]._click();
A(s.body.rows.map((r) => r.cells[0].textContent).join(",") === "2/5,3/5,10/5",
  "string fallback order (numeric collation: 2<3<10)");

// 场景 4：aria-sort 单列持值（换列清旧列）
s = mkTable(["a", "b"], [["1", "z"], ["2", "y"]]);
p.makeSortable(s.table);
s.ths[0]._click();
s.ths[1]._click();
A(s.ths[0]._aria === undefined && s.ths[1]._aria === "ascending", "single aria holder");

// 场景 5：tbody 重渲染（筛选换血）后 refresh 重放当前排序
s = mkTable(["v"], [["3"], ["1"], ["2"]]);
const api5 = p.makeSortable(s.table);
s.ths[0]._click();
A(s.body.rows.map((r) => r.cells[0].textContent).join(",") === "1,2,3", "pre-refresh sorted");
for (const r of s.body.rows.splice(0)) r.parentNode = null; // 旧行摘除
[["9"], ["5"], ["7"]].forEach((cs) => {
  const r = { cells: cs.map((t) => ({ textContent: t })), parentNode: s.body };
  s.body.rows.push(r);
});
api5.refresh();
A(s.body.rows.map((r) => r.cells[0].textContent).join(",") === "5,7,9",
  "refresh replays sort on fresh rows");

// 场景 6：幂等挂载
s = mkTable(["x"], [["1"]]);
const a1 = p.makeSortable(s.table);
const a2 = p.makeSortable(s.table);
A(a1 === a2, "idempotent mount returns same api");

console.log("ok:sort-glue");
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestNodeBehavioral:
    def test_sort_glue_end_to_end(self):
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e", _NODE_GLUE],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC))
        assert r.returncode == 0, r.stderr[-2000:]
        assert "ok:sort-glue" in r.stdout

    def test_node_check_pages_js(self):
        r = subprocess.run([_NODE, "--check", str(_STATIC / "pages.js")],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]
