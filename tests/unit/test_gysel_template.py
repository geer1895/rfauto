"""WP2.3 Gysel 功分器单测：理论核验锚/渲染/解析（理想六节环裁判）/综合/spec。

口径（#206 理论核验轮定版，对照 Microwaves101 "Gysel even/odd mode
analysis" 官方口径）：六节 λ/4 环——P1—70.7Ω 臂—P2/P3；P2/P3—50Ω
λ/4 隔离线—Δ1/Δ2（各接 50Ω 负载）；Δ1—50Ω λ/2 桥带（中点开路）—Δ2。
隔离机制：偶模臂变换 2Z0→Z0、桥带把负载支路开路化；奇模 P1/桥带中点
虚拟地、输出只见隔离线端接负载被吸收 → Γe=Γo=0 → S22=0 且 S32=0。
理论核验轮判废锚（skrf 数值证据，本文件固化）：
- 无桥带朴素直读拓扑 @f0：S21=-6.53dB、S11=-9.5dB、S32=-15.6dB（FAIL）；
- 合并单负载拓扑 @f0：S21=-9.03dB、S32=-2.5dB（FAIL）；
- 六节环 @f0：S21=S31=-3.01dB 同相、全匹配/隔离数值零（PASS）。
裁判=理想六节环 S 矩阵（f0 闭式），fake 与 skrf 装配互检（#205 纪律）。

拓扑重设计（2026-09-16 离线审计，本文件固化四候选对照）：矩形旧版
桥带继承 2·arm_len=36.324mm，对 50Ω λ/2=2·iso_len=35.500mm 有 +2.32%
二阶偏差（桥带 184.176°@f0），电路级把 @f0 S32/S11 封顶 -34.8dB——归因
主因（junction 台阶/双臂对称性为二阶）。候选：rect（矩形现状）/ trap
（真斜梯形）/ ljog（L-jog 等长折线）/ z70（桥带 70.7Ω 零几何改动）。
电路级 trap≡ljog（差异只在 EM 层：斜线 0.412mm 横移在 0.4mm 网格=1 胞，
逐行栅格化触发 #152 亚网格步距或退化为折线）；z70 @f0 亦理想但带边
2.3GHz 隔离 25.3dB 差于 rect 29.5dB（深度换带宽）且偏离 50Ω 桥带官方口径。
定版 ljog：全部六节电长度精确、轴对齐盒（#198 精确入网、#152 最小间距=
jog）、保 §10 官方口径；EM 地板由两处未切角 90° 弯折决定（真机 pt3 定案）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

W_ARM = 0.6035
W_FEED = 1.1134
ARM_LEN = 18.162
ISO_LEN = 17.75

NOMINAL = {"w_arm_mm": W_ARM, "w_feed_mm": W_FEED,
           "arm_len_mm": ARM_LEN, "iso_len_mm": ISO_LEN}

# 派生量（_gysel_layout 同式；纯几何恒等，非物理数字发明）
JOG = abs(ARM_LEN - ISO_LEN)      # 0.412mm 顶端横移
YJ = ISO_LEN - JOG                # 17.338mm 竖直段
XB = ISO_LEN                      # Δ 节点 x=±17.75mm → 桥带跨度 35.5mm

C0_MM_GHZ = 299.792458            # c（mm·GHz）


def _skrf_ring_s(kind: str, f0: float = 2.5, z0: float = 50.0) -> np.ndarray:
    """三种候选拓扑的 skrf 节点导纳装配 @f0（理论核验轮同源）。

    kind="ring"：六节环（λ/2 桥带连接两负载节点）；kind="naive"：无桥带；
    kind="merged"：两隔离线合并到单个负载。端口 0/1/2 = P1/P2/P3，
    内部节点 Schur 消元后取端口 S。
    """
    import skrf

    freq = skrf.Frequency(f0, f0, 1, unit="GHz")
    beta = 2.0 * np.pi * f0 * 1e9 / 299792458.0
    m_arm = skrf.media.DefinedGammaZ0(frequency=freq, gamma=1j * beta,
                                      z0=np.sqrt(2.0) * z0)
    m_iso = skrf.media.DefinedGammaZ0(frequency=freq, gamma=1j * beta, z0=z0)
    rl = m_iso.resistor(z0)
    if kind == "ring":
        nets = {(0, 1): m_arm.line(90, unit="deg"),
                (0, 2): m_arm.line(90, unit="deg"),
                (1, 3): m_iso.line(90, unit="deg"),
                (3, 4): m_iso.line(180, unit="deg"),
                (4, 2): m_iso.line(90, unit="deg")}
        load_nodes = (3, 4)
    elif kind == "naive":
        nets = {(0, 1): m_arm.line(90, unit="deg"),
                (0, 2): m_arm.line(90, unit="deg"),
                (1, 3): m_iso.line(90, unit="deg"),
                (2, 4): m_iso.line(90, unit="deg")}
        load_nodes = (3, 4)
    else:  # merged
        nets = {(0, 1): m_arm.line(90, unit="deg"),
                (0, 2): m_arm.line(90, unit="deg"),
                (1, 3): m_iso.line(90, unit="deg"),
                (2, 3): m_iso.line(90, unit="deg")}
        load_nodes = (3,)
    return _assemble(nets, load_nodes, rl, z0)


def _assemble(nets: dict, load_nodes: tuple, rl, z0: float) -> np.ndarray:
    """节点导纳装配 + 内部节点 Schur 消元 → 三端口 S（端口 0/1/2）。"""
    n_nodes = 1 + max(max(a, b) for a, b in nets)
    y = np.zeros((n_nodes, n_nodes), dtype=complex)
    for (a, b), net in nets.items():
        yy = net.y[0]
        y[a, a] += yy[0, 0]
        y[b, b] += yy[1, 1]
        y[a, b] += yy[0, 1]
        y[b, a] += yy[1, 0]
    for node in load_nodes:
        y[node, node] += complex(rl.y[0, 0, 0])
    y_red = (y[:3, :3] - y[:3, 3:] @ np.linalg.inv(y[3:, 3:]) @ y[3:, :3])
    return ((np.eye(3) - z0 * y_red)
            @ np.linalg.inv(np.eye(3) + z0 * y_red))


def _eps_pair() -> tuple[float, float]:
    """(εeff_arm, εeff_iso) 由确定性内核给出（rogers4350b h=0.508 @2.5GHz）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    st = Stackup.from_materials_yaml("rogers4350b_h0.508")
    _, e_arm = forward_z0(W_ARM, 2.5, st)
    _, e_iso = forward_z0(W_FEED, 2.5, st)
    return float(e_arm), float(e_iso)


