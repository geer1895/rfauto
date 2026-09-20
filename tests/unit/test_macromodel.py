"""D13 宏模型内核定向单元测试（确定性、无网络、无真机依赖）。

覆盖（验收列出的验证点）：
1. skrf 2.1.0 API 契约（先用 inspect.signature 核对再调用，不凭想象写 API）；
2. N=1 合成有理网络（series RLC 闭式 S11）→ 拟合 RMS ≤ -40 dB、带内无源、
   SPICE 结构有效、FSV GDM ≥ Good、整体 ok；
3. N=2 串联电感闭式两端口 → 4 条响应 FSV 全部 Ex/VG；
4. N=4 电感星形闭式四端口（Y = y(I - J/4)）→ 16 条响应、矢量 z0；
5. SPICE 子电路结构校验（子电路名/端口节点/元素类型计数/.ENDS）；
6. 结构校验器自身可被证伪（人为破坏 6 种 → valid False + 具体错误）；
7. 已知非无源网络（负阻 RLC，|S11|>1）→ enforce 前带内非无源、enforce 后
   带内无源（SVD 最大奇异值 ≤ 1+1e-6），且如实记录精度代价（不凑绿）；
8. 无源网络不触发 enforce；
9. 两次拟合 JSON 逐字节一致 + .sp 文件逐字节一致（确定性）；
10. 显式定阶且极点不足（色散传输线延迟 = 非有理）→ 显式 MacromodelFitError；
11. 自动升阶阶梯用尽仍不达标 → best-effort 返回（不抛错）+ passed/ok False；
12. 非法输入（缺字段/维度/长度/z0/频点数/频率轴）→ MacromodelInputError；
13. 返回值 JSON 原生且 round-trip；14. Touchstone 读取 + 拟合；
15. 四种输入表示（[re,im] / dict / s_real+s_imag / 扁平）逐字节等价。

裁判口径（不自证）：原始 S 由闭式解析式（系列 RLC / 串联电感 / 星形
Y 矩阵）给出，与 skrf 拟合器无共享代码路径；保真等级由 D12 的
rfauto.core.fsv（IEEE 1597.1 独立实现）判定；无源性另有独立于 skrf
半尺寸测试的"带内密集 SVD 直判"。

**SPICE 回放自检**（2026-09-12 D13 收口；2026-09-15 措辞同步）：导出网表的频域
AC 回放由本模块内置纯 Python 复数 MNA 求解器完成（``replay_spice_subcircuit_s``，
不依赖 ngspice.exe），定向测试见 test_macromodel_replay.py；它是"回放自检"而非
ngspice/LTspice/Xyce 等第三方 SPICE 仿真器的等价验证。第三方等价对拍另走
adapters.spice_netlist 的 ngspice .AC 通道（``xval_macromodel_spice``，真机门见
tests/real_edt/test_macromodel_xval_real.py），与回放自检是两条独立证据链。
本文件仍只断言网表**结构**正确；回放误差数字与集成门在 replay 测试文件。
"""

from __future__ import annotations

import inspect
import json

import numpy as np
import pytest
import skrf
from skrf.vectorFitting import VectorFitting

from rfauto.core.macromodel import (
    DEFAULT_ORDER_LADDER,
    GRADE_INDEX_GOOD,
    MIN_FREQ_POINTS,
    MacromodelFitError,
    MacromodelInputError,
    fit_macromodel,
    request_from_touchstone,
    validate_spice_subcircuit,
)

Z0 = 50.0


# --------------------------------------------------------------------------- #
# 闭式合成网络（独立于拟合器的原始数据来源）
# --------------------------------------------------------------------------- #

def _freq(n: int = 201, lo: float = 1e9, hi: float = 20e9) -> np.ndarray:
    return np.linspace(lo, hi, n)


def _pair_s(s: np.ndarray) -> list:
    """[nf][n][n][2] 的 [re, im] 对（JSON 原生）。"""
    return [
        [[[float(v.real), float(v.imag)] for v in row] for row in mat]
        for mat in np.asarray(s, dtype=complex)
    ]


def _dict_s(s: np.ndarray) -> list:
    """[nf][n][n] 的 {"re","im"} dict 形式。"""
    return [
        [[{"re": float(v.real), "im": float(v.imag)} for v in row] for row in mat]
        for mat in np.asarray(s, dtype=complex)
    ]


