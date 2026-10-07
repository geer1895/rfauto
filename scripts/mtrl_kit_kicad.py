"""SMA-PCB-mTRL-kit 式校准件 KiCad 生成器（F-A P2 尾件）。

单板多区块：THRU / REFLECT / LINE1 / LINE2 [+ RING 环形谐振器样片]，
每区块 SMA 双端焊盘（launch）+ 50Ω 微带段；B.Cu 整块地平面；板框
（Edge.Cuts 矩形）+ 四角 M3 安装孔。输出 KiCad 10 ``.kicad_pcb``。

上游参考（机制借镜，零文件拷贝）：ZiadHatab/SMA-PCB-mTRL-kit（BSD），
[A5] 出处见 研究扩充 F-A §3。

确定性设计链（LLM/脚本永不手写射频毫米数，#1c）：
- 50Ω 线宽 = ``core.synthesis.inverse_width``（skrf MLine
  Hammerstad-Jensen 正向 + brentq 反解），er/h/f0 全参数化；
- εeff 用**相速口径**（β 直取：(β·c0/ω)²，见 ``_er_eff_phase``）：
  实测 skrf MLine 的 ``ep_reff`` 属性（``synthesis.forward_z0`` 主路径
  返回值）是准静态值，与 β/``ep_reff_f`` 相速口径差 ~3.9%
  （FR4 er=4.4/h=1.6/5GHz/w=3.11mm 例：3.3357 vs 3.4659）；介质提取链
  （``dielectric_extract._mline_ep_reff``→``ep_reff_f``）与环谐振公式
  均按相速口径工作，设计端同口径才满足互逆自洽（坑登记 #118 族：
  "同模型口径"声明须属性级核对）；
- λg(f) = c0/(f·√εeff_phase(f))；
- 线长组合（mTRL 多模态基判据，预声明）：ΔL = L2−L1 = λg(f0)/4
  （"≈λg/4@带心"按构造恒等）；覆盖判据 ΔL ≥ λg(f_hi)/4（带缘多模态
  覆盖，违反即 ValueError 拒绝出图）。上界参考：经典经验规则
  ΔL < λg(f_hi)/2 在 f_hi=2·f0 且含色散时边缘性超出（~0.6%，色散使
  λg(f_hi) 略小于 λg(f0)/2）——两线 mTRL 的 2πn 根选择由 er_est 序列
  与频率连续性消歧（skrf NISTMultilineTRL 口径，见
  ``core.dielectric_extract.extract_gamma_mtrl``），该上界只报告不设门；
- Thru 物理长度取机械最小（THRU_MID_MM，DRC 间隙约束，非射频量），
  提取端参考面约定 skrf ``l=[0, …]``（thru 定义零长度基准）；
- Reflect = 单端 launch + 短 50Ω 段 + 端头方形开路焊盘（开路标准，
  相位偏移由 reflect 标准的 g_refl 相位估计吸收，不进线长判据）；
- RING：环平均周长 = n·λg（Joler 2022 Sensors 口径，与
  ``core.dielectric_extract.ring_resonator_f0_to_er`` 提取链互逆），
  n=1 谐振在 f0 → r_mean = c0/(2π·f0·√εeff(f0))；环线宽 = 同一 50Ω
  线宽；耦合缝是耦合结构设计量（非 50Ω 线宽，不属 #1c HJ 精算域），
  ``--ring-gap-mm`` 显式参数化（缺省 0.3mm），仿真域闭环（G2）校准。

运行方式：项目 venv 下独立运行（``.venv/Scripts/python.exe
scripts/mtrl_kit_kicad.py …``）；KiCad 面一律子进程调用 KiCad 自带
Python 3.11。

DFM 挂点：``--dfm`` 调 service ``check_design_dfm``（jlcpcb 剖面默认）
查线宽/钻孔/板厚，core ``check_gaps`` 同剖面补检缝宽（间距），
输出剖面门报告（#105：best-effort，不阻塞出图）。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from rfauto.core.synthesis import Stackup, inverse_width

C0 = 299792458.0  # m/s（与 core.dielectric_extract 同值）

# KiCad 面优先级：env RFAUTO_KICAD_PYTHON > 默认安装位（#275 模式）
KICAD_PYTHON_DEFAULT = r"E:\KiCad\bin\python.exe"
KICAD_SITE_PACKAGES = r"E:\KiCad\bin\Lib\site-packages"

# ─── 机械/工艺常量（launch/间隙/板框——非射频线宽；射频线宽一律 HJ #1c）───
Z0_TARGET_OHM = 50.0
PAD_L_MM = 3.0          # launch 信号焊盘长
GND_W_MM = 2.0          # launch 地焊盘宽
GND_GAP_MM = 0.5        # 信号-地焊盘间隙
GND_VIA_DRILL_MM = 0.6  # 地焊盘接地孔
GND_VIA_PAD_MM = 1.2
MOUNT_DRILL_MM = 3.2    # M3 安装孔
MOUNT_PAD_MM = 6.0
THRU_MID_MM = 0.6       # thru 直通段（DRC 间隙约束的最小机械长度）
REFLECT_TRACK_MM = 3.0  # reflect 开路段 50Ω 短线
ROW_CLEAR_MM = 5.0      # 区块行间距
BOARD_MARGIN_MM = 10.0  # 板缘留白
MOUNT_INSET_MM = 5.0    # 安装孔中心距板缘
RING_SEGMENTS = 72      # 环折线段数（弦长 < 线宽，视觉/制造连续）
RING_GAP_DEFAULT_MM = 0.3

BLOCK_RF = ("THRU", "REFLECT", "LINE1", "LINE2")


def _er_eff_phase(er: float, w_mm: float, h_mm: float, f_ghz: float) -> float:
    """相速口径 εeff = (β·c0/ω)²（skrf MLine HJ 正向 β 直取）。

    刻意不用 ``synthesis.forward_z0`` 返回的 εeff：其主路径读 ``ep_reff``
    属性（准静态值），与 β/``ep_reff_f`` 相速口径在 FR4@5GHz 差 ~3.9%
    （3.3357 vs 3.4659 实测）。介质提取链（``dielectric_extract``
    →``ep_reff_f``）与环形谐振器公式均按相速口径工作，设计端必须同口径
    （#118 族：正向模型"同口径"声明必须属性级核对，不能信 docstring）。
    """
    import skrf

    mline = skrf.media.MLine(
        frequency=skrf.Frequency(float(f_ghz), float(f_ghz), 1, unit="GHz"),
        w=float(w_mm) * 1e-3,
        h=float(h_mm) * 1e-3,
        ep_r=float(er),
        tand=0.0,
        model="hammerstadjensen",
    )
    beta = float(mline.beta[0].real)
    omega = 2.0 * math.pi * float(f_ghz) * 1e9
    return (beta * C0 / omega) ** 2


# ─── 设计计算（确定性内核，零 IO）─────────────────────────────────────────────

def compute_design(
    er: float,
    h_mm: float,
    f0_ghz: float,
    f_hi_ghz: float | None = None,
    *,
    with_ring: bool = False,
    ring_gap_mm: float = RING_GAP_DEFAULT_MM,
) -> dict[str, Any]:
    """计算校准件全套设计参数（mm；线宽 HJ 精算，判据见模块 docstring）。

    Returns:
        dict：w_mm / z0_actual_ohm / er_eff / λg / ΔL / 线长 / ring / 版图。

    Raises:
        ValueError: 物理或判据违规（er≤1、h≤0、频率非法、带缘覆盖不足）。
        RuntimeError: HJ 反解未自洽（needs_calibration）。
    """
    if not (float(er) > 1.0):
        raise ValueError(f"er 必须 >1（收到 {er}）")
    if not (float(h_mm) > 0.0):
        raise ValueError(f"h_mm 必须 >0（收到 {h_mm}）")
    if not (float(f0_ghz) > 0.0):
        raise ValueError(f"f0_ghz 必须 >0（收到 {f0_ghz}）")
    f_hi = float(f_hi_ghz) if f_hi_ghz is not None else 2.0 * float(f0_ghz)
    if not (f_hi > f0_ghz):
        raise ValueError(f"f_hi_ghz 必须 > f0_ghz（{f_hi} <= {f0_ghz}）")
    if with_ring and not (float(ring_gap_mm) > 0.0):
        raise ValueError(f"ring_gap_mm 必须 >0（收到 {ring_gap_mm}）")

    stackup = Stackup(
        name=f"kit_er{er:g}_h{h_mm:g}", epsilon_r=float(er), thickness_mm=float(h_mm)
    )
    w_mm, z0_actual, status = inverse_width(Z0_TARGET_OHM, f0_ghz, stackup)
    if status != "ok":
        raise RuntimeError(
            f"50Ω 线宽 HJ 反解未自洽（status={status}, z0={z0_actual:.2f}Ω）"
            "——er/h 组合超出模型适用域，拒绝出图"
        )
    er_eff_f0 = _er_eff_phase(er, w_mm, h_mm, f0_ghz)
    er_eff_fhi = _er_eff_phase(er, w_mm, h_mm, f_hi)

    lam_g0_mm = C0 / (f0_ghz * 1e9 * math.sqrt(er_eff_f0)) * 1e3
    lam_g_hi_mm = C0 / (f_hi * 1e9 * math.sqrt(er_eff_fhi)) * 1e3
    delta_l_mm = lam_g0_mm / 4.0
    # 预声明多模态基覆盖判据：ΔL ≥ λg(f_hi)/4
    coverage_ratio = delta_l_mm / lam_g_hi_mm
    if coverage_ratio < 0.25:
        raise ValueError(
            f"线长差 ΔL={delta_l_mm:.3f}mm 不满足带缘覆盖判据 "
            f"ΔL ≥ λg(f_hi)/4={lam_g_hi_mm / 4.0:.3f}mm（ratio={coverage_ratio:.3f}）"
            "——mTRL 多模态基不足，拒绝出图"
        )
    # 经典上界参考（只报告不设门，理由见模块 docstring）
    upper_ratio = delta_l_mm / (lam_g_hi_mm / 2.0)

    design: dict[str, Any] = {
        "er": float(er),
        "h_mm": float(h_mm),
        "f0_ghz": float(f0_ghz),
        "f_hi_ghz": f_hi,
        "w_mm": w_mm,
        "z0_target_ohm": Z0_TARGET_OHM,
        "z0_actual_ohm": z0_actual,
        "er_eff_f0": er_eff_f0,
        "er_eff_fhi": er_eff_fhi,
        "lam_g0_mm": lam_g0_mm,
        "lam_g_hi_mm": lam_g_hi_mm,
        "delta_l_mm": delta_l_mm,
        "coverage_ratio": coverage_ratio,
        "upper_ratio": upper_ratio,
        "thru_mid_mm": THRU_MID_MM,
        "reflect_track_mm": REFLECT_TRACK_MM,
        "line1_mid_mm": delta_l_mm,
        "line2_mid_mm": 2.0 * delta_l_mm,
        "ring": None,
    }
    if with_ring:
        r_mean_mm = C0 / (2.0 * math.pi * f0_ghz * 1e9 * math.sqrt(er_eff_f0)) * 1e3
        design["ring"] = {
            "r_mean_mm": r_mean_mm,
            "r_out_mm": r_mean_mm + w_mm / 2.0,
            "gap_mm": float(ring_gap_mm),
            "n_harmonic": 1,
        }
    _layout(design)
    return design


def _rf_row_height(w_mm: float) -> float:
    """RF 区块行高：信号线 + 上下（间隙 + 地焊盘）。"""
    return w_mm + 2.0 * (GND_GAP_MM + GND_W_MM)


def _layout(design: dict[str, Any]) -> None:
    """纵向堆叠各区块行（左对齐 x0=MARGIN），写回 design["rows"]/板尺寸。"""
    w = design["w_mm"]
    ring = design["ring"]

    specs: list[dict[str, Any]] = []
    specs.append({"name": "THRU", "mid": design["thru_mid_mm"], "h": _rf_row_height(w)})
    specs.append(
        {
            "name": "REFLECT",
            "mid": None,  # 单端开路结构，len 单独算
            "h": _rf_row_height(w),
            "len": PAD_L_MM + design["reflect_track_mm"] + w,
        }
    )
    specs.append({"name": "LINE1", "mid": design["line1_mid_mm"], "h": _rf_row_height(w)})
    specs.append({"name": "LINE2", "mid": design["line2_mid_mm"], "h": _rf_row_height(w)})
    if ring is not None:
        specs.append(
            {
                "name": "RING",
                "mid": None,
                "h": 2.0 * ring["r_out_mm"] + 2.0,
                "len": 2.0 * ring["r_out_mm"] + 2.0 * ring["gap_mm"] + 4.0 * PAD_L_MM,
            }
        )

    rows: list[dict[str, Any]] = []
    y = BOARD_MARGIN_MM
    for spec in specs:
        length = spec["len"] if spec["mid"] is None else 2.0 * PAD_L_MM + spec["mid"]
        rows.append(
            {
                "name": spec["name"],
                "x0": BOARD_MARGIN_MM,
                "y0": y,
                "x1": BOARD_MARGIN_MM + length,
                "y1": y + spec["h"],
                "yc": y + spec["h"] / 2.0,
            }
        )
        y += spec["h"] + ROW_CLEAR_MM
    design["rows"] = rows
    design["board_w_mm"] = max(r["x1"] for r in rows) + BOARD_MARGIN_MM
    design["board_h_mm"] = rows[-1]["y1"] + BOARD_MARGIN_MM


# ─── 版图 → 绘制指令序列（与 pcbnew 解耦，纯数据可测）────────────────────────

def build_ops(design: dict[str, Any]) -> list[dict[str, Any]]:
    """版图 → 绘制指令序列（track/rect/via/text，mm 坐标，KiCad 无关）。"""
    ops: list[dict[str, Any]] = []
    w = design["w_mm"]

    def launch(cx: float, yc: float) -> None:
        """一组 SMA launch：信号焊盘 + 上下地焊盘 + 接地孔。"""
        ops.append(
            {
                "op": "rect",
                "x1": cx - PAD_L_MM / 2.0,
                "y1": yc - w / 2.0,
                "x2": cx + PAD_L_MM / 2.0,
                "y2": yc + w / 2.0,
                "layer": "F_Cu",
                "filled": True,
            }
        )
        for sign in (-1.0, 1.0):
            gy = yc + sign * (w / 2.0 + GND_GAP_MM + GND_W_MM / 2.0)
            ops.append(
                {
                    "op": "rect",
                    "x1": cx - PAD_L_MM / 2.0,
                    "y1": gy - GND_W_MM / 2.0,
                    "x2": cx + PAD_L_MM / 2.0,
                    "y2": gy + GND_W_MM / 2.0,
                    "layer": "F_Cu",
                    "filled": True,
                }
            )
            ops.append(
                {
                    "op": "via",
                    "x": cx,
                    "y": gy,
                    "drill": GND_VIA_DRILL_MM,
                    "pad": GND_VIA_PAD_MM,
                }
            )

    for row in design["rows"]:
        yc = row["yc"]
        # 每行 B.Cu 整块地平面（50Ω 微带参考地）
        ops.append(
            {
                "op": "rect",
                "x1": row["x0"],
                "y1": row["y0"],
                "x2": row["x1"],
                "y2": row["y1"],
                "layer": "B_Cu",
                "filled": True,
            }
        )
        name = row["name"]
        if name in ("THRU", "LINE1", "LINE2"):
            launch(row["x0"] + PAD_L_MM / 2.0, yc)
            launch(row["x1"] - PAD_L_MM / 2.0, yc)
            ops.append(
                {
                    "op": "track",
                    "x1": row["x0"] + PAD_L_MM / 2.0,
                    "y1": yc,
                    "x2": row["x1"] - PAD_L_MM / 2.0,
                    "y2": yc,
                    "w": w,
                    "layer": "F_Cu",
                }
            )
        elif name == "REFLECT":
            launch(row["x0"] + PAD_L_MM / 2.0, yc)
            xe = row["x0"] + PAD_L_MM + design["reflect_track_mm"]
            ops.append(
                {
                    "op": "track",
                    "x1": row["x0"] + PAD_L_MM / 2.0,
                    "y1": yc,
                    "x2": xe,
                    "y2": yc,
                    "w": w,
                    "layer": "F_Cu",
                }
            )
            # 端头方形开路焊盘（Reflect = 开路标准）
            ops.append(
                {
                    "op": "rect",
                    "x1": xe - w / 2.0,
                    "y1": yc - w / 2.0,
                    "x2": xe + w / 2.0,
                    "y2": yc + w / 2.0,
                    "layer": "F_Cu",
                    "filled": True,
                }
            )
        elif name == "RING":
            ring = design["ring"]
            r_mean = ring["r_mean_mm"]
            gap = ring["gap_mm"]
            xc = (row["x0"] + row["x1"]) / 2.0
            launch(row["x0"] + PAD_L_MM / 2.0, yc)
            launch(row["x1"] - PAD_L_MM / 2.0, yc)
            for side in (-1.0, 1.0):
                # 耦合焊盘中心=环带外缘+r_outer+gap：焊盘近缘距环外缘恰为
                # gap（审查轨 B P1-3：旧式差 w/2 致焊盘嵌入环金属=短路 stub）
                xf = xc + side * (r_mean + w + gap)
                ops.append(
                    {
                        "op": "track",
                        "x1": row["x0"] + PAD_L_MM / 2.0 if side < 0 else row["x1"] - PAD_L_MM / 2.0,
                        "y1": yc,
                        "x2": xf,
                        "y2": yc,
                        "w": w,
                        "layer": "F_Cu",
                    }
                )
                ops.append(
                    {
                        "op": "rect",
                        "x1": xf - w / 2.0,
                        "y1": yc - w / 2.0,
                        "x2": xf + w / 2.0,
                        "y2": yc + w / 2.0,
                        "layer": "F_Cu",
                        "filled": True,
                    }
                )
            # 环体：折线逼近圆（弦长 < 线宽，连续无缝）
            n = RING_SEGMENTS
            for i in range(n):
                a1 = 2.0 * math.pi * i / n
                a2 = 2.0 * math.pi * (i + 1) / n
                ops.append(
                    {
                        "op": "track",
                        "x1": xc + r_mean * math.cos(a1),
                        "y1": yc + r_mean * math.sin(a1),
                        "x2": xc + r_mean * math.cos(a2),
                        "y2": yc + r_mean * math.sin(a2),
                        "w": w,
                        "layer": "F_Cu",
                    }
                )
        # 丝印区块名（行上方）
        ops.append(
            {
                "op": "text",
                "x": (row["x0"] + row["x1"]) / 2.0,
                "y": row["y0"] - 1.2,
                "s": name,
            }
        )

    # 板框（Edge.Cuts 矩形；KiCad 10 BoardOutline() 返回裸 SwigPyObject 不可用）
    ops.append(
        {
            "op": "rect",
            "x1": 0.0,
            "y1": 0.0,
            "x2": design["board_w_mm"],
            "y2": design["board_h_mm"],
            "layer": "Edge_Cuts",
            "filled": False,
            "lw": 0.01,
        }
    )
    # 四角 M3 安装孔
    for mx, my in (
        (MOUNT_INSET_MM, MOUNT_INSET_MM),
        (design["board_w_mm"] - MOUNT_INSET_MM, MOUNT_INSET_MM),
        (MOUNT_INSET_MM, design["board_h_mm"] - MOUNT_INSET_MM),
        (design["board_w_mm"] - MOUNT_INSET_MM, design["board_h_mm"] - MOUNT_INSET_MM),
    ):
        ops.append({"op": "via", "x": mx, "y": my, "drill": MOUNT_DRILL_MM, "pad": MOUNT_PAD_MM})
    # 标题丝印
    ops.append(
        {
            "op": "text",
            "x": design["board_w_mm"] / 2.0,
            "y": design["board_h_mm"] - 3.0,
            "s": (
                f"SMA-PCB mTRL kit  er={design['er']:g}  h={design['h_mm']:g}mm  "
                f"f0={design['f0_ghz']:g}GHz  W50={design['w_mm']:.3f}mm"
            ),
        }
    )
    return ops


# ─── KiCad 子进程生成（KiCad 自带 Python 3.11， 规则 2）────────────────

# 生成器脚本在 KiCad Python 下运行：只依赖 pcbnew/json/sys，纯 ASCII
# （规避跨版本/跨区域编码面）；几何全部经 JSON 传入。
_BUILDER_SOURCE = r'''
import json
import sys

sys.path.insert(0, r"__KICAD_SITE_PACKAGES__")
import pcbnew

NM = 1000000  # 1 mm = 1e6 nm（KiCad 内部单位）


def V(x_mm, y_mm):
    return pcbnew.VECTOR2I(int(round(x_mm * NM)), int(round(y_mm * NM)))


def main():
    with open(sys.argv[1], encoding="utf-8") as fh:
        spec = json.load(fh)
    board = pcbnew.BOARD()
    for op in spec["ops"]:
        kind = op["op"]
        if kind == "track":
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(V(op["x1"], op["y1"]))
            t.SetEnd(V(op["x2"], op["y2"]))
            t.SetWidth(int(round(op["w"] * NM)))
            t.SetLayer(getattr(pcbnew, op["layer"]))
            board.Add(t)
        elif kind == "rect":
            s = pcbnew.PCB_SHAPE(board)
            s.SetShape(pcbnew.SHAPE_T_RECT)
            s.SetStart(V(op["x1"], op["y1"]))
            s.SetEnd(V(op["x2"], op["y2"]))
            s.SetLayer(getattr(pcbnew, op["layer"]))
            s.SetWidth(int(round(op.get("lw", 0.0) * NM)))
            if op.get("filled"):
                s.SetFilled(True)
            board.Add(s)
        elif kind == "via":
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(V(op["x"], op["y"]))
            v.SetDrill(int(round(op["drill"] * NM)))
            v.SetWidth(int(round(op["pad"] * NM)))
            board.Add(v)
        elif kind == "text":
            t = pcbnew.PCB_TEXT(board)
            t.SetText(op["s"])
            t.SetPosition(V(op["x"], op["y"]))
            t.SetLayer(pcbnew.F_SilkS)
            t.SetTextSize(pcbnew.VECTOR2I(int(1.0 * NM), int(1.0 * NM)))
            t.SetTextThickness(int(0.15 * NM))
            board.Add(t)
        else:
            raise ValueError("unknown op: %r" % kind)
    board.Save(spec["out"])
    print("SAVED " + spec["out"])


main()
'''


def resolve_kicad_python(explicit: str | None = None) -> str | None:
    """KiCad Python 解析：显式参 > env RFAUTO_KICAD_PYTHON > 默认安装位。"""
    for cand in (explicit, os.environ.get("RFAUTO_KICAD_PYTHON"), KICAD_PYTHON_DEFAULT):
        if cand and Path(cand).is_file():
            return cand
    return None


def generate_kicad_pcb(
    design: dict[str, Any],
    out_dir: str | Path,
    *,
    kicad_python: str | None = None,
) -> dict[str, Any]:
    """子进程调用 KiCad Python 生成 .kicad_pcb（返回 ok/stdout/stderr/path）。"""
    if kicad_python and not Path(kicad_python).is_file():
        # 显式路径无效 = 意图明确 → 硬报错，不静默回退安装位（#277 三态精神）
        return {
            "ok": False,
            "errors": [f"--kicad-python 显式路径不存在: {kicad_python}"],
        }
    exe = resolve_kicad_python(kicad_python)
    if exe is None:
        return {
            "ok": False,
            "errors": [
                "KiCad Python 不可达（ tried: --kicad-python / env "
                "RFAUTO_KICAD_PYTHON / " + KICAD_PYTHON_DEFAULT + " ）——"
                "安装 KiCad 或降级只跑 --dry-run（设计参数面零 KiCad 依赖）"
            ],
        }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "mtrl_kit.kicad_pcb"
    spec = {"out": str(out_path), "ops": build_ops(design)}
    builder_src = _BUILDER_SOURCE.replace("__KICAD_SITE_PACKAGES__", KICAD_SITE_PACKAGES)

    tmp_dir = Path(tempfile.mkdtemp(prefix="mtrlkit_"))
    try:
        spec_path = tmp_dir / "mtrlkit_spec.json"
        builder_path = tmp_dir / "mtrlkit_builder.py"
        spec_path.write_text(json.dumps(spec, ensure_ascii=True), encoding="utf-8")
        builder_path.write_text(builder_src, encoding="utf-8")
        proc = subprocess.run(
            [exe, str(builder_path), str(spec_path)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        ok = proc.returncode == 0 and out_path.is_file()
        return {
            "ok": ok,
            "path": str(out_path),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
            "kicad_python": exe,
            "errors": [] if ok else [f"KiCad 子进程失败 rc={proc.returncode}"],
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def verify_kicad_pcb_opens(path: str | Path, *, kicad_python: str | None = None) -> dict[str, Any]:
    """KiCad LoadBoard 回读验证（实测可打开；#331：以引擎读回为准）。"""
    if kicad_python and not Path(kicad_python).is_file():
        return {"ok": False, "errors": [f"--kicad-python 显式路径不存在: {kicad_python}"]}
    exe = resolve_kicad_python(kicad_python)
    if exe is None:
        return {"ok": False, "errors": ["KiCad Python 不可达"]}
    code = (
        "import sys; sys.path.insert(0, r'" + KICAD_SITE_PACKAGES + "'); "
        "import pcbnew; b = pcbnew.LoadBoard(r'" + str(path) + "'); "
        "print('TRACKS', len(list(b.GetTracks())))"
    )
    proc = subprocess.run([exe, "-c", code], capture_output=True, text=True, timeout=120)
    ok = proc.returncode == 0 and "TRACKS" in proc.stdout
    return {
        "ok": ok,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "errors": [] if ok else ["LoadBoard 回读失败"],
    }


