"""EM-5 件①③ core/common_mode 单测（接地拓扑 λ/20 判据 + 浮地-机壳 CM 路径）。

锚树口径（#118：锚值独立复算/独立公式，不赌推导）：
- 接地判据恒等面：s < λ/20 ⟺ f < c/(20s)（严格不等号，扫描双判定一致）；
  已知值锚：f=100 MHz → λ=3 m → λ/20=0.15 m；等号点归 electrically_long。
- 平行板电容：C = ε0·εr·A/d（测试文件独立常数 ε0=8.854187817e-12）。
- CM 回路双路径：路径 A=V/|R+j(ωL−1/ωC)| vs 测试文件独立有理化式
  I=V·ωC/√((1−ω²LC)²+(ωRC)²)；f=0 → I=0（浮地隔直定义面）；谐振
  f0=1/(2π√(LC)) 处 I=V/R（损耗限幅恒等）；R=0 恰在谐振 → ValueError。
- 辐射链（件③的"接 I_CM 入口"）：模块 I_CM(µA) 喂
  emc_radiated.cm_radiated_field 后，E 场与测试文件独立 Ott 第一性式
  E=N·η·k·I·L/(4πd) 从模块返回 I 重算一致 ≤1e-12。
- 负例：bool 拒收（df7+⑯）、负值、c_f 与 area 二选一、er<1、f_mhz=0 判据。

物理数值全部出自闭式内核公式与测试文件独立复算，无手编数字（铁律 7）。
"""

from __future__ import annotations

import json
import math

import pytest

from rfauto.core.common_mode import (
    LAMBDA20,
    chassis_coupling_capacitance,
    cm_radiated_via_chassis,
    floating_ground_cm_current,
    ground_spacing_criteria,
    ground_spacing_criterion,
    grounding_critical_frequency_hz,
    max_ground_spacing_m,
)
from rfauto.core.emc_radiated import cm_radiated_field

# ── 测试文件内独立常数（#118：不 import 模块常数，避免同源自证）───────────────
C0 = 299792458.0
EPS0 = 8.854187817e-12
ETA = 120.0 * math.pi


def _ott_e_v_per_m(f_mhz: float, length_m: float, i_ua: float, d_m: float, image: bool) -> float:
    """第一性短偶极式（测试文件独立实现）：E = N·η·k·I·L/(4πd)。"""
    n_img = 2.0 if image else 1.0
    k_wave = 2.0 * math.pi * (f_mhz * 1e6) / C0
    return n_img * (ETA * k_wave * (i_ua * 1e-6) * length_m) / (4.0 * math.pi * d_m)


def _i_cm_path_b(f_mhz: float, v: float, c: float, l_h: float, r: float) -> float:
    """有理化恒等式（测试文件独立实现）：I = V·ωC/√((1−ω²LC)²+(ωRC)²)。"""
    omega = 2.0 * math.pi * f_mhz * 1e6
    if omega == 0.0:
        return 0.0
    return v * omega * c / math.sqrt((1.0 - omega * omega * l_h * c) ** 2 + (omega * r * c) ** 2)


# ── 件①：接地拓扑判据 ────────────────────────────────────────────────────────


