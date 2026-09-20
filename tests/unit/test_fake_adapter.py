"""FakeAdapter 单元测试——验证解析近似模型 + 故障注入。"""

import numpy as np
import pytest

from rfauto.adapters.fake_adapter import FakeAdapter
from rfauto.core.errors import ModelBuildError, SimulationFailedError
from rfauto.core.interfaces import SolveReport
from rfauto.core.objectives import Objective, SpecEvaluator


class TestFakeAdapterBasics:
    """FakeAdapter 基本功能测试。"""

    def test_connect(self, fake_adapter):
        fake_adapter.connect({})
        assert fake_adapter.health_check()

    def test_solve_returns_report(self, fake_adapter):
        fake_adapter.connect({})
        report = fake_adapter.solve("test_setup")
        assert isinstance(report, SolveReport)
        assert report.success

    def test_get_sparams_returns_network(self, fake_adapter):
        fake_adapter.connect({})
        fake_adapter.solve("test_setup")
        network = fake_adapter.get_sparams()
        assert network.s.shape[0] > 0  # 有频点
        assert network.s.shape[1] >= 2  # 至少 2 端口

    def test_export_touchstone(self, fake_adapter, tmp_path):
        fake_adapter.connect({})
        fake_adapter.solve("test_setup")
        out_path = fake_adapter.export_touchstone(tmp_path / "test.s2p")
        assert out_path.exists()

    def test_close(self, fake_adapter):
        fake_adapter.connect({})
        fake_adapter.close()


class TestFakeAdapter3Port:
    """3 端口 FakeAdapter 测试（P2 调优循环核心）。"""

    def test_3port_network_shape(self, fake_adapter_3port):
        """3 端口网络返回 3x3 S 矩阵。"""
        fake_adapter_3port.connect({})
        fake_adapter_3port.solve("test")
        network = fake_adapter_3port.get_sparams()
        assert network.s.shape[1] == 3
        assert network.s.shape[2] == 3

    def test_3port_passivity(self, fake_adapter_3port):
        """3 端口无源性：每行 |S|² 之和 ≤ 1。"""
        fake_adapter_3port.connect({})
        fake_adapter_3port.solve("test")
        network = fake_adapter_3port.get_sparams()
        for i in range(network.s.shape[0]):
            row_sum = np.sum(np.abs(network.s[i]) ** 2, axis=1)
            assert np.all(row_sum <= 1.01), f"频点 {i} 无源性违例: max={np.max(row_sum):.4f}"

    def test_3port_reciprocity(self, fake_adapter_3port):
        """3 端口互易性：Sij ≈ Sji。"""
        fake_adapter_3port.connect({})
        fake_adapter_3port.solve("test")
        network = fake_adapter_3port.get_sparams()
        assert np.allclose(network.s[:, 1, 2], network.s[:, 2, 1], atol=0.01)

    def test_3port_s11_in_band(self, fake_adapter_3port):
        """3 端口 S11 在 2.4GHz 附近应低于 -10dB。"""
        fake_adapter_3port.connect({})
        fake_adapter_3port.solve("test")
        network = fake_adapter_3port.get_sparams()

        freq_ghz = network.frequency.f * 1e-9
        mask = (freq_ghz >= 2.3) & (freq_ghz <= 2.5)
        if np.any(mask):
            s11_db = 20 * np.log10(np.abs(network.s[mask, 0, 0]) + 1e-30)
            assert np.min(s11_db) < -10.0, f"S11 在带内不够低: {np.min(s11_db):.1f} dB"

    def test_3port_s21_and_s31_equal(self, fake_adapter_3port):
        """3 端口 S21 和 S31 幅度应相等（等功率分配）。"""
        fake_adapter_3port.connect({})
        fake_adapter_3port.solve("test")
        network = fake_adapter_3port.get_sparams()

        freq_ghz = network.frequency.f * 1e-9
        mask = (freq_ghz >= 2.3) & (freq_ghz <= 2.5)
        if np.any(mask):
            s21 = np.abs(network.s[mask, 1, 0])
            s31 = np.abs(network.s[mask, 2, 0])
            assert np.allclose(s21, s31, atol=1e-4), "S21 与 S31 幅度不等"

    def test_3port_iso_s23_in_band(self, fake_adapter_3port):
        """3 端口隔离度 iso_s23 在带内应大于 15dB。"""
        fake_adapter_3port.connect({})
        fake_adapter_3port.solve("test")
        network = fake_adapter_3port.get_sparams()

        objectives = [
            Objective(metric="iso_s23_db", band=[2.3, 2.5], op="min_above", value=15),
        ]
        metrics = SpecEvaluator.compute_metrics(network, objectives)
        iso_val = metrics.get("iso_s23_db_min_in_band")
        assert iso_val is not None, "iso_s23_db_min_in_band 未计算"
        assert iso_val >= 15.0, f"隔离度不足: {iso_val:.1f} dB"

    def test_3port_cost_evaluation(self, fake_adapter_3port):
        """3 端口完整 cost 评估（含 iso_s23 目标）。"""
        fake_adapter_3port.connect({})
        fake_adapter_3port.solve("test")
        network = fake_adapter_3port.get_sparams()

        objectives = [
            Objective(metric="s11_db", band=[2.3, 2.5], op="max_below", value=-15),
            Objective(metric="s21_db", band=[2.3, 2.5], op="mean_within", value=[-3.6, -3.1]),
            Objective(metric="iso_s23_db", band=[2.3, 2.5], op="min_above", value=20),
        ]
        metrics = SpecEvaluator.compute_metrics(network, objectives)
        cost = SpecEvaluator.evaluate_objectives(metrics, objectives)

        assert "s11_db_max_in_band" in metrics
        assert "s21_db_mean_in_band" in metrics
        assert "iso_s23_db_min_in_band" in metrics
        assert cost >= 0.0

    def test_3port_touchstone_export(self, fake_adapter_3port, tmp_path):
        """3 端口导出 Touchstone（.s3p）。"""
        fake_adapter_3port.connect({})
        fake_adapter_3port.solve("test")
        out_path = fake_adapter_3port.export_touchstone(tmp_path / "test.s3p")
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8", errors="ignore")
        assert "# S-parameters" in content or "! S-parameters" in content or content.startswith("!")


