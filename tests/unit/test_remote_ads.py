"""多机协同 v1——service/remote_ads_service 单测（全离线，#139 通道 mock 钉死）。

覆盖：env 门拒绝（unit 门内必拒，零真机零连网）、自包含化检查两分支
（#276：绝对路径报错/相对依赖同传/缺依赖报错/越界拒绝）、执行 rc≠0 透
传、回拉缺产物报错、清理调用断言（任务毕必须清理）、远端命令形态钉
（G5 零双引号/G8 PS 原生/#272 env 形态）。SSH 通道全部 FakeTransport
（patch 在消费点 ras.SshTransport，P3-7 家法）。
"""

import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.service.remote_ads_service as ras
from rfauto.infra.remote_machines import (
    ENV_REMOTE_SSH_PASSWORD,
    ENV_REMOTE_SSH_USER,
)
from rfauto.service.remote_ads_service import (
    REMOTE_ADS_ENV,
    RemoteAdsError,
    remote_ads_run,
)

ADS_DIR = "E:\\ADS27\\ADS2027"
WORK_ROOT = "E:\\rfauto_remote"


def _one_machine(monkeypatch, **kw):
    from rfauto.infra.remote_machines import RemoteMachineConfig

    cfg = RemoteMachineConfig(
        name="sim_host", host="10.20.30.40", ssh_port=22,
        hfss_project_root=kw.pop("project_root", WORK_ROOT),
        ads_hpeesof_dir=kw.pop("ads_dir", ADS_DIR),
        probe_ports={"rdp": 3389},
        **kw,
    )
    monkeypatch.setattr(ras, "load_remote_machines", lambda: {"sim_host": cfg})
    return cfg


def _set_creds(monkeypatch):
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")


def _mock_probe(monkeypatch):
    monkeypatch.setattr(
        ras, "probe_machine",
        lambda cfg: {"name": cfg.name, "reachable": True, "ports": {}},
    )


def _write_netlist(tmp_path: Path, body: str, name: str = "smoke.sp") -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="ascii")
    return p


_SIMPLE_NETLIST = (
    "Port:P1  P1 0 Num=1 Z=50 Ohm Noise=yes\n"
    "Port:P2  P2 0 Num=2 Z=50 Ohm Noise=yes\n"
    "HB:HB1  HB1 \n"
)


