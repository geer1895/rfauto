"""MM-3 GSTC 面抗综合内核单测（core/gstc.py + metasurface_lut v2 通道，规格
规格深案 §C-2）。

裁判 = 独立代数恒等式/经典文献锚，不是被测实现的自我推导（#118 家法）：
  * Eq.(19) 恒等式独立路径：k·χ_ee·(T+R+1) ≡ 2j(T+R−1)、
    k·χ_mm·(T−R+1) ≡ 2j(T−R−1)——由 Eq.(19) 移项而来，与正向实现完全
    不同的代码路径（正向算 T/R、恒等式只验 S 面代数自洽）；
  * 对称 χ（χ_ee=χ_mm）→ R=0 恒等 + |T|=1 + T≡(2−jkχ)/(2+jkχ)
    （分母约元后的独立闭式）；
  * 无耗守卫 |T|²+|R|²=1（实 χ 代数恒等式 (4+ab)²+4(b−a)² ≡
    (4−ab)²+4(a+b)²）——格点+随机实对批量钉；
  * 经典锚：电阻膜 χ_ee=−j/k（↔归一化并联导纳 y=1）→ T=2/3、R=−1/3
    精确；匹配吸收帘（CPA）χ_ee=χ_mm=−2j/k → T=R=0 精确；金属帘
    （PEC 墙）χ_ee→∞、χ_mm=0 → R→−1、T→0 渐近。
    厚帘口径注记：GSTC 面零厚度、k·d 无定义域——"厚帘"取帘面极限两
    点（PEC 帘反射墙 + 匹配吸收帘全吸），均在闭式有效域内；
  * 往返 Eq.(19)→Eq.(17)：逐位 ≤1e-12（含损耗/含噪目标批量）；
  * 负例：χ_em/χ_me 参数位 ValueError、gain χ 守卫 ValueError、
    Eq.(19) 奇点 ValueError、synthesize 内置往返自检（故障注入不可达
    ——代数恒等，靠 LUT 通道的管线负例补防）；
  * LUT v2 通道桥：s21 载体 → lut_interp_s21_pchip → t_r_from_db_phase
    → gstc_crosscheck 全链 PASS（节点逐位）+ v1 旧载体兼容读（#106）。

确定性：无网络、无真机、无文件 IO。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.gstc import (
    DT_GATE_DB_DEFAULT,
    gstc_crosscheck,
    gstc_forward,
    gstc_synthesize,
    t_r_from_db_phase,
)
from rfauto.core.metasurface_lut import (
    LUT_SCHEMA,
    MetasurfaceLUT,
    lut_interp_s21_pchip,
)

# 固定"随机"实/复对（钉死种子口径，无运行时随机）
_REAL_PAIRS = [(0.5, 2.0), (0.1, 0.7), (1.3, 0.4), (2.5, 2.5), (0.0, 1.1),
               (0.05, 0.9), (1.0, 3.0)]
_COMPLEX_TARGETS = [(0.7 - 0.1j, 0.2 + 0.3j), (0.5 + 0.1j, -0.3 + 0.2j),
                    (0.9 + 0.0j, 0.1 - 0.05j), (0.2 + 0.2j, 0.6 - 0.4j),
                    (-0.5 + 0.3j, 0.4 + 0.4j), (0.05 - 0.02j, -0.9 + 0.1j)]


def _k_of(f_ghz: float) -> float:
    return 2.0 * math.pi * (f_ghz * 1e9) / 299792458.0


# ─── §1 正向闭式：对称/无耗/经典锚 ────────────────────────────────────────────


class TestForwardClosedForms:
    def test_symmetric_chi_zero_reflection_identity(self):
        """对称 χ（χ_ee=χ_mm）→ R≡0（分子 2jk(χ−χ)=0 恒等）+ |T|=1。"""
        for chi in (0.3, 0.05, 1.7):
            out = gstc_forward(chi, chi, 1.0)
            assert out["r"] == 0.0  # 分子恰为零：逐位恒等
            assert abs(out["t"]) == pytest.approx(1.0, abs=1e-14)
            assert out["energy"] == pytest.approx(1.0, abs=1e-14)

    def test_symmetric_chi_matches_reduced_closed_form(self):
        """独立路径：对称实 χ 的 T ≡ (2−jkχ)/(2+jkχ)（约元后闭式）。"""
        for chi, k in [(0.3, 1.0), (0.8, 2.0 * math.pi / 30.0), (0.05, 10.0)]:
            out = gstc_forward(chi, chi, k)
            t_ref = (2.0 - 1j * k * chi) / (2.0 + 1j * k * chi)
            assert out["t"] == pytest.approx(t_ref, abs=1e-14)

    @pytest.mark.parametrize(("chi_ee", "chi_mm"), _REAL_PAIRS)
    def test_lossless_energy_identity_exact(self, chi_ee, chi_mm):
        """无耗守卫（实 χ）：|T|²+|R|²=1 代数恒等，逐位级。"""
        for k in (1.0, 0.7, 3.5):
            out = gstc_forward(chi_ee, chi_mm, k)
            assert out["energy"] == pytest.approx(1.0, abs=1e-12)

    def test_eq19_rearranged_identities_independent_path(self):
        """Eq.(19) 移项恒等式（独立代码路径）：
        k·χ_ee·(T+R+1) ≡ 2j(T+R−1)、k·χ_mm·(T−R+1) ≡ 2j(T−R−1)。"""
        rng = np.random.default_rng(20261002)
        for chi_ee_r, chi_mm_r in _REAL_PAIRS:
            for k in (1.0, 2.2):
                for ce, cm in [(chi_ee_r + 0j, chi_mm_r + 0j),
                               (complex(chi_ee_r, -0.4), complex(chi_mm_r, -0.2)),
                               (complex(rng.uniform(-1, 1), -abs(rng.uniform(0, 1))),
                                complex(rng.uniform(-1, 1), -abs(rng.uniform(0, 1))))]:
                    out = gstc_forward(ce, cm, k)
                    t, r = out["t"], out["r"]
                    assert abs(k * ce * (t + r + 1) - 2j * (t + r - 1)) <= 1e-12
                    assert abs(k * cm * (t - r + 1) - 2j * (t - r - 1)) <= 1e-12

    def test_resistive_sheet_classic_anchor(self):
        """经典电阻膜锚：χ_ee=−j/k（y=jkχ_ee=1）→ T=2/3、R=−1/3 精确
        （归一化并联导纳 1 的传输线标准结果）。"""
        for k in (1.0, 209.44):
            out = gstc_forward(-1j / k, 0.0, k)
            assert out["t"] == pytest.approx(2.0 / 3.0, abs=1e-14)
            assert out["r"] == pytest.approx(-1.0 / 3.0, abs=1e-14)
            assert out["energy"] < 1.0  # 有耗吸收

    def test_critical_absorption_curtain_anchor(self):
        """匹配吸收帘（CPA）：χ_ee=χ_mm=−2j/k → 2+jkχ=4、分子 4+k²χ²=0
        → T=R=0 精确（全吸收，无源侧 Im χ<0）。"""
        out = gstc_forward(-2j, -2j, 1.0)
        assert out["t"] == 0.0 and out["r"] == 0.0
        assert out["energy"] == 0.0

    def test_pec_wall_curtain_asymptote(self):
        """金属帘（PEC 墙）渐近：χ_ee→∞、χ_mm=0 → R→−1、T→0（O(1/χ)）。"""
        out = gstc_forward(1e6, 0.0, 1.0)
        assert abs(out["t"]) <= 1e-5
        assert abs(out["r"] + 1.0) <= 1e-5

    def test_empty_sheet_is_identity(self):
        out = gstc_forward(0.0, 0.0, 1.0)
        assert out["t"] == pytest.approx(1.0, abs=1e-15)
        assert out["r"] == 0.0

    def test_lossy_sheet_absorbs_monotonically_plausible(self):
        """有耗 χ（Im<0）能量 <1（吸收），且 dB/相位报告自洽。"""
        out = gstc_forward(complex(0.3, -0.5), complex(0.8, -0.2), 1.0)
        assert 0.0 < out["energy"] < 1.0
        assert out["t_db"] == pytest.approx(20 * math.log10(abs(out["t"])),
                                            abs=1e-12)
        assert out["t_phase_deg"] == pytest.approx(
            math.degrees(math.atan2(out["t"].imag, out["t"].real)), abs=1e-12)

    def test_zero_transmission_db_phase_none_json_safe(self):
        """|T|=0（CPA）的 dB/相位为 None（无有限 dB，JSON 安全——
        shell 层 [re,im] 化后无 NaN/Inf 泄漏）。"""
        out = gstc_forward(-2j, -2j, 1.0)
        assert out["t_db"] is None and out["t_phase_deg"] is None
        safe = {"t_db": out["t_db"], "r_db": out["r_db"],
                "t_phase_deg": out["t_phase_deg"], "energy": out["energy"]}
        json.dumps(safe, allow_nan=False)  # 不抛即合格


# ─── §2 守卫负例 ──────────────────────────────────────────────────────────────


class TestGuards:
    def test_gain_chi_violates_passivity_guard(self):
        """增益 χ（Im>0）→ 无源守卫 |R|²+|T|²>1+1e-9 违，ValueError。"""
        # χ_ee=0.005+0.005j、χ_mm=0 @k≈209.44（10GHz）：|T|²≈2.0>1（实测）
        with pytest.raises(ValueError, match="无源守卫"):
            gstc_forward(0.005 + 0.005j, 0.0, _k_of(10.0))

    def test_gain_chi_numeric_evidence_before_guard(self):
        """守卫触发前先钉数值证据（guard 不是空转）：能量 3.09>1。"""
        ce, cm, k = 0.005 + 0.005j, 0.0 + 0j, _k_of(10.0)
        den = (2 + 1j * k * ce) * (2 + 1j * k * cm)
        t = (4 + (k * ce) * (k * cm)) / den
        r = 2j * k * (cm - ce) / den
        assert abs(t) ** 2 + abs(r) ** 2 > 3.0  # 明确超物理，非 1+ε 边界抖动

    def test_polarization_cross_rejected(self):
        with pytest.raises(ValueError, match=r"交叉极化|polarization"):
            gstc_forward(0.1, 0.2, 1.0, polarization="cross")

    def test_polarization_xy_equivalent_normal_incidence(self):
        """x/y 法向入射共极化简并（单轴面同 χ_ee）→ 结果同一。"""
        a = gstc_forward(0.3, 0.8, 1.0, polarization="x")
        b = gstc_forward(0.3, 0.8, 1.0, polarization="y")
        assert a["t"] == b["t"] and a["r"] == b["r"]

    def test_chi_em_chi_me_explicit_not_implemented(self):
        """χ_em/χ_me 参数位保留：传非 None 即 ValueError（规格 §C-2 显式不做）。"""
        with pytest.raises(ValueError, match="χ_em"):
            gstc_forward(0.1, 0.2, 1.0, chi_em=0.05)
        with pytest.raises(ValueError, match="χ_em"):
            gstc_forward(0.1, 0.2, 1.0, chi_me=0.05)

    def test_bad_k_and_chi_inputs_rejected(self):
        with pytest.raises(ValueError):
            gstc_forward(0.1, 0.2, 0.0)
        with pytest.raises(ValueError):
            gstc_forward(0.1, 0.2, -1.0)
        with pytest.raises(ValueError):
            gstc_forward(float("nan"), 0.2, 1.0)
        with pytest.raises(ValueError):
            gstc_forward(0.1, [1.0, 2.0, 3.0], 1.0)
        with pytest.raises(ValueError):
            gstc_forward(0.1, 0.2, 1.0, polarization="circular")

    def test_synthesize_singular_denominators_rejected(self):
        """Eq.(19) 奇点：|T+R+1|→0（T=−1 全反 Huygens 极限）与 |T−R+1|→0。"""
        with pytest.raises(ValueError, match="χ_ee"):
            gstc_synthesize(-1.0 + 0j, 0.0 + 0j, 1.0)
        with pytest.raises(ValueError, match="χ_mm"):
            gstc_synthesize(0.5 + 0j, 1.5 + 0j, 1.0)


# ─── §3 往返恒等（Eq.19↔Eq.17）────────────────────────────────────────────────


class TestRoundTrip:
    @pytest.mark.parametrize(("t", "r"), _COMPLEX_TARGETS)
    def test_roundtrip_bitwise_1e_minus_12(self, t, r):
        """规格 §C-2：Eq.(19)→Eq.(17) 往返逐位 ≤1e-12（含损耗目标批量）。"""
        for k in (1.0, _k_of(10.0)):
            inv = gstc_synthesize(t, r, k)
            assert inv["roundtrip_residual"] <= 1e-12
            fwd = gstc_forward(inv["chi_ee"], inv["chi_mm"], k)
            assert abs(fwd["t"] - t) <= 1e-12
            assert abs(fwd["r"] - r) <= 1e-12

    def test_roundtrip_matches_manual_eq19(self):
        """χ 反演值 == 手算 Eq.(19)（独立公式路径，非实现内部复用）。"""
        t, r, k = 0.7 - 0.1j, 0.2 + 0.3j, 1.3
        inv = gstc_synthesize(t, r, k)
        chi_ee_ref = 2j * (t + r - 1) / (k * (t + r + 1))
        chi_mm_ref = 2j * (t - r - 1) / (k * (t - r + 1))
        assert inv["chi_ee"] == pytest.approx(chi_ee_ref, abs=1e-15)
        assert inv["chi_mm"] == pytest.approx(chi_mm_ref, abs=1e-15)

    def test_lossless_targets_recover_real_chi(self):
        """无耗目标（实 χ 正向产出）反演回实 χ（Im ≤1e-12）——
        反演保持无耗性（可实现性自洽）。"""
        for chi_ee, chi_mm in [(0.4, 0.9), (0.15, 1.6), (1.1, 0.55)]:
            out = gstc_forward(chi_ee, chi_mm, 1.0)
            inv = gstc_synthesize(out["t"], out["r"], 1.0)
            assert abs(inv["chi_ee"].imag) <= 1e-12
            assert abs(inv["chi_mm"].imag) <= 1e-12
            assert inv["chi_ee"].real == pytest.approx(chi_ee, abs=1e-12)
            assert inv["chi_mm"].real == pytest.approx(chi_mm, abs=1e-12)

    def test_identity_target_recovers_zero_chi(self):
        inv = gstc_synthesize(1.0 + 0j, 0.0 + 0j, 1.0)
        assert abs(inv["chi_ee"]) <= 1e-15
        assert abs(inv["chi_mm"]) <= 1e-15


# ─── §4 带内对拍通道（J4 接口面）───────────────────────────────────────────────


class TestCrosscheck:
    @staticmethod
    def _band_data(chi_ee: float, chi_mm: float, freqs: list[float]):
        s11, s21 = [], []
        for f in freqs:
            out = gstc_forward(chi_ee, chi_mm, _k_of(f))
            s11.append(out["r"])
            s21.append(out["t"])
        return s11, s21

    def test_synthetic_band_passes_at_machine_precision(self):
        """合成带（实 χ 帘、9.5–10.5GHz 五点）→ PASS @ ~1e-13dB
        （离线同源口径——门判管线破坏，判别力在真机腿，docstring 诚实边界）。"""
        freqs = [9.5 + 0.25 * i for i in range(5)]
        s11, s21 = self._band_data(0.002, 0.004, freqs)
        cc = gstc_crosscheck(freqs, s11, s21, band_ghz=[9.75, 10.25])
        assert cc["verdict"] == "PASS"
        assert cc["n_points"] == 5 and cc["n_in_band"] == 3
        assert cc["max_dt_db"] <= 1e-9
        assert cc["n_dt_excluded"] == 0
        assert cc["gate_dt_db"] == DT_GATE_DB_DEFAULT == 0.5
        # 反演 χ 与设定值一致（物理自洽）
        assert cc["chi_ee"][0][0] == pytest.approx(0.002, abs=1e-12)
        assert cc["chi_mm"][0][1] == pytest.approx(0.0, abs=1e-15)

    def test_full_band_default_and_gate_fail_verdict(self):
        """缺省全带；gate 收紧到不可达小值 → FAIL（门活口验证，非恒 PASS）。"""
        freqs = [10.0, 10.5, 11.0]
        s11, s21 = self._band_data(0.001, 0.003, freqs)
        cc = gstc_crosscheck(freqs, s11, s21, gate_dt_db=1e-30)
        assert cc["verdict"] == "FAIL" and cc["n_in_band"] == 3

    def test_input_validation_negatives(self):
        freqs = [10.0, 10.5]
        s11, s21 = self._band_data(0.001, 0.003, freqs)
        with pytest.raises(ValueError, match="长度不一致"):
            gstc_crosscheck(freqs, s11[:1], s21)
        with pytest.raises(ValueError, match="升序"):
            gstc_crosscheck([10.5, 10.0], s11, s21)
        with pytest.raises(ValueError, match="带内无频点"):
            gstc_crosscheck(freqs, s11, s21, band_ghz=[20.0, 21.0])
        with pytest.raises(ValueError, match="band_ghz"):
            gstc_crosscheck(freqs, s11, s21, band_ghz=[21.0, 20.0])
        with pytest.raises(ValueError):
            gstc_crosscheck(freqs, [float("nan"), 0.0], s21)
        with pytest.raises(ValueError, match="反演失败"):
            gstc_crosscheck([10.0, 10.5], [0.0 + 0j, 0.1 + 0j],
                            [-1.0 + 0j, 0.9 + 0j])  # 点 0 落 Eq.19 奇点（T=−1）

    def test_zero_transmission_point_excluded_honestly(self):
        """|T|=0 点无有限 dB → 诚实剔除（n_dt_excluded）不进 max。"""
        freqs = [10.0, 10.5]
        s11, s21 = self._band_data(0.001, 0.003, freqs)
        s21[0] = 0.0 + 0j  # 注入零透射点
        cc = gstc_crosscheck(freqs, s11, s21)
        assert cc["n_dt_excluded"] == 1
        assert cc["verdict"] == "PASS"
        assert cc["dt_db"][0] is None


# ─── §5 LUT v2 通道桥（schema v1→v2 兼容 #106）────────────────────────────────


def _lut_with_s21(n_px: int = 7, n_freq: int = 9) -> tuple[MetasurfaceLUT, np.ndarray]:
    """合成 v2 LUT：s21 列=实 χ 帘 (χee=0.002, χmm=0.004) 在各 px 的微缩放
    正向数据（px 只作幅度扰动，保证 pchip 非退化），返回 (lut, freq)。"""
    freq = np.linspace(9.0, 11.0, n_freq)
    px = np.linspace(2.0, 5.0, n_px)
    s11_db = np.full((n_px, n_freq), -0.2)
    s11_ph = np.tile(np.linspace(-170.0, 150.0, n_px)[:, None], (1, n_freq))
    s21_db = np.empty((n_px, n_freq))
    s21_ph = np.empty((n_px, n_freq))
    scale = 0.90 + 0.02 * np.arange(n_px)
    for i in range(n_px):
        for j in range(n_freq):
            out = gstc_forward(0.002 * scale[i], 0.004 * scale[i], _k_of(float(freq[j])))
            s21_db[i, j] = 20.0 * math.log10(abs(out["t"]))
            s21_ph[i, j] = math.degrees(math.atan2(out["t"].imag, out["t"].real))
    lut = MetasurfaceLUT(
        cell_id="ms_gstc_demo", f0_ghz=10.0, substrate_key="air",
        sweep_key="px_mm", sweep_values=px, freq_ghz=freq,
        s11_db=s11_db, s11_phase_deg=s11_ph,
        s21_db=s21_db, s21_phase_deg=s21_ph, origin="synthetic")
    return lut, freq


class TestLutV2Bridge:
    def test_v2_json_csv_roundtrip_bitwise(self):
        lut, _ = _lut_with_s21()
        assert lut.validate() == []
        lut2 = MetasurfaceLUT.from_json(lut.to_json())
        assert lut2.to_dict()["schema"] == LUT_SCHEMA == "metasurface_lut/v2"
        assert np.array_equal(lut2.s21_db, lut.s21_db)
        assert np.array_equal(lut2.s21_phase_deg, lut.s21_phase_deg)
        lut3 = MetasurfaceLUT.from_csv(lut.to_csv())
        assert np.array_equal(lut3.s21_db, lut.s21_db)
        assert np.array_equal(lut3.s21_phase_deg, lut.s21_phase_deg)
        assert MetasurfaceLUT.from_json(lut3.to_json()).to_dict() == lut.to_dict()

    def test_v1_dict_compat_read(self):
        """#106 兼容：v1 旧载体（无 s21 字段、schema=v1）合法读入 → s21=None。"""
        lut, _ = _lut_with_s21()
        d1 = json.loads(lut.to_json())
        del d1["s21_db"], d1["s21_phase_deg"]
        d1["schema"] = "metasurface_lut/v1"
        old = MetasurfaceLUT.from_json(json.dumps(d1, ensure_ascii=False))
        assert old.s21_db is None and old.s21_phase_deg is None
        assert old.validate() == []
        assert np.array_equal(old.s11_db, lut.s11_db)

    def test_v1_csv_four_column_compat_read(self):
        """v1 4 列 CSV 旧格式合法读入（s21=None，写出恒 v2 格式）。"""
        lut, _ = _lut_with_s21()
        bare = MetasurfaceLUT(
            cell_id=lut.cell_id, f0_ghz=lut.f0_ghz,
            substrate_key=lut.substrate_key, sweep_key=lut.sweep_key,
            sweep_values=lut.sweep_values, freq_ghz=lut.freq_ghz,
            s11_db=lut.s11_db, s11_phase_deg=lut.s11_phase_deg)
        csv4 = bare.to_csv()
        assert csv4.splitlines()[1] == ("sweep_value,freq_ghz,s11_db,"
                                        "s11_phase_deg")
        old = MetasurfaceLUT.from_csv(csv4)
        assert old.s21_db is None and old.validate() == []
        # v2 LUT 写 6 列且能读回
        assert lut.to_csv().splitlines()[1].count(",") == 5
        MetasurfaceLUT.from_csv(lut.to_csv())

    def test_v2_validation_pair_and_shape(self):
        lut, freq = _lut_with_s21()
        bad_shape = MetasurfaceLUT(
            cell_id="x", f0_ghz=10.0, substrate_key="s", sweep_key="px",
            sweep_values=lut.sweep_values, freq_ghz=freq,
            s11_db=lut.s11_db, s11_phase_deg=lut.s11_phase_deg,
            s21_db=lut.s21_db[:, :3], s21_phase_deg=lut.s21_phase_deg)
        assert any("s21_db 形状" in p for p in bad_shape.validate())
        bad_pair = MetasurfaceLUT(
            cell_id="x", f0_ghz=10.0, substrate_key="s", sweep_key="px",
            sweep_values=lut.sweep_values, freq_ghz=freq,
            s11_db=lut.s11_db, s11_phase_deg=lut.s11_phase_deg,
            s21_db=lut.s21_db)
        assert any("成对" in p for p in bad_pair.validate())

    def test_unknown_schema_still_rejected(self):
        lut, _ = _lut_with_s21()
        d = json.loads(lut.to_json())
        d["schema"] = "metasurface_lut/v9"
        with pytest.raises(ValueError, match="兼容集"):
            MetasurfaceLUT.from_dict(d)

    def test_s21_interp_node_exact_and_missing_rejected(self):
        lut, _ = _lut_with_s21()
        i = 3
        db, ph = lut_interp_s21_pchip(lut, float(lut.sweep_values[i]))
        assert db == pytest.approx(float(lut.s21_db[i, 4]), abs=1e-12)
        assert ph == pytest.approx(float(lut.s21_phase_deg[i, 4]), abs=1e-12)
        d1 = json.loads(lut.to_json())
        del d1["s21_db"], d1["s21_phase_deg"]
        d1["schema"] = "metasurface_lut/v1"
        old = MetasurfaceLUT.from_dict(d1)
        with pytest.raises(ValueError, match="s21"):
            lut_interp_s21_pchip(old, 3.0)

    def test_full_channel_lut_to_crosscheck_pass(self):
        """全链通道（真机通道语义：单胞扫频 Γ/T）：LUT v2 某 px 行的
        s11/s21 列 → t_r_from_db_phase → gstc_crosscheck PASS @1e-9
        （接口面落地证明，真机正演腿留位）。"""
        lut, _ = _lut_with_s21()
        i = 0  # 单胞行（真机通道=一个胞沿频轴扫）
        s11, s21, f_list = [], [], []
        for j in range(lut.freq_ghz.size):
            db11 = float(lut.s11_db[i, j])
            ph11 = float(lut.s11_phase_deg[i, j])
            db21 = float(lut.s21_db[i, j])
            ph21 = float(lut.s21_phase_deg[i, j])
            g = t_r_from_db_phase(db11, ph11)
            t = t_r_from_db_phase(db21, ph21)
            s11.append(complex(g))
            s21.append(complex(t))
            f_list.append(float(lut.freq_ghz[j]))
        assert len(set(f_list)) == len(f_list)  # 频轴严格升序（通道口径）
        cc = gstc_crosscheck(f_list, s11, s21, band_ghz=[9.5, 10.5])
        assert cc["verdict"] == "PASS"
        assert cc["max_dt_db"] <= 1e-9
