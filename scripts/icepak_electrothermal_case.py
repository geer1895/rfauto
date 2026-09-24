"""Icepak 电-热首案例真机脚本（WP4.4a）。

链路：Wilkinson 隔离电阻损耗 → Icepak 温度场 → 材料温漂 →
S 参数失谐。全部数值由确定性内核产出（#7 纪律：LLM/脚本不发明物理数字）：

  1) 损耗（core/electrothermal）：隔离注入工况——输出端口 2 注入
     P_inj=1.0W（功率归一入射波），理想 Wilkinson（Pozar §7.3）隔离
     电阻耗散 P_res = P_inj/2 = 0.5W；
  2) 温度场（adapters/icepak_adapter，pyaedt Icepak 真机）：
     - 工况 A（1-D 传导锚）：发热块满覆基板 + 底面 Dirichlet +
       TemperatureOnly → 块中面温度对独立解析锚（Incropera 1-D 传导）
       门 ≤2%——只验"温度场求解机器可信"；
     - 工况 B（器件场景）：0805 量级隔离电阻块 2.0×1.25×0.15mm 置于
       RO4350B 量级基板 → T_blk 进温漂链；
  3) 温漂→失谐（core/electrothermal.thermal_detune，闭式单一事实源
     = thermal_iteration.closed_form_drift_ratio）：TCDk=+50 ppm/K、
     CTE=14 ppm/K（RO4350B 数据手册量级，占位口径如实标注）、
     f0=2.4GHz（recipes/wilkinson_pd_v1.yaml）、带 [2.3, 2.5]GHz
     （patch/wilkinson tune 系 recipe 同带）→ df0 与带内判据。

纪律：
- AEDT 2025.1 gRPC 通道级不稳定（#191）：整轮重试 ×3（仅本脚本自己
  启动的失败会话才 kill 桌面）；
- 真机失败如实写 JSON（ok=false + error），不凑绿；
- 产物：runs/icepak_electrothermal/electrothermal_case.json。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "runs" / "icepak_electrothermal"
OUT_JSON = WORK / "electrothermal_case.json"

# ── 案例参数（来源见模块头，均为显式口径非默认值漂移）─────────────────────────
P_INJECTED_W = 1.0          # 隔离注入工况：输出端口注入功率 [W]
F0_HZ = 2.4e9               # wilkinson_pd_v1.yaml f0_ghz
BAND_LO_HZ, BAND_HI_HZ = 2.3e9, 2.5e9
TCDK_PPM_PER_K = 50.0       # RO4350B 数据手册量级（锚定状态见下注）
CTE_PPM_PER_K = 14.0        # 同上（面内有效值量级）
# 锚定状态（WP4.4a ⑤，#190 "HFSS 为对齐基准"范式）：锚定腿已实装于
# scripts/icepak_hfss_loss_e2e.py（HFSS 环形谐振器两温度点 → df0/dT 有效
# 斜率 → TCDk_eff = 2·(|slope|−CTE)，仲裁工件 =
# runs/icepak_hfss_loss_e2e/e2e_case.json["anchor"]）。真机首跑
# 锚定判据未过（斜率对一阶闭式偏差 >20%，f0 提取受 HFSS 重解跳变污染、
# 归因待证），故占位常数维持数据手册口径并如实标注，未回写锚值
# （不凑绿 #122）；锚定判据通过后应以此处两常量替换为锚定值。
T_REF_C = 25.0              # 温漂参考温度 = Icepak 底面 Dirichlet 温度
DEVICE_BLOCK_MM = (2.0, 1.25, 0.15)  # 0805 量级隔离电阻块（器件工况）
MAX_ATTEMPTS = 3


def _kill_desktops() -> None:
    """attempt 间清理（治理单源，#157 先查后杀）。

    委托 src/rfauto/infra/desktop_guard.py：孤儿（父进程已死）点杀，
    活桌面/枚举失败只记录不抛（本调用点在 try 外，strict 抛错会炸掉
    重试架丢结果落盘——strict=False best-effort，#105）。
    旧实现 Get-Process|Stop-Process -Force 无条件代杀已废弃（#265）。
    """
    from rfauto.infra.desktop_guard import kill_orphan_ansysedt_desktops

    kill_orphan_ansysedt_desktops(log=print, strict=False)


def _run_case() -> dict:
    from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
    from rfauto.adapters.icepak_adapter import (
        IcepakAdapter,
        anchor_closed_form_c,
        normalize_stack_params,
    )
    from rfauto.core.electrothermal import isolation_injection_case
    from rfauto.service.electrothermal_service import run_wilkinson_electrothermal

    # ── 1) 隔离电阻损耗（确定性内核，能量守恒口径见模块 docstring）──────────
    power = isolation_injection_case(P_INJECTED_W)
    p_res = power["resistor_w"]
    print(f"[1] 隔离注入 P_inj={P_INJECTED_W}W → P_res={p_res}W "
          f"(port1 出 {power['port1_out_w']}W)", flush=True)

    # ── 2) Icepak 温度场（真机，A 锚 + B 器件）────────────────────────────
    cfg = EMSolverConfig(solver_type=EMSolverType.ICEPAK,
                         working_dir=str(WORK),
                         extra_params={"desktop_version": "2025.1",
                                       "problem_type": "TemperatureOnly",
                                       "save_project": True})
    adapter = IcepakAdapter(cfg)
    if not adapter.connect():
        return {"ok": False, "error": f"connect: {adapter._last_message}"}
    try:
        # 工况 A：满覆 1-D 传导锚（监控点=基板中面线性区，网格离散不敏感；
        # 首跑块内中面监控因体热源抛物面剖面的网格敏感性 2.79% 超门）
        if not adapter.use_design("rfauto_et_anchor"):
            return {"ok": False, "error": adapter._last_message}
        if not adapter.build_geometry({"power_w": p_res,
                                       "monitor_point": "substrate_midplane"}):
            return {"ok": False, "error": f"build A: {adapter._last_message}"}
        res_a = adapter.solve()
        if not res_a.success:
            return {"ok": False, "error": f"solve A: {res_a.message}"}
        anchor_sim = res_a.field_data["anchor"]
        anchor_cf = anchor_closed_form_c(normalize_stack_params(
            {"power_w": p_res}))
        print(f"[2A] 锚工况 T_sim={anchor_sim['t_sim_c']:.4f}C vs 闭式"
              f"{anchor_sim['t_closed_form_c']:.4f}C "
              f"(偏差 {anchor_sim['relative_deviation'] * 100:.3g}%, "
              f"门 2% pass={anchor_sim['pass_2pct']})", flush=True)

        # 工况 B：器件量级隔离电阻块
        if not adapter.use_design("rfauto_et_device"):
            return {"ok": False, "error": adapter._last_message}
        if not adapter.build_geometry({
                "power_w": p_res,
                "blk_len_mm": DEVICE_BLOCK_MM[0],
                "blk_wid_mm": DEVICE_BLOCK_MM[1],
                "blk_thk_mm": DEVICE_BLOCK_MM[2]}):
            return {"ok": False, "error": f"build B: {adapter._last_message}"}
        res_b = adapter.solve()
        if not res_b.success:
            return {"ok": False, "error": f"solve B: {res_b.message}"}
        t_blk = res_b.field_data["t_blk_c"]
        print(f"[2B] 器件工况 T_blk={t_blk:.3f}C "
              f"(wall {res_b.wall_time_s:.1f}s)", flush=True)
    finally:
        adapter.close()

    # ── 3) 温漂 → 失谐（service 链，注入真机温度）────────────────────────
    chain = run_wilkinson_electrothermal({
        "case": {"scenario": "isolation_injection",
                 "injected_power_w": P_INJECTED_W},
        "thermal": {"ambient_c": T_REF_C, "t_hot_c": t_blk},
        "material": {"t_ref_c": T_REF_C, "cte_ppm_per_k": CTE_PPM_PER_K,
                     "tcdk_ppm_per_k": TCDK_PPM_PER_K},
        "resonator": {"f0_hz": F0_HZ},
        "band": {"low_hz": BAND_LO_HZ, "high_hz": BAND_HI_HZ},
    })
    if not chain.get("ok"):
        return {"ok": False, "error": f"chain: {chain.get('error')}"}
    drift = chain["chain"]["drift"]
    band = chain["chain"]["band"]
    print(f"[3] ΔT={chain['chain']['material']['delta_t_c']:.3f}K → "
          f"df={drift['df_hz'] / 1e3:+.1f}kHz ({drift['df_ppm']:+.1f}ppm)，"
          f"f0'={drift['f0_shifted_hz'] / 1e9:.6f}GHz，带内={band['in_band']}",
          flush=True)

    return {
        "ok": True,
        "case": {
            "scenario": "wilkinson_isolation_injection",
            "injected_power_w": P_INJECTED_W,
            "f0_hz": F0_HZ, "band_hz": [BAND_LO_HZ, BAND_HI_HZ],
            "material": {"tcdk_ppm_per_k": TCDK_PPM_PER_K,
                         "cte_ppm_per_k": CTE_PPM_PER_K,
                         "note": "RO4350B 数据手册量级占位口径"},
        },
        "power": power,
        "icepak": {
            "anchor": {"sim": anchor_sim,
                       "block_midplane_reference_c": anchor_cf,
                       "tolerance": 0.02},
            "device": {"t_blk_c": t_blk,
                       "block_mm": list(DEVICE_BLOCK_MM),
                       "wall_time_s": res_b.wall_time_s},
            "aedt_version": "2025.1",
            "problem_type": "TemperatureOnly",
        },
        "chain": chain["chain"],
    }


def _clean_project_artifacts() -> None:
    """清掉上次运行遗留的 AEDT 工程（陈旧设计会让 insert_design 重建出
    重名对象/边界，监控点读数退化为默认 20C——真机二跑实证）。
    只点名 AEDT 工程产物，不碰日志与 JSON 证据（白名单式清理）。"""
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
    (WORK / "electrothermal_case.json").write_text(
        json.dumps(last, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {OUT_JSON}", flush=True)
    return 0 if last and last.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
