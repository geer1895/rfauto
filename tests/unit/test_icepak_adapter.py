"""WP4.4a Icepak 适配器单测（fake pyaedt：零 AEDT/license/桌面依赖）。

覆盖：注册表/枚举、能力声明如实（A5：热通道不产 S 参数）、参数规范化
（未知字段/非正值显式报错）、1-D 传导锚闭式、build→solve 调用序列
（pyaedt Icepak API 名逐个对照：create_box/assign_stationary_wall_with_
temperature/assign_solid_block/assign_point_monitor_in_object/create_setup/
analyze/evaluate_monitor_quantity）、显式单位字符串（#218 同法）、温度
提取解析、失败路径 best-effort（#105：不抛异常）。
"""

from __future__ import annotations

import sys
import types

import pytest

from rfauto.adapters import icepak_adapter as ia
from rfauto.adapters.em_solver_base import (
    EMSolverConfig,
    EMSolverType,
    get_global_registry,
)
from rfauto.adapters.icepak_adapter import (
    ANCHOR_TOLERANCE,
    IcepakAdapter,
    anchor_closed_form_c,
    normalize_stack_params,
    register_icepak_adapter,
)

# ─── pyaedt 录制桩（任意属性→可调用→返回子桩，调用记入共享列表）──────────────


class _Recorder:
    def __init__(self, calls: list, path: str = "", value: object = None):
        self._calls = calls
        self._path = path
        self._value = value

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        full = f"{self._path}.{name}" if self._path else name
        self._calls.append(("attr", full))
        return _Recorder(self._calls, full)

    def __call__(self, *args, **kwargs):
        self._calls.append(("call", self._path, args, kwargs))
        return _Recorder(self._calls, self._path)


class _FakeModeler(_Recorder):
    """模型器桩：create_box 返回具名对象；get_object_faces 按物体定制。"""

    def create_box(self, origin, sizes, name, material):
        self._calls.append(("call", "modeler.create_box",
                            (tuple(origin), tuple(sizes), name, material), {}))
        return types.SimpleNamespace(name=name)

    def get_object_faces(self, name):
        self._calls.append(("call", "modeler.get_object_faces", (name,), {}))
        if name == "Region":
            return [201, 202, 203, 204, 205, 206]
        return [101, 102, 103, 104, 105, 106]

    def get_face_center(self, face_id):
        centers = {101: [10.0, 10.0, 0.0], 102: [10.0, 10.0, 0.508],
                   103: [0.0, 10.0, 0.254], 104: [20.0, 10.0, 0.254],
                   105: [10.0, 0.0, 0.254], 106: [10.0, 20.0, 0.254],
                   # 空气域（10mm 六向填充）六面面心：字符串带单位形态
                   201: ["10mm", "10mm", "-10mm"], 202: ["10mm", "10mm", "10.658mm"],
                   203: ["-10mm", "10mm", "0.329mm"], 204: ["30mm", "10mm", "0.329mm"],
                   205: ["10mm", "-10mm", "0.329mm"], 206: ["10mm", "30mm", "0.329mm"]}
        return centers[int(face_id)]

    def create_region(self, pad_value, pad_type="Percentage Offset", name="Region"):
        self._calls.append(("call", "modeler.create_region",
                            (tuple(pad_value),),
                            {"pad_type": pad_type, "name": name}))
        return types.SimpleNamespace(name=name)

    def create_cylinder(self, orientation, origin, radius, height, name, material):
        self._calls.append(("call", "modeler.create_cylinder",
                            (orientation, tuple(origin), radius, height, name,
                             material), {}))
        return types.SimpleNamespace(name=name)

    def subtract(self, blank, tools, keep_originals=False):
        self._calls.append(("call", "modeler.subtract",
                            (blank, tuple(tools)),
                            {"keep_originals": keep_originals}))
        return True


class _FakeMaterials:
    def __init__(self, calls):
        self._calls = calls
        self.material_keys: dict[str, object] = {}

    def add_material(self, name, properties=None):
        self._calls.append(("call", "materials.add_material", (name, properties), {}))
        self.material_keys[name] = types.SimpleNamespace(**(properties or {}))
        return self.material_keys[name]


class _FakeMonitor:
    """监控模块桩（pyaedt Monitor.assign_face_monitor 口径：face id/list）。"""

    def __init__(self, calls):
        self._calls = calls

    def assign_face_monitor(self, face_id, monitor_quantity="Temperature",
                            monitor_name=None):
        self._calls.append(("call", "monitor.assign_face_monitor",
                            (face_id if isinstance(face_id, list) else [face_id],),
                            {"monitor_quantity": monitor_quantity,
                             "monitor_name": monitor_name}))
        if isinstance(face_id, list):
            return [f"{monitor_name}_{i}" for i in range(len(face_id))]
        return monitor_name


