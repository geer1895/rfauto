"""core/neural_surrogate 神经代理内核单测（aurora_r R-05 / B1）。

分层：
- torch 无关内核全测（归一化逐位回收/数据集对齐/切分/LOO 聚合/纯 numpy
  前向/信封契约/unavailable 路径/CNN 占位）；
- torch 依赖面用 skipif 钉住（装了才跑，torch 缺失环境只跳过 torch 组，
  torch 无关组照常全跑）——与 test_deeponet 的模块级 importorskip 不同，
  本文件 torch 无关组必须存活于无 torch 环境；
- #118 双源对拍：mlp_forward_numpy vs 手工标量双重循环（双 numpy 路径）
  + torch 前向 vs mlp_forward_numpy（跨实现路径）；aggregate_loo_metrics
  vs 手工求和公式。
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

_src_dir = Path(__file__).parent.parent.parent / "src"
if _src_dir.exists() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

import rfauto.core.neural_surrogate as ns
from rfauto.core.neural_surrogate import (
    ACTIVATIONS,
    NORMALIZATION_KINDS,
    CNNSpec,
    MLPSpec,
    NormalizationSpec,
    aggregate_loo_metrics,
    apply_normalization,
    build_cnn_surrogate,
    build_sparam_dataset,
    derive_mlp_spec,
    fit_normalization,
    loo_folds,
    mlp_forward_numpy,
    mlp_spec_from_dict,
    mlp_spec_to_dict,
    predict_mlp,
    split_train_val,
    torch_available,
    undo_normalization,
    validate_mlp_spec,
)


def _torch_ok() -> bool:
    """torch 可用性懒探测（skipif 条件；无 torch 环境不炸收集）。"""
    try:
        return torch_available()
    except Exception:  # pragma: no cover - 探测自身异常按缺失处理
        return False


_requires_torch = pytest.mark.skipif(
    not _torch_ok(), reason="torch 为可选依赖（extra: torch），未安装跳过")


# ─── 合成夹具（S 参数合成响应面；数值为测试夹具非物理断言） ──────────────────

FREQS_HZ = [1.0e9, 1.5e9, 2.0e9, 2.5e9]  # T=4


def _s21_curve(x: float, freqs: np.ndarray) -> np.ndarray:
    """单参数光滑复响应（衰减+线性相位，re/im 双光滑），测试夹具。"""
    f_ghz = np.asarray(freqs, dtype=np.float64) / 1e9
    amp = 0.5 + 1.5 * x
    tau = 0.2 + 0.6 * x
    return np.exp(-amp - 1j * 2.0 * np.pi * f_ghz * tau)


def _synthetic_samples(n: int = 24, n_grid: int = 8):
    freqs = np.linspace(1.0e9, 2.0e9, n_grid)
    samples = []
    for x in np.linspace(0.0, 1.0, n):
        samples.append({"params": {"x": float(x)},
                        "curves": {"s21": _s21_curve(float(x), freqs).tolist()}})
    return samples, freqs


def _synthetic_dataset(n: int = 24, n_grid: int = 8) -> dict:
    samples, freqs = _synthetic_samples(n, n_grid)
    return build_sparam_dataset(samples, freqs_hz=freqs.tolist())


def _two_channel_dataset() -> dict:
    """2 参数 × 2 通道 × T=4 小数据集（列序/偏移/数值精确断言用）。"""
    freqs = FREQS_HZ
    samples = []
    for x, y in [(0.0, 1.0), (0.5, 2.0), (1.0, 3.0)]:
        s11 = [complex(0.1 * x + 0.01 * k, -0.2 * y) for k in range(4)]
        s21 = [complex(0.3 * x, 0.4 * y - 0.05 * k) for k in range(4)]
        samples.append({"params": {"x": x, "y": y},
                        "curves": {"s11": s11, "s21": s21}})
    return build_sparam_dataset(samples, freqs_hz=freqs)


# ─── 归一化窗口（纯函数 + 逆变换，逐位回收钉） ───────────────────────────────


class TestNormalization:
    def test_minmax_fit_exact(self):
        x = np.array([[0.0, 1.0], [8.0, 3.0], [4.0, 2.0]])
        spec = fit_normalization(x, "minmax")
        assert spec.kind == "minmax"
        assert spec.center == (0.0, 1.0)
        assert spec.scale == (8.0, 2.0)

    def test_standard_fit_values(self):
        x = np.array([[0.0], [2.0], [4.0]])
        spec = fit_normalization(x, "standard")
        assert spec.center == (2.0,)  # 均值精确
        assert spec.scale[0] == pytest.approx(math.sqrt(8.0 / 3.0), rel=1e-15)

    def test_roundtrip_bitexact_power_of_two(self):
        """2 的幂窗宽格点：apply→undo 逐位相等（== 断言，非 approx）。"""
        x = np.array([[1.0], [1.25], [1.5], [2.0], [2.5], [3.0]])
        spec = fit_normalization(x, "minmax")
        rec = undo_normalization(spec, apply_normalization(spec, x))
        assert np.array_equal(rec, x)
        x2 = np.array([[0.0], [2.0], [4.0], [6.0], [8.0]])
        spec2 = fit_normalization(x2, "minmax")
        assert np.array_equal(
            undo_normalization(spec2, apply_normalization(spec2, x2)), x2)

    def test_roundtrip_general_within_1e15(self):
        rng = np.random.default_rng(7)
        x = rng.uniform(-3.0, 5.0, (50, 4))
        for kind in NORMALIZATION_KINDS:
            spec = fit_normalization(x, kind)
            rec = undo_normalization(spec, apply_normalization(spec, x))
            scale = np.asarray(spec.scale)
            scale = np.where(np.abs(scale) < 1e-12, 1.0, scale)
            assert float(np.max(np.abs(rec - x) / scale)) <= 1e-15, kind

    def test_degenerate_dim_invertible(self):
        """常数列：scale=0 如实落窗，窗口内恒 0 且逆变换逐位回收。"""
        x = np.array([[2.0, 1.0], [2.0, 3.0]])
        for kind in NORMALIZATION_KINDS:
            spec = fit_normalization(x, kind)
            assert spec.scale[0] == 0.0
            xn = apply_normalization(spec, x)
            assert np.all(xn[:, 0] == 0.0)
            assert np.array_equal(undo_normalization(spec, xn), x), kind

    def test_spec_json_roundtrip_bitexact(self):
        rng = np.random.default_rng(11)
        x = rng.uniform(-1.0, 1.0, (20, 3))
        for kind in NORMALIZATION_KINDS:
            spec = fit_normalization(x, kind)
            spec2 = NormalizationSpec.from_dict(
                json.loads(json.dumps(spec.to_dict())))
            assert spec2 == spec
            assert np.array_equal(
                apply_normalization(spec, x), apply_normalization(spec2, x))

    def test_apply_dim_mismatch_raises(self):
        spec = fit_normalization(np.zeros((3, 2)), "minmax")
        with pytest.raises(ValueError, match="不一致"):
            apply_normalization(spec, np.zeros((3, 3)))
        with pytest.raises(ValueError, match="不一致"):
            undo_normalization(spec, np.zeros((2, 5)))

    def test_fit_rejects_unknown_kind_and_bad_shape(self):
        with pytest.raises(ValueError, match="归一化档"):
            fit_normalization(np.zeros((3, 2)), "robust")
        with pytest.raises(ValueError, match="二维"):
            fit_normalization(np.zeros(3), "minmax")


# ─── 模型规格声明 ────────────────────────────────────────────────────────────


class TestSpec:
    def test_validation_errors(self):
        base = {"n_inputs": 2, "n_outputs": 4}
        errs = validate_mlp_spec(MLPSpec(**base, activation="swish"))
        assert any("激活" in e for e in errs)
        errs = validate_mlp_spec(MLPSpec(**base, output_head="mag_phase"))
        assert any("output_head" in e for e in errs)
        errs = validate_mlp_spec(MLPSpec(**base, hidden=()))
        assert any("hidden" in e for e in errs)
        errs = validate_mlp_spec(
            MLPSpec(n_inputs=0, n_outputs=0, epochs=0, lr=-1.0,
                    weight_decay=-0.1))
        assert len(errs) >= 5
        assert validate_mlp_spec(MLPSpec(**base)) == []

    def test_json_roundtrip(self):
        spec = MLPSpec(n_inputs=3, n_outputs=8, hidden=(16, 8), seed=7,
                       lr=0.01, weight_decay=1e-4)
        spec2 = mlp_spec_from_dict(json.loads(json.dumps(mlp_spec_to_dict(spec))))
        assert spec2 == spec
        assert spec2.hidden == (16, 8)

    def test_derive_from_dataset(self):
        ds = _two_channel_dataset()
        spec = derive_mlp_spec(ds, hidden=(8,), epochs=10)
        assert spec.n_inputs == 2
        assert spec.n_outputs == 2 * 2 * 4
        with pytest.raises(ValueError, match="ok 信封"):
            derive_mlp_spec({"ok": False, "errors": ["x"]})


# ─── 数据集构建器 ────────────────────────────────────────────────────────────


class TestDatasetBuilder:
    def test_column_layout_exact(self):
        ds = _two_channel_dataset()
        assert ds["ok"] is True
        assert ds["param_names"] == ["x", "y"]
        assert ds["channels"] == ["s11", "s21"]
        assert ds["n_grid"] == 4 and ds["n_samples"] == 3
        assert ds["n_outputs"] == 16
        assert ds["channel_offsets"] == {
            "s11": {"re_offset": 0, "im_offset": 4},
            "s21": {"re_offset": 8, "im_offset": 12},
        }
        y0 = ds["Y"][0]
        # 列序=通道 sorted 序、每通道先 re 后 im 各 T 列
        # （浮点字面量陷阱：0.4-0.05 ≠ 字面 0.35，逐列 1e-15 容差断言）
        np.testing.assert_allclose(y0[0:4], [0.0, 0.01, 0.02, 0.03],
                                   atol=1e-15)  # s11 re（x=0）
        np.testing.assert_allclose(y0[4:8], [-0.2, -0.2, -0.2, -0.2],
                                   atol=1e-15)  # s11 im（y=1）
        np.testing.assert_allclose(y0[8:12], [0.0, 0.0, 0.0, 0.0],
                                   atol=1e-15)  # s21 re
        np.testing.assert_allclose(y0[12:16], [0.4, 0.35, 0.3, 0.25],
                                   atol=1e-15)  # s21 im
        assert ds["X"][0] == [0.0, 1.0]

    def test_re_im_dict_form_and_param_order(self):
        samples = [{"params": {"b": 1.0, "a": 2.0},
                    "curves": {"c1": {"re": [1.0, 2.0], "im": [0.0, -1.0]}}}]
        ds = build_sparam_dataset(samples, freqs_hz=[1e9, 2e9],
                                  param_names=["b", "a"])
        assert ds["ok"] is True
        assert ds["param_names"] == ["b", "a"]  # 显式序不被 sorted 覆盖
        assert ds["Y"][0] == [1.0, 2.0, 0.0, -1.0]

    def test_grid_length_mismatch_error(self):
        samples = [{"params": {"x": 1.0}, "curves": {"s11": [0j] * 3}}]
        env = build_sparam_dataset(samples, freqs_hz=FREQS_HZ)
        assert env["ok"] is False
        assert any("样本 0" in e and "s11" in e for e in env["errors"])

    def test_param_keyset_mismatch_error(self):
        samples = [
            {"params": {"x": 1.0}, "curves": {"s11": [0j] * 4}},
            {"params": {"x": 1.0, "y": 2.0}, "curves": {"s11": [0j] * 4}},
        ]
        env = build_sparam_dataset(samples, freqs_hz=FREQS_HZ)
        assert env["ok"] is False
        assert any("键集" in e for e in env["errors"])

    def test_nonfinite_dropped_with_reason(self):
        freqs = FREQS_HZ
        nan = float("nan")
        samples = [
            {"params": {"x": 0.1}, "curves": {"s11": [0j] * 4}},
            {"params": {"x": nan}, "curves": {"s11": [0j] * 4}},
            {"params": {"x": 0.3},
             "curves": {"s11": [complex(1.0, nan)] + [0j] * 3}},
            {"params": {"x": float("inf")}, "curves": {"s11": [0j] * 4}},
        ]
        env = build_sparam_dataset(samples, freqs_hz=freqs)
        assert env["ok"] is True
        assert env["n_samples"] == 1 and env["n_dropped"] == 3
        assert [d["index"] for d in env["dropped"]] == [1, 2, 3]
        assert "非有限" in env["dropped"][0]["reason"]

    def test_all_dropped_error_envelope(self):
        samples = [{"params": {"x": float("nan")}, "curves": {"s11": [0j] * 4}}]
        env = build_sparam_dataset(samples, freqs_hz=FREQS_HZ)
        assert env["ok"] is False
        assert any("全部样本被丢弃" in e for e in env["errors"])

    def test_structural_errors(self):
        env = build_sparam_dataset([], freqs_hz=FREQS_HZ)
        assert env["ok"] is False and "空" in env["errors"][0]
        bad = [{"params": "not-a-dict", "curves": {"s11": [0j] * 4}}]
        assert build_sparam_dataset(bad, freqs_hz=FREQS_HZ)["ok"] is False
        assert build_sparam_dataset(
            [{"params": {"x": 1.0}, "curves": {"s11": [0j] * 4}}],
            freqs_hz=[float("nan"), 1.0])["ok"] is False
        # 标量曲线值（0 维）也是结构违例而非 IndexError
        scalar = [{"params": {"x": 1.0}, "curves": {"s11": 0.5}}]
        assert build_sparam_dataset(scalar, freqs_hz=FREQS_HZ)["ok"] is False


# ─── 切分与 LOO 聚合（纯函数） ───────────────────────────────────────────────


class TestSplitAndLoo:
    def test_split_deterministic_and_partition(self):
        a = split_train_val(10, val_frac=0.2, seed=3)
        b = split_train_val(10, val_frac=0.2, seed=3)
        assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])
        tr, va = a
        assert va.size == 2 and tr.size == 8
        assert set(tr.tolist()) | set(va.tolist()) == set(range(10))
        assert not set(tr.tolist()) & set(va.tolist())
        c = split_train_val(10, val_frac=0.2, seed=4)
        assert not np.array_equal(a[1], c[1])  # 换 seed 换划分

    def test_split_edges(self):
        tr, va = split_train_val(1, val_frac=0.2)
        assert tr.size == 1 and va.size == 0  # 单点全训
        tr, va = split_train_val(7, val_frac=0.0)
        assert va.size == 0 and tr.size == 7
        with pytest.raises(ValueError):
            split_train_val(5, val_frac=1.0)
        with pytest.raises(ValueError):
            split_train_val(0)

    def test_loo_folds_complement(self):
        folds = loo_folds(4)
        assert len(folds) == 4
        for i, (tr, va) in enumerate(folds):
            assert va.tolist() == [i]
            assert sorted(tr.tolist()) == [j for j in range(4) if j != i]
        with pytest.raises(ValueError):
            loo_folds(1)

    def test_aggregate_matches_manual_sums(self):
        """#118 独立口径：手工求和公式 vs 实现。"""
        t = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        p = np.array([[1.5, 2.0], [2.5, 5.0], [5.5, 6.0]])
        m = aggregate_loo_metrics(t, p)
        assert m["n_folds"] == 3
        assert m["rmse_per_column"][0] == pytest.approx(0.5)
        assert m["rmse_per_column"][1] == pytest.approx(math.sqrt(1.0 / 3.0))
        assert m["rmse_total"] == pytest.approx(
            math.sqrt(1.75 / 6.0))  # 手工：Σerr²=0.25×3+1.0，N=6
        for j in (0, 1):
            tc = t[:, j] - t[:, j].mean()
            pc = p[:, j] - p[:, j].mean()
            rho_manual = float(
                np.sum(tc * pc) / math.sqrt(float(np.sum(tc * tc))
                                            * float(np.sum(pc * pc))))
            got = m["pearson_rho_per_column"][j]
            assert got == pytest.approx(rho_manual, abs=1e-12)

    def test_aggregate_constant_column_rho_none(self):
        t = np.array([[1.0, 1.0], [2.0, 1.0], [3.0, 1.0]])
        p = np.array([[1.1, 5.0], [2.2, 5.0], [3.3, 5.0]])
        m = aggregate_loo_metrics(t, p)
        assert m["pearson_rho_per_column"][1] is None  # 预测常数列→ρ 如实 None
        assert m["pearson_rho_per_column"][0] == pytest.approx(1.0, abs=1e-12)

    def test_aggregate_perfect_and_shape_guard(self):
        t = np.array([[1.0, -2.0], [3.0, 4.0]])
        m = aggregate_loo_metrics(t, t.copy())
        assert m["rmse_total"] == 0.0
        with pytest.raises(ValueError, match="同形"):
            aggregate_loo_metrics(np.zeros((2, 2)), np.zeros((3, 2)))


