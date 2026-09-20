"""A8 MAPES stage-1 定向单元测试（确定性、无网络、无真机依赖）。

覆盖验证点：
1. 原文端口数公式参考实现（paper_port_count，仅作对照，不冒充 stage-1 约定）；
2. 尺寸一致性：布局端口编号/数量与 :class:`PixelLayout` 约定一致；
3. 占位映射：同一 `topology_key` 的展平 bool 与矩阵往返；
4. 占用→对角负载映射（逐像素口：缺席=开路 inf、在场=短路 0；
   耦合口 = 两端像素 AND）；
5. Schur 补闭式 vs **独立直接线性求解**（节点法 Kirchhoff 全节点方程组）；
6. 开路/短路退化解析极限（全开路 = Z_EE；T 网解析 Z_ext）；
7. `Z→S` 单口解析锚；
8. 互易性/无源性（合成 Z_ALL 与外端口 S）；
9. 非法输入显式报错；
10. 批量图案确定性、顺序无关；
11. predict(params)->metrics 平铺契约（E3 同构）；
12. I/O 去耦物理不变量（短路 I/O 端口全部直接邻居 ⇒ 与全短路等价）。

实测偏差（本文件断言阈值的依据，2026-09-12 本机 .venv，4x4 布局 Q=60）：
- Schur 闭式 vs 独立节点法 max|ΔS|：4x4 十二组图案（全空/全占/棋盘/一行 +
  8 组随机）×（开路-短路混合 + 有限阻抗）实测 **9.01e-16**；
  6x6 四代表图案 **7.96e-16**；本题断言阈值 1e-12。
- 全开路退化 `Z_ext - Z_EE` 实测 **0.0**（精确）。
- 合成 Z_ALL 互易误差 `max|Z - Z^T|` 实测 **8.95e-16**，
  `min eig Re(Z)` 实测 **+0.1336**（>0 → 无源）。

公式来源：src/rfauto/core/mapes.py 模块 docstring（原文实读与借鉴
整理见该 docstring）。stage-1 的像素域编号约定是
本仓自定（原文 Fig. 端口格点未复刻，见 honest notes），故不编造原文数值。
"""

from __future__ import annotations

from functools import cache

import numpy as np
import pytest

from rfauto.core.errors import ConfigError
from rfauto.core.mapes import (
    CATEGORY_DIAG_ANTI,
    CATEGORY_DIAG_MAIN,
    CATEGORY_PIXEL,
    CATEGORY_PIXEL_H,
    CATEGORY_PIXEL_V,
    VIA_GROUND,
    VIA_INTERLAYER,
    MapesModel,
    PixelLayout,
    dft_time2freq,
    fake_mesh,
    fit_alpha_scaling,
    load_network_z,
    nodal_reference_s,
    occupancy_to_load,
    paper_port_count,
    port_gamma,
    wave_decompose_ui,
    z_to_s,
)

FREQ_HZ = 2.5e9
Z0 = 50.0
SCHUR_VS_NODAL_TOL = 1.0e-12

LAYOUT_4 = PixelLayout(n_rows=4, n_cols=4, n_io_ports=2)

CHECKERBOARD_4 = (np.add.outer(np.arange(4), np.arange(4)) % 2 == 0)
ONE_ROW_4 = np.zeros((4, 4), dtype=bool)
ONE_ROW_4[2, :] = True


@cache
def _mesh(n_ports: int):
    return fake_mesh(n_ports)


@cache
def _z_all(n_ports: int, freq_hz: float) -> np.ndarray:
    return _mesh(n_ports).z_all(freq_hz)


def _s_from_schur(z_all: np.ndarray, loads: np.ndarray) -> np.ndarray:
    return z_to_s(load_network_z(z_all, n_io=2, load_impedances=loads))


def _random_patterns(count: int, size: int = 4, seed: int = 20260912) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    return [
        rng.integers(0, 2, size=(size, size)).astype(bool)
        for _ in range(count)
    ]


# --------------------------------------------------------------------------- #
# 1. 原文端口数公式（参考对照）
# --------------------------------------------------------------------------- #

def test_paper_port_count_reference_formula() -> None:
    assert paper_port_count(1, 1, 1) == 4
    assert paper_port_count(2, 2, 1) == 16
    assert paper_port_count(3, 3, 1) == 40
    assert paper_port_count(2, 3, 1) == 25
    # L(6MN-3M-3N+4) + (L-1)MN
    assert paper_port_count(1, 1, 2) == 9
    assert paper_port_count(2, 2, 2) == 16 * 2 + 4
    with pytest.raises(ConfigError):
        paper_port_count(0, 3)
    with pytest.raises(ConfigError):
        paper_port_count(3, 3, 0)


