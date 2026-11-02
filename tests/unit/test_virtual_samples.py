"""virtual_samples 虚拟样本生成器（W4-4 机制层最小闭环）单测。

裁判纪律（#118）：收口实验的地面真相全部用与被测实现无共享代码路径的
独立闭式公式构造（串联 RLC 反射 / 基内单极点族）；判据带正例（生成样本
逐一过 passivity_verdict）+ 负例（脏锚点必红）；复现性 = 同种子两跑逐位
一致（AGENTS 7 确定性红线）；数据完整性红线（#144 家法）= 纯函数零文件
系统写入（测试钉住 cwd 无新文件）。

收口两态对比（test_closing_two_state_mean_gain）：稀疏真实合成样本
（8 点 × 4 个固定训练抽样）±虚拟样本扩充 → pole_residue 训练 → 独立
公式验证集曲线相对 RMSE 均值对比。实测（2026-10-28，本文件钉态）：
    抽样   off      on       比
    7    0.6570   0.5351   0.815
    11   0.4485   0.4284   0.955
    23   0.5056   0.5197   1.028（退化——如实保留，不 cherry-pick）
    31   0.4755   0.4702   0.989
    均值 0.5216   0.4884   0.936（−6.4%）
诚实边界（regime 依赖，module docstring 与交付报告同笔）：基精确+强非
线性人工 regime 下凸组合弦偏置（O(h²) 单侧 Jensen 型）可致退化，鲁棒
增益需消费侧置信度加权（VIRTUAL_WEIGHT_KEY 接口点已预留，W4-3 裁定
不越界）——钉均值方向不钉单抽样方向即此原因。
"""

from __future__ import annotations

import os

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated(isolated):
    """隔离体收编 tests/conftest.py::isolated（T5 三批单源化）。"""
    yield


F_LO_HZ = 1.0e9
F_HI_HZ = 5.0e9
N_FREQ = 81
Z0 = 50.0


def _freq_grid() -> np.ndarray:
    return np.linspace(F_LO_HZ, F_HI_HZ, N_FREQ)


def _rl_curve(r_ohm: float, l_nh: float) -> np.ndarray:
    """独立公式：串联 R-L 单端口反射（正实 Z → 无源），W4-3 同源形态。"""
    z = r_ohm + 2.0j * np.pi * _freq_grid() * l_nh * 1e-9
    return (z - Z0) / (z + Z0)


UNIT_BOUNDS = {"r_ohm": (5.0, 15.0), "l_nh": (1.0, 3.0)}


def _corner_anchors() -> list[dict]:
    """2 参数单位格 4 角锚点（归一化空间 corners，距离计算可手算）。"""
    corners = [(5.0, 1.0), (5.0, 3.0), (15.0, 1.0), (15.0, 3.0)]
    return [{"params": {"r_ohm": r, "l_nh": l_nh},
             "metrics": {"s11_curve": _rl_curve(r, l_nh)}}
            for r, l_nh in corners]


def _rel_rmse(model, val_points, truth) -> float:
    errs = [np.linalg.norm(model.predict_curve(p) - truth(p))
            / np.linalg.norm(truth(p)) for p in val_points]
    return float(np.mean(errs))


# ─── 确定性与纯函数红线 ───────────────────────────────────────────────────────


class TestDeterminismAndPurity:
    def test_same_seed_two_runs_bitwise(self):
        from rfauto.optimization.surrogate import generate_virtual_samples

        anchors = _corner_anchors()
        v1 = generate_virtual_samples(anchors, bounds=UNIT_BOUNDS,
                                      n_blend=6, seed=42)
        v2 = generate_virtual_samples(anchors, bounds=UNIT_BOUNDS,
                                      n_blend=6, seed=42)
        assert len(v1) == len(v2) > 0
        for a, b in zip(v1, v2, strict=False):
            assert a["params"] == b["params"]
            assert np.array_equal(a["metrics"]["s11_curve"],
                                  b["metrics"]["s11_curve"])
            assert a["virtual_weight"] == b["virtual_weight"]
            assert a["virtual"] == b["virtual"]

    def test_different_seed_differs(self):
        from rfauto.optimization.surrogate import generate_virtual_samples

        anchors = _corner_anchors()
        v1 = generate_virtual_samples(anchors, bounds=UNIT_BOUNDS,
                                      n_blend=6, seed=42)
        v2 = generate_virtual_samples(anchors, bounds=UNIT_BOUNDS,
                                      n_blend=6, seed=7)
        diff = any(not np.array_equal(
            a["metrics"]["s11_curve"], b["metrics"]["s11_curve"])
            for a, b in zip(v1, v2, strict=False))
        assert diff

    def test_pure_function_no_filesystem_writes(self, isolated):
        """#144 家法红线：生成器零文件系统写入（cwd 前后清单逐位一致）。"""
        from rfauto.optimization.surrogate import generate_virtual_samples

        before = sorted(os.listdir(isolated))
        anchors = _corner_anchors()
        generate_virtual_samples(anchors, bounds=UNIT_BOUNDS,
                                 n_blend=6, seed=42)
        assert sorted(os.listdir(isolated)) == before