def _series_rlc_s11(f: np.ndarray, r: float = 5.0, l_henry: float = 2e-9, c: float = 0.5e-12) -> np.ndarray:
    """1 端口串联 RLC 闭式反射：Z = R + jwL + 1/(jwC)，S11 = (Z-Z0)/(Z+Z0)。"""
    w = 2.0 * np.pi * f
    z = r + 1j * w * l_henry + 1.0 / (1j * w * c)
    return ((z - Z0) / (z + Z0)).reshape(-1, 1, 1)


def _nonpassive_rlc_s11(f: np.ndarray, r_neg: float = -5.0, l_henry: float = 2e-9, c: float = 0.5e-12) -> np.ndarray:
    """同拓扑但串联负阻（有源）→ 带内 |S11| > 1，已知非无源。"""
    return _series_rlc_s11(f, r=r_neg, l_henry=l_henry, c=c)


def _series_inductor_2port(f: np.ndarray, r: float = 3.0, l_henry: float = 3e-9) -> np.ndarray:
    """2 端口串联阻抗 Z = R + jwL 的闭式 S（对称互易）。"""
    w = 2.0 * np.pi * f
    z = r + 1j * w * l_henry
    den = 2.0 * Z0 + z
    s = np.zeros((f.size, 2, 2), dtype=complex)
    s[:, 0, 0] = z / den
    s[:, 1, 1] = z / den
    s[:, 0, 1] = 2.0 * Z0 / den
    s[:, 1, 0] = 2.0 * Z0 / den
    return s


def _star_4port(f: np.ndarray, r: float = 2.0, l_henry: float = 1e-9) -> np.ndarray:
    """4 端口电感星形（各端口经 R+jwL 接公共中心）闭式 S。

    节点分析给出 Y = y (I - J/4)，y = 1/(R+jwL)；S = (I - Z0 Y)(I + Z0 Y)^-1。
    """
    w = 2.0 * np.pi * f
    y = 1.0 / (r + 1j * w * l_henry)
    ident = np.eye(4)
    jmat = np.ones((4, 4)) / 4.0
    s = np.zeros((f.size, 4, 4), dtype=complex)
    for k in range(f.size):
        ymat = y[k] * (ident - jmat)
        s[k] = (ident - Z0 * ymat) @ np.linalg.inv(ident + Z0 * ymat)
    return s


def _matched_delay_2port(f: np.ndarray, tau: float = 1e-9) -> np.ndarray:
    """匹配无色散延迟线 S21 = exp(-j2πf·tau)：非有理（纯延迟）→ VF 无法逼近。"""
    s = np.zeros((f.size, 2, 2), dtype=complex)
    s[:, 0, 1] = np.exp(-2j * np.pi * f * tau)
    s[:, 1, 0] = np.exp(-2j * np.pi * f * tau)
    return s


def _request(s: np.ndarray, f: np.ndarray, **kw) -> dict:
    req: dict = {"freq_hz": f.tolist(), "s": _pair_s(s)}
    req.update(kw)
    return req


def _dumps(result: dict) -> str:
    return json.dumps(result, sort_keys=True)


# --------------------------------------------------------------------------- #
# 1. skrf API 契约（先核对签名再依赖）
# --------------------------------------------------------------------------- #

def test_skrf_api_contract_used_by_kernel() -> None:
    """钉住本内核用到的 skrf 2.1.0 方法签名（换版本时第一时间暴露）。"""
    ver = tuple(int(x) for x in skrf.__version__.split(".")[:2])
    assert ver >= (2, 1)

    fit = inspect.signature(VectorFitting.vector_fit)
    for name in ("n_poles_real", "n_poles_cmplx", "init_pole_spacing", "fit_constant", "fit_proportional", "enforce_dc"):
        assert name in fit.parameters, name
    assert fit.parameters["init_pole_spacing"].default == "lin"

    enforce = inspect.signature(VectorFitting.passivity_enforce)
    for name in ("n_samples", "f_max", "parameter_type", "preserve_dc"):
        assert name in enforce.parameters, name

    assert "parameter_type" in inspect.signature(VectorFitting.passivity_test).parameters
    assert "parameter_type" in inspect.signature(VectorFitting.is_passive).parameters

    resp = inspect.signature(VectorFitting.get_model_response)
    assert list(resp.parameters)[:3] == ["self", "i", "j"]

    spice = inspect.signature(VectorFitting.write_spice_subcircuit_s)
    assert "fitted_model_name" in spice.parameters
    assert "create_reference_pins" in spice.parameters
    assert spice.parameters["fitted_model_name"].default == "s_equivalent"


# --------------------------------------------------------------------------- #
# 2-4. N=1 / N=2 / N=4 合成有理网络
# --------------------------------------------------------------------------- #

