"""EDB 快车道 MCP 工具组（CLI 出口同批，2026-10-08）——3 工具薄壳。

零逻辑转发 service/edb_lane_service（规则 4；发射综合/建库/批解编排全在
service 与 adapters 确定性内核，铁律 7——本模块零物理数值）。与 CLI
``rfauto edb build/solve/status`` 同源同名 service 函数（JSON 进出）：

- ``edb_emit_spec``：只读发射（spec/config 预览，可选 out_dir 存证落盘）；
- ``edb_build_solve``：**mutating**——建库写 workdir（.aedb+config 存证）；
  ``payload.solve=true`` 时追加真机批解（ansysedt -BatchSolve 短命批进程
  + 可选 -batchextract 导 Touchstone，长跑面，超时由 timeout_s 承担；
  v1 同步返回不进 async 队列——与 hfss_batch 直接批解通道同口径）；
- ``edb_status``：只读资产清单（工程/存证/日志/Touchstone 扫描）。

无 license/缺 pyedb 环境不受影响：service 层错误归一 error 信封不炸会话；
``dry_run=true`` 建库面零写盘零 pyedb（计划态冒烟）。

2026-10-08 追加 MCP resources 两件（尾部，不计入工具数）：``rfauto://edb/
status``（五族清单+产物统计，edb_status 同源薄资源）与 ``rfauto://edb/
datasets``（runs/datasets/ 下 edb_lane_* 数据集 manifest 摘要，
dataset_insights.list_datasets 前缀过滤薄包装）。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope


@mcp.tool
def edb_emit_spec(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """发射声明式 EDB spec（edb_branchline/edb_power_divider 平面族发射器）。

    尺寸全部由 core.synthesis 闭式综合产出（确定性内核，铁律 7）；本工具
    只读预览，不触 pyedb/AEDT。与 CLI ``rfauto edb build --dry-run`` 的
    发射段同源。

    Args:
        payload: JSON 进出 payload：template（缺省 "edb_branchline"）；
            params（设计参数 dict，f0_ghz 必填、z0_ohm 仅 50、stackup/
            sweep/adapt 可选）；out_dir（可选，spec JSON 存证落盘目录，
            写 <stem>_spec.json——唯一的写副作用）。

    Returns:
        dict: 成功 ``{ok, template, spec, config_json, spec_path?}``；
        失败 ``{ok: false, errors: [str]}``（未知模板/综合自检失败/契约
        校验失败/落盘 IO 错误），不抛出。
    """
    from rfauto.service.edb_lane_service import edb_emit_spec as _fn

    data = dict(payload or {})
    try:
        return _fn(str(data.get("template") or "edb_branchline"),
                   dict(data.get("params") or {}),
                   out_dir=data.get("out_dir"))
    except (KeyError, TypeError, ValueError) as e:
        return error_envelope(str(e))


@mcp.tool
def edb_build_solve(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """EDB 建库（.aedb）+ 可选批处理求解与 Touchstone 导出一站式编排。

    **mutating**：向 workdir 写 ``<name>.aedb`` 工程与 ``<name>_config.json``
    存证；``solve=true`` 时拉起 ansysedt 短命批进程真机求解（需 AEDT 在
    位，长跑面——超时/失败/缺装全部进信封 errors 不炸会话）。无 license
    冒烟用 ``dry_run=true``（只发射+契约双检+config 预览，零写盘零 pyedb）。

    Args:
        payload: JSON 进出 payload：template（缺省 "edb_branchline"）；
            params（设计参数 dict，同 edb_emit_spec）；workdir（产物根，
            缺省 "runs/edb_lane"）；name（文件名主干，缺省=template）；
            dry_run（true=计划态零写盘）；solve（true=建库后接批解，
            缺省 false）；timeout_s（每段进程 watchdog 超时秒，缺省
            3600）；export（批后导 Touchstone 开关，缺省 true，导出失败
            只告警不推翻求解 ok）。

    Returns:
        dict: ``{ok, template, build:{...}, solve?:{...}}``（dry_run 时
        build 节带 spec/config 预览且无路径键）；失败 ``{ok: false,
        errors: [str], build?/solve?}``，不抛出。
    """
    from rfauto.service.edb_lane_service import edb_build_solve as _fn

    data = dict(payload or {})
    try:
        return _fn(
            str(data.get("template") or "edb_branchline"),
            dict(data.get("params") or {}),
            workdir=data.get("workdir") or "runs/edb_lane",
            name=data.get("name"),
            dry_run=bool(data.get("dry_run", False)),
            solve=bool(data.get("solve", False)),
            timeout_s=float(data.get("timeout_s", 3600.0)),
            export=bool(data.get("export", True)),
        )
    except (KeyError, TypeError, ValueError) as e:
        return error_envelope(str(e))


@mcp.tool
def edb_status(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """扫描 EDB 快车道产物根目录的资产清单（只读，零求解零导入）。

    按 stem 归组清点：.aedb 工程、*_config.json 建库存证、ansysedt 批解
    与导出日志、*_export.s2p Touchstone、*_spec.json 发射存证。目录不
    存在=ok 空 表（n_projects=0，不臆造）。

    Args:
        payload: JSON 进出 payload：root（产物根目录，缺省
            "runs/edb_lane"）。

    Returns:
        dict: ``{ok, root, n_projects, items:[{stem, aedb, config_json,
        solve_log, extract_log, touchstone, spec_json, solved}]}``，
        缺项 None；不抛出。
    """
    from rfauto.service.edb_lane_service import edb_status as _fn

    data = dict(payload or {})
    try:
        return _fn(data.get("root") or "runs/edb_lane")
    except (KeyError, TypeError, ValueError) as e:
        return error_envelope(str(e))


# ─── MCP resources 两件（只读快车道状态面，2026-10-08：+2 resources）──────────
# 与 mcp_tools/resources.py 五件同惯例：@mcp.resource 装饰器注册、函数体
# 惰性 import service 层既有函数（缺缝薄包装）、dict 形态 JSON 文本返回、
# 不计入工具数（R5-02 双口径门：注册面 list_resources() vs @mcp.resource
# 正则——新增资源两面天然同增）。facade re-import 在 mcp_server.py edb
# 工具组块尾（不得前移到 resources 组——from-import 源序=模块首导序，
# 前移会把本组三工具的注册序整体带前，金快照 tool_names_order 即漂）。


@mcp.resource("rfauto://edb/status")
def edb_status_resource() -> dict[str, Any]:
    """EDB 快车道状态（只读）：五族能力清单 + 产物根资产统计。

    service/edb_lane_service.edb_status 同源薄资源（缺省产物根
    ``runs/edb_lane``）：templates 五族清单（四支持族 + lange 结构化
    不支持）、items 逐工程资产行；另补 ``summary`` 薄聚合（solved/
    touchstone/config/spec 逐类计数，从 items 确定性复算，零新数值源
    ——铁律 7）。目录不存在=ok 空表（n_projects=0，不臆造）。
    """
    from rfauto.service.edb_lane_service import edb_status

    data = edb_status()
    if data.get("ok"):
        items = data.get("items") or []
        data["summary"] = {
            "n_solved": sum(1 for it in items if it.get("solved")),
            "n_touchstone": sum(1 for it in items if it.get("touchstone")),
            "n_config_json": sum(1 for it in items if it.get("config_json")),
            "n_spec_json": sum(1 for it in items if it.get("spec_json")),
        }
    return data


@mcp.resource("rfauto://edb/datasets")
def edb_datasets_resource() -> dict[str, Any]:
    """EDB 道数据集清单（只读）：runs/datasets/ 下 edb_lane_* manifest 摘要。

    service/dataset_insights.list_datasets 同源薄资源，按 name 前缀
    ``edb_lane_`` 过滤（逐行 name/schema_version/created_at/format/
    n_points/n_rows/n_dup/visibility/n_gt_rows/gt_unlocked/has_hf/
    dataset_dir）；失败信封原样透传，目录不存在=ok 空表（不臆造）。
    """
    from rfauto.service.dataset_insights import list_datasets
    from rfauto.service.envelope import ok_envelope

    data = list_datasets()
    if not data.get("ok"):
        return data
    rows = [d for d in data.get("datasets") or []
            if str(d.get("name") or "").startswith("edb_lane_")]
    return ok_envelope(out_dir=data.get("out_dir"), datasets=rows,
                       n_datasets=len(rows))
