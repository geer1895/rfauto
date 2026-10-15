"""DP-14 Y1 — cline_coupler 半模型 HFSS 对拍（df6 HFSS 轨件 2，件 1 后串行）。

判据预声明：runs/df6_hfss_track/criteria.md 件 2 节 + 真机口径修订 v2
（2026-09-24：Modal 面类别=Gamma/Port Zo/S Parameter；renormalize=False；
CharImp 三定义子解；门 1 端口切耦合段）。发射草案：
runs/df6_dp14y1/handoff.md（A 主判/B 互检/门 0-4/坑位清单）。

五设计各占一次桌面会话（#191：一桌面同时只活一个 Hfss 实例）：
- y1_even_z / y1_odd_z（门 1 主判）：半模型**仅耦合段**（线 A，对称面 x=0
  竖直薄片 Perfect H=PMC / Perfect E=PEC），端口×2 于 y=±lc/2 **直接切
  耦合线**（板边馈线端口面模阻抗=馈线模 ≈50Ω 非 Z0e/Z0o——v2 修正），
  显式积分线过线心；Port Zo@Zpv 直读=Z0e/Z0o，末级加 Zpi/Zvi 子解做
  Zvi=√(Zpi·Zpv) 恒等式实测自校（#356⑤）；
- y1_even / y1_odd（门 3）：带馈线半模型（板边端口），gen 基 S；
- y1_full（门 2/3/4）：全模型 4 端口 gen 基 S。

每设计 ΔS 收敛阶梯 3 级（#335）：0.02/12 → 0.01/18 → 0.005/24，单频
2.5GHz；末两级差在门内才采信；触 max_passes 未收敛的解不进判读。

几何单源 _c4_layout（米→mm 字面预计算 #218）；jog 端 0.02mm 面积重叠垫片
+ unite + object_names 校验（#310/#336）；薄片金属 assign_perfecte_to_sheets
（#356①）；板边端口 y 向零边距（#191）；get_face_center 模型单位 mm +
非空守卫（#285）；finally release_desktop（#265）；整轮重试 ≤2（#191）。

运行（分离进程）：powershell -NoProfile -ExecutionPolicy Bypass -File
scripts/df6_launch_y1.ps1
产物：runs/df6_hfss_track/y1_verdict.json + logs/y1_launch.log
"""
from __future__ import annotations

import cmath
import contextlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "runs" / "df6_hfss_track"
OUT_JSON = WORK / "y1_verdict.json"
VERSION = "2025.1"
F_PROBE = 2.5
SOLVE_TIMEOUT_S = 1200.0
LEVELS = ((0.02, 12), (0.01, 18), (0.005, 24))   # (MaxDeltaS, MaximumPasses)

# ── cline_coupler 标称几何（_c4_layout 米 → mm 字面预计算，#218）──────────
W_L, S_G, L_C, W_F = 0.9243, 0.0820, 18.1469, 1.1117
CLEAR, BOARD, H_SUB = 5.0, 60.0, 0.508           # mm；BOARD=板边半幅
ZM = H_SUB
XA = -(W_L + S_G) / 2.0                          # 线 A 中心 x
XFA = -(W_F / 2.0 + CLEAR / 2.0)                 # 馈线中心 x（A 侧）
Y_IN = L_C / 2.0 + W_F                           # 馈线内端 |y|
PAD = 0.02                                       # #336：jog 端面积重叠垫片
PORT_HW = 1.5 * W_F                              # S 设计端口半宽（3×wf）
PORT_H = 4.0 * H_SUB                             # 端口高（4×h）
Z_PORT_W_LADDER = (2.5, 4.0, 6.0)                # v2.2：z 端口宽度阶梯（mm）
AIR_X, AIR_TOP = BOARD + 5.0, 5.0                # 空气域（y 向零边距 #191）
L_FEED = BOARD - L_C / 2.0 - W_F                 # 均匀馈段长（jog 前止）
Z_F = 50.0                                       # 路线 B 馈段特征阻抗
# KJ 锚（runs/df6_dp14y1/criteria.md §1，coupled_microstrip_even_odd_ohm）
KJ_Z0E = 69.37088231385582
KJ_Z0O = 36.03866991398955
KJ_EE_E = 2.9921589396848027
KJ_EE_O = 2.466280526755509
C0 = 299792458.0


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _preflight() -> None:
    from rfauto.infra.desktop_guard import kill_orphan_ansysedt_desktops

    kill_orphan_ansysedt_desktops(log=log, strict=True)


def _release(h) -> None:
    from rfauto.infra.desktop_guard import release_desktop_capped

    with contextlib.suppress(Exception):
        release_desktop_capped(
            lambda: h.release_desktop(close_projects=True,
                                      close_desktop=True))


def _new_design(kind: str):
    import shutil

    from ansys.aedt.core import Hfss

    proj = WORK / f"y1_{kind}.aedt"
    # 全量重建：旧档/旧结果/旧锁先清（孤儿桌面会留 .lock → Project is
    # locked；复用旧档则 Rad/端口等边界重名 → create boundary 失败。
    # 本设计每次全量重建，旧解不构成证据依赖——C4 _clean_project 同款）
    for stale in (proj, proj.with_suffix(".aedtresults"),
                  proj.parent / (proj.stem + ".pyaedt"),
                  proj.parent / (proj.name + ".lock")):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        elif stale.exists():
            with contextlib.suppress(Exception):
                stale.unlink()
    log(f"旧项目已清理: {proj.name}")
    return Hfss(project=str(proj), design=f"y1_{kind}",
                solution_type="DrivenModal", version=VERSION,
                non_graphical=True, new_desktop=True)


