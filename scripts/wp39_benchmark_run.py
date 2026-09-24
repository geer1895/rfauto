r"""WP3.9 MVP 基准运行器（§10.0）：3 问题 × 2 引擎 × 真跑预算 25。

问题（同 §10.0 口径：单一确定性指标 cost，两引擎回代同一评估器）：
- mline  阻抗匹配：微带线宽 w→|S11|@2.5GHz 越深越好（50Ω 匹配）；
- patch  谐振调频：贴片 L/W→|S11|@2.0GHz（谐振对准 2.0GHz）；
- ratrace 隔离度：环半径 R→|S31|@2.5GHz（Σ→Δ 隔离，环中心对准 f0）。

引擎：
- pattern_search = HFSS Optimetrics 口径基线（达标线）：Hooke-Jeeves
  Pattern Search 的**等价 scripted loop**（预声明允许口径）——PyAEDT
  驱动设计变量更新 + analyze + 导出，与 Optimetrics 同一求解语义；
  不用 GUI 原生 Optimetrics setup 的原因：其 Pattern Search 无法硬帽
  评估次数（预算 25 固定不得超无法保证），MVP 以等价环保预算精确；
  kernel 见 service/wp39_benchmark.pattern_search_loop。
- sbo = rfauto 代理环（``rfauto tune --sampler sbo`` 同内核
  run_surrogate_loop：LHS 初始采样→smt_kriging GP→2000 虚拟寻优→
  top-K 真跑→refit，real_cost_trace 出收敛曲线）。

公平口径（两引擎完全一致）：
- 同一 HFSS 设计几何（设计变量参数化，逐点 set variable→重解，无
  重渲染）+ 同一 setup（单频、MaxDeltaS 0.02、MaximumPasses 12）+
  同一 cost 评估器（SpecEvaluator 闭式，两引擎构造同一 objectives）；
- 每次真跑尝试（成功+失败）计 1 预算，硬帽 25；
- wall-clock 计"优化墙钟"= 首评估开始→末评估结束（含环内算法开销），
  不含 desktop 启动与一次性建模（两引擎同口径，launch/build 另记）；
- 战役严格串行（机器独占，计时公平）；desktop/建模级故障允许整轮
  重启 ≤3 次，仅当该轮零成功评估（重启轮不提供判据数字）。

运行（长任务分离+日志轮询，#157）：
  powershell Start-Process -FilePath .venv\Scripts\python.exe `
    -ArgumentList "scripts/wp39_benchmark_run.py -problem mline -engine pattern_search" `
    -RedirectStandardOutput runs/wp39_mvp/mline__pattern_search.log `
    -RedirectStandardError runs/wp39_mvp/mline__pattern_search.err.log -Wait
判定汇总：.venv\Scripts\python.exe scripts/wp39_benchmark_run.py -judge
离线自检（零真机，dry-run 走解析面）：
  .venv\Scripts\python.exe scripts/wp39_benchmark_run.py -problem mline `
    -engine sbo -dry-run -outdir runs/wp39_mvp_dry

产出：runs/wp39_mvp/{problem}__{engine}.json + summary.json。
几何纪律：字面量一律显式 mm（#218）；设计变量表达式随变量量纲
（#218 三类语义③），不出现纯数字串/纯字面算术。

换判据变体（wp39-factory-verdict-next；产出走新目录
runs/wp39_factory_verdict_next/，不覆盖既有归档 #122）：
- mline_eps     |εeff−target|（S21 相位斜率抽取，sweep 2.4–2.6 Discrete 41 点，
                ④ 名义点先标定 target；非 dB 越小越好）——mline 基线臂与
                openEMS 工厂回代同 setup 同抽取；
- ratrace_null  deep_null_neighborhood_db（2.3–2.7GHz、hw 25MHz，sweep
                Interpolating 81 点）——两臂同 sweep 重跑。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, "src")

from rfauto.service.wp39_benchmark import (
    deep_null_neighborhood_db,
    eps_eff_error_metric,
    eps_eff_from_s21_phase,
)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUTDIR = REPO / "runs" / "wp39_mvp"
HFSS_VERSION = "2025.1"
MAX_ATTEMPTS = 3
BUDGET_DEFAULT = 25
SEED_DEFAULT = 42

# cost 收敛容差（dB；surrogate 环 stagnation 判定用）
SBO_TOL_ABS_DB = 0.25
SBO_TOL_ROUNDS = 2
SBO_TOP_K = 2
SBO_VIRTUAL_TRIALS = 2000
# εeff 指标的 stagnation 容差（无量纲）：0.25dB 语义不可直接套到
# |εeff−target|（量级 1e-3~1e-1，套用即首轮判停）——取 εeff 的 0.1%
# （≈HJ 闭式对真机系统偏移 1~2% 的一个量级以下），wp39-factory-verdict-next
SBO_TOL_ABS_EPS = 0.003

SCHEMA = "wp39_mvp_campaign_v1"

# ── 换判据常量（wp39-factory-verdict-next）────────────────────────
# mline_eps：HFSS 波端口面=线两端（y=±MLINE_Y_HALF），S21 相位斜率抽取 εeff
# 的线长精确 = 2·MLINE_Y_HALF；sweep 2.4–2.6GHz（±4%，与 β 抽取窗同口径）
MLINE_Y_HALF = 40.0
MLINE_LINE_LEN_M = 2.0 * MLINE_Y_HALF * 1e-3
MLINE_EPS_SWEEP = {"band_ghz": (2.4, 2.6), "points": 41,
                   "type": "Discrete", "name": "Sweep"}
# ratrace_null：深零点邻域指标常量与 runs/wp39_mvp_followup/ratrace_null.json
# 同源（search 2.3–2.7GHz、hw 25MHz）保证可比；sweep 走 Interpolating
# （81 点 5MHz 栅格；Discrete 81 点 4 端口每评估 +数分钟，两臂 ×25 超墙钟预算）
RATRACE_NULL_SEARCH_GHZ = (2.3, 2.7)
RATRACE_NULL_HW_GHZ = 0.025
RATRACE_NULL_SWEEP = {"band_ghz": RATRACE_NULL_SEARCH_GHZ, "points": 81,
                      "type": "Interpolating", "name": "Sweep"}
#: ④ 纪律：εeff 目标由本引擎名义点标定后写入（run_campaign 标定步 /
#: followup replay 档从基线 JSON 回填）；None=未标定，评估即报错不猜
EPS_TARGET: dict[str, float | None] = {"mline_eps": None}

CANDIDATE_IMPL_DESC = (
    "rfauto 代理环：run_surrogate_loop（`rfauto tune --sampler sbo` 同内核）"
    "smt_kriging GP + 2000 虚拟寻优 top-K 真跑")
BASELINE_IMPL_DESC = (
    "HFSS Optimetrics 口径基线（达标线）：Hooke-Jeeves Pattern Search 等价 "
    "scripted loop（PyAEDT set variable→analyze→导出，同一 setup/cost；"
    "GUI 原生 setup 无法硬帽评估数，预算 25 用等价环精确执行）")


# ── 问题定义 ─────────────────────────────────────────────────────────────────


@dataclass
class ProblemDef:
    """单问题：参数面 + HFSS 构建器 + 指标提取 + 离线解析面。"""

    name: str
    metric_name: str
    metric_desc: str
    bounds: dict[str, tuple[float, float]]
    nominal: dict[str, float]
    var_map: dict[str, str]           # 参数名 → HFSS 设计变量名
    design_name: str
    f0_ghz: float
    n_ports: int                      # 端口数（touchstone 归一化用）
    n_init: int                       # sbo 初始 LHS 点数（维度相关）
    build: Callable[[Any], None]      # h(pyaedt Hfss) → 几何+端口+setup
    metric_from_network: Callable[[Any], float]
    dry_metrics: Callable[[dict[str, float]], dict[str, float]]
    ports_desc: str
    extra: dict[str, Any] = field(default_factory=dict)
    #: 战役 JSON metric_semantics 后缀（非 dB 指标必须如实改写）
    metric_semantics_note: str = "（dB 越负越好）"
    #: sweep 变体（wp39-factory-verdict-next）：None=单频 setup（原口径）；
    #: dict(band_ghz, points, type, name) → _make_setup 追加线性计数 sweep，
    #: evaluate 导出前走 HfssAdapter.assert_sweep_completed
    sweep: dict[str, Any] | None = None
    #: ④ 标定：True → 战役前在名义点解一次、eps_extract(net) 写 EPS_TARGET
    calibrate: bool = False
    eps_extract: Callable[[Any], float] | None = None
    #: Pattern Search 起点（None=nominal）。εeff 变体 target 在名义点标定，
    #: 起点取名义点即"起点=最优"（metric≡0，cost 劣化不可判）且对无起点
    #: 先验的 sbo 臂不公平——起点改域中心，标定点仍为名义点
    x0: dict[str, float] | None = None


# ── 通用构建件 ───────────────────────────────────────────────────────────────


def _mm(v: float) -> str:
    """预计算浮点 + 显式 mm（#218：禁纯数字串/纯字面算术）。"""
    return f"{v!r}mm"


