"""core.compose：配方确定性内核包。

- dag_schema（DP-9）：配方 DAG 化确定性 schema 内核。
- layout_netlist（DP-8）：模板 pin 契约+几何组合引擎（布局合并路线）。

分层约束（分层铁律）：本包只做纯函数（schema/排序/映射/文本发射），
零 I/O、零网络、零 adapters 依赖；组合实例契约由调用方注入
（COMPOSE_CONTRACTS 经 service/compose_service 组装）。
"""

from rfauto.core.compose.dag_schema import (
    DAG_SCHEMA,
    DEFAULT_ESCALATION,
    DEFAULT_RERUN_TRIGGERS,
    LINEAR_CHAIN_KINDS,
    NODE_KINDS,
    NODE_STATUSES,
    RERUN_TRIGGER_CATEGORIES,
    STAGE_KIND_MAP,
    DagSchemaError,
    canonical,
    linear_chain_recipe,
    nodes_from_stages,
    normalize_node,
    parse_dag,
    topo_order,
)
from rfauto.core.compose.layout_netlist import (
    COMPOSE_META_SCHEMA,
    COMPOSE_NETLIST_SCHEMA,
    ComposeError,
    canonical_json,
    compose_netlist,
    frame_apply_dir,
    frame_apply_point,
    normalize_netlist,
)

__all__ = [
    "COMPOSE_META_SCHEMA",
    "COMPOSE_NETLIST_SCHEMA",
    "DAG_SCHEMA",
    "DEFAULT_ESCALATION",
    "DEFAULT_RERUN_TRIGGERS",
    "LINEAR_CHAIN_KINDS",
    "NODE_KINDS",
    "NODE_STATUSES",
    "RERUN_TRIGGER_CATEGORIES",
    "STAGE_KIND_MAP",
    "ComposeError",
    "DagSchemaError",
    "canonical",
    "canonical_json",
    "compose_netlist",
    "frame_apply_dir",
    "frame_apply_point",
    "linear_chain_recipe",
    "nodes_from_stages",
    "normalize_netlist",
    "normalize_node",
    "parse_dag",
    "topo_order",
]
