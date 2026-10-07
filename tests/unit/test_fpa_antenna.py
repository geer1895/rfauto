"""LM-1 Fabry-Perot 谐振腔天线内核单测（研究扩充 round4 中件包二 LM-1）。

裁判口径（#118 双径/独立来源）：
- 谐振恒等式：闭式解 h 回代 4πh/λ0−φ_PRS−φ_GND=2πN（规格钉 rel 1e-12；
  N=0 退化为 abs 1e-12，浮点上 4πh/λ0 残差 ~1e-15 rad 量级）；
- φ_PRS=φ_GND=0 → h=N·λ0/2 恒等式（规格 PMC/PPEC 口径）；
- D 恒等式：R=0→D=1 逐位；R=0.9→D=19 双径（路径 A=(1+R)/(1−R) 模块内、
  路径 B=2/(1−R)−1 测试内独立代数），rel 1e-9；
- 文献锚：Ji 2016 PIERL 58:73-79（DOI 10.2528/PIERL15101802，开放期刊，
  原文 PDF 已抓全文核对）：Eq.(1) 谐振条件 + 设计值 Lr=27 mm@5.5 GHz
  （PEC 地板）。论文未印 φ_PRS 数值——由本式反解隐含 φ_PRS≈176.7°，
  与均匀金属 PRS 的 ~180° 渐近口径差 1.8%，规格 ±5% 带内（预声明：
  反解频率取带心 5.5 GHz，带缘 5.35/5.76 GHz 时偏差 7% 超带——如实
  登记，锚只在带心判）；
- Q 面：无可达文献数字锚（如实 UNVERIFIED-lit）——双径裁判=能量衰减
  定义（内核）vs Airy 标准具半高全宽口径（测试内独立推导），rel ≤1.5%
  @R∈{0.5,0.9,0.99}（高精细度极限两口径渐近相等，R=0.5 处互差 1.05%
  手算核对）；
- 边界：R∉[0,1)/h<=0/f0<=0/NaN/bool → ValueError。

service 薄层测试（fpa_antenna_service.py，JSON 信封 ok=False 不抛）随本
文件跑（定向门文件面固定，见任务书）。
"""

from __future__ import annotations

import json
import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import fpa_antenna
from rfauto.service import fpa_antenna_service

# ─── 常量（独立手算路径，不经模块）────────────────────────────────────────────

C0 = 299792458.0
F0_GHZ = 5.5
LAM0_M = C0 / (F0_GHZ * 1e9)  # 0.0545077... m
JI_H_M = 0.027  # Ji 2016 设计值 Lr=27 mm
D_R09 = 19.0  # (1+0.9)/(1-0.9) 手算
D_R09_DB = 12.7875360095  # 10*log10(19) 手算（ln19/ln10*10）


# ─── 1. 谐振条件：恒等式与经典口径 ───────────────────────────────────────────


def _identity_residual_deg(h_m: float, f0_ghz: float, phi_prs_deg: float,
                           phi_gnd_deg: float, n: int) -> float:
    """独立重算谐振恒等式残差 4πh/λ0−φ_PRS−φ_GND−2πN（rad；不经模块函数）。"""
    lam0 = C0 / (f0_ghz * 1e9)
    return 4.0 * math.pi * h_m / lam0 - math.radians(phi_prs_deg) - math.radians(phi_gnd_deg) - 2.0 * math.pi * n


@pytest.mark.parametrize("phi_prs,phi_gnd", [(0.0, 0.0), (30.0, 180.0), (-90.0, 45.0), (170.0, -170.0), (-175.0, 175.0)])
def test_resonance_roundtrip_identity_rel_1e_12(phi_prs: float, phi_gnd: float) -> None:
    """闭式解 h 回代谐振恒等式（规格判据 1，rel 1e-12；N=0 用 abs 1e-12）。"""
    sols = fpa_antenna.resonance_heights(F0_GHZ, phi_prs, phi_gnd, n_solutions=5)
    assert len(sols) == 5
    for sol in sols:
        residual = _identity_residual_deg(sol.h_m, F0_GHZ, phi_prs, phi_gnd, sol.n)
        tol = 1e-12 * max(1.0, abs(2.0 * math.pi * sol.n))
        assert abs(residual) <= tol


