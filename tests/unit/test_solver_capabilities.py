"""A5 求解器能力协议（§10.1 A5）——全注册适配器能力声明单测。

确定性、无网络、无真机：只枚举 EMSolverRegistry、调用 capabilities() 与
离线模板渲染/源码内省，不做任何真实求解。

覆盖：
- 全注册适配器（openEMS/COMSOL/Palace）都有 capabilities() 且字段完整/类型正确；
- capabilities() 两次调用确定性一致；
- 「声明 vs 实现」一致性抽检（声明为真 → 必须有对应实现方法/事实依据）；
- 未知/非法适配器类型显式报错（不静默返回空声明）；
- 不虚报：对已知不支持项断言 False。
"""

from __future__ import annotations

import inspect
import json

import pytest
from pydantic import ValidationError

import rfauto.adapters  # noqa: F401  —— 导入副作用：注册 openems/comsol/palace/ngsolve/meep/elmer
from rfauto.adapters.comsol_adapter import ComsolAdapter
from rfauto.adapters.em_solver_base import (
    CAPABILITY_METHOD_REQUIREMENTS,
    MATERIAL_MODELS,
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
    EMSolverType,
    SolverCapabilities,
    get_global_registry,
    solver_capabilities_for,
)
from rfauto.core.interfaces import AdapterCapabilities

# 期望完整字段表（名称 → 期望类型），含继承自 AdapterCapabilities 的位
EXPECTED_FIELDS: dict[str, type] = {
    "supports_wave_port": bool,
    "supports_lumped_port": bool,
    "supports_field_export": bool,
    "supports_convergence_report": bool,
    "supports_touchstone_export": bool,
    "supports_headless_solve": bool,
    "supports_optimetrics": bool,
    "solver_type": str,
    "dimension": str,
    "material_models": tuple,
    "parallel_backends": tuple,
    "supports_sar": bool,
    "supports_nf2ff": bool,
    "supports_lumped_elements": bool,
    "supported_templates": tuple,
    "requires_license": bool,
    "availability_gate": str,
    "available": bool,
}

BUILTIN_SOLVERS = ("openems", "comsol", "palace", "meep", "elmer")


def _instances() -> dict[str, EMSolverAdapter]:
    """按注册表创建全部已注册适配器实例（不 connect、不求解）。"""
    reg = get_global_registry()
    out: dict[str, EMSolverAdapter] = {}
    for stype in reg.list_available():
        key = str(getattr(stype, "value", stype))
        out[key] = reg.create(stype, EMSolverConfig(solver_type=stype))
    return out


class TestFullRegistrationCoverage:
    """§10.1 A5：全求解器声明单测覆盖。"""

    def test_registry_covers_builtin_solvers(self):
        names = {str(getattr(s, "value", s)) for s in get_global_registry().list_available()}
        assert set(BUILTIN_SOLVERS) <= names

    def test_every_registered_adapter_declares_capabilities(self):
        for name, adapter in _instances().items():
            caps = adapter.capabilities()
            assert isinstance(caps, SolverCapabilities), name
            assert caps.solver_type == name

    def test_capability_fields_complete_and_typed(self):
        declared = set(SolverCapabilities.model_fields)
        assert set(EXPECTED_FIELDS) <= declared
        for name, adapter in _instances().items():
            caps = adapter.capabilities()
            for field, expected in EXPECTED_FIELDS.items():
                value = getattr(caps, field)
                assert isinstance(value, expected), f"{name}.{field}={value!r}"

    def test_capabilities_model_extends_core_adapter_capabilities(self):
        # 与 hfss/fake 的能力声明模型同源（服务层可统一消费）
        assert issubclass(SolverCapabilities, AdapterCapabilities)
        assert set(AdapterCapabilities.model_fields) <= set(SolverCapabilities.model_fields)

    def test_material_models_within_vocabulary(self):
        # 2026-09-15：Elmer 热通道诚实声明 material_models=()（EM 材料词表
        # 对热传导不适用）——改为「非空时才校验 ⊆ MATERIAL_MODELS」，
        # 空声明由 test_elmer_honest 单独钉死，不再强制每通道非空。
        for name, adapter in _instances().items():
            caps = adapter.capabilities()
            if caps.material_models:
                assert set(caps.material_models) <= MATERIAL_MODELS, name

    def test_capabilities_deterministic(self):
        first = _instances()
        second = _instances()
        for name in first:
            a = first[name].capabilities().model_dump()
            b = first[name].capabilities().model_dump()
            c = second[name].capabilities().model_dump()
            assert a == b == c, name

    def test_capabilities_available_matches_is_available(self):
        for name, adapter in _instances().items():
            caps = adapter.capabilities()
            assert caps.available is bool(adapter.is_available()), name

    def test_capabilities_do_not_require_connection(self):
        # 2026-09-15：Elmer 热通道为 2-D 条带网格 → 维度断言放宽为合法域
        # {"2d", "3d"}（不虚报由 test_elmer_honest 钉 dimension=="2d"）。
        # 2026-09-25：+"circuit"（DP-14 N7 qucsator 电路级通道如实声明，
        # 合流门抓出该消费者漏同步——P1.11 test_solver_capabilities 补账）。
        for name, adapter in _instances().items():
            assert adapter._connected is False  # 未连接即应可查能力
            caps = adapter.capabilities()
            assert caps.dimension in ("2d", "3d", "circuit"), name


