"""多机协同 v1 旗舰——service/remote_oe_service 单测（全离线，#139 通道 mock 钉死）。

覆盖：env 门拒绝（unit 门内必拒，零真机零连网）、座位内容物校验（#122 判据
先行 fail-closed/渲染产物必本地）、互斥三态（命中=候跑 SKIP 不发射/旁证非
CLEAR/查询失败 fail-closed）、同步通道五步（上传四件/bat CRLF 字节核验/发射
rc 透传/回拉镜像/清理 census）、rc≠0 产物在=PARTIAL 如实、回拉空=FAIL、清理
失败翻 FAIL、keep_remote 如实留档、轮询档（存活复核 60s/120s 双采样/rc 完成/
静默消失连续确认/超时不代杀）。SSH 通道全部 FakeTransport（patch 在消费点
roe.SshTransport，P3-7 家法；等待/时钟注入点零真睡零真钟）。
"""

import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.service.remote_oe_service as roe
from rfauto.infra.remote_machines import (
    ENV_REMOTE_SSH_PASSWORD,
    ENV_REMOTE_SSH_USER,
)
from rfauto.service.remote_oe_service import (
    REMOTE_OE_ENV,
    build_driver_py,
    build_mutex_command,
    build_run_task_bat,
    remote_oe_run,
)

WORK_ROOT = "E:\\rfauto_remote"

#: 命令形态标记（互斥直查 vs 批次存活查的区分锚，测试路由用）
MUTEX_MARK = "$_.Name -eq 'python.exe'"
UTC_MATCH = "$_.CommandLine -match"


def _one_machine(monkeypatch, **kw):
    from rfauto.infra.remote_machines import RemoteMachineConfig

    cfg = RemoteMachineConfig(
        name="sim_host", host="10.20.30.40", ssh_port=22,
        hfss_project_root=kw.pop("project_root", WORK_ROOT),
        probe_ports={"ansys_license": 1055},
        **kw,
    )
    monkeypatch.setattr(roe, "load_remote_machines", lambda: {"sim_host": cfg})
    return cfg


def _set_creds(monkeypatch):
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")


def _mock_probe(monkeypatch):
    monkeypatch.setattr(
        roe, "probe_machine",
        lambda cfg: {"name": cfg.name, "reachable": True, "ports": {}},
    )


def _seat_spec(**kw):
    spec = {
        "template": "bend",
        "simulation_py": "# rendered simulation.py\n",
        "criteria_md": "# criteria（#122 判据先行）\n- G1..G5\n",
        "timeout_s": 120.0,
        "campaign": "ge_fd",
        "render_sha256": "ab" * 32,
    }
    spec.update(kw)
    return spec


