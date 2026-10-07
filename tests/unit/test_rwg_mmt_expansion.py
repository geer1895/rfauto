"""ME-5 MMT 不连续性扩面（ge-me5）——感性销钉/谐振窗一阶闭式的离线判据。

独立双路径纪律（#118）：所有数值锚走两条不共享代码的路径——
(A) 被测函数（numpy 向量化级数，src/rfauto/core/rwg_mmt.py 增量段）；
(B) 本文件纯 math 标量循环重实现（式自原书页独立转录，代码形态不同）。
公式出处（原书 PDF 逐页多模态核对，ge-me5 批）：N. Marcuvitz, Waveguide
Handbook（MIT Rad Lab Vol.10, 1951）——感性销钉 §5.11(a) Eq.(1)/(2) 与
S₀/S₁ 级数 p.257-258；感性窗口 §5.2(a) Eq.(1a) p.221；容性窗口 §5.1(a)
对称款 Eq.(2a) p.218（含 Q₂ 与 (b/λ₀)² 修正项，全式三项）。

物理单调性判据（模型推导+实测双核，见被测函数 docstring）：
- 销钉：r↑ → |b|↑（开口趋短路）；r→0 → b→0（1/ln 慢极限，单调趋零断言）；
  offset 趋侧壁 → |b|↓（TE10 场强 sin² 弱化）；镜像 offset 逐位对称。
- 谐振窗：f_res 两侧 b_total 变号（感性↔容性）；w↑ → f_res 下移（趋截止）；
  h↑ → f_res 上移（b_C↓，与 w 反向——两极限夹逼全窗退化点）；er_fill↑ →
  f_res 下移（介质加载）。
"""
from __future__ import annotations

import math

import pytest

from rfauto.core.rwg_mmt import (
    Waveguide,
    inductive_post_susceptance,
    mode_basis,
    resonant_window_susceptance,
)

# WR-90 手算锚常量（公开手册表值：a=22.86mm、b=10.16mm、fc=6.557GHz）。
_C = 299.792458  # mm·GHz
_A = 22.86
_B = 10.16
_FC = 6.5571  # GHz（WR-90 公开手册表值 4 位有效；精确值=_C/(2×22.86)）
_F = 10.0  # GHz（fc<f<2fc=13.115 带内）


# ── 路径 B：纯 math 标量重实现（自原书式独立转录） ───────────────────────────


def _post_x_norm_scalar(f_ghz: float, a_mm: float, r_mm: float,
                        offset_mm: float = 0.0, n_sum: int = 20000) -> float:
    """感性销钉 x_norm=X/Z₀ 标量路径（§5.11(a) Eq.(1)；尾界 ≤1e-4）。"""
    lam0 = _C / f_ghz
    fc = _C / (2.0 * a_mm)
    lam_g = lam0 / math.sqrt(1.0 - (fc / f_ghz) ** 2)
    d = 2.0 * r_mm
    x = a_mm / 2.0 + offset_mm
    u = math.pi * x / a_mm
    gamma = 2.0 * a_mm / lam0
    s0_sum = 0.0
    s1_sum = 0.0
    for n in range(2, n_sum + 1):
        sn = math.sin(math.pi * x * n / a_mm)
        s2n = math.sin(2.0 * math.pi * x * n / a_mm)
        root = math.sqrt(n * n - gamma * gamma)
        s0_sum += sn * sn * (1.0 / root - 1.0 / n)
        s1_sum += s2n * (n / root - 1.0)
    s0 = (math.log((4.0 * a_mm / (math.pi * d)) * math.sin(u))
          - 2.0 * math.sin(u) ** 2 + 2.0 * s0_sum)
    s1 = 0.5 / math.tan(u) - math.sin(2.0 * u) + s1_sum
    bracket = (s0 - (math.pi * d / (2.0 * lam0)) ** 2
               - (math.pi * d / (2.0 * a_mm)) ** 2
               * (s0 / math.tan(u) - s1) ** 2)
    return (a_mm / (2.0 * lam_g)) * bracket / math.sin(u) ** 2


