"""T-Q26a HFSS 护栏三件钉（Q-X1 席，晶圆键合外部使用者实测反馈 P0 三坑）。

反馈源：D:/晶圆键合/rfauto_反馈与实测经验.md §3 P0 + §5 复现片段
（外部建模使用者借 rfauto venv 直调 PyAEDT 实测，2026-11-06）：

1. **坑①积分线表达式字符串**（§5 片段①）：``wave_port(integration_line=
   [["-L_cav/2", ...]])`` → AEDTRuntimeError 'Failed to create boundary
   Wave Port' 且 traceback 指向 material 检查误导排查——护栏=
   ``hfss_session.validate_integration_line`` 数值前置校验（ValueError=
   参数错误，先于任何 pyaedt 边界调用）；
2. **坑② sweep 重名静默改名**（§5 片段②）：``create_linear_count_sweep``
   重名时 AEDT 静默改名（Sweep → Sweep_NVR7O5）→ ``export_touchstone
   ("Setup1","Sweep")`` 报底层 gRPC 'solution not found'——护栏=
   ``resolve_sweep_actual_name``（创建侧捕获改名）+ ``resolve_export_sweep_name``
   （导出侧实名核对/单 sweep 自动/多 sweep 拒绝列候选）；
3. **坑③非 ASCII 路径无提示**（§5 片段④）：中文路径 OpenProject 直接
   GrpcApiError 且无"路径含非 ASCII"提示——护栏=``infra.ascii_paths.
   ensure_ascii_workdir``（%TEMP%/<sha8> 映射，拷回责任在调用方）+
   ``rfauto doctor`` 工作目录 ASCII 检查项。

全 mock 零真机（pyaedt 禁 import，HFSS 禁启——单测禁真打硬规则）；
反馈 §5 片段以 mock 形态复现并钉护栏拦截（错误类型+文案断言）。
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.adapters.hfss_adapter import HfssAdapter
from rfauto.adapters.hfss_session import (
    HfssSession,
    normalize_sweep_names,
    resolve_export_sweep_name,
    resolve_sweep_actual_name,
    validate_integration_line,
)
from rfauto.infra.ascii_paths import (
    ascii_path_report,
    ascii_workdir_target,
    ensure_ascii_workdir,
    is_ascii_path,
)

# ─── 反馈 §5 片段原样常量（mock 复现的输入面） ────────────────────────────────

#: §5 片段①：表达式字符串积分线（真实故障入参，逐字保留）
_REPRO_EXPRESSION_LINE = [
    ["-L_cav/2", "0mm", "-H_cav/2"],
    ["-L_cav/2", "0mm", "H_cav/2"],
]

#: 反馈 §3.1 的成功形态：数值坐标（按 model_units 解释）
_NUMERIC_LINE = [[-2.5, 0.0, -0.2], [-2.5, 0.0, 0.2]]


# ─── 护栏 1：integration_line 数值前置校验 ────────────────────────────────────

class _FakePyaedtBoundary:
    """模拟 pyaedt wave_port/lumped_port：被调用即抛反馈实测形态错误。"""

    def __init__(self, msg: str = "AEDTRuntimeError: Failed to create "
                 "boundary Wave Port P1"):
        self.calls: list[dict] = []
        self._msg = msg

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError(self._msg)


class TestIntegrationLineValidation:
    def test_repro_expression_string_rejected_with_exact_message(self):
        """反馈 §5 片段① mock 复现：表达式字符串 → ValueError（参数错误），
        文案含规定前缀 + 肇事项原文。"""
        with pytest.raises(ValueError) as ei:
            validate_integration_line(_REPRO_EXPRESSION_LINE)
        msg = str(ei.value)
        assert ("integration_line must be numeric coordinates in model "
                "units") in msg
        assert "'-L_cav/2'" in msg
        assert "material" in msg, "文案须带误导性 traceback 说明（修正指引）"

    def test_guard_precedes_pyaedt_boundary_call(self):
        """坑①核心语义：护栏先于 pyaedt——按'先校验后赋端口'编排时
        wave_port 不被触达，误导性 AEDTRuntimeError 不再出现。"""
        wave_port = _FakePyaedtBoundary()
        line = _REPRO_EXPRESSION_LINE
        with pytest.raises(ValueError):
            validate_integration_line(line)  # 护栏（先）
            wave_port(integration_line=line)  # 不应到达
        assert wave_port.calls == [], "护栏未前置——pyaedt 被触达即坑①复现"

    def test_numeric_coordinates_accepted(self):
        """反馈 §3.1 成功形态（数值坐标）放行；int/float 混排均可。"""
        assert validate_integration_line(_NUMERIC_LINE) is None
        assert validate_integration_line([[0, 0, 0], [1.5, 2, 0.25]]) is None

    def test_passthrough_none_and_direction_forms(self):
        """None 与方向式积分线（pyaedt Gravity 枚举/方向串）直通不校验。"""
        assert validate_integration_line(None) is None
        assert validate_integration_line("ZPos") is None

        class _GravityLike:  # 模拟 pyaedt Gravity 枚举成员
            pass

        sentinel = _GravityLike()
        assert validate_integration_line(sentinel) is None

    def test_bool_item_rejected(self):
        """bool 是 int 子类——显式拒绝（True 静默当 1.0 即坐标污染）。"""
        with pytest.raises(ValueError, match="numeric coordinates"):
            validate_integration_line([[True, 0.0, 0.0], [1.0, 2.0, 3.0]])

    def test_lumped_port_param_name_in_message(self):
        """lumped_port 同口径：自定义 param 名进文案（同一校验器两端口共用）。"""
        with pytest.raises(ValueError) as ei:
            validate_integration_line(_REPRO_EXPRESSION_LINE,
                                      param="lumped integration_line")
        assert "lumped integration_line must be numeric" in str(ei.value)

    def test_structure_errors_explicit(self):
        """非两点形态/点内坐标数错误 → 结构指引 ValueError（不落到 pyaedt）。"""
        with pytest.raises(ValueError, match="两点"):
            validate_integration_line([1.0, 2.0, 3.0])  # 扁平非嵌套
        with pytest.raises(ValueError, match="2-3 个坐标项"):
            validate_integration_line([[1.0, 0.0], [2.0, 3.0, 4.0, 5.0]])


# ─── 护栏 2：sweep 重名捕获 + 导出自动解析 ────────────────────────────────────

class _FakeSimProfile:
    def __init__(self, status: str):
        self.status = status


class _FakeProfiles(dict):
    pass


class _FakeSetupSolved:
    is_solved = True

    def get_profile(self):
        return None


class _FakeHfssExport:
    """导出面假会话（绿 profile + 可配置 setup/sweep 名单，str 双形态之一）。"""

    are_there_simulations_running = False

    def __init__(self, sweeps, setups=("Setup1",), ports=("P1", "P2")):
        self._sweeps = list(sweeps)
        self._setups = list(setups)
        self.ports = list(ports)
        self.osolution = object()
        self.working_directory = None
        self.project_path = None
        self.project_name = "proj"
        self.design_name = "d"

    def get_profile(self, name):
        return _FakeProfiles({"s1": _FakeSimProfile("Normal Completion")})

    def get_setup(self, name):
        return _FakeSetupSolved()

    def get_setups(self):
        return self._setups

    def get_sweeps(self, name):
        return self._sweeps


class _FakeSweepObj:
    """SweepHFSS 形态最小仿真（带 .name）。"""

    def __init__(self, name: str):
        self.name = name


class _FakeHfssSetup:
    """configure_setup 面假会话：create_setup/create_linear_count_sweep 记账。"""

    def __init__(self, sweep_names_after):
        self.sweep_names_after = list(sweep_names_after)
        self.created_sweeps: list[dict] = []

    def create_setup(self, name="Setup1", **kwargs):
        class _S:
            def __init__(self):
                self.props: dict = {}

            def update(self):
                return True

        return _S()

    def create_linear_count_sweep(self, **kwargs):
        self.created_sweeps.append(kwargs)
        return True  # 旧 pyaedt bool 形态（改名只能靠 get_sweeps 兜）

    def get_sweeps(self, name):
        return list(self.sweep_names_after)


@pytest.fixture()
def adapter():
    HfssSession.reset()
    a = HfssAdapter()
    yield a
    HfssSession.reset()


def _patch_direct_export(monkeypatch):
    """把 ExportNetworkData 换成记账桩（记 (setup, sweep)，落占位文件）。"""
    calls: list[tuple[str, str | None, Path]] = []

    def _fake_export(hfss, setup_name, sweep_name, path):
        calls.append((setup_name, sweep_name, Path(path)))
        Path(path).write_text("# GHz S MA R 50\n", encoding="ascii")

    monkeypatch.setattr(HfssAdapter, "_direct_export_touchstone",
                        staticmethod(_fake_export))
    return calls


class TestExportSweepResolution:
    def test_single_sweep_auto_used(self, adapter, monkeypatch, tmp_path):
        """sweep=None + 单 sweep → 自动采用（既有行为回归钉）。"""
        adapter.session.hfss = _FakeHfssExport(["Sweep1"])
        calls = _patch_direct_export(monkeypatch)
        out = adapter.export_touchstone(tmp_path / "params.s2p")
        assert out == tmp_path / "params.s2p"
        assert calls and calls[0][1] == "Sweep1"

    def test_multi_sweep_requires_explicit_with_candidates(
            self, adapter, monkeypatch, tmp_path):
        """sweep=None + 多 sweep → ValueError '请显式指定' + 列候选名
        （旧径静默取第一个=坑②病灶形态，绝不回流）。"""
        adapter.session.hfss = _FakeHfssExport(["SweepA", "SweepB"])
        with pytest.raises(ValueError) as ei:
            adapter.export_touchstone(tmp_path / "params.s2p")
        msg = str(ei.value)
        assert "请显式指定" in msg
        assert "SweepA" in msg and "SweepB" in msg

    def test_repro_renamed_sweep_explicit_name_lists_candidates(
            self, adapter, monkeypatch, tmp_path):
        """反馈 §5 片段② mock 复现：请求名 'Sweep' 已被静默改名
        （实际 'Sweep_NVR7O5'）→ ValueError 列候选 + 改名指引，
        绝不落到 gRPC 'solution not found'。"""
        adapter.session.hfss = _FakeHfssExport(["Sweep_NVR7O5"])
        with pytest.raises(ValueError) as ei:
            adapter.export_touchstone(tmp_path / "params.s2p", sweep="Sweep")
        msg = str(ei.value)
        assert "Sweep_NVR7O5" in msg, "候选名（实际名）必须进文案"
        assert "静默改名" in msg, "改名指引必须进文案"
        assert "solution not found" in msg

    def test_explicit_actual_sweep_exports(self, adapter, monkeypatch,
                                           tmp_path):
        """显式给实际名（改名后）→ 放行导出，sweep 名逐字传递。"""
        adapter.session.hfss = _FakeHfssExport(["Sweep_NVR7O5"])
        calls = _patch_direct_export(monkeypatch)
        adapter.export_touchstone(tmp_path / "params.s2p",
                                  sweep="Sweep_NVR7O5")
        assert calls and calls[0][1] == "Sweep_NVR7O5"

    def test_unknown_setup_lists_candidates(self, adapter, tmp_path):
        """setup 显式指定但不存在 → ValueError 列候选（实名核对对称面）。"""
        adapter.session.hfss = _FakeHfssExport(["Sweep1"],
                                               setups=("Setup1", "Setup2"))
        with pytest.raises(ValueError, match=r"Setup9.*Setup1"):
            adapter.export_touchstone(tmp_path / "params.s2p", setup="Setup9")

    def test_zero_sweeps_falls_back_to_setup_solution(self, adapter,
                                                      monkeypatch, tmp_path):
        """零 sweep → sweep_name=None（setup 主解口径，既有行为不变）。"""
        adapter.session.hfss = _FakeHfssExport([])
        calls = _patch_direct_export(monkeypatch)
        adapter.export_touchstone(tmp_path / "params.s2p")
        assert calls and calls[0][1] is None


class TestConfigureSetupRenameCapture:
    def test_repro_rename_captured_and_warned(self, adapter, caplog):
        """反馈 §5 片段②创建侧 mock 复现：请求 'Sweep'、AEDT 实际
        'Sweep_NVR7O5' → 实际名被解析 + warning 带两侧名字（旧径静默）。"""
        hfss = _FakeHfssSetup(["Sweep_NVR7O5"])
        adapter.session.hfss = hfss
        with caplog.at_level(logging.WARNING):
            adapter.configure_setup({"sweep_name": "Sweep"})
        # 请求名原样传 pyaedt（创建语义不变），实际名靠解析捕获
        assert hfss.created_sweeps[0]["name"] == "Sweep"
        assert "Sweep_NVR7O5" in caplog.text
        assert "Sweep" in caplog.text

    def test_no_rename_no_warning(self, adapter, caplog):
        """无重名（请求名在列）→ 零告警，行为不变。"""
        hfss = _FakeHfssSetup(["Sweep1"])
        adapter.session.hfss = hfss
        with caplog.at_level(logging.WARNING):
            adapter.configure_setup({"sweep_name": "Sweep1"})
        assert "改名" not in caplog.text

    def test_get_sweeps_absent_falls_back(self, adapter):
        """旧 fake 形态（无 get_sweeps）→ best-effort 回退请求名，不炸
        （改名捕获是观测面，不阻塞创建主流程）。"""

        class _NoSweepsHfss(_FakeHfssSetup):
            def get_sweeps(self, name):
                raise RuntimeError("gRPC blip")

        hfss = _NoSweepsHfss([])
        adapter.session.hfss = hfss
        adapter.configure_setup({"sweep_name": "Sweep1"})  # 不抛即通过
        assert hfss.created_sweeps[0]["name"] == "Sweep1"


class TestSweepHelpers:
    def test_normalize_mixed_shapes(self):
        """str 与对象 .name 双形态归一；无名对象/异常跳过（best-effort）。"""
        assert normalize_sweep_names(["A", _FakeSweepObj("B"), None,
                                      object()]) == ["A", "B"]
        assert normalize_sweep_names(None) == []
        assert normalize_sweep_names([]) == []

    def test_resolve_actual_name_from_created_object(self, caplog):
        """SweepHFSS 形态（.name 可取）→ 直接用实际名 + 改名 warning。"""
        with caplog.at_level(logging.WARNING):
            actual = resolve_sweep_actual_name(
                _FakeHfssSetup([]), "Setup1", "Sweep",
                created=_FakeSweepObj("Sweep_NVR7O5"))
        assert actual == "Sweep_NVR7O5"
        assert "Sweep_NVR7O5" in caplog.text

    def test_resolve_requested_present_returns_requested(self):
        hfss = _FakeHfssSetup(["Sweep"])
        assert resolve_sweep_actual_name(hfss, "Setup1", "Sweep") == "Sweep"

    def test_resolve_rename_prefix_single_candidate(self):
        """AEDT 改名惯例 <原名>_<随机后缀>：唯一前缀候选即实际名。"""
        hfss = _FakeHfssSetup(["Sweep_NVR7O5", "Other"])
        assert resolve_sweep_actual_name(hfss, "Setup1", "Sweep") == \
            "Sweep_NVR7O5"

    def test_resolve_ambiguous_prefix_falls_back_to_requested(self):
        """多个 <原名>_ 候选（跨代累积工程）→ 不猜，回退请求名。"""
        hfss = _FakeHfssSetup(["Sweep_AAA", "Sweep_BBB"])
        assert resolve_sweep_actual_name(hfss, "Setup1", "Sweep") == "Sweep"

    def test_resolve_query_failure_falls_back(self):
        """get_sweeps 抛错 → 回退请求名（观测面不阻塞主流程）。"""

        class _Boom:
            def get_sweeps(self, name):
                raise RuntimeError("gRPC blip")

        assert resolve_sweep_actual_name(_Boom(), "Setup1", "Sweep") == "Sweep"

    def test_export_resolver_single_and_multi(self):
        """单 sweep 自动采用；多 sweep ValueError 列候选（含候选名单）。"""
        assert resolve_export_sweep_name(
            _FakeHfssExport(["S1"]), "Setup1") == "S1"
        with pytest.raises(ValueError, match=r"S1.*S2|S2.*S1"):
            resolve_export_sweep_name(_FakeHfssExport(["S1", "S2"]), "Setup1")

    def test_export_resolver_object_form_sweeps(self):
        """get_sweeps 返回对象列表（pyaedt 对象形态）→ 归一后自动采用。"""

        class _ObjSweeps(_FakeHfssExport):
            def get_sweeps(self, name):
                return [_FakeSweepObj("Sweep1")]

        assert resolve_export_sweep_name(_ObjSweeps([]), "Setup1") == "Sweep1"


# ─── 护栏 3：ensure_ascii_workdir + doctor 工作目录 ASCII 检查 ────────────────

class TestEnsureAsciiWorkdir:
    def test_is_ascii_path_predicate(self):
        assert is_ascii_path("E:/rfauto_workspace") is True
        assert is_ascii_path("D:/晶圆键合/proj.aedt") is False

    def test_ascii_path_returned_unchanged_no_side_effect(self, tmp_path):
        """全 ASCII → 原样返回（不建目录、不改写——调用方语义零变化）。"""
        src = tmp_path / "wb_plain"
        work = ensure_ascii_workdir(src)
        assert work == src
        assert not work.exists(), "ASCII 路径不得有建目录副作用"

    def test_repro_non_ascii_path_mapped_to_temp(self):
        """反馈 §5 片段④ mock 形态：中文路径（D:/晶圆键合/…）→ 映射到
        %TEMP%/rfauto_ascii_<sha8>，目录名恒 ASCII、确定性、幂等创建。"""
        src = "D:/晶圆键合/demo.aedt"
        work = ensure_ascii_workdir(src)
        try:
            assert work == ascii_workdir_target(src)
            assert work.is_dir(), "映射目录须建好（mkdir parents exist_ok）"
            assert "rfauto_ascii_" in work.name
            assert is_ascii_path(str(work)), "映射后整条路径须全 ASCII"
            assert work.parent == Path(tempfile.gettempdir()), \
                "映射目标须在 %TEMP% 直下"
            # 确定性：同一原路径跨调用恒同一映射目录（reopen 语义成立）
            assert ensure_ascii_workdir(src) == work
        finally:
            work.rmdir()  # 会话一次性产物，用毕即删（根目录纪律同源）

    def test_report_offenders_and_suggestion(self):
        report = ascii_path_report("D:/晶圆键合/x")
        assert report["ascii"] is False
        assert "晶" in report["bad_chars"]
        assert report["mapped_dir"] is not None
        assert "ensure_ascii_workdir" in report["suggestion"]

    def test_report_ascii_path_clean(self, tmp_path):
        report = ascii_path_report(tmp_path)
        assert report["ascii"] is True
        assert report["bad_chars"] == []
        assert report["mapped_dir"] is None

    def test_mapped_target_is_pure_function(self):
        """ascii_workdir_target 只算不建（doctor 报告面无副作用）。"""
        target = ascii_workdir_target("D:/晶圆键合/never_created")
        assert not target.exists()


class TestDoctorAsciiCheck:
    def test_doctor_includes_ascii_check_ok(self, tmp_path, monkeypatch):
        """service doctor()：ASCII cwd（tmp_path）→ '工作目录 ASCII' 项
        status=ok，detail 为 cwd 原文。"""
        from rfauto.service.api import doctor as doctor_service

        monkeypatch.chdir(tmp_path)
        result = doctor_service()
        check = next(c for c in result["checks"]
                     if c["name"] == "工作目录 ASCII")
        assert check["status"] == "ok"
        assert check["detail"] == str(tmp_path)

    def test_doctor_non_ascii_cwd_warns_with_guidance(self, tmp_path,
                                                      monkeypatch):
        """反馈 §5 片段④ doctor 面 mock 复现：非 ASCII cwd → 项非 ok，
        detail 含肇事字符 + ensure_ascii_workdir 映射指引（拷回责任入文案）。"""
        from rfauto.service.api import doctor as doctor_service

        bad = tmp_path / "晶圆键合"
        bad.mkdir()
        monkeypatch.chdir(bad)
        result = doctor_service()
        check = next(c for c in result["checks"]
                     if c["name"] == "工作目录 ASCII")
        assert check["status"] != "ok"
        assert "ensure_ascii_workdir" in check["detail"]
        assert "晶" in check["detail"]
        assert "拷回" in check["detail"]

    def test_doctor_cli_json_lists_ascii_check(self, tmp_path, monkeypatch):
        """CLI doctor --json：ASCII 检查项入信封 checks（既有渲染形态，
        零新 CLI 叶）。"""
        from rfauto.cli.main import app as cli_app

        runner = CliRunner()
        monkeypatch.setenv("RFAUTO_AEDT_PATH", str(tmp_path))
        monkeypatch.setenv("RFAUTO_HPEESOF_DIR", str(tmp_path))
        result = runner.invoke(cli_app, ["doctor", "--json"])
        assert result.exit_code == 0, result.output
        assert "工作目录 ASCII" in result.output

    def test_doctor_envelope_ok_flips_on_non_ascii(self, tmp_path,
                                                   monkeypatch):
        """信封一致性：非 ASCII cwd 且其余探测全绿 → envelope ok=False
        （'全绿才 True' 注记契约保持）。"""
        from rfauto.service.api import doctor as doctor_service

        bad = tmp_path / "晶圆键合2"
        bad.mkdir()
        monkeypatch.chdir(bad)
        monkeypatch.setenv("RFAUTO_AEDT_PATH", str(bad))  # 存在目录 → AEDT 绿
        monkeypatch.setenv("RFAUTO_HPEESOF_DIR", str(bad))  # ADS 绿
        result = doctor_service()
        others = [c for c in result["checks"] if c["name"] != "工作目录 ASCII"]
        assert all(c["status"] == "ok" for c in others), \
            "前置条件：其余检查全绿（否则本钉无判别力）"
        assert result["ok"] is False
