"""aurora_l Wave-G G2 席：CALC 跨键交叉验证框架 v1（审计面，2026-10-23）。

═══ 性质与本席纪律 ═══════════════════════════════════════════════════════
本文件是**审查不是修复**（用户令"微波公式计算器加强"的审计维度）：CALC
334 键每键有自己的 test（EXPECTED+invariants），但两个键算同一物理量走
不同公式路径时没有一致性检查。本框架只做跨键对拍；跑出的不一致**如实
登记为发现，不回改 src/**（禁改清单：src/、scripts/、docs/）。

═══ 框架形态（注册表+参数化，非 if-else 硬编码）═════════════════════════
- ``CROSS_PAIR_REGISTRY``：pair_id → CrossPair。**新增一对=在注册表加一个
  注册块**（evaluate 闭包+一行注册），运行器/存在性守卫/台账测试全部
  通用，不动框架本体。
- ``QuantityComparison``：一次对拍（量名/两值/两来源/判定模式/可选独立
  容差）；``documented``+``documented_band`` = **已登记发现**的注记与实测
  偏差带（发现登记面，test_cross_validation_findings_ledger 统一审计）。
- 运行器（test_calc_cross_pair）：逐注册对执行 evaluate → 全部比较量
  偏差 ≤ 容差（rel=对称相对差 |a−b|/max(|a|,|b|)；abs=绝对差，零目标量
  如 |S11|≈0 用）；失败消息带全证据（输入+两键输出+偏差+容差）。
- rel_tol 按域定标：综合键输出几何量有 mm/Ω 位数量化（round 2-5 位），
  互逆回代容差 1e-3~1e-5；单源常量/同公式双实现容差 1e-9~1e-12。

═══ 配对清单（摸底 2026-10-23，25 对=A 互逆 12+B 同量异路 13）═══════════
A 正反解互逆（synthesis 名义参数 → analysis 反解回代）：
  microstrip / cpw / cpwg / cps / stripline / suspended_stripline /
  slotline / siw / dr_te01d（Cohn 超越方程正反）/ coax_line_z0（同键双
  路线 analyze↔synthesize）/ t_match（design→impedance）/
  crlh（balanced_synthesize→unit_cell_report 回判）。
B 同物理量不同公式路径（共同输入子集对拍）：
  微带 (Z0,εeff) 双路径（analysis vs microstrip_lambda_g）；CPW↔CPWG
  半无限基板极限；悬置带线 h→b / h→0 双极限↔带状线；同轴 Z0 记号差
  （工程 60 vs 精确 η0/2π——已登记发现）；TE11 截止双键；矩形波导
  TE10 传播参数双键；ΔR=c/2B 双键（FMCW vs 脉压）；电离层 f_p 双键；
  combline C→0 极限↔λ/4 同轴腔（有限 C arctan 偏差——已登记发现）；
  λ/4 变换长度↔微带 λg/4；切比雪夫原型 ε↔反射函数带边纹波；驻波换算
  自逆往返；π/T/桥 T 衰减器三拓扑同衰减 ABCD→S 对拍。
覆盖域：Z0/εeff/衰减器/滤波器原型/谐振频率/雷达分辨率/传播/匹配/
超材料——宽域。
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY

# ═══ 框架结构 ══════════════════════════════════════════════════════════════

CATEGORY_INVERSE = "inverse_synthesis_analysis"
CATEGORY_SAME_QUANTITY = "same_quantity_diff_path"
_VALID_CATEGORIES = (CATEGORY_INVERSE, CATEGORY_SAME_QUANTITY)


@dataclass(frozen=True)
class QuantityComparison:
    """一次跨键对拍：同一物理量的两个键产出。

    mode="rel"：对称相对差 |a−b|/max(|a|,|b|)（缺省）；mode="abs"：绝对差
    （零目标量如 |S11|≈0 用，此时 tol 必填）。tol=None 用配对级容差。
    documented/document_band：已登记发现的注记与实测偏差带（发现登记面
    ——偏差在带内=登记在案的一致性注记，带外=框架红）。
    """

    quantity: str
    value_a: float
    value_b: float
    source_a: str
    source_b: str
    mode: str = "rel"
    tol: float | None = None
    documented: str = ""
    documented_band: tuple[float, float] | None = None


@dataclass(frozen=True)
class CrossPair:
    """一条配对注册（新增对=加一条）。

    evaluate 返回（比较量列表, 证据 dict）——证据含输入回显与两键原始
    输出，失败消息全量带出（发现=输入+两键输出+差异，审计口径）。
    """

    pair_id: str
    category: str
    domain: str
    description: str
    rel_tol: float
    keys: tuple[str, ...]
    evaluate: Callable[[], tuple[list[QuantityComparison], dict[str, Any]]]
    abs_tol: float | None = None  # mode="abs" 比较量的配对级缺省容差


def _calc(key: str, **params: Any) -> dict[str, Any]:
    """跑一个 CALC 键（注册表直调——纯函数，无 service 开关语义）。"""
    spec = CALCULATOR_REGISTRY.get(key)
    return spec.func(**params)


def _cmp(
    quantity: str,
    value_a: float,
    value_b: float,
    source_a: str,
    source_b: str,
    *,
    tol: float | None = None,
    mode: str = "rel",
    documented: str = "",
    documented_band: tuple[float, float] | None = None,
) -> QuantityComparison:
    """构造比较量（关键字收口，注册块少噪声）。"""
    return QuantityComparison(
        quantity=quantity, value_a=float(value_a), value_b=float(value_b),
        source_a=source_a, source_b=source_b, mode=mode, tol=tol,
        documented=documented, documented_band=documented_band)


def _rel_dev(a: float, b: float) -> float:
    """对称相对差 |a−b|/max(|a|,|b|)（零目标量走 mode="abs"，勿用本式）。"""
    denom = max(abs(a), abs(b))
    if denom == 0.0:
        return 0.0 if a == b else math.inf
    return abs(a - b) / denom


def _limit_of(pair: CrossPair, comp: QuantityComparison) -> float:
    if comp.tol is not None:
        return comp.tol
    if comp.mode == "abs":
        if pair.abs_tol is None:
            raise AssertionError(
                f"{pair.pair_id}: abs 比较量 {comp.quantity!r} 无容差"
                "（comp.tol 或 pair.abs_tol 必居其一，注册错误）")
        return pair.abs_tol
    return pair.rel_tol


# ═══ A 类：正反解互逆（synthesis → analysis 回代）═════════════════════════
# 容差定标依据（各键输出量化位）：几何量 round 4-5 位 mm + Z0 round 2-3 位
# Ω → 回代偏差 ~1e-4 量级封顶；εeff round 4 位 → ~3e-5。取 1e-3 保险带，
# 内核真坏（饱和域塌缩/公式转录错）时远超此带必红。

def _ev_microstrip() -> tuple[list[QuantityComparison], dict[str, Any]]:
    inp = dict(z0_ohm=50.0, freq_ghz=10.0, epsilon_r=4.4, h_mm=0.508)
    s = _calc("microstrip_synthesis", **inp)
    a = _calc("microstrip_analysis", width_mm=s["width_mm"], freq_ghz=10.0,
              epsilon_r=4.4, h_mm=0.508)
    ev = {"inputs": {"synthesis": inp},
          "outputs": {"synthesis": s, "analysis": a}}
    comps = [
        _cmp("z0_ohm", s["z0_actual_ohm"], a["z0_ohm"],
             "microstrip_synthesis.z0_actual_ohm", "microstrip_analysis.z0_ohm"),
        _cmp("eps_eff", s["eps_eff"], a["eps_eff"],
             "microstrip_synthesis.eps_eff", "microstrip_analysis.eps_eff"),
        _cmp("lambda_g_mm", s["lambda_g_mm"], a["lambda_g_mm"],
             "microstrip_synthesis.lambda_g_mm", "microstrip_analysis.lambda_g_mm"),
    ]
    return comps, ev


def _ev_cpw() -> tuple[list[QuantityComparison], dict[str, Any]]:
    inp = dict(z0_ohm=50.0, gap_mm=0.1, freq_ghz=10.0, epsilon_r=4.4,
               h_mm=0.508)
    s = _calc("cpw_synthesis", **inp)
    a = _calc("cpw_analysis", w_mm=s["w_mm"], gap_mm=0.1, freq_ghz=10.0,
              epsilon_r=4.4, h_mm=0.508)
    ev = {"inputs": {"synthesis": inp},
          "outputs": {"synthesis": s, "analysis": a}}
    comps = [
        _cmp("z0_ohm", s["z0_actual_ohm"], a["z0_ohm"],
             "cpw_synthesis.z0_actual_ohm", "cpw_analysis.z0_ohm"),
        _cmp("eps_eff", s["eps_eff"], a["eps_eff"],
             "cpw_synthesis.eps_eff", "cpw_analysis.eps_eff"),
    ]
    return comps, ev


def _ev_cpwg() -> tuple[list[QuantityComparison], dict[str, Any]]:
    # 几何在共形映射适用域内（h 相对 w 不过薄——薄基板 k→1 退化域显式
    # 拒绝是内核正确行为，交叉验证取域内点）
    inp = dict(z0_ohm=50.0, gap_mm=0.3, freq_ghz=10.0, epsilon_r=4.4,
               h_mm=1.6)
    s = _calc("cpwg_synthesis", **inp)
    a = _calc("cpwg_analysis", w_mm=s["w_mm"], gap_mm=0.3, epsilon_r=4.4,
              h_mm=1.6, freq_ghz=10.0)
    ev = {"inputs": {"synthesis": inp},
          "outputs": {"synthesis": s, "analysis": a}}
    comps = [
        _cmp("z0_ohm", s["z0_actual_ohm"], a["z0_ohm"],
             "cpwg_synthesis.z0_actual_ohm", "cpwg_analysis.z0_ohm"),
        _cmp("eps_eff", s["eps_eff"], a["eps_eff"],
             "cpwg_synthesis.eps_eff", "cpwg_analysis.eps_eff"),
    ]
    return comps, ev


def _ev_cps() -> tuple[list[QuantityComparison], dict[str, Any]]:
    inp = dict(z0_ohm=80.0, gap_mm=0.15, freq_ghz=10.0, epsilon_r=3.66,
               h_mm=0.508)
    s = _calc("cps_synthesis", **inp)
    a = _calc("cps_analysis", w_mm=s["w_mm"], gap_mm=0.15, epsilon_r=3.66,
              h_mm=0.508, freq_ghz=10.0)
    ev = {"inputs": {"synthesis": inp},
          "outputs": {"synthesis": s, "analysis": a}}
    comps = [
        _cmp("z0_ohm", s["z0_actual_ohm"], a["z0_ohm"],
             "cps_synthesis.z0_actual_ohm", "cps_analysis.z0_ohm"),
        _cmp("eps_eff", s["eps_eff"], a["eps_eff"],
             "cps_synthesis.eps_eff", "cps_analysis.eps_eff"),
    ]
    return comps, ev


def _ev_stripline() -> tuple[list[QuantityComparison], dict[str, Any]]:
    inp = dict(z0_ohm=50.0, b_mm=1.6, epsilon_r=4.4)
    s = _calc("stripline_synthesis", **inp)
    a = _calc("stripline_analysis", w_mm=s["w_mm"], b_mm=1.6, epsilon_r=4.4)
    ev = {"inputs": {"synthesis": inp},
          "outputs": {"synthesis": s, "analysis": a}}
    comps = [
        _cmp("z0_ohm", s["z0_actual_ohm"], a["z0_ohm"],
             "stripline_synthesis.z0_actual_ohm", "stripline_analysis.z0_ohm"),
        # TEM 均匀填充：εeff≡εr（analysis 直出；synthesis 无此出——
        # 交叉验证对 analysis εeff 与输入 εr 钉 TEM 恒等）
        _cmp("eps_eff_vs_er", a["eps_eff"], 4.4,
             "stripline_analysis.eps_eff", "输入 epsilon_r（TEM 恒等）"),
    ]
    return comps, ev


def _ev_suspended_stripline() -> tuple[list[QuantityComparison], dict[str, Any]]:
    inp = dict(z0_ohm=50.0, b_mm=3.0, h_mm=0.508, epsilon_r=4.4)
    s = _calc("suspended_stripline_synthesis", **inp)
    a = _calc("suspended_stripline_analysis", w_mm=s["w_mm"], b_mm=3.0,
              h_mm=0.508, epsilon_r=4.4)
    ev = {"inputs": {"synthesis": inp},
          "outputs": {"synthesis": s, "analysis": a}}
    comps = [
        _cmp("z0_ohm", s["z0_actual_ohm"], a["z0_ohm"],
             "suspended_stripline_synthesis.z0_actual_ohm",
             "suspended_stripline_analysis.z0_ohm"),
        _cmp("eps_eff", s["eps_eff"], a["eps_eff"],
             "suspended_stripline_synthesis.eps_eff",
             "suspended_stripline_analysis.eps_eff"),
    ]
    return comps, ev


def _ev_slotline() -> tuple[list[QuantityComparison], dict[str, Any]]:
    inp = dict(z0_ohm=60.0, h_mm=0.508, epsilon_r=9.8, freq_ghz=10.0)
    s = _calc("slotline_synthesis", **inp)
    a = _calc("slotline_analysis", w_mm=s["w_mm"], h_mm=0.508,
              epsilon_r=9.8, freq_ghz=10.0)
    ev = {"inputs": {"synthesis": inp},
          "outputs": {"synthesis": s, "analysis": a}}
    comps = [
        _cmp("z0_ohm", s["z0_actual_ohm"], a["z0_ohm"],
             "slotline_synthesis.z0_actual_ohm", "slotline_analysis.z0_ohm"),
        _cmp("eps_eff", s["eps_eff"], a["eps_eff"],
             "slotline_synthesis.eps_eff", "slotline_analysis.eps_eff"),
    ]
    return comps, ev


def _ev_siw() -> tuple[list[QuantityComparison], dict[str, Any]]:
    inp = dict(fc10_ghz=10.0, epsilon_r=2.2, d_mm=0.5, s_mm=1.0)
    s = _calc("siw_synthesis", **inp)
    # 分析频率取带内（12 GHz > fc10=10 GHz）
    a = _calc("siw_analysis", w_mm=s["w_mm"], d_mm=0.5, s_mm=1.0,
              epsilon_r=2.2, freq_ghz=12.0)
    ev = {"inputs": {"synthesis": inp, "analysis_freq_ghz": 12.0},
          "outputs": {"synthesis": s, "analysis": a}}
    comps = [
        _cmp("fc10_ghz", 10.0, a["fc10_ghz"],
             "siw_synthesis 目标 fc10", "siw_analysis.fc10_ghz"),
        _cmp("weff_mm", s["weff_mm"], a["weff_mm"],
             "siw_synthesis.weff_mm", "siw_analysis.weff_mm"),
    ]
    return comps, ev


def _ev_dr_te01d() -> tuple[list[QuantityComparison], dict[str, Any]]:
    inp = dict(epsilon_r=38.0, f0_ghz=3.5, height_to_diameter=0.5)
    s = _calc("dr_te01d_design_size", **inp)
    a = _calc("dr_te01d_cohn_f0", diameter_mm=s["diameter_mm"],
              height_mm=s["height_mm"], epsilon_r=38.0)
    ev = {"inputs": {"design": inp},
          "outputs": {"design": s, "forward": a}}
    comps = [
        _cmp("f0_ghz", 3.5, a["f0_ghz"],
             "dr_te01d_design_size 目标 f0", "dr_te01d_cohn_f0.f0_ghz"),
    ]
    return comps, ev


def _ev_coax_bidirectional() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """coax_line_z0 单键双路线：analyze(a,b)→Z0 → synthesize(Z0,b)→a。"""
    an = _calc("coax_line_z0", a_mm=1.0, b_mm=3.0)
    sy = _calc("coax_line_z0", z0_ohm=an["z0_ohm"], b_mm=3.0)
    ev = {"outputs": {"analyze_route": an, "synthesize_route": sy}}
    comps = [
        _cmp("a_mm_roundtrip", 1.0, sy["a_mm"],
             "analyze 输入 a_mm=1.0", "synthesize_route.a_mm"),
        _cmp("z0_roundtrip", an["z0_ohm"], sy["z0_ohm"],
             "analyze_route.z0_ohm", "synthesize_route.z0_ohm"),
    ]
    return comps, ev


def _ev_t_match() -> tuple[list[QuantityComparison], dict[str, Any]]:
    inp = dict(freq_hz=1.0e9, main_radius_m=1.0e-3, bar_radius_m=0.5e-3,
               spacing_m=10.0e-3, za_re_ohm=73.0, za_im_ohm=0.0,
               target_rin_ohm=50.0)
    d = _calc("t_match_design", **inp)
    i = _calc("t_match_impedance", freq_hz=1.0e9, main_radius_m=1.0e-3,
              bar_radius_m=0.5e-3, spacing_m=10.0e-3,
              tbar_length_m=d["tbar_length_m"], dipole_length_m=0.2,
              za_re_ohm=73.0, za_im_ohm=0.0)
    ev = {"inputs": {"design": inp, "design_tbar_length_m": d["tbar_length_m"]},
          "outputs": {"design": d, "impedance": i}}
    comps = [
        _cmp("rin_re_ohm", 50.0, i["zin_re_ohm"],
             "t_match_design 目标 Rin", "t_match_impedance.zin_re_ohm",
             tol=1.0e-6),
        _cmp("alpha", d["alpha"], i["alpha"],
             "t_match_design.alpha", "t_match_impedance.alpha", tol=1.0e-9),
        _cmp("z0_two_wire_ohm", d["z0_two_wire_ohm"], i["z0_two_wire_ohm"],
             "t_match_design.z0_two_wire_ohm",
             "t_match_impedance.z0_two_wire_ohm", tol=1.0e-9),
    ]
    return comps, ev


# ═══ B 类：同物理量不同公式路径（共同输入子集对拍）═══════════════════════

def _ev_microstrip_two_paths() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """微带 (Z0, εeff)：analysis（forward_z0 链）vs microstrip_lambda_g
    （直构 skrf MLine）——同一 HJ 模型的两条调用路径。"""
    inp = dict(width_mm=0.7, freq_ghz=10.0, epsilon_r=4.4, h_mm=0.508)
    a = _calc("microstrip_analysis", **inp)
    b = _calc("microstrip_lambda_g", **inp)
    ev = {"inputs": inp, "outputs": {"analysis": a, "lambda_g": b}}
    comps = [
        _cmp("z0_ohm", a["z0_ohm"], b["z0_ohm"],
             "microstrip_analysis.z0_ohm", "microstrip_lambda_g.z0_ohm",
             tol=1.0e-9),
        _cmp("eps_eff", a["eps_eff"], b["eps_eff"],
             "microstrip_analysis.eps_eff", "microstrip_lambda_g.eps_eff",
             tol=1.0e-9),
    ]
    return comps, ev


def _ev_cpw_cpwg_semiinfinite() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """CPW（skrf 准静态）vs CPWG（共形映射部分电容）在厚基板半无限极限：
    h≫w 时底接地影响消失，两键应收敛到同一 (Z0, εeff)。"""
    inp = dict(w_mm=0.5, gap_mm=0.2, freq_ghz=10.0, epsilon_r=4.4, h_mm=50.0)
    c1 = _calc("cpw_analysis", **inp)
    c2 = _calc("cpwg_analysis", w_mm=0.5, gap_mm=0.2, epsilon_r=4.4,
               h_mm=50.0, freq_ghz=10.0)
    ev = {"inputs": inp,
          "outputs": {"cpw_analysis": c1, "cpwg_analysis": c2}}
    comps = [
        _cmp("z0_ohm", c1["z0_ohm"], c2["z0_ohm"],
             "cpw_analysis.z0_ohm", "cpwg_analysis.z0_ohm"),
        _cmp("eps_eff", c1["eps_eff"], c2["eps_eff"],
             "cpw_analysis.eps_eff", "cpwg_analysis.eps_eff"),
    ]
    return comps, ev


def _ev_ssl_limits() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """悬置带线两支精确极限锚↔带状线闭式（同族回归锚）：
    h→b（全填充）→ (εr, 带状线 Z0@εr)；h→0（无基板）→ (1, 空气带状线)。"""
    full = _calc("suspended_stripline_analysis", w_mm=1.5, b_mm=3.0,
                 h_mm=3.0, epsilon_r=4.4)
    strip_full = _calc("stripline_analysis", w_mm=1.5, b_mm=3.0,
                       epsilon_r=4.4)
    zero = _calc("suspended_stripline_analysis", w_mm=1.5, b_mm=3.0,
                 h_mm=0.0, epsilon_r=4.4)
    strip_air = _calc("stripline_analysis", w_mm=1.5, b_mm=3.0, epsilon_r=1.0)
    ev = {"outputs": {"ssl_h_full": full, "stripline_full": strip_full,
                      "ssl_h_zero": zero, "stripline_air": strip_air}}
    comps = [
        _cmp("z0_full_fill", full["z0_ohm"], strip_full["z0_ohm"],
             "ssl(h=b).z0_ohm", "stripline(εr).z0_ohm", tol=1.0e-6),
        _cmp("eps_eff_full_fill", full["eps_eff"], strip_full["eps_eff"],
             "ssl(h=b).eps_eff", "stripline(εr).eps_eff", tol=1.0e-6),
        _cmp("z0_zero_fill", zero["z0_ohm"], strip_air["z0_ohm"],
             "ssl(h=0).z0_ohm", "stripline(εr=1).z0_ohm", tol=1.0e-6),
        _cmp("eps_eff_zero_fill", zero["eps_eff"], strip_air["eps_eff"],
             "ssl(h=0).eps_eff", "stripline(εr=1).eps_eff", tol=1.0e-6),
    ]
    return comps, ev


def _ev_coax_z0_convention() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """同轴 Z0 双路径：coax_line_z0（工程记号 60）vs coax_line_attenuation
    （精确 η0/2π=59.9585）——已知记号差 ~0.07%，源码 note 在案。"""
    inp = dict(a_mm=1.0, b_mm=3.0)
    z = _calc("coax_line_z0", **inp)
    att = _calc("coax_line_attenuation", f_ghz=1.0, a_mm=1.0, b_mm=3.0,
                conductivity_s_per_m=5.8e7)
    ev = {"inputs": {"geometry": inp},
          "outputs": {"coax_line_z0": z, "coax_line_attenuation": att}}
    comps = [
        _cmp("z0_ohm", z["z0_ohm"], att["z0_ohm"],
             "coax_line_z0.z0_ohm（60 记号）",
             "coax_line_attenuation.z0_ohm（η0/2π 精确）",
             documented=("同轴 Z0 记号差：阻抗面按工程惯例 60、损耗/Q 链按"
                         "精确 η0/2π=59.9585——源码 note 自证的两口径并存，"
                         "记号差 ~0.07%（非缺陷，登记在案）"),
             documented_band=(5.0e-4, 9.0e-4)),
    ]
    return comps, ev


def _ev_coax_te11_two_keys() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """TE11 截止频率双键（coax_line_z0 vs coax_line_cutoff_attenuator）：
    同式 c0/(π(a+b)√εr) 在两个模块各写一份（转录双实现），应逐位一致。"""
    z = _calc("coax_line_z0", a_mm=1.0, b_mm=3.0)
    cut = _calc("coax_line_cutoff_attenuator", a_mm=1.0, b_mm=3.0,
                length_mm=10.0)
    ev = {"outputs": {"coax_line_z0": {"te11": z["te11_cutoff_ghz"]},
                      "cutoff_attenuator": {"te11": cut["te11_cutoff_ghz"]}}}
    comps = [
        _cmp("te11_cutoff_ghz", z["te11_cutoff_ghz"], cut["te11_cutoff_ghz"],
             "coax_line_z0.te11_cutoff_ghz",
             "coax_line_cutoff_attenuator.te11_cutoff_ghz", tol=1.0e-9),
    ]
    return comps, ev


def _ev_te10_two_keys() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """矩形波导 TE10 传播参数双键（waveguide_lambda_g vs wg_te10_attenuation）：
    Pozar §3 同族两处独立实现（fc/λg/β），输出量化 9 位小数级。"""
    wg = _calc("waveguide_lambda_g", a_mm=22.86, f_ghz=10.0, b_mm=10.16)
    att = _calc("wg_te10_attenuation", a_mm=22.86, b_mm=10.16, f_ghz=10.0)
    ev = {"outputs": {"waveguide_lambda_g": wg, "wg_te10_attenuation": att}}
    comps = [
        _cmp("fc10_ghz", wg["fc10_ghz"], att["fc_ghz"],
             "waveguide_lambda_g.fc10_ghz", "wg_te10_attenuation.fc_ghz",
             tol=1.0e-9),
        _cmp("lambda_g_mm", wg["lambda_g_mm"], att["lambda_g_mm"],
             "waveguide_lambda_g.lambda_g_mm", "wg_te10_attenuation.lambda_g_mm",
             tol=1.0e-9),
        _cmp("beta_rad_per_m", wg["beta_rad_per_m"], att["beta_rad_per_m"],
             "waveguide_lambda_g.beta_rad_per_m",
             "wg_te10_attenuation.beta_rad_per_m", tol=1.0e-9),
    ]
    return comps, ev


def _ev_range_resolution() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """ΔR=c/(2B) 双键：FMCW 带宽-分辨率 vs LFM 脉压设计（同仓双源）。"""
    b_hz = 1.0e9
    f = _calc("fmcw_bandwidth_range_resolution", bandwidth_hz=b_hz)
    p = _calc("pulse_compression_design", bandwidth_hz=b_hz, pulse_width_s=1.0e-6)
    ev = {"inputs": {"bandwidth_hz": b_hz},
          "outputs": {"fmcw": f, "pulse_compression": p}}
    comps = [
        _cmp("range_resolution_m", f["range_resolution_m"],
             p["range_resolution_m"],
             "fmcw_bandwidth_range_resolution.range_resolution_m",
             "pulse_compression_design.range_resolution_m", tol=1.0e-12),
    ]
    return comps, ev


def _ev_plasma_frequency() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """电离层 f_p 双键：critical_frequency（正解）vs
    ionospheric_plasma_frequency（折射指数面的随行 f_p）+ n² 恒等式交叉
    （折射键 n² 对正解键 f_p 的解析关系）。"""
    ne = 1.0e12
    crit = _calc("critical_frequency", electron_density_m3=ne)
    f_twice = 2.0 * crit["f_p_hz"]
    idx = _calc("ionospheric_plasma_frequency", electron_density_m3=ne,
                freq_hz=f_twice)
    ev = {"inputs": {"electron_density_m3": ne, "freq_hz": f_twice},
          "outputs": {"critical": crit, "plasma_index": idx}}
    comps = [
        _cmp("f_p_hz", crit["f_p_hz"], idx["f_p_hz"],
             "critical_frequency.f_p_hz",
             "ionospheric_plasma_frequency.f_p_hz", tol=1.0e-9),
        _cmp("n_squared_identity", 1.0 - (crit["f_p_hz"] / f_twice) ** 2,
             idx["n_squared"],
             "1−(f_p/f)²（critical 键 f_p 代入）",
             "ionospheric_plasma_frequency.n_squared", tol=1.0e-9),
    ]
    return comps, ev


def _ev_combline_c0_limit() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """combline 谐振器 C→0 极限 ↔ λ/4 同轴腔（combline_resonance 的
    θ=arctan(1/(ωCZr)) 在 C→0 时 θ→90°、杆长→λg/4=同轴腔 quarter 腔长）。
    有限 C 的 arctan 截断偏差 ~2/(πωCZr)（登记在案，非缺陷）。"""
    comb = _calc("combline_resonance", zr_ohm=80.0, cap_ff=0.001,
                 epsilon_r=1.0, f0_ghz=2.0)
    cav = _calc("coaxial_cavity_resonance", mode="quarter", f0_ghz=2.0,
                epsilon_r=1.0)
    ev = {"inputs": {"f0_ghz": 2.0, "combline_cap_ff": 0.001},
          "outputs": {"combline": comb, "coaxial_cavity_quarter": cav}}
    comps = [
        _cmp("length_mm", comb["length_mm"], cav["length_mm"],
             "combline_resonance.length_mm（C→0）",
             "coaxial_cavity_resonance.length_mm（λ/4）",
             documented=("combline 有限 C 的 arctan 截断偏差：θ=arctan(1/"
                         "(ωCZr))<90°，cap_ff=1e-3 时偏差 ~2/(πωCZr)≈6.4e-7"
                         "（极限逼近的数学尾差，非缺陷，登记在案）"),
             documented_band=(2.0e-7, 2.0e-6)),
    ]
    return comps, ev


def _ev_quarter_wave_length() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """λ/4 变换器物理长度↔微带 λg/4：quarter_wave_transformer 的 λg 公式
    对 microstrip_synthesis 的 εeff 链（同仓光速常量/εeff→λg 链双键一致）。"""
    ms_inp = dict(z0_ohm=50.0, freq_ghz=10.0, epsilon_r=4.4, h_mm=0.508)
    ms = _calc("microstrip_synthesis", **ms_inp)
    qw = _calc("quarter_wave_transformer", z_source_ohm=25.0,
               z_load_ohm=100.0, freq_ghz=10.0, eps_eff=ms["eps_eff"])
    ev = {"inputs": {"microstrip_synthesis": ms_inp},
          "outputs": {"microstrip_synthesis": ms, "quarter_wave": qw}}
    comps = [
        _cmp("length_mm", qw["length_mm"], ms["lambda_g_mm"] / 4.0,
             "quarter_wave_transformer.length_mm",
             "microstrip_synthesis.lambda_g_mm/4（λg/4 恒等）"),
    ]
    return comps, ev


def _ev_chebyshev_ripple() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """切比雪夫原型↔反射函数带边纹波（滤波器原型域）：prototype 的 ε
    常数 vs refl_fn 带边 |S11|=ε/√(1+ε²)（=−RL dB 纹波定义恒等）。"""
    proto = _calc("chebyshev_prototype", order=3, rl_db=20.0)
    refl = _calc("chebyshev_refl_fn", n=3, rz_db=20.0, omega=[1.0])
    s11_edge = float(refl["s11_mag"][0])
    eps_implied = s11_edge / math.sqrt(1.0 - s11_edge * s11_edge)
    ev = {"inputs": {"order": 3, "rl_db": 20.0, "omega": [1.0]},
          "outputs": {"prototype": proto, "refl_fn": refl}}
    comps = [
        _cmp("s11_band_edge", 10.0 ** (-20.0 / 20.0), s11_edge,
             "10^(−RL/20)（纹波定义）", "chebyshev_refl_fn.s11_mag@Ω=1",
             tol=1.0e-9),
        _cmp("epsilon", proto["epsilon"], eps_implied,
             "chebyshev_prototype.epsilon",
             "chebyshev_refl_fn 带边反推 ε=|S11|/√(1−|S11|²)", tol=1.0e-6),
    ]
    return comps, ev


def _ev_vswr_roundtrip() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """驻波换算自逆往返（vswr_convert 单键三入口互逆）：RL→VSWR→RL 与
    RL→|Γ|→|Γ| 回代（输出 4-6 位量化的往返尾差 ~1e-4 级）。"""
    o1 = _calc("vswr_convert", return_loss_db=20.0)
    o2 = _calc("vswr_convert", vswr=o1["vswr"])
    ev = {"outputs": {"step1_from_rl": o1, "step2_from_vswr": o2}}
    comps = [
        _cmp("return_loss_roundtrip", 20.0, o2["return_loss_db"],
             "输入 return_loss_db=20", "往返 return_loss_db"),
        _cmp("gamma_roundtrip", o1["gamma_mag"], o2["gamma_mag"],
             "step1.gamma_mag", "step2.gamma_mag"),
    ]
    return comps, ev


def _attenuator_sparams(resistors: dict[str, float], z0: float,
                        topology: str) -> tuple[float, float]:
    """由电阻值独立构建 2 端口 Y 矩阵→S 参数（测试侧裁判，#118 口径）。

    π：中点串联+两端并联；T：两臂串联+中点并联；桥 T：两臂各串 Z0、
    桥电阻跨输入-输出、中点并联——桥 T 用三节点导纳消元（中点收缩）。
    """
    if topology == "pi":
        g_ser = 1.0 / resistors["r_series_mid_ohm"]
        g_sh = 1.0 / resistors["r_shunt_end_ohm"]
        y = np.array([[g_sh + g_ser, -g_ser], [-g_ser, g_sh + g_ser]])
    elif topology == "t":
        r_arm = resistors["r_series_arm_ohm"]
        r_mid = resistors["r_shunt_mid_ohm"]
        z = np.array([[r_arm + r_mid, r_mid], [r_mid, r_arm + r_mid]])
        y = np.linalg.inv(z)
    elif topology == "bridged_t":
        r_bridge = resistors["r_bridge_ohm"]
        r_shunt = resistors["r_shunt_mid_ohm"]
        y3 = np.array([
            [1.0 / r_bridge + 1.0 / z0, -1.0 / z0, -1.0 / r_bridge],
            [-1.0 / z0, 2.0 / z0 + 1.0 / r_shunt, -1.0 / z0],
            [-1.0 / r_bridge, -1.0 / z0, 1.0 / r_bridge + 1.0 / z0],
        ])
        idx = [0, 2]
        y_aa = y3[np.ix_(idx, idx)]
        y_am = y3[np.ix_(idx, [1])]
        y_ma = y3[np.ix_([1], idx)]
        y = y_aa - y_am @ y_ma / y3[1, 1]
    else:  # pragma: no cover - 注册面封闭，防御分支
        raise ValueError(f"未知衰减器拓扑 {topology!r}")
    ident = np.eye(2)
    s = np.linalg.solve(ident + z0 * y, ident - z0 * y)
    return abs(s[1, 0]), abs(s[0, 0])


def _ev_attenuator_topologies() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """π/T/桥 T 衰减器三拓扑同衰减对拍（衰减器域）：三条不同闭式路径的
    电阻值各自构建网络，S21 应同值（=1/N）、S11 应同为零（匹配条件）。"""
    atten_db, z0 = 6.0, 50.0
    n = 10.0 ** (atten_db / 20.0)
    pi = _calc("attenuator_pi", attenuation_db=atten_db, z0_ohm=z0)
    t = _calc("attenuator_t", attenuation_db=atten_db, z0_ohm=z0)
    bt = _calc("attenuator_bridged_t", attenuation_db=atten_db, z0_ohm=z0)
    s21_pi, s11_pi = _attenuator_sparams(pi, z0, "pi")
    s21_t, s11_t = _attenuator_sparams(t, z0, "t")
    s21_bt, s11_bt = _attenuator_sparams(bt, z0, "bridged_t")
    ev = {"inputs": {"attenuation_db": atten_db, "z0_ohm": z0},
          "outputs": {"pi": pi, "t": t, "bridged_t": bt,
                      "sparams": {"pi": [s21_pi, s11_pi],
                                  "t": [s21_t, s11_t],
                                  "bridged_t": [s21_bt, s11_bt]}}}
    comps = [
        _cmp("s21_pi_vs_t", s21_pi, s21_t,
             "attenuator_pi 网络 |S21|", "attenuator_t 网络 |S21|"),
        _cmp("s21_t_vs_bridged_t", s21_t, s21_bt,
             "attenuator_t 网络 |S21|", "attenuator_bridged_t 网络 |S21|"),
        _cmp("s21_vs_1_over_n", 1.0 / n, s21_pi,
             "1/N=10^(−A/20)（定义）", "attenuator_pi 网络 |S21|"),
        _cmp("s11_pi_zero", 0.0, s11_pi, "理想匹配 0",
             "attenuator_pi 网络 |S11|", mode="abs", tol=1.0e-4),
        _cmp("s11_t_zero", 0.0, s11_t, "理想匹配 0",
             "attenuator_t 网络 |S11|", mode="abs", tol=1.0e-4),
        _cmp("s11_bridged_t_zero", 0.0, s11_bt, "理想匹配 0",
             "attenuator_bridged_t 网络 |S11|", mode="abs", tol=1.0e-4),
    ]
    return comps, ev


def _ev_crlh_synth_analysis() -> tuple[list[QuantityComparison], dict[str, Any]]:
    """CRLH 平衡单元综合↔分析（超材料域，注册面声明的回判对）：
    synth(f0,Z0,C_L 种子)→四元 LC→report 分析键在 f0 处 f_se/f_sh 回代；
    Z_CRLH 在 f0 精确点为 0/0 数值奇异（report 出噪声值，不取）——取
    1.01·f0 处 √(L_R/C_R) 频率无关恒等对拍（平衡单元解析性质）。"""
    f0_ghz, z0_ohm = 5.0, 50.0
    s = _calc("crlh_balanced_synthesize", f0_ghz=f0_ghz, z0_ohm=z0_ohm,
              c_l_pf=1.0)
    rep = _calc("crlh_unit_cell_report", l_r_nh=s["l_r_nh"],
                c_l_pf=s["c_l_pf"], l_l_nh=s["l_l_nh"],
                c_r_pf=s["c_r_pf"], f_ghz=f0_ghz)
    rep_off = _calc("crlh_unit_cell_report", l_r_nh=s["l_r_nh"],
                    c_l_pf=s["c_l_pf"], l_l_nh=s["l_l_nh"],
                    c_r_pf=s["c_r_pf"], f_ghz=1.01 * f0_ghz)
    ev = {"inputs": {"f0_ghz": f0_ghz, "z0_ohm": z0_ohm, "c_l_pf": 1.0},
          "outputs": {"synthesis": s, "report_at_f0": {
              k: rep[k] for k in ("f_se_hz", "f_sh_hz", "balance_ratio")},
              "report_at_1.01f0": {"z_crlh_abs_ohm":
                                   rep_off["z_crlh_abs_ohm"]}}}
    comps = [
        _cmp("f_se_ghz", f0_ghz, rep["f_se_hz"] / 1.0e9,
             "crlh_balanced_synthesize.f0_ghz",
             "crlh_unit_cell_report.f_se_hz（回 f0）", tol=1.0e-9),
        _cmp("f_sh_ghz", f0_ghz, rep["f_sh_hz"] / 1.0e9,
             "crlh_balanced_synthesize.f0_ghz",
             "crlh_unit_cell_report.f_sh_hz（回 f0）", tol=1.0e-9),
        _cmp("balance_ratio", 1.0, rep["balance_ratio"],
             "平衡条件恒等 1.0", "crlh_unit_cell_report.balance_ratio",
             tol=1.0e-9),
        _cmp("z_crlh_off_f0_ohm", z0_ohm, rep_off["z_crlh_abs_ohm"],
             "crlh_balanced_synthesize.z0_ohm",
             "crlh_unit_cell_report.z_crlh_abs_ohm@1.01·f0（√(L_R/C_R) "
             "频率无关恒等）", tol=1.0e-9),
    ]
    return comps, ev


# ═══ 配对注册表（新增对=在下方加一个注册块）═══════════════════════════════

CROSS_PAIR_REGISTRY: dict[str, CrossPair] = {}


def _register(pair: CrossPair) -> None:
    if pair.pair_id in CROSS_PAIR_REGISTRY:  # pragma: no cover - 防御
        raise ValueError(f"交叉验证配对重名注册: {pair.pair_id}")
    CROSS_PAIR_REGISTRY[pair.pair_id] = pair


# ── A 类：正反解互逆 ────────────────────────────────────────────────────────
_register(CrossPair(
    "microstrip_synthesis_analysis", CATEGORY_INVERSE, "Z0/eps_eff",
    "微带：synthesis(z0=50)→w→analysis(w) 回代（skrf HJ 同模型）",
    rel_tol=1.0e-3,
    keys=("microstrip_synthesis", "microstrip_analysis"),
    evaluate=_ev_microstrip))
_register(CrossPair(
    "cpw_synthesis_analysis", CATEGORY_INVERSE, "Z0/eps_eff",
    "CPW：synthesis(z0=50)→w→analysis(w) 回代（skrf CPW 准静态）",
    rel_tol=1.0e-3,
    keys=("cpw_synthesis", "cpw_analysis"),
    evaluate=_ev_cpw))
_register(CrossPair(
    "cpwg_synthesis_analysis", CATEGORY_INVERSE, "Z0/eps_eff",
    "CPWG：synthesis(z0=50)→w→analysis(w) 回代（共形映射部分电容闭式）",
    rel_tol=1.0e-3,
    keys=("cpwg_synthesis", "cpwg_analysis"),
    evaluate=_ev_cpwg))
_register(CrossPair(
    "cps_synthesis_analysis", CATEGORY_INVERSE, "Z0/eps_eff",
    "CPS：synthesis(z0=80)→w→analysis(w) 回代（部分电容闭式+FD 定标）",
    rel_tol=1.0e-3,
    keys=("cps_synthesis", "cps_analysis"),
    evaluate=_ev_cps))
_register(CrossPair(
    "stripline_synthesis_analysis", CATEGORY_INVERSE, "Z0/eps_eff",
    "带状线：synthesis(z0=50)→w→analysis(w) 回代（零厚度椭圆积分闭式）",
    rel_tol=1.0e-3,
    keys=("stripline_synthesis", "stripline_analysis"),
    evaluate=_ev_stripline))
_register(CrossPair(
    "suspended_stripline_synthesis_analysis", CATEGORY_INVERSE, "Z0/eps_eff",
    "悬置带线：synthesis(z0=50)→w→analysis(w) 回代（softmin 定标闭式）",
    rel_tol=1.0e-3,
    keys=("suspended_stripline_synthesis", "suspended_stripline_analysis"),
    evaluate=_ev_suspended_stripline))
_register(CrossPair(
    "slotline_synthesis_analysis", CATEGORY_INVERSE, "Z0/eps_eff",
    "槽线：synthesis(z0=60)→w→analysis(w) 回代（Janaswamy-Schaubert 拟合式）",
    rel_tol=1.0e-3,
    keys=("slotline_synthesis", "slotline_analysis"),
    evaluate=_ev_slotline))
_register(CrossPair(
    "siw_synthesis_analysis", CATEGORY_INVERSE, "resonant_frequency",
    "SIW：synthesis(fc10=10)→w→analysis(w) 回代（Cassivi 等效宽度）",
    rel_tol=1.0e-4,
    keys=("siw_synthesis", "siw_analysis"),
    evaluate=_ev_siw))
_register(CrossPair(
    "dr_te01d_design_forward", CATEGORY_INVERSE, "resonant_frequency",
    "圆柱 DR TE01δ：design_size(f0=3.5)→(D,L)→cohn_f0 回代（超越方程正反）",
    rel_tol=1.0e-5,
    keys=("dr_te01d_design_size", "dr_te01d_cohn_f0"),
    evaluate=_ev_dr_te01d))
_register(CrossPair(
    "coax_z0_bidirectional_routes", CATEGORY_INVERSE, "Z0",
    "同轴 Z0 同键双路线：analyze(a,b)→Z0→synthesize(Z0,b)→a 回代",
    rel_tol=1.0e-9,
    keys=("coax_line_z0",),
    evaluate=_ev_coax_bidirectional))
_register(CrossPair(
    "t_match_design_impedance", CATEGORY_INVERSE, "matching",
    "T-match：design(目标 Rin=50)→T 棒长度→impedance(l') 回代 Re(Zin)",
    rel_tol=1.0e-6,
    keys=("t_match_design", "t_match_impedance"),
    evaluate=_ev_t_match))

# ── B 类：同物理量不同公式路径 ──────────────────────────────────────────────
_register(CrossPair(
    "microstrip_z0_eps_two_paths", CATEGORY_SAME_QUANTITY, "Z0/eps_eff",
    "微带 (Z0,εeff) 双路径：analysis(forward_z0 链) vs microstrip_lambda_g"
    "（直构 skrf MLine）",
    rel_tol=1.0e-9,
    keys=("microstrip_analysis", "microstrip_lambda_g"),
    evaluate=_ev_microstrip_two_paths))
_register(CrossPair(
    "cpw_cpwg_semiinfinite_limit", CATEGORY_SAME_QUANTITY, "Z0/eps_eff",
    "CPW(skrf) vs CPWG(共形映射) 厚基板半无限极限：两族公式收敛同一点",
    rel_tol=5.0e-4,
    keys=("cpw_analysis", "cpwg_analysis"),
    evaluate=_ev_cpw_cpwg_semiinfinite))
_register(CrossPair(
    "suspended_stripline_limit_stripline", CATEGORY_SAME_QUANTITY, "Z0/eps_eff",
    "悬置带线 h→b / h→0 双精确极限↔带状线闭式（同族回归锚）",
    rel_tol=1.0e-6,
    keys=("suspended_stripline_analysis", "stripline_analysis"),
    evaluate=_ev_ssl_limits))
_register(CrossPair(
    "coax_z0_convention_60_vs_exact", CATEGORY_SAME_QUANTITY, "Z0",
    "同轴 Z0 记号差：coax_line_z0（工程 60）vs coax_line_attenuation"
    "（精确 η0/2π）——已登记发现（源码 note 在案）",
    rel_tol=1.0e-3,
    keys=("coax_line_z0", "coax_line_attenuation"),
    evaluate=_ev_coax_z0_convention))
_register(CrossPair(
    "coax_te11_cutoff_two_keys", CATEGORY_SAME_QUANTITY, "resonant_frequency",
    "TE11 截止双键同式双实现：coax_line_z0 vs coax_line_cutoff_attenuator",
    rel_tol=1.0e-9,
    keys=("coax_line_z0", "coax_line_cutoff_attenuator"),
    evaluate=_ev_coax_te11_two_keys))
_register(CrossPair(
    "wg_te10_params_two_keys", CATEGORY_SAME_QUANTITY, "propagation",
    "矩形波导 TE10 (fc,λg,β) 双键双实现：waveguide_lambda_g vs "
    "wg_te10_attenuation",
    rel_tol=1.0e-9,
    keys=("waveguide_lambda_g", "wg_te10_attenuation"),
    evaluate=_ev_te10_two_keys))
_register(CrossPair(
    "range_resolution_fmcw_vs_pulse_compression", CATEGORY_SAME_QUANTITY,
    "radar_resolution",
    "ΔR=c/(2B) 双键：fmcw_bandwidth_range_resolution vs "
    "pulse_compression_design",
    rel_tol=1.0e-12,
    keys=("fmcw_bandwidth_range_resolution", "pulse_compression_design"),
    evaluate=_ev_range_resolution))
_register(CrossPair(
    "plasma_frequency_two_keys", CATEGORY_SAME_QUANTITY, "propagation",
    "电离层 f_p 双键（critical_frequency vs ionospheric_plasma_frequency）"
    "+n² 恒等式交叉",
    rel_tol=1.0e-9,
    keys=("critical_frequency", "ionospheric_plasma_frequency"),
    evaluate=_ev_plasma_frequency))
_register(CrossPair(
    "combline_c0_limit_quarter_wave_cavity", CATEGORY_SAME_QUANTITY,
    "resonant_frequency",
    "combline C→0 极限↔λ/4 同轴腔——有限 C arctan 尾差已登记发现",
    rel_tol=1.0e-4,
    keys=("combline_resonance", "coaxial_cavity_resonance"),
    evaluate=_ev_combline_c0_limit))
_register(CrossPair(
    "quarter_wave_length_vs_microstrip_lambda_g", CATEGORY_SAME_QUANTITY,
    "resonant_frequency",
    "λ/4 变换器长度↔微带 λg/4（λg 公式与光速常量跨键一致）",
    rel_tol=5.0e-4,
    keys=("quarter_wave_transformer", "microstrip_synthesis"),
    evaluate=_ev_quarter_wave_length))
_register(CrossPair(
    "chebyshev_prototype_vs_refl_fn", CATEGORY_SAME_QUANTITY,
    "filter_prototype",
    "切比雪夫原型 ε 常数↔反射函数带边纹波（|S11|@Ω=1=ε/√(1+ε²)=−RL 定义）",
    rel_tol=1.0e-6,
    keys=("chebyshev_prototype", "chebyshev_refl_fn"),
    evaluate=_ev_chebyshev_ripple))
_register(CrossPair(
    "vswr_convert_self_roundtrip", CATEGORY_SAME_QUANTITY, "matching",
    "驻波换算自逆往返：RL→VSWR→RL 与 RL→|Γ|→|Γ|（单键三入口互逆）",
    rel_tol=1.0e-3,
    keys=("vswr_convert",),
    evaluate=_ev_vswr_roundtrip))
_register(CrossPair(
    "attenuator_pi_t_bridged_t_topologies", CATEGORY_SAME_QUANTITY,
    "attenuation",
    "π/T/桥 T 衰减器三拓扑同衰减：三闭式路径电阻值→网络 |S21| 同值、"
    "|S11|≈0（ABCD/Y 矩阵测试侧裁判）",
    rel_tol=1.0e-4,
    keys=("attenuator_pi", "attenuator_t", "attenuator_bridged_t"),
    evaluate=_ev_attenuator_topologies))
_register(CrossPair(
    "crlh_balanced_synthesis_analysis", CATEGORY_INVERSE, "metamaterial",
    "CRLH 平衡单元：synth(f0,Z0,C_L)→四元 LC→report 分析键回判（f_se/f_sh"
    "回 f0 + Z_CRLH=√(L_R/C_R) 恒等；f0 精确点 0/0 奇异不取）",
    rel_tol=1.0e-9,
    keys=("crlh_balanced_synthesize", "crlh_unit_cell_report"),
    evaluate=_ev_crlh_synth_analysis))


# ═══ 框架运行器（通用，不因新增对改动）═════════════════════════════════════

def _fmt_evidence(evidence: dict[str, Any]) -> str:
    lines: list[str] = []
    for name, payload in evidence.items():
        lines.append(f"  {name}: {payload!r}")
    return "\n".join(lines)


@pytest.mark.parametrize("pair_id", sorted(CROSS_PAIR_REGISTRY))
def test_calc_cross_pair(pair_id: str) -> None:
    """逐注册对执行跨键对拍：全部比较量偏差 ≤ 容差。

    失败即**发现**（审查面不修 src/）：消息带输入回显+两键输出+偏差+
    容差全证据，供发现登记。
    """
    pair = CROSS_PAIR_REGISTRY[pair_id]
    comps, evidence = pair.evaluate()
    assert comps, f"{pair_id}: 注册对无比较量（注册错误）"
    problems: list[str] = []
    for comp in comps:
        limit = _limit_of(pair, comp)
        dev = (abs(comp.value_a - comp.value_b) if comp.mode == "abs"
               else _rel_dev(comp.value_a, comp.value_b))
        if not (math.isfinite(dev) and dev <= limit):
            problems.append(
                f"  [{comp.quantity}] {comp.source_a}={comp.value_a!r} vs "
                f"{comp.source_b}={comp.value_b!r} → 偏差={dev:.6g} "
                f"> 容差={limit:.6g}（mode={comp.mode}）")
    assert not problems, (
        f"CALC 交叉验证不一致（发现登记，不修 src/）\n"
        f"pair={pair_id}（{pair.category}/{pair.domain}）\n"
        f"{pair.description}\n"
        + "\n".join(problems) + "\n证据：\n" + _fmt_evidence(evidence))


def test_cross_pair_registry_keys_exist() -> None:
    """注册对引用的全部 CALC 键必须真实存在（键改名即框架红，防静默失配）。"""
    known = set(CALCULATOR_REGISTRY.names(include_experimental=True))
    missing: list[str] = []
    for pair in CROSS_PAIR_REGISTRY.values():
        for key in pair.keys:
            if key not in known:
                missing.append(f"{pair.pair_id} → {key}")
    assert not missing, f"交叉验证配对引用了不存在的 CALC 键：{missing}"


def test_cross_pair_registry_wellformed() -> None:
    """注册表良构：类别封闭、容差为正、abs 比较量带容差、pair_id 唯一。"""
    assert len(CROSS_PAIR_REGISTRY) == len(
        {p.pair_id for p in CROSS_PAIR_REGISTRY.values()})
    for pair in CROSS_PAIR_REGISTRY.values():
        assert pair.category in _VALID_CATEGORIES, (
            f"{pair.pair_id}: 未知类别 {pair.category!r}")
        assert pair.rel_tol > 0.0, f"{pair.pair_id}: rel_tol 必须为正"
        assert callable(pair.evaluate), f"{pair.pair_id}: evaluate 不可调用"
        assert pair.description, f"{pair.pair_id}: 缺描述"
        comps, _ = pair.evaluate()
        assert comps, f"{pair.pair_id}: 无比较量"
        for comp in comps:
            if comp.mode == "abs":
                assert comp.tol is not None or pair.abs_tol is not None, (
                    f"{pair.pair_id}/{comp.quantity}: abs 比较量缺容差")
            else:
                assert not math.isnan(comp.value_a), (
                    f"{pair.pair_id}/{comp.quantity}: value_a=NaN")
                assert not math.isnan(comp.value_b), (
                    f"{pair.pair_id}/{comp.quantity}: value_b=NaN")


def test_cross_pair_registry_min_coverage() -> None:
    """覆盖棘轮：≥8 对且五域齐备（Z0/εeff/衰减/滤波器原型/谐振频率）——
    只收不放（对齐 WITHOUT_JSON 棘轮门语义），删对必显式改此门。"""
    assert len(CROSS_PAIR_REGISTRY) >= 8
    domains = {p.domain for p in CROSS_PAIR_REGISTRY.values()}
    for required in ("Z0", "eps_eff", "attenuation", "filter_prototype",
                     "resonant_frequency"):
        assert any(required in d for d in domains), (
            f"覆盖域缺失：{required}（现有域={sorted(domains)}）")
    cats = {p.category for p in CROSS_PAIR_REGISTRY.values()}
    assert cats == set(_VALID_CATEGORIES), (
        f"两类配对必须都在册（现有={sorted(cats)}）")


def test_cross_validation_findings_ledger() -> None:
    """发现台账：带 documented 注记的比较量=已登记发现，实测偏差必须落在
    登记带内（带外=登记失真，框架红）。台账非空守卫：登记面不得被清空。"""
    entries: list[str] = []
    problems: list[str] = []
    for pair in CROSS_PAIR_REGISTRY.values():
        comps, _ = pair.evaluate()
        for comp in comps:
            if not comp.documented:
                continue
            dev = _rel_dev(comp.value_a, comp.value_b)
            band = comp.documented_band
            assert band is not None, (
                f"{pair.pair_id}/{comp.quantity}: documented 发现缺登记带")
            ok = band[0] <= dev <= band[1]
            entry = (f"  {pair.pair_id}/{comp.quantity}: 实测偏差="
                     f"{dev:.3e} 登记带=[{band[0]:.1e}, {band[1]:.1e}] "
                     f"{'OK' if ok else '带外!'}\n    注记：{comp.documented}")
            entries.append(entry)
            if not ok:
                problems.append(entry)
    assert entries, "发现台账为空——登记面被清空（审计面不得静默收缩）"
    assert not problems, "已登记发现偏差落带外（登记失真）：\n" + "\n".join(
        problems)
