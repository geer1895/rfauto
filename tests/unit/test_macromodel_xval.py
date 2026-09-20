"""D13 第三方 SPICE 交叉验证（ngspice .AC xval）定向单元测试——**全离线**。

验收目标（方案冻结验收行 D13）："ngspice/Xyce 回放 vs 原 S 参数 FSV
（D12）评级 ≥Good"。

本文件验证 `adapters.spice_netlist.xval_macromodel_spice` /
`run_ngspice_ac_sparam` 的**编排与解析管道**（ngspice 二进制打桩为"按闭式
Y 写 wrdata 复数文件"的确定性替身——零网络、零真机，#139）；wrdata 输出
格式原文夹具（真机标定捕获）的解析与 deck 渲染断言在
test_spice_netlist.py；真二进制端到端真机门在
tests/real_edt/test_macromodel_xval_real.py。

闭式真值：串联 R-L 二端口 Y = (1/Z)[[1,-1],[-1,1]]（Z=R+jωL），与拟合器、
ngspice 替身无共享代码路径（#122 裁判不自证）。

分层红线：core 禁 import adapters（fit_macromodel 主链不缺省依赖 ngspice，
由 lint-imports + 本文件全离线可跑共同钉住）；Xyce 维持探测钩子不实现。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rfauto.adapters import spice_netlist as sn
from rfauto.core.fsv import GRADE_CODES, grade_index_of
from rfauto.core.macromodel import (
    GRADE_INDEX_GOOD,
    MIN_FREQ_POINTS,
    fit_macromodel,
    replay_spice_subcircuit_s,
)

Z0 = 50.0
R_SER = 3.0
L_SER = 3e-9


def _freq(n: int = 33) -> np.ndarray:
    return np.linspace(1e9, 20e9, n)


def _closed_form_y(freq: np.ndarray) -> np.ndarray:
    w = 2.0 * np.pi * freq
    z = R_SER + 1j * w * L_SER
    y = np.zeros((freq.size, 2, 2), dtype=complex)
    y[:, 0, 0] = y[:, 1, 1] = 1.0 / z
    y[:, 0, 1] = y[:, 1, 0] = -1.0 / z
    return y


def _closed_form_s(freq: np.ndarray) -> np.ndarray:
    w = 2.0 * np.pi * freq
    z = R_SER + 1j * w * L_SER
    den = 2.0 * Z0 + z
    s = np.zeros((freq.size, 2, 2), dtype=complex)
    s[:, 0, 0] = s[:, 1, 1] = z / den
    s[:, 0, 1] = s[:, 1, 0] = 2.0 * Z0 / den
    return s


def _write_dut(tmp_path: Path) -> Path:
    sp = tmp_path / "dut.sp"
    sp.write_text(
        f".SUBCKT dut p1 p2\nR1 p1 m {R_SER}\nL1 m p2 {L_SER:.17g}\n.ENDS dut\n",
        encoding="ascii",
    )
    return sp


class _NgspiceStub:
    """ngspice 二进制替身：读 deck 提取激励端口/wrdata 名/频轴，按闭式 Y 写复数列。

    语义即真机标定口径：i(v_i) = -Y[i, j]（j=激励端口），每向量三列
    (freq, real, imag)，逐频追加。
    """

    def __init__(self, y: np.ndarray, *, fail_ports: set[int] | None = None, skip_write: bool = False):
        self.y = y
        self.fail_ports = fail_ports or set()
        self.skip_write = skip_write
        self.calls: list[dict] = []

    def __call__(self, deck_path, *, exe=None, timeout_s=300.0):
        text = deck_path.read_text(encoding="ascii")
        exc = None
        for ln in text.splitlines():
            if ln.startswith("V") and ln.endswith("AC 1"):
                exc = int(ln.split()[0][1:]) - 1
        assert exc is not None, "替身要求 deck 内恰有一个 AC 1 激励源"
        wr_name = next(
            ln.split()[1] for ln in text.splitlines() if ln.strip().startswith("wrdata")
        )
        freqs = [
            float(ln.split()[3])
            for ln in text.splitlines()
            if ln.strip().startswith("ac lin 1 ")
        ]
        self.calls.append({"excited_port": exc, "wrdata": wr_name, "n_freq": len(freqs)})
        if exc in self.fail_ports:
            return {
                "stdout": "Error: Unknown circuit device",
                "stderr": "",
                "returncode": 0,
                "errors": ["Error: Unknown circuit device"],
            }
        if self.skip_write:
            return {"stdout": "", "stderr": "", "returncode": 0, "errors": []}
        lines = []
        for k, f in enumerate(freqs):
            cells: list[float] = []
            for i in range(self.y.shape[1]):
                iv = -self.y[k, i, exc]
                cells += [f, iv.real, iv.imag]
            lines.append(" " + "  ".join(f"{c:.17g}" for c in cells))
        (deck_path.parent / wr_name).write_text("\n".join(lines) + "\n", encoding="ascii")
        return {"stdout": "", "stderr": "", "returncode": 0, "errors": []}


# --------------------------------------------------------------------------- #
# 1. 端到端编排（替身）：fit 导出 → xval 真跑管道 → FSV 评级
# --------------------------------------------------------------------------- #

def test_xval_end_to_end_with_stub_matches_closed_form(tmp_path, monkeypatch) -> None:
    freq = _freq()
    s_orig = _closed_form_s(freq)
    sp = tmp_path / "model.sp"
    fit_macromodel({
        "freq_hz": freq.tolist(),
        "s": [[[[float(v.real), float(v.imag)] for v in row] for row in mat] for mat in s_orig],
        "z0": [Z0, Z0],
        "spice_path": str(sp),
        "subckt_name": "m2",
    })
    stub = _NgspiceStub(_closed_form_y(freq))
    monkeypatch.setattr(sn, "run_ngspice", stub)

    x = sn.xval_macromodel_spice(s_orig, freq, sp, z0=[Z0, Z0], work_dir=tmp_path / "xv")
    assert x["status"] == "ok"
    assert x["verifier"] == sn.XVAL_VERIFIER_NGSPICE_AC
    assert x["n_ports"] == 2 and x["n_points"] == int(freq.size)
    assert [c["excited_port"] for c in stub.calls] == [0, 1]  # 逐端口各跑一次
    assert all(c["n_freq"] == int(freq.size) for c in stub.calls)
    # 验收判据：对拍 S vs 原始 S 的 FSV GDM 等级下标 ≤ 2（≥Good）
    assert x["worst_gdm_grade"] in GRADE_CODES
    assert grade_index_of(float(x["fsv"]["per_response"]["s11"]["gdm_mean"])) <= GRADE_INDEX_GOOD
    assert x["gdm_at_least_good"] is True
    # 闭式替身下对拍误差 = 拟合残差（机器精度级）
    assert x["xval_vs_reference"]["max_abs"] < 1e-10
    # 结果 JSON 原生（可 json.dumps）且随结果带对拍 S 矩阵
    import json

    assert json.loads(json.dumps(x)) == x
    assert np.asarray(x["s"]).shape == (int(freq.size), 2, 2, 2)


def test_xval_uses_replay_same_port_layout_and_z0(tmp_path, monkeypatch) -> None:
    """xval 的端口布局/z0 推断与回放自检同口径（同为 R1..RN 推断）。"""
    freq = _freq(n=17)
    s_orig = _closed_form_s(freq)
    sp = _write_dut(tmp_path)  # 无 R<i> 参考电阻 → 显式 z0；缺 z0 时两侧同样报错
    stub = _NgspiceStub(_closed_form_y(freq))
    monkeypatch.setattr(sn, "run_ngspice", stub)
    x = sn.xval_macromodel_spice(s_orig, freq, sp, work_dir=tmp_path / "xv")
    assert x["status"] == "error"  # 网表无 R1..R2 且未显式 z0 → 与回放自检同样显式拒绝
    assert "参考阻抗" in x["error"] or "z0" in x["error"]


def test_xval_passes_through_replay_equivalent_errors(tmp_path) -> None:
    """与回放自检口径一致性：同一坏网表，replay 与 xval 都显式拒绝。"""
    freq = _freq(n=17)
    sp = tmp_path / "bad.sp"
    sp.write_text(".SUBCKT d p1\n.options reltol=1e-4\nR1 p1 0 50\n.ENDS d\n", encoding="ascii")
    x = sn.xval_macromodel_spice(
        np.zeros((freq.size, 1, 1), dtype=complex), freq, sp, work_dir=tmp_path / "xv"
    )
    assert x["status"] == "error"
    assert "未知指令" in x["error"]
    with pytest.raises(Exception, match="未知指令"):
        replay_spice_subcircuit_s(sp, freq, z0=Z0)


# --------------------------------------------------------------------------- #
# 2. 失败语义（#105/#122：best-effort + 如实，绝不抛、绝不伪造通过）
# --------------------------------------------------------------------------- #

def test_xval_ngspice_error_recorded_as_error_status(tmp_path, monkeypatch) -> None:
    freq = _freq(n=17)
    sp = _write_dut(tmp_path)
    stub = _NgspiceStub(_closed_form_y(freq), fail_ports={1})
    monkeypatch.setattr(sn, "run_ngspice", stub)
    x = sn.xval_macromodel_spice(
        _closed_form_s(freq), freq, sp, z0=[Z0, Z0], work_dir=tmp_path / "xv"
    )
    assert x["status"] == "error"
    assert "端口 2" in x["error"]
    assert x["gdm_at_least_good"] is False


def test_xval_missing_wrdata_recorded_as_error_status(tmp_path, monkeypatch) -> None:
    freq = _freq(n=17)
    sp = _write_dut(tmp_path)
    stub = _NgspiceStub(_closed_form_y(freq), skip_write=True)
    monkeypatch.setattr(sn, "run_ngspice", stub)
    x = sn.xval_macromodel_spice(
        _closed_form_s(freq), freq, sp, z0=[Z0, Z0], work_dir=tmp_path / "xv"
    )
    assert x["status"] == "error"
    assert "wrdata" in x["error"]


def test_xval_freq_axis_mismatch_recorded_as_error_status(tmp_path, monkeypatch) -> None:
    """替身频轴与请求轴不一致（模拟 $& 量化类漂移）→ 显式 error，不静默配对。"""
    freq = _freq(n=17)
    sp = _write_dut(tmp_path)
    monkeypatch.setattr(sn, "run_ngspice", _NgspiceStub(_closed_form_y(freq)))

    orig_parse = sn.parse_ngspice_wrdata_ac

    def _drift_parse(text, *, n_vectors=None):
        f, v = orig_parse(text, n_vectors=n_vectors)
        return f * (1.0 + 1e-6), v  # 3.6ppm 量级漂移（$& 量化坑的模拟）

    monkeypatch.setattr(sn, "parse_ngspice_wrdata_ac", _drift_parse)
    x = sn.xval_macromodel_spice(
        _closed_form_s(freq), freq, sp, z0=[Z0, Z0], work_dir=tmp_path / "xv"
    )
    assert x["status"] == "error"
    assert "频率轴" in x["error"]


def test_xval_too_few_points_recorded_as_error_status(tmp_path, monkeypatch) -> None:
    """FSV 需要 ≥16 点：不足时 error（compare_s_matrices 下限，不静默降级）。"""
    freq = np.linspace(1e9, 2e9, MIN_FREQ_POINTS - 1)
    sp = _write_dut(tmp_path)
    monkeypatch.setattr(sn, "run_ngspice", _NgspiceStub(_closed_form_y(freq)))
    x = sn.xval_macromodel_spice(
        _closed_form_s(freq), freq, sp, z0=[Z0, Z0], work_dir=tmp_path / "xv"
    )
    assert x["status"] == "error"
    assert str(MIN_FREQ_POINTS) in x["error"] or "MIN_POINTS" in x["error"]


def test_xval_missing_binary_recorded_as_error_status(tmp_path, monkeypatch) -> None:
    freq = _freq(n=17)
    sp = _write_dut(tmp_path)

    def _no_exe(sub, f, z, *, work_dir, exe=None, timeout_s=300.0, **kw):
        raise FileNotFoundError("未找到 ngspice 可执行文件；可设 RFAUTO_NGSPICE_BIN")

    monkeypatch.setattr(sn, "run_ngspice_ac_sparam", _no_exe)
    x = sn.xval_macromodel_spice(
        _closed_form_s(freq), freq, sp, z0=[Z0, Z0], work_dir=tmp_path / "xv"
    )
    assert x["status"] == "error"
    assert "FileNotFoundError" in x["error"]
    assert x["gdm_at_least_good"] is False


# --------------------------------------------------------------------------- #
# 3. 电阻硬下限改写（ngspice-47 钳位对策的编排面）
# --------------------------------------------------------------------------- #

def test_run_ac_sparam_records_resistor_rewrite(tmp_path, monkeypatch) -> None:
    """含 <1e-12Ω 泄漏电阻的网表：改写进 dut.sp 副本且逐条记账；MNA 等价由
    replay 对拍（rewritten vs 原）为 0 钉死（见 adapters 模块 docstring）。"""
    freq = _freq(n=17)
    sp = tmp_path / "leak.sp"
    sp.write_text(
        ".SUBCKT leak p1 p2\n"
        "Rp1 0 xa 4.311356730512539e-24\n"
        "R1 p1 m 3.0\n"
        "L1 m p2 3e-9\n"
        ".ENDS leak\n",
        encoding="ascii",
    )
    stub = _NgspiceStub(_closed_form_y(freq))
    monkeypatch.setattr(sn, "run_ngspice", stub)
    res = sn.run_ngspice_ac_sparam(sp, freq, [Z0, Z0], work_dir=tmp_path / "wd")
    rw = res["resistor_rewrite"]
    assert rw["enabled"] is True and rw["n_rewritten"] == 1
    assert rw["items"][0]["name"] == "Rp1"
    assert rw["items"][0]["value_ohm"] == pytest.approx(4.311356730512539e-24)
    dut_text = (tmp_path / "wd" / "dut.sp").read_text(encoding="ascii")
    assert "Rp1 0 xa 4.311356730512539e-24" not in dut_text
    assert "Grw_Rp1 0 xa 0 xa" in dut_text
    # 关闭改写：原样复制（此时 ngspice 会钳位——由真机门/警告面暴露，不在此重复）
    res2 = sn.run_ngspice_ac_sparam(
        sp, freq, [Z0, Z0], work_dir=tmp_path / "wd2", rewrite_small_resistors=False
    )
    assert res2["resistor_rewrite"]["n_rewritten"] == 0
    assert "Rp1 0 xa 4.311356730512539e-24" in (tmp_path / "wd2" / "dut.sp").read_text(encoding="ascii")


# --------------------------------------------------------------------------- #
# 4. 回放自检与第三方对拍的措辞边界（两条证据链不得混同）
# --------------------------------------------------------------------------- #

def test_two_evidence_chains_are_distinctly_worded(tmp_path, monkeypatch) -> None:
    """回放自检 disclaimer 含『回放自检』+『不是』；xval note 声明 third-party 且
    与回放自检相互独立——调用方不可能把 status==ok 误读成另一条链。"""
    freq = _freq(n=17)
    sp = _write_dut(tmp_path)
    monkeypatch.setattr(sn, "run_ngspice", _NgspiceStub(_closed_form_y(freq)))
    x = sn.xval_macromodel_spice(
        _closed_form_s(freq), freq, sp, z0=[Z0, Z0], work_dir=tmp_path / "xv"
    )
    rep = replay_spice_subcircuit_s(sp, freq, z0=Z0)
    assert "回放自检" in rep["disclaimer"] and "不是" in rep["disclaimer"]
    assert "第三方" in x["note"] and "独立" in x["note"]
    assert rep["solver"] != x["verifier"]
    assert x["verifier"] == "third_party_ngspice_ac"
    assert rep["solver"].startswith("rfauto-core")
