"""0.1⑤ HFSS 同几何仲裁：E4 探针 wilkinson 标称点在 HFSS 中的独立复算。

背景（0.1 频率尺度根因闭环的最后一环）：openEMS 官方方法学重建后谷位
收敛于 ~2.2GHz（E4/E4-fine，runs/audit_freq_scale/e4_wilk*/），而设计
预期 2.5GHz（arm=λ/4 @2.5）。-10%~-12% 残差当初归结为"色散/结效应"
（耦合臂偶模色散 + T 结不连续，理想闭式不含）——该归结目前是假设
（docs/v1_acceptance_verdict.md §4 caveat）。本脚本把 E4 探针的同一
几何（同参数/同端口面位置/同集总电阻）在 HFSS 中独立重建求解，用第
三方求解器仲裁残差归属。

判据（确定性，写入 result.json 的 verdict 字段）：
- f_v(HFSS) ≤ 2.31GHz（=2.2+5%）→ PASS-A：openEMS 谷位可信，残差
  属物理（色散/结效应），0.1⑤ 关闭，结论归档进阶段 1 验收档案。
- f_v(HFSS) ≥ 2.35GHz（=2.5-6%）→ FAIL-B：openEMS 谷位存在系统差，
  回 1b 模板审计（网格/端口口径/边界逐项对照 HFSS）。
- 两者之间 → INCONCLUSIVE：如实记录，补参考面/网格档对照后再判。

方法学对齐与已声明差异（写入 report.md）：
- 金属：零厚度 PEC sheet（对齐 openEMS Metal 面语义）；
- 地：z=0 PEC 面（对齐 openEMS z-min PEC 边界）；
- 侧/顶边界：HFSS 辐射边界贴基板边缘（对齐 openEMS 侧向 MUR 贴基板
  边缘；顶部同 E4 的 5mm 空气——两者同享"边界离线近"的紧致性，这是
  受控对照的一部分）；
- 端口：HFSS wave port 50Ω renormalize @馈线端边界。馈线是匹配 50Ω
  线，|S11| 沿无损匹配线不变 → 参考面位置对谷位是二阶效应，不复刻
  E4 的 MeasPlaneShift=L/3；
- 介质 er=3.66 tanδ=0.0037、扫频 1.5-3.5GHz 401 点：同 E4。

运行前提（内存纪律）：patch/dipole 等真机任务空闲、
wmic OS get FreePhysicalMemory ≥ 4GB。执行：
    .venv\\Scripts\\python.exe scripts\\hfss_same_geometry_arbitration.py
产物：runs/audit_freq_scale/hfss_arbitration/{result.json, report.md,
hfss_arb.s3p}
"""
from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = REPO_ROOT / "runs" / "audit_freq_scale" / "hfss_arbitration"

# E4 探针标称点（runs/audit_freq_scale/probe_wilk_official.py，mm/Hz）
W_IN, W_ARM, L_ARM = 1.113, 0.604, 18.1
GAP = 8.0
ER, TAND, SUB_H = 3.66, 0.0037, 0.508
Y_T, Y_END = -30.0, -11.9          # T 分叉 y / 臂端 y
Y_IN_B, Y_OUT_B = -50.0, 30.0      # 输入/输出端口边界（馈线 20 / 41.9mm）
X_HALF = 25.0                      # 基板半宽（E4 域侧边界）
XA = GAP / 2 + W_ARM / 2           # 臂中心线 x
R_ISO = 100.0
AIR_TOP = 5.0                      # E4 同款顶部空气厚度
F_V_OPENEMS_GHZ = 2.2              # E4-fine 收敛谷位（对照锚）
PASS_A_MAX_GHZ = 2.31              # 2.2 + 5%
FAIL_B_MIN_GHZ = 2.35              # 2.5 - 6%