def _candidate_ring_s(
    kind: str,
    f_ghz: float,
    arm_len: float = ARM_LEN,
    iso_len: float = ISO_LEN,
    z0: float = 50.0,
) -> np.ndarray:
    """四候选拓扑物理长度装配 @f_ghz（无损 TEM，theta ∝ d·√εeff·f）。

    kind="rect"：桥带 50Ω 物理长 2·arm_len（矩形现状，@f0 184.176°）；
    kind="trap"/"ljog"：桥带 50Ω 2·iso_len 精确（电路级同构，差异只在 EM）；
    kind="z70"：桥带 70.7Ω 物理长 2·arm_len（=70.7Ω λ/2 精确，零几何改动）。
    臂 70.7Ω arm_len、隔离线 50Ω iso_len 四候选共用。
    """
    import skrf

    e_arm, e_iso = _eps_pair()
    freq = skrf.Frequency(f_ghz, f_ghz, 1, unit="GHz")
    beta = 2.0 * np.pi * f_ghz * 1e9 / 299792458.0
    m_arm = skrf.media.DefinedGammaZ0(frequency=freq, gamma=1j * beta,
                                      z0=np.sqrt(2.0) * z0)
    m_iso = skrf.media.DefinedGammaZ0(frequency=freq, gamma=1j * beta, z0=z0)

    def line(m, d_mm: float, eff: float):
        return m.line(d_mm * math.sqrt(eff) * 1e-3, unit="m")

    nets = {(0, 1): line(m_arm, arm_len, e_arm),
            (0, 2): line(m_arm, arm_len, e_arm),
            (1, 3): line(m_iso, iso_len, e_iso),
            (4, 2): line(m_iso, iso_len, e_iso)}
    if kind == "rect":
        nets[(3, 4)] = line(m_iso, 2 * arm_len, e_iso)
    elif kind in ("trap", "ljog"):
        nets[(3, 4)] = line(m_iso, 2 * iso_len, e_iso)
    elif kind == "z70":
        nets[(3, 4)] = line(m_arm, 2 * arm_len, e_arm)
    else:
        raise ValueError(kind)
    return _assemble(nets, (3, 4), m_iso.resistor(z0), z0)


