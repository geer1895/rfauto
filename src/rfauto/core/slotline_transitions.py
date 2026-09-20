"""MSL↔slotline 过渡 + Marchand 巴伦：理论核验、设计参数与判据计算。

理论核验（零仿真；公式与常数逐个有出处，
不凭记忆写未核对的式子；无法双源核对的量只给"文献典型量级"并标注口径级别）
================================================================================

一、经典 MSL↔slotline 过渡（Roberts/Knorr 口径，本项 render_msl_slot_transition）
--------------------------------------------------------------------------------
拓扑（双层板：顶层微带、底层地板开槽，正交跨越）：
- 微带馈线跨过槽线后继续延伸一段 **开路 λg_m/4 支节**（含开路端修正 Δl）：
  开路经 λ/4 变换 → 跨越点处**虚短路**（Z_in = −j·Z_stub·cot(βl)，βl=π/2 时为 0）；
- 槽线自跨越点向另一侧延伸 **短路 λg_s/4 段**（文献经典实现=圆形金属短路盘，
  半径 ≈ λg'/4；本最小族用矩形金属桥接封口，二阶差异如实记录）：
  短路经 λ/4 变换 → 跨越点处**虚开路**（Z_in = j·Z_slot·tan(βl)，βl=π/2 时为 ∞）；
- 机理：虚短路使微带电流在跨越点最大，位移电流跨槽桥接、激励槽线模式向输出
  臂行进；虚开路阻止能量泄入短接支节臂。

出处：
- W. K. Roberts, "A New Wide-Band Balun," Proc. IRE 45(12), pp. 1628–1631,
  Dec. 1957（微带开路支节 + 槽线 λ/4 短路的过渡原形，锥削槽线天线文献
  （Yngvesson 等）沿用称 Roberts transition）。
- J.-B. Knorr, "Slot-Line Transitions," IEEE Trans. MTT-22(5), pp. 548–554,
  May 1974（等效电路与设计分析）。
- B. Schuppert, "Microstrip/Slotline Transitions: Modeling and Experimental
  Investigation," IEEE Trans. MTT-36(8), pp. 1272–1282, Aug. 1988（建模与
  带宽实证：非补偿结典型约一个倍频程量级带宽）。
- R. Garg, I. Bahl, M. Bozzi, "Microstrip Lines and Slotlines," 3rd ed.,
  Artech House, 2013（transitions/baluns 汇总章；本项参数表的书级权威口径）。

设计式（本模块实现）：
- 微带 50Ω 线宽 w_m 与 εeff_m：skrf HJ 综合（core/synthesis.inverse_width /
  forward_z0，线宽一律综合精算不拍脑袋）。
- 支节长 l_stub = λg_m/4 + Δl_open；Hammerstad 经典开路端修正
  Δl = h·0.412·(εeff+0.3)·(w/h+0.264) / [(εeff−0.258)·(w/h+0.813)]
  （Hammerstad 1975 族闭式，CAD 工具通用口径；微带 w=3.344/h=1.524、
  εeff=2.853 @2.5GHz → Δl≈0.624mm，量级 0.4h，二阶但计入）。
- 槽线短路段长 l_short = λg'/4（λg' 由 core/slotline 闭式；槽宽有效域同其
  0.006≤d/λ0≤0.06、窄槽段域检查，超域 ValueError 不外推）。
- 文献典型性能（书级口径，非单篇引用）：单过渡插损 ≈0.5–1dB；背靠背对
  ≈1–1.5dB；带内回损 ≲−10dB 带宽约一个倍频程（Schuppert 1988 口径）；
  补偿/渐变（多节或锥削槽线、径向短截）可展宽，本最小族 v1 不含渐变
  （渐变形状=文献宽带化选项，列 followUps）。

二、Marchand 巴伦最小族（本项 render_marchand_balun，双槽臂口径）
--------------------------------------------------------------------------------
原理（N. Marchand, "Transmission-Line Conversion Transformers," Electronics
17(12), pp. 142–145, Dec. 1944）：两段耦合线节串接——不平衡输入沿主线（原边）
依次穿过两个耦合区；两个副边的近端构成平衡端子对，远端短接（接地变体）。
平面双槽线实现（本项定版几何）：
- 底层地板开**两条平行槽**（槽宽 s、中心距 d_c，中条带宽 d_c−s 取=微带宽 w_m：
  跨越区局地回流路径连续），槽 1 开口朝 +x（右端输出、左端在 −λg'/4 处封口
  短路），槽 2 镜像（左端输出、右端封口）；
- 顶层微带自边缘（P1）沿 y 垂直穿过两槽，跨越槽 2 后延伸 λg_m/4+Δl 开路支节
  （与单过渡同机理：两跨越点各成一个 Roberts 型过渡，共享同一开路支节与两段
  λg'/4 短路臂——串接两节的最小 Marchand）；
- 输出口径：P2/P3 = 各槽远端跨槽口（本栈 LumpedPort，R=槽线 Z0 端接），
  每口自带平衡端对（槽两缘）——"双平衡输出"。单端对地测量每臂理想 −3dB
  （与文献巴伦单端口测量口径一致，任务门 |S21|≥−3.5dB 同源）。
- 相位约定（重要，判读 0°/180° 必须先定极性）：两口 start/stop 均按 y 递增
  方向（槽 1 口跨[中条→外地]、槽 2 口跨[外地→中条]）——该极性下**推挽平衡
  （对中条反相）⇒ 两口电压同相**；若读出 ≈180° 则结构实为同相分配器。
  幅度/回损/隔离门与极性无关。

文献典型（书级口径）：Marchand 巴伦多倍频程（≈2:1 起步，补偿版更宽）；
带内幅度不平衡 ≲1dB；单臂插损（含结损耗）−3.5~−4.5dB；平衡臂间隔离
典型 >10–15dB（无耗互易三口不可全匹配+全隔离，S23 与匹配/损耗联动，
判据冲突时如实 PARTIAL 归因）。

三、openEMS 逐引擎修正（synthesize_marchand_two_section(engine=)，2026-09-18 标定）
--------------------------------------------------------------------------------
"reference"（缺省）=HJ 综合现状（输出逐字节不变）；"openems"=本仓 openEMS 逐档
修正：Z0 目标经 engine_z0_correction（4 点直微带线标定 PCHIP@log10 w，数据
marchand_line_calibration 标定）预畸变反解设计宽（耦合段 + w_feed/w_bal 同曲线
定点），节长按 β +2% 常数缩短。**标定基准=直微带单线，耦合段 Z0e/Z0o 适用性是
外推**（修正模型/适用域/域外钳制详见 engine_z0_correction docstring）。

有效域与检查
------------
- 槽线闭式有效域：继承 core/slotline（0.006≤d/λ0≤0.06、窄槽段 0.0015≤W/λ0
  ≤0.075、εr∈[2.22,9.8]），运行时逐频检查、超域 ValueError 不外推；
- 微带 HJ 综合域：skrf MLine 常规域（h/λ0 适中），λ/4 近似在 f0±倍频程内
  一阶有效；
- 设计点（与路线 A/B 同，三方可比）：f0=2.5GHz、RO4350B 60mil（h=1.524、
  εr=3.66、tanδ=0.0037）、槽宽 1.0mm → 闭式 Z0=110.92Ω/εeff=1.6462/
  λ'=93.4624mm；微带 50Ω w=3.3439mm/εeff=2.8530 → l_stub=18.3725mm、
  l_short=23.3656mm、d_c=4.3439mm。

判据（预声明，真机不凑绿 #122）
--------------------------------
- 过渡段：带内(2.25–2.75GHz) max|S11|≤−10dB（P1 线基）；S21 对"理想 DUT
  抽头模型基线"的超额损耗 ≤1dB@f0（基线由 scripts 层 tap_network_sparams
  计算——分层：core 不 import adapters）；β 对闭式 ≤5%（信息门）。
- 巴伦（预声明门写死）：带内幅度不平衡 ≤1dB；P1 回损 ≤−10dB；隔离
  |S23| ≤−15dB；带内 |S21| ≥−3.5dB；相位差按上述极性约定如实报告。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any

from rfauto.core.slotline import C0, slotline_closed_form
from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

#: 判据带（f0±10%，与路线 B 同）
BAND_GHZ_DEFAULT: tuple[float, float] = (2.25, 2.75)
#: 巴伦预声明门
BALUN_GATES = {
    "amp_imbalance_db_le": 1.0,
    "rl_db_le": -10.0,
    "isolation_db_le": -15.0,
    "s21_db_ge": -3.5,
}
#: 过渡段门（本项预声明）
TRANSITION_GATES = {
    "band_max_s11_db_le": -10.0,
    "excess_loss_db_f0_le": 1.0,
}


def microstrip_open_end_delta_l_mm(w_mm: float, h_mm: float,
                                   eps_eff: float) -> float:
    """Hammerstad 经典微带开路端修正 Δl（mm）。

    Δl = h·0.412·(εeff+0.3)·(w/h+0.264) / [(εeff−0.258)·(w/h+0.813)]
    （出处见模块 docstring 一；w/h>0、εeff>0.258 域内有效）。
    """
    if not (w_mm > 0 and h_mm > 0 and eps_eff > 0.258):
        raise ValueError(
            f"microstrip_open_end_delta_l_mm: 输入超有效域 "
            f"w={w_mm!r} h={h_mm!r} eps_eff={eps_eff!r}")
    r = w_mm / h_mm
    return h_mm * 0.412 * (eps_eff + 0.3) * (r + 0.264) / (
        (eps_eff - 0.258) * (r + 0.813))


@dataclass(frozen=True)
class TransitionDesign:
    """Roberts/Knorr 过渡设计参数（全部 mm/Ω，米制换算在适配层）。"""

    f0_ghz: float
    w_slot_mm: float
    h_mm: float
    er: float
    # 槽线侧（闭式锚）
    z_slot_ohm: float
    eps_eff_slot: float
    lambda_slot_mm: float
    l_short_mm: float                 # 槽线短路臂 λg'/4
    # 微带侧（HJ 综合锚）
    w_msl_mm: float
    z_msl_ohm: float
    eps_eff_msl: float
    l_stub_mm: float                  # 开路支节 λg_m/4 + Δl_open
    dl_open_mm: float

    def to_dict(self) -> dict:
        return {
            "f0_ghz": self.f0_ghz, "w_slot_mm": self.w_slot_mm,
            "h_mm": self.h_mm, "er": self.er,
            "z_slot_ohm": round(self.z_slot_ohm, 4),
            "eps_eff_slot": round(self.eps_eff_slot, 6),
            "lambda_slot_mm": round(self.lambda_slot_mm, 4),
            "l_short_mm": round(self.l_short_mm, 4),
            "w_msl_mm": round(self.w_msl_mm, 4),
            "z_msl_ohm": round(self.z_msl_ohm, 4),
            "eps_eff_msl": round(self.eps_eff_msl, 6),
            "l_stub_mm": round(self.l_stub_mm, 4),
            "dl_open_mm": round(self.dl_open_mm, 4),
        }


def transition_design(f0_ghz: float, h_mm: float, er: float,
                      w_slot_mm: float, tan_d: float = 0.0037,
                      z_msl_target: float = 50.0) -> TransitionDesign:
    """Roberts/Knorr 过渡设计参数（理论核验轮产物，几何模板消费）。

    线宽/长度全部由闭式精算：微带 skrf HJ 综合、槽线 core/slotline 闭式
    （超有效域显式 ValueError，不外推）。
    """
    cf = slotline_closed_form(w_slot_mm, h_mm, er, f0_ghz)
    stack = Stackup(name="design", epsilon_r=er, thickness_mm=h_mm,
                    loss_tangent=tan_d)
    w_m, _z_m, _status = inverse_width(z_msl_target, f0_ghz, stack)
    z_m_chk, eps_m = forward_z0(w_m, f0_ghz, stack)
    lam_m = C0 / (f0_ghz * 1e9) / math.sqrt(eps_m) * 1e3
    dl = microstrip_open_end_delta_l_mm(w_m, h_mm, eps_m)
    return TransitionDesign(
        f0_ghz=f0_ghz, w_slot_mm=w_slot_mm, h_mm=h_mm, er=er,
        z_slot_ohm=cf.z0_ohm, eps_eff_slot=cf.eps_eff,
        lambda_slot_mm=cf.lambda_ratio * C0 / (f0_ghz * 1e9) * 1e3,
        l_short_mm=cf.lambda_ratio * C0 / (f0_ghz * 1e9) * 1e3 / 4.0,
        w_msl_mm=w_m, z_msl_ohm=z_m_chk, eps_eff_msl=eps_m,
        l_stub_mm=lam_m / 4.0 + dl, dl_open_mm=dl)


@dataclass(frozen=True)
class MarchandDesign(TransitionDesign):
    """双槽臂 Marchand 巴伦设计参数（在过渡参数上加槽距）。"""

    d_center_mm: float = 0.0           # 两槽中心距（=w_msl+s_slot）

    @property
    def a1_mm(self) -> float:          # 槽内缘到中线（中条半宽）
        return self.d_center_mm / 2.0 - self.w_slot_mm / 2.0

    @property
    def a2_mm(self) -> float:          # 槽外缘到中线
        return self.d_center_mm / 2.0 + self.w_slot_mm / 2.0

    def to_dict(self) -> dict:
        return {**super().to_dict(), "d_center_mm": round(self.d_center_mm, 4),
                "a1_mm": round(self.a1_mm, 4), "a2_mm": round(self.a2_mm, 4)}


def marchand_design(f0_ghz: float, h_mm: float, er: float,
                    w_slot_mm: float, tan_d: float = 0.0037,
                    z_msl_target: float = 50.0) -> MarchandDesign:
    """Marchand 双槽臂巴伦设计参数：d_c = w_m + s（中条宽=微带宽）。"""
    base = transition_design(f0_ghz, h_mm, er, w_slot_mm, tan_d, z_msl_target)
    base_kw = {f.name: getattr(base, f.name) for f in fields(TransitionDesign)}
    return MarchandDesign(**base_kw,
                          d_center_mm=base.w_msl_mm + base.w_slot_mm)


# ───────────────────────── 判据/指标计算（纯函数，两引擎共用） ─────────────────────────

def _band_mask(f_hz, band_ghz):
    import numpy as np

    return ((np.asarray(f_hz, dtype=float) >= band_ghz[0] * 1e9)
            & (np.asarray(f_hz, dtype=float) <= band_ghz[1] * 1e9))


def _db(c):
    import numpy as np

    return 20.0 * np.log10(np.abs(np.asarray(c)) + 1e-300)


def transition_metrics(f_hz, s11, s21, band_ghz=BAND_GHZ_DEFAULT,
                       s21_ideal_db_f0: float | None = None,
                       beta_probe_f0: float | None = None,
                       beta_closed_f0: float | None = None) -> dict:
    """过渡段指标（P1 线基 S11/S21；s21_ideal_db_f0=理想 DUT 抽头基线 dB）。

    excess_loss_db_f0 = s21_ideal_db_f0 − |S21|@f0(dB)（≥0 为超额损耗，正=更损耗；
    基线 None 时只报 |S21| 不判损耗门——如实缺项）。
    """
    import numpy as np

    f_hz = np.asarray(f_hz, dtype=float)
    m = _band_mask(f_hz, band_ghz)
    i0 = int(np.argmin(np.abs(f_hz - 0.5 * (band_ghz[0] + band_ghz[1]) * 1e9)))
    s11_db = _db(s11)
    s21_db = _db(s21)
    out = {
        "band_ghz": list(band_ghz),
        "s11_db_f0": float(s11_db[i0]),
        "s21_db_f0": float(s21_db[i0]),
        "band_max_s11_db": float(np.max(s11_db[m])),
        "band_min_s21_db": float(np.min(s21_db[m])),
        "passivity_max": float(np.max(np.abs(np.asarray(s11)[m]) ** 2
                                      + np.abs(np.asarray(s21)[m]) ** 2)),
        "gates": {
            "band_max_s11_le_minus10db":
                bool(np.max(s11_db[m]) <= TRANSITION_GATES["band_max_s11_db_le"]),
        },
    }
    if s21_ideal_db_f0 is not None:
        # 超额损耗 = 理想基线 − 实测（dB，正=更损耗；dB 更负即损耗更大）
        exc = float(s21_ideal_db_f0) - float(s21_db[i0])
        out["s21_ideal_baseline_db_f0"] = float(s21_ideal_db_f0)
        out["excess_loss_db_f0"] = exc
        out["gates"]["excess_loss_f0_le_1db"] = bool(
            exc <= TRANSITION_GATES["excess_loss_db_f0_le"])
    if beta_probe_f0 is not None and beta_closed_f0:
        out["beta_probe_f0_rad_m"] = float(beta_probe_f0)
        out["beta_closed_f0_rad_m"] = float(beta_closed_f0)
        out["beta_vs_closed_pct"] = (float(beta_probe_f0) / float(beta_closed_f0)
                                     - 1.0) * 100.0
    return out


def balun_metrics(f_hz, s11, s21, s31, s23=None,
                  band_ghz=BAND_GHZ_DEFAULT) -> dict:
    """巴伦指标（预声明门写死；相位差按模板极性约定如实报告）。

    相位约定（见模块 docstring 二）：两口 start/stop 同为 y 递增 →
    push-pull 平衡 ⇒ phase_diff ≈ 0°；≈180° ⇒ 实为同相分配器。
    """
    import numpy as np

    f_hz = np.asarray(f_hz, dtype=float)
    s11 = np.asarray(s11, dtype=complex)
    s21 = np.asarray(s21, dtype=complex)
    s31 = np.asarray(s31, dtype=complex)
    m = _band_mask(f_hz, band_ghz)
    i0 = int(np.argmin(np.abs(f_hz - 0.5 * (band_ghz[0] + band_ghz[1]) * 1e9)))
    s21_db, s31_db, s11_db = _db(s21), _db(s31), _db(s11)
    imb = s21_db - s31_db
    ph = np.angle(s31 * np.conj(s21), deg=True)
    out = {
        "band_ghz": list(band_ghz),
        "s11_db_f0": float(s11_db[i0]),
        "s21_db_f0": float(s21_db[i0]),
        "s31_db_f0": float(s31_db[i0]),
        "amp_imbalance_db_f0": float(imb[i0]),
        "phase_diff_deg_f0": float(ph[i0]),
        "band_max_s11_db": float(np.max(s11_db[m])),
        "band_min_s21_db": float(np.min(s21_db[m])),
        "band_max_abs_imbalance_db": float(np.max(np.abs(imb[m]))),
        "phase_diff_deg_band_mean": float(np.mean(ph[m])),
        "gates": {
            "amp_imbalance_le_1db": bool(
                np.max(np.abs(imb[m])) <= BALUN_GATES["amp_imbalance_db_le"]),
            "rl_le_minus10db": bool(
                np.max(s11_db[m]) <= BALUN_GATES["rl_db_le"]),
            "s21_ge_minus3p5db": bool(
                np.min(s21_db[m]) >= BALUN_GATES["s21_db_ge"]),
        },
    }
    if s23 is not None:
        s23_db = _db(np.asarray(s23, dtype=complex))
        out["s23_db_f0"] = float(s23_db[i0])
        out["band_max_s23_db"] = float(np.max(s23_db[m]))
        out["gates"]["isolation_le_minus15db"] = bool(
            np.max(s23_db[m]) <= BALUN_GATES["isolation_db_le"])
    return out


# ═══════════════ 三、真 Marchand：两节对称耦合段电路级综合（2026-09-18）═══════════════
#
# 背景：双槽臂"单支节串接=最小 Marchand"猜想四门 FAIL 两引擎
# 互证→证伪（共享单支节使两跨越点激励不对称、拓扑无隔离机制）。真 Marchand 必须是
# **两节 λ/4 耦合段、各臂独立端接**（Marchand 1944 原理；Cloete 1979 精确综合；
# Ang & Robertson, IEEE MTT-49(2) 2001 阻抗变换型分析）。本段只做确定性电路级内核
# （数值只在内核）：
#
# ① 对称耦合线四端口 Z 矩阵——偶/奇模叠加推导（本模块自推，Pozar §7.6 同源）：
#    单模 TL 二端口 Z = −jZ0[[cotθ, cscθ],[cscθ, cotθ]]；V1=Ve+Vo、V3=Ve−Vo、
#    Ie=(I1+I3)/2、Io=(I1−I3)/2 ⇒ 同线同端 −j(Z0e+Z0o)cotθ/2、同线对端
#    −j(Z0e+Z0o)cscθ/2、异线同端 −j(Z0e−Z0o)cotθ/2、异线对端 −j(Z0e−Z0o)cscθ/2。
#    独立裁判（单测）：全端口 Z_c=√(Z0e·Z0o) 端接的四端口 S 逐点对照 adapters 的
#    Pozar (7.83)/(7.84) 闭式 coupled_line_coupler_sparams（两份独立实现）。
# ② 两节 Marchand 网络：通用端口约束消元（短路 V=0 / 开路 I=0 / 内连 V 等 I 反 /
#    外部端口单位电流激励）→ 3 端口 Z → S（实参考阻抗归一）。**拓扑定版**：
#    节 1：主线近端=P1（不平衡）、主线远端→结点、副线近端**短路**、副线远端→平衡 A；
#    节 2：主线近端=结点、主线远端**开路**、副线近端→平衡 B、副线远端**短路**。
# ③ f0（θ=π/2，cotθ=0、cscθ=1）闭式（手算推导，与 ② 数值逐位互证，单测钉住）：
#    记 P=(Z0e+Z0o)/2、M=(Z0e−Z0o)/2。副线短路条件 ⇒ I_b1=−(P/M)I_d1、
#    I_a2=−(P/M)I_c2，结点 I_a2=−I_b1 ⇒ **I_c2=−I_d1**（两平衡端电流等幅反相）；
#    单端端接 Z_t 时 V_A=−V_B=j(Z0e·Z0o)/(2M)·I_a1，
#    **Z_in = 2(Z0e·Z0o)²/((Z0e−Z0o)²·Z_t)**。
#    匹配 Z_s ⇒ Z0e·Z0o/(Z0e−Z0o)=√(Z_s·Z_t/2)；以 C=(Z0e−Z0o)/(Z0e+Z0o)、
#    Z_c=√(Z0e·Z0o) 改写：**C = 1/√(1+2·Z_s·Z_t/Z_c²)**，
#    Z0e=Z_c√((1+C)/(1−C))、Z0o=Z_c√((1−C)/(1+C))。
#    Z_s=Z_t=Z_c=50Ω ⇒ C=1/√3（−4.77dB）、(Z0e,Z0o)=(96.59, 25.88)Ω——与常规
#    Marchand 文献常引设计点一致（推导后核对，非抄录；数值互证见单测）。
# ④ 几何：KJ 偶/奇模闭式二维反解 (w,s)（core/coupled_microstrip 正向，嵌套
#    brentq，与 adapters.coupled_bpf_width_gap_from_zee_zoo 同法、core 层独立实现，
#    分层不可反向 import）；节长 λ/4 @ (εeff_e+εeff_o)/2（耦合器族同口径）；
#    50Ω 馈线 / Z_t 平衡臂线宽 skrf HJ 综合；平衡侧若走槽线：Z_L 槽宽由
#    core/slotline 闭式反解（越域 None 如实），过渡段 λ/4 参数复用 transition_design。
# ⑤ 预声明验收门（真机渲染冒烟前写死，#122 不凑绿）：MARCHAND2_GATES。
#    模型自检：综合点必须过自身电路级门（否则综合不自洽）。
# 局限如实：无耗 TEM 理想耦合线（无偶/奇模相速差、无结区寄生、无导体/介质损耗）；
# θ=kπ 处 Z 矩阵奇异（csc），扫频须避开 f=2k·f0（本设计带 f0±30% 内无此点）。

#: 两节对称 Marchand 预声明门（f0±10% 带内；真机冒烟按此判读，原始值并列如实）
MARCHAND2_GATES = {
    "band_max_s11_db_le": -10.0,
    "band_min_s21_db_ge": -3.5,
    "band_min_s31_db_ge": -3.5,
    "band_max_abs_imbalance_db_le": 1.0,
    "band_max_phase_error_deg_le": 10.0,   # |Δφ − 180°|
}


def coupled_line_z_matrix(z0e: float, z0o: float, theta_rad) -> Any:
    """对称耦合线四端口 Z 矩阵（无耗 TEM）：端口序 0=线1近端 1=线1远端 2=线2近端 3=线2远端。

    theta_rad 标量或 (nf,) 数组 → (4,4) 或 (nf,4,4) 复矩阵；θ=kπ 奇异显式报错。
    推导见段首 ①（偶/奇模叠加）。
    """
    import numpy as np

    ze, zo = float(z0e), float(z0o)
    if not (ze > 0.0 and zo > 0.0 and ze > zo):
        raise ValueError(f"coupled_line_z_matrix: 须 Z0e > Z0o > 0，得 ({ze}, {zo})")
    th = np.asarray(theta_rad, dtype=float)
    if np.any(np.abs(np.sin(th)) < 1e-12):
        raise ValueError("coupled_line_z_matrix: θ=kπ 处 cscθ 奇异（避开 f=2k·f0）")
    cot = np.cos(th) / np.sin(th)
    csc = 1.0 / np.sin(th)
    p = -0.5j * (ze + zo)
    m = -0.5j * (ze - zo)
    z = np.zeros((*th.shape, 4, 4), dtype=complex)
    for i in range(4):
        z[..., i, i] = p * cot
    for i, j in ((0, 1), (2, 3)):
        z[..., i, j] = z[..., j, i] = p * csc
    for i, j in ((0, 2), (1, 3)):
        z[..., i, j] = z[..., j, i] = m * cot
    for i, j in ((0, 3), (1, 2)):
        z[..., i, j] = z[..., j, i] = m * csc
    return z


def reduce_z_network(z_full, external, shorts=(), opens=(), connections=()) -> Any:
    """通用端口约束消元：(…,n,n) 全 Z → 外部端口 (…,n_ext,n_ext) Z。

    约束（每端口恰一条）：shorts V_k=0；opens I_k=0；connections (i,j) 内连
    V_i=V_j 且 I_i+I_j=0；external 端口按单位电流逐列激励（其余外部端口开路）。
    未被任何约束覆盖/重复覆盖的端口显式报错。

    **病态警告（本项实证）**：外部端口开路激励在内部谐振点（θ=π/2 的 λ/4
    短路/开路副线）线性系统奇异，S 参数须走端接口径 reduce_to_s_matrix；
    本函数只用于非谐振 θ 的 Z 参数（单测对照解析）。
    """
    import numpy as np

    z = np.asarray(z_full, dtype=complex)
    n = z.shape[-1]
    ext = [int(k) for k in external]
    covered: list[int] = list(ext) + [int(k) for k in shorts] + [int(k) for k in opens]
    for i, j in connections:
        covered += [int(i), int(j)]
    if sorted(covered) != list(range(n)):
        raise ValueError(
            f"reduce_z_network: 端口约束须恰好覆盖 0..{n - 1} 各一次，得 {sorted(covered)}")
    lead = z.shape[:-2]
    a = np.zeros((*lead, n, n), dtype=complex)
    b = np.zeros((*lead, n, len(ext)), dtype=complex)
    for col, p in enumerate(ext):
        a[..., p, p] = 1.0
        b[..., p, col] = 1.0
    for k in opens:
        a[..., int(k), int(k)] = 1.0
    for k in shorts:
        a[..., int(k), :] = z[..., int(k), :]
    for i, j in connections:
        i, j = int(i), int(j)
        a[..., i, :] = z[..., i, :] - z[..., j, :]
        a[..., j, i] = 1.0
        a[..., j, j] = 1.0
    currents = np.linalg.solve(a, b)            # (…, n, n_ext)
    volts = z @ currents                         # (…, n, n_ext)
    return volts[..., ext, :]


def reduce_to_s_matrix(z_full, external, z_ref, shorts=(), opens=(),
                       connections=()) -> Any:
    """端口约束消元直接出 S：外部端口按参考阻抗端接、逐端口单位入射波激励。

    与 reduce_z_network 同一约束语义，但外部端口方程改为
    V_k + Z_k·I_k = 2√Z_k·δ_kp（入射波 a_p=1，其余外部端口 Z_k 端接），
    S_kp = (V_k − Z_k·I_k)/(2√Z_k)。端接使谐振（如 θ=π/2 的 λ/4 短路/开路副线）
    不再产生开路激励下的奇异线性系统——reduce_z_network 在该处病态（实证）。
    """
    import numpy as np

    z = np.asarray(z_full, dtype=complex)
    n = z.shape[-1]
    ext = [int(k) for k in external]
    zr = np.asarray(z_ref, dtype=float).reshape(len(ext))
    if np.any(zr <= 0.0):
        raise ValueError("reduce_to_s_matrix: 参考阻抗须为正实数")
    covered: list[int] = list(ext) + [int(k) for k in shorts] + [int(k) for k in opens]
    for i, j in connections:
        covered += [int(i), int(j)]
    if sorted(covered) != list(range(n)):
        raise ValueError(
            f"reduce_to_s_matrix: 端口约束须恰好覆盖 0..{n - 1} 各一次，得 {sorted(covered)}")
    lead = z.shape[:-2]
    a = np.zeros((*lead, n, n), dtype=complex)
    b = np.zeros((*lead, n, len(ext)), dtype=complex)
    for col, p in enumerate(ext):
        a[..., p, :] = z[..., p, :]
        a[..., p, p] += zr[col]
        b[..., p, col] = 2.0 * math.sqrt(zr[col])
    for k in opens:
        a[..., int(k), int(k)] = 1.0
    for k in shorts:
        a[..., int(k), :] = z[..., int(k), :]
    for i, j in connections:
        i, j = int(i), int(j)
        a[..., i, :] = z[..., i, :] - z[..., j, :]
        a[..., j, i] = 1.0
        a[..., j, j] = 1.0
    currents = np.linalg.solve(a, b)                       # (…, n, n_ext)
    volts = z @ currents
    s = np.empty((*lead, len(ext), len(ext)), dtype=complex)
    for row, k in enumerate(ext):
        s[..., row, :] = (volts[..., k, :] - zr[row] * currents[..., k, :]) / (
            2.0 * math.sqrt(zr[row]))
    return s


def z_to_s(z, z_ref) -> Any:
    """实参考阻抗归一 Z→S：S=(Zn−I)(Zn+I)⁻¹，Zn=D^{-1/2} Z D^{-1/2}。"""
    import numpy as np

    z = np.asarray(z, dtype=complex)
    n = z.shape[-1]
    zr = np.asarray(z_ref, dtype=float).reshape(n)
    if np.any(zr <= 0.0):
        raise ValueError("z_to_s: 参考阻抗须为正实数")
    sq = np.sqrt(zr)
    zn = z / (sq[:, None] * sq[None, :])
    eye = np.eye(n, dtype=complex)
    return (zn - eye) @ np.linalg.inv(zn + eye)


def marchand_two_section_sparams(freq_ghz, f0_ghz: float, z0e: float, z0o: float,
                                 z_unbal_ohm: float = 50.0,
                                 z_bal_se_ohm: float = 50.0) -> Any:
    """两节对称 Marchand 巴伦 3 端口 S（电路级、无耗 TEM）：(nf,3,3)。

    端口：0=不平衡输入（参考 z_unbal）、1=平衡 A、2=平衡 B（各单端参考 z_bal_se，
    差分负载 Z_L=2·z_bal_se）。θ=(π/2)·f/f0；拓扑见段首 ②。
    """
    import numpy as np

    f = np.asarray(freq_ghz, dtype=float)
    if np.any(f <= 0.0) or float(f0_ghz) <= 0.0:
        raise ValueError("marchand_two_section_sparams: 频率须 >0")
    theta = 0.5 * np.pi * f / float(f0_ghz)
    z4 = coupled_line_z_matrix(z0e, z0o, theta)          # (nf,4,4)
    nf = z4.shape[0]
    z8 = np.zeros((nf, 8, 8), dtype=complex)
    z8[:, :4, :4] = z4
    z8[:, 4:, 4:] = z4
    # 节 1 端口 0..3 = (a1,b1,c1,d1)，节 2 端口 4..7 = (a2,b2,c2,d2)
    return reduce_to_s_matrix(
        z8, external=(0, 3, 6),
        z_ref=(float(z_unbal_ohm), float(z_bal_se_ohm), float(z_bal_se_ohm)),
        shorts=(2, 7), opens=(5,), connections=((1, 4),))


def marchand_input_impedance_f0(z0e: float, z0o: float, z_bal_se_ohm: float) -> float:
    """f0 闭式（段首 ③）：Z_in = 2(Z0e·Z0o)²/((Z0e−Z0o)²·Z_t)。"""
    ze, zo, zt = float(z0e), float(z0o), float(z_bal_se_ohm)
    if not (ze > zo > 0.0 and zt > 0.0):
        raise ValueError("marchand_input_impedance_f0: 须 Z0e > Z0o > 0、Z_t > 0")
    return 2.0 * (ze * zo) ** 2 / ((ze - zo) ** 2 * zt)


def marchand_coupling_for_match(z_unbal_ohm: float, z_bal_se_ohm: float,
                                z_c_ohm: float) -> float:
    """f0 匹配所需电压耦合系数（段首 ③）：C = 1/√(1+2·Z_s·Z_t/Z_c²)。"""
    zs, zt, zc = float(z_unbal_ohm), float(z_bal_se_ohm), float(z_c_ohm)
    if not (zs > 0.0 and zt > 0.0 and zc > 0.0):
        raise ValueError("marchand_coupling_for_match: 阻抗须 >0")
    return 1.0 / math.sqrt(1.0 + 2.0 * zs * zt / (zc * zc))


def even_odd_from_coupling(c: float, z_c_ohm: float) -> tuple[float, float]:
    """C、Z_c → (Z0e, Z0o)：Z0e=Z_c√((1+C)/(1−C))、Z0o=Z_c√((1−C)/(1+C))。"""
    cc, zc = float(c), float(z_c_ohm)
    if not (0.0 < cc < 1.0 and zc > 0.0):
        raise ValueError(f"even_odd_from_coupling: 须 0<C<1、Z_c>0，得 ({cc}, {zc})")
    r = math.sqrt((1.0 + cc) / (1.0 - cc))
    return zc * r, zc / r


def coupled_microstrip_width_gap_from_even_odd(
        zee_ohm: float, zoo_ohm: float, freq_ghz: float,
        er: float, h_mm: float) -> tuple[float, float]:
    """(Z0e,Z0o) → (w_mm, s_mm)：KJ 闭式二维数值反解（core 层，嵌套 brentq）。

    内层：固定 w，s↑ ⇒ Z0e 单调下降（s→∞ 退化单线 Z0_single(w)），对 Z0e 解 s；
    外层：w↑ ⇒ 内层 s*↑ ⇒ Z0o(w,s*) 单调上升，对 Z0o 解 w。不可达显式报错。
    """
    from scipy.optimize import brentq

    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    ze_t, zo_t = float(zee_ohm), float(zoo_ohm)
    f0, e_r, h = float(freq_ghz), float(er), float(h_mm)
    if not ze_t > zo_t > 0.0:
        raise ValueError(f"须 Z0e > Z0o > 0，得 ({ze_t}, {zo_t})")
    stack = Stackup(name="marchand2", epsilon_r=e_r, thickness_mm=h)
    w_lo = float(inverse_width(ze_t * 0.999, f0, stack)[0])
    w_hi = w_lo + 8.0
    s_lo, s_hi = 0.02, 60.0

    def _ze_res(w_mm: float, s_mm: float) -> float:
        single = forward_z0(w_mm, f0, stack)
        return coupled_microstrip_even_odd_ohm(w_mm, s_mm, f0, e_r, h,
                                               single=single)[0] - ze_t

    def _s_star(w_mm: float) -> float | None:
        f_lo = _ze_res(w_mm, s_lo)
        if f_lo < 0.0:
            return None
        if f_lo == 0.0:
            return s_lo
        return float(brentq(lambda s: _ze_res(w_mm, s), s_lo, s_hi, xtol=1e-9))

    def _h(w_mm: float) -> float:
        s_mm = _s_star(w_mm)
        if s_mm is None:
            return float("nan")
        single = forward_z0(w_mm, f0, stack)
        return coupled_microstrip_even_odd_ohm(w_mm, s_mm, f0, e_r, h,
                                               single=single)[1] - zo_t

    lo_b, hi_b = w_lo, w_hi
    for _ in range(60):
        mid = 0.5 * (lo_b + hi_b)
        if _ze_res(mid, s_lo) > 0.0:
            lo_b = mid
        else:
            hi_b = mid
    w_zemax = 0.5 * (lo_b + hi_b)
    h_lo = _h(w_lo)
    h_hi = _h(w_zemax)
    if not (math.isfinite(h_lo) and math.isfinite(h_hi)) or h_lo <= 0.0 or h_hi >= 0.0:
        raise ValueError(
            f"(Z0e,Z0o)=({ze_t:.3f},{zo_t:.3f})Ω @h={h}mm 在 KJ 可达域外"
            f"（外层残差端点 {h_lo:.3f}/{h_hi:.3f}，须异号）")
    w_mm = float(brentq(_h, w_lo, w_zemax, xtol=1e-9))
    s_mm = _s_star(w_mm)
    assert s_mm is not None
    return w_mm, s_mm


@dataclass(frozen=True)
class MarchandTwoSectionDesign:
    """两节对称 Marchand 电路级综合结果（mm/Ω；平衡侧单端参考 z_bal_se=Z_L/2）。

    realizable=False 时几何为"最近可达"钳位点（KJ 反解越域时 s 钳 0.02mm），
    model_metrics 按**实际可达 (Z0e,Z0o)** 计算——门 FAIL 如实进结果不抛异常（#122）。
    """

    f0_ghz: float
    z_unbal_ohm: float
    z_bal_diff_ohm: float
    z_bal_se_ohm: float
    match_invariant_ohm: float  # L_req = √(Z_s·Z_t/2) = Z0e·Z0o/(Z0e−Z0o)
    z_c_ohm: float
    coupling: float
    coupling_db: float
    z0e_ohm: float              # 闭式理想值
    z0o_ohm: float
    z0e_realized_ohm: float     # KJ 回代（几何实际可达）
    z0o_realized_ohm: float
    er: float
    h_mm: float
    s_min_mm: float
    realizable: bool
    w_mm: float                 # 耦合段单线宽（KJ 反解）
    s_mm: float                 # 耦合缝
    l_sect_mm: float            # 每节长 λ/4 @ (εeff_e+εeff_o)/2
    ere_e: float
    ere_o: float
    w_feed_mm: float            # 不平衡 Z_s 馈线宽（HJ）
    w_bal_line_mm: float        # 平衡臂单端 Z_t 线宽（HJ）
    slot_balanced: dict | None  # 平衡侧走槽线的可选口径（Z_L 槽宽 + 过渡段），域外 None
    model_metrics: dict         # 电路级自检指标 + 门（按实际可达 Z0e/Z0o）
    notes: tuple[str, ...]

    def to_dict(self) -> dict:
        out = {f.name: getattr(self, f.name) for f in fields(MarchandTwoSectionDesign)}
        out["notes"] = list(self.notes)
        return out

    def nominal_params(self) -> dict[str, float]:
        """供真机渲染冒烟的名义几何（4 位舍入，闭式精算，#1c）。"""
        return {"w_mm": round(self.w_mm, 4), "s_mm": round(self.s_mm, 4),
                "l_sect_mm": round(self.l_sect_mm, 4),
                "w_feed_mm": round(self.w_feed_mm, 4),
                "w_bal_line_mm": round(self.w_bal_line_mm, 4),
                "r_bal_se_ohm": round(self.z_bal_se_ohm, 4)}


