"""C15 厂商被动元件库单元测试（Plan §10.3 C15 / §10.22 #24）。

验收判据：
A（自谐振锚，#118 双裁判）：合成电感 L=10nH/Rs=0.5Ω/Cp=0.25pF → 闭式
   SRF=1/(2π√(L·Cp))≈3.183GHz；写 tmp .s2p 读回，SRF 提取（|Z| 峰抛物线
   细化 / Im 过零插值）与解析值相对误差 ≤0.5%；低频 L_eff≈标称 ≤1%；
   Q(f)=ωL/Rs 对拍 ≤0.5%。
B（匹配链偏差）：synthesize_l_match(50→25Ω@2.4GHz low_pass) 理想链 vs
   真元件链（series/shunt 两槽位均替换）；真链递推理想回代与
   MatchNetworkResult.input_impedance 身份一致 <1e-12；skrf |S11| 逐点
   <0.1dB；报告量化 Δmatch_depth/L_eff 比值/SRF/f0/最佳匹配频点偏移。
C（registry/条款）：缺文件→KeyError、哈希篡改→ValueError、synthetic
   哈希会话内"生成→取哈希→校验"不钉死、真实条目缺文件 skip-not-fail。
D（下载器）：monkeypatch 钉住 urllib 通道（#139 零真网），只测纯函数与
   登记流；ruff 覆盖 scripts/（#119）。

物理数值全部出自闭式内核/生成器公式，无手编数字（铁律 7）。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.matching import synthesize_l_match, to_skrf_network
from rfauto.core.vendor_passives import (
    ImpedanceCurve,
    VendorPartEntry,
    chain_input_impedance,
    effective_capacitance,
    effective_inductance,
    extract_srf,
    im_zero_crossings,
    load_impedance_curve,
    load_part,
    match_deviation_report,
    q_factor,
    read_catalog,
    sha256_file,
    synthesize_rlc_capacitor_z,
    synthesize_rlc_inductor_z,
    synthesize_seed_model_file,
    validate_catalog,
    write_catalog,
    write_touchstone_one_port,
    write_touchstone_series_2port,
)
from rfauto.service.vendor_passives_service import (
    list_vendor_parts,
    register_model_entry,
    run_match_deviation,
)

_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "vendor_passive_download",
    Path(__file__).resolve().parents[2] / "scripts" / "vendor_passive_download.py",
)
assert _SCRIPT_SPEC is not None and _SCRIPT_SPEC.loader is not None
dl = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(dl)

# 判据 A 锚参数（给定值，闭式 SRF 由内核公式复算）
L0, RS0, CP0 = 10e-9, 0.5, 0.25e-12
SRF0_HZ = 1.0 / (2.0 * math.pi * math.sqrt(L0 * CP0))  # ≈3.1831 GHz

# 判据 B 匹配场景
F0_GHZ = 2.4
BAND_SRF_HZ = np.linspace(0.5e9, 25e9, 2501)  # 曲线频带：包含两合成件的 SRF


def _write_inductor_s2p(path: Path, l_h: float, rs_ohm: float, cp_f: float,
                        freqs: np.ndarray) -> Path:
    z = synthesize_rlc_inductor_z(freqs, l_h, rs_ohm, cp_f)
    return write_touchstone_series_2port(
        path, freqs, z,
        comment=f"synthetic inductor L={l_h:g} Rs={rs_ohm:g} Cp={cp_f:g}",
    )


@pytest.fixture()
def match_result():
    return synthesize_l_match(50.0, 25.0, F0_GHZ, response="low_pass")


@pytest.fixture()
def series_slot_path(tmp_path: Path, match_result) -> Path:
    """替换 series 槽位的合成电感 .s2p（L=理想值、Rs=0.3Ω、Cp=0.05pF→SRF≈17.5GHz）。"""
    l_ideal = next(e.value for e in match_result.elements if e.role == "series" and e.kind == "L")
    return _write_inductor_s2p(tmp_path / "series_l.s2p", l_ideal, 0.3, 0.05e-12, BAND_SRF_HZ)


@pytest.fixture()
def series_slot_curve(series_slot_path: Path) -> ImpedanceCurve:
    return load_impedance_curve(series_slot_path)


# ─── 判据 A：合成生成器 + SRF/L_eff/Q 锚 ─────────────────────────────────────

class TestSyntheticGenerators:
    """合成 RLC 生成器与 Touchstone 往返（写盘字节确定，不依赖 skrf 写盘 #175）。"""

    def test_series_s2p_roundtrip_matches_closed_form(self, tmp_path: Path):
        freqs = np.linspace(0.1e9, 10e9, 2001)
        path = _write_inductor_s2p(tmp_path / "l.s2p", L0, RS0, CP0, freqs)
        curve = load_impedance_curve(path)
        z_direct = synthesize_rlc_inductor_z(curve.freqs_hz, L0, RS0, CP0)
        rel = np.max(np.abs(curve.z - z_direct) / np.abs(z_direct))
        assert rel < 1e-9
        assert curve.n_ports == 2

    def test_written_bytes_deterministic(self, tmp_path: Path):
        freqs = np.linspace(0.1e9, 2e9, 101)
        z = synthesize_rlc_inductor_z(freqs, L0, RS0, CP0)
        p1 = write_touchstone_series_2port(tmp_path / "a.s2p", freqs, z, comment="x")
        p2 = write_touchstone_series_2port(tmp_path / "b.s2p", freqs, z, comment="x")
        assert sha256_file(p1) == sha256_file(p2)

    def test_touchstone_header_and_columns(self, tmp_path: Path):
        freqs = np.linspace(0.1e9, 2e9, 11)
        path = _write_inductor_s2p(tmp_path / "h.s2p", L0, RS0, CP0, freqs)
        lines = path.read_text(encoding="ascii").splitlines()
        assert lines[-13].startswith("! ")          # 注释头
        assert lines[-12] == "# GHZ S RI R 50"      # 选项行（GHz/RI/50Ω）
        assert len(lines[-1].split()) == 9          # f + 4×(Re,Im)

    def test_one_port_roundtrip(self, tmp_path: Path):
        freqs = np.linspace(0.1e9, 1e9, 51)
        z = synthesize_rlc_inductor_z(freqs, L0, RS0, CP0)
        path = write_touchstone_one_port(tmp_path / "o.s1p", freqs, z, comment="1port")
        curve = load_impedance_curve(path)
        assert curve.n_ports == 1
        assert np.max(np.abs(curve.z - z) / np.abs(z)) < 1e-9

    def test_capacitor_generator_branch_values(self):
        # C 取自 L 匹配内核的 shunt 槽位、ESL 由 SRF=20GHz 闭式反推（无手编数字）
        c_f = next(e.value for e in synthesize_l_match(50.0, 25.0, F0_GHZ).elements if e.role == "shunt")
        esl = 1.0 / ((2.0 * math.pi * 20e9) ** 2 * c_f)
        freqs = np.array([1e9, 2e9])
        z = synthesize_rlc_capacitor_z(freqs, c_f, 0.05, esl)
        w = 2.0 * math.pi * freqs
        assert np.allclose(z.real, 0.05)
        assert np.allclose(z.imag, -1.0 / (w * c_f) + w * esl)


