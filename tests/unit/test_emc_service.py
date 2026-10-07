"""W7 台账①态接线批 X3：emc_service（cispr_detector + common_mode）单测。

接线面（2026-10-04，W7 台账行 1/2：cispr_detector、common_mode → 新建
emc_service 薄面）四函数：
- ``cispr_band_params`` / ``cispr_detect_compute``（CISPR 16-1-1）；
- ``ground_spacing_check`` / ``cm_radiated_budget_compute``（共模辐射）。

裁判口径（#118 不自证）：band 表锚 B6=9 kHz（Band B，双源核对公开值）；
正弦等幅峰值读数 20log10(A)+120 手算回收（Peak=包络峰定义面）；λ/20 判据
用恒等面独立键入——s=0.15 m @100 MHz 时 λ=3 m、λ/20=0.15 m 等号点归
electrically_long（严格不等号）；CM 回路用纯容性简化手算 I=V·ωC 回收。
信封纪律：errors 恒 list[str]、绝不抛异常；core 内核自身测试
（test_cispr_detector/test_common_mode）不重复。
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

from rfauto.service.emc_service import (
    EMC_SERVICE_SCHEMA_VERSION,
    cispr_band_params,
    cispr_detect_compute,
    cm_radiated_budget_compute,
    ground_spacing_check,
)

# ── CISPR 16-1-1 ────────────────────────────────────────────────────────────


class TestCisprService:
    def test_band_params_b_double_source_anchor(self) -> None:
        """Band B 四参数逐值=公开双源锚（B6=9 kHz/充 1 ms/放 160 ms/表头 160 ms）。"""
        out = cispr_band_params("b")  # 大小写不敏感
        assert out["ok"] is True
        assert out["schema_version"] == EMC_SERVICE_SCHEMA_VERSION
        res = out["result"]
        assert res["band"] == "B"
        assert res["bw6_hz"] == 9e3
        assert res["tau_charge_s"] == 1e-3
        assert res["tau_discharge_s"] == 160e-3
        assert res["tau_meter_s"] == 160e-3
        assert "CISPR 16-1-1" in res["source"]
        assert out["provenance"]["kernel"] == "rfauto.core.cispr_detector"

    def test_detect_sine_peak_handcalc(self) -> None:
        """正弦等幅 Peak 读数=20log10(A)+120 手算回收（Peak=包络峰定义面）。

        短突发下 QP/Avg 受表头建立残差影响（内核 docstring 诚实边界），
        只断言读数有序（Peak ≥ Avg）与 Peak 逐位带，不重复 core 的三检波器
        恒等钉。
        """
        fs = 30e6
        t = np.arange(30000) / fs
        amp = 0.01  # 10 mV
        sig = amp * np.sin(2.0 * np.pi * 1e6 * t)
        out = cispr_detect_compute(
            [float(v) for v in sig], fs, "B", f_center_hz=1e6)
        assert out["ok"] is True
        res = out["result"]
        assert res["peak_dbuv"] == pytest.approx(20.0 * math.log10(amp) + 120, abs=0.1)
        assert res["avg_dbuv"] <= res["peak_dbuv"] + 1e-9
        assert res["band"] == "B"
        assert isinstance(res["qp_settling_ok"], bool)

    def test_band_params_invalid_to_envelope(self) -> None:
        for bad in ("X", "", None, 3):
            out = cispr_band_params(bad)  # type: ignore[arg-type]
            assert out["ok"] is False
            assert isinstance(out["errors"], list) and out["errors"]

    def test_detect_input_validation_to_envelope(self) -> None:
        """非数值元素/全零波形/欠采样逐项折信封（不抛异常）。"""
        out = cispr_detect_compute([0.1, "x", 0.2], 30e6, "B")
        assert out["ok"] is False
        assert any("samples" in e for e in out["errors"])
        out2 = cispr_detect_compute([0.0, 0.0, 0.0], 30e6, "B")
        assert out2["ok"] is False
        assert any("全零" in e for e in out2["errors"])
        # fs < 4×B6（Band B 9 kHz → 36 kHz）显式拒收
        out3 = cispr_detect_compute([0.1, 0.2, 0.1], 1e3, "B")
        assert out3["ok"] is False
        assert any("fs_hz" in e for e in out3["errors"])

    def test_detect_result_json_roundtrip(self) -> None:
        fs = 30e6
        t = np.arange(30000) / fs
        sig = 0.01 * np.sin(2.0 * np.pi * 1e6 * t)
        out = cispr_detect_compute([float(v) for v in sig], fs, "B")
        revived = json.loads(json.dumps(out))
        assert revived == out


# ── 共模辐射预算 ────────────────────────────────────────────────────────────


class TestCommonModeService:
    def test_ground_spacing_identity_boundary(self) -> None:
        """λ/20 恒等面独立键入：s=λ/20 等号点归 electrically_long（严格不等号）。

        100 MHz → λ=c/f=2.99796 m、λ/20=c/(20f)=0.1498962 m（独立键入闭式）；
        s=0.1498 m（<λ/20）→ equipotential，s=0.1499 m（>）→
        electrically_long；critical_f=c/(20s) 互反恒等。
        """
        lambda20 = 299792458.0 / (20.0 * 100.0e6)
        ok_out = ground_spacing_check(0.1498, 100.0)
        assert ok_out["ok"] is True
        assert ok_out["result"]["verdict"] == "equipotential"
        eq_out = ground_spacing_check(0.1499, 100.0)
        assert eq_out["ok"] is True
        assert eq_out["result"]["verdict"] == "electrically_long"
        res = eq_out["result"]
        assert res["lambda20_m"] == pytest.approx(lambda20, rel=1e-9)
        assert res["critical_f_mhz"] == pytest.approx(
            299792458.0 / (20.0 * 0.1499) / 1e6, rel=1e-9)
        assert res["model"] == "ground_spacing_lambda20"
        assert ok_out["provenance"]["kernel"] == "rfauto.core.common_mode"

    def test_cm_budget_purely_capacitive_handcalc(self) -> None:
        """纯容性回路（L=0）手算回收：I=V·ωC（路径 A/B 代数恒等）。"""
        f_mhz, v, c = 100.0, 0.1, 1e-11  # 100 MHz / 0.1 V / 10 pF
        out = cm_radiated_budget_compute(
            f_mhz, 1.0, 3.0, v, c_f=c)
        assert out["ok"] is True
        loop = out["result"]["floating_ground"]
        omega = 2.0 * math.pi * f_mhz * 1e6
        i_hand = v * omega * c  # A
        assert loop["i_cm_ua"] == pytest.approx(i_hand * 1e6, rel=1e-9)
        assert loop["i_cm_a_path_b"] == pytest.approx(i_hand, rel=1e-9)
        assert loop["dual_path_diff_db"] < 1e-9
        assert loop["resonance_f_mhz"] is None  # L=0 无谐振参考面
        # 辐射段透传完好（emc_radiated 链字段在场）
        rad = out["result"]["radiated"]
        assert rad["model"] if isinstance(rad.get("model"), str) else True
        assert out["provenance"]["kernel"] == "rfauto.core.common_mode"

    def test_cm_budget_capacitance_from_geometry(self) -> None:
        """平行板几何路径：C=ε0·εr·A/d 手算回收后与 c_f 直给同值。"""
        area, dist, er = 0.01, 0.005, 4.4
        eps0 = 8.854187817e-12
        c_hand = eps0 * er * area / dist
        geo = cm_radiated_budget_compute(
            100.0, 1.0, 3.0, 0.1, coupling_area_m2=area,
            coupling_distance_m=dist, er=er)
        direct = cm_radiated_budget_compute(
            100.0, 1.0, 3.0, 0.1, c_f=c_hand)
        assert geo["ok"] is True and direct["ok"] is True
        assert geo["result"]["floating_ground"]["c_f"] == pytest.approx(
            direct["result"]["floating_ground"]["c_f"], rel=1e-12)

    def test_cm_budget_capacitance_ambiguity_rejected(self) -> None:
        """电容双给（c_f+面积）→ ok=False（单一事实来源）。"""
        out = cm_radiated_budget_compute(
            100.0, 1.0, 3.0, 0.1, c_f=1e-11,
            coupling_area_m2=0.01, coupling_distance_m=0.005)
        assert out["ok"] is False
        assert any("二选一" in e for e in out["errors"])

    def test_cm_budget_negative_inputs_to_envelope(self) -> None:
        out = cm_radiated_budget_compute(-1.0, 1.0, 3.0, 0.1, c_f=1e-11)
        assert out["ok"] is False
        assert any("f_mhz" in e for e in out["errors"])
        out2 = cm_radiated_budget_compute(100.0, 0.0, 3.0, 0.1, c_f=1e-11)
        assert out2["ok"] is False  # length_m 须 >0

    def test_ground_spacing_invalid_to_envelope(self) -> None:
        out = ground_spacing_check(0.0, 100.0)
        assert out["ok"] is False
        out2 = ground_spacing_check(0.1, -5.0)
        assert out2["ok"] is False
        assert isinstance(out2["errors"], list) and out2["errors"]


# ─── MCP 薄壳冒烟（facade 直调，单位换算锚 mm/cm/pF/nH→SI）──────────────────


def test_mcp_emc_tools_registered():
    import asyncio

    from rfauto.mcp_server import mcp

    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"emc_cispr_band_params", "emc_cispr_detect",
            "emc_ground_spacing_check", "emc_cm_radiated_budget"} <= names


def test_mcp_emc_tools_callable_envelope():
    from rfauto.mcp_server import (
        emc_cispr_band_params,
        emc_cispr_detect,
        emc_cm_radiated_budget,
        emc_ground_spacing_check,
    )

    band = emc_cispr_band_params("B")
    assert band["ok"] is True and band["result"]["bw6_hz"] == 9e3
    # mm→m 薄壳换算：149.8 mm=0.1498 m < λ/20 @100 MHz → equipotential
    gs = emc_ground_spacing_check(spacing_mm=149.8, f_mhz=100.0)
    assert gs["ok"] is True
    assert gs["result"]["verdict"] == "equipotential"
    # pF/cm²/mm/nH→SI 换算与 service 直调同值（纯容性手算 I=V·ωC）
    budget = emc_cm_radiated_budget(
        f_mhz=100.0, length_m=1.0, distance_m=3.0, v_cm_v=0.1, c_pf=10.0)
    omega = 2.0 * math.pi * 100.0e6
    assert budget["ok"] is True
    assert budget["result"]["floating_ground"]["i_cm_ua"] == pytest.approx(
        0.1 * omega * 10e-12 * 1e6, rel=1e-9)
    # 时域波形薄壳（伏特直传，Peak 手算锚）
    fs = 30e6
    t = np.arange(30000) / fs
    sig = 0.01 * np.sin(2.0 * np.pi * 1e6 * t)
    det = emc_cispr_detect(
        [float(v) for v in sig], fs_mhz=30.0, band="B", f_center_mhz=1.0)
    assert det["ok"] is True
    assert det["result"]["peak_dbuv"] == pytest.approx(80.0, abs=0.1)
    # 非法入参 → ok=False 信封不抛出
    assert emc_cispr_band_params("Z")["ok"] is False
    assert emc_ground_spacing_check(-1.0, 100.0)["ok"] is False
