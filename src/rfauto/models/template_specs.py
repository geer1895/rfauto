"""现有模板的 TemplateSpec 收拢（WP2.0：新模板 = 在此文件加一个条目）。

AU-1 b4 同构注册收缩：22 个「直引综合内核 + 直引 fake 模型 + 角色表」的
模板注册由 :data:`_SIMPLE_SPECS` 数据表 + :func:`_register_simple_spec`
单点注册循环驱动（新同构模板 = 表加一行 + bootstrap plan 加一个名字）；
定制注册（本地综合闭包/族循环）保留独立函数。行为零变化：注册序、
TemplateSpec 六件套字段、组件对象身份与收缩前逐位一致（快照钉
runs/au1_b4/ts_surface_{before,after}.json）。

组件引用全部在注册时 import——保持插件 entry-point 发现的启动轻量
（models 层允许 import adapters/core，见 .importlinter 分层）。
"""

from __future__ import annotations

import math
from functools import partial
from typing import Any

from rfauto.core.synthesis import nominal_width_mm
from rfauto.models.template_spec import (
    TEMPLATE_SPECS,
    TemplateSpec,
    register_template_spec,
)

__all__ = ["TEMPLATE_SPECS", "bootstrap_template_specs"]

#: 同构注册行：(模板名, 综合内核名(core.synthesis 属性), fake 模型公开名
#: (fake_adapter 公开别名，AU-1 b4 私有名公开化), hfss_plugin, 物理角色表)。
_SimpleSpecEntry = tuple[str, str, str, "str | None", dict[str, str]]

# 注册序 = 表序（与原 bootstrap 调用序逐位一致；plan 引用见文末）。
_SIMPLE_SPECS: tuple[_SimpleSpecEntry, ...] = (
    # ── 首批模板（WP1.x）──
    ("wilkinson", "synthesize_wilkinson", "wilkinson_sparams_3port",
     "wilkinson_power_divider",
     {"arm_len_mm": "resonator_length_mm",
      "series_w_mm": "impedance_line_width_mm",
      "shunt_w_mm": "shunt_line_width_mm"}),
    ("branchline", "synthesize_branchline", "branchline_sparams",
     "branchline_coupler",
     {"arm_len_mm": "resonator_length_mm",
      "series_w_mm": "impedance_line_width_mm",
      "shunt_w_mm": "shunt_line_width_mm"}),
    ("patch", "synthesize_patch", "patch_sparams_1port",
     "patch_antenna",
     {"patch_len_mm": "resonator_length_mm",
      "patch_w_mm": "patch_width_mm",
      "feed_offset_mm": "feed_offset_mm"}),
    # 以下均纯 openEMS 锚模板（hfss_plugin=None）
    ("mline", "synthesize_mline_model", "mline_sparams", None,
     {"w_mm": "line_width_mm",
      "line_len_mm": "line_length_mm"}),
    ("cpw", "synthesize_cpw_model", "cpw_sparams", None,
     {"w_mm": "line_width_mm",
      "gap_mm": "gap_width_mm",
      "line_len_mm": "line_length_mm"}),
    ("dipole", "synthesize_dipole_model", "dipole_sparams", None,
     {"dipole_len_mm": "resonator_length_mm"}),  # 辐射器件族
    # TEM：εeff=εr，解析同形（fake 复用 mline_sparams）
    ("stripline", "synthesize_stripline_model", "mline_sparams", None,
     {"w_mm": "line_width_mm",
      "line_len_mm": "line_length_mm"}),
    # ── C9 传输线族 II / Tier 2 过渡族 / 不连续性基元族 / Tier 1 ──
    # #154：w_mm=单带宽、gap_mm=两带间缝、line_len_mm=两端口间线长——fake
    # （_cps_ri）与 openEMS（_cps_lines）逐参数同语义
    ("cps", "synthesize_cps_model", "cps_sparams", None,
     {"w_mm": "line_width_mm",
      "gap_mm": "gap_width_mm",
      "line_len_mm": "line_length_mm"}),
    # b_mm=腔高（两地面间距）无角色词表条目，按名直读（fake/openEMS 同名同义）
    ("suspended_stripline", "synthesize_suspended_stripline_model",
     "suspended_stripline_sparams", None,
     {"w_mm": "line_width_mm",
      "line_len_mm": "line_length_mm"}),
    # #154 只映射语义确定键：w_msl_mm=微带段线宽（50Ω 口径）、gap_cpw_mm=CPW
    # 缝、line_len_mm=总长；w_cpw_mm（CPWG 中心带宽）/渐变区/过孔栅栏参数无
    # 角色词表条目，fake/openEMS 按名直读同义
    ("msl_cpw", "synthesize_msl_cpw_model", "msl_cpw_sparams", None,
     {"w_msl_mm": "line_width_mm",
      "gap_cpw_mm": "gap_width_mm",
      "line_len_mm": "line_length_mm"}),
    # #154：w_msl_mm=微带段线宽、line_len_mm=微带体带长；同轴几何（r_i/r_o/
    # shell_t/er_fill/shell_len/pin_lay/port_len）无角色词表条目，按名直读
    ("sma_launcher", "synthesize_sma_launcher_model", "sma_launcher_sparams",
     None,
     {"w_msl_mm": "line_width_mm",
      "line_len_mm": "line_length_mm"}),
    ("wstep", "synthesize_wstep_model", "wstep_sparams", None,
     {"w1_mm": "line_width_mm",
      "w2_mm": "step_width_mm",
      "line_len_mm": "line_length_mm"}),
    ("tjunc", "synthesize_tjunc_model", "tjunc_sparams", None,
     {"w_feed_mm": "line_width_mm",
      "through_len_mm": "line_length_mm",
      "branch_len_mm": "branch_length_mm"}),
    ("bend", "synthesize_bend_model", "bend_sparams", None,
     {"w_mm": "line_width_mm",
      "arm_len_mm": "line_length_mm"}),
    ("via", "synthesize_via_model", "via_sparams", None,
     {"w_mm": "line_width_mm"}),
    ("atten_pi", "synthesize_atten_pi_model", "atten_pi_sparams", None,
     {"w_mm": "line_width_mm"}),
    ("atten_t", "synthesize_atten_t_model", "atten_t_sparams", None,
     {"w_mm": "line_width_mm"}),
    ("ratrace", "synthesize_ratrace_model", "ratrace_sparams", None,
     {"w_ring_mm": "line_width_mm"}),
    ("gysel", "synthesize_gysel_model", "gysel_sparams", None,
     {"w_arm_mm": "impedance_line_width_mm",
      "w_feed_mm": "shunt_line_width_mm",
      "arm_len_mm": "resonator_length_mm",
      "iso_len_mm": "line_length_mm"}),
    # 综合入口已下沉 core（WP2.3 收口 ⑦，2026-09-16）：原本地闭包 →
    # core/synthesis.synthesize_hairpin_model（本表只做注册组装，零数值）
    ("hairpin", "synthesize_hairpin_model", "hairpin_sparams", None,
     {"w_mm": "line_width_mm",
      "arm_len_mm": "resonator_length_mm",
      "gap_mm": "gap_width_mm"}),
    # ── SIW 族 ──
    # #154 角色映射只收语义确定键：w_mm=两过孔列心距（line_width_mm 词表
    # 口径）、line_len_mm=两端口面间距；d_mm/s_mm 无词表条目按名直读同义
    # （suspended_stripline b_mm 先例）。f0=10GHz 设计点（2.5GHz 下 SIW
    # 物理上装不下 60mm 板，runs/siw_family/criteria.md §2）
    ("siw", "synthesize_siw_model", "siw_sparams", None,
     {"w_mm": "line_width_mm",
      "line_len_mm": "line_length_mm"}),
    # Deslandes-Wu 两段论：锥=50Ω MSL→Z_PV 阻抗变换器+锥末-SIW 台阶；双
    # MSLPort 线基（CalcPort ref=50 主口径，line_z0=engine 反演旋钮留判读
    # 侧）。#154：w_mm=两过孔列心距、siw_len_mm=线段长；d_mm/s_mm/
    # taper_len_mm 无词表条目按名直读同义。预声明门
    # runs/df6_a2siwmsl/criteria.md §4
    ("msl_siw_taper", "synthesize_msl_siw_taper_model",
     "msl_siw_taper_sparams", None,
     {"w_mm": "line_width_mm",
      "siw_len_mm": "line_length_mm"}),
)


def _register_simple_spec(entry: _SimpleSpecEntry) -> None:
    """同构注册单点：表行 → TemplateSpec 六件套（行为与原样板函数逐位一致）。

    synthesizer/fake_model 经模块属性名解析——与原逐名 from-import 绑定
    **同一函数对象**；meta/roles 显式 dict() 拷贝（与原内联字面量同语义，
    每次注册独立副本）；render_script 每次注册新建 partial（func/args 同）。
    缺属性经 getattr 报 AttributeError（原 ImportError 的同义失败面，
    编程错误由注册表测试当场抓）。
    """
    name, synth_name, fake_name, hfss_plugin, roles = entry
    from rfauto.adapters import fake_adapter
    from rfauto.adapters.openems_templates import TEMPLATE_META, render_script
    from rfauto.core import synthesis

    register_template_spec(TemplateSpec(
        name=name,
        meta=dict(TEMPLATE_META[name]),
        synthesizer=getattr(synthesis, synth_name),
        physics_roles=dict(roles),
        render_script=partial(render_script, name),
        fake_model=getattr(fake_adapter, fake_name),
        hfss_plugin=hfss_plugin,
    ))


def _register_hairpin_alt() -> None:
    # 交替取向 hairpin（2026-09-18 w2g，TODO 0dk 根修）：综合入口 = core 的
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
        hfss_plugin=None,  # 纯 openEMS 锚模板（WP2.3 BPF 族锚）
    ))


# 天线族 II 各模板：闭式设计函数（openems_templates §10.3 C1）+ 物理角色
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
                     "op": "max_below", "value": s11_target_db},
                ],
            }
            return ModelSynthesisResult(
                model=template,
                goal={"f0_ghz": f0_ghz, "s11_target_db": s11_target_db},
                params=params,
                recipe_draft=recipe_draft,
                notes=[f"{template}: 谐振尺寸由 openems_templates 闭式设计函数"
                       f"给出（§10.3 C1 理论核验口径，设计式不做端效应预补偿）"],
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
            hfss_plugin=None,  # 纯 openEMS 辐射族（§10.3 C1 天线族 II）
        ))


