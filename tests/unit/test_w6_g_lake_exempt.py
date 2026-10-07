"""W6-G 湖压缩豁免执行单测（合成小湖 fixture，全离线零网络）。

判据映射（runs/w6_phase6/criteria.md W6-G 节，用户裁决：部分批准两子树、
可逆 apply 禁裸删）：
- 豁免白名单口径：仅点名子树解除 no_meta_inflight 保护，其余无 meta 子树
  维持保护不进删除清单；指针/名字启发保护优先于豁免；min_age 新近保留；
- 可逆路径：blob 化（内容寻址 move）+ manifest 逐条 sha 审计；run 树缩容
  bytes_freed 与 plan 对账；同内容二次命中 dedup_existing 不覆盖 blob；
- 恢复面：restore dry-run 逐条 sha 回放零写；target_root 模拟重建字节
  读回一致；purge 逐条清退 blob（run 树零触碰）；
- 30 天观察窗注记进 manifest（purge_after/回填路径/恢复与清退命令一行）。
真实湖面零触碰（真湖 apply 走 runs/w6_phase6/w6g/ 驱动与日志，非测试面）。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from rfauto.cli.main import app
from rfauto.service.lake_compact_service import (
    REVERSIBLE_MANIFEST_FORMAT,
    apply_h5_retention,
    apply_h5_retention_reversible,
    plan_h5_retention,
    purge_blobs_from_manifest,
    restore_h5_from_manifest,
)
from rfauto.service.sim_ci_service import BASELINE_SCHEMA

runner = CliRunner()

_OLD = 3 * 86400.0


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hashes(root: Path, *, skip_blob_store: bool = False) -> dict[str, str]:
    out: dict[str, str] = {}
    for current, _dirs, files in os.walk(root):
        for name in files:
            p = Path(current) / name
            rel = p.relative_to(root).as_posix()
            if skip_blob_store and rel.startswith(".blob_store/"):
                continue
            out[rel] = _sha(p)
    return out


def _age_tree(root: Path, seconds: float = _OLD) -> None:
    for p in root.rglob("*"):
        if p.is_file():
            st = p.stat()
            os.utime(p, (st.st_atime - seconds, st.st_mtime - seconds))


@pytest.fixture()
def exempt_lake(tmp_path: Path) -> dict[str, Path]:
    """豁免形态小湖：点名子树（无 meta 深层 h5，含同内容重复）+未点名
    无 meta 子树（须维持保护）+有 meta judged run（混合形态对照）。"""
    runs = tmp_path / "runs"
    a = b"NF2FF-PAYLOAD-A" * 64
    b = b"NF2FF-PAYLOAD-B" * 64
    (runs / "camp_exempt" / "pt1" / "fdtd").mkdir(parents=True)
    (runs / "camp_exempt" / "pt1" / "fdtd" / "nf2ff_E.h5").write_bytes(a)
    (runs / "camp_exempt" / "pt1" / "fdtd" / "nf2ff_H.h5").write_bytes(b)
    (runs / "camp_exempt" / "pt2" / "fdtd").mkdir(parents=True)
    # 同内容重复（dedup_existing 路径）
    (runs / "camp_exempt" / "pt2" / "fdtd" / "nf2ff_E.h5").write_bytes(a)
    # 未点名子树：无 meta（保护对照）
    (runs / "camp_other" / "pt9").mkdir(parents=True)
    (runs / "camp_other" / "pt9" / "field.h5").write_bytes(b"KEEP-ME")
    # 有 meta judged（medium 正常候选，混合形态）
    judged = runs / "camp_other" / "pt_judged"
    judged.mkdir(parents=True)
    (judged / "field.h5").write_bytes(b"META-H5")
    (judged / "meta.json").write_text(
        json.dumps({"status": "judged", "timestamp": "2026-09-01"}),
        encoding="utf-8")
    _age_tree(runs)
    return {"runs": runs, "judged": judged}


class TestExemptPlan:
    def test_only_named_subtrees_enter_delete_list(self, exempt_lake):
        runs = exempt_lake["runs"]
        plan = plan_h5_retention(runs, tier="medium",
                                 exempt_subtrees=["camp_exempt"])
        assert plan["ok"] is True
        assert plan["exempt_subtrees"] == ["camp_exempt"]
        # 3 豁免行 + 1 meta judged 行（混合形态：medium 正常候选）
        assert plan["n_delete"] == 4
        assert plan["golden_rewrite_audit"]["violations"] == []
        rows = plan["delete"]
        exempt_rows = [r for r in rows if r.get("exempt_subtree")]
        assert len(exempt_rows) == 3
        assert all(r["exempt_subtree"] == "camp_exempt"
                   for r in exempt_rows)
        assert all(r["reason"] == "user_exempt_subtree"
                   for r in exempt_rows)
        assert all(r["path"].startswith("camp_exempt/")
                   for r in exempt_rows)
        # 未点名无 meta 子树维持保护（pt9；pt_judged 是 meta 行属正常候选）
        assert not any(r["path"].startswith("camp_other/pt9")
                       for r in rows)
        assert plan["keep_reasons"].get("no_meta_inflight", 0) >= 1
        # plan 对账：bytes_delete == 清单 size 和
        assert plan["bytes_delete"] == sum(r["size"] for r in rows)
        # 豁免行三档均计入（+meta judged 行本就三档可删）
        for t in ("conservative", "medium", "aggressive"):
            assert plan["tiers"][t]["n_delete"] == 4

    def test_default_none_keeps_legacy_behavior(self, exempt_lake):
        runs = exempt_lake["runs"]
        plan = plan_h5_retention(runs, tier="medium")
        assert plan["ok"] is True
        assert plan["exempt_subtrees"] == []
        assert plan["n_delete"] == 1  # 仅 meta judged 行
        assert plan["delete"][0]["path"].startswith("camp_other/pt_judged")

    @pytest.mark.parametrize("bad", ["../evil", "absent_tree", "C:/x",
                                     "/top", "a\\b"])
    def test_invalid_exempt_subtree_rejected(self, exempt_lake, bad):
        plan = plan_h5_retention(exempt_lake["runs"], tier="medium",
                                 exempt_subtrees=[bad])
        assert plan["ok"] is False
        assert plan.get("errors")

    def test_pointer_protection_beats_exemption(self, exempt_lake,
                                                tmp_path):
        runs = exempt_lake["runs"]
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir(exist_ok=True)
        ptr = knowledge / "anchors.yaml"
        ptr.write_text(
            yaml.safe_dump({"anchors": [{"anchor_id": "x", "provenance": {
                "arbitration_runs": [
                    "runs/camp_exempt/pt1/fdtd/nf2ff_E.h5"]}}]},
                allow_unicode=True), encoding="utf-8")
        plan = plan_h5_retention(
            runs, tier="medium", exempt_subtrees=["camp_exempt"],
            pointer_sources=[(ptr, "anchor_evidence")])
        assert plan["ok"] is True
        assert plan["n_delete"] == 2  # 受保护深目录的 h5 仍保留
        assert not any(r["path"].endswith("pt1/fdtd/nf2ff_E.h5")
                       for r in plan["delete"])
        assert plan["golden_rewrite_audit"]["violations"] == []

    def test_min_age_keeps_fresh_exempt_file(self, exempt_lake):
        runs = exempt_lake["runs"]
        fresh = runs / "camp_exempt" / "pt3"
        fresh.mkdir(parents=True)
        (fresh / "new.h5").write_bytes(b"FRESH")
        plan = plan_h5_retention(runs, tier="medium",
                                 exempt_subtrees=["camp_exempt"])
        assert not any(r["path"].startswith("camp_exempt/pt3")
                       for r in plan["delete"])
        assert plan["keep_reasons"].get("recent_activity", 0) >= 1


class TestReversibleApply:
    def test_blob_move_manifest_and_bytes_account(self, exempt_lake,
                                                  tmp_path):
        runs = exempt_lake["runs"]
        plan = plan_h5_retention(runs, tier="medium",
                                 exempt_subtrees=["camp_exempt"])
        before_tree = _tree_hashes(runs)
        manifest = tmp_path / "rev_manifest.json"
        result = apply_h5_retention_reversible(
            plan, manifest_path=manifest, runs_root=runs,
            observation_days=30)
        assert result["ok"] is True, result.get("errors")
        assert result["n_deleted"] == 4
        assert result["n_moved"] == 3 and result["n_dedup_existing"] == 1
        # run 树缩容与 plan 对账
        assert result["bytes_freed"] == plan["bytes_delete"]
        assert result["bytes_retained"] == plan["bytes_delete"]
        # blob 布局 {store}/h5/<sha16>，字节与原内容一致
        store = runs / ".blob_store" / "h5"
        blobs = sorted(store.glob("*"))
        assert len(blobs) == 3  # 同内容去重后 A/B/META 三份
        want = {b"NF2FF-PAYLOAD-A" * 64, b"NF2FF-PAYLOAD-B" * 64,
                b"META-H5"}
        assert {_sha(p) for p in blobs} == {
            hashlib.sha256(w).hexdigest() for w in want}
        # 原路径全部消失；未点名的无 meta 子树零触碰
        after_tree = _tree_hashes(runs)
        for rel, digest in before_tree.items():
            if rel.startswith("camp_exempt/")                     or rel == "camp_other/pt_judged/field.h5":
                assert rel not in after_tree
            else:
                assert after_tree.get(rel) == digest
        # manifest 审计：格式/逐条 sha/豁免标记
        m = json.loads(manifest.read_text(encoding="utf-8"))
        assert m["format"] == REVERSIBLE_MANIFEST_FORMAT
        assert m["n_entries"] == 4
        assert m["bytes_freed"] == plan["bytes_delete"]
        assert all(e["sha256"] for e in m["entries"])
        assert sum(1 for e in m["entries"]
                   if e["exempt_subtree"] == "camp_exempt") == 3
        assert all(e["operation_commit"] for e in m["entries"])

    def test_observation_window_note_in_manifest(self, exempt_lake,
                                                 tmp_path):
        runs = exempt_lake["runs"]
        plan = plan_h5_retention(runs, tier="medium",
                                 exempt_subtrees=["camp_exempt"])
        manifest = tmp_path / "win_manifest.json"
        result = apply_h5_retention_reversible(
            plan, manifest_path=manifest, runs_root=runs,
            observation_days=30)
        assert result["ok"] is True
        m = json.loads(manifest.read_text(encoding="utf-8"))
        win = m["observation_window"]
        assert win["days"] == 30
        assert win["purge_after"] >= "2026-11"
        assert win["backfill_path"] == "runs/.blob_store/h5"
        assert "restore_h5_from_manifest" in win["restore_command"]
        assert "purge_blobs_from_manifest" in win["purge_command"]
        assert "blob" in win["note"]
        assert result["purge_after"] == win["purge_after"]

    def test_restore_dryrun_sha_replay_zero_write(self, exempt_lake,
                                                  tmp_path):
        runs = exempt_lake["runs"]
        plan = plan_h5_retention(runs, tier="medium",
                                 exempt_subtrees=["camp_exempt"])
        manifest = tmp_path / "m.json"
        assert apply_h5_retention_reversible(
            plan, manifest_path=manifest, runs_root=runs)["ok"] is True
        before = _tree_hashes(runs)
        rep = restore_h5_from_manifest(manifest, runs_root=runs,
                                       dry_run=True)
        assert rep["ok"] is True, rep["errors"]
        assert rep["n_entries"] == 4
        assert rep["n_verified"] == 4
        assert rep["n_missing_blob"] == 0
        assert _tree_hashes(runs) == before  # dry-run 零写面

    def test_restore_rebuilds_layout_bytes_identical(self, exempt_lake,
                                                     tmp_path):
        runs = exempt_lake["runs"]
        originals = {
            "camp_exempt/pt1/fdtd/nf2ff_E.h5": b"NF2FF-PAYLOAD-A" * 64,
            "camp_exempt/pt1/fdtd/nf2ff_H.h5": b"NF2FF-PAYLOAD-B" * 64,
            "camp_exempt/pt2/fdtd/nf2ff_E.h5": b"NF2FF-PAYLOAD-A" * 64,
            "camp_other/pt_judged/field.h5": b"META-H5",
        }
        plan = plan_h5_retention(runs, tier="medium",
                                 exempt_subtrees=["camp_exempt"])
        manifest = tmp_path / "m.json"
        assert apply_h5_retention_reversible(
            plan, manifest_path=manifest, runs_root=runs)["ok"] is True
        target = tmp_path / "rebuilt"
        rep = restore_h5_from_manifest(manifest, runs_root=runs,
                                       target_root=target)
        assert rep["ok"] is True, rep["errors"]
        assert rep["n_restored"] == 4
        for rel, payload in originals.items():
            assert (target / rel).read_bytes() == payload

    def test_purge_releases_blobs_only(self, exempt_lake, tmp_path):
        runs = exempt_lake["runs"]
        plan = plan_h5_retention(runs, tier="medium",
                                 exempt_subtrees=["camp_exempt"])
        manifest = tmp_path / "m.json"
        assert apply_h5_retention_reversible(
            plan, manifest_path=manifest, runs_root=runs)["ok"] is True
        after_apply = _tree_hashes(runs)
        rep = purge_blobs_from_manifest(manifest, runs_root=runs)
        assert rep["ok"] is True, rep["errors"]
        # 同内容 A 双条目共享一个 blob：物理清退 3 份（A 只删一次）
        assert rep["n_purged"] == 3 and rep["n_missing"] == 1
        m = json.loads(manifest.read_text(encoding="utf-8"))
        distinct = {e["sha256"]: e["size"] for e in m["entries"]}
        assert rep["bytes_released"] == sum(distinct.values())
        assert not any((runs / ".blob_store" / "h5").iterdir())
        # purge 只动 blob，run 树零触碰（树哈希剔除 blob store 面）
        assert _tree_hashes(runs, skip_blob_store=True) == {
            k: v for k, v in after_apply.items()
            if not k.startswith(".blob_store/")}
        rep2 = purge_blobs_from_manifest(manifest, runs_root=runs)
        assert rep2["n_missing"] == 4 and rep2["n_purged"] == 0

    def test_tampered_plan_rows_refused(self, exempt_lake, tmp_path):
        runs = exempt_lake["runs"]
        plan = plan_h5_retention(runs, tier="medium",
                                 exempt_subtrees=["camp_exempt"])
        # 篡改 1：豁免标记与 plan 回显不一致
        bad = dict(plan)
        bad["delete"] = [dict(plan["delete"][0],
                              exempt_subtree="camp_other")]
        manifest = tmp_path / "m1.json"
        r1 = apply_h5_retention_reversible(
            bad, manifest_path=manifest, runs_root=runs)
        assert r1["ok"] is False and r1["n_deleted"] == 0
        # 篡改 2：路径越出豁免子树
        bad2 = dict(plan)
        bad2["delete"] = [dict(plan["delete"][0], path="camp_other/pt9/"
                               "field.h5")]
        r2 = apply_h5_retention_reversible(
            bad2, manifest_path=tmp_path / "m2.json", runs_root=runs)
        assert r2["ok"] is False and r2["n_deleted"] == 0
        # 零动：目标全部仍在
        assert (runs / "camp_exempt" / "pt1" / "fdtd"
                / "nf2ff_E.h5").is_file()

    def test_no_meta_disappearing_refused_meta_rows(self, exempt_lake,
                                                    tmp_path):
        runs = exempt_lake["runs"]
        plan = plan_h5_retention(runs, tier="medium")  # meta judged 行
        (exempt_lake["judged"] / "meta.json").unlink()
        r = apply_h5_retention_reversible(
            plan, manifest_path=tmp_path / "m.json", runs_root=runs)
        assert r["ok"] is False
        assert any("#144" in e for e in r.get("errors") or [])
        assert (runs / "camp_other" / "pt_judged" / "field.h5").is_file()

    def test_legacy_delete_refuses_exempt_plan_fail_closed(
            self, exempt_lake, tmp_path):
        """直删函数不识豁免行（无 meta）→ fail-closed 拒绝且零动（安全语义）。"""
        runs = exempt_lake["runs"]
        plan = plan_h5_retention(runs, tier="medium",
                                 exempt_subtrees=["camp_exempt"])
        r = apply_h5_retention(plan, manifest_path=tmp_path / "m.json",
                               runs_root=runs)
        # meta judged 行照删；3 豁免行 fail-closed 拒绝（errors 如实）
        assert r["ok"] is False and r["n_deleted"] == 1
        assert len(r.get("errors") or []) >= 3
        assert (runs / "camp_exempt" / "pt1" / "fdtd"
                / "nf2ff_E.h5").exists()
        # 直删路径不产生 blob store（历史行为保持）
        assert not (runs / ".blob_store" / "h5").exists()


class TestCliExemptCompact:
    @pytest.fixture()
    def pinned(self, exempt_lake, tmp_path):
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir()
        (knowledge / "simci_baseline.yaml").write_text(
            yaml.safe_dump({"schema": BASELINE_SCHEMA,
                            "pinned_run_id": "pt_x",
                            "model_run_ids": {}},
                           allow_unicode=True), encoding="utf-8")
        return knowledge / "simci_baseline.yaml"

    def test_cli_apply_reversible_default(self, exempt_lake, pinned,
                                          tmp_path):
        runs = exempt_lake["runs"]
        manifest = tmp_path / "cli_m.json"
        result = runner.invoke(app, [
            "lake", "compact", "--runs-root", str(runs),
            "--baseline-path", str(pinned),
            "--exempt-subtree", "camp_exempt",
            "--manifest", str(manifest), "--apply", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["n_deleted"] == 4
        assert payload["n_moved"] + payload["n_dedup_existing"] == 4
        assert (runs / ".blob_store" / "h5").is_dir()
        assert manifest.is_file()

    def test_cli_no_reversible_keeps_unlink(self, exempt_lake, pinned,
                                            tmp_path):
        runs = exempt_lake["runs"]
        manifest = tmp_path / "cli_m2.json"
        # 直删路径不带豁免（历史语义）：meta judged 行照删
        result = runner.invoke(app, [
            "lake", "compact", "--runs-root", str(runs),
            "--baseline-path", str(pinned),
            "--no-reversible",
            "--manifest", str(manifest), "--apply", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True and payload["n_deleted"] == 1
        assert not (runs / ".blob_store" / "h5").exists()

    def test_cli_no_reversible_rejects_exempt(self, exempt_lake, pinned,
                                              tmp_path):
        result = runner.invoke(app, [
            "lake", "compact", "--runs-root", str(exempt_lake["runs"]),
            "--baseline-path", str(pinned),
            "--exempt-subtree", "camp_exempt",
            "--no-reversible", "--apply", "--json"])
        assert result.exit_code == 2
        assert "reversible" in result.output

    def test_cli_help_carries_new_flags(self):
        # COLUMNS=200 宽渲染：rich 截断点随平台漂移（Linux CI 假红
        # 2026-10-07 首跑实证）——宽端旗标完整渲染，断言跨平台稳定
        # typer rich_utils 在【导入期】读 TERMINAL_WIDTH 存 MAX_WIDTH
        # 全局（invoke 期 env 太晚，2026-10-07 二跑实证 COLUMNS 单独
        # 无效）——render 期逐次读模块全局，monkeypatch 确定生效。
        import pytest
        import typer.rich_utils
        with pytest.MonkeyPatch.context() as _mp:
            _mp.setattr(typer.rich_utils, "MAX_WIDTH", 200)
            result = runner.invoke(app, ["lake", "compact", "--help"])
        assert result.exit_code == 0, result.output
        assert "--exempt-subtree" in result.output
        assert "--reversible" in result.output
