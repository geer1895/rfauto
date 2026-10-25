"""aurora72 A7-B 席锚树：waveguide_iris 三键（矩形波导膜片电纳/谐振窗/
单膜片匹配）+ guanella_tlt 两键（Guanella 传输线变压器设计/频响）。

数值断言口径（#118 不自证——闭式测试侧独立重解/教科书极限恒等/异构路线
互证/判废对照，不用实现侧公式互证自身）：
- 膜片电纳：λg/电纳闭式测试侧独立重算逐位 1e-12；极限恒等（开口→全边
  电纳→0、开口收缩 |b| 单调发散）；正反解双向往返 ≤1e-9（感性/容性各
  三开口）；TE10 截止标度恒等（f=2fc → λg=2λ0/√3 测试侧重解）。
- 谐振窗：反解档回代 |B总|=0 构造级；验证档残余如实非零；小感性开口
  指数下溢显式拒绝（容性解不可达守卫）。
- 单膜片匹配：Γ=1/3@0° 教科书解独立推导（y_L=0.5 → |t|=√2、
  b_i=±1/√2 双分支感性/容性各一）；ABCD 回代测试侧独立算 |Γin|=0；
  g>1/带相位负载双案例；Γ=0 退化 none 分支；守卫族。
- Guanella 设计：4:1/9:1/16:1 的 n 与 Z0=√(Rin·Rlo) 恒等式；5:1 复合比
  显式拒绝（族界如实）；λ/8 线长上限 c 精确常数链。
- Guanella 频响：全频段理想匹配定理（最优 Z0 → 全频轴 |S11|≤1e-12，
  解析定理 vs 数值解）；标量串并式 Z_in(θ)（测试侧独立推导）vs 4 端子
  消元式 |S11| 双路线互证 ≤1e-9；θ=90° 失配 |S11|=(k²−1)/(k²+1) 经典
  λ/4 倒抗闭式；n=1 恒等 |S11|=0/|S21|=1；无耗功率守恒 ≤1e-12 与互易
  S12=S21；失配随 θ 单调增长；θ=kπ 精确奇异频点显式拒绝；守卫族。
- 新键 description 首行"中文名：全角冒号"形态门（中文名含 CJK ≤24 字符）。
"""

from __future__ import annotations

import cmath
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

_C0 = 299792458.0
_WR90 = {"a_mm": 22.86, "b_mm": 10.16}


def _run(name: str, **params: object) -> dict:
    out = run_calculator(name, params)
    assert out["ok"], f"{name} 失败: {out.get('error')!r}"
    return out["result"]


def _fail(name: str, **params: object) -> None:
    out = run_calculator(name, params)
    assert out["ok"] is False and out.get("error"), (
        f"{name}({params}) 应显式拒绝，得到 ok={out.get('ok')!r}")


NEW_KEYS = (
    "wg_iris_susceptance", "wg_resonant_window", "wg_iris_match",
    "guanella_tlt_design", "guanella_tlt_response")


# ─── 描述形态门（R5 §①：中文名全由 description 自带）────────────────────────

@pytest.mark.parametrize("key", NEW_KEYS)
def test_description_zh_head_form(key: str) -> None:
    import re

    spec = CALCULATOR_REGISTRY.get(key)
    head = re.split(r"[：:]", str(spec.description or ""))[0].strip()
    assert head and re.search(r"[\u4e00-\u9fff]", head)
    assert len(head) <= 24, f"{key} 中文名超 24 字符: {head!r}"


# ─── 测试侧独立闭式（#118：与实现侧同式异推，推导即锚）───────────────────────

def _lam0_mm(f_ghz: float) -> float:
    return _C0 / (f_ghz * 1e9) * 1e3


def _lam_g_mm(a_mm: float, f_ghz: float) -> float:
    lam0 = _lam0_mm(f_ghz)
    fc = _C0 / (2.0 * a_mm * 1e-3) / 1e9
    return lam0 / math.sqrt(1.0 - (fc / f_ghz) ** 2)


def _b_ind_ref(a_mm: float, d_mm: float, lam_g_mm: float) -> float:
    return -(lam_g_mm / a_mm) / math.tan(math.pi * d_mm / (2.0 * a_mm)) ** 2


