"""layered_stack A_auto/C 档双档对照判读服务（aurora_q 席位 Q-X26）。

判据单源复用（零重实现）：判据门限 G0-G3/S0 哨兵/CSV 口径/verdict 组合
规则的唯一事实源 = runs/aurora_q/qx10_smoke/qx10_verdict.py（#122 冻结；
Q-X14 Fix3 加 S0 结构哨兵）。本服务**动态加载该冻结模块后委托**其
judge_qx10/collect_stats/structural_sentinel——不在本模块重写任何门限
（门限数字在本模块出现即缺陷；对照/分解只消费模块产出的状态词）。
模块文件缺失/缺必需属性 → fail-loud（FileNotFoundError/ValueError），
不静默降级（#122：如实不凑）。

运行配置注入（Q-X11 criteria_qx11.md §6 预声明的合法消费口径）：仅
MESH_RESOLUTION_MM / NRTS / EXCITE_PORT 三键可注入（白名单闭集，其余
键=ValueError——防运行配置注入漂移成门限篡改）；每次加载=独立新模块
实例（importlib 文件加载，不进 sys.modules、不污染全局），两档各持
配置互不泄漏。

三因子正交分解框架（RC1/RC2/RC3；#122：因子判据预声明于本 docstring，
真数据进来不改判据）：
  RC1 几何（端口失义面）  : S0 结构哨兵 TRIGGER → implicated；S0 PASS →
                          excluded；S0 SKIPPED/键缺（旧 stats 重放）→
                          unevaluated（不冒充）。
  RC3 截断（#262 家族）   : over_unity_cnt>0 且 RC1 implicated →
                          co_present_not_attributed（S0 先于截断归因——
                          加倍窗治不了结构失义，qx10_verdict 同款纪律）；
                          >0 且 S0 PASS → implicated；==0 → excluded；
                          观测缺 → unevaluated。
  RC2 网格精度            : 单档内不自证（单档无收敛证据）；只跨档判——
                          同 geometry 标签两档按 base/cells 精化比对：
                          粗档 implicated+细档 excluded → 网格主导嫌疑
                          （mesh_dominant_suspect）；两档皆 implicated →
                          persists（网格精化不治→RC2 排除）；任一档
                          unevaluated → not_observable。
  正交性边界（如实预声明）：A vs C 现存对照是**网格+窗联合精化**（base
  2.42× ∧ 窗 2.0× 同时变）——单对照对 RC2/RC3 只能出"联合精化不治"
  结论（not_cured_by_joint_refinement），完全正交需单因子隔离跑（同
  mesh 换窗 / 同窗换 mesh）。框架把该边界写进 pair 结论，不冒充正交。

修复后 A 档重发射（Q-X12 §5 Fix4-2 预声明"qx11 A 档数据对修复后几何
不可复用"）：发射面（qx11_launch/qx11_harvest/qx11_audit，runs/ 只读）
由主代理复用——本服务供**判读侧**两件：①derive_relaunch_nrts（§3 冻结
推导同式：物理窗 ≥C 档加倍窗，只许加窗不许减窗）+pick 校验；②
judge_mirror（收割回拉镜像 → 判读，qx11_harvest._judge 同款语义独立
实现：audit base_m→mesh 注入、meta closed_form 透传、产物缺→INCOMPLETE
透传）。发射前必须重跑 qx11_audit（修复后渲染 sha/base/cells/dt 全变，
漂移门 fail-loud）——本服务零 SSH 零真机，真机步全留主代理。

服务层 JSON 进出（规则 4）：全部公开函数入/出 plain dict（JSON 可序列
化），None 透传（观测缺=不缺数伪装，如实 null）。
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import types
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: 判据单源（runs/ 证据区只读件）相对仓根路径；仓根由本文件位置推导
#: （src/rfauto/service/x.py → parents[3]=repo 根）。
VERDICT_MODULE_RELATIVE = Path("runs") / "aurora_q" / "qx10_smoke" / "qx10_verdict.py"

#: 加载后模块必须具备的判据面（缺任一=fail-loud；防"半成品判据模块"
#: 被当真判读）。
_REQUIRED_ATTRS = (
    "judge_qx10",
    "collect_stats",
    "structural_sentinel",
    "closed_form_anchor",
    "gate_g0_anchor",
    "gate_g1_beta",
    "gate_g2_s11_valley",
    "gate_g3_health",
    "nominal_plane_dist_m",
)

#: 运行配置注入白名单（Q-X11 criteria §6 预声明的合法键闭集）→ 模块级键。
#: 门限常量（G1_PASS/S0 哨兵阈值等）**不在白名单**——注入即拒。
_CONFIG_KEYS: dict[str, str] = {
    "mesh_resolution_mm": "MESH_RESOLUTION_MM",
    "nrts": "NRTS",
    "excite_port": "EXCITE_PORT",
}

#: 判读产物契约（judge_products 缺件判定）。
_PRODUCT_FILES = ("sparams.csv", "port_beta.csv")

#: derive_relaunch_nrts 的 C 档参照（#122 冻结推导的对照基准）：
#: C 档 NrTS=51000（Q-X10 冻结运行配置）；C 档 dt=12.253783…fs
#: （budget_ladder.json C_base40um 行 exec 实测，qx10_verdict
#: FROZEN_DT_FS=12.25 同源四舍五入）。
_C_NRTS_DEFAULT = 51_000
_C_DT_FS_DEFAULT = 12.253783221768696

#: over_unity_cnt 的最末兜底来源标注（Q-X11 旧版 verdict 截断路径只把
#: 计数写进 note 文本；regex 提取带来源标注不冒充 stats 直读）。
_OU_NOTE_PATTERN = re.compile(r"over_unity_cnt=(\d+)")


# ── 判据模块加载（单源复用；独立实例；白名单注入）─────────────────────────
def default_verdict_module_path(repo_root: str | Path | None = None) -> Path:
    """判据单源默认路径（repo/runs/aurora_q/qx10_smoke/qx10_verdict.py）。"""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[3]
    return Path(repo_root) / VERDICT_MODULE_RELATIVE


def load_verdict_module(
    path: str | Path | None = None,
    *,
    config: Mapping[str, Any] | None = None,
) -> types.ModuleType:
    """加载判据单源为**独立新模块实例**并注入运行配置（白名单闭集）。

    - path 缺省=仓内 runs/aurora_q/qx10_smoke/qx10_verdict.py；文件缺
      → FileNotFoundError（fail-loud，不静默降级）。
    - 每次调用=全新 exec 的模块实例（importlib 文件加载、不注册
      sys.modules）——两档判读各持注入配置互不泄漏，全局无副作用。
    - config 键必须在 :data:`_CONFIG_KEYS` 白名单内（mesh_resolution_mm/
      nrts/excite_port），其余键=ValueError（防运行配置注入漂移成门限
      篡改——G1_PASS 等门限常量不可达）；值按模块键语义强转
      （mesh=float / nrts=int / excite_port=int）。
    - 模块缺 :data:`_REQUIRED_ATTRS` 任一判据面 → ValueError（列出缺
      项；防半成品模块当真判读）。
    """
    resolved = Path(path) if path is not None else default_verdict_module_path()
    if not resolved.is_file():
        raise FileNotFoundError(
            f"判据单源缺失（fail-loud 不静默降级）: {resolved}")
    spec = importlib.util.spec_from_file_location(
        f"_qx10_verdict_fresh_{uuid.uuid4().hex}", resolved)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"判据单源加载器构造失败: {resolved}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    missing = [a for a in _REQUIRED_ATTRS if not hasattr(module, a)]
    if missing:
        raise ValueError(
            f"判据单源缺必需判据面 {missing}: {resolved}")
    for key, value in (config or {}).items():
        if key not in _CONFIG_KEYS:
            raise ValueError(
                f"运行配置键 '{key}' 不在白名单 {_CONFIG_KEYS}——门限常量"
                "不可注入（Q-X11 criteria §6 合法键闭集）")
        attr = _CONFIG_KEYS[key]
        coerced = float(value) if key == "mesh_resolution_mm" else int(value)
        setattr(module, attr, coerced)
    return module


# ── 判读入口（产物缺→INCOMPLETE 透传；judge 口径全在单源模块内）───────────
def _mirror_meta_closed_form(rundir: Path) -> dict[str, Any] | None:
    meta_path = rundir / "layered_stack_meta.json"
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    cf = meta.get("closed_form")
    if cf is None:
        return None
    return {
        "epsilon_eff": float(cf["epsilon_eff"]),
        "z0_ohm": float(cf["z0_ohm"]),
    }


def judge_products(
    rundir: str | Path,
    *,
    meta_closed_form: Mapping[str, float] | None = None,
    config: Mapping[str, Any] | None = None,
    verdict_module_path: str | Path | None = None,
) -> dict[str, Any]:
    """对一份判读产物目录判读（G0-G3/S0 门限与口径全在单源模块内）。

    - 产物契约：rundir 下 sparams.csv+port_beta.csv 两件齐 → 模块
      collect_stats→judge_qx10(measured, meta)；任一件缺 →
      judge_qx10(None)（INCOMPLETE+missing 透传，如实不凑）。
    - meta_closed_form 缺省时尝试 rundir/layered_stack_meta.json 的
      closed_form 键（qx11_harvest 同款契约）；两者皆缺 → None（G0 的
      meta 位项如实跳过，模块内注记）。
    - 返回 JSON 信封：verdict/stats/run_config（实际注入值）/产物根/
      判据模块路径。零仿真零网络——纯离线 CSV 统计+门组装。
    """
    rd = Path(rundir)
    module = load_verdict_module(verdict_module_path, config=config)
    meta_cf = (
        {"epsilon_eff": float(meta_closed_form["epsilon_eff"]),
         "z0_ohm": float(meta_closed_form["z0_ohm"])}
        if meta_closed_form is not None
        else _mirror_meta_closed_form(rd))
    products_ok = all((rd / f).is_file() for f in _PRODUCT_FILES)
    measured = module.collect_stats(rd) if products_ok else None
    verdict = module.judge_qx10(measured, meta_cf)
    return {
        "verdict": verdict,
        "stats": measured,
        "run_config": {
            "mesh_resolution_mm": getattr(module, "MESH_RESOLUTION_MM", None),
            "nrts": getattr(module, "NRTS", None),
            "excite_port": getattr(module, "EXCITE_PORT", None),
        },
        "rundir": str(rd),
        "products_ok": products_ok,
        "verdict_module_path": str(
            verdict_module_path if verdict_module_path is not None
            else default_verdict_module_path()),
    }


def judge_mirror(
    mirror: str | Path,
    *,
    audit_json: str | Path | Mapping[str, Any] | None = None,
    nrts: int | None = None,
    excite_port: int = 1,
    verdict_module_path: str | Path | None = None,
) -> dict[str, Any]:
    """收割回拉镜像 → 判读（A 档判读入口；qx11_harvest._judge 同款语义）。

    与 :func:`judge_products` 的差异只在运行配置来源：audit_json（离线
    审计产物，键 base_m 单位米）→ mesh_resolution_mm=base_m*1e3——与
    qx11_harvest._judge 的 §6 预声明口径同式独立实现（qx11_server 件
    零改动只读）。nrts **必显式传入**（A 档窗是发射前冻结的预声明运
    行配置，缺=ValueError 不猜默认——猜窗=截断嫌疑复发面，criteria
    §3 教训）。镜像 meta layered_stack_meta.json 的 closed_form 自动
    透传；产物缺 → INCOMPLETE 透传。
    """
    if nrts is None:
        raise ValueError(
            "nrts 必显式传入（发射前冻结的运行配置；缺=不判读不猜默认）")
    if audit_json is None:
        raise ValueError(
            "audit_json 必显式传入（base_m→mesh 注入；缺=不判读不猜默认）")
    if isinstance(audit_json, Mapping):
        audit = dict(audit_json)
    else:
        audit = json.loads(Path(audit_json).read_text(encoding="utf-8"))
    if "base_m" not in audit:
        raise ValueError(
            f"audit 缺 base_m 键（fail-loud 不猜网格）: keys={sorted(audit)}")
    base_mm = float(audit["base_m"]) * 1e3
    return judge_products(
        mirror,
        config={"mesh_resolution_mm": base_mm, "nrts": int(nrts),
                "excite_port": int(excite_port)},
        verdict_module_path=verdict_module_path,
    )


# ── 修复后 A 档重发射：NrTS 推导（criteria_qx11.md §3 冻结推导同式）────────
def derive_relaunch_nrts(
    *,
    dt_fs: float,
    c_nrts: int = _C_NRTS_DEFAULT,
    c_dt_fs: float = _C_DT_FS_DEFAULT,
    pick: int | None = None,
) -> dict[str, Any]:
    """修复后重发射的 NrTS 下界推导（§3 冻结规则：物理窗 ≥C 档加倍窗）。

    规则（发射前冻结，#122）：C 档加倍窗 = 2·c_nrts·c_dt_fs；本档
    NrTS_min = ceil(加倍窗/dt_fs)；只许加窗不许减窗——pick（取整档，
    Q-X11 先例 135000=向上有意取整）< NrTS_min → ValueError fail-loud。
    dt_fs/c_dt_fs 必须来自 exec 实测预算（budget/audit 产物），不收
    手写字面以外的猜值。返回窗口量（ps）与对照比值，全 JSON 可序列化。
    """
    for name, val in (("dt_fs", dt_fs), ("c_dt_fs", c_dt_fs)):
        if not (isinstance(val, (int, float)) and math.isfinite(val)
                and val > 0):
            raise ValueError(f"{name} 必为正有限实数（exec 实测），得 {val!r}")
    if not (isinstance(c_nrts, int) and c_nrts >= 1):
        raise ValueError(f"c_nrts 必为正整数，得 {c_nrts!r}")
    c_doubled_window_ps = 2.0 * c_nrts * c_dt_fs / 1000.0
    nrts_min = math.ceil(c_doubled_window_ps * 1000.0 / float(dt_fs))
    chosen = nrts_min if pick is None else int(pick)
    if chosen < nrts_min:
        raise ValueError(
            f"pick={chosen} < NrTS 下界 {nrts_min}（物理窗 <C 档加倍窗="
            "减窗，#262 只许加窗不许减窗——fail-loud）")
    window_ps = chosen * float(dt_fs) / 1000.0
    return {
        "nrts_min": nrts_min,
        "nrts_pick": chosen,
        "dt_fs": float(dt_fs),
        "window_ps": window_ps,
        "c_nrts": int(c_nrts),
        "c_dt_fs": float(c_dt_fs),
        "c_doubled_window_ps": c_doubled_window_ps,
        "window_ratio_vs_c_doubled": window_ps / c_doubled_window_ps,
        "rule": "NrTS_min=ceil(2·C_NRTS·C_DT/dt)；物理窗≥C 档加倍窗"
                "（criteria_qx11.md §3 冻结推导同式）",
    }


# ── 档位记录规约 + 双档对照表（None 透传；不缺数伪装）─────────────────────
def _gate_status(verdict: Mapping[str, Any], gate: str) -> str | None:
    gates = verdict.get("gates")
    if not isinstance(gates, Mapping):
        return None
    g = gates.get(gate)
    if not isinstance(g, Mapping):
        return None
    status = g.get("status")
    return str(status) if status is not None else None


def _over_unity_cnt(verdict: Mapping[str, Any],
                    stats: Mapping[str, Any] | None) -> tuple[int | None, str]:
    """over_unity_cnt 取值链（stats 直读→verdict 顺带→G3 门→note regex）。"""
    if stats is not None and stats.get("over_unity_cnt") is not None:
        return int(stats["over_unity_cnt"]), "stats"
    also = verdict.get("over_unity_cnt_also")
    if also is not None:
        return int(also), "verdict.over_unity_cnt_also"
    gates = verdict.get("gates")
    if isinstance(gates, Mapping):
        g3 = gates.get("G3")
        if isinstance(g3, Mapping) and g3.get("s_over_unity_cnt") is not None:
            return int(g3["s_over_unity_cnt"]), "gates.G3"
    note = verdict.get("note")
    if isinstance(note, str):
        m = _OU_NOTE_PATTERN.search(note)
        if m:
            return int(m.group(1)), "note_regex"
    return None, "missing"


def build_tier_record(
    name: str,
    *,
    verdict: Mapping[str, Any] | None,
    stats: Mapping[str, Any] | None = None,
    mesh: Mapping[str, Any] | None = None,
    nrts: int | None = None,
    geometry: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """单档判读记录规约（从 verdict/stats/mesh 抽观测面；缺键=None 透传）。

    - verdict=None（未判读/产物整缺）→ not_judged=True，判读字段全
      None——对照面如实记"未判"，不冒充任何门结果。
    - stats 缺时观测面回落 verdict 内嵌位（G1 observed/顺带键/note
      regex——见 :func:`_over_unity_cnt`），每键带来源标注。
    - mesh = {"base_mm":…, "cells":…, "dt_fs":…}（budget/audit 实测）；
      nrts+dt_fs 齐时算 window_ps（物理窗，ps）。
    - geometry = "pre-fix"/"post-fix"（RC2 跨档可比性的分组标签——不同
      几何两档不做网格归因，正交性边界）。
    """
    v: Mapping[str, Any] = verdict if isinstance(verdict, Mapping) else {}
    s: Mapping[str, Any] = stats if isinstance(stats, Mapping) else {}
    m: Mapping[str, Any] = mesh if isinstance(mesh, Mapping) else {}
    ou, ou_src = _over_unity_cnt(v, s)
    eps_med = s.get("eps_eff_med")
    eps_src = "stats"
    if eps_med is None:
        gates = v.get("gates")
        if isinstance(gates, Mapping):
            g1 = gates.get("G1")
            if isinstance(g1, Mapping) and g1.get("observed_eps_eff") is not None:
                eps_med = g1["observed_eps_eff"]
                eps_src = "gates.G1"
    g0 = v.get("g0_status")
    if g0 is None and isinstance(v.get("g0_anchor"), Mapping):
        g0 = v["g0_anchor"].get("status")
    dt_fs = m.get("dt_fs")
    window_ps = None
    if nrts is not None and isinstance(dt_fs, (int, float)) and dt_fs > 0:
        window_ps = int(nrts) * float(dt_fs) / 1000.0
    return {
        "name": name,
        "verdict": v.get("verdict"),
        "not_judged": verdict is None,
        "g0_status": g0,
        "s0_status": v.get("s0_structure", {}).get("status")
        if isinstance(v.get("s0_structure"), Mapping) else None,
        "s0_failed": list(v.get("s0_structure", {}).get("failed") or [])
        if isinstance(v.get("s0_structure"), Mapping) else [],
        "port_structure_suspect": v.get("port_structure_suspect") is True,
        "truncation_suspect": v.get("truncation_suspect") is True,
        "g1_status": _gate_status(v, "G1"),
        "g2_status": _gate_status(v, "G2"),
        "g3_status": _gate_status(v, "G3"),
        "over_unity_cnt": ou,
        "over_unity_cnt_source": ou_src,
        "eps_eff_med": eps_med,
        "eps_eff_med_source": eps_src,
        "eps_eff_closed": None,
        "eps_eff_rel": None,
        "f_valley_ghz": s.get("f_valley_ghz"),
        "valley_depth_db": s.get("valley_depth_db"),
        "beta_r2_min": s.get("beta_r2_min"),
        "beta_port_disagreement_med": s.get("beta_port_disagreement_med"),
        "zl_re_med_ports": s.get("zl_re_med_ports"),
        "passivity_max": s.get("passivity_max"),
        "plane_dist_ok": s.get("plane_dist_ok"),
        "audit_ok": s.get("audit_ok"),
        "n_points_band": s.get("n_points_band"),
        "wall_s": s.get("wall_s"),
        "mesh_base_mm": m.get("base_mm"),
        "mesh_cells": m.get("cells"),
        "dt_fs": dt_fs,
        "nrts": nrts,
        "window_ps": window_ps,
        "geometry": geometry,
        "source": source,
    }


def _factor_status(row: Mapping[str, Any], factor: str) -> str:
    """单档因子状态（预声明规则见模块 docstring；状态词闭集）。"""
    if factor == "RC1_geometry_port_structure":
        if row["port_structure_suspect"]:
            return "implicated"
        if row["s0_status"] == "PASS":
            return "excluded"
        return "unevaluated"
    if factor == "RC3_truncation":
        ou = row["over_unity_cnt"]
        if ou is None:
            return "unevaluated"
        if int(ou) <= 0:
            return "excluded"
        if row["port_structure_suspect"]:
            return "co_present_not_attributed"
        return "implicated"
    if factor == "RC2_mesh_resolution":
        return "indeterminate_per_tier"  # 单档不自证；跨档结论见 pairwise
    raise KeyError(factor)


def _pairwise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同 geometry 标签两档配对（粗→细按 base_mm；缺 base 不同几何不配）。"""
    by_geo: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r["geometry"] and r["mesh_base_mm"] is not None:
            by_geo.setdefault(str(r["geometry"]), []).append(r)
    pairs: list[dict[str, Any]] = []
    for geo, group in by_geo.items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda r: float(r["mesh_base_mm"]),
                         reverse=True)  # 粗在前
        coarse, fine = ordered[0], ordered[1]
        pair: dict[str, Any] = {
            "geometry": geo,
            "coarse": coarse["name"],
            "fine": fine["name"],
            "base_ratio": (float(coarse["mesh_base_mm"])
                           / float(fine["mesh_base_mm"])),
            "cells_ratio": (
                float(coarse["mesh_cells"]) / float(fine["mesh_cells"])
                if coarse["mesh_cells"] and fine["mesh_cells"] else None),
            "window_ratio": (
                float(fine["window_ps"]) / float(coarse["window_ps"])
                if fine["window_ps"] and coarse["window_ps"] else None),
        }
        # RC1 配对（状态词闭集 implicated/excluded/unevaluated）
        cs, fs_ = (_factor_status(coarse, "RC1_geometry_port_structure"),
                   _factor_status(fine, "RC1_geometry_port_structure"))
        if cs == "unevaluated" or fs_ == "unevaluated":
            rc1_pv = "not_observable"
        elif fs_ == "excluded" and cs == "implicated":
            rc1_pv = "cured_by_joint_refinement"
        elif fs_ == "implicated" and cs == "implicated":
            rc1_pv = "not_cured_by_joint_refinement"
        elif fs_ == "implicated" and cs == "excluded":
            rc1_pv = "inverted"  # 精化后新现=数据反常，如实旗标不归因
        else:
            rc1_pv = "absent_both"
        pair["rc1"] = {"coarse": cs, "fine": fs_, "pair_verdict": rc1_pv}
        # RC3 配对（co_present_not_attributed=异常在场但归因被 S0 阻断
        # ——配对语义按"在场"算：在场即未治，归因阻断单列旗标）
        cs3, fs3 = (_factor_status(coarse, "RC3_truncation"),
                    _factor_status(fine, "RC3_truncation"))
        _present = ("implicated", "co_present_not_attributed")
        if cs3 == "unevaluated" or fs3 == "unevaluated":
            rc3_pv = "not_observable"
        elif fs3 == "excluded" and cs3 in _present:
            rc3_pv = "cured_by_joint_refinement"
        elif fs3 in _present and cs3 in _present:
            rc3_pv = "not_cured_by_joint_refinement"
        elif fs3 in _present and cs3 == "excluded":
            rc3_pv = "inverted"  # 精化后新现=数据反常，如实旗标不归因
        else:
            rc3_pv = "absent_both"
        pair["rc3"] = {"coarse": cs3, "fine": fs3, "pair_verdict": rc3_pv,
                       "fine_attribution_blocked_by_rc1":
                           fs3 == "co_present_not_attributed",
                       "coarse_attribution_blocked_by_rc1":
                           cs3 == "co_present_not_attributed"}
        pairs.append(pair)
    return pairs


