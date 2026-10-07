"""fd_oe_campaign 驱动离线回归钉（零引擎、零网络、零真机）。

钉面（#df5③/#105/#268/#122）：
① NOMINAL 名义参数真传入 render_script（审查轨 B P1-1「恒 {}」回归家族：
   params 恒空时 render 走内部缺省，ms 族曾在 h=0.508 缺省上跑）；
② 渲染字面量自证（#df5③）：名义参数全部未流入渲染字面量 → G1 fail-fast
   （不烧真机墙钟），求解面零调用；
③ 求解完结（无论健康与否）必清点产物清单（port dump 末行时间轴 #268、
   sparams.csv、模板原生非端口产物）——solver 未回填且磁盘无 csv 时
   PARTIAL 但证据面不缺位；
④ solver 未回填 s_params 但磁盘 sparams.csv 在档 → 离线收割进 G3 判读
   （sparams_source=disk_harvest）；
⑤ G2 求解异常路径同样落产物清单与 wall_s。

渲染/求解面全 mock（monkeypatch rfauto 模块属性——驱动 main() 惰性 import，
补丁属性在调用时生效），不碰 openEMS。
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

MODULE_NAME = "fd_oe_campaign_test_target"
TEMPLATE = "fake_t"
NOMINAL = {"a_mm": 1.0, "b_mm": 2.0, "n_sect": 3}


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
    """参数敏感的假渲染：每个参数值都进字面量（扰动必改变文本）。"""
    lines = [f"# {template} auto"]
    for k in sorted(params):
        lines.append(f"{k} = {params[k]!r}")
    lines.append(f"BAND = {band!r}")
    lines.append(f"MESH = {mesh_resolution_mm!r}")
    return "\n".join(lines)


def _fake_render_const(template, params, band, mesh_resolution_mm=0.0):
    """参数不敏感的假渲染：「恒 {}」回归签名（参数被吞）。"""
    return "FIXED_TEXT\n"


class _Recorder:
    """渲染/求解调用记录面。"""

    def __init__(self):
        self.render_calls: list[dict] = []
        self.solver_builds = 0
        self.solved = 0


def _make_env(monkeypatch, tmp_path, driver, rec: _Recorder, *,
              render_fn=_fake_render_ok, result=None, solve_exc=None):
    """patch 驱动 main() 惰性 import 的全部 rfauto 面 + chdir tmp。"""
    monkeypatch.chdir(tmp_path)
    meta = {TEMPLATE: {"f0_ghz": 5.8, "mesh_resolution_mm": 0.4}}
    nominal = {TEMPLATE: dict(NOMINAL)}

    def _render(template, params, band, mesh_resolution_mm=0.0):
        rec.render_calls.append({"template": template,
                                 "params": dict(params),
                                 "band": tuple(band),
                                 "mesh": mesh_resolution_mm})
        return render_fn(template, params, band,
                         mesh_resolution_mm=mesh_resolution_mm)

    class _FakeSolver:
        def __init__(self, cfg):
            self.cfg = cfg
            rec.solver_builds += 1

        def connect(self):
            return True

        def build_geometry(self, spec):
            return True

        def solve(self):
            rec.solved += 1
            if solve_exc is not None:
                raise solve_exc
            return result

    monkeypatch.setattr("rfauto.adapters.openems_templates.TEMPLATE_META", meta)
    monkeypatch.setattr(
        "rfauto.adapters.openems_templates.TEMPLATE_NOMINAL", nominal)
    monkeypatch.setattr("rfauto.adapters.openems_templates.render_script", _render)
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


def test_nominal_params_reach_render(driver, monkeypatch, tmp_path):
    """钉①：NOMINAL 真传入 render_script（恒 {} 回归即在此翻红）。"""
    rec = _Recorder()
    result = types.SimpleNamespace(success=True,
                                   s_params=np.zeros((3, 2, 2), dtype=complex))
    _make_env(monkeypatch, tmp_path, driver, rec, result=result)
    assert driver.main() == 0
    assert rec.render_calls, "render 未被调用"
    assert rec.render_calls[0]["params"] == NOMINAL
    assert rec.solved == 1
    verdict = _read_verdict(tmp_path)
    assert verdict["status"] == "PASS"
    assert verdict["nominal_literal"]["all_swallowed"] is False
    assert all(v is True for v in verdict["nominal_literal"]["flowed"].values())
    assert len(verdict["render_input_sha256"]) == 64


def test_swallowed_nominal_fails_fast_without_solve(driver, monkeypatch, tmp_path):
    """钉②：参数全未流入渲染字面量 → G1 literal FAIL + 求解面零调用。"""
    rec = _Recorder()
    _make_env(monkeypatch, tmp_path, driver, rec, render_fn=_fake_render_const)
    # H1-5：座位 FAIL → rc 2（修复前恒 0）。
    assert driver.main() == 2
    assert rec.solver_builds == 0 and rec.solved == 0
    verdict = _read_verdict(tmp_path)
    assert verdict["status"] == "FAIL"
    assert "渲染字面量" in verdict["reason"]
    assert verdict["nominal_literal"]["all_swallowed"] is True


def test_solve_complete_no_sparams_harvests_artifacts(driver, monkeypatch, tmp_path):
    """钉③：无 S 参数产物时 PARTIAL，但产物清单落 verdict（证据面不缺位）。"""
    rec = _Recorder()
    result = types.SimpleNamespace(success=True, s_params=None)
    _make_env(monkeypatch, tmp_path, driver, rec, result=result)
    run_dir = tmp_path / "runs" / "ge_fd" / TEMPLATE
    (run_dir / "fdtd").mkdir(parents=True)
    (run_dir / "fdtd" / "port_ut_1A").write_text(
        "% header\n1.0e-8 0.001\n1.1495e-08\t-0.0001\n", encoding="utf-8")
    (run_dir / "fdtd" / "et").write_text("0 0\n1.15e-13 6.5e-5\n2.47e-09 6.5e-5\n",
                                         encoding="utf-8")
    # H1-5：PARTIAL 座位 → rc 4（非 FAIL/SKIP 的非 PASS 态）。
    assert driver.main() == 4
    verdict = _read_verdict(tmp_path)
    assert verdict["status"] == "PARTIAL"
    art = verdict["artifacts"]
    assert art["port_dumps"]["port_ut_1A"] == pytest.approx(1.1495e-08)
    assert art["et_t_end"] == pytest.approx(2.47e-09)
    assert art["sparams_csv_bytes"] is None


def test_disk_sparams_harvested_when_solver_sparams_empty(
        driver, monkeypatch, tmp_path):
    """钉④：solver 未回填但磁盘 csv 在档 → 离线收割进 G3（零求解补产物）。"""
    rec = _Recorder()
    result = types.SimpleNamespace(success=True, s_params=None)
    _make_env(monkeypatch, tmp_path, driver, rec, result=result)
    run_dir = tmp_path / "runs" / "ge_fd" / TEMPLATE
    run_dir.mkdir(parents=True)
    (run_dir / "sparams.csv").write_text(
        "freq_hz,re_S11,im_S11,re_S21,im_S21\n"
        "4.64e9,0.1,0.0,0.5,0.0\n"
        "5.8e9,0.2,0.01,0.6,0.0\n",
        encoding="utf-8")
    assert driver.main() == 0
    verdict = _read_verdict(tmp_path)
    assert verdict["sparams_source"] == "disk_harvest"
    assert verdict["shape"] == [2, 2, 2]
    assert verdict["g3_finite"] is True
    assert verdict["g3_passive_le_1p05"] is True
    assert verdict["status"] == "PASS"


def test_g2_exception_records_artifacts_and_wall(driver, monkeypatch, tmp_path):
    """钉⑤：G2 异常路径落产物清单 + wall_s（#105 观测不缺位）。"""
    rec = _Recorder()
    _make_env(monkeypatch, tmp_path, driver, rec,
              solve_exc=RuntimeError("引擎不可用"))
    run_dir = tmp_path / "runs" / "ge_fd" / TEMPLATE
    (run_dir / "fdtd").mkdir(parents=True)
    (run_dir / "fdtd" / "port_ut_1A").write_text("% h\n1.0e-8 0.001\n",
                                                 encoding="utf-8")
    # H1-5：座位 FAIL → rc 2。
    assert driver.main() == 2
    verdict = _read_verdict(tmp_path)
    assert verdict["status"] == "FAIL"
    assert verdict["reason"].startswith("G2 求解")
    assert isinstance(verdict["wall_s"], float)
    assert verdict["artifacts"]["port_dumps"]["port_ut_1A"] == pytest.approx(1.0e-8)