def _b_cap_ref(b_mm: float, d_mm: float, lam0_mm: float) -> float:
    return (4.0 * b_mm / lam0_mm) * math.log(
        1.0 / math.sin(math.pi * d_mm / (2.0 * b_mm)))


def _zin_guanella(theta: float, z0: float, r_out: float,
                  n: int) -> float:
    """标量串并式 Z_in（测试侧独立推导：每线视入 nR_lo、串联链求和）。"""
    t = cmath.tan(complex(theta))
    z_line_in = z0 * (n * r_out + 1j * z0 * t) / (z0 + 1j * n * r_out * t)
    return n * z_line_in


# ─── 膜片电纳键 ──────────────────────────────────────────────────────────────

class TestIrisSusceptance:
    def test_closed_form_independent_recompute(self):
        """λg 与两膜片电纳闭式测试侧独立重算逐位 1e-12。"""
        for f_ghz in (8.0, 10.0, 12.0):
            lam_g = _lam_g_mm(_WR90["a_mm"], f_ghz)
            for d_mm in (5.0, 11.43, 18.0):
                r = _run("wg_iris_susceptance", **_WR90, f_ghz=f_ghz,
                         d_mm=d_mm)
                assert abs(r["lambda_g_mm"] - lam_g) <= 1e-9
                assert r["b_norm"] == pytest.approx(
                    _b_ind_ref(_WR90["a_mm"], d_mm, lam_g), rel=1e-11,
                    abs=1e-12)
            for d_mm in (2.0, 5.08, 8.0):
                r = _run("wg_iris_susceptance", **_WR90, f_ghz=f_ghz,
                         iris_type="capacitive", d_mm=d_mm)
                assert r["b_norm"] == pytest.approx(
                    _b_cap_ref(_WR90["b_mm"], d_mm, _lam0_mm(f_ghz)),
                    rel=1e-11, abs=1e-12)

    def test_limit_identities_and_monotonicity(self):
        """极限恒等：开口→全边 b→0（连续性）；开口收缩 |b| 单调发散。"""
        prev = 0.0
        for d_mm in (21.0, 16.0, 11.43, 7.0, 3.0):
            r = _run("wg_iris_susceptance", **_WR90, f_ghz=10.0, d_mm=d_mm)
            assert r["b_norm"] < prev <= 0.0  # 感性负值单调更负
            prev = r["b_norm"]
        r_open = _run("wg_iris_susceptance", **_WR90, f_ghz=10.0,
                      d_mm=22.7)  # 开口→a：b→0
        assert abs(r_open["b_norm"]) < 0.01
        cap_prev = 0.0
        for d_mm in (9.0, 5.08, 2.0):
            r = _run("wg_iris_susceptance", **_WR90, f_ghz=10.0,
                     iris_type="capacitive", d_mm=d_mm)
            assert r["b_norm"] > cap_prev >= 0.0  # 容性正值单调更正
            cap_prev = r["b_norm"]

    def test_inverse_roundtrip_both_types(self):
        """正反解双向往返：电纳→开口→电纳回代 ≤1e-9（两型各三开口）。"""
        for iris_type, ds in (("inductive", (18.0, 11.43, 6.0)),
                              ("capacitive", (8.0, 5.08, 2.5))):
            for d_mm in ds:
                fwd = _run("wg_iris_susceptance", **_WR90, f_ghz=10.0,
                           iris_type=iris_type, d_mm=d_mm)
                inv = _run("wg_iris_susceptance", **_WR90, f_ghz=10.0,
                           iris_type=iris_type, b_norm=fwd["b_norm"])
                assert abs(inv["d_mm"] - d_mm) <= 1e-9
                assert abs(inv["b_norm_backsub"]
                           - fwd["b_norm"]) <= 1e-9

    def test_te10_cutoff_scaling_identity(self):
        """TE10 标度恒等：f=2fc → λg=2λ0/√3（测试侧独立重解）。"""
        fc = _C0 / (2.0 * _WR90["a_mm"] * 1e-3) / 1e9
        r = _run("wg_iris_susceptance", **_WR90, f_ghz=2.0 * fc, d_mm=11.43)
        expect = _lam0_mm(2.0 * fc) / math.sqrt(0.75)
        assert abs(r["lambda_g_mm"] - expect) <= 1e-9

    def test_guards(self):
        _fail("wg_iris_susceptance", a_mm=0.0, b_mm=10.16, f_ghz=10.0,
              d_mm=5.0)
        _fail("wg_iris_susceptance", a_mm=22.86, b_mm=30.0, f_ghz=10.0,
              d_mm=5.0)  # b>a 非标准口径
        _fail("wg_iris_susceptance", a_mm=22.86, b_mm=10.16, f_ghz=5.0,
              d_mm=5.0)  # TE10 截止以下
        _fail("wg_iris_susceptance", a_mm=22.86, b_mm=10.16, f_ghz=10.0,
              d_mm=22.86)  # 开口=全边（无膜片）
        _fail("wg_iris_susceptance", a_mm=22.86, b_mm=10.16, f_ghz=10.0,
              iris_type="x", d_mm=5.0)  # 白名单外
        _fail("wg_iris_susceptance", a_mm=22.86, b_mm=10.16,
              f_ghz=10.0)  # 双缺
        _fail("wg_iris_susceptance", a_mm=22.86, b_mm=10.16, f_ghz=10.0,
              d_mm=5.0, b_norm=-1.0)  # 双给超定
        _fail("wg_iris_susceptance", a_mm=22.86, b_mm=10.16, f_ghz=10.0,
              iris_type="inductive", b_norm=1.0)  # 感性符号
        _fail("wg_iris_susceptance", a_mm=22.86, b_mm=10.16, f_ghz=10.0,
              iris_type="capacitive", b_norm=-1.0)  # 容性符号