def _vexpr(term: str, *offsets: float) -> str:
    """设计变量表达式：('0.5*R', +0.48, -0.27) → '0.5*R+0.48mm-0.27mm'。

    含设计变量表达式随变量量纲（#218 三类语义③）；字面量一律带 mm。
    """
    out = term
    for off in offsets:
        if off != 0.0:
            out += f"{off:+.9g}mm"
    return out


def _sub_expr(literal_mm: float, term: str) -> str:
    """字面量(mm) − 设计变量表达式：('60.0', 'Rr') → '60.0mm-Rr'。

    变量 term 经 h[var]=...mm 定义带 mm 量纲（#218 三类语义③），字面量
    显式带 mm；geometry 实参经本 helper 构造，避免内联 f-string 字面算术。
    """
    return f"{literal_mm!r}mm-{term}"


def _kill_desktops() -> None:
    """ansysedt 清场（治理单源）：孤儿点杀+活桌面 fail-closed（#245/#265）。

    委托 src/rfauto/infra/desktop_guard.py；旧实现 Get-Process|
    Stop-Process -Force 无条件代杀已废弃（误杀他轨合法桌面，#265）。
    wp39_followup_run 经 runner._kill_desktops() 传递受益。
    """
    from rfauto.infra.desktop_guard import kill_orphan_ansysedt_desktops

    kill_orphan_ansysedt_desktops(log=print)


def _wait_variables_ready(h: Any) -> None:
    """变量管理器就绪探测（#191 家族：新建项目后 GetVariables 可 ~10s None）。"""
    for _ in range(30):
        try:
            if h.odesign is not None and h.odesign.GetVariables() is not None:
                return
        except Exception:
            pass
        time.sleep(2)


def _make_setup(h: Any, f0_ghz: float,
                sweep: dict[str, Any] | None = None) -> None:
    """单频自适应 setup（原口径）；sweep 给定时追加线性计数 sweep。

    sweep 路径沿 HfssAdapter.configure_setup（hfss_adapter.py:188-218）同一
    PyAEDT API ``create_linear_count_sweep``（adapter 本身禁改，wp39 惯例
    在运行器内复刻）；自适应频率仍为 f0（=带中心），sweep_type 显式给定
    （PyAEDT 默认 Discrete）。
    """
    setup = h.create_setup(name="Setup")
    setup.props["Frequency"] = f"{f0_ghz!r}GHz"
    setup.props["MaxDeltaS"] = 0.02
    setup.props["MaximumPasses"] = 12
    setup.update()
    if sweep:
        lo, hi = (float(v) for v in sweep["band_ghz"])
        sw = h.create_linear_count_sweep(
            setup="Setup", unit="GHz", start_frequency=lo,
            stop_frequency=hi, num_of_freq_points=int(sweep["points"]),
            name=str(sweep.get("name", "Sweep")), save_fields=False,
            sweep_type=str(sweep.get("type", "Discrete")))
        if sw in (None, False):
            raise RuntimeError(f"create_linear_count_sweep 失败: {sweep!r}")


def _add_material(h: Any) -> None:
    with contextlib.suppress(Exception):
        h.materials.add_material("rfauto_m366", properties={
            "permittivity": 3.66, "dielectric_loss_tangent": 0.0037})


# ── P1：mline 阻抗匹配（w→|S11|@2.5GHz；probe 几何变量化，#191 口径）────────


