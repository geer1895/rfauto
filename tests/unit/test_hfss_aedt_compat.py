"""AEDT 导入兼容回归钉（aurora_q T-Q17②③④，全 mock 零真机零网络）。

② 版本切换丢路径：``_prune_ansysem_env`` 先验证后删除 + 快照恢复——
   切换目标版本不可用时不破坏既有注册路径（外部用户 2022 R2 实证回归钉：
   UI 缺省 2025.1 与实装版本不一致时，唯一有效路径曾被剪掉且不恢复）；
③ COM 回退通道：gRPC 连接类失败 → ``use_grpc_api=False`` 重试一次，回退态
   会话释放即恢复，缺省 gRPC 路径零变化，远程分支不回退；
④ 缺装优雅降级：ModuleNotFoundError → 携带 ``pip install -e ".[hfss]"``
   指引的失败信封（adapter 错误消息 + CLI --json error_envelope）。

单测纪律：③④ 用例对 pyaedt settings 的依赖与 test_hfss_import.py 同款
（无 skip 标记，缺装即错——不扩大 skip 清单）；②④ 的纯离线路径不触
pyaedt import。禁真机 ansysedt 启动（#139）。
"""

from __future__ import annotations

import json
import os
from typing import Any, ClassVar

import pytest

from rfauto.adapters import hfss_import

