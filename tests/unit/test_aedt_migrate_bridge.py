"""aedt_migrate 桥接腿+远程配方测试（aurora_r AM-S3，纯离线零 AEDT）。

覆盖（AM-S3 任务书三钉）::

    BLOCKED 钉    config null → blocked 形态（S1 枚举单源）+ runner 不被
                  调 + 不误报 FAIL（树级 BLOCKED 复钉 + 远程腿工厂不注入）
    mock 全链     本地腿 fake runner 全链：open(cutoff)→bridge(success)
                  →回迁产物路径→re-entry 输入构造（S1b/S2b/S3b 链，
                  MIGRATED_VIA_BRIDGE_PASS）；runner 失败/产物未落盘
                  →FAILED_BRIDGE 如实；原件只读；staging 清理；
                  脚本/命令行字面钉
    配方清单钉    远程发射清单：console 可见 bat 形态/中间根唯一/清理
                  清单/互斥标记/env 意图门
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.infra.remote_machines import RemoteMachineConfig, resolve_machine
from rfauto.service import remote_service as _rs_facade
from rfauto.service.aedt_migrate_bridge import (
    BRIDGE_DEFAULT_TIMEOUT_S,
    BRIDGE_SCRIPT_NAME,
    BRIDGE_VERSION_DEFAULT,
    build_bridge_command,
    build_bridge_executors,
    build_bridge_saveas_script,
    plan_bridge_artifact_path,
    resolve_bridge_leg,
    run_bridge_executor,
    subprocess_runner,
)
from rfauto.service.aedt_migrate_service import (
    VERDICT_BLOCKED_NO_BRIDGE_HOST,
    VERDICT_FAILED_BRIDGE,
    VERDICT_MIGRATED_VIA_BRIDGE_PASS,
    migrate_project,
)
from rfauto.service.remote_service.aedt_migrate import (
    AEDT_MIGRATE_MUTEX_FINGERPRINT,
    AEDT_MIGRATE_MUTEX_PROCESS,
    AEDT_MIGRATE_REMOTE_ENV,
    AEDT_MIGRATE_REMOTE_WORK_ROOT,
    aedt_migrate_remote_recipe,
    build_bridge_task_bat,
)
from rfauto.service.remote_service.mutex import remote_mutex_command

_CUTOFF_MSG = (
    "ERROR: Legacy project files can no longer be opened in this version. "
    "Please use release 2023 R2 or earlier to convert the file."
)

_BRIDGE_EXE = "C:\\Program Files\\ANSYS Inc\\ANSYS Inc\\v232\\AnsysEM\\ansysedt.exe"


# ---------------------------------------------------------------------------
# fake 件（全离线：fake runner + S1 树其余阶段 fake 执行器）
# ---------------------------------------------------------------------------

class FakeRunner:
    """fake runner：记录 command/timeout；可脚本化 rc 与产物落盘行为。"""

    def __init__(
        self,
        *,
        rc: int = 0,
        create_artifact: bool = True,
        stderr: str = "",
    ):
        self.rc = rc
        self.create_artifact = create_artifact
        self.stderr = stderr
        self.calls: list[dict] = []
        self.script_texts: list[str] = []

    def __call__(self, command, *, timeout_s=None):
        self.calls.append({
            "command": [str(c) for c in command],
            "timeout_s": timeout_s,
        })
        script = Path(command[-1])
        text = script.read_text(encoding="ascii")
        # 脚本内容调用时快照（成功路径 stage 目录随后被清理——事后读不到）
        self.script_texts.append(text)
        if self.create_artifact and self.rc == 0:
            # 模拟 2023 R2 SaveAs：产物落 target 路径（命令行 -RunScript
            # 脚本里烘焙的 TARGET_PROJECT）。
            target = text.split('TARGET_PROJECT = r"')[1].split('"')[0]
            Path(target).write_bytes(b"bridged-by-2023r2-fake")
        return {
            "rc": self.rc,
            "stdout_tail": "",
            "stderr_tail": self.stderr,
        }


class _TreeExecutors:
    """S1 树其余阶段 fake（direct_open/health/compare；路由最小件）。"""

    def __init__(self, open_script: list[str], extra: dict | None = None):
        self.open_script = list(open_script)
        self.open_calls: list[str] = []
        self.extra = dict(extra or {})

    def direct_open(self, project_path, context):
        self.open_calls.append(str(project_path))
        return {"outcome": self.open_script.pop(0), "messages": ["open"]}

    def health(self, project_path, context):
        return {"ok": True, "geometry_error": False,
                "checks": {k: True for k in (
                    "materials", "boundaries", "mesh", "setups",
                    "optimetrics")}, "messages": ["health"]}

    def compare(self, project_path, context):
        return {"has_baseline": True, "baseline_kind": "sparams",
                "deltas": {"s21_db": 0.001}, "messages": ["compare"]}

    def mapping(self) -> dict:
        return {
            "direct_open": self.direct_open,
            "health": self.health,
            "compare": self.compare,
            **self.extra,
        }


@pytest.fixture()
def project_file(tmp_path: Path) -> Path:
    p = tmp_path / "legacy2021" / "filter21.aedt"
    p.parent.mkdir(parents=True)
    p.write_text("$ begin 'HFSSProjectInformation'\n\tVersion='2021.2'\n",
                 encoding="utf-8")
    return p


def _context(tmp_path: Path, config: dict | None) -> dict:
    return {
        "project_path": "",
        "work_root": str(tmp_path / "work"),
        "config": dict(config or {}),
        "inventory_entry": {},
    }


# ---------------------------------------------------------------------------
# BLOCKED 钉（null → blocked 枚举单源 + 不误报 FAIL）
# ---------------------------------------------------------------------------

class TestBlockedPins:
    def test_executor_blocked_on_null_config(self, project_file, tmp_path):
        runner = FakeRunner()
        res = run_bridge_executor(
            project_file, _context(tmp_path, {"bridge_2023R2": None}),
            runner=runner)
        assert res["outcome"] == "blocked"
        # S1 枚举单源（复用，不重造）
        assert res["verdict"] == VERDICT_BLOCKED_NO_BRIDGE_HOST
        assert res["verdict"] == "BLOCKED_NO_BRIDGE_HOST"
        assert res["bridge_artifact"] is None
        assert runner.calls == []  # 未执行任何通道

    def test_executor_blocked_on_missing_bridge_key(
            self, project_file, tmp_path):
        res = run_bridge_executor(
            project_file, _context(tmp_path, {}), runner=FakeRunner())
        assert res["outcome"] == "blocked"
        assert res["verdict"] == VERDICT_BLOCKED_NO_BRIDGE_HOST

    def test_executor_blocked_on_remote_leg(self, project_file, tmp_path,
                                            monkeypatch):
        # 离线注入机器注册表（机器本档 gitignored，干净检出零依赖）
        import rfauto.service.remote_service.aedt_migrate as _rm

        stub_cfg = RemoteMachineConfig(
            name="lab_bridge_host", host="10.0.0.9",
            hfss_project_root=r"E:\rfauto_remote")
        monkeypatch.setattr(
            _rm, "load_remote_machines",
            lambda: {"lab_bridge_host": stub_cfg})
        res = run_bridge_executor(
            project_file,
            _context(tmp_path, {"bridge_2023R2":
                                {"machine": "lab_bridge_host"}}),
            runner=FakeRunner())
        assert res["outcome"] == "blocked"
        assert res["verdict"] == VERDICT_BLOCKED_NO_BRIDGE_HOST
        # 远程腿附发射清单（挂账面可审计），但零执行
        assert res["remote_recipe"]["ok"] is True
        assert res["remote_recipe"]["launch"]["pending"] is True

    def test_tree_blocked_config_null_executor_not_called(
            self, project_file, tmp_path):
        """null 配置：树在本执行器被调**之前**就 BLOCKED（S1 单点判定）
        ——不误报 FAIL，executor 零调用。"""
        calls: list = []

        def spy_executor(project_path, context):
            calls.append(project_path)
            return run_bridge_executor(project_path, context)

        tree = _TreeExecutors(["cutoff"], extra={"bridge": spy_executor})
        report = migrate_project(
            project_file,
            {"bridge_2023R2": None},
            tree.mapping(),
            work_root=tmp_path / "work",
        )
        assert report["verdict"] == VERDICT_BLOCKED_NO_BRIDGE_HOST
        assert report["verdict"] != "FAILED_BRIDGE"
        assert calls == []

    def test_factory_remote_leg_not_injected_tree_blocked(
            self, project_file, tmp_path):
        """远程腿：工厂不注入 bridge executor → 树按缺 executor 语义
        BLOCKED（不误报 FAILED_BRIDGE——挂账≠失败，#122）。"""
        config = {"bridge_2023R2": {"machine": "lab_bridge_host"}}
        executors = build_bridge_executors(config, runner=FakeRunner())
        assert executors == {}
        tree = _TreeExecutors(["cutoff"], extra=executors)
        report = migrate_project(
            project_file, config, tree.mapping(),
            work_root=tmp_path / "work")
        assert report["verdict"] == VERDICT_BLOCKED_NO_BRIDGE_HOST

    def test_factory_null_config_empty(self):
        assert build_bridge_executors(None) == {}
        assert build_bridge_executors({"bridge_2023R2": None}) == {}