# ─── DFM 挂点（service fab_check 面 + core 缝宽补检，#105 best-effort）────────

def design_to_dfm_dict(design: dict[str, Any]) -> dict[str, Any]:
    """设计 → PCBDesign-dict（service.check_design_dfm 入参契约，mm）。"""
    vias = [{"drill": GND_VIA_DRILL_MM, "pad": GND_VIA_PAD_MM},
            {"drill": MOUNT_DRILL_MM, "pad": MOUNT_PAD_MM}]
    return {
        "traces": [{"width": design["w_mm"]}],
        "vias": vias,
        "copper_oz": 1.0,
        "board_thickness_mm": design["h_mm"],
    }


def run_dfm(design: dict[str, Any], *, profile: str = "jlcpcb") -> dict[str, Any]:
    """DFM 剖面门：service check_design_dfm（线宽/钻孔/板厚）+ 缝宽补检。

    best-effort（#105）：任何异常 → ``{"ran": False, "errors": [...]}`` 留痕，
    不阻塞主路径。
    """
    gaps_mm = [GND_GAP_MM]
    if design["ring"] is not None:
        gaps_mm.append(design["ring"]["gap_mm"])
    try:
        from rfauto.core.fab_check import check_gaps, load_profile
        from rfauto.service.fab_service import check_design_dfm

        report = check_design_dfm(design_to_dfm_dict(design), profile=profile)
        report["gap_violations"] = check_gaps(
            gaps_mm, load_profile(profile), copper_oz=1.0
        )
        report["gaps_mm"] = gaps_mm
        report["profile"] = profile
        return report
    except Exception as exc:  # best-effort 观测面不得阻塞出图（#105）
        return {"ran": False, "ok": None, "errors": [f"DFM 门异常: {exc}"]}