# ─── 纯 numpy 前向（#118 双源对拍） ──────────────────────────────────────────


def _tiny_state(spec: MLPSpec, rng: np.random.Generator) -> dict:
    dims = [spec.n_inputs, *spec.hidden, spec.n_outputs]
    layers = []
    for din, dout in itertools.pairwise(dims):
        layers.append({"W": rng.normal(0.0, 0.5, (dout, din)).tolist(),
                       "b": rng.normal(0.0, 0.1, dout).tolist()})
    return {"layers": layers}


def _manual_forward(state: dict, spec: MLPSpec, x: np.ndarray) -> np.ndarray:
    """手工标量双重循环前向（与向量化实现互为独立路径，#118）。"""
    a = [float(v) for v in x]
    n_layers = len(state["layers"])
    for idx, layer in enumerate(state["layers"]):
        w, b = layer["W"], layer["b"]
        z = []
        for o in range(len(b)):
            s = float(b[o])
            for i, av in enumerate(a):
                s += float(av) * float(w[o][i])
            z.append(s)
        if idx < n_layers - 1:
            if spec.activation == "tanh":
                a = [math.tanh(v) for v in z]
            elif spec.activation == "relu":
                a = [max(v, 0.0) for v in z]
            elif spec.activation == "silu":
                a = [v / (1.0 + math.exp(-v)) for v in z]
            else:  # gelu（exact erf 形式）
                a = [0.5 * v * (1.0 + math.erf(v / math.sqrt(2.0)))
                     for v in z]
        else:
            a = z
    return np.array(a)


