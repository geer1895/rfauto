"""审查修复批 D（core 层）可见性标记回归钉。

覆盖 docs/audit/code_audit_slice1_core_20260929.md 的：
- P2-1：四处裸吞异常补 ``as exc`` + reason 面（error_budget / wcd /
  solve_health / run_artifact）——诊断信息不再在失败路径丢失；
- P2-2：MapesModel.predict 附 stage / z_all_source 元数据键（#273 同族，
  合成口径显式随产物走）；
- P2-3：inverse_adjoint jax x64 不可用时 dtype 回退经 ``"x64"`` 键外露；
- P2-5：synthesize_bpf_model LM 数值兜底产物显式标 needs_calibration，
  横向矩阵构造失败显式 ok=False（不静默近似）。

铁律：全部为元数据/可见性断言，数值行为零变化。
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from rfauto.core.error_budget import BudgetTrace, budget_report_stacked
from rfauto.core.errors import ConfigError
from rfauto.core.inverse_adjoint import OptimizeConfig, optimize_density
from rfauto.core.mapes import (
    METRIC_METADATA_KEYS,
    Z_ALL_SOURCES,
    MapesModel,
    PixelLayout,
    fake_mesh,
)
from rfauto.core.run_artifact import RunArtifact, RunArtifactStore
from rfauto.core.solve_health import UNKNOWN, solve_health_check
from rfauto.core.synthesis import synthesize_bpf_model
from rfauto.core.wcd import wcd_specs

# ─── P2-1：裸吞异常归类 ───────────────────────────────────────────────────────


class _AlwaysCrashPredict:
    """predict 恒炸：键面探针应兜住并附 pred_probe_error，而非中断编排。"""

    def __call__(self, params: dict) -> dict:
        raise RuntimeError("predict surface exploded")


def test_wcd_specs_pred_probe_error_surfaces_on_predict_crash():
    """P2-1（wcd.py）：predict(名义点) 探针炸 → per_spec 如实报缺键 + 顶层
    pred_probe_error 附异常归类，控制流与探针成功路径零差异。"""
    out = wcd_specs(
        center={"w_mm": 1.0},
        sigmas={"w_mm": 0.1},
        predict=_AlwaysCrashPredict(),
        objectives=[{"metric": "gain_db", "op": "max_below", "value": 3.0}],
    )
    assert out["ok"] is False
    assert "pred_probe_error" in out
    assert "RuntimeError" in out["pred_probe_error"]
    # 键面探针炸 ⇒ 各规范如实报"缺该指标键"（不硬算）
    assert all("缺该指标键" in str(v.get("note")) for v in out["per_spec"].values())


def test_wcd_specs_no_probe_error_key_on_healthy_predict():
    """探针正常时结果不含 pred_probe_error（失败路径专属键，零常态足迹）。"""
    out = wcd_specs(
        center={"w_mm": 1.0},
        sigmas={"w_mm": 0.1},
        predict=lambda params: {"gain_db": 2.0},
        objectives=[{"metric": "gain_db", "op": "max_below", "value": 3.0}],
    )
    assert "pred_probe_error" not in out


class _BadNetwork:
    """duck-type network：属性访问即炸（模拟损坏的 skrf 对象替身）。"""

    @property
    def s(self):
        raise ValueError("corrupt network array")

    @property
    def frequency(self):
        raise ValueError("corrupt network array")


def test_solve_health_network_extract_error_surfaces():
    """P2-1（solve_health.py）：network 提取炸 → S 类因子 UNKNOWN + 顶层
    network_extract_error 附根因，不炸整个体检。"""
    report = solve_health_check(network=_BadNetwork())
    assert "network_extract_error" in report
    assert "ValueError" in report["network_extract_error"]
    assert UNKNOWN in {f["status"] for f in report["factors"]}


def test_solve_health_no_extract_error_key_without_network():
    """未给 network 时报告不含 network_extract_error（零常态足迹）。"""
    report = solve_health_check(freq_hz=np.array([1e9, 2e9]),
                                s_matrix=np.zeros((2, 2, 2), dtype=complex))
    assert "network_extract_error" not in report


def test_budget_report_stacked_returns_false_on_unwritable_path(tmp_path):
    """P2-1（error_budget.py）：画图/写盘失败 → False + as exc 归类保留，
    不抛异常不阻塞主路径（#105 best-effort 语义不变）。"""
    trace = BudgetTrace(
        f=np.array([1e9, 2e9]),
        contributions={"a": np.array([1.0, 0.5])},
        modes={"a": "quadratic"},
        total=np.array([1.0, 0.5]),
    )
    bad_dir = tmp_path / "no_such_dir"
    assert budget_report_stacked(trace, bad_dir / "x.png") is False


def test_run_artifact_store_skips_corrupt_artifact(tmp_path):
    """P2-1（run_artifact.py）：损坏 artifact json 在 fidelity 过滤清点中被
    跳过（as exc 归类），合法条目照常返回，不炸整个清点。"""
    store = RunArtifactStore(str(tmp_path))
    store.save(RunArtifact(run_id="good_run", recipe_hash="h", mapping_hash="m",
                           fidelity="hfss"))
    (tmp_path / "corrupt_run.json").write_text("{not valid json", encoding="utf-8")
    runs = store.list_runs(fidelity="hfss")
    assert runs == ["good_run"]
    # 无过滤清点不受坏文件影响（走的是另一分支，两分支都应存活）
    assert sorted(store.list_runs()) == ["corrupt_run", "good_run"]


# ─── P2-3：jax dtype 回退可见性 ───────────────────────────────────────────────