def marchand_two_section_metrics(f_hz, s3, band_ghz=BAND_GHZ_DEFAULT) -> dict:
    """3 端口 S (nf,3,3) → 预声明门指标（f0=带中心；相位误差=|Δφ−180°|）。"""
    import numpy as np

    f_hz = np.asarray(f_hz, dtype=float)
    s = np.asarray(s3, dtype=complex)
    m = _band_mask(f_hz, band_ghz)
    i0 = int(np.argmin(np.abs(f_hz - 0.5 * (band_ghz[0] + band_ghz[1]) * 1e9)))
    s11_db, s21_db, s31_db = _db(s[:, 0, 0]), _db(s[:, 1, 0]), _db(s[:, 2, 0])
    s23_db = _db(s[:, 2, 1])
    imb = s21_db - s31_db
    ph = np.angle(s[:, 2, 0] * np.conj(s[:, 1, 0]), deg=True)
    ph_err = np.abs(np.abs(ph) - 180.0)
    out = {
        "band_ghz": list(band_ghz),
        "s11_db_f0": float(s11_db[i0]), "s21_db_f0": float(s21_db[i0]),
        "s31_db_f0": float(s31_db[i0]), "s23_db_f0": float(s23_db[i0]),
        "phase_diff_deg_f0": float(ph[i0]),
        "band_max_s11_db": float(np.max(s11_db[m])),
        "band_min_s21_db": float(np.min(s21_db[m])),
        "band_min_s31_db": float(np.min(s31_db[m])),
        "band_max_abs_imbalance_db": float(np.max(np.abs(imb[m]))),
        "band_max_phase_error_deg": float(np.max(ph_err[m])),
        "band_max_s23_db": float(np.max(s23_db[m])),
    }
    g = MARCHAND2_GATES
    out["gates"] = {
        "band_max_s11_le_minus10db": bool(out["band_max_s11_db"] <= g["band_max_s11_db_le"]),
        "band_min_s21_ge_minus3p5db": bool(out["band_min_s21_db"] >= g["band_min_s21_db_ge"]),
        "band_min_s31_ge_minus3p5db": bool(out["band_min_s31_db"] >= g["band_min_s31_db_ge"]),
        "amp_imbalance_le_1db": bool(
            out["band_max_abs_imbalance_db"] <= g["band_max_abs_imbalance_db_le"]),
        "phase_error_le_10deg": bool(
            out["band_max_phase_error_deg"] <= g["band_max_phase_error_deg_le"]),
    }
    out["all_gates_pass"] = all(out["gates"].values())
    return out


