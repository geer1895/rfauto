"""DP-8 compose service：模板几何组合的 YAML 进出编排（JSON 进出薄服务）。

分层（core 分层契约/.importlinter）：cli/mcp_server → 本模块 → core.compose.
layout_netlist（纯确定性引擎）+ adapters.openems_templates（组合契约注册表
COMPOSE_CONTRACTS + TEMPLATE_META port_pins schema）。本模块职责：
1. 组合契约/schema 注入（唯一 adapters 依赖点；core 零反向依赖由此保证）；
2. YAML/JSON 文件读写（唯一 IO 面）；
3. 异常到 JSON 的翻译（ok=False + error，不抛出）。

数值/几何/守卫全部在确定性内核（铁律 7）；落盘产物=simulation.py +
compose_meta.json + netlist.yaml 回写副本（provenance 齐套，C5 复验源）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: 首例 netlist（golden fixture 的单一事实源；测试/CLI 示例共用）。
#: 直段解耦口径（criteria.md §1）：过渡=msl_siw_taper 最小结构段
#: （siw_len=2.8mm，藩篱 k=±1 恰装下且板缘-末孔缘距 0.1mm ≫ #349 地板——
#: 2.6mm 会使板缘与孔缘 k·s+d/2 浮点近重合触 #349，实例化时测得即换）。
GOLDEN_NETLISTS: dict[str, dict[str, Any]] = {
    "siw_chain": {
        "schema": "rfauto-netlist-v1",
        "band_ghz": [9.75, 10.25],
        "mesh_resolution_mm": 0.4,
        "substrate": {"h_mm": 0.508, "er": 3.66, "tan_d": 0.0037},
        "instances": [
            {"id": "taper_in", "template": "msl_siw_taper",
             "params": {"siw_len_mm": 2.8}},
            {"id": "run", "template": "siw", "params": {}},
            {"id": "taper_out", "template": "msl_siw_taper",
             "params": {"siw_len_mm": 2.8}},
        ],
        "connections": [
            {"a": ["taper_in", "siw"], "b": ["run", "p1"]},
            {"a": ["run", "p2"], "b": ["taper_out", "siw"]},
        ],
        "exposed_ports": [
            {"instance": "taper_in", "pin": "msl"},
            {"instance": "taper_out", "pin": "msl"},
        ],
        "global_params": {"excite_port": 1, "nrts": 100000},
    },
}


def _contracts() -> dict[str, dict[str, Any]]:
    """组合契约注册表（惰性导入：adapters 依赖只在组合路径出现）。"""
    from rfauto.adapters.openems_templates import COMPOSE_CONTRACTS

    return dict(COMPOSE_CONTRACTS)


def _schema_map() -> dict[str, list[dict[str, Any]]]:
    """port_pins schema 注入（TEMPLATE_META[t]["port_pins"]，opt-in 校验）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_META

    return {t: m["port_pins"] for t, m in TEMPLATE_META.items()
            if m.get("port_pins")}


def list_composable_templates() -> dict[str, Any]:
    """已注册组合契约的模板与 pin schema（opt-in 台账，JSON 进出）。"""
    contracts = _contracts()
    schema = _schema_map()
    templates = []
    for tid in sorted(contracts):
        templates.append({"template": tid,
                          "port_pins": schema.get(tid),
                          "schema_declared": tid in schema})
    return {"ok": True, "result": {"templates": templates,
                                   "n_templates": len(templates)}}


def compose_from_netlist(netlist: dict[str, Any]) -> dict[str, Any]:
    """netlist dict → {ok, result:{script, meta}}（内存态，零落盘）。

    守卫失败/契约缺失经 ComposeError(ValueError) 翻译为 ok=False + error
    文本（报双 pin id+坐标+差值，原文透传不加工）。
    """
    from rfauto.core.compose.layout_netlist import ComposeError, compose_netlist

    try:
        script, meta = compose_netlist(netlist, _contracts(), _schema_map())
    except ComposeError as exc:
        return {"ok": False, "error": str(exc)}
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "result": {"script": script, "meta": meta}}


def compose_from_yaml_file(netlist_path: str | Path) -> dict[str, Any]:
    """netlist YAML 文件 → 组合结果（compose_from_netlist 的文件入口）。"""
    import yaml

    path = Path(netlist_path)
    if not path.exists():
        return {"ok": False, "error": f"netlist 文件不存在: {path}"}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"netlist YAML 不可读: {exc}"}
    if not isinstance(data, dict):
        return {"ok": False,
                "error": f"netlist YAML 必须为映射，得到 {type(data)!r}"}
    return compose_from_netlist(data)


