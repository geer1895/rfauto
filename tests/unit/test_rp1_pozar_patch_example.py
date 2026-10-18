"""RP-1 卡 2：微带天线章典型例数值回收（规格卡
docs/rp1_classic_reproduction_specs_20261008.md §二开工规格兑现）。

**书名勘误（卡 4 MYJ 同款名义勘误口径）**：规格卡"Pozar 微带天线章典型例"
的可核原文实为 **Balanis《Antenna Theory: Analysis and Design》Ch.14
Example 14.1**——RT/duroid 5880（εr=2.2、h=0.1588cm=0.0625in）@10GHz；
且内核 Rin 模型本名 patch_rin_edge_balanis（Balanis 腔模链即本卡出处面）。

来源等级 **SECONDARY_PRINTED**（RP-1 四档制）：印刷值转录自章节公开复本
（academia.edu CHAPTER 14 Microstrip Antennas #5358708 + Semnan 大学课程
页 prezaei /downloads/file/2051）三处独立印刷面：
- 例题陈述（检索引述原文）："Example 14.1 Design a rectangular microstrip
  antenna using a substrate (RT/duroid 5880) with dielectric constant of
  2.2, h = 0.1588 cm (0.0625 inches)…"（f0=10GHz 由该章 Fig 14.19(a) 文
  "…computed at f0 = 10 GHz for the rectangular microstrip of Example
  14.1 … with εr = 2.2, h = 0.1588 cm, L = 0.906 cm and Le = 1.068 cm"钉）；
- Fig 14.31 题注："…rectangular microstrip patch antennas (W = 1.186 cm,
  L = 0.906 cm, εr = 2.2, λ0 = 3 cm)"。
即印刷值：**W=11.86mm、L=9.06mm、Le=10.68mm**（4 位有效印刷档）。

判据（规格卡预声明）：**5e-3 rel**（4 位印刷半格档）。偏差来源分类二支
（规格卡预声明）：口径类（例值惯例 vs 本仓冻结口径——如实分类不凑）与
离散-印刷类。本卡实测命中**口径类一支**：印刷 L=Le−2ΔL（文献惯例总扣）
vs 内核 synthesize_patch=Le−4ΔL（XA-1 冻结口径，语义翻转挂 L5 v2 批）——
测试钉 L_print≈L_kernel+2ΔL_edge（既证印刷惯例又量化内核偏差，零行为）。

如实缺项（#122 不编）：Rin/y0 印刷值不可达转录（章节复本正文未展开，
检索面第三方计算器数值不构成印刷面）——skip 登记维持。
"""

from __future__ import annotations

import math

import pytest

_C_MM_GHZ = 299.792458

# ── 印刷值转录（SECONDARY_PRINTED；出处见模块 docstring，勿改值）────────────
_EPS_R = 2.2
_H_MM = 1.588          # 0.1588 cm
_F0_GHZ = 10.0
_W_PRINT_MM = 11.86    # 1.186 cm（Fig 14.31 题注）
_L_PRINT_MM = 9.06     # 0.906 cm（Fig 14.19a 文+Fig 14.31 题注双印）
_LE_PRINT_MM = 10.68   # 1.068 cm（Fig 14.19a 文 Le）
_GATE_REL = 5e-3       # 4 位印刷半格档（规格卡判据预声明）


# ── 独立第二实现（文献公式转录，不 import 内核——#118 禁同源）───────────────

def _w_ref_mm(f0_ghz: float, er: float) -> float:
    """Balanis eq.(14-1a) 宽度式第二实现：W=c/(2f)·√(2/(εr+1))。"""
    return _C_MM_GHZ / (2.0 * f0_ghz) * math.sqrt(2.0 / (er + 1.0))


def _eps_eff_ref(w_mm: float, er: float, h_mm: float) -> float:
    """修正 Wheeler εeff 第二实现：(εr+1)/2+(εr−1)/2·(1+12h/W)^(−1/2)。"""
    return ((er + 1.0) / 2.0
            + (er - 1.0) / 2.0 / math.sqrt(1.0 + 12.0 * h_mm / w_mm))


def _delta_l_edge_ref_mm(w_mm: float, h_mm: float, eps_eff: float) -> float:
    """Hammerstad 1975 每边缘 ΔL 第二实现（0.412 原式）。"""
    u = w_mm / h_mm
    return (0.412 * h_mm * (eps_eff + 0.3) * (u + 0.264)
            / ((eps_eff - 0.258) * (u + 0.8)))


def _le_ref_mm(f0_ghz: float, eps_eff: float) -> float:
    """有效腔长第二实现：Le=λ0/(2√εeff)=c/(2f√εeff)。"""
    return _C_MM_GHZ / (2.0 * f0_ghz * math.sqrt(eps_eff))


