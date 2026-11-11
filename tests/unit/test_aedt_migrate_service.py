"""aedt_migrate service 决策树全路由 fake 测试（aurora_r AM-S1，纯离线零 AEDT）。

覆盖（每 verdict 一钉，AM-S1 任务书路由表）::

    MIGRATED_DIRECT_PASS              test_route_direct_pass
    MIGRATED_DIRECT_FAIL_COMPARISON   test_route_direct_fail_comparison
    MIGRATED_VIA_BRIDGE_PASS          test_route_via_bridge_pass_reentry_chain
    NEEDS_CAD_REEXPORT                test_route_needs_cad_reexport
                                      test_route_needs_cad_reexport_no_rescue_executor
    NO_BASELINE                       test_route_no_baseline
    FAILED_OPEN                       test_route_failed_open
    FAILED_HEALTH                     test_route_failed_health
    FAILED_BRIDGE                     test_route_failed_bridge_executor_error
                                      test_route_failed_bridge_reentry_cutoff
                                      test_route_failed_bridge_missing_artifact
    BLOCKED_NO_BRIDGE_HOST            test_route_blocked_bridge_config_null_not_fail
                                      test_route_blocked_bridge_executor_missing

另钉：报告 schema mandated 键集/engine_identity AX-3 单源（build_engine_identity
消费）/只读铁律（原件零写+Stage 0 不执行拷贝）/幂等跳过（MIGRATED_* 跳、
FAILED_* 重跑）/配置解析守卫/checks 归一/对比 fail-closed/tolerance 族回退/
collect_aedt_projects 收集守卫。
"""

from __future__ import annotations

import json
import typing
from datetime import datetime
from pathlib import Path

import pytest

from rfauto.infra.run_store import build_engine_identity
from rfauto.service import aedt_migrate_service as _mod
from rfauto.service.aedt_migrate_service import (
    CHECK_KEYS,
    MIGRATION_VERDICTS,
    REPORT_SCHEMA,
    VERDICT_BLOCKED_NO_BRIDGE_HOST,
    VERDICT_FAILED_BRIDGE,
    VERDICT_FAILED_HEALTH,
    VERDICT_FAILED_OPEN,
    VERDICT_MIGRATED_DIRECT_FAIL_COMPARISON,
    VERDICT_MIGRATED_DIRECT_PASS,
    VERDICT_MIGRATED_VIA_BRIDGE_PASS,
    VERDICT_NEEDS_CAD_REEXPORT,
    VERDICT_NO_BASELINE,
    build_project_inventory_entry,
    classify_open_error,
    collect_aedt_projects,
    is_migrated_verdict,
    load_aedt_migrate_config,
    migrate_batch,
    migrate_project,
    parse_aedt_migrate_config,
    plan_backup_path,
    read_migration_report,
    read_source_version_fingerprint,
    sha256_file,
)

_CUTOFF_MSG = (
    "ERROR: Legacy project files can no longer be opened in this version. "
    "Please use release 2023 R2 or earlier to convert the file."
)


# ---------------------------------------------------------------------------
# fake executor 工厂（全离线；调用记录供路由断言）
# ---------------------------------------------------------------------------