# ─── 谐振窗键 ────────────────────────────────────────────────────────────────

class TestResonantWindow:
    def test_solve_branch_exact_resonance(self):
        """反解档回代 |B总|=0（构造级残差）+独立重算 d_cap 闭式。"""
        d_ind = 11.43
        r = _run("wg_resonant_window", **_WR90, f_ghz=10.0, d_ind_mm=d_ind)
        assert r["resonant"] is True
        assert r["b_total_norm"] <= 1e-9
        # 独立重算：b_cap_req=−b_ind → d_c=(2b/π)asin exp(−b_req·λ0/4b)
        lam_g = _lam_g_mm(_WR90["a_mm"], 10.0)
        b_req = lam_g / _WR90["a_mm"]  # cot²(π/4)=1
        sin_x = math.exp(-b_req * _lam0_mm(10.0) / (4.0 * _WR90["b_mm"]))
        d_cap_ref = (2.0 * _WR90["b_mm"] / math.pi) * math.asin(sin_x)
        assert abs(r["d_cap_mm"] - d_cap_ref) <= 1e-9

    def test_verify_branch_honest_residual(self):
        """验证档：双开口给齐不凑零——残余电纳如实非零。"""
        r = _run("wg_resonant_window", **_WR90, f_ghz=10.0, d_ind_mm=11.43,
                 d_cap_mm=3.0)
        assert r["route"] == "verify"
        b_ind = _b_ind_ref(_WR90["a_mm"], 11.43,
                           _lam_g_mm(_WR90["a_mm"], 10.0))
        b_cap = _b_cap_ref(_WR90["b_mm"], 3.0, _lam0_mm(10.0))
        assert abs(r["b_total_norm"] - (b_ind + b_cap)) <= 1e-9
        assert abs(r["b_total_norm"]) > 1e-6  # 3.0mm 非谐振开口
        assert r["resonant"] is False

    def test_underflow_guard(self):
        """小感性开口 → 所需容性电纳指数下溢 → 显式拒绝（可达域守卫）。"""
        _fail("wg_resonant_window", a_mm=22.86, b_mm=10.16, f_ghz=10.0,
              d_ind_mm=0.5)
        _fail("wg_resonant_window", a_mm=22.86, b_mm=10.16, f_ghz=10.0,
              d_ind_mm=0.0)
        _fail("wg_resonant_window", a_mm=22.86, b_mm=10.16, f_ghz=10.0,
              d_ind_mm=22.86)


# ─── 单膜片匹配键 ────────────────────────────────────────────────────────────