class TestDeclaredVsImplemented:
    """「声明 vs 实现」一致性抽检。"""

    def test_requirement_map_keys_are_real_fields(self):
        assert set(CAPABILITY_METHOD_REQUIREMENTS) <= set(SolverCapabilities.model_fields)

    @staticmethod
    def _backed(adapter: EMSolverAdapter, flag: str) -> bool:
        methods = CAPABILITY_METHOD_REQUIREMENTS.get(flag, ())
        if any(hasattr(adapter, m) for m in methods):
            return True
        if flag == "supports_touchstone_export":
            return "touchstone" in adapter.supported_output_formats()
        return False

    def test_declared_true_flags_have_implementation(self):
        for name, adapter in _instances().items():
            caps = adapter.capabilities()
            for flag in CAPABILITY_METHOD_REQUIREMENTS:
                if getattr(caps, flag):
                    assert self._backed(adapter, flag), f"{name}.{flag} 声明为真但无实现"

    def test_openems_port_axis_backed_by_templates(self):
        from rfauto.adapters.openems_templates import render_script

        caps = solver_capabilities_for(EMSolverType.OPENEMS)
        assert caps.supports_lumped_port is True
        assert caps.supports_wave_port is False
        # 实际渲染：集总/微带端口存在，波导端口（RectWG 等）不存在
        for template in ("wilkinson", "mline", "dipole", "patch"):
            script = render_script(template, {}, (2.0, 3.0))
            assert ("MSLPort" in script) or ("LumpedPort" in script), template
            assert "RectWG" not in script, template

    def test_openems_templates_match_template_meta(self):
        from rfauto.adapters.openems_templates import TEMPLATE_META

        caps = solver_capabilities_for(EMSolverType.OPENEMS)
        assert set(caps.supported_templates) == set(TEMPLATE_META)

    def test_comsol_lumped_port_backed_by_source(self):
        caps = solver_capabilities_for(EMSolverType.COMSOL)
        src = inspect.getsource(ComsolAdapter)
        assert caps.supports_lumped_port is True
        assert "LumpedPort" in src
        # 数值 TEM 边界模端口完整链（6i③，真机过锚）支撑 wave=True 声明：
        # Port 特征 + numericTEM + 边界模分析步 + StudyStep 解引用在源中
        assert caps.supports_wave_port is True
        for token in ('"Port", 2', '"numericTEM", "1"',
                      'STUDY_STEP_BOUNDARY_MODE', '"StudyStep",'):
            assert token in src, token

    def test_comsol_field_export_backed_by_methods(self):
        caps = solver_capabilities_for(EMSolverType.COMSOL)
        assert caps.supports_field_export is True
        assert callable(getattr(ComsolAdapter, "temperature_field", None))
        assert callable(getattr(ComsolAdapter, "evaluate_volume_series", None))

    def test_palace_port_passthrough_backed_by_config(self, tmp_path):
        """端口透传钉官方 v0.18.1 口径：端口在 Boundaries 分节（无顶层 Ports）。

        官方出处：config-schema.json 顶层 required=五分节、Boundaries 下
        WavePort/LumpedPort 数组（2026-09-22 实测取证，
        runs/palace_spike/schema_fix_plan.md §0）。
        """
        from rfauto.adapters.palace_solver import PalaceSolver

        dummy_exe = tmp_path / "palace-mock"
        dummy_exe.write_text("", encoding="ascii")
        workdir = tmp_path / "run"
        cfg = EMSolverConfig(solver_type=EMSolverType.PALACE,
                             exe_path=str(dummy_exe), working_dir=str(workdir))
        solver = PalaceSolver(cfg)
        assert solver.connect()
        ports = {
            "WavePort": [{"Index": 1, "Attributes": [2], "Mode": 1,
                          "Excitation": 1}],
            "LumpedPort": [{"Index": 2, "Attributes": [3], "R": 50.0,
                            "Excitation": 2}],
        }
        materials = [{"Attributes": [1], "Permittivity": 2.08}]
        assert solver.build_geometry({"mesh_file": "board.msh",
                                      "materials": materials, "ports": ports})
        data = json.loads((workdir / "palace_config.json").read_text(encoding="utf-8"))
        # 顶层 = 官方五分节，无顶层 Ports/Materials（2026-09-22 差距表 A1/A4/A5）
        assert set(data.keys()) == {"Problem", "Model", "Domains", "Boundaries", "Solver"}
        assert "Ports" not in data
        assert data["Problem"]["Type"] == "Driven"
        assert data["Boundaries"]["WavePort"] == ports["WavePort"]
        assert data["Boundaries"]["LumpedPort"] == ports["LumpedPort"]
        caps = solver.capabilities()
        assert caps.supports_wave_port is True and caps.supports_lumped_port is True


