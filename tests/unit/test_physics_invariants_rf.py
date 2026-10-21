"""G15 物理不变量·端口网络对称元变（§3 镜像/置换 + §4.1 互易扫描 +
§4.2 线性叠加 + §4.3 无源性）。

架构批 W2-S4 拆分批自 test_physics_invariants.py 迁出（R1 立项 #7）：
本件不变量都是 S 矩阵面的端口网络对称性（射频网络域元变）——

1. **镜像对称+互易**（§3）：自对称 2 端口 S11=S22、S=Sᵀ；
2. **端口重编号置换等价**（§3）：自同构置换下 S 按同置换重排不变；
3. **互易全键扫描**（§4.1）：S/ABCD 产出白名单键逐键实调断 S=Sᵀ；
4. **线性叠加**（§4.2）：随机复高斯入射下 S(a₁+a₂)=Sa₁+Sa₂；
5. **无源性**（§4.3）：逐频 σmax(S) ≤ 1+1e-9（DP-1 G4 口径）。

负例自证（置换非自同构/破坏矩阵注入）随族在本件；四族集中负例面在 _meas。
共享常数/引擎见 _invariants_helpers.py。

确定性口径（任务硬约束 4）：Hypothesis 一律 derandomize=True（固定种子），
禁网络、禁真机；本文件只跑 fake/闭式内核。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from rfauto.core.calculators import CALCULATOR_REGISTRY
from tests.unit._invariants_helpers import (
    _MIRROR_TOL,
    _PERM_TOL,
    _QM1_FAKE_SAMPLES,
    _QM1_FREQ,
    _QM1_PASSIVITY_TOL,
    _QM1_SUPERPOS_PAIRS,
    _QM1_SUPERPOS_SEED,
    _QM1_SUPERPOS_TOL,
    _S_PLANE_SCAN_CASES,
    G15,
    MIRROR_2PORT,
    PERMUTATION_CASES,
    S_PLANE_CALCULATOR_KEYS,
    _cm_response_variants,
    _fake_sparams,
    _max_mirror_violation,
    _max_permutation_violation,
    _max_reciprocity_violation,
    _max_sigma_max,
    _qm1_fake_splanes,
    _superposition_violation,
)


@pytest.mark.parametrize("model,variables", MIRROR_2PORT)
def test_mirror_symmetry_and_reciprocity(
    model: str, variables: dict[str, Any]
) -> None:
    """镜像对称结构：S11=S22（结构自对称）+ S=Sᵀ（互易）。

    wstep（w1≠w2）不是自对称结构：其不变量为镜像对关系——配置 (w1,w2) 的
    S 矩阵等于配置 (w2,w1) 的 S 按端口置换重排（#235 修复 wstep fake S22
    后由数据质量修复师实证，S11≠S22 是正确行为）。
    """
    s = _fake_sparams(model, variables, (2.0, 3.0, 101), 2, 2.5)
    assert _max_reciprocity_violation(s) <= _MIRROR_TOL, (
        f"{model} 互易性违背: {_max_reciprocity_violation(s):.3e}"
    )
    if model == "wstep":
        mirrored = dict(variables)
        mirrored["w1_mm"], mirrored["w2_mm"] = variables["w2_mm"], variables["w1_mm"]
        s_m = _fake_sparams(model, mirrored, (2.0, 3.0, 101), 2, 2.5)
        pair_violation = float(np.max(np.abs(s - s_m[:, ::-1, ::-1])))
        assert pair_violation <= 1e-12, (
            f"wstep 镜像对关系违背: {pair_violation:.3e}"
        )
    else:
        assert _max_mirror_violation(s) <= _MIRROR_TOL, (
            f"{model} 镜像对称违背: {_max_mirror_violation(s):.3e}"
        )


@pytest.mark.parametrize("model,variables,n_ports,perm,phase_exact",
                         PERMUTATION_CASES)
def test_port_renumbering_permutation_equivalence(
    model: str, variables: dict[str, Any], n_ports: int, perm: list[int],
    phase_exact: bool,
) -> None:
    """端口重编号置换等价：S[σ(i),σ(j)] == S[i,j]（相位精确或仅幅值）。"""
    s = _fake_sparams(model, variables, (2.0, 3.0, 101), n_ports, 2.5)
    if phase_exact:
        delta = _max_permutation_violation(s, perm)
    else:
        mag = np.abs(s)
        delta = float(np.max(np.abs(mag - mag[:, perm][:, :, perm])))
    assert delta <= _PERM_TOL, (
        f"{model} 置换 {perm} 违背: max|ΔS|={delta:.3e}"
    )


def test_permutation_oracle_detects_non_automorphism() -> None:
    """自证：非自同构置换（输入↔输出）必须被检出为大偏差。"""
    s = _fake_sparams("gysel", {}, (2.0, 3.0, 101), 3, 2.5)
    good = _max_permutation_violation(s, [0, 2, 1])
    bad = _max_permutation_violation(s, [1, 0, 2])
    assert good <= _PERM_TOL
    assert bad > 0.5, f"置换预言机对非自同构不敏感: {bad:.3e}"


def test_oracle_checkers_reject_corrupted_matrices() -> None:
    """预言机自证（函数级）：喂入被破坏的 S 矩阵必须抛 AssertionError。"""
    s = _fake_sparams("mline", {"w_mm": 1.113, "line_len_mm": 40.0},
                      (2.0, 3.0, 101), 2, 2.5)
    assert _max_reciprocity_violation(s) <= _MIRROR_TOL

    broken = s.copy()
    broken[:, 0, 1] *= 1.5  # 破坏互易性
    assert _max_reciprocity_violation(broken) > 1e-6
    with pytest.raises(AssertionError):
        assert _max_reciprocity_violation(broken) <= _MIRROR_TOL

    broken_mirror = s.copy()
    broken_mirror[:, 1, 1] += 0.3  # 破坏 S11=S22
    with pytest.raises(AssertionError):
        assert _max_mirror_violation(broken_mirror) <= _MIRROR_TOL


@pytest.mark.parametrize("name,variant", _S_PLANE_SCAN_CASES)
def test_reciprocity_full_key_scan(name: str, variant: str) -> None:
    """①互易全键扫描：S/ABCD 产出键逐键实调，断 S=Sᵀ（tol 与 §3 同 1e-12）。

    范围由静态白名单控制（§D-7 适用性谓词）——闭式注册键中唯一 S 面产出
    键 coupling_matrix_response 以 3 套综合矩阵变体复调；spec.reciprocal
    必须为 True（豁免键走封闭清单，不得滞留白名单）。
    """
    assert name in S_PLANE_CALCULATOR_KEYS
    spec = CALCULATOR_REGISTRY.get(name)
    assert spec.reciprocal is True, (
        f"{name} 在 S 面白名单但 reciprocal=False——应移入豁免清单并重新归类")
    s = _cm_response_variants()[variant]
    assert s.ndim == 3 and s.shape[-1] == s.shape[-2] > 0
    viol = _max_reciprocity_violation(s)
    assert viol <= _MIRROR_TOL, f"{name}[{variant}] 互易违背: {viol:.3e}"


@pytest.mark.parametrize("model,variables,n_ports,f0_ghz", _QM1_FAKE_SAMPLES)
def test_linear_superposition_fake_splane(
    model: str, variables: dict[str, Any], n_ports: int, f0_ghz: float,
) -> None:
    """②线性叠加：随机复高斯 a₁,a₂ 下 S(a₁+a₂) = Sa₁+Sa₂（≤1e-10）。

    被测面=线性网络的响应算子 b(a)=S·a（逐频）；叠加线性是 S 矩阵面成立
    的前提约束（未来适配器若引入激励相关/功率相关响应即在此被检出）。
    """
    s = _qm1_fake_splanes()[model]
    n = s.shape[-1]
    rng = np.random.default_rng(_QM1_SUPERPOS_SEED + n_ports + len(model))
    worst = 0.0
    for _ in range(_QM1_SUPERPOS_PAIRS):
        a1 = (rng.standard_normal((_QM1_FREQ[2], n))
              + 1j * rng.standard_normal((_QM1_FREQ[2], n)))
        a2 = (rng.standard_normal((_QM1_FREQ[2], n))
              + 1j * rng.standard_normal((_QM1_FREQ[2], n)))
        worst = max(worst, _superposition_violation(s, a1, a2))
    assert worst <= _QM1_SUPERPOS_TOL, (
        f"{model} 叠加违例: max|S(a₁+a₂)−(Sa₁+Sa₂)|={worst:.3e}")


@G15
@given(data=st.data())
def test_linear_superposition_arbitrary_entries(data: st.DataObject) -> None:
    """②叠加属性化：任意有界复入射对（Hypothesis 固定种子）恒等仍成立。"""
    s = _qm1_fake_splanes()["mline"]
    n = s.shape[-1]
    f_idx = data.draw(st.integers(min_value=0, max_value=_QM1_FREQ[2] - 1))

    def draw_vector() -> np.ndarray:
        re = data.draw(st.lists(
            st.floats(min_value=-5.0, max_value=5.0, allow_nan=False,
                      allow_infinity=False), min_size=n, max_size=n))
        im = data.draw(st.lists(
            st.floats(min_value=-5.0, max_value=5.0, allow_nan=False,
                      allow_infinity=False), min_size=n, max_size=n))
        return np.asarray(re) + 1j * np.asarray(im)

    viol = _superposition_violation(
        s[f_idx][None, :, :], draw_vector()[None, :], draw_vector()[None, :])
    assert viol <= _QM1_SUPERPOS_TOL, f"叠加违例: {viol:.3e}"


@pytest.mark.parametrize("model,variables,n_ports,f0_ghz", _QM1_FAKE_SAMPLES)
def test_passivity_fake_splane(
    model: str, variables: dict[str, Any], n_ports: int, f0_ghz: float,
) -> None:
    """③无源性：抽样 9 模板逐频 σmax(S) ≤ 1+1e-9（无源网络不可有功率增益）。

    σmax(S†S)=σmax(S)²，判据按 G4 先例（test_field_circuit_anchor）写在
    σmax(S) 上。hairpin 走 coupling_matrix_response 的 9 位小数舍入输出，
    实测 σmax=1+9.8e-10 贴门但确定性（fixture 固定）——越门先查舍入地板
    （cm_core.c3 round(...,9)）再查物理。
    """
    sig = _max_sigma_max(_qm1_fake_splanes()[model])
    assert sig <= 1.0 + _QM1_PASSIVITY_TOL, (
        f"{model} 无源违背: σmax={sig:.12f} > 1+{_QM1_PASSIVITY_TOL}")


def test_passivity_closed_form_s_keys() -> None:
    """③闭式 S 面键（白名单全量）：3 个矩阵变体逐频 σmax ≤ 1+1e-9。

    舍入地板注记：coupling_matrix_response 输出按 9 位小数四舍五入，
    元素舍入 5e-10 → σmax 地板 ~1+0.9e-9（实测），贴门但确定性——
    §D-7 "2-3 个闭式 S 面键" 中现存 S 面产出键仅此一键（注册表实测）。
    """
    worst = max(_max_sigma_max(s) for s in _cm_response_variants().values())
    assert worst <= 1.0 + _QM1_PASSIVITY_TOL, (
        f"闭式 S 面无源违背: σmax={worst:.12f}")


def test_wilkinson3_passivity_fixed_gate() -> None:
    """③wilkinson(3 端口) 无源门转正（QM-1 违例已修）。

    历史：§D-7 曾实测 σmax≈1.184@3GHz（|S21| 全带恒定 1/√2 + 逐行 0.95
    归一 ≠ 幺正无源），xfail 文档化后于 ge8b 批修复——透射幅度按
    √(1-|S_kk|²) 能量守恒乘+σmax 兜底（fake_adapter）。修后全频段
    σmax ≤ 1+1e-9，wilkinson 补入抽样面（8→9）。
    """
    s = _fake_sparams("wilkinson",
                      {"series_w_mm": 0.604, "shunt_w_mm": 1.113,
                       "arm_len_mm": 18.1},
                      _QM1_FREQ, 3, 2.5)
    assert _max_sigma_max(s) <= 1.0 + _QM1_PASSIVITY_TOL
