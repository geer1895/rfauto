"""fab 剖面 / DFM 门服务层（DP-7 P1/P3，JSON 进出）。

职责（分层铁律：服务层 JSON 进出，CLI/MCP 薄壳）：
- ``load_fab_profile``：knowledge/fab_profiles/*.yaml → JSON 视图；
- ``check_template_dfm``：模板名义几何（``template_meta()`` 只读）+ 用户
  覆盖 → 对剖面校验（几何事实提取见 ``FAB_GEOMETRY_FACTS``——显式登记
  优先，未登记模板走保守后缀扫描；#154 教训：同名参数跨模板语义可能
  相反，slot/slotline 族参数一律不按线宽分类）；
- ``check_design_dfm`` / ``check_design_dfm_best_effort``：KiCad
  PCBDesign-dict 面（adapters/kicad_pcell.py::generate_pcb 导出前接线，
  best-effort #105 不阻塞导出）；
- ``fab_profile_yield``：公差扰动良率估计（DP-7 C4 端到端被测面；缺省
  路径=单参数均匀乘性 U(1±tol)，``tolerance_source`` 引用分支=单源
  {param: σ} 正态多参数 MC，见 DP-7 P2）；
- **P2 公差来源单源（一处定义，uq/yield 链经它取 σ，不再手抄）**：
  ``load_material_epsilon_r_tolerance``（εr 容差=configs/materials.yaml
  声明）、``derive_tolerances_from_fab_profile``（trace=名义×
  trace_tol_pct/100、板厚=剖面字段、εr=materials.yaml）、
  ``resolve_tolerance_source``（tolerance_source 引用形态→σ dict）、
  ``design_for_yield``（DFM 门+良率 MC+逐规范 Cpk 一条 JSON 面）。

本模块不改 core/calculators.py / openems_templates.py（禁改面）；uq 链
挂点=``uq_service.surrogate_yield/_at`` 的 ``tolerance_source`` kwarg
（函数内惰性 import 本模块，无模块级环）。对照实现语义见
tests/unit/test_fab_service.py 与 tests/unit/test_dp7p2_tolerance_source.py
的独立手工 MC。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.fab_check import (
    FabProfileError,
    check_geometry,
    load_profile,
)

__all__ = [
    "FAB_GEOMETRY_FACTS",
    "check_design_dfm",
    "check_design_dfm_best_effort",
    "check_template_dfm",
    "derive_tolerances_from_fab_profile",
    "design_for_yield",
    "fab_profile_yield",
    "load_fab_profile",
    "load_material_epsilon_r_tolerance",
    "resolve_tolerance_source",
]

# 模板 → 几何事实参数名（trace=线宽/gap=缝宽，mm）。显式登记优先；
# 未登记模板走 _scan_geometry_params 后缀扫描（保守：含 "slot" 的参数
# 一律不按线宽分类——槽宽是地平面开缝，语义与导带线宽相反，#154）。
FAB_GEOMETRY_FACTS: dict[str, dict[str, tuple[str, ...]]] = {
    "mline": {"traces": ("w_mm",), "gaps": ()},
    "cpw": {"traces": ("w_mm",), "gaps": ("gap_mm",)},
    "stripline": {"traces": ("w_mm",), "gaps": ()},
    "suspended_stripline": {"traces": ("w_mm",), "gaps": ()},
    "cps": {"traces": ("w_mm",), "gaps": ("gap_mm",)},
    "wilkinson": {"traces": ("series_w_mm", "shunt_w_mm"), "gaps": ()},
    "branchline": {"traces": ("series_w_mm", "shunt_w_mm"), "gaps": ()},
    "coupled_line": {"traces": ("line_w_mm",), "gaps": ("gap_mm",)},
    "dipole": {"traces": ("dipole_w_mm",), "gaps": ("gap_mm",)},
    "stepped_impedance": {
        "traces": ("z1_width_mm", "z2_width_mm"), "gaps": ()},
}

_TRACE_SUFFIXES = ("w_mm", "_w_mm", "_width_mm")
_GAP_SUFFIXES = ("gap_mm", "_gap_mm")


def _scan_geometry_params(params: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """未登记模板的保守后缀扫描（slot* 排除，#154）。"""
    traces: list[str] = []
    gaps: list[str] = []
    for name in params:
        low = str(name).lower()
        if "slot" in low:
            continue
        if low == "w_mm" or low.endswith(_TRACE_SUFFIXES):
            traces.append(name)
        elif low.endswith(_GAP_SUFFIXES):
            gaps.append(name)
    return {"traces": tuple(sorted(traces)), "gaps": tuple(sorted(gaps))}


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def load_fab_profile(
    name: str = "jlcpcb", *, profiles_dir: str | None = None
) -> dict[str, Any]:
    """fab 剖面 → JSON 视图（含逐字段来源注记 raw）。"""
    try:
        prof = load_profile(name, profiles_dir=profiles_dir)
    except FabProfileError as exc:
        return {"ok": False, "errors": [str(exc)]}
    return {
        "ok": True,
        "name": prof.name,
        "profile_version": prof.profile_version,
        "source_url": prof.source_url,
        "retrieved_date": prof.retrieved_date,
        "trace_tol_pct": prof.trace_tol_pct,
        "impedance_tol_pct": prof.impedance_tol_pct,
        "copper_rules": {
            f"{oz:g}": {"min_trace_mm": r.min_trace_mm,
                        "min_gap_mm": r.min_gap_mm}
            for oz, r in sorted(prof.copper_rules.items())
        },
        "board_thickness_mm": [prof.board_thickness_min_mm,
                               prof.board_thickness_max_mm],
        "min_drill_mm": prof.min_drill_mm,
        "min_via_annular_ring_mm": prof.min_via_annular_ring_mm,
        "min_solder_mask_dam_mm": prof.min_solder_mask_dam_mm,
        "surface_finishes": list(prof.surface_finishes),
        "supported_materials": list(prof.supported_materials),
        "path": prof.path,
    }