class TestNumpyForward:
    def test_matches_manual_loop_all_activations(self):
        rng = np.random.default_rng(21)
        x = rng.uniform(-1.0, 1.0, 2)
        for act in ACTIVATIONS:
            spec = MLPSpec(n_inputs=2, n_outputs=3, hidden=(4, 5),
                           activation=act)
            state = _tiny_state(spec, rng)
            got = mlp_forward_numpy(state, spec, x)
            want = _manual_forward(state, spec, x)
            np.testing.assert_allclose(got, want, rtol=1e-12, atol=1e-13)

    def test_batch_and_vector_forms(self):
        rng = np.random.default_rng(22)
        spec = MLPSpec(n_inputs=2, n_outputs=2, hidden=(6,))
        state = _tiny_state(spec, rng)
        xb = rng.uniform(-1.0, 1.0, (5, 2))
        batch = mlp_forward_numpy(state, spec, xb)
        assert batch.shape == (5, 2)
        for i in range(5):
            np.testing.assert_allclose(
                batch[i], mlp_forward_numpy(state, spec, xb[i]),
                rtol=1e-15, atol=0.0)

    def test_structure_guards(self):
        spec = MLPSpec(n_inputs=2, n_outputs=2, hidden=(4,))
        state = _tiny_state(spec, np.random.default_rng(23))
        with pytest.raises(ValueError, match="输入维"):
            mlp_forward_numpy(state, spec, np.zeros(3))
        with pytest.raises(ValueError, match="未知激活"):
            bad = dataclasses.replace(spec, activation="swish")
            mlp_forward_numpy(state, bad, np.zeros(2))
        with pytest.raises(ValueError, match="形状违例"):
            broken = {"layers": [{"W": [[1.0]], "b": [0.0, 0.0]}]}
            mlp_forward_numpy(broken, spec, np.zeros(2))
        with pytest.raises(ValueError, match="layers"):
            mlp_forward_numpy({"layers": []}, spec, np.zeros(2))
        with pytest.raises(ValueError, match="Mapping"):
            mlp_forward_numpy([1, 2], spec, np.zeros(2))


