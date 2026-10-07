"""PK-5 压电/声学材料常数表（ge8d 席 D1；round14 §五 PK-5 扩展口径）。

规格：研究扩充 round14 :142（AlN/ScAlN/LN/LT+TCD
入 materials schema，带来源+UNVERIFIED 状态位）+ 任务书 wave_d/seat_d_all.md
席 D1（LiNbO3/Quartz/PZT 等压电常数**双源**表；**检索不可达=零值诚实登记**，
PK-9 print_materials_ext.py 先例）。

**零值诚实登记（#df6-⑨ 引用腐坏纪律；本会话 2026-10-03 实测检索账）**
--------------------------------------------------------------------
本批可逐位核对的可达检索通道：Wikipedia 原文/原始 wikitext（en.wikipedia.org，
web_reader 通道；直连 curl/WebFetch 对 wikipedia/wikiwand 域 DNS 污染不可达）。
逐条核对结果（bit-for-bit）：

- **AlN（已核，含压电/弹性表）**：ρ=3.255 g/cm³（Haynes/CRC 97e p.4.45，infobox
  逐位）；wurtzite P6₃mc（No.186）hP4、a=0.31117 nm、c=0.49788 nm（Vurgaftman
  JAP 94, 3675 (2003)，infobox 逐位）；**e31=−0.60、e33=1.46 C/m²、c13=108、
  c33=373 GPa**（Wikipedia 正文表逐位，双引 Ambacher J. Phys. D 31, 2653
  (1998) + JAP 87, 334 (2000)，两文 doi-access=free）；带隙 6.015 eV；本征
  热导 321 W/(m·K)（Cheng PRMaterials 4, 044602 (2020)）。
- **α-Quartz（已核）**：比重 2.65（不纯变体 2.59–2.63；infobox ``gravity``
  字段逐位，引 Deer/Howie/Zussman）；P3₂21（No.154）、a=4.9133 Å、c=5.4053 Å、
  Z=3（infobox 逐位）；α↔β 转变 573 °C（正文逐位）；压电性 Curie 兄弟 1880
  （正文+两处原始引文逐位）。
- **LiNbO3（已核+冲突登记）**：ρ=4.30 g/cm³（Haynes/CRC，infobox 逐位）；
  三方 R3c（No.161）、点群 3m、菱方元胞 a=5.1501 Å、c=5.4952 Å、α=β=62.057°、
  γ=60°（infobox 逐位）。**密度冲突**：菱方元胞晶体学推导（Z_rh=2，R 心=六
  方 Z/3）给 4.62 g/cm³，与 infobox 4.30 差 ~7%——两源**不收敛**，按
  CONFLICT_registered 如实登记（不裁决、不采信记忆值 ~4.64；该值只进
  retrieval_pointers）。另：infobox 的 d33=27 pm/V 是**非线性光学**系数
  （PPLN 语境），非压电 d33——本表**不登记**为压电量（防张冠李戴）。
- **ScAlN(x=0–0.43)/LiTaO3/PZT-5A/PZT-5H（检索不可达=零值）**：本会话检索
  通道内无可逐位核对的常数表（厂商页 404/无表、付费墙、检索摘要属转述）——
  全部常数按 NO_VALUE_retrieval_pending 登记（值=None+检索指针），**不凭
  记忆复写文献数值**（PK-9 先例逐字执行）。
- **独立第二源=晶体学推导**（#118 独立路径）：wurtzite/六方 V=(√3/2)a²c、
  一般三方 V=a²c√(1−3cos²α+2cos³α)（γ=60°），ρ=Z·M/(N_A·V)。AlN 推导
  3.262 vs CRC 3.255（0.2% ✓ 双源收敛）、Quartz 推导 2.646 vs 比重 2.65
  （0.2% ✓）、LN 推导 4.624 vs CRC 4.30（7% ✗ 冲突登记）。推导式本身以
  合成已知量回收钉（#118）。

状态档（文案即语义，print_materials_ext/material_library 先例）
----------------------------------------------------------------
``dual_source_agree``（两独立通道 ≤0.5% 收敛）/ ``single_source_quoted``
（单一可达通道逐位读出）/ ``derived_from_verified``（由已核输入闭式推导，
公式与输入各自留痕）/ ``CONFLICT_registered``（多源不收敛，带登记不裁决）/
``NO_VALUE_retrieval_pending``（值 None + 检索指针）。

闭式函数面（确定性内核，铁律 7：数字只由闭式/加载器产出）
----------------------------------------------------------------
- kt² 声学定义（IEEE Std 176 家族口径，与 core/acoustic_resonator.py 的
  keff²≈(fa²−fs²)/fa² 同族）：kt² = 1 − (v_s/v_a)²（v_s unstiffened、
  v_a stiffened 声速）；正/反变换 v_a=v_s/√(1−kt²)、v_s=v_a√(1−kt²)。
- 常数链：c33^D = c33^E + e33²/ε33^S；kt² = e33²/(c33^D·ε33^S)
  = e33²/(ε33·c33^E + e33²)（代数恒等式单测互证）。
- 声速：v=√(c/ρ)（一维纵波牛顿式，教科书恒等式级）。
- 密度推导：Z·M/(N_A·V)。

接口：纯函数零 IO（加载器仅 pathlib 本地读）；全部返回 JSON 可序列化
float/dict/str/bool/None；数值 0.0 合法（判缺失一律 is not None，#364④）；
bool 显式拒收。**不进 @register_calculator 注册表、不定义 __all__**
（acoustic_resonator/package_interconnect 先例：免 #231/#304 注册表消费
者连动与公开 API 快照重钉）。
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

# 物理常数
#: 阿伏伽德罗常数（1/mol，CODATA 2018 精确定义）
N_A = 6.02214076e23
#: 真空介电常数（F/m，μ0 精确定义 + c 精确定义导出）
EPS0_F_PER_M = 8.8541878128e-12

# 状态档（文案即语义）
STATUS_DUAL_SOURCE_AGREE = "dual_source_agree"
STATUS_SINGLE_SOURCE_QUOTED = "single_source_quoted"
STATUS_DERIVED_FROM_VERIFIED = "derived_from_verified"
STATUS_CONFLICT_REGISTERED = "CONFLICT_registered"
STATUS_NO_VALUE_RETRIEVAL_PENDING = "NO_VALUE_retrieval_pending"

_VALUE_STATUSES = (
    STATUS_DUAL_SOURCE_AGREE,
    STATUS_SINGLE_SOURCE_QUOTED,
    STATUS_DERIVED_FROM_VERIFIED,
)
_ALLOWED_STATUSES = (
    *_VALUE_STATUSES,
    STATUS_CONFLICT_REGISTERED,
    STATUS_NO_VALUE_RETRIEVAL_PENDING,
)

_DATA_PATH = Path(__file__).resolve().parent / "piezo_data" / "piezo_materials.json"


# ─── 闭式函数（确定性内核）───────────────────────────────────────────────────


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


def kt2_from_velocities(v_stiffened_m_s: float, v_unstiffened_m_s: float) -> float:
    """kt² = 1 − (v_s/v_a)²（IEEE Std 176 家族声学定义；v_a ≥ v_s>0）。

    合成回收锚：v_s/v_a=0.99 → kt²=0.0199；v_s=v_a → 0.0（#118 合成回收）。
    """
    va = _positive(v_stiffened_m_s, "v_stiffened_m_s")
    vs = _positive(v_unstiffened_m_s, "v_unstiffened_m_s")
    if vs > va:
        raise ValueError(f"v_unstiffened ({vs}) 不得大于 v_stiffened ({va})")
    return 1.0 - (vs / va) ** 2


def velocity_stiffened(v_unstiffened_m_s: float, kt2: float) -> float:
    """v_a = v_s/√(1−kt²)（压电刚化闭式；0≤kt²<1）。"""
    vs = _positive(v_unstiffened_m_s, "v_unstiffened_m_s")
    k = _finite(kt2, "kt2")
    if not 0.0 <= k < 1.0:
        raise ValueError(f"kt2 必须在 [0,1) 内，收到 {kt2!r}")
    return vs / math.sqrt(1.0 - k)


def velocity_unstiffened(v_stiffened_m_s: float, kt2: float) -> float:
    """v_s = v_a·√(1−kt²)（上式反变换；构造恒等式单测互证）。"""
    va = _positive(v_stiffened_m_s, "v_stiffened_m_s")
    k = _finite(kt2, "kt2")
    if not 0.0 <= k < 1.0:
        raise ValueError(f"kt2 必须在 [0,1) 内，收到 {kt2!r}")
    return va * math.sqrt(1.0 - k)


def stiffened_elastic_constant(c33_e_gpa: float, e33_c_m2: float,
                               eps33_f_per_m: float) -> float:
    """c33^D = c33^E + e33²/ε33^S [GPa]（压电刚化关系，IEEE Std 176 口径）。"""
    ce = _positive(c33_e_gpa, "c33_e_gpa")
    e = _finite(e33_c_m2, "e33_c_m2")
    eps = _positive(eps33_f_per_m, "eps33_f_per_m")
    # GPa = 1e9 Pa；e²/ε 量纲 (C/m²)²/(F/m) = C²/(F·m²) = (C/V)²·(V·A·s
    # 折算)=N/m²=Pa（量纲自洽：e²/ε 单位 Pa，×1e-9 转 GPa）
    return ce + (e * e / eps) * 1e-9


def kt2_from_constants(e33_c_m2: float, c33_e_gpa: float,
                       eps33_f_per_m: float) -> float:
    """kt² = e33²/(ε33·c33^E + e33²)（由 c^D=c^E+e²/ε 代入 kt²=e²/(c^D·ε)
    的代数恒等；与 stiffened_elastic_constant+kt2_from_elastic_stiffening
    两步链逐位一致——单测互证）。"""
    e = _finite(e33_c_m2, "e33_c_m2")
    ce = _positive(c33_e_gpa, "c33_e_gpa")
    eps = _positive(eps33_f_per_m, "eps33_f_per_m")
    e2_pa = e * e / eps  # Pa
    return e2_pa / (ce * 1e9 + e2_pa)


def kt2_from_elastic_stiffening(c33_d_gpa: float, c33_e_gpa: float) -> float:
    """kt² = 1 − c33^E/c33^D（构造性定义；c33^D>c33^E>0）。"""
    cd = _positive(c33_d_gpa, "c33_d_gpa")
    ce = _positive(c33_e_gpa, "c33_e_gpa")
    if ce >= cd:
        raise ValueError(f"c33_e ({ce}) 必须 < c33_d ({cd})")
    return 1.0 - ce / cd


def longitudinal_velocity_m_s(density_kg_m3: float, elastic_pa: float) -> float:
    """一维纵波 v=√(c/ρ) [m/s]（牛顿声速式；c 单位 Pa、ρ 单位 kg/m³）。"""
    rho = _positive(density_kg_m3, "density_kg_m3")
    c = _positive(elastic_pa, "elastic_pa")
    return math.sqrt(c / rho)


def hex_cell_volume_m3(a_m: float, c_m: float) -> float:
    """六方/纤锌矿元胞体积 V=(√3/2)·a²·c [m³]（精确几何式）。"""
    a = _positive(a_m, "a_m")
    c = _positive(c_m, "c_m")
    return 0.5 * math.sqrt(3.0) * a * a * c


def trigonal_cell_volume_m3(a_m: float, c_m: float, alpha_deg: float,
                            gamma_deg: float) -> float:
    """三方（菱方设定 a=b，α=β）元胞体积 [m³]。

    由一般三斜体积式 V=a·b·c·√(1−cos²α−cos²β−cos²γ+2cosα·cosβ·cosγ)
    代入 a=b（本表 LN 菱方设定 α=β=62.057°、γ=60°）对称化而来。正确性
    由 tests 的六方退化锚独立验证：α=90°、γ=120° 时退化为
    hex_cell_volume=(√3/2)a²c 逐位。
    """
    a = _positive(a_m, "a_m")
    c = _positive(c_m, "c_m")
    ca = math.cos(math.radians(_finite(alpha_deg, "alpha_deg")))
    cg = math.cos(math.radians(_finite(gamma_deg, "gamma_deg")))
    inner = 1.0 - 2.0 * ca * ca - cg * cg + 2.0 * ca * ca * cg
    if inner <= 0.0:
        raise ValueError("元胞角度组合非法（体积根号为负）")
    return a * a * c * math.sqrt(inner)


def density_from_unit_cell_kg_m3(z_formula_units: float,
                                 molar_mass_g_mol: float,
                                 cell_volume_m3: float) -> float:
    """ρ = Z·M/(N_A·V) [kg/m³]（晶体学精确式；合成回收锚见 tests）。"""
    z = _positive(z_formula_units, "z_formula_units")
    m = _positive(molar_mass_g_mol, "molar_mass_g_mol")
    v = _positive(cell_volume_m3, "cell_volume_m3")
    return (z * m / N_A / v) * 1e-3  # g/m³ → kg/m³


# ─── 数据加载器（本地 JSON，唯一 IO 面）──────────────────────────────────────


def load_piezo_table(path: str | Path | None = None) -> dict[str, Any]:
    """读压电材料表 JSON → dict（深拷贝语义：每次调用返回独立副本）。

    结构校验：每条 property 必须 {value, status, sources, ...}；状态必须在
    状态档全集内；NO_VALUE 档 value 必须为 None 且必须带 retrieval_pointers。
    """
    p = Path(path) if path is not None else _DATA_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))
    materials = raw.get("materials")
    if not isinstance(materials, dict) or not materials:
        raise ValueError(f"{p}: materials 表缺失或为空")
    for mid, entry in materials.items():
        props = entry.get("properties", {})
        for prop, item in props.items():
            if not isinstance(item, dict):
                raise ValueError(f"{p}: {mid}.{prop} 非对象")
            status = item.get("status")
            if status not in _ALLOWED_STATUSES:
                raise ValueError(f"{p}: {mid}.{prop} 状态档非法: {status!r}")
            if status == STATUS_NO_VALUE_RETRIEVAL_PENDING:
                if item.get("value") is not None:
                    raise ValueError(f"{p}: {mid}.{prop} NO_VALUE 档不得带值")
                if not item.get("retrieval_pointers"):
                    raise ValueError(f"{p}: {mid}.{prop} NO_VALUE 档缺检索指针")
            elif status in _VALUE_STATUSES or status == STATUS_CONFLICT_REGISTERED:
                if item.get("value") is None:
                    raise ValueError(f"{p}: {mid}.{prop} 值档缺 value")
                if not item.get("sources"):
                    raise ValueError(f"{p}: {mid}.{prop} 值档缺 sources")
    return raw


def get_material(material_id: str, path: str | Path | None = None) -> dict[str, Any]:
    """取单材料条目（深拷贝；不存在即 KeyError）。"""
    table = load_piezo_table(path)
    if material_id not in table["materials"]:
        raise KeyError(f"材料不存在: {material_id!r}")
    return copy.deepcopy(table["materials"][material_id])


def property_value(material_id: str, prop: str,
                   path: str | Path | None = None) -> float | None:
    """取属性数值：有值档返回 float；NO_VALUE 返回 None（判缺失 is not None）。"""
    entry = get_material(material_id, path)
    item = entry.get("properties", {}).get(prop)
    if item is None:
        return None
    value = item.get("value")
    if value is None:
        return None
    if isinstance(value, list):  # 带/冲突登记取中点，状态本身已声明语义
        return 0.5 * (float(value[0]) + float(value[1]))
    return float(value)


def dual_source_report(path: str | Path | None = None) -> dict[str, int]:
    """状态档计数面（诚实交付度盘点：不得冒充双源覆盖度）。"""
    table = load_piezo_table(path)
    counts = {s: 0 for s in _ALLOWED_STATUSES}
    counts["NO_VALUE_retrieval_pending"] = 0
    counts["properties_total"] = 0
    for entry in table["materials"].values():
        for item in entry.get("properties", {}).values():
            counts["properties_total"] += 1
            status = item["status"]
            counts[status] = counts.get(status, 0) + 1
    return counts
