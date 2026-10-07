"""fd_oe_campaign G2 portless 判据改道·离线回归钉（T42+v2 升格，零引擎/零网络/零真机）。

钉面（#122/#314/#350；预声明=runs/ms_array_nxn_rerun/salvage/criteria_salvage.md
§三/§六）：
① 双路径钉·ported：无端口改道只对 PORTLESS_TEMPLATES 生效——普通模板无
   S 参数产物仍走原语义 PARTIAL「G2: 无 S 参数产物（数值面证据缺）」，
   verdict 无 g2_portless_salvage 键（T40 归因面零变化）；
② 双路径钉·portless：PORTLESS_TEMPLATES 无 sparams 时改道 nf2ff dump 面
   证据（S1 覆盖 ≥90% + S2 链已执行 + S3a 方向图完整 + S3b-v2 前向通量）
   → PASS 带 g2_portless_salvage 块（criteria_version=v2_forward_flux +
   farfield_v2 块记录 P_up/Dmax_v2）；G3 如实不判（g3_finite=None，#314）；
③ S1 覆盖不足 → PARTIAL（不凑 PASS 不判废）；证据缺 → PARTIAL+不可判
   （#314 缺证据不判）；portless 永不产 FAIL；
④ S3b 旧判据 Prad≥0 **已移除**（T47 结论 1：portless 闭盒 Prad≡0 恒等式
   结构性永假）——v2 前向通量门：P_up 有限>0 且 Dmax_v2∈[0,40]dBi → True；
   Dmax_v2 越界 → False→PARTIAL；P_up≤0/证据缺/Dmax 缺 → None（恒等式零
   族如实 UNKNOWN 不凑 PASS）；Dmax 引擎归档非物理=登记缺陷不消费；
⑤ array_meta 陈旧（mtime 早于 nf2ff h5）=链未执行证据（T40：重跑杀于
   FDTD 循环时 array_meta 是前轮残留）→ S2 如实不可判；
⑥ 渲染脚本远场计划解析（纯文本零副作用：函数调用行不 eval）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import h5py
import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

MODULE_NAME = "fd_oe_campaign_salvage_test_target"
TEMPLATE = "fake_t"
NOMINAL = {"a_mm": 1.0, "b_mm": 2.0}

NRTS_DECLARED = 303110
STEP_COVERED = 273792      # 0.9033 ≥ 0.90（T40 rerun 实测口径）
STEP_SHORT = 150000        # 0.495 < 0.90


def _load_driver():
    spec = importlib.util.spec_from_file_location(
        MODULE_NAME, SCRIPTS / "fd_oe_campaign.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def driver():
    return _load_driver()


def _fake_render_ok(template, params, band, mesh_resolution_mm=0.0):
    lines = [f"# {template} auto"]
    for k in sorted(params):
        lines.append(f"{k} = {params[k]!r}")
    return "\n".join(lines)


def _make_env(monkeypatch, tmp_path, *, portless=False):
    """patch 驱动 main() 惰性 import 的 rfauto 面 + chdir tmp。

    solver 回 success=True + s_params=None（G2 无 S 产物路径）；portless=True
    时把 monkeypatch 的 PORTLESS_TEMPLATES 钉到 fake_t（驱动惰性 import 读
    到 patch 值）。
    """
    monkeypatch.chdir(tmp_path)
    meta = {TEMPLATE: {"f0_ghz": 5.8, "mesh_resolution_mm": 0.4}}
    nominal = {TEMPLATE: dict(NOMINAL)}

    class _FakeSolver:
        def __init__(self, cfg):
            pass

        def connect(self):
            return True

        def build_geometry(self, spec):
            return True

        def solve(self):
            return types.SimpleNamespace(success=True, s_params=None)

    import rfauto.adapters.openems_templates as ot

    monkeypatch.setattr(ot, "TEMPLATE_META", meta)
    monkeypatch.setattr(ot, "TEMPLATE_NOMINAL", nominal)
    monkeypatch.setattr(
        ot, "PORTLESS_TEMPLATES", (TEMPLATE,) if portless else ("ms_array_NxN",))
    monkeypatch.setattr(ot, "render_script", _fake_render_ok)
    monkeypatch.setattr("rfauto.adapters.openems_solver.OpenEMSSolver", _FakeSolver)
    monkeypatch.setattr("rfauto.adapters.em_solver_base.EMSolverConfig",
                        lambda **kw: types.SimpleNamespace(**kw))
    monkeypatch.setattr("rfauto.adapters.em_solver_base.resolve_openems_exe",
                        lambda: "unused")
    monkeypatch.setattr("rfauto.service.health_service.health_check_run",
                        lambda name, runs_dir=None: {"verdict": "skip", "ok": True})
    monkeypatch.setattr(sys, "argv", ["fd_oe_campaign.py", "--only", TEMPLATE])


def _read_verdict(tmp_path: Path) -> dict:
    v = tmp_path / "runs" / "ge_fd" / TEMPLATE / "verdict.json"
    assert v.exists(), "verdict.json 未落盘"
    return json.loads(v.read_text(encoding="utf-8"))


def _write_dump_h5(path: Path, last_step: int) -> None:
    """合成 nf2ff dump h5 最小面：FieldData/TD 快照键（首/中/末）+Mesh。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as fh:
        td = fh.create_group("FieldData/TD")
        for step in (0, last_step // 2, last_step):
            ds = td.create_dataset(f"{step:08d}", data=np.zeros(
                (3, 1, 4, 2), dtype=np.float32))
            ds.attrs["d_order"] = "NXYZ"
        mesh = fh.create_group("Mesh")
        mesh.create_dataset("x", data=np.array([-0.0284, 0.0284]))
        mesh.create_dataset("y", data=np.linspace(-0.0284, 0.0284, 8))
        mesh.create_dataset("z", data=np.linspace(0.0031, 0.0074, 5))


def _write_dump_h5_face(path: Path, axis: str, const: float) -> None:
    """合成面文件（Mesh 单轴常量=面坐标，对拍用）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as fh:
        fh.create_group("FieldData/TD").create_dataset(
            "00000000", data=np.zeros((3, 1, 4, 2), dtype=np.float32))
        mesh = fh.create_group("Mesh")
        span_xy = np.linspace(-0.0284, 0.0284, 8)
        span_z = np.linspace(0.0031, 0.0074, 5)
        cols = {"x": [const] if axis == "x" else span_xy,
                "y": [const] if axis == "y" else span_xy,
                "z": [const] if axis == "z" else span_z}
        for a in ("x", "y", "z"):
            mesh.create_dataset(a, data=np.asarray(cols[a]))


def _write_result_h5(path: Path, dmax: float, prad: float,
                     n_theta: int = 181, n_phi: int = 2, nan: bool = False) -> None:
    """合成 CalcNF2FF 结果 h5（nf2ff_results 同构最小面）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as fh:
        mesh = fh.create_group("Mesh")
        mesh.create_dataset("theta", data=np.linspace(-90.0, 90.0, n_theta))
        mesh.create_dataset("phi", data=np.linspace(0.0, 90.0, n_phi))
        mesh.create_dataset("r", data=np.array([1.0]))
        data = fh.create_group("nf2ff")
        data.attrs["Frequency"] = np.array([1e10])
        data.attrs["Dmax"] = np.array([dmax])
        data.attrs["Prad"] = np.array([prad])
        val = 0.3 + 0.1j
        if nan:
            val = np.nan + 0j
        for comp in ("E_theta", "E_phi"):
            g = data.create_group(f"{comp}/FD")
            raw = np.full((n_phi, n_theta), val.real, dtype=np.float64)
            gim = np.full((n_phi, n_theta), val.imag, dtype=np.float64)
            g.create_dataset("f0_real", data=raw)
            g.create_dataset("f0_imag", data=gim)


def _write_v2_evidence(run_dir: Path, **overrides) -> dict:
    """写 run 目录约定名 farfield_v2.json（归一化 v2 证据，schema 同
    criteria_salvage.md §六.2）；合成值独立于 T47 实测（只测判读逻辑）。"""
    ev: dict = {"farfield_semantics": "v2_forward_flux",
                "p_up_w": 1.2e-09, "p_dn_w": 1.8e-09,
                "p_up_over_pdn": 2.0 / 3.0,
                "dmax_v2_linear": 35.48, "dmax_v2_dbi": 15.5,
                "theta_peak_deg": 0.0,
                "pad_convergence_rel": 0.0025,
                "hemisphere_closure_rel": 1.8e-16,
                "late_over_full_rel": 9.2e-11}
    ev.update(overrides)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "farfield_v2.json").write_text(json.dumps(ev), encoding="utf-8")
    return ev


