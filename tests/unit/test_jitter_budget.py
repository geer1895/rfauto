"""F-E 件 4 抖动预算/双狄拉克 TJ 内核单测（研究扩充 round3 F-E 表件 4 判据）。

裁判口径（#118 双路径，不自证）：
- 路径 A = scipy.special.erfcinv（内核同源）；路径 B = scipy.stats.norm.isf
  （ndtri 独立实现）——两路径对 Q(1e-12) 逐位一致（7.034483825301131，
  2026-09-27 实测），白皮书引用值 7.0344（Stephens, Agilent 5989-3206EN；
  2Q=14.069 ≈ "pp≈14σ" 经验）符合到引用的 5 位有效数字。
- 前向合成 → 反演回收：注入 (σ_RJ, DJ_δδ) 生成两 BER 点 TJ，闭式反演
  逐位闭合（rel 1e-9 门）。
- 浴盆曲线与 TJ 的互证：{u: BER(u)≤target} 区域宽 vs EW=1−TJ(target)，
  深尾域对侧交叉项修正 <1e-20（模块 docstring 诚实边界 1 的实测残差面）。

si_channel 互证：si_channel 的 jitter_pp/jitter_rms 是确定性实测口径
（无 BER 语义），本文件只做类型级/恒等式级互证（2·Q(1e-12)=14.0690 vs
"14σ"经验），不混读两条口径的数值。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import norm

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import jitter_budget as jb
from rfauto.core import si_channel
from rfauto.service import jitter_budget_service as jsvc

# ─── 离线实测钉（双路径一致，见文件头；不臆造，#118）─────────────────────────
Q_1E12 = 7.034483825301131  # scipy.special.erfcinv 与 stats.norm.isf 逐位一致
TWO_Q_1E12 = 14.068967650602263  # = 2Q；对 "14" 经验的相对偏差 0.4926%
Q_1E6 = 4.753424308822899
Q_1E3 = 3.0902323061678136
#: 白皮书/行业引用值（5 位有效数字；非本文件计算值，来源见文件头）
Q_1E12_LITERATURE = 7.0344


# ─── 1. Q 函数：恒等式与独立双路径 ───────────────────────────────────────────


def test_q_from_ber_roundtrip_independent_forward():
    """Q=√2·erfcinv(2·BER) → 前向 erfc 回收 BER（erfc 与 erfcinv 互逆但独立方向）。"""
    for ber in (1e-14, 1e-12, 1e-9, 1e-6, 1e-3, 0.1):
        q = jb.q_from_ber(ber)
        ber_back = 0.5 * math.erfc(q / math.sqrt(2.0))
        assert ber_back == pytest.approx(ber, rel=1e-9)


def test_q_from_ber_1e12_bitwise_and_independent_paths():
    q = jb.q_from_ber(1e-12)
    assert q == Q_1E12  # 内核路径逐位钉（回归保护）
    assert q == float(norm.isf(1e-12))  # 独立实现路径（ndtri）逐位一致
    # 白皮书引用值（5 位有效数字）符合
    assert abs(q - Q_1E12_LITERATURE) < 1e-4


def test_two_q_1e12_matches_14_point_069_rule():
    """2·Q(1e-12) = 14.0690…"pp≈14σ" 经验法则的精确出处；偏差 0.4926% 钉死。"""
    two_q = 2.0 * jb.q_from_ber(1e-12)
    assert two_q == pytest.approx(TWO_Q_1E12, rel=1e-15)
    assert two_q == pytest.approx(14.069, abs=5e-4)
    rel_to_14 = (two_q - 14.0) / 14.0
    assert rel_to_14 == pytest.approx(0.004926260757304465, rel=1e-9)


def test_q_from_ber_input_guards():
    for bad in (0.0, 0.5, -0.1, 0.6, 1.0, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            jb.q_from_ber(bad)
    with pytest.raises(ValueError):
        jb.q_from_ber("abc")  # 非数值串；数值串按 aging 先例可转换


def test_gauss_tail_q_known_values():
    assert jb.gauss_tail_q(0.0) == 0.5  # 逐位（erfc(0)=1）
    assert jb.gauss_tail_q(1.0) == pytest.approx(float(norm.sf(1.0)), rel=1e-12)
    assert jb.gauss_tail_q(-1.0) == pytest.approx(1.0 - float(norm.sf(1.0)), rel=1e-12)
    assert jb.gauss_tail_q(3.0) == pytest.approx(float(norm.sf(3.0)), rel=1e-12)


# ─── 2. 双狄拉克 TJ ──────────────────────────────────────────────────────────


def test_tj_dual_dirac_offline_recycle_via_independent_quantile():
    """TJ = DJ + 2σ·Q(BER)：Q 用 stats.norm.isf 独立路径重算对照（#118）。"""
    for ber, sigma, dj in ((1e-12, 0.01, 0.3), (1e-6, 0.02, 0.15), (1e-3, 0.05, 0.4)):
        expected = dj + 2.0 * sigma * float(norm.isf(ber))
        assert jb.tj_dual_dirac(ber, sigma, dj) == pytest.approx(expected, rel=1e-12)
    # 离线实测钉：0.3 + 0.02·7.034483825301131
    assert jb.tj_dual_dirac(1e-12, 0.01, 0.3) == pytest.approx(0.44068967650602264, rel=1e-15)


