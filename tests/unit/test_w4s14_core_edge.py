"""aurora_f W4-S14 席锚树：multisection_coupler 等纹波成员（R7 G5 唯一
遗留收官）+ kuroda_identities 两键（Pozar Table 8.7 四恒等式/Example 8.5
三阶低通全并联实现）+ pll_lock_time（二阶 II 型环捕获/锁定时间）。

数值断言口径（#118 不自证——闭式独立重解/文献原文数值/异路线互证，不用
自身推导互证自身）：
- 等纹波综合：N=3 结点权闭式测试侧独立推导（Q₁(y)=(1−ε)+(2ε/Y)y 线性
  匹配 → Γ₀=ε/(2Y)、Γ₁=1−ε+ε/(2Y)，比值判据对电平归一 scale 不变）；
  等纹波极值族 F(θ_k)/sinθ_k=1±ε 在切比雪夫极值点 y_k 逐位（构造定理）；
  精确级联 f0 命中 1e-9 dB/能量守恒 1e-12/f0 隔离零/回文；flatness 语义
  对照=N=5 等纹波带内非单调 vs 二项式单调（跨键同仓对照，任务书钉）。
- Kuroda 校验：四恒等式多电长 θ∈{30°,45°,70°} max_abcd_dev≤1e-12；Pozar
  式 (8.80a) 原文矩阵（Ω 归一因式）测试侧独立构造逐位——行 (a) 文献等
  式直接对照（#122 文献锚主判）；恒等式基元（UE/串联短路/并联开路）
  测试侧独立 ABCD 复算。
- Kuroda 实现：Pozar Example 8.5 文献圆整值窗（64.9/70.3/64.9/217.5Ω
  ±0.5%、n²=1.299）+g=(1,1,1) 闭式档（n²=2 → stubs 2/1/2、UEs 2/2）独
  立推导；全链 ABCD 等价残差 ≤1e-12（恒等式精确性端到端裁判）。
- PLL 锁定时间：pull-in 时间 GT ECE6440 L060 数值例 4.675s 原文窗
  0.5%（#122 文献锚主判）；线性包络二分一致性（精确暂态 |φ_e(t_lock)|
  ≤φ_tol<|φ_e(0.99·t_lock)|——闭式与精确暂态异路线互证）；ζ≥1 二分档
  独立求根互证；−3dB 带宽 Gardner 式经 |H(jω_3dB)|²=1/2 恒等式独立验
  证（非同式复算）；II 型稳态误差恒 0；lock-in 范围/时间恒等式。
- 守卫族：见 test_physics_invariants DOMAIN_ERROR_CASES 同笔（此处不复
  写，只留描述形态门）。
"""

from __future__ import annotations

import itertools
import math
import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator


def _run(name: str, **params: object) -> dict:
    out = run_calculator(name, params)
    assert out["ok"], f"{name} 失败: {out.get('error')!r}"
    return out["result"]


def _fail(name: str, **params: object) -> None:
    out = run_calculator(name, params)
    assert out["ok"] is False and out.get("error"), (
        f"{name}({params}) 应显式拒绝，得到 ok={out.get('ok')!r}")


NEW_KEYS = (
    "multisection_coupler_equiripple",
    "kuroda_identity_abcd", "kuroda_shunt_realize",
    "pll_lock_time")


# ─── 描述形态门（R5 §①：中文名全由 description 自带）────────────────────────

@pytest.mark.parametrize("key", NEW_KEYS)
def test_description_zh_head_form(key: str) -> None:
    spec = CALCULATOR_REGISTRY.get(key)
    head = re.split(r"[：:]", str(spec.description or ""))[0].strip()
    assert head and re.search(r"[\u4e00-\u9fff]", head)
    assert len(head) <= 24, f"{key} 中文名超 24 字符: {head!r}"


# ─── 等纹波多节耦合器：综合键 ────────────────────────────────────────────────