def test_resonance_zero_phase_half_wave_identity() -> None:
    """φ_PRS=φ_GND=0 → h=N·λ0/2 恒等式（规格判据 2；λ0/2 是 2 的幂除法逐位）。"""
    sols = fpa_antenna.resonance_heights(F0_GHZ, 0.0, 0.0, n_solutions=4)
    for k, sol in enumerate(sols):
        assert sol.n == k + 1  # N=0 给 h=0 已排除，最小解从 N=1 起
        assert sol.h_m == pytest.approx((k + 1) * LAM0_M / 2.0, rel=1e-15)


def test_resonance_quarter_wave_pec_and_ji_half_wave() -> None:
    """Trentini 经典口径：PEC 地板 φ_GND=180°、φ_PRS=0° → h=λ0/4（N=0）；
    φ_PRS=180° → h=λ0/2（N=0，Ji 2016 设计口径，见文献锚测试）。"""
    sols = fpa_antenna.resonance_heights(F0_GHZ, 0.0, 180.0, n_solutions=1)
    assert sols[0].n == 0
    assert sols[0].h_m == pytest.approx(LAM0_M / 4.0, rel=1e-15)
    sols2 = fpa_antenna.resonance_heights(F0_GHZ, 180.0, 180.0, n_solutions=1)
    assert sols2[0].n == 0
    assert sols2[0].h_m == pytest.approx(LAM0_M / 2.0, rel=1e-15)


def test_resonance_heights_list_monotone_consecutive() -> None:
    """解列表：N 连续升序、h 严格增、全正；n_solutions 计数足额。"""
    sols = fpa_antenna.resonance_heights(F0_GHZ, -60.0, 180.0, n_solutions=7)
    assert len(sols) == 7
    ns = [s.n for s in sols]
    hs = [s.h_m for s in sols]
    assert ns == list(range(ns[0], ns[0] + 7))
    assert all(h > 0.0 for h in hs)
    assert all(b - a > 0.0 for a, b in pairwise(hs))
    # 相邻阶间距恰 λ0/2（相位和固定，N→N+1 差一整半波）
    half = LAM0_M / 2.0
    assert all(b - a == pytest.approx(half, rel=1e-12) for a, b in pairwise(hs))


def test_resonance_heights_h_max_filter() -> None:
    """h_max_m 过滤：解全 ≤ 上界；过紧上界如实返回空列表（不造解）。"""
    sols = fpa_antenna.resonance_heights(F0_GHZ, 0.0, 180.0, n_solutions=10, h_max_m=0.05)
    assert sols and all(s.h_m <= 0.05 for s in sols)
    empty = fpa_antenna.resonance_heights(F0_GHZ, 0.0, 180.0, n_solutions=10, h_max_m=1e-6)
    assert empty == []


