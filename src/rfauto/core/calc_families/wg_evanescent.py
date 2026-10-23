"""矩形波导 TE10 截止下倏逝传播解 CALC 键（aurora_j W4-S12，2026-10-23）。

一键：wg_evanescent_attenuation（截止频率以下 TE10 倏逝模衰减常数精确式
+ 倏逝波阻抗 ηc——A2 席位键；候选定稿 runs/aurora_j/w4_candidates.md §1.3）。

#222 triple-grep 证据（2026-10-23 本席开工实测）
--------------------------------------------------------
``evanescent|倏逝`` calc_families 面唯一实中=coax_line_cutoff_attenuator
（同轴线 TE11 **高阶模**截止式衰减器——器件面：截止衰减器滑动段口径，
深截止注记 α→k_c；矩形波导 TE10 主模的倏逝传播解+倏逝波阻抗无注册键，
截止侧全仓空白——候选表 §1.1/§1.3 同结论）。
``wg_evanescent`` src/tests/scripts 三面零命中。

物理口径（#1c/#300 出处纪律；docstring 写死）
--------------------------------------------------------
- TE10 主模截止频率 fc=c/(2a√(εrμr))（与 waveguide_lambda_g/wg_fundamental
  同式，本键独立实现零 import 复用——几何守卫 b≤a 同 _guide_dims 口径）。
- 截止以下传播常数 γ=√(kc²−k²) 为实：α=k·√((fc/f)²−1) Np/m，k=ω√με
  （Pozar《Microwave Engineering》§3.x 矩形波导一般理论：截止下 β→−jα
  场沿 z 指数衰减无净功率流）。深截止极限 f≪fc → α→kc=π/a（只由几何决
  定，与 coax_line_cutoff_attenuator 的深截止注记同物理）。
- 倏逝波阻抗（TE 口径，e^{jωt−γz} 约定）：ηc=jωμ/γ=jη0√(μr/εr)/
  √((fc/f)²−1)——纯虚感抗（倏逝模储能不耗能的电路指纹）；TM 倏逝口径
  为容抗 −jη0√(μr/εr)·√((fc/f)²−1)，本键只出 TE10 面（主模语义）。
- f≥fc 显式拒绝（行波区无倏逝语义——镜像惯例：wg_fundamental/wg_iris
  的 f≤fc 拒绝与 coax_line_cutoff_attenuator 的 f≥fc 拒绝，本键跟随
  后者口径；传播态衰减/功率用 wg_te10_attenuation/wg_te10_power_capacity）。

数值锚（#118 独立路线，tests/unit/test_w4s12_wg_conductor_keys.py）：
WR-90 a=22.86mm fc=6.5571GHz 教科书锚；α 两式恒等（√(kc²−k²) 与
k√((fc/f)²−1) 独立代数路径 rel≤1e-12）；深截止 α→kc 极限；f→fc⁻ α→0
连续性；ηc 纯虚守卫。测试侧另做 α·λg 传播/倏逝分段恒等旁证
（f>fc 时 β=k√(1−(fc/f)²) 与 f<fc 时 α=k√((fc/f)²−1) 同一 γ 的两支）。

守卫：a_mm/b_mm>0 且 b_mm≤a_mm（给出 b 时校验标准口径，TE10 量与 b 无
关同 waveguide_lambda_g 可选语义）；f_ghz>0 且 <fc；epsilon_r≥1、mu_r>0；
bool 入参显式拒收（df7+⑯）。

接口：纯函数零 IO；math 为主；全部返回 JSON 可序列化结构（复数按服务
[re,im] 约定出双字段+η 模）；无 ``__all__``（公开 API 快照口径）。

出处：
- wg_evanescent_attenuation：矩形波导一般理论截止下传播常数与波阻抗
  （Pozar Microwave Engineering §3 矩形波导 TE/TM 模一般理论——式级
  转引 Rizzi/Eaton 同族教科书通行形态，章节级落键面不落页码）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator

_MU0 = 1.25663706212e-6
_EPS0 = 8.8541878128e-12


def _num(value: Any, name: str) -> float:
    """有限数守卫（bool 显式拒收——float(True)=1.0 静默污染，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


