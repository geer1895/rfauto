"""MP-4 电迁移-场联动内核单测（core/electromigration.py，round15 :86）。

裁判 = 外部独立来源（#118：不是被测实现的自我推导）：
  * Black MTTF 手算回收：A=1e5 h·(A/cm²)²、J=1e6 A/cm²、n=2、Ea=0.7 eV、
    T=85 °C → Ea/kT=0.7/(8.617333262e-5·358.15)=22.6809、
    e^22.6809=7.0825e9、A·J⁻²=1e-7 → MTTF=708.25 h（Black 1969 IEEE T-ED
    口径；J 单位与 A 标定一致的单位无关性由本例钉）；
  * Arrhenius AF 交叉恒等式：AF(55→85 °C, Ea=0.7) 手算 e^(8123.16·
    2.55259e-4)=e^2.07365≈7.9536（实现 7.9528，手算 1e-4 带内）且
    MTTF(T_use)/MTTF(T_stress) == AF（aging.arrhenius_af 独立函数）；
  * 局部 J 手算：J=sqrt(1e9/1.724e-8)=2.4084e8 A/m²（≈2.41 MA/cm²，互连
    工程典型带）+ 铜 TCR 链 ρ(85 °C)=1.724e-8·(1+3.93e-3·65)=2.1644e-8；
  * Blech 临界积独立推导：Ω=摩尔体积 7.11e-6 m³/mol ÷ N_A（N_A=SI 2019
    精确值 6.02214076e23），Cu Δσ=50 MPa → (jL)_c≈2.137e5 A/m≈2.14e3
    A/cm——与文献通引「Cu Blech product ~2000 A/cm」工程带吻合
    （I. A. Blech, J. Appl. Phys. 47, 1203 (1976) 闭式）；
  * Foster 热链（MP-1 消费面）：稳态 ΔT=P·ΣR=60 °C（能量守恒锚）+
    t=1 s 瞬态手算 2·[10(1−e⁻¹)+20(1−e⁻⁰·⁰¹)]=13.0404 °C；
  * IPC-2152 ΔT 联合：已注册键 ipc2152_trace_temp_rise 输出 delta_t_c
    经 temperature_c 注入的组合链演示（联合口径=服务级组合）。

确定性：无网络、无真机、无文件 IO、无随机。
"""

from __future__ import annotations

import pytest

from rfauto.core.electromigration import (
    COPPER_ATOMIC_VOLUME_M3,
    blech_check,
    blech_critical_product,
    em_mttf_check,
    local_current_density,
    resistivity_at,
)
from rfauto.service.calculator_service import run_calculator

K_B_EV_PER_K = 8.617333262e-5  # aging 同源常数（仅本文件手算注释用）
NA_MOL = 6.02214076e23         # SI 2019 精确值
CU_RHO_20C = 1.724e-8          # Ω·m（IACS 100% 退火铜）
CU_TCR = 3.93e-3               # 1/K @ 20 °C

_BLACK = dict(a_black=1.0e5, n_black=2.0, ea_ev=0.7)


# ---------------------------------------------------------------- 局部 J 面


