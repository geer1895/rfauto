"""TF-5 多节 λ/4 变换器 + N-way Wilkinson 综合单测（round5 r5-插①）。

锚点纪律（#118，独立双路径）：
- src 路径 = 对数权重（结点增量 δ_i）exp/log 累积；
- 测试锚 = 直接幂字面量（50·2^(1/4)=59.4604、50·2^(3/4)=84.0896，任务书钉的
  Pozar 二节 binomial 教科书值）+ 谱系恒等式（乘积/对称）+ 物理判据
  （全节 λ/4 级联 ABCD 闭式 |S11| 对照——ABCD 助手在本文件内，不进 src）。
- g 值表锚 = 教科书通行值（0.1dB N=3 = 1.0316/1.1474/1.0316 等）+ 相邻 N 的
  g1 单调关系抽查。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.synthesis import (
    synthesize_multisection_quarter_wave,
    synthesize_nway_wilkinson,
)


def _abcd_s11(sections_z: list[float], zl: float, z0: float, theta: float) -> complex:
    """N 节 λ/4 线级联的精确 ABCD → S11（复数一致约定）。

    每节 [cosθ, jZ·sinθ; j·sinθ/Z, cosθ]，Zin=(A·ZL+B)/(C·ZL+D)，
    Γ=(Zin-Z0)/(Zin+Z0)。与 src 的对数权重路径完全独立（物理判据）。
    """
    a_mat, b_mat, c_mat, d_mat = 1.0 + 0j, 0j, 0j, 1.0 + 0j
    for z in sections_z:
        c, s = math.cos(theta), math.sin(theta)
        a_mat, b_mat = a_mat * c + b_mat * 1j * s / z, a_mat * 1j * z * s + b_mat * c
        c_mat, d_mat = c_mat * c + d_mat * 1j * s / z, c_mat * 1j * z * s + d_mat * c
    z_in = (a_mat * zl + b_mat) / (c_mat * zl + d_mat)
    return (z_in - z0) / (z_in + z0)


class TestBinomialMultisection:
    """binomial 多节 λ/4 变换器（任务锚 + 恒等式 + 中心匹配物理判据）。"""

    def test_n2_task_anchor(self):
        """任务书锚：50→100 n=2 → 59.4604/84.0896（独立幂字面量路径）。"""
        result = synthesize_multisection_quarter_wave(50.0, 100.0, 2)
        assert result["profile"] == "binomial"
        zs = [sec["z_ohm"] for sec in result["sections"]]
        # 双路径锚：src=对数权重累积；此处=直接幂（50·2^(1/4), 50·2^(3/4)）
        assert zs[0] == pytest.approx(50.0 * 2.0 ** 0.25, rel=1e-12)
        assert zs[1] == pytest.approx(50.0 * 2.0 ** 0.75, rel=1e-12)
        # 任务书钉的教科书量级（rtol 1e-3）
        assert zs[0] == pytest.approx(59.46, rel=1e-3)
        assert zs[1] == pytest.approx(84.09, rel=1e-3)

    def test_product_identity_n2(self):
        """多节谱系恒等式：Z_1·Z_2 = Z0·ZL（逐位）。"""
        result = synthesize_multisection_quarter_wave(50.0, 100.0, 2)
        zs = [sec["z_ohm"] for sec in result["sections"]]
        assert zs[0] * zs[1] == pytest.approx(50.0 * 100.0, rel=1e-12)

    def test_symmetry_identity_various_n(self):
        """对称恒等式 Z_i·Z_{N+1-i}=Z0·ZL（n=1..4，非 2:1 比例）。"""
        for n in (1, 2, 3, 4):
            result = synthesize_multisection_quarter_wave(50.0, 175.0, n)
            zs = [sec["z_ohm"] for sec in result["sections"]]
            assert len(zs) == n
            for i in range(n):
                assert zs[i] * zs[n - 1 - i] == pytest.approx(
                    50.0 * 175.0, rel=1e-9), f"n={n}, i={i}"

    def test_n1_degenerates_single_section(self):
        """n=1 退化=单节 √(Z0·ZL)（与手算互证）。"""
        result = synthesize_multisection_quarter_wave(50.0, 100.0, 1)
        zs = [sec["z_ohm"] for sec in result["sections"]]
        assert len(zs) == 1
        assert zs[0] == pytest.approx(math.sqrt(50.0 * 100.0), rel=1e-12)

    def test_stepdown_reversed_sections(self):
        """反向（100→50）节阻抗 = 正向节序列的逆序。"""
        down = synthesize_multisection_quarter_wave(100.0, 50.0, 2)
        up = synthesize_multisection_quarter_wave(50.0, 100.0, 2)
        zs_down = [sec["z_ohm"] for sec in down["sections"]]
        zs_up = [sec["z_ohm"] for sec in up["sections"]]
        assert zs_down == pytest.approx(list(reversed(zs_up)), rel=1e-12)

    def test_center_match_binomial_all_n(self):
        """物理判据：全节 λ/4 级联 ABCD 在 f0 的 |S11|≈0（乘积恒等式 ⇒ 精确匹配）。"""
        for n in (1, 2, 3, 4):
            result = synthesize_multisection_quarter_wave(50.0, 100.0, n)
            zs = [sec["z_ohm"] for sec in result["sections"]]
            s11 = _abcd_s11(zs, 100.0, 50.0, math.pi / 2)
            assert abs(s11) < 1e-10, f"n={n}: |S11(f0)|={abs(s11):.2e}"

    def test_validation_errors(self):
        """入参越界显式 ValueError（含 bool/浮点拒收，df7+⑯）。"""
        with pytest.raises(ValueError, match="n_sections"):
            synthesize_multisection_quarter_wave(50.0, 100.0, 0)
        with pytest.raises(ValueError, match="整数"):
            synthesize_multisection_quarter_wave(50.0, 100.0, 2.5)
        with pytest.raises(ValueError, match="整数"):
            synthesize_multisection_quarter_wave(50.0, 100.0, True)
        with pytest.raises(ValueError, match="profile"):
            synthesize_multisection_quarter_wave(50.0, 100.0, 2, profile="bogus")
        with pytest.raises(ValueError, match="z0"):
            synthesize_multisection_quarter_wave(0.0, 100.0, 2)
        with pytest.raises(ValueError, match="zl"):
            synthesize_multisection_quarter_wave(50.0, -5.0, 2)
        with pytest.raises(ValueError, match="ripple_db"):
            synthesize_multisection_quarter_wave(50.0, 100.0, 2, ripple_db=0.0)
        with pytest.raises(ValueError, match="ripple_db"):
            synthesize_multisection_quarter_wave(50.0, 100.0, 2, ripple_db=5.0)
        with pytest.raises(ValueError, match="ripple_db"):
            synthesize_multisection_quarter_wave(50.0, 100.0, 2, ripple_db=-100.0)
        # binomial 带宽电平高于原始失配（Γm=0.891 > Γδ=1/3）→ 无法估带宽
        with pytest.raises(ValueError, match="失配"):
            synthesize_multisection_quarter_wave(50.0, 100.0, 2, ripple_db=-1.0)


class TestChebyshevMultisection:
    """chebyshev 多节 λ/4 变换器（T_N 展开双路径 + 等纹波物理判据）。"""

    def test_ripple_required(self):
        """chebyshev 必须显式给 ripple_db。"""
        with pytest.raises(ValueError, match="chebyshev"):
            synthesize_multisection_quarter_wave(50.0, 100.0, 2, profile="chebyshev")

    def test_n2_dual_path_weights(self):
        """测试侧独立重算 T_2 展开权重 → 节阻抗与 FBW 双路径对拍。"""
        gm, gd = 0.1, 1.0 / 3.0
        s = math.cosh(math.acosh(gd / gm) / 2)
        raw = [s ** 2, 2.0 * (s ** 2 - 1.0), s ** 2]
        w = [x / sum(raw) for x in raw]
        expect_z = [50.0 * math.exp(math.log(2.0) * sum(w[:i])) for i in (1, 2)]
        expect_fbw = 2.0 - 4.0 * math.acos(1.0 / s) / math.pi

        result = synthesize_multisection_quarter_wave(
            50.0, 100.0, 2, profile="chebyshev", ripple_db=-20.0)
        zs = [sec["z_ohm"] for sec in result["sections"]]
        assert zs == pytest.approx(expect_z, rel=1e-12)
        assert result["bandwidth_estimate"]["fbw"] == pytest.approx(
            expect_fbw, rel=1e-6)
        # 对称恒等式同样成立
        assert zs[0] * zs[1] == pytest.approx(5000.0, rel=1e-9)

    def test_n2_center_peak_equal_ripple(self):
        """偶 N：f0 处 |S11|≈Γm（等纹波中心峰，一阶模型精度带内）。"""
        result = synthesize_multisection_quarter_wave(
            50.0, 100.0, 2, profile="chebyshev", ripple_db=-20.0)
        zs = [sec["z_ohm"] for sec in result["sections"]]
        s11_f0 = abs(_abcd_s11(zs, 100.0, 50.0, math.pi / 2))
        assert 0.6 * 0.1 < s11_f0 < 1.4 * 0.1
        # 带边 ≈ Γm
        th0 = result["bandwidth_estimate"]["theta_edge_rad"]
        assert abs(_abcd_s11(zs, 100.0, 50.0, th0)) < 1.4 * 0.1

    def test_n3_center_null_and_middle_section(self):
        """奇 N：f0 处 |S11|≈0；中节 = √(Z0·ZL)。"""
        result = synthesize_multisection_quarter_wave(
            50.0, 100.0, 3, profile="chebyshev", ripple_db=-20.0)
        zs = [sec["z_ohm"] for sec in result["sections"]]
        assert abs(_abcd_s11(zs, 100.0, 50.0, math.pi / 2)) < 1e-10
        assert zs[1] == pytest.approx(math.sqrt(5000.0), rel=1e-12)

    def test_in_band_ripple_bound(self):
        """带内 |S11| 不显著超过设计纹波（一阶模型精度留 50% 裕量）。"""
        result = synthesize_multisection_quarter_wave(
            50.0, 100.0, 3, profile="chebyshev", ripple_db=-20.0)
        zs = [sec["z_ohm"] for sec in result["sections"]]
        th0 = result["bandwidth_estimate"]["theta_edge_rad"]
        for frac in [0.7 + 0.05 * k for k in range(13)]:
            theta = math.pi / 2 * frac
            assert abs(_abcd_s11(zs, 100.0, 50.0, theta)) <= 0.15, (
                f"f/f0={frac}: |S11|={abs(_abcd_s11(zs, 100.0, 50.0, theta)):.4f}")
        # 带外（θ<θ0）不判：一阶表驱动对深带外无约束
        assert th0 > 0

    def test_feasibility_infeasible_ripple(self):
        """纹波电平高于原始失配 → 显式 ValueError（无需/无法综合）。"""
        with pytest.raises(ValueError, match="失配"):
            synthesize_multisection_quarter_wave(
                50.0, 100.0, 2, profile="chebyshev", ripple_db=-1.0)

    def test_n5_rejected_binomial_ok(self):
        """chebyshev N>4 超出表驱动范围显式拒绝；binomial N=5 正常。"""
        with pytest.raises(ValueError, match="N≤4"):
            synthesize_multisection_quarter_wave(
                50.0, 100.0, 5, profile="chebyshev", ripple_db=-20.0)
        result = synthesize_multisection_quarter_wave(50.0, 100.0, 5)
        assert len(result["sections"]) == 5

    def test_prototype_reference_attached(self):
        """chebyshev 返回附原型 g 值参照（出处链）；binomial 为 None。"""
        result = synthesize_multisection_quarter_wave(
            50.0, 100.0, 3, profile="chebyshev", ripple_db=-20.0)
        ref = result["prototype_reference"]
        assert ref is not None
        # |S11|=-20dB → 通带纹波 0.0436dB → 最近档 0.1dB（教科书行）
        assert ref["g_values"] == [1.0316, 1.1474, 1.0316]
        assert ref["ripple_table_db"] == 0.1
        assert ref["passband_ripple_db"] == pytest.approx(
            -10.0 * math.log10(1.0 - 10.0 ** (-2.0)), abs=1e-4)
        assert ref["g_termination"] == 1.0
        binom = synthesize_multisection_quarter_wave(50.0, 100.0, 3)
        assert binom["prototype_reference"] is None


class TestChebyshevLpfGTable:
    """内嵌 g 值表：教科书锚 + 相邻 N 的 g1 关系抽查 + 选档/越界。"""

    def test_table_rows_textbook_anchors(self):
        from rfauto.core.synthesis import chebyshev_lpf_g_values
        # 入参=|S11| 负 dB 口径；档位映射：-20→0.1dB、-9→0.5dB、-6→1.0dB
        assert chebyshev_lpf_g_values(3, -20.0)["g_values"] == [
            1.0316, 1.1474, 1.0316]
        assert chebyshev_lpf_g_values(2, -9.0)["g_values"] == [1.4029, 0.7071]
        assert chebyshev_lpf_g_values(3, -6.0)["g_values"] == [
            2.0236, 0.9941, 2.0236]
        assert chebyshev_lpf_g_values(4, -20.0)["g_values"] == [
            1.1088, 1.3062, 1.7704, 0.8181]  # 偶 N g4 修正=W4-E 批 #118 双源钉（旧 1.3062 系 g2 镜像转录错；Pozar §8.4 递推+教科书通行值回核）
        assert chebyshev_lpf_g_values(3, -9.0)["ripple_table_db"] == 0.5
        assert chebyshev_lpf_g_values(3, -6.0)["ripple_table_db"] == 1.0
        # 出处注记在案
        assert "Table 4.05-1" in chebyshev_lpf_g_values(1, -20.0)["source"]

    def test_g1_monotone_in_adjacent_n(self):
        """相邻 N 的 g1 关系：固定纹波下单调增（教科书表性质抽查）。"""
        from rfauto.core.synthesis import chebyshev_lpf_g_values
        for _table_ripple, req in ((0.1, -20.0), (0.5, -9.0), (1.0, -6.0)):
            g1s = [chebyshev_lpf_g_values(n, req)["g_values"][0]
                   for n in (1, 2, 3, 4)]
            assert g1s == sorted(g1s), f"req={req}: g1 序列 {g1s} 非单调增"

    def test_nearest_ripple_selection(self):
        """|S11| 口径→通带纹波精确换算后取最近档；正中 tie-break 取纹波更深一档。"""
        from rfauto.core.synthesis import chebyshev_lpf_g_values
        assert chebyshev_lpf_g_values(3, -14.0)["ripple_table_db"] == 0.1
        assert chebyshev_lpf_g_values(3, -8.5)["ripple_table_db"] == 0.5
        assert chebyshev_lpf_g_values(3, -7.0)["ripple_table_db"] == 1.0
        # 通带纹波恰 0.3dB（0.1/0.5 正中）↔ |S11|=-11.7560dB → tie-break 取 0.5
        tie_req = 10.0 * math.log10(1.0 - 10.0 ** (-0.03))
        assert tie_req == pytest.approx(-11.7560, abs=1e-3)
        assert chebyshev_lpf_g_values(3, tie_req)["ripple_table_db"] == 0.5

    def test_out_of_scope_errors(self):
        from rfauto.core.synthesis import chebyshev_lpf_g_values
        with pytest.raises(ValueError, match="N≤4"):
            chebyshev_lpf_g_values(5, -20.0)
        with pytest.raises(ValueError, match="越界"):
            chebyshev_lpf_g_values(3, -60.01)
        with pytest.raises(ValueError, match="chebyshev"):
            chebyshev_lpf_g_values(3, None)


class TestNwayWilkinsonStar:
    """star 口径：Pon 1961 闭式（√N·Z0 臂 + R=Z0 星形隔离）。"""

    def test_star_n2_matches_classic(self):
        """N=2 退化为既有 2-way：臂 √2·Z0、隔离 2·Z0；经 HJ 链与
        synthesize_wilkinson 的 series 臂对拍同解。"""
        from rfauto.core.synthesis import synthesize_mline, synthesize_wilkinson
        star2 = synthesize_nway_wilkinson(2, z0=50.0, topology="star")
        p = star2["params"]
        assert p["arm_z_ohm"] == pytest.approx(50.0 * math.sqrt(2.0), rel=1e-3)
        assert p["n_isolation_r"] == 2
        assert p["isolation_r_ohm"] == pytest.approx(50.0, rel=1e-3)
        # 两支 Z0 串联 = 经典 2·Z0 = 100Ω 隔离（与 synthesize_wilkinson docstring 口径一致）
        assert p["n_isolation_r"] * p["isolation_r_ohm"] == pytest.approx(100.0, rel=1e-3)
        # HJ 链对拍：star2 臂阻抗反解线宽 == synthesize_wilkinson series_w_mm
        # （后者 params 按 3 位小数取整，两侧同走 synthesize_mline 精确对齐）
        width_star = synthesize_mline(50.0 * math.sqrt(2.0), 2.4).width_mm
        assert round(width_star, 3) == (
            synthesize_wilkinson(f0_ghz=2.4, z0_ohm=50.0).params["series_w_mm"])

    def test_star_n3_anchor(self):
        """N=3 闭式手算：臂 = 50√3 = 86.6025，R=Z0=50 ×3 支。"""
        star3 = synthesize_nway_wilkinson(3, z0=50.0, topology="star")
        p = star3["params"]
        # params 按 4 位小数取整（家族口径），锚对照用 1e-4 相对容差
        assert p["arm_z_ohm"] == pytest.approx(50.0 * 3.0 ** 0.5, rel=1e-4)
        assert p["arm_z_ohm"] == pytest.approx(86.6025, abs=1e-3)
        assert p["isolation_r_ohm"] == pytest.approx(50.0, abs=1e-12)
        assert p["n_isolation_r"] == 3
        assert p["arm_count"] == 3

    def test_star_n4_anchor_and_input_match(self):
        """N=4：臂 = 2·Z0 = 100Ω；N 臂并联于输入结 = Z0（闭式匹配口径）。"""
        star4 = synthesize_nway_wilkinson(4, z0=50.0, topology="star")
        p = star4["params"]
        assert p["arm_z_ohm"] == pytest.approx(100.0, rel=1e-12)
        assert p["arm_z_ohm"] / math.sqrt(4) == pytest.approx(50.0, rel=1e-12)
        assert p["n_isolation_r"] == 4

    def test_star_n5_non_power_of_two_ok(self):
        """star 接受任意 N≥2（非 2 幂合法；仅 tree 限制 2 幂）。"""
        star5 = synthesize_nway_wilkinson(5, topology="star")
        assert star5["params"]["arm_z_ohm"] == pytest.approx(
            50.0 * 5.0 ** 0.5, rel=1e-3)

    def test_family_dict_contract(self):
        """返回与 synthesize_wilkinson 同族契约：model/goal/params/recipe_draft/notes。"""
        result = synthesize_nway_wilkinson(2)
        assert set(result) == {"model", "goal", "params", "recipe_draft", "notes"}
        assert result["model"] == "nway_wilkinson_power_divider"
        assert set(result["goal"]) == {"n_way", "z0_ohm", "topology"}
        assert result["recipe_draft"]["recipe_version"] == 1
        assert result["recipe_draft"]["schema_version"] == 1
        assert isinstance(result["notes"], list) and result["notes"]


class TestNwayWilkinsonTree:
    """tree 口径：既有 2-way 单元级联（2^k 限定）。"""

    def test_tree_n4_structure(self):
        """N=4：2 级、每级臂 √2·Z0=70.71Ω、隔离 R=2·Z0=100Ω；共 6 臂 3 阻。"""
        tree4 = synthesize_nway_wilkinson(4, z0=50.0, topology="tree")
        p = tree4["params"]
        assert p["stages"] == 2
        assert p["arm_z_ohm"] == pytest.approx(50.0 * math.sqrt(2.0), rel=1e-4)
        assert p["isolation_r_ohm"] == pytest.approx(100.0, rel=1e-12)
        assert p["arm_count"] == 6
        assert p["n_isolation_r"] == 3

    def test_tree_equals_star_at_n2(self):
        """N=2：tree（单级 2-way）与 star 臂阻抗同解、等效隔离同为 2·Z0。"""
        tree2 = synthesize_nway_wilkinson(2, topology="tree")
        star2 = synthesize_nway_wilkinson(2, topology="star")
        assert tree2["params"]["arm_z_ohm"] == pytest.approx(
            star2["params"]["arm_z_ohm"], rel=1e-12)
        assert tree2["params"]["arm_z_ohm"] == pytest.approx(
            50.0 * math.sqrt(2.0), rel=1e-4)
        # 等效隔离：tree 1 支 2·Z0；star 2 支 Z0 串联
        assert tree2["params"]["isolation_r_ohm"] == pytest.approx(100.0, rel=1e-12)
        assert (star2["params"]["n_isolation_r"]
                * star2["params"]["isolation_r_ohm"]) == pytest.approx(100.0, rel=1e-12)

    def test_tree_star_port_impedance_equivalence_n4(self):
        """N=4 关键阻抗等价：两拓扑端口口径均 Z0（每结点并联恢复 Z0）；
        臂阻抗口径差异已在 docstring/notes 注明（star 2·Z0 vs tree √2·Z0）。"""
        star4 = synthesize_nway_wilkinson(4, topology="star")
        tree4 = synthesize_nway_wilkinson(4, topology="tree")
        ps, pt = star4["params"], tree4["params"]
        # star：N 臂 √N·Z0 并联 = Z0
        assert ps["arm_z_ohm"] / math.sqrt(ps["n_way"]) == pytest.approx(
            ps["input_z_ohm"], rel=1e-12)
        # tree：每级 2 臂 √2·Z0 并联 = Z0（params 取整口径 → 1e-4 容差）
        assert pt["arm_z_ohm"] / math.sqrt(2.0) == pytest.approx(
            pt["input_z_ohm"], rel=1e-4)
        # 端口口径等价、臂口径不等价（口径差异的证据）
        assert ps["input_z_ohm"] == pt["input_z_ohm"] == 50.0
        assert ps["arm_z_ohm"] != pytest.approx(pt["arm_z_ohm"], rel=1e-3)
        assert any("口径差异" in note for note in tree4["notes"])

    def test_tree_non_power_of_two_rejected(self):
        """非 2 幂 tree → 显式 ValueError（任意 N 用 star）。"""
        with pytest.raises(ValueError, match="2 的幂"):
            synthesize_nway_wilkinson(3, topology="tree")
        with pytest.raises(ValueError, match="2 的幂"):
            synthesize_nway_wilkinson(6, topology="tree")

    def test_validation_errors(self):
        """n<2 / bool / 非法拓扑 / 非法 z0 → 显式 ValueError。"""
        with pytest.raises(ValueError, match="n"):
            synthesize_nway_wilkinson(1)
        with pytest.raises(ValueError, match="整数"):
            synthesize_nway_wilkinson(2.0)
        with pytest.raises(ValueError, match="整数"):
            synthesize_nway_wilkinson(True)
        with pytest.raises(ValueError, match="topology"):
            synthesize_nway_wilkinson(4, topology="bogus")
        with pytest.raises(ValueError, match="z0"):
            synthesize_nway_wilkinson(4, z0=0.0)


class TestMultisectionPhysicalLengths:
    """HJ 链物理长度（仅 f0_ghz 显式给出时精算；缺省层叠家族惯例）。"""

    def test_lengths_with_f0_hj_chain(self):
        """给 f0：每节线宽/εeff/λ/4 长度经 HJ 链精算（50→100 两节 @2.4GHz）。"""
        result = synthesize_multisection_quarter_wave(50.0, 100.0, 2, f0_ghz=2.4)
        for sec in result["sections"]:
            assert sec["status"] == "ok"
            assert 0.2 < sec["width_mm"] < 5.0
            assert 2.5 < sec["epsilon_eff"] < 3.7  # rogers4350b h0.508 合理窗
            assert 16.0 < sec["length_mm"] < 20.0  # λ/4 @2.4GHz 量级（εeff≈2.9-3.3）
        # 高阻节更窄、εeff 更低 → 长度更长（单调方向判据）
        lo, hi = result["sections"]
        assert lo["width_mm"] > hi["width_mm"]
        assert lo["length_mm"] < hi["length_mm"]

    def test_no_f0_leaves_none_not_fabricated(self):
        """不给 f0：物理量显式留 None（禁虚构 εeff，#1c）。"""
        result = synthesize_multisection_quarter_wave(50.0, 100.0, 2)
        for sec in result["sections"]:
            assert sec["width_mm"] is None
            assert sec["epsilon_eff"] is None
            assert sec["length_mm"] is None
            assert sec["status"] is None
        assert any("None" in note for note in result["notes"])
