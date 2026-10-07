"""netlist/ffs 行文法 fuzz（round3 附带三件之三扩面，E 类台账
plan_gap_e_tail_20260929 §三.3 残余池销账：Touchstone 已落，本件补
netlist+ffs 两文法）。

覆盖面（与既有 test_touchstone_fuzz.py 同 FUZZ 预算惯例：derandomize +
max_examples=20，控单元门预算）：

- ADS 网表写端（adapters/ads_netlist.generate_netlist）：占位符全替换、
  Port 块、SnP ``File=`` 指向真实存在的绝对路径（#276 自包含面）、
  SweepPlan 数值 %g 往返、双次渲染逐字节幂等；
- SPICE 网表写端（adapters/spice_netlist.render_ngspice_netlist）：元件行
  文法（前缀计数=circuit 顺序、数值 .12g 往返、零归一 "0"）、V 源
  SIN TD 相位换算自洽（td·f0·360 = −(phase+90)）+ ngspice-45.2 实测
  独立锚（test_td_phase_conversion_ngspice_measured_anchor，证据
  runs/spice_td_anchor_20260929）、结构行
  （.tran/.four/.meas/.end）、双次渲染逐字节幂等；
- netlist 链输出行文法（spice_netlist.parse_ngspice_wrdata_ac）：策略生成
  wrdata 文本→解析**精确**回收（repr 全精度逐位）+ 结构负例（行列残缺/
  频率列不一致/非数值令牌/非 3 倍列/空输出/n_vectors 不符）显式
  NgspiceAcError（#316 方向：坏结构宁可显式失败）；
- .ffs ASCII 行文法（core/nf_transform.read_ffs）：策略生成频块→头/三功率/
  频率/角轴/复矩阵逐位回收 + freq_index 选块 + 结构负例（头缺失/频块数
  非法/网格头数不符/行序违例/跨块轴不一致/数据行不足）显式 ValueError。

#118 纪律：回收钉只对"策略生成→解析"往返做（真值=策略参数），不自我推导
物理量。atheris Windows NO-GO 维持（hypothesis 库内 fuzz）。
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Any

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from rfauto.adapters import ads_netlist as ads
from rfauto.adapters import spice_netlist as sp
from rfauto.core import nf_transform as nf
from rfauto.core.circuit_hb import (
    HBCapacitor,
    HBCircuit,
    HBDiode,
    HBInductor,
    HBResistor,
    HBVSource,
)

FUZZ = settings(
    derandomize=True,
    deadline=None,
    max_examples=20,
    suppress_health_check=[HealthCheck.too_slow],
)

_ST_COMPLEX = st.tuples(st.floats(-1.0, 1.0), st.floats(-1.0, 1.0)).map(
    lambda t: complex(t[0], t[1])
)

_KIND_BY_CLASS = {
    "HBResistor": "R",
    "HBCapacitor": "C",
    "HBInductor": "L",
    "HBDiode": "D",
    "HBVSource": "V",
}


def _assert_num_roundtrip(token: str, expected: float, *, rtol: float = 1e-10) -> None:
    """数值 token 往返钉：零值必须字面 "0"，非零按相对容差回收。"""
    if expected == 0.0:
        assert token == "0", f"零值 token 应归一为 '0'，得到 {token!r}"
        return
    got = float(token)
    assert got == pytest.approx(expected, rel=rtol), f"{token!r} vs {expected!r}"


# ---------------------------------------------------------------------------
# 1) ADS 网表写端文法 fuzz（generate_netlist）
# ---------------------------------------------------------------------------

@st.composite
def _ads_spec(draw: st.DrawFn) -> dict[str, Any]:
    n_ports = draw(st.sampled_from([1, 2, 3]))
    n_freq = draw(st.integers(min_value=2, max_value=8))
    start = draw(st.floats(0.1, 5.0))
    ratio = draw(st.floats(1.01, 2.0))
    f_ghz = [start * ratio**i for i in range(n_freq)]
    return {"n_ports": n_ports, "f_ghz": f_ghz}


def _write_snp(td: str, n_ports: int, f_ghz: list[float]) -> str:
    """手写最小 RI Touchstone（列主序 S 行序；#248 扩展名-rank 契约）。"""
    path = os.path.join(td, f"gen.s{n_ports}p")
    lines = ["! fuzz ads netlist case", "# GHZ S RI R 50"]
    for k, f in enumerate(f_ghz):
        toks = [repr(float(f))]
        for m in range(n_ports * n_ports):
            toks += [repr(round(0.1 * (m + 1) * (k + 1), 9)), repr(0.05)]
        lines.append(" ".join(toks))
    with open(path, "w", encoding="ascii") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


