"""EM-5 件② vendor_passives ferrite_bead 单测（并联 RLC 磁珠模型，2026-10-02）。

锚树口径（#118：锚值独立复算/独立公式，不赌推导）：
- 谐振恒等式：ω0=1/(2π√(LC)) 处 |Z|=R **精确**（损耗限幅峰=datasheet
  额定阻抗语义，如 600Ω@100MHz）——独立公式 Z=1/(1/R+j(ωC−1/ωL)) 复算。
- 渐近线：低频（ωL≪R）|Z|≈ωL（相对偏差理论值 1−1/√(1+(ωL/R)²)，独立
  复算）；高频 |Z|≈1/ωC。
- DC 直通：f=0 → Z=0 恒等（磁珠额定偏置电流的规格面——串联 C 解析被
  物理排除的判据锚）。
- SRF 提取往返：合成 → 写 s2p → 读回 → |Z| 峰抛物线细化回收 f0 ≤0.5%
  （判据 A 口径，C15 既有锚同款）。
- 种子生成器：ferrite_bead 分支（C 由 srf_ghz 反推）字节确定 + 往返一致；
  schema：from_dict 接受 ferrite_bead / 拒绝笔误类型；工作区 catalog 的
  synthetic 磁珠条目可解析。

物理数值全部出自闭式内核公式与测试文件独立复算，无手编数字（铁律 7）。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.vendor_passives import (
    VendorPartEntry,
    default_catalog_path,
    extract_srf,
    load_impedance_curve,
    read_catalog,
    sha256_file,
    synthesize_ferrite_bead_z,
    synthesize_seed_model_file,
    validate_catalog,
    write_touchstone_series_2port,
)
from rfauto.service.vendor_passives_service import register_model_entry

# ── 测试文件内独立常数与公式（#118：不 import 模块常数）───────────────────────
# 典型磁珠口径（Murata BLM18AG601SN1 语义的合成再现）：600Ω@100MHz、L≈1 µH
L0, R0, F0 = 1.0e-6, 600.0, 100e6
C0 = 1.0 / ((2.0 * math.pi * F0) ** 2 * L0)  # ≈2.533 pF（独立反推）


def _bead_z_ref(freqs_hz: np.ndarray, l_h: float, r_loss: float, c_par: float) -> np.ndarray:
    """独立复算（并联 RLC 导纳式，测试文件独立键入；DC 点恒 0）。"""
    w = 2.0 * math.pi * np.asarray(freqs_hz, dtype=float)
    z = np.zeros(w.shape, dtype=complex)
    nz = w > 0.0
    wn = w[nz]
    y = 1.0 / r_loss + 1j * (wn * c_par - 1.0 / (wn * l_h))
    z[nz] = 1.0 / y
    return z


# ── 1. 闭式恒等式 ────────────────────────────────────────────────────────────


class TestBeadClosedForm:
    def test_resonance_impedance_equals_r_exactly(self):
        """ω0 处 |Z|=R 精确（损耗限幅峰=额定阻抗语义锚）。"""
        z = synthesize_ferrite_bead_z(np.array([F0]), L0, R0, C0)
        assert abs(z[0]) == pytest.approx(R0, rel=1e-12)
        assert abs(z[0] - R0) / R0 < 1e-14

    def test_matches_independent_formula(self):
        """与测试文件独立公式逐点一致 ≤1e-12（含 DC 点）。"""
        freqs = np.array([0.0, 1e6, 10e6, F0, 3e8, 1e9])
        z = synthesize_ferrite_bead_z(freqs, L0, R0, C0)
        z_ref = _bead_z_ref(freqs, L0, R0, C0)
        assert np.max(np.abs(z - z_ref)) <= 1e-9
        assert z[0] == 0.0  # DC 直通恒等（精确 0）

    def test_low_frequency_inductive_asymptote(self):
        """低频 |Z|≈ωL：1e-4·ω0（10 kHz）处 R/C 两项修正均 ≤1e-8 → |Z|/ωL 偏差 ≤1e-6。"""
        f = 1e-4 * F0
        z = synthesize_ferrite_bead_z(np.array([f]), L0, R0, C0)
        w_l = 2.0 * math.pi * f * L0
        # 修正项量级自检：R 项 (ωL/R)²/2 与 C 项 ω²LC/2 都远小于门
        assert (w_l / R0) ** 2 / 2.0 < 1e-8
        assert (2.0 * math.pi * f) ** 2 * L0 * C0 / 2.0 < 1e-8
        assert abs(abs(z[0]) / w_l - 1.0) < 1e-6
        assert z[0].imag > 0.0  # 感性

    def test_high_frequency_capacitive_asymptote(self):
        """高频 |Z|≈1/ωC（容性，Im<0）。"""
        f = 100.0 * F0
        z = synthesize_ferrite_bead_z(np.array([f]), L0, R0, C0)
        assert z[0].imag < 0.0
        assert abs(z[0]) == pytest.approx(1.0 / (2.0 * math.pi * f * C0), rel=1e-4)

    def test_dc_zero_and_input_guards(self):
        """DC→0 + 参数守卫（非正/非有限 → ValueError）。"""
        assert synthesize_ferrite_bead_z(np.array([0.0, 1e6]), L0, R0, C0)[0] == 0.0
        with pytest.raises(ValueError, match="正有限"):
            synthesize_ferrite_bead_z(np.array([1e6]), 0.0, R0, C0)
        with pytest.raises(ValueError, match="正有限"):
            synthesize_ferrite_bead_z(np.array([1e6]), L0, -1.0, C0)
        with pytest.raises(ValueError, match="正有限"):
            synthesize_ferrite_bead_z(np.array([1e6]), L0, R0, float("nan"))


# ── 2. SRF 提取往返（判据 A 口径）────────────────────────────────────────────


class TestBeadSrfRoundtrip:
    def test_srf_extraction_recovers_f0(self, tmp_path: Path):
        """合成 → 写 s2p → 读回 → |Z| 峰回收 f0 ≤0.5% 且峰值 ≈R。"""
        freqs = np.linspace(0.05 * F0, 3.0 * F0, 4001)
        z = synthesize_ferrite_bead_z(freqs, L0, R0, C0)
        path = write_touchstone_series_2port(
            tmp_path / "bead.s2p", freqs, z, comment="synthetic bead 600ohm@100MHz"
        )
        curve = load_impedance_curve(path)
        srf_hz = extract_srf(curve.freqs_hz, curve.z, mode="peak")
        assert srf_hz is not None
        assert srf_hz == pytest.approx(F0, rel=0.005)
        z_at_peak = curve.z[int(np.argmin(np.abs(curve.freqs_hz - srf_hz)))]
        assert abs(z_at_peak) == pytest.approx(R0, rel=0.005)

    def test_direct_vs_written_identical(self, tmp_path: Path):
        """写盘往返不改变阻抗（相对差 ≤1e-9，#175 字节确定口径）。"""
        freqs = np.linspace(0.05 * F0, 3.0 * F0, 501)
        z = synthesize_ferrite_bead_z(freqs, L0, R0, C0)
        path = write_touchstone_series_2port(tmp_path / "b.s2p", freqs, z)
        curve = load_impedance_curve(path)
        assert np.max(np.abs(curve.z - z) / np.abs(z)) < 1e-9


