"""env_reliability MCP 工具组（F-10 六服务 shell 接线 W3-D，Phase 3，2026-10-05）。

aging.py 单组先例（本组八工具一文件，env_reliability 域批形态）：零逻辑
转发 service（规则 4）；一切失败 ok=False 信封不抛出（不炸会话）；数值只
出确定性内核（铁律 7）。与 CLI `rfauto fault-tree report` / `datasheet
build` / `bench netlist-goldset` / `humidity uptake|msl` / `weave
styles|estimate` / `cryo surface` 同源同名 service 函数（JSON 进出）。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope, ok_envelope


@mcp.tool
def fault_tree_report(
    playbook_path: str = "",
    engine: str = "enumerate",
    out_format: str = "json",
) -> dict[str, Any]:
    """故障树报告（QM-FTA 复合工具）：playbook→OR-of-AND 树+孤儿审计+最小割集；out_format 为 mermaid 时附图文本。

    与 CLI ``rfauto fault-tree report`` 同源。engine 取 enumerate（缺省，
    纯确定性恒可用）或 z3（可选依赖 rfauto[z3]；未装 ok=False 如实报缺，
    不静默回退）；z3 路径附三重形式验证（有效性/最小性/完备性）。

    Args:
        playbook_path: playbook YAML 路径（缺省 knowledge/diagnostics/playbook.yaml）。
        engine: 最小割集引擎，enumerate 或 z3。
        out_format: json（缺省）或 mermaid（附 mermaid 文本节与行数）。

    Returns:
        dict: {ok, tree, audit, mcs, n_mcs, n_clauses, nonminimal, engine,
        z3_checked, z3_report?, mermaid?}；playbook 加载失败/树无有效规则/
        z3 未装 → ok=False 不抛出。
    """
    from rfauto.service.fault_tree_service import (
        build_fault_tree as _build,
    )
    from rfauto.service.fault_tree_service import (
        mermaid_fault_tree as _mermaid,
    )
    from rfauto.service.fault_tree_service import (
        minimal_cut_sets as _mcs,
    )
    try:
        built = _build(playbook_path or None)
        if not built.get("ok"):
            return built
        mcs = _mcs(tree=built.get("tree"), engine=engine)
        out: dict[str, Any] = {**built, **mcs}
        if out_format == "mermaid":
            mm = _mermaid(built["tree"])
            if not mm.get("ok"):
                return mm
            out["mermaid"] = mm.get("mermaid")
            out["n_mermaid_lines"] = mm.get("n_lines")
        return out
    except (KeyError, TypeError, ValueError) as e:
        return error_envelope(str(e))


@mcp.tool
def build_datasheet(
    run_dir: str = "",
    template: str = "",
    part_number: str = "",
    out_format: str = "md",
) -> dict[str, Any]:
    """器件规格书生成（EP-4 复合工具）：run 报告模型（PR-4）+模板名义 → rfauto-datasheet/v1 模型+md/HTML 渲染全文。

    免责声明恒在（工程规格书非厂商 datasheet，数值逐条 source）；run 缺省
    =纯名义面（curves 如实 missing 不伪造）；run 目录不存在 → ok=False
    （正常失败路径非 bug）。

    Args:
        run_dir: run 目录（PR-4 报告模型数据源；空=无实测节）。
        template: 模板注册名（docs/templates/<t>/meta.yaml 名义来源；空=无名义行）。
        part_number: 器件型号（缺省=template 名；两者全空则 ok=False）。
        out_format: md（缺省）或 html。

    Returns:
        dict: {ok, model, content, format, part_number, template}；
        构建/渲染异常 → ok=False errors。
    """
    from rfauto.service.datasheet_service import (
        build_datasheet as _build,
    )
    from rfauto.service.datasheet_service import (
        load_template_meta as _load_meta,
    )
    from rfauto.service.datasheet_service import (
        render_html as _render_html,
    )
    from rfauto.service.datasheet_service import (
        render_markdown as _render_md,
    )
    try:
        if out_format not in ("md", "html"):
            return error_envelope(
                f"out_format 须为 md 或 html，实际 {out_format!r}")
        report = None
        if run_dir:
            from rfauto.service.report_render import build_report_model

            report = build_report_model(run_dir)
        meta = _load_meta(template) if template else None
        model = _build(
            part_number=part_number or template,
            template=template,
            meta=meta,
            report=report,
        )
        content = _render_html(model) if out_format == "html" else _render_md(model)
        return ok_envelope(
            model=model,
            content=content,
            format=out_format,
            part_number=model["identification"]["part_number"],
            template=template,
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError) as e:
        return error_envelope(f"datasheet 构建失败: {e}")


@mcp.tool
def netlist_goldset_replay(
    goldset_path: str,
    engine: str = "qucsator",
    exe_path: str = "",
) -> dict[str, Any]:
    """网表 goldset 回放门（AI-6）：构造 qucsatorRF 真通道逐任务回放，对照 gold 值按容差打分出 PASS 率门。

    fail-closed：qucsator 可执行缺席/engine 未知 → ok=False 显式报缺（不
    静默不空跑）；通道异常任务判 ERROR 与 FAIL 分列。指标约定（v1）：
    n_freq/freq_min_hz/freq_max_hz/sXX_mag_min/max/sXX_db_min/max（模块
    service.netlist_sim_channels docstring 全表）；expected 外指标通道不
    产出即如实 FAIL。

    Args:
        goldset_path: 网表 goldset YAML（tasks[].netlist/analysis/expected，
            schema 见 service.netlist_goldset_service 模块 docstring）。
        engine: 模拟器通道（v1 仅 qucsator）。
        exe_path: qucsatorRF 可执行显式路径（缺省走 resolve_qucsator_exe
            四源回退：env→solvers.yaml→工作区→PATH）。

    Returns:
        dict: {ok, gate, n_cases, n_pass, n_fail, n_error, pass_rate,
        min_pass_rate, results, reasons}；通道构造失败 → ok=False gate=FAIL。
    """
    from rfauto.service.netlist_goldset_service import (
        replay_netlist_goldset as _fn,
    )
    from rfauto.service.netlist_sim_channels import build_simulator_channel

    try:
        channel = build_simulator_channel(engine, exe_path or None)
    except (FileNotFoundError, ValueError) as exc:
        return error_envelope(
            f"模拟器通道构造失败（fail-closed，不静默）: {exc}",
            gate="FAIL", engine=engine, n_cases=0)
    try:
        return _fn(goldset_path=goldset_path, simulator=channel)
    except (KeyError, TypeError, ValueError) as e:
        return error_envelope(str(e), gate="FAIL")


@mcp.tool
def humidity_uptake(payload: dict[str, Any]) -> dict[str, Any]:
    """湿度吸湿估计（env_rel 域）：时长/扩散系数/板厚 → Fick 级数+√t 律。

    F-H.2 双路径（可选 εr(M) 混合节）。诚实边界：D/M∞/er_water 由调用方
    按数据表给值（服务不内嵌材料常数，awaiting_data 政策）；数值只在
    确定性内核 core.humidity_drift（铁律 7）；不用于 MSL 寿命查询（走
    msl_floor_life_query）。非法入参/内核异常 → ok=False errors（不抛出）。
    只读无时序约束。

    Args:
        payload: JSON 进出 payload：t_s 或 t_h（二选一）、diffusivity_m2_s
            （必填）、thickness_m 或 thickness_mm（二选一）、m_inf_frac?、
            t_over_tau_max?、epsilon?（moisture_frac/er_dry/rho_dry/
            er_water/rule?/rho_water?）。

    Returns:
        dict: {ok, schema_version, uptake, epsilon?, provenance,
        disclaimer}；非法入参/内核异常 → ok=False errors（不抛出）。
    """
    from rfauto.service.humidity_drift_service import (
        moisture_uptake_estimate as _fn,
    )
    try:
        return _fn(payload)
    except (KeyError, TypeError, ValueError) as e:
        return error_envelope(str(e))


@mcp.tool
def msl_floor_life_query(payload: dict[str, Any]) -> dict[str, Any]:
    """MSL 车间寿命查询（env_rel 域）：msl 等级 → J-STD-033 floor life（h）。

    F-H.2 表 verbatim 面（不插值不外推），不用于湿度吸湿估计（走
    humidity_uptake）。msl 非法 → ok=False errors 如实。只读无时序约束。

    Args:
        payload: JSON 进出 payload：msl（必填，"1".."6"/"2a"/"5a"）、
            exposure_h?（给出则判 expired）。

    Returns:
        dict: {ok, schema_version, msl, floor_life_h（None=无限，JSON 语义）,
        unlimited, exposure_h?, expired?}；非法入参 → ok=False errors。
    """
    from rfauto.service.humidity_drift_service import (
        msl_floor_life_query as _fn,
    )
    try:
        return _fn(payload)
    except (KeyError, TypeError, ValueError) as e:
        return error_envelope(str(e))


@mcp.tool
def weave_style_info(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """编织样式表查询（env_rel 域）：样式键 → 织构参数+MIT 出处（只读面）。

    HS-1。零数值面（参数表只读，不产物理数字），不用于 skew 估计（走
    weave_skew_estimate）。未知样式 → ok=False errors 如实。只读无时序
    约束。

    Args:
        payload: 可省（全表）；或 {style: "1067"/"1080"/"2116"/"7628"}
            查单样式。未知样式 → ok=False errors。

    Returns:
        dict: {ok, schema_version, provenance, styles}；零数值面（参数表
        只读，不产物理数字）。
    """
    from rfauto.service.glass_weave_skew_service import (
        weave_style_info as _fn,
    )
    try:
        return _fn(payload)
    except (KeyError, TypeError, ValueError) as e:
        return error_envelope(str(e))


@mcp.tool
def weave_skew_estimate(payload: dict[str, Any]) -> dict[str, Any]:
    """编织 skew 估计（env_rel 域）：样式/方向/走线长/树脂 εr → skew+UI 判定。

    HS-1 端到端闭式统计估计面（不含损耗/色散/线耦合），不用于样式表查询
    （走 weave_style_info）；er_resin 必填无缺省（诚实边界）。参数缺失/
    非法 → ok=False errors 不产数字。只读无时序约束。

    Args:
        payload: JSON 进出 payload：style（必填）、direction?（x/y）、
            length_m 或 length_mm（二选一）、er_resin（必填）、
            trace_width_mm?、theta_deg?、phase_error_frac?、coverage_delta?、
            data_rate_gbps?、ns_levels?、budget_frac?。

    Returns:
        dict: {ok, schema_version, style, provenance, geometry, er_bounds,
        skew_worst, skew_expected?, zigzag_residual?, ui_verdict?,
        disclaimer}；参数缺失/非法 → ok=False errors（不产数字）。
    """
    from rfauto.service.glass_weave_skew_service import (
        weave_skew_estimate as _fn,
    )
    try:
        return _fn(payload)
    except (KeyError, TypeError, ValueError) as e:
        return error_envelope(str(e))


@mcp.tool
def cryo_surface_estimate(payload: dict[str, Any]) -> dict[str, Any]:
    """低温材料面估计（env_rel 域）：温度/RRR/频率 → 铜面 ρ/Rs/δ/l/f_c 全量。

    F-H.4（可选超导节与 Q 分解节）。诚实边界：线性声子项深低温高估
    （Bloch-Grüneisen 未建模）；Chambers 反常区 Rs 幅值与 Nb Mattis-Bardeen
    Rs(T) 未实现（超导 R_s 由调用方外供）；介电表为单源典型带（如实标注），
    不用于计量级低温基准。非法入参/内核异常 → ok=False errors（不抛出）。
    只读无时序约束。

    Args:
        payload: JSON 进出 payload：t_k/rrr/f_hz（必填）、superconductor?
            （lambda_l0_m/tc_k/film_thickness_m 必填组+f0_at_zero_k_hz?/
            kappa_kinetic? 成对）、q_section?（tan_delta_eff 必填+
            rs_ohm_per_sq/geometry_factor_ohm 成对可选）。

    Returns:
        dict: {ok, schema_version, copper, superconductor?, q?, constants,
        provenance, disclaimer}；非法入参/内核异常 → ok=False errors。
    """
    from rfauto.service.cryo_materials_service import (
        cryo_surface_estimate as _fn,
    )
    try:
        return _fn(payload)
    except (KeyError, TypeError, ValueError) as e:
        return error_envelope(str(e))
