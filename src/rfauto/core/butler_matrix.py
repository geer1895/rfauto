"""4×4 Butler 矩阵综合与波束指向内核（理想无耗闭式 + skrf 级联双路径）。

法源（铁律 5：来源写 docstring；裁判=独立路径互证，#118）：

- 拓扑：Butler, J. & Lowe, R., "Beam-Forming Matrix Simplifies Design of
  Electronically Scanned Antennas", Electronic Design, vol. 9, pp. 170-173
  (1961)。4×4 结构 = 4 个 3 dB 90° 混合环 + 2 个交叉结（crossover）+
  4 个移相器（本模块钉死连线表见 :func:`butler_wiring_table` 与下方连线图）。
- 混合环闭式口径：branch-line coupler 理想 S 参数（Pozar, Microwave
  Engineering, branch-line coupler 节）：通路口/耦合口幅度 1/√2、两臂
  相位正交、隔离口为零、无耗匹配。

任务书规格勘误（#118"修正之前先验证模型本身"，2026-09-27 B2 批落地时核对）：
任务书字面混合环矩阵 ``(−1/2)·[[0,j,j,0],…]`` 每列能量 Σ|S_ij|² = 1/2
（6 dB 有耗），与任务书自身的"无耗（每列 Σ|S_ij|²=1）"判据矛盾；且该矩阵
四个通路口全部等相位，以其为积木组装时波束口 1/2 两列恒等（简并，不构成
Butler 矩阵）。本模块按无耗 3 dB 90° 混合环钉死（2×2 传输块
``(1/√2)·[[1, 1], [j, −j]]``），混合环恒等式按 unitary 口径验证。

约定钉死（全模块一致，多版本相位约定中选此一种）：

- 混合环 4 端口序 (1, 2, 3, 4) = (左上入, 右上出, 右下出, 左下入)。任一
  左侧入口：同侧横穿臂 0°（1/√2）、对角臂 ±90°（上入→右下 +90°，
  下入→右下 −90°）；对侧镜像对称；隔离对 (1,4) 与 (2,3)。
- 交叉结：4 端口置换矩阵，左 (1,2) 入、右 (3,4) 出、内对角交叉
  （左上入→右下出、左下入→右上出），理想 0 dB 直通。
- 移相器：2 端口 ``[[0, e^{jφ}], [e^{jφ}, 0]]``，φ 任意有限实数（内部
  规范化到 [0, 2π)，钉死规范化而非报错）。
- 端口序按相位递进闭式 δ_k = (2k−N−1)·π/N（N=4）钉死：物理槽位
  （上→下）= 波束口 (B1, B3, B4, B2)——经典 Butler 波束口交错编排
  （相邻物理口不可能对应相邻波束序号，由混合环正交性强制）。
- 波束指向配对约定（钉死）：激励按接收式共轭权重（导向矢量共轭，波束
  指向文献标准口径）送入 :func:`array_factor`；发射第 n 元相位 e^{+jδn}
  在其 e^{+jψn} 核下峰值落 u=−δ/(2πd/λ)（互易对侧），取共轭后峰角与
  闭式 sinθ_k 同号对照（任务书预声明配对 δ_k ↔ +sinθ_k）。
- 线移相器组（45° 栅格）：(a1, b1, a2, b2) = (0°, 135°, 0°, 45°)。
  任务书示意值 {±45°, ±22.5°} 出自另一参考面约定；约定换算只差端口
  参考面（对角酉阵），物理波束性质逐项等价，本约定自洽钉死。

连线表（ASCII，信号左→右；◇=交叉结内对角交叉）::

    物理槽位(上→下)=B1,B3,B4,B2       线(上→下)=a1,b1,a2,b2
    B1 ─┤H_L1 ├─ a1 ─0°────────────────────(直通)──┤H_R1 上入
    B3 ─┤     ├─ b1 ─135°──╲                        │
                           ╳ (交叉结1: b1↔a2)
    B4 ─┤H_L2 ├─ a2 ──0°───╱──────(交叉到 H_R1 下入)─┤
    B2 ─┤     ├─ b2 ──45°──────────────(直通)───────┤H_R2 下入

    H_R1 上出 ────────────────────────────(直通)─── A1
    H_R2 上出 ──────────────╲
                             ╳ (交叉结2: RH2上出↔RH1下出)
    H_R1 下出 ──────────────╱────────────────────── A3
    H_R2 下出 ───────────────────────────────────── A4

闭式结果（主锚，45° 单位相位表 mod 8，行=波束口 B1..B4，列=天线 A1..A4）::

    B1: [0, 5, 2, 7]      δ_1 = −135°
    B2: [0, 7, 6, 5]      δ_2 =  −45°
    B3: [0, 1, 2, 3]      δ_3 =  +45°
    B4: [0, 3, 6, 1]      δ_4 = +135°

全部条目幅度恰为 1/2；总 8×8 S = [[0, S_ba], [S_baᵀ, 0]]（无耗、匹配、
互易：波束口间隔离与反射精确为 0——纯前馈网络无重反射）。

双路径（#118）：闭式层级合成 vs skrf Network 级联（:func:`build_butler_network`）
互证，预声明门 max|ΔS| ≤ 1e-9（条目 O(1)，abs=rel）。

边界登记（如实，2026-09-27）：N=8 泛化**未落**——8×8 经典 Butler 需要
22.5° 栅格移相器族（DFT 半槽偏移 e^{−j7πn/8} 不可吸附到 45° 栅格）与
8 端口连线拓扑的独立穷举搜索，本批超出 4×4 范围，登记为 4×4-only 边界；
本模块移相器接口（任意 φ）与连线表结构已为后续泛化留位，不构成对 8×8
可实现性的否定。

纯算法零 IO（skrf 仅在显式调用的级联路径内 import）；numpy 复矩阵进出。
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np

from rfauto.core.array_synthesis import array_factor

#: 波束口数（本模块钉死 4×4；8×8 为已登记边界，见模块 docstring）
N_BEAM_PORTS = 4

#: 预声明容差：双路径互证 / 无耗性 / 等幅（条目 O(1)，abs=rel 等价）
_TOL = 1e-9
#: 波束角预声明验收带（deg）
ANGLE_BAND_DEG = 1.0

#: 线移相器相位（45° 单位，mod 8），线序 (a1, b1, a2, b2)
_SHIFTER_UNITS = (0, 3, 0, 1)
#: 闭式相位表锚（45° 单位 mod 8）：行=波束口 1..4，列=天线 1..4
_S_PHASE_UNITS = ((0, 5, 2, 7), (0, 7, 6, 5), (0, 1, 2, 3), (0, 3, 6, 1))
#: 波束口 k（1..4）对应的物理槽位（上→下 1..4）
_BEAM_PORT_TO_SLOT = (1, 4, 2, 3)
#: 每列能量 / 双路径门同名常量导出（service 层复用）
TOL_LOSSLESS = _TOL
TOL_DUAL_PATH = _TOL


def _finite(value: float, name: str) -> float:
    """入参收敛为有限 float；bool 显式拒收（float(True)=1.0 静默污染，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _check_beam_port(beam_port: int) -> int:
    """波束口号收敛：1..4 整数（bool/浮点/越界显式报错，钉死不规范化）。"""
    if isinstance(beam_port, bool) or not isinstance(beam_port, (int, np.integer)):
        raise ValueError(f"beam_port 须为 1..4 整数，收到 {beam_port!r}")
    k = int(beam_port)
    if not 1 <= k <= N_BEAM_PORTS:
        raise ValueError(f"beam_port 须为 1..4，收到 {k}")
    return k


