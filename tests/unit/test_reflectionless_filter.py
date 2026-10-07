"""TF-2 无反射滤波器闭式族单测（研究扩充 round5 §4.2 TF-2 判据）。

裁判口径（#118 双路径，路径 A=内核实现，路径 B=独立实现/文献）：
- 路径 B1：Chebyshev g_k 文献 4 位表（0.1/0.5 dB N=3/5/7；与
  tests/unit/test_lc_filter.py 同源誊录，MYJ 1964 §4.05 递式重算钉正）；
- 路径 B2：core/lc_filter.cauer_ladder_gk（TF-1 已验收内核，只读复用为
  独立裁判，奇阶 g_k 交叉 ≤1e-9）；
- 路径 B3：偶阶响应恒等——测试内独立 ABCD 梯形（不等终接 g0=1、
  g_{N+1}=coth²(β/4)）vs 闭式 1/(1+ε²T_N²) ≤1e-10；
- 恒阻恒等式（任务主判据）：200 点扫频 |S11|max ≤1e-9（预声明；实测
  MNA ≤3e-13 / 模式路径 ≤3e-16）；对偶互证 z_e·z_o = Z0² 逐频残差
  ≤1e-9（实测 ≤1e-15）；双引擎一致 ≤1e-9（实测 ≤4e-13）。
- 滚降（#122 如实登记）：远阻带渐近实测 −20 dB/dec（与阶数无关，端口
  单串 C 主导）；阶数作用 = 过渡带肩部变陡。任务书 "-40dB/dec×N" 口径
  按实测修正，判据按实测口径钉（渐近 [−20±2] dB/dec 窗 + 肩部随 P 变陡）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import lc_filter
from rfauto.core import reflectionless_filter as rf

# ─── 路径 B1：文献 4 位 g 表（与 test_lc_filter 同源誊录）─────────────────────

CHEBY_TABLE = {
    0.1: {
        3: [1.0316, 1.1474, 1.0316],
        5: [1.1468, 1.3712, 1.9750, 1.3712, 1.1468],
        7: [1.1812, 1.4228, 2.0967, 1.5734, 2.0967, 1.4228, 1.1812],
    },
    0.5: {
        3: [1.5963, 1.0967, 1.5963],
        5: [1.7058, 1.2296, 2.5408, 1.2296, 1.7058],
        7: [1.7373, 1.2582, 2.6383, 1.3443, 2.6383, 1.2582, 1.7373],
    },
}
TABLE_RTOL = 2.5e-4  # 4 位十进制舍入（同 TF-1 预声明）


# ─── 路径 B3：独立 ABCD 梯形（不等终接响应恒等裁判）──────────────────────────


def _ladder_plr(g_values: list[float], g_load: float, omega: np.ndarray) -> np.ndarray:
    """由 g 表搭不对称终接梯形（g1=串 L），返回功率损耗比 1/|S21|²−1。

    独立于内核实现（测试内手写 ABCD 级联 + Thevenin 传输），#118。
    """
    zs = 1.0
    a = np.ones_like(omega, dtype=complex)
    b = np.zeros_like(omega, dtype=complex)
    c = np.zeros_like(omega, dtype=complex)
    d = np.ones_like(omega, dtype=complex)
    for k, g_k in enumerate(g_values):
        if k % 2 == 0:  # 串 L
            a, b, c, d = a, a * (1j * omega * g_k) + b, c, c * (1j * omega * g_k) + d
        else:  # 并 C
            y = 1j * omega * g_k
            a, b, c, d = a + y * b, b, c + y * d, d
    v_load = 1.0 / ((a + zs * c) + (b + zs * d) / g_load)
    p_load = np.abs(v_load) ** 2 / g_load
    p_avail = 1.0 / (4.0 * zs)
    return p_avail / p_load - 1.0


# ─── 1. 原型表面 ─────────────────────────────────────────────────────────────


def test_cheby_g_table_published_anchors_odd():
    """奇阶 g 表 vs 文献 4 位表（0.1/0.5 dB，N=3/5/7，rel ≤2.5e-4）。"""
    for ripple, rows in CHEBY_TABLE.items():
        for n, expected in rows.items():
            g, g_load = rf.chebyshev_g_table(n, ripple)
            assert len(g) == n
            assert abs(g_load - 1.0) <= 1e-12  # 奇阶等终接
            assert np.max(np.abs(np.asarray(g) / np.asarray(expected) - 1.0)) <= TABLE_RTOL


def test_cheby_g_table_even_order_gload_and_response_identity():
    """偶阶 g_load = coth²(β/4) ≠ 1 + 响应恒等 vs 闭式 PLR（独立路径 B3）。

    偶阶不等终接梯形复现 1/(1+ε²T_N²)（含 DC 增益 1/(1+ε²)）≤1e-10——
    该口径正是无反射拓扑消费的标准原型表（任务判据：可达源回收）。
    """
    w = np.linspace(1e-3, 3.0, 1201)
    for n in (4, 6):
        for ripple in (0.1, 0.5):
            g, g_load = rf.chebyshev_g_table(n, ripple)
            assert all(g_k > 0.0 for g_k in g)
            assert g_load > 1.0  # 偶阶不等终接（coth²(β/4)）
            eps2 = 10.0 ** (ripple / 10.0) - 1.0
            tn = np.polynomial.chebyshev.chebval(w, np.eye(n + 1)[n])
            # 以 |S21|² 比较（量纲良定；PLR 在高频 ~1e7，绝对差会被放大）
            p21_expected = 1.0 / (1.0 + eps2 * tn**2)
            p21_got = 1.0 / (1.0 + _ladder_plr(g, g_load, w))
            assert np.max(np.abs(p21_got - p21_expected)) <= 1e-12
            dc_gain = 1.0 / (1.0 + _ladder_plr(g, g_load, np.array([1e-6]))[0])
            assert abs(dc_gain - 1.0 / (1.0 + eps2)) <= 1e-9


def test_cheby_g_table_cross_check_lc_filter():
    """奇阶 g 表 vs TF-1 cauer_ladder_gk 元件值（跨内核交叉，≤1e-9）。"""
    for ripple in (0.1, 0.5):
        for n in (3, 5, 7):
            g, _ = rf.chebyshev_g_table(n, ripple)
            spec = lc_filter.make_prototype("chebyshev1", n, ripple_db=ripple)
            ladder = lc_filter.cauer_ladder_gk(spec, first_element="series")
            g_ref = [el.value for el in ladder.elements]
            assert np.max(np.abs(np.asarray(g) - np.asarray(g_ref))) <= 1e-9


def test_g_table_guards():
    with pytest.raises(ValueError):
        rf.chebyshev_g_table(0, 0.5)  # N<1
    with pytest.raises(ValueError):
        rf.chebyshev_g_table(True, 0.5)  # bool 显式拒收（df7+⑯）
    with pytest.raises(ValueError):
        rf.chebyshev_g_table(3.0, 0.5)  # 非 int
    with pytest.raises(ValueError):
        rf.chebyshev_g_table(3, 0.0)  # 纹波 <=0
    with pytest.raises(ValueError):
        rf.chebyshev_g_table(3, -0.5)
    with pytest.raises(ValueError):
        rf.chebyshev_g_table(3, float("nan"))


# ─── 2. 规格与元件值表面 ─────────────────────────────────────────────────────


def test_make_spec_guards():
    with pytest.raises(ValueError):
        rf.make_spec(0, 0.5)  # n_pairs < 1
    with pytest.raises(ValueError):
        rf.make_spec(True, 0.5)  # bool
    with pytest.raises(ValueError):
        rf.make_spec(2, 0.0)
    with pytest.raises(ValueError):
        rf.make_spec(2, 0.5, z0_ohm=0.0)
    with pytest.raises(ValueError):
        rf.make_spec(2, 0.5, fc_hz=0.0)  # fc<=0（非 None 判缺失语义）
    with pytest.raises(ValueError):
        rf.make_spec(2, 0.5, kind="bandpass")  # 未注册 kind
    ok = rf.make_spec(2, 0.5, z0_ohm=50.0, fc_hz=1e6, kind=rf.KIND_HPF)
    assert ok.n_pairs == 2 and ok.z0_ohm == 50.0 and ok.fc_hz == 1e6
    assert ok.kind == "hpf"
    norm = rf.make_spec(2, 0.5)
    assert norm.fc_hz is None and norm.kind == "lpf"  # 判缺失 is not None（#364④）


def test_make_network_guards():
    with pytest.raises(ValueError):
        rf.make_network("not-a-spec")  # 非 ReflectionlessSpec


def test_element_table_structure():
    """元件值表结构：[Mor15] 约束式（等值链）＋逐件 role/side/index 完整。

    v = 1/(2·g1)；桥 = 2v；链内全部对 = v；平面元件 = 2·链值
    （Cn2 = 2·Lb2）；R = Z0；去归一化 L·Z0/ωc、C/(Z0·ωc)。
    """
    net = rf.make_network(rf.make_spec(n_pairs=3, ripple_db=0.5, z0_ohm=50.0, fc_hz=1e6))
    g, _ = rf.chebyshev_g_table(2 * 3 + 1, 0.5)
    v_norm = 1.0 / (2.0 * g[0])
    omega_c = 2.0 * math.pi * 1e6
    scale_c = 1.0 / (50.0 * omega_c)
    scale_l = 50.0 / omega_c
    assert net.v_norm == pytest.approx(v_norm)
    assert net.bridge_l_h == pytest.approx(2.0 * v_norm * scale_l)
    chain_vals = [v for _, v in net.chain_pairs]
    assert len(chain_vals) == 6
    # 等值链（归一化基值逐位相等；物理值按 C/L 各自缩放）
    c_vals = [chain_vals[2 * i] for i in range(3)]
    l_vals = [chain_vals[2 * i + 1] for i in range(3)]
    assert all(v == c_vals[0] for v in c_vals) and all(v == l_vals[0] for v in l_vals)
    assert c_vals[0] == pytest.approx(v_norm * scale_c)  # 偶位为串 C
    assert l_vals[0] == pytest.approx(v_norm * scale_l)  # 奇位为并 L
    assert net.plane_c_f == pytest.approx(2.0 * v_norm * scale_c)  # Cn2 = 2·Lb2
    assert net.r_absorber_ohm == 50.0
    # 逐件表
    roles = [el.role for el in net.elements]
    assert roles.count("bridge_series_L") == 1
    assert roles.count("chain_series_C") == 6 and roles.count("chain_shunt_L") == 6
    assert roles.count("chain_series_R") == 2 and roles.count("plane_shunt_C") == 1
    assert len(net.elements) == 1 + 2 * (2 * 3 + 1) + 1
    sides = {el.side for el in net.elements}
    assert sides == {"left", "right", "common"}
    assert all(el.index is not None for el in net.elements if el.role.startswith("chain_s"))
    bridge = next(el for el in net.elements if el.role == "bridge_series_L")
    assert bridge.index is None and bridge.side == "common"


def test_to_dict_json_roundtrip():
    """to_dict JSON 可序列化＋规格字段回读；None 语义经 is not None 判定。"""
    net = rf.make_network(rf.make_spec(n_pairs=2, ripple_db=0.5, z0_ohm=50.0, fc_hz=1e6))
    payload = json.dumps(net.to_dict())  # 不抛即 JSON 可序列化
    back = json.loads(payload)
    assert back["spec"]["n_pairs"] == 2
    assert back["spec"]["fc_hz"] == 1e6
    assert back["g_table"][0] == pytest.approx(1.7058, rel=1e-4)
    assert back["bridge_l_h"] == net.bridge_l_h
    assert len(back["elements"]) == len(net.elements)
    norm = rf.make_network(rf.make_spec(2, 0.5)).to_dict()
    assert norm["spec"]["fc_hz"] is None  # 归一化语义
    assert norm["bridge_c_f"] is None and norm["plane_l_h"] is None
    # 谱系勘误登记在 sources（任务书语境钉死）
    assert "lineage_correction" in norm["sources"]
    assert "Morgan-Boyd" in norm["sources"]["lineage_correction"]
    assert "UNVERIFIED" in norm["sources"]["concept"]  # 付费墙表格不誊录如实登记


# ─── 3. 恒阻恒等式（任务主判据）与双引擎 ─────────────────────────────────────

SWEEP = np.geomspace(1e-3, 1e3, 200)  # 200 点扫频（任务判据口径）


@pytest.mark.parametrize("n_pairs", [1, 2, 3])
@pytest.mark.parametrize("kind", [rf.KIND_LPF, rf.KIND_HPF])
def test_constant_resistance_main_criterion(n_pairs, kind):
    """恒阻恒等式主判据：200 点 |S11|max ≤1e-9（预声明；实测 ≤3e-13）。"""
    net = rf.make_network(rf.make_spec(n_pairs=n_pairs, ripple_db=0.5, kind=kind))
    s11, s21 = rf.network_sparams(net, SWEEP)
    worst = float(np.abs(s11).max())
    assert worst <= 1e-9
    assert float(np.abs(s21).max()) <= 1.0 + 1e-9  # 无源界


@pytest.mark.parametrize("kind", [rf.KIND_LPF, rf.KIND_HPF])
def test_dual_engine_agreement(kind):
    """#118 双路径：MNA 全网表 vs 偶/奇半电路（P=1/2，一致 ≤1e-9）。"""
    for n_pairs in (1, 2):
        net = rf.make_network(rf.make_spec(n_pairs=n_pairs, ripple_db=0.5, kind=kind))
        s11_a, s21_a = rf.network_sparams(net, SWEEP)
        s11_b, s21_b = rf.network_sparams_by_modes(net, SWEEP)
        assert float(np.abs(s11_a - s11_b).max()) <= 1e-9
        assert float(np.abs(s21_a - s21_b).max()) <= 1e-9