# ---------------------------------------------------------------------------
# 腿解析 / 纯函数面
# ---------------------------------------------------------------------------

class TestLegResolution:
    def test_none(self):
        assert resolve_bridge_leg(None) == "none"

    def test_local(self):
        assert resolve_bridge_leg({"ansysedt_exe": _BRIDGE_EXE}) == "local"

    def test_remote(self):
        assert resolve_bridge_leg({"machine": "lab_bridge_host"}) == "remote"

    def test_ambiguous_loud(self):
        with pytest.raises(ValueError, match="歧义"):
            resolve_bridge_leg(
                {"ansysedt_exe": _BRIDGE_EXE, "machine": "lab_bridge_host"})

    def test_empty_mapping_loud(self):
        with pytest.raises(ValueError, match="至少配置其一"):
            resolve_bridge_leg({"foo": 1})

    def test_non_mapping_loud(self):
        with pytest.raises(ValueError, match="mapping"):
            resolve_bridge_leg("E:\\bridge")

    def test_artifact_plan_shape(self, tmp_path):
        p = plan_bridge_artifact_path(
            Path("x") / "filter21.aedt", tmp_path, "deadbeef" + "0" * 56)
        assert p == tmp_path / "bridged" / "filter21__deadbeef.aedt"

    def test_command_literal(self):
        cmd = build_bridge_command(_BRIDGE_EXE, "s.py", "l.log")
        assert cmd == [_BRIDGE_EXE, "-ng", "-Logfile", "l.log",
                       "-RunScript", "s.py"]
        # #374 参数序纪律：末位恒为最后旗标（-RunScript）的操作数
        assert cmd[-2] == "-RunScript"

    def test_script_ascii_and_content(self, tmp_path):
        text = build_bridge_saveas_script(
            tmp_path / "in.aedt", tmp_path / "out.aedt")
        text.encode("ascii")  # 纯 ASCII（不抛即过）
        assert 'STAGED_PROJECT = r"' in text
        assert "OpenProject(" in text
        assert "SaveAs(" in text
        assert ", False)" in text  # overwrite=False 幂等
        assert "QuitApplication" in text

    def test_script_non_ascii_loud(self, tmp_path):
        with pytest.raises(ValueError, match="非 ASCII"):
            build_bridge_saveas_script(
                tmp_path / "中文" / "in.aedt", tmp_path / "out.aedt")


