"""HFSS 窗 B→A 仲裁 · 8 席执行编排驱动（wf:hfss-window-driver；零真机交付）。

把 runs/hfss_window_b2a/ 8 席预声明判据（criteria.md，#122 判据先行）变成
可执行编排：连会话（machine 参数化）→ 建模（criteria §2 逐席方案）→ 断链
审计（#336）→ ΔS 三档收敛阶梯（#335）→ Touchstone 导出（#309 命名口径）→
G11 健康门（#314 掩码）→ 仲裁判读（#350 四态预声明）→ verdict json/md 落盘。
本脚本交付时**零求解零发射**——真机发射由主代理择机（双触发：服务器许可
换发 或 本机 openEMS 队列空+HFSS 插队）。

用法（工作区根目录）::

    .venv/Scripts/python.exe scripts/hfss_window_arbitration.py --list
    .venv/Scripts/python.exe scripts/hfss_window_arbitration.py --seat wilkinson --dry-run
    .venv/Scripts/python.exe scripts/hfss_window_arbitration.py --seat wilkinson --machine local
    .venv/Scripts/python.exe scripts/hfss_window_arbitration.py --all --machine sim_host
    .venv/Scripts/python.exe scripts/hfss_window_arbitration.py --all --machine sim_host \
        --parallel 3 --port-base 50051        # 波内 3 席并行（wf:hfss-window-parallel）
    .venv/Scripts/python.exe scripts/hfss_window_arbitration.py --all --remote sim_host \
        --parallel 4                          # v1 调度面：--remote 路由（license 预检
                                              # fail-closed+hfss.max_parallel 闸缺省 2）

退出码：0=席位执行完成且仲裁态 ∈ {AGREE_JUDGE, AGREE_OPENEMS, AGREE_HFSS,
DISAGREE}（DISAGREE 是裁决数据不是执行失败，#225 口径）；1=执行 FAIL
（异常/不可判读，fail-closed）；2=SKIP（被阻塞：许可/license 预检未过/
进程残留/实现待续）。

完成度（交付时）：stepped_impedance / coupled_line / wilkinson /
marchand_balun 四席全量建模链（wf:hfss-window-driver）；gysel /
branchline / patch_array_1x4 / patch_array_2x2 四席建模由补批
wf:hfss-window-builders2（2026-09-28）补全——8/8 builder=full（`--list`
核对），skeleton→NotImplementedError 防线保留（SEATS 显式改回 skeleton
即复效，fail-closed 测试钉在案）。

判读纯函数（提取/门判定/阶梯采信/G11/断链审计/OE 参考解析）全部离线可测，
不 import pyaedt（先例 tests/unit/test_hfss_marchand_anchor.py 同制度）。

OE 参考值单一事实源（发射前置已补齐，oe_nominal_README.md 2026-09-28/29）：
- wilkinson          → runs/hfss_window_b2a/wilkinson/oe_nominal/sparams.csv
- coupled_line       → …/coupled_line/oe_nominal_wideband/sparams.csv（仲裁档）
- stepped_impedance  → …/stepped_impedance/oe_nominal_wideband/sparams.csv（仲裁档）
- branchline         → runs/branchline_real_anchor/branchline.s4p
- gysel              → runs/gysel_miter_ab/verdict.json variants.off.judged
- marchand_balun     → runs/smoke_marchand_2sect/verdict.json + sameport_arb（常量钉）
- patch_array_1x4/2x2 → runs/ge_fd/<t>/（归档 CSV，常量钉，README 读档实测）
缺口席（前 3 席）产物缺失时回退闭式半集 + verdict 封顶 AGREE_HFSS（criteria §1b）。

判读口径实现注记（如实，随 verdict.implementation_notes 落档）：
- marchand §2 预声明"主判=2 模端口 S 反演"——平衡侧两端子分居主线 ±y
  （非耦合对，x=结平面整截面切口含贯通主线共 3 导体），2 模端口无位可落；
  本实现按其"端接口径"（P2/P3=140Ω 集总，与 OE smoke 同端口同几何，
  #同源渲染）落地；f_null 主门依赖 P1 反射但 S11 经场耦合亦受平衡侧负载
  影响，端口口径对谷位的影响未单变量实证——对比有效性依据=两引擎同端口
  同几何同源渲染（同口径对比），非「端口口径无影响」（P2-2 措辞修正）。
- marchand §2"不设辐射边界（锚 A 先例）"与被引锚 A/B/hairpin-A-driven 实码
  （辐射开放面）矛盾——本实现跟随被引先例实码（ASSIGN_RADIATION=True，
  单开关可翻转按 criteria 字面执行）。
- gysel S32 band_max 的 OE 数字 −22.48dB 实际产自判读带 2.25–2.75（README
  §4 表标注"2.0–3.0 内"与产物 provenance 不符）——HFSS 侧按产物实际带取
  同口径。
- coupled_line 相邻双线端口片（中心距 w+gap=1.5mm）在 4w 惯例宽度下重叠
  ——端口宽取 w+gap−0.05mm（不重叠约束下最大可行宽，criteria §2 实现
  细节增补；#191 余量依赖积分线+高度，Round 记录可复核）。

S2 审计 lesson 回写（2026-09-29，docs/audit/hfss_window_disagree_audit_
20260929.md §3/§5/§8.3，机制面零已落档 verdict/锚改动）：
- lesson-1 带窗对称化：band 统计量门**双侧同带**强制（band_symmetry_
  violations/assert_band_symmetry）——外部常量型 OE 参考（constants/
  verdict_fields）必须声明 ``oe["band_ghz"]`` 且与带统计量提取器显式带
  逐位一致，违例 run_seat 起跑前 fail-closed（本窗 marchand OE smoke 带
  [2.25,2.75] vs HFSS 全窗 [1.8,3.6] 直接对差=口径缺口实证）；
- lesson-2 病态背景弱特征不设门：``weak_feature`` 门（marchand f_null
  首用）在定位口带内最优匹配劣于 −3dB（|Γ|>0.7 近全反射背景）时降级
  info——观测分歧照实记录、不翻总态（本窗 f_null 跨 build 漂移 +45% 的
  病态性实证）；
- lesson-3 argmin 双谷口径：s_db_min_f 定位量随 ``<metric>_valleys``
  谷位图+深度矩阵结构化出口（valley_map/valley_map_compare）——patch_2x2
  实证谷位一致 ≤0.3% 而 f_min 分歧 14.3% 实为谷深排序翻转，单值 f_*
  语义丢失谷位图；
- marchand 可选端口形态（S2 决策 2 发射面）：``port_form``（lumped140
  缺省=已落档行为零变化 / wave2mode=平衡侧 2 模大截面波端口，判据分派
  criteria_for_run、导出 Σ模数 .s5p、产物目录 hfss_side_wave2mode 隔离；
  平衡量经 2 模反演离线判读消费 run*.s5p 归档——本批只备发射面不发射）。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

OUT_ROOT = REPO / "runs" / "hfss_window_b2a"
B2A_ROOT_ON_SERVER = "hfss_window_b2a"      # 服务器侧 project_root 下的相对段
HFSS_VERSION = "2025.1"                     # 与 v251 配对
SOLVE_TIMEOUT_S_DEFAULT = 3600.0            # watchdog（criteria §6 单结构 3600s）


def _solve_timeout_from_env() -> float:
    """HFSS 单解 watchdog 超时 env 口（patch_2x2 rung3 结构性超 3600s 恢复通道）。

    优先级：env ``RFAUTO_HFSS_SOLVE_TIMEOUT_S`` > 缺省 3600s（照
    RFAUTO_HPEESOF_DIR/RFAUTO_XYCE_EXE 先例；同名 env 全仓已有约定——
    hfss_adapter.solve、infra/env_vars knob、slotline/ratrace/helix
    arbitration 同款）。非法值（非数字/非有限正数）回缺省不炸；
    env 不设时行为与原常量逐字节一致（判据冻结不放宽，仅恢复通道）。
    """
    raw = os.environ.get("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "").strip()
    if not raw:
        return SOLVE_TIMEOUT_S_DEFAULT
    try:
        value = float(raw)
    except ValueError:
        return SOLVE_TIMEOUT_S_DEFAULT
    if not math.isfinite(value) or value <= 0:
        return SOLVE_TIMEOUT_S_DEFAULT
    return value


SOLVE_TIMEOUT_S = _solve_timeout_from_env()
PAD_MM = 0.02                               # #310④/#336 面积重叠垫
BOARD_MM = 60.0                             # TL 席板半宽（引擎 BOARD 同源）
AIR_TOP_MM = 5.0                            # wilkinson §2 空气顶 ≥5mm
MARCHAND_AIR_TOP_MM = 15.0                  # 锚 B 同款顶垫
MARCHAND_FEED_LEN_MM = 4.0                  # 锚 B B_FEED_LEN_MM（平衡臂馈线）
MARCHAND_PAD_MM = 12.0                      # 锚 B B_PAD_MM（四周垫）
MARCHAND_SUB_MARGIN_MM = 3.0                # 锚 B B_SUB_MARGIN_MM
PORT_SPLIT_MARGIN_MM = 0.05                 # 相邻端口片间隙（coupled_line）
C0 = 299792458.0
DB_FLOOR = 1e-12

# ── S2 审计 lesson 回写常量（docs/audit/hfss_window_disagree_audit_20260929.md）──
WEAK_FEATURE_BG_FLOOR_DB = -3.0   # lesson-2：定位口带内最优匹配劣于此值
                                  # （|Γ|>0.7 近全反射背景）→ 弱特征病态降级 info
BAND_STAT_KINDS = ("s_db_band_min", "s_db_band_max", "imb_band_max")
                                  # lesson-1：带统计量提取器种类（双侧同带强制对象）
OE_CONST_SOURCES = ("constants", "verdict_fields")
                                  # lesson-1：外部常量型 OE 参考（不经本驱动
                                  # 同带提取，同带性必须显式声明可核验）
# marchand 可选端口形态（S2 决策 2 发射面；缺省 lumped140=已落档行为零变化）：
MARCHAND_PORT_FORMS = ("lumped140", "wave2mode")
MARCHAND_W2M_LATERAL_MM = 12.0    # wave2mode 大截面横向 ±12mm（锚 A 同款，
                                  # marchand criteria §2 预声明）

# 并行发射（wf:hfss-window-parallel）：远程 grpcsrv 端口基址（与注册表
# DEFAULT_GRPC_PORT 同源；--parallel N>1 时席位按波内下标分 base+0..N-1，
# 波次复用；--port-base 可覆盖）。
DEFAULT_GRPC_PORT_BASE = 50051


# criteria §2 与被引锚实码矛盾时的开关（见模块 docstring 判读口径注记；
# 翻 False = 按 criteria 字面"不设辐射边界"执行，域侧壁缺省 PEC）。
ASSIGN_RADIATION = True

# 四态判读（#350/wilkinson §4 预声明；严重度序=总态取最差）
_STATE_RANK = {"AGREE_JUDGE": 0, "AGREE_OPENEMS": 1, "AGREE_HFSS": 2,
               "DISAGREE": 3}
_OK_VERDICTS = ("AGREE_JUDGE", "AGREE_OPENEMS", "AGREE_HFSS", "DISAGREE")

Rect = tuple[float, float, float, float]   # (x0, y0, x1, y1) mm


# ═════════════════════ 8 席 spec（criteria × 7 节结构化；§1-§7 一席不缺）════════════════════
# 每席键：order（README 发射序）/ template/f0_ghz/n_ports（§1）/ window_ghz+
# n_points+ladder+ladder_scalars（§3）/ gates+x_ref（§4）/ g11（§5）/
# budget_min（§6）/ builder+builder_status（§2 实现面）/ oe（§1 OE 参考源）/
# anchor（§7 锚注册方案）。判据发射后不改：门值/窗/预算改动=返工。
SEATS: dict[str, dict[str, Any]] = {
    # ── 发射序 1（最短预算+链路冒烟席）──
    "stepped_impedance": {
        "order": 1,
        "template": "stepped_impedance",
        "f0_ghz": 2.4,
        "n_ports": 2,
        "window_ghz": (1.5, 3.5),
        "n_points": 401,
        "ladder": ((0.02, 12), (0.01, 20), (0.005, 30)),
        "budget_min": 30,
        "builder": "stepped_impedance",
        "ladder_scalars": ("s21_at_f0_db", "f_dip_ghz", "s11_min_db"),
        "extractors": (
            {"metric": "s21_at_f0_db", "kind": "s_db_at_f", "ij": (1, 0), "f_ghz": 2.4},
            {"metric": "f_dip_ghz", "kind": "s_db_min_f", "ij": (0, 0), "band": "window"},
            {"metric": "s11_min_db", "kind": "s_db_min_v", "ij": (0, 0), "band": "window"},
            {"metric": "bw_3db_ghz", "kind": "bw3db", "ij": (1, 0), "band": "window"},
        ),
        "gates": (
            {"metric": "s21_at_f0_db", "gate": 0.5, "gate_kind": "db_diff", "key": True},
            {"metric": "f_dip_ghz", "gate": 3.0, "gate_kind": "rel_pct", "key": True},
            {"metric": "bw_3db_ghz", "gate": 20.0, "gate_kind": "rel_pct", "key": True},
        ),
        "g11": {"passive_le": 1.05, "recip_le": 1e-3},
        "oe": {
            "source": "sparams_csv",
            "candidates": (
                "runs/hfss_window_b2a/stepped_impedance/oe_nominal_wideband/sparams.csv",
                "runs/hfss_window_b2a/stepped_impedance/oe_nominal/sparams.csv",
            ),
            "fallback": "closed_form:stepped_cascade",
            "provenance": "runs/hfss_window_b2a/stepped_impedance/"
                          "oe_nominal_wideband（verdict.json 2026-09-29；README "
                          "仲裁消费建议 wideband 档；bw_3db 语义=review-slice11 "
                          "P1-1 主瓣口径：OE ≥−3dB 段 [1.595,3.5] 触上窗沿截断"
                          "→如实 UNKNOWN，旧档 1.905=截断下界不可比）",
        },
        "anchor": "stepped_impedance.f_pass.openems-hfss-v1（kind=constant，"
                  "quantity=|S11| 谷位相对偏差 %，domain=seg_len 3–8mm/n_segments "
                  "3–7，fallback=closed_form 段级联；DISAGREE 改 pointer 锚）",
    },
    # ── 发射序 2 ──
    "coupled_line": {
        "order": 2,
        "template": "coupled_line",
        "f0_ghz": 2.4,
        "n_ports": 3,
        "window_ghz": (1.8, 3.0),
        "n_points": 401,
        "ladder": ((0.02, 12), (0.01, 20), (0.005, 30)),
        "budget_min": 30,
        "builder": "coupled_line",
        "ladder_scalars": ("f_peak_ghz", "coupling_at_f0_db", "through_at_f0_db"),
        "extractors": (
            {"metric": "coupling_at_f0_db", "kind": "s_db_at_f", "ij": (2, 0),
             "f_ghz": 2.4},
            # review-slice11 P1-2（#298 口径）：argmax 峰位是峰平台化歧义量
            # （双侧 −3dB 带上沿触窗 censored）——f_peak 报告口径改 −3dB 带心；
            # 判据语义变更已注记 runs/hfss_window_b2a/coupled_line/criteria.md
            # §8（门值/窗不变）。
            {"metric": "f_peak_ghz", "kind": "s_db_max_f_center3db", "ij": (2, 0),
             "band": "window"},
            {"metric": "coupling_peak_db", "kind": "s_db_max_v", "ij": (2, 0),
             "band": "window"},
            {"metric": "through_at_f0_db", "kind": "s_db_at_f", "ij": (1, 0),
             "f_ghz": 2.4},
        ),
        "gates": (
            {"metric": "coupling_at_f0_db", "gate": 0.5, "gate_kind": "db_diff",
             "key": True},
            {"metric": "f_peak_ghz", "gate": 3.0, "gate_kind": "rel_pct", "key": True,
             "x_ref": "closed_form:coupled_quarter_wave"},
            {"metric": "through_at_f0_db", "gate": 0.5, "gate_kind": "db_diff",
             "key": True},
        ),
        "g11": {"passive_le": 1.05, "recip_le": 1e-3},
        "oe": {
            "source": "sparams_csv",
            "candidates": (
                "runs/hfss_window_b2a/coupled_line/oe_nominal_wideband/sparams.csv",
                "runs/hfss_window_b2a/coupled_line/oe_nominal/sparams.csv",
            ),
            "fallback": "closed_form:coupled_quarter_wave",
            "provenance": "runs/hfss_window_b2a/coupled_line/oe_nominal_wideband"
                          "（verdict.json 2026-09-29；f_peak 口径=review-slice11 "
                          "P1-2 峰 −3dB 带心（#298）：wideband 档峰 2.955 仍触上"
                          "窗沿（3.0 处仅降 0.012dB，−3dB 带上沿截断 censored），"
                          "旧「宽带档确认真峰在窗内」断言失实已改正）",
        },
        "anchor": "coupled_line.s31_coupling.openems-hfss-v1（kind=constant，"
                  "quantity=耦合度相对偏差 dB，domain=gap 0.3–2mm/coupled_len "
                  "15–25mm，fallback=closed_form even/odd C；DISAGREE 改 pointer 锚）",
    },
    # ── 发射序 3 ──
    "wilkinson": {
        "order": 3,
        "template": "wilkinson",
        "f0_ghz": 2.5,
        "n_ports": 3,
        "window_ghz": (2.0, 3.0),
        "n_points": 401,
        "ladder": ((0.02, 12), (0.01, 20), (0.005, 30)),
        "budget_min": 45,
        "builder": "wilkinson",
        "ladder_scalars": ("f_match_ghz", "s21_at_match_db", "s23_band_max_db"),
        "extractors": (
            {"metric": "f_match_ghz", "kind": "s_db_min_f", "ij": (0, 0), "band": "window"},
            {"metric": "s11_min_db", "kind": "s_db_min_v", "ij": (0, 0), "band": "window"},
            {"metric": "s21_at_match_db", "kind": "s_db_at_ref", "ij": (1, 0),
             "ref": "f_match_ghz"},
            {"metric": "s31_at_match_db", "kind": "s_db_at_ref", "ij": (2, 0),
             "ref": "f_match_ghz"},
            {"metric": "split_db", "kind": "diff_at_ref", "ij1": (1, 0), "ij2": (2, 0),
             "ref": "f_match_ghz"},
            {"metric": "s23_band_max_db", "kind": "s_db_band_max", "ij": (1, 2),
             "band": "window"},
        ),
        "gates": (
            {"metric": "f_match_ghz", "gate": 3.0, "gate_kind": "rel_pct", "key": True,
             "x_ref": (2.375, 2.625)},
            {"metric": "split_db", "gate": 0.3, "gate_kind": "db_diff", "key": True},
            {"metric": "s21_at_match_db", "gate": 0.5, "gate_kind": "db_diff",
             "key": True, "x_ref": (-3.5, -2.5)},
            {"metric": "s23_band_max_db", "gate": 5.0, "gate_kind": "db_diff",
             "key": True, "x_ref": ("le", -15.0)},
            {"metric": "s11_min_db", "gate": 5.0, "gate_kind": "db_diff", "key": True},
        ),
        "g11": {"passive_le": 1.05, "recip_le": 1e-3},
        "oe": {
            "source": "sparams_csv",
            "candidates": ("runs/hfss_window_b2a/wilkinson/oe_nominal/sparams.csv",),
            "fallback": "closed_form:wilkinson_hj",
            "provenance": "runs/hfss_window_b2a/wilkinson/oe_nominal（verdict.json "
                          "2026-09-28；带 2.0–3.0 与 §3 窗同栅；S23 第二激励 footer）",
        },
        "anchor": "wilkinson.f_match.openems-hfss-v1（kind=constant，quantity="
                  "f_match 相对偏差 %，domain=arm_len 15–25mm，fallback=closed_form；"
                  "DISAGREE 改 wilkinson.disagreement.openems-hfss-v1 pointer 锚）",
    },
    # ── 发射序 4（最高风险席，预声明 DISAGREE 概率高）──
    "marchand_balun": {
        "order": 4,
        "template": "marchand_balun",
        "f0_ghz": 2.5,
        "n_ports": 3,
        "window_ghz": (1.8, 3.6),
        "n_points": 401,
        "ladder": ((0.02, 12), (0.01, 20), (0.005, 30)),
        "budget_min": 60,
        "builder": "marchand_balun",
        # 可选端口形态（S2 决策 2 发射面）：lumped140=已落档 140Ω 集总 build
        # （缺省，行为零变化）；wave2mode=平衡侧 2 模大截面波端口单变量对照
        # （criteria_for_run 判据分派；发射参数见 --marchand-port-form）。
        "port_form": "lumped140",
        "ladder_scalars": ("f_null_ghz", "s21_band_min_db", "imbalance_band_max_db"),
        "extractors": (
            # lesson-2（S2 审计 §3.2(b)）：f_null 在近全反射背景上是病态弱
            # 特征量（本窗 HFSS s11_min 仅 −1.28dB、跨 build 谷位漂移 +45%）
            # ——weak_feature 门：带内最优匹配劣于 −3dB 时降级 info 不翻
            # 总态（弱特征门定义面；观测分歧照实记录）。
            {"metric": "f_null_ghz", "kind": "s_db_min_f", "ij": (0, 0), "band": "window"},
            {"metric": "s11_min_db", "kind": "s_db_min_v", "ij": (0, 0), "band": "window"},
            {"metric": "s21_band_min_db", "kind": "s_db_band_min", "ij": (1, 0),
             "band": (2.25, 2.75)},
            {"metric": "s31_band_min_db", "kind": "s_db_band_min", "ij": (2, 0),
             "band": (2.25, 2.75)},
            {"metric": "imbalance_band_max_db", "kind": "imb_band_max",
             "ij1": (1, 0), "ij2": (2, 0), "band": (2.25, 2.75)},
            {"metric": "phase_diff_at_f_null_deg", "kind": "phase_diff_at_ref",
             "ij1": (1, 0), "ij2": (2, 0), "ref": "f_null_ghz"},
        ),
        "gates": (
            {"metric": "f_null_ghz", "gate": 10.0, "gate_kind": "rel_pct", "key": True,
             "weak_feature": True},
            {"metric": "s21_band_min_db", "gate": 1.0, "gate_kind": "db_diff",
             "key": True},
            {"metric": "s31_band_min_db", "gate": 1.0, "gate_kind": "db_diff",
             "key": True},
            {"metric": "imbalance_band_max_db", "gate": 0.5, "gate_kind": "db_diff",
             "key": True},
            {"metric": "phase_diff_at_f_null_deg", "gate": 10.0, "gate_kind": "abs_diff",
             "key": False},
        ),
        "g11": {"passive_le": 1.05, "recip_le": 1e-3},
        "oe": {
            "source": "constants",
            "constants": {
                "f_null_ghz": 3.272,
                "s21_band_min_db": -6.44,
                "s31_band_min_db": -5.35,
                "imbalance_band_max_db": 1.085,
            },
            # lesson-1 同带强制：OE 常量产自判读带 2.25–2.75（smoke/sameport
            # 判读带），必须显式声明并与带统计量提取器带逐位一致（不一致=
            # run_seat fail-closed）。
            "band_ghz": (2.25, 2.75),
            "provenance": "runs/smoke_marchand_2sect/verdict.json（幅度三量，判读带 "
                          "2.25–2.75）+ runs/marchand_sameport_arb/arbverdict.json"
                          "（f_null 3.272GHz 驻波免疫估计器主判）；预声明 DISAGREE "
                          "概率高，BALUN_GATES 记录不判",
        },
        "anchor": "预期 DISAGREE 路径：marchand.f_null.openems-hfss-v1（kind=pointer，"
                  "quantity=整器件 S11 谷位两引擎分歧，value=双值 {openems, hfss}，"
                  "fallback=none，status=experimental）；意外 AGREE 改常量锚",
    },
    # ── 发射序 5（建模全量，2026-09-28 补批 wf:hfss-window-builders2）──
    "gysel": {
        "order": 5,
        "template": "gysel",
        "f0_ghz": 2.5,
        "n_ports": 3,
        "window_ghz": (2.0, 3.0),
        "n_points": 401,
        "ladder": ((0.02, 12), (0.01, 20), (0.005, 30)),
        "budget_min": 60,
        "builder": "gysel",
        "ladder_scalars": ("s21_at_f0_db", "s32_band_max_db", "s11_at_f0_db"),
        "extractors": (
            {"metric": "s21_at_f0_db", "kind": "s_db_at_f", "ij": (1, 0), "f_ghz": 2.5},
            {"metric": "s31_at_f0_db", "kind": "s_db_at_f", "ij": (2, 0), "f_ghz": 2.5},
            {"metric": "split_at_f0_db", "kind": "diff_at_f", "ij1": (1, 0),
             "ij2": (2, 0), "f_ghz": 2.5},
            {"metric": "s32_band_max_db", "kind": "s_db_band_max", "ij": (2, 1),
             "band": (2.25, 2.75)},
            {"metric": "s32_at_f0_db", "kind": "s_db_at_f", "ij": (2, 1), "f_ghz": 2.5},
            {"metric": "s11_at_f0_db", "kind": "s_db_at_f", "ij": (0, 0), "f_ghz": 2.5},
        ),
        "gates": (
            {"metric": "s21_at_f0_db", "gate": 0.5, "gate_kind": "db_diff", "key": True,
             "x_ref": (-3.5, -2.5)},
            {"metric": "split_at_f0_db", "gate": 0.3, "gate_kind": "db_diff",
             "key": True},
            {"metric": "s32_band_max_db", "gate": 5.0, "gate_kind": "db_diff",
             "key": True},
            {"metric": "s11_at_f0_db", "gate": 5.0, "gate_kind": "db_diff",
             "key": True},
            {"metric": "s32_at_f0_db", "gate": 5.0, "gate_kind": "db_diff",
             "key": False, "x_ref": ("le", -20.0)},
        ),
        "g11": {"passive_le": 1.05, "recip_le": 1e-3},
        "oe": {
            "source": "verdict_fields",
            "path": "runs/gysel_miter_ab/verdict.json",
            "fields": {
                "s21_at_f0_db": "variants.off.judged.at_f0.s21_db",
                "split_at_f0_db": "variants.off.judged.at_f0.split_diff_db",
                "s32_band_max_db": "variants.off.judged.iso.band_max_db",
                "s32_at_f0_db": "variants.off.judged.at_f0.s32_db",
                "s11_at_f0_db": "variants.off.judged.at_f0.s11_db",
            },
            "fallback": {"s21_at_f0_db": -3.221, "split_at_f0_db": 0.0,
                         "s32_band_max_db": -22.48, "s11_at_f0_db": -24.99},
            # lesson-1 同带强制：verdict_fields 常量产自判读带 2.25–2.75（README
            # §4 标注 2.0–3.0 与产物 provenance 不符，按产物实际带），显式声明
            # 与 s32_band_max 提取器带一致。
            "band_ghz": (2.25, 2.75),
            "provenance": "runs/gysel_miter_ab/verdict.json variants.off.judged"
                          "（名义无切角 off 臂=名义设计，2026-09-27）；S32 band_max"
                          " 产物带 2.25–2.75（README §4 标注 2.0–3.0 与产物不符，"
                          "按产物实际带取同口径，如实注记）；β=88.913 rad/m 信息项",
        },
        "anchor": "gysel.s32_iso.openems-hfss-v1（kind=constant，quantity=S32 "
                  "band_max 相对偏差 dB，domain=arm_len 15–22mm，fallback=closed_form "
                  "理想环闭式；β 信息项 ≤2% 时 provenance 附记双引擎 β 互证；"
                  "DISAGREE 改 pointer 锚）",
    },
    # ── 发射序 6（建模全量，2026-09-28 补批）──
    "branchline": {
        "order": 6,
        "template": "branchline",
        "f0_ghz": 2.4,
        "n_ports": 4,
        "window_ghz": (1.8, 2.8),
        "n_points": 401,
        "ladder": ((0.02, 12), (0.01, 20), (0.005, 30)),
        "budget_min": 60,
        "builder": "branchline",
        "ladder_scalars": ("f_match_ghz", "split_db", "s41_band_max_db"),
        "extractors": (
            {"metric": "f_match_ghz", "kind": "s_db_min_f", "ij": (0, 0), "band": "window"},
            {"metric": "s11_min_db", "kind": "s_db_min_v", "ij": (0, 0), "band": "window"},
            {"metric": "amp_mid_db", "kind": "mean_amp_at_ref", "ij1": (1, 0),
             "ij2": (2, 0), "ref": "f_match_ghz"},
            {"metric": "split_db", "kind": "diff_at_ref", "ij1": (1, 0), "ij2": (2, 0),
             "ref": "f_match_ghz"},
            {"metric": "s41_band_max_db", "kind": "s_db_band_max", "ij": (3, 0),
             "band": "window"},
        ),
        "gates": (
            {"metric": "f_match_ghz", "gate": 3.0, "gate_kind": "rel_pct", "key": True,
             "x_ref": (2.28, 2.52)},
            {"metric": "split_db", "gate": 0.3, "gate_kind": "db_diff", "key": True},
            {"metric": "amp_mid_db", "gate": 0.5, "gate_kind": "db_diff", "key": True,
             "x_ref": (-3.5, -2.5)},
            {"metric": "s41_band_max_db", "gate": 5.0, "gate_kind": "db_diff",
             "key": True},
            {"metric": "s11_min_db", "gate": 5.0, "gate_kind": "db_diff", "key": True},
        ),
        "g11": {"passive_le": 1.05, "recip_le": 1e-3},
        "oe": {
            "source": "touchstone",
            "candidates": ("runs/branchline_real_anchor/branchline.s4p",),
            "fallback": {"f_match_ghz": 2.136, "split_db": 0.054,
                         "amp_mid_db": -3.192, "s41_band_max_db": -40.41,
                         "s11_min_db": -48.78},
            "fallback_note": "s4p 缺失时常量回退（criteria §4 预声明值）；"
                             "s41_band_max 以 @f_match −40.41 代带内包络（归档仅 "
                             "at_match 值），如实注记",
            "provenance": "runs/branchline_real_anchor/branchline.s4p + "
                          "verdict_nominal.json（f_match 2.136/−48.78/−3.219/−3.165/"
                          "−40.41dB、split 0.054dB）；名义 −10.78% 分解账在案（#252），"
                          "主判=同几何引擎对不判 vs 设计 2.4GHz",
        },
        "anchor": "branchline.f_match.openems-hfss-v1（kind=constant，quantity=引擎间 "
                  "f_match 相对偏差 %，domain=arm_len 17–21mm，fallback=closed_form；"
                  "decomposition 结论随 provenance 引用不重写；DISAGREE 改 pointer 锚）",
    },
    # ── 发射序 7（建模全量，2026-09-28 补批；辐射族首席）──
    "patch_array_1x4": {
        "order": 7,
        "template": "patch_array_1x4",
        "f0_ghz": 5.8,
        "n_ports": 1,
        "window_ghz": (4.64, 6.96),
        "n_points": 401,
        "ladder": ((0.02, 12), (0.01, 20), (0.005, 30)),
        "budget_min": 90,
        "builder": "patch_array_1x4",
        "ladder_scalars": ("f_min_ghz", "s11_min_db", "s11_at_5p8_db"),
        "extractors": (
            {"metric": "f_min_ghz", "kind": "s_db_min_f", "ij": (0, 0), "band": "window"},
            {"metric": "s11_min_db", "kind": "s_db_min_v", "ij": (0, 0), "band": "window"},
            {"metric": "s11_at_5p8_db", "kind": "s_db_at_f", "ij": (0, 0), "f_ghz": 5.8},
        ),
        "gates": (
            {"metric": "f_min_ghz", "gate": 5.0, "gate_kind": "rel_pct", "key": True,
             "x_ref": (5.0, 6.6)},
            {"metric": "s11_min_db", "gate": 3.0, "gate_kind": "db_diff", "key": True,
             "x_ref": ("le", -8.0)},
            {"metric": "s11_at_5p8_db", "gate": 2.0, "gate_kind": "db_diff",
             "key": False},
        ),
        "g11": {"passive_le": 1.05, "recip_le": None},
        "oe": {
            "source": "constants",
            "constants": {"f_min_ghz": 6.026, "s11_min_db": -13.63,
                          "s11_at_5p8_db": -5.00},
            "provenance": "runs/ge_fd/patch_array_1x4/（F-D 战役 PASS 4372s，归档 "
                          "CSV 文档代理读档实测，README §1）；谷位 +3.9% 预声明已知，"
                          "主判=两引擎谷位/谷深一致不判 vs 设计 5.8GHz；方向图归 "
                          "OTA 线本席不判",
        },
        "anchor": "patch_array.f_res.openems-hfss-v1（族级单源，template_family="
                  "[patch_array_1x4, patch_array_2x2, patch_array_series]，kind="
                  "constant，quantity=阵列谷位相对偏差 %，domain=d 0.4–0.6λ0，"
                  "fallback=closed_form Balanis 传输线模型；DISAGREE 改 pointer 锚）",
    },
    # ── 发射序 8（建模全量，2026-09-28 补批；复用席 7 建模链）──
    "patch_array_2x2": {
        "order": 8,
        "template": "patch_array_2x2",
        "f0_ghz": 5.8,
        "n_ports": 1,
        "window_ghz": (4.64, 6.96),
        "n_points": 401,
        "ladder": ((0.02, 12), (0.01, 20), (0.005, 30)),
        "budget_min": 90,
        "builder": "patch_array_2x2",
        "ladder_scalars": ("f_min_ghz", "s11_min_db", "s11_at_5p8_db"),
        "extractors": (
            {"metric": "f_min_ghz", "kind": "s_db_min_f", "ij": (0, 0), "band": "window"},
            {"metric": "s11_min_db", "kind": "s_db_min_v", "ij": (0, 0), "band": "window"},
            {"metric": "s11_at_5p8_db", "kind": "s_db_at_f", "ij": (0, 0), "f_ghz": 5.8},
        ),
        "gates": (
            {"metric": "f_min_ghz", "gate": 5.0, "gate_kind": "rel_pct", "key": True,
             "x_ref": (5.0, 6.6)},
            {"metric": "s11_min_db", "gate": 3.0, "gate_kind": "db_diff", "key": True,
             "x_ref": ("le", -8.0)},
            {"metric": "s11_at_5p8_db", "gate": 2.0, "gate_kind": "db_diff",
             "key": False},
        ),
        "g11": {"passive_le": 1.05, "recip_le": None},
        "oe": {
            "source": "constants",
            "constants": {"f_min_ghz": 4.976, "s11_min_db": -17.84,
                          "s11_at_5p8_db": -2.92},
            "provenance": "runs/ge_fd/patch_array_2x2/（F-D 战役 PASS 4028.5s，归档 "
                          "CSV 文档代理读档实测，README §1）；谷位 −14.2% 预声明已知"
                          "越 x_ref 窗→两引擎一致时按 AGREE_OPENEMS 判（不事后改窗）",
        },
        "anchor": "不重复注册：并入席 7 族锚 patch_array.f_res.openems-hfss-v1 第二 "
                  "provenance 数据点；两席判态不同→族锚降级 experimental（不取平均"
                  "凑族锚，#122）",
    },
}

LAUNCH_ORDER: tuple[str, ...] = tuple(
    sorted(SEATS, key=lambda name: int(SEATS[name]["order"])))


# ═══════════ 判据 lesson 门 + marchand 端口形态发射面（S2 审计 2026-09-29）══════════
# 回写对象=SEATS 判据定义面；已落档 verdict/锚值零触碰（#122 判据面演进走
# 机制新增，不改动已发射席的门值/窗/预算）。

def resolve_marchand_port_form(seat_name: str,
                               port_form: str | None = None) -> str:
    """marchand 端口形态解析（S2 决策 2 发射面）：显式参数 > 席 spec 缺省
    （lumped140=已落档 140Ω 集总 build，行为零变化）。非 marchand 席显式传
    非 lumped140 形态=ValueError（端口形态单变量对照只属该席；显式传缺省
    lumped140 容忍为无操作——本函数对已解析值幂等，内部分派面可安全回呼）；
    CLI 面对非 marchand 席的任何显式传参在 main() parser.error 拒绝。"""
    default = str(SEATS.get(seat_name, {}).get("port_form", "lumped140"))
    form = default if port_form is None else str(port_form)
    if form not in MARCHAND_PORT_FORMS:
        raise ValueError(f"未知 marchand 端口形态 {form!r}"
                         f"（可选 {MARCHAND_PORT_FORMS}）")
    if (seat_name != "marchand_balun" and port_form is not None
            and form != "lumped140"):
        raise ValueError(f"--marchand-port-form 仅适用 marchand_balun"
                         f"（got seat={seat_name}, form={form}）")
    return form


def criteria_for_run(seat_name: str, port_form: str | None = None) -> dict:
    """判据分派（#122 判据先行）：lumped140（缺省）=冻结 SEATS spec 原样
    （同一 dict，零复制零变化）；marchand wave2mode=端口形态单变量对照判据
    ——平衡侧改 2 模大截面波端口后，模域 S（Σ5 模）对端接口径幅度提取器
    （S21/S31/imbalance band 门）不可直接消费，判读面分派为 **P1 反射侧**
    （f_null 主门 weak_feature 条件降级 + s11_min 信息项）；平衡量经 2 模
    反演离线判读（锚 A 链，消费 run*.s5p 归档）。SEATS 本体不动（已落档
    criteria §3–§5 冻结）。"""
    seat = SEATS[seat_name]
    form = resolve_marchand_port_form(seat_name, port_form)
    if form == "lumped140":
        return seat
    w2m = dict(seat)
    w2m["port_form"] = form
    w2m["extractors"] = tuple(
        e for e in seat["extractors"]
        if e["metric"] in ("f_null_ghz", "s11_min_db"))
    # 判据分派门表（预声明，非 SEATS 冻结面）：f_null 主门（P1 反射跨端口
    # 形态可比；weak_feature 条件降级 lesson-2）+ s11_min 信息项（端口形态
    # 敏感量，记录不判）。平衡量 band 门不进分派面（2 模反演离线判读）。
    w2m["gates"] = (
        {"metric": "f_null_ghz", "gate": 10.0, "gate_kind": "rel_pct",
         "key": True, "weak_feature": True,
         "note": "OE 参考 3.272GHz=驻波免疫估计器主判（P1 反射谷，跨端口"
                 "形态可比）；病态背景弱特征条件降级 lesson-2"},
        {"metric": "s11_min_db", "gate": 5.0, "gate_kind": "db_diff",
         "key": False,
         "note": "信息项：P1 反射带内最优匹配深度（端口形态敏感，记录不判）"},
    )
    w2m["ladder_scalars"] = ("f_null_ghz", "s11_min_db")
    return w2m


def seat_mode_count(seat_name: str, port_form: str | None = None) -> int:
    """Touchstone 导出 Σ模数（#309 命名口径）：端子数；marchand wave2mode
    =P1 单模 + PA/PB 各 2 模 = 5（.s5p）。"""
    seat = SEATS[seat_name]
    if (seat_name == "marchand_balun"
            and resolve_marchand_port_form(seat_name, port_form) == "wave2mode"):
        return 1 + 2 + 2
    return int(seat["n_ports"])


def band_symmetry_violations(seat: dict) -> list[str]:
    """lesson-1（带窗对称化）：band 统计量门**双侧同带**强制。

    背景（审计 §3.2(c)）：本窗 marchand 的 OE 幅度参考取自 smoke 判读带
    [2.25,2.75]、HFSS 值取自全窗 [1.8,3.6]，不同频带上的 band min/max 直接
    对差=判据口径缺口（42dB 级 DISAGREE 的放大器，非主因但必须堵死）。机制：
    外部常量型 OE 参考（source ∈ OE_CONST_SOURCES，不经本驱动同带提取）
    的带统计量门必须 ①提取器显式声明数值带（band="window" 双侧语义不同、
    不可核验=违例）②``oe["band_ghz"]`` 已声明且与每个带统计量提取器带逐位
    一致。曲线型 OE（sparams_csv/touchstone）经同一提取器同带提取（构造性
    同带）豁免；其显式声明 band_ghz 时仍做一致性复核。返回违例清单（空=
    过门）；run_seat 起跑前 fail-closed（判据面错误=执行 FAIL，不发射）。
    """
    out: list[str] = []
    oe = seat.get("oe", {})
    src = oe.get("source")
    gated = {g["metric"] for g in seat.get("gates", ())}
    declared = oe.get("band_ghz")
    declared_t = (None if declared is None
                  else (float(declared[0]), float(declared[1])))
    for ex in seat.get("extractors", ()):
        if ex.get("metric") not in gated or ex.get("kind") not in BAND_STAT_KINDS:
            continue
        name, band = ex["metric"], ex.get("band", "window")
        if band == "window":
            if src in OE_CONST_SOURCES:
                out.append(
                    f"{name}: 带统计量门 band=window 而 OE 为外部常量源"
                    f"（{src}）——外部常量的判读带不可核验（lesson-1 双侧"
                    "同带强制）")
            continue
        band_t = (float(band[0]), float(band[1]))
        if src in OE_CONST_SOURCES and declared_t is None:
            out.append(f"{name}: OE 为外部常量源而 oe.band_ghz 未声明"
                       "（lesson-1 双侧同带强制）")
        elif declared_t is not None and declared_t != band_t:
            out.append(f"{name}: oe.band_ghz {declared_t} 与提取器带 "
                       f"{band_t} 不一致（lesson-1 双侧同带强制）")
    return out


def assert_band_symmetry(seat: dict) -> None:
    """lesson-1 门（run_seat 起跑前 fail-closed）。"""
    violations = band_symmetry_violations(seat)
    if violations:
        raise ValueError(
            "判据 lesson-1 违例（band 统计量门双侧同带，S2 审计 2026-09-29 "
            "§3.2(c)/§3.4①）：\n- " + "\n- ".join(violations))


# ═══════════════ 纯函数：S 参数指标提取（OE/HFSS 同一函数，#121 同口径）══════════════

def _db(x: Any) -> Any:
    return 20.0 * np.log10(np.maximum(np.abs(x), DB_FLOOR))


def _band_mask(freq_ghz: np.ndarray, band: tuple[float, float]) -> np.ndarray:
    return (freq_ghz >= band[0]) & (freq_ghz <= band[1])


def _band_of(ex: dict, seat: dict) -> tuple[float, float]:
    band = ex.get("band", "window")
    if band == "window":
        return (float(seat["window_ghz"][0]), float(seat["window_ghz"][1]))
    return (float(band[0]), float(band[1]))


def _interp_db_at(freq_ghz: np.ndarray, sdb: np.ndarray, f_ghz: float) -> float:
    idx = int(np.argmin(np.abs(freq_ghz - f_ghz)))
    return float(sdb[idx])


def _bw3db_detail(freq_ghz: np.ndarray, sdb: np.ndarray,
                  band: tuple[float, float]) -> dict[str, Any]:
    """−3dB 带宽明细（review-slice11 P1-1 新语义，criteria §8 注记在案）：

    - **主瓣口径**：带内 |S21|≥−3dB 可能有多个连续段——取**含 S21 峰的段**
      （峰所在段=主通带；不含峰段=窗沿截断伪象瓣）。旧"最宽段"口径会把
      窗沿截断的上瓣当带宽（stepped HFSS rung3 上瓣 0.705 vs 主瓣 0.68
      实证，review-slice11 P1-1 错瓣拾取）；
    - **触沿截断**：主瓣段触碰窗沿（f=窗端点，1e-9 GHz 容差）→
      truncated=True 且 width=None——带宽只是窗沿截断下界，如实 UNKNOWN
      不 DISAGREE（判据语义变更；#281 夹持伪象族，此前仅"全上/全下"
      返回 None、触沿段照常返回数值，违背自身语义声明）；
    - 无穿越（全 <−3dB）/全程 ≥−3dB → width=None（原语义不变，如实）。

    返回 {width, truncated, reason, segments, main_lobe?, peak_*}；segments
    记全部 ≥−3dB 段（f_lo/f_hi/width）供 verdict/离线复核留证。
    """
    m = _band_mask(freq_ghz, band)
    idx = np.nonzero(m)[0]
    if idx.size == 0:
        return {"width": None, "truncated": False, "reason": "empty_band",
                "segments": []}
    fg = freq_ghz[idx]
    sub = np.asarray(sdb)[m]
    above = sub >= -3.0
    if not bool(above.any()):
        return {"width": None, "truncated": False, "reason": "no_crossing",
                "segments": []}
    segs: list[dict[str, Any]] = []
    run_start = None
    for k, flag in enumerate([*above, False]):
        if flag and run_start is None:
            run_start = k
        elif not flag and run_start is not None:
            segs.append({"f_lo": float(fg[run_start]),
                         "f_hi": float(fg[k - 1]),
                         "width": float(fg[k - 1] - fg[run_start]),
                         "i_lo": run_start, "i_hi": k - 1})
            run_start = None
    if bool(above.all()):
        return {"width": None, "truncated": False, "reason": "all_above",
                "segments": [{k: s[k] for k in ("f_lo", "f_hi", "width")}
                             for s in segs]}
    peak_local = int(np.argmax(sub))
    main = next(s for s in segs if s["i_lo"] <= peak_local <= s["i_hi"])
    tol = 1e-9
    truncated = bool(fg[main["i_lo"]] <= band[0] + tol
                     or fg[main["i_hi"]] >= band[1] - tol)
    return {"width": None if truncated else main["width"],
            "truncated": truncated,
            "reason": "edge_truncated" if truncated else "main_lobe",
            "segments": [{k: s[k] for k in ("f_lo", "f_hi", "width")}
                         for s in segs],
            "main_lobe": {k: main[k] for k in ("f_lo", "f_hi", "width")},
            "peak_f_ghz": float(fg[peak_local]),
            "peak_db": float(sub[peak_local])}


def _bw3db(freq_ghz: np.ndarray, sdb: np.ndarray,
           band: tuple[float, float]) -> float | None:
    """−3dB 带宽门值（主瓣口径+触沿截断如实 UNKNOWN，明细
    _bw3db_detail；review-slice11 P1-1 语义变更，stepped 席 criteria §8 注记）。"""
    return _bw3db_detail(freq_ghz, sdb, band)["width"]


def _peak_f3db_center(freq_ghz: np.ndarray, sdb: np.ndarray,
                      band: tuple[float, float]) -> tuple[float | None, bool]:
    """峰位 −3dB 带心（review-slice11 P1-2，#298 口径）。

    argmax 峰位在峰平台化时是歧义量（纹波/平台上任意点同值，真峰可在平台
    任意处；#298 切比雪夫纹波峰族实证）——报告口径取峰邻域 ≥(峰−3dB)
    连续段的带心（段触窗沿时以窗端点夹持，#281 族）。
    返回 (center, censored)：censored=段触窗沿（真峰可在窗外，带心为夹持
    下界估计，verdict/锚须带 censored 标记不可作定量引用）；带空→
    (None, False)。"""
    m = _band_mask(freq_ghz, band)
    if not bool(m.any()):
        return None, False
    sub = np.asarray(sdb)[m]
    fg = freq_ghz[m]
    pk = int(np.argmax(sub))
    lvl = float(sub[pk]) - 3.0
    lo = pk
    while lo - 1 >= 0 and sub[lo - 1] >= lvl:
        lo -= 1
    hi = pk
    while hi + 1 < len(sub) and sub[hi + 1] >= lvl:
        hi += 1
    tol = 1e-9
    censored = bool(fg[lo] <= band[0] + tol or fg[hi] >= band[1] - tol)
    return float(0.5 * (fg[lo] + fg[hi])), censored


def valley_map(freq_ghz: np.ndarray, sdb: np.ndarray,
               band: tuple[float, float] | None = None,
               min_prominence_db: float = 3.0) -> dict[str, Any]:
    """lesson-3 谷位图+深度矩阵（S2 审计 2026-09-29 §5.2/§5.4）。

    argmin 型 f_*（s_db_min_f）在带内多谷时是离散/双稳量：patch_2x2 实证
    两引擎 4 谷谷位一致 ≤0.3% 而「f_min 分歧 14.3%」实为谷 1/谷 2 深度排序
    翻转——单值 f_* 语义丢失谷位图。对（带内）dB 曲线提取全部显著局部极小：
    prominence=谷深相对「到最近更深谷（或带端）之间最高点」的高差，
    <min_prominence_db 的纹波谷不计。返回 {band, n_valleys, valleys:
    [{f_ghz, depth_db, prominence_db}] 按频率升序}（值同层结构化出口，
    ``<metric>_valleys``，_detail 先例）。"""
    fg = np.asarray(freq_ghz, dtype=float)
    sdb = np.asarray(sdb, dtype=float)
    if band is not None:
        m = _band_mask(fg, band)
        if not bool(m.any()):
            return {"band": None, "n_valleys": 0, "valleys": []}
        fg, sdb = fg[m], sdb[m]
    n = len(sdb)
    if n < 3:
        return {"band": (None if band is None else [float(band[0]),
                                                    float(band[1])]),
                "n_valleys": 0, "valleys": []}
    is_min = np.zeros(n, dtype=bool)
    is_min[1:-1] = (sdb[1:-1] < sdb[:-2]) & (sdb[1:-1] < sdb[2:])
    valleys: list[dict[str, Any]] = []
    for i in np.nonzero(is_min)[0]:
        side_cols: list[float] = []
        for rng in (range(i - 1, -1, -1), range(i + 1, n)):
            col: float | None = None
            for j in rng:
                if sdb[j] < sdb[i]:          # 触到更深谷=该侧鞍点已定
                    break
                col = float(sdb[j]) if col is None else max(col, float(sdb[j]))
            side_cols.append(col if col is not None else float(sdb[i]))
        prom = min(side_cols) - float(sdb[i])
        if prom >= min_prominence_db:
            valleys.append({"f_ghz": float(fg[i]),
                            "depth_db": float(sdb[i]),
                            "prominence_db": round(float(prom), 6)})
    return {"band": (None if band is None else [float(band[0]),
                                                float(band[1])]),
            "n_valleys": len(valleys), "valleys": valleys}


def valley_map_compare(hfss_vm: dict, oe_vm: dict,
                       pos_tol_pct: float = 1.0) -> dict[str, Any]:
    """双侧谷位图对读（lesson-3「谷位图+深度矩阵」判读口径）：HFSS 谷逐个
    配最近 OE 谷（位置），报位置差 %/谷深差 dB；depth_order_agrees=按位置
    序的谷深排序两侧是否一致；argmin_same=最深谷落同一谷（位置差 ≤
    pos_tol_pct）。patch_2x2 预期形态：位置差 ≤0.3% 全对、谷深排序翻转
    （depth_order_agrees=False）而单值 f_min 差 14.3%——「f_min 分歧」的
    真语义在此字段而非单值。"""
    hv = list(hfss_vm.get("valleys") or [])
    ov = list(oe_vm.get("valleys") or [])
    pairs: list[dict[str, Any]] = []
    for v in hv:
        if not ov:
            break
        j = int(np.argmin([abs(v["f_ghz"] - w["f_ghz"]) for w in ov]))
        w = ov[j]
        base = abs(float(w["f_ghz"]))
        pos_pct = (abs(v["f_ghz"] - w["f_ghz"]) / base * 100.0
                   if base > 1e-12 else float("inf"))
        pairs.append({"f_ghz": v["f_ghz"], "oe_f_ghz": w["f_ghz"],
                      "pos_diff_pct": round(float(pos_pct), 4),
                      "depth_db": v["depth_db"], "oe_depth_db": w["depth_db"],
                      "depth_diff_db": round(float(v["depth_db"]
                                                  - w["depth_db"]), 4)})

    def _order(vs: list[dict[str, Any]]) -> list[float]:
        return [round(float(v["f_ghz"]), 6)
                for v in sorted(vs, key=lambda v: v["depth_db"])]

    out: dict[str, Any] = {"pairs": pairs}
    if hv and ov:
        out["max_pos_diff_pct"] = max(p["pos_diff_pct"] for p in pairs)
        out["depth_order_hfss"] = _order(hv)
        out["depth_order_oe"] = _order(ov)
        out["depth_order_agrees"] = (out["depth_order_hfss"]
                                     == out["depth_order_oe"])
        hd = min(hv, key=lambda v: v["depth_db"])
        od = min(ov, key=lambda v: v["depth_db"])
        out["argmin_same"] = bool(
            abs(hd["f_ghz"] - od["f_ghz"]) / max(abs(od["f_ghz"]), 1e-12)
            * 100.0 <= pos_tol_pct)
    return out


def _measured_ok(mask: np.ndarray | None, ij: tuple[int, int],
                 band_sel: np.ndarray | None = None) -> bool:
    """#314：席指标需要的元素必须（选择带内）全部已测；无掩码=HFSS 全矩阵
    （掩码语义完备）恒 True。mask 兼容 (n,n) 与 (nf,n,n) 两种形态。"""
    if mask is None:
        return True
    arr = np.asarray(mask)
    if arr.ndim == 3:
        if ij[0] >= arr.shape[1] or ij[1] >= arr.shape[2]:
            return False
        col = arr[:, ij[0], ij[1]]
        col = col[band_sel] if band_sel is not None else col
        return bool(np.all(col))
    if ij[0] >= arr.shape[0] or ij[1] >= arr.shape[1]:
        return False
    return bool(arr[ij[0], ij[1]])   # (n,n) 掩码与频点无关，band_sel 不影响


def _measured_val(mask: np.ndarray | None, ij: tuple[int, int],
                  freq_ghz: np.ndarray, s: np.ndarray, f_ghz: float) -> float | None:
    idx = int(np.argmin(np.abs(freq_ghz - f_ghz)))
    if mask is not None:
        arr = np.asarray(mask)
        got = (arr[idx, ij[0], ij[1]] if arr.ndim == 3
               else arr[ij[0], ij[1]])
        if not bool(got):
            return None
    return _interp_db_at(freq_ghz, _db(s[:, ij[0], ij[1]]), f_ghz)


def _diff_at(mask: np.ndarray | None, ij1: tuple[int, int], ij2: tuple[int, int],
             freq_ghz: np.ndarray, s: np.ndarray, f_ghz: float) -> float | None:
    v1 = _measured_val(mask, ij1, freq_ghz, s, f_ghz)
    v2 = _measured_val(mask, ij2, freq_ghz, s, f_ghz)
    if v1 is None or v2 is None:
        return None
    return float(v1 - v2)


def extract_metrics(freq_hz: np.ndarray, s: np.ndarray, seat: dict,
                    mask: np.ndarray | None = None,
                    notes: list[str] | None = None) -> dict[str, Any]:
    """(freq_hz, S[nf,n,n]) → 席指标 dict。OE 与 HFSS 走同一提取器（同口径）。

    mask（#314）：bool (n,n) 或 (nf,n,n)；True=该元素直接测得。所需元素带内
    存在未测点 → 该指标 None（判读 UNKNOWN，不凑判）。
    notes（review-slice11 P1-2，可选）：提取侧如实注记出口（censored 等）——
    调用方传 list 时追加、随 implementation_notes 落 verdict；None=现行为。
    censored 结构化出口（review-slice13 P1-1，照本批 P2-2「关键判读口径不得
    只存自由文本」自立先例）：center3db 带心触窗沿 / bw3db 主瓣触沿截断时，
    在**值同层**落 ``<metric>_censored=True``（键值结构化，live 重跑自动在位，
    非顶层自由文本）；notes 仍并行发射供 implementation_notes 留证。
    """
    freq_ghz = np.asarray(freq_hz, dtype=float) / 1e9
    s = np.asarray(s, dtype=complex)
    if s.ndim == 2:
        s = s[None, ...]
    out: dict[str, Any] = {}
    # 第一遍：定位量（f_*）；第二遍：引用/带内量（*_at_ref / band / at_f）
    for ex in seat["extractors"]:
        key, kind, ij = ex["metric"], ex["kind"], ex.get("ij", (0, 0))
        if kind in ("s_db_min_f", "s_db_min_v", "s_db_max_f", "s_db_max_v",
                    "s_db_max_f_center3db"):
            lo, hi = _band_of(ex, seat)
            m = _band_mask(freq_ghz, (lo, hi))
            # P2-1（review-slice3）：第一遍定位量同过 #314 掩码——零填充列
            # 不参与定位（否则垃圾 f_* 级联污染 *_at_ref 引用量），与 band 系
            # 同口径（带内全测才定位）。
            if not _measured_ok(mask, ij, m):
                out[key] = None
                continue
            sdb = _db(s[:, ij[0], ij[1]])
            if not bool(m.any()):
                out[key] = None
                continue
            if kind == "s_db_max_f_center3db":
                # review-slice11 P1-2（#298 口径）：argmax 峰位是平台歧义量，
                # f_peak 报告口径改峰 −3dB 带心；段触窗沿 censored 如实注记
                # （真峰可在窗外，带心为夹持下界，不作定量引用）。
                center, censored = _peak_f3db_center(freq_ghz, sdb, (lo, hi))
                out[key] = center
                if censored:
                    # review-slice13 P1-1：censored 结构化字段与值同层落
                    # （live 重跑自动在位；离线补写 "censored": true 的档案
                    # 缺口就此闭合），notes 并行发射供留证。
                    out[key + "_censored"] = True
                    if notes is not None:
                        notes.append(
                            f"{key}: 峰 −3dB 段触窗沿（censored，#281 族）——带心"
                            "为窗沿夹持下界，真峰可在窗外，不可作定量引用"
                            "（review-slice11 P1-2）")
                continue
            fill = -np.inf if kind in ("s_db_max_f", "s_db_max_v") else np.inf
            sub = np.where(m, sdb, fill)
            idx = int(np.argmax(sub) if fill < 0 else np.argmin(sub))
            if kind in ("s_db_min_f", "s_db_max_f"):
                out[key] = float(freq_ghz[idx])
                if kind == "s_db_min_f":
                    # lesson-3（S2 审计 §5.2/§5.4）：argmin 型定位量随谷位图
                    # 出口（值同层，_detail 先例）——多谷近邻判读按谷位图+
                    # 深度矩阵，单值 f_* 语义丢失谷位信息（patch_2x2 排序
                    # 翻转实证）；单谷形态出口照发（n_valleys=1 如实）。
                    vm = valley_map(freq_ghz, sdb, (lo, hi))
                    out[key + "_valleys"] = vm
                    if vm["n_valleys"] >= 2 and notes is not None:
                        notes.append(
                            f"{key}: 带内 {vm['n_valleys']} 谷（lesson-3）——"
                            "argmin 单值为离散/双稳量，判读按 <metric>_valleys"
                            " 谷位图+深度矩阵，不按单值下物理结论")
            else:
                out[key] = float(sdb[idx])
    for ex in seat["extractors"]:
        key, kind = ex["metric"], ex["kind"]
        ij = ex.get("ij", (0, 0))
        if key in out:
            continue
        if kind == "s_db_at_f":
            if not _measured_ok(mask, ij):
                out[key] = None
            else:
                out[key] = _interp_db_at(freq_ghz, _db(s[:, ij[0], ij[1]]),
                                         float(ex["f_ghz"]))
        elif kind == "s_db_at_ref":
            ref = out.get(ex["ref"])
            out[key] = (None if ref is None
                        else _measured_val(mask, ij, freq_ghz, s, float(ref)))
        elif kind == "diff_at_ref":
            ref = out.get(ex["ref"])
            out[key] = (None if ref is None
                        else _diff_at(mask, ex["ij1"], ex["ij2"], freq_ghz, s,
                                      float(ref)))
        elif kind == "diff_at_f":
            out[key] = _diff_at(mask, ex["ij1"], ex["ij2"], freq_ghz, s,
                                float(ex["f_ghz"]))
        elif kind == "mean_amp_at_ref":
            ref = out.get(ex["ref"])
            if ref is None:
                out[key] = None
            else:
                v1 = _measured_val(mask, ex["ij1"], freq_ghz, s, float(ref))
                v2 = _measured_val(mask, ex["ij2"], freq_ghz, s, float(ref))
                out[key] = None if (v1 is None or v2 is None) else 0.5 * (v1 + v2)
        elif kind in ("s_db_band_max", "s_db_band_min"):
            lo, hi = _band_of(ex, seat)
            m = _band_mask(freq_ghz, (lo, hi))
            if not _measured_ok(mask, ij, m):
                out[key] = None
                continue
            sdb = _db(s[:, ij[0], ij[1]])
            if not bool(m.any()):
                out[key] = None
            else:
                out[key] = (float(np.max(sdb[m])) if kind == "s_db_band_max"
                            else float(np.min(sdb[m])))
        elif kind == "imb_band_max":
            lo, hi = _band_of(ex, seat)
            m = _band_mask(freq_ghz, (lo, hi))
            if not (_measured_ok(mask, ex["ij1"], m)
                    and _measured_ok(mask, ex["ij2"], m)):
                out[key] = None
                continue
            d = np.abs(_db(s[:, ex["ij1"][0], ex["ij1"][1]])
                       - _db(s[:, ex["ij2"][0], ex["ij2"][1]]))
            out[key] = None if not bool(m.any()) else float(np.max(d[m]))
        elif kind == "phase_diff_at_ref":
            ref = out.get(ex["ref"])
            if ref is None:
                out[key] = None
                continue
            idx = int(np.argmin(np.abs(freq_ghz - float(ref))))
            out[key] = float(np.angle(
                s[idx, ex["ij2"][0], ex["ij2"][1]]
                * np.conj(s[idx, ex["ij1"][0], ex["ij1"][1]]), deg=True))
        elif kind == "bw3db":
            lo, hi = _band_of(ex, seat)
            if not _measured_ok(mask, ij):
                out[key] = None
            else:
                # review-slice13 P3-A/P2补：明细走 _bw3db_detail 同层落
                # （<metric>_detail；docstring「供 verdict 留证」就此在 live
                # 链兑现，bw 截断档不再只有裸 None）；truncated → censored
                # 结构化字段（review-slice13 P1-1）+ notes 出口（此前 bw3db
                # 分支无 notes，截断语义只可从离线重判脚本补）。
                detail = _bw3db_detail(freq_ghz, _db(s[:, ij[0], ij[1]]),
                                       (lo, hi))
                out[key] = detail["width"]
                out[key + "_detail"] = detail
                if detail["truncated"]:
                    out[key + "_censored"] = True
                    if notes is not None:
                        notes.append(
                            f"{key}: 带宽主瓣段触窗沿截断（censored，#281 族）"
                            "——width=None 为窗沿截断下界，真带宽可在窗外，"
                            "不可作定量引用（review-slice11 P1-1 主瓣口径）")
    return out


# ═══════════════ 纯函数：门判定（#350 四态）+ 阶梯采信（#335）+ G11（#314）══════════════

def _diff_of(gate_kind: str, hfss_v: float, oe_v: float) -> float:
    if gate_kind == "rel_pct":
        base = abs(oe_v)
        if base < 1e-12:
            return abs(hfss_v - oe_v) * 100.0
        return abs(hfss_v - oe_v) / base * 100.0
    if gate_kind in ("db_diff", "abs_diff"):
        return abs(hfss_v - oe_v)
    raise ValueError(f"未知 gate_kind {gate_kind!r}")


def _in_x_ref(value: float, x_ref: Any) -> bool:
    """裁判窗判定：tuple=(lo,hi) 窗；("le",v)/("ge",v) 单边；None/closed_form
    未解析串=无窗（恒 True，判读侧如实标注）。"""
    if x_ref is None:
        return True
    if isinstance(x_ref, str):
        return True
    if (isinstance(x_ref, tuple) and len(x_ref) == 2
            and x_ref[0] in ("le", "ge")):
        return value <= x_ref[1] if x_ref[0] == "le" else value >= x_ref[1]
    lo, hi = float(x_ref[0]), float(x_ref[1])
    return bool(lo <= value <= hi)


def _x_ref_repr(x_ref: Any) -> Any:
    if x_ref is None:
        return None
    if isinstance(x_ref, str):
        return x_ref
    if isinstance(x_ref, tuple) and x_ref and x_ref[0] in ("le", "ge"):
        return [x_ref[0], x_ref[1]]
    return [float(x_ref[0]), float(x_ref[1])]


def judge_metric(hfss_v: Any, oe_v: Any, gate: dict) -> dict:
    """单指标四态判读（criteria §4 预声明，写死）。

    - 双方任一值缺失（None/NaN）→ UNKNOWN（不参与总态，#122 如实）；
    - 门不过 → DISAGREE；
    - 门过 + 均落裁判窗 → AGREE_JUDGE；
    - 门过 + HFSS 落窗而 OE 越窗 → AGREE_HFSS（HFSS 对齐基准，OE 记 κ）；
    - 门过 + 其余（双越窗/跨界）→ AGREE_OPENEMS（引擎互证成立，偏差归因
      裁判窗/名义侧）。
    """
    out: dict[str, Any] = {
        "metric": gate["metric"], "gate": gate["gate"],
        "gate_kind": gate["gate_kind"], "key": bool(gate["key"]),
        "x_ref": _x_ref_repr(gate.get("x_ref")), "hfss": hfss_v, "oe": oe_v,
    }
    vals: list[float] = []
    for v in (hfss_v, oe_v):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out["state"] = "UNKNOWN"
            return out
        vals.append(float(v))
    hfss_f, oe_f = vals
    diff = _diff_of(gate["gate_kind"], hfss_f, oe_f)
    in_gate = diff <= gate["gate"]
    hfss_in = _in_x_ref(hfss_f, gate.get("x_ref"))
    oe_in = _in_x_ref(oe_f, gate.get("x_ref"))
    out.update({"diff": round(diff, 6), "in_gate": bool(in_gate),
                "hfss_in_x_ref": bool(hfss_in), "oe_in_x_ref": bool(oe_in)})
    if not in_gate:
        out["state"] = "DISAGREE"
    elif hfss_in and oe_in:
        out["state"] = "AGREE_JUDGE"
    elif hfss_in:
        out["state"] = "AGREE_HFSS"
    else:
        out["state"] = "AGREE_OPENEMS"
    return out


def _s_band_ext_db(freq_hz: np.ndarray, s: np.ndarray, ij: tuple[int, int],
                   band: tuple[float, float]) -> tuple[float, float]:
    """带内 |Sij| dB 的 (band_max, band_min)——lesson-2 背景判据独立重算用
    （与提取器同 _db/掩码口径；带空 → NaN）。"""
    freq_ghz = np.asarray(freq_hz, dtype=float) / 1e9
    sdb = _db(np.asarray(s)[:, ij[0], ij[1]])
    m = _band_mask(freq_ghz, band)
    if not bool(m.any()):
        return float("nan"), float("nan")
    return float(np.max(sdb[m])), float(np.min(sdb[m]))


def weak_feature_downgrade(gate: dict, freq_hz: np.ndarray, s: np.ndarray,
                           seat: dict) -> dict[str, Any] | None:
    """lesson-2（病态背景弱特征不设 DISAGREE 门）背景判据。

    定位口带内**最优匹配**（|S| dB band-min）劣于 WEAK_FEATURE_BG_FLOOR_DB
    （−3dB，|Γ|>0.7）→ 该带内"谷"是全反射背景上的纹波极小（marchand 本窗
    HFSS 实证：s11_min 仅 −1.28dB、f_null 跨 build 漂移 +45%，审计 §3.2(b)）
    ——病态弱特征只记信息项不设门：观测分歧照实记录、不翻总态。健康背景
    （真实深谷）门照常强制（负例语义）。非 weak_feature 门 / 定位口无带
    返回 None；否则返回 {metric, band_ghz, background_db, floor_db,
    pathological, downgraded, rule}（downgraded=pathological，判读侧据此
    排除出总态并注记）。"""
    if not gate.get("weak_feature"):
        return None
    ex = next((e for e in seat["extractors"]
               if e["metric"] == gate["metric"]), None)
    if ex is None or ex.get("kind") != "s_db_min_f":
        return None
    lo, hi = _band_of(ex, seat)
    _mx, mn = _s_band_ext_db(freq_hz, s, ex.get("ij", (0, 0)), (lo, hi))
    pathological = bool(mn == mn and mn > WEAK_FEATURE_BG_FLOOR_DB)
    return {"metric": gate["metric"], "band_ghz": [float(lo), float(hi)],
            "background_db": (None if mn != mn else round(mn, 6)),
            "floor_db": WEAK_FEATURE_BG_FLOOR_DB,
            "pathological": pathological, "downgraded": pathological,
            "rule": ("定位口带内最优匹配劣于 −3dB（|Γ|>0.7 近全反射背景）"
                     "→ 病态弱特征降级 info 不翻总态（lesson-2，S2 审计 "
                     "§3.2(b)/§3.4②）")}


def total_verdict(per_metric: list[dict], cap: str | None = None) -> str:
    """总态：任一关键指标 DISAGREE → DISAGREE；否则取最差 AGREE 态；关键
    指标全 UNKNOWN → UNDECIDABLE；cap（闭式半集回退）封顶 AGREE_HFSS。
    lesson-2：病态背景降级（weak_feature.downgraded）的行不翻总态——观测
    照实记录在行内，降级只移除其判读效力（info 语义）。"""
    key_states = [r["state"] for r in per_metric
                  if r.get("key") and r["state"] != "UNKNOWN"
                  and not (isinstance(r.get("weak_feature"), dict)
                           and r["weak_feature"].get("downgraded"))]
    if not key_states:
        total = "UNDECIDABLE"
    elif "DISAGREE" in key_states:
        total = "DISAGREE"
    else:
        total = max(key_states, key=lambda st: _STATE_RANK[st])
    if cap == "AGREE_HFSS" and total in ("AGREE_JUDGE", "AGREE_OPENEMS"):
        total = "AGREE_HFSS"
    return total


def ladder_pick(rungs: list[dict], gates: tuple[dict, ...],
                scalars: tuple[str, ...]) -> dict:
    """ΔS 阶梯采信（#335）：触顶档（passes 用尽且 final_delta_s>档目标）数据
    不判读；收敛证据提取失败档（extraction_failed，review-slice3 P1-2）同样
    不判读（#323 终止信息缺失不采信，与触顶两态分开）；采信最深未触顶档；
    饱和=末两可用档 |Δ标量| < 门宽/3（逐标量，单调性只记录）。"""
    usable = [r for r in rungs
              if not r.get("topped") and not r.get("extraction_failed")]
    report: dict[str, Any] = {
        "rungs": [{k: r.get(k) for k in ("level", "max_delta_s", "max_passes",
                                         "passes", "final_delta_s", "topped",
                                         "extraction_failed", "solve_s")}
                  for r in rungs],
        "usable_levels": [r["level"] for r in usable],
        "extraction_failed_levels": [r["level"] for r in rungs
                                     if r.get("extraction_failed")],
    }
    if not usable:
        unv = report["extraction_failed_levels"]
        reason = ("全部档收敛证据提取失败（如实 UNKNOWN，#323 不采信）"
                  if unv and len(unv) == len(rungs)
                  else "全部档触顶或收敛证据缺失（#335 触顶档不判读）")
        report.update({"chosen_level": None, "saturated": None,
                       "saturated_all": None,
                       "reason": f"{reason} → 不可判读"})
        return report
    chosen = usable[-1]
    report["chosen_level"] = chosen["level"]
    gate_w = {g["metric"]: float(g["gate"]) for g in gates}
    if len(usable) >= 2:
        prev, last = usable[-2], usable[-1]
        sat: dict[str, bool] = {}
        for name in scalars:
            a = prev.get("metrics", {}).get(name)
            b = last.get("metrics", {}).get(name)
            if a is None or b is None or name not in gate_w:
                sat[name] = False
                continue
            sat[name] = abs(float(b) - float(a)) < gate_w[name] / 3.0
        report["saturated"] = sat
        report["saturated_all"] = all(sat.values()) if sat else None
    else:
        report["saturated"] = None
        report["saturated_all"] = None
    return report


def g11_health(freq_hz: np.ndarray, s: np.ndarray, mask: np.ndarray | None,
               g11: dict) -> dict:
    """G11 健康门（#314 掩码口径）：有限性/无源性全矩阵；互易性只对双向独立
    已测对下结论，无对如实 UNKNOWN 不凑判。FAIL 不自动翻仲裁态。"""
    s = np.asarray(s, dtype=complex)
    if s.ndim == 2:
        s = s[None, ...]
    finite = bool(np.all(np.isfinite(s)))
    mag = np.abs(s)
    passive_le = float(g11["passive_le"])
    out: dict[str, Any] = {
        "finite": finite,
        "passive": bool(np.max(mag) <= passive_le),
        "max_abs_s": round(float(np.max(mag)), 6),
        "passive_le": passive_le,
        "n_points": int(s.shape[0]),
    }
    recip_le = g11.get("recip_le")
    if recip_le is None:
        out["reciprocity"] = "NOT_APPLICABLE（单端口，criteria §5 如实不设门）"
        return out
    if mask is not None and np.asarray(mask).ndim == 2:
        m2 = np.asarray(mask)
        pairs = [(i, j) for i in range(s.shape[1]) for j in range(s.shape[2])
                 if i < j and bool(m2[i, j]) and bool(m2[j, i])]
    else:
        pairs = [(i, j) for i in range(s.shape[1]) for j in range(s.shape[2]) if i < j]
    if not pairs:
        out["reciprocity"] = "UNKNOWN（无双向独立已测对，#314 不凑判）"
        return out
    worst = max(float(np.max(np.abs(s[:, i, j] - s[:, j, i]))) for i, j in pairs)
    out["reciprocity"] = "PASS" if worst <= float(recip_le) else "FAIL"
    out["reciprocity_max_abs"] = round(worst, 9)
    out["reciprocity_le"] = float(recip_le)
    out["reciprocity_pairs"] = [list(p) for p in pairs]
    return out


# ═══════════════ 纯函数：几何审计（#310④ 重叠垫 / #336 断链 / #191 集总桥）══════════════

def rect_overlap_area(a: Rect, b: Rect) -> float:
    """XY 矩形交叠面积（mm²）；#310④ 铁律：仅共边=0 面积不连通。"""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def apply_pads(rects: dict[str, Rect], pads: list[dict[str, Any]]) -> dict[str, Rect]:
    """junction 重叠垫（#310④）：pad={a, b, axis}——把 a 沿指向 b 的方向延伸
    PAD_MM，保证 a∩b 面积 > 0（unite 真合并、薄片进 PEC 表）。"""
    out: dict[str, Rect] = {k: (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
                            for k, v in rects.items()}
    for pad in pads:
        a_name, b_name = pad["a"], pad["b"]
        ax_lo, ay_lo, ax_hi, ay_hi = out[a_name]
        bx_lo, by_lo, bx_hi, by_hi = out[b_name]
        if pad.get("axis", "y") == "y":
            if (by_lo + by_hi) >= (ay_lo + ay_hi):
                ay_hi = ay_hi + PAD_MM
            else:
                ay_lo = ay_lo - PAD_MM
        else:
            if (bx_lo + bx_hi) >= (ax_lo + ax_hi):
                ax_hi = ax_hi + PAD_MM
            else:
                ax_lo = ax_lo - PAD_MM
        out[a_name] = (ax_lo, ay_lo, ax_hi, ay_hi)
    return out


def edge_touch_pads(rects: dict[str, Rect],
                    tol: float = 1e-6) -> list[dict[str, Any]]:
    """邻接自动垫（#310④，阵列树/环网几十片拼接用）：零面积但共边的盒对
    （一轴间隙 ≤tol 且另一轴投影 >tol）逐对生成 pad——apply_pads 把前者
    向后者延伸 PAD_MM。面积交叠对跳过（已连通）；纯点接触（双轴投影皆
    0）不生成（引擎语义下非连接）。确定性：按 rects 声明序 i<j 枚举。"""
    names = list(rects)
    pads: list[dict[str, Any]] = []
    for i, a in enumerate(names):
        ra = rects[a]
        for b in names[i + 1:]:
            rb = rects[b]
            if rect_overlap_area(ra, rb) > 1e-9:
                continue
            gx = max(ra[0], rb[0]) - min(ra[2], rb[2])   # x 向间隙（0=共边）
            gy = max(ra[1], rb[1]) - min(ra[3], rb[3])
            px = min(ra[2], rb[2]) - max(ra[0], rb[0])   # 另一轴投影
            py = min(ra[3], rb[3]) - max(ra[1], rb[1])
            if abs(gx) <= tol and py > tol:
                pads.append({"a": a, "b": b, "axis": "x"})
            elif abs(gy) <= tol and px > tol:
                pads.append({"a": a, "b": b, "axis": "y"})
    return pads


def audit_connectivity(rects: dict[str, Rect],
                       min_area: float = 1e-9) -> dict[str, Any]:
    """断链审计（#336 纯函数）：正面积交叠=连通；返回主分量与孤儿清单。
    孤儿 >0 → 建模面断链 → fail-fast 不起跑。"""
    names = list(rects)
    parent: dict[str, str] = {n: n for n in names}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if rect_overlap_area(rects[a], rects[b]) > min_area:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra
    comps: dict[str, list[str]] = {}
    for n in names:
        comps.setdefault(find(n), []).append(n)
    main_root = max(comps, key=lambda r: len(comps[r]))
    orphans = sorted(n for r, members in comps.items()
                     if r != main_root for n in members)
    return {"main": sorted(comps[main_root]), "orphans": orphans,
            "n_components": len(comps)}


def _point_on_rect(pt: tuple[float, float], rect: Rect,
                   tol: float = 1e-6) -> bool:
    return (rect[0] - tol <= pt[0] <= rect[2] + tol
            and rect[1] - tol <= pt[1] <= rect[3] + tol)


def audit_geometry(rects: dict[str, Rect],
                   port_points: dict[str, tuple[float, float]]) -> dict[str, Any]:
    """几何连通审计（#336 纯函数，多岛拓扑语义）：
    - 每个端口馈点/集总口触点必须落在某块金属上（ports_missing_metal）；
    - 每个连通分量必须含 ≥1 个端口触点（floating_components=悬空金属岛，
      fail）。marchand 类拓扑 DC 上天然 3 岛（主岛 P1/副 1 岛 P2/副 2 岛
      P3，经场耦合与过孔地短路连通），"单主分量"判据对它不成立——改判
      "无端口岛=断链"。"""
    conn = audit_connectivity(rects)
    # 重建分量归属（main/orphans 只是名单，按根重算一次）
    parent: dict[str, str] = {n: n for n in rects}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    names = list(rects)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if rect_overlap_area(rects[a], rects[b]) > 1e-9:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra
    comps: dict[str, list[str]] = {}
    for n in names:
        comps.setdefault(find(n), []).append(n)
    missing = [name for name, pt in port_points.items()
               if not any(_point_on_rect(pt, rects[n]) for n in names)]
    floating: list[str] = []
    for root, members in comps.items():
        hit = any(any(_point_on_rect(pt, rects[m]) for m in members)
                  for pt in port_points.values())
        if not hit:
            floating.append(root)
    return {"connectivity": conn,
            "ports_missing_metal": sorted(missing),
            "floating_components": sorted(floating),
            "n_components": len(comps),
            "ok": (not missing) and (not floating)}


def audit_lumped_bridge(sheet: Rect, axis: str,
                        metal_rects: dict[str, Rect],
                        tol: float = 1e-6) -> dict[str, Any]:
    """集总元件桥审计：两端各触一块金属（边接触 ≤tol）；且与任何 PEC 薄片
    零面积交叠（#191：重叠区电阻被 PEC 击败）。"""
    lo = sheet[0] if axis == "x" else sheet[1]
    hi = sheet[2] if axis == "x" else sheet[3]
    touched = {"lo": False, "hi": False}
    overlap_fail: list[str] = []
    for name, mr in metal_rects.items():
        if rect_overlap_area(sheet, mr) > 1e-9:
            overlap_fail.append(name)
            continue
        if axis == "x":
            proj = min(sheet[3], mr[3]) - max(sheet[1], mr[1])
            if proj > tol and abs(mr[2] - lo) <= tol:
                touched["lo"] = True
            if proj > tol and abs(mr[0] - hi) <= tol:
                touched["hi"] = True
        else:
            proj = min(sheet[2], mr[2]) - max(sheet[0], mr[0])
            if proj > tol and abs(mr[3] - lo) <= tol:
                touched["lo"] = True
            if proj > tol and abs(mr[1] - hi) <= tol:
                touched["hi"] = True
    return {"ok": all(touched.values()) and not overlap_fail,
            "touched": touched, "pec_overlap": overlap_fail,
            "axis": axis, "end_lo": lo, "end_hi": hi}


# ═══════════════ 席上下文与几何面（名义几何单一事实源现算，零手抄 #1c）══════════════

def seat_context(seat_name: str, port_form: str | None = None) -> dict[str, Any]:
    """模板名义参数/基板单一事实源（TEMPLATE_META/TEMPLATE_NOMINAL /
    marchand_two_section_nominal 现算，禁手抄）。port_form（S2 决策 2 发射
    面）只进 marchand ctx（layout 端口形态分派消费；None=席 spec 缺省）。"""
    seat = SEATS[seat_name]
    ctx: dict[str, Any] = {"seat": seat_name, "f0_ghz": seat["f0_ghz"]}
    if seat_name == "marchand_balun":
        from rfauto.core.slotline_transitions import marchand_two_section_nominal

        d = marchand_two_section_nominal()
        nom = d.nominal_params()
        ctx.update({
            "w_mm": float(nom["w_mm"]), "s_mm": float(nom["s_mm"]),
            "l_sect_mm": float(nom["l_sect_mm"]),
            "w_feed_mm": float(nom["w_feed_mm"]),
            "w_bal_mm": float(nom["w_bal_line_mm"]),
            "r_bal_se_ohm": float(nom["r_bal_se_ohm"]),
            "z_unbal_ohm": float(d.z_unbal_ohm),
            "h_mm": 1.524, "er": 3.66, "tan_d": 0.0037,
            "via_side_mm": 0.25,
            "port_form": resolve_marchand_port_form(seat_name, port_form),
            "provenance": "core/slotline_transitions.marchand_two_section_nominal()"
                          "（=runs/smoke_marchand_2sect/design.json 同源）",
        })
        return ctx
    from rfauto.adapters.openems_templates import _DEFAULT_SUB, TEMPLATE_NOMINAL

    template = seat["template"]
    ctx.update({
        "nominal_params": dict(TEMPLATE_NOMINAL[template]),
        "h_mm": float(_DEFAULT_SUB["h_mm"]),
        "er": float(_DEFAULT_SUB["er"]),
        "tan_d": float(_DEFAULT_SUB["tan_d"]),
        "provenance": f"docs/templates/{template}/meta.yaml + openems_templates."
                      "_DEFAULT_SUB（渲染同源）",
    })
    return ctx


def _layout_stepped(ctx: dict) -> dict[str, Any]:
    p = ctx["nominal_params"]
    z1 = float(p["z1_width_mm"])
    z2 = float(p["z2_width_mm"])
    seg = float(p["seg_len_mm"])
    n = int(p["n_segments"])
    total = n * seg
    rects: dict[str, Rect] = {"feed_in": (-z1 / 2, -BOARD_MM, z1 / 2, -total / 2)}
    for i in range(n):
        w = z1 if i % 2 == 0 else z2
        y0 = -total / 2 + i * seg
        rects[f"seg_{i}"] = (-w / 2, y0, w / 2, y0 + seg)
    rects["feed_out"] = (-z1 / 2, total / 2, z1 / 2, BOARD_MM)
    pads = [{"a": "feed_in", "b": "seg_0", "axis": "y"}]
    for i in range(n - 1):
        pads.append({"a": f"seg_{i}", "b": f"seg_{i + 1}", "axis": "y"})
    pads.append({"a": f"seg_{n - 1}", "b": "feed_out", "axis": "y"})
    port_w = max(4.0 * z1, 1.2)          # criteria §2 绝对最小尺寸约束
    port_h = max(3.0, 3.0 * ctx["h_mm"])
    ports = [
        {"name": "P1", "edge_y": -BOARD_MM, "center_x": 0.0, "w": port_w,
         "h": port_h},
        {"name": "P2", "edge_y": BOARD_MM, "center_x": 0.0, "w": port_w,
         "h": port_h},
    ]
    return {"rects": rects, "pads": pads, "ports": ports, "lumped": [],
            "board": BOARD_MM, "air_top": AIR_TOP_MM}


def _layout_coupled(ctx: dict) -> dict[str, Any]:
    p = ctx["nominal_params"]
    lw = float(p["line_w_mm"])
    gap = float(p["gap_mm"])
    cl = float(p["coupled_len_mm"])
    xl0, xl1 = -lw - gap / 2, -gap / 2          # 左线 x 跨
    xr0, xr1 = gap / 2, gap / 2 + lw            # 右线 x 跨
    rects: dict[str, Rect] = {
        "line_left": (xl0, -cl / 2, xl1, cl / 2),
        "line_right": (xr0, -cl / 2, xr1, cl / 2),
        "feed_left_in": (xl0, -BOARD_MM, xl1, -cl / 2),
        "feed_left_out": (xl0, cl / 2, xl1, BOARD_MM),
        "feed_right_in": (xr0, -BOARD_MM, xr1, -cl / 2),
    }
    pads = [
        {"a": "feed_left_in", "b": "line_left", "axis": "y"},
        {"a": "feed_left_out", "b": "line_left", "axis": "y"},
        {"a": "feed_right_in", "b": "line_right", "axis": "y"},
    ]
    # 相邻端口不重叠约束：两线中心距 w+gap，逐端口最大可行宽=w+gap−间隙余量
    # （<4w 惯例；#191 余量依赖积分线+高度；实现注记如实落档）。
    port_w = max(lw + gap - PORT_SPLIT_MARGIN_MM, 1.2)
    port_h = max(3.0, 3.0 * ctx["h_mm"])
    ports = [
        {"name": "P1", "edge_y": -BOARD_MM, "center_x": 0.5 * (xl0 + xl1),
         "w": port_w, "h": port_h},
        {"name": "P2", "edge_y": BOARD_MM, "center_x": 0.5 * (xl0 + xl1),
         "w": port_w, "h": port_h},
        {"name": "P3", "edge_y": -BOARD_MM, "center_x": 0.5 * (xr0 + xr1),
         "w": port_w, "h": port_h},
    ]
    return {"rects": rects, "pads": pads, "ports": ports, "lumped": [],
            "board": BOARD_MM, "air_top": AIR_TOP_MM,
            "notes": [f"coupled_line 相邻端口截面 {port_w:.3f}mm（<4w 惯例；"
                      "两线中心距 w+gap 相邻端口不重叠约束下最大可行宽，"
                      "criteria §2 实现细节增补，Round 记录可复核）"]}


def _layout_wilkinson(ctx: dict) -> dict[str, Any]:
    p = ctx["nominal_params"]
    w_in = float(p["shunt_w_mm"])
    w_arm = float(p["series_w_mm"])
    l_arm = float(p["arm_len_mm"])
    gap = 8.0
    xa = gap / 2 + w_arm / 2
    y_t = -30.0
    y_end = y_t + l_arm
    rects: dict[str, Rect] = {
        "t_junction": (-xa - w_arm / 2, y_t, xa + w_arm / 2, y_t + w_arm),
        "arm_left": (-xa - w_arm / 2, y_t, -xa + w_arm / 2, y_end),
        "arm_right": (xa - w_arm / 2, y_t, xa + w_arm / 2, y_end),
        "feed_in": (-w_in / 2, -BOARD_MM, w_in / 2, y_t),
        "feed_out_left": (-xa - w_in / 2, y_end, -xa + w_in / 2, BOARD_MM),
        "feed_out_right": (xa - w_in / 2, y_end, xa + w_in / 2, BOARD_MM),
    }
    pads = [
        {"a": "feed_in", "b": "t_junction", "axis": "y"},
        {"a": "feed_out_left", "b": "arm_left", "axis": "y"},
        {"a": "feed_out_right", "b": "arm_right", "axis": "y"},
    ]
    port_w = max(4.0 * w_in, 1.2)
    port_h = max(3.0, 3.0 * ctx["h_mm"])
    ports = [
        {"name": "P1", "edge_y": -BOARD_MM, "center_x": 0.0, "w": port_w,
         "h": port_h},
        {"name": "P2", "edge_y": BOARD_MM, "center_x": -xa, "w": port_w,
         "h": port_h},
        {"name": "P3", "edge_y": BOARD_MM, "center_x": xa, "w": port_w,
         "h": port_h},
    ]
    # 100Ω 隔离电阻：XY 片精确跨两臂内缘（#191：与 PEC 薄片零面积交叠），
    # 电流沿 x（引擎 LumpedElement ny=x 同位同向）。
    r_sheet: Rect = (-(xa - w_arm / 2), y_end - w_arm / 2,
                     xa - w_arm / 2, y_end + w_arm / 2)
    lumped = [{"name": "Riso", "kind": "rlc", "r_ohm": 100.0, "sheet": r_sheet,
               "axis": "x", "contact_metal": ["arm_left", "arm_right"],
               "note": "Lumped RLC Parallel R=100Ω start_direction=XPos"
                       "（same_geometry_arbitration 先例 API；#191 无 PEC 交叠）"}]
    return {"rects": rects, "pads": pads, "ports": ports, "lumped": lumped,
            "board": BOARD_MM, "air_top": AIR_TOP_MM}


def _layout_marchand(ctx: dict) -> dict[str, Any]:
    """两节 Marchand（锚 B 实码同构，几何值 ctx 单源现算零手抄）。

    主线贯通 x∈[x0,2ℓ]（节 1 远端↔节 2 近端=结点；节 2 远端=微带开路端），
    节 1 副线 +y 侧 x∈[0,ℓ]（近端过孔短路）、节 2 副线 −y 侧 x∈[ℓ,2ℓ]
    （远端过孔短路，关于主线中心 y=w/2 镜像，#310④）；平衡侧按 ctx 端口
    形态（S2 决策 2 发射面）分派：
    - lumped140（缺省，已落档行为零变化）：140Ω 馈线（面积重叠 w/2 内建后
      unite）+ P2/P3 集总口；
    - wave2mode：馈线延伸到域界（端口面贴 ±y 边界；#174 馈线止于域中=
      开路 stub 反例规避）+ PA/PB 2 模大截面波端口（criteria §2 预声明
      主判形态、锚 A 同款横向 ±12mm/全高、modes=2 积分线显式 [[S,S],[E,E]]
      #308 格式）；140Ω 集总端接移除（端接口径→端口形态单变量）。
    P1 波端口落基板 −x 边（主线延长到边，|S11| 幅度对参考面平移不变）。
    """
    w, s, ell = ctx["w_mm"], ctx["s_mm"], ctx["l_sect_mm"]
    wb = ctx["w_bal_mm"]
    lf = MARCHAND_FEED_LEN_MM
    via = ctx["via_side_mm"]
    ovl = 0.5 * w                 # 馈线-副线面积重叠（锚 B 实证仅共边不合并）
    y_out = 2.0 * w + s           # 节 1 副线外缘
    y_out2 = w + s                # 节 2 副线外缘 |y|（关于主线中心镜像口径）
    x_tot = 2.0 * ell
    x0 = -MARCHAND_PAD_MM         # 基板/主线 −x 边（P1 端口面）
    sub_half_y = y_out + lf + MARCHAND_SUB_MARGIN_MM
    form = resolve_marchand_port_form("marchand_balun", ctx.get("port_form"))
    rects: dict[str, Rect] = {
        "MainLine": (x0, 0.0, x_tot, w),
        "SecLine1": (0.0, w + s, ell, y_out),
        "SecLine2": (ell, -y_out2, x_tot, -s),
    }
    port_h = max(3.0, 3.0 * ctx["h_mm"])
    port_w = max(4.0 * w, 1.2)
    ports = [
        {"name": "P1", "edge": ("x", x0), "center_y": 0.5 * w,
         "w": port_w, "h": port_h},
    ]
    notes_form: str
    if form == "wave2mode":
        rects["FeedA"] = (ell - wb, y_out - ovl, ell, sub_half_y)
        rects["FeedB"] = (ell, -sub_half_y, ell + wb, -y_out2 + ovl)
        z_top = MARCHAND_AIR_TOP_MM      # GAir 域顶（build_frame 口径 z 0→air_top）
        lat = MARCHAND_W2M_LATERAL_MM
        ports += [
            {"name": "PA", "edge_y": sub_half_y,
             "center_x": ell - wb / 2.0, "w": 2.0 * lat, "h": z_top,
             "modes": 2},
            {"name": "PB", "edge_y": -sub_half_y,
             "center_x": ell + wb / 2.0, "w": 2.0 * lat, "h": z_top,
             "modes": 2},
        ]
        lumped: list[dict[str, Any]] = []
        notes_form = (
            "port_form=wave2mode：平衡侧=2 模大截面波端口（criteria §2 预声明"
            "主判形态；hfss_marchand_anchor (a) 同款横向 ±12mm/全高、modes=2、"
            "积分线显式 [[S,S],[E,E]] #308 格式，偶/奇按 εeff 较高识别 #307）；"
            "馈线延伸至域界（端口面贴 ±y 边界，#174 反例规避）；140Ω 集总端接"
            "移除——端接口径→端口形态单变量对照（S2 审计决策 2 发射面）")
    else:
        rects["FeedA"] = (ell - wb, y_out - ovl, ell, y_out + lf)
        rects["FeedB"] = (ell, -y_out2 - lf, ell + wb, -y_out2 + ovl)
        lumped = [
            {"name": "P2", "kind": "port", "r_ohm": ctx["r_bal_se_ohm"],
             "sheet": (ell - wb, y_out + lf, ell, y_out + lf), "axis": "y",
             "contact_point": (ell - wb / 2, y_out + lf),
             "note": "XZ 薄片 z 0→h sizes=[h, wb]（#310④ 轴向循环映射）"},
            {"name": "P3", "kind": "port", "r_ohm": ctx["r_bal_se_ohm"],
             "sheet": (ell, -y_out2 - lf, ell + wb, -y_out2 - lf), "axis": "y",
             "contact_point": (ell + wb / 2, -y_out2 - lf),
             "note": "XZ 薄片 z 0→h"},
        ]
        notes_form = ("平衡侧口径=P2/P3 140Ω 集总（OE smoke 同端口同几何）；"
                      "criteria §2 预声明 2 模端口主判因平衡端子非耦合对"
                      "（隔主线）不可落位，实现偏差见 implementation_notes")
    vias = [
        {"name": "Via1", "x0": 0.0, "y_c": 1.5 * w + s, "side": via},
        {"name": "Via2", "x0": x_tot - via, "y_c": -(0.5 * w + s), "side": via},
    ]
    return {"rects": rects, "pads": [], "ports": ports, "lumped": lumped,
            "vias": vias, "board": None, "air_top": MARCHAND_AIR_TOP_MM,
            "sub_half_y": sub_half_y, "pad_x": MARCHAND_PAD_MM,
            "notes": [notes_form]}


def _layout_gysel(ctx: dict) -> dict[str, Any]:
    """Gysel L-jog 六节环（`_gysel_layout` 单源现算零手抄；criteria §2）。

    下边双 70.7Ω 臂（P1 中点分叉、角=P2/P3）+ 左右 50Ω 隔离竖直段 YJ +
    顶端 L-jog 横移（jog=|arm_len−iso_len|，竖直+横移=λ/4 保电长）+ 顶边
    50Ω λ/2 桥带（跨度 2·iso_len 精确，中点开路）。Δ1/Δ2（x=±iso_len）各
    接 50Ω **竖直** Lumped RLC 端接（导带点↔地：XZ 薄片 sizes=[h(→Z),
    w(→X)] #310④ 轴向映射、Gravity.ZPos 电流——mapes bleed 先例 API）。
    三端口全部 y=−60 板边（P1 x=0、P2/P3 x=∓XA，OE MSLPort 同位同宽）；
    馈线延伸到臂中线 y=0（OE MSLPort stop 同口径）→ 臂/隔离竖直段/jog/
    桥带片间自然面积交叠，馈线↔竖直段 y=0 缝由 edge_touch_pads 垫连。
    """
    from rfauto.adapters.openems_templates import _gysel_layout

    g = _gysel_layout(dict(ctx["nominal_params"]))
    wa, wf, xa = float(g["wa"]), float(g["wf"]), float(g["xa"])
    yj, xb = float(g["yj"]), float(g["xb"])
    rects: dict[str, Rect] = {
        "feed_in": (-wf / 2, -BOARD_MM, wf / 2, 0.0),
        "arm_bottom": (-xa, -wa / 2, xa, wa / 2),
        "iso_left_v": (-xa - wf / 2, 0.0, -xa + wf / 2, yj),
        "iso_right_v": (xa - wf / 2, 0.0, xa + wf / 2, yj),
        "jog_left": (min(-xa, -xb) - wf / 2, yj - wf / 2,
                     max(-xa, -xb) + wf / 2, yj + wf / 2),
        "jog_right": (min(xa, xb) - wf / 2, yj - wf / 2,
                      max(xa, xb) + wf / 2, yj + wf / 2),
        "bridge_top": (-xb - wf / 2, yj - wf / 2, xb + wf / 2, yj + wf / 2),
        "feed_out_left": (-xa - wf / 2, -BOARD_MM, -xa + wf / 2, 0.0),
        "feed_out_right": (xa - wf / 2, -BOARD_MM, xa + wf / 2, 0.0),
    }
    pads = edge_touch_pads(rects)
    port_w = max(4.0 * wf, 1.2)
    port_h = max(3.0, 3.0 * ctx["h_mm"])
    ports = [
        {"name": "P1", "edge_y": -BOARD_MM, "center_x": 0.0, "w": port_w,
         "h": port_h},
        {"name": "P2", "edge_y": -BOARD_MM, "center_x": -xa, "w": port_w,
         "h": port_h},
        {"name": "P3", "edge_y": -BOARD_MM, "center_x": xa, "w": port_w,
         "h": port_h},
    ]
    # Δ1/Δ2 竖直负载薄片：x 跨=线宽（OE LumpedElement 盒 x 跨 W_F 同位）、
    # y=YJ 过桥带中心、z 0→h（底缘触 GGnd、顶缘触桥带，#191 异面零交叠）。
    lumped = [
        {"name": "Rload1", "kind": "rlc", "r_ohm": 50.0, "plane": "xz",
         "sheet": (-xb - wf / 2, yj, -xb + wf / 2, yj),
         "contact_point": (-xb, yj),
         "note": "Δ1 50Ω 竖直 Lumped RLC：XZ 薄片 sizes=[h(→Z), w(→X)]、"
                 "Gravity.ZPos（mapes bleed 先例 API；#191 与 XY PEC 异面"
                 "零面积交叠）"},
        {"name": "Rload2", "kind": "rlc", "r_ohm": 50.0, "plane": "xz",
         "sheet": (xb - wf / 2, yj, xb + wf / 2, yj),
         "contact_point": (xb, yj),
         "note": "Δ2 50Ω 竖直 Lumped RLC（同 Rload1 口径）"},
    ]
    return {"rects": rects, "pads": pads, "ports": ports, "lumped": lumped,
            "board": BOARD_MM, "air_top": AIR_TOP_MM,
            "notes": [
                f"L-jog 等长变体：YJ={yj:.4f}mm（=iso_len−|arm_len−iso_len|）、"
                f"Δ 节点 x=±{xb:.4f}mm（桥带 2·iso_len=λ/2 精确）；"
                "criteria §2 '不设辐射边界'与被引锚实码（辐射开放面）矛盾——"
                "跟随 marchand 席同款先例（ASSIGN_RADIATION 单开关可翻字面）；"
                "jog 顶边带缘入网语义在 HFSS 侧=自然几何（无网格缝合需求，"
                "如实注记）",
            ]}


def _layout_branchline(ctx: dict) -> dict[str, Any]:
    """标准角馈正方环 branchline（openems_templates geometry_spec 同式现算；
    criteria §2）。横臂 series_w（35.35Ω）/竖臂+馈线 shunt_w（50Ω），环边
    =arm_len；四角 50Ω 馈线至板边 ±60mm，4 端口（P1 入左下/P2 直通右下/
    P3 耦合右上/P4 隔离左上，OE 端口序同源）。环片间自然面积交叠；馈线
    p1/p3 与臂仅共边 → edge_touch_pads 垫连（#310④/#336，criteria §2
    "每个拼接处 0.02mm 重叠垫"）；无切角（OE 名义同源，斜切可选未采）。
    """
    p = ctx["nominal_params"]
    arm = float(p["arm_len_mm"])
    sw = float(p["series_w_mm"])
    shw = float(p["shunt_w_mm"])
    half = arm / 2.0
    rects: dict[str, Rect] = {
        "arm_top": (-half - shw / 2, half - sw / 2, half + shw / 2,
                    half + sw / 2),
        "arm_bottom": (-half - shw / 2, -half - sw / 2, half + shw / 2,
                       -half + sw / 2),
        "arm_left": (-half - shw / 2, -half, -half + shw / 2, half),
        "arm_right": (half - shw / 2, -half, half + shw / 2, half),
        "feed_p1": (-half - shw / 2, -BOARD_MM, -half + shw / 2, -half),
        "feed_p2": (half, -half - shw / 2, BOARD_MM, -half + shw / 2),
        "feed_p3": (half - shw / 2, half, half + shw / 2, BOARD_MM),
        "feed_p4": (-BOARD_MM, half - shw / 2, -half, half + shw / 2),
    }
    pads = edge_touch_pads(rects)
    port_w = max(4.0 * shw, 1.2)
    port_h = max(3.0, 3.0 * ctx["h_mm"])
    ports = [
        {"name": "P1", "edge_y": -BOARD_MM, "center_x": -half, "w": port_w,
         "h": port_h},
        {"name": "P2", "edge": ("x", BOARD_MM), "center_y": -half,
         "w": port_w, "h": port_h},
        {"name": "P3", "edge_y": BOARD_MM, "center_x": half, "w": port_w,
         "h": port_h},
        {"name": "P4", "edge": ("x", -BOARD_MM), "center_y": half,
         "w": port_w, "h": port_h},
    ]
    return {"rects": rects, "pads": pads, "ports": ports, "lumped": [],
            "board": BOARD_MM, "air_top": AIR_TOP_MM,
            "notes": [
                f"8 片正方环（边长 {arm}mm；横臂 {sw}mm/竖臂+馈 {shw}mm）；"
                f"共边缝自动垫 {len(pads)} 处（feed_p1↔arm_left/"
                "feed_p3↔arm_right，环片角部为自然面积交叠——审计实测为准）；"
                "criteria §2 '不设辐射边界'与被引锚实码矛盾——marchand 席"
                "同款处理（ASSIGN_RADIATION 单开关可翻字面）；无集总元件",
            ]}


def _layout_patch_array(ctx: dict, template: str) -> dict[str, Any]:
    """C2 阵列 HFSS 面（`_arr_layout` 渲染单一事实源消费，零手抄；
    criteria §2 席 6/7 共用口径）。

    全部金属盒（贴片 3 盒/缺口内馈段/λ/4 70.7Ω 变换树/50Ω 透明连线/走廊
    折弯链）零厚 @z=h 逐一转 XY 薄片；共边缝由 edge_touch_pads 逐对垫连
    （数十片 unite，#310④/#336）。底探针=**竖直 XZ LumpedPort**（地板↔
    导带，marchand 锚先例 API：薄片宽=馈线宽 fw、z 0→h；引擎探针盒
    ±0.1×±1.0mm 同位同 y——#257 探针盒 ≥2 格/#283 中线落网格为引擎网格
    语义，HFSS 自适应网格如实声明）。空气域=板全域 footprint + 顶 λ0/4
    （radiate_open_faces 面心过滤 → 顶+四侧 5 面辐射边界，底=PEC 地不
    入辐射面；#356③ 路径分岔：radiation 边界非阻抗壳）。
    """
    from rfauto.adapters.openems_templates import _arr_layout

    arr = _arr_layout(template, dict(ctx["nominal_params"]))
    rects: dict[str, Rect] = {
        name: (float(x0), float(y0), float(x1), float(y1))
        for _prop, name, x0, y0, _z0, x1, y1, _z1 in arr["boxes"]}
    pads = edge_touch_pads(rects)
    port = arr["ports"][0]                     # 单底探针 LumpedPort（单源）
    x_probe = 0.5 * (float(port["start_mm"][0]) + float(port["stop_mm"][0]))
    y_probe = 0.5 * (float(port["start_mm"][1]) + float(port["stop_mm"][1]))
    fw = float(ctx["nominal_params"]["feed_w_mm"])
    probe = {
        "name": "P1", "kind": "port", "r_ohm": float(port["R"]),
        "sheet": (x_probe - fw / 2, y_probe, x_probe + fw / 2, y_probe),
        "contact_point": (x_probe, y_probe),
        "note": "底探针 LumpedPort 竖直 XZ 薄片 z 0→h sizes=[h(→Z), fw(→X)]"
                f"（marchand 锚先例；引擎探针盒 {port['start_mm'][0]}→"
                f"{port['stop_mm'][0]}mm 同位同 x={x_probe:.4f}/"
                f"y={y_probe:.4f}，薄片宽取馈线"
                "宽 fw=marchand 实码口径；#257/#283 为引擎网格语义如实声明）",
    }
    if template == "patch_array_2x2":
        probe["note"] += "；顶排折弯链（走廊上行+上方内折+自上向下入缺口）" \
                         "逐缝自动垫连+镜像语义审计（_layout 内 fail-fast）"
    lumped = [probe]
    air_top = 0.25 * C0 / (float(ctx["f0_ghz"]) * 1e9) * 1e3   # λ0/4（mm）
    mirror = _array_mirror_audit(template, rects, ctx) \
        if template == "patch_array_2x2" else None
    notes = [
        f"金属 {len(rects)} 片单源消费 _arr_layout（贴片 3 盒/元+变换树+"
        f"透明连线）；共边缝自动垫 {len(pads)} 处 unite；空气顶 "
        f"λ0/4={air_top:.3f}mm@{ctx['f0_ghz']}GHz、四侧=板边（阵列辐射缘"
        "到板边 ≥λ0/4 同口径）；方向图归 OTA 线本席不判（criteria §1）",
    ]
    if mirror is not None:
        notes.append(
            "顶排折弯链镜像语义审计 PASS（#310④：底排缺口 −y 自下入/顶排 +y "
            "自上入，逐盒核对 stub 方向与缺口侧，渲染单源消费+审计双确认）")
    return {"rects": rects, "pads": pads, "ports": [], "lumped": lumped,
            "board": BOARD_MM, "air_top": air_top, "notes": notes,
            "mirror_audit": mirror}


def _array_mirror_audit(template: str, rects: dict[str, Rect],
                        ctx: dict) -> dict[str, Any]:
    """2×2 顶排折弯链镜像语义审计（criteria §2，#310④ 镜像坐标教训）：
    底排缺口朝 −y（stub 自下入）与顶排缺口朝 +y（stub 自上入）关于栅格
    旋转对称——逐盒核对 stub 方向/缺口侧/贴片跨度，违者 fail-fast。"""
    del template
    l_mm = float(ctx["nominal_params"]["elem_len_mm"])
    d_in = float(ctx["nominal_params"]["elem_feed_mm"])
    per_col: dict[str, dict[str, bool]] = {}
    for col in ("l", "r"):
        b_l, t_l = rects[f"e_b_{col}_l"], rects[f"e_t_{col}_l"]
        sb, st = rects[f"e_b_{col}_stub"], rects[f"e_t_{col}_stub"]
        cb, ct = rects[f"e_b_{col}_c"], rects[f"e_t_{col}_c"]
        per_col[col] = {
            "stub_bottom_at_mouth_lo": abs(sb[1] - b_l[1]) <= 1e-9,
            "stub_bottom_into_patch": abs((sb[3] - sb[1]) - d_in) <= 1e-9,
            "stub_top_at_mouth_hi": abs(st[3] - t_l[3]) <= 1e-9,
            "stub_top_into_patch": abs((st[3] - st[1]) - d_in) <= 1e-9,
            "notch_bottom_row_at_lo": abs(cb[1] - (b_l[1] + d_in)) <= 1e-9,
            "notch_top_row_at_hi": abs(ct[3] - (t_l[3] - d_in)) <= 1e-9,
            "elem_span_eq_L": abs((b_l[3] - b_l[1]) - l_mm) <= 1e-9,
        }
    audit = {"ok": all(all(v.values()) for v in per_col.values()),
             "per_column": per_col}
    if not audit["ok"]:
        raise ValueError(
            f"patch_array_2x2 顶排折弯链镜像语义审计 fail（#310④）：{audit}")
    return audit


_LAYOUTS: dict[str, Callable[[dict], dict[str, Any]]] = {
    "stepped_impedance": _layout_stepped,
    "coupled_line": _layout_coupled,
    "wilkinson": _layout_wilkinson,
    "marchand_balun": _layout_marchand,
    "gysel": _layout_gysel,
    "branchline": _layout_branchline,
    "patch_array_1x4": lambda ctx: _layout_patch_array(ctx, "patch_array_1x4"),
    "patch_array_2x2": lambda ctx: _layout_patch_array(ctx, "patch_array_2x2"),
}


def seat_layout(seat_name: str, ctx: dict) -> dict[str, Any]:
    """席几何面：垫前矩形→0.02mm 重叠垫→连通/端口/集总审计一次完成
    （#336 fail-fast 数据面在建模前跑）。"""
    lay = _LAYOUTS[seat_name](ctx)
    padded = apply_pads(lay["rects"], lay["pads"])
    port_points: dict[str, tuple[float, float]] = {}
    for pt in lay["ports"]:
        if "edge_y" in pt:
            port_points[pt["name"]] = (float(pt["center_x"]), float(pt["edge_y"]))
        else:
            port_points[pt["name"]] = (float(pt["edge"][1]),
                                       float(pt["center_y"]))
    for lump in lay.get("lumped", []):
        cp = lump.get("contact_point")
        if cp is not None:
            port_points[lump["name"]] = (float(cp[0]), float(cp[1]))
    audit = audit_geometry(padded, port_points)
    lay["padded_rects"] = padded
    lay["audit"] = audit
    for lump in lay.get("lumped", []):
        if lump.get("kind") != "rlc":
            continue
        if lump.get("plane") == "xz":
            # 竖直薄片（gysel 50Ω 端接）：与 XY PEC 异面零面积交叠（#191），
            # 桥接语义=顶缘 z=h 触导带+底缘 z=0 触地（mapes bleed 先例）；
            # 触点落金属由 port_points 通道（上方 audit_geometry）兜底复核。
            cp = lump["contact_point"]
            on_metal = any(_point_on_rect(cp, r) for r in padded.values())
            lump["audit"] = {"ok": bool(on_metal), "mode": "xz_shunt",
                             "contact_on_metal": bool(on_metal),
                             "pec_overlap": [],
                             "note": "竖直薄片与 XY PEC 异面（#191 零面积"
                                     "交叠）；顶缘触导带/底缘触地"}
            continue
        metal = {k: padded[k] for k in lump.get("contact_metal", [])}
        sh = lump["sheet"]
        lump["audit"] = audit_lumped_bridge(sh, lump["axis"], metal)
    return lay


# ═══════════════ OE 参考值解析（单一事实源 / 闭式回退封顶 AGREE_HFSS）══════════════

def _resolve_oe_sparams_csv(seat: dict,
                            notes: list[str] | None = None
                            ) -> tuple[dict, str, np.ndarray | None]:
    """oe_nominal sparams.csv（#314 掩码解析器单源）→ 同口径指标。

    notes（review-slice13 P1-1）：透传 extract_metrics 提取侧注记出口——OE
    侧 censored（如 coupled 峰带心触窗沿）不再零出口，双侧注记随
    implementation_notes 落 verdict。
    """
    from rfauto.service.health_service import _parse_sparams_csv_masked

    for rel in seat["oe"]["candidates"]:
        path = REPO / rel
        if not path.exists():
            continue
        loaded = _parse_sparams_csv_masked(path)
        if loaded is None:
            continue
        freq_hz, s, mask = loaded
        return (extract_metrics(freq_hz, s, seat, mask, notes=notes),
                str(path), mask)
    raise FileNotFoundError(
        f"OE sparams 缺失：{seat['oe']['candidates']}（席 {seat['template']}）")


def _resolve_oe_touchstone(seat: dict,
                           notes: list[str] | None = None
                           ) -> tuple[dict, str, None]:
    """OE touchstone → 同口径指标（notes 透传同 _resolve_oe_sparams_csv，
    review-slice13 P1-1）。"""
    import skrf

    for rel in seat["oe"]["candidates"]:
        path = REPO / rel
        if not path.exists():
            continue
        net = skrf.Network(str(path))
        return (extract_metrics(net.frequency.f.astype(float),
                                np.asarray(net.s, dtype=complex), seat, None,
                                notes=notes),
                str(path), None)
    raise FileNotFoundError(f"OE touchstone 缺失：{seat['oe']['candidates']}")


def _resolve_oe_verdict_fields(seat: dict) -> tuple[dict, str, None]:
    path = REPO / seat["oe"]["path"]
    data = json.loads(path.read_text(encoding="utf-8"))
    vals: dict[str, Any] = {}
    for metric, dotted in seat["oe"]["fields"].items():
        node: Any = data
        for part in dotted.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                node = None
                break
        vals[metric] = None if node is None else float(node)
    return vals, str(path), None


def _resolve_oe_constants(seat: dict) -> tuple[dict, str, None]:
    return dict(seat["oe"]["constants"]), str(seat["oe"]["provenance"]), None


def _closed_form_refs(kind: str, seat: dict) -> dict[str, Any]:
    """闭式半集回退（criteria §1b；core 单源现算）。返回指标值 + x_ref 解析。"""
    out: dict[str, Any] = {}
    if kind == "coupled_quarter_wave":
        from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

        nom = seat["oe"].get("_nom")
        lw = float((nom or {}).get("line_w_mm", 1.0))
        gap = float((nom or {}).get("gap_mm", 0.5))
        cl = float((nom or {}).get("coupled_len_mm", 20.0))
        ze, zo, ee, eo = coupled_microstrip_even_odd_ohm(lw, gap, 2.4, 3.66, 0.508)
        eff = 0.5 * (ee + eo)
        f_qw = C0 / (4.0 * cl * 1e-3 * math.sqrt(eff)) / 1e9
        out["f_peak_ghz"] = f_qw
        out["coupling_at_f0_db"] = 20.0 * math.log10(abs((ze - zo) / (ze + zo)))
        out["x_ref_f_peak_ghz"] = (f_qw * 0.97, f_qw * 1.03)
        out["kj"] = {"z0e_ohm": ze, "z0o_ohm": zo, "ere_e": ee, "ere_o": eo,
                     "note": "闭式 λ/4@mean(εeff_e,εeff_o)（criteria §4 闭式裁判）"}
    elif kind == "wilkinson_hj":
        from rfauto.core.synthesis import Stackup, forward_z0

        nom = seat["oe"].get("_nom")
        w_arm = float((nom or {}).get("series_w_mm", 0.604))
        l_arm = float((nom or {}).get("arm_len_mm", 18.1))
        _z0, eff = forward_z0(w_arm, 2.5, Stackup(name="b2a", epsilon_r=3.66,
                                                  thickness_mm=0.508))
        out["f_match_ghz"] = C0 / (4.0 * l_arm * 1e-3 * math.sqrt(eff)) / 1e9
        out["note"] = "HJ λ/4@εeff(0.604mm)（criteria §1b 闭式回退）"
    elif kind == "stepped_cascade":
        out["note"] = ("段级联闭式半集（criteria §1b：z1/z2 HJ 阻抗+5 段 ABCD/"
                       "skrf 级联）——回退路径登记；verdict 封顶 AGREE_HFSS，"
                       "闭式级联 S 参数实现在发射前批补（实现待续）")
    else:
        raise ValueError(f"_closed_form_refs: 未知闭式回退 kind {kind!r}")
    return out


def resolve_oe_refs(seat_name: str) -> dict[str, Any]:
    """OE 参考值解析：产物在档→同口径提取；缺失→闭式回退+cap=AGREE_HFSS
    （criteria §1b）；闭式也不可得→空值（指标 UNKNOWN 如实）。

    返回 dict 恒带 ``notes``（review-slice13 P1-1）：sparams_csv/touchstone
    两条现算路径的提取侧 censored 注记（双侧 censored 场景 live 重跑双注记，
    不再只记 chosen rung 的 HFSS 侧）；常量/闭式回退路径为空表。
    """
    seat = SEATS[seat_name]
    spec = seat["oe"]
    if spec.get("_nom") is None:
        with contextlib.suppress(Exception):
            ctx = seat_context(seat_name)
            spec["_nom"] = ctx.get("nominal_params")
    oe_notes: list[str] = []
    try:
        if spec["source"] == "sparams_csv":
            vals, src, mask = _resolve_oe_sparams_csv(seat, notes=oe_notes)
        elif spec["source"] == "touchstone":
            vals, src, mask = _resolve_oe_touchstone(seat, notes=oe_notes)
        elif spec["source"] == "verdict_fields":
            vals, src, mask = _resolve_oe_verdict_fields(seat)
        elif spec["source"] == "constants":
            vals, src, mask = _resolve_oe_constants(seat)
        else:
            raise ValueError(f"未知 OE source {spec['source']!r}")
        return {"values": vals, "source": src, "provenance": spec["provenance"],
                "mask": mask, "cap": None, "notes": oe_notes}
    except (FileNotFoundError, KeyError, OSError, ValueError) as exc:
        fb = spec.get("fallback")
        if isinstance(fb, str) and fb.startswith("closed_form:"):
            kind = fb.split(":", 1)[1]
            cf = _closed_form_refs(kind, seat)
            keys = {e["metric"] for e in seat["extractors"]}
            return {"values": {k: v for k, v in cf.items() if k in keys},
                    "source": f"closed_form:{kind}",
                    "provenance": (str(spec["provenance"])
                                   + f"；产物缺失（{type(exc).__name__}）→闭式半集"),
                    "mask": None, "cap": "AGREE_HFSS", "closed_form": cf,
                    "notes": oe_notes}
        if isinstance(fb, dict):
            return {"values": dict(fb), "source": "constants_fallback",
                    "provenance": (str(spec["provenance"])
                                   + f"；产物缺失（{type(exc).__name__}）→预声明常量"),
                    "mask": None, "cap": None,
                    "note": spec.get("fallback_note"), "notes": oe_notes}
        return {"values": {}, "source": "missing",
                "provenance": spec["provenance"], "mask": None, "cap": None,
                "error": str(exc), "notes": oe_notes}


# ═══════════════ HFSS 面（pyaedt 延迟导入；真机发射才走）══════════════

class LicenseBlockedError(RuntimeError):
    """远程/本机 HFSS 许可或进程面阻塞（fail-closed SKIP 口径）。"""


def check_ansysedt_residue() -> int:
    """本机 ansysedt 计数（#265 孤儿桌面判据；查询失败 -1 不阻塞主路径）。"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process ansysedt -ErrorAction SilentlyContinue | "
             "Measure-Object).Count"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        return int(proc.stdout.strip() or 0)
    except Exception:
        return -1


def _mm(v: float) -> str:
    return f"{float(v):.9f}mm"


def _ensure_material(h, ctx: dict) -> str:
    mat = "rfauto_b2a_sub"
    with contextlib.suppress(Exception):
        h.materials.add_material(mat, properties={
            "permittivity": ctx["er"],
            "dielectric_loss_tangent": ctx["tan_d"]})
    return mat


def _sheet(h, name: str, rect: Rect, z: float) -> None:
    h.modeler.create_rectangle(
        orientation="XY",
        origin=[_mm(rect[0]), _mm(rect[1]), _mm(z)],
        sizes=[_mm(rect[2] - rect[0]), _mm(rect[3] - rect[1])], name=name)


def _audit_obj(h, name: str, exp: Rect | list[float], tol: float = 0.02) -> None:
    """bbox 自审（#310④ hairpin §7.2② 先例；薄片 z 向期望 [z, z]）。"""
    got = [float(v) for v in h.modeler[name].bounding_box]
    want = list(exp)
    if len(got) != 6 or any(abs(g - w) > tol
                            for g, w in zip(got, want, strict=False)):
        raise RuntimeError(f"bbox 自审失败 {name}: got={got} want={want}")


def build_frame(h, lay: dict, ctx: dict, mat: str) -> list[float]:
    """基板+地板+空气域（挖去基板，hairpin 锚先例）；返回 [x0,y0,x1,y1]。"""
    h_mm = ctx["h_mm"]
    if lay.get("board") is not None:
        b = float(lay["board"])
        x0, y0, x1, y1 = -b, -b, b, b
    else:
        x0 = -float(lay["pad_x"])
        x1 = 2.0 * ctx["l_sect_mm"] + float(lay["pad_x"])
        y0 = -float(lay["sub_half_y"])
        y1 = float(lay["sub_half_y"])
    h.modeler.create_box(
        origin=[_mm(x0), _mm(y0), "0mm"],
        sizes=[_mm(x1 - x0), _mm(y1 - y0), _mm(h_mm)], name="GSub", material=mat)
    h.modeler["GSub"].solve_inside = True
    _sheet(h, "GGnd", (x0, y0, x1, y1), 0.0)
    h.modeler.create_box(
        origin=[_mm(x0), _mm(y0), "0mm"],
        sizes=[_mm(x1 - x0), _mm(y1 - y0), _mm(lay["air_top"])],
        name="GAir", material="vacuum")
    h.modeler.subtract("GAir", ["GSub"])
    h.modeler["GAir"].solve_inside = True
    return [x0, y0, x1, y1]


def radiate_open_faces(h, sub: list[float], h_mm: float,
                       port_edges: set[tuple[str, float]]) -> int:
    """开放面辐射（锚 A/B/hairpin-A-driven 先例实码；端口面跳过）。
    面心=模型单位 mm（#285）；空选择守卫。返回辐射面数。"""
    if not ASSIGN_RADIATION:
        return 0
    faces = h.modeler.get_object_faces("GAir")
    open_faces: list[int] = []
    for f in faces:
        cx, cy, cz = h.modeler.get_face_center(f)
        if cz < h_mm + 1e-6:
            continue                      # 基板顶界面（hairpin 锚同款条件）
        on_port = False
        for axis, val in port_edges:
            coord = cx if axis == "x" else cy
            if abs(coord - val) < 1e-3:
                on_port = True
                break
        if not on_port:
            open_faces.append(f)
    if not open_faces:
        raise RuntimeError("辐射面过滤为空（#285 面心口径/端口面核对）")
    h.assign_radiation_boundary_to_faces(assignment=open_faces, name="GRad")
    return len(open_faces)


def build_seat_geometry(h, seat_name: str, ctx: dict) -> dict[str, Any]:
    """criteria §2 建模：薄片 PerfectE（#356①）+ 0.02mm 重叠垫 unite（#310④）
    + 断链审计 fail-fast（#336）+ 端口/集总。返回 build_info。"""
    lay = seat_layout(seat_name, ctx)
    audit = lay["audit"]
    if not audit["ok"]:
        raise RuntimeError(
            f"断链审计 fail（#336）：orphans={audit['connectivity']['orphans']} "
            f"ports_missing={audit['ports_missing_metal']} "
            f"floating={audit['floating_components']}")
    for lump in lay.get("lumped", []):
        la = lump.get("audit")
        if la is not None and not la["ok"]:
            raise RuntimeError(
                f"集总桥审计 fail：{lump['name']} touched={la['touched']} "
                f"pec_overlap={la['pec_overlap']}（#191）")
    h.modeler.model_units = "mm"
    mat = _ensure_material(h, ctx)
    h_mm = ctx["h_mm"]
    sub = build_frame(h, lay, ctx, mat)
    # 金属薄片逐片创建+逐片 bbox 自审前移（#310④ hairpin §7.2② 先例）
    names: list[str] = []
    for nm, rect in lay["padded_rects"].items():
        _sheet(h, nm, rect, h_mm)
        _audit_obj(h, nm, [rect[0], rect[1], h_mm, rect[2], rect[3], h_mm])
        names.append(nm)
    # 过孔棒（marchand）：真实三维尺寸 pec 实体（#264），subtract 基板消重叠歧义
    via_names: list[str] = []
    for via in lay.get("vias", []):
        side = float(via["side"])
        h.modeler.create_box(
            origin=[_mm(via["x0"]), _mm(via["y_c"] - side / 2), "0mm"],
            sizes=[_mm(side), _mm(side), _mm(h_mm)],
            name=via["name"], material="pec")
        via_names.append(via["name"])
    if via_names:
        h.modeler.subtract("GSub", via_names, keep_originals=True)
    # unite 全金属薄片（保留首名 #310）+ 并集 bbox 自审
    with contextlib.suppress(Exception):
        h.modeler.unite(list(names))
    metal_name = names[0]
    arr = np.asarray(list(lay["padded_rects"].values()), dtype=float)
    _audit_obj(h, metal_name,
               [float(arr[:, 0].min()), float(arr[:, 1].min()), h_mm,
                float(arr[:, 2].max()), float(arr[:, 3].max()), h_mm])
    existing = set(h.modeler.object_names)
    pec_sheets = [n for n in (metal_name, "GGnd") if n in existing]
    h.assign_perfecte_to_sheets(assignment=pec_sheets, name="GMetalPEC")
    # 端口：微带惯例波端口（积分线 地面(z=0)→导带上缘，df6⑪ 口径；renorm 50）。
    # 薄片平面/尺寸按 #310④ 轴向循环映射（XZ=法向 Y：Width→Z、Height→X；
    # YZ=法向 X：Width→Y、Height→Z）——edge_y 横截面薄片必须 XZ+[h,w]
    # （review-slice4 P0-1：原 YZ+[w,h] 产出 x≡xc−w/2 竖条非横截面薄片，
    # same_geometry "ZX"+[4h,5w]/ratrace y-edge 先例同式）；逐片 bbox 自审
    # （#310④ 纪律，P1-1：端口片与金属片/集总片同级防线）；积分线点序=
    # (x,y,z) 且方向=地面(z=0)→导带上缘（start→end；df6⑪/Gravity.ZPos/
    # same_geometry/ratrace/hairpin·marchand 锚全部真机先例同向——
    # review-slice5 P3-1 统一翻转：原导带→地只差该端口 S 行列相位 180°，
    # 幅值/频点门免疫，发射前统一为先例方向防未来相位域消费踩差）。
    port_names: list[str] = []
    for pt in lay["ports"]:
        sheet = f"{pt['name']}sheet"
        if "edge_y" in pt:
            yc = float(pt["center_x"])
            h.modeler.create_rectangle(
                orientation="XZ",
                origin=[_mm(yc - pt["w"] / 2), _mm(pt["edge_y"]), "0mm"],
                sizes=[_mm(pt["h"]), _mm(pt["w"])], name=sheet)
            _audit_obj(h, sheet,
                       [yc - pt["w"] / 2, float(pt["edge_y"]), 0.0,
                        yc + pt["w"] / 2, float(pt["edge_y"]), float(pt["h"])])
            integ = [[_mm(yc), _mm(pt["edge_y"]), "0mm"],
                     [_mm(yc), _mm(pt["edge_y"]), _mm(h_mm)]]
        else:
            _axis, x_edge = pt["edge"]
            y_c = float(pt["center_y"])
            h.modeler.create_rectangle(
                orientation="YZ",
                origin=[_mm(x_edge), _mm(y_c - pt["w"] / 2), "0mm"],
                sizes=[_mm(pt["w"]), _mm(pt["h"])], name=sheet)
            _audit_obj(h, sheet,
                       [float(x_edge), y_c - pt["w"] / 2, 0.0,
                        float(x_edge), y_c + pt["w"] / 2, float(pt["h"])])
            integ = [[_mm(x_edge), _mm(y_c), "0mm"],
                     [_mm(x_edge), _mm(y_c), _mm(h_mm)]]
        face = h.modeler.get_object_faces(sheet)[0]
        modes = int(pt.get("modes", 1))
        if modes == 1:
            h.wave_port(assignment=face, name=pt["name"], impedance=50.0,
                        renormalize=True, modes=1, integration_line=integ)
        else:
            # #308 显式多模积分线格式=[起点列表(每模一个), 终点列表(每模
            # 一个)]——传 [line, line] 被解析成模 1 起点=终点（"length of
            # port lines must be greater than zero"，锚 A 首跑实证）；两模
            # 同用地→导带竖直路径（锚 A 同款）。
            h.wave_port(assignment=face, name=pt["name"], impedance=50.0,
                        renormalize=True, modes=modes,
                        integration_line=[[integ[0], integ[0]],
                                          [integ[1], integ[1]]])
        port_names.append(pt["name"])
    # 集总 RLC：wilkinson=XY 片跨两臂（XPos 电流）；gysel=竖直 XZ 片对地
    # （ZPos 电流，mapes bleed 先例 API；XZ sizes=[h(→Z), w(→X)] #310④ 映射）
    from ansys.aedt.core.generic.constants import Gravity

    for lump in lay.get("lumped", []):
        if lump.get("kind") != "rlc":
            continue
        sheet = f"{lump['name']}sheet"
        if lump.get("plane") == "xz":
            r = lump["sheet"]
            h.modeler.create_rectangle(
                orientation="XZ",
                origin=[_mm(r[0]), _mm(r[1]), "0mm"],
                sizes=[_mm(h_mm), _mm(r[2] - r[0])], name=sheet)
            _audit_obj(h, sheet, [r[0], r[1], 0.0, r[2], r[1], h_mm])
            h.assign_lumped_rlc_to_sheet(
                assignment=sheet, start_direction=Gravity.ZPos,
                name=f"{lump['name']}RLC", rlc_type="Parallel",
                resistance=float(lump["r_ohm"]))
            continue
        _sheet(h, sheet, lump["sheet"], h_mm)
        h.assign_lumped_rlc_to_sheet(
            assignment=sheet,
            start_direction=Gravity.XPos if lump["axis"] == "x" else Gravity.ZPos,
            name=f"{lump['name']}RLC", rlc_type="Parallel",
            resistance=float(lump["r_ohm"]))
    # marchand 平衡侧 140Ω 集总口（锚 B 同款 XZ 薄片 sizes=[h, wb]，#310④ 映射）
    for lump in lay.get("lumped", []):
        if lump.get("kind") != "port":
            continue
        sheet = f"{lump['name']}sheet"
        r = lump["sheet"]
        h.modeler.create_rectangle(
            orientation="XZ",
            origin=[_mm(r[0]), _mm(r[1]), "0mm"],
            sizes=[_mm(h_mm), _mm(r[2] - r[0])], name=sheet)
        _audit_obj(h, sheet, [r[0], r[1], 0.0, r[2], r[1], h_mm])
        h.lumped_port(assignment=sheet, integration_line=Gravity.ZPos,
                      impedance=float(lump["r_ohm"]), name=lump["name"],
                      renormalize=True)
    n_rad = radiate_open_faces(h, sub, h_mm, _port_edges(lay))
    # review-slice11 P2-2：kind="port" 集总口（marchand P2/P3 140Ω）结构化
    # 记账——判读所依赖的关键端口口径不得只存于自由文本注记（对照 gysel
    # Rload1/2 全账先例）；name/阻抗/落位/contact 单源现抄自 layout。
    lumped_ports = [
        {"name": ln["name"], "kind": "port",
         "impedance_ohm": float(ln["r_ohm"]),
         "sheet_x0y0x1y1_mm": [float(v) for v in ln["sheet"]],
         "axis": ln.get("axis"),
         "contact_point_xy_mm": ([float(v) for v in ln["contact_point"]]
                                 if ln.get("contact_point") else None),
         "note": ln.get("note", "")}
        for ln in lay.get("lumped", []) if ln.get("kind") == "port"]
    return {"unite_kept": metal_name, "pec_sheets": pec_sheets,
            "ports": port_names, "vias": via_names, "n_radiation_faces": n_rad,
            "lumped_ports": lumped_ports,
            "audit": {"connectivity": audit["connectivity"],
                      "ports_ok": audit["ok"],
                      "lumped": {ln["name"]: ln.get("audit")
                                 for ln in lay.get("lumped", [])
                                 if ln.get("audit") is not None}},
            "radiation": bool(ASSIGN_RADIATION),
            "notes": lay.get("notes", []),
            "layout_provenance": ctx["provenance"]}


def _port_edges(lay: dict) -> set[tuple[str, float]]:
    edges: set[tuple[str, float]] = set()
    for pt in lay["ports"]:
        if "edge_y" in pt:
            edges.add(("y", float(pt["edge_y"])))
        else:
            edges.add(("x", float(pt["edge"][1])))
    return edges


def make_setup_and_sweep(h, seat: dict, level: int) -> str:
    """ΔS 阶梯档 setup（#335：同几何同端口，仅 MaxDeltaS/Passes 变；档 0 建，
    档 ≥1 改 props 重解析续化）。"""
    ds, passes = seat["ladder"][level]
    lo, hi = seat["window_ghz"]
    if level == 0:
        setup = h.create_setup(name="Setup")
        setup.props["Frequency"] = f"{seat['f0_ghz']!r}GHz"
        setup.props["MaxDeltaS"] = float(ds)
        setup.props["MaximumPasses"] = int(passes)
        setup.update()
        h.create_linear_count_sweep(
            setup="Setup", unit="GHz", start_frequency=float(lo),
            stop_frequency=float(hi), num_of_freq_points=int(seat["n_points"]),
            name="Sweep", sweep_type="Interpolating", save_fields=False)
    else:
        setup = h.get_setup("Setup")
        setup.props["MaxDeltaS"] = float(ds)
        setup.props["MaximumPasses"] = int(passes)
        setup.update()
    return "Setup"


def solve_with_watchdog(h, setup_name: str,
                        timeout_s: float = SOLVE_TIMEOUT_S) -> dict:
    """求解 watchdog（#145：超时只在真未完成时判废，竞态完成接受真结果）。"""
    box: dict = {"done": False, "err": None}

    def _go() -> None:
        try:
            h.analyze(setup=setup_name)
            box["done"] = True
        except Exception as exc:
            box["err"] = repr(exc)

    t0 = time.monotonic()
    th = threading.Thread(target=_go, daemon=True)
    th.start()
    th.join(timeout=timeout_s)
    solve_s = round(time.monotonic() - t0, 1)
    if not box["done"]:
        if box["err"] is not None:
            raise RuntimeError(f"solve 失败（{solve_s}s）: {box['err']}")
        raise RuntimeError(f"solve watchdog 超时（>{timeout_s}s，#145）")
    return {"solve_s": solve_s}


def convergence_record(h) -> dict:
    """passes/final_delta_s（#335 触顶判据：passes 用尽且 final_delta_s>目标）。

    fail-closed（review-slice3 P1-2；#335/#323 同源）：提取失败（setup 缺失/
    异常/passes==0）→ ``{"extraction_failed": True}`` 不带 passes——提取失败
    ≠未触顶（两态分开，不把失败翻成 topped=True），判读链对该档不判收敛门
    （如实 UNKNOWN），绝不把零收敛证据当"未触顶"采信。passes==0 与 analyze
    成功互斥（成功至少 1 pass），故 0 判为提取失败信号。
    """
    from rfauto.adapters.hfss_adapter import HfssAdapter

    failed: dict[str, Any] = {"extraction_failed": True}
    try:
        setup = h.get_setup("Setup")
        if setup is None:
            return failed
        passes, ds = HfssAdapter._extract_convergence(setup)
        if int(passes) <= 0:
            return failed
        return {"passes": int(passes), "final_delta_s": float(ds),
                "extraction_failed": False}
    except Exception:
        return failed


def export_network_data(h, target_path: str) -> None:
    """ExportNetworkData 直连（L2 先例口径；50Ω 重归一）。target_path 为最终
    文件全名（远程=服务器侧路径语义）。"""
    osolution = h.osolution
    if osolution is None:
        raise RuntimeError("hfss.osolution 不可用（导出失败）")
    osolution.ExportNetworkData(
        "", ["Setup:Sweep"], 3, target_path.replace("\\", "/"), ["all"],
        True, 50, "S", -1, 0, 15, False, False, False)


def export_touchstone(h, path: Path, n_term: int) -> Path:
    """本地导出：显式 .sNp 名（#309 Σ模数口径；#248 反向坑=适配器按端口边界
    数命名，不经过）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path.with_suffix(f".s{n_term}p")
    export_network_data(h, str(target))
    if not target.exists():
        raise RuntimeError(f"Touchstone 导出未产生文件：{target}")
    return target


def touchstone_is_synthetic(path: Path, tol: float = 1e-12) -> bool:
    """P2-1 防御判别：dry-run 合成链（synthetic_s 全实数 + skrf RI 写出）的
    Touchstone 全矩阵虚部恒 0（Im≡0），真机引擎导出必有数值虚部——Im≡0
    判 synthetic（实证：patch_array_2x2/hfss_side/rung3.s1p 与
    hfss_side_dryrun/rung3.s1p 逐字节相同，review-slice11 P2-1）。"""
    _freq, s = read_touchstone(path)
    return bool(float(np.max(np.abs(np.imag(s)))) <= tol)


def read_touchstone(path: Path, *,
                    reject_synthetic: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """读 Touchstone → (freq_hz, S[nf,n,n])。reject_synthetic=True（真机判读
    链，P2-1 防御）时 Im≡0 判 dry-run 合成残留拒读——防把 hfss_side_dryrun
    漏移的 stub 数据当真机 rung 消费（stub 即 OE 参考投影，会伪「逐位一致
    AGREE」）；dry-run 合成链自身回读传 False（合成数据本就 Im≡0）。"""
    import skrf

    net = skrf.Network(str(path))
    s = np.asarray(net.s, dtype=complex)
    if reject_synthetic and float(np.max(np.abs(np.imag(s)))) <= 1e-12:
        raise ValueError(
            "Touchstone 全矩阵虚部恒 0（Im≡0）=dry-run 合成残留特征"
            "（synthetic_s 全实数；review-slice11 P2-1 防御）——拒读："
            f"{path}")
    return net.frequency.f.astype(float), s


# ── 会话（machine 参数化；远程路径留阻塞分支，许可无效=SKIP 如实）────────────

def open_local_hfss(seat: dict, project_path: Path) -> Any:
    from ansys.aedt.core import Hfss

    project_path.parent.mkdir(parents=True, exist_ok=True)
    return Hfss(project=str(project_path), design=f"b2a_{seat['template']}",
                version=HFSS_VERSION, non_graphical=True, new_desktop=True)


def ensure_remote_project_dir(machine: str, project_dir: str) -> bool:
    """服务器侧项目目录预建（幂等 mkdir；review-slice3 P1-1 附带缺口——
    本地分支有 mkdir(parents=True)，远程分支原无对应面）。

    经注册表 SshTransport 远程执行 ``cmd /c mkdir``：服务器=Windows（注册表
    project_root 盘符路径），cmd 内建 mkdir 带命令扩展自动建中间目录，且
    ``cmd /c`` 前缀对 cmd.exe/PowerShell 缺省 shell 双兼容（remote_service
    裸 PowerShell 命令依赖缺省 shell 的教训在此收口，#310 P3-10 同源）。
    幂等：目录已在档 rc=0。返回 True=在档；False=SSH 面故障（调用方
    fail-closed，verdict 如实，不静默发射）。
    """
    try:
        from rfauto.infra.remote_machines import SshTransport, load_remote_machines, resolve_machine

        cfg = resolve_machine(machine, load_remote_machines())
        transport = SshTransport(cfg)
        transport.connect()
        try:
            win_path = project_dir.replace("/", "\\").rstrip("\\")
            rc, _out, _err = transport.run_command(
                f'cmd /c mkdir "{win_path}"', timeout_s=30.0)
            return rc == 0
        finally:
            with contextlib.suppress(Exception):
                transport.close()
    except Exception:
        return False


def open_remote_hfss(seat: dict, machine: str, *,
                     grpc_port: int | None = None) -> tuple[Any, Any, dict]:
    """远程会话（多机协同 v0）：注册表解析→探活→目录预建→attach。许可端口
    不可达或 FlexNet 换发未完成（现况 -8,544）→ LicenseBlockedError → SKIP
    如实。

    grpc_port（wf:hfss-window-parallel）：per-seat gRPC 端口覆盖——``--parallel
    N>1`` 时每个席位各自 ``ansysedt -grpcsrv <base+i>`` 独立实例，attach 端口
    替换注册表单值 ``cfg.hfss_grpc_port`` 消费点；None（缺省）=注册表端口，
    行为零变化。覆盖值随 ``info["remote"]["port"]`` 进 verdict 留证。

    review-slice3 P1-1：Desktop/Hfss 构造包共享单源
    ``remote_session_switches()``（remote_service._attach_and_verify 同款，
    hfss_session CM 单源勿复制）——缺省 grpc_local/grpc_secure_mode=True 时
    pyaedt 1.4.0 把连接串 machine 改写为 ""（WNUA 本机通道语义），远程
    attach 要么打不到服务器要么落本机桌面；attach 完成后置
    ``settings.remote_rpc_session = None``（Hfss 设计初始化按 rpyc 客户端
    对象消费，裸 True 必炸——L2 实证）。"""
    from ansys.aedt.core import Desktop, Hfss
    from ansys.aedt.core.generic.settings import settings

    from rfauto.adapters.hfss_session import remote_session_switches
    from rfauto.service.remote_service import hfss_remote_session_config, remote_probe

    probe = remote_probe(machine)
    entry = (probe.get("machines") or [{}])[0]
    ports = entry.get("ports", {}) if isinstance(entry, dict) else {}
    lic = ports.get("ansys_license")
    lic_open = bool(lic.get("open")) if isinstance(lic, dict) else None
    if lic_open is False:
        raise LicenseBlockedError(
            f"远程许可端口不可达（ansys_license probe={lic}）——SKIP 如实"
            "（hfss_gui FlexNet -8,544 换发待管理员口径）")
    remote = hfss_remote_session_config(machine).get("remote")
    if not remote:
        raise LicenseBlockedError(f"机器 {machine!r} 未登记远程会话配置")
    if grpc_port is not None:
        remote = {**remote, "port": int(grpc_port)}
    server_project = (
        f"{remote['project_root']}\\{B2A_ROOT_ON_SERVER}\\{seat['template']}"
        f"\\hfss_side\\project.aedt")
    project_dir = server_project.rsplit("\\", 1)[0]
    if not ensure_remote_project_dir(machine, project_dir):
        raise RuntimeError(
            f"服务器侧项目目录预建失败：{project_dir}（machine={machine}，"
            "SSH 面）——远程分支 fail-closed（无目录不发射）")
    with remote_session_switches():
        desktop = Desktop(version=remote["version"], non_graphical=True,
                          new_desktop=False, machine=remote["machine"],
                          port=remote["port"])
        # remote_rpc_session 在 attach 语义是 bool，但 Hfss 设计初始化按 rpyc 客户端
        # 对象消费——attach 完成后置 None（L2 实证，remote_service 同款）。
        settings.remote_rpc_session = None
        h = Hfss(project=server_project, design=f"b2a_{seat['template']}",
                 version=remote["version"], non_graphical=True,
                 machine=remote["machine"], port=remote["port"])
    info = {"remote": remote, "server_project": server_project,
            "project_dir": project_dir, "probe_license_open": lic_open}
    return desktop, h, info


def fetch_remote_file(machine: str, remote_path: str, local_path: Path) -> bool:
    """SFTP 回取（best-effort #105：失败返回 False，verdict 如实记）。"""
    try:
        from rfauto.infra.remote_machines import SshTransport, load_remote_machines, resolve_machine

        cfg = resolve_machine(machine, load_remote_machines())
        transport = SshTransport(cfg)
        transport.connect()
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            transport.download_file(remote_path, local_path)
            return local_path.exists()
        finally:
            with contextlib.suppress(Exception):
                transport.close()
    except Exception:
        return False


# ── 建模注册表：8 席全量=build_seat_geometry（skeleton 防线保留 fail-closed）──

def build_seat(h, seat_name: str, ctx: dict) -> dict[str, Any]:
    seat = SEATS[seat_name]
    if seat.get("builder_status") == "skeleton":
        raise NotImplementedError(
            f"席 {seat_name} 建模函数为骨架（实现待续，后续批补）——"
            "spec/判读/OE 参考已全量就绪，补 builder 即可发射")
    return build_seat_geometry(h, seat_name, ctx)


# ═══════════════ dry-run 合成钩子（离线端到端钉，零 pyaedt 零网络）══════════════

def synthetic_s(seat_name: str, freq_hz: np.ndarray,
                variant: str = "agree", n_ports: int | None = None) -> np.ndarray:
    """合成 S（判读器合成注入钉）：谐振型 |S11| 谷 + OE 量级传输/隔离。
    variant="disagree" 把谷位挪出 ±gate 带（判 DISAGREE 路径）。
    n_ports（S2 决策 2 发射面）：矩阵阶覆盖（marchand wave2mode=Σ模数 5，
    模域零填充）；None=席端子数（缺省行为零变化）。"""
    seat = SEATS[seat_name]
    n = int(n_ports) if n_ports is not None else int(seat["n_ports"])
    nf = len(freq_hz)
    fg = np.asarray(freq_hz, dtype=float) / 1e9
    oe = resolve_oe_refs(seat_name)["values"]
    f_key = next((k for k in ("f_match_ghz", "f_dip_ghz", "f_null_ghz",
                              "f_min_ghz", "f_peak_ghz")
                  if oe.get(k) is not None), None)
    f0 = float(oe[f_key]) if f_key else seat["f0_ghz"]
    if variant == "disagree":
        f0 = f0 * (0.7 if f_key == "f_peak_ghz" else 1.15)
    depth = oe.get("s11_min_db")
    depth = float(depth) if depth is not None else -20.0
    span = seat["window_ghz"][1] - seat["window_ghz"][0]
    base = 10.0 ** (-0.5 / 20.0)
    dip = 10.0 ** (depth / 20.0)
    s11 = base - (base - dip) * np.exp(
        -((fg - f0) / max(0.05 * span, 1e-6)) ** 2)
    thru_key = next((k for k in ("s21_at_f0_db", "through_at_f0_db",
                                 "s21_at_match_db", "amp_mid_db")
                     if oe.get(k) is not None), None)
    thru_db = float(oe[thru_key]) if thru_key else -3.01
    thru = 10.0 ** (thru_db / 20.0)
    iso = 10.0 ** (-40.0 / 20.0)
    s = np.zeros((nf, n, n), dtype=complex)
    s[:, 0, 0] = s11
    if n >= 2:
        s[:, 1, 0] = thru * (1.0 + 0.02 * np.sin(2.0 * np.pi * fg / 5.0))
    if n >= 3:
        s[:, 2, 0] = thru * (1.0 - 0.02 * np.sin(2.0 * np.pi * fg / 5.0))
        s[:, 1, 2] = iso * (1.0 + 0.01 * np.sin(2.0 * np.pi * fg / 5.0))
    if n >= 4:
        s[:, 3, 0] = iso
    return s


def make_dry_hooks(seat_name: str, variant: str = "agree",
                   n_modes: int | None = None) -> dict[str, Callable]:
    """dry-run 钩子（#df4② 最小 dry-call 钉的端到端版）：零 pyaedt 全链。
    n_modes：合成 S 矩阵阶覆盖（marchand wave2mode=5；None=席端子数）。"""
    seat = SEATS[seat_name]

    def _open(_seat, _machine, project_path: Path) -> str:
        Path(project_path).parent.mkdir(parents=True, exist_ok=True)
        return "dry-session"

    def _build(_h, _seat_name, _ctx) -> dict:
        return {"unite_kept": "dry", "pec_sheets": ["dry"], "ports": [],
                "audit": {"ports_ok": True}, "radiation": False, "dry": True}

    def _solve(_h, _seat_name, level, max_delta_s, max_passes) -> dict:
        return {"solve_s": 0.0, "passes": int(max_passes),
                "final_delta_s": float(max_delta_s) * 0.5, "level": level}

    def _export(_h, _seat_name, path: Path, n_term: int) -> Path:
        import skrf

        freq = (np.linspace(seat["window_ghz"][0], seat["window_ghz"][1],
                            seat["n_points"]) * 1e9)
        # n_ports 仅在矩阵阶覆盖需要时透传（monkeypatch 3 参合成器兼容：
        # 缺省路径调用形态逐字节不变）
        s = (synthetic_s(seat_name, freq, variant, n_ports=n_modes)
             if n_modes is not None and n_modes != int(seat["n_ports"])
             else synthetic_s(seat_name, freq, variant))
        net = skrf.Network(frequency=skrf.Frequency.from_f(freq, unit="Hz"), s=s)
        target = path.with_suffix(f".s{n_term}p")
        net.write_touchstone(str(target))
        return target

    return {"open": _open, "build": _build, "solve": _solve, "export": _export}


# ═══════════════ 席编排（fail-closed；verdict json/md 落盘）══════════════

def remote_license_preflight(machine: str, *, deep: bool = False) -> dict:
    """发射前 license 预检薄包装（v1 调度面一级门，2026-09-29）。

    转发 ``rfauto.service.remote_service.license_preflight``：license 端口
    TCP 探活（+可选 attach health 深检，信息面不进门）；席位级 lmstat 查询
    UNVERIFIED（端口 OPEN≠席位可用，G6 教训）。模块级薄包装便于单测钉
    通道（#139：unit 门零真网）。 """
    from rfauto.service.remote_service import license_preflight

    return license_preflight(machine, deep=deep)


def remote_max_parallel(machine: str) -> int | None:
    """注册表 ``hfss.max_parallel`` 读数（远程真机并行度闸；缺省 2=实测
    可用档，server_invocation_playbook §2.4）。

    注册表读不了（机器未登记/解析失败）→ ``None``＝不设闸：坏机器由逐席
    license 预检与会话层如实 FAIL/SKIP，闸层不抢戏不添错（#105 best-effort
    同源——观测/治理面不得成为主路径故障点）。"""
    try:
        from rfauto.infra.remote_machines import DEFAULT_HFSS_MAX_PARALLEL, load_remote_machines, resolve_machine

        cfg = resolve_machine(machine, load_remote_machines())
        if cfg is None:
            return None
        return int(getattr(cfg, "hfss_max_parallel",
                           DEFAULT_HFSS_MAX_PARALLEL))
    except Exception:
        return None


def default_out_dir(seat_name: str, machine: str,
                    root: Path | None = None,
                    port_form: str | None = None) -> Path:
    """per-seat 产物目录（模板隔离 ✓；root=None=缺省 OUT_ROOT，行为零变化）。
    marchand wave2mode 端口形态单变量对照运行产物隔离到 hfss_side_wave2mode
    （S2 决策 2：已落档 hfss_side/ 的 verdict/锚证据零触碰）。"""
    seat = SEATS[seat_name]
    sub = "hfss_side" if machine == "local" else "hfss_side_remote"
    if (seat_name == "marchand_balun"
            and resolve_marchand_port_form(seat_name, port_form) == "wave2mode"):
        sub += "_wave2mode"
    return (root if root is not None else OUT_ROOT) / seat["template"] / sub


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1, default=str) + "\n",
        encoding="utf-8")