def _build_mline(h: Any, sweep: dict[str, Any] | None = None) -> None:
    from ansys.aedt.core.generic.constants import Gravity

    _add_material(h)
    X_HALF, Y_HALF = 25.0, MLINE_Y_HALF
    SUB_H = 0.508
    h.modeler.model_units = "mm"
    _wait_variables_ready(h)
    h["W"] = _mm(1.113)

    h.modeler.create_box(origin=[_mm(-X_HALF), _mm(-Y_HALF), _mm(0.0)],
                         sizes=[_mm(2 * X_HALF), _mm(2 * Y_HALF), _mm(SUB_H)],
                         name="Sub", material="rfauto_m366")
    # Line 宽 = 设计变量 W（表达式随变量量纲，#218 ③）
    h.modeler.create_box(origin=["-W/2", _mm(-Y_HALF), _mm(SUB_H)],
                         sizes=["W", _mm(2 * Y_HALF), _mm(0.0)],
                         name="Line", material="pec")
    h.modeler.create_box(origin=[_mm(-X_HALF), _mm(-Y_HALF), _mm(0.0)],
                         sizes=[_mm(2 * X_HALF), _mm(2 * Y_HALF), _mm(0.0)],
                         name="Gnd", material="pec")
    h.assign_perfecte_to_sheets(assignment=["Line"], name="LinePEC")
    h.assign_perfecte_to_sheets(assignment=["Gnd"], name="GndPEC")
    h.modeler["Sub"].solve_inside = True

    # 空气盒 y 向零边距（波端口贴外边界，#191）；x/z 5mm 辐射缓冲；
    # 必须从 Air 挖去 Sub/Line（重叠体=端口材质接触歧义，#191 实证）
    h.modeler.create_box(
        origin=[_mm(-(X_HALF + 5)), _mm(-Y_HALF), _mm(0.0)],
        sizes=[_mm(2 * X_HALF + 10), _mm(2 * Y_HALF), _mm(SUB_H + 5)],
        name="Air", material="vacuum")
    h.modeler.subtract("Air", ["Sub", "Line"])
    h.modeler["Air"].solve_inside = True
    open_faces = []
    for f in h.modeler.get_object_faces("Air"):
        cx, cy, cz = h.modeler.get_face_center(f)
        if abs(abs(cy) - (Y_HALF + 5)) < 1e-6:
            continue  # y 侧端面=端口面（端口+辐射同面不支持，#191）
        if abs(cz - (SUB_H + 5)) < 1e-6 or abs(abs(cx) - (X_HALF + 5)) < 1e-6:
            open_faces.append(f)
    h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")

    # 波端口：官方尺寸（#191/#192）：宽 5×w 高 4×sub_h，origin x=-2.5×w
    for name, y_mm in (("P1sheet", -Y_HALF), ("P2sheet", Y_HALF)):
        h.modeler.create_rectangle(
            orientation="ZX",
            origin=["-2.5*W", _mm(y_mm), _mm(0.0)],
            sizes=[_mm(4 * SUB_H), "5*W"],
            name=name)
        face = h.modeler.get_object_faces(name)[0]
        h.wave_port(assignment=face, name=name + "P", impedance=50.0,
                    renormalize=True, integration_line=Gravity.ZPos)
    _make_setup(h, 2.5, sweep=sweep)


def _s11_db_at(net: Any) -> float:
    return float(20 * np.log10(abs(net.s[0, 0, 0]) + 1e-12))


def _dry_mline(params: dict[str, float]) -> dict[str, float]:
    w = params["w_mm"]
    return {"s11_f0_db": -20.0 - 25.0 * math.exp(-((w - 1.11) / 0.30) ** 2)}


# ── P1'：mline_eps 换判据（S21 相位斜率→εeff，|εeff−target|，非 dB）──────────


def _mline_eps_from_network(net: Any) -> float:
    """HFSS 2 端口 .s2p → εeff（S21 相位斜率，线长=波端口面间距 80mm）。"""
    eps, _meta = eps_eff_from_s21_phase(net.f, net.s[:, 1, 0], MLINE_LINE_LEN_M)
    return float(eps)


def _mline_eps_metric(net: Any) -> float:
    """|εeff(net)−EPS_TARGET| —— target 未标定即报错（④ 纪律，不猜）。"""
    target = EPS_TARGET.get("mline_eps")
    if target is None:
        raise RuntimeError("mline_eps 目标 εeff 未标定（④：战役前先名义点标定）")
    return eps_eff_error_metric(_mline_eps_from_network(net), target)


def _dry_mline_eps(params: dict[str, float]) -> dict[str, float]:
    # 合成单调地貌 εeff(w)=2.80+0.12w，target 取 w=1.20 处（起点 1.113 须
    # 移动才能到达，非平凡；dry 同 ④ "target=本引擎标定值" 语义）
    eps = 2.80 + 0.12 * params["w_mm"]
    target = 2.80 + 0.12 * 1.20
    return {"eps_eff_abs_err": abs(eps - target), "eps_eff": eps}


# ── P2：patch 谐振调频（L/W→|S11|@2.0GHz；plugin 官方口径几何变量化）────────


def _build_patch(h: Any) -> None:
    _add_material(h)
    from rfauto.adapters.hfss_builder_utils import (
        AIRBOX,
        GROUND,
        MATERIAL_AIR,
        MATERIAL_PEC,
        MATERIAL_SUBSTRATE,
    )

    h.modeler.model_units = "mm"
    _wait_variables_ready(h)
    # 可调变量（基准参数面）+ 固定结构变量（recipes/patch_antenna_v1 官方口径）
    h["patch_len"] = _mm(40.0)
    h["patch_w"] = _mm(45.0)
    h["feed_offset"] = _mm(7.8)
    h["sub_h"] = _mm(0.508)
    h["sub_w"] = _mm(80.0)
    h["sub_l"] = _mm(80.0)
    h["copper_t"] = _mm(0.035)
    h["air_margin"] = _mm(10.0)
    h["air_height"] = _mm(30.0)
    h["coax_r"] = _mm(1.5)
    h["coax_wall_r"] = _mm(3.5)
    h["coax_ext"] = _mm(5.0)

    modeler = h.modeler
    modeler.create_box(origin=["(-sub_w/2)", "(-sub_l/2)", "0mm"],
                       sizes=["sub_w", "sub_l", "0mm"],
                       name=GROUND, material=MATERIAL_PEC)
    modeler.create_box(origin=["(-sub_w/2)", "(-sub_l/2)", "0mm"],
                       sizes=["sub_w", "sub_l", "sub_h"],
                       name="Substrate", material=MATERIAL_SUBSTRATE)
    modeler.create_box(origin=["(-patch_w/2)", "(-patch_len/2)", "sub_h"],
                       sizes=["patch_w", "patch_len", "copper_t"],
                       name="PatchMain", material=MATERIAL_PEC)
    # 同轴探针馈电（官方模式：PEC 针 + 真空柱 + 柱壁 PEC sheet，真机验证过）
    modeler.create_cylinder(orientation="Z",
                            origin=["feed_offset", "0mm", "(-coax_ext)"],
                            radius="coax_r", height="coax_ext",
                            name="FeedWire", material=MATERIAL_PEC)
    modeler.create_cylinder(orientation="Z",
                            origin=["feed_offset", "0mm", "0mm"],
                            radius="coax_r", height="sub_h",
                            name="FeedPinUp", material=MATERIAL_PEC)
    modeler.create_cylinder(orientation="Z",
                            origin=["feed_offset", "0mm", "(-coax_ext)"],
                            radius="coax_wall_r", height="coax_ext",
                            name="FeedOuter", material="vacuum")
    modeler.subtract(GROUND, ["FeedOuter"], keep_originals=True)
    modeler.subtract("Substrate", ["FeedPinUp"], keep_originals=True)

    def _face_axis_sets(face: Any) -> tuple[set, set, set]:
        pts = [v.position for v in face.vertices if v.position]
        xs = {round(p[0], 6) for p in pts}
        ys = {round(p[1], 6) for p in pts}
        zs = {round(p[2], 6) for p in pts}
        return xs, ys, zs

    feed_outer_obj = modeler["FeedOuter"]
    outer_wall_id = None
    port_face_obj = None
    wall_spread = -1.0
    port_bottom_z = None
    for face in feed_outer_obj.faces:
        xs, ys, zs = _face_axis_sets(face)
        if len(zs) > 1:
            spread = max(zs) - min(zs)
            if spread > wall_spread:
                wall_spread = spread
                outer_wall_id = face.id
        else:
            z = next(iter(zs))
            if port_bottom_z is None or z < port_bottom_z:
                port_bottom_z = z
                port_face_obj = face
    assert outer_wall_id is not None and port_face_obj is not None
    h.assign_perfecte_to_sheets(outer_wall_id, "FeedOuterPEC")

    modeler.create_box(
        origin=["(-sub_w/2-air_margin)", "(-sub_l/2-air_margin)",
                "(-coax_ext)"],
        sizes=["(sub_w+2*air_margin)", "(sub_l+2*air_margin)",
               "(air_height+coax_ext)"],
        name=AIRBOX, material=MATERIAL_AIR)
    modeler.subtract(AIRBOX, ["Substrate", "PatchMain", "FeedOuter",
                              "FeedWire", "FeedPinUp"])
    # 辐射边界：顶点法选空气盒外表面（底面=端口面与内部腔面排除，真机口径）
    airbox = modeler[AIRBOX]
    all_pts = [v.position for f in airbox.faces for v in f.vertices
               if v.position]
    x0e, x1e = min(p[0] for p in all_pts), max(p[0] for p in all_pts)
    y0e, y1e = min(p[1] for p in all_pts), max(p[1] for p in all_pts)
    z1e = max(p[2] for p in all_pts)
    radiating = []
    for face in airbox.faces:
        xs, ys, zs = _face_axis_sets(face)
        if (len(xs) == 1 and xs in ({x0e}, {x1e})) or (len(ys) == 1 and ys in ({y0e}, {y1e})) or (len(zs) == 1 and zs == {z1e}):
            radiating.append(face.id)
    h.assign_radiation_boundary_to_faces(assignment=radiating,
                                         name="RadiationBoundary")
    h.wave_port(port_face_obj, reference="FeedOuter", create_pec_cap=True,
                name="PortInput", impedance=50.0, renormalize=True)
    _make_setup(h, 2.45)