class TestHonestDeclarations:
    """不虚报：已知不支持项必须为 False。"""

    def test_openems_honest(self):
        caps = solver_capabilities_for(EMSolverType.OPENEMS)
        assert caps.supports_wave_port is False
        assert caps.supports_field_export is False
        assert caps.supports_convergence_report is False
        assert caps.supports_optimetrics is False
        # WP4.1（2026-09-13）：get_nf2ff/get_sar 已实现（官方 nf2ff/Dipole SAR
        # 教程口径，随包绑定消费），两位翻真；声明 vs 实现由一致性抽检守护
        assert caps.supports_nf2ff is True
        assert caps.supports_sar is True
        assert caps.parallel_backends == ()
        assert caps.requires_license is False
        assert caps.availability_gate == "exe_path"

    def test_comsol_honest(self):
        caps = solver_capabilities_for(EMSolverType.COMSOL)
        # 数值 TEM 边界模端口完整链（6i③）真机过锚后翻真（原 False=仅
        # LumpedPort 口径）
        assert caps.supports_wave_port is True
        assert caps.supports_lumped_port is True
        assert caps.supports_convergence_report is False
        assert caps.supports_optimetrics is False  # 仅端口激励扫描，非通用优化
        assert caps.supports_nf2ff is False
        assert caps.supports_sar is False
        assert caps.requires_license is True  # 每次 solve 占 RF 席位
        assert caps.supported_templates == ("parallel_plate", "mline")
        # tanδ 介质损耗口径（官方 LossTangentDF 组）接入后有耗介质建模
        assert "lossy_dielectric" in caps.material_models

    def test_palace_honest(self):
        caps = solver_capabilities_for(EMSolverType.PALACE)
        assert caps.supports_field_export is False
        assert caps.supports_convergence_report is False
        assert caps.supports_optimetrics is False
        assert caps.supports_nf2ff is False
        assert caps.supports_sar is False
        assert caps.parallel_backends == ()
        assert caps.requires_license is False
        assert caps.supported_templates == ()  # 网格由调用方提供，无模板机制

    def test_meep_honest(self):
        """A1（2026-09-14）：Meep 适配器能力如实声明（本机 CI-only，不虚报引擎理论能力）。"""
        caps = solver_capabilities_for(EMSolverType.MEEP)
        assert caps.supports_wave_port is True   # EigenModeSource 模式端口
        assert caps.supports_lumped_port is False
        assert caps.supports_field_export is False
        assert caps.supports_convergence_report is False
        assert caps.supports_optimetrics is False
        assert caps.supports_nf2ff is False
        assert caps.supports_sar is False
        assert caps.supports_touchstone_export is False  # 仅 CSV 产物
        assert caps.parallel_backends == ()
        assert caps.requires_license is False
        assert caps.supported_templates == ("mline",)
        # 2026-09-15 A1 子项④：tanδ 走常值 D_conductivity（钉频带中心，
        # 官方 Materials 口径）→ lossy_dielectric 翻位（实现见
        # meep_adapter.tand_to_d_conductivity + 模板 SUB）
        assert caps.material_models == ("pec", "lossless_dielectric",
                                        "lossy_dielectric")

    def test_elmer_honest(self):
        """A4 接线（2026-09-15）：Elmer 热通道能力如实声明，逐位钉死。

        VectorHelmholtz 择一收口：EM 求解位 False 是择一结论（开源 FEM EM
        通道=A9 NGSolve），不是待实现占位——理由见 elmer_adapter.py 模块
        docstring；能力面 = D3-2 开源热兜底 + COMSOL ht/Icepak 交叉验证器。
        """
        caps = solver_capabilities_for(EMSolverType.ELMER)
        assert caps.solver_type == "elmer"
        assert caps.supports_wave_port is False
        assert caps.supports_lumped_port is False
        assert caps.supports_touchstone_export is False
        assert caps.supports_nf2ff is False
        assert caps.supports_sar is False
        assert caps.supports_lumped_elements is False
        assert caps.supports_optimetrics is False
        assert caps.supports_convergence_report is False
        assert caps.supports_field_export is True   # temperature_field()
        assert caps.supports_headless_solve is True  # 子进程 ElmerSolver
        assert caps.dimension == "2d"
        assert caps.material_models == ()   # EM 材料词表对热通道不适用（诚实留空）
        assert caps.supported_templates == ("heat_slab_1d",)
        assert caps.requires_license is False   # GPL 开源
        assert caps.availability_gate == "exe_path"
        assert caps.parallel_backends == ()

    def test_mmt_honest(self):
        """DP-1 P2（2026-09-24）：MMT 模匹配通道能力如实声明，逐位钉死。

        纯仓内 numpy 零外部进程零 license（#261 免役/#246 免标）→ 无可用性
        门；无辐射/无场导出/无 nf2ff/SAR（槽线/共面/辐射族仍走 FDTD/FEM）；
        Touchstone 有实现（export_touchstone，skrf z0_ref 基）；supported_
        templates=段表直连无模板机制。
        """
        caps = solver_capabilities_for(EMSolverType.MMT)
        assert caps.solver_type == "mmt"
        assert caps.supports_wave_port is False
        assert caps.supports_lumped_port is False
        assert caps.supports_field_export is False
        assert caps.supports_convergence_report is False
        assert caps.supports_touchstone_export is True
        assert caps.supports_headless_solve is True
        assert caps.supports_optimetrics is False
        assert caps.supports_nf2ff is False
        assert caps.supports_sar is False
        assert caps.supports_lumped_elements is False
        assert caps.dimension == "2d"
        assert caps.material_models == ("pec", "lossless_dielectric",
                                        "lossy_dielectric")
        assert caps.supported_templates == ("chain",)
        assert caps.requires_license is False
        assert caps.availability_gate == ""  # 恒可用（无 exe/配置门）
        assert caps.parallel_backends == ()

    def test_palace_touchstone_not_overclaimed(self):
        """Palace 适配器仅解析 port-S.csv（官方 Driven 结果文件），无 Touchstone
        写出 → 能力位如实 False。

        C-LOW ③：supported_output_formats() 的 6g 遗留 touchstone 声明
        已按实际实现修正为 ["csv"]（消费者 r3_services output_formats 透出
        面），声明 vs 产物两口径现已一致。
        """
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
        from rfauto.adapters.palace_solver import PalaceSolver

        caps = solver_capabilities_for(EMSolverType.PALACE)
        assert caps.supports_touchstone_export is False
        assert not hasattr(PalaceSolver, "export_touchstone")
        assert not hasattr(PalaceSolver, "_export_touchstone")
        # 输出格式声明面同步如实（palace 实际仅产 CSV）
        solver = PalaceSolver(EMSolverConfig(solver_type=EMSolverType.PALACE))
        assert "touchstone" not in solver.supported_output_formats()
        assert "csv" in solver.supported_output_formats()