def _slot_balanced_option(f0: float, h_mm: float, er: float, tan_d: float,
                          z_unbal: float, z_l: float) -> tuple[dict | None, str]:
    """平衡侧走槽线的可选口径：Z_L 槽宽（core/slotline 反解）+ Roberts 过渡段参数。"""
    from scipy.optimize import brentq

    from rfauto.core.slotline import W_OVER_LAMBDA0_NARROW_RANGE, slotline_closed_form

    try:
        lam0_mm = C0 / (f0 * 1e9) * 1e3
        w_lo = W_OVER_LAMBDA0_NARROW_RANGE[0] * lam0_mm * (1.0 + 1e-6)
        w_hi = W_OVER_LAMBDA0_NARROW_RANGE[1] * lam0_mm * (1.0 - 1e-6)

        def _obj(w: float) -> float:
            return slotline_closed_form(w, h_mm, er, f0).z0_ohm - z_l

        lo_v, hi_v = _obj(w_lo), _obj(w_hi)
        if lo_v > 0.0 or hi_v < 0.0:
            raise ValueError(
                f"Z_L={z_l}Ω 越窄槽段可达范围 [{lo_v + z_l:.1f}, {hi_v + z_l:.1f}]Ω")
        w_slot = float(brentq(_obj, w_lo, w_hi, xtol=1e-9))
        td = transition_design(f0, h_mm, er, w_slot, tan_d, z_unbal)
    except ValueError as exc:
        return None, f"槽线平衡侧口径不可用（{exc}）"
    opt = {"z_slot_target_ohm": z_l, "w_slot_mm": round(w_slot, 4),
           "transition": td.to_dict()}
    return opt, (f"槽线平衡侧：Z_L={z_l}Ω 槽宽 {opt['w_slot_mm']}mm、过渡支节 "
                 f"{td.to_dict()['l_stub_mm']}mm/短路臂 {td.to_dict()['l_short_mm']}mm")