# ---------------------------------------------------------------------------
# 本地腿 mock 全链（open→save-as→回迁产物→re-entry 输入构造）
# ---------------------------------------------------------------------------

class TestLocalMockChain:
    def _run_tree(self, project_file, tmp_path, runner):
        config = {"bridge_2023R2": {"ansysedt_exe": _BRIDGE_EXE}}
        executors = build_bridge_executors(config, runner=runner)
        assert set(executors) == {"bridge"}
        tree = _TreeExecutors(["cutoff", "success"], extra=executors)
        report = migrate_project(
            project_file, config, tree.mapping(),
            work_root=tmp_path / "work")
        return report, tree, executors["bridge"]

    def test_full_chain_via_bridge_pass(self, project_file, tmp_path):
        runner = FakeRunner()
        report, tree, _ = self._run_tree(project_file, tmp_path, runner)
        assert report["verdict"] == VERDICT_MIGRATED_VIA_BRIDGE_PASS
        # 桥接→直开重入链（S1 既有路由，本席零路由代码）
        assert report["stage_reached"] == "S0→S1→S4→S1b→S2b→S3b"
        # 回迁产物路径 = work_root/bridged/<stem>__<sha8>.aedt
        import hashlib

        sha8 = hashlib.sha256(project_file.read_bytes()).hexdigest()[:8]
        artifact = (tmp_path / "work" / "bridged"
                    / f"filter21__{sha8}.aedt")
        assert artifact.is_file()
        # re-entry 输入构造：第二次直开的入参=桥接产物（非原件）
        assert len(tree.open_calls) == 2
        assert tree.open_calls[0] == str(project_file)
        assert tree.open_calls[1] == str(artifact)
        # 体检/对比消费的也是桥接产物（context project_path 同步）
        assert report["comparison"]["via_bridge"] is True
        # AX-3 engine identity：桥接机版本随报告落盘
        assert report["engine_identity"]["version"] == BRIDGE_VERSION_DEFAULT

    def test_runner_received_command_script_log_timeout(
            self, project_file, tmp_path):
        runner = FakeRunner()
        self._run_tree(project_file, tmp_path, runner)
        assert len(runner.calls) == 1
        call = runner.calls[0]
        cmd = call["command"]
        assert cmd[0] == _BRIDGE_EXE
        assert "-ng" in cmd
        assert cmd[cmd.index("-Logfile") + 1].endswith(".log")
        assert cmd[cmd.index("-RunScript") + 1].endswith(BRIDGE_SCRIPT_NAME)
        assert call["timeout_s"] == BRIDGE_DEFAULT_TIMEOUT_S
        # 脚本烘焙（调用时快照——成功路径 stage 目录随后被清理）：
        # staged 拷贝件→产物（都在 work_root 下，非原件）
        text = runner.script_texts[0]
        staged = text.split('STAGED_PROJECT = r"')[1].split('"')[0]
        target = text.split('TARGET_PROJECT = r"')[1].split('"')[0]
        assert staged.startswith(
            str((tmp_path / "work" / "bridge_stage").resolve()))
        assert target.startswith(
            str((tmp_path / "work" / "bridged").resolve()))
        assert target != str(project_file)

    def test_runner_failure_failed_bridge(self, project_file, tmp_path):
        runner = FakeRunner(rc=1, stderr="license checkout failed")
        report, _, _ = self._run_tree(project_file, tmp_path, runner)
        assert report["verdict"] == VERDICT_FAILED_BRIDGE
        assert any("license checkout failed" in m
                   for m in report["messages"])

    def test_artifact_missing_after_rc0_fail_closed(
            self, project_file, tmp_path):
        runner = FakeRunner(create_artifact=False)
        report, _, _ = self._run_tree(project_file, tmp_path, runner)
        assert report["verdict"] == VERDICT_FAILED_BRIDGE
        assert any("未落盘" in m for m in report["messages"])

    def test_original_readonly_and_stage_cleaned(
            self, project_file, tmp_path):
        original_bytes = project_file.read_bytes()
        runner = FakeRunner()
        self._run_tree(project_file, tmp_path, runner)
        # 原件零改动 + 原旁零新文件（写面全在 work_root）
        assert project_file.read_bytes() == original_bytes
        assert [p.name for p in project_file.parent.iterdir()] == [
            project_file.name]
        # staging 清理（任务毕清理纪律）；产物在 bridged/ 不受影响
        stage_root = tmp_path / "work" / "bridge_stage"
        assert not any(stage_root.glob("*/*")) or not stage_root.exists() \
            or all(not d.exists() for d in stage_root.iterdir())
        assert any((tmp_path / "work" / "bridged").glob("*.aedt"))

    def test_non_ascii_work_root_loud_before_runner(
            self, project_file, tmp_path):
        runner = FakeRunner()
        context = _context(tmp_path, {
            "bridge_2023R2": {"ansysedt_exe": _BRIDGE_EXE}})
        context["work_root"] = str(tmp_path / "中文work")
        with pytest.raises(ValueError, match="非 ASCII"):
            run_bridge_executor(project_file, context, runner=runner)
        assert runner.calls == []

    def test_missing_project_loud(self, tmp_path):
        context = _context(tmp_path, {
            "bridge_2023R2": {"ansysedt_exe": _BRIDGE_EXE}})
        with pytest.raises(FileNotFoundError):
            run_bridge_executor(tmp_path / "nope.aedt", context,
                                runner=FakeRunner())

    def test_sha_from_inventory_entry_reused(self, project_file, tmp_path):
        """inventory_entry 带 sha256 时复用（S0 单点哈希，不二次计算）。"""
        context = _context(tmp_path, {
            "bridge_2023R2": {"ansysedt_exe": _BRIDGE_EXE}})
        context["inventory_entry"] = {
            "project": "filter21", "sha256": "cafebabe" + "0" * 56}
        runner = FakeRunner()
        res = run_bridge_executor(project_file, context, runner=runner)
        assert res["outcome"] == "success"
        assert Path(res["bridge_artifact"]).name == "filter21__cafebabe.aedt"

    def test_standalone_success_shape(self, project_file, tmp_path):
        res = run_bridge_executor(
            project_file,
            _context(tmp_path, {"bridge_2023R2": {
                "ansysedt_exe": _BRIDGE_EXE, "timeout_s": 60.0}}),
            runner=FakeRunner())
        assert res["outcome"] == "success"
        assert res["runner_rc"] == 0
        assert Path(res["bridge_artifact"]).is_file()
        assert res["stage_cleaned"] is True
        assert res["engine_identity"]["ansysedt_version"] == (
            BRIDGE_VERSION_DEFAULT)
        assert res["engine_identity"]["machine"]
        assert res["messages"][0].startswith("bridge version=")