class TestSrfExtraction:
    """判据 A：SRF/L_eff/Q 与闭式值对拍（≤0.5% / ≤1% / ≤0.5%）。"""

    @pytest.fixture()
    def seed_curve(self, tmp_path: Path) -> ImpedanceCurve:
        path = _write_inductor_s2p(
            tmp_path / "seed.s2p", L0, RS0, CP0, np.linspace(0.1e9, 10e9, 20001)
        )
        return load_impedance_curve(path)

    def test_srf_z_peak_within_half_percent(self, seed_curve: ImpedanceCurve):
        srf = extract_srf(seed_curve.freqs_hz, seed_curve.z, mode="peak")
        assert srf is not None
        assert abs(srf - SRF0_HZ) / SRF0_HZ <= 0.005

    def test_srf_im_zero_crossing_within_half_percent(self, seed_curve: ImpedanceCurve):
        crossings = im_zero_crossings(seed_curve.freqs_hz, seed_curve.z)
        inductive_end = [f for f, direction in crossings if direction == "inductive_to_capacitive"]
        assert inductive_end, "合成电感必须存在感性→容性过零"
        assert abs(inductive_end[0] - SRF0_HZ) / SRF0_HZ <= 0.005

    def test_low_freq_leff_within_1pct(self, seed_curve: ImpedanceCurve):
        for f_hz in (0.1e9, 0.2e9):  # 频带 [0.1, 10] GHz 内取低频点
            z = seed_curve.at(f_hz)
            assert abs(effective_inductance(f_hz, z) - L0) / L0 <= 0.01

    def test_q_factor_matches_omega_l_over_rs(self, seed_curve: ImpedanceCurve):
        f_hz = 0.1e9
        q = q_factor(seed_curve.at(f_hz))
        q_ideal = 2.0 * math.pi * f_hz * L0 / RS0
        assert abs(q - q_ideal) / q_ideal <= 0.005

    def test_capacitor_srf_valley_within_half_percent(self, tmp_path: Path):
        c_f = next(e.value for e in synthesize_l_match(50.0, 25.0, F0_GHZ).elements if e.role == "shunt")
        esr = 0.05
        esl = 1.0 / ((2.0 * math.pi * 20e9) ** 2 * c_f)  # SRF 目标 20GHz，闭式反推
        srf_analytic = 1.0 / (2.0 * math.pi * math.sqrt(c_f * esl))
        freqs = np.linspace(0.2e9, 30e9, 4001)  # 带内含 SRF（带边极值会返回 None）
        z = synthesize_rlc_capacitor_z(freqs, c_f, esr, esl)
        srf = extract_srf(freqs, z, mode="valley")
        assert srf is not None
        assert abs(srf - srf_analytic) / srf_analytic <= 0.005
        # 谷深 = ESR（串联谐振阻抗最小值）；网格相对步长 7.45MHz/20GHz≈3.7e-4
        # 量化谷深（实测 3.2e-4），断言 1e-3
        assert abs(np.min(np.abs(z)) - esr) / esr < 1e-3

    def test_srf_at_band_edge_returns_none(self, tmp_path: Path):
        # 带边即峰：SRF 不在带内 → None（不硬凑数字）
        freqs = np.linspace(0.1e9, 0.5e9, 401)
        z = synthesize_rlc_inductor_z(freqs, L0, RS0, CP0)
        assert extract_srf(freqs, z, mode="peak") is None

    def test_extract_srf_rejects_bad_mode(self, seed_curve: ImpedanceCurve):
        with pytest.raises(ValueError, match="peak/valley"):
            extract_srf(seed_curve.freqs_hz, seed_curve.z, mode="median")