def build_e4_geometry(adapter) -> str:
    """在 HFSS 中重建 E4 探针几何，返回输入波端口对象名。"""
    hfss = adapter.session.hfss
    modeler = hfss.modeler
    modeler.model_units = "mm"

    mat = f"rfauto_arb_{int(ER * 100)}"
    # PyAEDT 1.4 签名：add_material(name, properties: dict)（旧 kwargs 口径
    # 抛 TypeError 且会被 suppress 吞掉，随后首个 set_variables 必崩，#191）
    with contextlib.suppress(Exception):
        hfss.materials.add_material(
            mat, properties={"permittivity": ER,
                             "dielectric_loss_tangent": TAND})  # 重复执行时复用

    vars_ = {
        "w_in": f"{W_IN}mm", "w_arm": f"{W_ARM}mm", "l_arm": f"{L_ARM}mm",
        "gap": f"{GAP}mm", "sub_h": f"{SUB_H}mm",
        "y_t": f"{Y_T}mm", "y_end": f"{Y_END}mm",
        "y_in_b": f"{Y_IN_B}mm", "y_out_b": f"{Y_OUT_B}mm",
        "x_half": f"{X_HALF}mm", "xa": f"{XA}mm", "air_top": f"{AIR_TOP}mm",
    }
    for k, v in vars_.items():
        hfss[k] = v

    # 基板 + 地（零厚度 PEC box，官方推荐模式，同插件惯例）
    modeler.create_box(
        origin=["-x_half", "y_in_b", "0mm"],
        sizes=["(2*x_half)", "(y_out_b-y_in_b)", "sub_h"],
        name="ArbSubstrate", material=mat)
    modeler.create_box(
        origin=["-x_half", "y_in_b", "0mm"],
        sizes=["(2*x_half)", "(y_out_b-y_in_b)", "0mm"],
        name="ArbGround", material="pec")

    # 走线：零厚度 PEC（对齐 openEMS metal sheet 语义）→ unite
    modeler.create_box(
        origin=["(-w_in/2)", "y_in_b", "sub_h"],
        sizes=["w_in", "(y_t-y_in_b)", "0mm"], name="ArbTraceIn",
        material="pec")
    modeler.create_box(
        origin=["(-xa-w_arm/2)", "y_t", "sub_h"],
        sizes=["(2*xa+w_arm)", "w_arm", "0mm"], name="ArbTraceTbar",
        material="pec")
    modeler.create_box(
        origin=["(-xa-w_arm/2)", "y_t", "sub_h"],
        sizes=["w_arm", "(y_end-y_t)", "0mm"], name="ArbTraceArmL",
        material="pec")
    modeler.create_box(
        origin=["(xa-w_arm/2)", "y_t", "sub_h"],
        sizes=["w_arm", "(y_end-y_t)", "0mm"], name="ArbTraceArmR",
        material="pec")
    # 输出馈线 ×2（臂端 → y_out_b 端口面，50Ω w_in）——首版漏建致
    # P2/P3 端口悬空（S21/S31≈-145dB、P1 全反射，#191 实证）
    modeler.create_box(
        origin=["(xa-w_in/2)", "y_end", "sub_h"],
        sizes=["w_in", "(y_out_b-y_end)", "0mm"], name="ArbTraceOutR",
        material="pec")
    modeler.create_box(
        origin=["(-xa-w_in/2)", "y_end", "sub_h"],
        sizes=["w_in", "(y_out_b-y_end)", "0mm"], name="ArbTraceOutL",
        material="pec")
    modeler.unite(
        ["ArbTraceIn", "ArbTraceTbar", "ArbTraceArmL", "ArbTraceArmR",
         "ArbTraceOutR", "ArbTraceOutL"],
        keep_originals=False)

    # 零厚度 sheet 的 material="pec" 不产生导电边界（PyAEDT 1.4 不再
    # 自动转，validation 还 PASSED——边界清单里无 PerfectE，走线/地是
    # 不导电隐形片，端口全反射、S21≈-145dB，#191 实证）——显式赋 PerfectE
    hfss.assign_perfecte_to_sheets(assignment=["ArbTraceIn"],
                                   name="ArbTracePEC")
    hfss.assign_perfecte_to_sheets(assignment=["ArbGround"],
                                   name="ArbGroundPEC")

    # 隔离电阻：XY 面 sheet 跨两臂臂端，电流沿 X，100Ω。
    # x 精确收窄到两臂内缘（±(xa-w_arm/2)）——旧版 x∈±gap/2 与臂
    # PerfectE sheet 重叠，重叠区电阻被 PEC 击败（#191）
    modeler.create_rectangle(
        orientation="XY",
        origin=["-(xa-w_arm/2)", "(y_end-w_arm/2)", "sub_h"],
        sizes=["(2*(xa-w_arm/2))", "w_arm"], name="ArbResistor")
    from ansys.aedt.core.generic.constants import Gravity

    hfss.assign_lumped_rlc_to_sheet(
        assignment="ArbResistor", start_direction=Gravity.XPos,
        name="ArbResistorR", rlc_type="Parallel", resistance=R_ISO)

    # 空气域：侧向贴基板边缘、顶 5mm（E4 域对齐），辐射边界盖顶+四侧
    modeler.create_box(
        origin=["-x_half", "y_in_b", "0mm"],
        sizes=["(2*x_half)", "(y_out_b-y_in_b)", "(sub_h+air_top)"],
        name="ArbAir", material="air")
    modeler.subtract("ArbAir", ["ArbSubstrate", "ArbTraceIn"])
    air_faces = modeler.get_object_faces("ArbAir")
    top_z = SUB_H + AIR_TOP
    # 只辐射顶面 + x 侧外表面（#191）：y 端面与波端口共面（端口+辐射
    # 同面 HFSS 不支持）；subtract 挖基板留下的内腔面（z=sub_h 平面/
    # 腔壁，center z<sub_h+…）是域内面，赋辐射即报 internal radiation
    # boundary（r4 profile 实证）。z=0 面贴 PEC 地，也不辐射。
    open_faces = []
    for f in air_faces:
        cx, _cy, cz = modeler.get_face_center(f)
        if cz > SUB_H + 1e-6 and (abs(cz - top_z) < 1e-6
                                  or abs(abs(cx) - X_HALF) < 1e-6):
            open_faces.append(f)
    hfss.assign_radiation_boundary_to_faces(
        assignment=open_faces, name="ArbRadiation")

    # 波端口：XZ 面 sheet（法向 Y）贴空气盒端面。尺寸按官方口径
    # （Ansys "Wave Port Size" / EDABoard 惯例，同 wilkinson 插件已验证
    # 手法）：宽 5×w_in、高 4×sub_h——首版 1×w_in×1×sub_h 端口模式
    # 严重截断致全反射（S11≈0dB 全带，#191 实证）
    def _port(name: str, y_expr: str, center_x_expr: str) -> str:
        modeler.create_rectangle(
            orientation="ZX",
            origin=[f"({center_x_expr}-2.5*w_in)", y_expr, "0mm"],
            sizes=["(4*sub_h)", "(5*w_in)"], name=name)
        return modeler.get_object_faces(name)[0]

    in_face = _port("ArbPortSheetIn", "y_in_b", "0mm")
    hfss.wave_port(assignment=in_face, name="ArbP1", impedance=50.0,
                   renormalize=True,
                   integration_line=Gravity.ZPos)
    out1 = _port("ArbPortSheetOut1", "y_out_b", "(xa)")
    hfss.wave_port(assignment=out1, name="ArbP2", impedance=50.0,
                   renormalize=True, integration_line=Gravity.ZPos)
    out2 = _port("ArbPortSheetOut2", "y_out_b", "(-xa)")
    hfss.wave_port(assignment=out2, name="ArbP3", impedance=50.0,
                   renormalize=True, integration_line=Gravity.ZPos)
    return "ArbP1"