def test_resonance_heights_input_guards() -> None:
    """边界：f0<=0/NaN 相位/bool/n_solutions 非法 → ValueError。"""
    with pytest.raises(ValueError):
        fpa_antenna.resonance_heights(0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        fpa_antenna.resonance_heights(-1.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        fpa_antenna.resonance_heights(F0_GHZ, float("nan"), 0.0)
    with pytest.raises(ValueError):
        fpa_antenna.resonance_heights(F0_GHZ, 0.0, float("inf"))
    with pytest.raises(ValueError):
        fpa_antenna.resonance_heights(True, 0.0, 0.0)  # bool 显式拒收（df7+⑯）
    with pytest.raises(ValueError):
        fpa_antenna.resonance_heights(F0_GHZ, 0.0, 0.0, n_solutions=0)
    with pytest.raises(ValueError):
        fpa_antenna.resonance_heights(F0_GHZ, 0.0, 0.0, n_solutions=True)


# ─── 2. 反解 φ_PRS ────────────────────────────────────────────────────────────


def test_required_prs_phase_roundtrip_identity() -> None:
    """反解→回代：resonance_heights 含 h_m 解（rel 1e-12），恒等式逐点成立。"""
    for h_m in (0.005, LAM0_M / 2.0, 0.12):
        req = fpa_antenna.required_prs_phase(F0_GHZ, h_m, 180.0)
        assert -180.0 < req["phi_prs_deg"] <= 180.0
        residual = _identity_residual_deg(h_m, F0_GHZ, float(req["phi_prs_deg"]), 180.0, int(req["n"]))
        assert abs(residual) <= 1e-12 * max(1.0, abs(2.0 * math.pi * req["n"]))
        sols = fpa_antenna.resonance_heights(F0_GHZ, float(req["phi_prs_deg"]), 180.0, n_solutions=16)
        h_recovered = min(s.h_m for s in sols)
        # 解族不变量：包裹平移吸收 n·λ0/2 后族整体下移，最小解恒落 (0, λ0/2]；
        # 给定 h_m 本身必须仍在族内（rel 1e-12，真正回代判据）
        assert 0.0 < h_recovered <= LAM0_M / 2.0 * (1.0 + 1e-12)
        assert any(s.h_m == pytest.approx(h_m, rel=1e-12) for s in sols)


def test_required_prs_phase_wrapped_range_and_order() -> None:
    """包裹域 (-180,180]；h 跨多个半波时 N 随 h 增（阶数一致性）。"""
    phases = []
    ns = []
    for k in range(1, 6):
        req = fpa_antenna.required_prs_phase(F0_GHZ, k * LAM0_M / 2.0, 0.0)
        phases.append(float(req["phi_prs_deg"]))
        ns.append(int(req["n"]))
    assert all(-180.0 < p <= 180.0 for p in phases)
    assert ns == sorted(ns) and len(set(ns)) == 5
    # h=λ0/2、φ_GND=0：total=2π → N=1、φ_PRS=0（恰整阶）
    assert ns[0] == 1 and phases[0] == pytest.approx(0.0, abs=1e-9)


def test_required_prs_phase_input_guards() -> None:
    """边界：h<=0/f0<=0/NaN → ValueError。"""
    with pytest.raises(ValueError):
        fpa_antenna.required_prs_phase(F0_GHZ, 0.0, 180.0)
    with pytest.raises(ValueError):
        fpa_antenna.required_prs_phase(F0_GHZ, -0.01, 180.0)
    with pytest.raises(ValueError):
        fpa_antenna.required_prs_phase(0.0, 0.027, 180.0)
    with pytest.raises(ValueError):
        fpa_antenna.required_prs_phase(F0_GHZ, float("nan"), 180.0)


# ─── 3. 增益口径（Ji 2016 Eq.(2)）────────────────────────────────────────────


def test_directivity_degenerate_identities_exact() -> None:
    """R=0 → D=1.0（0 dB）逐位（log10(1)=0）；R→1⁻ → D→∞（≥1e15 判发散向）。"""
    assert fpa_antenna.directivity(0.0) == 1.0
    assert fpa_antenna.directivity_db(0.0) == 0.0
    huge = fpa_antenna.directivity(1.0 - 1e-16)
    assert huge > 1e15


def test_directivity_r09_nineteen_double_path() -> None:
    """R=0.9 → D=19（12.79 dB）：路径 A=模块式、路径 B=2/(1−R)−1 独立代数（rel 1e-9）。"""
    d = fpa_antenna.directivity(0.9)
    assert d == pytest.approx(D_R09, rel=1e-9)
    assert d == pytest.approx(2.0 / (1.0 - 0.9) - 1.0, rel=1e-9)
    assert fpa_antenna.directivity_db(0.9) == pytest.approx(D_R09_DB, rel=1e-9)


def test_directivity_monotone_scan_conservation() -> None:
    """扫描面：R 严格增 → D 严格增（单调性守恒）；向量化与标量逐位一致。"""
    r = np.linspace(0.0, 0.99, 200)
    d = fpa_antenna.directivity_scan(r)
    assert bool(np.all(np.diff(d) > 0.0))
    assert np.array_equal(d, np.array([fpa_antenna.directivity(float(x)) for x in r]))
    # R=0 端点恰 1.0
    assert d[0] == 1.0


def test_directivity_input_guards() -> None:
    """边界：R<0/R=1/R>1/NaN/数组含越界 → ValueError。"""
    for bad in (-0.1, 1.0, 1.5, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            fpa_antenna.directivity(bad)
    with pytest.raises(ValueError):
        fpa_antenna.directivity_scan(np.array([0.2, 0.99, 1.0]))
    with pytest.raises(ValueError):
        fpa_antenna.directivity_scan(np.array([0.2, np.nan]))
    with pytest.raises(ValueError):
        fpa_antenna.directivity_db(1.0)


# ─── 4. Q/带宽面（能量衰减内核 vs Airy 标准具双径）───────────────────────────


def _airy_fwhm_q(f0_ghz: float, h_m: float, r: float) -> float:
    """独立裁判径：Airy 标准具 FWHM Q（测试内推导，非模块代码）。

    非对称腔（R_PRS=R、R_GND=1）：系数精细度 F_c=4√R/(1−√R)²，HWHM（往返
    相位）δ_h=2·arcsin((1−√R)/(2·R^(1/4)))，Q=(2πh/λ0)/δ_h。
    """
    lam0 = C0 / (f0_ghz * 1e9)
    sq = math.sqrt(r)
    quarter = r**0.25
    delta_h = 2.0 * math.asin((1.0 - sq) / (2.0 * quarter))
    return (2.0 * math.pi * h_m / lam0) / delta_h


def test_resonance_q_self_consistency_and_recycle() -> None:
    """Q 自洽：bw_frac×Q=1（rel 1e-12）；Q 与 f-直接手算路径 rel 1e-12。"""
    h = LAM0_M / 2.0
    out = fpa_antenna.resonance_q(F0_GHZ, h, 0.9)
    q = float(out["q"])
    assert float(out["bandwidth_frac"]) * q == pytest.approx(1.0, rel=1e-12)
    # 独立代数路径：Q=4πhf/c/(−lnR)（频率直接进式，不经 lam0）
    q_alt = 4.0 * math.pi * h * (F0_GHZ * 1e9) / C0 / (-math.log(0.9))
    assert q == pytest.approx(q_alt, rel=1e-12)
    # 谐振阶归一：h=λ0/2 时 roundtrip_orders=1、Q=2π/(−lnR)
    assert float(out["roundtrip_orders"]) == pytest.approx(1.0, rel=1e-15)
    assert q == pytest.approx(2.0 * math.pi / (-math.log(0.9)), rel=1e-12)


@pytest.mark.parametrize("r", [0.5, 0.9, 0.99])
def test_resonance_q_vs_airy_fwhm_double_path(r: float) -> None:
    """双径裁判：能量衰减 Q vs Airy FWHM Q，rel ≤1.5%（R=0.5 手算互差 1.05%）。"""
    h = LAM0_M / 2.0
    q_pole = float(fpa_antenna.resonance_q(F0_GHZ, h, r)["q"])
    q_airy = _airy_fwhm_q(F0_GHZ, h, r)
    assert q_pole == pytest.approx(q_airy, rel=0.015)


def test_resonance_q_monotone_in_r_and_h() -> None:
    """Q 随 R 单调增（镜越强腔越窄）、随 h 单调增（高阶更窄）；带宽=1/Q 随之。"""
    h = LAM0_M / 2.0
    qs = [float(fpa_antenna.resonance_q(F0_GHZ, h, r)["q"]) for r in (0.1, 0.5, 0.9, 0.99)]
    assert all(b > a for a, b in pairwise(qs))
    qs_h = [float(fpa_antenna.resonance_q(F0_GHZ, hh, 0.9)["q"]) for hh in (0.01, 0.027, 0.05)]
    assert all(b > a for a, b in pairwise(qs_h))
    # 极限向：R→1⁻ Q→∞（>1e6）、R→0⁺ Q→0（<1）
    assert float(fpa_antenna.resonance_q(F0_GHZ, h, 1.0 - 1e-6)["q"]) > 1e6
    assert float(fpa_antenna.resonance_q(F0_GHZ, h, 1e-3)["q"]) < 1.0


def test_resonance_q_input_guards() -> None:
    """边界：R=0/R=1/R>1/h<=0/f0<=0 → ValueError（Q 面拒绝 R=0：无腔无谐振）。"""
    h = LAM0_M / 2.0
    for bad_r in (0.0, 1.0, 1.1, -0.5, float("nan"), True):
        with pytest.raises(ValueError):
            fpa_antenna.resonance_q(F0_GHZ, h, bad_r)
    with pytest.raises(ValueError):
        fpa_antenna.resonance_q(F0_GHZ, 0.0, 0.9)
    with pytest.raises(ValueError):
        fpa_antenna.resonance_q(-1.0, h, 0.9)
    # UNKNOWN 登记随返回体携带（诚实边界不靠口头）
    out = fpa_antenna.resonance_q(F0_GHZ, h, 0.9)
    assert out["feed_loading"] == "unknown_feed_loading_not_included"


# ─── 5. 一次成点 design_point ─────────────────────────────────────────────────


def test_design_point_branches_consistent() -> None:
    """phi 分支与 h 分支互为反函数：h/φ_PRS/n/D/Q 全一致（rel 1e-12）。"""
    by_phi = fpa_antenna.design_point(F0_GHZ, 0.9, 180.0, phi_prs_deg=150.0, n=1)
    by_h = fpa_antenna.design_point(F0_GHZ, 0.9, 180.0, h_m=float(by_phi["h_m"]))
    assert by_h["phi_prs_deg"] == pytest.approx(150.0, rel=1e-12)
    assert by_h["n"] == by_phi["n"]
    assert by_h["h_m"] == pytest.approx(float(by_phi["h_m"]), rel=1e-12)
    assert by_h["directivity"] == by_phi["directivity"]
    assert by_h["q"] == pytest.approx(float(by_phi["q"]), rel=1e-12)
    # D 与 Q 与单函数一致（同源不串味）
    assert by_phi["directivity"] == pytest.approx(fpa_antenna.directivity(0.9), rel=1e-15)
    assert by_phi["q"] == pytest.approx(float(fpa_antenna.resonance_q(F0_GHZ, float(by_phi["h_m"]), 0.9)["q"]), rel=1e-15)


def test_design_point_requires_exactly_one_and_guards() -> None:
    """恰给其一（is None 判缺失，#364④）；负阶 h<=0 → ValueError。"""
    with pytest.raises(ValueError):
        fpa_antenna.design_point(F0_GHZ, 0.9, 180.0)
    with pytest.raises(ValueError):
        fpa_antenna.design_point(F0_GHZ, 0.9, 180.0, phi_prs_deg=0.0, h_m=0.027)
    with pytest.raises(ValueError):
        fpa_antenna.design_point(F0_GHZ, 0.9, 180.0, phi_prs_deg=0.0, n=-5)  # 该阶 h<0
    with pytest.raises(ValueError):
        fpa_antenna.design_point(F0_GHZ, 1.0, 180.0, phi_prs_deg=0.0)  # R=1 拒收


def test_design_point_to_dict_json_roundtrip() -> None:
    """dataclass to_dict + design_point 返回体 JSON 可序列化（float/int/str）。"""
    sol = fpa_antenna.resonance_heights(F0_GHZ, 0.0, 180.0, n_solutions=1)[0]
    d = sol.to_dict()
    assert set(d) == {"n", "h_m", "lam0_m", "f0_ghz", "phi_prs_deg", "phi_gnd_deg"}
    assert isinstance(d["n"], int) and isinstance(d["h_m"], float)
    json.dumps(d)  # 不抛即可序列化
    design = fpa_antenna.design_point(F0_GHZ, 0.5, 180.0, phi_prs_deg=0.0)
    json.dumps(design)

# ─── 6. 文献锚（Ji 2016 PIERL 58，±5% 带）────────────────────────────────────


def test_literature_anchor_ji2016_pierl58() -> None:
    """文献锚（预声明 ±5%）：Ji 2016 Eq.(1) 设计值 Lr=27 mm @ 5.5 GHz、PEC 地板。

    原文（开放期刊，PDF 已核）：Eq.(1) Lr=(φ/π+1)λ0/4+N·λ0/2 与本模块约定式
    解集同族；φ_PRS 论文未印——双向回收：
    (a) h=λ0/2（φ_PRS=180°）= 27.254 mm vs 论文 27 mm → 偏差 0.93%；
    (b) h=27 mm 反解 φ_PRS → 176.7° vs 均匀金属 PRS 渐近 180° → 偏差 1.8%。
    带（5.35–5.76 GHz）缘偏差 7% 超带——锚只在带心 5.5 GHz 判（如实登记）。
    """
    sols = fpa_antenna.resonance_heights(F0_GHZ, 180.0, 180.0, n_solutions=1)
    h_half_wave_m = sols[0].h_m
    assert abs(h_half_wave_m - JI_H_M) / JI_H_M <= 0.05
    req = fpa_antenna.required_prs_phase(F0_GHZ, JI_H_M, 180.0)
    assert abs(float(req["phi_prs_deg"]) - 180.0) / 180.0 <= 0.05
    # 反解路径独立复核（f-直接手算路径，rel 1e-12）
    total = 4.0 * math.pi * JI_H_M * (F0_GHZ * 1e9) / C0 - math.pi
    assert float(req["phi_prs_deg"]) == pytest.approx(math.degrees(total), rel=1e-12)


# ─── 7. service 薄层（JSON 信封 ok=False 不抛）───────────────────────────────


def test_service_fpa_design_ok_and_error_envelope() -> None:
    """正常路径 ok=True；非法入参 ok=False errors（不抛）；缺参点名进 errors。"""
    out = fpa_antenna_service.fpa_design(
        {"f0_ghz": F0_GHZ, "r": 0.9, "phi_gnd_deg": 180.0, "phi_prs_deg": 150.0, "n": 1}
    )
    assert out["ok"] is True
    assert out["design"]["h_m"] > 0.0
    assert out["design"]["directivity"] == pytest.approx(D_R09, rel=1e-9)
    bad = fpa_antenna_service.fpa_design({"f0_ghz": F0_GHZ, "r": 1.0, "phi_gnd_deg": 180.0})
    assert bad["ok"] is False and bad["errors"]
    missing = fpa_antenna_service.fpa_design({"f0_ghz": F0_GHZ, "r": 0.9})
    assert missing["ok"] is False and any("phi_gnd_deg" in e for e in missing["errors"])
    not_dict = fpa_antenna_service.fpa_design([1, 2, 3])  # type: ignore[arg-type]
    assert not_dict["ok"] is False


def test_service_heights_and_scan_envelopes() -> None:
    """heights/scan 两入口：ok=True 数组面；空/非法 ok=False；JSON 可序列化。"""
    hs = fpa_antenna_service.fpa_resonance_heights(
        {"f0_ghz": F0_GHZ, "phi_prs_deg": 0.0, "phi_gnd_deg": 180.0, "n_solutions": 3}
    )
    assert hs["ok"] is True and len(hs["solutions"]) == 3
    assert hs["solutions"][0]["h_m"] == pytest.approx(LAM0_M / 4.0, rel=1e-15)
    json.dumps(hs)
    scan = fpa_antenna_service.fpa_directivity_scan({"r_values": [0.0, 0.5, 0.9]})
    assert scan["ok"] is True
    assert scan["d"][-1] == pytest.approx(D_R09, rel=1e-9)
    assert scan["d_db"][-1] == pytest.approx(D_R09_DB, rel=1e-9)
    bad = fpa_antenna_service.fpa_directivity_scan({"r_values": [0.5, 1.0]})
    assert bad["ok"] is False and bad["errors"]
    json.dumps(scan)
