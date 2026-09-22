"""C7：gysel mitered-jog 切角旋钮真机 A/B（离线面+真机编排，marchand_via_ab 同骨架）。

登记语境（排空五轮 followUps "gysel 弯折等效长度/mitered-jog 再
一轮真机"）：gysel L-jog 等长变体（P2⑪，runs/gysel_smoke/pt3）真跑 S32@f0
-38.1dB，电路级 ≤-88dB 增益被 EM 地板吃掉大半（归因假设待证 #122：两处未切角
90° 弯折等效长度/弯角寄生）。IC67 已落 `_jog_miter_mm` opt-in 旋钮
（adapters/openems_templates._gysel_layout/_gysel_jog_lines：每侧 jog 转角外
上角 c×c 台阶缺口，45° miter 切角的阶梯网格单步近似；缺省 0=未切角基线渲染
逐字节不变）。本对照回答：**切角对隔离深度的真实改善量**（假设方向：切角→
隔离改善即 |S23| 负得更多/带内更平稳；方向相反也如实落档）。

A/B 口径（渲染单源 render_script("gysel", ...)，两变体唯一差异=jog 段原语+
缺口缘网格线；off=不带旋钮键=烟测口径逐字节同源，仅一条注释行随 #313 文档化
与 runs/gysel_smoke/pt3/simulation.py 漂移——FDTD 输入零差异）：
  off = _jog_miter_mm 缺省（不传键）——A 臂基线（=pt3 复跑）
  on  = _jog_miter_mm=0.2——B 臂切角档
c=0.2mm 的选择（预声明，网格相撞约束）：缺口缘 x=±(XA+W_F/2−c) 与既有桥带缘
x=±(XB+W_F/2) 间距=jog−c=0.412−c、缺口顶缘 y=YJ+W_F/2−c 与负载盒缘
YJ+G/2 间距=(W_F−G)/2−c=0.3067−c；c≥0.3 时后者塌到 6.7µm、c=0.4 时前者塌到
12µm——#152 族 CFL 时间步塌缩（离线 exec 实测 dt 因子 7.7×/4.3×），预算不可
行。c=0.2 为两约束下最大档（min span 53.4µm、dt 因子 1.26×，实测）。

用法（cwd=仓库根）：
  python scripts/gysel_miter_ab.py --plan      # 两变体渲染+exec 几何审计（离线零仿真）
  python scripts/gysel_miter_ab.py --collect   # A/B 两轮 openEMS 真跑（共享锁+#261+resume）
  python scripts/gysel_miter_ab.py --judge     # A/B 差值表+如实判读（离线）

预算预声明（criteria.md 同源，起跑前写死）：单轮继承 gysel 烟测口径（mesh
0.4mm、扫频 2.25-2.75GHz 401 点、NrTS 缺省 100000+缺省能量判据停机）；单轮
历史参考 wall=pt3 6926s（并发批嫌疑，solo 预期更低）；单轮硬超时 90min、两轮
名义 ≤2h，**PARTIAL 门=1.5×（3h，到点停）**；共享锁 runs/.oe_collect.lock
（O_CREAT|O_EXCL、30s 轮询、30min 上限 fail-closed、陈锁 pid 接管）+#261 命令
行互斥查（自身名 gysel_miter_ab 不入模式——#261 自锁坑）；断点 resume=
collect_ok.json 逐变体幂等。

判读（G11 掩码纪律）：gysel 9 列 CSV=部分矩阵——S11/S21/S31 出自激励 1 run、
S23 出自激励 3 run（双激励 footer），S12/S13/S22/S32/S33 未测不判、互易补齐
不使用。主量=ΔS32@f0（on−off）：≤−1dB 改善 / |Δ|<1dB 持平 / ≥+1dB 恶化；
带内平稳性副量=Δband_max_S32 ≤−0.5dB；护栏（miter 不得破坏匹配/均分）：ΔS11@f0
≥+3dB 或 |Δsplit|≥0.5dB 记 SIDE_EFFECT 如实列账。

退出码：0=门过/完成；1=门未达/执行失败；2=参数错误。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

# ─── 预声明常量（criteria.md 同源；改判读先改 criteria 再改这里） ──────────────
ROOT = REPO / "runs" / "gysel_miter_ab"
PLAN_PATH = ROOT / "plan.json"
CRITERIA_PATH = ROOT / "criteria.md"
VERDICT_PATH = ROOT / "verdict.json"
COLLECT_STATE_PATH = ROOT / "collect_state.json"
LOCK_PATH = REPO / "runs" / ".oe_collect.lock"
LOCK_POLL_S = 30.0
LOCK_MAX_WAIT_S = 30.0 * 60.0       # 忙等上限，超时 fail-closed

VARIANTS: tuple[str, ...] = ("off", "on")
MITER_C_MM = 0.2                    # B 臂切角档（网格相撞约束下最大档，见模块头）
FREQ_RANGE_GHZ = (2.25, 2.75)       # gysel 烟测口径继承（footer 401 点）
NF = 401
MESH_MM = 0.4                       # 烟测收敛档
F0_GHZ = 2.5
GYS_PARAMS: dict[str, float] = {"w_arm_mm": 0.6035, "w_feed_mm": 1.1134,
                                "arm_len_mm": 18.162, "iso_len_mm": 17.75}
SOLVE_TIMEOUT_S = 90.0 * 60.0       # 单轮硬超时
BUDGET_WALL_S = 2.0 * 60.0 * 60.0   # 两轮名义预算
PARTIAL_FACTOR = 1.5                # 超 1.5×（3h）→ PARTIAL 停
#: gysel 烟测历史 wall（runs/gysel_smoke/pt*_pass.log；pt3 含并发拖慢嫌疑）
PT3_REF_WALL_S = 6926
PT2_REF_WALL_S = 1702

#: 判读阈值（预声明，judge/ab_table 单测钉）
IMPROVE_MAX_DB = -1.0               # ΔS32@f0 ≤ −1dB → 改善
STABILITY_DELTA_DB = -0.5           # Δband_max_S32 ≤ −0.5dB → 带内更平稳
SIDE_EFFECT_S11_DB = 3.0            # ΔS11@f0 ≥ +3dB → 匹配护栏
SIDE_EFFECT_SPLIT_DB = 0.5          # |Δ均分差| ≥ 0.5dB → 均分护栏
MESH_MIN_SPAN_M = 40e-6             # exec 审计门（#152 族；c=0.2 实测 53.4µm）
DT_FACTOR_MAX = 1.5                 # on/off CFL dt 因子门（c=0.2 实测 1.26）

#: gysel 烟测硬门（runs/gysel_smoke 判据，逐臂如实判定非本 A/B 主判）
GATE_BETA_PCT = 2.0
GATE_SPLIT_DB = 0.5
GATE_S32_DB = -15.0
GATE_S11_DB = -10.0
H_SUB_MM, ER, TAND = 0.508, 3.66, 0.0037   # _DEFAULT_SUB（rogers4350b_h0.508）

#: pt3 基线（runs/gysel_smoke/pt3_pass.log 原文；off 臂应为同轮复现锚）
PT3_BASELINE = {"s32_db": -38.1, "s32_min_db": -52.5, "s32_min_f_ghz": 2.451,
                "s11_db": -25.0, "beta_delta_pct": 0.94}


# ─── 纯逻辑（单测钉死面，零引擎零 IO） ────────────────────────────────────────

def strip_variant_specific(text: str) -> str:
    """剥离两变体唯一差异段（近点两行+jog 段），余下应逐字节相等。

    差异段契约：① ``_near_x =``/``_near_y =`` 两行（缺口缘网格线）；
    ② ``# 顶端 L-jog 横移段`` 注释起、``# 顶边桥带`` 注释止的 jog 原语块。
    """
    kept: list[str] = []
    in_jog = False
    for ln in text.splitlines():
        if ln.startswith("_near_x =") or ln.startswith("_near_y ="):
            continue
        if ln.startswith("# 顶端 L-jog 横移段"):
            in_jog = True
            continue
        if in_jog and ln.startswith("# 顶边桥带"):
            in_jog = False
        if in_jog:
            continue
        kept.append(ln)
    return "\n".join(kept) + "\n"


def parse_jog_boxes(text: str) -> list[tuple[float, float, float, float]]:
    """切角档渲染文本中具体数字 jog 盒 (x0, y0, x1, y1)（符号式盒跳过）。"""
    import re

    boxes = []
    for m in re.finditer(r"gysel\.AddBox\(\(([^)]+)\),\s*\n\s*\(([^)]+)\),",
                         text):
        try:
            x0, y0 = (float(v) for v in m.group(1).split(",")[:2])
            x1, y1 = (float(v) for v in m.group(2).split(",")[:2])
        except ValueError:
            continue
        boxes.append((x0, y0, x1, y1))
    return boxes


def notch_audit(text: str, c_mm: float = MITER_C_MM) -> dict[str, Any]:
    """on 臂缺口几何断言（IC67 语义复算）：8 盒、带并集=原 jog 减两缺口。

    缺口语义（_gysel_jog_lines）：每侧 jog 段拆主段（全高）+缺口段（降高 c），
    转角外上角 c×c 台阶缺口；带并集=金属并集恒等（竖直段/桥带/端口不动）。
    渲染盒坐标=米（脚本主体同单位；2026-09-21 A/B 审计修正 mm 字面量后）。
    """
    n_box = text.count("gysel.AddBox")
    boxes = parse_jog_boxes(text)
    wf = GYS_PARAMS["w_feed_mm"] * 1e-3
    yj = 17.338e-3
    c = c_mm * 1e-3
    lo_full = (min(GYS_PARAMS["arm_len_mm"], GYS_PARAMS["iso_len_mm"])
               - GYS_PARAMS["w_feed_mm"] / 2) * 1e-3
    hi_full = (max(GYS_PARAMS["arm_len_mm"], GYS_PARAMS["iso_len_mm"])
               + GYS_PARAMS["w_feed_mm"] / 2) * 1e-3

    def _union_len(ivs: list[tuple[float, float]]) -> float:
        ivs = sorted(ivs)
        total, lo, hi = 0.0, ivs[0][0], ivs[0][1]
        for a, b in ivs[1:]:
            if a > hi:
                total += hi - lo
                lo, hi = a, b
            else:
                hi = max(hi, b)
        return total + hi - lo

    band_lo = _union_len([(b[0], b[2]) for b in boxes
                          if b[1] <= yj - wf / 2 + 1e-9
                          and b[3] >= yj + wf / 2 - c - 1e-9])
    band_top = _union_len([(b[0], b[2]) for b in boxes
                           if b[1] <= yj + wf / 2 - c + 1e-9
                           and b[3] >= yj + wf / 2 - 1e-9])
    flush = GYS_PARAMS["arm_len_mm"] * 1e-3 + wf / 2   # 内移档缺口贴竖直段外缘
    flush_ok = any(abs(x1 - flush) < 1e-9
                   and abs(x0 - (flush - c)) < 1e-9
                   and abs(y1 - (yj + wf / 2 - c)) < 1e-9
                   for x0, _y0, x1, y1 in boxes)
    checks = {
        "boxes_8": bool(n_box == 8),
        "jog_boxes_4": bool(len(boxes) == 4),
        "band_lo_full": bool(abs(band_lo - 2.0 * (hi_full - lo_full)) < 1e-9),
        "band_top_cut_2c": bool(abs(band_top - 2.0 * (hi_full - lo_full - c))
                                < 1e-9),
        "notch_flush_outcorner": bool(flush_ok),
    }
    return {"c_mm": c_mm, "checks": checks,
            "all_pass": bool(all(checks.values()))}


def expected_jog_boxes_m(c_mm: float = MITER_C_MM) -> list[list[float]]:
    """on 臂 jog 段 4 盒的期望坐标（米，_gysel_layout 派生；script 语境=米）。

    每侧拆主段（全高）+缺口段（降高 c）：缺口贴竖直段外缘（内移档
    xb<xa）、自角点 x=±(XA+W_F/2) 向 jog 远端延伸 c。供 plan 对 exec 后
    CSX 金属原语坐标逐值断言（渲染文本字面量=mm、脚本语境=米，单位错会
    在此显式红——#212 离线审计抓画法错误的制度化面）。
    """
    wf = GYS_PARAMS["w_feed_mm"] * 1e-3
    xa = GYS_PARAMS["arm_len_mm"] * 1e-3
    xb = GYS_PARAMS["iso_len_mm"] * 1e-3
    yj = (GYS_PARAMS["iso_len_mm"] - abs(GYS_PARAMS["arm_len_mm"]
                                         - GYS_PARAMS["iso_len_mm"])) * 1e-3
    c = c_mm * 1e-3
    out = []
    for s in (1.0, -1.0):
        m1, m2 = sorted((s * min(xa, xb), s * max(xa, xb)))
        jlo, jhi = m1 - wf / 2, m2 + wf / 2
        cx = s * (xa + wf / 2)          # 内移档（xb<xa）：缺口贴外缘
        nlo, nhi = sorted((cx, cx - s * c))
        mlo, mhi = (nhi, jhi) if abs(nlo - jlo) < 1e-12 else (jlo, nlo)
        out.append([mlo, yj - wf / 2, mhi, yj + wf / 2])
        out.append([nlo, yj - wf / 2, nhi, yj + wf / 2 - c])
    return out


def metal_boxes_xy_m(scope: dict[str, Any]) -> list[list[float]]:
    """exec 后 scope["CSX"] 的 gysel 金属盒 (x0, y0, x1, y1)（米，min/max 归一）。"""
    import numpy as np

    csx = scope["CSX"]
    out: list[list[float]] = []
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        if str(prop.GetTypeString()) != "Metal" or str(prop.GetName()) != "gysel":
            continue
        for prim in prop.GetAllPrimitives():
            if not hasattr(prim, "GetStart"):
                continue
            s = np.asarray(prim.GetStart(), dtype=float)
            e = np.asarray(prim.GetStop(), dtype=float)
            out.append([float(min(s[0], e[0])), float(min(s[1], e[1])),
                        float(max(s[0], e[0])), float(max(s[1], e[1]))])
    return out


def exec_mesh_audit(path: Path, text: str) -> dict[str, Any]:
    """离线 exec 网格审计（零仿真；FDTD.Run 截断口径，#212/#312 同法）。

    读终网格三轴最小间距/线数 + CFL dt 估计（1/(c·√Σ1/dᵢ²)，磁导率=1）；
    守卫 MESH_MIN_SPAN_M（#152 族：缺口缘与既有缘相撞塌 dt）。标准渲染路径
    无 audit dict，网格从 exec 后 scope["mesh"] 实测。
    """
    import numpy as np

    cut = text.index("FDTD.Run(")
    scope: dict[str, Any] = {"__name__": "__main__", "__file__": str(path)}
    exec(compile(text[:cut], str(path), "exec"), scope)
    mesh = scope.get("mesh")
    if mesh is None:
        raise RuntimeError("exec 后无 mesh（渲染契约破坏？）")
    min_span: dict[str, float] = {}
    n_lines: dict[str, int] = {}
    for ax in "xyz":
        ls = np.asarray(mesh.GetLines(ax), dtype=float)
        min_span[ax] = float(np.min(np.diff(ls)))
        n_lines[ax] = len(ls)
    dt = 1.0 / (299792458.0 * math.sqrt(sum(1.0 / v ** 2 for v in
                                            min_span.values())))
    boxes = metal_boxes_xy_m(scope)
    in_domain = bool(boxes) and all(abs(v) <= 0.0601 for b in boxes for v in b)
    return {"min_span_m": min_span, "mesh_lines": n_lines, "dt_cfl_s": dt,
            "min_span_ge_40um": bool(all(v >= MESH_MIN_SPAN_M
                                         for v in min_span.values())),
            "metal_boxes_xy_m": boxes, "metal_in_domain": in_domain}


def load_sparams(path: Path) -> dict[str, Any]:
    """gysel 9 列 CSV → freq + 复数 S（#314 掩码口径：只读已测 4 元素）。"""
    import numpy as np

    with open(path, encoding="utf-8") as fh:
        header = fh.readline().strip().split(",")
    if len(header) != 9:
        raise ValueError(
            f"gysel sparams.csv 须 9 列（freq+4 复数，G11 宽度守卫），"
            f"得 {len(header)} 列：{header[:12]}")
    d = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    if d.shape[1] != 9:
        raise ValueError(f"gysel sparams.csv 数据宽度 {d.shape[1]}≠9")
    return {"f_ghz": d[:, 0] / 1e9,
            "s11": d[:, 1] + 1j * d[:, 2],
            "s21": d[:, 3] + 1j * d[:, 4],
            "s31": d[:, 5] + 1j * d[:, 6],
            "s23": d[:, 7] + 1j * d[:, 8]}


