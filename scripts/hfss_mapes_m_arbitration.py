"""HFSS 逐口 m 规范仲裁（sref 剩余互易底）。

预声明：runs/hfss_mapes_m_arb/criteria.md（先于任何真跑写死，判读常量
不许跑后改）。模板：scripts/hfss_mapes_g0_arbitration.py（结构构建/负载
接法/判读链照抄改造；被仲裁口=lumped_port 50Ω，其余 149 口（含 io 两口）
全部 50Ω RLC 负载——与 openEMS 每轮"单激励+全 50Ω 端接"同端接语义）。

两段执行（判读段零仿真可复跑）：
    .venv/Scripts/python.exe scripts/hfss_mapes_m_arbitration.py --hfss
    .venv/Scripts/python.exe scripts/hfss_mapes_m_arbitration.py --judge
环境变量（同 g0）：RFAUTO_MAPES_M_DELTA_S（缺省 0.02）/
RFAUTO_MAPES_M_MAX_PASSES（缺省 12）/ RFAUTO_MAPES_M_TAG（产物后缀）。

主判据（criteria §6/§7）：对 11 个抽样口解 S11，与 openEMS raw wave 装配
对角比幅相；m_p = mask 内 median_f angle(S11_h·conj(S11_oe))；d_p 并列
不进门。应用门：m 按层展开（io 逐口、via 单飞、其余层中位）酉对角共轭
作用于 wav+colC 装配链，150 轮零仿真复算互易底：≤5e-3 PASS，否则 FAIL
如实（"m 是剩余主项"假设也可能被证伪——预声明解释分支见 criteria §1/§7）。
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
WORK_DIR = REPO / "runs" / "hfss_mapes_m_arb"
RAW_UI_NPZ = REPO / "runs" / "mapes_zall_refix" / "s5_diag" / "raw_ui.npz"
DELTA_NPZ = REPO / "runs" / "mapes_sref_study" / "delta_estimates.npz"

# ---- 预声明门（criteria §6/§7/§8，写死） ------------------------------
GATE_TARGET = 5.0e-3
S11_FLOOR = 0.05
Z0 = 50.0
SOLVE_TIMEOUT_S = 2400
WALL_BUDGET_S = 3 * 3600
WALL_PARTIAL_S = int(1.5 * WALL_BUDGET_S)
PRIMARY_CALIBER = "wav_diag"
CALIBERS = ("wav_diag", "wc_diag", "gamma_hat")
LAYER_MEDIAN = ("pixel", "pixel_h", "pixel_v", "diag")

# 抽样名单（criteria §4 写死）：(端口号1基, label, 层, 档)
SAMPLED: list[tuple[int, str, str, str]] = [
    (1, "io1", "io", "both"),
    (2, "io2", "io", "both"),
    (3, "px_r0_c0", "pixel", "lo"),
    (38, "px_r5_c5", "pixel", "hi"),
    (39, "h_r0_c0", "pixel_h", "lo"),
    (68, "h_r5_c4", "pixel_h", "hi"),
    (69, "v_r0_c0", "pixel_v", "lo"),
    (98, "v_r4_c5", "pixel_v", "hi"),
    (99, "dm_r0_c0", "diag", "lo"),
    (148, "da_r4_c4", "diag", "hi"),
    (150, "via1_via_ground", "via", "single"),
]


def _load_zall_module():
    """按路径加载 scripts/mapes_s2_zall.py（scripts 非包；几何单一事实源）。"""
    path = REPO / "scripts" / "mapes_s2_zall.py"
    spec = importlib.util.spec_from_file_location("mapes_s2_zall", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def port_classes() -> dict[int, tuple[str, str]]:
    """0 基端口索引 → (层, label)；层=slot.category 权威口径（criteria §4）。"""
    mod = _load_zall_module()
    layout = mod.build_layout()
    slots = layout.load_slots()
    geom = mod.build_geom(layout)
    out: dict[int, tuple[str, str]] = {}
    for port in geom.ports:
        idx = port.number - 1
        if port.slot_index < 0:
            out[idx] = ("io", port.label)
            continue
        cat = slots[port.slot_index].category
        layer = {"pixel": "pixel", "pixel_h": "pixel_h", "pixel_v": "pixel_v",
                 "diag_main": "diag", "diag_anti": "diag",
                 "via_ground": "via"}[cat]
        out[idx] = (layer, port.label)
    return out


def load_assembly() -> dict:
    """openEMS 装配链（零仿真复算，analyze_sref 同式）：wav/wav+colC/Γ̂/m̂。"""
    sys.path.insert(0, str(REPO / "src"))
    from rfauto.core.mapes import assemble_s_from_ui

    with np.load(RAW_UI_NPZ) as d:
        freqs = np.asarray(d["freq_hz"], dtype=float)
        uf = np.asarray(d["uf_all"], dtype=complex)
        im = np.asarray(d["if_all"], dtype=complex)
    s_wav = assemble_s_from_ui(uf, im, reference_impedance=Z0, numerator="wave")
    with np.load(DELTA_NPZ) as dd:
        delta = np.asarray(dd["delta"], dtype=complex)
        mh = np.asarray(dd["m_gauge"], dtype=complex)
    diag = np.diagonal(s_wav, axis1=1, axis2=2)  # (nf,q) raw wave 对角
    sh, ch = np.sinh(delta / 2.0), np.cosh(delta / 2.0)
    gam = (diag * ch - sh) / (ch - diag * sh)  # Δ 模型内精确反演（同 colC）
    cfac = ch + gam * sh
    s_wc = s_wav * cfac[:, None, :]
    return {
        "freqs": freqs, "s_wav": s_wav, "s_wc": s_wc, "diag_wav": diag,
        "gamma_hat": gam, "m_c": np.median(mh.imag, axis=0),
        "calibers": {"wav_diag": diag, "wc_diag": np.diagonal(s_wc, axis1=1,
                                                              axis2=2),
                     "gamma_hat": gam},
    }


# --------------------------------------------------------------------------- #
# HFSS 段（--hfss）
# --------------------------------------------------------------------------- #

def build_mapes_geometry(adapter, port_number: int) -> dict:
    """重建 MAPES Z_ALL 参考结构；被仲裁口=lumped_port，其余全部 50Ω 负载。

    与 g0 唯一结构差：io 两口在本系列降为 50Ω RLC 竖片（除非被仲裁）。
    """
    mod = _load_zall_module()
    layout = mod.build_layout()
    geom = mod.build_geom(layout)
    bleeds = mod.bleed_boxes(geom)
    from rfauto.core.mapes import PORT_KIND_LUMPED_GAP, port_probe_axes

    hfss = adapter.session.hfss
    modeler = hfss.modeler
    modeler.model_units = "mm"

    def mm(v: float) -> str:
        return f"{v * 1e3:.9f}"

    mat = "rfauto_mapes_rogers4350b"
    with contextlib.suppress(Exception):
        hfss.materials.add_material(
            mat, properties={"permittivity": mod.SUB["er"],
                             "dielectric_loss_tangent": mod.SUB["tan_d"]})

    dx0, dy0, dx1, dy1 = geom.domain
    h = geom.sub_h_m
    air_top = h + 3e8 / 6e9 / 4.0  # 顶 λ0/4 @6GHz（同 g0/openEMS）

    modeler.create_box(
        origin=[mm(dx0), mm(dy0), "0mm"],
        sizes=[mm(dx1 - dx0), mm(dy1 - dy0), mm(h)],
        name="Substrate", material=mat)
    modeler.create_rectangle(
        orientation="XY", origin=[mm(dx0), mm(dy0), "0mm"],
        sizes=[mm(dx1 - dx0), mm(dy1 - dy0)], name="Ground")
    patch_names = []
    for i, (px0, py0, px1, py1) in enumerate(geom.patches):
        name = f"Patch{i}"
        modeler.create_rectangle(
            orientation="XY", origin=[mm(px0), mm(py0), mm(h)],
            sizes=[mm(px1 - px0), mm(py1 - py0)], name=name)
        patch_names.append(name)
    pixels_name = patch_names[0]  # unite 保留首对象名（#285）
    modeler.unite(patch_names, keep_originals=False)

    load_sheets: list[tuple[str, str, float]] = []  # (name, direction, R)
    arb_sheet = ""
    arb_direction = "ZPos"
    for port in geom.ports:
        s, t = port.start, port.stop
        is_arb = port.number == port_number
        if port.kind == PORT_KIND_LUMPED_GAP:
            name = f"ArbP{port.number}" if is_arb else f"LoadP{port.number}"
            modeler.create_rectangle(
                orientation="XY",
                origin=[mm(s[0]), mm(s[1]), mm(h)],
                sizes=[mm(t[0] - s[0]), mm(t[1] - s[1])], name=name)
            direction = ("XPos", "YPos")[port_probe_axes(port)]
            if is_arb:
                arb_sheet, arb_direction = name, direction
            else:
                load_sheets.append((name, direction, 50.0))
        else:  # 竖直贴片-地口（含 io）
            x_c = 0.5 * (s[0] + t[0])
            name = f"ArbP{port.number}" if is_arb else f"LoadP{port.number}"
            if not is_arb:
                load_sheets.append((name, "ZPos", 50.0))
            else:
                arb_sheet, arb_direction = name, "ZPos"
            modeler.create_rectangle(
                orientation="YZ",
                origin=[mm(x_c), mm(s[1]), "0mm"],
                sizes=[mm(t[1] - s[1]), mm(h)], name=name)
    if not arb_sheet:
        raise RuntimeError(f"被仲裁口 {port_number} 未落任何 sheet")
    for i, (bx0, by0, bx1, by1) in enumerate(bleeds):
        name = f"Bleed{i}"
        modeler.create_rectangle(
            orientation="YZ", origin=[mm(0.5 * (bx0 + bx1)), mm(by0), "0mm"],
            sizes=[mm(by1 - by0), mm(h)], name=name)
        load_sheets.append((name, "ZPos", 10000.0))

    hfss.assign_perfecte_to_sheets(assignment=["Ground"], name="GroundPEC")
    hfss.assign_perfecte_to_sheets(assignment=[pixels_name], name="PixelsPEC")

    from ansys.aedt.core.generic.constants import Gravity

    for name, direction, r_ohm in load_sheets:
        hfss.assign_lumped_rlc_to_sheet(
            assignment=name, start_direction=getattr(Gravity, direction),
            name=f"{name}RLC", rlc_type="Parallel", resistance=r_ohm)

    modeler.create_box(
        origin=[mm(dx0), mm(dy0), "0mm"],
        sizes=[mm(dx1 - dx0), mm(dy1 - dy0), mm(air_top)],
        name="Air", material="air")
    subtract_tools = ["Substrate", "Ground", pixels_name] + [
        n for n, _d, _r in load_sheets] + [arb_sheet]
    modeler.subtract("Air", subtract_tools)
    # 面心以模型单位 mm 返回（#285），几何常量为米制——统一 mm 后过滤
    top_mm = air_top * 1e3
    h_mm = h * 1e3
    mid_x = 0.5 * (dx0 + dx1) * 1e3
    mid_y = 0.5 * (dy0 + dy1) * 1e3
    half_x = 0.5 * (dx1 - dx0) * 1e3
    half_y = 0.5 * (dy1 - dy0) * 1e3
    tol = 1e-3
    open_faces = []
    for face in modeler.get_object_faces("Air"):
        cx, cy, cz = (float(v) for v in modeler.get_face_center(face))
        if cz > h_mm + tol and (
                abs(cz - top_mm) < tol
                or abs(abs(cx - mid_x) - half_x) < tol
                or abs(abs(cy - mid_y) - half_y) < tol):
            open_faces.append(face)
    if not open_faces:
        raise RuntimeError("辐射面过滤为空：检查面心单位/域尺寸")
    hfss.assign_radiation_boundary_to_faces(
        assignment=open_faces, name="Radiation")

    # 被仲裁口 = 真端口（sheet 名传入，#263；积分线方向随口类）
    hfss.lumped_port(
        assignment=arb_sheet, integration_line=getattr(Gravity, arb_direction),
        impedance=50.0, name=f"P{port_number}", renormalize=True)
    return {"layout": layout, "geom": geom, "n_loads": len(load_sheets),
            "n_bleeds": len(bleeds)}


def make_setup(adapter, delta_s: float, max_passes: int) -> str:
    hfss = adapter.session.hfss
    setup = hfss.create_setup(name="MapesMArbSetup")
    setup.props["Frequency"] = "3.5GHz"
    setup.props["MaxDeltaS"] = float(delta_s)
    setup.props["MaximumPasses"] = int(max_passes)
    setup.update()
    hfss.create_linear_count_sweep(
        setup="MapesMArbSetup", unit="GHz", start_frequency=1.0,
        stop_frequency=6.0, num_of_freq_points=41, name="MapesMArbSweep",
        sweep_type="Interpolating", save_fields=False)
    return "MapesMArbSetup"


def _kill_desktops() -> None:
    """ansysedt 清场（治理单源）：孤儿点杀+活桌面 fail-closed（#245/#265）。

    委托 src/rfauto/infra/desktop_guard.py；旧实现 Get-Process|
    Stop-Process -Force 无条件代杀已废弃（误杀他轨合法桌面，#265）。
    """
    from rfauto.infra.desktop_guard import kill_orphan_ansysedt_desktops

    kill_orphan_ansysedt_desktops(log=print)


def solve_ports() -> list[dict]:
    """逐口全生命周期（每口 close→connect→open_or_create 同工程新设计，
    全部 g0 验证过的调用形式；#191 禁双 Hfss 实例故不走 insert_design）。"""
    import shutil

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    for stale in WORK_DIR.glob("hfss_mapes_m_arb.aedt*"):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        else:
            stale.unlink(missing_ok=True)
    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.infra.version_probe import resolve_aedt_install

    install = resolve_aedt_install(None)
    assert install is not None, "未发现可用 AEDT 安装"
    version = install["aedt_version"]
    delta_s = float(os.environ.get("RFAUTO_MAPES_M_DELTA_S", "0.02"))
    max_passes = int(os.environ.get("RFAUTO_MAPES_M_MAX_PASSES", "12"))
    tag = os.environ.get("RFAUTO_MAPES_M_TAG", "")

    runs: list[dict] = []
    for number, label, _layer, tier in SAMPLED:
        if tier == "refine":
            continue  # refine 轮单独跑（见下方 runs + [refine 项]）
        runs.append({"port": number, "label": label, "tier": tier,
                     "suffix": "", "delta_s": delta_s})
    t_start = time.time()
    design_no = 0
    project_path = WORK_DIR / "hfss_mapes_m_arb.aedt"
    adapter = HfssAdapter()
    connected = False
    try:
        refine_spec = {"port": 1, "label": "io1", "tier": "refine",
                       "suffix": "_refine", "delta_s": 0.002}
        for spec in (*runs, refine_spec):
            design_no += 1
            design_name = f"mapes_m_p{spec['port']:03d}{spec['suffix']}"
            t0 = time.time()
            if connected:
                adapter.close(save=True)
                connected = False
            adapter.connect({"desktop_version": version, "non_graphical": True})
            connected = True
            adapter.open_or_create_project(project_path, design_name)
            build_info = build_mapes_geometry(adapter, spec["port"])
            t_build = time.time() - t0
            setup_name = make_setup(adapter, spec["delta_s"], max_passes)
            t1 = time.time()
            report = adapter.solve(setup_name, timeout_s=SOLVE_TIMEOUT_S)
            t_solve = time.time() - t1
            assert report.success, f"求解失败: {report.message}"
            passes, final_ds = 0, 0.0
            with contextlib.suppress(Exception):
                setup = adapter.session.hfss.get_setup(setup_name)
                if setup is not None:
                    passes, final_ds = HfssAdapter._extract_convergence(setup)
            s2p = adapter.export_touchstone(
                WORK_DIR / f"port_{spec['port']:03d}{spec['suffix']}.s1p")
            spec.update({"s1p": str(s2p), "passes": passes,
                         "final_delta_s": final_ds, "t_build_s": round(t_build, 1),
                         "t_solve_s": round(t_solve, 1),
                         "n_loads": build_info["n_loads"],
                         "design": design_name})
            print(f"[port {spec['port']}] {spec['label']} "
                  f"build={t_build:.0f}s "
                  f"solve={t_solve:.0f}s passes={passes} dS={final_ds:.4f} "
                  f"-> {Path(s2p).name}", flush=True)
        elapsed = time.time() - t_start
        print(f"[done] {design_no} solves, wall={elapsed / 60:.1f}min",
              flush=True)
        (WORK_DIR / f"hfss_runs{('_' + tag) if tag else ''}.json").write_text(
            json.dumps({"aedt_version": version, "delta_s": delta_s,
                        "max_passes": max_passes, "wall_s": round(elapsed, 1),
                        "runs": runs}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        return runs
    finally:
        if connected:
            with contextlib.suppress(Exception):
                adapter.close(save=True)


def main_hfss() -> int:
    for attempt in range(2):
        try:
            if attempt:
                _kill_desktops()
            solve_ports()
            print("MAPES_M_HFSS_DONE", flush=True)
            return 0
        except Exception as exc:
            print(f"attempt {attempt + 1}/2 FAIL: {exc}", flush=True)
    print("MAPES_M_HFSS_FAIL_AFTER_ATTEMPTS", flush=True)
    return 1


# --------------------------------------------------------------------------- #
# 判读段（--judge，零仿真）
# --------------------------------------------------------------------------- #

def _angle_median(prod: np.ndarray, mask: np.ndarray) -> tuple[float, str]:
    """带内中位相位差；样本极差 >π 时回退复数中位式（criteria §6 守卫）。"""
    ang = np.angle(prod[mask])
    if float(ang.max() - ang.min()) > np.pi:
        return float(np.angle(np.median(prod[mask]))), "complex_median_f"
    return float(np.median(ang)), "median_angle"


def _interp_to(freq_ref: np.ndarray, f: np.ndarray,
               v: np.ndarray) -> np.ndarray:
    if freq_ref.shape == f.shape and np.allclose(freq_ref, f, rtol=1e-6,
                                                 atol=1.0):
        return v
    return np.interp(freq_ref, f, v.real) + 1j * np.interp(freq_ref, f, v.imag)


def _port_entry(number: int, label: str, layer: str, tier: str,
                asm: dict, freqs: np.ndarray) -> dict:
    """单口判读条目：三口径 m/d/τ + 频点掩码统计（criteria §6 估计式）。"""
    import skrf

    suffix = "_refine" if tier == "refine" else ""
    path = WORK_DIR / f"port_{number:03d}{suffix}.s1p"
    if not path.exists():
        raise FileNotFoundError(f"缺少 HFSS 产物 {path}（先跑 --hfss）")
    net = skrf.Network(str(path))
    f_h = net.frequency.f.astype(float)
    s11_h = _interp_to(freqs, f_h, net.s[:, 0, 0])
    mask = np.abs(s11_h) >= S11_FLOOR
    entry: dict = {"port": number, "label": label, "layer": layer,
                   "tier": tier, "n_freq_used": int(np.count_nonzero(mask)),
                   "s11_hfss_band_median":
                       float(np.median(np.abs(s11_h[mask]))),
                   "angle_estimator": ""}
    for cal in CALIBERS:
        s_oe = _interp_to(freqs, f_h, asm["calibers"][cal][:, number - 1])
        prod = s11_h * np.conj(s_oe)
        m_p, est = _angle_median(prod, mask)
        d_p = float(np.median(
            (np.abs(np.abs(s11_h) - np.abs(s_oe))
             / np.maximum(np.abs(s11_h), S11_FLOOR))[mask]))
        phase = np.unwrap(np.angle(prod))
        tau_p = float(np.polyfit(2.0 * np.pi * freqs[mask], phase, 1)[0])
        entry[cal] = {"m_rad": m_p, "d_rel": d_p, "tau_ps": tau_p * 1e12}
        if cal == PRIMARY_CALIBER:
            entry["angle_estimator"] = est
    return entry


def judge() -> dict:
    asm = load_assembly()
    freqs, s_wc, m_c = asm["freqs"], asm["s_wc"], asm["m_c"]
    classes = port_classes()
    runs_meta: dict = {}
    meta_path = WORK_DIR / "hfss_runs.json"
    if meta_path.exists():
        runs_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    per_port: list[dict] = []
    for number, label, layer, tier in SAMPLED:
        per_port.append(_port_entry(number, label, layer, tier, asm, freqs))

    main_rows = [e for e in per_port if e["tier"] != "refine"]
    m_of: dict[int, float] = {e["port"]: e[PRIMARY_CALIBER]["m_rad"]
                              for e in main_rows}
    d_of: dict[int, float] = {e["port"]: e[PRIMARY_CALIBER]["d_rel"]
                              for e in main_rows}

    # 层展开（criteria §7）：io 逐口、via 单飞、其余层中位
    m_full = np.zeros(len(classes), dtype=float)
    m_full[0], m_full[1] = m_of[1], m_of[2]
    m_full[148] = m_full[149] = m_of[150]
    layer_detail: dict[str, dict] = {}
    for layer in LAYER_MEDIAN:
        members = [e["port"] for e in main_rows if e["layer"] == layer]
        val = float(np.median([m_of[p] for p in members]))
        layer_detail[layer] = {"sampled_ports": members,
                               "m_rad_median": val}
        for idx, (cls, _lbl) in classes.items():
            if cls == layer:
                m_full[idx] = val
    layer_detail["io"] = {"sampled_ports": [1, 2],
                          "m_rad": [m_of[1], m_of[2]]}
    layer_detail["via"] = {"sampled_ports": [150], "m_rad": m_of[150]}

    # 应用（酉对角共轭；σmax 严格不变）
    def conj_phase(s: np.ndarray, m: np.ndarray) -> np.ndarray:
        return (s * np.exp(-1j * m)[None, :, None]
                * np.exp(1j * m)[None, None, :])

    sys.path.insert(0, str(REPO / "src"))
    from rfauto.core.mapes import fit_reciprocity_gain, z_all_gate

    g_base = z_all_gate(s_wc)
    _x_base, info_base = fit_reciprocity_gain(s_wc)
    s_fix = conj_phase(s_wc, m_full)
    g_fix = z_all_gate(s_fix)
    _x_fix, info_fix = fit_reciprocity_gain(s_fix)
    verdict = "PASS" if g_fix["reciprocity_max"] <= GATE_TARGET else "FAIL"

    # 诊断 D1（m̂_c 反事实）/ D2（相关性）/ D5（分层贡献）
    s_d1 = conj_phase(s_wc, m_c)
    g_d1 = z_all_gate(s_d1)
    sampled_ports = [e["port"] for e in main_rows]
    mh_sample = np.array([m_c[p - 1] for p in sampled_ports])
    hfss_sample = np.array([m_of[p] for p in sampled_ports])
    from scipy.stats import pearsonr, spearmanr

    d2 = {
        "pearson_r": float(pearsonr(mh_sample, hfss_sample).statistic),
        "pearson_p": float(pearsonr(mh_sample, hfss_sample).pvalue),
        "spearman_rho": float(spearmanr(mh_sample, hfss_sample).statistic),
        "spearman_p": float(spearmanr(mh_sample, hfss_sample).pvalue),
        "median_offset_rad": float(np.median(hfss_sample - mh_sample)),
        "rms_after_offset_rad": float(np.sqrt(np.mean(
            ((hfss_sample - mh_sample)
             - np.median(hfss_sample - mh_sample)) ** 2))),
    }
    m_io_only = m_c.copy()
    m_io_only[0], m_io_only[1] = m_of[1], m_of[2]
    m_virt_only = m_full.copy()
    m_virt_only[0], m_virt_only[1] = m_c[0], m_c[1]
    d5 = {
        "hfss_all": g_fix["reciprocity_max"],
        "hfss_virtual_mhat_io": float(z_all_gate(
            conj_phase(s_wc, m_virt_only))["reciprocity_max"]),
        "mhat_virtual_hfss_io": float(z_all_gate(
            conj_phase(s_wc, m_io_only))["reciprocity_max"]),
        "mhat_all": g_d1["reciprocity_max"],
    }

    # D4：io1 精网格相位稳定度（独立读 port_001_refine.s1p，不在 SAMPLED 层）
    d4 = {}
    if (WORK_DIR / "port_001_refine.s1p").exists():
        refine = _port_entry(1, "io1", "io", "refine", asm, freqs)
        m_ref = refine[PRIMARY_CALIBER]["m_rad"]
        d4 = {"port": 1, "m_coarse_rad": m_of[1], "m_refine_rad": m_ref,
              "abs_dm_rad": abs(m_of[1] - m_ref),
              "d_coarse": d_of[1], "d_refine": refine[PRIMARY_CALIBER]["d_rel"],
              "tau_coarse_ps": main_rows[0][PRIMARY_CALIBER]["tau_ps"],
              "tau_refine_ps": refine[PRIMARY_CALIBER]["tau_ps"]}

    wall = runs_meta.get("wall_s")
    budget = "ok"
    if wall is not None and float(wall) > WALL_PARTIAL_S:
        budget = f"PARTIAL_over_1p5x_wall_{wall}s"

    res = {
        "id": "hfss_mapes_m",
        "verdict": verdict,
        "budget_status": budget,
        "gate": {
            "target": GATE_TARGET,
            "reciprocity_max_baseline_wav_colC": g_base["reciprocity_max"],
            "reciprocity_max_after_m": g_fix["reciprocity_max"],
            "reciprocity_perfreq_median_after_m":
                g_fix["reciprocity_perfreq_median"],
            "sigma_max_before": g_base["sigma_max"],
            "sigma_max_after": g_fix["sigma_max"],
            "application": "S_fix = S_wc * exp(-j m_i) * exp(+j m_k)（酉对角共轭）",
            "m_expansion": layer_detail,
        },
        "secondary_curl": {
            "curl_wrms_median_wav_colC": info_base["fit_resid_wrms_median"],
            "curl_wrms_median_after_m": info_fix["fit_resid_wrms_median"],
        },
        "diagnostics": {
            "D1_mhat_counterfactual": {
                "reciprocity_max": g_d1["reciprocity_max"],
                "note": "m̂_c（自提取带内中位相位）全量共轭——若 HFSS 完美钉中"
                        " m̂ 的可达位置；逐频完整 m̂ 共轭=逐位不变（规范不变性"
                        "自检，criteria §2）",
            },
            "D2_correlation_mhats_vs_hfss": d2,
            "D4_io1_refine": d4,
            "D5_layer_contribution": d5,
        },
        "per_port": per_port,
        "primary_caliber": PRIMARY_CALIBER,
        "n_solves": len(per_port),
        "wall_s": wall,
        "runs_meta": runs_meta,
        "criteria": "runs/hfss_mapes_m_arb/criteria.md",
    }
    tag = os.environ.get("RFAUTO_MAPES_M_TAG", "")
    out = WORK_DIR / f"arbitration_result{('_' + tag) if tag else ''}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: res[k] for k in
                      ("verdict", "budget_status", "gate", "secondary_curl",
                       "diagnostics")}, ensure_ascii=False, indent=1),
          flush=True)
    print(f"MAPES_M_VERDICT_{verdict}", flush=True)
    return res


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--judge"
    if mode == "--hfss":
        return main_hfss()
    if mode == "--judge":
        judge()
        return 0
    raise SystemExit(f"未知模式 {mode}（用 --hfss / --judge）")


if __name__ == "__main__":
    sys.exit(main())
