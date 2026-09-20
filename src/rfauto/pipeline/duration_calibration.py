"""openEMS 历史实耗标定档案装载与覆盖面统计。

:mod:`quota_guard` 的
:class:`~rfauto.pipeline.quota_guard.RobustDurationPredictor` 是纯确定性内核；
本模块负责唯一允许 IO 的一部分——把 runs/ 下可读的 openEMS 历史实耗数据
装配成 :class:`~rfauto.pipeline.quota_guard.DurationSample` 标定档（family），
并给出覆盖面（coverage ratio）实测统计。

标定档（family）划分口径：按模板家族分档，不同几何模板的求解机时不具可比
性（验收教训：受控同模板 mline 序列 LOO_max=22.4%，跨模板混池
281%）：

* ``mline_benchmark``——runs/benchmark/mline_mesh_convergence.json 受控同模板
  网格序列（4 点）；
* ``ratrace``——runs/ratrace_arbitration/openems_convergence.json（0.2mm 精算
  1 点）+ runs/ratrace_smoke/pt8|pt9 日志 solve_s（0.4mm 冒烟 2 点，
  受并发污染的次级样本，source 中如实标注）。

域体积/网格特征从各 run 的渲染脚本 simulation.py 解析（与
scripts/cost_report.py 同一口径）；缺文件的源按 best-effort 跳过并记录在
``skipped``（#105：数据装配不得成为主路径故障点）。

另设 :func:`load_duration_sample_json`：直接装载
duration_sample 同构 schema 归档（``nr_ts_cap_declared``/``hit_nr_ts_cap``
停机机制面 -> DurationSample 的 ``nrts_limit``/``stop_reason`` 特征字段），
供 NrTS/stop_reason 特征就绪后的重训并入训练集。

分层：pipeline 层，仅依赖标准库 + 同层 quota_guard。无网络、无求解器调用。
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from rfauto.pipeline.quota_guard import (
    MIN_CALIBRATION_SAMPLES,
    STOP_REASON_ENERGY,
    STOP_REASON_NRTS_CAP,
    STOP_REASONS,
    DurationSample,
    RobustDurationPredictor,
)

__all__ = [
    "DURATION_SAMPLE_SCHEMA_PREFIX",
    "FAMILY_MLINE",
    "FAMILY_RATRACE",
    "calibration_report",
    "load_duration_sample_json",
    "load_openems_duration_samples",
]

#: 受控同模板 mline 网格收敛序列（相对 runs/ 的路径）。
MLINE_CONVERGENCE_REL = "benchmark/mline_mesh_convergence.json"
#: ratrace 仲裁精算实耗（相对 runs/ 的路径）。
RATRACE_CONVERGENCE_REL = "ratrace_arbitration/openems_convergence.json"
#: duration_sample 同构 schema 前缀（"同构可并入训练集"）。
#: 实档：runs/quota_guard/ratrace_duration_samples.json（14 样本档）、
#: runs/ratrace_03mm_sample/duration_sample.json。schema 缺省按同构宽容
#: 装载；schema 存在且前缀不符时整文件记 skipped（不猜格式）。
DURATION_SAMPLE_SCHEMA_PREFIX = "rfauto.quota_guard.ratrace_duration_samples"
#: ratrace 冒烟日志（0.4mm，次级样本）。
RATRACE_SMOKE_LOGS: tuple[tuple[str, float], ...] = (
    ("ratrace_smoke/pt8/smoke_pt8.log", 0.4),
    ("ratrace_smoke/pt9/smoke_pt9.log", 0.4),
)

FAMILY_MLINE = "mline_benchmark"
FAMILY_RATRACE = "ratrace"

_RATRACE_SIM_REL = "ratrace_arbitration/mesh_0p2mm/p1/simulation.py"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _solve_s_from_log(path: Path) -> float | None:
    """日志中形如 ``solve_s=NNN`` 的最大值（与 cost_report 同口径）。"""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    values = [float(v) for v in re.findall(r"solve_s\s*=\s*([0-9]+(?:\.[0-9]+)?)", text)]
    return max(values) if values else None


def _sim_geometry(sim_path: Path) -> dict[str, float] | None:
    """从 openEMS 渲染脚本解析网格与域体积（与 cost_report 同口径）。"""
    if not sim_path.is_file():
        return None
    text = sim_path.read_text(encoding="utf-8", errors="replace")

    def number(pattern: str, default: float | None = None) -> float | None:
        match = re.search(pattern, text, re.M)
        return float(match.group(1)) if match else default

    base = number(r"^BASE\s*=\s*([0-9.eE+-]+)")
    board = number(r"^BOARD\s*=\s*([0-9.eE+-]+)")
    h_sub = number(r"^H_SUB\s*=\s*([0-9.eE+-]+)")
    if base is None or board is None or h_sub is None:
        return None
    air_side = number(r"^AIR_SIDE\s*=\s*([0-9.eE+-]+)", 0.0) or 0.0
    air_top = number(r"^AIR_TOP\s*=\s*([0-9.eE+-]+)", 0.0) or 0.0
    dom_xy_m = 2.0 * (board + air_side)
    domain_volume_mm3 = (dom_xy_m * 1e3) ** 2 * ((h_sub + air_top) * 1e3)
    return {"mesh_mm": base * 1e3, "domain_volume_mm3": domain_volume_mm3}


def load_openems_duration_samples(runs_dir: str | Path) -> dict[str, Any]:
    """装载 runs/ 历史 openEMS 实耗 -> 按模板家族分档的标定档。

    返回 ``{"families": {family: [DurationSample, ...]}, "provenance": [...],
    "skipped": [...]}``。缺文件的源跳过并记入 ``skipped``（best-effort）。
    """
    runs = Path(runs_dir)
    families: dict[str, list[DurationSample]] = {FAMILY_MLINE: [], FAMILY_RATRACE: []}
    provenance: list[str] = []
    skipped: list[str] = []

    # 1) 受控 mline 网格序列（同模板，验收口径档）
    conv = _read_json(runs / MLINE_CONVERGENCE_REL)
    if conv is None:
        skipped.append(MLINE_CONVERGENCE_REL)
    else:
        provenance.append(MLINE_CONVERGENCE_REL)
        for entry in conv.get("entries", []):
            mesh = float(entry["mesh_mm"])
            wall = float(entry["wall_s"])
            sim = (
                runs / "benchmark" / "mline_mauto" / "simulation.py"
                if mesh <= 0.0
                else runs / "benchmark" / f"mline_m{mesh:g}" / "simulation.py"
            )
            geom = _sim_geometry(sim)
            if geom is None:
                skipped.append(str(sim.relative_to(runs)))
                continue
            families[FAMILY_MLINE].append(
                DurationSample(
                    mesh_mm=mesh if mesh > 0 else geom["mesh_mm"],
                    solve_s=wall,
                    domain_volume_mm3=geom["domain_volume_mm3"],
                    n_excitations=1,
                    source=str(sim.relative_to(runs)),
                )
            )

    # 2) ratrace 档：0.2mm 精算 + 冒烟次级样本
    ratrace = _read_json(runs / RATRACE_CONVERGENCE_REL)
    ratrace_geom = _sim_geometry(runs / _RATRACE_SIM_REL)
    if ratrace is None or ratrace_geom is None:
        skipped.append(RATRACE_CONVERGENCE_REL)
    else:
        provenance.append(RATRACE_CONVERGENCE_REL)
        wall_02 = ratrace.get("solve_s_0p2mm")
        if wall_02:
            families[FAMILY_RATRACE].append(
                DurationSample(
                    mesh_mm=0.2,
                    solve_s=float(wall_02),
                    domain_volume_mm3=ratrace_geom["domain_volume_mm3"],
                    n_excitations=4,
                    source=RATRACE_CONVERGENCE_REL,
                )
            )
    for log_rel, mesh in RATRACE_SMOKE_LOGS:
        wall = _solve_s_from_log(runs / log_rel)
        if wall is None or ratrace_geom is None:
            skipped.append(log_rel)
            continue
        provenance.append(log_rel)
        families[FAMILY_RATRACE].append(
            DurationSample(
                mesh_mm=mesh,
                solve_s=wall,
                domain_volume_mm3=ratrace_geom["domain_volume_mm3"],
                n_excitations=4,
                source=f"{log_rel} (smoke, 并发污染次级样本)",
            )
        )

    return {
        "families": families,
        "provenance": provenance,
        "skipped": skipped,
    }


def _positive_float(value: Any) -> float | None:
    """Finite strictly-positive float or None（非数/非正/缺失一律 None）。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0.0 else None


