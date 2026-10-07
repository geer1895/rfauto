"""KD-6 schema 迁移工具测试（round16 P2，J 流）。

锚树：
- 注册面：同起点重复注册拒绝（歧义迁移图禁止）/只前进（from>=to 拒）/
  非可调用迁移函数拒绝/快照确定性；
- 迁移面：单步/多步链式（1→2→3）/路径断裂显式报错（不跳版本不猜路径）/
  幂等（当前>=target 无操作 n_steps=0）/原载荷不被就地改写（副本语义）/
  未标注载荷=版本 0 约定/非 int 版本拒绝/迁移函数返回非 dict 拒绝；
- 确定性：同输入两次迁移结果逐位一致；
- 仿 runs_stats 语义锚：版本戳显式、单调前进、重放安全。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

from rfauto.service.schema_migration_service import (
    PAYLOAD_VERSION_KEY,
    SCHEMA_MIGRATION_REGISTRY_VERSION,
    UNVERSIONED,
    SchemaMigrationError,
    migrate_payload,
    register_migration,
    registry_snapshot,
    reset_registry,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_registry()
    yield
    reset_registry()


class TestRegistry:
    def test_register_and_snapshot(self):
        register_migration(1, 2, "v1_to_v2", lambda d: {**d, "new": True})
        snap = registry_snapshot()
        assert snap == [{"from_version": 1, "to_version": 2, "name": "v1_to_v2"}]

    def test_duplicate_origin_rejected(self):
        register_migration(1, 2, "first", lambda d: d)
        with pytest.raises(SchemaMigrationError, match="歧义"):
            register_migration(1, 3, "second", lambda d: d)

    def test_non_forward_migration_rejected(self):
        with pytest.raises(SchemaMigrationError, match="前进"):
            register_migration(2, 2, "noop", lambda d: d)
        with pytest.raises(SchemaMigrationError, match="前进"):
            register_migration(3, 1, "rollback", lambda d: d)

    def test_non_callable_rejected(self):
        with pytest.raises(SchemaMigrationError, match="可调用"):
            register_migration(1, 2, "bad", "not-callable")

    def test_non_int_version_rejected(self):
        with pytest.raises(SchemaMigrationError, match="int"):
            register_migration("1", 2, "bad", lambda d: d)

    def test_snapshot_sorted_by_origin(self):
        register_migration(2, 3, "b", lambda d: d)
        register_migration(1, 2, "a", lambda d: d)
        assert [e["from_version"] for e in registry_snapshot()] == [1, 2]

    def test_registry_version_pinned(self):
        assert SCHEMA_MIGRATION_REGISTRY_VERSION == 1


class TestMigrate:
    def test_single_step(self):
        register_migration(1, 2, "add_cost_unit",
                           lambda d: {**d, "cost_unit": "dB"})
        out = migrate_payload({PAYLOAD_VERSION_KEY: 1, "cost": 3.0},
                              target_version=2)
        assert out["payload"] == {PAYLOAD_VERSION_KEY: 2, "cost": 3.0,
                                  "cost_unit": "dB"}
        assert out["n_steps"] == 1
        assert out["history"] == [{"from_version": 1, "to_version": 2,
                                   "name": "add_cost_unit"}]

    def test_multi_step_chain(self):
        register_migration(1, 2, "a", lambda d: {**d, "v2": True})
        register_migration(2, 3, "b", lambda d: {**d, "v3": True})
        out = migrate_payload({PAYLOAD_VERSION_KEY: 1}, target_version=3)
        assert out["payload"][PAYLOAD_VERSION_KEY] == 3
        assert out["n_steps"] == 2
        assert [h["name"] for h in out["history"]] == ["a", "b"]

    def test_unversioned_payload_starts_at_zero(self):
        register_migration(UNVERSIONED, 1, "stamp",
                           lambda d: {**d, PAYLOAD_VERSION_KEY: 1})
        out = migrate_payload({"cost": 1.0}, target_version=1)
        assert out["from_version"] == UNVERSIONED
        assert out["payload"][PAYLOAD_VERSION_KEY] == 1

    def test_broken_path_is_explicit_not_guessed(self):
        register_migration(1, 2, "a", lambda d: {**d})
        # 载荷在版本 1，但 target=3 而 2→3 未注册 → 断裂显式报错
        with pytest.raises(SchemaMigrationError, match="断裂"):
            migrate_payload({PAYLOAD_VERSION_KEY: 1}, target_version=3)

    def test_idempotent_replay_noop_when_current_ge_target(self):
        register_migration(1, 2, "a", lambda d: {**d, "migrated": True})
        payload = {PAYLOAD_VERSION_KEY: 3}
        out = migrate_payload(payload, target_version=2)
        assert out["n_steps"] == 0
        assert out["payload"] == {PAYLOAD_VERSION_KEY: 3}

    def test_source_payload_not_mutated(self):
        register_migration(1, 2, "a", lambda d: {**d, "x": 1})
        src = {PAYLOAD_VERSION_KEY: 1}
        out = migrate_payload(src, target_version=2)
        assert src == {PAYLOAD_VERSION_KEY: 1}
        assert out["payload"] == {PAYLOAD_VERSION_KEY: 2, "x": 1}

    def test_migration_returning_non_dict_rejected(self):
        register_migration(1, 2, "bad", lambda d: [1, 2])  # type: ignore[arg-type]
        with pytest.raises(SchemaMigrationError, match="dict"):
            migrate_payload({PAYLOAD_VERSION_KEY: 1}, target_version=2)

    def test_non_int_payload_version_rejected(self):
        with pytest.raises(SchemaMigrationError, match="int"):
            migrate_payload({PAYLOAD_VERSION_KEY: "v1"}, target_version=2)

    def test_non_dict_payload_rejected(self):
        with pytest.raises(SchemaMigrationError, match="dict"):
            migrate_payload([1, 2], target_version=2)  # type: ignore[arg-type]

    def test_deterministic(self):
        register_migration(1, 2, "a", lambda d: {**d, "n": d.get("n", 0) + 1})
        p = {PAYLOAD_VERSION_KEY: 1, "n": 0}
        a = json.dumps(migrate_payload(p, target_version=2), sort_keys=True)
        b = json.dumps(migrate_payload(p, target_version=2), sort_keys=True)
        assert a == b

    def test_samples_style_migration_scenario(self):
        """仿 runs_stats 语义：samples 载荷 v1（无 provenance）→ v2（补
        provenance 块）→ v3（cost 从行内提为嵌套 metrics）。"""
        register_migration(
            1, 2, "samples_add_provenance",
            lambda d: {**d, "provenance": {"adapter": d.get("adapter", "unknown")}})
        register_migration(
            2, 3, "samples_nest_metrics",
            lambda d: {**d, "metrics": {"cost": d.get("cost")}})

        v1 = {"adapter": "hfss", "cost": 0.25, PAYLOAD_VERSION_KEY: 1}
        out = migrate_payload(v1, target_version=3)
        assert out["payload"]["provenance"] == {"adapter": "hfss"}
        assert out["payload"]["metrics"] == {"cost": 0.25}
        assert out["payload"][PAYLOAD_VERSION_KEY] == 3
        # 重放安全：再跑一次结果不变
        out2 = migrate_payload(v1, target_version=3)
        assert out == out2
