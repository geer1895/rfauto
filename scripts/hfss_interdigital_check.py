"""interdigital 全波分歧 HFSS 对拍复核（判读门先于求解落盘）。

仲裁问题（runs/hfss_interdigital_check/criteria.md §〇）：
  c3 interdigital 全波哨外推 S21∞@f0=−14.4657dB（帽停不可信）vs 电路裁判
  C-pass 带心 2.5000GHz / S21@f0≈0dB——HFSS 全波站哪边。
  主门 M1：|S21_hfss@2.5 − 参考甲(0.000)| ≤0.5dB → AGREE_CIRCUIT；
           |S21_hfss@2.5 − 参考乙(−14.4657)| ≤0.5dB → AGREE_SENTINEL；
           其余 SPLIT；无合格收敛解 UNDECIDED。副门 S1 只旁证不翻案。

建模铁律逐条落地（criteria.md §〇 同文 + audit2_criteria.md §四审计结论）：
  真实三维过孔圆柱（#264 反面；接触键合经 audit2 eigen 证据链核实正常）；
  零厚导体 PerfectE（#356①）；Driven Modal
  （#356② 反面）；波端口官方微带口径 5w×4h（#192）；收敛三级阶梯 ΔS
  0.02→0.01→0.005、触 max_passes 的解不进判读（#335①）；几何预审计逐对象
  bounding_box ±1e-6mm + 耦合缝 + 端口面（#310④/#285①/#191）；
  finally release_desktop（#265）；解前 fail-closed 查存量 ansysedt
  （#265/#245：只报错不代杀）。
几何单源：rfauto.adapters.openems_templates._c3_layout（#212，米→mm），
  参数=TEMPLATE_NOMINAL["interdigital"]（注册 4 位舍入值=重设计名义，
  redesign_nominals.json matches_registered_nominal=true）。

用法（cwd=仓库根；venv=.venv\\Scripts\\python.exe）：
  python scripts/hfss_interdigital_check.py --audit    # 离线：布局+域+端口表
  python scripts/hfss_interdigital_check.py --solve    # HFSS 真跑（含审计）
  python scripts/hfss_interdigital_check.py --judge    # 离线判读（读 s2p）
  python scripts/hfss_interdigital_check.py --all      # solve + judge
退出码：audit 0；solve 0=三阶梯全解出；judge 0=verdict 非 UNDECIDED。
"""
from __future__ import annotations

import argparse
import itertools
import json
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

OUT = REPO / "runs" / "hfss_interdigital_check"
CRITERIA = OUT / "criteria.md"

# ── 域与端口（criteria.md §〇 预声明值；禁 solve 中改） ─────────────────────
AEDT_VERSION = "2025.1"
ER = 3.66
TAND = 0.0037
H_MM = 0.508
SUB_X_HALF = 20.0            # 基板 x∈[−20,20]
SUB_Y = (-60.0, 25.0)        # 基板 y（板边=端口面在 −60）
AIR_MARGIN = 25.0            # x/侧向/top 辐射缓冲 ≈λ0/4@3GHz
AIR_X_HALF = SUB_X_HALF + AIR_MARGIN
AIR_Y = (SUB_Y[0], SUB_Y[1] + AIR_MARGIN)
PORT_W_FACTOR = 5.0          # 官方微带波端口口径（#192 PASS_A）
PORT_H_FACTOR = 4.0
SETUP_LADDER = ((0.02, 15), (0.01, 20), (0.005, 25))  # (MaxDeltaS, MaxPasses)
SWEEP_GHZ = (2.35, 2.70)
SWEEP_POINTS = 141           # 步进 2.5MHz，含 2.5 精确点（2.35+60·0.0025）
SOLVE_TIMEOUT_S = 21600      # 单 setup 看门狗（6h 防挂死上限，非预算门：
                             # Setup2 实测 4h59m=20 passes 重网格尾+扫频，
                             # 机器被并行轨争用再放大；80min 级看门狗必误杀）
BUILD_ATTEMPTS = 2           # 整轮重建重试（#191 anchors 同款）
GAP_TOL_MM = 1e-6

