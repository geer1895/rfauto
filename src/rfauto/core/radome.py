"""NX-5 天线罩（radome）多层透波 + 一阶瞄准线误差（BSE）闭式面。

规格：研究扩充 round14 §四 NX-5——"多层介质
ABCD 堆叠 + 一阶射线 BSE；对拍 IEEE Access 09474462"。全仓 0 hit
（grep 证，2026-10-03 #222 接地）。纯闭式叶子，零 IO、不进 calculators。

模块面
------
- ``dielectric_abcd``：单层介质斜入射特征矩阵（TE/TM 各自的修正导纳
  Y_te = y·cosθ_t / Y_tm = y/cosθ_t，层内相位 δ=k0·√(εr μr)·d·cosθ_t）。
- ``stack_power_rt``：多层堆叠特征矩阵级联 → 功率反射/透射（能量守恒
  无耗介质 |R|²+|T|²=1 结构锚）。
- ``normal_incidence_fresnel``：单界面 Fresnel 独立闭式（裁判路）。
- ``half_wave_slab_transmission``：半波长整数倍无耗板 T=1 恒等（结构锚）。
- ``slab_deviation_angle``：平行板零偏折 / 楔形板偏折角闭式（薄楔
  δ ≈ (n−1)·α）——BSE 的一阶几何面。
- ``spherical_shell_ray_bse``：同心球壳天线罩逐射线偏折**精确**几何闭式
  （碰撞参数缩放律，见函数 docstring）；居中孔径质心一阶矩 BSE=0
  （奇对称恒等锚，真实扫描 BSE 属姿态项不虚构）。
- ``boresight_error_note``：BSE 判据口径文档面（峰值偏移/瞄准线误差/
  透射损耗三要素；IEEE Access 09474462 口径名，页码 UNVERIFIED）。

物理口径（全 SI；时谐 e^{+jωt}，层矩阵用 e^{−jkz} 传播约定）
----------------------------------------------------------------
* 介质特征矩阵（Born-Wolf 膜系口径，修正导纳制）：
  层矩阵 M_i = [[cosδ, j·sinδ/Y_i], [j·Y_i·sinδ, cosδ]]，
  Y_i = n_i·cosθ_t（TE）| n_i/cosθ_t（TM），n_i=√(εr μr)；
  δ = (2πf/c)·n_i·d·cosθ_t。级联 M=ΠM_i 后
  输入导纳 Y = (C+D·Y_s)/(A+B·Y_s)，r=(Y_0−Y)/(Y_0+Y)、
  t=2Y_0/(Y_0(A+B·Y_s)+C+D·Y_s)。两侧自由空间 → 功率守恒 |r|²+|t|²=1。
* 设计约束：纯标准库+numpy；非法输入显式 ValueError；无基准的经验面
  （多次内反射高级修正）不做（铁律 7/#122）。

出处
----
1. round 文档：round14 §四 NX-5。
2. Born & Wolf "Principles of Optics"（膜系特征矩阵口径名）；IEEE Access
   09474462（BSE 判据口径名）。页码 UNVERIFIED 如实。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = [
    "C0_M_S",
    "RADOME_SOURCE",
    "boresight_error_note",
    "dielectric_abcd",
    "half_wave_slab_transmission",
    "normal_incidence_fresnel",
    "single_interface_rt",
    "slab_deviation_angle",
    "spherical_shell_ray_bse",
    "stack_power_rt",
]

C0_M_S = 299792458.0
RADOME_SOURCE = (
    "Born-Wolf 膜系特征矩阵（口径名）+ IEEE Access 09474462（BSE 判据"
    "口径名）；页码 UNVERIFIED（#122 如实）"
)


def _positive(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def _finite(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v):
        raise ValueError(f"{name} 必须为有限数，实际 {x!r}")
    return v


def _snell_angle(n_from: float, n_to: float, theta_in: float) -> float:
    """Snell 折射角；全反射时抛 ValueError（射线面不追踪全反射支）。"""
    s = n_from * math.sin(theta_in) / n_to
    if abs(s) > 1.0:
        raise ValueError("全反射：射线面一阶口径不适用")
    return math.asin(s)


def _nonneg(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v < 0.0:
        raise ValueError(f"{name} 必须为非负有限数，实际 {x!r}")
    return v


# ─── 多层堆叠特征矩阵 ────────────────────────────────────────────────────────
def dielectric_abcd(thickness_m: Any, er: Any, f_hz: Any,
                    theta_in_rad: Any, polarization: str,
                    mu_r: Any = 1.0) -> np.ndarray:
    """单层介质特征矩阵 M=[[cosδ, j·sinδ/Y],[j·Y·sinδ, cosδ]]（修正导纳制）。

    Y = n·cosθ_t（TE）| n/cosθ_t（TM），n=√(εr μr)；δ=k0·n·d·cosθ_t。
    厚度 0 → 恒等阵（界面跳变由级联导纳失配承担）。
    """
    d = _nonneg(thickness_m, "thickness_m")
    eps = _positive(er, "er")
    mur = _positive(mu_r, "mu_r")
    f = _positive(f_hz, "f_hz")
    theta_in = _finite(theta_in_rad, "theta_in_rad")
    if polarization not in ("te", "tm"):
        raise ValueError(f"polarization 须为 'te'|'tm'，实际 {polarization!r}")
    if abs(theta_in) >= math.pi / 2.0:
        raise ValueError("入射角须 |θ|<90°")
    n_rel = math.sqrt(eps * mur)
    theta_t = _snell_angle(1.0, n_rel, theta_in)
    y = n_rel * math.cos(theta_t) if polarization == "te" \
        else n_rel / math.cos(theta_t)
    delta = 2.0 * math.pi * f / C0_M_S * n_rel * d * math.cos(theta_t)
    cos_d = complex(math.cos(delta))
    sin_d = complex(math.sin(delta))
    return np.array([[cos_d, 1j * sin_d / y],
                     [1j * y * sin_d, cos_d]], dtype=complex)


def single_interface_rt(er_from: Any, er_to: Any, theta_in_rad: Any,
                        polarization: str) -> dict[str, complex]:
    """单界面斜入射 Fresnel 复振幅 r/t 与功率（半空间口径，独立裁判面）。

    修正导纳制：r=(Y_1−Y_2)/(Y_1+Y_2)、t=2Y_1/(Y_1+Y_2)，
    Y_i = n_i·cosθ_i（TE）| n_i/cosθ_i（TM）。全反射显式 ValueError。
    """
    e1 = _positive(er_from, "er_from")
    e2 = _positive(er_to, "er_to")
    theta = _finite(theta_in_rad, "theta_in_rad")
    if polarization not in ("te", "tm"):
        raise ValueError(f"polarization 须为 'te'|'tm'，实际 {polarization!r}")
    n1, n2 = math.sqrt(e1), math.sqrt(e2)
    if abs(theta) >= math.pi / 2.0:
        raise ValueError("入射角须 |θ|<90°")
    theta_t = _snell_angle(n1, n2, theta)
    if polarization == "te":
        y1, y2 = n1 * math.cos(theta), n2 * math.cos(theta_t)
    else:
        y1, y2 = n1 / math.cos(theta), n2 / math.cos(theta_t)
    r = (y1 - y2) / (y1 + y2)
    t = 2.0 * y1 / (y1 + y2)
    # 功率透射 = 导纳比 × |t|²（半空间两侧介质不同；无耗 y 实）
    return {"r": r, "t": t, "power_r": abs(r) ** 2,
            "power_t": (y2 / y1) * abs(t) ** 2}


def stack_power_rt(layers: Any, f_hz: Any, theta_in_rad: Any,
                   polarization: str) -> dict[str, complex]:
    """多层无耗介质堆叠 → 复 r/t 与功率 R/T（两侧自由空间）。

    layers: [(thickness_m, er, mu_r), ...]（入射顺序，不得为空）。
    修正导纳制下 Y_0=cosθ_0（TE）| 1/cosθ_0（TM）、Y_s=Y_0（同介质）。
    注意：0 厚层=恒等阵（无界面语义）；单界面裁判面用
    ``single_interface_rt``。
    """
    theta_in = _finite(theta_in_rad, "theta_in_rad")
    if abs(theta_in) >= math.pi / 2.0:
        raise ValueError("入射角须 |θ|<90°")
    if polarization not in ("te", "tm"):
        raise ValueError(f"polarization 须为 'te'|'tm'，实际 {polarization!r}")
    if not layers:
        raise ValueError("layers 不得为空")
    y0 = math.cos(theta_in) if polarization == "te" else 1.0 / math.cos(theta_in)
    m_total = np.eye(2, dtype=complex)
    for thickness, er, mur in layers:
        m_total = m_total @ dielectric_abcd(thickness, er, f_hz, theta_in,
                                            polarization, mur)
    a, b = complex(m_total[0, 0]), complex(m_total[0, 1])
    c, d = complex(m_total[1, 0]), complex(m_total[1, 1])
    ys = y0  # 两侧同一介质（自由空间）
    y_in = (c + d * ys) / (a + b * ys)
    r = (y0 - y_in) / (y0 + y_in)
    t = 2.0 * y0 / (y0 * (a + b * ys) + (c + d * ys))
    return {"r": r, "t": t, "power_r": abs(r) ** 2, "power_t": abs(t) ** 2}


def normal_incidence_fresnel(er_from: Any, er_to: Any) -> tuple[float, float]:
    """垂直入射单界面 Fresnel 功率反射/透射（独立裁判路）。

    r_amp=(√ε2−√ε1)/(√ε1+√ε2)，R=|r|²、T=1−R（无耗磁中性）。
    """
    e1 = _positive(er_from, "er_from")
    e2 = _positive(er_to, "er_to")
    n1, n2 = math.sqrt(e1), math.sqrt(e2)
    r_amp = (n2 - n1) / (n1 + n2)
    big_r = r_amp * r_amp
    return big_r, 1.0 - big_r


def half_wave_slab_transmission(er: Any, f_hz: Any) -> dict[str, float]:
    """半波长整数倍无耗单板：T=1 恒等（法向，结构锚）。

    板厚 d=λ_in/2=(c/f)·(1/√εr)/2（μr=1）。
    """
    eps = _positive(er, "er")
    f = _positive(f_hz, "f_hz")
    lam_in = C0_M_S / f / math.sqrt(eps)
    d = lam_in / 2.0
    out = stack_power_rt([(d, eps, 1.0)], f, 0.0, "te")
    return {"thickness_m": d, "power_t": out["power_t"],
            "power_r": out["power_r"]}


# ─── BSE 一阶几何面 ──────────────────────────────────────────────────────────
def slab_deviation_angle(wedge_angle_rad: Any, er: Any) -> dict[str, float]:
    """平行板/楔形板射线偏折（一阶薄楔口径）。

    平行板（wedge=0）：入射=出射方向（零偏折，对称性恒等锚）。
    薄楔（楔角 α≪1）：总偏折 δ ≈ (n−1)·α（两次 Snell 的一阶合成，
    薄棱镜工程式）。α<0 显式 ValueError。
    """
    alpha = _finite(wedge_angle_rad, "wedge_angle_rad")
    eps = _positive(er, "er")
    n = math.sqrt(eps)
    if alpha < 0.0:
        raise ValueError("楔角须非负")
    if alpha == 0.0:
        return {"deviation_rad": 0.0, "n_rel": n, "regime": "parallel_plate"}
    return {"deviation_rad": (n - 1.0) * alpha, "n_rel": n,
            "regime": "thin_wedge"}


def spherical_shell_ray_bse(outer_radius_m: Any, thickness_m: Any, er: Any,
                            f_hz: Any, impact_offsets_m: Any) -> dict[str, Any]:
    """同心球壳天线罩逐射线偏折**精确**几何闭式（无损、两次 Snell）。

    平行射线束（沿 z）以横向偏移 b 打在同心球壳外表面。球面折射的
    碰撞参数缩放律（对球心 O 的垂距）：一次折射 p → p·(n_from/n_to)——
    外表面进入（1→n）：p'=b/n；内表面出射（n→1）：p''=p'·n=b（腔内
    射线碰撞参数还原=原偏移）。逐面偏折（对法向转向量）：

      δ_entry = asin(|b|/r_out) − asin(|b|/(n·r_out))
      δ_exit  = asin(|b|/r_in)  − asin(|b|/(n·r_in))
      dev(b) = sign(b)·(δ_entry + δ_exit)（b>0 偏向轴）

    |b| ∈ [r_in, r_out) 的纯穿壳射线：两折射面同为外球面 → 缩放律
    闭合 δ_exit=0，dev = sign(b)·δ_entry。全式为精确几何光学闭式
    （同心几何无薄壁近似）；轴上 b=0 零偏折（对称性锚）；dev(−b)=−dev(b)
    奇对称 → 居中孔径质心一阶矩 BSE=0（对称性恒等，如实报告——真实
    天线罩 BSE 来自天线扫描离轴的局部几何，属姿态项，本面不虚构）。
    无损几何面与频率无关（f_hz 仅作接口占位）。无多次内反射/像差
    高级项（IEEE Access 09474462 判据口径名，页码 UNVERIFIED）。
    返回 {offsets_m, exit_angle_rad, bse_first_order_rad}。
    """
    r_out = _positive(outer_radius_m, "outer_radius_m")
    d = _positive(thickness_m, "thickness_m")
    eps = _positive(er, "er")
    _ = _positive(f_hz, "f_hz")  # 无损几何面与频率无关（docstring 声明）
    n = math.sqrt(eps)
    if d >= r_out:
        raise ValueError("thickness_m 须小于 outer_radius_m")
    r_in = r_out - d
    offsets = np.atleast_1d(np.asarray(impact_offsets_m, dtype=float))
    if np.any(np.abs(offsets) >= r_out):
        raise ValueError("横向偏移须 |b|<R_out（打到壳上）")

    def _dev(bb: float) -> float:
        ab = abs(bb)
        sgn = 1.0 if bb >= 0.0 else -1.0
        d_entry = math.asin(ab / r_out) - math.asin(ab / (n * r_out))
        # 纯穿壳（|b|>=r_in）：第二面同为外球面，缩放律闭合 δ=0
        d_exit = math.asin(ab / r_in) - math.asin(ab / (n * r_in)) \
            if ab < r_in else 0.0
        return sgn * (d_entry + d_exit)

    angles_arr = np.asarray([_dev(float(b)) for b in offsets], dtype=float)
    bse = float(np.mean(angles_arr)) if angles_arr.size else 0.0
    return {
        "offsets_m": [float(x) for x in offsets],
        "exit_angle_rad": angles_arr.tolist(),
        "bse_first_order_rad": bse,
    }


def boresight_error_note() -> dict[str, str]:
    """BSE 判据口径文档面（三要素 + 无基准声明）。"""
    return {
        "boresight_error": (
            "BSE=带罩后主瓣峰值指向的无罩方向偏角（峰值偏移口径）"
        ),
        "first_order_face": (
            "本模块 spherical_shell_ray_bse 给同心球壳逐射线精确几何偏折"
            "（居中孔径质心=0 奇对称）；扫描离轴姿态项不做"
        ),
        "related_metrics": (
            "透射损耗（TIL）与主瓣展宽为同族判据——消费 stack_power_rt"
        ),
        "source": RADOME_SOURCE,
    }
