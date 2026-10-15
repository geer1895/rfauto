"""方向 3 全链测试（审查缺口 #12）：mock 仪器 capture → calibrate → correlate。

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


# ─── A7 P1-2：skrf.vi 主路 timeout_ms 必须真实生效 ────────────────────────────

class _FakeConn:
    """pyvisa 连接替身：记录 timeout（ms）与 close。"""

    def __init__(self):
        self.timeout = None
        self.closed = False

    def close(self):
        self.closed = True


class TestDriverTimeout:
    """A7 P1-2（2026-10-13）：skrf.vi 驱动构造签名只收 (address, backend)
    （skrf 2.1.0 实测），timeout_ms 原先只在 raw pyvisa 逃生口生效——主路
    四型号（pna/fieldfox/znb/zva）构造后必须真实补设超时，未生效留痕。
    """

    def _connect(self, monkeypatch, model, driver_cls, timeout_ms):
        from rfauto.measurement import vna_capture
        monkeypatch.setattr(vna_capture, "_resolve_driver",
                            lambda m: driver_cls)
        cfg = vna_capture.VNAConfig(
            address="TCPIP0::192.0.2.1::inst0::INSTR", model=model,
            timeout_ms=timeout_ms)
        v = vna_capture.VNAInterface(cfg)
        assert v.connect() is True
        return v

    def test_timeout_property_channel_all_four_models(self, monkeypatch):
        """四主路经 timeout property 通道生效（skrf 2.1.0 VNA 基类实测
        取面），会话日志带生效通道注记（配置面=生效面）。"""

        made: list = []

        class _Driver:
            def __init__(self, address, backend="@py"):
                self._resource = _FakeConn()
                made.append(self)

            @property
            def timeout(self):
                return self._resource.timeout

            @timeout.setter
            def timeout(self, value):
                self._resource.timeout = value

        for model in ("pna", "fieldfox", "znb", "zva"):
            v = self._connect(monkeypatch, model, _Driver, 4321)
            assert made[-1]._resource.timeout == 4321, model
            connect_entries = [e for e in v._session_log
                               if e.command == "connect"]
            assert any("timeout_ms=4321 via instrument.timeout" in e.response
                       for e in connect_entries), model

    def test_timeout_fallback_to_resource_handle(self, monkeypatch):
        """无 timeout property 的驱动代际 → 经 _resource 句柄设超时
        （skrf 2.x 底层资源实测取面）。"""

        class _Driver:
            def __init__(self, address, backend="@py"):
                self._resource = _FakeConn()

        v = self._connect(monkeypatch, "pna", _Driver, 2500)
        assert v._instrument._resource.timeout == 2500

    def test_timeout_fallback_to_legacy_con_handle(self, monkeypatch):
        """旧代际 ``.con`` 句柄兼容取面（A7 P1-2 报告所指访问路径）。"""

        class _Driver:
            def __init__(self, address, backend="@py"):
                self.con = _FakeConn()

        v = self._connect(monkeypatch, "znb", _Driver, 1111)
        assert v._instrument.con.timeout == 1111

    def test_timeout_unset_logged_not_silent(self, monkeypatch):
        """无任何已知通道时留痕不静默（#331 家法：配置面与生效面一致）。"""

        class _Driver:
            def __init__(self, address, backend="@py"):
                pass

        v = self._connect(monkeypatch, "pna", _Driver, 1000)
        assert any(e.command == "connect_timeout_unset"
                   for e in v._session_log)

    def test_close_uses_resolved_connection(self, monkeypatch):
        """close() 经同一取面助手关闭底层连接（原 ".con" 直取在 skrf
        2.1.0 是静默 no-op，同面修正）。"""

        class _Driver:
            def __init__(self, address, backend="@py"):
                self._resource = _FakeConn()

        v = self._connect(monkeypatch, "pna", _Driver, 1000)
        v.close()
        assert v._instrument._resource.closed is True