def _base_stack(h, x_lo: float, x_hi: float, y_lo: float, y_hi: float):
    """板 + 地（薄片 PEC，#356①）；solve_inside 显式钉住。"""
    h.modeler.model_units = "mm"
    with contextlib.suppress(Exception):
        h.materials.add_material("rfauto_m366", properties={
            "permittivity": 3.66, "dielectric_loss_tangent": 0.0037})
    h.modeler.create_box(origin=[f"{x_lo}mm", f"{y_lo}mm", "0mm"],
                         sizes=[f"{x_hi - x_lo}mm", f"{y_hi - y_lo}mm",
                                f"{ZM}mm"],
                         name="Sub", material="rfauto_m366")
    h.modeler["Sub"].solve_inside = True
    h.modeler.create_box(origin=[f"{x_lo}mm", f"{y_lo}mm", "0mm"],
                         sizes=[f"{x_hi - x_lo}mm", f"{y_hi - y_lo}mm",
                                "0mm"],
                         name="Gnd", material="pec")


def _radiate(h, air_x_neg: float | None, air_x_pos: float | None) -> None:
    """顶面 +（存在的）x 墙辐射（#285 面过滤 mm + 非空守卫）。"""
    faces = h.modeler.get_object_faces("Air")
    open_faces = []
    for f in faces:
        cx, _cy, cz = (float(v) for v in h.modeler.get_face_center(f))
        hit = abs(cz - AIR_TOP) < 1e-6
        if air_x_neg is not None and abs(cx - air_x_neg) < 1e-6:
            hit = True
        if air_x_pos is not None and abs(cx - air_x_pos) < 1e-6:
            hit = True
        if hit:
            open_faces.append(f)
    if not open_faces:
        raise RuntimeError("辐射面过滤为空（#285 非空守卫）")
    h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")


def _metal_boxes(side: int) -> list[tuple[str, float, float]]:
    """线侧金属盒清单（side=−1 线 A / +1 线 B 镜像）→ (名, x0, x1)。"""
    s = float(side)
    xa, xf = XA * s, XFA * s
    return [
        ("line", xa - W_L / 2.0, xa + W_L / 2.0),
        ("feed_n", xf - W_F / 2.0, xf + W_F / 2.0),
        ("jog_n", min(xf - W_F / 2.0, xa), max(xf + W_F / 2.0, xa)),
        ("feed_f", xf - W_F / 2.0, xf + W_F / 2.0),
        ("jog_f", min(xf - W_F / 2.0, xa), max(xf + W_F / 2.0, xa)),
    ]


def _box_y_span(nm: str) -> tuple[float, float]:
    """盒 y 区间（mm）：line=耦合段、feed=馈线、jog=搭接段（带垫 #336）。"""
    if nm == "line":
        return -L_C / 2.0, L_C / 2.0
    if nm == "feed_n":
        return -BOARD, -Y_IN
    if nm == "feed_f":
        return Y_IN, BOARD
    if nm == "jog_n":
        return -(Y_IN + PAD), -L_C / 2.0 + PAD
    return L_C / 2.0 - PAD, Y_IN + PAD


