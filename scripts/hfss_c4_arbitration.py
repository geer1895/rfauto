"""HFSS 名义几何仲裁 C4 耦合器族裁判口径（对齐基准口径）。

背景（C4 下一假设①）：openEMS 合规网格两轮复跑 S31 归一后 −2.03（lange）/
−8.00（cline）vs 裁判闭式 −3.01/−10.05——耦合度强 1~2dB；z 向地板已排除面内离散；
剩余假设=裁判闭式在 lange s/h=0.076<KJ 有效域 0.1（cline 0.161 边缘）不适用，即
"裁判错"而非"引擎错"。

本脚本按代码单源名义几何（openems_templates.TEMPLATE_NOMINAL + _c4_layout，零手抄）
在 HFSS 重建 lange / cline_coupler 两结构：零厚度 PEC sheet 走线（与 openEMS AddMetal
同口径）+ lange air-bridge/立柱按真实三维尺寸 pec 实体（#264）+ 单源 boxes 中 `*_jog`
横向垫 0.02mm 面积重叠后 unite（共边薄片 unite 不合并，#310）+ 每馈线独立 4 只单模
大截面波端口（宽 4mm≈3.6w、高 3mm≈5.9h；每端口=单微带准 TEM 线，不涉及 #307 双导体
模阻抗基准换算，端口 renormalize 50Ω）+ 波端口 deembed 到 openEMS 同款测量面
（MeasPlaneShift 单源读取）+ 辐射边界（顶+两侧，mline r4 同口径，y 端面留给端口）。

预声明门（写死，先于任何真跑；判读常量不许跑后改）：
- 主判量 = |S31| @f0=2.5GHz（deembed 后，50Ω 口径）；
- d_oe = |S31_hfss − S31_oe_norm|（oe 口径=runs/smoke_c4_refix/<t>_judge.json 的
  after_norm.at_f0_nominal，数据单源读取）；
- d_judge = |S31_hfss − S31_judge|（闭式经 smoke.circuit_judge 同核在进程内重算，
  等价 judge_c4_assembly 记录的 −3.01/−10.05）；
- d_oe ≤ 0.5dB 且 d_oe < d_judge → AGREE_OPENEMS（假设成立：裁判闭式在该 s/h 域
  不适用，裁判口径需按 HFSS 修正）；
- d_judge ≤ 0.5dB 且 d_judge < d_oe → AGREE_JUDGE（引擎系统性偏差，方向指向 x 向
  加密/边缘建模）；
- 其余（含两边都不进 0.5dB 或打平）→ INCONCLUSIVE。
两模板同判 → 结论置信度高；仅单模板进判 → 中（cline s/h=0.161 本就边缘）。

自检：σmax（SVD，G1 同门 ≤1.01）作几何/端口连通性哨兵（薄片-实体接触断开会使
σmax 或 S11 异常）；cline 端口角色核对 |S21|>|S31|、lange ||S21|−|S31||<1.5dB。

产物：runs/hfss_c4_arbitration/（c4_<t>.aedt、<t>_arbitration.s4p、verdict.json、
run_log.txt）。执行（工作区根目录）：
    .venv/Scripts/python.exe scripts/hfss_c4_arbitration.py
预算 ≤90min：lange 先跑（主嫌疑）；累计墙钟按 BUDGET_FRACTION_PER_TEMPLATE 缺口
跳过剩余模板并在 verdict 如实标注 skipped。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
WORK_DIR = REPO / "runs" / "hfss_c4_arbitration"
OE_REF_DIR = REPO / "runs" / "smoke_c4_refix"

for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# ── 预声明门（写死） ──────────────────────────────────────────────────────
TOL_SIDE_DB = 0.5
SIGMA_MAX_GATE = 1.01
BUDGET_TOTAL_S = 90 * 60
BUDGET_FRACTION_PER_TEMPLATE = 0.45   # 剩余墙钟不足此比例则不再开新模板
SOLVE_TIMEOUT_S = 2100
FREQ_GHZ = (2.0, 3.0, 401)
PORT_W_MM = 4.0                       # ≈3.6×w_feed
PORT_H_MM = 3.0                       # ≈5.9×h（官方波端口尺寸 ≥3w/≥5h 口径）
XHALF_MM = 25.0                       # x 向辐射缓冲（mline r4 同量级；声明差异：
                                      # HFSS 辐射边界 vs openEMS PML_8）
ZTOP_MM = 8.0
JOG_EPS_MM = 0.02                     # jog 端向垫片（共边薄片 unite 需面积重叠，#310）
H_SUB_MM = 0.508
ER = 3.66
TAND = 0.0037
MATERIAL = "rfauto_c4_rogers4350b"
TEMPLATES = ("lange", "cline_coupler")

# sheet 连通链（逐对面积重叠后 unite；名称= _c4_layout 确定性命名，构建前审计）
SHEET_CHAINS: dict[str, list[list[str]]] = {
    "cline_coupler": [
        ["feed_p1_feed", "feed_p1_jog", "line_a", "feed_p2_jog", "feed_p2_feed"],
        ["feed_p3_feed", "feed_p3_jog", "line_b", "feed_p4_jog", "feed_p4_feed"],
    ],
    "lange": [
        ["feed_p1_feed", "feed_p1_jog", "finger_1", "feed_p2_jog", "feed_p2_feed"],
        ["feed_p3_feed", "feed_p3_jog", "finger_4", "feed_p4_jog", "feed_p4_feed"],
        ["finger_3"],
        ["finger_2"],
    ],
}
# lange 三维桥/柱按桥组 unite（#264 真实三维尺寸；solid-solid 共面接触自动连通）
BRIDGE_GROUPS = (("a", 1, 3), ("b", 2, 4), ("b2", 2, 4), ("a2", 1, 3))


def _log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    with open(WORK_DIR / "run_log.txt", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ── 纯函数（离线单测面） ─────────────────────────────────────────────────
def box_area_overlap_xy(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """两盒 x∧y 面积重叠（同一 z 面；零=不连通）。盒=(名,x0,y0,z0,x1,y1,z1)。"""
    dx = min(a[4], b[4]) - max(a[1], b[1])
    dy = min(a[5], b[5]) - max(a[2], b[2])
    return max(dx, 0.0) * max(dy, 0.0)


def inflate_jog_boxes(boxes: list[tuple], eps_mm: float) -> list[tuple]:
    """`*_jog` 盒 y 向两端各垫 eps（mm）：共边→面积重叠（#310）。其余盒不动。"""
    out = []
    for b in boxes:
        if b[0].endswith("_jog"):
            out.append((b[0], b[1], b[2] - eps_mm, b[3], b[4], b[5] + eps_mm, b[6]))
        else:
            out.append(b)
    return out


