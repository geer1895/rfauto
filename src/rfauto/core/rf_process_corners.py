"""F-J.4 RF 工艺角五角 worst-case 集（确定性极值版 = MC 注入链的确定性投影）。

定位（研究扩充 round5 §三件 4）：给 PCB 制造工艺
波动一个**确定性**的 2^5=32 角全枚举极值集——每参数取 (nominal, lo, hi)
三元组的两端，角向量全枚举即蒙特卡洛注入链的确定性投影（MC 采样支撑集的
端点；角间 spread 是工艺波动对响应影响的上界估计）。与 core/pce.py 的
corner_worst_case（通用容差角点穷举，按 param_specs 两端取点）关系：彼处
面向任意 PCE 参数，本模块钉死 PCB fab 五工艺角 + 物理方向语义表 +
电镀集边（thieving）修正带 + 输出直接对齐 tolerance/uq 面入参形态——
optimization/tolerance.py::ToleranceAnalyzer.analyze 的 ``nominal_params``
与 ``tolerances``（{param: ±半宽}）dict、service/uq_service 的 {param: σ}
（σ=半宽/k 由调用方折算）。

五角（业界无统一命名标准，本模块自钉命名——F-J 规格口径）：
- ``etch_bias_um``：蚀刻偏差（线宽减窄量幅值，µm，≥0；hi=线更窄）；
- ``t_cu_um``：成品铜厚（µm；带经电镀集边 thieving 口径派生，见
  THIEVING_TABLE / t_cu_thieving_band_um / t_cu_param）；
- ``epsilon_r``：介电常数（materials.yaml ``epsilon_r`` 同名键；容差带
  缺省 ±0.05 绝对——materials.yaml ``epsilon_r_tol_abs`` 同名惯例，
  Rogers RO4000 process Dk 口径，configs/materials.yaml verified-web 登记）；
- ``tan_delta``：损耗角正切（materials.yaml tan_d 同族；带缺省 ±20% 相对）；
- ``alignment_um``：层间对准偏差幅值（µm，≥0；hi=对准最差）。

物理方向语义表（RESPONSE_CLASS_TABLE，标注面非判据——判据是 slope 符号，
见 predict_extreme_corner）：frequency 类（谐振频率）εr_lo→f_hi
（f∝1/√εr，语义即规格例 εr_hi→f_lo）、etch_bias_hi（线窄）→f_hi
（εeff 略降，弱方向）、t_cu_lo（铜薄）→f_hi（弱惯例方向）、tanδ/对准
一阶不移频（None）；loss 类（插损）tanδ_hi→损耗上、t_cu_lo（薄铜/集边）
→损耗上、etch_bias_hi（线窄电流密度高）→损耗上、alignment_hi（耦合对准
退化→带内插损加深，弱惯例方向）、εr 一阶不改损耗主导项（None）。
具名惯例角 ARCHETYPE_CORNERS："高频角"=高速/毫米波最坏评估惯例组合——
规格例口径 εr_hi+tanδ_hi+thin_cu，再补 etch_bias_hi/alignment_hi 两最坏
幅值端；"低频角"为其逐参数反向。

判据锚（#122 先行）：2^n 角全枚举计数守恒（恰好 2^n、corner_id 无重）；
角方向物理自洽（方向表语义标注，本测试文件钉）；spread 极值定位恒等式
（单调响应下 argmax/argmin 角 = slope 符号预测角，逐位；零斜率并列钉
枚举序首个 = 方向 "lo"）。UNVERIFIED 清单见 THIEVING_TABLE 与缺省带注：
蚀刻偏差 0-20µm、层间对准 0-75µm、tanδ ±20% 均为行业惯例带（无可达
单源，不虚构出处）——具体 fab 以 core/fab_check.py FabProfile 剖面为准。

接口：纯函数零 IO；ProcessParam/Corner dataclass+to_dict（JSON 可序列化）；
数值 0.0 合法、判缺失一律 is not None（#364④）；bool 显式拒收
（df7+⑯）。不进 calculators 注册表（core 叶约定，消费者是 service 层）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ARCHETYPE_CORNERS",
    "DEFAULT_ALIGNMENT_BAND_UM",
    "DEFAULT_ER_TOL_ABS",
    "DEFAULT_ETCH_BIAS_BAND_UM",
    "DEFAULT_TAN_DELTA_REL_PCT",
    "FIVE_CORNER_PARAM_NAMES",
    "RESPONSE_CLASS_TABLE",
    "THIEVING_TABLE",
    "Corner",
    "ProcessParam",
    "build_five_corners",
    "corner_injection_set",
    "corner_spread",
    "corner_spread_from_slopes",
    "enumerate_corners",
    "expected_extreme_directions",
    "make_param",
    "predict_extreme_corner",
    "t_cu_param",
    "t_cu_thieving_band_um",
]

# ─── 五角命名与缺省带 ─────────────────────────────────────────────────────────

#: 五工艺角参数名（顺序即角枚举位序：名字表第 j 位 = 角向量第 j 位二进制位）。
FIVE_CORNER_PARAM_NAMES: tuple[str, ...] = (
    "etch_bias_um",
    "t_cu_um",
    "epsilon_r",
    "tan_delta",
    "alignment_um",
)

#: 五角缺省带（行业惯例带；fab 剖面如声明以剖面为准——UNVERIFIED 清单：
#: 蚀刻偏差 0-20µm 与层间对准 0-75µm 为常规刚板量产惯例量级，无可达单源；
#: εr ±0.05 绝对 = materials.yaml ``epsilon_r_tol_abs`` 同名惯例
#: （Rogers RO4000 process Dk ±0.05 口径，configs/materials.yaml
#: 2026-09-25 verified-web 登记）；tanδ ±20% 相对为惯例带 UNVERIFIED；
#: t_cu 带不在此钉——经 THIEVING_TABLE 派生）。
DEFAULT_ETCH_BIAS_BAND_UM = (0.0, 20.0)
DEFAULT_ALIGNMENT_BAND_UM = (0.0, 75.0)
DEFAULT_ER_TOL_ABS = 0.05
DEFAULT_TAN_DELTA_REL_PCT = 20.0

#: 电镀集边（thieving）惯例口径（UNVERIFIED——行业惯例带，无可达单源；
#: IPC-6012 只钉孔铜验收面，不钉面铜集边分布）：孤立线成品铜厚因电镀
#: 电流集边相对电镀目标值上偏 20–40%；密区（thieving/覆铜包裹）视作
#: 目标口径（+0%）。角集 t_cu 上端取 max_plus_pct 最大档（+40%，孤立线
#: 集边最坏）；+20% 为孤立线集边典型带下缘（厚度修正函数展示面）。
THIEVING_TABLE: dict[str, dict[str, float]] = {
    "isolated": {"min_plus_pct": 20.0, "max_plus_pct": 40.0},
    "dense": {"min_plus_pct": 0.0, "max_plus_pct": 0.0},
}

#: 物理方向语义表：响应类 → 每参数取哪一端使该类响应**极大**。
#: "lo"/"hi"=已声明方向（含弱惯例方向，注内标弱）；None=一阶无一致方向
#: （不进单调判据）。仅标注面——spread 极值定位的判据是 slope 符号
#: （predict_extreme_corner），本表由测试文件做物理自洽钉。
RESPONSE_CLASS_TABLE: dict[str, dict[str, str | None]] = {
    "frequency": {
        "etch_bias_um": "hi",  # 线宽变窄 → εeff 略降 → f 上移（弱方向）
        "t_cu_um": "lo",  # 铜薄 → 分布电容略降 → f 上移（弱惯例方向）
        "epsilon_r": "lo",  # εr_hi→f_lo（f∝1/√εr）：取 lo 使 f 极大
        "tan_delta": None,  # 一阶不移频（复 εr 实部主导相速）
        "alignment_um": None,  # 一阶作用于耦合量而非谐振频率
    },
    "loss": {
        "etch_bias_um": "hi",  # 线窄 → 电流密度高 → 导体损耗上
        "t_cu_um": "lo",  # 薄铜（含集边下带）→ 导体损耗上
        "epsilon_r": None,  # 一阶不改损耗主导项
        "tan_delta": "hi",  # 介质损耗上
        "alignment_um": "hi",  # 耦合对准退化 → 带内插损加深（弱惯例方向）
    },
}

#: 具名惯例角（物理方向表常量）："高频角"=高速/毫米波最坏评估惯例组合
#: ——规格例口径 εr_hi+tanδ_hi+thin_cu，补 etch_bias_hi/alignment_hi；
#: "低频角"为其逐参数反向。标注面：角仍须从 enumerate_corners 全集取。
ARCHETYPE_CORNERS: dict[str, dict[str, str]] = {
    "high_freq_worst": {
        "etch_bias_um": "hi",
        "t_cu_um": "lo",
        "epsilon_r": "hi",
        "tan_delta": "hi",
        "alignment_um": "hi",
    },
    "low_freq_worst": {
        "etch_bias_um": "lo",
        "t_cu_um": "hi",
        "epsilon_r": "lo",
        "tan_delta": "lo",
        "alignment_um": "lo",
    },
}


# ─── 数值守卫 ─────────────────────────────────────────────────────────────────


def _finite(value: float, name: str) -> float:
    """入参收敛为有限 float；bool 显式拒收（df7+⑯）；非法即显式报错。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到 {value!r}")
    return out


