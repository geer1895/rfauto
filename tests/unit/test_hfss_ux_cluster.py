"""T-Q26c HFSS 杂项簇四件钉（Q-X8 席，晶圆键合外部使用者实测反馈 P1/P2）。

反馈源：D:/晶圆键合/rfauto_反馈与实测经验.md §3.5/§3.6/§2.4/P2 表
（外部建模使用者借 rfauto venv 直调 PyAEDT 实测，2026-11-06）：

1. **件①deembed 单位语义**（P1-3.5）：``wave_port(..., deembed=0.3)`` 签名
   只写 float，无法确认按 model_units(mm) 还是 m——护栏=
   ``hfss_session.validate_deembed_distance``（float|str 校验 + docstring
   写死 pyaedt 1.9.0 value_with_units→DeembedDist 的 model_units 口径）；
2. **件②validate_full_design 具名包装**（P1-3.6）：pyaedt 返回
   ``(messages, success)`` 解包顺序与生态惯例相反——护栏=
   ``validate_design_named()`` 具名结构（ok/errors/warnings/raw）；
3. **件③.aedt.lock 占用检测 + 显式重建**（P2 前两项）：另一 GUI 已打开
   同一 .aedt 时求解报 'Error updating solution state'（看不出文件占用），
   复用上次失败工程对象/sweep 累积——护栏=``detect_project_occupancy``（锁
   属主 + ansysedt 命令行双通道，#265 家法）+ ``ensure_project_not_occupied``
   + ``prepare_fresh_workdir``（显式重建，禁自动 rmtree）；
4. **件④export_model_picture 合法值 + 非图形报错**（P2 后两项）：传
   ``"iso"`` 报 'orientation name iso doesn't exist' 无候选提示；非图形模式
   报误导性 'NoneType' object has no attribute 'recreate_application'——护栏=
   ``MODEL_PICTURE_ORIENTATIONS`` 常量表 + ``normalize_model_picture_orientation``
   + ``ensure_graphical_session``（明确 RuntimeError）。

全 mock 零真机（pyaedt 禁 import，HFSS 禁启，PowerShell 探针全 monkeypatch
——单测禁真打硬规则）；反馈实测形态以 mock 复现并钉护栏拦截（错误类型+
文案断言）。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.infra.desktop_guard as desktop_guard
from rfauto.adapters.hfss_session import (
    DEFAULT_MODEL_PICTURE_ORIENTATION,
    MODEL_PICTURE_ORIENTATIONS,
    HfssSession,
    detect_project_occupancy,
    ensure_graphical_session,
    ensure_project_not_occupied,
    normalize_model_picture_orientation,
    prepare_fresh_workdir,
    validate_deembed_distance,
    validate_design_named,
)

# ─── mock 面通用件 ────────────────────────────────────────────────────────────


class _FakePsutilProcess:
    def __init__(self, name: str):
        self._name = name

    def name(self):
        return self._name


class _FakePsutilModule:
    """假 psutil 模块体（sys.modules 注入，test_resource_janitor_service 同款）。

    Error/NoSuchProcess 同源异常类（``except psutil.Error`` 判 dead 路径
    可走通）；Process 按名字查表，表外 PID 抛 NoSuchProcess=已退出。
    """

    class Error(Exception):
        pass

    class NoSuchProcess(Error):
        pass

    def __init__(self, name_by_pid: dict[int, str]):
        self._name_by_pid = dict(name_by_pid)

    def Process(self, pid):
        pid = int(pid)
        if pid not in self._name_by_pid:
            raise _FakePsutilModule.NoSuchProcess(pid)
        return _FakePsutilProcess(self._name_by_pid[pid])


def _patch_psutil(monkeypatch, name_by_pid: dict[int, str]) -> None:
    """向 sys.modules 注入假 psutil（族名核验路径全 mock，零真进程依赖）。"""
    monkeypatch.setitem(sys.modules, "psutil",
                        _FakePsutilModule(name_by_pid))


def _patch_no_psutil(monkeypatch) -> None:
    """令 `import psutil` 失败——走 desktop_guard 兜底路径。"""
    monkeypatch.setitem(sys.modules, "psutil", None)


def _patch_enum(monkeypatch, procs: list[dict] | Exception) -> None:
    """把 desktop_guard 枚举面换成桩（禁真 PowerShell——零真机纪律）。"""

    def _enum():
        if isinstance(procs, Exception):
            raise procs
        return list(procs)

    monkeypatch.setattr(desktop_guard, "list_ansysedt_processes", _enum)


def _patch_alive(monkeypatch, mapping: dict[int, bool] | None) -> None:
    """desktop_guard.process_alive 桩（fallback 路径用）；mapping None=未知态。"""

    def _alive(pid: int):
        if mapping is None:
            return None
        return mapping.get(int(pid))

    monkeypatch.setattr(desktop_guard, "process_alive", _alive)


def _write_lock(
    directory: Path, project_stem: str = "wb", pid: int | None = 4242
) -> Path:
    """写一枚实测形态锁文本（顶层 DesktopProcessID + DesktopProcessPath）。"""
    lock = directory / f"{project_stem}.aedt.lock"
    lines = ["[Project Lock]"]
    if pid is not None:
        lines.append(f"DesktopProcessID={pid}")
        lines.append(f"DesktopProcessPath='{directory / (project_stem + '.aedt')}'")
    lock.write_text("\n".join(lines) + "\n", encoding="ascii")
    return lock


# ─── 件①（P1-3.5）：deembed 单位语义 ──────────────────────────────────────────


class TestDeembedUnitSemantics:
    def test_repro_float_accepted_semantics_documented(self):
        """反馈 P1-3.5 复现面：传 0.3 的疑义=单位——护栏放行数值型，且
        docstring 写死口径（model_units / mm / value_with_units→DeembedDist
        链），调用者不必再靠结果反推。"""
        assert validate_deembed_distance(0.3) is None
        doc = validate_deembed_distance.__doc__ or ""
        assert "model_units" in doc, "缺省单位口径必须写明（反馈 P1-3.5 主诉）"
        assert "mm" in doc
        assert "value_with_units" in doc and "DeembedDist" in doc, (
            "pyaedt 消费链源码口径（hfss.py props['DeembedDist'] = "
            "self.value_with_units(deembed)）必须入 docstring")
        assert "P1-3.5" in doc

    def test_none_and_numeric_forms_pass(self):
        """None=pyaedt DoDeembed=False（禁用）；int/float 均放行。"""
        assert validate_deembed_distance(None) is None
        assert validate_deembed_distance(0) is None
        assert validate_deembed_distance(1) is None
        assert validate_deembed_distance(2.5e-3) is None

    def test_bool_rejected(self):
        """bool 是 int 子类——True 会静默当 1.0 个 model_units 距离，显式拒绝。"""
        with pytest.raises(ValueError, match="布尔"):
            validate_deembed_distance(True)

    def test_negative_rejected_with_zero_disables_guidance(self):
        """负距离非物理：deembed=0 即禁用——文案必须带该指引。"""
        with pytest.raises(ValueError) as ei:
            validate_deembed_distance(-0.3)
        msg = str(ei.value)
        assert "≥0" in msg and "0=禁用" in msg

    def test_nan_inf_rejected(self):
        """NaN/Inf 经 value_with_units 写入 DeembedDist 即垃圾几何——fail-loud。"""
        with pytest.raises(ValueError, match="有限"):
            validate_deembed_distance(float("nan"))
        with pytest.raises(ValueError, match="有限"):
            validate_deembed_distance(float("inf"))

    def test_string_with_units_and_expression_passthrough(self):
        """带单位串（'0.3mm'，value_with_units 原样透传）与表达式/变量名串
        （AEDT 按 model_units 求值）均放行；表达式内裸数=m 的相邻坑入 doc。"""
        assert validate_deembed_distance("0.3mm") is None
        assert validate_deembed_distance("-L_cav/2") is None
        doc = validate_deembed_distance.__doc__ or ""
        assert "米" in doc, "AEDT 表达式内裸数按内部 SI（米）解释的相邻坑须提示"

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError, match="不可为空"):
            validate_deembed_distance("   ")

    def test_unsupported_types_rejected(self):
        with pytest.raises(ValueError, match=r"float \| str"):
            validate_deembed_distance(["0.3mm"])
        with pytest.raises(ValueError, match=r"float \| str"):
            validate_deembed_distance({"d": 0.3})

    def test_param_name_customization(self):
        """floquet 等面用自定义形参名进文案（Q-X1 param 先例同款）。"""
        with pytest.raises(ValueError) as ei:
            validate_deembed_distance(["0.3mm"], param="deembed_distance")
        assert "deembed_distance" in str(ei.value)


# ─── 件②（P1-3.6）：validate_full_design 具名包装 ────────────────────────────


class _FakeHfssValidate:
    """validate_full_design 假会话：按 pyaedt 1.9.0 真形态返回 (messages, ok)。"""

    def __init__(self, result):
        self._result = result
        self.calls: list[dict] = []

    def validate_full_design(self, design=None, output_dir=None, ports=None):
        self.calls.append(
            {"design": design, "output_dir": output_dir, "ports": ports})
        return self._result


class TestValidateDesignNamed:
    def test_repro_unpack_order_named_structure(self):
        """反馈 P1-3.6 复现面：pyaedt (messages, success) 顺序——按生态惯例
        (ok, msgs) 解包会把 list 当 bool。具名结构消除歧义：键面固定
        ok/errors/warnings/raw，ok 取 pyaedt 权威标志。"""
        hfss = _FakeHfssValidate((
            ["Desktop messages:", "[error] Parts Vacuum and W2_Membrane intersect.",
             "[warning] Port P1 is not covered by a metal sheet."],
            True,
        ))
        named = validate_design_named(hfss)
        assert set(named) == {"ok", "errors", "warnings", "raw"}
        assert named["ok"] is True
        assert len(named["errors"]) == 1 and "intersect" in named["errors"][0]
        assert len(named["warnings"]) == 1
        assert len(named["raw"]) == 3, "raw 原样保真"

    def test_ok_false_when_validation_fails(self):
        hfss = _FakeHfssValidate((["Design validation check ERROR."], False))
        named = validate_design_named(hfss)
        assert named["ok"] is False
        assert named["errors"] == [], "ok 不因 [error] 标记面变化——两面向独立"

    def test_error_warning_classification_case_insensitive(self):
        """[ERROR]/[Warning] 大小写漂移形态同样分类（消息文本观察面）。"""
        hfss = _FakeHfssValidate((
            ["[ERROR] boom", "[Warning] meh", "plain line"], True))
        named = validate_design_named(hfss)
        assert named["errors"] == ["[ERROR] boom"]
        assert named["warnings"] == ["[Warning] meh"]

    def test_none_hfss_rejected(self):
        with pytest.raises(ValueError, match="hfss 实例缺失"):
            validate_design_named(None)

    def test_shape_drift_fail_loud(self):
        """返回形态漂移（3 元组 / 1 元组 / 第二元素非 bool）→ ValueError
        拒绝猜测解包——具名包装的存在意义即消灭解包歧义。"""
        with pytest.raises(ValueError, match="形态漂移"):
            validate_design_named(_FakeHfssValidate((["a"], True, "extra")))
        with pytest.raises(ValueError, match="形态漂移"):
            validate_design_named(_FakeHfssValidate((["m1", "m2"],)))
        with pytest.raises(ValueError, match="bool"):
            validate_design_named(_FakeHfssValidate((["a"], "True")))

    def test_design_ports_passthrough(self):
        hfss = _FakeHfssValidate(([], True))
        validate_design_named(hfss, design="d1", ports=2)
        assert hfss.calls[0] == {"design": "d1", "output_dir": None, "ports": 2}

    def test_none_message_items_skipped(self):
        """消息含 None 项（版本漂移形态）不进 raw（str(None) 污染挡在门口）。"""
        hfss = _FakeHfssValidate((["[error] x", None], True))
        named = validate_design_named(hfss)
        assert named["raw"] == ["[error] x"]


# ─── 件③（P2 前两项）：.aedt.lock 占用检测 + 显式重建 ─────────────────────────


class TestDetectProjectOccupancy:
    def test_repro_gui_occupied_via_alive_lock_owner(self, tmp_path, monkeypatch):
        """反馈 §2.4 复现面：另一 AEDT GUI 已打开同一 .aedt（锁属主活）→
        occupied=True 且证据链齐（lock_path/owner_pid/owner_alive）。"""
        _patch_psutil(monkeypatch, {4242: "ansysedt.exe"})
        _patch_enum(monkeypatch, [])
        _write_lock(tmp_path)
        report = detect_project_occupancy(tmp_path / "wb.aedt")
        assert report["occupied"] is True
        assert report["lock_present"] is True
        assert report["owner_pid"] == 4242
        assert report["owner_alive"] == "alive"
        assert report["stale"] is False
        assert "占用" in report["reason"]

    def test_owner_pid_reused_by_other_process_is_dead(self, tmp_path, monkeypatch):
        """属主 PID 被非 ansysedt 进程复用 → dead（janitor _process_liveness
        同语义：锁属主特定是 ansysedt）→ 陈旧锁。"""
        _patch_psutil(monkeypatch, {4242: "python.exe"})
        _patch_enum(monkeypatch, [])
        _write_lock(tmp_path)
        report = detect_project_occupancy(tmp_path / "wb.aedt")
        assert report["occupied"] is False
        assert report["owner_alive"] == "dead"
        assert report["stale"] is True

    def test_stale_lock_via_fallback_oracle(self, tmp_path, monkeypatch):
        """psutil 缺失 → desktop_guard.process_alive 兜底（False=属主死）。"""
        _patch_no_psutil(monkeypatch)
        _patch_alive(monkeypatch, {4242: False})
        _patch_enum(monkeypatch, [])
        _write_lock(tmp_path)
        report = detect_project_occupancy(tmp_path / "wb.aedt")
        assert report["occupied"] is False
        assert report["stale"] is True

    def test_owner_alive_via_fallback_oracle(self, tmp_path, monkeypatch):
        _patch_no_psutil(monkeypatch)
        _patch_alive(monkeypatch, {4242: True})
        _patch_enum(monkeypatch, [])
        _write_lock(tmp_path)
        report = detect_project_occupancy(tmp_path / "wb.aedt")
        assert report["occupied"] is True

    def test_cmdline_match_reports_occupied_without_lock(
            self, tmp_path, monkeypatch):
        """#265 家法通道：无锁但 ansysedt 命令行引用本工程（大小写/分隔符
        漂移形态）→ occupied=True，pid 入账。"""
        _patch_psutil(monkeypatch, {})
        _patch_enum(monkeypatch, [
            {"pid": 42, "ppid": 1,
             "cmdline": '"' + str(tmp_path / "WB.AEDT").replace("\\\\", "/")
                        + '" -grpcsrv 5000 -ng'},
        ])
        report = detect_project_occupancy(tmp_path / "wb.aedt")
        assert report["occupied"] is True
        assert report["ansysedt_matching_pids"] == [42]

    def test_cmdline_boundary_no_false_positive(self, tmp_path, monkeypatch):
        """带边界匹配：my_wb.aedt / wb.aedt.lock 不构成 wb.aedt 的占用证据。"""
        _patch_psutil(monkeypatch, {})
        _patch_enum(monkeypatch, [
            {"pid": 7, "ppid": 1,
             "cmdline": '"' + str(tmp_path / "my_wb.aedt") + '" -grpcsrv 1'},
            {"pid": 8, "ppid": 1,
             "cmdline": '"' + str(tmp_path / "wb.aedt.lock") + '" -grpcsrv 2'},
        ])
        report = detect_project_occupancy(tmp_path / "wb.aedt")
        assert report["ansysedt_matching_pids"] == []
        assert report["occupied"] is False

    def test_enum_failure_fail_unknown(self, tmp_path, monkeypatch):
        """枚举失败（fail-closed 抛错面）→ occupied=None（fail-unknown，
        #105 观测面不炸），reason 注明枚举失败。"""
        _patch_psutil(monkeypatch, {})
        _patch_enum(monkeypatch, RuntimeError("enum timeout"))
        report = detect_project_occupancy(tmp_path / "wb.aedt")
        assert report["occupied"] is None
        assert "枚举失败" in report["reason"]

    def test_lock_without_owner_text_unknown(self, tmp_path, monkeypatch):
        """目录锁/无 DesktopProcessID 文本 → occupied=None（保守不可判定）。"""
        _patch_psutil(monkeypatch, {})
        _patch_enum(monkeypatch, [])
        lock = tmp_path / "wb.aedt.lock"
        lock.mkdir()  # 目录形锁
        report = detect_project_occupancy(tmp_path / "wb.aedt")
        assert report["occupied"] is None
        assert report["lock_present"] is True
        assert report["owner_pid"] is None

    def test_no_lock_no_process_free(self, tmp_path, monkeypatch):
        """无锁无进程 → occupied=False（干净工程的既有行为锚）。"""
        _patch_psutil(monkeypatch, {})
        _patch_enum(monkeypatch, [])
        report = detect_project_occupancy(tmp_path / "wb.aedt")
        assert report["occupied"] is False
        assert report["lock_present"] is False
        assert report["stale"] is None


