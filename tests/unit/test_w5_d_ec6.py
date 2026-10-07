"""W5-D 件 2 EC-6 测试：toolsets 目录资源+guidelines 上下文工具（零网络全确定性）。

判据（spec §2.3 预声明门值，runs/research_seats_20261004/se_specs3/SPECS.md）：
1. 单一真源对拍：枚举名单==live list_tools 名单（逐位）；
2. skill 文本质量：非空且含坑号或命令名；缺 → errors 显式；
3. guidelines 回收例：openems ≥5 条且可溯源；未知 topic ok=False（双态钉）；
4. 确定性钉：同输入两次调用逐位一致（零网络零随机）。
共享计数面（test_mcp_server 计数/名单、test_mcp_tool_consistency 台账数、
check_numbers 声明数、docs 三处）归主代理合流集中更新——本席只登记预期红。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import yaml

from rfauto.mcp_server import get_mcp_server
from rfauto.mcp_tools.guidelines import get_guidelines_for as tool_get_guidelines_for
from rfauto.mcp_tools.resources import toolsets_definition_resource
from rfauto.service.guidelines_service import get_guidelines_for
from rfauto.service.toolsets_service import (
    TOOLSETS_RESOURCE_URI,
    TOOLSETS_SCHEMA,
    build_toolsets_definition,
    default_toolsets_yaml_path,
    enumerate_registered_tool_names,
)

# ── 判据 1：单一真源（枚举==live 注册面；资源==服务同源） ─────────────────────


def test_enumeration_matches_live_registry_bitwise() -> None:
    live = {t.name for t in asyncio.run(get_mcp_server().list_tools())}
    static = set(enumerate_registered_tool_names())
    assert static == live
    assert len(static) == len(live)


def test_tracked_yaml_builds_ok_with_nonempty_tools() -> None:
    payload = build_toolsets_definition()
    assert payload["ok"] is True, payload.get("errors")
    toolsets = payload["toolsets"]
    assert len(toolsets) >= 10
    names = {ts["name"] for ts in toolsets}
    assert len(names) == len(toolsets)  # 无重名
    for ts in toolsets:
        assert ts["description"].strip()
        assert ts["tools"], f"{ts['name']} 成员为空（hint 全零命中应已在 ok 门拦截）"
        # 判据 2：skill 非空且含 ≥1 个坑号（#NNN）或 rfauto 命令名
        assert ts["skill"].strip()
        assert ("#" in ts["skill"]) or ("rfauto" in ts["skill"])


def test_resource_function_is_service_same_source() -> None:
    assert toolsets_definition_resource() == build_toolsets_definition()


def test_toolsets_resource_uri_registered() -> None:
    uris = {str(r.uri) for r in asyncio.run(get_mcp_server().list_resources())}
    assert TOOLSETS_RESOURCE_URI in uris
    # 本仓 scheme 一致性裁决：全 URI 均为 rfauto:// scheme（不用官方 toolsets:/）
    assert all(u.startswith("rfauto://") for u in uris)


def test_guidelines_tool_registered() -> None:
    names = {t.name for t in asyncio.run(get_mcp_server().list_tools())}
    assert "get_guidelines_for" in names


# ── drift/skill 质量钉（tmp 样本造分歧，FAIL 面显式） ─────────────────────────


def _write_yaml(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "toolsets.yaml"
    path.write_text(
        yaml.safe_dump(
            {"schema": TOOLSETS_SCHEMA, "toolsets": entries},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_tools_hint_drift_reports_fail(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        [
            {
                "name": "fake_set",
                "description": "d",
                "skill": "先看 #152 再动手",
                "tools_hint": ["bands_*", "no_such_tool_xyz"],
            }
        ],
    )
    payload = build_toolsets_definition(path, tool_names=["bands_list", "bands_get"])
    assert payload["ok"] is False
    assert any("no_such_tool_xyz" in e for e in payload["errors"])
    assert any("零命中" in e for e in payload["errors"])
    # 命中部分照常枚举（已构建部分随行留痕）
    assert payload["toolsets"][0]["tools"] == ["bands_get", "bands_list"]


def test_empty_skill_and_markerless_skill_flagged(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        [
            {"name": "s1", "description": "d", "skill": "", "tools_hint": ["alpha"]},
            {
                "name": "s2",
                "description": "d",
                "skill": "纯叙事没有任何出处标记",
                "tools_hint": ["alpha"],
            },
        ],
    )
    payload = build_toolsets_definition(path, tool_names=["alpha"])
    assert payload["ok"] is False
    assert any("s1" in e and "skill 为空" in e for e in payload["errors"])
    assert any("s2" in e and "出处标记" in e for e in payload["errors"])


def test_rfauto_command_counts_as_skill_marker(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        [
            {
                "name": "s1",
                "description": "d",
                "skill": "开工先 `rfauto doctor` 体检",
                "tools_hint": ["alpha"],
            }
        ],
    )
    payload = build_toolsets_definition(path, tool_names=["alpha"])
    assert payload["ok"] is True, payload.get("errors")


def test_schema_version_mismatch_rejected(tmp_path: Path) -> None:
    path = tmp_path / "t.yaml"
    path.write_text(
        yaml.safe_dump({"schema": "other-v9", "toolsets": []}), encoding="utf-8"
    )
    payload = build_toolsets_definition(path)
    assert payload["ok"] is False
    assert any("schema" in e for e in payload["errors"])


# ── 判据 3：guidelines 回收例（真实数据源，双态钉） ───────────────────────────


def test_guidelines_openems_recovery() -> None:
    payload = get_guidelines_for("openems")
    assert payload["ok"] is True
    hits = payload["hits"]
    assert len(hits) >= 5
    for hit in hits:
        # 每条 openems 相关：类别命中或文本含 openems（pitfalls），或 playbook 指纹规则
        relevant = (
            hit["category"] == "openems"
            or hit["source"] == "playbook"
            or "openems" in hit["text"].lower()
        )
        assert relevant, hit
        # 可溯源：ref 非空 + anchor 非空（#NNN 是 出处标记/ 行锚）
        assert hit["ref"].strip()
        assert hit["anchor"].strip()


def test_guidelines_unknown_topic_fails_explicit() -> None:
    payload = get_guidelines_for("绝不存在主题xyz")
    assert payload["ok"] is False
    assert payload["errors"]
    assert any("词表" in e for e in payload["errors"])


def test_guidelines_empty_topic_fails() -> None:
    assert get_guidelines_for("   ")["ok"] is False
    assert get_guidelines_for("")["ok"] is False


def test_guidelines_fdtd_alias_maps_to_openems_with_playbook() -> None:
    payload = get_guidelines_for("fdtd")
    assert payload["ok"] is True
    cats = {h["category"] for h in payload["hits"]}
    assert "openems" in cats
    assert payload["counts"]["playbook"] >= 1  # fdtd_truncation_artifact 指纹规则


def test_guidelines_hfss_category() -> None:
    payload = get_guidelines_for("hfss")
    assert payload["ok"] is True
    assert payload["counts"]["total"] >= 3
    for hit in payload["hits"]:
        assert (
            hit["category"] == "hfss"
            or hit["source"] == "playbook"
            or "hfss" in hit["text"].lower()
        )


def test_guidelines_missing_source_fails_gracefully(tmp_path: Path) -> None:
    payload = get_guidelines_for("openems", knowledge_root=tmp_path)
    assert payload["ok"] is False
    assert any("加载失败" in e or "不存在" in e for e in payload["errors"])


# ── 判据 4：确定性（零网络零随机，两次调用逐位一致） ──────────────────────────


def test_guidelines_deterministic_bitwise() -> None:
    a = get_guidelines_for("openems")
    b = get_guidelines_for("openems")
    assert json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(
        b, ensure_ascii=False, sort_keys=True
    )


def test_toolsets_definition_deterministic_bitwise() -> None:
    assert json.dumps(
        build_toolsets_definition(), ensure_ascii=False, sort_keys=True
    ) == json.dumps(build_toolsets_definition(), ensure_ascii=False, sort_keys=True)


# ── 薄壳一致性：MCP 工具函数转发 service 同名函数 ────────────────────────────


def test_tool_shell_forwards_to_service() -> None:
    service_payload = get_guidelines_for("openems")
    tool_payload = tool_get_guidelines_for("openems")
    assert tool_payload == service_payload


def test_tracked_yaml_path_exists() -> None:
    assert default_toolsets_yaml_path().is_file()
