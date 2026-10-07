"""F-J.1 分层导体表面阻抗（ENIG 三层 TL 级联闭式）单测。

裁判口径（#118：独立推导优先，不引用被测实现自证）：
- 极限行为由级联式独立推导：
  * 单层退化（只有半无限基底）：Z_in = (1+j)*Rs_base——与既有
    smooth_surface_resistance 逐位对拍（分层递推的极限一致性）；
  * 厚层极限（t >> delta）：代数上 Z_i*(Z_L+Z_i)/(Z_i+Z_L) = Z_i
    （顶层自蔽、底层不可见）；
  * 薄层极限（t -> 0）：ch->1、sh->gamma*t，Z_in -> Z_L（镀层透明），
    一阶增量 = x*(1+j)*(Z_i^2 - Z_L^2)/Z_i。
- ENIG 抬升倍数独立推导（wave-matrix 级联 + tanh 形式双路径互证）：不透明 Ni
  极限 r_eff/Rs_cu = sqrt(rho_rel) = 2.0（rho_Ni = 4x rho_cu）；缺省 ENIG
  实测/推导 1 GHz ≈ 1.68（t_Ni/delta_Ni ≈ 0.72 过渡区 + 薄 Au 互置，且
  x_eff > r_eff 相位偏离 45°）、10 GHz ≈ 1.96（趋近不透明）。任务书"3-6x
  松界"判为 NiP 电阻率分散（3-6x rho_cu）口径而非倍数本身——断言窗取
  推导覆盖窗 [1.5, 2.5] + 松界 <6.0，与任务书期望的偏差如实登记。
- 独立参考实现：tanh 形式（与被测 ch/sh 形式不同算术路径）+ cmath。

全部测试确定性、无网络、无求解器、无真机。
"""

from __future__ import annotations

import cmath
import math
from itertools import pairwise

import pytest

from rfauto.core.conductor_loss import (
    FINISH_NOTE_KEYS,
    enig_stack,
    finish_qualitative_note,
    layered_surface_impedance,
    skin_depth,
    smooth_surface_resistance,
)

#: 铜电导率 [S/m]（与既有 test_conductor_loss 同口径）
SIGMA_CU = 5.8e7
#: 金电导率 [S/m]（体金通用值）
SIGMA_AU = 4.1e7


def _cu_substrate() -> dict:
    return {"material": "cu", "conductivity_s_per_m": SIGMA_CU}


def _rs(freq_hz: float, sigma: float) -> float:
    return smooth_surface_resistance(freq_hz, sigma)


def _ref_zin(freq_hz: float, stack: list[tuple[float, float | None]]) -> complex:
    """独立参考实现：tanh 形式逐层递推（顶→基底序；基底 t=None 半无限）。

    与被测实现的 ch/sh 形式是同一代数式的不同算术路径（cmath.tanh
    独立裁判），非同源自证。
    """
    z = _rs(freq_hz, stack[-1][0]) * (1 + 1j)
    for sigma, t in reversed(stack[:-1]):
        z_i = _rs(freq_hz, sigma) * (1 + 1j)
        tanh_gt = cmath.tanh((1 + 1j) * (t / skin_depth(freq_hz, sigma)))
        z = z_i * (z + z_i * tanh_gt) / (z_i + z * tanh_gt)
    return z


# ─── 单层退化（与既有函数逐位对拍） ───────────────────────────────────────────


class TestSingleLayerDegenerate:
    def test_bitwise_matches_smooth_surface_resistance(self):
        for freq in (1e9, 10e9, 2.45e9):
            for sigma in (SIGMA_CU, SIGMA_AU, 1.45e7):
                out = layered_surface_impedance(
                    freq, [{"material": "base", "conductivity_s_per_m": sigma}]
                )
                expected = _rs(freq, sigma) * (1 + 1j)
                assert out["z_in_complex"] == expected  # 逐位（实虚部全等）

    def test_rho_rel_substrate_bitwise(self):
        # rho_rel = 1.0 的基底 ≡ 直接给 conductivity（同一除法路径）
        via_rho = layered_surface_impedance(
            1e9, [{"material": "cu", "rho_rel": 1.0}]
        )
        via_sigma = layered_surface_impedance(1e9, [_cu_substrate()])
        assert via_rho["z_in_complex"] == via_sigma["z_in_complex"]

    def test_single_layer_xeff_equals_reff(self):
        # 良导体表面阻抗相位 45°：x_eff == r_eff（逐位）
        out = layered_surface_impedance(1e9, [_cu_substrate()])
        assert out["x_eff"] == out["r_eff"]