# ─── 参数三元组与角 ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProcessParam:
    """单工艺参数三元组 (nominal, lo, hi)（角集最小载体，JSON 可序列化）。"""

    name: str
    nominal: float
    lo: float
    hi: float
    unit: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "nominal": self.nominal,
            "lo": self.lo,
            "hi": self.hi,
            "unit": self.unit,
            "source": self.source,
        }


@dataclass(frozen=True)
class Corner:
    """单角：id + 方向表（param→"lo"/"hi"）+ 参数值表（param→float）。"""

    corner_id: str
    directions: dict[str, str]
    params: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "directions": dict(self.directions),
            "params": dict(self.params),
        }


def make_param(
    name: str,
    nominal: float,
    lo: float,
    hi: float,
    unit: str = "",
    source: str = "",
) -> ProcessParam:
    """构造并校验单参数三元组：lo ≤ nominal ≤ hi，非法即 ValueError。"""
    if not isinstance(name, str) or not name:
        raise ValueError("name 必须为非空 str")
    nom = _finite(nominal, f"{name}.nominal")
    lo_ = _finite(lo, f"{name}.lo")
    hi_ = _finite(hi, f"{name}.hi")
    if lo_ > hi_:
        raise ValueError(f"{name}: lo({lo_!r}) > hi({hi_!r}) 非法（band 反向）")
    if not (lo_ <= nom <= hi_):
        raise ValueError(f"{name}: nominal({nom!r}) 必须落在 [lo, hi]=[{lo_!r}, {hi_!r}] 内")
    return ProcessParam(name=name, nominal=nom, lo=lo_, hi=hi_, unit=str(unit), source=str(source))


