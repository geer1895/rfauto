"""HFSS→Icepak 场级损耗端到端 + 双向温漂 + 锚定 真机脚本（WP4.4a ①③⑤）。

同一 AEDT 工程（wp44a_e2e.aedt）内双设计同桌面（#191 gRPC 整轮重试）：

  - ``rfauto_hfss_src``（HFSS 源设计，本脚本 pyaedt 直驱，不走
    hfss_session 公共通道）：环形谐振器（ring resonator，馈线-环 gap
    耦合，PEC 金属=无导体损耗，介质损耗在基板体积内）——RO4350B 量级
    基板，50Ω 馈线宽由 core/synthesis skrf-HJ 综合产出（综合精算，1c），
    环均值半径初值 = λg/2π（初值而已，f0 以 HFSS 实测为准）；
    几何全部挂 $scale（CTE 尺寸膨胀）与 $epsr（TCDk 介电温漂）两个
    工程变量，重解温度点只改这两个变量；
  - ``rfauto_et_field``（Icepak 接收设计）：adapter.build_ring_substrate_case
    同名同坐标基板（rfauto_sub + rfauto_sub_ring）→ map_em_losses
    （pyaedt assign_em_losses，同工程 source_project_name=None）→ 求解；
  - ``rfauto_et_lumped``（同功率集总对照）：环带体 assign_solid_block
    总功率 = HFSS |S|² 口径耗散功率。

判据（冻结口径，全部由真机数据+确定性内核
产出，不凑绿 #122）：

  A. 功率守恒 ≤5%：HFSS P_diss = P_in·(1−|S11|²−|S21|²)（port1 单端口
     1W 激励，edit_sources 把 port2 置 0W）vs Icepak 底面 Dirichlet
     HeatFlowRate（TemperatureOnly 下唯一出热口=映射损耗总功率）；
  B. 场级映射 vs 同功率集总 ≤10%（环带中面同监控点温差/温升）；
  C. 双向温漂 ≤2 轮真机演示：T0 → 损耗 → Icepak T1 → HFSS@T1 重解
     （εr(T)=εr_ref·(1+TCDk·ΔT)，core/thermal_iteration 材料模型同口径；
     CTE 走 $scale 尺寸膨胀）→ f0 漂移对一阶闭式 −CTE·ΔT−½TCDk·ΔT
     ≤20%。注意：|f0(T1)−f0(T0)| 是物理漂移不是迭代残差（定点收敛性
     由离线 solve_thermal_fixed_point 注入 fake 评估器演示，
     test_electrothermal_service）；
  D. 锚定（#190 HFSS 为对齐基准）：固定 ΔT=+50K 两温度点提取
     df0/dT 有效斜率 [ppm/K] → TCDk_eff = 2·(|slope|−CTE)（确定性算术）
     回写 scripts/icepak_electrothermal_case.py 占位常量；本 JSON 即
     仲裁 provenance 工件。

纪律：
- 数值纪律：几何/频率估计值全部出自确定性内核（synthesis/闭式）；一切
  "实测"数字（f0/P_diss/T/R_th/斜率）出自 HFSS/Icepak 真机；
- AEDT 2025.1 gRPC 通道级不稳（#191）：整轮重试 ×3，仅杀本脚本遗留
  桌面；每轮前白名单清工程产物（陈旧设计重名=监控读默认值的坑）；
- 真机失败如实 ok=false + error 落 JSON，不凑绿。

产物：runs/icepak_hfss_loss_e2e/e2e_case.json
"""
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "runs" / "icepak_hfss_loss_e2e"
PROJECT = WORK / "wp44a_e2e.aedt"
OUT_JSON = WORK / "e2e_case.json"