class TestEnsureProjectNotOccupied:
    def test_repro_occupied_raises_with_guidance(self, tmp_path, monkeypatch):
        """反馈 P2 复现面 mock 复现+修好断言：占用 → ValueError 带
        '工程被 GUI 占用' + 'Error updating solution state' 病灶原文 + 清场
        指引（#265/#245 家法），绝不落到求解期的暗坑。"""
        _patch_psutil(monkeypatch, {4242: "ansysedt.exe"})
        _patch_enum(monkeypatch, [])
        _write_lock(tmp_path)
        with pytest.raises(ValueError) as ei:
            ensure_project_not_occupied(tmp_path / "wb.aedt")
        msg = str(ei.value)
        assert "工程被 GUI/会话占用" in msg
        assert "Error updating solution state" in msg
        assert "desktop_guard" in msg or "remote_hfss_cleanup" in msg

    def test_unknown_warns_and_passes(self, tmp_path, monkeypatch, caplog):
        """fail-unknown → warning 放行（求解进被占工程可恢复，不值得为探测
        面故障阻塞），返回报告可续链。"""
        _patch_psutil(monkeypatch, {})
        _patch_enum(monkeypatch, RuntimeError("enum timeout"))
        with caplog.at_level(logging.WARNING):
            report = ensure_project_not_occupied(tmp_path / "wb.aedt")
        assert report["occupied"] is None
        assert "不可判定" in caplog.text

    def test_free_passes_without_warning(self, tmp_path, monkeypatch, caplog):
        _patch_psutil(monkeypatch, {})
        _patch_enum(monkeypatch, [])
        with caplog.at_level(logging.WARNING):
            report = ensure_project_not_occupied(tmp_path / "wb.aedt")
        assert report["occupied"] is False
        assert caplog.text == ""