_ADS_TEMPLATE = """Options ResourceUsage=yes
S_Param:SP1 SweepVar="freq" SweepPlan="SP1_stim"
SweepPlan: SP1_stim Start={{FSTART}} {{FREQ_UNIT}} Stop={{FSTOP}} {{FREQ_UNIT}} Lin={{NPOINTS}}
{{PORTS}}
{{SNP_LINE}}
"""


class TestAdsNetlistGrammarFuzz:
    @given(_ads_spec())
    @FUZZ
    def test_placeholders_and_idempotent(self, spec: dict[str, Any]):
        n = spec["n_ports"]
        f_ghz = spec["f_ghz"]
        with tempfile.TemporaryDirectory() as td:
            snp = _write_snp(td, n, f_ghz)
            tpl = os.path.join(td, "tpl.net")
            with open(tpl, "w", encoding="ascii") as fh:
                fh.write(_ADS_TEMPLATE)
            p1 = ads.generate_netlist(tpl, snp, os.path.join(td, "a.net"))
            p2 = ads.generate_netlist(tpl, snp, os.path.join(td, "b.net"))
            text1 = p1.read_text(encoding="ascii")
            # 不变量 A：双次渲染逐字节幂等（同输入无墙钟/无随机面）
            assert text1 == p2.read_text(encoding="ascii")
            # 不变量 B：占位符全替换
            assert "{{" not in text1 and "}}" not in text1
            # 不变量 C：Port 块恰 N 行、编号/Z 连续合法
            for i in range(1, n + 1):
                assert f"Port:P{i}" in text1
                assert f"Num={i} Z=50 Ohm" in text1
            assert len(re.findall(r"Port:P\d+", text1)) == n
            # 不变量 D：SnP 行 NumPorts=N 且 File= 指向真实存在的绝对路径
            # （#276 面：File= 写绝对路径，网表自包含可达）
            m = re.search(r'NumPorts=(\d+) File="([^"]+)"', text1)
            assert m is not None
            assert int(m.group(1)) == n
            file_field = m.group(2)
            assert os.path.isabs(file_field)
            assert os.path.isfile(file_field)
            assert os.path.samefile(file_field, snp)
            # 不变量 E：SweepPlan 数值 %g 往返（真值=策略频率，非 skrf 内部）
            fstart_hz = min(f_ghz) * 1e9
            fstop_hz = max(f_ghz) * 1e9
            m2 = re.search(r"Start=(\S+) (\S+) Stop=(\S+) (\S+) Lin=(\d+)", text1)
            assert m2 is not None
            assert m2.group(2) == "GHz" and m2.group(4) == "GHz"  # 无契约缺省单位
            assert float(m2.group(1)) * 1e9 == pytest.approx(fstart_hz, rel=1e-5)
            assert float(m2.group(3)) * 1e9 == pytest.approx(fstop_hz, rel=1e-5)
            assert int(m2.group(5)) == len(f_ghz)


# ---------------------------------------------------------------------------
# 2) SPICE 网表写端文法 fuzz（render_ngspice_netlist）
# ---------------------------------------------------------------------------