def _normalize_phase(phi_rad: float) -> float:
    """相位规范化到 [0, 2π)（钉死规范化而非报错）。"""
    phi = _finite(phi_rad, "phi_rad")
    two_pi = 2.0 * math.pi
    out = math.fmod(phi, two_pi)
    if out < 0.0:
        out += two_pi
    return out


def _u45(units: int | float) -> complex:
    """45° 单位整数相位的精确复指数（|·|=1）。"""
    return complex(np.exp(1j * math.pi / 4.0 * float(units % 8)))


# ─── 理想元件 S 矩阵 ─────────────────────────────────────────────────────────


def butler_hybrid_s_matrix() -> np.ndarray:
    """钉死约定下的理想 3 dB 90° 混合环 S 矩阵（4×4，端口序见模块 docstring）。

    S = (1/√2)·[[0, 1, j, 0], [1, 0, 0, 1], [j, 0, 0, −j], [0, 1, −j, 0]]。
    无耗、匹配、互易；隔离对 (1,4)、(2,3) 精确为零。
    """
    return (1.0 / math.sqrt(2.0)) * np.array(
        [
            [0, 1, 1j, 0],
            [1, 0, 0, 1],
            [1j, 0, 0, -1j],
            [0, 1, -1j, 0],
        ],
        dtype=complex,
    )