def decompose_factors(records: Mapping[str, Mapping[str, Any]]
                      ) -> dict[str, Any]:
    """RC1/RC2/RC3 三因子分解（入参=build_tier_record 产出 name→row）。

    返回 {factors: {name: {RC1/RC2/RC3: 状态词}}} + {pairs: 跨档配对}
    （RC2 网格归因只存在于 pairs——单档不自证；pair 结论含联合精化
    边界标注，见模块 docstring 正交性边界条）。
    """
    rows = [dict(r) for r in records.values()]
    factors = {
        r["name"]: {
            "RC1_geometry_port_structure": _factor_status(
                r, "RC1_geometry_port_structure"),
            "RC2_mesh_resolution": _factor_status(r, "RC2_mesh_resolution"),
            "RC3_truncation": _factor_status(r, "RC3_truncation"),
        }
        for r in rows
    }
    pairs = _pairwise(rows)
    rc2: list[str] = [p["rc1"]["pair_verdict"] for p in pairs
                      if p["rc1"]["pair_verdict"] != "not_observable"]
    rc3: list[str] = [p["rc3"]["pair_verdict"] for p in pairs
                      if p["rc3"]["pair_verdict"] != "not_observable"]
    if "cured_by_joint_refinement" in rc2:
        rc2_conclusion = "mesh_dominant_suspect"
    elif "not_cured_by_joint_refinement" in rc2:
        rc2_conclusion = "mesh_excluded_persists"
    elif "inverted" in rc2:
        rc2_conclusion = "inverted_refinement_suspect"
    else:
        rc2_conclusion = "not_observable"
    if "cured_by_joint_refinement" in rc3:
        rc3_conclusion = "window_dominant_suspect"
    elif "not_cured_by_joint_refinement" in rc3:
        rc3_conclusion = "window_mesh_joint_refinement_not_cured"
    elif "inverted" in rc3:
        rc3_conclusion = "inverted_refinement_suspect"
    else:
        rc3_conclusion = "not_observable"
    geos = {str(r["geometry"]) for r in rows if r["geometry"]}
    return {
        "factors": factors,
        "pairs": pairs,
        "conclusions": {
            "RC2_mesh": rc2_conclusion,
            "RC3_truncation": rc3_conclusion,
            "geometry_labels_present": sorted(geos),
            "orthogonality_caveat": (
                "现存对照=网格+窗联合精化（base 2.42×∧窗 2.0× 同变）；"
                "pair 结论只支持'联合精化不治/治了'，完全正交归因需"
                "单因子隔离跑（同 mesh 换窗 / 同窗换 mesh）"),
        },
    }


