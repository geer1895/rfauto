"""WP4.4c COMSOL 适配器单测（mock MPh client：零 COMSOL/license/JVM 依赖）。

覆盖：注册表/枚举、EMSolverAdapter 结构契约、capabilities 如实声明、参数映射
（rfauto mm/Ω → COMSOL 参数/plist）、闭式与判据纯函数、build/solve 生命周期
（Java 调用序列对照官方口径：接口类型串/集总端口属性/PMC 侧壁/Frequency study）、
license 串行锁、版本钉扎 6.3。
"""

from __future__ import annotations

import json
import sys
import types
from typing import ClassVar

import numpy as np
import pytest

from rfauto.adapters import comsol_adapter as ca
from rfauto.adapters.comsol_adapter import (
    COMSOL_VERSION_PIN,
    ComsolAdapter,
    extract_eps_eff,
    format_plist,
    normalize_parallel_plate_params,
    parallel_plate_closed_form,
    parallel_plate_z0,
    resolve_freq_points,
    tl_section_sparams,
    to_comsol_parameters,
    transmission_health,
)
from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverType,
    get_global_registry,
)

# ─── Java 链式调用录制桩 ─────────────────────────────────────────────────────


class _JavaRecorder:
    """任意属性 → 可调用 → 返回子桩；所有调用以 (路径, 参数) 记入共享列表。

    getReal/getImag 返回预置的 EvalGlobal 数据（行=表达式、列=解号，官方口径）。
    """

    def __init__(self, calls: list, data: dict, path: str = ""):
        self._calls = calls
        self._data = data
        self._path = path

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def _call(*args):
            full = f"{self._path}.{name}" if self._path else name
            self._calls.append((full, args))
            if name == "getReal":
                return self._data["real"]
            if name == "getImag":
                return self._data["imag"]
            return _JavaRecorder(self._calls, self._data, full)

        return _call


class _FakeModel:
    def __init__(self, calls, data):
        self.java = _JavaRecorder(calls, data)
        self.saved: list[str] = []

    def save(self, path):
        self.saved.append(str(path))


class _FakeClient:
    """MPh Client 桩：create() 时断言求解锁已被持有（license 串行纪律）。"""

    def __init__(self, data):
        self.calls: list = []
        self.data = data
        self.removed: list = []
        self.lock_held_at_create: bool | None = None

    def create(self, name):
        self.lock_held_at_create = ca._SOLVE_LOCK.locked()
        return _FakeModel(self.calls, self.data)

    def remove(self, model):
        self.removed.append(model)


def _eval_data(freqs_ghz, spec):
    """按闭式生成 EvalGlobal 返回数据（3 行：freq/S11/S21）。"""
    f = np.asarray(freqs_ghz, dtype=float)
    s = parallel_plate_closed_form(spec, f)
    rows_re = [list(f * 1e9), list(s[:, 0, 0].real), list(s[:, 1, 0].real)]
    rows_im = [[0.0] * len(f), list(s[:, 0, 0].imag), list(s[:, 1, 0].imag)]
    return {"real": rows_re, "imag": rows_im}


def _calls_named(calls, suffix):
    return [(n, a) for n, a in calls if n.endswith(suffix)]


def _make_adapter(tmp_path, client=None, available=True, monkeypatch=None, **extra):
    if monkeypatch is not None:
        monkeypatch.setattr(ca, "mph_installed", lambda: available)
    cfg = EMSolverConfig(
        solver_type=EMSolverType.COMSOL,
        working_dir=str(tmp_path / "work"),
        freq_range_ghz=(2.2, 2.6),
        mesh_resolution_mm=1.0,
        extra_params={"comsol_root": str(tmp_path), **extra},
    )
    factory = (lambda: client) if client is not None else None
    return ComsolAdapter(cfg, client_factory=factory)


# ─── 注册 / 结构 / capabilities ──────────────────────────────────────────────


