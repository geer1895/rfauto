"""现有模板的 TemplateSpec 收拢（新模板 = 在此文件加一个条目）。

组件引用全部在条目函数内 import——保持插件 entry-point 发现的启动轻量
（models 层允许 import adapters/core，见 .importlinter 分层）。
"""

from __future__ import annotations

import math
from functools import partial
from typing import Any

from rfauto.models.template_spec import (
    TEMPLATE_SPECS,
    TemplateSpec,
    register_template_spec,
)

__all__ = ["TEMPLATE_SPECS", "bootstrap_template_specs"]


def _register_wilkinson() -> None:
    from rfauto.adapters.fake_adapter import _wilkinson_sparams_3port
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_wilkinson

    register_template_spec(TemplateSpec(
        name="wilkinson",
        meta=dict(TEMPLATE_META["wilkinson"]),
        synthesizer=synthesize_wilkinson,
        physics_roles={
            "arm_len_mm": "resonator_length_mm",
            "series_w_mm": "impedance_line_width_mm",
            "shunt_w_mm": "shunt_line_width_mm",
        },
        render_script=partial(render_script, "wilkinson"),
        fake_model=_wilkinson_sparams_3port,
        hfss_plugin="wilkinson_power_divider",
    ))


def _register_branchline() -> None:
    from rfauto.adapters.fake_adapter import _branchline_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_branchline

    register_template_spec(TemplateSpec(
        name="branchline",
        meta=dict(TEMPLATE_META["branchline"]),
        synthesizer=synthesize_branchline,
        physics_roles={
            "arm_len_mm": "resonator_length_mm",
            "series_w_mm": "impedance_line_width_mm",
            "shunt_w_mm": "shunt_line_width_mm",
        },
        render_script=partial(render_script, "branchline"),
        fake_model=_branchline_sparams,
        hfss_plugin="branchline_coupler",
    ))


def _register_patch() -> None:
    from rfauto.adapters.fake_adapter import _patch_sparams_2port
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_patch

    register_template_spec(TemplateSpec(
        name="patch",
        meta=dict(TEMPLATE_META["patch"]),
        synthesizer=synthesize_patch,
        physics_roles={
            "patch_len_mm": "resonator_length_mm",
            "patch_w_mm": "patch_width_mm",
            "feed_offset_mm": "feed_offset_mm",
        },
        render_script=partial(render_script, "patch"),
        fake_model=_patch_sparams_2port,
        hfss_plugin="patch_antenna",
    ))


def _register_mline() -> None:
    from rfauto.adapters.fake_adapter import _mline_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_mline_model

    register_template_spec(TemplateSpec(
        name="mline",
        meta=dict(TEMPLATE_META["mline"]),
        synthesizer=synthesize_mline_model,
        physics_roles={
            "w_mm": "line_width_mm",
            "line_len_mm": "line_length_mm",
        },
        render_script=partial(render_script, "mline"),
        fake_model=_mline_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（均匀线无需桌面 FEM）
    ))


def _register_cpw() -> None:
    from rfauto.adapters.fake_adapter import _cpw_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_cpw_model

    register_template_spec(TemplateSpec(
        name="cpw",
        meta=dict(TEMPLATE_META["cpw"]),
        synthesizer=synthesize_cpw_model,
        physics_roles={
            "w_mm": "line_width_mm",
            "gap_mm": "gap_width_mm",
            "line_len_mm": "line_length_mm",
        },
        render_script=partial(render_script, "cpw"),
        fake_model=_cpw_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板
    ))


def _register_dipole() -> None:
    from rfauto.adapters.fake_adapter import _dipole_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_dipole_model

    register_template_spec(TemplateSpec(
        name="dipole",
        meta=dict(TEMPLATE_META["dipole"]),
        synthesizer=synthesize_dipole_model,
        physics_roles={
            "dipole_len_mm": "resonator_length_mm",
        },
        render_script=partial(render_script, "dipole"),
        fake_model=_dipole_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（辐射器件族）
    ))


def _register_stripline() -> None:
    from rfauto.adapters.fake_adapter import _mline_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_stripline_model

    register_template_spec(TemplateSpec(
        name="stripline",
        meta=dict(TEMPLATE_META["stripline"]),
        synthesizer=synthesize_stripline_model,
        physics_roles={
            "w_mm": "line_width_mm",
            "line_len_mm": "line_length_mm",
        },
        render_script=partial(render_script, "stripline"),
        fake_model=_mline_sparams,  # TEM：εeff=εr，解析同形
        hfss_plugin=None,  # 纯 openEMS 锚模板
    ))


def _register_cps() -> None:
    from rfauto.adapters.fake_adapter import _cps_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_cps_model

    register_template_spec(TemplateSpec(
        name="cps",
        meta=dict(TEMPLATE_META["cps"]),
        synthesizer=synthesize_cps_model,
        # #154：w_mm=单带宽、gap_mm=两带间缝、line_len_mm=两端口间线长——fake
        # （_cps_ri）与 openEMS（_cps_lines）逐参数同语义
        physics_roles={
            "w_mm": "line_width_mm",
            "gap_mm": "gap_width_mm",
            "line_len_mm": "line_length_mm",
        },
        render_script=partial(render_script, "cps"),
        fake_model=_cps_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（C9 传输线族 II）
    ))


def _register_suspended_stripline() -> None:
    from rfauto.adapters.fake_adapter import _suspended_stripline_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_suspended_stripline_model

    register_template_spec(TemplateSpec(
        name="suspended_stripline",
        meta=dict(TEMPLATE_META["suspended_stripline"]),
        synthesizer=synthesize_suspended_stripline_model,
        # b_mm=腔高（两地面间距）无角色词表条目，按名直读（fake/openEMS 同名同义）
        physics_roles={
            "w_mm": "line_width_mm",
            "line_len_mm": "line_length_mm",
        },
        render_script=partial(render_script, "suspended_stripline"),
        fake_model=_suspended_stripline_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（C9 传输线族 II）
    ))


def _register_msl_cpw() -> None:
    from rfauto.adapters.fake_adapter import _msl_cpw_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_msl_cpw_model

    register_template_spec(TemplateSpec(
        name="msl_cpw",
        meta=dict(TEMPLATE_META["msl_cpw"]),
        synthesizer=synthesize_msl_cpw_model,
        # #154 只映射语义确定键：w_msl_mm=微带段线宽（50Ω 口径）、gap_cpw_mm=CPW
        # 缝、line_len_mm=总长；w_cpw_mm（CPWG 中心带宽）/渐变区/过孔栅栏参数无
        # 角色词表条目，fake/openEMS 按名直读同义
        physics_roles={
            "w_msl_mm": "line_width_mm",
            "gap_cpw_mm": "gap_width_mm",
            "line_len_mm": "line_length_mm",
        },
        render_script=partial(render_script, "msl_cpw"),
        fake_model=_msl_cpw_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（Tier 2 过渡族）
    ))


