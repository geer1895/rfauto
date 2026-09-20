"""C9 传输线族 II：共面带 CPS 模板 —— 闭式锚 + 注册四件套 + 离线几何审计。

闭式出处（docs/rf_template_references.md §11.1）：Wadell (1991) p.83
均匀线 Z0=120π·K(k1)/K'(k1)/√εeff（MathWorks RF PCB 官方例 MoM 对拍）+
Gupta/Ghione 部分电容 tanh 板映射（同 _cpwg_ri 框架）+ **FD 定标有效厚度
γ(εr)=1+0.9014·εr^−0.6361**（2026-09-18 定标：裸映射对无地薄基板
系统性偏低 −3~−12%，定标后 ≤1.4%；裁判=core/quasistatic_fd.py，其自身先过
HJ 微带/Cohn/半空间极限基准，见 test_quasistatic_fd.py）。#118 判据全部取
独立来源：Babinet/Booker 对偶恒等式 Z_CPS·Z_CPW=η0²/4（skrf media.CPW
为互补方独立实现）、解析极限、scipy 椭圆积分直算、FD 裁判现算。

离线几何审计（#212）：render → exec 几何段 → CSXCAD 实测原语/网格/端口，
零仿真。真机 openEMS 冒烟后置（scripts/smoke_cps_anchor.py）。
"""

from __future__ import annotations

import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.calculators import (
    CALCULATOR_REGISTRY,
    _cps_ri,
    _kk_ratio,
    cps_analysis,
    cps_synthesis,
)

ER, H = 3.66, 0.508
_EPS0 = 8.8541878128e-12
_C0 = 299792458.0
_ETA0 = 1.0 / (_EPS0 * _C0)   # 精确真空波阻抗 376.730Ω（"120π" 为旧 SI 近似）


# ─── 闭式锚（#118：独立来源）──────────────────────────────────────────────────

def test_cps_air_matches_wadell_120pi_form():
    """均匀空气 CPS：Z0 = η0·K(k1)/K'(k1)，k1=gap/(gap+2w)（Wadell 3.4.6.1，
    scipy 椭圆积分直算独立复现；εeff=1）。"""
    from scipy.special import ellipk

    for w, gap in ((0.5, 0.5), (1.0, 0.4), (0.3, 1.2)):
        k1 = (gap / 2) / (gap / 2 + w)
        r1 = float(ellipk(k1 * k1)) / float(ellipk(1.0 - k1 * k1))
        eps_eff, z0 = _cps_ri(w, gap, 1e6, 1.0)     # h 巨大 + εr=1 = 均匀空气
        assert eps_eff == pytest.approx(1.0, abs=1e-9)
        assert z0 == pytest.approx(_ETA0 * r1, rel=1e-9)
    # MathWorks 官方例几何（a=0.5 内缘距、b=2.0 外缘距 → gap=0.5、w=0.75）：
    # 120π·K(0.25)/K'(0.25) 口径（其 MoM 求解器对拍到几 Ω 网格差）
    z_mw = _cps_ri(0.75, 0.5, 1e6, 1.0)[1]
    assert z_mw == pytest.approx(_ETA0 * _kk_ratio(0.25), rel=1e-9)
    assert 200.0 < z_mw < 225.0     # MathWorks MoM 报 206.45（网格差几 Ω）


def test_cps_cpw_babinet_duality_against_skrf():
    """互补对偶（Booker 扩展 Babinet）：CPS(w,gap) 与 CPW(center=gap, slot=w)
    共用模量 k，Z_CPS·Z_CPW·√(εeff1·εeff2) = η0²/4。互补方用 skrf media.CPW
    独立实现（无限厚基板极限 h=10m，两者 εeff 同为 (1+εr)/2）。"""
    skrf = pytest.importorskip("skrf")

    f = skrf.Frequency(2.5, 2.5, 1, unit="GHz")
    for w, gap in ((0.5, 0.5), (1.0, 0.4), (0.3, 1.2)):
        eps_cps, z_cps = _cps_ri(w, gap, 1e6, ER)
        cpw = skrf.media.CPW(frequency=f, w=gap * 1e-3, s=w * 1e-3, ep_r=ER,
                             h=10.0, t=None, rho=None, tand=0.0,
                             diel="frequencyinvariant")
        z_cpw = float(np.real(np.atleast_1d(cpw.z0)[0]))
        eps_cpw = float(np.real(np.atleast_1d(cpw.ep_reff)[0]))
        assert eps_cps == pytest.approx((1 + ER) / 2, rel=1e-6)
        assert eps_cpw == pytest.approx((1 + ER) / 2, rel=1e-6)
        product = z_cps * z_cpw * math.sqrt(eps_cps * eps_cpw)
        assert product / (_ETA0 ** 2 / 4) == pytest.approx(1.0, rel=2e-4)