class TestLocalCurrentDensity:
    """场→局部 J：手算锚 + TCR 链 + 往返恒等式 + 域守卫。"""

    def test_hand_anchor_no_tcr(self) -> None:
        # J = sqrt(1e9/1.724e-8) = sqrt(5.800464e16) = 2.4084e8 A/m²
        j = local_current_density(1e9, 293.15, CU_RHO_20C)
        assert j == pytest.approx(2.4084e8, rel=1e-4)
        # 互连工程典型带（~0.1–2 MA/cm² 量级语境）
        assert 2.0e4 <= j * 1e-4 <= 5.0e4  # A/cm²

    def test_tcr_chain_85c(self) -> None:
        # ρ(85 °C) = 1.724e-8·(1+3.93e-3·65) = 2.16440e-8（手算）
        rho85 = resistivity_at(CU_RHO_20C, 273.15 + 85.0, CU_TCR, 20.0)
        assert rho85 == pytest.approx(2.16440e-8, rel=1e-4)
        # J(85 °C) = sqrt(1e9/2.16440e-8) = 2.1495e8（热胀电阻率 → J 降）
        j85 = local_current_density(1e9, 273.15 + 85.0, CU_RHO_20C,
                                    tcr_per_k=CU_TCR, t_ref_c=20.0)
        assert j85 == pytest.approx(2.1495e8, rel=1e-4)
        assert j85 < local_current_density(1e9, 293.15, CU_RHO_20C)

    def test_joule_roundtrip_identity(self) -> None:
        # q → J → q 往返恒等式（ρ·J² 还原原损耗密度）
        q0 = 3.7e8
        j = local_current_density(q0, 350.0, CU_RHO_20C)
        assert CU_RHO_20C * j * j == pytest.approx(q0, rel=1e-15)

    def test_domain_guards(self) -> None:
        with pytest.raises(ValueError, match=">0"):
            local_current_density(0.0, 300.0, CU_RHO_20C)
        with pytest.raises(ValueError, match=">0"):
            local_current_density(1e9, 300.0, -1e-8)
        # TCR 外推到非物理负电阻率显式拒绝（线性模型定义域）
        with pytest.raises(ValueError, match="非正"):
            resistivity_at(CU_RHO_20C, 100.0, 1.0, 20.0)  # 1+1·(100−293)<0


# ---------------------------------------------------------------- Black 面


class TestBlackChain:
    """Black MTTF（消费 aging）：手算回收 + AF 恒等式 + 单调性 + 域守卫。"""

    def test_black_hand_recovery_via_em_mttf_check(self) -> None:
        # J 与 A 同标定单位（A/cm² 口径）：MTTF = 1e5·(1e6)^-2·e^22.6809
        # = 1e-7·7.0825e9 = 708.25 h（手算）
        r = em_mttf_check(j_density_a_per_m2=1.0e6,
                          temperature_c=85.0, **_BLACK)
        assert r["mttf"] == pytest.approx(708.25, rel=1e-3)
        assert r["route_j"] == "direct" and r["route_t"] == "direct"

    def test_af_hand_and_mttf_ratio_identity(self) -> None:
        # AF(55→85 °C, Ea=0.7)：(1/328.15−1/358.15)=2.55259e-4、
        # Ea/k=8123.16 → exp(2.07365)≈7.9536（手算 1e-4 带内）
        r = em_mttf_check(j_density_a_per_m2=1.0e6, temperature_c=85.0,
                          t_ref_af_c=55.0, **_BLACK)
        assert r["af"] == pytest.approx(7.9528, rel=1e-3)
        # 恒等式：mttf_at_ref = mttf·AF（round 12 位绝对舍入 → rel 1e-6 门）
        assert r["mttf_at_ref"] == pytest.approx(
            r["mttf"] * r["af"], rel=1e-6)
        # MTTF(55 °C) 手算：1e-7·e^(0.7/(k·328.15)) = 1e-7·5.63261e10
        # = 5632.6 h（AF 交叉验证的同源独立值）
        assert r["mttf_at_ref"] == pytest.approx(5632.6, rel=1e-3)

    def test_mttf_monotone_in_j_and_t(self) -> None:
        mttf = lambda j, t: em_mttf_check(  # noqa: E731
            j_density_a_per_m2=j, temperature_c=t, **_BLACK)["mttf"]
        assert mttf(1e9, 85.0) > mttf(2e9, 85.0)  # J 升 → MTTF 降（n>0）
        assert mttf(1e9, 85.0) > mttf(1e9, 125.0)  # T 升 → MTTF 降（Ea>0）

    def test_domain_guards(self) -> None:
        with pytest.raises(ValueError, match="二选一"):
            em_mttf_check(temperature_c=85.0, **_BLACK)  # J 无源
        with pytest.raises(ValueError, match="二选一"):
            em_mttf_check(loss_density_w_per_m3=1e9, j_density_a_per_m2=1e10,
                          resistivity_ohm_m=CU_RHO_20C,
                          temperature_c=85.0, **_BLACK)  # J 双源
        with pytest.raises(ValueError, match=">0"):
            em_mttf_check(loss_density_w_per_m3=0.0,
                          resistivity_ohm_m=CU_RHO_20C,
                          temperature_c=85.0, **_BLACK)  # q≤0
        with pytest.raises(ValueError, match="a_black"):
            em_mttf_check(j_density_a_per_m2=1e10, temperature_c=85.0,
                          ea_ev=0.7)  # 缺 a_black
        with pytest.raises(ValueError, match="ea_ev"):
            em_mttf_check(j_density_a_per_m2=1e10, temperature_c=85.0,
                          a_black=1e5)  # 缺 ea_ev
        with pytest.raises(ValueError, match="绝对零度"):
            em_mttf_check(j_density_a_per_m2=1e10, temperature_c=-300.0,
                          **_BLACK)
        with pytest.raises(ValueError, match="二选一"):
            em_mttf_check(j_density_a_per_m2=1e10, temperature_c=85.0,
                          zth_r_c_per_w=[10.0], zth_tau_s=[1.0],
                          power_w=1.0, **_BLACK)  # T 双源
        with pytest.raises(ValueError, match="三参数必须同给"):
            em_mttf_check(j_density_a_per_m2=1e10, zth_r_c_per_w=[10.0],
                          **_BLACK)  # T 半源


