"""runs_verify_service 测试（K4，aurora_k，P11/F7：结果新鲜度与溯源）。

用户验收场景原话钉面："把 13:05 的旧 s1p 放进新 run 目录，``runs verify``
必须报 stale，不能静默通过"——即 manifest 收官指纹与盘上 Touchstone 内容
sha256 不符时必须红（stale_replaced）。四态语义：fresh / stale（stale_
replaced·missing·unreadable·snapshot_replaced·snapshot_missing·
sidecar_mismatch·manifest_corrupt 任一命中）/ legacy（无 manifest 放行带
note）/ untracked_new（信息级，不算 stale）。

K20 审查修复钉面（aurora_l Wave-A A1）：
- ``unreadable``（文件读不出，Windows 文件锁/OSError 形态）必须 stale 级
  ——原实现记 issue 却不入 _STALE_KINDS，行内注释"不静默放行"与实际
  fresh 放行相反；
- manifest 记录的 recipe 快照哈希必须回查（snapshot_replaced/snapshot_
  missing 均 stale 级；老 manifest 缺段跳过）；
- 声明式产物（results/metrics.json、results/report.md）入指纹段——报告
  主数据源被顶替必须红（老 manifest 缺 ``artifacts`` 段跳过）。

K20 审查④钉面（aurora_l Wave-B B2）：``replay_run``（``rfauto replay``）
接 freshness gate——源 run 快照被顶替时拒重跑（snapshot_replaced 不冠源
run 之名重跑）；legacy/fresh 放行带 freshness 观测字段。

全部确定性：合成 run 落 tmp_path，零真机零网络零 runs/ 湖写入。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.service.runs_verify_service import (
    MANIFEST_FILENAME,
    manifest_for_run,
    verify_run,
    write_manifest,
    write_touchstone_sidecar,
)

# ── 合成 run 构造（HFSS 头形态见 runs/20260916_213017_93dabfa3 真实样本）──

_HFSS_HEADER = (
    "! Touchstone file exported from HFSS 2025.1.0\n"
    "!        File:           D:/rf_workspace/runs/fake_run/hfss/design.aedt\n"
    "!        Generated:      07:29:41 PM Oct 22, 2026\n"
    "!        Design:         RFADesign\n"
    "# Hz S RI R 50\n"
)

_OLD_HEADER = _HFSS_HEADER.replace("Oct 22", "Oct 21")  # 13:05 旧工程形态


def _make_run(tmp_path: Path, name: str = "run_k4") -> Path:
    run = tmp_path / name
    (run / "results").mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({
        "run_id": name, "adapter": "hfss", "model": "patch_antenna",
        "status": "done", "aedt_version": "2025.1.0", "git_sha": "abc1234",
        "package_version": "1.0.0", "study_name": name,
        "timestamp": "2026-10-22T19:29:41+00:00",
    }), encoding="utf-8")
    (run / "recipe.snapshot.yaml").write_text(
        "model: patch_antenna\nparams: {}\n", encoding="utf-8")
    (run / "results" / "params.s1p").write_text(
        _HFSS_HEADER + "1.0e9 0.1 0.0\n", encoding="utf-8")
    # K20 审查③：声明式产物（报告主数据源）——manifest 生成走 write_manifest
    # 同源，fresh 路径用例经此自动覆盖 artifacts 指纹段（不手写 manifest）
    (run / "results" / "metrics.json").write_text(json.dumps({
        "metrics": {"s11_db": -20.0}, "cost": 0.04,
    }), encoding="utf-8")
    (run / "results" / "report.md").write_text(
        "# run report\nverdict: PASS\n", encoding="utf-8")
    return run


def _stamp(run: Path) -> None:
    """收官指纹：sidecar + manifest（run_once 收尾链路同序）。"""
    snp = sorted((run / "results").glob("params.s*p"))
    assert snp, "合成 run 应含 params.sNp"
    write_touchstone_sidecar(
        snp[0], run_id=run.name,
        design_name="RFADesign", setup="Setup1", sweep="Sweep1")
    write_manifest(run)


# ── 四态 ────────────────────────────────────────────────────────────────────


class TestVerifyStates:
    def test_fresh(self, tmp_path: Path) -> None:
        run = _make_run(tmp_path)
        _stamp(run)
        result = verify_run(run)
        assert result["ok"] is True
        assert result["status"] == "fresh"
        assert result["issues"] == []
        assert result["run_id"] == run.name

    def test_stale_replaced_user_acceptance_scenario(self, tmp_path: Path) -> None:
        """用户验收场景原文：13:05 旧 s1p 放进新 run 目录 → 必须报 stale。"""
        run = _make_run(tmp_path)
        _stamp(run)
        # 19:45 拷回工作区形态：同目录同名文件被旧工程内容顶替
        (run / "results" / "params.s1p").write_text(
            _OLD_HEADER + "1.0e9 0.9 0.0\n", encoding="utf-8")
        result = verify_run(run)
        assert result["ok"] is False
        assert result["status"] == "stale"
        kinds = {issue["kind"] for issue in result["issues"]}
        assert "stale_replaced" in kinds
        # sidecar 跟文件走且未被同步改写 → 文件级错配证据同时在场
        assert "sidecar_mismatch" in kinds
        assert any("旧" in err or "不符" in err for err in result["errors"])

    def test_missing_recorded_touchstone(self, tmp_path: Path) -> None:
        """漏拷形态：manifest 记录的文件不在盘上。"""
        run = _make_run(tmp_path)
        _stamp(run)
        (run / "results" / "params.s1p").unlink()
        result = verify_run(run)
        assert result["ok"] is False
        assert result["status"] == "stale"
        assert any(issue["kind"] == "missing" for issue in result["issues"])

    def test_legacy_run_passes_with_note(self, tmp_path: Path) -> None:
        """增量兼容红线：老 run 无 manifest → legacy 放行，ok=True 不伪造。"""
        run = _make_run(tmp_path)
        assert not (run / MANIFEST_FILENAME).exists()
        result = verify_run(run)
        assert result["ok"] is True
        assert result["status"] == "legacy"
        assert result["legacy"] is True
        assert "legacy" in result["note"]

    def test_untracked_new_is_informational_not_stale(self, tmp_path: Path) -> None:
        """manifest 未登记且 mtime 晚于 manifest 生成 → untracked_new，仍 fresh。"""
        run = _make_run(tmp_path)
        _stamp(run)
        manifest = json.loads(
            (run / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        extra = run / "results" / "extra_curve.s2p"
        extra.write_text("# Hz S RI R 50\n1e9 0 0 0 0\n", encoding="utf-8")
        from datetime import datetime

        newer = datetime.fromisoformat(manifest["generated_at"]).timestamp() + 60
        os.utime(extra, (newer, newer))
        result = verify_run(run)
        assert result["status"] == "fresh"
        assert result["ok"] is True
        kinds = {issue["kind"] for issue in result["issues"]}
        assert "untracked_new" in kinds
        assert not (kinds & {"stale_replaced", "missing", "sidecar_mismatch"})

    def test_corrupt_manifest_is_stale(self, tmp_path: Path) -> None:
        """manifest 损坏=无法作证 → 不静默通过（多报不放过 #316）。"""
        run = _make_run(tmp_path)
        _stamp(run)
        (run / MANIFEST_FILENAME).write_text("{trunc", encoding="utf-8")
        result = verify_run(run)
        assert result["ok"] is False
        assert result["status"] == "stale"
        assert any(issue["kind"] == "manifest_corrupt"
                   for issue in result["issues"])

    def test_nonexistent_dir_is_clean_error(self, tmp_path: Path) -> None:
        result = verify_run(tmp_path / "no_such_run")
        assert result["ok"] is False
        assert result["status"] == "error"
        assert result["issues"] == []