def _register_sma_launcher() -> None:
    from rfauto.adapters.fake_adapter import _sma_launcher_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_sma_launcher_model

    register_template_spec(TemplateSpec(
        name="sma_launcher",
        meta=dict(TEMPLATE_META["sma_launcher"]),
        synthesizer=synthesize_sma_launcher_model,
        # #154：w_msl_mm=微带段线宽、line_len_mm=微带体带长；同轴几何（r_i/r_o/
        # shell_t/er_fill/shell_len/pin_lay/port_len）无角色词表条目，按名直读
        physics_roles={
            "w_msl_mm": "line_width_mm",
            "line_len_mm": "line_length_mm",
        },
        render_script=partial(render_script, "sma_launcher"),
        fake_model=_sma_launcher_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（Tier 2 过渡族）
    ))


def _register_wstep() -> None:
    from rfauto.adapters.fake_adapter import _wstep_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_wstep_model

    register_template_spec(TemplateSpec(
        name="wstep",
        meta=dict(TEMPLATE_META["wstep"]),
        synthesizer=synthesize_wstep_model,
        physics_roles={
            "w1_mm": "line_width_mm",
            "w2_mm": "step_width_mm",
            "line_len_mm": "line_length_mm",
        },
        render_script=partial(render_script, "wstep"),
        fake_model=_wstep_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（不连续性基元族）
    ))


def _register_tjunc() -> None:
    from rfauto.adapters.fake_adapter import _tjunc_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_tjunc_model

    register_template_spec(TemplateSpec(
        name="tjunc",
        meta=dict(TEMPLATE_META["tjunc"]),
        synthesizer=synthesize_tjunc_model,
        physics_roles={
            "w_feed_mm": "line_width_mm",
            "through_len_mm": "line_length_mm",
            "branch_len_mm": "branch_length_mm",
        },
        render_script=partial(render_script, "tjunc"),
        fake_model=_tjunc_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（不连续性基元族）
    ))


def _register_bend() -> None:
    from rfauto.adapters.fake_adapter import _bend_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_bend_model

    register_template_spec(TemplateSpec(
        name="bend",
        meta=dict(TEMPLATE_META["bend"]),
        synthesizer=synthesize_bend_model,
        physics_roles={
            "w_mm": "line_width_mm",
            "arm_len_mm": "line_length_mm",
        },
        render_script=partial(render_script, "bend"),
        fake_model=_bend_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（不连续性基元族）
    ))


def _register_via() -> None:
    from rfauto.adapters.fake_adapter import _via_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_via_model

    register_template_spec(TemplateSpec(
        name="via",
        meta=dict(TEMPLATE_META["via"]),
        synthesizer=synthesize_via_model,
        physics_roles={
            "w_mm": "line_width_mm",
        },
        render_script=partial(render_script, "via"),
        fake_model=_via_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（不连续性基元族收官）
    ))


def _register_atten_pi() -> None:
    from rfauto.adapters.fake_adapter import _atten_pi_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_atten_pi_model

    register_template_spec(TemplateSpec(
        name="atten_pi",
        meta=dict(TEMPLATE_META["atten_pi"]),
        synthesizer=synthesize_atten_pi_model,
        physics_roles={
            "w_mm": "line_width_mm",
        },
        render_script=partial(render_script, "atten_pi"),
        fake_model=_atten_pi_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（Tier 1 首族）
    ))


def _register_atten_t() -> None:
    from rfauto.adapters.fake_adapter import _atten_t_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_atten_t_model

    register_template_spec(TemplateSpec(
        name="atten_t",
        meta=dict(TEMPLATE_META["atten_t"]),
        synthesizer=synthesize_atten_t_model,
        physics_roles={
            "w_mm": "line_width_mm",
        },
        render_script=partial(render_script, "atten_t"),
        fake_model=_atten_t_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（Tier 1 横向变体）
    ))


def _register_ratrace() -> None:
    from rfauto.adapters.fake_adapter import _ratrace_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_ratrace_model

    register_template_spec(TemplateSpec(
        name="ratrace",
        meta=dict(TEMPLATE_META["ratrace"]),
        synthesizer=synthesize_ratrace_model,
        physics_roles={
            "w_ring_mm": "line_width_mm",
        },
        render_script=partial(render_script, "ratrace"),
        fake_model=_ratrace_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（Tier 1 混合环族）
    ))


def _register_gysel() -> None:
    from rfauto.adapters.fake_adapter import _gysel_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_gysel_model

    register_template_spec(TemplateSpec(
        name="gysel",
        meta=dict(TEMPLATE_META["gysel"]),
        synthesizer=synthesize_gysel_model,
        physics_roles={
            "w_arm_mm": "impedance_line_width_mm",
            "w_feed_mm": "shunt_line_width_mm",
            "arm_len_mm": "resonator_length_mm",
            "iso_len_mm": "line_length_mm",
        },
        render_script=partial(render_script, "gysel"),
        fake_model=_gysel_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（Tier 1 高隔离功分族）
    ))


def _register_hairpin() -> None:
    # 综合入口已下沉 core：原本地闭包 → core/synthesis
    # synthesize_hairpin_model（C13→KJ/抽头闭式→几何，ModelSynthesisResult 合同不变，
    # 本处只做注册组装，零数值）
    from rfauto.adapters.fake_adapter import _hairpin_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import synthesize_hairpin_model

    register_template_spec(TemplateSpec(
        name="hairpin",
        meta=dict(TEMPLATE_META["hairpin"]),
        synthesizer=synthesize_hairpin_model,
        physics_roles={
            "w_mm": "line_width_mm",
            "arm_len_mm": "resonator_length_mm",
            "gap_mm": "gap_width_mm",
        },
        render_script=partial(render_script, "hairpin"),
        fake_model=_hairpin_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（滤波器族首例）
    ))


def _register_hairpin_alt() -> None:
    # 交替取向 hairpin（交替取向根修）：综合入口 = core 的
    # synthesize_hairpin_model 纯 KJ 链（几何与 hairpin 同链同值，唯一变量=取向），
    # 本处只改模型标签/注记并保持 ModelSynthesisResult 合同（零数值，coupled_bpf
    # 本地组装同款）；fake 派发按 model_type="hairpin_alt" 走纯 KJ（不乘同向 c(gap)）。
    from rfauto.adapters.fake_adapter import _hairpin_sparams
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core.synthesis import ModelSynthesisResult, synthesize_hairpin_model

    def synthesize_hairpin_alt_model(
        order: int = 3, f0_ghz: float = 2.5, fbw: float = 0.05,
        rl_db: float = 20.0, **_: Any,
    ) -> ModelSynthesisResult:
        """hairpin_alt spec 综合入口：hairpin 纯 KJ 设计链 + 交替取向标签。"""
        base = synthesize_hairpin_model(order=order, f0_ghz=f0_ghz, fbw=fbw,
                                        rl_db=rl_db)
        draft = dict(base.recipe_draft)
        draft["model"] = "hairpin_alt_bpf"
        return ModelSynthesisResult(
            model="hairpin_alt_bpf", goal=dict(base.goal), params=dict(base.params),
            recipe_draft=draft,
            notes=[*base.notes,
                   "交替取向（奇数序谐振器翻转）：gap→k 纯 KJ，不乘同向 c(gap)；"
                   "c_alt 预声明门见 scripts/hairpin_q_extract.hairpin_alt_kgap_gate"],
        )

    register_template_spec(TemplateSpec(
        name="hairpin_alt",
        meta=dict(TEMPLATE_META["hairpin_alt"]),
        synthesizer=synthesize_hairpin_alt_model,
        physics_roles={
            "w_mm": "line_width_mm",
            "arm_len_mm": "resonator_length_mm",
            "gap_mm": "gap_width_mm",
        },
        render_script=partial(render_script, "hairpin_alt"),
        fake_model=_hairpin_sparams,
        hfss_plugin=None,  # 纯 openEMS（hairpin 同族）
    ))