def _dry_patch(params: dict[str, float]) -> dict[str, float]:
    lo, ww = params["patch_len_mm"], params["patch_w_mm"]
    return {"s11_f0_db": (-2.0
                          - 12.0 * math.exp(-((lo - 40.7) / 0.55) ** 2)
                          - 1.5 * math.exp(-((ww - 42.0) / 2.5) ** 2))}


# ── P3：ratrace 隔离度（R→|S31|@2.5GHz；仲裁几何变量化，#219③）──────────────

KY = 0.866                     # 结点高度系数（模板字面，同 _ratrace_lines）
RVAR = "Rr"                   # 环半径设计变量名（"R" 被桌面判未定义，预检实证）
R_PHYS = 17.344                # 物理环半径（synthesis 1.5λg，不过 k）
W_RING = 0.6035                # 70.7Ω 环带宽
W_F = 1.1134                   # 50Ω 馈宽
BOARD = 60.0                   # 板半边
SUB_H = 0.508
AIR_TOP, AIR_BACK = 5.0, 5.0
PORT_W = 5.0 * W_F             # 官方波端口宽 5×w（#191）
PORT_H = 4.0 * SUB_H
W2 = W_F / 2.0
XT_OFF = 4.0 / math.tan(math.radians(60.0))  # 弯折点 x 偏置（模板同式）


def _rx(off: float) -> str:
    """x 坐标表达式：0.5*Rr ± off（径向段方向恒 60°，仅幅值随 Rr）。"""
    return _vexpr("0.5*" + RVAR, off)


def _mx(off: float) -> str:
    """镜像侧 x 坐标表达式：−0.5*R ± off（off 为相对弯折基点的原始偏移；
    绝对坐标处的负偏移由调用方显式传负值）。"""
    return _vexpr("-0.5*" + RVAR, off)


def _ry(off: float, sign: int = 1) -> str:
    """y 坐标表达式：±0.866*Rr ± const。"""
    return _vexpr(f"{'' if sign > 0 else '-'}{KY!r}*{RVAR}", off)


def _stub_quad(x_coef: Callable[[float], str], y_sign: int,
               dx: float, dy: float, z: str) -> list[list[str]]:
    """径向馈+弯折段带状四边形角点 a,c,d,b（带宽 2·W2，方向随 (dx,dy)）。"""
    norm = math.hypot(dx, dy)
    nx, ny = dy / norm, -dx / norm
    near = [(x_coef(s * W2 * nx), _ry(s * W2 * ny, y_sign))
            for s in (1.0, -1.0)]
    far = [(x_coef(dx + s * W2 * nx), _ry(dy + s * W2 * ny, y_sign))
           for s in (1.0, -1.0)]
    pts = near + far  # [a, b, c, d]
    return [[pts[0][0], pts[0][1], z], [pts[2][0], pts[2][1], z],
            [pts[3][0], pts[3][1], z], [pts[1][0], pts[1][1], z]]