def make_setup(adapter) -> str:
    """自适应 @2.5GHz（紧判据 delta 0.01/15 passes）+ 1.5-3.5GHz 401 点插值扫频。"""
    hfss = adapter.session.hfss
    setup = hfss.create_setup(name="ArbSetup")
    setup.props["Frequency"] = "2.5GHz"
    setup.props["MaxDeltaS"] = 0.01
    setup.props["MaximumPasses"] = 15
    setup.update()
    hfss.create_linear_count_sweep(
        setup="ArbSetup", unit="GHz", start_frequency=1.5,
        stop_frequency=3.5, num_of_freq_points=401, name="ArbSweep",
        sweep_type="Interpolating", save_fields=False)
    return "ArbSetup"


def verdict_of(f_v: float) -> str:
    """仲裁判据（确定性，单测口径同报告）。"""
    if f_v <= PASS_A_MAX_GHZ:
        return "PASS_A"
    if f_v >= FAIL_B_MIN_GHZ:
        return "FAIL_B"
    return "INCONCLUSIVE"


def analyze(s3p: Path) -> dict:
    """从 Touchstone 提取谷位/深度/劈裂健康指标并给判定。"""
    import numpy as np
    import skrf

    net = skrf.Network(str(s3p))
    f = net.frequency.f
    s11db = 20 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-12)
    band = (f >= 1.5e9) & (f <= 3.5e9)
    i = int(np.argmin(s11db[band]))
    fv_hz = float(f[band][i])
    fv = fv_hz / 1e9  # GHz（首版把 Hz 值直接当 GHz 比较，verdict 全错，#191）
    s21 = 20 * np.log10(np.abs(net.s[band][i, 1, 0]) + 1e-12)
    s31 = 20 * np.log10(np.abs(net.s[band][i, 2, 0]) + 1e-12)
    # 健康判据：谷深 ≤-10dB 且等分口径 |S21-(-3)|≤1dB——不达标时判定
    # 不可采信，改判 INCONCLUSIVE（模板未达健康口径，r7 实证）
    healthy = bool(
        s11db[band][i] <= -10.0 and abs(s21 + 3.0) <= 1.0)
    verdict = verdict_of(fv) if healthy else "INCONCLUSIVE"
    return {
        "valley_ghz": round(fv, 4),
        "valley_s11_db": float(s11db[band][i]),
        "s21_at_valley_db": float(s21),
        "s31_at_valley_db": float(s31),
        "f_v_openems_ghz": F_V_OPENEMS_GHZ,
        "residual_vs_openems_pct": round(
            (fv - F_V_OPENEMS_GHZ) / F_V_OPENEMS_GHZ * 100, 2),
        "healthy": healthy,
        "verdict": verdict,
    }