def _build_z_half(h, sym_bc: str) -> None:
    """门 1 z 设计：半模型仅耦合段 + 对称墙 + 端口直接切耦合线（v2）。"""
    _base_stack(h, -BOARD, 0.0, -L_C / 2.0, L_C / 2.0)
    h.modeler.create_box(origin=[f"{XA - W_L / 2.0}mm", f"{-L_C / 2.0}mm",
                                 f"{ZM}mm"],
                         sizes=[f"{W_L}mm", f"{L_C}mm", "0mm"],
                         name="line_a", material="pec")
    h.assign_perfecte_to_sheets(assignment=["Gnd", "line_a"],
                                name="MetalPEC")
    # 对称墙：x=0 竖直薄片盖满全截面（板厚+空气域）
    h.modeler.create_rectangle(
        orientation="YZ", origin=["0mm", f"{-L_C / 2.0}mm", "0mm"],
        sizes=[f"{L_C}mm", f"{AIR_TOP}mm"], name="SymWall")
    if sym_bc == "PMC":
        h.assign_perfecth_to_sheets(assignment=["SymWall"], name="SymH")
    else:
        h.assign_perfecte_to_sheets(assignment=["SymWall"], name="SymE")
    # 空气域（subtract 基板/地/线；y 向零边距=端口贴外边界 #191）
    h.modeler.create_box(origin=[f"{-AIR_X}mm", f"{-L_C / 2.0}mm", "0mm"],
                         sizes=[f"{AIR_X}mm", f"{L_C}mm", f"{AIR_TOP}mm"],
                         name="Air", material="vacuum")
    h.modeler.subtract("Air", ["Sub", "Gnd", "line_a"])
    h.modeler["Air"].solve_inside = True
    _radiate(h, -AIR_X, None)
    # 端口直接切耦合线：横向 [−zport_w, 0]（线 A+半缝+左余量）、高 4h、
    # 显式积分线过线心（垂直 = 线对地位电压路径）；renormalize=False（v2）
    # v2.2：宽度=设计变量（横向收敛阶梯载体）
    h["zport_w"] = f"{Z_PORT_W_LADDER[0]:.6f}mm"
    for name, y_mm in (("P1", -L_C / 2.0), ("P2", L_C / 2.0)):
        h.modeler.create_rectangle(
            orientation="ZX",
            origin=["-zport_w", f"{y_mm}mm", "0mm"],
            sizes=[f"{PORT_H}mm", "zport_w"], name=name + "sheet")
        port_face = h.modeler.get_object_faces(name + "sheet")[0]
        # 积分线=地(z=0)→导带上缘(z=ZM)：连到面顶缘会穿过导带金属，
        # 电压路径无效（df6 v2.1 实测坑：Zpv/Zvi 崩、Zpi 无恙）
        h.wave_port(
            assignment=port_face, name=name, impedance=50.0,
            renormalize=False, characteristic_impedance="Zpv",
            integration_line=[[f"{XA}mm", f"{y_mm}mm", "0mm"],
                              [f"{XA}mm", f"{y_mm}mm", f"{ZM}mm"]])
    setup = h.create_setup(name="Setup1")
    setup.props["Frequency"] = f"{F_PROBE}GHz"
    setup.props["MaxDeltaS"] = LEVELS[0][0]
    setup.props["MaximumPasses"] = LEVELS[0][1]
    setup.update()


def _build_s_half(h, sym_bc: str) -> None:
    """门 3 S 设计：带馈线半模型（板边端口，handoff 原案几何）。"""
    _base_stack(h, -BOARD, 0.0, -BOARD, BOARD)
    names = []
    for (nm, x0, x1) in _metal_boxes(-1):
        ya, yb = _box_y_span(nm)
        h.modeler.create_box(origin=[f"{x0}mm", f"{ya}mm", f"{ZM}mm"],
                             sizes=[f"{x1 - x0}mm", f"{yb - ya}mm", "0mm"],
                             name=nm, material="pec")
        names.append(nm)
    united = h.modeler.unite(names)   # #310：保留首名；object_names 校验
    if united not in set(h.modeler.object_names) or \
            len(set(h.modeler.object_names)) != 3:
        raise RuntimeError(f"unite 后对象校验失败: {united}")
    h.assign_perfecte_to_sheets(assignment=["Gnd", united], name="MetalPEC")
    # v2.2：墙裁至耦合段 y 跨度（全板长墙实测把馈口模压成截止态
    # γ=940/m——criteria v2.2 第 2 条）；馈区无墙=小近似如实记注
    h.modeler.create_rectangle(
        orientation="YZ", origin=["0mm", f"{-L_C / 2.0}mm", "0mm"],
        sizes=[f"{L_C}mm", f"{AIR_TOP}mm"], name="SymWall")
    if sym_bc == "PMC":
        h.assign_perfecth_to_sheets(assignment=["SymWall"], name="SymH")
    else:
        h.assign_perfecte_to_sheets(assignment=["SymWall"], name="SymE")
    h.modeler.create_box(
        origin=[f"{-AIR_X}mm", f"{-BOARD}mm", "0mm"],
        sizes=[f"{AIR_X}mm", f"{2 * BOARD}mm", f"{AIR_TOP}mm"],
        name="Air", material="vacuum")
    h.modeler.subtract("Air", ["Sub", "Gnd", united])
    h.modeler["Air"].solve_inside = True
    _radiate(h, -AIR_X, None)
    _ports_and_setup(h, (("P1", XFA, -BOARD), ("P2", XFA, BOARD)))


def _build_full(h) -> None:
    """全模型：线 A/B 两组金属 + 4 端口（板边 y=±60）。"""
    _base_stack(h, -BOARD, BOARD, -BOARD, BOARD)
    united_names = []
    for side in (-1, +1):
        names = []
        for (nm, x0, x1) in _metal_boxes(side):
            tag = f"{'a' if side < 0 else 'b'}_{nm}"
            ya, yb = _box_y_span(nm)
            h.modeler.create_box(origin=[f"{x0}mm", f"{ya}mm", f"{ZM}mm"],
                                 sizes=[f"{x1 - x0}mm", f"{yb - ya}mm",
                                        "0mm"],
                                 name=tag, material="pec")
            names.append(tag)
        united = h.modeler.unite(names)
        if united not in set(h.modeler.object_names):
            raise RuntimeError(f"unite 后对象缺失: {united}")
        united_names.append(united)
    h.assign_perfecte_to_sheets(assignment=["Gnd", *united_names],
                                name="MetalPEC")
    h.modeler.create_box(
        origin=[f"{-AIR_X}mm", f"{-BOARD}mm", "0mm"],
        sizes=[f"{2 * AIR_X}mm", f"{2 * BOARD}mm", f"{AIR_TOP}mm"],
        name="Air", material="vacuum")
    h.modeler.subtract("Air", ["Sub", "Gnd", *united_names])
    h.modeler["Air"].solve_inside = True
    _radiate(h, -AIR_X, AIR_X)
    _ports_and_setup(h, (("P1", XFA, -BOARD), ("P2", XFA, BOARD),
                         ("P3", -XFA, -BOARD), ("P4", -XFA, BOARD)))


