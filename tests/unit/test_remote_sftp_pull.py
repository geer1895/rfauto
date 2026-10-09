"""remote_sftp_pull 单测——L2 sftp 回拉执行体（全 fake 零真连，#139）。

覆盖：正常回拉（清单/字节/逐文件账目）、白名单过滤、远端缺文件如实跳过、
校验失败重试一次后如实失败（大小/sha256 两形态）、本地同名冲突跳过不覆盖、
枚举 fail-closed（rc≠0/清单行解析失败/路径越界/单引号 G5）、凭据与登记
前置守卫、transport 生命周期、resolve_pull_out_dir 双根收敛、清单构造器
自动回填。服务器 sim_host 不可用期全程 mock/本地形态验证，禁止真连。
"""

import fnmatch
import hashlib
import json
import sys
from pathlib import Path

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.service.remote_sftp_pull as rsp
from rfauto.infra.remote_machines import (
    RemoteMachineConfig,
    RemoteTransportError,
)
from rfauto.service.remote_sftp_pull import (
    L2_PRODUCT_PATTERNS,
    PULL_MANIFEST_NAME,
    pull_artifacts,
    record_pull_manifest,
    resolve_pull_out_dir,
)

_REMOTE_ROOT = "E:/rfauto_remote/l2_smoke"   # 正斜杠 sftp 口径（服务器 E 盘根）
_F1 = f"{_REMOTE_ROOT}/l2_smoke.s2p"
_F2 = f"{_REMOTE_ROOT}/sub/ports.csv"
_F3 = f"{_REMOTE_ROOT}/aedt_console.log"


class FakeSftpTransport:
    """假 sftp 通道：记录调用序列；枚举/Test-Path/哈希/下载行为可编程。"""

    def __init__(self, *, listing: str = "", listing_rc: int = 0,
                 files: dict[str, bytes] | None = None,
                 test_path: dict[str, bool] | None = None,
                 remote_hashes: dict[str, str] | None = None,
                 download_effects: dict[str, list] | None = None):
        self.commands: list[str] = []
        self.downloads: list[tuple[str, str]] = []
        self.connected = False
        self.closed = False
        self.listing = listing
        self.listing_rc = listing_rc
        self.files = files or {}
        self.test_path = test_path or {}
        self.remote_hashes = remote_hashes or {}
        self.download_effects = download_effects or {}
        self._dl_counts: dict[str, int] = {}

    def connect(self):
        self.connected = True

    def run_command(self, cmd, timeout_s=60.0):
        self.commands.append(cmd)
        if cmd.startswith("Get-ChildItem"):
            return self.listing_rc, self.listing, ""
        if cmd.startswith("Test-Path"):
            for key, val in self.test_path.items():
                if key.replace("/", "\\") in cmd:
                    return 0, ("True\n" if val else "False\n"), ""
            return 0, "False\n", ""
        if cmd.startswith("(Get-FileHash"):
            for key, val in self.remote_hashes.items():
                if key.replace("/", "\\") in cmd:
                    return 0, val + "\n", ""
            return 1, "", "no hash"
        return 0, "", ""

    def download_file(self, remote, local):
        self.downloads.append((remote, str(local)))
        n = self._dl_counts.get(remote, 0)
        self._dl_counts[remote] = n + 1
        effects = self.download_effects.get(remote)
        if effects:
            action = effects[min(n, len(effects) - 1)]
            if isinstance(action, Exception):
                raise action
            payload = action
        else:
            payload = self.files.get(remote)
        if payload is None:
            raise FileNotFoundError(remote)
        p = Path(local)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(payload)

    def close(self):
        self.closed = True


def _listing(*pairs: tuple[str, int]) -> str:
    win_root = _REMOTE_ROOT.replace("/", "\\")
    return "".join(
        f"{win_root}\\{rel}|{size}\n" for rel, size in pairs
    )


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ─── 正常回拉 ─────────────────────────────────────────────────────────────