# ─── 判据：无源性正例 / 脏锚点负例 / 凸性与防泄露守护 ─────────────────────────


class TestPassivityAndGuards:
    def test_all_generated_passivity_positive(self):
        from rfauto.optimization.surrogate import generate_virtual_samples
        from rfauto.optimization.surrogate.pole_residue import (
            passivity_verdict,
        )

        virtuals = generate_virtual_samples(_corner_anchors(),
                                            bounds=UNIT_BOUNDS,
                                            n_blend=8, seed=42)
        assert len(virtuals) == 8
        for s in virtuals:
            verdict = passivity_verdict(s["metrics"]["s11_curve"])
            assert verdict["passive"] is True
            assert verdict["sigma_max_in_band"] <= 1.0

    def test_dirty_anchor_rejected_named(self):
        """负例：非无源锚点（×1.5）→ ValueError 点名锚点索引（#316 多报）。

        选材注记：锚点 0（r=5Ω, l=1nH）带内 max|S|≈0.859，×1.5≈1.29>1
        为真违例；若选 max|S| 低的角锚点（如 r=15, l=1 的 0.652），×1.5
        仍 <1 构不成负例（×小系数造不出违例——W4-3 同款教训）。
        """
        from rfauto.optimization.surrogate import generate_virtual_samples

        anchors = _corner_anchors()
        assert float(np.max(np.abs(
            anchors[0]["metrics"]["s11_curve"]))) < 1.0  # 锚点本体无源
        anchors[0]["metrics"]["s11_curve"] = (
            anchors[0]["metrics"]["s11_curve"] * 1.5)
        assert float(np.max(np.abs(
            anchors[0]["metrics"]["s11_curve"]))) > 1.0  # 违例已构成
        with pytest.raises(ValueError, match="锚点 0"):
            generate_virtual_samples(anchors, bounds=UNIT_BOUNDS,
                                     n_blend=4, seed=42)

    def test_blend_params_in_box_and_meta_shape(self):
        from rfauto.optimization.surrogate import (
            VIRTUAL_WEIGHT_KEY,
            generate_virtual_samples,
        )

        virtuals = generate_virtual_samples(_corner_anchors(),
                                            bounds=UNIT_BOUNDS,
                                            n_blend=8, seed=42)
        for s in virtuals:
            assert sorted(s["params"]) == ["l_nh", "r_ohm"]
            for k, (lo, hi) in UNIT_BOUNDS.items():
                assert lo <= s["params"][k] <= hi
            w = s[VIRTUAL_WEIGHT_KEY]
            assert 0.0 <= w <= 1.0
            meta = s["virtual"]
            assert meta["family"] == "anchor_blend"
            assert len(meta["anchors"]) == 2
            assert all(0 <= a < 4 for a in meta["anchors"])
            assert 0.0 < meta["t"] < 1.0
            assert "s11_curve" in s["metrics"]

    def test_leakage_guard_min_dist(self):
        """防泄露：返回虚拟点与所有锚点的归一化距离 ≥ min_rel_dist。"""
        from rfauto.optimization.surrogate import generate_virtual_samples
        from rfauto.optimization.surrogate.virtual_samples import _normalized

        min_rel = 0.6
        virtuals = generate_virtual_samples(
            _corner_anchors(), bounds=UNIT_BOUNDS, n_blend=8, seed=42,
            min_rel_dist=min_rel)
        assert 0 < len(virtuals) < 8  # 守护弃置了近重复候选
        anchor_pts = np.vstack([
            _normalized(s["params"], ["l_nh", "r_ohm"], UNIT_BOUNDS)
            for s in _corner_anchors()])
        for s in virtuals:
            x = _normalized(s["params"], ["l_nh", "r_ohm"], UNIT_BOUNDS)
            dmin = float(np.sqrt(((anchor_pts - x) ** 2).sum(axis=1)).min())
            assert dmin >= min_rel

    def test_input_guards(self):
        from rfauto.optimization.surrogate import generate_virtual_samples

        anchors = _corner_anchors()
        with pytest.raises(ValueError, match="至少需要 2 个锚点"):
            generate_virtual_samples(anchors[:1])
        bad_keys = [{"params": {"r_ohm": 6.0, "extra": 1.0},
                     "metrics": {"s11_curve": _rl_curve(6.0, 2.0)}}]
        with pytest.raises(ValueError, match="参数键集"):
            generate_virtual_samples(anchors + bad_keys)
        mixed = [{"params": {"r_ohm": 6.0, "l_nh": 2.0}, "metrics": {}}]
        with pytest.raises(ValueError, match="CURVE_KEY"):
            generate_virtual_samples(anchors + mixed)
        short = [{"params": {"r_ohm": 6.0, "l_nh": 2.0},
                  "metrics": {"s11_curve": np.ones(5, dtype=complex)}}]
        with pytest.raises(ValueError, match="曲线长度"):
            generate_virtual_samples(anchors + short)
        notcurve = [{"params": {"r_ohm": 6.0, "l_nh": 2.0},
                     "metrics": {"s11_curve": "not-a-curve"}}]
        with pytest.raises(ValueError, match="不可转为复数曲线"):
            generate_virtual_samples(anchors + notcurve)
        with pytest.raises(ValueError, match="n_scale"):
            generate_virtual_samples(anchors, n_scale=5)
        with pytest.raises(ValueError, match="blend_t_range"):
            generate_virtual_samples(anchors, blend_t_range=(0.0, 0.5))
        with pytest.raises(ValueError, match="scale_alpha_range"):
            generate_virtual_samples(anchors, scale_alpha_range=(0.5, 1.5))
        with pytest.raises(ValueError, match="idw_power"):
            generate_virtual_samples(anchors, idw_power=0.0)
        with pytest.raises(ValueError, match="k_nearest"):
            generate_virtual_samples(anchors, k_nearest=0)
        with pytest.raises(ValueError, match="min_rel_dist"):
            generate_virtual_samples(anchors, min_rel_dist=-0.1)
        with pytest.raises(ValueError, match="n_blend"):
            generate_virtual_samples(anchors, n_blend=-1)
        with pytest.raises(ValueError, match="bounds"):
            generate_virtual_samples(anchors, bounds={"r_ohm": (5.0, 15.0)})
        empty = [{"params": {}, "metrics": {}}] * 2
        with pytest.raises(ValueError, match="params 不得为空"):
            generate_virtual_samples(empty)