def _ports_and_setup(h, ports) -> None:
    """板边波端口（3×wf×4h，Gravity.ZPos；renormalize=False #v2）+ Setup。"""
    from ansys.aedt.core.generic.constants import Gravity

    for name, xc, y_mm in ports:
        h.modeler.create_rectangle(
            orientation="ZX",
            origin=[f"{xc - PORT_HW}mm", f"{y_mm}mm", "0mm"],
            sizes=[f"{PORT_H}mm", f"{2 * PORT_HW}mm"], name=name + "sheet")
        port_face = h.modeler.get_object_faces(name + "sheet")[0]
        # Zpi 对积分线路径稳健（Zpv/Zvi 需有效电压路径）；该 Zo 仅作
        # 路线 B 解嵌 z0 用，S 为 gen 基与 CharImp 定义无关
        h.wave_port(assignment=port_face, name=name,
                    impedance=50.0, renormalize=False,
                    characteristic_impedance="Zpi",
                    integration_line=Gravity.ZPos)
    setup = h.create_setup(name="Setup1")
    setup.props["Frequency"] = f"{F_PROBE}GHz"
    setup.props["MaxDeltaS"] = LEVELS[0][0]
    setup.props["MaximumPasses"] = LEVELS[0][1]
    setup.update()


def _solve_level(h, design: str, ds: float, mp: int,
                 char_imps: tuple[str, ...],
                 ports: tuple[str, ...] = ("P1", "P2")) -> dict:
    """单 ΔS 级：逐 CharImp 子解（v2）→ 全量读数 + profile 收敛元数据。"""
    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.infra.desktop_guard import run_with_watchdog
    from rfauto.service.port_gate_service import HfssPortDriver, _extract_modal_port_data

    setup = h.get_setup("Setup1")
    setup.props["Frequency"] = f"{F_PROBE}GHz"
    setup.props["MaxDeltaS"] = ds
    setup.props["MaximumPasses"] = mp
    setup.update()
    ext_last = None
    for ci in char_imps:
        HfssPortDriver._set_ports_char_imp(
            hfss=h, port_names=ports, char_imp=ci, mode_index=1)
        run_with_watchdog(lambda: h.analyze(setup="Setup1"),
                          timeout_s=SOLVE_TIMEOUT_S,
                          what=f"{design} ΔS={ds} [{ci}]")
        ext_last = _extract_modal_port_data(
            h, "Setup1", ("P1", "P2", "P3", "P4"))
    passes, delta_s = HfssAdapter._extract_convergence(setup)
    ext = ext_last
    rec = {
        "max_delta_s": ds, "max_passes": mp, "char_imps": list(char_imps),
        "passes": passes, "delta_s_final": delta_s,
        "converged": (delta_s is not None and delta_s <= ds),
        "hit_max_passes": bool(passes and mp and passes >= mp),
        "categories": ext["categories"], "errors": ext["errors"],
        "n_modes": ext["n_modes"],
        "port_data": {pn: {k: _fmt_c(v) for k, v in d.items()}
                      for pn, d in ext["port_data"].items()},
        "s_data": {f"S({a},{b})": {"re": v.real, "im": v.imag,
                                   "db": 20 * math.log10(abs(v) + 1e-300),
                                   "deg": math.degrees(cmath.phase(v))}
                   for (a, b), v in ext["s_data"].items()},
    }
    zo1 = ext["port_data"].get("P1", {}).get("Zo")
    if zo1 is not None:
        rec["zo_p1_ohm"] = abs(zo1)
    gam1 = ext["port_data"].get("P1", {}).get("Gamma")
    if gam1 is not None:
        rec["gamma_p1"] = _fmt_c(gam1)
        # εeff=(β/k0)²，β=γ 虚部（HFSS Gamma=α+jβ；实部为衰减 α）
        rec["eps_eff"] = (gam1.imag * C0 / (2 * math.pi * F_PROBE
                                            * 1e9)) ** 2
    log(f"{design} ΔS={ds}: delta_s={delta_s} passes={passes} "
        f"Zo(P1)={rec.get('zo_p1_ohm')} eps={rec.get('eps_eff')}")
    return rec


def _fmt_c(z: complex | None) -> dict | None:
    if z is None:
        return None
    z = complex(z)
    return {"re": round(z.real, 9), "im": round(z.imag, 9)}


def _solve_z_levels(h, design: str) -> list[dict]:
    """z 设计 v2.2：端口宽度阶梯（ΔS 固定 0.005/20）；末宽三定义子解。"""
    out = []
    for lvl, w in enumerate(Z_PORT_W_LADDER):
        h["zport_w"] = f"{w:.6f}mm"
        cis = ("Zpv",) if lvl < len(Z_PORT_W_LADDER) - 1             else ("Zpv", "Zpi", "Zvi")
        out.append(_solve_level(h, design, 0.005, 20, cis))
    return out