def test_tj_sigma_zero_branch_exact():
    """σ_RJ=0（无随机展宽）：TJ=DJ 逐位恒等，任意合法 BER（规格预声明分支）。"""
    for ber in (1e-14, 1e-12, 1e-6, 1e-3, 0.4999):
        assert jb.tj_dual_dirac(ber, 0.0, 0.3) == 0.3
    assert jb.tj_dual_dirac(1e-12, 0.0, 0.0) == 0.0


def test_tj_monotone_and_ge_dj():
    """TJ>DJ（σ>0 时严格）；对 σ 与 D 单调不减。"""
    base = jb.tj_dual_dirac(1e-12, 0.01, 0.3)
    assert base > 0.3
    assert jb.tj_dual_dirac(1e-12, 0.02, 0.3) > base
    assert jb.tj_dual_dirac(1e-12, 0.01, 0.35) > base
    # BER 更宽松（更大）→ TJ 更小（Q 递减）
    assert jb.tj_dual_dirac(1e-6, 0.01, 0.3) < base


def test_tj_input_guards():
    with pytest.raises(ValueError):
        jb.tj_dual_dirac(1e-12, -0.01, 0.3)  # σ<0
    with pytest.raises(ValueError):
        jb.tj_dual_dirac(1e-12, 0.01, -0.3)  # D<0
    with pytest.raises(ValueError):
        jb.tj_dual_dirac(1e-12, True, 0.3)  # bool 显式拒收（df7+⑯）
    with pytest.raises(ValueError):
        jb.tj_dual_dirac(0.0, 0.01, 0.3)  # BER 守卫透传
    with pytest.raises(ValueError):
        jb.tj_dual_dirac(float("nan"), 0.01, 0.3)


# ─── 3. RJ/DJ 分离：前向合成 → 反演回收 ──────────────────────────────────────


@pytest.mark.parametrize(
    "sigma,dj,ber_lo,ber_hi",
    [
        (0.01, 0.3, 1e-12, 1e-6),
        (0.02, 0.15, 1e-11, 1e-4),
        (0.005, 0.5, 1e-12, 1e-9),
        (0.033, 0.0, 1e-12, 1e-8),
    ],
)
def test_separate_rj_dj_roundtrip_exact(sigma, dj, ber_lo, ber_hi):
    """注入 (σ, DJ) → 前向两点 TJ → 反演回收逐位（rel 1e-9 门，实际 ~1e-15）。"""
    tj_lo = jb.tj_dual_dirac(ber_lo, sigma, dj)
    tj_hi = jb.tj_dual_dirac(ber_hi, sigma, dj)
    fit = jb.separate_rj_dj((tj_lo, ber_lo), (tj_hi, ber_hi))
    assert fit.sigma_rj == pytest.approx(sigma, rel=1e-9)
    assert fit.dj_dd == pytest.approx(dj, rel=1e-9, abs=1e-15)
    # 点序无关（输入两点的先后不影响拟合结果）
    fit_rev = jb.separate_rj_dj((tj_hi, ber_hi), (tj_lo, ber_lo))
    assert fit_rev.sigma_rj == fit.sigma_rj
    assert fit_rev.dj_dd == fit.dj_dd