# ── 3. 种子生成器 ferrite_bead 分支 + schema ─────────────────────────────────


def _bead_entry(**overrides: object) -> VendorPartEntry:
    base: dict[str, object] = {
        "part_id": "synth_bead_test",
        "vendor": "synthetic",
        "mpn": "SYNTH-BEAD-TEST",
        "type": "ferrite_bead",
        "nominal_value": L0,
        "model_file": "synth_bead_test.s2p",
        "srf_ghz": 0.1,
        "esr_ohm": R0,
        "synthetic": True,
    }
    base.update(overrides)
    return VendorPartEntry.from_dict(str(base["part_id"]), base)  # type: ignore[arg-type]


class TestBeadSeedGeneratorAndSchema:
    def test_seed_generator_branch_and_determinism(self, tmp_path: Path):
        """ferrite_bead 分支：C 由 srf 反推 → 读回与独立公式一致；两跑同哈希。"""
        entry = _bead_entry()
        path1, sha1 = synthesize_seed_model_file(entry, tmp_path)
        _path2, sha2 = synthesize_seed_model_file(entry, tmp_path)
        assert sha1 == sha2
        curve = load_impedance_curve(path1)
        z_ref = _bead_z_ref(curve.freqs_hz, L0, R0, C0)
        assert np.max(np.abs(curve.z - z_ref) / np.abs(z_ref)) < 1e-9

    def test_seed_generator_requires_metadata(self, tmp_path: Path):
        """缺 srf/esr → ValueError（synthetic 再现前提）。"""
        entry = _bead_entry(srf_ghz=None, esr_ohm=None)
        with pytest.raises(ValueError, match="srf_ghz/esr_ohm"):
            synthesize_seed_model_file(entry, tmp_path)

    def test_seed_generator_rejects_unknown_type(self, tmp_path: Path):
        """构造器旁路 from_dict 的未知类型 → 生成器 else 分支显式 ValueError。"""
        entry = VendorPartEntry(
            part_id="x", vendor="synthetic", mpn="X", type="transformer",
            nominal_value=1.0, model_file="x.s2p", srf_ghz=0.1, esr_ohm=1.0,
            synthetic=True,
        )
        with pytest.raises(ValueError, match="不支持再现的元件类型"):
            synthesize_seed_model_file(entry, tmp_path)

    def test_from_dict_accepts_bead_rejects_typo(self):
        """schema：ferrite_bead 合法；笔误类型列出允许值。"""
        entry = _bead_entry()
        assert entry.type == "ferrite_bead"
        with pytest.raises(ValueError, match="ferrite_bead"):
            _bead_entry(type="ferrite")

    def test_register_model_entry_roundtrip(self, tmp_path: Path):
        """service 登记流：磁珠条目写 catalog 读回同值（tmp 隔离）。"""
        catalog = tmp_path / "catalog.yaml"
        register_model_entry(
            catalog_path=catalog,
            part_id="bead_rt",
            vendor="Murata",
            mpn="BLM18AG601SN1",
            part_type="ferrite_bead",
            nominal_value=1.0e-6,
            model_file="real.s2p",
            sha256="a" * 64,
            srf_ghz=None,
            esr_ohm=600.0,
            license_note="SimSurfing 免费下载，文件不入 git",
        )
        entry = read_catalog(catalog)["bead_rt"]
        assert entry.type == "ferrite_bead"
        assert entry.esr_ohm == 600.0

    def test_workspace_catalog_has_beed_entry(self):
        """工作区 catalog 回归：synthetic 磁珠条目可解析（skip-not-fail 盘点不红）。"""
        catalog = default_catalog_path()
        entries = read_catalog(catalog)
        entry = entries.get("synth_bead600_100mhz_demo")
        assert entry is not None, "工作区 catalog 缺 EM-5 synthetic 磁珠条目"
        assert entry.type == "ferrite_bead"
        assert entry.nominal_value == pytest.approx(1.0e-6, rel=1e-12)
        assert entry.esr_ohm == pytest.approx(600.0, rel=1e-12)
        assert entry.srf_ghz == pytest.approx(0.1, rel=1e-12)
        statuses = {s.part_id: s for s in validate_catalog(catalog)}
        assert statuses["synth_bead600_100mhz_demo"].status in ("ok", "unverified")

    def test_workspace_seed_file_matches_generator(self):
        """种子文件在场时：与生成器再现逐字节同哈希（确定性锚；不在场 skip）。"""
        catalog = default_catalog_path()
        entry = read_catalog(catalog)["synth_bead600_100mhz_demo"]
        seed = catalog.parent / entry.model_file
        if not seed.exists():
            pytest.skip("种子模型文件未生成（gitignored，工作区未再现）")
        _, sha = synthesize_seed_model_file(entry, catalog.parent)
        assert sha == sha256_file(seed)