class _FakeGlobalRegion:
    """mesh.global_mesh_region.global_region 桩：object=None 表示无自动
    Region（走 create_region）；给了 object 则记录填充 setter。"""

    def __init__(self, calls, region_obj=None):
        self._calls = calls
        self.object = region_obj

    @property
    def padding_types(self):
        return None

    @padding_types.setter
    def padding_types(self, values):
        self._calls.append(("call", "global_region.padding_types",
                            (tuple(values),), {}))

    @property
    def padding_values(self):
        return None

    @padding_values.setter
    def padding_values(self, values):
        self._calls.append(("call", "global_region.padding_values",
                            (tuple(values),), {}))


class _FakeIcepak:
    """Icepak 应用桩：API 名/调用序列逐一记录，供序列断言。"""

    def __init__(self, calls, project, design, version, non_graphical,
                 new_desktop, **_kw):
        calls.append(("call", "Icepak.__init__",
                      (), {"project": project, "design": design,
                           "version": version, "non_graphical": non_graphical,
                           "new_desktop": new_desktop}))
        self.calls = calls
        self.design_name = design
        self.modeler = _FakeModeler(calls, "modeler")
        self.materials = _FakeMaterials(calls)
        self.monitor = _FakeMonitor(calls)
        self.mesh = types.SimpleNamespace(
            global_mesh_region=types.SimpleNamespace(
                global_region=_FakeGlobalRegion(calls)))
        self.problem_type = None
        self.design_settings: dict = {}
        self.saved = False
        self.released = False

    def assign_surface_monitor(self, face_name, monitor_type="Temperature",
                               monitor_name=None):
        self.calls.append(("call", "assign_surface_monitor", (face_name,),
                           {"monitor_type": monitor_type,
                            "monitor_name": monitor_name}))
        return monitor_name

    def assign_stationary_wall_with_temperature(self, geometry, name=None,
                                                temperature="0cel", **_kw):
        self.calls.append(("call", "assign_stationary_wall_with_temperature",
                           (geometry,), {"temperature": temperature}))
        return types.SimpleNamespace(name=name or "Wall")

    def assign_solid_block(self, object_name, power_assignment, **_kw):
        self.calls.append(("call", "assign_solid_block",
                           (object_name, power_assignment), {}))
        return types.SimpleNamespace(name="Block")

    def assign_point_monitor_in_object(self, name, monitor_type="Temperature",
                                       monitor_name=None):
        self.calls.append(("call", "assign_point_monitor_in_object",
                           (name,), {"monitor_type": monitor_type,
                                     "monitor_name": monitor_name}))
        return monitor_name

    def assign_point_monitor(self, position, monitor_type="Temperature",
                             monitor_name=None):
        self.calls.append(("call", "assign_point_monitor",
                           (tuple(position),),
                           {"monitor_type": monitor_type,
                            "monitor_name": monitor_name}))
        return monitor_name

    def edit_design_settings(self, gravity_dir=0, ambient_temperature=20, **_kw):
        self.calls.append(("call", "edit_design_settings",
                           (gravity_dir, ambient_temperature), {}))
        self.design_settings = {"gravity_dir": gravity_dir,
                                "ambient_temperature": ambient_temperature}
        return True

    def assign_openings(self, air_faces):
        self.calls.append(("call", "assign_openings",
                           (tuple(air_faces),), {}))
        return types.SimpleNamespace(name="Opening1")

    def insert_design(self, name):
        self.calls.append(("call", "insert_design", (name,), {}))
        self.design_name = name
        return name

    def create_setup(self, name):
        self.calls.append(("call", "create_setup", (name,), {}))
        self.last_setup = types.SimpleNamespace(name=name, props={})
        return self.last_setup

    def analyze(self, setup_name):
        self.calls.append(("call", "analyze", (setup_name,), {}))
        return True

    def globalMeshSettings(self, meshtype, **_kw):
        self.calls.append(("call", "globalMeshSettings", (meshtype,), {}))
        return True

    def save_project(self):
        self.saved = True

    def release_desktop(self, **_kw):
        self.released = True