def test_separate_rj_dj_closed_form_cross_check():
    """对称闭式 DJ=(Q₁TJ₂−Q₂TJ₁)/(Q₁−Q₂) 与逐点回代 DJ=TJ₁−2Q₁σ 互证（双路径）。"""
    sigma, dj = 0.012, 0.22
    tj1, ber1 = jb.tj_dual_dirac(1e-12, sigma, dj), 1e-12
    tj2, ber2 = jb.tj_dual_dirac(1e-7, sigma, dj), 1e-7
    fit = jb.separate_rj_dj((tj1, ber1), (tj2, ber2))
    q1 = jb.q_from_ber(ber1)
    dj_point1 = tj1 - 2.0 * q1 * fit.sigma_rj
    assert fit.dj_dd == pytest.approx(dj_point1, rel=1e-9)
    # 输出按 BER 升序回显
    assert fit.ber_1 == ber1 and fit.ber_2 == ber2
    assert fit.to_dict()["sigma_rj"] == fit.sigma_rj


def test_separate_rj_dj_guards():
    tj12 = jb.tj_dual_dirac(1e-12, 0.01, 0.3)
    tj6 = jb.tj_dual_dirac(1e-6, 0.01, 0.3)
    with pytest.raises(ValueError):  # 两点 BER 相同 → 斜率不可辨
        jb.separate_rj_dj((0.4, 1e-12), (0.35, 1e-12))
    with pytest.raises(ValueError):  # σ=0：TJ 与 BER 无关
        jb.separate_rj_dj((tj6, 1e-12), (tj6, 1e-6))
    with pytest.raises(ValueError):  # 斜率反号：低 BER 反而 TJ 小
        jb.separate_rj_dj((tj6, 1e-12), (tj12, 1e-6))
    with pytest.raises(ValueError):  # TJ<0 非法
        jb.separate_rj_dj((-tj12, 1e-12), (tj6, 1e-6))
    with pytest.raises(ValueError):  # 点结构非法：长度 1
        jb.separate_rj_dj((tj12,), (tj6, 1e-6))
    with pytest.raises(ValueError):  # 点结构非法：长度 3
        jb.separate_rj_dj((tj12, 1e-12, 0.0), (tj6, 1e-6))
    with pytest.raises(ValueError):  # 点结构非法：非序列
        jb.separate_rj_dj("ab", (tj6, 1e-6))
    with pytest.raises(ValueError):  # 点内 BER 越界透传
        jb.separate_rj_dj((tj12, 0.7), (tj6, 1e-6))


# ─── 4. 浴盆曲线 ─────────────────────────────────────────────────────────────


def test_bathtub_minimum_at_dj_center():
    """最小点位于 DJ 两边缘（D/2 与 1−D/2）的中点 u=0.5（±半 UI 内 argmin 定位）。"""
    for sigma, dj in ((0.01, 0.3), (0.02, 0.0), (0.05, 0.6)):
        u, ber = jb.bathtub_curve(sigma, dj)
        step = u[1] - u[0]
        argmin = int(np.argmin(ber))
        assert abs(float(u[argmin]) - 0.5) <= step
    u, ber = jb.bathtub_curve(0.01, 0.3, n_points=801)
    assert u[int(np.argmin(ber))] == 0.5  # 网格含 0.5 时精确落点


def test_bathtub_symmetric_about_half_ui():
    """BER(u)=BER(1−u) 逐位对称。

    网格取 2⁶+1 点（步长 1/64 全部二进制精确）：u=k/64 时 1−u=(64−k)/64
    精确可表示，故 1−u 无舍入 → 两路表达式操作数逐位相同（IEEE 加法交换
    律）。非 dyadic 网格下 1−u 本身有末位舍入（Sterbenz 只对 u≥0.5 精确），
    逐位对称不成立属测试构造问题而非内核问题。
    """
    u, _ = jb.bathtub_curve(0.02, 0.3, n_points=65)
    ber = jb.bathtub_ber(u, 0.02, 0.3)
    assert np.array_equal(ber, jb.bathtub_ber(1.0 - u, 0.02, 0.3))  # 逐位对称


