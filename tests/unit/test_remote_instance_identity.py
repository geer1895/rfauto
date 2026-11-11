"""VB-4 grpcsrv 实例身份绑定单测（全离线合成，#139：SSH 通道 monkeypatch 钉死）。

覆盖（席位任务书验收面）：
① 判定纯函数五态钉：匹配 / PID 不符 / 创建时刻不符（PID 复用）/
   记录缺失→拒连 / 记录损坏→拒连（外加活实例不可验态 fail-closed）；
② 开关缺省关零变化（env 未设：attach 调用形状逐字节同、无记录步骤键）；
③ 记录读写往返 + 损坏 JSON 拒（坏 JSON/形状不合/类型错/时刻不可解析）；
④ 发射侧编排（恰一命中才可记录/歧义拒）+ attach 侧核验编排离线面；
⑤ 真机冒烟 opt-in skipif 门（``RFAUTO_REMOTE_SMOKE=1`` 才跑——本席
   零真机，服务器真机冒烟窗口留主代执行，挂账声明）。
"""

import os
import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.service.remote_service as rs
import rfauto.service.remote_service.hfss_smoke as rsh
from rfauto.service.remote_service import instance_identity as ii
from rfauto.service.remote_service.instance_identity import (
    InstanceRecordError,
    build_instance_record,
    judge_instance_identity,
    load_instance_record,
    parse_creation_query_output,
    parse_creation_to_key,
    query_creation_by_fingerprint_command,
    query_creation_by_pid_command,
    record_filename,
    remote_record_paths,
    write_instance_record,
)

RECORD_ARGS = dict(
    port=50051,
    pid=1234,
    process_create_time="20261110123456.123456",
    seat="R-15",
    project_root="E:\\rfauto_remote",
)


def _record(**overrides):
    kwargs = dict(RECORD_ARGS)
    kwargs.update(overrides)
    return build_instance_record(**kwargs)


class _FakeTransport:
    """离线 SSH 桩：命令按子串注册表应答；零网络零真机（#139）。"""

    def __init__(self, replies=None, fail_upload=False):
        self.commands: list[str] = []
        self.uploads: list[tuple[str, str]] = []
        self.replies = dict(replies or {})
        self.fail_upload = fail_upload

    def connect(self):
        pass

    def run_command(self, cmd, timeout_s=60.0):
        self.commands.append(cmd)
        for key, val in self.replies.items():
            if key in cmd:
                if isinstance(val, tuple):
                    return val
                return 0, val, ""
        return 0, "", ""

    def upload_file(self, local, remote):
        if self.fail_upload:
            raise OSError("mock: upload boom")
        self.uploads.append((str(local), remote))

    def close(self):
        pass


# ─── ① 判定纯函数五态钉 ──────────────────────────────────────────────────


def test_judge_match_allows():
    rec = _record()
    out = judge_instance_identity(
        "ok", rec, 1234, "20261110123456.123456")
    assert out["verdict"] == "match" and out["allowed"] is True


def test_judge_pid_mismatch_refuses():
    rec = _record()
    out = judge_instance_identity(
        "ok", rec, 9999, "20261110123456.123456")
    assert out["verdict"] == "pid_mismatch" and out["allowed"] is False
    assert "PID 不符" in out["reason"]


def test_judge_create_time_mismatch_refuses_pid_reuse():
    """PID 复用形态：PID 相等、创建时刻不同键 → 拒。"""
    rec = _record()
    out = judge_instance_identity(
        "ok", rec, 1234, "20261110120000.000000")
    assert out["verdict"] == "create_time_mismatch"
    assert out["allowed"] is False
    assert "PID 复用" in out["reason"]


def test_judge_record_missing_refuses():
    out = judge_instance_identity("missing", None, 1234, "20261110123456.123456")
    assert out["verdict"] == "record_missing" and out["allowed"] is False


def test_judge_record_corrupt_refuses():
    out = judge_instance_identity("corrupt", None, 1234, "20261110123456.123456")
    assert out["verdict"] == "record_corrupt" and out["allowed"] is False


