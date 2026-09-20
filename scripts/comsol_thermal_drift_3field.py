"""D14 stage-2：COMSOL 三场热漂移（solid 热膨胀 → 变形构型 → emw 本征重解）。

方案口径（§10.4 D14 / §10.24）：D3 只覆盖材料参数温漂，本链补**尺寸温漂与
形变**——COMSOL Solid Mechanics（线弹性+热膨胀）→ 变形几何/移动网格 →
EM 重解；验收 = 三场 vs stage-1 单向链**漂移量** ≤10%
（core/thermo_mech.three_field_vs_oneway，分母=单向链漂移）。

官方参照（API 逐条实录，禁止凭想象写）：
- applications/RF_Module/Filters/cavity_filter_thermal_expansion.mph（即
  COMSOL 官方"微波滤波器热漂移"例）：Stationary(仅 solid) → Eigenfrequency
  (emw、setSolveFor("/frame/spatial1",False))——solid 位移场定义
  material→spatial frame 映射，emw 在变形后构型上重解本征频率（形变不重解），
  这就是"变形几何/移动网格→EM 重解"的官方实现机制；建模指令流解包实录
  runs/d14_stage2/_doc_probe/cavity_te/actions.txt；
- 结构材料属性（Enu 组 E/nu + def 组 thermalexpansioncoefficient 9 元数组）：
  MEMS_Module biased_resonator_3d_basic.mph（runs/d14_stage2/_doc_probe/mems3d/）。

模型（平行板介质谐振腔，选型理由=解析干净+封闭域本征秒级）：
- 介质块 a×b×h；顶/底面（z=0,h）PEC、四侧 PMC → z 向均匀 TM 模（m=1,n=0,
  p=0）：f0 = c/(2·a·√εr)，与 stage-1 hairpin 半波式同构
  （core/thermo_mech.hairpin_resonance_ghz 口径）；
- solid 与 emw 共享介质域材料：def 组 relpermittivity（emw 消费，温度依赖
  参数表达式 EPS_T）+ Enu 组 E/nu 与 thermalexpansioncoefficient（solid 消费）；
- 约束：角点单点 Displacement0 全约束抑制刚体位移（假设：约束点邻域扰动
  ≪ 均匀热应变，报告 assumption 字段如实记录）；
- 温度以全局参数注入（Tref/T1，solid ThermalExpansion 的 minput_* 与 EPS_T
  表达式同源引用）——与 stage-1 等温单向链口径严格对齐（ht 热场链是 D3
  职责，不进本对比）。

纪律：license 席位串行（复用 adapters.comsol_adapter._SOLVE_LOCK）、
mph.start 显式 version="6.3"（get_shared_client）；真机路径 run_real 仅 CLI
显式运行；定向单测零 COMSOL 依赖（tests/unit/test_comsol_thermal_drift.py
用记录桩断言 Java 序列）。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.adapters import comsol_adapter as ca
from rfauto.core.thermo_mech import (
    STAGE2_ACCEPTANCE_RELATIVE_DEVIATION,
    closed_form_thermal_drift,
    hairpin_resonance_ghz,
    thermo_mech_chain,
    three_field_vs_oneway,
)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO / "runs" / "d14_stage2"
DEFAULT_MESH_HMAX_MM = 1.0
DEFAULT_NEIGS = 1

DRIFT_SPEC_DEFAULTS: dict[str, float] = {
    "a_mm": 20.0,       # 谐振长（x，半波向）
    "b_mm": 12.0,       # 宽（y，与 a 异值防模式简并：f01≈6.5GHz 远离）
    "h_mm": 1.154,      # 厚（z；p=0 模 f 与 h 无关，一阶不敏感）
    "eps_r": 3.66,      # rogers4350b 口径（同 mline 锚）
    "tcdk_ppm_per_k": 50.0,   # 演示量级（调用方注入原则，stage-1 同口径）
    "cte_ppm_per_k": 14.0,    # 面内 CTE 演示量级（stage-1 同值）
    "youngs_gpa": 3.0,  # 各向同性演示量级（均匀应变下漂移判据不敏感，报告注明）
    "nu": 0.3,
    "t_ref_c": 25.0,
}
TEMPS_C_DEFAULT: tuple[float, ...] = (-40.0, 85.0)  # §10.4 D14 环境包络端点


def _box_selection(comp: Any, tag: str, dim: int,
                   lo: tuple[float, float, float],
                   hi: tuple[float, float, float]) -> None:
    """Box 选择集（xmin..zmax/condition 口径同适配器/oven 脚本；整数传字符串 #217④）。"""
    sel = comp.selection().create(tag, "Box")
    sel.set("entitydim", str(dim))
    for axis, value in zip(("x", "y", "z"), lo, strict=True):
        sel.set(f"{axis}min", value)
    for axis, value in zip(("x", "y", "z"), hi, strict=True):
        sel.set(f"{axis}max", value)
    sel.set("condition", "inside")


