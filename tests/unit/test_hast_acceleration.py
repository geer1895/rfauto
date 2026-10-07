"""MP-6 HAST 加速因子换算测试（锚树预声明，#122 判据先行）。

每件 ≥2 独立基准（出处见 core/hast_acceleration.py 模块 docstring）：

- Arrhenius 通道：① 消费恒等式——°C 薄壳与 core/aging.arrhenius_af K
  口径逐位一致（禁改消费互证）；② 合成回收锚（Ea=0.7 eV、85→110 °C
  手算 exp 值，#118）；③ 同温 → AF=1 逐位。
- Peck 湿度通道：① 幂律缩放恒等式（RH_s/RH_u=2、n=2.7 → 2^2.7）；
  ② n=1 退化为线性比值；③ 域守卫（RH>100、n≤0）。
- Hallberg-Peck 组合：① 同温同湿 AF=1 逐位；② 分通道乘积=总 AF
  （构造恒等）；③ 应力域单调性（RH_s↑ → AF↑）。
- 反解：round-trip 恒等（反解 RH_s 回代 == 目标 AF）+ 不可达目标
  守卫（RH_s>100 拒绝）+ AF_T≤1 无解域守卫。
- 等效时长：1000 h×AF 线性恒等；**边界**（不产寿命结论）——模块无
  life/mttf 命名导出（结构性守卫，grep 面）。
- 条件表报告：A110/A118 同条件互证、A101 85/85、source_b 如实
  retrieval_pending（不冒充双源）。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.aging import arrhenius_af
from rfauto.core.hast_acceleration import (
    PECK_N_REGISTERED_BAND,
    equivalent_stress_hours,
    hallberg_peck_af,
    hast_conditions_report,
    peck_humidity_factor,
    stress_rh_for_target_af,
)

# ─── Arrhenius 通道 ──────────────────────────────────────────────────────────


def test_arrhenius_c_shell_matches_aging_kernel_bitwise() -> None:
    from rfauto.core.hast_acceleration import arrhenius_af_c
    ea = 0.7
    assert arrhenius_af_c(ea, 85.0, 110.0) == pytest.approx(
        arrhenius_af(ea, 85.0 + 273.15, 110.0 + 273.15), rel=1e-15)
    # 同温 → AF=1 逐位（0.0 值偏移合法性，#364④）
    assert arrhenius_af_c(ea, 85.0, 85.0) == 1.0
    with pytest.raises(ValueError):
        arrhenius_af_c(ea, -300.0, 110.0)


def test_arrhenius_synthetic_recall() -> None:
    from rfauto.core.hast_acceleration import arrhenius_af_c
    tu, ts = 85.0 + 273.15, 110.0 + 273.15
    expected = math.exp(0.7 / 8.617333262e-5 * (1.0 / tu - 1.0 / ts))
    assert arrhenius_af_c(0.7, 85.0, 110.0) == pytest.approx(expected, rel=1e-12)
    # 手算量级锚：exp[8124.9×0.00018218]=exp(1.4802)=4.3925（内核与
    # 手算公式一致即判据；不作记忆带断言——#df6-⑨ 防记忆值腐坏）
    assert arrhenius_af_c(0.7, 85.0, 110.0) == pytest.approx(4.3925, rel=1e-3)


# ─── Peck 湿度通道 ───────────────────────────────────────────────────────────


def test_peck_power_law_identity_and_guards() -> None:
    assert peck_humidity_factor(85.0, 100.0, 2.7) == pytest.approx(
        (100.0 / 85.0) ** 2.7, rel=1e-15)
    # n=1 线性退化
    assert peck_humidity_factor(50.0, 100.0, 1.0) == pytest.approx(2.0, rel=1e-15)
    # 应力湿=使用湿 → 1 逐位
    assert peck_humidity_factor(85.0, 85.0, 2.7) == 1.0
    with pytest.raises(ValueError):
        peck_humidity_factor(85.0, 101.0, 2.7)
    with pytest.raises(ValueError):
        peck_humidity_factor(85.0, 100.0, 0.0)


# ─── Hallberg-Peck 组合 ──────────────────────────────────────────────────────


def test_hallberg_peck_identity_and_monotonicity() -> None:
    af = hallberg_peck_af(0.7, 85.0, 85.0, 85.0, 85.0, 2.7)
    # 同温同湿 → AF=1 逐位
    assert af["af_total"] == 1.0
    # 分通道乘积=总 AF（构造恒等）
    af2 = hallberg_peck_af(0.7, 85.0, 110.0, 85.0, 100.0, 2.7)
    assert af2["af_total"] == pytest.approx(
        af2["af_temperature"] * af2["af_humidity"], rel=1e-15)
    # 应力域单调
    af3 = hallberg_peck_af(0.7, 85.0, 110.0, 85.0, 100.0, 3.0)
    assert af3["af_total"] > af2["af_total"]
    # n 登记带在场且无发明缺省（UNVERIFIED band 只作指针）
    assert PECK_N_REGISTERED_BAND == (2.5, 3.0)
    assert af2["peck_n_status"] == "UNVERIFIED_band"
    assert af2["peck_n"] == 2.7  # 调用方显式供给值回显


# ─── 反解与等效时长 ──────────────────────────────────────────────────────────


def test_stress_rh_roundtrip_and_guards() -> None:
    # 可达目标：AF_max(RH_s=100)=4.3925×(100/85)^2.7≈8.30，取 6.0
    target = 6.0
    rh_s = stress_rh_for_target_af(0.7, 85.0, 110.0, 85.0, target, 2.7)
    assert 85.0 < rh_s <= 100.0
    # round-trip 恒等：反解值回代 == 目标 AF
    af = hallberg_peck_af(0.7, 85.0, 110.0, 85.0, rh_s, 2.7)
    assert af["af_total"] == pytest.approx(target, rel=1e-12)
    # 不可达目标（RH_s 需 >100）守卫
    with pytest.raises(ValueError, match="不可达"):
        stress_rh_for_target_af(0.7, 85.0, 110.0, 85.0, 100.0, 2.7)
    # 应力温度不构成加速 → 无解域守卫
    with pytest.raises(ValueError, match="无解域"):
        stress_rh_for_target_af(0.7, 110.0, 85.0, 85.0, 10.0, 2.7)


def test_equivalent_stress_hours_linear_identity() -> None:
    assert equivalent_stress_hours(1000.0, 46.0) == pytest.approx(46000.0, rel=1e-15)
    with pytest.raises(ValueError):
        equivalent_stress_hours(0.0, 46.0)


def test_no_life_conclusion_export_structural_guard() -> None:
    # 边界守卫（environment_tables.life_from_condition 同款）：本模块
    # 不得导出任何寿命/MTTF 命名入口（结构性检查，非 grep 脆弱面）
    import rfauto.core.hast_acceleration as mod
    exported = [name for name in dir(mod) if not name.startswith("_")]
    forbidden = ("life", "mttf", "reliability", "failure_rate", "fit_rate")
    hits = [name for name in exported
            if any(word in name.lower() for word in forbidden)]
    assert hits == []


# ─── 条件表报告 ──────────────────────────────────────────────────────────────


def test_hast_conditions_report_honesty() -> None:
    report = hast_conditions_report()
    conds = report["conditions"]
    assert conds["hast_unbiased_jesd22_a110"]["temperature_c"] == 110.0
    assert conds["hast_unbiased_jesd22_a110"]["relative_humidity_percent"] == 85.0
    assert conds["hast_unbiased_jesd22_a110"]["source_a"] == \
        "in_repo_environment_tables_merged"
    # source_b 如实 retrieval_pending（不冒充双源）
    assert conds["hast_unbiased_jesd22_a110"]["source_b_status"] == \
        "NO_VALUE_retrieval_pending"
    assert report["internal_consistency_checks"]["a110_a118_same_conditions"] is True
    assert report["internal_consistency_checks"]["a101_85_85"] is True
    assert "不冒充双源收敛" in report["dual_source_honesty_note"]
