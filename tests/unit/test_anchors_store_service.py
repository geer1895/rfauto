"""DP-3 锚注册表装载/服务/CLI 接线测试（判据 a2 + b + d，预声明
runs/df6_dp3anchors/criteria.md）。

- a2：f_dip·L 双锚值与 scripts/wp39_followup_run.py 硬编码字面值逐位相等
  （regex 只读提取，scripts 非包不入 import 面）；
- b：provenance 单测——真实注册表 validate 全过（runs 路径存在/commit 可
  解析/时戳可解析/consumers 文件存在/referee_script 存在）；
- d：装载集合 == EXPECTED_ANCHORS 单源；
- store best-effort：缺文件/坏 YAML → 空集 + warning（#105）；
- service JSON 面四入口 + CLI/MCP 挂载最小接线。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _REPO_ROOT / "knowledge" / "anchors.yaml"

#: b/d 判据依赖 runs/ 真机证据目录（arbitration_runs/referee/candidates 指向）。
#: 证据目录不随 git 分发（runs/ 整体不入库）——缺失环境整组诚实 skip，
#: 证据在位（内部工作区/归档恢复）时照常全量校验。
_EVIDENCE_DIRS = (
    "runs/df6_a1_r4", "runs/df5_c3fix", "runs/df6_dp14m1", "runs/df6_dp18c9",
    "runs/wp39_probe_patch", "runs/wp39_mvp_followup", "runs/siw_family",
)
_requires_evidence = pytest.mark.skipif(
    any(not (_REPO_ROOT / d).exists() for d in _EVIDENCE_DIRS),
    reason="runs/ evidence directories not distributed with git "
           "(anchors provenance validation needs them)")


def _live_anchor_set():
    from rfauto.infra.anchors_store import load_anchors

    return load_anchors()


# ── 判据 d + b：单源计数与 provenance 全过 ─────────────────────────────────

def test_d_registry_matches_expected_single_source() -> None:
    from rfauto.core.anchors import EXPECTED_ANCHOR_COUNT, EXPECTED_ANCHORS

    anchor_set = _live_anchor_set()
    assert len(anchor_set.load_errors) == 0
    assert set(anchor_set.anchor_ids) == set(EXPECTED_ANCHORS)
    assert len(anchor_set) == EXPECTED_ANCHOR_COUNT


@_requires_evidence
def test_b_validate_registry_full_pass() -> None:
    from rfauto.infra.anchors_store import validate_anchor_set

    report = validate_anchor_set(_live_anchor_set(),
                                 registry_path=_REGISTRY_PATH)
    assert report["ok"], f"provenance/schema issues: {report['issues']}"
    assert report["expected_match"] and report["count"] == 6


def test_b_each_active_anchor_provenance_fields_resolvable() -> None:
    from datetime import datetime

    anchor_set = _live_anchor_set()
    for rec in anchor_set.records:
        if rec.status == "awaiting_data":
            continue
        assert rec.provenance.get("arbitration_runs"), rec.anchor_id
        assert re.fullmatch(r"[0-9a-f]{7,40}",
                            str(rec.provenance["commit"]).lower())
        datetime.fromisoformat(str(rec.registered_at))
        assert rec.uncertainty and rec.uncertainty.get("value") is not None


# ── 判据 a2：f_dip·L 双值与 scripts 硬编码字面值逐位相等 ───────────────────

def test_a2_f_dip_l_bit_exact_against_script_literals() -> None:
    src = (_REPO_ROOT / "scripts" / "wp39_followup_run.py").read_text(
        encoding="utf-8")
    hfss_lit = float(re.search(r"^HFSS_PATCH_CONSTANT_REF\s*=\s*([0-9.]+)",
                               src, re.M).group(1))
    oe_lit = float(re.search(r"^OPENEMS_PATCH_CONSTANT_DOC\s*=\s*([0-9.]+)",
                             src, re.M).group(1))
    assert hfss_lit == 99.8 and oe_lit == 76.8  # 脚本现值先自钉
    anchor_set = _live_anchor_set()
    got_oe = anchor_set.resolve_anchor("patch.f_dip_l.openems-v1")
    got_hfss = anchor_set.resolve_anchor("patch.f_dip_l.hfss-v1")
    assert got_oe["value"] == oe_lit
    assert got_hfss["value"] == hfss_lit


# ── store best-effort（#105）与缓存 ────────────────────────────────────────

def test_store_missing_file_best_effort_empty_warning(
        caplog: pytest.LogCaptureFixture) -> None:
    from rfauto.infra.anchors_store import load_anchors

    with caplog.at_level(logging.WARNING, logger="rfauto.infra.anchors_store"):
        anchor_set = load_anchors(_REPO_ROOT / "knowledge" / "no_such.yaml")
    assert len(anchor_set) == 0
    assert any("best-effort" in r.message for r in caplog.records)


@_requires_evidence
def test_store_corrupt_yaml_best_effort_empty(
        caplog: pytest.LogCaptureFixture) -> None:
    from rfauto.infra.anchors_store import load_anchors

    bad = _REPO_ROOT / "runs" / "df6_dp3anchors" / "_bad_anchors.yaml"
    bad.write_text("anchors: [ {anchor_id: broken\n  :::\n", encoding="utf-8")
    try:
        with caplog.at_level(logging.WARNING,
                             logger="rfauto.infra.anchors_store"):
            anchor_set = load_anchors(bad, force_reload=True)
        assert len(anchor_set) == 0
        assert caplog.records
    finally:
        bad.unlink(missing_ok=True)


def test_store_bad_anchor_does_not_sink_whole_table() -> None:
    from rfauto.core.anchors import AnchorSet
    from rfauto.infra.anchors_store import load_anchors

    data = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
    data["anchors"].append({"anchor_id": "bad.id-v1", "kind": "constant",
                            "status": "active"})
    merged = AnchorSet(data["anchors"])
    assert len(merged.load_errors) == 1
    assert len(merged) == 6
    assert load_anchors(_REGISTRY_PATH) is not None


def test_store_mtime_cache_roundtrip() -> None:
    from rfauto.infra.anchors_store import load_anchors

    first = load_anchors(_REGISTRY_PATH)
    second = load_anchors(_REGISTRY_PATH)
    assert first is second  # 同 (path, mtime, size) 命中缓存


# ── service JSON 面 ────────────────────────────────────────────────────────

@_requires_evidence
def test_service_list_inspect_validate_resolve_json_roundtrip() -> None:
    from rfauto.service import anchors_service as svc

    listed = svc.list_anchors()
    assert listed["ok"] and listed["count"] == 6
    assert json.dumps(listed, ensure_ascii=False)  # JSON 可序列化

    inspected = svc.inspect_anchor("c3.l_via_h.openems-hfss-v1")
    assert inspected["ok"] and inspected["anchor"]["value"] == 0.125e-9

    miss = svc.inspect_anchor("no.such-v1")
    assert miss["ok"] is False and "未知锚" in miss["error"]

    report = svc.validate_registry()
    assert report["ok"] and report["expected_match"]

    resolved = svc.resolve_anchor_request("cps.gamma_er.fdref-v1",
                                          {"er": 3.66})
    assert resolved["ok"] and resolved["result"]["value"] == pytest.approx(
        1.3949000923648935)

    residual = svc.note_anchor_residual_request("cps.gamma_er.fdref-v1",
                                                {"er": 3.66}, 1.40)
    assert residual["ok"] and residual["result"]["stale"] is False


def test_service_registry_yaml_shape_honest() -> None:
    """schema: anchors/v1 头与全注册表 status 如实登记。

    df7 收尾笔：c3.k_of_g 骨架已按预声明转换回填翻 active（6 点全 PASS+
    严格单调，curve_verdict.json），awaiting_data→active 转换完成=全 6 active。
    """
    data = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert data["schema"] == "anchors/v1"
    statuses = {a["anchor_id"]: a["status"] for a in data["anchors"]}
    assert statuses["c3.k_of_g.openems-hfss-v1"] == "active"
    assert sum(s == "active" for s in statuses.values()) == 6
    kofg = next(a for a in data["anchors"]
                if a["anchor_id"] == "c3.k_of_g.openems-hfss-v1")
    assert len(kofg["points"]) == 6
    assert kofg["uncertainty"] is not None
    assert kofg["provenance"]["arbitration_runs"] == ["runs/df6_a1_r4"]


# ── CLI 挂载最小接线（#305：--help 真构建；list/validate JSON 出）──────────

def test_cli_anchors_help_builds() -> None:
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    runner = CliRunner()
    for args in (["anchors", "--help"], ["anchors", "list", "--help"],
                 ["anchors", "inspect", "--help"],
                 ["anchors", "validate", "--help"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output)


def test_cli_anchors_list_json() -> None:
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    result = CliRunner().invoke(app, ["anchors", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] == 6


def test_cli_anchors_inspect_json() -> None:
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    result = CliRunner().invoke(
        app, ["anchors", "inspect", "patch.f_dip_l.openems-v1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["anchor"]["value"] == 76.8


@_requires_evidence
def test_cli_anchors_validate_pass() -> None:
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    result = CliRunner().invoke(app, ["anchors", "validate"])
    assert result.exit_code == 0, result.output


# ── MCP 挂载最小接线（工具注册 + 可调用，不开传输；#270 list_tools 口径）────

def test_mcp_tools_registered_and_callable() -> None:
    import asyncio

    from rfauto.mcp_server import mcp

    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert {"anchors_list", "anchors_inspect"} <= set(tools)
    listed = tools["anchors_list"].fn()
    assert listed["ok"] and listed["count"] == 6
    inspected = tools["anchors_inspect"].fn("c3.l_via_h.openems-hfss-v1")
    assert inspected["ok"] and inspected["anchor"]["version"] == 1
