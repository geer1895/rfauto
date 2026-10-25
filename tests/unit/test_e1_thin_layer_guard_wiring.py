"""E1 薄层朝向守卫全渲染器接线测试（aurora_l Wave-E，反馈 P7）。

零仿真（渲染期 Python 面，秒级）：core.stackup.assert_thin_layer（K9 P7
断言，全仓 0/26 渲染器消费 → 本席接线）的接线钉——

① 竖墙场景端到端（mim_cap，P7 病灶原型）：monkeypatch Stackup.from_dict
   把 mim_diel 层注入 15μm（声明 d_um=0.2）→ _mim_cap_layout 渲染期抛
   ModelBuildError 带换向指引（"竖墙"+换扫掠截面朝向）——守卫语义通道
   优先于既有 1e-15 内部错误 ValueError（ModelBuildError 非 ValueError
   子类，类型即区分）；实测/声明比 75（两个数量级，用户病灶量级）。
② 竖墙场景端到端（render_script fleet 落点）：monkeypatch render_core
   命名空间的 sma_launcher_layout 单源，注入 z_top=z_g+15mm（声明基板
   h=0.508mm）→ render_script 渲染期抛 ModelBuildError——夹具抬板跨度
   vs 声明基板厚的跨源对账生效（layout 字面 vs substrate 声明）。
③ 正常场景全绿：接线面 12 模板逐个 render_script 返回脚本文本（守卫
   通过零误伤）——audit 面（test_template_geometry_audit 676 测）零破坏
   的聚焦镜像；自由空间/天线 2 高杆族（无介质层）不在接线面，如实跳过。
④ 单位对齐钉：mim_cap 脚本 D_MIM 字面 = 0.2μm→2.0000000000000002e-07 m
   （to_mm("um")→mm→×1e-3 m 链，K12 换算惯例）；layout 双链对账
   （stackup 链 span ≈ params 链 d——ulp 漂移 2.4e-13 相对，守卫 1%
   rel_tol 为此设计，位级相等是错误口径）。
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import rfauto.adapters.oe_templates.render_core as _render_core
from rfauto.adapters.openems_templates import (
    MIM_CAP_NOMINAL,
    TEMPLATE_NOMINAL,
    _mim_cap_layout,
    render_script,
)
from rfauto.core.errors import ModelBuildError
from rfauto.core.stackup import Stackup
from tests.unit import _geometry_audit_helpers as gh

# 审计口径同款渲染档（mim_cap=0.002 μm 工艺档，sma/isl=0.4 缺省档）
_E1_WIRED_TEMPLATES = (
    # 整脚本渲染器（薄层参数族：μ IPD 工艺 + GaAs 薄膜基板）
    "mim_cap", "interdigital_cap", "octagonal_spiral",
    # render_script fleet 落点（layout 跨源分支 + 声明跨度变体分支）
    "sma_launcher", "isl_shielded", "embedded_ms",
    "suspended_stripline", "stripline", "via", "inverted_ms",
    # 缺省 guided 分支代表（[0, H_SUB] 全板基板）
    "msl_cpw", "patch",
)


# ─── ① 竖墙场景端到端：mim_cap 介质层（P7 病灶原型）────────────────────────


def test_mim_cap_wall_layer_raises_with_p7_guidance(monkeypatch) -> None:
    """声明 0.2μm 实建 15μm（竖墙）→ 渲染期 ModelBuildError 带换向指引。"""
    real_from_dict = Stackup.from_dict

    def wall_from_dict(data):   # 竖墙注入：mim_diel 层 0.2μm → 15μm
        stack = real_from_dict(data)
        layers = tuple(
            dataclasses.replace(ly, thickness_um=15.0)
            if ly.name == "mim_diel" else ly
            for ly in stack.layers)
        return Stackup(substrate=stack.substrate, layers=layers)

    monkeypatch.setattr(Stackup, "from_dict",
                        staticmethod(wall_from_dict))
    with pytest.raises(ModelBuildError) as ei:
        render_script("mim_cap", dict(MIM_CAP_NOMINAL), (2.0, 2.0),
                      mesh_resolution_mm=0.002)
    msg = str(ei.value)
    assert "竖墙" in msg                       # 病灶定性（K9 P7 文案）
    assert "换扫掠截面朝向" in msg             # 换向指引
    assert "实测/声明比 75" in msg             # 两个数量级（15/0.2）


def test_mim_cap_guard_precedes_internal_error_channel(monkeypatch) -> None:
    """守卫通道优先：竖墙场景抛 ModelBuildError 而非既有 1e-15 ValueError

    （ModelBuildError 非 ValueError 子类——若守卫未接线/次序错置，本测
    以 ValueError 红钉住回归）。"""
    real_from_dict = Stackup.from_dict

    def wall_from_dict(data):
        stack = real_from_dict(data)
        layers = tuple(
            dataclasses.replace(ly, thickness_um=15.0)
            if ly.name == "mim_diel" else ly
            for ly in stack.layers)
        return Stackup(substrate=stack.substrate, layers=layers)

    monkeypatch.setattr(Stackup, "from_dict",
                        staticmethod(wall_from_dict))
    with pytest.raises(ModelBuildError):       # 非 ValueError——类型即区分
        _mim_cap_layout(dict(MIM_CAP_NOMINAL), (2.0, 2.0))


# ─── ② 竖墙场景端到端：render_script fleet 落点（sma_launcher 跨源对账）───


def test_sma_launcher_wall_span_raises_via_render_script(monkeypatch) -> None:
    """夹具抬板单源被注入 z_top=z_g+15mm（声明 h=0.508mm）→ 渲染期红。"""
    real_layout = _render_core.sma_launcher_layout

    def wall_layout(p, h_sub_m, base_m, board_m=0.060):
        lay = real_layout(p, h_sub_m, base_m, board_m)
        return {**lay, "z_top": lay["z_g"] + 15e-3}   # 竖墙：15mm vs 0.508mm

    monkeypatch.setattr(_render_core, "sma_launcher_layout", wall_layout)
    with pytest.raises(ModelBuildError) as ei:
        render_script("sma_launcher", dict(TEMPLATE_NOMINAL["sma_launcher"]),
                      gh.band_for("sma_launcher"), mesh_resolution_mm=0.4)
    msg = str(ei.value)
    assert "竖墙" in msg and "换扫掠截面朝向" in msg


# ─── ③ 正常场景全绿：接线面 12 模板零误伤 ─────────────────────────────────


@pytest.mark.parametrize("template", _E1_WIRED_TEMPLATES)
def test_wired_templates_render_green(template) -> None:
    """守卫通过路径：正常名义渲染返回脚本文本（零误伤——零破坏红线）。"""
    mesh_mm = gh.TEMPLATE_MESH_MM.get(template, gh.DEFAULT_MESH_MM)
    text = render_script(template, dict(TEMPLATE_NOMINAL[template]),
                         gh.band_for(template), mesh_resolution_mm=mesh_mm)
    assert isinstance(text, str) and "AddBox" in text


# ─── ④ 单位对齐钉：μm 声明 → m 渲染（K12 换算惯例）────────────────────────


def test_mim_cap_diel_literal_is_um_to_m_aligned() -> None:
    """脚本 D_MIM 字面=2.0000000000000002e-07 m（0.2μm 经 to_mm("um")→mm
    →×1e-3 m 单源；字面为浮点链原值——μm→m 链落字面对齐钉）。"""
    text = render_script("mim_cap", dict(MIM_CAP_NOMINAL), (2.0, 2.0),
                         mesh_resolution_mm=0.002)
    assert "D_MIM = 2.0000000000000002e-07" in text


def test_mim_cap_layout_dual_chain_span_bitwise_agrees() -> None:
    """双链对账（守卫通过态）：stackup 链 z 跨度 ≈ params 链 d。

    容差口径=K9 rel_tol 同源（1%）：双链浮点加法 ulp 漂移实测 2.4e-13
    （相对）——守卫 1% 容差即为此设计（"0.2μm 层容 ±2nm 落格噪声"），
    位级相等是错误口径（本钉以 1e-9 收紧档锚定双链一致性数量级）。
    """
    lay = _mim_cap_layout(dict(MIM_CAP_NOMINAL), (2.0, 2.0))
    assert lay["z_diel"][1] - lay["z_diel"][0] == pytest.approx(
        lay["d"], rel=1e-9)
    assert lay["d"] == pytest.approx(0.2e-6, rel=1e-9)   # 0.2μm → m 终点锚