def _register_coupled_bpf() -> None:
    from rfauto.adapters.fake_adapter import _coupled_bpf_sparams
    from rfauto.adapters.openems_templates import (
        COUPLED_BPF_NOMINAL,
        TEMPLATE_META,
        coupled_bpf_design_from_order,
        render_script,
    )
    from rfauto.core.synthesis import ModelSynthesisResult

    def synthesize_coupled_bpf_model(
        order: int = 3, f0_ghz: float = 2.5, fbw: float = 0.05,
        rl_db: float = 20.0, **_: Any,
    ) -> ModelSynthesisResult:
        """coupled_bpf spec 综合入口：切比雪夫 g 值 → J 倒置器 → KJ (w,s) →
        几何（确定性内核 = core/matching g 值 + openems_templates 综合链），
        包装为 spec 合同的 ModelSynthesisResult——只做组装，零数值。"""
        design = coupled_bpf_design_from_order(order, f0_ghz, fbw, rl_db)
        params: dict[str, Any] = {
            "order": int(design["order"]),
            "w_feed_mm": round(float(design["w_feed_mm"]), 4),
            "widths_mm": [round(float(s["w_mm"]), 4) for s in design["sections"]],
            "gaps_mm": [round(float(s["s_mm"]), 4) for s in design["sections"]],
            "res_len_mm": round(float(design["res_len_mm"]), 4),
            "feed_len_mm": round(float(design["feed_len_mm"]), 4),
        }
        assert set(params) == set(COUPLED_BPF_NOMINAL)
        band = (f0_ghz * (1.0 - fbw * 0.475), f0_ghz * (1.0 + fbw * 0.475))
        recipe_draft = {
            "model": "coupled_bpf",
            "recipe_version": 1,
            "schema_version": 1,
            "params": {k: {"value": v} for k, v in params.items()},
            "setup": {"solver": "openEMS",
                      "freq_range_ghz": [f0_ghz * 0.7, f0_ghz * 1.3],
                      "points": 401},
            "objectives": [
                {"metric": "s11_db", "band": [band[0], band[1]],
                 "op": "max_below", "value": -rl_db},
            ],
        }
        return ModelSynthesisResult(
            model="coupled_bpf",
            goal={"f0_ghz": f0_ghz, "fbw": fbw, "rl_db": rl_db,
                  "order": int(order)},
            params=params,
            recipe_draft=recipe_draft,
            notes=list(design["notes"]),
        )

    register_template_spec(TemplateSpec(
        name="coupled_bpf",
        meta=dict(TEMPLATE_META["coupled_bpf"]),
        synthesizer=synthesize_coupled_bpf_model,
        # #154：列表参数 widths_mm/gaps_mm 在 fake/openEMS 两通道同索引同语义
        # （第 j 耦合段线宽/边到边缝）；角色词表无列表角色，按元素物理量归类
        physics_roles={
            "w_feed_mm": "line_width_mm",
            "widths_mm": "impedance_line_width_mm",
            "gaps_mm": "gap_width_mm",
            "res_len_mm": "resonator_length_mm",
            "feed_len_mm": "line_length_mm",
        },
        render_script=partial(render_script, "coupled_bpf"),
        fake_model=_coupled_bpf_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（BPF 族锚）
    ))


# 天线族 II 各模板：闭式设计函数（openems_templates）+ 物理角色
# （只映射语义确定的键；helix 谐振尺寸由 d/N/p 联合决定，无单键谐振长度角色）
_ANTENNA2_ROLES: dict[str, dict[str, str]] = {
    "monopole": {"mon_len_mm": "resonator_length_mm",
                 "mon_w_mm": "line_width_mm"},
    "pifa": {"pifa_l_mm": "resonator_length_mm",
             "pifa_w_mm": "patch_width_mm",
             "pin_back_mm": "feed_offset_mm"},
    "ifa": {"ifa_arm_mm": "resonator_length_mm",
            "ifa_w_mm": "line_width_mm",
            "feed_off_mm": "feed_offset_mm"},
    "loop": {"loop_side_mm": "resonator_length_mm",
             "loop_w_mm": "line_width_mm",
             "loop_gap_mm": "gap_width_mm"},
    "helix": {"helix_w_mm": "line_width_mm"},
    "slot": {"slot_l_mm": "resonator_length_mm",
             "feed_w_mm": "line_width_mm",
             "slot_w_mm": "gap_width_mm"},
}


def _antenna2_design_params(template: str, f0_ghz: float,
                            nominal: dict[str, Any]) -> dict[str, Any]:
    """谐振尺寸 = 闭式设计函数（4 位舍入，与 ANTENNA2_NOMINAL 再生口径一致），
    其余几何输入沿用 nominal。"""
    from rfauto.adapters import openems_templates as ot

    params = dict(nominal)
    if template == "monopole":
        params["mon_len_mm"] = round(ot.monopole_len_mm(f0_ghz), 4)
    elif template == "pifa":
        params["pifa_l_mm"] = round(ot.pifa_l_mm(
            f0_ghz, float(nominal["pifa_w_mm"]), float(nominal["pifa_ws_mm"])), 4)
    elif template == "ifa":
        params["ifa_arm_mm"] = round(ot.ifa_arm_len_mm(
            f0_ghz, float(nominal["ifa_w_mm"])), 4)
    elif template == "loop":
        params["loop_side_mm"] = round(ot.loop_side_mm(
            f0_ghz, float(nominal["loop_w_mm"])), 4)
    elif template == "helix":
        params["helix_pitch_mm"] = round(ot.helix_pitch_mm(
            f0_ghz, float(nominal["helix_d_mm"]), int(nominal["helix_turns"])), 4)
    elif template == "slot":
        params["slot_l_mm"] = round(ot.slot_len_mm(f0_ghz), 4)
    else:
        raise KeyError(f"非 antenna2 模板: {template}")
    return params


def _register_antenna2() -> None:
    from rfauto.adapters.fake_adapter import _antenna2_sparams
    from rfauto.adapters.openems_templates import (
        ANTENNA2_NOMINAL,
        ANTENNA2_TEMPLATES,
        TEMPLATE_META,
        render_script,
    )
    from rfauto.core.synthesis import ModelSynthesisResult

    def _make_synthesizer(template: str):
        def synthesize_antenna2_model(
            f0_ghz: float = 2.4, s11_target_db: float = -10.0, **_: Any,
        ) -> ModelSynthesisResult:
            """antenna2 spec 综合入口：闭式设计函数 → 几何（确定性内核），
            包装为 ModelSynthesisResult——只做组装，零数值。"""
            nominal = ANTENNA2_NOMINAL[template]
            params = _antenna2_design_params(template, f0_ghz, nominal)
            metric = "s21_db" if template == "slot" else "s11_db"
            recipe_draft = {
                "model": template,
                "recipe_version": 1,
                "schema_version": 1,
                "params": {k: {"value": v} for k, v in params.items()},
                "setup": {"solver": "openEMS",
                          "freq_range_ghz": [f0_ghz - 0.5, f0_ghz + 0.5],
                          "points": 401},
                "objectives": [
                    {"metric": metric,
                     "band": [f0_ghz * 0.98, f0_ghz * 1.02],
                     "op": "min_below", "value": s11_target_db},
                ],
            }
            return ModelSynthesisResult(
                model=template,
                goal={"f0_ghz": f0_ghz, "s11_target_db": s11_target_db},
                params=params,
                recipe_draft=recipe_draft,
                notes=[f"{template}: 谐振尺寸由 openems_templates 闭式设计函数"
                       f"给出（理论核验口径，设计式不做端效应预补偿）"],
            )
        synthesize_antenna2_model.__name__ = f"synthesize_{template}_model"
        return synthesize_antenna2_model

    for template in ANTENNA2_TEMPLATES:
        register_template_spec(TemplateSpec(
            name=template,
            meta=dict(TEMPLATE_META[template]),
            synthesizer=_make_synthesizer(template),
            physics_roles=dict(_ANTENNA2_ROLES[template]),
            render_script=partial(render_script, template),
            fake_model=partial(_antenna2_sparams, template=template),
            hfss_plugin=None,  # 纯 openEMS 辐射族（天线族 II）
        ))