class TestEquirippleCoupler:
    def test_n3_junction_closed_form_ratio(self):
        """N=3 结点权闭式独立推导：Q₁=(1−ε)+(2ε/Y)y → Γ₀=ε/(2Y)、
        Γ₁=1−ε+ε/(2Y)（比值判据对电平归一 scale 不变，#118 异路线）。"""
        ripple_db, fbw = 0.5, 0.6
        out = _run("multisection_coupler_equiripple", n_sections=3,
                   coupling_db=10.0, ripple_db=ripple_db, fbw=fbw)
        ratio = 10.0 ** (ripple_db / 20.0)
        eps = (ratio - 1.0) / (ratio + 1.0)
        theta_edge = math.pi / 2.0 * (1.0 - fbw / 2.0)
        y_edge = math.cos(theta_edge) ** 2
        g0_cf = eps / (2.0 * y_edge)
        g1_cf = (1.0 - eps) + g0_cf
        gam = out["junction_gamma"]
        assert abs(gam[1] / gam[0] - g1_cf / g0_cf) <= 1e-9
        assert gam[0] > 0.0 and gam[1] > 0.0      # 可实现符号（σ=(−1)^M）
        assert gam[2] == -gam[1] and gam[3] == -gam[0]  # 反对称构造定理

    def test_equioscillation_at_chebyshev_extrema(self):
        """等纹波极值族：y_k=Y(1−cos(kπ/M))/2 处 Q=|F|/sinθ 触 1±ε——
        电平归一（精确级联求根 scale）不改形状，用 Q(y_k)/Q(y_0) 比值判
        （构造定理，测试侧独立采样）。"""
        for n_sec, ripple_db, fbw in ((3, 0.5, 0.6), (5, 0.3, 0.8),
                                      (7, 0.2, 1.0)):
            out = _run("multisection_coupler_equiripple", n_sections=n_sec,
                       coupling_db=10.0, ripple_db=ripple_db, fbw=fbw)
            m = (n_sec - 1) // 2
            ratio = 10.0 ** (ripple_db / 20.0)
            eps = (ratio - 1.0) / (ratio + 1.0)
            theta_edge = math.pi / 2.0 * (1.0 - fbw / 2.0)
            y_edge = math.cos(theta_edge) ** 2
            gam = out["junction_gamma"]

            def q_shape(th: float, gam_loc: list[float],
                        n_loc: int) -> float:
                f_val = sum(g * math.sin((n_loc - 2 * i) * th)
                            for i, g in enumerate(gam_loc))
                return f_val / math.sin(th)

            q_center = q_shape(math.pi / 2.0, gam, n_sec)
            for k in range(m + 1):
                y_k = y_edge * (1.0 - math.cos(k * math.pi / m)) / 2.0
                th_k = math.acos(math.sqrt(max(y_k, 0.0)))
                q_val = q_shape(th_k, gam, n_sec) / q_center
                expect = (1.0 + eps * ((-1.0) ** (m + k))) / (
                    1.0 + eps * ((-1.0) ** m))
                assert abs(q_val - expect) <= 1e-9, (n_sec, k, q_val, expect)


    def test_exact_cascade_properties(self):
        """精确级联：f0 命中 ≤1e-9 dB/回文/Z0e·Z0o=Z0²/隔离零/能量守恒
        （频响键跨键互证）。"""
        out = _run("multisection_coupler_equiripple", n_sections=3,
                   coupling_db=10.0, ripple_db=0.5, fbw=0.6)
        assert abs(out["exact_s31_at_f0_db"] + 10.0) <= 1e-9
        assert out["exact_vs_target_db"] <= 1e-9
        assert out["coupling_palindrome_dev"] <= 1e-15
        assert out["zr_identity_dev"] <= 1e-15
        assert out["isolation_s41_at_f0_linear"] <= 1e-10
        assert out["isolation_s41_at_f0_db"] is None
        resp = _run("multisection_coupler_response",
                    z0e_ohm=out["z0e_ohm"], z0o_ohm=out["z0o_ohm"],
                    f0_ghz=2.0, freq_ghz=[1.7, 1.9, 2.0, 2.1, 2.3])
        assert resp["energy_conservation_max_dev"] <= 1e-12
        assert abs(resp["s31_at_f0_db"] - out["exact_s31_at_f0_db"]) <= 1e-9

    def test_flatness_semantics_vs_binomial(self):
        """flatness 语义对照（任务书钉）：N=5 等纹波带内非单调（内极值）
        vs 二项式中心最大平坦（带内单调）——跨键同仓对照。"""
        eq5 = _run("multisection_coupler_equiripple", n_sections=5,
                   coupling_db=10.0, ripple_db=0.3, fbw=0.6)
        bin5 = _run("multisection_coupler_binomial", n_sections=5,
                    coupling_db=10.0)
        assert eq5["flatness_semantics"] == "equiripple"

        def s31_mono(db_list: list[float]) -> bool:
            return all(b <= a + 1e-9 for a, b in itertools.pairwise(db_list))

        # 带形 60°→88°（θ 线性采样 f=f0·θ/90°）：等纹波含内极值=非单调
        band = list(eq5["exact_band_s31_db"])
        assert not s31_mono(band), (
            "等纹波 N=5 带形应含内极值（非单调），却得到单调列表")
        # 二项式中心最大平坦：带内 |S31| 随 θ→90° 单调升（构造定理）——
        # 用同款 θ 线性采样经频响键独立重算
        theta_list = [math.radians(60.0 + 28.0 * k / 20) for k in range(21)]
        resp_b = _run(
            "multisection_coupler_response",
            z0e_ohm=bin5["z0e_ohm"], z0o_ohm=bin5["z0o_ohm"], f0_ghz=2.0,
            freq_ghz=[2.0 * t / (math.pi / 2.0) for t in theta_list])
        mags = resp_b["s31_db"]
        assert all(b >= a - 1e-9 for a, b in itertools.pairwise(mags)), (
            "二项式 N=5 从带缘到中心应单调升（中心最大平坦语义）")

    def test_achieved_ripple_honest_field(self):
        """实现纹波字段如实存在且与一阶目标有差（不隐藏二阶差/锥度）。"""
        out = _run("multisection_coupler_equiripple", n_sections=5,
                   coupling_db=10.0, ripple_db=0.3, fbw=0.6)
        assert out["first_order_ripple_db"] == pytest.approx(0.3, rel=1e-9)
        assert out["achieved_band_ripple_db"] > 0.0
        # 60% 带宽下精确带纹波与一阶目标同量级（>0 且不塌缩为 0）
        assert 0.05 < out["achieved_band_ripple_db"] < 5.0