# ─── §C4 耦合器族 II：cline_coupler / branchline_2sect / lange（2026-09-16 注册）──
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


# ─── 初始模板补注册：stepped_impedance / coupled_line（2026-09-16，antenna2
# followups 六项之 D）── 首批模板（WP1.x）有渲染/元数据但无 TemplateSpec（
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
            # feed_w_mm=50Ω 馈线宽（六百七十一/#1c 修复批）：宽度是阻抗定义
            # 量，2.4GHz 标称 1.1133mm；f0 扫描时按常数沿用（HJ 50Ω 宽随 f0
            # 弱漂移 <0.5%@±50%，设计面名义口径）
            "feed_w_mm": float(nominal["feed_w_mm"]),
        }
        stackup = Stackup(name="stepped_impedance_spec", epsilon_r=3.66,
                          thickness_mm=0.508)
        z1, ere1 = forward_z0(float(nominal["z1_width_mm"]), float(f0_ghz),
                              stackup)
        z2, ere2 = forward_z0(float(nominal["z2_width_mm"]), float(f0_ghz),
                              stackup)
        zf, eref = forward_z0(float(nominal["feed_w_mm"]), float(f0_ghz),
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
                 "op": "max_below", "value": -10.0},
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
                f" εeff={ere2:.4f}，FEED({nominal['feed_w_mm']}mm)={zf:.3f}Ω"
                f" εeff={eref:.4f}（@f0，rogers4350b；feed=50Ω 馈线"
                "六百七十一/#1c 修复批）",
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
            "feed_w_mm": "feed_line_width_mm",
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


# ─── §C3 滤波器族 II：interdigital / combline / sir_bpf（2026-09-15 注册）─────
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

            l_via_h=None：名义几何链开过孔补偿（登记⑨+R1 校准 df5-c3fix，自动取
            HFSS 仲裁校准值 C3_L_VIA_CAL_H=0.125nH，原 Goldfarb-Pucel 几何值
            高估已弃），新战役 draft 配方渲染几何在过孔存在下谐振回 f0。
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


# §10.3 C2 阵列族：物理角色只映射语义确定的键（antenna2 同口径）——单元间距无
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
                     "op": "max_below", "value": s11_target_db},
                ],
            }
            return ModelSynthesisResult(
                model=template,
                goal={"f0_ghz": f0_ghz, "s11_target_db": s11_target_db},
                params=params,
                recipe_draft=recipe_draft,
                notes=[f"{template}: 单元 L/W 由 Balanis Ch.14 传输线模型闭式给出，"
                       f"线宽/λ/4/λg/2 由 skrf HJ 精算（§10.3 C2 理论核验口径，"
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
            hfss_plugin=None,  # 纯 openEMS 辐射族（§10.3 C2 阵列族）
        ))