# ─── 受控环境夹具 ─────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_aedt_env(monkeypatch):
    """受控 ANSYSEM_ROOT 环境：剥离真机变量，只留 2025R1 注册路径（fake 值）。

    monkeypatch 收口恢复：delenv/setenv 的真机原值测试后逐键还原。"""
    for k in list(os.environ):
        if k.startswith("ANSYSEM_ROOT"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANSYSEM_ROOT251", "E:/fake/v251/AnsysEM")
    return {"old_var": "ANSYSEM_ROOT251",
            "old_value": "E:/fake/v251/AnsysEM"}


class _FlagGuard:
    """use_grpc_api 观测窗：current 读当前值，original 存测试前基线。"""

    def __init__(self, settings: Any, original: Any):
        self.settings = settings
        self.original = original

    @property
    def use_grpc_api(self) -> Any:
        return self.settings.use_grpc_api


@pytest.fixture()
def grpc_flag_guard() -> _FlagGuard:
    """use_grpc_api 会话卫生：记录原值，测试后强制恢复（防回退翻转泄漏）。"""
    from ansys.aedt.core.generic.settings import settings as aedt_settings

    guard = _FlagGuard(aedt_settings, aedt_settings.use_grpc_api)
    yield guard
    aedt_settings.use_grpc_api = guard.original
    hfss_import._COM_FALLBACK_STATE.update(active=False, previous=None)


class _MinimalHfss:
    """只读采集面的最小替身（变量面为空即可，spec 采集全部 best-effort）。"""

    design_name = "Design1"
    variable_manager = None
    setups: ClassVar[list] = []
    boundaries: ClassVar[list] = []
    parametrics: ClassVar[list] = []

    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs
        from ansys.aedt.core.generic.settings import settings as aedt_settings

        self.grpc_at_ctor = aedt_settings.use_grpc_api

    def autosave_disable(self):
        return None

    def release_desktop(self, close_projects=True, close_desktop=True):
        return True


def _write_project(tmp_path, name="fake.aedt"):
    project = tmp_path / name
    project.write_text("", encoding="utf-8")
    return str(project)


# ─── ② 版本切换不丢已注册路径 ─────────────────────────────────────────────────


class TestVersionSwitchKeepsRegisteredPath:
    def test_prune_skips_when_target_version_missing(self, fake_aedt_env):
        """先验证后删除：目标版本环境变量不存在 → 零删除（2025R1 路径原样）。"""
        removed = hfss_import._prune_ansysem_env("2022.2")
        assert removed == {}
        assert os.environ[fake_aedt_env["old_var"]] == fake_aedt_env["old_value"]

    def test_prune_snapshots_and_removes_only_conflicts(
            self, monkeypatch, fake_aedt_env):
        """两版本并存：只删冲突项且快照可恢复；目标版本路径不动。"""
        monkeypatch.setenv("ANSYSEM_ROOT222", "D:/Program Files/AnsysEM 222")
        removed = hfss_import._prune_ansysem_env("2025.1")
        assert removed == {"ANSYSEM_ROOT222": "D:/Program Files/AnsysEM 222"}
        assert "ANSYSEM_ROOT222" not in os.environ
        assert os.environ[fake_aedt_env["old_var"]] == fake_aedt_env["old_value"]
        hfss_import._restore_ansysem_env(removed)
        assert os.environ["ANSYSEM_ROOT222"] == "D:/Program Files/AnsysEM 222"

    def test_version_switch_failure_keeps_2025r1_path(
            self, monkeypatch, fake_aedt_env, tmp_path):
        """任务书冻结场景回归钉：注册 2025R1 → 切 2022R2 → 失败 → 路径仍在。

        2022R2 未注册（ROOT222 不存在）：先验证后删除使剪枝整体跳过。"""
        project = _write_project(tmp_path)

        def _fail_open(*a, **kw):
            raise ConnectionError("Failed to connect to AEDT via gRPC.")

        monkeypatch.setattr(hfss_import, "_open_hfss", _fail_open)
        spec = hfss_import.import_project_spec(project, version="2022.2")
        assert spec["ok"] is False
        assert "打开 HFSS 工程失败" in spec["error"]
        assert os.environ.get(fake_aedt_env["old_var"]) == fake_aedt_env["old_value"]

    def test_version_switch_failure_restores_pruned_old_path(
            self, monkeypatch, fake_aedt_env, tmp_path):
        """两版本并存 + 切换失败：被剪枝的 2025R1 路径恢复回进程环境。"""
        monkeypatch.setenv("ANSYSEM_ROOT222", "D:/Program Files/AnsysEM 222")
        project = _write_project(tmp_path)

        def _fail_open(*a, **kw):
            # 构造窗口内：旧版本路径已被剪掉（会话作用域语义成立的前提）
            assert fake_aedt_env["old_var"] not in os.environ
            raise ConnectionError("Failed to connect to AEDT via gRPC.")

        monkeypatch.setattr(hfss_import, "_open_hfss", _fail_open)
        spec = hfss_import.import_project_spec(project, version="2022.2")
        assert spec["ok"] is False
        assert os.environ.get(fake_aedt_env["old_var"]) == fake_aedt_env["old_value"]

    def test_readonly_switch_failure_restores_old_path(
            self, monkeypatch, fake_aedt_env, tmp_path):
        """只读链同口径：worker 收尾恢复剪枝快照（join 后断言，确定性）。"""
        monkeypatch.setenv("ANSYSEM_ROOT222", "D:/Program Files/AnsysEM 222")
        project = _write_project(tmp_path, "ro.aedt")

        def _fail_open(*a, **kw):
            raise ConnectionError("Failed to connect to AEDT via gRPC.")

        monkeypatch.setattr(hfss_import, "_open_hfss_readonly", _fail_open)
        spec = hfss_import.import_project_spec_readonly(project,
                                                        version="2022.2")
        assert spec["ok"] is False
        assert os.environ.get(fake_aedt_env["old_var"]) == fake_aedt_env["old_value"]

    def test_success_scoped_restore_after_release(
            self, monkeypatch, fake_aedt_env, tmp_path):
        """成功路径同样会话作用域恢复：进程环境零遗留（先后两版本互不吞）。"""
        monkeypatch.setenv("ANSYSEM_ROOT222", "D:/Program Files/AnsysEM 222")
        project = _write_project(tmp_path, "ok.aedt")
        monkeypatch.setattr(hfss_import, "_open_hfss",
                            lambda *a, **kw: _MinimalHfss())
        spec = hfss_import.import_project_spec(project, version="2025.1")
        assert spec["ok"] is True, spec.get("error")
        assert os.environ.get("ANSYSEM_ROOT222") == "D:/Program Files/AnsysEM 222"

    def test_prune_default_version_missing_keeps_everything(
            self, monkeypatch, fake_aedt_env):
        """UI 缺省 2025.1 × 实装 2022.2（外部用户实证形态）：唯一路径不被剪。"""
        monkeypatch.delenv("ANSYSEM_ROOT251", raising=False)
        monkeypatch.setenv("ANSYSEM_ROOT222", "D:/Program Files/AnsysEM 222")
        removed = hfss_import._prune_ansysem_env("2025.1")
        assert removed == {}
        assert os.environ["ANSYSEM_ROOT222"] == "D:/Program Files/AnsysEM 222"


# ─── ③ COM 回退通道 ───────────────────────────────────────────────────────────


class TestConnectionErrorClassifier:
    @pytest.mark.parametrize("exc", [
        ConnectionError("Failed to connect to AEDT via gRPC."),
        RuntimeError("gRPC timeout waiting for channel"),
        Exception("GrpcApiError-like"),  # 消息含 grpc（消息面归一匹配）
    ])
    def test_connection_class_detected(self, exc):
        assert hfss_import._is_grpc_connection_error(exc) is True

    @pytest.mark.parametrize("exc", [
        ValueError("工程文件不存在"),
        OSError("磁盘满"),
        hfss_import.HfssDependencyMissing("未检测到 PyAEDT"),
    ])
    def test_non_connection_class_not_matched(self, exc):
        assert hfss_import._is_grpc_connection_error(exc) is False


class TestComFallback:
    def test_grpc_failure_falls_back_to_com(
            self, monkeypatch, grpc_flag_guard, fake_aedt_env, tmp_path):
        """gRPC 连接类失败 → use_grpc_api=False 第二路被调用 → 释放后恢复。"""
        import ansys.aedt.core as aedt_core

        attempts: list[_MinimalHfss] = []

        class _FirstFails(_MinimalHfss):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                attempts.append(self)
                if len(attempts) == 1:
                    raise ConnectionError("Failed to connect to AEDT via gRPC.")

        monkeypatch.setattr(aedt_core, "Hfss", _FirstFails)
        monkeypatch.setattr(hfss_import, "_com_channel_available",
                            lambda: True)  # 与真机 pythonnet 有无解耦
        project = _write_project(tmp_path, "com.aedt")
        before = grpc_flag_guard.original

        spec = hfss_import.import_project_spec(project)

        assert spec["ok"] is True, spec.get("error")
        assert len(attempts) == 2
        assert attempts[0].grpc_at_ctor == before   # 第一路=缺省 gRPC 语义（零变化）
        assert attempts[1].grpc_at_ctor is False    # 第二路=COM（翻转生效）
        assert attempts[1].kwargs == attempts[0].kwargs  # 参数原样透传
        # 会话释放后回退态恢复（运行期读点随会话存活，不能中途翻回）
        assert grpc_flag_guard.use_grpc_api == before
        assert hfss_import._COM_FALLBACK_STATE["active"] is False

    def test_readonly_grpc_failure_falls_back_to_com(
            self, monkeypatch, grpc_flag_guard, fake_aedt_env, tmp_path):
        """只读链同口径：副本语义保持（new_desktop/close_on_exit/remove_lock）。"""
        import ansys.aedt.core as aedt_core

        attempts: list[_MinimalHfss] = []

        class _FirstFails(_MinimalHfss):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                attempts.append(self)
                if len(attempts) == 1:
                    raise ConnectionError("Failed to connect to AEDT via gRPC.")

        monkeypatch.setattr(aedt_core, "Hfss", _FirstFails)
        monkeypatch.setattr(hfss_import, "_com_channel_available", lambda: True)
        project = _write_project(tmp_path, "com_ro.aedt")

        spec = hfss_import.import_project_spec_readonly(project, timeout_s=30.0)

        assert spec["ok"] is True, spec.get("error")
        assert len(attempts) == 2
        assert attempts[1].kwargs["new_desktop"] is True
        assert attempts[1].kwargs["close_on_exit"] is False
        assert attempts[1].kwargs["remove_lock"] is False

    def test_non_connection_error_no_fallback(
            self, monkeypatch, grpc_flag_guard, fake_aedt_env, tmp_path):
        """非连接类失败（坏工程等）：不回退，原错误透传（行为零变化）。"""
        import ansys.aedt.core as aedt_core

        calls: list[int] = []

        class _Boom:
            def __init__(self, **kwargs):
                calls.append(1)
                raise ValueError("无效工程文件")

        monkeypatch.setattr(aedt_core, "Hfss", _Boom)
        monkeypatch.setattr(hfss_import, "_com_channel_available", lambda: True)
        project = _write_project(tmp_path, "bad.aedt")

        spec = hfss_import.import_project_spec(project)

        assert spec["ok"] is False
        assert "打开 HFSS 工程失败" in spec["error"]
        assert "无效工程文件" in spec["error"]
        assert len(calls) == 1
        assert grpc_flag_guard.use_grpc_api == grpc_flag_guard.original  # 未翻转
        assert hfss_import._COM_FALLBACK_STATE["active"] is False

    def test_both_channels_fail_reports_both_attempts(
            self, monkeypatch, grpc_flag_guard, fake_aedt_env, tmp_path):
        """双通道均失败：错误携带两次尝试诊断，回退态即时恢复。"""
        import ansys.aedt.core as aedt_core

        class _BothFail(_MinimalHfss):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                if self.grpc_at_ctor is not False:
                    raise ConnectionError("Failed to connect to AEDT via gRPC.")
                raise OSError("COM 初始化失败")

        monkeypatch.setattr(aedt_core, "Hfss", _BothFail)
        monkeypatch.setattr(hfss_import, "_com_channel_available", lambda: True)
        project = _write_project(tmp_path, "both.aedt")

        spec = hfss_import.import_project_spec(project)

        assert spec["ok"] is False
        assert "gRPC 与 COM 通道均启动失败" in spec["error"]
        assert "ConnectionError" in spec["error"] and "OSError" in spec["error"]
        # COM 失败分支即时恢复全局设置（不留 COM 残态）
        assert grpc_flag_guard.use_grpc_api == grpc_flag_guard.original
        assert hfss_import._COM_FALLBACK_STATE["active"] is False

    def test_com_fallback_skipped_when_channel_unavailable(
            self, monkeypatch, grpc_flag_guard, fake_aedt_env, tmp_path):
        """COM 不可达（非 Windows/pythonnet 缺装）：不空转重试，gRPC 错误原样。"""
        import ansys.aedt.core as aedt_core

        calls: list[int] = []

        class _ConnFail:
            def __init__(self, **kwargs):
                calls.append(1)
                raise ConnectionError("Failed to connect to AEDT via gRPC.")

        monkeypatch.setattr(aedt_core, "Hfss", _ConnFail)
        monkeypatch.setattr(hfss_import, "_com_channel_available", lambda: False)
        project = _write_project(tmp_path, "nocom.aedt")

        spec = hfss_import.import_project_spec(project)

        assert spec["ok"] is False
        assert len(calls) == 1
        assert hfss_import._COM_FALLBACK_STATE["active"] is False

    def test_remote_branch_never_falls_back(
            self, monkeypatch, grpc_flag_guard, fake_aedt_env):
        """远程分支不回退 COM：machine/port 只在 gRPC 通道有意义。"""
        import ansys.aedt.core as aedt_core

        calls: list[int] = []

        class _ConnFail:
            def __init__(self, **kwargs):
                calls.append(1)
                raise ConnectionError("Failed to connect to AEDT via gRPC.")

        def _fake_remote(remote_machine, version):
            return {"name": "lab_server", "machine": "192.0.2.10",
                    "port": 15555, "project_root": "E:/rfauto_remote",
                    "version": version}

        monkeypatch.setattr(aedt_core, "Hfss", _ConnFail)
        monkeypatch.setattr(hfss_import, "_remote_session_info", _fake_remote)
        monkeypatch.setattr(hfss_import, "_com_channel_available", lambda: True)

        spec = hfss_import.import_project_spec(
            "E:/rfauto_remote/proj/remote.aedt", version="2025.1",
            remote_machine="lab_server")

        assert spec["ok"] is False
        assert "打开 HFSS 工程失败" in spec["error"]
        assert len(calls) == 1  # 远程只有一路 gRPC，失败即报
        assert hfss_import._COM_FALLBACK_STATE["active"] is False


# ─── ④ 缺装优雅降级 ───────────────────────────────────────────────────────────


def _raise_missing():
    raise hfss_import.HfssDependencyMissing(
        hfss_import._PYAEDT_INSTALL_GUIDE.format(
            detail="No module named 'ansys'"))


class TestMissingDependencyGuidance:
    def test_import_spec_missing_pyaedt_returns_guidance(
            self, monkeypatch, fake_aedt_env, tmp_path):
        """④ 验收钉：缺装 → 错误信封带 pip install -e ".[hfss]" 指引。"""
        project = _write_project(tmp_path, "m.aedt")
        monkeypatch.setattr(hfss_import, "_import_hfss_cls", _raise_missing)
        spec = hfss_import.import_project_spec(project)
        assert spec["ok"] is False
        assert 'pip install -e ".[hfss]"' in spec["error"]
        assert "pyaedt>=1.9.0,<2" in spec["error"]

    def test_readonly_missing_pyaedt_returns_guidance(
            self, monkeypatch, fake_aedt_env, tmp_path):
        project = _write_project(tmp_path, "m_ro.aedt")
        monkeypatch.setattr(hfss_import, "_import_hfss_cls", _raise_missing)
        spec = hfss_import.import_project_spec_readonly(project)
        assert spec["ok"] is False
        assert 'pip install -e ".[hfss]"' in spec["error"]

    def test_recipe_chain_missing_pyaedt_returns_guidance(
            self, monkeypatch, fake_aedt_env, tmp_path):
        """端到端链（import_project_recipe）：指引随 spec 失败透传。"""
        project = _write_project(tmp_path, "m_recipe.aedt")
        monkeypatch.setattr(hfss_import, "_import_hfss_cls", _raise_missing)
        result = hfss_import.import_project_recipe(project)
        assert result["ok"] is False
        assert 'pip install -e ".[hfss]"' in result["error"]

    def test_real_module_not_found_maps_to_guidance(self):
        """真实 ModuleNotFoundError → _import_hfss_cls 转抛指引（映射端到端）。"""
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "ansys" or name.startswith("ansys."):
                raise ModuleNotFoundError("No module named 'ansys'", name=name)
            return real_import(name, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(builtins, "__import__", _fake_import)
            with pytest.raises(hfss_import.HfssDependencyMissing) as ei:
                hfss_import._import_hfss_cls()
        assert 'pip install -e ".[hfss]"' in str(ei.value)
        assert isinstance(ei.value.__cause__, ModuleNotFoundError)

    def test_cli_hfss_import_json_failure_is_error_envelope(
            self, monkeypatch, fake_aedt_env, tmp_path):
        """④ 信封验收钉：CLI --json 失败信封走 error_envelope 构造器
        （errors=list[str] 含指引；旧单数 error 键不再回传）。"""
        from typer.testing import CliRunner

        from rfauto.cli.main import app as root_app

        project = _write_project(tmp_path, "cli.aedt")
        monkeypatch.setattr(hfss_import, "_import_hfss_cls", _raise_missing)
        result = CliRunner().invoke(
            root_app, ["hfss-import", project, "--json"])
        assert result.exit_code == 1, result.output[:400]
        payload, _ = json.JSONDecoder().raw_decode(
            result.output[result.output.index("{"):])
        assert payload["ok"] is False
        assert isinstance(payload.get("errors"), list)
        assert any('pip install -e ".[hfss]"' in e for e in payload["errors"])
        assert "error" not in payload  # 信封契约：单数 error 不再回传
        assert "spec" in payload and "recipe" in payload  # 明细字段保留

    def test_cli_hfss_import_json_success_envelope_unchanged(
            self, monkeypatch, fake_aedt_env, tmp_path):
        """成功路径零变化钉：--json 成功信封原样透传（不进 error_envelope）。"""
        from typer.testing import CliRunner

        from rfauto.cli.main import app as root_app

        project = _write_project(tmp_path, "cli_ok.aedt")
        ok_result = {"ok": True, "spec": {"design": "D1"},
                     "recipe": {"model": "custom_hfss"}}
        monkeypatch.setattr("rfauto.service.v3_services.hfss_import_recipe",
                            lambda *a, **kw: dict(ok_result))
        result = CliRunner().invoke(
            root_app, ["hfss-import", project, "--json"])
        assert result.exit_code == 0, result.output[:400]
        payload, _ = json.JSONDecoder().raw_decode(
            result.output[result.output.index("{"):])
        assert payload == ok_result
