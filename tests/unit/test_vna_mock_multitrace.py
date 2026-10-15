"""MockVNAInstrument 多迹线 SCPI 计算面（0bx followUp 离线半边，2026-10-11 W7-D）。

验收口径（R3_followups §② #9）：
- ``CALC:PAR:DEF[:EXT]``/``:SDEF`` 计算面 mock：write() 注册命名迹线
  （名 → S<rx><tx>），query() 补目录（PAR:CAT?/NAME?）、迹线号（SNUM?）与
  点名/选中迹线复数据（DATA:SDAT? [名]）；
- 多迹线采集 → skrf Network 形状正确（(n, P, P)，P=最高端口号）；
- 真机协议行为零臆造（实现面 TODO 注记承接着真机联调半边）；
- 全链：connect(mock 文件) → 定义迹线 → capture() → 形状与数据断言。

全部离线合成数据，秒级、零硬件（与 test_vna_replay.py L1 口径一致）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import skrf

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.measurement.vna_capture import (
    MOCK_MODEL,
    MockVNAInstrument,
    VNAConfig,
    VNAInterface,
)

N_PTS = 21


def _freq() -> skrf.Frequency:
    return skrf.Frequency(1.0, 2.0, N_PTS, unit="GHz")


def _twoport() -> skrf.Network:
    f = _freq()
    s = np.zeros((N_PTS, 2, 2), dtype=complex)
    s[:, 0, 0] = 0.1 + 0.05j
    s[:, 1, 0] = 0.7 * (1 - 0.2j)
    s[:, 0, 1] = 0.7 * (1 + 0.2j)
    s[:, 1, 1] = 0.2 - 0.1j
    return skrf.Network(frequency=f, s=s)


def _fourport() -> skrf.Network:
    rng = np.random.default_rng(7)
    f = _freq()
    s = (rng.standard_normal((N_PTS, 4, 4))
         + 1j * rng.standard_normal((N_PTS, 4, 4))) * 0.2
    return skrf.Network(frequency=f, s=s)


def _sdat_pairs(mock: MockVNAInstrument, command: str) -> np.ndarray:
    """DATA:SDAT? 应答 → 复数数组（re,im 交替解析）。"""
    raw = mock.query(command)
    vals = [float(x) for x in raw.split(",")]
    return np.array([complex(vals[2 * i], vals[2 * i + 1])
                     for i in range(len(vals) // 2)])


class TestTraceDefineSurface:
    """write() 定义面：PNA DEF:EXT 与 ZNB SDEF 双风格注册。"""

    def test_define_ext_registers_named_trace(self):
        mock = MockVNAInstrument(_twoport())
        mock.write("CALC1:PAR:DEF:EXT 'tr21','S21'")
        mock.write("CALC1:PAR:DEF 'tr11','S11'")
        assert mock.traces == {"tr21": (2, 1), "tr11": (1, 1)}

    def test_sdef_znb_style_registers_named_trace(self):
        mock = MockVNAInstrument(_twoport())
        mock.write("CALC1:PAR:SDEF 'm21','S21'")
        assert mock.traces == {"m21": (2, 1)}

    def test_define_ignores_non_sparam_expression(self):
        """非纯 S<mn> 表达式不注册（真机扩展表达式属真机半边，不臆造）。"""
        mock = MockVNAInstrument(_twoport())
        mock.write("CALC1:PAR:DEF:EXT 'bad','SNP:file.s2p'")
        assert mock.traces == {}

    def test_select_records_selected_trace(self):
        mock = MockVNAInstrument(_twoport())
        mock.write("CALC1:PAR:DEF:EXT 'a','S11'")
        mock.write("CALC1:PAR:DEF:EXT 'b','S21'")
        mock.write("CALC1:PAR:SEL 'b'")
        assert mock.selected_trace == "b"

    def test_written_log_still_records(self):
        mock = MockVNAInstrument(_twoport())
        mock.write("CALC1:PAR:DEF:EXT 'a','S11'")
        assert "CALC1:PAR:DEF:EXT 'a','S11'" in mock.written


class TestTraceQuerySurface:
    """query() 目录/迹线号/数据面（点名与选中两条路）。"""

    def test_catalog_lists_names_and_params(self):
        mock = MockVNAInstrument(_twoport())
        mock.write("CALC1:PAR:DEF:EXT 'tr21','S21'")
        mock.write("CALC1:PAR:SDEF 'tr11','S11'")
        assert mock.query("CALC1:PAR:CAT?") == "'tr21','S21','tr11','S11'"

    def test_catalog_ext_and_name_forms(self):
        mock = MockVNAInstrument(_twoport())
        mock.write("CALC1:PAR:DEF:EXT 'a','S11'")
        assert mock.query("CALC:PAR:CAT:EXT?") == "'a','S11'"
        assert mock.query("CALC:PAR:NAME?") == "'a','S11'"

    def test_snum_returns_one_based_registration_order(self):
        mock = MockVNAInstrument(_twoport())
        mock.write("CALC1:PAR:DEF:EXT 'tr21','S21'")
        mock.write("CALC1:PAR:DEF:EXT 'tr11','S11'")
        assert mock.query("CALC1:PAR:SNUM? 'tr21'") == "1"
        assert mock.query("CALC1:PAR:SNUM? 'tr11'") == "2"

    def test_snum_without_name_uses_selected(self):
        mock = MockVNAInstrument(_twoport())
        mock.write("CALC1:PAR:DEF:EXT 'tr21','S21'")
        mock.write("CALC1:PAR:DEF:EXT 'tr11','S11'")
        mock.write("CALC1:PAR:SEL 'tr11'")
        assert mock.query("CALC:PAR:SNUM?") == "2"

    def test_snum_unknown_trace_is_zero(self):
        mock = MockVNAInstrument(_twoport())
        mock.write("CALC1:PAR:DEF:EXT 'a','S11'")
        assert mock.query("CALC:PAR:SNUM? 'nope'") == "0"

    def test_data_by_name_matches_source_column(self):
        src = _twoport()
        mock = MockVNAInstrument(src)
        mock.write("CALC1:PAR:DEF:EXT 'tr21','S21'")
        got = _sdat_pairs(mock, "CALC1:DATA:SDAT? 'tr21'")
        assert got.shape == (N_PTS,)
        assert np.allclose(got, src.s[:, 1, 0], atol=1e-12)

    def test_data_after_select_matches_selected_trace(self):
        src = _twoport()
        mock = MockVNAInstrument(src)
        mock.write("CALC1:PAR:DEF:EXT 'tr11','S11'")
        mock.write("CALC1:PAR:DEF:EXT 'tr21','S21'")
        mock.write("CALC1:PAR:SEL 'tr21'")
        got = _sdat_pairs(mock, "CALC1:DATA:SDAT?")
        assert np.allclose(got, src.s[:, 1, 0], atol=1e-12)

    def test_data_no_traces_keeps_legacy_s11_behavior(self):
        """无迹线定义：DATA:SDAT? 仍回历史 S11（既有 raw 逃生口兼容钉）。"""
        src = _twoport()
        mock = MockVNAInstrument(src)
        got = _sdat_pairs(mock, "CALC1:DATA:SDAT?")
        assert np.allclose(got, src.s[:, 0, 0], atol=1e-12)

    def test_data_no_selection_defaults_to_first_registered(self):
        src = _twoport()
        mock = MockVNAInstrument(src)
        mock.write("CALC1:PAR:DEF:EXT 'tr21','S21'")
        mock.write("CALC1:PAR:DEF:EXT 'tr11','S11'")
        got = _sdat_pairs(mock, "CALC1:DATA:SDAT?")
        assert np.allclose(got, src.s[:, 1, 0], atol=1e-12)

    def test_unknown_name_falls_back_to_zero_convention(self):
        mock = MockVNAInstrument(_twoport())
        mock.write("CALC1:PAR:DEF:EXT 'a','S11'")
        assert mock.query("CALC1:DATA:SDAT? 'ghost'") == "0"


class TestTraceNetworkAssembly:
    """多迹线采集主路：get_snp_network 按迹线装配（形状正确）。"""

    def test_no_traces_returns_full_copy(self):
        src = _twoport()
        mock = MockVNAInstrument(src)
        net = mock.get_snp_network()
        assert net.nports == 2 and np.allclose(net.s, src.s, atol=1e-12)
        net.s[:] = 0
        assert np.abs(mock.get_snp_network().s).max() > 0

    def test_defined_traces_assemble_4port_shape(self):
        src = _fourport()
        mock = MockVNAInstrument(src)
        mock.write("CALC1:PAR:DEF:EXT 't41','S41'")
        mock.write("CALC1:PAR:DEF:EXT 't14','S14'")
        net = mock.get_snp_network()
        assert isinstance(net, skrf.Network)
        assert net.s.shape == (N_PTS, 4, 4)
        assert np.allclose(net.s[:, 3, 0], src.s[:, 3, 0], atol=1e-12)
        assert np.allclose(net.s[:, 0, 3], src.s[:, 0, 3], atol=1e-12)
        # 未定义交叉项零填：迹线目录即已测掩码（#314 掩码纪律的消费面注记）
        assert np.abs(net.s[:, 0, 1]).max() == 0.0

    def test_defined_traces_on_2port_keeps_full_square(self):
        src = _twoport()
        mock = MockVNAInstrument(src)
        for name, sp in (("t11", "S11"), ("t21", "S21"),
                         ("t12", "S12"), ("t22", "S22")):
            mock.write(f"CALC1:PAR:DEF:EXT '{name}','{sp}'")
        net = mock.get_snp_network()
        assert net.s.shape == (N_PTS, 2, 2)
        assert np.allclose(net.s, src.s, atol=1e-12)

    def test_single_trace_gives_one_port_shape(self):
        src = _twoport()
        mock = MockVNAInstrument(src)
        mock.write("CALC1:PAR:DEF:EXT 't11','S11'")
        net = mock.get_snp_network()
        assert net.s.shape == (N_PTS, 1, 1)
        assert np.allclose(net.s[:, 0, 0], src.s[:, 0, 0], atol=1e-12)


class TestMockChainCapture:
    """全链：connect(mock 文件) → SCPI 定义迹线 → capture() 形状正确。"""

    def test_capture_with_traces_via_interface(self, tmp_path):
        src = _twoport()
        path = tmp_path / "hist.s2p"
        src.write_touchstone(str(path))
        cfg = VNAConfig(address="MOCK", model=MOCK_MODEL,
                        mock_source=str(path))
        v = VNAInterface(cfg)
        assert v.connect()
        try:
            inst = v._instrument
            assert isinstance(inst, MockVNAInstrument)
            inst.write("CALC1:PAR:DEF:EXT 'tr21','S21'")
            inst.write("CALC1:PAR:DEF:EXT 'tr11','S11'")
            net = v.capture()
            assert net is not None
            assert net.s.shape == (N_PTS, 2, 2)
            assert np.allclose(net.s[:, 1, 0], src.s[:, 1, 0], atol=1e-9)
            assert np.allclose(net.s[:, 0, 0], src.s[:, 0, 0], atol=1e-9)
            # raw SCPI 表面同链可用（目录+迹线号）
            assert "tr21" in v.raw_scpi("CALC1:PAR:CAT?")
            assert v.raw_scpi("CALC1:PAR:SNUM? 'tr21'") == "1"
        finally:
            v.close()

    def test_capture_without_traces_unchanged_full_2port(self, tmp_path):
        src = _twoport()
        path = tmp_path / "hist2.s2p"
        src.write_touchstone(str(path))
        cfg = VNAConfig(address="MOCK", model=MOCK_MODEL,
                        mock_source=str(path))
        v = VNAInterface(cfg)
        assert v.connect()
        try:
            net = v.capture()
            assert net is not None and net.nports == 2
            assert np.allclose(net.s, src.s, atol=1e-6)
        finally:
            v.close()


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