class _FakeExecutors:
    """五阶段 fake 执行器（每阶段可脚本化 outcome；记录每次调用入参）。"""

    def __init__(
        self,
        *,
        open_script: list[str] | None = None,
        engine_identity: dict | None = None,
        health_ok: bool = True,
        geometry_error: bool = False,
        checks: dict | None = None,
        has_baseline: bool = True,
        baseline_kind: str = "sparams",
        family: str | None = None,
        deltas: dict | None = None,
        bridge_outcome: str = "success",
        bridge_artifact: str | None = "auto",
        rescue_list: list[str] | None = None,
        bridge_messages: list[str] | None = None,
    ):
        self.open_script = list(open_script or ["success"])
        self.engine_identity = engine_identity
        self.health_ok = health_ok
        self.geometry_error = geometry_error
        self.checks = checks if checks is not None else {
            k: True for k in CHECK_KEYS}
        self.has_baseline = has_baseline
        self.baseline_kind = baseline_kind
        self.family = family
        self.deltas = deltas if deltas is not None else {"s21_db": 0.001}
        self.bridge_outcome = bridge_outcome
        self.bridge_artifact = bridge_artifact
        self.rescue_list = rescue_list
        self.bridge_messages = bridge_messages or []
        self.calls: dict[str, list] = {k: [] for k in _mod.EXECUTOR_KEYS}

    # -- 各阶段执行器（签名 (project_path, context) -> dict）--
    def direct_open(self, project_path, context):
        self.calls["direct_open"].append((str(project_path), dict(context)))
        outcome = self.open_script.pop(0) if self.open_script else "success"
        res: dict = {"outcome": outcome, "messages": [f"open:{outcome}"]}
        if self.engine_identity:
            res["engine_identity"] = self.engine_identity
        return res

    def health(self, project_path, context):
        self.calls["health"].append((str(project_path), dict(context)))
        return {
            "ok": self.health_ok,
            "geometry_error": self.geometry_error,
            "checks": self.checks,
            "messages": ["health:done"],
        }

    def compare(self, project_path, context):
        self.calls["compare"].append((str(project_path), dict(context)))
        res = {
            "has_baseline": self.has_baseline,
            "baseline_kind": self.baseline_kind,
            "deltas": self.deltas,
            "messages": ["compare:done"],
        }
        if self.family is not None:
            res["family"] = self.family
        return res

    def bridge(self, project_path, context):
        self.calls["bridge"].append((str(project_path), dict(context)))
        artifact = self.bridge_artifact
        if artifact == "auto":
            artifact = str(Path(context["work_root"]) / "bridged" / "conv.aedt")
        res: dict = {
            "outcome": self.bridge_outcome,
            "messages": list(self.bridge_messages),
        }
        if artifact:
            res["bridge_artifact"] = artifact
        return res

    def rescue(self, project_path, context):
        self.calls["rescue"].append((str(project_path), dict(context)))
        return {"rebuild_list": list(self.rescue_list or []),
                "messages": ["rescue:done"]}

    def mapping(self) -> dict:
        return {
            "direct_open": self.direct_open,
            "health": self.health,
            "compare": self.compare,
            "bridge": self.bridge,
            "rescue": self.rescue,
        }


@pytest.fixture()
def project_file(tmp_path: Path) -> Path:
    """合成 .aedt 原件（带 2021 版本指纹头，供 S0 尽力读取）。"""
    p = tmp_path / "legacy2021" / "filter21.aedt"
    p.parent.mkdir(parents=True)
    p.write_text(
        "$ begin 'HFSSProjectInformation'\n"
        "\tVersion='2021.2'\n"
        "$ end 'HFSSProjectInformation'\n",
        encoding="utf-8",
    )
    return p


def _run(project: Path, fake: _FakeExecutors, tmp_path: Path, config=None):
    return migrate_project(
        project, config, fake.mapping(), work_root=tmp_path / "work")


# ---------------------------------------------------------------------------
# 决策树路由表（每 verdict 一钉）
# ---------------------------------------------------------------------------

