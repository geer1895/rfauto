"""core/gci.py（网格收敛检查器 GCI/Richardson，SV-6）验证锚（#118 独立来源）。

裁判本身必须先过已知解析基准才有资格裁判：
- 幂律解析族 f = C + h^q：观察阶 p 恒等于 q（p=1/2/非整数 1.5 三档），
  恒定比二进制精确构造（h 取 2 的幂、C=0 → 差与比值逐位精确），
  Richardson 外推逐位回收 C、GCI 带必含真值；
- 振荡族 f = C + (−1)^k·h^2：Çelik 2008 绝对值处方判振荡、p 仍 = 2、
  带仍保守含真值；
- 发散族 f = C + 1/h：差比 < 1 → p = −1 如实报告、不虚构误差带；
- 负例：<3 网格、r ≤ 1、零差、fs ≤ 0、重复/非正 h；
- 广义支路：非恒定比 (2.5, 2.4) 两点模型非整数 p 二分回收 q=2；
- 同源对拍：恒定 r 单调支路与 vv_mapping.u_num_gci 同式一致；
- 语义分工：振荡情形 vv_mapping 保守 None，本模块如实分类给带（契约
  不同不矛盾，双向钉死）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.gci import (
    FS_DEFAULT,
    REASON_NO_ROOT,
    REASON_NONPOSITIVE_ORDER,
    REASON_OSC_REQUIRES_CONSTANT_R,
    REASON_ZERO_DIFFERENCE,
    STATUS_DEGENERATE,
    STATUS_MONOTONIC,
    STATUS_OSCILLATORY,
    GridConvergenceResult,
    assess_grid_convergence,
    assess_triple,
    gci_from_order,
)
from rfauto.core.vv_mapping import u_num_gci

# 二进制精确构造：h 取 2 的幂（2^-7 起步），C=0 → f 与逐级差全为精确浮点
H1 = 2.0**-7
C_QUAD = 0.0


def _quad(h: float) -> float:
    return C_QUAD + h * h


# ─── 幂律解析族：p 精确回收 + 外推逐位回 C + GCI 带含真值 ────────────────────

def test_quadratic_exact_recovery_p2():
    """f = h²：p = 2、外推逐位回 C=0、GCI = 1.25·2⁻¹⁴（二进制可逐位）。"""
    f1, f2, f3 = _quad(H1), _quad(2 * H1), _quad(4 * H1)
    res = assess_triple(f1, f2, f3, 2.0)
    assert res.status == STATUS_MONOTONIC
    assert res.convergent is True
    assert res.p == pytest.approx(2.0, abs=1e-12)
    # 外推：4·f1 − f2 = 2⁻¹² − 2⁻¹² = 0（幂律下逐位精确）
    assert res.f_extrapolated == pytest.approx(C_QUAD, abs=1e-18)
    assert res.richardson_error == pytest.approx(2.0**-14, rel=1e-12)
    # GCI = Fs·|ε21|/(r^p − 1) = 1.25·3·2⁻¹⁴/3 = 1.25·2⁻¹⁴
    assert res.gci_fine == pytest.approx(1.25 * 2.0**-14, rel=1e-12)
    assert res.band is not None
    assert res.band[0] <= C_QUAD <= res.band[1]


def test_linear_exact_recovery_p1():
    """f = h：p = 1、外推回 0、GCI = 1.25·h1（quasistatic_fd 一阶外推的带形式）。"""
    f1, f2, f3 = H1, 2 * H1, 4 * H1
    res = assess_triple(f1, f2, f3, 2.0)
    assert res.status == STATUS_MONOTONIC
    assert res.p == pytest.approx(1.0, abs=1e-12)
    assert res.f_extrapolated == pytest.approx(0.0, abs=1e-18)
    assert res.gci_fine == pytest.approx(1.25 * H1, rel=1e-12)
    assert res.band is not None and res.band[0] <= 0.0 <= res.band[1]


def test_non_integer_order_p1_5():
    """f = h^1.5：非整数观察阶 p = 1.5 精确回收（ln 闭式天然支持）。"""
    f1, f2, f3 = H1**1.5, (2 * H1) ** 1.5, (4 * H1) ** 1.5
    res = assess_triple(f1, f2, f3, 2.0)
    assert res.convergent is True
    assert res.p == pytest.approx(1.5, rel=1e-9)
    assert res.f_extrapolated == pytest.approx(0.0, abs=1e-15)
    assert res.band is not None and res.band[0] <= 0.0 <= res.band[1]


def test_band_contains_true_value_with_offset():
    """C ≠ 0（单调族 f = C + h²）时带仍含真值：|φ1 − C| = h² ≤ GCI。"""
    c = 5.0
    f1, f2, f3 = c + H1**2, c + (2 * H1) ** 2, c + (4 * H1) ** 2
    res = assess_triple(f1, f2, f3, 2.0)
    assert res.status == STATUS_MONOTONIC
    assert res.gci_fine is not None and res.band is not None
    assert abs(f1 - c) <= res.gci_fine
    assert res.band[0] <= c <= res.band[1]


# ─── 振荡收敛判别（Çelik 2008 绝对值处方）────────────────────────────────────

def test_oscillatory_classified_and_band_conservative():
    """f = C + (−1)^k·h²：判振荡、p 仍 2、带仍含真值 C。"""
    c = 5.0
    f1 = c - H1**2          # 细：负支
    f2 = c + (2 * H1) ** 2  # 中：正支（ε21 = 5·2⁻¹⁴ > 0）
    f3 = c - (4 * H1) ** 2  # 粗：负支（ε32 = −5·2⁻¹² < 0）
    res = assess_triple(f1, f2, f3, 2.0)
    assert res.status == STATUS_OSCILLATORY
    assert res.convergent is True
    assert res.p == pytest.approx(2.0, abs=1e-12)
    assert res.gci_fine == pytest.approx(1.25 * (5.0 * 2.0**-14) / 3.0, rel=1e-9)
    assert res.band is not None and res.band[0] <= c <= res.band[1]
    # 语义分工：同输入 vv_mapping.u_num_gci 保守 None（差比 ≤1 一律不虚构）
    assert u_num_gci(f1, f2, f3, 2.0) is None


def test_oscillatory_nonpositive_ratio_honest():
    """振荡且 |差比| ≤ 1：p ≤ 0 如实报告、不虚构带。"""
    # ε21 = 1、ε32 = −0.5 → |R| = 0.5 → p = −1
    res = assess_triple(0.0, 1.0, 0.5, 2.0)
    assert res.status == STATUS_OSCILLATORY
    assert res.convergent is False
    assert res.p == pytest.approx(-1.0, abs=1e-12)
    assert res.gci_fine is None and res.band is None
    assert res.reason == REASON_NONPOSITIVE_ORDER


# ─── 发散与退化 ──────────────────────────────────────────────────────────────

def test_divergent_monotonic_negative_order():
    """f = 1/h（细化越细值越大）：差比 0.5 → p = −1、无带、不虚构。"""
    f1, f2, f3 = 1.0 / H1, 1.0 / (2 * H1), 1.0 / (4 * H1)
    res = assess_triple(f1, f2, f3, 2.0)
    assert res.status == STATUS_MONOTONIC
    assert res.convergent is False
    assert res.p == pytest.approx(-1.0, abs=1e-12)
    assert res.gci_fine is None and res.band is None and res.f_extrapolated is None
    assert res.reason == REASON_NONPOSITIVE_ORDER


def test_degenerate_zero_difference():
    """零逐级差：degenerate + reason，p/GCI None。"""
    res = assess_triple(1.0, 1.0, 2.0, 2.0)
    assert res.status == STATUS_DEGENERATE
    assert res.convergent is False and res.p is None and res.gci_fine is None
    assert res.reason == REASON_ZERO_DIFFERENCE
    res_const = assess_triple(3.0, 3.0, 3.0, 2.0)
    assert res_const.status == STATUS_DEGENERATE
    assert res_const.reason == REASON_ZERO_DIFFERENCE


# ─── 负例（参数校验）─────────────────────────────────────────────────────────

def test_value_errors_insufficient_and_invalid():
    """<3 网格 / 长度不匹配 / r ≤ 1 / fs ≤ 0 / 非正或重复 h / 非有限值。"""
    with pytest.raises(ValueError, match="至少需要 3 级网格"):
        assess_grid_convergence([0.1, 0.05], [1.0, 2.0])
    with pytest.raises(ValueError, match="长度不一致"):
        assess_grid_convergence([0.1, 0.05, 0.025], [1.0, 2.0])
    with pytest.raises(ValueError, match="r 必须 > 1"):
        assess_triple(1.0, 2.0, 4.0, 1.0)
    with pytest.raises(ValueError, match="r 必须 > 1"):
        assess_triple(1.0, 2.0, 4.0, 0.5)
    with pytest.raises(ValueError, match="fs 必须 > 0"):
        assess_triple(1.0, 2.0, 4.0, 2.0, fs=0.0)
    with pytest.raises(ValueError, match="fs 必须 > 0"):
        assess_grid_convergence([0.1, 0.05, 0.025], [4.0, 2.0, 1.0], fs=-1.0)
    with pytest.raises(ValueError, match="h 必须为正"):
        assess_grid_convergence([0.1, 0.05, 0.0], [1.0, 2.0, 4.0])
    with pytest.raises(ValueError, match="重复值"):
        assess_grid_convergence([0.1, 0.1, 0.05], [1.0, 2.0, 4.0])
    with pytest.raises(ValueError, match="有限"):
        assess_triple(1.0, float("nan"), 4.0, 2.0)


def test_gci_from_order_formula_and_guards():
    """公式直算面：Fs·|ε21|/(r^p − 1)；p ≤ 0 / r ≤ 1 / fs ≤ 0 抛 ValueError。"""
    assert gci_from_order(1.0, 2.0, 2.0, 2.0) == pytest.approx(1.25 / 3.0, rel=1e-12)
    with pytest.raises(ValueError, match="无正收敛阶"):
        gci_from_order(1.0, 2.0, 2.0, 0.0)
    with pytest.raises(ValueError, match="无正收敛阶"):
        gci_from_order(1.0, 2.0, 2.0, -1.0)
    with pytest.raises(ValueError, match="r 必须 > 1"):
        gci_from_order(1.0, 2.0, 1.0, 2.0)


def test_fs_scaling():
    """GCI 对安全因子线性：fs=2.0 的带是 fs=1.25 的 1.6 倍。"""
    f1, f2, f3 = _quad(H1), _quad(2 * H1), _quad(4 * H1)
    base = assess_triple(f1, f2, f3, 2.0)
    wide = assess_triple(f1, f2, f3, 2.0, fs=2.0)
    assert wide.fs == 2.0
    assert wide.gci_fine == pytest.approx(base.gci_fine * (2.0 / FS_DEFAULT), rel=1e-12)


# ─── 序列入口（迁移语义）─────────────────────────────────────────────────────

def test_sequence_constant_ratio_matches_triple():
    """序列入口恒定比支路 == assess_triple 结果 + h 报告字段（单源不漂移）。"""
    hs = [H1, 2 * H1, 4 * H1, 8 * H1]
    fs_vals = [_quad(h) for h in hs]
    res_seq = assess_grid_convergence(hs, fs_vals)
    f1, f2, f3 = fs_vals[0], fs_vals[1], fs_vals[2]
    res_tri = assess_triple(f1, f2, f3, 2.0)
    assert res_seq == res_tri.__class__(
        **{**res_tri.__dict__, "h_fine": H1, "h_medium": 2 * H1, "h_coarse": 4 * H1})
    assert res_seq.r_constant is True
    assert res_seq.r == pytest.approx(2.0, rel=1e-12)


def test_sequence_generalized_ratio_recovers_p2():
    """非恒定比 (2.5, 2.4)：广义两点模型二分解非整数 p，回收 q=2 与 C=10。"""
    hs = [0.14, 0.01, 0.06, 0.025]  # 乱序输入，内部排序取最细三级
    fs_vals = [10.0 + h * h for h in hs]
    res = assess_grid_convergence(hs, fs_vals)
    assert res.r_constant is False
    assert res.status == STATUS_MONOTONIC
    assert res.convergent is True
    assert res.p == pytest.approx(2.0, rel=1e-8)
    assert res.f_extrapolated == pytest.approx(10.0, abs=1e-9)
    assert res.r == pytest.approx(math.sqrt(0.06 / 0.01), rel=1e-12)
    assert res.h_fine == 0.01 and res.h_medium == 0.025 and res.h_coarse == 0.06
    assert res.band is not None and res.band[0] <= 10.0 <= res.band[1]


def test_sequence_no_root_honest():
    """非恒定比且差比 ≤ R_min（p 无正根）：如实 p=None + reason，不虚构。"""
    # h = 0.01/0.025/0.06 → R_min = ln2.4/ln2.5 ≈ 0.9555；取 R = 0.9 < R_min
    res = assess_grid_convergence([0.01, 0.025, 0.06], [0.0, 1.0, 1.9])
    assert res.status == STATUS_MONOTONIC
    assert res.convergent is False and res.p is None
    assert res.gci_fine is None and res.band is None
    assert res.reason == REASON_NO_ROOT


def test_sequence_oscillatory_nonconstant_honest():
    """振荡且比非恒定：两点模型不可表 → p=None + 专属 reason。"""
    res = assess_grid_convergence([0.01, 0.025, 0.06], [3.0, 4.0, 3.5])
    assert res.status == STATUS_OSCILLATORY
    assert res.convergent is False and res.p is None and res.gci_fine is None
    assert res.reason == REASON_OSC_REQUIRES_CONSTANT_R


def test_sequence_order_normalization_bitwise():
    """粗→细 / 细→粗输入同一结果（排序归一逐位一致）。"""
    hs = [0.01, 0.025, 0.06]
    fs_vals = [10.0 + h * h for h in hs]
    asc = assess_grid_convergence(hs, fs_vals)
    desc = assess_grid_convergence(hs[::-1], fs_vals[::-1])
    assert asc == desc


# ─── 同源对拍与产出契约 ──────────────────────────────────────────────────────

def test_consistency_with_vv_mapping_u_num_gci():
    """恒定 r 单调支路与 vv_mapping.u_num_gci 同式（Fs·|Δ|/(r^p−1)）对拍。"""
    f1, f2, f3 = _quad(H1), _quad(2 * H1), _quad(4 * H1)
    res = assess_triple(f1, f2, f3, 2.0)
    ref = u_num_gci(f1, f2, f3, 2.0, fs=1.25)
    assert ref is not None
    assert res.gci_fine == pytest.approx(ref, rel=1e-12)


def test_as_dict_roundtrip():
    """as_dict 键齐全且 JSON 可承载（band 转列表、None 保序）。"""
    f1, f2, f3 = _quad(H1), _quad(2 * H1), _quad(4 * H1)
    res = assess_triple(f1, f2, f3, 2.0)
    d = res.as_dict()
    expected_keys = set(GridConvergenceResult.__dataclass_fields__)
    assert set(d) == expected_keys
    assert d["band"] == list(res.band)
    assert json.loads(json.dumps(d))["gci_fine"] == pytest.approx(res.gci_fine)
    # 不可估支路同样可序列化（None 字段保序不丢）
    d_deg = assess_triple(1.0, 1.0, 2.0, 2.0).as_dict()
    assert json.loads(json.dumps(d_deg))["reason"] == REASON_ZERO_DIFFERENCE
