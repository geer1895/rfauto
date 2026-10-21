"""矩形波导介质窗族（架构批 W2-S2 席域 C6，R2_core_tier4 §③ Top11
设计案）。

出处（教科书经典口径二级转引，详见下节物理口径）：
- wg_dielectric_window：介质填充波导段 TE10 口径+半波长全传输谐振
  （Pozar, Microwave Engineering 波导媒质填充/阻抗变换节同族二级转引；
  半波长段=双界面反射对消构造恒等式）。

单键 wg_dielectric_window：介质窗（横贯波导截面的介质片/棒，厚度 t）
半波长全传输谐振设计+给定厚度核验+逐频扫描带宽面——与 wg_resonant_
window（感性/容性薄膜片组合谐振窗）成族补全"真空密封窗"两形态。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``dielectric.?window|介质窗`` 仅 multipactor.py:575 一处**边界注记**
（"单表面/介质窗 multipactor 未建模，勿据此免检"）——设计面零（R2 §②
方向 1 判据原文复跑同判）。膜片型窗（waveguide_iris.wg_resonant_
window）已有，介质型空白，本键补口。

物理口径（docstring 写死，#1c/#300 出处纪律；#118 锚树见
tests/unit/test_w2s2_core_tier4.py）
--------------------------------------------------------
介质片（εr，μr=1）横贯波导=一段长 t 的介质填充波导段夹在空气段之间。
TE10 口径（矩形波导主模，介质填充只改 β 与 Z_TE，截止形状同）：

    空气段   β_a = (2πf/c)·√(1 − (fc/f)²)，fc = c/(2a)
    介质段   β_d = (2πf/c)·√(εr − (fc/f)²)
    λg,air = 2π/β_a，λg,slab = 2π/β_d

  TE 模阻抗 Z_TE = ωμ/β → 介质段/空气段阻抗比 Z_d/Z_a = β_a/β_d =
  λg,slab/λg,air（同 μ 口径；与工作频率无关的比值面随输出透出）。

半波长谐振（全传输）恒等式：界面反射 Γ01 = (Z_d−Z_a)/(Z_d+Z_a)，介质
段输入反射（TL 级联闭式）：

    Γ_in = Γ01·(1 − e^{−2jβ_d t})/(1 − Γ01²·e^{−2jβ_d t})

β_d·t = mπ（t = m·λg,slab/2，m=1,2,...）时 e^{−2jβ_d t} = 1 → Γ_in = 0
精确（双界面反射对消——半波长段 ABCD=[−1,0;0,−1] 与恒等矩阵仅差符号，
构造级恒等式）；传输系数 S21 = (1−Γ01²)·e^{−jβ_d t}/(1−Γ01²·e^{−2jβ_d t})
（无损，|S11|²+|S21|²=1 恒等式随 residual 字段自检）。

带宽面（εr/厚度扫描）：freq_ghz 列表给出时逐频精确求 |S11|/|S21|（同一
闭式，无近似——带宽行为由 Γ01 与 β_d(f) 色散自然给出，一阶语义=离谐
振 |Γ| 随 |β_d·t−mπ| 增大，εr 越高 Z 失配越大带宽越窄，扫描表如实透出）。

退化自检：εr=1 → Z_d=Z_a → Γ01=0 → 任意 t 全直通（无窗退化档，如实
输出不拒绝）；εr<1 非物理显式拒绝。

边界防撞（#222）
--------------------------------------------------------
- waveguide_iris.wg_resonant_window=感/容薄膜片组合谐振窗（电纳对消
  口径）——本键=介质段半波长谐振（阻抗变换口径），两形态互指成族不并；
- waveguide_closed_form=圆/矩形腔模谱、waveguide_lambda_g=TE10 传播参
  数抽键——λg 闭式语义分层（本键 λg,slab=介质填充段自算，不撞空气档
  键面）；core/rwg_mmt=数值模匹配（真机仲裁路径，本键=工程闭式档）；
- multipactor=介质窗倍增放电面（其 docstring 边界注记即本键的下游不
  覆盖声明）——本键只做窗传输设计，不做放电阈值；
- 平板介质谐振器（dr_te01d）/介质天线罩（radome 类）语义不并入。

数值锚（#118 独立来源；锚树 tests/unit/test_w2s2_core_tier4.py）
--------------------------------------------------------
- WR-90（a=22.86mm）/f=10GHz/εr=2.2：fc=6.557140GHz、λg,air=
  39.707119mm、λg,slab=22.533532mm、Z_d/Z_a=0.567494、t½=11.266766mm、
  Γ01=−0.275922（独立算术复算逐位）；
- t=λg,slab/2 → |S11|≈0（1e-16 级，构造恒等式）；t=λg,slab 同零；
- t=λg,slab/4 → |Γ_in|=(Z_d²−Z_a²)/(Z_d²+Z_a²)=0.512803（λ/4 变换器
  反射闭式独立路线对拍，−5.800983dB）；
- |S11|²+|S21|²=1 全扫描（能量守恒恒等）；εr=1 → 全直通。

守卫：a_mm>0；f_ghz>TE10 截止（空气段传播守卫）；eps_r≥1（=1 无窗退
化档，<1 非物理拒绝）；m_order≥1 整数（设计档）；t_mm>0（核验档）；
bool 入参显式拒收（_finite_nb，fec_codes._as_int 同族先例）。

接口：纯函数零 IO；math/cmath；全部返回 JSON 可序列化结构（浮点/字符
串/bool/None；数值 0.0 合法，判缺失一律 is not None，禁 ``or 缺省``，
#364④）。无 ``__all__``（公开 API 快照口径，waveguide_iris 先例）。
"""