@st.composite
def _circuit_spec(draw: st.DrawFn) -> dict[str, Any]:
    n_nodes = draw(st.integers(min_value=3, max_value=6))
    f0 = draw(st.floats(1e6, 1e10))
    elem_kinds = draw(
        st.lists(st.sampled_from(["R", "C", "L", "D", "V"]), min_size=1, max_size=6)
    )
    elements: list[Any] = []
    for kind in elem_kinds:
        a = draw(st.integers(0, n_nodes - 1))
        b = draw(st.integers(0, n_nodes - 1))
        if a == b:
            b = (a + 1) % n_nodes
        if kind == "R":
            elements.append(HBResistor(a, b, draw(st.floats(0.01, 1e6))))
        elif kind == "C":
            elements.append(HBCapacitor(a, b, draw(st.floats(1e-15, 1e-9))))
        elif kind == "L":
            elements.append(HBInductor(a, b, draw(st.floats(1e-12, 1e-6))))
        elif kind == "D":
            elements.append(
                HBDiode(a, b, draw(st.floats(1e-12, 1e-6)), draw(st.floats(0.5, 2.0)))
            )
        else:
            elements.append(
                HBVSource(
                    a,
                    b,
                    draw(st.floats(-5.0, 5.0)),
                    draw(st.floats(0.01, 10.0)),
                    phase_deg=draw(st.floats(-360.0, 360.0)),
                )
            )
    tstop = draw(st.floats(1e-9, 1e-6))
    tmax = tstop * draw(st.floats(0.01, 1.0))
    has_tstep = draw(st.booleans())
    tstep = tmax * draw(st.floats(0.1, 1.0)) if has_tstep else None
    meas_names = draw(st.lists(st.sampled_from(["m0", "m1", "m2"]), max_size=2))
    meas_avg = {
        nm: f"n{draw(st.integers(1, n_nodes - 1))}"
        for nm in dict.fromkeys(meas_names)
    }
    non_ground = [f"n{i}" for i in range(1, n_nodes)]
    four_mode = draw(st.sampled_from(["default", "subset", "empty"]))
    if four_mode == "subset":
        picked = draw(
            st.lists(st.sampled_from(non_ground), max_size=len(non_ground))
        )
        four_nodes: list[str] | None = list(dict.fromkeys(picked))
    elif four_mode == "empty":
        four_nodes = []
    else:
        four_nodes = None
    circuit = HBCircuit(n_nodes=n_nodes, f0_hz=f0)
    for el in elements:
        circuit.add(el)
    return {
        "circuit": circuit,
        "node_names": ["0", *non_ground],
        "f0": f0,
        "tstop": tstop,
        "tmax": tmax,
        "tstep": tstep,
        "meas_avg": meas_avg,
        "four_nodes": four_nodes,
        "elements": elements,
    }


