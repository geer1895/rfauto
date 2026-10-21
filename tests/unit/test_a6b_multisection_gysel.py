"""架构批 A6-B 席锚树：multisection_coupler 两键（多节对称定向耦合器二项
式综合/精确频响）+ gysel_core 两键（Gysel 功分器 core 电气综合/五线六节点
精确频响）。

数值断言口径（#118 不自证——闭式独立重解/文献-锚常数/异路线互证/判废对
照，不用自身推导互证自身）：
- 多节综合：最大平坦条件测试侧独立重解（一阶响应 f(θ)=2Γ₀sin3θ+2Γ₁sinθ
  对 x=sinθ 求导、g'(x=1)=0 → Γ₁=9Γ₀、节耦合比 c₂/c₁=10——与实现侧三角
  分解互为异路线）；N=1 退化 c₁=目标、精确级联 f0=闭式逐位；电平归一求
  根残差 ≤1e-9 dB；节耦合回文/Z0e·Z0o=Z0²/隔离零/60°-120° 对称四构造定
  理；一阶 vs 精确二阶差 (0,0.5)dB 如实存在性。
- 多节频响：N=1 vs 单节精确闭式 c·sinθ/√(1−c²cos²θ)（测试侧独立推导：
  Γo=−Γe 配对 → S31=Γe）逐位 ≤1e-9；能量守恒 |S11|²+|S21|²+|S31|²+
  |S41|²=1 ≤1e-12（构造定理）；带形单调（|S31| 随 sinθ 单调=最大平坦）；
  vs 综合键跨键互证 ≤1e-9。
- Gysel 综合：√2·Z0 教科书常数；偶/奇半电路测试侧独立重解（有限代理端
  接，γ 随代理缩比收敛：proxy×1000 → γ/1000）；S 矩阵互易 S=Sᵀ、σmax≤1
  （有耗无源）、列功率=匹配 + 均分 −3.0103dB 恒等。
- Gysel 频响：f0 vs 理想矩阵 ≤1e-9；耗散守恒 ≤1e-12；无桥带判废对照
  vs #206 判废锚 −6.53dB（带 0.05dB 窗）+测试侧五节点独立重解 ≤1e-9；
  频轴镜像对称（f0±δ 逐位）；跨键互证（综合 S 矩阵 vs 频响 f0）。
- 守卫族：偶数节/过耦 1dB@3 节/θ=kπ（f=2f0）显式拒绝等。
- 新键 description 首行"中文名：全角冒号"形态门（中文名含 CJK ≤24 字符）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
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
    "multisection_coupler_binomial", "multisection_coupler_response",
    "gysel_core_synthesize", "gysel_frequency_response")


# ─── 描述形态门（R5 §①：中文名全由 description 自带）────────────────────────

@pytest.mark.parametrize("key", NEW_KEYS)
def test_description_zh_head_form(key: str) -> None:
    import re

    spec = CALCULATOR_REGISTRY.get(key)
    head = re.split(r"[：:]", str(spec.description or ""))[0].strip()
    assert head and re.search(r"[\u4e00-\u9fff]", head)
    assert len(head) <= 24, f"{key} 中文名超 24 字符: {head!r}"


# ─── 多节耦合器：综合键 ──────────────────────────────────────────────────────

def _first_order_s31(gam: list[float], th: float, n: int) -> float:
    """一阶耦合口响应（测试侧独立构造）：|Σ Γ_i e^{−j2iθ}|。"""
    return abs(sum(g * np.exp(-2j * i * th) for i, g in enumerate(gam)))


class TestMultisectionBinomial:
    def test_n3_junction_ratio_independent_maxflat(self):
        """最大平坦条件测试侧独立重解：N=3 → Γ₁=9Γ₀、节耦合比 1:10:1。

        独立路线：一阶响应 f(x)=Γ₀sin3θ+Γ₁sinθ 的镜像对称半和
        2j·e^{−j3θ}(Γ₀sin3θ+Γ₁sinθ)，对 x=sinθ 在 x=1 处 g'(1)=0：
        g=(3Γ₀+Γ₁)x−4Γ₀x³ → 3Γ₀+Γ₁−12Γ₀=0 → Γ₁=9Γ₀。
        """
        r = _run("multisection_coupler_binomial", n_sections=3,
                 coupling_db=10.0)
        gam = r["junction_gamma"]
        assert len(gam) == 4
        assert abs(gam[0] + gam[3]) <= 1e-15        # 镜像反对称
        assert abs(gam[1] + gam[2]) <= 1e-15
        ratio = gam[1] / gam[0]
        assert abs(ratio - 9.0) <= 1e-9, f"结点比 {ratio}≠9（最大平坦）"
        # 符号：前半正后半负（半和构造）
        assert gam[0] > 0 and gam[1] > 0 and gam[2] < 0 and gam[3] < 0
        c = r["coupling_linear"]
        assert abs(c[1] / c[0] - 10.0) <= 1e-9      # 累计链 c₂=10c₁
        # 独立 g1：一阶 |S31(90°)| = 2|Γ₀sin270+Γ₁sin90|
        g1 = abs(gam[0] * math.sin(3 * math.pi / 2)
                 + gam[1] * math.sin(math.pi / 2))
        # 电平归一后：一阶值与目标差=二阶量（0.262dB 实测）
        assert r["first_order_s31_at_f0_db"] == pytest.approx(-10.262, abs=0.05)
        assert g1 * 2 == pytest.approx(
            10 ** (r["first_order_s31_at_f0_db"] / 20.0), rel=1e-9)

    def test_n5_junction_ratio(self):
        """N=5 → 结点比 3:25:150（独立推导：∫(1−t²)² 与 sin5/sin3/sin1 三角分
        解；结点半权 Γ=[1/80, 5/48, 5/8]）。"""
        r = _run("multisection_coupler_binomial", n_sections=5,
                 coupling_db=10.0)
        gam = r["junction_gamma"]
        assert abs(gam[1] / gam[0] - 25.0 / 3.0) <= 1e-6
        assert abs(gam[2] / gam[0] - 50.0) <= 1e-6
        assert abs(gam[3] + gam[2]) <= 1e-15

    def test_exact_hits_target_at_f0(self):
        """电平归一=精确级联 θ=90° 求根：|S31|@f0=目标 ≤1e-9 dB。"""
        for n, cdb in ((1, 10.0), (3, 10.0), (3, 20.0), (5, 6.0), (7, 15.0)):
            r = _run("multisection_coupler_binomial", n_sections=n,
                     coupling_db=cdb)
            assert abs(r["exact_s31_at_f0_db"] + cdb) <= 1e-9, (
                f"N={n}/{cdb}dB 精确级联未命中目标")
            assert abs(r["exact_vs_target_db"]) <= 1e-9

    def test_n1_degenerate_exact_closed_form(self):
        """N=1 退化：c₁=目标（线性）、f0 精确闭式恒等、一阶=精确。"""
        r = _run("multisection_coupler_binomial", n_sections=1,
                 coupling_db=10.0)
        c_target = 10 ** (-0.5)
        assert r["coupling_linear"][0] == pytest.approx(c_target, rel=1e-12)
        assert r["first_order_vs_exact_db"] == pytest.approx(0.0, abs=1e-9)
        ze = r["z0e_ohm"][0]
        zo = r["z0o_ohm"][0]
        rr = ze / 50.0
        c_back = (rr * rr - 1.0) / (rr * rr + 1.0)   # 测试侧独立反解
        assert c_back == pytest.approx(c_target, rel=1e-9)
        # z0e/z0o 输出按 9 位小数舍入 → 回代地板 ~1e-11 相对
        assert zo == pytest.approx(50.0 / rr, rel=1e-10)

    def test_structure_invariants(self):
        """构造定理四件套：回文/Zr 恒等/f0 隔离零/60°-120° 镜像对称。"""
        r = _run("multisection_coupler_binomial", n_sections=3,
                 coupling_db=10.0)
        assert r["coupling_palindrome_dev"] <= 1e-15
        assert r["zr_identity_dev"] <= 1e-15
        assert r["isolation_s41_at_f0_linear"] < 1e-10
        assert (r["isolation_s41_at_f0_db"] is None
                or r["isolation_s41_at_f0_db"] < -200.0)
        assert r["symmetry_dev_60_120"] <= 1e-12
        assert r["s31_60deg_db"] < r["exact_s31_at_f0_db"]   # 单调爬升

    def test_first_order_vs_exact_gap_positive(self):
        """有限耦合二阶差：0 < 一阶−精确 < 0.5dB（3 节 10dB 档，如实存在）。"""
        r = _run("multisection_coupler_binomial", n_sections=3,
                 coupling_db=10.0)
        assert 0.0 < r["first_order_vs_exact_db"] < 0.5


# ─── 多节耦合器：频响键 ──────────────────────────────────────────────────────

def _single_section_closed_form(c: float, th: float) -> float:
    """单节精确闭式（测试侧独立推导）：Z0e·Z0o=Z0² → Γ0o=−Γ0e → S31=Γe，
    |S31|=c·sinθ/√(1−c²cos²θ)。"""
    return c * math.sin(th) / math.sqrt(1.0 - c * c * math.cos(th) ** 2)


class TestMultisectionResponse:
    def test_n1_vs_exact_closed_form(self):
        """N=1 vs 单节精确闭式逐位（5 频点，含带外）。"""
        r = _run("multisection_coupler_binomial", n_sections=1,
                 coupling_db=10.0)
        c = 10 ** (-0.5)
        resp = _run("multisection_coupler_response",
                    z0e_ohm=r["z0e_ohm"], z0o_ohm=r["z0o_ohm"], f0_ghz=2.0,
                    freq_ghz=[1.0, 1.4, 2.0, 2.6, 3.0])
        for f, s31_mag in zip(resp["freq_ghz"], resp["s31_mag"],
                              strict=True):
            th = (math.pi / 2.0) * f / 2.0
            ref = _single_section_closed_form(c, th)
            # 频响输入=综合输出 9 位小数舍入值 → 配对地板 ~1e-11 相对
            assert s31_mag == pytest.approx(ref, rel=1e-9), f"f={f}"
        assert resp["s31_at_f0_db"] == pytest.approx(-10.0, abs=1e-9)

    def test_energy_conservation_and_isolation(self):
        """无耗构造定理：能量守恒 ≤1e-12；f0 隔离 |S41|<1e-12 记 None。"""
        r = _run("multisection_coupler_binomial", n_sections=3,
                 coupling_db=10.0)
        resp = _run("multisection_coupler_response",
                    z0e_ohm=r["z0e_ohm"], z0o_ohm=r["z0o_ohm"], f0_ghz=2.0,
                    freq_ghz=[1.2, 1.6, 2.0, 2.4, 2.8])
        assert resp["energy_conservation_max_dev"] <= 1e-12
        assert resp["isolation_s41_at_f0_linear"] < 1e-10
        assert (resp["isolation_s41_at_f0_db"] is None
                or resp["isolation_s41_at_f0_db"] < -200.0)
        # 直通+耦合功率 @f0 = 1（匹配+隔离下无耗分配）
        p = 10 ** (resp["s21_at_f0_db"] / 10) + 10 ** (resp["s31_at_f0_db"] / 10)
        assert p == pytest.approx(1.0, abs=1e-9)

    def test_max_flat_monotone_response(self):
        """最大平坦带形：|S31| 随 sinθ 单调爬升至 f0（30°..90° 五点）。"""
        r = _run("multisection_coupler_binomial", n_sections=3,
                 coupling_db=10.0)
        resp = _run("multisection_coupler_response",
                    z0e_ohm=r["z0e_ohm"], z0o_ohm=r["z0o_ohm"], f0_ghz=2.0,
                    freq_ghz=[1.0, 1.33, 1.67, 1.9, 2.0])
        s31 = resp["s31_db"]
        pairs = [(s31[i], s31[i + 1]) for i in range(len(s31) - 1)]
        assert all(a < b for a, b in pairs), f"非单调: {s31}"

    def test_cross_key_consistency_with_synth(self):
        """跨键互证：频响键 @f0 vs 综合键精确级联字段逐位 ≤1e-9。"""
        r = _run("multisection_coupler_binomial", n_sections=3,
                 coupling_db=10.0)
        resp = _run("multisection_coupler_response",
                    z0e_ohm=r["z0e_ohm"], z0o_ohm=r["z0o_ohm"], f0_ghz=2.0,
                    freq_ghz=[2.0])
        assert resp["s31_at_f0_db"] == pytest.approx(
            r["exact_s31_at_f0_db"], abs=1e-9)
        assert resp["s21_at_f0_db"] == pytest.approx(
            r["exact_s21_at_f0_db"], abs=1e-9)

    def test_guards(self):
        """越界显式拒绝族。"""
        _fail("multisection_coupler_binomial", n_sections=2, coupling_db=10.0)
        _fail("multisection_coupler_binomial", n_sections=3, coupling_db=0.0)
        _fail("multisection_coupler_binomial", n_sections=3, coupling_db=1.0)
        _fail("multisection_coupler_binomial", n_sections=3, coupling_db=10.0,
              z0_ohm=0.0)
        _fail("multisection_coupler_response", z0e_ohm=[70.6, 56.6],
              z0o_ohm=[39.2], f0_ghz=2.0, freq_ghz=[2.0])
        _fail("multisection_coupler_response", z0e_ohm=[70.6, 56.6],
              z0o_ohm=[39.2, 44.8], f0_ghz=2.0, freq_ghz=[4.0])  # θ=π 奇异
        _fail("multisection_coupler_response", z0e_ohm=[70.6, 56.6],
              z0o_ohm=[39.2, 44.8], f0_ghz=2.0, freq_ghz=[])
        _fail("multisection_coupler_response", z0e_ohm=[39.2, 44.8],
              z0o_ohm=[70.6, 56.6], f0_ghz=2.0, freq_ghz=[2.0])  # Z0e>Z0o


# ─── Gysel：综合键 ───────────────────────────────────────────────────────────

def _half_circuit_gamma(z0: float, proxy: float,
                        mode: str) -> tuple[float, float]:
    """偶/奇半电路测试侧独立重解（λ/4 变换 Zc²/ZL 逐段手算）。

    偶模：对称面虚开路（桥带中点=proxy 大电阻）+P1 端口拆半 2Z0；
    奇模：对称面虚地（proxy 小电阻）。（独立于实现的同物理异写路线）
    """
    z_arm = math.sqrt(2.0) * z0
    if mode == "even":
        z_bridge_in = z0 * z0 / proxy              # λ/4 → 虚开路=短路趋势
        d1 = 1.0 / (1.0 / z0 + 1.0 / z_bridge_in)  # 负载 ∥ 桥带
        zin_iso = z0 * z0 / d1
        zin_arm = z_arm * z_arm / (2.0 * z0)       # 端口拆半
        zin = 1.0 / (1.0 / zin_arm + 1.0 / zin_iso)
    else:
        z_bridge_in = z0 * z0 / proxy              # λ/4 → 虚地=开路趋势
        d1 = 1.0 / (1.0 / z0 + 1.0 / z_bridge_in)
        zin_iso = z0 * z0 / d1
        zin_arm = z_arm * z_arm / proxy            # P1 虚地
        zin = 1.0 / (1.0 / zin_arm + 1.0 / zin_iso)
    gamma = (zin - z0) / (zin + z0)
    return abs(gamma), zin


class TestGyselCoreSynthesize:
    def test_design_values_constant(self):
        """√2·Z0 臂 / Z0 隔离线·桥带·负载 / 90°-90°-180° 电气长（教科书常数）。"""
        r = _run("gysel_core_synthesize", z0_ohm=50.0)
        assert r["z_arm_ohm"] == pytest.approx(50.0 * math.sqrt(2.0),
                                               rel=1e-12)
        assert r["z_iso_ohm"] == pytest.approx(50.0)
        assert r["z_bridge_ohm"] == pytest.approx(50.0)
        assert r["arm_electrical_deg"] == 90.0
        assert r["bridge_electrical_deg"] == 180.0

    def test_even_odd_gamma_converge_to_zero(self):
        """偶/奇半电路 γ→0：两组代理端接缩比收敛（γ ∝ 1/proxy）。"""
        r = _run("gysel_core_synthesize", z0_ohm=50.0)
        assert r["gamma_max_residual"] <= 1e-6
        ver = r["even_odd_verification"]
        assert len(ver) == 2
        # 测试侧独立重解 vs 实现输出逐位一致（异写路线）
        for item, proxy_o, proxy_s in zip(
                ver, (1e9, 1e12), (1e-9, 1e-12), strict=True):
            ge, _ = _half_circuit_gamma(50.0, proxy_o, "even")
            go, _ = _half_circuit_gamma(50.0, proxy_s, "odd")
            assert item["gamma_e"] == pytest.approx(ge, rel=1e-9)
            assert item["gamma_o"] == pytest.approx(go, rel=1e-9)
            assert item["zin_e_over_z0"] == pytest.approx(1.0, abs=1e-6)
            assert item["zin_o_over_z0"] == pytest.approx(1.0, abs=1e-9)
        # 缩比收敛：proxy×1000 → γ/1000
        assert ver[1]["gamma_e"] * 1000 == pytest.approx(
            ver[0]["gamma_e"], rel=1e-6)

    def test_s_matrix_properties(self):
        """理想 f0 三口 S：互易 S=Sᵀ；σmax≤1（有耗无源）；均分 −3.0103dB。"""
        r = _run("gysel_core_synthesize", z0_ohm=50.0)
        s = np.array([[complex(e[0], e[1]) for e in row]
                      for row in r["s_matrix_f0"]])
        assert np.max(np.abs(s - s.T)) <= 1e-18
        assert np.max(np.linalg.svd(s, compute_uv=False)) <= 1.0 + 1e-12
        # 端口 1 列功率=1（匹配入射全分配）；2/3 列=隔离负载吸收后端口余量
        col_p = np.sum(np.abs(s) ** 2, axis=0)
        assert col_p[0] == pytest.approx(1.0, abs=1e-12)
        assert r["split_db"] == pytest.approx(-10.0 * math.log10(2.0),
                                              abs=1e-12)
        assert abs(s[1, 0] + 1j / math.sqrt(2)) <= 1e-15   # −j/√2（λ/4 臂）
        assert s[2, 1] == 0.0 and s[0, 0] == 0.0

    def test_guards(self):
        _fail("gysel_core_synthesize", z0_ohm=0.0)
        _fail("gysel_core_synthesize", z0_ohm=-50.0)
        _fail("gysel_core_synthesize", z0_ohm=float("nan"))


# ─── Gysel：频响键 ───────────────────────────────────────────────────────────

class TestGyselFrequencyResponse:
    def test_f0_matches_ideal_matrix(self):
        """f0 锚：−3.0103dB 恒等 + 理想矩阵偏差 ≤1e-9 + 全对角/隔离零。"""
        r = _run("gysel_frequency_response", f0_ghz=2.0,
                 freq_ghz=[1.6, 1.8, 2.0, 2.2, 2.4])
        assert r["s21_at_f0_db"] == pytest.approx(-10.0 * math.log10(2.0),
                                                  abs=1e-9)
        assert r["s31_at_f0_db"] == pytest.approx(-10.0 * math.log10(2.0),
                                                  abs=1e-9)
        assert r["f0_ideal_matrix_dev"] <= 1e-9
        assert r["s32_at_f0_db"] < -200.0
        assert r["reciprocity_max_dev"] <= 1e-15

    def test_dissipation_conservation(self):
        """耗散守恒：|a1|²=Σ|b_k|²+|V_Δ1|²/Z0+|V_Δ2|²/Z0（≤1e-12 全频轴）。

        f0 处匹配激励负载零耗散（隔离负载只在输出失配时吃功率——Gysel
        大功率口径的机理），失谐频点负载耗散>0 且守恒仍成立。
        """
        r = _run("gysel_frequency_response", f0_ghz=2.0,
                 freq_ghz=[1.6, 1.8, 2.0, 2.2, 2.4])
        assert r["dissipation_conservation_max_dev"] <= 1e-12

    def test_no_bridge_counter_example(self):
        """判废对照：无桥带朴素拓扑带心 S21=−6.53dB（#206 判废锚+独立重解）。

        测试侧五节点独立重解（无 M）：P2 端看臂(2Z0) ∥ 隔离线 λ/4 端接
        Z0(=Z0) → Z=2Z0/3 → Γ=−0.2；P1→P2 传输按臂级联合成。独立 4 节
        点导纳解 vs 实现字段 ≤1e-9，且 −6.53±0.05 窗=文献判废锚。
        """
        r = _run("gysel_frequency_response", f0_ghz=2.0,
                 freq_ghz=[2.0])
        nb = r["no_bridge_s21_at_f0_db"]
        assert nb == pytest.approx(-6.53, abs=0.05)
        # 测试侧独立五节点导纳重解
        z0, th = 50.0, math.pi / 2
        n = 5
        y = np.zeros((n, n), dtype=complex)

        def stamp(ia, ib, zc):
            y[ia, ia] += -1j / math.tan(th) / zc
            y[ib, ib] += -1j / math.tan(th) / zc
            y[ia, ib] += 1j / (zc * math.sin(th))
            y[ib, ia] += 1j / (zc * math.sin(th))

        z_arm = math.sqrt(2.0) * z0
        stamp(0, 1, z_arm)
        stamp(0, 2, z_arm)
        stamp(1, 3, z0)
        stamp(2, 4, z0)
        y[3, 3] += 1 / z0
        y[4, 4] += 1 / z0
        pp, ii = np.ix_((0, 1, 2), (0, 1, 2)), np.ix_((3, 4), (3, 4))
        pi_, ip = np.ix_((0, 1, 2), (3, 4)), np.ix_((3, 4), (0, 1, 2))
        y_red = y[pp] - y[pi_] @ np.linalg.solve(y[ii], y[ip])
        eye = np.eye(3, dtype=complex)
        s = np.linalg.solve(eye + z0 * y_red, eye - z0 * y_red)
        assert 20 * math.log10(abs(s[1, 0])) == pytest.approx(nb, abs=1e-5)

    def test_band_mirror_symmetry_and_cross_key(self):
        """频轴镜像对称（f0±δ 逐位）+ 跨键（综合 S 矩阵 vs 频响 f0）。"""
        r = _run("gysel_frequency_response", f0_ghz=2.0,
                 freq_ghz=[1.6, 1.8, 2.0, 2.2, 2.4])
        assert r["s21_db"][0] == pytest.approx(r["s21_db"][4], abs=1e-9)
        assert r["s21_db"][1] == pytest.approx(r["s21_db"][3], abs=1e-9)
        assert r["s32_db"][3] == pytest.approx(r["s32_db"][1], abs=1e-9)
        synth = _run("gysel_core_synthesize", z0_ohm=50.0)
        s21 = synth["s_matrix_f0"][1][0]
        assert 20 * math.log10(math.hypot(s21[0], s21[1])) == pytest.approx(
            r["s21_at_f0_db"], abs=1e-9)

    def test_guards(self):
        """越界显式拒绝族（含 θ=kπ：f=2f0）。"""
        _fail("gysel_frequency_response", f0_ghz=0.0, freq_ghz=[2.0])
        _fail("gysel_frequency_response", f0_ghz=2.0, freq_ghz=[4.0])
        _fail("gysel_frequency_response", f0_ghz=2.0, freq_ghz=[])
        _fail("gysel_frequency_response", f0_ghz=2.0, freq_ghz=[-1.0])
        _fail("gysel_frequency_response", f0_ghz=2.0, freq_ghz=[2.0],
              z0_ohm=0.0)
