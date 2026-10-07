"""feed_offset 口径单源化跨面钉（2026-10-03 #154 收口，ge8b 席 B7）。

背景（真分裂，跨面取值流贯通）：单贴片 feed_offset_mm 曾三种坐标口径并存
——openEMS 渲染自贴片中心（官方教程 x=-off，runs/ 真机产物 simulation.py
字面裁判 FEED_X=-5.5*1e-3）、fake/综合自辐射边 inset 深度（Balanis cos²，
XA-2 闭式输 10.43）、HFSS 探针写在非谐振宽轴（x=+feed_offset，y=0=谐振轴
场节点）。TemplateSpec "patch" 一行同时驱动四面 → 同值异几何静默分裂。

本批统一为**自贴片中心沿谐振轴**（openEMS 官方口径为裁判面不动，综合闭式
off=(L/π)·arcsin√(Rin_t/Rin_edge)、fake R_in=R_edge·sin²(π·off/L)、HFSS
probe (0,-feed_offset)）。本文件钉三向一致 + 跨面值恒等链：

1. render 字面（FEED_X 解析）↔ grid 字面（馈盒边入网点）↔ geometry_spec
   预览（端口/单元）同吃同一自中心值；
2. 综合输出 ↔ 渲染几何隐含 inset 深度 y0=L/2−off ↔ 独立 Balanis 自边
   cos² 复算回收（若任一面回退自边口径，本链当场红）；
3. fake 谷深 == 独立自边复算的 |Γ|（非 50Ω 目标点防 clip 饱和）；
4. HFSS 探针在谐振轴（源级结构钉，单测无 HFSS）；
5. roles 词表映射（键名不动，消费面大——#154 单源化只统一语义不换键）。
"""

from __future__ import annotations

import inspect
import math
import re

import numpy as np
import pytest

from rfauto.adapters.fake_adapter import FakeAdapter
from rfauto.adapters.oe_templates.render_core import geometry_spec
from rfauto.adapters.openems_templates import _near_points, render_script
from rfauto.core.synthesis import (
    patch_fringing_delta_l,
    synthesize_patch,
)

_C_MM_GHZ_LOCAL = 299.792458


def _hand_calc_l_full(er: float, h_mm: float, w_mm: float) -> float:
    """L 全精度独立复算（修前档=总扣 4ΔL；与 XA-5 锚同链）。"""
    er_eff = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 * h_mm / w_mm) ** (-0.5)
    dl = 2.0 * patch_fringing_delta_l(w_mm * 1e-3, h_mm * 1e-3, er_eff) * 1e3
    return _C_MM_GHZ_LOCAL / (2 * 2.4 * math.sqrt(er_eff)) - 2 * dl


_W_MM_NOMINAL = _C_MM_GHZ_LOCAL / (2 * 2.4) * math.sqrt(2 / 4.66)


def _synth_params(rin_t: float = 50.0) -> dict[str, float]:
    """综合设计点（名义 2.4GHz/3.66/0.508），返回渲染/fake 可直接消费的
    圆值参数 dict（recipe 载荷口径）。"""
    res = synthesize_patch(2.4, 3.66, 0.508, rin_t_ohm=rin_t)
    p = res.params
    return {"patch_len_mm": float(p["patch_len_mm"]),
            "patch_w_mm": float(p["patch_w_mm"]),
            "feed_offset_mm": float(p["feed_offset_mm"])}


class TestRenderFaceFromCenterLiteral:
    """三面同吃同一自中心值（render 字面 / grid 字面 / 预览）。"""

    def test_render_grid_preview_same_offset(self):
        params = _synth_params()
        off = params["feed_offset_mm"]
        s = render_script("patch", params, (1.9, 2.9))
        m = re.search(r"FEED_X = (-[0-9.]+) \* 1e-3", s)
        assert m, "渲染字面缺 FEED_X 行（官方口径 x=-feed_offset）"
        assert float(m.group(1)) == pytest.approx(-off)

        # grid 字面：馈盒两条 x 边（FEED_X±0.1mm）必须入网（铁律 #3）
        nx, _ny = _near_points("patch", params)
        for target in (-(off + 0.1) * 1e-3, -(off - 0.1) * 1e-3):
            assert any(abs(v - target) < 1e-9 for v in nx), (target, nx)

        # 预览面：端口 x=−off、单元值同键回传
        spec = geometry_spec("patch", params)
        assert spec["ports"][0]["pos_mm"][0] == pytest.approx(-off)
        assert spec["elements"][0]["feed_offset_mm"] == pytest.approx(off)
        probe = next(b for b in spec["boxes"] if b["name"] == "feed_probe")
        assert probe["start_mm"][0] == pytest.approx(-(off + 0.1))
        assert probe["stop_mm"][0] == pytest.approx(-(off - 0.1))