def test_bathtub_width_matches_eye_width():
    """{u: BER(u)≤target} 区域宽 ≈ EW=1−TJ(target)（对侧尾修正 <1e-20，rel 1e-9 门）。"""
    sigma, dj, target = 0.05, 0.2, 1e-6
    tub = lambda x: float(jb.bathtub_ber(x, sigma, dj)[0])  # noqa: E731

    lo, hi = 0.0, 0.5  # tub(0)≈0.98>target；tub(0.5)≈1e-15<target
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if tub(mid) > target:
            lo = mid
        else:
            hi = mid
    width = 1.0 - 2.0 * hi
    assert width == pytest.approx(jb.eye_width_ui(target, sigma, dj), rel=1e-9)


def test_bathtub_guards():
    with pytest.raises(ValueError):  # σ=0 退化阶跃 → 显式拒绝（确定性口径走 tj）
        jb.bathtub_ber(0.5, 0.0, 0.3)
    with pytest.raises(ValueError):  # DJ>1 UI 眼确定性全闭合
        jb.bathtub_ber(0.5, 0.01, 1.5)
    with pytest.raises(ValueError):
        jb.bathtub_ber([-0.1], 0.01, 0.3)
    with pytest.raises(ValueError):
        jb.bathtub_ber([float("nan")], 0.01, 0.3)
    with pytest.raises(ValueError):
        jb.bathtub_ber(True, 0.01, 0.3)
    with pytest.raises(ValueError):
        jb.bathtub_ber(np.array([[0.1, 0.2]]), 0.01, 0.3)
    with pytest.raises(ValueError):
        jb.bathtub_ber(np.array([True, False]), 0.01, 0.3)  # 布尔数组静默转 0/1 防御
    with pytest.raises(TypeError):
        jb.bathtub_curve(0.01, 0.3, n_points=True)
    with pytest.raises(ValueError):
        jb.bathtub_curve(0.01, 0.3, n_points=1)


# ─── 5. EW+TJ 恒等式与分量合成 ───────────────────────────────────────────────


def test_eye_width_plus_tj_identity_and_closure():
    """EW+TJ=1 UI 恒等式；超出闭合阈值时 EW 为负（如实返回不截断）。"""
    for sigma, dj, ber in ((0.01, 0.3, 1e-12), (0.02, 0.15, 1e-6), (0.05, 0.0, 1e-9)):
        tj = jb.tj_dual_dirac(ber, sigma, dj)
        ew = jb.eye_width_ui(ber, sigma, dj)
        assert ew == 1.0 - tj  # 同一表达式，逐位
        assert ew + tj == pytest.approx(1.0, abs=1e-12)
    # σ=0.1 @1e-12：TJ=1.407>1 → 眼闭合
    assert jb.eye_width_ui(1e-12, 0.1, 0.0) < 0.0


def test_combine_rj_rss():
    assert jb.combine_rj([3.0, 4.0]) == pytest.approx(5.0, rel=1e-12)
    assert jb.combine_rj([0.01, 0.02, 0.015]) == pytest.approx(
        float(np.linalg.norm(np.array([0.01, 0.02, 0.015]))), rel=1e-12
    )
    assert jb.combine_rj([0.05]) == 0.05  # 单源恒等
    assert jb.combine_rj([0.0, 0.02]) == 0.02  # 零源不计
    assert jb.combine_rj([]) == 0.0  # 空表 = 无随机源
    for bad in ([-1.0], [True], "abc", [0.01, [0.02]]):
        with pytest.raises((ValueError, TypeError)):
            jb.combine_rj(bad)


def test_compose_dj_pp_upper_bound():
    assert jb.compose_dj_pp(0.1, 0.05, 0.03) == pytest.approx(0.28, rel=1e-12)
    assert jb.compose_dj_pp(pj_amp_ui=0.1) == pytest.approx(0.2, rel=1e-12)
    assert jb.compose_dj_pp(dcd_pp_ui=0.0, buj_pp_ui=0.0) == 0.0  # 显式 0 合法（#364④）
    with pytest.raises(ValueError):  # 全缺省 = 无分量可合成
        jb.compose_dj_pp()
    with pytest.raises(ValueError):
        jb.compose_dj_pp(pj_amp_ui=-0.1)


