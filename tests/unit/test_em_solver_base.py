"""模块化 EM 求解器 + KiCad P-Cell 单元测试。"""

from __future__ import annotations

from pathlib import Path

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverRegistry,
    EMSolverResult,
    EMSolverType,
    get_global_registry,
)
from rfauto.adapters.kicad_pcell import (
    Pad,
    PCBDesign,
    PCBGenerationResult,
    Trace,
    Via,
    create_microstrip_pcb,
)


class TestEMSolverBase:
    """EM 求解器基类测试。"""

    def test_solver_types(self):
        """求解器类型枚举。"""
        assert EMSolverType.OPENEMS.value == "openems"
        assert EMSolverType.MEEP.value == "meep"
        assert EMSolverType.HFSS.value == "hfss"

    def test_config_creation(self):
        """配置创建。"""
        config = EMSolverConfig(
            solver_type=EMSolverType.OPENEMS,
            freq_range_ghz=(1.0, 5.0),
        )
        assert config.solver_type == EMSolverType.OPENEMS

    def test_result_creation(self):
        """结果创建。"""
        result = EMSolverResult(success=True, message="OK")
        assert result.success

    def test_result_to_dict(self):
        """结果序列化。"""
        import numpy as np
        result = EMSolverResult(
            success=True,
            freq_ghz=np.array([1.0, 2.0]),
            s_params=np.zeros((2, 2, 2)),
            message="test",
        )
        d = result.to_dict()
        assert d["n_freq_points"] == 2
        assert d["n_ports"] == 2


class TestEMSolverRegistry:
    """求解器注册表测试。"""

    def test_register_and_create(self):
        """注册和创建。"""
        registry = EMSolverRegistry()

        # 创建一个简单的测试求解器
        class TestSolver(EMSolverAdapter):
            def connect(self): return True
            def is_available(self): return True
            def build_geometry(self, g): return True
            def solve(self): return EMSolverResult(success=True)
            def get_sparams(self): return None, None
            def close(self): pass

        registry.register(EMSolverType.FAKE, TestSolver)
        assert registry.is_registered(EMSolverType.FAKE)

        solver = registry.create(EMSolverType.FAKE, EMSolverConfig(solver_type=EMSolverType.FAKE))
        assert isinstance(solver, TestSolver)

    def test_list_available(self):
        """列出可用求解器。"""
        registry = EMSolverRegistry()
        registry.register(EMSolverType.OPENEMS, type(None))
        available = registry.list_available()
        assert EMSolverType.OPENEMS in available

    def test_global_registry(self):
        """全局注册表。"""
        registry = get_global_registry()
        assert isinstance(registry, EMSolverRegistry)


class TestKiCadPCell:
    """KiCad P-Cell 测试。"""

    def test_trace_creation(self):
        """走线创建。"""
        trace = Trace(start=[0, 0], end=[10, 0], width=1.0)
        assert trace.width == 1.0
        assert trace.layer == "F.Cu"

    def test_via_creation(self):
        """过孔创建。"""
        via = Via(position=[5, 5], drill=0.5, pad=1.0)
        assert via.drill == 0.5

    def test_pad_creation(self):
        """焊盘创建。"""
        pad = Pad(position=[0, 0], size=[2, 1], shape="rect")
        assert pad.shape == "rect"

    def test_pcb_design(self):
        """PCB 设计创建。"""
        design = PCBDesign(
            board_size=[50, 30],
            traces=[Trace(start=[0, 0], end=[10, 0], width=1.0)],
            vias=[Via(position=[5, 5], drill=0.5, pad=1.0)],
        )
        assert len(design.traces) == 1
        assert len(design.vias) == 1

    def test_pcb_design_to_dict(self):
        """PCB 设计序列化。"""
        design = PCBDesign(
            traces=[Trace(start=[0, 0], end=[10, 0], width=1.0)],
        )
        d = design.to_dict()
        assert len(d["traces"]) == 1
        assert d["traces"][0]["width"] == 1.0

    def test_generation_result(self):
        """生成结果。"""
        result = PCBGenerationResult(
            success=True,
            output_path="test.kicad_pcb",
            n_traces=1,
        )
        assert result.success
        assert result.n_traces == 1


class TestCreateMicrostripPCB:
    """微带线 PCB 快捷函数测试。"""

    def test_create_without_kicad(self, tmp_path):
        """没有 KiCad 时应返回失败；有 KiCad 时产物只落 tmp_path。

        CWD 卫生钉（ge6 followUp，ge5 月终门两次再生实证）：本测试曾以
        相对路径 ``test.kicad_pcb`` 调真机生成——KiCad 在位的开发机上每次
        全量门都在 pytest CWD（仓根）再生 test.kicad_p* 三个产物文件。
        改 tmp_path 后生成面不再污染仓根。
        """
        out = tmp_path / "test.kicad_pcb"
        result = create_microstrip_pcb(
            output_path=str(out),
            width_mm=1.0,
            length_mm=10.0,
        )
        # 如果 KiCad 不存在，应该失败
        if not Path(r"E:\KiCad\bin\python.exe").exists():
            assert not result.success
        else:
            # KiCad 在位：真机子进程成败皆如实（生成链自身健康另有
            # test_kicad_pcell 面）；本测试只钉 CWD 卫生——生成成功时
            # 产物必须落 tmp_path
            if result.success:
                assert out.is_file()
        cwd_new = {p.name for p in Path.cwd().glob("test.kicad_p*")}
        assert not cwd_new, f"测试产物泄漏进 CWD: {sorted(cwd_new)}"