class TestUnknownAdapterErrors:
    """未知/非法适配器显式报错。"""

    def test_registry_create_unknown_enum_raises(self):
        # A1（2026-09-14）MEEP 已注册（MeepSolver）；2026-09-15 ELMER 已接线
        # 注册（elmer_adapter 导入即注册）——未注册探针改用 Q3D
        # （register_q3d_adapter 存在但无模块级调用、未入全局注册表）
        reg = get_global_registry()
        with pytest.raises(ValueError, match="未注册的求解器"):
            reg.create(EMSolverType.Q3D, EMSolverConfig(solver_type=EMSolverType.Q3D))

    def test_registry_create_unknown_string_raises_cleanly(self):
        reg = get_global_registry()
        with pytest.raises(ValueError, match="cst_custom"):
            reg.create("cst_custom", EMSolverConfig(solver_type="cst_custom"))

    def test_solver_capabilities_for_unknown_raises(self):
        with pytest.raises(KeyError, match="未声明的求解器能力"):
            solver_capabilities_for("no_such_solver")
        # MEEP 已声明（A1）；ELMER 已接线注册（2026-09-15）——未声明枚举改用 Q3D
        with pytest.raises(KeyError):
            solver_capabilities_for(EMSolverType.Q3D)

    def test_invalid_capability_field_type_rejected(self):
        with pytest.raises(ValidationError):
            SolverCapabilities(material_models=123)
        with pytest.raises(ValidationError):
            SolverCapabilities(dimension=object())

    def test_undeclared_custom_solver_gets_conservative_defaults(self):
        class CustomSolver(EMSolverAdapter):
            def connect(self): return True
            def is_available(self): return False
            def build_geometry(self, geometry): return True
            def solve(self): return EMSolverResult(success=False)
            def get_sparams(self): return None, None
            def close(self): pass

        solver = CustomSolver(EMSolverConfig(solver_type="custom_eda"))
        caps = solver.capabilities()
        assert isinstance(caps, SolverCapabilities)
        assert caps.solver_type == "custom_eda"
        assert caps.availability_gate == "undeclared"
        # 未声明通道不做任何能力声明（宁可拒绝也不虚报）
        for flag in CAPABILITY_METHOD_REQUIREMENTS:
            assert getattr(caps, flag) is False, flag
        assert caps.supported_templates == ()
        assert caps.material_models == ()


class TestOpenEMSFacade:
    """兼容门面 OpenEMSAdapter 与注册表声明一致。"""

    def test_facade_capabilities_match_registry_declaration(self):
        from rfauto.adapters.openems_adapter import OpenEMSAdapter

        facade = OpenEMSAdapter()
        caps = facade.capabilities()
        assert isinstance(caps, SolverCapabilities)
        baseline = solver_capabilities_for(EMSolverType.OPENEMS)
        assert caps.model_dump(exclude={"available"}) == baseline.model_dump(exclude={"available"})
        assert caps.available is bool(facade.is_available())

