"""HFSS 链路稳定性兜底钉（P1/P2/P5，2026-10 用户实战反馈，全 fake 零真机）。

钉住三项契约（aurora_j S-B 席，pyaedt 1.4 × AEDT 2025.1 用户实测病灶）：

1. **P2 setup 白名单**：``configure_setup`` 收 ``minimum_passes``（含 AEDT
   原生大小写别名 ``MinimumPasses`` 等）走 ``setup.props`` 原生属性字典
   （create_setup kwarg 面恒空——透传即 GrpcApiError: EditSetup）；白名单
   外键显式 ValueError（宁可契约错误不裸 gRPC，静默丢键亦契约错误）；
   MaxDeltaS/MaximumPasses 历史缺省保真；类型/歧义双形态 fail-loud；
2. **P1 导出失败保留工程**：``export_touchstone`` 失败路径零 save/覆盖/
   删除（工程文件字节保真），结构化错误（details）含工程绝对路径+设计
   名+建议动作；工程文件被会话重存时如实区分（不冒充"未触碰"）；
3. **P5 CJK 路径守卫**：非 ASCII 工程路径缺省 ValueError（指引 ASCII 工
   作目录/ascii_workdir 选项，守卫先于任何状态写入）；opt-in 重定向
   %TEMP% ASCII 工作目录（原工程播副本、close 交付拷回 .aedt+.aedtresults、
   拷回失败如实抛、工作副本永不删除）；远程会话非 ASCII 显式拒绝。

批处理通道（hfss_batch）零行为变化钉：CJK 工程 -BatchSolve 照常发射
（用户实测能建能解）；-batchextract 导出段 CJK 工程名定向结构化失败
（纯 ASCII 脚本资产不可烘焙），绝不拉起进程。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.adapters.hfss_adapter as hfss_adapter_mod
import rfauto.adapters.hfss_batch as hb
from rfauto.adapters.hfss_adapter import HfssAdapter
from rfauto.adapters.hfss_session import (
    HfssSession,
    ascii_workdir_path,
    deliver_ascii_workdir,
    has_non_ascii,
    prepare_ascii_workdir,
    validate_setup_config,
)
from rfauto.core.errors import ModelBuildError

# ─── P2：setup 白名单校验 ─────────────────────────────────────────────────────


class _FakeSetup:
    """模拟 pyaedt Setup：props 字典 + update 记账。"""

    def __init__(self):
        self.props: dict = {}
        self.update_calls = 0

    def update(self):
        self.update_calls += 1
        return True


class _FakeHfssForSetup:
    """模拟 Hfss：create_setup 记录 kwarg 面（P2 契约=恒空）+ sweep 记录。"""

    def __init__(self):
        self.created: list[tuple[str, dict]] = []
        self.last_setup: _FakeSetup | None = None
        self.sweeps: list[dict] = []

    def create_setup(self, name="Setup1", **kwargs):
        self.created.append((name, kwargs))
        self.last_setup = _FakeSetup()
        return self.last_setup

    def create_linear_count_sweep(self, **kwargs):
        self.sweeps.append(kwargs)
        return True


@pytest.fixture()
def adapter():
    HfssSession.reset()
    a = HfssAdapter()
    yield a
    HfssSession.reset()


def test_minimum_passes_goes_through_props(adapter):
    """P2 主契约：minimum_passes 走 setup.props，create_setup kwarg 面恒空。"""
    hfss = _FakeHfssForSetup()
    adapter.session.hfss = hfss

    adapter.configure_setup({"freq_range_ghz": [2.0, 3.0], "minimum_passes": 1})

    props = hfss.last_setup.props
    assert props["MinimumPasses"] == 1
    assert props["MaxDeltaS"] == 0.02
    assert props["MaximumPasses"] == 12
    assert props["Frequency"] == "2.5GHz"
    assert hfss.last_setup.update_calls == 1
    # P2 核心契约：pyaedt create_setup 不收任何透传 kwarg（透传即
    # GrpcApiError: EditSetup，2026-10 用户实测）
    assert hfss.created == [("Setup1", {})]


def test_minimum_passes_native_cased_alias(adapter):
    """AEDT 原生大小写别名 MinimumPasses 等价 snake_case。"""
    hfss = _FakeHfssForSetup()
    adapter.session.hfss = hfss

    adapter.configure_setup({"MinimumPasses": 3, "MaximumPasses": 7,
                             "MaxDeltaS": 0.01})

    props = hfss.last_setup.props
    assert props["MinimumPasses"] == 3
    assert props["MaximumPasses"] == 7
    assert props["MaxDeltaS"] == 0.01


def test_defaults_preserved_without_convergence_keys(adapter):
    """键缺省：MaxDeltaS/MaximumPasses 历史缺省回填，MinimumPasses 不写入。"""
    hfss = _FakeHfssForSetup()
    adapter.session.hfss = hfss

    adapter.configure_setup({})

    props = hfss.last_setup.props
    assert props["MaxDeltaS"] == 0.02
    assert props["MaximumPasses"] == 12
    assert "MinimumPasses" not in props


def test_recipe_setup_section_keys_accepted():
    """既有配方 setup 段键（solver/radiation_box）不因白名单误伤。"""
    resolved = validate_setup_config({
        "solver": "DrivenModal", "radiation_box": "Open",
        "freq_range_ghz": [1.5, 3.5], "points": 201,
        "convergence_delta": 0.02,
    })
    assert resolved == {"MaxDeltaS": 0.02, "MaximumPasses": 12}


def test_unknown_kwarg_explicit_error_with_guidance():
    """白名单外键显式 ValueError：含未知键名+MinimumPasses 指引（不裸 gRPC）。"""
    with pytest.raises(ValueError, match="FooBar"):
        validate_setup_config({"FooBar": 1})
    # 拼写近似键（用户真实场景：想写 MinimumPasses 拼错）同样显式拒绝
    with pytest.raises(ValueError) as ei:
        validate_setup_config({"MinimumPases": 2})
    assert "MinimumPases" in str(ei.value)
    assert "MinimumPasses" in str(ei.value), "错误消息须含 MinimumPasses 指引"


def test_configure_setup_unknown_key_rejected_before_create(adapter):
    """configure_setup 入口校验：零半成品（create_setup 不被触达）。"""
    hfss = _FakeHfssForSetup()
    adapter.session.hfss = hfss
    with pytest.raises(ValueError, match="FooBar"):
        adapter.configure_setup({"FooBar": 1})
    assert hfss.created == []


def test_conflicting_double_form_rejected():
    """同字段双形态同给且值不等 → 歧义拒绝。"""
    with pytest.raises(ValueError, match="歧义"):
        validate_setup_config({"max_passes": 12, "MaximumPasses": 15})
    with pytest.raises(ValueError, match="歧义"):
        validate_setup_config({"minimum_passes": 1, "MinimumPasses": 2})


def test_same_value_double_form_accepted():
    """双形态同值（如 12 与 12.0 数值等价）放行——歧义门只拦值不等。"""
    resolved = validate_setup_config({"max_passes": 12, "MaximumPasses": 12})
    assert resolved["MaximumPasses"] == 12


@pytest.mark.parametrize("raw", [0, -1, 1.5, True, "abc", None])
def test_integer_field_type_validation(raw):
    """MaximumPasses/MinimumPasses 整数面 fail-loud（bool 显式拒绝）。"""
    with pytest.raises(ValueError):
        validate_setup_config({"minimum_passes": raw})
    with pytest.raises(ValueError):
        validate_setup_config({"maximum_passes": raw})


@pytest.mark.parametrize("raw", [0, -0.01, "abc", None])
def test_max_delta_s_type_validation(raw):
    """MaxDeltaS 须为 >0 数值。"""
    with pytest.raises(ValueError):
        validate_setup_config({"convergence_delta": raw})


def test_non_mapping_setup_config_rejected():
    with pytest.raises(ValueError, match="dict/Mapping"):
        validate_setup_config(None)  # type: ignore[arg-type]


# ─── P1：导出失败保留工程 + 结构化错误 ────────────────────────────────────────


class _FakeSimProfile:
    def __init__(self, status: str):
        self.status = status


class _FakeProfiles(dict):
    pass


class _FakeSetupSolved:
    is_solved = True

    def get_profile(self):
        return None


class _FakeHfssForExport:
    """求解完成态假会话（profile 绿 + is_solved 绿），导出面可注入失败。"""

    are_there_simulations_running = False

    def __init__(self, export_raises: Exception):
        self._export_raises = export_raises
        self.ports = ["P1", "P2"]
        self.osolution = object()
        self.working_directory = None
        self.project_path = None
        self.project_name = "proj"
        self.design_name = "d"
        self.save_calls = 0
        self.export_calls = 0

    def get_profile(self, name):
        return _FakeProfiles({"s1": _FakeSimProfile("Normal Completion")})

    def get_setup(self, name):
        return _FakeSetupSolved()

    def get_setups(self):
        return ["Setup1"]

    def get_sweeps(self, name):
        return ["Sweep1"]

    def save_project(self):
        self.save_calls += 1

    def export_touchstone(self, setup=None, sweep=None, output_file=None):
        self.export_calls += 1
        raise self._export_raises


def _make_export_adapter(adapter, tmp_path, export_raises):
    proj = tmp_path / "work" / "demo.aedt"
    proj.parent.mkdir(parents=True, exist_ok=True)
    payload = b"PK\x03\x04 fake aedt project payload"
    proj.write_bytes(payload)
    hfss = _FakeHfssForExport(export_raises)
    adapter.session.hfss = hfss
    adapter._project_path = proj
    adapter._design_name = "Design1"
    return proj, payload, hfss


def test_export_failure_preserves_project_and_structured_error(adapter, tmp_path,
                                                               monkeypatch):
    """P1 主契约：导出失败路径零 save/覆盖/删除，错误结构化含建议动作。"""
    proj, payload, hfss = _make_export_adapter(
        adapter, tmp_path, RuntimeError("GrpcApiError: ExportNetworkData"))

    def _boom(hfss_, setup_name, sweep_name, path):
        raise RuntimeError("GrpcApiError: ExportNetworkData")

    monkeypatch.setattr(HfssAdapter, "_direct_export_touchstone",
                        staticmethod(_boom))
    (tmp_path / "out").mkdir()
    target = tmp_path / "out" / "params.s2p"

    with pytest.raises(ModelBuildError) as ei:
        adapter.export_touchstone(target)

    msg = str(ei.value)
    # 结构化错误面：工程绝对路径 + 设计名 + setup + 建议动作（同会话重试/
    # 重跑 build+solve）
    assert str(proj) in msg
    assert "Design1" in msg
    assert "Setup1" in msg
    assert "同会话" in msg
    assert "build+solve" in msg
    assert ei.value.details["project"] == str(proj)
    assert ei.value.details["design"] == "Design1"
    # 工程文件字节保真（失败路径无覆盖/删除/截断）
    assert proj.exists()
    assert proj.read_bytes() == payload
    # 失败路径零 save_project（导出链只读）
    assert hfss.save_calls == 0
    assert ei.value.details["project_file_post"] is not None


def test_export_failure_reports_session_resave(adapter, tmp_path, monkeypatch):
    """导出尝试期间工程文件被会话重存 → 错误如实区分（不冒充未触碰）。"""
    proj, _payload, _hfss = _make_export_adapter(
        adapter, tmp_path, RuntimeError("GrpcApiError"))

    def _boom_and_touch(hfss_, setup_name, sweep_name, path):
        # 模拟 AEDT 会话内部重存（大小+mtime 变化）
        with open(proj, "ab") as fh:
            fh.write(b"-resaved")
        raise RuntimeError("GrpcApiError")

    monkeypatch.setattr(HfssAdapter, "_direct_export_touchstone",
                        staticmethod(_boom_and_touch))
    (tmp_path / "out").mkdir()

    with pytest.raises(ModelBuildError) as ei:
        adapter.export_touchstone(tmp_path / "out" / "params.s2p")

    assert "重存" in str(ei.value)
    assert ei.value.details["project_file_pre"][1:] != \
        ei.value.details["project_file_post"][1:]


# ─── P5：CJK 工程路径守卫 + ascii_workdir 重定向交付 ─────────────────────────


class _FakeOdesignReady:
    def GetVariables(self):
        return ["x"]  # 就绪窗探测立即通过（零 sleep）


class _FakeHfssCtor:
    """模拟 ansys.aedt.core.Hfss 构造：记录 kwargs。"""

    last_kwargs: dict | None = None

    def __init__(self, **kwargs):
        _FakeHfssCtor.last_kwargs = kwargs
        self.odesign = _FakeOdesignReady()


@pytest.fixture()
def fake_hfss_cls(monkeypatch):
    monkeypatch.setattr(hfss_adapter_mod, "_Hfss", _FakeHfssCtor,
                        raising=False)
    _FakeHfssCtor.last_kwargs = None
    return _FakeHfssCtor


def test_has_non_ascii_and_workdir_determinism():
    assert has_non_ascii(Path("D:/IPD调研/p.aedt")) is True
    assert has_non_ascii(Path("D:/work/p.aedt")) is False
    w1 = ascii_workdir_path("D:/IPD调研/p.aedt")
    w2 = ascii_workdir_path("D:/IPD调研/p.aedt")
    assert w1 == w2, "同一原路径摘要确定（reopen 语义）"
    assert not has_non_ascii(w1)
    assert w1.name == "rfauto_work.aedt"


def test_cjk_path_default_raises_before_any_state(adapter, tmp_path):
    """P5 缺省形态：非 ASCII 路径 ValueError，守卫先于状态写入/目录创建。"""
    cjk = tmp_path / "IPD调研" / "demo.aedt"
    with pytest.raises(ValueError) as ei:
        adapter.open_or_create_project(cjk, "D1")
    assert "ascii_workdir" in str(ei.value)
    assert "macro error" in str(ei.value)
    assert adapter._project_path is None
    assert adapter._design_name is None
    assert adapter._ascii_delivery is None
    assert not cjk.parent.exists(), "守卫须先于父目录创建"


def test_cjk_path_optin_redirect_and_delivery(adapter, tmp_path, fake_hfss_cls):
    """opt-in：重定向 %TEMP% ASCII 工作目录，close 交付 .aedt+.aedtresults。"""
    original = tmp_path / "IPD调研" / "demo.aedt"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"PK\x03\x04 fake-aedt-v1")
    adapter.session._settings = {"ascii_workdir": True}

    adapter.open_or_create_project(original, "Design1")

    work = adapter._project_path
    assert work is not None and not has_non_ascii(work)
    assert work.parent.parent.parent == Path(tempfile.gettempdir())
    assert adapter._ascii_delivery == (work, original)
    assert fake_hfss_cls.last_kwargs["project"] == str(work)
    assert work.read_bytes() == b"PK\x03\x04 fake-aedt-v1", "原工程播到工作副本"

    # 模拟会话内求解+保存：工作副本被覆写 + 旁路 .aedtresults 产物
    work.write_bytes(b"solved-aedt-v2")
    results = work.parent / "rfauto_work.aedtresults" / "Design1.results"
    results.mkdir(parents=True)
    (results / "profile.prof").write_text("***status: Normal", encoding="utf-8")

    adapter.close()

    # 交付拷回：.aedt 新解 + results 整目录落到原目标（CJK 路径）
    assert original.read_bytes() == b"solved-aedt-v2"
    delivered = original.parent / "demo.aedtresults" / "Design1.results" / \
        "profile.prof"
    assert delivered.read_text(encoding="utf-8") == "***status: Normal"
    assert adapter._ascii_delivery is None
    # 工作副本永不删除（人工兜底面）
    assert work.exists()


def test_new_project_optin_no_seed_copy(adapter, tmp_path, fake_hfss_cls):
    """原工程不存在（新建）：只重定向零拷贝；未保存即 close=无物可交付，
    干净返回（原目标不凭空产生半成品）。"""
    original = tmp_path / "IPD调研" / "new.aedt"
    adapter.session._settings = {"ascii_workdir": True}

    adapter.open_or_create_project(original, "D1")
    work = adapter._project_path
    assert work is not None and not work.exists()

    adapter.close()  # 工作副本不存在 → 无物可交付告警路径，零错误
    assert not original.exists()
    assert adapter._ascii_delivery is None


def test_prepare_workdir_keeps_newer_work_copy(tmp_path):
    """工作副本比原工程新（疑似上次未交付）→ 保留工作副本（防丢数据）。"""
    original = tmp_path / "orig" / "a.aedt"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"v1")
    work = ascii_workdir_path(original)
    work.parent.mkdir(parents=True, exist_ok=True)
    work.write_bytes(b"v2-solved")
    os.utime(original, (1000, 1000))
    os.utime(work, (2000, 2000))

    out = prepare_ascii_workdir(original, work)
    assert out == work
    assert work.read_bytes() == b"v2-solved"


def test_prepare_workdir_refreshes_when_original_newer(tmp_path):
    """原工程比工作副本新（用户改了设计）→ 从原工程刷新。"""
    original = tmp_path / "orig" / "a.aedt"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"v2-edited")
    work = ascii_workdir_path(original)
    work.parent.mkdir(parents=True, exist_ok=True)
    work.write_bytes(b"v1-stale")
    os.utime(work, (1000, 1000))
    os.utime(original, (2000, 2000))

    prepare_ascii_workdir(original, work)
    assert work.read_bytes() == b"v2-edited"


def test_deliver_workdir_reports_per_file_errors(tmp_path, monkeypatch):
    """交付逐文件入账：.aedt 失败 + results 单文件失败都如实记账不抛。"""
    import shutil as _shutil

    work = tmp_path / "w" / "rfauto_work.aedt"
    work.parent.mkdir(parents=True)
    work.write_bytes(b"w")
    results = work.parent / "rfauto_work.aedtresults" / "d.results"
    results.mkdir(parents=True)
    (results / "ok.prof").write_text("ok", encoding="utf-8")
    original = tmp_path / "o" / "demo.aedt"

    real_copy2 = _shutil.copy2

    def _flaky_copy2(src, dst, **kw):
        if str(src).endswith("rfauto_work.aedt"):
            raise OSError("disk full")
        return real_copy2(src, dst, **kw)

    monkeypatch.setattr(_shutil, "copy2", _flaky_copy2)
    errors = deliver_ascii_workdir(work, original)
    # .aedt 主文件失败入账；results 内成功文件已交付
    assert any(".aedt 拷回失败" in e for e in errors)
    assert (original.parent / "demo.aedtresults" / "d.results" /
            "ok.prof").read_text(encoding="utf-8") == "ok"


def test_close_delivery_failure_raises_and_preserves_workdir(adapter, tmp_path,
                                                             monkeypatch):
    """交付失败如实抛（不静默），工作副本保留供人工兜底。"""
    work = tmp_path / "w" / "rfauto_work.aedt"
    work.parent.mkdir(parents=True)
    work.write_bytes(b"w")
    original = tmp_path / "o" / "demo.aedt"
    adapter._ascii_delivery = (work, original)
    # hfss_adapter 按值导入 deliver_ascii_workdir——补丁须打在消费侧引用
    monkeypatch.setattr(
        "rfauto.adapters.hfss_adapter.deliver_ascii_workdir",
        lambda w, o: [f".aedt 拷回失败: {w} -> {original}（disk full）"])

    with pytest.raises(ModelBuildError) as ei:
        adapter.close()
    assert "拷回失败" in str(ei.value)
    assert str(work.parent) in str(ei.value)
    assert ei.value.details["errors"]
    assert work.exists(), "工作副本永不删除"
    assert adapter._ascii_delivery is None


def test_cjk_path_remote_session_rejects(adapter, tmp_path):
    """远程会话=服务器侧路径语义，本地 %TEMP% 重定向不成立，显式拒绝。"""
    adapter.session._remote = {
        "name": "sim_server", "machine": "10.20.30.40",
        "port": 1055, "project_root": "E:/rfauto_remote", "version": "2025.1",
    }
    with pytest.raises(ValueError, match="服务器侧"):
        adapter.open_or_create_project("D:/IPD调研/demo.aedt", "D1")


# ─── hfss_batch 通道：零行为变化 + 导出段 CJK 定向失败 ───────────────────────


def test_batch_solve_cjk_path_unchanged(monkeypatch, tmp_path):
    """批处理 -BatchSolve 对 CJK 路径照常发射（零行为变化，仅提示）。"""
    proj = tmp_path / "IPD调研" / "demo.aedt"
    proj.parent.mkdir(parents=True)
    proj.write_bytes(b"x")
    monkeypatch.setattr(hb, "find_ansysedt_exe",
                        lambda explicit=None: Path("E:/fake/ansysedt.exe"))

    seen: dict = {}

    class _P:
        pid = 1

        def wait(self, timeout=None):
            return 0

    def _popen(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        return _P()

    monkeypatch.setattr(hb.subprocess, "Popen", _popen)
    res = hb.solve_project_batch(proj, timeout_s=60)
    assert res["ok"] is True
    assert res["rc"] == 0
    assert str(proj) in seen["cmd"], "工程路径原样发射（无重定向）"


def test_batch_export_cjk_project_structured_fail_no_launch(monkeypatch,
                                                            tmp_path):
    """-batchextract 导出段：CJK 工程名定向结构化失败，绝不拉起进程。"""
    proj = tmp_path / "IPD调研" / "demo.aedt"
    proj.parent.mkdir(parents=True)
    proj.write_bytes(b"x")
    monkeypatch.setattr(hb, "find_ansysedt_exe",
                        lambda explicit=None: Path("E:/fake/ansysedt.exe"))

    def _no_popen(cmd, **kwargs):
        raise AssertionError("CJK 路径不得拉起 -batchextract 进程")

    monkeypatch.setattr(hb.subprocess, "Popen", _no_popen)
    res = hb.export_touchstone_after_solve(proj)
    assert res["ok"] is False
    assert res["rc"] is None
    assert any("非 ASCII" in e for e in res["errors"])
    assert res["out_file"] is None