# ─── 判据 B：匹配链真元件替换 ────────────────────────────────────────────────

def _skrf_s11_db(result, freqs_ghz: np.ndarray) -> np.ndarray:
    """沿用 test_matching 风格：to_skrf_network → 源端 |S11|（dB 深度）。"""
    network = to_skrf_network(result, list(freqs_ghz))
    magnitude = np.abs(np.asarray(network.s[:, 0, 0]))
    return -20.0 * np.log10(np.where(magnitude == 0.0, np.nan, magnitude))


class TestChainRecursion:
    """真链递推：理想回代身份一致 + skrf ±0.1dB 逐点对拍。"""

    GRID = np.linspace(0.75 * F0_GHZ, 1.25 * F0_GHZ, 61)

    def test_identity_no_replacement(self, match_result):
        for f in self.GRID:
            mine = chain_input_impedance(match_result.elements, match_result.z_load, float(f), None)
            reference = match_result.input_impedance(float(f))
            assert abs(mine - reference) <= 1e-12 * max(1.0, abs(reference))

    def test_identity_with_ideal_back_substitution(self, match_result):
        """用理想 LCElement 阻抗走 replacements 通道回代，与闭式递推身份一致。"""
        for f in self.GRID:
            mine = chain_input_impedance(
                match_result.elements, match_result.z_load, float(f),
                {i: e.impedance(2.0 * math.pi * float(f) * 1e9)
                 for i, e in enumerate(match_result.elements)},
            )
            reference = match_result.input_impedance(float(f))
            assert abs(mine - reference) <= 1e-12 * max(1.0, abs(reference))

    def test_skrf_pointwise_within_0p1db(self, match_result):
        grid = np.linspace(0.7 * F0_GHZ, 1.3 * F0_GHZ, 61)
        sim_db = _skrf_s11_db(match_result, grid)
        checked = 0
        for f, sim in zip(grid, sim_db, strict=True):
            if not math.isfinite(sim) or sim > 60.0:  # 零点邻域无有效 dB 比较
                continue
            z = chain_input_impedance(match_result.elements, match_result.z_load, float(f), None)
            mine = -20.0 * math.log10(abs((z - match_result.z_source) / (z + match_result.z_source)))
            assert abs(mine - float(sim)) < 0.1
            checked += 1
        assert checked >= 55