def test_cps_substrate_limits():
    """h→∞ εeff→(1+εr)/2（半空间口径）；h→0 εeff→1；εeff∈(1, εr) 且随 h 单调。"""
    assert _cps_ri(0.5, 0.5, 1e6, ER)[0] == pytest.approx((1 + ER) / 2, rel=1e-9)
    assert _cps_ri(0.5, 0.5, 1e-6, ER)[0] == pytest.approx(1.0, abs=1e-9)
    hs = (0.05, 0.15, 0.3, 0.508, 1.0, 2.0, 5.0, 20.0)
    eps = [_cps_ri(0.5, 0.5, h, ER)[0] for h in hs]
    assert all(1.0 < e < ER for e in eps)
    assert all(a < b for a, b in pairwise(eps)), eps


def test_cps_gap_limits_and_w_monotonic():
    """gap→0 Z0→0、gap→∞ Z0→∞；Z0 随 w 严格单调递减（k1=gap/(gap+2w)）。"""
    assert _cps_ri(0.5, 1e-5, H, ER)[1] < 40.0
    assert _cps_ri(0.5, 1e4, H, ER)[1] > 1000.0
    ws = (0.05, 0.1, 0.3, 0.5, 1.0, 2.0, 5.0, 10.0)
    zs = [_cps_ri(w, 0.5, H, ER)[1] for w in ws]
    assert all(a > b for a, b in pairwise(zs)), zs


def test_cps_fd_referee_points_pinned():
    """2D FD Laplace 独立裁判点（§11.1，w=s=0.5 εr=3.66，core/quasistatic_fd.py
    Richardson 值，2026-09-18 定标轮实测）：定标闭式 εeff 与 FD 差 ≤2.5%
    （h=0.15 为 a/h=1.67 定标域边缘 −2.0%，h≥0.3 ≤1.2%；裸映射曾 −3~−9.5%）。
    旧 refs 表（1.4696/1.9665/2.2260/2.3592/2.3916）出自侧墙过近的临时 FD，
    其 h=8mm 极限自偏 +2.8% 即证据，已撤。"""
    fd = {0.15: 1.5504, 0.3: 1.8359, 0.508: 2.0450, 1.0: 2.2222, 2.5: 2.3082,
          8.0: 2.3280}
    assert fd[8.0] == pytest.approx((1 + ER) / 2, rel=1e-3)   # 裁判过精确极限
    for h, eps_fd in fd.items():
        eps_cl = _cps_ri(0.5, 0.5, h, ER)[0]
        assert abs(eps_fd / eps_cl - 1.0) <= 0.025, (h, eps_fd, eps_cl)
        if h >= 0.3:
            assert abs(eps_fd / eps_cl - 1.0) <= 0.012, (h, eps_fd, eps_cl)


def test_cps_calibration_matches_live_fd_referee():
    """定标闭式 vs 裁判现算（#118，同一会话零常数复用）：标称几何 ≤1%、
    高 εr（6.15）与薄板（h=0.3）≤2%。裁判 richardson=False 单档 d0=h/10 快速档
    （单档相对 Richardson 偏 <0.3%，测试预算 <1s）。"""
    from rfauto.core.quasistatic_fd import cps_quasistatic

    cases = ((2.95, 0.5, H, ER, 0.01), (1.27, 0.508, H, 6.15, 0.02),
             (1.0, 0.4, 0.3, ER, 0.02))
    for w, gap, h, er, tol in cases:
        fd = cps_quasistatic(w, gap, h, er, d0_mm=h / 10, richardson=False).eps_eff
        cl = _cps_ri(w, gap, h, er)[0]
        assert abs(cl / fd - 1.0) <= tol, (w, gap, h, er, cl, fd)