class TestSpiceNetlistGrammarFuzz:
    @given(_circuit_spec())
    @FUZZ
    def test_element_grammar_and_idempotent(self, spec: dict[str, Any]):
        circuit = spec["circuit"]
        node_set = set(spec["node_names"])
        meas_avg = spec["meas_avg"] if spec["meas_avg"] else None
        render_kwargs: dict[str, Any] = dict(
            tstop_s=spec["tstop"],
            tmax_s=spec["tmax"],
            tstep_s=spec["tstep"],
            meas_avg=meas_avg,
            four_nodes=spec["four_nodes"],
        )
        with tempfile.TemporaryDirectory() as td:
            p1 = sp.render_ngspice_netlist(
                circuit, os.path.join(td, "a.cir"), spec["node_names"], **render_kwargs
            )
            p2 = sp.render_ngspice_netlist(
                circuit, os.path.join(td, "b.cir"), spec["node_names"], **render_kwargs
            )
            text = p1.read_text(encoding="ascii")
            # 不变量 A：双次渲染逐字节幂等
            assert text == p2.read_text(encoding="ascii")
            lines = text.splitlines()
            # 不变量 B：结构行（标题/.options/.../.end 收尾）
            assert lines[0].startswith("* ")
            assert lines[1].startswith(".options")
            assert lines[-1] == ".end"
            # 不变量 C：元件行前缀计数=circuit 顺序计数，数值 .12g 往返
            elem_lines = [ln for ln in lines if ln and ln[0] in "RCLVD"]
            by_kind: dict[str, list[list[str]]] = {}
            for ln in elem_lines:
                toks = ln.split()
                by_kind.setdefault(toks[0][0], []).append(toks)
                assert toks[1] in node_set and toks[2] in node_set
            expected: dict[str, list[Any]] = {"R": [], "C": [], "L": [], "D": [], "V": []}
            for el in spec["elements"]:
                expected[_KIND_BY_CLASS[type(el).__name__]].append(el)
            for kind, els in expected.items():
                assert len(by_kind.get(kind, [])) == len(els), kind
            for i, el in enumerate(expected["R"]):
                _assert_num_roundtrip(by_kind["R"][i][3], el.resistance)
            for i, el in enumerate(expected["C"]):
                _assert_num_roundtrip(by_kind["C"][i][3], el.capacitance)
            for i, el in enumerate(expected["L"]):
                _assert_num_roundtrip(by_kind["L"][i][3], el.inductance)
            # 二极管：模型行 Is/N 往返（尾括号剥离）+ 元件引用对应模型名
            for i, el in enumerate(expected["D"]):
                toks = by_kind["D"][i]
                assert toks[3] == f"DMOD{i + 1}"
                model_line = next(
                    ln for ln in lines if ln.startswith(f".model DMOD{i + 1} ")
                )
                is_tok = model_line.split("Is=")[1].split()[0]
                n_tok = model_line.split("N=")[1].split()[0].rstrip(")")
                _assert_num_roundtrip(is_tok, el.is_sat)
                _assert_num_roundtrip(n_tok, el.emission_n)
            # 电压源：DC/SIN(0 amp f0 td) 文法 + TD 相位换算自洽
            for i, el in enumerate(expected["V"]):
                toks = by_kind["V"][i]
                assert toks[3] == "DC" and toks[5] == "SIN(0"
                _assert_num_roundtrip(toks[4], el.dc)
                _assert_num_roundtrip(toks[6], el.amp)
                _assert_num_roundtrip(toks[7], spec["f0"])
                td_tok = toks[8].rstrip(")")
                td_expected = -((el.phase_deg + 90.0) / 360.0) / spec["f0"]
                _assert_num_roundtrip(td_tok, td_expected)
                # 换算自洽：td·f0·360 = −(phase+90)（余弦参考口径）
                td_val = float(td_tok)
                f0_val = float(toks[7])
                assert td_val * f0_val * 360.0 == pytest.approx(
                    -(el.phase_deg + 90.0), abs=1e-6
                )
            # 不变量 D：.tran 四数值往返（tstep 缺省=tmax；#117：显式判 None）
            tran_toks = next(ln for ln in lines if ln.startswith(".tran ")).split()
            eff_tstep = spec["tstep"] if spec["tstep"] is not None else spec["tmax"]
            _assert_num_roundtrip(tran_toks[1], eff_tstep)
            _assert_num_roundtrip(tran_toks[2], spec["tstop"])
            _assert_num_roundtrip(tran_toks[3], 0.0)
            _assert_num_roundtrip(tran_toks[4], spec["tmax"])
            # 不变量 E：.four 基频与节点清单；.meas 窗口往返
            four_eff = spec["four_nodes"]
            if four_eff is None:
                four_eff = spec["node_names"][1:]
            four_line = next((ln for ln in lines if ln.startswith(".four ")), None)
            if four_eff:
                assert four_line is not None
                ftoks = four_line.split()
                _assert_num_roundtrip(ftoks[1], spec["f0"])
                assert ftoks[2:] == [f"v({nm})" for nm in four_eff]
            else:
                assert four_line is None
            win = spec["tstop"] / 2.0
            for name in (meas_avg or {}):
                meas_line = next(
                    ln for ln in lines if ln.startswith(f".meas tran {name} ")
                )
                _assert_num_roundtrip(meas_line.split("from=")[1].split()[0], win)
                _assert_num_roundtrip(meas_line.split("to=")[1].split()[0], spec["tstop"])

    def test_td_phase_conversion_ngspice_measured_anchor(self):
        """TD 相位换算的独立实测锚（review-slice4 P2-3，#118 口径）。

        自洽钉（td·f0·360=−(phase+90) 由实现公式恒等推出）之上补独立来源：
        一次性真跑对拍（2026-09-29，WSL ngspice-45.2 batch，证据存档
        runs/spice_td_anchor_20260929/：网表+wrdata 波形+anchor_result.json）。
        方法=按写端公式 TD=−((phase+90)/360)/f0 写 SIN(0 1 1e6 TD)→tran
        40µs→LS 投影回收 cos 参考相位（v≈a·cosθ+b·sinθ，φ=atan2(−b,a)，
        t≥4T 共 2305 点，幅值回收 1.0、rms 残差 ~3e-10）。实测：0/45/−90°
        逐位相等；180° 回收 −180°（atan2 值域 (−180,180] 等价角）。
        本钉三条：①写端公式仍发射经实验验证的 TD；②独立引擎真值相位
        ≡请求相位（mod 360）；③锚挂在真实 render 输出上（SIN TD token）。
        运行环境无关：不依赖 WSL/ngspice 在装（真跑为一次性锚定实验）。
        """
        f0 = 1e6
        # (phase_deg, 实验验证 TD s, ngspice 实测 cos 参考相位 deg)
        archived = [
            (0.0, -2.5e-07, 0.0),
            (45.0, -3.75e-07, 45.0),
            (-90.0, -0.0, -90.0),
            (180.0, -7.5e-07, -180.0),
        ]
        for ph, td_validated, phi_measured in archived:
            # ① 写端公式 = 实验验证值（公式被改=与实测锚脱钩当场红）
            assert -((ph + 90.0) / 360.0) / f0 == td_validated
            # ② 独立引擎真值：实测相位 ≡ 请求相位（mod 360；−180≡180）
            assert (phi_measured - ph) % 360.0 == pytest.approx(0.0, abs=1e-6)
            # ③ 真实 render 的 SIN(...) TD token == 实验验证值（锚接写端）
            circuit = HBCircuit(n_nodes=2, f0_hz=f0)
            circuit.add(HBVSource(0, 1, 0.0, 1.0, phase_deg=ph))
            with tempfile.TemporaryDirectory() as td:
                path = sp.render_ngspice_netlist(
                    circuit, os.path.join(td, "anchor.cir"), ["0", "n1"],
                    tstop_s=4e-6, tmax_s=1e-9, title="td anchor probe")
                vline = next(
                    ln for ln in path.read_text(encoding="ascii").splitlines()
                    if ln.startswith("V1 "))
                td_tok = vline.split("SIN(0")[1].split()[2].rstrip(")")
                assert float(td_tok) == pytest.approx(
                    td_validated, rel=1e-10, abs=1e-18)