# --------------------------------------------------------------------------- #
# 2. 尺寸一致性 / 端口编号
# --------------------------------------------------------------------------- #

def test_layout_port_numbering_and_sizes() -> None:
    # 4x4：pixel=4*4=16、h=4*3=12、v=3*4=12、diag=3*3=9 x2 → 58 加载口
    assert LAYOUT_4.n_load_ports == 58
    assert LAYOUT_4.n_ports == 60
    cats = LAYOUT_4.slot_categories()
    assert len(cats) == LAYOUT_4.n_load_ports
    assert cats.count(CATEGORY_PIXEL) == 16
    assert cats.count(CATEGORY_PIXEL_H) == 12
    assert cats.count(CATEGORY_PIXEL_V) == 12
    assert cats.count(CATEGORY_DIAG_MAIN) == 9
    assert cats.count(CATEGORY_DIAG_ANTI) == 9
    # 槽位标签唯一、顺序稳定：逐像素口在最前
    labels = [slot.label for slot in LAYOUT_4.load_slots()]
    assert len(set(labels)) == len(labels)
    assert labels[:2] == ["px_r0_c0", "px_r0_c1"]


def test_layout_with_vias_extends_port_set() -> None:
    layout = PixelLayout(
        n_rows=3, n_cols=3, n_layers=2, n_io_ports=2,
        via_slots=((0, 0, VIA_GROUND), (1, 1, VIA_INTERLAYER)))
    base = PixelLayout(n_rows=3, n_cols=3, n_layers=2, n_io_ports=2)
    assert base.n_load_ports == 3 * 3 + 3 * 2 + 2 * 3 + 2 * 2 * 2  # 9+6+6+8 = 29
    assert layout.n_load_ports == base.n_load_ports + 2
    assert layout.topology_key != base.topology_key
    categories = layout.slot_categories()
    assert categories[-2:] == (VIA_GROUND, VIA_INTERLAYER)


def test_model_rejects_port_count_mismatch() -> None:
    z_wrong = np.eye(LAYOUT_4.n_ports - 1, dtype=complex) * Z0
    with pytest.raises(ConfigError):
        MapesModel(LAYOUT_4, z_wrong, FREQ_HZ)


# --------------------------------------------------------------------------- #
# 3. 占位映射往返（topology_key + 展平 bool）
# --------------------------------------------------------------------------- #

def test_flatten_unflatten_roundtrip_same_topology_key() -> None:
    layout = PixelLayout(
        n_rows=3, n_cols=3, n_layers=2, n_io_ports=2,
        via_slots=((0, 0, VIA_GROUND), (1, 1, VIA_INTERLAYER)))
    pattern = np.array([[True, False, True],
                        [False, True, False],
                        [True, True, False]])
    vias = np.array([True, False])
    params = layout.flatten(pattern, vias)
    assert params["topology_key"] == layout.topology_key
    assert params["occ0_0"] == 1.0
    assert params["occ0_1"] == 0.0
    assert params["via1"] == 0.0
    assert all(isinstance(v, float) for k, v in params.items() if k != "topology_key")
    pattern_back, vias_back = layout.unflatten(params)
    assert np.array_equal(pattern, pattern_back)
    assert np.array_equal(vias, vias_back)


def test_unflatten_rejects_foreign_topology_key_and_bad_values() -> None:
    other = PixelLayout(n_rows=4, n_cols=5, n_io_ports=2)
    params = LAYOUT_4.flatten(np.ones((4, 4), dtype=bool))
    with pytest.raises(ConfigError):
        other.unflatten(params)  # topology_key 不符
    params_bad = dict(params)
    params_bad["occ0_0"] = 2.0
    with pytest.raises(ConfigError):
        LAYOUT_4.unflatten(params_bad)
    params_missing = dict(params)
    del params_missing["occ2_2"]
    with pytest.raises(ConfigError):
        LAYOUT_4.unflatten(params_missing)
    params_extra = dict(params)
    params_extra["occ9_9"] = 1.0
    with pytest.raises(ConfigError):
        LAYOUT_4.unflatten(params_extra)
    with pytest.raises(ConfigError):
        LAYOUT_4.unflatten(["not", "a", "dict"])


# --------------------------------------------------------------------------- #
# 4. 占用→对角负载映射
# --------------------------------------------------------------------------- #