def _progress(out_dir: Path, msg: str, *, dry_run: bool = False) -> None:
    """progress.log 追加（UTF-8 显式 #89）。dry_run=True 时行带 ``[dryrun]``
    前缀（review-slice11 P2-3 判读链防御）：存量干跑曾把合成 verdict 行写入
    真跑目录（gysel 假 DISAGREE 与真态相反），此后干跑行可辨识、消费者按
    parse_verdict_lines/``[dryrun]`` 前缀拒收。"""
    line = (f"[{time.strftime('%H:%M:%S')}] "
            + ("[dryrun] " if dry_run else "") + msg)
    print(line, flush=True)
    with contextlib.suppress(OSError), (out_dir / "progress.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


_VERDICT_LINE_RE = re.compile(
    r"^\[(?P<time>\d\d:\d\d:\d\d)\] (?P<dryrun>\[dryrun\] )?"
    r"verdict=(?P<verdict>\S+) status=(?P<status>\S+) "
    r"wall=(?P<wall_s>[\d.]+)s$")

# review-slice13 P2-1：存量无前缀假行特征带（4 个 hfss_side_dryrun 目录 legacy
# 假 verdict 行 wall 2.0s 级 vs 真机 verdict 485–6065s；slice11 坑 2「dry_run/
# machine/异常 wall 三字段秒辨」先例的 wall 分量）。阈值取 60s 安全带——真跑
# 快速失败 attempt（许可/残留 SKIP、abort FAIL，wall 可 <60s）同样不产出，其
# 执行证据在 verdict.json/独立 attempt 行，不经本判读解析器。
_VERDICT_WALL_S_MIN = 60.0


def parse_verdict_lines(progress_log: Path | str) -> list[dict[str, Any]]:
    """progress.log verdict 行解析（review-slice11 P2-3 判读链防御，纯函数）：

    - ``[dryrun]`` 前缀行（fix8 起写入即带）一律不产出 verdict——干跑合成
      判读（wall≈0.5s）与真态可相反，grep 消费者禁直取；
    - 存量无前缀假行按 wall 特征拒收（review-slice13 P2-1：4 个
      hfss_side_dryrun 目录 legacy 假行 wall 2.0s 级、无前缀，此前仍被正常
      解析产出）——``wall_s < 60s`` 的 verdict 行不产出（dry 合成链特征；
      真跑快速失败 attempt 的执行证据走 verdict.json，不依赖本解析器）。
    返回 [{time, verdict, status, wall_s}]（按文件序）。"""
    out: list[dict[str, Any]] = []
    try:
        text = Path(progress_log).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        mo = _VERDICT_LINE_RE.match(line.strip())
        if mo is None or mo.group("dryrun"):
            continue
        wall_s = float(mo.group("wall_s"))
        if wall_s < _VERDICT_WALL_S_MIN:
            continue
        out.append({"time": mo.group("time"),
                    "verdict": mo.group("verdict"),
                    "status": mo.group("status"),
                    "wall_s": wall_s})
    return out


def _verdict_md(seat_name: str, verdict: dict) -> str:
    lines = [
        f"# {seat_name} · HFSS 窗 B→A 仲裁 verdict",
        "",
    ]
    if verdict.get("dry_run"):
        # review-slice4 P3：dry-run=合成数据，md 首屏醒目横幅（消费者第一眼可见）
        lines += [
            "> **⚠ SYNTHETIC DATA（dry-run 合成链）——下表 HFSS 列为 "
            "synthetic_s 合成值，非实测：",
            "> 不作验收/仲裁依据，仅离线端到端链路钉"
            "（review-slice4 P3）。**",
            "",
        ]
    lines += [
        f"- 总态：**{verdict.get('verdict')}**（status={verdict.get('status')}，"
        f"wall {verdict.get('wall_s')}s / 预算 {verdict.get('budget_min')}min）",
        f"- OE 参考：{verdict.get('oe', {}).get('source')}"
        f"（cap={verdict.get('oe', {}).get('cap')}）",
        f"- 收敛：chosen_level={verdict.get('ladder', {}).get('chosen_level')}"
        f" saturated={verdict.get('ladder', {}).get('saturated_all')}",
        f"- G11：passive={verdict.get('g11', {}).get('passive')}"
        f" reciprocity={verdict.get('g11', {}).get('reciprocity')}",
        "",
        "| 指标 | HFSS | OE | 门 | 差 | 态 |",
        "|---|---|---|---|---|---|",
    ]
    for r in verdict.get("per_metric", []):
        state = r["state"]
        wf = r.get("weak_feature")
        if isinstance(wf, dict) and wf.get("downgraded"):
            state += "→info(weak)"     # lesson-2：病态背景降级（记录不判）
        lines.append(
            f"| {r['metric']} | {r.get('hfss')} | {r.get('oe')} "
            f"| {r.get('gate')}({r.get('gate_kind')}) | {r.get('diff')} "
            f"| {state} |")
    for note in verdict.get("implementation_notes") or []:
        lines.append(f"\n> 注记：{note}")
    if verdict.get("error"):
        lines.append(f"\n> error：{verdict['error']}")
    lines.append("\n> 判据：runs/hfss_window_b2a/" + seat_name
                 + "/criteria.md（§3–§5 冻结，发射后不改）")
    return "\n".join(lines) + "\n"


def _is_license_error(exc: Exception) -> bool:
    try:
        from rfauto.core.errors import LicenseError

        if isinstance(exc, LicenseError):
            return True
    except Exception:
        pass
    msg = str(exc).lower()
    return ("license" in msg or "flexnet" in msg or "lmgrd" in msg
            or "-8,544" in msg or "-8544" in msg)


def run_seat(seat_name: str, *, machine: str = "local",
             out_dir: Path | None = None, dry_run: bool = False,
             dry_variant: str = "agree",
             grpc_port: int | None = None,
             residue_check: bool = True,
             marchand_port_form: str | None = None) -> dict:
    """单席全流程（fail-closed：任何步失败=verdict FAIL+证据留痕，不凑绿）。

    dry_run=True 时走 make_dry_hooks 合成链（零 pyaedt 零求解，离线端到端钉）；
    真机路径固定函数化（open_local_hfss/open_remote_hfss → build_seat →
    make_setup_and_sweep/solve_with_watchdog → export_touchstone），测试经
    monkeypatch 注入故障（fail-closed 路径钉）。

    grpc_port（wf:hfss-window-parallel）：远程分支 attach 端口覆盖（None=注册
    表单值，行为零变化；非 None 时随 verdict["grpc_port"] 落档）。
    residue_check：本机 ansysedt 残留检查开关（#265）——``--parallel>1`` 时
    席位子进程传入 False（兄弟席实例会被误计残留），波前/波后守卫上移到
    编排器；缺省 True=现行为零变化。
    marchand_port_form（S2 决策 2 发射面）：marchand 端口形态（None=席 spec
    缺省 lumped140=已落档行为零变化；wave2mode=2 模大截面波端口单变量对照，
    判据分派 criteria_for_run、导出 Σ模数 .s5p、产物目录 hfss_side_wave2mode
    隔离）；起跑前跑判据 lesson 门（lesson-1 同带强制，违例 fail-closed）。
    """
    port_form = resolve_marchand_port_form(seat_name, marchand_port_form)
    seat = criteria_for_run(seat_name, port_form)
    out_dir = (Path(out_dir) if out_dir is not None
               else default_out_dir(seat_name, machine, port_form=port_form))
    t0 = time.monotonic()
    verdict: dict[str, Any] = {
        "seat": seat_name, "template": seat["template"], "machine": machine,
        "dry_run": bool(dry_run),
        "port_form": port_form,
        "criteria": str(OUT_ROOT / seat["template"] / "criteria.md"),
        "budget_min": seat["budget_min"],
        "window_ghz": list(seat["window_ghz"]),
        "ladder_declared": [list(r) for r in seat["ladder"]],
    }
    if grpc_port is not None:
        verdict["grpc_port"] = int(grpc_port)
    if dry_run:
        # review-slice4 P3：dry-run 链的 HFSS 列=synthetic_s 合成值（与 OE
        # 列逐位同值系注入所致）——verdict 带醒目合成标记，不作验收/仲裁依据
        verdict["data_provenance"] = "synthetic"
        verdict["synthetic_note"] = (
            "dry-run 合成链（synthetic_s，零 pyaedt 零求解）：per_metric 的"
            " HFSS 列为合成数据非实测，本 verdict 仅作离线端到端链路钉，"
            "不作验收/仲裁依据（review-slice4 P3）")
    h = None
    desktop = None
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # ⓪ 判据 lesson 门（S2 审计 2026-09-29 lesson-1）：band 统计量门
        # 双侧同带强制——违例=判据面错误，fail-closed 不发射不触会话（#122）
        assert_band_symmetry(seat)
        # ① 本机进程残留检查（#265；dry/远程不适用；parallel>1 时由编排器
        # 波前守卫承担，席位子进程传 residue_check=False 防兄弟席误计）
        if residue_check and machine == "local" and not dry_run:
            residue = check_ansysedt_residue()
            verdict["ansysedt_before"] = residue
            if residue > 0:
                raise LicenseBlockedError(
                    f"本机 ansysedt 残留 {residue} 个（#265 孤儿桌面判据）——"
                    "不代杀，人工核对后重跑")
        # ①b 发射前 license 预检（v1 调度面，2026-09-29）：远程真机路径才走
        # （dry-run 合成链零网络；local 路径零行为变化）——预检不过=
        # LicenseBlockedError → SKIP 如实记账（信封随 verdict 落档），不硬打。
        if machine != "local" and not dry_run:
            pre = remote_license_preflight(machine)
            verdict["license_preflight"] = pre
            if pre.get("verdict") != "PASS":
                raise LicenseBlockedError(
                    f"license 预检未过（verdict={pre.get('verdict')}，"
                    f"reason={pre.get('reason')}）——该座 fail-skip 不硬打")
        # ② OE 参考（单一事实源/闭式回退）
        oe = resolve_oe_refs(seat_name)
        verdict["oe"] = {"source": oe["source"], "cap": oe.get("cap"),
                         "provenance": oe["provenance"],
                         "values": oe["values"]}
        if not dry_run:
            _progress(out_dir, f"OE 参考：{oe['source']} values={oe['values']}")
        ctx = seat_context(seat_name, port_form=port_form)
        project = out_dir / "project.aedt"
        n_mode = seat_mode_count(seat_name, port_form)
        hooks = (make_dry_hooks(seat_name, dry_variant, n_modes=n_mode)
                 if dry_run else {})
        # ③ 会话（machine 参数化）
        if dry_run:
            h = hooks["open"](seat, machine, project)
        elif machine == "local":
            h = open_local_hfss(seat, project)
        else:
            desktop, h, remote_info = open_remote_hfss(seat, machine,
                                                       grpc_port=grpc_port)
            verdict["remote"] = remote_info
        # ④ 建模 + 断链审计（#336 fail-fast 在 builder 内）
        build = build_seat(h, seat_name, ctx) if not dry_run else hooks["build"](
            h, seat_name, ctx)
        verdict["build"] = build
        if not dry_run:
            _progress(out_dir, f"build ok: unite={build.get('unite_kept')} "
                               f"ports={build.get('ports')} rad_faces="
                               f"{build.get('n_radiation_faces')}")
        # ⑤ ΔS 阶梯（#335：三档各一次求解，同几何同端口）
        rungs: list[dict] = []
        for level, (ds, passes) in enumerate(seat["ladder"]):
            if dry_run:
                solve_meta = hooks["solve"](h, seat_name, level, ds, passes)
            else:
                make_setup_and_sweep(h, seat, level)
                solve_meta = dict(solve_with_watchdog(h, "Setup"))
            if dry_run:
                snp = Path(hooks["export"](h, seat_name,
                                           out_dir / f"rung{level + 1}",
                                           n_mode))
            elif machine == "local":
                snp = export_touchstone(h, out_dir / f"rung{level + 1}", n_mode)
            else:
                server_dir = str(Path(verdict["remote"]["server_project"]).parent)
                server_snp = f"{server_dir}\\rung{level + 1}.s{n_mode}p"
                export_network_data(h, server_snp)
                snp = out_dir / f"rung{level + 1}.s{n_mode}p"
                got = fetch_remote_file(machine, server_snp, snp)
                verdict["remote_fetch"] = {"ok": bool(got),
                                           "server_path": server_snp}
                if not got:
                    raise RuntimeError(
                        f"远程 Touchstone 回取失败：{server_snp}（verdict 无从判读）")
            freq_hz, smat = read_touchstone(snp, reject_synthetic=not dry_run)
            conv = solve_meta if dry_run else convergence_record(h)
            conv_failed = bool(conv.get("extraction_failed"))
            topped = (not conv_failed
                      and conv.get("passes") is not None
                      and conv.get("final_delta_s") is not None
                      and int(conv["passes"]) >= int(passes)
                      and float(conv["final_delta_s"]) > float(ds))
            rung_notes: list[str] = []
            rungs.append({
                "level": level + 1, "max_delta_s": ds, "max_passes": passes,
                "passes": conv.get("passes"),
                "final_delta_s": conv.get("final_delta_s"), "topped": topped,
                "extraction_failed": conv_failed,
                "solve_s": solve_meta.get("solve_s"), "touchstone": str(snp),
                "metrics": extract_metrics(freq_hz, smat, seat, None,
                                           notes=rung_notes),
                "metric_notes": rung_notes,
                "_freq": freq_hz, "_s": smat,
            })
            if not dry_run:
                _progress(out_dir,
                          f"rung{level + 1} done: ds<={ds} passes="
                          f"{conv.get('passes')} fds={conv.get('final_delta_s')}"
                          f" topped={topped}")
        ladder = ladder_pick(rungs, seat["gates"], seat["ladder_scalars"])
        verdict["ladder"] = ladder
        chosen = next((r for r in rungs
                       if r["level"] == ladder.get("chosen_level")), None)
        if chosen is None:
            n_top = sum(1 for r in rungs if r.get("topped"))
            n_unv = sum(1 for r in rungs if r.get("extraction_failed"))
            raise RuntimeError(
                f"ΔS 阶梯无可用档（触顶 {n_top} 档/收敛证据提取失败 {n_unv} 档；"
                "#335/#323）→ 该席不可判读（fail-closed）")
        # ⑥ G11 健康门（HFSS 全激励完整矩阵，掩码语义完备）
        verdict["g11"] = g11_health(chosen["_freq"], chosen["_s"], None,
                                    seat["g11"])
        # ⑦ 仲裁判读（#350 四态；x_ref 闭式解析按席回填）
        cf = oe.get("closed_form") or {}
        per_metric = []
        wf_notes: list[str] = []
        for gate in seat["gates"]:
            g = dict(gate)
            if (isinstance(g.get("x_ref"), str)
                    and g["x_ref"].startswith("closed_form:")
                    and "x_ref_f_peak_ghz" in cf):
                g["x_ref"] = cf["x_ref_f_peak_ghz"]
            row = judge_metric(chosen["metrics"].get(g["metric"]),
                               oe["values"].get(g["metric"]), g)
            # review-slice13 P1-1：censored 结构化流转进 per_metric（双侧
            # 分记，live 重跑自动在位，非离线手工补写/自由文本；门值与四态
            # 不因此改写——判据冻结 #122，定量引用禁令由 censored 字段+
            # implementation_notes 承载）
            cens = {"hfss": bool(chosen["metrics"].get(g["metric"]
                                                       + "_censored")),
                    "oe": bool(oe["values"].get(g["metric"] + "_censored"))}
            if cens["hfss"] or cens["oe"]:
                row["censored"] = cens
            # lesson-2（S2 审计 §3.2(b)/§3.4②）：病态背景弱特征门降级
            # info——背景判据独立重算（定位口带内最优匹配），降级行不翻
            # 总态（total_verdict 排除），观测分歧照实记录 + 注记留证。
            wf = weak_feature_downgrade(g, chosen["_freq"], chosen["_s"],
                                        seat)
            if wf is not None:
                row["weak_feature"] = wf
                if wf["downgraded"]:
                    wf_notes.append(
                        f"{g['metric']}: 病态背景弱特征降级 info（带内最优"
                        f"匹配 {wf['background_db']}dB > {wf['floor_db']}dB"
                        "，近全反射背景；lesson-2）——观测分歧照实记录、"
                        "不翻总态，不作物理结论引用")
            per_metric.append(row)
        verdict["per_metric"] = per_metric
        verdict["verdict"] = total_verdict(per_metric, cap=oe.get("cap"))
        verdict["hfss_metrics"] = dict(chosen["metrics"])
        # review-slice13 P3-A/P2补：bw 截断档明细结构化落 verdict（照 f_peak
        # notes 先例——判读所依赖的口径不得只存自由文本，离线复核不再依赖
        # 归档外重判脚本）
        bw_detail = next((chosen["metrics"][e["metric"] + "_detail"]
                          for e in seat["extractors"] if e["kind"] == "bw3db"
                          and e["metric"] + "_detail" in chosen["metrics"]),
                         None)
        if bw_detail is not None:
            verdict["bw_detail"] = bw_detail
        # lesson-3：argmin 型定位量双侧谷位图+深度矩阵出口（单值 f_* 语义
        # 不承载谷位；patch_2x2 排序翻转实证）。常量型 OE 无曲线 → 仅 HFSS
        # 侧如实缺位（不虚构）。
        vms: dict[str, Any] = {}
        for e in seat["extractors"]:
            key = e["metric"]
            h_vm = chosen["metrics"].get(key + "_valleys")
            o_vm = oe["values"].get(key + "_valleys")
            if h_vm is None and o_vm is None:
                continue
            entry: dict[str, Any] = {}
            if h_vm is not None:
                entry["hfss"] = h_vm
            if o_vm is not None:
                entry["oe"] = o_vm
            if h_vm is not None and o_vm is not None:
                entry["compare"] = valley_map_compare(h_vm, o_vm)
            vms[key] = entry
        if vms:
            verdict["valley_maps"] = vms
        # BALUN_GATES 记录项（marchand：记录不判，criteria §4 预声明）；
        # wave2mode 判据分派下模域矩阵非端接口径，记录项不适用（如实缺位，
        # 平衡量经 2 模反演离线判读）。
        if seat_name == "marchand_balun" and port_form == "lumped140":
            with contextlib.suppress(Exception):
                from rfauto.core.slotline_transitions import marchand_two_section_metrics

                m = marchand_two_section_metrics(chosen["_freq"], chosen["_s"],
                                                 (2.25, 2.75))
                verdict["balun_gates_record"] = {
                    k: m[k] for k in ("band_max_s11_db", "band_min_s21_db",
                                      "band_min_s31_db",
                                      "band_max_abs_imbalance_db",
                                      "band_max_phase_error_deg", "gates")}
        # ⑧ 预算守卫在 finally 统一计（超 1.5×=PARTIAL 如实，门不放宽；
        # FAIL/SKIP 路径同样计 wall，不因异常豁免预算诚实性）
        conv_notes = [
            f"ΔS 阶梯档 {lvl} 收敛证据提取失败（passes/final_delta_s 不可得）"
            "——该档如实 UNKNOWN 不判收敛门（#335/#323 fail-closed）"
            for lvl in ((verdict.get("ladder") or {}).get(
                "extraction_failed_levels") or [])]
        verdict["implementation_notes"] = [
            *(build.get("notes") or []),
            *_spec_notes(seat_name, port_form=port_form),
            *conv_notes,
            *(oe.get("notes") or []),
            *(chosen.get("metric_notes") or []),
            *wf_notes,
        ]
    except NotImplementedError as exc:
        verdict["verdict"] = "SKIP"
        verdict["status"] = "SKIP(实现待续)"
        verdict["error"] = str(exc)
    except LicenseBlockedError as exc:
        verdict["verdict"] = "SKIP"
        verdict["status"] = "SKIP(许可/进程阻塞)"
        verdict["error"] = str(exc)
    except Exception as exc:  # fail-closed：异常=FAIL+留痕（许可类→SKIP）
        if _is_license_error(exc):
            verdict["verdict"] = "SKIP"
            verdict["status"] = "SKIP(许可阻塞)"
            verdict["error"] = f"{type(exc).__name__}: {exc}"
        else:
            verdict["verdict"] = "FAIL"
            verdict["status"] = "FAIL(执行异常)"
            verdict["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        verdict["wall_s"] = round(time.monotonic() - t0, 1)
        # 预算守卫（超 1.5×=PARTIAL 如实；对任何 verdict 态生效，FAIL 语义不覆盖）
        if verdict["wall_s"] > 1.5 * seat["budget_min"] * 60:
            base = str(verdict.get("status") or "DONE")
            if "PARTIAL" not in base and verdict.get("verdict") != "FAIL":
                verdict["status"] = "PARTIAL(超预算)"
            elif "PARTIAL" not in base and verdict.get("verdict") == "FAIL":
                verdict["status"] = base + "+超预算"
        elif not verdict.get("status"):
            verdict["status"] = "DONE"
        # ⑨ finally release（#265 孤儿桌面铁律）+ 零残留留证
        if h is not None and hasattr(h, "release_desktop"):
            with contextlib.suppress(Exception):
                h.release_desktop(close_projects=True, close_desktop=True)
        if desktop is not None:
            with contextlib.suppress(Exception):
                desktop.release_desktop(close_on_exit=True, close_projects=False)
        if machine == "local" and not dry_run and residue_check:
            residue_after = check_ansysedt_residue()
            _write_json(out_dir / "ansysedt_check.json",
                        {"before": verdict.get("ansysedt_before"),
                         "after": residue_after,
                         "zero_residue": residue_after == 0})
            verdict["ansysedt_after"] = residue_after
    # ⑩ verdict 落盘（json+md，UTF-8 显式 #89）
    _write_json(out_dir / "verdict.json", verdict)
    with contextlib.suppress(OSError):
        (out_dir / "verdict.md").write_text(_verdict_md(seat_name, verdict),
                                            encoding="utf-8")
    _progress(out_dir, f"verdict={verdict.get('verdict')} status="
                       f"{verdict.get('status')} wall={verdict.get('wall_s')}s",
              dry_run=dry_run)
    return verdict


def _spec_notes(seat_name: str, port_form: str | None = None) -> list[str]:
    notes: list[str] = []
    if seat_name == "marchand_balun":
        notes.append(
            "criteria §2 预声明主判=2 模端口 S 反演；平衡侧两端子分居主线 ±y"
            "（非耦合对，x=结平面整截面切口含贯通主线共 3 导体），2 模大截面"
            "端口无位可落——按同段预声明的端接口径（P2/P3=140Ω 集总）落地，"
            "与 OE smoke 同端口同几何（#同源渲染）；f_null 主门依赖 P1 反射但 "
            "S11 经场耦合亦受平衡侧负载影响，端口口径对谷位的影响未单变量实证"
            "（review-slice11 P2-2 措辞修正）——对比有效性依据=两引擎同端口同"
            "几何同源渲染（同口径对比），非「端口口径无影响」。2 模反演路线留"
            "后续批（实现待续，criteria §8 状态注记）。")
        if resolve_marchand_port_form(seat_name, port_form) == "wave2mode":
            notes.append(
                "port_form=wave2mode 判据分派（criteria_for_run，S2 审计决策 2 "
                "发射面）：平衡侧=2 模大截面波端口（锚 A 同款，本注记所述「无位"
                "可落」指结平面整截面切口；馈线端横截面只含馈线+地，可落位）；"
                "判读面=P1 反射侧（f_null 主门 weak_feature 条件降级+s11_min "
                "信息项）；平衡量 band 门（s21/s31/imbalance）对模域 S 不可直接"
                "消费，经 2 模反演离线判读（锚 A 链，消费 run*.s5p 归档）——"
                "本运行=端口形态单变量对照，非完整仲裁；BALUN_GATES 记录项不"
                "适用（模域矩阵非端接口径）。")
    if seat_name == "gysel":
        notes.append(
            "S32 band_max 门值 −22.48dB 的产物实际判读带=2.25–2.75（README §4"
            " 标注 2.0–3.0 与 provenance 不符）——HFSS 侧同带 2.25–2.75 取值，"
            "如实注记。")
    return notes


# ═══════════════ 并行发射（wf:hfss-window-parallel）═══════════════
# 设计要点（--parallel N，缺省 1=现串行行为逐字节零变化）：
# - 端口分配：席位按发射序切波（每波 N 席），波内下标 i → gRPC 端口
#   base+i（base 缺省 50051=注册表 DEFAULT_GRPC_PORT 同源，波次复用）；
# - 发射隔离选型=**多进程**（每席独立子进程跑本脚本 --seat）：open_remote_hfss
#   经 remote_session_switches 做 pyaedt 进程级全局 settings+env 保存/恢复，
#   线程并发进入/退出互相踩恢复值（共享可变态在）；子进程隔离单席崩溃/挂死
#   （#157 家族）不连坐；判读面 CPU 活也不与求解争 GIL；
# - 服务器侧多实例：每席独立 ``ansysedt -grpcsrv <host>:<port>:InsecureMode``。
#   共享 helper 核对结论：remote_service._launch_grpcsrv 端口取自 cfg（按理
#   dataclasses.replace 可 per-port）但其 bat 落点=固定共享名 launch_grpcsrv.bat
#   （project_root 下），并发/波间重写竞态不安全；remote_hfss_cleanup 虽按
#   grpc_match 端口指纹精确杀，但带 RFAUTO_REMOTE_SMOKE env 门（静默跳过清理
#   =孤儿桌面 #265 风险）。故本驱动自带 per-port 变体：vbs=launch_grpcsrv_
#   <port>.vbs、任务=RFAuto\\hfss_window_<port>_<hex8>（schtasks 唯一名）、
#   清理=命令行含 -grpcsrv 且含 ":<port>:" 指纹才杀（fix4 口径，多实例天然
#   不互杀）。静默化（wf:silent-launch-p8，2026-09-29 用户痛点：schtasks 跑
#   .bat=cmd 宿主窗可见+bat 直接拉 ansysedt=控制台窗，服务器桌面黑框积累）：
#   bat 全弃改 VBScript 包装——WScript.Shell.Run "<cmd>", 0, False（windowstyle
#   0=完全无窗、False=异步不等待），schtasks /tr 改 wscript.exe <vbs>（wscript
#   为 GUI 宿主自身无控制台）；清理面（指纹杀+任务删除）不变；
# - 预算池语义：并行下墙钟=波内 max（非求和），campaign 墙钟=Σ 波 max；
# - 残留守卫（#265）上移编排器：local 真机波前一次性 residue==0 门 + 波后
#   FAIL 即查；席位子进程 --no-residue-check（兄弟席实例不算残留）。

def partition_waves(seat_names: list[str] | tuple[str, ...],
                    parallel: int) -> list[list[str]]:
    """席位按发射序切波：每波 parallel 席，波内全完成进下波（纯函数）。"""
    parallel = int(parallel)
    if parallel < 1:
        raise ValueError(f"parallel 必须 ≥1（got {parallel}）")
    names = [str(n) for n in seat_names]
    return [names[i:i + parallel] for i in range(0, len(names), parallel)]


def assign_seat_ports(seat_names: list[str] | tuple[str, ...], parallel: int,
                      port_base: int = DEFAULT_GRPC_PORT_BASE) -> dict[str, int]:
    """席位→gRPC 端口：base + 波内下标（50051+0..N-1，波次复用；纯函数）。

    与 partition_waves 同构：第 w 波第 j 席的端口=base+j，下一波同下标席位
    复用同端口（上一波已清理）。parallel=1 时全部席位映射 base+0（串行路径
    并不消费该映射，仅规划面一致）。
    """
    parallel = int(parallel)
    if parallel < 1:
        raise ValueError(f"parallel 必须 ≥1（got {parallel}）")
    base = int(port_base)
    return {str(name): base + (i % parallel)
            for i, name in enumerate(seat_names)}


def launch_remote_grpcsrv(machine: str, port: int, *,
                          grpc_wait_s: float = 90.0,
                          extra_cli_args: str = "-ng") -> dict[str, Any]:
    """服务器侧静默拉起独立 ``ansysedt -grpcsrv <host>:<port>:InsecureMode``
    监听（per-port 变体，remote_service._launch_grpcsrv 同款流程，见节首核对
    结论）。

    步骤：端口占用预检（已有监听=疑残留实例，fail-closed 不代杀 #265）→
    服务器侧工作根 → sftp 传 per-port vbs → schtasks 注册+触发（唯一任务名，
    wscript.exe 静默宿主）→ 轮询 gRPC 端口开。返回 ``{"ok": True, "port",
    "task_name", "vbs"}`` 或 ``{"ok": False, "reason", "steps"}``（best-effort
    观测面，信封不抛）。``extra_cli_args``：追加给 ansysedt 的开关，缺省
    ``-ng``（无头服务器，L2 验证版同款）。

    静默语义（wf:silent-launch-p8）：vbs 单行 ``CreateObject("WScript.Shell")
    .Run "<cmd>", 0, False``（<cmd> 含带引号 exe 路径+参数，VBScript 字符串内
    双引号按两个连续引号转义）——windowstyle 0=目标窗完全隐藏、False=异步
    不等待（schtasks 触发即返回，不占任务进程）；wscript.exe 为 GUI 宿主
    自身无控制台，全程零可见窗（旧 per-port .bat 形态的 cmd 黑框双源根治，
    bat 已全弃无兼容路径）。
    """
    port = int(port)
    transport = None
    steps: dict[str, Any] = {}
    try:
        from rfauto.infra.remote_machines import SshTransport, load_remote_machines, probe_port, resolve_machine

        cfg = resolve_machine(machine, load_remote_machines())
        transport = SshTransport(cfg)
        transport.connect()
        if not cfg.hfss_ansysedt_exe:
            return {"ok": False, "port": port,
                    "reason": "机器未登记 hfss.ansysedt_exe（无法拉起 grpcsrv 监听）",
                    "steps": steps}
        open_pre, _ms = probe_port(cfg.host, port, timeout_s=2.0)
        if open_pre:
            return {"ok": False, "port": port,
                    "reason": (f"端口 {port} 已有监听（疑残留 grpcsrv 实例）——"
                               "不代杀，人工核对后重跑或 --port-base 换段"),
                    "steps": steps}
        work_root = cfg.hfss_project_root.replace("/", "\\")
        rc, _out, err = transport.run_command(
            f"New-Item -ItemType Directory -Force -Path '{work_root}' | Out-Null",
            timeout_s=20.0)
        if rc != 0:
            return {"ok": False, "port": port,
                    "reason": f"服务器侧工作根创建失败: {err[:120]}",
                    "steps": steps}
        # per-port vbs 落点：并发多实例互不覆盖（共享固定名的根治）
        vbs_remote = (f"{cfg.hfss_project_root}/launch_grpcsrv_{port}.vbs"
                      .replace("\\", "/"))
        exe = cfg.hfss_ansysedt_exe.replace("/", "\\")
        prefix = f"{extra_cli_args} " if extra_cli_args else ""
        vbs_line = (f'CreateObject("WScript.Shell").Run """{exe}"" {prefix}'
                    f"-grpcsrv {cfg.host}:{port}:InsecureMode\", 0, False\r\n")
        with tempfile.TemporaryDirectory() as td:
            vbs_local = Path(td) / f"launch_grpcsrv_{port}.vbs"
            vbs_local.write_bytes(vbs_line.encode("ascii"))
            transport.upload_file(vbs_local, vbs_remote)
        steps["vbs_upload"] = {"remote": vbs_remote}
        task_name = f"RFAuto\\hfss_window_{port}_{uuid.uuid4().hex[:8]}"
        schtasks: dict[str, Any] = {"task_name": task_name}
        steps["schtasks"] = schtasks
        vbs_win = f"{cfg.hfss_project_root}\\launch_grpcsrv_{port}.vbs"
        # /tr 内层引号用 PowerShell 单引号外包裹（远端 exec 缺省 shell=PowerShell，
        # New-Item 同通道实证；双引号嵌套在 PS 会被吞）
        for cmd, label in (
            (f"schtasks /create /f /tn \"{task_name}\" "
             f"/tr 'wscript.exe \"{vbs_win}\"' /sc once /st 23:59", "create"),
            (f"schtasks /run /tn \"{task_name}\"", "run"),
        ):
            rc, _out, err = transport.run_command(cmd, timeout_s=30.0)
            schtasks[label] = rc
            if rc != 0:
                schtasks["stderr_head"] = err[:200]
                return {"ok": False, "port": port,
                        "reason": f"schtasks {label} 非零退出（rc={rc}）",
                        "steps": steps}
        deadline = time.monotonic() + grpc_wait_s
        opened = False
        while time.monotonic() < deadline:
            opened, _ms = probe_port(cfg.host, port, timeout_s=2.0)
            if opened:
                break
            time.sleep(2.0)
        if not opened:
            return {"ok": False, "port": port,
                    "reason": f"grpcsrv 端口 {port} 等待超时（>{grpc_wait_s:.0f}s）",
                    "steps": steps}
        steps["grpc_port_open"] = True
        return {"ok": True, "port": port, "task_name": task_name,
                "vbs": vbs_remote, "steps": steps}
    except Exception as exc:
        return {"ok": False, "port": port,
                "reason": f"{type(exc).__name__}: {str(exc)[:160]}",
                "steps": steps}
    finally:
        if transport is not None:
            with contextlib.suppress(Exception):
                transport.close()


def cleanup_remote_grpcsrv(machine: str, port: int, *,
                           task_name: str | None = None) -> dict[str, Any]:
    """per-port 清理（fix4 端口指纹口径）：Query Win32_Process 取 ansysedt
    命令行，只杀含 ``-grpcsrv`` 且含 ``":<port>:"`` 指纹的实例——多波并行
    复用端口逐席清理、多实例不互杀、共享机他人实例不误杀（#261 自排除同
    源）；schtasks 只删本席唯一任务名。无匹配=0 杀如实上报。best-effort
    （#105）：失败返回失败信封不抛，绝不阻塞主路径。"""
    port = int(port)
    transport = None
    steps: dict[str, Any] = {}
    try:
        from rfauto.infra.remote_machines import SshTransport, load_remote_machines, resolve_machine

        cfg = resolve_machine(machine, load_remote_machines())
        transport = SshTransport(cfg)
        transport.connect()
        _rc, out, _err = transport.run_command(
            "Get-CimInstance Win32_Process -Filter \"Name='ansysedt.exe'\" | "
            "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }",
            timeout_s=30.0)
        fingerprint = f":{port}:"
        targets: list[str] = []
        for line in out.splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            pid_s, _, cmdline = line.partition("|")
            if not pid_s.strip().isdigit():
                continue
            lowered = cmdline.lower()
            if "grpcsrv" not in lowered:
                continue
            if fingerprint.lower() not in lowered:
                continue
            targets.append(pid_s.strip())
        steps["ansysedt_grpcsrv_pids"] = targets
        if targets:
            kill_rc, _o, _e = transport.run_command(
                "taskkill /F " + " ".join(f"/PID {p}" for p in targets),
                timeout_s=30.0)
            steps["kill_rc"] = kill_rc
        if task_name:
            transport.run_command(f"schtasks /delete /f /tn \"{task_name}\"",
                                  timeout_s=20.0)
            steps["deleted_tasks"] = [task_name]
        return {"ok": True, "port": port, "killed_pids": targets, "steps": steps}
    except Exception as exc:
        return {"ok": False, "port": port,
                "reason": f"{type(exc).__name__}: {str(exc)[:160]}",
                "steps": steps}
    finally:
        if transport is not None:
            with contextlib.suppress(Exception):
                transport.close()


def _seat_argv(seat_name: str, *, machine: str, out_dir: Path,
               dry_run: bool, grpc_port: int | None,
               residue_check: bool,
               marchand_port_form: str | None = None) -> list[str]:
    """单席子进程 argv（父编排器→子 driver 的全链参数携带）。"""
    argv = [sys.executable, str(Path(__file__).resolve()),
            "--seat", seat_name, "--machine", machine,
            "--out-dir", str(out_dir)]
    if dry_run:
        argv.append("--dry-run")
    if grpc_port is not None:
        argv += ["--grpc-port", str(int(grpc_port))]
    if not residue_check:
        argv.append("--no-residue-check")
    if marchand_port_form is not None:
        argv += ["--marchand-port-form", str(marchand_port_form)]
    return argv


def _spawn_seat(argv: list[str], out_dir: Path, log_fh) -> Any:
    """单席子进程发射（会合版：父进程 wait 收 per-seat verdict；子进程
    stdout/stderr 落 seat_subprocess.log，#242 stdout cap 不触主链路）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(argv, stdout=log_fh, stderr=subprocess.STDOUT)


def _read_seat_verdict(out_dir: Path) -> dict[str, Any] | None:
    try:
        return json.loads(
            (Path(out_dir) / "verdict.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def _parent_progress(root: Path, msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with contextlib.suppress(OSError), \
            (Path(root) / "window_parallel.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run_all_parallel(machine: str, dry_run: bool, parallel: int,
                     port_base: int = DEFAULT_GRPC_PORT_BASE,
                     out_root: Path | None = None,
                     max_parallel_cap: dict[str, Any] | None = None) -> int:
    """--all --parallel N>1 波次编排（run_all 路由入口；N=1 走串行零变化）。

    波内 N 席并行（每席独立子进程），波内全完成进下波；remote 真机路径波前
    逐席拉起独立 grpcsrv（端口=base+波内下标）、波后 per-port 指纹清理；
    local 真机路径波前一次性 residue==0 门、波后 FAIL 即查（#265）。预算池：
    波墙钟=波内 max（非求和），campaign 墙钟=Σ 波 max。退出码语义与串行同源
    （FAIL/不可判读→1；SKIP→2；合法裁决→0）。

    v1 调度面（2026-09-29）：remote 真机路径**波前 license 预检**（fail-closed：
    不过=整波席位 SKIP 如实落 verdict.json，不拉 grpcsrv 不硬打；下波重探，
    license 中途恢复则后续波照常）；``max_parallel_cap``（run_all 按 注册表
    ``hfss.max_parallel`` 收敛 --parallel 后传入的记账 dict）非 None 时随
    window_summary.json 落档（local 路径恒 None=summary 零新增键）。
    """
    parallel = int(parallel)
    if parallel < 2:
        raise ValueError("run_all_parallel 需要 parallel≥2（1=串行走 run_all）")
    root = Path(out_root) if out_root is not None else OUT_ROOT
    names = list(LAUNCH_ORDER)
    ports = assign_seat_ports(names, parallel, port_base)
    waves = partition_waves(names, parallel)
    remote_real = machine != "local" and not dry_run
    local_real = machine == "local" and not dry_run
    summary: list[dict[str, Any]] = []
    waves_meta: list[dict[str, Any]] = []
    stopped_reason: str | None = None

    if local_real:
        residue = check_ansysedt_residue()
        if residue > 0:
            stopped_reason = (f"本机 ansysedt 残留 {residue} 个（#265）"
                              "——并行波前守卫，不代杀")
            _parent_progress(root, stopped_reason)
            for name in names:
                summary.append({"seat": name, "verdict": "SKIP",
                                "status": "SKIP(本机 ansysedt 残留)",
                                "wall_s": 0.0})

    for w_idx, wave in enumerate(waves, start=1):
        if stopped_reason is not None:
            break
        _parent_progress(root, f"wave {w_idx}/{len(waves)}: {list(wave)} "
                               f"ports={[ports[n] for n in wave]}")
        launch_env: dict[str, dict[str, Any]] = {}
        if remote_real:
            # 波前 license 预检（v1 调度面）：不过→整波 SKIP 不发射（不拉
            # grpcsrv 不硬打），逐席 verdict.json 记账；下波重探（license
            # 中途恢复则后续波照常发射）。
            pre = remote_license_preflight(machine)
            if pre.get("verdict") != "PASS":
                _parent_progress(root, f"wave {w_idx} license 预检未过"
                                       f"（{pre.get('reason')}）——整波 SKIP"
                                       " 不硬打")
                for name in wave:
                    out_dir = default_out_dir(name, machine, root=root)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    skip_v = {"seat": name,
                              "template": SEATS[name]["template"],
                              "machine": machine, "verdict": "SKIP",
                              "status": "SKIP(license 预检未过)",
                              "license_preflight": pre,
                              "grpc_port": ports[name]}
                    _write_json(out_dir / "verdict.json", skip_v)
                    summary.append({"seat": name, "verdict": "SKIP",
                                    "status": skip_v["status"], "wall_s": 0.0,
                                    "grpc_port": ports[name]})
                waves_meta.append({"wave": w_idx, "seats": list(wave),
                                   "ports": {n: ports[n] for n in wave},
                                   "wall_s_max": 0.0,
                                   "license_gate": {"verdict": pre.get("verdict"),
                                                    "reason": pre.get("reason")},
                                   "launch": None, "cleanup": None})
                continue
            wave_gate: dict[str, Any] = {"verdict": pre.get("verdict"),
                                         "reason": pre.get("reason")}
        else:
            wave_gate = None
        if remote_real:
            for name in wave:
                # 逐席串行拉起（每席等端口开再下一席）：vbs 落点 per-port 本
                # 已无竞态，串行拉起让探活语义逐席清晰、失败定位到席
                launch_env[name] = launch_remote_grpcsrv(machine, ports[name])
        procs: dict[str, tuple[Any, Path, Any]] = {}
        for name in wave:
            out_dir = default_out_dir(name, machine, root=root)
            if remote_real and not launch_env[name].get("ok"):
                fail_v = {"seat": name, "template": SEATS[name]["template"],
                          "machine": machine, "verdict": "FAIL",
                          "status": "FAIL(grpcsrv 拉起失败)",
                          "error": launch_env[name].get("reason"),
                          "grpc_port": ports[name]}
                _write_json(out_dir / "verdict.json", fail_v)
                summary.append({"seat": name, "verdict": "FAIL",
                                "status": fail_v["status"], "wall_s": 0.0,
                                "grpc_port": ports[name],
                                "error": fail_v["error"]})
                continue
            argv = _seat_argv(
                name, machine=machine, out_dir=out_dir, dry_run=dry_run,
                grpc_port=(ports[name] if remote_real else None),
                residue_check=not local_real)
            out_dir.mkdir(parents=True, exist_ok=True)
            log_fh = (out_dir / "seat_subprocess.log").open("wb")
            procs[name] = (_spawn_seat(argv, out_dir, log_fh), out_dir, log_fh)
        wave_entries: list[dict[str, Any]] = []
        for name in wave:
            if name not in procs:
                continue
            proc, out_dir, log_fh = procs[name]
            rc = proc.wait()
            log_fh.close()
            v = _read_seat_verdict(out_dir)
            if v is None:
                entry: dict[str, Any] = {
                    "seat": name, "verdict": "FAIL",
                    "status": "FAIL(verdict 缺失——子进程未落盘)",
                    "wall_s": None, "rc": rc}
            else:
                entry = {"seat": name, "verdict": v.get("verdict"),
                         "status": v.get("status"),
                         "wall_s": v.get("wall_s"), "rc": rc}
            wave_entries.append(entry)
            summary.append(entry)
        wall_max = max([e["wall_s"] for e in wave_entries
                        if e["wall_s"] is not None] or [0.0])
        cleanup_env: dict[str, dict[str, Any]] = {}
        if remote_real:
            for name in wave:
                cleanup_env[name] = cleanup_remote_grpcsrv(
                    machine, ports[name],
                    task_name=launch_env.get(name, {}).get("task_name"))
        wave_entry: dict[str, Any] = {"wave": w_idx, "seats": list(wave),
                                      "ports": {n: ports[n] for n in wave},
                                      "wall_s_max": wall_max,
                                      "launch": launch_env or None,
                                      "cleanup": cleanup_env or None}
        if remote_real:
            # v1 调度面：波级 license 预检留痕（local 波零新增键=零变化）
            wave_entry["license_gate"] = wave_gate
        waves_meta.append(wave_entry)
        if local_real and any(e.get("verdict") == "FAIL"
                              for e in wave_entries):
            residue_after = check_ansysedt_residue()
            if residue_after > 0:
                stopped_reason = ("FAIL 后 ansysedt 残留——后续波停（#265，不代杀）")
                _parent_progress(root, stopped_reason)

    total_wall = round(sum(w["wall_s_max"] for w in waves_meta), 1)
    summary_payload: dict[str, Any] = {
        "machine": machine, "dry_run": dry_run,
        "parallel": parallel, "port_base": int(port_base),
        "order": names, "seat_ports": {n: ports[n] for n in names},
        "waves": waves_meta, "seats": summary,
        "wall_s_campaign": total_wall,
        "budget_pool_note": "并行墙钟=波内 max（非求和）；wall_s_campaign=Σ波max",
        "stopped_reason": stopped_reason,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    if max_parallel_cap is not None:
        # v1 调度面：hfss.max_parallel 闸记账（run_all 传入；local 恒 None）
        summary_payload["max_parallel_cap"] = max_parallel_cap
    _write_json(root / "window_summary.json", summary_payload)
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
    states = [s.get("verdict") for s in summary]
    if any(v not in _OK_VERDICTS and v != "SKIP" for v in states):
        return 1
    if any(v == "SKIP" for v in states):
        return 2
    return 0


def run_all(machine: str = "local", dry_run: bool = False, *,
            parallel: int = 1,
            port_base: int = DEFAULT_GRPC_PORT_BASE,
            out_root: Path | None = None,
            marchand_port_form: str | None = None) -> int:
    """按 README 发射序编排：parallel=1（缺省）串行 solo（相邻席 ansysedt
    零残留检查 #265，行为逐字节零变化）；parallel>1 波内并行
    （run_all_parallel，wf:hfss-window-parallel）。

    marchand_port_form：仅与 --seat marchand_balun 单席路径同用（S2 决策 2
    发射面）；--all 批量编排禁用（端口形态单变量对照不进批量波次）。

    退出码与单席语义同源（review-slice3 P3：--all 恒 0 修复）：任一席
    FAIL/UNDECIDABLE→1；无 FAIL 但有 SKIP→2；全部合法裁决态→0。
    """
    parallel = int(parallel)
    if parallel < 1:
        raise ValueError(f"--parallel 必须 ≥1（got {parallel}）")
    if marchand_port_form is not None:
        raise ValueError("--marchand-port-form 仅与 --seat marchand_balun "
                         "同用（--all 批量编排不适用端口形态单变量对照）")
    cap_note: dict[str, Any] | None = None
    if machine != "local" and parallel > 1:
        # v1 调度面（2026-09-29）：远程真机并行度受注册表 hfss.max_parallel
        # 闸（缺省 2=实测可用档，playbook §2.4）——发射侧收敛，超额部分记档；
        # local 路径零注册表读零行为变化。
        cap = remote_max_parallel(machine)
        if cap is not None and parallel > int(cap):
            cap_note = {"declared": int(parallel), "effective": int(cap),
                        "source": ("hfss.max_parallel（注册表；缺省 2="
                                   "实测可用档，playbook §2.4）")}
            print(f"[window] --parallel {parallel} → {cap}"
                  "（hfss.max_parallel 注册表闸）", flush=True)
            parallel = int(cap)
    if parallel > 1:
        return run_all_parallel(machine, dry_run, parallel,
                                port_base=port_base, out_root=out_root,
                                max_parallel_cap=cap_note)
    summary: list[dict] = []
    for seat_name in LAUNCH_ORDER:
        v = run_seat(seat_name, machine=machine, dry_run=dry_run)
        summary.append({"seat": seat_name, "verdict": v.get("verdict"),
                        "status": v.get("status"), "wall_s": v.get("wall_s")})
        if (v.get("verdict") == "FAIL" and machine == "local"
                and not dry_run and (check_ansysedt_residue() or 0) > 0):
            _progress(default_out_dir(seat_name, machine),
                      "FAIL 后 ansysedt 残留——后续席停（#265，不代杀）")
            break
    _write_json(OUT_ROOT / "window_summary.json",
                {"machine": machine, "dry_run": dry_run,
                 "order": list(LAUNCH_ORDER), "seats": summary,
                 "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
    states = [s.get("verdict") for s in summary]
    if any(v not in _OK_VERDICTS and v != "SKIP" for v in states):
        return 1
    if any(v == "SKIP" for v in states):
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="HFSS 窗 B→A 仲裁 8 席执行编排（判据 runs/hfss_window_b2a/；"
                    "本驱动交付=零发射，真机由主代理择机）")
    parser.add_argument("--seat", choices=LAUNCH_ORDER, default=None,
                        help="单席（与 --all 二选一）")
    parser.add_argument("--all", action="store_true",
                        help="按 README 发射序全部 8 席（缺省 solo 串行）")
    parser.add_argument("--machine", choices=("local", "sim_host"),
                        default="local",
                        help="会话目标（缺省 local；sim_host=远程注册表机器）")
    parser.add_argument("--remote", nargs="?", const="", default=None,
                        metavar="MACHINE",
                        help="战役路由到注册表远程机器（v1 调度面，2026-09-29）："
                             "发射前 license 预检 fail-closed（license 端口不通"
                             "→该座 SKIP 不硬打）；远程真机并行度受注册表 "
                             "hfss.max_parallel 闸（缺省 2）。不带值=唯一登记机器；"
                             "与 --machine 互斥；缺省（不带 --remote）=local "
                             "行为零变化")
    parser.add_argument("--out-dir", default=None,
                        help="产物目录（缺省 runs/hfss_window_b2a/<t>/hfss_side）")
    parser.add_argument("--dry-run", action="store_true",
                        help="离线端到端（合成 S，零 pyaedt 零求解）——交付 dry-call 钉")
    parser.add_argument("--parallel", type=int, default=1,
                        help="并行度（仅与 --all 同用；缺省 1=现串行行为零变化；"
                             "N>1 波内 N 席并行，每席独立子进程+独立 grpcsrv 实例）")
    parser.add_argument("--port-base", type=int, default=DEFAULT_GRPC_PORT_BASE,
                        help="并行远程 grpcsrv 端口基址（席位按波内下标分 "
                             "base+0..N-1，波次复用；缺省 50051）")
    parser.add_argument("--grpc-port", type=int, default=None,
                        help="单席远程 grpc 端口覆盖（仅与 --seat 同用；缺省读"
                             "注册表 cfg.hfss_grpc_port）")
    parser.add_argument("--no-residue-check", action="store_true",
                        help="跳过本机 ansysedt 残留检查（#265；仅并行编排器"
                             "传入——兄弟席实例不算残留，守卫上移波前/波后）")
    parser.add_argument("--marchand-port-form", choices=MARCHAND_PORT_FORMS,
                        default=None,
                        help="marchand 端口形态发射面（S2 审计决策 2；仅与 "
                             "--seat marchand_balun 同用；缺省 lumped140="
                             "已落档行为零变化；wave2mode=平衡侧 2 模大截面"
                             "波端口单变量对照——判据分派 criteria_for_run、"
                             "导出 .s5p、产物目录 hfss_side_wave2mode 隔离，"
                             "平衡量 2 模反演离线判读；本批只备发射面不发射）")
    parser.add_argument("--list", action="store_true",
                        help="打印发射序与预算后退出")
    args = parser.parse_args(argv)

    # --remote 路由解析（v1 调度面）：先于 --list/--seat 校验——只在本参数
    # 给出时读注册表（缺省 local 零注册表读零行为变化）；解析失败=argparse
    # 级报错（SystemExit 2），不发进编排层。
    if args.remote is not None:
        if args.machine != "local":
            parser.error("--remote 与 --machine 互斥（路由目标二选一）")
        if args.remote.strip().lower() == "local":
            parser.error("--remote 用于远程分派；本机路径省略 --remote 即可")
        from rfauto.infra.remote_machines import RemoteConfigError, load_remote_machines, resolve_machine

        try:
            remote_cfg = resolve_machine(args.remote.strip() or None,
                                         load_remote_machines())
        except RemoteConfigError as exc:
            parser.error(f"--remote 机器解析失败: {exc}")
        if remote_cfg is None:
            parser.error("--remote：注册表无登记机器"
                         "（configs/remote_machines.yaml）")
        args.machine = remote_cfg.name

    if args.list:
        for name in LAUNCH_ORDER:
            seat = SEATS[name]
            print(f"{seat['order']}. {name:20s} budget={seat['budget_min']}min "
                  f"window={seat['window_ghz']} ports={seat['n_ports']} "
                  f"builder={seat.get('builder_status', 'full')}")
        return 0
    if not args.all and args.seat is None:
        parser.error("--seat 或 --all 必选其一（--list 查看发射序）")
    if args.parallel < 1:
        parser.error(f"--parallel 必须 ≥1（got {args.parallel}）")
    if args.parallel > 1 and not args.all:
        parser.error("--parallel>1 仅与 --all 同用（单席无并行语义）")
    if args.grpc_port is not None and args.all:
        parser.error("--grpc-port 仅与 --seat 同用（--all 端口由 "
                     "--port-base 分配器分配）")
    if args.marchand_port_form is not None:
        if args.all:
            parser.error("--marchand-port-form 仅与 --seat 同用（--all 批量"
                         "编排不适用端口形态单变量对照）")
        if args.seat != "marchand_balun":
            parser.error("--marchand-port-form 仅适用 --seat marchand_balun")
    if args.all:
        return run_all(machine=args.machine, dry_run=args.dry_run,
                       parallel=args.parallel, port_base=args.port_base,
                       out_root=(Path(args.out_dir) if args.out_dir
                                 else None))
    out_dir = Path(args.out_dir) if args.out_dir else None
    v = run_seat(args.seat, machine=args.machine, out_dir=out_dir,
                 dry_run=args.dry_run, grpc_port=args.grpc_port,
                 residue_check=not args.no_residue_check,
                 marchand_port_form=args.marchand_port_form)
    state = v.get("verdict")
    if state in _OK_VERDICTS:
        return 0
    return 2 if state == "SKIP" else 1


if __name__ == "__main__":
    raise SystemExit(main())