# ─── 厚层 / 薄层极限 ──────────────────────────────────────────────────────────


class TestLimits:
    def test_thick_top_layer_hides_all_below_bitwise(self):
        # Au 100µm ≈ 40δ_Au@1GHz（>= 20 渐近阈值）→ Z_in == 顶层 Z_au 逐位
        layers = [
            {"material": "au", "thickness_m": 100e-6, "conductivity_s_per_m": SIGMA_AU},
            {"material": "ni", "thickness_m": 200e-6, "conductivity_s_per_m": 1.45e7},
            _cu_substrate(),
        ]
        out = layered_surface_impedance(1e9, layers)
        assert out["z_in_complex"] == _rs(1e9, SIGMA_AU) * (1 + 1j)

    def test_thick_ni_over_cu_two_layer_bitwise(self):
        # 10 GHz：delta_Ni ≈ 1.32µm，200µm ≈ 151δ >= 20 → Z_in == Z_Ni 逐位
        layers = [
            {"material": "ni", "thickness_m": 200e-6, "conductivity_s_per_m": 1.45e7},
            _cu_substrate(),
        ]
        out = layered_surface_impedance(10e9, layers)
        assert out["z_in_complex"] == _rs(10e9, 1.45e7) * (1 + 1j)

    def test_asymptotic_ratio_is_sqrt_rho_rel(self):
        # 独立推导锚：不透明单金属镀层 r_eff/Rs_cu = sqrt(sigma_cu/sigma_layer)
        layers = [
            {"material": "ni", "thickness_m": 200e-6, "conductivity_s_per_m": 1.45e7},
            _cu_substrate(),
        ]
        out = layered_surface_impedance(10e9, layers)
        ratio = out["r_eff"] / _rs(10e9, SIGMA_CU)
        assert ratio == pytest.approx(math.sqrt(SIGMA_CU / 1.45e7), rel=1e-9)

    def test_zero_thickness_coating_exact_passthrough(self):
        with_au0 = layered_surface_impedance(
            1e9,
            [{"material": "au", "thickness_m": 0.0, "conductivity_s_per_m": SIGMA_AU},
             _cu_substrate()],
        )
        bare = layered_surface_impedance(1e9, [_cu_substrate()])
        assert with_au0["z_in_complex"] == bare["z_in_complex"]  # 逐位
        assert any("passthrough" in note for note in with_au0["regime_notes"])

    @pytest.mark.parametrize(
        ("t_coat", "rtol"), [(1e-12, 1e-5), (1e-10, 1e-3)]
    )
    def test_thin_coating_converges_to_substrate(self, t_coat, rtol):
        # t -> 0：Z_in -> 基底铜值（推导一阶偏差 ~0.5*t/delta）
        layers = [
            {"material": "au", "thickness_m": t_coat, "conductivity_s_per_m": SIGMA_AU},
            {"material": "ni", "thickness_m": t_coat, "conductivity_s_per_m": 1.45e7},
            _cu_substrate(),
        ]
        out = layered_surface_impedance(1e9, layers)
        bare = layered_surface_impedance(1e9, [_cu_substrate()])
        assert out["z_in_complex"] == pytest.approx(
            bare["z_in_complex"], rel=rtol, abs=0.0
        )

    def test_thin_limit_monotone_in_ni_thickness(self):
        # 镀层加厚：r_eff 从裸铜值单调升向 Ni 主导值（推导 1.0 -> ~2.0）
        r_effs = []
        for t_ni_um in (0.05, 0.2, 0.5, 1.0, 2.0, 3.0, 6.0):
            layers = [
                {"material": "au", "thickness_m": 7.5e-8,
                 "conductivity_s_per_m": SIGMA_AU},
                {"material": "ni", "thickness_m": t_ni_um * 1e-6,
                 "conductivity_s_per_m": 1.45e7},
                _cu_substrate(),
            ]
            r_effs.append(layered_surface_impedance(1e9, layers)["r_eff"])
        assert all(b > a for a, b in pairwise(r_effs))


# ─── ENIG 三层封装 ────────────────────────────────────────────────────────────