# ─── §C4 耦合器族 II：cline_coupler / branchline_2sect / lange（注册）──
# 综合入口 = openems_templates 设计链（Pozar 闭式 → KJ/HJ 线宽 → λ/4），本文件
# 只做 4 位舍入组装（零数值）；三模板均纯 openEMS 锚模板（hfss_plugin=None）。

def _c4_recipe_draft(model: str, params: dict[str, Any], f0_ghz: float,
                     objectives: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": model,
        "recipe_version": 1,
        "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"solver": "openEMS",
                  "freq_range_ghz": [f0_ghz * 0.7, f0_ghz * 1.3],
                  "points": 401},
        "objectives": objectives,
    }


def _register_cline_coupler() -> None:
    from rfauto.adapters.fake_adapter import _cline_coupler_sparams
    from rfauto.adapters.openems_templates import (
        CLINE_COUPLER_NOMINAL,
        TEMPLATE_META,
        cline_coupler_design,
        render_script,
    )
    from rfauto.core.synthesis import ModelSynthesisResult

    def synthesize_cline_coupler_model(
        coupling_db: float = 10.0, f0_ghz: float = 2.5, z0_ohm: float = 50.0,
        **_: Any,
    ) -> ModelSynthesisResult:
        """cline_coupler spec 综合入口：C(dB) → Pozar (Z0e,Z0o) → KJ (w,s) →
        λ/4（确定性内核 openems_templates.cline_coupler_design），只组装零数值。"""
        design = cline_coupler_design(coupling_db, f0_ghz, z0_ohm)
        params: dict[str, Any] = {
            "w_mm": round(float(design["w_mm"]), 4),
            "gap_mm": round(float(design["s_mm"]), 4),
            "coupled_len_mm": round(float(design["lc_mm"]), 4),
            "w_feed_mm": round(float(design["w_feed_mm"]), 4),
        }
        assert set(params) == set(CLINE_COUPLER_NOMINAL)
        band = [f0_ghz * 0.96, f0_ghz * 1.04]
        objectives = [
            {"metric": "s31_db", "band": band, "op": "mean_within",
             "value": [-coupling_db - 0.5, -coupling_db + 0.5]},
            {"metric": "s11_db", "band": band, "op": "max_below", "value": -20.0},
        ]
        return ModelSynthesisResult(
            model="cline_coupler",
            goal={"f0_ghz": f0_ghz, "z0_ohm": z0_ohm, "coupling_db": coupling_db},
            params=params,
            recipe_draft=_c4_recipe_draft("cline_coupler", params, f0_ghz,
                                          objectives),
            notes=list(design["notes"]),
        )

    register_template_spec(TemplateSpec(
        name="cline_coupler",
        meta=dict(TEMPLATE_META["cline_coupler"]),
        synthesizer=synthesize_cline_coupler_model,
        physics_roles={
            "w_mm": "line_width_mm",
            "gap_mm": "gap_width_mm",
            "coupled_len_mm": "resonator_length_mm",
            "w_feed_mm": "shunt_line_width_mm",
        },
        render_script=partial(render_script, "cline_coupler"),
        fake_model=_cline_coupler_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（§C4 耦合器族 II）
    ))


def _register_branchline_2sect() -> None:
    from rfauto.adapters.fake_adapter import _branchline_2sect_sparams
    from rfauto.adapters.openems_templates import (
        BRANCHLINE_2SECT_NOMINAL,
        TEMPLATE_META,
        branchline_2sect_design,
        render_script,
    )
    from rfauto.core.synthesis import ModelSynthesisResult

    def synthesize_branchline_2sect_model(
        f0_ghz: float = 2.5, z0_ohm: float = 50.0, main_z_ratio: float = 1.0,
        **_: Any,
    ) -> ModelSynthesisResult:
        """branchline_2sect spec 综合入口：f0 阻抗族（Pozar 经典点 main_z_ratio=1）
        → HJ 线宽 → λ/4（确定性内核 branchline_2sect_design），只组装零数值。"""
        design = branchline_2sect_design(f0_ghz, z0_ohm,
                                         main_z_ratio=main_z_ratio)
        params: dict[str, Any] = {
            key: round(float(design[key]), 4)
            for key in ("w_main_mm", "w_out_mm", "w_mid_mm", "w_feed_mm",
                        "sect_len_mm", "branch_len_mm")
        }
        assert set(params) == set(BRANCHLINE_2SECT_NOMINAL)
        band = [f0_ghz * 0.96, f0_ghz * 1.04]
        objectives = [
            {"metric": "s21_db", "band": band, "op": "mean_within",
             "value": [-3.5, -2.5]},
            {"metric": "s31_db", "band": band, "op": "mean_within",
             "value": [-3.5, -2.5]},
            {"metric": "s11_db", "band": band, "op": "max_below", "value": -15.0},
        ]
        return ModelSynthesisResult(
            model="branchline_2sect",
            goal={"f0_ghz": f0_ghz, "z0_ohm": z0_ohm,
                  "main_z_ratio": main_z_ratio},
            params=params,
            recipe_draft=_c4_recipe_draft("branchline_2sect", params, f0_ghz,
                                          objectives),
            notes=list(design["notes"]),
        )

    register_template_spec(TemplateSpec(
        name="branchline_2sect",
        meta=dict(TEMPLATE_META["branchline_2sect"]),
        synthesizer=synthesize_branchline_2sect_model,
        physics_roles={
            "w_main_mm": "line_width_mm",
            "w_out_mm": "impedance_line_width_mm",
            "w_mid_mm": "shunt_line_width_mm",
            "sect_len_mm": "resonator_length_mm",
            "branch_len_mm": "line_length_mm",
            "w_feed_mm": "shunt_line_width_mm",
        },
        render_script=partial(render_script, "branchline_2sect"),
        fake_model=_branchline_2sect_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（§C4 耦合器族 II）
    ))