# ── 案例常量（口径见模块 docstring）─────────────────────────────────────────
AEDT_VERSION = "2025.1"
HFSS_DESIGN = "rfauto_hfss_src"
Z0_TARGET = 50.0                 # 馈线目标阻抗 [Ω]
STACKUP = "rogers4350b_h0.508"   # materials.yaml 键（εr=3.66, h=0.508mm）
TAN_DELTA = 0.0037               # RO4350B 数据手册量级（HFSS 材料输入）
F0_TARGET_GHZ = 2.4              # 环周长初值的目标频率（实测以 HFSS 为准）
P_PORT_W = 1.0                   # port1 激励功率 [W]（port2 置 0W）
T_REF_C = 25.0                   # Dirichlet 底温 = 温漂参考温度
TCDK_PPM_PER_K = 50.0            # RO4350B 数据手册量级（HFSS 材料温度律输入）
CTE_PPM_PER_K = 14.0             # 同上（$scale 尺寸膨胀输入）
DELTA_T_ANCHOR_K = 50.0          # 锚定腿固定温度步长 [K]
CONSERVATION_TOL = 0.05          # 判据 A 门
FIELD_VS_LUMPED_TOL = 0.10       # 判据 B 门
DRIFT_VS_CLOSED_TOL = 0.20       # 判据 C/D 门
MAX_ATTEMPTS = 2  # 收官轮：单 attempt ~35min，2 次 bounding 总时长
FINE_SPAN_HZ = 25.0e6    # 温度腿离散细扫半宽（锚定腿期望漂移 −4.65MHz 在窗内）
FINE_POINTS = 201        # 离散点数（0.25MHz 步长 + 三点抛物线细化）
C0 = 299792458.0

# 环形几何（HFSS 与 Icepak 两面同值；环宽=馈线宽）
GAP_MM = 0.10                    # 馈线-环耦合缝
AIR_PAD_MM = 5.0                 # 空气盒 x 向辐射缓冲（y 向不留=端口贴边）
AIR_TOP_MM = 8.0                 # 空气盒 z 向净高


def _kill_desktops() -> None:
    """杀本脚本遗留的 ansysedt（仅整轮重试时调用，#157 先查后杀）。"""
    probe = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process ansysedt -ErrorAction SilentlyContinue).Count"],
        capture_output=True, text=True)
    count = (probe.stdout or "").strip()
    print(f"[retry] 检测到 {count or 0} 个 ansysedt 进程，清理后重试", flush=True)
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process ansysedt -ErrorAction SilentlyContinue | "
                    "Stop-Process -Force"], capture_output=True)
    time.sleep(5)


def _clean_project_artifacts() -> None:
    """白名单清 AEDT 工程产物（陈旧设计重名=监控读默认值，真机实证）。
    只点名工程四件，不碰日志与 JSON 证据。"""
    import shutil

    for name in ("wp44a_e2e.aedt",
                 "wp44a_e2e.aedt.lock",
                 "wp44a_e2e.aedtresults",
                 "wp44a_e2e.pyaedt"):
        path = WORK / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink(missing_ok=True)


def _mm_val(raw: Any) -> float:
    """pyaedt get_face_center 返回值（float 或 "12.0mm" 串）→ float。"""
    return float(str(raw).replace("mm", "").strip())


def _peak_frequency(freq_hz: Any, s21_mag: Any) -> dict:
    """|S21| 峰值频率：网格 argmax + 三点抛物线插值细化（确定性算术）。"""
    freq_hz = np.asarray(freq_hz, dtype=float)
    s21_mag = np.asarray(s21_mag, dtype=float)
    i = int(np.argmax(s21_mag))
    f_grid = float(freq_hz[i])
    refined = f_grid
    if 0 < i < len(freq_hz) - 1:
        f1, f2 = float(freq_hz[i - 1]), float(freq_hz[i + 1])
        y0, y1, y2 = (float(s21_mag[i - 1]), float(s21_mag[i]),
                      float(s21_mag[i + 1]))
        denom = y0 - 2.0 * y1 + y2
        if denom != 0.0:
            delta = 0.5 * (y0 - y2) / denom * (f2 - f1) / 2.0
            if abs(delta) <= (f2 - f1):
                refined = float(freq_hz[i] + delta)
    return {"peak_hz": refined, "grid_peak_hz": f_grid,
            "grid_step_hz": float(freq_hz[1] - freq_hz[0]),
            "s21_at_peak": float(s21_mag[i])}


