"""DP-11 P1/P2：VnaAdapter + pyvisa-sim 全链（criteria.md G1/G4/G8）。

- G1：pyvisa-sim 声明式仪器应答 → 触发扫频 → capture → 校准核验 →
  En 报告全链零硬件；驱动解析失败回退 raw SCPI 逃生口；
- G4：注册表挂载 + CAPABILITIES 如实；
- #139 钉：全部通道 pyvisa-sim/注入 transport，无真实网络/真机调用；
  chdir 隔离（#144），run 目录落 tmp。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rfauto.adapters.em_solver_base import (
    EMSolverConfig,
    EMSolverType,
    get_global_registry,
)
from rfauto.measurement.vna_capture import MOCK_MODEL

#: pyvisa-sim 仪器定义（与 measurement/librevna.py 消费面逐字对齐）
VNA_SIM_YAML = Path(__file__).resolve().parents[1] / "fixtures" / "vna_sim.yaml"

SIM_ADDR_CAL = "TCPIP0::sim-vna::10001::INSTR"
SIM_ADDR_UNCAL = "TCPIP0::sim-vna-uncal::10001::INSTR"


def _vna_config(**extra) -> EMSolverConfig:
    params = {
        "address": SIM_ADDR_CAL,
        "model": "librevna",
        "visa_library": f"{VNA_SIM_YAML}@sim",
        "n_points": 5,
        "ifbw_hz": 1000.0,
        "calkit_id": "wl_2g5_solt_smoke",
    }
    params.update(extra)
    return EMSolverConfig(solver_type=EMSolverType.VNA,
                          freq_range_ghz=(1.0, 3.0), extra_params=params)


@pytest.fixture()
def vna_adapter():
    import rfauto.adapters  # noqa: F401 — 导入副作用完成注册

    adapter = get_global_registry().create(EMSolverType.VNA, _vna_config())
    yield adapter
    adapter.close()


class TestRegistration:
    """G4：注册表挂载 + 能力面如实。"""

    def test_vna_enum_and_registry(self):
        import rfauto.adapters  # noqa: F401

        assert EMSolverType.VNA.value == "vna"
        assert get_global_registry().is_registered(EMSolverType.VNA)

    def test_capabilities_honest(self, vna_adapter):
        caps = vna_adapter.capabilities()
        assert caps.solver_type == "vna"
        assert caps.supports_touchstone_export is True
        assert caps.supports_headless_solve is True
        # 测量=非仿真：仿真侧能力位如实全 False
        assert caps.supports_wave_port is False
        assert caps.supports_lumped_port is False
        assert caps.supports_field_export is False
        assert caps.supports_nf2ff is False
        assert caps.supports_sar is False
        assert caps.supports_optimetrics is False
        assert caps.supports_convergence_report is False
        assert caps.material_models == ()
        assert caps.supported_templates == ()
        assert caps.requires_license is False
        assert caps.availability_gate == "address"

    def test_is_available_false_without_address(self):
        import rfauto.adapters  # noqa: F401

        adapter = get_global_registry().create(
            EMSolverType.VNA,
            EMSolverConfig(solver_type=EMSolverType.VNA, extra_params={}))
        assert adapter.is_available() is False

    def test_unknown_model_rejected_explicitly(self):
        import rfauto.adapters  # noqa: F401

        adapter = get_global_registry().create(
            EMSolverType.VNA,
            _vna_config(model="copper_mountain", address="x"))
        assert adapter.connect() is False

    def test_build_geometry_is_noop_registration(self, vna_adapter):
        assert vna_adapter.build_geometry({"dut": "mline"}) is True


class TestPyvisaSimFullChain:
    """G1：sim 仪器 → 触发扫频 → capture → 校准 → En，零硬件全链。"""

    def test_solve_returns_measured_result(self, vna_adapter):
        result = vna_adapter.solve()
        assert result.success is True
        assert result.s_params.shape == (5, 2, 2)
        assert result.freq_ghz[0] == pytest.approx(1.0)
        assert result.freq_ghz[-1] == pytest.approx(3.0)
        mask = result.measured_mask
        assert mask is not None and bool(np.all(mask))
        meta = result.measurement_meta
        assert meta["calibrated"] is True
        assert meta["idn"].startswith("LibreVNA,")
        assert meta["driver"] == "librevna"
        assert meta["suspect"] == []
        assert meta["calkit_id"] == "wl_2g5_solt_smoke"

    def test_fixture_values_bitwise_into_network(self, vna_adapter):
        """fixture 应答 → 解析 → 网络逐位一致（G1 消费面对齐口径）。"""
        result = vna_adapter.solve()
        s21_0 = result.s_params[0, 1, 0]
        assert s21_0.real == -1.4473103847089729e-16
        assert s21_0.imag == -0.9

    def test_sweep_written_sequence(self, vna_adapter):
        """触发扫频的写序列留痕（官方单次扫频命令集）。"""
        vna_adapter.solve()
        driver = vna_adapter._interface._driver
        assert "VNA:FREQuency:START 1000000000.000000" in driver.written
        assert "VNA:ACQuisition:SINGLE TRUE" in driver.written
        assert "VNA:ACQuisition:RUN" in driver.written

    def test_uncalibrated_marks_suspect_not_blocked(self):
        """未校准：meta 校准态 False + suspect 记录，结果仍产出（G4 决议）。"""
        import rfauto.adapters  # noqa: F401

        adapter = get_global_registry().create(
            EMSolverType.VNA, _vna_config(address=SIM_ADDR_UNCAL))
        try:
            result = adapter.solve()
            assert result.success is True
            meta = result.measurement_meta
            assert meta["calibrated"] is False
            assert any("未校准" in s for s in meta["suspect"])
        finally:
            adapter.close()

    def test_get_sparams_matches_fake_contract(self, vna_adapter):
        """get_sparams 与 EMSolver 面同契约：(freq_ghz, s_params) 元组。"""
        freq, s = vna_adapter.get_sparams()
        assert freq.shape == (5,)
        assert s.shape == (5, 2, 2)

    def test_export_touchstone(self, vna_adapter, tmp_path):
        vna_adapter.solve()
        out = vna_adapter.export_touchstone(tmp_path / "params.s2p")
        assert out.exists()

    def test_solve_without_connection_fails_honest(self):
        import rfauto.adapters  # noqa: F401

        adapter = get_global_registry().create(
            EMSolverType.VNA,
            EMSolverConfig(solver_type=EMSolverType.VNA, extra_params={}))
        result = adapter.solve()
        assert result.success is False
        assert "未连接" in result.message


class TestDriverFallback:
    """G1②：LibreVNA 映射失败 → 回退路径（vna_capture 驱动链/逃生口）。"""

    def test_raw_scpi_escape_hatch_mock_model(self, monkeypatch):
        """model="mock"（vna_capture 原生回放路）经 VNAInterface 链可用。"""
        import skrf

        from rfauto.adapters.vna_adapter import VnaAdapter

        freq = skrf.Frequency(1.0, 2.0, 3, "ghz")
        s = np.zeros((3, 1, 1), dtype=complex)
        s[:, 0, 0] = 0.5
        net = skrf.Network(frequency=freq, s=s)
        ts = tmp_touchstone(net)
        adapter = VnaAdapter(_vna_config(
            model=MOCK_MODEL, address="MOCK",
            mock_source=str(ts)))
        try:
            assert adapter.connect() is True
            result = adapter.solve()
            assert result.success is True
            assert result.s_params.shape == (3, 1, 1)
            meta = result.measurement_meta
            assert meta["driver"] == "mock"
        finally:
            adapter.close()

    def test_resolve_driver_failure_falls_back_to_raw_scpi(self, monkeypatch):
        """skrf.vi 驱动解析失败 → raw pyvisa 逃生口（PNA 族命令集路径）。"""
        from rfauto.measurement import vna_capture
        from rfauto.measurement.vna_capture import VNAConfig, VNAInterface

        class _RawInstr:
            def query(self, cmd):
                if cmd == "*IDN?":
                    return "FAKE,PNA-X,N0001,A.14"
                if "CORR:STATE?" in cmd:
                    return "1"
                if "FREQ:DATA" in cmd:
                    return ",".join(str(1e9 + i * 1e8) for i in range(3))
                if "DATA:SDAT" in cmd:
                    return "0.5,0.0,0.5,0.1,0.5,0.2"
                return "0"

        monkeypatch.setattr(
            vna_capture, "_resolve_driver", lambda model: None)
        iface = VNAInterface(VNAConfig(address="MOCK", model="pna"))
        iface._instrument = _RawInstr()
        iface._connected = True
        net = iface.capture()
        assert net is not None and len(net.f) == 3
        # raw 路产物是 1 端口（当前迹线）——掩码/如实承载由 adapter 层处理
        assert net.s[0, 0, 0] == complex(0.5, 0.0)


def tmp_touchstone(net) -> Path:
    import tempfile

    d = Path(tempfile.mkdtemp())
    p = d / "measured.s1p"
    net.write_touchstone(str(p))
    return p
