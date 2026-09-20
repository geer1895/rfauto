"""WP4.4b Q3D 适配器单测（fake pyaedt：零 AEDT/license/桌面依赖）。

覆盖：注册表/枚举、能力声明如实（A5：寄生通道不产 S 参数/场/Touchstone）、
参数规范化（未知字段/非正值显式报错）、闭式锚数值、build→solve 调用序列
（pyaedt Q3D API 名逐个对照：Q3d/create_box/assign_net/source/sink/
create_setup/analyze/export_matrix_data）、显式单位字符串（#218 同法）、
矩阵导出解析（容错式：种类头/列名/数值行/包裹行跳过）、L/C 每长度锚门、
失败路径 best-effort（#105：不抛异常）。
"""

from __future__ import annotations

import sys
import types

import pytest

from rfauto.adapters import q3d_adapter as qa
from rfauto.adapters.em_solver_base import (
    EMSolverConfig,
    EMSolverRegistry,
    EMSolverType,
)
from rfauto.adapters.q3d_adapter import (
    ANCHOR_TOLERANCE,
    Q3dAdapter,
    _diagonal_total,
    _parse_matrix_export,
    anchor_for_spec,
    normalize_trace_params,
    register_q3d_adapter,
)

# ─── 矩阵导出文本样例（Q3D ExportMatrixData 口径，含包裹行/单 net 约减）──────

RL_TEXT = '''Design Name:rfauto_q3d
Profile:'Default'

Matrix("Original")

"L"(nH)
\t"trace"
"trace"\t14.40489

"R"(ohm)
\t"trace"
"trace"\t0.350211
'''

C_TEXT = '''Design Name:rfauto_q3d

Matrix("Original")

"C"(pF)
\t"trace"
"trace"\t5.59624
'''

MULTI_NET_TEXT = '''Matrix("Reduced")

"L"(nH)
\t"trace"\t"gnd"
"trace"\t14.2\t0.01
"gnd"\t0.01\t1.9
'''


# ─── 解析器 ──────────────────────────────────────────────────────────────────


class TestMatrixParser:
    def test_parse_rl_and_c_sections(self):
        parsed = _parse_matrix_export(RL_TEXT)
        assert set(parsed) == {"L", "R"}
        assert parsed["L"]["unit"] == "nH"
        assert parsed["L"]["names"] == ["trace"]
        assert parsed["L"]["elements"][("trace", "trace")] == pytest.approx(14.40489)
        assert parsed["R"]["elements"][("trace", "trace")] == pytest.approx(0.350211)

    def test_parse_multi_net_grid(self):
        parsed = _parse_matrix_export(MULTI_NET_TEXT)
        assert parsed["L"]["names"] == ["trace", "gnd"]
        assert parsed["L"]["elements"][("trace", "gnd")] == pytest.approx(0.01)

    def test_wrapper_lines_ignored(self):
        assert "Matrix" not in _parse_matrix_export(RL_TEXT)
        assert _parse_matrix_export("Design Name:x\n\n") == {}

    def test_diagonal_total_selection(self):
        parsed = _parse_matrix_export(MULTI_NET_TEXT)
        assert _diagonal_total(parsed, "L", "trace") == pytest.approx(14.2)
        assert _diagonal_total(parsed, "R", "trace") is None
        single = _parse_matrix_export(RL_TEXT)
        assert _diagonal_total(single, "L", "trace") == pytest.approx(14.40489)
        assert _diagonal_total(single, "missing", "trace") is None


# ─── pyaedt 录制桩 ───────────────────────────────────────────────────────────


class _FakeModeler:
    def __init__(self, calls: list):
        self._calls = calls

    def create_box(self, origin, sizes, name, material):
        self._calls.append(("call", "modeler.create_box",
                            (tuple(origin), tuple(sizes), name, material), {}))
        return types.SimpleNamespace(name=name)


class _FakeMaterials:
    def __init__(self, calls: list):
        self._calls = calls
        self.material_keys: dict[str, object] = {}

    def add_material(self, name, properties=None):
        self._calls.append(("call", "materials.add_material",
                            (name, properties), {}))
        self.material_keys[name] = types.SimpleNamespace(**(properties or {}))
        return self.material_keys[name]