class TestDecisionTreeRoutes:
    def test_route_direct_pass(self, project_file, tmp_path):
        fake = _FakeExecutors(open_script=["success"])
        report = _run(project_file, fake, tmp_path)
        assert report["verdict"] == VERDICT_MIGRATED_DIRECT_PASS
        assert report["stage_reached"] == "S0→S1→S2→S3"
        assert report["comparison"]["within_tolerance"] is True
        assert report["comparison"]["via_bridge"] is False

    def test_route_direct_fail_comparison(self, project_file, tmp_path):
        fake = _FakeExecutors(deltas={"s21_db": 0.5})  # > 预声明 default 0.05
        report = _run(project_file, fake, tmp_path)
        assert report["verdict"] == VERDICT_MIGRATED_DIRECT_FAIL_COMPARISON
        assert report["comparison"]["within_tolerance"] is False
        assert report["comparison"]["deltas"] == {"s21_db": 0.5}
        assert any("超差" in m for m in report["messages"])

    def test_route_via_bridge_pass_reentry_chain(self, project_file, tmp_path):
        fake = _FakeExecutors(open_script=["cutoff", "success"])
        report = _run(
            project_file, fake, tmp_path,
            config={"bridge_2023R2": {"host": "bridge-pc"}})
        assert report["verdict"] == VERDICT_MIGRATED_VIA_BRIDGE_PASS
        # stage_reached 记录 bridge→direct 重入链（S1b/S2b/S3b）
        assert report["stage_reached"] == "S0→S1→S4→S1b→S2b→S3b"
        assert report["comparison"]["via_bridge"] is True
        # 重入直开的入参=桥接产物路径（非原件）
        assert len(fake.calls["direct_open"]) == 2
        first_path, _ = fake.calls["direct_open"][0]
        reentry_path, reentry_ctx = fake.calls["direct_open"][1]
        assert first_path == str(project_file)
        assert reentry_path != str(project_file)
        assert reentry_path.endswith(".aedt")
        assert Path(reentry_ctx["project_path"]) == Path(reentry_path)
        # 体检/对比消费的也是桥接产物
        assert fake.calls["health"][0][0] == reentry_path
        assert fake.calls["compare"][0][0] == reentry_path

    def test_route_needs_cad_reexport(self, project_file, tmp_path):
        fake = _FakeExecutors(
            geometry_error=True,
            rescue_list=["materials", "boundaries", "excitations"])
        report = _run(project_file, fake, tmp_path)
        assert report["verdict"] == VERDICT_NEEDS_CAD_REEXPORT
        assert report["stage_reached"] == "S0→S1→S2→S5"
        assert report["rescue"]["rebuild_status"] == "NEEDS_MANUAL"
        assert report["rescue"]["rebuild_list"] == [
            "materials", "boundaries", "excitations"]

    def test_route_needs_cad_reexport_no_rescue_executor(
            self, project_file, tmp_path):
        fake = _FakeExecutors(geometry_error=True)
        executors = fake.mapping()
        executors.pop("rescue")
        report = migrate_project(
            project_file, None, executors, work_root=tmp_path / "work")
        assert report["verdict"] == VERDICT_NEEDS_CAD_REEXPORT
        assert report["rescue"]["rebuild_list"] == []
        assert any("rescue executor 未注入" in m for m in report["messages"])

    def test_route_no_baseline(self, project_file, tmp_path):
        fake = _FakeExecutors(has_baseline=False)
        report = _run(project_file, fake, tmp_path)
        assert report["verdict"] == VERDICT_NO_BASELINE
        assert report["comparison"] is None  # schema mandated comparison|null
        assert report["stage_reached"] == "S0→S1→S2→S3"

    def test_route_failed_open(self, project_file, tmp_path):
        fake = _FakeExecutors(open_script=["error"])
        report = _run(project_file, fake, tmp_path)
        assert report["verdict"] == VERDICT_FAILED_OPEN
        assert report["stage_reached"] == "S0→S1"
        # 如实终态：体检/对比未跑
        assert fake.calls["health"] == []
        assert fake.calls["compare"] == []

    def test_route_failed_health(self, project_file, tmp_path):
        fake = _FakeExecutors(health_ok=False, geometry_error=False)
        report = _run(project_file, fake, tmp_path)
        assert report["verdict"] == VERDICT_FAILED_HEALTH
        assert report["stage_reached"] == "S0→S1→S2"
        assert fake.calls["compare"] == []

    def test_route_failed_bridge_executor_error(self, project_file, tmp_path):
        fake = _FakeExecutors(
            open_script=["cutoff"],
            bridge_outcome="error",
            bridge_messages=["2023 R2 host unreachable"])
        report = _run(
            project_file, fake, tmp_path,
            config={"bridge_2023R2": {"host": "bridge-pc"}})
        assert report["verdict"] == VERDICT_FAILED_BRIDGE
        assert report["stage_reached"] == "S0→S1→S4"
        assert any("2023 R2 host unreachable" in m for m in report["messages"])

    def test_route_failed_bridge_reentry_cutoff(self, project_file, tmp_path):
        fake = _FakeExecutors(open_script=["cutoff", "cutoff"])
        report = _run(
            project_file, fake, tmp_path,
            config={"bridge_2023R2": {"host": "bridge-pc"}})
        assert report["verdict"] == VERDICT_FAILED_BRIDGE
        assert "S1b" in report["stage_reached"]

    def test_route_failed_bridge_missing_artifact(self, project_file, tmp_path):
        fake = _FakeExecutors(
            open_script=["cutoff"], bridge_outcome="success",
            bridge_artifact=None)  # success 但缺产物=契约违约，如实 FAILED
        report = _run(
            project_file, fake, tmp_path,
            config={"bridge_2023R2": {"host": "bridge-pc"}})
        assert report["verdict"] == VERDICT_FAILED_BRIDGE
        assert any("bridge_artifact" in m for m in report["messages"])

    def test_route_blocked_bridge_config_null_not_fail(
            self, project_file, tmp_path):
        """BLOCKED 不误报 FAIL 钉：bridge null → BLOCKED_*，非 FAILED_*。"""
        fake = _FakeExecutors(open_script=["cutoff"])
        report = _run(project_file, fake, tmp_path)  # 缺省 bridge_2023R2=None
        assert report["verdict"] == VERDICT_BLOCKED_NO_BRIDGE_HOST
        assert report["verdict"].startswith("BLOCKED_")
        assert not report["verdict"].startswith("FAILED_")
        assert report["verdict"] in MIGRATION_VERDICTS
        assert report["stage_reached"] == "S0→S1→S4"
        assert fake.calls["bridge"] == []
        assert any("BLOCKED 非 FAIL" in m for m in report["messages"])

    def test_route_blocked_bridge_executor_missing(self, project_file, tmp_path):
        fake = _FakeExecutors(open_script=["cutoff"])
        executors = fake.mapping()
        executors.pop("bridge")
        report = migrate_project(
            project_file, {"bridge_2023R2": {"host": "x"}}, executors,
            work_root=tmp_path / "work")
        assert report["verdict"] == VERDICT_BLOCKED_NO_BRIDGE_HOST
        assert fake.calls["bridge"] == []