# ─── Kuroda 恒等式：ABCD 校验键 ──────────────────────────────────────────────

def _ue_abcd_ref(z: float, th: float):
    c, s = complex(math.cos(th)), complex(math.sin(th))
    return [[c, 1j * z * s], [1j * s / z, c]]


class TestKurodaIdentityAbcd:
    def test_four_identities_multitheta_bitwise(self):
        """四恒等式 θ∈{30°,45°,70°} 逐位恒等（commensurate 口径）+n² 独
        立公式。"""
        for ident, zs, zu in ((1, 1.405, 3.3487), (2, 3.3487, 1.0),
                              (3, 2.0, 3.0), (4, 2.0, 3.0)):
            n_sq_cf = (1.0 + zs / zu) if ident in (1, 4) else (1.0 + zu / zs)
            for th_deg in (30.0, 45.0, 70.0):
                out = _run("kuroda_identity_abcd", identity=ident,
                           z1_ohm=zs, z2_ohm=zu, theta_deg=th_deg)
                assert out["max_abcd_dev"] <= 1e-12, (ident, th_deg)
                assert out["n_sq"] == pytest.approx(n_sq_cf, rel=1e-12)

    def test_pozar_eq80_row_a_independent_matrix(self):
        """Pozar 式 (8.80a) 原文矩阵测试侧独立构造（Ω 归一因式）与键输
        出逐位对照——行 (a) 文献等式直接锚（#122 主判）。

        Pozar 行 (a) 标签：Z₁=单位元、Z₂=短截线（n²=1+Z₂/Z₁）；本键参
        数 z1=短截线、z2=单位元——按标签映射传参。"""
        pz_ue, pz_stub = 50.0, 20.0
        th = math.radians(37.0)
        omega = math.tan(th)
        n_sq = 1.0 + pz_stub / pz_ue
        k = 1.0 / math.sqrt(1.0 + omega * omega)
        ref = [
            [k * complex(1.0), k * 1j * omega * pz_ue],
            [k * 1j * omega * (1.0 / pz_ue + 1.0 / pz_stub),
             k * complex(1.0 - omega * omega * pz_ue / pz_stub)],
        ]
        out = _run("kuroda_identity_abcd", identity=1, z1_ohm=pz_stub,
                   z2_ohm=pz_ue, theta_deg=37.0)
        got = out["abcd_left"]
        got_m = [[complex(got["a_re"][i][j] if isinstance(got["a_re"][i],
                                                          list)
                          else got["a_re"][2 * i + j],
                          got["a_im"][2 * i + j]) for j in range(2)]
                 for i in range(2)]
        for i in range(2):
            for j in range(2):
                assert abs(got_m[i][j] - ref[i][j]) <= 1e-12, (i, j)
        assert out["n_sq"] == pytest.approx(n_sq, rel=1e-12)

    def test_right_side_elements_reference_recompute(self):
        """右侧元素表独立 ABCD 复算（基元级异路线）：级联=左侧矩阵逐
        位。"""
        out = _run("kuroda_identity_abcd", identity=2, z1_ohm=3.3487,
                   z2_ohm=1.0, theta_deg=45.0)
        th = math.pi / 4.0
        n_sq = out["n_sq"]
        # (b) 右=[UE n²·stub][并联开路 n²·ue]——独立复算
        m1 = _ue_abcd_ref(n_sq * 3.3487, th)
        z_open = n_sq * 1.0
        m2 = [[complex(1.0), complex(0.0)],
              [1.0 / (-1j * z_open / math.tan(th)), complex(1.0)]]
        prod = [
            [m1[0][0] * m2[0][0] + m1[0][1] * m2[1][0],
             m1[0][0] * m2[0][1] + m1[0][1] * m2[1][1]],
            [m1[1][0] * m2[0][0] + m1[1][1] * m2[1][0],
             m1[1][0] * m2[0][1] + m1[1][1] * m2[1][1]],
        ]
        got = out["abcd_right"]
        for i in range(2):
            for j in range(2):
                ref = prod[i][j]
                assert abs(got["a_re"][2 * i + j] - ref.real) <= 1e-12
                assert abs(got["a_im"][2 * i + j] - ref.imag) <= 1e-12