class TestPrepareFreshWorkdir:
    def test_rebuild_removes_and_recreates_empty(self, tmp_path, monkeypatch):
        """反馈 P2 复现面：复用上次失败工程对象/sweep 累积（Box1_1、
        Sweep_NVR7O5）→ 显式重建清干净：.aedt/陈旧锁/杂散子目录全清，
        目录重建为空。"""
        _patch_psutil(monkeypatch, {4242: "python.exe"})  # 锁属主死=陈旧可清
        _patch_enum(monkeypatch, [])
        work = tmp_path / "work"
        work.mkdir()
        (work / "wb.aedt").write_bytes(b"fake")
        _write_lock(work)
        (work / "wb.aedtresults").mkdir()
        (work / "wb.aedtresults" / "old.txt").write_text("stale", encoding="ascii")
        out = prepare_fresh_workdir(work)
        assert out == Path(work)
        assert work.is_dir()
        assert list(work.iterdir()) == [], "重建后必须为空（对象/sweep 累积根除）"

    def test_creates_missing_dir(self, tmp_path, monkeypatch):
        _patch_psutil(monkeypatch, {})
        _patch_enum(monkeypatch, [])
        work = tmp_path / "nested" / "work"
        out = prepare_fresh_workdir(work)
        assert out == Path(work)
        assert work.is_dir()

    def test_refuses_alive_owner_and_keeps_content(self, tmp_path, monkeypatch):
        """活属主锁 → ValueError 拒删，目录内容原样（防误删红线）。"""
        _patch_psutil(monkeypatch, {4242: "ansysedt.exe"})
        _patch_enum(monkeypatch, [])
        work = tmp_path / "work2"
        work.mkdir()
        _write_lock(work)
        (work / "wb.aedt").write_bytes(b"fake")
        with pytest.raises(ValueError, match="占用"):
            prepare_fresh_workdir(work)
        assert (work / "wb.aedt").is_file(), "拒删时内容必须原样保留"

    def test_refuses_unknown_occupancy_fail_closed(self, tmp_path, monkeypatch):
        """占用不可判定（枚举失败）→ 拒删（破坏性方向 fail-closed，同
        kill_orphan_ansysedt_desktops strict=True 口径）。"""
        _patch_psutil(monkeypatch, {})
        _patch_enum(monkeypatch, RuntimeError("enum timeout"))
        work = tmp_path / "work3"
        work.mkdir()
        (work / "keep.txt").write_text("keep", encoding="ascii")
        with pytest.raises(ValueError, match="不可判定"):
            prepare_fresh_workdir(work)
        assert (work / "keep.txt").is_file()

    def test_refuses_root_and_file(self, tmp_path):
        """盘根/文件系统根（parent==自身）与非目录目标显式拒绝。"""
        with pytest.raises(ValueError, match="盘根"):
            prepare_fresh_workdir(Path(tmp_path.anchor))
        target = tmp_path / "plain.txt"
        target.write_text("x", encoding="ascii")
        with pytest.raises(ValueError, match="不是目录"):
            prepare_fresh_workdir(target)

    def test_responsibility_documented(self):
        """禁自动 rmtree 的责任声明必须入 docstring（任务书硬要求）。"""
        doc = prepare_fresh_workdir.__doc__ or ""
        assert "禁自动 rmtree" in doc
        assert "不会自动调用" in doc
        assert "不可恢复" in doc
        assert "盘根" in doc