def _install_fake_pyaedt(monkeypatch: pytest.MonkeyPatch, calls: list,
                         monitor_report: dict) -> None:
    """把 fake ansys.aedt.core 注入 sys.modules（adapter 内延迟 import 命中）。"""
    fake_mod = types.ModuleType("ansys.aedt.core")

    def _make_ipk(*args, **kwargs):
        app = _FakeIcepak(calls, **{
            k: v for k, v in kwargs.items()
            if k in ("project", "design", "version", "non_graphical",
                     "new_desktop")})
        app._monitor_report = monitor_report
        # post.evaluate_monitor_quantity 返回预置报告；monitor_report 也可
        # 是 {监控名: 报告} 逐监控预置（缺失键回退整份报告，兼容旧用例）
        class _Post:
            @staticmethod
            def evaluate_monitor_quantity(**kw):
                calls.append(("call", "post.evaluate_monitor_quantity", (), kw))
                report = app._monitor_report
                if isinstance(report, dict):
                    return report.get(kw.get("monitor"), report)
                return report

            @staticmethod
            def evaluate_boundary_quantity(**kw):
                calls.append(("call", "post.evaluate_boundary_quantity", (), kw))
                report = app._monitor_report
                if isinstance(report, dict):
                    return report.get(kw.get("boundary"), {})
                return report

        app.post = _Post()
        return app

    fake_mod.Icepak = _make_ipk
    for name in ("ansys", "ansys.aedt", "ansys.aedt.core"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name)
                            if "." not in name else fake_mod)
    sys.modules["ansys"].aedt = sys.modules["ansys.aedt"]
    sys.modules["ansys.aedt"].core = fake_mod
    monkeypatch.setattr(ia, "pyaedt_installed", lambda: True)


def _make_adapter(tmp_path, **extra) -> IcepakAdapter:
    cfg = EMSolverConfig(solver_type=EMSolverType.ICEPAK,
                         working_dir=str(tmp_path / "wp44a"), extra_params=extra)
    return IcepakAdapter(cfg)


# ─── 注册表 / 能力声明 ───────────────────────────────────────────────────────


