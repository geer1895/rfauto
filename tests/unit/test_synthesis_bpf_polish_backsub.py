"""W6-C 席（架构批 R3_followups §② 第 6/7 条）：C13 _cm_polish 兜底路径
钉 + N≥13/14 边界冒烟 + BPF 综合返回前 raise 型回代硬门（R1-4）。

定位（#222 实测口径，登记行只作线索）：
- polish 兜底入口 = src/rfauto/core/synthesis.py ``synthesize_bpf_model``
  内 ``fit_res > 1e-8`` 分支 → core/calc_families/cm_core.py
  ``_cm_polish``（LM 幅频精化，scipy least_squares method='lm'）；
- N≥14 边界（本批修复）：旧实现 polish 网格固定 41 点 → LM 残差数
  2×41=82 < 未知数 6·order → scipy method='lm' 直接 ValueError
  （N=14 修前实测 ok=False"横向矩阵构造失败"）——修法与
  cm_core.coupling_matrix_synthesize_n2 同款 min(max(41, 3·order+2),
  8·order+9)（c13-inc2 先例单源；order≤13 网格逐位不变）；
- 回代硬门（R1-4）：两层容差（主门 1e−5=既有响应判据同值 / 产物门
  1e−8=出版舍入噪声 ~1e−11 的 3 个量级余量），strict 缺省开，
  env RFAUTO_SYN_BPF_STRICT=0 或 strict=False 关（旧 ok=False 形态）。

超时保护（本仓无 pytest-timeout 插件）：重例（N=14/15，实测 ~5-6s/次）
走 _with_budget 线程 future 等待上限 90s——线程不可强杀，超时即判红并
留说明（残留线程随进程退出回收）；预算 ≈ 实测 15 倍，正常链不受影响。
"""

from __future__ import annotations

import concurrent.futures

import numpy as np
import pytest

import rfauto.core.calculators as calculators
from rfauto.core.calculators import (
    _cm_polish,
    _cm_poly_max_err,
    _cm_transversal_exact,
    _gcheb_prototype,
)
from rfauto.core.synthesis import synthesize_bpf_model

_BUDGET_S = 90.0


def _with_budget(fn, *args, **kwargs):
    """超时保护：结果等待上限 _BUDGET_S（≈实测重例 ~6s 的 15 倍）。"""
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(fn, *args, **kwargs)
        return fut.result(timeout=_BUDGET_S)
    except concurrent.futures.TimeoutError:
        raise AssertionError(
            f"超预算 {_BUDGET_S}s 未返回（超时保护判红；线程不可强杀，"
            "残留求解线程随进程退出回收）") from None
    finally:
        ex.shutdown(wait=False)


# ─── 任务1：_cm_polish 兜底内核 + N≥13/14 边界 ───────────────────────────────

@pytest.mark.slow  # 终门 DURATIONS >60s 慢件（193s，LM 幅频精化数值重件）
def test_cm_polish_recovers_degraded_start_substantially():
    """兜底内核钉（构造触发兜底的输入）：对精确横向矩阵人为退化（扰动
    三个耦合系数），LM 幅频精化大幅回收（实测 1.5e−1 → 3.3e−5，≥2 个
    量级）。幅频最小二乘非凸：深退化起点不保证复得闭式精度
    （3.3e−5 ≫ 1e−8）——这正是 synthesize_bpf_model 兜底产物标
    needs_calibration 的依据（超限标记而非静默通过，惯例④）。"""
    proto = _gcheb_prototype(6, 22.0, (1.5, 2.5))
    mt = _cm_transversal_exact(6, proto)
    bad = mt.copy()
    bad[1, 1] += 0.05
    bad[0, 2] += 0.03
    bad[5, 6] -= 0.04
    fit_bad = _cm_poly_max_err(bad, proto)
    assert fit_bad > 1e-2                       # 起点确已退化
    m2, res = _cm_polish(6, proto, bad,
                         np.linspace(-0.99, 0.99, 41))
    assert res is not None
    fit_out = _cm_poly_max_err(m2, proto)
    assert fit_out < 1e-4                       # 实测 3.27e−5：回收但非闭式级
    assert fit_out < 0.01 * fit_bad             # 回收 ≥2 个量级