class TestMatchDeviationReport:
    """偏差报告：series/shunt 两槽位均覆盖（§10.22 #24 口径）。"""

    def test_series_slot_report(self, match_result, series_slot_curve: ImpedanceCurve):
        slot = next(i for i, e in enumerate(match_result.elements) if e.role == "series")
        report = match_deviation_report(match_result, {slot: series_slot_curve})
        entry = report.slots[0]
        assert (entry.slot_kind, entry.slot_role, entry.slot_index) == ("L", "series", slot)
        # L_eff/L_nom = 1/(1−(f0/SRF)²) 闭式对拍（合成模型确定性）
        l_ideal = next(e.value for e in match_result.elements if e.role == "series")
        srf_analytic = 1.0 / (2.0 * math.pi * math.sqrt(l_ideal * 0.05e-12))
        assert entry.srf_over_f0 is not None
        assert abs(entry.srf_over_f0 - srf_analytic / 1e9 / F0_GHZ) / (srf_analytic / 1e9 / F0_GHZ) <= 0.005
        assert entry.eff_over_nom is not None
        assert abs(entry.eff_over_nom - 1.0 / (1.0 - (F0_GHZ / (srf_analytic / 1e9)) ** 2)) < 2e-3
        assert 0.95 < entry.eff_over_nom < 1.05
        assert entry.series_crosscheck_rel is not None and entry.series_crosscheck_rel < 1e-9
        # 深度与偏移：真链 f0 深度有限劣化；最佳频点下移（L_eff 抬升）且幅度有界
        assert 3.0 < report.real_match_depth_db_f0 < 100.0
        assert report.delta_match_depth_db_f0 == -math.inf  # 理想链 f0 精确匹配（+inf 深度）
        assert report.band_max_abs_delta_db is not None and report.band_max_abs_delta_db > 0.1
        assert report.n_band_points_compared >= 90
        assert -0.1 * F0_GHZ < report.best_freq_offset_ghz < 0.0

    def test_shunt_slot_report(self, match_result, tmp_path: Path):
        slot = next(i for i, e in enumerate(match_result.elements) if e.role == "shunt")
        c_ideal = next(e.value for e in match_result.elements if e.role == "shunt")
        esr = 0.05
        srf_target = 20e9
        esl = 1.0 / ((2.0 * math.pi * srf_target) ** 2 * c_ideal)
        z = synthesize_rlc_capacitor_z(BAND_SRF_HZ, c_ideal, esr, esl)
        path = write_touchstone_series_2port(tmp_path / "shunt_c.s2p", BAND_SRF_HZ, z, comment="shunt slot")
        curve = load_impedance_curve(path)
        report = match_deviation_report(match_result, {slot: curve})
        entry = report.slots[0]
        assert (entry.slot_kind, entry.slot_role) == ("C", "shunt")
        c_eff = effective_capacitance(F0_GHZ * 1e9, curve.at(F0_GHZ * 1e9))
        assert entry.eff_over_nom is not None
        assert 0.95 < entry.eff_over_nom < 1.05
        assert abs(entry.eff_over_nom - c_eff / c_ideal) < 1e-9
        assert entry.srf_over_f0 is not None
        assert abs(entry.srf_over_f0 - srf_target / 1e9 / F0_GHZ) / (srf_target / 1e9 / F0_GHZ) <= 0.005
        assert 3.0 < report.real_match_depth_db_f0 < 100.0
        assert report.band_max_abs_delta_db is not None and report.band_max_abs_delta_db > 0.1
        assert -0.1 * F0_GHZ < report.best_freq_offset_ghz < 0.0

    def test_report_dict_jsonable_and_curve_replacement(self, match_result, series_slot_curve: ImpedanceCurve):
        """复数常量替换通道 + 报告 dict 经 service _jsonable 严格 JSON（inf→None）。"""
        slot = next(i for i, e in enumerate(match_result.elements) if e.role == "series")
        z_const = series_slot_curve.at(F0_GHZ * 1e9)
        report = match_deviation_report(match_result, {slot: z_const})
        from rfauto.service.vendor_passives_service import _jsonable

        text = json.dumps(_jsonable(report.to_dict()), allow_nan=False)
        assert "f0_ghz" in text and "slots" in text


