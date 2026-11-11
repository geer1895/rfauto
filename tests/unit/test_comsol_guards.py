"""COMSOL adapter 静默失效双守卫单测（T-Q16，2026-11-02 专利3 外借批反馈）。

守卫语义（全 mock，零 COMSOL/license/JVM 依赖；红线=缺省零行为变化）：
- 空网格守卫（§8 坑2）：mesh 序列 getNumElem()=0 → 求解不启动
  （success=False + message 指向网格配置），study 不 run；拿不到单元数
  （unknown=None）→ 放行不误报；
- 热弹性静默零解守卫（§8 坑1）：解全精确零 + 模型含 ThermalExpansion 特征
  → message/field_data 显式警告（success 不变）；解非全零或特征扫描
  无命中/拿不到 → 不告警。
实录出处：docs/comsol_references.md §8（坑1/坑2）；反馈原件
runs/aurora_q/feedback/rfauto使用反馈-20261102.md。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.adapters import comsol_adapter as ca
from rfauto.adapters.comsol_adapter import (
    EMPTY_MESH_GUARD_MSG,
    ZERO_SOLUTION_GUARD_NOTE_FMT,
    ComsolAdapter,
    mesh_element_count,
    normalize_parallel_plate_params,
    parallel_plate_closed_form,
    solution_all_zero,
    thermal_expansion_feature_tags,
)
from rfauto.adapters.em_solver_base import (
    EMSolverConfig,
    EMSolverType,
)

FREQS = [2.2, 2.4, 2.6]

# ─── 手写 Java 树桩（受控返回值；与通用录制桩互斥使用）───────────────────────


class _MeshSeq:
    def __init__(self, n):
        self._n = n

    def getNumElem(self):
        return self._n


class _MeshList:
    def __init__(self, meshes):
        self._m = meshes  # tag -> 单元数

    def tags(self):
        return list(self._m)

    def __call__(self, tag):
        return _MeshSeq(self._m[tag])


class _NoMeshComp:
    """无 mesh 列表的 component（拿不到→unknown 路径）。"""


class _Feat:
    def __init__(self, ftype, subs=None):
        self._t = ftype
        self._subs = subs or {}

    def getType(self):
        return self._t

    def feature(self, *args):
        if not args:
            return _FeatList(self._subs)
        return self._subs[args[0]]


class _FeatList:
    def __init__(self, feats):
        self._f = feats  # tag -> _Feat

    def tags(self):
        return list(self._f)

    def __call__(self, tag):
        return self._f[tag]


class _Phys:
    def __init__(self, feats):
        self._f = feats

    def feature(self, *args):
        if not args:
            return _FeatList(self._f)
        return self._f[args[0]]


class _PhysList:
    def __init__(self, phys):
        self._p = phys  # tag -> _Phys

    def tags(self):
        return list(self._p)

    def __call__(self, tag):
        return self._p[tag]


class _Comp:
    def __init__(self, meshes=None, phys=None):
        self._meshes = meshes
        self._phys = phys

    def mesh(self, *args):
        if self._meshes is None:
            raise RuntimeError("该组件无 mesh 列表（unknown 形态）")
        if not args:
            return _MeshList(self._meshes)
        return _MeshSeq(self._meshes[args[0]])

    def physics(self, *args):
        if self._phys is None:
            raise RuntimeError("该组件无 physics 列表（unknown 形态）")
        if not args:
            return _PhysList(self._phys)
        return self._phys[args[0]]


class _CompList:
    def __init__(self, comps):
        self._c = comps  # tag -> _Comp

    def tags(self):
        return list(self._c)

    def __call__(self, tag):
        return self._c[tag]


class _Java:
    def __init__(self, comps):
        self._c = comps

    def component(self, *args):
        if not args:
            return _CompList(self._c)
        return self._c[args[0]]


class _TreeModel:
    def __init__(self, comps):
        self.java = _Java(comps)


# ─── 通用录制桩（缺省零行为钉用：任意属性→可调用→子桩，getReal/getImag 出数据）


class _JavaRecorder:
    def __init__(self, calls, data, path=""):
        self._calls = calls
        self._data = data
        self._path = path

    def __getattr__(self, name):
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


class _FakeClient:
    def create(self, name):
        self.calls: list = []
        self.model = _FakeModel(self.calls, self.data)
        return self.model

    def __init__(self, data):
        self.data = data


# ─── mesh_element_count：known / zero / unknown 三态 ─────────────────────────


class TestMeshElementCount:
    def test_sums_sequences_across_components(self):
        model = _TreeModel({
            "comp1": _Comp(meshes={"mesh1": 10}),
            "comp2": _Comp(meshes={"mesh1": 5, "mesh2": 1}),
        })
        assert mesh_element_count(model) == 16

    def test_zero_when_all_sequences_empty(self):
        model = _TreeModel({"comp1": _Comp(meshes={"mesh1": 0})})
        assert mesh_element_count(model) == 0  # 只有 Size 节点形态（§8 坑2）

    def test_unknown_when_no_mesh_list(self):
        model = _TreeModel({"comp1": _NoMeshComp()})
        assert mesh_element_count(model) is None

    def test_unknown_when_getnumelem_not_numeric(self):
        # getNumElem 缺失/返回非数值（ recorder 桩形态）→ unknown 不误报
        model = _TreeModel({"comp1": _Comp(meshes={"mesh1": "not-a-number"})})
        assert mesh_element_count(model) is None

    def test_unknown_on_recorder_mock_and_none_model(self):
        calls: list = []
        model = _FakeModel(calls, {"real": [], "imag": []})
        assert mesh_element_count(model) is None  # unknown：守卫缺省放行
        assert mesh_element_count(None) is None


# ─── thermal_expansion_feature_tags：命中 / 无命中 / unknown 三态 ─────────────


class TestThermalExpansionScan:
    def test_finds_subfeature_under_lemm1(self):
        solid = _Phys(feats={"lemm1": _Feat(
            "LinearElasticMaterial",
            subs={"te1": _Feat("ThermalExpansion")})})
        model = _TreeModel({"comp1": _Comp(phys={"solid": solid})})
        assert thermal_expansion_feature_tags(model) == ("solid/lemm1/te1",)

    def test_top_level_feature_hit(self):
        solid = _Phys(feats={"teX": _Feat("ThermalExpansion")})
        model = _TreeModel({"comp1": _Comp(phys={"solid": solid})})
        assert thermal_expansion_feature_tags(model) == ("solid/teX",)

    def test_no_hit_returns_empty_tuple_not_none(self):
        emw = _Phys(feats={"lport1": _Feat("LumpedPort")})
        model = _TreeModel({"comp1": _Comp(phys={"emw": emw})})
        assert thermal_expansion_feature_tags(model) == ()

    def test_unknown_when_scan_surface_missing(self):
        calls: list = []
        model = _FakeModel(calls, {"real": [], "imag": []})
        assert thermal_expansion_feature_tags(model) is None  # unknown 不误报
        assert thermal_expansion_feature_tags(None) is None


# ─── solution_all_zero：精确零判别（坑1 可检测面）─────────────────────────────


class TestSolutionAllZero:
    def test_exact_zero_complex_matrix(self):
        assert solution_all_zero(np.zeros((3, 2, 2), dtype=complex)) is True

    def test_tiny_and_nan_and_empty_are_not_zero(self):
        tiny = np.zeros((1, 2, 2), dtype=complex)
        tiny[0, 0, 0] = 1e-300  # 物理小量 ≠ 精确零（与全零列判别同口径）
        assert solution_all_zero(tiny) is False
        nan = np.zeros((1, 2, 2), dtype=complex)
        nan[0, 1, 0] = np.nan + 1j * np.nan  # 未定义列（NaN）不构成全零证据
        assert solution_all_zero(nan) is False
        assert solution_all_zero(np.zeros((0, 2, 2), dtype=complex)) is False


# ─── solve() 集成：守卫注入复现 + 缺省零行为变化钉 ───────────────────────────


def _make_adapter(tmp_path, client, **extra):
    cfg = EMSolverConfig(
        solver_type=EMSolverType.COMSOL,
        working_dir=str(tmp_path / "work"),
        freq_range_ghz=(2.2, 2.6),
        mesh_resolution_mm=1.0,
        extra_params={"comsol_root": str(tmp_path), **extra},
    )
    return ComsolAdapter(cfg, client_factory=lambda: client)


def _built_adapter(tmp_path, client):
    adapter = _make_adapter(tmp_path, client)
    adapter.connect()
    assert adapter.build_geometry({"template": "parallel_plate",
                                   "params": {"freq_ghz": FREQS}})
    return adapter


def _eval_data(spec):
    """闭式 EvalGlobal 数据（行=freq/S11/S21，3 行官方口径）。"""
    f = np.asarray(FREQS, dtype=float)
    s = parallel_plate_closed_form(spec, f)
    return {"real": [list(f * 1e9), list(s[:, 0, 0].real), list(s[:, 1, 0].real)],
            "imag": [[0.0] * len(f), list(s[:, 0, 0].imag), list(s[:, 1, 0].imag)]}


def _zero_s_data():
    """全零 S 解数据（freq 行真实、S 行全精确零=坑1 静默零解形态）。"""
    f = np.asarray(FREQS, dtype=float)
    n = len(f)
    return {"real": [list(f * 1e9), [0.0] * n, [0.0] * n],
            "imag": [[0.0] * n, [0.0] * n, [0.0] * n]}


def _calls_named(calls, suffix):
    return [(n, a) for n, a in calls if n.endswith(suffix)]


class TestSolveGuards:
    def test_empty_mesh_guard_blocks_before_study_run(self, tmp_path, monkeypatch):
        client = _FakeClient(_eval_data(normalize_parallel_plate_params(None)))
        adapter = _built_adapter(tmp_path, client)
        monkeypatch.setattr(ca, "mesh_element_count", lambda model: 0)
        result = adapter.solve()
        assert not result.success
        assert "网格配置" in result.message and "getNumElem" in result.message
        assert result.message == EMPTY_MESH_GUARD_MSG
        assert not _calls_named(client.calls, "study.run")  # 求解不启动
        assert not ca._SOLVE_LOCK.locked()  # 锁随 return 释放

    def test_zero_solution_guard_warns_on_thermal_feature(self, tmp_path,
                                                          monkeypatch):
        client = _FakeClient(_zero_s_data())
        adapter = _built_adapter(tmp_path, client)
        monkeypatch.setattr(ca, "mesh_element_count", lambda model: 154)
        monkeypatch.setattr(ca, "thermal_expansion_feature_tags",
                            lambda model: ("solid/lemm1/te1",))
        result = adapter.solve()
        assert result.success  # 告警不拦截：求解本身已完成
        assert "热弹性静默零解守卫" in result.message
        assert "检查 ThermalExpansion Tref 显式设置" in result.message
        assert result.field_data["guard_warnings"] == [
            ZERO_SOLUTION_GUARD_NOTE_FMT.format(tags="solid/lemm1/te1")]

    def test_zero_solution_without_thermal_feature_stays_silent(self, tmp_path,
                                                                monkeypatch):
        # 解全零但无 ThermalExpansion 特征（=既有 RF 通道形态）→ 不告警
        client = _FakeClient(_zero_s_data())
        adapter = _built_adapter(tmp_path, client)
        monkeypatch.setattr(ca, "mesh_element_count", lambda model: 154)
        monkeypatch.setattr(ca, "thermal_expansion_feature_tags", lambda model: ())
        result = adapter.solve()
        assert result.success
        assert "守卫" not in result.message
        assert "guard_warnings" not in result.field_data

    def test_default_path_zero_behavior_change(self, tmp_path):
        """缺省零行为钉：真守卫函数跑在录制桩上（unknown 路径）→ 结果与
        既有 RF 通道逐键一致（无 guard 键、message 无守卫字样）。"""
        client = _FakeClient(_eval_data(normalize_parallel_plate_params(None)))
        adapter = _built_adapter(tmp_path, client)
        result = adapter.solve()
        assert result.success, result.message
        # 缺省 unknown 语义实测：录制桩无 Java 链实值 → 两守卫检测面均 None
        assert mesh_element_count(client.model) is None
        assert thermal_expansion_feature_tags(client.model) is None
        assert "守卫" not in result.message
        assert "guard_warnings" not in result.field_data
        assert set(result.field_data) == {
            "sparam_fill", "physics", "mesh_hmax_mm", "touchstone",
            "template", "port_chain", "loss_tangent"}
        assert result.message.startswith("COMSOL 6.3 频域求解完成")

    @pytest.mark.parametrize("count", [None, 1])
    def test_mesh_guard_only_fires_on_exact_zero(self, tmp_path, monkeypatch,
                                                 count):
        """unknown（None）与非零单元数都放行——只有精确 0 拦截。"""
        client = _FakeClient(_eval_data(normalize_parallel_plate_params(None)))
        adapter = _built_adapter(tmp_path, client)
        monkeypatch.setattr(ca, "mesh_element_count", lambda model: count)
        result = adapter.solve()
        assert result.success, result.message
        assert _calls_named(client.calls, "study.run")