# ─── openEMS 逐引擎修正（2026-09-18 marchand_line_calibration 4 点标定）──

#: openEMS 单线 Z0 引擎偏差标定表：(w_mm, Z0_engine/Z0_HJ − 1)，负=引擎偏低阻。
#: 数据源 marchand_line_calibration 标定表 calibration_table.json 的 dev_pct_primary
#: （Z0 主判据=四路由中位，spread ≤0.6%；p1_wbal/p2_w80/p3_wmain/p4_wfeed，2026-09-18）
MARCHAND_OPENEMS_Z0_DEV_CAL: tuple[tuple[float, float], ...] = (
    (0.2981, -0.11559883283386052),
    (1.4041606419093198, -0.04096610927274657),
    (1.7616, -0.03198932608614302),
    (3.3439000000000005, -0.0109101005876171),
)
#: 标定有效域（mm）；域外钳制到端点 dev 值，不外推
MARCHAND_OPENEMS_W_DOMAIN_MM: tuple[float, float] = (
    MARCHAND_OPENEMS_Z0_DEV_CAL[0][0], MARCHAND_OPENEMS_Z0_DEV_CAL[-1][0])
#: β 引擎偏差常数（S21 相位拟合 +1.46~+3.24% 平缓，标定建议 +2%±1%）→ 节长除以 (1+此值)
MARCHAND_OPENEMS_BETA_DEV: float = 0.02