def missing_chain_links(chains: list[list[str]],
                        by_name: dict[str, tuple]) -> list[tuple[str, str]]:
    """链上相邻盒对面积重叠为 0 的断链清单（空=全连通；构建前 #310 审计）。"""
    out: list[tuple[str, str]] = []
    for chain in chains:
        for a, b in pairwise(chain):
            if box_area_overlap_xy(by_name[a], by_name[b]) <= 0.0:
                out.append((a, b))
    return out


def three_way_verdict(s31_hfss_db: float, s31_oe_db: float, s31_judge_db: float,
                      tol_db: float = TOL_SIDE_DB) -> dict[str, Any]:
    """三方对账预声明门：HFSS 落谁侧（±tol 内且更近者）；其余 INCONCLUSIVE。"""
    d_oe = abs(s31_hfss_db - s31_oe_db)
    d_judge = abs(s31_hfss_db - s31_judge_db)
    if d_oe <= tol_db and d_oe < d_judge:
        side, verdict = "openems", "AGREE_OPENEMS"
    elif d_judge <= tol_db and d_judge < d_oe:
        side, verdict = "judge", "AGREE_JUDGE"
    else:
        side, verdict = "inconclusive", "INCONCLUSIVE"
    return {"side": side, "verdict": verdict, "d_openems_db": round(d_oe, 4),
            "d_judge_db": round(d_judge, 4), "tol_db": tol_db}