# ---------------------------------------------------------------- Blech 面


class TestBlech:
    """Blech 长度效应：独立推导 + 文献带 + 双向判 + Δσ 线性 + 守卫。"""

    def test_critical_product_independent_derivation(self) -> None:
        # Ω 从摩尔体积独立推（7.11e-6 m³/mol ÷ N_A），闭式手算链
        omega = 7.11e-6 / NA_MOL
        assert omega == pytest.approx(COPPER_ATOMIC_VOLUME_M3, rel=1e-4)
        jl_c = blech_critical_product(50e6, omega, 1.0, CU_RHO_20C)
        # 手算：5.9032e-22/2.7622e-27 = 2.137e5 A/m = 2137 A/cm
        assert jl_c == pytest.approx(2.137e5, rel=1e-3)
        # 文献通引「Cu Blech product ~2000 A/cm」带（Δσ=50 MPa 量级假设）
        assert 2000.0 <= jl_c * 0.01 <= 2500.0

    def test_sigma_linearity_and_zstar_abs(self) -> None:
        base = blech_critical_product(50e6, COPPER_ATOMIC_VOLUME_M3, 1.0,
                                      CU_RHO_20C)
        # 判据对 Δσ 线性（100 MPa 翻倍——文档声明的敏感度口径由本例钉）
        assert blech_critical_product(
            100e6, COPPER_ATOMIC_VOLUME_M3, 1.0, CU_RHO_20C) == \
            pytest.approx(2.0 * base, rel=1e-15)
        # |Z*| 口径：±2 同值、且 = Z*=1 的一半
        assert blech_critical_product(50e6, COPPER_ATOMIC_VOLUME_M3, -2.0,
                                      CU_RHO_20C) == \
            blech_critical_product(50e6, COPPER_ATOMIC_VOLUME_M3, 2.0,
                                   CU_RHO_20C)
        assert blech_critical_product(50e6, COPPER_ATOMIC_VOLUME_M3, 2.0,
                                      CU_RHO_20C) == \
            pytest.approx(0.5 * base, rel=1e-15)

    def test_immortal_and_mortal_verdicts(self) -> None:
        jl_c = blech_critical_product(50e6, COPPER_ATOMIC_VOLUME_M3, 1.0,
                                      CU_RHO_20C)
        immortal = blech_check(1e9, 10e-6, 50e6, COPPER_ATOMIC_VOLUME_M3,
                               1.0, CU_RHO_20C)
        assert immortal["jl_a_per_m"] == pytest.approx(1.0e4, rel=1e-15)
        assert immortal["immortal"] is True
        assert immortal["margin"] == pytest.approx(jl_c / 1.0e4, rel=1e-9)
        mortal = blech_check(1e10, 100e-6, 50e6, COPPER_ATOMIC_VOLUME_M3,
                             1.0, CU_RHO_20C)
        assert mortal["jl_a_per_m"] == pytest.approx(1.0e6, rel=1e-15)
        assert mortal["immortal"] is False
        assert mortal["margin"] == pytest.approx(jl_c / 1.0e6, rel=1e-9)
        assert mortal["margin"] < 1.0 <= immortal["margin"]

    def test_zero_sigma_never_immortal(self) -> None:
        # Δσ=0 → 临界积 0 → 永不 immortal（判据极限语义）
        out = blech_check(1e8, 1e-6, 0.0, COPPER_ATOMIC_VOLUME_M3, 1.0,
                          CU_RHO_20C)
        assert out["jl_critical_a_per_m"] == 0.0
        assert out["immortal"] is False

    def test_domain_guards(self) -> None:
        with pytest.raises(ValueError, match="非零"):
            blech_critical_product(50e6, COPPER_ATOMIC_VOLUME_M3, 0.0,
                                   CU_RHO_20C)
        with pytest.raises(ValueError, match=">0"):
            blech_check(0.0, 10e-6, 50e6, COPPER_ATOMIC_VOLUME_M3, 1.0,
                        CU_RHO_20C)
        with pytest.raises(ValueError, match=">0"):
            blech_check(1e9, 0.0, 50e6, COPPER_ATOMIC_VOLUME_M3, 1.0,
                        CU_RHO_20C)