# ── K20 审查修复钉：unreadable / recipe 快照回查 / 声明式产物指纹 ────────────


class TestUnreadableIsStale:
    """K20 审查 P1：读不出来即按不可信处理——unreadable 必须 stale 级。"""

    def test_unreadable_touchstone_is_stale(self, tmp_path: Path,
                                            monkeypatch) -> None:
        """平台无关钉：_sha256_file 抛 OSError（文件锁/权限形态）→ stale。"""
        run = _make_run(tmp_path)
        _stamp(run)
        from rfauto.service import runs_verify_service as rvs

        def _boom(path: Path) -> str:
            raise OSError(13, "Permission denied（模拟文件锁占位）")

        monkeypatch.setattr(rvs, "_sha256_file", _boom)
        result = verify_run(run)
        assert result["ok"] is False
        assert result["status"] == "stale"
        kinds = {issue["kind"] for issue in result["issues"]}
        assert "unreadable" in kinds

    @pytest.mark.skipif(sys.platform != "win32",
                        reason="Windows 句柄锁形态；平台无关钉见上一用例")
    def test_unreadable_locked_file_windows_is_stale(
            self, tmp_path: Path) -> None:
        """真文件形态钉：msvcrt 句柄锁占位全文件 → 读取 OSError → stale。

        锁语义环境差异诚实处理：锁后探测读取仍可成功则如实 skip（不假绿
        不硬红）。
        """
        import msvcrt

        run = _make_run(tmp_path)
        _stamp(run)
        snp = run / "results" / "params.s1p"
        size = snp.stat().st_size
        from rfauto.service.runs_verify_service import _sha256_file

        # 句柄必须跨 verify_run 持有（文件锁占位的生命周期所在），禁 with
        fh = open(snp, "rb")  # noqa: SIM115
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, size)
            try:
                try:
                    _sha256_file(snp)
                except OSError:
                    pass
                else:
                    pytest.skip("该环境句柄锁未阻断读取（模拟前提不成立）")
                result = verify_run(run)
            finally:
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, size)
        finally:
            fh.close()
        assert result["ok"] is False
        assert result["status"] == "stale"
        assert any(issue["kind"] == "unreadable"
                   for issue in result["issues"])


