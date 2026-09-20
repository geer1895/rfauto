"""方向 3 全链测试）：mock 仪器 capture → calibrate → correlate。

真机路径语义验证：raw SCPI 测量必须产出真实 skrf.Network（旧实现解析后
恒 return None，capture 真机不可用）；calibrate 方法存在且可记录校准态。
"""

from __future__ import annotations

import numpy as np
import pytest


class FakeInstrument:
    """SCPI 仿真仪器：返回 11 点频率 + S11 复数数据（Lorentzian 谐振形状）。"""

    def __init__(self, calibrated: str = "1"):
        self.calibrated = calibrated
        self.written: list[str] = []

    def query(self, cmd: str) -> str:
        if cmd == "*IDN?":
            return "MOCK,VNA-FAKE,SN001,FW2.1"
        if "CORR:STATE?" in cmd:
            return self.calibrated
        if "FREQ:DATA" in cmd:
            return ",".join(str(2.0e9 + i * 0.1e9) for i in range(11))
        if "DATA:SDAT" in cmd:
            vals = []
            for i in range(11):
                mag = 0.9 if i != 5 else 0.2  # 谐振点 S11 深
                vals += [mag, 0.0]
            return ",".join(str(v) for v in vals)
        return "0"

    def write(self, cmd: str) -> None:
        self.written.append(cmd)


@pytest.fixture()
def vna(monkeypatch):
    monkeypatch.setattr("rfauto.measurement.vna_capture._resolve_driver", lambda model: None)
    from rfauto.measurement.vna_capture import VNAConfig, VNAInterface
    v = VNAInterface(VNAConfig(address="MOCK", model="", channel=1))
    fake = FakeInstrument()
    v._instrument = fake
    v._connected = True
    return v, fake


class TestRawCapture:
    def test_capture_returns_real_network(self, vna):
        import skrf

        v, _ = vna
        net = v.capture()
        assert net is not None
        assert isinstance(net, skrf.Network)
        assert len(net.f) == 11
        assert net.s.shape == (11, 1, 1)
        # 谐振点（第 6 点）|S11| 明显低于其余点 —— 数据真的被解析了
        mags = np.abs(net.s[:, 0, 0])
        assert mags[5] < 0.5 and mags[0] > 0.8

    def test_capture_not_connected_returns_none(self, monkeypatch):
        from rfauto.measurement.vna_capture import VNAConfig, VNAInterface
        v = VNAInterface(VNAConfig(address=""))
        assert v.capture() is None

    def test_capture_logged_to_session(self, vna, tmp_path):
        v, _ = vna
        v.capture()
        out = tmp_path / "session.jsonl"
        v.save_session(out)
        text = out.read_text(encoding="utf-8")
        assert "capture" in text


class TestCalibrate:
    def test_calibrate_applied(self, vna):
        v, _ = vna
        result = v.calibrate()
        assert result["ok"]
        assert result["calibrated"] is True

    def test_calibrate_not_applied(self, monkeypatch):
        from rfauto.measurement.vna_capture import VNAConfig, VNAInterface
        monkeypatch.setattr("rfauto.measurement.vna_capture._resolve_driver", lambda model: None)
        v = VNAInterface(VNAConfig(address="MOCK"))
        v._instrument = FakeInstrument(calibrated="0")
        v._connected = True
        result = v.calibrate()
        assert result["ok"] and result["calibrated"] is False

    def test_calibrate_requires_connect(self):
        from rfauto.measurement.vna_capture import VNAConfig, VNAInterface
        result = VNAInterface(VNAConfig()).calibrate()
        assert not result["ok"]

    def test_probe_capabilities(self, vna):
        v, _ = vna
        caps = v.probe_capabilities()
        assert caps["connected"] and caps["driver"] == "raw_scpi"
        assert "MOCK" in caps["idn"]


class TestFullChain:
    """L1 验收口径：capture → calibrate → correlate 全链（无硬件）。"""

    def test_capture_calibrate_correlate(self, vna, tmp_path):
        import skrf

        from rfauto.measurement.correlate import compute_correlation
        from rfauto.measurement.import_data import import_touchstone

        v, _ = vna
        net = v.capture()
        assert net is not None
        assert v.calibrate()["calibrated"]

        # correlate 引擎面向 2 端口（S11+S21）——把捕获的 S11 扩展成 2 端口
        # Touchstone 再导回（真实数据流形态），与自身做相关性
        s2 = np.zeros((len(net.f), 2, 2), dtype=complex)
        s2[:, 0, 0] = net.s[:, 0, 0]
        s2[:, 1, 0] = net.s[:, 0, 0] * 0.1
        s2[:, 0, 1] = net.s[:, 0, 0] * 0.1
        s2[:, 1, 1] = net.s[:, 0, 0]
        net2 = skrf.Network(frequency=net.frequency, s=s2)

        ts_path = tmp_path / "measured.s2p"
        net2.write_touchstone(str(ts_path))
        measured = import_touchstone(str(ts_path))
        sim_path = tmp_path / "sim.s2p"
        net2.write_touchstone(str(sim_path))
        sim = import_touchstone(str(sim_path))
        result = compute_correlation(sim, measured, threshold_db=3.0)
        assert result is not None
        assert isinstance(result.is_correlated, bool)
        assert result.metrics.n_freq_points == 11