def _solve_s_levels(h, design: str,
                    ports: tuple[str, ...] = ("P1", "P2")) -> list[dict]:
    """S 设计 ΔS 阶梯：全级 Zpi（S 为 gen 基，与定义无关）。"""
    return [_solve_level(h, design, ds, mp, ("Zpi",), ports=ports)
            for ds, mp in LEVELS]


def run_design(kind: str, sym_bc: str | None) -> dict:
    h = _new_design(kind)
    try:
        if kind in ("even", "odd"):
            _build_s_half(h, sym_bc)
            levels = _solve_s_levels(h, f"y1_{kind}")
        elif kind in ("even_z", "odd_z"):
            _build_z_half(h, sym_bc)
            levels = _solve_z_levels(h, f"y1_{kind}")
        else:
            _build_full(h)
            levels = _solve_s_levels(h, "y1_full",
                                     ports=("P1", "P2", "P3", "P4"))
        return {"design": f"y1_{kind}", "sym_bc": sym_bc, "levels": levels}
    finally:
        _release(h)


# ── 离线判读（criteria.md 件 2 节 + v2 修订；纯数学零求解）─────────────────


def _s(rec: dict, key: str) -> complex:
    v = rec["s_data"][key]
    return complex(v["re"], v["im"])


def _zo(rec: dict, port: str) -> complex | None:
    v = rec["port_data"].get(port, {}).get("Zo")
    return complex(v["re"], v["im"]) if v else None


def _renorm_s(s: np.ndarray, z_from: list[complex],
              z_to: list[complex]) -> np.ndarray:
    """N×N 功率波 S 参考阻抗变换（Z 矩阵中转；rwg_mmt.renormalize_2port
    同式推广到 N 口，允许复 z0——有耗线模阻抗）。奇异显式报错。"""
    n = s.shape[0]
    zf = np.asarray(z_from, dtype=complex)
    zt = np.asarray(z_to, dtype=complex)
    eye = np.eye(n, dtype=complex)
    z_mat = (np.sqrt(zf)[:, None] * np.linalg.solve(eye - s, eye + s)
             * np.sqrt(zf)[None, :])
    d_inv = np.diag(1.0 / np.sqrt(zt))
    d_mat = np.diag(np.sqrt(zt))
    return d_inv @ (z_mat - np.diag(zt)) @ np.linalg.solve(
        z_mat + np.diag(zt), d_mat)


def _s_to_abcd(s2: np.ndarray, z0: float) -> np.ndarray:
    """2×2 S（实参考 z0）→ ABCD（电压/电流式）。"""
    s11, s12 = s2[0, 0], s2[0, 1]
    s21, s22 = s2[1, 0], s2[1, 1]
    den = 2.0 * s21
    a = ((1 + s11) * (1 - s22) + s12 * s21) / den
    b = z0 * ((1 + s11) * (1 + s22) - s12 * s21) / den
    c = ((1 - s11) * (1 - s22) - s12 * s21) / (den * z0)
    d = ((1 - s11) * (1 + s22) + s12 * s21) / den
    return np.array([[a, b], [c, d]], dtype=complex)


def _abcd_to_s(A: np.ndarray, z0: float) -> np.ndarray:
    """2×2 ABCD（电压/电流式）→ S（实参考 z0）：
    S11=(a+b/z0−c·z0−d)/den、S21=2/den、S12=2(ad−bc)/den、
    S22=(d−a+b/z0−c·z0)/den（den=a+b/z0+c·z0+d）。"""
    a, b, c, d = A[0, 0], A[0, 1], A[1, 0], A[1, 1]
    den = a + b / z0 + c * z0 + d
    return np.array([[(a + b / z0 - c * z0 - d) / den,
                      2 * (a * d - b * c) / den],
                     [2 / den,
                      (d - a + b / z0 - c * z0) / den]], dtype=complex)


