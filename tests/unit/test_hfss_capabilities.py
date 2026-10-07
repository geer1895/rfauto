"""ME-23：HFSS 仲裁通道能力声明补齐的一致性测试（2026-09-26）。

背景：HFSS 走 SimulatorAdapter 旧协议且不注册进 EMSolverRegistry，
solver_capabilities_for(EMSolverType.HFSS) 曾抛 KeyError（r3 §1.2 P1 级：
仲裁裁判通道自身零能力声明）。修复=按 openEMS 先例把 _HFSS_CAPABILITIES
集中进 em_solver_base._SOLVER_CAPABILITY_SPECS。

本测试钉三件事：
1. 声明可达：solver_capabilities_for("hfss") 返回声明而非 KeyError；
2. 双协议一致性：新 SolverCapabilities 与 HfssAdapter.capabilities()
   （A5 旧协议 AdapterCapabilities 七位）在共享位上逐位一致——防两处漂移；
3. 诚实性：不虚报（SAR/nf2ff/模板/并行）+license 与材料域事实钉。
"""

from __future__ import annotations

from rfauto.adapters.em_solver_base import (
    MATERIAL_MODELS,
    EMSolverType,
    solver_capabilities_for,
)
from rfauto.adapters.hfss_adapter import HfssAdapter

# 新声明与 A5 旧协议 AdapterCapabilities 的共享位（七位布尔）
_SHARED_FLAGS = (
    "supports_wave_port",
    "supports_lumped_port",
    "supports_field_export",
    "supports_convergence_report",
    "supports_touchstone_export",
    "supports_headless_solve",
    "supports_optimetrics",
)


def test_hfss_capabilities_declared_and_reachable() -> None:
    spec = solver_capabilities_for(EMSolverType.HFSS)
    assert spec.solver_type == "hfss"
    assert spec.availability_gate == "pyaedt+grpc"


def test_hfss_new_declaration_matches_legacy_protocol() -> None:
    """双协议一致性：七共享位与新声明逐位相等（防两处漂移）。"""
    legacy = HfssAdapter().capabilities()
    spec = solver_capabilities_for(EMSolverType.HFSS)
    for flag in _SHARED_FLAGS:
        assert getattr(spec, flag) is getattr(legacy, flag), flag


def test_hfss_honest_non_overclaims() -> None:
    spec = solver_capabilities_for(EMSolverType.HFSS)
    assert spec.supports_sar is False
    assert spec.supports_nf2ff is False
    assert spec.supported_templates == ()
    assert spec.parallel_backends == ()
    assert spec.requires_license is True
    assert spec.dimension == "3d"
    assert len(spec.material_models) > 0
    assert set(spec.material_models) <= MATERIAL_MODELS


def test_hfss_no_longer_undeclared_fallback() -> None:
    """修复前 HFSS 落 _undeclared_capabilities（availability_gate=
    "undeclared"、全 False）——钉住不再走保守回退。"""
    spec = solver_capabilities_for("hfss")
    assert spec.availability_gate != "undeclared"
    assert spec.supports_touchstone_export is True


def test_q3d_still_undeclared() -> None:
    """仅 HFSS 补声明——其余未声明枚举（Q3D）保持 KeyError 原语义。"""
    import pytest

    with pytest.raises(KeyError):
        solver_capabilities_for(EMSolverType.Q3D)