def _db(s: np.ndarray) -> np.ndarray:
    return 20 * np.log10(np.abs(s) + 1e-12)


def test_template_tables_have_gysel():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "gysel" in TEMPLATE_META and "gysel" in TEMPLATE_NOMINAL
    assert TEMPLATE_META["gysel"]["n_ports"] == 3
    assert TEMPLATE_NOMINAL["gysel"]["w_arm_mm"] == pytest.approx(W_ARM,
                                                                  abs=0.001)
    assert TEMPLATE_NOMINAL["gysel"]["iso_len_mm"] == pytest.approx(ISO_LEN,
                                                                    abs=0.05)
    assert _TEMPLATE_PORT_AXES["gysel"] == ("y",)
    assert _TEMPLATE_RADIATOR["gysel"] is False
    # 参数表仍为 4 键（jog/YJ/XB 为派生量，schema/缓存零波及）
    assert TEMPLATE_META["gysel"]["params"] == [
        "w_arm_mm", "w_feed_mm", "arm_len_mm", "iso_len_mm"]


def test_render_gysel_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("gysel", dict(NOMINAL), (2.25, 2.75))
    compile(text, "gen", "exec")  # 语法门（#201 制度化）
    for n in (1, 2, 3):
        assert f"MSLPort(CSX, port_nr={n}" in text
    assert text.count('prop_dir="y"') == 3
    # 双 50Ω 隔离负载 LumpedElement（atten_pi shunt 同款 ny=2 短柱），Δ 在 ±XB
    assert text.count('CSX.AddLumpedElement("iso_load') == 2
    assert "ny=2" in text and "R=50.0" in text
    assert "_r1.AddBox((-XB - W_F / 2, YJ - G / 2, 0.0)" in text
    assert "_r2.AddBox((XB - W_F / 2, YJ - G / 2, 0.0)" in text
    # λ/2 桥带（隔离必要环节，#206 判废锚）：顶边带缘 YJ±W_F/2、跨度 ±XB
    assert "YJ - W_F / 2" in text and "YJ + W_F / 2" in text
    assert "gysel.AddBox((-XB - W_F / 2, YJ - W_F / 2, H_SUB)" in text
    # L-jog 横移段：方向无关 min/max 写法 + 派生量常量
    assert "min(-XA, -XB) - W_F / 2" in text and "max(XA, XB) + W_F / 2" in text
    assert "JOG = " in text and "YJ = " in text and "XB = " in text
    # 隔离线竖直段止于 YJ（不再是 YI）
    assert "(-XA + W_F / 2, YJ, H_SUB)" in text
    # 下边双臂（70.7Ω）
    assert "-XA, -W_A / 2" in text
    # 第二激励轮禁用旧激励属性（gysel pt1 判废修复：不禁止则第二 run
    # 双激励，S23 被同相 -3dB 直通污染——S23 相位=S21 相位证据链；#211
    # footer 修复断言不得回退）
    assert '== "Excitation"' in text
    assert 'not str(_pr.GetName()).startswith("e3_")' in text
    # β 金标准插桩（#162）
    assert "port_beta.csv" in text


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import _near_points

    nx, ny = _near_points("gysel", dict(NOMINAL))
    # P1 馈线带缘 ±W_F/2
    for edge_mm in (-0.5567, 0.5567):
        assert min(abs(v - edge_mm * 1e-3) for v in nx) < 1e-12
    # 竖边/馈线 x 缘 ±XA±W_F/2（#198 精确入网）
    for edge_mm in (-(ARM_LEN + 0.5567), -(ARM_LEN - 0.5567),
                    ARM_LEN - 0.5567, ARM_LEN + 0.5567):
        assert min(abs(v - edge_mm * 1e-3) for v in nx) < 1e-12
    # Δ 节点负载盒 x 缘 ±XB±W_F/2（新增）
    for edge_mm in (-(XB + 0.5567), -(XB - 0.5567), XB - 0.5567, XB + 0.5567):
        assert min(abs(v - edge_mm * 1e-3) for v in nx) < 1e-12
    # 臂带缘 ±W_A/2
    for edge_mm in (-0.30175, 0.30175):
        assert min(abs(v - edge_mm * 1e-3) for v in ny) < 1e-12
    # 顶边桥带/jog 段带缘与负载盒 y 缘（以 YJ 为中心，不再是 YI）
    for edge_mm in (YJ - 0.5567, YJ + 0.5567, YJ - 0.25, YJ + 0.25):
        assert min(abs(v - edge_mm * 1e-3) for v in ny) < 1e-9
    # #152 核对：Δ 缘与竖边带缘最小间距 = jog = 0.412mm ≫ 1µm
    xs = np.sort(np.array([v for v in nx if v > 0]))
    assert float(np.min(np.diff(xs))) == pytest.approx(JOG * 1e-3, rel=1e-6)
    assert JOG * 1e-3 > 1e-6