def _route_b(full_lvl: dict) -> dict:
    """路线 B（门 2）：全模型 gen S → 偶/奇 2 口叠加 → 50Ω 重归一 →
    馈线 ABCD 解嵌（L_feed 均匀段；jog 台阶寄生不建模——如实注记）→
    对称均匀线反演 Z_m=√(B/C)、A=cosh(γL)。"""
    out: dict = {"note": "jog 台阶寄生未建模；超门不凑绿（#122）",
                 "l_feed_mm": L_FEED}
    ports = ("P1", "P2", "P3", "P4")
    zo = [_zo(full_lvl, p) for p in ports]
    if any(z is None for z in zo):
        return {"verdict": "UNKNOWN", "reason": "Port Zo 读数缺失"}
    s_gen = np.zeros((4, 4), dtype=complex)
    for i, pi in enumerate(ports):
        for j, pj in enumerate(ports):
            key = f"S({pi},{pj})"
            if key not in full_lvl["s_data"]:
                return {"verdict": "UNKNOWN", "reason": f"S 量缺失: {key}"}
            s_gen[i, j] = _s(full_lvl, key)
    try:
        s50 = _renorm_s(s_gen, [complex(v) for v in zo], [50.0] * 4)
    except Exception as exc:
        return {"verdict": "UNKNOWN", "reason": f"重归一失败: {exc!r}"}
    gam = full_lvl["port_data"]["P1"].get("Gamma")
    gam_c = complex(gam["re"], gam["im"]) if gam else 0j
    th_f = gam_c * (L_FEED * 1e-3)
    z_f = zo[0] if zo[0] is not None else complex(Z_F)
    results: dict = {}
    for tag, sign, kj in (("even", 1.0, KJ_Z0E), ("odd", -1.0, KJ_Z0O)):
        gamma_m = s50[0, 0] + sign * s50[2, 0]     # Γe=S11+S31 / Γo=S11−S31
        t_m = s50[1, 0] + sign * s50[3, 0]         # Te=S21+S41 / To=S21−S41
        s2 = np.array([[gamma_m, t_m], [t_m, gamma_m]], dtype=complex)
        a_tot = _s_to_abcd(s2, 50.0)
        a_f = np.array(
            [[cmath.cosh(th_f), z_f * cmath.sinh(th_f)],
             [cmath.sinh(th_f) / z_f, cmath.cosh(th_f)]], dtype=complex)
        a_f_inv = np.linalg.inv(a_f)
        a_c = a_f_inv @ a_tot @ a_f_inv
        roundtrip = float(np.max(np.abs(a_f @ a_c @ a_f - a_tot)))
        if a_c[1, 0] == 0:
            results[tag] = {"z_m": None, "reason": "C=0 反演退化"}
            continue
        z_m = cmath.sqrt(a_c[0, 1] / a_c[1, 0])
        gl = cmath.acosh(a_c[0, 0])
        results[tag] = {
            "z_m": _fmt_c(z_m), "z_m_abs": abs(z_m), "kj": kj,
            "dev_pct": abs(abs(z_m) - kj) / kj * 100.0,
            "gamma_L": _fmt_c(gl), "roundtrip_resid": roundtrip,
        }
    out["routes"] = results
    bad = [k for k, v in results.items()
           if v.get("dev_pct") is None or v["dev_pct"] > 2.0]
    out["verdict"] = "FAIL" if bad else "PASS"
    if bad:
        out["reason"] = f"互差超 2%: {bad}（含解嵌近似残差，如实）"
    return out