class TestRegistryAndCapabilities:
    def test_enum_and_registry(self):
        assert EMSolverType.ICEPAK.value == "icepak"
        reg = get_global_registry()
        register_icepak_adapter(reg)
        assert reg.is_registered(EMSolverType.ICEPAK)
        cls = reg.lookup("icepak")
        assert cls is IcepakAdapter

    def test_capabilities_declared_honestly(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        caps = adapter.capabilities()
        assert caps.solver_type == "icepak"
        assert caps.supports_field_export is True
        assert caps.supports_touchstone_export is False
        assert caps.supports_wave_port is False
        assert caps.supports_headless_solve is True
        assert caps.requires_license is True
        assert ia.TEMPLATE_CONDUCTION_STACK in caps.supported_templates

    def test_get_sparams_refuses(self, tmp_path):
        with pytest.raises(NotImplementedError, match="不产出 S 参数"):
            _make_adapter(tmp_path).get_sparams()


# ─── 参数规范化 / 闭式锚 ─────────────────────────────────────────────────────


class TestNormalizeAndAnchor:
    def test_defaults_and_partial_update(self):
        spec = normalize_stack_params({"power_w": 0.25})
        assert spec["board_thk_mm"] == 0.508
        assert spec["power_w"] == 0.25

    def test_unknown_key_rejected(self):
        with pytest.raises(ValueError, match="未知模板参数"):
            normalize_stack_params({"nope": 1.0})

    def test_nonpositive_rejected(self):
        with pytest.raises(ValueError, match="正数"):
            normalize_stack_params({"power_w": 0.0})

    def test_anchor_closed_form_matches_core(self):
        spec = normalize_stack_params(None)
        anchor = anchor_closed_form_c(spec)
        assert anchor["rise_k"] == pytest.approx(1.68125)
        assert anchor["t_monitor_c"] == pytest.approx(25.0 + 1.68125)


# ─── build→solve 调用序列（pyaedt API 名逐一对照）────────────────────────────


class TestBuildSolveSequence:
    def test_build_and_solve_full_sequence(self, tmp_path, monkeypatch):
        calls: list = []
        # 监控点温升 = 闭式锚温升 × 1.005（+0.5% 偏差）→ 门应过
        anchor = anchor_closed_form_c(normalize_stack_params(None))
        t_sim = 25.0 + anchor["rise_k"] * 1.005
        report = {"Mean": t_sim, "Unit": "cel"}
        _install_fake_pyaedt(monkeypatch, calls, report)
        adapter = _make_adapter(tmp_path)

        assert adapter.connect() is True
        assert adapter.build_geometry({"power_w": 0.5}) is True
        result = adapter.solve()
        adapter.close()

        assert result.success is True
        assert result.field_data["t_blk_c"] == pytest.approx(t_sim)
        anchor_out = result.field_data["anchor"]
        assert anchor_out["relative_deviation"] == pytest.approx(0.005, rel=1e-6)
        assert anchor_out["pass_2pct"] is True
        assert ANCHOR_TOLERANCE == 0.02

        # 序列断言：API 名与关键参数（显式单位字符串，#218 同法）
        kinds = [c[1] for c in calls]
        assert "Icepak.__init__" in kinds
        init = next(c for c in calls if c[1] == "Icepak.__init__")
        assert init[3]["version"] == "2025.1"
        assert init[3]["non_graphical"] is True
        assert init[3]["new_desktop"] is True
        assert init[3]["design"] == "rfauto_et"
        boxes = [c for c in calls if c[1] == "modeler.create_box"]
        assert len(boxes) == 2
        # 基板：z 从 0mm 起，厚度显式 mm
        sub = next(c for c in boxes if c[2][2] == "rfauto_sub")
        assert sub[2][0] == ("0mm", "0mm", "0mm")
        assert sub[2][1][2] == "0.508mm"
        # 发热块：置于基板顶面（z=board_thk），满覆足印
        blk = next(c for c in boxes if c[2][2] == "rfauto_blk")
        assert blk[2][0][2] == "0.508mm"
        assert blk[2][1] == ("20.0mm", "20.0mm", "0.15mm")
        assert kinds.count("materials.add_material") == 2
        wall = next(c for c in calls
                    if c[1] == "assign_stationary_wall_with_temperature")
        assert wall[2][0] == 101  # z≈0 的底面 id
        assert wall[3]["temperature"] == "25.0cel"
        block = next(c for c in calls if c[1] == "assign_solid_block")
        assert block[2] == ("rfauto_blk", "0.5W")
        monitor = next(c for c in calls if c[1] == "assign_point_monitor_in_object")
        assert monitor[2] == ("rfauto_blk",)
        assert monitor[3]["monitor_name"] == "rfauto_T_blk"
        assert ("call", "create_setup", ("rfauto_et_setup",), {}) in calls
        assert ("call", "analyze", ("rfauto_et_setup",), {}) in calls
        assert any(c[1] == "post.evaluate_monitor_quantity" for c in calls)
        # close：释放桌面（_ipk 置空）
        assert adapter._ipk is None

    def test_solve_fails_without_build(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, {"Mean": 60.0})
        adapter = _make_adapter(tmp_path)
        adapter.connect()
        result = adapter.solve()
        assert result.success is False
        assert "未建模" in result.message

    def test_build_rejects_oversized_block(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, {})
        adapter = _make_adapter(tmp_path)
        adapter.connect()
        assert adapter.build_geometry({"blk_len_mm": 30.0}) is False
        assert "足印" in adapter._last_message

    def test_monitor_failure_is_soft(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, {})
        # 覆盖 monitor 返回 None 的分支
        original = _FakeIcepak.assign_point_monitor_in_object

        def _none(self, name, monitor_type="Temperature", monitor_name=None):
            self.calls.append(("call", "assign_point_monitor_in_object",
                               (name,), {"monitor_name": monitor_name}))
            return None

        monkeypatch.setattr(_FakeIcepak,
                            "assign_point_monitor_in_object", _none)
        try:
            adapter = _make_adapter(tmp_path)
            adapter.connect()
            assert adapter.build_geometry({}) is False
            assert "监控点" in adapter._last_message
        finally:
            monkeypatch.setattr(_FakeIcepak,
                                "assign_point_monitor_in_object", original)
        assert calls  # 桩仍被走到

    def test_extract_temperature_variants(self):
        assert ia._temperature_from_summary({"Mean": 61.3, "Unit": "cel"}) == 61.3
        assert ia._temperature_from_summary({"Mean": "61.3cel"}) == 61.3
        assert ia._temperature_from_summary({"Max": " 60 cel"}) == 60.0
        assert ia._temperature_from_summary({"Unit": "cel"}) is None
        assert ia._temperature_from_summary("garbage") is None

    def test_substrate_midplane_anchor_mode(self, tmp_path, monkeypatch):
        """锚工况：基板中面监控点 + 线性闭式（手算 0.79375K 温升）。"""
        calls: list = []
        # 线性区任何温度都应精确命中闭式：给 温升 +0.1% 偏差
        _install_fake_pyaedt(monkeypatch, calls,
                             {"Mean": 25.0 + 0.79375 * 1.001, "Unit": "cel"})
        adapter = _make_adapter(tmp_path)
        adapter.connect()
        assert adapter.use_design("rfauto_et_anchor") is True
        assert adapter.build_geometry(
            {"power_w": 0.5, "monitor_point": "substrate_midplane"}) is True
        result = adapter.solve()
        adapter.close()

        assert result.success is True
        anchor_out = result.field_data["anchor"]
        assert anchor_out["monitor_point"] == "substrate_midplane"
        assert anchor_out["t_closed_form_c"] == pytest.approx(25.79375)
        assert anchor_out["relative_deviation"] == pytest.approx(0.001, rel=1e-6)
        assert anchor_out["pass_2pct"] is True
        # 监控点位置 = 基板中面（10,10,0.254）mm，显式单位字符串
        pos = next(c for c in calls if c[1] == "assign_point_monitor")
        assert pos[2][0] == ("10.0mm", "10.0mm", "0.254mm")
        assert pos[3]["monitor_name"] == "rfauto_T_sub"
        assert ("call", "insert_design", ("rfauto_et_anchor",), {}) in calls

    def test_invalid_monitor_point_rejected(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, {})
        adapter = _make_adapter(tmp_path)
        adapter.connect()
        assert adapter.build_geometry({"monitor_point": "bogus"}) is False
        assert "monitor_point" in adapter._last_message


# ─── EM 损耗映射薄封装（方案注记 API 名）────────────────────────────────────


class TestMapEmLosses:
    def test_requires_connect(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        out = adapter.map_em_losses({"assignment": "x", "design": "d",
                                     "setup": "s", "sweep": "sw"})
        assert out == {"ok": False, "error": "未连接：先 connect()"}

    def test_forwards_to_assign_em_losses(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, {})
        adapter = _make_adapter(tmp_path)
        adapter.connect()
        payload = {"assignment": ["rfauto_blk"], "design": "uUSB",
                   "setup": "Setup1", "sweep": "LastAdaptive",
                   "map_frequency": "2.5GHz", "loss_multiplier": 2.0}
        forwarded: dict = {}

        class _Boundary:
            name = "EMLoss1"

        def _fake_assign(*args, **kw):
            forwarded["args"] = args
            forwarded.update(kw)
            return _Boundary()

        adapter._ipk.assign_em_losses = _fake_assign
        out = adapter.map_em_losses(payload)
        assert out == {"ok": True, "boundary_name": "EMLoss1"}
        assert forwarded["args"][0] == ["rfauto_blk"]
        assert forwarded["args"][1] == "uUSB"
        assert forwarded["args"][3] == "LastAdaptive"
        assert forwarded["map_frequency"] == "2.5GHz"
        assert forwarded["loss_multiplier"] == 2.0


# ─── WP4.4a ①：附着既有工程（project_path → new_desktop=False）───────────────


class TestConnectAttachProject:
    def test_attach_mode_uses_existing_project(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, {})
        project = str(tmp_path / "e2e" / "wp44a_e2e.aedt")
        adapter = _make_adapter(tmp_path, project_path=project,
                                design_name="rfauto_et_e2e")
        assert adapter.connect() is True
        init = next(c for c in calls if c[1] == "Icepak.__init__")
        assert init[3]["project"] == project
        assert init[3]["new_desktop"] is False
        assert init[3]["design"] == "rfauto_et_e2e"
        assert init[3]["non_graphical"] is True

    def test_default_connect_unchanged(self, tmp_path, monkeypatch):
        """默认路径回归钉：无 project_path → 新建 wp44a_electrothermal.aedt
        + new_desktop=True + design=rfauto_et（现首案例口径不变）。"""
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, {})
        adapter = _make_adapter(tmp_path)
        assert adapter.connect() is True
        init = next(c for c in calls if c[1] == "Icepak.__init__")
        assert init[3]["project"] == str(
            (tmp_path / "wp44a") / "wp44a_electrothermal.aedt")
        assert init[3]["new_desktop"] is True
        assert init[3]["design"] == "rfauto_et"

    def test_empty_project_path_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="project_path"):
            _make_adapter(tmp_path, project_path="   ")