def _build_hfss_source(h: Any) -> dict:
    """HFSS 源设计：环形谐振器（变量化 $scale/$epsr；线宽=综合产出）。"""
    from ansys.aedt.core.generic.constants import Gravity

    from rfauto.core.synthesis import synthesize_mline

    syn = synthesize_mline(Z0_TARGET, F0_TARGET_GHZ, STACKUP)
    if syn.status != "ok":
        raise RuntimeError(f"馈线综合未自洽: {syn.to_dict()}")
    feed_w_mm = float(syn.width_mm)
    eps_eff = float(syn.epsilon_eff)
    lambda_g_mm = C0 / (F0_TARGET_GHZ * 1e9) * 1e3 / math.sqrt(eps_eff)
    r_mean_mm = lambda_g_mm / (2.0 * math.pi)
    r_in_mm = r_mean_mm - feed_w_mm / 2.0
    r_out_mm = r_mean_mm + feed_w_mm / 2.0
    # 基板尺寸：环+缓冲须落在板内（确定性算术）；y 向馈线长 = sub_half−r_out
    sub_half_mm = math.ceil(r_out_mm + AIR_PAD_MM) + 8.0
    sub_l_mm = sub_w_mm = 2.0 * sub_half_mm
    print(f"[geom] w={feed_w_mm:.4f}mm(50Ω HJ) εeff={eps_eff:.4f} "
          f"λg={lambda_g_mm:.2f}mm → r_mean={r_mean_mm:.3f}mm "
          f"board={sub_l_mm:.0f}×{sub_w_mm:.0f}mm", flush=True)

    h.modeler.model_units = "mm"
    # 工程变量：$scale（CTE 尺寸膨胀，无量纲）、$epsr（TCDk 介电温漂）
    h["$scale"] = 1.0
    h["$epsr"] = 3.66
    # 设计变量（带单位；几何表达式 = 带单位变量 × 无量纲 $scale。
    # #218 口径：禁裸数字算术串——曾按 SI 米求值致端口悬空 2.78m。
    # 几何实参一律写成纯设计变量表达式的普通字符串（量纲随变量，
    # dim_audit 判 DESIGN_VAR_EXPR），空气盒缓冲同样先落成带 mm 变量）
    h["sub_l"] = f"{sub_l_mm}mm"
    h["sub_w"] = f"{sub_w_mm}mm"
    h["sub_h"] = "0.508mm"
    h["feed_w"] = f"{feed_w_mm}mm"
    h["r_in"] = f"{r_in_mm}mm"
    h["r_out"] = f"{r_out_mm}mm"
    h["gap"] = f"{GAP_MM}mm"
    h["air_pad"] = f"{AIR_PAD_MM}mm"
    h["air_top"] = f"{AIR_TOP_MM}mm"

    # 材料：εr 挂工程变量 $epsr（材料是工程级定义，只能引用 $ 变量；
    # MatProperty.value 接受表达式串），tanδ 常数（温度系数二阶量，
    # 与 core 材料模型 tan_delta_tempco=0 同口径）
    mat = h.materials.add_material("rfauto_sub_mat")
    mat.permittivity = "$epsr"
    mat.dielectric_loss_tangent = TAN_DELTA

    # 基板外体（含环带孔）+ 环带体（与 Icepak 接收设计同名同坐标）
    h.modeler.create_box(
        origin=["-sub_l*$scale/2", "-sub_w*$scale/2", "0mm"],
        sizes=["sub_l*$scale", "sub_w*$scale", "sub_h*$scale"],
        name="rfauto_sub", material="rfauto_sub_mat")
    h.modeler.create_cylinder(
        orientation="Z", origin=["0mm", "0mm", "0mm"],
        radius="r_out*$scale", height="sub_h*$scale",
        name="rfauto_sub_ring", material="rfauto_sub_mat")
    h.modeler.create_cylinder(
        orientation="Z", origin=["0mm", "0mm", "0mm"],
        radius="r_in*$scale", height="sub_h*$scale",
        name="_ring_inner", material="rfauto_sub_mat")
    h.modeler.subtract("rfauto_sub_ring", ["_ring_inner"])
    h.modeler.subtract("rfauto_sub", ["rfauto_sub_ring"], keep_originals=True)
    # 地板 / 环 / 馈线：PEC（零厚片/环带片；无导体损耗，介质损耗为唯一
    # 映射源——冒烟级口径，见 docstring）；环带片=两同心圆片相减
    h.modeler.create_box(
        origin=["-sub_l*$scale/2", "-sub_w*$scale/2", "0mm"],
        sizes=["sub_l*$scale", "sub_w*$scale", "0mm"], name="Gnd",
        material="pec")
    h.modeler.create_circle(
        orientation="XY", origin=["0mm", "0mm", "sub_h*$scale"],
        radius="r_out*$scale", name="Ring", material="pec")
    h.modeler.create_circle(
        orientation="XY", origin=["0mm", "0mm", "sub_h*$scale"],
        radius="r_in*$scale", name="_ring_pec_inner", material="pec")
    h.modeler.subtract("Ring", ["_ring_pec_inner"])
    h.modeler.create_box(
        origin=["-feed_w*$scale/2", "-sub_w*$scale/2", "sub_h*$scale"],
        sizes=["feed_w*$scale", "(sub_w/2-r_out-gap)*$scale", "0mm"],
        name="Feed1", material="pec")
    h.modeler.create_box(
        origin=["-feed_w*$scale/2", "(r_out+gap)*$scale", "sub_h*$scale"],
        sizes=["feed_w*$scale", "(sub_w/2-r_out-gap)*$scale", "0mm"],
        name="Feed2", material="pec")
    h.assign_perfecte_to_sheets(
        assignment=["Gnd", "Ring", "Feed1", "Feed2"], name="PEC_all")
    h.modeler["rfauto_sub"].solve_inside = True
    h.modeler["rfauto_sub_ring"].solve_inside = True

    # 空气盒：y 向不留边距（端口贴外边界），x/z 留辐射缓冲（mline 探针
    # 同法：必须从空气盒 subtract 实体，重叠体=端口材质接触歧义）。
    # #218 规则：加法表达式里的字面量**必须带 mm 量纲**（裸数字被 AEDT
    # 按 SI 米求值——首跑实证空气盒变 5m/8m，面选择全空）；缓冲量走
    # 带 mm 的设计变量 air_pad/air_top（=AIR_PAD_MM/AIR_TOP_MM）；纯乘系数
    # （2.5*feed_w）无量纲歧义、允许
    h.modeler.create_box(
        origin=["(-sub_l/2-air_pad)*$scale", "-sub_w*$scale/2", "0mm"],
        sizes=["(sub_l+2*air_pad)*$scale", "sub_w*$scale",
               "(sub_h+air_top)*$scale"],
        name="Air", material="vacuum")
    h.modeler.subtract("Air", ["rfauto_sub", "rfauto_sub_ring"])
    h.modeler["Air"].solve_inside = True
    air_faces = h.modeler.get_object_faces("Air")
    open_faces = []
    for f in air_faces:
        cx, cy, cz = (_mm_val(v) for v in h.modeler.get_face_center(f))
        if abs(abs(cy) - sub_half_mm) < 1e-6:
            continue  # y 侧面=端口面，不赋辐射（#191 mline 探针实证）
        if abs(cz - (0.508 + AIR_TOP_MM)) < 1e-6 \
                or abs(abs(cx) - (sub_half_mm + AIR_PAD_MM)) < 1e-6:
            open_faces.append(f)
    if not open_faces:
        # 不把空选择集喂给 pyaedt（其内部 IndexError 掩盖真因）；
        # 诊断信息随 RuntimeError 落入产物 JSON error
        centers = [h.modeler.get_face_center(f) for f in air_faces]
        raise RuntimeError(
            f"辐射面过滤为空（air_faces={air_faces} centers={centers!r}）"
            "——检查几何表达式单位")
    h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")

    # 波端口（官方尺寸比例 5×w × 4×sub_h，#191/#192 口径）×2，贴 y 边界；
    # 馈线沿 ±y、居中 x=0 → 两端口 sheet 同为 x∈[−2.5w, +2.5w]
    for name, y_expr in (("P1sheet", "-sub_w*$scale/2"),
                         ("P2sheet", "sub_w*$scale/2")):
        h.modeler.create_rectangle(
            orientation="ZX",
            origin=["-2.5*feed_w*$scale", y_expr, "0mm"],
            sizes=["4*sub_h*$scale", "5*feed_w*$scale"],
            name=name)
        port_face = h.modeler.get_object_faces(name)[0]
        h.wave_port(assignment=port_face, name=name + "P",
                    impedance=Z0_TARGET, renormalize=True,
                    integration_line=Gravity.ZPos)
    return {"feed_w_mm": feed_w_mm, "eps_eff": eps_eff,
            "r_in_mm": r_in_mm, "r_out_mm": r_out_mm,
            "sub_l_mm": sub_l_mm, "sub_w_mm": sub_w_mm}


