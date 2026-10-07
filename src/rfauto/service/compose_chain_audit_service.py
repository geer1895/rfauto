"""compose_chain_audit_service：模板积木级联端口兼容审计（XC 模板积木 v1 的 service 面）。

规划期审计：给定**任意长度级联链**（chain=[{template, params?}...]），
逐实例调契约 layout（identity frame，免摆位），自动配对相邻实例的
outlet→inlet junction，出 P2/P3/P5 同容差的完全兼容报告 + 暴露端口
方案（首 inlet/末 outlet，D4 发射器支持域）+ 全链 substrate 一致性
（D6）/边界类一致性（D5）预检。

与 compose_service（DP-8 全量组合器）的分工：组合器做摆位求解+守卫
fail-fast 出渲染文本；本面**不摆位不渲染**，只回答"这条链的端口面
兼容吗"——跑组合器之前的快速裁决面。内核在 core/compose/cascade_audit
（P2/P3/P5 容差单源自 layout_netlist import，禁双头）。

payload 契约::

    {"chain": [{"template": "msl_siw_taper", "params": {...}?}, ...],
     "band_ghz": [lo, hi],
     "mesh_resolution_mm": 0.5,        # 契约 layout 的 base_m 来源
     "substrate": {"h_mm", "er", "tan_d" | er/tan_d 二选一按契约}?,
         # 缺省取首实例契约声明；给定时逐实例 D6 比对
     "connections"?: 兼容字段（现役链式自动配对，显式连接走组合器）}

verdict：任一 junction/预检 mismatch → ``issues``；有 unknown（契约缺/
方向不唯一）→ ``attention``；否则 ``clean``。
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from rfauto.core.compose.cascade_audit import (
    audit_junction,
    chain_axis_of,
    chain_endpoints,
)
from rfauto.service.envelope import error_envelope, ok_envelope

_SOURCE = "rfauto.service.compose_chain_audit_service"
_EMITTABLE_PORT_TYPES = ("lumped", "msl")
"""D4 发射器支持域（core/compose/layout_netlist._emit_primitive 同口径）。"""


def _contracts() -> dict[str, dict[str, Any]]:
    """组合契约注册表（惰性导入 adapters，compose_service 同款）。"""
    from rfauto.adapters.oe_templates.render_siw import COMPOSE_CONTRACTS

    return dict(COMPOSE_CONTRACTS)


def _instance_layout(template: str, params: dict[str, Any] | None,
                     band_ghz: tuple[float, float], base_m: float,
                     h_m: float) -> dict[str, Any]:
    """单实例契约 layout（identity frame）。契约缺失/守卫拒绝如实上抛。"""
    contracts = _contracts()
    entry = contracts.get(template)
    if entry is None:
        raise KeyError(f"模板 {template!r} 无组合契约"
                       f"（可用: {sorted(contracts)}）")
    fn = entry["layout"]
    return fn(dict(params or {}), band_ghz, base_m, h_m, (0.0, 0.0, False))


def compose_chain_audit(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """级联端口兼容审计（JSON 进出薄面；程序性入参错转 ok=False）。"""
    payload = dict(payload or {})
    chain = payload.get("chain")
    band = payload.get("band_ghz")
    mesh = payload.get("mesh_resolution_mm")
    if not isinstance(chain, list) or len(chain) < 1:
        return error_envelope(["chain 必须为非空列表（[{template, params?}...]）"])
    if not isinstance(band, (list, tuple)) or len(band) != 2:
        return error_envelope(["band_ghz 必须为 [lo, hi]"])
    if mesh is None:
        return error_envelope(
            ["mesh_resolution_mm 必给（契约 layout "
                                        "base_m 来源，过孔分辨守卫消费）"],
        )
    try:
        band_t = (float(band[0]), float(band[1]))
        base_m = float(mesh) * 1e-3
    except (TypeError, ValueError) as exc:
        return error_envelope([f"band/mesh 入参非法: {exc}"])

    layouts: list[dict[str, Any]] = []
    instances: list[dict[str, Any]] = []
    unknown_rows: list[dict[str, Any]] = []
    substrate_declared = payload.get("substrate")
    for i, item in enumerate(chain):
        if not isinstance(item, dict) or not item.get("template"):
            return error_envelope([f"chain[{i}] 缺 template 键"])
        tid = str(item["template"])
        try:
            lay = _instance_layout(tid, item.get("params"), band_t, base_m,
                                   float((substrate_declared or {}).get(
                                       "h_mm", 0.508e-3) or 0.508e-3))
        except KeyError as exc:
            unknown_rows.append({"instance": tid, "reason": str(exc)})
            continue
        except (TypeError, ValueError) as exc:
            unknown_rows.append({"instance": tid,
                                 "reason": f"{type(exc).__name__}: {exc}"})
            continue
        layouts.append(lay)
        instances.append({"index": i, "template": tid,
                          "bc_compat": lay.get("bc_compat"),
                          "substrate": lay.get("substrate")})

    rows: list[dict[str, Any]] = []
    mismatches = 0
    for a, b in pairwise(layouts):
        pins_a, pins_b = a["pins"], b["pins"]
        axis_a = chain_axis_of(pins_a)
        axis_b = chain_axis_of(pins_b)
        if axis_a is None or axis_b is None or axis_a != axis_b:
            rows.append({"junction": "auto-pair", "verdict": "unknown",
                         "reason": f"主轴不唯一或不一致（{axis_a!r} vs "
                                   f"{axis_b!r}）——链式配对不适用，显式"
                                   " connections 走组合器"})
            continue
        out_a = chain_endpoints(pins_a, axis_a)[1]
        in_b = chain_endpoints(pins_b, axis_b)[0]
        if len(out_a) != 1 or len(in_b) != 1:
            rows.append({"junction": "auto-pair", "verdict": "unknown",
                         "reason": f"端点候选不唯一（outlet={out_a}，"
                                   f"inlet={in_b}）——显式 connections 走组合器"})
            continue
        pa, pb = pins_a[out_a[0]], pins_b[in_b[0]]
        j = audit_junction(pa, pb,
                           label=f"{out_a[0]}→{in_b[0]}")
        j["port_types"] = [pa.get("port_type"), pb.get("port_type")]
        if j["verdict"] == "mismatch":
            mismatches += 1
        rows.append(j)

    # 暴露端口方案（链式：首实例 inlet + 末实例 outlet）
    exposed_plan: dict[str, Any] | None = None
    if layouts:
        first_axis = chain_axis_of(layouts[0]["pins"])
        last_axis = chain_axis_of(layouts[-1]["pins"])
        if first_axis and last_axis and first_axis == last_axis:
            in_first = chain_endpoints(layouts[0]["pins"], first_axis)[0]
            out_last = chain_endpoints(layouts[-1]["pins"], last_axis)[1]
            exposed = []
            if len(in_first) == 1:
                exposed.append({"instance_index": 0,
                                "pin": in_first[0],
                                "port_type":
                                    layouts[0]["pins"][in_first[0]].get("port_type")})
            if len(out_last) == 1:
                exposed.append({"instance_index": len(layouts) - 1,
                                "pin": out_last[0],
                                "port_type":
                                    layouts[-1]["pins"][out_last[0]].get("port_type")})
            bad_types = [e for e in exposed
                         if e["port_type"] not in _EMITTABLE_PORT_TYPES]
            exposed_plan = {"exposed": exposed, "n_exposed": len(exposed),
                            "d4_emittable": not bad_types}
            if bad_types:
                mismatches += 1

    # D6/D5 全链一致性预检
    subs = [inst.get("substrate") for inst in instances
            if inst.get("substrate")]
    d6_ok = True
    for s in subs[1:]:
        if s != subs[0]:
            d6_ok = False
    bcs = {str(inst.get("bc_compat")) for inst in instances}
    d5_ok = len(bcs) <= 1
    if substrate_declared is not None and subs:
        key_map = {"h_mm": "h_m"}
        for k, v in substrate_declared.items():
            sk = key_map.get(k, k)
            for s in subs:
                if sk in s:
                    try:
                        sv = float(s[sk])
                        dv = float(v) * (1e-3 if k.endswith("_mm") else 1.0)
                    except (TypeError, ValueError):
                        d6_ok = False
                        continue
                    if abs(sv - dv) > 1e-9 * max(abs(sv), abs(dv), 1.0):
                        d6_ok = False
    if not d6_ok:
        mismatches += 1

    n_unknown = len(unknown_rows) + sum(
        1 for r in rows if r["verdict"] == "unknown")
    if mismatches:
        verdict = "issues"
    elif n_unknown:
        verdict = "attention"
    else:
        verdict = "clean"
    return ok_envelope(
        n_instances=len(layouts),
        instances=instances,
        junctions=rows,
        unknown_instances=unknown_rows,
        exposed_plan=exposed_plan,
        d6_substrate_consistent=d6_ok,
        d5_bc_compat_consistent=d5_ok,
        summary={"n_junctions": len(rows), "n_mismatch": mismatches,
                    "n_unknown": n_unknown},
        verdict=verdict,
        source=_SOURCE,
    )