class TestRegistryAndStructure:
    def test_enum_member_and_raw_string_resolution(self):
        assert EMSolverType.COMSOL.value == "comsol"
        # solvers.yaml 里 solver_type: comsol 经 load_solvers_config 走 EMSolverType(raw)
        assert EMSolverType("comsol") is EMSolverType.COMSOL

    def test_registered_on_package_import(self):
        import rfauto.adapters  # noqa: F401 - 注册副作用

        registry = get_global_registry()
        assert registry.is_registered(EMSolverType.COMSOL)
        inst = registry.create(EMSolverType.COMSOL,
                               EMSolverConfig(solver_type=EMSolverType.COMSOL))
        assert isinstance(inst, ComsolAdapter)

    def test_listed_by_service_registry_view(self):
        import rfauto.adapters  # noqa: F401
        from rfauto.service.r3_services import list_registered_solvers

        names = [s["type"] for s in list_registered_solvers()["solvers"]]
        assert "comsol" in names

    def test_is_em_solver_adapter_with_full_contract(self):
        assert issubclass(ComsolAdapter, EMSolverAdapter)
        assert ComsolAdapter.__abstractmethods__ == frozenset()
        for name in ("connect", "is_available", "build_geometry", "solve",
                     "get_sparams", "close"):
            assert callable(getattr(ComsolAdapter, name))

    def test_param_semantics_declared_for_every_template_param(self):
        assert set(ComsolAdapter.param_semantics) == set(ca.SUPPORTED_TEMPLATES)
        assert (set(ComsolAdapter.param_semantics["parallel_plate"])
                == set(ca.PARALLEL_PLATE_DEFAULTS))
        assert set(ComsolAdapter.param_semantics["mline"]) == set(ca.MLINE_DEFAULTS)

    def test_capabilities_declared_honestly(self, tmp_path, monkeypatch):
        adapter = _make_adapter(tmp_path, monkeypatch=monkeypatch)
        assert adapter.supported_output_formats() == ["csv", "touchstone"]
        kinds = [v["kind"] for v in adapter.visualizations()]
        assert kinds == ["sparams"]  # 未 save_mph 时不虚报 model3d
        status = adapter.get_status()
        assert status["solver_type"] == "comsol"
        assert status["comsol_version_pin"] == "6.3"
        assert status["templates"] == ["parallel_plate", "mline"]
        assert "serial" in status["license_policy"]


# ─── 可用性 / 连接 ───────────────────────────────────────────────────────────


class TestAvailability:
    def test_available_requires_mph_and_root(self, tmp_path, monkeypatch):
        assert _make_adapter(tmp_path, available=True, monkeypatch=monkeypatch).is_available()
        assert not _make_adapter(tmp_path, available=False, monkeypatch=monkeypatch).is_available()
        monkeypatch.setattr(ca, "mph_installed", lambda: True)
        cfg = EMSolverConfig(solver_type=EMSolverType.COMSOL,
                             extra_params={"comsol_root": str(tmp_path / "nope")})
        assert not ComsolAdapter(cfg).is_available()

    def test_connect_does_not_start_client(self, tmp_path, monkeypatch):
        started = []
        adapter = _make_adapter(tmp_path, client=None, monkeypatch=monkeypatch)
        adapter._client_factory = lambda: started.append(1)
        assert adapter.connect()
        assert started == []  # server/license 推迟到 solve
        assert not _make_adapter(tmp_path, available=False, monkeypatch=monkeypatch).connect()

    def test_shared_client_pins_version_and_is_singleton(self, monkeypatch):
        calls = []
        fake_mph = types.ModuleType("mph")

        def _start(version=None, cores=None):
            calls.append((version, cores))
            return object()

        fake_mph.start = _start
        monkeypatch.setitem(sys.modules, "mph", fake_mph)
        monkeypatch.setattr(ca, "_CLIENT", None)
        c1 = ca.get_shared_client()
        c2 = ca.get_shared_client(version="6.4")  # 第二次请求不能换 JVM
        assert c1 is c2
        assert calls == [(COMSOL_VERSION_PIN, 2)]
        assert COMSOL_VERSION_PIN == "6.3"


# ─── 参数映射 / 闭式 / 判据（确定性内核）─────────────────────────────────────