# ---------------------------------------------------------------------------
# 远程配方清单钉（console 形态/中间根/清理清单/互斥标记/env 门）
# ---------------------------------------------------------------------------

class TestRemoteRecipe:
    def test_manifest_core_fields(self):
        env = aedt_migrate_remote_recipe("filter21", "abcd1234")
        assert env["ok"] is True
        assert env["channel"] == "aedt_migrate_bridge_remote"
        assert env["task"]["dir"] == (
            rf"{AEDT_MIGRATE_REMOTE_WORK_ROOT}"
            rf"\tasks\aedt_migrate_bridge_abcd1234")
        assert env["paths"]["input_staged"].endswith("input\\filter21.aedt")
        assert env["paths"]["artifact_out"].endswith(
            "out\\filter21__abcd1234.aedt")
        # 脚本单源：远程腿与本地腿同一 save-as 脚本构造器
        assert "SaveAs(" in env["script_content"]
        assert env["script_content"].split(
            'TARGET_PROJECT = r"')[1].split('"')[0] == (
            env["paths"]["artifact_out"])

    def test_manifest_launch_pending_env_gate(self):
        env = aedt_migrate_remote_recipe("p", "abcd1234")
        launch = env["launch"]
        assert launch["pending"] is True  # 挂账：不真发射
        assert launch["env_gate"] == AEDT_MIGRATE_REMOTE_ENV
        assert AEDT_MIGRATE_REMOTE_ENV == "RFAUTO_AEDT_MIGRATE_REMOTE"
        assert "60s/120s" in " ".join(launch["steps"])  # 0b-2 存活复核
        assert any("once" in s and "Delete" in s
                   for s in launch["steps"])  # schtasks 补刀
        assert "挂账" in launch["executor"]

    def test_manifest_mutex_pin_ansysedt_commandline(self):
        env = aedt_migrate_remote_recipe("p", "abcd1234")
        assert env["mutex"]["process"] == "ansysedt.exe"
        assert env["mutex"]["process"] == AEDT_MIGRATE_MUTEX_PROCESS
        # #261 共享单源复用（指纹=本通道 RunScript 脚本名）
        assert env["mutex"]["command"] == remote_mutex_command(
            "ansysedt.exe", AEDT_MIGRATE_MUTEX_FINGERPRINT)
        assert "RunScript" in AEDT_MIGRATE_MUTEX_FINGERPRINT
        assert BRIDGE_SCRIPT_NAME.removesuffix(".py") in (
            AEDT_MIGRATE_MUTEX_FINGERPRINT)

    def test_manifest_cleanup_verified_gone(self):
        env = aedt_migrate_remote_recipe("filter21", "abcd1234")
        cleanup = env["cleanup"]
        assert "schtasks /delete" in cleanup["schtasks_delete_form"]
        assert "/PID" in cleanup["kill_form"]
        assert "/IM" not in cleanup["kill_form"]  # 禁全杀
        # 任务毕 verified_gone：任务目录+staged 输入+产物逐路径复核
        assert env["task"]["dir"] in cleanup["verified_gone"]
        assert env["paths"]["input_staged"] in cleanup["verified_gone"]
        assert env["paths"]["artifact_out"] in cleanup["verified_gone"]

    def test_bat_console_visible_direct_form(self):
        task_dir = rf"{AEDT_MIGRATE_REMOTE_WORK_ROOT}\tasks\t1"
        bat = build_bridge_task_bat(
            task_dir, _BRIDGE_EXE, rf"{task_dir}\s.py",
            rf"{task_dir}\b.log")
        text = bat.decode("ascii")
        assert "@echo off" in text
        assert f'"{_BRIDGE_EXE}" -ng -Logfile' in text  # exe 直指
        assert "-RunScript" in text
        assert "launch_rc.txt" in text  # qx28 家法 delta
        assert "exit /b %RC%" in text
        # 反隐蔽形态（0b-2）：无 wscript / 无隐藏窗标志
        assert "wscript" not in text.lower()
        assert "windowstyle" not in text.lower()
        # CRLF 字节核验（写侧=远端同验）
        assert bat.count(b"\r\n") == bat.count(b"\n")
        assert bat.count(b"\n") > 0

    def test_manifest_bat_pending_without_exe(self):
        env = aedt_migrate_remote_recipe("p", "abcd1234")
        assert env["bat_content"] is None
        assert env["bat_pending_reason"]
        assert "2023 R2" in env["bat_pending_reason"]

    def test_manifest_bat_rendered_with_exe(self):
        env = aedt_migrate_remote_recipe(
            "p", "abcd1234", ansysedt_exe=_BRIDGE_EXE)
        assert env["bat_content"] is not None
        assert env["bat_pending_reason"] is None
        assert _BRIDGE_EXE in env["bat_content"]

    def test_work_root_sanctioned_only(self):
        env = aedt_migrate_remote_recipe(
            "p", "abcd1234", work_root="Q:\\not_allowed_root")
        assert env["ok"] is False
        assert any(AEDT_MIGRATE_REMOTE_WORK_ROOT in e
                   for e in env["errors"])

    def test_machine_cfg_injection_enriches_manifest(self):
        cfg = RemoteMachineConfig(
            name="bridge_host", host="10.0.0.9",
            hfss_project_root=r"E:\rfauto_remote")
        env = aedt_migrate_remote_recipe(
            "p", "abcd1234", machine_cfg=cfg)
        assert env["ok"] is True
        assert env["machine"] == {"name": "bridge_host", "host": "10.0.0.9"}
        assert env["work_root"] == r"E:\rfauto_remote"

    def test_machine_cfg_mismatched_root_refused(self):
        cfg = RemoteMachineConfig(
            name="odd_host", host="10.0.0.9",
            hfss_project_root=r"D:\other")
        env = aedt_migrate_remote_recipe("p", "abcd1234", machine_cfg=cfg)
        assert env["ok"] is False

    def test_machine_name_resolution_via_registry(self, monkeypatch):
        import rfauto.service.remote_service.aedt_migrate as _rm

        # 虚构机器名+虚构主机（机器名/主机=本机注册表语义演示，非真实拓扑）
        real_cfg = RemoteMachineConfig(
            name="lab_bridge_host", host="10.0.0.9",
            hfss_project_root=r"E:\rfauto_remote")
        monkeypatch.setattr(
            _rm, "load_remote_machines",
            lambda: {"lab_bridge_host": real_cfg})
        env = aedt_migrate_remote_recipe(
            "p", "abcd1234", machine="lab_bridge_host")
        assert env["ok"] is True
        assert env["machine"]["host"] == "10.0.0.9"
        # resolve_machine 单源一致性（同名解析同对象）
        assert resolve_machine("lab_bridge_host",
                               {"lab_bridge_host": real_cfg}) is (
            real_cfg)