def t_cu_thieving_band_um(target_um: float, density: str) -> tuple[float, float]:
    """厚度修正函数：电镀目标铜厚 → 该密度类成品铜厚带 (lo, hi)。

    口径见 THIEVING_TABLE（UNVERIFIED 行业惯例带）：isolated 上偏
    +20%..+40%，dense +0%（目标口径）。target_um 必须 >0（电镀目标，
    乘法基）；density 不在表内 → ValueError。
    """
    key = str(density)
    if key not in THIEVING_TABLE:
        raise ValueError(f"density 必须是 {sorted(THIEVING_TABLE)} 之一，实际 {density!r}")
    target = _finite(target_um, "target_um")
    if target <= 0.0:
        raise ValueError(f"target_um 必须 >0，收到 {target!r}")
    band = THIEVING_TABLE[key]
    lo = target * (1.0 + band["min_plus_pct"] / 100.0)
    hi = target * (1.0 + band["max_plus_pct"] / 100.0)
    return (lo, hi)


def t_cu_param(target_um: float, density: str = "isolated", source: str = "") -> ProcessParam:
    """t_cu 工艺角参数：带 = thieving 修正带（入角集），nominal = 带中点。

    集边上偏为单侧带（成品铜厚只比目标厚），电镀目标值本身落在带外
    （isolated 时 target < lo），违反 make_param 的 nominal∈[lo,hi]
    不变式——故 nominal 取带中点，目标值与密度记入 source 字段留痕。
    """
    lo, hi = t_cu_thieving_band_um(target_um, density)
    center = 0.5 * (lo + hi)
    src = source or f"THIEVING_TABLE:{density}:target_um={target_um}"
    return make_param("t_cu_um", center, lo, hi, unit="um", source=src)