def _build_ratrace(h: Any, sweep: dict[str, Any] | None = None) -> None:
    from ansys.aedt.core.generic.constants import Gravity

    _add_material(h)
    h.modeler.model_units = "mm"
    _wait_variables_ready(h)
    h[RVAR] = _mm(R_PHYS)
    z = _mm(SUB_H)

    h.modeler.create_box(
        origin=[_mm(-BOARD - AIR_BACK), _mm(-BOARD), _mm(0.0)],
        sizes=[_mm(BOARD + AIR_BACK + BOARD), _mm(2 * BOARD), _mm(0.0)],
        name="Gnd", material="pec")
    h.modeler.create_box(origin=[_mm(-BOARD), _mm(-BOARD), _mm(0.0)],
                         sizes=[_mm(2 * BOARD), _mm(2 * BOARD), _mm(SUB_H)],
                         name="Sub", material="rfauto_m366")
    h.modeler["Sub"].solve_inside = True
    # 环带 = 外圆盘 − 内圆盘（半径 = 设计变量 R ± 常量，#218 ③）
    h.modeler.create_circle(orientation="XY", origin=["0mm", "0mm", z],
                            radius=_vexpr(RVAR, W_RING / 2),
                            name="RingOuter", material="pec")
    h.modeler.create_circle(orientation="XY", origin=["0mm", "0mm", z],
                            radius=_vexpr(RVAR, -W_RING / 2),
                            name="RingInner", material="pec")
    h.modeler.subtract("RingOuter", ["RingInner"])
    sheets = ["RingOuter"]
    # Σ 馈（geo 0°，x∈[Rr, BOARD]，水平，宽度/位置与 Rr 无关）
    h.modeler.create_box(origin=[RVAR, _mm(-W2), z],
                         sizes=[_sub_expr(BOARD, RVAR), _mm(W_F), _mm(0.0)],
                         name="FeedSigma", material="pec")
    sheets.append("FeedSigma")  # 仲裁同式——漏 append=Σ 馈不并入环（预检实证）
    # 径向馈 + 弯折竖直引出（out1=60°/out2=300° 右侧，Δ=120° 左镜像）
    h.modeler.create_polyline(
        points=_stub_quad(_rx, +1, XT_OFF, 4.0, z),
        cover_surface=True, close_surface=True, name="StubOut1",
        material="pec")
    h.modeler.create_polyline(
        points=_stub_quad(_rx, -1, XT_OFF, -4.0, z),
        cover_surface=True, close_surface=True, name="StubOut2",
        material="pec")
    h.modeler.create_polyline(
        points=_stub_quad(_mx, +1, -XT_OFF, 4.0, z),
        cover_surface=True, close_surface=True, name="StubDelta",
        material="pec")
    # 竖直引出段（出顶缘 ×2、出底缘 ×1；x 中心 = X_T ± 常量）
    vert_h = f"{BOARD - 4!r}mm-{KY!r}*{RVAR}"
    h.modeler.create_box(origin=[_rx(XT_OFF - W2), _ry(4.0), z],
                         sizes=[_mm(W_F), vert_h, _mm(0.0)],
                         name="VertOut1", material="pec")
    h.modeler.create_box(origin=[_vexpr("-0.5*" + RVAR, -(XT_OFF + W2)),
                                 _ry(4.0), z],
                         sizes=[_mm(W_F), vert_h, _mm(0.0)],
                         name="VertDelta", material="pec")
    h.modeler.create_box(origin=[_rx(XT_OFF - W2), _mm(-BOARD), z],
                         sizes=[_mm(W_F), vert_h, _mm(0.0)],
                         name="VertOut2", material="pec")
    sheets += ["StubOut1", "StubOut2", "StubDelta",
               "VertOut1", "VertDelta", "VertOut2"]
    h.modeler.unite(sheets)
    h.assign_perfecte_to_sheets(assignment=["Gnd", "RingOuter"],
                                name="MetalPEC")
    # 空气域：端口侧（x=+BOARD/y=±BOARD）零缓冲，−x/顶留辐射缓冲
    h.modeler.create_box(
        origin=[_mm(-BOARD - AIR_BACK), _mm(-BOARD), _mm(0.0)],
        sizes=[_mm(BOARD + AIR_BACK + BOARD), _mm(2 * BOARD),
               _mm(SUB_H + AIR_TOP)],
        name="Air", material="vacuum")
    h.modeler.subtract("Air", ["Sub", "RingOuter"])
    h.modeler["Air"].solve_inside = True
    # 辐射边界：正向选取顶面 + −x 外侧面（端口面/底面/内腔面不辐射，#219③）
    top_z = SUB_H + AIR_TOP
    open_faces = []
    for f in h.modeler.get_object_faces("Air"):
        cx, _cy, cz = h.modeler.get_face_center(f)
        if cz <= SUB_H + 1e-6:
            continue
        if abs(cz - top_z) < 1e-6 or abs(cx - (-BOARD - AIR_BACK)) < 1e-6:
            open_faces.append(f)
    h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")

    # 波端口（官方尺寸 5w×4h，#191；P1 Σ@x=+BOARD 固定，P2-P4 随 R）
    p24_x = _rx(XT_OFF - PORT_W / 2)
    p3_x = _vexpr("-0.5*" + RVAR, -(XT_OFF + PORT_W / 2))
    port_specs = [
        ("P1sheet", "YZ", [_mm(BOARD), _mm(-PORT_W / 2), _mm(0.0)],
         [_mm(PORT_W), _mm(PORT_H)]),
        ("P2sheet", "ZX", [p24_x, _mm(BOARD), _mm(0.0)],
         [_mm(PORT_H), _mm(PORT_W)]),
        ("P3sheet", "ZX", [p3_x, _mm(BOARD), _mm(0.0)],
         [_mm(PORT_H), _mm(PORT_W)]),
        ("P4sheet", "ZX", [p24_x, _mm(-BOARD), _mm(0.0)],
         [_mm(PORT_H), _mm(PORT_W)]),
    ]
    for name, orient, origin, sizes in port_specs:
        h.modeler.create_rectangle(orientation=orient, origin=origin,
                                   sizes=sizes, name=name)
        face = h.modeler.get_object_faces(name)[0]
        h.wave_port(assignment=face, name=name + "P", impedance=50.0,
                    renormalize=True, integration_line=Gravity.ZPos)
    _make_setup(h, 2.5, sweep=sweep)


def _s31_db_at(net: Any) -> float:
    return float(20 * np.log10(abs(net.s[0, 2, 0]) + 1e-12))


def _s31_null_neighborhood_db(net: Any) -> float:
    """③ 深零点邻域指标（sweep 2.3–2.7GHz 样本；与 ratrace_null.json 同源常量）。"""
    s31_db = 20.0 * np.log10(np.abs(net.s[:, 2, 0]) + 1e-12)
    return deep_null_neighborhood_db(
        net.f / 1e9, s31_db, *RATRACE_NULL_SEARCH_GHZ, RATRACE_NULL_HW_GHZ)


def _dry_ratrace_null(params: dict[str, float]) -> dict[str, float]:
    # 合成 Lorentzian 深零点：零点频率随 r 漂移、谷深随 |r−r*| 收浅——
    # 单频谷深会随之摆动，邻域功率平均不动（③ 判据语义）
    r = params["r_mm"]
    f = np.linspace(*RATRACE_NULL_SEARCH_GHZ, 81)
    f_null = 2.5 + 0.05 * (r - 16.9)
    depth_db = -52.0 + 6.0 * abs(r - 16.9)
    p_floor = 10.0 ** (-20.0 / 10.0)
    p_null = 10.0 ** (depth_db / 10.0)
    power = p_floor - (p_floor - p_null) / (
        1.0 + ((f - f_null) / 0.02) ** 2)
    v = 10.0 * np.log10(power)
    return {"s31_null_neighborhood_db": float(
        deep_null_neighborhood_db(
            f, v, *RATRACE_NULL_SEARCH_GHZ, RATRACE_NULL_HW_GHZ))}


def _dry_ratrace(params: dict[str, float]) -> dict[str, float]:
    r = params["r_mm"]
    return {"s31_f0_db": -28.0 - 25.0 * math.exp(-((r - 16.9) / 0.8) ** 2)}


# ── 问题注册表 ───────────────────────────────────────────────────────────────