class TestRecipeSnapshotCheck:
    """K20 审查②：manifest 记了快照哈希就必须回查——旧快照不能冒充 fresh。"""

    def test_snapshot_replaced_is_stale(self, tmp_path: Path) -> None:
        run = _make_run(tmp_path)
        _stamp(run)
        (run / "recipe.snapshot.yaml").write_text(
            "model: old_model\nparams: {}\n", encoding="utf-8")
        result = verify_run(run)
        assert result["ok"] is False
        assert result["status"] == "stale"
        kinds = {issue["kind"] for issue in result["issues"]}
        assert "snapshot_replaced" in kinds

    def test_snapshot_missing_is_stale(self, tmp_path: Path) -> None:
        """快照是 recipe 证据：记录在而盘上丢 → snapshot_missing，stale 级。"""
        run = _make_run(tmp_path)
        _stamp(run)
        (run / "recipe.snapshot.yaml").unlink()
        result = verify_run(run)
        assert result["ok"] is False
        assert result["status"] == "stale"
        kinds = {issue["kind"] for issue in result["issues"]}
        assert "snapshot_missing" in kinds

    def test_manifest_without_recipe_section_skips(self, tmp_path: Path) -> None:
        """老 manifest 兼容：无 recipe_snapshot 段 → 跳过不报，仍 fresh。"""
        run = _make_run(tmp_path)
        _stamp(run)
        manifest = json.loads(
            (run / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        manifest.pop("recipe_snapshot", None)
        (run / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        result = verify_run(run)
        assert result["ok"] is True
        assert result["status"] == "fresh"
        assert result["issues"] == []


class TestDeclarativeArtifactFingerprints:
    """K20 审查③：声明式产物入指纹——报告主数据源被顶替必须红。"""

    def test_manifest_records_artifacts_when_present(
            self, tmp_path: Path) -> None:
        """存在才记：metrics.json/report.md 入指纹；不存在不记不报。"""
        run = _make_run(tmp_path)
        manifest = manifest_for_run(run)
        assert manifest["artifacts"]["results/metrics.json"]["sha256"] == \
            hashlib.sha256(
                (run / "results" / "metrics.json").read_bytes()).hexdigest()
        assert manifest["artifacts"]["results/report.md"]["sha256"] == \
            hashlib.sha256(
                (run / "results" / "report.md").read_bytes()).hexdigest()
        # 不存在不记不报
        (run / "results" / "report.md").unlink()
        assert "results/report.md" not in manifest_for_run(run)["artifacts"]

    def test_metrics_json_replaced_is_stale(self, tmp_path: Path) -> None:
        run = _make_run(tmp_path)
        _stamp(run)
        (run / "results" / "metrics.json").write_text(json.dumps({
            "metrics": {"s11_db": -0.1}, "cost": 9.9,
        }), encoding="utf-8")
        result = verify_run(run)
        assert result["ok"] is False
        assert result["status"] == "stale"
        assert any(issue["kind"] == "stale_replaced"
                   and issue["path"] == "results/metrics.json"
                   for issue in result["issues"])

    def test_manifest_without_artifacts_section_is_touchstone_only(
            self, tmp_path: Path) -> None:
        """老 manifest 兼容：只指纹过 Touchstone（缺 artifacts 段）→ 跳过。"""
        run = _make_run(tmp_path)
        _stamp(run)
        manifest = json.loads(
            (run / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        manifest.pop("artifacts", None)
        (run / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        # metrics.json 被顶替也不红（老 manifest 只作证 Touchstone 面）
        (run / "results" / "metrics.json").write_text("{}", encoding="utf-8")
        result = verify_run(run)
        assert result["ok"] is True
        assert result["status"] == "fresh"


# ── manifest / sidecar 内容钉 ────────────────────────────────────────────────


class TestManifestAndSidecar:
    def test_manifest_records_touchstone_and_recipe_hash(self, tmp_path: Path) -> None:
        run = _make_run(tmp_path)
        manifest = manifest_for_run(run)
        assert manifest["touchstones"]["results/params.s1p"]["sha256"] == \
            hashlib.sha256(
                (run / "results" / "params.s1p").read_bytes()).hexdigest()
        assert manifest["recipe_snapshot"]["sha256"] == \
            hashlib.sha256((run / "recipe.snapshot.yaml").read_bytes()).hexdigest()
        # meta 已有字段直接引用不重算
        assert manifest["meta_ref"]["aedt_version"] == "2025.1.0"
        assert manifest["meta_ref"]["git_sha"] == "abc1234"
        assert manifest["run_id"] == run.name
        assert manifest["touchstone_count"] == 1

    def test_manifest_for_run_rejects_missing_dir(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            manifest_for_run(tmp_path / "nope")

    def test_sidecar_hash_pin(self, tmp_path: Path) -> None:
        """sidecar sha256 必须钉住文件内容（run_id+设计名+导出时间齐备）。"""
        run = _make_run(tmp_path)
        result = write_touchstone_sidecar(
            run / "results" / "params.s1p", run_id=run.name,
            design_name="RFADesign", setup="Setup1", sweep="Sweep1")
        sidecar = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        assert sidecar["sha256"] == hashlib.sha256(
            (run / "results" / "params.s1p").read_bytes()).hexdigest()
        assert sidecar["run_id"] == run.name
        assert sidecar["design_name"] == "RFADesign"
        assert sidecar["setup"] == "Setup1"
        assert sidecar["exported_at"]

    def test_write_manifest_envelope(self, tmp_path: Path) -> None:
        run = _make_run(tmp_path)
        result = write_manifest(run)
        assert result["ok"] is True
        assert (run / MANIFEST_FILENAME).is_file()

    def test_sidecar_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            write_touchstone_sidecar(tmp_path / "ghost.s1p", run_id="x")


# ── CLI 冒烟（runs verify，--json 双路径）────────────────────────────────────


class TestCliRunsVerify:
    def test_cli_fresh_exit_zero(self, tmp_path: Path) -> None:
        run = _make_run(tmp_path)
        _stamp(run)
        result = CliRunner().invoke(root_app, ["runs", "verify", str(run)])
        assert result.exit_code == 0
        assert "fresh" in result.stdout

    def test_cli_stale_exit_one_human_readable(self, tmp_path: Path) -> None:
        run = _make_run(tmp_path)
        _stamp(run)
        (run / "results" / "params.s1p").write_text(
            _OLD_HEADER + "1.0e9 0.9 0.0\n", encoding="utf-8")
        result = CliRunner().invoke(root_app, ["runs", "verify", str(run)])
        assert result.exit_code == 1
        assert "stale" in result.stdout
        assert "stale_replaced" in result.stdout

    def test_cli_stale_json_envelope(self, tmp_path: Path) -> None:
        run = _make_run(tmp_path)
        _stamp(run)
        (run / "results" / "params.s1p").write_text(
            _OLD_HEADER + "1.0e9 0.9 0.0\n", encoding="utf-8")
        result = CliRunner().invoke(
            root_app, ["runs", "verify", str(run), "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["status"] == "stale"
        assert payload["run_id"] == run.name

    def test_cli_run_id_resolution_under_runs_root(self, tmp_path: Path,
                                                   monkeypatch) -> None:
        """run_id 短名解析：显式路径不在场时回退 runs/<run_id>。"""
        run = _make_run(tmp_path / "runs")
        _stamp(run)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(root_app, ["runs", "verify", run.name])
        assert result.exit_code == 0
        assert "fresh" in result.stdout

    def test_cli_legacy_passes(self, tmp_path: Path) -> None:
        run = _make_run(tmp_path)
        result = CliRunner().invoke(root_app, ["runs", "verify", str(run)])
        assert result.exit_code == 0
        assert "legacy" in result.stdout


# ── report 拒 stale（freshness gate）────────────────────────────────────────


def _make_report_run(tmp_path: Path, name: str = "run_report") -> Path:
    """report 链路可渲染的最小 run（meta/sparams.csv/verdict；DP-13 同构）。"""
    run = tmp_path / name
    run.mkdir()
    (run / "meta.json").write_text(json.dumps({
        "template": "mline", "engine": "openems", "stage": "sample",
        "mesh_mm": 0.3, "n_ports": 2,
    }, ensure_ascii=False), encoding="utf-8")
    rows = ["freq_hz,re_S11,im_S11,re_S21,im_S21"]
    for i in range(5):
        rows.append(f"{(2.0 + 0.25 * i) * 1e9:.1f},0.06,0.08,0.5,0.5")
    (run / "sparams.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (run / "results").mkdir()
    (run / "results" / "params.s2p").write_text(
        "# Hz S RI R 50\n1e9 0 0 0 0\n", encoding="utf-8")
    return run


class TestReportFreshnessGate:
    def test_report_rejects_stale(self, tmp_path: Path) -> None:
        from rfauto.service.report_render import render_run_report

        run = _make_report_run(tmp_path)
        _stamp(run)
        # 用户病灶形态：旧工程 s2p 顶替新产物 → report 拒绝出图
        (run / "results" / "params.s2p").write_text(
            "# Hz S RI R 50\n1e9 0.9 0.0 0.0 0.0\n", encoding="utf-8")
        result = render_run_report(run)
        assert result["ok"] is False
        assert result["stage"] == "freshness_gate"
        assert result["status"] == "stale"
        assert any(issue["kind"] == "stale_replaced"
                   for issue in result["issues"])

    def test_report_fresh_passes_with_status(self, tmp_path: Path) -> None:
        from rfauto.service.report_render import render_run_report

        run = _make_report_run(tmp_path)
        _stamp(run)
        result = render_run_report(run)
        assert result["ok"] is True
        assert result["freshness"]["status"] == "fresh"

    def test_report_legacy_passes_with_note(self, tmp_path: Path) -> None:
        """增量兼容：老 run（无 manifest）报告行为不变，仅带 note。"""
        from rfauto.service.report_render import render_run_report

        run = _make_report_run(tmp_path)
        result = render_run_report(run)
        assert result["ok"] is True
        assert result["freshness"]["status"] == "legacy"
        assert "legacy" in result["freshness"]["note"]

    def test_report_nonexistent_dir_clean_error_unchanged(self,
                                                          tmp_path: Path) -> None:
        from rfauto.service.report_render import render_run_report

        result = render_run_report(tmp_path / "ghost_run")
        assert result == {"ok": False,
                          "error": f"run 目录不存在：{tmp_path / 'ghost_run'}"}


# ── replay 拒 stale（freshness gate，K20 审查④）────────────────────────────


class TestReplayFreshnessGate:
    """replay 是"复现源 run 配方"的入口：快照被顶替必须拒重跑（generate_
    report_for_run 同款语义：stale 拒、legacy/fresh 放行带 note）。"""

    def _run_once_fake(self, tmp_path: Path, monkeypatch) -> dict:
        monkeypatch.chdir(tmp_path)  # run 目录 cwd 相对解析（#144 家族）
        import yaml

        recipe = tmp_path / "recipe_patch.yaml"
        recipe.write_text(yaml.safe_dump({
            "model": "patch_antenna",
            "params": {"f0_ghz": {"value": 2.4, "unit": "GHz"}},
            "setup": {},
            "objectives": [],
        }), encoding="utf-8")
        from rfauto.service.api import run_once

        result = run_once(str(recipe), adapter_name="fake")
        assert result["ok"] is True, result.get("errors")
        return result

    def test_replay_rejects_stale_snapshot_replaced(
            self, tmp_path: Path, monkeypatch) -> None:
        """K20 审查②同款形态：源 run 快照被旧配方顶替 → replay 拒（不冠源
        run 之名重跑被顶替后的配方）。"""
        result = self._run_once_fake(tmp_path, monkeypatch)
        source_run = Path("runs") / str(result["run_id"])
        (source_run / "recipe.snapshot.yaml").write_text(
            "model: old_model\nparams: {}\n", encoding="utf-8")
        from rfauto.service.api import replay_run

        replayed = replay_run(str(result["run_id"]))
        assert replayed["ok"] is False
        assert replayed["stage"] == "freshness_gate"
        assert replayed["status"] == "stale"
        assert any(issue["kind"] == "snapshot_replaced"
                   for issue in replayed["issues"])
        assert replayed.get("replay_run_id") is None  # 未重跑

    def test_replay_fresh_passes_with_status(
            self, tmp_path: Path, monkeypatch) -> None:
        result = self._run_once_fake(tmp_path, monkeypatch)
        from rfauto.service.api import replay_run

        replayed = replay_run(str(result["run_id"]))
        assert replayed["ok"] is True, replayed.get("errors")
        assert replayed["freshness"]["status"] == "fresh"

    def test_replay_legacy_passes_with_note(
            self, tmp_path: Path, monkeypatch) -> None:
        """增量兼容：老 run（无 manifest）replay 行为不变，仅带 note。"""
        result = self._run_once_fake(tmp_path, monkeypatch)
        source_run = Path("runs") / str(result["run_id"])
        (source_run / MANIFEST_FILENAME).unlink()
        from rfauto.service.api import replay_run

        replayed = replay_run(str(result["run_id"]))
        assert replayed["ok"] is True, replayed.get("errors")
        assert replayed["freshness"]["status"] == "legacy"
        assert "legacy" in replayed["freshness"]["note"]


# ── run_once 收尾接线（fake 通道端到端，chdir 隔离 #144）──────────────────


class TestRunOnceWiring:
    def test_run_once_writes_manifest_and_sidecar(self, tmp_path: Path,
                                                  monkeypatch) -> None:
        """run_once（fake）收官后 run 目录含 manifest.json 与 sidecar。"""
        monkeypatch.chdir(tmp_path)  # run 目录 cwd 相对解析（#144 家族）
        import yaml

        recipe = tmp_path / "recipe_patch.yaml"
        recipe.write_text(yaml.safe_dump({
            "model": "patch_antenna",
            "params": {"f0_ghz": {"value": 2.4, "unit": "GHz"}},
            "setup": {},
            "objectives": [],
        }), encoding="utf-8")
        from rfauto.service.api import run_once

        result = run_once(str(recipe), adapter_name="fake")
        assert result["ok"] is True, result.get("errors")
        run_dir = Path(result["run_dir"])
        assert (run_dir / MANIFEST_FILENAME).is_file()
        snp = sorted((run_dir / "results").glob("params.s*p"))
        assert snp, "fake 通道应导出 Touchstone"
        assert (run_dir / "results" / f"{snp[0].name}.meta.json").is_file()
        # 收官即刻校验必须 fresh
        assert verify_run(run_dir)["status"] == "fresh"
