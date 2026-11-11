"""hfss_migrate（aedt_migrate Stage 1/2 执行器）单元钉——全离线零 AEDT。

钉住契约（蓝图 aedt_migrate §1 Stage 1/2 + 席位任务书）：

1. **cutoff 三态判定**：``is_cutoff_message`` 两针 AND（Jim Sherman 引述
   形态）——正例含换行/大小写漂移、负例（license/锁定/缺文件类单针
   命中）不误判；``open_legacy_project`` 异常串命中 → ``outcome=cutoff``。
2. **原件只读铁律**：SaveAs 路径=migrated/ 且 ≠ 原件；staging 拷贝件
   打开、原 .aedt 字节不动；SaveAs 目标与原件同路径直接拒绝。
3. **validate 解包顺序（晶圆键合 §2.4）**：fake ``validate_full_design``
   返回 ``(messages, ok)`` 双形态—— ``(非空 messages, False)`` 若解包
   反了 messages 当 bool 即假 pass，钉死 outcome。
4. **六项检查清单**：计数可用 / 单项查询异常如实入账（available=False
   + error 原文，不抛）。
5. **会话生命周期（#265）**：注入会话不代关（close 计数=调用方指令）；
   打开失败自建会话就地关；wrapper（migrate_open_save_and_check）
   finally 必关（save=False）+ staging 清理。
6. **SaveAs 显式性**：overwrite=False 目标已存在拒绝（幂等语义）；
   migrated 目录非 ASCII ValueError fail-closed。
7. **Modeler Check 模板守卫**：``run_modeler_check_script`` 未验证即
   NotImplementedError（UNVERIFIED-API 禁执行）。
"""

import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.adapters import hfss_migrate as hm

CUTOFF_QUOTE = (
    "Legacy project files can no longer be opened in this version.\n"
    "Please use release 2023 R2 or earlier to convert this project."
)


class FakeDesktop:
    """模拟 ansys.aedt.core.Desktop：load_project 可编程三态。"""

    def __init__(self, load_result=None, load_raises=None):
        self.load_calls: list[str] = []
        self._load_result = load_result
        self._load_raises = load_raises
        self.odesktop = _FakeOdesktop()
        self.save_calls: list[tuple] = []

    def load_project(self, project_file, design_name=None):
        self.load_calls.append(str(project_file))
        if self._load_raises is not None:
            raise self._load_raises
        return self._load_result

    def save_project(self, project_name=None, project_path=None):
        self.save_calls.append((project_name, str(project_path)))
        Path(project_path).write_bytes(b"migrated-by-desktop")
        return True

    def design_list(self, project=None):
        return ["HFSSDesign1"]


class _FakeOdesktop:
    def GetMessages(self, project, design, severity):
        return [f"sev{severity} message"]


class FakeApp:
    """模拟 pyaedt app 句柄：save_project/validate/清单访问器全 fake。"""

    def __init__(self, validate_return=None, validate_raises=None):
        self.project_name = "legacy_proj"
        self.design_name = "HFSSDesign1"
        self.save_calls: list[str] = []
        self._validate_return = validate_return
        self._validate_raises = validate_raises
        self.materials = _NS(material_keys={"copper": 1, "vacuum": 1})
        self.boundaries = [object(), object(), object()]
        self.mesh = _NS(meshoperations=[object()])
        self.setups = [object()]
        self.parametrics = _NS(setups=[object(), object()])
        self.optimizations = _NS(setups=[])
        self.modeler = _FakeModeler()

    def save_project(self, file_name, overwrite=True, refresh_ids=False):
        self.save_calls.append(str(file_name))
        Path(file_name).write_bytes(b"migrated-by-app")
        return True

    def validate_full_design(self, design=None, output_dir=None, ports=None):
        if self._validate_raises is not None:
            raise self._validate_raises
        return self._validate_return