def butler_crossover_s_matrix() -> np.ndarray:
    """理想交叉结（crossover）S 矩阵（4×4 置换矩阵，内对角交叉、0 dB 直通）。"""
    return np.array(
        [
            [0, 0, 0, 1],
            [0, 0, 1, 0],
            [0, 1, 0, 0],
            [1, 0, 0, 0],
        ],
        dtype=complex,
    )


def butler_phase_shifter_s_matrix(phi_rad: float) -> np.ndarray:
    """理想移相器 S 矩阵（2×2）：``[[0, e^{jφ}], [e^{jφ}, 0]]``，φ 规范化到 [0, 2π)。"""
    e = np.exp(1j * _normalize_phase(phi_rad))
    return np.array([[0.0, e], [e, 0.0]], dtype=complex)


def butler_wiring_table() -> dict:
    """钉死连线表（JSON 可序列化 dict，与模块 docstring 连线图一致）。"""
    return {
        "beam_port_to_slot": {str(k): s for k, s in enumerate(_BEAM_PORT_TO_SLOT, start=1)},
        "left_hybrids": {
            "HL1": {"top_in": "slot1(B1)", "bottom_in": "slot2(B3)", "out_top": "a1", "out_bottom": "b1"},
            "HL2": {"top_in": "slot3(B4)", "bottom_in": "slot4(B2)", "out_top": "a2", "out_bottom": "b2"},
        },
        "line_shifters_deg": {"a1": _SHIFTER_UNITS[0] * 45.0, "b1": _SHIFTER_UNITS[1] * 45.0,
                              "a2": _SHIFTER_UNITS[2] * 45.0, "b2": _SHIFTER_UNITS[3] * 45.0},
        "crossover1": {"through": ["a1", "b2"], "crossed": [["b1", "a2"]]},
        "right_hybrid_inputs": {"HR1_top": "a1", "HR1_bottom": "a2", "HR2_top": "b1", "HR2_bottom": "b2"},
        "crossover2": {"through": [["HR1_top_out", "A1"], ["HR2_bottom_out", "A4"]],
                       "crossed": [["HR1_bottom_out", "A3"], ["HR2_top_out", "A2"]]},
        "antennas": {"A1": "HR1_top_out", "A2": "HR2_top_out", "A3": "HR1_bottom_out", "A4": "HR2_bottom_out"},
    }


# ─── 闭式路径：层级合成 ───────────────────────────────────────────────────────


def _block_diag2(m: np.ndarray) -> np.ndarray:
    out = np.zeros((4, 4), dtype=complex)
    out[:2, :2] = m
    out[2:, 2:] = m
    return out


def butler4_s_beam_to_antenna() -> np.ndarray:
    """闭式 4×4 波束口→天线口 S 矩阵（行=波束口 B1..B4，列=天线 A1..A4）。

    层级合成：左混合环层 → 线移相器层 → 交叉结1（内对角）→ 右混合环层 →
    交叉结2（输出内对角）。全部为酉阵/置换之积，逐条目幅度恰 1/2；
    与 45° 单位相位表锚 :data:`_S_PHASE_UNITS` 严格一致（#118 内部双路径）。
    """
    b = (1.0 / math.sqrt(2.0)) * np.array([[1, 1], [1j, -1j]], dtype=complex)
    left = _block_diag2(b)
    d_lines = np.diag([_u45(x) for x in _SHIFTER_UNITS])
    # RH 输入口序 (RH1上, RH1下, RH2上, RH2下) ← 线 (a1, a2, b1, b2)：交叉结1
    p_in = np.eye(4, dtype=complex)[[0, 2, 1, 3]]
    right = _block_diag2(b)
    # 天线序 (A1..A4) ← RH 输出 (RH1上, RH2上, RH1下, RH2下)：交叉结2
    p_out = np.zeros((4, 4), dtype=complex)
    for ant, rh_out in enumerate((0, 2, 1, 3)):
        p_out[ant, rh_out] = 1.0
    s = p_out @ right @ p_in @ d_lines @ left  # 列=波束口（物理槽位序 1..4）
    # 波束端口序钉死：端口 k = 物理槽位 _BEAM_PORT_TO_SLOT[k-1]（交错编排，见 docstring）
    sigma = [s_idx - 1 for s_idx in _BEAM_PORT_TO_SLOT]
    s_ba = s.T[sigma, :].copy()  # 行=波束口 B1..B4
    # 内部一致性守卫：与相位表锚逐位一致（45° 单位整数）
    ph = np.round(np.angle(s_ba) / (math.pi / 4.0)).astype(int) % 8
    if not np.array_equal(ph, np.array(_S_PHASE_UNITS, dtype=int)):  # pragma: no cover - 结构性守卫
        raise AssertionError("闭式层级合成与 45° 单位相位表锚不一致（内部错误）")
    return s_ba