class TestGroundSpacingCriterion:
    def test_known_value_anchor_100mhz(self):
        """f=100 MHz → λ=c/f≈2.9979 m，λ/20=c/(20f)≈0.14990 m（精确 c 复算）。"""
        lambda20_exact = C0 / (LAMBDA20 * 100e6)
        res = ground_spacing_criterion(0.10, 100.0)
        assert res.verdict == "equipotential"
        assert res.lambda20_m == pytest.approx(lambda20_exact, rel=1e-15)
        assert res.lambda20_m == pytest.approx(0.1499, rel=1e-3)  # 量级锚（教科书 0.15 m 口径）
        assert res.wavelength_m == pytest.approx(C0 / 1e8, rel=1e-15)
        assert res.spacing_over_lambda20 == pytest.approx(0.10 / lambda20_exact, rel=1e-15)
        res_far = ground_spacing_criterion(0.20, 100.0)
        assert res_far.verdict == "electrically_long"

    def test_boundary_equality_is_electrically_long(self):
        """等号点 s=λ/20 归电长侧（规格字面严格不等号，不凑容差）。"""
        s_eq = C0 / (LAMBDA20 * 100e6)  # 精确 λ/20（测试文件独立复算）
        res = ground_spacing_criterion(s_eq, 100.0)
        assert res.verdict == "electrically_long"
        assert res.spacing_over_lambda20 == pytest.approx(1.0, rel=1e-12)

    def test_identity_s_vs_fcrit_sweep(self):
        """恒等面：s<λ/20 ⟺ f<c/(20s)——双路径独立判定扫描一致。"""
        spacings = [0.01, 0.05, 0.15, 0.3, 1.0, 2.5]
        freqs = [1.0, 10.0, 27.0, 100.0, 300.0, 1000.0]
        for s in spacings:
            f_crit_hz = grounding_critical_frequency_hz(s)
            assert f_crit_hz == pytest.approx(C0 / (LAMBDA20 * s), rel=1e-15)
            for f_mhz in freqs:
                f_hz = f_mhz * 1e6
                expected = "equipotential" if f_hz < f_crit_hz else "electrically_long"
                got = ground_spacing_criterion(s, f_mhz)
                assert got.verdict == expected, (s, f_mhz)
                assert got.critical_f_mhz == pytest.approx(f_crit_hz / 1e6, rel=1e-15)

    def test_equivalence_both_directions(self):
        """max_ground_spacing 与 critical_frequency 互逆恒等（双方向）。"""
        f_mhz = 27.0
        s_max = max_ground_spacing_m(f_mhz)
        # 恰在 λ/20 间距的临界频率 = 该频点（等号点归电长侧，f_crit=f）
        assert grounding_critical_frequency_hz(s_max) == pytest.approx(f_mhz * 1e6, rel=1e-12)

    def test_batch_and_json(self):
        results = ground_spacing_criteria(0.1, [30.0, 100.0, 1000.0])
        # 30 MHz: λ/20=0.5 m > 0.1；100 MHz: 0.15 > 0.1；1000 MHz: λ/20=0.015 < 0.1
        assert [r.verdict for r in results] == [
            "equipotential", "equipotential", "electrically_long",
        ]
        payload = json.dumps(results[0].to_dict())
        assert '"verdict": "equipotential"' in payload

    def test_negative_inputs_rejected(self):
        with pytest.raises(ValueError, match="正"):
            ground_spacing_criterion(0.0, 100.0)
        with pytest.raises(ValueError, match="正"):
            ground_spacing_criterion(0.1, 0.0)  # DC 域判据无定义
        with pytest.raises(ValueError, match="实数"):
            ground_spacing_criterion(True, 100.0)  # bool 显式拒收（df7+⑯）
        with pytest.raises(ValueError, match="实数"):
            max_ground_spacing_m(False)


# ── 件③：浮地-机壳耦合电容路径 ───────────────────────────────────────────────


class TestChassisCouplingCapacitance:
    def test_parallel_plate_anchor(self):
        """C = ε0·εr·A/d（独立常数复算）：A=0.01 m²、d=1 mm → 88.54 pF。"""
        c = chassis_coupling_capacitance(0.01, 1e-3)
        assert c == pytest.approx(EPS0 * 0.01 / 1e-3, rel=1e-15)
        assert c == pytest.approx(88.54e-12, rel=1e-3)
        c_fr4 = chassis_coupling_capacitance(0.01, 1e-3, er=4.4)
        assert c_fr4 == pytest.approx(4.4 * c, rel=1e-15)

    def test_negative_inputs_rejected(self):
        with pytest.raises(ValueError, match="正"):
            chassis_coupling_capacitance(0.0, 1e-3)
        with pytest.raises(ValueError, match="er"):
            chassis_coupling_capacitance(0.01, 1e-3, er=0.5)
        with pytest.raises(ValueError, match="实数"):
            chassis_coupling_capacitance(0.01, 1e-3, er=True)


