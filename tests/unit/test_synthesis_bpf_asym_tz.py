"""aurora72 A5-D 席（C13 非对称 TZ 支持；R3_followups §② #11 / R8_other_optimizations 面 1）：
synthesize_bpf_model 显式非对称 TZ 端到端（tz_mode="explicit"）+ W6-C 回代门不破。

#222 核实口径（本批实测）：
- 内核 cm_core inc2/inc3（2026-09-12/15）已有显式 TZ 面：_gcheb_prototype_
  explicit（共轭闭合=实系数 s 域谱分解；非闭合=复系数谱分解）+
  _cm_transversal_exact（复对称横向矩阵，Cameron 1999 §III-A complex-even/
  odd 实化——仓内核对注记 tests/unit/test_coupling_matrix.py C13 inc3 段
  "§III-A/B 原文已核对"）+ 注册计算器 coupling_matrix_synthesize_explicit；
- 但综合草稿入口 synthesize_bpf_model 仅 ± 成对口径（|Ω_z| 折叠符号、
  对数 ≤ order//2）——单个/奇数个纯虚轴非对称 TZ 的端到端综合（拓扑约简
  +回代门）缺位，本批以 tz_mode="explicit" 闭合。

文献锚口径（诚实分层，#118：读不到的原文不硬造数字）：
- 构造口径=文献锚：Cameron 1999 IEEE T-MTT 47(4) §III-A/B（Y 留数横向 +
  complex-even/odd 实化），原文核对先例见 test_coupling_matrix.py inc3 段；
- Cameron 原书非对称 TZ 例数值表未读到（同 C13 inc2 先例"原文未读到"如实
  记录），数值锚用三级独立来源：
  ① 解析不变量：TZ 处 |S21|=0（P(s) 根）、镜像侧 |S21|>0.1（非对称本体）、
    带边 |S11(1)|=ε/√(1+ε²)（RL 精确锚）、轴上幺正性 |S11|²+|S21|²=1；
  ② 双路径恒等：闭合显式集归并 ± 对后与既有 paired 路径逐位一致
    （显式独立谱分解 vs 老路径实测差 ~1e−15 非逐位，故闭合归并是逐位
    恒等的必要设计，见 synthesize_bpf_model docstring）；
  ③ 特征值锚（定理级预言：约简用复正交合同旋转 RMRᵀ，RᵀR=I ⟹ 相似
    变换 ⟹ 特征值不变）：N=3 单侧 TZ（Ω_z=+2.0、RL=22dB、"经典上阻带
    单陷波"非对称最小例）横向矩阵特征值全实，五元组常数钉住（探针
    实测，1e−6 回归锚），folded/arrow 输出矩阵特征值与横向矩阵一致
    ≤1e−9（实测 ~8e−13）。

超时保护：N=14 重例（实测 ~4.3s，LM 兜底网格 44 点）沿 W6-C 的
_with_budget 惯例（上限 90s ≈ 实测 20 倍）。
"""

from __future__ import annotations

import concurrent.futures
import math

import numpy as np
import pytest

import rfauto.core.calculators as calculators
from rfauto.core.calculators import (
    _cm_response_raw,
    _cm_transversal_exact,
    _gcheb_prototype_explicit,
)
from rfauto.core.synthesis import synthesize_bpf_model

_BUDGET_S = 90.0

# 特征值锚（N=3、RL=22dB、单侧 TZ Ω_z=+2.0；横向/folded 输出一致，升序）
_EIG_ANCHOR_N3_TZP2 = (-2.583794740298, -1.034616958936, 0.231616477154,
                       1.592488036007, 1.794307186073)
# folded 输出实数耦合锚（同例；anti 族单交叉 m13）
_M01_ANCHOR = 1.283595
_M12_ANCHOR = 1.091565
_M13_ANCHOR = -0.883737