# audit2（2026-09-23/24，runs/hfss_interdigital_check/_audit2/）过孔接触结论：
# 全模型（缺省网格）bars_only eigen=2.485/2.607/2.692GHz 三棒耦合簇——原构型
# 共面顶盘-薄片键合正常（棒短路），建模段零改动；单棒小盒四变体（原构型+网格
# 指派/pad±网格指派）均 5.2/4.4GHz λ/2 悬空口径且无 λ/4 模——共面键合是网格
# 路径依赖的（audit 教训：HFSS eigen 探针禁对共面薄片+实体强制同网格加密）；
# 穿片伸出 0.05mm 三变体全数 "Error in Solving Setup"（片-实体交叉校验非法）。
# 上轮阶梯 UNDECIDED 的根因不是建模缺陷，而是几何值域（过孔电感过补偿/耦 合
# 缝与馈耦合语义）+高 Q 弱耦模的本征收敛难度——几何值归设计链轨（#154/SC）。

# ── 冻结参考值（criteria.md §一；先于求解写死） ─────────────────────────────
S21_CIRC_DB = 0.0            # 电路裁判 @2.5GHz（本轮离线重算冻结）
S21_SENTINEL_DB = -14.4657   # 哨外推 s21_f0.s_inf_db（stage1_summary 原文）
M1_GATE_DB = 0.5
F0_GHZ = 2.5
S1_WINDOW_PCT = 0.02         # 副门 S1a 谷位窗 f0±2%
S1_DEEP_DB = -20.0           # S1b circuit 侧旁证（RL 纹波电平）
S1_SHALLOW_DB = -6.0         # S1b sentinel 侧旁证
PASSIVITY_MAX = 1.02

_BBOX_TOL_MM = 1e-6


# ── 布局（几何单源 _c3_layout；离线 --audit 可测） ───────────────────────────


def layout_mm() -> dict:
    """注册名义 → _c3_layout（米）→ mm dict（单源，禁手算 #252）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, _c3_layout

    nom = TEMPLATE_NOMINAL["interdigital"]
    lay = _c3_layout("interdigital", dict(nom))
    mm = 1e3
    return {
        "nominal": nom,
        "w": lay["w_bar"] * mm,
        "res_len": lay["res_len"] * mm,
        "gaps": [g * mm for g in lay["gaps"]],
        "feed_len": lay["feed_len"] * mm,
        "board": lay["board"] * mm,
        "y1": lay["y1"] * mm,
        "y_top": lay["y_top"] * mm,
        "xs": [x * mm for x in lay["xs"]],
        "r_via": lay["r_via"] * mm,
        "vias": [(x * mm, y * mm) for x, y in lay["vias"]],
        "boxes": [(n, x0 * mm, y0 * mm, x1 * mm, y1m * mm)
                  for (x0, y0, x1, y1m), n in zip(lay["boxes"],
                                                  lay["box_names"],
                                                  strict=True)],
    }


def port_specs(lay: dict) -> list[dict]:
    """两波端口规格（官方 5w×4h，积分线 trace 心 z=h→z=0）。"""
    specs = []
    for k, name in ((0, "P1"), (4, "P4")):
        xc = lay["xs"][k]
        specs.append({
            "name": name,
            "x_center": xc,
            "x0": xc - PORT_W_FACTOR * lay["w"] / 2.0,
            "width": PORT_W_FACTOR * lay["w"],
            "height": PORT_H_FACTOR * H_MM,
            "y": SUB_Y[0],
        })
    return specs


# ── HFSS 构造（真跑） ────────────────────────────────────────────────────────


def _assert_existing_desktops_none() -> None:
    """fail-closed：存量 ansysedt 一律拒跑（不代杀，#245 核对命令行纪律）。"""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process ansysedt -ErrorAction SilentlyContinue).Count"],
        capture_output=True, text=True)
    n = (r.stdout or "0").strip()
    if n and n != "0":
        raise RuntimeError(
            f"检测到 {n} 个存量 ansysedt 进程——按 #265/#245 纪律不代杀，"
            f"先人工核对命令行处置后再跑（防误杀他轨合法桌面）")


def _bbox(h, name: str) -> list[float]:
    return [float(v) for v in h.modeler[name].bounding_box]  # pyaedt 1.x per-object property（#253②）


def _audit_bbox(name: str, bb: list[float], exp: tuple[float, ...]) -> None:
    for v, e in zip(bb, exp, strict=True):
        if abs(v - e) > _BBOX_TOL_MM:
            raise AssertionError(
                f"{name} bounding_box {bb} != 期望 {list(exp)} "
                f"(tol {_BBOX_TOL_MM}mm)——几何错误 solve 前拦下（#310④）")