def test_cps_effective_thickness_factor_contract():
    """γ(εr)=1+C·εr^−P：εr=3.66 → 1.395；单调递减、εr→∞ → 1；εr<1 拒绝。"""
    from rfauto.core.calculators import (
        CPS_H_EFF_GAMMA_C,
        CPS_H_EFF_GAMMA_P,
        cps_effective_thickness_factor,
    )

    assert cps_effective_thickness_factor(ER) == pytest.approx(1.3949, abs=1e-3)
    assert cps_effective_thickness_factor(ER) == pytest.approx(
        1 + CPS_H_EFF_GAMMA_C * ER ** (-CPS_H_EFF_GAMMA_P))
    gs = [cps_effective_thickness_factor(e) for e in (1.5, 2.2, 3.66, 6.15, 10.2, 1e6)]
    assert all(a > b for a, b in pairwise(gs))
    assert gs[-1] == pytest.approx(1.0, abs=1e-3)
    with pytest.raises(ValueError):
        cps_effective_thickness_factor(0.9)


def test_cps_corner_domain_boundary_pinned():
    """适用域边界钉（#122 如实不硬凑）：定标域（a/h≲1 且
    b/h≲3）之外 γ(εr) 单参数修正数据不支持（逐点最优 γ 增强比是 (a/h,b/h)
    二维曲面），闭式在宽带缝角落**低估**——FD 单档裁判（d0=min(H/20,a/4)，
    与定标族扫描同档）实测：a/h=2,b/h=6,εr=10.2 → −2.8%；a/h=3,b/h=6,
    εr=12.9 → −5.7%（旧 refs 注记 −2~−4% 偏轻，本表为准）。钉住方向与量级，
    防静默漂移；域内精度由 test_cps_fd_referee_points_pinned/INFO 门守。"""
    from rfauto.core.quasistatic_fd import cps_quasistatic

    h = 0.508
    for ah, bh, er, fd_expect, dev_expect in (
            (2.0, 6.0, 10.2, 2.4692, -0.028),
            (3.0, 6.0, 12.9, 2.7094, -0.057)):
        a, b = ah * h, bh * h
        w, gap = b - a, 2 * a
        fd = cps_quasistatic(w, gap, h, er, d0_mm=min(h / 20, a / 4),
                             richardson=False).eps_eff
        assert fd == pytest.approx(fd_expect, abs=0.004), (ah, bh, er, fd)
        cl = _cps_ri(w, gap, h, er)[0]
        dev = cl / fd - 1.0
        assert dev == pytest.approx(dev_expect, abs=0.008), (ah, bh, er, dev)
        assert dev < 0          # 方向钉：角落低估（不是过拟合偶然）


def test_cps_domain_errors_explicit():
    with pytest.raises(ValueError):
        _cps_ri(0.0, 0.5, H, ER)
    with pytest.raises(ValueError):
        _cps_ri(0.5, 0.5, 0.0, ER)
    with pytest.raises(ValueError):
        _cps_ri(0.5, 0.5, H, 0.5)


# ─── 注册键 / 综合回代 ────────────────────────────────────────────────────────

def test_cps_registry_keys():
    names = set(CALCULATOR_REGISTRY.names())
    assert {"cps_analysis", "cps_synthesis"} <= names


def test_cps_synthesis_roundtrip_and_reachability():
    out = cps_synthesis(120.0, 0.5, 2.5, ER, H)
    assert out["z0_actual_ohm"] == pytest.approx(120.0, abs=0.01)
    back = cps_analysis(out["w_mm"], 0.5, ER, H, 2.5)
    assert back["z0_ohm"] == pytest.approx(120.0, abs=0.05)
    assert back["eps_eff"] == pytest.approx(out["eps_eff"], abs=1e-3)
    # 印制 CPS 天然高阻：50Ω @gap=0.5 落在可达域之下（定标后下限 ≈94Ω）→
    # 显式报错（不返 NaN）
    with pytest.raises(ValueError, match="超出可达范围"):
        cps_synthesis(50.0, 0.5, 2.5, ER, H)


