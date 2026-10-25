"""AP-8 3GPP TS 38.901 数字化（round17 §三 AP-8，P2/L；2026-10-03）。

UMa/UMi/RMa/InH-Office 路损闭式 + O2I 穿透 + TDL-A..E 谱表；CDL 留
接口。**确定性内核零随机数**：标准中的随机要素（阴影衰落 σSF、
UMa 有效环境高度 hE 的随机抽取、O2I σP、d2D-in 均匀分布）以
**参数化 + 分布参数透出**承载（铁律 7：数值只在确定性内核；抽样
由调用方/服务层做），核心返回均值口径路径损耗。

双源核验（#118/#300；2026-10-03 实取）
------------------------------------
- **主源**：3GPP TS 38.901 V21.0.0 (2024-09) 官方 docx
  （ftp.3gpp.org/Specs/archive/38_series/38.901/38901-j50.zip，
  runs/ge8_followup/wave_c/_c3_refs/ 存档）——Table 7.4.1-1（路损）、
  Table 7.4.3-1/2/3（O2I 材料/模型/legacy）、Table 7.7.2-1..5（TDL）、
  NOTE 1/2/5（断点/频域）逐条转录。
- **第二源 1（正式版本载体）**：ETSI TR 138 901 V19.2.0 官方 PDF
  （etsi.org/deliver/etsi_tr/.../tr_138901v190200p.pdf）——InH/UMi/
  O2I 材料表逐式比对一致（含 IRR glass 25.4+0.11f 的 Rel-19 更新值，
  V19.2 与 V21 一致；更旧版本的 23.02+0.0755f 系历史值，本文档
  不采用）。
- **第二源 2（独立实现互证）**：NVIDIA Sionna（src/sionna/phy/
  channel/tr38901/uma_scenario.py / umi_scenario.py /
  rma_scenario.py / lsp.py 与 models/v19_2/TDL-*.json）——UMa/UMi/
  RMa PL 逐常数一致；O2I low/high 公式一致；TDL-A..E 五表
  delay/power **逐位一致**（23/23/24/14/15 tap）。
- 引用腐坏纪律（#df6-⑨）：以上数值全部来自 2026-10-03 实取文本，
  无凭记忆复写项。

公式与口径（Table 7.4.1-1；fc 单位 GHz、距离 m 的表式 → 本内核
统一 SI 入参 Hz/m，换算在函数内）
----------------------------------------------------------------
- UMa LOS：PL1 = 28.0+22·lg d3D+20·lg fc（10m≤d2D≤d'BP）；
  PL2 = 28.0+40·lg d3D+20·lg fc − 9·lg(d'BP²+(hBS−hUT)²)
  （d'BP≤d2D≤5km）；d'BP = 4·h'BS·h'UT·fc/c（NOTE 1，h'=h−hE；
  UMa hE 随机规则见 uma_effective_height_rule，确定性口径 hE 入参
  缺省 1.0 m）。σSF=4；hUT∈[1.5,22.5]m、hBS=25m（缺省）。
- UMa NLOS：max(PL_UMa-LOS, 13.54+39.08·lg d3D+20·lg fc−0.6(hUT−1.5))，
  σSF=6；optional 档 32.4+20·lg fc+30·lg d3D，σSF=7.8。
- UMi-Street Canyon LOS：PL1 = 32.4+21·lg d3D+20·lg fc；
  PL2 = 32.4+40·lg d3D+20·lg fc − 9.5·lg(d'BP²+(hBS−hUT)²)；
  hE=1.0 m 固定（NOTE 1）；hBS=10m 缺省。σSF=4。
- UMi NLOS：max(PL_LOS, 35.3·lg d3D+22.4+21.3·lg fc−0.3(hUT−1.5))，
  σSF=7.82；optional 32.4+20·lg fc+31.9·lg d3D，σSF=8.2。
- RMa LOS：dBP = 2π·hBS·hUT·fc/c（NOTE 5）；
  PL1 = 20·lg(40π·d3D·fc/3) + min(0.03h^1.72,10)·lg d3D
        − min(0.044h^1.72,14.77) + 0.002·lg(h)·d3D；
  PL2 = PL1(dBP) + 40·lg(d3D/dBP)；h=平均楼高（5..50m）、W=街宽、
  hBS∈[10,150]m、hUT∈[1,10]m；fc≤30 GHz（NOTE 2：RMa fH=30）。
- RMa NLOS：max(PL_LOS, 161.04−7.1·lg W+7.5·lg h
  −(24.37−3.7(h/hBS)²)·lg hBS+(43.42−3.1·lg hBS)(lg d3D−3)
  +20·lg fc−(3.2(lg(11.75hUT))²−4.97))，σSF=8。
- InH-Office LOS：32.4+17.3·lg d3D+20·lg fc，σSF=3；
  NLOS：max(PL_LOS, 17.30+38.3·lg d3D+24.9·lg fc)，σSF=8.03；
  optional 32.4+20·lg fc+31.9·lg d3D，σSF=8.29；1m≤d3D≤150m。
- 频域（NOTE 2）：0.5 < fc < fH，fH=100 GHz（UMa/UMi/InH）、
  30 GHz（RMa）；域外显式 ValueError。
- NOTE 1 原文 "c = 3.0·10⁸ m/s"（docx 文本抽取呈 "3.0108" 系上标
  8 展平伪象）；本内核用 SI 精确值 299792458（与 3.0e8 差 <0.01%，
  断点距离影响可忽略，如实注记）。

O2I（§7.4.3.1，V21 Table 7.4.3-1/2/3）
--------------------------------------
PL = PLb(3D 距离改 d3D-out+d3D-in) + PLtw + PLin + N(0,σP²)；
材料损耗（f GHz）：glass 2+0.2f / IRR glass 25.4+0.11f（Rel-19 更新
值，V19.2/V21 一致；旧版 23.02+0.0755f 不采用）/ concrete 5+4f /
plywood 1.03+0.17f / wood 4.85+0.12f；
PLtw = 5 − 10·lg(0.3·10^(−Lglass/10)+0.7·10^(−Lconcrete/10))（low）
     = 5 − 10·lg(0.7·10^(−LIRR/10)+0.3·10^(−Lconcrete/10))（high）
     = 5 − 10·lg(0.3·10^(−Lglass/10)+0.7·10^(−Lplywood/10))（low_a），
σP = 4.4/6.5/4.4 dB；PLin = 0.5·d2D-in；
legacy（<6 GHz 单频，Table 7.4.3-3）：PLtw=20 dB 固定、σP=0、
σSF→7 dB；car（§7.4.3.2）：μ=9（金属化车窗 20）、σP=5。
通用式（7.4-3）：PLtw = PLnpi − 10·lg(Σ pᵢ·10^(−Lᵢ/10))，
external_wall_loss_db 暴露（PLnpi 缺省 5 dB）。

TDL（Table 7.7.2-1..5；§7.7.3/§7.7.6）
--------------------------------------
五表 delay/power 逐位转录（主源 docx 文本，第二源 Sionna JSON 互证
逐位一致）；归一化 RMS 时延扩展自检 ≈1.0（表自身舍入内，测试钉）。
§7.7-1 缩放：τₙ = τₙ,norm·DS_wanted（归一 DS=1）。
§7.7.6 K 因子改写：方程 (7.7.6-1/2) 在 V21 docx 中为 Equation.3 OLE
对象（二进制 MathType，文本不可提取）——按语义唯一实现：LOS 功率
不变、Rayleigh tap 同乘 K_model/K_target（线性）（唯一保持 LOS 功率
并达到目标 K 的 NLOS 侧缩放）；K_model 由表自算：TDL-D=13.3 dB、
TDL-E=22 dB 与表 NOTE 声明一致（自洽锚；字面方程转录 UNVERIFIED
如实，#122）。
CDL：任务书明示"留接口"——cdl_profile 为显式 NotImplementedError
接口（表值数字化非本件范围）。

锚（tests/unit/test_tr38901_pathloss.py）
----------------------------------------
1. 双源数字锚：UMa/UMi/RMa/InH 各取 (d,f) 点与 Sionna 形态独立
   重算（同式不同代码路径）对拍；InH 用 ETSI PDF 文本系数独立
   重排算式（17.30 与 38.3 项交换序）。
2. 断点连续性：LOS 两段在 d2D=d'BP 处连续（PL1(d'BP)=PL2(d'BP)，
   UMa/UMi 恒等式：d3D 在断点处两式相等的代数性质由实现保证，
   实测差 <1e-9 dB）；RMa PL2(dBP)=PL1(dBP) 按构造。
3. 频率标度：f 翻倍 → FSPL 段 +6.02 dB（20·lg2）；NLOS 段同。
4. O2I：f→0 极限 glass=2/concrete=5 dB 算术锚；low/high 模型
   f=1GHz 手算值；legacy=20dB 固定。
5. TDL：五表归一 DS≈1（≤0.007，表舍入界）；tap 数/LOS 标志/K
   因子自算=表 NOTE 声明（13.3/22 dB）；K 重标定往返（K→20dB 后
   自算 K=20±1e-9）；§7.7-1 缩放后 DS=DS_wanted。
"""