class TestEnig:
    @pytest.mark.parametrize("freq_hz", [1e9, 10e9])
    def test_lift_ratio_derived_band(self, freq_hz):
        # 独立推导（wave-matrix + tanh 双路径互证）：1 GHz ≈ 1.68（Ni 过渡区
        # x≈0.72 拉低），10 GHz ≈ 1.96（趋近不透明极限 sqrt(4)=2.0）。
        # 窗 [1.5, 2.5] 为推导覆盖窗；<6.0 为任务书"3-6x 松界"的宽容上界
        # （NiP ρ 分散到 6x 铜时 sqrt(6)*1.45≈3.6 仍在界内）。
        out = enig_stack(freq_hz)
        ratio = out["r_eff"] / _rs(freq_hz, SIGMA_CU)
        assert 1.5 <= ratio <= 2.5
        assert ratio < 6.0

    def test_power_law_sqrt_f_in_band(self):
        # r_eff ~ sqrt(f) 带内形态：10G/1G 比值 = sqrt(10) * (带内抬升比
        # 1.96/1.68)，总斜率指数 ~0.57（>0.5 属推导内形态：Ni 随 f 由过渡区
        # 走向不透明，非数值伪象）。
        r1 = enig_stack(1e9)["r_eff"]
        r10 = enig_stack(10e9)["r_eff"]
        assert r10 > r1
        exponent = math.log(r10 / r1) / math.log(10.0)
        assert 0.50 <= exponent <= 0.65

    def test_au_layer_small_but_visible_share(self):
        # 独立推导：薄 Au（x≈0.03）对 r_eff 份额 ~5%（Ni 过渡区放大），
        # 非 <1% 可忽略——断言 (0, 15%) 窗。
        full = enig_stack(1e9)
        no_au = layered_surface_impedance(
            1e9,
            [{"material": "ni", "thickness_m": 3.0e-6, "conductivity_s_per_m": 1.45e7},
             _cu_substrate()],
        )
        rel = abs(full["r_eff"] - no_au["r_eff"]) / no_au["r_eff"]
        assert 0.0 < rel < 0.15

    def test_thicker_ni_raises_reff(self):
        r3 = enig_stack(1e9, ni_thickness_m=3.0e-6)["r_eff"]
        r6 = enig_stack(1e9, ni_thickness_m=6.0e-6)["r_eff"]
        assert r6 > r3

    def test_matches_manual_layered_call_bitwise(self):
        manual = layered_surface_impedance(
            1e9,
            [
                {"material": "au", "thickness_m": 7.5e-8,
                 "conductivity_s_per_m": SIGMA_AU},
                {"material": "ni", "thickness_m": 3.0e-6,
                 "conductivity_s_per_m": SIGMA_CU / 4.0},
                _cu_substrate(),
            ],
        )
        assert enig_stack(1e9) == manual  # 逐位（缺省 sigma_ni = sigma_cu/4）

    def test_sigma_ni_default_equals_cu_over_4(self):
        explicit = enig_stack(1e9, sigma_ni=SIGMA_CU / 4.0)
        assert enig_stack(1e9) == explicit

    def test_sigma_ni_override_changes_result(self):
        low = enig_stack(1e9, sigma_ni=SIGMA_CU / 3.0)["r_eff"]
        high = enig_stack(1e9, sigma_ni=SIGMA_CU / 6.0)["r_eff"]
        assert high > low  # ρ_Ni 越高（σ 越低）损耗抬升越大

    def test_skin_depths_order_and_values(self):
        out = enig_stack(1e9)
        deltas = out["skin_depths"]
        assert len(deltas) == 3
        assert deltas[0] == skin_depth(1e9, SIGMA_AU)  # 顶→基底序，逐位
        assert deltas[1] == skin_depth(1e9, SIGMA_CU / 4.0)
        assert deltas[2] == skin_depth(1e9, SIGMA_CU)
        assert deltas[1] > deltas[0] > deltas[2]  # δ_Ni > δ_Au > δ_Cu


# ─── 独立参考实现对拍（tanh 形式 + cmath，#118） ─────────────────────────────


class TestIndependentReference:
    @pytest.mark.parametrize(
        "stack",
        [
            [(SIGMA_AU, 7.5e-8), (1.45e7, 3.0e-6), (SIGMA_CU, None)],
            [(1.45e7, 1.0e-6), (SIGMA_CU, None)],
            [(SIGMA_AU, 0.5e-6), (1.45e7, 4.5e-6), (SIGMA_CU, None)],
        ],
    )
    @pytest.mark.parametrize("freq_hz", [1e9, 10e9])
    def test_matches_tanh_reference(self, stack, freq_hz):
        layers = [
            ({"material": "au", "thickness_m": t, "conductivity_s_per_m": s}
             if s != 1.45e7
             else {"material": "ni", "thickness_m": t, "conductivity_s_per_m": s})
            if t is not None
            else {"material": "cu", "conductivity_s_per_m": s}
            for s, t in stack
        ]
        out = layered_surface_impedance(freq_hz, layers)
        ref = _ref_zin(freq_hz, stack)
        assert out["z_in_complex"] == pytest.approx(ref, rel=1e-12, abs=0.0)