def test_judge_live_unverifiable_refuses_fail_closed():
    rec = _record()
    for live_pid, live_creation in ((None, "20261110123456.123456"),
                                    (1234, None),
                                    (1234, "not-a-datetime")):
        out = judge_instance_identity("ok", rec, live_pid, live_creation)
        assert out["verdict"] == "live_unverifiable"
        assert out["allowed"] is False


def test_judge_record_state_precedence_over_live():
    """记录态优先：缺失记录+活 PID 不可得 → 报 record_missing（文档化序）。"""
    out = judge_instance_identity("missing", None, None, None)
    assert out["verdict"] == "record_missing"


# ─── ② 开关缺省关零变化 ──────────────────────────────────────────────────


def test_switch_default_off():
    assert ii.instance_verify_enabled({}) is False
    assert ii.instance_verify_enabled({"RFAUTO_REMOTE_INSTANCE_VERIFY": ""}) is False
    assert ii.instance_verify_enabled({"RFAUTO_REMOTE_INSTANCE_VERIFY": "0"}) is False
    assert ii.instance_verify_enabled({"RFAUTO_REMOTE_INSTANCE_VERIFY": "no"}) is False


def test_switch_truthy_variants():
    for value in ("1", "true", "TRUE", "Yes", "on"):
        assert ii.instance_verify_enabled(
            {"RFAUTO_REMOTE_INSTANCE_VERIFY": value}) is True


def test_smoke_default_off_attach_call_shape_unchanged(monkeypatch):
    """缺省路径零变化：attach 恰以既有两参形状被调，零记录步骤键。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    monkeypatch.delenv(ii.REMOTE_INSTANCE_VERIFY_ENV, raising=False)
    _wire_machine(monkeypatch)
    captured: dict = {}

    def fake_attach(cfg, steps, **kw):
        captured["kwargs"] = kw
        return {"ok": True, "reason": None, "steps": steps}

    monkeypatch.setattr(rs, "_attach_and_verify", fake_attach)
    out = rs.remote_hfss_smoke("lab_server")
    assert out["ok"] is True
    assert captured["kwargs"] == {}
    assert "instance_record" not in out["steps"]
    assert "instance_verify" not in out["steps"]


def test_l2_default_off_solve_call_shape_unchanged(monkeypatch, tmp_path):
    """L2 缺省路径零变化：_l2_model_solve_export 恰以既有四参形状被调。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    monkeypatch.delenv(ii.REMOTE_INSTANCE_VERIFY_ENV, raising=False)
    _wire_machine(monkeypatch)
    captured: dict = {}

    def fake_solve(cfg, proj, s2p, steps, **kw):
        captured["kwargs"] = kw
        return {"ok": False, "reason": "mock: 到此为止"}  # 截流免 Test-Path

    monkeypatch.setattr(rs, "_l2_model_solve_export", fake_solve)
    out = rs.remote_hfss_l2_smoke("lab_server", out_dir=str(tmp_path / "pull"))
    assert captured["kwargs"] == {}
    assert "instance_record" not in out["steps"]


def _wire_machine(monkeypatch):
    """既有测试同款单机登记+凭据+探活桩（零真机零连网）。

    ``_launch_grpcsrv`` 一并打桩成功——不桩会走真实 ``probe_port`` TCP
    轮询（#139 禁网红线；既有 test_smoke_mutex_clear 同款约束）。
    """
    cfg = rs.RemoteMachineConfig(
        name="lab_server", host="192.0.2.10", ssh_port=22,
        hfss_grpc_port=50051, hfss_project_root="E:\\rfauto_remote",
        hfss_ansysedt_exe="E:\\x\\ansysedt.exe",
    )
    monkeypatch.setattr(rs, "load_remote_machines", lambda: {"lab_server": cfg})
    monkeypatch.setenv("RFAUTO_REMOTE_SSH_USER", "u")
    monkeypatch.setenv("RFAUTO_REMOTE_SSH_PASSWORD", "p")
    monkeypatch.setattr(rs, "probe_machine",
                        lambda cfg: {"name": cfg.name, "reachable": True})
    monkeypatch.setattr(rs, "SshTransport", lambda cfg: _FakeTransport())
    monkeypatch.setattr(rs, "_launch_grpcsrv", lambda *a, **kw: None)
    return cfg