class TestIrisMatch:
    def test_textbook_solution_independent_derivation(self):
        """Γ=1/3@0°：y_L=0.5 → 二次方程 (−1/4)t²+1/2=0 → |t|=√2（独立推
        导）；b_i=∓Im{y_in}=∓1/√2 双分支；感性/容性各一。"""
        r = _run("wg_iris_match", **_WR90, f_ghz=10.0, gamma_mag=1.0 / 3.0,
                 gamma_phase_deg=0.0)
        assert abs(r["y_load_norm_g"] - 0.5) <= 1e-12
        assert abs(r["y_load_norm_b"]) <= 1e-12
        types = sorted(b["iris_type"] for b in r["branches"])
        assert types == ["capacitive", "inductive"]
        for br in r["branches"]:
            assert abs(abs(br["tan_beta_l"]) - math.sqrt(2.0)) <= 1e-9
            assert abs(abs(br["b_iris_norm"]) - math.sqrt(0.5)) <= 1e-9
            assert br["gamma_in_residual"] <= 1e-12
            assert 0.0 <= br["l_mm"] < r["lambda_g_mm"]
        assert r["preferred_branch"] == next(
            b["branch"] for b in r["branches"]
            if b["iris_type"] == "inductive")

    def test_abcd_independent_verification(self):
        """ABCD 回代测试侧独立算：沿线变换式+并联电纳补偿 → |Γin|=0。"""
        gamma_mag, gamma_ph = 0.4, 37.0
        r = _run("wg_iris_match", **_WR90, f_ghz=10.0, gamma_mag=gamma_mag,
                 gamma_phase_deg=gamma_ph)
        gamma = gamma_mag * cmath.exp(1j * math.radians(gamma_ph))
        y_l = (1.0 - gamma) / (1.0 + gamma)
        lam_g = _lam_g_mm(_WR90["a_mm"], 10.0)
        beta = 2.0 * math.pi / lam_g
        for br in r["branches"]:
            t = cmath.tan(complex(beta * br["l_mm"]))
            y_in = (y_l + 1j * t) / (1.0 + 1j * y_l * t)
            y_tot = y_in + 1j * br["b_iris_norm"]
            g_in = abs((1.0 - y_tot) / (1.0 + y_tot))
            assert g_in <= 1e-9, (br, g_in)

    def test_high_g_and_matched_degenerate(self):
        """g>1 案例（Γ@180°）+ Γ=0 退化 none 分支。"""
        r = _run("wg_iris_match", **_WR90, f_ghz=10.0, gamma_mag=1.0 / 3.0,
                 gamma_phase_deg=180.0)
        assert abs(r["y_load_norm_g"] - 2.0) <= 1e-12
        for br in r["branches"]:
            assert br["gamma_in_residual"] <= 1e-12
        r0 = _run("wg_iris_match", **_WR90, f_ghz=10.0, gamma_mag=0.0,
                  gamma_phase_deg=0.0)
        assert r0["branches"][0]["iris_type"] == "none"
        assert r0["branches"][0]["b_iris_norm"] == 0.0
        assert r0["branches"][0]["l_mm"] == 0.0

    def test_guards(self):
        _fail("wg_iris_match", a_mm=22.86, b_mm=10.16, f_ghz=10.0,
              gamma_mag=1.0, gamma_phase_deg=0.0)  # |Γ|=1 无源界
        _fail("wg_iris_match", a_mm=22.86, b_mm=10.16, f_ghz=10.0,
              gamma_mag=-0.2, gamma_phase_deg=0.0)
        _fail("wg_iris_match", a_mm=22.86, b_mm=10.16, f_ghz=10.0,
              gamma_mag=0.2, gamma_phase_deg=200.0)
        _fail("wg_iris_match", a_mm=22.86, b_mm=10.16, f_ghz=5.0,
              gamma_mag=0.2, gamma_phase_deg=0.0)  # 截止以下
        _fail("wg_iris_match", a_mm=0.0, b_mm=10.16, f_ghz=10.0,
              gamma_mag=0.2, gamma_phase_deg=0.0)


# ─── Guanella 设计键 ─────────────────────────────────────────────────────────