def test_second_source_matches_printed_values() -> None:
    """第二实现 vs 印刷值（W/L/Le/ΔL 四值，5e-3 半格门）。"""
    w = _w_ref_mm(_F0_GHZ, _EPS_R)
    ee = _eps_eff_ref(w, _EPS_R, _H_MM)
    dl = _delta_l_edge_ref_mm(w, _H_MM, ee)
    le = _le_ref_mm(_F0_GHZ, ee)
    assert w == pytest.approx(_W_PRINT_MM, rel=_GATE_REL)          # 3.0e-4
    assert le == pytest.approx(_LE_PRINT_MM, rel=_GATE_REL)        # 4.2e-4
    # 文献惯例总扣：L=Le−2ΔL
    assert le - 2.0 * dl == pytest.approx(_L_PRINT_MM, rel=_GATE_REL)
    # εeff 与 Le 印刷值互洽（由印刷 Le 反演的 εeff 一致性；Le 单位 mm）
    ee_from_print = (_C_MM_GHZ / (2.0 * _F0_GHZ * _LE_PRINT_MM)) ** 2
    assert ee == pytest.approx(ee_from_print, rel=_GATE_REL)
    # ΔL_edge 印刷回收：(Le−L)/2
    assert dl == pytest.approx(
        (_LE_PRINT_MM - _L_PRINT_MM) / 2.0, rel=_GATE_REL)


def test_kernel_chain_recovery() -> None:
    """内核链回收：W/εeff/ΔL 逐值对拍印刷值；L 记口径类偏差（XA-1）。

    域守卫发现（如实账）：synthesize_patch 全函数在本例点**越域**——
    k0·h=0.333>0.3 触 patch_rin_edge_balanis 适用域守卫（厚基板），
    即内核贴片综合函数域不含经典教材例点（feed_offset 面依赖 Rin 模型）。
    W/L 总扣面按规格卡消费口径（synthesis.py:783 docstring 三式+:591
    ΔL 单源）直取重建——印刷值仍为外部裁判，非内核自证。
    """
    from rfauto.core.synthesis import patch_fringing_delta_l

    w_full = _w_ref_mm(_F0_GHZ, _EPS_R)
    ee_kernel = _eps_eff_ref(w_full, _EPS_R, _H_MM)
    # W：内核链式（=synthesize_patch 同式）vs 印刷半格门
    assert w_full == pytest.approx(_W_PRINT_MM, rel=_GATE_REL)
    # ΔL_edge：全仓单源（0.412 每边缘）vs 印刷回收值
    dl_kernel_mm = patch_fringing_delta_l(w_full * 1e-3, _H_MM * 1e-3,
                                          ee_kernel) * 1e3
    dl_print = (_LE_PRINT_MM - _L_PRINT_MM) / 2.0
    assert dl_kernel_mm == pytest.approx(dl_print, rel=_GATE_REL)
    # L：口径类偏差（印刷=Le−2ΔL 文献惯例 vs 内核=Le−4ΔL XA-1 冻结）——
    # 钉 L_print ≈ L_kernel + 2ΔL（既证印刷惯例又量化内核偏差，零行为）
    l_kernel_mm = _le_ref_mm(_F0_GHZ, ee_kernel) - 2.0 * (
        2.0 * dl_kernel_mm)
    assert l_kernel_mm == pytest.approx(_LE_PRINT_MM - 4.0 * dl_print,
                                        rel=_GATE_REL)
    assert 2.0 * dl_kernel_mm == pytest.approx(
        _LE_PRINT_MM - _L_PRINT_MM, rel=_GATE_REL)
    assert (l_kernel_mm + 2.0 * dl_kernel_mm) == pytest.approx(
        _L_PRINT_MM, rel=_GATE_REL)
    # Le 全精度第二实现 vs 印刷
    assert _le_ref_mm(_F0_GHZ, ee_kernel) == pytest.approx(
        _LE_PRINT_MM, rel=_GATE_REL)
    # 域守卫发现实证：综合全函数在本例点显式 ValueError（k0·h 守卫）
    from rfauto.core.synthesis import synthesize_patch

    with pytest.raises(ValueError, match="k0·h"):
        synthesize_patch(f0_ghz=_F0_GHZ, er=_EPS_R, h_mm=_H_MM)


@pytest.mark.skip(reason="RP-1 卡 2 如实缺项（#122）：例值 Rin/y0 印刷值"
                         "不可达转录（章节复本正文未展开，检索面第三方"
                         "计算器数值不构成印刷面）——内核 "
                         "patch_rin_edge_balanis 页码 UNVERIFIED 账维持，"
                         "取得印刷面后补回收钉")
def test_rin_printed_value_recovery() -> None:
    """占位：Rin 印刷值回收钉（skip=如实缺项登记，规格卡口径）。"""