def _window_scalar(f_ghz: float, a_mm: float, b_mm: float, w_mm: float,
                   h_mm: float, er: float = 1.0) -> dict:
    """谐振窗 b_L/b_C/λg_res 标量路径（§5.2(a) 主项 + §5.1(a) Eq.(2a) 全式）。"""
    lam0 = _C / f_ghz
    fc = _C / (2.0 * a_mm)
    sq_er = math.sqrt(er)
    lam_g = lam0 / math.sqrt(er - (fc / f_ghz) ** 2)
    tw = math.pi * w_mm / (2.0 * a_mm)
    b_l = -(lam_g / a_mm) * (math.cos(tw) / math.sin(tw)) ** 2
    th = math.pi * h_mm / (2.0 * b_mm)
    sh = math.sin(th)
    ch = math.cos(th)
    q2 = 1.0 / math.sqrt(1.0 - (b_mm / (lam0 / sq_er)) ** 2) - 1.0
    l_c = (math.log(1.0 / sh)
           + q2 * ch ** 4 / (1.0 + q2 * sh ** 4)
           + (1.0 / 16.0) * (b_mm / (lam0 / sq_er)) ** 2
           * (1.0 - 3.0 * sh ** 2) ** 2 * ch ** 4)
    b_c = (4.0 * b_mm / lam_g) * l_c
    return {"b_l": b_l, "b_c": b_c, "b_total": b_l + b_c,
            "lam_g_res": math.tan(tw) * math.sqrt(4.0 * a_mm * b_mm * l_c)}


# ── 感性销钉 ─────────────────────────────────────────────────────────────────