def engine_z0_correction(w_mm: float) -> float:
    """openEMS（本仓 v0.37 进程内 FDTD）单线 Z0 引擎偏差 dev(w)=Z0_engine/Z0_HJ − 1。

    模型：4 点标定 **PCHIP 内插（对数宽度轴 log10(w)**，标定建议"对数宽度轴更稳"），
    节点=MARCHAND_OPENEMS_Z0_DEV_CAL；dev 单调（窄线更负：−11.6%@0.2981mm →
    −1.1%@3.3439mm），PCHIP 保单调。中段 90–120Ω（marchand z0e=95.2Ω 区）无实测
    点，内插不确定度估计 ±2pp（标定建议补点后再收紧）。

    适用域（如实声明，仅此口径有效）：
    - w ∈ [0.2981, 3.3439] mm、基板 RO4350B h=1.524mm/εr=3.66/tanδ=0.0037、
      缺省网格档（BASE=1.0447/NEAR=0.2612mm）、判读带 2.25–2.75GHz 带中位；
    - **标定基准=直微带单线**（双 MSLPort 直线）：耦合线对 Z0e/Z0o 的引擎偏差未
      标定（归 C4 面），本曲线用于耦合段属**外推**（同因子施加于偶/奇模）；
      槽线族偏差（CPS εeff +11.7%，#302/#303）结构特有，不可移植到微带口径；
    - 域外（w<0.2981 或 w>3.3439）**钳制到端点值**不外推（窄线端实际偏差预计
      更负，钳制偏保守）；调用方比对 MARCHAND_OPENEMS_W_DOMAIN_MM 自行注记。
    """
    w = float(w_mm)
    if not w > 0.0:
        raise ValueError(f"engine_z0_correction: w_mm 须 >0，得 {w_mm!r}")
    from scipy.interpolate import PchipInterpolator

    lo, hi = MARCHAND_OPENEMS_W_DOMAIN_MM
    xs = [math.log10(p[0]) for p in MARCHAND_OPENEMS_Z0_DEV_CAL]
    ys = [p[1] for p in MARCHAND_OPENEMS_Z0_DEV_CAL]
    x = min(max(math.log10(w), math.log10(lo)), math.log10(hi))
    return float(PchipInterpolator(xs, ys)(x))