# ---------------------------------------------------------------------------
# 3) wrdata AC 输出行文法 fuzz（parse_ngspice_wrdata_ac）
# ---------------------------------------------------------------------------

@st.composite
def _wrdata_spec(draw: st.DrawFn) -> dict[str, Any]:
    n_vec = draw(st.integers(min_value=1, max_value=4))
    n_rows = draw(st.integers(min_value=1, max_value=10))
    start = draw(st.floats(1e6, 1e9))
    ratio = draw(st.floats(1.01, 2.0))
    freqs = [start * ratio**i for i in range(n_rows)]
    vals = [
        [draw(_ST_COMPLEX) * draw(st.sampled_from([1.0, 1e3])) for _ in range(n_vec)]
        for _ in range(n_rows)
    ]
    blanks = draw(st.lists(st.integers(0, n_rows), min_size=1, max_size=3))
    return {"n_vec": n_vec, "freqs": freqs, "vals": vals, "blanks": set(blanks)}


def _wrdata_text(spec: dict[str, Any]) -> str:
    lines: list[str] = []
    for r, f in enumerate(spec["freqs"]):
        if r in spec["blanks"]:
            lines.append("")  # 空行噪声=**追加**，不吞数据行
        row = []
        for v in range(spec["n_vec"]):
            z = complex(spec["vals"][r][v])
            row += [repr(float(f)), repr(z.real), repr(z.imag)]
        lines.append(" ".join(row))
    return "\n".join(lines) + "\n"


