"""多模型契约测试（审查修复 C4）。

审查发现的原始问题：run_once 的 fake 模式硬编码 3 端口 wilkinson——
branchline（4 端口）/ patch（2 端口）的 fake 仿真产出的是错误模型的数据；
branchline 解析模型 f0 硬编码 2.4，参数变化无响应；FakeAdapter 未播种随机。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


class TestContractForNPorts:
    def test_three_ports_matches_legacy_default(self):
        from rfauto.core.contracts import AdsExchangeContract
        c = AdsExchangeContract.for_n_ports(3)
        assert c.touchstone.port_order == ["input", "output_1", "output_2"]
        assert c == AdsExchangeContract()  # 与历史默认完全一致

    def test_four_ports_branchline(self):
        from rfauto.core.contracts import AdsExchangeContract
        c = AdsExchangeContract.for_n_ports(4)
        assert c.touchstone.port_order == ["input", "output_1", "output_2", "output_3"]

    def test_one_port_rejects_or_accepts(self):
        from rfauto.core.contracts import AdsExchangeContract
        with pytest.raises(ValueError):
            AdsExchangeContract.for_n_ports(0)

    def test_plugin_metadata(self):
        from rfauto.models.registry import get
        assert get("wilkinson_power_divider").n_ports == 3
        assert get("branchline_coupler").n_ports == 4
        # 0da followUp②：单馈贴片物理 1 端口（与 TEMPLATE_META/docs meta 一致）
        assert get("patch_antenna").n_ports == 1


class TestRunOnceMultiModel:
    """run_once(fake) 必须按插件端口数产出正确扩展名的 Touchstone。"""

    def _run(self, monkeypatch, tmp_path, recipe_name):
        monkeypatch.chdir(tmp_path)
        recipe_path = Path(__file__).parent.parent.parent / "recipes" / recipe_name
        from rfauto.service.api import run_once
        result = run_once(recipe_path)
        assert result["ok"], result.get("errors")
        return result, tmp_path

    def test_run_once_branchline_s4p(self, tmp_path, monkeypatch):
        result, _ = self._run(monkeypatch, tmp_path, "branchline_coupler_v1.yaml")
        run_dir = Path(result["run_dir"])
        snp = list((run_dir / "results").glob("params.s4p"))
        assert snp, f"应产出 params.s4p，实际: {list((run_dir / 'results').glob('*'))}"
        # 4 端口网络的指标可计算
        assert result["metrics"], "metrics 不应为空"

    def test_run_once_patch_s1p(self, tmp_path, monkeypatch):
        """0da followUp② 回归钉：单馈 patch fake 链产出 1 端口 .s1p
        （旧口径借 2 端口形状落 .s2p，与 HFSS 设计实际 1 端口相悖）。"""
        result, _ = self._run(monkeypatch, tmp_path, "patch_antenna_v1.yaml")
        run_dir = Path(result["run_dir"])
        snp = list((run_dir / "results").glob("params.s1p"))
        assert snp, f"应产出 params.s1p，实际: {list((run_dir / 'results').glob('*'))}"
        # 回读 skrf 1 端口网络可解析（扩展名=rank 推断依据，#248）
        import skrf
        net = skrf.Network(str(snp[0]))
        assert net.s.shape[1:] == (1, 1)

    def test_run_once_wilkinson_still_s3p(self, tmp_path, monkeypatch):
        """回归保护：wilkinson 仍为 3 端口 .s3p（历史行为不变）。"""
        result, _ = self._run(monkeypatch, tmp_path, "wilkinson_pd_v1.yaml")
        run_dir = Path(result["run_dir"])
        assert list((run_dir / "results").glob("params.s3p"))


class TestFakeAdapterSeeding:
    def test_same_seed_reproducible(self):
        """同配置两次求解必须逐点一致（可复现）。"""
        from rfauto.adapters.fake_adapter import FakeAdapter

        def solve_once():
            a = FakeAdapter(n_ports=3, seed=123)
            a.connect({})
            a.solve("main_setup")
            n = a.get_sparams()
            a.close()
            return n.s

        s1, s2 = solve_once(), solve_once()
        np.testing.assert_array_equal(s1, s2)

    def test_branchline_responds_to_arm_len(self):
        """branchline 解析模型必须对 arm_len 变化有响应（优化回路有信号）。"""
        from rfauto.adapters.fake_adapter import FakeAdapter

        def solve_with(arm_len_mm):
            a = FakeAdapter(model_type="branchline", n_ports=4, freq_ghz=(1.0, 4.0, 201))
            a.connect({})
            a.set_variables({"arm_len_mm": f"{arm_len_mm}mm"})
            a.solve("main_setup")
            s11_db = 20 * np.log10(np.abs(a.get_sparams().s[:, 0, 0]) + 1e-30)
            a.close()
            return s11_db

        s11_short = solve_with(16.0)   # f0 上移
        s11_design = solve_with(20.5)  # f0 ≈ 2.4GHz
        # 臂长变化应显著改变 S11 曲线（f0 移动）
        assert np.max(np.abs(s11_short - s11_design)) > 0.5, (
            "branchline 解析模型对 arm_len 无响应——优化回路将拿不到梯度信号"
        )


class TestOptimizerMultiModel:
    def test_tune_branchline_fake(self, tmp_path, monkeypatch):
        """run_optimization(fake) + branchline 配方：4 端口链路完整可跑。"""
        import shutil

        monkeypatch.chdir(tmp_path)
        src = Path(__file__).parent.parent.parent / "recipes" / "branchline_coupler_v1.yaml"
        recipe_path = tmp_path / "branchline.yaml"
        shutil.copy2(src, recipe_path)

        from rfauto.optimization.optimizer import run_optimization
        result = run_optimization(
            recipe_path, adapter_name="fake", max_trials=4,
            study_name="c4_branchline_test",
        )
        assert result["ok"], result.get("errors")
        assert result["trials_completed"] == 4, (
            f"4 个 trial 应全部完成（非剪枝），实际: {result}"
        )
        assert result["best_cost"] is not None
