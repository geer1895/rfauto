"""df7_dp1fix 缺陷②/① 回归钉：镜像对称门 + 级联星积独立裁判 + judge
模态重建 s22≠s11 fixture（判据 runs/df7_dp1fix/criteria.md §2/§5，先写后跑）。

背景（战役 followUp 登记）：
- 缺陷②：solve_chain 镜像对称链 S11≠S22（@10GHz 相位差 31.7°）——两根因
  Fix-A=gsm_cascade s12/s21 中间逆互换；Fix-B=窄→宽结面按 canonical（宽→窄）
  计算后 gsm_flip 精确翻转（反向 Petrov 重解非镜像协变）。
- 缺陷①：judge mmt_modal_s 以 [[s11,s21],[s21,s11]] 对称假定重建，而归档
  meta s22≠s11——模态腿污染（judge −13.146 vs 真模态 −12.957 dB @8GHz）。

门（criteria §2 数值写死）：镜像对称链 max|S11−S22|、max|S12−S21|（复模）
≤1e-9；级联回收 vs 独立线性方程组重解 ≤1e-12；judge 重建 renorm 往返
≤1e-12。真机零依赖，秒级。
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.rwg_mmt import (
    Gsm,
    HStepJunction,
    InductiveIris,
    ModePolicy,
    UniformSection,
    Waveguide,
    aperture_h_matrix,
    gsm_cascade,
    gsm_flip,
    junction_gsm,
    mode_basis,
    mode_counts,
    solve_chain,
)

WR90 = Waveguide(a=22.86e-3, b=10.16e-3)
F10 = 10e9
SYM_TOL = 1e-9  # 镜像对称门（criteria §2 写死；实测 ~1e-14 量级，留余量）

_CH_T0 = [UniformSection(WR90, 10e-3), InductiveIris(WR90, 16e-3, 0.0),
          UniformSection(WR90, 10e-3)]
_CH_T1 = [UniformSection(WR90, 10e-3), InductiveIris(WR90, 16e-3, 1e-3),
          UniformSection(WR90, 10e-3)]


def _sym_dev(s: np.ndarray) -> dict[str, float]:
    return {"s11_s22": float(np.max(np.abs(s[:, 0, 0] - s[:, 1, 1]))),
            "s12_s21": float(np.max(np.abs(s[:, 0, 1] - s[:, 1, 0])))}


class TestMirrorSymmetryGates:
    """门 S1-S3（criteria §2 写死）：对称链 S11==S22、S12==S21 数值门。"""

    def test_gate_s1_mirror_straight_trivial(self):
        """镜像直链：S11=S22=0、S12=S21=e^{−jβL} 逐位（端口索引排除钉）。"""
        res = solve_chain([UniformSection(WR90, 0.02)], np.array([F10]),
                          ModePolicy(n_doublings_max=0))
        s = res.s2x2[0]
        assert s[0, 0] == 0.0 and s[1, 1] == 0.0
        assert s[0, 1] == s[1, 0]
        assert abs(s[0, 1]) == 1.0

    def test_gate_s2_zero_thickness_iris(self):
        res = solve_chain(_CH_T0, np.array([8e9, 10e9, 10.5e9, 12e9]),
                          ModePolicy(n_modes_ref=21, n_doublings_max=0))
        dev = _sym_dev(res.s2x2)
        assert dev["s11_s22"] <= SYM_TOL, f"S11≠S22: {dev}"
        assert dev["s12_s21"] <= SYM_TOL, f"S12≠S21: {dev}"

    def test_gate_s3_thick_iris(self):
        res = solve_chain(_CH_T1, np.array([8e9, 10e9, 12e9]),
                          ModePolicy(n_modes_ref=21, n_doublings_max=0))
        dev = _sym_dev(res.s2x2)
        assert dev["s11_s22"] <= SYM_TOL, f"S11≠S22: {dev}"
        assert dev["s12_s21"] <= SYM_TOL, f"S12≠S21: {dev}"

    def test_mirror_symmetry_holds_under_default_policy(self):
        """×2 收敛门全开（缺省策略）下对称性仍是代数恒等（收敛档无关）。"""
        res = solve_chain(_CH_T0, np.array([10e9]))
        assert res.converged
        dev = _sym_dev(res.s2x2)
        assert dev["s11_s22"] <= SYM_TOL and dev["s12_s21"] <= SYM_TOL


class TestJunctionFlipSemantics:
    """Fix-B 语义钉：flip=块交换；镜像链恒等式 flip(C)=C；窄→宽翻转生效。"""

    def test_gsm_flip_block_swap(self):
        g = Gsm(s11=np.array([[1 + 2j]]), s12=np.array([[3 + 4j]]),
                s21=np.array([[5 + 6j]]), s22=np.array([[7 + 8j]]))
        f = gsm_flip(g)
        assert f.s11[0, 0] == 7 + 8j and f.s22[0, 0] == 1 + 2j
        assert f.s12[0, 0] == 5 + 6j and f.s21[0, 0] == 3 + 4j
        assert gsm_flip(f).s11[0, 0] == 1 + 2j  # 对合

    def test_chain_flip_invariance_iris(self):
        """C=J⋆T⋆flip(J) 满足 flip(C)=C → S11=S22（Fix-B 代数保证）。"""
        res = solve_chain(_CH_T0, np.array([F10]), ModePolicy(n_doublings_max=0))
        dev = _sym_dev(res.s2x2)
        assert dev["s11_s22"] <= SYM_TOL and dev["s12_s21"] <= SYM_TOL

    def test_wide_to_narrow_unchanged_and_narrow_to_wide_is_flip(self):
        """canonical 方向（宽→窄）保持直接计算；窄→宽=孪生翻转（非原值）。"""
        sub = Waveguide(a=16e-3, b=10.16e-3)
        freqs = np.array([F10])
        pol = ModePolicy(n_modes_ref=6, n_doublings_max=0)
        n_main, n_sub = mode_counts([WR90.a, sub.a], pol)
        # 宽→窄（a_left>a_right）走原路径：与手工 junction 直解逐位一致
        fwd = HStepJunction(WR90, sub, x0_m=(WR90.a - sub.a) / 2,
                            aperture_m=sub.a, offset_left_m=0.0,
                            offset_right_m=(WR90.a - sub.a) / 2)
        res_fwd = solve_chain([fwd], freqs, pol)
        bm = mode_basis(WR90, n_main, F10)
        bs = mode_basis(sub, n_sub, F10)
        x0 = (WR90.a - sub.a) / 2
        h = aperture_h_matrix(bm, bs, x0, sub.a, offset1=0.0, offset2=x0)
        g_direct = junction_gsm(h, bm.z_te, bs.z_te)
        assert res_fwd.s2x2[0, 0, 0] == g_direct.s11[0, 0]
        assert res_fwd.s2x2[0, 1, 1] == g_direct.s22[0, 0]
        # 窄→宽：修前=反向直接重解；修后=flip(宽→窄)——两者不相等即钉住
        # 修复生效（缺陷②根因面），且新值满足镜像恒等（对偶链验证）
        back = HStepJunction(sub, WR90, x0_m=(WR90.a - sub.a) / 2,
                             aperture_m=sub.a, offset_left_m=(WR90.a - sub.a) / 2,
                             offset_right_m=0.0)
        res_back = solve_chain([back], freqs, pol)
        assert res_back.s2x2[0, 0, 0] == g_direct.s22[0, 0]
        assert res_back.s2x2[0, 1, 1] == g_direct.s11[0, 0]
        assert res_back.s2x2[0, 0, 1] == g_direct.s21[0, 0]
        assert res_back.s2x2[0, 1, 0] == g_direct.s12[0, 0]
        # 反向直接重解（旧路径值）≠ 翻转值（根因在档，非平凡恒等）
        h_b = aperture_h_matrix(bs, bm, x0, sub.a, offset1=x0, offset2=0.0)
        g_old = junction_gsm(h_b, bs.z_te, bm.z_te)
        assert abs(complex(g_old.s11[0, 0]) - complex(g_direct.s22[0, 0])) > 1e-9

    def test_equal_width_junction_not_flipped(self):
        """等宽结面（εr 台阶）不触发翻转：H 为口径 Gram 对称阵，镜像协变。"""
        wg2 = Waveguide(a=WR90.a, b=WR90.b, eps_r=2.04)
        res = solve_chain(
            [HStepJunction(WR90, wg2, x0_m=0.0, aperture_m=WR90.a)],
            np.array([F10]), ModePolicy(n_modes_ref=1, n_doublings_max=0))
        b1 = mode_basis(WR90, 1, F10)
        b2 = mode_basis(wg2, 1, F10)
        gamma = (b2.z_te[0] - b1.z_te[0]) / (b2.z_te[0] + b1.z_te[0])
        assert abs(res.s2x2[0, 0, 0] - gamma) < 1e-12  # 既有 A2 锚不变


class TestCascadeIndependentReferee:
    """Fix-A 回归钉：星积 vs 独立界面线性方程组重解（#118 独立裁判）。"""

    @staticmethod
    def _ref_cascade(a: Gsm, b: Gsm) -> np.ndarray:
        nmid = a.n_out
        eye = np.eye(nmid)
        n1, n3 = a.n_in, b.n_out
        out = np.zeros((2, 2), complex)
        cols = []
        for a1, a3 in (np.eye(n1), np.zeros((n3, n1))), \
                      (np.zeros((n1, n3)), np.eye(n3)):
            u = np.linalg.solve(np.block([[eye, -a.s22], [-b.s11, eye]]),
                                np.vstack([a.s21 @ a1, b.s12 @ a3]))
            a2p, a2m = u[:nmid], u[nmid:]
            cols.append((a.s11 @ a1 + a.s12 @ a2m, b.s21 @ a2p + b.s22 @ a3))
        out[0, 0] = cols[0][0][0, 0]
        out[1, 0] = cols[0][1][0, 0]
        out[0, 1] = cols[1][0][0, 0]
        out[1, 1] = cols[1][1][0, 0]
        return out

    @staticmethod
    def _rand_recip(rng: np.random.Generator, n1: int, n2: int) -> Gsm:
        """随机互易 Gsm：全阵对称（s11/s22 对称 + s12=s21ᵀ，同 junction 形）。"""

        def cmplx(shape):
            return (rng.uniform(-0.4, 0.4, shape)
                    + 1j * rng.uniform(-0.4, 0.4, shape))

        def sym(n: int) -> np.ndarray:
            m = cmplx((n, n))
            return m + m.T  # 对称化（级联互易恒等式前提：s11/s22 对称）

        m = cmplx((n1, n2))
        return Gsm(s11=sym(n1), s12=m, s21=m.T.copy(), s22=sym(n2))

    def test_random_reciprocal_blocks_match_linear_solve(self):
        rng = np.random.default_rng(42)
        for na1, nmid, nb2 in ((2, 4, 3), (3, 3, 3), (5, 2, 2)):
            a = self._rand_recip(rng, na1, nmid)
            b = self._rand_recip(rng, nmid, nb2)
            got = np.array([[gsm_cascade(a, b).s11[0, 0], gsm_cascade(a, b).s12[0, 0]],
                            [gsm_cascade(a, b).s21[0, 0], gsm_cascade(a, b).s22[0, 0]]])
            ref = self._ref_cascade(a, b)
            assert float(np.max(np.abs(got - ref))) <= 1e-12

    def test_cascade_reciprocity_exact_for_reciprocal_blocks(self):
        rng = np.random.default_rng(7)
        a = self._rand_recip(rng, 2, 3)
        b = self._rand_recip(rng, 3, 4)
        c = gsm_cascade(a, b)
        assert float(np.max(np.abs(c.s12 - c.s21.T))) <= 1e-12

    def test_physical_chain_cascade_matches_tl_closed_form(self):
        """既有 A3 锚（εr 台阶双段级联 vs TL ABCD）修后仍绿（不变面）。"""
        wg2 = Waveguide(a=WR90.a, b=WR90.b, eps_r=2.04)
        length1, length2 = 0.012, 0.018
        res = solve_chain(
            [UniformSection(WR90, length1),
             HStepJunction(WR90, wg2, x0_m=0.0, aperture_m=WR90.a),
             UniformSection(wg2, length2)],
            np.array([F10]), ModePolicy(n_modes_ref=1, n_doublings_max=0))
        k0 = 2 * np.pi * F10 / 299792458.0
        mus = {}

        def bz(wg):
            k = k0 * math.sqrt(wg.eps_r)
            beta = math.sqrt(k * k - (math.pi / wg.a) ** 2)
            return beta, 2 * np.pi * F10 * (4e-7 * math.pi) / beta

        b1, z1 = bz(WR90)
        b2, z2 = bz(wg2)
        for beta, z, ln in ((b1, z1, length1), (b2, z2, length2)):
            mus[ln] = np.array([
                [math.cos(beta * ln), 1j * z * math.sin(beta * ln)],
                [1j * math.sin(beta * ln) / z, math.cos(beta * ln)]])
        abcd = mus[length1] @ mus[length2]
        a_, b_, c_, d_ = abcd[0, 0], abcd[0, 1], abcd[1, 0], abcd[1, 1]
        den = a_ * z2 + b_ + c_ * z1 * z2 + d_ * z1
        s_ref = np.array([
            [(a_ * z2 + b_ - c_ * z1 * z2 - d_ * z1) / den,
             2 * math.sqrt(z1 * z2) / den],
            [2 * math.sqrt(z1 * z2) / den,
             (-a_ * z2 + b_ - c_ * z1 * z2 + d_ * z1) / den]])
        assert float(np.max(np.abs(res.s2x2[0] - s_ref))) <= 1e-9


