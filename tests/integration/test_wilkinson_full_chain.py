"""Wilkinson 全链路集成测试：build -> solve -> export -> metrics。

轻量 Setup 确保 5 分钟内完成求解：
- 频段 2.3-2.5 GHz（中心频率附近窄带）
- 11 个频点（非 401 点）
- 收敛阈值 delta_s=0.1（宽松，快速收敛）
- 最大 passes=5（限制迭代次数）
- export_touchstone_on_completion 防 gRPC 断连

运行命令：
    pytest tests/integration/test_wilkinson_full_chain.py -m real_edt -v
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_edt


def _get_aedt_version() -> str:
    """根据 AEDT 路径推断版本号。"""
    aedt_path = os.environ.get("RFAUTO_AEDT_PATH", "")
    if "v231" in aedt_path:
        return "2023.1"
    return "2025.1"


def _skip_if_no_aedt():
    """无 AEDT 路径时跳过测试。"""
    aedt_path = os.environ.get("RFAUTO_AEDT_PATH", "")
    if not aedt_path or not Path(aedt_path).exists():
        pytest.skip(f"RFAUTO_AEDT_PATH not set or not exists: {aedt_path}")


@pytest.fixture
def real_hfss_adapter():
    """提供真实的 HfssAdapter 实例（连接 -> yield -> 关闭）。"""
    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.adapters.hfss_session import HfssSession

    HfssSession.reset()
    adapter = HfssAdapter()
    version = _get_aedt_version()
    adapter.connect({
        "desktop_version": version,
        "non_graphical": True,
        "new_desktop_session": True,
    })
    yield adapter
    adapter.close(save=False)


class TestWilkinsonFullChain:
    """Wilkinson 全链路测试：build -> solve -> export -> metrics。"""

    def test_full_chain_build_solve_export_metrics(
        self, real_hfss_adapter, tmp_path
    ):
        """完整链路：建模 -> 轻量求解 -> 导出 Touchstone -> 计算指标。"""
        _skip_if_no_aedt()

        from rfauto.core.interfaces import SolveReport
        from rfauto.models.wilkinson_power_divider.plugin import WilkinsonPDPlugin
        from rfauto.models.wilkinson_power_divider.schema import WilkinsonPDParams

        total_start = time.time()

        # ─── 1. 打开项目 ─────────────────────────────────────────────────
        project_path = str(tmp_path / "wilkinson_full_chain.aedt")
        real_hfss_adapter.open_or_create_project(project_path, "WilkinsonFullChain")
        print("[1/6] 项目已打开")

        # ─── 2. 建模 ─────────────────────────────────────────────────────
        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams()
        plugin.build(real_hfss_adapter, params)
        print("[2/6] 建模完成")

        hfss = real_hfss_adapter.session.hfss

        # ─── 3. 创建轻量 Setup ──────────────────────────────────────────
        # 频段 2.3-2.5 GHz（窄带，中心频率附近）
        # 11 个频点（少点数 = 快）
        # delta_s=0.1（宽松收敛阈值，快速通过）
        # max_passes=5（限制迭代次数）
        setup_name = "Setup1"
        sweep_name = "Sweep1"

        new_setup = hfss.create_setup(name=setup_name)
        new_setup.props["Frequency"] = "2.4GHz"
        new_setup.props["MaxDeltaS"] = 0.1
        new_setup.props["MaximumPasses"] = 5
        new_setup.update()

        hfss.create_linear_count_sweep(
            setup=setup_name,
            unit="GHz",
            start_frequency=2.3,
            stop_frequency=2.5,
            num_of_freq_points=11,
            name=sweep_name,
            save_fields=False,  # 不保存场数据 = 更快
        )

        # 设置求解完成后自动导出 Touchstone（防 gRPC 断连）
        output_dir = str(tmp_path)
        hfss.export_touchstone_on_completion(export=True, output_dir=output_dir)

        print(f"[3/6] Setup 已创建: {setup_name} + {sweep_name}")
        print("      频率 2.3-2.5 GHz, 11 点, delta_s=0.1, max_passes=5")

        # ─── 4. 求解 ─────────────────────────────────────────────────────
        solve_start = time.time()
        report = real_hfss_adapter.solve(setup_name, timeout_s=600)
        solve_elapsed = time.time() - solve_start

        assert isinstance(report, SolveReport), f"求解返回类型错误: {type(report)}"
        assert report.success, f"求解失败: {report.message}"
        print(f"[4/6] 求解完成: {report.passes} passes, "
              f"delta_s={report.delta_s_final:.4f}, 耗时={solve_elapsed:.1f}s")

        # ─── 5. 导出 Touchstone ──────────────────────────────────────────
        # 3 端口网络必须用 .s3p 扩展名（Touchstone 规范 + skrf 从扩展名推断 rank）
        sparams_path = tmp_path / "wilkinson_full_chain.s3p"
        exported = real_hfss_adapter.export_touchstone(sparams_path)
        assert exported.exists(), f"Touchstone 文件未生成: {exported}"
        assert exported.stat().st_size > 100, f"Touchstone 文件过小: {exported.stat().st_size} bytes"
        print(f"[5/6] Touchstone 已导出: {exported} ({exported.stat().st_size} bytes)")

        # ─── 6. 计算指标 ─────────────────────────────────────────────────
        import numpy as np
        import skrf as rf

        network = rf.Network(sparams_path)

        # 基本验证
        assert network.nports == 3, f"端口数错误: 期望 3, 实际 {network.nports}"
        assert network.frequency.npoints == 11, \
            f"频点数错误: 期望 11, 实际 {network.frequency.npoints}"
        print(f"[6/6] S 参数已加载: {network.nports} 端口, {network.frequency.npoints} 频点")

        # 计算关键指标
        network.frequency.f * 1e-9

        # S11（回波损耗）—— 期望 < -10 dB
        s11_db = 20 * np.log10(np.abs(network.s[:, 0, 0]) + 1e-30)
        s11_min = float(np.min(s11_db))

        # S21（插损）—— 期望 ~ -3.0 dB
        s21_db = 20 * np.log10(np.abs(network.s[:, 0, 1]) + 1e-30)
        s21_mean = float(np.mean(s21_db))

        # S32（隔离度）—— 期望 < -10 dB（宽松，因收敛阈值低）
        if network.nports >= 3:
            s32_db = 20 * np.log10(np.abs(network.s[:, 1, 2]) + 1e-30)
            s32_min = float(np.min(s32_db))
        else:
            s32_min = float("nan")

        # 无源性验证（所有 |S| <= 1）
        max_s_abs = float(np.max(np.abs(network.s)))
        is_passive = max_s_abs <= 1.05  # 允许 5% 误差

        # 打印指标摘要
        print("\n" + "=" * 60)
        print("Wilkinson 功分器指标摘要（2.3-2.5 GHz, 11 点）")
        print("=" * 60)
        print(f"  S11 最小值:     {s11_min:>8.2f} dB  (期望 < -10 dB)")
        print(f"  S21 带内均值:   {s21_mean:>8.2f} dB  (期望 ~ -3.0 dB)")
        print(f"  S32 最小值:     {s32_min:>8.2f} dB  (期望 < -10 dB)")
        print(f"  max|S| (无源):  {max_s_abs:>8.4f}     (期望 <= 1.0)")
        print(f"  无源性验证:     {'PASS' if is_passive else 'FAIL'}")
        print("=" * 60)

        # 功能验证断言（宽松阈值，因 delta_s=0.1 不保证精度）
        # 1. S21 应在 -5 到 -1 dB 之间（宽松，仅验证功能）
        assert -6.0 < s21_mean < -1.5, \
            f"S21 带内均值 {s21_mean:.2f} dB 不在合理范围 [-6, -1.5]"

        # 2. 无源性（允许 5% 误差）
        assert is_passive, \
            f"无源性违例: max|S|={max_s_abs:.4f} > 1.05"

        total_elapsed = time.time() - total_start
        print(f"\n全链路完成: 总耗时 {total_elapsed:.1f}s (求解 {solve_elapsed:.1f}s)")
        print("全链路功能验证 PASSED")