@pytest.mark.parametrize("kind", [rf.KIND_LPF, rf.KIND_HPF])
def test_duality_identity(kind):
    """对偶互证：z_e·z_o = Z0² 逐频残差 ≤1e-9（实测 ≤1e-15，任务判据 4）。"""
    for n_pairs in (1, 2, 3):
        net = rf.make_network(rf.make_spec(n_pairs=n_pairs, ripple_db=0.5, kind=kind))
        res = rf.duality_residual(net, SWEEP)
        assert float(res.max()) <= 1e-9


def test_mode_path_s11_machine_zero():
    """模式路径 |S11| 机器零（对偶恒等式的直接推论，实测 ~1e-16）。"""
    net = rf.make_network(rf.make_spec(n_pairs=2, ripple_db=0.5))
    s11, _ = rf.network_sparams_by_modes(net, SWEEP)
    assert float(np.abs(s11).max()) <= 1e-9


# ─── 4. 响应形态（LPF 低通 / HPF 高通，#122 如实口径）────────────────────────


def _wc3db(net: rf.ReflectionlessNetwork) -> float:
    w = np.geomspace(1e-2, 1e3, 4001)
    _s11, s21 = rf.network_sparams(net, w)
    p = np.abs(s21) ** 2
    for i in range(1, len(w)):
        if p[i - 1] >= 0.5 > p[i]:
            frac = (p[i - 1] - 0.5) / (p[i - 1] - p[i])
            return float(w[i - 1] + frac * (w[i] - w[i - 1]))
    raise AssertionError("无 −3dB 交越")


