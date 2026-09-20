"""HFSS 真机跑 MAPES Z_ALL 参考结构，仲裁基准 g0（对齐基准口径）。

背景：MAPES 装配
Z_ALL 的全局复规范 ``g(f) = g0·exp(j·2π·f·τ)``（core/mapes.gauge_factor）互易
原理性不可辨识；openEMS 侧直接全波腿对拍标定 g0=1.005/τ=−0.25ps 因"直接腿与
装配腿同类探针同源偏差"被否作裁判。HFSS 是对齐基准，
本脚本在 HFSS 独立重建 Z_ALL 参考结构，仲裁 openEMS 装配列的绝对幅度。

结构定义（与 openEMS 参考轮逐位同源，几何全部经 core.mapes.pixel_board_geom
+ scripts.mapes_s2_zall.build_layout/build_geom/bleed_boxes 导入，零手抄数字）：
6×6 单层像素板（底面连续地 + rogers4350b 0.508mm + 36 浮地贴片），Q=150：
- io1/io2：竖直贴片-地集总口（HFSS lumped_port 50Ω， sheet 名传入，#263）；
- 148 个虚拟口负载：竖直口/pixel、via、对角口=贴片-地 50Ω（Lumped RLC 沿 Z），
  pixel_h/v 缝隙口=贴片间 50Ω 桥（Lumped RLC 沿缝跨轴，sheet 落贴片面 z=h）；
- 36 个 10kΩ 直流泄放（bleed_boxes 逐位复刻，Lumped RLC 沿 Z）。
HFSS 只把 io 两口设为 port，其余负载=纯边界（无激励），2 端口解。

已声明差异（判读时如实计入）：
- 缝隙负载 sheet 平铺贴片面（HFSS 集总边界的标准接法）vs openEMS 集中盒
  z∈[h/2,h]（caps=True 串电容耦合）——同 50Ω 桥语义，寄生位置二阶差异；
- HFSS Lumped RLC/Port 无串联隔直电容，openEMS LumpedPort caps=True——
  stage-4 实测带内端接 |Re Z|∈[38,57]Ω，差异计入门容差；
- 吸收边界：HFSS 辐射边界（顶+四侧）vs openEMS PML_8；域扩同为横向 6mm
  垫 + 顶 12.5mm（λ0/4 @6GHz），受控对齐。

预声明门（写死，先于任何真跑；判读常量不许跑后改）：
- 主判量 = |S11| @io1（全端口 50Ω 端接同定义），频轴 = openEMS 同款
  linspace(1,6,41) GHz；
- d = median_f( ||S11,h(f)| − |S11,oe(f)|| / max(|S11,h(f)|, 0.05) )，
  |S11,h| < 0.05 的深谷频点剔除（若全带无剔除点则全带入样）；
- 对照口径 primary = runs/mapes_s5_diag/z_all_s5.npz 的 s_cal_sym_proj
  （消费口径，followUps ⑤ 定版）；s_cal_sym 与 s4 raw 作副证；
- d ≤ 5% → AGREE；5% < d ≤ 15% → PARTIAL；> 15% → DISAGREE（附方向：
  HFSS 高/低）。S21(io1→io2)≈2e-5 近零（重度加载阻尼格栅），只作绝对
  量级旁证 median|ΔS21|（线性），不进门。
- g0 拟合：G(f)=S11,h/S11,oe（primary 口径），|g0| = median|G(f)|（带内），
  τ = unwrap(angle G) 对 2πf 最小二乘斜率（同 mask）。

产物：runs/hfss_mapes_g0/（hfss_mapes_g0.aedt、.s2p、arbitration_result.json、
本日志）。执行（工作区根目录）：
    .venv/Scripts/python.exe scripts/hfss_mapes_g0_arbitration.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
WORK_DIR = REPO / "runs" / "hfss_mapes_g0"

# ---- 预声明门（写死） -------------------------------------------------
GATE_AGREE_MAX = 0.05
GATE_PARTIAL_MAX = 0.15
S11_FLOOR = 0.05
PRIMARY_CALIBER = "s_cal_sym_proj"
OE_S5_NPZ = REPO / "runs" / "mapes_s5_diag" / "z_all_s5.npz"
OE_S4_NPZ = REPO / "runs" / "mapes_s4" / "z_all.npz"

SOLVE_TIMEOUT_S = 2400


def _load_zall_module():
    """按路径加载 scripts/mapes_s2_zall.py（scripts 非包；几何单一事实源）。"""
    path = REPO / "scripts" / "mapes_s2_zall.py"
    spec = importlib.util.spec_from_file_location("mapes_s2_zall", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_mapes_geometry(adapter) -> dict:
    """在 HFSS 中重建 MAPES Z_ALL 参考结构（6×6 像素板 + 150 口等效负载）。"""
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

    ER = mod.SUB["er"]
    TAND = mod.SUB["tan_d"]
    mat = "rfauto_mapes_rogers4350b"
    with contextlib.suppress(Exception):
        hfss.materials.add_material(
            mat, properties={"permittivity": ER,
                             "dielectric_loss_tangent": TAND})

    dx0, dy0, dx1, dy1 = geom.domain
    h = geom.sub_h_m
    air_top = h + 3e8 / 6e9 / 4.0  # 顶 λ0/4 @6GHz（与 openEMS 轮脚本同式）

    # 基板 + 地 + 贴片（零厚度 PEC sheet，#191 口径显式赋 PerfectE）
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
    # unite 保留首对象名（同几何仲裁先例 ArbTraceIn），不存在的名字会被
    # PerfectE 赋界静默吞成 "Objects or Faces selected do not exist"
    pixels_name = patch_names[0]
    modeler.unite(patch_names, keep_originals=False)

    # 端口/负载 sheet：竖直口=YZ 面竖片（z 0→h），缝隙口=贴片面 XY 桥片
    load_sheets: list[tuple[str, str, float]] = []  # (name, dir, R)
    io_sheets: list[tuple[str, int]] = []  # (name, port_number)
    for port in geom.ports:
        s, t = port.start, port.stop
        if port.kind == PORT_KIND_LUMPED_GAP:
            name = f"LoadP{port.number}" if port.slot_index >= 0 else f"IoP{port.number}"
            modeler.create_rectangle(
                orientation="XY",
                origin=[mm(s[0]), mm(s[1]), mm(h)],
                sizes=[mm(t[0] - s[0]), mm(t[1] - s[1])], name=name)
            direction = ("XPos", "YPos")[port_probe_axes(port)]
            load_sheets.append((name, direction, 50.0))
        else:  # 竖直贴片-地口
            x_c = 0.5 * (s[0] + t[0])
            if port.slot_index < 0:
                name = f"IoP{port.number}"
                io_sheets.append((name, port.number))
            else:
                name = f"LoadP{port.number}"
                load_sheets.append((name, "ZPos", 50.0))
            modeler.create_rectangle(
                orientation="YZ",
                origin=[mm(x_c), mm(s[1]), "0mm"],
                sizes=[mm(t[1] - s[1]), mm(h)], name=name)
    # 36 个 10kΩ 直流泄放（bleed_boxes 逐位；竖片过盒中心，电流沿 Z）
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

    # 空气域（横向 6mm 垫 + 顶 12.5mm 同 openEMS）→ 减去全部实体/薄片
    modeler.create_box(
        origin=[mm(dx0), mm(dy0), "0mm"],
        sizes=[mm(dx1 - dx0), mm(dy1 - dy0), mm(air_top)],
        name="Air", material="air")
    subtract_tools = ["Substrate", "Ground", pixels_name] + [
        n for n, _d, _r in load_sheets] + [n for n, _n in io_sheets]
    modeler.subtract("Air", subtract_tools)
    # 面心坐标以模型单位 mm 返回，几何常量为米制——比较前统一到 mm（首跑
    # 用米制阈值过滤得空列表 → create_boundary list index out of range）
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

    # io 两口 = 真 port（sheet 名传入，#263）
    for name, number in io_sheets:
        hfss.lumped_port(
            assignment=name, integration_line=Gravity.ZPos, impedance=50.0,
            name=f"P{number}", renormalize=True)
    return {"layout": layout, "geom": geom, "n_loads": len(load_sheets),
            "n_bleeds": len(bleeds)}


def make_setup(adapter) -> str:
    """自适应 @3.5GHz（缺省 ΔS 0.02 / ≤12 passes）+ 1-6GHz 41 点插值扫频（同频轴）。

    网格收敛自检用环境变量收紧：RFAUTO_MAPES_G0_DELTA_S /
    RFAUTO_MAPES_G0_MAX_PASSES；产物名后缀 RFAUTO_MAPES_G0_TAG。
    """
    import os

    hfss = adapter.session.hfss
    setup = hfss.create_setup(name="MapesG0Setup")
    setup.props["Frequency"] = "3.5GHz"
    setup.props["MaxDeltaS"] = float(os.environ.get("RFAUTO_MAPES_G0_DELTA_S", "0.02"))
    setup.props["MaximumPasses"] = int(os.environ.get("RFAUTO_MAPES_G0_MAX_PASSES", "12"))
    setup.update()
    hfss.create_linear_count_sweep(
        setup="MapesG0Setup", unit="GHz", start_frequency=1.0,
        stop_frequency=6.0, num_of_freq_points=41, name="MapesG0Sweep",
        sweep_type="Interpolating", save_fields=False)
    return "MapesG0Setup"


def verdict_of(d: float) -> str:
    """预声明门（写死）：d≤5% AGREE / 5–15% PARTIAL / >15% DISAGREE。"""
    if d <= GATE_AGREE_MAX:
        return "AGREE"
    if d <= GATE_PARTIAL_MAX:
        return "PARTIAL"
    return "DISAGREE"


def _interp_to(freq_ref: np.ndarray, f: np.ndarray, v: np.ndarray) -> np.ndarray:
    if freq_ref.shape == f.shape and np.allclose(freq_ref, f, rtol=1e-6, atol=1.0):
        return v
    out = np.empty(freq_ref.shape, dtype=complex)
    for i in range(v.shape[1]):
        for j in range(v.shape[2]):
            out[:, i, j] = np.interp(freq_ref, f, v[:, i, j])
    return out


def analyze(s2p: Path, passes: int, delta_s: float, version: str,
            build_info: dict, t_wall: dict) -> dict:
    """HFSS 2 口 S 对 openEMS 三口径逐位判读 + g0/τ 拟合 + 预声明门判定。"""
    import skrf

    net = skrf.Network(str(s2p))
    f_hfss = net.frequency.f.astype(float)
    s_hfss = net.s[:, :2, :2]  # (41,2,2)
    with np.load(OE_S5_NPZ) as d5:
        freq_oe = np.asarray(d5["freq_hz"], dtype=float)
        calibers = {
            "s_cal_sym_proj": np.asarray(d5["s_cal_sym_proj"]),
            "s_cal_sym": np.asarray(d5["s_cal_sym"]),
        }
    with np.load(OE_S4_NPZ) as d4:
        calibers["s4_raw"] = np.asarray(d4["s_all"])
    assert np.allclose(freq_oe, freq_oe[0] + np.arange(41) * (freq_oe[1] - freq_oe[0]))

    s11_h = np.abs(s_hfss[:, 0, 0])
    s21_h = np.abs(s_hfss[:, 1, 0])
    mask = s11_h >= S11_FLOOR
    results: dict[str, dict] = {}
    for name, s_oe in calibers.items():
        s_m = _interp_to(freq_oe, f_hfss, s_oe)
        s11_oe = np.abs(s_m[:, 0, 0])
        s21_oe = np.abs(s_m[:, 1, 0])
        rel = np.abs(s11_h - s11_oe) / np.maximum(s11_h, S11_FLOOR)
        d = float(np.median(rel[mask]))
        ratio = s_hfss[mask, 0, 0] / s_m[mask, 0, 0]
        g0_abs = float(np.median(np.abs(ratio)))
        phase = np.unwrap(np.angle(ratio))
        tau_s = float(np.polyfit(
            2.0 * np.pi * freq_oe[mask], phase, 1)[0])
        results[name] = {
            "d_s11_median_rel": d,
            "s11_hfss_band_median": float(np.median(s11_h[mask])),
            "s11_oe_band_median": float(np.median(s11_oe[mask])),
            "g0_abs": g0_abs,
            "tau_ps": tau_s * 1e12,
            "n_freq_used": int(np.count_nonzero(mask)),
            "s21_abs_delta_median_linear": float(np.median(np.abs(s21_h - s21_oe))),
            "s21_hfss_band_median": float(np.median(s21_h)),
            "s21_oe_band_median": float(np.median(s21_oe)),
        }
    primary = results[PRIMARY_CALIBER]
    verdict = verdict_of(primary["d_s11_median_rel"])
    direction = ""
    if verdict != "AGREE":
        s11_oe_p = np.abs(calibers[PRIMARY_CALIBER][:, 0, 0])
        direction = ("hfss_higher" if np.median(s11_h[mask] - s11_oe_p[mask]) > 0
                     else "hfss_lower")
    return {
        "id": "hfss_mapes_g0",
        "verdict": verdict,
        "direction": direction,
        "gate": {
            "agree_max": GATE_AGREE_MAX, "partial_max": GATE_PARTIAL_MAX,
            "s11_floor": S11_FLOOR, "metric":
                "median_f ||S11,h|-|S11,oe||/max(|S11,h|,0.05), 深谷剔除",
            "primary_caliber": PRIMARY_CALIBER,
            "primary_d": primary["d_s11_median_rel"],
        },
        "calibers": results,
        "freq_ghz": [float(freq_oe[0]) / 1e9, float(freq_oe[-1]) / 1e9],
        "n_freq": int(freq_oe.shape[0]),
        "structure": {
            "topology_key": build_info["layout"].topology_key,
            "n_ports_oe": build_info["layout"].n_ports,
            "n_hfss_ports": 2,
            "n_load_sheets": build_info["n_loads"],
            "n_bleed_sheets": build_info["n_bleeds"],
            "declared_differences": [
                "缝隙负载 sheet 平铺贴片面 vs openEMS 集中盒 z∈[h/2,h]（同 50Ω 桥语义）",
                "HFSS 集总元无串联隔直电容 vs openEMS LumpedPort caps=True",
                "吸收边界 HFSS 辐射（顶+四侧）vs openEMS PML_8；域扩同 6mm 横垫+12.5mm 顶",
                "HFSS 负载为纯边界（无激励）2 端口解，端口定义与 openEMS 50Ω 端接同义",
            ],
        },
        "passes": passes, "final_delta_s": delta_s, "aedt_version": version,
        "wall_time_s": t_wall,
    }


def _kill_desktops() -> None:
    import subprocess

    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process | Where-Object { $_.ProcessName -match "
                    "'ansysedt' } | Stop-Process -Force"], capture_output=True)
    time.sleep(3)


def main() -> int:
    for attempt in range(2):
        try:
            if attempt:
                _kill_desktops()
            return _run()
        except Exception as exc:
            print(f"attempt {attempt + 1}/2 FAIL: {exc}", flush=True)
    print("ARB_FAIL_AFTER_ATTEMPTS")
    return 1


def _run() -> int:
    import shutil

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    # 失败尝试残留的 .aedt 会被 open_or_create 打开而与同名新建对象冲突
    # （同几何仲裁先例每轮 rmtree）；只清项目文件，日志/判读留存
    for stale in WORK_DIR.glob("hfss_mapes_g0.aedt*"):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        else:
            stale.unlink(missing_ok=True)
    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.infra.version_probe import resolve_aedt_install

    install = resolve_aedt_install(None)
    assert install is not None, "未发现可用 AEDT 安装"
    version = install["aedt_version"]

    adapter = HfssAdapter()
    adapter.connect({"desktop_version": version, "non_graphical": True})
    try:
        t0 = time.time()
        adapter.open_or_create_project(
            WORK_DIR / "hfss_mapes_g0.aedt", "mapes_g0")
        build_info = build_mapes_geometry(adapter)
        t_build = time.time() - t0
        print(f"[build] done {t_build:.0f}s loads={build_info['n_loads']} "
              f"bleeds={build_info['n_bleeds']}", flush=True)

        setup_name = make_setup(adapter)
        t1 = time.time()
        report = adapter.solve(setup_name, timeout_s=SOLVE_TIMEOUT_S)
        t_solve = time.time() - t1
        assert report.success, f"求解失败: {report.message}"
        passes, delta_s = 0, 0.0
        with contextlib.suppress(Exception):
            setup = adapter.session.hfss.get_setup(setup_name)
            if setup is not None:
                passes, delta_s = HfssAdapter._extract_convergence(setup)
        print(f"[solve] {t_solve:.0f}s passes={passes} dS={delta_s:.4f}",
              flush=True)

        import os

        tag = os.environ.get("RFAUTO_MAPES_G0_TAG", "")
        suffix = ("_" + tag) if tag else ""
        s2p = adapter.export_touchstone(WORK_DIR / f"hfss_mapes_g0{suffix}.s2p")
        res = analyze(Path(s2p), passes, delta_s, version, build_info,
                      {"build_s": round(t_build, 1), "solve_s": round(t_solve, 1)})
        res["setup"] = {"max_delta_s": float(os.environ.get("RFAUTO_MAPES_G0_DELTA_S", "0.02")),
                        "max_passes": int(os.environ.get("RFAUTO_MAPES_G0_MAX_PASSES", "12")),
                        "tag": tag}
        out_name = f"arbitration_result{suffix}.json"
        (WORK_DIR / out_name).write_text(
            json.dumps(res, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        print(json.dumps({k: res[k] for k in
                          ("verdict", "direction", "calibers")},
                         ensure_ascii=False, indent=1), flush=True)
        print(f"MAPES_G0_VERDICT_{res['verdict']}", flush=True)
        return 0
    finally:
        adapter.close(save=True)


if __name__ == "__main__":
    sys.exit(main())