def test_occupancy_to_load_mapping_single_pixel() -> None:
    layout = PixelLayout(n_rows=2, n_cols=2, n_io_ports=1)
    pattern = np.array([[True, False], [False, False]])
    states = layout.slot_occupancy(pattern)
    # 槽序：px(0,0), px(0,1), px(1,0), px(1,1), h(0,0), h(1,0),
    #       v(0,0), v(0,1), dm(0,0), da(0,0)
    assert list(states) == [True, False, False, False,
                            False, False, False, False, False, False]
    loads = occupancy_to_load(pattern, layout)
    finite = np.isfinite(loads)
    assert list(finite) == list(states)
    assert np.all(loads[finite] == 0.0)
    assert np.all(np.isinf(loads[~finite]))


def test_occupancy_to_load_is_and_of_endpoints() -> None:
    """耦合槽 = 两端像素同时在场（AND）；对角槽单独验证。"""
    layout = PixelLayout(n_rows=2, n_cols=2, n_io_ports=1)
    # 槽序：px(0,0), px(0,1), px(1,0), px(1,1), h(0,0), h(1,0),
    #       v(0,0), v(0,1), dm(0,0), da(0,0)
    diagonal = np.array([[True, False], [False, True]])
    assert list(layout.slot_occupancy(diagonal)) == [
        True, False, False, True, False, False, False, False, True, False]
    corner = np.array([[True, True], [True, False]])
    assert list(layout.slot_occupancy(corner)) == [
        True, True, True, False, True, False, True, False, False, True]
    # 单像素在场：只有它自己的占位口短路，无相邻像素 → 无耦合口点亮
    single = np.array([[True, False], [False, False]])
    assert list(layout.slot_occupancy(single)) == [
        True, False, False, False, False, False, False, False, False, False]


def test_occupancy_rejects_bad_shape_and_values() -> None:
    with pytest.raises(ConfigError):
        LAYOUT_4.slot_occupancy(np.ones((4, 5), dtype=bool))
    with pytest.raises(ConfigError):
        LAYOUT_4.slot_occupancy(np.full((4, 4), 3))
    with pytest.raises(ConfigError):
        occupancy_to_load(np.ones((4, 4), dtype=bool), "not-a-layout")
    via_layout = PixelLayout(3, 3, 1, 2, ((0, 0, VIA_GROUND),))
    with pytest.raises(ConfigError):
        via_layout.slot_occupancy(np.ones((3, 3), bool))  # 缺 vias
    with pytest.raises(ConfigError):
        via_layout.slot_occupancy(np.ones((3, 3), bool), np.array([2]))


# --------------------------------------------------------------------------- #
# 5. Schur 闭式 vs 独立直接线性求解
# --------------------------------------------------------------------------- #

def test_schur_closed_form_matches_independent_nodal_solve() -> None:
    """核心裁判：闭式 Schur 补 vs 全节点 Kirchhoff 直接解（两条独立路径）。"""
    mesh = _mesh(LAYOUT_4.n_ports)
    z_all = _z_all(LAYOUT_4.n_ports, FREQ_HZ)
    patterns = [
        np.zeros((4, 4), dtype=bool),
        np.ones((4, 4), dtype=bool),
        CHECKERBOARD_4,
        ONE_ROW_4,
        *_random_patterns(8),
    ]
    worst = 0.0
    for pattern in patterns:
        loads = occupancy_to_load(pattern, LAYOUT_4)
        # (a) 开路/短路混合负载
        s_schur = _s_from_schur(z_all, loads)
        s_ref = mesh.reference_s(n_io=2, load_impedances=loads, freq_hz=FREQ_HZ)
        worst = max(worst, float(np.max(np.abs(s_schur - s_ref))))
        # (b) 有限负载（rho=10Ω 与 5kΩ 混合）
        finite_loads = np.where(np.isfinite(loads), 10.0 + 0.0j, 5000.0 + 0.0j)
        s_schur_f = _s_from_schur(z_all, finite_loads)
        s_ref_f = mesh.reference_s(n_io=2, load_impedances=finite_loads, freq_hz=FREQ_HZ)
        worst = max(worst, float(np.max(np.abs(s_schur_f - s_ref_f))))
    # 两种负载口径（开路/短路混合 + 有限阻抗）都在同一次扫描里比较
    assert worst < SCHUR_VS_NODAL_TOL, f"max|ΔS|={worst:.3e} 超过阈值"