class TestGuanellaDesign:
    def test_n2_ratio_and_z_line_identity(self):
        """4:1/9:1/16:1 → n 与 Z0=√(Rin·Rlo) 恒等式；每线负载 n·R_lo。"""
        for r_in, n_exp in ((200.0, 2), (450.0, 3), (800.0, 4)):
            r = _run("guanella_tlt_design", r_in_ohm=r_in, r_out_ohm=50.0)
            assert r["n_lines"] == n_exp
            assert abs(r["impedance_ratio"] - n_exp ** 2) <= 1e-9
            assert abs(r["z_line_ohm"]
                       - math.sqrt(r_in * 50.0)) <= 1e-9
            assert abs(r["line_load_ohm"] - n_exp * 50.0) <= 1e-9

    def test_compound_ratio_rejected(self):
        """5:1（√5 非整数）与 3:1 复合比显式拒绝（族界如实不做）。"""
        _fail("guanella_tlt_design", r_in_ohm=250.0, r_out_ohm=50.0)
        _fail("guanella_tlt_design", r_in_ohm=150.0, r_out_ohm=50.0)

    def test_lambda_eighth_length_bound(self):
        """λ/8 准则：l_max = v_f·c/(8·f_max)（c 精确常数链）。"""
        r = _run("guanella_tlt_design", r_in_ohm=200.0, r_out_ohm=50.0,
                 f_max_ghz=2.0, v_f=1.0)
        assert abs(r["l_max_mm"] - _C0 / (8.0 * 2.0e9) * 1e3) <= 1e-9
        r2 = _run("guanella_tlt_design", r_in_ohm=200.0, r_out_ohm=50.0,
                  f_max_ghz=6.0, v_f=0.7)
        assert abs(r2["l_max_mm"]
                   - 0.7 * _C0 / (8.0 * 6.0e9) * 1e3) <= 1e-9
        r3 = _run("guanella_tlt_design", r_in_ohm=200.0, r_out_ohm=50.0)
        assert r3["l_max_mm"] is None  # 未给 f_max 不出长度

    def test_guards(self):
        _fail("guanella_tlt_design", r_in_ohm=0.0, r_out_ohm=50.0)
        _fail("guanella_tlt_design", r_in_ohm=200.0, r_out_ohm=-50.0)
        _fail("guanella_tlt_design", r_in_ohm=200.0, r_out_ohm=50.0,
              f_max_ghz=-1.0)
        _fail("guanella_tlt_design", r_in_ohm=200.0, r_out_ohm=50.0,
              v_f=0.0)
        _fail("guanella_tlt_design", r_in_ohm=200.0, r_out_ohm=50.0,
              v_f=1.5)


# ─── Guanella 频响键 ─────────────────────────────────────────────────────────

