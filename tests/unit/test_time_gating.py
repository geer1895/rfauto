"""§10.20 ③ S 参数时域门控（core/time_gating.py）定向测试。

覆盖
----
- skrf 2.1.0 时域门控接口契约（先 inspect 实测，钉住签名/1 端口限制/单位表）；
- 合成"主响应 + 延迟杂散"：门控后杂散被抑制、主响应谷位保持（容差=实测达到值）；
- 门参数边界：无门（gate=None）与全门（TimeGate.full_record）均为恒等；
- 非法输入/维度不符显式报错；
- 确定性：两次运行逐字节一致；
- 真实归档验收（runs/ 不入 git，缺档 skip 不假装通过）。

真实归档证据（2026-09-12 本机实测，命令见报告）
------------------------------------------------
优先归档的裁决：
- runs/20260908_122552_01847f02/calibration/openems_work/pt_8841552996/sparams.csv：
  存在（401 点 1.5–3.5 GHz，df=5 MHz）。但 S11 与 S21 **逐点恒等**（退化产物），
  |S11| 中位 ≈0.99、最大 1.0038（非无源）——整带近乎全反射，唯一"谷"是 1.955 GHz
  的窄凹口。门控（span=20 ns）**谷位 0 Hz 不漂**，但凹口被门自身平滑削平
  （-9.35 → -2.48 dB），肩部纹波反而升（0.176 → 0.238 dB），门外能量比仅 9.5e-4
  ——即"纹波下降"来自削平凹口而非剔除寄生物。判：**不适合**作清洗验收对象。
- runs/ratrace_smoke/pt8/ratrace.s4p：存在（401 点 2.25–2.75 GHz）。S11 从带边
  2.25 GHz 的 -25.63 dB 单调升到 2.75 GHz 的 -9.49 dB——**谷位贴在带边**，带内无谷；
  门控把谷位内移 18 个频点（22.5 MHz）。判：**不适合**（无带内谷）。

可用的真实验收对象（同机实测前后值，见 parametrize 表）：
- runs/ratrace_arbitration/hfss_ratrace.s4p（HFSS 仲裁，401 点 2.0–3.0 GHz，
  谷 2.410 GHz / -28.90 dB）：门 span=20 ns → 谷位漂移 0 Hz，带内纹波
  12.6796 → 10.3693 dB，肩部 11.9128 → 9.5344 dB。
- runs/ratrace_smoke/pt9/ratrace.s4p（openEMS，401 点 2.25–2.75 GHz，
  谷 2.355 GHz / -36.97 dB）：门 span=40 ns → 漂移 0 Hz，纹波 19.2780 → 17.6767 dB。
- runs/audit_freq_scale/hfss_mline_repro/diag_flush_originfix/m.s2p（HFSS 匹配线复现，
  201 点 1.5–3.5 GHz，|S11|≈-40 dB 且带内 17.6 dB 条纹）：门 span=10 ns → 漂移
  0 Hz，纹波 17.6322 → 14.6559 dB。

诚实边界（不得含糊）
--------------------
三个可用归档的门外冲激能量比都 < 0.003（门宽已覆盖可见冲激主瓣）——频域纹波的
下降同时包含"门自身的频域平滑"，不是纯粹的寄生物剔除。合成用例（杂散与主响应
相距 120 ns，可分辨）才是"门真的剔除了寄生物"的定量证据（门外能量比 3.85%）。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import numpy as np
import pytest
import skrf

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

from rfauto.core.time_gating import (
    TIME_UNIT_SCALE,
    TimeGate,
    band_ripple_db,
    band_valley,
    compare_gate,
    gate_network,
    has_interior_valley,
    impulse_out_of_gate_energy_ratio,
    shoulder_ripple_db,
)

# ── 带 provenance 的归档路径（runs/ 入 .gitignore，缺档 skip）────────────────
_PATCH_CSV = (
    REPO
    / "runs"
    / "20260908_122552_01847f02"
    / "calibration"
    / "openems_work"
    / "pt_8841552996"
    / "sparams.csv"
)
_PT8_S4P = REPO / "runs" / "ratrace_smoke" / "pt8" / "ratrace.s4p"
_PT9_S4P = REPO / "runs" / "ratrace_smoke" / "pt9" / "ratrace.s4p"
_HFSS_RATRACE_S4P = REPO / "runs" / "ratrace_arbitration" / "hfss_ratrace.s4p"
_MSL_FLUSH_S2P = (
    REPO / "runs" / "audit_freq_scale" / "hfss_mline_repro" / "diag_flush_originfix" / "m.s2p"
)


# ---------------------------------------------------------------------------
# 助手
# ---------------------------------------------------------------------------

def _synthetic_echo_network(
    *,
    f0_hz: float = 2.5e9,
    q: float = 25.0,
    echo_amp: float = 0.2,
    echo_delay_s: float = 120e-9,
    npoints: int = 801,
) -> tuple[skrf.Network, np.ndarray, skrf.Frequency]:
    """已知"主响应 + 延迟杂散"合成网络（确定性，无随机）。

    主响应 = 单极点反射凹口 S_main = 1 - A/(1 + 2jQ(f-f0)/f0)（A=0.9，谷深 -20 dB）；
    杂散 = 主响应的延迟拷贝 a*S_main*exp(-2j*pi*f*tau)（时间域 = tau 处的回波）。
    返回 (总网络, S_main 真值数组, 频率轴)。
    """
    f = np.linspace(2e9, 3e9, npoints)
    s_main = 1.0 - 0.9 / (1.0 + 2j * q * (f - f0_hz) / f0_hz)
    s_tot = s_main * (1.0 + echo_amp * np.exp(-2j * np.pi * f * echo_delay_s))
    freq = skrf.Frequency.from_f(f, unit="hz")
    net = skrf.Network(frequency=freq, s=s_tot.reshape(-1, 1, 1), z0=50.0)
    return net, s_main, freq


def _load_patch_csv(path: Path) -> skrf.Network:
    """读 openEMS 归档 CSV（freq_hz,re_S11,im_S11,re_S21,im_S21...）的 S11。"""
    data = np.genfromtxt(str(path), delimiter=",", names=True)
    freq = skrf.Frequency.from_f(np.asarray(data["freq_hz"], dtype=float), unit="hz")
    s11 = np.asarray(data["re_S11"], dtype=float) + 1j * np.asarray(data["im_S11"], dtype=float)
    return skrf.Network(frequency=freq, s=s11.reshape(-1, 1, 1), z0=50.0)


def _ns_gate(span_ns: float, **kwargs) -> TimeGate:
    """验收统一口径：centered 门、显式秒、fft_window=None（见模块 docstring 实测）。"""
    kwargs.setdefault("fft_window", None)
    return TimeGate.from_center_span(0.0, span_ns, unit="ns", **kwargs)


# ---------------------------------------------------------------------------
# skrf 接口契约（先 inspect 核对真实签名，钉住）
# ---------------------------------------------------------------------------

def test_skrf_time_gate_signature_and_unit_table_contract() -> None:
    """skrf 2.1.0 实测契约：签名参数名/t_unit 单位表/1 端口限制。"""
    params = list(inspect.signature(skrf.time.time_gate).parameters)
    assert params == [
        "ntwk", "start", "stop", "center", "span", "mode", "window",
        "method", "fft_window", "conv_mode", "t_unit",
    ]
    # 本模块的单位表与 skrf.time.time_lookup_dict 同口径（数值逐项相等）
    lookup = skrf.time.time_lookup_dict
    assert set(TIME_UNIT_SCALE) == set(lookup)
    for unit, scale in TIME_UNIT_SCALE.items():
        assert scale == pytest.approx(float(lookup[unit]), rel=0.0, abs=0.0)
    # Network.time_gate 只是 time_gate 的薄封装（实测源码一行 return）
    assert isinstance(skrf.Network.time_gate, type(skrf.Network.time_gate))


def test_skrf_time_gate_rejects_multiport() -> None:
    """skrf 原生门只吃 1 端口：N 端口直接 ValueError（本模块靠逐 S 元素绕开）。"""
    net, _, _ = _synthetic_echo_network()
    two_port = skrf.Network(frequency=net.frequency, s=np.zeros((net.frequency.npoints, 2, 2),
                                                               dtype=complex), z0=50.0)
    with pytest.raises(ValueError, match="one-port"):
        skrf.time.time_gate(two_port, start=-1e-9, stop=1e-9, t_unit="s")


# ---------------------------------------------------------------------------
# 门参数值对象：构造/单位/校验
# ---------------------------------------------------------------------------

def test_time_gate_from_times_and_center_span_equivalent() -> None:
    a = TimeGate.from_times(-10.0, 30.0, unit="ns")
    b = TimeGate.from_center_span(10.0, 40.0, unit="ns")
    assert a.resolved_s == pytest.approx((b.resolved_s[0], b.resolved_s[1]), rel=0.0, abs=1e-21)
    assert a.resolved_s == pytest.approx((-1e-8, 3e-8), rel=0.0, abs=1e-20)
    # 单位换算：ns 与 s 等价
    assert TimeGate.from_center_span(0.0, 5.0, unit="ns").span_s == pytest.approx(
        TimeGate.from_center_span(0.0, 5e-9, unit="s").span_s, rel=0.0, abs=0.0
    )
    d = a.to_dict()
    assert d["start_s"] == pytest.approx(-1e-8, rel=0.0, abs=1e-24)
    assert d["mode"] == "bandpass" and d["method"] == "fft" and d["fft_window"] is None


@pytest.mark.parametrize(
    "kwargs, exc, frag",
    [
        ({}, ValueError, "需要完整"),
        ({"start_s": -1e-9}, ValueError, "同时给出"),
        ({"span_s": 1e-9}, ValueError, "同时给出"),
        ({"start_s": -1e-9, "stop_s": 1e-9, "center_s": 0.0, "span_s": 1e-9}, ValueError, "不能同时给"),
        ({"start_s": 1e-9, "stop_s": -1e-9}, ValueError, "严格大于"),
        ({"start_s": 1e-9, "stop_s": 1e-9}, ValueError, "严格大于"),
        ({"center_s": 0.0, "span_s": 0.0}, ValueError, "必须为正"),
        ({"center_s": 0.0, "span_s": -1e-9}, ValueError, "必须为正"),
        ({"center_s": 0.0, "span_s": float("nan")}, ValueError, "有限实数"),
        ({"center_s": float("inf"), "span_s": 1e-9}, ValueError, "有限实数"),
        ({"center_s": 0.0, "span_s": "1ns"}, TypeError, "必须是实数"),
        ({"center_s": 0.0, "span_s": 1e-9, "mode": "lowpass"}, ValueError, "mode"),
        ({"center_s": 0.0, "span_s": 1e-9, "method": "dft"}, ValueError, "method"),
    ],
)
def test_time_gate_rejects_illegal_specs(kwargs: dict, exc: type, frag: str) -> None:
    with pytest.raises(exc, match=frag):
        TimeGate(**kwargs)


def test_time_gate_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="未知时间单位"):
        TimeGate.from_times(-1.0, 1.0, unit="ns_")


# ---------------------------------------------------------------------------
# 门控：边界（无门/全门=恒等）＋ N 端口
# ---------------------------------------------------------------------------

def test_gate_network_none_is_identity() -> None:
    """无门 = 恒等（返回副本，不共享内存）。"""
    net, _, _ = _synthetic_echo_network()
    out = gate_network(net, None)
    assert np.array_equal(out.s, net.s)
    out.s[0, 0, 0] = 123.0
    assert net.s[0, 0, 0] != 123.0  # 副本与原对象解耦


def test_gate_network_full_record_boxcar_is_identity() -> None:
    """全门（门宽 = 整个 FFT 时间记录，闸门全 1）= 恒等，浮点误差 ~1e-15。"""
    net, _, _ = _synthetic_echo_network()
    ident = gate_network(net, TimeGate.full_record(net))
    assert np.allclose(ident.s, net.s, rtol=0.0, atol=1e-12)
    assert float(np.abs(ident.s - net.s).max()) == pytest.approx(2.0e-15, abs=1e-13)


def test_gate_network_rejects_bad_inputs() -> None:
    net, _, _ = _synthetic_echo_network()
    with pytest.raises(TypeError, match=r"skrf\.Network"):
        gate_network([1, 2, 3], _ns_gate(20.0))
    with pytest.raises(TypeError, match="TimeGate"):
        gate_network(net, "kaiser")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="s_params 不能为空"):
        gate_network(net, _ns_gate(20.0), s_params=[])
    with pytest.raises(ValueError, match="实际长度 1"):
        gate_network(net, _ns_gate(20.0), s_params=[(0,)])
    with pytest.raises(TypeError, match="必须是整数"):
        gate_network(net, _ns_gate(20.0), s_params=[[0, "1"]])
    with pytest.raises(ValueError, match="越界"):
        gate_network(net, _ns_gate(20.0), s_params=[(0, 1)])


def test_gate_network_single_point_frequency_grid_rejected() -> None:
    one = skrf.Network(
        frequency=skrf.Frequency(2.5e9, 2.5e9, 1, unit="hz"),
        s=np.zeros((1, 1, 1), dtype=complex),
        z0=50.0,
    )
    with pytest.raises(ValueError, match="频率点数"):
        gate_network(one, _ns_gate(20.0))


def test_gate_network_multiport_gates_only_requested_pairs() -> None:
    """N 端口：指定 (0, 0) 时只改 S11，其余元素逐字节不动（skrf 要求的逐元素门控）。"""
    _, _, freq = _synthetic_echo_network()
    rng = np.random.default_rng(20260912)
    s4 = (rng.normal(size=(len(freq.f), 4, 4)) + 1j * rng.normal(size=(len(freq.f), 4, 4))) * 0.1
    net4 = skrf.Network(frequency=freq, s=s4, z0=50.0)
    out = gate_network(net4, _ns_gate(20.0), s_params=[(0, 0)])
    assert out.s.shape == net4.s.shape
    assert not np.allclose(out.s[:, 0, 0], net4.s[:, 0, 0])  # 门确实生效
    for i in range(4):
        for j in range(4):
            if (i, j) != (0, 0):
                assert np.array_equal(out.s[:, i, j], net4.s[:, i, j])
    # 默认口径 = 全部 16 个元素都被门控
    out_all = gate_network(net4, _ns_gate(20.0))
    assert not np.array_equal(out_all.s, net4.s)


# ---------------------------------------------------------------------------
# 合成验证：延迟杂散被抑制 + 主响应谷位保持
# ---------------------------------------------------------------------------

def test_synthetic_echo_suppressed_and_valley_preserved() -> None:
    """合成"主响应 + 120 ns 延迟杂散"：boxcar 40 ns 门剔除回波、谷位回到 2.5 GHz。

    实测（本机 2026-09-12）：谷位 2.49625 → 2.50000 GHz（真值 2.5）；肩部纹波
    4.2533 → 0.9350 dB；|S-S_main| 最大偏差 0.19902 → 0.08481。
    """
    net, s_main, _ = _synthetic_echo_network()
    gate = _ns_gate(40.0, window="boxcar")
    gated = gate_network(net, gate)
    rep = compare_gate(net, gated, gate=gate)

    # 主响应谷位：门后落在真值 2.5 GHz 上（门前的 3.75 MHz 调制偏移被消掉）
    assert rep["before"]["dip_freq_ghz"] == pytest.approx(2.49625, abs=1e-9)
    assert rep["after"]["dip_freq_ghz"] == pytest.approx(2.5, abs=1e-12)
    assert rep["dip_shift_hz"] == pytest.approx(3.75e6, rel=0.0, abs=1.0)
    # 谷深基本保住（20.0 -> 19.86 dB）
    assert rep["after"]["dip_db"] == pytest.approx(-19.857, abs=0.05)
    # 杂散条纹被压制：肩部纹波砍掉 ~78%
    assert rep["before"]["shoulder_ripple_db"] == pytest.approx(4.2533, abs=0.01)
    assert rep["after"]["shoulder_ripple_db"] == pytest.approx(0.9350, abs=0.01)
    assert rep["after"]["shoulder_ripple_db"] < 0.5 * rep["before"]["shoulder_ripple_db"]
    assert rep["shoulder_ripple_delta_db"] < -3.0
    # 与真值的最大复偏差减半（0.19902 -> 0.08481，实测比值 0.426）
    err_before = float(np.abs(net.s[:, 0, 0] - s_main).max())
    err_after = float(np.abs(gated.s[:, 0, 0] - s_main).max())
    assert err_before == pytest.approx(0.19902, abs=1e-4)
    assert err_after == pytest.approx(0.08481, abs=1e-4)
    assert err_after < 0.6 * err_before


def test_synthetic_out_of_gate_energy_ratio_matches_echo_power() -> None:
    """门外冲激能量比 ≈ 回波功率占比 a²/(1+a²) = 0.04/1.04 = 3.846%（实测 3.847%）。"""
    net, _, _ = _synthetic_echo_network(echo_amp=0.2)
    ratio = impulse_out_of_gate_energy_ratio(net, _ns_gate(40.0, window="boxcar"))
    assert ratio == pytest.approx(0.04 / 1.04, abs=3e-4)
    # 门远大于记录则几乎不丢能量；门极窄则丢很多——单调性方向正确
    wide = impulse_out_of_gate_energy_ratio(net, _ns_gate(160.0, window="boxcar"))
    assert wide < 0.05
    with pytest.raises(TypeError, match="TimeGate"):
        impulse_out_of_gate_energy_ratio(net, None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 指标定义（解析可验，不依赖归档）
# ---------------------------------------------------------------------------

def test_band_valley_and_ripple_definitions() -> None:
    """解析曲线：单点深谷 40 dB，肩部平坦 → band 纹波 40 dB、肩部 0 dB。"""
    f = np.linspace(2e9, 3e9, 101)
    mag = np.ones(101)
    mag[50] = 0.01  # 2.5 GHz 处 -40 dB 窄谷
    net = skrf.Network(
        frequency=skrf.Frequency.from_f(f, unit="hz"),
        s=mag.reshape(-1, 1, 1).astype(complex),
        z0=50.0,
    )
    f_dip, db_dip = band_valley(net)
    assert f_dip == pytest.approx(2.5e9, rel=0.0, abs=0.0)
    assert db_dip == pytest.approx(-40.0, rel=0.0, abs=1e-9)
    assert band_ripple_db(net) == pytest.approx(40.0, rel=0.0, abs=1e-9)
    # 挖掉谷位正负 10% 带宽（1 GHz 的 0.1）后只剩平坦肩部
    assert shoulder_ripple_db(net, notch_exclusion=0.10) == pytest.approx(0.0, abs=1e-9)
    # notch_exclusion=0 → 只挖掉谷位那一个采样点（单点谷被挖净 → 肩部平坦）
    assert shoulder_ripple_db(net, notch_exclusion=0.0) == pytest.approx(0.0, abs=1e-9)
    # 三点谷：excl=0 只挖中点数不到两侧 → 肩部仍见 40 dB；excl=0.10 全挖净 → 0
    mag3 = np.ones(101)
    mag3[49:52] = 0.01
    net3 = skrf.Network(
        frequency=skrf.Frequency.from_f(f, unit="hz"),
        s=mag3.reshape(-1, 1, 1).astype(complex),
        z0=50.0,
    )
    assert shoulder_ripple_db(net3, notch_exclusion=0.0) == pytest.approx(40.0, abs=1e-9)
    assert shoulder_ripple_db(net3, notch_exclusion=0.10) == pytest.approx(0.0, abs=1e-9)
    assert has_interior_valley(net) is True
    # 谷位贴带边的合成曲线 → 不是带内谷
    mag_edge = np.linspace(1.0, 0.1, 101)
    net_edge = skrf.Network(
        frequency=skrf.Frequency.from_f(f, unit="hz"),
        s=mag_edge.reshape(-1, 1, 1).astype(complex),
        z0=50.0,
    )
    assert has_interior_valley(net_edge) is False


@pytest.mark.parametrize(
    "call, exc, frag",
    [
        (lambda n: band_valley(n, band=(2.5e9, 2.5e9)), ValueError, "hi > lo"),
        (lambda n: band_valley(n, band=(3.0e9, 4.0e9)), ValueError, "选中的频点"),
        (lambda n: band_ripple_db(n, s_param=(0, 3)), ValueError, "越界"),
        (lambda n: shoulder_ripple_db(n, notch_exclusion=0.5), ValueError, "notch_exclusion"),
        (lambda n: shoulder_ripple_db(n, notch_exclusion=-0.1), ValueError, "notch_exclusion"),
        (lambda n: has_interior_valley(n, edge_margin=0.5), ValueError, "edge_margin"),
        (lambda n: compare_gate([1], n), TypeError, r"skrf\.Network"),
    ],
)
def test_metric_and_compare_validation(call, exc: type, frag: str) -> None:
    net, _, _ = _synthetic_echo_network()
    with pytest.raises(exc, match=frag):
        call(net)


def test_compare_gate_requires_same_grid() -> None:
    """before/after 频率网格或端口数不一致 → 显式报错（不静默广播）。"""
    net, _, _ = _synthetic_echo_network()
    shifted = skrf.Network(
        frequency=skrf.Frequency.from_f(net.f * 1.0001, unit="hz"),
        s=net.s.copy(),
        z0=50.0,
    )
    with pytest.raises(ValueError, match="频率网格不一致"):
        compare_gate(net, shifted)
    two = skrf.Network(
        frequency=net.frequency,
        s=np.zeros((net.frequency.npoints, 2, 2), dtype=complex),
        z0=50.0,
    )
    with pytest.raises(ValueError, match="端口数不一致"):
        compare_gate(net, two)


# ---------------------------------------------------------------------------
# 确定性
# ---------------------------------------------------------------------------

def test_gating_is_deterministic_byte_identical() -> None:
    """两次门控逐字节一致（纯 numpy，无随机/无全局状态）。"""
    net, _, _ = _synthetic_echo_network()
    gate = _ns_gate(40.0, window="boxcar")
    a = gate_network(net, gate)
    b = gate_network(net, gate)
    assert a.s.tobytes() == b.s.tobytes()
    assert compare_gate(net, a, gate=gate) == compare_gate(net, b, gate=gate)


# ---------------------------------------------------------------------------
# 真实归档（runs/ 不入 git；缺档 skip，不假装通过）
# ---------------------------------------------------------------------------

def test_real_archive_patch_csv_is_degenerate_and_unsuitable() -> None:
    """优先归档①裁决：patch sparams.csv 存在但退化，不适合当清洗验收对象。

    实测：S11 与 S21 逐点恒等；|S11| 中位 0.9936、最大 1.00383（>1，非无源）；
    门 span=20 ns 后谷位 0 Hz 不漂，但凹口被平滑削平（-9.353 → -2.477 dB）、
    肩部纹波反升（0.176 → 0.238 dB）、门外能量比 9.5e-4（几乎没剔东西）。
    """
    if not _PATCH_CSV.exists():
        pytest.skip(f"归档缺失：{_PATCH_CSV}")
    data = np.genfromtxt(str(_PATCH_CSV), delimiter=",", names=True)
    s11 = np.asarray(data["re_S11"]) + 1j * np.asarray(data["im_S11"])
    s21 = np.asarray(data["re_S21"]) + 1j * np.asarray(data["im_S21"])
    assert np.allclose(s11, s21, rtol=0.0, atol=1e-12)  # 退化：S11 ≡ S21
    mag = np.abs(s11)
    assert float(np.median(mag)) > 0.98
    assert float(mag.max()) > 1.0  # 非无源，产物本身不可信

    net = _load_patch_csv(_PATCH_CSV)
    gate = _ns_gate(20.0)
    rep = compare_gate(net, gate_network(net, gate), gate=gate)
    assert rep["before"]["dip_freq_ghz"] == pytest.approx(1.955, abs=1e-9)
    assert rep["dip_shift_hz"] == 0.0  # 谷位没漂
    # 但"纹波下降"是削平凹口：谷深变浅 >5 dB、肩部纹波反而上升、门外几乎没能量
    assert rep["after"]["dip_db"] - rep["before"]["dip_db"] > 5.0
    assert rep["after"]["shoulder_ripple_db"] > rep["before"]["shoulder_ripple_db"]
    assert rep["out_of_gate_energy_ratio"] < 0.01
    assert has_interior_valley(net) is True


def test_real_archive_pt8_has_edge_valley_and_is_unsuitable() -> None:
    """优先归档②裁决：pt8 S11 谷位贴带边（无带内谷），门控把谷位内移 18 频点。"""
    if not _PT8_S4P.exists():
        pytest.skip(f"归档缺失：{_PT8_S4P}")
    net = skrf.Network(str(_PT8_S4P)).s11
    assert has_interior_valley(net) is False
    f_dip, _ = band_valley(net)
    assert f_dip == pytest.approx(float(net.f[0]), rel=0.0, abs=0.0)  # 谷在下带边
    gate = _ns_gate(40.0)
    rep = compare_gate(net, gate_network(net, gate), gate=gate)
    step = float(net.f[1] - net.f[0])
    assert rep["dip_shift_hz"] / step == pytest.approx(18.0, abs=0.5)


# 实测前后值（2026-09-12 本机，与模块 docstring 的数字同源）
# (标签, 路径, 门宽 ns, 门前纹波 dB, 门后纹波 dB, 门前肩部 dB, 门后肩部 dB)
_ACCEPTANCE_CASES = [
    ("hfss_ratrace", _HFSS_RATRACE_S4P, 20.0, 12.6796, 10.3693, 11.9128, 9.5344),
    ("ratrace_pt9", _PT9_S4P, 40.0, 19.2780, 17.6767, 15.3680, 14.0276),
    ("msl_repro_flush", _MSL_FLUSH_S2P, 10.0, 17.6322, 14.6559, 7.7183, 6.7201),
]


@pytest.mark.parametrize("label, path, span_ns, rip_b, rip_a, sh_b, sh_a", _ACCEPTANCE_CASES)
def test_real_archive_gate_keeps_valley_and_reduces_ripple(
    label: str, path: Path, span_ns: float, rip_b: float, rip_a: float, sh_b: float, sh_a: float
) -> None:
    """真实归档验收（§10.20 ③）：谷位不漂（<=1 个频点）且带内纹波下降。"""
    if not path.exists():
        pytest.skip(f"归档缺失：{path}")
    net = skrf.Network(str(path)).s11
    assert has_interior_valley(net) is True, f"{label} 带内无谷"
    gate = _ns_gate(span_ns)
    rep = compare_gate(net, gate_network(net, gate), gate=gate)
    step = float(net.f[1] - net.f[0])

    # ① 谷位不漂：实测三个归档均为 0 Hz（容差 1 个频点）
    assert abs(rep["dip_shift_hz"]) <= step, f"{label} 谷位漂了 {rep['dip_shift_hz']/1e6:.3f} MHz"
    assert rep["dip_shift_hz"] == pytest.approx(0.0, abs=1.0)

    # ② 纹波下降：整带与肩部都要降（实测值带 0.05 dB 回归钉）
    assert rep["before"]["band_ripple_db"] == pytest.approx(rip_b, abs=0.05)
    assert rep["after"]["band_ripple_db"] == pytest.approx(rip_a, abs=0.05)
    assert rep["before"]["shoulder_ripple_db"] == pytest.approx(sh_b, abs=0.05)
    assert rep["after"]["shoulder_ripple_db"] == pytest.approx(sh_a, abs=0.05)
    assert rep["after"]["band_ripple_db"] < rep["before"]["band_ripple_db"]
    assert rep["after"]["shoulder_ripple_db"] < rep["before"]["shoulder_ripple_db"]

    # 诚实指标：门外冲激能量比（这三个归档均 < 0.003，纹波下降含门的平滑成分）
    assert 0.0 <= rep["out_of_gate_energy_ratio"] < 0.01