def _make_portless_run_dir(run_dir: Path, *, last_step: int = STEP_COVERED,
                           dmax: float = -174.35, prad: float = 1e-12,
                           fresh: bool = True, result: bool = True,
                           nan: bool = False, v2: bool = True) -> None:
    """合成 portless run 目录（dump h5+nrts_meta+array_meta+结果 h5+v2 证据）。"""
    fdtd = run_dir / "fdtd"
    _write_dump_h5(fdtd / "nf2ff_E_0.h5", last_step)
    (run_dir / "nrts_meta.json").write_text(
        json.dumps({"nrts_declared": NRTS_DECLARED}), encoding="utf-8")
    (run_dir / "array_meta.json").write_text(
        json.dumps({"ok": True, "dmax_linear": dmax}), encoding="utf-8")
    h5_mtime = 1000000.0
    meta_mtime = h5_mtime + 60.0 if fresh else h5_mtime - 60.0
    os.utime(fdtd / "nf2ff_E_0.h5", (h5_mtime, h5_mtime))
    os.utime(run_dir / "array_meta.json", (meta_mtime, meta_mtime))
    if result:
        _write_result_h5(fdtd / "nf2ff.h5", dmax, prad, nan=nan)
        os.utime(fdtd / "nf2ff.h5", (meta_mtime, meta_mtime))
    if v2:
        _write_v2_evidence(run_dir)