@pytest.mark.parametrize("pattern_name", ["all_empty", "all_full", "checkerboard", "one_row"])
def test_schur_vs_nodal_for_representative_patterns(pattern_name: str) -> None:
    patterns = {
        "all_empty": np.zeros((4, 4), dtype=bool),
        "all_full": np.ones((4, 4), dtype=bool),
        "checkerboard": CHECKERBOARD_4,
        "one_row": ONE_ROW_4,
    }
    mesh = _mesh(LAYOUT_4.n_ports)
    z_all = _z_all(LAYOUT_4.n_ports, FREQ_HZ)
    loads = occupancy_to_load(patterns[pattern_name], LAYOUT_4)
    s_schur = _s_from_schur(z_all, loads)
    s_ref = mesh.reference_s(n_io=2, load_impedances=loads, freq_hz=FREQ_HZ)
    np.testing.assert_allclose(s_schur, s_ref, atol=SCHUR_VS_NODAL_TOL, rtol=0.0)


def test_nodal_reference_matches_single_node_analytic() -> None:
    """裁判自身的解析锚：单节点并联阻抗 z → S11=(z-z0)/(z+z0)。"""
    z = 120.0 + 40.0j
    y = np.array([[1.0 / z]], dtype=complex)
    s = nodal_reference_s(y, n_io=1)
    assert abs(s[0, 0] - (z - Z0) / (z + Z0)) < 1.0e-12
    # 与 Z→S 闭式一致
    assert abs(s[0, 0] - z_to_s(np.array([[z]]))[0, 0]) < 1.0e-12


# --------------------------------------------------------------------------- #
# 6. 开路/短路退化解析极限
# --------------------------------------------------------------------------- #

def test_all_open_limit_equals_z_ee() -> None:
    z_all = _z_all(LAYOUT_4.n_ports, FREQ_HZ)
    loads = occupancy_to_load(np.zeros((4, 4), dtype=bool), LAYOUT_4)
    assert np.all(~np.isfinite(loads))  # 全开路
    z_ext = load_network_z(z_all, n_io=2, load_impedances=loads)
    diff = float(np.max(np.abs(z_ext - z_all[:2, :2])))
    assert diff == 0.0, f"全开路应精确等于 Z_EE，实得 {diff:.3e}"


def test_all_short_against_t_network_analytic() -> None:
    """T 网解析：外部 1/2 经 Zs 到内部节点 3，节点 3 对地 Zp。

    - 内部节点开路（全开路）→ Z_ext = [[Zs+Zp, Zp], [Zp, Zs+Zp]]；
    - 内部节点短路（全短路）→ Z_ext = [[Zs, 0], [0, Zs]]。
    """
    zs = 30.0 + 12.0j
    zp = 80.0 - 25.0j
    y = np.array([
        [1.0 / zs, 0.0, -1.0 / zs],
        [0.0, 1.0 / zs, -1.0 / zs],
        [-1.0 / zs, -1.0 / zs, 2.0 / zs + 1.0 / zp],
    ], dtype=complex)
    z_all = np.linalg.inv(y)
    z_open = load_network_z(z_all, n_io=2, load_impedances=[np.inf])
    np.testing.assert_allclose(
        z_open, np.array([[zs + zp, zp], [zp, zs + zp]]), atol=1.0e-9, rtol=0.0)
    z_short = load_network_z(z_all, n_io=2, load_impedances=[0.0])
    np.testing.assert_allclose(
        z_short, np.array([[zs, 0.0], [0.0, zs]]), atol=1.0e-9, rtol=0.0)


def test_z_to_s_single_port_analytic() -> None:
    assert abs(z_to_s(np.array([[Z0]], dtype=complex))[0, 0]) < 1.0e-15
    assert abs(z_to_s(np.array([[0.0]], dtype=complex))[0, 0] + 1.0) < 1.0e-15
    assert abs(z_to_s(np.array([[1j * Z0]], dtype=complex))[0, 0] - 1j) < 1.0e-15