def metrics(sp: dict[str, Any], f0_ghz: float = F0_GHZ) -> dict[str, Any]:
    """隔离口指标（judge_gysel_ljog 口径扩展带内 max/min；确定性内核复算）。"""
    import numpy as np

    def _db(x):
        return 20.0 * np.log10(np.abs(x) + 1e-300)

    f = sp["f_ghz"]
    i0 = int(np.argmin(np.abs(f - f0_ghz)))
    s11db, s21db = _db(sp["s11"]), _db(sp["s21"])
    s31db, s23db = _db(sp["s31"]), _db(sp["s23"])
    i_iso = int(np.argmin(s23db))
    i_m = int(np.argmin(s11db))
    phase = np.degrees(np.angle(sp["s21"][i0] * np.conj(sp["s31"][i0])))
    return {
        "nf": len(f),
        "at_f0": {"f_ghz": float(f[i0]),
                  "s11_db": float(s11db[i0]), "s21_db": float(s21db[i0]),
                  "s31_db": float(s31db[i0]), "s32_db": float(s23db[i0]),
                  "split_diff_db": float(s21db[i0] - s31db[i0]),
                  "phase_diff_deg": float(phase)},
        "iso": {"min_db": float(np.min(s23db)),
                "min_f_ghz": float(f[i_iso]),
                "offset_pct": float(100.0 * (f[i_iso] - f0_ghz) / f0_ghz),
                "band_max_db": float(np.max(s23db))},
        "match": {"min_db": float(np.min(s11db)),
                  "min_f_ghz": float(f[i_m]),
                  "offset_pct": float(100.0 * (f[i_m] - f0_ghz) / f0_ghz)},
        "band_edges": {
            "lo": {"f_ghz": float(f[0]), "s32_db": float(s23db[0]),
                   "s11_db": float(s11db[0])},
            "hi": {"f_ghz": float(f[-1]), "s32_db": float(s23db[-1]),
                   "s11_db": float(s11db[-1])}},
        "s11_passive_violation_pts": int(np.sum(np.abs(sp["s11"]) > 1.05)),
        "s23_passive_violation_pts": int(np.sum(np.abs(sp["s23"]) > 1.05)),
    }


