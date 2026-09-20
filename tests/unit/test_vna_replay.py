"""补强17（§10.22）VNA 软侧离线回放回归：mock 仪表驱动 + 历史 .s2p 回放全链。

验收口径（方案行）：回放 1 组历史 .s2p 走完 采集→校准→相关 链单测；
correlate 接 D12 FSV（曲线级 ADM/FDM/GDM 六级评级，core/fsv 唯一计算路径）。

全部离线合成数据（*.[sx]p 被 .gitignore 全局排除，历史文件在测试内合成，
与 test_vna_capture_chain.py 的 L1 口径一致），秒级、零硬件。
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import skrf

from rfauto.measurement.calibration import (
    CalibrationKit,
    CalibrationMethod,
    CalibrationStandard,
)
from rfauto.measurement.correlate import (
    compute_correlation,
    compute_fsv_assessment,
    generate_correlation_report,
)
from rfauto.measurement.vna_capture import (
    MOCK_MODEL,
    VNAConfig,
    VNAInterface,
    run_offline_replay,
)

F_START, F_STOP, N_PTS = 2.0, 3.0, 101


def _freq() -> skrf.Frequency:
    return skrf.Frequency(F_START, F_STOP, N_PTS, unit="GHz")


def _resonant_pad(freq: skrf.Frequency, loss_db: float,
                  depth: float = 0.5, s11_mag: float = 0.05) -> skrf.Network:
    """带谐振谷的匹配垫片（确定性合成，给 FSV 提供 Lo/Hi 带特征内容）。

    |S21| = pad·(1 − depth·Lorentzian(f0=2.5GHz, FWHM=60MHz))；
    注意平坦 dB 曲线是 FSV 的退化输入（特征带仅剩噪声 → 相对分母塌缩），
    #195「判据统计量必须匹配响应形态」在 FSV 输入选择上的同源教训。
    """
    f = freq.f
    x = (f - 2.5e9) / 60e6
    s21 = 10 ** (-loss_db / 20.0) * (1.0 - depth / (1.0 + x * x))
    s11 = s11_mag * (1.0 + 0.3 * np.cos(2 * np.pi * (f - f[0]) / (f[-1] - f[0])))
    s = np.zeros((len(f), 2, 2), dtype=complex)
    s[:, 0, 0] = s11
    s[:, 1, 1] = s11
    s[:, 1, 0] = s21
    s[:, 0, 1] = s21
    return skrf.Network(frequency=freq, s=s)


@pytest.fixture()
def historical_pair(tmp_path):
    """一组"历史"测量/仿真对：DUT(10dB 带谐振垫) 串 4dB 转接器后的记录。

    - 历史测量 raw = dut ** adapter（4dB 转接器，未去嵌时 S21 偏 ~4.9dB）；
    - 仿真 sim = dut 本征；响应式校准（adapter 归一化去嵌）后应完美相关。
    """
    freq = _freq()
    dut = _resonant_pad(freq, loss_db=10.0)
    adapter = _resonant_pad(freq, loss_db=4.0, depth=0.1)
    raw = dut ** adapter
    meas_path = tmp_path / "historical_meas.s2p"
    sim_path = tmp_path / "sim_dut.s2p"
    raw.write_touchstone(str(meas_path))
    dut.write_touchstone(str(sim_path))
    return str(meas_path), str(sim_path), dut, adapter


@pytest.fixture()
def response_kit(historical_pair):
    """内存响应式校准套件（method=NONE + thru 标准件 = 4dB 转接器）。"""
    _, _, _, adapter = historical_pair
    return CalibrationKit(
        name="ideal_response", method=CalibrationMethod.NONE,
        standards=[CalibrationStandard("adapter_thru", adapter, "through")],
    )


def _mock_vna(source: str, **kw) -> VNAInterface:
    cfg = VNAConfig(address="MOCK", model=MOCK_MODEL, mock_source=source, **kw)
    v = VNAInterface(cfg)
    assert v.connect()
    return v


class TestMockDriver:
    """mock 仪表驱动：connect/capture/calibrate 与真实驱动同协议。"""

    def test_connect_capture_full_2port_replay(self, historical_pair):
        meas = historical_pair[0]
        v = _mock_vna(meas)
        try:
            net = v.capture()
            assert net is not None
            assert net.nports == 2 and len(net.f) == N_PTS
            from_file = skrf.Network(meas)
            assert np.allclose(net.s, from_file.s, atol=1e-6)
            # 回放副本：改动捕获结果不污染回放源
            net.s[:] = 0
            assert np.abs(v.capture().s).max() > 0
        finally:
            v.close()
        assert not v._connected

    def test_capture_via_raw_scpi_surface(self, historical_pair):
        """屏蔽 get_snp_network 后走 raw SCPI 逃生口：1-port S11 真实解析。"""
        meas, _, _, _ = historical_pair
        v = _mock_vna(meas)
        v._instrument.get_snp_network = None  # 实例属性遮蔽方法 → raw 路径
        net = v.capture()
        assert net is not None and net.s.shape == (N_PTS, 1, 1)
        from_file = skrf.Network(meas)
        assert np.allclose(net.s[:, 0, 0], from_file.s[:, 0, 0], atol=1e-9)
        # SCPI 表面应答格式与真实仪表一致（频率 Hz、re,im 交替）
        freq_resp = v.raw_scpi("SENS1:FREQ:DATA?")
        parsed = [float(x) for x in freq_resp.split(",")]
        assert len(parsed) == N_PTS and parsed[0] == pytest.approx(2.0e9)

    def test_calibrate_state_via_mock(self, historical_pair):
        meas, _, _, _ = historical_pair
        assert _mock_vna(meas, mock_calibrated=True).calibrate()["calibrated"]
        v = _mock_vna(meas, mock_calibrated=False)
        result = v.calibrate()
        assert result["ok"] and not result["calibrated"]

    def test_probe_capabilities_driver_label(self, historical_pair):
        meas, _, _, _ = historical_pair
        v = _mock_vna(meas)
        caps = v.probe_capabilities()
        assert caps["driver"] == "mock" and "MOCK_VNA" in caps["idn"]

    def test_mock_connect_requires_source(self):
        v = VNAInterface(VNAConfig(address="MOCK", model=MOCK_MODEL))
        assert not v.connect()
        assert v._session_log[-1].command == "connect_failed"

    def test_session_log_jsonl_roundtrip(self, historical_pair, tmp_path):
        meas = historical_pair[0]
        v = _mock_vna(meas)
        v.capture()
        v.calibrate()
        v.close()
        out = tmp_path / "session.jsonl"
        v.save_session(out)
        entries = [json.loads(line) for line in
                   out.read_text(encoding="utf-8").strip().splitlines()]
        cmds = [e["command"] for e in entries]
        assert cmds[0] == "connect" and "capture" in cmds and "calibrate" in cmds
        assert cmds[-1] == "close"


class TestOfflineReplayChain:
    """验收主测例：历史 .s2p 走完 采集→校准→相关 链。"""

    def test_replay_full_chain_with_response_cal(
            self, historical_pair, response_kit, tmp_path):
        meas, sim, _, _ = historical_pair
        session = tmp_path / "replay_session.jsonl"
        result = run_offline_replay(meas, sim, response_kit, session_path=session)

        assert result["ok"], result
        # 采集：mock 驱动真实解析历史 Touchstone
        assert result["connect"] == {"ok": True, "driver": "mock"}
        assert result["capture"]["ok"]
        assert result["capture"]["n_ports"] == 2
        assert result["capture"]["n_points"] == N_PTS
        assert result["capture"]["freq_range_ghz"] == [F_START, F_STOP]
        # 校准：响应式去嵌 4dB 转接器
        assert result["calibration"]["is_calibrated"] is True
        assert result["calibrate"]["calibrated"] is True
        # 相关：去嵌后 S21 与仿真一致 → dB 偏差≈0、FSV 等级 Ex
        corr = result["correlation"]
        assert corr["is_correlated"] is True
        assert corr["metrics"]["s21_max_deviation_db"] < 0.1
        assert corr["metrics"]["s11_max_deviation_db"] < 0.1
        assert corr["fsv"]["s21"]["ok"] is True
        assert corr["fsv"]["s21"]["gdm_grade"] == "Ex"
        assert corr["fsv"]["s11"]["gdm_grade"] == "Ex"
        # 会话 JSONL 落盘（best-effort 通道在本链路为必选参数时必须生效）
        cmds = [json.loads(line)["command"] for line in
                session.read_text(encoding="utf-8").strip().splitlines()]
        assert {"connect", "calibrate", "capture", "close"} <= set(cmds)

    def test_replay_without_cal_detects_divergence(self, historical_pair):
        """未校准原样比对：4dB 转接器插入损耗 + 形状差 → dB 门判不相关。"""
        meas, sim, _, _ = historical_pair
        result = run_offline_replay(meas, sim, None)
        assert result["ok"] and result["calibration"] is None
        corr = result["correlation"]
        assert corr["is_correlated"] is False
        assert corr["metrics"]["s21_max_deviation_db"] == pytest.approx(4.9, abs=0.2)
        assert len(corr["warnings"]) > 0

    def test_replay_fsv_flags_wrong_sim(self, historical_pair, response_kit, tmp_path):
        """错误仿真（平坦 20dB pad）+ 正确校准 → FSV 等级显著劣于正确仿真。"""
        meas, sim, _, _ = historical_pair
        wrong_path = tmp_path / "sim_wrong.s2p"
        f = _freq()
        wrong = skrf.Network(frequency=f,
                             s=np.zeros((N_PTS, 2, 2), dtype=complex))
        wrong.s[:, 1, 0] = 0.1  # 平坦 20dB pad，无谐振特征
        wrong.s[:, 0, 1] = 0.1
        wrong.s[:, 0, 0] = 0.05
        wrong.s[:, 1, 1] = 0.05
        wrong.write_touchstone(str(wrong_path))

        good = run_offline_replay(meas, sim, response_kit)
        bad = run_offline_replay(meas, str(wrong_path), response_kit)

        from rfauto.core.fsv import GRADE_CODES

        g_good = good["correlation"]["fsv"]["s21"]["gdm_grade"]
        g_bad = bad["correlation"]["fsv"]["s21"]["gdm_grade"]
        assert GRADE_CODES.index(g_bad) > GRADE_CODES.index(g_good)
        assert bad["correlation"]["is_correlated"] is False
        assert bad["correlation"]["fsv"]["s21"]["gdm_mean"] > \
            good["correlation"]["fsv"]["s21"]["gdm_mean"]


class TestCorrelateFsvIntegration:
    """correlate 接 D12：加性字段语义与 best-effort 降级。"""

    def test_identical_networks_grade_ex_vg(self, historical_pair):
        _, sim, _, _ = historical_pair
        data = skrf.Network(sim)
        fsv = compute_fsv_assessment(
            _wrap(data, "sim"), _wrap(data, "meas"))
        assert fsv["s11"]["ok"] and fsv["s21"]["ok"]
        assert fsv["s21"]["gdm_grade"] in ("Ex", "VG")
        assert fsv["s21"]["gdm_mean"] < 0.1
        assert fsv["s21"]["n_points"] == N_PTS

    def test_too_few_points_degrades_gracefully(self):
        freq = skrf.Frequency(1, 2, 5, unit="GHz")  # < core.fsv.MIN_POINTS
        net = skrf.Network(frequency=freq,
                           s=np.ones((5, 2, 2), dtype=complex) * 0.5)
        fsv = compute_fsv_assessment(_wrap(net, "a"), _wrap(net, "b"))
        assert fsv["s11"]["ok"] is False
        assert "MIN_POINTS" in fsv["s11"]["error"] or "公共轴" in fsv["s11"]["error"]

    def test_one_port_network_s21_unavailable(self, historical_pair):
        _, sim, _, _ = historical_pair
        net1 = skrf.Network(sim).s11
        fsv = compute_fsv_assessment(_wrap(net1, "a"), _wrap(net1, "b"))
        assert fsv["s11"]["ok"] is True
        assert fsv["s21"]["ok"] is False and "端口" in fsv["s21"]["error"]

    def test_compute_correlation_with_fsv_toggle(self, historical_pair):
        _, sim, _, _ = historical_pair
        data = _wrap(skrf.Network(sim), "x")
        on = compute_correlation(data, data, with_fsv=True)
        off = compute_correlation(data, data, with_fsv=False)
        assert on.fsv is not None and "s11" in on.fsv
        assert off.fsv is None and "fsv" in off.to_dict()
        assert off.to_dict()["fsv"] is None

    def test_report_renders_fsv_section(self, historical_pair, tmp_path):
        meas, sim, _, _ = historical_pair
        result = run_offline_replay(meas, sim, response_kit_holder(historical_pair))
        report = generate_correlation_report(
            _corr_from(result), tmp_path / "r.md")
        assert "FSV" in report and "GDM=" in report


# ─── 测试辅助 ────────────────────────────────────────────────────────────────

def _wrap(net: skrf.Network, name: str):
    from rfauto.measurement.import_data import MeasurementData, MeasurementMetadata

    return MeasurementData(
        network=net, metadata=MeasurementMetadata(), source_file=name,
        n_ports=net.nports,
        freq_range_ghz=(float(net.f[0]) / 1e9, float(net.f[-1]) / 1e9),
    )


def response_kit_holder(pair):
    """与 fixture 同构的内存响应式套件（供非 fixture 作用域复用）。"""
    _, _, _, adapter = pair
    return CalibrationKit(
        name="ideal_response", method=CalibrationMethod.NONE,
        standards=[CalibrationStandard("adapter_thru", adapter, "through")],
    )


def _corr_from(result: dict):
    """把 run_offline_replay 结果重建为 CorrelationResult（报告渲染测试用）。"""
    from rfauto.measurement.correlate import CorrelationMetrics, CorrelationResult

    m = result["correlation"]["metrics"]
    return CorrelationResult(
        sim_file=result["sim_file"], measured_file=result["measured_file"],
        metrics=CorrelationMetrics(
            s11_max_deviation_db=m["s11_max_deviation_db"],
            s21_max_deviation_db=m["s21_max_deviation_db"],
            s11_mean_deviation_db=m["s11_mean_deviation_db"],
            s21_mean_deviation_db=m["s21_mean_deviation_db"],
            freq_range_ghz=tuple(m["freq_range_ghz"]),
            n_freq_points=m["n_freq_points"],
        ),
        is_correlated=result["correlation"]["is_correlated"],
        threshold_db=result["correlation"]["threshold_db"],
        warnings=result["correlation"]["warnings"],
        fsv=result["correlation"]["fsv"],
    )