class TestFloatingGroundCmCurrent:
    # 典型浮地面：10 cm²、1 mm 悬浮间距（≈88.5 pF）+ 50 nH 走线电感
    C0P, L0P, R0P, V0 = 88.54187817e-12, 50e-9, 2.0, 0.1

    def test_low_frequency_pure_capacitive(self):
        """无 L 无 R：I = ωCV 精确（纯容性回路）。"""
        f = 100.0
        res = floating_ground_cm_current(f, self.V0, self.C0P)
        i_expect = self.V0 * 2.0 * math.pi * f * 1e6 * self.C0P
        assert res.i_cm_ua == pytest.approx(i_expect * 1e6, rel=1e-12)
        # 量级锚：0.1 V @100 MHz 经 88.5 pF → ~5.6 mA
        assert res.i_cm_ua == pytest.approx(5556.0, rel=1e-2)

    def test_dual_path_independent_recompute(self):
        """路径 A（|V/Z|）vs 测试文件独立有理化式：≤1e-12（代数恒等）。"""
        cases = [
            (1.0, 0.1, 88.5e-12, 0.0, 0.0),
            (100.0, 0.1, 88.54187817e-12, 50e-9, 2.0),
            (300.0, 0.05, 20e-12, 200e-9, 5.0),
            (27.0, 1.0, 1e-10, 10e-9, 0.5),
        ]
        for f, v, c, l_h, r in cases:
            res = floating_ground_cm_current(f, v, c, l_h, r)
            i_b = _i_cm_path_b(f, v, c, l_h, r)
            assert res.i_cm_ua == pytest.approx(i_b * 1e6, rel=1e-12), (f, v, c, l_h, r)
            assert res.i_cm_a_path_b == pytest.approx(i_b, rel=1e-12)
            assert res.dual_path_diff_db <= 1e-9  # 预声明 ±3 dB 带的实测值（代数恒等）

    def test_dc_blocking_identity(self):
        """f=0 → I=0 恒等（浮地 C 隔直——定义面）。"""
        res = floating_ground_cm_current(0.0, self.V0, self.C0P, self.L0P, self.R0P)
        assert res.i_cm_ua == 0.0
        assert res.i_cm_a_path_b == 0.0
        assert res.dual_path_diff_db == 0.0

    def test_series_resonance_loss_limited(self):
        """谐振 f0=1/(2π√(LC)) 处 I=V/R（损耗限幅恒等，独立复算 f0）。"""
        l_h, c, v = 50e-9, 88.54187817e-12, 0.1
        f0_mhz = 1.0 / (2.0 * math.pi * math.sqrt(l_h * c)) / 1e6
        res = floating_ground_cm_current(f0_mhz, v, c, l_h, 2.0)
        assert res.i_cm_ua == pytest.approx(v / 2.0 * 1e6, rel=1e-9)
        assert res.i_cm_a_path_b == pytest.approx(v / 2.0, rel=1e-9)
        assert res.resonance_f_mhz == pytest.approx(f0_mhz, rel=1e-12)

    def test_resonance_reported_but_current_below_when_off(self):
        """失谐点电流 < 谐振值（谐振参考面报告，I(f0) 为上界）。"""
        res_off = floating_ground_cm_current(50.0, 0.1, self.C0P, self.L0P, 2.0)
        res_on = floating_ground_cm_current(res_off.resonance_f_mhz, 0.1, self.C0P, self.L0P, 2.0)
        assert res_off.i_cm_ua < res_on.i_cm_ua

    def test_zero_impedance_at_resonance_rejected(self):
        """R=0 恰在谐振 → 非物理无界电流 → ValueError。"""
        l_h, c = 50e-9, 88.54187817e-12
        f0_mhz = 1.0 / (2.0 * math.pi * math.sqrt(l_h * c)) / 1e6
        with pytest.raises(ValueError, match="谐振"):
            floating_ground_cm_current(f0_mhz, 0.1, c, l_h, 0.0)

    def test_negative_and_bool_rejected(self):
        with pytest.raises(ValueError, match="非负"):
            floating_ground_cm_current(100.0, -0.1, self.C0P)
        with pytest.raises(ValueError, match="正"):
            floating_ground_cm_current(100.0, 0.1, 0.0)
        with pytest.raises(ValueError, match="实数"):
            floating_ground_cm_current(True, 0.1, self.C0P)  # bool 拒收
        with pytest.raises(ValueError, match="实数"):
            floating_ground_cm_current(100.0, 0.1, self.C0P, l_path_h=True)