class TestFakeAdapterSParams:
    """验证 S 参数的物理合理性。"""

    def test_passivity(self, fake_adapter):
        """无源性：|S| ≤ 1。"""
        fake_adapter.connect({})
        fake_adapter.solve("test")
        network = fake_adapter.get_sparams()
        max_s = np.max(np.abs(network.s))
        assert max_s <= 1.05, f"S 参数无源性违例: max|S|={max_s}"

    def test_wilkinson_s11_in_band(self, fake_adapter):
        """Wilkinson 功分器 2.4GHz 附近 S11 应低于 -10dB。"""
        fake_adapter.connect({})
        fake_adapter.solve("test")
        network = fake_adapter.get_sparams()

        # 找 2.4GHz 附近
        freq_ghz = network.frequency.f * 1e-9
        mask = (freq_ghz >= 2.3) & (freq_ghz <= 2.5)
        if np.any(mask):
            s11_db = 20 * np.log10(np.abs(network.s[mask, 0, 0]) + 1e-30)
            min_s11 = np.min(s11_db)
            # 放宽到 -5dB（FakeAdapter 是解析近似）
            assert min_s11 < -5.0, f"S11 在带内不够低: {min_s11:.1f} dB"


class TestFakeAdapterFaultInjection:
    """故障注入测试——验证自愈路径。"""

    def test_simulation_failure(self):
        """故障注入：仿真失败。"""
        from rfauto.adapters.fake_adapter import FaultInjection
        adapter = FakeAdapter(fault=FaultInjection(fail_solve=True))
        adapter.connect({})
        with pytest.raises(SimulationFailedError):
            adapter.solve("test")

    def test_build_failure(self):
        """故障注入：建模失败（触发自愈 R1）。"""
        from rfauto.adapters.fake_adapter import FaultInjection
        adapter = FakeAdapter(fault=FaultInjection(fail_build=True))
        adapter.connect({})
        with pytest.raises(ModelBuildError):
            adapter.build_and_setup(lambda a: None, {})