def test_components_dataclass_budget_end_to_end():
    comp = jb.JitterComponents(rj_sigmas=[0.01, 0.02], pj_amp_ui=0.05, buj_pp_ui=0.02)
    sigma_total = comp.total_sigma_rj()
    dj_total = comp.total_dj_pp()
    assert sigma_total == pytest.approx(math.sqrt(0.01**2 + 0.02**2), rel=1e-15)
    assert dj_total == pytest.approx(0.12, rel=1e-12)
    # 预算面与内核单点函数逐位一致（DJ_δδ 取峰峰和上界口径）
    for ber in (1e-12, 1e-9, 1e-6):
        assert comp.tj_at_ber(ber) == jb.tj_dual_dirac(ber, sigma_total, dj_total)
        assert comp.eye_width_at_ber(ber) == jb.eye_width_ui(ber, sigma_total, dj_total)
    with pytest.raises(ValueError):
        jb.JitterComponents(rj_sigmas=[-0.01])
    with pytest.raises(ValueError):
        jb.JitterComponents(rj_sigmas="abc")
    with pytest.raises(ValueError):
        jb.JitterComponents(rj_sigmas=[], dcd_pp_ui=-1.0)


def test_dataclass_to_dict_json_serializable():
    fit = jb.separate_rj_dj(
        (jb.tj_dual_dirac(1e-12, 0.01, 0.3), 1e-12),
        (jb.tj_dual_dirac(1e-6, 0.01, 0.3), 1e-6),
    )
    comp = jb.JitterComponents(rj_sigmas=[0.01], pj_amp_ui=0.05)
    payload = {"fit": fit.to_dict(), "components": comp.to_dict()}
    text = json.dumps(payload)  # None/float 全部可序列化，无 ndarray 泄漏
    back = json.loads(text)
    assert back["fit"]["sigma_rj"] == pytest.approx(0.01, rel=1e-9)
    assert back["components"]["dcd_pp_ui"] is None
    assert back["components"]["sigma_rj_total"] == pytest.approx(0.01, rel=1e-15)


# ─── 6. 与 si_channel 互证接口 ───────────────────────────────────────────────


def test_rms_ui_to_sigma_rj_si_channel_interop():
    """类型级互证：σ_RJ 注入 si_channel.EyeMetrics 的抖动字段，双狄拉克 pp 口径自洽。"""
    sigma = 0.02
    rms = jb.rms_ui_to_sigma_rj(sigma)
    comp = jb.JitterComponents(rj_sigmas=[sigma])
    tj = comp.tj_at_ber(1e-12)
    m = si_channel.EyeMetrics(
        eye_height=1.0,
        eye_height_mean=1.0,
        eye_height_frac=1.0,
        eye_width_ui=comp.eye_width_at_ber(1e-12),
        jitter_pp_ui=tj,
        jitter_rms_ui=rms,
        optimal_phase_ui=0.5,
        level_one=1.0,
        level_zero=0.0,
        n_ones=100,
        n_zeros=100,
    )
    # 双狄拉克精确口径：pp = 2·Q(1e-12)·σ = 14.0690σ
    assert m.jitter_pp_ui == pytest.approx(TWO_Q_1E12 * sigma, rel=1e-15)
    assert m.to_dict()["jitter_rms_ui"] == rms
    # "≈14σ" 经验是它的舍入记忆：实测相对偏差 0.4926%
    rel = (m.jitter_pp_ui - 14.0 * sigma) / (14.0 * sigma)
    assert rel == pytest.approx(0.004926260757304465, rel=1e-9)


def test_rms_ui_to_sigma_rj_guards():
    assert jb.rms_ui_to_sigma_rj(0.01) == 0.01
    assert jb.rms_ui_to_sigma_rj(0.0) == 0.0
    for bad in (-0.01, True, float("nan")):
        with pytest.raises(ValueError):
            jb.rms_ui_to_sigma_rj(bad)


# ─── 7. service 薄壳（JSON 信封 ok=False 不抛）───────────────────────────────