def test_pull_normal_flow(tmp_path):
    """正常回拉：两文件全拉、逐文件账目、清单 JSON 落盘、通道不代关。"""
    body1, body2 = b"s2p-payload-41pts", b"freq,port"
    t = FakeSftpTransport(
        listing=_listing(("l2_smoke.s2p", len(body1)),
                         ("sub\\ports.csv", len(body2))),
        files={_F1: body1, _F2: body2},
    )
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", transport=t)
    assert out["ok"] is True and out["verdict"] == "PASS"
    assert out["counts"] == {"pulled": 2, "skipped_exists": 0,
                             "missing_remote": 0, "filtered": 0,
                             "failed": 0}
    # 下载调用序列（远端路径按正斜杠 sftp 口径）
    assert [d[0] for d in t.downloads] == [_F1, _F2]
    # 本地落位镜像子目录 + 内容逐字节一致
    local1 = Path(out["files"][0]["local"])
    local2 = Path(out["files"][1]["local"])
    assert local1 == tmp_path / "pull" / "l2_smoke.s2p"
    assert local2 == tmp_path / "pull" / "sub" / "ports.csv"
    assert local1.read_bytes() == body1 and local2.read_bytes() == body2
    # 逐文件账目：bytes + sha256
    assert out["files"][0]["bytes"] == len(body1)
    assert out["files"][0]["sha256"] == _sha(body1)
    assert out["files"][0]["attempts"] == 1
    # 注入通道=调用方所有：不代 close
    assert t.closed is False and t.connected is False
    # 回拉清单 JSON
    mpath = Path(out["manifest_path"])
    assert mpath == tmp_path / "pull" / PULL_MANIFEST_NAME
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    assert manifest["schema"] == rsp.MANIFEST_SCHEMA
    assert manifest["remote_dir"] == _REMOTE_ROOT
    assert manifest["machine"] == "sim_host"
    assert len(manifest["files"]) == 2
    row = manifest["files"][0]
    assert row["remote"] == _F1 and row["status"] == "pulled"
    assert row["bytes"] == len(body1) and row["sha256"] == _sha(body1)


def test_pull_lifecycle_self_built_transport(tmp_path, monkeypatch):
    """transport=None：自建通道走 connect/close 全生命周期（凭据在档）。"""
    body = b"lifecycle"
    fake = FakeSftpTransport(
        listing=_listing(("l2_smoke.s2p", len(body))), files={_F1: body})
    cfg = RemoteMachineConfig(
        name="sim_host", host="192.0.2.50", ssh_port=22,
        ssh_user="testuser", ssh_password="fake-pass",
        hfss_project_root="E:\\rfauto_remote")
    monkeypatch.setattr(rsp, "load_remote_machines", lambda: {"sim_host": cfg})
    monkeypatch.setattr(rsp, "SshTransport", lambda c: fake)
    out = pull_artifacts(None, remote_dir=_REMOTE_ROOT,
                         out_dir=tmp_path / "pull")
    assert out["ok"] is True and out["verdict"] == "PASS"
    assert fake.connected is True and fake.closed is True
    assert out["machine"] == "sim_host"


# ─── 白名单过滤 ───────────────────────────────────────────────────────────


def test_whitelist_filters_non_matching(tmp_path):
    """白名单：未命中文件=filtered 如实落账，不发起下载。"""
    body = b"only-touchstone"
    t = FakeSftpTransport(
        listing=_listing(("l2_smoke.s2p", len(body)), ("big.aedt", 999),
                         ("dump.bin", 3)),
        files={_F1: body},
    )
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", include_patterns=("*.s2p",),
        transport=t)
    assert out["ok"] is True and out["verdict"] == "PASS"
    assert out["counts"]["pulled"] == 1 and out["counts"]["filtered"] == 2
    assert [d[0] for d in t.downloads] == [_F1]
    statuses = {f["remote"]: f["status"] for f in out["files"]}
    assert statuses[_F1] == "pulled"
    assert statuses[f"{_REMOTE_ROOT}/big.aedt"] == "filtered"
    assert statuses[f"{_REMOTE_ROOT}/dump.bin"] == "filtered"