def _register_lange() -> None:
    from rfauto.adapters.fake_adapter import _lange_sparams
    from rfauto.adapters.openems_templates import (
        LANGE_NOMINAL,
        TEMPLATE_META,
        lange_design,
        render_script,
    )
    from rfauto.core.synthesis import ModelSynthesisResult

    def synthesize_lange_model(
        f0_ghz: float = 2.5, z0_ohm: float = 50.0, coupling_db: float = 3.0103,
        **_: Any,
    ) -> ModelSynthesisResult:
        """lange spec 综合入口：Pozar 四指设计式 → 相邻对 (Z0e,Z0o) → KJ (w,s)
        → 指长 λ/4（确定性内核 lange_design），只组装零数值。"""
        design = lange_design(f0_ghz, z0_ohm, coupling_db)
        params: dict[str, Any] = {
            "w_mm": round(float(design["w_mm"]), 4),
            "gap_mm": round(float(design["s_mm"]), 4),
            "finger_len_mm": round(float(design["finger_len_mm"]), 4),
            "w_feed_mm": round(float(design["w_feed_mm"]), 4),
        }
        assert set(params) == set(LANGE_NOMINAL)
        band = [f0_ghz * 0.96, f0_ghz * 1.04]
        objectives = [
            {"metric": "s21_db", "band": band, "op": "mean_within",
             "value": [-3.5, -2.5]},
            {"metric": "s31_db", "band": band, "op": "mean_within",
             "value": [-3.5, -2.5]},
            {"metric": "s11_db", "band": band, "op": "max_below", "value": -15.0},
        ]
        return ModelSynthesisResult(
            model="lange",
            goal={"f0_ghz": f0_ghz, "z0_ohm": z0_ohm, "coupling_db": coupling_db},
            params=params,
            recipe_draft=_c4_recipe_draft("lange", params, f0_ghz, objectives),
            notes=list(design["notes"]),
        )

    register_template_spec(TemplateSpec(
        name="lange",
        meta=dict(TEMPLATE_META["lange"]),
        synthesizer=synthesize_lange_model,
        physics_roles={
            "w_mm": "line_width_mm",
            "gap_mm": "gap_width_mm",
            "finger_len_mm": "resonator_length_mm",
            "w_feed_mm": "shunt_line_width_mm",
        },
        render_script=partial(render_script, "lange"),
        fake_model=_lange_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（§C4 耦合器族 II）
    ))


# ─── 初始模板补注册：stepped_impedance / coupled_line ── 首批模板有渲染/元数据但无 TemplateSpec（
# TEMPLATE_META 25 vs TEMPLATE_SPECS 23 差集）与 fake 派发（solve 直接
# ValueError）。综合入口复用既有确定性内核（HJ 正向 / KJ 偶奇模），本文件
# 只做 4 位舍入组装，零数值；hfss_plugin=None（纯 openEMS 锚模板）。

def _register_stepped_impedance() -> None:
    from rfauto.adapters.fake_adapter import _stepped_impedance_sparams
    from rfauto.adapters.openems_templates import (
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
        render_script,
    )
    from rfauto.core.synthesis import ModelSynthesisResult, Stackup, forward_z0

    def synthesize_stepped_impedance_model(
        f0_ghz: float = 2.4, **_: Any,
    ) -> ModelSynthesisResult:
        """stepped_impedance spec 综合入口：标称几何 + 标称电长度尺度律
        （seg_len ∝ 1/f0，θ@f0 与标称点等值——确定性恒等式，非经验常数）；
        z1/z2 宽度沿用标称（HJ 阻抗/εeff 进 notes 互检，偶数段=z1 宽）。
        """
        nominal = TEMPLATE_NOMINAL["stepped_impedance"]
        params: dict[str, Any] = {
            "z1_width_mm": float(nominal["z1_width_mm"]),
            "z2_width_mm": float(nominal["z2_width_mm"]),
            "seg_len_mm": round(float(nominal["seg_len_mm"]) * 2.4
                                / float(f0_ghz), 4),
            "n_segments": int(nominal["n_segments"]),
        }
        stackup = Stackup(name="stepped_impedance_spec", epsilon_r=3.66,
                          thickness_mm=0.508)
        z1, ere1 = forward_z0(float(nominal["z1_width_mm"]), float(f0_ghz),
                              stackup)
        z2, ere2 = forward_z0(float(nominal["z2_width_mm"]), float(f0_ghz),
                              stackup)
        recipe_draft = {
            "model": "stepped_impedance",
            "recipe_version": 1,
            "schema_version": 1,
            "params": {k: {"value": v} for k, v in params.items()},
            "setup": {"solver": "openEMS",
                      "freq_range_ghz": [float(f0_ghz) - 0.5,
                                         float(f0_ghz) + 0.5],
                      "points": 401},
            "objectives": [
                {"metric": "s11_db",
                 "band": [float(f0_ghz) * 0.96, float(f0_ghz) * 1.04],
                 "op": "min_below", "value": -10.0},
            ],
        }
        return ModelSynthesisResult(
            model="stepped_impedance",
            goal={"f0_ghz": float(f0_ghz)},
            params=params,
            recipe_draft=recipe_draft,
            notes=[
                f"HJ 互检：Z1({nominal['z1_width_mm']}mm)={z1:.3f}Ω"
                f" εeff={ere1:.4f}，Z2({nominal['z2_width_mm']}mm)={z2:.3f}Ω"
                f" εeff={ere2:.4f}（@f0，rogers4350b）",
                f"seg_len={params['seg_len_mm']}mm（标称电长度尺度律 "
                f"∝1/f0，2.4GHz 标称 {nominal['seg_len_mm']}mm）；"
                "段链奇偶交替（偶数段=z1 宽），阶梯跳宽不连续性不进模型",
            ],
        )

    register_template_spec(TemplateSpec(
        name="stepped_impedance",
        meta=dict(TEMPLATE_META["stepped_impedance"]),
        synthesizer=synthesize_stepped_impedance_model,
        physics_roles={
            "z1_width_mm": "impedance_line_width_mm",
            "z2_width_mm": "step_width_mm",
            "seg_len_mm": "resonator_length_mm",
        },
        render_script=partial(render_script, "stepped_impedance"),
        fake_model=_stepped_impedance_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（初始模板补注册）
    ))