class TestParameterMapping:
    def test_normalize_defaults_override_and_validation(self):
        spec = normalize_parallel_plate_params(None)
        assert spec == ca.PARALLEL_PLATE_DEFAULTS
        spec = normalize_parallel_plate_params({"length_mm": "30", "freq_ghz": [1, 2]})
        assert spec["length_mm"] == 30.0 and spec["eps_r"] == 2.1
        with pytest.raises(ValueError):
            normalize_parallel_plate_params({"width_mm": -1})

    def test_to_comsol_parameters_units(self):
        params = to_comsol_parameters(normalize_parallel_plate_params(
            {"length_mm": 20, "width_mm": 6, "height_mm": 1.154, "eps_r": 2.1,
             "z_ref_ohm": 50}))
        assert params == {"L": "20[mm]", "W": "6[mm]", "H": "1.154[mm]",
                          "eps_r": "2.1", "Zref": "50[ohm]"}

    def test_format_plist_explicit_units(self):
        assert format_plist([2.2, 2.4, 2.6]) == "2.2[GHz] 2.4[GHz] 2.6[GHz]"

    def test_resolve_freq_points(self):
        cfg = EMSolverConfig(solver_type=EMSolverType.COMSOL, freq_range_ghz=(1.0, 3.0),
                             extra_params={"n_freq": 3})
        assert resolve_freq_points(cfg, None) == [1.0, 2.0, 3.0]
        assert resolve_freq_points(cfg, {"freq_ghz": [2.4]}) == [2.4]
        with pytest.raises(ValueError):
            resolve_freq_points(cfg, {"freq_ghz": []})

    def test_default_geometry_is_50_ohm(self):
        d = ca.PARALLEL_PLATE_DEFAULTS
        assert abs(parallel_plate_z0(d["width_mm"], d["height_mm"], d["eps_r"]) - 50.0) < 0.01

    def test_closed_form_matched_line_and_eps_extraction(self):
        f = np.array([2.2, 2.3, 2.4, 2.5, 2.6])
        s = tl_section_sparams(f, eps_eff=2.1, z_line=50.0, length_mm=20.0, z_ref=50.0)
        assert np.all(np.abs(s[:, 0, 0]) < 1e-12)
        assert np.allclose(np.abs(s[:, 1, 0]), 1.0)
        # 2.4GHz：βL = 2π f √εr L / c = 1.4578 rad
        assert abs(np.angle(s[2, 1, 0]) + 1.4578) < 1e-3
        assert abs(extract_eps_eff(f, s[:, 1, 0], 20.0) - 2.1) < 1e-9

    def test_closed_form_mismatch_has_standing_wave(self):
        spec = normalize_parallel_plate_params({"z_ref_ohm": 75.0})
        s = parallel_plate_closed_form(spec, np.array([2.2, 2.6]))
        assert 0.3 < abs(s[0, 0, 0]) < 0.4  # |Γ|=0.2 的双端失配驻波 ≈ -8.5dB
        assert np.allclose(np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2, 1.0)

    def test_transmission_health_flags_nonphysical(self):
        f = np.array([2.2, 2.4])
        good = tl_section_sparams(f, 2.1, 50.0, 20.0)
        assert transmission_health(f, good)["ok"]
        bad = good.copy()
        bad[0, 0, 0] = 1.5  # |S|>1 非物理
        h = transmission_health(f, bad)
        assert not h["ok"] and not h["checks"]["passivity"]


# ─── 生命周期：build / solve / close（mock client）──────────────────────────