def test_l2_product_patterns_constant():
    """L2 产物建议白名单常量：Touchstone/判读 CSV/清单/日志在列，工程档不在。"""
    assert fnmatch.fnmatch("l2_smoke.s2p", L2_PRODUCT_PATTERNS[0])
    assert any(fnmatch.fnmatch("ports.csv", p) for p in L2_PRODUCT_PATTERNS)
    assert any(fnmatch.fnmatch("pull_manifest.json", p)
               for p in L2_PRODUCT_PATTERNS)
    assert not any(fnmatch.fnmatch("proj.aedt", p) for p in L2_PRODUCT_PATTERNS)


# ─── 远端缺文件（显式清单模式） ────────────────────────────────────────────


def test_missing_remote_skips_with_warning(tmp_path):
    """显式清单：远端缺文件=missing_remote 跳过+告警，零下载，verdict FAIL。"""
    t = FakeSftpTransport(test_path={_F1: False})
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", remote_files=[_F1], transport=t)
    assert out["ok"] is False and out["verdict"] == "FAIL"
    assert t.downloads == []
    assert out["counts"]["missing_remote"] == 1
    assert any("缺文件" in w for w in out["warnings"])
    assert out["files"][0]["status"] == "missing_remote"
    # 清单照写（记账产物，fail 时同样落盘）
    manifest = json.loads(Path(out["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["files"][0]["status"] == "missing_remote"


def test_explicit_list_pull_flat(tmp_path):
    """显式清单在位：扁平落位到 out_dir 根（无子目录镜像）。"""
    body = b"explicit"
    t = FakeSftpTransport(test_path={_F1: True}, files={_F1: body})
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", remote_files=[_F1], transport=t)
    assert out["ok"] is True and out["verdict"] == "PASS"
    assert Path(out["files"][0]["local"]) == tmp_path / "pull" / "l2_smoke.s2p"
    assert Path(out["files"][0]["local"]).read_bytes() == body


# ─── 完整性校验（大小/sha256，失败重试一次） ───────────────────────────────


def test_size_mismatch_retry_once_then_fail(tmp_path):
    """大小校验失败：重试一次（共 2 次下载）仍不过=如实 failed；半截产物清理。"""
    body = b"x" * 40                       # 实际 40B，声明 100B
    t = FakeSftpTransport(
        listing=_listing(("l2_smoke.s2p", 100)),
        files={_F1: body},
    )
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", transport=t)
    assert out["ok"] is False and out["verdict"] == "FAIL"
    assert t._dl_counts[_F1] == 2          # 恰好重试一次
    row = out["files"][0]
    assert row["status"] == "failed" and row["attempts"] == 2
    assert "size_mismatch" in row["error"]
    assert out["counts"]["failed"] == 1
    assert any("size_mismatch" in e for e in out["errors"])
    # 失败路径不留半截文件
    assert not (tmp_path / "pull" / "l2_smoke.s2p").exists()
    manifest = json.loads(Path(out["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["counts"]["failed"] == 1


def test_retry_second_attempt_success(tmp_path):
    """首拉损坏、重拉完好 → pulled（attempts=2），最终信封 PASS。"""
    good = b"good-payload" * 3
    t = FakeSftpTransport(
        listing=_listing(("l2_smoke.s2p", len(good))),
        download_effects={_F1: [b"truncated", good]},
    )
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", transport=t)
    assert out["ok"] is True and out["verdict"] == "PASS"
    assert t._dl_counts[_F1] == 2
    row = out["files"][0]
    assert row["status"] == "pulled" and row["attempts"] == 2
    assert Path(row["local"]).read_bytes() == good


def test_sha256_mismatch_retry_once_then_fail(tmp_path):
    """sha256 校验（verify_sha256=True）：远端哈希对不上→重试一次→如实失败。"""
    body = b"payload-with-wrong-remote-hash"
    bad_hash = "0" * 64
    t = FakeSftpTransport(
        listing=_listing(("l2_smoke.s2p", len(body))),
        files={_F1: body},
        remote_hashes={_F1: bad_hash.upper()},   # Get-FileHash 大写口径
    )
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", verify_sha256=True, transport=t)
    assert out["ok"] is False and out["verdict"] == "FAIL"
    assert t._dl_counts[_F1] == 2
    row = out["files"][0]
    assert row["status"] == "failed" and "sha256_mismatch" in row["error"]
    # 大写远端哈希与小写本地哈希比较口径正确（非大小写伪差异）
    assert out["files"][0]["error"] is not None


def test_sha256_verify_pass(tmp_path):
    """sha256 校验通过：远端哈希（大写）==本地流式 sha256（小写）→ pulled。"""
    body = b"verified-payload"
    t = FakeSftpTransport(
        listing=_listing(("l2_smoke.s2p", len(body))),
        files={_F1: body},
        remote_hashes={_F1: _sha(body).upper()},
    )
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", verify_sha256=True, transport=t)
    assert out["ok"] is True and out["verdict"] == "PASS"
    assert out["files"][0]["sha256"] == _sha(body)
    assert any(c.startswith("(Get-FileHash") for c in t.commands)


def test_sha256_unavailable_fail_closed(tmp_path):
    """远端 Get-FileHash 非零退出：验不了=重试一次后如实 failed（不静默放行）。"""
    body = b"no-hash-available"
    t = FakeSftpTransport(
        listing=_listing(("l2_smoke.s2p", len(body))),
        files={_F1: body},
        remote_hashes={},                      # 哈希查询走 rc=1 分支
    )
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", verify_sha256=True, transport=t)
    assert out["ok"] is False and out["verdict"] == "FAIL"
    assert "remote_hash_unavailable" in out["files"][0]["error"]


# ─── 本地落位冲突 ─────────────────────────────────────────────────────────


def test_local_conflict_skips_without_overwrite(tmp_path):
    """本地同名冲突：跳过+告警，不覆盖、不下载，原内容逐字节不变。"""
    local = tmp_path / "pull" / "l2_smoke.s2p"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"LOCAL-GUARD-CONTENT")
    body = b"remote-newer-content"
    t = FakeSftpTransport(
        listing=_listing(("l2_smoke.s2p", len(body))), files={_F1: body})
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", transport=t)
    assert out["verdict"] == "PASS" and out["ok"] is True
    assert out["counts"]["skipped_exists"] == 1
    assert t.downloads == []               # 冲突文件零下载
    assert local.read_bytes() == b"LOCAL-GUARD-CONTENT"   # 不覆盖
    assert any("跳过不覆盖" in w for w in out["warnings"])
    assert out["files"][0]["status"] == "skipped_exists"


# ─── 枚举 fail-closed（G5/解析/越界） ──────────────────────────────────────


def test_enumeration_rc_nonzero_fail_closed(tmp_path):
    """枚举 rc≠0：显式报错不冒充空产物，不写清单。"""
    t = FakeSftpTransport(listing_rc=1)
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", transport=t)
    assert out["ok"] is False
    assert any("枚举失败" in e for e in out["errors"])
    assert not (tmp_path / "pull" / PULL_MANIFEST_NAME).exists()


def test_malformed_listing_line_fail_closed(tmp_path):
    """清单行非 path|size 形态：如实报解析失败（#331 观察面失真防线）。"""
    t = FakeSftpTransport(listing="garbage-line-without-protocol\n")
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", transport=t)
    assert out["ok"] is False
    assert any("解析失败" in e for e in out["errors"])


def test_out_of_prefix_listing_rejected(tmp_path):
    """清单路径越出产物目录：fail-closed 拒绝（防误拉他目录）。"""
    evil = "E:/elsewhere/secret.s2p"
    t = FakeSftpTransport(
        listing=_listing(("l2_smoke.s2p", 5))
        + evil.replace("/", "\\") + "|5\n")
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", transport=t)
    assert out["ok"] is False
    assert any("越出产物目录" in e for e in out["errors"])


def test_listing_dotdot_relative_segment_rejected(tmp_path):
    """相对段含 ``..``：字符串上仍以根为前缀（前缀检查的逃逸面）——
    fail-closed 拒绝，本地零落位（防 out_dir 镜像根被落位越界）。"""
    evil = f"{_REMOTE_ROOT}\\..\\..\\escape.txt|5"
    t = FakeSftpTransport(
        listing=_listing(("l2_smoke.s2p", 5)) + evil + "\n",
        files={f"{_REMOTE_ROOT}/../../escape.txt": b"evil"})
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull", transport=t)
    assert out["ok"] is False
    assert any(".." in e for e in out["errors"])
    assert not (tmp_path / "pull" / "escape.txt").exists()
    assert list((tmp_path / "pull").rglob("escape.txt")) == []


def test_remote_dir_single_quote_rejected(tmp_path):
    """G5：remote_dir 含单引号=验证期拒绝，零命令下发。"""
    t = FakeSftpTransport()
    out = pull_artifacts(
        "sim_host", remote_dir="E:/rfauto'remote",
        out_dir=tmp_path / "pull", transport=t)
    assert out["ok"] is False
    assert t.commands == []
    assert any("单引号" in e for e in out["errors"])


# ─── 前置守卫（登记/凭据/机器名） ──────────────────────────────────────────


def test_no_registry_skipped(tmp_path, monkeypatch):
    """零登记：skipped 信封（ok=False，L2 前置段同形），零通道构造。"""
    monkeypatch.setattr(rsp, "load_remote_machines", lambda: {})

    def _boom(*a, **kw):
        raise AssertionError("无登记机器时不得构造通道")

    monkeypatch.setattr(rsp, "SshTransport", _boom)
    out = pull_artifacts(None, remote_dir=_REMOTE_ROOT,
                         out_dir=tmp_path / "pull")
    assert out["ok"] is False and out["skipped"] is True
    assert "无登记机器" in out["reason"]


def test_missing_credentials_skipped_no_connect(tmp_path, monkeypatch):
    """凭据缺失：如实 skipped，不构造通道不发起连接。"""
    cfg = RemoteMachineConfig(
        name="sim_host", host="192.0.2.50", ssh_port=22,
        hfss_project_root="E:\\rfauto_remote")
    monkeypatch.setattr(rsp, "load_remote_machines", lambda: {"sim_host": cfg})
    monkeypatch.delenv(rsp.ENV_REMOTE_SSH_USER, raising=False)
    monkeypatch.delenv(rsp.ENV_REMOTE_SSH_PASSWORD, raising=False)

    def _boom(*a, **kw):
        raise AssertionError("凭据缺失时不得构造通道")

    monkeypatch.setattr(rsp, "SshTransport", _boom)
    out = pull_artifacts(None, remote_dir=_REMOTE_ROOT,
                         out_dir=tmp_path / "pull")
    assert out["ok"] is False and out["skipped"] is True
    assert out["steps"]["ssh"]["auth"] == "missing_credentials"


def test_unknown_machine_error_envelope(tmp_path, monkeypatch):
    """未登记机器名：error 信封（resolve_machine 报错转信封，不裸抛）。"""
    cfg = RemoteMachineConfig(
        name="sim_host", host="192.0.2.50", ssh_port=22,
        ssh_user="u", ssh_password="p")
    monkeypatch.setattr(rsp, "load_remote_machines", lambda: {"sim_host": cfg})
    out = pull_artifacts("nope", remote_dir=_REMOTE_ROOT,
                         out_dir=tmp_path / "pull")
    assert out["ok"] is False
    assert any("nope" in e for e in out["errors"])


def test_paramiko_missing_becomes_error_envelope(tmp_path, monkeypatch):
    """paramiko 缺装（SshTransport 构造抛 RemoteTransportError）→ error 信封。"""
    cfg = RemoteMachineConfig(
        name="sim_host", host="192.0.2.50", ssh_port=22,
        ssh_user="u", ssh_password="p")
    monkeypatch.setattr(rsp, "load_remote_machines", lambda: {"sim_host": cfg})

    def _boom(c):
        raise RemoteTransportError(
            "SSH 通道需要 paramiko：pip install rfauto[remote]")

    monkeypatch.setattr(rsp, "SshTransport", _boom)
    out = pull_artifacts(None, remote_dir=_REMOTE_ROOT,
                         out_dir=tmp_path / "pull")
    assert out["ok"] is False
    assert any("paramiko" in e for e in out["errors"])
    assert out["stage"] == "connect"


# ─── 落位解析与清单构造器 ─────────────────────────────────────────────────


def test_resolve_pull_out_dir_absolute_passthrough(tmp_path):
    assert resolve_pull_out_dir(tmp_path / "x") == tmp_path / "x"


def test_resolve_pull_out_dir_relative_runs_convergence(
        tmp_path, monkeypatch):
    """相对路径：runs 双根收敛（cwd 优先，agent_sandbox._resolve_root 同款）。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    got = resolve_pull_out_dir("runs/remote_pull/case1")
    assert got == tmp_path / "runs" / "remote_pull" / "case1"


def test_resolve_pull_out_dir_default_stamp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    got = resolve_pull_out_dir(None)
    assert got.parent == tmp_path / "runs" / "remote_pull"
    assert len(got.name) == 15 and "_" in got.name   # YYYYMMDD_HHMMSS


def test_record_pull_manifest_autofill(tmp_path):
    """清单构造器：缺 bytes/sha256 的行按本地文件自动回填；信封走 ok 构造器。"""
    local = tmp_path / "artifact.s2p"
    local.write_bytes(b"autofill-me")
    out = record_pull_manifest(
        tmp_path, files=[{
            "remote": _F1, "local": str(local), "status": "pulled",
        }], machine="sim_host", remote_dir=_REMOTE_ROOT)
    assert out["ok"] is True
    manifest = json.loads(Path(out["path"]).read_text(encoding="utf-8"))
    row = manifest["files"][0]
    assert row["bytes"] == 11
    assert row["sha256"] == _sha(b"autofill-me")
    assert row["remote"] == _F1 and row["status"] == "pulled"
    assert manifest["counts"]["pulled"] == 1
    assert "attempts" not in row and "error" not in row
    # 原子写：正式清单旁不留 .tmp 半写残面
    assert list(tmp_path.glob("*.tmp")) == []


def test_pull_mixed_partial_verdict(tmp_path):
    """混合形态：一拉成一缺 → PARTIAL（ok=True），逐文件状态如实并存。"""
    body = b"partial-ok"
    t = FakeSftpTransport(
        files={_F1: body},
        test_path={_F1: True, f"{_REMOTE_ROOT}/gone.s2p": False},
    )
    out = pull_artifacts(
        "sim_host", remote_dir=_REMOTE_ROOT,
        out_dir=tmp_path / "pull",
        remote_files=[_F1, f"{_REMOTE_ROOT}/gone.s2p"], transport=t)
    assert out["ok"] is True and out["verdict"] == "PARTIAL"
    assert out["counts"] == {"pulled": 1, "skipped_exists": 0,
                             "missing_remote": 1, "filtered": 0,
                             "failed": 0}
