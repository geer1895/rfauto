"""Touchstone 文法 fuzz（round3 附带三件之三；core/aaa.py 同批 E 尾件）。

口径（研究扩充 §3.1 附带三件原文）：
    "hypothesis 文法 fuzz（Touchstone/netlist/ffs 行文法策略生成+parse→write→parse
    幂等不变量；atheris Windows NO-GO）"

本件覆盖 = Touchstone 文法：1/2 端口 × RI/MA/DB 格式 × HZ/KHZ/MHZ/GHZ 量级
× 注释/空行噪声。netlist/ffs 两文法未落（E 类台账如实登记，留后续批捎带）。

坑面钉死：
- #248：skrf 只按 .sNp 扩展名推断 rank——生成文件扩展名必须与端口数一致
  （1→.s1p、2→.s2p），rank×扩展名契约即本测试载体；
- #287：MA/DB 文本首 parse 即带格式精度（log10/三角函数往返）——对原始值
  的等值钉只走 RI 全精度路；parse→write→parse 幂等不变量从**第二次生成**
  起逐位钉（skrf 写端 RI 全精度 repr，实测逐位可复现）。

读端/写端 = skrf 基线依赖（>=2.0）；derandomize 确定性 + max_examples=20
（G15 惯例，控单元门预算）。
"""

from __future__ import annotations

import math
import os
import tempfile
from typing import Any

import numpy as np
import pytest
import skrf
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

FUZZ = settings(
    derandomize=True,
    deadline=None,
    max_examples=20,
    suppress_health_check=[HealthCheck.too_slow],
)

_UNIT_SCALES = [("HZ", 1.0), ("KHZ", 1e3), ("MHZ", 1e6), ("GHZ", 1e9)]
_EXT_BY_PORTS = {1: ".s1p", 2: ".s2p"}

_st_complex = st.tuples(st.floats(-1.0, 1.0), st.floats(-1.0, 1.0)).map(
    lambda t: complex(t[0], t[1])
)


@st.composite
def _spec(draw: st.DrawFn) -> dict[str, Any]:
    n_ports = draw(st.sampled_from([1, 2]))
    unit, scale = draw(st.sampled_from(_UNIT_SCALES))
    fmt = draw(st.sampled_from(["RI", "MA", "DB"]))
    n_freq = draw(st.integers(min_value=5, max_value=12))
    start = draw(st.floats(0.5, 5.0))
    ratio = draw(st.floats(1.01, 1.5))
    freqs_base = [start * ratio**i for i in range(n_freq)]
    n_pair = n_ports * n_ports
    s_flat = [draw(_st_complex) for _ in range(n_freq * n_pair)]
    noise = draw(st.lists(st.sampled_from(["!", "", "! inline comment"]), max_size=3))
    return {
        "n_ports": n_ports,
        "unit": unit,
        "scale": scale,
        "fmt": fmt,
        "freqs_base": freqs_base,
        "s_flat": s_flat,
        "noise": noise,
    }


def _freqs_hz(spec: dict[str, Any]) -> np.ndarray:
    return np.array([f * spec["scale"] for f in spec["freqs_base"]], dtype=float)


def _s_matrix(spec: dict[str, Any]) -> np.ndarray:
    n = spec["n_ports"]
    nf = len(spec["freqs_base"])
    arr = np.array(spec["s_flat"], dtype=complex).reshape(nf, n_pair := n * n)
    out = np.empty((nf, n, n), dtype=complex)
    # Touchstone 行序=列主序（S11,S21,...,SN1,S12,...）——写端口径
    for k in range(n_pair):
        i, j = k % n, k // n
        out[:, i, j] = arr[:, k]
    return out