# ─── 信封契约：unavailable 路径 / 数据错误路径 / CNN 占位 ────────────────────


class TestEnvelopeContract:
    def test_unavailable_envelopes_no_torch(self, monkeypatch):
        monkeypatch.setattr(ns, "_load_torch", lambda: None)
        ds = _synthetic_dataset(n=6, n_grid=4)
        spec = derive_mlp_spec(ds, hidden=(4,), epochs=5)
        calls = [
            lambda: ns.fit_neural_surrogate(ds, spec),
            lambda: predict_mlp({"ok": True, "kind": "neural_surrogate_mlp",
                                 "state": {}, "norm_x": {}, "norm_y": {},
                                 "param_names": [], "spec": {}}, {}),
            lambda: ns.loo_evaluate_mlp(ds, spec),
        ]
        for call in calls:
            env = call()
            assert env["ok"] is False
            assert env["unavailable"] is True
            assert env["install_hint"] == ns.TORCH_INSTALL_HINT
            assert env["errors"] and all(
                isinstance(e, str) for e in env["errors"])
            assert "torch" in env["errors"][0]

    def test_torch_available_flag_monkeypatched(self, monkeypatch):
        monkeypatch.setattr(ns, "_load_torch", lambda: None)
        assert torch_available() is False

    def test_fit_data_error_envelopes(self, monkeypatch):
        # 假 torch 哨兵：错误路径在触达训练前返回，可离线钉数据面信封
        monkeypatch.setattr(ns, "_load_torch", lambda: object())
        ds = _synthetic_dataset(n=6, n_grid=4)
        spec_bad_dim = MLPSpec(n_inputs=99, n_outputs=99, epochs=3)
        env = ns.fit_neural_surrogate(ds, spec_bad_dim)
        assert env["ok"] is False and "unavailable" not in env
        assert "不一致" in env["errors"][0]
        env = ns.fit_neural_surrogate(ds, MLPSpec(
            n_inputs=1, n_outputs=32, activation="swish", epochs=3))
        assert env["ok"] is False and any("激活" in e for e in env["errors"])
        env = ns.fit_neural_surrogate({"ok": False, "errors": ["x"]},
                                      MLPSpec(n_inputs=1, n_outputs=32))
        assert env["ok"] is False and "ok 信封" in env["errors"][0]

    def test_predict_shape_and_missing_param_errors(self, monkeypatch):
        monkeypatch.setattr(ns, "_load_torch", lambda: object())
        env = predict_mlp({"ok": False}, {"x": 1.0})
        assert env["ok"] is False and "ok 信封" in env["errors"][0]
        fake_fit = {"ok": True, "kind": "neural_surrogate_mlp",
                    "state": {"layers": []}, "norm_x": {"kind": "minmax",
                                                        "center": [0.0],
                                                        "scale": [1.0]},
                    "norm_y": {"kind": "minmax", "center": [0.0],
                               "scale": [1.0]},
                    "param_names": ["x"], "n_grid": 1,
                    "channel_offsets": {"s21": {"re_offset": 0,
                                                "im_offset": 0}},
                    "freqs_hz": [1e9], "channels": ["s21"],
                    "spec": {"n_inputs": 1, "n_outputs": 2, "hidden": [4],
                             "activation": "tanh", "output_head": "re_im",
                             "epochs": 1, "lr": 0.1, "weight_decay": 0.0,
                             "seed": 1}}
        env = predict_mlp(fake_fit, {"y": 1.0})
        assert env["ok"] is False and "缺名" in env["errors"][0]
        tampered = dict(fake_fit, spec=dict(fake_fit["spec"], n_inputs=7))
        env = predict_mlp(tampered, {"x": 1.0})
        assert env["ok"] is False and "不一致" in env["errors"][0]

    def test_loo_max_folds_guard(self, monkeypatch):
        monkeypatch.setattr(ns, "_load_torch", lambda: object())
        ds = _synthetic_dataset(n=6, n_grid=4)
        spec = derive_mlp_spec(ds, hidden=(4,), epochs=3)
        env = ns.loo_evaluate_mlp(ds, spec, max_folds=0)
        assert env["ok"] is False and "max_folds" in env["errors"][0]

    def test_cnn_placeholder_structured(self):
        env = build_cnn_surrogate(
            CNNSpec(n_freq=64, footprint_rows=32, footprint_cols=32))
        assert env["ok"] is False
        assert env["not_implemented"] is True
        assert env["spec"]["footprint_rows"] == 32
        assert "未实现" in env["errors"][0]