def test_theory_ring_passes_naive_variants_fail():
    """理论核验锚（#206）：六节环达理想判据；两个朴素变体判废。

    理想判据 @f0：S21=S31=-3.01±0.05dB、S11/S22/S33/S32 ≤-40dB。
    本测试固化理论核验轮的 skrf 数值证据——桥带是隔离的必要环节。
    """
    for kind, ok in (("ring", True), ("naive", False), ("merged", False)):
        s = _skrf_ring_s(kind)
        db = _db(s)
        ideal = (abs(db[1, 0] + 3.01) < 0.05 and abs(db[2, 0] + 3.01) < 0.05
                 and db[0, 0] <= -40 and db[1, 1] <= -40
                 and db[2, 2] <= -40 and db[2, 1] <= -40)
        assert bool(ideal) == ok, \
            f"变体 {kind}: S21={db[1, 0]:.2f} S11={db[0, 0]:.1f}"
    # 环的传输相位 = -90°（λ/4 臂），双输出同相
    s = _skrf_ring_s("ring")
    assert np.angle(s[1, 0]) == pytest.approx(-np.pi / 2, abs=1e-9)
    assert np.angle(s[2, 0]) == pytest.approx(-np.pi / 2, abs=1e-9)
    # 判废变体的量化锚（理论核验轮实测：naive S21=-6.53/S11=-9.5dB）
    s_n = _skrf_ring_s("naive")
    db_n = _db(s_n)
    assert db_n[1, 0] == pytest.approx(-6.53, abs=0.1)
    assert db_n[0, 0] == pytest.approx(-9.5, abs=0.3)


def test_candidate_assembly_method_matches_locked_ring():
    """物理长度装配法与 #206 角度装配法互检（方法学验证，#118 独立来源）。

    取各线自身 εeff 的精确 λ/4（λ0/(4√εeff)）喂 ljog 装配，应逐元素等于
    _skrf_ring_s("ring")（90°/180° 角度装配）——证明 theta ∝ d·√εeff·f 的
    物理长度缩放与角度口径同源，后续候选数字才有裁判资格。
    """
    e_arm, e_iso = _eps_pair()
    lam0 = C0_MM_GHZ / 2.5
    s_phys = _candidate_ring_s("ljog", 2.5,
                               arm_len=lam0 / (4 * math.sqrt(e_arm)),
                               iso_len=lam0 / (4 * math.sqrt(e_iso)))
    np.testing.assert_allclose(s_phys, _skrf_ring_s("ring", f0=2.5), atol=1e-7)


