"""wf:nrts-fix 四 F-D 模板 NrTS/EndCriteria 接线回归钉（零真机、零网络）。

背景（runs/fd_rerun_20260927/seat2_truncation_verdict 判读）：TEMPLATE_META.
max_time_ns 早已声明但渲染链从未消费，patch_array_series 缺省 NrTS=100000
（11.5ns 窗）内 4.88GHz 长寿命储能只衰减到幅值 14% 即被切——#262 截断族。

钉面四件（对应任务书）：
① NrTS 换算纯函数（nrts_from_max_time_ns/cfl_dt_s，#328 终网格 CFL 口径）；
② 渲染字面量钉：四 F-D 模板 EndCriteria=1e-06 + Run 前 SetNumberOfTimeSteps
   终网格折算块 + nrts_meta.json 落盘；显式 _nrts/_end_criteria 旋钮最高优先；
③ 其他模板逐字节不变钉（全模板 old-vs-new 已实测 53/53 同字节，此处钉
   结构不变式 + 2 模板 sha256 金钉）；
④ fd_oe_campaign nrts_converged 判读门判定表（#266 口径四分支，c3 同款）。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rfauto.adapters import openems_templates as ot

FD_TEMPLATES = ("patch_array_series", "patch_eep_1x4", "ifa", "ms_array_NxN")


def _render(template: str, params: dict | None = None):
    """战役同构渲染：TEMPLATE_NOMINAL 名义参数 + META 声明网格（0→0.4）。"""
    f0 = float(ot.TEMPLATE_META[template]["f0_ghz"])
    merged = dict(ot.TEMPLATE_NOMINAL.get(template, {}))
    if params:
        merged.update(params)
    mesh = float(ot.TEMPLATE_META[template].get("mesh_resolution_mm") or 0.0)
    return ot.render_script(template, merged, (0.8 * f0, 1.2 * f0),
                            mesh_resolution_mm=mesh if mesh > 0 else 0.4)


def _load_campaign():
    spec = importlib.util.spec_from_file_location(
        "fd_oe_campaign", SCRIPTS / "fd_oe_campaign.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("fd_oe_campaign", mod)
    spec.loader.exec_module(mod)
    return mod


# ── ① NrTS 换算纯函数 ────────────────────────────────────────────────────

class TestNrtsMath:
    def test_seat2_anchor(self):
        # seat2 实测 dt=1.15e-13 s、max_time_ns=30：ceil(1.1·30e-9/1.15e-13)
        assert ot.nrts_from_max_time_ns(30.0, 1.15e-13) == 286957

    def test_ms_array_60ns(self):
        # ms_array_NxN META max_time_ns=60（非 30 缺省）
        assert ot.nrts_from_max_time_ns(60.0, 1.15e-13) == 573914

    def test_safety_margin_direction(self):
        # 安全余量方向：同 dt 下 NrTS ≥ 无余量值（宁长勿截）
        base = math.ceil(30e-9 / 1.15e-13)
        assert ot.nrts_from_max_time_ns(30.0, 1.15e-13) >= base

    def test_rejects_nonpositive(self):
        for t, dt in ((0.0, 1e-13), (-1.0, 1e-13), (30.0, 0.0), (30.0, -1e-13)):
            with pytest.raises(ValueError, match="须 >0"):
                ot.nrts_from_max_time_ns(t, dt)

    def test_cfl_dt_uniform_mm(self):
        # 立方网格：dt=dx/(c·√3)——独立形式互证 + 数值锚
        dx = 1e-3
        dt = ot.cfl_dt_s(dx, dx, dx)
        assert dt == pytest.approx(dx / (299792458.0 * math.sqrt(3.0)))
        assert dt == pytest.approx(1.9258206e-12, rel=1e-6)

    def test_cfl_dt_anisotropic(self):
        # 各向异性：dt 由最小间距轴支配（#328 终网格最小格口径）
        fine = 1e-4
        dt = ot.cfl_dt_s(fine, 1e-3, 1e-3)
        assert dt == pytest.approx(1.0 / (299792458.0 * math.sqrt(
            1.0 / fine**2 + 1.0 / 1e-3**2 + 1.0 / 1e-3**2)))
        assert dt < ot.cfl_dt_s(1e-3, 1e-3, 1e-3)

    def test_cfl_dt_rejects_nonpositive(self):
        with pytest.raises(ValueError, match="须 >0"):
            ot.cfl_dt_s(0.0, 1e-3, 1e-3)


# ── ② 缺省接线判定单源 ──────────────────────────────────────────────────

class TestFdNrtsDefaults:
    def test_auto_applies_to_fd_templates(self):
        for t in FD_TEMPLATES:
            params: dict = {}
            mt = ot._fd_nrts_defaults(t, params)
            assert mt == float(ot.TEMPLATE_META[t]["max_time_ns"]) > 0
            assert params["_end_criteria"] == ot.END_CRITERIA_FD == 1e-6
            assert t not in ("ms_array_NxN",) or mt == 60.0

    def test_explicit_nrts_wins(self):
        params = {"_nrts": 555}
        assert ot._fd_nrts_defaults("patch_array_series", params) is None
        assert params == {"_nrts": 555}          # 零副作用

    def test_explicit_end_criteria_wins(self):
        params = {"_end_criteria": 1e-8}
        assert ot._fd_nrts_defaults("ifa", params) is None
        assert params == {"_end_criteria": 1e-8}

    def test_non_fd_template_untouched(self):
        for t in ("mline", "wilkinson", "ms_patch", "interdigital"):
            params: dict = {}
            assert ot._fd_nrts_defaults(t, params) is None
            assert params == {}

    def test_meta_missing_falls_back(self, monkeypatch):
        monkeypatch.delitem(ot.TEMPLATE_META["ifa"], "max_time_ns")
        params: dict = {}
        assert ot._fd_nrts_defaults("ifa", params) == ot.NRTS_MAX_TIME_FALLBACK_NS

    def test_scope_registered_in_meta(self):
        assert set(FD_TEMPLATES) == set(ot.NRTS_MAX_TIME_TEMPLATES)
        assert set(ot.NRTS_MAX_TIME_TEMPLATES) <= set(ot.TEMPLATE_META)


# ── ③ 渲染字面量钉 ──────────────────────────────────────────────────────

class TestRenderLiterals:
    def test_fd_templates_wired(self):
        for t, t_ns in (("patch_array_series", "30.0e-09"),
                        ("patch_eep_1x4", "30.0e-09"),
                        ("ifa", "30.0e-09"),
                        ("ms_array_NxN", "60.0e-09")):
            text = _render(t)
            # EndCriteria 显式进 FDTD 构造行（−60dB）
            assert "EndCriteria=1e-06)" in text, t
            # Run 前终网格 CFL 折算块（#328）+ 官方 setter 覆写
            assert "SetNumberOfTimeSteps(_nrts_fd)" in text, t
            assert f"1.1 * {t_ns} / _dt_cfl" in text, t
            assert "nrts_meta.json" in text, t
            # 折算块在 Run 之前（终网格点；body 可能补线 #311）
            assert text.index("SetNumberOfTimeSteps") < text.index("FDTD.Run("), t

    def test_explicit_nrts_knob_no_auto(self):
        text = _render("patch_array_series", {"_nrts": 555})
        assert "NrTS=555" in text
        assert "SetNumberOfTimeSteps" not in text
        assert "EndCriteria=" not in text

    def test_explicit_end_criteria_knob_no_auto(self):
        text = _render("ifa", {"_end_criteria": 1e-8})
        assert "EndCriteria=1e-08" in text
        assert "SetNumberOfTimeSteps" not in text

    def test_non_fd_templates_structural_invariance(self):
        # 非 F-D 模板：无 EndCriteria/无覆写块/nrts_meta.json（缺省路径零接触；
        # 全 57 模板 old-vs-new 全量同字节已实测，此处抽代表钉结构不变式）
        for t in ("mline", "wilkinson", "ms_patch", "ms_cross", "bend"):
            text = _render(t)
            assert "SetNumberOfTimeSteps" not in text, t
            assert "nrts_meta.json" not in text, t
            assert "EndCriteria=" not in text, t

    def test_non_fd_templates_byte_pin(self):
        # sha256 金钉（本仓渲染管线字节；有意改模板时重钉并注明出处——df5 口径）
        # 出处：wf:nrts-fix 接线后实测（全 57 模板 old-vs-new 对比 53/53 同字节；
        # 渲染口径=TEMPLATE_NOMINAL 名义参数+META 网格，战役同构）
        # wf:w6e-h01 换钉（2026-10-06）：H-01 sidecar 尾段追加，整脚本 sha
        # 必移（csv 写出段逐字节零漂移，diff 证据 runs/w6_phase6/w6e）；
        pins = {
            "mline": ("855c725bd08c17e1", (2.0, 3.0)),
            # ms_patch 重钉（2026-10-01 ge5 J2 fallback 段①，runs/ge5_j2fb）：
            # 读出修复（全口径电阻片 LumpedPort → soft plane+双 E 探针对+
            # _WgProbePairRefl 反射垫片，jcross 修法同族移植）——旧钉
            # a126c88ff0e66234 对应电阻片读出渲染（已废，audit §D/E）。
            "ms_patch": ("f072b6d99fc57e44", (8.0, 12.0)),
        }
        for t, (sha, band) in pins.items():
            text = ot.render_script(
                t, dict(ot.TEMPLATE_NOMINAL.get(t, {})), band,
                mesh_resolution_mm=float(
                    ot.TEMPLATE_META[t].get("mesh_resolution_mm") or 0.0) or 0.4)
            assert hashlib.sha256(text.encode()).hexdigest()[:16] == sha, t


# ── ④ 离线审计：exec 渲染脚本零仿真（#212）────────────────────────────

def _exec_head(text: str, tmp_path: Path) -> dict:
    """渲染→exec Run 之前全文（几何+网格+折算块）→globals（零仿真）。"""
    head = text[:text.index("FDTD.Run(")]
    g: dict = {"__name__": "sim", "__file__": str(tmp_path / "simulation.py")}
    exec(compile(head, "sim", "exec"), g)  # #212 制式审计入口（零仿真）
    return g


class TestOfflineExecAudit:
    def test_patch_array_series_nrts_overrides(self, tmp_path):
        g = _exec_head(_render("patch_array_series"), tmp_path)
        lines = {ax: g["mesh"].GetLines(ax) for ax in ("x", "y", "z")}
        import numpy as np

        dmins = [float(np.min(np.diff(np.asarray(v, dtype=float))))
                 for v in lines.values()]
        # 生成脚本内联公式 ↔ 纯函数互证（#212 审计口径）
        assert g["_dt_cfl"] == pytest.approx(ot.cfl_dt_s(*dmins), rel=1e-12)
        assert g["_nrts_fd"] == ot.nrts_from_max_time_ns(30.0, g["_dt_cfl"])
        # 修复方向：不再吃 100000 帽（seat2 判读的修复面）
        assert g["_nrts_fd"] > 100000
        # nrts_meta.json 落盘（门旁证/审计消费）
        meta = json.loads((tmp_path / "nrts_meta.json").read_text(encoding="utf-8"))
        assert meta["nrts_declared"] == g["_nrts_fd"]
        assert meta["max_time_ns"] == 30.0
        assert meta["end_criteria"] == 1e-6
        assert meta["dt_cfl_s"] == pytest.approx(g["_dt_cfl"], rel=1e-12)

    def test_ms_array_nxn_nrts_overrides(self, tmp_path):
        text = _render("ms_array_NxN")
        assert "EndCriteria=1e-06)" in text
        g = _exec_head(text, tmp_path)
        assert g["_nrts_fd"] == ot.nrts_from_max_time_ns(60.0, g["_dt_cfl"])
        assert g["_nrts_fd"] > 100000
        meta = json.loads((tmp_path / "nrts_meta.json").read_text(encoding="utf-8"))
        assert meta["max_time_ns"] == 60.0

    def test_mline_exec_has_no_override(self, tmp_path):
        g = _exec_head(_render("mline"), tmp_path)
        assert "_nrts_fd" not in g and "_dt_cfl" not in g
        assert not (tmp_path / "nrts_meta.json").exists()


# ── ⑤ fd_oe_campaign nrts_converged 门（#266 口径判定表）────────────────

_TRUNC_LOG = (
    "FDTD simulation size: 358x1245x40 --> 1.2e7 FDTD cells\n"
    "FDTD timestep is: 1.15e-13 s; Nyquist rate: 2898 timesteps @1.044e10 Hz\n"
    "Excitation signal length is: 21476 timesteps (2.46974e-09s)\n"
    "Max. number of timesteps: 286957 ( --> 13.36 * Excitation signal length)\n"
    "Timestep: 143478 || Energy: ~1.0e-02 (-20.00dB)\n"
    "Timestep: 286957 || Energy: ~1.4e-02 (-18.53dB)\n"
    "Time for 286957 iterations with 1.2e7 cells : 10200.5 sec\n"
    "Max. number of timesteps was reached before the end-criteria of -60dB\n")
_EARLY_OK_LOG = (
    "FDTD timestep is: 1.15e-13 s; Nyquist rate: 2898 timesteps @1.044e10 Hz\n"
    "Excitation signal length is: 21476 timesteps (2.46974e-09s)\n"
    "Max. number of timesteps: 286957 ( --> 13.36 * Excitation signal length)\n"
    "Timestep: 143478 || Energy: ~1.0e-02 (-20.00dB)\n"
    "Timestep: 190000 || Energy: ~9.1e-07 (-60.41dB)\n"
    "Time for 190123 iterations with 1.2e7 cells : 6760.0 sec\n")


class TestCampaignGate:
    @pytest.fixture()
    def fd(self):
        return _load_campaign()

    def test_parse_truncation_signature(self, fd):
        eng = fd.parse_engine_log(_TRUNC_LOG)
        assert eng["dt_s"] == pytest.approx(1.15e-13)
        assert eng["nrts"] == 286957           # 引擎实收=覆写后真值
        assert eng["iterations_done"] == 286957
        assert eng["hit_nrts_limit"] is True
        assert eng["nrts_limit_warning"] is True
        assert eng["end_criteria_db"] == -60.0
        assert eng["min_energy_db"] == -20.0     # 日志能量最低值（峰后回摆前）

    def test_parse_early_stop(self, fd):
        eng = fd.parse_engine_log(_EARLY_OK_LOG)
        assert eng["hit_nrts_limit"] is False
        assert eng["nrts_limit_warning"] is False
        assert eng["excitation_covered"] is True

    def test_convergence_branches(self, fd):
        # ① 引擎触帽告警 → 未收敛（能量再低不采信，c3 同款）
        conv = fd.nrts_convergence(fd.parse_engine_log(_TRUNC_LOG))
        assert conv["converged"] is False
        assert "触 NrTS 上限" in conv["reason"]
        # ② 终止信息缺失 → 不可证明收敛（不采信）
        assert fd.nrts_convergence({})["converged"] is False
        # ③ 触帽但能量已达判据 → 收敛
        hit_ok = fd.nrts_convergence({
            "nrts": 400000, "iterations_done": 400000, "hit_nrts_limit": True,
            "nrts_limit_warning": False, "min_energy_db": -78.52})
        assert hit_ok["converged"] is True
        # ④ 未触帽（EndCriteria 提前停机）→ 收敛
        early = fd.nrts_convergence(fd.parse_engine_log(_EARLY_OK_LOG))
        assert early["converged"] is True
        assert "提前停机" in early["reason"]

    def test_parse_truncation_no_space_variant(self, fd):
        # 7×7 实机文变体（2026-10-01 J2 段⑤）：引擎可输出 "Max.number"（无空格），
        # 旧正则 "Max\. number" 漏检 → 截断门失明（judge 子串匹配同病实证）。
        t = (_TRUNC_LOG
             .replace("Max. number of timesteps: 286957",
                      "Max.number of timesteps: 286957")
             .replace("Max. number of timesteps was reached",
                      "Max.number of timesteps was reached"))
        eng = fd.parse_engine_log(t)
        assert eng["hit_nrts_limit"] is True
        assert eng["nrts_limit_warning"] is True
        assert eng["end_criteria_db"] == -60.0
        conv = fd.nrts_convergence(eng)
        assert conv["converged"] is False

    def test_gate_on_run_dir(self, fd, tmp_path):
        run = tmp_path / "run"
        run.mkdir()
        # 日志缺 → ok=None（不可判，不凑 FAIL 也不凑 PASS）
        gate = fd.nrts_converged_gate(run)
        assert gate["ok"] is None
        # 截断指纹 → ok=False
        (run / "_last_stdout.log").write_text(_TRUNC_LOG, encoding="utf-8")
        (run / "nrts_meta.json").write_text(
            json.dumps({"nrts_declared": 286957, "max_time_ns": 30.0,
                        "dt_cfl_s": 1.15e-13, "end_criteria": 1e-6}),
            encoding="utf-8")
        gate = fd.nrts_converged_gate(run)
        assert gate["ok"] is False
        assert gate["nrts_meta"]["nrts_declared"] == 286957
        # 收敛 → ok=True
        (run / "_last_stdout.log").write_text(_EARLY_OK_LOG, encoding="utf-8")
        assert fd.nrts_converged_gate(run)["ok"] is True

    def test_apply_gate_table(self, fd):
        v = fd.apply_nrts_gate({"status": "PASS"}, {"ok": False, "reason": "触帽未达"})
        assert v["status"] == "FAIL" and "nrts_converged: " in v["reason"]
        v2 = fd.apply_nrts_gate({"status": "PASS"}, {"ok": None, "reason": "日志缺"})
        assert v2["status"] == "PASS" and "nrts_converged" in v2   # 留痕不判
        v3 = fd.apply_nrts_gate({"status": "PARTIAL"}, {"ok": False, "reason": "r"})
        assert v3["status"] == "PARTIAL"                           # 不升级只降级
        v4 = fd.apply_nrts_gate({"status": "FAIL", "reason": "x"},
                                {"ok": True, "reason": "提前停机"})
        assert v4["status"] == "FAIL" and v4["reason"] == "x"      # 门不救 FAIL

    def test_campaign_targets_cover_four_seats(self, fd):
        for t in FD_TEMPLATES:
            assert t in fd.TARGETS