class TestJudgeModalRebuild:
    """缺陷①回归钉：judge mmt_modal_s 完整 2×2 重建（s22≠s11 fixture）。"""

    @classmethod
    def setup_class(cls) -> None:
        script = (Path(__file__).resolve().parents[2] / "scripts"
                  / "df6_dp1p3_judge.py")
        spec = importlib.util.spec_from_file_location("dp1p3_judge", script)
        assert spec is not None and spec.loader is not None
        cls.judge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.judge)

    @staticmethod
    def _fixture(zte: float, seed: int = 11) -> tuple[dict, np.ndarray]:
        """s22≠s11 的 50Ω S fixture：随机互易模态阵反归一到 50Ω 基（可逆构造）。"""
        rng = np.random.default_rng(seed)
        s_modal = (rng.uniform(-0.3, 0.3, (2, 2))
                   + 1j * rng.uniform(-0.3, 0.3, (2, 2)))
        s50 = judge_renorm(s_modal, [zte, zte], [50.0, 50.0])  # (2,2) 单频
        assert abs(s50[0, 0] - s50[1, 1]) > 1e-3  # fixture 前提：s22≠s11
        mmt = {
            "freqs_hz": np.array([10e9]),
            "s11": np.array([s50[0, 0]]),
            "s21": np.array([s50[1, 0]]),
            "s12": np.array([s50[0, 1]]),
            "s22": np.array([s50[1, 1]]),
            "determined": np.array([True]),
            "meta": {"beta_te10_ports": [[[2 * math.pi * 10e9 * 1.25663706212e-6
                                           / zte, 0.0]]]},
        }
        return mmt, s50[None, :, :]  # (1,2,2) 与 mmt_modal_s 输出同形

    def test_roundtrip_full_matrix(self):
        """新实现：50Ω→模态反归一→回 50Ω 恢复原矩阵 ≤1e-12（可逆性）。"""
        zte = 499.3
        mmt, s50 = self._fixture(zte)
        modal, s50_out = self.judge.mmt_modal_s(mmt)
        assert float(np.max(np.abs(s50_out[0] - s50[0]))) <= 1e-15
        back = self.judge.renorm_s(modal[0], [zte, zte], [50.0, 50.0])
        assert float(np.max(np.abs(back - s50[0]))) <= 1e-12

    def test_symmetric_assumption_deviation_pin(self):
        """旧实现（对称假定 s22:=s11）同 fixture 往返失败——差异钉。"""
        zte = 499.3
        mmt, s50 = self._fixture(zte)
        modal_new, _ = self.judge.mmt_modal_s(mmt)
        s50_old = np.zeros((2, 2), complex)
        s50_old[0, 0] = mmt["s11"][0]
        s50_old[1, 0] = mmt["s21"][0]
        s50_old[0, 1] = mmt["s21"][0]
        s50_old[1, 1] = mmt["s11"][0]  # 旧实现：s22:=s11、s12:=s21
        modal_old = self.judge.renorm_s(s50_old, [50.0, 50.0], [zte, zte])
        back_new = self.judge.renorm_s(modal_new[0], [zte, zte], [50.0, 50.0])
        back_old = self.judge.renorm_s(modal_old, [zte, zte], [50.0, 50.0])
        dev_new = float(np.max(np.abs(back_new - s50[0])))
        dev_old = float(np.max(np.abs(back_old - s50[0])))
        assert dev_new <= 1e-12
        assert dev_old > 1e-3, "旧对称重建应可测偏离（fixture 需 s22≠s11）"

    def test_straight_case_identical_to_symmetric_assumption(self):
        """straight 例（s22==s11 逐位）新旧重建逐位一致——锚面零变化。"""
        zte = 480.0
        gam = (zte - 50.0) / (zte + 50.0)
        t = complex(math.cos(2.0), -math.sin(2.0))
        # 有载 50Ω 闭式线 S（judge line_s_closed 同形；s11≠0 但 s22==s11）
        s11 = gam * (1 - t * t) / (1 - gam * gam * t * t)
        s21 = t * (1 - gam * gam) / (1 - gam * gam * t * t)
        mmt = {
            "freqs_hz": np.array([10e9]),
            "s11": np.array([s11]), "s21": np.array([s21]),
            "s12": np.array([s21]), "s22": np.array([s11]),
            "determined": np.array([True]),
            "meta": {"beta_te10_ports": [[[2 * math.pi * 10e9 * 1.25663706212e-6
                                           / zte, 0.0]]]},
        }
        modal, _ = self.judge.mmt_modal_s(mmt)
        assert abs(modal[0, 0, 0]) <= 1e-9          # 模态 S11=0
        assert abs(abs(modal[0, 1, 0]) - 1.0) <= 1e-12  # |模态 S21|=1
        assert abs(modal[0, 1, 0] - t) <= 1e-9      # 模态 S21=e^{−jβL}


def judge_renorm(s: np.ndarray, z_from: list[float], z_to: list[float]) -> np.ndarray:
    """测试本地 N 口功率波 renorm（与 judge.renorm_s 同式，独立拷贝防自证）。"""
    n = s.shape[0]
    zf = np.asarray(z_from, float)
    zt = np.asarray(z_to, float)
    eye = np.eye(n)
    z_mat = (np.sqrt(zf)[:, None] * np.linalg.solve(eye - s, eye + s)
             * np.sqrt(zf)[None, :])
    return (np.diag(1.0 / np.sqrt(zt))
            @ (z_mat - np.diag(zt)) @ np.linalg.solve(z_mat + np.diag(zt),
                                                      np.diag(np.sqrt(zt))))
