"""E12 像素域生成式逆设计最小闭环单测（确定性、零真机、纯闭式内核）。

覆盖：
1. 评判器 hinge 数学（手工构造 MapesResult，期望值手算钉死）；
2. 评判确定性（同图案两次求检逐字段一致）；
3. 频段与扫频空交集显式报错（#121 精神）；
4. PassbandTarget / p_on 输入校验；
5. 提议器（随机伯努利）确定性 + 形状；1-bit 邻域完备性；
6. 4x4 小域搜索契约 + 不劣于随机阶段 + 全程确定性；
7. 6x6 验收例（scripts/e12_inverse_demo.py 同常数冻结）：随机阶段
   error=0.4248 dB → 局部精修 2 步达 error=0（PASS，20/36 占用，169 个
   唯一图案）——数字出自 core/mapes.py 闭式内核，同 seed 可复现。

铁律 7 对照：提议器只产出 0/1 拓扑；误差/等级/S 参数全部由评判器产出。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# 确保 src 在 path 中（同 test_mapes 模式）
src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.core.errors import ConfigError
from rfauto.core.inverse_design import (
    PassbandTarget,
    build_demo_model,
    evaluate_design,
    evaluate_occupancy,
    one_flip_neighbors,
    propose_random,
    run_inverse_search,
)
from rfauto.core.mapes import MapesResult, PixelLayout

TARGET = PassbandTarget(
    band_ghz=(5.5, 6.5),
    stop_low_ghz=(0.5, 3.0),
    stop_high_ghz=(9.5, 12.0),
    s21_pass_min_db=-8.0,
    s21_stop_low_max_db=-25.0,
    s21_stop_high_max_db=-12.0,
)
MESH_KWARGS = dict(r_edge=0.01, l_edge=1.5e-10, g_node=0.001, c_node=5e-12)


def _synthetic_result(freqs_ghz: list[float],
                      s21_db: list[float]) -> MapesResult:
    """手造 MapesResult（只含评判器消费的 freq_hz + s_external 字段）。"""
    freq_hz = np.asarray(freqs_ghz, dtype=float) * 1e9
    s = np.zeros((len(freqs_ghz), 2, 2), dtype=complex)
    for k, db in enumerate(s21_db):
        s[k, 1, 0] = 10.0 ** (db / 20.0)
    return MapesResult(
        topology_key="synthetic",
        freq_hz=freq_hz,
        occupancy=np.zeros((1, 1), dtype=bool),
        vias=np.zeros(0, dtype=bool),
        load_impedance=np.zeros(1, dtype=complex),
        z_all=np.zeros((1, 3, 3), dtype=complex),
        z_external=np.zeros((len(freqs_ghz), 2, 2), dtype=complex),
        s_external=s,
    )


class TestJudge:
    def test_hinge_math_hand_computed(self):
        # 手算：通带[1.5,3.5]含 2,3GHz；欠达 = max(0,-12-s21) → 只有 3GHz
        # 的 -14dB 违例 2dB，均值 1.0；低阻带含 1GHz -6dB，泄漏 24dB；
        # 高阻带含 4GHz -26dB，无泄漏。error = 1 + 24 + 0 = 25 → MISS
        result = _synthetic_result([1.0, 2.0, 3.0, 4.0],
                                   [-6.0, -10.0, -14.0, -26.0])
        target = PassbandTarget(
            band_ghz=(1.5, 3.5), stop_low_ghz=(0.5, 1.0),
            stop_high_ghz=(3.5, 4.5),
            s21_pass_min_db=-12.0, s21_stop_low_max_db=-30.0,
            s21_stop_high_max_db=-25.0)
        out = evaluate_design(result, target)
        assert out["pass_violation_db"] == pytest.approx(1.0)
        assert out["stop_low_violation_db"] == pytest.approx(24.0)
        assert out["stop_high_violation_db"] == pytest.approx(0.0)
        assert out["error_db"] == pytest.approx(25.0)
        assert out["grade"] == "MISS"
        assert out["s21_passband_min_db"] == pytest.approx(-14.0)
        assert out["s21_stopband_max_db"] == pytest.approx(-6.0)
        assert out["n_pass_freq"] == 2
        assert out["n_stop_low_freq"] == 1
        assert out["n_stop_high_freq"] == 1

    def test_pass_grade_requires_exact_spec(self):
        # 全频段贴线满足 → 误差 0 → PASS；整体超差 1dB → NEAR（2dB 总和）
        target = PassbandTarget(
            band_ghz=(1.5, 3.5), stop_low_ghz=(0.5, 1.0),
            stop_high_ghz=(3.5, 4.5),
            s21_pass_min_db=-8.0, s21_stop_low_max_db=-6.0,
            s21_stop_high_max_db=-6.0)
        good = _synthetic_result([1.0, 2.0, 4.0], [-7.0, -7.0, -7.0])
        out = evaluate_design(good, target)
        assert out["grade"] == "PASS"
        assert out["error_db"] == 0.0
        near = _synthetic_result([1.0, 2.0, 4.0], [-5.0, -5.0, -5.0])
        out = evaluate_design(near, target)
        assert out["grade"] == "NEAR"
        assert out["error_db"] == pytest.approx(2.0)

    def test_judge_deterministic_on_mapes_kernel(self):
        layout = PixelLayout(n_rows=3, n_cols=3, n_io_ports=2)
        model = build_demo_model(layout, np.linspace(0.5e9, 12e9, 16),
                                 mesh_kwargs=MESH_KWARGS)
        occ = np.array([[1, 0, 1], [0, 1, 0], [1, 1, 0]], dtype=bool)
        a = evaluate_occupancy(model, occ, TARGET)
        b = evaluate_occupancy(model, occ, TARGET)
        assert a == b
        assert set(a["params"]) == set(layout.flatten(occ))
        assert a["topology_key"] == layout.topology_key

    def test_band_without_freq_overlap_rejected(self):
        result = _synthetic_result([1.0, 2.0], [-6.0, -6.0])
        target = PassbandTarget(
            band_ghz=(5.0, 6.0), stop_low_ghz=(0.5, 1.0),
            stop_high_ghz=(6.5, 8.0),
            s21_pass_min_db=-8.0, s21_stop_low_max_db=-30.0,
            s21_stop_high_max_db=-30.0)
        with pytest.raises(ConfigError, match="无交集"):
            evaluate_design(result, target)

    def test_target_validation(self):
        with pytest.raises(ConfigError):
            PassbandTarget(band_ghz=(6.0, 5.0), stop_low_ghz=(0.5, 1.0),
                           stop_high_ghz=(7.0, 8.0), s21_pass_min_db=-8,
                           s21_stop_low_max_db=-25, s21_stop_high_max_db=-12)
        with pytest.raises(ConfigError):
            PassbandTarget(band_ghz=(5.5, 6.5), stop_low_ghz=(0.5, 6.0),
                           stop_high_ghz=(9.5, 12.0), s21_pass_min_db=-8,
                           s21_stop_low_max_db=-25, s21_stop_high_max_db=-12)
        with pytest.raises(ConfigError):
            PassbandTarget(band_ghz=(5.5, 6.5), stop_low_ghz=(0.5, 3.0),
                           stop_high_ghz=(5.0, 12.0), s21_pass_min_db=-8,
                           s21_stop_low_max_db=-25, s21_stop_high_max_db=-12)


class TestProposers:
    def test_random_proposer_deterministic(self):
        import random

        layout = PixelLayout(n_rows=4, n_cols=5, n_io_ports=2)
        rng1, rng2 = random.Random(11), random.Random(11)
        a = propose_random(layout, rng1, p_on=0.5)
        b = propose_random(layout, rng2, p_on=0.5)
        assert a.shape == (4, 5)
        assert (a == b).all()
        assert a.dtype == bool
        with pytest.raises(ConfigError):
            propose_random(layout, random.Random(1), p_on=1.5)

    def test_one_flip_neighbors_complete(self):
        occ = np.array([[1, 0], [0, 1]], dtype=bool)
        neighbors = one_flip_neighbors(occ)
        assert len(neighbors) == 4
        for cand in neighbors:
            assert int(np.count_nonzero(cand != occ)) == 1
        # 行主序：第 k 个候选翻转的是第 k 个像素
        assert (neighbors[0] == np.array([[0, 0], [0, 1]])).all()
        assert (neighbors[3] == np.array([[1, 0], [0, 0]])).all()


class TestSearch:
    @pytest.fixture(scope="class")
    def small_search(self):
        layout = PixelLayout(n_rows=4, n_cols=4, n_io_ports=2)
        model = build_demo_model(layout, np.linspace(0.5e9, 12e9, 16),
                                 mesh_kwargs=MESH_KWARGS)
        return run_inverse_search(model, TARGET, n_random=24,
                                  max_local_steps=4, k_top=5, seed=99)

    def test_contract_and_not_worse_than_random(self, small_search):
        res = small_search
        assert res["ok"]
        assert res["n_evaluated"] >= res["n_random"]
        assert res["n_random"] == 24
        assert res["best"]["error_db"] == pytest.approx(
            res["local_phase"]["final_error_db"])
        # 局部贪心只接受严格改善 → 不劣于随机阶段
        assert res["local_phase"]["improvement_db"] >= 0.0
        assert res["best"]["grade"] in {"PASS", "NEAR", "MISS"}
        errors = [rec["error_db"] for rec in res["top_k"]]
        assert errors == sorted(errors)
        assert len(res["top_k"]) <= 5
        assert all(rec["grade"] in {"PASS", "NEAR", "MISS"}
                   for rec in res["top_k"])

    def test_fully_deterministic(self, small_search):
        layout = PixelLayout(n_rows=4, n_cols=4, n_io_ports=2)
        model = build_demo_model(layout, np.linspace(0.5e9, 12e9, 16),
                                 mesh_kwargs=MESH_KWARGS)
        again = run_inverse_search(model, TARGET, n_random=24,
                                   max_local_steps=4, k_top=5, seed=99)
        a = dict(small_search)
        a.pop("elapsed_s")
        b = dict(again)
        b.pop("elapsed_s")
        assert a == b


class TestAcceptance6x6:
    """§10.18 E12 验收例：6x6 域指定通带逆设计（演示脚本同常数冻结）。"""

    @pytest.fixture(scope="class")
    def demo_result(self):
        layout = PixelLayout(n_rows=6, n_cols=6, n_io_ports=2)
        model = build_demo_model(layout, np.linspace(0.5e9, 12e9, 24),
                                 mesh_kwargs=MESH_KWARGS)
        return run_inverse_search(model, TARGET, n_random=64,
                                  max_local_steps=8, k_top=5, seed=20260912)

    def test_reaches_pass_grade(self, demo_result):
        res = demo_result
        assert res["ok"]
        # 冻结校准数字（2026-09-12 本机实测）：随机 0.4248 → 精修后 0
        assert res["random_phase"]["best_error_db"] == pytest.approx(
            0.4248, abs=1e-3)
        assert res["local_phase"]["steps"] == 2
        assert res["local_phase"]["stop_reason"] == "local_optimum"
        assert res["best"]["error_db"] <= 1e-9
        assert res["best"]["grade"] == "PASS"
        assert res["best"]["n_occupied"] == 20
        assert res["n_evaluated"] == 169
        # 规格余量（评判器产出的物理数字）
        assert res["best"]["s21_passband_min_db"] >= TARGET.s21_pass_min_db
        assert res["best"]["s21_stopband_max_db"] <= \
            TARGET.s21_stop_high_max_db