class _NS:
    """简易命名空间（清单访问器容器）。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeModeler:
    """模拟 GeometryModeler：heal_objects（pyaedt primitives.py:7033 形态）。"""

    def __init__(self):
        self.object_names = ["Box1", "Box2"]
        self.heal_calls: list[str] = []
        self.heal_return = True

    def heal_objects(self, assignment, **_kw):
        self.heal_calls.append(assignment)
        return self.heal_return


class FakeSession:
    """模拟 HfssSession：connect/close 计数（#265 契约钉）。"""

    def __init__(self, desktop=None):
        self.desktop = desktop
        self._connected = False
        self.connect_calls: list[dict] = []
        self.close_calls: list[bool] = []
        self.desktop_pid = 4242

    @property
    def is_connected(self):
        return self._connected and self.desktop is not None

    def connect(self, settings):
        self.connect_calls.append(dict(settings))
        self._connected = True

    def close(self, save=True):
        self.close_calls.append(save)
        self._connected = False


def _write_original(tmp_path, content=b"legacy-project-bytes"):
    original = tmp_path / "legacy_proj.aedt"
    original.write_bytes(content)
    return original


@pytest.fixture()
def fake_session():
    app = FakeApp(validate_return=(["m1", "m2"], True))
    sess = FakeSession(FakeDesktop(load_result=app))
    return sess, app


# ─── 1. cutoff 三态判定 ──────────────────────────────────────────────


class TestCutoffDetection:
    def test_exact_quote_is_cutoff(self):
        assert hm.is_cutoff_message(CUTOFF_QUOTE) is True

    def test_whitespace_and_case_normalized(self):
        text = "legacy   PROJECT\nfiles CAN NO LONGER BE opened in this version"
        assert hm.is_cutoff_message(text) is True

    def test_single_needle_not_cutoff(self):
        # 锁定类报错只含第二针——单针不得判 cutoff（AND 语义钉）。
        assert hm.is_cutoff_message(
            "The project can no longer be opened because it is locked."
        ) is False
        assert hm.is_cutoff_message(
            "legacy project files must be migrated manually"
        ) is False

    def test_unrelated_errors_not_cutoff(self):
        assert hm.is_cutoff_message("License error: no licenses available") is False
        assert hm.is_cutoff_message("File not found: x.aedt") is False
        assert hm.is_cutoff_message("") is False

    def test_open_exception_maps_to_cutoff(self, tmp_path):
        original = _write_original(tmp_path)
        desktop = FakeDesktop(load_raises=RuntimeError(CUTOFF_QUOTE))
        sess = FakeSession(desktop)
        report = hm.open_legacy_project(
            original, session=sess, stage_root=tmp_path / "stage")
        assert report["outcome"] == hm.OUTCOME_CUTOFF
        assert report["cutoff"] is True
        assert report["ok"] is False
        assert any("cutoff" in e for e in report["errors"])


# ─── 2. 直开成功 + SaveAs 路径/原件只读 ──────────────────────────────