def test_parse_sparams_csv_disk_3port_layout(driver, tmp_path):
    """9 列 3 端口 csv → (n,3,3) 且条目落位正确；垃圾输入如实 None。"""
    p = tmp_path / "sp.csv"
    p.write_text(
        "% comment\n"
        "freq_hz,re_S11,im_S11,re_S21,im_S21,re_S31,im_S31,re_S23,im_S23\n"
        "1e9,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8\n",
        encoding="utf-8")
    s = driver._parse_sparams_csv_disk(p)
    assert s is not None and s.shape == (1, 3, 3)
    assert s[0, 0, 0] == pytest.approx(0.1 + 0.2j)
    assert s[0, 1, 0] == pytest.approx(0.3 + 0.4j)
    assert s[0, 2, 0] == pytest.approx(0.5 + 0.6j)
    assert s[0, 1, 2] == pytest.approx(0.7 + 0.8j)
    bad = tmp_path / "bad.csv"
    bad.write_text("not,a,real\nx,y,z\n", encoding="utf-8")
    assert driver._parse_sparams_csv_disk(bad) is None


def test_nominal_literal_check_int_render_exception_marks_unknown(driver):
    """扰动渲染对 int 参数炸掉（如 range(3.003)）→ None（不可判，不计吞）。"""

    def _render(template, params, band, mesh_resolution_mm=0.0):
        if not isinstance(params.get("n_x"), int):
            raise TypeError("int only")
        return f"OK n_x={params['n_x']!r} a_mm={params['a_mm']!r}"

    flowed, base = driver._nominal_literal_check(
        TEMPLATE, {"n_x": 3, "a_mm": 1.0}, (4.0, 6.0), 0.4, _render)
    assert base.startswith("OK n_x=3")
    assert flowed["n_x"] is None
    assert flowed["a_mm"] is True