def _dataset_candidates(model: Any) -> list[str | None]:
    """数据集候选序：默认解优先，其后按标签倒序（新建靠后=新解靠前，oven 手法）。"""
    tags: list[str | None] = [None]
    try:
        for t in model.java.result().dataset().tags():
            s = str(t)
            if s not in tags:
                tags.append(s)
    except Exception:  # 桩对象/版本差异：只有默认候选
        pass
    return [tags[0], *reversed(tags[1:])]


def _extract_valid(model: Any, fetch: Callable[[str | None, int], Any]) -> Any:
    """逐数据集候选提取，首个成功者胜出（候选耗尽则如实抛错；best-effort #105）。"""
    last_exc: Exception | None = None
    for k, ds in enumerate(_dataset_candidates(model)):
        try:
            return fetch(ds, k)
        except Exception as exc:  # JPype 异常族难枚举，逐候选吞
            last_exc = exc
    raise RuntimeError(f"所有数据集候选提取失败: {last_exc}")


def normalize_drift_params(params: dict[str, Any] | None = None) -> dict[str, float]:
    """spec 标量规范化：补默认、转 float、正数/有限校验。

    温度点清单不进本函数（可变长度）：CLI/main 走 opts["temps_c"]，
    纯函数面（compare_three_field）经 opts_temps(spec) 读 spec["_temps"]。
    """
    merged = dict(DRIFT_SPEC_DEFAULTS)
    merged.update({k: float(v) for k, v in (params or {}).items()})
    for key in ("a_mm", "b_mm", "h_mm", "eps_r", "youngs_gpa"):
        if merged[key] <= 0.0:
            raise ValueError(f"{key} 必须 >0")
        if not np.isfinite(merged[key]):
            raise ValueError(f"{key} 必须有限")
    if merged["nu"] <= 0.0 or merged["nu"] >= 0.5:
        raise ValueError("nu 必须在 (0, 0.5) 开区间")
    return merged


def drift_comsol_parameters(spec: dict[str, float]) -> dict[str, str]:
    """COMSOL 全局参数表（表达式显式带单位；#217④ 整数属性传字符串同纪律）。

    EPS_T = ε(T) 线性温漂表达式（TCDk 口径），与单向链 thermo_mech_chain 的
    eps_scale = 1 + TCDk·ΔT 同式——三场与单向链物理对齐的关键。
    """
    tcdk_per_k = spec["tcdk_ppm_per_k"] * 1e-6
    return {
        "A": f"{spec['a_mm']:g}[mm]",
        "B": f"{spec['b_mm']:g}[mm]",
        "H": f"{spec['h_mm']:g}[mm]",
        "EPSR": f"{spec['eps_r']:g}",
        "alphatcdk": f"{tcdk_per_k:g}[1/K]",
        "EPS_T": "EPSR*(1+alphatcdk*(T1-Tref))",
        "Tref": f"{spec['t_ref_c']:g}[degC]",
        "T1": f"{spec['t_ref_c']:g}[degC]",
        "cte": f"{spec['cte_ppm_per_k'] * 1e-6:g}[1/K]",
    }