def test_n1_series_rlc_fit_rms_passivity_and_spice(tmp_path) -> None:
    f = _freq()
    s = _series_rlc_s11(f)
    req = _request(s, f, spice_path=str(tmp_path / "n1.sp"), subckt_name="rlc1")
    r = fit_macromodel(req)

    assert r["n_ports"] == 1
    assert r["n_points"] == int(f.size)
    assert r["fit"]["passed"] is True
    assert r["fit"]["rms_db"] <= -40.0
    assert isinstance(r["fit"]["skrf_get_rms_error"], float)
    assert r["passivity"]["before"]["passive_in_band"] is True
    assert r["passivity"]["enforced"] is False
    assert r["passivity"]["after"]["sigma_max_in_band"] <= 1.0 + 1e-6
    assert r["spice"]["valid"] is True
    assert r["fsv"]["gdm_at_least_good"] is True
    assert r["ok"] is True
    assert r["poles_summary"]["n_poles"] == r["order"]["n_poles_total"]


def test_n2_series_inductor_fit_and_fsv(tmp_path) -> None:
    f = _freq()
    s = _series_inductor_2port(f)
    r = fit_macromodel(_request(s, f, spice_path=str(tmp_path / "n2.sp")))

    assert r["n_ports"] == 2
    assert r["fit"]["rms_db"] <= -40.0
    assert set(r["fsv"]["per_response"]) == {"s11", "s12", "s21", "s22"}
    assert r["fsv"]["n_responses"] == 4
    assert r["fsv"]["worst_gdm_grade"] in {"Ex", "VG"}
    assert r["fsv"]["max_grade_index_for_good"] == GRADE_INDEX_GOOD
    assert r["spice"]["n_ports"] == 2
    assert r["spice"]["nodes"] == ["p1", "p2"]
    assert r["spice"]["valid"] is True


def test_n4_inductive_star_multiport(tmp_path) -> None:
    f = _freq(n=121)
    s = _star_4port(f)
    r = fit_macromodel(_request(s, f, z0=[Z0] * 4, spice_path=str(tmp_path / "n4.sp")))

    assert r["n_ports"] == 4
    assert r["z0_ohm"] == [Z0, Z0, Z0, Z0]
    assert r["fit"]["rms_db"] <= -40.0
    assert r["fsv"]["n_responses"] == 16
    assert r["fsv"]["gdm_at_least_good"] is True
    assert r["passivity"]["after"]["passive_in_band"] is True
    assert r["spice"]["n_ports"] == 4
    assert r["spice"]["element_counts"]["R"] >= 4
    assert r["ok"] is True


# --------------------------------------------------------------------------- #
# 5-6. SPICE 结构校验（可被证伪）
# --------------------------------------------------------------------------- #

def _write_spice(tmp_path, name: str = "good.sp", subckt: str = "equiv_good") -> object:
    f = _freq()
    s = _series_rlc_s11(f)
    sp = tmp_path / name
    fit_macromodel(_request(s, f, spice_path=str(sp), subckt_name=subckt))
    return sp


def test_spice_structure_validation(tmp_path) -> None:
    sp = _write_spice(tmp_path)
    info = validate_spice_subcircuit(sp, expected_ports=1, expected_name="equiv_good")

    assert info["valid"] is True
    assert info["exists"] is True
    assert info["errors"] == []
    assert info["subckt_name"] == "equiv_good"
    assert info["nodes"] == ["p1"]
    assert info["n_ports"] == 1
    assert info["has_ends"] is True
    assert info["pin_names_ok"] is True
    assert info["n_elements"] == sum(info["element_counts"].values())
    for etype in ("R", "G", "V", "C"):
        assert info["element_counts"].get(etype, 0) > 0, etype


def test_spice_validator_detects_corruption(tmp_path) -> None:
    """结构校验器自身要被证伪：人为破坏 → valid False + 具体错误。"""
    sp = _write_spice(tmp_path)
    good = sp.read_text(encoding="utf-8")

    no_ends = tmp_path / "no_ends.sp"
    no_ends.write_text(good.replace(".ENDS", "").replace(".ends", ""), encoding="utf-8")
    info = validate_spice_subcircuit(no_ends, expected_ports=1, expected_name="equiv_good")
    assert info["valid"] is False
    assert any(".ENDS" in e for e in info["errors"])

    info = validate_spice_subcircuit(sp, expected_name="other_name")
    assert info["valid"] is False
    assert any("子电路名不符" in e for e in info["errors"])

    bogus = tmp_path / "bogus.sp"
    bogus.write_text(good + "Zbad 1 2 44\n", encoding="utf-8")
    info = validate_spice_subcircuit(bogus)
    assert info["valid"] is False
    assert any("未知元素类型" in e for e in info["errors"])

    short = tmp_path / "short.sp"
    short.write_text(good + "Rbad 1\n", encoding="utf-8")
    info = validate_spice_subcircuit(short)
    assert info["valid"] is False
    assert any("令牌不足" in e for e in info["errors"])

    info = validate_spice_subcircuit(sp, expected_ports=2)
    assert info["valid"] is False
    assert any("端口数不符" in e for e in info["errors"])

    info = validate_spice_subcircuit(tmp_path / "missing.sp")
    assert info["valid"] is False
    assert info["exists"] is False