def test_lpf_response_shape():
    """LPF：DC 直通、单调滚降、无源性、−3dB 截止窗、阻带吸收行为。"""
    net = rf.make_network(rf.make_spec(n_pairs=2, ripple_db=0.5))
    w = np.geomspace(1e-2, 1e2, 801)
    _s11, s21 = rf.network_sparams(net, w)
    mag = np.abs(s21)
    assert mag[0] >= 0.99  # DC 直通
    i_half, i_one, i_two = (int(np.argmin(np.abs(w - x))) for x in (0.5, 1.0, 2.0))
    assert mag[i_two] < mag[i_one] < mag[i_half]  # 单调滚降
    assert float(mag.max()) <= 1.0 + 1e-9  # 无源
    i_stop = int(np.argmin(np.abs(w - 10.0)))
    assert mag[i_stop] ** 2 <= 0.25  # 阻带 ≥6dB：功率被吸收支路吸收
    assert _wc3db(net) == pytest.approx(1.96, rel=0.05)  # 实测锚 1.9611（0.5dB/P=2）


def test_stopband_slope_honest():
    """滚降判据（#122 实测口径）：远阻带渐近 [−20±2] dB/dec + 肩部随 P 变陡。

    任务书 "-40dB/dec×N" 口径与本拓扑实测不符（端口单串 C 主导，渐近
    −20 dB/dec 与阶数无关）——按实测修正登记，不凑勾。
    """
    w = np.geomspace(1e-2, 1e6, 1201)
    shoulder = {}
    for n_pairs in (1, 2, 3):
        net = rf.make_network(rf.make_spec(n_pairs=n_pairs, ripple_db=0.5))
        _s11, s21 = rf.network_sparams(net, w)
        mag_db = 20.0 * np.log10(np.abs(s21))
        sel = (w > 1e3) & (w < 1e5)
        slope = float(np.polyfit(np.log10(w[sel]), mag_db[sel], 1)[0])
        assert -22.0 <= slope <= -18.0  # 渐近 −20 dB/dec（实测钉）
        sel2 = (w > 3.0) & (w < 30.0)
        shoulder[n_pairs] = float(np.polyfit(np.log10(w[sel2]), mag_db[sel2], 1)[0])
    assert shoulder[3] < shoulder[1] - 5.0  # 阶数作用 = 过渡带肩部变陡（实测 −3 vs −17）