def build_five_corners(
    nominals: Mapping[str, float],
    *,
    er_tol_abs: float = DEFAULT_ER_TOL_ABS,
    tan_delta_rel_pct: float = DEFAULT_TAN_DELTA_REL_PCT,
    t_cu_density: str = "isolated",
    bands: Mapping[str, tuple[float, float]] | None = None,
) -> list[ProcessParam]:
    """五角参数集：nominals 给五键名义值，缺省带按常量，bands 逐键覆盖。

    - nominals 键必须**恰好**是 FIVE_CORNER_PARAM_NAMES（缺名/多名即
      ValueError）；
    - ``nominals["t_cu_um"]`` 语义 = 电镀目标铜厚（µm）——thieving 派生带
      的中点作角集 nominal（目标值低于孤立线成品带，直接作 nominal 违反
      nominal∈[lo,hi]）；bands 显式给 t_cu_um 带时该键即角集 nominal 本身
      （须落带内）；
    - er 带 = nominal ± er_tol_abs（绝对）；tan_delta 带 = nominal ×
      (1±pct/100)（相对，nominal 须 >0）；etch_bias/alignment 缺省带为
      [0, 上限]（幅值语义），bands 可覆盖。

    返回参数顺序 = FIVE_CORNER_PARAM_NAMES 顺序（角枚举位序契约）。
    """
    nom = {str(k): v for k, v in dict(nominals).items()}
    missing = [k for k in FIVE_CORNER_PARAM_NAMES if k not in nom]
    extra = [k for k in nom if k not in FIVE_CORNER_PARAM_NAMES]
    if missing or extra:
        raise ValueError(
            f"nominals 键必须恰为 {list(FIVE_CORNER_PARAM_NAMES)}；缺 {missing}，多 {extra}"
        )
    band_map = {str(k): v for k, v in dict(bands or {}).items()}
    for key, band in band_map.items():
        if key not in FIVE_CORNER_PARAM_NAMES:
            raise ValueError(f"bands 键 {key!r} 不在五角命名表内")
        lo, hi = band
        if _finite(lo, f"bands[{key}].lo") > _finite(hi, f"bands[{key}].hi"):
            raise ValueError(f"bands[{key}]: lo > hi 非法")

    out: list[ProcessParam] = []
    for name in FIVE_CORNER_PARAM_NAMES:
        if name == "t_cu_um" and "t_cu_um" not in band_map:
            out.append(t_cu_param(nom[name], density=t_cu_density))
            continue
        band = band_map.get(name)
        if band is None:
            if name == "etch_bias_um":
                band = DEFAULT_ETCH_BIAS_BAND_UM
            elif name == "alignment_um":
                band = DEFAULT_ALIGNMENT_BAND_UM
            elif name == "epsilon_r":
                er_nom = _finite(nom[name], "nominals.epsilon_r")
                band = (er_nom - er_tol_abs, er_nom + er_tol_abs)
            else:  # tan_delta
                td_nom = _finite(nom[name], "nominals.tan_delta")
                if td_nom <= 0.0:
                    raise ValueError(f"nominals.tan_delta 必须 >0（相对带基），收到 {td_nom!r}")
                rel = tan_delta_rel_pct / 100.0
                band = (td_nom * (1.0 - rel), td_nom * (1.0 + rel))
        out.append(
            make_param(
                name,
                nom[name],
                band[0],
                band[1],
                unit="um" if name.endswith("_um") else "-",
                source="bands 显式覆盖" if name in band_map else "缺省带（UNVERIFIED 惯例带）",
            )
        )
    return out


