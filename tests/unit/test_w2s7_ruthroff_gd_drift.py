"""aurora_f W2-S7 席锚树：ruthroff_balun 两键（Ruthroff 巴伦设计/频响）
+ gd_equalizer 两键（全通节综合/级联频响）+ measurement_drift 两键
（测量漂移估计/监控）。

数值断言口径（#118 不自证——闭式测试侧独立重解/教科书极限恒等/异构路线
互证/判废对照/合成回收，不用实现侧公式互证自身）：
- Ruthroff 设计：4:1/9:1 的 n 与 Z0=√(Rin·Rlo) 恒等式；带缘判据常数链
  （θ_bd=arccos(1−u)、u 为 (1−5γ²)u²+16γ²u−16γ² 精确根，γ=0.1；l_max/
  f_zero 链）；带缘跨键一致（设计 l_max 处频响 |S11|=0.1）；与 Guanella
  同比值同 Z0 档对拍（同仓双源：guanella_tlt_design 实调对比块逐字段
  互证）；≥16:1 复合拓扑与 5:1 复合比显式拒绝（族界如实）。
- Ruthroff 频响（W7-S25 P1-1/P2-1 修正体，审查 runs/aurora_f/
  review_w6_kernel.md）：**真独立双路线**——① KCL 全节点方程求解（4 端
  子分支方程直写、零 Y₂ₚ 形成、功率波 a/b 带 √R 归一）② 4 端子差分导纳
  congruence（Y4=Tᵀ·Y2·T+节点映射+消 GND）——两路线互证并对照实现盖章
  ≤1e-9，KCL 残差 ≤1e-12、无耗幺正 ≤1e-12；闭式第三锚：Z_in=Z0[2ρ(1+
  cosθ)+j sinθ]/[cosθ+jρ sinθ]、G=16ρ²(1+cosθ)²/[(1+4ρ²)²sin²θ+4ρ²(1+
  3cosθ)²]、最优档 |S11|²=(1−cosθ)²/[(1+3cosθ)²+4sin²θ]（测试侧独立推
  导）≤1e-9；Ranzani 式(3) 低电长匹配锚（θ→0：Z_in→4R_out、G→1、θ=15°
  近单位增益）；θ=90° 非匹配反向锚（|S11|=√0.2、G=0.8、Z_in=R_in−2jZ0
  ——防旧"λ/4 匹配点"错误模型回潮）；θ→π 传输零点渐近（G<0.01）；无耗
  功率守恒 ≤1e-12 与互易 S12=S21 ≤1e-12。
- 全通节综合：零极点镜像残差逐位 0（D(−s)/D(s) 构造定理）；一阶
  τ_dc 参数化回收（a=2/τ_dc→小频点 τ 回收 ≤1e-9）；二阶 τ_peak
  参数化回收（Q=τ_pk·ω0/4→f0 处 τ=τ_pk、直流 τ=2/(Qω0) 双点回收）。
- 级联频响：|S21|≡1 全频轴平坦度 ≤1e-10 dB（全通定义恒等式）；级联
  时延可加性（两节合计 vs 单节跑和 ≤1e-15）；群时延曲线积分语义
  ∫₀^∞ τ dω=order·π（数值 Simpson+解析尾项 ≤1e-6 相对）；相位差与
  带内时延积分一致性（≤5% 带限语义）。
- 漂移估计：无噪合成线性漂移斜率逐位回收 ≤1e-12、去趋势校正序列恒定
  ≤1e-12（#340 回收钉范式）；已知 σ 档 se=σ/√Sxx 独立重算恒等 + z 带
  端点恒等；零漂交替序列假阳钉（drift_detected=False 且 0∈CI）；
  残差 t 档 sigma_source/distribution 如实 + se=s/√Sxx 独立重算。
- 漂移监控：SPC 控制限恒等式 UCL−μ₀=L·σ·√(λ/(2−λ)·(1−(1−λ)^{2i}))
  独立重算偏差 ≤1e-12；合成漂移注入（阶跃斜坡）→ CUSUM 越限回收
  （breach_at 落窗内）+ verdict 组合；稳定序列三线不告警（假阳钉）；
  复用钉：与直接调用 anchor_drift_spc.ewma_control/cusum_test 同参逐
  字段一致（同仓双源）。
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

_C0 = 299792458.0


def _run(name: str, **params: object) -> dict:
    out = run_calculator(name, params)
    assert out["ok"], f"{name} 失败: {out.get('error')!r}"
    return out["result"]


def _fail(name: str, **params: object) -> None:
    out = run_calculator(name, params)
    assert out["ok"] is False and out.get("error"), (
        f"{name}({params}) 应显式拒绝，得到 ok={out.get('ok')!r}")


NEW_KEYS = (
    "ruthroff_balun_design", "ruthroff_balun_response",
    "gd_allpass_section_synthesize", "gd_equalizer_cascade_response",
    "measurement_drift_estimate", "measurement_drift_monitor")


# ─── 描述形态门（R5 §①：中文名全由 description 自带）────────────────────────

@pytest.mark.parametrize("key", NEW_KEYS)
def test_description_zh_head_form(key: str) -> None:
    import re

    spec = CALCULATOR_REGISTRY.get(key)
    head = re.split(r"[：:]", str(spec.description or ""))[0].strip()
    assert head and re.search(r"[\u4e00-\u9fff]", head)
    assert len(head) <= 24, f"{key} 中文名超 24 字符: {head!r}"


# ─── Ruthroff 设计（ruthroff_balun_design）───────────────────────────────────

class TestRuthroffDesign:
    def test_n2_ratio_and_z_line_identity(self):
        for r_in, n in ((200.0, 2), (450.0, 3)):
            out = _run("ruthroff_balun_design", r_in_ohm=r_in,
                       r_out_ohm=50.0)
            assert out["ratio_n"] == n
            assert abs(out["z_line_ohm"] - math.sqrt(r_in * 50.0)) <= 1e-9
            assert abs(out["impedance_ratio"] - n * n) <= 1e-9
            assert out["n_lines"] == (1 if n == 2 else 4)

    def test_band_edge_constant_chain(self):
        # 带缘判据常数链：γ=0.1 的精确二次根 → θ_bd=arccos(1−u)、
        # l_max=θ_bd·v_f·c/(2π·f_max)、f_zero=f_max·π/θ_bd（测试侧独立
        # 求根，不读实现侧常数）
        out = _run("ruthroff_balun_design", r_in_ohm=200.0,
                   r_out_ohm=50.0, f_max_ghz=2.0, v_f=1.0)
        gamma = out["s11_band_max"]
        assert gamma == 0.1
        g2 = gamma * gamma
        u = ((-16.0 * g2 + math.sqrt(256.0 * g2 * g2
                                     + 64.0 * g2 * (1.0 - 5.0 * g2)))
             / (2.0 * (1.0 - 5.0 * g2)))
        assert 0.0 < u < 1.0
        th_bd_deg = math.degrees(math.acos(1.0 - u))
        th_bd_rad = math.radians(th_bd_deg)
        assert abs(out["theta_band_deg"] - th_bd_deg) <= 1e-9
        l_max_mm = th_bd_rad * _C0 / (2.0 * math.pi * 2.0e9) * 1e3
        assert abs(out["l_max_mm"] - l_max_mm) <= 1e-9
        f_zero = _C0 / (2.0 * (l_max_mm * 1e-3)) / 1e9
        assert abs(out["f_zero_ghz"] - f_zero) <= 1e-9
        assert abs(f_zero - 2.0 * math.pi / th_bd_rad) <= 1e-9

    def test_band_edge_matches_response_key(self):
        # 带缘跨键一致：设计 l_max 处频响 |S11|=0.1（-20 dB）精确落点
        out = _run("ruthroff_balun_design", r_in_ohm=200.0,
                   r_out_ohm=50.0, f_max_ghz=2.0, v_f=1.0)
        resp = _run("ruthroff_balun_response", r_in_ohm=200.0,
                    r_out_ohm=50.0, length_mm=out["l_max_mm"],
                    freq_ghz=[2.0])
        assert abs(resp["s11_db"][0] + 20.0) <= 0.01
        # 带内（半长）回损优、带外（倍长）回损劣——单调语义
        inside = _run("ruthroff_balun_response", r_in_ohm=200.0,
                      r_out_ohm=50.0, length_mm=out["l_max_mm"] / 2.0,
                      freq_ghz=[2.0])
        outside = _run("ruthroff_balun_response", r_in_ohm=200.0,
                       r_out_ohm=50.0, length_mm=out["l_max_mm"] * 2.0,
                       freq_ghz=[2.0])
        assert inside["s11_db"][0] < resp["s11_db"][0] < outside["s11_db"][0]

    def test_guanella_contrast_same_warehouse_dual_source(self):
        # 同仓双源：对比块 vs guanella_tlt_design 实调（同比值同 Z0 档）
        out = _run("ruthroff_balun_design", r_in_ohm=200.0,
                   r_out_ohm=50.0)
        gua = _run("guanella_tlt_design", r_in_ohm=200.0, r_out_ohm=50.0)
        assert out["guanella_contrast"]["n_lines_guanella"] == \
            gua["n_lines"]
        assert out["guanella_contrast"]["z_line_ohm"] == gua["z_line_ohm"]
        assert out["z_line_ohm"] == gua["z_line_ohm"]

    def test_compound_and_oversize_ratio_rejected(self):
        _fail("ruthroff_balun_design", r_in_ohm=150.0, r_out_ohm=50.0)
        _fail("ruthroff_balun_design", r_in_ohm=800.0, r_out_ohm=50.0)
        _fail("ruthroff_balun_design", r_in_ohm=50.0, r_out_ohm=50.0)


# ─── Ruthroff 频响（ruthroff_balun_response；W7-S25 P1-1/P2-1 修正体）────────

_L_MM = 18.737028625  # θ=90°@4GHz（旧"λ/4 频率"留作非匹配反向锚载体）


def _theta(f_ghz: float, l_mm: float = _L_MM, v_f: float = 1.0) -> float:
    return 2.0 * math.pi * f_ghz * 1e9 * (l_mm * 1e-3) / (v_f * _C0)


def _line_y2(theta: float, z0: float) -> np.ndarray:
    """无耗线差分 2 口 Y（口=(近端对, 远端对)）——路线② 起点。"""
    ys = -1j * math.cos(theta) / (math.sin(theta) * z0)
    ym = 1j / (z0 * math.sin(theta))
    return np.array([[ys, ym], [ym, ys]], dtype=complex)


def _route_congruence(theta: float, z0: float, r_in: float,
                      r_out: float) -> np.ndarray:
    """路线②：4 端子差分导纳 congruence（Y4=Tᵀ·Y2·T，u=T·V_t）+ 端子→
    节点映射（t1→A、t2→B、t3→GND、t4→A）+ 消 GND → (B, A) 口序 → D 标
    度 S。与实现侧半角项 2×2 直写形成路径异构。"""
    t = np.array([[1, 0, -1, 0], [0, 1, 0, -1]], dtype=complex)
    y4 = t.conj().T @ _line_y2(theta, z0) @ t
    m = np.zeros((4, 3), dtype=complex)  # 节点 A=0、B=1、GND=2
    for i, nd in enumerate((0, 1, 2, 0)):  # t1→A、t2→B、t3→GND、t4→A
        m[i, nd] = 1.0
    y_node = m.conj().T @ y4 @ m
    y2p = y_node[np.ix_([1, 0], [1, 0])]
    d = np.diag([math.sqrt(r_in), math.sqrt(r_out)])
    zs = d @ y2p @ d
    eye = np.eye(2, dtype=complex)
    return np.linalg.solve(eye + zs, eye - zs)


def _route_kcl(theta: float, z0: float, r_in: float,
               r_out: float, vs: float = 1.0) -> dict:
    """路线①：KCL 全节点（分支方程直写，零 Y₂ₚ 形成）+ 功率波 a/b
    （√R 归一）直接构 S——与任何导纳阵路径异构。

    线差分分支电流：u1=V_t1−V_t3=V_A、u2=V_t2−V_t4=V_B−V_A；
    i_t1=Ys·u1+Ym·u2（落于 A）、i_t2=Ym·u1+Ys·u2（落于 B）、
    i_t4=−i_t2（落于 A）。KCL-A: i_t1+i_t4+V_A/R_out=0；
    KCL-B: i_t2+(V_B−V_s)/R_in=0。
    """
    ys = -1j * math.cos(theta) / (math.sin(theta) * z0)
    ym = 1j / (z0 * math.sin(theta))
    a_mat = np.array([
        [(2.0 * ys - 2.0 * ym) + 1.0 / r_out, ym - ys],
        [ym - ys, ys + 1.0 / r_in]], dtype=complex)
    va, vb = np.linalg.solve(a_mat, np.array([0.0, vs / r_in],
                                             dtype=complex))
    i1 = (vs - vb) / r_in      # 口1（B 侧）进网络电流
    i2 = -va / r_out           # 口2（A 侧）进网络电流
    a1 = (vb + r_in * i1) / (2.0 * math.sqrt(r_in))
    b1 = (vb - r_in * i1) / (2.0 * math.sqrt(r_in))
    b2 = (va - r_out * i2) / (2.0 * math.sqrt(r_out))
    res_a = abs((2 * ys - 2 * ym) * va + (ym - ys) * vb + va / r_out)
    res_b = abs((ym - ys) * va + ys * vb + (vb - vs) / r_in)
    return {"s11": b1 / a1, "s21": b2 / a1, "zin": vb / i1,
            "kcl_res": max(res_a, res_b)}


def _closed_zin(theta: float, z0: float, r_out: float) -> complex:
    """闭式第三锚（测试侧独立推导）：Z_in=Z0[2ρ(1+cosθ)+j sinθ]/
    [cosθ+jρ sinθ]，ρ=R_out/Z0。"""
    rho = r_out / z0
    return z0 * (2.0 * rho * (1.0 + math.cos(theta))
                 + 1j * math.sin(theta)) / (
        math.cos(theta) + 1j * rho * math.sin(theta))


def _closed_gain(theta: float, z0: float, r_out: float) -> float:
    """闭式第三锚：G=16ρ²(1+cosθ)²/[(1+4ρ²)²sin²θ+4ρ²(1+3cosθ)²]。"""
    rho = r_out / z0
    return (16.0 * rho ** 2 * (1.0 + math.cos(theta)) ** 2
            / ((1.0 + 4.0 * rho ** 2) ** 2 * math.sin(theta) ** 2
               + 4.0 * rho ** 2 * (1.0 + 3.0 * math.cos(theta)) ** 2))


class TestRuthroffResponse:
    def test_dual_route_independent(self):
        # 真独立双路线（P2-1 重做）：KCL 全节点 vs congruence 导纳阵互证
        # ≤1e-12，并对照实现 s11/s21 dB 与 zin re/im ≤1e-9；KCL 残差/无耗
        # 幺正 ≤1e-12 构造自检；闭式第三锚 ≤1e-9
        freqs = [1.0, 2.0, 3.0, 5.0, 6.5]
        out = _run("ruthroff_balun_response", r_in_ohm=200.0,
                   r_out_ohm=50.0, length_mm=_L_MM, freq_ghz=freqs)
        r_in, r_out, z0 = 200.0, 50.0, 100.0
        for k, f in enumerate(freqs):
            th = _theta(f)
            s_k = _route_kcl(th, z0, r_in, r_out)
            s_c = _route_congruence(th, z0, r_in, r_out)
            assert s_k["kcl_res"] <= 1e-12
            unit = abs(1.0 - (abs(s_k["s11"]) ** 2 + abs(s_k["s21"]) ** 2))
            assert unit <= 1e-12
            assert abs(s_k["s11"] - s_c[0, 0]) <= 1e-12
            assert abs(s_k["s21"] - s_c[1, 0]) <= 1e-12
            assert abs(10.0 ** (out["s11_db"][k] / 20.0)
                       - abs(s_c[0, 0])) <= 1e-9
            assert abs(10.0 ** (out["s21_db"][k] / 20.0)
                       - abs(s_c[1, 0])) <= 1e-9
            zin_c = r_in * (1.0 + s_c[0, 0]) / (1.0 - s_c[0, 0])
            dev = abs(complex(out["zin_re_ohm"][k], out["zin_im_ohm"][k])
                      - zin_c)
            assert dev <= 1e-6
            assert abs(_closed_zin(th, z0, r_out) - s_k["zin"]) <= 1e-9

    def test_dc_match_anchor_ranzani_eq3(self):
        # Ranzani 式(3) 低电长匹配锚：θ→0 处 Z_in→4R_out、|S11|→0、G→1
        f0 = 1.0
        l_tiny = (math.radians(2.0) * _C0
                  / (2.0 * math.pi * f0 * 1e9) * 1e3)  # θ(f0)=2°
        out = _run("ruthroff_balun_response", r_in_ohm=200.0,
                   r_out_ohm=50.0, length_mm=l_tiny, freq_ghz=[f0])
        assert abs(out["theta_deg"][0] - 2.0) <= 1e-6
        assert out["s11_db"][0] <= -60.0
        assert out["s21_db"][0] >= -0.001
        assert abs(out["zin_re_ohm"][0] - 200.0) <= 0.5
        assert abs(out["zin_im_ohm"][0]) <= 0.05

    def test_low_band_near_unity_gain(self):
        # 审查数值锚（θ=15°）：|S11|≈0.008666、G≈0.999925、Z_in≈4.069R_out
        f0 = 1.0
        l_15 = (math.radians(15.0) * _C0
                / (2.0 * math.pi * f0 * 1e9) * 1e3)
        out = _run("ruthroff_balun_response", r_in_ohm=200.0,
                   r_out_ohm=50.0, length_mm=l_15, freq_ghz=[f0])
        assert abs(10.0 ** (out["s11_db"][0] / 20.0) - 0.008666) <= 2e-5
        assert abs(10.0 ** (out["s21_db"][0] / 10.0) - 0.999925) <= 2e-6
        assert abs(out["zin_re_ohm"][0] - 4.0693 * 50.0) <= 0.01

    def test_quarter_wave_reverse_anchor(self):
        # θ=90° 非匹配反向锚（防回潮）：|S11|=√0.2、G=0.8、Z_in=R_in−2jZ0
        # ——旧"λ/4 匹配点定理"（|S11|=0、Z_in=R_in）系错误模型产物
        out = _run("ruthroff_balun_response", r_in_ohm=200.0,
                   r_out_ohm=50.0, length_mm=_L_MM, freq_ghz=[4.0])
        assert abs(out["theta_deg"][0] - 90.0) <= 1e-6
        assert abs(10.0 ** (out["s11_db"][0] / 20.0)
                   - math.sqrt(0.2)) <= 1e-9
        assert abs(10.0 ** (out["s21_db"][0] / 10.0) - 0.8) <= 1e-9
        assert abs(out["zin_re_ohm"][0] - 200.0) <= 1e-6
        assert abs(out["zin_im_ohm"][0] + 200.0) <= 1e-6

    def test_closed_forms_optimal_and_offoptimal(self):
        # 最优档（ρ=1/2）|S11|²=(1−c)²/[(1+3c)²+4s²] 与 G 闭式；失配档
        # （z_line=80，ρ=0.625）G 闭式——测试侧独立推导 ≤1e-9
        freqs = [1.0, 2.0, 3.0, 5.0, 6.0]
        out = _run("ruthroff_balun_response", r_in_ohm=200.0,
                   r_out_ohm=50.0, length_mm=_L_MM, freq_ghz=freqs)
        for k, f in enumerate(freqs):
            th = _theta(f)
            c, s = math.cos(th), math.sin(th)
            s11_sq = (1.0 - c) ** 2 / ((1.0 + 3.0 * c) ** 2 + 4.0 * s * s)
            assert abs(10.0 ** (out["s11_db"][k] / 10.0) - s11_sq) \
                <= 1e-9 * max(1.0, s11_sq)
            g_ref = _closed_gain(th, 100.0, 50.0)
            assert abs(10.0 ** (out["s21_db"][k] / 10.0) - g_ref) \
                <= 1e-9 * max(1.0, g_ref)
        out2 = _run("ruthroff_balun_response", r_in_ohm=200.0,
                    r_out_ohm=50.0, length_mm=_L_MM, freq_ghz=freqs,
                    z_line_ohm=80.0)
        for k, f in enumerate(freqs):
            g_ref = _closed_gain(_theta(f), 80.0, 50.0)
            assert abs(10.0 ** (out2["s21_db"][k] / 10.0) - g_ref) \
                <= 1e-9 * max(1.0, g_ref)

    def test_pi_zero_approach_and_conservation(self):
        # θ→π 传输零点渐近（NIST 文"ratio goes to zero at θ=π"）
        out = _run("ruthroff_balun_response", r_in_ohm=200.0,
                   r_out_ohm=50.0, length_mm=_L_MM,
                   freq_ghz=[7.9, 7.99])
        for v in out["s21_db"]:
            assert v < -20.0
        assert out["power_conservation_max_dev"] <= 1e-12
        assert out["reciprocity_max_dev"] <= 1e-12
        # 9:1 双对复合拓扑如实拒绝（频响键只做 4:1 单线对）
        _fail("ruthroff_balun_response", r_in_ohm=450.0, r_out_ohm=50.0,
              length_mm=_L_MM, freq_ghz=[1.0])


# ─── 全通节综合（gd_allpass_section_synthesize）──────────────────────────────

class TestGdAllpassSection:
    def test_zero_pole_mirror_exact(self):
        for spec in ({"order": 1, "tau_dc_s": 2e-9},
                     {"order": 2, "f0_ghz": 1.0, "q": 5.0},
                     {"order": 2, "f0_ghz": 2.0, "tau_peak_s": 8e-9}):
            out = _run("gd_allpass_section_synthesize", **spec)
            assert out["zero_pole_mirror_max_dev"] == 0.0
            for p, z in zip(out["poles"], out["zeros"], strict=True):
                assert abs(z["re"] + p["re"]) == 0.0
                assert abs(z["im"] + p["im"]) == 0.0

    def test_first_order_tau_recovery(self):
        tau_dc = 2e-9
        out = _run("gd_allpass_section_synthesize", order=1,
                   tau_dc_s=tau_dc)
        assert abs(out["tau_dc_s"] - tau_dc) <= 1e-15
        # 小频点群时延回收（级联频响载体，τ(ω→0)→τ_dc）
        f_tiny = 1e-4 / (2.0 * math.pi) / tau_dc * 1e-9  # ωτ=1e-4
        resp = _run("gd_equalizer_cascade_response",
                    freq_ghz=[f_tiny],
                    sections=[{"order": 1, "tau_dc_s": tau_dc}])
        assert abs(resp["group_delay_s"][0] / tau_dc - 1.0) <= 1e-8

    def test_second_order_peak_and_dc_recovery(self):
        # τ_peak 参数化→Q=τ_pk·ω0/4→f0 处 τ=τ_pk、直流 τ=2/(Qω0) 双点
        f0, tau_pk = 1.0, 8e-9
        out = _run("gd_allpass_section_synthesize", order=2, f0_ghz=f0,
                   tau_peak_s=tau_pk)
        w0 = 2.0 * math.pi * f0 * 1e9
        q = tau_pk * w0 / 4.0
        assert abs(out["q"] - q) <= 1e-12
        assert abs(out["tau_peak_s"] - tau_pk) <= 1e-15
        resp = _run("gd_equalizer_cascade_response",
                    freq_ghz=[1e-7, f0],
                    sections=[{"order": 2, "f0_ghz": f0,
                               "tau_peak_s": tau_pk}])
        tau_dc_ref = 2.0 / (q * w0)
        assert abs(resp["group_delay_s"][0] / tau_dc_ref - 1.0) <= 1e-6
        assert abs(resp["group_delay_s"][1] / tau_pk - 1.0) <= 1e-6


# ─── 级联频响（gd_equalizer_cascade_response）────────────────────────────────

_SECTIONS2 = [{"order": 1, "tau_dc_s": 2e-9},
              {"order": 2, "f0_ghz": 1.0, "q": 5.0}]
_FREQS = [0.05, 0.1, 0.3, 0.8, 2.0]


class TestGdCascade:
    def test_allpass_identity_flatness(self):
        out = _run("gd_equalizer_cascade_response", freq_ghz=_FREQS,
                   sections=_SECTIONS2)
        assert out["total_order"] == 3
        for v in out["s21_db"]:
            assert abs(v) <= 1e-10
        assert abs(out["s21_flatness_max_dev_db"]) <= 1e-10

    def test_cascade_additivity(self):
        total = _run("gd_equalizer_cascade_response", freq_ghz=_FREQS,
                     sections=_SECTIONS2)
        part_a = _run("gd_equalizer_cascade_response", freq_ghz=_FREQS,
                      sections=[_SECTIONS2[0]])
        part_b = _run("gd_equalizer_cascade_response", freq_ghz=_FREQS,
                      sections=[_SECTIONS2[1]])
        for k in range(len(_FREQS)):
            summed = part_a["group_delay_s"][k] + part_b["group_delay_s"][k]
            # 输出按 18 位小数舍入：两侧各 ≤5e-19 舍入残差——容差取
            # 3e-18 绝对（舍入底）+1e-12 相对（可加性语义钉）
            assert abs(total["group_delay_s"][k] - summed) <= (
                3e-18 + 1e-12 * abs(summed))
        assert abs(total["tau_dc_total_s"]
                   - (part_a["tau_dc_total_s"]
                      + part_b["tau_dc_total_s"])) <= 1e-12 * abs(
            total["tau_dc_total_s"])

    def test_phase_integral_semantics(self):
        # ∫₀^∞ τ dω = order·π（数值 Simpson+解析尾项 ≤1e-6 相对；
        # τ(0) 用参数化定义值前置——定义非被测对象）
        def _simpson(ws: list, taus: list) -> float:
            h = ws[1] - ws[0]
            acc = taus[0] + taus[-1]
            for i in range(1, len(ws) - 1):
                acc += taus[i] * (4.0 if i % 2 == 1 else 2.0)
            return acc * h / 3.0

        def _grid(w_lo: float, w_hi: float, n_int: int) -> list:
            return [w_lo + (w_hi - w_lo) * i / n_int for i in range(n_int + 1)]

        def _taus_at(sections: list, ws: list) -> list:
            out = _run("gd_equalizer_cascade_response",
                       freq_ghz=[w / (2.0 * math.pi) / 1e9 for w in ws],
                       sections=sections)
            return out["group_delay_s"]

        # 一阶：全域单段 [0, 400/τ_dc]，解析尾项 π−2·arctan(W/a)
        tau_dc = 2e-9
        a = 2.0 / tau_dc
        w_max = 400.0 / tau_dc
        ws = _grid(0.0, w_max, 20000)
        taus1_first = _taus_at([_SECTIONS2[0]], ws[1:])
        taus = [tau_dc, *taus1_first]
        total = _simpson(ws, taus) + (math.pi - 2.0 * math.atan(w_max / a))
        assert abs(total / math.pi - 1.0) <= 1e-6

        # 二阶：复合两段 [0, 10ω0]∪[10ω0, W]，尾项 2(ω0/Q)/W
        f0, q = 1.0, 5.0
        w0 = 2.0 * math.pi * f0 * 1e9
        w_ten, w_far = 10.0 * w0, 2.0 * math.pi * 400e9
        ws1 = _grid(0.0, w_ten, 20000)
        taus1_rest = _taus_at([_SECTIONS2[1]], ws1[1:])
        taus1 = [2.0 / (q * w0), *taus1_rest]
        part1 = _simpson(ws1, taus1)
        ws2 = _grid(w_ten, w_far, 20000)
        taus2 = _taus_at([_SECTIONS2[1]], ws2)
        part2 = _simpson(ws2, taus2)
        tail = 2.0 * (w0 / q) / w_far
        total2 = part1 + part2 + tail
        assert abs(total2 / (2.0 * math.pi) - 1.0) <= 1e-6

    def test_band_delay_phase_consistency(self):
        # 带限语义：Δφ(带内) ≈ ∫_带 τ dω（矩形和中点语义一致性 ≤10%
        # ——精度锚=上面积分恒等式，此处只钉"相位差=时延积分"同积分微
        # 分为一的语义；带取 [0.1,0.6] 平滑段避开带缘二阶峰陡升）
        freqs = [0.1 + 0.025 * i for i in range(21)]
        out = _run("gd_equalizer_cascade_response", freq_ghz=freqs,
                   sections=_SECTIONS2)
        dw = 2.0 * math.pi * 0.025e9
        integ = sum(out["group_delay_s"]) * dw
        dphi = abs(out["phase_rad_unwrapped"][0]
                   - out["phase_rad_unwrapped"][-1])
        assert abs(integ - dphi) / dphi <= 0.10

    def test_guards(self):
        _fail("gd_equalizer_cascade_response", freq_ghz=[],
              sections=_SECTIONS2)
        _fail("gd_equalizer_cascade_response", freq_ghz=[-1.0],
              sections=_SECTIONS2)
        _fail("gd_equalizer_cascade_response", freq_ghz=_FREQS,
              sections=[])
        _fail("gd_equalizer_cascade_response", freq_ghz=_FREQS,
              sections=[{"order": 2, "f0_ghz": 1.0}])
        _fail("gd_equalizer_cascade_response", freq_ghz=_FREQS,
              sections=[{"order": 2, "f0_ghz": 1.0, "q": -1.0}])


# ─── 测量漂移估计（measurement_drift_estimate）───────────────────────────────

class TestMeasurementDriftEstimate:
    def test_exact_slope_recovery_and_correction(self):
        # 无噪合成线性漂移：斜率逐位回收 + 校正序列恒定（#340 回收钉范式）
        n, slope_true = 21, 0.05
        vals = [1.0 + slope_true * i for i in range(n)]
        out = _run("measurement_drift_estimate", values=vals, sigma=0.01)
        assert abs(out["slope_per_step"] - slope_true) <= 1e-12
        assert out["drift_detected"] is True
        assert abs(out["intercept"] - 1.0) <= 1e-12
        ybar = sum(vals) / n
        for v in out["corrected_values"]:
            assert abs(v - ybar) <= 1e-12  # 均值保持去趋势

    def test_known_sigma_se_identity(self):
        # se=σ/√Sxx 独立重算 + z 带端点恒等
        n = 21
        vals = [1.0 + 0.05 * i for i in range(n)]
        sigma = 0.01
        out = _run("measurement_drift_estimate", values=vals, sigma=sigma)
        sxx = sum((i - (n - 1) / 2) ** 2 for i in range(n))
        se_ref = sigma / math.sqrt(sxx)
        assert abs(out["slope_stderr"] - se_ref) <= 1e-15
        from statistics import NormalDist
        z = NormalDist().inv_cdf(0.975)
        assert abs(out["ci_low"]
                   - (out["slope_per_step"] - z * se_ref)) <= 1e-12
        assert abs(out["ci_high"]
                   - (out["slope_per_step"] + z * se_ref)) <= 1e-12
        assert out["sigma_source"] == "caller_declared"

    def test_zero_drift_false_alarm_pin(self):
        # 零漂交替序列（确定性）：不告警且 0∈CI（假阳率由 confidence 控制）
        vals = [5.0 + 0.02 * ((-1.0) ** i) for i in range(21)]
        out = _run("measurement_drift_estimate", values=vals, sigma=0.02)
        assert out["drift_detected"] is False
        assert out["ci_low"] <= 0.0 <= out["ci_high"]

    def test_residual_t_fallback_honest(self):
        # 未声明 σ：残差 s 走 t 带（sigma_source 如实），se=s/√Sxx 独立重算
        n = 12
        vals = [3.0 + 0.01 * i + 0.005 * ((-1.0) ** i) for i in range(n)]
        out = _run("measurement_drift_estimate", values=vals)
        assert out["sigma_source"] == "residual_t"
        assert out["distribution"].startswith("student_t_df")
        ybar = sum(vals) / n
        sxx = sum((i - (n - 1) / 2) ** 2 for i in range(n))
        slope = sum((i - (n - 1) / 2) * (vals[i] - ybar)
                    for i in range(n)) / sxx
        rss = sum((vals[i] - (ybar + slope * (i - (n - 1) / 2))) ** 2
                  for i in range(n))
        s = math.sqrt(rss / (n - 2))
        assert abs(out["slope_stderr"] - s / math.sqrt(sxx)) <= 1e-15
        assert abs(out["residual_std"] - s) <= 1e-15


# ─── 测量漂移监控（measurement_drift_monitor）────────────────────────────────

_SPC = dict(sigma=0.05, target=10.0, ewma_lambda=0.3, ewma_L=2.7,
            cusum_k=0.5, cusum_h=4.0)


class TestMeasurementDriftMonitor:
    def test_control_limit_identity(self):
        # UCL−μ₀=L·σ·√(λ/(2−λ)·(1−(1−λ)^{2i})) 独立重算 ≤1e-12
        vals = [10.0 + 0.001 * i for i in range(12)]
        out = _run("measurement_drift_monitor", values=vals, **_SPC)
        assert out["control_limit_identity_max_dev"] <= 1e-12
        for i, ucl in enumerate(out["ewma"]["ucl"], start=1):
            factor = (0.3 / 1.7) * (1.0 - 0.7 ** (2 * i))
            assert abs(ucl - 10.0 - 2.7 * 0.05 * math.sqrt(factor)) \
                <= 1e-12

    def test_synthetic_drift_injection_recovery(self):
        # 阶跃斜坡注入→CUSUM 越限回收（breach_at 落窗内）+ verdict 组合
        vals = [10.0] * 8 + [10.0 + 0.1 * (i - 7) for i in range(8, 16)]
        out = _run("measurement_drift_monitor", values=vals, **_SPC)
        assert out["cusum_alarm"] is True
        assert 9 <= out["cusum_breach_at"] <= 14
        assert out["cusum_breach_side"] == "high"
        assert out["verdict"] == "drifted"
        assert out["trend"]["alarm"] is True

    def test_stable_series_no_alarm(self):
        # 稳定序列：三线不告警（假阳钉）
        vals = [10.0 + 0.001 * i for i in range(12)]
        out = _run("measurement_drift_monitor", values=vals, **_SPC)
        assert out["verdict"] == "stable"
        assert out["fired_lines"] == []
        assert out["ewma_alarm"] is False
        assert out["cusum_alarm"] is False
        assert out["n_lines_computed"] == 3

    def test_reuse_parity_with_anchor_spc(self):
        # 复用钉：与直接调用 anchor_drift_spc 内核同参逐字段一致（同仓双源）
        from rfauto.core.anchor_drift_spc import cusum_test, ewma_control

        vals = [10.0 + 0.002 * math.sin(i) for i in range(12)]
        out = _run("measurement_drift_monitor", values=vals, **_SPC)
        ewma_ref = ewma_control(vals, sigma=0.05, target=10.0,
                                lam=0.3, L=2.7)
        cusum_ref = cusum_test(vals, sigma=0.05, target=10.0,
                               k=0.5, h=4.0)
        assert out["ewma"]["ewma"] == ewma_ref["ewma"]
        assert out["ewma"]["ucl"] == ewma_ref["ucl"]
        assert out["ewma"]["breach_at"] == ewma_ref["breach_at"]
        assert out["cusum"]["c_plus"] == cusum_ref["c_plus"]
        assert out["cusum"]["breach_at"] == cusum_ref["breach_at"]
        assert out["cusum"]["breach_side"] == cusum_ref["breach_side"]