def _engine_corrected_line_width(z_target_ohm: float, freq_ghz: float,
                                 stack: Stackup) -> tuple[float, bool]:
    """单线 Z0 目标经 dev(w) 预畸变的定点反解：engine(w)≡Z_HJ(w)·(1+dev(w))=Z_target。

    定点收缩因子 ≪1（dev 随 w 平缓），60 次上限充裕；返回 (w_mm, 域外钳制与否)。
    """
    z_t = float(z_target_ohm)
    w = float(inverse_width(z_t, float(freq_ghz), stack)[0])
    lo, hi = MARCHAND_OPENEMS_W_DOMAIN_MM
    for _ in range(60):
        w_next = float(inverse_width(z_t / (1.0 + engine_z0_correction(w)),
                                     float(freq_ghz), stack)[0])
        done = abs(w_next - w) <= 1e-7
        w = w_next
        if done:
            break
    return w, not (lo <= w <= hi)


def _engine_corrected_width_gap(ze_ohm: float, zoo_ohm: float, freq_ghz: float,
                                er: float,
                                h_mm: float) -> tuple[float, float, float, bool]:
    """耦合段 (Z0e,Z0o) 目标经 dev(w) 预畸变反解 (w,s)：KJ 目标=(Z0e,Z0o)/(1+dev(w))。

    dev 依赖所解 w，故对 KJ 目标做定点迭代（dev 随 w 平缓、收缩快）；返回
    (w_mm, s_mm, dev(w_final), 域外钳制与否)。中间迭代越 KJ 可达域的 ValueError
    由调用方按"该 Z_c 不可达"处理（与 reference 口径同路）。
    """
    ze_t, zo_t = float(ze_ohm), float(zoo_ohm)
    w = s = 0.0
    for _ in range(60):
        w, s = coupled_microstrip_width_gap_from_even_odd(ze_t, zo_t, float(freq_ghz),
                                                          er, h_mm)
        dev = engine_z0_correction(w)
        ze_next = float(ze_ohm) / (1.0 + dev)
        zo_next = float(zoo_ohm) / (1.0 + dev)
        done = abs(ze_next - ze_t) <= 1e-7 and abs(zo_next - zo_t) <= 1e-7
        ze_t, zo_t = ze_next, zo_next
        if done:
            break
    lo, hi = MARCHAND_OPENEMS_W_DOMAIN_MM
    return w, s, engine_z0_correction(w), not (lo <= w <= hi)


