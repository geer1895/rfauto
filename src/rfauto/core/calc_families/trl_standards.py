"""TRL 校准件设计面（aurora36 W6-A 席，R2 空白域 G7——标准件设计端补口）。

出处（TRL 校准经典文献，正文物理口径节转录）：
- trl_standards_design / trl_line_electric_scan：TRL 标准件设计与
  经典窗判据（G. F. Engen & C. A. Hoer, "'Thru-Reflect-Line': An
  improved technique for calibrating the dual six-port automatic
  network analyzer", IEEE Trans. MTT 27(12), 1979；校准件设计规则
  NIST Technical Note 1341）。

两键：trl_standards_design（直通/反射/线标准件综合 + 经典窗判据）/
trl_line_electric_scan（线标准件频带电长度扫描 + 覆盖率适用性）。

与既有 trl_solt 的分工（语义防撞）
----------------------------------
core/trl_solt.py = 标准件**原始测量数据 → 误差箱提取 + 校准应用**
（solt_extract/trl_extract/apply_calibration，测量链下游）；本族 =
校准件**设计端**（给定介质与频带 → 标准件物理长度与适用性判据，
测量链上游），全仓此前仅 3 处注释性命中（R2 §③ G7 三重搜索证据），
零键面重叠。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- 介质双路恰给其一：
  ① 波导路——wr_name 走 core/rw_tables 单源（wr_lookup），TE10 导波
  波长 λg=C/√(f²−fc²)（消费 rw_tables.wavelength_g 同款闭式；
  fc=c/(2a) 恒等式表内自洽）；f 距截止 <1.05× 显式拒绝（λg 发散带，
  bethe_hole_coupler 同守卫口径）。
  ② TEM 路——显式 z0_ohm/epsilon_eff（微带等准 TEM 用工程 εeff），
  λg=C/(f·√εeff)。
- TRL 线标准长度：带中心 f_c=(f1+f2)/2 的 λg(f_c)/4（L. Engen &
  C. Hoer, "Thru-Reflect-Line: An Improved Technique for Calibrating
  the Dual Six-Port Automatic Network Analyzer", IEEE Trans. MTT
  27(12):987-998, 1979 原理；NIST Technical Note 1341 校准件设计
  规则面。同源引注背书的六端口反演架构面=calc_families/six_port.py
  （aurora_f W3-S10 D7 落地；本族=TRL/SOLT 标准件设计端、六端口
  Γ 反演在其层，边界互指））。
- 经典窗判据（教科书规则面，两判据独立回显）：
  ① 线标准电长度窗 θ∈[20°,160°]：θ 过小（近 0°，line 与 thru 不可分）
  或过大（近 180°，λg/4 谐振病态、反射相位敏感）时 TRL 提取病态
  （NIST TN 1341 / 教科书推荐窗；θ(f)=360·L/λg(f) 单调升，带缘 θ1<90°
  <θ2 自动成立）；
  ② 单线频带比窗 f2/f1∈[1.2,3]（任务书经典窗）：TEM 无色散下比值
  r 对应带缘电长度 θ1=90°·2/(1+r)、θ2=90°·2r/(1+r)——r=8 恰触
  [20°,160°] 窗界（θ1=20°/θ2=160°，测试钉），r=3 → 45°/135°；
  波导色散下窗判据由 θ 扫描独立回显（λg 随 f 下降 → θ2/θ1 比值
  大于频率比）。
- 直通标准：长度 0（flush，TRL 惯用口径）或短直通
  through_length_mm>0 显式给。
- 反射标准：短路/开路（TRL 对反射标准只要求 |Γ|≈1、相位任意——
  Engen-Hoer 原理），offset="ideal"（参考面处理想短路/开路）或
  "quarter_wave"（λg/4 偏置短路段：无损线变换 Zin=jZ0·tan(βl)
  （短路面）→ l=λg/4 时 tan→∞ 呈开路；开路件反之呈短路；
  βl=2π·l/λg）。波导路归一化电抗面回显（不冒充绝对欧姆）。
- 守卫：f2>f1>0；wr_name 与 z0/εeff 互斥且 z0/εeff 须成对；z0>0、
  εeff≥1；through_length_mm≥0；reflect_type/offset 白名单；波导
  f<1.05·fc 拒绝；线长>0；n_points∈[2,2001]；越界一律显式拒绝。

数值锚（#118 独立来源：闭式自洽回收 + 教科书窗界恒等，不用自身
推导互证；锚树 tests/unit/test_w6a_trl_emc.py）
- WR-90 @10 GHz λg/4 = C/(4√(f²−fc²)) = 9.927mm（c0/(4√(1−(λ0/2a)²))
  自洽回收口径；~10mm 量级锚）；
- TEM 经典窗界恒等：f2/f1=8 → 带缘电长度恰 20°/160°（窗界自洽）；
  f2/f1=3 → 45°/135°；
- WR-90 X 波段 8.2–12.4 GHz 单线（λg/4@10.3）带缘电长度 55.8°/119.3°
  在窗内（色散口径扫描独立核对）；
- 扫描键闭式逆 θ(f)=θt 的连续解 f=√(fc²+(θt·C/(360L))²)（波导）/
  f=θt·C/(360·L·√εeff)（TEM）与栅格穿越点一致。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator

# 经典窗常量（教科书规则面，任务书钉；两键共用）
_THETA_WINDOW_DEG = (20.0, 160.0)
_RATIO_WINDOW = (1.2, 3.0)
# 波导截止附近拒绝下界（λg 发散带，bethe_hole_coupler 同口径）
_F_OVER_FC_MIN = 1.05

_SOURCE_TRL = ("Engen & Hoer 1979 IEEE Trans.MTT 27(12):987-998 (TRL 原理); "
               "NIST TN 1341 校准件设计规则; WR 表 core/rw_tables 单源")

_MEDIUM_NOTE = ("TRL 反射标准只要求 |Γ|≈1、相位任意（Engen-Hoer 原理），"
                "短路/开路皆可")


# ─── 介质解析与电长度公共核 ──────────────────────────────────────────────────

def _resolve_medium(wr_name: str | None, z0_ohm: float | None,
                    epsilon_eff: float | None, key: str
                    ) -> dict[str, Any]:
    """介质双路解析：wr_name（波导，rw_tables 单源）XOR z0+εeff（TEM）。"""
    if wr_name is not None and (z0_ohm is not None or epsilon_eff is not None):
        raise ValueError(f"{key}: wr_name（波导路）与 z0_ohm/epsilon_eff"
                         "（TEM 路）只能二选一")
    if wr_name is not None:
        from rfauto.core.rw_tables import wr_lookup

        try:
            rec = wr_lookup(str(wr_name))
        except KeyError as exc:
            # 服务层 ok=False 信封只收 ValueError/TypeError 族（KeyError
            # 逃逸会裸抛）——未知名翻译成 ValueError 显式拒绝
            raise ValueError(f"{key}: {exc}") from exc
        return {"kind": "waveguide", "wr_name": rec.wr_name,
                "a_mm": rec.a_mm, "b_mm": rec.b_mm,
                "fc10_ghz": rec.fc10_ghz,
                "band_ghz": [rec.f_start_ghz, rec.f_end_ghz],
                "wr_source": rec.source}
    if z0_ohm is None or epsilon_eff is None:
        raise ValueError(
            f"{key}: 须给 wr_name（WR 型号，rw_tables 单源）或同时给 "
            "z0_ohm/epsilon_eff（TEM 显式口径）")
    z0 = float(z0_ohm)
    eps = float(epsilon_eff)
    if not (math.isfinite(z0) and z0 > 0.0):
        raise ValueError(f"{key}: z0_ohm 必须为正有限数，得到 {z0_ohm!r}")
    if not (math.isfinite(eps) and eps >= 1.0):
        raise ValueError(
            f"{key}: epsilon_eff 必须 ≥1（有效介电常数物理下界），"
            f"得到 {epsilon_eff!r}")
    return {"kind": "tem", "z0_ohm": z0, "epsilon_eff": eps}


def _lambda_g_mm(freq_ghz: float, medium: dict[str, Any]) -> float:
    """导波波长（mm）：波导路消费 rw_tables.wavelength_g 单源。"""
    if medium["kind"] == "waveguide":
        from rfauto.core.rw_tables import wavelength_g

        return wavelength_g(freq_ghz, medium["a_mm"])
    return C_MM_GHZ / (freq_ghz * math.sqrt(medium["epsilon_eff"]))


def _check_band(freq_lo: Any, freq_hi: Any, medium: dict[str, Any],
                key: str) -> tuple[float, float]:
    """频带守卫：f2>f1>0；波导路带缘须距截止 ≥1.05×（λg 发散显式拒绝）。"""
    f1 = float(freq_lo)
    f2 = float(freq_hi)
    if not (math.isfinite(f1) and math.isfinite(f2) and f1 > 0.0 and f2 > f1):
        raise ValueError(
            f"{key}: 频带须满足 0<f1<f2（GHz），得到 f1={freq_lo!r}, "
            f"f2={freq_hi!r}")
    if medium["kind"] == "waveguide":
        fc = float(medium["fc10_ghz"])
        for f in (f1, f2):
            if f < _F_OVER_FC_MIN * fc:
                raise ValueError(
                    f"{key}: f={f:g} GHz 距 TE10 截止 {fc:.4f} GHz 不足 "
                    f"{_F_OVER_FC_MIN:g}×（截止附近 λg 发散，显式拒绝）")
    return f1, f2


def _electric_deg(length_mm: float, freq_ghz: float,
                  medium: dict[str, Any]) -> float:
    """线标准电长度 θ=360°·L/λg(f)（度；λg 随 f 降 → θ 单调升）。"""
    return 360.0 * length_mm / _lambda_g_mm(freq_ghz, medium)


def _medium_out(medium: dict[str, Any]) -> dict[str, Any]:
    """介质信息回显块（JSON 面可序列化）。"""
    if medium["kind"] == "waveguide":
        return {"kind": "waveguide", "wr_name": medium["wr_name"],
                "a_mm": round(float(medium["a_mm"]), 4),
                "b_mm": round(float(medium["b_mm"]), 4),
                "fc10_ghz": round(float(medium["fc10_ghz"]), 6),
                "recommended_band_ghz": [float(medium["band_ghz"][0]),
                                         float(medium["band_ghz"][1])],
                "wr_table_source": medium["wr_source"]}
    return {"kind": "tem", "z0_ohm": float(medium["z0_ohm"]),
            "epsilon_eff": float(medium["epsilon_eff"])}


def _reflect_presented(reflect_type: str, offset_mm: float,
                       lambda_g_center_mm: float) -> float:
    """反射件参考面归一化电抗 x（短路面 Zin=jZ0·tanβl → x=tan(βl)；
    开路件 Zin=−jZ0/tanβl → x=−1/tan(βl)；无损 |Γ|≡1）。"""
    beta_l = 2.0 * math.pi * offset_mm / lambda_g_center_mm
    tan_bl = math.tan(beta_l)
    if abs(tan_bl) < 1e-12:
        return math.inf if reflect_type == "open" else 0.0
    return tan_bl if reflect_type == "short" else -1.0 / tan_bl


def _window_verdict(theta1: float, theta2: float, ratio: float
                    ) -> dict[str, Any]:
    lo, hi = _THETA_WINDOW_DEG
    r_lo, r_hi = _RATIO_WINDOW
    return {
        "theta_window_deg": [lo, hi],
        "theta1_in_window": bool(theta1 >= lo),
        "theta2_in_window": bool(theta2 <= hi),
        "theta_window_ok": bool(theta1 >= lo and theta2 <= hi),
        "ratio_window": [r_lo, r_hi],
        "freq_ratio_in_window": bool(r_lo <= ratio <= r_hi),
        "window_rule": "线标准带缘电长度 [20°,160°]（NIST TN 1341/教科书"
                       "推荐窗）；单线频带比 f2/f1∈[1.2,3]",
    }


# ─── 键 1：TRL 标准件综合 ────────────────────────────────────────────────────

@register_calculator(
    "trl_standards_design",
    "TRL 校准件设计面（直通/反射/线标准件综合）：给定波导（wr_name 走 "
    "rw_tables 单源）或 TEM 线（z0_ohm/epsilon_eff 显式）与频带 f1–f2 → "
    "线标准长度=带中心 λg/4（Engen-Hoer 1979/NIST TN 1341 规则）、直通"
    "长度（0=flush 或短直通）、反射标准（短路/开路 × ideal/λg/4 偏置，"
    "归一化电抗回显，|Γ|≡1 口径）+ 经典窗双判据（带缘电长度 [20°,160°] "
    "推荐窗 + 单线频带比 f2/f1∈[1.2,3]；越窗给多线 TRL 建议 note）。"
    "锚：WR-90@10GHz λg/4=9.927mm；TEM 比值 8 恰触 20°/160° 窗界。守卫："
    "波导 f<1.05·fc 拒绝（λg 发散）；wr_name 与 z0/εeff 互斥",
    (("wr_name", "str - WR 波导型号（如 'WR-90'，rw_tables 单源；与 "
      "z0_ohm/epsilon_eff 二选一）"),
     ("z0_ohm", "float Ω TEM 线特性阻抗（显式口径，须与 epsilon_eff 同给）"),
     ("epsilon_eff", "float - TEM 线有效介电常数（≥1）"),
     ("f1_ghz", "float GHz 频带下缘（>0）"),
     ("f2_ghz", "float GHz 频带上缘（>f1）"),
     ("through_length_mm", "float mm 直通长度（≥0，缺省 0=flush 口径）"),
     ("reflect_type", "str - short|open（缺省 short）"),
     ("reflect_offset", "str - ideal|quarter_wave（缺省 ideal；"
      "quarter_wave=λg/4 偏置短路段，无损线变换）")),
    required=("f1_ghz", "f2_ghz"),
)
def trl_standards_design(f1_ghz: float, f2_ghz: float,
                         wr_name: str | None = None,
                         z0_ohm: float | None = None,
                         epsilon_eff: float | None = None,
                         through_length_mm: float = 0.0,
                         reflect_type: str = "short",
                         reflect_offset: str = "ideal") -> dict[str, Any]:
    key = "trl_standards_design"
    medium = _resolve_medium(wr_name, z0_ohm, epsilon_eff, key)
    f1, f2 = _check_band(f1_ghz, f2_ghz, medium, key)
    thru = float(through_length_mm)
    if not (math.isfinite(thru) and thru >= 0.0):
        raise ValueError(
            f"{key}: through_length_mm 必须为非负有限数，"
            f"得到 {through_length_mm!r}")
    if reflect_type not in ("short", "open"):
        raise ValueError(
            f"{key}: reflect_type 须为 short|open，得到 {reflect_type!r}")
    if reflect_offset not in ("ideal", "quarter_wave"):
        raise ValueError(
            f"{key}: reflect_offset 须为 ideal|quarter_wave，"
            f"得到 {reflect_offset!r}")

    f_center = 0.5 * (f1 + f2)
    lambda_g_center = _lambda_g_mm(f_center, medium)
    line_length_mm = lambda_g_center / 4.0
    theta1 = _electric_deg(line_length_mm, f1, medium)
    theta2 = _electric_deg(line_length_mm, f2, medium)
    ratio = f2 / f1
    window = _window_verdict(theta1, theta2, ratio)

    notes: list[str] = []
    if not window["theta_window_ok"]:
        notes.append(
            "带缘电长度越 [20°,160°] 经典窗（θ 过小与 thru 不可分/过大谐振"
            "病态）——建议多线 TRL（分段 line 标准覆盖带）或收窄频带")
    if not window["freq_ratio_in_window"]:
        notes.append(
            f"频带比 f2/f1={ratio:.4g} 越 [1.2,3] 经典窗——单线 TRL 适用性"
            "欠佳，建议多线分段（每段满足电长度窗）")

    offset_mm = 0.0 if reflect_offset == "ideal" else lambda_g_center / 4.0
    x_norm = _reflect_presented(reflect_type, offset_mm, lambda_g_center)
    reflect: dict[str, Any] = {
        "type": reflect_type,
        "offset": reflect_offset,
        "offset_length_mm": round(offset_mm, 6),
        "presented_norm_x": (None if math.isinf(x_norm) else round(x_norm, 9)),
        "presented_gamma_mag": 1.0,
        "note": _MEDIUM_NOTE + ("；λg/4 偏置把短路变开路/开路变短路"
                                "（无损线变换）"
                                if reflect_offset == "quarter_wave" else
                                "；ideal=参考面处理想件"),
    }
    if math.isinf(x_norm):
        reflect["presented_norm_x_note"] = "tan(90°) 发散=理想开路面（数值发散如实返 null 面）"
    if medium["kind"] == "tem":
        z0 = float(medium["z0_ohm"])
        reflect["presented_z_ohm_re"] = 0.0
        reflect["presented_z_ohm_im"] = (
            None if math.isinf(x_norm) or math.isinf(abs(x_norm))
            else round(x_norm * z0, 6))

    return {
        "medium": _medium_out(medium),
        "f1_ghz": round(f1, 6),
        "f2_ghz": round(f2, 6),
        "freq_ratio": round(ratio, 9),
        "f_center_ghz": round(f_center, 9),
        "lambda_g_center_mm": round(lambda_g_center, 6),
        "line_standard_length_mm": round(line_length_mm, 6),
        "line_electric_deg": {
            "f1": round(theta1, 6),
            "center": 90.0,
            "f2": round(theta2, 6),
        },
        "through": {
            "length_mm": round(thru, 6),
            "note": ("flush 直通（长度 0，参考面直连，TRL 惯用）" if thru == 0.0
                     else "短直通（长度非 0，须在误差箱中作为级联线段处理）"),
        },
        "reflect": reflect,
        "window": window,
        "multi_line_suggested": bool(notes),
        "notes": notes,
        "source": _SOURCE_TRL,
    }


# ─── 键 2：线标准电长度扫描与覆盖率 ──────────────────────────────────────────

def _theta_band_edges(length_mm: float, medium: dict[str, Any]
                      ) -> tuple[float, float]:
    """电长度窗界 [20°,160°] 的连续频率解（闭式逆，GHz/mm 单位制）。

    波导：θ=360·L·√(f²−fc²)/C → f=√(fc²+(θ·C/(360L))²)；
    TEM：θ=360·L·f·√εeff/C → f=θ·C/(360·L·√εeff)。
    """
    lo, hi = _THETA_WINDOW_DEG
    if medium["kind"] == "tem":
        k = C_MM_GHZ / (360.0 * length_mm * math.sqrt(medium["epsilon_eff"]))
        return lo * k, hi * k
    fc = float(medium["fc10_ghz"])

    def f_at(theta_t: float) -> float:
        return math.sqrt(fc * fc
                         + (theta_t * C_MM_GHZ / (360.0 * length_mm)) ** 2)

    return f_at(lo), f_at(hi)


@register_calculator(
    "trl_line_electric_scan",
    "TRL电长度扫描：TRL 线标准适用性键（频带电长度扫描 + 覆盖率）：给定线长 line_length_mm"
    "（波导 wr_name 或 TEM z0/εeff 双路同 trl_standards_design）与频带 "
    "f1–f2 → 逐频点电长度 θ(f)=360°·L/λg(f) 数组、[20°,160°] 经典窗覆盖"
    "率（窗内点占比）、窗界连续解 [f_lo,f_hi]（闭式逆：波导 "
    "f=√(fc²+(θ·C/(360L))²)/TEM 线性逆）与全带覆盖判定。θ 随 f 单调升"
    "（λg 降）。守卫同族：线长>0、n_points∈[2,2001]、波导 f<1.05·fc 拒绝",
    (("wr_name", "str - WR 波导型号（rw_tables 单源；与 z0/εeff 二选一）"),
     ("z0_ohm", "float Ω TEM 线特性阻抗（显式口径）"),
     ("epsilon_eff", "float - TEM 线有效介电常数（≥1）"),
     ("line_length_mm", "float mm 线标准物理长度（>0）"),
     ("f1_ghz", "float GHz 频带下缘（>0）"),
     ("f2_ghz", "float GHz 频带上缘（>f1）"),
     ("n_points", "int 扫描点数（[2,2001]，缺省 41）")),
    required=("line_length_mm", "f1_ghz", "f2_ghz"),
)
def trl_line_electric_scan(line_length_mm: float, f1_ghz: float,
                           f2_ghz: float, wr_name: str | None = None,
                           z0_ohm: float | None = None,
                           epsilon_eff: float | None = None,
                           n_points: int = 41) -> dict[str, Any]:
    key = "trl_line_electric_scan"
    medium = _resolve_medium(wr_name, z0_ohm, epsilon_eff, key)
    length = float(line_length_mm)
    if not (math.isfinite(length) and length > 0.0):
        raise ValueError(
            f"{key}: line_length_mm 必须为正有限数，得到 {line_length_mm!r}")
    f1, f2 = _check_band(f1_ghz, f2_ghz, medium, key)
    n = int(n_points)
    if n < 2 or n > 2001:
        raise ValueError(f"{key}: n_points 须在 [2,2001] 内，得到 {n_points!r}")

    step = (f2 - f1) / (n - 1)
    freqs = [f1 + step * i for i in range(n)]
    thetas = [_electric_deg(length, f, medium) for f in freqs]
    lo, hi = _THETA_WINDOW_DEG
    in_win = [bool(lo <= t <= hi) for t in thetas]
    coverage = sum(in_win) / n

    f_lo_raw, f_hi_raw = _theta_band_edges(length, medium)
    f_lo = min(max(f_lo_raw, f1), f2)
    f_hi = min(max(f_hi_raw, f1), f2)
    band_ok = bool(f_lo < f_hi)
    notes: list[str] = []
    if not band_ok:
        notes.append("窗界解落在频带外（线长对频带过短或过长）——本带无"
                     "[20°,160°] 窗内连续子带")

    return {
        "medium": _medium_out(medium),
        "line_length_mm": round(length, 6),
        "f1_ghz": round(f1, 6),
        "f2_ghz": round(f2, 6),
        "n_points": n,
        "freq_ghz": [round(f, 6) for f in freqs],
        "electric_deg": [round(t, 6) for t in thetas],
        "theta_window_deg": [lo, hi],
        "coverage_fraction": round(coverage, 9),
        "full_band_coverage": bool(coverage == 1.0),
        "valid_band_ghz": (None if not band_ok
                           else [round(f_lo, 9), round(f_hi, 9)]),
        "valid_band_clipped": bool(band_ok and (f_lo != f_lo_raw
                                                or f_hi != f_hi_raw)),
        "theta_monotonic_increasing": bool(all(
            thetas[i] < thetas[i + 1] for i in range(n - 1))),
        "notes": notes,
        "source": _SOURCE_TRL,
    }