def test_enable_x64_fallback_when_jax_config_frozen(monkeypatch):
    """P2-3：jax 可导入但 config 冻结（update 抛错）→ 回退 False 且入缓存。"""
    import rfauto.core.inverse_adjoint as ia

    monkeypatch.setattr(ia, "_X64_CACHE", {})
    fake_jax = types.ModuleType("jax")
    fake_jax.config = types.SimpleNamespace(
        update=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("config frozen")),
        x64_enabled=False)
    monkeypatch.setitem(sys.modules, "jax", fake_jax)
    assert ia._enable_x64() is False
    assert ia._X64_CACHE["x64"] is False


def test_enable_x64_fallback_when_jax_missing(monkeypatch):
    """P2-3：jax 完全缺失（import ImportError）→ 同样回退 False。"""
    import rfauto.core.inverse_adjoint as ia

    monkeypatch.setattr(ia, "_X64_CACHE", {})
    monkeypatch.setitem(sys.modules, "jax", None)  # import jax → ImportError
    assert ia._enable_x64() is False
    assert ia._X64_CACHE["x64"] is False


def test_optimize_density_reports_x64_marker():
    """P2-3：optimize_density 输出附 x64 键（False = float32 回退，即
    审查建议的 dtype_fallback 语义；本机 jax 正常时应为 True）。"""
    pytest.importorskip("jax", reason="jax 为可选依赖（extra: jax）")
    result = optimize_density(optimize_cfg=OptimizeConfig(iterations=1))
    assert isinstance(result["x64"], bool)
    # simulate / gradient_check 此前已外露同键（回归钉防退化）
    from rfauto.core.inverse_adjoint import simulate

    diag = simulate(np.full(80, 0.5))
    assert isinstance(diag["x64"], bool)


# ─── P2-2：mapes stage / z_all_source 标记 ────────────────────────────────────


def _mapes_model(**kwargs) -> MapesModel:
    layout = PixelLayout(n_rows=2, n_cols=2, n_io_ports=2)
    mesh = fake_mesh(layout.n_ports)
    freqs = np.array([1.0e9, 2.0e9])
    z_stack = np.stack([mesh.z_all(float(f)) for f in freqs])
    return MapesModel(layout, z_stack, freqs, **kwargs)


def test_mapes_predict_carries_stage_and_z_all_source():
    """P2-2：predict 输出附 stage/z_all_source 元数据键（缺省合成口径），
    数值指标仍全为 float。"""
    model = _mapes_model()
    metrics = model.predict(model.layout.flatten(np.ones((2, 2), dtype=bool)))
    assert set(METRIC_METADATA_KEYS) <= set(metrics)
    assert metrics["stage"] == "synthetic"
    assert metrics["z_all_source"] == "synthetic"
    for key, val in metrics.items():
        if key in METRIC_METADATA_KEYS:
            assert isinstance(val, str)
        else:
            assert isinstance(val, float)


def test_mapes_z_all_source_extracted_passthrough():
    """P2-2：构造 kwarg z_all_source="extracted"（stage-2+ 真机提取）随
    predict 产物外露；stage 仍标合成闭式口径。"""
    model = _mapes_model(z_all_source="extracted")
    metrics = model.predict(model.layout.flatten(np.zeros((2, 2), dtype=bool)))
    assert metrics["z_all_source"] == "extracted"
    assert metrics["stage"] == "synthetic"


def test_mapes_z_all_source_invalid_rejected():
    """P2-2：z_all_source 非法取值显式报错（防自由文本漂移）。"""
    with pytest.raises(ConfigError, match="z_all_source"):
        _mapes_model(z_all_source="bogus")
    assert Z_ALL_SOURCES == ("synthetic", "extracted")


# ─── P2-5：synthesis 数值兜底可见性 ───────────────────────────────────────────


def test_bpf_default_closed_form_not_marked_needs_calibration():
    """P2-5：纯闭式路径 needs_calibration 恒 False（零常态足迹）。"""
    out = synthesize_bpf_model(order=3, f0_ghz=2.4, fbw=0.1, rl_db=20.0)
    assert out["ok"] is True
    assert out["method"] == "cameron_residue"
    assert out["needs_calibration"] is False


def test_bpf_lm_polish_marks_needs_calibration(monkeypatch):
    """P2-5：闭式残差超限走 LM 精化 → method=+lm 且产物显式标
    needs_calibration=True（零数值变化；数值响应门 <1e-5 照常生效）。"""
    import rfauto.core.calculators as calculators

    monkeypatch.setattr(calculators, "_cm_poly_max_err",
                        lambda mt, proto: 5.0e-3)  # 强制触发兜底精化路径
    out = synthesize_bpf_model(order=13, f0_ghz=2.4, fbw=0.1, rl_db=22.0)
    assert out["ok"] is True
    assert out["method"] == "cameron_residue+lm"
    assert out["needs_calibration"] is True
    assert out["response_max_err"] < 1e-5


def test_bpf_transversal_failure_is_explicit_not_silent(monkeypatch):
    """P2-5：横向矩阵构造彻底失败 → 显式 ok=False + 异常归类进 errors
    （审查核实：1343 except 分支本就非静默近似，回归钉防退化）。"""
    import rfauto.core.calculators as calculators

    def _boom(order, proto):
        raise RuntimeError("transversal blew up")

    monkeypatch.setattr(calculators, "_cm_transversal_exact", _boom)
    out = synthesize_bpf_model(order=5, f0_ghz=2.4, fbw=0.1, rl_db=20.0)
    assert out["ok"] is False
    # errors 携带兜底分支的异常归类（f"{exc}" 用 str 形态）
    assert any("横向矩阵构造失败" in str(e) and "transversal blew up" in str(e)
               for e in out["errors"])
