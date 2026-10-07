"""MS-7 tinySA 通道测试（mock 先行；真机通道硬件门拒绝钉）。

纪律钉（席6 任务书）：tinySA 一律 mock 通道（硬件门未裁，真机禁触发）——
本文件零真实串口、零 pyserial 触发；硬件门拒绝路径在 env 未设下实测。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.measurement.tiny_sa import (
    ENV_ALLOW_REAL,
    HardwareGateLocked,
    MockTinySATransport,
    SerialTransport,
    TinySADriver,
    build_scan_binary,
    parse_frequencies,
    parse_scan_binary,
)

_F1, _F2, _N = 100.0e6, 900.0e6, 101


def _driver(**kw) -> TinySADriver:
    transport = MockTinySATransport(**kw)
    driver = TinySADriver(transport)
    driver.setup_sweep(_F1, _F2, _N)
    return driver


def test_mock_capture_spectrum_deterministic_and_parse_roundtrip() -> None:
    """mock 谱确定性（同参数逐位）+ 二进制解析往返自洽 + 命令序列留痕。"""
    d1 = _driver(tones={300.0e6: -30.0})
    d2 = _driver(tones={300.0e6: -30.0})
    s1 = d1.capture_spectrum()
    s2 = d2.capture_spectrum()
    assert s1.points == _N
    np.testing.assert_array_equal(s1.freqs_hz, s2.freqs_hz)
    np.testing.assert_array_equal(s1.levels_dbm, s2.levels_dbm)
    assert s1.freqs_hz[0] == _F1 and s1.freqs_hz[-1] == _F2
    # 命令序列：pause → scan → resume（官方冻结回读口径；驱动侧留痕）
    tail = d1.written[-3:]
    assert tail[0] == "pause" and tail[-1] == "resume"
    assert tail[1] == "scan 100000000.000000 900000000.000000 101"
    # tone 落最近频点且抬到 tone 电平
    f_peak, lvl_peak = s1.peak()
    assert abs(f_peak - 300.0e6) <= (_F2 - _F1) / (_N - 1)
    assert lvl_peak == pytest.approx(-30.0)
    # 解析器与构造器往返（同一格式单源）
    blob = build_scan_binary(_F1, _F2, s1.levels_dbm)
    f2p, l2p = parse_scan_binary(blob, expect_points=_N,
                                 expect_start_hz=_F1, expect_stop_hz=_F2)
    np.testing.assert_allclose(f2p, s1.freqs_hz)
    np.testing.assert_array_equal(l2p, s1.levels_dbm)


def test_parse_header_guards() -> None:
    """解析守卫：头点数/起止不符与截断显式 ValueError（不静默）。"""
    good = build_scan_binary(_F1, _F2, np.full(_N, -90.0))
    with pytest.raises(ValueError, match="点数"):
        parse_scan_binary(good, expect_points=_N + 1)
    with pytest.raises(ValueError, match="f1"):
        parse_scan_binary(good, expect_start_hz=200.0e6)
    with pytest.raises(ValueError, match="载荷不足"):
        parse_scan_binary(good[:-4], expect_points=_N)
    with pytest.raises(ValueError, match="12 字节头"):
        parse_scan_binary(b"\x01\x02")
    freqs = parse_frequencies("100 200.5 300")
    np.testing.assert_allclose(freqs, [100.0, 200.5, 300.0])
    with pytest.raises(ValueError, match="为空"):
        parse_frequencies("  ")


def test_driver_setup_and_ascii_surface() -> None:
    """ASCII 面：version/vbat/frequencies 映射；setup 守卫。"""
    d = _driver()
    assert d.idn().startswith("tinySA,mock")
    assert d.vbat_mv() == 3900
    freqs = parse_frequencies(d._transport.query(
        "frequencies 1e6 2e6 5"))
    assert len(freqs) == 5
    with pytest.raises(ValueError, match="先 setup_sweep"):
        TinySADriver(MockTinySATransport()).capture_spectrum()
    with pytest.raises(ValueError, match="points"):
        d.setup_sweep(_F1, _F2, 1)
    with pytest.raises(ValueError, match="频率窗非法"):
        d.setup_sweep(_F2, _F1, _N)


def test_frozen_capture_issues_pause_resume_and_sdata_path() -> None:
    """冻结采集走 pause→scan→resume；非冻结直采不夹 pause。"""
    d = _driver()
    d.capture_spectrum(frozen=True)
    assert d.written[-3] == "pause" and d.written[-1] == "resume"
    d.capture_spectrum(frozen=False)
    assert d.written[-1].startswith("scan ")
    assert d.written[-2] != "pause"


def test_hardware_gate_locked_by_default(monkeypatch) -> None:
    """真机硬件门：allow_real 缺省拒绝；env 未设即便 allow_real=True 仍拒绝。"""
    monkeypatch.delenv(ENV_ALLOW_REAL, raising=False)
    with pytest.raises(HardwareGateLocked, match="硬件门锁定"):
        SerialTransport("COM3")
    with pytest.raises(HardwareGateLocked, match="硬件门锁定"):
        SerialTransport("COM3", allow_real=True)
    # 门条件成立时仅构造成功，不触串口（pyserial 惰性到 _ensure_open）
    monkeypatch.setenv(ENV_ALLOW_REAL, "1")
    t = SerialTransport("COM3", allow_real=True)
    assert t.port == "COM3"