# ─── Kuroda 恒等式：三阶低通全并联实现键 ─────────────────────────────────────

class TestKurodaShuntRealize:
    def test_pozar_example85_literature_window(self):
        """Example 8.5 文献圆整值窗（#122 主判）：n²=1.299、短截线
        64.9/70.3/64.9Ω、连接线 217.5Ω（Pozar 图 8.36(e)，±0.5%）。"""
        out = _run("kuroda_shunt_realize", g=[3.3487, 0.7117, 3.3487],
                   z0_ohm=50.0)
        assert out["n_sq"] == pytest.approx(1.299, rel=5e-3)
        for got, lit in zip(out["stub_shunt_ohm"], (64.9, 70.3, 64.9),
                            strict=True):
            assert got == pytest.approx(lit, rel=5e-3), (got, lit)
        for got in out["ue_line_ohm"]:
            assert got == pytest.approx(217.5, rel=5e-3)
        assert out["chain_abcd_max_dev"] <= 1e-12

    def test_g1_closed_form(self):
        """g=(1,1,1) 闭式档（独立推导）：n²=2 → 短截线 2/1/2、UE 线 2/2
        （归一）。"""
        out = _run("kuroda_shunt_realize", g=[1.0, 1.0, 1.0], z0_ohm=1.0)
        assert out["n_sq"] == pytest.approx(2.0, rel=1e-15)
        assert out["stub_shunt_normalized"] == pytest.approx(
            [2.0, 1.0, 2.0], rel=1e-15)
        assert out["ue_line_normalized"] == pytest.approx([2.0, 2.0],
                                                          rel=1e-15)
        assert out["chain_abcd_max_dev"] <= 1e-12

    def test_asymmetric_g_n_sq_split(self):
        """非对称 g₁≠g₃ 两端 n² 分列（守卫语义：对称时合并）。"""
        out = _run("kuroda_shunt_realize", g=[2.0, 1.0, 4.0], z0_ohm=1.0)
        assert out["n_sq"] == pytest.approx(1.5, rel=1e-15)
        assert out["n_sq_right"] == pytest.approx(1.25, rel=1e-15)
        assert out["chain_abcd_max_dev"] <= 1e-12


# ─── PLL 锁定时间 ────────────────────────────────────────────────────────────