def ab_table(m_off: dict[str, Any], m_on: dict[str, Any]) -> dict[str, Any]:
    """A/B 差值表（主量 ΔS32@f0；带内对照；护栏量），结论分支预声明。"""
    rows: list[dict[str, Any]] = []

    def row(key: str, label: str, off: float, on: float) -> None:
        rows.append({"metric": key, "label": label, "unit": "dB",
                     "off": round(float(off), 3), "on": round(float(on), 3),
                     "delta": round(float(on) - float(off), 3)})

    a0, b0 = m_off["at_f0"], m_on["at_f0"]
    ao, bo = m_off["iso"], m_on["iso"]
    ae, be = m_off["band_edges"], m_on["band_edges"]
    row("s32_f0", "S32@f0（隔离深度·主量）", a0["s32_db"], b0["s32_db"])
    row("s32_min", "S32 带内谷深（#195 s23 口径）", ao["min_db"], bo["min_db"])
    row("s32_band_max", "S32 带内最差点（平稳性副量）",
        ao["band_max_db"], bo["band_max_db"])
    row("s32_edge_lo", "S32@2.3GHz 带边", ae["lo"]["s32_db"],
        be["lo"]["s32_db"])
    row("s32_edge_hi", "S32@2.7GHz 带边", ae["hi"]["s32_db"],
        be["hi"]["s32_db"])
    row("s11_f0", "S11@f0（护栏）", a0["s11_db"], b0["s11_db"])
    row("s21_f0", "S21@f0", a0["s21_db"], b0["s21_db"])
    row("s31_f0", "S31@f0", a0["s31_db"], b0["s31_db"])
    d_main = float(rows[0]["delta"])
    d_stab = float(rows[2]["delta"])
    d_s11 = float(rows[5]["delta"])
    d_split = float(b0["split_diff_db"]) - float(a0["split_diff_db"])
    if d_main <= IMPROVE_MAX_DB:
        concl = "MITER_IMPROVES(隔离主量改善)"
    elif d_main >= -IMPROVE_MAX_DB:
        concl = "MITER_WORSENS(隔离主量恶化)"
    else:
        concl = "MITER_NEUTRAL(隔离主量持平)"
    stability = ("STABLE_IMPROVED(带内最差点更低)" if d_stab <= STABILITY_DELTA_DB
                 else "STABLE_WORSENED" if d_stab >= -STABILITY_DELTA_DB
                 else "STABLE_NEUTRAL")
    side_effects: list[str] = []
    if d_s11 >= SIDE_EFFECT_S11_DB:
        side_effects.append(f"S11 护栏（Δ={d_s11:+.2f}dB ≥ +{SIDE_EFFECT_S11_DB}）")
    if abs(d_split) >= SIDE_EFFECT_SPLIT_DB:
        side_effects.append(
            f"均分护栏（Δsplit={d_split:+.2f}dB ≥ ±{SIDE_EFFECT_SPLIT_DB}）")
    return {"rows": rows, "delta_s32_f0_db": round(d_main, 3),
            "delta_s32_band_max_db": round(d_stab, 3),
            "delta_s11_f0_db": round(d_s11, 3),
            "delta_split_diff_db": round(d_split, 3),
            "conclusion": concl, "stability": stability,
            "side_effects": side_effects,
            "thresholds": {"improve_max_db": IMPROVE_MAX_DB,
                           "stability_delta_db": STABILITY_DELTA_DB,
                           "side_effect_s11_db": SIDE_EFFECT_S11_DB,
                           "side_effect_split_db": SIDE_EFFECT_SPLIT_DB}}