def _register_coupled_line() -> None:
    from rfauto.adapters.fake_adapter import _coupled_line_sparams
    from rfauto.adapters.openems_templates import (
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
        coupled_microstrip_even_odd_ohm,
        render_script,
    )
    from rfauto.core.synthesis import ModelSynthesisResult

    def synthesize_coupled_line_model(
        f0_ghz: float = 2.4, **_: Any,
    ) -> ModelSynthesisResult:
        """coupled_line spec 综合入口：KJ 偶/奇模 @标称 (w,s) → εeff_avg
        =(εeff_e+εeff_o)/2 → λ/4 耦合段长（确定性内核 4 位舍入）；耦合度
        C=(Z0e−Z0o)/(Z0e+Z0o) 进 notes/objectives（f0 处 |S31|≈C，
        Z0e·Z0o≈Z0² 时恒等）。"""
        nominal = TEMPLATE_NOMINAL["coupled_line"]
        params: dict[str, Any] = {
            "line_w_mm": float(nominal["line_w_mm"]),
            "gap_mm": float(nominal["gap_mm"]),
            "coupled_len_mm": 0.0,   # 下方 KJ 闭式回填
        }
        ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
            float(nominal["line_w_mm"]), float(nominal["gap_mm"]),
            float(f0_ghz))
        ere_avg = 0.5 * (ere_e + ere_o)
        params["coupled_len_mm"] = round(
            299.792458 / (4.0 * float(f0_ghz) * math.sqrt(ere_avg)), 4)
        c_volt = (ze - zo) / (ze + zo)
        c_db = 20.0 * math.log10(abs(c_volt))
        band = [float(f0_ghz) * 0.96, float(f0_ghz) * 1.04]
        recipe_draft = {
            "model": "coupled_line",
            "recipe_version": 1,
            "schema_version": 1,
            "params": {k: {"value": v} for k, v in params.items()},
            "setup": {"solver": "openEMS",
                      "freq_range_ghz": [float(f0_ghz) - 0.5,
                                         float(f0_ghz) + 0.5],
                      "points": 401},
            "objectives": [
                {"metric": "s31_db", "band": band, "op": "mean_within",
                 "value": [c_db - 0.5, c_db + 0.5]},
                {"metric": "s11_db", "band": band, "op": "max_below",
                 "value": -15.0},
            ],
        }
        return ModelSynthesisResult(
            model="coupled_line",
            goal={"f0_ghz": float(f0_ghz), "coupling_db": round(c_db, 4)},
            params=params,
            recipe_draft=recipe_draft,
            notes=[
                f"KJ @({nominal['line_w_mm']}mm,{nominal['gap_mm']}mm)："
                f"Z0e={ze:.3f}Ω Z0o={zo:.3f}Ω εeff_e={ere_e:.4f} "
                f"εeff_o={ere_o:.4f}（@f0）",
                f"耦合段长=λ0/(4√εeff_avg)={params['coupled_len_mm']}mm"
                f"（εeff_avg={(ere_e + ere_o) / 2:.4f}，Pozar 耦合线口径）；"
                f"C=(Z0e−Z0o)/(Z0e+Z0o)={c_db:.3f}dB（Z0e·Z0o="
                f"{ze * zo:.1f}Ω²，≈2500 ⇒ f0 |S31|≈C）",
                "口径注：渲染几何线 B 远端开路（旧三端口画法），fake 按 "
                "port4 端接 50Ω 理想耦合器口径（设计裁判）",
            ],
        )

    register_template_spec(TemplateSpec(
        name="coupled_line",
        meta=dict(TEMPLATE_META["coupled_line"]),
        synthesizer=synthesize_coupled_line_model,
        physics_roles={
            "line_w_mm": "line_width_mm",
            "gap_mm": "gap_width_mm",
            "coupled_len_mm": "resonator_length_mm",
        },
        render_script=partial(render_script, "coupled_line"),
        fake_model=_coupled_line_sparams,
        hfss_plugin=None,  # 纯 openEMS 锚模板（初始模板补注册）
    ))


_BOOTSTRAPPED = False


# ─── §C3 滤波器族 II：interdigital / combline / sir_bpf（注册）─────
# 综合入口 = openems_templates 设计链（C13 原型 → MYJ 斜率 → J → Cohn 精确 x →
# KJ 一维反解缝 → 谐振棒闭式长度）；本文件只做组装，零数值。
_C3_ROLES: dict[str, dict[str, str]] = {
    "interdigital": {"w_mm": "line_width_mm",
                     "res_len_mm": "resonator_length_mm",
                     "gaps_mm": "gap_width_mm",
                     "feed_len_mm": "line_length_mm"},
    # c_load_pf（装载电容值）无长度类角色，不映射
    "combline": {"w_mm": "line_width_mm",
                 "res_len_mm": "resonator_length_mm",
                 "gaps_mm": "gap_width_mm",
                 "feed_len_mm": "line_length_mm"},
    # w_low/w_high=阶梯阻抗两段线宽（低阻段承担耦合、高阻段接地端）
    "sir_bpf": {"w_feed_mm": "line_width_mm",
                "w_low_mm": "impedance_line_width_mm",
                "w_high_mm": "step_width_mm",
                "l_low_mm": "resonator_length_mm",
                "gaps_mm": "gap_width_mm",
                "feed_len_mm": "line_length_mm"},
}