def test_bpf_n13_boundary_smoke_both_families():
    """N=13 边界冒烟（合成小规模，实测 <0.2s/例，不触兜底）：全极点走
    纯闭式（family=none、needs_calibration=False）；单对 TZ 走 shifted
    族。N=13 恰为旧固定 41 点网格的 LM 可用上界（3·13+2=41）。"""
    out0 = synthesize_bpf_model(order=13, f0_ghz=2.4, fbw=0.1, rl_db=22.0)
    assert out0["ok"] is True
    assert out0["method"] == "cameron_residue"
    assert out0["needs_calibration"] is False
    assert out0["cross_family"] == "none"
    assert out0["response_max_err"] < 1e-7
    out1 = synthesize_bpf_model(order=13, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
                                transmission_zeros_ghz=[2.59])
    assert out1["ok"] is True
    assert out1["cross_family"] == "shifted"
    assert out1["response_max_err"] < 1e-7


def test_bpf_n14_boundary_grid_fix_and_fallback_labels():
    """N=14 边界（网格修复直接靶点）+ 兜底标签自然触发（非 monkeypatch）：
    旧固定 41 点在 N=14 必炸（LM 残差数 82 < 未知数 84 → scipy
    method='lm' 抛 ValueError → 修前实测 ok=False"横向矩阵构造失败"）；
    修复后两例收敛（实测 err 3.1e−10 / 2.4e−10，~5s/例），且闭式残差
    >1e−8（3.3e−8 / 1.8e−7）自然落入兜底 → method=cameron_residue+lm、
    needs_calibration=True。N=14 folded 已退化（family=mixed、
    pattern_residual 1e−8 量级，N=15 cm-core 已知口径同族）——如实钉。"""
    for tz in (None, [2.59]):
        out = _with_budget(synthesize_bpf_model, order=14, f0_ghz=2.4,
                           fbw=0.1, rl_db=22.0, transmission_zeros_ghz=tz)
        assert out["ok"] is True, out.get("errors")
        assert out["method"] == "cameron_residue+lm"
        assert out["needs_calibration"] is True
        assert out["response_max_err"] < 1e-5
        assert out["cross_family"] == "mixed"
        assert out["pattern_residual"] > 1e-9


# ─── 任务2：R1-4 raise 型回代硬门 ────────────────────────────────────────────

def test_bpf_gate_normal_chain_identical_across_strict_modes(monkeypatch):
    """正常链逐位不变（要求②）：strict 三种取值（None 缺省/True/False）
    与 env 关闸四途径对正常输入返回 dict 深度相等——门零足迹、零新增
    输出键（回归证据=既有 synthesis 测试全绿）。"""
    kw = dict(order=5, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
              transmission_zeros_ghz=[2.59])
    monkeypatch.delenv("RFAUTO_SYN_BPF_STRICT", raising=False)
    base = synthesize_bpf_model(**kw)
    assert base["ok"] is True
    assert base == synthesize_bpf_model(**kw, strict=True)
    assert base == synthesize_bpf_model(**kw, strict=False)
    monkeypatch.setenv("RFAUTO_SYN_BPF_STRICT", "0")
    assert base == synthesize_bpf_model(**kw)


def test_bpf_gate_tampered_coefficients_raise(monkeypatch):
    """要求①篡改系数→门红：注入坏系数（约简输出主线耦合 +5e−2，≫1e−5
    主门容差）→ strict 缺省 raise ValueError（回代自洽失败）；strict=
    False → 旧形态 ok=False + errors 携带超限详情（不静默）。"""
    orig = calculators._cm_reduce_folded

    def _corrupt(m, *a, **kw):
        mred, bad = orig(m, *a, **kw)
        mred = mred.copy()
        mred[1, 2] += 5e-2
        return mred, bad

    monkeypatch.setattr(calculators, "_cm_reduce_folded", _corrupt)
    kw = dict(order=4, f0_ghz=2.4, fbw=0.1, rl_db=20.0)
    with pytest.raises(ValueError, match="回代自洽失败"):
        synthesize_bpf_model(**kw)
    out = synthesize_bpf_model(**kw, strict=False)
    assert out["ok"] is False
    assert any("拓扑约简后频响偏差" in e for e in out["errors"])
    assert out["response_max_err"] > 1e-5


