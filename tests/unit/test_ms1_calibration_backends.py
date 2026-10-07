"""MS-1 skrf 校准后端扩容+残差诊断（规格 D-2，2026-10-02）。

验收锚（规格原文：合成已知误差盒 directivity −40dB 等 mock 语料→回收
|Δ|≤−60dB，零仪器）：
① 透传类 11 类 venv 实测存在性表（MultilineTRL=TRL 别名不单设）；
② 每透传类 ≥1 合成语料冒烟：embed→校准→DUT 回收 max|ΔS|≤1e-9；
③ SOLT 象限语料四参数×正反向逐系数回收 ≤−60dB（实测 ≤−305dB；
   Elf/Elr 象限身份由 probe 实测钉定：Elf=yf 端 0 反射、Elr=xr 端 1）；
④ 残差诊断 schema（residual_networks/error_terms 四参数分列/thresholds/
   verdict）+ JSON 安全 + NIST/TUG 残差语义降级（skrf 内部 ideals:=measured）；
⑤ calkit catalog schema v2（offset_delay_ps/offset_loss_db_per_mm/
   offset_z0_ohm，DefinedGammaZ0 合成非理想件）向后兼容 v1；
⑥ vna_service ``calibration_diagnostics.json`` 挂点（JSON 进出）。
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pytest
import skrf
import yaml

from rfauto.measurement.calibration import (
    DEFAULT_RESIDUAL_MAX_DB,
    DEFAULT_TRACKING_RIPPLE_DB,
    CalibrationKit,
    CalibrationMethod,
    CalibrationStandard,
    apply_generic_calibration,
    build_calibration_diagnostics,
)

# venv 实测（skrf 2.1.0）：MultilineTRL 是 TRL 的别名，不单设透传成员
_SPEC_PASSTHROUGH_CLASSES = (
    "SOLT", "TwelveTerm", "EightTerm", "TRL", "NISTMultilineTRL",
    "TUGMultilineTRL", "UnknownThru", "LRM", "LRRM", "SixteenTerm",
    "MultiportSOLT",
)

_METHOD_VALUE_BY_CLASS = {
    "SOLT": "solt", "TwelveTerm": "twelve_term", "EightTerm": "eight_term",
    "TRL": "trl", "NISTMultilineTRL": "nist_multiline_trl",
    "TUGMultilineTRL": "tug_multiline_trl", "UnknownThru": "unknown_thru",
    "LRM": "lrm", "LRRM": "lrrm", "SixteenTerm": "sixteen_term",
    "MultiportSOLT": "multiport_solt",
}


# ─── 确定性合成语料（零仪器；误差盒显式给定系数，不用系统熵源）────────────────

def _errbox(wg: skrf.media.DefinedGammaZ0, s11m: float, s11p: float,
            s22m: float, s22p: float, tm: float,
            weak: bool = False) -> skrf.Network:
    nf = len(wg.frequency.f)
    s = np.zeros((nf, 2, 2), dtype=complex)
    s[:, 0, 0] = s11m * np.exp(1j * s11p)
    s[:, 1, 1] = s22m * np.exp(1j * s22p)
    s[:, 1, 0] = tm
    s[:, 0, 1] = tm
    net = skrf.Network(frequency=wg.frequency, s=s)
    if weak:
        net.s[:, 0, 0] *= 0.1
        net.s[:, 1, 1] *= 0.1
    return net


def _kit(method: CalibrationMethod, ideals: list[skrf.Network],
         types: list[str]) -> CalibrationKit:
    return CalibrationKit(
        name=f"ms1_{method.value}", method=method,
        standards=[CalibrationStandard(t, n, t)
                   for t, n in zip(types, ideals, strict=True)])


def _solt_quadrant_corpus(n_pts: int = 41,
                          method: CalibrationMethod = CalibrationMethod.SOLT):
    """SOLT 象限语料（skrf SOLTTest 同款测量模型，系数显式）。

    注入四参数：directivity −40dB（xf.s11=0.01）、source match −30.5dB
    （xf.s22=0.03）、tracking ≈ −0.18dB（tm=0.98）。
    """
    freq = skrf.Frequency(2.0, 3.0, n_pts, unit="GHz")
    wg = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0)
    xf = _errbox(wg, 0.01, 0.5, 0.03, -0.6, 0.98)
    xr = _errbox(wg, 0.012, 1.1, 0.02, 0.7, 0.98)
    yf = _errbox(wg, 0.008, -0.9, 0.025, 0.2, 0.98)
    yr = _errbox(wg, 0.014, 0.8, 0.03, -1.2, 0.98)

    def quad(ntwk: skrf.Network) -> skrf.Network:
        mf = xf ** ntwk ** yf
        mr = xr ** ntwk ** yr
        m = ntwk.copy()
        m.s[:, 0, 0] = mf.s[:, 0, 0]
        m.s[:, 1, 0] = mf.s[:, 1, 0]
        m.s[:, 0, 1] = mr.s[:, 0, 1]
        m.s[:, 1, 1] = mr.s[:, 1, 1]
        return m

    ideals = [wg.short(nports=2, name="short"),
              wg.open(nports=2, name="open"),
              wg.match(nports=2, name="load"),
              wg.thru(name="through")]
    measured = [quad(k) for k in ideals]
    dut = wg.line(35, "deg", name="dut")
    return {
        "wg": wg, "boxes": (xf, xr, yf, yr),
        "kit": _kit(method, ideals, ["short", "open", "load", "through"]),
        "measured": measured, "dut": dut, "dut_measured": quad(dut),
        "kwargs": {"method_params": {"n_thrus": 1}} if method
        is CalibrationMethod.TWELVE_TERM else {},
    }


def _terminate_corpus(freq, boxes, gf, gr, ideals):
    """terminate 测量模型公共段：measured = terminate(x**std**y, gf, gr)。"""
    from skrf.calibration import terminate as skrf_terminate

    x, y = boxes
    measured = [skrf_terminate(x ** k ** y, gf, gr) for k in ideals]
    return measured


def _trl_terminate_corpus(method: CalibrationMethod):
    freq = skrf.Frequency(2.0, 3.0, 101, unit="GHz")
    wg = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0)
    boxes = (_errbox(wg, 0.02, 0.3, 0.032, -0.5, 0.98, weak=True),
             _errbox(wg, 0.028, -0.9, 0.02, 0.2, 0.98, weak=True))
    gf = _errbox(wg, 0.10, 0.5, 0, 0, 0).s11
    gr = _errbox(wg, 0.12, -0.7, 0, 0, 0).s11
    ideals = [wg.thru(name="through"),
              wg.short(nports=2, name="reflect"),
              wg.line(90, "deg", name="line")]
    measured = _terminate_corpus(freq, boxes, gf, gr, ideals)
    dut = wg.line(25, "deg", name="dut")
    x, y = boxes
    from skrf.calibration import terminate as skrf_terminate

    return {
        "wg": wg, "boxes": boxes,
        "kit": _kit(method, ideals, ["through", "reflect", "line"]),
        "measured": measured, "dut": dut,
        "dut_measured": skrf_terminate(x ** dut ** y, gf, gr),
        "kwargs": {"switch_terms": (gf, gr)},
    }


def _unknown_thru_corpus():
    from skrf.calibration import terminate as skrf_terminate

    freq = skrf.Frequency(2.0, 3.0, 41, unit="GHz")
    wg = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0)
    boxes = (_errbox(wg, 0.02, 0.3, 0.032, -0.5, 0.98, weak=True),
             _errbox(wg, 0.028, -0.9, 0.02, 0.2, 0.98, weak=True))
    gf = _errbox(wg, 0.10, 0.5, 0, 0, 0).s11
    gr = _errbox(wg, 0.12, -0.7, 0, 0, 0).s11
    ideals = [wg.short(nports=2, name="short"),
              wg.open(nports=2, name="open"),
              wg.match(nports=2, name="load"),
              wg.thru(name="through")]
    # 未知直通=失配衰减线（ideal 只用于开方取号，相位 ±π 内已知）
    ut_thru = (wg.impedance_mismatch(50, 45) ** wg.line(20, "deg")
               ** wg.impedance_mismatch(45, 50))
    ut_thru.name = "through"
    actuals = [wg.short(nports=2), wg.open(nports=2), wg.match(nports=2),
               ut_thru]
    x, y = boxes
    measured = [skrf_terminate(x ** k ** y, gf, gr) for k in actuals]
    dut = wg.line(25, "deg", name="dut")
    return {
        "wg": wg,
        "kit": _kit(CalibrationMethod.UNKNOWN_THRU, ideals,
                    ["short", "open", "load", "through"]),
        "measured": measured, "dut": dut,
        "dut_measured": skrf_terminate(x ** dut ** y, gf, gr),
        "kwargs": {"switch_terms": (gf, gr)},
    }


def _lrm_corpus():
    from skrf.calibration import terminate as skrf_terminate
    from skrf.network import two_port_reflect

    freq = skrf.Frequency(2.0, 3.0, 41, unit="GHz")
    wg = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0)
    boxes = (_errbox(wg, 0.02, 0.3, 0.032, -0.5, 0.98, weak=True),
             _errbox(wg, 0.028, -0.9, 0.02, 0.2, 0.98, weak=True))
    gf = _errbox(wg, 0.10, 0.5, 0, 0, 0).s11
    gr = _errbox(wg, 0.12, -0.7, 0, 0, 0).s11
    ideals = [wg.line(90, "deg", name="line"),
              wg.short(nports=2, name="reflect"),
              wg.match(nports=2, name="match")]
    # 反射件实际值未知（相位与短路差 ~22°<90°，LRM 契约内）
    actual_refl = wg.load(-0.9 - 0.1j)
    actuals = [wg.line(90, "deg", name="line"),
               two_port_reflect(actual_refl, actual_refl, name="reflect"),
               wg.match(nports=2, name="match")]
    x, y = boxes
    measured = [skrf_terminate(x ** k ** y, gf, gr) for k in actuals]
    dut = wg.line(25, "deg", name="dut")
    return {
        "wg": wg,
        "kit": _kit(CalibrationMethod.LRM, ideals,
                    ["line", "reflect", "match"]),
        "measured": measured, "dut": dut,
        "dut_measured": skrf_terminate(x ** dut ** y, gf, gr),
        "kwargs": {"switch_terms": (gf, gr)},
    }


def _lrrm_corpus():
    from skrf.calibration import terminate as skrf_terminate
    from skrf.network import two_port_reflect

    freq = skrf.Frequency(2.0, 3.0, 41, unit="GHz")
    wg = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0)
    boxes = (_errbox(wg, 0.02, 0.3, 0.032, -0.5, 0.98, weak=True),
             _errbox(wg, 0.028, -0.9, 0.02, 0.2, 0.98, weak=True))
    gf = _errbox(wg, 0.10, 0.5, 0, 0, 0).s11
    gr = _errbox(wg, 0.12, -0.7, 0, 0, 0).s11
    ideals = [wg.line(90, "deg", name="line"),
              wg.short(nports=2, name="reflect"),
              wg.open(nports=2, name="reflect2"),
              wg.load(0.1, nports=2, name="match")]
    # 实际件带寄生（skrf LRRMTest 同款）：reflect1 未知反射、reflect2 幅度
    # 已知（≈1）、match=已知阻 + 未知串联电感
    s_act = wg.inductor(5e-12) ** wg.short(1)
    o_act = wg.shunt_capacitor(5e-15) ** wg.open(1)
    m_act = wg.inductor(15e-12) ** wg.load(0.1, nports=1)
    actuals = [wg.line(90, "deg", name="line"),
               two_port_reflect(s_act, s_act, name="reflect"),
               two_port_reflect(o_act, o_act, name="reflect2"),
               two_port_reflect(m_act, m_act, name="match")]
    x, y = boxes
    measured = [skrf_terminate(x ** k ** y, gf, gr) for k in actuals]
    dut = wg.line(25, "deg", name="dut")
    return {
        "wg": wg,
        "kit": _kit(CalibrationMethod.LRRM, ideals,
                    ["line", "reflect", "reflect2", "match"]),
        "measured": measured, "dut": dut,
        "dut_measured": skrf_terminate(x ** dut ** y, gf, gr),
        "kwargs": {"switch_terms": (gf, gr)},
    }


def _multiline_media(n_pts: int = 61):
    """多线 TRL 语料公共段：er_eff=4−0.02j 媒质 + 温和弱失配误差盒。"""
    freq = skrf.Frequency(1.0, 10.0, n_pts, unit="GHz")
    wg = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0)
    er = 4.0 - 0.02j
    med = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0,
                                    gamma=wg.gamma * np.sqrt(er))
    boxes = (_errbox(wg, 0.02, 0.3, 0.032, -0.5, 0.98, weak=True),
             _errbox(wg, 0.028, -0.9, 0.02, 0.2, 0.98, weak=True))
    gf = _errbox(wg, 0.10, 0.5, 0, 0, 0).s11
    gr = _errbox(wg, 0.12, -0.7, 0, 0, 0).s11
    return freq, wg, med, er, boxes, gf, gr


def _nist_multiline_corpus():
    from skrf.network import two_port_reflect

    freq, wg, med, er, boxes, gf, gr = _multiline_media()
    l1, l2 = 1e-3, 5e-3
    ideals = [med.thru(name="through"),
              two_port_reflect(med.short(), med.short(), name="reflect"),
              med.line(l1, "m", name="line"),
              med.line(l2, "m", name="line2")]
    measured = _terminate_corpus(freq, boxes, gf, gr, ideals)
    from skrf.calibration import terminate as skrf_terminate

    x, y = boxes
    dut = med.line(35, "deg", name="dut")
    return {
        "wg": wg, "er": er, "lens": (l1, l2), "boxes": boxes,
        "gf": gf, "gr": gr,
        "kit": _kit(CalibrationMethod.NIST_MULTILINE_TRL, ideals,
                    ["through", "reflect", "line", "line2"]),
        "measured": measured, "dut": dut,
        "dut_measured": skrf_terminate(x ** dut ** y, gf, gr),
        "kwargs": {"switch_terms": (gf, gr),
                   "method_params": {"Grefls": [-1], "l": [0, l1, l2],
                                     "er_est": er, "z0_ref": 50}},
    }


def _tug_multiline_corpus():
    from skrf.network import two_port_reflect

    freq, wg, med, er, boxes, gf, gr = _multiline_media()
    l1, l2 = 1e-3, 5e-3
    ideals = [med.thru(name="through"),
              med.line(l1, "m", name="line"),
              med.line(l2, "m", name="line2"),
              two_port_reflect(med.short(), med.short(), name="reflect")]
    measured = _terminate_corpus(freq, boxes, gf, gr, ideals[:3])
    from skrf.calibration import terminate as skrf_terminate

    x, y = boxes
    dut = med.line(35, "deg", name="dut")
    return {
        "wg": wg, "er": er,
        "kit": _kit(CalibrationMethod.TUG_MULTILINE_TRL, ideals,
                    ["through", "line", "line2", "reflect"]),
        "measured": measured, "dut": dut,
        "dut_measured": skrf_terminate(x ** dut ** y, gf, gr),
        "kwargs": {"switch_terms": (gf, gr),
                   "method_params": {"line_lengths": [0, l1, l2],
                                     "er_est": er, "reflect_est": -1}},
    }


def _sixteen_term_corpus():
    from skrf.calibration import terminate as skrf_terminate
    from skrf.network import connect, two_port_reflect

    rng = np.random.default_rng(42)
    freq = skrf.Frequency(2.0, 3.0, 21, unit="GHz")
    wg = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0)
    n = len(freq.f)
    # 4-port 误差网络（VNA0, DUT0, DUT1, VNA1 拓扑；skrf SixteenTermTest 同款）
    z = 0.02 * (rng.standard_normal((n, 4, 4)) + 1j * rng.standard_normal((n, 4, 4)))
    znet = skrf.Network(frequency=freq, s=z)
    gf = skrf.Network(frequency=freq,
                      s=0.1 * (rng.standard_normal(n) + 1j * rng.standard_normal(n)))
    gr = skrf.Network(frequency=freq,
                      s=0.1 * (rng.standard_normal(n) + 1j * rng.standard_normal(n)))

    def measure(ntwk: skrf.Network) -> skrf.Network:
        out = skrf_terminate(connect(znet, 1, ntwk, 0, num=2), gf, gr)
        out.name = ntwk.name
        return out

    o = wg.open(1, name="open")
    s = wg.short(1, name="short")
    m = wg.match(1, name="load")
    ideals = [wg.thru(name="thru"),
              two_port_reflect(o, m, name="om"),
              two_port_reflect(m, o, name="mo"),
              two_port_reflect(o, o, name="oo"),
              two_port_reflect(s, s, name="ss")]
    measured = [measure(k) for k in ideals]
    dut = wg.line(30, "deg", name="dut")
    return {
        "wg": wg,
        "kit": _kit(CalibrationMethod.SIXTEEN_TERM, ideals,
                    ["thru", "om", "mo", "oo", "ss"]),
        "measured": measured, "dut": dut, "dut_measured": measure(dut),
        "kwargs": {"switch_terms": (gf, gr)},
    }


def _multiport_corpus():
    from skrf.calibration import terminate_nport
    from skrf.network import connect, twoport_to_nport

    rng = np.random.default_rng(42)
    freq = skrf.Frequency(2.0, 3.0, 21, unit="GHz")
    wg = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0)
    n = len(freq.f)
    nports = 3
    gf = skrf.Network(frequency=freq,
                      s=0.1 * (rng.standard_normal(n) + 1j * rng.standard_normal(n)))
    zbig = 0.02 * (rng.standard_normal((n, 2 * nports, 2 * nports))
                   + 1j * rng.standard_normal((n, 2 * nports, 2 * nports)))

    def port_type(i: int) -> str:
        return "VNA" if i < nports else "DUT"

    def port_number(i: int) -> int:
        return i if i < nports else i - nports

    for i in range(2 * nports):
        for j in range(i + 1, 2 * nports):
            if port_type(i) == port_type(j) or port_number(i) != port_number(j):
                zbig[:, i, j] = 0
                zbig[:, j, i] = 0
    znet = skrf.Network(frequency=freq, s=zbig)
    iso = 0.005 * (rng.standard_normal((n, nports, nports))
                   + 1j * rng.standard_normal((n, nports, nports)))
    for i in range(nports):
        iso[:, i, i] = 0
    iso_net = skrf.Network(frequency=freq, s=iso)

    def measure(ntwk: skrf.Network) -> skrf.Network:
        out = terminate_nport(connect(znet, nports, ntwk, 0, num=nports),
                              [gf, gf, gf])
        out = out + iso_net
        out.name = ntwk.name
        return out

    thru2 = (wg.impedance_mismatch(50, 45) ** wg.line(20, "deg")
             ** wg.impedance_mismatch(45, 50))
    types = ["through1", "through2", "open", "short", "load"]
    ideals = [twoport_to_nport(thru2, 0, i, nports) for i in (1, 2)]
    ideals += [wg.open(nports=nports, name="open"),
               wg.short(nports=nports, name="short"),
               wg.match(nports=nports, name="load")]
    for nd, nm in zip(ideals, types, strict=True):
        nd.name = nm
    measured = [measure(k) for k in ideals]
    dut = skrf.Network(frequency=freq,
                       s=0.1 * (rng.standard_normal((n, nports, nports))
                                + 1j * rng.standard_normal((n, nports, nports))),
                       name="dut3p")
    return {
        "wg": wg,
        "kit": _kit(CalibrationMethod.MULTIPORT_SOLT, ideals, types),
        "measured": measured, "dut": dut, "dut_measured": measure(dut),
        "kwargs": {"method_params": {"isolation": measured[-1]}},
    }


_PASSTHROUGH_CORPUS = {
    "solt": _solt_quadrant_corpus,
    "twelve_term": lambda: _solt_quadrant_corpus(
        method=CalibrationMethod.TWELVE_TERM),
    "trl": lambda: _trl_terminate_corpus(CalibrationMethod.TRL),
    "eight_term": lambda: _trl_terminate_corpus(CalibrationMethod.EIGHT_TERM),
    "unknown_thru": _unknown_thru_corpus,
    "lrm": _lrm_corpus,
    "lrrm": _lrrm_corpus,
    "nist_multiline_trl": _nist_multiline_corpus,
    "tug_multiline_trl": _tug_multiline_corpus,
    "sixteen_term": _sixteen_term_corpus,
    "multiport_solt": _multiport_corpus,
}


# ─── ① 透传类实测存在性 ───────────────────────────────────────────────────────

class TestPassthroughClassAvailability:
    """规格清单 vs venv 实测（skrf 2.1.0）：11 类全存在，MultilineTRL=TRL 别名。"""

    def test_all_spec_classes_exist(self):
        for name in _SPEC_PASSTHROUGH_CLASSES:
            assert hasattr(skrf.calibration, name), name

    def test_multiline_trl_is_trl_alias(self):
        assert skrf.calibration.MultilineTRL is skrf.calibration.TRL

    def test_enum_covers_all_passthrough_classes(self):
        for name in _SPEC_PASSTHROUGH_CLASSES:
            assert _METHOD_VALUE_BY_CLASS[name] in {m.value for m in CalibrationMethod}


# ─── ② 每透传类合成语料冒烟（零仪器）──────────────────────────────────────────

@pytest.mark.parametrize("method_value", sorted(_PASSTHROUGH_CORPUS))
def test_passthrough_smoke_embed_calibrate_recover(method_value):
    """规格 D-2 冒烟：embed→校准→DUT 回收 max|ΔS|≤1e-9（合成语料零仪器）。"""
    corpus = _PASSTHROUGH_CORPUS[method_value]()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = apply_generic_calibration(
            corpus["measured"], corpus["kit"], dut=corpus["dut_measured"],
            **corpus["kwargs"])
    assert result.is_calibrated is True
    assert result.method.value == method_value
    assert result.skrf_cal is not None
    max_ds = float(np.max(np.abs(result.calibrated_network.s - corpus["dut"].s)))
    assert max_ds <= 1e-9, (method_value, max_ds)


def test_nist_missing_required_param_raises():
    """NIST 缺 Grefls/l → 显式 ValueError（参数面契约，不静默）。"""
    corpus = _nist_multiline_corpus()
    mp = dict(corpus["kwargs"]["method_params"])
    mp.pop("Grefls")
    with pytest.raises(ValueError, match="Grefls"):
        apply_generic_calibration(corpus["measured"], corpus["kit"],
                                  switch_terms=corpus["kwargs"]["switch_terms"],
                                  method_params=mp)


def test_tug_missing_line_lengths_raises():
    """TUG 缺 line_lengths → 显式 ValueError。"""
    corpus = _tug_multiline_corpus()
    with pytest.raises(ValueError, match="line_lengths"):
        apply_generic_calibration(corpus["measured"], corpus["kit"],
                                  switch_terms=corpus["kwargs"]["switch_terms"])


def test_nist_count_mismatch_raises():
    """NIST 标准件数与 Grefls/l 参数面不齐 → 显式 ValueError。"""
    corpus = _nist_multiline_corpus()
    mp = dict(corpus["kwargs"]["method_params"])
    mp["l"] = [0.0, 1e-3]
    with pytest.raises(ValueError, match="不齐"):
        apply_generic_calibration(corpus["measured"], corpus["kit"],
                                  switch_terms=corpus["kwargs"]["switch_terms"],
                                  method_params=mp)


def test_none_method_rejected():
    corpus = _solt_quadrant_corpus()
    kit = _kit(CalibrationMethod.NONE, corpus["measured"][:1], ["through"])
    with pytest.raises(ValueError, match="NONE"):
        apply_generic_calibration(corpus["measured"][:1], kit)


# ─── ③ 验收锚：合成已知误差盒→四参数各自回收 ≤−60dB ──────────────────────────

class TestErrorBoxRecoveryAnchor:
    """规格原文锚：directivity −40dB 等已知误差盒 mock 语料→回收 |Δ|≤−60dB。"""

    @classmethod
    def _calibrated(cls):
        corpus = _solt_quadrant_corpus()
        result = apply_generic_calibration(
            corpus["measured"], corpus["kit"], dut=corpus["dut_measured"])
        assert result.is_calibrated is True
        return corpus, result

    @staticmethod
    def _dbmax(a, b) -> float:
        d = float(np.max(np.abs(np.asarray(a) - np.asarray(b))))
        return 20.0 * np.log10(d + 1e-300)

    def test_dut_recovery_below_minus60db(self):
        corpus, result = self._calibrated()
        db = self._dbmax(result.calibrated_network.s, corpus["dut"].s)
        assert db <= -60.0, db

    def test_four_error_parameters_recovered_per_direction(self):
        """四参数×正反向逐系数回收（象限身份由 scratch probe 实测钉定）。"""
        corpus, result = self._calibrated()
        xf, xr, yf, yr = corpus["boxes"]
        c12 = result.skrf_cal.coefs_12term
        identities = {
            "forward directivity": xf.s[:, 0, 0],
            "forward source match": xf.s[:, 1, 1],
            "forward reflection tracking": xf.s[:, 1, 0] * xf.s[:, 0, 1],
            "forward load match": yf.s[:, 0, 0],
            "forward transmission tracking": xf.s[:, 1, 0] * yf.s[:, 1, 0],
            "reverse directivity": yr.s[:, 1, 1],
            "reverse source match": yr.s[:, 0, 0],
            "reverse reflection tracking": yr.s[:, 0, 1] * yr.s[:, 1, 0],
            "reverse load match": xr.s[:, 1, 1],
            "reverse transmission tracking": xr.s[:, 0, 1] * yr.s[:, 0, 1],
        }
        for key, expected in identities.items():
            db = self._dbmax(c12[key], expected)
            assert db <= -60.0, (key, db)

    def test_injected_directivity_is_minus40db(self):
        """注入面自检：directivity 确为 −40dB（锚数字的来源）。"""
        corpus, _ = self._calibrated()
        xf = corpus["boxes"][0]
        assert 20.0 * np.log10(float(np.abs(xf.s[0, 0, 0]))) == pytest.approx(-40.0)


# ─── ④ 残差诊断 schema ───────────────────────────────────────────────────────

_DIAGNOSE_KEYS = {"ok", "method", "freq_ghz", "residual_networks",
                  "residual_semantics", "error_terms", "error_terms_available",
                  "skrf_error_estimates", "thresholds", "verdict"}


class TestCalibrationDiagnosticsSchema:

    @classmethod
    def _diag(cls, **kw):
        corpus = _solt_quadrant_corpus()
        result = apply_generic_calibration(
            corpus["measured"], corpus["kit"], dut=corpus["dut_measured"],
            **corpus["kwargs"])
        return build_calibration_diagnostics(result, **kw)

    def test_schema_keys_and_thresholds(self):
        diag = self._diag()
        assert set(diag) == _DIAGNOSE_KEYS
        assert diag["ok"] is True
        assert diag["method"] == "solt"
        assert diag["thresholds"] == {
            "residual_max_db": DEFAULT_RESIDUAL_MAX_DB,
            "tracking_ripple_db": DEFAULT_TRACKING_RIPPLE_DB,
            "db_floor_db": -300.0,
        }
        assert len(diag["residual_networks"]) == 4
        for entry in diag["residual_networks"]:
            assert set(entry) == {"standard", "db_curve"}
            assert len(entry["db_curve"]) == len(diag["freq_ghz"])

    def test_error_terms_four_parameters_forward_reverse(self):
        """规格 schema：四参数正反向分列 + 12 项透射跟踪附加键。"""
        diag = self._diag()
        et = diag["error_terms"]
        for key in ("directivity_db", "source_match_db", "load_match_db",
                    "tracking_db", "transmission_tracking_db"):
            assert key in et, key
            assert set(et[key]) == {"forward", "reverse"}
        n = len(diag["freq_ghz"])
        for curve in et["directivity_db"].values():
            assert len(curve) == n
        # 注入锚：directivity −40dB 曲线逐点等于注入值
        for v in et["directivity_db"]["forward"]:
            assert v == pytest.approx(-40.0, abs=1e-6)

    def test_verdict_pass_on_clean_corpus(self):
        diag = self._diag()
        verdict = diag["verdict"]
        assert verdict["status"] == "pass"
        assert verdict["residual_pass"] is True
        assert verdict["residual_max_observed_db"] <= -40.0
        assert verdict["tracking_pass"] is True
        assert all(v <= 1.0 for v in verdict["tracking_ripple_observed_db"].values())
        assert verdict["failures"] == []
        assert diag["residual_semantics"] == "self_consistency"

    def test_json_safe_round_trip(self):
        """JSON 进出铁律：全报告可 dumps（地板钳位后无 ±inf/NaN）。"""
        diag = self._diag()
        text = json.dumps(diag, ensure_ascii=False, allow_nan=False)
        assert "Infinity" not in text and "NaN" not in text

    def test_ideal_corpus_clamps_zero_coefficients_to_floor(self):
        """理想恒等校准（系数=0）→ dB 曲线钳位地板，不产 ±inf。"""
        freq = skrf.Frequency(2.0, 3.0, 21, unit="GHz")
        wg = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0)
        ideals = [wg.short(nports=2, name="short"),
                  wg.open(nports=2, name="open"),
                  wg.match(nports=2, name="load"),
                  wg.thru(name="through")]
        kit = _kit(CalibrationMethod.SOLT, ideals,
                   ["short", "open", "load", "through"])
        result = apply_generic_calibration([k.copy() for k in ideals], kit)
        diag = build_calibration_diagnostics(result)
        assert diag["ok"] is True
        assert diag["verdict"]["status"] == "pass"
        fwd = diag["error_terms"]["directivity_db"]["forward"]
        assert all(v == pytest.approx(-300.0) for v in fwd)

    def test_threshold_forced_fail_reports_failures(self):
        diag = self._diag(residual_max_db=-400.0)
        assert diag["verdict"]["status"] == "fail"
        assert diag["verdict"]["residual_pass"] is False
        assert diag["verdict"]["failures"]
        assert "门限" in diag["verdict"]["failures"][0]

    def test_noisy_corpus_fails_residual_gate(self):
        """实测面注入噪声 → 残差超 −40dB 门 → verdict=fail（门可失败）。"""
        corpus = _solt_quadrant_corpus()
        rng = np.random.default_rng(7)
        noisy = [k.copy() for k in corpus["measured"]]
        for net in noisy:
            net.s = net.s + 0.03 * (rng.standard_normal(net.s.shape)
                                    + 1j * rng.standard_normal(net.s.shape))
        result = apply_generic_calibration(noisy, corpus["kit"])
        diag = build_calibration_diagnostics(result)
        assert diag["verdict"]["status"] == "fail"
        assert diag["verdict"]["residual_pass"] is False

    def test_uncalibrated_result_reports_reason(self):
        from rfauto.measurement.calibration import apply_calibration
        from rfauto.measurement.import_data import MeasurementData

        freq = skrf.Frequency(2.0, 3.0, 5, unit="GHz")
        net = skrf.Network(frequency=freq,
                           s=np.zeros((5, 2, 2), dtype=complex))
        legacy = MeasurementData(network=net, metadata=None,
                                 source_file="mock", n_ports=2,
                                 freq_range_ghz=(2.0, 3.0))
        res = apply_calibration(legacy, None)
        diag = build_calibration_diagnostics(res)
        assert diag["ok"] is False
        assert "reason" in diag

    def test_multiline_residual_semantics_degrades_honestly(self):
        """NIST 内部 ideals:=measured → 残差=修正量语义，residual 门不判。"""
        corpus = _nist_multiline_corpus()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = apply_generic_calibration(
                corpus["measured"], corpus["kit"], dut=corpus["dut_measured"],
                **corpus["kwargs"])
        diag = build_calibration_diagnostics(result)
        assert diag["residual_semantics"] == "correction_vs_measured"
        assert diag["verdict"]["residual_pass"] is None
        assert diag["verdict"]["status"] in ("pass", "fail", "unknown")
        assert diag["error_terms_available"] is True


# ─── ⑤ catalog schema v2（offset 合成 DefinedGammaZ0 非理想件）───────────────

def _write_std_fixture(tmp_path: Path) -> dict[str, skrf.Network]:
    freq = skrf.Frequency(2.0, 3.0, 21, unit="GHz")
    wg = skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0)
    nets = {
        "short": wg.short(1, name="short"),
        "load": wg.match(1, name="load"),
        "thru": wg.thru(name="thru"),
    }
    for name, net in nets.items():
        ext = "s1p" if net.nports == 1 else "s2p"
        net.write_touchstone(str(tmp_path / f"std_{name}.{ext}"))
    return nets


def _write_catalog(tmp_path: Path, entry: dict) -> None:
    (tmp_path / "catalog.yaml").write_text(
        yaml.safe_dump({"calkits": entry}), encoding="utf-8")


class TestCatalogSchemaV2:
    """standards 值升 {file, offset_*}（schema_version:2），v1 零改动兼容。"""

    def test_v1_string_form_loads_byte_identical(self, tmp_path):
        from rfauto.measurement.calibration import load_calkit

        nets = _write_std_fixture(tmp_path)
        _write_catalog(tmp_path, {"v1_kit": {
            "description": "v1 形态", "method": "solt",
            "standards": {"short": "std_short.s1p",
                          "load": "std_load.s1p",
                          "thru": "std_thru.s2p"}}})
        kit = load_calkit("v1_kit", directory=tmp_path)
        assert kit.method == CalibrationMethod.SOLT
        assert kit.metadata["schema_version"] == 1
        by_type = {s.standard_type: s.network for s in kit.standards}
        assert np.array_equal(by_type["short"].s, nets["short"].s)
        assert np.array_equal(by_type["through"].s, nets["thru"].s)

    def test_v2_offset_delay_shifts_phase_exactly(self, tmp_path):
        """offset_delay_ps=10 → Γ 相位移动 −2·2πf·τ（er_eff=1 偏置线口径）。"""
        from rfauto.measurement.calibration import load_calkit

        nets = _write_std_fixture(tmp_path)
        _write_catalog(tmp_path, {"v2_kit": {
            "schema_version": 2, "method": "solt",
            "standards": {"short": {
                "file": "std_short.s1p", "offset_delay_ps": 10.0}}}})
        kit = load_calkit("v2_kit", directory=tmp_path)
        assert kit.metadata["schema_version"] == 2
        assert kit.metadata["offsets"]["short"] == {"offset_delay_ps": 10.0}
        phys = kit.standards[0].network
        tau = 10.0e-12
        expected = np.angle(nets["short"].s[:, 0, 0]) \
            - 2.0 * 2.0 * np.pi * np.asarray(nets["short"].f) * tau
        got = np.angle(phys.s[:, 0, 0])
        assert np.allclose((got - expected + np.pi) % (2 * np.pi) - np.pi,
                           0.0, atol=1e-9)
        # 无损偏置线不改变幅度
        assert np.allclose(np.abs(phys.s[:, 0, 0]), 1.0)

    def test_v2_offset_loss_attenuates_two_way(self, tmp_path):
        """offset_loss_db_per_mm → 双程损耗 = 2×(dB/mm·mm)，逐点可解析预言。"""
        from rfauto.measurement.calibration import load_calkit

        nets = _write_std_fixture(tmp_path)
        _write_catalog(tmp_path, {"v2_kit": {
            "schema_version": 2, "method": "solt",
            "standards": {"short": {
                "file": "std_short.s1p", "offset_delay_ps": 100.0,
                "offset_loss_db_per_mm": 0.01}}}})
        kit = load_calkit("v2_kit", directory=tmp_path)
        phys = kit.standards[0].network
        c0 = 299792458.0
        length_mm = c0 * 100.0e-12 * 1e3
        expected_drop_db = 2.0 * 0.01 * length_mm
        got_db = (20.0 * np.log10(np.abs(phys.s[:, 0, 0]))
                  - 20.0 * np.log10(np.abs(nets["short"].s[:, 0, 0])))
        assert np.allclose(got_db, -expected_drop_db, atol=0.01)

    def test_v2_offset_z0_creates_mismatch_ripple(self, tmp_path):
        """offset_z0_ohm 失配：有耗偏置线 + 短路 → |Γ|<1 且逐频起伏。

        （无损线+短路端 |Γ|≡1——纯电抗负载对任意参考阻抗都是全反射，
        纹波必须经损耗进入。）
        """
        from rfauto.measurement.calibration import load_calkit

        _write_std_fixture(tmp_path)
        _write_catalog(tmp_path, {"v2_kit": {
            "schema_version": 2, "method": "solt",
            "standards": {"short": {
                "file": "std_short.s1p", "offset_delay_ps": 200.0,
                "offset_loss_db_per_mm": 0.02,
                "offset_z0_ohm": 45.0}}}})
        kit = load_calkit("v2_kit", directory=tmp_path)
        mag = np.abs(kit.standards[0].network.s[:, 0, 0])
        assert mag.max() - mag.min() > 0.005   # 失配+损耗干涉纹波
        assert mag.max() <= 1.0 + 1e-9         # 无源

    def test_v2_mixed_v1_values_per_standard(self, tmp_path):
        """v2 档内 v1 字符串形态逐标准件合法（向后兼容的最小粒度）。"""
        from rfauto.measurement.calibration import load_calkit

        nets = _write_std_fixture(tmp_path)
        _write_catalog(tmp_path, {"v2_kit": {
            "schema_version": 2, "method": "solt",
            "standards": {"short": {"file": "std_short.s1p",
                                    "offset_delay_ps": 5.0},
                          "load": "std_load.s1p",
                          "thru": "std_thru.s2p"}}})
        kit = load_calkit("v2_kit", directory=tmp_path)
        by_type = {s.standard_type: s.network for s in kit.standards}
        # v2 dict 形态：偏置线改写相位（匹配负载 Γ=0 除外，short 可辨）
        assert not np.array_equal(by_type["short"].s, nets["short"].s)
        # v1 字符串形态：逐字节原样
        assert np.array_equal(by_type["load"].s, nets["load"].s)
        assert np.array_equal(by_type["through"].s, nets["thru"].s)

    def test_v2_missing_file_key_raises(self, tmp_path):
        from rfauto.measurement.calibration import load_calkit

        _write_std_fixture(tmp_path)
        _write_catalog(tmp_path, {"bad": {
            "schema_version": 2, "method": "solt",
            "standards": {"short": {"offset_delay_ps": 1.0}}}})
        with pytest.raises(KeyError, match="file"):
            load_calkit("bad", directory=tmp_path)

    def test_real_knowledge_catalog_still_loads(self):
        """真实 knowledge/calkits（v1 形态）经新 loader 零改动加载。"""
        from rfauto.measurement.calibration import load_calkit

        kit = load_calkit("wl_2g5_solt_smoke")
        assert kit.method == CalibrationMethod.SOLT
        assert kit.metadata["schema_version"] == 1
        assert len(kit.standards) == 4


# ─── ⑥ vna_service calibration_diagnostics.json 挂点 ─────────────────────────

class TestVnaServiceDiagnostics:

    @staticmethod
    def _cal_result():
        corpus = _solt_quadrant_corpus()
        return apply_generic_calibration(
            corpus["measured"], corpus["kit"], dut=corpus["dut_measured"])

    def test_write_calibration_diagnostics(self, tmp_path):
        from rfauto.service.vna_service import vna_write_calibration_diagnostics

        out = vna_write_calibration_diagnostics(self._cal_result(), tmp_path)
        assert out["ok"] is True
        path = Path(out["path"])
        assert path.name == "calibration_diagnostics.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == "1.0"
        assert payload["verdict"]["status"] == "pass"

    def test_write_accepts_preadjusted_dict_and_thresholds(self, tmp_path):
        from rfauto.service.vna_service import vna_write_calibration_diagnostics

        out = vna_write_calibration_diagnostics(
            {"ok": True, "method": "solt", "verdict": {"status": "pass"}},
            tmp_path)
        assert out["ok"] is True
        payload = json.loads(
            Path(out["path"]).read_text(encoding="utf-8"))
        assert payload["method"] == "solt"

    def test_write_bad_input_reports_error(self, tmp_path):
        from rfauto.service.vna_service import vna_write_calibration_diagnostics

        out = vna_write_calibration_diagnostics(object(), tmp_path)
        assert out["ok"] is False
        assert out["errors"]

    def test_run_vna_measure_writes_diagnostics_product(
            self, tmp_path, monkeypatch):
        """run_vna_measure(cal_result=…) → 产物落 run 根 + artifacts 登记。"""
        pytest.importorskip("pyvisa")
        monkeypatch.chdir(tmp_path)
        from rfauto.service.vna_service import run_vna_measure

        sim_yaml = (Path(__file__).resolve().parents[1]
                    / "fixtures" / "vna_sim.yaml")
        out = run_vna_measure(
            address="TCPIP0::sim-vna::10001::INSTR", model="librevna",
            freq_range_ghz=(1.0, 3.0), n_points=5, ifbw_hz=1000.0,
            calkit_id="wl_2g5_solt_smoke",
            visa_library=f"{sim_yaml}@sim",
            params={"model": "mline"},
            runs_dir=tmp_path / "runs",
            cal_result=self._cal_result())
        assert out["ok"] is True, out.get("errors")
        run_dir = Path(out["run_dir"])
        diag_path = run_dir / "calibration_diagnostics.json"
        assert diag_path.exists()
        assert out["artifacts"]["calibration_diagnostics"] \
            == "calibration_diagnostics.json"
        payload = json.loads(diag_path.read_text(encoding="utf-8"))
        assert payload["verdict"]["status"] == "pass"
        vm = json.loads((run_dir / "vna_measure.json").read_text(
            encoding="utf-8"))
        assert vm["calibration"]["diagnostics"] == {
            "file": "calibration_diagnostics.json", "method": "solt",
            "verdict": "pass"}

    def test_run_vna_measure_without_cal_result_keeps_legacy_shape(
            self, tmp_path, monkeypatch):
        """cal_result 缺省 None：artifacts 登记为 None，零新产物（向后兼容）。"""
        pytest.importorskip("pyvisa")
        monkeypatch.chdir(tmp_path)
        from rfauto.service.vna_service import run_vna_measure

        sim_yaml = (Path(__file__).resolve().parents[1]
                    / "fixtures" / "vna_sim.yaml")
        out = run_vna_measure(
            address="TCPIP0::sim-vna::10001::INSTR", model="librevna",
            freq_range_ghz=(1.0, 3.0), n_points=5, ifbw_hz=1000.0,
            calkit_id="wl_2g5_solt_smoke",
            visa_library=f"{sim_yaml}@sim",
            runs_dir=tmp_path / "runs")
        assert out["ok"] is True, out.get("errors")
        assert out["artifacts"]["calibration_diagnostics"] is None
        assert not (Path(out["run_dir"])
                    / "calibration_diagnostics.json").exists()
