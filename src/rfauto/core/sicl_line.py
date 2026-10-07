"""基片集成同轴线（SICL）特性阻抗闭式内核：矩形外腔（接地过孔墙）内悬置内导体。

结构口径（round3 F-F 表件 7）
-----------------------------
SICL 截面 = 矩形同轴：外腔宽 a、高 b（均为过孔墙中心线距），内导体条带宽 w、
厚 t（t=0 薄带合法），腔内介质 εr——准 TEM 主模。Z0 由准静态电容给出：
Z0 = sqrt(L/C)，L·C_air = μ0ε0（洛伦兹恒等），Z0 = Z0_air/sqrt(εeff)。

引源与可达性登记（铁律 1c/#118/#300：常数与公式形态逐条有出处；不可达如实标）
-----------------------------------------------------------------------------
- Gatti, Bozzi, Perregrini, Wu, Bosisio, "A Novel Substrate Integrated Coaxial
  Line (SICL) for Wide-Band Applications," 36th EuMC 2006, pp. 1614–1617
  （SICL 开山论文）。**可达性**：IEEE/RG 均付费墙（2026-09-27 实测仅摘要），
  本模块**不抄该文常数**。勘误登记：研究扩充 round3
  §二写"Gatti 2010"——2010 EuMC 的 Gatti/Bozzi 是 SICL Butler matrix 应用论文，
  闭式相关的 canonical 开山篇为上述 2006 论文。
- 闭式选型（矩形同轴 = 屏蔽带状线工程闭式族；Howe《Stripline Circuit Design》
  1974 / Cristal–Gunston 矩形同轴族口径，文献族归属 **UNVERIFIED-1**：原文未
  取得可双源核对的文本）：

      k = tanh(π a / 2b) · sech(π w / 2b)          （共形模数，壁形式）
      C_thin/ε = 4 · K(k') / K(k)                   （零厚总电容，K 完全椭圆积分）
      Z0_air = 30π · K(k) / K(k')                   （εr=1）

  公式形态按"极限自检 + 独立数值裁判"钉死（#118/#122，裁判见
  tests/unit/test_sicl_line.py 的 FD 准静态电容，零共享代码）：
    · a→∞：k→sech(πw/2b)=tanh 补模数 → 恒等退化 repo exact 带状线闭式
      （core/calculators._stripline_z0，Cohn 共形精确解）；
    · w≫a 且 b/w→0：Z0→η0·b/(4w·√εr)（上下两间隙各 b/2 的平行板极限；
      渐近展开 C = 4w/b + 8·ln2/π + O(b/w)——共形闭式带 O(1) 常数边缘项，
      b/w=0.02 时 PP 偏差 −0.9%，小模数走 ln(4/k) 对数分支防 ellipk 溢出）；
    · w→0：对数发散（零厚细条 C→0），物理正确；
    · FD 裁判实测带见下方"声明域"。
- 有限厚扩展（**UNVERIFIED-2**，工程分解：平行板基项取真实间隙 (b−t) + 边缘
  项冻结于零厚值）：

      C(t)/ε = 4w/(b−t) + [C_thin/ε − 4w/b]

  t=0 逐位还原闭式；FD 裁判实测：t/b=0.02 时上式仍在声明带内，t/b=0.05 恶化
  到 ≤11.3%（边缘项随厚度增长未被建模，如实登记不掩盖）。
- 悬置部分填充（介质以条带为中面对称占 h_frac·b）：εeff = 1+(εr−1)·h_frac
  线性填充因子（**UNVERIFIED-3**，上界锚：边缘通量偏好空气 → 真实 εeff 更低）。
  双层 FD 裁判实测：εeff 高估 +16.8%/+15.7%（h/b=0.5/0.8，εr=4.4；若空气线
  精确则 Z0 相应低估 −7.5%/−7.0%）；h_frac=1 严格还原均匀口径。此路径仅
  登记面，不进 ±5% 判定带。
- SIW 过孔经验迁移（仅 docstring 登记，不实现门）：过孔直径 d 与列心距 s 迁移
  repo SIW 口径（core/synthesis.synthesize_siw_model：s ≤ 2d、d < λ_sub/5）；
  SICL 单模（准 TEM 无高次模）带宽上界 = 过孔墙矩形腔 TE10 截止类比
  （Gatti 2006 口径，**UNVERIFIED-4**：原文不可达，未核对系数）。

声明域与实测带（FD 裁判，#122 判据先行）
----------------------------------------
- 判定口径：均匀介质、薄带 t/b=0.02、双路径同 t 对照、b 归一网格。
- 声明域：1.5 ≤ a/b ≤ 4，0.3 ≤ w/b ≤ 0.9，gap = (a−w)/2 ≥ 0.5b。
- 实测带：|Z0_闭式/Z0_FD − 1| ≤ 5%（10 点网格实测 max +4.54%；系统性为正
  = 闭式低估电容/高估 Z0，缺壁槽电容贡献，方向已登记）。gap < 0.5b 时退化
  （gap=0.3b 实测 +9.5%~+10.5%），越域调用由 SiclResult.in_referee_band
  如实标记，不抛错、不掩盖。
- 裁判自身验证：对 exact 带状线族（a/b=8 方格网，双路径同族不同源）实测
  −0.9%~−1.8%；ε 缩放恒等 C(εr)=εr·C(1) 逐位（求解器线性）；加密收敛
  误差单调降（6.0% → 0.44% → 0.18%）。

接口约定
--------
- 入参 mm（几何）/无量纲（εr、h_frac），出参 SI（Z0 Ω、C F/m）。
- 纯函数零 IO；判缺失一律 is not None（#364④）；数值入参显式拒收 bool
  （df7+⑯）；越界/非法显式 ValueError 不外推。
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass

C0 = 299792458.0
#: 真空介电常数 ε0（F/m；2019 SI 修订后惯用近似值，与 core/calculators 同口径）
EPS0 = 8.8541878128e-12
#: 自由空间波阻抗 η0 = μ0·c（PP 极限与文档口径用）
ETA0 = 376.730313668

#: 声明域常量（FD 裁判实测带的作用域，模块级导出供调用方设门）
A_OVER_B_RANGE: tuple[float, float] = (1.5, 4.0)
W_OVER_B_RANGE: tuple[float, float] = (0.3, 0.9)
GAP_OVER_B_MIN = 0.5
T_OVER_B_JUDGED = 0.02
#: 判定带（#122 预声明）：闭式 vs FD 裁判 |rel| 上限（实测 max +4.54%，留实测余量）
JUDGED_BAND = 0.05

# 小模数对数渐近切换点：k < _K_SMALL 时 K(k)≈π/2、K(k')≈ln(4/k)（ellipk 在
# m=k'²→1 处溢出 inf，b/w→0 的平行板极限必须走解析分支）
_K_SMALL = 1e-8


def _finite(value: float, name: str) -> float:
    """入参收敛为有限 float；bool 显式拒收（df7+⑯：float(True)=1.0 静默污染）。"""
    if isinstance(value, bool):
        raise ValueError(f"sicl_line: {name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"sicl_line: {name} 必须为有限数，得到 {value!r}")
    return out


def _positive(value: float, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"sicl_line: {name} 必须 >0，得到 {value!r}")
    return out


@dataclass(frozen=True)
class SiclResult:
    """一次 SICL 闭式评估的全部量（SI：Z0 Ω、C F/m；几何比为无量纲）。"""

    z0_ohm: float            # 特性阻抗（准 TEM）
    eps_eff: float           # 准静态有效介电常数（均匀=εr；悬置=线性填充模型）
    c_f_m: float             # 单位长度电容（含介质，F/m）
    c_air_f_m: float         # 同几何 εr=1 口径电容（F/m）；c = eps_eff·c_air（模型恒等）
    k_conformal: float       # 共形模数 k=tanh(πa/2b)·sech(πw/2b)，登记面
    a_over_b: float
    w_over_b: float
    t_over_b: float
    gap_over_b: float        # (a−w)/2/b：条带缘-过孔墙无量纲间隙
    h_frac: float | None     # 悬置介质半高分数；None=均匀填充
    in_referee_band: bool    # 落在 FD 裁判实测 ±5% 声明域内（见模块 docstring）

    def to_dict(self) -> dict:
        """JSON 可序列化字典（float/bool/None）。"""
        return asdict(self)

    def to_json(self, indent: int | None = None) -> str:
        """JSON 字符串（调用方可直接落盘）。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def _k_ratio(k: float) -> float:
    """K(k')/K(k)（K 完全椭圆积分；scipy ellipk(m) 的 m=k²）。

    k → 0 时走对数渐近 K(k)≈π/2、K(k')≈ln(4/k)：既避免 ellipk(m→1) 溢出
    inf（b/w→0 平行板极限），也保持 PP 极限精度（k=1e-13 时渐近式相对
    误差 O(k²ln²k) 可忽略）。
    """
    if k < _K_SMALL:
        return math.log(4.0 / k) / (0.5 * math.pi)
    from scipy.special import ellipk

    return float(ellipk(1.0 - k * k)) / float(ellipk(k * k))