class TestLifecycleWithMockClient:
    FREQS: ClassVar[list[float]] = [2.2, 2.4, 2.6]

    def test_build_geometry_guards(self, tmp_path, monkeypatch):
        adapter = _make_adapter(tmp_path, monkeypatch=monkeypatch)
        assert not adapter.build_geometry({"template": "parallel_plate"})  # 未 connect
        adapter.connect()
        assert not adapter.build_geometry({"template": "microstrip"})  # 未支持模板
        assert not adapter.build_geometry({"template": "parallel_plate",
                                           "params": {"eps_r": -2}})  # 非法参数
        assert not adapter.solve().success  # 未 build

    def test_build_geometry_writes_spec_with_mapping(self, tmp_path, monkeypatch):
        adapter = _make_adapter(tmp_path, monkeypatch=monkeypatch)
        adapter.connect()
        assert adapter.build_geometry({"template": "parallel_plate",
                                       "params": {"length_mm": 25, "freq_ghz": self.FREQS}})
        spec = json.loads((tmp_path / "work" / "comsol_spec.json").read_text(encoding="utf-8"))
        assert spec["comsol_parameters"]["L"] == "25[mm]"
        assert spec["freq_ghz"] == self.FREQS
        assert spec["comsol_version_pin"] == "6.3"
        assert abs(spec["closed_form_z0_ohm"] - 50.0) < 0.01

    def _solved(self, tmp_path, monkeypatch, **extra):
        spec = normalize_parallel_plate_params(None)
        client = _FakeClient(_eval_data(self.FREQS, spec))
        adapter = _make_adapter(tmp_path, client=client, monkeypatch=monkeypatch, **extra)
        adapter.connect()
        assert adapter.build_geometry({"template": "parallel_plate",
                                       "params": {"freq_ghz": self.FREQS}})
        result = adapter.solve()
        return adapter, client, result

    def test_solve_success_shape_csv_and_fill_note(self, tmp_path, monkeypatch):
        adapter, _client, result = self._solved(tmp_path, monkeypatch)
        assert result.success, result.message
        assert result.s_params.shape == (3, 2, 2)
        assert np.allclose(result.freq_ghz, self.FREQS)
        assert np.allclose(np.abs(result.s_params[:, 1, 0]), 1.0, atol=1e-6)
        # 互易/对称补齐口径显式标注
        assert np.allclose(result.s_params[:, 0, 1], result.s_params[:, 1, 0])
        assert "Port Sweep" in result.field_data["sparam_fill"]
        assert result.field_data["physics"] == "ElectromagneticWaves(emw)"
        csv_text = (tmp_path / "work" / "sparams.csv").read_text(encoding="utf-8")
        assert csv_text.startswith("freq_hz,re_S11,im_S11,re_S21,im_S21")
        assert len(csv_text.strip().splitlines()) == 4
        _freq, s = adapter.get_sparams()
        assert s is result.s_params

    def test_solve_java_sequence_matches_official_api(self, tmp_path, monkeypatch):
        _, client, result = self._solved(tmp_path, monkeypatch)
        assert result.success
        calls = client.calls
        # RF Module 频域接口类型串 + 官方默认 tag emw（不是无 LumpedPort 的 ewfd 变体）
        assert _calls_named(calls, "physics.create")[0][1] == ("emw", "ElectromagneticWaves", "geom1")
        sets = [a for _, a in _calls_named(calls, ".set")]
        assert ("PortExcitation", "on") in sets and ("PortExcitation", "off") in sets
        assert sets.count(("PortType", "Uniform")) == 2
        assert sets.count(("TerminalType", "Cable")) == 2
        assert ("PortName", "1") in sets and ("PortName", "2") in sets  # 字符串：JPype 重载守卫
        assert ("Zref", "Zref") in sets
        assert ("entitydim", "2") in sets
        assert ("relpermittivity", ["eps_r"]) in sets
        assert ("plist", "2.2[GHz] 2.4[GHz] 2.6[GHz]") in sets
        assert ("hmax", 1.0) in sets and ("custom", "on") in sets
        feature_types = [a[1] for n, a in calls if n.endswith("physics.create.create")]
        assert feature_types.count("PerfectElectricConductor") == 2
        assert feature_types.count("PerfectMagneticConductor") == 2  # 侧壁 PMC（TEM 对称切割）
        assert feature_types.count("LumpedPort") == 2
        study_creates = [a for _, a in _calls_named(calls, "study.create")]
        assert study_creates[0] == ("std1",)
        assert ("freq", "Frequency") in study_creates  # 非 "FrequencyDomain"（真机实证）
        assert _calls_named(calls, "study.run")  # 按 tag 走 Java run，非 MPh 按名解析
        assert ("expr", ["freq", "comp1.emw.S11", "comp1.emw.S21"]) in sets
        # 参数表达式（带单位）
        param_sets = [a for n, a in calls if n == "param.set"]
        assert ("L", "20[mm]") in param_sets and ("Zref", "50[ohm]") in param_sets

    def test_solve_holds_serial_license_lock(self, tmp_path, monkeypatch):
        _, client, result = self._solved(tmp_path, monkeypatch)
        assert result.success
        assert client.lock_held_at_create is True
        assert not ca._SOLVE_LOCK.locked()  # 求解后释放

    def test_save_mph_and_visualizations_and_close(self, tmp_path, monkeypatch):
        adapter, client, result = self._solved(tmp_path, monkeypatch, save_mph=True)
        assert result.success
        assert adapter._model.saved and adapter._model.saved[0].endswith("comsol_model.mph")
        kinds = [v["kind"] for v in adapter.visualizations()]
        assert kinds == ["sparams", "model3d"]
        adapter.close()
        assert len(client.removed) == 1
        assert not adapter._connected

    def test_solve_failure_is_reported_not_raised(self, tmp_path, monkeypatch):
        def _boom():
            raise RuntimeError("license checkout failed")

        adapter = _make_adapter(tmp_path, monkeypatch=monkeypatch)
        adapter._client_factory = _boom
        adapter.connect()
        assert adapter.build_geometry({"template": "parallel_plate"})
        result = adapter.solve()
        assert not result.success
        assert "license checkout failed" in result.message
        assert not ca._SOLVE_LOCK.locked()
        with pytest.raises(RuntimeError):
            adapter.get_sparams()