def test_topology_candidates_offline_audit_locked():
    """离线核验轮四候选对照（2026-09-16 装配实测，本测试固化）。

    电路级归因：矩形桥带 +2.32%（184.176°@f0）把 @f0 S32/S11 封顶 -34.8dB；
    ljog/trap 电长度精确 @f0 ≤-88dB（−90.1/−88.4，残余来自 mm 三位舍入），
    带边 2.3/2.7GHz 隔离 25.9dB（≥25dB 判据）；z70 @f0 亦理想但 2.3GHz 隔离
    25.3dB 差于 rect 29.5dB（深度换带宽），rect 2.7GHz 隔离 23.0dB 不达 25dB。
    trap≡ljog 电路级逐元素相等（差异只在 EM 层）。
    """
    s = {k: {f: _candidate_ring_s(k, f) for f in (2.3, 2.5, 2.7)}
         for k in ("rect", "trap", "ljog", "z70")}
    d = {k: {f: _db(v) for f, v in fs.items()} for k, fs in s.items()}
    # ① 矩形现状基线（与历史归因数字 -34.78dB 互洽）
    assert d["rect"][2.5][2, 1] == pytest.approx(-34.77, abs=0.15)
    assert d["rect"][2.5][0, 0] == pytest.approx(-34.78, abs=0.15)
    assert d["rect"][2.3][2, 1] == pytest.approx(-29.46, abs=0.15)
    assert d["rect"][2.7][2, 1] == pytest.approx(-23.00, abs=0.15)
    # ② 定版 ljog：@f0 S32/S11 ≤-80dB（电长度精确），带边隔离 ≥25dB
    assert d["ljog"][2.5][2, 1] <= -80.0 and d["ljog"][2.5][0, 0] <= -80.0
    assert d["ljog"][2.5][1, 0] == pytest.approx(-3.01, abs=0.02)
    for f in (2.3, 2.7):
        assert -26.5 <= d["ljog"][f][2, 1] <= -25.0, d["ljog"][f][2, 1]
    # ③ trap 与 ljog 电路级同构（斜线/折线差异只在 EM 层）
    for f in (2.3, 2.5, 2.7):
        np.testing.assert_allclose(s["trap"][f], s["ljog"][f], atol=1e-12)
    # ④ z70：@f0 理想但低带边隔离差于 rect（深度换带宽）、均分带边最差
    assert d["z70"][2.5][2, 1] <= -80.0
    assert d["z70"][2.3][2, 1] > d["rect"][2.3][2, 1] + 3.0
    assert d["z70"][2.3][2, 1] == pytest.approx(-25.26, abs=0.15)
    assert d["z70"][2.3][1, 0] < d["ljog"][2.3][1, 0]
    # ⑤ 矩形桥带相位 @f0 = 184.176°（+2.32%）——归因主因的量化锚
    _, e_iso = _eps_pair()
    theta_rect = 360.0 * 2 * ARM_LEN * math.sqrt(e_iso) * 2.5 / C0_MM_GHZ
    assert theta_rect == pytest.approx(184.18, abs=0.05)
    dev_rect = 2 * ARM_LEN / (2 * ISO_LEN) - 1
    assert dev_rect == pytest.approx(0.0232, abs=0.0005)