# ─── ③ 记录读写往返 + 损坏拒 ─────────────────────────────────────────────


def test_record_write_load_roundtrip(tmp_path):
    rec = _record()
    written = write_instance_record(rec, tmp_path)
    path = Path(written["local_path"])
    assert path.is_file()
    assert written["filename"] == record_filename(rec)
    state, loaded = load_instance_record(path)
    assert state == "ok"
    assert loaded == rec  # uuid/created_at 经 JSON 往返逐字段保真


def test_record_default_filename_shape():
    rec = _record()
    assert record_filename(rec) == \
        f"grpcsrv_instance_p{rec['port']}_{rec['uuid'][:8]}.json"


@pytest.mark.parametrize("bad_text", [
    "",                       # 空文件
    "{not json",              # 坏 JSON
    "[1, 2, 3]",              # 非 object
    '{"port": 50051}',        # 缺键
    "garbage line\n{bad",     # 截断
])
def test_record_corrupt_variants_refused(tmp_path, bad_text):
    path = tmp_path / "bad.json"
    path.write_text(bad_text, encoding="utf-8")
    state, rec = load_instance_record(path)
    assert state == "corrupt" and rec is None


def test_record_shape_rejections(tmp_path):
    path = tmp_path / "shape.json"
    rec = _record()
    # 多键（完整记录口径：恰好七键）
    extra = dict(rec)
    extra["bonus"] = 1
    path.write_text(str(extra).replace("'", '"'), encoding="utf-8")
    assert load_instance_record(path)[0] == "corrupt"
    # pid/port 类型错（str）与 bool 陷阱（bool 是 int 子类）
    for bad in ("pid", "port"):
        wrong = dict(rec)
        wrong[bad] = str(rec[bad])
        with pytest.raises(InstanceRecordError):
            _validate_raw(wrong)
        bool_version = dict(rec)
        bool_version[bad] = True
        with pytest.raises(InstanceRecordError):
            _validate_raw(bool_version)
    # 创建时刻不可解析
    bad_time = dict(rec)
    bad_time["process_create_time"] = "31/10/2026 12:00"
    with pytest.raises(InstanceRecordError):
        _validate_raw(bad_time)
    assert load_instance_record(_dump(tmp_path, bad_time))[0] == "corrupt"


def _validate_raw(data):
    ii.validate_instance_record(data)


def _dump(tmp_path, data):
    import json

    path = tmp_path / "t.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_record_missing_state(tmp_path):
    state, rec = load_instance_record(tmp_path / "nope.json")
    assert state == "missing" and rec is None


def test_parse_creation_key_pins():
    assert parse_creation_to_key("20261110123456.123456") == \
        ("20261110123456", 123456, "")
    # 小数秒右侧补零等价
    assert parse_creation_to_key("20261110123456.5") == \
        parse_creation_to_key("20261110123456.500000")
    # 时区偏移保留入键（无偏移 ≠ 有偏移——fail-closed 不猜换算）
    assert parse_creation_to_key("20261110123456.123456") != \
        parse_creation_to_key("20261110123456.123456+480")
    assert parse_creation_to_key("bad") is None
    assert parse_creation_to_key(None) is None


# ─── ④ 查询命令构造（G5 零双引号）与协议行解析 ───────────────────────────


def test_query_commands_zero_double_quotes():
    fp = query_creation_by_fingerprint_command("ansysedt.exe", "grpcsrv.*:50051:")
    pid = query_creation_by_pid_command(1234)
    assert '"' not in fp and '"' not in pid
    assert "CreationDate" in fp and "grpcsrv.*:50051:" in fp
    assert "ProcessId -eq 1234" in pid