def test_shorting_io_neighbour_ports_decouples_external_ports() -> None:
    """物理不变量：短路 I/O 端口的全部直接邻居虚拟端口 ⇒ 与全短路等价。

    节点网络里若外部端口的每个直接邻居都被接地，外部端口即与其余网络
    去耦（只剩本地并联支路）——故任何满足该条件的图案都给出与全占用相同
    的外端口 Z/S（demo 中棋盘恰好命中）。去掉任一邻居则不再等价。
    """
    mesh = _mesh(LAYOUT_4.n_ports)
    z_all = _z_all(LAYOUT_4.n_ports, FREQ_HZ)
    n_io = LAYOUT_4.n_io_ports
    neighbours = set()
    for i, j in mesh.edges:
        if i < n_io <= j:
            neighbours.add(j)
        if j < n_io <= i:
            neighbours.add(i)
    slots = sorted(node - n_io for node in neighbours)
    assert len(slots) >= 2, f"外部端口直接邻居只有 {slots}"
    n_load = LAYOUT_4.n_load_ports
    all_short = np.zeros(n_load, dtype=complex)
    only_neighbours = np.full(n_load, np.inf, dtype=complex)
    only_neighbours[slots] = 0.0
    z_nb = load_network_z(z_all, n_io=n_io, load_impedances=only_neighbours)
    z_short = load_network_z(z_all, n_io=n_io, load_impedances=all_short)
    np.testing.assert_allclose(z_nb, z_short, atol=1.0e-12, rtol=0.0)
    partial = np.full(n_load, np.inf, dtype=complex)
    partial[slots[1:]] = 0.0
    z_partial = load_network_z(z_all, n_io=n_io, load_impedances=partial)
    assert float(np.max(np.abs(z_partial - z_short))) > 1.0e-3
    # 该子集结果同样经独立节点法复核
    np.testing.assert_allclose(
        z_to_s(z_nb),
        mesh.reference_s(n_io=n_io, load_impedances=only_neighbours, freq_hz=FREQ_HZ),
        atol=SCHUR_VS_NODAL_TOL, rtol=0.0)


# --------------------------------------------------------------------------- #
# 7. 互易性 / 无源性
# --------------------------------------------------------------------------- #

def test_synthetic_z_all_is_reciprocal_and_passive() -> None:
    z_all = _z_all(LAYOUT_4.n_ports, FREQ_HZ)
    assert float(np.max(np.abs(z_all - z_all.T))) < 1.0e-10
    herm = (z_all + z_all.conj().T) / 2.0
    assert float(np.min(np.linalg.eigvalsh(herm))) > 0.0  # Re(Z) 正定 → 无源


def test_external_s_reciprocal_and_passive_over_patterns() -> None:
    mesh = _mesh(LAYOUT_4.n_ports)
    z_all = _z_all(LAYOUT_4.n_ports, FREQ_HZ)
    for pattern in [np.zeros((4, 4), bool), np.ones((4, 4), bool),
                    CHECKERBOARD_4, ONE_ROW_4, *_random_patterns(4)]:
        loads = occupancy_to_load(pattern, LAYOUT_4)
        s = _s_from_schur(z_all, loads)
        assert float(np.max(np.abs(s - s.T))) < 1.0e-12
        assert float(np.max(np.linalg.norm(s, ord=2))) <= 1.0 + 1.0e-9
        # 独立节点法同样满足无源
        s_ref = mesh.reference_s(n_io=2, load_impedances=loads, freq_hz=FREQ_HZ)
        assert float(np.max(np.linalg.norm(s_ref, ord=2))) <= 1.0 + 1.0e-9


# --------------------------------------------------------------------------- #
# 8. 批量图案确定性 / 顺序无关
# --------------------------------------------------------------------------- #

def test_batch_patterns_deterministic_and_order_independent() -> None:
    freqs = np.array([1.0e9, 2.5e9, 5.0e9])
    mesh = _mesh(LAYOUT_4.n_ports)
    z_stack = np.stack([mesh.z_all(f) for f in freqs])
    model = MapesModel(LAYOUT_4, z_stack, freqs)
    patterns = [np.zeros((4, 4), bool), np.ones((4, 4), bool), CHECKERBOARD_4, ONE_ROW_4]
    forward = [model.predict(LAYOUT_4.flatten(p)) for p in patterns]
    backward = [model.predict(LAYOUT_4.flatten(p)) for p in reversed(patterns)]
    for i, metrics in enumerate(forward):
        assert metrics == backward[len(patterns) - 1 - i]
    # 重复求值逐位相同
    again = [model.predict(LAYOUT_4.flatten(p)) for p in patterns]
    assert forward == again
    # 结果确实随图案变化（不是常数占位）
    assert forward[0]["s11_db_min"] != forward[1]["s11_db_min"]


# --------------------------------------------------------------------------- #
# 9. predict 平铺契约 / 全链
# --------------------------------------------------------------------------- #

