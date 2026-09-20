"""导出前置 sweep 完成断言测试（#191 家族 r2-r4，方案 §10.9）。

全部 mock PyAEDT 通道（单测禁真打 HFSS）；profile 文本用
真机 r4（Engine Detected Error）与仲裁 r8（Normal Completion）的
.profile 片段内嵌为常量，不读 runs/（不入 git）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.adapters.hfss_adapter import HfssAdapter, parse_profile_text
from rfauto.adapters.hfss_session import HfssSession
from rfauto.core.errors import ModelBuildError, SimulationFailedError

# ─── 真机 profile 片段（r4 / r8 原样摘录，含 \' 转义） ──────────────────────

_R4_FAIL_SNIPPET = (
    r"ProfileItem('', 0, 0, 0, 0, 0, 'I(1, 0, \'***Port P1sheetP does not have "
    r"a solved inside material on either side.\')', false, true)"
    "\n"
    r"ProfileFootnote('I(2, 1, \'Stop Time\', \'09/09/2026 00:45:18\', "
    r"1, \'Status\', \'Engine Detected Error\')', 2)"
)

_R8_OK_SNIPPET = (
    r"ProfileFootnote('I(1, 0, \'Interpolating sweep converged and is "
    r"passive\')', 0)"
    "\n"
    r"ProfileFootnote('I(2, 1, \'Stop Time\', \'09/08/2026 10:44:43\', "
    r"1, \'Status\', \'Normal Completion\')', 0)"
)


# ─── mock 工具（模拟 pyaedt 对象，纯 Python 无网络/无 HFSS） ────────────────

class _FakeSimProfile:
    def __init__(self, status: str | None = None):
        self.status = status


class _FakeProfiles:
    """模拟 pyaedt Profiles（Mapping）。"""

    def __init__(self, items: dict):
        self._d = dict(items)

    def values(self):
        return self._d.values()

    def keys(self):
        return self._d.keys()

    def __iter__(self):
        return iter(self._d)

    def __getitem__(self, k):
        return self._d[k]

    def __len__(self):
        return len(self._d)


class _FakeSetup:
    def __init__(self, is_solved: bool = True, profile: object | None = None,
                 get_profile_raises: bool = False):
        self.is_solved = is_solved
        self._profile = profile
        self._raises = get_profile_raises

    def get_profile(self):
        if self._raises:
            raise RuntimeError("AEDT not connected")
        return self._profile


class _FakeSolution:
    """记录 ExportNetworkData 是否被触碰（断言必须挡在导出之前）。"""

    def __init__(self):
        self.export_calls = 0

    def ExportNetworkData(self, *args):
        self.export_calls += 1


class _FakeHfss:
    """模拟 Hfss 会话对象（按用例注入行为）。"""

    def __init__(
        self,
        *,
        profiles: _FakeProfiles | None = None,
        profile_raises: bool = False,
        running: bool = False,
        running_raises: bool = False,
        setup: _FakeSetup | None = None,
        get_setup_raises: bool = False,
        project_path: Path | None = None,
        project_name: str = "proj",
        design_name: str = "d",
    ):
        self._profiles = profiles
        self._profile_raises = profile_raises
        self._running = running
        self._running_raises = running_raises
        self._setup = setup
        self._get_setup_raises = get_setup_raises
        self.project_path = project_path
        self.project_name = project_name
        self.design_name = design_name
        self.osolution = _FakeSolution()

    @property
    def are_there_simulations_running(self) -> bool:
        if self._running_raises:
            raise RuntimeError("gRPC blip")
        return self._running

    def get_profile(self, name):
        if self._profile_raises:
            raise RuntimeError("get_profile failed")
        return self._profiles

    def get_setup(self, name):
        if self._get_setup_raises:
            raise RuntimeError("get_setup failed")
        return self._setup


@pytest.fixture()
def adapter(monkeypatch):
    """隔离 HfssSession 单例 + 清环境变量（确定性）。"""
    monkeypatch.delenv("RFAUTO_HFSS_SOLVE_TIMEOUT_S", raising=False)
    HfssSession.reset()
    a = HfssAdapter()
    yield a
    HfssSession.reset()


# ─── parse_profile_text：真机 profile 文本解析 ──────────────────────────────

class TestParseProfileText:
    def test_r4_engine_detected_error(self):
        """r4 真机片段：状态=Engine Detected Error + 端口诊断行。"""
        status, msgs = parse_profile_text(_R4_FAIL_SNIPPET)
        assert status == "Engine Detected Error"
        assert len(msgs) == 1
        assert "Port P1sheetP does not have a solved inside material" in msgs[0]

    def test_r8_normal_completion(self):
        """r8 仲裁真机片段：状态=Normal Completion、无诊断行。"""
        status, msgs = parse_profile_text(_R8_OK_SNIPPET)
        assert status == "Normal Completion"
        assert msgs == []

    def test_empty_text(self):
        assert parse_profile_text("") == (None, [])

    def test_unescaped_plain_status(self):
        status, msgs = parse_profile_text("'Status', 'Normal Completion'")
        assert status == "Normal Completion"
        assert msgs == []


# ─── assert_sweep_completed：三层检查 ────────────────────────────────────────

class TestAssertSweepCompleted:
    def test_not_connected_raises_model_build(self, adapter):
        adapter.session.hfss = None
        with pytest.raises(ModelBuildError):
            adapter.assert_sweep_completed("Setup")

    def test_solve_in_progress_raises(self, adapter):
        adapter.session.hfss = _FakeHfss(running=True)
        with pytest.raises(SimulationFailedError, match="求解仍在进行"):
            adapter.assert_sweep_completed("Setup")

    def test_running_query_blip_degrades(self, adapter):
        """查询通道抖动（gRPC 闪断）→ 降级跳过，不拦健康解。"""
        adapter.session.hfss = _FakeHfss(
            running_raises=True,
            profiles=_FakeProfiles({"s1": _FakeSimProfile("Normal Completion")}),
            setup=_FakeSetup(is_solved=True),
        )
        adapter.assert_sweep_completed("Setup")

    def test_engine_error_raises_with_diagnostic(self, adapter):
        """r4 形态：profile=Engine Detected Error → 拒绝导出+附诊断。"""
        adapter.session.hfss = _FakeHfss(
            profiles=_FakeProfiles({"s1": _FakeSimProfile("Engine Detected Error")}),
        )
        with pytest.raises(SimulationFailedError, match="Engine Detected Error"):
            adapter.assert_sweep_completed("Setup")

    def test_no_profile_anywhere_raises(self, adapter):
        """从未求解完成（无活态 profile 且无磁盘 .profile）→ 拒绝导出。"""
        adapter.session.hfss = _FakeHfss(profiles=None)
        with pytest.raises(SimulationFailedError, match="无求解 profile"):
            adapter.assert_sweep_completed("Setup")

    def test_disk_profile_fallback_error(self, adapter, tmp_path):
        """活态 API 无 profile → 磁盘 .profile 兜底仍能抓引擎错误。"""
        results = tmp_path / "proj.aedtresults" / "d.results"
        results.mkdir(parents=True)
        (results / "DV1_S1_V1.profile").write_text(_R4_FAIL_SNIPPET, encoding="utf-8")
        adapter.session.hfss = _FakeHfss(
            profiles=None, project_path=tmp_path,
            project_name="proj", design_name="d",
        )
        with pytest.raises(SimulationFailedError, match="Engine Detected Error"):
            adapter.assert_sweep_completed("Setup")

    def test_disk_profile_newest_wins(self, adapter, tmp_path):
        """多份磁盘 profile 取 mtime 最新（旧错误 profile 不误伤新解）。"""
        import os

        results = tmp_path / "proj.aedtresults" / "d.results"
        results.mkdir(parents=True)
        old = results / "DV1_S1_V1.profile"
        old.write_text(_R4_FAIL_SNIPPET, encoding="utf-8")
        new = results / "DV2_S1_V2.profile"
        new.write_text(_R8_OK_SNIPPET, encoding="utf-8")
        stat_old, stat_new = old.stat(), new.stat()
        os.utime(old, ns=(stat_old.st_atime_ns, stat_old.st_mtime_ns - 10_000_000))
        os.utime(new, ns=(stat_new.st_atime_ns, stat_new.st_mtime_ns + 10_000_000))
        adapter.session.hfss = _FakeHfss(
            profiles=None, project_path=tmp_path,
            project_name="proj", design_name="d",
        )
        # 最新=Normal Completion → 无活态 profile 时检查 3（is_solved）兜底放行
        adapter.session.hfss._setup = _FakeSetup(is_solved=True)
        adapter.assert_sweep_completed("Setup")

    def test_healthy_profile_passes(self, adapter):
        adapter.session.hfss = _FakeHfss(
            profiles=_FakeProfiles({"s1": _FakeSimProfile("Normal Completion")}),
            setup=_FakeSetup(is_solved=True),
        )
        adapter.assert_sweep_completed("Setup", "Sweep")

    def test_is_solved_false_raises(self, adapter):
        adapter.session.hfss = _FakeHfss(
            profiles=_FakeProfiles({"s1": _FakeSimProfile("Normal Completion")}),
            setup=_FakeSetup(is_solved=False),
        )
        with pytest.raises(SimulationFailedError, match="is_solved=False"):
            adapter.assert_sweep_completed("Setup")

    def test_is_solved_query_blip_degrades(self, adapter):
        adapter.session.hfss = _FakeHfss(
            profiles=_FakeProfiles({"s1": _FakeSimProfile("Normal Completion")}),
            get_setup_raises=True,
        )
        adapter.assert_sweep_completed("Setup")


# ─── solve()：analyze 返回 True 但引擎报错 → 如实判失败 ─────────────────────

class TestSolveProfileRecheck:
    def test_analyze_true_but_engine_error_fails(self, adapter, tmp_path):
        """pyaedt 吞异常打 "solved correctly"（analysis.py:2098）的假绿
        形态：analyze True + profile Engine Detected Error → success=False，
        且错误消息合并磁盘 .profile 的 "***" 引擎诊断行。"""
        results = tmp_path / "proj.aedtresults" / "d.results"
        results.mkdir(parents=True)
        (results / "DV1_S1_V1.profile").write_text(_R4_FAIL_SNIPPET, encoding="utf-8")
        fake = _FakeHfss(
            profiles=_FakeProfiles({"s1": _FakeSimProfile("Engine Detected Error")}),
            project_path=tmp_path, project_name="proj", design_name="d",
        )

        def _analyze(name, blocking=True):
            return True

        fake.analyze_setup = _analyze
        adapter.session.hfss = fake
        report = adapter.solve("Setup", timeout_s=30)
        assert report.success is False
        assert "Engine Detected Error" in report.message
        assert "solved inside material" in report.message

    def test_analyze_false_fails(self, adapter):
        fake = _FakeHfss()
        fake.analyze_setup = lambda name, blocking=True: False
        adapter.session.hfss = fake
        report = adapter.solve("Setup", timeout_s=30)
        assert report.success is False

    def test_healthy_solve_passes(self, adapter):
        fake = _FakeHfss(
            profiles=_FakeProfiles({"s1": _FakeSimProfile("Normal Completion")}),
            setup=_FakeSetup(is_solved=True, profile=None),
        )
        fake.analyze_setup = lambda name, blocking=True: True
        adapter.session.hfss = fake
        report = adapter.solve("Setup", timeout_s=30)
        assert report.success is True


# ─── export_touchstone：断言必须挡在 ExportNetworkData 之前 ─────────────────

class TestExportTouchstoneGate:
    def test_export_blocked_before_export_call(self, adapter):
        """r2-r4 挂起形态：未完成即导出 → 现在断言先行，
        osolution.ExportNetworkData 零触碰（绝不读中间数据）。"""
        fake = _FakeHfss(
            profiles=_FakeProfiles({"s1": _FakeSimProfile("Engine Detected Error")}),
        )
        fake.get_setups = lambda: ["Setup"]
        fake.get_sweeps = lambda name: ["Sweep"]
        fake.ports = ["P1", "P2"]
        adapter.session.hfss = fake
        with pytest.raises(SimulationFailedError):
            adapter.export_touchstone(Path("does_not_matter.s2p"))
        assert fake.osolution.export_calls == 0

    def test_export_gate_not_connected(self, adapter):
        adapter.session.hfss = None
        with pytest.raises(ModelBuildError):
            adapter.export_touchstone(Path("x.s2p"))