@register_calculator(
    "wg_evanescent_attenuation",
    "矩形波导 TE10 截止下倏逝传播解：fc=c/2a√(εrμr)、α=k√((fc/f)²−1) "
    "Np/m（深截止 f≪fc → α→π/a 只由几何决定）+倏逝波阻抗 ηc=jη0√(μr/εr)"
    "/√((fc/f)²−1)（纯虚感抗，e^{jωt} 口径）+dB/m 换算；f≥fc 行波区显式"
    "拒绝（传播态用 wg_te10_attenuation）；同轴线 TE11 截止衰减器="
    "coax_line_cutoff_attenuator 器件面不撞",
    (("a_mm", "float mm 波导宽边（TE10 截止=c/2a√(εrμr)；>0）"),
     ("f_ghz", "float GHz 工作频率（须<fc，截止以下倏逝态；≥fc 显式拒绝）"),
     ("b_mm", "float mm 波导窄边（>0 且 ≤a_mm，可选——TE10 倏逝量与 b 无"
      "关，给出即校验标准口径）"),
     ("epsilon_r", "float 填充相对介电常数（≥1，缺省 1）"),
     ("mu_r", "float 填充相对磁导率（>0，缺省 1）")),
    required=("a_mm", "f_ghz"),
)
def wg_evanescent_attenuation(a_mm: float, f_ghz: float,
                              b_mm: float | None = None,
                              epsilon_r: float = 1.0,
                              mu_r: float = 1.0) -> dict[str, Any]:
    """矩形波导 TE10 截止下倏逝衰减常数与倏逝波阻抗（独立实现零复用）。"""
    tag = "wg_evanescent_attenuation"
    a = _num(a_mm, f"{tag}.a_mm")
    if a <= 0.0:
        raise ValueError(f"{tag}: a_mm 必须 >0，得到 {a_mm!r}")
    b: float | None = None
    if b_mm is not None:
        b_chk = _num(b_mm, f"{tag}.b_mm")
        if b_chk <= 0.0:
            raise ValueError(f"{tag}: b_mm 必须 >0，得到 {b_mm!r}")
        if b_chk > a:
            raise ValueError(
                f"{tag}: b_mm 必须 ≤a_mm（标准矩形波导口径），得到 "
                f"a={a!r}, b={b_chk!r}")
        b = b_chk
    eps_r = _num(epsilon_r, f"{tag}.epsilon_r")
    if eps_r < 1.0:
        raise ValueError(f"{tag}: epsilon_r 必须 ≥1，得到 {epsilon_r!r}")
    mur = _num(mu_r, f"{tag}.mu_r")
    if mur <= 0.0:
        raise ValueError(f"{tag}: mu_r 必须 >0，得到 {mu_r!r}")
    f = _num(f_ghz, f"{tag}.f_ghz")
    if f <= 0.0:
        raise ValueError(f"{tag}: f_ghz 必须 >0，得到 {f_ghz!r}")

    fc_ghz = C_MM_GHZ / (2.0 * a * math.sqrt(eps_r * mur))
    if f >= fc_ghz:
        raise ValueError(
            f"{tag}: f_ghz={f!r} ≥截止频率 fc={fc_ghz:.9g} GHz——行波区无"
            "倏逝语义（传播态衰减/功率用 wg_te10_attenuation/"
            "wg_te10_power_capacity），本键显式拒绝")

    # 全 SI 组装（长度/波数一律 m，频率出口按 mm·GHz 常数换算）
    a_m = a * 1e-3
    # k=ω√με：ω=2πf·1e9，√με=√(εrμr)/c0 → k=2πf·1e9·√(εrμr)/299792458
    k_rad_m = (2.0 * math.pi * f * 1e9 * math.sqrt(eps_r * mur)
               / 299792458.0)
    kc_rad_m = math.pi / a_m
    f_over_fc = f / fc_ghz
    alpha_np_m = k_rad_m * math.sqrt((1.0 / f_over_fc) ** 2 - 1.0)
    alpha_db_m = alpha_np_m * 20.0 / math.log(10.0)
    # 深截止极限（f≪fc → α→kc；f=fc/10 时已 <0.5% 偏差，注记不判）
    deep_kc_dev = abs(alpha_np_m / kc_rad_m - 1.0)

    eta0_ohm = math.sqrt(_MU0 / _EPS0)
    eta_fill = eta0_ohm * math.sqrt(mur / eps_r)
    ev_sqrt = math.sqrt((1.0 / f_over_fc) ** 2 - 1.0)
    eta_ev_im = eta_fill / ev_sqrt  # j 系数：ηc=+j·ηc_im（TE 倏逝感抗）

    # 独立代数路径：f 极近 fc 时 kc²−k² 可能因独立舍入落微负，
    # max 钳 0（数学上 f<fc 恒正，钳制只消浮点路径噪声，零语义变化）
    gamma_rad_m = math.sqrt(max(kc_rad_m ** 2 - k_rad_m ** 2, 0.0))
    alpha_cross = abs(alpha_np_m - gamma_rad_m) / max(gamma_rad_m, 1e-300)

    return {
        "a_mm": a,
        "b_mm": b,
        "f_ghz": f,
        "epsilon_r": eps_r,
        "mu_r": mur,
        "fc_ghz": round(fc_ghz, 12),
        "f_over_fc": round(f_over_fc, 15),
        "k_rad_per_m": round(k_rad_m, 12),
        "kc_rad_per_m": round(kc_rad_m, 12),
        "alpha_np_m": round(alpha_np_m, 12),
        "alpha_db_m": round(alpha_db_m, 12),
        "eta_evanescent": [0.0, round(eta_ev_im, 12)],
        "eta_evanescent_mag_ohm": round(abs(eta_ev_im), 12),
        "gamma_identity_rel_dev": round(alpha_cross, 18),
        "deep_cutoff_alpha_over_kc": round(alpha_np_m / kc_rad_m, 15),
        "deep_cutoff_dev": round(deep_kc_dev, 15),
        "note": (
            "TE10 倏逝传播解：γ=√(kc²−k²) 实（截止下无相位推进无净功率"
            "流），α=k√((fc/f)²−1) 与 √(kc²−k²) 两式恒等（gamma_identity_"
            "rel_dev≈机器精度，构造级恒等式）；深截止 f≪fc → α→kc=π/a（"
            "deep_cutoff_alpha_over_kc→1，精密衰减器工作区惯例）；ηc 为 "
            "TE 倏逝波阻抗=jη0√(μr/εr)/√((fc/f)²−1) 纯虚感抗（[re,im] "
            "服务复数约定，实部恒 0；e^{jωt−γz} 口径）；TM 倏逝口径为容"
            "抗 −jη√((fc/f)²−1) 不在输出面（主模语义）；b_mm 可选（TE10 "
            "量与 b 无关，给出即校验 b≤a）；与 coax_line_cutoff_attenua"
            "tor 的边界=同轴 TE11 高阶模截止衰减器器件面（深截止近似注记"
            "）vs 本键矩形 TE10 倏逝传播解精确式+ηc 输出面"),
        "source": (
            "矩形波导一般理论截止下传播常数与波阻抗（Pozar Microwave "
            "Engineering §3 矩形波导 TE/TM 模一般理论，章节级转引；深截"
            "止极限注记同 Collin 同族教科书通行形态）"),
    }
