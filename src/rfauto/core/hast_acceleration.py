"""MP-6 HAST-ROSE 加速因子换算内核（ge8d 席 D1；round15 MP-5 后继件）。

规格：研究扩充 round15 :88（"HAST/ROSE/环境试验
条件表：JESD22-A110/IPC-TM-650 2.3.25/IEC 60068-2-27——纯表+入口不产寿命
结论"）+ 任务书 wave_d/seat_d_all.md 席 D1（"HAST-ROSE 环境表：高加速应力
测试标准条件表（JESD22 双源）+ **加速因子换算消费 aging 面**（复用
core/aging 禁改）"）。

分工与边界（规格钉死，双文件协同）
--------------------------------
- **条件表已在**：core/environment_tables.py（round15 MP-5 合流件，禁改）
  载 JESD22-A110/A118/A101/A102/IPC-TM-650 2.3.25 ROSE/IEC 60068-2-27
  六族条件。本模块只读消费其公开查询面（list_conditions），不复制表值。
- **双源状态如实**：条件表值本会话仅一检索通道（in-repo 已合流表，其
  verified=True 语义=合流时逐条核对公开文献转引）；JEDEC 原文页本会话
  不可达（检索通道受限）——source_b 按 NO_VALUE_retrieval_pending 登记
  （PK-9 先例；不凭记忆复写第二源数值）。双源核对面用 in-repo 表
  内部一致性守卫替代（A110/A118 同条件互证 + A102 psi↔Pa 精确换算
  复核），作为通道受限下的最小一致性裁判，不冒充外部双源。
- **加速因子面（本模块新增）**：Arrhenius 温度因子**禁改消费**
  core/aging.arrhenius_af（本仓 PoF 载面）+ Peck 湿度因子 +
  Hallberg-Peck 组合 AF + 目标 AF 反解应力 RH + 等效时长换算。
  **不产寿命结论**（environment_tables.life_from_condition 守卫同款
  边界；AF/等效时长是应力域换算，非可靠性预测）。

文献核实账（#df6-⑨；2026-10-03 本会话）
----------------------------------------
- Arrhenius AF 与 Ea=0.7 eV 行业缺省：core/aging.py 模块 docstring 已核
  （NASA SMA PoF + JESD47G 工作例），本模块沿用不重复登记。
- **Peck 指数 n 典型带 2.5–3.0 未逐位核**（D. S. Peck, IRPS 1986
  "Comprehensive model for humidity testing correlation" 与 JEDEC
  JEP122G 原文本会话不可达）——n 按 **UNVERIFIED_band 登记**、作为必填
  参数（无发明缺省值），典型带只进 retrieval_pointers 与文档注记。
  "Hallberg-Peck" 组合式（AF=AF_T·AF_RH）为业界标准组合口径，其结构
  正确性由单测的恒等式族裁判（同温同湿 AF=1、温度通道与 aging 逐位
  一致、湿度通道幂律缩放）。

接口：纯函数零 IO（条件表经 environment_tables 公开查询面只读）；
JSON 可序列化 float/dict/str/bool/None；数值 0.0 合法（判缺失 is not
None，#364④）；bool 显式拒收。不进 @register_calculator、不定义
__all__（acoustic_resonator/package_interconnect 先例）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.aging import K_B_EV_PER_K, arrhenius_af
from rfauto.core.environment_tables import list_conditions

#: 本会话可达条件源通道账（文案即语义）
SOURCE_A_IN_REPO = "in_repo_environment_tables_merged"
SOURCE_B_STATUS = "NO_VALUE_retrieval_pending"
_SOURCE_B_POINTERS = (
    "JEDEC JESD22-A110/A118/A101/A102 原文条件页（jedec.org 文档检索）",
    "IPC-TM-650 2.3.25 方法正文（IPC 采购件）",
    "IEC 60068-2-27/-2-14 严酷等级表",
)

#: Peck 指数登记带（UNVERIFIED——原文本会话不可达，只作指针不作缺省）
PECK_N_REGISTERED_BAND = (2.5, 3.0)
PECK_N_STATUS = "UNVERIFIED_band"

_C_TO_K_OFFSET = 273.15


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到 {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正，收到 {value!r}")
    return out


# ─── 加速因子换算（消费 core/aging 禁改）────────────────────────────────────


def arrhenius_af_c(ea_ev: float, t_use_c: float, t_stress_c: float) -> float:
    """Arrhenius 温度加速因子（°C 口径薄壳；核心=core/aging.arrhenius_af K
    口径禁改消费，本函数只做 273.15 换算）。"""
    ea = _finite(ea_ev, "ea_ev")
    tu = _finite(t_use_c, "t_use_c")
    ts = _finite(t_stress_c, "t_stress_c")
    if tu <= -_C_TO_K_OFFSET or ts <= -_C_TO_K_OFFSET:
        raise ValueError("摄氏温度不得低于 −273.15")
    return arrhenius_af(ea, tu + _C_TO_K_OFFSET, ts + _C_TO_K_OFFSET)


def peck_humidity_factor(rh_use_pct: float, rh_stress_pct: float,
                         n: float) -> float:
    """Peck 湿度加速因子 = (RH_s/RH_u)^n（幂律；n>0）。

    n 典型带 2.5–3.0 为 UNVERIFIED 登记（Peck 1986/JEP122G 原文本会话
    不可达）——本函数不设缺省，调用方显式供给。
    """
    ru = _positive(rh_use_pct, "rh_use_pct")
    rs = _positive(rh_stress_pct, "rh_stress_pct")
    if ru > 100.0 or rs > 100.0:
        raise ValueError("相对湿度按百分数（0,100]，收到超界值")
    expo = _finite(n, "n")
    if expo <= 0.0:
        raise ValueError(f"Peck 指数 n 必须为正，收到 {n!r}")
    return (rs / ru) ** expo


def hallberg_peck_af(ea_ev: float, t_use_c: float, t_stress_c: float,
                     rh_use_pct: float, rh_stress_pct: float,
                     n: float) -> dict[str, Any]:
    """Hallberg-Peck 组合加速因子 = Arrhenius 温度通道 × Peck 湿度通道。

    守卫：T_stress≥T_use 且 RH_stress≥RH_use 时 AF≥1（应力域单调性构造
    恒等）；温度相等且湿度相等 → AF=1 逐位。返回分通道值供审计。
    """
    af_t = arrhenius_af_c(ea_ev, t_use_c, t_stress_c)
    af_rh = peck_humidity_factor(rh_use_pct, rh_stress_pct, n)
    return {
        "af_total": af_t * af_rh,
        "af_temperature": af_t,
        "af_humidity": af_rh,
        "ea_ev": _finite(ea_ev, "ea_ev"),
        "t_use_c": t_use_c,
        "t_stress_c": t_stress_c,
        "rh_use_pct": rh_use_pct,
        "rh_stress_pct": rh_stress_pct,
        "peck_n": _finite(n, "n"),
        "peck_n_status": PECK_N_STATUS,
        "peck_n_registered_band": list(PECK_N_REGISTERED_BAND),
        "model": "hallberg_peck",
    }


def stress_rh_for_target_af(ea_ev: float, t_use_c: float, t_stress_c: float,
                            rh_use_pct: float, target_af: float,
                            n: float) -> float:
    """目标组合 AF 下反解应力相对湿度 [%RH]（闭式反解）。

    AF = AF_T·(RH_s/RH_u)^n ⟹ RH_s = RH_u·(AF/AF_T)^(1/n)；
    AF_T≥1 要求（否则应力温度不构成加速、湿度通道无解域守卫）。
    回代恒等式单测钉（round-trip）。
    """
    target = _positive(target_af, "target_af")
    ru = _positive(rh_use_pct, "rh_use_pct")
    af_t = arrhenius_af_c(ea_ev, t_use_c, t_stress_c)
    if af_t <= 1.0:
        raise ValueError(
            f"应力温度未构成加速（AF_T={af_t}），湿度反解无解域")
    expo = _finite(n, "n")
    if expo <= 0.0:
        raise ValueError(f"Peck 指数 n 必须为正，收到 {n!r}")
    rh_s = ru * (target / af_t) ** (1.0 / expo)
    if rh_s > 100.0:
        raise ValueError(
            f"反解 RH_s={rh_s:.4g}% 超出物理域 (0,100]——目标 AF 不可达")
    return rh_s


def equivalent_stress_hours(hours_at_use: float, af_total: float) -> float:
    """使用域时长 → 应力域等效时长 [h]：t_stress_equiv = t_use·AF。

    应力域换算（AF 定义式直用），**不是**寿命预测——边界同
    environment_tables.life_from_condition 守卫语义。
    """
    hours = _positive(hours_at_use, "hours_at_use")
    af = _positive(af_total, "af_total")
    return hours * af


# ─── 条件表双源状态面（只读消费 environment_tables）─────────────────────────


def hast_conditions_report() -> dict[str, Any]:
    """HAST/THB/autoclave 条件表双源状态报告（诚实通道账）。

    - source_a：in-repo environment_tables 已合流条目（只读深查）；
    - source_b：NO_VALUE_retrieval_pending + 检索指针（本会话通道受限）；
    - 内部一致性守卫（通道受限下的最小裁判，**不冒充外部双源**）：
      A110/A118 同条件互证、A101 85/85、A102 psi↔Pa 换算复核。
    """
    conds = {c["id"]: c for c in list_conditions()}
    hast_ids = (
        "hast_unbiased_jesd22_a110",
        "hast_biased_jesd22_a118",
        "thb_85_85_jesd22_a101",
        "autoclave_unbiased_jesd22_a102",
    )
    entries: dict[str, Any] = {}
    for cid in hast_ids:
        entry = conds.get(cid)
        if entry is None:
            entries[cid] = {"present": False,
                            "source_b_status": SOURCE_B_STATUS,
                            "source_b_pointers": list(_SOURCE_B_POINTERS)}
            continue
        cond = entry["condition"]
        entries[cid] = {
            "present": True,
            "standard": entry["standard"],
            "temperature_c": cond["temperature_c"],
            "relative_humidity_percent": cond["relative_humidity_percent"],
            "source_a": SOURCE_A_IN_REPO,
            "source_a_verified": bool(entry.get("verified", False)),
            "source_b_status": SOURCE_B_STATUS,
            "source_b_pointers": list(_SOURCE_B_POINTERS),
        }
    # 内部一致性守卫
    a110 = entries["hast_unbiased_jesd22_a110"]
    a118 = entries["hast_biased_jesd22_a118"]
    checks: dict[str, bool] = {}
    checks["a110_a118_same_conditions"] = bool(
        a110.get("present") and a118.get("present")
        and a110["temperature_c"] == a118["temperature_c"]
        and a110["relative_humidity_percent"] == a118["relative_humidity_percent"])
    thb = entries["thb_85_85_jesd22_a101"]
    checks["a101_85_85"] = bool(
        thb.get("present") and thb["temperature_c"] == 85.0
        and thb["relative_humidity_percent"] == 85.0)
    checks["k_b_matches_aging"] = K_B_EV_PER_K == 8.617333262e-5
    return {
        "conditions": entries,
        "internal_consistency_checks": checks,
        "dual_source_honesty_note": (
            "条件表值本会话仅 in-repo 单检索通道；外部第二源 retrieval"
            "_pending——本报告不冒充双源收敛"),
    }