# ─── 件④（P2 后两项）：export_model_picture 合法值 + 非图形守卫 ───────────────


class TestModelPictureOrientation:
    #: pyaedt 1.9.0 post_common_3d.export_model_picture docstring 合法集
    _PYAEDT_DOCSTRING_SET: frozenset[str] = frozenset({
        "top", "bottom", "right", "left", "front", "back",
        "trimetric", "dimetric", "isometric",
    })

    def test_constant_table_matches_pyaedt_docstring(self):
        """常量表与 pyaedt 1.9.0 docstring 合法集一致（防表漂移）；拼写取
        AEDT 报告器规范形（反馈实测 'Isometric' 可用）。"""
        lowered = {name.lower() for name in MODEL_PICTURE_ORIENTATIONS}
        assert lowered == self._PYAEDT_DOCSTRING_SET
        assert "Isometric" in MODEL_PICTURE_ORIENTATIONS

    def test_normalize_case_and_whitespace(self):
        """大小写不敏感 + 去空白 → 归一为 AEDT 拼写规范形。"""
        assert normalize_model_picture_orientation("isometric") == "Isometric"
        assert normalize_model_picture_orientation("TOP") == "Top"
        assert normalize_model_picture_orientation("  front ") == "Front"

    def test_repro_iso_abbreviation_rejected_lists_candidates(self):
        """反馈 P2 复现面 mock 复现+修好断言：传 'iso' → ValueError 列全
        候选 + AEDT 症状原文指引（不再落到无候选提示的 'orientation name
        iso doesn't exist'）。"""
        with pytest.raises(ValueError) as ei:
            normalize_model_picture_orientation("iso")
        msg = str(ei.value)
        assert "Isometric" in msg and "Top" in msg
        assert "doesn't exist" in msg, "AEDT 侧症状原文须入文案（可检索）"
        assert "完整名" in msg

    def test_none_returns_default(self):
        assert normalize_model_picture_orientation(None) == \
            DEFAULT_MODEL_PICTURE_ORIENTATION
        assert DEFAULT_MODEL_PICTURE_ORIENTATION == "Isometric"

    def test_allow_custom_passthrough_default_rejects(self):
        """已加入 Orientation List 的自定义视图名显式放行；缺省拒绝不猜。"""
        assert normalize_model_picture_orientation(
            "MyView", allow_custom=True) == "MyView"
        with pytest.raises(ValueError, match="MyView"):
            normalize_model_picture_orientation("MyView")

    def test_non_string_rejected(self):
        with pytest.raises(ValueError, match="str"):
            normalize_model_picture_orientation(3)


