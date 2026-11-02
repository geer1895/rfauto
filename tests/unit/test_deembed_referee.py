"""DP-15 C2 件1+件2：2x-thru 双路去嵌裁判 + s_error 包装（runs/df6_dp15c2/criteria.md）。

判据预声明（§1/§2）：理想匹配线合成语料 G1–G3 < 1e-6；s_error 恒等=0/已知
缩放=解析值逐位；ZC opt-in 不设门只记结构；skrf 版本钉 2.1.0。

合成语料全部解析构造（零真机零仿真秒级）：理想线 fixture + ABCD 合成 DUT
（skrf a2s 独立换形，与裁判面无同源代码）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

import skrf

from rfauto.core.deembed_referee import (
    DEFAULT_DC_MODE,
    DEFAULT_S_ERROR_FUNCTION,
    S_ERROR_FUNCTIONS,
    referee_2xthru_deembed,
    s_error_max,
    s_error_metric,
)

pytestmark = [
    pytest.mark.filterwarnings("ignore::RuntimeWarning"),
    pytest.mark.filterwarnings("ignore::UserWarning"),
]

C0 = 299_792_458.0

# ─── 合成语料（解析构造）─────────────────────────────────────────────────────


def _freq(n_points: int = 801) -> skrf.Frequency:
    return skrf.Frequency(0.1, 40.0, n_points, "GHz")


def _make_fix(
    freq: skrf.Frequency,
    length_m: float,
    eps_eff: float = 3.0,
    z0: float = 50.0,
    alpha_np_m: float = 0.0,
    line_z0: float | None = None,
) -> skrf.Network:
    """理想线 fixture（γ=α+jβ 解析；端口参考恒 z0）。

    line_z0=None 时线阻抗=端口参考（匹配线，S11=0）；给值时构造 Z0=line_z0
    的理想线段 ABCD 再按端口参考换形（失配线 S11≠0，判别力负例用）。
    """
    from skrf.network import a2s

    f = np.asarray(freq.f, dtype=float)
    gamma = alpha_np_m + 1j * 2.0 * np.pi * f * np.sqrt(eps_eff) / C0
    if line_z0 is None:
        s = np.zeros((f.size, 2, 2), dtype=complex)
        t = np.exp(-gamma * length_m)
        s[:, 0, 1] = t
        s[:, 1, 0] = t
        return skrf.Network(frequency=freq, s=s, z0=z0)
    gl = gamma * length_m
    ch, sh = np.cosh(gl), np.sinh(gl)
    ab = np.zeros((f.size, 2, 2), dtype=complex)
    ab[:, 0, 0] = ch
    ab[:, 0, 1] = line_z0 * sh
    ab[:, 1, 0] = sh / line_z0
    ab[:, 1, 1] = ch
    return skrf.Network(frequency=freq, s=a2s(ab, z0), z0=z0)


def _make_dut(
    freq: skrf.Frequency,
    z0: float = 50.0,
    eps_eff: float = 2.25,
    length_m: float = 4e-3,
    c_farad: float = 0.3e-12,
) -> skrf.Network:
    """合成 DUT：shunt C + 线 + shunt C（ABCD 独立构造 → a2s 换形）。"""
    from skrf.network import a2s

    f = np.asarray(freq.f, dtype=float)
    gl = 1j * 2.0 * np.pi * f * np.sqrt(eps_eff) / C0 * length_m
    ch, sh = np.cosh(gl), np.sinh(gl)
    abl = np.zeros((f.size, 2, 2), dtype=complex)
    abl[:, 0, 0] = ch
    abl[:, 0, 1] = z0 * sh
    abl[:, 1, 0] = sh / z0
    abl[:, 1, 1] = ch
    aby = np.zeros((f.size, 2, 2), dtype=complex)
    aby[:, 0, 0] = 1.0
    aby[:, 1, 0] = 1j * 2.0 * np.pi * f * c_farad
    aby[:, 1, 1] = 1.0
    ab = aby @ abl @ aby
    return skrf.Network(frequency=freq, s=a2s(ab, z0), z0=z0)


def _ideal_corpus(n_points: int = 801):
    """理想匹配线语料：FIX(25mm) ** DUT ** FIX + 同 fixture 的 2x-thru。"""
    freq = _freq(n_points)
    lf = 25e-3
    fix = _make_fix(freq, lf)
    dut = _make_dut(freq)
    thru2x = fix ** fix
    fdf = fix ** dut ** fix
    return freq, lf, dut, thru2x, fdf


# ─── 件2：s_error 包装 ───────────────────────────────────────────────────────


def test_skrf_version_pinned_2_1_0():
    """版本钉：skrf 升级必须自觉改钉（spec 件2 口径）。"""
    assert skrf.__version__ == "2.1.0"


def test_p370_import_path_is_deembedding_submodule():
    """审计 §1 注钉：P370 类在 calibration.deembedding 子模块，顶层 ImportError。"""
    from skrf.calibration.deembedding import IEEEP370_SE_NZC_2xThru
    from skrf.taper import Klopfenstein

    assert IEEEP370_SE_NZC_2xThru is not None
    assert Klopfenstein is not None
    with pytest.raises(ImportError):
        from skrf.calibration import IEEEP370_SE_NZC_2xThru


def test_s_error_identity_is_exactly_zero():
    freq = _freq(101)
    net = _make_dut(freq)
    for ef in S_ERROR_FUNCTIONS:
        err = s_error_metric(net, net, ef)
        assert err.shape == (101,)
        assert np.all(err == 0.0), f"恒等网络 {ef} 非零"


def test_s_error_known_scaling_analytic_bitwise():
    """全零网络 vs 全 0.25 常数矩阵：四口径解析手算值逐位相等（criteria §2）。

    常数取 2 的幂（0.25/0.0625）保证 float64 二进制精确——"逐位"语义成立；
    0.1² 之类十进制常数有最近舍入 ulp 差，不配逐位断言。
    """
    freq = _freq(31)
    zeros = skrf.Network(
        frequency=freq, s=np.zeros((31, 2, 2), dtype=complex), z0=50.0)
    const = skrf.Network(
        frequency=freq,
        s=np.full((31, 2, 2), 0.25, dtype=complex), z0=50.0)
    # average_l1 = mean|Δ| = 0.25；average_l2 = mean|Δ|² = 0.0625；
    # maximum_l1 = max|Δ| = 0.25；average_normalized = 2·0.25/(0+0.25) = 2.0
    assert np.all(s_error_metric(zeros, const, "average_l1_norm") == 0.25)
    assert np.all(s_error_metric(zeros, const, "average_l2_norm") == 0.0625)
    assert np.all(s_error_metric(zeros, const, "maximum_l1_norm") == 0.25)
    assert np.all(
        s_error_metric(zeros, const, "average_normalized_l1_norm") == 2.0)
    assert s_error_max(zeros, const) == 0.0625


def test_s_error_guards_are_explicit():
    freq_a = _freq(41)
    freq_b = skrf.Frequency(0.1, 40.0, 33, "GHz")
    net_a = _make_dut(freq_a)
    net_b = _make_dut(freq_b)
    net4 = skrf.Network(frequency=freq_a,
                        s=np.zeros((41, 4, 4), dtype=complex), z0=50.0)
    with pytest.raises(ValueError, match="error_function"):
        s_error_metric(net_a, net_a, "bogus_norm")
    with pytest.raises(ValueError, match="频率栅格"):
        s_error_metric(net_a, net_b)
    with pytest.raises(ValueError, match="端口数"):
        s_error_metric(net_a, net4)
    with pytest.raises(TypeError, match="Network"):
        s_error_metric(net_a, "not a network")


# ─── 件1：2x-thru 双路去嵌裁判 ───────────────────────────────────────────────


def test_referee_ideal_case_gate_pass_and_deterministic():
    """G1–G3 < 1e-6（规格书判据），重复调用逐字段一致。"""
    _freq_ob, lf, dut, thru2x, fdf = _ideal_corpus()
    kwargs = dict(
        dut_fdf=fdf,
        dummy_2xthru=thru2x,
        dut_reference=dut,
        fixture_length_m=lf,
    )
    out = referee_2xthru_deembed(**kwargs)
    assert out["ok"] is True
    assert out["gate_threshold"] == 1e-6
    assert out["dc_mode"] == DEFAULT_DC_MODE
    assert out["n_points"] == 801
    # 实测余量 ≥5 个量级：三列都钉住（阈值判据 < 1e-6 之外的实测记录）
    assert out["referee_max_s_error"] < 1e-6
    assert out["inhouse_vs_reference_max"] < 1e-6
    assert out["p370_vs_reference_max"] < 1e-6
    again = referee_2xthru_deembed(**kwargs)
    assert out == again, "裁判面非确定性"


def test_referee_dc_mode_add_dc_and_none_also_pass():
    """DC 三模式在合规语料上均过门（坑未显现，守卫保留——criteria §0.2）。"""
    _freq_ob, lf, dut, thru2x, fdf = _ideal_corpus()
    for dc_mode in (None, "add_dc"):
        out = referee_2xthru_deembed(
            dut_fdf=fdf, dummy_2xthru=thru2x, dut_reference=dut,
            fixture_length_m=lf, dc_mode=dc_mode)
        assert out["ok"] is True, f"dc_mode={dc_mode}"
        assert out["referee_max_s_error"] < 1e-6


def test_referee_detects_mismatch_prior_divergence():
    """判别力负例：43Ω 失配 fixture 上匹配先验自研路发散 → ok=False。

    钉的是裁判行为（两路显著分开），不钉具体数值（criteria §1）。
    """
    freq = _freq()
    lf = 25e-3
    fix = _make_fix(freq, lf, z0=50.0, line_z0=43.0)
    dut = _make_dut(freq)
    thru2x = fix ** fix
    fdf = fix ** dut ** fix
    out = referee_2xthru_deembed(
        dut_fdf=fdf, dummy_2xthru=thru2x, dut_reference=dut,
        fixture_length_m=lf)
    assert out["ok"] is False
    assert out["referee_max_s_error"] > 1e-6
    assert out["inhouse_vs_reference_max"] > 1e-6


def test_referee_zc_optin_recorded_not_gated():
    """ZC opt-in：结构完整、gated=False、不影响 ok 判定（criteria §0.4）。"""
    _freq_ob, lf, dut, thru2x, fdf = _ideal_corpus()
    plain = referee_2xthru_deembed(
        dut_fdf=fdf, dummy_2xthru=thru2x, dut_reference=dut,
        fixture_length_m=lf)
    out = referee_2xthru_deembed(
        dut_fdf=fdf, dummy_2xthru=thru2x, dut_reference=dut,
        fixture_length_m=lf, zc_fix_dut_fix=fdf)
    assert out["ok"] == plain["ok"]
    zc = out["zc_variant"]
    assert isinstance(zc, dict)
    assert zc["ran"] is True and zc["gated"] is False
    assert np.isfinite(zc["vs_reference_max"])
    assert np.isfinite(zc["vs_inhouse_max"])
    # 同一语料丢掉 ZC 后 zc_variant 如实为 None
    assert plain["zc_variant"] is None


def test_referee_input_guards_explicit():
    _freq_ob, lf, dut, thru2x, fdf = _ideal_corpus(101)
    base = dict(dut_fdf=fdf, dummy_2xthru=thru2x, dut_reference=dut)
    with pytest.raises(TypeError, match="Network"):
        referee_2xthru_deembed(
            dut_fdf="nope", dummy_2xthru=thru2x, dut_reference=dut,
            fixture_length_m=lf)
    with pytest.raises(ValueError, match="fixture_length_m"):
        referee_2xthru_deembed(fixture_length_m=0.0, **base)
    with pytest.raises(ValueError, match="dc_mode"):
        referee_2xthru_deembed(fixture_length_m=lf, dc_mode="bogus", **base)
    with pytest.raises(ValueError, match="网格"):
        short = _make_dut(skrf.Frequency(0.1, 40.0, 33, "GHz"))
        referee_2xthru_deembed(
            dut_fdf=fdf, dummy_2xthru=thru2x, dut_reference=short,
            fixture_length_m=lf)
    with pytest.raises(ValueError, match="gate_threshold"):
        referee_2xthru_deembed(
            fixture_length_m=lf, gate_threshold=-1.0, **base)
    assert DEFAULT_S_ERROR_FUNCTION == "average_l2_norm"