def butler4_s_full() -> np.ndarray:
    """闭式全 8×8 S 矩阵，端口序 (B1..B4, A1..A4)。

    纯前馈无耗网络：``[[0, S_ba], [S_baᵀ, 0]]``——波束口/天线口自身反射
    与口间隔离精确为 0（闭式路径）。
    """
    s_ba = butler4_s_beam_to_antenna()
    out = np.zeros((8, 8), dtype=complex)
    out[:4, 4:] = s_ba
    out[4:, :4] = s_ba.T
    return out


# ─── skrf 级联路径 ────────────────────────────────────────────────────────────


def build_butler_network():
    """skrf Network 级联组装全 8 端口 Butler 网络（端口序 (B1..B4, A1..A4)）。

    组件：4×混合环 + 4×移相器 + 2×交叉结，按 :func:`butler_wiring_table`
    连线表逐口级联。skrf ``connect`` 语义=被连口处**原位拼接**新网络剩余口，
    端口标签簿记按此维护；``innerconnect`` 消化网络内部互连。单频点
    （f=1 GHz，数值与频率无关——全部元件为理想常数 S 矩阵）。

    Returns:
        skrf.Network：8 端口网络。
    """
    import skrf as rf  # 局部导入：core 其余路径零 skrf 依赖（afs.py 同族惯例）

    def _net(s, name):
        s = np.asarray(s, dtype=complex)
        return rf.Network(f=[1.0], f_unit="GHz", s=s.reshape(1, s.shape[0], s.shape[1]), name=name)

    def _shifter(deg):
        return _net(butler_phase_shifter_s_matrix(math.radians(deg)), f"shifter{deg:g}")

    sh_a1, sh_b1 = _shifter(0.0), _shifter(135.0)
    sh_a2, sh_b2 = _shifter(0.0), _shifter(45.0)
    hl1 = _net(butler_hybrid_s_matrix(), "HL1")
    hl2 = _net(butler_hybrid_s_matrix(), "HL2")
    crossover = _net(butler_crossover_s_matrix(), "crossover")
    hr1 = _net(butler_hybrid_s_matrix(), "HR1")
    hr2 = _net(butler_hybrid_s_matrix(), "HR2")

    # H_L1 端口 (0,1,2,3)=(左上入B1, 右上出a1, 右下出b1, 左下入B3)
    # H_L2 端口 (0,1,2,3)=(左上入B4, 右上出a2, 右下出b2, 左下入B2)
    cur = rf.network.concat_ports([hl1, hl2])
    # concat_ports 交错排列：[HL1.p0, HL2.p0, HL1.p1, HL2.p1, HL1.p2, HL2.p2, HL1.p3, HL2.p3]
    labels = ["B1", "B4", "a1", "a2", "b1", "b2", "B3", "B2"]

    def _join(label, other, other_remaining):
        """connect(cur, idx(label), other, 0)，按 skrf 实际端口序维护标签。

        skrf connect 端口序 = [A 剩余口] + [B 剩余口]（**追加**）；仅当 B 为
        2 端口且 A>2 端口时 skrf 再 renumber 把 B 剩余口**原位插回** k 处
        （connect 源码尾部 ``ntwkB.nports == 2`` 分支）。两种情形分别处理。
        """
        nonlocal cur
        idx = labels.index(label)
        cur = rf.network.connect(cur, idx, other, 0, 1)
        if other.nports == 2:
            labels[idx:idx + 1] = other_remaining
        else:
            labels[idx:idx + 1] = []
            labels.extend(other_remaining)

    def _inner(la, lb):
        """innerconnect：消化 cur 内部互连（两端口均为外部口）。

        理想无耗元件（对角零）下 skrf innerconnect 的节点方程可能报
        "Singular matrix, using lstsq"（运行时警告，非错误）；组装正确性
        由闭式双路径逐位门（#118）独立兜底，此处按 #105 精神就地降噪。
        """
        nonlocal cur
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*Singular matrix.*", category=RuntimeWarning)
            cur = rf.network.innerconnect(cur, labels.index(la), labels.index(lb), 1)
        labels[:] = [x for x in labels if x not in (la, lb)]

    # 线移相器串入各线起点（H_L 出口侧；理想移相器在无耗线上的位置不影响相位）
    _join("a1", sh_a1, ["a1"])
    _join("b1", sh_b1, ["b1"])
    _join("a2", sh_a2, ["a2"])
    _join("b2", sh_b2, ["b2"])
    # 交叉结1 端口 (0,1,2,3)=(左上, 左下, 右上, 右下)：左上←b1（交叉到右下），
    # 左下←a2（交叉到右上）
    _join("b1", crossover, ["X1.lb", "X1.rt", "X1.rb"])
    _inner("a2", "X1.lb")
    # H_R1 端口 (0,1,2,3)=(上入a1, 上出A1, 下出X2, 下入a2交叉线)
    _join("a1", hr1, ["HR1.ot", "HR1.ob", "HR1.ib"])
    # H_R2 端口 (0,1,2,3)=(上入b1交叉线, 上出X2, 下出A4, 下入b2)
    _join("X1.rb", hr2, ["HR2.ot", "HR2.ob", "HR2.ib"])
    _inner("HR1.ib", "X1.rt")
    _inner("b2", "HR2.ib")
    # 交叉结2：左上←HR1 下出，左下←HR2 上出；右上=X2.rt→A2，右下=X2.rb→A3
    _join("HR1.ob", crossover, ["X2.lb", "X2.rt", "X2.rb"])
    _inner("X2.lb", "HR2.ot")

    # 终态标签：B1, B3, B4, B2 波束口 + HR1.ot(=A1), HR2.ob(=A4), X2.rt(=A2), X2.rb(=A3)
    final = [lbl if lbl not in ("HR1.ot", "HR2.ob", "X2.rt", "X2.rb")
             else {"HR1.ot": "A1", "HR2.ob": "A4", "X2.rt": "A2", "X2.rb": "A3"}[lbl]
             for lbl in labels]
    order = ["B1", "B2", "B3", "B4", "A1", "A2", "A3", "A4"]
    if sorted(final) != sorted(order):  # pragma: no cover - 结构性守卫
        raise AssertionError(f"skrf 组装端口标签不符：{final!r}")
    idx = [final.index(x) for x in order]
    s8 = cur.s[:, idx, :][:, :, idx]
    out = rf.Network(f=cur.f, f_unit="GHz", s=s8, z0=cur.z0[:, idx], name="butler4")
    return out