def resonator_closed_form_ghz(spec: dict[str, float]) -> float:
    """闭式基模 f0 = c/(2a√εr)（= stage-1 hairpin 半波式，L=a、εeff=εr）。"""
    return hairpin_resonance_ghz(spec["a_mm"], spec["eps_r"])


def drift_selection_boxes(spec: dict[str, float], *,
                          tol: float = 1e-3) -> dict[str, tuple[int, tuple[float, float, float], tuple[float, float, float]]]:
    """选择盒（dim, lo, hi）：顶底 PEC 面 / 四侧 PMC 面 / 三约束点（dim=0）。

    三点 3-2-1 约束（官方 cavity_filter_thermal_expansion.mph disp1/2/3 同构
    ——disp1 全 3 方向、disp2 xz、disp3 yz）：单点全约束留两刚体旋转模，
    真机实证稳态步病态不收敛（相对误差 0.57>容差，runs/d14_stage2/）。
    底面三点锚定不抑制面内/厚度自由膨胀（z=0 平面为参考）。
    """
    a, b, h = spec["a_mm"], spec["b_mm"], spec["h_mm"]
    return {
        "sel_pec_z0": (2, (-tol, -tol, -tol), (a + tol, b + tol, tol)),
        "sel_pec_zh": (2, (-tol, -tol, h - tol), (a + tol, b + tol, h + tol)),
        "sel_pmc_x0": (2, (-tol, -tol, -tol), (tol, b + tol, h + tol)),
        "sel_pmc_xl": (2, (a - tol, -tol, -tol), (a + tol, b + tol, h + tol)),
        "sel_pmc_y0": (2, (-tol, -tol, -tol), (a + tol, tol, h + tol)),
        "sel_pmc_yw": (2, (-tol, b - tol, -tol), (a + tol, b + tol, h + tol)),
        "sel_fix1": (0, (-tol, -tol, -tol), (tol, tol, tol)),
        "sel_fix2": (0, (a - tol, -tol, -tol), (a + tol, tol, tol)),
        "sel_fix3": (0, (-tol, b - tol, -tol), (tol, b + tol, tol)),
    }