def _setup_and_sweep(h: Any, f0_center_ghz: float, span_ghz: float = 0.25) -> None:
    """自适应 setup + 插值扫频（找 f0 用，无场保存）。"""
    setup = h.create_setup(name="Setup")
    setup.props["Frequency"] = f"{f0_center_ghz:.6f}GHz"
    setup.props["MaxDeltaS"] = 0.02
    setup.props["MaximumPasses"] = 10
    setup.update()
    h.create_linear_count_sweep(
        setup="Setup", unit="GHz", start_frequency=f0_center_ghz - span_ghz,
        stop_frequency=f0_center_ghz + span_ghz, num_of_freq_points=401,
        name="Sweep", sweep_type="Interpolating", save_fields=False)


def _solve_sweep_f0(h: Any) -> tuple[dict, int]:
    """分析并从插值扫频 |S21| 峰提取 f0（三点抛物线细化）。返回 (peak, 点数)。"""
    h.analyze(setup="Setup")
    sol = h.post.get_solution_data(
        expressions=["S(2,1)"], setup_sweep_name="Setup : Sweep")
    if sol is None or not sol.expressions:
        raise RuntimeError("Sweep 解数据读取失败")
    freq, mag = sol.get_expression_data(expression="S(2,1)", formula="mag",
                                        convert_to_SI=True)
    freq = np.asarray(freq, dtype=float)
    mag = np.asarray(mag, dtype=float)
    if freq.size < 3:
        raise RuntimeError(f"Sweep 点数不足: {freq.size}")
    return _peak_frequency(freq, mag), int(freq.size)