def butler4_s_beam_to_antenna_skrf() -> np.ndarray:
    """skrf 级联路径的 4×4 波束口→天线口 S 矩阵（行=B1..B4，列=A1..A4）。"""
    return np.array(build_butler_network().s[0, :4, 4:], dtype=complex)


def butler4_s_full_skrf() -> np.ndarray:
    """skrf 级联路径的全 8×8 S 矩阵（端口序 (B1..B4, A1..A4)）。"""
    return np.array(build_butler_network().s[0], dtype=complex)


# ─── 波束指向验证面 ───────────────────────────────────────────────────────────


def beam_excitation(beam_port: int, s_ba: np.ndarray | None = None) -> np.ndarray:
    """波束口 k 的阵元激励向量（复权重，长度 4，= S_ba 第 k 行）。

    s_ba 缺省用闭式路径。幅度全部 1/2（等幅），相位按 δ_k 线性递进。
    """
    k = _check_beam_port(beam_port)
    s = butler4_s_beam_to_antenna() if s_ba is None else np.asarray(s_ba, dtype=complex)
    if s.shape != (N_BEAM_PORTS, N_BEAM_PORTS):
        raise ValueError(f"s_ba 形状须为 (4, 4)，收到 {s.shape}")
    return s[k - 1, :].copy()