# ── ①② 双路径钉（驱动 main() 级）──────────────────────────────────────

def test_ported_template_no_sparams_unchanged(driver, monkeypatch, tmp_path):
    """钉①：ported 模板无 S 产物仍 PARTIAL 原语义，无 salvage 块（零变化）。"""
    _make_env(monkeypatch, tmp_path, portless=False)
    run_dir = tmp_path / "runs" / "ge_fd" / TEMPLATE
    (run_dir / "fdtd").mkdir(parents=True)
    (run_dir / "fdtd" / "et").write_text("0 0\n1e-9 0.0\n", encoding="utf-8")
    # H1-5：ported 模板无 S 产物=PARTIAL 座 → rc 4（判读语义零变化钉保留）。
    assert driver.main() == 4
    verdict = _read_verdict(tmp_path)
    assert verdict["status"] == "PARTIAL"
    assert verdict["reason"] == "G2: 无 S 参数产物（数值面证据缺）"
    assert "g2_portless_salvage" not in verdict


def test_portless_template_salvage_pass(driver, monkeypatch, tmp_path):
    """钉②：portless 无 S 产物 → 改道 dump 面证据（v2 前向通量）PASS +
    salvage 块（criteria_version=v2_forward_flux + farfield_v2 记录
    P_up/Dmax_v2）+ G3 如实不判（None）+ Dmax 缺陷登记不消费。"""
    _make_env(monkeypatch, tmp_path, portless=True)
    _make_portless_run_dir(tmp_path / "runs" / "ge_fd" / TEMPLATE)
    assert driver.main() == 0
    verdict = _read_verdict(tmp_path)
    assert verdict["status"] == "PASS"
    assert verdict["g3_finite"] is None and verdict["g3_passive_le_1p05"] is None
    salv = verdict["g2_portless_salvage"]
    assert salv["status"] == "PASS" and salv["g2_pass"] is True
    assert salv["criteria_version"] == "v2_forward_flux"
    assert salv["checks"] == {"s1_record_completeness": True,
                              "s2_chain_executed": True,
                              "s3a_pattern_complete": True,
                              "s3b_v2_forward_flux": True,
                              "s3c_empty_field_fuse": True}
    # S3b 旧判据键已移除（T47 结论 1 恒等式零结构性永假）
    assert "s3b_prad_nonneg" not in salv["checks"]
    cov = salv["coverage"]
    assert cov["td_last_step"] == STEP_COVERED
    assert cov["nrts_declared"] == NRTS_DECLARED
    assert cov["coverage"] == pytest.approx(STEP_COVERED / NRTS_DECLARED)
    # v2 块：run 目录 farfield_v2.json 内联自动加载 + P_up/Dmax_v2 记录
    v2h = salv["farfield_v2"]
    assert v2h["v2_available"] is True and v2h["s3b_v2"] is True
    assert v2h["p_up_w"] == pytest.approx(1.2e-09)
    assert v2h["dmax_v2_dbi"] == pytest.approx(15.5)
    assert v2h["dmax_v2_range_dbi"] == [0.0, 40.0]
    assert "v2 物理值合理" in salv["reason"]
    # Dmax 非物理（引擎归档）：登记在 farfield 块、reason 有标记，不阻断 PASS
    assert salv["farfield"]["dmax_defect_registered"] is True
    assert salv["farfield"]["dmax_linear"] == pytest.approx(-174.35)
    assert "Dmax 非物理" in salv["reason"]
    # nrts 门对无日志 run 如实不可判、不降级
    assert verdict["nrts_converged"]["ok"] is None


# ── ③④ 判读映射（gate 级纯函数）──────────────────────────────────────

def test_portless_coverage_below_threshold_partial(driver, monkeypatch, tmp_path):
    """钉③：S1 覆盖 <90% → PARTIAL（不凑 PASS 不判废；v2 过也救不回 S1）。"""
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "runs" / "ge_fd" / TEMPLATE
    _make_portless_run_dir(run_dir, last_step=STEP_SHORT)
    salv = driver.portless_g2_gate(run_dir, farfield_evidence={
        "chain_executed": True, "pattern_complete": True,
        "dmax_defect_registered": False, "source": "salvage"})
    assert salv["status"] == "PARTIAL" and salv["g2_pass"] is False
    assert salv["checks"]["s1_record_completeness"] is False
    assert salv["checks"]["s3b_v2_forward_flux"] is True   # v2 过不救 S1
    assert "s1_record_completeness" in salv["reason"]