def test_hpf_transform():
    """HPF 对偶变换：高通形态＋恒阻恒等式保持（任务可选判据 5）。"""
    net = rf.make_network(rf.make_spec(n_pairs=2, ripple_db=0.5, kind=rf.KIND_HPF))
    assert net.bridge_c_f is not None and net.plane_l_h is not None
    assert net.bridge_l_h is None and net.plane_c_f is None
    w = np.geomspace(1e-2, 1e2, 401)
    s11, s21 = rf.network_sparams(net, w)
    assert float(np.abs(s11).max()) <= 1e-9  # 恒阻保持
    mag = np.abs(s21)
    assert mag[0] <= 0.05  # DC 阻断
    assert mag[-1] >= 0.99  # 高频直通
    assert float(rf.duality_residual(net, SWEEP).max()) <= 1e-9
    # 元件值与 LPF 同源（同一 v_norm 基值；LP→HP 为 L↔C 值取倒数）
    net_lpf = rf.make_network(rf.make_spec(n_pairs=2, ripple_db=0.5))
    assert net.v_norm == pytest.approx(net_lpf.v_norm)
    # 桥：LPF 串 L = 2v·Z0/ωc ↔ HPF 串 C = (1/2v)/(Z0·ωc)（归一化 ωc=1, Z0=1）
    assert net.bridge_c_f == pytest.approx(1.0 / net_lpf.bridge_l_h)