def check_template_dfm(
    template: str,
    params: dict[str, float] | None = None,
    *,
    profile: str = "jlcpcb",
    material: str = "rogers4350b_h0.508",
    copper_oz: float = 1.0,
    surface_finish: str | None = None,
    board_thickness_mm: float | None = None,
) -> dict[str, Any]:
    """模板渲染几何 DFM 门（名义几何 + 用户覆盖，JSON 契约）。

    几何事实源只读：``adapters.openems_templates.template_meta`` 的
    nominal_params（openems_templates.py 本批禁改，此处不回写）。
    """
    from rfauto.adapters.openems_templates import template_meta

    try:
        meta = template_meta(template)
    except KeyError:
        return {"ok": False, "errors": [f"未知模板: {template}"]}
    merged: dict[str, Any] = {**meta.get("nominal_params", {}),
                              **(params or {})}
    facts = FAB_GEOMETRY_FACTS.get(template) or _scan_geometry_params(merged)
    traces = [v for k in facts["traces"]
              if (v := _numeric(merged.get(k))) is not None]
    gaps = [v for k in facts["gaps"]
            if (v := _numeric(merged.get(k))) is not None]
    try:
        prof = load_profile(profile)
    except FabProfileError as exc:
        return {"ok": False, "errors": [str(exc)]}
    report = check_geometry(
        prof,
        traces_mm=traces,
        gaps_mm=gaps,
        copper_oz=copper_oz,
        material=material,
        surface_finish=surface_finish,
        board_thickness_mm=board_thickness_mm,
    )
    out = report.to_dict()
    out["ran"] = True
    out["template"] = template
    out["params_source"] = "TEMPLATE_NOMINAL+user_overrides"
    out["facts"] = {"traces": list(facts["traces"]),
                    "gaps": list(facts["gaps"])}
    if template not in FAB_GEOMETRY_FACTS:
        out["facts"]["scan_note"] = (
            "模板未登记 FAB_GEOMETRY_FACTS，走保守后缀扫描（slot* 排除，#154）")
    return out


def check_design_dfm(
    design: dict[str, Any],
    *,
    profile: str = "jlcpcb",
) -> dict[str, Any]:
    """KiCad PCBDesign-dict 面 DFM 门（JSON 契约，不抛异常面见 best_effort）。

    入参形状 = ``PCBDesign.to_dict()``（traces[].width、vias[].drill/pad，
    mm）+ 可选 copper_oz/material/board_thickness_mm/surface_finish。
    """
    try:
        prof = load_profile(profile)
    except FabProfileError as exc:
        return {"ok": False, "errors": [str(exc)]}
    report = check_geometry(
        prof,
        traces_mm=[float(t["width"]) for t in design.get("traces") or []
                   if t.get("width") is not None],
        drills_mm=[float(v["drill"]) for v in design.get("vias") or []
                   if v.get("drill") is not None],
        pad_diams_mm=[float(v["pad"]) for v in design.get("vias") or []
                      if v.get("pad") is not None] or None,
        copper_oz=float(design.get("copper_oz") or 1.0),
        material=design.get("material"),
        board_thickness_mm=design.get("board_thickness_mm"),
        surface_finish=design.get("surface_finish"),
    )
    out = report.to_dict()
    out["ran"] = True
    return out