def test_parse_query_output_protocol_lines_only():
    out = "header noise\n1234|20261110123456.123456\n\nother\n5678|20261110120000.000000\n"
    hits = parse_creation_query_output(out)
    assert hits == [(1234, "20261110123456.123456"),
                    (5678, "20261110120000.000000")]
    assert parse_creation_query_output("") == []
    # 空时刻段不误判为命中
    assert parse_creation_query_output("1234|\n") == []


# ─── ⑤ 发射侧编排（恰一命中才可记录；歧义/零命中/失败拒） ─────────────────


def _fake_cfg():
    return rs.RemoteMachineConfig(
        name="lab_server", host="192.0.2.10", ssh_port=22,
        hfss_grpc_port=50051, hfss_project_root="E:\\rfauto_remote",
        hfss_ansysedt_exe="E:\\x\\ansysedt.exe",
    )


def test_write_launch_record_happy_path(tmp_path):
    cfg = _fake_cfg()
    transport = _FakeTransport(
        replies={"CreationDate": "1234|20261110123456.123456\n"})
    steps: dict = {}
    out = ii.write_launch_instance_record(
        cfg, transport, fingerprint="grpcsrv.*:50051:", seat="R-15",
        local_dir=tmp_path, steps=steps)
    assert out is None
    rec_info = steps["instance_record"]
    assert rec_info["pid"] == 1234
    assert rec_info["remote_path"].endswith(
        "\\instance_records\\" + Path(rec_info["local_path"]).name)
    assert rec_info["sftp_path"].startswith("E:/rfauto_remote/instance_records/")
    state, loaded = load_instance_record(rec_info["local_path"])
    assert state == "ok" and loaded["port"] == 50051 and loaded["seat"] == "R-15"
    assert len(transport.uploads) == 1
    for cmd in transport.commands:
        assert '"' not in cmd  # G5 全程零双引号


def test_write_launch_record_zero_hit_refuses(tmp_path):
    cfg = _fake_cfg()
    transport = _FakeTransport(replies={"CreationDate": ""})
    steps: dict = {}
    out = ii.write_launch_instance_record(
        cfg, transport, fingerprint="grpcsrv.*:50051:",
        local_dir=tmp_path, steps=steps)
    assert out is not None and "恰一" in out["reason"]
    assert steps["instance_record"]["hits"] == 0
    assert not transport.uploads  # 未上传未落记录


def test_write_launch_record_ambiguous_refuses(tmp_path):
    cfg = _fake_cfg()
    transport = _FakeTransport(replies={"CreationDate":
                                        "1|20261110123456.000000\n"
                                        "2|20261110123456.000000\n"})
    steps: dict = {}
    out = ii.write_launch_instance_record(
        cfg, transport, fingerprint="grpcsrv.*:50051:",
        local_dir=tmp_path, steps=steps)
    assert out is not None and "2 例" in out["reason"]


def test_write_launch_record_query_rc_failure_refuses(tmp_path):
    cfg = _fake_cfg()
    transport = _FakeTransport(replies={"CreationDate": (1, "", "boom")})
    steps: dict = {}
    out = ii.write_launch_instance_record(
        cfg, transport, fingerprint="grpcsrv.*:50051:",
        local_dir=tmp_path, steps=steps)
    assert out is not None and "rc=1" in out["reason"]


def test_write_launch_record_upload_failure_refuses(tmp_path):
    """上传失败 → 失败片段（fail-closed 拒 attach，非裸抛）。"""
    cfg = _fake_cfg()
    transport = _FakeTransport(
        replies={"CreationDate": "1234|20261110123456.123456\n"},
        fail_upload=True)
    steps: dict = {}
    out = ii.write_launch_instance_record(
        cfg, transport, fingerprint="grpcsrv.*:50051:",
        local_dir=tmp_path, steps=steps)
    assert out is not None and "fail-closed" in out["reason"]
    assert steps["instance_record"]["error"] == "OSError"


