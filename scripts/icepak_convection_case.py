"""WP4.4a ② Icepak 自然对流工况真机脚本（TemperatureAndFlow）。

链路：0805 量级隔离电阻块（2.0×1.25×0.15mm，P_res=0.5W，隔离注入工况
core/electrothermal.isolation_injection_case）+ RO4350B 量级基板，置入
空气域（adapter.build_convection_case）：

  - create_region：包围盒 Absolute Offset 10mm 六向空气域；
  - edit_design_settings：重力 −Z（pyaedt gravity_dir=2；预声明草案
    "5=−Z" 与 pyaedt icepak.py:1106-1115 实装相反，按代码实裁定）、
    环境温度 25C；
  - assign_openings：空气域六面开口（自然对流进出口）；
  - HeatFlowRate 面监控：壁面 1 + 开口每面 1（能量平衡数据源）；
  - problem_type=TemperatureAndFlow（层流默认）。

判据（冻结口径；无闭式自然对流裁判——如实冒烟级）：
  - 能量平衡 ≤10%：壁面导出热 + 开口对流热 ≈ P_in（HeatFlowRate 监控
    汇总，adapter.solve() 内置门）；
  - 物理健康：同功率下 T_自然对流 < T_纯传导（对照=同几何纯传导设计
    TemperatureOnly 真跑，非闭式近似——小器件块展布热阻使满覆闭式严重
    低估，闭式只作参考输出）；
  - 解收敛（Icepak 求解器收敛完成=analyze 正常返回+监控可读）。

纪律：AEDT 2025.1 gRPC 整轮重试 ×3（#191，仅杀本脚本遗留桌面）；
每轮前白名单清工程产物；真机失败如实 ok=false 不凑绿（#122）。

产物：runs/icepak_convection_case/convection_case.json
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "runs" / "icepak_convection_case"
OUT_JSON = WORK / "convection_case.json"

AEDT_VERSION = "2025.1"
P_INJECTED_W = 1.0            # 隔离注入工况：输出端口注入功率 [W]
DEVICE_BLOCK_MM = (2.0, 1.25, 0.15)  # 0805 量级隔离电阻块
MAX_ATTEMPTS = 3


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
    """白名单清 AEDT 工程产物（陈旧设计重名=监控读默认值的坑；.lock 残留=
    下一轮 "Project is locked"——首跑重试实证）。adapter 默认工程名
    wp44a_electrothermal.aedt（无 project_path 模式）。"""
    import shutil

    for name in ("wp44a_electrothermal.aedt",
                 "wp44a_electrothermal.aedt.lock",
                 "wp44a_electrothermal.aedtresults",
                 "wp44a_electrothermal.pyaedt"):
        path = WORK / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink(missing_ok=True)


def _run_case() -> dict:
    from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
    from rfauto.adapters.icepak_adapter import (
        IcepakAdapter,
        anchor_closed_form_c,
        normalize_stack_params,
    )
    from rfauto.core.electrothermal import isolation_injection_case

    # ── 1) 隔离电阻损耗（确定性内核；与首案例同工况口径）──────────────────
    power = isolation_injection_case(P_INJECTED_W)
    p_res = power["resistor_w"]
    print(f"[1] 隔离注入 P_inj={P_INJECTED_W}W → P_res={p_res}W", flush=True)

    # ── 2) 自然对流设计 + 纯传导对照设计（同一 adapter，problem_type 按设计）
    cfg = EMSolverConfig(
        solver_type=EMSolverType.ICEPAK, working_dir=str(WORK),
        extra_params={"desktop_version": AEDT_VERSION,
                      "problem_type": "TemperatureAndFlow",
                      "design_name": "rfauto_conv",
                      "save_project": False})
    adapter = IcepakAdapter(cfg)
    if not adapter.connect():
        return {"ok": False, "error": f"connect: {adapter._last_message}"}
    try:
        stack = {"power_w": p_res,
                 "blk_len_mm": DEVICE_BLOCK_MM[0],
                 "blk_wid_mm": DEVICE_BLOCK_MM[1],
                 "blk_thk_mm": DEVICE_BLOCK_MM[2]}
        if not adapter.build_convection_case(dict(stack, region_pad_mm=10.0)):
            return {"ok": False, "error": f"build conv: {adapter._last_message}"}
        t_conv_wall = time.perf_counter()
        res_conv = adapter.solve()
        if not res_conv.success:
            return {"ok": False, "error": f"solve conv: {res_conv.message}"}
        t_conv = res_conv.field_data["t_blk_c"]
        conv_wall = time.perf_counter() - t_conv_wall
        balance = res_conv.field_data["anchor"]["energy_balance"]
        healthy = res_conv.field_data["anchor"]["physically_healthy"]
        print(f"[2A] 自然对流 T={t_conv:.3f}C 能量平衡偏差="
              f"{balance['relative_imbalance'] * 100:.2f}%（门 10% "
              f"pass={balance['pass']}）壁面 {balance['wall_w']:.4f}W + "
              f"开口 {balance['openings_w']:.4f}W vs P={balance['p_in_w']}W",
              flush=True)

        # 纯传导对照：同空气域同网格族、不开口、关流动（TemperatureOnly）。
        # 2025.1 真机实证：无域对照网格对小块更细，温度差被网格噪声淹没
        # （242.5 vs 219.7，方向非物理）——对照必须同几何域。
        if not adapter.use_design("rfauto_cond", problem_type="TemperatureOnly"):
            return {"ok": False, "error": adapter._last_message}
        if not adapter.build_convection_case(
                dict(stack, region_pad_mm=10.0, with_openings=False)):
            return {"ok": False, "error": f"build cond: {adapter._last_message}"}
        res_cond = adapter.solve()
        if not res_cond.success:
            return {"ok": False, "error": f"solve cond: {res_cond.message}"}
        t_cond = res_cond.field_data["t_blk_c"]
        cooler = t_conv < t_cond
        print(f"[2B] 同域纯传导对照 T={t_cond:.3f}C → 自然对流更低={cooler}"
              f"（ΔT={t_cond - t_conv:.3f}K）", flush=True)

        # 闭式满覆参考（小块展布下严重低估，仅记录不判门——#195 同源纪律：
        # 判据形态必须匹配响应形态）
        cf = anchor_closed_form_c(normalize_stack_params(
            {"power_w": p_res,
             "blk_len_mm": DEVICE_BLOCK_MM[0],
             "blk_wid_mm": DEVICE_BLOCK_MM[1],
             "blk_thk_mm": DEVICE_BLOCK_MM[2]}))
    finally:
        adapter.close()

    gates = {
        "energy_balance_10pct": bool(balance["pass"]),
        "cooler_than_conduction": bool(healthy and cooler),
    }
    ok = all(gates.values())
    return {
        "ok": ok,
        "gates": gates,
        "power": power,
        "convection": {
            "t_blk_c": t_conv,
            "wall_time_s": conv_wall,
            "energy_balance": balance,
            "problem_type": "TemperatureAndFlow",
            "gravity_dir": 2,
            "gravity_note": "pyaedt edit_design_settings 口径 2=−Z（预声明"
                            "草案 5=−Z 与实装相反，按代码实裁定）",
            "region_pad_mm": 10.0,
        },
        "conduction_reference": {
            "t_blk_c": t_cond,
            "problem_type": "TemperatureOnly",
            "note": "对照=同空气域(10mm 六向填充)不开口关流动设计——与对流"
                    "设计同几何同网格族，仅差流动物理（2025.1 实证无域对照"
                    "网格噪声淹没物理差）",
            "closed_form_full_coverage_c": cf["t_monitor_c"],
            "closed_form_note": "满覆 1-D 闭式对小块展布工况严重低估，仅记录",
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