# ─── 判据 C：registry 与条款门 ───────────────────────────────────────────────

def _entry_dict(**overrides: object) -> dict:
    base: dict = {
        "vendor": "synthetic", "mpn": "SYNTH-L-10NH", "type": "inductor",
        "nominal_value": L0, "srf_ghz": SRF0_HZ / 1e9, "esr_ohm": RS0,
        "model_file": "seed_l.s2p", "sha256": None, "source_url": "",
        "license_note": "合成种子件（本仓生成，无厂商条款约束）", "synthetic": True,
        "downloaded_at": None,
    }
    base.update(overrides)
    return base


class TestRegistryProvenance:
    """缺文件 KeyError / 哈希篡改 ValueError / synthetic 不钉哈希 / 缺文件 skip-not-fail。"""

    def test_missing_part_id_raises_keyerror(self, tmp_path: Path):
        catalog = tmp_path / "catalog.yaml"
        write_catalog(catalog, {})
        with pytest.raises(KeyError, match="no_such_part"):
            load_part("no_such_part", catalog_path=catalog)

    def test_missing_file_raises_keyerror(self, tmp_path: Path):
        catalog = tmp_path / "catalog.yaml"
        entry = VendorPartEntry.from_dict("ghost", _entry_dict(
            synthetic=False, sha256="ab" * 32, model_file="ghost.s2p"))
        write_catalog(catalog, {"ghost": entry})
        with pytest.raises(KeyError, match=r"ghost\.s2p"):
            load_part("ghost", catalog_path=catalog)

    def test_synthetic_generate_hash_verify_roundtrip(self, tmp_path: Path):
        """synthetic 哈希在同一会话内"生成→取哈希→校验"，不在 git 钉死数字。"""
        catalog = tmp_path / "catalog.yaml"
        entry = VendorPartEntry.from_dict("synth_l", _entry_dict())
        path, sha = synthesize_seed_model_file(entry, tmp_path)
        assert path.exists()
        path2, sha2 = synthesize_seed_model_file(entry, tmp_path)  # 再现字节相同
        assert sha == sha2 and path2 == path
        entries = {"synth_l": VendorPartEntry.from_dict("synth_l", _entry_dict(sha256=None))}
        write_catalog(catalog, entries)
        loaded = load_part("synth_l", catalog_path=catalog, directory=tmp_path)
        assert loaded.entry.part_id == "synth_l"
        assert loaded.curve.n_ports == 2

    def test_hash_tamper_raises_valueerror(self, tmp_path: Path):
        catalog = tmp_path / "catalog.yaml"
        entry = VendorPartEntry.from_dict("synth_l", _entry_dict())
        path, sha = synthesize_seed_model_file(entry, tmp_path)
        write_catalog(catalog, {"synth_l": VendorPartEntry.from_dict(
            "synth_l", _entry_dict(synthetic=False, sha256=sha))})
        assert load_part("synth_l", catalog_path=catalog, directory=tmp_path)  # 先验 OK
        path.write_text(path.read_text(encoding="ascii") + "! tampered\n", encoding="ascii")
        with pytest.raises(ValueError, match="sha256"):
            load_part("synth_l", catalog_path=catalog, directory=tmp_path)

    def test_real_part_requires_sha256(self):
        with pytest.raises(ValueError, match="sha256"):
            VendorPartEntry.from_dict("real_no_sha", _entry_dict(synthetic=False))

    def test_real_part_sha_mismatch_detected(self, tmp_path: Path):
        entry = VendorPartEntry.from_dict("real", _entry_dict(synthetic=False, sha256="cd" * 32))
        assert entry.sha256 == "cd" * 32  # 真实条目允许登记哈希（provenance 索引）
        catalog = tmp_path / "catalog.yaml"
        path, _ = synthesize_seed_model_file(VendorPartEntry.from_dict("synth_l", _entry_dict()), tmp_path)
        write_catalog(catalog, {"real": VendorPartEntry.from_dict(
            "real", _entry_dict(synthetic=False, sha256="cd" * 32, model_file=path.name))})
        with pytest.raises(ValueError, match="provenance"):
            load_part("real", catalog_path=catalog, directory=tmp_path)

    def test_validate_catalog_skip_not_fail(self, tmp_path: Path):
        """四态盘点：ok / file_missing / unverified / hash_mismatch，绝不抛。"""
        catalog = tmp_path / "catalog.yaml"
        _, sha_ok = synthesize_seed_model_file(
            VendorPartEntry.from_dict("tmp", _entry_dict(model_file="ok_l.s2p")), tmp_path)
        parts = {
            "ok_part": VendorPartEntry.from_dict("ok_part", _entry_dict(
                synthetic=False, sha256=sha_ok, model_file="ok_l.s2p")),
            "ghost_part": VendorPartEntry.from_dict("ghost_part", _entry_dict(
                synthetic=False, sha256="ab" * 32, model_file="ghost.s2p")),
            "synth_part": VendorPartEntry.from_dict("synth_part", _entry_dict(
                model_file="synth_l.s2p")),
            "tampered_part": VendorPartEntry.from_dict("tampered_part", _entry_dict(
                synthetic=False, sha256="cd" * 32, model_file="ok_l.s2p")),
        }
        synthesize_seed_model_file(VendorPartEntry.from_dict("synth_part", _entry_dict(
            model_file="synth_l.s2p")), tmp_path)
        write_catalog(catalog, parts)
        statuses = {s.part_id: s.status for s in validate_catalog(catalog, tmp_path)}
        assert statuses == {
            "ok_part": "ok",
            "ghost_part": "file_missing",
            "synth_part": "unverified",
            "tampered_part": "hash_mismatch",
        }
        listing = list_vendor_parts(catalog_path=catalog, directory=tmp_path)
        json.dumps(listing, allow_nan=False)  # 严格 JSON
        by_id = {p["part_id"]: p["status"] for p in listing["parts"]}
        assert by_id == statuses

    def test_validate_catalog_broken_file_reports_not_raises(self, tmp_path: Path):
        catalog = tmp_path / "catalog.yaml"
        catalog.write_text("not: [valid\n  yaml: {", encoding="utf-8")
        statuses = validate_catalog(catalog)
        assert statuses[0].status == "invalid_entry"

    def test_missing_catalog_raises_keyerror_in_strict_load(self, tmp_path: Path):
        with pytest.raises(KeyError, match="catalog"):
            load_part("x", catalog_path=tmp_path / "absent.yaml")