def _stop_reason_from_entry(entry: dict[str, Any]) -> str:
    """样本级停机原因：显式 ``stop_reason`` 优先，其次 ``hit_nr_ts_cap`` 三值。

    归档口径（ratrace_duration_samples.json field_notes）：``hit_nr_ts_cap``
    True = 实测迭代数==声明上限被截停（nrts_cap）；False = 能量判据提前停机
    （energy）；None/缺省 = 无 stdout 尾巴归档、机制未知（""，旧样本缺省）。
    未识别的显式值按未知处理（特征层 one-hot 全中性），不抛错（#105）。
    """
    raw = entry.get("stop_reason")
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in STOP_REASONS:
            return normalized
    hit = entry.get("hit_nr_ts_cap")
    if isinstance(hit, bool):
        return STOP_REASON_NRTS_CAP if hit else STOP_REASON_ENERGY
    return ""


def load_duration_sample_json(path: str | Path) -> dict[str, Any]:
    """装载 duration_sample 同构 schema 归档 -> :class:`DurationSample` 档。

    消费该归档形态（``runs/quota_guard/ratrace_duration_samples.json``
    14 样本档与 ``runs/ratrace_03mm_sample/duration_sample.json`` 同构；
    "同构可并入训练集"）。逐条字段映射：

    * ``wall_s`` -> ``solve_s``、``base_mm``（缺省回退 ``mesh_mm``）->
      ``mesh_mm``——两者必需，缺/非法该条记入 ``skipped``；
    * ``nr_ts_cap_declared`` -> ``nrts_limit``（缺/null/非法 -> 0 未申报）；
    * ``stop_reason``（显式，优先）或 ``hit_nr_ts_cap`` 三值 -> ``stop_reason``
      枚举（True->nrts_cap / False->energy / None->""）；
    * ``adapter`` -> ``solver``（缺省 openems）、``template``/``grid_tier``/
      ``n_excitations``（缺省 1）/``domain_volume_mm3``（缺省 1.0）/``source``
      直传（缺省向后兼容）。

    旧样本缺新字段按缺省/one-hot 中性装载，不炸旧数据；内部矛盾条目如实
    skip（触顶 ``hit=True`` 而无声明上限——机制已知但无法特征化，不猜测入集，
    #105 best-effort）。返回 ``{"samples": [...], "provenance": [...],
    "skipped": [...]}``，样本不按 family 预分组（同构档跨模板，分组留给
    消费方按 ``template``/``tier_key`` 处理）。零求解器调用、无网络。
    """
    file_path = Path(path)
    label = file_path.name
    payload = _read_json(file_path)
    if payload is None:
        return {"samples": [], "provenance": [], "skipped": [str(file_path)]}

    schema = payload.get("schema")
    if isinstance(schema, str) and not schema.startswith(
        DURATION_SAMPLE_SCHEMA_PREFIX
    ):
        return {
            "samples": [],
            "provenance": [],
            "skipped": [f"{label}: schema mismatch {schema!r}"],
        }

    samples: list[DurationSample] = []
    skipped: list[str] = []
    for index, entry in enumerate(payload.get("samples", [])):
        if not isinstance(entry, dict):
            skipped.append(f"{label}#{index}: non-dict entry")
            continue
        tag = f"{label}#{entry.get('id') or index}"
        wall = _positive_float(entry.get("wall_s"))
        mesh = _positive_float(entry.get("base_mm") or entry.get("mesh_mm"))
        if wall is None or mesh is None:
            skipped.append(f"{tag}: 缺 wall_s/base_mm 或非法")
            continue
        cap = _positive_float(entry.get("nr_ts_cap_declared"))
        nrts_limit = int(cap) if cap is not None else 0
        stop_reason = _stop_reason_from_entry(entry)
        if stop_reason == STOP_REASON_NRTS_CAP and nrts_limit <= 0:
            skipped.append(f"{tag}: 触顶样本缺 nr_ts_cap_declared")
            continue
        n_exc_raw = entry.get("n_excitations")
        n_exc = 1.0 if n_exc_raw is None else _positive_float(n_exc_raw)
        if n_exc is None:
            skipped.append(f"{tag}: n_excitations 非法")
            continue
        volume_raw = entry.get("domain_volume_mm3")
        volume = 1.0 if volume_raw is None else _positive_float(volume_raw)
        if volume is None:
            skipped.append(f"{tag}: domain_volume_mm3 非法")
            continue
        samples.append(
            DurationSample(
                mesh_mm=mesh,
                solve_s=wall,
                domain_volume_mm3=volume,
                n_excitations=max(1, round(n_exc)),
                nrts_limit=nrts_limit,
                stop_reason=stop_reason,
                solver=str(entry.get("adapter") or "openems"),
                template=str(entry.get("template") or ""),
                grid_tier=str(entry.get("grid_tier") or ""),
                source=str(entry.get("source") or tag),
            )
        )

    return {
        "samples": samples,
        "provenance": [str(file_path)],
        "skipped": skipped,
    }


def calibration_report(runs_dir: str | Path) -> dict[str, Any]:
    """分档 + 混池的稳健预测器标定摘要与覆盖面统计（JSON 原生）。

    每档独立拟合 :class:`RobustDurationPredictor`（稳健语义：样本不足
    或 LOO 不可信 -> status="unknown" + 保守上界），另给混池结果作对照——
    跨模板混池预计落入 unknown（这正是分档口径的实证依据）。
    """
    loaded = load_openems_duration_samples(runs_dir)
    families: dict[str, Any] = {}
    for family, samples in loaded["families"].items():
        predictor = RobustDurationPredictor.fit(samples)
        summary = predictor.summary()
        summary["n_samples_below_min"] = (
            len(samples) < MIN_CALIBRATION_SAMPLES
        )
        summary["sample_sources"] = [s.source for s in samples]
        families[family] = summary

    pooled_samples = [
        s for samples in loaded["families"].values() for s in samples
    ]
    pooled = RobustDurationPredictor.fit(pooled_samples).summary()

    return {
        "generated_by": "rfauto.pipeline.duration_calibration.calibration_report",
        "families": families,
        "pooled": pooled,
        "provenance": loaded["provenance"],
        "skipped": loaded["skipped"],
    }