class TestInductivePost:
    def test_wr90_center_anchor_dual_path(self) -> None:
        """主锚：WR-90 居中 r=1mm@10GHz——路径 A vs 路径 B（rel 1e-3，
        远高于级数尾界差、远低于任何转录错误量级）；感性为负。"""
        out = inductive_post_susceptance(_F, _A, 1.0)
        ref_x = _post_x_norm_scalar(_F, _A, 1.0)
        assert out["x_norm"] == pytest.approx(ref_x, rel=1e-3)
        assert out["b_norm"] == pytest.approx(-1.0 / ref_x, rel=1e-3)
        assert out["b_norm"] < 0.0
        assert out["x_norm"] > 0.0

    def test_r_to_zero_b_monotone_to_zero(self) -> None:
        """微扰极限连续性：r→0 时 b_norm 单调趋零（1/ln 慢极限——绝对阈值
        断言对该规律物理不成立，按单调趋零+量级压缩断言）。"""
        bs = [abs(inductive_post_susceptance(_F, _A, r)["b_norm"])
              for r in (1e-3, 1e-2, 0.05, 0.2, 1.0)]
        assert bs == sorted(bs)
        assert bs[0] < 0.2 * bs[-1]
        # x_norm（并联电抗）反向趋于开路
        xs = [inductive_post_susceptance(_F, _A, r)["x_norm"]
              for r in (1.0, 0.2, 0.05)]
        assert xs == sorted(xs)

    def test_radius_monotonic_abs_b(self) -> None:
        """r↑ → |b|↑ 严格单调（杆变粗→并联电纳趋短路，物理方向）。"""
        bs = [abs(inductive_post_susceptance(_F, _A, r)["b_norm"])
              for r in (0.2, 0.5, 0.8, 1.1)]
        assert bs == sorted(bs)
        assert len(set(bs)) == 4

    def test_n_posts_parallel_exact_and_independent(self) -> None:
        """n 根并联口径：b(n)=n×b(1) 精确成立；单杆值与独立标量路径对拍。"""
        b1 = inductive_post_susceptance(_F, _A, 0.8)["b_norm"]
        b3 = inductive_post_susceptance(_F, _A, 0.8, n_posts=3)["b_norm"]
        assert b3 == 3.0 * b1
        ref = -1.0 / _post_x_norm_scalar(_F, _A, 0.8)
        assert b1 == pytest.approx(ref, rel=1e-3)

    def test_lambda_g_identity_vs_mode_basis_and_hand(self) -> None:
        """λg=λ0/√(1−(fc/f)²) 双锚：既有 mode_basis β（SI 路径）逐位 + 手算
        常量（WR-90 fc=6.557GHz 公开表值）独立复算。"""
        out = inductive_post_susceptance(_F, _A, 1.0)
        wg = Waveguide(a=_A * 1e-3, b=_B * 1e-3)
        beta = float(mode_basis(wg, 1, _F * 1e9).beta[0].real)
        assert out["lambda_g_mm"] == pytest.approx(2.0 * math.pi / beta * 1e3,
                                                   rel=1e-12)
        lam_g_hand = (299.792458 / _F
                      / math.sqrt(1.0 - (_FC / _F) ** 2))
        assert out["lambda_g_mm"] == pytest.approx(lam_g_hand, rel=1e-4)
        assert out["lambda_0_mm"] == pytest.approx(299.792458 / _F, rel=1e-12)

    def test_offset_mirror_symmetry_exact(self) -> None:
        """镜像对称：±offset 的 b_norm 逐位一致（TE10 场对中线偶对称）。"""
        b_plus = inductive_post_susceptance(_F, _A, 0.8, offset_mm=3.0)["b_norm"]
        b_minus = inductive_post_susceptance(_F, _A, 0.8, offset_mm=-3.0)["b_norm"]
        assert b_plus == b_minus

    def test_offset_toward_wall_weakens(self) -> None:
        """offset 趋侧壁 → |b| 单调弱化（TE10 场 sin(πx/a) 强度弱化，一阶）。"""
        b0 = abs(inductive_post_susceptance(_F, _A, 0.8)["b_norm"])
        b2 = abs(inductive_post_susceptance(_F, _A, 0.8, offset_mm=2.0)["b_norm"])
        b4 = abs(inductive_post_susceptance(_F, _A, 0.8, offset_mm=4.0)["b_norm"])
        assert b0 > b2 > b4 > 0.0

    def test_x_series_norm_matches_book_eq2(self) -> None:
        """串联臂 X_b/Z₀=(a/λg)(πd/a)²sin²(πx/a)（Eq.(2)）手算恒等式。"""
        out = inductive_post_susceptance(_F, _A, 1.0, offset_mm=2.0)
        u = math.pi * out["x_over_a"]
        expect = (_A / out["lambda_g_mm"]) * (math.pi * out["d_over_a"]) ** 2 \
            * math.sin(u) ** 2
        assert out["x_series_norm"] == pytest.approx(expect, rel=1e-12)

    def test_below_cutoff_raises(self) -> None:
        with pytest.raises(ValueError, match="fc"):
            inductive_post_susceptance(6.0, _A, 1.0)

    def test_at_cutoff_raises(self) -> None:
        with pytest.raises(ValueError, match="2fc"):
            inductive_post_susceptance(_C / (2.0 * _A), _A, 1.0)

    def test_above_2fc_raises(self) -> None:
        """原书限制 a<λ<2a 上界（TE20 项在 2fc 发散）强制。"""
        with pytest.raises(ValueError, match="2fc"):
            inductive_post_susceptance(13.5, _A, 1.0)

    def test_d_over_a_limit_raises(self) -> None:
        with pytest.raises(ValueError, match=r"0\.10"):
            inductive_post_susceptance(_F, _A, 1.15)

    def test_offset_out_of_valid_window_raises(self) -> None:
        with pytest.raises(ValueError, match="x/a"):
            inductive_post_susceptance(_F, _A, 0.8, offset_mm=7.0)
        with pytest.raises(ValueError, match="x/a"):
            inductive_post_susceptance(_F, _A, 0.8, offset_mm=-7.5)

    def test_bool_and_bad_scalar_inputs_raise(self) -> None:
        with pytest.raises(ValueError, match="bool"):
            inductive_post_susceptance(True, _A, 1.0)
        with pytest.raises(ValueError, match="bool"):
            inductive_post_susceptance(_F, False, 1.0)
        with pytest.raises(ValueError, match="正数"):
            inductive_post_susceptance(_F, _A, 0.0)
        with pytest.raises(ValueError, match="bool"):
            inductive_post_susceptance(_F, _A, 1.0, n_posts=True)
        with pytest.raises(ValueError, match="正整数"):
            inductive_post_susceptance(_F, _A, 1.0, n_posts=2.5)
        with pytest.raises(ValueError, match="bool"):
            inductive_post_susceptance(_F, _A, 1.0, offset_mm=True)
        with pytest.raises(ValueError):
            inductive_post_susceptance(_F, _A, 1.0, n_posts=0)


# ── 谐振窗 ───────────────────────────────────────────────────────────────────