class FakeTransport:
    """全通道 mock：记录命令/上传/下载，按命令前缀应答。

    New-Item 记录 workdir（供 Get-ChildItem 应答构造真实感远端路径）。
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.commands: list[str] = []
        self.uploads: list[tuple[str, str]] = []
        self.downloads: list[tuple[str, str]] = []
        self.workdir = WORK_ROOT + "\\ads_x"
        self.exec_rc = 0
        self.exec_stdout = "hpeesofsim done\n"
        self.exec_stderr = ""
        self.dataset_exists = "True"
        # 互斥预检（#261，X4 推广）：直查命中行/旁证探针输出
        self.mutex_hits: list[str] = []
        self.mutex_rc = 0
        self.probe_output = "mutex CLEAR\n"
        # 相对"被枚举目录"的文件清单（Get-ChildItem 按命令内路径应答）
        self.listing_rel = ["a.ds_data", "Master.ai_datadb"]
        self.fail_on = None  # 命令前缀→注入异常
        self.removed: set[str] = set()  # Remove-Item 成功的目录（小写）
        self.dirs: list[str] = []  # New-Item 记录（首个=批次根目录）

    def connect(self):
        if self.fail_on == "connect":
            raise ConnectionError("mock: connect refused")
        self.connected = True

    def run_command(self, cmd, timeout_s=60.0):
        self.commands.append(cmd)
        if self.fail_on and cmd.startswith(self.fail_on):
            raise RuntimeError("mock: command boom")
        if "-eq 'hpeesofsim.exe'" in cmd:                 # 互斥直查（权威）
            return self.mutex_rc, "".join(
                f"{h}\n" for h in self.mutex_hits), ""
        if "run_server_probe.ps1" in cmd:                 # 互斥旁证
            return 0, self.probe_output, ""
        if cmd.startswith("New-Item"):
            d = cmd.split("'")[1]
            if not self.dirs:
                self.workdir = d
            self.dirs.append(d)
            return 0, "", ""
        if cmd.startswith("Remove-Item"):
            self.removed.add(cmd.split("'")[1].lower())
            return 0, "", ""
        if cmd.startswith("Test-Path"):
            target = cmd.split("'")[1].lower()
            gone = any(
                target == r or target.startswith(r + "\\") for r in self.removed
            )
            if gone:
                return 0, "False\n", ""
            return 0, f"{self.dataset_exists}\n", ""
        if cmd.startswith("Get-ChildItem"):
            ds = cmd.split("'")[1]
            # "." 相对项=单文件数据集形态（枚举返回数据集路径自身）
            lines = [ds if rel == "." else f"{ds}\\{rel}" for rel in self.listing_rel]
            return 0, ("\n".join(lines) + "\n") if lines else "", ""
        if "hpeesofsim.exe" in cmd:
            return self.exec_rc, self.exec_stdout, self.exec_stderr
        return 0, "", ""  # 其他

    def upload_file(self, local, remote):
        self.uploads.append((str(local), remote))

    def download_file(self, remote, local):
        self.downloads.append((remote, str(local)))
        p = Path(local)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake-ds-bytes")

    def close(self):
        self.closed = True


# ─── env 门（真机 opt-in，unit 门内必拒） ──────────────────────────────────


def test_run_refuses_without_env_gate(monkeypatch):
    """真机远跑必须显式 opt-in：env 未设一律拒绝（零 SSH 尝试）。"""
    monkeypatch.delenv(REMOTE_ADS_ENV, raising=False)

    def _boom(*a, **kw):
        raise AssertionError("env 门未开时不得发起任何连接")

    monkeypatch.setattr(ras, "SshTransport", _boom)
    out = remote_ads_run("whatever.sp", "sim_host")
    assert out["ok"] is False and out["skipped"] is True
    assert "RFAUTO_REMOTE_SMOKE" in out["reason"]


def test_run_no_registered_machines(monkeypatch):
    monkeypatch.setenv(REMOTE_ADS_ENV, "1")
    monkeypatch.setattr(ras, "load_remote_machines", lambda: {})
    out = remote_ads_run("x.sp", None)
    assert out["skipped"] is True and "无登记机器" in out["reason"]


def test_resolve_machine_unknown_name_skip_envelope(monkeypatch):
    """F3 修复钉（ADS 通道同构）：机器名未登记 → fail-closed SKIP 信封
    （不再裸抛 RemoteConfigError；与 remote_oe_service 同批同构）。"""
    monkeypatch.setenv(REMOTE_ADS_ENV, "1")
    _one_machine(monkeypatch)          # 注册表只有 sim_host

    def _boom(*a, **kw):
        raise AssertionError("机器解析失败时不得发起 SSH")

    monkeypatch.setattr(ras, "SshTransport", _boom)
    out = remote_ads_run("x.sp", "no_such_machine")
    assert out["ok"] is False and out["skipped"] is True
    assert "机器解析失败" in out["reason"] and "no_such_machine" in out["reason"]


def test_run_missing_ads_dir_skips(monkeypatch):
    """未登记 ads.hpeesof_dir：fail-closed（服务器侧 env 构造必需）。"""
    monkeypatch.setenv(REMOTE_ADS_ENV, "1")
    _one_machine(monkeypatch, ads_dir="")
    _set_creds(monkeypatch)
    _mock_probe(monkeypatch)

    def _boom(*a, **kw):
        raise AssertionError("配置缺失时不得发起 SSH")

    monkeypatch.setattr(ras, "SshTransport", _boom)
    out = remote_ads_run("x.sp", "sim_host")
    assert out["skipped"] is True
    assert "ads.hpeesof_dir" in out["reason"]


def test_run_missing_project_root_skips(monkeypatch):
    monkeypatch.setenv(REMOTE_ADS_ENV, "1")
    _one_machine(monkeypatch, project_root="")
    _set_creds(monkeypatch)
    _mock_probe(monkeypatch)
    monkeypatch.setattr(ras, "SshTransport", FakeTransport)
    out = remote_ads_run("x.sp", "sim_host")
    assert out["skipped"] is True
    assert "project_root" in out["reason"]


def test_run_missing_credentials_no_ssh(monkeypatch):
    monkeypatch.setenv(REMOTE_ADS_ENV, "1")
    _one_machine(monkeypatch)
    monkeypatch.delenv(ENV_REMOTE_SSH_USER, raising=False)
    monkeypatch.delenv(ENV_REMOTE_SSH_PASSWORD, raising=False)
    _mock_probe(monkeypatch)

    def _boom(*a, **kw):
        raise AssertionError("凭据缺失时不得发起 SSH")

    monkeypatch.setattr(ras, "SshTransport", _boom)
    out = remote_ads_run("x.sp", "sim_host")
    assert out["skipped"] is True
    assert out["steps"]["ssh"]["auth"] == "missing_credentials"


def test_run_local_netlist_missing(monkeypatch, tmp_path):
    monkeypatch.setenv(REMOTE_ADS_ENV, "1")
    _one_machine(monkeypatch)
    _set_creds(monkeypatch)
    _mock_probe(monkeypatch)
    monkeypatch.setattr(ras, "SshTransport", FakeTransport)
    out = remote_ads_run(tmp_path / "nope.sp", "sim_host")
    assert out["ok"] is False
    assert "不存在" in out["reason"]


# ─── 自包含化检查（#276，纯函数两分支） ────────────────────────────────────


def test_plan_deps_relative_ok_with_subdir(tmp_path):
    dep = tmp_path / "dep.s2p"
    dep.write_text("# s2p\n", encoding="ascii")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "x.s3p").write_text("# s3p\n", encoding="ascii")
    net = _write_netlist(tmp_path, (
        'SnP:SNP1  P1 P2 NumPorts=2 File="dep.s2p" Type="touchstone"\n'
        'SnP:SNP2  P1 P2 P3 NumPorts=3 File="sub/x.s3p" Type="touchstone"\n'
    ))
    plan = ras._plan_netlist_dependencies(net)
    rels = sorted(d["remote_rel"] for d in plan)
    assert rels == ["dep.s2p", "sub/x.s3p"]


def test_plan_deps_dedup_same_ref(tmp_path):
    (tmp_path / "dep.s2p").write_text("# s2p\n", encoding="ascii")
    net = _write_netlist(tmp_path, (
        'SnP:SNP1 File="dep.s2p"\nSnP:SNP2 File="dep.s2p"\n'
    ))
    plan = ras._plan_netlist_dependencies(net)
    assert len(plan) == 1


def test_plan_deps_absolute_ref_rejected(tmp_path):
    """#276 主雷：File= 写死本机绝对路径 → 显式报错（不静默上传）。"""
    net = _write_netlist(tmp_path, (
        'SnP:SNP1 File="C:/Users/someuser\\AppData\\Local\\Temp\\x.s2p"\n'
    ))
    with pytest.raises(RemoteAdsError, match="绝对路径"):
        ras._plan_netlist_dependencies(net)