# ─── 角向量表生成（组合枚举） ─────────────────────────────────────────────────


def enumerate_corners(params: Sequence[ProcessParam]) -> list[Corner]:
    """2^n 角全枚举（确定性序：k=0..2^n−1，参数 j 位=lo/hi ↔ k 第 j 位 0/1）。

    空参数集 → ValueError；corner_id = ``c{k:0{n}b}``（无重）。计数守恒
    由测试钉（恰好 2^n 条、每参数恰半数 lo/半数 hi）。
    """
    plist = list(params)
    if not plist:
        raise ValueError("params 不能为空（空参数集无角可言）")
    n = len(plist)
    out: list[Corner] = []
    for k in range(2**n):
        directions: dict[str, str] = {}
        values: dict[str, float] = {}
        for j, p in enumerate(plist):
            bit = (k >> j) & 1
            d = "hi" if bit else "lo"
            directions[p.name] = d
            values[p.name] = p.hi if bit else p.lo
        out.append(Corner(corner_id=f"c{k:0{n}b}", directions=directions, params=values))
    return out


def _corner_id_for_directions(plist: list[ProcessParam], dirs: Mapping[str, str]) -> str:
    """方向表 → 枚举序角 id（键集/值域不匹配即 ValueError）。"""
    k = 0
    for j, p in enumerate(plist):
        d = dirs.get(p.name)
        if d not in ("lo", "hi"):
            raise ValueError(f"方向表缺/非法项 {p.name}（须 lo/hi），实际 {d!r}")
        if d == "hi":
            k |= 1 << j
    n = len(plist)
    return f"c{k:0{n}b}"


def corner_injection_set(params: Sequence[ProcessParam]) -> dict[str, Any]:
    """MC 注入集（tolerance/uq 面入参形态，JSON 可序列化）。

    - ``nominal_params``：{param: nominal}——ToleranceAnalyzer.analyze 的
      nominal_params 直接形态；
    - ``tolerances_half_width``：{param: (hi−lo)/2}——同 analyze 的
      tolerances ±半宽语义；uq_service {param: σ} 需调用方 σ=半宽/k_sigma；
    - ``bounds`` / ``corners``：角点参数 dict 直接可作逐点求值入参
      （每个角 = MC 支撑集一个确定性端点）；
    - ``archetype_corner_ids``：具名惯例角在全集中的角 id（方向表反查）。
    """
    plist = list(params)
    corners = enumerate_corners(plist)  # 空集在此报错
    return {
        "n_params": len(plist),
        "n_corners": len(corners),
        "nominal_params": {p.name: p.nominal for p in plist},
        "bounds": {p.name: {"lo": p.lo, "hi": p.hi} for p in plist},
        "tolerances_half_width": {p.name: 0.5 * (p.hi - p.lo) for p in plist},
        "corners": [c.to_dict() for c in corners],
        "archetype_corner_ids": {
            name: _corner_id_for_directions(plist, dirs) for name, dirs in ARCHETYPE_CORNERS.items()
        },
    }


# ─── 角间 spread 面 ───────────────────────────────────────────────────────────


def _spread_from_values(corners: list[Corner], values: list[float]) -> dict[str, Any]:
    """聚合 spread 表：max−min + 极值角定位（严格 >/＜ 并列取枚举序首个）。"""
    vmax = values[0]
    vmin = values[0]
    imax = 0
    imin = 0
    for i, v in enumerate(values[1:], start=1):
        if v > vmax:
            vmax = v
            imax = i
        if v < vmin:
            vmin = v
            imin = i
    return {
        "n_corners": len(corners),
        "spread": vmax - vmin,
        "argmax_corner_id": corners[imax].corner_id,
        "argmin_corner_id": corners[imin].corner_id,
        "argmax_params": dict(corners[imax].params),
        "argmin_params": dict(corners[imin].params),
        "argmax_directions": dict(corners[imax].directions),
        "argmin_directions": dict(corners[imin].directions),
        "values": [
            {"corner_id": c.corner_id, "value": v} for c, v in zip(corners, values, strict=True)
        ],
    }