class TestOpenSuccessAndSaveAs:
    def test_open_success_returns_app_and_designs(self, tmp_path):
        original = _write_original(tmp_path)
        app = FakeApp(validate_return=([], True))
        sess = FakeSession(FakeDesktop(load_result=app))
        report = hm.open_legacy_project(
            original, session=sess, stage_root=tmp_path / "stage")
        assert report["outcome"] == hm.OUTCOME_OPENED
        assert report["ok"] is True
        assert report["app"] is app
        assert report["designs"] == ["HFSSDesign1"]
        assert report["design"] == "HFSSDesign1"
        assert report["staged"] is True
        # 打开的是 staging 拷贝件，不是原件
        assert Path(report["open_path"]) != original
        assert str(tmp_path / "stage") in report["open_path"]
        # 成功路径自建会话留场（活句柄不能交死会话）
        assert report["session_owned"] is False  # 注入会话
        assert sess.close_calls == []

    def test_saveas_goes_to_migrated_dir_not_original(self, tmp_path):
        original = _write_original(tmp_path)
        app = FakeApp(validate_return=([], True))
        migrated_dir = tmp_path / "migrated"
        save = hm.save_as_migrated(
            app, migrated_dir, original_path=original)
        assert save["ok"] is True
        assert save["migrated_path"] == str(migrated_dir / "legacy_proj.aedt")
        assert app.save_calls == [str(migrated_dir / "legacy_proj.aedt")]
        # 原件字节不动（只读铁律）
        assert original.read_bytes() == b"legacy-project-bytes"
        assert (migrated_dir / "legacy_proj.aedt").read_bytes() == b"migrated-by-app"

    def test_saveas_same_path_as_original_refused(self, tmp_path):
        original = _write_original(tmp_path)
        app = FakeApp(validate_return=([], True))
        save = hm.save_as_migrated(
            app, original.parent, original_path=original)
        assert save["ok"] is False
        assert app.save_calls == []  # 未触碰 save 通路
        assert any("原件只读" in e for e in save["errors"])

    def test_saveas_existing_target_refused_without_overwrite(self, tmp_path):
        original = _write_original(tmp_path)
        migrated_dir = tmp_path / "migrated"
        migrated_dir.mkdir()
        (migrated_dir / "legacy_proj.aedt").write_bytes(b"already-migrated")
        app = FakeApp(validate_return=([], True))
        save = hm.save_as_migrated(app, migrated_dir, original_path=original)
        assert save["ok"] is False
        assert app.save_calls == []
        assert any("overwrite=False" in e for e in save["errors"])
        # overwrite=True 放行
        save2 = hm.save_as_migrated(
            app, migrated_dir, original_path=original, overwrite=True)
        assert save2["ok"] is True

    def test_saveas_non_ascii_dir_fails_closed(self, tmp_path):
        original = _write_original(tmp_path)
        app = FakeApp(validate_return=([], True))
        bad_dir = tmp_path / "迁移件"
        with pytest.raises(ValueError, match="非 ASCII"):
            hm.save_as_migrated(app, bad_dir, original_path=original)
        assert app.save_calls == []

    def test_open_stage_false_non_ascii_fails_closed(self, tmp_path):
        cjk = tmp_path / "中文工程.aedt"
        cjk.write_bytes(b"x")
        sess = FakeSession(FakeDesktop(load_result=True))
        with pytest.raises(ValueError, match="非 ASCII"):
            hm.open_legacy_project(cjk, session=sess, stage=False)


# ─── 3. validate 解包顺序钉（晶圆键合 §2.4）─────────────────────────


class TestValidateUnpackOrder:
    def test_unpack_messages_ok_order_nonempty_false(self):
        # 判别性钉：(非空 messages, False)——若解包反了，ok=messages（truthy）
        # 会假 pass；正确解包必得 validate_failed。
        app = FakeApp(validate_return=(["geometry error: face invalid"], False))
        report = hm.run_health_check(app)
        assert report["validate"]["ok"] is False
        assert report["validate"]["messages"] == ["geometry error: face invalid"]
        assert report["outcome"] == "validate_failed"
        assert report["ok"] is False

    def test_unpack_empty_true_is_pass(self):
        app = FakeApp(validate_return=([], True))
        report = hm.run_health_check(app)
        assert report["validate"]["ok"] is True
        assert report["outcome"] == "pass"
        assert report["ok"] is True

    def test_validate_exception_recorded_not_raised(self):
        app = FakeApp(validate_raises=RuntimeError("grpc boom"))
        report = hm.run_health_check(app)
        assert report["outcome"] == "validate_failed"
        assert any("grpc boom" in e for e in report["errors"])

    def test_geometry_hint_from_messages(self):
        app = FakeApp(validate_return=(["Parts Vacuum and Body intersect."], False))
        report = hm.run_health_check(app)
        assert report["geometry_hint"] is True


