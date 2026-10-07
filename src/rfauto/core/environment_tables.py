r"""MP-5 环境试验条件表确定性内核（round15 §三 :88「HAST/ROSE/环境试验
条件表：JESD22-A110/IPC-TM-650 2.3.25/IEC 60068-2-27——纯表+入口不产寿命
结论」）。

性质与边界（规格钉死）
--------------------
* **纯表+查询面**：只录公开标准的试验条件值（schema 化 entry + 过滤查询 +
  温度循环剖面 schema/生成器）；**不产寿命结论**——任何"从条件换算寿命/
  可靠性预测"的入口在本模块显式拒绝（life_from_condition 守卫，规格
  「入口不产寿命结论」的字面落地；寿命/加速因子归 core/aging 与 MP-4）。
* **表值诚实口径**：每条 entry 带 verified 位与 source 出处串；verified=True
  表示该条件值为公开标准正文/条件表广泛收录值（本批录入时逐条核对公开
  文献转引）；标准公差/时长协议等随采购文件变化的语义只进 notes 不进
  condition 数值面。规格段只给标准号未给表值——本表值来自公开标准知识，
  完整等级清单以标准原文为准（抽检锚见 tests/unit/test_environment_tables.py）。

收录条目（本批六条+剖面 schema）
--------------------------------
1. JESD22-A110 HAST（无偏）：110 °C / 85 %RH / 水汽压 1.2×10⁵ Pa；
2. JESD22-A118 HAST（加偏）：同条件 + 直流偏置；
3. JESD22-A101 稳态温湿偏置寿命（THB）：85 °C / 85 %RH / 加偏（业界常用
   1000 h 时长进 notes 不进条件值）；
4. JESD22-A102 无偏高压锅（autoclave）：121 °C / 100 %RH / 15 psi 表压
   （=103421.36 Pa，1 psi=6894.757293168 Pa 精确换算）；
5. IPC-TM-650 方法 2.3.25 ROSE（溶剂萃取电阻率法）：75/25 IPA/DI 萃取液，
   离子污染判据 ≤1.56 µg/cm² NaCl 当量（=10.0645 µg/in²，1 in²=6.4516 cm²
   精确换算；该限值同 IPC-J-STD-001/IPC-6012 组件清洁度验收通引值）；
6. IEC 60068-2-27 试验 Ea 半正弦冲击优先严酷等级（抽检四档）：
   150 m/s²/11 ms、300 m/s²/18 ms、500 m/s²/11 ms、1000 m/s²/6 ms
   （SI 主口径；口语 g 名义值 ~15/30/50/100 g，g=9.80665 m/s² 仅换算参照，
   150 m/s²=15.30 g 而非严格 15 g——如实声明）；
7. 温度循环剖面 schema（IEC 60068-2-14 Test Na/Nb 语境）：只定义 schema 与
   生成/校验/周期时长闭式，**不录等级值**（规格未钉 -2-14 等级表；示例
   剖面标 example=True 且注明非标准规定值）。

设计约束：core 叶子层零依赖（仅 import math）、零 IO、JSON 可序列化；
查询返回深拷贝防调用方污染表；非法输入显式 ValueError。
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "PA_PER_PSI",
    "TEMPERATURE_CYCLE_FIELDS",
    "get_condition",
    "life_from_condition",
    "list_conditions",
    "list_families",
    "list_standards",
    "make_temperature_cycle_profile",
    "sample_temperature_cycle_profiles",
    "validate_temperature_cycle_profile",
]

# 1 psi = 6894.757293168 Pa（SI 精确换算：1 lbf=4.4482216152605 N，
# 1 in=0.0254 m → 4.4482216152605/0.00064516 Pa）
PA_PER_PSI = 6894.757293168
# 1 标准重力（IEC 冲击等级 g 口径换算参照）
GN_M_PER_S2 = 9.80665

_ENVIRONMENT_CONDITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "hast_unbiased_jesd22_a110",
        "family": "hast",
        "standard": "JESD22-A110",
        "title": "HAST 高加速温湿度应力试验（无偏）",
        "condition": {
            "temperature_c": 110.0,
            "relative_humidity_percent": 85.0,
            "water_vapor_pressure_pa": 120000.0,
            "bias": "unbiased",
        },
        "notes": "公差与试验时长按采购文件（业界常用 96 h 抽检时长）；"
                 "条件值为标准正文条件定义",
        "source": "JEDEC JESD22-A110（Highly-Accelerated Temperature and "
                  "Humidity Stress Test）条件定义",
        "verified": True,
    },
    {
        "id": "hast_biased_jesd22_a118",
        "family": "hast",
        "standard": "JESD22-A118",
        "title": "HAST 高加速温湿度应力试验（加偏）",
        "condition": {
            "temperature_c": 110.0,
            "relative_humidity_percent": 85.0,
            "water_vapor_pressure_pa": 120000.0,
            "bias": "dc_biased",
        },
        "notes": "偏置电压按器件规格由采购文件定；条件值同 A110 条件面",
        "source": "JEDEC JESD22-A118（HAST with bias）条件定义",
        "verified": True,
    },
    {
        "id": "thb_85_85_jesd22_a101",
        "family": "thb",
        "standard": "JESD22-A101",
        "title": "稳态温湿度偏置寿命试验（85/85 THB）",
        "condition": {
            "temperature_c": 85.0,
            "relative_humidity_percent": 85.0,
            "bias": "dc_biased",
        },
        "notes": "业界常用 1000 h 试验时长（按采购协议可缩放）；本表不录"
                 "时长为标准规定值",
        "source": "JEDEC JESD22-A101（Steady State Temperature Humidity "
                  "Bias Life Test）条件定义",
        "verified": True,
    },
    {
        "id": "autoclave_unbiased_jesd22_a102",
        "family": "autoclave",
        "standard": "JESD22-A102",
        "title": "无偏高压锅蒸压试验（autoclave）",
        "condition": {
            "temperature_c": 121.0,
            "relative_humidity_percent": 100.0,
            "chamber_pressure_gauge_psi": 15.0,
            "chamber_pressure_gauge_pa": round(15.0 * PA_PER_PSI, 2),
            "bias": "unbiased",
        },
        "notes": "最短试验时长 2 h 量级、具体按采购协议；表压 15 psi 为"
                 "标准条件口径（≈2 atm 绝对）",
        "source": "JEDEC JESD22-A102（Accelerated Moisture Resistance – "
                  "Unbiased Autoclave）条件定义",
        "verified": True,
    },
    {
        "id": "rose_ipc_tm_650_2_3_25",
        "family": "ionic_contamination",
        "standard": "IPC-TM-650 2.3.25",
        "title": "ROSE 溶剂萃取电阻率法（离子污染检测）",
        "condition": {
            "solvent_ipa_volume_percent": 75.0,
            "solvent_di_water_volume_percent": 25.0,
            "nacl_equivalent_limit_ug_per_cm2": 1.56,
        },
        "notes": "1.56 µg/cm² NaCl 当量 = 10.0645 µg/in²（精确换算），"
                 "同 IPC-J-STD-001/IPC-6012 组件清洁度验收通引限值；"
                 "萃取温度/终点判据按方法原文",
        "source": "IPC-TM-650 方法 2.3.25（Detection and Measurement of "
                  "Ionizable Surface Contaminants by Solvent Extraction）",
        "verified": True,
    },
    {
        "id": "shock_half_sine_iec_60068_2_27",
        "family": "shock",
        "standard": "IEC 60068-2-27",
        "title": "试验 Ea 冲击（半正弦）优先严酷等级（抽检四档）",
        "condition": {
            "waveform": "half_sine",
            "severities": [
                {"peak_accel_m_per_s2": 150.0, "duration_ms": 11.0},
                {"peak_accel_m_per_s2": 300.0, "duration_ms": 18.0},
                {"peak_accel_m_per_s2": 500.0, "duration_ms": 11.0},
                {"peak_accel_m_per_s2": 1000.0, "duration_ms": 6.0},
            ],
        },
        "notes": "SI 主口径 m/s²；口语 g 名义值 ~15/30/50/100 g 仅换算"
                 "参照（150 m/s²=15.30 g，g=9.80665 m/s²，非严格整数 g）；"
                 "完整等级清单（含后峰锯齿/梯形波与其余档位）以标准原文为准",
        "source": "IEC 60068-2-27（Environmental testing – Test Ea and "
                  "guidance: Shock）优先严酷等级表",
        "verified": True,
    },
)

# 温度循环剖面 schema（IEC 60068-2-14 Test Na（规定转移时间）/Nb（规定
# 变温速率）语境）：字段名 → 单位与语义说明。只定义 schema 不录等级值。
TEMPERATURE_CYCLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("t_low_c", "°C 循环低温端（< t_high_c）"),
    ("t_high_c", "°C 循环高温端（> t_low_c）"),
    ("rate_k_per_min", "K/min 平均变温速率（Test Nb 语义；Na 两箱法为 None）"),
    ("dwell_low_min", "min 低温端保持时长（≥0）"),
    ("dwell_high_min", "min 高温端保持时长（≥0）"),
    ("transfer_min", "min 箱间转移时间（Test Na 语义；Nb 为 None）"),
    ("n_cycles", "循环数（整数 ≥1）"),
)


def _copy(entry: dict[str, Any]) -> dict[str, Any]:
    """entry 深拷贝（两层足够：condition/severities 为最深层容器）。"""
    out = dict(entry)
    cond = out.get("condition")
    if isinstance(cond, dict):
        cond_copy = dict(cond)
        for key, val in cond_copy.items():
            if isinstance(val, list):
                cond_copy[key] = [dict(v) if isinstance(v, dict) else v
                                  for v in val]
        out["condition"] = cond_copy
    return out


def list_conditions(family: str | None = None,
                    standard: str | None = None) -> list[dict[str, Any]]:
    """条件表查询（family/standard 可任选过滤，None=不过滤；返回拷贝）。"""
    out = []
    for entry in _ENVIRONMENT_CONDITIONS:
        if family is not None and entry["family"] != family:
            continue
        if standard is not None and entry["standard"] != standard:
            continue
        out.append(_copy(entry))
    return out


def list_families() -> list[str]:
    """收录 family 名单（按表序去重）。"""
    seen: list[str] = []
    for entry in _ENVIRONMENT_CONDITIONS:
        if entry["family"] not in seen:
            seen.append(entry["family"])
    return seen


def list_standards() -> list[str]:
    """收录标准号名单（按表序去重）。"""
    seen: list[str] = []
    for entry in _ENVIRONMENT_CONDITIONS:
        if entry["standard"] not in seen:
            seen.append(entry["standard"])
    return seen


def get_condition(condition_id: str) -> dict[str, Any]:
    """按 id 取单条（未知名显式 KeyError 并列可用 id，与注册表同语义）。"""
    for entry in _ENVIRONMENT_CONDITIONS:
        if entry["id"] == condition_id:
            return _copy(entry)
    available = [e["id"] for e in _ENVIRONMENT_CONDITIONS]
    raise KeyError(f"未收录的环境条件 id: {condition_id}（可用: {available}）")


# ---------------------------------------------------------------------------
# 温度循环剖面 schema（生成/校验/周期时长闭式）
# ---------------------------------------------------------------------------

def _finite(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为有限数值") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数值")
    return out


def validate_temperature_cycle_profile(profile: dict[str, Any]) -> None:
    """校验温度循环剖面（schema 字段域；非法显式 ValueError）。"""
    t_low = _finite(profile.get("t_low_c"), "t_low_c")
    t_high = _finite(profile.get("t_high_c"), "t_high_c")
    if t_high <= t_low:
        raise ValueError(
            f"t_high_c 必须严格大于 t_low_c（得 {t_high} vs {t_low}）")
    rate = profile.get("rate_k_per_min")
    if rate is not None and _finite(rate, "rate_k_per_min") <= 0.0:
        raise ValueError("rate_k_per_min 必须 >0（或 None=Test Na 两箱法）")
    transfer = profile.get("transfer_min")
    if transfer is not None and _finite(transfer, "transfer_min") < 0.0:
        raise ValueError("transfer_min 必须 >=0（或 None=Test Nb 斜率法）")
    for key in ("dwell_low_min", "dwell_high_min"):
        if _finite(profile.get(key, 0.0), key) < 0.0:
            raise ValueError(f"{key} 必须 >=0")
    n_cycles = profile.get("n_cycles", 1)
    if not isinstance(n_cycles, int) or isinstance(n_cycles, bool) \
            or n_cycles < 1:
        raise ValueError("n_cycles 必须为整数且 ≥1")


def make_temperature_cycle_profile(
    t_low_c: float,
    t_high_c: float,
    *,
    rate_k_per_min: float | None = None,
    dwell_low_min: float = 0.0,
    dwell_high_min: float = 0.0,
    transfer_min: float | None = None,
    n_cycles: int = 1,
) -> dict[str, Any]:
    """生成温度循环剖面（schema 校验 + 单循环时长闭式）。

    周期时长闭式：Test Nb（给 rate）→ t_cycle = 2·(t_high−t_low)/rate
    + dwell_low + dwell_high；Test Na（给 transfer）→ t_cycle = dwell_low
    + dwell_high + 2·transfer；两法都不给 → cycle_time_min=None（纯包络
    剖面）。n_cycles>0 时 total_time_min = n_cycles·t_cycle。
    """
    profile: dict[str, Any] = {
        "t_low_c": t_low_c,
        "t_high_c": t_high_c,
        "rate_k_per_min": rate_k_per_min,
        "dwell_low_min": dwell_low_min,
        "dwell_high_min": dwell_high_min,
        "transfer_min": transfer_min,
        "n_cycles": n_cycles,
    }
    validate_temperature_cycle_profile(profile)
    t_low = float(t_low_c)
    t_high = float(t_high_c)
    if rate_k_per_min is not None:
        ramp_min = (t_high - t_low) / float(rate_k_per_min)
        cycle_time = 2.0 * ramp_min + float(dwell_low_min) \
            + float(dwell_high_min)
        profile["ramp_min_per_leg"] = round(ramp_min, 12)
    elif transfer_min is not None:
        cycle_time = float(dwell_low_min) + float(dwell_high_min) \
            + 2.0 * float(transfer_min)
        profile["ramp_min_per_leg"] = None
    else:
        cycle_time = None
        profile["ramp_min_per_leg"] = None
    profile["cycle_time_min"] = None if cycle_time is None \
        else round(cycle_time, 12)
    profile["total_time_min"] = None if cycle_time is None \
        else round(cycle_time * int(n_cycles), 12)
    return profile


def sample_temperature_cycle_profiles() -> dict[str, dict[str, Any]]:
    """示例剖面（**example=True 非标准规定值**，只演示 schema 用法）。

    规格未钉 IEC 60068-2-14 等级表，本函数不录标准值——调用方按产品
    规格书/采购协议填值，schema 校验与周期时长闭式由本模块保证。
    """
    nb = make_temperature_cycle_profile(
        -40.0, 85.0, rate_k_per_min=10.0,
        dwell_low_min=10.0, dwell_high_min=10.0, n_cycles=100)
    na = make_temperature_cycle_profile(
        -40.0, 85.0, dwell_low_min=30.0, dwell_high_min=30.0,
        transfer_min=3.0, n_cycles=25)
    nb["example"] = True
    na["example"] = True
    nb["note"] = "示例剖面（Test Nb 斜率法语义），非标准规定值"
    na["note"] = "示例剖面（Test Na 转移时间语义），非标准规定值"
    return {"nb_ramp_example": nb, "na_transfer_example": na}


# ---------------------------------------------------------------------------
# 寿命结论守卫（规格「纯表+入口不产寿命结论」的字面落地）
# ---------------------------------------------------------------------------

def life_from_condition(*args: Any, **kwargs: Any) -> None:
    """显式拒绝：环境条件表不产寿命结论（round15 :88 规格）。

    寿命/加速因子语义归 core/aging（Arrhenius/Coffin-Manson/Black）与
    MP-4 core/electromigration；本表只供条件值，换算寿命必须显式走
    上述内核并由调用方承担模型选择，本模块不提供隐式换算入口。
    """
    raise NotImplementedError(
        "环境条件表不产寿命结论（round15 :88「纯表+入口不产寿命结论」）："
        "寿命换算请显式消费 core/aging 或 core/electromigration 内核")