def build_drift_model(client: Any, spec: dict[str, float],
                      opts: dict[str, Any]) -> Any:
    """在 Client 内构建三场热漂移模型（几何/材料/emw+solid/study/网格）。

    纯 Java API 序列，可被记录桩离线断言（tests/unit/test_comsol_thermal_drift.py）。
    物理场特征类型串/属性名逐条官方实录（模块 docstring 与 comsol_adapter
    D14 stage-2 方法组 docstring）。
    """
    model = client.create(f"rfauto_thermal_drift_{int(time.time())}")
    j = model.java
    for name, expr in drift_comsol_parameters(spec).items():
        j.param().set(name, expr)

    j.component().create("comp1", True)
    comp = j.component("comp1")
    geom = comp.geom().create("geom1", 3)
    geom.lengthUnit("mm")
    blk = geom.create("blk1", "Block")
    blk.set("base", "corner")
    blk.set("pos", ["0", "0", "0"])
    blk.set("size", ["A", "B", "H"])
    geom.run()

    for tag, (dim, lo, hi) in drift_selection_boxes(spec).items():
        _box_selection(comp, tag, dim, lo, hi)

    # 材料：单一介质域，emw 与 solid 共享同一材料对象（enw 消费 relpermittivity；
    # solid 消费 Enu 组 E/nu + def 组 thermalexpansioncoefficient——官方 MEMS 例
    # 同构，add_structural_properties 内部实录注释）
    mat = comp.material().create("mat1", "Common")
    mat.selection().all()
    grp = mat.propertyGroup("def")
    grp.set("relpermittivity", ["EPS_T"])  # ε(T) 温漂表达式（与单向链同式）
    grp.set("relpermeability", ["1"])
    grp.set("electricconductivity", ["0"])
    ca.ComsolAdapter.add_structural_properties(
        mat, youngs_expr=f"{spec['youngs_gpa']:g}[GPa]",
        poisson_expr=f"{spec['nu']:g}", cte_expr="cte")

    # emw：封闭腔本征问题（无端口无辐射边界）；顶底 PEC、四侧 PMC
    phys = comp.physics().create(ca.PHYSICS_TAG, ca.PHYSICS_TYPE, "geom1")
    for tag, sel in (("pec_z0", "sel_pec_z0"), ("pec_zh", "sel_pec_zh")):
        pec = phys.create(tag, "PerfectElectricConductor", 2)
        pec.selection().named(sel)
    for tag, sel in (("pmc_x0", "sel_pmc_x0"), ("pmc_xl", "sel_pmc_xl"),
                     ("pmc_y0", "sel_pmc_y0"), ("pmc_yw", "sel_pmc_yw")):
        pmc = phys.create(tag, "PerfectMagneticConductor", 2)
        pmc.selection().named(sel)

    # solid：线弹性（材料 E/nu）+ 热膨胀（Tref/T1 参数注入）+ 三点 3-2-1
    # 刚体约束（官方 cavity 例 disp1/2/3 同构；单点全约束留刚体旋转模，
    # 真机实证稳态步病态不收敛）
    solid = ca.ComsolAdapter.add_solid_mechanics(comp)
    ca.ComsolAdapter.add_thermal_expansion(
        solid, t_ref_expr="Tref", t_expr="T1")
    ca.ComsolAdapter.add_point_displacement_constraint(
        solid, selection="sel_fix1", tag="disp1", components=(0, 1, 2))
    ca.ComsolAdapter.add_point_displacement_constraint(
        solid, selection="sel_fix2", tag="disp2", components=(0, 2))
    ca.ComsolAdapter.add_point_displacement_constraint(
        solid, selection="sel_fix3", tag="disp3", components=(1, 2))

    # 网格位移=solid 位移（官方 tunable_cavity 例 PrescribedMeshDisplacement
    # 同构）：同域（emw 与 solid 共用介质域）场景必需且充分——eig 步（frame
    # 不作为求解对象）在变形后构型上重解 emw 本征
    ca.ComsolAdapter.add_mesh_displacement(comp)

    # study：Stationary(仅 solid) → Eigenfrequency(emw、变形构型)——官方
    # cavity_filter_thermal_expansion.mph 实录（build_thermal_drift_study docstring）
    ca.ComsolAdapter.build_thermal_drift_study(
        j, neigs=int(opts["neigs"]), study_tag=ca.STUDY_TAG)

    mesh = comp.mesh().create("mesh1")
    size = mesh.feature("size")
    size.set("custom", "on")
    size.set("hmax", float(opts["mesh_hmax_mm"]))
    mesh.create("ftet1", "FreeTet")
    mesh.run()
    return model


def _extract_eigenfrequency_valid(model: Any, k: int) -> float:
    """逐数据集候选提取基模本征频率（GHz）；候选耗尽如实抛错（oven 手法）。"""

    def fetch(ds: str | None, idx: int) -> float:
        arr = ca.ComsolAdapter.extract_eigenfrequency(
            model, dataset=ds, tag=f"eig_freq_{k}_{idx}")
        finite = arr[np.isfinite(arr) & (arr > 0.0)]
        if finite.size == 0:
            raise RuntimeError("该数据集无正有限本征频率")
        return float(finite[0])

    return float(_extract_valid(model, fetch))


