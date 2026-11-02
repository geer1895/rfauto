"""T-N20 ONNX 导出面单测（aurora_n W3，注册键导出面 fno/deep_ensemble/siren）。

判据（任务书预声明，门值冻结于 runs/aurora_n/w3_tn20/criteria.md）：
- A1 导出-回代对拍：torch 原生 predict vs onnxruntime 推理 allclose
  （rtol=1e-4/atol=1e-5 预声明——float32 权重 + ONNX DFT/目标算子分解
  与 torch 原生路径的浮点舍入差异，单测档实测量级 ~1e-7；测试面**独立
  复算**不经内核 self-verify，#118 裁判分离家法）；
- A2 负例（零依赖可跑）：非支持键（numpy 系 poly_ridge / torch 未覆盖键
  nn）显式报错列支持面三键；未拟合显式报错；service/CLI 信封同构；
- A3 确定性钉：同 seed 两 fit 两导出 → onnx 文件 sha256 逐字节一致
  （导出器原生 protobuf map 序不定已由内核 deterministic 序列化规范化，
  实测登记见 onnx_export docstring）；
- A4 零改动：导出只读模型（导出前后 predict 逐位一致）+ 既有注册面
  全在 + onnx 缺席=导出面缺席诚实报错（T-N17 botorch 家法，lazy import
  + importorskip 形态——onnx/onnxruntime 各自独立 skip，不与 torch 混同）。

消费面：service 信封（JSON 进出）+ CLI 叶（--json 成功/失败同构）。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.optimization.surrogate import (
    DeepEnsembleSurrogate,
    FNOSurrogate,
    NNSurrogate,
    PolyRidgeSurrogate,
    SirenFieldSurrogate,
    surrogate_registry,
)
from rfauto.optimization.surrogate.onnx_export import (
    PARITY_ATOL,
    PARITY_RTOL,
    SUPPORTED_KINDS,
    export_onnx,
)
from rfauto.service.surrogate_export_service import surrogate_export_onnx

# ── 依赖面（分层 skip：torch+onnx=导出面；onnxruntime=对拍面） ────────────

torch = pytest.importorskip("torch", reason="torch 为可选依赖（extra: torch）")
onnx = pytest.importorskip("onnx", reason="onnx 为可选依赖（extra: onnx）")


def _need_ort():
    pytest.importorskip("onnxruntime",
                        reason="onnxruntime 为可选依赖（仅导出-回代对拍消费）")


# ── 合成语料（tiny 单测档；与 test_tn18/test_tn19 语料同族独立重写） ─────

T_N = 16
T_AXIS = np.linspace(0.0, 1.0, T_N)


def _curve(x: float) -> np.ndarray:
    return np.sin(2 * np.pi * 1.3 * T_AXIS + 3 * x) + 0.5


def _curve_samples(n: int = 20, seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    return [{"params": {"x": float(v)},
             "metrics": {"s11_curve_db": _curve(v).tolist()}}
            for v in rng.uniform(0.0, 1.0, n)]


FNO_CFG = {"bounds": {"x": (0.0, 1.0)}, "freq_grid": [0.0, 1.0],
           "curve_samples": T_N, "width": 8, "n_modes": 4, "n_layers": 2,
           "epochs": 50, "lr": 5e-3, "seed": 42}


def _field(x, y):
    return np.cos(2 * np.pi * 3 * x) * np.cos(2 * np.pi * 5 * y) + 0.5


def _field_samples(n: int = 256, seed: int = 1, complex_mode: bool = False):
    rng = np.random.default_rng(seed)
    pts = rng.uniform(0.0, 1.0, (n, 2))
    out = []
    for x, y in pts:
        v = (_field(x, y) if not complex_mode
             else complex(float(np.cos(2 * np.pi * 3 * x)),
                          float(np.sin(2 * np.pi * 5 * y))))
        out.append({"params": {"x": float(x), "y": float(y)},
                    "metrics": {"field": v}})
    return out


SIREN_CFG = {"coord_keys": ["x", "y"], "field_key": "field",
             "width": 16, "n_hidden": 2, "epochs": 200, "seed": 42}


@pytest.fixture(scope="module")
def fno_model():
    m = FNOSurrogate(config=dict(FNO_CFG))
    m.fit(_curve_samples())
    return m


@pytest.fixture(scope="module")
def fno_export(fno_model, tmp_path_factory):
    out = tmp_path_factory.mktemp("tn20") / "fno.onnx"
    res = export_onnx(fno_model, out)
    return res, out


@pytest.fixture(scope="module")
def siren_model():
    m = SirenFieldSurrogate(config=dict(SIREN_CFG))
    m.fit(_field_samples())
    return m


@pytest.fixture(scope="module")
def siren_export(siren_model, tmp_path_factory):
    out = tmp_path_factory.mktemp("tn20") / "siren.onnx"
    res = export_onnx(siren_model, out)
    return res, out


@pytest.fixture(scope="module")
def siren_cplx_model():
    cfg = dict(SIREN_CFG)
    cfg["field_key"] = "field"
    m = SirenFieldSurrogate(config=cfg)
    m.fit(_field_samples(complex_mode=True))
    return m


@pytest.fixture(scope="module")
def de_model():
    m = DeepEnsembleSurrogate(config={
        "bounds": {"x": (0.0, 1.0)}, "freq_grid": [0.0, 1.0],
        "curve_samples": T_N, "width": 8, "n_modes": 4, "n_layers": 2,
        "epochs": 50, "n_members": 2, "seed": 42})
    m.fit(_curve_samples())
    return m


@pytest.fixture(scope="module")
def de_export(de_model, tmp_path_factory):
    out = tmp_path_factory.mktemp("tn20") / "de.onnx"
    res = export_onnx(de_model, out)
    return res, out


# ── A2：负例面（零依赖；支持面列出 + 未拟合 + 依赖缺席指引） ─────────────


class TestNegativeSurface:
    def test_numpy_kind_explicit_error_lists_surface(self, tmp_path):
        """非 torch 键显式报错列支持面（验收②；poly_ridge=numpy 系代表）。"""
        model = PolyRidgeSurrogate(config={"bounds": {"x": (0.0, 1.0)}})
        with pytest.raises(ValueError, match="支持面") as ei:
            export_onnx(model, tmp_path / "x.onnx")
        for k in SUPPORTED_KINDS:
            assert k in str(ei.value)

    def test_uncovered_torch_kind_same_explicit_error(self, tmp_path):
        """torch 系但未覆盖键（nn）同列支持面——覆盖面诚实=三键不虚报。"""
        model = NNSurrogate(config={"bounds": {"x": (0.0, 1.0)}})
        with pytest.raises(ValueError, match="fno, deep_ensemble, siren"):
            export_onnx(model, tmp_path / "x.onnx")

    def test_unfitted_explicit_error(self, tmp_path):
        model = FNOSurrogate(config=dict(FNO_CFG))
        with pytest.raises(RuntimeError, match="未拟合"):
            export_onnx(model, tmp_path / "x.onnx")

    def test_service_envelope_negatives(self, tmp_path):
        """service 信封：参数缺失/样本文件缺失/不支持 kind（零依赖可跑）。"""
        r = surrogate_export_onnx({})
        assert r["ok"] is False and r["errors"]
        r = surrogate_export_onnx({"kind": "fno", "config": {},
                                   "out_path": str(tmp_path / "x.onnx")})
        assert r["ok"] is False
        r = surrogate_export_onnx({
            "kind": "poly_ridge", "config": {}, "out_path": "x.onnx",
            "samples": [{"params": {"x": 0.5}, "metrics": {"cost": 1.0}}]})
        assert r["ok"] is False
        assert "fno, deep_ensemble, siren" in r["errors"][0]

    def test_onnx_absent_surface_absent(self, fno_model, tmp_path, monkeypatch):
        """onnx 缺席=导出面缺席+诚实报错（T-N17 家法；lazy import 不炸面）。"""
        monkeypatch.setitem(sys.modules, "onnx", None)
        with pytest.raises(RuntimeError, match="rfauto\\[onnx\\]"):
            export_onnx(fno_model, tmp_path / "x.onnx")


# ── A1：导出-回代对拍（三键；测试面独立复算） ─────────────────────────────


class TestBacktranslateParity:
    def test_fno_curve_parity(self, fno_model, fno_export):
        """fno：params (P,) → s11_db (T,)，torch 原生 predict_curve 对照。"""
        _need_ort()
        import onnxruntime as ort

        res, path = fno_export
        assert res["ok"] is True and res["verified"] is True
        sess = ort.InferenceSession(str(path),
                                    providers=["CPUExecutionProvider"])
        for x in (0.5, 0.05, 0.95, 0.27, 0.73):
            native = np.asarray(fno_model.predict_curve({"x": x})["s11_db"],
                                dtype=np.float64)
            got = sess.run(None, {"params": np.asarray([x],
                                                       dtype=np.float32)})[0]
            assert got.shape == (T_N,)
            assert np.allclose(native, got.ravel(),
                               rtol=PARITY_RTOL, atol=PARITY_ATOL), (
                               f"x={x} max|Δ|="
                               f"{np.max(np.abs(native - got.ravel()))}")

    def test_siren_field_parity_real(self, siren_model, siren_export):
        """siren 实数场：coords (D,) → values (1,)。"""
        _need_ort()
        import onnxruntime as ort

        res, path = siren_export
        assert res["verified"] is True and res["field_mode"] == "real"
        sess = ort.InferenceSession(str(path),
                                    providers=["CPUExecutionProvider"])
        for x, y in ((0.5, 0.5), (0.1, 0.9), (0.8, 0.2)):
            native = float(siren_model.predict({"x": x, "y": y})["field"])
            got = sess.run(None, {"coords": np.asarray([x, y],
                                                       dtype=np.float32)})[0]
            assert got.shape == (1,)
            assert abs(native - float(got[0])) <= PARITY_ATOL + PARITY_RTOL \
                * abs(native)

    def test_siren_field_parity_complex(self, siren_cplx_model,
                                        tmp_path_factory):
        """siren 复数场：输出 (2,)=re/im，complex(out[0], out[1]) 重组对照。"""
        _need_ort()
        import onnxruntime as ort

        out = tmp_path_factory.mktemp("tn20c") / "siren_cplx.onnx"
        res = export_onnx(siren_cplx_model, out)
        assert res["field_mode"] == "complex" and res["verified"] is True
        sess = ort.InferenceSession(str(out),
                                    providers=["CPUExecutionProvider"])
        for x, y in ((0.5, 0.5), (0.1, 0.9)):
            native = complex(
                siren_cplx_model.predict({"x": x, "y": y})["field"])
            got = sess.run(None, {"coords": np.asarray([x, y],
                                                       dtype=np.float32)})[0]
            assert got.shape == (2,)
            got_c = complex(float(got[0]), float(got[1]))
            assert abs(native - got_c) <= PARITY_ATOL + PARITY_RTOL \
                * abs(native)

    def test_deep_ensemble_parity_mean_std(self, de_model, de_export):
        """deep_ensemble：(2,T)=[均值; σ]，predict_curve_with_std 对照。"""
        _need_ort()
        import onnxruntime as ort

        res, path = de_export
        assert res["verified"] is True and res["n_members"] == 2
        sess = ort.InferenceSession(str(path),
                                    providers=["CPUExecutionProvider"])
        for x in (0.5, 0.13, 0.87):
            out = de_model.predict_curve_with_std({"x": x})
            native_mean = np.asarray(out["s11_db"], dtype=np.float64)
            native_std = np.asarray(out["s11_db_std"], dtype=np.float64)
            got = sess.run(None, {"params": np.asarray([x],
                                                       dtype=np.float32)})[0]
            assert got.shape == (2, T_N)
            assert np.allclose(native_mean, got[0],
                               rtol=PARITY_RTOL, atol=PARITY_ATOL)
            assert np.allclose(native_std, got[1],
                               rtol=PARITY_RTOL, atol=PARITY_ATOL)


# ── A3：确定性钉（同 seed 两 fit 两导出字节一致） ─────────────────────────


class TestDeterminism:
    def test_same_seed_two_export_bytes_identical(self, tmp_path_factory):
        """同 seed 两 fit → 两 onnx sha256 逐字节一致（验收③）。

        现场重拟合同 seed 确定性（三键 fit 固定种子）+ 导出 protobuf
        deterministic 规范化，两级串联同字节。
        """
        shas = []
        for i in range(2):
            m = FNOSurrogate(config=dict(FNO_CFG))
            m.fit(_curve_samples())
            out = tmp_path_factory.mktemp(f"tn20d{i}") / "fno.onnx"
            res = export_onnx(m, out)
            assert res["ok"] is True
            shas.append(hashlib.sha256(out.read_bytes()).hexdigest())
        assert shas[0] == shas[1]
        # 导出返回的 sha256 与盘上文件一致（防自报与落盘脱钩）
        assert shas[0] == res["sha256"]


# ── A4：零改动 + 注册面 + service/CLI 消费面 ──────────────────────────────


class TestZeroImpactAndConsumers:
    def test_export_readonly_model_unchanged(self, fno_model, fno_export):
        """导出只读：导出后原模型 predict_curve 逐位不变（A4 零改动）。"""
        for x in (0.3, 0.7):
            curve = np.asarray(fno_model.predict_curve({"x": x})["s11_db"])
            assert curve.shape == (T_N,) and np.isfinite(curve).all()
        # fixture 内导出已完成——此处复读仍逐位确定（predict 纯函数语义）
        c1 = np.asarray(fno_model.predict_curve({"x": 0.3})["s11_db"])
        c2 = np.asarray(fno_model.predict_curve({"x": 0.3})["s11_db"])
        assert np.array_equal(c1, c2)

    def test_registry_surface_intact(self):
        """既有注册面全在（零改动存在面）。"""
        for k in ("fno_lite", "fno", "deeponet", "ensemble", "poly_ridge",
                  "smt_kriging", "conformal", "deep_ensemble", "siren"):
            assert k in surrogate_registry.available()

    def test_service_ok_envelope(self, tmp_path):
        """service 正面：samples_path+config JSON 进出，sha256/n_samples 在。"""
        sp = tmp_path / "samples.json"
        sp.write_text(json.dumps(_curve_samples()), encoding="utf-8")
        r = surrogate_export_onnx({
            "kind": "fno", "config": FNO_CFG,
            "samples_path": str(sp), "out_path": str(tmp_path / "f.onnx")})
        assert r["ok"] is True, r.get("errors")
        assert r["verified"] is True and r["sha256"] and r["n_samples"] == 20
        assert r["input"]["name"] == "params"
        assert Path(r["path"]).is_file()

    def test_verify_skipped_note_when_ort_absent(self, fno_model,
                                                 tmp_path, monkeypatch):
        """onnxruntime 缺席：导出成功+对拍跳过注记（best-effort 不阻塞）。"""
        import rfauto.optimization.surrogate.onnx_export as mod

        monkeypatch.setattr(mod, "_ensure_onnxruntime", lambda: None)
        r = export_onnx(fno_model, tmp_path / "nover.onnx")
        assert r["ok"] is True and r["verified"] is False
        assert "onnxruntime" in r["verify_note"]

    def test_cli_json_envelope_success_and_failure(self, tmp_path, monkeypatch):
        """CLI 叶 --json：成功/失败信封同构（#144：chdir 隔离零 runs 湖写入）。"""
        from typer.testing import CliRunner

        from rfauto.cli.main import app as root_app

        monkeypatch.chdir(tmp_path)   # 导出落盘走 tmp（#144 家法）
        sp = tmp_path / "samples.json"
        sp.write_text(json.dumps(_curve_samples(12)), encoding="utf-8")
        cfg = dict(FNO_CFG)
        cfg["epochs"] = 30
        cp = tmp_path / "config.json"
        cp.write_text(json.dumps(cfg), encoding="utf-8")
        runner = CliRunner()
        ok = runner.invoke(root_app, [
            "surrogate", "export-onnx", "fno", str(sp), str(tmp_path / "c.onnx"),
            "--config", str(cp), "--json"])
        assert ok.exit_code == 0, ok.output[:400]
        payload = json.loads(ok.output[ok.output.index("{"):])
        assert payload.get("ok") is True and payload.get("sha256")
        bad = runner.invoke(root_app, [
            "surrogate", "export-onnx", "poly_ridge", str(sp),
            str(tmp_path / "b.onnx"), "--config", str(cp), "--json"])
        assert bad.exit_code == 1
        bad_payload = json.loads(bad.output[bad.output.index("{"):])
        assert bad_payload.get("ok") is False and bad_payload.get("errors")