def test_portless_evidence_missing_partial_not_fail(driver, tmp_path):
    """钉③：无 h5/无 nrts_meta/无 v2 证据 → 不可判 PARTIAL（#314 缺证据不判）。"""
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    salv = driver.portless_g2_gate(run_dir, farfield_evidence={
        "chain_executed": True, "pattern_complete": True,
        "dmax_defect_registered": False, "source": "salvage"})
    assert salv["status"] == "PARTIAL"
    assert salv["checks"]["s1_record_completeness"] is None
    assert salv["checks"]["s3b_v2_forward_flux"] is None
    assert salv["farfield_v2"]["v2_available"] is False
    assert "不可判" in salv["reason"]


def test_v2_identity_zero_unknown_not_pass(driver, tmp_path):
    """钉④·诚实钉：恒等式零场景 → s3b_v2 如实 UNKNOWN（None）不凑 PASS
    （T47 结论 1：v2 门要求 P_up>0，退化输入=P_up≤0 → 不可判 PARTIAL，
    也不判 FAIL——portless 永不 FAIL）。"""
    for p_up in (0.0, -1.4489e-24):   # 恒等式零代表值（引擎归档 Prad 同族）
        run_dir = tmp_path / f"run_{p_up!r}"
        _make_portless_run_dir(run_dir)
        salv = driver.portless_g2_gate(
            run_dir, v2_evidence={"p_up_w": p_up, "dmax_v2_dbi": 15.5})
        assert salv["status"] == "PARTIAL" and salv["g2_pass"] is False
        assert salv["checks"]["s3b_v2_forward_flux"] is None
        assert salv["farfield_v2"]["p_up_ok"] is False
        assert "恒等式零" in salv["farfield_v2"]["detail"]
        assert "不可判" in salv["reason"]


def test_v2_dmax_out_of_band_false_partial(driver, tmp_path):
    """钉④：P_up 合理但 Dmax_v2 越预声明带 [0,40]dBi → s3b_v2=False →
    PARTIAL（未过，物理不合理如实判）。"""
    run_dir = tmp_path / "run"
    _make_portless_run_dir(run_dir)
    salv = driver.portless_g2_gate(
        run_dir, v2_evidence={"p_up_w": 1.2e-09, "dmax_v2_dbi": 45.0})
    assert salv["status"] == "PARTIAL" and salv["g2_pass"] is False
    assert salv["checks"]["s3b_v2_forward_flux"] is False
    assert salv["farfield_v2"]["p_up_ok"] is True
    assert salv["farfield_v2"]["dmax_v2_ok"] is False
    assert "未过: s3b_v2_forward_flux" in salv["reason"]
    assert "越出预声明带" in salv["farfield_v2"]["detail"]


def test_v2_incomplete_dmax_missing_unknown(driver, tmp_path):
    """钉④：P_up 合理但 dmax_v2_dbi 缺 → 证据不完整 s3b_v2=None → PARTIAL。"""
    run_dir = tmp_path / "run"
    _make_portless_run_dir(run_dir)
    salv = driver.portless_g2_gate(
        run_dir, v2_evidence={"p_up_w": 1.2e-09})
    assert salv["status"] == "PARTIAL"
    assert salv["checks"]["s3b_v2_forward_flux"] is None
    assert salv["farfield_v2"]["p_up_ok"] is True
    assert salv["farfield_v2"]["dmax_v2_ok"] is None
    assert "不完整" in salv["farfield_v2"]["detail"]


def test_v2_quality_sidecars_recorded_not_blocking(driver, tmp_path):
    """钉④：质量旁证量（G1/G2/G4）登记进 farfield_v2.quality 且不阻断
    判定；未知额外键宽容忽略（schema 前向兼容）。"""
    run_dir = tmp_path / "run"
    _make_portless_run_dir(run_dir)
    salv = driver.portless_g2_gate(run_dir, v2_evidence={
        "p_up_w": 1.2e-09, "dmax_v2_dbi": 15.5, "p_dn_w": 1.8e-09,
        "pad_convergence_rel": 0.0025, "hemisphere_closure_rel": 1.8e-16,
        "late_over_full_rel": 9.2e-11, "future_key": 123})
    assert salv["status"] == "PASS"
    q = salv["farfield_v2"]["quality"]
    assert q["pad_convergence_rel"] == pytest.approx(0.0025)
    assert q["hemisphere_closure_rel"] == pytest.approx(1.8e-16)
    assert q["late_over_full_rel"] == pytest.approx(9.2e-11)
    assert q["p_dn_w"] == pytest.approx(1.8e-09)
    assert "future_key" not in q


# ─── 空场熔断（ge6 followUp，7×7 教训 六百九十三） ─────────────────