def _with_budget(fn, *args, **kwargs):
    """超时保护：结果等待上限 _BUDGET_S（沿 W6-C 惯例）。"""
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


def _fz_for_omega(omega: float, f0: float = 2.4, fbw: float = 0.1) -> float:
    """归一化低通 Ω → 上阻带绝对频率 f_z（f_z>f0）：
    (f/f0 − f0/f)/fbw = Ω ⟹ f² − Ω·fbw·f0·f − f0² = 0 取正根。"""
    b = omega * fbw * f0
    return float((b + math.sqrt(b * b + 4.0 * f0 * f0)) / 2.0)


def _mirror_fz(fz: float, f0: float = 2.4) -> float:
    """镜像频率（几何对称 f0²/f_z）：显式口径下映射到 −Ω_z。"""
    return f0 * f0 / fz


def _from_pairs(matrix):
    return np.array([[c[0] + 1j * c[1] for c in row] for row in matrix])


# ─── ① 非对称单 TZ 端到端（folded 清洁例：N=3 单侧 TZ 落 anti 单族）─────────

def test_asym_single_tz_n3_folded_end_to_end():
    """N=3 单侧 TZ（Ω_z=+2.0，"经典上阻带单陷波"）端到端：复系数原型 →
    复对称横向 → folded 落 anti 单族清洁（pattern=0）；解析不变量四件套
    （TZ 深零/镜像侧非零/带边纹波/轴上幺正）+ 特征值锚（常数钉 + 相似
    不变性跨路径对照）。"""
    fz = _fz_for_omega(2.0)
    out = synthesize_bpf_model(order=3, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
                               transmission_zeros_ghz=[fz], tz_mode="explicit")
    assert out["ok"] is True, out.get("errors")
    assert out["tz_mode"] == "explicit"
    assert out["tz_conjugate_closed"] is False
    assert out["coefficient_domain"] == "complex"
    assert out["transmission_zeros_norm"] == [2.0]
    assert out["method"] == "cameron_residue"
    assert out["needs_calibration"] is False
    assert out["response_max_err"] < 1e-9
    assert out["cross_family"] == "anti"
    assert out["pattern_residual"] == 0.0
    assert any("非对称" in n for n in out["notes"])
    m = _from_pairs(out["coupling_matrix"])
    # 特征值锚：常数钉（1e−6 回归锚）+ 全实 + 相似不变性（横向 vs 约简）
    ev = sorted(np.linalg.eigvals(m), key=lambda v: v.real)
    assert len(ev) == 5
    for got, want in zip(ev, _EIG_ANCHOR_N3_TZP2, strict=True):
        assert abs(got.imag) < 1e-8
        assert got.real == pytest.approx(want, abs=1e-6)
    proto = _gcheb_prototype_explicit(3, 22.0, [2.0])
    ev_t = sorted(np.linalg.eigvals(_cm_transversal_exact(3, proto)),
                  key=lambda v: v.real)
    assert np.max(np.abs(np.asarray(ev_t) - np.asarray(ev))) < 1e-9
    # folded 实数耦合形态锚（anti 族单交叉；探针实测 1e−6 回归锚）
    assert m[0, 1].real == pytest.approx(_M01_ANCHOR, abs=1e-6)
    assert m[3, 4].real == pytest.approx(_M01_ANCHOR, abs=1e-6)
    assert m[1, 2].real == pytest.approx(_M12_ANCHOR, abs=1e-6)
    assert m[2, 3].real == pytest.approx(_M12_ANCHOR, abs=1e-6)
    assert m[1, 3].real == pytest.approx(_M13_ANCHOR, abs=1e-6)
    assert np.max(np.abs(m.imag)) < 1e-9
    # 解析锚：TZ 深零（P(s) 根）+ 镜像侧非零（非对称本体）
    _, s21_at = _cm_response_raw(m, 1.0, 1.0, 2.0)
    _, s21_mirror = _cm_response_raw(m, 1.0, 1.0, -2.0)
    assert abs(s21_at) < 1e-9
    assert abs(s21_mirror) > 0.1
    # 带边纹波解析锚（RL=22dB ⟹ ε/√(1+ε²)）+ 轴上幺正性
    eps = out["epsilon"]
    s11_edge = abs(_cm_response_raw(m, 1.0, 1.0, 1.0)[0])
    assert s11_edge == pytest.approx(eps / math.sqrt(1.0 + eps ** 2), abs=1e-9)
    for w in np.linspace(-1.0, 1.0, 121):
        s11, s21 = _cm_response_raw(m, 1.0, 1.0, float(w))
        assert abs(abs(s11) ** 2 + abs(s21) ** 2 - 1.0) < 1e-9