def test_plan_deps_unc_ref_rejected(tmp_path):
    net = _write_netlist(tmp_path, 'SnP:SNP1 File="\\\\server\\share\\x.s2p"\n')
    with pytest.raises(RemoteAdsError, match="绝对路径"):
        ras._plan_netlist_dependencies(net)


def test_plan_deps_missing_dep_rejected(tmp_path):
    """#276 变体：相对引用但依赖本地缺失 → 显式报错。"""
    net = _write_netlist(tmp_path, 'SnP:SNP1 File="ghost.s2p"\n')
    with pytest.raises(RemoteAdsError, match="本地缺失"):
        ras._plan_netlist_dependencies(net)


def test_plan_deps_traversal_rejected(tmp_path):
    net = _write_netlist(tmp_path, 'SnP:SNP1 File="..\\x.s2p"\n')
    with pytest.raises(RemoteAdsError, match="越界"):
        ras._plan_netlist_dependencies(net)


def test_plan_deps_no_file_ref_selfcontained(tmp_path):
    net = _write_netlist(tmp_path, _SIMPLE_NETLIST)
    assert ras._plan_netlist_dependencies(net) == []


# ─── 远端命令形态钉（G5 零双引号 / G8 PS 原生 / #272 env 形态） ────────────


def test_exec_command_shape():
    cmd = ras._build_hpeesofsim_command(ADS_DIR, WORK_ROOT + "\\ads_x", "hpeesofsim.exe", "smoke.sp")
    assert "HPEESOF_DIR='E:\\ADS27\\ADS2027'" in cmd
    # #272 PATH 前置三件：bin + adsptolemy/lib.win32_64 + tools/python
    assert (
        "PATH='E:\\ADS27\\ADS2027\\bin;"
        "E:\\ADS27\\ADS2027\\adsptolemy\\lib.win32_64;"
        "E:\\ADS27\\ADS2027\\tools\\python;' + $env:PATH" in cmd
    )
    assert "Set-Location -LiteralPath 'E:\\rfauto_remote\\ads_x'" in cmd
    assert "& 'E:\\ADS27\\ADS2027\\bin\\hpeesofsim.exe' 'smoke.sp'" in cmd
    # rc 透传（PS 会话对原生 exe 恒 0 的对策；$null 守卫防 exe 启动失败残留）
    assert "exit $rc" in cmd and "$LASTEXITCODE" in cmd
    # G5：零双引号；G7/G8：不走 cmd /c && 链
    assert '"' not in cmd
    assert "cmd /c" not in cmd and "&&" not in cmd


