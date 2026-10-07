"""OE 三期发射编排驱动（wf:oe-phase3-prep；runs/oe_phase3/<t>/ 逐席 verdict）。

三席（月计划 W3 OE 窗 · completeness-mid 缺口映射）：
  ① ring_resonator      F-A.3 Design Dk 锚（F-A 仿真域闭环首步：OE run+提取回收）
  ② pyramid_horn        ME-7 真机首跑冒烟（离线审计 #212 已过）
  ③ coax_waveguide_transition  ME-6 真机首跑冒烟（离线审计 #212 已过）

零 src 改动、fd_oe_campaign/oe_nominal 驱动零改动（本脚本独立；nrts 收敛判读
等纯函数经 importlib 复用 fd_oe_campaign 单源，不复制）。

═══ 判据预声明（#122：先声明后跑；"首跑定标"=无 meta/criteria 锚的物理合理窗）═══

通用门（全席）：|S|≤1.05 无源（#262 族物理性：窗覆盖脉冲全程时不出现 |S|>1
截断假象）；G11 掩码健康门（rfauto.service.health_check_run，verdict=="unhealthy"
才升 FAIL——suspect-by-absence 只留痕不拦，#314 口径）；提取极值不得落在搜索窗
边缘 2 个频点内（#281 夹持伪象家族）。

── ring_resonator（F-A.3 Design Dk 提取回收；单激励 port1 → S11+S21 5 列）──
  频带 (1.5, 5.5) GHz（F0=3.5/fc=2.0：脉冲 1.43ns 短 + 覆盖 n=1/f1≈2.5 与
    n=2/f2≈5.0 两谐波；F-A M3 闭式 f_n≈n·c/(2π·r_mean·√εeff)）
  网格 0.5mm（gap 守卫上限 4·gap/3=0.533 内取安全档；NEAR=0.125 ≤ gap/3=
    0.1333 有 6% 余量——审计档 0.4 留给后续精算批，本档为冒烟档）
  时窗 12ns（NrTS=ceil(1.1·12ns/dt)，dt 按终网格 CFL 实算）：覆盖脉冲 8.4×；
    Q_L~100 时环衰 τ≈6.4ns，窗末能量约 −8dB——** NrTS 触帽属预期 **，
    本席 nrts_policy=record_only（窗为"位置级"冒烟档：f_n 峰位提取不受
    截断漂移一阶影响；meta max_time_ns=30ns 精算档属 Design Dk 锚定标批）
  判据窗：
    f1 ∈ [2.40, 2.60] GHz（名义 2.5 ±4%；依据：v1 闭式未含曲率/色散修正
      ±1~2% 文献量级 + 栅格化慢波未补偿 + 粗网格 ±1%）
    f2 ∈ [4.75, 5.25] GHz（名义 5.0 ±5%，色散随 f 增宽）
    |S21|@f1 ≥ 0.2（−14dB 谐振指纹地板，首跑定标——低于此=间隙耦合/模式
      激励失效信号）
    εr(f1) ∈ [3.11, 4.21]（名义 3.66 ±15%，首跑定标；依据：f1 窗 ±4% →
      εeff ±8% → HJ 逆映射实测斜率 1.446（forward_z0+brentq 数值复算，
      review_slice6 P2-3 勘误：原稿 ~1.7"填充因子倒数"系粗估失真）→
      f1 窗端点映射 εr∈[3.35, 4.01] ⊂ 窗（两侧覆盖有余）；窗值维持
      首跑定标口径不变，不构成事后改窗）
    |εr(f2)−εr(f1)| ≤ 0.60（双谐波一致性，首跑定标；色散/曲率随 f 增大，
      f2 侧系统偏差更大，取 f1 窗的 2 倍带宽）
    Q_L（信息项不设门）：S21 峰 3dB 带宽 → Q_L=f1/bw，供 tanδ 分离批判读
  εr 反演：εeff_n=(n·c0/(2π·r_mean·f_n))² → HJ 逆根（scipy brentq，
    forward_z0(er) 单调；同源回收钉在 test_oe_phase3_driver——HJ 模型本身
    的正确性由 test_ring_resonator_template 综合反解自洽测试承担，不在本层）

── pyramid_horn（ME-7 真机首跑；单端口 RectWGPort 解析 TE10）──
  频带 (8.0, 12.0) GHz（0.8–1.2×f0；TE10 可用带 8.2–12.4 内）
  网格 1.4mm（base=λ0/21.4@10GHz ≥ 20 格/λ 地板；阶梯守卫步距 2.96 ≥
    4·NEAR=1.4 过；审计档 0.6 = 官方 λ0/50 实测 172.8M cells 超冒烟预算
    两个量级—— NEAR 走廊钉死全轴密度（网格阶梯化 18 站 × maxRatio 过渡），
    定档探针 runs/oe_phase3/preflight）
  时窗 6ns（脉冲 1.43ns ×4.2；低 Q 辐射结构默认 −30dB 能量判据预期先停）
  判据窗（首跑定标，无 HFSS/闭式真机锚在档）：
    S11@10GHz ≤ −8dB（官方教程级匹配下限；粗网格冒烟档）
    band-min S11(8–12) ≤ −10dB
    core(9.5–10.5) max S11 ≤ −6dB
  方向性：本席**不可测**——renderer far_field 显式拒绝（Ph3 方向图窗未接
    线，meta smoke_note 同口径）；离线锚=horn_gain_direct 回代 15.000dB 已由
    test_pyramid_horn_template 钉。方向性真机窗=Ph3 另批，不冒充本席判据。
  nrts_policy=must_converge（触帽未达判据=FAIL，#266 口径）

── coax_waveguide_transition（ME-6 真机首跑；单激励 port1=探针基集总桥）──
  频带 (8.0, 12.0) GHz；网格 1.0mm（探针守卫 NEAR=0.25 ≤ min(2·pin_r,
    port_h)/3=0.333 有 25% 余量；集总口隙 port_h=1mm 在 NEAR 档 4 格 ≥2 格
    #257 地板）；时窗 6ns（同 horn）
  判据窗（首跑定标；官方 wiki Coax-to-Waveguide 教程 pin 比例档设计意图）：
    S11@10GHz ≤ −10dB（"tune for best impedance match"设计目标下限）
    S21@10GHz ≥ −1.5dB（插损：短波导段+匹配过渡，封闭腔无辐射损耗）
    core(9–11) max S11 ≤ −8dB
    ZL_WG@f0（信息项不设门）：renderer summary 回显解析 TE10 阻抗
  nrts_policy=must_converge（同 horn）

═══ 预算（离线推演，依据=引擎三日志标定速率 6e7–1.3e8 cell-steps/s）═══
  ring   2.6M cells × 61646 步 → 21–45min
  horn  16.1M cells × 16714 步 → 34–75min
  coax   4.3M cells × 34271 步 → 19–41min
  合计 solo 串行 ~1.2–2.7h（LAUNCH.md 预声明 ~2.5h 门）；--timeout 缺省
  7200s/席为硬上界。逐席 dt/cells 以 --preflight-only 产物为发射前复核。

═══ 用法 ═══
  预飞（离线零仿真，必跑）：python scripts/oe_phase3_campaign.py --preflight-only
  发射（队列空后主代理一键，solo+#261）：
    .venv/Scripts/python.exe scripts/oe_phase3_campaign.py --timeout 7200
  判读（跑后离线重判，零仿真）：python scripts/oe_phase3_campaign.py --judge-only
  产物：runs/oe_phase3/<t>/{simulation.py,sparams.csv,verdict.json,criteria.json}
        runs/oe_phase3/campaign_summary.json、runs/oe_phase3/preflight/
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

C0 = 299792458.0
SCRIPTS = Path(__file__).resolve().parent
OUT_ROOT = REPO / "runs" / "oe_phase3"

#: 引擎速率标定带（cell-steps/s）：三日志实测
#:   runs/audit_line_eps/rerun.log      177072×60000/184.19s = 5.77e7
#:   runs/audit_official_notch/run.log  269780×13974/28.78s  = 1.31e8
#:   runs/audit_openems_nominal/A_template_nominal/check.log
#:                                      1208592×20400/377.1s = 6.54e7
RATE_LO = 6e7
RATE_HI = 1.3e8

# ══ 逐席配置（预声明单源；网格/时窗依据见模块头判据预声明）════════════════
SEATS: dict[str, dict[str, Any]] = {
    "ring_resonator": {
        "band_ghz": (1.5, 5.5),
        "mesh_mm": 0.5,
        "window_ns": 12.0,
        "nrts_policy": "record_only",   # 位置级冒烟档：触帽预期，如实记录
        "excite_port": 1,
    },
    "pyramid_horn": {
        "band_ghz": (8.0, 12.0),
        "mesh_mm": 1.4,
        "window_ns": 6.0,
        "nrts_policy": "must_converge",
        "excite_port": 1,
    },
    "coax_waveguide_transition": {
        "band_ghz": (8.0, 12.0),
        "mesh_mm": 1.0,
        "window_ns": 6.0,
        "nrts_policy": "must_converge",
        "excite_port": 1,
    },
}
TARGETS = list(SEATS)

# ══ 判据窗（首跑定标依据见模块头；常量与 criteria.json 快照单源）══════════
RING = {
    "f1_win_ghz": (2.40, 2.60),       # 名义 2.5 ±4%
    "f2_win_ghz": (4.75, 5.25),       # 名义 5.0 ±5%
    "s21_peak_min": 0.2,              # −14dB 谐振指纹地板（首跑定标）
    "eps_r_win": (3.11, 4.21),        # 3.66 ±15%（首跑定标）
    "eps_r_diff_max": 0.60,           # 双谐波一致性（首跑定标）
    "f0_ghz": 2.5,
    "eps_r_nominal": 3.66,            # rogers4350b datasheet 名义
    "n_harmonics": (1, 2),
}
HORN = {
    "f0_ghz": 10.0,
    "s11_f0_max_db": -8.0,            # 首跑定标
    "band_ghz": (8.0, 12.0),
    "band_min_max_db": -10.0,         # 窗内最深匹配须 ≤ −10dB
    "core_ghz": (9.5, 10.5),
    "core_max_db": -6.0,
}
COAX = {
    "f0_ghz": 10.0,
    "band_ghz": (8.0, 12.0),          # 与席位频带同窗（band-min 门）
    "band_min_max_db": -10.0,         # 首跑定标
    "s11_f0_max_db": -10.0,           # 首跑定标（官方教程 pin 比例档设计意图）
    "s21_f0_min_db": -1.5,            # 首跑定标
    "core_ghz": (9.0, 11.0),
    "core_max_db": -8.0,
    "zl_wg_info_ohm": (100.0, 700.0),  # 信息项
}
PASSIVE_MAX = 1.05
#: 提取极值距搜索窗缘的最小频点数（#281 夹持伪象家族）
CLAMP_GUARD_PTS = 2
#: 网格最小间距地板（#349 起跑守卫）
GRID_MIN_SPACING_M = 10e-6


# ══ 纯函数（离线可测面）══════════════════════════════════════════════════
def pulse_est_s(fc_ghz: float) -> float:
    """openEMS 高斯激励长度估计（秒）：L ≈ 9/(π·fc) = 2.865ns·(1GHz/fc)。

    引擎两日志标定（"Excitation signal length is: N timesteps (Xs)"）：
      fc=1.0GHz → 2.865ns（runs/audit_line_eps/rerun.log、A_template_nominal/
      check.log 两例同值）；fc=3.5GHz → 0.8187ns（audit_official_notch/run.log）。
    仅作预飞覆盖度检查；真值以跑后引擎日志 excitation_steps 为准（nrts 门）。
    """
    fc = float(fc_ghz)
    if not fc > 0:
        raise ValueError(f"pulse_est_s: fc 须 >0，得 {fc!r}")
    return 9.0 / (math.pi * fc * 1e9)


def plan_nrts(window_ns: float, dt_s: float) -> int:
    """时窗→NrTS：ceil(1.1·T/dt)（复用 openems_templates 单源公式，#312 余量）。

    注：三席均不在 NRTS_MAX_TIME_TEMPLATES 接线清单内（那是四 F-D 模板专用），
    本驱动显式传 _nrts 参数（c3 先例 #266 旋钮路径，三席渲染器均消费）。
    """
    from rfauto.adapters.openems_templates import nrts_from_max_time_ns

    return nrts_from_max_time_ns(float(window_ns), float(dt_s))


def hj_inverse_er(
    eeff_meas: float, w_mm: float, f_ghz: float, h_mm: float,
    tan_d: float = 0.0,
) -> tuple[float | None, str]:
    """HJ 逆根：给定 εeff_meas 反解 εr（forward_z0 对 er 单调 → brentq）。

    返回 (er | None, note)。tan_d 必须与设计链同源（meta substrate 口径）：
    tan_d 进 HJ εeff（0→0.0037 差 0.19%，漏传即 −0.22% εr 系统偏差——单测
    回收钉实测抓出）。同源回收钉（#118 口径的换算正确性钉）：合成已知
    er → forward εeff → 逆根回收 == er；HJ 模型本身的正确性锚在
    test_ring_resonator_template（综合反解自洽），不在本层重复。
    """
    from scipy.optimize import brentq

    from rfauto.core.synthesis import Stackup, forward_z0

    def _model(er: float) -> float:
        sub = Stackup(name="ring-extract", epsilon_r=er, thickness_mm=h_mm,
                      loss_tangent=tan_d)
        _z0, eeff = forward_z0(w_mm, f_ghz, sub)
        return float(eeff)

    lo, hi = 1.05, 30.0
    f_lo, f_hi = _model(lo), _model(hi)
    if not f_lo < eeff_meas < f_hi:
        return None, (
            f"εeff={eeff_meas:.4f} 超出 HJ 可达域 [{f_lo:.4f}, {f_hi:.4f}]"
            f"（er∈[{lo},{hi}]）——如实不可判，不外推")
    er = float(brentq(lambda x: _model(x) - eeff_meas, lo, hi, xtol=1e-10))
    return er, "ok"


def _to_db(x):
    """幅值→dB（20log10；地板 −120dB 防 log(0)）。"""
    return 20.0 * np.log10(np.maximum(np.abs(np.asarray(x)), 1e-6))


def _argext_clamped(
    freqs: np.ndarray, y: np.ndarray, win: tuple[float, float], mode: str,
) -> tuple[int, bool]:
    """窗内 argmax/argmin + 边缘夹持判定（#281：极值不得落窗缘 2 频点内）。

    返回 (全数组索引, clamped)；窗内空 → (-1, True)。

    复数入参语义警示（oe3 S4 审计 H3）：np.argmax/argmin 对复数按实部比较
    （numpy 惯例），复数谱必须由调用方先取幅值（extract_ring 调用点已幅值化）。
    本函数入口禁加 np.abs——dB 域负值谱的 argmin 调用方（extract_waveguide，
    horn/coax 共享）会被 abs 翻转丢谷。
    """
    mask = (freqs >= win[0]) & (freqs <= win[1])
    idx_win = np.flatnonzero(mask)
    if idx_win.size == 0:
        return -1, True
    vals = np.asarray(y)[idx_win]
    pos = int(np.argmax(vals) if mode == "max" else np.argmin(vals))
    idx = int(idx_win[pos])
    step = int(idx_win[1] - idx_win[0]) if idx_win.size > 1 else 1
    clamped = bool(
        idx < idx_win[0] + CLAMP_GUARD_PTS * step
        or idx > idx_win[-1] - CLAMP_GUARD_PTS * step)
    return idx, clamped


def extract_ring(
    freqs: np.ndarray, s11: np.ndarray, s21: np.ndarray, nominal: dict[str, Any],
    h_mm: float = 0.508, tan_d: float = 0.0037,
) -> dict[str, Any]:
    """ring_resonator 标量提取（纯函数）：f1/f2 峰位 → εeff → εr 回收 + Q_L。

    h_mm/tan_d = meta.yaml substrate 单源（rogers4350b 0.508/0.0037）；tan_d
    与设计链同源是 εr 回收无系统偏差的前提（见 hj_inverse_er 注）。
    """
    out: dict[str, Any] = {"judge": "ring"}
    r_mean_mm = float(nominal["r_mean_mm"])
    w_mm = float(nominal["w_mm"])
    s21_db = _to_db(s21)
    for n, key, win in ((1, "f1", RING["f1_win_ghz"]),
                        (2, "f2", RING["f2_win_ghz"])):
        # 幅值语义（oe3 S4 审计 H3，2026-09-29 修）：s21 是原始复数，argmax
        # 对复数按实部比较——f2 真峰 (0.0086,−0.0502) 实部极小被跳过、误取
        # 4.75/误报 clamped。取模长后再 argmax；仅本调用点幅值化，horn/coax
        # 路径（extract_waveguide，已 dB 化实数）零影响（勿在 _argext_clamped
        # 入口 abs——会翻转 dB 域 argmin，见该函数 docstring）。
        idx, clamped = _argext_clamped(freqs, np.abs(s21), win, "max")
        if idx < 0:
            out[key] = None
            out[f"{key}_clamped"] = True
            continue
        f_n = float(freqs[idx])
        eeff = (n * C0 / (2.0 * math.pi * r_mean_mm * 1e-3 * f_n * 1e9)) ** 2
        er, note = hj_inverse_er(eeff, w_mm, f_n, h_mm, tan_d)
        out[key] = f_n
        out[f"{key}_clamped"] = clamped
        out[f"{key}_s21"] = float(abs(s21[idx]))
        out[f"{key}_s21_db"] = float(s21_db[idx])
        out[f"eeff_{key}"] = float(eeff)
        out[f"eps_r_{key}"] = er
        out[f"eps_r_{key}_note"] = note
    # Q_L 信息项（f1 峰 3dB 带宽；退化如实 None，不设门）
    out["ql_info"] = None
    if out.get("f1") is not None:
        idx1 = int(np.argmin(np.abs(freqs - float(out["f1"]))))
        peak_db = float(s21_db[idx1])
        within = np.flatnonzero(
            (freqs >= RING["f1_win_ghz"][0]) & (freqs <= RING["f1_win_ghz"][1])
            & (s21_db >= peak_db - 3.0))
        if within.size >= 3:
            bw = float(freqs[within[-1]] - freqs[within[0]])
            out["ql_info"] = {
                "f1_ghz": float(out["f1"]), "bw_3db_ghz": round(bw, 6),
                "ql": round(float(out["f1"]) / bw, 2) if bw > 0 else None,
            }
    return out


def judge_ring(ext: dict[str, Any], s: np.ndarray) -> dict[str, Any]:
    """ring 判据门（预声明窗 → status/checks；判读纯函数）。"""
    checks: list[dict[str, Any]] = []

    def _chk(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    finite = bool(np.all(np.isfinite(s)))
    passive = bool(np.all(np.abs(s) <= PASSIVE_MAX))
    _chk("finite", finite, "ok" if finite else "S 含非有限值")
    _chk("passive", passive,
         f"max|S|={float(np.max(np.abs(s))):.4f}（门 ≤{PASSIVE_MAX}）")
    f1, f2 = ext.get("f1"), ext.get("f2")
    er1 = ext.get("eps_r_f1")
    er2 = ext.get("eps_r_f2")
    peak1 = ext.get("f1_s21")
    _chk("f1_window",
         None if f1 is None else bool(RING["f1_win_ghz"][0] <= f1 <= RING["f1_win_ghz"][1]),
         f"f1={f1} 窗 {RING['f1_win_ghz']}")
    _chk("f2_window",
         None if f2 is None else bool(RING["f2_win_ghz"][0] <= f2 <= RING["f2_win_ghz"][1]),
         f"f2={f2} 窗 {RING['f2_win_ghz']}")
    _chk("s21_peak_floor",
         None if peak1 is None else bool(peak1 >= RING["s21_peak_min"]),
         f"|S21|@f1={peak1}（地板 {RING['s21_peak_min']}，首跑定标）")
    _chk("eps_r_f1_window",
         None if er1 is None else bool(RING["eps_r_win"][0] <= er1 <= RING["eps_r_win"][1]),
         f"εr(f1)={er1} 窗 {RING['eps_r_win']}（{RING['eps_r_nominal']} ±15%，首跑定标）")
    diff = None if (er1 is None or er2 is None) else abs(float(er1) - float(er2))
    _chk("eps_r_harmonic_consistency",
         None if diff is None else bool(diff <= RING["eps_r_diff_max"]),
         f"|εr(f2)−εr(f1)|={diff}（门 ≤{RING['eps_r_diff_max']}，首跑定标）")
    for key in ("f1", "f2"):
        if ext.get(f"{key}_clamped"):
            _chk(f"{key}_clamp_guard", False,
                 f"{key} 落搜索窗缘 2 频点内（#281 夹持伪象）")
    hard_names = ("finite", "passive", "f1_clamp_guard", "f2_clamp_guard",
                  "s21_peak_floor", "eps_r_f1_window")
    hard_fail = any(c["ok"] is False for c in checks if c["name"] in hard_names)
    soft_pending = any(c["ok"] is None for c in checks)
    if hard_fail:
        status = "FAIL"
    elif soft_pending:
        status = "PARTIAL"
    elif all(c["ok"] for c in checks):
        status = "PASS"
    else:
        status = "FAIL"
    return {"status": status, "checks": checks,
            "nrts_policy": SEATS["ring_resonator"]["nrts_policy"]}


def extract_waveguide(freqs: np.ndarray, s11: np.ndarray,
                      s21: np.ndarray | None = None,
                      zl_wg_f0: float | None = None,
                      template: str = "pyramid_horn") -> dict[str, Any]:
    """horn/transition 标量提取（纯函数）：S11 曲线 + 谷位夹持判定。

    夹持判定只在"真极值"上生效：谷深不比带内中位低 3dB（平坦谱/无谐振
    谷）时 argmin 本无物理意义，不触发 #281 夹持门（否则平坦匹配谱假红）。
    """
    s11_db = _to_db(s11)
    win = HORN["band_ghz"] if template == "pyramid_horn" else COAX["core_ghz"]
    idx, clamped = _argext_clamped(freqs, s11_db, win, "min")
    if idx >= 0:
        win_mask = (freqs >= win[0]) & (freqs <= win[1])
        band_ref = float(np.median(s11_db[win_mask]))
        is_real_dip = bool(float(s11_db[idx]) <= band_ref - 3.0)
        clamped = bool(clamped and is_real_dip)
    out: dict[str, Any] = {
        "judge": template, "freqs": freqs, "s11_db": s11_db,
        "f_dip": None if idx < 0 else float(freqs[idx]),
        "dip_clamped": clamped,
        "s21": None if s21 is None else np.asarray(s21),
        "zl_wg_f0_ohm": zl_wg_f0,
    }
    if s21 is not None:
        s21_db = _to_db(s21)
        out["s21_db"] = s21_db
        out["s21_f0_db"] = float(np.interp(COAX["f0_ghz"], freqs, s21_db))
    return out


def judge_waveguide_refl(
    ext: dict[str, Any], s: np.ndarray, spec: dict[str, Any], template: str,
) -> dict[str, Any]:
    """horn 判据门（S11 预声明窗；判读纯函数）。"""
    checks: list[dict[str, Any]] = []

    def _chk(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    finite = bool(np.all(np.isfinite(s)))
    passive = bool(np.all(np.abs(s) <= PASSIVE_MAX))
    _chk("finite", finite, "ok" if finite else "S 含非有限值")
    _chk("passive", passive, f"max|S|={float(np.max(np.abs(s))):.4f}")
    s11_db = ext["s11_db"]
    freqs = ext["freqs"]
    s11_f0 = float(np.interp(spec["f0_ghz"], freqs, s11_db))
    _chk("s11_f0", bool(s11_f0 <= spec["s11_f0_max_db"]),
         f"S11@{spec['f0_ghz']}GHz={s11_f0:.2f}dB"
         f"（门 ≤{spec['s11_f0_max_db']}dB，首跑定标）")
    band = spec["band_ghz"]
    band_mask = (freqs >= band[0]) & (freqs <= band[1])
    min_db = float(np.min(s11_db[band_mask]))
    _chk("band_min", bool(min_db <= spec["band_min_max_db"]),
         f"band-min S11={min_db:.2f}dB（门 ≤{spec['band_min_max_db']}dB）")
    core = spec["core_ghz"]
    core_mask = (freqs >= core[0]) & (freqs <= core[1])
    core_db = float(np.max(s11_db[core_mask]))
    _chk("core_max", bool(core_db <= spec["core_max_db"]),
         f"core max S11={core_db:.2f}dB（门 ≤{spec['core_max_db']}dB）")
    if ext.get("dip_clamped"):
        _chk("dip_clamp_guard", False, "S11 谷落搜索窗缘（#281 夹持伪象）")
    hard_names = ("finite", "passive", "dip_clamp_guard",
                  "s11_f0", "band_min", "core_max")
    status = ("FAIL" if any(c["ok"] is False for c in checks
                            if c["name"] in hard_names) else "PASS")
    scalars = {"s11_f0_db": round(s11_f0, 3), "band_min_db": round(min_db, 3),
               "core_max_db": round(core_db, 3)}
    if template == "pyramid_horn":
        # 方向性如实注记（#122）：本席不可测（far_field=Ph3 未接线），
        # 离线锚 horn_gain_direct=15dB 由 test_pyramid_horn_template 承担
        checks.append({
            "name": "directivity", "ok": None,
            "detail": "本席不可测：renderer far_field 显式拒绝（Ph3 方向图窗）；"
                      "离线锚 horn_gain_direct=15dB 已由单测钉——不冒充真机判据",
        })
    return {"status": status, "checks": checks, "scalars": scalars,
            "nrts_policy": SEATS[template]["nrts_policy"]}


def judge_coax(ext: dict[str, Any], s: np.ndarray) -> dict[str, Any]:
    """transition 判据门：waveguide_refl 门 + S21@f0 插损门。"""
    out = judge_waveguide_refl(ext, s, COAX, "coax_waveguide_transition")
    s21_f0 = ext.get("s21_f0_db")
    s21_ok = None if s21_f0 is None else bool(s21_f0 >= COAX["s21_f0_min_db"])
    out["checks"].append({
        "name": "s21_f0", "ok": s21_ok,
        "detail": ("S21@10GHz 缺测（插损判据不可判，#314 缺测如实）"
                   if s21_f0 is None else
                   f"S21@10GHz={s21_f0}dB"
                   f"（门 ≥{COAX['s21_f0_min_db']}dB，首跑定标）"),
    })
    zl = ext.get("zl_wg_f0_ohm")
    lo, hi = COAX["zl_wg_info_ohm"]
    out["checks"].append({
        "name": "zl_wg_info", "ok": None if zl is None else bool(lo <= zl <= hi),
        "detail": f"ZL_WG@f0={zl}Ω（信息项 {lo}–{hi}Ω）",
    })
    if s21_ok is False:
        out["status"] = "FAIL"
    elif s21_ok is None and out["status"] == "PASS":
        # 缺测如实（#314/#316，review_slice6 P2-1）：S21 是本席两根判据主轴
        # 之一，整列缺位（渲染器端口面异常/解析列名漂移）不得冒充 PASS。
        out["status"] = "PARTIAL"
        out["reason"] = "s21_f0 缺测：插损判据不可判（#314 缺测如实降 PARTIAL）"
    out["scalars"]["s21_f0_db"] = None if s21_f0 is None else round(float(s21_f0), 3)
    out["scalars"]["zl_wg_f0_ohm"] = zl
    return out


def build_criteria(template: str) -> dict[str, Any]:
    """预声明判据快照（criteria.json 单源；先落盘后发射）。"""
    seat = SEATS[template]
    crit: dict[str, Any] = {
        "template": template,
        "declared_at": time.strftime("%F %T"),
        "band_ghz": list(seat["band_ghz"]),
        "mesh_mm": seat["mesh_mm"],
        "window_ns": seat["window_ns"],
        "nrts_policy": seat["nrts_policy"],
        "passive_max": PASSIVE_MAX,
        "clamp_guard_pts": CLAMP_GUARD_PTS,
        "first_run_calibration_note": (
            "无 meta/criteria 锚的窗为物理合理性窗（首跑定标）——跑后按实测"
            "形态裁决收窄/放宽，不得事后改窗凑绿（#122）"),
    }
    if template == "ring_resonator":
        crit["windows"] = dict(RING)
        crit["basis"] = (
            "F-A.3 Design Dk 提取回收（月计划 W3）：f_n≈n·c/(2π·r_mean·√εeff)"
            " 反演 εr；窗依据见模块头判据预声明；tanδ 分离（1/Q_L 三项）属"
            " core/dielectric_extract 后续批次，本席只交 f_n/εr 回收")
    elif template == "pyramid_horn":
        crit["windows"] = dict(HORN)
        crit["basis"] = (
            "ME-7 真机首跑冒烟：S11 匹配窗（首跑定标）；方向性本席不可测"
            "（far_field=Ph3 窗），离线锚 15dB 已由单测承担")
    else:
        crit["windows"] = dict(COAX)
        crit["basis"] = (
            "ME-6 真机首跑冒烟：插损/回损窗（首跑定标，官方 wiki 教程 pin "
            "比例档设计意图）；HFSS 仲裁=Ph3 窗")
    return crit


def load_fd_campaign():
    """importlib 复用 fd_oe_campaign 纯函数（单源不复制；#315 零跨轨改动）。"""
    spec = importlib.util.spec_from_file_location(
        "fd_oe_campaign", SCRIPTS / "fd_oe_campaign.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("fd_oe_campaign", mod)
    spec.loader.exec_module(mod)
    return mod


# ══ 预飞审计（离线零仿真：render→exec 几何段→网格/守卫/字面量实测）════════
_NRTS_LIT = re.compile(r"(?:NrTS=(\d+)|NRTS = (\d+))")


def _rel_close(a: float, b: float, rel: float = 1e-9) -> bool:
    """相对容差比较（单源核对口径与 test_template_meta_consistency 同 rel）。"""
    return bool(abs(float(a) - float(b)) <= rel * max(1.0, abs(float(b))))


def nominal_vs_docs(template: str, docs_dir: Path | None = None) -> dict[str, Any]:
    """名义参数单源核对：TEMPLATE_NOMINAL vs docs/templates/<t>/meta.yaml。"""
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL

    docs_dir = docs_dir or (REPO / "docs" / "templates")
    path = docs_dir / template / "meta.yaml"
    if not path.exists():
        return {"ok": False, "mismatches": ["meta.yaml 缺"], "docs_path": str(path)}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mism: list[str] = []
    doc_nom = data.get("nominal_params") or {}
    for key, val in TEMPLATE_NOMINAL[template].items():
        doc = doc_nom.get(key)
        if doc is None:
            mism.append(f"{key}(docs 缺)")
        elif not _rel_close(float(doc), float(val)):
            mism.append(f"{key}({doc}!={val})")
    for key in ("f0_ghz", "n_ports", "max_time_ns", "mesh_resolution_mm"):
        doc_v, src_v = data.get(key), TEMPLATE_META[template].get(key)
        if doc_v is None or src_v is None:
            mism.append(f"{key}(缺)")
        elif float(doc_v) != float(src_v):
            mism.append(f"{key}({doc_v}!={src_v})")
    return {"ok": not mism, "mismatches": mism, "docs_path": str(path)}


def preflight(template: str) -> dict[str, Any]:
    """单席预飞审计（离线零仿真；返回 dict 落 preflight/<t>.json）。

    审计面（#212 口径：CSXCAD 实测对象，非字符串存在性）：
    ① 渲染+exec 几何段（截"# ── 求解 ──"）→ 终网格三轴实测；
    ② 网格最小间距 ≥10µm（#349）+ dt CFL + NrTS 计划 + 脉冲覆盖度门
       （window ≥ 2×pulse，#262 FC 窗族）；
    ③ 原语非空 + 端口数 == meta n_ports（拓扑细判由三模板 #212 单测承担）；
    ④ 名义参数单源核对（TEMPLATE_NOMINAL vs docs meta.yaml）；
    ⑤ _nrts 渲染字面量生效确认（新接线面：三席不在 F-D 自动接线清单，
       本驱动显式旋钮路径——字面量验证渲染真吃到）。
    """
    from rfauto.adapters.openems_templates import (
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
        cfl_dt_s,
        render_script,
    )

    seat = SEATS[template]
    meta = TEMPLATE_META[template]
    band = tuple(seat["band_ghz"])
    mesh = float(seat["mesh_mm"])
    nominal = dict(TEMPLATE_NOMINAL[template])
    out: dict[str, Any] = {
        "template": template, "band_ghz": list(band), "mesh_mm": mesh,
        "window_ns": seat["window_ns"],
    }

    text = render_script(template, dict(nominal), band, mesh_resolution_mm=mesh)
    marker = text.find("# ── 求解 ──")
    cut = marker if marker >= 0 else text.index("FDTD.Run(")
    scope: dict[str, Any] = {
        "__name__": "__main__",
        "__file__": str(REPO / "_oe_phase3_preflight_sim.py")}
    exec(compile(text[:cut], "oe_phase3_preflight", "exec"), scope)
    lines: dict[str, int] = {}
    dmin: dict[str, float] = {}
    for ax in ("x", "y", "z"):
        ls = np.asarray(scope["mesh"].GetLines(ax), dtype=float)
        lines[ax] = int(ls.size)
        dmin[ax] = float(np.min(np.diff(ls)))
    dt = cfl_dt_s(dmin["x"], dmin["y"], dmin["z"])
    nrts = plan_nrts(seat["window_ns"], dt)
    cells = lines["x"] * lines["y"] * lines["z"]
    fc_ghz = abs(band[1] - band[0]) / 2.0
    pulse = pulse_est_s(fc_ghz)
    window_s = nrts * dt
    out.update(
        mesh_lines=lines, cells=cells,
        dmin_mm={k: round(v * 1e3, 4) for k, v in dmin.items()},
        dt_s=dt, nrts_plan=nrts, window_real_ns=round(window_s * 1e9, 2),
        fc_ghz=fc_ghz, pulse_est_ns=round(pulse * 1e9, 3),
        pulse_coverage=round(window_s / pulse, 2),
        est_wall_min=[round(cells * nrts / RATE_HI / 60),
                      round(cells * nrts / RATE_LO / 60)],
        meta_max_time_ns=float(meta.get("max_time_ns") or 0.0),
        window_derivation=(
            f"冒烟档 {seat['window_ns']}ns（< meta max_time_ns="
            f"{meta.get('max_time_ns')}ns 精算档；依据见模块头判据预声明）"),
    )
    out["checks"] = {
        "grid_min_spacing_ge_10um": bool(min(dmin.values()) >= GRID_MIN_SPACING_M),
        "pulse_coverage_ge_2": bool(window_s >= 2.0 * pulse),
        "ports_match_meta": (
            len([k for k in scope if k.startswith("_port") and k[5:].isdigit()])
            == int(meta["n_ports"])),
        "primitives_nonempty": bool(scope["CSX"].GetQtyProperties() > 0),
    }
    with contextlib.suppress(KeyError):
        del scope["CSX"], scope["FDTD"], scope["mesh"]

    # ⑤ _nrts 字面量生效（渲染真吃到旋钮）
    lit = render_script(template, dict(nominal, _nrts=nrts), band,
                        mesh_resolution_mm=mesh)
    m = _NRTS_LIT.search(lit)
    lit_nrts = int(m.group(1) or m.group(2)) if m else None
    out["nrts_literal"] = {"expected": nrts, "rendered": lit_nrts,
                           "ok": lit_nrts == nrts}
    out["checks"]["nrts_literal_flows"] = bool(lit_nrts == nrts)

    # ④ 名义单源核对
    out["nominal_vs_docs"] = nominal_vs_docs(template)
    out["checks"]["nominal_single_source"] = bool(out["nominal_vs_docs"]["ok"])

    # 真值注记：名义逐参流入（扰动重渲染字面量变化）由 fd_oe_campaign 的
    # _nominal_literal_check 在发射路径执行（G1），预飞不重复 exec。
    out["ok"] = all(bool(v) for v in out["checks"].values())
    return out


# ══ 发射/判读主路径 ══════════════════════════════════════════════════════
def _read_sparams_columns(path: Path) -> dict[str, np.ndarray] | None:
    """sparams.csv → {列名: 复数/实数组}（freq_hz + re/im_Sxx 对）。"""
    import csv as _csv

    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rows = [r for r in _csv.reader(fh)
                    if r and not r[0].lstrip().startswith(("%", "#"))]
        if len(rows) < 2 or len(rows[0]) < 3:
            return None
        header = [c.strip().lower() for c in rows[0]]
        if header[0] != "freq_hz":
            return None
        arr = np.array([[float(x) for x in r] for r in rows[1:]], dtype=float)
        if arr.ndim != 2 or arr.shape[1] != len(header):
            return None
        cols: dict[str, np.ndarray] = {"freq_hz": arr[:, 0]}
        for c in range(1, len(header) - 1, 2):
            name = header[c]
            if not (name.startswith("re_s") and name[4:].isdigit()
                    and len(name[4:]) == 2):
                return None
            cols["s" + name[4:]] = arr[:, c] + 1j * arr[:, c + 1]
        return cols
    except (OSError, ValueError):
        return None


def _offline_scalars(template: str, run_dir: Path) -> dict[str, Any] | None:
    """跑后离线收割（零仿真）：sparams.csv + renderer meta json。"""
    cols = _read_sparams_columns(run_dir / "sparams.csv")
    if cols is None:
        return None
    freqs = cols["freq_hz"]
    zl = None
    meta_name = {"pyramid_horn": "pyramid_horn_meta.json",
                 "coax_waveguide_transition": "coax_wg_meta.json"}.get(template)
    if meta_name and (run_dir / meta_name).exists():
        with contextlib.suppress(OSError, ValueError, json.JSONDecodeError):
            mj = json.loads((run_dir / meta_name).read_text(encoding="utf-8"))
            zl = mj.get("zl_wg_f0_ohm")
    if template == "ring_resonator":
        if "s21" not in cols:
            return None
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
        return extract_ring(freqs, cols["s11"], cols["s21"],
                            TEMPLATE_NOMINAL[template])
    s21 = cols.get("s21")
    return extract_waveguide(freqs, cols["s11"], s21, zl, template)


def _judge(template: str, ext: dict[str, Any], s: np.ndarray) -> dict[str, Any]:
    if template == "ring_resonator":
        return judge_ring(ext, s)
    if template == "pyramid_horn":
        return judge_waveguide_refl(ext, s, HORN, template)
    return judge_coax(ext, s)


def _harvest_s(run_dir: Path, fd) -> np.ndarray | None:
    """S 矩阵收割：磁盘 csv（掩码部分矩阵 #314 口径；fd 单源解析器）。"""
    return fd._parse_sparams_csv_disk(run_dir / "sparams.csv")


def _apply_gates(verdict: dict[str, Any], template: str, run_dir: Path,
                 fd) -> None:
    """NrTS 收敛门（per-seat policy）+ G11 掩码健康门（就地改写 verdict）。

    must_converge：触 NrTS 帽且能量未达判据 → PASS 降 FAIL（#266 口径）；
    record_only：如实留痕不动状态（ring 位置级冒烟档，触帽属预期）。
    G11：仅 verdict=="unhealthy"（真实 FAIL 证据）升 FAIL，suspect 只留痕
    （#314/#209 口径）。两门均 best-effort（#105：不成为主路径故障点）。
    """
    try:
        gate = fd.nrts_converged_gate(run_dir)
        verdict["nrts_converged"] = gate
        if (SEATS[template]["nrts_policy"] == "must_converge"
                and gate.get("ok") is False and verdict.get("status") == "PASS"):
            verdict["status"] = "FAIL"
            verdict["reason"] = f"nrts_converged: {gate.get('reason')}"
    except Exception as exc:   # best-effort #105
        verdict["nrts_converged"] = {"ok": None, "reason": f"gate error: {exc}"}
    try:
        from rfauto.service.health_service import health_check_run
        hc = health_check_run(run_dir.name, runs_dir=str(OUT_ROOT))
        verdict["g11_health"] = {k: hc.get(k)
                                 for k in ("verdict", "ok") if k in hc}
        if (hc.get("verdict") == "unhealthy" and verdict.get("status") == "PASS"):
            verdict["status"] = "FAIL"
            verdict["reason"] = "G11 health verdict=unhealthy（#314 真实 FAIL 证据）"
    except Exception as exc:   # best-effort #105
        verdict["g11_health"] = {"error": str(exc)[:120]}


def run_judge_only(targets: list[str]) -> int:
    """--judge-only：对既有 runs/oe_phase3/<t>/ 离线重判（零仿真零渲染）。"""
    fd = load_fd_campaign()
    summary: dict[str, dict] = {}
    for template in targets:
        run_dir = OUT_ROOT / template
        if not (run_dir / "sparams.csv").exists():
            print(f"[oe3-judge] {template}: SKIP（sparams.csv 缺，未跑或未完结）",
                  flush=True)
            continue
        crit_p = run_dir / "criteria.json"
        verdict: dict[str, Any] = {
            "template": template, "mode": "judge_only",
            "judged_at": time.strftime("%F %T"),
            "criteria": (json.loads(crit_p.read_text(encoding="utf-8"))
                         if crit_p.exists() else None),
        }
        ext = _offline_scalars(template, run_dir)
        s = _harvest_s(run_dir, fd)
        if ext is None or s is None or s.size == 0:
            verdict.update(status="PARTIAL", reason="S 参数产物缺/不可解析")
        else:
            verdict["extracted"] = {k: v for k, v in ext.items()
                                    if not isinstance(v, np.ndarray)}
            jd = _judge(template, ext, s)
            verdict["judge"] = jd
            verdict["status"] = jd["status"]
            _apply_gates(verdict, template, run_dir, fd)
        (run_dir / "verdict.json").write_text(
            json.dumps(verdict, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8")
        summary[template] = verdict
        print(f"[oe3-judge] {template}: {verdict['status']}", flush=True)
    (OUT_ROOT / "campaign_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    return 0


def _render_for_check(template, params, band, mesh_resolution_mm=0.0):
    """_nominal_literal_check 的 render_fn 适配（基渲染不带本驱动旋钮）。"""
    from rfauto.adapters.openems_templates import render_script

    return render_script(template, dict(params), band,
                         mesh_resolution_mm=mesh_resolution_mm)


def run_solve(targets: list[str], timeout_s: float) -> int:
    """发射主路径（solo 串行；调用前确认 #261 互斥——LAUNCH.md 口径）。"""
    fd = load_fd_campaign()
    from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
    from rfauto.adapters.openems_solver import OpenEMSSolver
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    summary: dict[str, dict] = {}
    for template in targets:
        seat = SEATS[template]
        run_dir = OUT_ROOT / template
        run_dir.mkdir(parents=True, exist_ok=True)
        criteria = build_criteria(template)
        (run_dir / "criteria.json").write_text(
            json.dumps(criteria, ensure_ascii=False, indent=1), encoding="utf-8")
        verdict: dict[str, Any] = {
            "template": template, "started": time.strftime("%F %T"),
            "criteria": criteria,
        }
        band = tuple(seat["band_ghz"])
        mesh = float(seat["mesh_mm"])
        params = dict(TEMPLATE_NOMINAL.get(template, {}))
        t0 = time.time()
        try:
            # 预飞（零仿真）：网格/NrTS 计划/守卫红即不烧真机墙钟
            pre = preflight(template)
            verdict["preflight"] = pre
            if not pre["ok"]:
                raise RuntimeError(f"预飞门红: {pre['checks']}")

            # G1 渲染 + 名义参数流入自证（fd_oe_campaign 同款）
            flowed, text = fd._nominal_literal_check(
                template, params, band, mesh, _render_for_check)
            verdict["nominal_literal"] = {
                "flowed": flowed,
                "all_swallowed": all(v is False for v in flowed.values())}
            if all(v is False for v in flowed.values()):
                raise RuntimeError("G1: 名义参数全部未流入（恒{}回归签名）")
            (run_dir / "simulation.py").write_text(text, encoding="utf-8")

            # G2 真跑（solo 串行；_nrts 显式旋钮 = 预飞 NrTS 计划）
            params["_nrts"] = int(pre["nrts_plan"])
            solver = OpenEMSSolver(EMSolverConfig(
                solver_type="openems", exe_path=resolve_openems_exe(),
                working_dir=str(run_dir), freq_range_ghz=band,
                mesh_resolution_mm=mesh,
                extra_params={"solve_timeout_s": float(timeout_s)}))
            if not solver.connect():
                raise RuntimeError("openEMS 不可用")
            if not solver.build_geometry(
                    {"template": template, "params": dict(params)}):
                raise RuntimeError("build_geometry 失败")
            result = solver.solve()
        except Exception as exc:
            verdict["wall_s"] = round(time.time() - t0, 1)
            with contextlib.suppress(Exception):
                verdict["artifacts"] = fd._harvest_artifacts(run_dir)
            verdict.update(status="FAIL",
                           reason=f"G1/G2: {type(exc).__name__}: {str(exc)[:160]}")
            _save_verdict(run_dir, verdict)
            summary[template] = verdict
            print(f"[oe3] {template}: FAIL ({str(verdict['reason'])[:80]})",
                  flush=True)
            continue
        verdict["wall_s"] = round(time.time() - t0, 1)
        verdict["solve_success"] = bool(getattr(result, "success", False))
        with contextlib.suppress(Exception):
            verdict["artifacts"] = fd._harvest_artifacts(run_dir)

        ext = _offline_scalars(template, run_dir)
        s = _harvest_s(run_dir, fd)
        if ext is None or s is None or s.size == 0:
            verdict.update(status="PARTIAL", reason="S 参数产物缺/不可解析")
            _save_verdict(run_dir, verdict)
            summary[template] = verdict
            continue
        verdict["extracted"] = {k: v for k, v in ext.items()
                                if not isinstance(v, np.ndarray)}
        jd = _judge(template, ext, s)
        verdict["judge"] = jd
        verdict["status"] = jd["status"]
        if not verdict["solve_success"] and verdict["status"] == "PASS":
            verdict["status"] = "PARTIAL"
            verdict["reason"] = "求解器报告未正常结束（数值面健康，如超时截断）"
        _apply_gates(verdict, template, run_dir, fd)
        _save_verdict(run_dir, verdict)
        summary[template] = verdict
        print(f"[oe3] {template}: {verdict['status']} wall={verdict['wall_s']}s",
              flush=True)
    (OUT_ROOT / "campaign_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    counts: dict[str, int] = {}
    for v in summary.values():
        counts[v.get("status", "?")] = counts.get(v.get("status", "?"), 0) + 1
    print("[oe3] SUMMARY:", json.dumps(counts, ensure_ascii=False), flush=True)
    return 0


def _save_verdict(run_dir: Path, verdict: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")


def run_preflight_only(targets: list[str]) -> int:
    """--preflight-only：席位预飞审计落 runs/oe_phase3/preflight/（零仿真）。"""
    pdir = OUT_ROOT / "preflight"
    pdir.mkdir(parents=True, exist_ok=True)
    all_ok = True
    for template in targets:
        out = preflight(template)
        (pdir / f"{template}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        all_ok &= bool(out["ok"])
        print(f"[oe3-preflight] {template}: "
              f"{'OK' if out['ok'] else 'RED ' + str(out['checks'])} "
              f"cells={out['cells'] / 1e6:.1f}M NrTS={out['nrts_plan']} "
              f"est={out['est_wall_min']}min", flush=True)
    crit = {t: build_criteria(t) for t in targets}
    (pdir / "criteria_snapshot.json").write_text(
        json.dumps(crit, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[oe3-preflight] 产物: {pdir}", flush=True)
    return 0 if all_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OE 三期发射编排驱动（判据预声明见脚本头；零 src 改动）")
    parser.add_argument("--only", default=",".join(TARGETS),
                        help="逗号分隔模板子集（缺省三席全跑）")
    parser.add_argument("--timeout", type=float, default=7200.0,
                        help="单席求解超时秒（缺省 7200=2h 硬上界）")
    parser.add_argument("--preflight-only", action="store_true",
                        help="只跑离线预飞审计（零仿真），落 preflight/")
    parser.add_argument("--judge-only", action="store_true",
                        help="只对既有产物离线重判（零仿真），刷新 verdict.json")
    args = parser.parse_args()
    targets = [t.strip() for t in args.only.split(",") if t.strip()]
    unknown = [t for t in targets if t not in SEATS]
    if unknown:
        parser.error(f"未知席位: {unknown}（可用: {TARGETS}）")
    if args.preflight_only:
        return run_preflight_only(targets)
    if args.judge_only:
        return run_judge_only(targets)
    return run_solve(targets, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