def _c3_params_from_design(template: str, design: dict[str, Any]) -> dict[str, Any]:
    """设计 dict → 模板参数（4 位舍入，与 *_NOMINAL 再生口径一致；键集=NOMINAL）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    params: dict[str, Any] = {}
    for key in TEMPLATE_NOMINAL[template]:
        value = design[key]
        if key == "order":
            params[key] = int(value)
        elif isinstance(value, list):
            params[key] = [round(float(v), 4) for v in value]
        else:
            params[key] = round(float(value), 4)
    return params


def _register_c3_filters() -> None:
    from rfauto.adapters.fake_adapter import _c3_sparams
    from rfauto.adapters.openems_templates import (
        C3_TEMPLATES,
        TEMPLATE_META,
        combline_design_from_order,
        interdigital_design_from_order,
        render_script,
        sir_bpf_design_from_order,
    )
    from rfauto.core.synthesis import ModelSynthesisResult

    designers = {"interdigital": interdigital_design_from_order,
                 "combline": combline_design_from_order,
                 "sir_bpf": sir_bpf_design_from_order}

    def _make_synthesizer(template: str):
        def synthesize_c3_model(
            order: int = 3, f0_ghz: float = 2.5, fbw: float = 0.05,
            rl_db: float = 20.0, **_: Any,
        ) -> ModelSynthesisResult:
            """C3 spec 综合入口：设计链 → 几何（确定性内核），包装为
            ModelSynthesisResult——只做组装，零数值。

            l_via_h=None：名义几何链开过孔补偿（登记⑨，自动取 Goldfarb-Pucel
            几何值），draft 配方渲染几何在过孔存在下谐振回 f0。
            """
            design = designers[template](order, f0_ghz, fbw, rl_db, l_via_h=None)
            params = _c3_params_from_design(template, design)
            band = (f0_ghz * (1.0 - fbw * 0.475), f0_ghz * (1.0 + fbw * 0.475))
            recipe_draft = {
                "model": template,
                "recipe_version": 1,
                "schema_version": 1,
                "params": {k: {"value": v} for k, v in params.items()},
                "setup": {"solver": "openEMS",
                          "freq_range_ghz": [f0_ghz * 0.7, f0_ghz * 1.3],
                          "points": 401},
                "objectives": [
                    {"metric": "s11_db", "band": [band[0], band[1]],
                     "op": "max_below", "value": -rl_db},
                ],
            }
            return ModelSynthesisResult(
                model=template,
                goal={"f0_ghz": f0_ghz, "fbw": fbw, "rl_db": rl_db,
                      "order": int(order)},
                params=params,
                recipe_draft=recipe_draft,
                notes=list(design["notes"]),
            )
        synthesize_c3_model.__name__ = f"synthesize_{template}_model"
        return synthesize_c3_model

    for template in C3_TEMPLATES:
        register_template_spec(TemplateSpec(
            name=template,
            meta=dict(TEMPLATE_META[template]),
            synthesizer=_make_synthesizer(template),
            # #154：gaps_mm 列表在 fake/openEMS 两通道同索引同语义（第 j 缝边到边）
            physics_roles=dict(_C3_ROLES[template]),
            render_script=partial(render_script, template),
            fake_model=partial(_c3_sparams, template=template),
            hfss_plugin=None,  # 纯 openEMS 锚模板（§C3 滤波器族 II）
        ))


# 阵列族：物理角色只映射语义确定的键（antenna2 同口径）——单元间距无
# 词表角色不映射；q_len（λ/4 变换段）/link_len（λg/2 互联）归 line_length_mm
_ARRAY_TREE_ROLES: dict[str, str] = {
    "elem_len_mm": "resonator_length_mm",
    "elem_w_mm": "patch_width_mm",
    "elem_feed_mm": "feed_offset_mm",
    "feed_w_mm": "line_width_mm",
    "q_w_mm": "impedance_line_width_mm",
    "q_len_mm": "line_length_mm",
}
_ARRAY_ROLES: dict[str, dict[str, str]] = {
    "patch_array_1x4": dict(_ARRAY_TREE_ROLES),
    "patch_array_2x2": dict(_ARRAY_TREE_ROLES),
    "patch_array_series": {
        "elem_len_mm": "resonator_length_mm",
        "elem_w_mm": "patch_width_mm",
        "feed_w_mm": "line_width_mm",
        "link_len_mm": "line_length_mm",
    },
}


def _register_patch_array() -> None:
    from rfauto.adapters.fake_adapter import _array_sparams
    from rfauto.adapters.openems_templates import (
        ARRAY_TEMPLATES,
        TEMPLATE_META,
        array_design_params,
        render_script,
    )
    from rfauto.core.synthesis import ModelSynthesisResult

    def _make_synthesizer(template: str):
        def synthesize_patch_array_model(
            f0_ghz: float = 5.8, s11_target_db: float = -10.0, **_: Any,
        ) -> ModelSynthesisResult:
            """C2 阵列 spec 综合入口：单元 Balanis Ch.14 闭式 + 线宽/λ 段 skrf HJ
            精算（openems_templates.array_design_params 确定性内核，4 位舍入与
            ARRAY_NOMINAL 再生口径一致），包装为 ModelSynthesisResult——只做组装，
            零数值。"""
            params = array_design_params(template, f0_ghz)
            recipe_draft = {
                "model": template,
                "recipe_version": 1,
                "schema_version": 1,
                "params": {k: {"value": v} for k, v in params.items()},
                "setup": {"solver": "openEMS",
                          "freq_range_ghz": [f0_ghz - 0.5, f0_ghz + 0.5],
                          "points": 401},
                "objectives": [
                    {"metric": "s11_db",
                     "band": [f0_ghz * 0.98, f0_ghz * 1.02],
                     "op": "min_below", "value": s11_target_db},
                ],
            }
            return ModelSynthesisResult(
                model=template,
                goal={"f0_ghz": f0_ghz, "s11_target_db": s11_target_db},
                params=params,
                recipe_draft=recipe_draft,
                notes=[f"{template}: 单元 L/W 由 Balanis Ch.14 传输线模型闭式给出，"
                       f"线宽/λ/4/λg/2 由 skrf HJ 精算（理论核验口径，"
                       f"设计式不做端效应预补偿）"],
            )
        synthesize_patch_array_model.__name__ = f"synthesize_{template}_model"
        return synthesize_patch_array_model

    for template in ARRAY_TEMPLATES:
        register_template_spec(TemplateSpec(
            name=template,
            meta=dict(TEMPLATE_META[template]),
            synthesizer=_make_synthesizer(template),
            physics_roles=dict(_ARRAY_ROLES[template]),
            render_script=partial(render_script, template),
            fake_model=partial(_array_sparams, template=template),
            hfss_plugin=None,  # 纯 openEMS 辐射族（阵列族）
        ))


def _slotline_recipe_draft(model: str, params: dict[str, Any],
                           f0_ghz: float,
                           objectives: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": model,
        "recipe_version": 1,
        "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"solver": "openEMS",
                  "freq_range_ghz": [f0_ghz * 0.9, f0_ghz * 1.1],
                  "points": 201},
        "objectives": objectives,
    }


def _register_slotline_family() -> None:
    """槽线族四模板：路线 A/B 均匀槽线
    段 + MSL↔slot 过渡 + Marchand 双槽臂。渲染/(fake/综合)数值零拷贝——渲染走
    openems_templates 文末 SLOTLINE_FAMILY 分发（整脚本渲染器），fake 走
    fake_adapter 同名分支，综合只组装 core 闭式产物（数值只在确定性内核；线宽精算有出处）。#154 角色
    映射只收语义确定键：w_mm=线宽/w_slot_mm=槽缝（gap_width_mm 词表）、
    line_len_mm=线长；x_port_mm/h_mm 无词表条目，各通道按名直读同义（msl_cpw
    先例）。hfss_plugin=None：槽线族 HFSS 仲裁走 scripts/hfss_slotline_*.py
    大截面波端口口径（refs 文献口径），非桌面插件。"""
    from functools import partial

    from rfauto.adapters.fake_adapter import (
        _marchand_balun_sparams,
        _msl_slot_transition_sparams,
        _slotline_route_a_sparams,
        _slotline_route_b_sparams,
    )
    from rfauto.adapters.openems_templates import (
        MARCHAND_BALUN_NOMINAL,
        MSL_SLOT_TRANSITION_NOMINAL,
        SLOTLINE_LUMPED_NOMINAL,
        SLOTLINE_NOMINAL,
        TEMPLATE_META,
        render_script,
    )
    from rfauto.core.synthesis import ModelSynthesisResult

    def _slotline_core(f0_ghz: float, w_mm: float, h_mm: float,
                       er: float) -> tuple[dict[str, Any], list, list, Any]:
        from rfauto.core.slotline import slotline_closed_form

        cf = slotline_closed_form(w_mm, h_mm, er, f0_ghz)
        params: dict[str, Any] = {"w_mm": round(float(w_mm), 4),
                                  "line_len_mm": round(cf.lambda_ratio
                                                       * 299792458.0
                                                       / (f0_ghz * 1e9) * 1e3, 4),
                                  "h_mm": round(float(h_mm), 4)}
        assert set(params) == set(SLOTLINE_NOMINAL) - {"er", "tan_d"}
        objectives = [
            {"metric": "beta_rad_m", "band": [f0_ghz * 0.99, f0_ghz * 1.01],
             "op": "mean_within", "value": [cf.beta_rad_m * 0.97,
                                            cf.beta_rad_m * 1.03]},
            {"metric": "s11_db", "band": [f0_ghz * 0.99, f0_ghz * 1.01],
             "op": "max_below", "value": -15.0},
        ]
        notes = [f"λ'/λ0={cf.lambda_ratio:.5f} → line_len=1λ'={params['line_len_mm']}"
                 f"mm（Janaswamy–Schaubert 闭式 core/slotline 精算，"
                 f"Z0={cf.z0_ohm:.2f}Ω/εeff={cf.eps_eff:.4f}）",
                 "路线 A 真跑前置：模式文件须先经 ngsolve_modes.solve_slotline_mode "
                 "+ openems_slotline_port.write_slotline_mode_files 生成"]
        return params, objectives, notes, cf

    def _slotline_syn(f0_ghz: float = 2.5, w_mm: float = 1.0,
                      h_mm: float = 1.524, er: float = 3.66,
                      **_: Any) -> ModelSynthesisResult:
        params, objectives, notes, cf = _slotline_core(f0_ghz, w_mm, h_mm, er)
        return ModelSynthesisResult(
            model="slotline",
            goal={"f0_ghz": f0_ghz, "z0_ohm": round(cf.z0_ohm, 2),
                  "eps_eff": round(cf.eps_eff, 4)},
            params=params,
            recipe_draft=_slotline_recipe_draft("slotline", params, f0_ghz,
                                                objectives),
            notes=notes)

    def _slotline_lumped_syn(f0_ghz: float = 2.5, w_mm: float = 1.0,
                             h_mm: float = 1.524, er: float = 3.66,
                             **_: Any) -> ModelSynthesisResult:
        params, objectives, notes, cf = _slotline_core(f0_ghz, w_mm, h_mm, er)
        assert set(params) == set(SLOTLINE_LUMPED_NOMINAL) - {"er", "tan_d"}
        return ModelSynthesisResult(
            model="slotline_lumped",
            goal={"f0_ghz": f0_ghz, "z0_ohm": round(cf.z0_ohm, 2),
                  "eps_eff": round(cf.eps_eff, 4)},
            params=params,
            recipe_draft=_slotline_recipe_draft("slotline_lumped", params,
                                                f0_ghz, objectives),
            notes=[*notes, "路线 B：S 参数=并联抽头拓扑（#250），β 生产口径可用、"
                   "S 判读按 tap_network_sparams 换算"])

    def _transition_syn(f0_ghz: float = 2.5, w_slot_mm: float = 1.0,
                        h_mm: float = 1.524, er: float = 3.66,
                        **_: Any) -> ModelSynthesisResult:
        from rfauto.core.slotline_transitions import transition_design

        td = transition_design(f0_ghz, h_mm, er, w_slot_mm)
        params = {"w_slot_mm": round(float(w_slot_mm), 4), "x_port_mm": 40.0,
                  "h_mm": round(float(h_mm), 4)}
        assert set(params) == set(MSL_SLOT_TRANSITION_NOMINAL) - {"er", "tan_d",
                                                                 "f0_ghz"}
        objectives = [
            {"metric": "band_max_s11_db", "band": [f0_ghz * 0.9, f0_ghz * 1.1],
             "op": "max_below", "value": -10.0},
            {"metric": "excess_loss_db_f0", "band": [f0_ghz * 0.99, f0_ghz * 1.01],
             "op": "max_below", "value": 1.0},
        ]
        return ModelSynthesisResult(
            model="msl_slot_transition",
            goal={"f0_ghz": f0_ghz, "z_slot_ohm": round(td.z_slot_ohm, 2),
                  "l_short_mm": round(td.l_short_mm, 4),
                  "l_stub_mm": round(td.l_stub_mm, 4)},
            params=params,
            recipe_draft=_slotline_recipe_draft("msl_slot_transition", params,
                                                f0_ghz, objectives),
            notes=[f"短路臂 λg'/4={td.l_short_mm:.4f}mm、微带支节 λg_m/4+Δl="
                   f"{td.l_stub_mm:.4f}mm、50Ω 微带 w={td.w_msl_mm:.4f}mm"
                   "（Roberts/Knorr 闭式精算 core/slotline_transitions）",
                   "真机基线：HFSS IL 1.37dB 未达 1dB 门——结区优化 followUp"])

    def _marchand_syn(f0_ghz: float = 2.5, w_slot_mm: float = 1.0,
                      h_mm: float = 1.524, er: float = 3.66,
                      **_: Any) -> ModelSynthesisResult:
        from rfauto.core.slotline_transitions import marchand_two_section_nominal

        m2 = marchand_two_section_nominal()
        params = {"w_slot_mm": round(float(w_slot_mm), 4), "x_port_mm": 40.0,
                  "h_mm": round(float(h_mm), 4)}
        assert set(params) == set(MARCHAND_BALUN_NOMINAL) - {"er", "tan_d",
                                                             "f0_ghz"}
        objectives = [
            {"metric": "s11_db", "band": [f0_ghz * 0.9, f0_ghz * 1.1],
             "op": "max_below", "value": -10.0},
            {"metric": "s21_db", "band": [f0_ghz * 0.9, f0_ghz * 1.1],
             "op": "min_above", "value": -3.5},
        ]
        return ModelSynthesisResult(
            model="marchand_balun",
            goal={"f0_ghz": f0_ghz,
                  "two_section_nominal": m2.nominal_params(),
                  "two_section_realizable": m2.realizable,
                  "coupling_db": round(m2.coupling_db, 3)},
            params=params,
            recipe_draft=_slotline_recipe_draft("marchand_balun", params,
                                                f0_ghz, objectives),
            notes=[
                "**单支节最小族已被两引擎互证证伪**（两引擎四门 FAIL）——"
                "本 spec 的 fake/判据面为两节对称耦合段电路级模型（"
                "synthesize_marchand_two_section），与模板双槽臂几何不同源（如实）",
                f"真 Marchand 名义点：50Ω→280Ω 差分、C={m2.coupling_db:.2f}dB、"
                f"(w,s,ℓ)=({m2.w_mm:.4f},{m2.s_mm:.4f},{m2.l_sect_mm:.4f})mm@h={m2.h_mm}"
                f"（电路级门 {'PASS' if m2.model_metrics['all_gates_pass'] else 'FAIL'}）",
            ])

    specs = (
        ("slotline", _slotline_syn, _slotline_route_a_sparams,
         {"w_mm": "line_width_mm", "line_len_mm": "line_length_mm"}),
        ("slotline_lumped", _slotline_lumped_syn, _slotline_route_b_sparams,
         {"w_mm": "line_width_mm", "line_len_mm": "line_length_mm"}),
        ("msl_slot_transition", _transition_syn, _msl_slot_transition_sparams,
         {"w_slot_mm": "gap_width_mm"}),
        ("marchand_balun", _marchand_syn, _marchand_balun_sparams,
         {"w_slot_mm": "gap_width_mm"}),
    )
    for name, syn, fake, roles in specs:
        register_template_spec(TemplateSpec(
            name=name,
            meta=dict(TEMPLATE_META[name]),
            synthesizer=syn,
            physics_roles=dict(roles),
            render_script=partial(render_script, name),
            fake_model=fake,
            hfss_plugin=None,  # 纯 openEMS 模板（HFSS 仲裁走 scripts 大截面波端口）
        ))

def bootstrap_template_specs() -> None:
    """把现有模板 spec 登记进全局注册表（幂等，入口处调用一次）。"""
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _register_wilkinson()
    _register_branchline()
    _register_patch()
    _register_mline()
    _register_cpw()
    _register_dipole()
    _register_stripline()
    _register_stepped_impedance()
    _register_coupled_line()
    _register_cps()
    _register_suspended_stripline()
    _register_msl_cpw()
    _register_sma_launcher()
    _register_wstep()
    _register_tjunc()
    _register_bend()
    _register_via()
    _register_atten_pi()
    _register_atten_t()
    _register_ratrace()
    _register_gysel()
    _register_hairpin()
    _register_hairpin_alt()
    _register_coupled_bpf()
    _register_antenna2()
    _register_c3_filters()
    _register_patch_array()
    _register_cline_coupler()
    _register_branchline_2sect()
    _register_lange()
    _register_slotline_family()
    _BOOTSTRAPPED = True


bootstrap_template_specs()
