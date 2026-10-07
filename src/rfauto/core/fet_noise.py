"""F-L 第 1 步：Pospieszalski 场效应管噪声模型闭式内核 + 等噪声圆 + LNA 匹配面。

法源与引源纪律（#118：闭式系数回原文/可靠二手，docstring 钉出处）：

- 模型定义（拓扑+两等效温度+噪声源不相关）：M. W. Pospieszalski,
  "Modeling of noise parameters of MESFETs and MODFETs and their frequency
  and temperature dependence," IEEE Trans. Microwave Theory Tech., vol. 37,
  no. 9, pp. 1340-1350, Sept. 1989（原文 IEEE 付费墙不可达——二手可达源
  钉拓扑）：
  * O. Pronić-Renić et al., "A New Method for Accurate Noise Modeling of
    Microwave FET Transistors," ICEST 2004, Bitola（开放 PDF，
    rcvt.tu-sofia.bg/ICEST2004_2_33.pdf）——其 §II 逐字转引 Pospieszalski
    本征闭式（原文 eq.(1)-(6)，引 [3]=Pospieszalski 1989）：本征电路 =
    Cgs + Rgs + Rds + VCCS gm·V（**V 是 Cgs 两端电压**），Rgs 等效温度 Tg、
    Rds 等效温度 Td，两噪声源**完全不相关**；其 eq.(2) 的 Tmin 闭式与本
    模块一阶推导逐位恒等（tests/unit/test_fet_noise.py 以独立代数排布
    回收钉 rel 1e-12）。
  * J. Stenarson et al., "FET Noise Model Extraction Methods," GAAS 2003
    （开放 PDF，amsacta.unibo.it/215/1/GAAS1_2.pdf）——Fig.1a 同拓扑
    （Cgs 串 Ri@Tg、Rds@Td、i=v·gm），确认"one and two parameter
    Pospieszalski model"语义（Td 单参为缺省、Tg 可选第二参）。
- 本征闭式（Fmin/Rn/Yopt）为上述拓扑的一阶解析重推（非逐字转录——原文
  付费墙），正确性三重钉（先于引源逐位，#122）：
  ① 极限自检：Tg=Td=T0 且 Ri=0（无损寄生）→ Fmin=1.0（0 dB）**逐位**
    （无源无耗一致性）；Td→0⁺ → NFmin→0 dB（栅噪声被大 Gs 淹没的下确界）；
    Td↑ → NFmin 单调升；ω↑ → NFmin 单调升（Pospieszalski 低频 NFmin∝ω 特性）。
  ② 独立裁判：测试文件内置**无惯例暴力电路裁判**（节点分析逐源叠加，
    F = 1 + ΣT_i·g_i·|H_i|²/(T0·Gs·|Hs|²)，H=各噪声源到漏极开路戴维南
    电压的传递）——与四参闭式 F(Ys) 在随机 Ys 网格上逐位一致（实测
    ~5e-16）。
  ③ 引源回收：Pronić ICEST eq.(2) Tmin 闭式（独立代数排布）与本模块
    Fmin 恒等（rel 1e-12 级）。
- 诚实边界（预声明）：二手转引的 Ropt/Rn 逐字式（Pronić eq.(4)/(5)）在
  PDF 转录层存在分母规整歧义（与精确式差 (1+N)/(1+N+M) 型因子），本模块
  按 ②裁判+①极限取**精确式**，不转录存疑排布；高频段（Cgd/Cds/τ 非零、
  封装寄生）不在**本征闭式域**内——P8 批（2026-10-05）起由广义节点分析
  嵌入路径精确处理（path="embedded"），全带面
  pospieszalski_noise_sweep 出 NF(f)/Rn(f)/Γopt(f)；嵌入裁判=节点分析
  暴力电路同源路径，测试另置独立编码裁判+噪声相关矩阵级联（Hillbrand-
  Russer 链式法则，core/noise_correlation 法理同源）交叉钉。

等噪声圆与 Γ↔Z 换算**复用 core/active_chain.py**（Pozar ch.12 口径，
noise_figure_db/noise_figure_circle/z_to_gamma/gamma_to_z）——本模块是
"从小信号等效电路+等效温度**生成**四噪声参数"的上游面，不重复实现
四参→圆的下游公式（任务书 语境钉死②）。

单位口径：全部 SI（F/Ω/S/Hz/K），T0=290 K 缺省（IEEE 噪声口径），
z0=50 Ω 缺省。数值 0.0 合法（td_k=0 拒收：Γopt 退化，见 validate）；
判缺失一律 ``is not None``（#364④）；bool 显式拒收（df7+⑯）。
纯函数零 IO；LLM 不参与任何数值。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from rfauto.core.active_chain import (
    DEFAULT_Z0,
    Circle,
    noise_figure_circle,
    noise_figure_db,
    output_gamma,
    transducer_gain_db,
    z_to_gamma,
)

#: Boltzmann 常数（J/K）：SI 精确定义值（CODATA 2018）
K_B_J_PER_K = 1.380649e-23

#: IEEE 噪声口径参考温度（K）
T0_DEFAULT_K = 290.0

_EPS = 1e-15


def _finite(value: float, name: str) -> float:
    """入参收敛为有限 float；bool 显式拒收（df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _nonneg(value: float, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0")
    return out


# ─── 小信号等效电路（Pospieszalski 本征模型 + 可选栅/源寄生）─────────────────


@dataclass
class FetSmallSignal:
    """场效应管小信号等效电路（源极接地，Pospieszalski 本征模型 + 寄生）。

    cgs_f: 栅源电容 Cgs（F，>0）；
    ri_ohm: 栅源（充电）电阻 Rgs/Ri（Ω，>=0；栅噪声温度 Tg 挂在此电阻上，
        =0 时栅噪声源消失——无损栅支路极限）；
    gm_s: 跨导 gm（S，>0；受控源 i = gm·V_Cgs，V_Cgs 为 **Cgs 两端电压**，
        见模块头拓扑引源）；
    gds_s: 输出电导 gds=1/Rds（S，>0；漏噪声温度 Td 挂在此电导上）；
    rg_ohm: 栅串联寄生电阻 Rg（Ω，>=0，缺省 0；>0 时走数值嵌入路径）；
    rs_ohm: 源（共源引线）串联寄生电阻 Rs（Ω，>=0，缺省 0；>0 时走数值
        嵌入路径——共引线反馈不可用链式矩阵级联，走节点分析精确嵌入）；
    cgd_f: 栅漏电容 Cgd（F，>=0，缺省 0；fT 闭式与噪声嵌入路径共用——
        P8 批起进噪声拓扑（本征栅漏反馈，跨 g-d），不再只是 fT 摆设）。

    **P8 扩展寄生（2026-10-05，全缺省 0=既有口径逐位不变）**：
    cds_f: 漏源电容 Cds（F，>=0；本征漏源支路，跨 d-s）；
    tau_s: 跨导传输延迟 τ（s，>=0；受控源 i = gm·e^{−jωτ}·V_Cgs——
        gm 复数化的无损相位项，不引入新噪声源）；
    lg_h / ld_h / ls_h: 栅/漏/源键合线电感（H，>=0；无损——不挂噪声温度，
        只参与频率形变 F(f)；栅支路 Rg 与 Lg 串联、源支路 Rs 与 Ls 串联）；
    cpg_f / cpd_f: 封装焊盘并联电容（F，>=0；无损，分别在外栅/外漏节点对地）。

    任一寄生非零 → 噪声参数走广义节点分析精确嵌入路径（path="embedded"）；
    全零 → 本征闭式（path="intrinsic"）。**全带面**见
    pospieszalski_noise_sweep（NF(f)/Rn(f)/Γopt(f)，P8）。
    """

    cgs_f: float
    ri_ohm: float
    gm_s: float
    gds_s: float
    rg_ohm: float = 0.0
    rs_ohm: float = 0.0
    cgd_f: float = 0.0
    cds_f: float = 0.0
    tau_s: float = 0.0
    lg_h: float = 0.0
    ld_h: float = 0.0
    ls_h: float = 0.0
    cpg_f: float = 0.0
    cpd_f: float = 0.0

    def validate(self) -> FetSmallSignal:
        """数值守卫：非法入参显式 ValueError（#122 判据·数值守卫）。"""
        _positive(self.cgs_f, "cgs_f")
        _nonneg(self.ri_ohm, "ri_ohm")
        _positive(self.gm_s, "gm_s")
        _positive(self.gds_s, "gds_s")
        _nonneg(self.rg_ohm, "rg_ohm")
        _nonneg(self.rs_ohm, "rs_ohm")
        _nonneg(self.cgd_f, "cgd_f")
        _nonneg(self.cds_f, "cds_f")
        _nonneg(self.tau_s, "tau_s")
        _nonneg(self.lg_h, "lg_h")
        _nonneg(self.ld_h, "ld_h")
        _nonneg(self.ls_h, "ls_h")
        _nonneg(self.cpg_f, "cpg_f")
        _nonneg(self.cpd_f, "cpd_f")
        return self

    def has_parasitics(self) -> bool:
        """任一寄生/封装元件非零 → True（嵌入路径分派用；全零=闭式域）。"""
        return any(
            v > 0.0
            for v in (
                self.rg_ohm, self.rs_ohm, self.cgd_f, self.cds_f, self.tau_s,
                self.lg_h, self.ld_h, self.ls_h, self.cpg_f, self.cpd_f,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cgs_f": self.cgs_f,
            "ri_ohm": self.ri_ohm,
            "gm_s": self.gm_s,
            "gds_s": self.gds_s,
            "rg_ohm": self.rg_ohm,
            "rs_ohm": self.rs_ohm,
            "cgd_f": self.cgd_f,
            "cds_f": self.cds_f,
            "tau_s": self.tau_s,
            "lg_h": self.lg_h,
            "ld_h": self.ld_h,
            "ls_h": self.ls_h,
            "cpg_f": self.cpg_f,
            "cpd_f": self.cpd_f,
        }


# ─── 本征闭式（裁判逐位钉死的精确式）────────────────────────────────────────
#
# 记号（见测试文件独立重推路径 A/B）：
#   Ygs = jωCgs/(1 + jωCgs·Ri)          本征栅支路（Cgs 串 Ri）导纳
#   ggs = Re{Ygs} = ω²Cgs²Ri/(1+ω²Cgs²Ri²)
#   b   = Im{Ygs} = ωCgs/(1+ω²Cgs²Ri²)
#   N   = ω²Cgs²Ri²,  |β|² = 1/(1+N)    β = V_Cgs/V_gate 内节点分压
#   W   = Td·gds/(|β|²·gm²)
# 四参精确式：
#   Rn   = W/T0                                  （|Ys|²/Gs 系数，Ω）
#   Yopt = Gopt + j·Bopt
#   Gopt = sqrt(ggs² + Tg·|β|²·gm²·ggs/(Td·gds))
#   Bopt = −b
#   Fmin = 1 + 2·Rn·(Gopt + ggs)   （Td>0；Td→0⁺ 时 Rn→0/Gopt→∞，Fmin→1）
#   Zopt = 1/Yopt,  Γopt = (Zopt−Z0)/(Zopt+Z0)


@dataclass
class FetNoiseParams:
    """Pospieszalski 四噪声参数 + 换算面（单频点）。

    fmin_db / fmin_linear: 最小噪声系数（dB / 线性）；
    rn_ohm: 噪声电阻 Rn（Ω；归一值 rn_norm = Rn/Z0 由 to_dict 一并给出）；
    yopt / zopt / gamma_opt: 最优源导纳/阻抗/反射系数（S/Ω/无量纲）；
    tmin_k: 等效最小噪声温度 Tmin = T0·(Fmin−1)（K）；
    f_hz/tg_k/td_k/t0_k/z0: 口径回执；path: "intrinsic"|"embedded"。
    """

    f_hz: float
    fmin_linear: float
    fmin_db: float
    rn_ohm: float
    yopt: complex
    zopt: complex
    gamma_opt: complex
    tmin_k: float
    tg_k: float
    td_k: float
    t0_k: float
    z0: float
    path: str
    trg_k: float | None = None
    trs_k: float | None = None

    @property
    def rn_norm(self) -> float:
        """归一噪声电阻 Rn/Z0（active_chain.noise_figure_circle 口径）。"""
        return self.rn_ohm / self.z0

    def to_dict(self) -> dict[str, Any]:
        def _cx(v: complex) -> dict[str, float]:
            return {"re": round(v.real, 12), "im": round(v.imag, 12)}

        return {
            "f_hz": self.f_hz,
            "fmin_linear": round(self.fmin_linear, 12),
            "fmin_db": round(self.fmin_db, 9),
            "rn_ohm": round(self.rn_ohm, 9),
            "rn_norm": round(self.rn_norm, 12),
            "yopt": _cx(self.yopt),
            "zopt": _cx(self.zopt),
            "gamma_opt": _cx(self.gamma_opt),
            "tmin_k": round(self.tmin_k, 9),
            "tg_k": self.tg_k,
            "td_k": self.td_k,
            "t0_k": self.t0_k,
            "z0": self.z0,
            "path": self.path,
            "trg_k": self.trg_k,
            "trs_k": self.trs_k,
        }


def _branch_terms(w: float, model: FetSmallSignal) -> tuple[float, float, float]:
    """本征栅支路导纳 Ygs 的 (ggs, b, |β|²) 三元组。"""
    wc = w * model.cgs_f
    denom = 1.0 + (wc * model.ri_ohm) ** 2
    ggs = wc * wc * model.ri_ohm / denom
    b = wc / denom
    beta2 = 1.0 / denom
    return ggs, b, beta2


def _intrinsic_closed_form(
    w: float, model: FetSmallSignal, tg_k: float, td_k: float, t0_k: float
) -> tuple[float, float, complex]:
    """本征四参闭式（Fmin 线性, Rn Ω, Yopt）——裁判/引源三重钉，见模块头。"""
    ggs, b, beta2 = _branch_terms(w, model)
    w_prime = td_k * model.gds_s / (beta2 * model.gm_s * model.gm_s)
    rn_ohm = w_prime / t0_k
    gopt = math.sqrt(ggs * ggs + tg_k * beta2 * model.gm_s * model.gm_s * ggs / (td_k * model.gds_s))
    yopt = complex(gopt, -b)
    fmin = 1.0 + 2.0 * rn_ohm * (gopt + ggs)
    return fmin, rn_ohm, yopt


# ─── 数值嵌入路径（rg/rs > 0：节点分析精确嵌入 + 四参提取）───────────────────


def _build_nodal(w: float, ys: complex, model: FetSmallSignal) -> tuple[np.ndarray, dict[str, int]]:
    """嵌入网络的节点导纳矩阵（P8 批广义拓扑）。

    节点：gext, g, x, d[, dext][, s]（按需合并/省略）。

        gext-[Cpg对地]-[Rg+Lg]-g-[Cgs]-x-[Ri]-s-[Rs+Ls]-地；
        d-[Cds+gds]-s；g-[Cgd]-d；gm·e^{−jwτ}·(Vg−Vx) 从 d 抽到 s；
        d-[Ld]-dext-[Cpd对地]。

    rg=lg=0 → gext≡g；ld=0 → dext≡d；rs=ls=0 → s≡地（消元）。
    全寄生=0 时退化为既有两拓扑（本征/rg-rs 嵌入，逐位不变）。
    """
    has_gate = model.rg_ohm > 0.0 or model.lg_h > 0.0
    has_drain = model.ld_h > 0.0
    has_src = model.rs_ohm > 0.0 or model.ls_h > 0.0
    nodes = (["gext", "g"] if has_gate else ["g"]) + ["x", "d"] + (
        ["dext"] if has_drain else []) + (["s"] if has_src else [])
    idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)
    mat = np.zeros((n, n), dtype=complex)

    def stamp(a: str, b: str | None, y: complex) -> None:
        ia = idx[a]
        mat[ia, ia] += y
        if b is not None:
            ib = idx[b]
            mat[ib, ib] += y
            mat[ia, ib] -= y
            mat[ib, ia] -= y

    gate_ext = "gext" if has_gate else "g"
    src_node = "s" if has_src else None
    if has_gate:
        # 栅键合支路 Rg+Lg 串联（rg=0 时纯电感）
        stamp("gext", "g", 1.0 / complex(model.rg_ohm, w * model.lg_h))
    if model.cpg_f > 0.0:
        stamp(gate_ext, None, 1j * w * model.cpg_f)
    stamp(gate_ext, None, ys)
    stamp("g", "x", 1j * w * model.cgs_f)
    stamp("x", src_node, 1.0 / model.ri_ohm)
    if model.cgd_f > 0.0:
        stamp("g", "d", 1j * w * model.cgd_f)
    if model.cds_f > 0.0:
        stamp("d", src_node, 1j * w * model.cds_f)
    stamp("d", src_node, model.gds_s)
    if has_drain:
        stamp("d", "dext", 1.0 / (1j * w * model.ld_h))
        if model.cpd_f > 0.0:
            stamp("dext", None, 1j * w * model.cpd_f)
    gm = model.gm_s * np.exp(-1j * w * model.tau_s)  # τ 传输延迟（无损相位）
    ig, ix, id_ = idx["g"], idx["x"], idx["d"]
    mat[id_, ig] -= gm
    mat[id_, ix] += gm
    if has_src:
        is_ = idx["s"]
        mat[is_, ig] += gm
        mat[is_, ix] -= gm
        # 源键合支路 Rs+Ls 串联对地（漏写即源节点浮空，见 #118 裁判）
        stamp("s", None, 1.0 / complex(model.rs_ohm, w * model.ls_h))
    return mat, idx


def _vth_drain(
    mat: np.ndarray, idx: dict[str, int], injections: dict[str, float]
) -> complex:
    """输出端口开路（戴维南）电压，给定节点噪声电流注入（接地合并节点自动丢弃）。

    输出端口 = 外漏节点 dext（ld>0）或本征漏节点 d（P8 批起按拓扑分派）。
    """
    rhs = np.zeros(len(idx), dtype=complex)
    for name, cur in injections.items():
        if name in idx:
            rhs[idx[name]] += cur
    v = np.linalg.solve(mat, rhs)
    drain_ext = "dext" if "dext" in idx else "d"
    return complex(v[idx[drain_ext]])


def _f_of_ys(
    w: float,
    ys: complex,
    model: FetSmallSignal,
    temps: dict[str, float],
    t0_k: float,
) -> float:
    """裁判式 F(Ys)：1 + Σ T_i·g_i·|H_i|²/(T0·Gs·|Hs|²)（惯例无关，见模块头②）。

    噪声源清单（P8 批拓扑）：Ri@Tg（跨 g-s 支路诺顿）、Rds@Td（跨 d-s）、
    Rg@Trg（栅键合支路导纳实部）、Rs@Trs（源键合支路导纳实部）——电感/
    电容/τ 为无损元件不挂噪声，只参与频率形变（F(f)/Rn(f)/Γopt(f) 全带面
    的物理来源）。
    """
    gs = ys.real
    if gs <= _EPS:
        raise ValueError("源电导 Gs 必须 >0")
    mat, idx = _build_nodal(w, ys, model)
    src_in = "gext" if "gext" in idx else "g"
    hs = _vth_drain(mat, idx, {src_in: 1.0})
    ggs, _, _ = _branch_terms(w, model)
    # Ri 串联噪声 → 支路诺顿源（跨 g-s）：PSD 4kTg·ggs
    num = 0.0
    if model.ri_ohm > 0.0 and ggs > 0.0:
        hg = _vth_drain(mat, idx, {"g": 1.0, "s": -1.0})
        num += temps["tg"] * ggs * abs(hg) ** 2
    hd = _vth_drain(mat, idx, {"d": 1.0, "s": -1.0})
    num += temps["td"] * model.gds_s * abs(hd) ** 2
    if model.rg_ohm > 0.0 and "gext" in idx:
        # 栅键合支路（Rg+jwLg）噪声 → 诺顿源跨 gext-g：PSD 4kTrg·Re{Y_branch}
        y_br = 1.0 / complex(model.rg_ohm, w * model.lg_h)
        h_rg = _vth_drain(mat, idx, {"gext": 1.0, "g": -1.0})
        num += temps["trg"] * abs(h_rg) ** 2 * y_br.real
    if model.rs_ohm > 0.0 and "s" in idx:
        # 源键合支路（Rs+jwLs）噪声 → 诺顿源对地：PSD 4kTrs·Re{Y_branch}
        y_sb = 1.0 / complex(model.rs_ohm, w * model.ls_h)
        h_rs = _vth_drain(mat, idx, {"s": 1.0})
        num += temps["trs"] * abs(h_rs) ** 2 * y_sb.real
    return 1.0 + num / (t0_k * gs * abs(hs) ** 2)


def _extract_four_from_f(
    w: float,
    samples: list[tuple[complex, float]],
) -> tuple[float, float, complex]:
    """从 F(Ys) 样本线性提取四参（去退化四列基，列归一化 LSQ）。

    展开式 F·Gs = (Fmin−2RnGo)·G + Rn(G²+B²) − 2RnBo·B + Rn(Go²+Bo²) 中
    Fmin·Gs 与 −2RnGo·G 共用回归列 G（五列基秩亏，最小范数解任意分摊），
    故取四列基 [G, G²+B², B, 1] → (k, Rn, θb, θc)：
        Bo = −θb/(2Rn)，Go = √(θc/Rn − Bo²)（物理正根），Fmin = k + 2Rn·Go。
    θc/Rn < Bo²（负开方）→ ValueError（采样退化守卫）。
    """
    rows = np.array(
        [[ys.real, ys.real**2 + ys.imag**2, ys.imag, 1.0] for ys, _ in samples]
    )
    rhs = np.array([f * ys.real for ys, f in samples])
    scales = np.linalg.norm(rows, axis=0)
    scales[scales < _EPS] = 1.0
    sol, *_ = np.linalg.lstsq(rows / scales, rhs, rcond=None)
    k_fit, rn, theta_b, theta_c = (
        float(v) / s for v, s in zip(sol, scales, strict=True)
    )
    if rn <= 0.0:
        raise ValueError(f"四参提取退化：Rn={rn:.3e}（采样集不适定）")
    bopt = -theta_b / (2.0 * rn)
    go_sq = theta_c / rn - bopt * bopt
    if go_sq <= 0.0:
        raise ValueError(
            f"四参提取退化：Go²={go_sq:.3e} ≤0（采样集不适定，#364④ 判据 is not None 族）"
        )
    gopt = math.sqrt(go_sq)
    fmin = k_fit + 2.0 * rn * gopt
    return fmin, rn, complex(gopt, bopt)


def _embedded_noise_params(
    w: float,
    model: FetSmallSignal,
    tg_k: float,
    td_k: float,
    t0_k: float,
    trg_k: float,
    trs_k: float,
) -> tuple[float, float, complex]:
    """rg/rs>0 的精确数值嵌入：采样 F(Ys) → 四参（模块头②裁判的同源内路径）。"""
    temps = {"tg": tg_k, "td": td_k, "trg": trg_k, "trs": trs_k}
    b_scale = w * model.cgs_f
    samples: list[tuple[complex, float]] = []
    for g in np.geomspace(b_scale * 5e-3, b_scale * 10.0, 10):
        for b in np.linspace(-3.0 * b_scale, 1.0 * b_scale, 5):
            ys = complex(g, b)
            samples.append((ys, _f_of_ys(w, ys, model, temps, t0_k)))
    return _extract_four_from_f(w, samples)


# ─── 对外主口 ────────────────────────────────────────────────────────────────


def pospieszalski_noise_params(
    model: FetSmallSignal,
    f_hz: float,
    tg_k: float,
    td_k: float,
    *,
    t0_k: float = T0_DEFAULT_K,
    z0: float = DEFAULT_Z0,
    trg_k: float | None = None,
    trs_k: float | None = None,
) -> FetNoiseParams:
    """小信号等效电路 + 两等效温度 → Pospieszalski 四噪声参数（单频点）。

    model: FetSmallSignal（先 validate）；
    f_hz: 频率（Hz，>0）；tg_k/td_k: 栅/漏等效温度（K，>0；td=0 拒收——
        Γopt 退化为 −1 的无漏噪极限，测试用 td→0⁺ 钉下确界）；
    t0_k: 参考温度（K，>0，缺省 290）；z0: 归一阻抗（Ω，>0，缺省 50）；
    trg_k/trs_k: Rg/Rs 寄生噪声温度（K，缺省 None→t0_k，环境口径）；
        仅 rg_ohm/rs_ohm>0 时参与。

    rg_ohm=rs_ohm=0 且其余寄生全零 → 解析闭式（模块头①②③三重钉）；
    任一寄生非零 → 节点分析精确数值嵌入 + 线性四参提取（与闭式在零寄生处
    一致到 1e-9，测试钉）。全带扫描面见 pospieszalski_noise_sweep。
    """
    model = model.validate()
    w = 2.0 * math.pi * _positive(f_hz, "f_hz")
    tg = _positive(tg_k, "tg_k")
    td = _positive(td_k, "td_k")
    t0 = _positive(t0_k, "t0_k")
    z0_ = _positive(z0, "z0")
    trg = t0 if trg_k is None else _positive(trg_k, "trg_k")
    trs = t0 if trs_k is None else _positive(trs_k, "trs_k")
    if not model.has_parasitics():
        fmin, rn, yopt = _intrinsic_closed_form(w, model, tg, td, t0)
        path = "intrinsic"
    else:
        fmin, rn, yopt = _embedded_noise_params(w, model, tg, td, t0, trg, trs)
        path = "embedded"
    zopt = 1.0 / yopt
    gamma_opt = z_to_gamma(zopt, z0_)
    return FetNoiseParams(
        f_hz=float(f_hz),
        fmin_linear=fmin,
        fmin_db=10.0 * math.log10(fmin),
        rn_ohm=rn,
        yopt=yopt,
        zopt=zopt,
        gamma_opt=gamma_opt,
        tmin_k=t0 * (fmin - 1.0),
        tg_k=tg,
        td_k=td,
        t0_k=t0,
        z0=z0_,
        path=path,
        trg_k=trg_k,
        trs_k=trs_k,
    )


# ─── P8 全带面（NF(f)/Rn(f)/Γopt(f) 扫描）────────────────────────────────────


def pospieszalski_noise_sweep(
    model: FetSmallSignal,
    f_hz: Any,
    tg_k: float,
    td_k: float,
    *,
    t0_k: float = T0_DEFAULT_K,
    z0: float = DEFAULT_Z0,
    trg_k: float | None = None,
    trs_k: float | None = None,
) -> dict[str, Any]:
    """全带四噪声参数扫描（W4-C P8）：逐频点 pospieszalski_noise_params。

    f_hz: 频率数组（Hz，1-D、全正有限；顺序随入参保留）；其余口径同
    pospieszalski_noise_params。返回 JSON 可序列化 dict::

        {"n_points", "f_hz": [...], "fmin_linear": [...], "fmin_db": [...],
         "rn_ohm": [...], "rn_norm": [...], "yopt": [{"re","im"}...],
         "gamma_opt": [{"re","im"}...], "tmin_k": [...], "path": [...]}

    频率形变语义：寄生/封装（Cgd/Cds/τ/键合线/焊盘电容）全部无损——不新增
    噪声源，只改变传递与匹配随频率的演化，故 NFmin(f)/Rn(f)/Γopt(f) 随 f
    展宽（Pospieszalski 本征域 ω↑→NFmin 单调升特性在封装后保持但斜率被
    失配重塑）。纯函数零 IO；确定性内核（规则 7：LLM 不产数）。
    """
    arr = np.atleast_1d(np.asarray(f_hz, dtype=float))
    if arr.ndim != 1 or arr.size == 0:
        raise ValueError(f"f_hz 须为非空一维数组，得到 shape {np.shape(f_hz)!r}")
    if not np.all(np.isfinite(arr)) or np.any(arr <= 0.0):
        raise ValueError("f_hz 必须全为正且有限（Hz）")
    model = model.validate()
    rows = [
        pospieszalski_noise_params(
            model, float(f), tg_k, td_k,
            t0_k=t0_k, z0=z0, trg_k=trg_k, trs_k=trs_k,
        )
        for f in arr.tolist()
    ]

    def _cx(v: complex) -> dict[str, float]:
        return {"re": round(v.real, 12), "im": round(v.imag, 12)}

    return {
        "n_points": len(rows),
        "f_hz": [r.f_hz for r in rows],
        "fmin_linear": [round(r.fmin_linear, 12) for r in rows],
        "fmin_db": [round(r.fmin_db, 9) for r in rows],
        "rn_ohm": [round(r.rn_ohm, 9) for r in rows],
        "rn_norm": [round(r.rn_norm, 12) for r in rows],
        "yopt": [_cx(r.yopt) for r in rows],
        "gamma_opt": [_cx(r.gamma_opt) for r in rows],
        "tmin_k": [round(r.tmin_k, 9) for r in rows],
        "path": [r.path for r in rows],
    }


# ─── 下游换算面（复用 active_chain，不重复实现）──────────────────────────────


def noise_figure_at(params: FetNoiseParams, gamma_s: complex) -> float:
    """给定源反射系数的噪声系数 F(Γs)（dB）——active_chain.noise_figure_db。"""
    return float(noise_figure_db(params.fmin_db, params.gamma_opt, params.rn_norm, gamma_s))


def noise_circle(params: FetNoiseParams, nf_db: float) -> Circle:
    """等噪声圆（Γs 平面圆心+半径）——active_chain.noise_figure_circle 复用。

    nf_db < NFmin 时上游 ValueError（f_db 低于 Fmin）。归一阻抗取
    params.z0（Rn_norm/Γopt 均依该口径，不允许换口径）。
    """
    return noise_figure_circle(params.fmin_db, params.gamma_opt, params.rn_norm, nf_db)


def lna_source_match(
    params: FetNoiseParams,
    sparams: np.ndarray | None = None,
    gamma_l: complex | None = None,
) -> dict[str, Any]:
    """LNA 源匹配最小件：噪声最优源点 Γs=Γopt → 该点 NF；可选增益端口。

    **口径注记（形式论钉死）**：四参噪声式
    F = Fmin + 4·rn·|Γs−Γopt|²/((1−|Γs|²)|1+Γopt|²)
    （active_chain.noise_figure_db 同式）的极小点在 **Γs = Γopt 本身**，
    不取共轭（Γopt 已是"最优源反射系数"定义值；任务书"Γs=Γopt*"是阻抗
    共轭匹配的口语读法——功率共轭匹配才取 *，噪声最优不取）。故
    nf_at_match == nf_min 为内建恒等（测试钉）。

    sparams 给出时（2x2 S 矩阵，单频点）→ 追加建议负载 ΓL（缺省
    conj(Γout(Γs))，输出共轭口径）与该 (Γs,ΓL) 的变换增益
    （active_chain.transducer_gain_db）。纯建议面，不判稳定性
    （稳定性/双共轭匹配走 active_chain.simultaneous_conjugate_match）。
    """
    gamma_s = complex(params.gamma_opt)
    out: dict[str, Any] = {
        "gamma_s": {"re": round(gamma_s.real, 12), "im": round(gamma_s.imag, 12)},
        "nf_at_match_db": round(noise_figure_at(params, gamma_s), 9),
        "nf_min_db": round(params.fmin_db, 9),
    }
    if sparams is not None:
        s = np.asarray(sparams, dtype=complex)
        if s.shape != (2, 2):
            raise ValueError(f"期望 2x2 S 矩阵, 得到 {s.shape}")
        gl = np.conj(output_gamma(s, gamma_s)) if gamma_l is None else complex(gamma_l)
        out["gamma_l"] = {"re": round(gl.real, 12), "im": round(gl.imag, 12)}
        out["transducer_gain_db"] = round(float(transducer_gain_db(s, gamma_s, gl)), 9)
    return out


def transition_frequency_hz(model: FetSmallSignal) -> float:
    """截止频率 fT = gm/(2π·(Cgs+Cgd))（Hz）——小信号数据入参显式。

    fT 量级注记：Pospieszalski 低频段 NFmin−1 ∝ ω·sqrt(...)，与 f/fT 同尺度；
    工作频率远低于 fT（≲fT/10）时本征闭式域可信，接近/超过 fT 时
    Cgd/Cds/τ 不可忽略（超出本模块域，如实由调用方改走测量/EM 通道）。
    """
    model = model.validate()
    return model.gm_s / (2.0 * math.pi * (model.cgs_f + model.cgd_f))


def fukui_fmin(model: FetSmallSignal, f_hz: float, kf: float, *, include_ri: bool = False) -> float:
    """Fukui 经验式对照面（可选）：Fmin = 1 + kf·f·Cgs·√R/gm。

    H. Fukui, "Design of Microwave GaAs MESFET's for Broadband Low-Noise
    Amplifiers," IEEE Trans. Microwave Theory Tech., vol. MTT-27, pp.
    643-650, July 1979（经验归并式；√R 的 R = Rg+Rs（include_ri=False，
    三参数 kf/Rg/Rs 口径）或 Rg+Rs+Ri（含栅充电电阻变体）。

    kf 为**单位约定相关**的经验系数：本函数取全 SI 量纲口径（f[Hz]·Cgs[F]/
    gm[S]·√R[Ω]），无内嵌魔数（#118：不可达单源精确数不虚构）——kf 由
    调用方按所选文献的量纲约定显式标定供给。用途是与 Pospieszalski 做
    量级互证（预声明 ±30% 带，不逐位）。
    """
    model = model.validate()
    f = _positive(f_hz, "f_hz")
    k = _positive(kf, "kf")
    r_total = model.rg_ohm + model.rs_ohm + (model.ri_ohm if include_ri else 0.0)
    return 1.0 + k * f * model.cgs_f * math.sqrt(r_total) / model.gm_s


def _cx_from_dict(obj: dict[str, Any]) -> complex:
    return complex(float(obj["re"]), float(obj["im"]))


def params_from_dict(obj: dict[str, Any]) -> FetNoiseParams:
    """to_dict 的逆（服务层 JSON 往返用）；trg_k/trs_k 判缺失 is not None。"""
    return FetNoiseParams(
        f_hz=float(obj["f_hz"]),
        fmin_linear=float(obj["fmin_linear"]),
        fmin_db=float(obj["fmin_db"]),
        rn_ohm=float(obj["rn_ohm"]),
        yopt=_cx_from_dict(obj["yopt"]),
        zopt=_cx_from_dict(obj["zopt"]),
        gamma_opt=_cx_from_dict(obj["gamma_opt"]),
        tmin_k=float(obj["tmin_k"]),
        tg_k=float(obj["tg_k"]),
        td_k=float(obj["td_k"]),
        t0_k=float(obj["t0_k"]),
        z0=float(obj["z0"]),
        path=str(obj["path"]),
        trg_k=None if obj.get("trg_k") is None else float(obj["trg_k"]),
        trs_k=None if obj.get("trs_k") is None else float(obj["trs_k"]),
    )