PROBLEMS: dict[str, ProblemDef] = {
    "mline": ProblemDef(
        name="mline", metric_name="s11_f0_db",
        metric_desc="|S11|@2.5GHz dB（越负越好；50Ω 匹配 w*≈1.11，HJ 综合）",
        bounds={"w_mm": (0.5, 2.0)}, nominal={"w_mm": 1.113},
        var_map={"w_mm": "W"}, design_name="mline", f0_ghz=2.5,
        n_ports=2,
        n_init=5, build=_build_mline, metric_from_network=_s11_db_at,
        dry_metrics=_dry_mline, ports_desc="2 波端口（官方 5w×4h，#191）",
        extra={"family": "均匀微带线（hfss_mline_probe 几何变量化）"}),
    "patch": ProblemDef(
        name="patch", metric_name="s11_f0_db",
        metric_desc="|S11|@2.45GHz dB（越负越好；谐振调频对准 2.45GHz "
                    "ISM。目标经真机标定：标称 L=40 实测谷位 2.495GHz/"
                    "深 -13.9dB（runs/patch_hfss_probe，f_dip·L≈99.8 本机"
                    "口径），首版 2.0GHz 目标在盒内无谷（地貌平坦，两臂"
                    "同判无效基准）后重定心）",
        bounds={"patch_len_mm": (36.5, 41.5), "patch_w_mm": (40.0, 45.0)},
        nominal={"patch_len_mm": 40.0, "patch_w_mm": 45.0},
        var_map={"patch_len_mm": "patch_len", "patch_w_mm": "patch_w"},
        design_name="patch", f0_ghz=2.45,
        n_ports=1,
        n_init=8, build=_build_patch, metric_from_network=_s11_db_at,
        dry_metrics=_dry_patch,
        ports_desc="1 同轴探针波端口（官方 create_pec_cap 口径）",
        extra={"family": "矩形贴片天线（models/patch_antenna plugin 几何）",
               "feed_offset_mm": 7.8}),
    "ratrace": ProblemDef(
        name="ratrace", metric_name="s31_f0_db",
        metric_desc="|S31|@2.5GHz dB（越负越好；Σ→Δ 隔离，环中心对准 f0，"
                    "R*≈R_nom·f_center/f0≈16.9）",
        bounds={"r_mm": (15.5, 19.5)}, nominal={"r_mm": R_PHYS},
        var_map={"r_mm": RVAR}, design_name="ratrace", f0_ghz=2.5,
        n_ports=4,
        n_init=5, build=_build_ratrace, metric_from_network=_s31_db_at,
        dry_metrics=_dry_ratrace,
        ports_desc="4 波端口（官方 5w×4h，#219③ 仲裁几何变量化）",
        extra={"family": "rat-race 混合环（hfss_ratrace_arbitration 几何）",
               "w_ring_mm": W_RING, "w_feed_mm": W_F, "k_y": KY}),
    # ── 换判据变体（wp39-factory-verdict-next）───────────────────
    "mline_eps": ProblemDef(
        name="mline_eps", metric_name="eps_eff_abs_err",
        metric_desc="|εeff_engine(w)−εeff_target|（无量纲非 dB，越小越好；"
                    "target 按④纪律由本引擎名义点标定——HFSS 侧 S21 相位"
                    "斜率抽取，eps_eff_from_s21_phase）",
        bounds={"w_mm": (0.5, 2.0)}, nominal={"w_mm": 1.113},
        var_map={"w_mm": "W"}, design_name="mline_eps", f0_ghz=2.5,
        n_ports=2,
        n_init=5,
        build=lambda h: _build_mline(h, sweep=MLINE_EPS_SWEEP),
        metric_from_network=_mline_eps_metric,
        dry_metrics=_dry_mline_eps,
        ports_desc="2 波端口（同 mline，官方 5w×4h）",
        metric_semantics_note=("（无量纲 |εeff−target| 非 dB，越小越好；"
                               "target=本引擎名义点标定值）"),
        sweep=MLINE_EPS_SWEEP, calibrate=True,
        eps_extract=_mline_eps_from_network,
        x0={"w_mm": 1.25},
        extra={"family": "均匀微带线换判据档（归因 runs/"
                        "wp39_factory_verdict_next/attribution_mline_s11_"
                        "pseudofloor.md：|S11| 地貌=端口伪底，εeff 物理）",
               "line_len_m": MLINE_LINE_LEN_M}),
    "ratrace_null": ProblemDef(
        name="ratrace_null", metric_name="s31_null_neighborhood_db",
        metric_desc="深零点邻域功率平均 dB（搜索带 2.3–2.7GHz 内实测谷位"
                    "±25MHz；deep_null_neighborhood_db，③ 判据；与 "
                    "runs/wp39_mvp_followup/ratrace_null.json 常量同源）",
        bounds={"r_mm": (15.5, 19.5)}, nominal={"r_mm": R_PHYS},
        var_map={"r_mm": RVAR}, design_name="ratrace_null", f0_ghz=2.5,
        n_ports=4,
        n_init=5,
        build=lambda h: _build_ratrace(h, sweep=RATRACE_NULL_SWEEP),
        metric_from_network=_s31_null_neighborhood_db,
        dry_metrics=_dry_ratrace_null,
        ports_desc="4 波端口（同 ratrace，官方 5w×4h）",
        metric_semantics_note="（带内邻域功率平均 dB，越负越好）",
        sweep=RATRACE_NULL_SWEEP,
        extra={"family": "rat-race 混合环换判据档（③ 单频谷深对网格自适应"
                        "敏感 → 邻域能量判读；两臂同 sweep 重跑）",
               "w_ring_mm": W_RING, "w_feed_mm": W_F, "k_y": KY,
               "null_search_ghz": RATRACE_NULL_SEARCH_GHZ,
               "null_half_window_ghz": RATRACE_NULL_HW_GHZ}),
}


# ── HFSS 真机 evaluator ──────────────────────────────────────────────────────