# ─── 4. 六项检查清单 ────────────────────────────────────────────────


class TestChecklist:
    def test_all_items_counted(self):
        app = FakeApp(validate_return=([], True))
        report = hm.run_health_check(app)
        counts = {e["item"]: e["count"] for e in report["checklist"]}
        assert counts == {
            "materials": 2,
            "boundaries": 3,
            "mesh_operations": 1,
            "setups": 1,
            "optimetrics_parametric": 2,
            "optimetrics_optimization": 0,
        }
        assert all(e["available"] for e in report["checklist"])
        assert all(e["error"] is None for e in report["checklist"])
        assert len(report["checklist"]) == len(hm.CHECKLIST_ITEMS) == 6

    def test_broken_accessor_recorded_not_raised(self):
        app = FakeApp(validate_return=([], True))
        app.boundaries = _BrokenBoundaries()
        report = hm.run_health_check(app)
        entry = {e["item"]: e for e in report["checklist"]}["boundaries"]
        assert entry["available"] is False
        assert entry["count"] is None
        assert "RuntimeError" in entry["error"]
        assert report["ok"] is False  # 清单异常如实压 ok（不凑绿）

    def test_desktop_messages_collected_three_severities(self):
        app = FakeApp(validate_return=([], True))
        desktop = FakeDesktop(load_result=app)
        report = hm.run_health_check(app, desktop=desktop)
        assert report["desktop_messages"] == [
            "sev0 message", "sev1 message", "sev2 message",
        ]


class _BrokenBoundaries:
    """毒化访问器形态：len() 即抛（#413 会话毒化族离线替身）。"""

    def __len__(self):
        raise RuntimeError("poisoned session")


# ─── 5. 会话生命周期（#265）与 wrapper ──────────────────────────────