def beta_eps_eff(path: Path, f0_ghz: float = F0_GHZ) -> dict[str, Any]:
    """port_beta.csv → @f0 εeff（β 金标准，#162；advisory 非门）。"""
    import numpy as np

    d = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    i0 = int(np.argmin(np.abs(d[:, 0] / 1e9 - f0_ghz)))
    beta = float(d[i0, 1])
    eps = float((beta * 299792458.0 / (2.0 * math.pi * d[i0, 0])) ** 2)
    return {"beta_rad_m": beta, "eps_eff": eps}


def hj_eps_eff(w_mm: float, f0_ghz: float = F0_GHZ) -> float:
    from rfauto.core.synthesis import Stackup, forward_z0

    _, ee = forward_z0(w_mm, f0_ghz, Stackup(name="gysel", epsilon_r=ER,
                                             thickness_mm=H_SUB_MM,
                                             loss_tangent=TAND))
    return float(ee)


def gate_pack(m: dict[str, Any], eps_dev_pct: float) -> dict[str, bool]:
    """gysel 烟测硬门逐臂如实判定（β±2%/均分 ≤0.5dB/|S21|/|S31| −3±1dB/
    |S32| ≤−15dB/|S11| ≤−10dB；非本 A/B 主判，判据=改善量）。"""
    a0 = m["at_f0"]
    return {
        "beta_within_2pct": bool(abs(eps_dev_pct) <= GATE_BETA_PCT),
        "split_le_0p5db": bool(abs(a0["split_diff_db"]) <= GATE_SPLIT_DB),
        "s21_minus3pm1db": bool(abs(a0["s21_db"] + 3.0) <= 1.0),
        "s31_minus3pm1db": bool(abs(a0["s31_db"] + 3.0) <= 1.0),
        "s32_le_minus15db": bool(a0["s32_db"] <= GATE_S32_DB),
        "s11_le_minus10db": bool(a0["s11_db"] <= GATE_S11_DB),
    }


def read_et_facts(vd: str | Path, nrts: int = 100000) -> dict[str, Any]:
    """fdtd/et 时间轴事实（dt 实测/步数/时窗；#268 族——et 是激励时间序列，
    只读时间轴做收敛预算对账，不作衰减判据）。"""
    vd = Path(vd)
    et = vd / "fdtd" / "et"
    try:
        with open(et, encoding="utf-8") as fh:
            first = [fh.readline() for _ in range(2)]
            n = 2 + sum(1 for _ in fh)
        t0 = float(first[0].split()[0])
        t1 = float(first[1].split()[0])
        dt = t1 - t0
        t_end = t1 + dt * (n - 2)
        return {"dt_s": dt, "steps_used": n, "t_end_s": t_end,
                "nrts_cap": nrts,
                "nrts_touched": bool(n >= nrts)}
    except Exception as exc:   # 观测性 best-effort（#105：不阻塞判读主路）
        return {"error": str(exc)}


# ─── 编排（真机面：锁/#261/断点续跑；离线面：渲染审计/判读） ──────────────────

def _variant_dir(mode: str) -> Path:
    return ROOT / mode


def _render_variant(mode: str) -> tuple[Path, str]:
    from rfauto.adapters.openems_templates import render_script

    params: dict[str, Any] = dict(GYS_PARAMS)
    if mode == "on":
        params["_jog_miter_mm"] = MITER_C_MM
    text = render_script("gysel", params, FREQ_RANGE_GHZ,
                         mesh_resolution_mm=MESH_MM)
    vd = _variant_dir(mode)
    vd.mkdir(parents=True, exist_ok=True)
    path = vd / "render_script.py"
    path.write_text(text, encoding="utf-8")
    return path, text


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