def check_design_dfm_best_effort(
    design: dict[str, Any], *, profile: str = "jlcpcb"
) -> dict[str, Any]:
    """best-effort 包装（#105）：任何异常 → ``{"ran": False, ...}`` 留痕。"""
    from rfauto.core.fab_check import best_effort_dfm_for_design

    return best_effort_dfm_for_design(design, profile_name=profile)


def _violates(value: float, op: str, spec: float) -> bool:
    """规格判据（镜像 uq_service._violate_mask 口径，只收字符串 op）。"""
    if op == "max_below":
        return value > spec
    if op == "min_above":
        return value < spec
    raise ValueError(f"未知规格 op: {op}（支持 max_below/min_above）")


def fab_profile_yield(
    model: Any,
    nominal: dict[str, float],
    *,
    perturb_param: str | None = None,
    spec: dict[str, Any],
    profile: str = "jlcpcb",
    n: int = 10_000,
    seed: int = 42,
    tol_pct: float | None = None,
    tolerance_source: Any = None,
) -> dict[str, Any]:
    """公差扰动 → 代理蒙特卡洛良率（DP-7 C4 端到端被测面）。

    **缺省路径（不传 tolerance_source，行为零变化）**：扰动分布（DP-7
    规格原文）``扰动值 = 名义 × U(1±tol)``（均匀乘性，tol=剖面
    trace.tolerance_pct，单源；``tol_pct`` 显式传入仅用于测试合成对照）。
    规格 ``spec={"metric","op","value"}``，op∈{max_below, min_above}
    （与 uq_service SpecEvaluator 口径一致）。

    **P2 tolerance_source 引用分支（DP-7 输入规范化）**：传
    ``tolerance_source``（dict/str/Path，形态见
    :func:`resolve_tolerance_source`）→ 单源展开 {param: σ} → 正态加性
    多参数 MC（``uq_service._mc_yield`` 内核），输出带
    ``tolerance_provenance``（逐参数 source）与 ``cpk_per_spec``；
    distribution 标 ``normal_additive_single_source``（与缺省均匀乘性
    两条口径并存，各自标注不混同）。此时 ``perturb_param`` 不需要。

    P2 之前本段为「接口预留」注记：tolerance_source 键自始即本函数
    单源定义点，P2 批已落地（本 docstring 原文见
    runs/df6_dp7fab/criteria.md P2 延后注记）。
    """
    import numpy as np

    if tolerance_source is not None:
        return _fab_yield_from_tolerance_source(
            model, nominal, spec=spec, tolerance_source=tolerance_source,
            n=n, seed=seed)
    if perturb_param is None:
        return {"ok": False,
                "errors": ["perturb_param 必填（或传 tolerance_source 引用）"]}
    if n < 1:
        return {"ok": False, "errors": [f"n 必须 ≥1，收到: {n}"]}
    if perturb_param not in nominal:
        return {"ok": False, "errors": [f"扰动参数 {perturb_param} 不在名义点"]}
    metric = str(spec.get("metric", ""))
    op = str(spec.get("op", ""))
    spec_value = float(spec.get("value", 0.0))
    if not metric or op not in ("max_below", "min_above"):
        return {"ok": False,
                "errors": ["spec 非法: metric/op 必填，op∈(max_below, min_above)"]}
    try:
        prof = load_profile(profile)
    except FabProfileError as exc:
        return {"ok": False, "errors": [str(exc)]}
    tol = prof.trace_tol_pct if tol_pct is None else float(tol_pct)

    rng = np.random.default_rng(seed)
    base = float(nominal[perturb_param])
    draws = base * rng.uniform(1.0 - tol / 100.0, 1.0 + tol / 100.0, int(n))
    passes = 0
    values = np.empty(int(n))
    for i, w in enumerate(draws):
        pt = dict(nominal)
        pt[perturb_param] = float(w)
        pred = model.predict(pt)
        if metric not in pred:
            return {"ok": False,
                    "errors": [f"代理预测缺指标 {metric}: keys={sorted(pred)}"]}
        v = float(pred[metric])
        values[i] = v
        if not _violates(v, op, spec_value):
            passes += 1
    return {
        "ok": True,
        "yield_rate": passes / float(n),
        "n_draws": int(n),
        "seed": int(seed),
        "distribution": "uniform_multiplicative",
        "perturb_param": perturb_param,
        "nominal_params": {k: float(v) for k, v in nominal.items()},
        "tolerance": {"param": perturb_param, "pct": tol},
        "tolerance_source": f"fab_profile:{prof.name}:trace.tolerance_pct"
                            if tol_pct is None else "explicit_override",
        "profile": prof.name,
        "profile_version": prof.profile_version,
        "spec": {"metric": metric, "op": op, "value": spec_value},
        "metric_stats": {
            "mean": float(values.mean()), "std": float(values.std()),
            "q05": float(np.quantile(values, 0.05)),
            "q95": float(np.quantile(values, 0.95)),
        },
    }


