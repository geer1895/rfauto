"""aurora_l Wave-C C4：MCP runs diagnose/compare_runs 接 verify 四态测试（R1 #17）。

此前两工具的结论建立在未验产物上（诊断读 runs/<id>/results/metrics.json、
对比读双 run 同款路径，都不查 run 收官指纹）。本批接线后钉四态语义：

- diagnose：fresh/legacy 放行（freshness 块随响应）；stale → data 头部
  醒目 ``stale_warning`` 行 + freshness.status="stale"；verify 面故障 →
  unknown 不阻塞诊断主路径（#105）；
- compare_runs：行级 freshness 列（A3 batch_ops 先例形态）——stale 标
  红不硬拒（notes 点名脏侧），legacy 带 note，双 unknown 不冒充脏；
  run 缺失 → service error 信封原样透传（不注入 freshness）。

合成 run 手法照 test_freshness_gates.py（sidecar+manifest stamp）；
全离线零网络（#139）、chdir 隔离零 runs/ 湖写入（#144）。规则引擎语料
复用 test_mcp_tool_consistency.TestDiagnoseToolEndToEnd（独立内联）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

# ── MCP 调用与合成 run helpers ──────────────────────────────────────────────


def _call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """经 fastmcp call_tool 真调用（TestDiagnoseToolEndToEnd 同款走法）。"""
    from rfauto.mcp_server import mcp

    result = asyncio.run(mcp.call_tool(tool_name, arguments))
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    return json.loads(result.content[0].text)


def _make_run(root: Path, name: str, *, metrics: dict[str, Any],
              cost: float = 0.1) -> Path:
    """合成 run：meta + results/metrics.json + Touchstone（最小形态）。"""
    run = root / name
    (run / "results").mkdir(parents=True, exist_ok=True)
    (run / "meta.json").write_text(json.dumps({
        "run_id": name, "model": "wilkinson_power_divider",
        "adapter": "fake", "status": "done"}), encoding="utf-8")
    (run / "results" / "metrics.json").write_text(
        json.dumps({"run_id": name, "metrics": metrics, "cost": cost}),
        encoding="utf-8")
    (run / "results" / "params.s1p").write_text(
        "# GHz S RI R 50\n1.0 0.1 0.0\n", encoding="utf-8")
    return run


def _stamp(run: Path) -> None:
    """收官指纹（run_once 收尾链路同序：sidecar+manifest）。"""
    from rfauto.service.runs_verify_service import (
        MANIFEST_FILENAME,
        write_manifest,
        write_touchstone_sidecar,
    )

    snp = sorted((run / "results").glob("params.s*p"))[0]
    write_touchstone_sidecar(snp, run_id=run.name)
    write_manifest(run)
    assert (run / MANIFEST_FILENAME).is_file()


def _boom_verify(monkeypatch) -> None:
    """verify 面故障注入（#105 钉：观测面故障不阻塞消费主路径）。"""

    def _boom(run_dir):
        raise RuntimeError("verify 通道故障")

    monkeypatch.setattr(
        "rfauto.service.runs_verify_service.verify_run", _boom)


# diagnose 语料（复用既有钉的 R002 触发形态：-3 > -10 触发）
_DIAG_METRICS = {"s11_db_max_in_band": -3.0, "s21_db_mean_in_band": -1.0}
_STALE_WARNING = "结果文件与 run 记录不符，以下诊断可能基于旧产物"
# 顶替内容（与 stamp 时字节不同 → stale_replaced）
_REPLACED_S1P = "# GHz S RI R 50\n1.0 0.9 0.0\n"


# ── diagnose：freshness 块 + stale 头部提示 ─────────────────────────────────