CRITERIA_TEXT = """# criteria.md — C7 gysel mitered-jog 切角旋钮真机 A/B（起跑前预声明，{ts}）

## 问题钉死（语境）

- 登记项：gysel 隔离线两处未切角 90° 弯折构成 EM 地板，电路级 −88dB
  增益被 EM 弯折/网格地板吃掉大半（归因假设待证 #122）；IC67 落
  `_jog_miter_mm` opt-in（缺口贴竖直段缘、内外移自适应、渲染单源，缺省 0=
  未切角基线渲染逐字节不变）。
- A/B 问题=切角对隔离深度的真实改善量（假设方向：切角→隔离改善即 |S23|
  负得更多/带内更平稳）；**改善量=主交付，方向相反也如实落档**（#122）。
- 基线锚：runs/gysel_smoke/pt3（L-jog 未切角）S32@f0=-38.1dB、带内谷
  -52.5dB@2.451GHz、带边 -27.9/-24.1dB、S11@f0=-25.0dB、β 偏差 +0.94%。

## A/B 单变量

- 臂 A=off：`_jog_miter_mm` 缺省（不传键）——=pt3 复跑（渲染文本与
  runs/gysel_smoke/pt3/simulation.py 仅一条注释行随 #313 文档化漂移，
  FDTD 输入零差异；全文 diff 恰=jog 段原语+缺口缘网格线，单测钉）。
- 臂 B=on：`_jog_miter_mm=0.2`——每侧 jog 转角外上角 0.2×0.2mm 台阶缺口
  （45° miter 切角的阶梯网格单步近似）。
- c=0.2mm 的选择（网格相撞约束，离线 exec 实测）：缺口缘 x=±(XA+W_F/2−c)
  与桥带缘 x=±(XB+W_F/2) 间距=jog−c=0.412−c、缺口顶缘 y=YJ+W_F/2−c 与负载
  盒缘 y=YJ+G/2 间距=(W_F−G)/2−c=0.3067−c。c=0.3 → 6.7µm（dt×7.7）、
  c=0.4 → 12µm（dt×4.3）= #152 族 CFL 塌缩，预算不可行；c=0.2 → min span
  53.4µm、dt×1.26，为两约束下最大档。

## 预算（起跑前写死）

- 单轮继承 gysel 烟测口径：mesh=0.4mm、扫频 2.25-2.75GHz 401 点、NrTS 缺省
  100000+缺省能量判据停机（pt3 实测 66579 步自停、dt=172fs、时窗 11.46ns）。
- 单轮历史参考 wall：pt3=6926s（并发批嫌疑 #261 家族，solo 预期更低）、
  pt2=1702s；单轮硬超时 90min；两轮名义 ≤2h，**PARTIAL 门=1.5×（3h，到点停）**。
- 共享锁 runs/.oe_collect.lock（O_CREAT|O_EXCL、30s 轮询、30min 忙等上限
  fail-closed、陈锁 pid 接管）+#261 命令行互斥查（`_rfauto_runner|simulation.py|
  render_script.py`；自身名 gysel_miter_ab 不入模式——#261 自锁坑）。
- 断点 resume=collect_ok.json 逐变体幂等；判据/产出零改写（判读独立于渲染
  侧产物）。

## 判读（预声明，G11 掩码纪律）

- 9 列 CSV=部分矩阵：S11/S21/S31 出自激励 1 run、S23 出自激励 3 run（双激励
  footer）；S12/S13/S22/S32/S33 未测不判、互易补齐不使用（#314/#316：宽度≠9
  列 fail loud 不静默）。
- 同频轴硬校验（#287/#294 家族）：两变体 freq 轴逐点相等才可比，异栅拒绝。
- 主量=ΔS32@f0（on−off，dB，负=更深=改善）：≤−1dB → 改善；|Δ|<1dB → 持平；
  ≥+1dB → 恶化。带内平稳性副量=ΔS32 带内最差点 ≤−0.5dB。
- 带内对照表：S32@f0/谷深/带内 max/带边 2.3+2.7/S11@f0/S21@f0/S31@f0，
  off/on/Δ 逐行。
- 护栏（miter 不得破坏匹配/均分，如实记 SIDE_EFFECT 不改主结论方向）：
  ΔS11@f0 ≥+3dB；|Δ均分差| ≥0.5dB。|S11|>1.05 或 |S23|>1.05 任一频点 →
  先查截断（NrTS 触顶/FC 窗，#262）再谈物理。
- 烟测硬门逐臂如实判定（β±2%、均分 ≤0.5dB、|S21|/|S31| −3±1dB、|S32| ≤
  −15dB、|S11| ≤−10dB）——非本 A/B 主判，判据=改善量本身。
- β 金标准（port_beta.csv @f0 εeff vs HJ forward_z0 50Ω 馈，advisory）：
  两臂 β 偏差应一致（网格对 miter 缺口的局部加密不应改变馈线 εeff）。
"""