def test_service_jitter_tj_envelope():
    data = jsvc.jitter_tj({"ber": 1e-12, "sigma_rj": 0.01, "dj_dd": 0.3})
    assert data["ok"] is True
    assert data["schema_version"] == jsvc.JITTER_BUDGET_SERVICE_SCHEMA_VERSION
    assert data["tj"]["1e-12"] == pytest.approx(jb.tj_dual_dirac(1e-12, 0.01, 0.3), rel=1e-15)
    data = jsvc.jitter_tj({"bers": [1e-6, 1e-12], "sigma_rj": 0.01, "dj_dd": 0.3})
    assert data["ok"] is True and set(data["tj"]) == {"1e-12", "1e-06"}
    for payload in (
        {"ber": 1e-12, "dj_dd": 0.3},  # 缺 sigma_rj
        {"ber": 1.5, "sigma_rj": 0.01, "dj_dd": 0.3},  # BER 越界
        {"ber": 1e-12, "bers": [1e-6], "sigma_rj": 0.01, "dj_dd": 0.3},  # 二选一
        {"sigma_rj": 0.01, "dj_dd": 0.3},  # 全缺 BER
        {"ber": True, "sigma_rj": 0.01, "dj_dd": 0.3},  # bool 拒收
    ):
        out = jsvc.jitter_tj(payload)
        assert out["ok"] is False, payload
        assert out["errors"]


def test_service_jitter_separate_roundtrip():
    tj12 = jb.tj_dual_dirac(1e-12, 0.01, 0.3)
    tj6 = jb.tj_dual_dirac(1e-6, 0.01, 0.3)
    data = jsvc.jitter_separate({"point_1": [tj12, 1e-12], "point_2": [tj6, 1e-6]})
    assert data["ok"] is True
    assert data["sigma_rj"] == pytest.approx(0.01, rel=1e-9)
    assert data["dj_dd"] == pytest.approx(0.3, rel=1e-9)
    assert data["fit"]["ber_1"] == 1e-12
    for payload in (
        {"point_1": [tj12], "point_2": [tj6, 1e-6]},  # 结构非法
        {"point_1": [tj12, 1e-12], "point_2": [tj12, 1e-12]},  # 内核守卫：同 BER
        {"point_1": [tj6, 1e-12], "point_2": [tj12, 1e-6]},  # 内核守卫：斜率反号
        {},  # 全缺
    ):
        out = jsvc.jitter_separate(payload)
        assert out["ok"] is False, payload
        assert out["errors"]


def test_service_jitter_budget_end_to_end():
    data = jsvc.jitter_budget_table(
        {"rj_sigmas": [0.01, 0.02], "pj_amp_ui": 0.05, "buj_pp_ui": 0.02, "bers": [1e-12]}
    )
    assert data["ok"] is True
    assert data["sigma_rj_total"] == pytest.approx(math.sqrt(0.01**2 + 0.02**2), rel=1e-15)
    assert data["dj_pp_total"] == pytest.approx(0.12, rel=1e-12)
    assert data["tj"]["1e-12"] == pytest.approx(
        jb.tj_dual_dirac(1e-12, data["sigma_rj_total"], 0.12), rel=1e-15
    )
    assert data["components"]["pj_amp_ui"] == 0.05
    # 缺省 BER 档位
    data = jsvc.jitter_budget_table({"rj_sigmas": [0.01]})
    assert data["ok"] is True and set(data["tj"]) == {"1e-12", "1e-09", "1e-06"}
    for payload in (
        {},  # 缺 rj_sigmas
        {"rj_sigmas": "x"},  # 非数组
        {"rj_sigmas": [0.01], "bers": [1.5]},  # BER 越界
        {"rj_sigmas": [0.01], "pj_amp_ui": -1.0},  # 负分量
    ):
        out = jsvc.jitter_budget_table(payload)
        assert out["ok"] is False, payload
        assert out["errors"]


def test_service_never_raises_on_garbage():
    """JSON 边界兜底：任何垃圾入参 → ok=False，绝不抛异常。"""
    for func in (jsvc.jitter_tj, jsvc.jitter_separate, jsvc.jitter_budget_table):
        for payload in (None, "x", 42, [1, 2], {"ber": object()}):
            out = func(payload)
            assert out["ok"] is False, (func.__name__, payload)
            assert out["errors"]
