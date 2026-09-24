"""mline 均匀线 HFSS 通道探针（#191）。

分水岭实验：mline 已过 openEMS β 金标准（εeff≈2.886 @2.5GHz）。
若 HFSS 同几何健康（匹配 + εeff 双锚达标）→ HFSS 通道健康，
wilkinson 仲裁脚本问题在模板细节；若均匀线也全反射 → 手法层问题。
几何：均匀线 w=1.113mm 贯通 y∈[-40,40]（全均匀，总电长 80mm，
端面即端口面），S21 相位斜率→εeff 无歧义。

εeff 判读——双锚口径：
  主锚 = HFSS 对 openEMS β 金标准 ±2% → PASS/FAIL。锚值 2.886 为同几何
         全波真跑单点金标准（runs/benchmark/mline_mesh_convergence.json
         收敛值族 2.8813~2.8884，#189；归因档 §二采 2.886，HFSS 实测
         +1.18% 相容）。
  副锚 = HFSS 对 HJ 准静态闭式**放宽 ±3%**（择型理由：HJ 是独立来源解析
         锚（#118 纪律），完全降级为信息量会失去解析哨兵；实测系统偏移
         全谱 openEMS +1.18% / HFSS +2.36%/+2.53% 均在 3% 内，探针几何/
         频点钉死在 2.5GHz·w=1.113·RO4350B，不会误杀健康通道；若未来移
         出准静态有效域应显式重标定两锚，而非静默放水）。
  双锚任一超门或 |S11|min 未深于 -10dB → FAIL（如实不凑绿）。
判据内核（常量+dual_anchor_verdict）落 core/anchor_verdict.py 单一事实源
（engine harness 与 sweep_assert unitfix 臂同源
消费，防 scripts 多副本漂移 #116 同族）；本脚本为调用侧。

几何一律预计算浮点 + 显式单位（#218）：波端口 sheet 数值经
hfss_builder_utils.Quantity（B7 量纲安全构建器）构造并按工具序列化，
字符串算术表达式在构建期即被拒绝——#218 原案 "-2.5*1.113" 曾被 HFSS
按 SI 米求值，端口 sheet 悬空域外 2.78m（r2-r4 挂起真因）。
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

# 判据内核单一事实源（core/anchor_verdict.py）；sys.path hack 后置 import
# 为 ruff E402 覆盖形态（原 engine_benchmark_mline.py 同法）
from rfauto.core.anchor_verdict import (
    EPS_EFF_MLINE_GOLD,
    MAIN_ANCHOR_TOL_PCT,
    SUB_ANCHOR_TOL_PCT,
    dual_anchor_verdict,
)

REPO = Path(__file__).resolve().parents[1]
# 旧名兼容（探针单测/历史日志引用；金标准常量本体在 core）
EPS_EFF_OPENEMS_BETA = EPS_EFF_MLINE_GOLD
WORK = REPO / "runs" / "audit_freq_scale" / "hfss_mline_probe"
W, L_TOTAL, X_HALF, Y_HALF = 1.113, 80.0, 25.0, 40.0
ER, TAND, SUB_H = 3.66, 0.0037, 0.508
C0 = 299792458.0
# 官方波端口尺寸比例（Ansys Wave Port Size 口径，#192 仲裁 PASS_A 同法）：
# 宽 5×w、高 4×sub_h（自地起，含空气区）；origin x = -2.5×w（sheet 左缘）
PORT_W_FACTOR = 5.0
PORT_H_FACTOR = 4.0
PORT_X_FACTOR = -2.5


def _kill_desktops() -> None:
    """ansysedt 清场（治理单源）：孤儿点杀+活桌面 fail-closed（#245/#265）。

    委托 src/rfauto/infra/desktop_guard.py；旧实现 Get-Process|
    Stop-Process -Force 无条件代杀已废弃（误杀他轨合法桌面，#265）。
    """
    from rfauto.infra.desktop_guard import kill_orphan_ansysedt_desktops

    kill_orphan_ansysedt_desktops(log=print)


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    # 2025.1.0（无 SP）gRPC 通道级不稳定：每次桌面启动在随机的早期
    # 调用点（Rename/GetName/GetVariables）以 ~50% 概率失败——对策=
    # 整轮重试（杀桌面+清锁+重建），不做单调用级重试（#191）
    for attempt in range(3):
        try:
            _kill_desktops()
            import shutil

            shutil.rmtree(WORK, ignore_errors=True)
            WORK.mkdir(parents=True, exist_ok=True)
            return _run_probe()
        except Exception as exc:
            print(f"attempt {attempt + 1}/3 FAIL: {exc}", flush=True)
    print("MLINE_PROBE_FAIL_AFTER_3_ATTEMPTS")
    return 1


def _run_probe() -> int:
    from ansys.aedt.core import Hfss
    from ansys.aedt.core.generic.constants import Gravity

    from rfauto.adapters.hfss_builder_utils import Quantity

    h = Hfss(project=str(WORK / "mline_probe.aedt"), design="mline",
             version="2025.1", non_graphical=True, new_desktop=True)
    h.modeler.model_units = "mm"
    h.materials.add_material("rfauto_m366", properties={
        "permittivity": ER, "dielectric_loss_tangent": TAND})

    # 几何一律预计算浮点+显式单位后缀（#218 ①：纯数字串按模型单位补全，
    # 政策要求显式单位防模型 units 漂移）
    h.modeler.create_box(origin=[f"{-X_HALF}mm", f"{-Y_HALF}mm", "0mm"],
                         sizes=[f"{2 * X_HALF}mm", f"{2 * Y_HALF}mm",
                                f"{SUB_H}mm"],
                         name="Sub", material="rfauto_m366")
    h.modeler.create_box(origin=[f"{-W / 2}mm", f"{-Y_HALF}mm",
                                 f"{SUB_H}mm"],
                         sizes=[f"{W}mm", f"{2 * Y_HALF}mm", "0mm"],
                         name="Line", material="pec")
    h.modeler.create_box(origin=[f"{-X_HALF}mm", f"{-Y_HALF}mm", "0mm"],
                         sizes=[f"{2 * X_HALF}mm", f"{2 * Y_HALF}mm",
                                "0mm"],
                         name="Gnd", material="pec")
    h.assign_perfecte_to_sheets(assignment=["Line"], name="LinePEC")
    h.assign_perfecte_to_sheets(assignment=["Gnd"], name="GndPEC")
    # 波端口要求贴面介质 solve-inside（HFSS 官方语义：介质关 solve
    # inside 即"非可解材料"→ 端口报 no solved inside material，r2/r3
    # profile 实证）——显式钉住，防默认漂移
    h.modeler["Sub"].solve_inside = True

    # 空气盒 y 向不留边距（波端口必须在外边界；y 向留边距=内部端口，
    # 端口验证失败 Engine Detected Error，#191）；x/z 留 5mm 辐射缓冲。
    # 必须从空气盒 subtract 基板/走线（仲裁 r8 同法）——重叠体使端口
    # 面材质接触歧义："Port does not have a solved inside material on
    # either side"（r2 profile 实证，solve 4-7s 静默失败）
    h.modeler.create_box(
        origin=[f"{-(X_HALF + 5)}mm", f"{-Y_HALF}mm", "0mm"],
        sizes=[f"{2 * X_HALF + 10}mm", f"{2 * Y_HALF}mm",
               f"{SUB_H + 5}mm"],
        name="Air", material="vacuum")
    h.modeler.subtract("Air", ["Sub", "Line"])
    h.modeler["Air"].solve_inside = True
    air_faces = h.modeler.get_object_faces("Air")
    # 辐射只赋顶面 + x 侧外表面；y 侧端面与波端口同面（端口+辐射同面
    # HFSS 不支持，solve 2s 即败，#191）
    open_faces = []
    for f in air_faces:
        cx, cy, cz = h.modeler.get_face_center(f)
        on_y_side = abs(abs(cy) - (Y_HALF + 5)) < 1e-6
        if on_y_side:
            continue
        if abs(cz - (SUB_H + 5)) < 1e-6 or abs(abs(cx) - (X_HALF + 5)) < 1e-6:
            open_faces.append(f)
    h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")

    for name, y_mm in (("P1sheet", -Y_HALF), ("P2sheet", Y_HALF)):
        # 官方波端口尺寸（Ansys Wave Port Size 口径，#192 仲裁 PASS_A
        # 同法）：宽 5×w、高 4×sub_h（自地起，含空气区）——首版
        # 1×w×1×sub_h 端口模式严重截断致全反射（#191 实证）
        #
        # B7 量纲安全构建器（§10.19）热点接线示范：origin/尺寸经
        # Quantity 显式单位构造→to_hfss() 出预计算浮点+显式 mm。#218
        # 原案此处是字面算术表达式 f"-2.5*{W}"（被 HFSS 按 SI 米求值，
        # 端口 sheet 悬空域外 2.78m，r2-r4 挂起真因）——该类字符串输入
        # 在 Quantity 构建期即被拒绝，不再可能回流。
        port_w = PORT_W_FACTOR * Quantity.mm(W)
        port_h = PORT_H_FACTOR * Quantity.mm(SUB_H)
        port_x0 = PORT_X_FACTOR * Quantity.mm(W)
        h.modeler.create_rectangle(
            orientation="ZX",
            origin=[port_x0.to_hfss(), Quantity.mm(y_mm).to_hfss(), "0mm"],
            sizes=[port_h.to_hfss(), port_w.to_hfss()],
            name=name)
        port_face = h.modeler.get_object_faces(name)[0]
        h.wave_port(assignment=port_face, name=name + "P", impedance=50.0,
                    renormalize=True, integration_line=Gravity.ZPos)

    setup = h.create_setup(name="Setup")
    setup.props["Frequency"] = "2.5GHz"
    setup.props["MaxDeltaS"] = 0.02
    setup.props["MaximumPasses"] = 12
    setup.update()
    h.create_linear_count_sweep(setup="Setup", unit="GHz",
                                start_frequency=1.5, stop_frequency=3.5,
                                num_of_freq_points=201, name="Sweep",
                                sweep_type="Interpolating",
                                save_fields=False)
    t0 = time.time()
    h.analyze(setup="Setup")
    print(f"solve_s={time.time() - t0:.0f}", flush=True)

    from rfauto.adapters.hfss_adapter import HfssAdapter

    adapter = HfssAdapter()
    adapter.session.hfss = h
    s2p = adapter.export_touchstone(WORK / "mline_probe.s2p")

    import skrf

    net = skrf.network.Network(str(s2p))
    f = net.f
    s11 = net.s[:, 0, 0]
    s21 = net.s[:, 1, 0] if net.s.shape[2] >= 2 else net.s[:, 0, 0]
    m11 = 20 * np.log10(np.abs(s11) + 1e-12)
    i = int(np.argmin(m11))
    phase = np.unwrap(np.angle(s21))
    slope = np.polyfit(f, phase, 1)[0]
    eps_eff = (slope * C0 / (-2 * np.pi * L_TOTAL * 1e-3)) ** 2

    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    _, eps_hj = forward_z0(W, 2.5, stackup)
    res = dual_anchor_verdict(s11_min_db=float(m11[i]), eps_hfss=float(eps_eff),
                              eps_openems_beta=EPS_EFF_OPENEMS_BETA,
                              eps_hj=float(eps_hj))
    print(f"s11_min={m11[i]:.2f}dB@{f[i] / 1e9:.3f}GHz "
          f"s21@2.5={20 * np.log10(abs(np.interp(2.5e9, f, np.abs(s21))) + 1e-12):.2f}dB")
    print(f"eps_hfss={eps_eff:.4f} eps_openems_beta={EPS_EFF_OPENEMS_BETA} "
          f"delta_openems={res['delta_openems_pct']:+.2f}% "
          f"eps_hj={eps_hj:.4f} delta_hj={res['delta_hj_pct']:+.2f}%")
    print(f"DUAL_ANCHOR main±{MAIN_ANCHOR_TOL_PCT}%/sub±{SUB_ANCHOR_TOL_PCT}% "
          f"main_ok={res['main_ok']} sub_ok={res['sub_ok']} "
          f"match_ok={res['match_ok']}"
          + (f" reason: {res['reason']}" if res["reason"] else ""),
          flush=True)
    print(f"MLINE_PROBE_{res['verdict']}")
    h.release_desktop(close_projects=True, close_desktop=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