def test_v2_empty_field_fuse_unknown_not_dmax_pass(driver, tmp_path):
    """空场熔断钉：P_up>0 但低于绝对地板（7×7 实测 2.17e-22W）→ s3b_v2
    UNKNOWN+empty_field=True+Dmax 假值不产（dmax_v2_ok 压 None）——修复前
    P_up=2.17e-22>0 且 Dmax=35.19∈[0,40] 会假 PASS（零/零比值伪象）。"""
    run_dir = tmp_path / "run"
    _make_portless_run_dir(run_dir)
    salv = driver.portless_g2_gate(run_dir, v2_evidence={
        "p_up_w": 2.17e-22, "dmax_v2_dbi": 35.19,   # 7×7 实测两值
        "theta_peak_deg": 25.0})                      # argmax 空场伪象值
    assert salv["status"] == "PARTIAL" and salv["g2_pass"] is False
    assert salv["checks"]["s3b_v2_forward_flux"] is None
    v2h = salv["farfield_v2"]
    assert v2h["empty_field"] is True
    assert v2h["p_up_ok"] is False
    assert v2h["dmax_v2_ok"] is None                  # 熔断不产 Dmax 假值
    assert "空远场熔断" in v2h["detail"]
    assert "argmax" in salv["reason"] and "25°" not in salv["reason"].split("伪象")[0]


def test_v2_p_up_floor_boundary_normal_field_passes(driver, tmp_path):
    """空场熔断边界钉：P_up 恰在地板上（1e-14W）与正常量级（1.2e-9W）→
    不熔断 PASS 语义零变化。"""
    run_dir = tmp_path / "run"
    _make_portless_run_dir(run_dir)
    salv = driver.portless_g2_gate(run_dir, v2_evidence={
        "p_up_w": 1.0e-14, "dmax_v2_dbi": 15.5})      # 地板上边界
    assert salv["farfield_v2"]["empty_field"] is False
    assert salv["checks"]["s3b_v2_forward_flux"] is True
    assert salv["status"] == "PASS"


def test_farfield_health_empty_field_two_states(driver):
    """farfield 健康面空场钉：E_norm 全局 max 低于 −140dB 地板 →
    empty_field=True；正常场（0.5）→ False；不可读 → None。"""
    def _metrics(e_norm_max):
        return {"dmax": 4.9, "prad": 0.8, "n_theta": 181, "n_phi": 2,
                "shape": [181, 2], "finite_all": True,
                "e_norm_max": e_norm_max}

    h_empty = driver.farfield_health(_metrics(6.6e-9))    # 7×7 实测值 −163.7dB
    assert h_empty["empty_field"] is True
    h_ok = driver.farfield_health(_metrics(0.5))
    assert h_ok["empty_field"] is False
    h_none = driver.farfield_health(None)
    assert h_none["empty_field"] is None


def test_gate_s3c_empty_field_fuse_explicit_evidence(driver, tmp_path):
    """空场熔断显式证据钉：farfield 证据带 empty_field=True → s3c 检查键
    未过+reason 落 argmax 空场警示；旧式证据（无该键）不加检查键零漂移。"""
    run_dir = tmp_path / "run"
    _make_portless_run_dir(run_dir)
    base_ev = {"chain_executed": True, "pattern_complete": True,
               "dmax_defect_registered": False, "source": "salvage"}
    salv_fuse = driver.portless_g2_gate(
        run_dir, farfield_evidence={**base_ev, "empty_field": True})
    assert salv_fuse["checks"]["s3c_empty_field_fuse"] is False
    assert "s3c_empty_field_fuse" in salv_fuse["reason"]
    assert "空远场警示" in salv_fuse["reason"] and "argmax" in salv_fuse["reason"]
    assert salv_fuse["status"] == "PARTIAL"
    # 旧式证据 dict（无 empty_field 键）→ 不加 s3c 键（零行为变化）
    salv_legacy = driver.portless_g2_gate(
        run_dir, farfield_evidence=dict(base_ev))
    assert "s3c_empty_field_fuse" not in salv_legacy["checks"]
    assert salv_legacy["status"] == "PASS"


def test_v2_run_dir_file_autoload(driver, tmp_path):
    """钉④：v2_evidence=None 时自 run 目录约定 farfield_v2.json 自动加载
    （内联路径自足判定）。"""
    run_dir = tmp_path / "run"
    _make_portless_run_dir(run_dir)   # v2=True 写约定名文件
    salv = driver.portless_g2_gate(run_dir)
    assert salv["farfield_v2"]["v2_available"] is True
    assert salv["checks"]["s3b_v2_forward_flux"] is True
    assert salv["status"] == "PASS"