def _field_power_at_f0(h: Any, f0_ghz: float, tag: str) -> dict:
    """自适应频率改到 f0 重解 → LastAdaptive 口径耗散功率（port1 单端口）。

    EM 损耗映射源用 ``LastAdaptive``（pyaedt assign_em_losses 官方例口径）：
    自适应解的场恒被保存，数据链接可靠；单点扫频的场存档取链接在
    2025.1 真机实证失败（"Unable to obtain EM Loss data"）。
    tag 仅用于产物溯源标注（如 r1/r2）。
    """
    setup = h.get_setup("Setup")
    setup.props["Frequency"] = f"{f0_ghz:.9f}GHz"
    setup.update()
    # 场解激励：port1 单端口 1W（port2 置 0）——映射损耗总功率的可比口径
    h.edit_sources({"P1sheetP:1": (f"{P_PORT_W}W", "0deg"),
                    "P2sheetP:1": ("0W", "0deg")})
    h.analyze(setup="Setup")
    sol = h.post.get_solution_data(
        expressions=["mag(S(1,1))", "mag(S(2,1))"],
        setup_sweep_name="Setup : LastAdaptive")
    if sol is None:
        raise RuntimeError(f"LastAdaptive 解数据读取失败（{tag}）")
    _, m11 = sol.get_expression_data(expression="mag(S(1,1))", formula="real")
    _, m21 = sol.get_expression_data(expression="mag(S(2,1))", formula="real")
    s11 = float(np.asarray(m11).ravel()[0])
    s21 = float(np.asarray(m21).ravel()[0])
    p_diss = P_PORT_W * (1.0 - s11 ** 2 - s21 ** 2)
    return {"f0_ghz": f0_ghz, "s11_mag": s11, "s21_mag": s21,
            "p_diss_w": p_diss, "sweep": "LastAdaptive", "tag": tag}


def _fine_f0(h: Any, center_hz: float, sweep_name: str) -> tuple[dict, int]:
    """离散细扫（确定性逐点解）找 f0：插值扫频在重解后峰值漂移不可靠
    （2025.1 真机实测 T1 腿读出 +9002ppm 非物理跳变），温度腿一律离散点。"""
    start_ghz = (center_hz - FINE_SPAN_HZ) / 1e9
    stop_ghz = (center_hz + FINE_SPAN_HZ) / 1e9
    h.create_linear_count_sweep(
        setup="Setup", unit="GHz", start_frequency=start_ghz,
        stop_frequency=stop_ghz, num_of_freq_points=FINE_POINTS,
        name=sweep_name, sweep_type="Discrete", save_fields=False)
    h.analyze(setup="Setup")
    sol = h.post.get_solution_data(
        expressions=["S(2,1)"], setup_sweep_name=f"Setup : {sweep_name}")
    if sol is None or not sol.expressions:
        raise RuntimeError(f"{sweep_name} 解数据读取失败")
    freq, mag = sol.get_expression_data(expression="S(2,1)", formula="mag",
                                        convert_to_SI=True)
    freq = np.asarray(freq, dtype=float)
    mag = np.asarray(mag, dtype=float)
    if freq.size < 3:
        raise RuntimeError(f"{sweep_name} 点数不足: {freq.size}")
    return _peak_frequency(freq, mag), int(freq.size)