def test_cps_nominal_is_kernel_synthesized():
    """TEMPLATE_NOMINAL 标称几何 w=2.95/gap=0.5 保持（真机配对 #158：pt1 与复跑同
    几何，docs meta 同源）；定标后该几何内核精算 Z0=116.17Ω/εeff=1.6765（旧口径
    120Ω/1.5712 为裸映射值）——反解回代到 2.95 证明标称仍是内核自洽点，非手写。"""
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    nom = TEMPLATE_NOMINAL["cps"]
    eps_eff, z0 = _cps_ri(nom["w_mm"], nom["gap_mm"], H, ER)
    assert z0 == pytest.approx(116.17, abs=0.05)
    assert eps_eff == pytest.approx(1.6765, abs=1e-3)
    assert abs(eps_eff / 1.667 - 1.0) <= 0.01        # FD 裁判 Richardson 真值
    syn = cps_synthesis(z0, nom["gap_mm"], 2.5, ER, H)
    assert nom["w_mm"] == pytest.approx(syn["w_mm"], abs=5e-4)
    # 120Ω 设计档在定标口径下的内核解（synthesize_cps_model 缺省目标）
    assert cps_synthesis(120.0, nom["gap_mm"], 2.5, ER, H)["w_mm"] == pytest.approx(
        2.4863, abs=5e-4)


def test_synthesize_cps_model_contract():
    from rfauto.core.synthesis import synthesize_cps_model

    res = synthesize_cps_model()
    assert res.model == "cps"
    assert set(res.params) >= {"w_mm", "gap_mm", "line_len_mm"}
    assert res.recipe_draft["model"] == "cps"
    # 缺省 120Ω 档 = cps_synthesis 内核解（定标后 2.4863，旧裸映射 2.95）
    assert res.params["w_mm"] == pytest.approx(
        cps_synthesis(120.0, 0.5, 2.5, ER, H)["w_mm"], abs=5e-4)
    with pytest.raises(ValueError):
        synthesize_cps_model(z0_ohm=50.0, gap_mm=0.5)


# ─── 注册四件套 ──────────────────────────────────────────────────────────────

def test_cps_registration_quartet():
    from rfauto.adapters import openems_templates as ot
    from rfauto.models.template_specs import TEMPLATE_SPECS

    assert "cps" in ot.TEMPLATE_META and "cps" in ot.TEMPLATE_NOMINAL
    assert ot.TEMPLATE_META["cps"]["params"] == ["w_mm", "gap_mm", "line_len_mm"]
    assert ot._TEMPLATE_PORT_AXES["cps"] == ()          # 集总端口在域内 → 全 MUR
    assert ot._TEMPLATE_RADIATOR["cps"] is False
    assert (REPO / "docs" / "templates" / "cps" / "meta.yaml").exists()
    spec = TEMPLATE_SPECS.get("cps")
    assert spec.physics_roles == {"w_mm": "line_width_mm",
                                  "gap_mm": "gap_width_mm",
                                  "line_len_mm": "line_length_mm"}
    assert callable(TEMPLATE_SPECS.component("cps", "fake_model"))
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

    assert "cps" in EXPECTED_TEMPLATES


# ─── 离线几何审计（#212）─────────────────────────────────────────────────────

def _load(params=None):
    from tests.unit import _geometry_audit_helpers as gh

    return gh, gh.load_geometry("cps", params)