# ---------------------------------------------------------------------------
# 报告 schema / engine_identity / 体检 checks 归一
# ---------------------------------------------------------------------------

class TestReportSchema:
    REQUIRED_KEYS: typing.ClassVar[frozenset[str]] = frozenset({
        "project", "source_sha256", "backup_path", "stage_reached",
        "verdict", "checks", "messages", "engine_identity", "comparison",
        "timestamps",
    })

    def test_mandated_keys_present_all_routes(self, project_file, tmp_path):
        for fake in (
            _FakeExecutors(open_script=["success"]),
            _FakeExecutors(open_script=["cutoff"]),
            _FakeExecutors(open_script=["error"]),
            _FakeExecutors(has_baseline=False),
            _FakeExecutors(geometry_error=True),
        ):
            report = _run(project_file, fake, tmp_path)
            assert set(report) >= self.REQUIRED_KEYS
            assert report["schema"] == REPORT_SCHEMA
            assert set(report["checks"]) == set(CHECK_KEYS)
            assert all(
                isinstance(v, bool) or v is None
                for v in report["checks"].values())
            assert report["verdict"] in MIGRATION_VERDICTS
            # timestamps 可解析 ISO
            datetime.fromisoformat(report["timestamps"]["started_utc"])
            datetime.fromisoformat(report["timestamps"]["ended_utc"])

    def test_engine_identity_consumes_build_engine_identity_ax3(
            self, project_file, tmp_path):
        fake = _FakeExecutors(engine_identity={
            "ansysedt_version": "2025.1", "machine": "lab-ws01"})
        report = _run(project_file, fake, tmp_path)
        # AX-3 单源：与 build_engine_identity 直出逐键一致
        assert report["engine_identity"] == build_engine_identity({
            "engine": "aedt", "version": "2025.1", "machine": "lab-ws01"})
        assert report["engine_identity"]["version"] == "2025.1"
        assert report["engine_identity"]["machine"] == "lab-ws01"

    def test_engine_identity_missing_reported_unknown_not_fabricated(
            self, project_file, tmp_path):
        fake = _FakeExecutors(engine_identity=None)
        report = _run(project_file, fake, tmp_path)
        ident = report["engine_identity"]
        assert ident["engine"] == "aedt"
        assert ident["version"] == "unknown"  # 缺字段如实 unknown（AX-3）
        assert ident["machine"]  # best-effort hostname（非空即真）

    def test_checks_normalization_drops_extra_and_unknown(
            self, project_file, tmp_path):
        fake = _FakeExecutors(checks={
            "materials": True, "mesh": False, "excitations": True,
            "setups": "yes-not-bool"})
        report = _run(project_file, fake, tmp_path)
        assert set(report["checks"]) == set(CHECK_KEYS)
        assert report["checks"]["materials"] is True
        assert report["checks"]["mesh"] is False
        assert report["checks"]["boundaries"] is None  # 缺失=未知如实
        assert report["checks"]["optimetrics"] is None
        assert "excitations" not in report["checks"]  # 键集恒定
        assert report["checks"]["setups"] is None  # 非 bool=未知，不硬转