def test_check_remote_safe_rejects_quotes_and_spaces():
    with pytest.raises(RemoteAdsError):
        ras._check_remote_safe("x", "E:\\some dir")
    with pytest.raises(RemoteAdsError):
        ras._check_remote_safe("x", "E:\\it's")
    assert ras._check_remote_safe("x", "E:/a/b") == "E:\\a\\b"


# ─── 全通道编排（mock） ────────────────────────────────────────────────────


def _run_happy(monkeypatch, tmp_path, transport=None, **kw):
    monkeypatch.setenv(REMOTE_ADS_ENV, "1")
    _one_machine(monkeypatch, **kw.pop("machine_kw", {}))
    _set_creds(monkeypatch)
    _mock_probe(monkeypatch)
    t = transport or FakeTransport(None)
    monkeypatch.setattr(ras, "SshTransport", lambda cfg: t)
    net = _write_netlist(tmp_path, _SIMPLE_NETLIST)
    out_dir = tmp_path / "pull"
    envelope = remote_ads_run(
        net, "sim_host", out_dir=out_dir,
        **kw,
    )
    return envelope, t, net, out_dir


def test_full_channel_happy_path(monkeypatch, tmp_path):
    envelope, t, _n, _o = _run_happy(monkeypatch, tmp_path)
    assert envelope["ok"] is True and envelope["verdict"] == "PASS"
    assert envelope["exec_rc"] == 0
    c = envelope["criteria"]
    assert c["c1_rc0"] and c["c2_dataset_nonempty"] and c["c3_workdir_cleaned"]
    # 上传：网表落批次目录（sftp 面 / 分隔）
    uploaded = {r for _l, r in t.uploads}
    assert uploaded == {t.workdir.replace("\\", "/") + "/smoke.sp"}
    assert t.workdir.startswith(WORK_ROOT + "\\ads_")
    # 回拉：两条远端文件 → 本地镜像 <网表全名>.ds/（hpeesofsim 以网表
    # 文件名含扩展名命名数据集，真机首跑实证 <stem>.ds 推导假阴性）
    assert len(t.downloads) == 2
    ds_local = Path(envelope["dataset_local"])
    assert ds_local.name == "smoke.sp.ds"
    assert (ds_local / "a.ds_data").is_file()
    assert (ds_local / "Master.ai_datadb").is_file()
    # 服务器命令面：建目录/执行/存在性/枚举/清理全在档
    joined = "\n".join(t.commands)
    assert joined.count("New-Item -ItemType Directory -Force") >= 1
    assert any(c.startswith("Test-Path -LiteralPath") for c in t.commands)
    assert any(c.startswith("Get-ChildItem -LiteralPath") for c in t.commands)
    remove_cmds = [c for c in t.commands if c.startswith("Remove-Item")]
    assert len(remove_cmds) == 1  # 任务毕必须清理
    assert remove_cmds[0].startswith(
        f"Remove-Item -LiteralPath '{envelope['work_dir_remote']}'"
    )
    # steps 逐步落账
    steps = envelope["steps"]
    for key in ("probe", "ssh", "mutex", "upload", "exec", "fetch", "cleanup"):
        assert key in steps, key
    assert steps["upload"]["n_files"] == 1
    assert steps["exec"]["rc"] == 0
    assert steps["fetch"]["files"] == 2
    assert steps["cleanup"]["verified_gone"] is True
    # 互斥预检（#261，X4 推广）：CLEAR → 发射放行 + c0 落账
    assert envelope["criteria"]["c0_mutex_clear"] is True
    assert steps["mutex"]["busy"] is False
    # 互斥直查命令形态（进程域钉 hpeesofsim.exe；G5 零双引号）
    mutex_cmds = [c for c in t.commands if "-eq 'hpeesofsim.exe'" in c]
    assert len(mutex_cmds) == 1
    assert '"' not in mutex_cmds[0]
    assert "hpeesofsim" in mutex_cmds[0]