# ─── 判据 C/D：service 三入口 ────────────────────────────────────────────────

class TestServiceEntryPoints:
    def test_run_match_deviation_by_model_file(self, match_result, series_slot_path: Path):
        slot = next(i for i, e in enumerate(match_result.elements) if e.role == "series")
        report = run_match_deviation(
            z_source=50.0, z_load=25.0, f0_ghz=F0_GHZ, slot_index=slot,
            model_file=str(series_slot_path),
        )
        json.dumps(report, allow_nan=False)
        assert report["model_ref"].endswith(".s2p")
        assert 3.0 < report["real_match_depth_db_f0"] < 100.0
        assert report["slots"][0]["slot_kind"] == "L"
        assert report["curve_diag"]["n_ports"] == 2

    def test_run_match_deviation_by_part_id(self, tmp_path: Path, match_result, series_slot_path: Path):
        catalog = tmp_path / "catalog.yaml"
        l_ideal = next(e.value for e in match_result.elements if e.role == "series")
        register_model_entry(
            catalog_path=catalog, part_id="synth_series_l", vendor="synthetic",
            mpn="SYNTH-L-SERIES", part_type="inductor", nominal_value=l_ideal,
            model_file=series_slot_path.name, sha256=sha256_file(series_slot_path),
            srf_ghz=1.0 / (2.0 * math.pi * math.sqrt(l_ideal * 0.05e-12)) / 1e9, esr_ohm=0.3,
            license_note="合成件",
        )
        report = run_match_deviation(
            z_source=50.0, z_load=25.0, f0_ghz=F0_GHZ, slot_index=0,
            part_id="synth_series_l", catalog_path=catalog, directory=tmp_path,
        )
        json.dumps(report, allow_nan=False)
        assert report["model_ref"] == "registry:synth_series_l"

    def test_run_match_deviation_requires_exactly_one_source(self):
        with pytest.raises(ValueError, match="二选一"):
            run_match_deviation(50.0, 25.0, F0_GHZ, 0)
        with pytest.raises(ValueError, match="二选一"):
            run_match_deviation(50.0, 25.0, F0_GHZ, 0,
                                model_file="a.s2p", part_id="b")

    def test_run_match_deviation_slot_out_of_range(self, series_slot_path: Path):
        with pytest.raises(ValueError, match="slot_index"):
            run_match_deviation(50.0, 25.0, F0_GHZ, 7, model_file=str(series_slot_path))

    def test_register_rejects_duplicate_without_replace(self, tmp_path: Path):
        catalog = tmp_path / "catalog.yaml"
        kwargs = dict(
            catalog_path=catalog, part_id="dup", vendor="v", mpn="m",
            part_type="inductor", nominal_value=1e-9, model_file="x.s2p",
            sha256="ab" * 32,
        )
        register_model_entry(**kwargs)
        with pytest.raises(ValueError, match="replace"):
            register_model_entry(**kwargs)
        register_model_entry(**{**kwargs, "mpn": "m2", "replace": True})
        assert read_catalog(catalog)["dup"].mpn == "m2"

    def test_register_rejects_hash_file_mismatch(self, tmp_path: Path, series_slot_path: Path):
        with pytest.raises(ValueError, match="登记哈希与文件不符"):
            register_model_entry(
                catalog_path=tmp_path / "catalog.yaml", part_id="bad", vendor="v", mpn="m",
                part_type="inductor", nominal_value=1e-9,
                model_file=str(series_slot_path), sha256="ef" * 32,
            )

    def test_list_vendor_parts_missing_catalog(self, tmp_path: Path):
        listing = list_vendor_parts(catalog_path=tmp_path / "absent.yaml")
        assert listing["exists"] is False and listing["parts"] == []