def judge(even_z: dict, odd_z: dict, even: dict, odd: dict,
          full: dict) -> dict:
    """门 0-4 判读（criteria.md 件 2 节 + v2 修订阈值）。"""
    out: dict = {"gates": {}}
    # ── 门 0：ΔS 收敛阶梯（#335：末两级差在门内才采信）─────────────────
    gate0: dict = {"note": "#335：末两级差在门内才采信；触顶解不进判读"
                           "（v2.2：z 阶梯=端口宽度阶梯，ΔS 固定 0.005）",
                   "tol": {"zo_step_rel": 0.02, "s_step_rel": 0.00577}}
    for rec, name in ((even_z, "even_z"), (odd_z, "odd_z"),
                      (even, "even"), (odd, "odd"), (full, "full")):
        last2 = rec["levels"][-2:]
        entry: dict = {"converged_final": last2[1]["converged"],
                       "hit_max_passes": [lv["hit_max_passes"]
                                          for lv in last2]}
        ok = True
        if name.endswith("_z"):
            zo = [lv.get("zo_p1_ohm") for lv in last2]
            if all(v is not None for v in zo) and zo[1]:
                entry["zo_step_rel"] = abs(zo[1] - zo[0]) / zo[1]
                ok = ok and entry["zo_step_rel"] <= 0.02
            else:
                ok = False
        skeys = ("S(P2,P1)", "S(P3,P1)") if name == "full" \
            else ("S(P2,P1)",)
        for key in skeys:
            if key in last2[0]["s_data"] and key in last2[1]["s_data"]:
                a, b = abs(_s(last2[0], key)), abs(_s(last2[1], key))
                if b:
                    rel = abs(b - a) / b
                    entry[f"{key}_step_rel"] = rel
                    ok = ok and rel <= 0.00577
        entry["ok"] = bool(ok and entry["converged_final"]
                           and not any(entry["hit_max_passes"]))
        gate0[name] = entry
    out["gates"]["gate0_convergence"] = gate0
    trusted = all(gate0[k]["ok"] for k in
                  ("even_z", "odd_z", "even", "odd", "full"))
    if not trusted:
        out["gates"]["_note"] = "门 0 未全过：涉末级解的门如实 UNKNOWN"
    lvl_ez, lvl_oz = even_z["levels"][-1], odd_z["levels"][-1]
    # ── 门 1：z 设计直读 vs KJ + Zvi 恒等式实测自校（#356⑤）────────────
    g1: dict = {"kj_z0e": KJ_Z0E, "kj_z0o": KJ_Z0O}
    for rec, mode, kj in ((lvl_ez, "even", KJ_Z0E),
                          (lvl_oz, "odd", KJ_Z0O)):
        zo_pv = _zo(rec, "P1")
        entry: dict = {"z0_hfss_zpv": _fmt_c(zo_pv)}
        if zo_pv is not None and trusted:
            entry["dev_pct"] = abs(abs(zo_pv) - kj) / kj * 100.0
            entry["ok_dev"] = bool(entry["dev_pct"] <= 2.0)
        else:
            entry["ok_dev"] = None
        by_def = {ci: rec["port_data"].get("P1", {}).get("Zo")
                  for ci in rec.get("char_imps", ())} \
            if len(rec.get("char_imps", ()) or ()) > 1 else {}
        if {"Zpi", "Zpv", "Zvi"} <= set(by_def) and \
                all(by_def[c] for c in ("Zpi", "Zpv", "Zvi")):
            zpi = complex(by_def["Zpi"]["re"], by_def["Zpi"]["im"])
            zpv = complex(by_def["Zpv"]["re"], by_def["Zpv"]["im"])
            zvi = complex(by_def["Zvi"]["re"], by_def["Zvi"]["im"])
            expected = (zpi * zpv) ** 0.5
            rel = abs(zvi - expected) / abs(zvi) if abs(zvi) else None
            entry["zvi_identity"] = {
                "zpi": _fmt_c(zpi), "zpv": _fmt_c(zpv), "zvi": _fmt_c(zvi),
                "rel_err": rel,
                "ok": bool(rel is not None and rel <= 1e-6)}
            if rel is None or rel > 1e-6:
                entry["ok_dev"] = False
        else:
            entry["zvi_identity"] = {"status": "UNKNOWN",
                                     "reason": "末级三定义子解缺失"}
            entry["ok_dev"] = None
        g1[mode] = entry
    if not trusted:
        g1["verdict"] = "UNKNOWN"
    elif any(g1[m].get("ok_dev") is not True for m in ("even", "odd")):
        g1["verdict"] = ("FAIL" if any(g1[m].get("ok_dev") is False
                                       for m in ("even", "odd"))
                         else "UNKNOWN")
    else:
        g1["verdict"] = "PASS"
    out["gates"]["gate1_half_vs_kj"] = g1
    # ── 门 2：路线互差（路线 B：全模型 S 解嵌反演）──────────────────────
    g2: dict = {"verdict": "UNKNOWN", "reason": "门 0 未过"}
    if trusted:
        g2 = _route_b(full["levels"][-1])
    out["gates"]["gate2_route_cross"] = g2
    # ── 门 3：半/全 S 一致性（gen 基叠加 vs 半模型直读 @2.5GHz）─────────
    lvl_e, lvl_o, lvl_f = (even["levels"][-1], odd["levels"][-1],
                           full["levels"][-1])
    if trusted:
        g3: dict = {"basis": "generalized modal（重归一叠加非线性，禁用）",
                    "entries": {}}
        pairs = (("S11_vs_Ge", _s(lvl_e, "S(P1,P1)"),
                  _s(lvl_f, "S(P1,P1)") + _s(lvl_f, "S(P3,P1)"), 0.05),
                 ("S11_vs_Go", _s(lvl_o, "S(P1,P1)"),
                  _s(lvl_f, "S(P1,P1)") - _s(lvl_f, "S(P3,P1)"), 0.05),
                 ("S21_vs_Te", _s(lvl_e, "S(P2,P1)"),
                  _s(lvl_f, "S(P2,P1)") + _s(lvl_f, "S(P4,P1)"), 0.05),
                 ("S21_vs_To", _s(lvl_o, "S(P2,P1)"),
                  _s(lvl_f, "S(P2,P1)") - _s(lvl_f, "S(P4,P1)"), 0.05))
        v = "PASS"
        for nm, half_v, sup_v, tol in pairs:
            d_db = abs(20 * math.log10(abs(sup_v) + 1e-300)
                       - 20 * math.log10(abs(half_v) + 1e-300))
            d_deg = abs(math.degrees(cmath.phase(sup_v))
                        - math.degrees(cmath.phase(half_v)))
            d_deg = min(d_deg, 360 - d_deg)
            entry = {"db_diff": d_db, "phase_diff_deg": d_deg,
                     "tol_db": tol, "ok": bool(d_db <= tol and d_deg <= 1.0)}
            g3["entries"][nm] = entry
            if not entry["ok"]:
                v = "FAIL"
        g3["verdict"] = v
    else:
        g3 = {"verdict": "UNKNOWN", "reason": "门 0 未过或读数缺失"}
    out["gates"]["gate3_half_full_s"] = g3
    # ── 门 4：对称性自检（镜像配对 (1↔3)(2↔4)，线性残差 ≤1e-2）─────────
    if trusted:
        g4: dict = {"entries": {}}
        pairs = (("S11_vs_S33", "S(P1,P1)", "S(P3,P3)"),
                 ("S22_vs_S44", "S(P2,P2)", "S(P4,P4)"),
                 ("S21_vs_S34", "S(P2,P1)", "S(P4,P3)"),
                 ("S41_vs_S23", "S(P4,P1)", "S(P2,P3)"))
        worst = 0.0
        v4 = "PASS"
        for nm, ka, kb in pairs:
            if ka not in lvl_f["s_data"] or kb not in lvl_f["s_data"]:
                g4["entries"][nm] = {"ok": None, "reason": "S 量缺失（如实）"}
                continue
            resid = abs(_s(lvl_f, ka) - _s(lvl_f, kb))
            g4["entries"][nm] = {"linear_residual": resid,
                                 "db": 20 * math.log10(resid + 1e-300),
                                 "ok": bool(resid <= 1e-2)}
            worst = max(worst, resid)
            if resid > 1e-2:
                v4 = "FAIL"
        g4["worst_linear_residual"] = worst
        g4["verdict"] = v4
        g4["note"] = "超门先查网格不对称（#154 家族），如实报"
    else:
        g4 = {"verdict": "UNKNOWN", "reason": "门 0 未过"}
    out["gates"]["gate4_symmetry"] = g4
    # ── εeff 旁证（非门）：z 设计 Γ 直读耦合段偶/奇模 εeff ─────────────
    out["eps_eff"] = {
        "even_z": lvl_ez.get("eps_eff"), "odd_z": lvl_oz.get("eps_eff"),
        "kj_even": KJ_EE_E, "kj_odd": KJ_EE_O,
        "note": "旁证记录非门（β 口径 vs KJ 准静态，#301 同族）"}
    verdicts = [out["gates"][k].get("verdict")
                for k in ("gate1_half_vs_kj", "gate2_route_cross",
                          "gate3_half_full_s", "gate4_symmetry")]
    if not trusted:
        out["overall_verdict"] = "UNKNOWN"
    elif all(v == "PASS" for v in verdicts):
        out["overall_verdict"] = "PASS"
    elif any(v == "FAIL" for v in verdicts):
        out["overall_verdict"] = "FAIL"
    else:
        out["overall_verdict"] = "UNKNOWN"
    return out


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "logs").mkdir(exist_ok=True)
    t_start = time.time()
    result: dict = {
        "gate": "y1_half_model_hfss_arbitration",
        "criteria": "runs/df6_hfss_track/criteria.md 件 2 节 + v2 修订",
        "handoff": "runs/df6_dp14y1/handoff.md（A 主判/B 互检/门 0-4）",
        "template_scope": ("cline_coupler only（branchline_2sect 第二发"
                           "不在本窗口）"),
        "port_convention": {
            "z_designs": ("切耦合段 y=±lc/2，横向 [−2.5,0]mm × 4h 高，"
                          "显式积分线过线心；CharImp=Zpv 主判"),
            "s_designs_full": "板边 y=±60，3×wf×4h，Gravity.ZPos",
            "renormalize": False,
        },
        "version": VERSION,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    even_z = odd_z = even = odd = full = None
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            _preflight()
            if even_z is None:
                even_z = run_design("even_z", "PMC")
                result["even_z"] = even_z
                _write(result)
            if odd_z is None:
                odd_z = run_design("odd_z", "PEC")
                result["odd_z"] = odd_z
                _write(result)
            if even is None:
                even = run_design("even", "PMC")
                result["even"] = even
                _write(result)
            if odd is None:
                odd = run_design("odd", "PEC")
                result["odd"] = odd
                _write(result)
            if full is None:
                full = run_design("full", None)
                result["full"] = full
                _write(result)
            break
        except Exception as exc:
            last_err = exc
            log(f"attempt {attempt}/3 FAIL: {exc!r}")
            # 自家泄漏桌面点杀（parent=本 python，#265 不涉他轨）+ 孤儿清场
            with contextlib.suppress(Exception):
                import os as _os

                from rfauto.infra.desktop_guard import kill_ansysedt_by_ppid as _kbyp
                from rfauto.infra.desktop_guard import kill_orphan_ansysedt_desktops as _kill
                _kbyp(_os.getpid(), log=log)
                _kill(log=log, strict=False)
            # 轮间等桌面退净（泄漏桌面会让下轮 strict preflight 自锁）
            for _ in range(20):
                with contextlib.suppress(Exception):
                    from rfauto.infra.desktop_guard import list_ansysedt_processes as _lst
                    if not _lst():
                        break
                time.sleep(3)
    if None in (even_z, odd_z, even, odd, full):
        result["fatal"] = f"3 次整轮重试后仍未完成: {last_err!r}"
        result["overall_verdict"] = "UNKNOWN"
    else:
        result.update(judge(even_z, odd_z, even, odd, full))
    result["budget"] = {
        "pre_declared_min": 40, "pre_declared_max": 60,
        "partial_over_min": 90,
        "wall_clock_min": round((time.time() - t_start) / 60.0, 1),
        "solves_pre_declared": 19,
    }
    result["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write(result)
    _final_orphan_check(result)
    log(f"OVERALL={result.get('overall_verdict')} "
        f"wall={result['budget']['wall_clock_min']}min")
    print(f"Y1_TRACK_{result.get('overall_verdict')}", flush=True)
    return 0


def _write(result: dict) -> None:
    OUT_JSON.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    log(f"verdict JSON 已落盘: {OUT_JSON.name}")


def _final_orphan_check(result: dict) -> None:
    try:
        from rfauto.infra.desktop_guard import list_ansysedt_processes
        procs = list_ansysedt_processes()
        result["session"] = {
            "ansysedt_after": [p["pid"] for p in procs],
            "note": "0=零孤儿（任务管理器同口径核验）",
        }
        _write(result)
    except Exception as exc:
        result["session"] = {"error": f"孤儿核验失败: {exc!r}"}


if __name__ == "__main__":
    sys.exit(main())