# ─── WP4.4a ②：自然对流工况（空气域/重力/开口/HeatFlowRate 能量平衡）──────────


_CONVECTION_REPORTS = {
    "rfauto_T_blk": {"Mean": 25.9, "Unit": "cel"},       # 温升 0.9 < 1.68125 纯传导
    "Wall": {"Total": "0.3W"},                            # 壁面边界（fake 名 Wall）
    "Opening1": {"Total": -0.20},                         # 开口边界净出热（符号不参与）
}  # 开口 0.20W + 壁面 0.30W = 0.50W = P_in → 平衡偏差 0%


class TestConvectionCase:
    def _convection_adapter(self, tmp_path, monkeypatch, calls, reports):
        _install_fake_pyaedt(monkeypatch, calls, reports)
        return _make_adapter(tmp_path, problem_type="TemperatureAndFlow")

    def test_build_and_solve_full_sequence(self, tmp_path, monkeypatch):
        calls: list = []
        adapter = self._convection_adapter(tmp_path, monkeypatch, calls,
                                           dict(_CONVECTION_REPORTS))
        assert adapter.connect() is True
        assert adapter.build_convection_case({"power_w": 0.5}) is True
        result = adapter.solve()
        setup_obj = adapter._ipk.last_setup  # close 前抓（断言重力开关）
        adapter.close()

        assert result.success is True
        anchor = result.field_data["anchor"]
        assert anchor["mode"] == "convection"
        balance = anchor["energy_balance"]
        assert balance["total_out_w"] == pytest.approx(0.50)
        assert balance["relative_imbalance"] == pytest.approx(0.0, abs=1e-12)
        assert balance["pass"] is True
        assert anchor["physically_healthy"] is True
        assert anchor["pass_2pct"] is True
        assert result.field_data["t_blk_c"] == pytest.approx(25.9)
        heat = result.field_data["heat_flow"]
        assert heat["openings_w"] == pytest.approx(0.20)
        assert heat["wall_w"] == pytest.approx(0.30)
        assert heat["wall_boundary"] == "Wall"
        assert heat["opening_boundary"] == "Opening1"
        # 空气域包围盒诊断（面心 ±10mm 填充；字符串带单位形态被解析）
        extent = result.field_data["region_extent_mm"]
        assert extent["x_min"] == pytest.approx(-10.0)
        assert extent["x_max"] == pytest.approx(30.0)
        assert extent["z_max"] == pytest.approx(10.658)

        # 序列断言：空气域（无自动 Region → create_region）/重力(-Z=2)/开口/
        # 出热按边界 field summary 读（不再建面监控）
        region = next(c for c in calls if c[1] == "modeler.create_region")
        assert region[2] == (("10.0mm",) * 6,)
        assert region[3] == {"pad_type": "Absolute Offset", "name": "Region"}
        settings = next(c for c in calls if c[1] == "edit_design_settings")
        assert settings[2] == (2, 25.0)  # 重力 -Z（DEFAULT_GRAVITY_DIR）+ 环境温度
        openings = next(c for c in calls if c[1] == "assign_openings")
        assert openings[2] == ((201, 202, 203, 204, 205, 206),)
        assert not any(c[1] in ("monitor.assign_face_monitor",
                                "assign_surface_monitor") for c in calls)
        boundary_reads = [c for c in calls
                          if c[1] == "post.evaluate_boundary_quantity"]
        assert {c[3]["boundary"] for c in boundary_reads} == {"Wall", "Opening1"}
        assert all(c[3]["quantity"] == "HeatFlowRate" for c in boundary_reads)
        wall_read = next(c for c in boundary_reads if c[3]["boundary"] == "Wall")
        assert wall_read[3]["side"] == "Adjacent"  # 固侧出热（真机实证 Default=气侧）
        assert heat["wall_side"] == "Adjacent"
        assert ("call", "create_setup", ("rfauto_et_setup",), {}) in calls
        # 重力开关必须在 setup 级显式置 True（2025.1 默认 False=无浮升力）
        assert setup_obj.props["Include Gravity"] is True
        assert setup_obj.props["Convergence Criteria - Max Iterations"] == 100
        assert adapter._ipk is None

    def test_use_design_does_not_inherit_state(self, tmp_path, monkeypatch):
        """回归（2025.1 真机实证）：切设计后新设计不得继承旧设计的
        setup_name——旧状态存档必须挂在旧设计名下（_swap_design_state 的
        previous 取自切换前），否则 solve 跳过 create_setup、analyze 对
        不存在的 setup 静默 no-op（"solved in 0.0s"）→ 监控读空。"""
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, {"Mean": 60.0})
        adapter = _make_adapter(tmp_path)
        adapter.connect()
        assert adapter._ipk.design_name == "rfauto_et"
        adapter.build_geometry({"power_w": 0.5})
        adapter.solve()
        assert adapter._setup_name == "rfauto_et_setup"
        assert adapter.use_design("rfauto_second") is True
        assert adapter._ipk.design_name == "rfauto_second"
        assert adapter._setup_name is None
        assert adapter._built is False
        assert adapter._monitor_name is None
        saved = adapter._design_state["rfauto_et"]
        assert saved["setup_name"] == "rfauto_et_setup"
        assert saved["built"] is True

    def test_auto_region_reconfigured_instead_of_created(self, tmp_path,
                                                         monkeypatch):
        """AEDT Icepak 自动 Region 存在（2025.1 真机实证）→ 改填充不新建。"""
        calls: list = []
        adapter = self._convection_adapter(tmp_path, monkeypatch, calls,
                                           dict(_CONVECTION_REPORTS))
        adapter.connect()
        adapter._ipk.mesh.global_mesh_region.global_region = _FakeGlobalRegion(
            calls, region_obj=types.SimpleNamespace(name="Region"))
        assert adapter.build_convection_case({"power_w": 0.5}) is True
        assert not any(c[1] == "modeler.create_region" for c in calls)
        types_call = next(c for c in calls if c[1] == "global_region.padding_types")
        assert types_call[2] == (("Absolute Offset",) * 6,)
        values_call = next(c for c in calls
                           if c[1] == "global_region.padding_values")
        assert values_call[2] == (("10.0mm",) * 6,)
        # 面在填充改完后再取（顺序：padding → get_object_faces(Region)）
        idx_pad = calls.index(values_call)
        idx_faces = next(i for i, c in enumerate(calls)
                         if c[1] == "modeler.get_object_faces"
                         and c[2] == ("Region",))
        assert idx_faces > idx_pad

    def test_requires_temperature_and_flow_problem_type(self, tmp_path,
                                                        monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, {})
        adapter = _make_adapter(tmp_path)  # 默认 TemperatureOnly
        adapter.connect()
        assert adapter.build_convection_case({}) is False
        assert "TemperatureAndFlow" in adapter._last_message

    def test_same_domain_conduction_comparator_allowed(self, tmp_path,
                                                       monkeypatch):
        """with_openings=False：TemperatureOnly 下同域不开口对照（不开口）。"""
        calls: list = []
        _install_fake_pyaedt(
            monkeypatch, calls,
            {"rfauto_T_blk": {"Mean": 25.4, "Unit": "cel"},
             "Wall": {"Total": "0.5W"}})
        adapter = _make_adapter(tmp_path)  # TemperatureOnly
        adapter.connect()
        assert adapter.build_convection_case(
            {"power_w": 0.5, "with_openings": False}) is True
        assert not any(c[1] == "assign_openings" for c in calls)
        assert adapter._opening_boundary is None
        result = adapter.solve()
        assert result.success is True
        assert result.field_data["heat_flow"]["openings_w"] == 0.0
        assert result.field_data["heat_flow"]["wall_w"] == pytest.approx(0.5)

    def test_with_openings_false_rejected_under_flow(self, tmp_path,
                                                     monkeypatch):
        calls: list = []
        adapter = self._convection_adapter(tmp_path, monkeypatch, calls, {})
        adapter.connect()
        assert adapter.build_convection_case({"with_openings": False}) is False
        assert "TemperatureOnly" in adapter._last_message

    def test_with_openings_must_be_bool(self, tmp_path, monkeypatch):
        calls: list = []
        adapter = self._convection_adapter(tmp_path, monkeypatch, calls, {})
        adapter.connect()
        assert adapter.build_convection_case({"with_openings": "yes"}) is False
        assert "with_openings" in adapter._last_message

    def test_requires_connect(self, tmp_path):
        adapter = _make_adapter(tmp_path, problem_type="TemperatureAndFlow")
        assert adapter.build_convection_case({}) is False
        assert "未连接" in adapter._last_message

    @pytest.mark.parametrize("geometry,fragment", [
        ({"gravity_dir": 7}, "gravity_dir"),
        ({"gravity_dir": 2.5}, "gravity_dir"),
        ({"gravity_dir": True}, "gravity_dir"),
        ({"region_pad_mm": 0.0}, "region_pad_mm"),
        ({"region_pad_mm": "wide"}, "region_pad_mm"),
        ({"monitor_point": "bogus"}, "monitor_point"),
        ({"power_w": -1.0}, "正数"),
        ({"nope": 1.0}, "未知模板参数"),
    ])
    def test_invalid_geometry_rejected(self, tmp_path, monkeypatch, geometry,
                                       fragment):
        calls: list = []
        adapter = self._convection_adapter(tmp_path, monkeypatch, calls, {})
        adapter.connect()
        assert adapter.build_convection_case(geometry) is False
        assert fragment in adapter._last_message

    def test_opening_failure_is_soft(self, tmp_path, monkeypatch):
        calls: list = []
        adapter = self._convection_adapter(tmp_path, monkeypatch, calls, {})
        adapter.connect()
        original = _FakeIcepak.assign_openings

        def _none(self, air_faces):
            self.calls.append(("call", "assign_openings",
                               (tuple(air_faces),), {}))
            return None

        monkeypatch.setattr(_FakeIcepak, "assign_openings", _none)
        try:
            assert adapter.build_convection_case({}) is False
            assert "assign_openings" in adapter._last_message
        finally:
            monkeypatch.setattr(_FakeIcepak, "assign_openings", original)

    def test_energy_imbalance_reported_not_faked(self, tmp_path, monkeypatch):
        """能量平衡超门：solve 仍 success（真跑机器数据），门判如实 False。"""
        calls: list = []
        reports = dict(_CONVECTION_REPORTS)
        reports["Wall"] = {"Total": 0.9}  # 总出 1.1W vs 0.5W → 120% 失衡
        adapter = self._convection_adapter(tmp_path, monkeypatch, calls, reports)
        adapter.connect()
        adapter.build_convection_case({"power_w": 0.5})
        result = adapter.solve()
        assert result.success is True
        balance = result.field_data["anchor"]["energy_balance"]
        assert balance["pass"] is False
        assert balance["relative_imbalance"] == pytest.approx(1.2)

    def test_hotter_than_conduction_flagged_unhealthy(self, tmp_path,
                                                      monkeypatch):
        calls: list = []
        reports = dict(_CONVECTION_REPORTS)
        reports["rfauto_T_blk"] = {"Mean": 30.0}  # 温升 5K > 纯传导 1.68K
        adapter = self._convection_adapter(tmp_path, monkeypatch, calls, reports)
        adapter.connect()
        adapter.build_convection_case({"power_w": 0.5})
        result = adapter.solve()
        anchor = result.field_data["anchor"]
        assert anchor["physically_healthy"] is False
        assert anchor["pass_2pct"] is False

    def test_read_heat_flow_rates_none_before_solve(self, tmp_path, monkeypatch):
        calls: list = []
        adapter = self._convection_adapter(tmp_path, monkeypatch, calls, {})
        assert adapter.read_heat_flow_rates() is None

    def test_total_from_summary_variants(self):
        assert ia._total_from_summary({"Total": 0.3, "Unit": "W"}) == 0.3
        assert ia._total_from_summary({"Total": "0.3W"}) == 0.3
        assert ia._total_from_summary({"Mean": 1.0}) is None
        assert ia._total_from_summary("garbage") is None