def predict_extreme_corner(
    params: Sequence[ProcessParam], slopes: Mapping[str, float], *, maximize: bool = True
) -> Corner:
    """slope 符号 → 极值角预测（spread 极值定位恒等式的预测端）。

    每参数：slope>0 → "hi"（maximize）/"lo"（argmin）；slope<0 反之；
    slope==0 → "lo"（并列钉枚举序首个的同一口径，两向一致）。slopes 缺
    参数名 → ValueError。
    """
    plist = list(params)
    if not plist:
        raise ValueError("params 不能为空")
    directions: dict[str, str] = {}
    values: dict[str, float] = {}
    for p in plist:
        if p.name not in slopes:
            raise ValueError(f"slopes 缺参数 {p.name}")
        s = _finite(slopes[p.name], f"slopes.{p.name}")
        if s > 0.0:
            d = "hi" if maximize else "lo"
        elif s < 0.0:
            d = "lo" if maximize else "hi"
        else:
            d = "lo"  # 零斜率并列：钉 "lo"（与枚举序并列取首个同口径）
        directions[p.name] = d
        values[p.name] = p.hi if d == "hi" else p.lo
    return Corner(
        corner_id=_corner_id_for_directions(plist, directions),
        directions=directions,
        params=values,
    )


def corner_spread(
    params: Sequence[ProcessParam], fn: Callable[[dict[str, float]], float]
) -> dict[str, Any]:
    """角间 spread 表（callable 路径）：fn(params dict) → 标量，逐角求值。

    fn 返回非有限值 → ValueError；并列极值取枚举序首个（确定性）。
    """
    if not callable(fn):
        raise TypeError("fn 必须为 callable（params dict → float）")
    corners = enumerate_corners(params)
    values = [_finite(fn(dict(c.params)), f"fn({c.corner_id})") for c in corners]
    return _spread_from_values(corners, values)


def corner_spread_from_slopes(
    params: Sequence[ProcessParam], slopes: Mapping[str, float], r_nominal: float = 0.0
) -> dict[str, Any]:
    """角间 spread 表（参数化斜率表路径）：r(corner)=r_nominal+Σ s_j·Δp_j。

    与线性 fn 的 corner_spread 逐值一致（同序求和）；slopes 缺参数名 →
    ValueError。极值角定位恒等式：argmax/argmin corner_id ==
    predict_extreme_corner(...).corner_id（全非零斜率时逐位，测试钉）。
    """
    plist = list(params)
    corners = enumerate_corners(plist)
    slopes_f: dict[str, float] = {}
    for p in plist:
        if p.name not in slopes:
            raise ValueError(f"slopes 缺参数 {p.name}")
        slopes_f[p.name] = _finite(slopes[p.name], f"slopes.{p.name}")
    r0 = _finite(r_nominal, "r_nominal")
    values: list[float] = []
    for c in corners:
        acc = r0
        for p in plist:
            acc = acc + slopes_f[p.name] * (c.params[p.name] - p.nominal)
        values.append(_finite(acc, f"斜率表预测值({c.corner_id})"))
    return _spread_from_values(corners, values)


def expected_extreme_directions(response_class: str) -> dict[str, str]:
    """响应类 → 已声明方向表（None 项不声明；未知类 ValueError）。"""
    if response_class not in RESPONSE_CLASS_TABLE:
        raise ValueError(f"response_class 必须是 {sorted(RESPONSE_CLASS_TABLE)} 之一")
    table = RESPONSE_CLASS_TABLE[response_class]
    return {k: v for k, v in table.items() if v is not None}