def compose_write(netlist: dict[str, Any], out_dir: str | Path, *,
                  script_name: str = "simulation.py",
                  meta_name: str = "compose_meta.json",
                  netlist_name: str = "netlist.yaml") -> dict[str, Any]:
    """组合并落盘三件套（simulation.py/compose_meta.json/netlist.yaml）。

    落盘目录不存在即创建；同目录同名产物覆盖（组合发射是确定性的，
    同 netlist 重跑逐字节同——覆盖无损）。
    """
    import yaml

    composed = compose_from_netlist(netlist)
    if not composed.get("ok"):
        return composed
    out = Path(out_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / script_name).write_text(composed["result"]["script"],
                                       encoding="utf-8", newline="\n")
        (out / meta_name).write_text(
            json.dumps(composed["result"]["meta"], ensure_ascii=False,
                       indent=1, default=str) + "\n",
            encoding="utf-8", newline="\n")
        (out / netlist_name).write_text(
            yaml.safe_dump(netlist, allow_unicode=True, sort_keys=False),
            encoding="utf-8", newline="\n")
    except OSError as exc:
        return {"ok": False, "error": f"组合产物落盘失败: {exc}"}
    return {"ok": True,
            "result": {"out_dir": str(out), "script_path": str(out /
                                                               script_name),
                       "meta_path": str(out / meta_name),
                       "netlist_path": str(out / netlist_name),
                       "render_sha256":
                           composed["result"]["meta"]["render_sha256"],
                       "guards": composed["result"]["meta"]["guards"]}}


def compose_write_from_yaml_file(netlist_path: str | Path,
                                 out_dir: str | Path) -> dict[str, Any]:
    """netlist YAML 文件 → 组合三件套落盘（CLI/MCP 薄壳主入口）。"""
    import yaml

    path = Path(netlist_path)
    if not path.exists():
        return {"ok": False, "error": f"netlist 文件不存在: {path}"}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"netlist YAML 不可读: {exc}"}
    if not isinstance(data, dict):
        return {"ok": False,
                "error": f"netlist YAML 必须为映射，得到 {type(data)!r}"}
    return compose_write(data, out_dir)


def load_golden_netlist(example: str = "siw_chain") -> dict[str, Any]:
    """首例 netlist（GOLDEN_NETLISTS fixture；测试/CLI 示例共用，深拷贝）。"""
    import copy

    if example not in GOLDEN_NETLISTS:
        return {"ok": False,
                "error": f"未知组合示例 {example!r}（可用 "
                         f"{sorted(GOLDEN_NETLISTS)}）"}
    return {"ok": True, "result": copy.deepcopy(GOLDEN_NETLISTS[example])}


def verify_compose_provenance(out_dir: str | Path) -> dict[str, Any]:
    """C5 预演（P3 门的前置自检）：重渲染 sha256==compose_meta 落痕。

    读 out_dir/netlist.yaml → 重新组合 → sha256 与 out_dir/compose_meta.json
    的 render_sha256/netlist_sha256 对账（确定性引擎 ⇒ 必相等）。
    """
    import yaml

    out = Path(out_dir)
    netlist_file, meta_file = out / "netlist.yaml", out / "compose_meta.json"
    for f in (netlist_file, meta_file):
        if not f.exists():
            return {"ok": False, "error": f"provenance 复验缺产物: {f}"}
    try:
        netlist = yaml.safe_load(netlist_file.read_text(encoding="utf-8"))
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"provenance 产物不可读: {exc}"}
    recomposed = compose_from_netlist(netlist)
    if not recomposed.get("ok"):
        return recomposed
    meta2 = recomposed["result"]["meta"]
    checks = {
        "render_sha256": (meta.get("render_sha256")
                          == meta2["render_sha256"]),
        "netlist_sha256": (meta.get("netlist_sha256")
                           == meta2["netlist_sha256"]),
    }
    ok = all(checks.values())
    return {"ok": ok, "result": {"checks": checks,
                                 "render_sha256": meta2["render_sha256"],
                                 "expected": {k: meta.get(k) for k in checks}}}


__all__ = [
    "GOLDEN_NETLISTS",
    "compose_from_netlist",
    "compose_from_yaml_file",
    "compose_write",
    "compose_write_from_yaml_file",
    "list_composable_templates",
    "load_golden_netlist",
    "verify_compose_provenance",
]