def test_dmax_defect_registered_not_consumed(driver, tmp_path):
    """钉④：引擎归档 Dmax 非物理只登记，PASS 判定不含 Dmax（物理值以
    farfield_v2 为准）；健康 Dmax 证据不误标缺陷。"""
    run_dir = tmp_path / "run"
    _make_portless_run_dir(run_dir, dmax=-174.35, prad=1e-9)
    salv_bad = driver.portless_g2_gate(run_dir)
    assert salv_bad["farfield"]["dmax_defect_registered"] is True
    assert "farfield_semantics_defect" in salv_bad["reason"]
    # 换健康 Dmax 证据（其余同面）→ 缺陷标记解除，判定仍只看 S1..S3b-v2
    ev = dict(salv_bad["farfield"])
    ev["dmax_linear"], ev["dmax_dbi"], ev["dmax_defect_registered"] = 5.0, 6.99, False
    salv_ok = driver.portless_g2_gate(run_dir, farfield_evidence=ev)
    assert salv_ok["farfield"]["dmax_defect_registered"] is False
    assert "farfield_semantics_defect" not in salv_ok["reason"]
    assert salv_ok["status"] == "PASS"


def test_stale_array_meta_not_chain_evidence(driver, tmp_path):
    """钉⑤：array_meta 早于 nf2ff h5（前轮残留）→ S2 如实不可判→PARTIAL。"""
    run_dir = tmp_path / "run"
    _make_portless_run_dir(run_dir, fresh=False)
    salv = driver.portless_g2_gate(run_dir)
    assert salv["farfield"]["array_meta_fresh"] is False
    assert salv["checks"]["s2_chain_executed"] is False
    assert salv["status"] == "PARTIAL"
    assert "s2_chain_executed" in salv["reason"]


def test_fresh_run_dir_evidence_pass(driver, tmp_path):
    """钉⑤正向：新鲜 array_meta+结果 h5+v2 证据 → run_dir 内联证据自足 PASS。"""
    run_dir = tmp_path / "run"
    _make_portless_run_dir(run_dir, dmax=4.9, prad=0.8)
    salv = driver.portless_g2_gate(run_dir)
    assert salv["farfield"]["array_meta_fresh"] is True
    assert salv["status"] == "PASS"
    assert salv["farfield"]["dmax_defect_registered"] is False
    assert salv["farfield_v2"]["v2_available"] is True
    assert salv["farfield_v2"]["dmax_v2_dbi"] == pytest.approx(15.5)


# ── ⑥ 渲染脚本远场计划解析（纯文本）──────────────────────────────────

_MS_SNIPPET = '''
#!/usr/env/python3
"""openEMS script (rfauto ms_array_NxN template auto-generated, official-method mesh)."""
import numpy as np
F0 = 10000000000.0
FC = 2000000000.0
H_SUB = 0.001524
TAND = 0.0037
BASE = 0.0004   # 网格 base：λ_sub/50 @F_MAX（官方口径）或显式覆盖
NEAR = 0.0001   # 近场区 = base/_near_ratio
DOM_X = 0.02997921145
DOM_Y = 0.02997921145
Z_EXC = 0.009018811449999999   # 软平面照明面（λ0/4 空气隙上）
CSX = ContinuousStructure()
FDTD = openEMS(NrTS=100000, EndCriteria=1e-06)   # 占位（解析零副作用钉）
FDTD.SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "PEC", "MUR"])
mesh.AddLine("x", _x)
_FF_MARGIN = 4 * BASE
_FF = FDTD.CreateNF2FFBox(
    "nf2ff",
    np.array([-DOM_X + _FF_MARGIN, -DOM_Y + _FF_MARGIN, H_SUB + _FF_MARGIN]),
    np.array([DOM_X - _FF_MARGIN, DOM_Y - _FF_MARGIN, Z_EXC - _FF_MARGIN]))
_f_res = float(F0)
_THETA_CUT = np.arange(-90.0, 91.0, 1.0)
_PHI_CUT = [0.0, 90.0]
'''


def test_parse_nf2ff_plan_ms_array_literals(driver):
    """钉⑥：盒坐标/BC/角网/频率逐字面解析；函数调用行不 eval（零副作用）。"""
    plan = driver.parse_nf2ff_plan(_MS_SNIPPET)
    margin = 4 * 0.0004
    assert plan["box_start"] == pytest.approx(
        [-0.02997921145 + margin, -0.02997921145 + margin, 0.001524 + margin])
    assert plan["box_stop"] == pytest.approx(
        [0.02997921145 - margin, 0.02997921145 - margin, 0.009018811449999999 - margin])
    assert plan["boundary_cond"] == ["MUR", "MUR", "MUR", "MUR", "PEC", "MUR"]
    assert len(plan["theta_deg"]) == 181
    assert plan["phi_deg"] == [0.0, 90.0]
    assert plan["freq_expr"] == pytest.approx(1e10)
    # 零副作用：函数调用行（openEMS/ContinuousStructure）不进常量环境
    assert "FDTD" not in plan["constants"]
    assert "CSX" not in plan["constants"]
    assert plan["constants"]["_FF_MARGIN"] == pytest.approx(margin)
    # 旧形态（CreateNF2FFBox·BC 推导）无 directions/mirror 键（ge7 ffrender
    # 起直构六面形态才携带；旧档案判读路径零漂移的向后兼容钉）
    assert "nf2ff_directions" not in plan
    assert "nf2ff_mirror" not in plan