def test_write_launch_record_default_dir_under_cwd(tmp_path, monkeypatch):
    """缺省本地目录=cwd 相对 runs/（#144 chdir 隔离：tmp 内零污染真湖）。"""
    monkeypatch.chdir(tmp_path)
    cfg = _fake_cfg()
    transport = _FakeTransport(
        replies={"CreationDate": "1234|20261110123456.123456\n"})
    steps: dict = {}
    out = ii.write_launch_instance_record(
        cfg, transport, fingerprint="grpcsrv.*:50051:", steps=steps)
    assert out is None
    local = Path(steps["instance_record"]["local_path"])
    assert local.is_file()
    assert "runs" in local.parts and "remote_instance_records" in local.parts


def test_remote_record_paths_unsafe_refused():
    with pytest.raises(InstanceRecordError):
        remote_record_paths("E:\\bad path", "a.json")   # 空白
    with pytest.raises(InstanceRecordError):
        remote_record_paths("E:\\bad'path", "a.json")   # 单引号
    with pytest.raises(InstanceRecordError):
        remote_record_paths("E:\\ok", "a b.json")       # 文件名空白


# ─── ⑥ attach 侧核验编排（离线五态全走真判定链） ─────────────────────────


def _prep_record(tmp_path, **overrides):
    rec = _record(**overrides)
    written = write_instance_record(rec, tmp_path)
    return rec, written["local_path"]


def test_verify_orchestration_match(tmp_path):
    _rec, rec_path = _prep_record(tmp_path)
    transport = _FakeTransport(
        replies={"ProcessId -eq": "1234|20261110123456.123456\n"})
    steps: dict = {}
    out = ii.verify_attached_instance(
        transport, rec_path, 1234, steps=steps)
    assert out["allowed"] is True and out["verdict"] == "match"
    assert steps["instance_verify"]["record_state"] == "ok"
    for cmd in transport.commands:
        assert '"' not in cmd


def test_verify_orchestration_pid_mismatch(tmp_path):
    _rec, rec_path = _prep_record(tmp_path)
    transport = _FakeTransport(
        replies={"ProcessId -eq": "9999|20261110123456.123456\n"})
    out = ii.verify_attached_instance(
        transport, rec_path, 9999, steps={})
    assert out["verdict"] == "pid_mismatch" and out["allowed"] is False


def test_verify_orchestration_create_time_mismatch(tmp_path):
    _rec, rec_path = _prep_record(tmp_path)
    transport = _FakeTransport(
        replies={"ProcessId -eq": "1234|20261110120000.000000\n"})
    out = ii.verify_attached_instance(
        transport, rec_path, 1234, steps={})
    assert out["verdict"] == "create_time_mismatch" and not out["allowed"]


def test_verify_orchestration_missing_and_corrupt(tmp_path):
    out = ii.verify_attached_instance(
        _FakeTransport(), tmp_path / "nope.json", 1234, steps={})
    assert out["verdict"] == "record_missing" and not out["allowed"]
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    out = ii.verify_attached_instance(_FakeTransport(), bad, 1234, steps={})
    assert out["verdict"] == "record_corrupt" and not out["allowed"]


def test_verify_orchestration_query_failure_fail_closed(tmp_path):
    _rec, rec_path = _prep_record(tmp_path)
    transport = _FakeTransport(replies={"ProcessId -eq": (1, "", "boom")})
    out = ii.verify_attached_instance(transport, rec_path, 1234, steps={})
    assert out["verdict"] == "live_unverifiable" and not out["allowed"]
    assert out["query_error"] is not None


def test_verify_orchestration_transport_and_pid_unavailable(tmp_path):
    _rec, rec_path = _prep_record(tmp_path)
    out = ii.verify_attached_instance(None, rec_path, 1234, steps={})
    assert out["verdict"] == "live_unverifiable" and not out["allowed"]
    out = ii.verify_attached_instance(_FakeTransport(), rec_path, None,
                                      steps={})
    assert out["verdict"] == "live_unverifiable" and not out["allowed"]