def beam_angles_closed(spacing_lambda: float = 0.5) -> list[dict]:
    """各波束口闭式指向：sinθ_k = (k−(N+1)/2)·λ/(N·d)，δ_k = (2k−N−1)·π/N。

    返回 JSON 可序列化 list[dict]（beam_port / delta_deg / sin_theta / theta_deg）。
    |sinθ_k| ≥ 1（指向不可见区）显式报错。
    """
    d = _finite(spacing_lambda, "spacing_lambda")
    if d <= 0.0:
        raise ValueError("spacing_lambda 必须 >0")
    out = []
    for k in range(1, N_BEAM_PORTS + 1):
        sin_theta = (k - (N_BEAM_PORTS + 1) / 2.0) * 1.0 / (N_BEAM_PORTS * d)
        if abs(sin_theta) >= 1.0:
            raise ValueError(f"波束口 {k} 闭式指向 |sinθ|={abs(sin_theta):.4f} ≥ 1（不可见区，d 过小）")
        out.append({
            "beam_port": k,
            "delta_deg": math.degrees((2 * k - N_BEAM_PORTS - 1) * math.pi / N_BEAM_PORTS),
            "sin_theta": sin_theta,
            "theta_deg": math.degrees(math.asin(sin_theta)),
        })
    return out


def _wrap_deg(x: float) -> float:
    """角度差包装到 (−180, 180]。"""
    return (float(x) + 180.0) % 360.0 - 180.0


@dataclass(frozen=True)
class ButlerBeamReport:
    """波束指向验证报告（判据全部预声明，数值如实不凑绿）。

    判据（预声明）：
    - 相位递进：每波束口实测 δ vs 闭式 (2k−5)·45°，误差 ≤1e-9 deg（mod 360）；
    - 等幅：max||S|−0.5| ≤ 1e-9；
    - 无耗：每列 Σ|S_ij|² 偏离 1 ≤ 1e-9；
    - 隔离：skrf 全 8 口波束口间 |S_bb| max ≤ 1e-9（理想闭式精确 0）；
    - 双路径：max|S_skrf − S_闭式| ≤ 1e-9（#118 主判据）；
    - 波束角：AF argmax vs 闭式 asin(sinθ_k)，|误差| ≤ 1°。
    """

    spacing_lambda: float
    n_scan_points: int
    delta_closed_deg: tuple
    delta_measured_deg: tuple
    delta_error_deg: tuple
    sin_theta_closed: tuple
    theta_closed_deg: tuple
    theta_peak_deg: tuple
    angle_error_deg: tuple
    amplitude_max_dev: float
    column_energy_max_dev: float
    beam_isolation_max: float
    dual_path_max_absdiff: float
    angle_band_deg: float = ANGLE_BAND_DEG

    @property
    def all_pass(self) -> bool:
        return (
            max(abs(e) for e in self.delta_error_deg) <= _TOL
            and self.amplitude_max_dev <= _TOL
            and self.column_energy_max_dev <= _TOL
            and self.beam_isolation_max <= _TOL
            and self.dual_path_max_absdiff <= _TOL
            and max(abs(e) for e in self.angle_error_deg) <= self.angle_band_deg
        )

    def to_dict(self) -> dict:
        """JSON 可序列化 dict（float/tuple→list/bool）。"""
        return {
            "spacing_lambda": self.spacing_lambda,
            "n_scan_points": self.n_scan_points,
            "delta_closed_deg": list(self.delta_closed_deg),
            "delta_measured_deg": list(self.delta_measured_deg),
            "delta_error_deg": list(self.delta_error_deg),
            "sin_theta_closed": list(self.sin_theta_closed),
            "theta_closed_deg": list(self.theta_closed_deg),
            "theta_peak_deg": list(self.theta_peak_deg),
            "angle_error_deg": list(self.angle_error_deg),
            "amplitude_max_dev": self.amplitude_max_dev,
            "column_energy_max_dev": self.column_energy_max_dev,
            "beam_isolation_max": self.beam_isolation_max,
            "dual_path_max_absdiff": self.dual_path_max_absdiff,
            "angle_band_deg": self.angle_band_deg,
            "all_pass": self.all_pass,
        }