def test_asym_single_tz_lower_side_mirror():
    """下阻带单 TZ（Ω_z=−2.0，镜像频率）：零点落在 −2.0、+2.0 侧非零，
    folded 仍 anti 单族清洁——非对称符号口径双向生效。"""
    fz = _mirror_fz(_fz_for_omega(2.0))
    out = synthesize_bpf_model(order=3, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
                               transmission_zeros_ghz=[fz], tz_mode="explicit")
    assert out["ok"] is True, out.get("errors")
    assert out["transmission_zeros_norm"] == [-2.0]
    assert out["tz_conjugate_closed"] is False
    assert out["coefficient_domain"] == "complex"
    m = _from_pairs(out["coupling_matrix"])
    _, s21_at = _cm_response_raw(m, 1.0, 1.0, -2.0)
    _, s21_mirror = _cm_response_raw(m, 1.0, 1.0, 2.0)
    assert abs(s21_at) < 1e-9
    assert abs(s21_mirror) > 0.1
    assert out["cross_family"] == "anti"
    assert out["pattern_residual"] == 0.0


# ─── ② 退化恒等（闭合显式集 = paired 逐位）───────────────────────────────────

def test_asym_closed_explicit_bitwise_identity_with_paired():
    """退化恒等：explicit 模式给 ± 成对频率（共轭闭合）→ 归并 ± 对走既有
    实系数路径 ⟹ 除 tz_mode 自描述键外与 paired 同输入输出逐位一致
    （显式独立谱分解与老路径差 ~1e−15 非逐位，归并是逐位恒等的必要
    设计）。"""
    fz_hi = _fz_for_omega(2.0)
    fz_lo = _mirror_fz(fz_hi)
    kw = dict(order=4, f0_ghz=2.4, fbw=0.1, rl_db=22.0)
    paired = synthesize_bpf_model(**kw, transmission_zeros_ghz=[fz_hi])
    explicit = synthesize_bpf_model(**kw, transmission_zeros_ghz=[fz_hi, fz_lo],
                                    tz_mode="explicit")
    assert explicit["tz_mode"] == "explicit"
    assert explicit["tz_conjugate_closed"] is True
    assert explicit["coefficient_domain"] == "real"
    assert explicit["transmission_zeros_norm"] == [2.0]
    assert paired["transmission_zeros_norm"] == [2.0]
    prod_p = {k: v for k, v in paired.items() if k != "tz_mode"}
    prod_e = {k: v for k, v in explicit.items() if k != "tz_mode"}
    assert prod_e == prod_p
    # 同参数 strict 三态对闭合显式同样零足迹（沿 W6-C 语义）
    assert prod_e == {k: v for k, v in
                      synthesize_bpf_model(**kw,
                                           transmission_zeros_ghz=[fz_hi,
                                                                   fz_lo],
                                           tz_mode="explicit",
                                           strict=True).items()
                      if k != "tz_mode"}


# ─── ③ 多非对称 TZ：folded mixed 如实 + arrow 清洁稀疏 ──────────────────────