# ─── 两族形态与消费面接纳 ─────────────────────────────────────────────────────


class TestFamiliesAndConsumers:
    def test_scale_family_semantics(self):
        from rfauto.optimization.surrogate import (
            VIRTUAL_WEIGHT_KEY,
            generate_virtual_samples,
        )

        anchors = _corner_anchors()
        virtuals = generate_virtual_samples(anchors, bounds=UNIT_BOUNDS,
                                            n_blend=0, n_scale=4, seed=42)
        assert len(virtuals) == 4
        for s in virtuals:
            meta = s["virtual"]
            assert meta["family"] == "port_scale"
            i = meta["anchors"][0]
            alpha = meta["alpha"]
            assert 0.5 <= alpha <= 0.9
            assert s["params"] == anchors[i]["params"]  # 几何参数不变
            # 匹配衰减器核：S_v = α·S_i（与实现同式重算，逐位一致）
            assert np.array_equal(
                s["metrics"]["s11_curve"],
                alpha * anchors[i]["metrics"]["s11_curve"])
            assert s[VIRTUAL_WEIGHT_KEY] == alpha

    def test_scale_and_blend_joint_order(self):
        from rfauto.optimization.surrogate import generate_virtual_samples

        virtuals = generate_virtual_samples(_corner_anchors(),
                                            bounds=UNIT_BOUNDS,
                                            n_blend=5, n_scale=2, seed=42)
        families = [s["virtual"]["family"] for s in virtuals]
        assert families.count("anchor_blend") == 5
        assert families.count("port_scale") == 2
        assert families[:5] == ["anchor_blend"] * 5  # blend 先产

    def test_scalar_mode_nn_surrogate_acceptance(self):
        """标量模式（无曲线）：凸组合语义 + NNSurrogate.fit 直接接纳。"""
        from rfauto.optimization.surrogate import (
            NNSurrogate,
            generate_virtual_samples,
        )

        anchors = [{"params": {"r_ohm": r, "l_nh": l_nh},
                    "metrics": {"f0_ghz": 1.0 + r / 50.0 + l_nh,
                                "dip_db": -1.0 - l_nh}}
                   for r, l_nh in [(5.0, 1.0), (5.0, 3.0),
                                   (15.0, 1.0), (15.0, 3.0)]]
        virtuals = generate_virtual_samples(anchors, bounds=UNIT_BOUNDS,
                                            n_blend=6, seed=42)
        assert len(virtuals) == 6
        for s in virtuals:
            # 凸组合语义：混合值落在锚点值域内（凸权重非负和一）
            for k in ("f0_ghz", "dip_db"):
                vals = [a["metrics"][k] for a in anchors]
                assert min(vals) <= s["metrics"][k] <= max(vals)
        model = NNSurrogate(config={
            "bounds": UNIT_BOUNDS, "hidden": 8, "epochs": 50,
            "n_ensemble": 2, "seed": 42, "augmenter": "polynomial_cross"})
        info = model.fit(anchors + virtuals)
        assert info["n_samples"] == 10
        pred = model.predict({"r_ohm": 9.0, "l_nh": 2.0})
        assert set(pred) == {"f0_ghz", "dip_db"}

    def test_pole_residue_fit_accepts_virtual_append(self):
        """曲线模式端到端：同构字典直接并入 fit，n_curves=锚点+虚拟。"""
        from rfauto.optimization.surrogate import (
            PoleResidueSurrogate,
            generate_virtual_samples,
        )

        anchors = _corner_anchors()
        virtuals = generate_virtual_samples(anchors, bounds=UNIT_BOUNDS,
                                            n_blend=6, seed=42)
        cfg = {"bounds": UNIT_BOUNDS, "freq_grid_ghz": (1.0, 5.0),
               "n_freq": N_FREQ, "n_real_poles": 2, "n_cmplx_pairs": 1}
        info = PoleResidueSurrogate(config=cfg).fit(anchors + virtuals)
        assert info["n_curves"] == 4 + 6