def test_ripple_effect_on_g1_and_cutoff():
    """纹波 → g1 → 基值 → 截止移动；两种纹波下恒阻恒等式均保持。"""
    net_lo = rf.make_network(rf.make_spec(n_pairs=2, ripple_db=0.1))
    net_hi = rf.make_network(rf.make_spec(n_pairs=2, ripple_db=0.5))
    g1_lo, _ = rf.chebyshev_g_table(5, 0.1)
    g1_hi, _ = rf.chebyshev_g_table(5, 0.5)
    assert abs(g1_lo[0] - CHEBY_TABLE[0.1][5][0]) <= 1e-3  # 1.1468（N=5 文献表值）
    assert abs(g1_hi[0] - CHEBY_TABLE[0.5][5][0]) <= 1e-3  # 1.7058
    assert net_lo.v_norm > net_hi.v_norm  # g1 越大基值越小
    wc_lo = _wc3db(net_lo)
    wc_hi = _wc3db(net_hi)
    assert wc_hi > wc_lo  # 实测 1.96 vs ~1.33（0.5dB 截止更靠上）
    for net in (net_lo, net_hi):
        s11, _ = rf.network_sparams(net, SWEEP)
        assert float(np.abs(s11).max()) <= 1e-9


# ─── 5. 去归一化面 ───────────────────────────────────────────────────────────


def test_denormalization_and_scaling_identity():
    """去归一化（50Ω/1MHz）：恒阻保持＋频率伸缩恒等 s21_den(f)≡s21_norm(f/fc)。

    注意 network_sparams 入参为角频率（rad/s）——伸缩映射 ω_norm = 2πf/ωc
    = f/fc。
    """
    z0, fc = 50.0, 1e6
    net_n = rf.make_network(rf.make_spec(n_pairs=2, ripple_db=0.5))
    net_d = rf.make_network(rf.make_spec(n_pairs=2, ripple_db=0.5, z0_ohm=z0, fc_hz=fc))
    # 单位与量级（H/F 实际值）
    assert 1e-7 <= net_d.bridge_l_h <= 1e-5  # ≈4.67 µH
    assert 1e-10 <= net_d.plane_c_f <= 1e-8  # ≈1.87 nF
    assert net_d.r_absorber_ohm == 50.0
    f = np.geomspace(1e4, 1e9, 200)
    s11_d, s21_d = rf.network_sparams(net_d, 2.0 * math.pi * f)
    assert float(np.abs(s11_d).max()) <= 1e-9
    _s11_n, s21_n = rf.network_sparams(net_n, f / fc)  # ω_norm = f/fc
    assert float(np.abs(s21_d - s21_n).max()) <= 1e-9  # 频率伸缩恒等
    # 元件值缩放恒等：L_d = L_n·Z0/ωc
    assert net_d.bridge_l_h == pytest.approx(net_n.bridge_l_h * z0 / (2.0 * math.pi * fc))