# ---------------------------------------------------------------------------
# 只读铁律 / S0 纯文件面
# ---------------------------------------------------------------------------

class TestReadOnlyIronRule:
    def test_original_untouched_and_no_copy_executed(
            self, project_file, tmp_path):
        original_bytes = project_file.read_bytes()
        work = tmp_path / "work"  # _run 内部即以此为其 work_root
        fake = _FakeExecutors(open_script=["success"])
        report = _run(project_file, fake, tmp_path)
        # ① 原件逐字节未变
        assert project_file.read_bytes() == original_bytes
        # ② 备份路径已规划、指向 work_root/backup、恒 ≠ 原件
        backup = Path(report["backup_path"])
        assert backup != project_file
        assert backup.parent == work / "backup"
        # ③ Stage 0 不执行拷贝（拷贝归 S2 实机席）：备份位无文件
        assert not backup.exists()
        # ④ 单工程决策树零落盘（inventory/报告落盘归批量层）——work_root
        #    根本不该被建出来；无任何输出路径 == 原件路径（平凡真）
        assert report["project_path"] == str(project_file)
        assert not work.exists()

    def test_sha256_and_backup_plan_deterministic(self, project_file):
        digest = sha256_file(project_file)
        entry = build_project_inventory_entry(project_file, "E:/does-not-matter")
        assert entry["sha256"] == digest
        assert entry["sha8"] == digest[:8]
        planned = plan_backup_path(project_file, "w", digest)
        assert planned.name == f"filter21__{digest[:8]}.aedt"
        assert planned == plan_backup_path(project_file, "w", digest)

    def test_fingerprint_best_effort(self, project_file, tmp_path):
        found = read_source_version_fingerprint(project_file)
        assert found == {"source_version": "2021.2",
                         "fingerprint_source": "header:Version"}
        # AEVersion 优先档
        p2 = tmp_path / "a.aedt"
        p2.write_text("AEVersion(unknown)=2020.2\n", encoding="utf-8")
        assert read_source_version_fingerprint(p2)["source_version"] == "2020.2"
        # 读不到如实 unavailable，不伪造
        p3 = tmp_path / "b.aedt"
        p3.write_text("no version marker here", encoding="utf-8")
        assert read_source_version_fingerprint(p3) == {
            "source_version": None, "fingerprint_source": "unavailable"}

    def test_classify_open_error_conservative(self):
        assert classify_open_error(_CUTOFF_MSG) == "cutoff"
        assert classify_open_error("grpc connection refused") == "error"
        assert classify_open_error("Please use release 2023R2 or earlier") == "cutoff"


