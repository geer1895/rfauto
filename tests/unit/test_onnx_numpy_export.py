"""D5 numpy 系 ONNX 导出面单测（aurora_p，onnx.helper 自研转换层）。

判据（任务书预声明验收 A-E，门值冻结于 runs/aurora_p/d5/COVERAGE.md）：
- A 覆盖表全键落盘+表驱动钉：coverage_table() 与冻结键集逐键一致、
  四类两两不交、实测注册表键全部已分类（未分类键=分派面显式报错）；
- B ≥2 个 numpy 键端到端导出+对拍 PASS：本文件实测 6 键（poly_ridge/
  huber_ridge/pod_rom/nn/rff_gp/green_op），裁判=测试面独立复算
  （不经内核 self-verify，#118 家法），容差预声明 PARITY_RTOL/PARITY_ATOL
  （float64 原生 vs float32 图——冒烟实测 max_abs_diff ≤1.13e-6，两量级
  余量）；onnxruntime 缺席=对拍 skip-not-fail（checker 恒跑）；
- C torch 路径零变化：既有钉文件 test_tn20_onnx_export.py 零改动全绿
  （本文件不重复其断言，只钉分派委托一致性）；
- D 不可转换键显式报错+指引（pending/unsupported/torch_uncovered/
  未分类四路）；
- E 确定性：同 seed 两 fit 两导出 sha256 逐字节一致（返回值与盘上文件
  对账）。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.optimization.surrogate import (
    FNOSurrogate,
    GreenOperatorSurrogate,
    HuberRidgeSurrogate,
    NNSurrogate,
    PODROMSurrogate,
    PolyRidgeSurrogate,
    RffGPSurrogate,
    surrogate_registry,
)
from rfauto.optimization.surrogate.onnx_export import (
    PARITY_ATOL,
    PARITY_RTOL,
    SUPPORTED_KINDS,
    export_onnx,
)
from rfauto.optimization.surrogate.onnx_numpy_export import (
    NUMPY_EXPORTABLE_KINDS,
    NUMPY_PENDING_KINDS,
    NUMPY_UNSUPPORTED_KINDS,
    TORCH_UNCOVERED_KINDS,
    coverage_table,
    export_onnx_auto,
    export_onnx_numpy,
)
from rfauto.service.surrogate_export_service import surrogate_export_onnx

# ── 依赖面（分层 skip：onnx=builder 面；onnxruntime=对拍面；torch=分派委托） ──

onnx = pytest.importorskip("onnx", reason="onnx 为可选依赖（extra: onnx）")


def _need_ort():
    pytest.importorskip(
        "onnxruntime",
        reason="onnxruntime 为可选依赖（仅导出-回代对拍消费）")


# ── 合成语料（tiny 单测档；与冒烟探针 runs/aurora_p/d5/smoke_builders.py
#    同族独立重写——裁判分离：测试面自备探针，不消费内核 _probes） ─────────

BOUNDS2 = {"a": (0.0, 2.0), "b": (-1.0, 1.0)}


def _probes(bounds: dict, keys: list[str]) -> list[dict]:
    """探针=中点/角点/两对称内点（独立复算面，与内核 _probes 同口径）。"""
    return [{k: float(bounds[k][0] + f * (bounds[k][1] - bounds[k][0]))
             for k in keys}
            for f in (0.5, 0.0, 1.0, 0.25, 0.75)]


def _linear_samples(n: int = 12, seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    return [{"params": {"a": float(a), "b": float(b)},
             "metrics": {"cost": float(2.0 + 1.5 * a - 0.8 * b
                                    + 0.4 * a * a - 0.3 * a * b),
                         "gain": float(-1.0 + 0.5 * b)}}
            for a, b in rng.uniform([0.0, -1.0], [2.0, 1.0], (n, 2))]


T_N = 8
_F_AXIS = np.linspace(0.0, 1.0, T_N)


def _pod_samples(n: int = 12, seed: int = 1) -> list[dict]:
    rng = np.random.default_rng(seed)
    out = []
    for a, b in rng.uniform([0.0, -1.0], [2.0, 1.0], (n, 2)):
        curve = (np.sin(2 * np.pi * 1.1 * _F_AXIS + a) + 0.3 * b).tolist()
        out.append({"params": {"a": float(a), "b": float(b)},
                    "metrics": {"cost": float(1.0 + 0.2 * a - b),
                                "s11_curve_db": curve}})
    return out


def _nn_samples(n: int = 10, seed: int = 2) -> list[dict]:
    rng = np.random.default_rng(seed)
    return [{"params": {"a": float(a), "b": float(b)},
             "metrics": {"cost": float(1.0 + a * b + 0.2 * a)}}
            for a, b in rng.uniform([0.0, -1.0], [2.0, 1.0], (n, 2))]


def _go_samples(n: int = 10, seed: int = 3) -> list[dict]:
    rng = np.random.default_rng(seed)
    pairs = [(0, 0), (0, 1), (1, 1)]
    out = []
    for a, b in rng.uniform([0.0, -1.0], [2.0, 1.0], (n, 2)):
        s = np.zeros((T_N, 2, 2), dtype=complex)
        for k, (i, j) in enumerate(pairs):
            s[:, i, j] = 0.3 + 0.1 * a * (k + 1) + 0.05j * b
            if i != j:
                s[:, j, i] = s[:, i, j]
        out.append({"params": {"a": float(a), "b": float(b)},
                    "metrics": {"s_matrix": s.tolist()}})
    return out


def _assert_parity(model, path, metric_names, keys, fields=None) -> float:
    """测试面独立复算对拍（不经内核 verify）；返回实测 max_abs_diff。"""
    import onnxruntime as ort

    sess = ort.InferenceSession(str(path),
                                providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    worst = 0.0
    bounds = BOUNDS2
    for probe in _probes(bounds, keys):
        native_map = model.predict(probe)
        native = np.asarray([float(native_map[k]) for k in metric_names],
                            dtype=np.float64)
        vec = np.asarray([float(probe[k]) for k in keys], dtype=np.float32)
        outs = sess.run(None, {input_name: vec})
        got = np.asarray(outs[0], dtype=np.float64)
        assert got.shape == native.shape
        assert np.allclose(native, got, rtol=PARITY_RTOL, atol=PARITY_ATOL), (
            f"probe={probe} max|Δ|={np.max(np.abs(native - got))}")
        worst = max(worst, float(np.max(np.abs(native - got))))
        for fi, fkey in enumerate(fields or [], start=1):
            f_native = np.asarray(
                model.predict_field(fkey, probe)["values"], dtype=np.float64)
            f_got = np.asarray(outs[fi], dtype=np.float64)
            assert np.allclose(f_native, f_got,
                               rtol=PARITY_RTOL, atol=PARITY_ATOL)
            worst = max(worst, float(np.max(np.abs(f_native - f_got))))
    return worst


# ── A：覆盖表表驱动钉（零依赖） ──────────────────────────────────────────────


class TestCoverageTable:
    #: 冻结键集（2026-11-02 实测）：24 注册键 + gnn_geom（导入即注册键，
    #: 包 __init__ 未导入故缺省注册面 24——分类先行不靠导入时序）+
    #: lnn_cfc（同波 LNN 席已落注册表的在飞键，归 pending 类，逐键原因
    #: 见 NUMPY_PENDING_KINDS——转换评估权归交付席）
    FROZEN_KEYS = frozenset({
        "conformal", "deep_ensemble", "deeponet", "ensemble", "fno",
        "fno_lite", "gbdt", "gnn_geom", "green_op", "huber_ridge",
        "lnn_cfc", "mapes_pixel_analytic", "mt_gp", "ngo_stamp_rf", "nn",
        "pod_rom", "pole_residue", "poly_ridge", "rff_gp", "saas_gp",
        "siren", "smt_kriging", "smt_mfk", "svgp", "vf_parametric",
        "warped_kriging",
    })

    def test_table_covers_frozen_key_set_exactly(self):
        """覆盖表=冻结键集（逐键恰一分类；表驱动钉——表与代码一致）。"""
        table = coverage_table()
        assert set(table) == self.FROZEN_KEYS
        for kind, cls in table.items():
            assert cls in ("torch", "numpy", "pending", "unsupported",
                           "torch_uncovered"), (kind, cls)

    def test_classes_pairwise_disjoint(self):
        """四类常量两两不交（同键双分类=覆盖表自相矛盾）。"""
        groups = [set(SUPPORTED_KINDS), set(NUMPY_EXPORTABLE_KINDS),
                  set(NUMPY_PENDING_KINDS), set(NUMPY_UNSUPPORTED_KINDS),
                  set(TORCH_UNCOVERED_KINDS)]
        for i, a in enumerate(groups):
            for b in groups[i + 1:]:
                assert not a & b, sorted(a & b)

    def test_numpy_surface_frozen(self):
        """numpy 可转换面=6 键冻结（覆盖面诚实=不虚报）。"""
        assert NUMPY_EXPORTABLE_KINDS == (
            "green_op", "huber_ridge", "nn", "pod_rom", "poly_ridge",
            "rff_gp")

    def test_exportable_surface_keys_registered(self):
        """可导出面键全部真实注册（覆盖面不虚报；反向"注册表⊆表"断言
        在全量并行下会被测试 fixture 注册键污染（tn14_hetero_plateau
        实证）——"新键须分类"的棘轮由分派面显式报错钉承担）。"""
        table = coverage_table()
        available = set(surrogate_registry.available())
        for kind in ("fno", "deep_ensemble", "siren"):
            assert kind in available
        for kind in NUMPY_EXPORTABLE_KINDS:
            assert kind in available, kind
        assert set(table) == self.FROZEN_KEYS  # 表无垃圾键

    def test_unclassified_kind_explicit_error(self):
        """未分类键显式报错列覆盖面（表驱动诚实边界，不静默）。"""
        fake = SimpleNamespace(KIND="future_key_from_other_seat", fitted=True)
        with pytest.raises(ValueError, match="覆盖表"):
            export_onnx_auto(fake, "x.onnx")


# ── B：端到端导出+对拍（6 键；onnxruntime 缺席=skip-not-fail） ───────────────


class TestNumpyParity:
    def test_poly_ridge_parity(self, tmp_path):
        _need_ort()
        m = PolyRidgeSurrogate(config={"bounds": dict(BOUNDS2)})
        m.fit(_linear_samples())
        res = export_onnx_numpy(m, tmp_path / "poly.onnx")
        assert res["ok"] is True and res["verified"] is True
        assert res["exporter"] == "numpy-builder"
        assert res["metric_names"] == list(m.models.keys())
        worst = _assert_parity(m, tmp_path / "poly.onnx",
                               res["metric_names"], list(BOUNDS2))
        assert worst <= 2e-5  # 冒烟实测 ~3e-7，余量两个量级

    def test_huber_ridge_parity(self, tmp_path):
        _need_ort()
        m = HuberRidgeSurrogate(config={"bounds": dict(BOUNDS2)})
        m.fit(_linear_samples())
        res = export_onnx_numpy(m, tmp_path / "huber.onnx")
        assert res["verified"] is True
        _assert_parity(m, tmp_path / "huber.onnx", res["metric_names"],
                       list(BOUNDS2))

    def test_pod_rom_scalar_and_field_parity(self, tmp_path):
        """pod_rom：标量 metrics + 场键 field:<key> 双输出全对拍。"""
        _need_ort()
        m = PODROMSurrogate(config={"bounds": dict(BOUNDS2)})
        info = m.fit(_pod_samples())
        assert info["field_keys"] == ["s11_curve_db"]
        out = tmp_path / "pod.onnx"
        res = export_onnx_numpy(m, out)
        assert res["verified"] is True
        assert res["output"]["name"] == "metrics"
        assert [o["name"] for o in res["extra_outputs"]] == \
            ["field:s11_curve_db"]
        _assert_parity(m, out, res["metric_names"], list(BOUNDS2),
                       fields=["s11_curve_db"])

    def test_nn_ensemble_parity_polynomial_cross(self, tmp_path):
        _need_ort()
        m = NNSurrogate(config={"bounds": dict(BOUNDS2),
                                "augmenter": "polynomial_cross",
                                "epochs": 200, "hidden": 8,
                                "n_ensemble": 2, "seed": 42})
        m.fit(_nn_samples())
        res = export_onnx_numpy(m, tmp_path / "nn.onnx")
        assert res["verified"] is True
        assert res["n_ensemble"] == 2
        # 特征面=base+cross（augmenter 档语义透出）
        assert res["param_names"] == ["a", "b"]
        _assert_parity(m, tmp_path / "nn.onnx", res["metric_names"],
                       list(BOUNDS2))

    def test_rff_gp_parity(self, tmp_path):
        _need_ort()
        m = RffGPSurrogate(config={"bounds": dict(BOUNDS2),
                                   "n_features": 32, "seed": 7})
        m.fit(_nn_samples())
        res = export_onnx_numpy(m, tmp_path / "rff.onnx")
        assert res["verified"] is True
        _assert_parity(m, tmp_path / "rff.onnx", res["metric_names"],
                       list(BOUNDS2))

    def test_green_op_ridge_parity(self, tmp_path):
        """green_op：复 S→|S|→dB→带内 max/min 链；metric_names=交错序。"""
        _need_ort()
        m = GreenOperatorSurrogate(config={
            "bounds": dict(BOUNDS2), "n_ports": 2, "n_freq": T_N,
            "freq_grid_ghz": [0.0, 1.0], "reciprocal": True,
            "head": "ridge", "poly_degree": 2})
        m.fit(_go_samples())
        out = tmp_path / "go.onnx"
        res = export_onnx_numpy(m, out)
        assert res["verified"] is True
        assert res["output"]["name"] == "metrics"
        # 交错序 [s11_max, s11_min, s12_max, s12_min, s21..., s22...]（4 对）
        assert len(res["metric_names"]) == 2 * 2 * 2
        assert res["metric_names"][0] == "s11_db_max_in_band"
        assert res["metric_names"][1] == "s11_db_min_in_band"
        _assert_parity(m, out, res["metric_names"], list(BOUNDS2))


# ── D：负例面（零依赖可跑） ─────────────────────────────────────────────────


class TestNegativeSurface:
    def test_unfitted_explicit_error(self, tmp_path):
        m = PolyRidgeSurrogate(config={"bounds": dict(BOUNDS2)})
        with pytest.raises(RuntimeError, match="未拟合"):
            export_onnx_numpy(m, tmp_path / "x.onnx")

    def test_numpy_path_rejects_non_numpy_kind(self, tmp_path):
        """numpy 直出口拒 torch 键（列 numpy 面+指引）。"""
        fake = SimpleNamespace(KIND="fno", fitted=True)
        with pytest.raises(ValueError, match="poly_ridge") as ei:
            export_onnx_numpy(fake, tmp_path / "x.onnx")
        for k in NUMPY_EXPORTABLE_KINDS:
            assert k in str(ei.value)

    def test_auto_pending_kind_explicit_reason(self):
        """pending 键显式报错带逐键原因+python 推理指引。"""
        fake = SimpleNamespace(KIND="gnn_geom", fitted=True)
        with pytest.raises(ValueError, match="可转换但未实施"):
            export_onnx_auto(fake, "x.onnx")
        assert NUMPY_PENDING_KINDS["gnn_geom"]

    def test_auto_unsupported_kind_explicit_reason(self):
        """unsupported 键显式报错带原因（核方法/树/物理求解）。"""
        for kind in ("mt_gp", "gbdt", "pole_residue"):
            fake = SimpleNamespace(KIND=kind, fitted=True)
            with pytest.raises(ValueError, match="不支持"):
                export_onnx_auto(fake, "x.onnx")

    def test_auto_torch_uncovered_kind_explicit(self):
        """torch 未覆盖键（fno_lite/deeponet）显式报错不冒充可导出。"""
        fake = SimpleNamespace(KIND="fno_lite", fitted=True)
        with pytest.raises(ValueError, match="T-N20"):
            export_onnx_auto(fake, "x.onnx")

    def test_nn_wilkinson_rf_augmenter_rejected(self, tmp_path):
        """nn 缺省 wilkinson_rf 档（forward_z0 物理闭式）显式拒绝+指引。"""
        m = NNSurrogate(config={"bounds": dict(BOUNDS2), "epochs": 30,
                                "hidden": 8, "n_ensemble": 1, "seed": 42})
        m.fit(_nn_samples())
        with pytest.raises(ValueError, match="polynomial_cross"):
            export_onnx_numpy(m, tmp_path / "x.onnx")


# ── E：确定性钉 ─────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_poly_ridge_two_export_bytes_identical(self, tmp_path_factory):
        shas = []
        for i in range(2):
            m = PolyRidgeSurrogate(config={"bounds": dict(BOUNDS2)})
            m.fit(_linear_samples())
            out = tmp_path_factory.mktemp(f"d5det{i}") / "poly.onnx"
            res = export_onnx_numpy(m, out)
            assert res["ok"] is True
            shas.append(hashlib.sha256(out.read_bytes()).hexdigest())
        assert shas[0] == shas[1]
        assert shas[0] == res["sha256"]

    def test_rff_gp_two_export_bytes_identical(self, tmp_path_factory):
        """rff_gp：fit 含谱采样随机面——同 seed 两跑仍逐字节（确定性红线）。"""
        shas = []
        for i in range(2):
            m = RffGPSurrogate(config={"bounds": dict(BOUNDS2),
                                       "n_features": 32, "seed": 7})
            m.fit(_nn_samples())
            out = tmp_path_factory.mktemp(f"d5detff{i}") / "rff.onnx"
            res = export_onnx_numpy(m, out)
            shas.append(hashlib.sha256(out.read_bytes()).hexdigest())
        assert shas[0] == shas[1]
        assert shas[0] == res["sha256"]


# ── A4/C：零改动 + 分派委托 + service 消费面 ────────────────────────────────


class TestDispatchAndConsumers:
    def test_export_readonly_model_unchanged(self, tmp_path):
        """导出只读：导出前后原模型 predict dict 逐位一致（零改动钉）。"""
        m = PolyRidgeSurrogate(config={"bounds": dict(BOUNDS2)})
        m.fit(_linear_samples())
        before = {k: m.predict({"a": 1.3, "b": -0.2})[k]
                  for k in m.models}
        export_onnx_numpy(m, tmp_path / "ro.onnx", verify=False)
        after = {k: m.predict({"a": 1.3, "b": -0.2})[k] for k in m.models}
        assert before == after

    def test_auto_torch_key_delegates_dynamo_path(self, tmp_path_factory):
        """分派委托一致性：auto(fno) 与 export_onnx(同 seed 重拟合) 同字节。"""
        pytest.importorskip("torch", reason="torch 为可选依赖")
        _need_ort()
        cfg = {"bounds": {"x": (0.0, 1.0)}, "freq_grid": [0.0, 1.0],
               "curve_samples": 8, "width": 8, "n_modes": 4, "n_layers": 2,
               "epochs": 30, "seed": 42}
        rng = np.random.default_rng(0)
        samples = [{"params": {"x": float(v)},
                    "metrics": {"s11_curve_db":
                                (np.sin(2 * np.pi * 1.3 * np.linspace(0, 1, 8)
                                        + 3 * v) + 0.5).tolist()}}
                   for v in rng.uniform(0.0, 1.0, 20)]
        shas = []
        for i, fn in enumerate((export_onnx_auto, export_onnx)):
            m = FNOSurrogate(config=dict(cfg))
            m.fit(samples)
            out = tmp_path_factory.mktemp(f"d5disp{i}") / "fno.onnx"
            res = fn(m, out)
            assert res["exporter"] == "dynamo" and res["verified"] is True
            shas.append(hashlib.sha256(out.read_bytes()).hexdigest())
        assert shas[0] == shas[1]

    def test_service_auto_envelope_poly_ridge(self, tmp_path):
        """service format='auto'：numpy 键正面信封（sha256/metric_names）。"""
        sp = tmp_path / "samples.json"
        sp.write_text(json.dumps(_linear_samples()), encoding="utf-8")
        r = surrogate_export_onnx({
            "kind": "poly_ridge", "config": {"bounds": dict(BOUNDS2)},
            "samples_path": str(sp),
            "out_path": str(tmp_path / "p.onnx"), "format": "auto"})
        assert r["ok"] is True, r.get("errors")
        assert r["verified"] is True and r["sha256"]
        assert r["metric_names"] == ["cost", "gain"]
        assert Path(r["path"]).is_file()

    def test_service_legacy_default_rejects_numpy_kind(self, tmp_path):
        """service 缺省 format='torch'：poly_ridge 拒绝文案逐字节沿旧钉。"""
        r = surrogate_export_onnx({
            "kind": "poly_ridge", "config": {}, "out_path": "x.onnx",
            "samples": [{"params": {"a": 0.5, "b": 0.0},
                         "metrics": {"cost": 1.0}}]})
        assert r["ok"] is False
        assert "fno, deep_ensemble, siren" in r["errors"][0]

    def test_service_numpy_format_rejects_torch_kind(self):
        """service format='numpy'：torch 键拟合前拦截（不白跑训练）。"""
        r = surrogate_export_onnx({
            "kind": "fno", "config": {}, "out_path": "x.onnx",
            "samples": [{"params": {"x": 0.5},
                         "metrics": {"s11_curve_db": [0.0] * 8}}],
            "format": "numpy"})
        assert r["ok"] is False
        assert "poly_ridge" in r["errors"][0]

    def test_service_bad_format_rejected(self):
        r = surrogate_export_onnx({
            "kind": "poly_ridge", "config": {}, "out_path": "x.onnx",
            "samples": [], "format": "onnx2"})
        assert r["ok"] is False
        assert "format" in r["errors"][0]