# ------------------------------------------------- 联合报告（场→J→T→MTTF）


class TestEmMttfCheck:
    """联合报告路由：loss 反演、Foster 热链（稳态/瞬态）、Blech 嵌入。"""

    def test_loss_density_route_matches_core(self) -> None:
        r = em_mttf_check(loss_density_w_per_m3=1e9,
                          resistivity_ohm_m=CU_RHO_20C, tcr_per_k=CU_TCR,
                          temperature_c=85.0, **_BLACK)
        assert r["route_j"] == "loss_density"
        assert r["j_density_a_per_m2"] == local_current_density(
            1e9, 273.15 + 85.0, CU_RHO_20C, tcr_per_k=CU_TCR)
        assert r["resistivity_ohm_m"] == pytest.approx(2.16440e-8, rel=1e-4)

    def test_zth_steady_energy_conservation(self) -> None:
        # 稳态 ΔT = P·ΣR = 2·(10+20) = 60 °C → Tj = 25+60 = 85 °C（守恒锚）
        r = em_mttf_check(loss_density_w_per_m3=1e9,
                          resistivity_ohm_m=CU_RHO_20C,
                          zth_r_c_per_w=[10.0, 20.0],
                          zth_tau_s=[1.0, 100.0], power_w=2.0, **_BLACK)
        assert r["route_t"] == "thermal_transient_steady"
        assert r["delta_t_c"] == pytest.approx(60.0, rel=1e-12)
        assert r["temperature_c"] == pytest.approx(85.0, rel=1e-12)

    def test_zth_transient_hand_anchor(self) -> None:
        # t=1 s：ΔT = 2·[10(1−e⁻¹)+20(1−e⁻⁰·⁰¹)] = 2·6.5202068 = 13.0404 °C
        r = em_mttf_check(loss_density_w_per_m3=1e9,
                          resistivity_ohm_m=CU_RHO_20C,
                          zth_r_c_per_w=[10.0, 20.0],
                          zth_tau_s=[1.0, 100.0], power_w=2.0, time_s=1.0,
                          **_BLACK)
        assert r["route_t"] == "thermal_transient_transient"
        assert r["delta_t_c"] == pytest.approx(13.0404, rel=1e-4)
        assert r["temperature_c"] == pytest.approx(38.0404, rel=1e-4)

    def test_blech_embed_matches_standalone(self) -> None:
        r = em_mttf_check(j_density_a_per_m2=1e10, temperature_c=85.0,
                          resistivity_ohm_m=CU_RHO_20C,
                          segment_length_m=1e-4, delta_sigma_pa=50e6,
                          **_BLACK)
        assert r["blech"] == blech_check(1e10, 1e-4, 50e6,
                                         COPPER_ATOMIC_VOLUME_M3, 1.0,
                                         CU_RHO_20C)

    def test_blech_route_guards(self) -> None:
        with pytest.raises(ValueError, match="resistivity_ohm_m"):
            em_mttf_check(j_density_a_per_m2=1e10, temperature_c=85.0,
                          segment_length_m=1e-4, delta_sigma_pa=50e6,
                          **_BLACK)  # direct 路缺 ρ
        with pytest.raises(ValueError, match="delta_sigma_pa"):
            em_mttf_check(j_density_a_per_m2=1e10, temperature_c=85.0,
                          resistivity_ohm_m=CU_RHO_20C,
                          segment_length_m=1e-4, **_BLACK)  # 缺 Δσ