class TestCrossFaceValueIdentity:
    """综合输出 ↔ 渲染隐含 inset 深度 ↔ 独立 Balanis 自边复算（回收链）。"""

    def test_synthesis_offset_means_center_offset_not_edge_depth(self):
        """若综合回退自边口径（输 y0），L/2−off 就不再等于 y0_ref——当场红。

        y0_ref 用独立 acos 自边闭式（Balanis cos² 变换的正解），off 为
        综合输出（自中心 arcsin 口径）——两者经 off = L/2 − y0 恒等衔接。
        """
        from rfauto.core.synthesis import patch_rin_edge_balanis

        rin_edge = patch_rin_edge_balanis(_W_MM_NOMINAL, 0.508, 2.4)
        l_full = _hand_calc_l_full(3.66, 0.508, _W_MM_NOMINAL)
        y0_ref = (l_full / math.pi) * math.acos(math.sqrt(50.0 / rin_edge))

        params = _synth_params()
        off = params["feed_offset_mm"]
        l_round = params["patch_len_mm"]
        # 自中心口径回收：渲染几何隐含 inset 深度 = L/2 − off ≡ y0_ref
        implied_edge_depth = l_round / 2.0 - off
        assert implied_edge_depth == pytest.approx(y0_ref, abs=0.01)
        # 反向哨兵：off 本身不得等于 y0_ref（自边口径回退时两者重合）
        assert abs(off - y0_ref) > 1.0

    def test_fake_dip_recycles_independent_from_edge_form(self):
        """fake 谷深 == 独立自边 cos² 复算的 |Γ|（非 50Ω 点防 clip 饱和）。

        r_in_ref = (60λ0/W)·cos²(π·y0/L)：y0=L/2−off 为渲染隐含 inset 深度，
        cos² 为 Balanis 自边形式（与实现的 sin² 自中心形式独立）。若 fake
        回退"off 自边"旧义（cos²(π·off/L)），r_in 变为 r_edge·cos²(π·off/L)
        ≠ r_in_ref，谷深当场偏离。
        """
        rin_t = 100.0
        params = _synth_params(rin_t=rin_t)
        # 综合输出为圆值（2 位）——回收链用同源圆值反推 y0，容差吸收圆化
        y0 = params["patch_len_mm"] / 2.0 - params["feed_offset_mm"]
        lambda0_mm = 300.0 / 2.4          # fake 模型常数（docstring 口径）
        r_edge = 60.0 * lambda0_mm / params["patch_w_mm"]
        r_in_ref = r_edge * math.cos(math.pi * y0 / params["patch_len_mm"]) ** 2
        assert r_in_ref == pytest.approx(rin_t, rel=5e-3)   # 设计点回收
        gamma_ref = abs((r_in_ref - 50.0) / (r_in_ref + 50.0))

        ad = FakeAdapter(model_type="patch", n_ports=3,
                         freq_ghz=(1.5, 3.5, 801), f0_ghz=2.4)
        ad.connect({})
        ad.set_variables({k: f"{v}mm" for k, v in params.items()})
        report = ad.solve("main_setup")
        assert report.success
        mag = np.abs(ad.get_sparams().s[:, 0, 0])
        s11_min = float(mag.min())
        # s11_min clip 下限 0.005 / 上限 0.68；0.333 在带内不触 clip
        assert s11_min == pytest.approx(min(max(gamma_ref, 0.005), 0.68),
                                        abs=2e-3)


class TestHfssProbeAxis:
    """HFSS 探针在谐振轴（源级结构钉：探针 y=−feed_offset、x=0）。"""

    def test_probe_on_resonant_axis_from_center(self):
        from rfauto.models.patch_antenna.plugin import PatchAntennaPlugin

        src = inspect.getsource(PatchAntennaPlugin._build_hfss)
        # 旧分裂面：feed_offset 写在 x（=patch_w 非谐振宽轴）——必须绝迹
        assert 'origin=["feed_offset"' not in src
        # 单源口径：探针在 y=−feed_offset（自中心、谐振轴负向，openEMS
        # x=-off 镜像同基）
        assert '"(-feed_offset)"' in src
        # 轴契约：patch box y 向尺寸=patch_len（谐振轴）——探针钉所依赖的
        # 几何前提若被改动，本钉与探针钉须同批联动
        assert 'sizes=["patch_w", "patch_len", "copper_t"]' in src


class TestRolesMappingUnchanged:
    """roles 词表键名不动（消费面大），单源化只统一语义不换键。"""

    def test_patch_role_identity_and_vocabulary(self):
        from rfauto.core.physics_roles import ROLE_CANDIDATES
        from rfauto.models.template_spec import TEMPLATE_SPECS
        from rfauto.models.template_specs import bootstrap_template_specs

        bootstrap_template_specs()
        roles = dict(TEMPLATE_SPECS.get("patch").physics_roles)
        assert roles["feed_offset_mm"] == "feed_offset_mm"
        assert ROLE_CANDIDATES["feed_offset_mm"] == (
            "feed_offset_mm", "feed_offset")

    def test_array_inset_role_pair_documented_by_mapping(self):
        """阵列插入馈 elem_feed_mm（自边缺口深，render_array_eep/fake 阵列
        模型自洽对）仍映射同一角色——双子口径声明在 ROLE_CANDIDATES 注记，
        键名与映射均不动（候选 3 考证结论：阵列子链两侧本就同义，无分裂）。"""
        from rfauto.models.template_spec import TEMPLATE_SPECS
        from rfauto.models.template_specs import bootstrap_template_specs

        bootstrap_template_specs()
        roles = dict(TEMPLATE_SPECS.get("patch_array_1x4").physics_roles)
        assert roles["elem_feed_mm"] == "feed_offset_mm"