def cmd_plan() -> int:
    """两变体渲染+exec 几何审计（离线零仿真）；plan.json 不可变（resume 幂等）。"""
    from rfauto.adapters.openems_templates import render_script

    ROOT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    CRITERIA_PATH.write_text(CRITERIA_TEXT.format(ts=ts), encoding="utf-8")
    # off 逐字节不变钉（旋钮缺省=显式 0，IC67 契约在渲染层面复验）
    t_absent = render_script("gysel", dict(GYS_PARAMS), FREQ_RANGE_GHZ,
                             mesh_resolution_mm=MESH_MM)
    t_zero = render_script("gysel", dict(GYS_PARAMS, _jog_miter_mm=0.0),
                           FREQ_RANGE_GHZ, mesh_resolution_mm=MESH_MM)
    if t_absent != t_zero:
        print("[ab] off 逐字节不变钉 FAIL：缺省与显式 0 渲染不同——渲染器回归")
        return 1
    entries: dict[str, Any] = {}
    if PLAN_PATH.exists():
        old = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        print(f"[ab] plan.json 已存在（不可变，sha 校验幂等）：{PLAN_PATH}")
        entries = old.get("variants", {})
    audits: dict[str, dict[str, Any]] = {}
    for mode in VARIANTS:
        path, text = _render_variant(mode)
        sha = _sha256_text(text)
        prev = entries.get(mode) or {}
        if prev.get("sha256") not in (None, sha):
            print(f"[ab] {mode} 渲染文本 sha 漂移（判据/渲染器被改），拒绝静默"
                  "复用旧 plan")
            return 1
        notch = notch_audit(text) if mode == "on" else None
        if notch is not None and not notch["all_pass"]:
            print(f"[ab] {mode} 缺口几何断言 FAIL：{notch['checks']}")
            return 1
        audit = exec_mesh_audit(path, text)
        audits[mode] = audit
        if not audit["min_span_ge_40um"]:
            print(f"[ab] {mode} 网格最小间距 {audit['min_span_m']} < "
                  f"{MESH_MIN_SPAN_M * 1e6:.0f}µm（#152 族 CFL 风险）——不起跑")
            return 1
        if not audit["metal_in_domain"]:
            print(f"[ab] {mode} 金属原语越域（mm/m 单位错族？）boxes="
                  f"{audit['metal_boxes_xy_m'][:6]}——不起跑")
            return 1
        if mode == "on":
            # jog 盒坐标逐值断言（米）：渲染字面量单位错的确定性守卫（#212）
            want = expected_jog_boxes_m()
            got = audit["metal_boxes_xy_m"]
            missing = [b for b in want
                       if not any(all(abs(a - c) < 1e-12
                                      for a, c in zip(b, g, strict=True))
                                  for g in got)]
            if missing:
                print(f"[ab] on jog 盒坐标与期望（米）不符：missing={missing} "
                      f"got={got}——渲染器单位/几何错，不起跑")
                return 1
        entries[mode] = {
            "script": str(path), "sha256": sha,
            "mesh_min_span_m": audit["min_span_m"],
            "mesh_lines": audit["mesh_lines"],
            "dt_cfl_s": audit["dt_cfl_s"],
            "notch_audit": notch,
        }
        print(f"[ab] {mode}: min_span=" +
              ",".join(f"{a}:{v * 1e6:.1f}µm" for a, v in
                       audit["min_span_m"].items()) +
              f" dt~{audit['dt_cfl_s'] * 1e12:.2f}e-12s")
    dt_factor = audits["off"]["dt_cfl_s"] / audits["on"]["dt_cfl_s"]
    if dt_factor > DT_FACTOR_MAX:
        print(f"[ab] on/off CFL dt 因子 {dt_factor:.2f} > {DT_FACTOR_MAX}"
              "（切角档预算不可行）——不起跑，回退更小 c")
        return 1
    # 差异段契约：剥离近点两行+jog 段后余下逐字节相等（单变量）
    t_on = (_variant_dir("on") / "render_script.py").read_text(encoding="utf-8")
    if strip_variant_specific(t_absent) != strip_variant_specific(t_on):
        print("[ab] 差异段契约 FAIL：off/on 渲染在近点+jog 段之外存在差异")
        return 1
    plan = {
        "kind": "gysel_miter_ab_plan", "created_utc": ts,
        "criteria": str(CRITERIA_PATH),
        "variants": entries,
        "declared": {
            "miter_c_mm": MITER_C_MM, "freq_range_ghz": FREQ_RANGE_GHZ,
            "nf": NF, "mesh_mm": MESH_MM, "nrts": 100000,
            "params": GYS_PARAMS, "band": "全扫频带=判读带（烟测口径）",
            "solve_timeout_s": SOLVE_TIMEOUT_S, "budget_wall_s": BUDGET_WALL_S,
            "partial_factor": PARTIAL_FACTOR,
            "dt_factor_on_vs_off": round(dt_factor, 3),
            "pt3_baseline": PT3_BASELINE,
            "prediction": "切角→隔离改善：ΔS32@f0 ≤ −1dB；方向相反如实落档",
        },
    }
    PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    print(f"[ab] plan 落盘：{PLAN_PATH}（判据 {CRITERIA_PATH}，dt 因子 "
          f"{dt_factor:.2f}）")
    return 0


def _pid_alive(pid: int) -> bool | None:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
            capture_output=True, text=True, timeout=30)
        return str(pid) in (out.stdout or "")
    except Exception:
        return None


def acquire_lock(task: str, poll_s: float = LOCK_POLL_S) -> bool:
    """O_CREAT|O_EXCL 原子建锁；占用则 30s 轮询、30min 上限 fail-closed（返回
    False）；陈锁（持有者 pid 已死）接管。"""
    t0 = time.monotonic()
    while True:
        try:
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = {"task": task,
                       "ts": datetime.now(timezone.utc).isoformat(),
                       "pid": os.getpid()}
            os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            os.close(fd)
            return True
        except FileExistsError:
            holder: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                holder = json.loads(
                    LOCK_PATH.read_text(encoding="utf-8"))
            pid = holder.get("pid")
            alive = _pid_alive(pid) if isinstance(pid, int) else None
            if alive is False:
                print(f"[ab] 陈锁接管（持有者 pid={pid} 已死）：{holder}")
                with contextlib.suppress(OSError):
                    LOCK_PATH.unlink()
                continue
            if time.monotonic() - t0 > LOCK_MAX_WAIT_S:
                print(f"[ab] 锁忙等超 {LOCK_MAX_WAIT_S:.0f}s（fail-closed 放弃）："
                      f"{holder or '未知持有者'}")
                return False
            print(f"[ab] 锁被占（{holder or '未知持有者'}），{poll_s:.0f}s 后重试…",
                  flush=True)
            time.sleep(poll_s)


def release_lock(owner_pid: int) -> None:
    """删锁（删前校验内容 pid=自身，防误删后到者锁；best-effort #105）。"""
    try:
        holder = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        if holder.get("pid") == owner_pid:
            LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def oe_foreign_running() -> list[str]:
    """#261 互斥查：python 进程 CommandLine 含 `_rfauto_runner|simulation.py|
    render_script.py`（渲染脚本名=#261 口径第二模式）。

    自身名 gysel_miter_ab 不入模式（#261 自锁坑：互斥模式含自身名会
    命中自身 shim+解释器对死锁）。临时 .ps1 经 powershell -NoProfile
    -ExecutionPolicy Bypass -File 执行（#289：内联 $_ 会被 shell 层展开）。
    探测失败=如实抛错（fail-closed）。
    """
    ROOT.mkdir(parents=True, exist_ok=True)
    ps1 = ROOT / "_oe_proc_check.ps1"
    ps1.write_text(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match "
        "'_rfauto_runner|simulation\\.py|render_script\\.py' } | "
        "ForEach-Object { '{0}`t{1}' -f $_.ProcessId, $_.CommandLine }\n",
        encoding="ascii")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(ps1)],
            capture_output=True, text=True, timeout=120)
    finally:
        with contextlib.suppress(OSError):
            ps1.unlink()
    if out.returncode != 0:
        raise RuntimeError(f"#261 进程查询失败 rc={out.returncode}: "
                           f"{out.stderr[:300]}")
    return [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]


def _csv_complete(vd: Path) -> bool:
    """sparams.csv 完整性：9 列表头 + NF 行（G11 宽度守卫，fail loud 方向）。"""
    try:
        with open(vd / "sparams.csv", encoding="utf-8") as fh:
            header = fh.readline().strip().split(",")
            n = sum(1 for _ in fh)
        return len(header) == 9 and n == NF
    except OSError:
        return False