# ------------------------------------------------- 注册面 + IPC-2152 联合


class TestRegisteredShellAndIpc2152Joint:
    """注册键薄壳 + IPC-2152 ΔT 联合（组合链演示，round15 :86 联合口径）。"""

    def test_registered_key_matches_core(self) -> None:
        params = {
            "loss_density_w_per_m3": 1.0e9,
            "resistivity_ohm_m": CU_RHO_20C,
            "a_black": 1.0e5,
            "ea_ev": 0.7,
            "temperature_c": 85.0,
        }
        out = run_calculator("electromigration_mttf_check", params)
        assert out["ok"] is True, out
        core = em_mttf_check(loss_density_w_per_m3=1e9,
                             resistivity_ohm_m=CU_RHO_20C,
                             temperature_c=85.0, **_BLACK)
        assert out["result"] == core
        # 名义点：J≈2.41 MA/cm²、MTTF≈0.0122 h（physics_invariants 输入表）
        assert out["result"]["j_density_a_per_cm2"] == pytest.approx(
            2.4084e4, rel=1e-4)
        assert out["result"]["mttf"] == pytest.approx(0.012210, rel=1e-3)

    def test_ipc2152_delta_t_joint_chain(self) -> None:
        # 联合链：ipc2152_trace_temp_rise（Brooks & Adam 拟合）→ ΔT 注入
        # temperature_c=ambient+ΔT → Black MTTF（规格「IPC-2152 ΔT 联合」）
        ipc = run_calculator("ipc2152_trace_temp_rise", {
            "width_mm": 2.0, "copper_oz": 1.0, "current_a": 3.0,
            "internal": False})
        assert ipc["ok"] is True
        delta_t = ipc["result"]["delta_t_c"]
        out = run_calculator("electromigration_mttf_check", {
            "j_density_a_per_m2": 1.0e10, "a_black": 1.0e5, "ea_ev": 0.7,
            "temperature_c": 25.0 + delta_t})
        assert out["ok"] is True, out
        assert out["result"]["temperature_c"] == pytest.approx(
            25.0 + delta_t, rel=1e-12)
        # 温度链单调性：ΔT 越大 → MTTF 越短（联合方向正确性）
        out_hot = run_calculator("electromigration_mttf_check", {
            "j_density_a_per_m2": 1.0e10, "a_black": 1.0e5, "ea_ev": 0.7,
            "temperature_c": 25.0 + delta_t + 20.0})
        assert out_hot["result"]["mttf"] < out["result"]["mttf"]

    def test_registered_domain_error(self) -> None:
        out = run_calculator("electromigration_mttf_check", {
            "loss_density_w_per_m3": 0.0, "resistivity_ohm_m": CU_RHO_20C,
            "a_black": 1.0e5, "ea_ev": 0.7})
        assert out["ok"] is False
        assert out.get("error")
