"""MS-2 MM_NZC 多端口 AFR 去嵌测试（round15 MS-2：4 端口 fix-DUT-fix 回收）。

验收口径（规格钉）：合成语料上 DUT 有效元回收 |ΔS|_dB ≤ 1e-3，深零/隔离元
以复数线性残差另行把关（dB 域对深零元无意义）。

语料勘误（skrf 2.1.0 实测）：``DefinedGammaZ0.attenuator`` 把 dB 衰减实现成
``db_2_magnitude`` 正号（attenuator(6) → |S21|=1.995 放大），与 1.x 的
``10**(-s/20)`` 相反——测试语料一律手工缩放，不走该 API。
"""

from __future__ import annotations

import numpy as np
import pytest
import skrf
from skrf.media import DefinedGammaZ0

from rfauto.measurement.afr_2xthru import (
    check_2xthru_preconditions_mm,
    deembed_2xthru,
    deembed_2xthru_mm,
    recovery_delta_s21_db,
    recovery_delta_s_db,
    recovery_delta_s_lin,
)

FREQ = skrf.Frequency(0.05, 20, 401, "ghz")
MEDIA = DefinedGammaZ0(FREQ)


def _pair_through_4port(length_m: float, loss_db_per_m: float) -> skrf.Network:
    """4 端口「一对直通线」（'second' 口序：左 0,1 → 右 2,3）。

    口对 k 各走一段长/损可不同的 50Ω 匹配线——两对不对称才能抓跨对串扰
    污染。损耗以匹配缩放因子直接乘通路段 S（skrf 2.1 ``Media.attenuator``
    实测是 +dB 增益、符号反向，不可用——见本文件 docstring 勘误）。
    """
    s = np.zeros((len(FREQ.f), 4, 4), dtype=complex)
    for k, (left, right) in enumerate(((0, 2), (1, 3))):
        seg = MEDIA.line(length_m * (1.0 + 0.4 * k), unit="m")
        gain = 10.0 ** (-loss_db_per_m * (1.0 + 0.4 * k) / 20.0)
        s[:, right, left] = seg.s[:, 1, 0] * gain
        s[:, left, right] = seg.s[:, 0, 1] * gain
    return skrf.Network(frequency=FREQ, s=s, name="pair_through")


def _cascade_two(a: skrf.Network, b: skrf.Network) -> skrf.Network:
    """'second' 口序 4 端口级联（skrf ``**`` 运算符同语义，显式调用防歧义）。"""
    return a ** b


def _fixture_composite() -> tuple[skrf.Network, skrf.Network, skrf.Network]:
    """合成 (twoxthru, dut, fdf)：夹具=两对不对称线，DUT=异长线+6dB 衰减对。"""
    fix_left = _pair_through_4port(0.020, 0.0)
    fix_right = _pair_through_4port(0.030, 0.0)
    twoxthru = _cascade_two(fix_left, fix_right)

    dut = _pair_through_4port(0.045, 6.0)
    # DUT 再叠一点对的差异：第二对叠 3dB 衰减（直接改 S 参数合成）
    dut.s[:, 3, 1] *= 10 ** (-3.0 / 20.0)
    dut.s[:, 1, 3] *= 10 ** (-3.0 / 20.0)
    fdf = _cascade_two(_cascade_two(fix_left, dut), fix_right)
    return twoxthru, dut, fdf


def test_mm_nzc_four_port_recovery_within_1e3_db() -> None:
    """规格验收：4 端口 fix-DUT-fix 回收（有效元 |ΔS|_dB ≤1e-3 + 深零元线性残差）。"""
    twoxthru, dut, fdf = _fixture_composite()
    out = deembed_2xthru_mm(fdf, twoxthru)
    assert out["ok"], out.get("error")
    assert out["deembedder"] == "IEEEP370_MM_NZC_2xThru"
    delta = recovery_delta_s_db(out["network"], dut, floor_lin=1e-3)
    assert delta <= 1e-3, f"回收残差 {delta:.3e} dB 超 1e-3 门"
    lin = recovery_delta_s_lin(out["network"], dut)
    # 深零/隔离元泄漏实测 ~5e-3（−46 dB 量级）= NZC 时域门限法的诚实精度
    # （skrf docstring 自述 crude but robust）；门钉 −40 dB（1e-2 线性）。
    assert lin <= 1e-2, f"线性残差 {lin:.3e} 超 −40 dB 泄漏门"


def test_mm_nzc_precheck_pass_and_pairwise_symmetry_gate() -> None:
    """预检：合规 2x-thru 过门；人为破坏口对 1 对称性 → 指认该口对。"""
    twoxthru, _, _ = _fixture_composite()
    pre = check_2xthru_preconditions_mm(twoxthru)
    assert pre.ok, pre.failures

    bad = twoxthru.copy()
    bad.s[:, 3, 1] *= 1.05  # 破坏口对 (1,3) 的 S13/S31 对称（反向乘 1.05）
    pre_bad = check_2xthru_preconditions_mm(bad)
    assert not pre_bad.ok
    assert any("(1,3)" in msg for msg in pre_bad.failures)


def test_mm_nzc_port_count_guard_and_freq_mismatch() -> None:
    """守卫：非 4 端口显式拒绝；频率栅格不一致显式拒绝（不静默）。"""
    twox, _, _ = _fixture_composite()
    two_port = twox.s[:, :2, :2]
    net2 = skrf.Network(frequency=FREQ, s=two_port)
    with pytest.raises(ValueError, match="4 端口"):
        deembed_2xthru_mm(net2, twox)
    other_freq = skrf.Frequency(0.1, 20, 301, "ghz")
    m2 = DefinedGammaZ0(other_freq)
    # 用同款构造器造栅格不同的 4 端口
    s = np.zeros((len(other_freq.f), 4, 4), dtype=complex)
    net4_other = skrf.Network(frequency=other_freq, s=s)
    with pytest.raises(ValueError, match="频率栅格"):
        deembed_2xthru_mm(twox, net4_other)
    assert MEDIA is not None and m2 is not None


def test_single_end_path_still_gated_and_2port_recovery() -> None:
    """单端路径回归：同语料的 2 端口子网走原 SE_NZC 亦达标（防扩面破旧）。"""
    twoxthru, dut, fdf = _fixture_composite()

    def sub(net: skrf.Network, lo: int, hi: int) -> skrf.Network:
        return skrf.Network(
            frequency=FREQ, s=net.s[:, [hi, lo], :][:, :, [hi, lo]])

    out = deembed_2xthru(sub(fdf, 0, 2), sub(twoxthru, 0, 2))
    assert out["ok"], out.get("error")
    delta = recovery_delta_s21_db(out["network"], sub(dut, 0, 2))
    assert delta <= 1e-3, f"单端口对回收残差 {delta:.3e} dB"
    assert np.asarray(out["precheck"]["symmetry_max"]) >= 0.0