# ---------------------------------------------------------------------------
# 幂等（批量重跑跳过 MIGRATED_*；FAILED_*/BLOCKED_* 重跑）
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_batch_rerun_skips_migrated_and_rewrites_nothing(
            self, project_file, tmp_path):
        work = tmp_path / "work"
        fake = _FakeExecutors(open_script=["success"])
        first = migrate_batch(
            project_file, config={"work_root": str(work)},
            executors=fake.mapping())
        assert first["ok"] is True
        assert first["counts"] == {VERDICT_MIGRATED_DIRECT_PASS: 1}
        report_path = Path(first["results"][0]["report_path"])
        snapshot = report_path.read_bytes()

        second = migrate_batch(
            project_file, config={"work_root": str(work)},
            executors=_FakeExecutors().mapping())
        row = second["results"][0]
        assert row["skipped"] is True
        assert row["prior_verdict"] == VERDICT_MIGRATED_DIRECT_PASS
        assert second["counts"] == {"skipped": 1}
        # 报告文件未被重写
        assert report_path.read_bytes() == snapshot

    def test_batch_rerun_skips_fail_comparison_too(self, project_file, tmp_path):
        """MIGRATED_* 前缀族同属跳过集——同门不重跑赌不同数字（#122）。"""
        work = tmp_path / "work"
        fake = _FakeExecutors(deltas={"s21_db": 0.9})
        assert migrate_batch(
            project_file, config={"work_root": str(work)},
            executors=fake.mapping())["counts"] == {
                VERDICT_MIGRATED_DIRECT_FAIL_COMPARISON: 1}
        second = migrate_batch(
            project_file, config={"work_root": str(work)},
            executors=_FakeExecutors().mapping())
        assert second["results"][0]["skipped"] is True
        assert second["results"][0]["prior_verdict"] == (
            VERDICT_MIGRATED_DIRECT_FAIL_COMPARISON)

    def test_failed_open_and_blocked_rerun_not_skipped(
            self, project_file, tmp_path):
        work = tmp_path / "work"
        first = migrate_batch(
            project_file, config={"work_root": str(work)},
            executors=_FakeExecutors(open_script=["error"]).mapping())
        assert first["counts"] == {VERDICT_FAILED_OPEN: 1}
        second = migrate_batch(
            project_file, config={"work_root": str(work)},
            executors=_FakeExecutors(open_script=["cutoff"]).mapping())
        row = second["results"][0]
        assert row["skipped"] is False
        assert row["verdict"] == VERDICT_BLOCKED_NO_BRIDGE_HOST
        assert second["counts"] == {VERDICT_BLOCKED_NO_BRIDGE_HOST: 1}

    def test_is_migrated_verdict_predicate(self):
        assert is_migrated_verdict(VERDICT_MIGRATED_DIRECT_PASS)
        assert is_migrated_verdict(VERDICT_MIGRATED_VIA_BRIDGE_PASS)
        assert is_migrated_verdict(VERDICT_MIGRATED_DIRECT_FAIL_COMPARISON)
        assert not is_migrated_verdict(VERDICT_FAILED_OPEN)
        assert not is_migrated_verdict(VERDICT_BLOCKED_NO_BRIDGE_HOST)
        assert not is_migrated_verdict(VERDICT_NO_BASELINE)


# ---------------------------------------------------------------------------
# 批量编排（信封/inventory/收集守卫/executor 异常逐工程记行）
# ---------------------------------------------------------------------------