# ---------------------------------------------------------------------------
# facade 注册钉 + 缺省 runner 形态钉
# ---------------------------------------------------------------------------

class TestFacadeAndRunner:
    def test_facade_reexports_registered(self):
        """facade hunk 注册钉（__all__ 金快照未动——扩面归 S4 同笔）。"""
        assert (_rs_facade.AEDT_MIGRATE_REMOTE_ENV
                is AEDT_MIGRATE_REMOTE_ENV)
        assert (_rs_facade.AEDT_MIGRATE_MUTEX_FINGERPRINT
                is AEDT_MIGRATE_MUTEX_FINGERPRINT)
        assert (_rs_facade.aedt_migrate_remote_recipe
                is aedt_migrate_remote_recipe)
        assert (_rs_facade.build_bridge_task_bat is build_bridge_task_bat)
        # 新名未进 __all__（public_api 金快照零漂移；申报挂账 S4）
        assert "aedt_migrate_remote_recipe" not in _rs_facade.__all__

    def test_submodule_registered_in_fanout(self):
        import importlib

        sub = importlib.import_module(
            "rfauto.service.remote_service.aedt_migrate")
        assert hasattr(sub, "aedt_migrate_remote_recipe")
        # facade setattr 扇出覆盖新子模块（AU-1 语义：补丁即全局生效）
        fanout = _rs_facade._FANOUT["aedt_migrate_remote_recipe"]
        assert "aedt_migrate" in fanout

    def test_subprocess_runner_smoke(self, tmp_path):
        """缺省 runner 形态钉（真跑形态；本席不真跑 AEDT，只验契约）。"""
        import sys

        res = subprocess_runner(
            [sys.executable, "-c", "print('ok')"], timeout_s=30.0)
        assert res["rc"] == 0
        assert "ok" in res["stdout_tail"]
        res2 = subprocess_runner(
            [sys.executable, "-c", "import sys; sys.exit(3)"],
            timeout_s=30.0)
        assert res2["rc"] == 3
