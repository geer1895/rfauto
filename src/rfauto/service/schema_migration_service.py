"""KD-6 schema 演进管理（round16 P2，J 流）——版本迁移注册表。

定位（任务书口径）：samples/oe_result 类**载荷 schema 版本迁移**的
注册表工具面（仿 runs_stats 的 schema_version 表 + PRAGMA user_version
思路：版本戳显式、单调前进、幂等重放）。runs_stats 管数据库表的
schema_version，本模块管**载荷级** schema_version（JSON dict 自带
``schema_version`` 键）——迁移=纯函数（旧载荷 dict → 新载荷 dict），
零数据库依赖，落盘面由调用方决定。

设计约束（确定性内核）：
- 迁移注册一次一根边（from→to）；重复注册同起点=SchemaMigrationError
  （歧义迁移图禁止——迁移链必须线性可判定）；
- ``migrate_payload`` 从当前版本沿注册边走到 target：路径不连续
  （缺中间版本）=显式报错（不跳版本、不猜路径）；
- 已 ≥ target 的载荷=无操作（n_steps=0，幂等——重放安全）；
- 载荷无 schema_version 视为版本 0（"未标注=最老"约定，注册表声明）；
- 迁移函数必须纯（同输入同输出）；本模块对每次迁移前后打
  ``schema_history`` 追加条目（from/to/name）供溯源。

用法::

    from rfauto.service.schema_migration_service import (
        register_migration, migrate_payload)

    register_migration(1, 2, "add_provenance_block", lambda d: {**d, "provenance": {}})
    out = migrate_payload({"schema_version": 1, "cost": 0.5}, target_version=2)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

#: 迁移面契约版本（本模块自身 schema）。
SCHEMA_MIGRATION_REGISTRY_VERSION = 1

#: 载荷版本键名（载荷 dict 自带；缺省视为版本 0）。
PAYLOAD_VERSION_KEY = "schema_version"

#: 未标注载荷的约定版本。
UNVERSIONED = 0


class SchemaMigrationError(ValueError):
    """迁移注册表/迁移路径违例（负例测试的预期异常类型）。"""


# ─── 注册表（模块级单源；边表 from_version → (to_version, name, fn)）────────
_MIGRATIONS: dict[int, tuple[int, str, Callable[[dict[str, Any]], dict[str, Any]]]] = {}


def reset_registry() -> None:
    """清空注册表（仅测试用；生产面模块导入即空，注册发生在消费方）。"""
    _MIGRATIONS.clear()


def register_migration(
    from_version: int,
    to_version: int,
    name: str,
    migrate_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    """注册一条迁移边（from→to 恰 +1 或显式多步边均可，但同起点唯一）。

    - from==to 或 from>to=SchemaMigrationError（迁移只前进，不回退）；
    - 同 from_version 重复注册=SchemaMigrationError（迁移图必须线性可
      判定——同起点两条边即歧义，宁拒绝不留歧义）；
    - migrate_fn 必须是一元纯函数（dict→dict）；非 dict 载荷在执行期
      报错（注册期只验签名可调用）。
    """
    if not isinstance(from_version, int) or not isinstance(to_version, int):
        raise SchemaMigrationError("版本号必须是 int")
    if from_version >= to_version:
        raise SchemaMigrationError(
            f"迁移只前进：from={from_version} >= to={to_version}")
    if from_version in _MIGRATIONS:
        existing = _MIGRATIONS[from_version]
        raise SchemaMigrationError(
            f"from_version={from_version} 已注册迁移 {existing[1]!r}"
            f"（同起点歧义禁止，新边=先重构合并）")
    if not callable(migrate_fn):
        raise SchemaMigrationError("migrate_fn 必须可调用")
    _MIGRATIONS[from_version] = (int(to_version), str(name), migrate_fn)


def registry_snapshot() -> list[dict[str, Any]]:
    """注册表快照（确定性：按 from_version 升序；只读面）。"""
    return [{"from_version": fv, "to_version": tv, "name": name}
            for fv, (tv, name, _fn) in sorted(_MIGRATIONS.items())]


def _payload_version(payload: dict[str, Any]) -> int:
    """载荷版本读取（无键=UNVERSIONED=0；非 int=SchemaMigrationError）。"""
    v = payload.get(PAYLOAD_VERSION_KEY, UNVERSIONED)
    if isinstance(v, bool) or not isinstance(v, int):
        raise SchemaMigrationError(
            f"载荷 {PAYLOAD_VERSION_KEY} 须为 int，得到 {v!r}")
    return v


def migrate_payload(payload: dict[str, Any], *,
                    target_version: int) -> dict[str, Any]:
    """载荷沿注册迁移边走到 target_version（纯函数；幂等重放安全）。

    - 载荷须为 dict（含副本语义：迁移在浅拷贝上逐边应用，原载荷不
      被就地改写——调用方持有旧载荷引用安全）；
    - 当前版本 ≥ target：无操作返回副本（n_steps=0）；
    - 路径断裂（当前版本无注册边且 < target）=SchemaMigrationError
      （不跳版本、不猜路径，缺哪段如实报哪段）。

    Returns:
        {payload: 迁移后载荷, from_version, to_version, n_steps,
         history: [{from_version, to_version, name}]}
    """
    if not isinstance(payload, dict):
        raise SchemaMigrationError(f"载荷须为 dict，得到 {type(payload).__name__}")
    if not isinstance(target_version, int) or isinstance(target_version, bool):
        raise SchemaMigrationError(f"target_version 须为 int，得到 {target_version!r}")
    current = _payload_version(payload)
    work = dict(payload)
    history: list[dict[str, Any]] = []
    while current < target_version:
        edge = _MIGRATIONS.get(current)
        if edge is None:
            raise SchemaMigrationError(
                f"迁移路径断裂：版本 {current} 无注册边（target={target_version}，"
                f"已注册起点={sorted(_MIGRATIONS)}）")
        to_v, name, fn = edge
        migrated = fn(work)
        if not isinstance(migrated, dict):
            raise SchemaMigrationError(
                f"迁移 {name!r} 返回 {type(migrated).__name__}（须为 dict）")
        work = dict(migrated)
        history.append({"from_version": current, "to_version": to_v,
                        "name": name})
        current = to_v
    work[PAYLOAD_VERSION_KEY] = max(current, _payload_version(payload))
    return {"payload": work, "from_version": _payload_version(payload),
            "to_version": work[PAYLOAD_VERSION_KEY], "n_steps": len(history),
            "history": history}