class TestSessionLifecycle:
    def test_injected_session_not_closed_by_open(self, tmp_path):
        original = _write_original(tmp_path)
        sess = FakeSession(FakeDesktop(load_result=FakeApp(validate_return=([], True))))
        hm.open_legacy_project(original, session=sess, stage_root=tmp_path / "s")
        assert sess.close_calls == []

    def test_injected_session_not_closed_by_wrapper(self, tmp_path):
        original = _write_original(tmp_path)
        sess = FakeSession(FakeDesktop(load_result=FakeApp(validate_return=([], True))))
        hm.migrate_open_save_and_check(
            original, tmp_path / "migrated", session=sess,
            stage_root=tmp_path / "s")
        assert sess.close_calls == []  # 注入会话调用方 owns

    def test_self_built_session_closed_on_open_failure(self, tmp_path, monkeypatch):
        original = _write_original(tmp_path)
        sess = FakeSession(FakeDesktop(load_raises=RuntimeError("boom")))
        monkeypatch.setattr(hm, "HfssSession", _SingletonStub(sess))
        report = hm.open_legacy_project(original, stage_root=tmp_path / "s")
        assert report["outcome"] == hm.OUTCOME_OPEN_FAILED
        # 自建会话 + 打开失败 → 就地关（#265：无活句柄可交不留孤儿桌面）
        assert sess.close_calls == [False]

    def test_wrapper_closes_session_in_finally(self, tmp_path):
        original = _write_original(tmp_path)
        sess = FakeSession(FakeDesktop(load_result=FakeApp(validate_return=([], True))))
        result = hm.migrate_open_save_and_check(
            original, tmp_path / "migrated", session=sess,
            stage_root=tmp_path / "s")
        assert result["ok"] is True
        assert result["outcome"] == hm.OUTCOME_OPENED
        # 注入会话：wrapper 不代关，但 staging 必清（任务毕清理）
        assert sess.close_calls == []
        assert result["stage_cleaned"] is True
        assert result["migrated_path"] == str(tmp_path / "migrated" / "legacy_proj.aedt")

    def test_wrapper_close_called_via_self_built_session(self, tmp_path, monkeypatch):
        original = _write_original(tmp_path)
        sess = FakeSession(FakeDesktop(load_result=FakeApp(validate_return=([], True))))
        monkeypatch.setattr(hm, "HfssSession", _SingletonStub(sess))
        result = hm.migrate_open_save_and_check(
            original, tmp_path / "migrated", stage_root=tmp_path / "s")
        assert result["ok"] is True
        assert sess.close_calls == [False]  # wrapper finally 必关 save=False
        assert result["session_owned"] is True
        assert sess.connect_calls and sess.connect_calls[0]["desktop_version"] == \
            hm.MIGRATE_VERSION_DEFAULT

    def test_wrapper_cutoff_short_circuits_save(self, tmp_path):
        original = _write_original(tmp_path)
        desktop = FakeDesktop(load_raises=RuntimeError(CUTOFF_QUOTE))
        sess = FakeSession(desktop)
        result = hm.migrate_open_save_and_check(
            original, tmp_path / "migrated", session=sess,
            stage_root=tmp_path / "s")
        assert result["cutoff"] is True
        assert result["outcome"] == hm.OUTCOME_CUTOFF
        assert result["ok"] is False
        assert result["migrated_path"] is None  # cutoff 无 SaveAs
        assert result["health"] is None

    def test_wrapper_health_failure_flips_ok_not_outcome(self, tmp_path):
        # 体检失败不改 outcome（体检事实在 health 键，service 映射裁决）
        original = _write_original(tmp_path)
        app = FakeApp(validate_return=(["bad"], False))
        sess = FakeSession(FakeDesktop(load_result=app))
        result = hm.migrate_open_save_and_check(
            original, tmp_path / "migrated", session=sess,
            stage_root=tmp_path / "s")
        assert result["outcome"] == hm.OUTCOME_OPENED
        assert result["open"]["ok"] is True
        assert result["health"]["ok"] is False
        assert result["ok"] is False  # open_ok and save_ok and health_ok

    def test_wrapper_no_active_design_uses_desktop_saveas(self, tmp_path):
        original = _write_original(tmp_path)
        desktop = FakeDesktop(load_result=True)  # True=无活动设计
        sess = FakeSession(desktop)
        result = hm.migrate_open_save_and_check(
            original, tmp_path / "migrated", session=sess,
            stage_root=tmp_path / "s")
        assert result["open"]["no_active_design"] is True
        assert result["open"]["app"] is None
        assert desktop.save_calls == [("legacy_proj", str(
            tmp_path / "migrated" / "legacy_proj.aedt"))]
        assert result["ok"] is True  # 体检无对象（health=None），open/save 承担

    def test_wrapper_engine_identity_recorded(self, tmp_path):
        original = _write_original(tmp_path)
        sess = FakeSession(FakeDesktop(load_result=FakeApp(validate_return=([], True))))
        result = hm.migrate_open_save_and_check(
            original, tmp_path / "migrated", session=sess,
            stage_root=tmp_path / "s")
        assert result["engine"] == {"version": hm.MIGRATE_VERSION_DEFAULT,
                                    "desktop_pid": 4242}

    def test_wrapper_staging_cleaned_even_on_cutoff(self, tmp_path):
        original = _write_original(tmp_path)
        desktop = FakeDesktop(load_raises=RuntimeError(CUTOFF_QUOTE))
        sess = FakeSession(desktop)
        result = hm.migrate_open_save_and_check(
            original, tmp_path / "migrated", session=sess,
            stage_root=tmp_path / "s")
        assert result["stage_cleaned"] is True
        assert not (tmp_path / "s").exists()


class _SingletonStub:
    """HfssSession.instance() 单例替身（自建会话路径钉）。"""

    def __init__(self, sess):
        self._sess = sess

    def instance(self):
        return self._sess


