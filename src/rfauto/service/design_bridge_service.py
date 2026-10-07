"""run→design JSON 桥（SO-审查 §6③ A8 引导件 mini，2026-10-05）。

补 SO 走查 A8 断点："kicad pcb 无'从 run 最优参数→design JSON'桥"——
读 run 目录（meta.json + recipe.snapshot.yaml）的模型名与设计参数，
经 layout_generator 注册表（版图艺术层，参数语义与模板 physics_roles
同源，#154）生成 2D 线艺，再转 PCBDesign schema JSON 草稿，供
`rfauto kicad pcb` → `rfauto kicad drc` 链直接消费。

铁律 7：本模块零新物理数值——几何全部由 run 参数/显式覆盖派生；
馈线宽缺省档走 core/synthesis.nominal_width_mm 单源（#1c）；缺必需
参数时如实报缺失清单，不臆造默认值。
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

#: 桥产物 schema 标识。
DESIGN_BRIDGE_SCHEMA = "rfauto-design-bridge-v1"

#: recipe `model` → 版图生成器注册名（确定性映射；未收录模型走 --kind 显式）。
MODEL_TO_KIND: dict[str, str] = {
    "mline": "microstrip",
    "patch_antenna": "patch_antenna",
    "hairpin": "hairpin_bpf",
    "hairpin_alt": "hairpin_bpf",
}

#: model 设计参数 → 生成器参数名映射（同名同义直配，#154 跨面口径）。
_MODEL_PARAM_MAP: dict[str, dict[str, str | None]] = {
    "mline": {"w_mm": "width_mm", "line_len_mm": "length_mm"},
    "patch_antenna": {
        "patch_w_mm": "patch_width_mm",
        "patch_len_mm": "patch_length_mm",
        # feed_offset_mm 不进 2D 艺术层语义（生成器走底馈居中）——如实不映射
        "feed_offset_mm": None,
    },
    "hairpin": {
        "order": "order", "w_mm": "w_mm", "arm_len_mm": "arm_len_mm",
        "arm_gap_mm": "arm_gap_mm", "gap_mm": "gap_mm",
        "tap_frac": "tap_frac", "f0_ghz": "f0_ghz", "substrate": "stackup",
    },
    "hairpin_alt": {
        "order": "order", "w_mm": "w_mm", "arm_len_mm": "arm_len_mm",
        "arm_gap_mm": "arm_gap_mm", "gap_mm": "gap_mm",
        "tap_frac": "tap_frac", "f0_ghz": "f0_ghz", "substrate": "stackup",
    },
}

#: 生成器必需参数（映射+覆盖仍缺时如实报清单，不臆造）。
_KIND_REQUIRED: dict[str, tuple[str, ...]] = {
    "microstrip": ("width_mm", "length_mm"),
    "patch_antenna": ("patch_width_mm", "patch_length_mm", "feed_width_mm",
                      "feed_length_mm"),
    "hairpin_bpf": ("order", "arm_len_mm", "arm_gap_mm", "gap_mm",
                    "tap_frac"),
}

#: 二选一组（组内全备即可）：hairpin_bpf 线宽缺省档走综合单源，
#: 须给 w_mm 或（f0_ghz+stackup）其一；两者皆缺如实报，不臆造几何。
_KIND_REQUIRED_ALTERNATES: dict[str, tuple[frozenset[str], ...]] = {
    "hairpin_bpf": (frozenset({"w_mm"}),
                    frozenset({"f0_ghz", "stackup"})),
}


def _missing_params(kind: str, params: Mapping[str, Any]) -> list[str]:
    """必需参数缺口清单（二选一组=全部备选组都缺才记缺，报文含口径）。"""
    missing = [k for k in _KIND_REQUIRED.get(kind, ()) if k not in params]
    groups = _KIND_REQUIRED_ALTERNATES.get(kind, ())
    if groups and all(
            all(k not in params for k in group) for group in groups):
        missing.append(" 或 ".join("+".join(sorted(g)) for g in groups))
    return missing


def _flatten_params(raw: Any) -> dict[str, Any]:
    """recipe params 展平：{k: {value, unit}} → {k: value}；标量直通。"""
    out: dict[str, Any] = {}
    if not isinstance(raw, Mapping):
        return out
    for key, val in raw.items():
        if isinstance(val, Mapping) and "value" in val:
            out[str(key)] = val["value"]
        else:
            out[str(key)] = val
    return out


def _bbox(points: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def layout_to_pcb_design(layout: Any) -> dict[str, Any]:
    """Layout（版图交换单元）→ PCBDesign schema 兼容 dict。

    板框多边形（edge 层）→ board_size（包围盒）+ edge_cuts 点列；
    折线路径拆成 start/end 两点走线段（PCBDesign Trace 是两点段）；
    圆→circle 焊盘；过孔直配。
    """
    from rfauto.adapters.layout_generator import (
        LayoutCircle,
        LayoutPath,
        LayoutPolygon,
        LayoutVia,
    )

    board_size = [50.0, 30.0]
    edge_cuts: list[list[float]] = []
    traces: list[dict[str, Any]] = []
    pads: list[dict[str, Any]] = []
    vias: list[dict[str, Any]] = []
    for item in layout.items:
        if isinstance(item, LayoutPolygon):
            pts = [[float(x), float(y)] for x, y in item.points]
            x0, y0, x1, y1 = _bbox(pts)
            board_size = [round(x1 - x0, 6), round(y1 - y0, 6)]
            edge_cuts = pts
        elif isinstance(item, LayoutPath):
            pts = [(float(x), float(y)) for x, y in item.points]
            for (ax, ay), (bx, by) in itertools.pairwise(pts):
                traces.append({
                    "start": [round(ax, 6), round(ay, 6)],
                    "end": [round(bx, 6), round(by, 6)],
                    "width": round(float(item.width_mm), 6),
                    "layer": item.layer,
                })
        elif isinstance(item, LayoutCircle):
            pads.append({
                "position": [round(float(item.center[0]), 6),
                             round(float(item.center[1]), 6)],
                "size": [round(float(item.radius_mm) * 2.0, 6),
                         round(float(item.radius_mm) * 2.0, 6)],
                "shape": "circle",
                "layer": item.layer,
            })
        elif isinstance(item, LayoutVia):
            vias.append({
                "position": [round(float(item.position[0]), 6),
                             round(float(item.position[1]), 6)],
                "drill": round(float(item.drill_diameter_mm), 6),
                "pad": round(float(item.pad_diameter_mm), 6),
                "layers": [item.pad_layer, "B.Cu"],
            })
    return {
        "board_size": board_size,
        "traces": traces,
        "vias": vias,
        "pads": pads,
        "edge_cuts": edge_cuts,
    }


def run_to_design_json(
    run_dir: str | Path,
    *,
    kind: str | None = None,
    output: str | Path | None = None,
    param_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """run 目录 → PCBDesign JSON 草稿（`rfauto kicad design-from-run` 服务面）。

    Args:
        run_dir: run 目录（须含 meta.json 与 recipe.snapshot.yaml）。
        kind: 显式版图生成器注册名（缺省按 recipe `model` 映射）。
        output: design JSON 落盘路径（缺省只回信封不落盘）。
        param_overrides: 显式参数覆盖（补映射缺口，如 patch 的
            feed_length_mm；同名键覆盖映射值）。

    Returns:
        ok 信封 {schema, run_dir, model, kind, params, design, output?,
        next_steps}；输入缺失/映射缺参走 error_envelope（缺参如实列清单）。
    """
    rd = Path(run_dir)
    meta_path = rd / "meta.json"
    recipe_path = rd / "recipe.snapshot.yaml"
    if not meta_path.is_file():
        return error_envelope([f"run meta.json 不存在: {meta_path}"])
    if not recipe_path.is_file():
        return error_envelope([f"recipe 快照不存在: {recipe_path}"
                               "（run 未落配方快照，无法反推设计参数）"])
    try:
        import yaml

        recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return error_envelope([f"recipe 快照解析失败: {exc}"])
    model = str(recipe.get("model") or "")
    if not model:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            model = str(meta.get("model") or "")
        except Exception:
            model = ""
    if not model:
        return error_envelope(["recipe 快照与 meta.json 均无 model 字段"])

    resolved_kind = kind or MODEL_TO_KIND.get(model)
    if not resolved_kind:
        return error_envelope(
            [f"模型 {model!r} 无确定性版图映射；已知: "
             f"{sorted(MODEL_TO_KIND)}（或用 --kind 显式给生成器注册名）"])

    params = _flatten_params(recipe.get("params"))
    mapping = _MODEL_PARAM_MAP.get(model, {})
    gen_params: dict[str, Any] = {}
    for src_key, dst_key in mapping.items():
        if dst_key is None:
            continue
        if src_key in params:
            gen_params[dst_key] = params[src_key]
    for key, val in dict(param_overrides or {}).items():
        gen_params[key] = val

    from rfauto.adapters.layout_generator import LAYOUT_GENERATORS

    if resolved_kind not in LAYOUT_GENERATORS:
        return error_envelope(
            [f"未知版图生成器: {resolved_kind!r}；可用: "
             f"{sorted(LAYOUT_GENERATORS)}"])
    missing = _missing_params(resolved_kind, gen_params)
    if missing:
        return error_envelope(
            [f"生成器 {resolved_kind} 缺必需参数: {missing}"
             "（用 --param 名=值 显式补；桥不臆造默认几何，铁律 7）"])

    from rfauto.adapters.layout_generator import generate_layout

    gen_params.setdefault("name", f"{rd.name}_{resolved_kind}")
    try:
        layout = generate_layout(resolved_kind, gen_params)
    except (KeyError, ValueError, TypeError) as exc:
        return error_envelope([f"版图生成失败: {type(exc).__name__}: {exc}"])
    design = layout_to_pcb_design(layout)
    sections: dict[str, Any] = {
        "schema": DESIGN_BRIDGE_SCHEMA,
        "run_dir": str(rd),
        "model": model,
        "kind": resolved_kind,
        "params": gen_params,
        "design": design,
        "next_steps": [
            "rfauto kicad pcb <design.json> -o <输出.kicad_pcb>",
            "rfauto kicad drc <输出.kicad_pcb>（DRC/RF 规则门禁）",
        ],
    }
    if output is not None:
        out_p = Path(output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(design, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        sections["output"] = str(out_p)
    return ok_envelope(**sections)