def test_fake_gysel_ideal_split():
    """fake：理想六节环——均分 -3.01dB 同相、全匹配、输出互隔离。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="gysel", n_ports=3,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.solve("main_setup")
    net = ad.get_sparams()
    assert net.s.shape[1] == 3
    s21_db = 20 * np.log10(np.abs(net.s[:, 1, 0]) + 1e-12)
    s31_db = 20 * np.log10(np.abs(net.s[:, 2, 0]) + 1e-12)
    assert s21_db.mean() == pytest.approx(-3.01, abs=0.05)
    assert s31_db.mean() == pytest.approx(-3.01, abs=0.05)
    # 隔离对与全对角（诊断地板 -200dB）
    s32_db = 20 * np.log10(np.abs(net.s[:, 2, 1]) + 1e-12)
    s11_db = 20 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-12)
    assert s32_db.mean() < -100
    assert s11_db.mean() < -100
    # 传输相位：λ/4 臂 → -90°，双输出同相
    assert np.angle(net.s[50, 1, 0]) == pytest.approx(-np.pi / 2, abs=1e-9)
    assert np.angle(net.s[50, 2, 0]) == pytest.approx(-np.pi / 2, abs=1e-9)


def test_fake_gysel_matches_skrf_ring_assembly():
    """闭式裁判对照独立来源（#205 互检纪律）：skrf 六节环 Y 装配。

    独立构造：五条理想线段（70.7Ω λ/4×2 + 50Ω λ/4×2 + 50Ω λ/2 桥带）
    + 双 50Ω 负载的节点导纳装配（内部节点 Schur 消元），@f0 逐元素
    等于 fake 闭式。
    """
    from rfauto.adapters.fake_adapter import _gysel_sparams

    s_asm = _skrf_ring_s("ring", f0=2.5)
    s_ref = _gysel_sparams(np.array([2.5]))[0]
    # atol=1e-7：λ/2 桥带在 f0 处 Y 装配近奇异（中点开路节点），数值
    # 零残差 ~6e-9（=-164dB，仍是深度诊断零）；-3dB 主项误差 <1e-12
    np.testing.assert_allclose(s_asm, s_ref, atol=1e-7)


def test_synthesize_gysel_model_roundtrip():
    from rfauto.core.synthesis import (
        Stackup,
        forward_z0,
        inverse_width,
        synthesize_gysel_model,
    )

    result = synthesize_gysel_model(z0_ohm=50.0, freq_ghz=2.5)
    assert result.model == "gysel"
    st = Stackup.from_materials_yaml("rogers4350b_h0.508")
    w_arm_ref, _, _ = inverse_width(70.7, 2.5, st)
    w_iso_ref, _, _ = inverse_width(50.0, 2.5, st)
    assert result.params["w_arm_mm"] == pytest.approx(w_arm_ref, abs=0.01)
    assert result.params["w_feed_mm"] == pytest.approx(w_iso_ref, abs=0.01)
    # 臂/隔离线长度各用自身 εeff 的 λ/4（εeff 差 ~4.5%，不可混用）
    _, ea = forward_z0(w_arm_ref, 2.5, st)
    _, ei = forward_z0(w_iso_ref, 2.5, st)
    assert result.params["arm_len_mm"] == pytest.approx(
        299.792458 / 2.5 / np.sqrt(ea) / 4, abs=0.02)
    assert result.params["iso_len_mm"] == pytest.approx(
        299.792458 / 2.5 / np.sqrt(ei) / 4, abs=0.02)
    assert result.params["iso_len_mm"] != pytest.approx(
        result.params["arm_len_mm"], abs=0.1)
    # 参数表仍为 4 几何键 + f0（派生量只进 notes）
    assert set(result.params) == {"w_arm_mm", "w_feed_mm", "arm_len_mm",
                                  "iso_len_mm", "f0_ghz"}
    assert any("L-jog" in n and "2·iso_len" in n for n in result.notes)
    objs = result.recipe_draft["objectives"]
    assert objs[0]["metric"] == "s21_db" and objs[0]["op"] == "mean_within"
    assert objs[0]["value"] == pytest.approx([-3.5, -2.5])
    assert objs[1]["metric"] == "s11_db"


def test_gysel_spec_wiring():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("gysel")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    draft = TEMPLATE_SPECS.draft_recipe("gysel", z0_ohm=50.0)
    assert draft["model"] == "gysel"
    assert "w_arm_mm" in draft["params"]


def test_rect_bridge_deviation_historical_math_lock():
    """矩形旧版 +2.32% 二阶偏差——历史事实的纯数学锁（改判后保留）。

    几何事实（「Gysel 桥带 εeff 二阶偏差」历史判读）：矩形环顶边
    继承 70.7Ω 臂 λ/4 跨度 2·arm_len，而 50Ω λ/2 桥带设计值 = 2·iso_len——
    矩形环只有 2 个自由边长，臂/隔离线/桥带三个 λ/4 约束不可同时满足。
    本锁只钉数学关系（防标称参数静默漂移）：① 偏差落在 +2.32% 邻域；
    ② 偏差与两线 εeff 闭式互洽（λ/4∝1/√εeff，独立换算路径）。
    渲染几何已由 L-jog 变体消除该偏差（test_ljog_render_measured_
    electrical_lengths_locked），本锁不再断言 meta 文本"偏差固有"。
    """
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
    from rfauto.core.synthesis import Stackup, forward_z0

    nom = TEMPLATE_NOMINAL["gysel"]
    dev = 2.0 * nom["arm_len_mm"] / (2.0 * nom["iso_len_mm"]) - 1.0
    assert 0.020 <= dev <= 0.026  # +2.32% 邻域
    st = Stackup.from_materials_yaml("rogers4350b_h0.508")
    _, e_arm = forward_z0(nom["w_arm_mm"], 2.5, st)
    _, e_iso = forward_z0(nom["w_feed_mm"], 2.5, st)
    dev_from_eps = math.sqrt(e_iso / e_arm) - 1.0
    assert dev == pytest.approx(dev_from_eps, abs=0.002)


def test_ljog_render_measured_electrical_lengths_locked():
    """渲染实测锁（#212 手法：render→exec→CSXCAD 原语实测，零仿真）。

    在实测原语上钉两条电长度恒等式：
    ① P2→Δ 路径物理长（竖直段 YJ + 横移 |XA−XB|）== iso_len ±0.5%；
    ② 桥带跨度（两负载盒 x 心距 2·XB）== 2·iso_len ±0.5%。
    另钉：顶边带（jog×2+桥带）三盒共线于 y=YJ、负载盒落在 x=±XB。
    """
    from tests.unit import _geometry_audit_helpers as gh

    scope, prims = gh.load_geometry("gysel")
    loads = [p for p in prims if p.kind == "LumpedElement"]
    assert len(loads) == 2
    xc = sorted(float((p.lo[0] + p.hi[0]) / 2) for p in loads)
    span = xc[1] - xc[0]
    assert span == pytest.approx(2 * ISO_LEN * 1e-3, rel=0.005)
    xb_m = xc[1]
    yc_loads = [float((p.lo[1] + p.hi[1]) / 2) for p in loads]
    assert all(v == pytest.approx(YJ * 1e-3, rel=1e-6) for v in yc_loads)

    metal = [p for p in prims if p.kind == "Metal"]
    xa_m = ARM_LEN * 1e-3
    # 左竖直隔离段：x 心 −XA、从 y=0 起（排除 MSLPort 自画馈线，其 y 从 −BOARD 起）
    vert = [p for p in metal
            if abs(float((p.lo[0] + p.hi[0]) / 2) + xa_m) < 1e-9
            and abs(float(p.lo[1])) < 1e-9]
    assert len(vert) == 1, [(_p.lo, _p.hi) for _p in vert]
    yj_m = float(vert[0].hi[1])
    assert yj_m == pytest.approx(YJ * 1e-3, rel=1e-6)
    path = yj_m + abs(xa_m - xb_m)
    assert path == pytest.approx(ISO_LEN * 1e-3, rel=0.005)
    # 顶边带三盒（两 jog + 桥带）共线于 y=YJ
    top = [p for p in metal
           if abs(float((p.lo[1] + p.hi[1]) / 2) - yj_m) < 1e-9]
    assert len(top) == 3
    bridge = max(top, key=lambda p: float(p.hi[0] - p.lo[0]))
    assert float((bridge.lo[0] + bridge.hi[0]) / 2) == pytest.approx(0.0, abs=1e-12)
    assert float(bridge.hi[0] - bridge.lo[0]) == pytest.approx(
        2 * ISO_LEN * 1e-3 + W_FEED * 1e-3, rel=1e-6)
    # 派生量脚本常量与实测一致（渲染层 _gysel_layout 单一事实源）
    assert float(scope["XB"]) == pytest.approx(xb_m, rel=1e-9)
    assert float(scope["YJ"]) == pytest.approx(yj_m, rel=1e-9)
    assert float(scope["JOG"]) == pytest.approx(JOG * 1e-3, rel=1e-6)


def test_gysel_layout_guard_and_direction_agnostic():
    """_gysel_layout 守卫与方向无关性（审计 ×1.37 单键扰动全部保持合法）。"""
    from rfauto.adapters.openems_templates import _gysel_layout, render_script

    lay = _gysel_layout(dict(NOMINAL))
    assert lay["jog"] == pytest.approx(JOG, abs=1e-9)
    assert lay["yj"] == pytest.approx(YJ, abs=1e-9)
    assert lay["xb"] == pytest.approx(XB, abs=1e-12)
    assert lay["yj"] + lay["jog"] == pytest.approx(ISO_LEN, abs=1e-9)
    # iso_len ×1.37（审计扰动口径）→ Δ 外移：XB>XA，YJ=arm_len，仍合法可渲染
    p_out = dict(NOMINAL, iso_len_mm=ISO_LEN * 1.37 + 0.013)
    lay_out = _gysel_layout(p_out)
    assert lay_out["xb"] > lay_out["xa"] and lay_out["yj"] > 0
    assert lay_out["yj"] == pytest.approx(lay_out["xa"], abs=1e-9)
    compile(render_script("gysel", p_out, (2.25, 2.75)), "gen", "exec")
    # jog=0 退化（arm_len==iso_len）：Δ 回到角部、桥带跨度=2·iso_len，合法
    lay_eq = _gysel_layout(dict(NOMINAL, arm_len_mm=ISO_LEN))
    assert lay_eq["jog"] == 0.0 and lay_eq["yj"] == pytest.approx(ISO_LEN)
    # 守卫：arm_len ≥ 2·iso_len → YJ≤0，渲染 ValueError（不静默夹紧）
    with pytest.raises(ValueError, match="YJ"):
        _gysel_layout(dict(NOMINAL, arm_len_mm=2 * ISO_LEN + 1.0))
    with pytest.raises(ValueError):
        render_script("gysel", dict(NOMINAL, iso_len_mm=ARM_LEN / 2 - 0.5),
                      (2.25, 2.75))


def test_meta_text_ljog_variant_wording():
    """meta 文本改判（#122 如实）："偏差固有"改述为 L-jog 变体口径，历史保留。"""
    from rfauto.adapters.openems_templates import TEMPLATE_META

    semantics = TEMPLATE_META["gysel"]["param_semantics"]
    topology = TEMPLATE_META["gysel"]["topology"]
    assert "L-jog" in semantics and "2·iso_len" in semantics
    assert "偏差固有" not in semantics
    # 历史事实保留（+2.32% 归因与 #211 真跑基线不得抹去）
    assert "+2.32%" in semantics and "2·arm_len" in semantics
    assert "L-jog" in topology and "2·iso_len" in topology
    # 旧误导口径（"隔离线/半桥带 λ/4"）不得回归
    assert "隔离线/半桥带" not in semantics


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "gysel" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "gysel"
    assert data["n_ports"] == TEMPLATE_META["gysel"]["n_ports"]
    assert "L-jog" in data["topology"] and "2·iso_len" in data["topology"]
    # params/nominal 不变（schema/缓存零波及）
    assert data["params"] == TEMPLATE_META["gysel"]["params"]
    assert data["nominal_params"] == NOMINAL