def load_template_layout(template: str) -> dict[str, Any]:
    """代码单源名义几何（openems_templates，米）→ mm 布局 + 端口/测量面。"""
    from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL, _c4_layout

    params = {k: float(v) for k, v in TEMPLATE_NOMINAL[template].items()}
    lay = _c4_layout(template, params)
    boxes_mm = [(bx[0], bx[1] * 1e3, bx[2] * 1e3, bx[3] * 1e3, bx[4] * 1e3,
                 bx[5] * 1e3, bx[6] * 1e3) for bx in lay["boxes"]]
    ports = [{"nr": pt["nr"], "xc_mm": (pt["start"][0] + pt["stop"][0]) / 2.0 * 1e3,
              "y_face_mm": pt["start"][1] * 1e3,
              "deembed_mm": float(pt["meas_shift"]) * 1e3} for pt in lay["ports"]]
    ports.sort(key=lambda p: p["nr"])
    board_y = max(max(abs(b[2]), abs(b[5])) for b in boxes_mm)
    return {"boxes_mm": boxes_mm, "ports": ports,
            "f0_ghz": float(TEMPLATE_META[template]["f0_ghz"]), "params": params,
            "board_y_mm": board_y}


def judge_reference_db(template: str) -> dict[str, float]:
    """裁判闭式 @f0（smoke.circuit_judge 同核进程内重算 = judge_c4_assembly 出处）。"""
    import smoke_c4_coupler_family as smoke

    lay = load_template_layout(template)
    f0 = lay["f0_ghz"]
    circ = smoke.circuit_judge(template, np.array([f0]), lay["params"], f0)
    db = 20.0 * np.log10(np.abs(circ[0]) + 1e-12)
    return {"s11_db": float(db[0, 0]), "s21_db": float(db[1, 0]),
            "s31_db": float(db[2, 0]), "s41_db": float(db[3, 0])}


def openems_reference(template: str, ref_dir: Path = OE_REF_DIR) -> dict[str, Any] | None:
    """openEMS 归一后 @f0 参照（数据单源 runs/smoke_c4_refix/<t>_judge.json）。"""
    path = ref_dir / f"{template}_judge.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    m = d["after_norm"]["at_f0_nominal"]
    return {"caliber": "after_norm（#250 引擎 ZL 链归一）", "source": str(path),
            "s11_db": m["s11_db"], "s21_db": m["s21_db"], "s31_db": m["s31_db"],
            "s41_db": m["s41_db"],
            "sigma_max_norm": d["assembly_norm"]["sigma_max_norm"]}


# ── HFSS 真机构建面（pyaedt 惰性导入；离线测试不触） ─────────────────────
def assert_desktop_idle() -> None:
    """孤儿 ansysedt 哨兵（#265：父进程已死的桌面占轨）——发现即 fail-fast。"""
    out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    if "ansysedt.exe" in out:
        raise RuntimeError("检测到已在运行的 ansysedt.exe（#265 孤儿桌面嫌疑）——"
                           "先核对命令行/PID 清理后再跑，避免占轨空等")