# ─── WP4.4a ①：环形谐振器基板工况（场级映射接收几何 + 同功率集总对照）─────────


class TestRingSubstrateCase:
    def _ring_reports(self, t_c=26.5, wall_w=0.042):
        return {"rfauto_T_ring": {"Mean": t_c, "Unit": "cel"},
                "Wall": {"Total": wall_w}}

    def test_field_case_sequence_no_lumped_source(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, self._ring_reports())
        adapter = _make_adapter(tmp_path)
        assert adapter.connect() is True
        assert adapter.build_ring_substrate_case({"power_w": 0.0}) is True
        result = adapter.solve()
        adapter.close()

        assert result.success is True
        assert result.field_data["mode"] == "ring"
        assert result.field_data["t_blk_c"] == pytest.approx(26.5)
        assert result.field_data["heat_flow"]["wall_w"] == pytest.approx(0.042)
        assert result.field_data["anchor"]["pass_2pct"] is None  # 无 1-D 锚
        boxes = [c for c in calls if c[1] == "modeler.create_box"]
        assert len(boxes) == 1
        sub = boxes[0]
        assert sub[2][2] == "rfauto_sub"
        assert sub[2][0] == ("-20.0mm", "-20.0mm", "0mm")  # 中心在原点
        ring = next(c for c in calls if c[1] == "modeler.create_cylinder")
        assert ring[2] == ("Z", ("0mm", "0mm", "0mm"), "12.2mm", "0.508mm",
                           "rfauto_sub_ring", "rfauto_sub_mat")
        subt = next(c for c in calls if c[1] == "modeler.subtract")
        assert subt[2] == ("rfauto_sub", ("rfauto_sub_ring",))
        assert subt[3]["keep_originals"] is True
        assert not any(c[1] == "assign_solid_block" for c in calls)  # 无集总源
        mon = next(c for c in calls if c[1] == "assign_point_monitor")
        assert mon[2][0] == ("11.6mm", "0mm", "0.254mm")  # 环带中面
        assert mon[3]["monitor_name"] == "rfauto_T_ring"

    def test_lumped_comparator_assigns_block_power(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, self._ring_reports())
        adapter = _make_adapter(tmp_path)
        adapter.connect()
        assert adapter.build_ring_substrate_case({"power_w": 0.05}) is True
        block = next(c for c in calls if c[1] == "assign_solid_block")
        assert block[2] == ("rfauto_sub_ring", "0.05W")

    @pytest.mark.parametrize("geometry,fragment", [
        ({"ring_r_in_mm": 12.2, "ring_r_out_mm": 11.0}, "ring_r_in_mm"),
        ({"ring_r_out_mm": 25.0}, "半宽"),
        ({"power_w": -0.1}, "power_w"),
        ({"nope": 1.0}, "未知环形工况参数"),
        ({"board_thk_mm": 0.0}, "正数"),
    ])
    def test_invalid_ring_geometry_rejected(self, tmp_path, monkeypatch, geometry,
                                            fragment):
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, {})
        adapter = _make_adapter(tmp_path)
        adapter.connect()
        assert adapter.build_ring_substrate_case(geometry) is False
        assert fragment in adapter._last_message

    def test_requires_connect(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        assert adapter.build_ring_substrate_case({}) is False
        assert "未连接" in adapter._last_message

    def test_normalize_ring_params_defaults(self):
        spec = ia.normalize_ring_params(None)
        assert spec["ring_r_in_mm"] == 11.0
        assert spec["power_w"] == 0.0
        assert spec["board_k_w_mk"] == 0.4