from __future__ import annotations

import cmath
import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

_C0_M_S = 299792458.0


def _finite_nb(value: Any, name: str) -> float:
    """有限数收敛（bool 显式拒收版，全模块键面入参走此）——
    ``float(True)=1.0`` 静默污染面（W3-S1 审查 P3-2：原声明"自然拒收"
    失实），对齐 fec_codes._as_int 显式 bool 拒绝先例（df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染）")
    return _finite(value, name)


def _slab_face(a_mm: float, f_ghz: float, eps_r: float, tag: str
               ) -> tuple[float, float, float, float, float]:
    """TE10 介质片传播面单源：返回 (λ0_mm, λg,air_mm, λg,slab_mm,
    Z_d/Z_a, fc10_ghz)。"""
    a_m = a_mm * 1.0e-3
    f = f_ghz * 1.0e9
    fc10 = _C0_M_S / (2.0 * a_m)
    if f <= fc10:
        raise ValueError(
            f"{tag}: f_ghz={f_ghz!r} 不高于 TE10 截止 {fc10 / 1e9:.6f} GHz"
            "（空气段截止以下无传播，窗谐振语义失效）")
    k = 2.0 * math.pi * f / _C0_M_S
    beta_a = k * math.sqrt(1.0 - (fc10 / f) ** 2)
    beta_d = k * math.sqrt(eps_r - (fc10 / f) ** 2)
    lam0_mm = _C0_M_S / f * 1.0e3
    return (lam0_mm, 2.0 * math.pi / beta_a * 1.0e3,
            2.0 * math.pi / beta_d * 1.0e3, beta_a / beta_d,
            fc10 / 1.0e9)


def _slab_sparams(z_ratio: float, beta_d_rad_per_mm: float, t_mm: float
                  ) -> tuple[complex, complex]:
    """介质段级联闭式单源：(S11, S21)（空气段参考阻抗归一口径）。

    Γ01=(Z_d−Z_a)/(Z_d+Z_a)（z_ratio=Z_d/Z_a）；Γ_in=Γ01(1−e^{−2jβt})/
    (1−Γ01²e^{−2jβt})、S21=(1−Γ01²)e^{−jβt}/(1−Γ01²e^{−2jβt})（无损
    TL 级联闭式，模块 docstring 物理口径节）。"""
    g = (z_ratio - 1.0) / (z_ratio + 1.0)
    phase = cmath.exp(-2j * beta_d_rad_per_mm * t_mm)
    denom = 1.0 - g * g * phase
    s11 = g * (1.0 - phase) / denom
    s21 = (1.0 - g * g) * cmath.exp(-1j * beta_d_rad_per_mm * t_mm) / denom
    return s11, s21


@register_calculator(
    "wg_dielectric_window",
    "矩形波导介质窗（真空密封窗介质形态）：TE10 口径介质片半波长全传输"
    "谐振——t=m·λg,slab/2 双界面反射对消（Γ_in=Γ01(1−e^{−2jβt})/(1−"
    "Γ01²e^{−2jβt}) 在 βt=mπ 精确为零，构造级恒等式）+Z_TE 口径 Z_d/"
    "Z_a=λg,slab/λg,air+给定厚度核验/设计双档（t_mm 缺省=按 m_order 设"
    "计）+freq_ghz 列表逐频扫描带宽面；εr=1 无窗退化档全直通、<1 拒绝；"
    "能量守恒残差随输出自检；与 wg_resonant_window 膜片型成族（阻抗变"
    "换 vs 电纳对消两口径）",
    (("a_mm", "float mm 波导宽边（TE10 截止=c/2a；>0）"),
     ("f_ghz", "float GHz 设计/工作频率（>TE10 截止）"),
     ("eps_r", "float 介质相对介电常数（≥1；=1 无窗退化档，<1 拒绝）"),
     ("t_mm", "float mm 介质片厚度（核验档；缺省=设计档 m·λg,slab/2）"),
     ("m_order", "int 半波长阶数（设计档 t=m·λg,slab/2；≥1，缺省 1——"
      "工程取最薄档）"),
     ("freq_ghz", "float|list GHz 逐频扫描点（可选——带宽面 |S11|/|S21|"
      " 逐点闭式）")),
    required=("a_mm", "f_ghz", "eps_r"),
)
def wg_dielectric_window(a_mm: float, f_ghz: float, eps_r: float,
                         t_mm: float | None = None,
                         m_order: int = 1,
                         freq_ghz: float | list[float] | None = None
                         ) -> dict[str, Any]:
    tag = "wg_dielectric_window"
    a = _finite_nb(a_mm, f"{tag}.a_mm")
    if a <= 0.0:
        raise ValueError(f"{tag}: a_mm 必须 >0，得到 {a_mm!r}")
    f_val = _finite_nb(f_ghz, f"{tag}.f_ghz")
    er = _finite_nb(eps_r, f"{tag}.eps_r")
    if er < 1.0:
        raise ValueError(
            f"{tag}: eps_r 必须 ≥1（<1 非物理；=1 为无窗退化档），得到 "
            f"{eps_r!r}")
    m_chk = int(m_order)
    if m_chk < 1 or m_chk != m_order:
        raise ValueError(
            f"{tag}: m_order 必须 ≥1 整数，得到 {m_order!r}")

    lam0_mm, lg_a_mm, lg_d_mm, z_ratio, fc10_ghz = _slab_face(
        a, f_val, er, tag)
    beta_d_mm = 2.0 * math.pi / lg_d_mm
    g_if = (z_ratio - 1.0) / (z_ratio + 1.0)
    if t_mm is None:
        route = "design_halfwave"
        t_eff = m_chk * lg_d_mm / 2.0
    else:
        route = "verify_thickness"
        t_eff = _finite_nb(t_mm, f"{tag}.t_mm")
        if t_eff <= 0.0:
            raise ValueError(f"{tag}: t_mm 必须 >0，得到 {t_mm!r}")
    s11, s21 = _slab_sparams(z_ratio, beta_d_mm, t_eff)
    s11_mag = abs(s11)
    s21_mag = abs(s21)
    energy_residual = abs(s11_mag ** 2 + s21_mag ** 2 - 1.0)

    scan: list[dict[str, Any]] | None = None
    if freq_ghz is not None:
        f_list = [freq_ghz] if isinstance(freq_ghz, (int, float)) else list(
            freq_ghz)
        if not f_list:
            raise ValueError(f"{tag}: freq_ghz 至少一个频点")
        scan = []
        for i, f_in in enumerate(f_list):
            f_pt = _finite_nb(f_in, f"{tag}.freq_ghz[{i}]")
            _l0, _la, lg_d_pt, z_r_pt, _fc = _slab_face(a, f_pt, er, tag)
            s11_pt, s21_pt = _slab_sparams(z_r_pt, 2.0 * math.pi / lg_d_pt,
                                           t_eff)
            scan.append({
                "freq_ghz": round(f_pt, 12),
                "s11_mag": round(abs(s11_pt), 15),
                "s11_db": round(20.0 * math.log10(max(abs(s11_pt), 1e-15)),
                                9),
                "s21_mag": round(abs(s21_pt), 15),
                "s21_db": round(20.0 * math.log10(max(abs(s21_pt), 1e-15)),
                                9),
            })

    out: dict[str, Any] = {
        "a_mm": a,
        "f_ghz": f_val,
        "eps_r": er,
        "fc10_ghz": round(fc10_ghz, 9),
        "lambda_0_mm": round(lam0_mm, 12),
        "lambda_g_air_mm": round(lg_a_mm, 12),
        "lambda_g_slab_mm": round(lg_d_mm, 12),
        "z_slab_over_air": round(z_ratio, 12),
        "gamma_interface_mag": round(abs(g_if), 12),
        "route": route,
        "m_order": m_chk,
        "t_mm": round(t_eff, 12),
        "beta_phase_rad": round(beta_d_mm * t_eff, 12),
        "s11_mag": round(s11_mag, 15),
        "s11_db": round(20.0 * math.log10(max(s11_mag, 1e-15)), 9),
        "s21_mag": round(s21_mag, 15),
        "s21_db": round(20.0 * math.log10(max(s21_mag, 1e-15)), 9),
        "resonant": bool(s11_mag <= 1e-9),
        "energy_residual": round(energy_residual, 18),
        "note": (
            "半波长谐振恒等式：t=m·λg,slab/2 → e^{−2jβt}=1 → Γ_in=0（双"
            "界面反射对消，构造级 ~机器精度）；设计档取最薄阶 m_order=1 "
            "工程惯例（可升阶但机械公差敏感度同增，如实同口径算）；verify "
            "档如实给残余反射不凑零；εr=1 退化为无窗直通（Γ01=0 任意 t）"
            "不拒绝；无损口径无吸收/色散材料损耗项（复 εr 不在键面）——"
            "介质窗 multipactor 放电面不在本键（multipactor.py 边界注记"
            "同源声明）"),
        "source": (
            "TE 模阻抗 Z_TE=ωμ/β + 传输线级联闭式（Pozar Microwave "
            "Engineering ch.5 匹配变换器/λg 口径章节级转引，式号不落键"
            "面）；半波长段反射对消=λ/4 变换器族第一性恒等式"),
    }
    if scan is not None:
        out["scan"] = scan
    return out