_MS_SNIPPET_SIX_FACE = '''
#!/usr/env/python3
"""openEMS script (rfauto ms_array_NxN template auto-generated, official-method mesh)."""
import numpy as np
from openEMS.nf2ff import nf2ff as _NF2FF
F0 = 10000000000.0
FC = 2000000000.0
H_SUB = 0.001524
TAND = 0.0037
BASE = 0.0004   # 网格 base：λ_sub/50 @F_MAX（官方口径）或显式覆盖
NEAR = 0.0001   # 近场区 = base/_near_ratio
DOM_X = 0.02997921145
DOM_Y = 0.02997921145
Z_EXC = 0.009018811449999999   # 软平面照明面（λ0/4 空气隙上）
CSX = ContinuousStructure()
FDTD = openEMS(NrTS=100000, EndCriteria=1e-06)   # 占位（解析零副作用钉）
FDTD.SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "PEC", "MUR"])
mesh.AddLine("x", _x)
_FF_MARGIN = 4 * BASE
_FF = _NF2FF(
    CSX, "nf2ff",
    np.array([-DOM_X + _FF_MARGIN, -DOM_Y + _FF_MARGIN, H_SUB + _FF_MARGIN]),
    np.array([DOM_X - _FF_MARGIN, DOM_Y - _FF_MARGIN, Z_EXC - _FF_MARGIN]),
    directions=[True] * 6, mirror=[0] * 6)
_f_res = float(F0)
_THETA_CUT = np.arange(-90.0, 91.0, 1.0)
_PHI_CUT = [0.0, 90.0]
'''


def test_parse_nf2ff_plan_ms_array_six_face_literals(driver):
    """钉⑥-六面（ge7 ffrender）：直构 _NF2FF 形态盒坐标/directions/mirror
    解析；runs/ge6_ffdbg 定案修复后的渲染形态，judge 离线重建消费面。"""
    plan = driver.parse_nf2ff_plan(_MS_SNIPPET_SIX_FACE)
    margin = 4 * 0.0004
    assert plan["box_start"] == pytest.approx(
        [-0.02997921145 + margin, -0.02997921145 + margin, 0.001524 + margin])
    assert plan["box_stop"] == pytest.approx(
        [0.02997921145 - margin, 0.02997921145 - margin, 0.009018811449999999 - margin])
    # K-6 底面剔除（ge8b 批）：directions 底面(z start)=False，五面记录
    # 旧档案（ge7 ffrender 真机 verdict 六面字面）向后兼容钉：解析器仍收全真六面
    assert plan["nf2ff_directions"] == [True] * 6
    assert plan["nf2ff_mirror"] == [0] * 6
    assert plan["boundary_cond"] == ["MUR", "MUR", "MUR", "MUR", "PEC", "MUR"]
    assert len(plan["theta_deg"]) == 181
    assert plan["phi_deg"] == [0.0, 90.0]
    assert plan["freq_expr"] == pytest.approx(1e10)


def test_parse_nf2ff_plan_six_face_end_to_end_render(driver):
    """钉⑥-六面端到端：真渲染器字面 → judge 解析（渲染改动与判读面同源）。"""
    from rfauto.adapters import openems_templates as ot
    text = ot.render_script(
        "ms_array_NxN", dict(ot.TEMPLATE_NOMINAL["ms_array_NxN"]),
        (9.75, 10.25), mesh_resolution_mm=0.4)
    plan = driver.parse_nf2ff_plan(text)
    # K-6 底面剔除（ge8b 批）：真渲染字面=五面（底面 z start=False）
    assert plan["nf2ff_directions"] == [True, True, True, True, False, True]
    assert plan["nf2ff_mirror"] == [0] * 6
    margin = 4 * 0.0004
    h_sub = float(ot.TEMPLATE_NOMINAL["ms_array_NxN"]["h_mm"]) * 1e-3
    assert plan["box_start"][2] == pytest.approx(h_sub + margin)
    assert plan["box_start"][0] == pytest.approx(-plan["constants"]["DOM_X"]
                                                 + margin)
    assert plan["box_stop"][2] == pytest.approx(
        plan["constants"]["Z_EXC"] - margin)


def test_parse_nf2ff_plan_garbage_missing_keys(driver):
    """钉⑥：无关文本解析 → 必需键缺失（如实，不臆造缺省）。"""
    plan = driver.parse_nf2ff_plan("print('hello')\n")
    for key in ("box_start", "box_stop", "boundary_cond", "theta_deg"):
        assert key not in plan