# ─── 收口两态对比（PLAN 原文语义） ────────────────────────────────────────────


class TestClosingTwoState:
    def test_closing_two_state_mean_gain(self):
        """稀疏真实合成样本（8 点 × 4 固定抽样）±虚拟样本 → 独立公式验证
        集均值曲线 RMSE 对比：均值方向 on < off（数字表见本文件 docstring，
        含一个退化抽样——如实保留；阈值宽松钉均值方向不钉单抽样）。"""
        from rfauto.optimization.surrogate import (
            PoleResidueSurrogate,
            generate_virtual_samples,
        )
        from rfauto.optimization.surrogate.pole_residue import (
            passivity_verdict,
        )

        freq = np.linspace(0.5, 5.0, N_FREQ) * 1e9

        def truth(p: dict[str, float]) -> np.ndarray:
            # 独立公式：串联 RLC 单端口反射（与被测实现零共享代码路径）
            z = (p["r_ohm"] + 2j * np.pi * freq * p["l_nh"] * 1e-9
                 + 1.0 / (2j * np.pi * freq * p["c_pf"] * 1e-12))
            return (z - Z0) / (z + Z0)

        bounds = {"l_nh": (5.0, 15.0), "c_pf": (0.5, 2.0),
                  "r_ohm": (4.0, 20.0)}
        keys = ("l_nh", "c_pf", "r_ohm")
        cfg = {"bounds": bounds, "freq_grid_ghz": (0.5, 5.0),
               "n_freq": N_FREQ, "head": "ridge"}
        lattice = [(l_nh, c_pf, r_ohm)
                   for l_nh in np.linspace(5, 15, 5)
                   for c_pf in np.linspace(0.5, 2.0, 5)
                   for r_ohm in np.linspace(4, 20, 5)]
        offs, ons = [], []
        for tseed in (7, 11, 23, 31):
            rng = np.random.default_rng(tseed)
            idx = rng.choice(len(lattice), 18, replace=False)
            train = [{"params": dict(zip(keys, lattice[i], strict=False)),
                      "metrics": {"s11_curve": truth(
                          dict(zip(keys, lattice[i], strict=False)))}}
                     for i in idx[:8]]
            val = [dict(zip(keys, lattice[i], strict=False))
                   for i in idx[8:]]
            m_off = PoleResidueSurrogate(config=cfg)
            m_off.fit(train)
            virtuals = generate_virtual_samples(train, bounds=bounds,
                                                n_blend=16, seed=42)
            assert len(virtuals) == 16
            for s in virtuals:
                assert passivity_verdict(
                    s["metrics"]["s11_curve"])["passive"] is True
            m_on = PoleResidueSurrogate(config=cfg)
            info_on = m_on.fit(train + virtuals)
            assert info_on["n_curves"] == 24  # 虚拟样本全数接纳
            offs.append(_rel_rmse(m_off, val, truth))
            ons.append(_rel_rmse(m_on, val, truth))
        assert np.mean(ons) < np.mean(offs)