# ─── 6. 占用/缺文件契约 ──────────────────────────────────────────────


class TestGuards:
    def test_missing_file_raises_valueerror(self, tmp_path):
        with pytest.raises(ValueError, match="不存在"):
            hm.open_legacy_project(tmp_path / "nope.aedt", session=FakeSession(None))

    def test_non_aedt_suffix_rejected(self, tmp_path):
        notaedt = tmp_path / "proj.aedtz"
        notaedt.write_bytes(b"x")
        with pytest.raises(ValueError, match=r"\.aedt"):
            hm.open_legacy_project(notaedt, session=FakeSession(None))

    def test_occupied_maps_to_locked(self, tmp_path, monkeypatch):
        original = _write_original(tmp_path)
        monkeypatch.setattr(
            hm, "detect_project_occupancy",
            lambda p: {"occupied": True, "reason": "lock owner alive",
                       "lock_present": True})
        sess = FakeSession(FakeDesktop(load_result=FakeApp(validate_return=([], True))))
        report = hm.open_legacy_project(
            original, session=sess, stage_root=tmp_path / "s")
        assert report["outcome"] == hm.OUTCOME_LOCKED
        assert report["ok"] is False
        assert report["app"] is None
        assert sess.connect_calls == []  # 占用门在 license/会话之前
        # wrapper 对 locked 同样短路（无体检无 SaveAs）
        result = hm.migrate_open_save_and_check(
            original, tmp_path / "migrated", session=sess,
            stage_root=tmp_path / "s")
        assert result["outcome"] == hm.OUTCOME_LOCKED
        assert result["migrated_path"] is None

    def test_staging_copies_original_bytes(self, tmp_path):
        original = _write_original(tmp_path)
        info = hm.stage_ascii_copy(original, stage_root=tmp_path / "stage")
        staged = Path(info["staged_path"])
        assert staged.read_bytes() == b"legacy-project-bytes"
        assert original.read_bytes() == b"legacy-project-bytes"

    def test_stage_root_non_ascii_fails_closed(self, tmp_path):
        original = _write_original(tmp_path)
        with pytest.raises(ValueError, match="非 ASCII"):
            hm.stage_ascii_copy(original, stage_root=tmp_path / "暂存")


# ─── 7. heal opt-in 与 Modeler Check 模板守卫 ────────────────────────


class TestHealAndModelCheck:
    def test_heal_default_off(self):
        app = FakeApp(validate_return=([], True))
        report = hm.run_health_check(app)
        assert report["heal"] is None
        assert app.modeler.heal_calls == []

    def test_heal_opt_in_uses_wrapped_api(self):
        app = FakeApp(validate_return=([], True))
        report = hm.run_health_check(app, heal=True)
        assert report["heal"]["ran"] is True
        assert report["heal"]["ok"] is True
        assert app.modeler.heal_calls == ["Box1,Box2"]  # 缺省全体对象

    def test_heal_failure_recorded(self):
        app = FakeApp(validate_return=([], True))
        app.modeler.heal_return = False
        report = hm.run_health_check(app, heal=True)
        assert report["heal"]["ran"] is True
        assert report["heal"]["ok"] is False
        assert report["ok"] is False

    def test_modeler_check_script_refuses_unverified(self):
        with pytest.raises(NotImplementedError):
            hm.run_modeler_check_script()

    def test_model_check_metadata_declares_grounding(self):
        app = FakeApp(validate_return=([], True))
        report = hm.run_health_check(app)
        assert report["model_check"]["script_template_verified"] is False
        assert "validate_full_design" in report["model_check"]["covered_by"]

    def test_template_constant_carries_unverified_marker(self):
        assert "UNVERIFIED-API" in hm._MODEL_CHECK_SCRIPT_TEMPLATE
        assert "QuitApplication" in hm._MODEL_CHECK_SCRIPT_TEMPLATE  # #374④