def test_asym_two_upper_tz_folded_mixed_honest_and_arrow_clean():
    """N=4 双上侧 TZ（Ω=+1.2/+2.5）：folded 交叉耦合族落 mixed、残留
    0.799035 如实返回（与 test_coupling_matrix FOLDED_COMPLEX_BOUNDARY
    同归一集同值——端到端与内核探针一致），ok 仍按频响判（True）；
    arrow 稀疏清洁（源行仅 m01、三对角块+载端星形）+ 双 TZ 深陷波。"""
    kw = dict(order=4, f0_ghz=2.4, fbw=0.1, rl_db=22.0, tz_mode="explicit")
    fzs = [_fz_for_omega(1.2), _fz_for_omega(2.5)]
    folded = synthesize_bpf_model(**kw, transmission_zeros_ghz=fzs)
    assert folded["ok"] is True
    assert folded["cross_family"] == "mixed"
    assert folded["pattern_residual"] == pytest.approx(0.799035, abs=1e-3)
    assert folded["response_max_err"] < 1e-9
    assert folded["coefficient_domain"] == "complex"
    arrow = synthesize_bpf_model(**kw, transmission_zeros_ghz=fzs,
                                 topology="arrow")
    assert arrow["ok"] is True
    assert arrow["response_max_err"] < 1e-9
    m = _from_pairs(arrow["coupling_matrix"])
    assert abs(m[0, 2]) < 1e-9 and abs(m[0, 3]) < 1e-9 and abs(m[0, 4]) < 1e-9
    assert abs(m[1, 3]) < 1e-9 and abs(m[1, 4]) < 1e-9
    for wz in (1.2, 2.5):
        assert abs(_cm_response_raw(m, 1.0, 1.0, wz)[1]) < 1e-9
    ev = sorted(np.linalg.eigvals(m), key=lambda v: (v.real, v.imag))
    proto = _gcheb_prototype_explicit(4, 22.0, [1.2, 2.5])
    ev_t = sorted(np.linalg.eigvals(_cm_transversal_exact(4, proto)),
                  key=lambda v: (v.real, v.imag))
    assert np.max(np.abs(np.asarray(ev_t) - np.asarray(ev))) < 1e-9


# ─── ④ 回代门不破（篡改注入两 layer）────────────────────────────────────────

def test_asym_gate_tamper_injection_main_layer_red(monkeypatch):
    """主门（1e−5）：非对称输入下注入坏耦合（+5e−2）→ strict 缺省 raise
    ValueError；strict=False → 旧 ok=False 形态（errors 携带详情）。"""
    orig = calculators._cm_reduce_folded

    def _corrupt(m, *a, **kw):
        mred, bad = orig(m, *a, **kw)
        mred = mred.copy()
        mred[1, 2] += 5e-2
        return mred, bad

    monkeypatch.setattr(calculators, "_cm_reduce_folded", _corrupt)
    kw = dict(order=3, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
              transmission_zeros_ghz=[_fz_for_omega(2.0)], tz_mode="explicit")
    with pytest.raises(ValueError, match="回代自洽失败"):
        synthesize_bpf_model(**kw)
    out = synthesize_bpf_model(**kw, strict=False)
    assert out["ok"] is False
    assert any("拓扑约简后频响偏差" in e for e in out["errors"])
    assert out["response_max_err"] > 1e-5


def test_asym_gate_tamper_injection_published_layer_red(monkeypatch):
    """产物门（1e−8）：非对称 arrow 路径注入 2e−7（低于主门容差）→ 仅
    出版形态回代能抓到 → strict raise"产物门"/strict=False ok=False。"""
    orig = calculators._cm_reduce_arrow

    def _corrupt_small(m, *a, **kw):
        m = orig(m, *a, **kw).copy()
        m[2, 3] += 2e-7
        return m

    monkeypatch.setattr(calculators, "_cm_reduce_arrow", _corrupt_small)
    kw = dict(order=3, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
              transmission_zeros_ghz=[_fz_for_omega(2.0)],
              topology="arrow", tz_mode="explicit")
    with pytest.raises(ValueError, match="产物门"):
        synthesize_bpf_model(**kw)
    out = synthesize_bpf_model(**kw, strict=False)
    assert out["ok"] is False
    assert any("出版矩阵回代偏差" in e for e in out["errors"])