def synthesize_marchand_two_section(
        f0_ghz: float = 2.5, z_unbal_ohm: float = 50.0,
        z_bal_diff_ohm: float = 280.0, *, er: float = 3.66, h_mm: float = 1.524,
        tan_d: float = 0.0037, s_min_mm: float = 0.1, w_max_mm: float = 6.0,
        z_c_ohm: float | None = None,
        band_ghz: tuple[float, float] | None = None,
        engine: str = "reference") -> MarchandTwoSectionDesign:
    """两节对称 Marchand 电路级综合（确定性内核；数值只在此产出；门 FAIL 如实不抛）。

    匹配不变量 L_req=√(Z_s·Z_t/2) 只由 Z_s·Z_L 决定；Z_c 是沿等 L 族的自由参数
    （Z_c↑ 线更窄、所需缝更小）。z_c_ohm=None 时**自动扫描** Z_c（2.0→0.3×√(Z_s·Z_t)
    对数网格）取第一个满足 KJ 严格可达且 s≥s_min、w≤w_max 的点（=可制造缝下最窄
    线）；全部不可达 ⇒ realizable=False，几何取 √(Z_s·Z_t) 处钳位最近点如实报告。

    engine（逐引擎修正，2026-09-18 marchand_line_calibration 4 点标定）：
    "reference"（缺省）=HJ 综合现状（输出逐字节不变，SHA256 对拍钉）；"openems"=
    本仓 openEMS 逐档修正——Z0 目标经 engine_z0_correction 预畸变反解设计宽
    （耦合段 (Z0e,Z0o) 与 w_feed/w_bal 同曲线定点），节长按 β_engine=β_HJ·(1+0.02)
    缩短，model_metrics 按引擎期望阻抗 KJ 回代×(1+dev)（≈设计目标）计算。
    **标定基准=直微带单线，耦合段 Z0e/Z0o 适用性是外推**；不可达钳位回退不做
    预畸变（如实报告最近可达点）。修正模型与适用域详见 engine_z0_correction。

    **结构性事实（本项实证，非模型缺陷）**：边耦合微带在 RO4350B（h=0.508/1.524）
    KJ 域内 L 下限 ≈45/39Ω（缝 0.02mm）、缝 ≥0.1mm 时 ≈67/52Ω——常规 50Ω→100Ω
    差分 Marchand（L_req=35.36、C=−4.77dB）**不可用边耦合微带实现**（需 Lange/
    宽边耦合/多层），故缺省名义点取阻抗变换型 50Ω→280Ω 差分（L_req=59.16，
    折合振子量级负载）在 h=1.524、缝 0.1mm 下可达。
    """
    import numpy as np

    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm
    from rfauto.core.synthesis import Stackup, inverse_width

    f0 = float(f0_ghz)
    zs, zl = float(z_unbal_ohm), float(z_bal_diff_ohm)
    if not (f0 > 0.0 and zs > 0.0 and zl > 0.0 and float(s_min_mm) > 0.0):
        raise ValueError("synthesize_marchand_two_section: f0/Z_s/Z_L/s_min 须 >0")
    if engine not in ("reference", "openems"):
        raise ValueError(f"synthesize_marchand_two_section: engine 须为 "
                         f"'reference'|'openems'，得 {engine!r}")
    engine_openems = engine == "openems"
    zt = zl / 2.0
    l_req = math.sqrt(zs * zt / 2.0)
    zc_ref = math.sqrt(zs * zt)

    def _try(zc: float) -> tuple[float, float, float, float] | None:
        c = marchand_coupling_for_match(zs, zt, zc)
        ze, zo = even_odd_from_coupling(c, zc)
        try:
            if engine_openems:
                w, s, _, _ = _engine_corrected_width_gap(ze, zo, f0, er, h_mm)
            else:
                w, s = coupled_microstrip_width_gap_from_even_odd(ze, zo, f0, er, h_mm)
        except ValueError:
            return None
        return ze, zo, w, s

    chosen: tuple[float, float, float, float, float] | None = None
    if z_c_ohm is not None:
        zc = float(z_c_ohm)
        got = _try(zc)
        if got is not None and got[3] >= float(s_min_mm) and got[2] <= float(w_max_mm):
            chosen = (zc, *got)
    else:
        for zc in np.geomspace(2.0 * zc_ref, 0.3 * zc_ref, 61):
            got = _try(float(zc))
            if got is None:
                continue
            if got[3] >= float(s_min_mm) and got[2] <= float(w_max_mm):
                chosen = (float(zc), *got)
                break
    realizable = chosen is not None
    if not realizable:
        # 钳位最近可达点（adapters 反解同款：s 钳 s_lo，w 取 Z0e 可达上界）如实报告
        zc = float(z_c_ohm) if z_c_ohm is not None else zc_ref
        c = marchand_coupling_for_match(zs, zt, zc)
        ze, zo = even_odd_from_coupling(c, zc)
        w, s = _clamped_width_gap(ze, zo, f0, er, h_mm)
        chosen = (zc, ze, zo, w, s)
    zc, ze, zo, w_mm, s_mm = chosen
    c = marchand_coupling_for_match(zs, zt, zc)
    z_in = marchand_input_impedance_f0(ze, zo, zt)
    if abs(z_in - zs) > 1e-9 * max(1.0, zs):
        raise ValueError(f"闭式回代失配 Z_in={z_in} ≠ Z_s={zs}")   # 推导恒等式自检
    ze_kj, zo_kj, ere_e, ere_o = coupled_microstrip_even_odd_ohm(w_mm, s_mm, f0, er, h_mm)
    ere_avg = 0.5 * (ere_e + ere_o)
    l_sect = C0 / (f0 * 1e9) / math.sqrt(ere_avg) * 1e3 / 4.0
    if engine_openems:
        l_sect /= 1.0 + MARCHAND_OPENEMS_BETA_DEV   # β_engine=β_HJ·(1+0.02) ⇒ 节长缩短
    stack = Stackup(name="marchand2", epsilon_r=float(er), thickness_mm=float(h_mm),
                    loss_tangent=float(tan_d))
    w_feed = float(inverse_width(zs, f0, stack)[0])
    w_bal = float(inverse_width(zt, f0, stack)[0])
    engine_clamps: list[str] = []
    if engine_openems:
        w_feed_hj, w_bal_hj = w_feed, w_bal
        w_feed, feed_clamped = _engine_corrected_line_width(zs, f0, stack)
        w_bal, bal_clamped = _engine_corrected_line_width(zt, f0, stack)
        if feed_clamped:
            engine_clamps.append(f"w_feed({w_feed_hj:.4f}→{w_feed:.4f}mm)")
        if bal_clamped:
            engine_clamps.append(f"w_bal({w_bal_hj:.4f}→{w_bal:.4f}mm)")

    band = tuple(band_ghz) if band_ghz is not None else (0.9 * f0, 1.1 * f0)
    f_ghz = np.linspace(0.7 * f0, 1.3 * f0, 241)
    dev_final: float | None = None
    if engine_openems:
        dev_final = engine_z0_correction(w_mm)
        ze_model, zo_model = ze_kj * (1.0 + dev_final), zo_kj * (1.0 + dev_final)
    else:
        ze_model, zo_model = ze_kj, zo_kj
    s3 = marchand_two_section_sparams(f_ghz, f0, ze_model, zo_model, zs, zt)
    metrics = marchand_two_section_metrics(f_ghz * 1e9, s3, band)
    slot_balanced, slot_note = _slot_balanced_option(f0, float(h_mm), float(er),
                                                     float(tan_d), zs, zl)
    l_real = ze_kj * zo_kj / (ze_kj - zo_kj)
    model_basis = ("按引擎期望 Z0e/Z0o（KJ 回代×(1+dev)）" if engine_openems
                   else "按回代 Z0e/Z0o")
    notes = (
        f"f0 匹配闭式：L_req=√(Z_s·Z_t/2)={l_req:.3f}Ω；Z_c={zc:.3f}Ω → "
        f"C=1/√(1+2·Z_s·Z_t/Z_c²)={c:.5f}（{20 * math.log10(c):.2f}dB），"
        f"(Z0e,Z0o)=({ze:.3f},{zo:.3f})Ω，Z_t=Z_L/2={zt:.3f}Ω",
        (f"KJ 反解 (w,s)=({w_mm:.4f},{s_mm:.4f})mm@h={h_mm}/εr={er}"
         f"（s_min={s_min_mm}，{'严格可达' if realizable else '不可达→钳位最近点'}），"
         f"回代 (Z0e,Z0o)=({ze_kj:.3f},{zo_kj:.3f})Ω、L_realized={l_real:.3f}Ω，"
         f"εeff_e/o={ere_e:.4f}/{ere_o:.4f} → 节长 λ/4={l_sect:.4f}mm"),
        (f"电路级自检（{model_basis}，{band[0]:.3f}–{band[1]:.3f}GHz）："
         f"max|S11|={metrics['band_max_s11_db']:.2f}dB、min|S21|/|S31|="
         f"{metrics['band_min_s21_db']:.3f}/{metrics['band_min_s31_db']:.3f}dB、不平衡 "
         f"{metrics['band_max_abs_imbalance_db']:.3f}dB、相位误差 "
         f"{metrics['band_max_phase_error_deg']:.2f}°、S23@f0={metrics['s23_db_f0']:.2f}dB"
         f" → 门 {'PASS' if metrics['all_gates_pass'] else 'FAIL'}"),
        "局限：无耗 TEM 理想耦合线（无偶/奇模相速差、结区寄生、导体/介质损耗）；"
        "真机 IL 预期 −3.01dB 再减 0.2–0.5dB，门 −3.5dB 留 0.5dB 余量",
        slot_note,
    )
    if engine_openems:
        assert dev_final is not None
        clamp_txt = (f"域外钳制 {len(engine_clamps)} 处（{'、'.join(engine_clamps)}）；"
                     if engine_clamps else "")
        notes = (*notes, (
            f"openEMS 逐引擎修正（engine=openems；标定 marchand_line_calibration "
            f"4 点直微带线、PCHIP@log10(w)、适用域 w∈[{MARCHAND_OPENEMS_W_DOMAIN_MM[0]:.4f},"
            f"{MARCHAND_OPENEMS_W_DOMAIN_MM[1]:.4f}]mm/基板 h=1.524/εr=3.66 专用，域外钳制）："
            f"Z0 目标预畸变 Z_HJ=Z_target/(1+dev(w)) 反解设计宽——耦合段 (Z0e,Z0o)=({ze:.3f},"
            f"{zo:.3f})Ω → KJ 设计目标 ({ze / (1.0 + dev_final):.3f},{zo / (1.0 + dev_final):.3f})Ω"
            f"（w={w_mm:.4f}mm 处 dev={dev_final:.5f}）；w_feed {w_feed_hj:.4f}→{w_feed:.4f}mm、"
            f"w_bal {w_bal_hj:.4f}→{w_bal:.4f}mm 同曲线；节长按 β_engine=β_HJ·(1+"
            f"{MARCHAND_OPENEMS_BETA_DEV:.2f}) 缩短；电路级自检按引擎期望阻抗 KJ×(1+dev)≈设计目标；"
            f"{clamp_txt}标定基准=直微带单线，耦合段 Z0e/Z0o 适用性为外推（耦合对偏差归 C4 面）"
            f"{'' if realizable else '；不可达钳位回退未做预畸变（如实报告最近可达点）'}"))
    return MarchandTwoSectionDesign(
        f0_ghz=f0, z_unbal_ohm=zs, z_bal_diff_ohm=zl, z_bal_se_ohm=zt,
        match_invariant_ohm=l_req, z_c_ohm=zc, coupling=c,
        coupling_db=20.0 * math.log10(c), z0e_ohm=ze, z0o_ohm=zo,
        z0e_realized_ohm=ze_kj, z0o_realized_ohm=zo_kj, er=float(er), h_mm=float(h_mm),
        s_min_mm=float(s_min_mm), realizable=realizable, w_mm=w_mm, s_mm=s_mm,
        l_sect_mm=l_sect, ere_e=ere_e, ere_o=ere_o, w_feed_mm=w_feed,
        w_bal_line_mm=w_bal, slot_balanced=slot_balanced, model_metrics=metrics,
        notes=notes)