class TestResonantWindow:
    def test_branch_signs_and_total_identity(self) -> None:
        out = resonant_window_susceptance(_F, _A, _B, 12.0, 5.0)
        assert out["b_inductive"] < 0.0 < out["b_capacitive"]
        assert out["b_total"] == out["b_inductive"] + out["b_capacitive"]
        assert out["f_resonant_ghz_est"] is not None

    def test_dual_path_anchor_b_l_b_c(self) -> None:
        """主锚：b_L/b_C 与独立标量路径逐位对拍（含 Eq.(2a) 三项修正）。"""
        out = resonant_window_susceptance(_F, _A, _B, 12.0, 5.0)
        ref = _window_scalar(_F, _A, _B, 12.0, 5.0)
        assert out["b_inductive"] == pytest.approx(ref["b_l"], rel=1e-12)
        assert out["b_capacitive"] == pytest.approx(ref["b_c"], rel=1e-12)
        # 手算量级锚：b_L(12mm)≈−1.48（cot²=0.859、λg/a=1.737）；b_C≈0.385
        assert -1.6 < out["b_inductive"] < -1.4
        assert 0.35 < out["b_capacitive"] < 0.42

    def test_sign_flip_across_f_res(self) -> None:
        """谐振判据核心：f_res 两侧 b_total 变号（感性↔容性过渡），判读用
        独立标量路径（±6% 余量，远大于修正项引起的根移 ~1%）。"""
        f_res = resonant_window_susceptance(_F, _A, _B, 12.0, 5.0)["f_resonant_ghz_est"]
        assert f_res is not None
        below = _window_scalar(f_res * 0.94, _A, _B, 12.0, 5.0)["b_total"]
        above = _window_scalar(f_res * 1.06, _A, _B, 12.0, 5.0)["b_total"]
        assert below < 0.0 < above

    def test_f_res_solves_model_exactly(self) -> None:
        """解析零点自洽：λg_eff(f_res)=λg_res（λg_res 由测试独立按窗口闭式
        重算；λg_eff 的 fc 用精确除法——本钉验根的代数，非截止常数精度）。"""
        out = resonant_window_susceptance(_F, _A, _B, 12.0, 5.0)
        f_res = out["f_resonant_ghz_est"]
        assert f_res is not None
        ref = _window_scalar(_F, _A, _B, 12.0, 5.0)
        lam_g_at = (299.792458 / f_res
                    / math.sqrt(1.0 - (_C / (2.0 * _A) / f_res) ** 2))
        assert lam_g_at / ref["lam_g_res"] == pytest.approx(1.0, rel=1e-9)

    def test_f_res_decreases_with_window_width(self) -> None:
        """w↑ → f_res 单调下移（感性碍量 cot²↓；w→a 极限 f_res→fc⁺）。"""
        fress = [resonant_window_susceptance(_F, _A, _B, w, 5.0)["f_resonant_ghz_est"]
                 for w in (8.0, 10.0, 12.0, 14.0)]
        assert all(f is not None for f in fress)
        assert fress == sorted(fress, reverse=True)
        assert len(set(fress)) == 4

    def test_f_res_increases_with_window_height(self) -> None:
        """h↑ → f_res 单调上移（容性碍量 L_C↓；h→b 极限 f_res→∞）——与 w
        反向，两极限夹逼全窗退化点（docstring 推导+数值双核）。"""
        fress = [resonant_window_susceptance(_F, _A, _B, 12.0, h)["f_resonant_ghz_est"]
                 for h in (4.0, 5.0, 6.0, 7.0)]
        assert all(f is not None for f in fress)
        assert fress == sorted(fress)
        assert len(set(fress)) == 4

    def test_er_fill_downshifts_f_res(self) -> None:
        """er_fill>1 → f_res 下移（介质加载物理，√εr 标度）。"""
        f_air = resonant_window_susceptance(_F, _A, _B, 12.0, 5.0)["f_resonant_ghz_est"]
        f_diel = resonant_window_susceptance(_F, _A, _B, 12.0, 5.0,
                                             er_fill=2.25)["f_resonant_ghz_est"]
        assert f_air is not None and f_diel is not None
        assert f_diel < f_air
        assert f_air / f_diel == pytest.approx(math.sqrt(2.25), rel=5e-2)

    def test_er_fill_1_identity_with_default(self) -> None:
        """显式 er_fill=1 与缺省逐键相等（df5 公开仓经验②：旋钮语义钉）。"""
        out1 = resonant_window_susceptance(_F, _A, _B, 12.0, 5.0, er_fill=1.0)
        out0 = resonant_window_susceptance(_F, _A, _B, 12.0, 5.0)
        assert out1 == out0

    def test_susceptances_monotone_in_frequency(self) -> None:
        """物理方向：近截止 b_L→−∞（发散方向）；b_C 随 f 增大。"""
        b_l_low = resonant_window_susceptance(6.7, _A, _B, 12.0, 5.0)["b_inductive"]
        b_l_mid = resonant_window_susceptance(_F, _A, _B, 12.0, 5.0)["b_inductive"]
        b_l_high = resonant_window_susceptance(12.5, _A, _B, 12.0, 5.0)["b_inductive"]
        assert b_l_low < b_l_mid < b_l_high < 0.0
        b_c_low = resonant_window_susceptance(6.7, _A, _B, 12.0, 5.0)["b_capacitive"]
        b_c_high = resonant_window_susceptance(12.5, _A, _B, 12.0, 5.0)["b_capacitive"]
        assert 0.0 < b_c_low < b_c_high

    def test_full_window_transparent_degenerate(self) -> None:
        """全高全宽窗=无扰动透明面：b_total≡0、无谐振（None 如实）。"""
        out = resonant_window_susceptance(_F, _A, _B, _A, _B)
        assert out["b_total"] == pytest.approx(0.0, abs=1e-12)
        assert out["f_resonant_ghz_est"] is None

    def test_pure_inductive_no_root(self) -> None:
        """h=b（无 b 向缩窄）：b_C≡0、b_total<0 纯感性、无带内零点。"""
        out = resonant_window_susceptance(_F, _A, _B, 12.0, _B)
        assert out["b_capacitive"] == pytest.approx(0.0, abs=1e-12)
        assert out["b_total"] < 0.0
        assert out["f_resonant_ghz_est"] is None

    def test_pure_capacitive_no_root(self) -> None:
        """w=a（无 a 向缩窄）：b_L≡0、b_total>0 纯容性、无带内零点。"""
        out = resonant_window_susceptance(_F, _A, _B, _A, 5.0)
        assert out["b_inductive"] == pytest.approx(0.0, abs=1e-12)
        assert out["b_total"] > 0.0
        assert out["f_resonant_ghz_est"] is None

    def test_lambda_g_matches_post_path(self) -> None:
        """λg 口径跨函数一致（同频同波导逐位同值）。"""
        wp = resonant_window_susceptance(_F, _A, _B, 12.0, 5.0)
        po = inductive_post_susceptance(_F, _A, 1.0)
        assert wp["lambda_g_mm"] == po["lambda_g_mm"]
        assert wp["lambda_0_mm"] == po["lambda_0_mm"]

    def test_guards_raise(self) -> None:
        """守卫面：f≤fc/超口径尺寸/er<1/bool 全部 ValueError。"""
        with pytest.raises(ValueError, match="截止"):
            resonant_window_susceptance(6.0, _A, _B, 12.0, 5.0)
        with pytest.raises(ValueError, match="截止"):
            resonant_window_susceptance(_C / (2.0 * _A), _A, _B, 12.0, 5.0)
        with pytest.raises(ValueError, match="a_mm"):
            resonant_window_susceptance(_F, _A, _B, 25.0, 5.0)
        with pytest.raises(ValueError, match="b_mm"):
            resonant_window_susceptance(_F, _A, _B, 12.0, 11.0)
        with pytest.raises(ValueError, match="er_fill"):
            resonant_window_susceptance(_F, _A, _B, 12.0, 5.0, er_fill=0.9)
        with pytest.raises(ValueError, match="bool"):
            resonant_window_susceptance(True, _A, _B, 12.0, 5.0)
        with pytest.raises(ValueError, match="bool"):
            resonant_window_susceptance(_F, _A, _B, False, 5.0)
        with pytest.raises(ValueError, match="bool"):
            resonant_window_susceptance(_F, _A, _B, 12.0, 5.0, er_fill=True)
        with pytest.raises(ValueError, match="正数"):
            resonant_window_susceptance(_F, _A, _B, 0.0, 5.0)
        with pytest.raises(ValueError, match="正数"):
            resonant_window_susceptance(_F, -_A, _B, 12.0, 5.0)
