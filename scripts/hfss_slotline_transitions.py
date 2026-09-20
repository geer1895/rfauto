"""HFSS 波端口仲裁：MSL↔slotline 过渡 + Marchand 双槽臂巴伦。

大截面波端口口径（路线 B 实证：微带惯例窄框=fin-line 截止倏逝模）：
- 槽线口 P2/P3 = **端面全截面**波端口（板宽=端口宽），积分线跨槽 z=0，
  CharImp=Zpv、renormalize=False → 广义模态 S（线基，与 Zo 定义无关）；
- 微带口 P1 = 5w×5h 惯例波端口（微带无该陷阱；底面整版地），CharImp=Zpi，
  renormalize=False → 微带线基；
- 巴伦两口极性与 openEMS 同约定（积分线均 y 递增：槽 1 跨[中条→外地]、
  槽 2 跨[外地→中条]）——推挽平衡 ⇒ S21/S31 同相（相位差≈0°）。

辐射边界正向选面（#191：端口面/内腔面一律不辐射）：只辐射 cz 出基板带的面
（顶带/底带/侧墙上下段）且跳过端口所在整面（x− 与 y− 过渡 / x± 与 y+ 巴伦）；
未指派外表面默认 PEC（ratrace 实证口径）。

判据（写死）：巴伦幅度不平衡 ≤1dB、P1 回损 ≤−10dB、隔离 |S23| ≤−15dB、
带内 |S21| ≥−3.5dB；过渡段带内 max|S11| ≤−10dB、S21 超额损耗 ≤1dB@f0（HFSS
无抽头基线，理想 DUT 基线=0dB）；β 对闭式 ≤5%（信息门）。达不到如实 PARTIAL。

运行（长任务分离+日志轮询 #157；stdout 落文件 #242；ansysedt 占用先等待）：
  powershell Start-Process .venv\\Scripts\\python.exe -ArgumentList
  "scripts/hfss_slotline_transitions.py" -RedirectStandardOutput ...
产物：runs/slotline_transitions/hfss/{hfss_trans*.s2p, hfss_balun*.s2p,
port_modes.json, run.log}、runs/slotline_transitions/hfss_result.json
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "runs" / "slotline_transitions" / "hfss"
RESULT = REPO / "runs" / "slotline_transitions" / "hfss_result.json"
PROGRESS = REPO / "runs" / "slotline_transitions" / "progress.log"

# ── 设计点（与 openEMS/openems 模板逐键一致，全部字面预计算 #218）──
S_W, H, ER, TAND = 1.0, 1.524, 3.66, 0.0037
F0 = 2.5
F_LO, F_HI, N_PTS = 2.0, 3.0, 401
W_MSL = 3.3439            # 微带 50Ω（skrf HJ 综合）
X_SH = 23.3656            # 槽线短路臂 λg'/4
L_STUB = 18.3725          # 微带开路支节 λg_m/4+Δl
Y_TIP_TRANS = 0.5 + L_STUB        # 过渡段支节端 y（+）
Y_TIP_BALUN = -(2.6719 + L_STUB)  # 巴伦支节端 y（−，a2=2.6719）
A1, A2 = 1.6719, 2.6719   # 巴伦槽内/外缘
X_PORT = 40.0
DOM_X = 58.235            # x_port + 16·BASE（与 openEMS 同域）
DOM_Y = 50.0
Z_BOT, Z_TOP = 30.0, 20.0
PORT_W_MSL = 5 * W_MSL    # 16.7195
PORT_H_MSL = 5 * H        # 7.62
TIMEOUT_S = int(os.environ.get("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "7200"))


def _load_arb():
    """按路径加载路线 B 仲裁脚本模块（复用 _mm/_kill_desktops/端口模数据，只读）。"""
    spec = importlib.util.spec_from_file_location(
        "_slot_arb", REPO / "scripts" / "hfss_slotline_arbitration.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


ARB = _load_arb()
_mm = ARB._mm
_kill_desktops = ARB._kill_desktops
_extract_port_modes = ARB._extract_port_modes


def _progress(msg: str) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def _write_result(patch: dict) -> None:
    data = {}
    if RESULT.exists():
        data = json.loads(RESULT.read_text(encoding="utf-8"))
    data.update(patch)
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                      encoding="utf-8")


def wait_ansysedt_free(busy_timeout_s: float) -> None:
    """先到先得：ansysedt.exe 在跑则 60s 轮询等待（预声明规则）。"""
    t0 = time.time()
    while True:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ansysedt.exe"],
                           capture_output=True, text=True)
        if "ansysedt.exe" not in (r.stdout or ""):
            return
        if time.time() - t0 > busy_timeout_s:
            raise SystemExit(
                f"ansysedt.exe 占用超 {busy_timeout_s:.0f}s，退出（他轨优先）")
        print(f"[wait] ansysedt.exe 在跑，60s 后重查（已等 {time.time() - t0:.0f}s）",
              flush=True)
        time.sleep(60)


def _bottom_boxes(kind: str) -> list[tuple[str, list[float], list[float]]]:
    """底层地板零厚盒（与 openEMS 渲染逐键同枚举，mm）。"""
    dx, dy = DOM_X, DOM_Y
    seam = 3.0 * 0.2849  # ×NEAR，与模板 METAL_SEAM_OVERLAP 同值
    if kind == "trans":
        return [
            ("GndA", [-dx, 0.5, 0.0], [X_SH + seam, dy, 0.0]),
            ("GndB", [-dx, -dy, 0.0], [X_SH + seam, -0.5, 0.0]),
            ("GndC", [X_SH, -dy, 0.0], [dx, dy, 0.0]),
        ]
    return [
        ("M1", [-dx, A2, 0.0], [dx, dy, 0.0]),
        ("M2", [-dx, -dy, 0.0], [dx, -A2, 0.0]),
        ("M3", [-dx, -A1, 0.0], [dx, A1, 0.0]),
        ("M4", [X_SH, -A2, 0.0], [dx, -A1, 0.0]),
        ("M5", [-dx, A1, 0.0], [-X_SH, A2, 0.0]),
    ]


def dump_curve_params(kind: str, *curves: Path) -> None:
    """曲线同名 stem params JSON 落盘（import_workdir_runs 键路径契约 params）。

    runs/slotline_transitions/hfss/ 是**多曲线目录**（trans/balun 主导出+
    Gamma 附注导出共存）——同名 stem 归属 + "curve" 显式引用双保险；同一
    求解的两份导出参数相同，导入端指纹去重折叠为单点。字段=设计点常量
    （与 openEMS 模板逐键一致的字面预计算值，#218/#320 单源不手抄）+ kind。
    """
    from rfauto.service.dataset_service import write_workdir_params_json

    params = {
        "kind": str(kind), "w_slot_mm": float(S_W), "h_mm": float(H),
        "er": float(ER), "tan_d": float(TAND), "f0_ghz": float(F0),
        "w_msl_mm": float(W_MSL), "x_sh_mm": float(X_SH),
        "l_stub_mm": float(L_STUB), "a1_mm": float(A1), "a2_mm": float(A2),
        "dom_x_mm": float(DOM_X), "dom_y_mm": float(DOM_Y),
        "z_bot_mm": float(Z_BOT), "z_top_mm": float(Z_TOP),
    }
    for c in curves:
        write_workdir_params_json(OUT, params, curve=c)


def _build_and_solve(kind: str) -> dict:
    """建模+求解+导出（#191 整轮重试外层管；分析失败不重解）。"""
    from ansys.aedt.core import Hfss

    y_tip = Y_TIP_TRANS if kind == "trans" else Y_TIP_BALUN
    p1_y = -DOM_Y if kind == "trans" else DOM_Y          # P1 端口面
    msl_y0 = -DOM_Y if kind == "trans" else y_tip        # 微带盒 y 范围
    msl_y1 = y_tip if kind == "trans" else DOM_Y
    work = OUT / f"project_{kind}"
    work.mkdir(parents=True, exist_ok=True)

    h = Hfss(project=str(work / f"slotline_tr_{kind}.aedt"),
             design=f"tr_{kind}", version="2025.1",
             non_graphical=True, new_desktop=True)
    try:
        h.modeler.model_units = "mm"
        with contextlib.suppress(Exception):
            h.materials.add_material("rfauto_m366", properties={
                "permittivity": ER, "dielectric_loss_tangent": TAND})

        # 基板 + 底层地板（槽开在地板上）+ 顶层微带 + 空气域
        h.modeler.create_box(origin=[_mm(-DOM_X), _mm(-DOM_Y), "0mm"],
                             sizes=[_mm(2 * DOM_X), _mm(2 * DOM_Y), _mm(H)],
                             name="Sub", material="rfauto_m366")
        h.modeler["Sub"].solve_inside = True
        metal_names = []
        for _i, (name, lo, hi) in enumerate(_bottom_boxes(kind)):
            h.modeler.create_box(origin=[_mm(lo[0]), _mm(lo[1]), _mm(lo[2])],
                                 sizes=[_mm(hi[0] - lo[0]), _mm(hi[1] - lo[1]),
                                        "0mm"], name=name, material="pec")
            metal_names.append(name)
        h.modeler.create_box(origin=[_mm(-W_MSL / 2), _mm(msl_y0), _mm(H)],
                             sizes=[_mm(W_MSL), _mm(msl_y1 - msl_y0), "0mm"],
                             name="MslTop", material="pec")
        metal_names.append("MslTop")
        h.modeler.create_box(origin=[_mm(-DOM_X), _mm(-DOM_Y), _mm(-Z_BOT)],
                             sizes=[_mm(2 * DOM_X), _mm(2 * DOM_Y),
                                    _mm(Z_BOT + H + Z_TOP)],
                             name="Air", material="vacuum")
        h.modeler.subtract("Air", ["Sub", *metal_names])
        h.modeler["Air"].solve_inside = True
        h.assign_perfecte_to_sheets(assignment=metal_names, name="MetalPEC")

        # ── 波端口 ──
        # P1 微带（5w×5h 惯例，ZX 面法向 Y：sizes=[宽沿 Z, 高沿 X]，ratrace 口径）
        h.modeler.create_rectangle(
            orientation="ZX", origin=[_mm(-PORT_W_MSL / 2), _mm(p1_y), "0mm"],
            sizes=[_mm(PORT_H_MSL), _mm(PORT_W_MSL)], name="P1sheet")
        h.wave_port(assignment=h.modeler.get_object_faces("P1sheet")[0],
                    name="P1P", impedance=50.0, renormalize=False, modes=1,
                    integration_line=[["0mm", _mm(p1_y), "0mm"],
                                      ["0mm", _mm(p1_y), _mm(H)]],
                    characteristic_impedance="Zpi")
        # 槽线口：端面全截面 YZ（路线 B 大截面口径），积分线跨槽 z=0、y 递增
        slot_ports = (["P2sheet", -DOM_X, -0.5, 0.5] if kind == "trans" else
                      ["P2sheet", DOM_X, A1, A2])
        specs = [slot_ports]
        if kind == "balun":
            specs.append(["P3sheet", -DOM_X, -A2, -A1])
        for name, x_face, y_lo, y_hi in specs:
            h.modeler.create_rectangle(
                orientation="YZ", origin=[_mm(x_face), _mm(-DOM_Y),
                                          _mm(-Z_BOT)],
                sizes=[_mm(2 * DOM_Y), _mm(Z_BOT + H + Z_TOP)], name=name)
            h.wave_port(assignment=h.modeler.get_object_faces(name)[0],
                        name=name + "P", impedance=50.0, renormalize=False,
                        modes=1,
                        integration_line=[[_mm(x_face), _mm(y_lo), "0mm"],
                                          [_mm(x_face), _mm(y_hi), "0mm"]],
                        characteristic_impedance="Zpv")

        # ── 辐射边界：cz 出基板带的面，且跳过端口整面（#191 正向选面）──
        air_faces = h.modeler.get_object_faces("Air")
        open_faces = []
        for f in air_faces:
            cx, cy, cz = h.modeler.get_face_center(f)
            if not (cz > H + 1e-6 or cz < -1e-6):
                continue                       # 内腔面/基板带（贴材料界面）
            if kind == "trans" and (abs(cx + DOM_X) < 1e-6
                                    or abs(cy + DOM_Y) < 1e-6):
                continue                       # P2 端口面 / P1 端口面
            if kind == "balun" and (abs(abs(cx) - DOM_X) < 1e-6
                                    or abs(cy - DOM_Y) < 1e-6):
                continue                       # P2/P3 端口面 / P1 端口面
            open_faces.append(f)
        h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")

        setup = h.create_setup(name="Setup")
        setup.props["Frequency"] = f"{F0!r}GHz"
        setup.props["MaxDeltaS"] = 0.02
        setup.props["MaximumPasses"] = 15
        setup.update()
        h.create_linear_count_sweep(setup="Setup", unit="GHz",
                                    start_frequency=F_LO, stop_frequency=F_HI,
                                    num_of_freq_points=N_PTS, name="Sweep",
                                    sweep_type="Interpolating",
                                    save_fields=False)
        box: dict = {"done": False, "err": None}

        def _go() -> None:
            try:
                h.analyze(setup="Setup")
                box["done"] = True
            except Exception as exc:
                box["err"] = repr(exc)

        t0 = time.time()
        th = threading.Thread(target=_go, daemon=True)
        th.start()
        th.join(timeout=TIMEOUT_S)
        solve_s = round(time.time() - t0, 1)
        if not box["done"]:
            raise RuntimeError(f"solve watchdog 超时（>{TIMEOUT_S}s）err={box['err']}")
        print(f"[{kind}] solve_s={solve_s}", flush=True)

        # 端口模数据（Zpv/Zpi LastAdaptive，best-effort 留档）
        pnames = tuple(["P1P"] + [s[0] + "P" for s in specs])
        port_data, pm_meta = _extract_port_modes(h, pnames)

        # .s2p 导出（广义模态 S）+ Gamma/Zo 注释附注
        from rfauto.adapters.hfss_adapter import HfssAdapter

        adapter = HfssAdapter()
        adapter.session.hfss = h
        s2p = adapter.export_touchstone(OUT / f"hfss_{kind}.s2p")
        s2p_gamma = OUT / f"hfss_{kind}_gamma.s2p"
        h.osolution.ExportNetworkData(
            "", ["Setup:Sweep"], 3, str(s2p_gamma).replace("\\", "/"),
            ["all"], False, 50, "S", -1, 0, 15, False, True, False)
        if not s2p_gamma.exists():
            raise RuntimeError(f"Gamma 附注 touchstone 未落盘: {s2p_gamma}")
        dump_curve_params(kind, s2p, s2p_gamma)
        return {"ok": True, "solve_s": solve_s, "s2p": str(s2p),
                "s2p_gamma": str(s2p_gamma),
                "port_modes": {"ports": port_data, "extraction": pm_meta}}
    finally:
        with contextlib.suppress(Exception):
            h.release_desktop(close_projects=True, close_desktop=True)


