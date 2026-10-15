"""license_probe 多候选逐台探测回归钉（review_aurora_next A7 P2-4，2026-10-13）。

修复前形态：``probe_license`` 候选循环内**首个连接失败即 return
available=False**——环境变量列了主备两台 license server 时首台宕机即判
不可达，备台永不尝试（与模块"license-aware 队列挂起等待而非失败"意图
相悖；等待重试期间备台可能已恢复）。修复后：连接失败 ``continue`` 收集
逐台失败明细，循环外全败才返回 ``available=False``（detail 带逐台原因）。

不变量钉（既有口径防回归）：
- spec 解析失败（非 host:port / port@host 形态）仍即时 fail-open 放行；
- 单候选全败返回 ``server=该 spec``（str，消费面
  batch_guard.assert_license_headroom 按 truthy 判"已配置"）；
- 无配置放行（available=True, server=None）。
"""

from __future__ import annotations

import contextlib
import socket
import threading

import pytest


def _live_listener() -> socket.socket:
    """起 localhost TCP listener 模拟可达 license server（调用方负责 close）。

    accept 线程吞 OSError——fail-open 用例（解析失败提前放行）从不连接，
    close 后阻塞中的 accept 会抛错，不能泄漏成未处理线程异常告警。"""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def _accept():
        with contextlib.suppress(OSError):
            srv.accept()

    threading.Thread(target=_accept, daemon=True).start()
    return srv


@pytest.fixture()
def _no_license_env(monkeypatch):
    monkeypatch.delenv("ANSYSLMD_LICENSE_FILE", raising=False)
    monkeypatch.delenv("RFAUTO_LICENSE_SERVER", raising=False)


class TestMultiCandidateProbe:
    def test_primary_down_backup_reachable_passes(self, _no_license_env, monkeypatch):
        """核心回归钉：主台宕机不再短路判死——备台可达即 available=True。"""
        from rfauto.infra.license_probe import probe_license

        srv = _live_listener()
        try:
            backup_spec = f"127.0.0.1:{srv.getsockname()[1]}"
            monkeypatch.setenv("ANSYSLMD_LICENSE_FILE", "127.0.0.1:1")
            monkeypatch.setenv("RFAUTO_LICENSE_SERVER", backup_spec)
            result = probe_license(timeout_s=1.0)
        finally:
            srv.close()
        assert result["available"] is True
        assert result["server"] == backup_spec

    def test_all_candidates_down_fail_with_per_host_detail(self, _no_license_env, monkeypatch):
        """全候选逐台试完仍不可达才判不可用；detail 带逐台失败明细。"""
        from rfauto.infra.license_probe import probe_license

        monkeypatch.setenv("ANSYSLMD_LICENSE_FILE", "127.0.0.1:1")
        monkeypatch.setenv("RFAUTO_LICENSE_SERVER", "127.0.0.1:2")
        result = probe_license(timeout_s=1.0)
        assert result["available"] is False
        assert "127.0.0.1:1" in result["detail"]
        assert "127.0.0.1:2" in result["detail"]
        # server 保持 str 形态（多候选分号连接，消费面 truthy 判"已配置"）
        assert result["server"] == "127.0.0.1:1;127.0.0.1:2"

    def test_single_candidate_failure_shape_unchanged(self, _no_license_env):
        """单候选全败：server=该 spec、detail 非空（修复前形态逐字段保持）。"""
        from rfauto.infra.license_probe import probe_license

        result = probe_license("127.0.0.1:1", timeout_s=1.0)
        assert result["available"] is False
        assert result["server"] == "127.0.0.1:1"
        assert result["detail"]

    def test_unparseable_candidate_still_fails_open_first(self, _no_license_env, monkeypatch):
        """解析失败候选仍即时 fail-open 放行（多值串/文件路径形态，口径不变）。"""
        from rfauto.infra.license_probe import probe_license

        srv = _live_listener()
        try:
            live_spec = f"127.0.0.1:{srv.getsockname()[1]}"
            monkeypatch.setenv("ANSYSLMD_LICENSE_FILE", "some-weird-multi;spec")
            monkeypatch.setenv("RFAUTO_LICENSE_SERVER", live_spec)
            result = probe_license(timeout_s=1.0)
        finally:
            srv.close()
        assert result["available"] is True
        assert result["server"] == "some-weird-multi;spec"
        assert "无法探测" in result["detail"]