def build_template(adapter, template: str) -> dict[str, Any]:
    """HFSS 重建单模板：sheet 走线 + 桥/柱实体 + 大截面波端口 + deembed。"""
    from ansys.aedt.core.generic.constants import Gravity

    lay = load_template_layout(template)
    boxes = inflate_jog_boxes(lay["boxes_mm"], JOG_EPS_MM)
    by_name = {b[0]: b for b in boxes}
    broken = missing_chain_links(SHEET_CHAINS[template], by_name)
    if broken:
        raise RuntimeError(f"sheet 连通链审计失败（#310）：{broken}")

    hfss = adapter.session.hfss
    modeler = hfss.modeler
    modeler.model_units = "mm"
    with contextlib.suppress(Exception):
        hfss.materials.add_material(
            MATERIAL, properties={"permittivity": ER,
                                  "dielectric_loss_tangent": TAND})

    board = lay["board_y_mm"]
    modeler.create_box(origin=[-XHALF_MM, -board, 0.0],
                       sizes=[2 * XHALF_MM, 2 * board, H_SUB_MM],
                       name="Substrate", material=MATERIAL)
    modeler.create_rectangle(orientation="XY", origin=[-XHALF_MM, -board, 0.0],
                             sizes=[2 * XHALF_MM, 2 * board], name="Ground")
    solids: list[str] = []
    for (nm, x0, y0, z0, x1, y1, z1) in boxes:
        if abs(z1 - z0) < 1e-12:      # 零厚度 sheet（openEMS AddMetal 同口径）
            modeler.create_rectangle(orientation="XY", origin=[x0, y0, z0],
                                     sizes=[x1 - x0, y1 - y0], name=nm)
        else:                          # 桥/柱：真实三维 pec 实体（#264）
            modeler.create_box(origin=[x0, y0, z0],
                               sizes=[x1 - x0, y1 - y0, z1 - z0],
                               name=nm, material="pec")
            solids.append(nm)

    # sheet 网络 unite（保留首名 + object_names 校验，#310）
    net_names: list[str] = []
    for chain in SHEET_CHAINS[template]:
        head = chain[0]
        if len(chain) > 1:
            modeler.unite(list(chain), keep_originals=False)
        if head not in modeler.object_names:
            raise RuntimeError(f"unite 后 {head} 不在 object_names（#310 校验）")
        net_names.append(head)
    consumed = {n for chain in SHEET_CHAINS[template] for n in chain} - set(net_names)
    stray = [n for n in consumed if n in modeler.object_names]
    if stray:
        raise RuntimeError(f"unite 残留旧对象：{stray}")
    hfss.assign_perfecte_to_sheets(assignment=net_names, name="NetPEC")
    hfss.assign_perfecte_to_sheets(assignment=["Ground"], name="GndPEC")

    # 空气域 + 辐射边界（y 端面留给波端口，mline r4 同口径）
    modeler.create_box(origin=[-XHALF_MM, -board, 0.0],
                       sizes=[2 * XHALF_MM, 2 * board, ZTOP_MM],
                       name="Air", material="vacuum")
    try:
        modeler.subtract("Air", ["Substrate", *solids])
    except Exception as exc:            # 兜底记日志：sheet/实体与 air 重叠亦可解
        _log(f"WARN subtract 失败（{exc}），按重叠对象继续")

    tol = 1e-3
    open_faces = []
    for face in modeler.get_object_faces("Air"):
        cx, _cy, cz = (float(v) for v in modeler.get_face_center(face))
        if abs(abs(cx) - XHALF_MM) < tol or abs(cz - ZTOP_MM) < tol:
            open_faces.append(face)
    if not open_faces:
        raise RuntimeError("辐射面过滤为空：检查面心单位（#285）")
    hfss.assign_radiation_boundary_to_faces(assignment=open_faces, name="Radiation")

    # 4 只单模大截面波端口 + deembed 到 openEMS 同款测量面（MeasPlaneShift 单源）
    for pt in lay["ports"]:
        nm = f"P{pt['nr']}sheet"
        modeler.create_rectangle(
            orientation="ZX",
            origin=[pt["xc_mm"] - PORT_W_MM / 2.0, pt["y_face_mm"], 0.0],
            sizes=[PORT_H_MM, PORT_W_MM], name=nm)
        face = modeler.get_object_faces(nm)[0]
        hfss.wave_port(assignment=face, name=f"P{pt['nr']}", impedance=50.0,
                       renormalize=True, integration_line=Gravity.ZPos, modes=1,
                       deembed=pt["deembed_mm"])
    excit = [e for e in hfss.excitation_names if str(e).upper().startswith("P")]
    if len(excit) != 4:
        raise RuntimeError(f"波端口数 {len(excit)} != 4：{hfss.excitation_names}")
    return {"n_ports": 4,
            "deembed_mm": {f"P{p['nr']}": p["deembed_mm"] for p in lay["ports"]},
            "board_y_mm": board}


def make_setup(adapter) -> str:
    """自适应 @2.5GHz + 2-3GHz 401 点插值扫频（同 openEMS 频轴）。

    网格收敛自检用环境变量收紧：RFAUTO_C4_ARB_DELTA_S /
    RFAUTO_C4_ARB_MAX_PASSES；产物名后缀 RFAUTO_C4_ARB_TAG。
    """
    import os

    hfss = adapter.session.hfss
    setup = hfss.create_setup(name="Setup")
    setup.props["Frequency"] = "2.5GHz"
    setup.props["MaxDeltaS"] = float(os.environ.get("RFAUTO_C4_ARB_DELTA_S", "0.02"))
    setup.props["MaximumPasses"] = int(os.environ.get("RFAUTO_C4_ARB_MAX_PASSES", "12"))
    setup.update()
    hfss.create_linear_count_sweep(
        setup="Setup", unit="GHz", start_frequency=FREQ_GHZ[0],
        stop_frequency=FREQ_GHZ[1], num_of_freq_points=FREQ_GHZ[2],
        name="Sweep", sweep_type="Interpolating", save_fields=False)
    return "Setup"