def test_bpf_gate_published_matrix_layer_catches_subtle_tamper(monkeypatch):
    """产物门（1e−8 层）：篡改幅度 2e−7 低于主门容差（1e−5 主门查不出）、
    远高于出版舍入噪声（~1e−11）——仅出版形态 coupling_matrix 回代能
    抓到 → strict raise / strict=False 如实 ok=False（无静默通过路径）。"""
    orig = calculators._cm_reduce_folded

    def _corrupt_small(m, *a, **kw):
        mred, bad = orig(m, *a, **kw)
        mred = mred.copy()
        mred[2, 3] += 2e-7
        return mred, bad

    monkeypatch.setattr(calculators, "_cm_reduce_folded", _corrupt_small)
    kw = dict(order=4, f0_ghz=2.4, fbw=0.1, rl_db=20.0)
    with pytest.raises(ValueError, match="产物门"):
        synthesize_bpf_model(**kw)
    out = synthesize_bpf_model(**kw, strict=False)
    assert out["ok"] is False
    assert any("出版矩阵回代偏差" in e for e in out["errors"])


def test_bpf_gate_env_optout_semantics(monkeypatch):
    """env 门语义：RFAUTO_SYN_BPF_STRICT="0"/"False"（大小写不敏感）关
    闸——同一篡改输入返回旧 ok=False 形态而不 raise；"1" 显式开。"""
    orig = calculators._cm_reduce_folded

    def _corrupt(m, *a, **kw):
        mred, bad = orig(m, *a, **kw)
        mred = mred.copy()
        mred[1, 2] += 5e-2
        return mred, bad

    monkeypatch.setattr(calculators, "_cm_reduce_folded", _corrupt)
    kw = dict(order=4, f0_ghz=2.4, fbw=0.1, rl_db=20.0)
    monkeypatch.setenv("RFAUTO_SYN_BPF_STRICT", "0")
    assert synthesize_bpf_model(**kw)["ok"] is False
    monkeypatch.setenv("RFAUTO_SYN_BPF_STRICT", "False")
    assert synthesize_bpf_model(**kw)["ok"] is False
    monkeypatch.setenv("RFAUTO_SYN_BPF_STRICT", "1")
    with pytest.raises(ValueError):
        synthesize_bpf_model(**kw)


def test_bpf_n15_two_tz_unconverged_gate_two_sided():
    """polish 不收敛的天然触发（无 mock，实测 ~6s/侧）：N=15 + 归一
    Ω=1.2/2.5 双对 TZ——LM 在自身 47 点网格收敛（残差 ~7e−9）但对密集
    真值偏差 2.1e−4，folded 后 S21 偏差 1.42e−5 ≥ 1e−5 主门。双面语义：
    strict 缺省 raise ValueError（门红）；strict=False 返回旧 ok=False
    形态（response_max_err 如实 >1e−5，#122 不许凑绿）。"""
    fzs = [2.260316119, 2.1186773245]  # f0=2.4、fbw=0.1 下映射 Ω=±1.2/±2.5
    kw = dict(order=15, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
              transmission_zeros_ghz=fzs)
    with pytest.raises(ValueError, match="回代自洽失败"):
        _with_budget(synthesize_bpf_model, **kw)
    out = _with_budget(synthesize_bpf_model, strict=False, **kw)
    assert out["ok"] is False
    assert 1e-5 <= out["response_max_err"] < 1e-3
    assert any("拓扑约简后频响偏差" in e for e in out["errors"])