def _stat_solver_tags(model: Any) -> list[tuple[str, Any]]:
    """枚举（sol tag, Stationary 求解器特征）——序列可能不止一个 sol。"""
    out: list[tuple[str, Any]] = []
    for s in model.java.sol().tags():
        sol = model.java.sol(str(s))
        for f in sol.feature().tags():
            feat = sol.feature(str(f))
            try:
                if str(feat.getType()) == "Stationary":
                    out.append((str(s), feat))
            except Exception:  # 桩/版本差异：getType 不可用则跳过
                continue
    return out


def prepare_eigen_solver(model: Any, spec: dict[str, float]) -> list[str]:
    """生成 solver 序列并配置本征 shift 与稳态求解器稳健性（真机坑实录）。

    真机实证（runs/d14_stage2/）：
    - java 自动序列 Eigenvalue 缺省 shift=0 → ARPACK 命中零空间解 →
      emw.freq=0 假结果；shift 取**模型自己的闭式基模**（数值搜索起点，
      ±0.3% 温漂远在收敛域内）；
    - T1=Tref 点 ΔT=0 → 热膨胀零应变，稳态相对容差判据退化（残差
      0.006~0.007 间歇性超过默认容差；迭代求精也不稳）——stat 解只喂 EM
      形变（nm 级 vs 波长 mm 级），stol=1e-2 折合频率 <0.2ppm，物理充分；
    - 线性求解器强制 Direct（fc1.linsolver=d1，属性真机 properties() dump
      实录）：迭代法在点约束病态系统上间歇不收敛。
    序列生成走一次 run()（首解弃用；createAutoSequences("all") 实测会让
    稳态步不收敛报错）。
    """
    model.java.study(ca.STUDY_TAG).run()
    shift_ghz = resonator_closed_form_ghz(spec)
    touched = ca.ComsolAdapter.configure_eigen_shift(
        model, f"{shift_ghz:.8g}[GHz]")
    for _s, stat_feat in _stat_solver_tags(model):
        with contextlib.suppress(Exception):
            stat_feat.set("stol", "1e-2")
        with contextlib.suppress(Exception):
            stat_feat.feature("fc1").set("linsolver", "d1")
    print(f"[prep] eigen shift touched={touched}", flush=True)
    return touched


def evaluate_drift(model: Any, spec: dict[str, float],
                   opts: dict[str, Any]) -> dict[float, float]:
    """逐温度点：set T1 → 重跑 study → 提取基模本征频率（GHz）。

    首点为参考温度 Tref（归一锚），其后为环境包络点。温度驱动走参数
    （minput_temperature/EPS_T 同源引用 T1），与 stage-1 等温口径对齐。
    """
    prepare_eigen_solver(model, spec)
    f_sim: dict[float, float] = {}
    for k, t_c in enumerate([spec["t_ref_c"], *opts["temps_c"]]):
        model.java.param().set("T1", f"{float(t_c):.6g}[degC]")
        model.java.study(ca.STUDY_TAG).run()
        f_ghz = _extract_eigenfrequency_valid(model, k)
        f_sim[float(t_c)] = f_ghz
        print(f"[eig] T1={t_c:g} degC -> f_eig={f_ghz:.6f} GHz", flush=True)
    return f_sim