def test_verify_orchestration_ambiguous_pid_query_refuses(tmp_path):
    _rec, rec_path = _prep_record(tmp_path)
    transport = _FakeTransport(replies={"ProcessId -eq":
                                        "1234|20261110123456.123456\n"
                                        "1234|20261110123456.999999\n"})
    out = ii.verify_attached_instance(transport, rec_path, 1234, steps={})
    assert out["verdict"] == "live_unverifiable" and not out["allowed"]


# ─── ⑦ hfss_smoke 接线（开关开：记录+核验+清理退役） ──────────────────────


def test_smoke_verify_on_wires_record_and_verify(monkeypatch, tmp_path):
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    monkeypatch.setenv(ii.REMOTE_INSTANCE_VERIFY_ENV, "1")
    _wire_machine(monkeypatch)

    def fake_writer(cfg, transport, *, fingerprint, seat=None,
                    local_dir=None, steps=None):
        steps["instance_record"] = {
            "local_path": str(tmp_path / "rec.json"),
            "remote_path": "E:\\rfauto_remote\\instance_records\\rec.json",
            "pid": 1234,
        }
        return None

    captured: dict = {}

    def fake_attach(cfg, steps, **kw):
        captured.update(kw)
        return {"ok": True, "reason": None, "steps": steps}

    # 打桩落点=hfss_smoke 子模块（调用方全局解析处；facade __init__ 未
    # re-export 本名——接线面按持有模块打桩，公开面零变化）。
    monkeypatch.setattr(rsh, "write_launch_instance_record", fake_writer)
    monkeypatch.setattr(rs, "_attach_and_verify", fake_attach)
    out = rs.remote_hfss_smoke("lab_server", seat="R-15")
    assert out["ok"] is True
    assert captured.get("verify_identity") is True
    assert captured.get("record_path") == str(tmp_path / "rec.json")
    assert captured.get("transport") is not None
    assert out["steps"]["instance_record"]["pid"] == 1234


def test_smoke_verify_on_record_failure_refuses_attach(monkeypatch):
    """记录写不出 → fail-closed 拒 attach（ADR-0004 永不回退）。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    monkeypatch.setenv(ii.REMOTE_INSTANCE_VERIFY_ENV, "1")
    _wire_machine(monkeypatch)

    def fake_writer(cfg, transport, **kw):
        return {"reason": "mock: 记录写不出"}

    def _boom(*a, **kw):
        raise AssertionError("记录失败路径不得进入 attach")

    monkeypatch.setattr(rsh, "write_launch_instance_record", fake_writer)
    monkeypatch.setattr(rs, "_attach_and_verify", _boom)
    out = rs.remote_hfss_smoke("lab_server")
    assert out["ok"] is False
    assert "mock: 记录写不出" in out["reason"]


def test_l2_verify_on_wires_record_and_verify(monkeypatch, tmp_path):
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    monkeypatch.setenv(ii.REMOTE_INSTANCE_VERIFY_ENV, "1")
    _wire_machine(monkeypatch)
    captured: dict = {}

    def fake_writer(cfg, transport, *, fingerprint, seat=None,
                    local_dir=None, steps=None):
        steps["instance_record"] = {
            "local_path": str(tmp_path / "rec.json"),
            "remote_path": "E:\\rfauto_remote\\instance_records\\rec.json",
        }
        return None

    def fake_solve(cfg, proj, s2p, steps, **kw):
        captured.update(kw)
        return {"ok": False, "reason": "mock: 到此为止"}  # 截流免 Test-Path

    monkeypatch.setattr(rsh, "write_launch_instance_record", fake_writer)
    monkeypatch.setattr(rs, "_l2_model_solve_export", fake_solve)
    out = rs.remote_hfss_l2_smoke("lab_server", out_dir=str(tmp_path / "pull"))
    assert captured.get("verify_identity") is True
    assert captured.get("record_path") == str(tmp_path / "rec.json")
    assert captured.get("transport") is not None
    assert "instance_record" in out["steps"]


def test_cleanup_deletes_instance_record_exact_path(monkeypatch):
    """清理退役：精确点名删记录文件（非通配），命令全程零双引号。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    cfg = rs.RemoteMachineConfig(
        name="lab_server", host="192.0.2.10", ssh_port=22,
        hfss_grpc_port=50051, hfss_project_root="E:\\rfauto_remote",
    )
    monkeypatch.setattr(rs, "load_remote_machines", lambda: {"lab_server": cfg})
    monkeypatch.setenv("RFAUTO_REMOTE_SSH_USER", "u")
    monkeypatch.setenv("RFAUTO_REMOTE_SSH_PASSWORD", "p")
    transport = _FakeTransport()
    monkeypatch.setattr(rs, "SshTransport", lambda cfg: transport)
    out = rs.remote_hfss_cleanup(
        "lab_server",
        record_remote_path="E:\\rfauto_remote\\instance_records\\rec.json",
    )
    assert out["ok"] is True
    assert out["steps"]["deleted_instance_record"] == \
        "E:\\rfauto_remote\\instance_records\\rec.json"
    remove_cmds = [c for c in transport.commands if "Remove-Item" in c]
    assert len(remove_cmds) == 1
    assert "instance_records\\rec.json" in remove_cmds[0]
    assert '"' not in remove_cmds[0]


