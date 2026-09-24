"""数据工厂 B2 多保真 HFSS 稀疏锚点采集（脚本就绪；HFSS 真机由主代理排机）。

锚点计划（与 runs/datasets/datafactory_m1m3_merged_20260920 的 openEMS
150 行**同参数嵌套 DoE**——锚 w 一律对齐数据集精确既有值，使 smt_mfk 的
AR1 相关结构成立、"纯 OE 直接当预测"基线臂可做同 w 精确配对）：
  train 基础锚 = {0.5, 2.0, 1.113, 0.9178}（0.9178=S11 谷芯必钉；
                 落盘前吸附到数据集谷芯值 0.9177777…，Δw≈2.2e-5 mm）
  train 可选锚 = {0.745, 1.182}（--full 时加入）
  held-out 锚  = 从数据集精确值里按"最靠近区间中点"各取一个：
                 [0.95,1.05] 与 [1.4,1.6] 各一（#371 门判读点）
  全部 line_len=40mm（与 OE 采集 factory_m1_collect.LINE_LEN_MM 同参数）。

εeff 参考面跨度审计（#364② 红线①，先审计后采信——#1b）：
  scripts/hfss_mline_probe.py 的 L_TOTAL 口径 = **两端口面之间的实际几何
  跨度**（该探针 line 贯通 y∈[-40,40]，L_TOTAL=80=实测跨度，端面即端口
  面、无馈段）。本脚本同法：line 贯通 y∈[-20,+20]（line_len=40），端口
  面即线端。εeff 只用**实测端口面跨度 L_span**（get_face_center 实测，
  mm 口径——#285），绝不用名义 line_len 代入斜率式；审计断言：
    |L_span − line_len| ≤ 1e-6 mm（端口面=线端，名义==实测必须成立，
      不成立即几何错误，solve 前拦下）；
    端口片 x 居中、line 贯通跨度==L_span（连通性，#336 精神）、空气盒
      y 向与端口面齐平（端口在外边界——#191）；
    解出的 εeff ∈ [1.5, 5.0]（εr=3.66 微带族物理窗，越界即几何可疑）。
  #364② 的"名义 40mm 线实测跨度 93.2mm"根因=模板参考面在板缘含馈段；
  本几何无馈段、端口面=线端，故 nominal==measured 是**可断言的强约束**。
  实测端口面坐标与断言结果全部落 anchor.json 的 audit 块留痕。

链路复用 scripts/hfss_mline_probe.py 的 PyAEDT 口径：
  波端口官方尺寸（宽 5×w、高 4×sub_h，#192 PASS_A 同法）、PEC 薄片
  assign_perfecte_to_sheets（#356①：零厚盒 material="pec" 不导电）、
  介质 solve_inside 显式钉住、空气盒 y 向不留边距 + subtract 重叠体、
  辐射边界只赋顶面+x 侧面、Quantity 量纲安全构建器（#218）、
  Discrete 扫频 2.4–2.6GHz 41 点、finally release_desktop（#265 孤儿
  ansysedt 铁律）、逐点整轮重试（#191 gRPC 通道级不稳定）。

用法（cwd=仓库根；venv=.venv\\Scripts\\python.exe）：
  python scripts/factory_mf_hfss_anchors.py --audit            # 离线：锚点表+口径审计（无 HFSS）
  python scripts/factory_mf_hfss_anchors.py --collect          # HFSS 真跑（主代理排机）
  python scripts/factory_mf_hfss_anchors.py --collect --full   # 真跑并加可选锚
  python scripts/factory_mf_hfss_anchors.py --collect --extra-w 1.5
      # 补锚收尾：补充训练锚（名义 w；吸附最近数据集精确值，
      # 剔除既有锚含 held-out 门点——判据 anchor15_criteria.md §1/§2）
断点续跑：--collect 幂等；已有 anchor.json(status=done) 的点自动跳过。

退出码：--audit 预检全过 0，否则 1；--collect 全部锚点 done=0，否则 1。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.infra.desktop_guard import (
    kill_orphan_ansysedt_desktops as _kill_desktops,
)
from rfauto.infra.desktop_guard import release_desktop_capped, run_with_watchdog

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# ─── 预声明常量（与 factory_m1_collect / hfss_mline_probe 同源口径） ─────────
ROOT = REPO / "runs" / "factory_mf_anchors"
DATASET_DIR = REPO / "runs" / "datasets" / "datafactory_m1m3_merged_20260920"
SUBSTRATE = {"er": 3.66, "h_mm": 0.508, "tan_d": 0.0037}  # rogers4350b 锚口径
MATERIAL_NAME = "rfauto_m366"
LINE_LEN_MM = 40.0
BAND_GHZ = (2.4, 2.6)
SWEEP_POINTS = 41  # Discrete，0.005GHz 步进（含 M2 消费栅格全部 0.01 倍点）
FREQ_CENTER_GHZ = 2.5
SETUP_MAX_PASSES = 12
SETUP_MAX_DELTA_S = 0.02
TRAIN_ANCHORS = (0.5, 2.0, 1.113, 0.9178)
OPTIONAL_ANCHORS = (0.745, 1.182)
HELDOUT_RANGES = ((0.95, 1.05), (1.4, 1.6))
SNAP_TOL_MM = 1e-3  # 锚点吸附数据集精确值的容差（LHS 网格间距 0.01 的 1/10）
SPAN_ASSERT_TOL_MM = 1e-6
EPS_PHYS_WINDOW = (1.5, 5.0)  # εr=3.66 微带族 εeff 物理窗（越界即几何可疑）
C0 = 299792458.0
AEDT_VERSION_DEFAULT = "2025.1"  # hfss_mline_probe 全链实证版本
POINT_ATTEMPTS = 3  # 逐点整轮重试（#191：gRPC 通道级不稳定，单调用重试无效）
SOLVE_TIMEOUT_S = int(os.environ.get("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "21600"))
# 单 setup 求解看门狗（6h 防挂死上限，非预算门；hfss_interdigital_check
# 同款口径：Setup 级实测可达 5h 级，80min 级看门狗必误杀；#145 env 口径）
#: 官方波端口尺寸比例（Ansys Wave Port Size 口径，#192 PASS_A 同法）
PORT_W_FACTOR = 5.0
PORT_H_FACTOR = 4.0
PORT_X_FACTOR = -2.5
X_HALF_MM = 25.0  # 基板 x 半宽（探针同款）；空气盒 x/z 外扩 X_MARGIN_MM
X_MARGIN_MM = 5.0  # 空气盒 x/z 辐射缓冲（y 向不留边距，#191）

__all__ = [
    "build_anchor_plan",
    "load_dataset_ws",
    "point_id_for_w",
    "resolve_anchor_ws",
    "resolve_extra_anchor_ws",
    "select_heldout_ws",
]


# ─── 纯逻辑（离线可测：计划/吸附/held-out 选取） ─────────────────────────────


def point_id_for_w(w: float, used: dict[str, float]) -> str:
    """点 id（mfa_w<µm 四位>）；四舍五入撞名时追加序号守卫。"""
    base = f"mfa_w{round(float(w) * 1000):04d}"
    if base not in used:
        return base
    i = 2
    while f"{base}_{i}" in used:
        i += 1
    return f"{base}_{i}"


def resolve_anchor_ws(dataset_ws: list[float],
                      anchors: tuple[float, ...] = TRAIN_ANCHORS,
                      snap_tol: float = SNAP_TOL_MM) -> list[dict[str, float]]:
    """锚点 w 吸附到数据集精确既有值（嵌套 DoE 前提）。

    精确命中（|Δ|≤1e-9）直接用；否则取最近数据集值（须 ≤snap_tol；
    容差内出现距离并列的两个近邻 → 报错不猜）。无候选 → ValueError。
    """
    out: list[dict[str, float]] = []
    ws = np.asarray(dataset_ws, dtype=float)
    for a in anchors:
        a = float(a)
        exact = ws[np.abs(ws - a) <= 1e-9]
        if exact.size >= 1:
            out.append({"nominal": a, "run": float(exact[0]),
                        "snap_delta_mm": 0.0, "snapped": False})
            continue
        order = np.argsort(np.abs(ws - a))
        near = float(ws[order[0]])
        delta = abs(near - a)
        if delta > snap_tol:
            raise ValueError(
                f"锚点 w={a} 在数据集中无精确值且最近邻 {near:.9f} "
                f"(Δ={delta:.3e}mm) 超出吸附容差 {snap_tol}——嵌套 DoE "
                f"不成立，拒绝出计划（先核对数据集）")
        if ws.size > 1:
            second = float(ws[order[1]])
            if abs(abs(second - a) - delta) <= 1e-12:
                raise ValueError(f"锚点 w={a} 吸附候选并列（{near:.9f} / "
                                 f"{second:.9f}）——拒绝猜测")
        out.append({"nominal": a, "run": near,
                    "snap_delta_mm": delta, "snapped": True})
    return out


def select_heldout_ws(dataset_ws: list[float],
                      ranges: tuple[tuple[float, float], ...] = HELDOUT_RANGES,
                      ) -> list[dict[str, float]]:
    """held-out 锚：每个区间取数据集精确值中最靠近区间中点的一个。

    只在数据集既有值里选（嵌套 DoE + 基线臂同 w 精确配对）；区间内无
    候选 → ValueError。
    """
    ws = np.asarray(dataset_ws, dtype=float)
    out: list[dict[str, float]] = []
    for lo, hi in ranges:
        lo, hi = float(lo), float(hi)
        mid = (lo + hi) / 2.0
        inside = ws[(ws >= lo) & (ws <= hi)]
        if inside.size == 0:
            raise ValueError(f"held-out 区间 [{lo},{hi}] 内数据集无既有值"
                             f"——拒绝在区间外选点（任务口径红线）")
        pick = float(inside[np.argmin(np.abs(inside - mid))])
        out.append({"nominal": mid, "run": pick,
                    "snap_delta_mm": float(abs(pick - mid)), "snapped": False,
                    "range": [lo, hi]})
    return out


def resolve_extra_anchor_ws(dataset_ws: list[float],
                            extra_ws: tuple[float, ...],
                            excluded_ws: tuple[float, ...] = (),
                            ) -> list[dict[str, float]]:
    """补充锚（--extra-w）：吸附到数据集精确既有值（嵌套 DoE 前提）。

    与 resolve_anchor_ws 的 SNAP_TOL 吸附不同：补充锚直接取**最近数据集
    精确值**（KOH 修正模型 _exact_low_row 要求锚 w 与低保真行精确相等，
    EXACT_W_TOL=1e-12——超出 SNAP_TOL 的名义值也必须落在数据集既有值上，
    否则 fit 阶段拒绝）；excluded_ws（既有锚值，含 held-out 门点）从候选
    剔除——门点不入训练（gate 独立性，anchor15_criteria.md §1）。
    候选空 → ValueError。
    """
    ws_all = np.asarray(dataset_ws, dtype=float)
    cands_all = ws_all
    if excluded_ws:
        exc = np.asarray(excluded_ws, dtype=float)
        d_min = np.min(np.abs(ws_all[:, None] - exc[None, :]), axis=1)
        cands_all = ws_all[d_min > 1e-9]
    out: list[dict[str, float]] = []
    for a in extra_ws:
        a = float(a)
        if cands_all.size == 0:
            raise ValueError(f"补充锚 w={a}：剔除既有锚后数据集无候选")
        near = float(cands_all[np.argmin(np.abs(cands_all - a))])
        out.append({"nominal": a, "run": near,
                    "snap_delta_mm": float(abs(near - a)), "snapped": True})
    return out


def build_anchor_plan(dataset_ws: list[float],
                      full: bool = False,
                      extra_ws: tuple[float, ...] = (),
                      ) -> list[dict[str, Any]]:
    """锚点计划（纯函数）：train 基础(+可选+补充 --extra-w) + held-out。"""
    resolved = resolve_anchor_ws(dataset_ws)
    if full:
        resolved += resolve_anchor_ws(dataset_ws, OPTIONAL_ANCHORS)
    heldout = select_heldout_ws(dataset_ws)
    if extra_ws:
        resolved += resolve_extra_anchor_ws(
            dataset_ws, tuple(extra_ws),
            excluded_ws=tuple(r["run"] for r in resolved + heldout))
    used: dict[str, float] = {}
    plan: list[dict[str, Any]] = []
    for row in resolved + heldout:
        w_run = float(row["run"])
        pid = point_id_for_w(w_run, used)
        used[pid] = w_run
        group = "heldout" if "range" in row else "train"
        plan.append({
            "point_id": pid,
            "group": group,
            "w_mm_nominal": float(row["nominal"]),
            "w_mm": w_run,
            "snap_delta_mm": float(row["snap_delta_mm"]),
            "snapped": bool(row["snapped"]),
            "line_len_mm": LINE_LEN_MM,
        })
    return plan


def load_dataset_ws(dataset_dir: Path = DATASET_DIR) -> list[float]:
    """merged 数据集的 w_mm 清单（--audit/--collect 共用的嵌套前提）。"""
    import pandas as pd

    df = pd.read_parquet(Path(dataset_dir) / "points.parquet")
    ws = [float(json.loads(p)["w_mm"]) for p in df["params_json"]]
    if not ws:
        raise ValueError(f"{dataset_dir}: 数据集无行")
    return ws


# ─── HFSS 面（真跑；离线 --audit 不触） ──────────────────────────────────────

# 桌面治理单源：原 _list_ansysedt_processes/_process_alive/
# _kill_desktops 三函数（原型）已上收 src/rfauto/infra/desktop_guard.py，
# 语义不变（活桌面不杀 fail-closed/孤儿点杀/枚举失败不杀，#245/#265）；
# 本模块顶部 alias `_kill_desktops` 供 run_collect 调用与既有测试兼容。

def _eps_eff_from_phase_slope(slope_per_hz: float,
                              l_span_mm: float) -> float:
    """S21 相位斜率 → εeff（hfss_mline_probe.py:199 同式，L=实测跨度）。"""
    return float((slope_per_hz * C0 / (-2 * np.pi * l_span_mm * 1e-3)) ** 2)


def _audit_geometry(h: Any, w_mm: float, line_len_mm: float) -> dict[str, Any]:
    """端口面/连通性/外边界审计断言（#364② 红线①；solve 前拦几何错误）。

    get_face_center 返回模型单位（mm，#285）——本设计 model_units=mm，
    与 mm 常量直接比较。
    """
    half = line_len_mm / 2.0
    centers: list[list[float]] = []
    for name in ("P1sheet", "P2sheet"):
        faces = h.modeler.get_object_faces(name)
        if not faces:
            raise AssertionError(f"{name}: 无面可取（端口片未建成）")
        fc = h.modeler.get_face_center(faces[0])
        centers.append([float(v) for v in fc])
    l_span = abs(centers[1][1] - centers[0][1])
    # 断言 1（核心）：实测端口面跨度 == 名义 line_len（端口面=线端、无馈段）
    assert abs(l_span - line_len_mm) <= SPAN_ASSERT_TOL_MM, (
        f"端口面实测跨度 {l_span:.9f}mm != 名义 line_len {line_len_mm}mm "
        f"(tol {SPAN_ASSERT_TOL_MM})——参考面几何与设计不符（#364② 红线："
        f"εeff 必须用实测跨度，且此处名义==实测必须成立才可采信）")
    # 断言 2：两端口片 x 居中（sheet 左缘 -2.5w，宽 5w → 中心 0）、y 在线端
    for c in centers:
        assert abs(c[0]) <= SPAN_ASSERT_TOL_MM, (
            f"端口片 x 中心 {c[0]:.9f}mm 非零——端口片横向错位")
        assert abs(abs(c[1]) - half) <= SPAN_ASSERT_TOL_MM, (
            f"端口面 y={c[1]:.6f}mm 与线端 ±{half} 不符")
    # 断言 3：line y 向贯通跨度 == L_span（线端触及两端口面，#336 精神）
    bbox = [float(v) for v in h.modeler.get_object_bounding_box("Line")]
    line_span = bbox[4] - bbox[1]
    assert abs(line_span - l_span) <= SPAN_ASSERT_TOL_MM, (
        f"line y 向跨度 {line_span:.9f}mm != 端口面跨度 {l_span:.9f}mm"
        f"——线未贯通到端口面（开路 stub 风险，#174 族）")
    # 断言 4：空气盒 y 向与端口面齐平（端口在外边界，#191）
    air = [float(v) for v in h.modeler.get_object_bounding_box("Air")]
    assert abs(air[1] - (-half)) <= SPAN_ASSERT_TOL_MM and \
        abs(air[4] - half) <= SPAN_ASSERT_TOL_MM, (
        f"空气盒 y 范围 [{air[1]:.6f},{air[4]:.6f}] 与端口面 ±{half} 不齐平"
        f"——端口变内部端口（#191 实证 solve 必败）")
    audit = {
        "L_span_mm": l_span,
        "nominal_span_mm": line_len_mm,
        "span_assert_tol_mm": SPAN_ASSERT_TOL_MM,
        "span_assert_pass": True,
        "port_face_centers_mm": centers,
        "line_bbox_mm": bbox,
        "air_bbox_mm": air,
        "w_mm_port_sizing": {"w_factor": PORT_W_FACTOR,
                             "h_factor": PORT_H_FACTOR,
                             "x_factor": PORT_X_FACTOR},
        "note": ("L 口径=两端口面实测几何跨度（get_face_center，mm，#285）；"
                 "hfss_mline_probe.py L_TOTAL 同口径（其探针 80mm）。"
                 "本几何端口面=线端、无馈段，名义==实测由断言钉住。"),
    }
    print(f"[mfa] 几何审计 PASS：L_span={l_span:.6f}mm（名义 {line_len_mm}），"
          f"端口面中心 {centers}", flush=True)
    return audit


def _build_line_model(h: Any, w_mm: float, line_len_mm: float) -> None:
    """均匀微带线模型（hfss_mline_probe.py 同款，line_len 参数化）。"""
    from ansys.aedt.core.generic.constants import Gravity

    from rfauto.adapters.hfss_builder_utils import Quantity

    er_h = SUBSTRATE["h_mm"]
    half = line_len_mm / 2.0
    x_half = X_HALF_MM
    h.modeler.model_units = "mm"
    h.materials.add_material(MATERIAL_NAME, properties={
        "permittivity": SUBSTRATE["er"],
        "dielectric_loss_tangent": SUBSTRATE["tan_d"]})
    # 几何一律预计算浮点+显式单位（#218）
    h.modeler.create_box(
        origin=[f"{-x_half}mm", f"{-half}mm", "0mm"],
        sizes=[f"{2 * x_half}mm", f"{line_len_mm}mm", f"{er_h}mm"],
        name="Sub", material=MATERIAL_NAME)
    h.modeler.create_box(
        origin=[f"{-w_mm / 2}mm", f"{-half}mm", f"{er_h}mm"],
        sizes=[f"{w_mm}mm", f"{line_len_mm}mm", "0mm"],
        name="Line", material="pec")
    h.modeler.create_box(
        origin=[f"{-x_half}mm", f"{-half}mm", "0mm"],
        sizes=[f"{2 * x_half}mm", f"{line_len_mm}mm", "0mm"],
        name="Gnd", material="pec")
    # PEC 薄片必须 PerfectE（#356①：零厚盒 material="pec" 不导电）
    h.assign_perfecte_to_sheets(assignment=["Line"], name="LinePEC")
    h.assign_perfecte_to_sheets(assignment=["Gnd"], name="GndPEC")
    # 波端口要求贴面介质 solve-inside（#191 实证）
    h.modeler["Sub"].solve_inside = True
    # 空气盒 y 向不留边距（端口在外边界）+ subtract 重叠体（#191 实证）
    h.modeler.create_box(
        origin=[f"{-(x_half + X_MARGIN_MM)}mm", f"{-half}mm", "0mm"],
        sizes=[f"{2 * x_half + 2 * X_MARGIN_MM}mm", f"{line_len_mm}mm",
               f"{er_h + X_MARGIN_MM}mm"],
        name="Air", material="vacuum")
    h.modeler.subtract("Air", ["Sub", "Line"])
    h.modeler["Air"].solve_inside = True
    air_faces = h.modeler.get_object_faces("Air")
    open_faces = []
    for f in air_faces:
        cx, cy, cz = h.modeler.get_face_center(f)
        if abs(abs(cy) - half) < 1e-6:
            continue  # y 侧端面与波端口同面（端口+辐射同面不支持，#191）
        if abs(cz - (er_h + X_MARGIN_MM)) < 1e-6 or \
                abs(abs(cx) - (x_half + X_MARGIN_MM)) < 1e-6:
            open_faces.append(f)
    h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")
    # 波端口：官方尺寸（宽 5w / 高 4·sub_h，#192）；Quantity 量纲安全（#218）
    for name, y_mm in (("P1sheet", -half), ("P2sheet", half)):
        port_w = PORT_W_FACTOR * Quantity.mm(w_mm)
        port_h = PORT_H_FACTOR * Quantity.mm(er_h)
        port_x0 = PORT_X_FACTOR * Quantity.mm(w_mm)
        h.modeler.create_rectangle(
            orientation="ZX",
            origin=[port_x0.to_hfss(), Quantity.mm(y_mm).to_hfss(), "0mm"],
            sizes=[port_h.to_hfss(), port_w.to_hfss()],
            name=name)
        port_face = h.modeler.get_object_faces(name)[0]
        h.wave_port(assignment=port_face, name=name + "P", impedance=50.0,
                    renormalize=True, integration_line=Gravity.ZPos)


def _collect_point(pt: dict[str, Any], out_dir: Path,
                   aedt_version: str) -> dict[str, Any]:
    """单锚点 HFSS 真跑（探针同款整轮会话：new_desktop 起、finally 释放）。

    覆盖已有点目录（resume 语义在调用层：status=done 的点根本不进来）。
    """
    import skrf
    from ansys.aedt.core import Hfss

    from rfauto.adapters.hfss_adapter import HfssAdapter

    w = float(pt["w_mm"])
    line_len = float(pt["line_len_mm"])
    out_dir.mkdir(parents=True, exist_ok=True)
    h = None
    t0 = time.time()
    try:
        h = Hfss(project=str(out_dir / f"{pt['point_id']}.aedt"),
                 design="mfa", version=aedt_version, non_graphical=True,
                 new_desktop=True)
        _build_line_model(h, w, line_len)
        audit = _audit_geometry(h, w, line_len)

        setup = h.create_setup(name="Setup")
        setup.props["Frequency"] = f"{FREQ_CENTER_GHZ}GHz"
        setup.props["MaxDeltaS"] = SETUP_MAX_DELTA_S
        setup.props["MaximumPasses"] = SETUP_MAX_PASSES
        setup.update()
        h.create_linear_count_sweep(
            setup="Setup", unit="GHz", start_frequency=BAND_GHZ[0],
            stop_frequency=BAND_GHZ[1], num_of_freq_points=SWEEP_POINTS,
            name="Sweep", sweep_type="Discrete", save_fields=False)
        t_solve = time.time()
        # E-MED-5：solve 看门狗（超时 fail-closed 不再等待，线程留守；
        # fn 异常原样透传不冒充超时——desktop_guard.run_with_watchdog）
        run_with_watchdog(
            lambda: h.analyze(setup="Setup"),
            timeout_s=SOLVE_TIMEOUT_S,
            what=f"{pt['point_id']} Setup solve",
            log=print)
        solve_s = time.time() - t_solve

        adapter = HfssAdapter()
        adapter.session.hfss = h
        s2p = adapter.export_touchstone(out_dir / "sparams.s2p")

        net = skrf.network.Network(str(s2p))
        f = net.f
        s11 = net.s[:, 0, 0]
        s21 = net.s[:, 1, 0] if net.s.shape[2] >= 2 else net.s[:, 0, 0]
        m11 = 20 * np.log10(np.abs(s11) + 1e-12)
        s11_min = float(np.min(m11))
        phase = np.unwrap(np.angle(s21))
        slope = float(np.polyfit(f, phase, 1)[0])
        assert slope < 0.0, (
            f"S21 相位斜率 {slope:.3e} rad/Hz 非负——端口序/解缠异常，"
            f"拒绝采信（先审计再入账，#1b）")
        l_span = float(audit["L_span_mm"])
        eps_eff = _eps_eff_from_phase_slope(slope, l_span)
        # 物理窗守卫：εr=3.66 微带族 εeff 越界 → 几何/判读必有问题（#1b）
        assert EPS_PHYS_WINDOW[0] <= eps_eff <= EPS_PHYS_WINDOW[1], (
            f"eps_eff={eps_eff:.4f} 超出物理窗 {EPS_PHYS_WINDOW}"
            f"——几何或端口判读异常，拒绝落 done")
        band = (f >= BAND_GHZ[0] * 1e9) & (f <= BAND_GHZ[1] * 1e9)
        anchor: dict[str, Any] = {
            "schema": "factory_mf_anchor/1",
            "point_id": pt["point_id"],
            "group": pt["group"],
            "w_mm_nominal": pt["w_mm_nominal"],
            "w_mm": w,
            "snap_delta_mm": pt["snap_delta_mm"],
            "line_len_mm": line_len,
            "status": "done",
            "freq_ghz_span": [BAND_GHZ[0], BAND_GHZ[1]],
            "sweep_points": SWEEP_POINTS,
            "sweep_type": "Discrete",
            "eps_eff_slope_span": eps_eff,
            "eps_eff_method": ("S21 相位斜率，L=实测端口面跨度 "
                               f"{l_span:.6f}mm（audit 块）"),
            "s21_phase_slope_rad_per_hz": slope,
            "s11_min_db": s11_min,
            "s11_min_freq_ghz": float(f[int(np.argmin(m11))] / 1e9),
            "s21_db_at_center": float(20 * np.log10(
                np.abs(s21[band][len(band[band]) // 2]) + 1e-12)),
            "audit": audit,
            "touchstone": "sparams.s2p",
            "aedt_version": aedt_version,
            "substrate": dict(SUBSTRATE),
            "solved_at": datetime.now(UTC).isoformat(),
            "wall_s": round(time.time() - t0, 1),
            "solve_s": round(solve_s, 1),
        }
        if s11_min > -6.0:
            anchor["health_note"] = (
                f"s11_min={s11_min:.2f}dB 偏高（w={w} 时 Z0 失配贡献为主），"
                f"如实留痕；门判读在 rejudge 侧做")
        (out_dir / "anchor.json").write_text(
            json.dumps(anchor, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"[mfa] {pt['point_id']} done：eps_eff={eps_eff:.4f} "
              f"s11_min={s11_min:.2f}dB solve={solve_s:.0f}s", flush=True)
        return anchor
    finally:
        if h is not None:
            # E-MED-5：release 带 150s 上限（hfss_interdigital_check 口径：
            # 看门狗超时后 release 会对求解中的桌面阻塞到自然结束，实测
            # 3.6h——超时不候，孤儿风险留 #265/#245 人工处置）
            release_desktop_capped(
                lambda: h.release_desktop(close_projects=True,
                                          close_desktop=True),
                log=print)


def run_collect(full: bool, aedt_version: str,
                extra_ws: tuple[float, ...] = (),
                log=print) -> int:
    """批量采集（逐点 3 次整轮重试；done 点跳过——断点续跑幂等）。"""
    plan = build_anchor_plan(load_dataset_ws(), full=full,
                             extra_ws=tuple(extra_ws))
    index_path = ROOT / "collect_index.json"
    index: dict[str, Any] = {}
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    log(f"[mfa] 计划 {len(plan)} 点（train "
        f"{sum(1 for p in plan if p['group'] == 'train')} / heldout "
        f"{sum(1 for p in plan if p['group'] == 'heldout')}）；"
        f"断点续跑跳过已 done 点")
    n_ok = n_fail = 0
    for pt in plan:
        pid = str(pt["point_id"])
        row = index.get(pid)
        if isinstance(row, dict) and row.get("status") == "done":
            n_ok += 1
            log(f"[mfa] {pid} 已 done（断点续跑跳过）")
            continue
        out_dir = ROOT / pid
        last_exc: Exception | None = None
        for attempt in range(1, POINT_ATTEMPTS + 1):
            try:
                _kill_desktops(log=log)
                _collect_point(pt, out_dir, aedt_version)
                index[pid] = {"status": "done", "w_mm": pt["w_mm"],
                              "group": pt["group"]}
                n_ok += 1
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                log(f"[mfa] {pid} attempt {attempt}/{POINT_ATTEMPTS} FAIL: "
                    f"{exc}")
        if last_exc is not None:
            index[pid] = {"status": "failed",
                          "msg": str(last_exc)[:300],
                          "group": pt["group"]}
            n_fail += 1
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    log(f"[mfa] 采集收尾：done={n_ok} failed={n_fail} "
        f"(root={ROOT})")
    if n_fail:
        log("[mfa] 存在失败点：rejudge 侧按实际锚点数如实判读"
            "（train<2 时拒绝拟合）")
    return 0 if n_fail == 0 else 1


def run_audit(full: bool, extra_ws: tuple[float, ...] = ()) -> int:
    """离线预检：锚点表 + 嵌套吸附 + εeff 口径审计说明（无 HFSS）。"""
    ws = load_dataset_ws()
    try:
        plan = build_anchor_plan(ws, full=full, extra_ws=tuple(extra_ws))
    except ValueError as exc:
        print(f"[mfa][audit] 预检 FAIL: {exc}")
        return 1
    print("===== 锚点计划（嵌套 DoE，全部 line_len=40mm） =====")
    print(f"{'point_id':<12} {'group':<8} {'w_nominal':>10} "
          f"{'w_run':>18} {'snapΔ(mm)':>12}")
    for pt in plan:
        print(f"{pt['point_id']:<12} {pt['group']:<8} "
              f"{pt['w_mm_nominal']:>10.4f} {pt['w_mm']:>18.12f} "
              f"{pt['snap_delta_mm']:>12.3e}")
    print("\n===== εeff 参考面跨度口径审计（#364② 红线①） =====")
    print("hfss_mline_probe.py L_TOTAL 口径 = 两端口面实测几何跨度")
    print("（该探针 line 贯通 y∈[-40,40]，L_TOTAL=80=实测跨度，端面即端口")
    print("面、无馈段）。本脚本 line 贯通 y∈[-20,+20]（line_len=40），")
    print("εeff 一律用 get_face_center 实测跨度 L_span 代入斜率式；断言：")
    print(f"  |L_span − line_len| ≤ {SPAN_ASSERT_TOL_MM}mm（solve 前拦下）")
    print("  + 端口片 x 居中 + line 贯通==L_span + 空气盒与端口面齐平")
    print("  + 解出 εeff ∈ {EPS_PHYS_WINDOW}（越界即几何可疑）".replace(
        "{EPS_PHYS_WINDOW}", str(EPS_PHYS_WINDOW)))
    print(f"\nDiscrete 扫频 {BAND_GHZ}GHz {SWEEP_POINTS} 点；"
          f"setup MaxDeltaS={SETUP_MAX_DELTA_S} "
          f"MaximumPasses={SETUP_MAX_PASSES}")
    print(f"s2p 落盘 {ROOT}/<point_id>/sparams.s2p；"
          f"finally release_desktop（#265）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="B2 多保真 HFSS 稀疏锚点采集（--audit 离线预检 / "
                    "--collect 真机）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--audit", action="store_true",
                       help="离线：打印锚点表+审计口径（无 HFSS）")
    group.add_argument("--collect", action="store_true",
                       help="HFSS 真跑（主代理排机；断点续跑幂等）")
    ap.add_argument("--full", action="store_true",
                    help="加入可选训练锚 {0.745, 1.182}")
    ap.add_argument("--extra-w", type=float, nargs="+", default=(),
                    help="补充训练锚（名义 w 列表；吸附最近数据集精确值，"
                         "剔除既有锚含 held-out 门点；补锚收尾）")
    ap.add_argument("--aedt-version", type=str, default=AEDT_VERSION_DEFAULT)
    args = ap.parse_args(argv)
    if args.audit:
        return run_audit(args.full, extra_ws=tuple(args.extra_w))
    return run_collect(args.full, args.aedt_version,
                       extra_ws=tuple(args.extra_w))


if __name__ == "__main__":
    raise SystemExit(main())