class _FakeDesktopClass:
    def __init__(self, non_graphical):
        self.non_graphical = non_graphical


class _FakeApp:
    """pyaedt 1.9.0 真实判据路径形态：post 经 _app.desktop_class.non_graphical。"""

    def __init__(self, non_graphical):
        self.desktop_class = _FakeDesktopClass(non_graphical)


class TestEnsureGraphicalSession:
    def test_repro_non_graphical_runtime_error(self):
        """反馈 P2 复现面 mock 复现+修好断言：无头模式 → 明确 RuntimeError
        含规定短语 'requires graphical session' + 病灶原文 'recreate_
        application'（旧径='NoneType' object has no attribute ... 误导）。"""
        with pytest.raises(RuntimeError) as ei:
            ensure_graphical_session(_FakeApp(True))
        msg = str(ei.value)
        assert "requires graphical session" in msg
        assert "recreate_application" in msg
        assert "non_graphical=False" in msg, "修法指引必须入文案"

    def test_graphical_session_passes(self):
        ensure_graphical_session(_FakeApp(False))  # 不抛即通过

    def test_unknown_detection_passes_best_effort(self):
        """探测链全空（裸对象）→ 放行（#105：探测失败不得阻塞图形会话）。"""
        ensure_graphical_session(object())  # 不抛即通过

    def test_app_level_attribute_fallback(self):
        """旧代 App 级 non_graphical 属性形态同样拦（duck-type 第二探测）。"""

        class _OldApp:
            non_graphical = True

        with pytest.raises(RuntimeError, match="requires graphical session"):
            ensure_graphical_session(_OldApp())

    def test_session_settings_ducktype_preconnect(self):
        """rfauto HfssSession 未连接态（desktop None，settings 已带
        non_graphical=True）→ pre-connect fail-fast 拦截。"""
        try:
            session = HfssSession()
            session._settings = {"non_graphical": True}
            with pytest.raises(RuntimeError, match="requires graphical session"):
                ensure_graphical_session(session)
        finally:
            HfssSession.reset()