# ─── 判据 D：下载器（monkeypatch 钉死通道，#139 零真网）─────────────────────

class TestDownloader:
    def test_filename_from_url(self):
        assert dl.filename_from_url("https://example.com/models/0402DC-1N8.s2p?token=x") == "0402DC-1N8.s2p"
        assert dl.filename_from_url("https://example.com/a%20b/LQM%2010nH.s2p") == "LQM_10nH.s2p"
        assert dl.filename_from_url("https://example.com/dir/") == "model.s2p"
        assert dl.filename_from_url("https://example.com/") == "model.s2p"

    def test_sanitize_filename_whitelist(self):
        assert dl.sanitize_filename("a/b\\c:d*e?.s2p") == "a_b_c_d_e_.s2p"
        assert dl.sanitize_filename("") == "model.s2p"

    def test_fetch_uses_explicit_user_agent(self, monkeypatch):
        captured: dict = {}

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b"payload"

        def fake_urlopen(request, timeout=None):
            captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
            captured["timeout"] = timeout
            return _FakeResponse()

        monkeypatch.setattr(dl, "urlopen", fake_urlopen)
        assert dl.fetch_bytes("https://example.com/x.s2p", timeout_s=5.0) == b"payload"
        assert "rfauto" in captured["headers"]["user-agent"]
        assert captured["timeout"] == 5.0

    def test_download_model_writes_and_hashes(self, tmp_path: Path, monkeypatch):
        payload = b"# GHZ S RI R 50\n! fake\n"
        monkeypatch.setattr(dl, "fetch_bytes", lambda url, timeout_s=60.0: payload)
        path, sha, got = dl.download_model("https://example.com/models/X.s2p", tmp_path)
        assert path == tmp_path / "X.s2p" and path.read_bytes() == payload == got
        assert sha == hashlib.sha256(payload).hexdigest()

    def test_main_register_flow_end_to_end(self, tmp_path: Path, monkeypatch):
        """下载→落盘→--register 全链（fetch 钉死；catalog/文件都在 tmp）。"""
        freqs = np.linspace(0.1e9, 10e9, 501)
        staged = _write_inductor_s2p(tmp_path / "staged.s2p", L0, RS0, CP0, freqs)
        payload = staged.read_bytes()
        monkeypatch.setattr(dl, "fetch_bytes", lambda url, timeout_s=60.0: payload)
        catalog = tmp_path / "catalog.yaml"
        code = dl.main([
            "--url", "https://www.coilcraft.com/models/0402DC-1N8.s2p",
            "--dest", str(tmp_path), "--filename", "0402dc_1n8.s2p",
            "--register", "--catalog", str(catalog),
            "--part-id", "coilcraft_0402dc_1n8", "--vendor", "coilcraft",
            "--mpn", "0402DC-1N8", "--type", "inductor",
            "--nominal-value", "1.8e-9",
            "--source-page", "https://www.coilcraft.com/en-us/models/spice/",
            "--license-note", "Coilcraft 免费下载用于设计；禁止再分发模型文件",
        ])
        assert code == 0
        entries = read_catalog(catalog)
        assert entries["coilcraft_0402dc_1n8"].sha256 == hashlib.sha256(payload).hexdigest()
        assert entries["coilcraft_0402dc_1n8"].source_url.endswith("spice/")
        statuses = {s.part_id: s.status for s in validate_catalog(catalog, tmp_path)}
        assert statuses["coilcraft_0402dc_1n8"] == "ok"
        loaded = load_part("coilcraft_0402dc_1n8", catalog_path=catalog, directory=tmp_path)
        assert loaded.curve.n_ports == 2

    def test_main_register_requires_license_note(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(dl, "fetch_bytes", lambda url, timeout_s=60.0: b"! x\n")
        catalog = tmp_path / "catalog.yaml"
        code = dl.main([
            "--url", "https://example.com/x.s2p", "--dest", str(tmp_path),
            "--register", "--catalog", str(catalog), "--part-id", "p",
            "--vendor", "v", "--mpn", "m", "--type", "inductor",
            "--nominal-value", "1e-9",
        ])
        assert code == 2
        assert not catalog.exists()

    def test_main_register_requires_metadata(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(dl, "fetch_bytes", lambda url, timeout_s=60.0: b"! x\n")
        code = dl.main([
            "--url", "https://example.com/x.s2p", "--dest", str(tmp_path),
            "--register", "--catalog", str(tmp_path / "c.yaml"),
            "--license-note", "n",
        ])
        assert code == 2

    def test_main_without_register_skips_catalog(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(dl, "fetch_bytes", lambda url, timeout_s=60.0: b"! x\n")
        code = dl.main(["--url", "https://example.com/y.s2p", "--dest", str(tmp_path)])
        assert code == 0
        assert (tmp_path / "y.s2p").exists()