# ─── ⑤ 校验错误面（显式口径专属）────────────────────────────────────────────

def test_asym_explicit_mode_validation_errors():
    """通带内 TZ / 显式个数超阶（≤order，非 order//2）/ tz_mode 非法——
    errors 信封如实。"""
    bad = synthesize_bpf_model(order=3, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
                               transmission_zeros_ghz=[2.42], tz_mode="explicit")
    assert bad["ok"] is False
    assert any("通带" in e for e in bad["errors"])
    bad2 = synthesize_bpf_model(order=2, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
                                transmission_zeros_ghz=[2.6, 2.8, 3.0],
                                tz_mode="explicit")
    assert bad2["ok"] is False
    assert any("超出阶数" in e for e in bad2["errors"])
    bad3 = synthesize_bpf_model(order=3, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
                                tz_mode="both")
    assert bad3["ok"] is False
    assert any("tz_mode" in e for e in bad3["errors"])
    # 显式口径 TZ 个数上限=order（成对口径=order//2 的松绑）：N=3 容 3 个
    ok3 = synthesize_bpf_model(order=3, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
                               transmission_zeros_ghz=[_fz_for_omega(1.5),
                                                       _fz_for_omega(2.0),
                                                       _fz_for_omega(2.5)],
                               tz_mode="explicit")
    assert ok3["ok"] is True
    assert ok3["transmission_zeros_norm"] == [1.5, 2.0, 2.5]


# ─── ⑥ N=14 性能/网格公式（min(max(41,3N+2),8N+9) 对非对称路径同款）─────────

def test_asym_n14_single_tz_lm_fallback_grid_formula(monkeypatch):
    """N=14 单侧 TZ（arrow）：闭式残差 ~3e−6 >1e−8 自然落 LM 兜底
    （method=cameron_residue+lm、needs_calibration=True），精化网格点数
    =公式 min(max(41,3N+2),8N+9)=44（与成对路径单源同款）；兜底后回代
    主门过（<1e−5）、TZ 深零 <1e−6、带内幺正 <1e−6（探针实测
    1.95e−10/2.6e−8/2.7e−9）。"""
    n_pts_seen: list[int] = []
    orig_polish = calculators._cm_polish

    def _spy(order, proto, ma0, wgrid, rounds=4):
        n_pts_seen.append(len(wgrid))
        return orig_polish(order, proto, ma0, wgrid, rounds=rounds)

    monkeypatch.setattr(calculators, "_cm_polish", _spy)
    out = _with_budget(synthesize_bpf_model, order=14, f0_ghz=2.4, fbw=0.1,
                       rl_db=22.0,
                       transmission_zeros_ghz=[_fz_for_omega(2.0)],
                       tz_mode="explicit", topology="arrow")
    assert out["ok"] is True, out.get("errors")
    assert out["method"] == "cameron_residue+lm"
    assert out["needs_calibration"] is True
    assert out["coefficient_domain"] == "complex"
    assert n_pts_seen == [min(max(41, 3 * 14 + 2), 8 * 14 + 9)]
    assert out["response_max_err"] < 1e-5
    m = _from_pairs(out["coupling_matrix"])
    assert abs(_cm_response_raw(m, 1.0, 1.0, 2.0)[1]) < 1e-6
    dev = max(abs(abs(_cm_response_raw(m, 1.0, 1.0, float(w))[0]) ** 2
                  + abs(_cm_response_raw(m, 1.0, 1.0, float(w))[1]) ** 2
                  - 1.0) for w in np.linspace(-1.0, 1.0, 41))
    assert dev < 1e-6
