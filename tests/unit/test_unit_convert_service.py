"""unit_convert_service 定向门（ge8c 席C7 quantity pint 消费链）。

判据预声明（#118 双独立基准，出处见模块 docstring）：
1. 1 mil = 25.4 µm（国际码制定义，精确）——1 mm→mil = 1000/25.4 逐位；
2. λg·f·√εeff = c0 定义式恒等（εeff 取同一 forward_z0 出口）；
3. 错量纲（frequency→length）双门拒收（仓内 check_dimension 先拒 /
   pint DimensionalityError 兜底）；

4. pint 缺席=skipped 如实（能力不适用非失败）——sys.modules["pint"]=None
   钉通道（#139 同族：monkeypatch 钉住可选依赖通道，两种装态都成立，
   df6⑦ 装 extras 后 skip 转正仍绿）。
"""

from __future__ import annotations

import math

import pytest

from rfauto.service.unit_convert_service import (
    UNIT_CONVERT_SCHEMA,
    convert_quantity,
    convert_quantity_checked,
    mline_exit_quantities,
)

# ── 1. 通用换算通道（pint 已装态） ────────────────────────────────────────────

class TestConvertQuantity:
    def test_exact_mil_anchor(self):
        """1 mm → thou = 1000/25.4（1 thou=25.4 µm 国际码定义，精确换算；
        pint 目标单位名 thou——"mil" 在 pint 是另一无量纲角单位）。"""
        r = convert_quantity({"value": 1.0, "unit": "mm"}, "thou")
        assert r["ok"] is True and "skipped" not in r
        # pint 缩写渲染随版本漂移（0.26.1 把 thou 渲染成 "th"）——钉幅值
        assert r["to"]["unit"] in {"thou", "th"}
        assert r["to"]["magnitude"] == 1000.0 / 25.4
        assert r["in_unit_table"] is False  # mil 不在仓内表——如实透出

    def test_prefix_rescale_in_table(self):
        """GHz → MHz=1000（SI 前缀缩放，仓内表内单位回读真）。"""
        r = convert_quantity({"value": 2.4, "unit": "GHz"}, "MHz")
        assert r["ok"] is True
        assert r["to"]["magnitude"] == pytest.approx(2400.0)
        assert r["in_unit_table"] is True

    def test_resistance_prefix_view(self):
        """47 kohm → ohm 47000（桥出口 SI 值换算回归）。"""
        r = convert_quantity({"value": 47.0, "unit": "kohm"}, "ohm")
        assert r["ok"] is True
        assert r["to"]["magnitude"] == pytest.approx(47000.0)
        assert r["from"]["si_value"] == pytest.approx(47000.0)

    def test_dimension_mismatch_rejected(self):
        """frequency → length：pint DimensionalityError → error 信封。"""
        r = convert_quantity({"value": 1.0, "unit": "GHz"}, "mm")
        assert r["ok"] is False
        assert r["errors"] and "DimensionalityError" in r["errors"][0]

    def test_invalid_inner_quantity_rejected(self):
        """仓内守卫先拒：裸数字/未知单位进 error 清单（fail-closed）。"""
        r1 = convert_quantity(2.4, "mm")
        assert r1["ok"] is False and "裸数值" in r1["errors"][0]
        r2 = convert_quantity({"value": 1.0, "unit": "parsec"}, "mm")
        assert r2["ok"] is False and "未知单位" in r2["errors"][0]

    def test_empty_target_rejected(self):
        r = convert_quantity({"value": 1.0, "unit": "mm"}, "  ")
        assert r["ok"] is False


# ── 2. pint 缺席降级态（通道钉，两种装态都成立） ─────────────────────────────

class TestPintAbsentHonestSkipped:
    def test_convert_skipped_envelope_when_pint_missing(self, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules, "pint", None)
        r = convert_quantity({"value": 1.0, "unit": "mm"}, "thou")
        assert r["ok"] is True and r["skipped"] is True
        assert "rfauto[units]" in r["reason"]  # skipped≠failed：能力不适用
        assert r["from"]["si_value"] == pytest.approx(1e-3)  # 主出口不受影响

    def test_mline_views_degrade_to_skipped_nodes(self, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules, "pint", None)
        r = mline_exit_quantities(1.113, 2.5, 3.66, 0.508)
        assert r["ok"] is True  # 计算器主出口照常
        assert r["views"]["z0_kohm"]["skipped"] is True
        assert r["views"]["lambda_g_thou"]["skipped"] is True


# ── 3. 闭式计算器出口消费链（forward_z0 真跑） ───────────────────────────────

class TestMlineExitChain:
    def test_z0_exit_bitwise_equals_calculator(self):
        """出口 Z0 与计算器逐位同值（包装面零改写，铁律 7）。"""
        from rfauto.core.synthesis import Stackup, forward_z0

        z0_ref, eps_ref = forward_z0(1.113, 2.5, Stackup("judge", 3.66, 0.508))
        r = mline_exit_quantities(1.113, 2.5, 3.66, 0.508)
        assert r["ok"] is True
        assert r["z0_ohm"]["value"] == float(z0_ref)  # 逐位（零换算直传）
        assert r["eps_eff"] == float(eps_ref)
        assert r["z0_ohm"]["si_value"] == pytest.approx(float(z0_ref))
        assert r["z0_ohm"]["dimension"] == "resistance"

    def test_lambda_g_definition_identity(self):
        """λg·f·√εeff = c0 定义式恒等（合成回收 ≤1e-12 相对）。"""
        r = mline_exit_quantities(1.113, 2.5, 3.66, 0.508)
        lam_m = r["lambda_g_m"]["si_value"]
        f_hz = 2.5e9
        ident = lam_m * f_hz * math.sqrt(r["eps_eff"])
        assert ident == pytest.approx(299792458.0, rel=1e-12)

    def test_views_via_pint_channel(self):
        """pint 视图换算正确性：m→thou 锚 + ohm→kohm 前缀（双独立基准）。"""
        r = mline_exit_quantities(1.113, 2.5, 3.66, 0.508)
        lg_thou = r["views"]["lambda_g_thou"]
        assert lg_thou["ok"] is True
        assert lg_thou["to"]["unit"] in {"thou", "th"}  # 缩写渲染随版本
        expected = lg_thou["from"]["si_value"] / 25.4e-6  # 1 thou=25.4 µm 精确
        assert lg_thou["to"]["magnitude"] == pytest.approx(expected)
        z0_k = r["views"]["z0_kohm"]
        assert z0_k["to"]["magnitude"] == pytest.approx(
            z0_k["from"]["si_value"] / 1000.0)


# ── 4. 量纲预检演示面 ────────────────────────────────────────────────────────

class TestCheckedVariant:
    def test_checked_rejects_in_warehouse_first(self):
        r = convert_quantity_checked({"value": 1.0, "unit": "GHz"}, "mm",
                                     "length")
        assert r["ok"] is False
        assert "量纲不匹配" in r["errors"][0]  # 仓内文案（非 pint 异常）

    def test_checked_passes_through_dimension_match(self):
        r = convert_quantity_checked({"value": 1.0, "unit": "mm"}, "thou",
                                     "length")
        assert r["ok"] is True
        assert r["schema"] == UNIT_CONVERT_SCHEMA