def _round_complete(vd: Path) -> bool:
    """产物口径完成判定：sparams.csv 完整（9 列+NF 行）+ console 落 done 标记。

    rc 不进判定——openEMS 绑定库在解释器退出段偶发 0xC0000005 崩溃但 CSV
    已完整落盘（2026-09-04 实测、openems_solver 同口径：解析成功即接受，
    #208 家族）。本函数同时服务 _solve_once 完成判定与 resume 幂等检测。
    """
    if not _csv_complete(vd):
        return False
    try:
        with open(vd / "console.log", encoding="utf-8", errors="replace") as fh:
            return "rfauto openEMS simulation done" in fh.read()
    except OSError:
        return False


def _backfill_collect_ok(vd: Path) -> None:
    """resume 路径补写完成标记（旧代码轮 rc 崩溃但产物完整时；如实记 rc_note）。"""
    if (vd / "collect_ok.json").exists():
        return
    (vd / "collect_ok.json").write_text(json.dumps(
        {"ok": True, "wall_s": None, "rc": None,
         "rc_note": "backfilled：子进程 rc 非零（绑定退出段 0xC0000005 族）但"
                    "产物完整（sparams 9 列+401 行+done 标记），按完成计",
         "sparams_sha256": _sha256_file(vd / "sparams.csv"),
         "finished_utc": datetime.now(timezone.utc).isoformat()},
        ensure_ascii=False, indent=1), encoding="utf-8")


def _solve_once(mode: str, t_deadline: float | None) -> tuple[bool, float]:
    """单轮真跑（渲染脚本子进程直跑——绕开 solver 缓存，烟测同源口径；
    console 落日志；返回 (ok, wall_s)。ok=产物口径，rc 崩溃不误判失败）。"""
    vd = _variant_dir(mode)
    script = vd / "render_script.py"
    t0 = time.monotonic()
    env = dict(os.environ)
    env.pop("RFAUTO_SKIP_RUN", None)
    log_path = vd / "console.log"
    timeout = SOLVE_TIMEOUT_S
    if t_deadline is not None:
        timeout = max(60.0, min(timeout, t_deadline - time.monotonic()))
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.run([sys.executable, str(script)], cwd=str(vd),
                              env=env, stdout=log, stderr=subprocess.STDOUT,
                              timeout=timeout)
    wall = time.monotonic() - t0
    ok = _round_complete(vd)
    if ok:
        (vd / "collect_ok.json").write_text(json.dumps(
            {"ok": True, "wall_s": round(wall, 1), "rc": proc.returncode,
             "rc_note": ("rc=0" if proc.returncode == 0 else
                         f"rc={proc.returncode} 非零（绑定退出段崩溃族）但产物"
                         "完整，按完成计（openems_solver 同口径）"),
             "sparams_sha256": _sha256_file(vd / "sparams.csv"),
             "finished_utc": datetime.now(timezone.utc).isoformat()},
            ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ab] {mode} rc={proc.returncode} wall={wall:.0f}s ok={ok} "
          f"（日志 {log_path.name}）", flush=True)
    return ok, wall


def cmd_collect() -> int:
    """A/B 两轮 openEMS 真跑（共享锁内整段；断点 resume 幂等；预算 PARTIAL 门）。"""
    if not PLAN_PATH.exists():
        print("[ab] 无 plan.json（先 --plan）")
        return 2
    if str(Path.cwd().resolve()) != str(REPO.resolve()):
        print(f"[ab] 拒跑：cwd 必须是仓库根 {REPO}（当前 {Path.cwd()}）")
        return 2
    if not acquire_lock("gysel_miter_ab"):
        return 1
    owner_pid = os.getpid()
    t0 = time.monotonic()
    state: dict[str, Any] = {"variants": {}, "over_nominal": False,
                             "partial_budget": False}
    deadline = t0 + BUDGET_WALL_S * PARTIAL_FACTOR
    try:
        foreign = oe_foreign_running()
        if foreign:
            print("[ab] #261 互斥命中（他轨 OE 在跑，拒绝起跑，不代杀）：\n"
                  + "\n".join(f"  {ln}" for ln in foreign[:10]))
            return 1
        print("[ab] #261 命令行查：无他轨 OE 进程，锁内起跑")
        for mode in VARIANTS:
            vd = _variant_dir(mode)
            if _round_complete(vd):
                # resume 幂等（产物口径）：补写 collect_ok 后跳过，不重跑
                _backfill_collect_ok(vd)
                print(f"[ab] {mode} 产物完整已在（resume 跳过）")
                state["variants"][mode] = {"status": "done(resume)"}
                continue
            if time.monotonic() >= deadline:
                print(f"[ab] 预算到点（{PARTIAL_FACTOR}×名义），{mode} 不再起跑")
                state["variants"][mode] = {"status": "skipped(budget)"}
                state["partial_budget"] = True
                break
            ok, wall = _solve_once(mode, deadline)
            state["variants"][mode] = {
                "status": "done" if ok else "failed",
                "wall_s": round(wall, 1),
                "et_facts": read_et_facts(vd),
            }
            if not ok:
                print(f"[ab] {mode} FAIL（留档续跑：重跑 --collect 即 resume）")
        wall_total = time.monotonic() - t0
        state["wall_total_s"] = round(wall_total, 1)
        state["over_nominal"] = bool(wall_total > BUDGET_WALL_S)
        state["partial_budget"] = bool(wall_total > BUDGET_WALL_S * PARTIAL_FACTOR)
    finally:
        with contextlib.suppress(Exception):
            state["finished_utc"] = datetime.now(timezone.utc).isoformat()
            COLLECT_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False,
                                                     indent=1),
                                          encoding="utf-8")
        release_lock(owner_pid)
    n_done = sum(1 for v in state["variants"].values()
                 if isinstance(v, dict) and str(v.get("status", "")).startswith(
                     "done"))
    print(f"[ab] collect 完成 done={n_done}/2 wall={state.get('wall_total_s')}s "
          f"over_nominal={state['over_nominal']} "
          f"partial_budget={state['partial_budget']}")
    return 0 if n_done == 2 else 1