# ─── 守卫（显式 ValueError，不静默兜底） ─────────────────────────────────────


class TestGuards:
    def test_empty_layers_raises(self):
        with pytest.raises(ValueError, match="不能为空"):
            layered_surface_impedance(1e9, [])

    @pytest.mark.parametrize("bad", ["cu", {"material": "cu"}, None, 42])
    def test_layers_not_a_list_raises(self, bad):
        with pytest.raises(ValueError, match="list/tuple"):
            layered_surface_impedance(1e9, bad)

    def test_layer_not_a_dict_raises(self):
        with pytest.raises(ValueError, match="dict"):
            layered_surface_impedance(1e9, [("cu",)])

    @pytest.mark.parametrize("material", ["", "   ", 42, True, None])
    def test_bad_material_raises(self, material):
        with pytest.raises(ValueError, match="material"):
            layered_surface_impedance(
                1e9, [{"material": material, "conductivity_s_per_m": SIGMA_CU}]
            )

    def test_negative_thickness_raises(self):
        with pytest.raises(ValueError, match=">= 0"):
            layered_surface_impedance(
                1e9,
                [{"material": "au", "thickness_m": -1e-6,
                  "conductivity_s_per_m": SIGMA_AU},
                 _cu_substrate()],
            )

    def test_coating_missing_thickness_raises(self):
        with pytest.raises(ValueError, match="thickness_m"):
            layered_surface_impedance(
                1e9,
                [{"material": "au", "conductivity_s_per_m": SIGMA_AU},
                 _cu_substrate()],
            )

    def test_substrate_with_thickness_raises(self):
        with pytest.raises(ValueError, match="半无限体"):
            layered_surface_impedance(
                1e9,
                [{"material": "cu", "thickness_m": 35e-6,
                  "conductivity_s_per_m": SIGMA_CU}],
            )

    def test_layer_order_reversed_raises(self):
        # 基底铜不在末层 = 层序颠倒（顶→基底语义被破坏）
        with pytest.raises(ValueError, match="层序颠倒"):
            layered_surface_impedance(
                1e9,
                [
                    _cu_substrate(),
                    {"material": "ni", "thickness_m": 3e-6,
                     "conductivity_s_per_m": 1.45e7},
                    {"material": "au", "thickness_m": 7.5e-8,
                     "conductivity_s_per_m": SIGMA_AU},
                ],
            )

    def test_copper_mid_stack_raises(self):
        with pytest.raises(ValueError, match="层序颠倒"):
            layered_surface_impedance(
                1e9,
                [
                    {"material": "au", "thickness_m": 7.5e-8,
                     "conductivity_s_per_m": SIGMA_AU},
                    _cu_substrate(),
                    {"material": "ni", "thickness_m": 3e-6,
                     "conductivity_s_per_m": 1.45e7},
                ],
            )

    def test_conflicting_sigma_keys_raises(self):
        with pytest.raises(ValueError, match="二选一"):
            layered_surface_impedance(
                1e9,
                [{"material": "cu", "conductivity_s_per_m": SIGMA_CU,
                  "rho_rel": 1.0}],
            )

    def test_missing_sigma_keys_raises(self):
        with pytest.raises(ValueError, match="之一"):
            layered_surface_impedance(1e9, [{"material": "cu"}])

    def test_unknown_layer_key_raises(self):
        with pytest.raises(ValueError, match="未知键"):
            layered_surface_impedance(
                1e9, [{"material": "cu", "mu_r": 1.0,
                       "conductivity_s_per_m": SIGMA_CU}]
            )

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"freq_hz": True}, "bool"),
            ({"sigma_cu": True}, "bool"),
        ],
    )
    def test_layered_bool_scalars_raise(self, kwargs, match):
        with pytest.raises(ValueError, match=match):
            layered_surface_impedance(
                kwargs.get("freq_hz", 1e9),
                [_cu_substrate()],
                sigma_cu=kwargs.get("sigma_cu", SIGMA_CU),
            )

    @pytest.mark.parametrize("field", ["thickness_m", "conductivity_s_per_m", "rho_rel"])
    def test_layered_bool_layer_fields_raise(self, field):
        layer = {"material": "au" if field == "thickness_m" else "cu"}
        if field == "thickness_m":
            layer[field] = True
            layers = [layer, _cu_substrate()]
        else:
            layer[field] = True
            layers = [layer]
        with pytest.raises(ValueError, match="bool"):
            layered_surface_impedance(1e9, layers)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"freq_hz": True},
            {"au_thickness_m": True},
            {"ni_thickness_m": True},
            {"cu_conductivity": True},
            {"sigma_au": True},
            {"sigma_ni": True},
        ],
    )
    def test_enig_bool_inputs_raise(self, kwargs):
        with pytest.raises(ValueError, match="bool"):
            enig_stack(**{"freq_hz": 1e9, **kwargs})

    def test_nonpositive_sigma_cu_raises(self):
        with pytest.raises(ValueError, match="> 0"):
            layered_surface_impedance(1e9, [_cu_substrate()], sigma_cu=0.0)