# ─────────────────────────────── 分析（纯函数，离线可测） ───────────────────────────────

def analyze_hfss_run(kind: str, f_hz: np.ndarray, s_gen: np.ndarray,
                     gamma: np.ndarray) -> dict:
    """广义模态 S（线基）→ β 对拍 + core 判据（HFSS 无抽头基线=0dB 口径）。

    从 rfauto.core.slotline_transitions 引 transition_metrics/balun_metrics；
    β_slot = Gamma(槽口) 虚部 @f0；β_msl = Gamma(P1)（微带锚对照）。
    """
    from rfauto.core.slotline import slotline_closed_form
    from rfauto.core.slotline_transitions import balun_metrics, transition_metrics

    f0_hz = F0 * 1e9
    i0 = int(np.argmin(np.abs(f_hz - f0_hz)))
    cf = slotline_closed_form(S_W, H, ER, F0)
    gamma = np.asarray(gamma, dtype=complex)
    beta_msl = gamma[:, 0].imag                 # P1 列（微带 Zpi 口）
    beta_slot = gamma[:, 1].imag                # P2 列（槽线 Zpv 口）
    k0 = 2 * np.pi * f0_hz / 299792458.0
    out: dict = {
        "beta_slot_f0_rad_m": float(beta_slot[i0]),
        "beta_slot_vs_cf_pct": (float(beta_slot[i0]) / cf.beta_rad_m - 1) * 100,
        "beta_msl_f0_rad_m": float(beta_msl[i0]),
        "eps_eff_slot_f0": (float(beta_slot[i0]) / k0) ** 2,
        "reciprocity_max_lin": float(np.max(np.abs(
            s_gen - np.transpose(s_gen, (0, 2, 1))))),
        "passive_max_ev": float(np.max(np.abs(
            np.linalg.eigvalsh(s_gen @ np.conj(np.swapaxes(s_gen, 1, 2)))))),
    }
    if kind == "trans":
        m = transition_metrics(f_hz, s_gen[:, 0, 0], s_gen[:, 1, 0], (2.25, 2.75),
                               s21_ideal_db_f0=0.0)
        out["metrics"] = m
    else:
        m = balun_metrics(f_hz, s_gen[:, 0, 0], s_gen[:, 1, 0], s_gen[:, 2, 0],
                          s_gen[:, 1, 2], (2.25, 2.75))
        out["metrics"] = m
    return out