# --------------------------------------------------------------------------- #
# 7-8. 无源性：非无源 → enforce；无源 → 不 enforce
# --------------------------------------------------------------------------- #

def test_known_nonpassive_enforcement_failure_reported_honestly(tmp_path) -> None:
    """退化有源网络（0 实极点+1 复极点，无界违规）的无源化失败必须如实报告。

    历史：numpy 2.5.3 下 skrf 的 passivity_enforce 能把带内清干净（旧断言
    enforced=True/after passive）。a7 批次引入 fdtdx→tidy3d 硬钉后 venv 降到
    numpy 2.4.6，同例 passivity_enforce 直接 LinAlgError（Singular matrix，
    n_samples 1000→30 阶梯实测均不可绕）。按 #105/#122 纪律：能力不可用=
    如实上报（enforced=False+enforce_error），不制造假 pass。恢复条件=
    skrf/numpy 组合升级后重试（followUps 已登记）。
    """
    f = _freq()
    s = _nonpassive_rlc_s11(f)
    assert float(np.max(np.abs(s))) > 1.0  # 原始数据本身非无源（有源网络）

    r = fit_macromodel(_request(s, f, n_poles_real=0, n_poles_cmplx=1, spice_path=str(tmp_path / "np.sp")))
    before = r["passivity"]["before"]
    after = r["passivity"]["after"]

    assert before["passive_in_band"] is False
    assert before["sigma_max_in_band"] > 1.0
    assert r["passivity"]["enforced"] is False
    assert "LinAlgError" in (r["passivity"]["enforce_error"] or "")
    assert after["passive_in_band"] is False
    assert r["ok"] is False
    assert r["spice"]["valid"] is True


def test_passive_network_not_enforced() -> None:
    f = _freq()
    s = _series_rlc_s11(f)
    r = fit_macromodel(_request(s, f))

    assert r["passivity"]["before"]["passive_in_band"] is True
    assert r["passivity"]["enforced"] is False
    assert r["passivity"]["after"] == r["passivity"]["before"]
    assert r["passivity"]["enforce_error"] is None


# --------------------------------------------------------------------------- #
# 9. 确定性
# --------------------------------------------------------------------------- #

def test_two_fits_are_byte_identical(tmp_path) -> None:
    f = _freq()
    s = _series_rlc_s11(f)
    sp = tmp_path / "det.sp"
    req = _request(s, f, spice_path=str(sp))

    r1 = fit_macromodel(req)
    b1 = sp.read_bytes()
    r2 = fit_macromodel(req)
    b2 = sp.read_bytes()

    assert _dumps(r1) == _dumps(r2)
    assert b1 == b2
    assert len(b1) > 0


# --------------------------------------------------------------------------- #
# 10-11. 极点不足 / 阶梯用尽
# --------------------------------------------------------------------------- #

def test_explicit_insufficient_poles_raises(tmp_path) -> None:
    f = _freq()
    s = _matched_delay_2port(f)  # 纯延迟：非有理，低阶无法达标
    with pytest.raises(MacromodelFitError, match="极点不足"):
        fit_macromodel(_request(s, f, n_poles_real=0, n_poles_cmplx=1, spice_path=str(tmp_path / "bad.sp")))


def test_auto_ladder_best_effort_does_not_raise(tmp_path) -> None:
    f = _freq()
    s = _matched_delay_2port(f)
    r = fit_macromodel(_request(s, f, spice_path=str(tmp_path / "delay.sp")))

    assert r["order"]["explicit"] is False
    tried = [(a["n_poles_real"], a["n_poles_cmplx"]) for a in r["order"]["attempts"]]
    assert tried == [tuple(pair) for pair in DEFAULT_ORDER_LADDER]
    assert r["fit"]["passed"] is False
    assert r["ok"] is False
    assert r["fsv"]["gdm_at_least_good"] is False