def _clamped_width_gap(zee_ohm: float, zoo_ohm: float, freq_ghz: float,
                       er: float, h_mm: float) -> tuple[float, float]:
    """KJ 域外的最近可达点：s 钳 0.02mm、w 取 Z0e(w, 0.02)=Z0e_t 的上界（如实钳位）。"""
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    ze_t = float(zee_ohm)
    stack = Stackup(name="marchand2", epsilon_r=float(er), thickness_mm=float(h_mm))
    w_lo = float(inverse_width(ze_t * 0.999, float(freq_ghz), stack)[0])
    lo_b, hi_b = w_lo, w_lo + 8.0
    s_lo = 0.02
    for _ in range(60):
        mid = 0.5 * (lo_b + hi_b)
        single = forward_z0(mid, float(freq_ghz), stack)
        res = coupled_microstrip_even_odd_ohm(mid, s_lo, freq_ghz, er, h_mm,
                                              single=single)[0] - ze_t
        if res > 0.0:
            lo_b = mid
        else:
            hi_b = mid
    return 0.5 * (lo_b + hi_b), s_lo


#: 真机渲染冒烟名义设计点（闭式精算，#1c）：50Ω→280Ω 差分、RO4350B 60mil、缝 ≥0.1mm
MARCHAND2_NOMINAL_INPUTS: dict[str, float] = {
    "f0_ghz": 2.5, "z_unbal_ohm": 50.0, "z_bal_diff_ohm": 280.0,
    "er": 3.66, "h_mm": 1.524, "tan_d": 0.0037, "s_min_mm": 0.1,
}


def marchand_two_section_nominal() -> MarchandTwoSectionDesign:
    """名义设计点综合（供真机渲染冒烟；单测钉 realizable/门/KJ 回代）。"""
    kw = dict(MARCHAND2_NOMINAL_INPUTS)
    return synthesize_marchand_two_section(
        kw.pop("f0_ghz"), kw.pop("z_unbal_ohm"), kw.pop("z_bal_diff_ohm"), **kw)