def compare_tiers(
    records: Mapping[str, Mapping[str, Any]],
    *,
    closed_eps_eff: float | None = None,
) -> dict[str, Any]:
    """双档（或多档）对照表（行=档位观测面+三因子状态；缺键 None 透传）。

    - closed_eps_eff：闭式锚（调用方经判据单源 closed_form_anchor() 现
      算传入——本服务不重算闭式，零数值内核复制）；行内 eps_eff_closed
      缺时以此补，eps_eff_rel=|med−closed|/closed 两值齐才算（缺=None）。
    - verdict 缺失/未判档如实透传（not_judged=True、verdict=None）——
      INCOMPLETE/未判**永不升格**为 AGREE/PASS（如实不凑）。
    """
    rows: dict[str, dict[str, Any]] = {}
    for name, rec in records.items():
        row = dict(rec)
        if row.get("eps_eff_closed") is None and closed_eps_eff is not None:
            row["eps_eff_closed"] = float(closed_eps_eff)
        med, clo = row.get("eps_eff_med"), row.get("eps_eff_closed")
        if isinstance(med, (int, float)) and isinstance(clo, (int, float)) \
                and float(clo) != 0.0:
            row["eps_eff_rel"] = abs(float(med) - float(clo)) / float(clo)
        rows[name] = row
    summary = {
        "n_tiers": len(rows),
        "n_judged": sum(1 for r in rows.values() if not r["not_judged"]),
        "verdicts": {n: r["verdict"] for n, r in rows.items()},
        "n_incomplete": sum(
            1 for r in rows.values() if r["verdict"] == "INCOMPLETE"),
        "incomplete_passthrough_note": (
            "INCOMPLETE/未判档原样透传，不升格不凑绿（#122）"),
    }
    return {
        "tiers": rows,
        "summary": summary,
        "rc_matrix": decompose_factors(rows),
    }