class TestWrdataGrammarFuzz:
    @given(_wrdata_spec())
    @FUZZ
    def test_parse_exact_roundtrip(self, spec: dict[str, Any]):
        freq, vals = sp.parse_ngspice_wrdata_ac(
            _wrdata_text(spec), n_vectors=spec["n_vec"]
        )
        # repr 全精度 → 解析逐位相等（#287 族口径的 RI 全精度路）
        assert np.array_equal(freq, np.array(spec["freqs"], dtype=float))
        # 解析契约=values[n_vec, n_rows]（docstring 口径）；策略面按 [行][向量] 生成
        expected = np.array(spec["vals"], dtype=complex).T
        assert np.array_equal(vals, expected)

    def test_structural_negatives_fail_loud(self):
        good = "1e9 1.0 0.5\n2e9 0.5 -0.25\n"
        # 空输出
        with pytest.raises(sp.NgspiceAcError, match="为空"):
            sp.parse_ngspice_wrdata_ac("")
        # 行列残缺（首行 6 列、次行 3 列）
        with pytest.raises(sp.NgspiceAcError, match="列数"):
            sp.parse_ngspice_wrdata_ac(good + "3e9 1.0\n")
        # 非数值令牌
        with pytest.raises(sp.NgspiceAcError, match="非数值令牌"):
            sp.parse_ngspice_wrdata_ac("1e9 1.0 abc\n")
        # 非 3 倍列数
        with pytest.raises(sp.NgspiceAcError, match="3 的倍数"):
            sp.parse_ngspice_wrdata_ac("1e9 1.0\n")
        # 跨向量频率列不一致（#316 方向：显式报错不静默）
        with pytest.raises(sp.NgspiceAcError, match="不一致"):
            sp.parse_ngspice_wrdata_ac("1e9 1.0 0.0 2e9 0.5 0.5\n")
        # n_vectors 不符
        with pytest.raises(sp.NgspiceAcError, match="向量数"):
            sp.parse_ngspice_wrdata_ac(good, n_vectors=3)


# ---------------------------------------------------------------------------
# 4) .ffs ASCII 行文法 fuzz（core/nf_transform.read_ffs）
# ---------------------------------------------------------------------------

@st.composite
def _ffs_spec(draw: st.DrawFn) -> dict[str, Any]:
    n_freq = draw(st.integers(min_value=1, max_value=2))
    n_phi = draw(st.integers(min_value=1, max_value=3))
    n_theta = draw(st.integers(min_value=1, max_value=3))
    phi = sorted(
        draw(st.lists(st.integers(0, 359), unique=True, min_size=n_phi, max_size=n_phi))
    )
    theta = sorted(
        draw(
            st.lists(
                st.integers(0, 179), unique=True, min_size=n_theta, max_size=n_theta
            )
        )
    )
    start = draw(st.floats(1e9, 1e10))
    ratio = draw(st.floats(1.01, 1.5))
    freqs = [start * ratio**i for i in range(n_freq)]
    powers = [[draw(st.floats(0.01, 10.0)) for _ in range(3)] for _ in range(n_freq)]
    e_th = [
        [[draw(_ST_COMPLEX) for _ in range(n_theta)] for _ in range(n_phi)]
        for _ in range(n_freq)
    ]
    e_ph = [
        [[draw(_ST_COMPLEX) for _ in range(n_theta)] for _ in range(n_phi)]
        for _ in range(n_freq)
    ]
    noise = draw(
        st.lists(st.sampled_from(["// noise", "", "// fuzz marker"]), max_size=2)
    )
    return {
        "n_freq": n_freq,
        "phi": [float(v) for v in phi],
        "theta": [float(v) for v in theta],
        "freqs": freqs,
        "powers": powers,
        "e_th": e_th,
        "e_ph": e_ph,
        "noise": noise,
    }


def _ffs_text(spec: dict[str, Any], *, theta_axis_shift: float = 0.0) -> str:
    lines: list[str] = ["// fuzz ffs case"]
    lines += spec["noise"]
    lines.append("// #Frequencies (Hz)")
    lines.append(repr(float(spec["n_freq"])))
    lines.append("// Radiated/Accepted/Stimulated Power (W)")
    for k in range(spec["n_freq"]):
        for p in spec["powers"][k]:
            lines.append(repr(float(p)))
        lines.append(repr(float(spec["freqs"][k])))
    for k in range(spec["n_freq"]):
        lines.append("// >> Total #phi samples")
        lines.append(f"{len(spec['phi'])} {len(spec['theta'])}")
        lines.append("// >> Phi, Theta")
        for i_phi, ph in enumerate(spec["phi"]):
            for i_th, th in enumerate(spec["theta"]):
                th_eff = th + (theta_axis_shift if k == 1 else 0.0)
                zt = complex(spec["e_th"][k][i_phi][i_th])
                zp = complex(spec["e_ph"][k][i_phi][i_th])
                lines.append(
                    f"{ph!r} {th_eff!r} {zt.real!r} {zt.imag!r} "
                    f"{zp.real!r} {zp.imag!r}"
                )
    return "\n".join(lines) + "\n"