def test_batch_dir_unique_per_call(monkeypatch, tmp_path):
    """批次目录唯一化（uuid8）：并发批次不互踩；显式 batch_name 尊重。"""
    e1, _t1, _n, _o = _run_happy(monkeypatch, tmp_path)
    e2, _t2, _n, _o = _run_happy(monkeypatch, tmp_path)
    assert e1["work_dir_remote"] != e2["work_dir_remote"]
    assert e1["batch"].startswith("ads_") and e2["batch"].startswith("ads_")
    e3, _t3, _n, _o = _run_happy(
        monkeypatch, tmp_path, batch_name="mybatch1",
    )
    assert e3["work_dir_remote"] == f"{WORK_ROOT}\\mybatch1"


def test_batch_name_invalid_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv(REMOTE_ADS_ENV, "1")
    _one_machine(monkeypatch)
    _set_creds(monkeypatch)
    _mock_probe(monkeypatch)
    monkeypatch.setattr(ras, "SshTransport", FakeTransport)
    net = _write_netlist(tmp_path, _SIMPLE_NETLIST)
    out = remote_ads_run(net, "sim_host", batch_name="a b/c")
    assert out["ok"] is False
    assert "batch_name" in out["reason"]


def test_dependency_courier_uploaded(monkeypatch, tmp_path):
    """#276 正分支：相对依赖自动同传（含子目录 New-Item）。"""
    (tmp_path / "dep.s2p").write_text("# s2p\n", encoding="ascii")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "x.s3p").write_text("# s3p\n", encoding="ascii")
    net = _write_netlist(tmp_path, (
        'SnP:SNP1 File="dep.s2p"\nSnP:SNP2 File="sub/x.s3p"\n'
    ))
    monkeypatch.setenv(REMOTE_ADS_ENV, "1")
    _one_machine(monkeypatch)
    _set_creds(monkeypatch)
    _mock_probe(monkeypatch)
    t = FakeTransport(None)
    monkeypatch.setattr(ras, "SshTransport", lambda cfg: t)
    envelope = remote_ads_run(net, "sim_host", out_dir=tmp_path / "pull")
    assert envelope["ok"] is True
    uploaded = {Path(local).name: remote for local, remote in t.uploads}
    assert uploaded["dep.s2p"].endswith("/dep.s2p")
    assert uploaded["x.s3p"].endswith("/sub/x.s3p")
    assert any("'E:\\rfauto_remote\\ads_" in c and "sub'" in c
               for c in t.commands)  # 子目录预建
    assert envelope["steps"]["upload"]["n_files"] == 3  # 2 依赖 + 网表


def test_dependency_absolute_envelope_failclosed(monkeypatch, tmp_path):
    """#276：绝对路径依赖 → fail-closed 信封，零 SSH 上传。"""
    net = _write_netlist(tmp_path, 'SnP:SNP1 File="C:\\tmp\\x.s2p"\n')
    monkeypatch.setenv(REMOTE_ADS_ENV, "1")
    _one_machine(monkeypatch)
    _set_creds(monkeypatch)
    _mock_probe(monkeypatch)

    def _boom(*a, **kw):
        raise AssertionError("自包含化失败时不得发起 SSH")

    monkeypatch.setattr(ras, "SshTransport", _boom)
    out = remote_ads_run(net, "sim_host")
    assert out["ok"] is False
    assert "绝对路径" in out["reason"] and "#276" in out["reason"]