def sicl_k_conformal(w_mm: float, a_mm: float, b_mm: float) -> float:
    """共形模数 k = tanh(πa/2b)·sech(πw/2b)（壁形式，登记面）。"""
    w = _positive(w_mm, "w_mm")
    a = _positive(a_mm, "a_mm")
    b = _positive(b_mm, "b_mm")
    if w >= a:
        raise ValueError(
            f"sicl_line: 内导体宽 w={w}mm 须小于外腔宽 a={a}mm（条带不得越出/触及过孔墙）")
    return math.tanh(math.pi * a / (2.0 * b)) / math.cosh(math.pi * w / (2.0 * b))


def sicl_c_norm(w_mm: float, a_mm: float, b_mm: float, t_mm: float) -> float:
    """空气口径归一化电容 C/ε0（F/m per ε0），t=0 走零厚闭式、t>0 走分解式。

    分解式（UNVERIFIED-2）：C(t)/ε0 = 4w/(b−t) + [C_thin/ε0 − 4w/b]，
    平行板基项随真实间隙 (b−t) 收紧、边缘项冻结于零厚值。
    """
    w = _positive(w_mm, "w_mm")
    a = _positive(a_mm, "a_mm")
    b = _positive(b_mm, "b_mm")
    if w >= a:
        raise ValueError(
            f"sicl_line: 内导体宽 w={w}mm 须小于外腔宽 a={a}mm")
    t = _finite(t_mm, "t_mm")
    if t < 0.0:
        raise ValueError(f"sicl_line: 条带厚 t_mm 必须 >=0，得到 {t_mm!r}")
    if t >= b:
        raise ValueError(
            f"sicl_line: 条带厚 t={t}mm 须小于腔高 b={b}mm（上下间隙须为正）")
    c_thin = 4.0 * _k_ratio(sicl_k_conformal(w, a, b))
    if t == 0.0:
        return c_thin
    return 4.0 * w / (b - t) + (c_thin - 4.0 * w / b)


