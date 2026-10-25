"""SB22-PK-1 金标准 Q3D 对拍发射面准备（[SERVER] 批；本批只准备不发射）。

残差出处：INVENTORY.md 清单二 SB22 行残差四件之一（PK-1 金标准 Q3D 对拍；
文献量级表=其外部替代，tests/unit/test_pk2_vertical_lit_and_wiring.py 钉 3）。
本脚本=发射面：案例定义+闭式期望（消费 core 单源内核）+判读器+发射路径，
**不发射**（服务器 8 路 OE 在跑+HFSS 50051 被 SRV-DESIGNS 席占用）。

环境前置（复进条件，#122 如实声明）
------------------------------------------------------------
- **AEDT SP1 缺失=当前硬阻塞**：本机 2025.1（v251 无 SP）gRPC 桥矩阵导出
  族命令全部失败（export_matrix_data/裸 ExportMatrixData×6 参数/
  ExportCircuit/AlphaNumericTable 逐一实证，内部证据档*.log
  + case_result.json；solve 本身成功，阻塞在工具桥）；服务器 sim_server
  同为无 SP1（ge9 定谳 VERIFIED-NEGATIVE，与 E-05 mTLS 同前置）。
- **复进条件**：目标机（本机或服务器）AEDT 装 SP1+后，按本脚本原路径发射；
  SP 前发射将得到 solve 成功+导出失败 → INCONCLUSIVE（判读器如实落盘，
  不伪造结果）。
- 发射姿势（届时）：Start-Process 分离进程+日志轮询（#157）；attempt 间
  委托 desktop_guard.kill_orphan_ansysedt_desktops（#265）；gRPC 整轮重试
  （#191 口径，MAX_ATTEMPTS=3）；临时产物全落 runs/q3d_package_chain/
  （服务器侧执行则 E:\rfauto_remote 下同构目录，内核立规注记 0b）。

案例协议（两案例，返回路径约定逐案声明）
------------------------------------------------------------
- **case A：RDL 微带线（rfauto_trace 模板原路径，launch-ready）**——
  RDL 尺度参数（w=5µm/t=2µm/h=2µm/εr=3.3/len=1mm）走 q3d_adapter 既有
  build_geometry→solve→导出链；闭式期望=core/parasitic.interconnect_rlc_anchor
  （传输线恒等式 L=Z0√εeff/c0、C=√εeff/(Z0·c0)，Z0/εeff=HJ 单源）；
  门=ANCHOR_TOLERANCE 5%（adapter 既有锚门，RDL/PCB 同模板同权）。
- **case B：TGV 同轴（首发射需 API shake-down）**——Cu 棒 r=25µm×
  500µm+同轴 pec 屏蔽管（内 25µm/外 75µm，Ground）+玻璃 εr=6 环氧；
  返回路径=3r 同轴壳（与 core tgv_line_network 的 r_shield=3r 声明口径
  逐字对齐）；期望=L/C per-length×长度、z0_coax=η0·ln(3)/(2π√εr)；
  门=文献带端点 ±30%（L∈[0.07,0.65] nH、C∈[70,650] fF 总量，同
  test_pk2_vertical_lit_and_wiring 行 3）+z0 恒等 ≤1%。
- bondwire/bump 行**不在本批**（线-地平面回路闭式不在 core 内核，
  不在脚本里手写物理公式=铁律 7；升格前置=内核补线-平面回路式，另立）。

用法::
    .venv/Scripts/python.exe scripts/q3d_package_chain_case.py --dry-run   # 离线（本批已验）
    .venv/Scripts/python.exe scripts/q3d_package_chain_case.py             # 真发射（SP1 后）
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

WORKDIR = Path("runs/q3d_package_chain")
RESULT_JSON = WORKDIR / "case_result.json"
DRYRUN_JSON = WORKDIR / "dry_run.json"
MAX_ATTEMPTS = 3

#: case A 参数（RDL 尺度；normalize_trace_params 白名单键）
RDL_SPEC: dict[str, float] = {
    "trace_len_mm": 1.0,
    "trace_w_mm": 0.005,
    "trace_t_mm": 0.002,
    "sub_h_mm": 0.002,
    "sub_eps_r": 3.3,
    "sub_tan_d": 0.02,
    "sub_margin_mm": 0.05,
    "gnd_t_mm": 0.002,
    "solution_freq_ghz": 10.0,
    "max_passes": 12,
}

#: case B 参数（TGV 同轴；与 core tgv_line_network 行 3 同一设计点）
TGV_SPEC: dict[str, float] = {
    "r_via_m": 25e-6,
    "r_shield_m": 75e-6,
    "length_m": 500e-6,
    "er_glass": 6.0,
}

#: 文献带端点 ±30%（预声明；越带即红不凑绿 #122；同 lit 表行 3）
TGV_L_BAND_NH = (0.07, 0.65)
TGV_C_BAND_FF = (70.0, 650.0)
TGV_Z0_IDENTITY_TOL = 0.01


def expected_values() -> dict[str, Any]:
    """两案例的闭式期望（消费 core 单源内核，确定性零 IO）。

    case A 走 adapter.anchor_for_spec（内核 interconnect_rlc_anchor）；
    case B 走 core.package_chain.tgv_line_network（rosa/同轴单源）。
    """
    from rfauto.adapters.q3d_adapter import anchor_for_spec, normalize_trace_params
    from rfauto.core.package_chain import tgv_line_network

    spec = normalize_trace_params(RDL_SPEC)
    anchor = anchor_for_spec(spec)

    freq = [1.0e9]
    tgv = tgv_line_network(freq, r_via_m=TGV_SPEC["r_via_m"],
                           r_shield_m=TGV_SPEC["r_shield_m"],
                           length_m=TGV_SPEC["length_m"],
                           er_glass=TGV_SPEC["er_glass"])
    l_total_nh = tgv["l_per_length_nh_per_mm"] * TGV_SPEC["length_m"] * 1e3
    c_total_ff = tgv["c_per_length_ff_per_mm"] * TGV_SPEC["length_m"] * 1e3
    return {
        "case_a_rdl": {
            "kind": "rdl_microstrip",
            "spec": spec,
            "expected": anchor,
            "gate": {"tolerance": 0.05,
                     "basis": "interconnect_rlc_anchor 传输线恒等式 "
                              "（HJ Z0/εeff 单源）≤5%（adapter 既有锚门）"},
        },
        "case_b_tgv": {
            "kind": "tgv_coax",
            "spec": TGV_SPEC,
            "return_path": "coaxial pec shield r=3r_via（与内核 "
                           "tgv_line_network r_shield 口径逐字对齐）",
            "expected": {
                "l_total_nh": l_total_nh,
                "c_total_ff": c_total_ff,
                "z0_coax_ohm": tgv["z0_coax_ohm"],
            },
            "gate": {
                "l_band_nh": list(TGV_L_BAND_NH),
                "c_band_ff": list(TGV_C_BAND_FF),
                "z0_identity_tol": TGV_Z0_IDENTITY_TOL,
                "basis": "文献带端点 ±30%（lit 表行 3 同带）+z0 同轴闭式 "
                         "恒等 ≤1%",
            },
        },
    }


def build_verdict(extracted: dict[str, Any] | None,
                  expected: dict[str, Any]) -> dict[str, Any]:
    """判读器（纯函数）：Q3D 提取值 vs 闭式期望 → 逐行 verdict。

    extracted=None 或缺行 → INCONCLUSIVE（如实不伪造，#122/#316 方向：
    宁多报不放过）；越带 → FAIL；带内 → PASS。
    """
    rows: list[dict[str, Any]] = []

    def _row(name: str, value: float | None, lo: float, hi: float,
             basis: str) -> None:
        if value is None:
            rows.append({"name": name, "value": None, "band": [lo, hi],
                         "verdict": "INCONCLUSIVE", "basis": basis})
        elif lo <= value <= hi:
            rows.append({"name": name, "value": value, "band": [lo, hi],
                         "verdict": "PASS", "basis": basis})
        else:
            rows.append({"name": name, "value": value, "band": [lo, hi],
                         "verdict": "FAIL", "basis": basis})

    exp_a = expected["case_a_rdl"]
    gate_a = exp_a["gate"]["tolerance"]
    ext_a = (extracted or {}).get("case_a_rdl") or {}
    # 键面=interconnect_rlc_anchor 原生键（l_nh_per_mm/c_pf_per_mm/z0_ohm）；
    # expected 缺键=脚本缺陷，显式 INCONCLUSIVE 行不静默跳过（#331 族：
    # 审计工具不得自造标签/丢行）
    for key, band_basis in (("l_nh_per_mm", "L/长度"),
                            ("c_pf_per_mm", "C/长度"),
                            ("z0_ohm", "z0")):
        exp_val = (exp_a["expected"] or {}).get(key)
        got = ext_a.get(key)
        if exp_val is None:
            rows.append({"name": f"case_a.{key}", "value": got,
                         "band": None, "verdict": "INCONCLUSIVE",
                         "basis": "expected 缺键（脚本缺陷，须修发射面）"})
            continue
        _row(f"case_a.{key}", got,
             exp_val * (1.0 - gate_a), exp_val * (1.0 + gate_a),
             f"{band_basis} vs {exp_a['gate']['basis']}")

    exp_b = expected["case_b_tgv"]["expected"]
    gate_b = expected["case_b_tgv"]["gate"]
    ext_b = (extracted or {}).get("case_b_tgv") or {}
    _row("case_b.l_total_nh", ext_b.get("l_total_nh"),
         gate_b["l_band_nh"][0], gate_b["l_band_nh"][1], "L 文献带 ±30%")
    _row("case_b.c_total_ff", ext_b.get("c_total_ff"),
         gate_b["c_band_ff"][0], gate_b["c_band_ff"][1], "C 文献带 ±30%")
    z0 = ext_b.get("z0_coax_ohm")
    _row("case_b.z0_coax_ohm", z0,
         exp_b["z0_coax_ohm"] * (1.0 - gate_b["z0_identity_tol"]),
         exp_b["z0_coax_ohm"] * (1.0 + gate_b["z0_identity_tol"]),
         "同轴闭式恒等")

    n_pass = sum(1 for r in rows if r["verdict"] == "PASS")
    n_fail = sum(1 for r in rows if r["verdict"] == "FAIL")
    overall = ("INCONCLUSIVE" if any(r["verdict"] == "INCONCLUSIVE"
                                     for r in rows)
               else ("PASS" if n_fail == 0 else "FAIL"))
    return {"rows": rows, "n_pass": n_pass, "n_fail": n_fail,
            "verdict": overall}


def _extract_from_result(field_data: dict[str, Any] | None,
                         spec_a: dict[str, float],
                         spec_b: dict[str, float]) -> dict[str, Any] | None:
    """真机提取值 → 判读器输入形态（每长度归一；导出失败给 None 面）。

    field_data 契约（发射体填装时按此键）：case_a_rdl={l_total_nh,
    c_total_pf, z0_ohm}（Q3D 矩阵对角总计，导出单位 l=nH/c=pF），
    case_b_tgv={l_total_nh, c_total_ff}；本函数只做每长度归一（除以
    长度）与 z0=√(L/C) 换算，不做其他物理换算（铁律 7：数值全数来自
    内核与导出解析器）。
    """
    if not field_data:
        return None
    extracted: dict[str, Any] = {}
    raw_a = field_data.get("case_a_rdl") or {}
    if raw_a:
        length_mm = spec_a["trace_len_mm"]
        l_total = raw_a.get("l_total_nh")
        c_total = raw_a.get("c_total_pf")
        extracted["case_a_rdl"] = {
            "l_nh_per_mm": (l_total / length_mm
                            if l_total is not None else None),
            "c_pf_per_mm": (c_total / length_mm
                            if c_total is not None else None),
            "z0_ohm": raw_a.get("z0_ohm"),
        }
    raw_b = field_data.get("case_b_tgv") or {}
    if raw_b:
        l_nh = raw_b.get("l_total_nh")
        c_ff = raw_b.get("c_total_ff")
        z0 = (math.sqrt(l_nh * 1e-9 / (c_ff * 1e-15))
              if l_nh and c_ff else None)
        extracted["case_b_tgv"] = {
            "l_total_nh": l_nh,
            "c_total_ff": c_ff,
            "z0_coax_ohm": z0,
        }
    return extracted or None


def run_real() -> dict[str, Any]:
    """真发射路径（SP1 复进条件满足后执行；本批不调用）。

    case A 走 q3d_adapter 既有链（connect→build_geometry→solve→导出解析）；
    case B 的同轴建模需 pyaedt create_cylinder（仓内未实证面，首发射
    先 shake-down，失败 success=False 落盘 INCONCLUSIVE 不伪造）。
    """
    raise RuntimeError(
        "真发射未开放：AEDT SP1 前置未满足（本机与服务器均无 SP1，"
        "矩阵导出族全失败的证据在 runs/wp44b_q3d/）；装 SP1 后按本函数 "
        "docstring 与模块头协议实现发射体并单独评审——本批只交付发射面准备")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PK-1 金标准 Q3D 对拍发射面（--dry-run=离线验证，"
                    "缺省=真发射路径〔当前显式拒绝，SP1 前置未满足〕）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只算闭式期望+判读器自检，不触 AEDT")
    args = parser.parse_args()
    WORKDIR.mkdir(parents=True, exist_ok=True)

    expected = expected_values()
    # 判读器自检（离线）：内核期望值本身必须全 PASS（闭式对闭式恒等面）
    self_extract = {
        "case_a_rdl": expected["case_a_rdl"]["expected"],
        "case_b_tgv": {
            **expected["case_b_tgv"]["expected"],
            "z0_coax_ohm": expected["case_b_tgv"]["expected"]["z0_coax_ohm"],
        },
    }
    self_verdict = build_verdict(self_extract, expected)
    out = {
        "mode": "dry-run" if args.dry_run else "real",
        "expected": expected,
        "self_verdict": self_verdict,
        "env_precondition": (
            "BLOCKED-ENV(SP1)：本机/服务器 AEDT 均无 SP1，矩阵导出族失败"
            "（runs/wp44b_q3d/ 证据）；复进=目标机装 SP1 后真发射"),
    }
    if not args.dry_run:
        # 真发射显式拒绝（本批协议）：不触 AEDT、不伪造结果
        out["launch"] = {"status": "REFUSED",
                         "reason": run_real.__doc__}
    payload = json.dumps(out, ensure_ascii=False, indent=2)
    (DRYRUN_JSON if args.dry_run else RESULT_JSON).write_text(
        payload, encoding="utf-8")
    print(payload)
    return 0 if self_verdict["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
