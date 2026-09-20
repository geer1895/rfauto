"""D13 SPICE 回放自检定向单元测试（纯 Python 复数 MNA；不依赖 ngspice.exe）。

任务来源：D13 PARTIAL 收口（当时 PARTIAL 原因 = 无 ngspice.exe
回放未做）。本文件验证 `core/macromodel.replay_spice_subcircuit_s`：

1. MNA 内核语义对拍闭式解（与拟合器/skrf 无共享代码路径）：
   RC 1 端口 / 串联 R+L 2 端口 / VCCS / CCCS / VCVS / CCVS 合成网表，
   期望 S 由手工推导的闭式给出（各测试 docstring 附推导）；
2. skrf 导出网表回放：N=1 / N=4（含 z0 从 R<i> 推断）与参考针形式
   （create_reference_pins=True），回放 vs 原始闭式 S 误差数字；
3. fit_macromodel 集成：spice_replay 段（status/consistent/disclaimer/
   replay_vs_original / replay_vs_model）+ ok 门 + JSON round-trip +
   可关闭 + 失败如实记 error 并判 ok=False；
4. 语义/解析错误路径（非零独立源、未知元素、缺 .SUBCKT/.ENDS、0 Hz 含 L、
   奇异网表、端口数不符、z0 推断失败）。

诚实口径：本回放是**回放自检**（验证"导出网表在标准 SPICE 元素语义下重现
S 参数"），不是 ngspice/LTspice/Xyce 等第三方 SPICE 仿真器的等价验证。
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import skrf
from skrf.vectorFitting import VectorFitting

import rfauto.core.macromodel as macromodel_module
from rfauto.core.macromodel import (
    DEFAULT_REPLAY_CONSISTENCY_TOL,
    MacromodelError,
    MacromodelInputError,
    _parse_spice_number,
    fit_macromodel,
    replay_spice_ac_response,
    replay_spice_subcircuit_s,
)

Z0 = 50.0


# --------------------------------------------------------------------------- #
# 闭式合成网络与网表（独立于 MNA 内核的期望值来源）
# --------------------------------------------------------------------------- #

def _freq(n: int = 41, lo: float = 1e9, hi: float = 20e9) -> np.ndarray:
    return np.linspace(lo, hi, n)


def _series_rlc_s11(f: np.ndarray, r: float = 5.0, l_henry: float = 2e-9, c: float = 0.5e-12) -> np.ndarray:
    """1 端口串联 RLC：Z = R + jwL + 1/(jwC)，S11 = (Z-Z0)/(Z+Z0)。"""
    w = 2.0 * np.pi * f
    z = r + 1j * w * l_henry + 1.0 / (1j * w * c)
    return ((z - Z0) / (z + Z0)).reshape(-1, 1, 1)


def _series_rl_2port(f: np.ndarray, r: float = 3.0, l_henry: float = 3e-9) -> np.ndarray:
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


def _request(s: np.ndarray, f: np.ndarray, **kw) -> dict:
    req: dict = {
        "freq_hz": f.tolist(),
        "s": [[[[float(v.real), float(v.imag)] for v in row] for row in mat] for mat in np.asarray(s, dtype=complex)],
    }
    req.update(kw)
    return req


def _write_netlist(tmp_path, text: str, name: str = "net.sp") -> object:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _max_abs(s_ref: np.ndarray, s_test: np.ndarray) -> float:
    return float(np.max(np.abs(np.asarray(s_ref, dtype=complex) - np.asarray(s_test, dtype=complex))))


# --------------------------------------------------------------------------- #
# 1. SPICE 数值解析（后缀/科学计数/非法）
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("50.0", 50.0),
        ("-3.25", -3.25),
        ("1e3", 1.0e3),
        ("1.5E-2", 1.5e-2),
        ("2p", 2e-12),
        ("2pF", 2e-12),
        ("1k", 1e3),
        ("3meg", 3e6),
        ("10u", 1e-5),
        ("4n", 4e-9),
        ("2mil", 2 * 25.4e-6),
        ("7f", 7e-15),
    ],
)
def test_spice_number_parsing(token: str, expected: float) -> None:
    assert _parse_spice_number(token, "t") == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("token", ["abc", "--3", "1.2.3", ""])
def test_spice_number_parsing_rejects_garbage(token: str) -> None:
    with pytest.raises(MacromodelInputError, match="无法解析"):
        _parse_spice_number(token, "t")


# --------------------------------------------------------------------------- #
# 2. MNA 内核语义对拍闭式解（合成网表，期望值手工推导）
# --------------------------------------------------------------------------- #

def test_replay_rc_one_port_closed_form(tmp_path) -> None:
    """R=25Ω 串 C=2pF 到地：Z=25+1/(jωC)，S11=(Z-50)/(Z+50)；同时覆盖 z0 显式传参。"""
    p = _write_netlist(tmp_path, ".SUBCKT rc1 p1\nR1 p1 n1 25.0\nC1 n1 0 2e-12\n.ENDS rc1\n")
    f = _freq()
    r = replay_spice_subcircuit_s(p, f, z0=Z0)

    assert r["n_ports"] == 1
    assert r["port_nodes"] == ["p1"]
    assert r["subckt_name"] == "rc1"
    assert r["element_counts"] == {"R": 1, "C": 1}
    assert r["z0_source"] == "explicit"
    w = 2.0 * np.pi * f
    z = 25.0 + 1.0 / (1j * w * 2e-12)
    s_expect = (z - Z0) / (z + Z0)
    assert _max_abs(s_expect.reshape(-1, 1, 1), r["s"]) < 1e-12


def test_replay_number_suffixes_through_netlist(tmp_path) -> None:
    """后缀数值经网表端到端：R1=1k、C1=2p。"""
    p = _write_netlist(tmp_path, ".SUBCKT rcx p1\nR1 p1 n1 1k\nC1 n1 0 2p\n.ENDS rcx\n")
    f = _freq(n=21)
    r = replay_spice_subcircuit_s(p, f, z0=Z0)
    w = 2.0 * np.pi * f
    z = 1000.0 + 1.0 / (1j * w * 2e-12)
    assert _max_abs(((z - Z0) / (z + Z0)).reshape(-1, 1, 1), r["s"]) < 1e-12


def test_replay_series_rl_two_port_closed_form(tmp_path) -> None:
    """串联 R+L 二端口（Z = 3+jω·3n 在 p1/p2 之间）：闭式 S 对拍（覆盖 L 戳）。"""
    p = _write_netlist(tmp_path, ".SUBCKT sz2 p1 p2\nR1 p1 n1 3.0\nL1 n1 p2 3e-9\n.ENDS sz2\n")
    f = _freq()
    r = replay_spice_subcircuit_s(p, f, z0=[Z0, Z0])
    assert np.allclose(r["s"], _series_rl_2port(f), atol=1e-12)


def test_replay_vccs_two_port(tmp_path) -> None:
    """VCCS 跨导放大器：Y=[[0.02,0],[-0.02,0.02]] ⇒ S21=0.5、其余 0（与频率无关）。"""
    p = _write_netlist(
        tmp_path,
        ".SUBCKT amp2 p1 p2\nR1 p1 0 50.0\nG1 0 p2 p1 0 0.02\nR2 p2 0 50.0\n.ENDS amp2\n",
    )
    f = _freq(n=11)
    r = replay_spice_subcircuit_s(p, f, z0=Z0)
    expect = np.zeros((f.size, 2, 2), dtype=complex)
    expect[:, 1, 0] = 0.5
    assert _max_abs(expect, r["s"]) < 1e-12


def test_replay_cccs_two_port(tmp_path) -> None:
    """CCCS：Y21=-0.02·(1/50) ⇒ S21=0.01（覆盖 V 采样器 + F 戳）。"""
    p = _write_netlist(
        tmp_path,
        ".SUBCKT cccs2 p1 p2\nV1 p1 n1 0\nR1 n1 0 50.0\nF1 0 p2 V1 0.02\nR2 p2 0 50.0\n.ENDS cccs2\n",
    )
    f = _freq(n=11)
    r = replay_spice_subcircuit_s(p, f, z0=Z0)
    expect = np.zeros((f.size, 2, 2), dtype=complex)
    expect[:, 1, 0] = 0.01
    assert _max_abs(expect, r["s"]) < 1e-12


def test_replay_vcvs_two_port(tmp_path) -> None:
    """VCVS 单位增益缓冲 + 50/50 分压：S21=1/3、S22=-1/3（手工推导，覆盖 E 戳）。"""
    p = _write_netlist(
        tmp_path,
        ".SUBCKT buf2 p1 p2\nR1 p1 0 50.0\nE1 n1 0 p1 0 1.0\nR2 n1 p2 50.0\nR3 p2 0 50.0\n.ENDS buf2\n",
    )
    f = _freq(n=11)
    r = replay_spice_subcircuit_s(p, f, z0=Z0)
    expect = np.zeros((f.size, 2, 2), dtype=complex)
    expect[:, 1, 0] = 1.0 / 3.0
    expect[:, 1, 1] = -1.0 / 3.0
    assert _max_abs(expect, r["s"]) < 1e-12


def test_replay_ccvs_two_port(tmp_path) -> None:
    """CCVS（rm=100Ω 采样 50Ω 端口电流）：S21=2/3、S22=-1/3（覆盖 H 戳）。"""
    p = _write_netlist(
        tmp_path,
        ".SUBCKT h2 p1 p2\nV1 p1 n1 0\nR1 n1 0 50.0\nH1 n2 0 V1 100.0\nR2 p2 n2 50.0\nR3 p2 0 50.0\n.ENDS h2\n",
    )
    f = _freq(n=11)
    r = replay_spice_subcircuit_s(p, f, z0=Z0)
    expect = np.zeros((f.size, 2, 2), dtype=complex)
    expect[:, 1, 0] = 2.0 / 3.0
    expect[:, 1, 1] = -1.0 / 3.0
    assert _max_abs(expect, r["s"]) < 1e-12


def test_replay_dc_limit_capacitive_one_port(tmp_path) -> None:
    """f=0（无 L）：纯电容端口在 DC 为开路，S11=1（允许 0 Hz，仅含 L 时才拒绝）。"""
    p = _write_netlist(tmp_path, ".SUBCKT c1 p1\nC1 p1 0 2e-12\n.ENDS c1\n")
    r = replay_spice_subcircuit_s(p, np.array([0.0]), z0=Z0)
    assert abs(r["s"][0, 0, 0] - 1.0) < 1e-12


# --------------------------------------------------------------------------- #
# 3. skrf 导出网表回放（z0 从 R<i> 推断 / 参考针形式）
# --------------------------------------------------------------------------- #

def test_replay_skrf_export_n1_matches_closed_form(tmp_path) -> None:
    f = _freq()
    s_orig = _series_rlc_s11(f)
    sp = tmp_path / "n1.sp"
    fit_macromodel(_request(s_orig, f, spice_path=str(sp), subckt_name="rlc1"))

    r = replay_spice_subcircuit_s(sp, f)  # z0 缺省 → 从 R1 推断
    assert r["z0_source"] == "inferred_from_R_i"
    assert r["z0_ohm"] == [Z0]
    assert r["port_nodes"] == ["p1"]
    assert r["n_elements"] > 0
    assert r["disclaimer"]
    # 回放自检误差数字：skrf 综合网表在标准 SPICE 语义下重现原始 S 到机器精度量级
    assert _max_abs(s_orig, r["s"]) < 1e-10


def test_replay_skrf_export_n4_matches_closed_form(tmp_path) -> None:
    """N=4 电感星形（Y = y(I-J/4)）导出回放：z0 逐端口从 R1..R4 推断。"""
    f = _freq(n=81)
    y_diag = 1.0 / (2.0 + 1j * 2.0 * np.pi * f * 1e-9)
    ident = np.eye(4)
    jmat = np.ones((4, 4)) / 4.0
    s_orig = np.zeros((f.size, 4, 4), dtype=complex)
    for k in range(f.size):
        ymat = y_diag[k] * (ident - jmat)
        s_orig[k] = (ident - Z0 * ymat) @ np.linalg.inv(ident + Z0 * ymat)
    sp = tmp_path / "n4.sp"
    fit_macromodel(_request(s_orig, f, z0=[Z0] * 4, spice_path=str(sp)))

    r = replay_spice_subcircuit_s(sp, f, n_ports=4)
    assert r["z0_source"] == "inferred_from_R_i"
    assert r["z0_ohm"] == [Z0] * 4
    assert r["port_nodes"] == ["p1", "p2", "p3", "p4"]
    assert r["element_counts"].get("R", 0) >= 4
    assert _max_abs(s_orig, r["s"]) < 1e-10


def test_replay_skrf_export_reference_pins_mode(tmp_path) -> None:
    """create_reference_pins=True 的导出（p1 p1_ref ...）按差分端口回放。"""
    f = _freq()
    s_orig = _series_rlc_s11(f)
    nw = skrf.Network(frequency=f, s=s_orig, z0=Z0)
    vf = VectorFitting(nw)
    vf.vector_fit(n_poles_real=1, n_poles_cmplx=2)
    sp = tmp_path / "refpin.sp"
    vf.write_spice_subcircuit_s(str(sp), fitted_model_name="refpin", create_reference_pins=True)

    r = replay_spice_subcircuit_s(sp, f, z0=Z0)
    assert r["port_nodes"] == ["p1"]
    assert r["ref_nodes"] == ["p1_ref"]
    assert r["n_ports"] == 1
    assert _max_abs(s_orig, r["s"]) < 1e-8  # 低阶拟合残差 ~1e-9 量级亦可接受


def test_replay_is_deterministic(tmp_path) -> None:
    f = _freq(n=21)
    s_orig = _series_rlc_s11(f)
    sp = tmp_path / "det.sp"
    fit_macromodel(_request(s_orig, f, spice_path=str(sp)))
    r1 = replay_spice_subcircuit_s(sp, f)
    r2 = replay_spice_subcircuit_s(sp, f)

    assert r1["s"].tobytes() == r2["s"].tobytes()
    for key in ("subckt_name", "port_nodes", "z0_ohm", "element_counts", "freq_hz"):
        assert r1[key] == r2[key], key


# --------------------------------------------------------------------------- #
# 4. fit_macromodel 集成（spice_replay 段 + ok 门）
# --------------------------------------------------------------------------- #

def test_fit_result_contains_replay_selfcheck(tmp_path) -> None:
    f = _freq()
    s_orig = _series_rlc_s11(f)
    r = fit_macromodel(_request(s_orig, f, spice_path=str(tmp_path / "it.sp")))

    sr = r["spice_replay"]
    assert sr is not None
    assert sr["status"] == "ok"
    assert sr["verifier"] == "replay_selfcheck"
    assert "回放自检" in sr["disclaimer"] and "不是" in sr["disclaimer"]
    assert sr["consistent"] is True
    assert sr["consistency_tol_abs"] == DEFAULT_REPLAY_CONSISTENCY_TOL
    assert sr["replay_vs_model"]["max_abs"] <= DEFAULT_REPLAY_CONSISTENCY_TOL
    assert sr["replay_vs_original"]["max_abs"] < 1e-10
    assert sr["replay_vs_original"]["rms_db"] < -100.0
    assert r["ok"] is True
    # 回放 S 矩阵随结果返回（JSON [re, im] 对）且与复数真值一致
    s_rep = np.asarray(sr["s"], dtype=float)
    s_rep = s_rep[..., 0] + 1j * s_rep[..., 1]
    assert _max_abs(s_orig, s_rep) < 1e-10


def test_fit_result_replay_json_roundtrip(tmp_path) -> None:
    f = _freq(n=21)
    s_orig = _series_rlc_s11(f)
    r = fit_macromodel(_request(s_orig, f, spice_path=str(tmp_path / "rt.sp")))
    assert json.loads(json.dumps(r)) == r


def test_fit_replay_can_be_disabled(tmp_path) -> None:
    f = _freq(n=21)
    s_orig = _series_rlc_s11(f)
    r = fit_macromodel(_request(s_orig, f, spice_path=str(tmp_path / "off.sp"), spice_replay=False))
    assert r["spice_replay"] is None
    assert r["ok"] is True  # 关闭回放时 ok 门不检查回放（与 spice=None 同口径）
    assert r["spice"]["valid"] is True


def test_fit_replay_failure_recorded_and_ok_false(tmp_path, monkeypatch) -> None:
    f = _freq(n=21)
    s_orig = _series_rlc_s11(f)
    sp = tmp_path / "boom.sp"

    def _boom(*args, **kwargs) -> None:
        raise RuntimeError("boom: 回放内核不可用")

    monkeypatch.setattr(macromodel_module, "replay_spice_subcircuit_s", _boom)
    r = fit_macromodel(_request(s_orig, f, spice_path=str(sp)))

    assert r["spice_replay"]["status"] == "error"
    assert "boom: 回放内核不可用" in r["spice_replay"]["error"]
    assert r["ok"] is False  # 验证面不可用即不得宣称交付链可信
    assert r["spice"]["valid"] is True


def test_fit_without_spice_path_has_no_replay() -> None:
    f = _freq(n=21)
    s_orig = _series_rlc_s11(f)
    r = fit_macromodel(_request(s_orig, f))
    assert r["spice_replay"] is None


# --------------------------------------------------------------------------- #
# 5. 错误路径（解析/语义/数值）
# --------------------------------------------------------------------------- #

def test_replay_missing_file(tmp_path) -> None:
    with pytest.raises(MacromodelInputError, match="不存在"):
        replay_spice_subcircuit_s(tmp_path / "nope.sp", [1e9])


def test_replay_missing_subckt_or_ends(tmp_path) -> None:
    p = _write_netlist(tmp_path, "R1 p1 0 50.0\n", name="nosub.sp")
    with pytest.raises(MacromodelInputError, match="SUBCKT"):
        replay_spice_subcircuit_s(p, [1e9])

    p = _write_netlist(tmp_path, ".SUBCKT x p1\nR1 p1 0 50.0\n", name="noends.sp")
    with pytest.raises(MacromodelInputError, match="ENDS"):
        replay_spice_subcircuit_s(p, [1e9])


def test_replay_rejects_unknown_element_kind(tmp_path) -> None:
    p = _write_netlist(tmp_path, ".SUBCKT x p1\nZbad p1 0 50.0\n.ENDS x\n")
    with pytest.raises(MacromodelInputError, match="不被回放求解器支持"):
        replay_spice_subcircuit_s(p, [1e9])


def test_replay_rejects_duplicate_element_names(tmp_path) -> None:
    p = _write_netlist(tmp_path, ".SUBCKT x p1\nR1 p1 0 50.0\nR1 p1 0 50.0\n.ENDS x\n")
    with pytest.raises(MacromodelInputError, match="重复"):
        replay_spice_subcircuit_s(p, [1e9])


def test_replay_rejects_ground_pin(tmp_path) -> None:
    p = _write_netlist(tmp_path, ".SUBCKT x 0 p1\nR1 p1 0 50.0\n.ENDS x\n")
    with pytest.raises(MacromodelInputError, match="地节点"):
        replay_spice_subcircuit_s(p, [1e9])


@pytest.mark.parametrize("body", ["V1 p1 0 1.0\nR1 p1 0 50.0\n", "R1 p1 0 50.0\nI1 0 p1 0.01\n"])
def test_replay_rejects_nonzero_independent_sources(tmp_path, body: str) -> None:
    """回放按零输入线性响应提取 S；非零独立激励会污染端口电流提取 → 显式拒绝。"""
    p = _write_netlist(tmp_path, f".SUBCKT x p1\n{body}.ENDS x\n")
    with pytest.raises(MacromodelInputError, match="独立源"):
        replay_spice_subcircuit_s(p, [1e9])


def test_replay_rejects_dangling_control_source(tmp_path) -> None:
    p = _write_netlist(tmp_path, ".SUBCKT x p1\nR1 p1 0 50.0\nF1 0 p1 V9 0.02\n.ENDS x\n")
    with pytest.raises(MacromodelInputError, match="控制源"):
        replay_spice_subcircuit_s(p, [1e9])


def test_replay_rejects_zero_ohm_and_zero_henry(tmp_path) -> None:
    p = _write_netlist(tmp_path, ".SUBCKT x p1\nR1 p1 0 0.0\n.ENDS x\n")
    with pytest.raises(MacromodelInputError, match="0Ω"):
        replay_spice_subcircuit_s(p, [1e9], z0=Z0)
    p = _write_netlist(tmp_path, ".SUBCKT x p1\nL1 p1 0 0.0\n.ENDS x\n")
    with pytest.raises(MacromodelInputError, match="0H"):
        replay_spice_subcircuit_s(p, [1e9], z0=Z0)


def test_replay_rejects_zero_hz_with_inductor(tmp_path) -> None:
    p = _write_netlist(tmp_path, ".SUBCKT x p1 p2\nL1 p1 p2 1e-9\n.ENDS x\n")
    with pytest.raises(MacromodelInputError, match="0 Hz"):
        replay_spice_subcircuit_s(p, [0.0, 1e9], z0=Z0)
    with pytest.raises(MacromodelInputError, match="≥ 0"):
        replay_spice_subcircuit_s(p, [-1e9], z0=Z0)
    with pytest.raises(MacromodelInputError, match="为空"):
        replay_spice_subcircuit_s(p, [], z0=Z0)


def test_replay_singular_netlist_raises(tmp_path) -> None:
    """E1 强制 V(p1)=V(p1)（自指）→ 分支电流不定 → 矩阵奇异，显式报错不静默。"""
    p = _write_netlist(tmp_path, ".SUBCKT sing p1\nR1 p1 0 10.0\nE1 p1 0 p1 0 1.0\n.ENDS sing\n")
    with pytest.raises(MacromodelError, match="奇异"):
        replay_spice_subcircuit_s(p, [1e9], z0=Z0)


def test_replay_port_count_and_z0_inference_errors(tmp_path) -> None:
    f = [1e9, 2e9]
    p = _write_netlist(tmp_path, ".SUBCKT rc1 p1\nR1 p1 n1 25.0\nC1 n1 0 2e-12\n.ENDS rc1\n")
    with pytest.raises(MacromodelInputError, match="端口数不符"):
        replay_spice_subcircuit_s(p, f, z0=Z0, n_ports=3)

    p_noz = _write_netlist(tmp_path, ".SUBCKT c1 p1\nC1 p1 0 2e-12\n.ENDS c1\n", name="noz.sp")
    with pytest.raises(MacromodelInputError, match="R1"):
        replay_spice_subcircuit_s(p_noz, f)  # 无 R1 可推断且未显式传 z0


# --------------------------------------------------------------------------- #
# 6. 解析器升级（2026-09-15）：.PARAM 数字字面量 / 单层 .INCLUDE / 指令白名单
#    （原实现 .PARAM/.INCLUDE 等全部静默忽略——.PARAM 丢失会静默改元件值，不诚实）
# --------------------------------------------------------------------------- #

def test_param_numeric_literal_substitution(tmp_path) -> None:
    """.PARAM 数字字面量（含后缀）替换进元件值：R 用裸名、C 用 {名} 花括号形式。"""
    p = _write_netlist(
        tmp_path,
        ".SUBCKT rc1 p1\n.param rr = 25.0 cc=2p\nR1 p1 n1 rr\nC1 n1 0 {cc}\n.ENDS rc1\n",
        name="param.sp",
    )
    f = _freq(n=21)
    r = replay_spice_subcircuit_s(p, f, z0=Z0)
    w = 2.0 * np.pi * f
    z = 25.0 + 1.0 / (1j * w * 2e-12)
    assert _max_abs(((z - Z0) / (z + Z0)).reshape(-1, 1, 1), r["s"]) < 1e-12


def test_param_expression_rejected(tmp_path) -> None:
    """表达式/函数/参数链式引用显式报错（不静默取 0、不猜测求值）。"""
    p = _write_netlist(tmp_path, ".SUBCKT x p1\n.param bad = {2*3}\nR1 p1 0 50\n.ENDS x\n")
    with pytest.raises(MacromodelInputError, match="表达式/函数/参数引用"):
        replay_spice_subcircuit_s(p, [1e9], z0=Z0)

    p = _write_netlist(tmp_path, ".SUBCKT x p1\n.param a 1k\nR1 p1 0 50\n.ENDS x\n")
    with pytest.raises(MacromodelInputError, match="语法非法"):
        replay_spice_subcircuit_s(p, [1e9], z0=Z0)

    p = _write_netlist(tmp_path, ".SUBCKT x p1\n.param a = 1k b = a\nR1 p1 0 a\n.ENDS x\n")
    with pytest.raises(MacromodelInputError, match="表达式/函数/参数引用"):
        replay_spice_subcircuit_s(p, [1e9], z0=Z0)

    p = _write_netlist(tmp_path, ".SUBCKT x p1\nR1 p1 0 {rr*2}\n.ENDS x\n")
    with pytest.raises(MacromodelInputError, match="花括号表达式"):
        replay_spice_subcircuit_s(p, [1e9], z0=Z0)


def test_param_undefined_reference_rejected(tmp_path) -> None:
    """引用未定义参数：显式报错而非按 0/字面量处理（原静默忽略会把 '1k' 这类
    后缀值以外的标识符直接当不可解析值报错——现在报'未定义参数'，语义更准）。"""
    p = _write_netlist(tmp_path, ".SUBCKT x p1\nR1 p1 0 rzz\n.ENDS x\n")
    with pytest.raises(MacromodelInputError, match=r"未定义的 \.PARAM"):
        replay_spice_subcircuit_s(p, [1e9], z0=Z0)


def test_include_single_layer_inlined(tmp_path) -> None:
    """.INCLUDE 单层内联：顶层 include 元素体，回放结果与内联写法一致。"""
    (tmp_path / "body.inc").write_text("R1 p1 n1 25.0\nC1 n1 0 2e-12\n", encoding="utf-8")
    p = _write_netlist(
        tmp_path, ".SUBCKT rc1 p1\n.include body.inc\n.ENDS rc1\n", name="top.sp"
    )
    f = _freq(n=21)
    r = replay_spice_subcircuit_s(p, f, z0=Z0)
    w = 2.0 * np.pi * f
    z = 25.0 + 1.0 / (1j * w * 2e-12)
    assert _max_abs(((z - Z0) / (z + Z0)).reshape(-1, 1, 1), r["s"]) < 1e-12


def test_include_nested_rejected(tmp_path) -> None:
    """被包含文件中再 .INCLUDE：单层限制显式报错。"""
    (tmp_path / "lvl2.inc").write_text("R1 p1 0 50.0\n", encoding="utf-8")
    (tmp_path / "lvl1.inc").write_text(".include lvl2.inc\n", encoding="utf-8")
    p = _write_netlist(tmp_path, ".SUBCKT x p1\n.include lvl1.inc\n.ENDS x\n", name="nest.sp")
    with pytest.raises(MacromodelInputError, match="单层"):
        replay_spice_subcircuit_s(p, [1e9], z0=Z0)


def test_include_cycle_rejected(tmp_path) -> None:
    """.INCLUDE 自引用（循环）：显式报错。"""
    p = _write_netlist(tmp_path, ".SUBCKT x p1\n.include self.sp\nR1 p1 0 50.0\n.ENDS x\n", name="self.sp")
    with pytest.raises(MacromodelInputError, match="循环引用"):
        replay_spice_subcircuit_s(p, [1e9], z0=Z0)


def test_include_missing_file_rejected(tmp_path) -> None:
    p = _write_netlist(tmp_path, ".SUBCKT x p1\n.include ghost.inc\n.ENDS x\n", name="gm.sp")
    with pytest.raises(MacromodelInputError, match="不存在"):
        replay_spice_subcircuit_s(p, [1e9], z0=Z0)


def test_unknown_directive_now_explicit_error(tmp_path) -> None:
    """白名单外指令（.options/.ac/.model 等）：原静默忽略 → 现显式报错。"""
    for directive in (".options reltol=1e-4", ".ac lin 11 1e9 2e9", ".model dm D(Is=1e-14)", ".lib x.lib"):
        p = _write_netlist(
            tmp_path, f".SUBCKT x p1\n{directive}\nR1 p1 0 50.0\n.ENDS x\n", name="ud.sp"
        )
        with pytest.raises(MacromodelInputError, match="未知指令"):
            replay_spice_subcircuit_s(p, [1e9], z0=Z0)


# --------------------------------------------------------------------------- #
# 7. 有源 .AC 回放（replay_spice_ac_response）：放行非零独立源，
#    返回节点电压/支路电流（零输入校验只限定在 S 参数提取入口）
# --------------------------------------------------------------------------- #

def test_ac_response_rc_divider_closed_form(tmp_path) -> None:
    """V=1V + R 串 C 到地：V(n1)=Zc/(R+Zc)，I(V1)=-(1-V(n1))/R（SPICE 支路方向）。"""
    p = _write_netlist(
        tmp_path, ".SUBCKT div p1\nV1 p1 0 1.0\nR1 p1 n1 25.0\nC1 n1 0 2e-12\n.ENDS div\n"
    )
    f = _freq(n=21)
    r = replay_spice_ac_response(p, f)
    w = 2.0 * np.pi * f
    zc = 1.0 / (1j * w * 2e-12)
    vn1 = zc / (25.0 + zc)
    assert np.max(np.abs(r["node_voltages"]["p1"] - 1.0)) < 1e-12
    assert np.max(np.abs(r["node_voltages"]["n1"] - vn1)) < 1e-12
    iv1_expect = -(1.0 - vn1) / 25.0  # 正电流 = 从 p1 经源流向 0（与 ngspice i(v1) 同号）
    assert np.max(np.abs(r["branch_currents"]["V1"] - iv1_expect)) < 1e-12
    assert r["n_branches"] == 1
    assert r["subckt_name"] == "div"
    assert r["disclaimer"]


def test_ac_response_current_source_closed_form(tmp_path) -> None:
    """I 源注入 RC 并联：V(p1)=I·Z(R∥C)。"""
    p = _write_netlist(
        tmp_path, ".SUBCKT isrc p1\nI1 0 p1 0.01\nR1 p1 0 50.0\nC1 p1 0 2e-12\n.ENDS isrc\n"
    )
    f = np.linspace(1e6, 1e9, 11)
    r = replay_spice_ac_response(p, f)
    w = 2.0 * np.pi * f
    zpar = 1.0 / (1.0 / 50.0 + 1j * w * 2e-12)
    # I1 0 p1：电流从 0 经源流向 p1（注入 p1）→ V(p1) = 0.01·Zpar
    assert np.max(np.abs(r["node_voltages"]["p1"] - 0.01 * zpar)) < 1e-12
    assert "p1" in r["node_voltages"] and r["branch_currents"] == {}


def test_ac_response_with_param_and_nonzero_voltage_source(tmp_path) -> None:
    """有源回放 + .PARAM 组合：V=vv、R=rr 参数化，闭式分压。"""
    p = _write_netlist(
        tmp_path,
        ".SUBCKT dvd p1\n.param vv=2.0 rr=30.0 rl=20.0\nV1 p1 0 vv\nR1 p1 n1 rr\nR2 n1 0 rl\n.ENDS dvd\n",
        name="dvd.sp",
    )
    r = replay_spice_ac_response(p, [1e9])
    assert np.max(np.abs(r["node_voltages"]["n1"] - 2.0 * 20.0 / 50.0)) < 1e-12


def test_ac_response_rejects_bad_inputs(tmp_path) -> None:
    p = _write_netlist(tmp_path, ".SUBCKT d p1\nV1 p1 0 1.0\nR1 p1 0 50.0\n.ENDS d\n")
    with pytest.raises(MacromodelInputError, match="为空"):
        replay_spice_ac_response(p, [])
    with pytest.raises(MacromodelInputError, match="NaN/Inf"):
        replay_spice_ac_response(p, [float("nan")])
    with pytest.raises(MacromodelInputError, match="≥ 0"):
        replay_spice_ac_response(p, [-1e9])


def test_s_entry_still_rejects_nonzero_sources(tmp_path) -> None:
    """零输入语义不放宽：S 参数提取入口对非零独立源仍显式拒绝（指向有源回放入口）。"""
    p = _write_netlist(tmp_path, ".SUBCKT d p1\nV1 p1 0 1.0\nR1 p1 0 50.0\n.ENDS d\n")
    with pytest.raises(MacromodelInputError, match="replay_spice_ac_response"):
        replay_spice_subcircuit_s(p, [1e9], z0=Z0)