class TestCmRadiatedViaChassis:
    def test_chain_feeds_i_cm_entry_dual_path(self):
        """件③全链：模块 I_CM 喂 emc_radiated 入口后 E 与独立 Ott 式一致 ≤1e-12。"""
        f, ln, d, v, c = 100.0, 1.0, 3.0, 0.1, 88.54187817e-12
        budget = cm_radiated_via_chassis(f, ln, d, v, c_f=c)
        # 独立重算 I_CM（测试文件路径 B）→ 独立 Ott 式 → 与模块辐射面对拍
        i_b = _i_cm_path_b(f, v, c, 0.0, 0.0)
        e_expect = _ott_e_v_per_m(f, ln, i_b * 1e6, d, image=True)
        assert budget.floating_ground.i_cm_ua == pytest.approx(i_b * 1e6, rel=1e-12)
        assert budget.radiated.e_v_per_m == pytest.approx(e_expect, rel=1e-12)

    def test_parallel_plate_coupling_route(self):
        """area/distance 路线与直给 C 路线同值（单一事实来源分流）。"""
        args = (100.0, 1.0, 3.0, 0.1)
        via_c = cm_radiated_via_chassis(*args, c_f=88.54187817e-12)
        via_area = cm_radiated_via_chassis(*args, coupling_area_m2=0.01, coupling_distance_m=1e-3)
        assert via_c.floating_ground.i_cm_ua == pytest.approx(via_area.floating_ground.i_cm_ua, rel=1e-12)
        assert via_c.radiated.e_v_per_m == pytest.approx(via_area.radiated.e_v_per_m, rel=1e-12)

    def test_dc_end_to_end(self):
        """f=0 全链 → I=0 → E=0（两段恒等面贯通）。"""
        budget = cm_radiated_via_chassis(0.0, 1.0, 3.0, 0.1, c_f=88.5e-12)
        assert budget.floating_ground.i_cm_ua == 0.0
        assert budget.radiated.e_v_per_m == 0.0
        payload = json.dumps(budget.to_dict())
        assert '"i_cm_ua": 0.0' in payload

    def test_capacitance_source_xor_guard(self):
        """c_f 与 coupling_area_m2 二选一（同给/都不给 → ValueError）。"""
        with pytest.raises(ValueError, match="二选一"):
            cm_radiated_via_chassis(100.0, 1.0, 3.0, 0.1, c_f=1e-10, coupling_area_m2=0.01, coupling_distance_m=1e-3)
        with pytest.raises(ValueError, match="二选一"):
            cm_radiated_via_chassis(100.0, 1.0, 3.0, 0.1)
        with pytest.raises(ValueError, match="coupling_distance_m"):
            cm_radiated_via_chassis(100.0, 1.0, 3.0, 0.1, coupling_area_m2=0.01)

    def test_with_ground_image_passthrough(self):
        """镜像口径透传 emc_radiated（含/不含镜像差恰 ×2 幅度，+6.021 dB）。"""
        kw = dict(f_mhz=100.0, length_m=1.0, distance_m=3.0, v_cm_v=0.1, c_f=88.5e-12)
        with_img = cm_radiated_via_chassis(**kw)
        no_img = cm_radiated_via_chassis(**kw, with_ground_image=False)
        ratio = with_img.radiated.e_v_per_m / no_img.radiated.e_v_per_m
        assert ratio == pytest.approx(2.0, rel=1e-12)


def test_module_surface_exports():
    """__all__ 面存在性（防 #116 死壳：导入即验）。"""
    import rfauto.core.common_mode as m

    for name in m.__all__:
        assert getattr(m, name, None) is not None, name
    # 判据/回路结果对象类型存在且非删净占位
    assert callable(ground_spacing_criterion)
    assert callable(cm_radiated_field)  # emc_radiated 入口仍可导入（消费面未被破坏）