def test_cleanup_without_record_no_remove(monkeypatch):
    """缺省（无记录路径）零变化：不产生任何 Remove-Item 命令。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    cfg = rs.RemoteMachineConfig(
        name="lab_server", host="192.0.2.10", ssh_port=22,
        hfss_grpc_port=50051, hfss_project_root="E:\\rfauto_remote",
    )
    monkeypatch.setattr(rs, "load_remote_machines", lambda: {"lab_server": cfg})
    monkeypatch.setenv("RFAUTO_REMOTE_SSH_USER", "u")
    monkeypatch.setenv("RFAUTO_REMOTE_SSH_PASSWORD", "p")
    transport = _FakeTransport()
    monkeypatch.setattr(rs, "SshTransport", lambda cfg: transport)
    out = rs.remote_hfss_cleanup("lab_server")
    assert out["ok"] is True
    assert not any("Remove-Item" in c for c in transport.commands)


def test_smoke_off_no_record_cleanup_keys(monkeypatch):
    """缺省全链：steps 无 instance_record/instance_verify/删除键（零变化）。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    monkeypatch.delenv(ii.REMOTE_INSTANCE_VERIFY_ENV, raising=False)
    _wire_machine(monkeypatch)
    monkeypatch.setattr(rs, "_attach_and_verify",
                        lambda cfg, steps: {"ok": True, "reason": None,
                                            "steps": steps})
    out = rs.remote_hfss_smoke("lab_server")
    assert out["ok"] is True
    assert "deleted_instance_record" not in out["steps"]["cleanup"]["steps"]


# ─── ⑧ 真机冒烟 opt-in（skipif 门；本席零真机——服务器窗口留主代，挂账） ──


@pytest.mark.skipif(
    os.environ.get(rs.REMOTE_SMOKE_ENV) != "1",
    reason="真机冒烟 opt-in（RFAUTO_REMOTE_SMOKE=1）；unit 门零真机零连网"
           "——本席不跑真机，服务器真机冒烟窗口留主代执行（挂账声明）",
)
def test_real_l1_smoke_instance_verify_opt_in(monkeypatch):
    """真机窗口专用：L1 冒烟+实例身份核验全链（双 env 门）。

    预期：attach PASS 且 steps.instance_verify.verdict=match（正常发射→
    记录→attach 核验通过）；同端口杀掉重发而沿用旧记录的场景由判定纯
    函数 pid_mismatch/create_time_mismatch 钉（离线面），真机复验可选。
    """
    monkeypatch.setenv(ii.REMOTE_INSTANCE_VERIFY_ENV, "1")
    out = rs.remote_hfss_smoke(seat="R-15")
    assert out.get("ok") is True, out
    assert out["steps"]["instance_verify"]["verdict"] == "match"
