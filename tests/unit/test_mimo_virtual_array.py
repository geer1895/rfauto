"""NX-1 MIMO 虚拟阵内核单测（core/mimo_virtual_array.py，round14 §四 :88）。

裁判 = 外部独立来源/独立代码路径（#118：不是被测实现的自我推导）：
  * EuRAD 2023 12×6 验收案例（round14 规格钉）：等距收发 ULA（M=12、
    N=6、同距 d）→ 虚拟 M+N−1=17 元等距 ULA、三角多重数
    {1,2,3,4,5,6,6,6,6,6,6,6,5,4,3,2,1}、孔径 L_v=(M+N−2)d=16d（Li &
    Stoica, IEEE SPM 24(5) 2007 colocated MIMO virtual array 口径）；
  * 两路乘积恒等式：AF_tx(u)·AF_rx(u) ≡ 等效物理阵分组路径（本内核内
    两条独立代码路径）≡ sparse_array_cs.forward_matrix 列向 Kronecker
    （kron(a_tx,a_rx) 列构造 repeat·tile，第三方实现路径）——三路对拍；
  * 孔径可加恒等式 L_v = L_tx + L_rx（min/max 可分离性，任意位置精确，
    非近似）；
  * 首零分辨率闭式 1/(max(M,N)·d)（乘积方向图零点=因子零点之并；
    12×6 → AF(1/6)=0 精确实测 9e-17）；
  * 均匀虚拟 ULA 闭式 HPBW（单 Tx 复制 Rx 阵：虚拟=N 元均匀 ULA；
    Balanis 3ed §6.3 0.886λ/(Nd) 渐近式经 array_synthesis.broadside_
    hpbw_rad 复用；N=16 实测偏差 <2%，N≥32 <0.5%——渐近式的小 N 余量
    如实带窗）；
  * monostatic（收发同位）sum 口径 → p_v=2p 孔径/间距加倍，d=λ/2 物理
    阵 → 虚拟 d=λ（栅瓣区）——复用 array_synthesis.has_grating_lobe
    只读钉住物理含义（单站 MIMO 需 d≤λ/4 的文献结论的可观测面）；
  * PSLL：同构因子（Tx=Rx 同位同权）乘积方向图 = 因子² → dB 恰翻倍
    （同网格采样点逐位对应）；异构因子乘积 ≤ min(两因子 PSLL)
    （逐点 |prod|≤|factor| 的直接推论）；
  * 负例：空/2-D/NaN 位置、权重长度/非有限、未知口径、零和权重归一化
    显式拒绝；不等距收发 → 非均匀虚拟阵（distinct<M·N 有碰撞、等距
    闭式 None）——"虚拟阵恒为 M+N−1 元 ULA"的反例钉。

确定性：无网络、无真机、无文件 IO；随机相位权重用固定种子
（numpy Generator(7)，字面钉死）。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from rfauto.core.array_synthesis import (
    broadside_hpbw_rad,
    has_grating_lobe,
)
from rfauto.core.mimo_virtual_array import (
    equivalent_physical_array_factor,
    mimo_virtual_array_report,
    virtual_array_elements,
    virtual_array_factor,
)
from rfauto.core.sparse_array_cs import forward_matrix

D_HALF = 0.5
TX_12 = [i * D_HALF for i in range(12)]
RX_6 = [j * D_HALF for j in range(6)]
U_GRID = np.linspace(-1.0, 1.0, 4001)


# ------------------------------------------------------------- EuRAD 12×6 锚


class TestEuRadCase:
    """等距收发 ULA 虚拟阵闭式（round14 验收锚：12×6 → 17 元）。"""

    def test_seventeen_element_closed_form(self) -> None:
        el = virtual_array_elements(TX_12, RX_6)
        assert el["n_tx"] == 12 and el["n_rx"] == 6 and el["n_pairs"] == 72
        assert el["n_virtual"] == 12 + 6 - 1
        assert el["positions_lambda"] == pytest.approx(
            [k * D_HALF for k in range(17)])
        # 三角多重数：min(s+1, 6, 12, 17−s) → s=0..5 递增、平台 6、递减
        assert el["multiplicity"] == [
            1, 2, 3, 4, 5, 6, 6, 6, 6, 6, 6, 6, 5, 4, 3, 2, 1]
        assert sum(el["multiplicity"]) == 72
        assert el["uniform_spacing_lambda"] == pytest.approx(D_HALF)

    def test_aperture_additivity_identity(self) -> None:
        el = virtual_array_elements(TX_12, RX_6)
        assert el["aperture_tx_lambda"] == pytest.approx(11 * D_HALF)
        assert el["aperture_rx_lambda"] == pytest.approx(5 * D_HALF)
        assert el["aperture_lambda"] == pytest.approx(16 * D_HALF)
        assert el["aperture_additivity_residual"] == pytest.approx(0.0, abs=1e-12)

    def test_physical_mm_input_ulp_split_regressed(self) -> None:
        # 回归钉：物理单位输入（77 GHz、名义 λ/2=1.9467mm 舍入值）的和集
        # 按浮点路径分裂（2s'+3s' ≠ 1s'+4s'，ulp 级）——容差聚簇必须还原
        # 17 元等距虚拟阵，不得假分裂出零间距格点
        scale = 77.0 / 299.792458
        tx = [round(i * 1.9467, 4) * scale for i in range(12)]
        rx = [round(j * 1.9467, 4) * scale for j in range(6)]
        el = virtual_array_elements(tx, rx)
        assert el["n_virtual"] == 17
        assert sum(el["multiplicity"]) == 72
        assert el["uniform_spacing_lambda"] == pytest.approx(0.5, rel=1e-5)

    def test_report_first_null_aperture_gain_and_honest_closed_form(
            self) -> None:
        rep = mimo_virtual_array_report(TX_12, RX_6)
        # 首零闭式：乘积零点=因子零点之并 → 1/(max(12,6)·0.5)=1/6
        assert rep["rayleigh_first_null_u_closed_form"] == pytest.approx(1.0 / 6.0)
        assert abs(virtual_array_factor(
            np.array([1.0 / 6.0]), TX_12, RX_6)[0]) < 1e-12
        # 孔径增益 = 16d/11d（精确恒等式比值）
        assert rep["aperture_gain_vs_tx"] == pytest.approx(16.0 / 11.0)
        # 三角锥削自然虚拟阵：均匀阵 HPBW 闭式不适用（诚实 None），
        # 数值 HPBW 比窄因子更锐（乘积锐化）、远宽于 Rx 因子
        assert rep["hpbw_broadside_u_closed_form"] is None
        hpbw_tx = broadside_hpbw_rad(12, D_HALF)
        hpbw_rx = broadside_hpbw_rad(6, D_HALF)
        assert rep["hpbw_u_numeric"] < hpbw_tx < hpbw_rx
        # 数值分辨率增益（vs Tx 单阵）与孔径增益分离（锥削代价如实）
        assert 1.0 < rep["resolution_gain_numeric_vs_tx"] < 1.25
        # 乘积 vs 等效物理阵恒等残差（独立双路径对拍）
        assert rep["pattern_identity_residual"] < 1e-9
        # PSLL：乘积 ≤ 因子（逐点 |prod| ≤ |AF_tx| 主判峰值同 1）
        assert rep["psll_virtual_db"] <= rep["psll_tx_only_db"] + 1e-9
        # JSON 安全（无 NaN/Inf——service 合同）
        json.dumps(rep, allow_nan=False)


# ------------------------------------------------- 三路恒等式（对拍裁判）


class TestProductIdentity:
    """乘积路径 ≡ 分组路径 ≡ sparse_array_cs 列向 Kronecker（三路对拍）。"""

    def test_product_equals_grouped_uniform(self) -> None:
        af_prod = virtual_array_factor(U_GRID, TX_12, RX_6)
        el = virtual_array_elements(TX_12, RX_6)
        af_grouped = equivalent_physical_array_factor(U_GRID, el)
        assert float(np.max(np.abs(af_prod - af_grouped))) < 1e-9
        assert abs(af_prod[np.argmin(np.abs(U_GRID))] - 1.0) < 1e-12  # 侧射峰=1

    def test_product_equals_grouped_complex_weights(self) -> None:
        rng = np.random.default_rng(7)
        w_tx = np.exp(1j * rng.uniform(0.0, 2.0 * np.pi, 12))
        w_rx = np.exp(1j * rng.uniform(0.0, 2.0 * np.pi, 6))
        af_prod = virtual_array_factor(
            U_GRID, TX_12, RX_6, tx_weights=w_tx, rx_weights=w_rx)
        el = virtual_array_elements(
            TX_12, RX_6, tx_weights=w_tx, rx_weights=w_rx)
        af_grouped = equivalent_physical_array_factor(U_GRID, el)
        assert float(np.max(np.abs(af_prod - af_grouped))) < 1e-9

    def test_sparse_array_cs_forward_kronecker_identity(self) -> None:
        """接 sparse_array_cs：前向算子同构（列向 Kronecker，repeat·tile）。"""
        a_tx = forward_matrix(TX_12, U_GRID)
        a_rx = forward_matrix(RX_6, U_GRID)
        a_kron = np.repeat(a_tx, 6, axis=1) * np.tile(a_rx, (1, 12))
        w_tx = np.ones(12)
        w_rx = np.ones(6)
        resp_kron = (a_kron @ np.kron(w_tx, w_rx)) / (w_tx.sum() * w_rx.sum())
        el = virtual_array_elements(TX_12, RX_6)
        a_virtual = forward_matrix(np.asarray(el["positions_lambda"]), U_GRID)
        w_grouped = np.asarray(
            [c[0] + 1j * c[1] for c in el["pair_weights"]])
        resp_grouped = (a_virtual @ w_grouped) / w_grouped.sum()
        assert float(np.max(np.abs(resp_kron - resp_grouped))) < 1e-9

    def test_scan_offset_identity_and_peak(self) -> None:
        u0 = 0.3
        af = virtual_array_factor(
            U_GRID, TX_12, RX_6, scan_direction_cosine=u0)
        el = virtual_array_elements(TX_12, RX_6)
        af_g = equivalent_physical_array_factor(
            U_GRID, el, scan_direction_cosine=u0)
        assert float(np.max(np.abs(af - af_g))) < 1e-9
        assert abs(af[np.argmin(np.abs(U_GRID - u0))] - 1.0) < 1e-9

    def test_difference_convention(self) -> None:
        tx = [0.0, 1.0]
        rx = [0.0, 0.5]
        el = virtual_array_elements(tx, rx, convention="difference")
        # 带符号差 Lag：{0−0, 0−0.5, 1−0, 1−0.5} = {−0.5, 0, 0.5, 1.0}
        assert el["positions_lambda"] == pytest.approx([-0.5, 0.0, 0.5, 1.0])
        assert el["multiplicity"] == [1, 1, 1, 1]
        af_diff = virtual_array_factor(
            U_GRID, tx, rx, convention="difference")
        af_grouped = equivalent_physical_array_factor(U_GRID, el)
        assert float(np.max(np.abs(af_diff - af_grouped))) < 1e-9
        # 独立口径：AF_tx·conj(AF_rx)（两路相位相减的解析形式）
        af_tx = forward_matrix(tx, U_GRID) @ np.ones(2) / 2.0
        af_rx = forward_matrix(rx, U_GRID) @ np.ones(2) / 2.0
        assert float(np.max(np.abs(af_diff - af_tx * np.conj(af_rx)))) < 1e-9
        assert abs(af_diff[np.argmin(np.abs(U_GRID))] - 1.0) < 1e-12


# ------------------------------------------------- 均匀虚拟 ULA 闭式档


class TestUniformVirtualUla:
    """分组权重均匀的等距虚拟 ULA：HPBW/首零闭式精确档。"""

    def test_single_tx_replicates_rx_closed_form_hpbw(self) -> None:
        # 单 Tx（同位复制）→ 虚拟 = Rx 均匀 ULA（M=1 多重数全 1）
        rep = mimo_virtual_array_report([0.0], [j * D_HALF for j in range(16)])
        assert rep["weights_uniform"] is True
        assert rep["n_virtual"] == 16
        closed = broadside_hpbw_rad(16, D_HALF)
        assert rep["hpbw_broadside_u_closed_form"] == pytest.approx(closed)
        assert rep["hpbw_broadside_deg_closed_form"] == pytest.approx(
            float(np.degrees(closed)))
        # 渐近式小 N 余量：N=16 数值 vs 闭式 <2%（大 N 收敛 <0.5%）
        assert abs(rep["hpbw_u_numeric"] - closed) / closed < 2e-2
        assert rep["rayleigh_first_null_u_closed_form"] == pytest.approx(
            1.0 / (16 * D_HALF))
        assert abs(virtual_array_factor(
            np.array([0.125]), [0.0], [j * D_HALF for j in range(16)])[0]) < 1e-9

    def test_symmetric_16x16_numeric_resolution_gain(self) -> None:
        rep = mimo_virtual_array_report(
            [i * D_HALF for i in range(16)], [j * D_HALF for j in range(16)])
        assert rep["n_virtual"] == 31
        assert rep["rayleigh_first_null_u_closed_form"] == pytest.approx(0.125)
        # 对称 16×16：数值 HPBW 增益 ~1.39（三角锥削代价后）——带窗钉
        assert 1.25 < rep["resolution_gain_numeric_vs_tx"] < 1.55


class TestMonostaticDoubling:
    """收发同位恒等阵（monostatic 形态）sum 口径：自和集、孔径精确加倍。"""

    def test_identical_arrays_aperture_doubled(self) -> None:
        tx = [0.0, 0.5, 1.0]
        el = virtual_array_elements(tx, tx)
        # 自和集 {p_i+p_j}：5 元（2N−1）等距 d=0.5、跨 [0,2]——孔径加倍
        assert el["n_virtual"] == 2 * 3 - 1
        assert el["positions_lambda"] == pytest.approx(
            [0.0, 0.5, 1.0, 1.5, 2.0])
        assert el["multiplicity"] == [1, 2, 3, 2, 1]
        assert el["aperture_lambda"] == pytest.approx(
            2.0 * el["aperture_tx_lambda"])
        assert el["aperture_additivity_residual"] == pytest.approx(0.0, abs=1e-12)

    def test_single_pair_monostatic_position_doubled(self) -> None:
        # 单通道 monostatic（对角自发自收一对）：p_v = 2p 精确
        el = virtual_array_elements([0.75], [0.75])
        assert el["positions_lambda"] == pytest.approx([1.5])
        assert el["n_virtual"] == 1

    def test_diagonal_spacing_grating_lobe_flag(self) -> None:
        # 物理含义：d=λ/2 物理阵的对角自收口径等效间距 2d=λ=栅瓣区
        # （单站 MIMO ULA 需 d≤λ/4）——复用 array_synthesis 判据演示
        assert has_grating_lobe(1.0) is True


class TestPsll:
    """PSLL：同构因子乘积 dB 翻倍精确；异构因子 ≤ 因子。"""

    def test_same_kernel_product_doubles_db(self) -> None:
        tx = [i * D_HALF for i in range(8)]
        rep = mimo_virtual_array_report(tx, tx)
        # |prod| = |AF_tx|²（同网格采样点逐位对应）→ dB 恰 2×
        assert rep["psll_virtual_db"] == pytest.approx(
            2.0 * rep["psll_tx_only_db"], rel=1e-9)
        # 均匀 8 元阵第一副瓣经典量级（−13.26 dB 理论，采样带内）
        assert -14.0 < rep["psll_tx_only_db"] < -12.5

    def test_mixed_factors_product_bounded_by_each(self) -> None:
        rep = mimo_virtual_array_report(TX_12, RX_6)
        assert rep["psll_virtual_db"] <= rep["psll_tx_only_db"] + 1e-9
        rx_rep = mimo_virtual_array_report(TX_12[:1], RX_6)
        assert rep["psll_virtual_db"] <= rx_rep["psll_tx_only_db"] + 1e-9


# ------------------------------------------------------------- 负例


class TestNegative:
    """非法输入显式拒绝 + 物理反例（虚拟阵不恒为 M+N−1 元 ULA）。"""

    def test_empty_positions_rejected(self) -> None:
        with pytest.raises(ValueError, match="不能为空"):
            virtual_array_elements([], [0.0])

    def test_two_dim_positions_rejected(self) -> None:
        with pytest.raises(ValueError, match="一维"):
            virtual_array_elements([[0.0], [0.5]], [0.0])

    def test_nan_position_rejected(self) -> None:
        with pytest.raises(ValueError, match="非有限"):
            virtual_array_elements([0.0, float("nan")], [0.0])

    def test_unknown_convention_rejected(self) -> None:
        with pytest.raises(ValueError, match="convention"):
            virtual_array_elements([0.0], [0.0], convention="bogus")

    def test_weight_length_and_finiteness_rejected(self) -> None:
        with pytest.raises(ValueError, match="长度"):
            virtual_array_elements([0.0, 0.5], [0.0], tx_weights=[1.0])
        with pytest.raises(ValueError, match="非有限"):
            virtual_array_elements([0.0, 0.5], [0.0],
                                   tx_weights=[1.0, float("inf")])

    def test_zero_sum_weights_normalize_rejected(self) -> None:
        with pytest.raises(ValueError, match="归一化无定义"):
            virtual_array_factor(
                U_GRID, [0.0, 0.5], [0.0],
                tx_weights=[1.0, -1.0], normalize=True)
        # normalize=False 显式放行（零和权重的场本身合法）
        af = virtual_array_factor(
            np.array([0.0]), [0.0, 0.5], [0.0],
            tx_weights=[1.0, -1.0], normalize=False)
        assert af.shape == (1,)

    def test_unequal_spacings_not_uniform_ula(self) -> None:
        # 物理反例：Tx d=λ/2（3 元）× Rx {0, λ/4, 3λ/4} → 碰撞合并且
        # 格点不均匀：和集 distinct {0,.25,.5,.75,1,1.25,1.75}=7
        # （≠ M+N−1=5，也 < M·N=9）——"虚拟阵恒为等距 ULA"不成立
        el = virtual_array_elements(
            [0.0, 0.5, 1.0], [0.0, 0.25, 0.75])
        assert el["n_pairs"] == 9
        assert el["n_virtual"] == 7
        assert el["multiplicity"] == [1, 1, 1, 2, 1, 2, 1]
        assert el["uniform_spacing_lambda"] is None
        rep = mimo_virtual_array_report(
            [0.0, 0.5, 1.0], [0.0, 0.25, 0.75])
        # 等距闭式档全部诚实 None（不越界外推）
        assert rep["hpbw_broadside_u_closed_form"] is None
        assert rep["rayleigh_first_null_u_closed_form"] is None