class TestBatchOrchestration:
    def test_batch_envelope_and_inventory(self, project_file, tmp_path):
        work = tmp_path / "work"
        batch = migrate_batch(
            [project_file], config={"work_root": str(work)},
            executors=_FakeExecutors().mapping())
        assert batch["ok"] is True
        assert batch["total"] == 1
        inventory = json.loads(
            Path(batch["inventory_path"]).read_text(encoding="utf-8"))
        assert inventory["schema"] == _mod.INVENTORY_SCHEMA
        assert inventory["projects"][0]["sha256"] == sha256_file(project_file)
        assert inventory["projects"][0]["source_version"] == "2021.2"
        # 盘点面不带批量层内部键
        assert "stem_report_name" not in inventory["projects"][0]

    def test_batch_dir_recursion_and_dedup(self, project_file, tmp_path):
        (tmp_path / "nest" / "deep").mkdir(parents=True)
        (tmp_path / "nest" / "deep" / "x.aedt").write_text("v", encoding="utf-8")
        found = collect_aedt_projects(tmp_path / "nest")
        assert len(found) == 1
        # file+dir 双输入去重
        found2 = collect_aedt_projects([found[0], tmp_path / "nest"])
        assert len(found2) == 1

    def test_batch_collect_guards(self, tmp_path):
        with pytest.raises(ValueError, match="不存在"):
            collect_aedt_projects(tmp_path / "ghost")
        plain = tmp_path / "plain.txt"
        plain.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match=r"不是 \.aedt"):
            collect_aedt_projects(plain)
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ValueError, match="未找到任何"):
            collect_aedt_projects(empty)
        batch = migrate_batch(empty, config={"work_root": str(tmp_path / "w")},
                              executors=_FakeExecutors().mapping())
        assert batch["ok"] is False
        assert batch["errors"]

    def test_executor_crash_recorded_per_project_not_verdict(
            self, project_file, tmp_path):
        """executor 内部异常=基础设施故障——不折算 verdict，逐工程记 error 行。"""

        def boom(*_args, **_kwargs):
            raise RuntimeError("grpc channel broken")

        executors = _FakeExecutors().mapping()
        executors["direct_open"] = boom
        batch = migrate_batch(
            project_file, config={"work_root": str(tmp_path / "work")},
            executors=executors)
        assert batch["ok"] is True  # 批量不炸
        row = batch["results"][0]
        assert row["ok"] is False
        assert "RuntimeError: grpc channel broken" in row["errors"][0]
        assert batch["counts"] == {"error": 1}

    def test_missing_required_executor_is_loud(self, project_file, tmp_path):
        executors = _FakeExecutors().mapping()
        executors.pop("compare")
        with pytest.raises(ValueError, match="compare"):
            migrate_project(
                project_file, None, executors, work_root=tmp_path / "work")
        with pytest.raises(FileNotFoundError):
            migrate_project(
                tmp_path / "ghost.aedt", None, executors,
                work_root=tmp_path / "work")

    def test_read_migration_report_roundtrip(self, project_file, tmp_path):
        work = tmp_path / "work"
        batch = migrate_batch(
            project_file, config={"work_root": str(work)},
            executors=_FakeExecutors().mapping())
        report = read_migration_report(batch["results"][0]["report_path"])
        assert report["verdict"] == VERDICT_MIGRATED_DIRECT_PASS
        assert report["schema"] == REPORT_SCHEMA


# ---------------------------------------------------------------------------
# 配置解析（只写解析器+缺省值；不改 configs/settings.local.yaml 本体）
# ---------------------------------------------------------------------------