def _build_and_solve() -> dict:
    """整轮会话重试包装（#191：gRPC 通道级不稳定，单调用重试无效——
    anchors 同款：整轮重建重来；中间产物目录先清再建）。"""
    last_exc: Exception | None = None
    for attempt in range(1, BUILD_ATTEMPTS + 1):
        proj = OUT / "project"
        if proj.exists():
            shutil.rmtree(proj)
        try:
            return _build_and_solve_once()
        except Exception as exc:
            last_exc = exc
            print(f"[ic] build attempt {attempt}/{BUILD_ATTEMPTS} FAIL: "
                  f"{exc}", flush=True)
    raise last_exc  # type: raise[ValueError]


def _build_and_solve_once() -> dict:
    """构造+预审计+三级 ΔS 阶梯求解+逐级导出（单会话，finally 释放）。"""
    from ansys.aedt.core import Hfss

    from rfauto.adapters.hfss_adapter import HfssAdapter, touchstone_path_for_ports

    _assert_existing_desktops_none()
    lay = layout_mm()
    specs = port_specs(lay)
    proj_dir = OUT / "project"
    proj_dir.mkdir(parents=True, exist_ok=True)
    h = Hfss(project=str(proj_dir / "interdigital_check.aedt"),
             design="interdigital_check", version=AEDT_VERSION,
             non_graphical=True, new_desktop=True)
    result: dict = {"started_utc": datetime.now(UTC).isoformat(),
                    "setups": []}
    try:
        h.modeler.model_units = "mm"
        h.materials.add_material("rfauto_m366_chk", properties={
            "permittivity": ER, "dielectric_loss_tangent": TAND})

        # 基板
        h.modeler.create_box(
            origin=[f"{-SUB_X_HALF}mm", f"{SUB_Y[0]}mm", "0mm"],
            sizes=[f"{2 * SUB_X_HALF}mm", f"{SUB_Y[1] - SUB_Y[0]}mm",
                   f"{H_MM}mm"], name="Sub", material="rfauto_m366_chk")
        h.modeler["Sub"].solve_inside = True

        # 顶层导体（z=h 零厚片；XY 面 normal=Z → sizes=(X,Y)，#310④ 审计兜底）
        metal_names = []
        for nm, x0, y0, x1, y1 in lay["boxes"]:
            h.modeler.create_rectangle(
                orientation="XY", origin=[f"{x0}mm", f"{y0}mm", f"{H_MM}mm"],
                sizes=[f"{x1 - x0}mm", f"{y1 - y0}mm"], name=nm)
            metal_names.append(nm)
        # 地（z=0 全气盒足迹）
        h.modeler.create_rectangle(
            orientation="XY", origin=[f"{-AIR_X_HALF}mm", f"{AIR_Y[0]}mm",
                                      "0mm"],
            sizes=[f"{2 * AIR_X_HALF}mm", f"{AIR_Y[1] - AIR_Y[0]}mm"],
            name="Gnd")
        for nm in [*metal_names, "Gnd"]:
            h.assign_perfecte_to_sheets(assignment=[nm], name=f"PEC_{nm}")

        # 三维过孔（真实圆柱，交替接地；#264 反面；接触证据链见文件头 audit2 节）
        via_names = []
        for k, (vx, vy) in enumerate(lay["vias"], start=1):
            nm = f"via{k}"
            h.modeler.create_cylinder(
                orientation="Z", origin=[f"{vx}mm", f"{vy}mm", "0mm"],
                radius=f"{lay['r_via']}mm", height=f"{H_MM}mm", name=nm,
                material="pec")
            via_names.append(nm)

        # 空气盒 + subtract 基板
        h.modeler.create_box(
            origin=[f"{-AIR_X_HALF}mm", f"{AIR_Y[0]}mm", "0mm"],
            sizes=[f"{2 * AIR_X_HALF}mm", f"{AIR_Y[1] - AIR_Y[0]}mm",
                   f"{H_MM + AIR_MARGIN}mm"], name="Air", material="vacuum")
        h.modeler.subtract("Air", ["Sub"])
        h.modeler["Air"].solve_inside = True

        # 辐射边界：5 外表面（x±/y−/y+/z 顶；z 底由 Gnd 片承担）
        # 面过滤 mm 口径 + 非空守卫（#285①）；gRPC 单点读抖动重试（#191）
        tol = 1e-4  # mm；域常量为精确十进制，0.1µm 容差远低于任何真实歧义

        def _classify_air_faces() -> tuple[list[int], list[list[float]]]:
            faces = h.modeler.get_object_faces("Air")
            assert faces, "Air 无面可取（#285① 非空守卫）"
            centers = []
            rad: list[int] = []
            for f_id in faces:
                cx, cy, cz = (float(v)
                              for v in h.modeler.get_face_center(f_id))
                centers.append([f_id, cx, cy, cz])
                on_outer = (
                    abs(abs(cx) - AIR_X_HALF) < tol
                    or abs(cy - AIR_Y[0]) < tol
                    or abs(cy - AIR_Y[1]) < tol
                    or abs(cz - (H_MM + AIR_MARGIN)) < tol)
                on_bottom = abs(cz) < tol
                if on_outer and not on_bottom:
                    rad.append(f_id)
            return rad, centers

        rad_faces = []
        centers: list[list[float]] = []
        for attempt in range(3):
            rad_faces, centers = _classify_air_faces()
            if len(rad_faces) == 5:
                break
            print(f"[ic][warn] 辐射面过滤 attempt {attempt}: "
                  f"{len(rad_faces)}/5（gRPC 读抖动重试 #191）", flush=True)
            time.sleep(3)
        if len(rad_faces) != 5:
            raise AssertionError(
                f"辐射面过滤得 {len(rad_faces)} 面（期望 5：x±/y−/y+/顶）"
                f"——面中心全表 {centers}（#285①）")
        h.assign_radiation_boundary_to_faces(assignment=rad_faces, name="Rad")

        # 波端口×2（板边 y=−60，官方 5w×4h，积分线 trace→地）
        for sp in specs:
            nm = f"{sp['name']}sheet"
            h.modeler.create_rectangle(
                orientation="ZX",
                origin=[f"{sp['x0']}mm", f"{sp['y']}mm", "0mm"],
                sizes=[f"{sp['height']}mm", f"{sp['width']}mm"], name=nm)
            faces = h.modeler.get_object_faces(nm)
            assert faces, f"{nm} 无面可取（#285① 非空守卫）"
            fc = [float(v) for v in h.modeler.get_face_center(faces[0])]
            assert abs(fc[0] - sp["x_center"]) <= 1e-6 and \
                abs(fc[1] - sp["y"]) <= 1e-6 and \
                abs(fc[2] - sp["height"] / 2) <= 1e-6, (
                f"{nm} face center {fc} != 期望 x={sp['x_center']} "
                f"y={sp['y']} z={sp['height'] / 2}（mm 口径 #285①）")
            h.wave_port(assignment=faces[0], name=nm + "P", impedance=50.0,
                        renormalize=True, modes=1,
                        integration_line=[
                            [sp["x_center"], sp["y"], H_MM],
                            [sp["x_center"], sp["y"], 0.0]])

        # ── 几何预审计（#310④ bounding_box 全表；#191 端口面=域边界） ──
        audit: dict = {"objects": {}, "gaps_mm": {}, "ports": []}
        for nm, x0, y0, x1, y1 in lay["boxes"]:
            _audit_bbox(nm, _bbox(h, nm), (x0, y0, H_MM, x1, y1, H_MM))
            audit["objects"][nm] = _bbox(h, nm)
        _audit_bbox("Gnd", _bbox(h, "Gnd"),
                    (-AIR_X_HALF, AIR_Y[0], 0.0, AIR_X_HALF, AIR_Y[1], 0.0))
        audit["objects"]["Gnd"] = _bbox(h, "Gnd")
        for k, (vx, vy) in enumerate(lay["vias"], start=1):
            exp = (vx - lay["r_via"], vy - lay["r_via"], 0.0,
                   vx + lay["r_via"], vy + lay["r_via"], H_MM)
            _audit_bbox(f"via{k}", _bbox(h, f"via{k}"), exp)
            audit["objects"][f"via{k}"] = _bbox(h, f"via{k}")
        # 耦合缝（耦合强度敏感量，逐缝核对）
        boxes = lay["boxes"]
        for j in range(len(boxes) - 1):
            gap = boxes[j + 1][1] - boxes[j][3]
            if abs(gap - lay["gaps"][j]) > GAP_TOL_MM:
                raise AssertionError(
                    f"缝 {j} 实测 {gap:.9f}mm != 设计 {lay['gaps'][j]:.9f}mm")
            audit["gaps_mm"][f"j{j}"] = gap
        # 端口面=域外边界（#191：空气盒 y− 与端口面齐平）
        air_bb = _bbox(h, "Air")
        assert abs(air_bb[1] - SUB_Y[0]) <= _BBOX_TOL_MM, (
            f"Air ymin={air_bb[1]} != 端口面 {SUB_Y[0]}——端口变内部端口"
            f"（#191 solve 必败）")
        for sp in specs:
            fb = _bbox(h, f"feed{0 if sp['name'] == 'P1' else 4}_50")
            assert abs(fb[1] - SUB_Y[0]) <= _BBOX_TOL_MM, (
                f"{sp['name']} 馈线未贯通到端口面（开路 stub 风险 #174 族）")
            audit["ports"].append({"spec": sp})
        audit["air_bbox_mm"] = air_bb
        audit["L_span_note"] = "端口面=板边 y=-60（几何贯通由 bbox 审计钉住）"

        # ── 三级 ΔS 阶梯（#335①） ──
        adapter = HfssAdapter()
        adapter.session.hfss = h
        for i, (mds, mp) in enumerate(SETUP_LADDER, start=1):
            su = h.create_setup(name=f"Setup{i}")
            su.props["Frequency"] = f"{F0_GHZ}GHz"
            su.props["MaxDeltaS"] = mds
            su.props["MaximumPasses"] = mp
            su.update()
            h.create_linear_count_sweep(
                setup=f"Setup{i}", unit="GHz", start_frequency=SWEEP_GHZ[0],
                stop_frequency=SWEEP_GHZ[1], num_of_freq_points=SWEEP_POINTS,
                name=f"Sweep{i}", sweep_type="Discrete", save_fields=False)
            t0 = time.time()
            box: dict = {"done": False, "err": None}

            def _go(su_i: int = i, bx: dict = box) -> None:
                try:
                    h.analyze(setup=f"Setup{su_i}")
                    bx["done"] = True
                except Exception as exc:
                    bx["err"] = repr(exc)

            th = threading.Thread(target=_go, daemon=True)
            th.start()
            th.join(timeout=SOLVE_TIMEOUT_S)
            solve_s = round(time.time() - t0, 1)
            if not box["done"]:
                raise RuntimeError(
                    f"Setup{i} solve 看门狗超时（>{SOLVE_TIMEOUT_S}s）"
                    f" err={box['err']}")
            conv: dict = {}
            with contextlib_suppress():
                st = h.setups[i - 1]
                passes, delta_s = HfssAdapter._extract_convergence(st)
                conv = {"adaptive_passes": passes, "final_delta_s": delta_s,
                        "max_delta_s": mds, "max_passes": mp,
                        "touched_cap": bool(passes >= mp)}
            row = {"setup": f"Setup{i}", "max_delta_s": mds,
                   "max_passes": mp, "solve_s": solve_s,
                   "convergence": conv, "s2p": None, "export_error": None}
            for exp_attempt in (1, 2):  # 导出小重试（瞬态 gRPC 读抖动 #191）
                try:
                    s2p = OUT / f"setup{i}.s2p"
                    adapter.assert_sweep_completed(f"Setup{i}", f"Sweep{i}")
                    n_ports = HfssAdapter._design_port_count(h)
                    s2p = touchstone_path_for_ports(s2p, n_ports)
                    adapter._direct_export_touchstone(
                        h, f"Setup{i}", f"Sweep{i}", s2p)
                    assert s2p.exists(), "touchstone 导出未生成"
                    row["s2p"] = str(s2p)
                    break
                except Exception as exc:
                    row["export_error"] = repr(exc)[:300]
                    print(f"[ic][warn] Setup{i} export attempt "
                          f"{exp_attempt} FAIL: {exc}", flush=True)
                    time.sleep(5)
            result["setups"].append(row)
            print(f"[ic] Setup{i} done：solve={solve_s}s conv={conv} "
                  f"s2p={row['s2p']}", flush=True)
        result["ok"] = True
        return result
    finally:
        (OUT / "solve_record.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1),
            encoding="utf-8")
        # 释放带 150s 上限：看门狗超时后 release_desktop 会对求解中的桌面
        # 阻塞到求解自然结束（attempt1 实测阻塞 3.6h）——超时不候，如实
        # 记孤儿风险交人工按 #265/#245 处置
        rel_box: dict = {"done": False}

        def _rel() -> None:
            try:
                h.release_desktop(close_projects=True, close_desktop=True)
            except Exception as exc:  # #265：释放失败必须透出
                print(f"[ic][warn] release_desktop 失败（孤儿 ansysedt 风险"
                      f"#265）：{exc}", flush=True)
            rel_box["done"] = True

        rel_th = threading.Thread(target=_rel, daemon=True)
        rel_th.start()
        rel_th.join(timeout=150)
        if not rel_box["done"]:
            print("[ic][warn] release_desktop >150s 未返回（桌面疑似仍在"
                  "求解）——不再等待，孤儿 ansysedt 留待 #265/#245 人工"
                  "核对命令行后处置", flush=True)


