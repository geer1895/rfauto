"""激励盒内缩守卫单测（ge8e 审查批 F7 回归钉，审查 R4-2 / #253）。

原缺陷：#253"激励盒内缩 ≥2·BASE"无统一 raise 型守卫——slotline 只有起跑
审计记录键（excite_inset_ge2base 落 audit_mesh.json 靠下游消费）、
metasurface/siw 是字面量口径；新模板接入照抄缺省可能静默内缩不足
（#253 症状：Mur-ABC 延迟开启瞬态激起零模 DC 漂移，15ns 内涨到信号 10 倍）。

修法：adapters/oe_templates/inset_guard.py 单源 assert_excitation_inset
（不足即 ValueError 带两值与 #253 引用），三模板渲染面接入（siw_layout /
ms_unit_layout 四分支 / render_marchand2_script Python 侧）——只校验不改
几何（渲染面字节不变性：siw sha256 字节钉与 marchand2 逐字节钉不破）。
"""

from __future__ import annotations

import math

import pytest

from rfauto.adapters.oe_templates.inset_guard import (
    EXCITATION_INSET_MIN_BASE,
    assert_excitation_inset,
)


class TestAssertExcitationInset:
    """守卫本体：不足值 ValueError+足值直通。"""

    def test_sufficient_inset_passes(self):
        base = 0.5e-3
        # 不抛即过：足值直通分支（不足值 ValueError 由下一用例钉）
        assert_excitation_inset(2.0 * base, base, label="恰等值")   # ≥ 边界直通
        assert_excitation_inset(16.0 * base, base, label="siw 现状")
        assert_excitation_inset(16.5 * base, base, label="marchand2 现状")

    def test_insufficient_inset_raises_with_values_and_ref(self):
        base = 0.5e-3
        with pytest.raises(ValueError, match="#253") as ei:
            assert_excitation_inset(1.9 * base, base, label="X 模板")
        msg = str(ei.value)
        assert "1.9" in msg or "0.95" in msg          # 两值（内缩）入报错
        assert "BASE" in msg
        assert "X 模板" in msg

    def test_boundary_equality_passes(self):
        base = 1e-3
        # 守卫语义=内缩 ≥2·BASE（等号直通、严格小于才拒）
        assert_excitation_inset(EXCITATION_INSET_MIN_BASE * base, base)
        with pytest.raises(ValueError):
            assert_excitation_inset(
                math.nextafter(EXCITATION_INSET_MIN_BASE * base, 0.0), base)


class TestTemplateWiring:
    """三模板渲染面接入钉：现状几何全部过门（字节不变性前提）。"""

    def test_siw_layout_passes_guard(self):
        """siw 现状（port_inset=16·BASE）渲染过门（渲染函数内 raise 型）。"""
        from rfauto.adapters.oe_templates.render_siw import siw_layout

        # 与 test_siw_template NOM/BAND 同款（布局路径须无异常走通）
        nom = {"w_mm": 12.1317, "d_mm": 0.6, "s_mm": 1.0,
               "line_len_mm": 63.0724}
        lay = siw_layout(dict(nom), (9.75, 10.25), 0.4e-3, 0.508e-3)
        assert lay["port_inset"] >= 2 * 0.4e-3

    def test_metasurface_layouts_pass_guard(self):
        """metasurface 四分支现状（λ0/16、λ0/8）全部过门。"""
        from rfauto.adapters.oe_templates.render_metasurface import ms_unit_layout

        base = 0.4e-3
        h = 0.508e-3
        for tpl, params in (
            ("ms_patch", {}),
            ("ms_cross", {}),
            ("ms_jcross", {}),
        ):
            lay = ms_unit_layout(tpl, dict(params), (10.0, 14.0), base, h)
            assert "z_src" in lay
        # ms_ring_patch 走 LUT 名义
        lay = ms_unit_layout("ms_ring_patch", {}, (10.0, 14.0), base, h)
        assert "z_src" in lay

    def test_marchand2_render_passes_guard_and_bytes_stable(self):
        """marchand2 渲染过门且字节不变（守卫只在校验面，#312 同款钉）。"""
        from rfauto.adapters.oe_templates.render_slotline import (
            render_marchand2_script,
        )

        text_a = render_marchand2_script((2.0, 4.2))
        text_b = render_marchand2_script((2.0, 4.2))
        assert text_a == text_b
        assert "excite_inset_ge2base" in text_a  # 脚本内审计键仍在（记录面）