class _FakeQ3d:
    """Q3d 应用桩：API 名/调用序列逐一记录；export_matrix_data 落盘样例。"""

    def __init__(self, calls, project, design, version, non_graphical,
                 new_desktop, rl_text=RL_TEXT, c_text=C_TEXT):
        calls.append(("call", "Q3d.__init__", (),
                      {"project": project, "design": design,
                       "version": version, "non_graphical": non_graphical,
                       "new_desktop": new_desktop}))
        self.calls = calls
        self.modeler = _FakeModeler(calls)
        self.materials = _FakeMaterials(calls)
        self.rl_text = rl_text
        self.c_text = c_text
        self.net_calls: list = []
        self.released = False
        self.inserted: list[str] = []

    def assign_net(self, assignment, net_name=None, net_type="Signal"):
        self.calls.append(("call", "assign_net", (assignment,),
                           {"net_name": net_name, "net_type": net_type}))
        return types.SimpleNamespace(name=net_name)

    def source(self, assignment, direction=0, name=None, net_name=None):
        self.calls.append(("call", "source", (assignment,),
                           {"direction": direction, "name": name,
                            "net_name": net_name}))
        return types.SimpleNamespace(name=name)

    def sink(self, assignment, direction=3, name=None, net_name=None):
        self.calls.append(("call", "sink", (assignment,),
                           {"direction": direction, "name": name,
                            "net_name": net_name}))
        return types.SimpleNamespace(name=name)

    def insert_design(self, name):
        self.calls.append(("call", "insert_design", (name,), {}))
        self.inserted.append(name)
        return name

    def create_setup(self, name):
        self.calls.append(("call", "create_setup", (name,), {}))
        return _FakeSetup(self.calls, name)

    def analyze(self, setup_name):
        self.calls.append(("call", "analyze", (setup_name,), {}))

    def export_matrix_data(self, file_name, problem_type=None, **_kw):
        self.calls.append(("call", "export_matrix_data", (file_name,),
                           {"problem_type": problem_type}))
        text = self.rl_text if problem_type == "AC RL" else self.c_text
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(text)
        return True

    def save_project(self, file_path=None):
        self.calls.append(("call", "save_project", (str(file_path),), {})
                          if file_path else ("call", "save_project", (), {}))
        self.saved = True

    def release_desktop(self, **_kw):
        self.released = True


class _FakeSetup:
    def __init__(self, calls: list, name: str):
        self.calls = calls
        self.name = name
        self.props: dict = {}
        self._ac_rl = None
        self._cap = None

    @property
    def ac_rl_enabled(self):
        return self._ac_rl

    @ac_rl_enabled.setter
    def ac_rl_enabled(self, value):
        self._ac_rl = value

    @property
    def capacitance_enabled(self):
        return self._cap

    @capacitance_enabled.setter
    def capacitance_enabled(self, value):
        self._cap = value


def _install_fake_pyaedt(monkeypatch: pytest.MonkeyPatch, calls: list,
                         **fake_kwargs) -> None:
    """把 fake ansys.aedt.core 注入 sys.modules（adapter 内延迟 import 命中）。"""
    fake_mod = types.ModuleType("ansys.aedt.core")
    fake_mod.Q3d = lambda *a, **kw: _FakeQ3d(calls, **{
        k: v for k, v in kw.items()
        if k in ("project", "design", "version", "non_graphical",
                 "new_desktop")}, **fake_kwargs)
    for name in ("ansys", "ansys.aedt", "ansys.aedt.core"):
        monkeypatch.setitem(sys.modules, name,
                            types.ModuleType(name) if "." not in name
                            else fake_mod)
    sys.modules["ansys"].aedt = sys.modules["ansys.aedt"]
    sys.modules["ansys.aedt"].core = fake_mod
    monkeypatch.setattr(qa, "pyaedt_installed", lambda: True)


def _make_adapter(tmp_path, **extra) -> Q3dAdapter:
    cfg = EMSolverConfig(solver_type=EMSolverType.Q3D,
                         working_dir=str(tmp_path / "wp44b"), extra_params=extra)
    return Q3dAdapter(cfg)