class contextlib_suppress:
    """contextlib.suppress(Exception) 的最小内联替身（避免多余 import）。"""

    def __enter__(self) -> contextlib_suppress:
        return self

    def __exit__(self, *exc_info) -> bool:
        return True


# ── 判读（离线；读 setup{i}.s2p） ────────────────────────────────────────────


def _curve(net) -> dict:
    f = net.f / 1e9
    s11 = net.s[:, 0, 0]
    s21 = net.s[:, 1, 0]
    s11_db = 20 * np.log10(np.abs(s11) + 1e-30)
    s21_db = 20 * np.log10(np.abs(s21) + 1e-30)

    def at_db(curve_db: np.ndarray, fg: float) -> float:
        i = int(np.argmin(np.abs(f - fg)))
        return float(curve_db[i])

    # S1a 谷位：[f0±2%] 内 |S11| 最小
    win = (f >= F0_GHZ * (1 - S1_WINDOW_PCT)) & \
        (f <= F0_GHZ * (1 + S1_WINDOW_PCT))
    w_idx = np.where(win)[0]
    v_i = int(w_idx[int(np.argmin(s11_db[w_idx]))]) if w_idx.size else -1
    # −3dB 带（线性插值跨零；带心口径 #298 禁 argmax）
    edges = _band_edges(f, s21_db)
    # |S21| 峰位（记录项）
    peaks = _peaks(f, s21_db)
    passive = float(np.max(np.abs(s11) ** 2 + np.abs(s21) ** 2))
    return {
        "f0_ghz": F0_GHZ,
        "s21_db_at_f0": at_db(s21_db, F0_GHZ),
        "s11_db_at_f0": at_db(s11_db, F0_GHZ),
        "s11_valley": ({"f_ghz": float(f[v_i]),
                        "db": float(s11_db[v_i])} if v_i >= 0 else None),
        "band_3db": edges,
        "s21_peaks_ghz": peaks,
        "passivity_max": passive,
        "n_points": int(f.size),
        "freq_span_ghz": [float(f[0]), float(f[-1])],
    }


