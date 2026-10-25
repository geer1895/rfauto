"""aurora_k K8 THRU 去嵌+Z12 串联指标测试（反馈 F6/P14）。

覆盖面（#340 家法=合成已知量回收钉）：
- 对称半拆合成回收：已知 π 型夹具（250fF 并联+有耗线）的 2x-thru →
  半拆 → 单侧夹具逐位回收（S 域 ≤1e-12）；
- THRU 双边去嵌回收：measured = F ** DUT ** F、thru = F ** F →
  deembed_thru(half=True) → DUT 网络 ≤1e-9（任务书门）+ y21 口径
  C/R 逐位回收 ≤1e-9（173.5fF/1.4Ω 精确）；
- 强失配拒绝：|S11|≈0.96 语料下简化式 R 偏差 >2×（专用语料 >10×）+
  rejected=True+建议文案；y21 口径回真值；
- 用户数值锚（F6 验收语义）：合成 173.5fF+250fF 引线并联电容场景 →
  去嵌后 y21 口径回到 173.5fF±5%（实测逐位 173.5000）；
- 多波长半拆（3π 跨度/101 点）与欠采样守卫（22.6rad/61 点显式拒绝）；
- 纯串联件 Z 退化守卫、shunt 拓扑（C/Q/SRF 锚=解析值）、频带外守卫；
- CALC 两键（服务层 run_calculator 信封）+ CLI 两叶（CliRunner
  --json 信封+失败信封+退出码）。

全部确定性（固定参数合成，无随机/网络/真机）；容差=本机实测达到值
留 2-3 个量级余量（skrf 2.1.0 / Python 3.12）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import skrf

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

from rfauto.core.deembed import (
    deembed_thru,
    thru_half_network,
    z12_series_metrics,
)

_SKRF_A2S = skrf.network.a2s

# ── 合成语料常量（用户场景锚：R=1.4Ω/C=173.5fF/引线并联 250fF） ────────────
_FREQS_GHZ = np.linspace(0.5, 10.0, 96)
_FREQ = skrf.Frequency.from_f(_FREQS_GHZ * 1e9, unit="hz")
_R_SERIES = 1.4
_C_DUT_FF = 173.5
_C_LEAD_FF = 250.0   # 引线并联电容（F6：未去嵌 Z12 427.8fF 含 ~250fF）
_C_PAD_FF = 70.0     # DUT 自带 pad 并联（属 DUT 参考面内）
_RECOVERY_TOL = 1e-9  # 任务书门（实测 ~1e-15）


def _pi_network(freq: skrf.Frequency, c_shunt_ff: float,
                alpha_np_m: float, length_m: float, z_line: float = 50.0,
                ) -> skrf.Network:
    """对称 π 夹具：并联 C/2 + 有耗线 + 并联 C/2（ABCD 闭式逐点装配）。"""
    w = 2.0 * np.pi * np.asarray(freq.f, dtype=float)
    y_half = 1j * w * (c_shunt_ff * 1e-15) / 2.0
    beta = w * 1.5 / 299792458.0  # εeff=1.5（微带量级，非"恰好"调参）
    nf = w.size
    abcd = np.zeros((nf, 2, 2), dtype=complex)
    for k in range(nf):
        g = (alpha_np_m + 1j * beta[k]) * length_m
        line = np.array([[np.cosh(g), z_line * np.sinh(g)],
                         [np.sinh(g) / z_line, np.cosh(g)]])
        shunt = np.array([[1.0, 0.0], [-y_half[k], 1.0]])
        abcd[k] = shunt @ line @ shunt
    z0 = np.full((nf, 2), 50.0)
    return skrf.Network(frequency=freq, s=_SKRF_A2S(abcd, z0), z0=50.0)


def _series_rc(freq: skrf.Frequency, r_ohm: float, c_ff: float,
               ) -> skrf.Network:
    """纯串联 RC（ABCD B 元闭式）。"""
    w = 2.0 * np.pi * np.asarray(freq.f, dtype=float)
    nf = w.size
    zs = r_ohm + 1.0 / (1j * w * c_ff * 1e-15)
    abcd = np.stack([
        np.stack([np.ones(nf, dtype=complex), zs], axis=1),
        np.stack([np.zeros(nf, dtype=complex), np.ones(nf, dtype=complex)],
                 axis=1)], axis=1)
    return skrf.Network(
        frequency=freq, s=_SKRF_A2S(abcd, np.full((nf, 2), 50.0)), z0=50.0)


def _anchor_fixture() -> tuple[skrf.Network, skrf.Network, skrf.Network]:
    """用户锚语料：(measured, thru, dut_true)——F6 场景合成。

    lead=π(250fF, 2mm 有耗线)，dut=π(70fF pad, 串联 1.4Ω+173.5fF, 70fF)。
    measured = lead ** dut ** lead、thru = lead ** lead。
    """
    lead = _pi_network(_FREQ, _C_LEAD_FF, 0.15, 0.002)
    pad = _pi_network(_FREQ, _C_PAD_FF, 0.0, 0.0)  # 零长线=纯并联 C/2×2
    core = _series_rc(_FREQ, _R_SERIES, _C_DUT_FF)
    dut = pad ** core ** pad
    meas = lead ** dut ** lead
    thru = lead ** lead
    return meas, thru, dut


def _s_diff(a: skrf.Network, b: skrf.Network) -> float:
    return float(np.max(np.abs(np.asarray(a.s) - np.asarray(b.s))))


# ── 对称半拆+双边去嵌合成回收（#340 家法） ─────────────────────────────────

def test_thru_half_network_recovers_symmetric_fixture():
    """2x-thru 半拆 → 单侧夹具逐位（π 型非匹配夹具，B/C 非零全公式面）。"""
    lead = _pi_network(_FREQ, _C_LEAD_FF, 0.15, 0.002)
    half = thru_half_network(lead ** lead)
    assert _s_diff(half, lead) < 1e-12  # 实测 3.7e-16


def test_deembed_thru_half_recovers_dut_network():
    """THRU 双边去嵌网络级回收（任务书门 rel≤1e-9）。"""
    meas, thru, dut = _anchor_fixture()
    rec = deembed_thru(meas, thru, half=True)
    assert _s_diff(rec, dut) < _RECOVERY_TOL  # 实测 ~9e-16


def test_deembed_thru_half_recovers_c_r_bitwise():
    """去嵌后 y21 口径 C/R 逐位回收（π 型 DUT 精确路线）。"""
    meas, thru, _ = _anchor_fixture()
    rec = deembed_thru(meas, thru, half=True)
    metrics = z12_series_metrics(rec, f_hz=2.4e9)
    y21 = metrics["series_y21"]
    assert y21["reactance"] == "capacitive"
    assert abs(y21["c_series_f"] - _C_DUT_FF) / _C_DUT_FF <= _RECOVERY_TOL
    assert abs(y21["r_series_ohm"] - _R_SERIES) / _R_SERIES <= _RECOVERY_TOL


def test_deembed_thru_half_long_thru_multiwavelength():
    """多波长 thru（3π 电长度跨度/101 点）半拆回收——二阶差分分支连续性。"""
    freq = skrf.Frequency.from_f(np.linspace(0.1, 6.0, 101) * 1e9, unit="hz")
    fixture = _pi_network(freq, 5.0, 0.05, 0.05)
    pad_small = _pi_network(freq, 5.0, 0.0, 0.0)
    dut_true = (pad_small ** _series_rc(freq, _R_SERIES, _C_DUT_FF)
                ** pad_small)
    rec = deembed_thru(fixture ** dut_true ** fixture,
                       fixture ** fixture, half=True)
    assert _s_diff(rec, dut_true) < _RECOVERY_TOL  # 实测 ~3e-13


def test_thru_half_network_undersampled_guard():
    """欠采样守卫：22.6rad 跨度/61 点语料（半件 B 元快振荡栅格不足）显式拒绝。"""
    freq = skrf.Frequency.from_f(np.linspace(0.1, 6.0, 61) * 1e9, unit="hz")
    fixture = _pi_network(freq, 5.0, 0.05, 0.12)
    with pytest.raises(ValueError, match="欠采样"):
        thru_half_network(fixture ** fixture)


def test_thru_half_network_asymmetric_guard():
    lead = _pi_network(_FREQ, _C_LEAD_FF, 0.15, 0.002)
    other = _pi_network(_FREQ, 100.0, 0.15, 0.002)  # 不同夹具
    with pytest.raises(ValueError, match="非对称"):
        thru_half_network(lead ** other)


def test_deembed_thru_full_length_side_legacy():
    """half=False 全长单边（遗留语义回归钉，test_deembed 同款口径）。"""
    line = _pi_network(_FREQ, 0.0, 0.15, 0.01)  # 近匹配线
    dut = _series_rc(_FREQ, _R_SERIES, _C_DUT_FF)
    rec = deembed_thru(dut ** line, line, half=False)
    assert _s_diff(rec, dut) < 1e-9


# ── 强失配拒绝+用户数值锚（P14/F6） ────────────────────────────────────────

def test_simplified_formula_rejected_under_strong_mismatch():
    """强失配（|S11|≈0.96）语料：简化式 R 误算（>2×）+rejected=True+建议。"""
    meas, _, _ = _anchor_fixture()
    metrics = z12_series_metrics(meas, f_hz=2.4e9)
    simp = metrics["simplified_formula"]
    assert metrics["series"]["s11_mag"] > 0.9
    assert simp["rejected"] is True
    assert simp["threshold"] == 0.9
    assert "Z12" in simp["advice"]
    r_simpl = simp["r_series_ohm"]
    assert abs(r_simpl - _R_SERIES) > 2.0 * _R_SERIES  # 实测 4.55Ω（3.3×）


def test_simplified_formula_dramatic_error_scenario():
    """重夹具语料：简化式 R 误算 >10×（用户 P14 量级：1.4Ω→几十 Ω）。"""
    freq = skrf.Frequency.from_f(np.linspace(0.5, 6.0, 51) * 1e9, unit="hz")
    lead = _pi_network(freq, _C_LEAD_FF, 0.0, 0.004)  # 无耗重并联夹具
    pad = _pi_network(freq, 5.0, 0.0, 0.0)
    meas = (lead ** pad ** _series_rc(freq, _R_SERIES, _C_DUT_FF)
            ** pad ** lead)
    metrics = z12_series_metrics(meas, f_hz=2.4e9)
    simp = metrics["simplified_formula"]
    assert metrics["series"]["s11_mag"] > 0.9
    assert simp["rejected"] is True
    assert abs(simp["r_series_ohm"] - _R_SERIES) > 10.0 * _R_SERIES


def test_user_numeric_anchor_returns_to_lumped_value():
    """F6 验收语义：173.5fF+250fF 引线并联场景 → 去嵌后回集总值 ±5%。

    y21 口径逐位回 173.5000fF（超验收门 4 个量级）；未去嵌语料的口径
    读数显著偏离（用户实测 427.8fF 同机制：并联寄生污染提取）。
    """
    meas, thru, _ = _anchor_fixture()
    raw = z12_series_metrics(meas, f_hz=2.4e9)
    rec = deembed_thru(meas, thru, half=True)
    dec = z12_series_metrics(rec, f_hz=2.4e9, deembedded=True)
    c_dec = dec["series_y21"]["c_series_f"]
    assert abs(c_dec - _C_DUT_FF) / _C_DUT_FF <= 0.05  # 实测 ~5.7e-14
    # 未去嵌读数被引线寄生污染（用户实测 427.8fF 同机制）：z12 主口径被
    # 250fF 引线并联电容淹没（实测 11.2fF，偏离 >50%）；y21 口径受引线
    # 串联阻抗微污染（实测 176.7fF，+1.9%）——去嵌后恢复
    c_raw_z12 = raw["series"]["c_series_f"]
    assert c_raw_z12 is None or abs(c_raw_z12 - _C_DUT_FF) / _C_DUT_FF > 0.5
    c_raw_y21 = raw["series_y21"]["c_series_f"]
    assert abs(c_raw_y21 - _C_DUT_FF) / _C_DUT_FF > 0.01  # 实测 ~1.9%
    assert dec["deembedded"] is True
    # metadata 透传（K17 metric registry 预留字段）
    dec2 = z12_series_metrics(rec, f_hz=2.4e9, deembedded=True,
                              reference_plane="thru-deembedded(half)")
    assert dec2["reference_plane"] == "thru-deembedded(half)"
    assert dec2["topology"] == "series"


def test_q_caveat_note_attached():
    meas, _, _ = _anchor_fixture()
    metrics = z12_series_metrics(meas, f_hz=2.4e9)
    assert any("Q" in n and "损耗" in n for n in metrics["notes"])


# ── 守卫族 ─────────────────────────────────────────────────────────────────

def test_pure_series_z_degenerate_guard():
    """纯串联件（端口开路转移阻抗无定义）显式拒绝——skrf 会给 ~1e10 垃圾。"""
    with pytest.raises(ValueError, match="Z 参数退化"):
        z12_series_metrics(_series_rc(_FREQ, _R_SERIES, _C_DUT_FF),
                           f_hz=2.4e9)


def test_f_eval_out_of_band_rejected():
    meas, _, _ = _anchor_fixture()
    with pytest.raises(ValueError, match="超出频带"):
        z12_series_metrics(meas, f_hz=11e9)


def test_topology_guards():
    meas, _, _ = _anchor_fixture()
    with pytest.raises(ValueError, match="topology"):
        z12_series_metrics(meas, topology="parallel")
    with pytest.raises(ValueError, match="shunt 拓扑须 1 端口"):
        z12_series_metrics(meas, topology="shunt")
    w = 2.0 * np.pi * np.asarray(_FREQ.f)
    y1 = (1 / 2000.0) + 1j * w * 250e-15
    s11 = (1 - 50 * y1) / (1 + 50 * y1)
    net1 = skrf.Network(frequency=_FREQ, s=s11.reshape(-1, 1, 1), z0=50.0)
    with pytest.raises(ValueError, match="series 拓扑须 2 端口"):
        z12_series_metrics(net1)


def test_shunt_topology_capacitive_and_srf():
    """并联 1 端口：纯 C 语料 C/Q 逐位锚 + LC 并联的 SRF 过零插值解析锚。"""
    w = 2.0 * np.pi * np.asarray(_FREQ.f)
    # 纯并联 C（G=1/2kΩ）：C/Q 逐位锚
    y_c = (1 / 2000.0) + 1j * w * 250e-15
    s11_c = (1 - 50 * y_c) / (1 + 50 * y_c)
    net_c = skrf.Network(frequency=_FREQ, s=s11_c.reshape(-1, 1, 1), z0=50.0)
    m_c = z12_series_metrics(net_c, f_hz=2.4e9, topology="shunt")
    assert m_c["shunt"]["reactance"] == "capacitive"
    assert abs(m_c["shunt"]["c_shunt_f"] - 250.0) / 250.0 < 1e-9
    assert m_c["shunt"]["q_shunt"] == pytest.approx(
        (2 * np.pi * 2.4e9 * 250e-15) / 5e-4, rel=1e-9)
    # LC 并联（SRF=1/(2π√(LC))）：感性/容性换向+SRF 插值
    y = (1 / 2000.0) + 1j * (w * 250e-15 - 1.0 / (w * 8e-9))
    s11 = (1 - 50 * y) / (1 + 50 * y)
    net = skrf.Network(frequency=_FREQ, s=s11.reshape(-1, 1, 1), z0=50.0)
    below = z12_series_metrics(net, f_hz=2.0e9, topology="shunt")
    assert below["shunt"]["reactance"] == "inductive"  # f<SRF 感性
    # 有效 L = L/(1−ω²LC)（并联 C 与 L 共同决定 B，解析对照）
    w2 = 2 * np.pi * 2e9
    l_eff = 8e-9 / (1.0 - w2 * w2 * 250e-15 * 8e-9)
    assert below["shunt"]["l_shunt_h"] == pytest.approx(l_eff, rel=1e-9)
    above = z12_series_metrics(net, f_hz=5.0e9, topology="shunt")
    assert above["shunt"]["reactance"] == "capacitive"
    # B>0 侧 C_eff=B/ω 含 L 贡献（B=ωC−1/(ωL)，解析对照非裸 C）
    w5 = 2 * np.pi * 5e9
    assert above["shunt"]["c_shunt_f"] == pytest.approx(
        (w5 * 250e-15 - 1.0 / (w5 * 8e-9)) / w5 * 1e15, rel=1e-9)
    srf_expected = 1.0 / (2 * np.pi * np.sqrt(250e-15 * 8e-9))
    assert below["srf_hz"] is not None
    assert abs(below["srf_hz"] - srf_expected) / srf_expected < 1e-3


def test_default_f_eval_is_geometric_center():
    meas, _, _ = _anchor_fixture()
    m = z12_series_metrics(meas)
    center = float(np.sqrt(_FREQS_GHZ[0] * _FREQS_GHZ[-1]))
    assert m["f_eval_hz"] == pytest.approx(
        _FREQS_GHZ[np.argmin(np.abs(_FREQS_GHZ - center))] * 1e9)


# ── CALC 键（服务层信封） ───────────────────────────────────────────────────

def _pair_lists(net: skrf.Network) -> dict:
    s = np.asarray(net.s)
    out: dict = {"freq_ghz": [float(x) / 1e9 for x in net.f]}
    for i, j, name in ((0, 0, "s11"), (1, 0, "s21"),
                       (0, 1, "s12"), (1, 1, "s22")):
        out[name] = [[float(v.real), float(v.imag)] for v in s[:, i, j]]
    return out


def test_calc_key_z12_series_extract_via_service():
    from rfauto.service.calculator_service import run_calculator

    meas, _, _ = _anchor_fixture()
    p = _pair_lists(meas)
    out = run_calculator("z12_series_extract", {
        "freq_ghz": p["freq_ghz"], "s11": p["s11"], "s21": p["s21"],
        "s12": p["s12"], "s22": p["s22"], "f_eval_ghz": 2.4})
    assert out["ok"] is True, out.get("error")
    res = out["result"]
    assert res["simplified_formula"]["rejected"] is True
    assert res["assumed"] == {"s12_reciprocal": False, "s22_symmetric": False}
    json.dumps(out, allow_nan=False)
    # 缺 s12/s22 时互易/对称假设透传
    out2 = run_calculator("z12_series_extract", {
        "freq_ghz": p["freq_ghz"], "s11": p["s11"], "s21": p["s21"],
        "f_eval_ghz": 2.4})
    assert out2["ok"] is True
    assert out2["result"]["assumed"] == {
        "s12_reciprocal": True, "s22_symmetric": True}


def test_calc_key_deembed_thru_metrics_via_service():
    from rfauto.service.calculator_service import run_calculator

    meas, thru, _ = _anchor_fixture()
    pm, pt = _pair_lists(meas), _pair_lists(thru)
    out = run_calculator("deembed_thru_metrics", {
        "freq_ghz": pm["freq_ghz"],
        "dut_s11": pm["s11"], "dut_s21": pm["s21"],
        "dut_s12": pm["s12"], "dut_s22": pm["s22"],
        "thru_s11": pt["s11"], "thru_s21": pt["s21"],
        "thru_s12": pt["s12"], "thru_s22": pt["s22"],
        "f_eval_ghz": 2.4})
    assert out["ok"] is True, out.get("error")
    res = out["result"]
    assert res["deembed"] == {"mode": "half-split", "n_points": 96}
    assert res["deembedded"] is True
    assert res["reference_plane"] == "thru-deembedded(half-split)"
    assert abs(res["series_y21"]["c_series_f"] - _C_DUT_FF) / _C_DUT_FF <= 0.05
    json.dumps(out, allow_nan=False)


def test_calc_keys_domain_errors():
    from rfauto.service.calculator_service import run_calculator

    cases = [
        ("z12_series_extract", {"freq_ghz": [1.0], "s11": [[0.1, 0.0]]}),  # series 缺 s21
        ("z12_series_extract", {"freq_ghz": [1.0], "s11": [[0.1, 0.0]],
                                "s21": [[0.9, 0.0]],
                                "topology": "shunt"}),  # shunt 拒收带 s21
        ("z12_series_extract", {"freq_ghz": [1.0],
                                "s11": [[1.5, 0.0]], "s21": [[0.1, 0.0]]}),  # |S|>1
        ("z12_series_extract", {"freq_ghz": [1.0, 2.0],
                                "s11": [[0.1, 0.0]],
                                "s21": [[0.1, 0.0]]}),  # 长度不一致
        ("z12_series_extract", {"freq_ghz": [1.0], "s11": [[0.1, 0.0]],
                                "s21": [[0.1, 0.0]], "f_eval_ghz": 5.0}),  # 出带
        ("deembed_thru_metrics", {
            "freq_ghz": [1.0], "dut_s11": [[0.1, 0.0]], "dut_s21": [[0.9, 0.0]],
            "thru_s11": [[0.0, 0.0], [0.0, 0.0]],
            "thru_s21": [[1.0, 0.0], [1.0, 0.0]]}),  # thru 长度≠dut
    ]
    for name, params in cases:
        out = run_calculator(name, params)
        assert out["ok"] is False and out.get("error"), (name, params, out)


# ── CLI 两叶（CliRunner 信封+退出码） ──────────────────────────────────────

@pytest.fixture()
def _touchstone_files(tmp_path: Path):
    meas, thru, _ = _anchor_fixture()
    w = 2.0 * np.pi * np.asarray(_FREQ.f)
    y1 = (1 / 2000.0) + 1j * w * 250e-15
    s11_1p = (1 - 50 * y1) / (1 + 50 * y1)
    skrf.Network(frequency=_FREQ, s=s11_1p.reshape(-1, 1, 1), z0=50.0
                 ).write_touchstone(tmp_path / "shunt.s1p")
    meas.write_touchstone(tmp_path / "dut.s2p")
    thru.write_touchstone(tmp_path / "thru.s2p")
    return tmp_path


def test_cli_em_deembed_json_envelope(_touchstone_files, monkeypatch):
    from typer.testing import CliRunner

    from rfauto.cli.main import app as root_app

    monkeypatch.chdir(_touchstone_files)
    runner = CliRunner()
    result = runner.invoke(root_app, [
        "em", "deembed", "--dut", "dut.s2p", "--thru", "thru.s2p",
        "--f-eval-ghz", "2.4", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["deembed"]["mode"] == "half-split"
    assert abs(payload["series_y21"]["c_series_f"] - _C_DUT_FF) <= 0.05 * _C_DUT_FF
    # 失败信封（缺文件）+退出码 1
    bad = runner.invoke(root_app, [
        "em", "deembed", "--dut", "nope.s2p", "--thru", "thru.s2p", "--json"])
    assert bad.exit_code == 1
    assert json.loads(bad.output)["ok"] is False


def test_cli_em_metrics_json_envelope(_touchstone_files, monkeypatch):
    from typer.testing import CliRunner

    from rfauto.cli.main import app as root_app

    monkeypatch.chdir(_touchstone_files)
    runner = CliRunner()
    result = runner.invoke(root_app, [
        "em", "metrics", "--s2p", "shunt.s1p", "--topology", "shunt",
        "--f-eval-ghz", "2.4", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert abs(payload["shunt"]["c_shunt_f"] - 250.0) <= 0.05 * 250.0
    # series 语料+拒绝面
    result2 = runner.invoke(root_app, [
        "em", "metrics", "--s2p", "dut.s2p", "--f-eval-ghz", "2.4", "--json"])
    assert result2.exit_code == 0
    payload2 = json.loads(result2.output)
    assert payload2["simplified_formula"]["rejected"] is True
    # 拓扑错配失败信封
    bad = runner.invoke(root_app, [
        "em", "metrics", "--s2p", "dut.s2p", "--topology", "shunt", "--json"])
    assert bad.exit_code == 1
    assert json.loads(bad.output)["ok"] is False
