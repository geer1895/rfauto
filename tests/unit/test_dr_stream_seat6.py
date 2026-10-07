"""席6 DR 系测试：CDR mask（DR-9）+ 交错 SFDR/JESD204C（DR-10）
+ 串扰级联消费接口（DR-11）。DR-2/3 见 test_serdes_referee.py。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.cdr_jitter_mask import (
    cdr_jitter_transfer_first_order,
    cdr_jitter_transfer_second_order,
    cdr_mask_margin,
    cdr_peaking_factor,
)
from rfauto.core.interleave_spurs import (
    interleave_spur_table,
    q_factor,
    total_jitter_snr,
)
from rfauto.core.xtalk_cascade import (
    mock_fext_response,
    mock_next_response,
    xtalk_cascade_margin,
)

# ── DR-9 CDR ─────────────────────────────────────────────────────────────────


def test_first_order_jt_anchors() -> None:
    """一阶 JT 锚：JT(fc)=√2；高频平台→1；低频 −20 dB/dec（斜率钉）。"""
    fc = 1e6
    f = np.array([0.1e6, 1e6, 10e6, 100e6])
    jt = cdr_jitter_transfer_first_order(f, fc)
    assert jt[1] == pytest.approx(math.sqrt(2.0), rel=1e-9)
    assert jt[3] == pytest.approx(1.0, abs=1e-4)
    assert jt[0] == pytest.approx(math.sqrt(1.01) / 0.1, rel=1e-9)  # 解析值
    with pytest.raises(ValueError, match="全为正"):
        cdr_jitter_transfer_first_order(np.array([0.0, 1.0]), fc)


def test_second_order_peaking_formula() -> None:
    """二阶 peaking 闭式：|H|max=1/(2ζ√(1−ζ²))；ζ≥1/√2 无峰=1；阻尼对称域。"""
    assert cdr_peaking_factor(0.3) == pytest.approx(
        1.0 / (2 * 0.3 * math.sqrt(1 - 0.09)), rel=1e-12)
    assert cdr_peaking_factor(0.8) == 1.0
    assert cdr_peaking_factor(0.7071) == pytest.approx(1.0, abs=1e-3)
    with pytest.raises(ValueError, match="zeta"):
        cdr_peaking_factor(0.0)


def test_second_order_jt_shape() -> None:
    """二阶 JT：低频 −40 dB/dec（两个积分器）、高频平台 1。"""
    fn = 1e6
    f = np.array([0.001e6, 0.01e6, 10e6])
    jt = cdr_jitter_transfer_second_order(f, fn, 0.707)
    r10 = jt[1] / jt[0]
    assert r10 == pytest.approx(10.0, rel=0.05)  # −40dB/dec → 十倍频 ×100/10
    assert jt[2] == pytest.approx(1.0, abs=0.05)
    with pytest.raises(ValueError, match="zeta"):
        cdr_jitter_transfer_second_order(f, fn, 2.5)


def test_cdr_mask_margin_verdict() -> None:
    """mask 余量：宽松 mask 全过；紧 mask 指认最坏频点（对数域插值）。"""
    f = np.logspace(4, 9, 200)
    jt = cdr_jitter_transfer_first_order(f, 1e6)
    loose = cdr_mask_margin(f, jt, [(1e5, 100.0), (1e7, 1.1)])
    assert loose["verdict"] == "pass"
    tight = cdr_mask_margin(f, jt, [(1e6, 1.0), (1e7, 0.9)])
    assert tight["verdict"] == "fail"
    assert tight["worst_freq_hz"] == pytest.approx(1e6, rel=1e-9)
    with pytest.raises(ValueError, match="正"):
        cdr_mask_margin(f, jt, [(1e6, 0.0)])


# ── DR-10 交错杂散 + JESD204C ───────────────────────────────────────────────


def test_interleave_spur_positions_m2_m4() -> None:
    """杂散位置锚：M=2 → fs/2±fin；M=4 → fs/4±fin（交错经典族，折叠入带）。"""
    fs, fin = 100.0, 7.0
    out2 = interleave_spur_table(fs, fin, 2)
    got2 = {round(r["freq_hz"], 6) for r in out2["spurs"]}
    assert (fs / 2 - fin) in got2 or round(fs / 2 - fin, 6) in got2
    assert any(abs(r["freq_hz"] - (fs / 2 - fin)) < 1e-9
               for r in out2["spurs"])
    assert any(abs(r["freq_hz"] - fin) < 1e-9 for r in out2["spurs"])  # 镜像
    out4 = interleave_spur_table(fs, fin, 4)
    assert any(abs(r["freq_hz"] - (fs / 4 + fin)) < 1e-9
               for r in out4["spurs"])
    assert any(abs(r["freq_hz"] - (fs / 4 - fin)) < 1e-9
               for r in out4["spurs"])
    # 全部折叠进第一奈奎斯特区
    for r in out4["spurs"]:
        assert 0.0 <= r["freq_hz"] <= fs / 2.0 + 1e-9


def test_interleave_spur_guards() -> None:
    """守卫：fin 越奈奎斯特区 / 非整数路数显式拒绝。"""
    with pytest.raises(ValueError, match="奈奎斯特区"):
        interleave_spur_table(100.0, 51.0, 2)
    with pytest.raises(ValueError, match="≥2 整数"):
        interleave_spur_table(100.0, 7.0, 1)
    with pytest.raises(ValueError, match="≥2 整数"):
        interleave_spur_table(100.0, 7.0, 2.5)


def test_q_factor_erfc_definition() -> None:
    """Q(BER)=√2·erfcinv(2BER)：erfc 数值回代 BER 精确复原（定义式自洽）+
    公开习惯值锚（1e-12→7.03、1e-15→7.94）。"""
    for ber in (1e-3, 1e-9, 1e-12, 1e-15):
        q = q_factor(ber)
        ber_back = 0.5 * math.erfc(q / math.sqrt(2.0))
        assert ber_back == pytest.approx(ber, rel=1e-6)
    assert q_factor(1e-12) == pytest.approx(7.0345, abs=5e-4)
    assert q_factor(1e-15) == pytest.approx(7.9413, abs=5e-4)


def test_total_jitter_budget() -> None:
    """TJ = Q·RJ + DJ：RJ/DJ 线性入账；SNR 换算 = 20log10(1/2TJ)。"""
    out = total_jitter_snr(0.01, 0.05, ber=1e-12)
    q = q_factor(1e-12)
    assert out["tj_ui"] == pytest.approx(q * 0.01 + 0.05)
    assert out["snr_db"] == pytest.approx(
        20 * math.log10(1.0 / (2 * out["tj_ui"])), rel=1e-12)
    with pytest.raises(ValueError, match="非负"):
        total_jitter_snr(-0.01, 0.05)


# ── DR-11 串扰级联 ────────────────────────────────────────────────────────────


def test_xtalk_mock_response_shape() -> None:
    """mock 闭式：|NEXT| ∝ f（高通上升族），相位 +90°（纯电抗耦合）。"""
    f = np.array([1e6, 10e6, 100e6])
    nxt = mock_next_response(f, 1e-12)
    np.testing.assert_allclose(np.abs(nxt), 2 * math.pi * f * 1e-12,
                               rtol=1e-12)
    np.testing.assert_allclose(np.angle(nxt), math.pi / 2, atol=1e-12)
    assert mock_fext_response is not None
    with pytest.raises(ValueError, match="必须为正"):
        mock_next_response(f, 0.0)


def test_xtalk_cascade_margin_arithmetic() -> None:
    """级联账手算：P_eq = P_aggr + 20log10|c| + ΣG；margin=sens−P_eq。"""
    f = np.array([1e9])
    c = 1e-3  # −60 dB
    out = xtalk_cascade_margin(f, 10.0, lambda x: np.full_like(
        np.asarray(x, dtype=float), c, dtype=complex),
        victim_chain_gain_db=[10.0, -5.0], victim_sensitivity_dbm=-40.0)
    expect_eq = 10.0 + 20 * math.log10(1e-3) + 5.0  # 10−60+5 = −45 dBm
    assert out["p_equiv_interference_dbm"][0] == pytest.approx(
        expect_eq, rel=1e-12)
    assert out["margin_db"][0] == pytest.approx(-40.0 - expect_eq,
                                                rel=1e-12)
    assert out["verdict"][0] == "safe"  # −45 dBm 干扰 < −40 dBm 门限
    tight = xtalk_cascade_margin(f, 30.0, lambda x: np.full_like(
        np.asarray(x, dtype=float), c, dtype=complex),
        victim_sensitivity_dbm=-40.0)
    assert tight["verdict"][0] == "interfered"
    assert tight["worst_margin_db"] == tight["margin_db"][0]


def test_xtalk_consumer_interface_accepts_callable_and_rejects_garbage() -> None:
    """消费接口：可调用对象直通（MT-3 落地后系数函数即此形态）；垃圾入参显式拒。"""
    f = np.array([1e9, 2e9])
    out = xtalk_cascade_margin(f, 0.0, lambda fr: np.full(fr.size, 1e-4,
                                                          dtype=complex))
    assert out["coupling_db"][0] == pytest.approx(-80.0, abs=1e-9)
    assert out["coupling_source"].startswith("callable/network")
    with pytest.raises(TypeError, match=r"callable.*skrf.Network"):
        xtalk_cascade_margin(f, 0.0, 0.001)