def _band_edges(f: np.ndarray, s21_db: np.ndarray) -> dict | None:
    above = s21_db > -3.0
    ic = int(np.argmin(np.abs(f - F0_GHZ)))
    if not above[ic]:
        return None
    lo = hi = None
    for i in range(ic, 0, -1):
        if not above[i - 1]:
            x0, x1 = f[i - 1], f[i]
            y0, y1 = s21_db[i - 1], s21_db[i]
            lo = float(x0 + (x1 - x0) * (-3.0 - y0) / (y1 - y0))
            break
    for i in range(ic, len(f) - 1):
        if not above[i + 1]:
            x0, x1 = f[i], f[i + 1]
            y0, y1 = s21_db[i], s21_db[i + 1]
            hi = float(x0 + (x1 - x0) * (-3.0 - y0) / (y1 - y0))
            break
    if lo is None or hi is None:
        return None
    return {"lo_ghz": lo, "hi_ghz": hi,
            "center_ghz": (lo + hi) / 2.0,
            "bw_pct": (hi - lo) / F0_GHZ * 100.0}


def _peaks(f: np.ndarray, s21_db: np.ndarray) -> list[dict]:
    import scipy.signal as ss

    idx, _ = ss.find_peaks(s21_db, prominence=1.0)
    out = []
    for i in idx:
        out.append({"f_ghz": float(f[i]), "db": float(s21_db[i])})
    return out