def _tokens(z: complex, fmt: str) -> list[str]:
    # numpy 2.x 标量 repr 是 'np.float64(...)'（fuzz 首轮当场抓到）——先收敛
    # Python 标量再 repr，保证生成文本是真 Touchstone 数字
    z = complex(z)
    if fmt == "RI":
        return [repr(z.real), repr(z.imag)]
    mag = abs(z)
    ang = math.degrees(math.atan2(z.imag, z.real))
    if fmt == "MA":
        return [repr(mag), repr(ang)]
    if fmt == "DB":
        return [repr(20.0 * math.log10(max(mag, 1e-12))), repr(ang)]
    raise ValueError(f"未知格式 {fmt}")


def _touchstone_text(spec: dict[str, Any]) -> str:
    n = spec["n_ports"]
    s = _s_matrix(spec)
    lines: list[str] = [f"! fuzz grammar case ({n}-port {spec['fmt']} {spec['unit']})"]
    lines += spec["noise"]
    lines.append(f"# {spec['unit']} S {spec['fmt']} R 50")
    order = [(i, j) for j in range(n) for i in range(n)]  # 列主序
    for k, f_base in enumerate(spec["freqs_base"]):
        toks = [repr(float(f_base))]
        for i, j in order:
            toks += _tokens(s[k, i, j], spec["fmt"])
        lines.append(" ".join(toks))
    lines.append("! trailing")
    return "\n".join(lines) + "\n"


def _network_from_spec(spec: dict[str, Any]) -> skrf.Network:
    return skrf.Network(frequency=_freqs_hz(spec), s=_s_matrix(spec), z0=50.0)


def _parse(path: str) -> skrf.Network:
    return skrf.Network(path)


def _assert_close(net: skrf.Network, spec: dict[str, Any], *, s_rtol: float) -> None:
    np.testing.assert_allclose(net.f, _freqs_hz(spec), rtol=1e-12, atol=0.0)
    np.testing.assert_allclose(net.s, _s_matrix(spec), rtol=s_rtol, atol=1e-9)


class TestTouchstoneGrammarFuzz:
    @given(_spec())
    @FUZZ
    def test_text_parse_then_write_parse_idempotent(self, spec: dict[str, Any]):
        text = _touchstone_text(spec)
        with tempfile.TemporaryDirectory() as td:
            p1 = os.path.join(td, f"gen{_EXT_BY_PORTS[spec['n_ports']]}")
            with open(p1, "w", encoding="ascii") as fh:
                fh.write(text)
            net1 = _parse(p1)
            # 不变量 A：首 parse 保数据（RI 全精度；MA/DB 带格式精度，#287 口径）
            s_rtol = 1e-12 if spec["fmt"] == "RI" else 1e-6
            _assert_close(net1, spec, s_rtol=s_rtol)
            # 不变量 B：parse→write→parse 自第二次生成起逐位幂等（写端 RI 全精度）
            p2 = os.path.join(td, "b")  # 无扩展名：skrf 按 rank 自动补 .sNp
            net1.write_touchstone(p2)
            net2 = _parse(p2 + _EXT_BY_PORTS[spec["n_ports"]])
            p3 = os.path.join(td, "c")
            net2.write_touchstone(p3)
            net3 = _parse(p3 + _EXT_BY_PORTS[spec["n_ports"]])
            assert np.array_equal(net2.s, net3.s)
            assert np.array_equal(net2.f, net3.f)
            # 不变量 C：写读链不漂移参考阻抗
            assert float(np.real(net2.z0[0, 0])) == pytest.approx(50.0)

    @given(_spec())
    @FUZZ
    def test_object_write_read_roundtrip_exact(self, spec: dict[str, Any]):
        net = _network_from_spec(spec)
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "rt")
            net.write_touchstone(p)
            back = _parse(p + _EXT_BY_PORTS[spec["n_ports"]])
        # skrf 写端 RI 全精度：数据逐位保真（2026-09-28 venv skrf 2.1.0 实测）
        assert np.array_equal(back.f, _freqs_hz(spec))
        assert np.array_equal(back.s, _s_matrix(spec))