class TestDiagnoseFreshness:
    def test_fresh_run_diagnosis_with_freshness_block(self, tmp_path,
                                                      monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_run(tmp_path / "runs", "r1", metrics=_DIAG_METRICS)
        _stamp(tmp_path / "runs" / "r1")
        data = _call("diagnose", {"run_id": "r1"})
        assert data["ok"] is True
        body = data["data"]
        # 规则诊断本体不因接线变形（R002 语料同既有钉）
        assert {d["rule_id"] for d in body["diagnoses"]} == {"R002"}
        assert body["rules_applied"] == 2
        # freshness 块随响应；fresh 无提示行
        assert "stale_warning" not in body
        assert body["freshness"]["status"] == "fresh"
        assert body["freshness"]["n_issues"] == 0
        assert body["freshness"]["issues"] == []

    def test_stale_run_head_warning(self, tmp_path, monkeypatch):
        """验收场景：metrics.json 被旧内容顶替 → 结论头部醒目提示。"""
        monkeypatch.chdir(tmp_path)
        run = _make_run(tmp_path / "runs", "r_stale",
                        metrics=_DIAG_METRICS)
        _stamp(run)
        (run / "results" / "metrics.json").write_text(
            json.dumps({"run_id": "r_stale",
                        "metrics": {"s11_db_max_in_band": -20.0}}),
            encoding="utf-8")
        data = _call("diagnose", {"run_id": "r_stale"})
        # 提示不硬拒：诊断照常成立（ok=True），但结论头部带醒目行
        assert data["ok"] is True
        body = data["data"]
        assert body["stale_warning"] == _STALE_WARNING
        assert next(iter(body)) == "stale_warning"  # 结论头部
        assert body["freshness"]["status"] == "stale"
        kinds = {issue["kind"] for issue in body["freshness"]["issues"]}
        assert "stale_replaced" in kinds
        assert "stale_replaced" in body["freshness"]["note"]
        # 诊断数字反映盘上（被顶替后的）内容——正是提示要防的采信风险
        assert body["diagnoses"] == []

    def test_legacy_run_passes_with_note(self, tmp_path, monkeypatch):
        """无 manifest 老 run → legacy 放行带 note（增量兼容红线）。"""
        monkeypatch.chdir(tmp_path)
        _make_run(tmp_path / "runs", "r_legacy", metrics=_DIAG_METRICS)
        data = _call("diagnose", {"run_id": "r_legacy"})
        assert data["ok"] is True
        body = data["data"]
        assert "stale_warning" not in body
        assert body["freshness"]["status"] == "legacy"
        assert "legacy" in body["freshness"]["note"]

    def test_verify_face_failure_marks_unknown(self, tmp_path, monkeypatch):
        """verify 面故障不阻塞诊断（#105）：status=unknown + note。"""
        monkeypatch.chdir(tmp_path)
        _make_run(tmp_path / "runs", "r_u", metrics=_DIAG_METRICS)
        _stamp(tmp_path / "runs" / "r_u")
        _boom_verify(monkeypatch)
        data = _call("diagnose", {"run_id": "r_u"})
        assert data["ok"] is True
        body = data["data"]
        assert "stale_warning" not in body
        assert body["freshness"]["status"] == "unknown"
        assert "不可用" in body["freshness"]["note"]
        # 诊断主路径照常（R002 语料不因校验面故障丢失）
        assert {d["rule_id"] for d in body["diagnoses"]} == {"R002"}

    def test_missing_run_error_envelope_unchanged(self, tmp_path,
                                                  monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = _call("diagnose", {"run_id": "ghost_run"})
        assert data["ok"] is False
        assert data["errors"]


# ── compare_runs：行级 freshness 列（A3 batch_ops 先例形态） ────────────────


class TestCompareRunsFreshness:
    def test_stale_side_named_not_rejected(self, tmp_path, monkeypatch):
        """stale 标红不硬拒：notes 点名脏侧，对比结论可读出哪边是脏数据。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        _make_run(root, "r_a", metrics={"s11_db": -10.0}, cost=0.1)
        _stamp(root / "r_a")
        _make_run(root, "r_b", metrics={"s11_db": -30.0}, cost=0.3)
        _stamp(root / "r_b")
        # 顶替 r_b 的 Touchstone（对比面只读指标不读 sNp——freshness
        # 列须抓到对比数据本身看不见的错配）
        (root / "r_b" / "results" / "params.s1p").write_text(
            _REPLACED_S1P, encoding="utf-8")
        data = _call("compare_runs",
                     {"run_id_a": "r_a", "run_id_b": "r_b"})
        assert data["ok"] is True
        body = data["data"]
        rows = {row["side"]: row for row in body["freshness"]}
        assert rows["a"]["run_id"] == "r_a"
        assert rows["a"]["freshness"] == "fresh"
        assert rows["b"]["freshness"] == "stale"
        assert "stale_replaced" in rows["b"]["freshness_note"]
        assert any("r_b" in note and "stale" in note
                   for note in body["notes"])
        # 对比本体不因接线变形（逐指标 delta 语义不变）
        assert body["metrics"]["s11_db"]["delta"] == pytest.approx(-20.0)

    def test_legacy_rows_pass_with_note(self, tmp_path, monkeypatch):
        """无 manifest 老 run → legacy 放行带 note，无 notes（无脏侧）。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        _make_run(root, "r_l1", metrics={"s11_db": -10.0})
        _make_run(root, "r_l2", metrics={"s11_db": -20.0})
        data = _call("compare_runs",
                     {"run_id_a": "r_l1", "run_id_b": "r_l2"})
        assert data["ok"] is True
        body = data["data"]
        assert [row["freshness"] for row in body["freshness"]] == [
            "legacy", "legacy"]
        assert all("legacy" in row["freshness_note"]
                   for row in body["freshness"])
        assert "notes" not in body

    def test_verify_face_failure_marks_unknown_not_dirty(self, tmp_path,
                                                         monkeypatch):
        """双侧 unknown（#105）：不阻塞对比，也不冒充脏侧点名。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        _make_run(root, "r_u1", metrics={"s11_db": -10.0})
        _stamp(root / "r_u1")
        _make_run(root, "r_u2", metrics={"s11_db": -20.0})
        _stamp(root / "r_u2")
        _boom_verify(monkeypatch)
        data = _call("compare_runs",
                     {"run_id_a": "r_u1", "run_id_b": "r_u2"})
        assert data["ok"] is True
        body = data["data"]
        assert [row["freshness"] for row in body["freshness"]] == [
            "unknown", "unknown"]
        assert all("不可用" in row["freshness_note"]
                   for row in body["freshness"])
        assert "notes" not in body  # unknown 不冒充脏

    def test_missing_run_error_envelope_untouched(self, tmp_path,
                                                  monkeypatch):
        """run 缺失 → service error 信封原样透传（不注入 freshness）。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        _make_run(root, "r_only", metrics={"s11_db": -10.0})
        data = _call("compare_runs",
                     {"run_id_a": "r_only", "run_id_b": "ghost_run"})
        assert data["ok"] is False
        assert data["errors"]
        assert "freshness" not in data