def compare_three_field(spec: dict[str, float], f_sim: dict[float, float],
                        temps_c: list[float]) -> dict[str, Any]:
    """三场 vs 单向链（D14 stage-2 验收 ≤10%）+ stage-1 闭式复核（≤20%）。

    归一口径：f0_nominal 取**三场仿真在 Tref 的本征频率**（消掉网格系统性
    偏置）；单向链漂移按同比例重标定（f_oneway = f0_sim·(1+drift_oneway)）
    ——两侧漂移量都是相对各自参考点的无量纲比值，比较的只是漂移。
    temps_c 须含参考温度 t_ref_c（作为 f_sim 归一锚）。
    """
    f0_sim = f_sim[float(spec["t_ref_c"])]
    chain_by_temp: dict[str, dict[str, Any]] = {}
    comparison: dict[str, dict[str, Any]] = {}
    closed_by_temp: dict[str, dict[str, Any]] = {}
    for t_c in temps_c:
        dt = t_c - spec["t_ref_c"]
        chain = thermo_mech_chain(
            "hairpin", delta_t_c=dt, cte_ppm_per_k=spec["cte_ppm_per_k"],
            tcdk_ppm_per_k=spec["tcdk_ppm_per_k"],
            line_len_mm=spec["a_mm"], eps_eff=spec["eps_r"])
        chain_by_temp[f"{t_c:g}"] = chain
        closed_by_temp[f"{t_c:g}"] = closed_form_thermal_drift(
            resonator_closed_form_ghz(spec), dt, spec["cte_ppm_per_k"],
            spec["tcdk_ppm_per_k"])
        f_three = f_sim[float(t_c)]
        f_oneway_scaled = f0_sim * (1.0 + chain["oneway_df_over_f"])
        comparison[f"{t_c:g}"] = three_field_vs_oneway(
            f0_sim, f0_oneway_ghz=f_oneway_scaled, f0_three_field_ghz=f_three)
    stage1_recheck = {
        f"{t_c:g}": {
            "oneway_drift_ppm": chain_by_temp[f"{t_c:g}"]["oneway_drift_ppm"],
            "closed_form_drift_ppm":
                closed_by_temp[f"{t_c:g}"]["df_over_f_ppm"],
            "relative_deviation":
                chain_by_temp[f"{t_c:g}"]["relative_deviation"],
            "within_20pct": chain_by_temp[f"{t_c:g}"]["within_20pct"],
        }
        for t_c in temps_c
    }
    verdict = {
        "stage2_within_10pct_all": all(
            bool(v["within_10pct"]) for v in comparison.values()),
        "stage1_within_20pct_all": all(
            bool(v["within_20pct"]) for v in stage1_recheck.values()),
        "stage2_threshold": STAGE2_ACCEPTANCE_RELATIVE_DEVIATION,
        "assumption": ("温度参数注入（等温口径，与 stage-1 单向链严格对齐）；"
                       "三点 3-2-1 约束（官方 cavity 例同构）锚定刚体且不抑制"
                       "自由膨胀；CTE/E/nu 为"
                       "演示量级（漂移判据对均匀应变值不敏感）"),
    }
    return {
        "f0_sim_ref_ghz": f0_sim,
        "f0_closed_form_ghz": resonator_closed_form_ghz(spec),
        "chain_by_temp": chain_by_temp,
        "closed_form_by_temp": closed_by_temp,
        "comparison": comparison,
        "stage1_recheck": stage1_recheck,
        "verdict": verdict,
    }


def offline_report(spec: dict[str, float],
                   temps_c: list[float]) -> dict[str, Any]:
    """离线面：闭式锚 vs stage-1 单向链（无 COMSOL；--offline 与单测共用）。"""
    f0_closed = resonator_closed_form_ghz(spec)
    rows: dict[str, dict[str, Any]] = {}
    for t_c in temps_c:
        dt = t_c - spec["t_ref_c"]
        chain = thermo_mech_chain(
            "hairpin", delta_t_c=dt, cte_ppm_per_k=spec["cte_ppm_per_k"],
            tcdk_ppm_per_k=spec["tcdk_ppm_per_k"],
            line_len_mm=spec["a_mm"], eps_eff=spec["eps_r"])
        closed = closed_form_thermal_drift(
            f0_closed, dt, spec["cte_ppm_per_k"], spec["tcdk_ppm_per_k"])
        rows[f"{t_c:g}"] = {
            "delta_t_c": dt,
            "oneway_drift_ppm": chain["oneway_drift_ppm"],
            "closed_form_drift_ppm": closed["df_over_f_ppm"],
            "relative_deviation": chain["relative_deviation"],
            "within_20pct": chain["within_20pct"],
        }
    return {
        "mode": "offline",
        "f0_closed_form_ghz": f0_closed,
        "by_temp": rows,
        "stage1_within_20pct_all": all(bool(r["within_20pct"])
                                       for r in rows.values()),
    }