def test_exec_rc_nonzero_passthrough(monkeypatch, tmp_path):
    """执行 rc≠0 透传：信封 exec_rc=3 + fetch 不走 + 清理仍执行。"""
    t = FakeTransport(None)
    t.exec_rc = 3
    t.exec_stdout = "ERROR: syntax\n"
    envelope, t2, _n, _o = _run_happy(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is False and envelope["verdict"] == "FAIL"
    assert envelope["exec_rc"] == 3
    assert "rc=3" in envelope["reason"]
    assert envelope["steps"]["exec"]["rc"] == 3
    assert envelope["steps"]["exec"]["stdout_tail"].startswith("ERROR")
    assert envelope["steps"].get("fetch") is None                # 未到回拉
    assert any(c.startswith("Remove-Item") for c in t2.commands)   # 清理仍走
    assert envelope["criteria"]["c3_workdir_cleaned"] is True


def test_fetch_missing_dataset_failclosed(monkeypatch, tmp_path):
    """缺产物报错：Test-Path=False → fail-closed + 清理仍执行。"""
    t = FakeTransport(None)
    t.dataset_exists = "False"
    envelope, t2, _n, _o = _run_happy(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is False
    assert "数据集未落盘" in envelope["reason"]
    assert not t2.downloads  # 无产物可回拉
    assert any(c.startswith("Remove-Item") for c in t2.commands)
    assert envelope["criteria"]["c3_workdir_cleaned"] is True


def test_fetch_empty_enumeration_failclosed(monkeypatch, tmp_path):
    """数据集在档但零文件 → fail-closed（枚举空不是成功）。"""
    t = FakeTransport(None)
    t.listing_rel = []
    envelope, _t2, _n, _o = _run_happy(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is False
    assert "枚举为空" in envelope["reason"]


def test_cleanup_failure_flips_verdict(monkeypatch, tmp_path):
    """清理失败翻 FAIL（任务毕必须清理， 0b）——不静默放行。"""
    t = FakeTransport(None)

    real_run = t.run_command

    def run_with_failed_remove(cmd, timeout_s=60.0):
        if cmd.startswith("Remove-Item"):
            return 1, "in use\n", ""
        return real_run(cmd, timeout_s)

    t.run_command = run_with_failed_remove
    envelope, _t2, _n, _o = _run_happy(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is False and envelope["verdict"] == "FAIL"
    assert "清理" in envelope["reason"]
    assert envelope["criteria"]["c1_rc0"] is True  # 求解本身成功仍如实
    assert envelope["criteria"]["c3_workdir_cleaned"] is False


def test_keep_remote_skips_cleanup_honestly(monkeypatch, tmp_path):
    t = FakeTransport(None)
    envelope, t2, _n, _o = _run_happy(
        monkeypatch, tmp_path, transport=t, keep_remote=True,
    )
    assert envelope["ok"] is True
    assert not any(c.startswith("Remove-Item") for c in t2.commands)
    assert envelope["steps"]["cleanup"]["skipped"] is True
    assert "人工清理" in envelope["steps"]["cleanup"]["reason"]


def test_link_bare_exception_failclosed(monkeypatch, tmp_path):
    """链路裸抛（connect 后命令炸）→ fail-closed 信封（L2 同构）。"""
    t = FakeTransport(None)
    t.fail_on = "New-Item"  # run_command 内抛
    envelope, _t2, _n, _o = _run_happy(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is False
    assert "链路异常" in envelope["reason"] and "RuntimeError" in envelope["reason"]


# ─── 互斥预检（#261 每机互斥，X4 批推广；OE 通道同构三态） ─────────────────


def test_mutex_busy_skips_without_upload(monkeypatch, tmp_path):
    """互斥命中=候跑 SKIP：不上传不建目录不发射，零代杀命令。"""
    t = FakeTransport(None)
    t.mutex_hits = [
        "900|E:\\ADS27\\ADS2027\\bin\\hpeesofsim.exe cascade.sp"
    ]
    envelope, t2, _n, _o = _run_happy(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is False and envelope["skipped"] is True
    assert "候跑" in envelope["reason"] and "禁止代杀" in envelope["reason"]
    assert envelope["criteria"]["c0_mutex_clear"] is False
    assert envelope["steps"]["mutex"]["busy"] is True
    assert not t2.uploads                            # 未上传=未发射
    assert not any(c.startswith("New-Item") for c in t2.commands)
    assert not any("& '" in c for c in t2.commands)   # 引擎未发射
    # 清理复核仍走（finally）：无目录=verified_gone，无残留
    assert envelope["steps"]["cleanup"]["verified_gone"] is True
    assert not any("taskkill" in c or "Stop-Process" in c
                   for c in t2.commands)             # 全模块零杀进程命令


def test_mutex_probe_busy_is_also_busy(monkeypatch, tmp_path):
    """旁证非 CLEAR（直查零命中）同样候跑——宁枉勿纵，绝不抢席位。"""
    t = FakeTransport(None)
    t.probe_output = "mutex BUSY x2\n"
    envelope, _t2, _n, _o = _run_happy(monkeypatch, tmp_path, transport=t)
    assert envelope["skipped"] is True and "候跑" in envelope["reason"]


def test_mutex_probe_census_header_not_false_busy(monkeypatch, tmp_path):
    """回归钉（OE 2026-10-01 同款）：census 表头行不得判假忙堵门。"""
    t = FakeTransport(None)
    t.probe_output = (
        "=== [6] current solver-process census (#261 mutex precheck) ===\n"
        "mutex CLEAR\n")
    envelope, _t2, _n, _o = _run_happy(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is True and envelope["verdict"] == "PASS"
    assert envelope["criteria"]["c0_mutex_clear"] is True


def test_mutex_query_fail_failclosed(monkeypatch, tmp_path):
    """直查 rc≠0（验不了）→ fail-closed 不发射，不冒充互斥 CLEAR。"""
    t = FakeTransport(None)
    t.mutex_rc = 2
    envelope, t2, _n, _o = _run_happy(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is False and envelope["skipped"] is True
    assert "fail-closed" in envelope["reason"]
    assert envelope["steps"]["mutex"]["fail_closed"] is True
    assert not any(c.startswith("New-Item") for c in t2.commands)
    assert envelope["criteria"]["c0_mutex_clear"] is False


def test_dataset_stem_override(monkeypatch, tmp_path):
    """网表内显式 DATASET_EXPORT 指名时经 dataset_stem 覆盖。"""
    t = FakeTransport(None)
    t.listing_rel = ["a.ds_data"]
    envelope, _t2, _n, _o = _run_happy(
        monkeypatch, tmp_path, transport=t, dataset_stem="hb_run",
    )
    assert envelope["ok"] is True
    assert envelope["dataset_remote"].endswith("hb_run.ds")
    assert Path(envelope["dataset_local"]).name == "hb_run.ds"


def test_dataset_single_file_form(monkeypatch, tmp_path):
    """hpeesofsim 单文件数据集形态：枚举返回 .ds 路径自身（非目录子项）
    ——真机首跑实证形态，守卫须放行等值条目并整编回拉为单文件。"""
    t = FakeTransport(None)
    t.listing_rel = ["."]
    envelope, _t2, _n, _out_dir = _run_happy(monkeypatch, tmp_path, transport=t)
    assert envelope["ok"] is True and envelope["verdict"] == "PASS"
    fetch = envelope["steps"]["fetch"]
    assert fetch["form"] == "single_file"
    assert fetch["files"] == 1
    ds_local = Path(envelope["dataset_local"])
    assert ds_local.name == "smoke.sp.ds"
    assert ds_local.is_file()
    # 下载走数据集路径自身（sftp 面 / 分隔），不拼子路径
    assert t.downloads[0][0].endswith("smoke.sp.ds")
    assert t.downloads[0][0].startswith(t.workdir.replace("\\", "/"))