# ─── 返回契约与形态注记 ───────────────────────────────────────────────────────


class TestContract:
    def test_return_keys_contract(self):
        out = enig_stack(1e9)
        assert set(out) == {
            "freq_hz",
            "z_in_complex",
            "r_eff",
            "x_eff",
            "skin_depths",
            "regime_notes",
        }
        assert isinstance(out["z_in_complex"], complex)
        assert out["r_eff"] == out["z_in_complex"].real
        assert out["x_eff"] == out["z_in_complex"].imag
        assert out["freq_hz"] == 1e9

    def test_regime_notes_flag_thick_thin_and_substrate(self):
        thick = layered_surface_impedance(
            1e9,
            [{"material": "au", "thickness_m": 100e-6,
              "conductivity_s_per_m": SIGMA_AU},
             _cu_substrate()],
        )
        assert any("thick asymptote" in note for note in thick["regime_notes"])
        assert any("semi-infinite" in note for note in thick["regime_notes"])
        thin = layered_surface_impedance(
            1e9,
            [{"material": "au", "thickness_m": 1e-9,
              "conductivity_s_per_m": SIGMA_AU},
             _cu_substrate()],
        )
        assert any("thin" in note for note in thin["regime_notes"])

    def test_enig_transition_note(self):
        # 缺省 ENIG @1GHz：t_Ni/delta_Ni ≈ 0.72 属过渡区（非 thin 非 thick）
        out = enig_stack(1e9)
        assert any("transition" in note for note in out["regime_notes"])


# ─── 表面处理定性口径表（纯查表） ─────────────────────────────────────────────


class TestFinishNotes:
    def test_enig_note_mentions_nickel_sources_and_quant_pointer(self):
        note = finish_qualitative_note("enig", 5e9)
        assert "Ni(P)" in note
        assert "enig_stack" in note
        assert "DesignCon 2012" in note

    @pytest.mark.parametrize("finish", ["im_ag", "osp"])
    def test_im_ag_and_osp_negligible_above_2ghz(self, finish):
        note = finish_qualitative_note(finish, 5e9)
        assert "忽略" in note
        assert "裸铜" in note

    @pytest.mark.parametrize("finish", ["im_ag", "osp"])
    def test_im_ag_and_osp_hedge_below_2ghz(self, finish):
        note = finish_qualitative_note(finish, 900e6)
        assert "实测" in note

    def test_im_sn_note_suggests_measurement(self):
        assert "实测" in finish_qualitative_note("im_sn", 5e9)

    def test_hasl_note_warns_against_mmwave(self):
        note = finish_qualitative_note("hasl", 30e9)
        assert "毫米波不推荐" in note

    def test_finish_key_case_and_space_insensitive(self):
        assert finish_qualitative_note("  ENIG ", 1e9) == finish_qualitative_note(
            "enig", 1e9
        )

    def test_unknown_finish_raises(self):
        with pytest.raises(ValueError, match="未知表面处理"):
            finish_qualitative_note("eneig", 1e9)
        with pytest.raises(ValueError, match="未知表面处理"):
            finish_qualitative_note("im_ag_gold", 1e9)
        # 支持键集导出且含五键
        assert set(FINISH_NOTE_KEYS) == {"enig", "im_ag", "im_sn", "osp", "hasl"}

    @pytest.mark.parametrize("bad_freq", [0.0, -1e9, True])
    def test_note_rejects_bad_freq(self, bad_freq):
        with pytest.raises(ValueError):
            finish_qualitative_note("enig", bad_freq)

    @pytest.mark.parametrize("bad_finish", [42, None, True, ["enig"]])
    def test_note_rejects_non_str_finish(self, bad_finish):
        with pytest.raises(ValueError, match="finish"):
            finish_qualitative_note(bad_finish, 1e9)