# ─── torch 依赖面（skipif 钉住；本仓 venv 含 torch 2.14.0+cpu 实跑） ─────────


class TestTorchFace:
    @_requires_torch
    def test_training_bitwise_deterministic(self):
        ds = _synthetic_dataset(n=12, n_grid=4)
        spec = derive_mlp_spec(ds, hidden=(8, 8), epochs=400, lr=5e-3,
                               seed=42)
        f1 = ns.fit_neural_surrogate(ds, spec, val_frac=0.0)
        f2 = ns.fit_neural_surrogate(ds, spec, val_frac=0.0)
        assert f1["ok"] is True and f2["ok"] is True
        assert f1["state"] == f2["state"]  # 权重逐位一致
        assert f1["loss_history"] == f2["loss_history"]  # 损失轨迹逐位一致

    @_requires_torch
    def test_torch_forward_matches_numpy_oracle(self):
        """#118 跨实现对拍：torch 前向（predict 面）vs 纯 numpy 独立裁判。"""
        ds = _synthetic_dataset(n=10, n_grid=4)
        spec = derive_mlp_spec(ds, hidden=(8, 8), epochs=50, seed=1)
        fit_env = ns.fit_neural_surrogate(ds, spec, val_frac=0.0)
        assert fit_env["ok"] is True
        spec_r = mlp_spec_from_dict(fit_env["spec"])
        norm_x = NormalizationSpec.from_dict(fit_env["norm_x"])
        norm_y = NormalizationSpec.from_dict(fit_env["norm_y"])
        for xv in (0.1, 0.37, 0.83):
            pred = predict_mlp(fit_env, {"x": xv})
            assert pred["ok"] is True
            row_pred = np.zeros(spec_r.n_outputs)
            for c, o in fit_env["channel_offsets"].items():
                row_pred[o["re_offset"]:o["re_offset"] + fit_env["n_grid"]] = \
                    pred["curves"][c]["re"]
                row_pred[o["im_offset"]:o["im_offset"] + fit_env["n_grid"]] = \
                    pred["curves"][c]["im"]
            xn = apply_normalization(
                norm_x, np.array([[xv]], dtype=np.float64))
            row_np = undo_normalization(
                norm_y,
                mlp_forward_numpy(fit_env["state"], spec_r, xn))[0]
            np.testing.assert_allclose(row_pred, row_np, rtol=1e-10,
                                       atol=1e-12)

    @_requires_torch
    def test_fit_predict_recovery_on_held_out(self):
        """合成数据真训练回收：held-out 点 re/im 回收 RMSE ≤0.02。"""
        ds = _synthetic_dataset(n=24, n_grid=8)
        spec = derive_mlp_spec(ds, hidden=(32, 32), epochs=1500, lr=5e-3,
                               seed=42)
        fit_env = ns.fit_neural_surrogate(ds, spec, val_frac=0.0)
        assert fit_env["ok"] is True, fit_env.get("errors")
        freqs = np.asarray(ds["freqs_hz"])
        for xv in (0.37, 0.83):  # 非训练栅点（24 点栅步 1/23）
            pred = predict_mlp(fit_env, {"x": xv})
            assert pred["ok"] is True
            gt = _s21_curve(xv, freqs)
            got = np.array(pred["curves"]["s21"]["re"]) + 1j * np.array(
                pred["curves"]["s21"]["im"])
            rmse = float(np.sqrt(np.mean(np.abs(got - gt) ** 2)))
            assert rmse <= 0.02, f"x={xv} 回收 RMSE={rmse}"
            assert fit_env["train"]["rmse_per_channel"]["s21"] <= 0.02

    @_requires_torch
    def test_fit_envelope_json_roundtrip_predicts_identically(self):
        """服务层 JSON 进出契约：fit 信封 allow_nan=False 序列化逐位往返，
        JSON 态 predict 与内存态 predict 逐位同曲线。"""
        ds = _synthetic_dataset(n=14, n_grid=4)
        spec = derive_mlp_spec(ds, hidden=(16,), epochs=400, seed=3)
        fit_env = ns.fit_neural_surrogate(ds, spec, val_frac=0.2)
        assert fit_env["ok"] is True
        assert fit_env["n_train"] == 11 and fit_env["n_val"] == 3
        assert fit_env["val"] is not None
        assert fit_env["val"]["rmse_per_channel"]["s21"] >= 0.0
        blob = json.dumps(fit_env, allow_nan=False)
        fit2 = json.loads(blob)
        for xv in (0.2, 0.9):
            p1 = predict_mlp(fit_env, {"x": xv})
            p2 = predict_mlp(fit2, {"x": xv})
            assert p1 == p2  # float repr 往返精确 → dict 逐位相等

    @_requires_torch
    def test_loo_end_to_end(self):
        ds = _synthetic_dataset(n=6, n_grid=4)
        spec = derive_mlp_spec(ds, hidden=(16,), epochs=300, lr=5e-3, seed=5)
        env = ns.loo_evaluate_mlp(ds, spec)
        assert env["ok"] is True, env.get("errors")
        assert env["n_folds"] == 6 and len(env["per_fold"]) == 6
        assert env["loo"]["n_folds"] == 6
        assert all(v >= 0.0 for v in env["loo"]["rmse_per_column"])
        assert all(f["index"] == i for i, f in enumerate(env["per_fold"]))
        env3 = ns.loo_evaluate_mlp(ds, spec, max_folds=3)
        assert env3["n_folds"] == 3 and env3["loo"]["n_folds"] == 3

    @_requires_torch
    def test_predict_missing_param_error_envelope(self):
        ds = _synthetic_dataset(n=8, n_grid=4)
        spec = derive_mlp_spec(ds, hidden=(4,), epochs=20)
        fit_env = ns.fit_neural_surrogate(ds, spec, val_frac=0.0)
        env = predict_mlp(fit_env, {"y": 1.0})
        assert env["ok"] is False and "缺名" in env["errors"][0]