def cmd_judge() -> int:
    """A/B 差值表+如实判读（离线；同频轴硬校验+G11 掩码+烟测硬门逐臂）。"""
    if not PLAN_PATH.exists():
        print("[ab] 无 plan.json（先 --plan）")
        return 2
    variants: dict[str, Any] = {}
    freq_axes: list[Any] = []
    load_err: dict[str, str] = {}
    for mode in VARIANTS:
        vd = _variant_dir(mode)
        csv_path = vd / "sparams.csv"
        if not (vd / "collect_ok.json").exists() or not csv_path.exists():
            print(f"[ab] {mode} 缺产物（collect_ok/sparams）——先 --collect")
            return 2
        try:
            sp = load_sparams(csv_path)
        except ValueError as exc:
            load_err[mode] = str(exc)
            continue
        freq_axes.append(sp["f_ghz"])
        judged = metrics(sp)
        beta_eps = (beta_eps_eff(vd / "port_beta.csv")
                    if (vd / "port_beta.csv").exists() else None)
        eps_dev_pct = (round(100.0 * (beta_eps["eps_eff"]
                                      / hj_eps_eff(GYS_PARAMS["w_feed_mm"])
                                      - 1.0), 3)
                       if beta_eps else None)
        with open(vd / "collect_ok.json", encoding="utf-8") as fh:
            ok_marker = json.load(fh)
        gates = (gate_pack(judged, eps_dev_pct) if eps_dev_pct is not None
                 else {k: v for k, v in gate_pack(judged, 0.0).items()
                       if k != "beta_within_2pct"})
        variants[mode] = {
            "sparams_sha256": ok_marker.get("sparams_sha256"),
            "wall_s": ok_marker.get("wall_s"),
            "et_facts": read_et_facts(vd),
            "judged": judged,
            "beta": dict(beta_eps, eps_dev_pct=eps_dev_pct,
                         hj_50ohm_feed=round(hj_eps_eff(
                             GYS_PARAMS["w_feed_mm"]), 6))
            if beta_eps else None,
            "gates": gates,
            "gates_note": "" if eps_dev_pct is not None
            else "β 门缺 port_beta.csv 未判（其余门如实）",
        }
    if load_err:
        verdict_err = {
            "item": "C7 gysel_miter_ab", "conclusion": "INCONCLUSIVE(产物加载失败)",
            "load_errors": load_err,
            "note_g11": ("宽度≠9 列 fail loud（#316 兜底方向=多报不放过）："
                         "部分矩阵缺列不得当互易证据"),
        }
        VERDICT_PATH.write_text(json.dumps(verdict_err, ensure_ascii=False,
                                           indent=1), encoding="utf-8")
        print(f"[ab] verdict 落盘（INCONCLUSIVE）：{VERDICT_PATH}")
        return 1
    import numpy as np

    axis_ok = bool(np.array_equal(np.asarray(freq_axes[0]),
                                  np.asarray(freq_axes[1])))
    if not axis_ok:
        print("[ab] 两变体频轴不一致（#287 家族：同栅才可比）——判读拒绝")
        return 1
    tab = ab_table(variants["off"]["judged"], variants["on"]["judged"])
    gates_verdict = {m: ("PASS" if all(variants[m]["gates"].values()) else "FAIL")
                     for m in VARIANTS}
    truncation = {m: {
        "s11_pts_gt1p05": variants[m]["judged"]["s11_passive_violation_pts"],
        "s23_pts_gt1p05": variants[m]["judged"]["s23_passive_violation_pts"],
        "nrts_touched": bool(variants[m]["et_facts"].get("nrts_touched"))}
        for m in VARIANTS}
    budget = None
    if COLLECT_STATE_PATH.exists():
        with open(COLLECT_STATE_PATH, encoding="utf-8") as fh:
            st = json.load(fh)
        budget = {"wall_total_s": st.get("wall_total_s"),
                  "over_nominal": st.get("over_nominal"),
                  "partial_budget": st.get("partial_budget"),
                  "wall_note":
                      "wall_total_s=本次（resume）collect 墙钟=on 轮；off 轮在"
                      "首轮 collect 已完成（1936s，该轮驱动被外部终止后经"
                      " resume 产物口径收编、collect_ok 为补写无 wall），两轮"
                      "合计约 4146s 仍在 2h 名义预算内"}
    conclusion = dict(tab)
    conclusion["axis_identical"] = axis_ok
    conclusion["off_vs_pt3_baseline"] = {
        "delta_s32_f0_db": round(variants["off"]["judged"]["at_f0"]["s32_db"]
                                 - PT3_BASELINE["s32_db"], 3),
        "note": "off 臂=pt3 同轮复现锚；|Δ| 大于网格/引擎漂移量级（~1dB）时"
                "先查复跑环境再谈 A/B 差值"}
    verdict = {
        "item": "C7 gysel_miter_ab",
        "kind": "gysel mitered-jog 切角旋钮单变量对照（off vs on=0.2mm，"
                "名义设计固定）",
        "criteria": str(CRITERIA_PATH),
        "design_source": "TEMPLATE_NOMINAL gysel + _jog_miter_mm opt-in（IC67）",
        "variants": variants,
        "ab_table": tab,
        "conclusion": conclusion,
        "gate_verdict_per_variant": gates_verdict,
        "truncation_check": truncation,
        "note_gates": ("烟测硬门逐臂如实判定（本实验判据=隔离改善量非门冲绿，"
                       "#122）；部分矩阵掩码：S11/S21/S31（激励 1 run）+S23"
                       "（激励 3 run）为已测，S12/S13/S22/S32/S33 未测不判、"
                       "互易补齐不使用（#314）"),
        "mask": {"S11": True, "S21": True, "S31": True, "S23": True,
                 "S12/S13/S22/S32/S33": "未测（不判）"},
        "budget": budget,
        "artifacts": ["off/sparams.csv", "on/sparams.csv", "off/port_beta.csv",
                      "on/port_beta.csv", "off/console.log", "on/console.log"],
    }
    VERDICT_PATH.write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    print(json.dumps({
        "ab_rows": tab["rows"], "conclusion": tab["conclusion"],
        "stability": tab["stability"], "side_effects": tab["side_effects"],
        "off_vs_pt3": conclusion["off_vs_pt3_baseline"],
        "gates": gates_verdict,
        "beta_eps_dev_pct": {m: (variants[m]["beta"] or {}).get("eps_dev_pct")
                             for m in VARIANTS},
        "truncation": truncation, "budget": budget,
    }, ensure_ascii=False, indent=1))
    print(f"[ab] verdict 落盘：{VERDICT_PATH}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="C7 gysel mitered-jog 切角 A/B")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true", help="渲染+exec 几何审计（离线）")
    g.add_argument("--collect", action="store_true",
                   help="A/B 两轮真跑（锁+#261+resume）")
    g.add_argument("--judge", action="store_true",
                   help="A/B 差值表+判读（离线）")
    args = ap.parse_args(argv)
    if args.plan:
        return cmd_plan()
    if args.collect:
        return cmd_collect()
    return cmd_judge()


if __name__ == "__main__":
    raise SystemExit(main())