from __future__ import annotations

import copy
import math
from typing import Any

__all__ = [
    "C0_M_S",
    "CDL_NAMES",
    "TDL_PROFILES",
    "cdl_profile",
    "external_wall_loss_db",
    "inh_office_los_db",
    "inh_office_nlos_db",
    "material_penetration_db",
    "o2i_building_db",
    "o2i_car_db",
    "o2i_legacy_db",
    "rma_los_db",
    "rma_nlos_db",
    "tdl_delay_spread_ns",
    "tdl_k_factor_db",
    "tdl_profile",
    "tdl_rescale_k_factor",
    "tdl_scale_delays",
    "uma_effective_height_rule",
    "uma_los_db",
    "uma_nlos_db",
    "umi_los_db",
    "umi_nlos_db",
]

C0_M_S = 299792458.0

_F_MIN_GHZ = 0.5
_F_MAX_GHZ = 100.0
_F_MAX_RMA_GHZ = 30.0


def _num(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，得 {value!r}")
    return out


def _domain(value: float, lo: float, hi: float, name: str, unit: str) -> float:
    if not (lo <= value <= hi):
        raise ValueError(f"{name} 域盒 [{lo},{hi}] {unit}，得 {value}")
    return value


def _fc_ghz(f_hz: Any, name: str = "f_hz") -> float:
    f = _num(f_hz, name)
    ghz = f / 1e9
    return _domain(ghz, _F_MIN_GHZ, _F_MAX_GHZ, name.replace("_hz", "_ghz"),
                   "GHz")


# ─── UMa（Urban Macro，Table 7.4.1-1）───────────────────────────────────────

def uma_effective_height_rule(d2d_m: Any, h_ut_m: Any) -> dict[str, Any]:
    """UMa 有效环境高度 hE 的随机规则（NOTE 1）——确定性参数透出。

    hE=1m 的概率 p = 1/(1+C(d2D,hUT))；否则从离散均匀
    {12,15,…,hUT−1.5}（步长 3）抽取。C 与 g 定义：
        g = (5/4)·(d2D/100)³·e^(−d2D/150)（d2D>18m，否则 0）
        C = ((hUT−13)/10)^1.5·g（13≤hUT≤23；hUT<13 → 0）
    本函数只返回 p 与支集（不抽样）；hUT≥13 且 hUT−1.5<12 时支集
    为空 → p=1（hE=1m）。
    """
    d = _num(d2d_m, "d2d_m")
    hut = _num(h_ut_m, "h_ut_m")
    if hut < 1.5 or hut > 22.5:
        raise ValueError("h_ut_m 域盒 [1.5,22.5] m（UMa NOTE 1）")
    g = 1.25 * (d / 100.0) ** 3 * math.exp(-d / 150.0) if d > 18.0 else 0.0
    c = ((hut - 13.0) / 10.0) ** 1.5 * g if 13.0 <= hut <= 23.0 else 0.0
    p = 1.0 / (1.0 + c)
    support: list[float] = []
    if hut >= 13.0 and hut - 1.5 >= 12.0:
        k = 0
        while 12.0 + 3.0 * k <= hut - 1.5:
            support.append(round(12.0 + 3.0 * k, 6))
            k += 1
    return {"p_h_e_1m": p, "alt_support_m": support, "c": c, "g": g}


def _uma_umi_breakpoint_m(h_bs: float, h_ut: float, f_hz: float,
                          h_e: float) -> float:
    """d'BP = 4·h'BS·h'UT·fc/c（NOTE 1；SI 精确 c，见模块注记）。"""
    return 4.0 * (h_bs - h_e) * (h_ut - h_e) * f_hz / C0_M_S


def uma_los_db(
    d2d_m: Any, d3d_m: Any, f_hz: Any,
    h_bs_m: float = 25.0, h_ut_m: float = 1.5, h_e_m: float = 1.0,
) -> float:
    """UMa LOS 路损 [dB]（PL1/PL2 两段，Table 7.4.1-1）。

    域盒：10m ≤ d2D ≤ 5km；hUT∈[1.5,22.5]m（hE 随机规则见
    uma_effective_height_rule，确定性口径显式入参）。
    """
    f_ghz = _fc_ghz(f_hz)
    d2 = _num(d2d_m, "d2d_m")
    d3 = _num(d3d_m, "d3d_m")
    _domain(d2, 10.0, 5000.0, "d2d_m", "m")
    hb = _num(h_bs_m, "h_bs_m")
    hu = _domain(_num(h_ut_m, "h_ut_m"), 1.5, 22.5, "h_ut_m", "m")
    he = _num(h_e_m, "h_e_m")
    if he <= 0.0 or he >= min(hb, hu):
        raise ValueError("h_e_m 须为正且小于天线高度")
    dbp = _uma_umi_breakpoint_m(hb, hu, f_hz, he)
    if d2 <= dbp:
        return 28.0 + 22.0 * math.log10(d3) + 20.0 * math.log10(f_ghz)
    return (28.0 + 40.0 * math.log10(d3) + 20.0 * math.log10(f_ghz)
            - 9.0 * math.log10(dbp * dbp + (hb - hu) ** 2))


def uma_nlos_db(
    d2d_m: Any, d3d_m: Any, f_hz: Any,
    h_bs_m: float = 25.0, h_ut_m: float = 1.5, h_e_m: float = 1.0,
    variant: str = "primary",
) -> float:
    """UMa NLOS 路损 [dB] = max(PL_LOS, PL'_NLOS)；variant="optional"
    用单式 32.4+20·lg fc+30·lg d3D（σSF=7.8，表 Optional 行）。"""
    if variant not in ("primary", "optional"):
        raise ValueError(f"variant 只收 primary/optional，得 {variant!r}")
    hu = _domain(_num(h_ut_m, "h_ut_m"), 1.5, 22.5, "h_ut_m", "m")
    if variant == "optional":
        f_ghz = _fc_ghz(f_hz)
        d3 = _num(d3d_m, "d3d_m")
        return 32.4 + 20.0 * math.log10(f_ghz) + 30.0 * math.log10(d3)
    pl_los = uma_los_db(d2d_m, d3d_m, f_hz, h_bs_m=h_bs_m, h_ut_m=hu,
                        h_e_m=h_e_m)
    f_ghz = f_hz / 1e9
    d3 = _num(d3d_m, "d3d_m")
    pl_n = (13.54 + 39.08 * math.log10(d3) + 20.0 * math.log10(f_ghz)
            - 0.6 * (hu - 1.5))
    return max(pl_los, pl_n)


# ─── UMi-Street Canyon（Table 7.4.1-1；hE=1.0m 固定）────────────────────────

def umi_los_db(
    d2d_m: Any, d3d_m: Any, f_hz: Any,
    h_bs_m: float = 10.0, h_ut_m: float = 1.5,
) -> float:
    """UMi-Street Canyon LOS 路损 [dB]（hE=1.0m 固定，NOTE 1）。"""
    f_ghz = _fc_ghz(f_hz)
    d2 = _num(d2d_m, "d2d_m")
    d3 = _num(d3d_m, "d3d_m")
    _domain(d2, 10.0, 5000.0, "d2d_m", "m")
    hb = _num(h_bs_m, "h_bs_m")
    hu = _domain(_num(h_ut_m, "h_ut_m"), 1.5, 22.5, "h_ut_m", "m")
    dbp = _uma_umi_breakpoint_m(hb, hu, f_hz, 1.0)
    if d2 <= dbp:
        return 32.4 + 21.0 * math.log10(d3) + 20.0 * math.log10(f_ghz)
    return (32.4 + 40.0 * math.log10(d3) + 20.0 * math.log10(f_ghz)
            - 9.5 * math.log10(dbp * dbp + (hb - hu) ** 2))


def umi_nlos_db(
    d2d_m: Any, d3d_m: Any, f_hz: Any,
    h_bs_m: float = 10.0, h_ut_m: float = 1.5,
    variant: str = "primary",
) -> float:
    """UMi NLOS 路损 [dB] = max(PL_LOS, PL')；optional 单式档。"""
    if variant not in ("primary", "optional"):
        raise ValueError(f"variant 只收 primary/optional，得 {variant!r}")
    hu = _domain(_num(h_ut_m, "h_ut_m"), 1.5, 22.5, "h_ut_m", "m")
    if variant == "optional":
        f_ghz = _fc_ghz(f_hz)
        d3 = _num(d3d_m, "d3d_m")
        return 32.4 + 20.0 * math.log10(f_ghz) + 31.9 * math.log10(d3)
    pl_los = umi_los_db(d2d_m, d3d_m, f_hz, h_bs_m=h_bs_m, h_ut_m=hu)
    d3 = _num(d3d_m, "d3d_m")
    pl_n = (35.3 * math.log10(d3) + 22.4 + 21.3 * math.log10(f_hz / 1e9)
            - 0.3 * (hu - 1.5))
    return max(pl_los, pl_n)


# ─── RMa（Rural Macro，Table 7.4.1-1 + NOTE 2/5）────────────────────────────

def _rma_pl1(d3_m: float, f_ghz: float, h: float) -> float:
    return (20.0 * math.log10(40.0 * math.pi * d3_m * f_ghz / 3.0)
            + min(0.03 * h ** 1.72, 10.0) * math.log10(d3_m)
            - min(0.044 * h ** 1.72, 14.77)
            + 0.002 * math.log10(h) * d3_m)


def rma_los_db(
    d2d_m: Any, d3d_m: Any, f_hz: Any,
    h_bs_m: float = 35.0, h_ut_m: float = 1.5,
    avg_building_height_m: float = 5.0,
) -> float:
    """RMa LOS 路损 [dB]（PL1/PL2，NOTE 5 断点 2π·hBS·hUT·fc/c）。"""
    f_ghz = _domain(_num(f_hz, "f_hz") / 1e9, _F_MIN_GHZ, _F_MAX_RMA_GHZ,
                    "f_ghz", "GHz")
    d2 = _num(d2d_m, "d2d_m")
    d3 = _num(d3d_m, "d3d_m")
    _domain(d2, 10.0, 10000.0, "d2d_m", "m")
    hb = _domain(_num(h_bs_m, "h_bs_m"), 10.0, 150.0, "h_bs_m", "m")
    hu = _domain(_num(h_ut_m, "h_ut_m"), 1.0, 10.0, "h_ut_m", "m")
    h = _domain(_num(avg_building_height_m, "avg_building_height_m"),
                5.0, 50.0, "avg_building_height_m", "m")
    dbp = 2.0 * math.pi * hb * hu * f_hz / C0_M_S
    if d2 < dbp:
        return _rma_pl1(d3, f_ghz, h)
    return _rma_pl1(dbp, f_ghz, h) + 40.0 * math.log10(d3 / dbp)


def rma_nlos_db(
    d2d_m: Any, d3d_m: Any, f_hz: Any,
    h_bs_m: float = 35.0, h_ut_m: float = 1.5,
    avg_building_height_m: float = 5.0, avg_street_width_m: float = 20.0,
) -> float:
    """RMa NLOS 路损 [dB] = max(PL_RMa-LOS, PL')（W=街宽、h=楼高）。"""
    pl_los = rma_los_db(d2d_m, d3d_m, f_hz, h_bs_m=h_bs_m, h_ut_m=h_ut_m,
                        avg_building_height_m=avg_building_height_m)
    f_ghz = _num(f_hz, "f_hz") / 1e9
    d3 = _num(d3d_m, "d3d_m")
    hb = _num(h_bs_m, "h_bs_m")
    hu = _num(h_ut_m, "h_ut_m")
    h = _num(avg_building_height_m, "avg_building_height_m")
    w = _num(avg_street_width_m, "avg_street_width_m")
    pl_n = (161.04 - 7.1 * math.log10(w) + 7.5 * math.log10(h)
            - (24.37 - 3.7 * (h / hb) ** 2) * math.log10(hb)
            + (43.42 - 3.1 * math.log10(hb)) * (math.log10(d3) - 3.0)
            + 20.0 * math.log10(f_ghz)
            - (3.2 * math.log10(11.75 * hu) ** 2 - 4.97))
    return max(pl_los, pl_n)


# ─── InH-Office（Table 7.4.1-1）─────────────────────────────────────────────

def inh_office_los_db(d3d_m: Any, f_hz: Any) -> float:
    """InH-Office LOS 路损 [dB]：32.4+17.3·lg d3D+20·lg fc（1..150m）。"""
    f_ghz = _fc_ghz(f_hz)
    d3 = _domain(_num(d3d_m, "d3d_m"), 1.0, 150.0, "d3d_m", "m")
    return 32.4 + 17.3 * math.log10(d3) + 20.0 * math.log10(f_ghz)


def inh_office_nlos_db(d3d_m: Any, f_hz: Any,
                       variant: str = "primary") -> float:
    """InH-Office NLOS [dB] = max(PL_LOS, 17.30+38.3·lg d3D+24.9·lg fc)；
    optional：32.4+20·lg fc+31.9·lg d3D（σSF=8.29）。"""
    if variant not in ("primary", "optional"):
        raise ValueError(f"variant 只收 primary/optional，得 {variant!r}")
    f_ghz = _fc_ghz(f_hz)
    d3 = _domain(_num(d3d_m, "d3d_m"), 1.0, 150.0, "d3d_m", "m")
    if variant == "optional":
        return 32.4 + 20.0 * math.log10(f_ghz) + 31.9 * math.log10(d3)
    pl_los = inh_office_los_db(d3, f_hz)
    pl_n = 17.30 + 38.3 * math.log10(d3) + 24.9 * math.log10(f_ghz)
    return max(pl_los, pl_n)


# ─── O2I（§7.4.3；Table 7.4.3-1/2/3 + §7.4.3.2）─────────────────────────────

#: 材料穿透损耗闭式（f GHz）：L = a + b·f（Table 7.4.3-1；IRR 为
#: Rel-19 更新值，V19.2/V21 双版本一致）
MATERIAL_LOSS = {
    "glass": (2.0, 0.2),
    "irr_glass": (25.4, 0.11),
    "concrete": (5.0, 4.0),
    "plywood": (1.03, 0.17),
    "wood": (4.85, 0.12),
}

#: O2I 建筑穿透模型（Table 7.4.3-2）：材料配比与 σP
O2I_MODELS = {
    "low": {"mix": {"glass": 0.3, "concrete": 0.7}, "sigma_p_db": 4.4},
    "high": {"mix": {"irr_glass": 0.7, "concrete": 0.3}, "sigma_p_db": 6.5},
    "low_a": {"mix": {"glass": 0.3, "plywood": 0.7}, "sigma_p_db": 4.4},
}


def material_penetration_db(material: str, f_ghz: Any) -> float:
    """单材料穿透损耗 [dB] = a + b·f（Table 7.4.3-1，f in GHz）。"""
    if material not in MATERIAL_LOSS:
        raise ValueError(f"material 只收 {sorted(MATERIAL_LOSS)}，得 {material!r}")
    f = _num(f_ghz, "f_ghz")
    if f < 0.0:
        raise ValueError("f_ghz 须非负")
    a, b = MATERIAL_LOSS[material]
    return a + b * f


def external_wall_loss_db(
    mix: dict[str, float], f_ghz: Any, pl_npi_db: float = 5.0,
) -> float:
    """外穿透墙损通用式（7.4-3）：PLtw = PLnpi − 10·lg(Σ pᵢ·10^(−Lᵢ/10))。

    mix：{材料: 占比}（占比和须=1）；PLnpi 非垂直入射附加损（缺省
    5 dB，Table 7.4.3-2 各模型即本式在 PLnpi=5 的特例）。
    """
    f = _num(f_ghz, "f_ghz")
    if not mix:
        raise ValueError("mix 不得为空")
    total_p = sum(_num(p, "proportion") for p in mix.values())
    if abs(total_p - 1.0) > 1e-9:
        raise ValueError(f"材料占比和须=1，得 {total_p}")
    acc = 0.0
    for mat, p in mix.items():
        loss = material_penetration_db(mat, f)
        acc += p * 10.0 ** (-loss / 10.0)
    return pl_npi_db - 10.0 * math.log10(max(acc, 1e-300))


def o2i_building_db(
    pl_basic_db: Any, d2d_in_m: Any, f_hz: Any, model: str = "low",
) -> dict[str, float]:
    """O2I 建筑穿透总路损（7.4-2 均值口径）。

    返回 {pl_total_db, pl_tw_db, pl_in_db, sigma_p_db}；随机项
    N(0,σP²) 与 d2D-in 的抽样不在确定性内核（σP 如实透出）。
    适用域注记：low/high 用于 UMa/UMi（SMa 三档皆可），RMa 仅 low。
    """
    if model not in O2I_MODELS:
        raise ValueError(f"model 只收 {sorted(O2I_MODELS)}，得 {model!r}")
    plb = _num(pl_basic_db, "pl_basic_db")
    din = _domain(_num(d2d_in_m, "d2d_in_m"), 0.0, 25.0, "d2d_in_m", "m")
    f_ghz = _num(f_hz, "f_hz") / 1e9
    spec = O2I_MODELS[model]
    pl_tw = external_wall_loss_db(spec["mix"], f_ghz, pl_npi_db=5.0)
    pl_in = 0.5 * din
    return {
        "pl_total_db": plb + pl_tw + pl_in,
        "pl_tw_db": pl_tw,
        "pl_in_db": pl_in,
        "sigma_p_db": float(spec["sigma_p_db"]),
    }


def o2i_legacy_db(pl_basic_db: Any, d2d_in_m: Any) -> dict[str, float]:
    """<6 GHz 单频兼容 O2I（Table 7.4.3-3）：PLtw=20dB、σP=0、σSF→7。"""
    plb = _num(pl_basic_db, "pl_basic_db")
    din = _domain(_num(d2d_in_m, "d2d_in_m"), 0.0, 25.0, "d2d_in_m", "m")
    pl_tw, pl_in = 20.0, 0.5 * din
    return {"pl_total_db": plb + pl_tw + pl_in, "pl_tw_db": pl_tw,
            "pl_in_db": pl_in, "sigma_p_db": 0.0}


def o2i_car_db(pl_basic_db: Any, metallized_windows: bool = False,
) -> dict[str, float]:
    """O2I 车穿透（§7.4.3.2）：+μ（9；金属化车窗 20）dB，σP=5 dB。"""
    plb = _num(pl_basic_db, "pl_basic_db")
    mu = 20.0 if metallized_windows else 9.0
    return {"pl_total_db": plb + mu, "car_penetration_db": mu,
            "sigma_p_db": 5.0}


# ─── TDL 谱（Table 7.7.2-1..5；delay 归一 DS=1，power dB）───────────────────

#: 表值逐位转录（主源 V21.0.0 docx 文本；第二源 Sionna models/v19_2
#: TDL-*.json 逐位互证 2026-10-03）。TDL-D/E 首 tap 为 LOS+Rayleigh
#: 对（同 delay 两行）；k_factor_db 为表 NOTE 声明值（自算自洽见
#: tdl_k_factor_db）。
TDL_PROFILES: dict[str, dict[str, Any]] = {
    "TDL-A": {
        "delays_norm": [0.0000, 0.3819, 0.4025, 0.5868, 0.4610, 0.5375,
                        0.6708, 0.5750, 0.7618, 1.5375, 1.8978, 2.2242,
                        2.1718, 2.4942, 2.5119, 3.0582, 4.0810, 4.4579,
                        4.5695, 4.7966, 5.0066, 5.3043, 9.6586],
        "powers_db": [-13.4, 0.0, -2.2, -4.0, -6.0, -8.2, -9.9, -10.5,
                      -7.5, -15.9, -6.6, -16.7, -12.4, -15.2, -10.8,
                      -11.3, -12.7, -16.2, -18.3, -18.9, -16.6, -19.9,
                      -29.7],
        "los": False, "k_factor_db": None,
    },
    "TDL-B": {
        "delays_norm": [0.0000, 0.1072, 0.2155, 0.2095, 0.2870, 0.2986,
                        0.3752, 0.5055, 0.3681, 0.3697, 0.5700, 0.5283,
                        1.1021, 1.2756, 1.5474, 1.7842, 2.0169, 2.8294,
                        3.0219, 3.6187, 4.1067, 4.2790, 4.7834],
        "powers_db": [0.0, -2.2, -4.0, -3.2, -9.8, -1.2, -3.4, -5.2,
                      -7.6, -3.0, -8.9, -9.0, -4.8, -5.7, -7.5, -1.9,
                      -7.6, -12.2, -9.8, -11.4, -14.9, -9.2, -11.3],
        "los": False, "k_factor_db": None,
    },
    "TDL-C": {
        "delays_norm": [0.0, 0.2099, 0.2219, 0.2329, 0.2176, 0.6366,
                        0.6448, 0.6560, 0.6584, 0.7935, 0.8213, 0.9336,
                        1.2285, 1.3083, 2.1704, 2.7105, 4.2589, 4.6003,
                        5.4902, 5.6077, 6.3065, 6.6374, 7.0427, 8.6523],
        "powers_db": [-4.4, -1.2, -3.5, -5.2, -2.5, 0.0, -2.2, -3.9,
                      -7.4, -7.1, -10.7, -11.1, -5.1, -6.8, -8.7, -13.2,
                      -13.9, -13.9, -15.8, -17.1, -16.0, -15.7, -21.6,
                      -22.8],
        "los": False, "k_factor_db": None,
    },
    "TDL-D": {
        "delays_norm": [0.0, 0.0, 0.035, 0.612, 1.363, 1.405, 1.804,
                        2.596, 1.775, 4.042, 7.937, 9.424, 9.708,
                        12.525],
        "powers_db": [-0.2, -13.5, -18.8, -21.0, -22.8, -17.9, -20.1,
                      -21.9, -22.9, -27.8, -23.6, -24.8, -30.0, -27.7],
        "los": True, "k_factor_db": 13.3,
    },
    "TDL-E": {
        "delays_norm": [0.0, 0.0, 0.5133, 0.5440, 0.5630, 0.5440, 0.7112,
                        1.9092, 1.9293, 1.9589, 2.6426, 3.7136, 5.4524,
                        12.0034, 20.6519],
        "powers_db": [-0.03, -22.03, -15.8, -18.1, -19.8, -22.9, -22.4,
                      -18.6, -20.8, -22.6, -22.3, -25.6, -20.2, -29.8,
                      -29.2],
        "los": True, "k_factor_db": 22.0,
    },
}

CDL_NAMES = ("CDL-A", "CDL-B", "CDL-C", "CDL-D", "CDL-E")


def tdl_profile(name: str) -> dict[str, Any]:
    """TDL 谱表拷贝（deep copy，防调用方改表）。"""
    if name not in TDL_PROFILES:
        raise ValueError(f"name 只收 {sorted(TDL_PROFILES)}，得 {name!r}")
    return copy.deepcopy(TDL_PROFILES[name])


def cdl_profile(name: str) -> dict[str, Any]:
    """CDL 接口（任务书 AP-8 明示"CDL 留接口"）——表值数字化不在
    本件范围，显式 NotImplementedError（不冒充实现）。"""
    if name not in CDL_NAMES:
        raise ValueError(f"name 只收 {CDL_NAMES}，得 {name!r}")
    raise NotImplementedError(
        "CDL 表值数字化非本件范围（AP-8 任务书：CDL 留接口）；"
        "TDL 面已实现 tdl_profile/tdl_scale_delays/tdl_rescale_k_factor")


def tdl_delay_spread_ns(profile: dict[str, Any]) -> float:
    """谱表归一化 RMS 时延扩展 [ns]（§7.7.3 DS 定义，线性功率权重）。"""
    delays = profile.get("delays_norm")
    powers_db = profile.get("powers_db")
    if delays is None or powers_db is None or len(delays) != len(powers_db):
        raise ValueError("profile 须含等长 delays_norm/powers_db")
    p_lin = [10.0 ** (p / 10.0) for p in powers_db]
    p_tot = sum(p_lin)
    if p_tot <= 0.0:
        raise ValueError("功率表全非正")
    m1 = sum(p * t for p, t in zip(p_lin, delays, strict=True)) / p_tot
    m2 = sum(p * t * t for p, t in zip(p_lin, delays, strict=True)) / p_tot
    return math.sqrt(max(m2 - m1 * m1, 0.0))


def tdl_k_factor_db(profile: dict[str, Any]) -> float | None:
    """由谱表自算首 tap K 因子 [dB]（表 NOTE 口径：K₁ = P_LOS /
    P_同延迟 Rayleigh 分量，线性功率比）。

    非 LOS 谱返回 None。自算与表 NOTE 声明自洽：TDL-D → 13.3 dB、
    TDL-E → 22.0 dB（测试钉；该口径下首 tap 平均功率 = LOS+Rayleigh
    和 ≈ 0 dB 亦为表 NOTE 声明，双锚）。
    注：这与"总 LOS / 全部 Rayleigh tap 和"口径（TDL-D ≈ 8.98 dB）
    不同——表 NOTE 的 K₁ 是首 tap Ricean 分布的 K，不是全谱 K；
    §7.7.6 重标定对两种口径一致有效（所有 Rayleigh tap 同比缩放）。
    """
    if not profile.get("los"):
        return None
    powers_db = profile["powers_db"]
    p_los = 10.0 ** (powers_db[0] / 10.0)
    p_ray1 = 10.0 ** (powers_db[1] / 10.0)
    return 10.0 * math.log10(p_los / p_ray1)


def tdl_scale_delays(profile: dict[str, Any], ds_wanted_ns: Any) -> dict[str, Any]:
    """§7.7-1 时延缩放：τₙ = τₙ,norm·DS_wanted（归一 DS=1 口径）。

    返回缩放后谱表拷贝（delays_norm 字段语义随缩放变为 [ns] 绝对
    时延，如实以 delays_ns 键另存，原 delays_norm 保留）。
    """
    ds = _num(ds_wanted_ns, "ds_wanted_ns")
    if ds <= 0.0:
        raise ValueError("ds_wanted_ns 须为正")
    out = copy.deepcopy(profile)
    out["delays_ns"] = [t * ds for t in profile["delays_norm"]]
    out["ds_wanted_ns"] = ds
    return out


def tdl_rescale_k_factor(profile: dict[str, Any], k_target_db: Any,
) -> dict[str, Any]:
    """§7.7.6 K 因子改写（LOS 谱专用）：Rayleigh tap 功率同乘
    K_model/K_target（线性），LOS tap 功率不变。

    唯一性：保持 LOS 功率并使 P_LOS/ΣP'_NLOS = K_target 的 NLOS 侧
    等比缩放恰为该式（代数上唯一）。(7.7.6-1) 字面方程为 docx 内
    Equation.3 OLE 对象不可文本提取，字面转录 UNVERIFIED 如实；
    实现以 K 自算往返自洽钉（测试）。
    """
    if not profile.get("los"):
        raise ValueError("K 因子改写仅适用于 LOS 谱（TDL-D/E）")
    kt = _num(k_target_db, "k_target_db")
    if kt <= 0.0:
        raise ValueError("k_target_db 须为正")
    k_model = 10.0 ** ((tdl_k_factor_db(profile) or 0.0) / 10.0)
    k_tgt = 10.0 ** (kt / 10.0)
    scale = k_model / k_tgt
    out = copy.deepcopy(profile)
    out["powers_db"] = [profile["powers_db"][0]] + [
        p + 10.0 * math.log10(scale) for p in profile["powers_db"][1:]]
    out["k_factor_db"] = kt
    return out