def analyze_products(kind: str) -> dict:
    """读 touchstone 产物 → analyze_hfss_run（skrf 解析注释，不 import pyaedt）。"""
    import skrf
    from skrf.io.touchstone import hfss_touchstone_2_gamma_z0

    s2p = OUT / f"hfss_{kind}.s2p"
    if not s2p.exists():
        s2p = OUT / f"hfss_{kind}.s3p"   # N 端口 touchstone 扩展名随端口数
    s2p_gamma = OUT / f"hfss_{kind}_gamma.s2p"
    net = skrf.Network(str(s2p))
    # HFSS ExportNetworkData 按给定文件名落盘但内容为 N 端口格式：skrf 解析器
    # 按扩展名推断端口数 → 3 端口须 .s3p 命名副本（route B 2 端口无此问题）
    gamma_path = s2p_gamma
    if net.s.shape[1] > 2:
        gamma_path = OUT / f"hfss_{kind}_gamma.s{net.s.shape[1]}p"
        if not gamma_path.exists():
            shutil.copyfile(s2p_gamma, gamma_path)
    f_g, gamma_arr, _z0_arr = hfss_touchstone_2_gamma_z0(str(gamma_path))
    gamma = gamma_arr
    if gamma is None:
        raise RuntimeError(f"[{kind}] gamma touchstone 无 Gamma 注释")
    if len(f_g) != len(net.f) or not np.allclose(f_g, net.f):
        raise RuntimeError(f"[{kind}] 两份 touchstone 频率轴不一致")
    out = analyze_hfss_run(kind, net.f, net.s, gamma)
    out["s2p"] = str(s2p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyze-only", action="store_true")
    ap.add_argument("--kinds", default="trans,balun")
    ap.add_argument("--busy-timeout-s", type=float, default=2 * 3600)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = [k.strip() for k in args.kinds.split(",") if k.strip()]
    _write_result({"stage": "start", "design": {
        "s_w_mm": S_W, "h_mm": H, "er": ER, "tan_d": TAND, "f0_ghz": F0,
        "w_msl_mm": W_MSL, "x_sh_mm": X_SH, "l_stub_mm": L_STUB,
        "dom_x_mm": DOM_X, "dom_y_mm": DOM_Y, "z_bot_mm": Z_BOT,
        "z_top_mm": Z_TOP,
        "sweep": f"{F_LO}-{F_HI}GHz {N_PTS}pt interpolating",
        "port_convention": "P1=Zpi 微带线基；P2/P3=Zpv 槽线线基（广义 S）"}})
    if not args.analyze_only:
        wait_ansysedt_free(args.busy_timeout_s)
        for kind in wanted:
            last_err = None
            for attempt in range(3):
                try:
                    _kill_desktops()
                    shutil.rmtree(OUT / f"project_{kind}", ignore_errors=True)
                    res = _build_and_solve(kind)
                    _write_result({"stage": f"solved_{kind}",
                                   "attempt": attempt + 1,
                                   f"solve_s_{kind}": res["solve_s"]})
                    _progress(f"stage5 hfss/{kind}: solved "
                              f"{res['solve_s']}s attempt={attempt + 1}")
                    break
                except Exception as exc:
                    last_err = repr(exc)
                    print(f"[{kind}] attempt {attempt + 1}/3 FAIL: {last_err}",
                          flush=True)
                    _write_result({"stage": f"attempt_failed_{kind}",
                                   "attempt": attempt + 1, "error": last_err})
            else:
                _write_result({"stage": f"failed_all_attempts_{kind}",
                               "error": last_err})
                _progress(f"stage5 hfss/{kind}: FAILED all attempts {last_err}")
        _kill_desktops()

    analyses: dict = {}
    for kind in wanted:
        try:
            analyses[kind] = analyze_products(kind)
            print(f"[{kind}] metrics={json.dumps(analyses[kind]['metrics']['gates'])}",
                  flush=True)
        except Exception as exc:
            analyses[kind] = {"error": repr(exc)}
            print(f"[{kind}] analysis FAIL: {exc!r}", flush=True)
    gates: dict = {}
    if "trans" in analyses and "metrics" in analyses["trans"]:
        gates.update({f"trans_{k}": v
                      for k, v in analyses["trans"]["metrics"]["gates"].items()})
        gates["trans_beta_info_le_5pct"] = (
            abs(analyses["trans"]["beta_slot_vs_cf_pct"]) <= 5.0)
    if "balun" in analyses and "metrics" in analyses["balun"]:
        gates.update({f"balun_{k}": v
                      for k, v in analyses["balun"]["metrics"]["gates"].items()})
        gates["balun_isolation_le_minus15db"] = analyses["balun"][
            "metrics"]["gates"].get("isolation_le_minus15db", False)
        gates["balun_beta_info_le_5pct"] = (
            abs(analyses["balun"]["beta_slot_vs_cf_pct"]) <= 5.0)
    _write_result({"stage": "done", "analyses": analyses, "gates": gates})
    print(json.dumps(gates, indent=1, ensure_ascii=False), flush=True)
    _progress(f"stage5 hfss done: gates={gates}")
    hard = [v for k, v in gates.items() if "info" not in k]
    print(f"SLOTLINE_TRANS_HFSS_{'PASS' if all(hard) else 'FAIL'}", flush=True)
    return 0 if all(hard) else 1


if __name__ == "__main__":
    raise SystemExit(main())