class HfssEvaluator:
    """单战役 HFSS 通道：launch → build →（set var → solve → 导出 → 指标）×N。"""

    def __init__(self, problem: ProblemDef, workdir: Path) -> None:
        self.problem = problem
        # #140：第一行 Path() 收敛并转绝对——AEDT Project.Rename 按 ansysedt
        # 自身 cwd 解析相对路径，相对 -outdir 会让 Hfss() 构造期 Rename 挂起
        # ~6min 后 GrpcApiError（mline_eps 3/3 实证，绝对路径即过）
        self.workdir = Path(workdir).resolve()
        self.h = None
        self.adapter = None
        self.launch_s = 0.0
        self.build_s = 0.0
        self.n_solved = 0
        #: ④ 标定记录（calibrate 问题）：名义点 εeff/墙钟，独立于预算记账
        self.calibration: dict[str, Any] | None = None

    def launch_and_build(self) -> None:
        from ansys.aedt.core import Hfss

        t0 = time.time()
        self.h = Hfss(project=str(self.workdir / f"{self.problem.name}.aedt"),
                      design=self.problem.design_name, version=HFSS_VERSION,
                      non_graphical=True, new_desktop=True)
        self.launch_s = time.time() - t0
        t0 = time.time()
        self.problem.build(self.h)
        self.build_s = time.time() - t0
        from rfauto.adapters.hfss_adapter import HfssAdapter

        self.adapter = HfssAdapter()
        self.adapter.session.hfss = self.h

    def solve_network(self, params: dict[str, float]) -> Any:
        """set var → solve →（sweep 完成断言）→ 导出 → skrf.Network。"""
        import skrf

        for pname, hname in self.problem.var_map.items():
            self.h[hname] = f"{params[pname]:.10g}mm"
        report = self.adapter.solve("Setup")
        if not report.success:
            raise RuntimeError(f"solve 失败: {report.message}")
        if self.problem.sweep:
            # #191 家族：导出前显式确认 sweep 真正完成
            # （HfssAdapter.assert_sweep_completed，adapter 禁改直接消费）
            self.adapter.assert_sweep_completed(
                "Setup", str(self.problem.sweep.get("name", "Sweep")))
        out = self.workdir / f"eval_{self.n_solved}.sNp"
        out.unlink(missing_ok=True)
        sNp = self.adapter.export_touchstone(out)
        sNp = self._normalize_touchstone_suffix(Path(sNp))
        self.n_solved += 1
        return skrf.Network(str(sNp))

    def evaluate(self, params: dict[str, float]) -> dict[str, float]:
        net = self.solve_network(params)
        metric = self.problem.metric_from_network(net)
        metrics = {self.problem.metric_name: metric}
        if self.problem.eps_extract is not None:
            metrics["eps_eff"] = float(self.problem.eps_extract(net))
        return metrics

    def calibrate(self) -> dict[str, Any]:
        """④ 纪律：名义点解一次抽 εeff → EPS_TARGET[problem]（不计预算）。"""
        if self.problem.eps_extract is None:
            raise RuntimeError(f"{self.problem.name} 无 eps_extract，无法标定")
        t0 = time.time()
        net = self.solve_network(dict(self.problem.nominal))
        eps = float(self.problem.eps_extract(net))
        EPS_TARGET[self.problem.name] = eps
        self.calibration = {
            "params": dict(self.problem.nominal), "eps_eff_target": eps,
            "wall_s": round(time.time() - t0, 2),
            "n_freq": int(net.f.size),
            "freq_range_ghz": [round(float(net.f.min()) / 1e9, 4),
                               round(float(net.f.max()) / 1e9, 4)],
            "note": "④ 纪律：本引擎名义点标定 εeff 目标（S21 相位斜率抽取，"
                    "线长=波端口面间距）；标定评估独立记账，不计入预算",
        }
        return self.calibration

    def _normalize_touchstone_suffix(self, path: Path) -> Path:
        """字面 .sNp 扩展名归一成 .s{N}p（skrf 按扩展名推断端口数）。

        patch 预检实证：1 端口设计走 HfssAdapter.export_touchstone
        时不触发 n_ports≥2 的扩展名修正分支，HFSS 2025.1 落盘字面 ".sNp"，
        skrf.Network 无法解析——按问题端口数改名后读取。adapter 禁改，
        归一化留在本基准 evaluator。
        """
        if path.suffix.lower() != ".snp" or not path.exists():
            return path
        fixed = path.with_suffix(f".s{self.problem.n_ports}p")
        shutil.copyfile(path, fixed)
        return fixed

    def close(self) -> None:
        if self.h is not None:
            with contextlib.suppress(Exception):
                self.h.release_desktop(close_projects=True,
                                       close_desktop=True)
            self.h = None


# ── 引擎驱动（kernel 装配）───────────────────────────────────────────────────


def sbo_tol_abs(problem: ProblemDef) -> float:
    """stagnation 容差随指标量纲：dB 指标 0.25dB；εeff 误差指标 0.003。"""
    return (SBO_TOL_ABS_EPS if problem.metric_name.startswith("eps_eff")
            else SBO_TOL_ABS_DB)


def run_sbo_engine(problem: ProblemDef,
                   evaluate_fn: Callable[[dict[str, float]], dict[str, float]],
                   budget: int, seed: int) -> dict[str, Any]:
    from rfauto.optimization.surrogate_loop import run_surrogate_loop
    from rfauto.service.wp39_benchmark import sbo_objectives

    return run_surrogate_loop(
        problem.bounds, sbo_objectives(problem.metric_name), evaluate_fn,
        n_init=problem.n_init, top_k=SBO_TOP_K,
        virtual_trials=SBO_VIRTUAL_TRIALS, max_real=budget,
        tol_abs=sbo_tol_abs(problem), tol_rounds=SBO_TOL_ROUNDS,
        surrogate_kind="smt_kriging", seed=seed)


def run_pattern_engine(problem: ProblemDef,
                       evaluate_fn: Callable[[dict[str, float]], dict[str, float]],
                       budget: int, _seed: int) -> dict[str, Any]:
    from rfauto.service.wp39_benchmark import pattern_search_loop, sbo_objectives

    return pattern_search_loop(
        problem.bounds, evaluate_fn, sbo_objectives(problem.metric_name),
        x0=problem.x0 or problem.nominal, budget=budget)


ENGINES = {"sbo": run_sbo_engine, "pattern_search": run_pattern_engine}


# ── 战役执行 + JSON ──────────────────────────────────────────────────────────


def _kernel_opt_s(kernel: dict[str, Any]) -> float:
    return float(kernel.get("elapsed_s")
                 or (kernel.get("wall_s") or {}).get("optimization_s") or 0.0)


def _flatten_best(problem: ProblemDef, kernel: dict[str, Any]) -> dict | None:
    best = kernel.get("best")
    if not best:
        return None
    return {"params": best.get("params"),
            "metric": (best.get("metrics") or {}).get(problem.metric_name),
            "cost": best.get("cost")}


