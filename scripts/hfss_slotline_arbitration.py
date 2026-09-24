"""槽线（slotline）HFSS 波端口仲裁基准（路线 B，阶段 1）。

背景：openEMS 无 slotline 端口原语；HFSS 波端口对端口截面解二维本征模，
天然支持槽线——
本脚本用真机数字钉死"波端口能不能做槽线仲裁基准"的答案。

同几何口径（与路线 A runs/slotline_port_a 设计点逐键一致，三方可比）：
- W=1.0mm 槽宽、RO4350B 基板 er=3.66/tand=0.0037/h=1.524mm、f0=2.5GHz、
  线长 L=1λ'=93.4624mm（core/slotline 闭式：εeff=1.6462、β=67.227rad/m、
  Z0=110.92Ω）；
- 名义示例 h=0.508/w=0.5 在 2.5GHz 落闭式有效域外（d/λ0=0.00424<0.006，
  core/slotline.slotline_segment 显式 ValueError），按"闭式有效范围内"硬
  约束与路线 A 可比性取 h=1.524（本 docstring 即偏离说明）；
- 开放槽线（单面金属、无背板）：基板 z∈[0,h]，金属零厚 PEC sheet z=h，
  槽 |y|≤W/2 贯通至两端板缘（端口参考面=板缘，线长即两端口间距）；
- 板宽=端口宽（端口面覆盖整个端截面）；3D 外表面顶/底/两侧 y 墙=辐射边界
  （开放结构），x 两端=端口面。

波端口尺寸——**槽线特有陷阱（首跑真机实证）**：
- 首跑按微带官方惯例（#191：5×w 宽、4×h 高 + 2h 下方空气，5.0×10.668mm）
  → 端口模式 γ=206.8+j0.02 /m、Zo≈j31Ω、S21=−24dB：**截止倏逝模**。根因：
  HFSS 波端口外框默认 Perfect E，框把槽两侧地短接 → 端口截面=带槽金属隔板
  的封闭矩形波导（fin-line），单导体无 TEM，主模截止 ≈9.9GHz（由 α 反推
  kc=206.8/m），2.5GHz 不传播——即"端口边界贴地"的闭合端口口径。
- 修正：端口截面必须**大到框短接的 fin-line 主模在带内传播、且框远离槽场**
  （槽模横向渐近衰减 κ=k0√(εeff−1)≈42/m → 1/e≈24mm）。取三档：
  mid y±40/z(−20,h+20)mm、**wide y±60/z(−30,h+30)mm（=路线 A openEMS
  截面，基准档）**、xl y±90/z(−45,h+45)mm——mid→wide→xl 收敛量化框截断
  （假设/待证 → 三档实测）。narrow5w 产物留证（hfss_slotline_narrow5w*）。
- 积分线跨槽（槽缘→槽缘 @z=h，Zpv 电压路径=槽电压）；Driven Modal 1 模
  （HFSS 按 β 降序排模，槽模 εeff≈1.65 高于框内平行板/盒模 εeff≈1，居首）；
  2-3GHz 线性 401 点 Interpolating 扫描。

导出与判据：
- renormalize=False → 广义模态 S（与 Zo 定义无关；均匀线 S21=e^{−γL}）；
  CharImp：P1=Zpv（闭式定义）、P2=Zpi——两口截面全同（均匀线），
  ExportNetworkData(IncludeGammaImpedance=True) 让 HFSS 把各口 Gamma(f)/Zo(f)
  写进 touchstone 注释（skrf.io.touchstone.hfss_touchstone_2_gamma_z0 解析），
  一次求解同时得 Zpv(f)/Zpi(f)，Zvi=√(Zpi·Zpv)（HFSS 三定义恒等式）；对称性
  由 P1/P2 Gamma 逐频一致性背书（Modal Solution Data 类别只有 Gamma/Port Zo，
  运行时发现实证，无独立 Zpi/Zpv/Zvi 类别）。
- 判据：HFSS β(Gamma 虚部 @f0) vs 闭式 ≤5%（闭式自身拟合 ~2%）；S21 绝对
  相位独立复核 β（参考面=端口面，零端口延伸即去嵌口径；广义 S 已是线基）；
  三种 Z0 定义 vs 闭式 Z0 逐一记录不硬判（闭式=功率-电压定义，预期 Zpv 最近）。
- 50Ω 基（对拍口径）由 skrf 用 Zpv(f) 离线重归一。

运行（长任务分离+日志轮询，#157；stdout 落文件 #242；#191 整轮重试 ≤2 只包
"建模+求解+导出"，分析失败不重解（首跑因分析段 skrf 顶层无该函数三次重解，
教训）；--analyze-only 只对既有产物重分析）：
  powershell Start-Process .venv\\Scripts\\python.exe -ArgumentList
  "scripts/hfss_slotline_arbitration.py" -RedirectStandardOutput ...
产物：runs/slotline_arbitration/hfss/{hfss_slotline_<档>.s2p, hfss_slotline_<档>
  _gamma.s2p, port_modes.json, run.log}、runs/slotline_arbitration/hfss_arbitration.json
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "runs" / "slotline_arbitration" / "hfss"
RESULT = REPO / "runs" / "slotline_arbitration" / "hfss_arbitration.json"
PROGRESS = REPO / "runs" / "slotline_arbitration" / "progress.log"

# ── 设计点（与路线 A runs/slotline_port_a 逐键一致；全部字面预计算 #218）──
W = 1.0                  # 槽宽 mm
H = 1.524                # 基板厚 mm（RO4350B 60mil）
ER, TAND = 3.66, 0.0037
F0 = 2.5                 # GHz
L = 93.4624              # 线长 mm（=1λ' @2.5GHz 闭式）
F_LO, F_HI, N_PTS = 2.0, 3.0, 401
TIMEOUT_S = int(os.environ.get("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "7200"))

# 波端口/板截面三档（mm，显式半宽与上下空气）：wide=路线 A 截面=基准档
PORT_VARIANTS = [
    {"tag": "mid", "y_half_mm": 40.0, "z_bot_mm": 20.0, "z_top_mm": 20.0},
    {"tag": "wide", "y_half_mm": 60.0, "z_bot_mm": 30.0, "z_top_mm": 30.0},
    {"tag": "xl", "y_half_mm": 90.0, "z_bot_mm": 45.0, "z_top_mm": 45.0},
]
PRIMARY_TAG = "wide"
# 首跑窄档（微带惯例 5×w×4h+2h）留证：倏逝模实证，不再求解，只重分析
NARROW_TAG = "narrow5w"


def _mm(v: float) -> str:
    return f"{v!r}mm"


def _progress(msg: str) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def _kill_desktops(*, strict: bool = True) -> None:
    """ansysedt 清场（治理单源）：孤儿点杀+活桌面 fail-closed（#245/#265）。

    attempt 起点用缺省 strict=True（活桌面 fail-closed 抛错，重试架如实
    记失败）；全场收尾扫尾传 strict=False（活桌面/枚举失败只记录不抛，
    不连坐已完成战役，#105）。委托 src/rfauto/infra/desktop_guard.py；
    旧 Get-Process|Stop-Process -Force 无条件代杀已废弃（#265）。
    """
    from rfauto.infra.desktop_guard import kill_orphan_ansysedt_desktops

    kill_orphan_ansysedt_desktops(log=print, strict=strict)


def _write_result(patch: dict) -> None:
    data = {}
    if RESULT.exists():
        data = json.loads(RESULT.read_text(encoding="utf-8"))
    data.update(patch)
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                      encoding="utf-8")


def _extract_port_modes(h, port_names: tuple[str, ...]) -> tuple[dict, dict]:
    """Modal Solution Data @LastAdaptive：运行时发现量类别→逐量取值（best-effort）。

    不猜量名字串：先 available_quantities_categories 列出类别（记录进产物
    作证据），再按类别取 available_report_quantities 的精确量名；单类别失败
    只记 error，不拖垮整轮（观测性 best-effort，#105）。pyaedt 1.4
    SolutionData 取值 API = get_expression_data(expr, formula)。
    """
    meta: dict = {"categories": None, "errors": []}
    data: dict = {pn: {} for pn in port_names}
    sol_name = "Setup : LastAdaptive"
    try:
        cats = h.post.available_quantities_categories(
            report_category="Modal Solution Data", solution=sol_name)
        meta["categories"] = sorted(set(cats)) if cats else []
    except Exception as exc:
        meta["errors"].append(f"categories: {exc!r}")
        return data, meta
    wanted = [c for c in meta["categories"]
              if any(k in c for k in ("Gamma", "Zo", "Zpi", "Zpv", "Zvi"))]
    meta["wanted_categories"] = wanted
    for cat in wanted:
        try:
            qs = h.post.available_report_quantities(
                report_category="Modal Solution Data", solution=sol_name,
                quantities_category=cat)
            qs = list(qs) if qs else []
            meta.setdefault("quantities", {})[cat] = qs
            if not qs:
                continue
            sol = h.post.get_solution_data(
                expressions=qs, setup_sweep_name=sol_name,
                report_category="Modal Solution Data")
            if sol is None:
                meta["errors"].append(f"{cat}: get_solution_data None")
                continue
            for q in qs:
                try:
                    _x, re_ = sol.get_expression_data(q, formula="real")
                    _x, im_ = sol.get_expression_data(q, formula="imag")
                    val = [float(np.asarray(re_).ravel()[0]),
                           float(np.asarray(im_).ravel()[0])]
                except Exception as exc:
                    meta["errors"].append(f"{q}: {exc!r}")
                    continue
                for pn in port_names:
                    if pn in q:
                        data[pn][q] = val
        except Exception as exc:
            meta["errors"].append(f"{cat}: {exc!r}")
    return data, meta


def dump_curve_params(variant: dict, *curves: Path) -> None:
    """曲线同名 stem params JSON 落盘（import_workdir_runs 键路径契约 params）。

    runs/slotline_arbitration/hfss/ 是**多曲线目录**（各 tag 主导出+Gamma
    附注导出共存）——同名 stem 归属 + "curve" 显式引用双保险；同一求解的
    两份导出参数相同，导入端指纹去重折叠为单点。字段=设计点常量+端口截面
    三档实跑值（#320：variant dict 单源，不手抄；首跑窄档 narrow5w 的端口
    字面值已不在现役常量中，不臆造补写）。
    """
    from rfauto.service.dataset_service import write_workdir_params_json

    params = {
        "w_slot_mm": float(W), "h_mm": float(H), "er": float(ER),
        "tan_d": float(TAND), "f0_ghz": float(F0), "line_len_mm": float(L),
        "tag": str(variant["tag"]),
        "port_y_half_mm": float(variant["y_half_mm"]),
        "port_z_bot_mm": float(variant["z_bot_mm"]),
        "port_z_top_mm": float(variant["z_top_mm"]),
    }
    for c in curves:
        write_workdir_params_json(OUT, params, curve=c)


def _build_and_solve(variant: dict) -> dict:
    from ansys.aedt.core import Hfss

    tag = variant["tag"]
    half_bw = float(variant["y_half_mm"])
    bw = 2.0 * half_bw                                  # 板/端口总宽 mm
    z_bot = float(variant["z_bot_mm"])                  # 基板下空气 mm
    z_top = float(variant["z_top_mm"])                  # 金属面上空气 mm
    port_h = z_bot + H + z_top                          # 端口高 mm（域顶 z=H+z_top）
    work = OUT / f"project_{tag}"
    work.mkdir(parents=True, exist_ok=True)

    h = Hfss(project=str(work / f"slotline_{tag}.aedt"),
             design=f"slotline_{tag}", version="2025.1",
             non_graphical=True, new_desktop=True)
    try:
        h.modeler.model_units = "mm"
        with contextlib.suppress(Exception):
            h.materials.add_material("rfauto_m366", properties={
                "permittivity": ER, "dielectric_loss_tangent": TAND})

        # 基板：x∈[0,L]（板长=线长，两端即端口参考面）
        h.modeler.create_box(origin=["0mm", _mm(-half_bw), "0mm"],
                             sizes=[_mm(L), _mm(bw), _mm(H)],
                             name="Sub", material="rfauto_m366")
        h.modeler["Sub"].solve_inside = True
        # 槽线金属：两块零厚 PEC sheet @z=h，槽 |y|≤W/2 贯通至两端板缘
        w_half = 0.5 * W
        h.modeler.create_box(origin=["0mm", _mm(-half_bw), _mm(H)],
                             sizes=[_mm(L), _mm(half_bw - w_half), "0mm"],
                             name="MtlLeft", material="pec")
        h.modeler.create_box(origin=["0mm", _mm(w_half), _mm(H)],
                             sizes=[_mm(L), _mm(half_bw - w_half), "0mm"],
                             name="MtlRight", material="pec")
        # 空气域（开放槽线，无背板）：随后挖去基板与金属避免材料重叠
        h.modeler.create_box(origin=["0mm", _mm(-half_bw), _mm(-z_bot)],
                             sizes=[_mm(L), _mm(bw), _mm(port_h)],
                             name="Air", material="vacuum")
        h.modeler.subtract("Air", ["Sub", "MtlLeft", "MtlRight"])
        h.modeler["Air"].solve_inside = True
        h.assign_perfecte_to_sheets(assignment=["MtlLeft", "MtlRight"],
                                    name="SlotMetalPEC")

        # 波端口：端口面=域两端全截面（板宽=端口宽），垂直传播方向（法向 X
        # → "YZ" orientation，sizes=[宽沿 Y, 高沿 Z]，ratrace 实测口径）；
        # 积分线跨槽（槽缘→槽缘 @z=h，Zpv 电压路径=槽电压）。
        # renormalize=False → 广义模态 S；CharImp P1=Zpv / P2=Zpi（见 docstring）。
        port_specs = [
            ("P1sheet", 0.0, "Zpv"), ("P2sheet", L, "Zpi"),
        ]
        for name, x_edge, char_imp in port_specs:
            h.modeler.create_rectangle(
                orientation="YZ",
                origin=[_mm(x_edge), _mm(-half_bw), _mm(-z_bot)],
                sizes=[_mm(bw), _mm(port_h)], name=name)
            face = h.modeler.get_object_faces(name)[0]
            h.wave_port(
                assignment=face, name=name + "P", impedance=50.0,
                renormalize=False, modes=1,
                integration_line=[[_mm(x_edge), _mm(-w_half), _mm(H)],
                                  [_mm(x_edge), _mm(w_half), _mm(H)]],
                characteristic_impedance=char_imp)

        # 辐射边界：只辐射开放外表面（顶面、底面、两侧 y 墙）——正向按面心
        # 坐标选取：x 两端是端口面（端口+辐射不同面，#191）；基板内腔面
        # （顶棚 z=H、侧框 cz≈H/2、底框 z=0）一律不辐射（负向过滤会选进
        # 内腔面 → "An internal radiation boundary"，ratrace run2 实败同因）。
        air_faces = h.modeler.get_object_faces("Air")
        open_faces = []
        for f in air_faces:
            cx, _cy, cz = h.modeler.get_face_center(f)
            if abs(cx) < 1e-6 or abs(cx - L) < 1e-6:
                continue                        # 端口面（x 两端）
            if cz > H + 1e-6 or cz < -1e-6:
                open_faces.append(f)            # 顶面 / 两侧墙上下半 / 底面
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
        # 求解 watchdog（#145 同口径）
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
            raise RuntimeError(f"solve watchdog 超时（>{TIMEOUT_S}s）"
                               f" err={box['err']}")
        print(f"[{tag}] solve_s={solve_s}", flush=True)

        # ── 端口模式数据：Gamma + Port Zo（Modal Solution Data，best-effort）──
        port_data, pm_meta = _extract_port_modes(h, ("P1sheetP", "P2sheetP"))
        port_modes = {
            "variant": variant,
            "port_geometry": {"total_width_mm": bw, "height_mm": port_h,
                              "air_below_mm": z_bot, "air_above_mm": z_top,
                              "ground_side_mm": half_bw - w_half},
            "freq_ghz": F0, "ports": port_data, "extraction": pm_meta,
            "solve_s": solve_s,
        }
        pm_path = OUT / "port_modes.json"
        all_pm = {}
        if pm_path.exists():
            all_pm = json.loads(pm_path.read_text(encoding="utf-8"))
        all_pm[tag] = port_modes
        pm_path.write_text(json.dumps(all_pm, indent=2, ensure_ascii=False),
                           encoding="utf-8")

        # ── .s2p 导出（HfssAdapter：内含 sweep 完成前置断言，不绕过）──
        from rfauto.adapters.hfss_adapter import HfssAdapter

        adapter = HfssAdapter()
        adapter.session.hfss = h
        s2p = adapter.export_touchstone(OUT / f"hfss_slotline_{tag}.s2p")
        print(f"[{tag}] s2p={s2p}", flush=True)
        # 附带 Gamma(f)/Zo(f) 注释的第二份导出（IncludeGammaImpedance=True）
        s2p_gamma = OUT / f"hfss_slotline_{tag}_gamma.s2p"
        h.osolution.ExportNetworkData(
            "", ["Setup:Sweep"], 3, str(s2p_gamma).replace("\\", "/"),
            ["all"], False, 50, "S", -1, 0, 15, False, True, False)
        if not s2p_gamma.exists():
            raise RuntimeError(f"Gamma 附注 touchstone 未落盘: {s2p_gamma}")
        print(f"[{tag}] s2p_gamma={s2p_gamma}", flush=True)
        dump_curve_params(variant, s2p, s2p_gamma)
        return {"ok": True, "solve_s": solve_s, "s2p": str(s2p),
                "s2p_gamma": str(s2p_gamma), "port_modes": port_modes}
    finally:
        with contextlib.suppress(Exception):
            h.release_desktop(close_projects=True, close_desktop=True)


def beta_from_s21(f_hz: np.ndarray, s: np.ndarray, z_ref_old: float,
                  z_line: float, beta_prior_f0: float, f0_hz: float,
                  line_len_m: float) -> dict:
    """S21 绝对相位 → β(f)（参考面=端口面，零端口延伸即去嵌口径）。

    步骤：① skrf 把 z_ref_old 基 S 重归一到线自身模阻抗 z_line（广义模态 S
    传同值=恒等），消掉端-线失配多重反射涟漪（|Γ|=0.375 时涟漪 ±Γ²≈±2.2% β）；
    ② β(f)=(2πn−φ(f))/L，φ 为 unwrapped arg S21，分支 n 由闭式先验在 f0
    锁定——分支步长 2π/L 恰等于 1λ' 线的 β 本身，先验只需 ±50% 精度即无歧义。
    注意不能用 dφ/dω（群时延 → dβ/dω，槽线带内 εeff 1.61→1.68 会带
    ≈+4.7% 系统偏差，合成自检抓出）。
    """
    import skrf

    freq = skrf.Frequency.from_f(np.asarray(f_hz, dtype=float), unit="Hz")
    net = skrf.Network(frequency=freq, s=np.asarray(s, dtype=complex),
                       z0=float(z_ref_old))
    net.renormalize(float(z_line))
    s_line = net.s
    phi = np.unwrap(np.angle(s_line[:, 1, 0]))
    i0 = int(np.argmin(np.abs(np.asarray(f_hz) - f0_hz)))
    n = int(np.rint((beta_prior_f0 * line_len_m + phi[i0]) / (2.0 * np.pi)))
    beta = (2.0 * np.pi * n - phi) / line_len_m
    return {"beta_rad_m": beta, "beta_f0_rad_m": float(beta[i0]),
            "branch_n": n,
            "s11_line_basis_db_f0": float(20 * np.log10(
                abs(s_line[i0, 0, 0]) + 1e-12)),
            "s21_line_basis_db_f0": float(20 * np.log10(
                abs(s_line[i0, 1, 0]) + 1e-12))}


def analyze_hfss_slotline(f_hz: np.ndarray, s_gen: np.ndarray,
                          gamma: np.ndarray, z0: np.ndarray,
                          zpv_last_adaptive: complex | None = None,
                          w_mm: float = W, h_mm: float = H, er: float = ER,
                          f0_ghz: float = F0, line_len_mm: float = L) -> dict:
    """纯函数分析核（离线测试可对合成数据调用，不 import pyaedt）。

    入参：f_hz (N,)；s_gen (N,2,2) 广义模态 S（renormalize=False 导出）；
    gamma (N,2) 复传播常数（P1/P2 列）；z0 (N,2) touchstone "! Port Impedance"
    ——**两列都是 Zpi**（ExportNetworkData 实证：P2 列与 LastAdaptive
    Zo(P2,CharImp=Zpi) 逐位相等，P1 列≈P2 列，不按端口 CharImp 写）。
    zpv_last_adaptive：Modal Solution Data 的 Zo(P1, CharImp=Zpv) @f0（真
    Zpv）；None 时降级用 touchstone Zpi 列冒充并打 zpv_source 标记。
    Zvi=√(Zpi·Zpv)。50Ω 基重归一用 Zpv(f)≈Zpi(f)·(Zpv/Zpi)（比值近平不随频，
    近似并记录）。
    """
    import skrf

    from rfauto.core.slotline import slotline_closed_form

    f_hz = np.asarray(f_hz, dtype=float)
    s_gen = np.asarray(s_gen, dtype=complex)
    gamma = np.asarray(gamma, dtype=complex)
    z0 = np.asarray(z0, dtype=complex)
    f0_hz = f0_ghz * 1e9
    ll_m = line_len_mm * 1e-3
    cf_f0 = slotline_closed_form(w_mm, h_mm, er, f0_ghz)
    i0 = int(np.argmin(np.abs(f_hz - f0_hz)))

    beta_g = gamma.imag                         # (N,2)
    beta_gamma_f0 = float(0.5 * (beta_g[i0, 0] + beta_g[i0, 1]))
    alpha_f0 = float(0.5 * (gamma[i0, 0].real + gamma[i0, 1].real))
    port_sym = float(np.max(np.abs(gamma[:, 0] - gamma[:, 1])
                            / np.maximum(np.abs(gamma[:, 0]), 1e-30)))
    zpi_f = 0.5 * (z0[:, 0] + z0[:, 1])          # touchstone 两列均为 Zpi，取两口均值 (N,)
    zpi = complex(zpi_f[i0])
    if zpv_last_adaptive is not None:
        zpv = complex(zpv_last_adaptive)
        zpv_source = "last_adaptive Zo(P1, CharImp=Zpv)"
    else:
        zpv = complex(z0[i0, 0])
        zpv_source = "FALLBACK touchstone Zpi column (LastAdaptive Zpv 缺失，非真 Zpv)"
    zvi = complex(np.sqrt(zpi * zpv))
    zpv_a, zpi_a, zvi_a = abs(zpv), abs(zpi), abs(zvi)
    evanescent = bool(abs(gamma[i0, 0].real) > abs(gamma[i0, 0].imag))

    out: dict = {
        "beta_gamma_rad_m_f0": beta_gamma_f0,
        "beta_gamma_vs_cf_f0_pct": (beta_gamma_f0 / cf_f0.beta_rad_m - 1) * 100,
        "alpha_np_m_f0": alpha_f0,
        "mode_evanescent_at_f0": evanescent,
        "port_gamma_asymmetry_max_rel": port_sym,
        "cf_beta_f0_rad_m": cf_f0.beta_rad_m,
        "cf_eps_eff_f0": cf_f0.eps_eff,
        "eps_eff_gamma_f0": (beta_gamma_f0 / (2 * np.pi * f0_hz / 299792458.0)) ** 2,
        "zpi_ohm": zpi_a, "zpv_ohm": zpv_a, "zvi_ohm": zvi_a,
        "zpv_source": zpv_source,
        "zpv_complex": [zpv.real, zpv.imag], "zpi_complex": [zpi.real, zpi.imag],
        "zpv_over_zpi": zpv_a / zpi_a if zpi_a else None,
        "cf_z0_ohm_f0": cf_f0.z0_ohm,
        "zpv_vs_cf_pct": (zpv_a / cf_f0.z0_ohm - 1) * 100,
        "zpi_vs_cf_pct": (zpi_a / cf_f0.z0_ohm - 1) * 100,
        "zvi_vs_cf_pct": (zvi_a / cf_f0.z0_ohm - 1) * 100,
        "s11_db_f0_generalized": float(20 * np.log10(abs(s_gen[i0, 0, 0]) + 1e-12)),
        "s21_db_f0_generalized": float(20 * np.log10(abs(s_gen[i0, 1, 0]) + 1e-12)),
        "reciprocity_max_lin": float(np.max(np.abs(
            s_gen - np.transpose(s_gen, (0, 2, 1))))),
    }
    if evanescent:
        # 倏逝模：S21 相位/50Ω 重归一无意义（Zo 近纯虚），只记截止反推
        kc = abs(gamma[i0, 0])
        out.update({"cutoff_ghz_from_alpha": float(
            np.sqrt(max(kc ** 2 + (2 * np.pi * f0_hz / 299792458.0) ** 2, 0.0))
            * 299792458.0 / (2 * np.pi) / 1e9),
            "beta_s21_rad_m_f0": None, "beta_s21_vs_cf_f0_pct": None,
            "beta_s21_vs_gamma_pct": None, "beta_band_rows": [],
            "s11_db_f0_50ohm": None, "s21_db_f0_50ohm": None})
        return out

    # S21 绝对相位 β(f)：广义 S 已是线基（renorm 恒等）；分支由闭式先验锁定
    ph = beta_from_s21(f_hz, s_gen, zpv_a, zpv_a, cf_f0.beta_rad_m, f0_hz, ll_m)
    # 50Ω 基（对拍口径）：两口统一用 Zpv(f)≈Zpi(f)·(Zpv/Zpi)@f0（闭式=功率-电压定义；
    # touchstone 只给 Zpi(f)，比值随频近平，近似并记录）离线重归一
    freq = skrf.Frequency.from_f(f_hz, unit="Hz")
    ratio = zpv_a / zpi_a if zpi_a else 1.0
    zpv_f = np.abs(zpi_f) * ratio
    z0_pv = np.stack([zpv_f, zpv_f], axis=1)
    net50 = skrf.Network(frequency=freq, s=s_gen, z0=z0_pv)
    net50.renormalize(50.0)
    s50 = net50.s
    band_rows = []
    step = max(1, len(f_hz) // 8)
    for k in range(0, len(f_hz), step):
        fg = float(f_hz[k] / 1e9)
        cf_k = slotline_closed_form(w_mm, h_mm, er, fg)
        bg = float(0.5 * (beta_g[k, 0] + beta_g[k, 1]))
        band_rows.append({
            "f_ghz": fg, "beta_gamma": bg, "beta_s21": float(ph["beta_rad_m"][k]),
            "beta_cf": cf_k.beta_rad_m,
            "gamma_vs_cf_pct": (bg / cf_k.beta_rad_m - 1) * 100,
            "zpi_ohm": float(abs(zpi_f[k])), "zpv_ohm_est": float(zpv_f[k]),
            "z0_cf_ohm": cf_k.z0_ohm})
    out.update({
        "beta_s21_rad_m_f0": ph["beta_f0_rad_m"],
        "beta_s21_vs_cf_f0_pct": (ph["beta_f0_rad_m"] / cf_f0.beta_rad_m - 1) * 100,
        "beta_s21_vs_gamma_pct": (ph["beta_f0_rad_m"] / beta_gamma_f0 - 1) * 100,
        "beta_s21_branch_n": ph["branch_n"],
        "beta_band_rows": band_rows,
        "s11_db_f0_50ohm": float(20 * np.log10(abs(s50[i0, 0, 0]) + 1e-12)),
        "s21_db_f0_50ohm": float(20 * np.log10(abs(s50[i0, 1, 0]) + 1e-12)),
        "band_max_s11_db_50ohm": float(np.max(20 * np.log10(np.abs(s50[:, 0, 0]) + 1e-12))),
    })
    return out


def _analyze_variant(tag: str, s2p: Path, s2p_gamma: Path,
                     port_modes: dict | None) -> dict:
    import skrf
    from skrf.io.touchstone import hfss_touchstone_2_gamma_z0

    net = skrf.Network(str(s2p))
    f_g, gamma, z0 = hfss_touchstone_2_gamma_z0(str(s2p_gamma))
    if gamma is None or z0 is None:
        raise RuntimeError(f"[{tag}] gamma touchstone 无 Gamma/Port Impedance 注释")
    if len(f_g) != len(net.f) or not np.allclose(f_g, net.f):
        raise RuntimeError(f"[{tag}] 两份 touchstone 频率轴不一致")
    pm = port_modes or {}
    zpv_la = None
    zo_p1 = ((pm.get("ports") or {}).get("P1sheetP") or {}).get("Zo(P1sheetP)")
    if zo_p1 and len(zo_p1) == 2:
        zpv_la = complex(float(zo_p1[0]), float(zo_p1[1]))   # CharImp=Zpv 端口的 Zo
    out = analyze_hfss_slotline(net.f, net.s, gamma, z0, zpv_last_adaptive=zpv_la)
    out.update({"variant": tag, "port_geometry": pm.get("port_geometry"),
                "solve_s": pm.get("solve_s"),
                "last_adaptive_port_data": pm.get("ports"),
                "s2p": str(s2p), "s2p_gamma": str(s2p_gamma)})
    if out["mode_evanescent_at_f0"]:
        print(f"[{tag}] EVANESCENT: gamma={out['alpha_np_m_f0']:.2f}+j{out['beta_gamma_rad_m_f0']:.3f} "
              f"cutoff≈{out['cutoff_ghz_from_alpha']:.2f}GHz Zpv={out['zpv_complex']}", flush=True)
    else:
        print(f"[{tag}] beta_gamma={out['beta_gamma_rad_m_f0']:.3f} "
              f"({out['beta_gamma_vs_cf_f0_pct']:+.2f}% vs cf) "
              f"beta_s21={out['beta_s21_rad_m_f0']:.3f} "
              f"Zpi={out['zpi_ohm']:.2f} Zpv={out['zpv_ohm']:.2f} "
              f"Zvi={out['zvi_ohm']:.2f} cf_Z0={out['cf_z0_ohm_f0']:.2f}", flush=True)
    return out


def _load_port_modes() -> dict:
    pm_path = OUT / "port_modes.json"
    if pm_path.exists():
        return json.loads(pm_path.read_text(encoding="utf-8"))
    return {}


def _finalize(analyses: dict) -> dict:
    """三档收敛 + 基准档门 → verdict（写入 RESULT）。"""
    from rfauto.core.slotline import slotline_closed_form

    cf = slotline_closed_form(W, H, ER, F0)
    prim = analyses.get(PRIMARY_TAG)
    verdict: dict = {"primary_variant": PRIMARY_TAG,
                     "cf_beta_f0_rad_m": cf.beta_rad_m, "cf_z0_ohm_f0": cf.z0_ohm}
    conv = {}
    for tag in ("mid", "wide", "xl"):
        a = analyses.get(tag)
        if a and not a.get("mode_evanescent_at_f0"):
            conv[tag] = {"beta_gamma": a["beta_gamma_rad_m_f0"],
                         "beta_vs_cf_pct": a["beta_gamma_vs_cf_f0_pct"],
                         "zpv": a["zpv_ohm"], "zpi": a["zpi_ohm"],
                         "zvi": a["zvi_ohm"],
                         "port_width_mm": (a.get("port_geometry") or {}).get("total_width_mm")}
    verdict["port_size_convergence"] = conv
    if "wide" in conv and "xl" in conv:
        verdict["beta_wide_vs_xl_pct"] = (conv["wide"]["beta_gamma"] / conv["xl"]["beta_gamma"] - 1) * 100
        verdict["zpv_wide_vs_xl_pct"] = (conv["wide"]["zpv"] / conv["xl"]["zpv"] - 1) * 100
    if "mid" in conv and "wide" in conv:
        verdict["beta_mid_vs_wide_pct"] = (conv["mid"]["beta_gamma"] / conv["wide"]["beta_gamma"] - 1) * 100
    narrow = analyses.get(NARROW_TAG)
    if narrow:
        verdict["narrow5w_evidence"] = {
            "mode_evanescent_at_f0": narrow.get("mode_evanescent_at_f0"),
            "alpha_np_m_f0": narrow.get("alpha_np_m_f0"),
            "beta_gamma_rad_m_f0": narrow.get("beta_gamma_rad_m_f0"),
            "cutoff_ghz_from_alpha": narrow.get("cutoff_ghz_from_alpha"),
            "zpv_complex": narrow.get("zpv_complex"),
            "note": "微带惯例 5×w 端口：PEC 框短接槽两侧地 → fin-line 截止倏逝模（槽线波端口尺寸陷阱实证）"}
    if prim and not prim.get("mode_evanescent_at_f0"):
        verdict.update({
            "beta_gamma_vs_cf_f0_pct": prim["beta_gamma_vs_cf_f0_pct"],
            "gate_beta_le_5pct": abs(prim["beta_gamma_vs_cf_f0_pct"]) <= 5.0,
            "gate_beta_s21_le_5pct": abs(prim["beta_s21_vs_cf_f0_pct"]) <= 5.0,
            "gate_s21_vs_gamma_le_1pct_consistency": abs(prim["beta_s21_vs_gamma_pct"]) <= 1.0,
            "z0_three_defs_vs_cf": {
                "zpi_ohm": prim["zpi_ohm"], "zpv_ohm": prim["zpv_ohm"], "zvi_ohm": prim["zvi_ohm"],
                "zpi_pct": prim["zpi_vs_cf_pct"], "zpv_pct": prim["zpv_vs_cf_pct"],
                "zvi_pct": prim["zvi_vs_cf_pct"],
                "note": "闭式 Z0=功率-电压定义（Janaswamy 式(1)），预期 Zpv 最接近；三定义全记录不硬判"},
            "ok": bool(abs(prim["beta_gamma_vs_cf_f0_pct"]) <= 5.0
                       and abs(prim["beta_s21_vs_cf_f0_pct"]) <= 5.0),
        })
    else:
        verdict.update({"ok": False, "gate_beta_le_5pct": False,
                        "note": "基准档缺失或倏逝模，UNDECIDABLE"})
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyze-only", action="store_true", help="只对既有产物重分析")
    ap.add_argument("--variants", default=",".join(v["tag"] for v in PORT_VARIANTS),
                    help="逗号分隔要求解的档（默认全部）")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = [v.strip() for v in args.variants.split(",") if v.strip()]
    _write_result({"stage": "start", "w_mm": W, "h_mm": H, "er": ER,
                   "tan_d": TAND, "f0_ghz": F0, "line_len_mm": L,
                   "sweep": f"{F_LO}-{F_HI}GHz {N_PTS}pt interpolating",
                   "variants_spec": PORT_VARIANTS, "primary": PRIMARY_TAG,
                   "timeout_s": TIMEOUT_S, "analyze_only": args.analyze_only})
    # ── 求解阶段（#191 整轮重试 ≤2 只包建模+求解+导出）──
    if not args.analyze_only:
        for variant in PORT_VARIANTS:
            tag = variant["tag"]
            if tag not in wanted:
                continue
            last_err = None
            for attempt in range(3):
                try:
                    _kill_desktops()
                    shutil.rmtree(OUT / f"project_{tag}", ignore_errors=True)
                    res = _build_and_solve(variant)
                    _write_result({"stage": f"solved_{tag}", "attempt": attempt + 1,
                                   f"solve_s_{tag}": res["solve_s"]})
                    _progress(f"stage2 hfss/{tag}: solved {res['solve_s']}s attempt={attempt + 1}")
                    break
                except Exception as exc:
                    last_err = repr(exc)
                    print(f"[{tag}] attempt {attempt + 1}/3 FAIL: {last_err}", flush=True)
                    _write_result({"stage": f"attempt_failed_{tag}",
                                   "attempt": attempt + 1, "error": last_err})
            else:
                _write_result({"stage": f"failed_all_attempts_{tag}", "error": last_err})
                _progress(f"stage2 hfss/{tag}: FAILED all attempts {last_err}")
                print(f"SLOTLINE_HFSS_ARB_FAIL_{tag}", flush=True)
        _kill_desktops(strict=False)  # 收尾扫尾：只清孤儿，不连坐

    # ── 分析阶段（只读产物；失败不重解）──
    pm_all = _load_port_modes()
    analyses: dict = {}
    for tag in [NARROW_TAG] + [v["tag"] for v in PORT_VARIANTS]:
        s2p = OUT / f"hfss_slotline_{tag}.s2p"
        s2p_g = OUT / f"hfss_slotline_{tag}_gamma.s2p"
        if not (s2p.exists() and s2p_g.exists()):
            continue
        try:
            analyses[tag] = _analyze_variant(tag, s2p, s2p_g, pm_all.get(tag))
        except Exception as exc:
            analyses[tag] = {"variant": tag, "error": repr(exc)}
            print(f"[{tag}] analysis FAIL: {exc!r}", flush=True)
    verdict = _finalize(analyses)
    _write_result({"stage": "done", "verdict": verdict, "variants": analyses})
    print(json.dumps(verdict, indent=2, ensure_ascii=False, default=str), flush=True)
    ok = bool(verdict.get("ok"))
    _progress(f"stage2 hfss: done ok={ok} beta_vs_cf={verdict.get('beta_gamma_vs_cf_f0_pct')} "
              f"conv={verdict.get('port_size_convergence')}")
    print(f"SLOTLINE_HFSS_ARB_{'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