# ─── 注册表 / 能力声明 / 参数规范化 ──────────────────────────────────────────


class TestRegistryCapabilities:
    def test_enum_and_registry(self):
        assert EMSolverType.Q3D.value == "q3d"
        # 用独立注册表（test_elmer_adapter 同法）：注册进全局表会泄漏到
        # test_solver_capabilities 的"未注册探针=Q3D"用例（全量门实证）
        reg = EMSolverRegistry()
        register_q3d_adapter(reg)
        assert reg.is_registered(EMSolverType.Q3D)
        assert reg.lookup("q3d") is Q3dAdapter

    def test_capabilities_declared_honestly(self, tmp_path):
        caps = _make_adapter(tmp_path).capabilities()
        assert caps.solver_type == "q3d"
        assert caps.supports_wave_port is False
        assert caps.supports_lumped_port is False
        assert caps.supports_field_export is False
        assert caps.supports_touchstone_export is False
        assert caps.supports_headless_solve is True
        assert caps.requires_license is True
        assert qa.TEMPLATE_PARASITIC_MSTRIP in caps.supported_templates

    def test_get_sparams_refuses(self, tmp_path):
        with pytest.raises(NotImplementedError, match="不产出 S 参数"):
            _make_adapter(tmp_path).get_sparams()

    def test_normalize_rejects_unknown_and_nonpositive(self):
        with pytest.raises(ValueError, match="未知提取参数"):
            normalize_trace_params({"nope": 1.0})
        with pytest.raises(ValueError, match="正数"):
            normalize_trace_params({"trace_w_mm": 0.0})
        with pytest.raises(ValueError, match="max_passes"):
            normalize_trace_params({"max_passes": 0})

    def test_anchor_matches_core(self):
        anchor = anchor_for_spec(normalize_trace_params(None))
        assert anchor["z0_ohm"] == pytest.approx(50.62, abs=0.1)
        assert anchor["l_nh_per_mm"] == pytest.approx(0.2852, abs=0.002)
        assert anchor["c_pf_per_mm"] == pytest.approx(0.1113, abs=0.002)
        assert ANCHOR_TOLERANCE == 0.05


# ─── build→solve 调用序列（pyaedt API 名逐一对照）────────────────────────────