def run_campaign(problem_name: str, engine: str, outdir: Path,
                 budget: int = BUDGET_DEFAULT, dry_run: bool = False,
                 seed: int = SEED_DEFAULT) -> Path:
    problem = PROBLEMS[problem_name]
    outdir.mkdir(parents=True, exist_ok=True)
    out_json = outdir / f"{problem_name}__{engine}.json"
    attempts: list[dict[str, Any]] = []

    def write(stage: str, kernel: dict[str, Any] | None,
              evaluator: HfssEvaluator | None, note: str) -> None:
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "problem": problem_name, "engine": engine,
            "engine_impl": CANDIDATE_IMPL_DESC if engine == "sbo"
            else BASELINE_IMPL_DESC,
            "budget": budget, "stage": stage,
            "metric_name": problem.metric_name,
            "metric_semantics": problem.metric_desc + problem.metric_semantics_note,
            "params_meta": {
                "bounds": {k: list(v) for k, v in problem.bounds.items()},
                "nominal_start": problem.nominal,
                "pattern_search_x0": problem.x0 or problem.nominal,
                "unit": "mm", "var_map": problem.var_map},
            "problem_extra": problem.extra,
            "ports": problem.ports_desc,
            "dry_run": dry_run, "seed": seed, "attempts": attempts,
            "note": note,
        }
        if dry_run:
            payload["evaluator"] = "offline 解析面（dry-run，零真机）"
            payload["hfss"] = None
        else:
            setup_meta: dict[str, Any] = {
                "type": "single_frequency", "freq_ghz": problem.f0_ghz,
                "MaxDeltaS": 0.02, "MaximumPasses": 12}
            if problem.sweep:
                setup_meta["type"] = "adaptive_plus_linear_count_sweep"
                setup_meta["sweep"] = {
                    k: (list(v) if isinstance(v, tuple) else v)
                    for k, v in problem.sweep.items()}
            payload["hfss"] = {
                "version": HFSS_VERSION, "solution": "DrivenModal",
                "setup": setup_meta,
                "launch_s": None if evaluator is None
                else round(evaluator.launch_s, 2),
                "build_s": None if evaluator is None
                else round(evaluator.build_s, 2),
            }
            if evaluator is not None and evaluator.calibration is not None:
                payload["calibration"] = evaluator.calibration
        if kernel is not None:
            opt_s = _kernel_opt_s(kernel)
            payload.update({
                "best": _flatten_best(problem, kernel),
                "n_evals": kernel.get("n_attempts", kernel.get("n_evals")),
                "n_failures": kernel.get("n_failures"),
                "stop_reason": kernel.get("stop_reason"),
                "real_cost_trace": kernel.get("real_cost_trace"),
                "best_so_far_trace": kernel.get("best_so_far_trace"),
                "wall_s": {"optimization_s": round(opt_s, 2)},
                "kernel": {k: v for k, v in kernel.items()
                           if k not in ("best", "real_cost_trace",
                                        "best_so_far_trace", "failures")},
                "eval_failures": kernel.get("failures") or [],
            })
            if evaluator is not None:
                payload["wall_s"].update({
                    "launch_s": round(evaluator.launch_s, 2),
                    "build_s": round(evaluator.build_s, 2),
                    "total_s": round(evaluator.launch_s + evaluator.build_s
                                     + opt_s, 2)})
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                                       default=str), encoding="utf-8")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        evaluator: HfssEvaluator | None = None
        workdir = outdir / f"_work_{problem_name}__{engine}"
        try:
            if dry_run:
                kernel = ENGINES[engine](problem, problem.dry_metrics,
                                         budget, seed)
                write("done", kernel, None, "dry-run 解析面自检（零真机）")
                return out_json
            _kill_desktops()
            shutil.rmtree(workdir, ignore_errors=True)
            workdir.mkdir(parents=True, exist_ok=True)
            evaluator = HfssEvaluator(problem, workdir)
            evaluator.launch_and_build()
            if problem.calibrate:
                cal = evaluator.calibrate()
                print(f"[calibrate] {problem.name} nominal={cal['params']} "
                      f"eps_eff_target={cal['eps_eff_target']:.5f} "
                      f"({cal['wall_s']}s)", flush=True)
            kernel = ENGINES[engine](problem, evaluator.evaluate, budget,
                                     seed)
            has_best = kernel.get("best") is not None
            write("done" if has_best else "all_evals_failed", kernel,
                  evaluator,
                  f"attempt {attempt}/{MAX_ATTEMPTS}"
                  + ("" if has_best else "（全评估失败：desktop 级故障，"
                     "整轮重启不计入判据）"))
            if has_best:
                return out_json
            attempts.append({"attempt": attempt, "outcome": "no_success"})
        except Exception as exc:  # desktop/建模级故障 → 整轮重启
            print(f"attempt {attempt}/{MAX_ATTEMPTS} FAIL: {exc!r}",
                  flush=True)
            attempts.append({"attempt": attempt, "outcome": "error",
                             "error": repr(exc)})
            write("attempt_failed", None, evaluator, repr(exc))
        finally:
            if evaluator is not None:
                evaluator.close()
    print(f"WP39_CAMPAIGN_FAIL {problem_name} {engine}", flush=True)
    return out_json


# ── 判定汇总 ─────────────────────────────────────────────────────────────────


def judge(outdir: Path) -> Path:
    from rfauto.service.wp39_benchmark import (
        COST_MAX_DEGRADATION_PCT,
        WALLCLOCK_MAX_RATIO,
        judge_problem_pair,
        summarize_judgment,
    )

    verdicts: dict[str, dict[str, Any]] = {}
    for pname in sorted(PROBLEMS):
        base_p = outdir / f"{pname}__pattern_search.json"
        cand_p = outdir / f"{pname}__sbo.json"
        if not base_p.exists() and not cand_p.exists():
            continue  # 该问题未在本 outdir 开跑（换判据变体等），不占表
        if not base_p.exists() or not cand_p.exists():
            verdicts[pname] = {
                "problem": pname, "verdict": "FAIL",
                "reasons": [f"缺少战役 JSON：{base_p.name} / {cand_p.name}"]}
            continue
        base = json.loads(base_p.read_text(encoding="utf-8"))
        cand = json.loads(cand_p.read_text(encoding="utf-8"))
        verdicts[pname] = judge_problem_pair(base, cand)
    summary = summarize_judgment(verdicts)
    payload = {
        "schema": "wp39_mvp_summary_v1",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "criteria": {
            "budget": BUDGET_DEFAULT,
            "wallclock_max_ratio": WALLCLOCK_MAX_RATIO,
            "cost_max_degradation_pct": COST_MAX_DEGRADATION_PCT,
            "source": "WP3.9 MVP 基准"},
        "baseline_tiers": {
            "pattern_search": "达标线（本 MVP 实测）",
            "optislang_mop": "超额线（未接，见 followUps）"},
        "engines": {"candidate": CANDIDATE_IMPL_DESC,
                    "baseline": BASELINE_IMPL_DESC},
        "problems": verdicts,
        "summary": summary,
    }
    out = outdir / "summary.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for pname, v in verdicts.items():
        print(f"[{pname}] {v['verdict']} "
              f"ratio={v.get('wallclock_ratio')} deg%={v.get('degradation_pct')} "
              f"reasons={v.get('reasons')}")
    print(f"WP39_MVP_SUMMARY_{summary['overall']} -> {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-problem", choices=sorted(PROBLEMS), default=None)
    ap.add_argument("-engine", choices=sorted(ENGINES), default=None)
    ap.add_argument("-budget", type=int, default=BUDGET_DEFAULT)
    ap.add_argument("-outdir", default=str(DEFAULT_OUTDIR))
    ap.add_argument("-seed", type=int, default=SEED_DEFAULT)
    ap.add_argument("-dry-run", action="store_true")
    ap.add_argument("-judge", action="store_true")
    args = ap.parse_args()

    if args.judge:
        judge(Path(args.outdir).resolve())
        return 0
    if not args.problem or not args.engine:
        ap.error("-problem 与 -engine 必填（或使用 -judge）")
    import os

    os.environ.setdefault("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "900")
    out = run_campaign(args.problem, args.engine, Path(args.outdir).resolve(),
                       budget=args.budget, dry_run=args.dry_run,
                       seed=args.seed)
    print(f"WP39_CAMPAIGN_DONE {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