# ─── DP-7 P2：公差来源单源（fab 剖面 + materials.yaml → {param: σ}）─────────
# 判据预声明 runs/df6_dp7p2/criteria.md。一处定义：uq/yield 链的 σ 一律
# 经 resolve_tolerance_source/derive_tolerances_from_fab_profile 派生，
# 不再手抄。σ 口径 = 半宽/k_sigma（k_sigma 缺省 3.0，"3σ=公差"惯例，
# 与 robustness_service.load_tolerance_profile / tolerance.py 同源）。

#: 板厚参数识别（小写）：以 h_mm 结尾（h_mm/sub_h_mm/patch_h_mm…）或
#: 名含 thickness。trace/gap 分类优先（FAB_GEOMETRY_FACTS/后缀扫描，
#: slot* 排除沿用 #154）。
_THICKNESS_SUFFIX = "h_mm"
_THICKNESS_HINT = "thickness"
#: εr 参数识别：精确名（er/eps_r/epsilon_r）、er_<后缀> 或 er<数字> 变体
#: （er1/er2 多层介质的既有命名惯例）。
_ER_EXACT_NAMES = ("er", "eps_r", "epsilon_r")


def _materials_path() -> Path:
    """configs/materials.yaml（与 core/synthesis.py 同根推导，×3 到根）。"""
    return Path(__file__).resolve().parents[3] / "configs" / "materials.yaml"


def load_material_epsilon_r_tolerance(
    material_key: str,
    *,
    materials_path: str | Path | None = None,
) -> dict[str, Any]:
    """materials.yaml → εr 制造容差声明（DP-7 P2 单源，JSON 契约）。

    声明形态（材料条目内，二选一）：``epsilon_r_tol_abs``（绝对半宽，
    εr 同单位，Rogers datasheet 口径）或 ``epsilon_r_tol_pct``（相对
    百分数 ×epsilon_r/100 折半宽）。返回
    {ok, declared, material, epsilon_r?, tol?, declared_by?, source,
    source_note?, materials_path}；未声明（declared=False + source=
    "not_declared"）**不是错误**——如实留痕不虚构（fr4 无单一权威容差值）。
    """
    path = Path(materials_path) if materials_path else _materials_path()
    if not path.exists():
        return {"ok": False, "errors": [f"materials.yaml 不存在: {path}"]}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "errors": [f"materials.yaml 解析失败: {exc}"]}
    mats = (data or {}).get("materials") or {}
    mat = mats.get(str(material_key))
    if not isinstance(mat, dict):
        return {"ok": False, "errors": [
            f"materials.yaml 无材料条目: {material_key}"
            f"（可用: {sorted(mats)}）"]}
    out: dict[str, Any] = {
        "ok": True, "declared": False, "material": str(material_key),
        "materials_path": str(path), "source": "not_declared",
    }
    if mat.get("epsilon_r") is not None:
        try:
            out["epsilon_r"] = float(mat["epsilon_r"])
        except (TypeError, ValueError):
            return {"ok": False, "errors": [
                f"{material_key}.epsilon_r 数值非法: "
                f"{mat.get('epsilon_r')!r}"]}
    tol_abs = mat.get("epsilon_r_tol_abs")
    tol_pct = mat.get("epsilon_r_tol_pct")
    if tol_abs is None and tol_pct is None:
        return out
    declared_by = ("epsilon_r_tol_abs" if tol_abs is not None
                   else "epsilon_r_tol_pct")
    try:
        if tol_abs is not None:
            tol = float(tol_abs)
            if not tol > 0.0:
                raise ValueError(f"必须 >0，收到 {tol_abs!r}")
        else:
            pct = float(tol_pct)
            if not pct > 0.0:
                raise ValueError(f"必须 >0，收到 {tol_pct!r}")
            if "epsilon_r" not in out:
                raise ValueError("epsilon_r_tol_pct 需要条目含 epsilon_r 数值")
            tol = out["epsilon_r"] * pct / 100.0
    except (TypeError, ValueError) as exc:
        return {"ok": False,
                "errors": [f"{material_key}.{declared_by}: {exc}"]}
    out.update({
        "declared": True, "tol": tol, "declared_by": declared_by,
        "source": f"configs/materials.yaml:{material_key}:{declared_by}",
        "source_note": str(mat.get("epsilon_r_tol_source") or ""),
    })
    return out