def test_predict_flat_contract_and_chain() -> None:
    freqs = np.array([1.0e9, 2.5e9, 5.0e9])
    mesh = _mesh(LAYOUT_4.n_ports)
    model = MapesModel(LAYOUT_4, np.stack([mesh.z_all(f) for f in freqs]), freqs)
    assert model.KIND == "mapes_pixel_analytic"
    assert model.topology_key == LAYOUT_4.topology_key
    assert model.uncertainty(LAYOUT_4.flatten(CHECKERBOARD_4)) is None
    metrics = model.predict(LAYOUT_4.flatten(CHECKERBOARD_4))
    assert isinstance(metrics, dict)
    assert all(isinstance(v, float) for v in metrics.values())
    for key in ("s11_db_at_fc", "s21_db_at_fc", "s12_db_at_fc", "s22_db_at_fc",
                "s11_db_min", "s21_db_min", "passive_margin", "reciprocity_err"):
        assert key in metrics
    assert metrics["passive_margin"] >= -1.0e-9
    assert metrics["reciprocity_err"] < 1.0e-12


def test_model_single_frequency_and_full_s_matrix_shape() -> None:
    model = MapesModel(LAYOUT_4, _z_all(LAYOUT_4.n_ports, FREQ_HZ), FREQ_HZ)
    result = model.evaluate(LAYOUT_4.flatten(ONE_ROW_4))
    assert result.s_external.shape == (1, 2, 2)
    assert result.z_external.shape == (1, 2, 2)
    summary = result.summary()
    assert summary["n_freq"] == 1
    assert summary["n_io"] == 2
    assert summary["n_occupied_slots"] == int(np.count_nonzero(np.isfinite(result.load_impedance)))
    assert summary["n_open_slots"] == LAYOUT_4.n_load_ports - summary["n_occupied_slots"]


def test_model_frequency_axis_validation() -> None:
    mesh = _mesh(LAYOUT_4.n_ports)
    z_stack = np.stack([mesh.z_all(1e9), mesh.z_all(2e9)])
    with pytest.raises(ConfigError):
        MapesModel(LAYOUT_4, z_stack, np.array([1e9]))  # 频点数不符
    with pytest.raises(ConfigError):
        MapesModel(LAYOUT_4, z_stack, np.array([1e9, 2e9, 3e9]))
    with pytest.raises(ConfigError):
        MapesModel(LAYOUT_4, _z_all(LAYOUT_4.n_ports, 1e9), np.array([1e9, 2e9]))


# --------------------------------------------------------------------------- #
# 10. 非法输入显式报错
# --------------------------------------------------------------------------- #

def test_layout_validation_errors() -> None:
    with pytest.raises(ConfigError):
        PixelLayout(0, 3)
    with pytest.raises(ConfigError):
        PixelLayout(3, 3, n_layers=0)
    with pytest.raises(ConfigError):
        PixelLayout(3, 3, n_io_ports=0)
    with pytest.raises(ConfigError):
        PixelLayout(3, 3, via_slots=((5, 0, VIA_GROUND),))  # 越界
    with pytest.raises(ConfigError):
        PixelLayout(3, 3, via_slots=((0, 0, "via_magic"),))  # 未知种类
    with pytest.raises(ConfigError):
        PixelLayout(3, 3, n_layers=1, via_slots=((0, 0, VIA_INTERLAYER),))
    # 1x1 是合法退化：只有一个逐像素占位口
    tiny = PixelLayout(1, 1, n_io_ports=2)
    assert tiny.n_load_ports == 1
    assert tiny.n_ports == 3
    with pytest.raises(ConfigError):
        PixelLayout(3, 3, via_slots=((0, 0),))  # 不是三元组


def test_kernel_and_grid_validation_errors() -> None:
    z_all = _z_all(LAYOUT_4.n_ports, FREQ_HZ)
    with pytest.raises(ConfigError):
        load_network_z(np.ones((3, 4), dtype=complex), n_io=1, load_impedances=[0.0])
    with pytest.raises(ConfigError):
        load_network_z(z_all, n_io=0, load_impedances=[])
    with pytest.raises(ConfigError):
        load_network_z(z_all, n_io=2, load_impedances=[0.0])  # 长度不符
    with pytest.raises(ConfigError):
        z_to_s(np.ones((3, 4), dtype=complex))
    with pytest.raises(ConfigError):
        z_to_s(np.eye(2, dtype=complex), reference_impedance=0.0)
    with pytest.raises(ConfigError):
        nodal_reference_s(np.eye(3, dtype=complex), n_io=4, load_impedances=[])
    with pytest.raises(ConfigError):
        nodal_reference_s(np.eye(3, dtype=complex), n_io=1, load_impedances=[0.0])
    with pytest.raises(ConfigError):
        fake_mesh(0)
    with pytest.raises(ConfigError):
        _mesh(4).nodal_admittance(-1.0)