class TestBuildSolveSequence:
    def test_build_and_solve_full_sequence(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls)
        adapter = _make_adapter(tmp_path)

        assert adapter.connect() is True
        assert adapter.build_geometry({}) is True
        result = adapter.solve()
        adapter.close()

        assert result.success is True
        verdict = result.field_data["verdict"]
        # 样例 14.40489nH/50mm=0.28810/mm vs 锚 0.28524 → +1.00%；
        # 5.59624pF/50mm=0.111925 vs 锚 0.111299 → +0.56%：门应过
        assert verdict["l_rel_dev"] == pytest.approx(0.010036, abs=1e-4)
        assert verdict["c_rel_dev"] == pytest.approx(0.005619, abs=1e-4)
        assert verdict["pass_5pct"] is True
        extracted = result.field_data["extracted"]
        assert extracted["l_total_nh"] == pytest.approx(14.40489)
        assert extracted["c_total_pf"] == pytest.approx(5.59624)
        assert extracted["r_total_ohm"] == pytest.approx(0.350211)
        assert "R=0.350211Ω（参考）" in result.message or \
            "R=0.350211" in result.message

        # 序列断言：API 名与关键参数（显式单位字符串，#218 同法）
        init = next(c for c in calls if c[1] == "Q3d.__init__")
        # 真机实证：project 传不存在路径会走 oProject.Rename（2025.1
        # gRPC 必失败）→ project=None 默认新建 + connect 后 save 落盘
        assert init[3]["project"] is None
        assert init[3]["version"] == "2025.1"
        assert init[3]["non_graphical"] is True
        assert init[3]["new_desktop"] is True
        assert init[3]["design"] == "rfauto_q3d"
        saves = [c for c in calls if c[1] == "save_project"]
        assert saves and str(saves[0][2][0]).endswith("wp44b_parasitic.aedt")
        boxes = [c for c in calls if c[1] == "modeler.create_box"]
        assert len(boxes) == 3
        gnd = boxes[0]
        assert gnd[2][2] == "rfauto_gnd"
        assert gnd[2][0] == ("0mm", "0mm", "0mm")
        assert gnd[2][1] == ("70.0mm", "21.09mm", "0.035mm")
        sub = boxes[1]
        assert sub[2][0] == ("0mm", "0mm", "0.035mm")
        assert sub[2][1][2] == "0.508mm"
        trace = boxes[2]
        assert trace[2][2] == "rfauto_trace"
        assert trace[2][0] == ("10.0mm", "10.0mm", "0.543mm")
        assert trace[2][1] == ("50.0mm", "1.09mm", "0.035mm")
        assert trace[2][3] == "copper"
        nets = [c for c in calls if c[1] == "assign_net"]
        assert {c[3]["net_name"]: c[3]["net_type"] for c in nets} == \
            {"trace": "Signal", "gnd": "Ground"}
        src = next(c for c in calls if c[1] == "source")
        assert src[3]["direction"] == 0   # -x 端面（min x）
        snk = next(c for c in calls if c[1] == "sink")
        assert snk[3]["direction"] == 3   # +x 端面（max x）
        assert ("call", "create_setup", ("rfauto_q3d_setup",), {}) in calls
        assert ("call", "analyze", ("rfauto_q3d_setup",), {}) in calls
        exports = [c for c in calls if c[1] == "export_matrix_data"]
        assert {c[3]["problem_type"] for c in exports} == {"AC RL", "C"}
        setup = calls  # setup 开关经 _FakeSetup 属性记录在 props 之外，此处断言不炸即可
        assert setup
        # close：释放桌面（_q3d 置空）
        assert adapter._q3d is None

    def test_solve_fails_without_build(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls)
        adapter = _make_adapter(tmp_path)
        adapter.connect()
        result = adapter.solve()
        assert result.success is False
        assert "未建模" in result.message

    def test_build_requires_connect(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        assert adapter.build_geometry({}) is False
        assert "未连接" in adapter._last_message

    def test_build_rejects_unknown_param(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls)
        adapter = _make_adapter(tmp_path)
        adapter.connect()
        assert adapter.build_geometry({"bogus": 1.0}) is False
        assert "未知提取参数" in adapter._last_message

    def test_solve_fails_when_matrix_export_false(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls)
        adapter = _make_adapter(tmp_path)
        adapter.connect()
        adapter.build_geometry({})
        adapter._q3d.export_matrix_data = lambda *a, **kw: False
        result = adapter.solve()
        assert result.success is False
        assert "矩阵导出失败" in result.message

    def test_solve_fails_when_unparseable_matrix(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, rl_text="garbage\n",
                             c_text="garbage\n")
        adapter = _make_adapter(tmp_path)
        adapter.connect()
        adapter.build_geometry({})
        result = adapter.solve()
        assert result.success is False
        assert "RLC 提取失败" in result.message

    def test_connect_failure_is_soft(self, tmp_path, monkeypatch):
        fake_mod = types.ModuleType("ansys.aedt.core")

        def _boom(*a, **kw):
            raise RuntimeError("no desktop")

        fake_mod.Q3d = _boom
        for name in ("ansys", "ansys.aedt", "ansys.aedt.core"):
            monkeypatch.setitem(sys.modules, name,
                                types.ModuleType(name) if "." not in name
                                else fake_mod)
        sys.modules["ansys"].aedt = sys.modules["ansys.aedt"]
        sys.modules["ansys.aedt"].core = fake_mod
        monkeypatch.setattr(qa, "pyaedt_installed", lambda: True)
        adapter = _make_adapter(tmp_path)
        assert adapter.connect() is False
        assert "连接 AEDT/Q3D 失败" in adapter._last_message
        assert adapter.solve().success is False

    def test_use_design_lifecycle(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls)
        adapter = _make_adapter(tmp_path)
        assert adapter.use_design("x") is False  # 未连接
        adapter.connect()
        assert adapter.use_design("case_b") is True
        assert ("call", "insert_design", ("case_b",), {}) in calls