# ─── CLI ─────────────────────────────────────────────────────────────────────

def format_params_table(design: dict[str, Any]) -> str:
    """设计参数表（--dry-run 人读面）。"""
    lines = [
        "== SMA-PCB mTRL kit 设计参数表 ==",
        (
            f"er={design['er']:g}  h={design['h_mm']:g}mm  "
            f"f0={design['f0_ghz']:g}GHz  f_hi={design['f_hi_ghz']:g}GHz"
        ),
        (
            f"Z0={design['z0_target_ohm']:g}ohm -> w={design['w_mm']:.4f}mm "
            f"(HJ 回代 {design['z0_actual_ohm']:.2f}ohm)"
        ),
        (
            f"er_eff(f0)={design['er_eff_f0']:.4f}  "
            f"er_eff(f_hi)={design['er_eff_fhi']:.4f}"
        ),
        (
            f"lambda_g(f0)={design['lam_g0_mm']:.3f}mm  "
            f"lambda_g(f_hi)={design['lam_g_hi_mm']:.3f}mm"
        ),
        (
            f"delta_L=lambda_g(f0)/4={design['delta_l_mm']:.3f}mm  "
            f"coverage(dL/lg_hi)={design['coverage_ratio']:.3f} (>=0.25 required)  "
            f"upper(dL/(lg_hi/2))={design['upper_ratio']:.3f} (info only)"
        ),
        (
            f"THRU mid={design['thru_mid_mm']:g}mm  "
            f"LINE1 mid={design['line1_mid_mm']:.3f}mm  "
            f"LINE2 mid={design['line2_mid_mm']:.3f}mm  "
            f"REFLECT track={design['reflect_track_mm']:g}mm"
        ),
    ]
    if design["ring"] is not None:
        ring = design["ring"]
        lines.append(
            f"RING r_mean={ring['r_mean_mm']:.3f}mm  r_out={ring['r_out_mm']:.3f}mm  "
            f"gap={ring['gap_mm']:g}mm  n={ring['n_harmonic']}"
        )
    rows = "  ".join(
        f"{r['name']}[{r['x1'] - r['x0']:.1f}x{r['y1'] - r['y0']:.1f}]"
        for r in design["rows"]
    )
    lines.append(f"blocks: {rows}")
    lines.append(
        f"board: {design['board_w_mm']:.1f} x {design['board_h_mm']:.1f} mm"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mtrl_kit_kicad",
        description="SMA-PCB-mTRL-kit 式校准件 KiCad 生成器（线宽 HJ 精算）",
    )
    parser.add_argument("--out", default=None, help="输出目录（.kicad_pcb 落盘处）")
    parser.add_argument("--er", type=float, default=4.4, help="基板相对介电常数")
    parser.add_argument("--h-mm", type=float, default=1.6, help="基板厚度 mm")
    parser.add_argument("--f0-ghz", type=float, default=5.0, help="设计带心频率 GHz")
    parser.add_argument(
        "--f-hi-ghz", type=float, default=None,
        help="带缘频率 GHz（缺省 2*f0；覆盖判据 ΔL>=λg(f_hi)/4 在此校验）",
    )
    parser.add_argument("--with-ring", action="store_true", help="加 RING 环形谐振器样片")
    parser.add_argument(
        "--ring-gap-mm", type=float, default=RING_GAP_DEFAULT_MM,
        help="环耦合缝 mm（耦合结构设计量，G2 仿真域校准）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只打印设计参数表（含 MTRLKIT_PARAMS_JSON 行），不写任何文件",
    )
    parser.add_argument("--dfm", action="store_true", help="生成后跑 fab 剖面 DFM 门")
    parser.add_argument(
        "--profile", default="jlcpcb", help="DFM 剖面名（缺省 jlcpcb）"
    )
    parser.add_argument(
        "--kicad-python", default=None,
        help="KiCad 自带 Python 路径（缺省 env RFAUTO_KICAD_PYTHON 或安装位）",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="生成后用 KiCad LoadBoard 回读验证（实测可打开）",
    )
    args = parser.parse_args(argv)

    design = compute_design(
        args.er,
        args.h_mm,
        args.f0_ghz,
        args.f_hi_ghz,
        with_ring=args.with_ring,
        ring_gap_mm=args.ring_gap_mm,
    )
    print(format_params_table(design))
    params = {k: v for k, v in design.items() if k != "rows"}
    print("MTRLKIT_PARAMS_JSON: " + json.dumps(params, ensure_ascii=False))

    if args.dfm:
        report = run_dfm(design, profile=args.profile)
        print("DFM_REPORT_JSON: " + json.dumps(report, ensure_ascii=False, default=str))

    if args.dry_run:
        return 0
    if not args.out:
        parser.error("--out 必填（除非 --dry-run）")

    result = generate_kicad_pcb(design, args.out, kicad_python=args.kicad_python)
    for line in (result.get("stdout") or "").strip().splitlines():
        print(line)
    if not result["ok"]:
        for err in result.get("errors", []):
            print(err, file=sys.stderr)
        if result.get("stderr"):
            print(result["stderr"], file=sys.stderr)
        return 1
    print(f"OK -> {result['path']}")

    if args.verify:
        check = verify_kicad_pcb_opens(result["path"], kicad_python=args.kicad_python)
        print("VERIFY_JSON: " + json.dumps(check, ensure_ascii=False))
        if not check["ok"]:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