def test_fake_mesh_is_deterministic_and_frequency_dependent() -> None:
    assert fake_mesh(6) == fake_mesh(6)
    z1 = _z_all(6, 1.0e9)
    z2 = _z_all(6, 2.5e9)
    assert not np.allclose(z1, z2)
    assert float(np.max(np.abs(z1 - z1.T))) < 1.0e-12


# ─── stage-4：openEMS 波分解复刻帮手（离线 Γ 诊断内核，零仿真）─────────────

def test_dft_time2freq_matches_closed_form_on_centered_bin() -> None:
    fs, n, k0 = 1000.0, 4096, 37
    t = np.arange(n) / fs
    f0 = k0 * fs / n  # 恰落在 DFT 频箱上 → 泄漏为 0
    amp, phase = 0.7, 0.9
    v = amp * np.cos(2.0 * np.pi * f0 * t + phase)
    fv = dft_time2freq(t, v, [f0])
    # Σ cos(ωt+φ)e^{-jωt} = (N/2)e^{jφ}；F = 2·dt·N/2·A·e^{jφ} = N·dt·A·e^{jφ}
    expect = n / fs * amp * np.exp(1j * phase)
    assert abs(fv[0] - expect) < 1e-8


def test_dft_time2freq_rejects_bad_input() -> None:
    t = np.linspace(0.0, 1e-6, 32)
    with pytest.raises(ConfigError):
        dft_time2freq(t[:-1], t, [1e9])
    with pytest.raises(ConfigError):
        dft_time2freq(t, t, [-1.0])
    with pytest.raises(ConfigError):
        dft_time2freq(t[::-1], t, [1e9])  # 时间轴必须递增


def test_wave_decompose_ui_anchor_matched_open_short_half() -> None:
    z0 = 50.0
    u = np.array([1.0 + 0.5j, -0.3 + 0.2j])
    # 匹配：i = u/Z0 → 全吸收（uf_ref=if_ref=0，Γ=0）
    dec = wave_decompose_ui(u, u / z0, reference_impedance=z0)
    assert float(np.max(np.abs(dec["uf_ref"]))) == pytest.approx(0.0, abs=1e-15)
    assert float(np.max(np.abs(port_gamma(u, u / z0, reference_impedance=z0)))) == \
        pytest.approx(0.0, abs=1e-15)
    # 开路：i=0 → Γ=+1（a=b）
    dec = wave_decompose_ui(u, np.zeros(2, dtype=complex), reference_impedance=z0)
    assert float(np.max(np.abs(dec["uf_ref"] - dec["uf_inc"]))) == \
        pytest.approx(0.0, abs=1e-15)
    # 短路：u=0 → Γ=−1（a=−b）
    g = port_gamma(np.zeros(2, dtype=complex), u, reference_impedance=z0)
    assert float(np.max(np.abs(g + 1.0))) == pytest.approx(0.0, abs=1e-15)
    # Γ=0.5 合成锚：u_inc=1 → u_tot=1.5、i_tot=0.5/Z0
    g = port_gamma(np.array([1.5 + 0j]), np.array([0.5 / z0]), reference_impedance=z0)
    assert g[0] == pytest.approx(0.5 + 0j, abs=1e-15)


def test_wave_decompose_ui_roundtrip_and_validation() -> None:
    rng = np.random.default_rng(11)
    u = rng.normal(size=7) + 1j * rng.normal(size=7)
    i = rng.normal(size=7) + 1j * rng.normal(size=7)
    dec = wave_decompose_ui(u, i, reference_impedance=50.0)
    assert np.allclose(dec["uf_inc"] + dec["uf_ref"], u)
    # 电流波恒等式按 ports.py 口径：if_ref = if_inc − if_tot ⇒ if_inc − if_ref = i
    assert np.allclose(dec["if_inc"] - dec["if_ref"], i)
    assert np.allclose(dec["uf_inc"], 0.5 * (u + i * 50.0))
    assert np.allclose(dec["if_inc"], 0.5 * (i + u / 50.0))
    with pytest.raises(ConfigError):
        wave_decompose_ui(u, i[:-1])
    with pytest.raises(ConfigError):
        wave_decompose_ui(u, i, reference_impedance=0.0)
    with pytest.raises(ConfigError):
        port_gamma(u, i, reference_impedance=float("nan"))