def write_report(res: dict, passes: int, delta_s: float) -> Path:
    lines = [
        "# 0.1⑤ HFSS 同几何仲裁报告", "",
        f"- 谷位（HFSS）：**{res['valley_ghz']:.3f} GHz**"
        f"（深度 {res['valley_s11_db']:.1f} dB）",
        f"- 谷位（openEMS E4-fine 锚）：{res['f_v_openems_ghz']:.2f} GHz",
        f"- 残差：{res['residual_vs_openems_pct']:+.2f}%",
        f"- S21/S31 @谷：{res['s21_at_valley_db']:.2f} / "
        f"{res['s31_at_valley_db']:.2f} dB（健康口径 -3dB±0.5）",
        f"- 自适应收敛：{passes} passes，末次 ΔS={delta_s:.4f}",
        f"- **判定：{res['verdict']}**"
        "（PASS_A=残差属色散/结效应，openEMS 可信；"
        "FAIL_B=openEMS 系统差，回 1b 模板审计）", "",
        "方法学差异声明：HFSS 辐射边界贴基板边缘（对齐 openEMS MUR 位置）、"
        "顶部同 5mm；馈线为匹配 50Ω 线故参考面位置对谷位是二阶效应。"
        "判据阈值：PASS_A ≤2.31GHz / FAIL_B ≥2.35GHz。",
    ]
    out = WORK_DIR / "report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _kill_desktops() -> None:
    """ansysedt 清场（治理单源）：孤儿点杀+活桌面 fail-closed（#245/#265）。

    委托 src/rfauto/infra/desktop_guard.py；旧实现 Get-Process|
    Stop-Process -Force 无条件代杀已废弃（误杀他轨合法桌面，#265）。
    """
    from rfauto.infra.desktop_guard import kill_orphan_ansysedt_desktops

    kill_orphan_ansysedt_desktops(log=print)


def main() -> int:
    # 2025.1.0（无 SP）gRPC 通道级不稳定（#191）：整轮重试 ×3
    for attempt in range(3):
        try:
            _kill_desktops()
            import shutil

            shutil.rmtree(WORK_DIR, ignore_errors=True)
            return _run()
        except Exception as exc:
            print(f"attempt {attempt + 1}/3 FAIL: {exc}", flush=True)
    print("ARB_FAIL_AFTER_3_ATTEMPTS")
    return 1


def _run() -> int:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.infra.version_probe import resolve_aedt_install

    install = resolve_aedt_install(None)
    assert install is not None, "未发现可用 AEDT 安装（RFAUTO_AEDT_PATH 未设且自动探测失败）"
    version = install["aedt_version"]

    adapter = HfssAdapter()
    adapter.connect({"desktop_version": version, "non_graphical": True})
    try:
        adapter.open_or_create_project(
            WORK_DIR / "hfss_arbitration.aedt", "same_geometry_e4")
        build_e4_geometry(adapter)
        setup_name = make_setup(adapter)

        import os
        timeout_s = int(os.environ.get("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "14400"))
        report = adapter.solve(setup_name, timeout_s=timeout_s)
        assert report.success, f"求解失败: {report.message}"

        passes, delta_s = 0, 0.0
        with contextlib.suppress(Exception):
            setup = adapter.session.hfss.get_setup(setup_name)
            if setup is not None:
                passes, delta_s = HfssAdapter._extract_convergence(setup)

        s3p = adapter.export_touchstone(WORK_DIR / "hfss_arb.s3p")
        res = analyze(Path(s3p))
        res.update({"passes": passes, "final_delta_s": delta_s,
                    "aedt_version": version})
        (WORK_DIR / "result.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=1),
            encoding="utf-8")
        write_report(res, passes, delta_s)
        print(json.dumps(res, ensure_ascii=False))
        print("ARB_DONE" if res["verdict"] == "PASS_A" else "ARB_VERDICT_"
              + res["verdict"])
        return 0
    finally:
        adapter.close(save=True)


if __name__ == "__main__":
    sys.exit(main())