def verify_beam_steering(spacing_lambda: float = 0.5, n_points: int = 3601) -> ButlerBeamReport:
    """波束指向端到端验证：双路径互证 + 阵元激励 + AF 数值扫角 vs 闭式指向。

    波束方向图用 :func:`rfauto.core.array_synthesis.array_factor`（4 元阵、
    间距 d 显式参数），激励取共轭权重（接收式惯例，见模块 docstring 配对
    约定；复权重按线性拆分为 Re/Im 两次实权重调用），在 u=sinθ 可见区数值
    扫角取 |AF| argmax，与闭式 asin(sinθ_k) 对照（预声明 ±1° 带）。
    """
    d = _finite(spacing_lambda, "spacing_lambda")
    if d <= 0.0:
        raise ValueError("spacing_lambda 必须 >0")
    if isinstance(n_points, bool) or not isinstance(n_points, (int, np.integer)) or n_points < 1001:
        raise ValueError(f"n_points 须为 ≥1001 的整数，收到 {n_points!r}")
    n_points = int(n_points)

    s_closed = butler4_s_beam_to_antenna()
    s_skrf = butler4_s_beam_to_antenna_skrf()
    s_full_skrf = butler4_s_full_skrf()

    # 相位递进：闭式 vs 实测（闭式路径行相位差，mod 360 圆误差）
    delta_closed = tuple(
        _wrap_deg((2 * k - N_BEAM_PORTS - 1) * 180.0 / N_BEAM_PORTS) for k in range(1, N_BEAM_PORTS + 1)
    )
    delta_measured = tuple(
        _wrap_deg(np.degrees(np.angle(s_closed[k, 1] / s_closed[k, 0]))) for k in range(N_BEAM_PORTS)
    )
    delta_error = tuple(_wrap_deg(m - c) for m, c in zip(delta_measured, delta_closed, strict=True))

    # 等幅 + 无耗
    amplitude_max_dev = float(np.max(np.abs(np.abs(s_closed) - 0.5)))
    column_energy_max_dev = float(np.max(np.abs(np.sum(np.abs(s_closed) ** 2, axis=1) - 1.0)))

    # 波束口间隔离（skrf 全 8 口波束口块；理想闭式精确 0，如实报实测值）
    beam_isolation_max = float(np.max(np.abs(s_full_skrf[:4, :4])))

    # 双路径互证（#118 主判据）
    dual_path_max_absdiff = float(np.max(np.abs(s_skrf - s_closed)))

    # 数值扫角
    closed = beam_angles_closed(d)
    u_max = math.sin(math.radians(89.9))
    u_grid = np.linspace(-u_max, u_max, n_points)
    sin_theta_closed, theta_closed, theta_peak, angle_error = [], [], [], []
    for k in range(1, N_BEAM_PORTS + 1):
        w = beam_excitation(k, s_closed)
        # 指向约定（钉死）：波束指向文献标准口径=激励取导向矢量共轭（接收式
        # 权重）。发射激励第 n 元相位 e^{+jδn} 在 array_factor 的 e^{+jψn} 核下
        # 峰值落 u=−δ/(2πd/λ)（互易的对侧来波方向）；取共轭后峰角与闭式
        # sinθ_k = δ_k·λ/(2πd) 同号对照（任务书预声明配对 δ_k ↔ +sinθ_k）。
        # array_factor 只收实权重（内部 dtype=float 截断虚部）；复权重按线性拆分：
        # Σ w_n e^{jψn} = Σ Re(w_n) e^{jψn} + j·Σ Im(w_n) e^{jψn}
        wc = np.conj(w)
        af = array_factor(u_grid, wc.real, spacing_lambda=d, scan_direction_cosine=0.0, normalize=False)
        af = af + 1j * array_factor(u_grid, wc.imag, spacing_lambda=d, scan_direction_cosine=0.0, normalize=False)
        u_peak = float(u_grid[int(np.argmax(np.abs(af)))])
        theta_pk = math.degrees(math.asin(max(-1.0, min(1.0, u_peak))))
        sin_theta_closed.append(closed[k - 1]["sin_theta"])
        theta_closed.append(closed[k - 1]["theta_deg"])
        theta_peak.append(theta_pk)
        angle_error.append(theta_pk - closed[k - 1]["theta_deg"])

    return ButlerBeamReport(
        spacing_lambda=d,
        n_scan_points=n_points,
        delta_closed_deg=delta_closed,
        delta_measured_deg=delta_measured,
        delta_error_deg=delta_error,
        sin_theta_closed=tuple(sin_theta_closed),
        theta_closed_deg=tuple(theta_closed),
        theta_peak_deg=tuple(theta_peak),
        angle_error_deg=tuple(angle_error),
        amplitude_max_dev=amplitude_max_dev,
        column_energy_max_dev=column_energy_max_dev,
        beam_isolation_max=beam_isolation_max,
        dual_path_max_absdiff=dual_path_max_absdiff,
    )
