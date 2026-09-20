"""openems-real-smoke-bundle 离线可测部分（零 openEMS 依赖、零网络）。

覆盖：② NrTS 脚本级改写幂等 + 引擎日志解析 + 旧轮终止诊断；③ AddDump 注入点
唯一性/幂等/编译；④ branchline 四端口渲染四态（excite 恰一处=1、9 列 footer、
轮转集/元数据/geometry_spec 同步）+ 无源/互易/均分数学；① wstep 激励互换与
参考端口改写 + 按端口比对数学 + 引擎端接闭式模型极值；⑤ 修正步长限界；
⑥ M4 复算对账；③ 切片非退化判据。脚本经 importlib 按路径加载（先例
test_commit_groups.py），main() 不执行。
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.fake_adapter import _wstep_sparams
from rfauto.adapters.openems_templates import (
    _FOUR_PORT_ROTATION_TEMPLATES,
    COUPLED_BPF_NOMINAL,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    geometry_spec,
    render_script,
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ws = _load("smoke_wstep_anchor_s22")
nr = _load("smoke_coupled_bpf_nrts")
pf = _load("smoke_patch_field_dump")
bl = _load("smoke_branchline_real_anchor")
b6 = _load("smoke_b6_autotune_real")
m4 = _load("smoke_selfverify_m4_real")

_PORT_EXCITE = re.compile(r"^_port(\d) = MSLPort\(.*?excite=(\d)", re.S | re.M)


# ─── ② coupled_bpf NrTS ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def bpf_script() -> str:
    params = dict(COUPLED_BPF_NOMINAL)
    params["order"] = 3
    return render_script("coupled_bpf", params, (2.25, 2.75), mesh_resolution_mm=0.4)


def test_nrts_rewrite_idempotent_on_real_render(bpf_script):
    assert "NrTS=100000" in bpf_script
    out, n = nr.rewrite_nrts(bpf_script, 400000)
    assert n >= 1
    assert "NrTS=100000" not in out
    assert out.count("NrTS=400000") == n
    out2, n2 = nr.rewrite_nrts(out, 400000)
    assert n2 == 0 and out2 == out
    # 主 FDTD 行仍是合法调用（无 EndCriteria）
    assert "FDTD = openEMS(NrTS=400000)" in out
    compile(out, "sim_nrts", "exec")


def test_nrts_rewrite_with_end_criteria_idempotent(bpf_script):
    out, n = nr.rewrite_nrts(bpf_script, 400000, end_criteria=1e-5)
    assert n >= 1
    assert "openEMS(NrTS=400000, EndCriteria=1e-05)" in out
    assert "openEMS(NrTS=400000)" not in out
    out2, n2 = nr.rewrite_nrts(out, 400000, end_criteria=1e-5)
    assert n2 == 0 and out2 == out
    compile(out, "sim_nrts_ec", "exec")


_PROBE_LOG = """openEMS - force-disabling all field dumps
Create FDTD operator (compressed SSE + multi-threading)
FDTD simulation size: 379x1203x19 --> 8.6628e+06 FDTD cells
FDTD timestep is: 7.16917e-14 s; Nyquist rate: 2536 timesteps @2.75012e+09 Hz
Excitation signal length is: 159840 timesteps (1.14592e-08s)
Max. number of timesteps: 400000 ( --> 2.5025 * Excitation signal length)
Create FDTD engine (compressed SSE + multi-threading)
Running FDTD engine... this may take a while... grab a cup of coffee?!?
[@       32s] Timestep:         6513 || Speed:  139.4 MC/s (3.903e-03 s/TS) || Energy: ~2.58e-15 (- 4.64dB)
[@       48s] Timestep:        10413 || Speed:  136.8 MC/s (3.979e-03 s/TS) || Energy: ~1.06e-22 (-78.52dB)
Time for 400000 iterations with 8.6628e+06 cells : 9000.5 sec
Speed: 148.697 MCells/s
"""


def test_parse_engine_log_header_and_termination():
    info = nr.parse_engine_log(_PROBE_LOG)
    assert info["grid"] == [379, 1203, 19]
    assert info["cells"] == pytest.approx(8.6628e6)
    assert info["dt_s"] == pytest.approx(7.16917e-14)
    assert info["nyquist_steps"] == 2536
    assert info["excitation_steps"] == 159840
    assert info["excitation_s"] == pytest.approx(1.14592e-8)
    assert info["nrts"] == 400000
    assert info["iterations_done"] == 400000
    assert info["hit_nrts_limit"] is True
    assert info["excitation_covered"] is True
    assert info["last_energy_db"] == pytest.approx(-78.52)
    assert info["min_energy_db"] == pytest.approx(-78.52)
    assert info["nrts_limit_warning"] is False          # 无引擎告警行
    # 引擎显式告警行（NrTS=10 干跑实录）→ 终止原因直接可判
    warn = _PROBE_LOG.replace(
        "Time for 400000",
        "RunFDTD: Warning: Max. number of timesteps was reached before the end-criteria of "
        "-60dB was reached... \nTime for 400000")
    info3 = nr.parse_engine_log(warn)
    assert info3["nrts_limit_warning"] is True and info3["end_criteria_db"] == -60.0
    assert nr.PT1_PROBE["excitation_steps"] > 100000     # pt1 截断于激励脉冲中的实证常量
    # 提前收敛（能量判据）形态：迭代数 < NrTS
    early = _PROBE_LOG.replace("Time for 400000 iterations", "Time for 250000 iterations")
    info2 = nr.parse_engine_log(early)
    assert info2["hit_nrts_limit"] is False and info2["excitation_covered"] is True
    assert nr.parse_engine_log("") == {}


def test_diagnose_old_run_nrts_limited(tmp_path):
    dt = 7.16917e-14
    # pt1 形态：Nyquist/4 抽样 45.45ps、末点 7.136ns → ≈99.5k 步（NrTS=100000 截断）
    t = np.arange(0, 7.136e-9 + 1e-12, 4.5452567e-11)
    p = tmp_path / "port_ut_1A"
    p.write_text("% header\n% start\n% stop\n" + "\n".join(f"{ti:.12e}\t0.0" for ti in t) + "\n",
                 encoding="utf-8")
    d = nr.diagnose_old_run(p, dt)
    assert 98000 <= d["steps_est"] <= 100000
    assert d["nrts_limited"] is True
    # 能量判据提前停机形态
    t2 = np.arange(0, 3.0e-9, 4.5452567e-11)
    p2 = tmp_path / "port_ut_short"
    p2.write_text("% h\n" + "\n".join(f"{ti:.12e}\t0.0" for ti in t2) + "\n", encoding="utf-8")
    assert nr.diagnose_old_run(p2, dt)["nrts_limited"] is False


# ─── ③ patch 体 dump 注入 ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def patch_ff_script() -> str:
    return render_script("patch", TEMPLATE_NOMINAL["patch"], (2.0, 2.8), far_field=True)


def test_dump_injection_unique_before_run_and_idempotent(patch_ff_script):
    out, n = pf.inject_volume_dump(patch_ff_script)
    assert n == 1
    call = 'CSX.AddDump("E_field_f0", dump_type=10, frequency=[F0], file_type=1, dump_mode=2)'
    assert out.count(call) == 1
    i_dump = out.index(call)
    i_run = out.index("\nFDTD.Run(SIM_PATH") + 1
    assert i_dump < i_run, "dump 必须注入在主 Run 之前"
    # far_field 注入时主 Run 不带 disable_dumps（模板契约）
    run_line = out[i_run:].split("\n", 1)[0]
    assert "disable_dumps" not in run_line
    out2, n2 = pf.inject_volume_dump(out)
    assert n2 == 0 and out2 == out
    compile(out, "sim_patch_dump", "exec")


def test_dump_injection_rejects_ambiguous_anchor(patch_ff_script):
    with pytest.raises(ValueError):
        pf.inject_volume_dump(patch_ff_script + "\nFDTD.Run(SIM_PATH, verbose=0)\n")
    with pytest.raises(ValueError):
        pf.inject_volume_dump(patch_ff_script.replace("\nFDTD.Run(SIM_PATH", "\n# FDTD.Run(SIM_PATH"))


def test_slices_nondegenerate_judge():
    good = [{"axis": ax, "n": 5, "values": [[0.0, -3.0, -6.0], [-1.0, -2.0, -9.0]]} for ax in "xyz"]
    assert pf.slices_nondegenerate(good)["ok"] is True
    flat = [dict(g, values=[[-1.0, -1.0], [-1.0, -1.0]]) for g in good]
    assert pf.slices_nondegenerate(flat)["ok"] is False
    assert pf.slices_nondegenerate(good[:2])["ok"] is False
    assert pf.slices_nondegenerate([dict(g, n=1) for g in good])["ok"] is False


# ─── ④ branchline 四端口 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("k", [1, 2, 3, 4])
def test_branchline_four_state_excite_exactly_one(k):
    script = render_script("branchline", TEMPLATE_NOMINAL["branchline"], (1.6, 3.2),
                           mesh_resolution_mm=0.4, excite_port=k)
    ports = _PORT_EXCITE.findall(script)
    assert [p for p, _ in ports] == ["1", "2", "3", "4"]
    assert [e for _, e in ports] == ["1" if int(p) == k else "0" for p, _ in ports]
    assert f"_SREF = _port{k}.uf_inc" in script
    assert '"re_S41", "im_S41"' in script            # 9 列单激励 footer
    assert "_port4.CalcPort(SIM_PATH, f, ref_impedance=50)" in script
    assert "port_beta.csv" in script                  # β 金标准（50Ω 馈线）
    compile(script, f"sim_branchline_p{k}", "exec")


def test_branchline_registered_as_four_port_rotation_template():
    assert "branchline" in _FOUR_PORT_ROTATION_TEMPLATES
    meta = TEMPLATE_META["branchline"]
    assert meta["n_ports"] == 4
    assert "S41" in meta["extraction"] and "MSLPort 1-4" in meta["extraction"]
    spec = geometry_spec("branchline", TEMPLATE_NOMINAL["branchline"])
    assert len(spec["ports"]) == 4 and len(spec["boxes"]) == 10
    assert "PML 端接" not in spec["ports"][3]["name"]
    # 旧口径回退绊线：port4 不得再是 PML 端接
    script = render_script("branchline", TEMPLATE_NOMINAL["branchline"], (1.6, 3.2))
    assert "_port4 = MSLPort(CSX, port_nr=4" in script


def test_branchline_port4_geometry_mirrors_port2():
    script = render_script("branchline", TEMPLATE_NOMINAL["branchline"], (1.6, 3.2))
    p2 = re.search(r"_port2 = MSLPort\(.*?priority=10\)", script, re.S).group(0)
    p4 = re.search(r"_port4 = MSLPort\(.*?priority=10\)", script, re.S).group(0)
    assert "start=np.array([BOARD, -HALF + SHW / 2, H_SUB])" in p2
    assert "start=np.array([-BOARD, HALF + SHW / 2, H_SUB])" in p4   # 端口面贴板边 x=−BOARD
    assert "stop=np.array([-HALF, HALF - SHW / 2, 0])" in p4
    assert 'prop_dir="x"' in p4 and "MeasPlaneShift=(BOARD - HALF) / 3" in p4


def test_branchline_closed_form_math_helpers():
    from rfauto.linkage.field_circuit_anchor import branchline_smatrix

    f = np.linspace(1.6e9, 3.2e9, 401)
    s = branchline_smatrix(f, f0_hz=2.4e9)
    pr = bl.passivity_reciprocity(s)
    assert pr["sigma_max"] <= 1.0 + 1e-9 and pr["recip_max"] <= 1e-9
    m = bl.split_metrics(f / 1e9, s, 2.4)
    assert m["f_ghz"] == pytest.approx(2.4)
    assert -4.0 <= m["s21_db"] <= -2.0 and -4.0 <= m["s31_db"] <= -2.0
    assert m["s11_db"] <= -15.0 and m["s41_db"] <= -15.0
    assert all(v["ok"] for v in bl.split_gates(m).values())
    # 均分中心：无耗闭式在 f0 精确均分（有耗版 0.02Np/λ4 使直通/耦合路径衰减不等，
    # 交点偏到 ≈2.43GHz，是闭式自身性质，不是 helper 缺陷）
    s0 = branchline_smatrix(f, f0_hz=2.4e9, loss_np_per_qw=0.0)
    assert bl.equal_split_center(f / 1e9, s0, window_ghz=(2.0, 2.8)) == pytest.approx(2.4, abs=0.01)
    assert bl.equal_split_center(f / 1e9, s, window_ghz=(2.0, 2.8)) == pytest.approx(2.432, abs=0.01)


# ─── ① wstep 激励互换 + 按端口比对 ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def wstep_script() -> str:
    return render_script("wstep", {"w1_mm": ws.W1, "w2_mm": ws.W2, "line_len_mm": ws.L},
                         ws.FREQ_RANGE, mesh_resolution_mm=0.4)


def test_wstep_rewrite_for_port2_swaps_excite_and_reference(wstep_script):
    assert _PORT_EXCITE.findall(wstep_script) == [("1", "1"), ("2", "0")]
    n_ref = wstep_script.count("_port1.uf_inc")
    assert n_ref >= 3
    out = ws.rewrite_for_port2(wstep_script)
    assert _PORT_EXCITE.findall(out) == [("1", "0"), ("2", "1")]
    assert out.count("_port1.uf_inc") == 0 and out.count("_port2.uf_inc") == n_ref
    # footer 内 _port3e 副本（缩进块）excite=1 保持不变
    assert "excite=1, FeedShift=10 * NEAR,\n             MeasPlaneShift=float(_port3.measplane_shift)" in out
    assert ws.rewrite_for_port2(out) == out                      # 幂等
    assert ws.swap_excitation(out, 1) == ws.swap_reference_port(wstep_script, 2)  # 只换激励
    compile(out, "sim_wstep_p2", "exec")


def test_per_port_report_math_and_unitarity():
    f = np.linspace(1.5, 3.5, 201)
    s = _wstep_sparams(f, eps_eff1=2.85, eps_eff2=2.98, z1=50.0, z2=35.35,
                       seg_len_mm=20.0, tan_d=0.0037)
    rep = ws.per_port_report(s[:, 0, 0], s[:, 1, 1], s[:, 1, 0], s[:, 0, 1], s)
    # 引擎=裁判 → 匹配分配零偏差、互易零残差
    assert rep["d11_matched"] == 0.0 and rep["d22_matched"] == 0.0
    assert rep["recip_mag_engine"] == 0.0 and rep["d21_matched"] == 0.0
    # 低耗互易二端口幅度镜像 ≤0.01（幺正性），复数镜像显著（级联序可见）
    assert rep["mirror_mag_fake"] <= 0.01 and rep["mirror_mag_engine"] <= 0.01
    assert rep["mirror_cplx_fake"] > 0.1
    # 互换分配 = 把 S22 当 S11 比：偏差即幅度镜像量
    rep2 = ws.per_port_report(s[:, 1, 1], s[:, 0, 0], s[:, 1, 0], s[:, 0, 1], s)
    assert rep2["d11_matched"] == pytest.approx(rep["mirror_mag_fake"])


def test_engine_termination_model_limits():
    z1, z2, eps2 = 50.0, 35.35, 2.98
    l2 = 46.6667e-3
    f = np.linspace(0.5e9, 4.0e9, 20001)
    s11, s22 = ws.engine_termination_model(f, z1, z2, eps2, l2)
    assert np.allclose(s11, abs((z2 - z1) / (z2 + z1)))
    t_max = abs(z2 * z2 / 50.0 - 50.0) / (z2 * z2 / 50.0 + 50.0)
    assert s22.max() == pytest.approx(t_max, abs=1e-4)       # λ/4 变换器极值
    assert s22.min() == pytest.approx(0.0, abs=1e-3)         # λ/2 处回到 z_ref
    assert s11.shape == f.shape and s22.shape == f.shape


# ─── ⑤ 修正步长限界 / ⑥ M4 复算对账 ───────────────────────────────────────────

def test_step_within_bounds():
    bounds = {"w_mm": (0.6367, 1.0613)}
    hist = [{"round": 1, "params": {"w_mm": 0.849}},
            {"round": 2, "params": {"w_mm": 0.849 * 1.15}},
            {"round": 3, "params": {"w_mm": 0.849 * 1.15 * 0.9}}]
    out = b6.step_within_bounds(hist, bounds, 0.2)
    assert out["ok"] is True and len(out["checks"]) == 2
    bad = [{"round": 1, "params": {"w_mm": 0.849}}, {"round": 2, "params": {"w_mm": 0.849 * 1.3}}]
    assert b6.step_within_bounds(bad, bounds, 0.2)["ok"] is False
    oob = [{"round": 1, "params": {"w_mm": 1.0}}, {"round": 2, "params": {"w_mm": 1.1}}]
    assert b6.step_within_bounds(oob, bounds, 0.2)["ok"] is False
    assert b6.step_within_bounds(hist[:1], bounds, 0.2)["ok"] is True


def test_m4_consistency_passed_and_failed():
    hist = [{"round": 1, "phase": "coarse", "metrics": {"s11_db": -20.0}, "cost": 0.5},
            {"round": 2, "phase": "coarse", "metrics": {"s11_db": -22.0}, "cost": 0.4},
            {"round": 3, "phase": "fine", "metrics": {"s11_db": -21.0}, "cost": 0.45}]
    ms = [{"id": "M4", "status": "passed", "detail": "fine cost 0.45 vs coarse best 0.4（ε=0.2）"}]
    out = m4.m4_consistency(hist, ms, 0.2)
    assert out["coarse_best_cost"] == 0.4 and out["fine_cost"] == 0.45
    assert out["expect_pass"] is True and out["detail_numbers_match"] is True
    assert out["consistent"] is True
    # 细网格劣化超 ε 却标 passed → 不一致；标 failed → 一致
    hist2 = [*hist[:2], {"round": 3, "phase": "fine", "metrics": {}, "cost": 0.6}]
    ms_bad = [{"id": "M4", "status": "passed", "detail": "fine cost 0.6 vs coarse best 0.4（ε=0.2）"}]
    assert m4.m4_consistency(hist2, ms_bad, 0.2)["consistent"] is False
    ms_ok = [{"id": "M4", "status": "failed", "detail": "fine cost 0.6 vs coarse best 0.4（ε=0.2）"}]
    assert m4.m4_consistency(hist2, ms_ok, 0.2)["consistent"] is True
    assert m4.m4_consistency(hist[:1], ms, 0.2)["consistent"] is None