class TestGuanellaResponse:
    def test_all_frequency_match_theorem(self):
        """全频段理想匹配定理：最优 Z0=√(Rin·Rlo) → 全频轴 |S11|≤1e-12
        （解析定理 vs 4 端子数值解）；无耗功率守恒与互易构造级。"""
        length_mm = 18.737028625
        freqs = [0.5, 1.0, 2.0, 3.3, 5.0, 7.0]  # 全部避开 θ=kπ（f=8k）
        r = _run("guanella_tlt_response", r_in_ohm=200.0, r_out_ohm=50.0,
                 length_mm=length_mm, freq_ghz=freqs)
        assert r["matched_all_freq"] is True
        assert max(r["s11_db"]) <= -240.0
        assert max(abs(v) for v in r["s21_db"]) <= 1e-9  # 无耗全传输
        assert r["power_conservation_max_dev"] <= 1e-12
        assert r["reciprocity_max_dev"] <= 1e-12

    def test_scalar_series_parallel_vs_nodal(self):
        """双路线互证：标量串并式 Z_in(θ)（测试侧独立推导）→ |Γ| vs 4 端
        子消元 |S11| ≤1e-9（失配档 z_line=150Ω=k·nR_lo）。"""
        length_mm, z_line = 18.737028625, 150.0
        freqs = [1.0, 2.0, 3.0, 5.0, 6.5]
        r = _run("guanella_tlt_response", r_in_ohm=200.0, r_out_ohm=50.0,
                 length_mm=length_mm, freq_ghz=freqs, z_line_ohm=z_line)
        assert r["matched_all_freq"] is False
        for f, s11_db in zip(r["freq_ghz"], r["s11_db"], strict=True):
            theta = 2.0 * math.pi * f * 1e9 * (length_mm * 1e-3) / _C0
            zin = _zin_guanella(theta, z_line, 50.0, 2)
            gamma = abs((zin - 200.0) / (zin + 200.0))
            assert abs(10.0 ** (s11_db / 20.0) - gamma) <= 1e-9

    def test_quarter_wave_mismatch_closed_form(self):
        """θ=90° 失配 |S11|=(k²−1)/(k²+1)（k=1.5 → 0.3846…，经典 λ/4 倒
        抗式；精确奇异频点由长度常数链计算）。"""
        length_mm, k = 18.737028625, 1.5
        f_90 = _C0 / (4.0 * length_mm * 1e-3) / 1e9
        r = _run("guanella_tlt_response", r_in_ohm=200.0, r_out_ohm=50.0,
                 length_mm=length_mm, freq_ghz=[f_90], z_line_ohm=k * 100.0)
        assert abs(r["theta_deg"][0] - 90.0) <= 1e-6
        expect = (k * k - 1.0) / (k * k + 1.0)
        got = 10.0 ** (r["s11_db"][0] / 20.0)
        assert abs(got - expect) <= 1e-9
        # 功率守恒下 |S21|=√(1−|S11|²)
        assert abs(10.0 ** (r["s21_db"][0] / 20.0)
                   - math.sqrt(1.0 - expect ** 2)) <= 1e-9

    def test_mismatch_monotonic_growth(self):
        """失配随 θ 单调增长（k≠1，θ∈(0°,90°) 内单调；θ↔π−θ 对称不越半
        周期取样）；θ→0 极限 |S11|→0（Z_in(0)=R_in 任意 Z0）。"""
        length_mm = 18.737028625
        freqs = [0.25, 0.5, 1.0, 2.0]  # θ=5.625°..45°（90° 内单调段）
        r = _run("guanella_tlt_response", r_in_ohm=200.0, r_out_ohm=50.0,
                 length_mm=length_mm, freq_ghz=freqs, z_line_ohm=150.0)
        s11 = [10.0 ** (v / 20.0) for v in r["s11_db"]]
        assert s11 == sorted(s11)
        assert s11[0] < 0.05 and s11[-1] > 0.25  # θ→0 小失配→45° 显著失配

    def test_n1_identity_passthrough(self):
        """n=1（1:1）恒等：直通线 |S11|=0、|S21|=1 全频（等参考退化档）。"""
        r = _run("guanella_tlt_response", r_in_ohm=50.0, r_out_ohm=50.0,
                 length_mm=10.0, freq_ghz=[0.5, 1.0, 2.0, 5.0])
        assert r["n_lines"] == 1
        assert min(r["s11_db"]) <= -240.0
        assert max(abs(v) for v in r["s21_db"]) <= 1e-9

    def test_theta_kpi_exact_singular_rejection(self):
        """θ=π 精确奇异频点（f=c/2ℓ）显式拒绝；f→0 同面。"""
        length_mm = 18.737028625
        f_pi = _C0 / (2.0 * length_mm * 1e-3) / 1e9
        _fail("guanella_tlt_response", r_in_ohm=200.0, r_out_ohm=50.0,
              length_mm=length_mm, freq_ghz=[f_pi])
        _fail("guanella_tlt_response", r_in_ohm=200.0, r_out_ohm=50.0,
              length_mm=length_mm, freq_ghz=[0.0])

    def test_guards(self):
        _fail("guanella_tlt_response", r_in_ohm=150.0, r_out_ohm=50.0,
              length_mm=18.737, freq_ghz=[1.0])  # 3:1 非平方比
        _fail("guanella_tlt_response", r_in_ohm=200.0, r_out_ohm=50.0,
              length_mm=0.0, freq_ghz=[1.0])
        _fail("guanella_tlt_response", r_in_ohm=200.0, r_out_ohm=50.0,
              length_mm=18.737, freq_ghz=[])
        _fail("guanella_tlt_response", r_in_ohm=200.0, r_out_ohm=50.0,
              length_mm=18.737, freq_ghz=[1.0], v_f=1.2)
        _fail("guanella_tlt_response", r_in_ohm=200.0, r_out_ohm=50.0,
              length_mm=18.737, freq_ghz=[1.0], z_line_ohm=0.0)
        _fail("guanella_tlt_response", r_in_ohm=250.0, r_out_ohm=50.0,
              length_mm=18.737, freq_ghz=[1.0])