def _classify_tolerance_params(
    nominal: dict[str, Any],
    facts: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, list[str]]:
    """名义参数 → 公差类别（trace/gap/thickness/epsilon_r/other，确定性）。"""
    if facts is None:
        facts = _scan_geometry_params(dict(nominal))
    trace_set = set(facts.get("traces") or ())
    gap_set = set(facts.get("gaps") or ())
    classes: dict[str, list[str]] = {"traces": [], "gaps": [],
                                     "thickness": [], "epsilon_r": [],
                                     "other": []}
    for name in sorted(nominal):
        low = str(name).lower()
        if name in trace_set:
            classes["traces"].append(name)
        elif name in gap_set:
            classes["gaps"].append(name)
        elif low.endswith(_THICKNESS_SUFFIX) or _THICKNESS_HINT in low:
            classes["thickness"].append(name)
        elif (low in _ER_EXACT_NAMES or low.startswith("er_")
                or (low.startswith("er") and low[2:].isdigit())):
            classes["epsilon_r"].append(name)
        else:
            classes["other"].append(name)
    return classes


def derive_tolerances_from_fab_profile(
    nominal: dict[str, Any],
    *,
    profile: str = "jlcpcb",
    material: str | None = None,
    k_sigma: float = 3.0,
    facts: dict[str, tuple[str, ...]] | None = None,
    materials_path: str | Path | None = None,
) -> dict[str, Any]:
    """公差单源派生：fab 剖面 + materials.yaml → {param: σ}（一处定义）。

    派生公式（σ = 半宽/k_sigma，预声明 runs/df6_dp7p2/criteria.md C1）：
    - trace 参数：``tol = 名义 × trace.tolerance_pct/100``；
    - 板厚参数：名义 ≥1.0mm → ``tol = 名义 ×
      board_thickness.tolerance_pct_ge_1mm/100``；<1.0mm → ``tol =
      board_thickness.tolerance_abs_mm_lt_1mm``（剖面字段直取）；
    - εr 参数：materials.yaml 声明（epsilon_r_tol_abs/pct；未声明 →
      不派生 σ，provenance declared=False 如实留痕）。
    gap 参数不派生（剖面无 gap 公差声明，DFM 门按规格原文无折扣）。

    分布语义（诚实口径）：本函数只产 σ（uq 链 normal(0,σ) 抽样用）；
    与 fab_profile_yield 缺省路径的均匀乘性 U(1±tol) 是两条口径，
    provenance 以 dist 字段标注，不混同。
    """
    if not k_sigma > 0:
        return {"ok": False, "errors": [f"k_sigma 必须 >0，收到 {k_sigma!r}"]}
    try:
        prof = load_profile(profile)
    except FabProfileError as exc:
        return {"ok": False, "errors": [str(exc)]}
    nominal_f = {k: float(v) for k, v in nominal.items()
                 if isinstance(v, (int, float)) and not isinstance(v, bool)}
    classes = _classify_tolerance_params(nominal_f, facts=facts)
    sigmas: dict[str, float] = {}
    tolerances: dict[str, float] = {}
    provenance: dict[str, Any] = {}

    def _entry(name: str, cls: str, tol: float, source: str,
               **extra: Any) -> None:
        sigma = tol / float(k_sigma)
        sigmas[name] = sigma
        tolerances[name] = tol
        provenance[name] = {"class": cls, "nominal": float(nominal_f[name]),
                            "tol": tol, "sigma": sigma, "dist": "normal",
                            "k_sigma": float(k_sigma), "source": source,
                            **extra}

    for name in classes["traces"]:
        tol = nominal_f[name] * (prof.trace_tol_pct / 100.0)
        _entry(name, "trace", tol,
               f"fab_profile:{prof.name}:trace.tolerance_pct",
               pct=prof.trace_tol_pct)
    bt = prof.raw.get("board_thickness") or {}
    pct_ge = bt.get("tolerance_pct_ge_1mm")
    abs_lt = bt.get("tolerance_abs_mm_lt_1mm")
    for name in classes["thickness"]:
        nom = nominal_f[name]
        if nom >= 1.0 and pct_ge is not None:
            _entry(name, "board_thickness", nom * (float(pct_ge) / 100.0),
                   f"fab_profile:{prof.name}:board_thickness"
                   ".tolerance_pct_ge_1mm", pct=float(pct_ge))
        elif nom < 1.0 and abs_lt is not None:
            _entry(name, "board_thickness", float(abs_lt),
                   f"fab_profile:{prof.name}:board_thickness"
                   ".tolerance_abs_mm_lt_1mm", abs_mm=float(abs_lt))
        else:
            provenance[name] = {
                "class": "board_thickness", "nominal": nom,
                "declared": False, "source": "not_declared",
                "detail": "剖面 board_thickness 无对应公差字段"}
    er_decl: dict[str, Any] = {"declared": False, "material": material,
                               "source": "not_declared"}
    if material:
        mat_res = load_material_epsilon_r_tolerance(
            material, materials_path=materials_path)
        if mat_res.get("ok"):
            er_decl = {k: v for k, v in mat_res.items() if k != "ok"}
        else:
            er_decl = {"declared": False, "material": material,
                       "source": "not_declared",
                       "errors": list(mat_res.get("errors") or [])}
        if mat_res.get("ok") and mat_res.get("declared"):
            for name in classes["epsilon_r"]:
                _entry(name, "epsilon_r", float(mat_res["tol"]),
                       mat_res["source"], epsilon_r=mat_res.get("epsilon_r"),
                       source_note=mat_res.get("source_note"))
        elif classes["epsilon_r"]:
            for name in classes["epsilon_r"]:
                provenance[name] = {
                    "class": "epsilon_r", "nominal": nominal_f[name],
                    "declared": False, "source": "not_declared",
                    "detail": f"materials.yaml {material} 未声明 εr 容差"}
    return {
        "ok": True,
        "sigmas": sigmas,
        "tolerances": tolerances,
        "provenance": provenance,
        "epsilon_r_declaration": er_decl,
        "k_sigma": float(k_sigma),
        "profile": prof.name,
        "profile_version": prof.profile_version,
        "classes": classes,
    }