def test_cps_render_ports_bc_and_reference_impedance():
    """LumpedPort×2 跨缝差分（R=闭式 Z0）、CalcPort 参考阻抗=R、六面 MUR、
    域向下延 AIR_TOP（无地）；port_beta.csv 落盘端口元 y 坐标/实测差分线长
    （同 SSL beta 块先例；LumpedPort 无 β 无 beta 列）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, render_script

    nom = dict(TEMPLATE_NOMINAL["cps"])
    txt = render_script("cps", nom, (2.25, 2.75), mesh_resolution_mm=0.4)
    z0 = _cps_ri(nom["w_mm"], nom["gap_mm"], H, ER)[1]
    assert f"R_PORT = {round(z0, 4)!r}" in txt
    assert f"ref_impedance={round(z0, 4)!r}" in txt
    assert 'SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "MUR", "MUR"])' in txt
    assert txt.count("FDTD.AddLumpedPort(") == 2
    assert 'np.linspace(-AIR_TOP, 0, 5)' in txt
    # 端口几何落盘（新契约）：无 β 列（LumpedPort 无 beta），有端口元 y/实测线长
    assert "port_beta.csv" in txt
    assert '"freq_hz", "port_y1_m", "port_y2_m", "plane_dist_m"' in txt
    assert "beta_rad_per_m" not in txt.split("port_beta.csv")[1]
    # 其它模板参考阻抗文本逐字节不变（"50"）
    txt_ml = render_script("mline", {}, (2.25, 2.75), mesh_resolution_mm=0.4)
    assert "_port1.CalcPort(SIM_PATH, f, ref_impedance=50)" in txt_ml


def test_cps_port_plane_dist_offline_exec():
    """#212 离线 exec 实测：beta 块按终网格落盘的实测差分线长（端口元=E 场
    节点 cell 中心）与标称 L 差 ≤1 格（±1 BASE → εeff ±5.7% 口径地板的实测
    上界），且逐位等于测试侧独立重算（searchsorted 同口径）。"""
    import builtins
    import csv
    import io

    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, render_script
    from tests.unit import _geometry_audit_helpers as gh

    text = render_script("cps", dict(TEMPLATE_NOMINAL["cps"]), (2.25, 2.75),
                         mesh_resolution_mm=0.4)
    start = text.index("# cps 锚：端口元 y 坐标")
    end = text.index("_LOOP_DONE", start)
    block = text[start:end]
    scope, _ = gh.load_geometry("cps")

    captured: dict[str, str] = {}

    class _WriterFile:
        def __init__(self) -> None:
            self.buf = io.StringIO()

        def __enter__(self):
            return self.buf

        def __exit__(self, *exc):
            captured["csv"] = self.buf.getvalue()
            return False

    real_open = builtins.open
    builtins.open = lambda *a, **kw: _WriterFile()
    try:
        ns = dict(scope)
        ns["f"] = np.linspace(2.25e9, 2.75e9, 401)   # 脚本 FDTD.Run 后才定义
        exec(compile(block, "cps_beta_block", "exec"), ns)
    finally:
        builtins.open = real_open
    rows = list(csv.reader(io.StringIO(captured["csv"])))
    assert rows[0] == ["freq_hz", "port_y1_m", "port_y2_m", "plane_dist_m"]
    assert len(rows) == 402                                  # 401 频点
    y1, y2, dist = float(rows[1][1]), float(rows[1][2]), float(rows[1][3])
    # 测试侧独立重算（判读器消费口径同源验证）
    ys = gh.mesh_lines(scope, "y")
    j1 = int(np.clip(np.searchsorted(ys, scope["Y0"]) - 1, 0, ys.size - 2))
    j2 = int(np.clip(np.searchsorted(ys, scope["Y1"]) - 1, 0, ys.size - 2))
    assert y1 == pytest.approx(0.5 * (ys[j1] + ys[j1 + 1]), abs=1e-15)
    assert y2 == pytest.approx(0.5 * (ys[j2] + ys[j2 + 1]), abs=1e-15)
    assert dist == pytest.approx(y2 - y1, abs=1e-15)
    # 落格守卫：端口元节点偏离名义端口面 ≤1 格（BASE=0.4mm 审计档）
    base = 0.4e-3
    assert abs(y1 - float(scope["Y0"])) <= base + 1e-12
    assert abs(y2 - float(scope["Y1"])) <= base + 1e-12
    assert abs(dist - float(scope["Y1"] - scope["Y0"])) <= 2 * base + 1e-12


def test_cps_geometry_primitives_and_mesh():
    gh, (scope, prims) = _load()
    metal = [p for p in prims if p.kind == "Metal"]
    assert len(metal) == 2, "两条带"
    lo = sorted(p.lo[0] for p in metal)
    hi = sorted(p.hi[0] for p in metal)
    gap = 0.5e-3
    w = 2.95e-3
    assert lo[0] == pytest.approx(-gap / 2 - w, abs=1e-12)
    assert hi[0] == pytest.approx(-gap / 2, abs=1e-12)
    assert lo[1] == pytest.approx(gap / 2, abs=1e-12)
    assert hi[1] == pytest.approx(gap / 2 + w, abs=1e-12)
    assert all(p.lo[2] == pytest.approx(float(scope["H_SUB"])) for p in metal)
    # 基板 0..H_SUB，域 z 从 −AIR_TOP 起（无地，底 MUR）
    sub = [p for p in prims if p.kind == "Material"]
    assert len(sub) == 1 and sub[0].lo[2] == pytest.approx(0.0, abs=1e-12)
    z = gh.mesh_lines(scope, "z")
    assert z.min() == pytest.approx(-float(scope["AIR_TOP"]), abs=1e-9)
    assert gh.off_mesh_planes(prims, scope) == []
    # 四条带缘精确入网 + 缝内至少一条网格线（激励体积非零，#174/#198）
    x = gh.mesh_lines(scope, "x")
    for edge in (-gap / 2 - w, -gap / 2, gap / 2, gap / 2 + w):
        assert float(np.min(np.abs(x - edge))) <= 1e-9
    assert np.sum((x > -gap / 2 + 1e-9) & (x < gap / 2 - 1e-9)) >= 1


def test_cps_lumped_ports_bridge_the_gap_and_connect():
    gh, (scope, prims) = _load()
    ports = gh.port_objects(scope)
    assert set(ports) == {1, 2}
    for n, port in ports.items():
        start = np.asarray(port.start, dtype=float)
        stop = np.asarray(port.stop, dtype=float)
        assert not hasattr(port, "prop_ny"), "LumpedPort（非传输线端口）"
        assert abs(stop[0] - start[0]) == pytest.approx(0.5e-3, abs=1e-12)
        assert start[1] == pytest.approx((-1 if n == 1 else 1) * 20e-3, abs=1e-12)
    conductors, labels = gh.conductor_labels(prims)
    comps = {n: gh.containing_labels(gh.port_feed_point(p), conductors, labels)
             for n, p in ports.items()}
    assert comps[1] and comps[1] == comps[2], comps
    lumped = [p for p in prims if p.kind == "LumpedElement"]
    assert len(lumped) == 2, "两端各一 R 端接元件"


def test_cps_declared_params_drive_geometry():
    gh, _ = _load()
    changed = gh.geometry_changing_params("cps", ["w_mm", "gap_mm", "line_len_mm"])
    assert changed == {"w_mm", "gap_mm", "line_len_mm"}


# ─── fake 派发（#154 同参同义）───────────────────────────────────────────────

def test_fake_cps_dispatch_phase_slope_matches_closed_form():
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="cps", n_ports=2,
                     freq_ghz=(2.25, 2.75, 201), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"w_mm": "2.95mm", "gap_mm": "0.5mm",
                      "line_len_mm": "40mm"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    s = net.s
    phase = np.unwrap(np.angle(s[:, 1, 0]))
    slope = np.polyfit(net.f, phase, 1)[0]          # dφ/df = −2π√εeff L/c
    eps_engine = (-slope * _C0 / (2 * np.pi * 40e-3)) ** 2
    eps_ref = _cps_ri(2.95, 0.5, H, ER)[0]
    assert eps_engine == pytest.approx(eps_ref, rel=1e-3)
    assert np.max(np.abs(s[:, 0, 0])) < 1e-3       # 匹配端接口径 S11≈0
    # w 变 → εeff 变（数据工厂语义：参数驱动真实响应）
    ad.set_variables({"w_mm": "1.0mm", "gap_mm": "0.5mm", "line_len_mm": "40mm"})
    ad.solve("main_setup")
    s2 = ad.get_sparams().s
    assert not np.allclose(np.angle(s2[:, 1, 0]), np.angle(s[:, 1, 0]))
