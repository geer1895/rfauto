"""ADS 网表批求解执行面（ads_batch，发射器可插拔）单测——全 fake 零真跑。

覆盖：
1. env 构造：复用 ads_netlist._build_ads_env 语义钉（HPEESOF_DIR + PATH
   前置序 bin/adsptolemy/tools-python）；_resolve_ads_dir 透传 ads_dir；
2. local 发射：命令形态（exe+网表名）/cwd/logfile 句柄；
3. ssh 发射：argv 形态钉字面（BatchMode/port/host/末位命令串）+ 远端
   命令串钉字面（#272 env/G5 零双引号/rc 透传）+ 引号转义守卫；
4. 网表自包含（#276）：缺引用 fail-fast 零 Popen / ssh 绝对路径拒绝 /
   相对依赖存在放行；
5. staging：跨目录 workdir 复制网表+相对依赖、原位零复制；
6. 超时击杀：watchdog 触发整树回收（fake kill 记 pid+放行）、timed_out
   如实；timeout_s<=0 不启动看门；
7. 发射器注册表扩展缝（测试内注册、finally 还原不污染）；
8. local 真机冒烟：env 门 RFAUTO_ADS_BATCH_REAL=1 opt-in（df4⑥ 真跑
   不进缺省 unit 门）+ ADS 缺席 skip——零真跑由其余用例保证（no_real_popen
   兜底闸：未被替换的 Popen 一律炸）。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

import rfauto.adapters.ads_batch as ab
from rfauto.adapters.ads_batch import (
    AdsBatchError,
    ads_batch_solve,
    build_remote_hpeesofsim_command,
    build_ssh_command,
    check_remote_path_safe,
    collect_ads_artifacts,
    scan_netlist_file_refs,
    stage_netlist_bundle,
    validate_netlist_self_containment,
)

_FAKE_ADS = Path("E:\\fake\\ADS27")

_NETLIST_BODY = (
    "Options ResourceUsage=yes UseNutmegFormat=no EnableOptim=no\n"
    'S_Param:SP1 CalcS=yes CalcY=no CalcZ=no StatusLevel=2 SweepVar="freq" '
    'SweepPlan="SP1_stim" OutputPlan="SP1_Output"\n'
    "SweepPlan: SP1_stim Start=1 GHz Stop=2 GHz Lin=11\n"
    'OutputPlan:SP1_Output Type="Output" EquationNestLevel=2 '
    "SavedEquationNestLevel=2\n"
    "Port:P1  P1 0 Num=1 Z=50 Ohm Noise=yes\n"
    "Port:P2  P2 0 Num=2 Z=50 Ohm Noise=yes\n"
)


def _write_netlist(tmp_path: Path, *, snp_ref: str | None = None,
                   name: str = "demo.net") -> Path:
    body = _NETLIST_BODY
    if snp_ref is not None:
        body += (
            'SnP:SNP1  P1 P2 NumPorts=2 File="' + snp_ref + '" '
            'Type="touchstone" InterpMode="linear" InterpDom="" '
            'ExtrapMode="constant" Temp=27.0 CheckPassivity=0\n'
        )
    p = tmp_path / name
    p.write_text(body, encoding="ascii")
    return p


# ─── 假进程 / 假发射器（test_hfss_batch 同款）────────────────────────────────

class _FakeProc:
    """subprocess.Popen 假进程：立即返回 rc 或阻塞到 kill 事件。"""

    def __init__(self, rc: int = 0, release: threading.Event | None = None,
                 pid: int = 4242) -> None:
        self.pid = pid
        self._rc = rc
        self._release = release

    def wait(self, timeout: float | None = None) -> int:
        if self._release is not None:
            assert self._release.wait(timeout=30.0), "fake proc 等待击杀超时"
        return self._rc


class _PopenRecorder:
    """Popen 替身：记录命令行/kwargs，杜绝真机进程。"""

    def __init__(self, proc: _FakeProc) -> None:
        self.proc = proc
        self.calls: list[dict] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append({"cmd": [str(c) for c in cmd], "kwargs": kwargs})
        return self.proc


@pytest.fixture()
def no_real_popen(monkeypatch):
    """兜底闸：未被替换的 Popen 一律炸（保证零真机零真跑）。"""

    def _boom(*_a, **_k):
        raise AssertionError("测试路径不得触达真实 subprocess.Popen")

    monkeypatch.setattr(ab.subprocess, "Popen", _boom)


@pytest.fixture()
def fake_ads(monkeypatch):
    """钉住 ADS 目录解析（_resolve_ads_dir 导入复用缝，patch 在消费点）。"""
    monkeypatch.setattr(ab, "_resolve_ads_dir", lambda explicit=None: _FAKE_ADS)
    return _FAKE_ADS


# ─── env 构造（复用 ads_netlist 语义钉）──────────────────────────────────────

class TestLocalEnv:
    def test_env_hpeesof_dir_and_path_prepend_order(self, tmp_path,
                                                    monkeypatch, fake_ads):
        """HPEESOF_DIR=ads 根；PATH 前置 bin/adsptolemy/tools-python（真机
        实证口径，ads_python_api.run_simulation 内联构造同域）。"""
        recorder = _PopenRecorder(_FakeProc(rc=0))
        monkeypatch.setattr(ab.subprocess, "Popen", recorder)
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(nl, timeout_s=60)
        assert res["ok"] and res["rc"] == 0, res
        call = recorder.calls[0]
        env = call["kwargs"]["env"]
        assert env["HPEESOF_DIR"] == str(fake_ads)
        pre = ";".join([
            str(fake_ads / "bin"),
            str(fake_ads / "adsptolemy" / "lib.win32_64"),
            str(fake_ads / "tools" / "python"),
        ])
        assert env["PATH"].startswith(pre + ";")
        # 前置不吞掉既有 PATH（os.environ 尾段保留）
        assert env["PATH"].endswith(os.environ.get("PATH", ""))

    def test_ads_dir_param_passes_through_resolver(self, tmp_path,
                                                   monkeypatch, no_real_popen):
        seen: list = []
        monkeypatch.setattr(
            ab, "_resolve_ads_dir",
            lambda explicit=None: seen.append(explicit) or _FAKE_ADS)
        recorder = _PopenRecorder(_FakeProc(rc=0))
        monkeypatch.setattr(ab.subprocess, "Popen", recorder)
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(nl, ads_dir="E:\\explicit\\ADS", timeout_s=60)
        assert res["ok"]
        assert seen == ["E:\\explicit\\ADS"]
        assert res["ads_dir"] == str(_FAKE_ADS)

    def test_resolver_unavailable_is_structured_fail(self, tmp_path,
                                                     monkeypatch,
                                                     no_real_popen):
        def _raise(_explicit=None):
            raise FileNotFoundError("找不到可用 ADS 安装。尝试过: x; y。")

        monkeypatch.setattr(ab, "_resolve_ads_dir", _raise)
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(nl, timeout_s=60)
        assert res["ok"] is False and res["rc"] is None
        assert "ADS 安装不可用" in res["errors"][0]


# ─── local 发射命令形态 ──────────────────────────────────────────────────────

class TestLocalLaunch:
    def test_command_shape_cwd_logfile(self, tmp_path, monkeypatch, fake_ads):
        recorder = _PopenRecorder(_FakeProc(rc=0))
        monkeypatch.setattr(ab.subprocess, "Popen", recorder)
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(nl, timeout_s=60)
        call = recorder.calls[0]
        assert call["cmd"] == [
            str(fake_ads / "bin" / "hpeesofsim.exe"), "demo.net"]
        assert call["kwargs"]["cwd"] == str(tmp_path)
        assert call["kwargs"]["stderr"] == ab.subprocess.STDOUT
        assert res["logfile"] == str(tmp_path / "hpeesofsim_batch_demo.log")
        assert Path(res["logfile"]).exists()  # 驱动侧真实打开（追加形态）
        assert res["workdir"] == str(tmp_path)
        assert res["staged"] == []  # 原位执行零复制
        assert res["launcher"] == "local"

    def test_nonzero_rc_structured_fail(self, tmp_path, monkeypatch, fake_ads):
        recorder = _PopenRecorder(_FakeProc(rc=3))
        monkeypatch.setattr(ab.subprocess, "Popen", recorder)
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(nl, timeout_s=60)
        assert res["ok"] is False
        assert res["rc"] == 3
        assert res["timed_out"] is False
        assert "rc=3" in res["errors"][0]

    def test_stdout_redirected_into_logfile(self, tmp_path, monkeypatch,
                                            fake_ads):
        """Popen 收到的 stdout 句柄即 logfile（追加形态，输出可回读）。"""
        recorded: dict = {}

        class _Proc:
            pid = 7

            def wait(self, timeout=None):
                return 0

        def _popen(cmd, **kwargs):
            recorded["stdout"] = kwargs.get("stdout")
            recorded["stdout"].write(b"sim line\n")
            return _Proc()

        monkeypatch.setattr(ab.subprocess, "Popen", _popen)
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(nl, timeout_s=60)
        assert recorded["stdout"] is not None
        assert "sim line" in res["logfile_tail"]


# ─── ssh 发射形态（钉字面）───────────────────────────────────────────────────

_EXPECTED_REMOTE_CMD = (
    "$env:HPEESOF_DIR='E:\\ADS\\ADS27'; "
    "$env:PATH='E:\\ADS\\ADS27\\bin;E:\\ADS\\ADS27\\adsptolemy\\lib.win32_64;"
    "E:\\ADS\\ADS27\\tools\\python;' + $env:PATH; "
    "Set-Location -LiteralPath 'E:\\rfauto_remote\\ads_abcd1234'; "
    "if (-not (Test-Path -LiteralPath "
    "'E:\\ADS\\ADS27\\bin\\hpeesofsim.exe')) "
    "{ Write-Output 'HPEESOFSIM_NOT_FOUND'; exit 3 }; "
    "& 'E:\\ADS\\ADS27\\bin\\hpeesofsim.exe' 'demo.net'; "
    "$rc = $LASTEXITCODE; if ($null -eq $rc) { exit 1 }; exit $rc"
)


class TestSshLaunch:
    def test_remote_command_literal(self):
        """远端命令串钉字面（#272 env 形态 / G5 零双引号 / G8 ; 链 / rc 透传；
        正斜杠入参归一为反斜杠）。"""
        cmd = build_remote_hpeesofsim_command(
            "E:/ADS/ADS27", "E:/rfauto_remote/ads_abcd1234", "demo.net")
        assert cmd == _EXPECTED_REMOTE_CMD
        assert '"' not in cmd  # G5 零双引号纪律
        assert cmd.count("'") % 2 == 0  # 单引号成对包裹
        assert "$LASTEXITCODE" in cmd  # rc 捕获
        assert cmd.endswith("exit $rc")  # rc 显式透传（exit $rc）

    def test_ssh_argv_literal(self):
        """ssh argv 钉字面：BatchMode 缺省 / -p 端口 / host / 末位命令串
        （单个 argv 元素=一整条远端命令）。"""
        argv = build_ssh_command(
            "ssh", "user@10.20.30.40", _EXPECTED_REMOTE_CMD, port=2222)
        assert argv == [
            "ssh", "-o", "BatchMode=yes", "-p", "2222",
            "user@10.20.30.40", _EXPECTED_REMOTE_CMD,
        ]
        assert argv[-1] == _EXPECTED_REMOTE_CMD  # 命令串恒为末位单元素

    def test_ssh_argv_no_port_with_extra_options(self):
        argv = build_ssh_command(
            "C:\\Windows\\System32\\OpenSSH\\ssh.exe", "sim_server", "dir",
            extra_options=["-o", "StrictHostKeyChecking=accept-new"])
        assert argv[0].endswith("ssh.exe")
        assert argv[1:4] == ["-o", "BatchMode=yes",
                             "-o"]  # 缺省选项在前，extra 追加
        assert "StrictHostKeyChecking=accept-new" in argv
        assert "-p" not in argv  # 未给端口不出现 -p

    def test_ssh_solve_end_to_end_envelope(self, tmp_path, monkeypatch,
                                           no_real_popen):
        recorder = _PopenRecorder(_FakeProc(rc=0))
        monkeypatch.setattr(ab.subprocess, "Popen", recorder)
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(
            nl, launcher="ssh", ssh_host="user@10.20.30.40",
            remote_hpeesof_dir="E:\\ADS\\ADS27",
            remote_work_dir="E:\\rfauto_remote\\ads_abcd1234",
            ssh_port=2222, timeout_s=120)
        assert res["ok"] and res["rc"] == 0, res
        assert recorder.calls[0]["cmd"] == [
            "ssh", "-o", "BatchMode=yes", "-p", "2222",
            "user@10.20.30.40", _EXPECTED_REMOTE_CMD.replace(
                "'demo.net'", f"'{nl.name}'"),
        ]
        assert res["launcher"] == "ssh"
        assert res["remote_command"] == _EXPECTED_REMOTE_CMD.replace(
            "'demo.net'", f"'{nl.name}'")
        # 远端数据集命名 = 网表全名 + .ds（remote_ads 通道实证口径）
        assert res["remote_dataset"] == (
            "E:\\rfauto_remote\\ads_abcd1234\\demo.net.ds")
        assert res["ads_dir"] == "E:\\ADS\\ADS27"
        assert res["artifacts"] == []  # 远端枚举/回拉归 service.remote_ads_run

    def test_quote_guard_rejects_space_and_quote(self):
        with pytest.raises(AdsBatchError, match="空白"):
            check_remote_path_safe("remote_work_dir", "E:\\a b\\w")
        with pytest.raises(AdsBatchError, match="单引号"):
            check_remote_path_safe("remote_hpeesof_dir", "E:\\a'b")
        assert check_remote_path_safe("x", "E:/ok/dir") == "E:\\ok\\dir"

    def test_ssh_unsafe_path_fails_before_popen(self, tmp_path, monkeypatch,
                                                no_real_popen):
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(
            nl, launcher="ssh", ssh_host="h",
            remote_hpeesof_dir="E:\\a b",  # 含空白 → fail-closed
            remote_work_dir="E:\\w")
        assert res["ok"] is False and res["rc"] is None
        assert "单引号或空白" in res["errors"][0]

    def test_ssh_missing_params_structured_fail(self, tmp_path,
                                                no_real_popen):
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(nl, launcher="ssh")
        assert res["ok"] is False and res["rc"] is None
        assert "ssh_host" in res["errors"][0]
        assert "remote_hpeesof_dir" in res["errors"][0]
        assert "remote_work_dir" in res["errors"][0]


# ─── 网表自包含检查（#276）───────────────────────────────────────────────────

class TestSelfContainment:
    def test_scan_refs_order_and_dedup(self, tmp_path):
        nl = _write_netlist(tmp_path, snp_ref="a.s2p")
        nl.write_text(
            nl.read_text(encoding="ascii")
            + 'SnP:SNP2  P1 P2 NumPorts=2 File="a.s2p"\n'
            'SnP:SNP3  P1 P2 NumPorts=2 File="sub\\b.s2p"\n'
            "Other: Filename=not_a_ref.txt\n",
            encoding="ascii")
        assert scan_netlist_file_refs(nl) == ["a.s2p", "sub\\b.s2p"]

    def test_missing_ref_fails_fast_zero_popen(self, tmp_path, monkeypatch,
                                               no_real_popen):
        recorder = _PopenRecorder(_FakeProc(rc=0))
        monkeypatch.setattr(ab.subprocess, "Popen", recorder)
        nl = _write_netlist(tmp_path, snp_ref="ghost.s2p")
        res = ads_batch_solve(nl, timeout_s=60)
        assert res["ok"] is False and res["rc"] is None
        assert "ghost.s2p" in res["errors"][0]
        assert "fail-fast" in res["errors"][0]
        assert recorder.calls == []  # 零 Popen

    def test_existing_relative_ref_passes_local(self, tmp_path, monkeypatch,
                                                fake_ads):
        (tmp_path / "dep.s2p").write_text("! touchstone", encoding="ascii")
        recorder = _PopenRecorder(_FakeProc(rc=0))
        monkeypatch.setattr(ab.subprocess, "Popen", recorder)
        nl = _write_netlist(tmp_path, snp_ref="dep.s2p")
        res = ads_batch_solve(nl, timeout_s=60)
        assert res["ok"] and res["staged"] == []

    def test_absolute_ref_ok_local_missing_reports(self, tmp_path):
        nl = _write_netlist(tmp_path, snp_ref="E:\\elsewhere\\x.s2p")
        errs = validate_netlist_self_containment(nl, portable=False)
        assert len(errs) == 1 and "x.s2p" in errs[0] and "缺失" in errs[0]

    def test_absolute_ref_rejected_for_ssh(self, tmp_path):
        nl = _write_netlist(tmp_path, snp_ref="E:\\elsewhere\\x.s2p")
        errs = validate_netlist_self_containment(nl, portable=True)
        assert len(errs) == 1
        assert "绝对路径" in errs[0] and "#276" in errs[0]

    def test_dotdot_traversal_rejected_both_modes(self, tmp_path):
        nl = _write_netlist(tmp_path, snp_ref="..\\escape.s2p")
        for portable in (False, True):
            errs = validate_netlist_self_containment(nl, portable=portable)
            assert len(errs) == 1 and "越界" in errs[0]

    def test_ssh_mode_rejects_absolute_ref_in_driver(self, tmp_path,
                                                     monkeypatch,
                                                     no_real_popen):
        nl = _write_netlist(tmp_path, snp_ref="E:\\local\\dep.s2p")
        res = ads_batch_solve(
            nl, launcher="ssh", ssh_host="h",
            remote_hpeesof_dir="E:\\ADS\\ADS27",
            remote_work_dir="E:\\rfauto_remote\\b1")
        assert res["ok"] is False and res["rc"] is None
        assert "#276" in res["errors"][0]


# ─── staging（跨目录 workdir 自包含副本）─────────────────────────────────────

class TestStaging:
    def test_stage_copies_netlist_and_relative_deps(self, tmp_path):
        src = tmp_path / "src"
        (src / "data").mkdir(parents=True)
        (src / "demo.net").write_text("x\n", encoding="ascii")
        (src / "data" / "dep.s2p").write_text("! ts", encoding="ascii")
        (src / "abs.s2p").write_text("! ts", encoding="ascii")
        nl = src / "demo.net"
        nl.write_text(
            'SnP:SNP1  P1 P2 NumPorts=2 File="data/dep.s2p"\n'
            'SnP:SNP2  P1 P2 NumPorts=2 File="' + str(src / "abs.s2p") + '"\n',
            encoding="ascii")
        out = tmp_path / "stage"
        out.mkdir()
        staged_nl, staged = stage_netlist_bundle(nl, out)
        assert staged_nl == out / "demo.net"
        assert staged == ["demo.net", "data/dep.s2p"]  # 网表在前，绝对引用不复制
        # staged 副本与源网表逐字节一致（shutil.copy2）
        assert (out / "demo.net").read_bytes() == nl.read_bytes()
        assert (out / "data" / "dep.s2p").exists()
        assert (out / "abs.s2p").exists() is False

    def test_stage_in_place_zero_copy(self, tmp_path):
        nl = _write_netlist(tmp_path)
        staged_nl, staged = stage_netlist_bundle(nl, tmp_path)
        assert staged_nl == nl and staged == []

    def test_solve_with_explicit_workdir_runs_staged_copy(
            self, tmp_path, monkeypatch, fake_ads):
        src = tmp_path / "src"
        src.mkdir()
        (src / "dep.s2p").write_text("! ts", encoding="ascii")
        nl = _write_netlist(src, snp_ref="dep.s2p")
        recorder = _PopenRecorder(_FakeProc(rc=0))
        monkeypatch.setattr(ab.subprocess, "Popen", recorder)
        workdir = tmp_path / "stage"
        res = ads_batch_solve(nl, workdir=workdir, timeout_s=60)
        assert res["ok"]
        assert res["netlist"] == str(workdir / "demo.net")
        assert sorted(res["staged"]) == ["demo.net", "dep.s2p"]
        call = recorder.calls[0]
        assert call["cmd"][1] == "demo.net"
        assert call["kwargs"]["cwd"] == str(workdir)
        assert res["logfile"] == str(workdir / "hpeesofsim_batch_demo.log")


# ─── 产物扫描回收 ────────────────────────────────────────────────────────────

class TestArtifacts:
    def test_collect_whitelist_including_ds_dir(self, tmp_path):
        (tmp_path / "out.s2p").write_text("! ts", encoding="ascii")
        (tmp_path / "curve.plt").write_text("plt", encoding="ascii")
        (tmp_path / "sim.log").write_text("log", encoding="ascii")
        ds = tmp_path / "demo.net.ds"
        ds.mkdir()
        (ds / "Master.ai_datadb").write_text("db", encoding="ascii")
        (tmp_path / "demo.net").write_text("nl", encoding="ascii")  # 网表非产物
        found = collect_ads_artifacts(tmp_path)
        names = [Path(f).name for f in found]
        assert names == ["curve.plt", "demo.net.ds", "out.s2p", "sim.log"]
        # .ds 目录整目录记一条（不递归展开）
        assert sum(1 for f in found if f.endswith(".ds")) == 1

    def test_collect_limit_and_missing_dir(self, tmp_path):
        for i in range(5):
            (tmp_path / f"o{i}.s2p").write_text("! ts", encoding="ascii")
        assert len(collect_ads_artifacts(tmp_path, limit=3)) == 3
        assert collect_ads_artifacts(tmp_path / "ghost") == []

    def test_solve_envelope_carries_artifacts(self, tmp_path, monkeypatch,
                                              fake_ads):
        (tmp_path / "demo.net.ds").mkdir()
        recorder = _PopenRecorder(_FakeProc(rc=0))
        monkeypatch.setattr(ab.subprocess, "Popen", recorder)
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(nl, timeout_s=60)
        assert [Path(f).name for f in res["artifacts"]] == [
            "demo.net.ds", "hpeesofsim_batch_demo.log"]

    def test_input_refs_excluded_from_artifacts(self, tmp_path, monkeypatch,
                                                fake_ads):
        """网表 File= 引用输入（与产物同为 .sNp 形态）不混入产物清单。"""
        (tmp_path / "dep.s2p").write_text("! ts", encoding="ascii")
        (tmp_path / "demo.net.ds").mkdir()
        recorder = _PopenRecorder(_FakeProc(rc=0))
        monkeypatch.setattr(ab.subprocess, "Popen", recorder)
        nl = _write_netlist(tmp_path, snp_ref="dep.s2p")
        res = ads_batch_solve(nl, timeout_s=60)
        names = [Path(f).name for f in res["artifacts"]]
        assert names == ["demo.net.ds", "hpeesofsim_batch_demo.log"]
        assert "dep.s2p" not in names


# ─── 超时击杀 / 看门语义 ─────────────────────────────────────────────────────

class TestTimeout:
    def test_timeout_kills_process_tree(self, tmp_path, monkeypatch, fake_ads):
        killed: list[int] = []
        release = threading.Event()

        def fake_kill(pid, timeout_s=10.0):
            killed.append(pid)
            release.set()
            return True

        monkeypatch.setattr(ab, "_kill_process_tree", fake_kill)

        class _BlockingProc:
            pid = 99

            @staticmethod
            def wait(timeout=None):
                assert release.wait(timeout=30.0), "watchdog 未击杀，假进程悬挂"
                return 1

        monkeypatch.setattr(ab.subprocess, "Popen",
                            lambda cmd, **kw: _BlockingProc())
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(nl, timeout_s=0.05)
        assert res["ok"] is False
        assert res["timed_out"] is True
        assert killed == [99]  # 整树击杀按 Popen 句柄 pid，不按进程名扫杀
        assert "超时" in res["errors"][0] and "击杀" in res["errors"][0]

    def test_ssh_timeout_notes_local_only_scope(self, tmp_path, monkeypatch,
                                                no_real_popen):
        """ssh 发射超时：击杀只及本地 ssh 客户端，远端孤儿面如实注记。"""
        killed: list[int] = []
        release = threading.Event()

        def fake_kill(pid, timeout_s=10.0):
            killed.append(pid)
            release.set()
            return True

        monkeypatch.setattr(ab, "_kill_process_tree", fake_kill)

        class _BlockingProc:
            pid = 55

            @staticmethod
            def wait(timeout=None):
                assert release.wait(timeout=30.0)
                return 1

        monkeypatch.setattr(ab.subprocess, "Popen",
                            lambda cmd, **kw: _BlockingProc())
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(
            nl, launcher="ssh", ssh_host="h",
            remote_hpeesof_dir="E:\\ADS\\ADS27",
            remote_work_dir="E:\\rfauto_remote\\b1", timeout_s=0.05)
        assert res["timed_out"] is True and killed == [55]
        assert "本地 ssh 客户端" in res["errors"][0]
        assert "remote_ads" in res["errors"][0]

    def test_nonpositive_timeout_means_unlimited(self, tmp_path, monkeypatch,
                                                 fake_ads, no_real_popen):
        """timeout_s<=0 = 不设超时（不启动 watchdog timer，避免立即触发）。"""
        started: list[float] = []

        class _SpyWatchdog(ab.Watchdog):
            def start(self, timeout_s, callback):
                started.append(float(timeout_s))
                super().start(timeout_s, callback)

        monkeypatch.setattr(ab, "Watchdog", _SpyWatchdog)
        recorder = _PopenRecorder(_FakeProc(rc=0))
        monkeypatch.setattr(ab.subprocess, "Popen", recorder)
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(nl, timeout_s=0)
        assert res["ok"] is True
        assert started == []  # watchdog 从未启动


# ─── 发射器注册表（可插拔缝）─────────────────────────────────────────────────

class TestLauncherRegistry:
    def test_unknown_launcher_structured_fail(self, tmp_path, no_real_popen):
        nl = _write_netlist(tmp_path)
        res = ads_batch_solve(nl, launcher="carrier_pigeon")
        assert res["ok"] is False and res["rc"] is None
        assert "carrier_pigeon" in res["errors"][0]
        assert "local" in res["errors"][0] and "ssh" in res["errors"][0]

    def test_register_extends_dispatch(self, tmp_path, monkeypatch,
                                       no_real_popen):
        calls: list[tuple] = []

        @ab.register_launcher("testprobe")
        def _probe(netlist_name, work_dir, log_handle, opts):
            calls.append((netlist_name, str(work_dir), opts))
            cmd = ["fake-launcher", netlist_name]
            return cmd, _FakeProc(rc=0), {"ads_dir": "E:\\probe"}

        saved = dict(ab._LAUNCHERS)
        try:
            nl = _write_netlist(tmp_path)
            res = ads_batch_solve(nl, launcher="testprobe", timeout_s=60)
            assert res["ok"] and res["rc"] == 0
            assert res["launcher"] == "testprobe"
            assert res["command"] == ["fake-launcher", "demo.net"]
            assert res["ads_dir"] == "E:\\probe"
            assert calls == [("demo.net", str(tmp_path), {
                "ads_dir": None, "ssh_host": None, "ssh_port": None,
                "ssh_exe": "ssh", "ssh_options": None,
                "remote_hpeesof_dir": None, "remote_work_dir": None,
            })]
        finally:
            # 注册表还原（测试不污染全局 _LAUNCHERS）
            ab._LAUNCHERS.clear()
            ab._LAUNCHERS.update(saved)

    def test_missing_netlist_structured_fail(self, tmp_path, no_real_popen):
        res = ads_batch_solve(tmp_path / "ghost.net")
        assert res["ok"] is False and res["rc"] is None
        assert res["command"] == []  # 未发射任何进程
        assert "ghost.net" in res["errors"][0]


# ─── local 真机冒烟（opt-in，零真跑由上方全部用例保证）───────────────────────

_REAL_ENV = "RFAUTO_ADS_BATCH_REAL"


@pytest.mark.skipif(
    os.environ.get(_REAL_ENV) != "1",
    reason=f"local 真机验证需显式 {_REAL_ENV}=1（opt-in，unit 门默认零真跑）")
def test_local_real_hpeesofsim_smoke(tmp_path):
    """真机 local 发射冒烟：合成自包含 2 端口（SnP 绝对引用）→ hpeesofsim
    → rc=0 + .ds 数据集落盘。需本机 ADS 2027（RFAUTO_HPEESOF_DIR 或
    settings.local.yaml hpeesof_dir），缺席如实 skip。"""
    from rfauto.adapters.ads_netlist import _resolve_ads_dir

    try:
        ads = _resolve_ads_dir(None)
    except FileNotFoundError as exc:
        pytest.skip(f"ADS 不可用（真机冒烟需 ADS 2027）: {exc}")

    import numpy as np
    import skrf

    freq = skrf.Frequency(1, 2, 11, "GHz")
    s = np.zeros((freq.npoints, 2, 2), dtype=complex)
    for k in range(freq.npoints):
        s[k, 0, 1] = s[k, 1, 0] = 1 / np.sqrt(2)
    snp = tmp_path / "demo.s2p"
    skrf.Network(frequency=freq, s=s, z0=50).write_touchstone(
        str(snp), form="ri")
    body = _NETLIST_BODY + (
        'SnP:SNP1  P1 P2 NumPorts=2 File="' + str(snp) + '" '
        'Type="touchstone" InterpMode="linear" InterpDom="" '
        'ExtrapMode="constant" Temp=27.0 CheckPassivity=0\n'
    )
    nl = tmp_path / "ads_batch_smoke.net"
    nl.write_text(body, encoding="ascii")

    res = ads_batch_solve(nl, launcher="local", timeout_s=600)
    assert res["ok"], res
    assert res["rc"] == 0 and res["timed_out"] is False
    assert res["ads_dir"] == str(ads)
    ds_names = [Path(a).name for a in res["artifacts"] if a.endswith(".ds")]
    assert ds_names == ["ads_batch_smoke.net.ds"], res["artifacts"]