def resolve_tolerance_source(
    tolerance_source: Any,
    nominal: dict[str, Any],
    *,
    default_material: str | None = None,
    k_sigma: float = 3.0,
    facts: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """tolerance_source 引用 → {param: σ}（DP-7 P2 输入规范化，JSON 契约）。

    引用形态：
    - ``None``：{"ok": True, "mode": "arg", "sigmas": None}——调用方回落
      tolerances 直传（缺省行为零变化）；
    - ``str | Path``：同 schema YAML 文件路径，或裸剖面名（"jlcpcb"）；
    - ``dict``：{"fab_profile"?: 剖面名/路径, "material"?:
      materials.yaml 键, "k_sigma"?: float, "params"?: {param: {"tol":
      半宽} 或 数值半宽} 显式覆盖}。

    展开经 :func:`derive_tolerances_from_fab_profile`（单源），显式
    params 覆盖/追加其上（source="tolerance_source:params"）。
    """
    if tolerance_source is None:
        return {"ok": True, "mode": "arg", "sigmas": None,
                "provenance": None}
    src: dict[str, Any]
    if isinstance(tolerance_source, (str, Path)):
        p = Path(tolerance_source)
        if p.is_file():
            try:
                import yaml

                loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
            except Exception as exc:
                return {"ok": False,
                        "errors": [f"tolerance_source YAML 解析失败: {exc}"]}
            if not isinstance(loaded, dict):
                return {"ok": False,
                        "errors": [f"tolerance_source 文件顶层必须为映射: {p}"]}
            src = dict(loaded)
        elif isinstance(tolerance_source, str) \
                and not tolerance_source.endswith(".yaml"):
            src = {"fab_profile": tolerance_source}
        else:
            return {"ok": False, "errors": [f"tolerance_source 文件不存在: {p}"]}
    elif isinstance(tolerance_source, dict):
        src = dict(tolerance_source)
    else:
        return {"ok": False, "errors": [
            f"tolerance_source 必须为 dict/str/Path/None，"
            f"收到 {type(tolerance_source).__name__}"]}
    prof_name = src.get("fab_profile")
    material = src.get("material") or default_material
    try:
        ks = float(src.get("k_sigma", k_sigma))
    except (TypeError, ValueError):
        return {"ok": False, "errors": [
            f"tolerance_source.k_sigma 数值非法: {src.get('k_sigma')!r}"]}
    if prof_name:
        res = derive_tolerances_from_fab_profile(
            nominal, profile=str(prof_name), material=material,
            k_sigma=ks, facts=facts)
        if not res.get("ok"):
            return res
    else:
        res: dict[str, Any] = {
            "ok": True, "sigmas": {}, "tolerances": {}, "provenance": {},
            "epsilon_r_declaration": None, "k_sigma": ks, "profile": None,
            "profile_version": None,
        }
    sigmas = dict(res["sigmas"])
    tolerances = dict(res["tolerances"])
    provenance = dict(res["provenance"])
    explicit = src.get("params") or {}
    if not isinstance(explicit, dict):
        return {"ok": False, "errors": ["tolerance_source.params 必须为映射"]}
    for name, spec in explicit.items():
        name = str(name)
        tol = spec.get("tol") if isinstance(spec, dict) else spec
        try:
            tol_f = float(tol)
        except (TypeError, ValueError):
            return {"ok": False, "errors": [
                f"tolerance_source.params.{name}.tol 数值非法: {tol!r}"]}
        if not tol_f > 0.0:
            return {"ok": False, "errors": [
                f"tolerance_source.params.{name}.tol 必须 >0，收到 {tol_f!r}"]}
        sigmas[name] = tol_f / ks
        tolerances[name] = tol_f
        provenance[name] = {"class": "explicit", "tol": tol_f,
                            "sigma": tol_f / ks, "dist": "normal",
                            "k_sigma": ks,
                            "source": "tolerance_source:params"}
    res.update({"sigmas": sigmas, "tolerances": tolerances,
                "provenance": provenance, "mode": "tolerance_source",
                "material": material})
    return res


def _mc_from_model(
    model: Any,
    nominal: dict[str, float],
    sigmas: dict[str, float],
    specs: list[dict[str, Any]],
    *,
    n: int,
    seed: int,
) -> dict[str, Any]:
    """直配模型（``.predict`` 面）→ 最小 yield ctx → ``uq_service._mc_yield``。

    bounds 优先取模型自带（拟合面，批预测路径可与 model.names 对齐走
    向量化）；无则按名义垫出合成界（±6σ 扰动参数 / ±50% 其余——此时
    模型无批路径，_mc_yield 走逐点回退，bounds 仅占位）。返回含内部
    ``_draw_columns`` 键，消费方只取公共键。
    """
    from rfauto.service.uq_service import _mc_yield

    bounds = getattr(model, "bounds", None)
    if not isinstance(bounds, dict) or not bounds:
        max_sigma = max((float(s) for s in sigmas.values()), default=0.0)
        bounds = {}
        for p, v in nominal.items():
            pad = (6.0 * max_sigma if p in sigmas
                   else max(abs(float(v)) * 0.5, 1e-6))
            bounds[p] = (float(v) - pad, float(v) + pad)
    ctx = {"specs": specs, "model": model, "bounds": bounds}
    return _mc_yield(ctx, {k: float(v) for k, v in nominal.items()},
                     sigmas, n=int(n), seed=int(seed))


def _fab_yield_from_tolerance_source(
    model: Any,
    nominal: dict[str, float],
    *,
    spec: dict[str, Any],
    tolerance_source: Any,
    n: int,
    seed: int,
) -> dict[str, Any]:
    """fab_profile_yield 的 tolerance_source 分支（P2 单源正态多参数 MC）。"""
    if n < 1:
        return {"ok": False, "errors": [f"n 必须 ≥1，收到: {n}"]}
    metric = str(spec.get("metric", ""))
    op = str(spec.get("op", ""))
    spec_value = float(spec.get("value", 0.0))
    if not metric or op not in ("max_below", "min_above"):
        return {"ok": False,
                "errors": ["spec 非法: metric/op 必填，"
                           "op∈(max_below, min_above)"]}
    nom = {k: float(v) for k, v in nominal.items()}
    res = resolve_tolerance_source(tolerance_source, nom)
    if not res.get("ok"):
        return {"ok": False,
                "errors": list(res.get("errors") or ["tolerance_source 解析失败"])}
    sigmas = {k: float(v) for k, v in res["sigmas"].items()}
    if not sigmas:
        return {"ok": False,
                "errors": ["tolerance_source 未派生出任何参数公差"
                           "（检查名义参数分类/材料声明）"],
                "tolerance_provenance": res["provenance"]}
    specs_norm = [{"metric": metric, "op": op, "spec": spec_value}]
    mc = _mc_from_model(model, nom, sigmas, specs_norm, n=n, seed=seed)
    from rfauto.core.wcd import cpk_from_metric_stats

    cpk = cpk_from_metric_stats(mc["metric_stats"], specs_norm)
    return {
        "ok": True,
        "yield_rate": mc["yield_rate"],
        "n_draws": int(n),
        "seed": int(seed),
        "distribution": "normal_additive_single_source",
        "perturb_params": sorted(sigmas),
        "nominal_params": nom,
        "tolerances": sigmas,
        "tolerance_source": "tolerance_source_ref:"
                            + str(res.get("profile") or "explicit_params"),
        "tolerance_provenance": res["provenance"],
        "epsilon_r_declaration": res.get("epsilon_r_declaration"),
        "profile": res.get("profile"),
        "profile_version": res.get("profile_version"),
        "spec": {"metric": metric, "op": op, "value": spec_value},
        "metric_stats": mc["metric_stats"],
        "implementation": mc["implementation"],
        "cpk_per_spec": cpk["per_spec"],
    }


def design_for_yield(
    template: str,
    model: Any,
    specs: list[dict[str, Any]],
    *,
    params: dict[str, float] | None = None,
    profile: str = "jlcpcb",
    material: str = "rogers4350b_h0.508",
    copper_oz: float = 1.0,
    surface_finish: str | None = None,
    board_thickness_mm: float | None = None,
    tolerance_source: Any = None,
    k_sigma: float = 3.0,
    n: int = 10_000,
    seed: int = 42,
) -> dict[str, Any]:
    """DFM 门 + 良率 MC + 逐规范 Cpk 一条 JSON 面（DP-7 P2 端到端）。

    输入 = 模板名义（``template_meta().nominal_params`` 只读 +
    ``params`` 覆盖）+ fab 剖面（``profile``/``material``/``copper_oz``）；
    公差经单源派生（``tolerance_source`` 引用或缺省=剖面直派生）。
    输出 = {ok, template, dfm（DFM 清单，FAIL 不阻断 MC 报数——两信息
    面并列）, dfm_pass, nominal_params, tolerances, tolerance_provenance,
    yield_mc{yield_rate, nominal_metrics, metric_stats, implementation},
    cpk_per_spec, cpk_min, n_draws, seed}。MC 走
    ``uq_service._mc_yield``（向量化优先）；Cpk 走
    ``core/wcd.cpk_from_metric_stats``（零新机制）。

    ``specs`` = [{"metric", "op", "value"|"spec"}]，metric 须是
    ``model.predict`` 返回键（本面不做 DEFAULT_METRIC_KEY 映射——直配
    模型语义），op∈{max_below, min_above, mean_within}。
    """
    from rfauto.adapters.openems_templates import template_meta

    if not isinstance(specs, list) or not specs:
        return {"ok": False, "errors": ["specs 必须是非空列表"]}
    try:
        meta = template_meta(template)
    except KeyError:
        return {"ok": False, "errors": [f"未知模板: {template}"]}
    dfm = check_template_dfm(template, params, profile=profile,
                             material=material, copper_oz=copper_oz,
                             surface_finish=surface_finish,
                             board_thickness_mm=board_thickness_mm)
    if not dfm.get("ran"):
        return {"ok": False,
                "errors": list(dfm.get("errors") or ["DFM 门未运行"]),
                "dfm": dfm}
    nominal = {k: float(v) for k, v in meta.get("nominal_params", {}).items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)}
    nominal.update({k: float(v) for k, v in (params or {}).items()})
    facts = FAB_GEOMETRY_FACTS.get(template) or _scan_geometry_params(nominal)
    if tolerance_source is not None:
        res = resolve_tolerance_source(tolerance_source, nominal,
                                       default_material=material,
                                       k_sigma=k_sigma, facts=facts)
    else:
        res = derive_tolerances_from_fab_profile(
            nominal, profile=profile, material=material,
            k_sigma=k_sigma, facts=facts)
    if not res.get("ok"):
        return {"ok": False, "errors": list(res.get("errors") or []),
                "dfm": dfm}
    sigmas = {k: float(v) for k, v in res["sigmas"].items()}
    if not sigmas:
        return {"ok": False,
                "errors": ["公差单源未派生出任何参数"
                           "（检查模板几何参数分类与材料 εr 声明）"],
                "dfm": dfm,
                "tolerance_provenance": res["provenance"]}
    specs_norm: list[dict[str, Any]] = []
    for s in specs:
        op = str(s.get("op", ""))
        val = s.get("spec", s.get("value"))
        if not s.get("metric") or val is None \
                or op not in ("max_below", "min_above", "mean_within"):
            return {"ok": False,
                    "errors": [f"spec 非法（metric/op/value 必填，op∈"
                               f"max_below/min_above/mean_within）: {s!r}"],
                    "dfm": dfm}
        specs_norm.append({"metric": str(s["metric"]), "op": op,
                           "spec": val})
    mc = _mc_from_model(model, nominal, sigmas, specs_norm, n=n, seed=seed)
    from rfauto.core.wcd import cpk_from_metric_stats

    cpk = cpk_from_metric_stats(mc["metric_stats"], specs_norm)
    return {
        "ok": True,
        "template": template,
        "dfm": dfm,
        "dfm_pass": bool(dfm.get("ok")),
        "profile": res.get("profile"),
        "nominal_params": nominal,
        "tolerances": sigmas,
        "tolerance_provenance": res["provenance"],
        "epsilon_r_declaration": res.get("epsilon_r_declaration"),
        "k_sigma": float(res.get("k_sigma", k_sigma)),
        "n_draws": int(n),
        "seed": int(seed),
        "yield_mc": {
            "yield_rate": mc["yield_rate"],
            "nominal_metrics": mc["nominal_metrics"],
            "metric_stats": mc["metric_stats"],
            "implementation": mc["implementation"],
        },
        "cpk_per_spec": cpk["per_spec"],
        "cpk_min": cpk.get("min"),
    }
