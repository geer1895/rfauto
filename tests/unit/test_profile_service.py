"""PR-8 剖析入口单测（service/profile_service.py + /api/profile）。

py-spy 为可选依赖且本机未装——子进程路径 monkeypatch stub，缺装降级
路径真跑钉住（诚实 skip 的反面：降级面必须真实可测）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from rfauto.service import profile_service as ps
from rfauto.service.profile_service import profile_run, profile_status


@pytest.fixture()
def fake_pyspy(monkeypatch, tmp_path):
    """py-spy 在位 + subprocess 捕获（不真跑；产物 stub 落盘模拟 py-spy 写文件）。"""
    monkeypatch.setattr(ps.shutil, "which", lambda name: r"E:\tools\py-spy.exe")
    calls = {}

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        out = argv[argv.index("-o") + 1]
        ps.Path(out).write_bytes(b"flamegraph-stub")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ps.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    return calls


class TestStatus:
    def test_available(self, monkeypatch):
        monkeypatch.setattr(ps.shutil, "which", lambda name: r"E:\tools\py-spy.exe")
        r = profile_status()
        assert r["ok"] and r["available"] and r["exe"] == r"E:\tools\py-spy.exe"

    def test_missing_is_honest_not_fake(self, monkeypatch):
        monkeypatch.setattr(ps.shutil, "which", lambda name: None)
        r = profile_status()
        assert r["ok"] and r["available"] is False
        assert "pip install py-spy" in r["hint"]


class TestProfileRun:
    def test_pid_target_argv_shape(self, fake_pyspy):
        r = profile_run(pid=4242, duration_s=10, rate_hz=200, fmt="flamegraph")
        assert r["ok"], r
        argv = fake_pyspy["argv"]
        assert argv[0] == r"E:\tools\py-spy.exe" and argv[1] == "record"
        assert "-o" in argv and argv[argv.index("--format") + 1] == "flamegraph"
        assert argv[argv.index("-d") + 1] == "10.0"
        assert argv[argv.index("-r") + 1] == "200"
        assert argv[argv.index("--pid") + 1] == "4242"
        assert r["output_path"].endswith("pyspy_pid4242.svg")
        assert str(r["output_path"]).replace("\\", "/").startswith("runs/profile/")

    def test_cmd_target_argv_shape(self, fake_pyspy):
        r = profile_run(cmd=["python", "scripts/x.py", "--fast"])
        assert r["ok"], r
        argv = fake_pyspy["argv"]
        sep = argv.index("--")
        assert argv[sep + 1:] == ["python", "scripts/x.py", "--fast"]
        assert r["output_path"].endswith(".svg")

    def test_speedscope_ext(self, fake_pyspy):
        r = profile_run(pid=1, fmt="speedscope")
        assert r["ok"] and r["output_path"].endswith(".json")

    def test_pid_and_cmd_xor(self, fake_pyspy):
        assert profile_run()["ok"] is False
        assert profile_run(pid=1, cmd=["x"])["ok"] is False

    def test_missing_pyspy_is_error_with_hint(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ps.shutil, "which", lambda name: None)
        monkeypatch.chdir(tmp_path)
        r = profile_run(pid=1)
        assert r["ok"] is False and "pip install py-spy" in r["errors"][0]

    @pytest.mark.parametrize("kwargs,needle", [
        ({"pid": 1, "fmt": "perf"}, "fmt"),
        ({"pid": 1, "duration_s": 0.5}, "duration_s"),
        ({"pid": 1, "duration_s": 99999}, "duration_s"),
        ({"pid": 1, "rate_hz": 5}, "rate_hz"),
        ({"pid": 1, "rate_hz": 1.5}, "rate_hz"),
    ])
    def test_invalid_args_rejected(self, fake_pyspy, kwargs, needle):
        r = profile_run(**kwargs)
        assert r["ok"] is False and needle in r["errors"][0]

    def test_nonzero_rc_is_error_with_stderr(self, fake_pyspy, tmp_path, monkeypatch):
        def fail_run(argv, **kwargs):
            return SimpleNamespace(returncode=3, stdout="", stderr="Permission denied")

        monkeypatch.setattr(ps.subprocess, "run", fail_run)
        monkeypatch.chdir(tmp_path)
        r = profile_run(pid=1)
        assert r["ok"] is False and "rc=3" in r["errors"][0]

    def test_missing_output_file_is_error(self, fake_pyspy, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(ps.subprocess, "run",
                            lambda argv, **kw: SimpleNamespace(
                                returncode=0, stdout="", stderr=""))
        # 产物未落盘（stub 不写文件）→ 显错不假绿
        r = profile_run(pid=1)
        assert r["ok"] is False


class TestHttpEndpoint:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "runs").mkdir()  # /runs 静态挂载要求目录存在
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        return TestClient(create_ui_app())

    def test_get_status(self, client, monkeypatch):
        monkeypatch.setattr(ps.shutil, "which", lambda name: None)
        r = client.get("/api/profile").json()
        assert r["ok"] and r["available"] is False

    def test_post_run(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(ps.shutil, "which", lambda name: r"E:\t\py-spy.exe")

        def fake_run(argv, **kwargs):
            out = argv[argv.index("-o") + 1]
            ps.Path(out).write_bytes(b"<!DOCTYPE html>flame")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(ps.subprocess, "run", fake_run)
        r = client.post("/api/profile", json={"pid": "77", "duration_s": 5}).json()
        assert r["ok"] and r["output_path"].endswith("pyspy_pid77.svg")

    def test_post_bad_params_error_envelope(self, client):
        r = client.post("/api/profile", json={"duration_s": "abc"}).json()
        assert r["ok"] is False and "非法" in r["errors"][0]

    def test_index_serves_profile_view(self, client):
        html = client.get("/").text
        assert 'id="view-profile"' in html and 'data-v="profile"' in html