class TestConfigParsing:
    def test_defaults_block_semantics(self):
        cfg = parse_aedt_migrate_config(None)
        assert cfg == {
            "bridge_2023R2": None,  # null=桥接机未装 → BLOCKED 缺省关
            "tolerances": {"default": 0.05},
            "work_root": "runs/aedt_migrate",
        }

    def test_parse_overrides_and_normalization(self):
        cfg = parse_aedt_migrate_config({
            "bridge_2023R2": {"host": "bridge-pc", "ng": True},
            "tolerances": {"patch": 0.02, "default": 0.1},
            "work_root": "E:/tmp/mig",
            "unknown_future_key": 1,  # 未知键前向兼容忽略
        })
        assert cfg["bridge_2023R2"] == {"host": "bridge-pc", "ng": True}
        assert cfg["tolerances"] == {"patch": 0.02, "default": 0.1}
        assert cfg["work_root"] == "E:/tmp/mig"
        assert "unknown_future_key" not in cfg

    def test_parse_rejects_bad_values(self):
        with pytest.raises(ValueError, match="mapping"):
            parse_aedt_migrate_config("not-a-mapping")
        with pytest.raises(ValueError, match="bridge_2023R2"):
            parse_aedt_migrate_config({"bridge_2023R2": True})
        with pytest.raises(ValueError, match="tolerances"):
            parse_aedt_migrate_config({"tolerances": {"patch": -0.1}})
        with pytest.raises(ValueError, match="tolerances"):
            parse_aedt_migrate_config({"tolerances": {"patch": "abc"}})
        with pytest.raises(ValueError, match="work_root"):
            parse_aedt_migrate_config({"work_root": 123})

    def test_load_from_yaml_block(self, tmp_path):
        yaml_path = tmp_path / "settings.local.yaml"
        yaml_path.write_text(
            "aedt_path: C:/Program Files/ANSYS Inc\n"
            "aedt_migrate:\n"
            "  bridge_2023R2: null\n"
            "  tolerances:\n"
            "    default: 0.03\n"
            "    hairpin: 0.01\n"
            "  work_root: runs/mig\n",
            encoding="utf-8",
        )
        cfg = load_aedt_migrate_config(yaml_path)
        assert cfg["bridge_2023R2"] is None
        assert cfg["tolerances"] == {"default": 0.03, "hairpin": 0.01}
        assert cfg["work_root"] == "runs/mig"

    def test_load_missing_file_or_block_gives_defaults(self, tmp_path):
        assert load_aedt_migrate_config(
            tmp_path / "ghost.yaml") == parse_aedt_migrate_config(None)
        bare = tmp_path / "bare.yaml"
        bare.write_text("aedt_path: x\n", encoding="utf-8")
        assert load_aedt_migrate_config(bare) == parse_aedt_migrate_config(None)

    def test_load_bad_yaml_is_loud(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("aedt_migrate: [unclosed\n", encoding="utf-8")
        with pytest.raises(ValueError, match="YAML"):
            load_aedt_migrate_config(bad)


# ---------------------------------------------------------------------------
# 对比语义补充（fail-closed / tolerance 族回退）
# ---------------------------------------------------------------------------

class TestComparisonSemantics:
    def test_fail_closed_zero_deltas_is_honest_red(self, project_file, tmp_path):
        fake = _FakeExecutors(deltas={})  # 声明有基线但零 deltas
        report = _run(project_file, fake, tmp_path)
        assert report["verdict"] == VERDICT_MIGRATED_DIRECT_FAIL_COMPARISON
        assert report["comparison"]["within_tolerance"] is False
        assert any("fail-closed" in m for m in report["messages"])

    def test_tolerance_family_fallback_to_predeclared_default(
            self, project_file, tmp_path):
        fake = _FakeExecutors(family="patch", deltas={"s11_db": 0.04})
        report = _run(project_file, fake, tmp_path)  # tolerances 无 patch 族
        assert report["comparison"]["family"] == "default"
        assert report["comparison"]["tolerance"] == 0.05
        assert report["verdict"] == VERDICT_MIGRATED_DIRECT_PASS
        assert any("回退" in m for m in report["messages"])

    def test_family_specific_tolerance_consumed(self, project_file, tmp_path):
        fake = _FakeExecutors(family="hairpin", deltas={"s21_db": 0.02})
        report = _run(project_file, fake, tmp_path, config={
            "tolerances": {"hairpin": 0.01}})
        assert report["comparison"]["family"] == "hairpin"
        assert report["comparison"]["tolerance"] == 0.01
        assert report["verdict"] == VERDICT_MIGRATED_DIRECT_FAIL_COMPARISON

    def test_non_numeric_delta_fail_closed(self, project_file, tmp_path):
        fake = _FakeExecutors(deltas={"weird": "not-a-number"})
        report = _run(project_file, fake, tmp_path)
        assert report["verdict"] == VERDICT_MIGRATED_DIRECT_FAIL_COMPARISON
        assert report["comparison"]["deltas"]["weird"] == float("inf")

    def test_boundary_delta_within_tolerance(self, project_file, tmp_path):
        fake = _FakeExecutors(deltas={"s21_db": 0.05})  # 恰等于 tolerance
        report = _run(project_file, fake, tmp_path)
        assert report["comparison"]["within_tolerance"] is True
        assert report["verdict"] == VERDICT_MIGRATED_DIRECT_PASS