def _eligible(conv: dict | None) -> bool:
    """判读资格（criteria.md 勘误节，#335① 原文语义）：
    final_delta_s ≤ 该级目标即收敛合格（触顶但达标者合格；触顶未达标者
    不合格——'触 max_passes 未收敛的解不进判读'）。"""
    if not conv:
        return False
    return (float(conv.get("final_delta_s", 1.0))
            <= float(conv.get("max_delta_s", 0.0)))


def _ladder_saturated(s21_values: list[float]) -> tuple[bool, dict]:
    """#335① 关键标量饱和校验（criteria.md 勘误节）：相邻级差 ≤0.2dB 且
    末两级差 ≤0.1dB。少于两级 → 不可判定饱和（False）。"""
    if len(s21_values) < 2:
        return False, {"reason": "阶梯不足两级，饱和性不可判定"}
    adj = [abs(b - a) for a, b in itertools.pairwise(s21_values)]
    last = abs(s21_values[-1] - s21_values[-2])
    ok = max(adj) <= 0.2 and last <= 0.1
    return ok, {"adjacent_db": adj, "last_two_db": last}


def run_judge() -> dict:
    solve_rec: dict = {}
    rec_path = OUT / "solve_record.json"
    if rec_path.exists():
        solve_rec = json.loads(rec_path.read_text(encoding="utf-8"))
    curves: dict = {}
    for row in solve_rec.get("setups", []):
        if not row.get("s2p"):
            continue
        s2p = Path(row["s2p"])
        if not s2p.exists():
            continue
        import skrf as rf

        net = rf.Network(str(s2p))
        assert net.s.shape[1] == 2 and net.s.shape[2] == 2, (
            f"{s2p}: 非标准 2 端口 s2p（shape={net.s.shape}）")
        curves[row["setup"]] = {"conv": row.get("convergence"),
                                "solve_s": row.get("solve_s"),
                                "curve": _curve(net)}
    verdict: dict = {
        "schema": "hfss_interdigital_check/1",
        "generated_utc": datetime.now(UTC).isoformat(),
        "criteria": str(CRITERIA),
        "references": {"circuit_s21_db_at_f0": S21_CIRC_DB,
                       "sentinel_s21_inf_db_at_f0": S21_SENTINEL_DB,
                       "m1_gate_db": M1_GATE_DB},
        "curves": curves,
    }
    eligible = [k for k, c in sorted(curves.items())
                if _eligible(c["conv"])]
    # 饱和账只取判读合格级（final_delta_s 达标者）：未达标级的偏移是收敛
    # 攀爬的预期形态，不构成对判读解的反证；但合格级须 ≥2（单 ΔS 点不可
    # 验关键标量稳定性——#335① lange 单点教训）
    sat_vals = [curves[k]["curve"]["s21_db_at_f0"] for k in eligible]
    sat_ok, sat_detail = _ladder_saturated(sat_vals)
    verdict["ladder_s21_at_f0_all"] = [
        {"setup": k, "s21_db_at_f0": curves[k]["curve"]["s21_db_at_f0"],
         "eligible": _eligible(curves[k]["conv"])}
        for k in sorted(curves.keys())]
    verdict["ladder_s21_at_f0"] = sat_vals
    verdict["ladder_saturation"] = {"pass": sat_ok, "detail": sat_detail,
                                    "n_eligible": len(eligible),
                                    "rule": ("合格级相邻差≤0.2dB 且末两级"
                                             "≤0.1dB，合格级≥2"
                                             "（criteria.md 勘误节，#335①）")}
    if not eligible:
        verdict["verdict"] = "UNDECIDED"
        verdict["reason"] = (
            "无合格收敛解（各级 final_delta_s 均未达该级目标 ΔS）——"
            "#335① 触顶未收敛解不进判读")
    elif not sat_ok:
        verdict["verdict"] = "UNDECIDED"
        verdict["reason"] = (
            f"阶梯关键标量 S21@f0 未饱和 {sat_detail}——判读解不可采信"
            f"（#335① 关键标量账，lange S31 随 ΔS 移 0.8dB 教训）")
    else:
        pick = eligible[-1]
        c = curves[pick]["curve"]
        s21 = c["s21_db_at_f0"]
        d_circ = abs(s21 - S21_CIRC_DB)
        d_sent = abs(s21 - S21_SENTINEL_DB)
        verdict["judged_setup"] = pick
        verdict["s21_db_at_f0"] = s21
        verdict["delta_vs_circuit_db"] = d_circ
        verdict["delta_vs_sentinel_db"] = d_sent
        if d_circ <= M1_GATE_DB:
            verdict["verdict"] = "AGREE_CIRCUIT"
        elif d_sent <= M1_GATE_DB:
            verdict["verdict"] = "AGREE_SENTINEL"
        else:
            verdict["verdict"] = "SPLIT"
        # 副门 S1（只旁证）
        v = c["s11_valley"]
        s1a = None
        if v is not None:
            s1a = abs(v["f_ghz"] - F0_GHZ) / F0_GHZ <= S1_WINDOW_PCT
        s11f0 = c["s11_db_at_f0"]
        verdict["secondary"] = {
            "s1a_valley_pos_pass": s1a,
            "s1b_depth": ("circuit_side" if s11f0 <= S1_DEEP_DB else
                          "sentinel_side" if s11f0 >= S1_SHALLOW_DB
                          else "between"),
            "passivity_ok": c["passivity_max"] <= PASSIVITY_MAX,
        }
    (OUT / "verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
    return verdict


def run_audit() -> int:
    lay = layout_mm()
    print("===== 布局（_c3_layout 单源，mm） =====")
    for k in ("w", "res_len", "gaps", "feed_len", "y1", "y_top", "xs",
              "r_via", "vias"):
        print(f"{k}: {lay[k]}")
    for nm, x0, y0, x1, y1 in lay["boxes"]:
        print(f"  {nm:10s} [{x0:.6f},{y0:.4f}] -> [{x1:.6f},{y1:.4f}]")
    print("===== 域/端口/阶梯（criteria.md §〇 冻结值） =====")
    print(f"Sub x±{SUB_X_HALF} y{SUB_Y} z[0,{H_MM}]; "
          f"Air x±{AIR_X_HALF} y{AIR_Y} z[0,{H_MM + AIR_MARGIN}]")
    for sp in port_specs(lay):
        print(f"  port {sp['name']}: x0={sp['x0']:.6f} w={sp['width']:.4f} "
              f"h={sp['height']:.4f}")
    print(f"ladder: {SETUP_LADDER}; sweep {SWEEP_GHZ} {SWEEP_POINTS} pts")
    print(f"refs: circuit {S21_CIRC_DB} dB / sentinel {S21_SENTINEL_DB} dB "
          f"(gate ±{M1_GATE_DB})")
    assert CRITERIA.exists(), f"判读门未落盘：{CRITERIA}"
    print(f"criteria: {CRITERIA} OK（先于求解落盘）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="interdigital 全波分歧 HFSS 对拍复核（判读门先落盘）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--audit", action="store_true",
                   help="离线：布局+域+端口+参考值表（无 HFSS）")
    g.add_argument("--solve", action="store_true", help="HFSS 真跑")
    g.add_argument("--judge", action="store_true",
                   help="离线判读（读 setup*.s2p → verdict.json）")
    g.add_argument("--all", action="store_true", help="solve + judge")
    args = ap.parse_args(argv)
    if args.audit:
        return run_audit()
    if args.solve or args.all:
        assert CRITERIA.exists(), (
            f"判读门未落盘不得开解（#122）：{CRITERIA}")
        res = _build_and_solve()
        if not res.get("ok"):
            print("[ic] solve 未完成（见 solve_record.json）")
            return 1
    if args.judge or args.all:
        v = run_judge()
        print("\n===== interdigital HFSS 对拍 verdict =====")
        print(f"verdict = {v['verdict']}")
        if v.get("s21_db_at_f0") is not None:
            print(f"judged {v['judged_setup']}: S21@2.5="
                  f"{v['s21_db_at_f0']:.4f} dB "
                  f"(Δcircuit={v['delta_vs_circuit_db']:.4f} "
                  f"Δsentinel={v['delta_vs_sentinel_db']:.4f})")
        if "secondary" in v:
            print(f"secondary: {v['secondary']}")
        return 0 if v["verdict"] != "UNDECIDED" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