class TestFfsGrammarFuzz:
    @given(_ffs_spec())
    @FUZZ
    def test_read_exact_roundtrip(self, spec: dict[str, Any]):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "gen.ffs")
            with open(path, "w", encoding="ascii") as fh:
                fh.write(_ffs_text(spec))
            out = nf.read_ffs(path)
            # 逐位回收（repr 全精度：头/三功率/频率/角轴/复矩阵）
            assert out["ok"] is True
            assert out["n_freq"] == spec["n_freq"]
            assert out["frequencies_hz"] == spec["freqs"]
            assert out["power_radiated_accepted_stimulated"] == spec["powers"]
            np.testing.assert_array_equal(
                np.asarray(out["phi_deg"]), np.array(spec["phi"])
            )
            np.testing.assert_array_equal(
                np.asarray(out["theta_deg"]), np.array(spec["theta"])
            )
            np.testing.assert_array_equal(
                np.asarray(out["e_theta"]), np.array(spec["e_th"], dtype=complex)
            )
            np.testing.assert_array_equal(
                np.asarray(out["e_phi"]), np.array(spec["e_ph"], dtype=complex)
            )
            assert out["row_order"] == "phi_outer_theta_inner"
            # freq_index 选块=全读对应块
            for k in range(spec["n_freq"]):
                sub = nf.read_ffs(path, freq_index=k)
                np.testing.assert_array_equal(
                    np.asarray(sub["e_theta"]), np.asarray(out["e_theta"])[k]
                )

    def test_structural_negatives_fail_loud(self):
        spec = {
            "n_freq": 1,
            "phi": [0.0, 90.0],
            "theta": [0.0, 45.0, 90.0],
            "freqs": [2.4e9],
            "powers": [[1.0, 0.1, 2.0]],
            "e_th": [[[complex(1, 0)] * 3] * 2],
            "e_ph": [[[complex(0, 1)] * 3] * 2],
            "noise": [],
        }

        def read(text: str) -> dict[str, Any]:
            with tempfile.TemporaryDirectory() as td:
                p = os.path.join(td, "x.ffs")
                with open(p, "w", encoding="ascii") as fh:
                    fh.write(text)
                return nf.read_ffs(p)

        with pytest.raises(ValueError, match="未找到"):
            read(_ffs_text(spec).replace("// #Frequencies", "// Frequencies"))
        with pytest.raises(ValueError, match="非法"):
            # n_freq 首值行改 0 → 频块数非法
            lines = _ffs_text(spec).splitlines()
            lines[lines.index("// #Frequencies (Hz)") + 1] = "0.0"
            read("\n".join(lines) + "\n")
        with pytest.raises(ValueError, match="数据行不足"):
            read("\n".join(_ffs_text(spec).splitlines()[:-1]) + "\n")
        two = dict(
            spec,
            n_freq=2,
            freqs=[2.4e9, 4.8e9],
            powers=[[1.0, 0.1, 2.0]] * 2,
            e_th=[spec["e_th"][0]] * 2,
            e_ph=[spec["e_ph"][0]] * 2,
        )
        # 网格头数量 ≠ 频块数（两频块删一个网格头三元组）
        full_lines = _ffs_text(two).splitlines()
        i = full_lines.index("// >> Total #phi samples")
        del full_lines[i : i + 3]
        with pytest.raises(ValueError, match="网格头数量"):
            read("\n".join(full_lines) + "\n")
        # 行序违例（theta 外层 → phi 列随行步进变化）
        swapped = (
            "// #Frequencies (Hz)\n1.0\n"
            "// Radiated/Accepted/Stimulated Power (W)\n"
            "1.0\n0.1\n2.0\n2.4e+09\n"
            "// >> Total #phi samples\n2 3\n// >> Phi, Theta\n"
        )
        for th in (0.0, 45.0, 90.0):  # theta 外层、phi 内层=违例布局
            for ph in (0.0, 90.0):
                swapped += f"{th!r} {ph!r} 1.0 0.0 0.0 1.0\n"
        with pytest.raises(ValueError, match="行序"):
            read(swapped)
        # 跨频块角度轴不一致（块 2 theta 轴平移）
        with pytest.raises(ValueError, match="角度轴不一致"):
            read(_ffs_text(two, theta_axis_shift=1.0))
