"""G15 物理不变量·传输线电长度元变（§2 Maxwell 尺度律 + §4.4 频移等价）。

aurora_h W2-S4 拆分批自 test_physics_invariants.py 迁出（R1 立项 #7）：
本件两条不变量都作用在"承载电长度的传播尺寸"上（传输线域元变）——

1. **Maxwell 尺度律**（§2）：几何 ×k、频率 ÷k、材料不变 → S 参数不变。
   对均匀/级联传输线模型 β(f/k)·(kL)=β(f)·L、α(f/k)·(kL)=α(f)·L → S 严格
   不变（解析精确，非数值近似）；容差显式写出（实测达到值见断言旁注释）。
2. **频移等价**（§4.4）：均匀线 φ 差=−L·(β(f₂)−β(f₁))=−L·∫dβ（准静态
   β 线性于 f，∫dβ=Δβ 逐位成立）。

尺度律破坏样例的负例自证（test_scale_oracle_detects_broken_scaling）随族在
本件；β 错源负例在 _meas（四族负例集中面）。共享常数/引擎见
_invariants_helpers.py。

确定性口径（任务硬约束 4）：Hypothesis 一律 derandomize=True（固定种子），
禁网络、禁真机；本文件只跑 fake/闭式内核。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.unit._invariants_helpers import (
    _QM1_FREQ,
    _QM1_FREQ_PAIRS,
    _QM1_PHASE_TOL,
    _SCALE_TOL,
    G15,
    SCALE_CASES,
    _fake_sparams,
    _qm1_fake_splanes,
    _qm1_line_beta_models,
    _scale_violation,
)


@pytest.mark.parametrize("model,variables,length_keys,n_ports,f0_ghz", SCALE_CASES)
def test_maxwell_scale_law_fake_adapter(
    model: str, variables: dict[str, Any], length_keys: list[str],
    n_ports: int, f0_ghz: float,
) -> None:
    """k=2 元变：S 参数在尺度变换下逐点不变（|ΔS| ≤ 1e-10）。"""
    delta = _scale_violation(model, variables, length_keys, n_ports, f0_ghz, 2.0)
    assert delta <= _SCALE_TOL, f"{model} 尺度律违背: max|ΔS|={delta:.3e}"


@G15
@given(k=st.floats(min_value=1.2, max_value=3.5, allow_nan=False,
                   allow_infinity=False))
def test_maxwell_scale_law_arbitrary_k(k: float) -> None:
    """任意尺度因子 k：全部模板的尺度律仍成立（属性化，非单点）。"""
    for model, variables, length_keys, n_ports, f0_ghz in (
        (p.values[0], p.values[1], p.values[2], p.values[3], p.values[4])
        for p in SCALE_CASES
    ):
        delta = _scale_violation(
            model, variables, length_keys, n_ports, f0_ghz, k)
        assert delta <= _SCALE_TOL, (
            f"{model} k={k!r} 尺度律违背: max|ΔS|={delta:.3e}"
        )


def test_scale_oracle_detects_broken_scaling() -> None:
    """自证：只缩频率不缩几何（故意破坏）必须被尺度预言机检出。"""
    variables = {"w_mm": 1.113, "line_len_mm": 40.0}
    nominal = _fake_sparams("mline", variables, (2.0, 3.0, 101), 2, 2.5)
    broken = _fake_sparams("mline", variables, (1.0, 1.5, 101), 2, 2.5)
    assert float(np.max(np.abs(nominal - broken))) > 0.1, (
        "尺度预言机对破坏样例不敏感（恒真断言风险）"
    )


@pytest.mark.parametrize("i1,i2", _QM1_FREQ_PAIRS)
@pytest.mark.parametrize("model", ["mline", "cpw", "stripline"])
def test_frequency_shift_equivalence(model: str, i1: int, i2: int) -> None:
    """④频移等价：φ(f₂)−φ(f₁) = −L·(β(f₂)−β(f₁)) = −L·∫_{f₁}^{f₂} dβ。

    β 准静态口径线性于 f（无色散），∫dβ=Δβ 逐位成立；实测违例 ≤1e-15，
    门槛 1e-10 留浮点余量。频点对 (i1,i2) 参数化覆盖同频点/跨带/半带组合。
    """
    s = _qm1_fake_splanes()[model]
    phi = np.unwrap(np.angle(s[:, 0, 1]))
    beta, length_m = _qm1_line_beta_models()[model]
    measured = float(phi[i2] - phi[i1])
    predicted = -float(beta[i2] - beta[i1]) * length_m
    assert abs(measured - predicted) <= _QM1_PHASE_TOL, (
        f"{model} 频移等价违背 ({i1}->{i2}): |Δφ+L·Δβ|="
        f"{abs(measured - predicted):.3e}")


@G15
@given(data=st.data())
def test_frequency_shift_equivalence_arbitrary_pair(
    data: st.DataObject,
) -> None:
    """④频移等价属性化：任意频点对（Hypothesis 固定种子）恒等仍成立。"""
    model = data.draw(st.sampled_from(["mline", "cpw", "stripline"]))
    i1 = data.draw(st.integers(min_value=0, max_value=_QM1_FREQ[2] - 2))
    i2 = data.draw(st.integers(min_value=i1 + 1, max_value=_QM1_FREQ[2] - 1))
    s = _qm1_fake_splanes()[model]
    phi = np.unwrap(np.angle(s[:, 0, 1]))
    beta, length_m = _qm1_line_beta_models()[model]
    assert abs(float(phi[i2] - phi[i1])
               + float(beta[i2] - beta[i1]) * length_m) <= _QM1_PHASE_TOL