def test_run_portless_salvage_missing_plan_early_return(driver, tmp_path):
    """执行器守卫：计划解析缺 → PARTIAL 早退（不生成子进程/不触 openEMS）。"""
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "simulation.py").write_text("print('no plan')\n", encoding="utf-8")
    out = driver.run_portless_salvage(run_dir, tmp_path / "salvage")
    assert out["status"] == "PARTIAL" and out["g2_pass"] is False
    assert "解析缺" in out["reason"]
    ff = tmp_path / "salvage" / "farfield"
    assert not (ff / "_nf2ff_child.py").exists()
    assert not (ff / "nf2ff_metrics.json").exists()


def test_farfield_health_strict_shape_and_nan(driver):
    """farfield_health：严格角网长度核对 + NaN 判不完整；不可读=None 态；
    S3b 旧判据 prad_nonneg 已移除（T47 恒等式零）——prad 只作 raw 留痕。"""
    def _metrics(n_theta=181, n_phi=2, finite=True, dmax=4.9, prad=0.8):
        return {"dmax": dmax, "prad": prad, "n_theta": n_theta,
                "n_phi": n_phi, "shape": [n_theta, n_phi],
                "finite_all": finite, "e_norm_max": 0.5}

    h = driver.farfield_health(_metrics(), expect_theta=181, expect_phi=2)
    assert h["pattern_complete"] is True
    assert "prad_nonneg" not in h            # 判据已移除（T47 结论 1）
    assert h["prad"] == pytest.approx(0.8)   # raw 留痕仍在
    # prad 为负（引擎恒等式零族）不再产生任何判据性字段，只留痕
    h_neg = driver.farfield_health(_metrics(prad=-1.4489e-24),
                                   expect_theta=181, expect_phi=2)
    assert h_neg["pattern_complete"] is True
    assert h_neg["prad"] == pytest.approx(-1.4489e-24)
    assert "prad_nonneg" not in h_neg
    short = driver.farfield_health(
        _metrics(n_theta=90), expect_theta=181, expect_phi=2)
    assert short["pattern_complete"] is False
    nan = driver.farfield_health(_metrics(finite=False),
                                 expect_theta=181, expect_phi=2)
    assert nan["pattern_complete"] is False
    h_none = driver.farfield_health(None)
    assert h_none["chain_executed"] is None and h_none["readable"] is False
    assert "prad_nonneg" not in h_none


def test_box_crosscheck_against_recorded_mesh(driver, tmp_path):
    """盒对拍：字面量 vs h5 记录坐标（#329 口径）；缺文件=None。"""
    fdtd = tmp_path / "fdtd"
    _write_dump_h5_face(fdtd / "nf2ff_E_0.h5", "x", -0.0284)
    _write_dump_h5_face(fdtd / "nf2ff_E_1.h5", "x", 0.0284)
    _write_dump_h5_face(fdtd / "nf2ff_E_4.h5", "z", 0.0074)
    cc = driver._box_crosscheck(
        fdtd, [-0.0284, -0.0284, 0.0031], [0.0284, 0.0284, 0.0074])
    assert cc is not None
    assert cc["max_delta"] == pytest.approx(0.0, abs=1e-12)
    assert driver._box_crosscheck(tmp_path / "empty", [0, 0, 0], [0, 0, 0]) is None


def test_box_crosscheck_six_face_top_from_e5(driver, tmp_path):
    """六面档案顶面=E_5（ge7 ffrender 面序位移）：E_5 在档时 z_stop 取 E_5。

    直构六面记录下 E_4=底面（z=start_z）、E_5=顶面（z=stop_z）——若误读
    E_4（旧五面口径）则 z_stop=0.0031≠0.0074 → max_delta≠0，本断言即证
    E_5 优先。E_5 缺=旧五面档案 → E_4=顶（上测旧口径向后兼容钉）。
    """
    fdtd = tmp_path / "fdtd"
    _write_dump_h5_face(fdtd / "nf2ff_E_0.h5", "x", -0.0284)
    _write_dump_h5_face(fdtd / "nf2ff_E_1.h5", "x", 0.0284)
    _write_dump_h5_face(fdtd / "nf2ff_E_4.h5", "z", 0.0031)   # 底面（六面档案）
    _write_dump_h5_face(fdtd / "nf2ff_E_5.h5", "z", 0.0074)   # 顶面
    cc = driver._box_crosscheck(
        fdtd, [-0.0284, -0.0284, 0.0031], [0.0284, 0.0284, 0.0074])
    assert cc is not None
    assert cc["max_delta"] == pytest.approx(0.0, abs=1e-12)
    assert cc["recorded_stop"][2] == pytest.approx(0.0074, abs=1e-12)
