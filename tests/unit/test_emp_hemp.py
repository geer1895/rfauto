"""EMP/HEMP 常量表测试（ge8c 席C6，round19 EMP 小包）。

锚定：
- 双源逐格（#df6-⑨ 引用腐坏纪律）：E1 时间参数 S2(DOE)∩S3(PIER C/IEC)
  复算对拍 ≤5%；E2/E3 单源格必须如实 dual_source=False 且带注记；
- MIL-STD-464C §5.3 表：逐格 spot-check 抽行 + 全覆盖连续性守卫；
- 波形内核：α/β/K 数值复算 tr/FWHM/峰值（#118 复算裁判，非自证推导）；
- 负例：类型/取值非法显式报错。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.emp_hemp import (
    BELL_FWHM_S,
    BELL_TR_S,
    E1_ALPHA_PER_S,
    E1_BETA_PER_S,
    EMP_SCHEMA,
    HEMP_COMPONENTS,
    HIRF_F_RANGE_MHZ,
    HIRF_TABLES,
    MIL_STD_464C_EMP_POINTER,
    SOURCE_DOE_WF_GUIDE,
    SOURCE_PIER_C100_IEC,
    check_e1_self_consistency,
    e1_double_exponential,
    e1_spectrum,
    hirf_band_for,
    hirf_peak_for,
    hirf_platforms,
    validate_hirf_tables,
)


class TestHirfTables:
    """MIL-STD-464C §5.3 外部 RF EME 表（S1 逐格转录锚）。"""

    def test_schema_and_platforms(self) -> None:
        assert EMP_SCHEMA == "rfauto-emp-hemp-v1"
        assert hirf_platforms() == ["fixed_wing", "ground", "rotary_wing"]

    def test_registry_valid(self) -> None:
        # 连续性/单调性/峰值均值序/全覆盖守卫
        assert validate_hirf_tables() == []

    def test_each_table_23_rows(self) -> None:
        for rows in HIRF_TABLES.values():
            assert len(rows) == 23

    def test_ground_spot_rows(self) -> None:
        # TABLE 4 抽行（原文逐格）：1–2 GHz 2452/155；14–18 GHz 8671/243
        b = hirf_band_for("ground", 1500.0)
        assert b is not None and b.table == "TABLE 4"
        assert (b.peak_vm, b.avg_vm) == (2452.0, 155.0)
        b2 = hirf_band_for("ground", 15000.0)
        assert b2 is not None and (b2.peak_vm, b2.avg_vm) == (8671.0, 243.0)

    def test_rotary_spot_rows(self) -> None:
        # TABLE 5 抽行：1–2 GHz 6057/232；5.4–5.9 GHz 9179/657
        b = hirf_band_for("rotary_wing", 1800.0)
        assert b is not None and (b.peak_vm, b.avg_vm) == (6057.0, 232.0)
        b2 = hirf_band_for("rotary_wing", 5600.0)
        assert b2 is not None and (b2.peak_vm, b2.avg_vm) == (9179.0, 657.0)

    def test_fixed_wing_spot_rows(self) -> None:
        # TABLE 6 抽行：0.01–2 MHz 88/27；8.5–11 GHz 6299/238
        b = hirf_band_for("fixed_wing", 1.0)
        assert b is not None and (b.peak_vm, b.avg_vm) == (88.0, 27.0)
        b2 = hirf_band_for("fixed_wing", 9000.0)
        assert b2 is not None and (b2.peak_vm, b2.avg_vm) == (6299.0, 238.0)

    def test_band_edges_closed(self) -> None:
        # 频段端点左闭右闭：0.01 与 50000 均可查
        for f in (HIRF_F_RANGE_MHZ[0], HIRF_F_RANGE_MHZ[1]):
            for p in hirf_platforms():
                assert hirf_band_for(p, f) is not None

    def test_peak_for_json(self) -> None:
        out = hirf_peak_for("ground", 1500.0)
        assert out["ok"] is True
        assert out["peak_vm"] == 2452.0
        assert "MIL-STD-464C" in out["source"]

    def test_unknown_platform_and_out_of_range(self) -> None:
        assert hirf_band_for("ship", 100.0) is None  # 未登记平台不硬凑
        assert hirf_band_for("ground", 0.001) is None  # 越下界
        assert hirf_band_for("ground", 60000.0) is None  # 越上界
        out = hirf_peak_for("ship", 100.0)
        assert out["ok"] is False

    def test_type_and_value_errors(self) -> None:
        with pytest.raises(TypeError):
            hirf_band_for(123, 100.0)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            hirf_band_for("ground", float("nan"))


class TestHempComponents:
    """HEMP E1/E2/E3 常量（S2/S3 双源逐格锚）。"""

    def test_e1_dual_source(self) -> None:
        e1 = HEMP_COMPONENTS["E1"]
        assert e1.rise_time_s == 2.5e-9
        assert e1.fwhm_s == 23.0e-9
        assert e1.amplitude_existing == 25_000.0
        assert e1.amplitude_future == 50_000.0
        assert e1.dual_source is True
        assert SOURCE_DOE_WF_GUIDE in e1.sources
        assert SOURCE_PIER_C100_IEC in e1.sources

    def test_e2_e3_single_source_honest(self) -> None:
        # 单源格必须如实 dual_source=False + 注记（不冒充双源）
        for key in ("E2", "E3A", "E3B"):
            c = HEMP_COMPONENTS[key]
            assert c.dual_source is False
            assert c.sources == (SOURCE_DOE_WF_GUIDE,)
            assert len(c.note) > 10
        e2 = HEMP_COMPONENTS["E2"]
        assert e2.fwhm_s == 693.0e-6
        assert (e2.amplitude_existing, e2.amplitude_future) == (50.0, 100.0)
        assert e2.rise_time_s is None  # 源未给 → 不编
        e3a = HEMP_COMPONENTS["E3A"]
        assert (e3a.amplitude_existing, e3a.amplitude_future) == (40.0, 80.0)
        assert e3a.unit == "V/km"
        e3b = HEMP_COMPONENTS["E3B"]
        assert (e3b.amplitude_existing, e3b.amplitude_future) == (25.0, 50.0)

    def test_components_serializable(self) -> None:
        for c in HEMP_COMPONENTS.values():
            d = c.to_dict()
            assert d["component"] == c.component
            assert isinstance(d["sources"], list)

    def test_mil_std_pointer_not_numbers(self) -> None:
        # 464C §5.6 EMP 涉密指针：只有 statement 无数值（不编公开 HEMP 数）
        assert MIL_STD_464C_EMP_POINTER["status"] == "classified_environment_pointer"
        assert "MIL-STD-2169" in MIL_STD_464C_EMP_POINTER["statement"]


class TestE1WaveformKernel:
    """E1 双指数波形内核（S3 α/β/K 复算裁判）。"""

    def test_constants_source_pinned(self) -> None:
        assert E1_ALPHA_PER_S == 4.0e7
        assert E1_BETA_PER_S == 6.0e8
        assert (BELL_TR_S, BELL_FWHM_S) == (4.1e-9, 184.0e-9)

    def test_self_consistency_passes(self) -> None:
        # α/β/K 必须数值复算出 2.5ns/23ns/50kV/m（双源对拍核心锚）
        out = check_e1_self_consistency()
        assert out["ok"] is True, out
        assert max(out["rel_err"].values()) <= 0.05

    def test_self_consistency_detects_drift(self) -> None:
        # 文献锚改错 → 如实红（复算是裁判不是摆设）
        out = check_e1_self_consistency(tr_ref_s=1.0e-9)
        assert out["ok"] is False

    def test_waveform_peak_value(self) -> None:
        # E(t_p) ≈ 50 kV/m（解析独立复算：K·0.7693）
        t = np.linspace(0.0, 100e-9, 200_001)
        e = e1_double_exponential(t)
        assert float(np.max(e)) == pytest.approx(50_000.0, rel=0.01)

    def test_waveform_nonfinite_and_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            e1_double_exponential(-1e-9)
        with pytest.raises(ValueError):
            e1_double_exponential(float("nan"))

    def test_spectrum_shape(self) -> None:
        # 低频平台、数百 MHz 后衰减（S2 "frequency content in 100's of MHz"）
        f = np.array([1e6, 1e8, 1e9])
        s = e1_spectrum(f)
        assert s[0] > s[1] > s[2] * 10  # 1 GHz 深衰
        assert math.isfinite(float(s[0]))