# ─── stage-4：α 频率缩放（MapesModel keyword-only）+ 确定性校准内核 ─────────

def _batch_z_all(layout: PixelLayout, freqs: np.ndarray) -> np.ndarray:
    mesh = fake_mesh(layout.n_ports)
    return np.stack([mesh.z_all(float(f)) for f in freqs])


def test_mapes_model_alpha_one_is_identity_and_validated() -> None:
    freqs = np.linspace(1.0e9, 6.0e9, 11)
    z_all = _batch_z_all(LAYOUT_4, freqs)
    params = LAYOUT_4.flatten(np.eye(4, dtype=bool))
    base = MapesModel(LAYOUT_4, z_all, freqs)  # 向后兼容：三位置参数
    same = MapesModel(LAYOUT_4, z_all, freqs, alpha=1.0)
    assert same.alpha == 1.0
    assert np.array_equal(same.z_all_effective(), z_all)  # α=1 零插值
    assert base.predict(params) == same.predict(params)
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ConfigError):
            MapesModel(LAYOUT_4, z_all, freqs, alpha=bad)


def test_mapes_model_alpha_resamples_extraction_grid_with_edge_clamp() -> None:
    freqs = np.array([1.0e9, 2.0e9, 3.0e9, 4.0e9])
    z_all = _batch_z_all(LAYOUT_4, freqs)
    model = MapesModel(LAYOUT_4, z_all, freqs, alpha=0.5)
    eff = model.z_all_effective()
    # α·f = [0.5, 1.0, 1.5, 2.0] GHz → [钳位 Z(1), Z(1), 中点插值, Z(2)]
    assert np.allclose(eff[0], z_all[0])
    assert np.allclose(eff[1], z_all[0])
    assert np.allclose(eff[2], 0.5 * (z_all[0] + z_all[1]))
    assert np.allclose(eff[3], z_all[1])
    # 输出频率轴不变（用户轴），Schur 用的是缩放后的提取值
    res = model.evaluate(LAYOUT_4.flatten(np.zeros((4, 4), dtype=bool)))
    assert np.array_equal(res.freq_hz, freqs)
    assert np.allclose(res.z_all, eff)


def test_fit_alpha_scaling_recovers_synthetic_alpha_with_loo() -> None:
    freqs = np.linspace(1.0e9, 6.0e9, 41)
    z_all = _batch_z_all(LAYOUT_4, freqs)
    truth = MapesModel(LAYOUT_4, z_all, freqs, alpha=1.03)
    patterns = [
        np.zeros((4, 4), dtype=bool), np.eye(4, dtype=bool),
        np.add.outer(np.arange(4), np.arange(4)) % 2 == 0,
        np.array([[1, 1, 0, 0]] * 4, dtype=bool), np.ones((4, 4), dtype=bool),
    ]
    cases = []
    for pat in patterns:
        params = LAYOUT_4.flatten(pat)
        cases.append((params, truth.predict(params)))  # "直接全波" = α*=1.03 合成真值
    grid = np.round(np.arange(0.98, 1.0601, 0.002), 4)
    rep = fit_alpha_scaling(LAYOUT_4, z_all, freqs, cases, alpha_grid=grid)
    assert rep["n_cases"] == 5 and rep["metrics"] == ["s11_db_min", "s21_db_at_fc"]
    assert rep["alpha_best"] == pytest.approx(1.03, abs=1e-9)
    assert rep["sse_at_alpha_best"] < 1e-12
    assert rep["sse_at_alpha_1"] > rep["sse_at_alpha_best"]
    assert rep["improvement_ratio"] > 1e6
    assert all(d["alpha_fit"] == pytest.approx(1.03, abs=1e-9) for d in rep["loo"])
    assert rep["loo_mean_norm_err_at_fit"] < 1e-9
    assert rep["loo_mean_norm_err_at_1"] > 0.0
    assert len(rep["sse_curve"]) == len(grid) == len(rep["alpha_grid"])
    # 非法输入
    with pytest.raises(ConfigError):
        fit_alpha_scaling(LAYOUT_4, z_all, freqs, cases[:1])
    with pytest.raises(ConfigError):
        fit_alpha_scaling(LAYOUT_4, z_all, freqs,
                          [(cases[0][0], {"s11_db_min": -3.0}), *cases[1:]])
    with pytest.raises(ConfigError):
        fit_alpha_scaling(LAYOUT_4, z_all, freqs, cases, alpha_grid=[0.0, 1.0])