def analyze_template(template: str, s4p: Path, solve_info: dict[str, Any]) -> dict[str, Any]:
    """读 .s4p → @f0 指标 + 三方对账（纯判读，离线可复用）。"""
    import skrf

    lay = load_template_layout(template)
    f0 = lay["f0_ghz"]
    net = skrf.Network(str(s4p))
    f_ghz = net.f / 1e9
    s = net.s
    i = int(np.argmin(np.abs(f_ghz - f0)))
    db = 20.0 * np.log10(np.abs(s[i]) + 1e-12)
    sig = float(np.max(np.linalg.svd(s, compute_uv=False)[:, 0]))
    recip = float(np.max(np.abs(s - np.transpose(s, (0, 2, 1)))))
    metrics = {"f_ghz": float(f_ghz[i]), "s11_db": float(db[0, 0]),
               "s21_db": float(db[1, 0]), "s31_db": float(db[2, 0]),
               "s41_db": float(db[3, 0]),
               "phase_s31_minus_s21_deg": float(np.degrees(
                   np.angle(s[i, 2, 0]) - np.angle(s[i, 1, 0])))}
    role_ok = ((metrics["s21_db"] > metrics["s31_db"]) if template == "cline_coupler"
               else abs(metrics["s21_db"] - metrics["s31_db"]) < 1.5)
    oe = openems_reference(template)
    judge = judge_reference_db(template)
    if oe is None:
        raise RuntimeError(f"openEMS 参照缺失：{OE_REF_DIR / (template + '_judge.json')}")
    three = three_way_verdict(metrics["s31_db"], oe["s31_db"], judge["s31_db"])
    return {"template": template, "s4p": str(s4p), "hfss": metrics,
            "sigma_max": sig, "sigma_max_ok": bool(sig <= SIGMA_MAX_GATE),
            "recip_max": recip, "port_role_check_ok": bool(role_ok),
            "openems_ref": oe, "judge_ref": judge, "three_way": three,
            "solve": solve_info, "params": lay["params"],
            "s_over_h": lay["params"]["gap_mm"] / H_SUB_MM}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--templates", nargs="+", default=list(TEMPLATES))
    args = parser.parse_args(argv)

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    assert_desktop_idle()

    import os

    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.infra.version_probe import resolve_aedt_install

    tag = os.environ.get("RFAUTO_C4_ARB_TAG", "")
    suffix = ("_" + tag) if tag else ""
    install = resolve_aedt_install(None)
    assert install is not None, "未发现可用 AEDT 安装"
    version = install["aedt_version"]
    _log(f"AEDT {version}；模板顺序 {args.templates}")

    adapter = HfssAdapter()
    adapter.connect({"desktop_version": version, "non_graphical": True})
    results: dict[str, Any] = {}
    try:
        for template in args.templates:
            elapsed = time.time() - t0
            if elapsed + BUDGET_FRACTION_PER_TEMPLATE * BUDGET_TOTAL_S > BUDGET_TOTAL_S:
                _log(f"预算缺口：已耗时 {elapsed:.0f}s，跳过 {template}")
                results[template] = {"skipped": "budget"}
                continue
            _log(f"=== {template} build 开始（累计 {elapsed:.0f}s）")
            adapter.open_or_create_project(
                WORK_DIR / f"c4_{template}.aedt", f"c4_{template}")
            tb = time.time()
            build_info = build_template(adapter, template)
            _log(f"=== {template} build 完成 {time.time() - tb:.0f}s")
            setup_name = make_setup(adapter)
            ts = time.time()
            report = adapter.solve(setup_name, timeout_s=SOLVE_TIMEOUT_S)
            assert report.success, f"求解失败: {report.message}"
            solve_info = {"solve_s": round(time.time() - ts, 1),
                          "aedt_version": version,
                          "deembed_mm": build_info["deembed_mm"],
                          "max_delta_s": float(
                              os.environ.get("RFAUTO_C4_ARB_DELTA_S", "0.02")),
                          "max_passes": int(
                              os.environ.get("RFAUTO_C4_ARB_MAX_PASSES", "12")),
                          "tag": tag}
            with contextlib.suppress(Exception):
                setup = adapter.session.hfss.get_setup(setup_name)
                if setup is not None:
                    passes, delta_s = HfssAdapter._extract_convergence(setup)
                    solve_info["passes"] = passes
                    solve_info["final_delta_s"] = delta_s
            _log(f"=== {template} solve 完成 {solve_info['solve_s']}s")
            s4p = adapter.export_touchstone(
                WORK_DIR / f"{template}_arbitration{suffix}.s4p")
            results[template] = analyze_template(template, Path(s4p), solve_info)
            r = results[template]
            _log(f"[{template}] @f0 S31={r['hfss']['s31_db']:.2f}dB "
                 f"S21={r['hfss']['s21_db']:.2f} S11={r['hfss']['s11_db']:.1f} "
                 f"S41={r['hfss']['s41_db']:.1f} σmax={r['sigma_max']:.4f} | "
                 f"oe={r['openems_ref']['s31_db']:.2f} "
                 f"judge={r['judge_ref']['s31_db']:.2f} "
                 f"→ {r['three_way']['verdict']}")
    finally:
        adapter.close(save=True)      # #265：finally 必须 release_desktop

    # 汇总
    judged = {t: r for t, r in results.items() if "three_way" in r}
    sides = {t: r["three_way"]["side"] for t, r in judged.items()}
    if judged and all(v == "openems" for v in sides.values()):
        conclusion = ("假设成立：HFSS 与 openEMS 归一后一致（±0.5dB 内），裁判闭式在 "
                      "s/h<0.1~0.16 域不适用——裁判口径需按 HFSS 修正")
        confidence = "high" if len(judged) == 2 else "medium（仅单模板进判）"
    elif judged and all(v == "judge" for v in sides.values()):
        conclusion = ("假设不成立：HFSS 与裁判闭式一致——引擎系统性偏差，方向指向 "
                      "x 向加密/边缘建模")
        confidence = "high" if len(judged) == 2 else "medium（仅单模板进判）"
    elif judged:
        conclusion = f"两模板判向不一致：{sides}——逐模板看，无单一结论"
        confidence = "low"
    else:
        conclusion = "无有效模板进判（全部 skipped/失败）"
        confidence = "none"
    verdict = {"id": "hfss_c4_arbitration",
               "hypothesis": "裁判闭式在 lange s/h=0.076（<KJ 有效域 0.1，cline 0.161 "
                             "边缘）不适用——'裁判错'而非'引擎错'（C4 下一假设①）",
               "gates": {"tol_side_db": TOL_SIDE_DB, "sigma_max_gate": SIGMA_MAX_GATE,
                         "primary_metric": "|S31| @f0=2.5GHz（deembed 后 50Ω 口径）"},
               "budget_total_s": BUDGET_TOTAL_S, "wall_s": round(time.time() - t0, 1),
               "port": {"w_mm": PORT_W_MM, "h_mm": PORT_H_MM, "modes": 1,
                        "note": "每馈线独立单模波端口（单微带准 TEM 线），不涉 #307 "
                                "双导体模阻抗换算；renormalize 50Ω"},
               "declared_differences": [
                   "零厚度 PEC sheet 走线（=openEMS AddMetal）；air-bridge/立柱按真实"
                   "三维 pec 实体（#264）",
                   "jog 端向 0.02mm 面积重叠垫片（HFSS 薄片 unite 需面积重叠，#310）",
                   "吸收边界：HFSS 辐射（顶+两侧）vs openEMS PML_8；地=域底 PerfectE"
                   "（无限地面语义）",
                   "波端口 deembed 到 openEMS MeasPlaneShift 同款测量面（单源读取）",
                   "介质损耗 tanδ=0.0037 与 openEMS 同；导体无耗同 openEMS",
               ],
               "templates": results, "sides": sides, "conclusion": conclusion,
               "confidence": confidence}
    out = WORK_DIR / f"verdict{suffix}.json"
    out.write_text(json.dumps(verdict, ensure_ascii=False, indent=1, default=str) + "\n",
                   encoding="utf-8")
    _log(f"verdict → {out}；conclusion={conclusion}（confidence={confidence}）")
    print(f"C4_ARB_CONCLUSION_{verdict['confidence']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
