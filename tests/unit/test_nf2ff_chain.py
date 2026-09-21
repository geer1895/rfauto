"""nf2ff/SAR 提取链端到端单测（WP4.1 / D4）。

确定性、无网络、无真机（真跑证据独立于测试，见 runs/ 冒烟产物）：
- 模板注入：far_field/sar 渲染块存在性、disable_dumps 口径、域内盒；
- 求解器：farfield/sar 产物解析 + get_nf2ff/get_sar（JSON 进出）；
- 能力位：supports_nf2ff/supports_sar=True 与实现方法一致（不虚报）；
- 服务层：farfield_runs/farfield_view（tmp runs 目录隔离，#144）；
- UI 路由：/api/farfield[/run_id] 薄壳契约。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ─── 模板注入 ────────────────────────────────────────────────────────────────

class TestTemplateInjection:
    def test_dipole_far_field_block(self):
        from rfauto.adapters.openems_templates import render_script

        t = render_script("dipole", {"dipole_len_mm": 58.0}, (2.25, 2.75),
                          far_field=True)
        # 官方口径：CreateNF2FFBox + 域缩 4×网格 + Run 不再 disable_dumps
        assert "CreateNF2FFBox('nf2ff'" in t
        assert "_FF_MARGIN = 4 * BASE" in t
        assert "FDTD.Run(SIM_PATH, verbose=0, cleanup=True)" in t
        assert "CalcNF2FF(SIM_PATH" in t
        # f_res=|S11| 谷（官方 find(s11==min(s11)) 口径）+ 效率 η=Prad/P_acc
        assert "np.argmin(np.abs(S11))" in t
        assert "_Prad / _p_acc" in t
        # 产物契约：三个文件齐全
        for name in ("farfield_cut.csv", "farfield3d.csv", "farfield_meta.json"):
            assert name in t, name
        compile(t, "dipole_ff.py", "exec")

    def test_patch_far_field_box_excludes_pec_bottom(self):
        from rfauto.adapters.openems_templates import render_script

        t = render_script("patch", {"patch_len_mm": 34.9}, (2.0, 3.0),
                          far_field=True)
        # z 底=PEC 边界：盒 z 从 0 起（包住贴片+探针），directions/mirror 交
        # 由 CreateNF2FFBox 依 BC 自动派生（绑定源码：PEC → 面排除+PEC 镜像）
        assert "_FF_START = np.array([-DOM_X + _FF_MARGIN, -DOM_Y + _FF_MARGIN, 0.0])" in t
        assert "H_SUB + AIR_TOP - _FF_MARGIN" in t
        assert "_FF = FDTD.CreateNF2FFBox('nf2ff', _FF_START, _FF_STOP)" in t
        compile(t, "patch_ff.py", "exec")

    def test_far_field_off_keeps_legacy_baseline(self):
        from rfauto.adapters.openems_templates import render_script

        t = render_script("dipole", {}, (2.25, 2.75))
        assert "CreateNF2FFBox" not in t
        assert "FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)" in t

    def test_sar_injection_official_recipe(self):
        from rfauto.adapters.openems_templates import render_script

        t = render_script("dipole", {}, (2.25, 2.75), far_field=True, sar=True)
        # 官方 Dipole SAR：皮肤层文献值 + CellConstantMaterial + DumpType 29
        assert 'epsilon=50.0, kappa=0.65' in t and "density=1100.0" in t
        assert "CellConstantMaterial=1" in t
        assert "dump_type=29" in t
        assert "SAR_Calculation(mass=1.0, method='IEEE_62704')" in t
        assert "sar.csv" in t
        compile(t, "dipole_sar.py", "exec")

    def test_sar_requires_dipole_and_radiator_only_far_field(self):
        from rfauto.adapters.openems_templates import render_script

        with pytest.raises(ValueError, match="辐射模板"):
            render_script("mline", {}, (2.0, 3.0), far_field=True)
        with pytest.raises(ValueError, match="仅支持 dipole"):
            render_script("patch", {}, (2.0, 3.0), sar=True)


# ─── 求解器产物解析 ──────────────────────────────────────────────────────────

def _write_synthetic_artifacts(workdir: Path, with_sar: bool = True) -> None:
    """合成一套远场产物（fdtd/ 层级与真跑一致）。"""
    fdtd = workdir / "fdtd"
    fdtd.mkdir(parents=True, exist_ok=True)
    theta = np.arange(-180.0, 181.0, 1.0)
    rows = []
    for phi in (0.0, 90.0):
        for th in theta:
            e = abs(float(np.cos(np.pi / 2 * np.cos(np.deg2rad(th)))
                          / np.sin(np.deg2rad(th) + 1e-9)))
            rows.append({"phi_deg": phi, "theta_deg": float(th),
                         "re_e_theta": e, "im_e_theta": 0.0,
                         "re_e_phi": 0.0, "im_e_phi": 0.0,
                         "e_norm": e, "p_rad": e * e})
    from rfauto.core.farfield import write_farfield_cut_csv

    write_farfield_cut_csv(fdtd / "farfield_cut.csv", rows)
    meta = {
        "ok": True, "template": "dipole", "f_res_ghz": 2.447,
        "prad_w": 1.7e-3, "p_acc_w": 1.8e-3,
        "dmax_linear": 1.62, "dmax_dbi": 2.096,
        "efficiency": 1.7e-3 / 1.8e-3, "gain_max_dbi": 2.039,
        "power_budget_closure": 0.056,
        "nf2ff_box_start_m": [-0.07, -0.07, -0.018],
        "nf2ff_box_stop_m": [0.07, 0.07, 0.018], "radius_m": 1.0,
    }
    (fdtd / "farfield_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if with_sar:
        (fdtd / "sar.csv").write_text(
            "metric,value\nfreq_hz,2.447e9\nmass_g,1.0\np_acc_w,1.8e-3\n"
            "p_abs_w,8.0e-5\nsar_max_w_per_kg,0.42\n"
            "sar_max_w_per_kg_per_1w_acc,233.3\n", encoding="utf-8")
    # S 参数主路（sparams.csv，2 端口格式 5 数据列 + 表头；≥2 数据行保证 2-D）
    with open(fdtd / "sparams.csv", "w", newline="", encoding="utf-8") as fh:
        fh.write("freq_hz,re_S11,im_S11,re_S21,im_S21\n")
        fh.write("2.4e9,-0.3,0.1,0.7,-0.2\n")
        fh.write("2.5e9,-0.4,0.0,0.65,-0.25\n")


class TestSolverParsing:
    def _solver(self, tmp_path: Path):
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
        from rfauto.adapters.openems_solver import OpenEMSSolver

        cfg = EMSolverConfig(solver_type=EMSolverType.OPENEMS,
                             exe_path=str(tmp_path / "openEMS.exe"),
                             working_dir=str(tmp_path / "wd"))
        solver = OpenEMSSolver(cfg)
        # 生产不变式：build_geometry 先建 working_dir；此处直设等价状态
        solver._connected = True
        solver._working_dir = tmp_path / "wd"
        return solver

    def test_parse_output_attaches_farfield_and_sar(self, tmp_path):
        _write_synthetic_artifacts(tmp_path / "wd")
        solver = self._solver(tmp_path)
        result = solver._parse_output()
        assert result.success
        assert result.far_field is not None and result.far_field["ok"] is True
        meta = result.far_field["meta"]
        assert meta["dmax_dbi"] == pytest.approx(2.096, abs=1e-3)
        # 切面指标来自内核：半波型切面 HPBW≈78°
        cuts = result.far_field["cuts"]
        assert [c["phi_deg"] for c in cuts] == [0.0, 90.0]
        assert cuts[0]["hpbw_deg"] == pytest.approx(78.0, abs=3.0)
        # SAR：1g 归一值（原始激励口径，不混入端口预算闭合——真机校准：
        # p_abs 属性是激励总功率归一，与端口逐频谱功率不同尺度）
        sar = result.sar
        assert sar is not None and sar["ok"] is True
        assert sar["values"]["sar_max_w_per_kg_per_1w_acc"] == pytest.approx(233.3)
        assert result.s_params.shape == (2, 2, 2)  # S 参数主路不受影响

    def test_get_nf2ff_get_sar_json_contract(self, tmp_path):
        _write_synthetic_artifacts(tmp_path / "wd")
        solver = self._solver(tmp_path)
        nf = solver.get_nf2ff()
        assert nf["ok"] and nf["meta"]["template"] == "dipole"
        s = solver.get_sar()
        assert s["ok"] and "p_abs_w" in s["values"]

    def test_no_artifacts_returns_honest_none(self, tmp_path):
        (tmp_path / "wd").mkdir()
        solver = self._solver(tmp_path)
        solver._connected = True
        result = solver._parse_output()
        assert result.far_field is None and result.sar is None
        assert solver.get_nf2ff()["ok"] is False
        assert solver.get_sar()["ok"] is False


# ─── 能力位（不虚报）─────────────────────────────────────────────────────────

class TestCapabilities:
    def test_openems_declares_nf2ff_sar_with_methods(self):
        import rfauto.adapters  # noqa: F401  注册副作用
        from rfauto.adapters.em_solver_base import (
            EMSolverType,
            solver_capabilities_for,
        )
        from rfauto.adapters.openems_solver import OpenEMSSolver

        caps = solver_capabilities_for(EMSolverType.OPENEMS)
        assert caps.supports_nf2ff is True
        assert caps.supports_sar is True
        # 声明 vs 实现（CAPABILITY_METHOD_REQUIREMENTS 契约）
        assert callable(getattr(OpenEMSSolver, "get_nf2ff", None))
        assert callable(getattr(OpenEMSSolver, "get_sar", None))

    def test_others_still_honest(self):
        import rfauto.adapters  # noqa: F401
        from rfauto.adapters.em_solver_base import solver_capabilities_for

        assert solver_capabilities_for("comsol").supports_nf2ff is False
        assert solver_capabilities_for("palace").supports_nf2ff is False
        assert solver_capabilities_for("palace").supports_sar is False


# ─── 服务层 + UI 路由 ────────────────────────────────────────────────────────

@pytest.fixture()
def _ff_run(tmp_path, monkeypatch):
    from rfauto.service import nf2ff_service

    monkeypatch.chdir(tmp_path)
    _write_synthetic_artifacts(tmp_path / "runs" / "20260913_000000_ffdemo")
    monkeypatch.setattr(nf2ff_service, "RUNS_DIR", tmp_path / "runs")
    return "20260913_000000_ffdemo"


class TestServiceAndView:
    def test_farfield_runs_lists_artifact_runs(self, _ff_run):
        from rfauto.service.nf2ff_service import farfield_runs

        out = farfield_runs()
        assert out["ok"] and len(out["runs"]) == 1
        assert out["runs"][0]["run_id"] == _ff_run
        assert out["runs"][0]["has_sar"] is True

    def test_farfield_view_metrics_and_cuts(self, _ff_run):
        from rfauto.service.nf2ff_service import farfield_view

        v = farfield_view(_ff_run)
        assert v["ok"] is True
        assert v["template"] == "dipole"
        m = v["metrics"]
        assert m["dmax_dbi"] == pytest.approx(2.096, abs=1e-3)
        # SAR 块：1g 归一值直传；吸收占比 = 1 − η（端口+远场口径，
        # 真机冒烟校准：η 76.8% + 吸收 23.2% 恰闭合 100%）
        assert m["sar"]["sar_max_w_per_kg_per_1w_acc"] == pytest.approx(233.3)
        assert m["sar"]["absorbed_fraction"] == pytest.approx(1 - 1.7e-3 / 1.8e-3)
        assert len(v["cuts"]) == 2
        assert len(v["cuts"][0]["theta_deg"]) == 361

    def test_farfield_view_missing_run(self, tmp_path, monkeypatch):
        from rfauto.service import nf2ff_service

        monkeypatch.setattr(nf2ff_service, "RUNS_DIR", tmp_path)
        v = nf2ff_service.farfield_view("nope")
        assert v["ok"] is False


# ─── PEC 地镜像修正贯通服务层（W2⑥a：patch η=1.24>1 根因）────────────────

def _write_patch_run(run_dir: Path) -> None:
    """合成一套 patch 远场产物（接地镜像件：U=cos²θ 镜像对称、raw η=1.243）。"""
    run_dir.mkdir(parents=True, exist_ok=True)
    theta = np.arange(-180.0, 181.0, 1.0)
    rows = [{"phi_deg": phi, "theta_deg": float(th),
             "re_e_theta": abs(np.cos(np.deg2rad(th))), "im_e_theta": 0.0,
             "re_e_phi": 0.0, "im_e_phi": 0.0,
             "e_norm": abs(np.cos(np.deg2rad(th))),
             "p_rad": np.cos(np.deg2rad(th)) ** 2}
            for phi in (0.0, 90.0) for th in theta]
    from rfauto.core.farfield import write_farfield_cut_csv

    write_farfield_cut_csv(run_dir / "farfield_cut.csv", rows)
    # 3D 图：U=cos²θ 镜像对称 → D_upper=6（7.78 dBi）、D_full=3（4.77 dBi）
    lines = ["theta_deg,phi_deg,e_norm_db"]
    for t in np.arange(0.0, 181.0, 5.0):
        for p in np.arange(0.0, 360.0, 5.0):
            e = abs(np.cos(np.deg2rad(t)))
            lines.append(f"{t},{p},{20 * np.log10(max(e, 1e-300))}")
    (run_dir / "farfield3d.csv").write_text("\n".join(lines) + "\n",
                                            encoding="utf-8")
    meta = {
        "ok": True, "template": "patch", "f_res_ghz": 2.212,
        "prad_w": 1.4047655921302781e-25, "p_acc_w": 1.1301579524440128e-25,
        "dmax_linear": 1.7837598913888713, "dmax_dbi": 2.5133639439947677,
        "efficiency": 1.242981646142838, "gain_max_dbi": 3.4580111029957967,
        "power_budget_closure": 0.2429816461428379,
        "nf2ff_box_start_m": [-0.0823, -0.0823, 0.0],
        "nf2ff_box_stop_m": [0.0823, 0.0823, 0.0228], "radius_m": 1.0,
    }
    (run_dir / "farfield_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")


class TestPecMirrorServiceView:
    """接地模板（盒底 z=0）→ 指标按镜像因子 2 修正；原值留 raw；3D 图给
    上半球图形自归一方向性交叉值。"""

    def test_metrics_corrected_and_raw_kept(self, tmp_path, monkeypatch):
        from rfauto.service import nf2ff_service

        monkeypatch.chdir(tmp_path)
        _write_patch_run(tmp_path / "runs" / "patch_mirror_demo")
        monkeypatch.setattr(nf2ff_service, "RUNS_DIR", tmp_path / "runs")
        v = nf2ff_service.farfield_view("patch_mirror_demo")
        assert v["ok"] is True
        m = v["metrics"]
        assert m["pec_mirror_factor"] == 2.0
        assert m["efficiency"] == pytest.approx(0.6215, abs=1e-3)
        assert m["dmax_dbi"] == pytest.approx(5.524, abs=1e-2)
        assert m["gain_max_dbi"] == pytest.approx(3.458, abs=1e-3)  # 增益不变量
        assert m["power_budget_closure"] == pytest.approx(0.3785, abs=1e-3)
        assert m["raw"]["efficiency"] == pytest.approx(1.243, abs=1e-3)
        # 图形自归一交叉值：镜像件取上半球 → 7.78 dBi；整球 4.77 dBi
        assert m["dmax_pattern_upper_dbi"] == pytest.approx(10 * np.log10(6.0),
                                                            abs=0.05)
        assert m["dmax_pattern_full_dbi"] == pytest.approx(10 * np.log10(3.0),
                                                           abs=0.05)
        assert m["dmax_pattern_dbi"] == m["dmax_pattern_upper_dbi"]
        # meta 字段保持脚本原样（契约不变；修正只在 metrics）
        assert v["meta"]["efficiency"] == pytest.approx(1.243, abs=1e-3)
        json.dumps(v)

    def test_free_space_run_has_factor_one_and_no_raw(self, _ff_run):
        from rfauto.service.nf2ff_service import farfield_view

        m = farfield_view(_ff_run)["metrics"]
        assert m["pec_mirror_factor"] == 1.0
        assert "raw" not in m
        assert m["dmax_dbi"] == pytest.approx(2.096, abs=1e-3)


# ─── 极坐标页 η 门复用（TODO C21 followUp：farfield_view 复用 patch_eta_gate）─

class TestFarfieldViewEtaGate:
    """farfield_view（极坐标页数据源）复用 ui_service.patch_eta_gate（wf:w1c
    登记的 followUp）：patch 族按修正后 η 判读（raw 1.243 非物理值不进门）、
    非 patch 模板如实 None（#274 作用域分派——全包盒 dipole η≈0.99 不误判
    FAIL）；判读函数与 field_view 的 farfield_metrics["eta_gate"] 同一实现。
    前端极坐标页渲染 η 门（pages.js pageFarfield，与场页同口径）。"""

    def test_patch_run_gate_passes_on_corrected_eta(self, tmp_path, monkeypatch):
        from rfauto.service import nf2ff_service

        monkeypatch.chdir(tmp_path)
        _write_patch_run(tmp_path / "runs" / "eta_gate_patch")
        monkeypatch.setattr(nf2ff_service, "RUNS_DIR", tmp_path / "runs")
        v = nf2ff_service.farfield_view("eta_gate_patch")
        assert v["ok"] is True
        gate = v["metrics"]["eta_gate"]
        assert gate["gate"] == [0.55, 0.79]
        assert gate["value"] == pytest.approx(0.6215, abs=1e-3)  # 修正后 η（非 raw 1.243）
        assert gate["ok"] is True
        json.dumps(v)  # 服务层 JSON 进出契约：门结构可序列化

    def test_patch_run_gate_fails_below_band(self, tmp_path, monkeypatch):
        from rfauto.service import nf2ff_service

        monkeypatch.chdir(tmp_path)
        run_dir = tmp_path / "runs" / "eta_gate_low"
        _write_patch_run(run_dir)
        meta = json.loads(
            (run_dir / "farfield_meta.json").read_text(encoding="utf-8"))
        # 修正后 η = (prad/k)/p_acc（correct_pec_mirror 数值链）——改 prad_w
        # 使修正后 η=0.45 < 下沿 0.55（efficiency 字段仅展示口径，同步改）。
        meta["prad_w"] = 0.9 * meta["p_acc_w"]
        meta["efficiency"] = 0.9
        (run_dir / "farfield_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(nf2ff_service, "RUNS_DIR", tmp_path / "runs")
        gate = nf2ff_service.farfield_view("eta_gate_low")["metrics"]["eta_gate"]
        assert gate["ok"] is False
        assert "低于下沿" in gate["reason"]

    def test_non_patch_template_gate_is_none(self, _ff_run):
        from rfauto.service.nf2ff_service import farfield_view

        m = farfield_view(_ff_run)["metrics"]
        # dipole η≈0.944 落在窗内也不判——门只适用 patch 族（#274 作用域分派）
        assert 0.0 < m["efficiency"] < 1.0
        assert m["eta_gate"] is None

    def test_frontend_farfield_page_renders_eta_gate(self):
        pages = (SRC / "rfauto" / "ui" / "static" / "pages.js").read_text(
            encoding="utf-8")
        m = re.search(r"async function pageFarfield.*?(?=\n(?:/\*|async function ))",
                      pages, re.S)
        assert m is not None
        assert "m.eta_gate" in m.group(0)


class TestUiRoutes:
    def test_farfield_routes_thin_shells(self, _ff_run):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        client = TestClient(create_ui_app())
        listing = client.get("/api/farfield").json()
        assert listing["ok"] and listing["runs"][0]["run_id"] == _ff_run
        view = client.get(f"/api/farfield/{_ff_run}").json()
        assert view["ok"] and view["metrics"]["sar"]["mass_g"] == 1.0