def run_real(args: argparse.Namespace, spec: dict[str, float],
             opts: dict[str, Any]) -> dict[str, Any]:
    """真机链：Client（钉 6.3）→ 建模 → 逐温度点本征 → 三场 vs 单向链判定。"""
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with ca._SOLVE_LOCK:  # license 席位串行（同时刻全机只跑一个 COMSOL 求解）
        client = ca.get_shared_client()
        model = build_drift_model(client, spec, opts)
        if args.save_mph:
            model.save(str((out_dir / "thermal_drift_3field.mph").resolve()))
        f_sim = evaluate_drift(model, spec, opts)
        report = compare_three_field(spec, f_sim, opts["temps_c"])
    report.update({
        "mode": "real",
        "wp": "D14 stage-2 (§10.4/§10.24)",
        "spec": {k: v for k, v in spec.items() if not k.startswith("_")},
        "temps_c": opts["temps_c"],
        "opts": {k: v for k, v in opts.items() if k != "temps_c"},
        "adapter": ("comsol_adapter D14 stage-2 方法组 + 官方 "
                    "cavity_filter_thermal_expansion.mph 实录口径"),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    result_path = out_dir / "thermal_drift_3field_result.json"
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    (out_dir / "thermal_drift_3field_summary.md").write_text(
        render_summary(report), encoding="utf-8")
    print(f"[done] result -> {result_path}", flush=True)
    return report


def render_summary(report: dict[str, Any]) -> str:
    """人读摘要（关键数字与判定；报告数字全部可溯 JSON）。"""
    comp = report["comparison"]
    lines = [
        "# D14 stage-2 COMSOL 三场热漂移 vs stage-1 单向链",
        "",
        f"- f0_sim(Tref) = {report['f0_sim_ref_ghz']:.6f} GHz，"
        f"闭式 c/(2a√εr) = {report['f0_closed_form_ghz']:.6f} GHz",
        f"- verdict: stage2 ≤10% all={report['verdict']['stage2_within_10pct_all']}"
        f"，stage1 ≤20% all={report['verdict']['stage1_within_20pct_all']}",
        "",
        "| T (°C) | f_3f (GHz) | drift_3f (ppm) | drift_oneway (ppm) |"
        " 偏差 | ≤10% |",
        "|---:|---:|---:|---:|---:|:--:|",
    ]
    for key, row in comp.items():
        lines.append(
            f"| {key} | {row['f0_three_field_ghz']:.6f} "
            f"| {row['drift_three_field_ppm']:.2f} "
            f"| {row['drift_oneway_ppm']:.2f} "
            f"| {row['relative_deviation']:.4f} "
            f"| {'PASS' if row['within_10pct'] else 'FAIL'} |")
    lines += ["", f"假设与口径：{report['verdict']['assumption']}", ""]
    return "\n".join(lines)


def build_opts(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "mesh_hmax_mm": float(args.mesh_hmax),
        "neigs": int(args.neigs),
        "save_mph": bool(args.save_mph),
        "temps_c": [float(t) for t in str(args.temps).split(",")],
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true",
                        help="只出闭式锚 vs 单向链对照（不连 COMSOL）")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--mesh-hmax", default=DEFAULT_MESH_HMAX_MM, type=float)
    parser.add_argument("--neigs", default=DEFAULT_NEIGS, type=int)
    parser.add_argument("--save-mph", action="store_true")
    parser.add_argument("--temps", default=",".join(f"{t:g}" for t in TEMPS_C_DEFAULT),
                        help="逗号分隔温度点（°C），默认 -40,85")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    opts = build_opts(args)
    spec = dict(DRIFT_SPEC_DEFAULTS)
    if args.offline:
        report = offline_report(spec, opts["temps_c"])
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    report = run_real(args, spec, opts)
    print(render_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