def sicl_closed_form(
    w_mm: float,
    a_mm: float,
    b_mm: float,
    t_mm: float = 0.0,
    eps_r: float = 1.0,
    h_frac: float | None = None,
) -> SiclResult:
    """SICL 矩形同轴闭式主入口：(w, a, b, t, εr, h_frac) → (Z0, εeff, C)。

    h_frac=None 均匀介质（εeff=εr）；0≤h_frac≤1 介质以条带为中面对称占
    h_frac·b（线性填充因子模型，UNVERIFIED-3 上界锚）。越界 ValueError。
    """
    er = _finite(eps_r, "eps_r")
    if er < 1.0:
        raise ValueError(f"sicl_line: eps_r 必须 >=1（负/空气以下介电常数非物理），得到 {eps_r!r}")
    if h_frac is not None:
        hf = _finite(h_frac, "h_frac")
        if not 0.0 <= hf <= 1.0:
            raise ValueError(f"sicl_line: h_frac 必须在 [0, 1]，得到 {h_frac!r}")
    else:
        hf = None
    c_air = EPS0 * sicl_c_norm(w_mm, a_mm, b_mm, t_mm)
    if hf is None or hf == 1.0:
        eps_eff = er
    elif hf == 0.0:
        eps_eff = 1.0
    else:
        eps_eff = 1.0 + (er - 1.0) * hf
    c_total = c_air * eps_eff
    z0_air = 1.0 / (C0 * c_air)
    z0 = z0_air / math.sqrt(eps_eff)
    w = float(w_mm)
    a = float(a_mm)
    b = float(b_mm)
    t = float(t_mm)
    a_over_b = a / b
    w_over_b = w / b
    t_over_b = t / b
    gap_over_b = (a - w) / (2.0 * b)
    in_band = (
        A_OVER_B_RANGE[0] <= a_over_b <= A_OVER_B_RANGE[1]
        and W_OVER_B_RANGE[0] <= w_over_b <= W_OVER_B_RANGE[1]
        and gap_over_b >= GAP_OVER_B_MIN
        and t_over_b <= T_OVER_B_JUDGED
        and (hf is None or hf == 1.0)
    )
    return SiclResult(
        z0_ohm=z0,
        eps_eff=eps_eff,
        c_f_m=c_total,
        c_air_f_m=c_air,
        k_conformal=sicl_k_conformal(w, a, b),
        a_over_b=a_over_b,
        w_over_b=w_over_b,
        t_over_b=t_over_b,
        gap_over_b=gap_over_b,
        h_frac=hf,
        in_referee_band=in_band,
    )


def sicl_z0(
    w_mm: float,
    a_mm: float,
    b_mm: float,
    t_mm: float = 0.0,
    eps_r: float = 1.0,
    h_frac: float | None = None,
) -> float:
    """特性阻抗 Z0（Ω，准 TEM）。"""
    return sicl_closed_form(w_mm, a_mm, b_mm, t_mm, eps_r, h_frac).z0_ohm


def sicl_eps_eff(
    w_mm: float,
    a_mm: float,
    b_mm: float,
    t_mm: float = 0.0,
    eps_r: float = 1.0,
    h_frac: float | None = None,
) -> float:
    """准静态有效介电常数（均匀=εr；悬置=线性填充模型）。"""
    return sicl_closed_form(w_mm, a_mm, b_mm, t_mm, eps_r, h_frac).eps_eff


def sicl_c_total(
    w_mm: float,
    a_mm: float,
    b_mm: float,
    t_mm: float = 0.0,
    eps_r: float = 1.0,
    h_frac: float | None = None,
) -> float:
    """单位长度电容（F/m，含介质）。"""
    return sicl_closed_form(w_mm, a_mm, b_mm, t_mm, eps_r, h_frac).c_f_m