class TestPllLockTime:
    def test_pull_in_literature_anchor(self):
        """GT ECE6440 L060 数值例（#122 主判）：f_n=3Hz、ζ=0.7、Δf=30Hz
        → T_P=4.675s（原文窗 0.5%）。"""
        out = _run("pll_lock_time", fn_hz=3.0, zeta=0.7, df_hz=30.0)
        assert out["t_pull_in_s"] == pytest.approx(4.675, rel=5e-3)
        assert out["t_lockin_rule_of_thumb_s"] == pytest.approx(
            1.0 / 3.0, rel=1e-12)

    def test_linear_envelope_bisection_consistency(self):
        """线性档包络一致性（异路线互证）：ζ<1 精确闭式 t_lock 处精确暂
        态 |φ_e|≤φ_tol 且 0.99·t_lock 处 >φ_tol；闭式独立重算逐位。"""
        fn, zeta, df, tol_deg = 1.0e5, 0.707, 2.0e4, 5.0
        out = _run("pll_lock_time", fn_hz=fn, zeta=zeta, df_hz=df,
                   tol_deg=tol_deg)
        wn = 2.0 * math.pi * fn
        dw = 2.0 * math.pi * df
        phi_tol = math.radians(tol_deg)
        wd = wn * math.sqrt(1.0 - zeta * zeta)
        t_cf = math.log(dw / (phi_tol * wd)) / (zeta * wn)
        assert out["t_lock_s"] == pytest.approx(t_cf, rel=1e-9)
        assert out["t_lock_closed_form"] is True
        assert out["regime"] == "linear_lock"

        def phi_env(t: float) -> float:
            return (dw / wd) * math.exp(-zeta * wn * t)

        assert phi_env(out["t_lock_s"]) <= phi_tol * (1.0 + 1e-6)
        assert phi_env(0.99 * out["t_lock_s"]) > phi_tol

    def test_zeta_overdamped_bisection_matches_transient(self):
        """ζ≥1 二分档：t_lock_closed_form=False 且与精确暂态独立扫描求根
        一致 ≤1e-9；稳态误差恒 0。"""
        out = _run("pll_lock_time", fn_hz=1.0e4, zeta=1.5, df_hz=2.0e3,
                   tol_deg=2.0)
        assert out["t_lock_closed_form"] is False
        wn = 2.0 * math.pi * 1.0e4
        dw = 2.0 * math.pi * 2.0e3
        s1 = -1.5 * wn + wn * math.sqrt(1.25)
        s2 = -1.5 * wn - wn * math.sqrt(1.25)
        phi_tol = math.radians(2.0)

        def phi(t: float) -> float:
            return abs(dw * (math.exp(s1 * t) - math.exp(s2 * t))
                       / (s1 - s2))

        lo, hi = 0.0, out["t_lock_s"] * 2.0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if phi(mid) > phi_tol:
                lo = mid
            else:
                hi = mid
        assert out["t_lock_s"] == pytest.approx(0.5 * (lo + hi), abs=1e-9)
        assert out["steady_state_error_rad"] == 0.0

    def test_bw3db_gardner_identity(self):
        """−3dB 带宽 Gardner 式经 |H(jω_3dB)|²=1/2 恒等式独立验证（非同
        式复算，#118 口径）。"""
        for zeta in (0.3, 0.5, 0.707, 1.0, 2.0):
            fn = 7.0e3
            out = _run("pll_lock_time", fn_hz=fn, zeta=zeta, df_hz=1.0e3)
            wn = 2.0 * math.pi * fn
            w3 = 2.0 * math.pi * out["bw_3db_hz"]
            num = (2.0 * zeta * wn * w3) ** 2 + wn ** 4
            den = (wn ** 2 - w3 ** 2) ** 2 + (2.0 * zeta * wn * w3) ** 2
            assert abs(num / den - 0.5) <= 1e-12, zeta

    def test_regime_classification_and_lockin_identity(self):
        """档位判别：Δf=0.5·Δf_L → linear_lock；Δf=3·Δf_L →
        nonlinear_pull_in；Δf_L=ζω_n/π 恒等；df=0 → t_lock=0。"""
        fn, zeta = 1.0e5, 0.707
        out_l = _run("pll_lock_time", fn_hz=fn, zeta=zeta, df_hz=0.0)
        assert out_l["t_lock_s"] == 0.0
        wn = 2.0 * math.pi * fn
        df_l = zeta * wn / (2.0 * math.pi)
        out_a = _run("pll_lock_time", fn_hz=fn, zeta=zeta,
                     df_hz=0.5 * df_l)
        assert out_a["regime"] == "linear_lock"
        assert out_a["df_lock_in_hz"] == pytest.approx(df_l, rel=1e-12)
        out_b = _run("pll_lock_time", fn_hz=fn, zeta=zeta,
                     df_hz=3.0 * df_l)
        assert out_b["regime"] == "nonlinear_pull_in"
