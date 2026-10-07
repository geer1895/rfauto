r"""MM-3 GSTC 面抗综合确定性内核（规格 规格深案 §C-2；
B 流超材料，2026-10-02）。纯函数零 IO，数值全部落在本内核（铁律 7）。

法源（规格 §C-2 逐式核到 arXiv:1408.0273v2 = IEEE TAP 63(7) 2015）：
法向入射单轴 Huygens 面闭式（χ_ee/χ_mm=面电/磁极化率，单位米；k=真空波数
rad/m，两式共用分母 D=(2+jkχ_ee)(2+jkχ_mm)）：

    Eq.(17)  T_x = (4 + k²χ_ee·χ_mm) / D
    Eq.(18)  R_x = 2jk(χ_mm − χ_ee) / D
    Eq.(19)  χ_ee = 2j(T + R − 1) / [k(T + R + 1)]
             χ_mm = 2j(T − R − 1) / [k(T − R + 1)]

口径与守卫（预声明）
====================
- **无耗 ⇔ χ 实数（本式口径）**：实 χ 时 |T|²+|R|²=1 为代数恒等——
  记 a=kχ_ee、b=kχ_mm（实），(4+ab)²+4(b−a)² ≡ (4−ab)²+4(a+b)²（展开
  逐项相消），即分子分母模方恒等。锚树按此钉逐位。
- **有耗/增益**：Im χ<0 =有耗吸收（经典锚：χ_ee=−j/k、χ_mm=0 的电阻膜
  ↔ 归一化并联导纳 y=jkχ_ee=1 → T=2/3、R=−1/3 精确）；**Im χ>0 =增益
  （非物理）**→ gstc_forward 无源守卫 |R|²+|T|²≤1+1e-9 违即 ValueError
  （规格 §C-2 守卫原文）。
- **往返恒等**：Eq.(19)→Eq.(17)/(18) 代数精确（把 Eq.(19) 回代展开、
  利用 (kχ_mm−2j)=−j(2+jkχ_mm) 类恒等式逐项相消）——gstc_synthesize
  内置自检 max(|ΔT|,|ΔR|)≤1e-12，违即 RuntimeError（实现缺陷，禁止
  消费本结果，#118 家法：换算必须合成回收自钉）。
- **χ_em/χ_me 显式不做**：交叉（磁电）耦合闭式原文未给（MM-5 同裁）——
  参数位保留（chi_em/chi_me），传非 None 即 ValueError；交叉/圆极化
  polarization 同拒。
- **极化**：法向入射 x/y 共极化简并（单轴面 χ_ee 对 x/y 共用，结果同
  一致返回）；'x'/'y' 均收。
- **奇点**：Eq.(19) 分母 |T±R+1|→0 即 χ→∞ 极点域（如 T=−1 全反 Huygens
  极限、T=R=−1 域）→ 显式 ValueError；χ=±2j/k 集体谐振（D=0）在正向
  表现为复除零（ZeroDivisionError，service 层翻译 ok=False）。
- **对拍通道（gstc_crosscheck）**：频带 (Γ,T) → Eq.(19) χ 反演 →
  正演回带内 Δ|T|_dB 门（0.5dB 起步，规格 §C-2 原文）。诚实边界：离线
  通道正反两腿同源闭式 → Δ|T|≈1e-13 dB（门判的是接口/管线破坏：
  NaN/长度/奇点/精度）；判别力在 J4 Floquet 锚真机侧替换正演腿后到位
  （真机面本批不做，接口留位）。

设计约束：core 层（numpy/math，零求解器零新依赖）；非法输入显式
ValueError 不静默兜底；shell（calc_families）负责 JSON 化（complex→[re,im]），
本模块直接返回 complex（core 直调消费者口径）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core.metasurface_lut import C0_M_S

__all__ = [
    "gstc_crosscheck",
    "gstc_forward",
    "gstc_synthesize",
    "t_r_from_db_phase",
]

#: 规格 §C-2 守卫原文：|R|²+|T|² ≤ 1+1e-9
_ENERGY_TOL = 1e-9
#: 规格 §C-2 往返自检：Eq.(19)↔Eq.(17) 逐位 ≤1e-12
_ROUNDTRIP_TOL = 1e-12
#: Eq.(19) 分母奇点阈（|T±R+1| 低于此判 χ→∞ 极点域，反演病态显式拒绝）
_SINGULAR_TOL = 1e-9
#: 规格 §C-2 对拍门起步值：带内 Δ|T| ≤ 0.5 dB
DT_GATE_DB_DEFAULT = 0.5

_POL_CO = ("x", "y")

_CHI_EM_MSG = (
    "χ_em/χ_me 交叉（磁电）耦合闭式原文未给（arXiv 1408.0273v2 只给 "
    "χ_ee/χ_mm 对角闭式，规格 §C-2 显式不做、MM-5 同裁）——参数位保留，"
    "传非 None 即拒绝")


def _as_complex(value: Any, name: str) -> complex:
    """标量实数或 [re, im] 对 → complex（service JSON 复数约定，mimo 同款）。"""
    if isinstance(value, complex):
        if not (math.isfinite(value.real) and math.isfinite(value.imag)):
            raise ValueError(f"{name} 含非有限值（NaN/Inf）")
        return value
    if isinstance(value, bool):
        raise ValueError(f"{name} 须为实数或 [re, im] 对，收到 bool")
    if isinstance(value, (int, float)):
        v = float(value)
        if not math.isfinite(v):
            raise ValueError(f"{name} 含非有限值（NaN/Inf）")
        return complex(v, 0.0)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            re, im = float(value[0]), float(value[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 须为实数或 [re, im] 对，收到 {value!r}") from exc
        if not (math.isfinite(re) and math.isfinite(im)):
            raise ValueError(f"{name} 含非有限值（NaN/Inf）")
        return complex(re, im)
    raise ValueError(f"{name} 须为实数或 [re, im] 对，收到 {value!r}")


def _as_k(value: Any) -> float:
    """波数入参收敛：正有限 float（rad/m）。"""
    if isinstance(value, bool):
        raise ValueError("k_rad_m 须为正有限实数")
    try:
        k = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"k_rad_m 须为正有限实数，收到 {value!r}") from exc
    if not math.isfinite(k) or k <= 0.0:
        raise ValueError(f"k_rad_m 须为正有限实数，收到 {value!r}")
    return k


def _amp_db(x: complex) -> float | None:
    """幅度 dB；|x|=0 无有限 dB（JSON 安全，返回 None 由消费者裁决）。"""
    m = abs(x)
    return None if m == 0.0 else 20.0 * math.log10(m)


def _phase_deg(x: complex) -> float | None:
    """相位（度，atan2 主值）；x=0 相位无定义（返回 None）。"""
    return None if x == 0 else math.degrees(math.atan2(x.imag, x.real))


# ─── 正向闭式（Eq.17/18）──────────────────────────────────────────────────────


def _forward_core(chi_ee: complex, chi_mm: complex,
                  k_rad_m: float) -> tuple[complex, complex]:
    """Eq.(17)/(18) 裸闭式（无守卫）——gstc_forward 与 synthesize 往返自检共用。

    χ=±2j/k 集体谐振时 D=0 → 复除零 ZeroDivisionError（显式，不静默）。
    """
    den = (2.0 + 1j * k_rad_m * chi_ee) * (2.0 + 1j * k_rad_m * chi_mm)
    t = (4.0 + (k_rad_m * chi_ee) * (k_rad_m * chi_mm)) / den
    r = 2j * k_rad_m * (chi_mm - chi_ee) / den
    return t, r


def gstc_forward(chi_ee: Any, chi_mm: Any, k_rad_m: Any,
                 polarization: str = "x", *,
                 chi_em: Any = None, chi_me: Any = None) -> dict[str, Any]:
    """Eq.(17)/(18) 正向：χ_ee/χ_mm → (T, R)，带无源守卫（规格 §C-2）。

    - 守卫 |R|²+|T|²≤1+1e-9：违即 ValueError（χ 含增益支——本式口径
      Im χ>0 即增益；无耗面要求 χ 实数，有耗面要求 Im χ<0）。
    - polarization：'x'/'y'（法向入射共极化简并，同一结果）；其他值
      ValueError；交叉极化走 chi_em/chi_me 参数位（显式不做，传非 None
      即 ValueError）。
    - 返回 complex 的 t/r 及 dB/相位（零值 dB/相位为 None，JSON 安全）。
    """
    if chi_em is not None or chi_me is not None:
        raise ValueError(_CHI_EM_MSG)
    if polarization not in _POL_CO:
        raise ValueError(
            f"polarization={polarization!r} 非法：法向入射只支持 "
            f"'x'/'y'（单轴面共极化简并）；交叉极化走 chi_em/chi_me 参数位"
            "（显式不做）")
    ce = _as_complex(chi_ee, "chi_ee")
    cm = _as_complex(chi_mm, "chi_mm")
    k = _as_k(k_rad_m)
    t, r = _forward_core(ce, cm, k)
    energy = abs(t) ** 2 + abs(r) ** 2
    if energy > 1.0 + _ENERGY_TOL:
        raise ValueError(
            f"无源守卫违背：|R|²+|T|²={energy:.6e} > 1+{_ENERGY_TOL:g}"
            f"（χ 含增益支：本式口径 Im χ>0 即增益——无耗面要求 χ 实数、"
            "有耗面要求 Im χ<0）")
    return {
        "t": t, "r": r, "energy": energy,
        "t_db": _amp_db(t), "r_db": _amp_db(r),
        "t_phase_deg": _phase_deg(t), "r_phase_deg": _phase_deg(r),
        "chi_ee": ce, "chi_mm": cm, "k_rad_m": k,
        "polarization": polarization,
    }


# ─── 逆解（Eq.19）与往返自检 ─────────────────────────────────────────────────


def gstc_synthesize(t: Any, r: Any, k_rad_m: Any) -> dict[str, Any]:
    """Eq.(19) 逆解：(T, R) → (χ_ee, χ_mm)，内置 Eq.19↔Eq.17 往返自检。

    - 奇点守卫：|T+R+1| 或 |T−R+1| < 1e-9 → ValueError（χ→∞ 极点域，
      如 T=−1 全反 Huygens 极限）——反演病态显式拒绝不外推。
    - 往返自检：χ 回代 Eq.(17)/(18)（无守卫裸路径 _forward_core），
      max(|ΔT|,|ΔR|) > 1e-12 即 RuntimeError（代数上应精确恒等）。
    - 诚实边界：正向无源守卫**不**在本路径套用（实测目标可轻微超物理
      ——反演是纯代数，χ 出现微小增益部是数据问题不是本函数故障；
      守卫语义归 gstc_forward）。χ 的可实现性判读归调用方。
    """
    tv = _as_complex(t, "t")
    rv = _as_complex(r, "r")
    k = _as_k(k_rad_m)
    den_e = tv + rv + 1.0
    den_m = tv - rv + 1.0
    if abs(den_e) < _SINGULAR_TOL:
        raise ValueError(
            f"Eq.(19) χ_ee 分母 |T+R+1|={abs(den_e):.3e} < {_SINGULAR_TOL:g}"
            "（χ_ee→∞ 极点域，如 T=−1 全反 Huygens 极限）——反演病态显式拒绝")
    if abs(den_m) < _SINGULAR_TOL:
        raise ValueError(
            f"Eq.(19) χ_mm 分母 |T−R+1|={abs(den_m):.3e} < {_SINGULAR_TOL:g}"
            "（χ_mm→∞ 极点域）——反演病态显式拒绝")
    chi_ee = 2j * (tv + rv - 1.0) / (k * den_e)
    chi_mm = 2j * (tv - rv - 1.0) / (k * den_m)
    t2, r2 = _forward_core(chi_ee, chi_mm, k)
    residual = max(abs(t2 - tv), abs(r2 - rv))
    if residual > _ROUNDTRIP_TOL:
        raise RuntimeError(
            f"Eq.(19)↔Eq.(17) 往返自检失败：max(|ΔT|,|ΔR|)={residual:.3e} > "
            f"{_ROUNDTRIP_TOL:g}（代数上应精确恒等——实现缺陷，禁止消费本结果）")
    return {
        "chi_ee": chi_ee, "chi_mm": chi_mm, "k_rad_m": k,
        "roundtrip_residual": residual,
        "t_recovered": t2, "r_recovered": r2,
    }


# ─── 载体换算与带内对拍通道（J4 Floquet 锚接口面）────────────────────────────


def t_r_from_db_phase(db: Any, phase_deg: Any) -> np.ndarray:
    """dB 幅度 + 解缠相位（度）→ 复数数组（LUT v2 s21 载体消费口）。

    t = 10^(db/20)·e^{j·phase}——MetasurfaceLUT v2 的 s21_db/s21_phase_deg
    列直通本函数构成复透射（metasurface_lut.lut_interp_s21_pchip 出
    (dB, deg)，本函数出 complex，两步即 LUT→gstc 通道桥）。
    """
    mag = 10.0 ** (np.asarray(db, dtype=float) / 20.0)
    ph = np.exp(1j * np.radians(np.asarray(phase_deg, dtype=float)))
    return mag * ph


def gstc_crosscheck(freq_ghz: Any, s11: Any, s21: Any, *,
                    band_ghz: Any = None,
                    gate_dt_db: float = DT_GATE_DB_DEFAULT) -> dict[str, Any]:
    """带内对拍通道：频带 (Γ,T) → Eq.(19) χ 反演 → 正演回 Δ|T|_dB 门。

    规格 §C-2：「ms 真机单胞 Γ/T→χ 反演→正演回对拍（J4 Floquet 锚通道），
    门=带内 Δ|T|≤0.5dB 起步」。入参为真机/合成单胞扫频复数组（s11=Γ、
    s21=T，元素=实数或 [re,im] 对）；band_ghz=[f_lo, f_hi] 缺省全带。
    逐点反演奇点（χ→∞ 极点域）带频点指数报 ValueError。

    诚实边界：离线通道正反两腿同源闭式 → Δ|T|≈1e-13 dB（门判接口/管线
    破坏：长度错位/NaN/奇点/精度）；判别力在 J4 Floquet 锚真机侧替换
    正演腿后到位（真机面本批不做，接口留位）。
    """
    f = np.atleast_1d(np.asarray(freq_ghz, dtype=float))
    if f.ndim != 1 or f.size < 1:
        raise ValueError(f"freq_ghz 需一维非空数组，形状 {np.shape(freq_ghz)}")
    if not bool(np.all(np.isfinite(f))) or bool(np.any(f <= 0)):
        raise ValueError("freq_ghz 须全为正有限数")
    if bool(np.any(np.diff(f) <= 0)):
        raise ValueError("freq_ghz 须严格升序（对拍通道频轴口径）")
    if not (isinstance(s11, (list, tuple)) and isinstance(s21, (list, tuple))):
        raise ValueError("s11/s21 须为序列（逐频点复数：实数或 [re,im] 对）")
    if len(s11) != len(s21) or len(s11) != int(f.size):
        raise ValueError(
            f"s11/s21/freq_ghz 长度不一致：{len(s11)}/{len(s21)}/{int(f.size)}")
    g = [_as_complex(v, f"s11[{i}]") for i, v in enumerate(s11)]
    tdata = [_as_complex(v, f"s21[{i}]") for i, v in enumerate(s21)]

    # 带内掩码
    if band_ghz is None:
        mask = np.ones(int(f.size), dtype=bool)
    else:
        band = np.asarray(band_ghz, dtype=float).ravel()
        if band.size != 2 or not bool(np.all(np.isfinite(band))) \
                or band[0] >= band[1]:
            raise ValueError(f"band_ghz 须为 [f_lo, f_hi] 且 lo<hi，得 {band_ghz!r}")
        mask = (f >= band[0]) & (f <= band[1])
        if not bool(mask.any()):
            raise ValueError(
                f"带内无频点：band_ghz={band_ghz!r} 与扫频 "
                f"[{f[0]}, {f[-1]}] 不相交")

    gate = float(gate_dt_db)
    if not math.isfinite(gate) or gate <= 0:
        raise ValueError(f"gate_dt_db 须为正有限数，得 {gate!r}")

    chi_ee_list: list[list[float]] = []
    chi_mm_list: list[list[float]] = []
    dt_db_list: list[float | None] = []
    max_dt: float | None = None
    max_dt_freq: float | None = None
    n_excluded = 0
    for i in range(int(f.size)):
        k = 2.0 * math.pi * (float(f[i]) * 1e9) / C0_M_S
        try:
            inv = gstc_synthesize(tdata[i], g[i], k)
        except ValueError as exc:
            raise ValueError(f"频点 {i}（{float(f[i])} GHz）反演失败: {exc}") from exc
        chi_ee_list.append([inv["chi_ee"].real, inv["chi_ee"].imag])
        chi_mm_list.append([inv["chi_mm"].real, inv["chi_mm"].imag])
        if mask[i]:
            db_meas = _amp_db(tdata[i])
            db_rec = _amp_db(inv["t_recovered"])
            if db_meas is None or db_rec is None:
                # |T|=0 无有限 dB——该点诚实剔除不进 max（计数上报）
                dt_db_list.append(None)
                n_excluded += 1
            else:
                dt = abs(db_meas - db_rec)
                dt_db_list.append(dt)
                if max_dt is None or dt > max_dt:
                    max_dt = dt
                    max_dt_freq = float(f[i])
    # 带内全部 |T|=0（无有限 dB）→ 如实 UNKNOWN，不凑 PASS 也不凑 FAIL
    verdict = ("UNKNOWN" if max_dt is None
               else "PASS" if max_dt <= gate else "FAIL")
    return {
        "n_points": int(f.size),
        "n_in_band": int(mask.sum()),
        "band_ghz": None if band_ghz is None else [float(band_ghz[0]),
                                                   float(band_ghz[1])],
        "gate_dt_db": gate,
        "max_dt_db": max_dt,
        "max_dt_freq_ghz": max_dt_freq,
        "n_dt_excluded": n_excluded,
        "verdict": verdict,
        "chi_ee": chi_ee_list,
        "chi_mm": chi_mm_list,
        "dt_db": dt_db_list,
    }