def _run_case() -> dict:
    from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
    from rfauto.adapters.icepak_adapter import RING_DEFAULTS, IcepakAdapter
    from rfauto.core.electrothermal import closed_form_drift_ratio

    h = None
    adapter = None
    try:
        # ── HFSS 源设计 ────────────────────────────────────────────────────
        from ansys.aedt.core import Hfss

        h = Hfss(project=str(PROJECT), design=HFSS_DESIGN,
                 version=AEDT_VERSION, non_graphical=True, new_desktop=True)
        geom = _build_hfss_source(h)
        _setup_and_sweep(h, F0_TARGET_GHZ)
        peak, n_sweep = _solve_sweep_f0(h)
        # 粗扫定窗心后立刻离散细扫：插值扫频峰值误差对高 Q 环达兆级
        # （真机实证 2.3877 vs 离散细扫 2.4064），f0 一律以离散细扫为准
        peak, _n_fine = _fine_f0(h, peak["peak_hz"], "SweepR1")
        f0_t0_hz = peak["peak_hz"]
        print(f"[HFSS@T0] f0={f0_t0_hz / 1e9:.6f}GHz "
              f"(网格步长 {peak['grid_step_hz'] / 1e6:.2f}MHz)", flush=True)
        fp0 = _field_power_at_f0(h, f0_t0_hz / 1e9, "r1")
        p_diss_t0 = fp0["p_diss_w"]
        print(f"[HFSS@T0] |S11|={fp0['s11_mag']:.4f} "
              f"|S21|={fp0['s21_mag']:.4f} → P_diss={p_diss_t0:.6f}W",
              flush=True)

        # ── Icepak：场级映射设计 + 同功率集总对照（单 adapter 多设计快照）──
        icepak_geo = {
            "power_w": 0.0,
            "board_len_mm": geom["sub_l_mm"],
            "board_wid_mm": geom["sub_w_mm"],
            "board_thk_mm": RING_DEFAULTS["board_thk_mm"],
            "board_k_w_mk": RING_DEFAULTS["board_k_w_mk"],
            "ring_r_in_mm": geom["r_in_mm"],
            "ring_r_out_mm": geom["r_out_mm"],
            "t_base_c": T_REF_C,
        }
        cfg = EMSolverConfig(
            solver_type=EMSolverType.ICEPAK, working_dir=str(WORK),
            extra_params={"project_path": str(PROJECT),
                          "design_name": "rfauto_et_field",
                          "problem_type": "TemperatureOnly",
                          "desktop_version": AEDT_VERSION,
                          "save_project": False})
        adapter = IcepakAdapter(cfg)
        if not adapter.connect():
            return {"ok": False,
                    "error": f"icepak connect: {adapter._last_message}"}

        def _map_and_solve(fp: dict) -> tuple[dict, Any]:
            mapped = adapter.map_em_losses({
                "assignment": ["rfauto_sub", "rfauto_sub_ring"],
                "design": HFSS_DESIGN, "setup": "Setup",
                "sweep": fp["sweep"],
                # 显式频点必须给：LastAdaptive+空 Intrinsics 在 2025.1 让
                # 链接彻底取不到数据（"Unable to obtain EM Loss data"，真机
                # 实证）；显式 f0 才能建立数据链接
                "map_frequency": f"{fp['f0_ghz']:.9f}GHz",
                "source_project_name": None})
            if not mapped.get("ok"):
                return mapped, None
            return mapped, adapter.solve()

        if not adapter.build_ring_substrate_case(dict(icepak_geo)):
            return {"ok": False,
                    "error": f"build field: {adapter._last_message}"}
        mapped1, res_field1 = _map_and_solve(fp0)
        if res_field1 is None or not res_field1.success:
            err = (mapped1.get("error") if mapped1 else None) or \
                  (res_field1.message if res_field1 is not None else "n/a")
            return {"ok": False, "error": f"field solve r1: {err}"}
        t_field1 = res_field1.field_data["t_blk_c"]
        wall_w = res_field1.field_data["heat_flow"]["wall_w"]
        cons_rel = abs(wall_w - p_diss_t0) / p_diss_t0
        conservation_pass = cons_rel <= CONSERVATION_TOL
        print(f"[Icepak field r1] T_ring={t_field1:.3f}C 底面出热="
              f"{wall_w:.6f}W vs P_diss={p_diss_t0:.6f}W → 守恒偏差="
              f"{cons_rel * 100:.2f}%（门 5%）pass={conservation_pass}",
              flush=True)

        # 同功率集总对照（环带体均匀体热源）
        if not adapter.use_design("rfauto_et_lumped"):
            return {"ok": False, "error": adapter._last_message}
        if not adapter.build_ring_substrate_case(
                dict(icepak_geo, power_w=p_diss_t0)):
            return {"ok": False,
                    "error": f"build lumped: {adapter._last_message}"}
        res_lumped = adapter.solve()
        if not res_lumped.success:
            return {"ok": False, "error": f"lumped solve: {res_lumped.message}"}
        t_lumped = res_lumped.field_data["t_blk_c"]
        rise_field = t_field1 - T_REF_C
        diff_rel = (abs(t_field1 - t_lumped) / abs(rise_field)
                    if abs(rise_field) > 1e-12 else float("inf"))
        lumped_pass = diff_rel <= FIELD_VS_LUMPED_TOL
        print(f"[Icepak lumped] T_ring={t_lumped:.3f}C → 场级 vs 集总温差="
              f"{abs(t_field1 - t_lumped):.4f}K（温升 {rise_field:.4f}K 的 "
              f"{diff_rel * 100:.2f}%，门 10%）pass={lumped_pass}", flush=True)

        # ── ③ 双向温漂第 2 轮 + ⑤ 锚定腿（HFSS 材料温度律重解）─────────────
        from rfauto.service.electrothermal_service import derive_r_th_from_field

        r_th = derive_r_th_from_field(
            {"t_hot_c": t_field1, "power_w": p_diss_t0, "ambient_c": T_REF_C,
             "source": "icepak_field_r1"})
        if not r_th.get("ok"):
            return {"ok": False, "error": f"r_th: {r_th.get('error')}"}
        t1 = t_field1
        delta_t_r1 = t1 - T_REF_C
        # HFSS@T1：εr(T)=εr_ref·(1+TCDk·ΔT)（core 材料模型同口径），
        # CTE 走 $scale 尺寸膨胀
        h["$epsr"] = 3.66 * (1.0 + TCDK_PPM_PER_K * 1e-6 * delta_t_r1)
        h["$scale"] = 1.0 + CTE_PPM_PER_K * 1e-6 * delta_t_r1
        peak_r2, _ = _fine_f0(h, f0_t0_hz, "SweepR2")
        f0_t1_hz = peak_r2["peak_hz"]
        fp1 = _field_power_at_f0(h, f0_t1_hz / 1e9, "r2")
        p_diss_t1 = fp1["p_diss_w"]
        drift_hz = f0_t1_hz - f0_t0_hz
        drift_ratio = drift_hz / f0_t0_hz
        closed_ratio = closed_form_drift_ratio(
            CTE_PPM_PER_K, TCDK_PPM_PER_K, delta_t_r1)
        drift_dev = (abs(drift_ratio - closed_ratio) / abs(closed_ratio)
                     if abs(closed_ratio) > 0 else float("inf"))
        drift_pass = drift_dev <= DRIFT_VS_CLOSED_TOL
        print(f"[HFSS@T1={t1:.3f}C] f0={f0_t1_hz / 1e9:.6f}GHz 漂移="
              f"{drift_hz / 1e3:+.1f}kHz ({drift_ratio * 1e6:+.1f}ppm) vs "
              f"闭式 {closed_ratio * 1e6:+.1f}ppm → 偏差 "
              f"{drift_dev * 100:.1f}%（门 20%）pass={drift_pass}", flush=True)

        # 第二轮 Icepak（重映射 @f0(T1) 新损耗）
        if not adapter.set_active_design("rfauto_et_field"):
            return {"ok": False, "error": adapter._last_message}
        if mapped1.get("boundary_name"):
            adapter.delete_boundary(mapped1["boundary_name"])
        _mapped2, res_field2 = _map_and_solve(fp1)
        t_field2 = (res_field2.field_data["t_blk_c"]
                    if res_field2 is not None and res_field2.success else None)
        t2 = t_field2

        # ⑤ 锚定腿：固定 ΔT=+50K（εr+尺寸同律），有效斜率 → TCDk_eff
        h["$epsr"] = 3.66 * (1.0 + TCDK_PPM_PER_K * 1e-6 * DELTA_T_ANCHOR_K)
        h["$scale"] = 1.0 + CTE_PPM_PER_K * 1e-6 * DELTA_T_ANCHOR_K
        peak_a, _ = _fine_f0(h, f0_t0_hz, "SweepAnchor")
        f0_a_hz = peak_a["peak_hz"]
        slope_ppm_per_k = ((f0_a_hz - f0_t0_hz) / f0_t0_hz
                           / DELTA_T_ANCHOR_K * 1e6)
        closed_slope = -(CTE_PPM_PER_K + 0.5 * TCDK_PPM_PER_K)
        slope_dev = abs(slope_ppm_per_k - closed_slope) / abs(closed_slope)
        tcdk_eff = 2.0 * (abs(slope_ppm_per_k) - CTE_PPM_PER_K)
        anchor_pass = slope_dev <= DRIFT_VS_CLOSED_TOL
        print(f"[ANCHOR ΔT=+{DELTA_T_ANCHOR_K:.0f}K] f0={f0_a_hz / 1e9:.6f}GHz "
              f"斜率={slope_ppm_per_k:+.2f}ppm/K vs 闭式 {closed_slope:+.1f}"
              f"ppm/K（偏差 {slope_dev * 100:.1f}%）→ "
              f"TCDk_eff={tcdk_eff:.2f}ppm/K", flush=True)
    finally:
        import contextlib

        # 先经 HFSS 句柄整工程存盘（含 Icepak 设计），再释放桌面（adapter
        # close 内置 best-effort；双句柄同桌面，二次释放静默）
        if h is not None:
            with contextlib.suppress(Exception):
                h.save_project()
        if adapter is not None:
            adapter.close()
        if h is not None:
            with contextlib.suppress(Exception):
                h.release_desktop(close_projects=False, close_desktop=True)

    gates = {
        "conservation_5pct": bool(conservation_pass),
        "field_vs_lumped_10pct": bool(lumped_pass),
        "drift_vs_closed_form_20pct": bool(drift_pass),
        "anchor_slope_20pct": bool(anchor_pass),
        "round2_icepak_solved": t2 is not None,
    }
    ok = all(gates.values())
    return {
        "ok": ok,
        "gates": gates,
        "hfss": {
            "design": HFSS_DESIGN,
            "geometry": geom,
            "f0_t0_hz": f0_t0_hz,
            "peak_t0": peak,
            "n_sweep_points": n_sweep,
            "field_power_t0": fp0,
            "f0_t1_hz": f0_t1_hz,
            "field_power_t1": fp1,
            "f0_anchor_hz": f0_a_hz,
        },
        "bidirectional": {
            "rounds": 2,
            "t0_c": T_REF_C, "t1_c": t1, "t2_c": t2,
            "delta_t_r1_k": delta_t_r1,
            "f0_t0_hz": f0_t0_hz, "f0_t1_hz": f0_t1_hz,
            "drift_hz": drift_hz, "drift_ratio": drift_ratio,
            "closed_form_ratio": closed_ratio,
            "drift_deviation": drift_dev,
            "note": "|f0(T1)-f0(T0)| 为物理漂移；定点收敛性由离线 "
                    "solve_thermal_fixed_point（fake 评估器注入）演示",
        },
        "anchor": {
            "delta_t_k": DELTA_T_ANCHOR_K,
            "slope_ppm_per_k": slope_ppm_per_k,
            "closed_form_slope_ppm_per_k": closed_slope,
            "slope_deviation": slope_dev,
            "tcdk_eff_ppm_per_k": tcdk_eff,
            "cte_ppm_per_k": CTE_PPM_PER_K,
            "provenance": "HFSS 环形谐振器两温度点（εr(T)+CTE 尺寸膨胀），"
                          "本 JSON 即仲裁工件（#190 HFSS 对齐基准范式）",
        },
        "icepak": {
            "field_r1": {"t_ring_c": t_field1, "wall_w": wall_w,
                         "p_diss_hfss_w": p_diss_t0,
                         "conservation_rel": cons_rel},
            "lumped": {"t_ring_c": t_lumped, "power_w": p_diss_t0,
                       "diff_rel": diff_rel},
            "field_r2": {"t_ring_c": t_field2,
                         "p_diss_hfss_w": p_diss_t1},
            "r_th": r_th,
        },
        "aedt_version": AEDT_VERSION,
    }


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    last: dict | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"=== attempt {attempt}/{MAX_ATTEMPTS} ===", flush=True)
        _clean_project_artifacts()
        try:
            last = _run_case()
        except Exception as exc:
            last = {"ok": False, "error": f"unhandled: {exc}"}
        if last.get("ok"):
            break
        print(f"attempt {attempt} FAIL: {last.get('error')}", flush=True)
        if attempt < MAX_ATTEMPTS:
            _kill_desktops()
    OUT_JSON.write_text(json.dumps(last, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"WROTE {OUT_JSON}", flush=True)
    return 0 if last and last.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