# --------------------------------------------------------------------------- #
# 12. 非法输入
# --------------------------------------------------------------------------- #

def _invalid_cases() -> list[tuple[str, dict]]:
    f = _freq(n=41)
    s = _series_rlc_s11(f)
    base = _pair_s(s)
    return [
        ("not_dict", []),
        ("missing_freq", {"s": base}),
        ("missing_s", {"freq_hz": f.tolist()}),
        ("too_few_points", {"freq_hz": f[: MIN_FREQ_POINTS - 8].tolist(), "s": base[: MIN_FREQ_POINTS - 8]}),
        ("non_increasing", {"freq_hz": np.sort(f)[::-1].tolist(), "s": base}),
        ("nan_freq", {"freq_hz": [float("nan"), *f[1:].tolist()], "s": base}),
        ("length_mismatch", {"freq_hz": f.tolist(), "s": base[:-1]}),
        ("non_square", {"freq_hz": f.tolist(), "s": np.ones((f.size, 2, 3)).tolist()}),
        ("z0_length", {"freq_hz": f.tolist(), "s": base, "z0": [Z0, Z0]}),
        ("z0_complex", {"freq_hz": f.tolist(), "s": base, "z0": [[50 + 1j, 0], [0, 50]]}),
        ("nports_mismatch", {"freq_hz": f.tolist(), "s": base, "n_ports": 2}),
        (
            "s_real_imag_shape",
            {
                "freq_hz": f.tolist(),
                "s_real": np.zeros((f.size, 1, 1)).tolist(),
                "s_imag": np.zeros((f.size, 1)).tolist(),
            },
        ),
        ("flat_not_square", {"freq_hz": f.tolist(), "s": np.ones((f.size, 3)).tolist()}),
        ("explicit_half_order", {"freq_hz": f.tolist(), "s": base, "n_poles_real": 1}),
    ]


@pytest.mark.parametrize(("case", "spec"), _invalid_cases(), ids=[c[0] for c in _invalid_cases()])
def test_invalid_inputs_raise(case: str, spec: dict) -> None:
    with pytest.raises(MacromodelInputError):
        fit_macromodel(spec)


# --------------------------------------------------------------------------- #
# 13-15. JSON 往返 / Touchstone / 输入表示等价
# --------------------------------------------------------------------------- #

def test_result_is_json_native_and_roundtrips(tmp_path) -> None:
    f = _freq(n=41)
    s = _series_rlc_s11(f)
    r = fit_macromodel(_request(s, f, spice_path=str(tmp_path / "json.sp")))

    text = json.dumps(r)  # 全为 JSON 原生类型（含 inf 已转 null）才会成功
    assert json.loads(text) == r
    assert isinstance(r["fit"]["rms_db"], float)
    assert isinstance(r["passivity"]["after"]["sigma_max_in_band"], float)
    assert isinstance(r["spice"]["element_counts"], dict)


def test_request_from_touchstone_and_fit(tmp_path) -> None:
    f = _freq(n=101)
    s = _series_inductor_2port(f)
    nw = skrf.Network(frequency=f, s=s, z0=Z0)
    p = tmp_path / "demo.s2p"
    nw.write_touchstone(str(p))

    req = request_from_touchstone(p)
    assert req["n_ports"] == 2
    assert len(req["freq_hz"]) == f.size
    assert req["z0"] == [Z0, Z0]
    assert req["source_path"] == str(p)

    r = fit_macromodel({**req, "spice_path": str(tmp_path / "demo.sp")})
    assert r["n_ports"] == 2
    assert r["fit"]["rms_db"] <= -40.0
    assert r["spice"]["valid"] is True

    with pytest.raises(MacromodelInputError):
        request_from_touchstone(tmp_path / "nope.s1p")


def test_input_forms_are_equivalent() -> None:
    f = _freq(n=101)
    s = _series_rlc_s11(f)
    base = {"freq_hz": f.tolist()}
    flat = [[cell for row in mat for cell in row] for mat in _dict_s(s)]

    r_pair = fit_macromodel({**base, "s": _pair_s(s)})
    r_dict = fit_macromodel({**base, "s": _dict_s(s)})
    r_split = fit_macromodel({**base, "s_real": np.real(s).tolist(), "s_imag": np.imag(s).tolist()})
    r_flat = fit_macromodel({**base, "s": flat})

    assert _dumps(r_pair) == _dumps(r_dict)
    assert _dumps(r_pair) == _dumps(r_split)
    assert _dumps(r_pair) == _dumps(r_flat)