def _register_eep_array() -> None:
    """§DP-4 P3 EEP 阵列族（2026-09-24 df6）：patch_eep_2x2/patch_eep_1x4。

    每元独立 LumpedPort 探针 1..4、无 corporate 馈树（互耦档 EEP 专用）；
    综合入口复用 C2 阵列单元闭式设计链（openems_templates.eep_design_params：
    Balanis Ch.14 单元 + skrf HJ 线宽 + 0.484λ0 间距，4 位舍入与 EEP_NOMINAL
    再生口径一致）。#154 角色映射只收语义确定键（C2 同口径）：spacing 无词表
    角色不映射。hfss_plugin=None（HFSS Floquet 锚走独立脚本，DP-4 §2d）。
    """
    from rfauto.adapters.fake_adapter import _eep_sparams
    from rfauto.adapters.openems_templates import (
        EEP_TEMPLATES,
        TEMPLATE_META,
        eep_design_params,
        render_script,
    )
    from rfauto.core.synthesis import ModelSynthesisResult

    _EEP_ROLES: dict[str, str] = {
        "elem_len_mm": "resonator_length_mm",
        "elem_w_mm": "patch_width_mm",
        "elem_feed_mm": "feed_offset_mm",
        "feed_w_mm": "line_width_mm",
    }

    def _make_synthesizer(template: str):
        def synthesize_eep_array_model(
            f0_ghz: float = 5.8, s11_target_db: float = -10.0, **_: Any,
        ) -> ModelSynthesisResult:
            """EEP 阵 spec 综合入口：单元 Balanis Ch.14 闭式 + 线宽 skrf HJ 精算
            （openems_templates.eep_design_params 确定性内核），包装为
            ModelSynthesisResult——只做组装，零数值。"""
            params = eep_design_params(template, f0_ghz)
            recipe_draft = {
                "model": template,
                "recipe_version": 1,
                "schema_version": 1,
                "params": {k: {"value": v} for k, v in params.items()},
                "setup": {"solver": "openEMS",
                          "freq_range_ghz": [f0_ghz - 0.25, f0_ghz + 0.25],
                          "points": 401},
                "objectives": [
                    {"metric": "s11_db",
                     "band": [f0_ghz * 0.98, f0_ghz * 1.02],
                     "op": "max_below", "value": s11_target_db},
                ],
            }
            return ModelSynthesisResult(
                model=template,
                goal={"f0_ghz": f0_ghz, "s11_target_db": s11_target_db},
                params=params,
                recipe_draft=recipe_draft,
                notes=[f"{template}: 单元 L/W 由 Balanis Ch.14 传输线模型闭式给出，"
                       "线宽由 skrf HJ 精算、间距 0.484λ0（§DP-4 P3 EEP 理论核验"
                       "口径；互耦档真机判据 J4 见 runs/df6_dp4p3/criteria.md）"],
            )
        synthesize_eep_array_model.__name__ = f"synthesize_{template}_model"
        return synthesize_eep_array_model

    for template in EEP_TEMPLATES:
        register_template_spec(TemplateSpec(
            name=template,
            meta=dict(TEMPLATE_META[template]),
            synthesizer=_make_synthesizer(template),
            physics_roles=dict(_EEP_ROLES),
            render_script=partial(render_script, template),
            fake_model=partial(_eep_sparams, template=template),
            hfss_plugin=None,  # 纯 openEMS 辐射族（HFSS Floquet 锚另派）
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


# ─── §VI-3 W2-B spec 补齐 22 模板（2026-10-05 Phase 2 批 W2-B 席）────────────
# 三小批（VI-3 规格；分批=族归类）：①传输线/波导均匀段与过渡 9（embedded_ms/
# fgcpw/inverted_ms/isl_shielded/hmsiw/sicl/qwt_multisection/
# coax_waveguide_transition/ridged_wg）②辐射/超表面/材料 8（ms_patch/ms_cross/
# ms_jcross/ms_ring_patch/ms_array_NxN/pyramid_horn/vivaldi_tsa/
# ring_resonator）③滤波/功分/移相 5（diplexer/nway_wilkinson/schiffman/
# varactor_bpf/xcheb_bpf4）。
#
# 综合入口纪律（铁律 7/#1c/#252）：毫秒-秒级设计链一律真复算（与
# test_*_templates 的名义按链复算钉同源同值）；FD 反演慢链（embedded_ms
# ~22s/fgcpw ~46s/inverted_ms ~13s——render_ta_wave_c 注如实账，ta_wave 测试
# 同样不整链复算）引 TEMPLATE_NOMINAL 名义值（HJ/FD 精算值已在 META），
# 禁手抄毫米数捷径。物理角色只收语义确定键（#154，ROLE_CANDIDATES 词表内），
# 其余键按名直读同义（suspended_stripline b_mm 先例）。
#
# fake_model=None：22 模板无已标定 fake 前向模型（FakeAdapter.solve 的
# model_type 分派同样未注册这 21 个名字——varactor_bpf 的 fake 走 solve 内联
# 分派支路，无可提取的独立函数面），行为与 spec 注册互相一致；按 TemplateSpec
# 显式缺失语义（"可见但不可用，绝不静默"）注册 None——describe()/CLI 清单
# 如实显示 ✗，component(name,"fake_model") 抛 TemplateComponentMissing。
# hfss_plugin=None：纯 openEMS 锚模板（同槽线族口径，HFSS 仲裁走 scripts）。


def _vi3_recipe_draft(template: str, params: dict[str, Any],
                      f0_ghz: float, objectives: list[dict[str, Any]],
                      band_frac: float = 0.96,
                      points: int = 401) -> dict[str, Any]:
    """VI-3 批通用配方草稿骨架（与 _c4_recipe_draft 同构；零数值组装）。"""
    return {
        "model": template,
        "recipe_version": 1,
        "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"solver": "openEMS",
                  "freq_range_ghz": [f0_ghz * band_frac, f0_ghz / band_frac],
                  "points": points},
        "objectives": objectives,
    }


def _vi3_s11_objective(f0_ghz: float, rl_db: float = -15.0,
                       band_frac: float = 0.96) -> list[dict[str, Any]]:
    """均匀段/一端口族缺省回损目标（mline 先例口径）。"""
    return [{"metric": "s11_db", "band": [f0_ghz * band_frac,
                                          f0_ghz / band_frac],
             "op": "max_below", "value": rl_db}]


def _register_vi3_lines() -> None:
    """批① 传输线均匀段族 6 件（TA-7/8/9/10/11 + TA-3）：设计链复算或名义
    引用（FD 慢链），缺省实参复现 TEMPLATE_NOMINAL 名义值（毫秒链逐位、
    FD 慢链按 META 引用，口径见段头注）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL, render_script
    from rfauto.core.synthesis import ModelSynthesisResult

    def _line_syn(template: str, nominal: dict[str, Any],
                  provenance: str):
        def synthesize(f0_ghz: float = 2.5, **_: Any):
            # FD 慢链名义引用档：几何=TEMPLATE_NOMINAL（#252 引名义值），
            # f0 只进 goal/频窗（准静态设计点弱频变，移点重综合=显式 FD
            # 复算归 P3 批，本档如实登记不假装重算）。
            params = {k: ([round(float(x), 4) for x in v]
                          if isinstance(v, list) else round(float(v), 4))
                      for k, v in nominal.items()}
            return ModelSynthesisResult(
                model=template,
                goal={"f0_ghz": float(f0_ghz), "design_point": "nominal"},
                params=params,
                recipe_draft=_vi3_recipe_draft(
                    template, params, float(f0_ghz),
                    _vi3_s11_objective(float(f0_ghz))),
                notes=[
                    provenance,
                    "FD 反演慢链（嵌入式 ~22s/FGCPW ~46s/倒置 ~13s，"
                    "render_ta_wave_c 注如实账）：本 spec 引 TEMPLATE_NOMINAL"
                    " 名义值（FD 精算已在 META，#252 禁手抄）；f0 移点重综合"
                    "走 FD 链显式复算（P3 批面）",
                ])
        synthesize.__name__ = f"synthesize_{template}_model"
        return synthesize

    # ── TA-11 embedded_ms / TA-9 fgcpw / TA-7 inverted_ms：FD 慢链名义引用 ──
    _emb = TEMPLATE_NOMINAL["embedded_ms"]
    register_template_spec(TemplateSpec(
        name="embedded_ms",
        meta=dict(TEMPLATE_META["embedded_ms"]),
        synthesizer=_line_syn(
            "embedded_ms", _emb,
            "名义几何=embedded_ms_design_params(50Ω, h1=0.508, h2=0.254, "
            "er=3.66) FD 反演预精算值（w=1.0014 回代 49.999Ω，εeff=3.24008"
            "——core/embedded_line FD 裁判链，test_ta_wave_c_templates 钉）"),
        physics_roles={"w_mm": "line_width_mm",
                       "line_len_mm": "line_length_mm"},
        render_script=partial(render_script, "embedded_ms"),
        fake_model=None,  # 无已标定 fake 前向模型（段头注口径）
        hfss_plugin=None,
    ))
    _fg = TEMPLATE_NOMINAL["fgcpw"]
    register_template_spec(TemplateSpec(
        name="fgcpw",
        meta=dict(TEMPLATE_META["fgcpw"]),
        synthesizer=_line_syn(
            "fgcpw", _fg,
            "名义几何=fgcpw_design_params(50Ω, gap=0.2, gnd=4.0, h=0.508, "
            "er=3.66) FD 反演预精算值（w=4.3466 回代 50.000Ω，εeff=1.8303"
            "；G-N 文献闭式同点偏差 εeff −6.6%/Z0 −3.6% 如实在账，#302 同族）"),
        physics_roles={"w_mm": "line_width_mm", "gap_mm": "gap_width_mm",
                       "line_len_mm": "line_length_mm"},
        render_script=partial(render_script, "fgcpw"),
        fake_model=None,
        hfss_plugin=None,
    ))
    _inv = TEMPLATE_NOMINAL["inverted_ms"]
    register_template_spec(TemplateSpec(
        name="inverted_ms",
        meta=dict(TEMPLATE_META["inverted_ms"]),
        synthesizer=_line_syn(
            "inverted_ms", _inv,
            "名义几何=inverted_ms_design_params(50Ω, h_air=h_sub=0.508, "
            "er=3.66) FD 反演预精算值（w=2.1359 回代 49.9994Ω，εeff=1.2467"
            "——倒置微带定义性质，test_ta_wave_a_templates 钉）"),
        physics_roles={"w_mm": "line_width_mm",
                       "line_len_mm": "line_length_mm"},
        render_script=partial(render_script, "inverted_ms"),
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── TA-10 isl_shielded：准静态链毫秒级真复算（w 由链给，d/s/line_len=档位惯例）──
    def synthesize_isl_shielded_model(
        f0_ghz: float = 2.5, z0_ohm: float = 50.0, **_: Any,
    ) -> ModelSynthesisResult:
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL as _TN
        from rfauto.core.isl_line import isl_design_params

        nominal = _TN["isl_shielded"]
        d = isl_design_params(z0_ohm=z0_ohm,
                              g_air_mm=float(nominal["g_air_mm"]),
                              h_sub_mm=0.508,
                              h_top_mm=float(nominal["h_top_mm"]),
                              er=float(nominal["er"]))
        params: dict[str, Any] = {
            "w_mm": float(d["w_mm"]),
            "g_air_mm": float(nominal["g_air_mm"]),
            "h_top_mm": float(nominal["h_top_mm"]),
            "d_mm": float(nominal["d_mm"]),
            "s_mm": float(nominal["s_mm"]),
            "line_len_mm": float(nominal["line_len_mm"]),
            "er": float(nominal["er"]),
            "tan_d": float(nominal["tan_d"]),
        }
        assert set(params) == set(nominal)
        return ModelSynthesisResult(
            model="isl_shielded",
            goal={"f0_ghz": float(f0_ghz), "z0_ohm": float(d["z0_ohm"]),
                  "eps_eff": float(d["eps_eff"])},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "isl_shielded", params, float(f0_ghz),
                _vi3_s11_objective(float(f0_ghz))),
            notes=[
                f"w={d['w_mm']}mm（目标 {z0_ohm}Ω，回代 {d['z0_ohm']}Ω，"
                f"εeff={d['eps_eff']}——core/isl_line 双半腔 Cohn 准静态 "
                "brentq 反解，毫秒级链真复算）",
                "d/s/line_len=siw 同源档/40mm 惯例（设计链不产，引名义档；"
                "#154 无词表条目按名直读同义）",
            ])

    register_template_spec(TemplateSpec(
        name="isl_shielded",
        meta=dict(TEMPLATE_META["isl_shielded"]),
        synthesizer=synthesize_isl_shielded_model,
        physics_roles={"w_mm": "line_width_mm",
                       "line_len_mm": "line_length_mm"},
        render_script=partial(render_script, "isl_shielded"),
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── TA-8 hmsiw：设计链真复算（w 链给 + line_len=3λg@f0 式 (12) β）──
    def synthesize_hmsiw_model(
        f0_ghz: float = 10.0, **_: Any,
    ) -> ModelSynthesisResult:
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL as _TN
        from rfauto.core.hmsiw import hmsiw_beta_rad_m, hmsiw_closed_form, hmsiw_design_params

        nominal = _TN["hmsiw"]
        fc_target = float(f0_ghz) / 1.5   # 论文 §II.B：fc≈f0/1.5 名义规则
        d = hmsiw_design_params(fc10_target_ghz=fc_target,
                                er=float(nominal["er"]),
                                h_mm=float(nominal["h_mm"]),
                                d_mm=float(nominal["d_mm"]),
                                s_mm=float(nominal["s_mm"]))
        # 式 (12) β 链自 4 位舍入名义 w 起算（siw "链路与综合逐位同源：
        # 4 位舍入 w 起算" 同构造，test_hmsiw_nominal_chain_recompute 口径）
        ch_nom = hmsiw_closed_form(round(float(d["w_mm"]), 4),
                                   float(nominal["h_mm"]),
                                   float(nominal["er"]),
                                   float(nominal["d_mm"]),
                                   float(nominal["s_mm"]))
        beta, _fc = hmsiw_beta_rad_m(ch_nom["w_eff_hmsiw_mm"],
                                     float(nominal["er"]), float(f0_ghz))
        lam_g_mm = 2.0 * math.pi / beta * 1e3
        params: dict[str, Any] = {
            "w_mm": round(float(d["w_mm"]), 4),
            "d_mm": float(nominal["d_mm"]),
            "s_mm": float(nominal["s_mm"]),
            "line_len_mm": round(3.0 * lam_g_mm, 4),
            "h_mm": float(nominal["h_mm"]),
            "er": float(nominal["er"]),
            "tan_d": float(nominal["tan_d"]),
        }
        assert set(params) == set(nominal)
        return ModelSynthesisResult(
            model="hmsiw",
            goal={"f0_ghz": float(f0_ghz), "fc_te05_ghz": round(
                float(d["fc_te05_ghz"]), 6)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "hmsiw", params, float(f0_ghz),
                _vi3_s11_objective(float(f0_ghz))),
            notes=[
                f"w={params['w_mm']}mm（fc 目标 {fc_target:.4f}=f0/1.5，"
                f"式 (8)(9)(13)(10)(11) brentq 反解，回代 fc="
                f"{d['fc_te05_ghz']:.6f}GHz）",
                f"line_len=3λg@f0={params['line_len_mm']}mm"
                f"（β={beta:.5f} rad/m 式 (12)，λg={lam_g_mm:.5f}mm——siw "
                "同构造 3λg 口径）",
            ])

    register_template_spec(TemplateSpec(
        name="hmsiw",
        meta=dict(TEMPLATE_META["hmsiw"]),
        synthesizer=synthesize_hmsiw_model,
        physics_roles={"w_mm": "line_width_mm",
                       "line_len_mm": "line_length_mm"},
        render_script=partial(render_script, "hmsiw"),
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── TA-3 sicl：共形闭式 brentq 反解真复算（sicl_design_params 单源）──
    def synthesize_sicl_model(
        f0_ghz: float = 2.5, z0_ohm: float = 50.0, **_: Any,
    ) -> ModelSynthesisResult:
        from rfauto.adapters.oe_templates.render_sicl_nway import sicl_design_params
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL as _TN

        nominal = _TN["sicl"]
        d = sicl_design_params(f0_ghz=float(f0_ghz), z0_ohm=z0_ohm,
                               eps_r=float(nominal["er"]))
        params: dict[str, Any] = {
            "w_mm": float(d["w_mm"]),
            "a_mm": float(d["a_mm"]),
            "d_mm": float(d["d_mm"]),
            "s_mm": float(d["s_mm"]),
            "line_len_mm": float(d["line_len_mm"]),
            "h_mm": float(nominal["h_mm"]),
            "er": float(nominal["er"]),
            "tan_d": float(nominal["tan_d"]),
        }
        assert set(params) == set(nominal)
        return ModelSynthesisResult(
            model="sicl",
            goal={"f0_ghz": float(f0_ghz), "z0_ohm": float(z0_ohm)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "sicl", params, float(f0_ghz),
                _vi3_s11_objective(float(f0_ghz))),
            notes=[
                f"a/b=2.5 档 → a={d['a_mm']}mm；w={d['w_mm']}mm（Z0={z0_ohm}"
                "Ω 共形闭式 brentq 反解，回代自洽 |ΔZ0|≤1e-9·Z0 内核断言——"
                "sicl_design_params 单源，test_sicl_nway_templates 钉）",
                "d/s=0.6/1.0 siw 同源档、line_len=40mm 惯例（链给非手抄）",
            ])

    register_template_spec(TemplateSpec(
        name="sicl",
        meta=dict(TEMPLATE_META["sicl"]),
        synthesizer=synthesize_sicl_model,
        physics_roles={"w_mm": "line_width_mm",
                       "line_len_mm": "line_length_mm"},
        render_script=partial(render_script, "sicl"),
        fake_model=None,
        hfss_plugin=None,
    ))


def _register_vi3_waveguide() -> None:
    """批①续 过渡/阻抗变换/波导 3 件（TA-2/TA-12(同轴)/TA-6）：设计链全复算。"""
    from rfauto.adapters.openems_templates import (
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
        coax_wg_design_params,
        qwt_multisection_design_params,
        render_script,
        ridged_wg_design_params,
    )
    from rfauto.core.synthesis import ModelSynthesisResult

    # ── TA-2 qwt_multisection：一阶小反射表驱动 + HJ（链 19ms）──
    def synthesize_qwt_multisection_model(
        f0_ghz: float = 2.5, z0_ohm: float = 50.0, zl_ohm: float = 100.0,
        n_sections: int = 3, profile: str = "binomial",
        ripple_db: float = -20.0, **_: Any,
    ) -> ModelSynthesisResult:
        nominal = TEMPLATE_NOMINAL["qwt_multisection"]
        d = qwt_multisection_design_params(f0_ghz=f0_ghz, z0_ohm=z0_ohm,
                                           zl_ohm=zl_ohm,
                                           n_sections=int(n_sections),
                                           profile=str(profile),
                                           ripple_db=float(ripple_db))
        params: dict[str, Any] = {
            "widths_mm": list(d["widths_mm"]),
            "lengths_mm": list(d["lengths_mm"]),
            "feed_w_mm": float(d["feed_w_mm"]),
            "z_load_ohm": float(d["z_load_ohm"]),
        }
        assert set(params) == set(nominal)
        return ModelSynthesisResult(
            model="qwt_multisection",
            goal={"f0_ghz": float(f0_ghz), "z0_ohm": float(z0_ohm),
                  "zl_ohm": float(zl_ohm), "profile": str(profile),
                  "ripple_db": float(ripple_db)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "qwt_multisection", params, float(f0_ghz),
                _vi3_s11_objective(float(f0_ghz))),
            notes=[
                "节阻抗=一阶小反射表驱动闭式（"
                "synthesize_multisection_quarter_wave 内核），各节 HJ 线宽/"
                "εeff/物理 λ/4 长；馈线 inverse_width 50Ω（"
                "qwt_multisection_design_params 单源，"
                "test_schiffman_qwt_templates 反解自洽钉）",
                "末节 LumpedElement R=ZL 端接盒（mmwave_series_array 链末"
                "负载同法）；节间阶梯不连续性不进闭式裁判（meta 注如实）",
            ])

    register_template_spec(TemplateSpec(
        name="qwt_multisection",
        meta=dict(TEMPLATE_META["qwt_multisection"]),
        synthesizer=synthesize_qwt_multisection_model,
        physics_roles={"widths_mm": "impedance_line_width_mm",
                       "lengths_mm": "line_length_mm",
                       "feed_w_mm": "line_width_mm"},
        render_script=partial(render_script, "qwt_multisection"),
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── WR 表联动同轴-波导过渡（coax_wg_design_params，链即时）──
    def synthesize_coax_waveguide_transition_model(
        f0_ghz: float = 10.0, wr_name: str = "WR-90", **_: Any,
    ) -> ModelSynthesisResult:
        nominal = TEMPLATE_NOMINAL["coax_waveguide_transition"]
        d = coax_wg_design_params(wr_name=str(wr_name), f0_ghz=float(f0_ghz),
                                  l_wg_mm=float(nominal["l_wg_mm"]))
        params: dict[str, Any] = {
            "a_mm": float(d["a_mm"]),
            "b_mm": float(d["b_mm"]),
            "l_wg_mm": float(d["l_wg_mm"]),
            "wg_t_mm": float(d["wg_t_mm"]),
            "pin_len_mm": float(d["pin_len_mm"]),
            "pin_r_mm": float(d["pin_r_mm"]),
            "port_h_mm": float(d["port_h_mm"]),
            "backshort_mm": float(d["backshort_mm"]),
            "er": float(nominal["er"]),
            "h_mm": float(nominal["h_mm"]),
        }
        assert set(params) == set(nominal)
        return ModelSynthesisResult(
            model="coax_waveguide_transition",
            goal={"f0_ghz": float(f0_ghz), "wr_name": str(wr_name)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "coax_waveguide_transition", params, float(f0_ghz),
                _vi3_s11_objective(float(f0_ghz))),
            notes=[
                f"{wr_name} 表联动（wr_lookup 单源）：a/b=WR 口径、"
                f"pin_len=0.55·b（官方教程比例）、backshort=λg/4@{f0_ghz}GHz"
                "（TE10 λg 闭式）——coax_wg_design_params 单源，"
                "test_coax_wg_template 钉",
                "port1=探针基 LumpedPort（R=50Ω）、port2=RectWGPort 解析 "
                "TE10（跨口 sqrt(ZL1/ZL2) 阻抗校正，官方 wiki 口径）",
            ])

    register_template_spec(TemplateSpec(
        name="coax_waveguide_transition",
        meta=dict(TEMPLATE_META["coax_waveguide_transition"]),
        synthesizer=synthesize_coax_waveguide_transition_model,
        physics_roles={"pin_r_mm": "line_width_mm"},
        render_script=partial(render_script, "coax_waveguide_transition"),
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── TA-6 ridged_wg：横磁共振方程二分反解脊深（design_ridge_depth 内核）──
    def synthesize_ridged_wg_model(
        fc_target_ghz: float = 5.0, a_mm: float = 22.86, b_mm: float = 10.16,
        s_mm: float = 9.144, **_: Any,
    ) -> ModelSynthesisResult:
        nominal = TEMPLATE_NOMINAL["ridged_wg"]
        d = ridged_wg_design_params(a_mm=float(a_mm), b_mm=float(b_mm),
                                    s_mm=float(s_mm),
                                    fc_target_ghz=float(fc_target_ghz),
                                    l_ridge_mm=float(nominal["l_ridge_mm"]),
                                    l_feed_mm=float(nominal["l_feed_mm"]))
        params: dict[str, Any] = {
            "a_mm": float(d["a_mm"]),
            "b_mm": float(d["b_mm"]),
            "s_mm": float(d["s_mm"]),
            "d_mm": float(d["d_mm"]),
            "l_ridge_mm": float(d["l_ridge_mm"]),
            "l_feed_mm": float(d["l_feed_mm"]),
            "er": float(d["er"]),
            "h_mm": float(d["h_mm"]),
        }
        assert set(params) == set(nominal)
        f0_meta = float(TEMPLATE_META["ridged_wg"]["f0_ghz"])
        return ModelSynthesisResult(
            model="ridged_wg",
            goal={"fc_target_ghz": float(fc_target_ghz)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "ridged_wg", params, f0_meta,
                _vi3_s11_objective(f0_meta)),
            notes=[
                f"脊深 d={d['d_mm']}mm（fc 目标 {fc_target_ghz}GHz 横磁共振"
                "方程单调降二分反解 design_ridge_depth 内核；XC-P 精度域守卫 "
                "g/b≥0.4 链内强制）——test_diplexer_ridged_templates 4 位舍入"
                "回代 |Δfc|/fc≤1e-4 钉",
                "双 RectWGPort 打在加宽馈段（a_feed=c/(2·0.75·fc) 结构性 "
                ">4a/3）；空气填充全金属（er=1.0/h=0.0 名义档）",
            ])

    register_template_spec(TemplateSpec(
        name="ridged_wg",
        meta=dict(TEMPLATE_META["ridged_wg"]),
        synthesizer=synthesize_ridged_wg_model,
        physics_roles={"s_mm": "line_width_mm",
                       "l_ridge_mm": "line_length_mm"},
        render_script=partial(render_script, "ridged_wg"),
        fake_model=None,
        hfss_plugin=None,
    ))


def _register_vi3_metasurface() -> None:
    """批② 辐射/超表面/材料 8 件：名义尺寸闭式（core/metasurface_lut 单源）+
    horn/vivaldi/ring 设计链全复算。"""
    from rfauto.adapters.openems_templates import (
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
        render_script,
        ring_resonator_design_params,
    )
    from rfauto.core.horn_synthesis import synthesize_pyramid_horn
    from rfauto.core.metasurface_lut import ms_cross_arm_len_mm, ms_jcross_slot_dims_mm, ms_patch_resonant_len_mm
    from rfauto.core.synthesis import ModelSynthesisResult
    from rfauto.core.vivaldi_tsa import vivaldi_tsa_design

    def _lam0_mm(f0_ghz: float) -> float:
        return 299792458.0 / (float(f0_ghz) * 1e9) * 1e3

    def _eps_eff_screen(er: float) -> float:
        return (1.0 + float(er)) / 2.0   # Luukkonen eq.3 单侧基板加载

    # ── ms_patch / ms_ring_patch：Hammerstad 不动点 + λ0/2 阵格 ──
    def _make_ms_patch_like(template: str):
        def synthesize(
            f0_ghz: float = 10.0, er: float = 3.66, h_mm: float = 1.524,
            **_: Any,
        ) -> ModelSynthesisResult:
            nominal = TEMPLATE_NOMINAL[template]
            px = round(ms_patch_resonant_len_mm(float(f0_ghz), float(er),
                                                float(h_mm)), 4)
            period = round(_lam0_mm(f0_ghz) / 2.0, 4)
            if template == "ms_patch":
                params: dict[str, Any] = {"px_mm": px, "py_mm": px,
                                          "period_mm": period,
                                          "h_mm": float(h_mm),
                                          "er": float(er),
                                          "tan_d": float(nominal["tan_d"])}
            else:  # ms_ring_patch：贴片边长=谐振变量，环几何=布局内单源
                params = {"patch_px_mm": px, "period_mm": period,
                          "h_mm": float(h_mm), "er": float(er),
                          "tan_d": float(nominal["tan_d"])}
            assert set(params) == set(nominal)
            return ModelSynthesisResult(
                model=template,
                goal={"f0_ghz": float(f0_ghz)},
                params=params,
                recipe_draft=_vi3_recipe_draft(
                    template, params, float(f0_ghz),
                    _vi3_s11_objective(float(f0_ghz), -10.0, 0.98)),
                notes=[
                    f"单元谐振边长={px}mm（λ0/(2√εeff(w)) Hammerstad 不动点"
                    f"，core/metasurface_lut 单源）×λ0/2 阵格={period}mm"
                    "（#252 闭式非手抄；er/h 走基板名义）",
                    "读出口径：双 E 探针对反射分解（ge5 修复后 LUT 扫描"
                    "战役面，meta extraction 注）",
                ])
        synthesize.__name__ = f"synthesize_{template}_model"
        return synthesize

    for template in ("ms_patch", "ms_ring_patch"):
        register_template_spec(TemplateSpec(
            name=template,
            meta=dict(TEMPLATE_META[template]),
            synthesizer=_make_ms_patch_like(template),
            physics_roles=({"px_mm": "resonator_length_mm",
                            "py_mm": "patch_width_mm"} if template == "ms_patch"
                           else {"patch_px_mm": "resonator_length_mm"}),
            render_script=partial(render_script, template),
            fake_model=None,
            hfss_plugin=None,
        ))

    # ── ms_cross / ms_jcross：屏族 εeff=(1+εr)/2 闭式 ──
    def synthesize_ms_cross_model(
        f0_ghz: float = 10.0, er: float = 3.66, **_: Any,
    ) -> ModelSynthesisResult:
        nominal = TEMPLATE_NOMINAL["ms_cross"]
        arm = round(ms_cross_arm_len_mm(float(f0_ghz), float(er)), 4)
        params: dict[str, Any] = {
            "arm_len_mm": arm,
            "arm_w_mm": round(arm / 5.0, 4),
            "period_mm": round(0.4 * _lam0_mm(f0_ghz), 4),
            "h_mm": float(nominal["h_mm"]),
            "er": float(er),
            "tan_d": float(nominal["tan_d"]),
        }
        assert set(params) == set(nominal)
        return ModelSynthesisResult(
            model="ms_cross",
            goal={"f0_ghz": float(f0_ghz)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "ms_cross", params, float(f0_ghz),
                _vi3_s11_objective(float(f0_ghz), -10.0, 0.98)),
            notes=[
                f"臂长（中心→尖端）={arm}mm（总跨 λ0/(2√εeff)、"
                f"εeff=(1+εr)/2 Luukkonen eq.3）×臂宽=臂长/5 ×周期 0.4λ0"
                "（无光栅瓣口径）——core/metasurface_lut 单源",
            ])

    register_template_spec(TemplateSpec(
        name="ms_cross",
        meta=dict(TEMPLATE_META["ms_cross"]),
        synthesizer=synthesize_ms_cross_model,
        physics_roles={"arm_len_mm": "resonator_length_mm",
                       "arm_w_mm": "line_width_mm"},
        render_script=partial(render_script, "ms_cross"),
        fake_model=None,
        hfss_plugin=None,
    ))

    def synthesize_ms_jcross_model(
        f0_ghz: float = 10.0, er: float = 3.66, **_: Any,
    ) -> ModelSynthesisResult:
        nominal = TEMPLATE_NOMINAL["ms_jcross"]
        jc = ms_jcross_slot_dims_mm(float(f0_ghz), float(er))
        params: dict[str, Any] = {
            "slot_len_mm": round(float(jc["slot_len_mm"]), 4),
            "slot_w_mm": round(float(jc["slot_len_mm"]) / 10.0, 4),
            "stub_len_mm": round(float(jc["stub_len_mm"]), 4),
            "period_mm": round(0.4 * _lam0_mm(f0_ghz), 4),
            "h_mm": float(nominal["h_mm"]),
            "er": float(er),
            "tan_d": float(nominal["tan_d"]),
        }
        assert set(params) == set(nominal)
        return ModelSynthesisResult(
            model="ms_jcross",
            goal={"f0_ghz": float(f0_ghz)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "ms_jcross", params, float(f0_ghz),
                _vi3_s11_objective(float(f0_ghz), -10.0, 0.98)),
            notes=[
                f"主缝=λg/4={params['slot_len_mm']}mm、端枝=λg/8="
                f"{params['stub_len_mm']}mm、缝宽=λg/40（Marcuvitz 网格 EC "
                "初值口径，带心真机修正归 P3——meta 注如实）×周期 0.4λ0",
            ])

    register_template_spec(TemplateSpec(
        name="ms_jcross",
        meta=dict(TEMPLATE_META["ms_jcross"]),
        synthesizer=synthesize_ms_jcross_model,
        physics_roles={"slot_len_mm": "resonator_length_mm",
                       "slot_w_mm": "gap_width_mm",
                       "stub_len_mm": "line_length_mm"},
        render_script=partial(render_script, "ms_jcross"),
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── ms_array_NxN：演示名义务（真机战役走参数注入）；period 闭式 ──
    def synthesize_ms_array_nxn_model(
        f0_ghz: float = 10.0, n_x: int = 3, n_y: int = 3, **_: Any,
    ) -> ModelSynthesisResult:
        nominal = TEMPLATE_NOMINAL["ms_array_NxN"]
        params: dict[str, Any] = {
            "n_x": int(n_x), "n_y": int(n_y),
            "period_mm": round(_lam0_mm(f0_ghz) / 2.0, 4),
            "cell_map": [list(row) for row in nominal["cell_map"]],
            "h_mm": float(nominal["h_mm"]),
            "er": float(nominal["er"]),
            "tan_d": float(nominal["tan_d"]),
        }
        assert set(params) == set(nominal)
        return ModelSynthesisResult(
            model="ms_array_NxN",
            goal={"f0_ghz": float(f0_ghz), "n_x": int(n_x), "n_y": int(n_y)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "ms_array_NxN", params, float(f0_ghz),
                _vi3_s11_objective(float(f0_ghz), -10.0, 0.98)),
            notes=[
                "有限 N×N 反射阵（ms_patch 单元平铺）；cell_map=名义三值 "
                "px 图样（逐单元驱动演示，真机 15×15 战役走参数注入）",
            ])

    register_template_spec(TemplateSpec(
        name="ms_array_NxN",
        meta=dict(TEMPLATE_META["ms_array_NxN"]),
        synthesizer=synthesize_ms_array_nxn_model,
        physics_roles={},  # 逐单元 cell_map 无单词表角色（#154 口径）
        render_script=partial(render_script, "ms_array_NxN"),
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── pyramid_horn：口径场综合（horn_synthesis 内核即时）──
    def synthesize_pyramid_horn_model(
        gain_db: float = 15.0, f_ghz: float = 10.0, wr_name: str = "WR-90",
        **_: Any,
    ) -> ModelSynthesisResult:
        nominal = TEMPLATE_NOMINAL["pyramid_horn"]
        r = synthesize_pyramid_horn(float(gain_db), float(f_ghz),
                                    str(wr_name))
        params: dict[str, Any] = {
            "a_mm": float(r["a_mm"]),
            "b_mm": float(r["b_mm"]),
            "a1_mm": float(r["a1_mm"]),
            "b1_mm": float(r["b1_mm"]),
            "l_feed_mm": float(nominal["l_feed_mm"]),
            "l_flare_mm": float(r["l_mm"]),
            "er": float(nominal["er"]),
            "h_mm": float(nominal["h_mm"]),
        }
        assert set(params) == set(nominal)
        return ModelSynthesisResult(
            model="pyramid_horn",
            goal={"gain_db": float(gain_db), "f_ghz": float(f_ghz),
                  "gain_db_achieved": round(float(r["gain_db_achieved"]), 4),
                  "eff_ap": round(float(r["eff_ap"]), 4)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "pyramid_horn", params, float(f_ghz),
                _vi3_s11_objective(float(f_ghz), -15.0)),
            notes=[
                f"{wr_name} 馈电、目标增益 {gain_db}dB：口径 a1×b1="
                f"{r['a1_mm']:.2f}×{r['b1_mm']:.2f}mm、张角段长 "
                f"{r['l_mm']:.2f}mm（口径场闭式综合 core/horn_synthesis，"
                "σ 补偿相位口径）；增益判读=闭式对照（meta extraction 注）",
                "l_feed=60mm 名义档（渲染实际管长=max(l_feed, "
                "l_flare+λ0/4+4mm)——口径侧空气余量自动保证 #174 族）",
            ])

    register_template_spec(TemplateSpec(
        name="pyramid_horn",
        meta=dict(TEMPLATE_META["pyramid_horn"]),
        synthesizer=synthesize_pyramid_horn_model,
        physics_roles={"l_flare_mm": "line_length_mm",
                       "l_feed_mm": "line_length_mm"},
        render_script=partial(render_script, "pyramid_horn"),
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── vivaldi_tsa：指数律+口面半波低截止（core/vivaldi_tsa 内核）──
    def synthesize_vivaldi_tsa_model(
        f_low_ghz: float = 6.0, w_throat_mm: float = 0.3,
        l_mm: float = 80.0, **_: Any,
    ) -> ModelSynthesisResult:
        nominal = TEMPLATE_NOMINAL["vivaldi_tsa"]
        d = vivaldi_tsa_design(float(f_low_ghz), float(w_throat_mm),
                               float(l_mm))
        params: dict[str, Any] = {
            "w_throat_mm": float(d["w_throat_mm"]),
            "w_mouth_mm": round(float(d["w_mouth_mm"]), 6),
            "l_mm": float(d["l_mm"]),
            "feed_w_mm": float(nominal["feed_w_mm"]),
            "er": float(nominal["er"]),
            "tan_d": float(nominal["tan_d"]),
        }
        assert set(params) == set(nominal)
        f0_meta = float(TEMPLATE_META["vivaldi_tsa"]["f0_ghz"])
        return ModelSynthesisResult(
            model="vivaldi_tsa",
            goal={"f_low_ghz": float(f_low_ghz),
                  "k_per_mm": round(float(d["k_per_mm"]), 9)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "vivaldi_tsa", params, f0_meta,
                _vi3_s11_objective(f0_meta, -10.0)),
            notes=[
                f"口面宽=c/(2·f_low)={d['w_mouth_mm']}mm（半波低截止准则，"
                f"回代 {d['f_low_ghz']}GHz 逐位）、指数律 k="
                f"{d['k_per_mm']:.9f}/mm（core/vivaldi_tsa 单源）",
                "50Ω 微带跨槽馈（slot 模板已证机理；巴伦=独立馈电件留"
                "登记注记，meta smoke_note 如实）",
            ])

    register_template_spec(TemplateSpec(
        name="vivaldi_tsa",
        meta=dict(TEMPLATE_META["vivaldi_tsa"]),
        synthesizer=synthesize_vivaldi_tsa_model,
        physics_roles={"w_throat_mm": "gap_width_mm",
                       "w_mouth_mm": "gap_width_mm",
                       "feed_w_mm": "line_width_mm",
                       "l_mm": "line_length_mm"},
        render_script=partial(render_script, "vivaldi_tsa"),
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── ring_resonator：基模 f1 → 环半径 HJ 链（design_params 单源）──
    # 50Ω 宽缺省走 XC-W 单源（synthesis.nominal_width_mm @2.5GHz round4）；
    # None 哨兵惰性求值避免 import 期读 materials.yaml（50Ω 宽字面量普查
    # 守卫 test_width_single_source 消费面）。
    def synthesize_ring_resonator_model(
        f1_ghz: float = 2.5,
        w_mm: float | None = None,
        gap_mm: float = 0.4,
        **_: Any,
    ) -> ModelSynthesisResult:
        if w_mm is None:
            w_mm = nominal_width_mm(50.0, float(f1_ghz),
                                    "rogers4350b_h0.508")
        d = ring_resonator_design_params(f1_ghz=float(f1_ghz),
                                         w_mm=float(w_mm),
                                         gap_mm=float(gap_mm))
        params: dict[str, Any] = {
            "r_mean_mm": float(d["r_mean_mm"]),
            "w_mm": float(d["w_mm"]),
            "gap_mm": float(d["gap_mm"]),
            "feed_w_mm": float(d["feed_w_mm"]),
        }
        assert set(params) == set(TEMPLATE_NOMINAL["ring_resonator"])
        return ModelSynthesisResult(
            model="ring_resonator",
            goal={"f1_ghz": float(f1_ghz)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "ring_resonator", params, float(f1_ghz),
                _vi3_s11_objective(float(f1_ghz))),
            notes=[
                f"r_mean={d['r_mean_mm']}mm（基模 n=1：闭环周长=λg，"
                "εeff 取直微带 HJ 值——曲率/色散修正 v1 不含，meta 注如实；"
                "ring_resonator_design_params 单源 rtol 1e-9 钉）",
                "材料提取 fixture 口径：对置 180° 馈点对各次模均为场腹",
            ])

    register_template_spec(TemplateSpec(
        name="ring_resonator",
        meta=dict(TEMPLATE_META["ring_resonator"]),
        synthesizer=synthesize_ring_resonator_model,
        physics_roles={"r_mean_mm": "resonator_length_mm",
                       "w_mm": "line_width_mm",
                       "gap_mm": "gap_width_mm",
                       "feed_w_mm": "line_width_mm"},
        render_script=partial(render_script, "ring_resonator"),
        fake_model=None,
        hfss_plugin=None,
    ))


def _register_vi3_filters() -> None:
    """批③ 滤波/功分/移相 5 件（TA-5/TA-4/TA-1/M-5/TA-14）：设计链全复算
    （diplexer/nway 即时、schiffman ~0.4s、varactor/xcheb ~0.3s）。"""
    from rfauto.adapters.openems_templates import (
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
        VARACTOR_BPF_NOMINAL,
        diplexer_design_params,
        nway_wilkinson_design_params,
        render_script,
        schiffman_design_params,
    )
    from rfauto.core.cross_coupled_map import cross_coupled_ring_quad_design
    from rfauto.core.synthesis import ModelSynthesisResult
    from rfauto.core.varactor import varactor_bpf_design

    # ── TA-5 diplexer：一阶 CR 对偶（内核 element_values 单源）──
    def synthesize_diplexer_model(
        f0_ghz: float = 2.5, z0_ohm: float = 50.0, **_: Any,
    ) -> ModelSynthesisResult:
        nominal = TEMPLATE_NOMINAL["diplexer"]
        d = diplexer_design_params(f0_ghz=float(f0_ghz), z0_ohm=float(z0_ohm))
        params: dict[str, Any] = {
            "w_feed_mm": float(d["w_feed_mm"]),
            "l_lpf_nh": float(d["l_lpf_nh"]),
            "c_hpf_pf": float(d["c_hpf_pf"]),
        }
        assert set(params) == set(nominal)
        return ModelSynthesisResult(
            model="diplexer",
            goal={"f0_ghz": float(f0_ghz), "z0_ohm": float(z0_ohm)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "diplexer", params, float(f0_ghz),
                _vi3_s11_objective(float(f0_ghz))),
            notes=[
                f"一阶常阻互补 CR 对：L=Z0/ωc={d['l_lpf_nh']}nH、"
                f"C=1/(ωc·Z0)={d['c_hpf_pf']}pF（diplexer_lpf_hpf 内核，"
                "S11≡0/互补≡1/交越=fc 三锚闭式精确）；w_feed=nominal_width_mm "
                "50Ω（diplexer_design_params 单源，test 钉）",
                "渲染 v1 只支持一阶 CR 对（≥2 阶对复合回损固有地板 ~−7dB "
                "判读门不可判读——meta 注如实）；集总元件值进 LumpedElement "
                "不进导体几何",
            ])

    register_template_spec(TemplateSpec(
        name="diplexer",
        meta=dict(TEMPLATE_META["diplexer"]),
        synthesizer=synthesize_diplexer_model,
        physics_roles={"w_feed_mm": "line_width_mm"},
        render_script=partial(render_script, "diplexer"),
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── TA-4 nway_wilkinson：tree 阻抗级 + HJ（nway_wilkinson_design_params）──
    def synthesize_nway_wilkinson_template_model(
        f0_ghz: float = 2.5, z0_ohm: float = 50.0, n_way: int = 4, **_: Any,
    ) -> ModelSynthesisResult:
        nominal = TEMPLATE_NOMINAL["nway_wilkinson"]
        d = nway_wilkinson_design_params(f0_ghz=float(f0_ghz),
                                         z0_ohm=float(z0_ohm),
                                         n_way=int(n_way))
        params: dict[str, Any] = {
            "w_arm_mm": float(d["w_arm_mm"]),
            "w_feed_mm": float(d["w_feed_mm"]),
            "arm_len_mm": float(d["arm_len_mm"]),
            "iso_r_ohm": float(d["iso_r_ohm"]),
        }
        assert set(params) == set(nominal)
        return ModelSynthesisResult(
            model="nway_wilkinson",
            goal={"f0_ghz": float(f0_ghz), "z0_ohm": float(z0_ohm),
                  "n_way": int(n_way)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "nway_wilkinson", params, float(f0_ghz),
                _vi3_s11_objective(float(f0_ghz))),
            notes=[
                "tree 拓扑（渲染取内核 tree 分支——star 单层 N≥3 不可布，"
                "meta 拓扑注）：臂 √2·Z0 HJ 反解 w_arm、λ/4 臂长 εeff 精算、"
                "隔离 R=2·Z0（synthesize_nway_wilkinson 内核单源，"
                "test_sicl_nway_templates 反解自洽钉）",
                "渲染守卫拒 n_way≠4（轮转管线规模；N=2 与 wilkinson 同解）",
            ])

    register_template_spec(TemplateSpec(
        name="nway_wilkinson",
        meta=dict(TEMPLATE_META["nway_wilkinson"]),
        synthesizer=synthesize_nway_wilkinson_template_model,
        physics_roles={"w_arm_mm": "impedance_line_width_mm",
                       "w_feed_mm": "line_width_mm",
                       "arm_len_mm": "resonator_length_mm"},
        render_script=partial(render_script, "nway_wilkinson"),
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── TA-1 schiffman：全通匹配 (Z0e,Z0o)=(Z0√ρ, Z0/√ρ) → KJ 反解 ──
    def synthesize_schiffman_template_model(
        f0_ghz: float = 2.5, z0_ohm: float = 50.0, rho: float = 2.0,
        delta_phase_deg: float = 90.0, **_: Any,
    ) -> ModelSynthesisResult:
        d = schiffman_design_params(f0_ghz=float(f0_ghz), rho=float(rho),
                                    z0_ohm=float(z0_ohm),
                                    delta_phase_deg=float(delta_phase_deg))
        params: dict[str, Any] = {
            "w_mm": float(d["w_mm"]),
            "gap_mm": float(d["gap_mm"]),
            "l_coupled_mm": float(d["l_coupled_mm"]),
            "l_ref_mm": float(d["l_ref_mm"]),
            "w_ref_mm": float(d["w_ref_mm"]),
        }
        assert set(params) == set(TEMPLATE_NOMINAL["schiffman"])
        return ModelSynthesisResult(
            model="schiffman",
            goal={"f0_ghz": float(f0_ghz), "rho": float(rho),
                  "delta_phase_deg": float(delta_phase_deg)},
            params=params,
            recipe_draft=_vi3_recipe_draft(
                "schiffman", params, float(f0_ghz),
                _vi3_s11_objective(float(f0_ghz))),
            notes=[
                f"ρ=Z0e/Z0o={rho} 全通匹配 Z0e·Z0o=Z0²（耦合段 KJ 反解 "
                f"w={d['w_mm']}/s={d['gap_mm']}mm）→ Δφ@f0=+{delta_phase_deg}° "
                "参考段一步反解（synthesize_schiffman 内核单源，"
                "test_schiffman_qwt_templates 反解自洽钉）",
                "双路径同板 DC 隔离净空 ≥3·h_sub 由渲染守卫强制（meta 注）",
            ])

    register_template_spec(TemplateSpec(
        name="schiffman",
        meta=dict(TEMPLATE_META["schiffman"]),
        synthesizer=synthesize_schiffman_template_model,
        physics_roles={"w_mm": "line_width_mm", "gap_mm": "gap_width_mm",
                       "l_coupled_mm": "resonator_length_mm",
                       "l_ref_mm": "line_length_mm",
                       "w_ref_mm": "line_width_mm"},
        render_script=partial(render_script, "schiffman"),
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── M-5 varactor_bpf：C(V) 主谐振方程 + loaded 廓线抽头（设计链单源）──
    def synthesize_varactor_bpf_model(
        f0_ghz: float = 2.5, f_unloaded_ghz: float = 2.8,
        cj0_pf: float = 1.0, phi_v: float = 0.9, order: int = 3,
        fbw: float = 0.05, rl_db: float = 20.0, **_: Any,
    ) -> ModelSynthesisResult:
        nominal = VARACTOR_BPF_NOMINAL
        d = varactor_bpf_design(f0_ghz=float(f0_ghz),
                                f_unloaded_ghz=float(f_unloaded_ghz),
                                cj0_pf=float(cj0_pf), phi_v=float(phi_v),
                                order=int(order), fbw=float(fbw),
                                rl_db=float(rl_db))
        params: dict[str, Any] = {
            "order": int(d["order"]),
            "w_mm": round(float(d["w_mm"]), 4),
            "arm_len_mm": round(float(d["arm_len_mm"]), 4),
            "arm_gap_mm": round(float(d["arm_gap_mm"]), 4),
            "gap_mm": round(float(d["gap_mm"]), 4),
            "tap_frac": round(float(d["tap_frac"]), 6),
            "cj0_pf": float(d["cj0_pf"]),
            "phi_v": float(d["phi_v"]),
            "bias_v": round(float(d["bias_v"]), 4),
        }
        assert set(params) == set(nominal)
        band = (float(f0_ghz) * (1.0 - float(fbw) * 0.475),
                float(f0_ghz) * (1.0 + float(fbw) * 0.475))
        recipe = _vi3_recipe_draft(
            "varactor_bpf", params, float(f0_ghz),
            [{"metric": "s11_db", "band": [band[0], band[1]],
              "op": "max_below", "value": -float(rl_db)}])
        return ModelSynthesisResult(
            model="varactor_bpf",
            goal={"f0_ghz": float(f0_ghz), "fbw": float(fbw),
                  "rl_db": float(rl_db), "order": int(order),
                  "f_unloaded_ghz": float(f_unloaded_ghz)},
            params=params,
            recipe_draft=recipe,
            notes=[
                f"臂长=λg/2({f_unloaded_ghz}GHz)（无载上沿，C 装载向下调谐）；"
                f"名义偏置 C={d['c_mid_pf']:.4f}pF → V={d['bias_v']:.4f}V；"
                "抽头 τ=loaded 廓线 branch B 自 C 端计（P0 修复口径，"
                "varactor_bpf_design 单源——fake/名义/渲染三方同源）",
                "耦合链纯 KJ（hairpin c(gap) 结构修正预声明不转移本族）；"
                "调谐窗 f(V=0)/f(V=10V) 见 design 返回（FDTD 三档静态 run）",
            ])

    register_template_spec(TemplateSpec(
        name="varactor_bpf",
        meta=dict(TEMPLATE_META["varactor_bpf"]),
        synthesizer=synthesize_varactor_bpf_model,
        physics_roles={"w_mm": "line_width_mm",
                       "arm_len_mm": "resonator_length_mm",
                       "gap_mm": "gap_width_mm",
                       "arm_gap_mm": "gap_width_mm",
                       "tap_frac": "feed_offset_mm"},
        render_script=partial(render_script, "varactor_bpf"),
        # fake 前向模型在 FakeAdapter.solve 的 varactor_bpf 分派支路内联
        # （M-5 注册）——无可提取独立函数面，spec 面如实 None。
        fake_model=None,
        hfss_plugin=None,
    ))

    # ── TA-14 xcheb_bpf4：交叉耦合折叠矩阵定点（TZ=[2.0] 名义）──
    def synthesize_xcheb_bpf4_model(
        f0_ghz: float = 2.5, fbw: float = 0.05, rl_db: float = 20.0,
        **_: Any,
    ) -> ModelSynthesisResult:
        nominal = TEMPLATE_NOMINAL["xcheb_bpf4"]
        d = cross_coupled_ring_quad_design(
            f0_ghz=float(f0_ghz), fbw=float(fbw), rl_db=float(rl_db),
            transmission_zeros=[2.0], er=float(nominal["er"]),
            h_mm=float(nominal["h_mm"]),
            g_open_mm=float(nominal["g_open_mm"]))
        params: dict[str, Any] = {
            "w_mm": round(float(d["w_mm"]), 4),
            "a_mm": round(float(d["a_mm"]), 4),
            "g12_mm": round(float(d["g12_mm"]), 4),
            "g23_mm": round(float(d["g23_mm"]), 4),
            "g34_mm": round(float(d["g34_mm"]), 4),
            "g14_mm": round(float(d["g14_mm"]), 4),
            "g_open_mm": float(nominal["g_open_mm"]),
            "g_pos_mm": round(float(d["g_pos_mm"]), 4),
            "tap_t_mm": round(float(d["tap_t_mm"]), 4),
            "h_mm": float(nominal["h_mm"]),
            "er": float(nominal["er"]),
            "tan_d": float(nominal["tan_d"]),
        }
        assert set(params) == set(nominal)
        band = (float(f0_ghz) * (1.0 - float(fbw) * 0.475),
                float(f0_ghz) * (1.0 + float(fbw) * 0.475))
        recipe = _vi3_recipe_draft(
            "xcheb_bpf4", params, float(f0_ghz),
            [{"metric": "s11_db", "band": [band[0], band[1]],
              "op": "max_below", "value": -float(rl_db)}])
        return ModelSynthesisResult(
            model="xcheb_bpf4",
            goal={"f0_ghz": float(f0_ghz), "fbw": float(fbw),
                  "rl_db": float(rl_db), "transmission_zeros": [2.0]},
            params=params,
            recipe_draft=recipe,
            notes=[
                "四个 λg/2 方形开路环 2×2：耦合矩阵 cm_core folded 映射"
                "（含非相邻 4-1 交叉耦合）定点收敛；Q_e 链 m_S1→Q_e→τ→"
                "tap_t=τ·周长−g_pos（cross_coupled_ring_quad_design 单源，"
                "test_ta_wave_c_templates 按链逐键钉）",
                "χ 一阶部分长耦合与环角/开缝结构效应未经 EM 校准（hairpin "
                "c(gap) 同族待标定项，#122 如实登记）",
            ])

    register_template_spec(TemplateSpec(
        name="xcheb_bpf4",
        meta=dict(TEMPLATE_META["xcheb_bpf4"]),
        synthesizer=synthesize_xcheb_bpf4_model,
        physics_roles={"w_mm": "line_width_mm",
                       "a_mm": "resonator_length_mm",
                       "g12_mm": "gap_width_mm",
                       "g23_mm": "gap_width_mm",
                       "g34_mm": "gap_width_mm",
                       "g14_mm": "gap_width_mm",
                       "g_open_mm": "gap_width_mm",
                       "g_pos_mm": "feed_offset_mm",
                       "tap_t_mm": "line_length_mm"},
        render_script=partial(render_script, "xcheb_bpf4"),
        fake_model=None,
        hfss_plugin=None,
    ))


_BOOTSTRAPPED = False


def _register_slotline_family() -> None:
    """槽线族四模板（2026-09-18 w1b，followUps ④/0df②/0dl①）：路线 A/B 均匀槽线
    段 + MSL↔slot 过渡 + Marchand 双槽臂。渲染/(fake/综合)数值零拷贝——渲染走
    openems_templates 文末 SLOTLINE_FAMILY 分发（整脚本渲染器），fake 走
    fake_adapter 同名分支，综合只组装 core 闭式产物（铁律 7/1c）。#154 角色
    映射只收语义确定键：w_mm=线宽/w_slot_mm=槽缝（gap_width_mm 词表）、
    line_len_mm=线长；x_port_mm/h_mm 无词表条目，各通道按名直读同义（msl_cpw
    先例）。hfss_plugin=None：槽线族 HFSS 仲裁走 scripts/hfss_slotline_*.py
    大截面波端口口径（refs §8/铁律），非桌面插件。"""
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
            notes=[f"短路臂 λg'/4={td.l_short_mm:.4f}mm、微带支节 λg_m/4−Δl="
                   f"{td.l_stub_mm:.4f}mm、50Ω 微带 w={td.w_msl_mm:.4f}mm"
                   "（Roberts/Knorr 闭式精算 core/slotline_transitions）",
                   "真机基线（a8abe8d）：HFSS IL 1.37dB 未达 1dB 门——结区优化 followUp"])

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
                "**单支节最小族已被两引擎互证证伪**（四门 FAIL）——"
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


def _register_coil_nfc() -> None:
    """§COIL_NFC NFC/WPC 线圈族（2026-09-26 df7 C10b，文末注册块）：
    单端口方螺旋线圈（13.56MHz NFC 频段，FR4 类基板、中跳线桥、外圈馈隙
    LumpedPort）。综合入口 = f0/C_tune → L_target → core/nfc_coil
    synthesize_coil 反解 d_out（确定性内核，4 位舍入与 COIL_NFC_NOMINAL
    再生口径一致），本处只组装零数值（#154 角色映射只收语义确定键：
    gap_mm=馈隙长/h_mm=板厚/er/tan_d 无词表条目按名直读同义）。
    hfss_plugin=None；真机 13.56MHz FDTD 预算见 runs/df7_nfc/criteria.md
    §e（本批零发射）。"""
    from rfauto.adapters.fake_adapter import _coil_nfc_sparams
    from rfauto.adapters.openems_templates import (
        COIL_NFC_NOMINAL,
        TEMPLATE_META,
        render_script,
    )
    from rfauto.core.nfc_coil import (
        resonant_frequency,
        spiral_inductance,
        synthesize_coil,
    )
    from rfauto.core.synthesis import ModelSynthesisResult

    def synthesize_coil_nfc_model(
        n_turns: int = 7, w_mm: float = 0.5, s_mm: float = 0.5,
        gap_mm: float = 0.4, h_mm: float = 1.6, er: float = 4.4,
        tan_d: float = 0.02, c_tune_pf: float = 47.0,
        f0_mhz: float = 13.56, **_: Any,
    ) -> ModelSynthesisResult:
        """coil_nfc spec 综合入口：f0/C_tune → L_target=1/((2πf)²C) →
        core synthesize_coil 二分反解 d_out（确定性内核），只组装零数值。"""
        l_target = 1.0 / ((2.0 * math.pi * f0_mhz * 1e6) ** 2
                          * (c_tune_pf * 1e-12))
        design = synthesize_coil(l_target, "square", float(n_turns),
                                 float(w_mm) * 1e-3, float(s_mm) * 1e-3)
        params: dict[str, Any] = {
            "n_turns": int(n_turns),
            "d_out_mm": round(float(design["d_out_m"]) * 1e3, 4),
            "w_mm": round(float(w_mm), 4),
            "s_mm": round(float(s_mm), 4),
            "gap_mm": round(float(gap_mm), 4),
            "h_mm": round(float(h_mm), 4),
            "er": round(float(er), 4),
            "tan_d": round(float(tan_d), 4),
        }
        assert set(params) == set(COIL_NFC_NOMINAL)
        from rfauto.core.nfc_coil import CoilGeometry

        l_nom = spiral_inductance(
            CoilGeometry("square", float(params["n_turns"]),
                         float(params["d_out_mm"]) * 1e-3,
                         float(params["w_mm"]) * 1e-3,
                         float(params["s_mm"]) * 1e-3), "current_sheet")
        f0_realized = resonant_frequency(l_nom, c_tune_pf * 1e-12)
        f0_ghz = f0_mhz / 1e3
        recipe_draft = {
            "model": "coil_nfc",
            "recipe_version": 1,
            "schema_version": 1,
            "params": {k: {"value": v} for k, v in params.items()},
            "setup": {"solver": "openEMS",
                      "freq_range_ghz": [f0_ghz * 0.9, f0_ghz * 1.1],
                      "points": 201},
            "objectives": [
                {"metric": "s11_db",
                 "band": [f0_ghz * 0.97, f0_ghz * 1.03],
                 "op": "max_below", "value": -10.0},
            ],
        }
        return ModelSynthesisResult(
            model="coil_nfc",
            goal={"f0_mhz": float(f0_mhz), "c_tune_pf": float(c_tune_pf),
                  "l_self_uh": round(l_nom * 1e6, 6),
                  "f0_realized_mhz": round(f0_realized / 1e6, 6)},
            params=params,
            recipe_draft=recipe_draft,
            notes=[
                f"L_target={l_target * 1e6:.4f}µH（f0={f0_mhz}MHz、"
                f"C_tune={c_tune_pf}pF 闭式）→ d_out={params['d_out_mm']}mm"
                "（core/nfc_coil.synthesize_coil 二分反解，回代相对差 "
                f"{design['rel_error']:.2e}）",
                "fake=一阶串联 RLC（未标定如实声明）；渲染=阶梯方螺旋+中跳"
                "线桥，跳线附加电感未建模（criteria §附如实注记）",
            ],
        )

    register_template_spec(TemplateSpec(
        name="coil_nfc",
        meta=dict(TEMPLATE_META["coil_nfc"]),
        synthesizer=synthesize_coil_nfc_model,
        physics_roles={
            "w_mm": "line_width_mm",
            "s_mm": "gap_width_mm",
        },
        render_script=partial(render_script, "coil_nfc"),
        fake_model=_coil_nfc_sparams,
        hfss_plugin=None,
    ))


def _register_mmwave_series_array() -> None:
    """§MMWAVE_SERIES_ARRAY 串馈毫米波阵（2026-09-26 df7 C10d，文末注册块）：
    汽车雷达 76-81GHz 行波串馈贴片阵（f0=78GHz、N=4、链末匹配集总负载到地）。
    综合入口 = f0/tilt_u0 → openems_templates.mmwave_series_design_params
    闭式链（Balanis 单元 + skrf HJ 线宽/βg + 倾斜式反解互联长 s，4 位舍入与
    MMWAVE_SERIES_NOMINAL 再生口径一致），本处只组装零数值（#154 角色映射
    只收语义确定键：h_mm=板厚/er/tan_d/n_elem/feed_margin_mm/load_r_ohm
    无词表条目按名直读同义）。hfss_plugin=None；真机预算预声明
    runs/df7_c10d/criteria.md §d（本批零发射）。"""
    from rfauto.adapters.fake_adapter import _mmwave_series_sparams
    from rfauto.adapters.openems_templates import (
        MMWAVE_SERIES_NOMINAL,
        TEMPLATE_META,
        _ant2_eps_eff,
        mmwave_series_design_params,
        render_script,
    )
    from rfauto.core.array_synthesis import series_feed_beam_direction_cosine
    from rfauto.core.synthesis import ModelSynthesisResult

    def synthesize_mmwave_series_array_model(
        f0_ghz: float = 78.0, tilt_u0: float = 0.30, n_elem: int = 4,
        er: float = 3.0, h_mm: float = 0.127, **_: Any,
    ) -> ModelSynthesisResult:
        """C10d spec 综合入口：mmwave_series_design_params 确定性内核
        （#1c 全闭式），只组装零数值。"""
        params = mmwave_series_design_params(
            f0_ghz=f0_ghz, tilt_u0=tilt_u0, n_elem=n_elem, er=er, h_mm=h_mm)
        assert set(params) == set(MMWAVE_SERIES_NOMINAL)
        lam0 = 299.792458 / f0_ghz
        k0 = 2.0 * math.pi / lam0
        pitch = params["elem_len_mm"] + params["link_len_mm"]
        beta_g = k0 * math.sqrt(_ant2_eps_eff(
            params["feed_w_mm"], f0_ghz, params["er"], params["h_mm"]))
        u0_real = series_feed_beam_direction_cosine(
            pitch, k0, params["link_len_mm"], beta_g)
        f0_ghz_val = f0_ghz
        recipe_draft = {
            "model": "mmwave_series_array",
            "recipe_version": 1,
            "schema_version": 1,
            "params": {k: {"value": v} for k, v in params.items()},
            "setup": {"solver": "openEMS",
                      "freq_range_ghz": [f0_ghz_val - 2.5, f0_ghz_val + 2.5],
                      "points": 401},
            "objectives": [
                {"metric": "s11_db",
                 "band": [f0_ghz_val - 0.75, f0_ghz_val + 0.75],
                 "op": "max_below", "value": -10.0},
            ],
        }
        return ModelSynthesisResult(
            model="mmwave_series_array",
            goal={"f0_ghz": float(f0_ghz), "tilt_u0": float(tilt_u0),
                  "u0_realized": round(u0_real, 6),
                  "beam_theta_deg": round(
                      math.degrees(math.asin(max(-1.0, min(1.0, u0_real)))), 4),
                  "pitch_over_lambda0": round(pitch / lam0, 6)},
            params=params,
            recipe_draft=recipe_draft,
            notes=[
                f"串馈行波阵：s={params['link_len_mm']}mm（倾斜设计式反解，"
                f"u0={tilt_u0}）、d/λ0={pitch / lam0:.4f}（栅瓣判据 ≤"
                f"{1.0 / (1.0 + tilt_u0):.4f}）；链末 50Ω 集总匹配到地",
                "fake=单元谐振精确逆吸收谷一阶（未标定如实声明，行波互耦/"
                "端接残余反射未建模）；渲染=整脚本渲染器（PML_8 端口轴+"
                "LumpedElement shunt 端接），真机预算 criteria §d 零发射",
            ],
        )

    register_template_spec(TemplateSpec(
        name="mmwave_series_array",
        meta=dict(TEMPLATE_META["mmwave_series_array"]),
        synthesizer=synthesize_mmwave_series_array_model,
        physics_roles={
            "elem_len_mm": "resonator_length_mm",
            "elem_w_mm": "patch_width_mm",
            "feed_w_mm": "line_width_mm",
            "link_len_mm": "line_length_mm",
        },
        render_script=partial(render_script, "mmwave_series_array"),
        fake_model=_mmwave_series_sparams,
        hfss_plugin=None,  # 纯 openEMS 辐射族（§18.3d C10d）
    ))


def bootstrap_template_specs() -> None:
    """把现有模板 spec 登记进全局注册表（幂等，入口处调用一次）。

    plan 元组 = 注册序单点：字符串步取 :data:`_SIMPLE_SPECS` 同构表行，
    可调用步为定制注册（本地综合闭包/族循环）。顺序与收缩前 bootstrap
    调用序逐位一致（TEMPLATE_SPECS._specs 插入序快照钉）。
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    simple = {row[0]: row for row in _SIMPLE_SPECS}
    plan: tuple[Any, ...] = (
        # 首批模板（WP1.x）×7 → 初始模板补注册 ×2
        "wilkinson", "branchline", "patch", "mline", "cpw", "dipole",
        "stripline",
        _register_stepped_impedance,
        _register_coupled_line,
        # C9 传输线族 II / Tier 2 过渡 / 基元族 / Tier 1 / 功分族 ×13
        "cps", "suspended_stripline", "msl_cpw", "sma_launcher", "wstep",
        "tjunc", "bend", "via", "atten_pi", "atten_t", "ratrace", "gysel",
        "hairpin",
        # 定制注册（原序逐位）
        _register_hairpin_alt,
        _register_coupled_bpf,
        _register_antenna2,
        _register_c3_filters,
        _register_patch_array,
        _register_eep_array,
        _register_cline_coupler,
        _register_branchline_2sect,
        _register_lange,
        _register_slotline_family,
        # SIW 族 ×2 → 文末注册块 ×2
        "siw", "msl_siw_taper",
        _register_coil_nfc,
        _register_mmwave_series_array,
        # §VI-3 W2-B spec 补齐 ×4（批①线/波导 9 + 批②辐射/超表面 8 +
        # 批③滤波/功分/移相 5 = 22 件；注册序=批内表序）
        _register_vi3_lines,
        _register_vi3_waveguide,
        _register_vi3_metasurface,
        _register_vi3_filters,
    )
    used = {s for s in plan if isinstance(s, str)}
    assert used == set(simple), (
        f"_SIMPLE_SPECS 与 plan 不同步：表多 {sorted(set(simple) - used)} "
        f"plan 多 {sorted(used - set(simple))}")
    for step in plan:
        if isinstance(step, str):
            _register_simple_spec(simple[step])
        else:
            step()
    _BOOTSTRAPPED = True


bootstrap_template_specs()