class FakeTransport:
    """全通道 mock：按命令形态应答（互斥直查/旁证探针/建目录/rc 文件/
    批次进程查/port_ut 尾/枚举/清理）。等待与超时判定经 sleep_fn/now_fn 注入，
    本类零时序依赖。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.commands: list[str] = []
        self.uploads: list[tuple[str, str]] = []
        self.uploaded_bytes: dict[str, bytes] = {}
        self.downloads: list[tuple[str, str]] = []
        self.dirs: list[str] = []
        self.removed: set[str] = set()
        self.mutex_hits: list[str] = []
        self.probe_output = "===== probe =====\nmutex CLEAR\n"
        self.exec_rc = 0
        self.exec_stdout = "[launch] ok\n[launch done] rc=0\nproduct-census:\n"
        self.launch_rc_text: str | None = "rc=0"
        self.rc_visible_after_checks = 0
        self._rc_checks = 0
        self.batch_procs: list[str] = []
        self.port_ut_tail = "port_ut_0|1.234e-08 0.045"
        self.listing_rel = ["simulation.py", "driver.log",
                            "sparams.csv", "fdtd/port_ut_0"]
        self.fail_on = None
        self.start_process_rc = 0

    def connect(self):
        if self.fail_on == "connect":
            raise ConnectionError("mock: connect refused")
        self.connected = True

    def run_command(self, cmd, timeout_s=60.0):
        self.commands.append(cmd)
        if self.fail_on and cmd.startswith(self.fail_on):
            raise RuntimeError("mock: command boom")
        if "$_.Name -eq 'python.exe'" in cmd:            # 互斥直查（权威）
            return 0, "".join(f"{h}\n" for h in self.mutex_hits), ""
        if "run_server_probe.ps1" in cmd:                 # 互斥旁证
            return 0, self.probe_output, ""
        if "cleanup_after_task.ps1" in cmd:               # census 旁证
            return 0, "census: no rfauto/openEMS procs\n", ""
        if cmd.startswith("New-Item"):
            self.dirs.append(cmd.split("'")[1])
            return 0, "", ""
        if cmd.startswith("Start-Process"):               # poll 档发射
            return self.start_process_rc, "", ""
        if cmd.startswith("Test-Path"):
            target = cmd.split("'")[1].lower()
            if any(target == r or target.startswith(r + "\\")
                   for r in self.removed):
                return 0, "False\n", ""
            if target.endswith("\\launch_rc.txt"):
                self._rc_checks += 1
                if (self.launch_rc_text is None
                        or self._rc_checks < self.rc_visible_after_checks):
                    return 0, "False\n", ""
                return 0, "True\n", ""
            return 0, "True\n", ""
        if "Get-Content -LiteralPath" in cmd and "launch_rc.txt" in cmd:
            return 0, f"{self.launch_rc_text}\n", ""
        if "$_.CommandLine -match" in cmd:                # 批次存活查
            return 0, "".join(f"{p}\n" for p in self.batch_procs), ""
        if "port_ut_*" in cmd:                            # port_ut 尾行
            return 0, self.port_ut_tail + "\n" if self.port_ut_tail else "", ""
        if cmd.startswith("Get-ChildItem"):
            task = cmd.split("'")[1]
            lines = [f"{task}\\{rel}" for rel in self.listing_rel]
            return 0, ("\n".join(lines) + "\n") if lines else "", ""
        if cmd.startswith("Remove-Item"):
            self.removed.add(cmd.split("'")[1].lower())
            return 0, "", ""
        if cmd.startswith("cmd /c"):                      # sync 档发射
            return self.exec_rc, self.exec_stdout, ""
        return 0, "", ""

    def upload_file(self, local, remote):
        # 记录上传字节（staging 目录在通道 finally 即删——读回走本记录）
        self.uploads.append((str(local), remote))
        self.uploaded_bytes[remote] = Path(local).read_bytes()

    def download_file(self, remote, local):
        self.downloads.append((remote, str(local)))
        p = Path(local)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake-oe-product-bytes")

    def close(self):
        self.closed = True


def _run_sync(monkeypatch, tmp_path, transport=None, **kw):
    monkeypatch.setenv(REMOTE_OE_ENV, "1")
    _one_machine(monkeypatch, **kw.pop("machine_kw", {}))
    _set_creds(monkeypatch)
    _mock_probe(monkeypatch)
    t = transport or FakeTransport(None)
    monkeypatch.setattr(roe, "SshTransport", lambda cfg: t)
    out_dir = tmp_path / "pull"
    envelope = remote_oe_run(
        "sim_host", _seat_spec(**kw.pop("spec_kw", {})),
        out_dir=out_dir, **kw,
    )
    return envelope, t, out_dir


# ─── env 门（真机 opt-in，unit 门内必拒） ──────────────────────────────────


def test_run_refuses_without_env_gate(monkeypatch):
    monkeypatch.delenv(REMOTE_OE_ENV, raising=False)

    def _boom(*a, **kw):
        raise AssertionError("env 门未开时不得发起任何连接")

    monkeypatch.setattr(roe, "SshTransport", _boom)
    out = remote_oe_run("sim_host", _seat_spec())
    assert out["ok"] is False and out["skipped"] is True
    assert "RFAUTO_REMOTE_SMOKE" in out["reason"]


def test_run_no_registered_machines(monkeypatch):
    monkeypatch.setenv(REMOTE_OE_ENV, "1")
    monkeypatch.setattr(roe, "load_remote_machines", lambda: {})
    out = remote_oe_run(None, _seat_spec())
    assert out["skipped"] is True and "无登记机器" in out["reason"]


def test_run_missing_credentials_no_ssh(monkeypatch):
    monkeypatch.setenv(REMOTE_OE_ENV, "1")
    _one_machine(monkeypatch)
    monkeypatch.delenv(ENV_REMOTE_SSH_USER, raising=False)
    monkeypatch.delenv(ENV_REMOTE_SSH_PASSWORD, raising=False)
    _mock_probe(monkeypatch)

    def _boom(*a, **kw):
        raise AssertionError("凭据缺失时不得发起 SSH")

    monkeypatch.setattr(roe, "SshTransport", _boom)
    out = remote_oe_run("sim_host", _seat_spec())
    assert out["skipped"] is True
    assert out["steps"]["ssh"]["auth"] == "missing_credentials"


def test_run_missing_project_root_skips(monkeypatch):
    monkeypatch.setenv(REMOTE_OE_ENV, "1")
    _one_machine(monkeypatch, project_root="")
    _set_creds(monkeypatch)
    _mock_probe(monkeypatch)

    def _boom(*a, **kw):
        raise AssertionError("配置缺失时不得发起 SSH")

    monkeypatch.setattr(roe, "SshTransport", _boom)
    out = remote_oe_run("sim_host", _seat_spec())
    assert out["skipped"] is True and "project_root" in out["reason"]


# ─── 座位内容物校验（纯函数，fail-closed 不发射） ──────────────────────────


@pytest.mark.parametrize("mutate,frag", [
    ({"template": ""}, "template"),
    ({"template": "a b"}, "template"),
    ({"simulation_py": ""}, "simulation_py"),
    ({"simulation_py": "  "}, "simulation_py"),
    ({"criteria_md": ""}, "criteria_md"),
    ({"criteria_md": "  "}, "判据先行"),
    ({"timeout_s": 0}, "timeout_s"),
    ({"timeout_s": -1}, "timeout_s"),
    ({"campaign": ""}, "campaign"),
])
def test_seat_spec_validation_failclosed(monkeypatch, mutate, frag):
    monkeypatch.setenv(REMOTE_OE_ENV, "1")
    _one_machine(monkeypatch)
    _set_creds(monkeypatch)
    _mock_probe(monkeypatch)

    def _boom(*a, **kw):
        raise AssertionError("座位校验失败时不得发起 SSH")

    monkeypatch.setattr(roe, "SshTransport", _boom)
    out = remote_oe_run("sim_host", _seat_spec(**mutate))
    assert out["ok"] is False and out["launched"] is False
    assert frag in out["reason"]


def test_wait_mode_invalid_rejected(monkeypatch):
    monkeypatch.setenv(REMOTE_OE_ENV, "1")
    _one_machine(monkeypatch)

    def _boom(*a, **kw):
        raise AssertionError("wait_mode 非法时不得发起 SSH")

    monkeypatch.setattr(roe, "SshTransport", _boom)
    out = remote_oe_run("sim_host", _seat_spec(), wait_mode="detached")
    assert out["ok"] is False and "wait_mode" in out["reason"]


# ─── 互斥三态（#261 服务器侧：命中候跑/旁证/查询失败 fail-closed） ──────────


def test_mutex_busy_skips_without_launch(monkeypatch, tmp_path):
    t = FakeTransport(None)
    t.mutex_hits = ["4242|python -u E:\\rfauto_remote\\tasks\\oe_x\\driver.py"]
    envelope, t2, _o = _run_sync(monkeypatch, tmp_path, transport=t)
    assert envelope["skipped"] is True and envelope["launched"] is False
    assert "候跑" in envelope["reason"] and "禁止代杀" in envelope["reason"]
    assert envelope["criteria"]["c1_mutex_clear"] is False
    assert not t2.uploads                            # 未上传=未发射
    assert not any(c.startswith("New-Item") for c in t2.commands)
    # 清理复核仍走（finally）：无目录=verified_gone，无残留
    assert envelope["steps"]["cleanup"]["verified_gone"] is True
    assert not any("taskkill" in c or "Stop-Process" in c
                   for c in t2.commands)             # 全模块零杀进程命令


def test_mutex_probe_busy_is_also_busy(monkeypatch, tmp_path):
    """旁证非 CLEAR（直查零命中）同样候跑——宁枉勿纵，绝不抢席位。"""
    t = FakeTransport(None)
    t.probe_output = "mutex BUSY x2\n"
    envelope, _t2, _o = _run_sync(monkeypatch, tmp_path, transport=t)
    assert envelope["skipped"] is True and "候跑" in envelope["reason"]


def test_mutex_probe_busy_value_lines_without_mutex_word(monkeypatch, tmp_path):
    """真机实证形态（2026-10-01）：探针 census 表头含 mutex 字样而值行
    "BUSY: PID=..." 不含——双扫描必须抓到 BUSY 值行（宁枉勿纵）。"""
    t = FakeTransport(None)
    t.probe_output = (
        "=== [6] current solver-process census (#261 mutex precheck) ===\n"
        'BUSY: PID=8584 CMD="python" -u scripts\\varactor_smoke.py\n')
    envelope, _t2, _o = _run_sync(monkeypatch, tmp_path, transport=t)
    assert envelope["skipped"] is True and "候跑" in envelope["reason"]


def test_mutex_probe_census_header_not_false_busy(monkeypatch, tmp_path):
    """回归钉：census 表头行（含 mutex 字样非 clear）不得判假忙——否则
    CLEAR 服务器被永久堵门（2026-10-01 代码审查抓出）。"""
    t = FakeTransport(None)
    t.probe_output = (
        "=== [6] current solver-process census (#261 mutex precheck) ===\n"
        "mutex CLEAR\n")
    envelope, _t2, _o = _run_sync(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is True and envelope["launched"] is True
    assert envelope["criteria"]["c1_mutex_clear"] is True


def test_mutex_query_fail_failclosed(monkeypatch, tmp_path):
    """直查 rc≠0（验不了）→ fail-closed 不发射，不冒充互斥 CLEAR。"""
    t = FakeTransport(None)

    real_run = t.run_command

    def run_with_failed_mutex(cmd, timeout_s=60.0):
        if "$_.Name -eq 'python.exe'" in cmd:
            return 2, "", "cim failed"
        return real_run(cmd, timeout_s)

    t.run_command = run_with_failed_mutex
    envelope, t2, _o = _run_sync(monkeypatch, tmp_path, transport=t)
    assert envelope["skipped"] is True and envelope["launched"] is False
    assert "fail-closed" in envelope["reason"]
    assert not any(c.startswith("New-Item") for c in t2.commands)


# ─── 同步通道五步（全链 happy path） ───────────────────────────────────────


def test_sync_happy_path(monkeypatch, tmp_path):
    envelope, t, out_dir = _run_sync(monkeypatch, tmp_path)
    assert envelope["ok"] is True and envelope["verdict"] == "PASS"
    assert envelope["launched"] is True and envelope["exec_rc"] == 0
    c = envelope["criteria"]
    assert c["c1_mutex_clear"] and c["c2_products_fetched"]
    assert c["c3_workdir_cleaned"]
    # 上传：四件轻量文件落任务目录（sftp 面 / 分隔），任务目录唯一化
    uploaded = {Path(local_p).name: remote
                for local_p, remote in t.uploads}
    assert set(uploaded) == {"simulation.py", "criteria.md", "driver.py",
                             "run_task.bat"}
    task_sftp = envelope["task_dir_remote"].replace("\\", "/")
    assert all(r.startswith(task_sftp + "/") for r in uploaded.values())
    assert envelope["task_dir_remote"].startswith(WORK_ROOT + "\\tasks\\oe_")
    # bat CRLF 字面核验（上传字节=写侧字节，sftp 二进制安全；staging 已删，
    # 字节读 FakeTransport 上传记录）
    bat_remote = next(r for _l, r in t.uploads if r.endswith("run_task.bat"))
    bat_bytes = t.uploaded_bytes[bat_remote]
    assert bat_bytes.count(b"\r\n") == bat_bytes.count(b"\n") > 0
    assert b"call E:\\rfauto_remote\\rfauto_env.bat" in bat_bytes
    assert b"(echo rc=%RC%)>" in bat_bytes and b"exit /b %RC%" in bat_bytes
    # 发射形态：§5.4 直指（cmd /c 裸路径，零双引号）
    launch = next(c for c in t.commands if c.startswith("cmd /c"))
    assert launch == f"cmd /c {envelope['task_dir_remote']}\\run_task.bat"
    # 回拉镜像：out_dir 下 fdtd/ 子目录层级还原
    assert (out_dir / "sparams.csv").is_file()
    assert (out_dir / "fdtd" / "port_ut_0").is_file()
    assert envelope["steps"]["fetch"]["files"] == len(t.listing_rel)
    # 服务器命令面：建目录/枚举/census/清理全在档；清理=任务目录点删+复核
    assert sum(1 for c in t.commands if c.startswith("New-Item")) == 1
    assert any(c.startswith("Get-ChildItem -LiteralPath") for c in t.commands)
    assert any("cleanup_after_task.ps1" in c for c in t.commands)
    remove = [c for c in t.commands if c.startswith("Remove-Item")]
    assert remove == [
        f"Remove-Item -LiteralPath '{envelope['task_dir_remote']}' "
        "-Recurse -Force -ErrorAction SilentlyContinue"]
    # steps 逐步落账（五步+probe/mutex/ssh）
    for key in ("probe", "mutex", "ssh", "upload", "launch", "wait",
                "fetch", "cleanup"):
        assert key in envelope["steps"], key
    assert envelope["steps"]["wait"]["rc_file_crosscheck"]["rc"] == 0
    assert envelope["steps"]["cleanup"]["verified_gone"] is True
    assert envelope["render_sha256"] == "ab" * 32


def test_exec_rc_nonzero_with_products_partial(monkeypatch, tmp_path):
    """引擎 rc≠0 但产物在档：通道 ok=PARTIAL 如实（判读交本地降档），不假绿。"""
    t = FakeTransport(None)
    t.exec_rc = 3
    t.launch_rc_text = "rc=3"
    envelope, _t2, _o = _run_sync(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is True and envelope["verdict"] == "PARTIAL"
    assert envelope["exec_rc"] == 3
    assert "rc=3" in envelope["reason"] and "降档" in envelope["reason"]
    assert envelope["criteria"]["c2_products_fetched"] is True


def test_exec_rc_nonzero_without_products_failclosed(monkeypatch, tmp_path):
    t = FakeTransport(None)
    t.exec_rc = 3
    t.listing_rel = []
    envelope, _t2, _o = _run_sync(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is False and envelope["verdict"] == "FAIL"
    assert "无可回拉产物" in envelope["reason"]
    assert envelope["criteria"]["c2_products_fetched"] is False


def test_fetch_empty_enumeration_failclosed(monkeypatch, tmp_path):
    t = FakeTransport(None)
    t.listing_rel = []
    envelope, _t2, _o = _run_sync(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is False
    assert "无可回拉产物" in envelope["reason"]


def test_cleanup_failure_flips_verdict(monkeypatch, tmp_path):
    """清理失败翻 FAIL（任务毕必须清理， 0b）——不静默放行。"""
    t = FakeTransport(None)

    real_run = t.run_command

    def run_with_failed_remove(cmd, timeout_s=60.0):
        if cmd.startswith("Remove-Item"):
            return 1, "in use\n", ""
        return real_run(cmd, timeout_s)

    t.run_command = run_with_failed_remove
    envelope, _t2, _o = _run_sync(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is False and envelope["verdict"] == "FAIL"
    assert "清理" in envelope["reason"]
    assert envelope["criteria"]["c3_workdir_cleaned"] is False


def test_keep_remote_skips_cleanup_honestly(monkeypatch, tmp_path):
    t = FakeTransport(None)
    envelope, t2, _o = _run_sync(monkeypatch, tmp_path, transport=t,
                                 keep_remote=True)
    assert envelope["ok"] is True
    assert not any(c.startswith("Remove-Item") for c in t2.commands)
    assert envelope["steps"]["cleanup"]["skipped"] is True


def test_link_bare_exception_failclosed(monkeypatch, tmp_path):
    """链路裸抛（connect 后命令炸）→ fail-closed 信封（L2 同构）。"""
    t = FakeTransport(None)
    t.fail_on = "New-Item"
    envelope, _t2, _o = _run_sync(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is False
    assert "链路异常" in envelope["reason"] and "RuntimeError" in envelope["reason"]


def test_batch_dir_unique_per_call(monkeypatch, tmp_path):
    e1, _t1, _o = _run_sync(monkeypatch, tmp_path)
    e2, _t2, _o = _run_sync(monkeypatch, tmp_path)
    assert e1["task_dir_remote"] != e2["task_dir_remote"]


def test_backup_window_flag_registered(monkeypatch, tmp_path):
    """02:50–05:35 备份窗发射=信封如实登记（不阻断，操作方自负）。"""
    import time as _time

    monkeypatch.setenv(REMOTE_OE_ENV, "1")
    _one_machine(monkeypatch)
    _set_creds(monkeypatch)
    _mock_probe(monkeypatch)
    t = FakeTransport(None)
    monkeypatch.setattr(roe, "SshTransport", lambda cfg: t)
    monkeypatch.setattr(_time, "localtime",
                        lambda: _time.struct_time(
                            (2026, 9, 30, 3, 0, 0, 0, 0, 0)))
    envelope = remote_oe_run("sim_host", _seat_spec(),
                             out_dir=tmp_path / "pull")
    assert envelope["backup_window_risk"] is True


def test_backup_window_bounds():
    assert roe._in_backup_window(
        _mk(2, 49)) is False
    assert roe._in_backup_window(_mk(2, 50)) is True
    assert roe._in_backup_window(_mk(4, 0)) is True
    assert roe._in_backup_window(_mk(5, 35)) is True
    assert roe._in_backup_window(_mk(5, 36)) is False


def _mk(h, m):
    import time as _time
    return _time.struct_time((2026, 9, 30, h, m, 0, 0, 0, 0))


# ─── 轮询档（长座位：存活复核/轮询/静默消失/超时不代杀） ────────────────────


def test_poll_happy_path_with_survival_checks(monkeypatch, tmp_path):
    """发射后 60s/120s 双采样（进程在场+CPU 增量）→ 轮询 rc 文件完成。"""
    t = FakeTransport(None)
    t.rc_visible_after_checks = 3     # 存活双采样期 rc 未落，第 3 查完成
    t.batch_procs = ["777|12.5"]
    cpu = {"v": 12.5}

    real_run = t.run_command

    def run_with_growing_cpu(cmd, timeout_s=60.0):
        # 注意：互斥直查命令同含 "$_.CommandLine -match"——须按 Name 过滤
        # 存在与否区分（互斥命令归 FakeTransport 原路由应答）
        t.commands.append(cmd)
        if (UTC_MATCH in cmd) and (MUTEX_MARK not in cmd):
            cpu["v"] += 30.0          # 每次采样 CPU 增量（0b-2 进度证据）
            return 0, f"777|{cpu['v']}\n", ""
        return real_run(cmd, timeout_s)

    t.run_command = run_with_growing_cpu
    envelope, t2, out_dir = _run_sync(
        monkeypatch, tmp_path, transport=t, wait_mode="poll",
        sleep_fn=lambda _s: None,
    )
    assert envelope["ok"] is True and envelope["verdict"] == "PASS"
    assert envelope["exec_rc"] == 0
    launch = envelope["steps"]["launch"]
    assert launch["mode"] == "poll"
    assert launch["command"].startswith("Start-Process -FilePath 'cmd.exe'")
    assert '"' not in launch["command"]            # G5 零双引号
    assert "run_task.bat" in launch["command"]
    wait = envelope["steps"]["wait"]
    assert wait["mode"] == "poll" and wait["done"] is True
    surv = wait["survival"]
    assert surv["alive"] is True and surv["cpu_progress"] is True
    assert [s["delay_s"] for s in surv["samples"]] == [60.0, 120.0]
    # 双采样命令确实落在 60s/120s 两个时点（存活复核非可选项，0b-2）
    batch_queries = [c for c in t2.commands if "$_.CommandLine -match" in c]
    assert len(batch_queries) >= 2
    assert (out_dir / "sparams.csv").is_file()


def test_poll_silent_death_confirmed(monkeypatch, tmp_path):
    """双采样零进程+无 rc → 轮询环连续 2 次确认 → 静默消失 FAIL（0b-2 嫌疑）。"""
    t = FakeTransport(None)
    t.launch_rc_text = None            # rc 永不落盘
    t.batch_procs = []                 # 进程永不在场
    envelope, _t2, _o = _run_sync(
        monkeypatch, tmp_path, transport=t, wait_mode="poll",
        sleep_fn=lambda _s: None,
    )
    assert envelope["ok"] is False and envelope["verdict"] == "FAIL"
    assert envelope["launched"] is True
    assert "静默消失" in envelope["reason"]
    assert envelope["steps"]["wait"]["silent_death"] is True
    assert envelope["steps"]["wait"]["survival"]["alive"] is False


def test_poll_timeout_records_pids_no_kill(monkeypatch, tmp_path):
    """轮询超时：PIDs 落信封交人工处置，**不代杀**（全命令零杀进程形态）。"""
    t = FakeTransport(None)
    t.launch_rc_text = None
    t.batch_procs = ["888|99.0"]
    ticks = iter(range(0, 10**9, 1000))     # 假钟：每次读 +1000s

    envelope, t2, _o = _run_sync(
        monkeypatch, tmp_path, transport=t, wait_mode="poll",
        sleep_fn=lambda _s: None, now_fn=lambda: next(ticks),
    )
    assert envelope["ok"] is False and envelope["verdict"] == "FAIL"
    assert "轮询超时" in envelope["reason"] and "不代杀" in envelope["reason"]
    assert envelope["steps"]["wait"]["timeout"] is True
    assert envelope["steps"]["wait"]["survival"]["alive"] is True
    assert not any("taskkill" in c or "Stop-Process" in c
                   for c in t2.commands)


def test_poll_launch_command_fail_failclosed(monkeypatch, tmp_path):
    t = FakeTransport(None)
    t.start_process_rc = 1
    envelope, _t2, _o = _run_sync(
        monkeypatch, tmp_path, transport=t, wait_mode="poll",
        sleep_fn=lambda _s: None,
    )
    assert envelope["ok"] is False and envelope["launched"] is True
    assert "发射命令失败" in envelope["reason"]


def test_poll_fast_seat_rc_during_survival(monkeypatch, tmp_path):
    """短座位在存活采样期即完成：rc 早到=完成证据，复核让位不误判。"""
    t = FakeTransport(None)
    t.rc_visible_after_checks = 1     # 第一次采样点 rc 已在
    envelope, _t2, _o = _run_sync(
        monkeypatch, tmp_path, transport=t, wait_mode="poll",
        sleep_fn=lambda _s: None,
    )
    assert envelope["ok"] is True and envelope["exec_rc"] == 0
    assert envelope["steps"]["wait"]["survival"]["rc_early_seen"] is True


# ─── 纯函数构建器形态钉 ────────────────────────────────────────────────────


def test_build_mutex_command_shape():
    cmd = build_mutex_command()
    assert '"' not in cmd and "&&" not in cmd and "cmd /c" not in cmd
    assert "$_.Name -eq 'python.exe'" in cmd
    assert "simulation\\.py" in cmd and "_rfauto_runner" in cmd
    assert "'{0}|{1}' -f $_.ProcessId, $_.CommandLine" in cmd


def test_build_run_task_bat_shape_and_crlf():
    bat = build_run_task_bat("E:\\rfauto_remote\\tasks\\oe_x",
                             "E:\\rfauto_remote\\rfauto_env.bat")
    assert bat.count(b"\r\n") == bat.count(b"\n") > 0     # CRLF 字节纪律
    assert b"@echo off" in bat
    assert b'set "TASK_DIR=E:\\rfauto_remote\\tasks\\oe_x"' in bat
    assert b"-u \"%TASK_DIR%\\driver.py\"" in bat          # #157 防缓冲
    assert b'> "%TASK_DIR%\\driver.log" 2> "%TASK_DIR%\\driver.err"' in bat
    assert b"(echo rc=%RC%)>" in bat                       # poll 档 rc 落盘
    assert b"exit /b %RC%" in bat and b"cd /d %RFAUTO_REPO%" in bat


def test_build_driver_py_compiles_and_shape():
    src = build_driver_py(2400.0)
    compile(src, "driver.py", "exec")                      # 服务器侧可执行
    assert "TIMEOUT_S = 2400.0" in src
    assert "_rfauto_runner.py" in src
    assert "os.add_dll_directory" in src                   # Py3.8+ DLL 接线
    assert "runpy.run_path(sys.argv[1], run_name='__main__')" in src
    assert "simulation.py" in src
    assert "_last_stdout.log" in src and "_last_stderr.log" in src
    assert "TimeoutExpired" in src and "124" in src        # 超时=rc 124


def test_check_remote_safe_rejects_quotes_and_spaces():
    with pytest.raises(roe.RemoteOeError):
        roe._check_remote_safe("x", "E:\\some dir")
    with pytest.raises(roe.RemoteOeError):
        roe._check_remote_safe("x", "E:\\it's")
    assert roe._check_remote_safe("x", "E:/a/b") == "E:\\a\\b"


def test_check_remote_safe_rejects_cmd_metacharacters():
    """ge5 审查 F7 修复钉：cmd/PS 元字符与变量展开前缀 fail-closed 拒绝.

    修复前只拒单引号+空白——`E:\\x&whoami` / `E:\\rfauto%PATH%x` /
    `E:\\a^b` 全部放行（审查报告实测复现面）。
    """
    for evil in ("E:\\x&whoami", "E:\\a|b", "E:\\a<b", "E:\\a>b",
                 "E:\\a^b", "E:\\rfauto%PATH%x"):
        with pytest.raises(roe.RemoteOeError, match="cmd 元字符"):
            roe._check_remote_safe("x", evil)
    # 合法路径（盘符冒号/反斜杠/下划线/点/连字符）不受影响
    assert roe._check_remote_safe("x", "E:\\rfauto_remote\\oe_2026") == (
        "E:\\rfauto_remote\\oe_2026")


# ─── ge6 followUp 清偿批（F1/F3） ──────────────────────────────────────────


def test_poll_rc_file_unparseable_partial_not_silent_pass(monkeypatch, tmp_path):
    """F1 修复钉：poll 档 launch_rc.txt 在档但内容非 rc=<int> 形态 →
    信封显式 PARTIAL+errors 留痕（修复前走 else 分支静默 PASS——exec_rc=None
    且产物在=假绿；campaign 层 solve_success=(exec_rc==0)=False 兜底不受
    影响，本钉收的是通道信封层口径）。"""
    t = FakeTransport(None)
    t.launch_rc_text = "rc=???"       # 在档但不可解析（int('???') ValueError）
    envelope, _t2, _o = _run_sync(
        monkeypatch, tmp_path, transport=t, wait_mode="poll",
        sleep_fn=lambda _s: None,
    )
    assert envelope["verdict"] == "PARTIAL" and envelope["ok"] is True
    assert envelope["exec_rc"] is None
    assert envelope["errors"], "rc_parse_failed 未记入信封 errors"
    assert any("rc_parse_failed" in e for e in envelope["errors"])
    assert "rc 文件不可解析" in envelope["reason"]
    assert envelope["steps"]["wait"]["rc_parse_failed"] is True
    assert envelope["steps"]["fetch"]["files"] >= 1   # 产物照常回拉为证据


def test_poll_rc_file_unparseable_survival_early_same_semantics(
        monkeypatch, tmp_path):
    """F1 修复钉（短座位形态）：rc 文件在存活采样期即到但不可解析 →
    与 poll 环同语义 PARTIAL（两路信封传播统一，不分叉）。"""
    t = FakeTransport(None)
    t.launch_rc_text = "garbage-no-equals"   # split('=') 后 int() 仍失败
    envelope, _t2, _o = _run_sync(
        monkeypatch, tmp_path, transport=t, wait_mode="poll",
        sleep_fn=lambda _s: None,
    )
    assert envelope["verdict"] == "PARTIAL" and envelope["ok"] is True
    assert envelope["exec_rc"] is None
    assert envelope["steps"]["wait"]["survival"]["rc_early_seen"] is True
    assert envelope["steps"]["wait"]["rc_parse_failed"] is True
    assert "rc 文件不可解析" in envelope["reason"]


def test_poll_rc_parse_ok_still_pass(monkeypatch, tmp_path):
    """F1 回归钉：rc 文件可解析（rc=0）时 PASS 语义零变化。"""
    t = FakeTransport(None)
    t.launch_rc_text = "rc=0"
    envelope, _t2, _o = _run_sync(
        monkeypatch, tmp_path, transport=t, wait_mode="poll",
        sleep_fn=lambda _s: None,
    )
    assert envelope["verdict"] == "PASS" and envelope["exec_rc"] == 0
    assert envelope["errors"] == []
    assert envelope["steps"]["wait"]["rc_parse_failed"] is False


def test_resolve_machine_unknown_name_skip_envelope(monkeypatch):
    """F3 修复钉：机器名未登记 → fail-closed SKIP 信封（不再裸抛
    RemoteConfigError——与 remote_ads_service 同批同构，直连消费面不分叉）。"""
    monkeypatch.setenv(REMOTE_OE_ENV, "1")
    _one_machine(monkeypatch)          # 注册表只有 sim_host
    _set_creds(monkeypatch)

    def _boom(*a, **kw):
        raise AssertionError("机器解析失败时不得发起 SSH")

    monkeypatch.setattr(roe, "SshTransport", _boom)
    out = remote_oe_run("no_such_machine", _seat_spec())
    assert out["ok"] is False and out["skipped"] is True
    assert "机器解析失败" in out["reason"] and "no_such_machine" in out["reason"]


def test_resolve_machine_ambiguous_skip_envelope(monkeypatch):
    """F3 修复钉：注册表多台且未指名 → SKIP 信封（resolve_machine 的
    RemoteConfigError 同族收编）。"""
    from rfauto.infra.remote_machines import RemoteMachineConfig

    monkeypatch.setenv(REMOTE_OE_ENV, "1")
    cfgs = {
        f"m{i}": RemoteMachineConfig(
            name=f"m{i}", host="10.0.0.1", ssh_port=22,
            hfss_project_root=WORK_ROOT, probe_ports={},
        )
        for i in range(2)
    }
    monkeypatch.setattr(roe, "load_remote_machines", lambda: cfgs)
    _set_creds(monkeypatch)

    def _boom(*a, **kw):
        raise AssertionError("多机未指名时不得发起 SSH")

    monkeypatch.setattr(roe, "SshTransport", _boom)
    out = remote_oe_run(None, _seat_spec())
    assert out["ok"] is False and out["skipped"] is True
    assert "机器解析失败" in out["reason"]
