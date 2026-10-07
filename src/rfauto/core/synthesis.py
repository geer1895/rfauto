"""E6a 微带线综合引擎（扩展方案 §E6a）。

正向：skrf MLine (Hammerstad-Jensen) 计算 Z0/εeff
反解：自写 brentq 求逆（HJ 闭式 + 扫描括号）

设计决策：
- 正向锁死 model='hammerstadjensen'（与 G0 验证一致）
- 反解结果回代正向做自洽断言（|ΔZ0|<0.5Ω）
- 层叠复用 configs/materials.yaml（带 source/verified_by）
- L0 层，无 SDK 依赖（只有 skrf + numpy + scipy）

验收（扩展方案）：
① 反解→正向回算 |ΔZ0|<0.5Ω
② 响应性：Z0 单调降 → W 单调升
③ 对拍矩阵：常规+极端 W/h + 多频点，常规 <3% 极端 <5%
④ 超限标 needs_calibration 而非静默通过
精度档案：knowledge/precision_profiles.yaml#synthesis.forward_z0（行为=WARN，last_verified=2026-10-02）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.materials import load_materials_yaml

# ─── 层叠数据 ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Stackup:
    """微带线层叠参数（从 materials.yaml 加载）。"""
    name: str
    epsilon_r: float
    thickness_mm: float
    loss_tangent: float = 0.0
    rho: float = 1.724e-8     # copper resistivity (ohm·m)
    rough_mm: float = 0.5e-3  # surface roughness (mm)

    @classmethod
    def from_materials_yaml(
        cls,
        stackup_name: str,
        materials_path: str | Path | None = None,
    ) -> Stackup:
        """从 configs/materials.yaml 加载层叠参数（发现顺序见 core/materials）。"""
        # AU-5 单点：路径发现+读档收敛 core/materials（env 覆盖+
        # 向上发现在此生效）；签名与缺省解析路径零变化。
        data = load_materials_yaml(materials_path)

        materials = data.get("materials", {})
        if stackup_name not in materials:
            raise KeyError(f"未知层叠: {stackup_name}，可用: {list(materials.keys())}")

        mat = materials[stackup_name]
        return cls(
            name=stackup_name,
            epsilon_r=float(mat.get("epsilon_r", 1.0)),
            thickness_mm=float(mat.get("thickness_mm", 1.0)),
            loss_tangent=float(mat.get("loss_tangent", 0.0)),
            rho=float(mat.get("rho", 1.724e-8)),
            rough_mm=float(mat.get("rough_mm", 0.5e-3)),
        )


# ─── 正向计算（skrf MLine）────────────────────────────────────────────────────


class ForwardMedia(tuple):
    """forward_z0 的介质显式化载体（XA-4，2026-10-02）。

    逻辑字段三元组 {z0, er_eff, source}：source ∈ {"ep_reff", "er_eff",
    "beta", "bulk_fallback"}，显式标记 εeff 取值通道（skrf 属性名随版本
    漂移：2.1 是 ep_reff、旧版 er_eff；都缺走 β 反推；再缺兜底体介电常数）。

    **实现形态是长度 2 的 tuple 子类**（不是 dataclass）：全仓既有消费点
    以 ``z0, er = forward_z0(...)`` 二元组解包或 ``[0]/[1]`` 索引消费
    （实测 src/tests/scripts 共 329 处引用、其中解包/索引消费 152 行；
    #315 旧口径零破坏惯例）；``z0``/``er_eff`` 以 property 暴露、
    ``source`` 以实例属性挂载（tuple 子类实例自带 __dict__）。相等语义=
    数值相等（与裸 2 元组 ``==`` 兼容），source 不进 __eq__（保全部既有
    数值断言逐位不变）；需要来源比较用 ``.source``。
    """

    def __new__(cls, z0: float, er_eff: float, source: str) -> ForwardMedia:
        self = super().__new__(cls, (float(z0), float(er_eff)))
        self.source = str(source)  # type: ignore[attr-defined]
        return self

    @property
    def z0(self) -> float:
        return self[0]

    @property
    def er_eff(self) -> float:
        return self[1]

    def __reduce__(self) -> tuple:  # pickle/deepcopy 保 source（默认 reduce 会丢）
        return (self.__class__, (self[0], self[1], self.source))

    def __repr__(self) -> str:
        return (f"ForwardMedia(z0={self[0]!r}, er_eff={self[1]!r}, "
                f"source={self.source!r})")


def _forward_media_source_of(mline: Any, freq_ghz: float, er_bulk: float) -> tuple[float, str]:
    """εeff 取值通道探测（ep_reff → er_eff → beta → bulk_fallback）。

    β 反推口径：εeff = (β·c / (2π·f))²。兜底回退体介电常数（会把 λ 反推的
    f0 带偏——2026-09-03 v0 实测；XA-4 起该通道显式标记并下泄
    SynthesisResult.status="er_eff_fallback"，不再静默）。
    """
    try:
        return float(np.real(mline.ep_reff[0])), "ep_reff"
    except AttributeError:
        pass
    try:
        return float(mline.er_eff[0]), "er_eff"
    except AttributeError:
        pass
    try:
        beta = float(np.real(mline.beta[0]))
        omega = 2 * np.pi * freq_ghz * 1e9
        c0 = 299792458.0
        return (beta * c0 / omega) ** 2, "beta"
    except Exception:
        return float(er_bulk), "bulk_fallback"


def forward_media(
    width_mm: float,
    freq_ghz: float,
    stackup: Stackup,
) -> ForwardMedia:
    """正向计算：微带线宽度 → ForwardMedia（z0, er_eff + source 来源标记）。

    使用 skrf MLine (Hammerstad-Jensen) 模型（与 G0 验证一致）；εeff 通道
    探测见 _forward_media_source_of（XA-4 来源显式化）。
    """
    import skrf

    mline = skrf.media.MLine(
        frequency=skrf.Frequency(freq_ghz, freq_ghz, 1, unit="GHz"),
        w=width_mm * 1e-3,        # m
        h=stackup.thickness_mm * 1e-3,  # m
        ep_r=stackup.epsilon_r,
        tand=stackup.loss_tangent,
        rho=stackup.rho,
        rough=stackup.rough_mm * 1e-3,  # m
        model="hammerstadjensen",
    )
    z0 = float(np.real(mline.z0[0]))
    er_eff, source = _forward_media_source_of(mline, freq_ghz, stackup.epsilon_r)
    return ForwardMedia(z0, er_eff, source)


def _probe_skrf_version() -> str:
    """skrf 版本显式探测（XA-4：εeff 属性名随版本漂移，版本入 meta）。

    本机 venv 实证 importlib.metadata 对 skrf 无 dist-info（uv 装法），
    PackageNotFoundError 必须回退 skrf.__version__——探测链显式化即为此。
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return str(version("skrf"))
        except PackageNotFoundError:
            pass
        except Exception:  # pragma: no cover - 元数据损坏兜底
            pass
    except ImportError:  # pragma: no cover - 标准库恒在
        pass
    import skrf
    return str(getattr(skrf, "__version__", "unknown"))


def forward_z0(
    width_mm: float,
    freq_ghz: float,
    stackup: Stackup,
) -> ForwardMedia:
    """正向计算：微带线宽度 → ForwardMedia（长度 2 tuple：z0, εeff；.source 来源）。

    旧口径 ``-> tuple[float, float]`` 二元组解包/[0][1] 索引消费点零破坏
    （ForwardMedia 是长度 2 tuple 子类，XA-4 2026-10-02）；新增消费用
    ``.z0/.er_eff/.source`` 属性。εeff 回退体介电常数的通道显式见
    forward_media。
    """
    return forward_media(width_mm, freq_ghz, stackup)


# ─── 反解（brentq 求逆）───────────────────────────────────────────────────────

def inverse_width(
    z0_target: float,
    freq_ghz: float,
    stackup: Stackup,
    *,
    w_min_mm: float = 0.05,
    w_max_mm: float = 20.0,
    xtol: float = 1e-6,
) -> tuple[float, float, str]:
    """反解：目标阻抗 → 微带线宽度。

    使用 brentq 求逆，反解结果回代正向做自洽断言。

    Returns:
        (width_mm, z0_actual, status)
        status: "ok" | "needs_calibration" (如果回代偏差>0.5Ω)
    """
    from scipy.optimize import brentq

    def objective(w_mm: float) -> float:
        z0, _ = forward_z0(w_mm, freq_ghz, stackup)
        return z0 - z0_target

    # 扫描找括号：Z0 随 W 单调递减
    # 验证单调性
    z0_lo, _ = forward_z0(w_min_mm, freq_ghz, stackup)
    z0_hi, _ = forward_z0(w_max_mm, freq_ghz, stackup)

    if z0_lo < z0_target:
        # 目标阻抗低于最窄线宽的阻抗——无法求解
        return w_min_mm, z0_lo, "needs_calibration"
    if z0_hi > z0_target:
        # 目标阻抗高于最宽线宽的阻抗——无法求解
        return w_max_mm, z0_hi, "needs_calibration"

    # brentq 求解
    w_solved = brentq(objective, w_min_mm, w_max_mm, xtol=xtol)

    # 自洽断言：回代正向
    z0_actual, _er_eff = forward_z0(w_solved, freq_ghz, stackup)
    delta = abs(z0_actual - z0_target)

    status = "ok" if delta < 0.5 else "needs_calibration"

    return w_solved, z0_actual, status


# ─── 标称线宽单源（XC-W，2026-10-02）──────────────────────────────────────────
#
# 月度宏图 §10.1 弱点 6「50Ω 宽常数四系」收敛点：50Ω 标称线宽的唯一计算源。
# 历史上渲染缺省/注册表/文档散落 1.1134（round4@2.5GHz）、1.1133（round4@2.4GHz）、
# 1.113（round3）、1.112（round4@5.8GHz 无耗链）、1.1117（round4@2.5GHz 无耗链）
# 五档字面量副本；单源化后各系一次 inverse_width(50) 计算、同参系逐位同值，
# 由 tests/unit/test_width_single_source.py 钉住。归档字面量（TEMPLATE_NOMINAL、
# docs/templates meta、各 *_NOMINAL 字面量落表）不改值，只做逐位一致性钉扎。

@cache
def _inverse_width_nominal(
    z0_ohm: float,
    freq_ghz: float,
    epsilon_r: float,
    thickness_mm: float,
    loss_tangent: float,
    rho: float,
    rough_mm: float,
) -> float:
    """inverse_width 的进程内缓存底座（XC-W 唯一计算点，不对外）。

    键=层叠六标量（与 forward_media 实际消费面一一对应；name 不进正向），
    同 (Z0, f, εr, h, tanδ, ρ, rough) 全仓只跑一次 brentq（单次 ~5-15ms；
    进程内首个 MLine 构造另有 ~1s 级 skrf 一次性初始化，与本缓存无关）。
    """
    stackup = Stackup(
        name="nominal_width",
        epsilon_r=float(epsilon_r),
        thickness_mm=float(thickness_mm),
        loss_tangent=float(loss_tangent),
        rho=float(rho),
        rough_mm=float(rough_mm),
    )
    w, _z0_actual, status = inverse_width(float(z0_ohm), float(freq_ghz), stackup)
    if status != "ok":
        raise ValueError(
            f"标称线宽反解未自洽（status={status!r}，z0={z0_ohm}Ω@"
            f"{freq_ghz}GHz，εr={epsilon_r} h={thickness_mm}mm）")
    return float(w)


def _round_width(w: float, digits: int | None) -> float:
    """标称档舍入（digits=None=原值不舍入，供链内继续精算的消费方）。"""
    return float(w) if digits is None else round(float(w), int(digits))


@cache
def nominal_width_mm(
    z0_ohm: float,
    freq_ghz: float,
    stackup_name: str,
    *,
    digits: int | None = 4,
    materials_path: str | Path | None = None,
) -> float:
    """configs/materials.yaml 层叠系的标称线宽单源（XC-W 权威源）。

    「50Ω 馈线宽」缺省档的唯一计算点：inverse_width(50)@各 (εr,h,f) 即权威
    （铁律 1c），返回按 digits 舍入的标称档。rogers4350b_h0.508 标准档：
    @2.5GHz round4=1.1134 / round3=1.113；@2.4GHz round4=1.1133（round3 同
    为 1.113，跨频同档逐位同值由一致性测试钉住）。round 为 IEEE754 就近
    舍入，与历史字面量逐位一致（repr 同串）——渲染字节零漂移。

    Args:
        z0_ohm: 目标阻抗（Ω）。
        freq_ghz: 设计频点（GHz）。
        stackup_name: materials.yaml 层叠键。
        digits: 舍入位数（None=原值）；None 供设计链继续精算，标称档用 3/4。
        materials_path: materials.yaml 路径（缺省走发现链）。

    Returns:
        标称线宽（mm）。
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    return _round_width(
        _inverse_width_nominal(
            z0_ohm, freq_ghz, stackup.epsilon_r, stackup.thickness_mm,
            stackup.loss_tangent, stackup.rho, stackup.rough_mm),
        digits)


def lossless_width_mm(
    z0_ohm: float,
    freq_ghz: float,
    epsilon_r: float = 3.66,
    thickness_mm: float = 0.508,
    *,
    digits: int | None = 4,
) -> float:
    """无耗裸层叠系（tanδ=0，ρ/rough 取 Stackup 缺省）标称线宽单源（XC-W）。

    hairpin/c3/c4/combline/varactor（@2.5GHz→1.1117）与 C2 阵列链
    （@5.8GHz→1.112）的共用口径——这些设计链的 KJ/HJ 闭式均为无耗介质，
    tanδ 不进其正向，故 50Ω 宽须取无耗层叠反解（与 nominal_width_mm 的
    yaml 层叠档 1.1134 差 1.7µm，源于 HJ Z0 随介质损耗弱变——两档并存
    是参数系不同，非同参漂移，一致性测试分系钉住）。
    """
    bare = Stackup(name="lossless_width", epsilon_r=float(epsilon_r),
                   thickness_mm=float(thickness_mm))
    return _round_width(
        _inverse_width_nominal(
            z0_ohm, freq_ghz, bare.epsilon_r, bare.thickness_mm,
            bare.loss_tangent, bare.rho, bare.rough_mm),
        digits)


# ─── 综合入口 ──────────────────────────────────────────────────────────────────

@dataclass
class SynthesisResult:
    """综合结果。"""
    z0_target: float
    freq_ghz: float
    stackup_name: str
    width_mm: float
    z0_actual: float
    epsilon_eff: float
    # XA-4（2026-10-02）扩 "er_eff_fallback"：εeff 走体介电常数兜底通道时
    # 显式下泄（不可信标记而非静默通过，#316 多报方向）；Z0 回代失败
    # needs_calibration 优先级更高，两真并存时保留 needs_calibration。
    status: str  # "ok" | "needs_calibration" | "er_eff_fallback"
    delta_z0: float
    # XA-4：εeff 来源标记（ep_reff|er_eff|beta|bulk_fallback）+ skrf 版本
    # 显式探测（εeff 属性名随 skrf 版本漂移，版本入 meta 供 provenance）。
    er_eff_source: str = "ep_reff"
    skrf_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "z0_target": self.z0_target,
            "freq_ghz": self.freq_ghz,
            "stackup": self.stackup_name,
            "width_mm": round(self.width_mm, 4),
            "z0_actual": round(self.z0_actual, 2),
            "epsilon_eff": round(self.epsilon_eff, 4),
            "status": self.status,
            "delta_z0": round(self.delta_z0, 4),
            "er_eff_source": self.er_eff_source,
            "skrf_version": self.skrf_version,
        }


def synthesize_mline(
    z0_target: float,
    freq_ghz: float,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> SynthesisResult:
    """微带线综合：目标阻抗 → 线宽。

    E6a 主入口。正向用 skrf MLine (HJ)，反解用 brentq。

    Args:
        z0_target: 目标特性阻抗 (Ω)
        freq_ghz: 频率 (GHz)
        stackup_name: 层叠名称（materials.yaml 键）
        materials_path: materials.yaml 路径（默认 configs/materials.yaml）

    Returns:
        SynthesisResult
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)

    width_mm, z0_actual, status = inverse_width(z0_target, freq_ghz, stackup)
    media = forward_media(width_mm, freq_ghz, stackup)
    er_eff = media.er_eff
    # XA-4（2026-10-02）：εeff 兜底体介电常数的通道显式下泄为
    # er_eff_fallback（λ 系长度不可信的显式标记，#316 多报方向）；
    # needs_calibration（Z0 回代失败）更严重，优先保留。
    if status == "ok" and media.source == "bulk_fallback":
        status = "er_eff_fallback"

    return SynthesisResult(
        z0_target=z0_target,
        freq_ghz=freq_ghz,
        stackup_name=stackup_name,
        width_mm=width_mm,
        z0_actual=z0_actual,
        epsilon_eff=er_eff,
        status=status,
        delta_z0=abs(z0_actual - z0_target),
        er_eff_source=media.source,
        skrf_version=_probe_skrf_version(),
    )


# ─── 批量综合（对拍矩阵用）────────────────────────────────────────────────────

def synthesize_batch(
    targets: list[tuple[float, float, str]],
    *,
    materials_path: str | Path | None = None,
) -> list[SynthesisResult]:
    """批量综合：(z0_target, freq_ghz, stackup_name) 列表 → 结果列表。"""
    return [
        synthesize_mline(z0, f, s, materials_path=materials_path)
        for z0, f, s in targets
    ]


# ─── 模型综合引擎（方向 8a：指标→闭式公式初值→配方草稿）──────────────────────

@dataclass
class ModelSynthesisResult:
    """模型综合结果。"""
    model: str
    goal: dict[str, Any]
    params: dict[str, float]
    recipe_draft: dict[str, Any]
    notes: list[str]
    #: 设计侧读数面板（W4-A/P9 起可选；结构化输出供 kernel_cards/服务层
    #: 直消费——notes 的人类可读摘要之外的单源数字通道）。缺省 None 零变化。
    panel: dict[str, float] | None = None


def synthesize_wilkinson(
    f0_ghz: float = 2.4,
    z0_ohm: float = 50.0,
    s11_target_db: float = -20.0,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> ModelSynthesisResult:
    """Wilkinson 功分器综合：f0 + Z0 → arm_len + series_w + shunt_w.

    闭式公式：
    - arm_len = lambda/4 = c / (4 * f0 * sqrt(epsilon_eff))
    - series_w: Z0*sqrt(2) ≈ 70.7Ω λ/4 臂线宽（标准 Wilkinson 两臂，比馈线窄；
      隔离电阻 2*Z0=100Ω 接两臂末端，不是线宽）
    - shunt_w: Z0 = 50Ω 馈线宽（宽）

    #154 语义对齐：series/shunt 口径与 TEMPLATE_META.param_semantics、
    models/wilkinson_power_divider、fake _wilkinson_s11_min 统一
    （series=70.7Ω 臂窄、shunt=50Ω 馈线宽，2026-09-04 统一口径）。

    XA-3 迭代序修正（2026-10-02）：arm_len 的 εeff 必须取臂线宽自身——
    inverse_width(70.7Ω)→forward_z0(w_series)→εeff(w_series)→λ/4；旧口径
    εeff@w=1mm 近似在名义点使 λ/4 偏约 +1.9%（w=1mm 比 70.7Ω 臂宽、εeff 偏
    高、λ/4 偏短；18.57→18.92mm@2.4GHz 名义点实测；XA-5 数值锚钉
    tests/unit/test_synthesis_patch_anchor.py）。
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    c_mm_ghz = 299.792458  # mm*GHz

    # series arm width: Zt = Z0*sqrt(2) ≈ 70.7Ω（两臂，比 50Ω 窄）
    series_result = synthesize_mline(z0_ohm * np.sqrt(2), f0_ghz, stackup_name, materials_path=materials_path)
    series_w = series_result.width_mm

    # shunt feeder width: Z0 = 50Ω（宽）
    shunt_result = synthesize_mline(z0_ohm, f0_ghz, stackup_name, materials_path=materials_path)
    shunt_w = shunt_result.width_mm

    # XA-3 迭代序：臂长用臂线宽自身 εeff（不再 εeff@w=1mm 近似）
    series_media = forward_media(series_w, f0_ghz, stackup)
    lambda_4_mm = c_mm_ghz / (4 * f0_ghz * np.sqrt(series_media.er_eff))

    params = {
        "f0_ghz": f0_ghz,
        "arm_len_mm": round(lambda_4_mm, 2),
        "series_w_mm": round(series_w, 3),
        "shunt_w_mm": round(shunt_w, 3),
    }

    recipe_draft = {
        "model": "wilkinson_power_divider",
        "recipe_version": 1,
        "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"solver": "DrivenModal", "freq_range_ghz": [f0_ghz * 0.7, f0_ghz * 1.3], "points": 401},
        "objectives": [
            {"metric": "s11_db", "band": [f0_ghz * 0.96, f0_ghz * 1.04], "op": "max_below", "value": s11_target_db},
        ],
    }

    notes = [
        f"lambda/4 = {lambda_4_mm:.2f}mm @ {f0_ghz}GHz "
        f"(εeff@w_series={series_media.er_eff:.4f}，w={series_w:.3f}mm，"
        f"εeff 来源 {series_media.source})",
        f"70.7ohm series arm = {series_w:.3f}mm",
        f"50ohm shunt feeder = {shunt_w:.3f}mm",
    ]
    return ModelSynthesisResult(model="wilkinson_power_divider", goal={"f0_ghz": f0_ghz, "z0_ohm": z0_ohm},
                                params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_branchline(
    f0_ghz: float = 2.4,
    z0_ohm: float = 50.0,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> ModelSynthesisResult:
    """Branchline coupler综合：f0 + Z0 → series/shunt 臂长（各自 εeff）+ 臂宽.

    闭式公式（XA-3 迭代序修正，2026-10-02）：
    - series_len = λ/4 @ εeff(inverse_width(Z0/√2))——35.35Ω series 臂按自身
      线宽的 εeff 精算；shunt_len = λ/4 @ εeff(inverse_width(Z0))——50Ω shunt
      臂按自身 εeff。两臂 εeff 差数个百分点，不可再共用同一臂长（旧口径
      arm_len=λ/4@εeff(w=1mm) 对两臂都是双重近似）；
    - series_w: 35.35Ω (Z0/sqrt(2)) line width for series arms
    - shunt_w: 50Ω line width for shunt arms

    #315 兼容：arm_len_mm 保留为弃用别名（=series_len_mm），旧消费方
    （oe_templates 方环渲染/grid、template_specs 物理角色映射、fake）零破坏；
    迁移指引用 notes 弃用注记。series/shunt 严格设计（方环变矩形环）需渲染
    透传双键，属渲染层改动不在本批（报告主代理）。
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    c_mm_ghz = 299.792458

    series_result = synthesize_mline(z0_ohm / np.sqrt(2), f0_ghz, stackup_name, materials_path=materials_path)
    shunt_result = synthesize_mline(z0_ohm, f0_ghz, stackup_name, materials_path=materials_path)
    # XA-3 迭代序：各臂 λ/4 用各自线宽的 εeff（inverse_width→forward_z0）
    media_series = forward_media(series_result.width_mm, f0_ghz, stackup)
    media_shunt = forward_media(shunt_result.width_mm, f0_ghz, stackup)
    series_len_mm = c_mm_ghz / (4 * f0_ghz * np.sqrt(media_series.er_eff))
    shunt_len_mm = c_mm_ghz / (4 * f0_ghz * np.sqrt(media_shunt.er_eff))

    params = {
        "f0_ghz": f0_ghz,
        "series_len_mm": round(series_len_mm, 2),
        "shunt_len_mm": round(shunt_len_mm, 2),
        # 弃用别名（#315）：=series_len_mm；渲染方环暂消费本键，双键透传留渲染批
        "arm_len_mm": round(series_len_mm, 2),
        "series_w_mm": round(series_result.width_mm, 3),
        "shunt_w_mm": round(shunt_result.width_mm, 3),
    }
    recipe_draft = {
        "model": "branchline_coupler", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"solver": "DrivenModal", "freq_range_ghz": [f0_ghz * 0.7, f0_ghz * 1.3], "points": 401},
        "objectives": [{"metric": "s11_db", "band": [f0_ghz * 0.96, f0_ghz * 1.04], "op": "max_below", "value": -15}],
    }
    notes = [f"series λ/4 = {series_len_mm:.2f}mm @ 35.35Ω 臂（εeff="
             f"{media_series.er_eff:.4f}，w={series_result.width_mm:.3f}mm）",
             f"shunt λ/4 = {shunt_len_mm:.2f}mm @ 50Ω 臂（εeff="
             f"{media_shunt.er_eff:.4f}，w={shunt_result.width_mm:.3f}mm）",
             f"35.35ohm series = {series_result.width_mm:.3f}mm",
             f"50ohm shunt = {shunt_result.width_mm:.3f}mm",
             "arm_len_mm 为弃用别名（#315 兼容）：映射 series_len_mm；shunt 臂用 "
             "shunt_len_mm（各自 εeff 各自臂长，XA-3 2026-10-02）"]
    return ModelSynthesisResult(model="branchline_coupler", goal={"f0_ghz": f0_ghz}, params=params,
                                recipe_draft=recipe_draft, notes=notes)


def patch_fringing_delta_l(w_m: float, h_m: float, er_eff: float) -> float:
    """矩形贴片单辐射边缘等效长度增量 ΔL（Hammerstad 1975 原式，SI 米制进出）。

    原式（Hammerstad 1975；Pozar eq.4.23 同口径，与 oe_templates/closedform.
    _open_end_delta_mm、core/slotline_transitions 同式）::

        ΔL/h = 0.412·(εeff+0.3)(w/h+0.264) / [(εeff−0.258)(w/h+0.8)]

    每个辐射边缘各延伸 ΔL，两边缘合计 2ΔL。本函数是全仓唯一 ΔL 算术单源
    （XA-1/PV-016 三副本收敛，2026-10-02）；εeff 由调用方按同口径给出。

    XA-1/PV-016 仲裁注记（runs/xa1_arbitration/xa1_arbitration_evidence.json，
    2026-10-02）：历史三副本（synthesize_patch / rf_match.patch_length /
    closedform._array_patch_eps_dl）以 0.824=2×0.412 作"两边缘合计"常数、
    调用侧再 ×2 ⇒ 总扣 4ΔL（疑似双计）。离线锚仲裁判 INCONCLUSIVE：两语义
    K=f_dip·L 预测差仅 ~0.02%（远小于 ±5% 锚不确定度），openEMS 带（76.8±5%）
    双落、HFSS 带（99.8±5%）双出；归档点反解引擎隐含总扣 D_eng=0.75–1.28mm
    介于 2ΔL(0.49)–4ΔL(0.97) 且散布≫语义差（倾向 4ΔL 只记不强判）；HFSS 锚
    反解 D_eng<0 物理不可能（本机口径，非 TM10 物理量）。故本函数只单源化
    0.412 每边缘原式，调用侧现行总扣口径零行为维持；语义翻转（总扣 2ΔL）
    需联动 ARRAY_NOMINAL/docs meta/fake 逆/symbolic_fit 判决式，留主代理批。
    语义终裁挂 L5 v2 批（runs/xa1_arbitration/l5_sweep/criteria.md §一；
    R1-2 审查批 2026-10-04 出处标签注记）。
    """
    w = float(w_m)
    h = float(h_m)
    if not (w > 0.0 and h > 0.0):
        raise ValueError(f"w_m/h_m 必须为正，得 {w_m!r}/{h_m!r}")
    if not float(er_eff) > 1.0:
        raise ValueError(f"er_eff 必须 > 1，收到 {er_eff!r}")
    u = w / h
    return 0.412 * h * (er_eff + 0.3) * (u + 0.264) / ((er_eff - 0.258) * (u + 0.8))


def patch_rin_edge_balanis(w_mm: float, h_mm: float, f0_ghz: float) -> float:
    """矩形贴片边缘馈输入电阻 Rin_edge（Ω）。

    出处口径：Balanis《Antenna Theory: Analysis and Design》4th ed. §14-8
    （**页码/式号 UNVERIFIED 待核**——按任务书 §B-1 XA-2 传递口径落地，未持
    原文逐位核对，引用该出处前必须回原文核验，不冒充已核）。

    模型（谐振腔一阶口径，两辐射槽经腔体驻波变换到边缘）::

        Rin_edge = 1 / (2·(G1 + G12))
        G1  = (W/(120·λ0))·[1 − (k0·h)²/24]              单槽自电导（k0·h≪1）
        G12 = (1/(120π²))·∫₀^π sin³θ·[sin((k0h/2)cosθ)/cosθ]²·J0(k0·W·sinθ) dθ
                                                          两槽互电导

    积分经 u=cosθ 代换为 ∫₋₁¹(1−u²)·[sin(a·u)/u]²·J0(k0·W·√(1−u²)) du
    （a=k0h/2；u→0 可去奇点极限 a²，数值稳定；scipy.quad 确定性求积，
    数值只在确定性内核——铁律 7）。

    适用域：k0·h ≪ 1（守卫 k0·h < 0.3，厚基板越域显式报错不外推，
    #122/#1c 惯例）；贴片在谐振（L=λg/2 口径）假设下成立。
    """
    from scipy.integrate import quad
    from scipy.special import j0

    w = float(w_mm) * 1e-3
    h = float(h_mm) * 1e-3
    f0 = float(f0_ghz) * 1e9
    if not (w > 0.0 and h > 0.0 and f0 > 0.0):
        raise ValueError(f"w_mm/h_mm/f0_ghz 须为正，得 {w_mm!r}/{h_mm!r}/{f0_ghz!r}")
    c0 = 299792458.0
    k0 = 2.0 * math.pi * f0 / c0
    lam0 = c0 / f0
    if not k0 * h < 0.3:
        raise ValueError(
            f"k0·h={k0 * h:.3f} 超出单槽电导近似适用域（须 ≪1，守卫 <0.3）；"
            "厚基板口径需回 Balanis 原式重推，不外推")
    g1 = (w / (120.0 * lam0)) * (1.0 - (k0 * h) ** 2 / 24.0)
    a = k0 * h / 2.0
    kw = k0 * w

    def _integrand(u: float) -> float:
        su = a if abs(u) < 1e-9 else math.sin(a * u) / u
        arg = kw * math.sqrt(max(0.0, 1.0 - u * u))
        return su * su * float(j0(arg)) * (1.0 - u * u)

    integral, _abserr = quad(_integrand, -1.0, 1.0, limit=400)
    g12 = integral / (120.0 * math.pi ** 2)
    return 1.0 / (2.0 * (g1 + g12))


def patch_cavity_metrics(w_mm: float, l_mm: float, h_mm: float,
                         f0_ghz: float, er: float, *,
                         tan_d: float = 0.0,
                         sigma_s_per_m: float = 5.8e7,
                         vswr: float = 2.0,
                         er_eff: float | None = None) -> dict[str, float]:
    """矩形贴片腔模读数面板：Q 分解 / 分数带宽 / 方向性 / 辐射效率（W4-A/P9）。

    式面（#1c 原文核对，2026-10-05：Balanis《Antenna Theory》4th ed.
    Ch.14 原文页 852-854 + Table 14.2 逐式核对，Semnan 镜像 PDF）：

    - 总 Q（式 14-83，薄基板 Qsw→∞ 舍弃）::

        1/Qt = 1/Qrad + 1/Qc + 1/Qd

    - 导体 Q（式 14-84）：Qc = h·√(π·f·μ0·σ)；介质 Q（式 14-85）：
      Qd = 1/tanδ（tanδ=0 → 无耗 Qd=inf）；
    - 辐射 Q（式 14-86 + 14-86a + 14-87a/b）：Qrad = 2ω·ε0·εr·K/(h·(Gt/l))，
      矩形 TM010 的 K = Le/4（式 14-87a）、Gt/l = Grad/W（式 14-87b），
      整理为 Qrad = ω·ε0·εr·Le·W/(2h·Grad)；Grad = 2(G1+G12) =
      1/Rin_edge（单源 patch_rin_edge_balanis，同书 §14-8 口径）；
      Le = L + 2ΔL（有效长度，ΔL 单源 patch_fringing_delta_l）；
    - 分数带宽（式 14-88a）：BW = (VSWR−1)/(Qt·√VSWR)；
    - 辐射效率（式 14-90，薄基板口径）：e_cds = Qt/Qrad；
    - 方向性（式 14-55 + 14-55a）：D0 = π·(2πW/λ0)²/I2，

          I2 = ∫₀^π [sin((k0W/2)cosθ)/cosθ]²·sin³θ·cos²((k0Le/2)sinθ·sinφ)dθdφ

      双重积分经 Jacobi-Anger（∫₀^π cos²(c·sinφ)dφ = (π/2)(1+J0(2c))）
      降为 scipy.quad 一维确定性求积（铁律 7）；大 W 渐近 D0→8·(W/λ0)
      （式 14-57 第二支，测试钉）；式 (14-55) 两形态恒等与单槽渐近的
      π 因子定谳记录见 runs/w4_phase4/w4a/REPORT.md。

    Returns:
        {"q_rad", "q_c", "q_d", "q_total", "bw_frac", "bw_pct",
         "radiation_eff", "d0", "d0_db", "grad_rad_siemens", "le_mm"}。

    适用域：k0·h ≪ 1（守卫同 patch_rin_edge_balanis <0.3，腔模口径）。
    """
    from scipy.integrate import quad
    from scipy.special import j0

    w = float(w_mm) * 1e-3
    length = float(l_mm) * 1e-3
    h = float(h_mm) * 1e-3
    f0 = float(f0_ghz) * 1e9
    e_r = float(er)
    if not (w > 0.0 and length > 0.0 and h > 0.0 and f0 > 0.0 and e_r > 1.0):
        raise ValueError(
            f"patch_cavity_metrics: 几何/频率/εr 须正且 εr>1，得 "
            f"w={w_mm!r}, l={l_mm!r}, h={h_mm!r}, f0={f0_ghz!r}, er={er!r}")
    c0 = 299792458.0
    k0 = 2.0 * math.pi * f0 / c0
    lam0 = c0 / f0
    if not k0 * h < 0.3:
        raise ValueError(
            f"k0·h={k0 * h:.3f} 超出腔模口径（守卫 <0.3，同 patch_rin_edge_"
            "balanis）；厚基板需回原文重推，不外推")
    rin_edge = patch_rin_edge_balanis(w * 1e3, h * 1e3, f0 * 1e-9)
    grad = 1.0 / rin_edge                       # Grad = 2(G1+G12)（14-87b 链）
    ere = (float(er_eff) if er_eff is not None
           else _patch_er_eff(w, h, e_r))
    d_l = patch_fringing_delta_l(w, h, ere)     # 有效长度增量（单源 0.412 式）
    le = length + 2.0 * d_l                     # 有效长度（式 14-3 口径）
    omega = 2.0 * math.pi * f0
    eps0 = 8.8541878128e-12
    mu0 = 4.0e-7 * math.pi
    q_rad = omega * eps0 * e_r * le * w / (2.0 * h * grad)          # 14-86 链
    q_c = h * math.sqrt(math.pi * f0 * mu0 * float(sigma_s_per_m))  # 14-84
    td = float(tan_d)
    q_d = math.inf if td <= 0.0 else 1.0 / td                       # 14-85
    q_total = 1.0 / (1.0 / q_rad + 1.0 / q_c + 1.0 / q_d)           # 14-83
    s_v = float(vswr)
    if not s_v > 1.0:
        raise ValueError(f"vswr 须 >1，得到 {vswr!r}")
    bw_frac = (s_v - 1.0) / (q_total * math.sqrt(s_v))              # 14-88a
    e_rad = q_total / q_rad                                          # 14-90
    # 方向性 D0（14-55/14-55a；Jacobi-Anger 降维后一维确定性求积）
    a_w = 0.5 * k0 * w
    beta_le = 0.5 * k0 * le

    def _integrand(theta: float) -> float:
        cz = math.cos(theta)
        sz = math.sin(theta)
        sz_over_cz = a_w if abs(cz) < 1e-9 else math.sin(a_w * cz) / cz
        return (sz_over_cz * sz_over_cz) * sz ** 3 \
            * (1.0 + float(j0(2.0 * beta_le * sz)))

    i2, _abserr = quad(_integrand, 0.0, math.pi, limit=400)
    i2 *= math.pi / 2.0
    d0 = math.pi * (2.0 * math.pi * w / lam0) ** 2 / i2
    return {
        "q_rad": q_rad, "q_c": q_c, "q_d": q_d, "q_total": q_total,
        "bw_frac": bw_frac, "bw_pct": 100.0 * bw_frac,
        "radiation_eff": e_rad, "d0": d0, "d0_db": 10.0 * math.log10(d0),
        "grad_rad_siemens": grad, "le_mm": le * 1e3,
    }


def _patch_er_eff(w_m: float, h_m: float, er: float) -> float:
    """贴片腔模链内的 εeff（与 synthesize_patch 同式：HJ 简化形）。"""
    w = float(w_m)
    h = float(h_m)
    if w <= 0.0 or h <= 0.0:
        raise ValueError("w_m/h_m 必须为正")
    return (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * (1.0 + 12.0 * h / w) ** (-0.5)


def synthesize_patch(
    f0_ghz: float = 2.4,
    er: float = 3.66,
    h_mm: float = 0.508,
    s11_target_db: float = -10.0,
    *,
    rin_t_ohm: float = 50.0,
) -> ModelSynthesisResult:
    """矩形贴片天线综合（Hammerstad 模型）：f0 + er + h → patch_len + patch_w + feed_offset.

    闭式公式：
    - W = c / (2*f0) * sqrt(2/(er+1))
    - er_eff = (er+1)/2 + (er-1)/2 * (1+12*h/W)^(-0.5)
    - ΔL_edge = patch_fringing_delta_l（0.412 每边缘，Hammerstad 1975 单源）
    - dL = 2*ΔL_edge（两边缘合计，数值上=旧 0.824h(…) 常数）
    - L = c/(2*f0*sqrt(er_eff)) - 2*dL   [总扣口径=4ΔL（三副本一致，历史
      仲裁 INCONCLUSIVE 在档 runs/xa1_arbitration/；语义终裁挂 L5 v2 批，
      见 runs/xa1_arbitration/l5_sweep/criteria.md §一——R1-2 审查批
      2026-10-04 出处标签注记，数值零改动；另见 patch_fringing_delta_l
      docstring]
    - feed_offset（XA-2 馈电闭式；2026-10-02 替换旧魔数 l_mm*0.3，
      2026-10-03 #154 单源化改输出口径=**自贴片中心**沿谐振轴的偏移，
      openEMS 官方教程 x=-feed_offset 同基——旧档输出自辐射边 inset 深度
      y0，同键异语义跨面分裂已收口）::

          Rin(off) = Rin_edge·sin²(π·off/L)      （腔体驻波，off 自中心）
          off = (L/π)·arcsin√(Rin_t/Rin_edge)    ≡ L/2 − y0

      Rin_edge 由 patch_rin_edge_balanis 闭式给出（Balanis 4th §14-8 口径，
      页码 UNVERIFIED 待核）；Rin_t=目标馈电阻抗（rin_t_ohm，缺省 50Ω 系统
      阻抗）。物理有效域 0 < Rin_t ≤ Rin_edge（馈点只能从中心向边缘提阻；
      =Rin_edge 退化边缘馈 off=L/2），越域显式 ValueError 不外推；
      off∈(0, L/2] 由 arcsin 值域自动保证。
    """
    c_mm_ghz = 299.792458
    w_mm = c_mm_ghz / (2 * f0_ghz) * np.sqrt(2 / (er + 1))
    er_eff = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 * h_mm / w_mm) ** (-0.5)
    dL = 2.0 * patch_fringing_delta_l(w_mm * 1e-3, h_mm * 1e-3, er_eff) * 1e3
    l_mm = c_mm_ghz / (2 * f0_ghz * np.sqrt(er_eff)) - 2 * dL
    rin_edge = patch_rin_edge_balanis(w_mm, h_mm, f0_ghz)
    rin_t = float(rin_t_ohm)
    if not (0.0 < rin_t <= rin_edge):
        raise ValueError(
            f"rin_t_ohm={rin_t} 超出可达域 (0, {rin_edge:.2f}]Ω：馈点只能"
            "把输入电阻从中心 0Ω 向边缘 Rin_edge 提（sin² 变换），越域不外推")
    feed_offset = (l_mm / math.pi) * math.asin(math.sqrt(rin_t / rin_edge))

    params = {"f0_ghz": f0_ghz, "patch_len_mm": round(l_mm, 2), "patch_w_mm": round(w_mm, 2),
              "feed_offset_mm": round(feed_offset, 2)}
    recipe_draft = {
        "model": "patch_antenna", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"solver": "DrivenModal", "freq_range_ghz": [f0_ghz * 0.8, f0_ghz * 1.2], "points": 401},
        "objectives": [{"metric": "s11_db", "band": [f0_ghz * 0.96, f0_ghz * 1.04], "op": "max_below", "value": s11_target_db}],
    }
    notes = [f"W={w_mm:.2f}mm, L={l_mm:.2f}mm (er_eff={er_eff:.3f})",
             f"feed_offset={feed_offset:.2f}mm（XA-2 闭式自贴片中心：Rin_edge="
             f"{rin_edge:.1f}Ω，Rin_t={rin_t:.1f}Ω，off=(L/π)·arcsin√(Rin_t/"
             "Rin_edge)，openEMS 官方口径 x=-off 同基；#154 单源化"
             " 2026-10-03）"]
    # 腔模读数面板（W4-A/P9：Balanis 14-83~14-90/14-55 链，结构化通道）
    panel = patch_cavity_metrics(w_mm, l_mm, h_mm, f0_ghz, er, er_eff=er_eff)
    notes.append(
        f"腔模面板: Qt={panel['q_total']:.1f}（Qrad={panel['q_rad']:.1f}/"
        f"Qc={panel['q_c']:.1f}/Qd={panel['q_d']:.1f}），BW(VSWR≤2)="
        f"{panel['bw_pct']:.1f}%，D0={panel['d0_db']:.2f} dBi，"
        f"e_rad={100.0 * panel['radiation_eff']:.1f}%（Balanis 4th Ch.14，"
        "tanδ=0 默认——损耗面传 tan_d/sigma_s_per_m）")
    return ModelSynthesisResult(model="patch_antenna", goal={"f0_ghz": f0_ghz}, params=params,
                                recipe_draft=recipe_draft, notes=notes, panel=panel)


def synthesize_mline_model(
    z0_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    line_len_mm: float = 40.0,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> ModelSynthesisResult:
    """均匀微带线综合（WP2.1 锚模板）：目标 Z0 → 线宽（skrf HJ 精算）。

    锚模板三重身份：校准件 + 引擎仲裁探针（S21 相位斜率→εeff，β 金
    标准 #162）+ 数据工厂（单点秒-分钟级）。线宽绝不沿用文档毫米数
    （铁律 1c）——inverse_width 精算并回代自洽。
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    width_mm, z0_actual, _status = inverse_width(z0_ohm, freq_ghz, stackup)
    _, er_eff = forward_z0(width_mm, freq_ghz, stackup)

    params = {"w_mm": round(width_mm, 4), "line_len_mm": line_len_mm,
              "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "mline", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 401},
        "objectives": [{"metric": "s11_db",
                        "band": [freq_ghz * 0.95, freq_ghz * 1.05],
                        "op": "max_below", "value": -15.0}],
    }
    notes = [f"w={width_mm:.4f}mm（目标 {z0_ohm}Ω，实际 {z0_actual:.2f}Ω，"
             f"εeff={er_eff:.4f}）", f"line_len={line_len_mm}mm",
             f"λg@f0={299.792458 / (freq_ghz * er_eff ** 0.5):.2f}mm"]
    return ModelSynthesisResult(
        model="mline", goal={"z0_ohm": z0_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_cpw_model(
    z0_ohm: float = 50.0,
    gap_mm: float = 0.2,
    freq_ghz: float = 2.5,
    line_len_mm: float = 40.0,
    er: float = 3.66,
    h_mm: float = 0.508,
) -> ModelSynthesisResult:
    """均匀共面波导（底接地 CPWG 口径）综合（WP2.1 CPW 锚）。

    openEMS 官方口径 z-min=PEC 强制地，实际结构是 CPWG——合成参照系
    必须同口径（#193 参照系错位教训：skrf CPW 无地口径合成的 50Ω 线
    在真实结构里是 18Ω，|S11| 卡 −6.5dB）。共形映射闭式见
    core/calculators._cpwg_ri（实测 εeff/S11 双锚校验，#198）。
    Z0 随 w 单调递减；brentq 反解后回代自洽。gap 为固定参数
    （Z0 反解存在性依赖 gap，越界显式报错）。
    """
    from scipy.optimize import brentq

    from rfauto.core.calculators import _cpwg_ri

    def z0_of(w_mm: float) -> float:
        return _cpwg_ri(w_mm, gap_mm, h_mm, er)[1]

    w_mm = brentq(lambda w: z0_of(w) - z0_ohm, 1e-4, 10.0, xtol=1e-7)
    eps_eff = _cpwg_ri(w_mm, gap_mm, h_mm, er)[0]

    params = {"w_mm": round(w_mm, 4), "gap_mm": gap_mm,
              "line_len_mm": line_len_mm, "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "cpw", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [{"metric": "s11_db",
                        "band": [freq_ghz * 0.95, freq_ghz * 1.05],
                        "op": "max_below", "value": -15.0}],
    }
    notes = [f"w={w_mm:.4f}mm（目标 {z0_ohm}Ω CPWG 口径，gap={gap_mm}mm，"
             f"εeff={eps_eff:.4f}）", f"line_len={line_len_mm}mm"]
    return ModelSynthesisResult(
        model="cpw", goal={"z0_ohm": z0_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_dipole_model(
    f0_ghz: float = 2.4,
    dipole_w_mm: float = 2.0,
    gap_mm: float = 2.0,
) -> ModelSynthesisResult:
    """半波振子综合（WP1.3）：目标谐振频率 → 全臂长（λ/2 自由空间闭式）。

    L = c/(2·f0)。引擎端效应残差如实记录不采信为锚：#194 冒烟 58mm
    实测谷 2.285GHz vs 闭式 2.585GHz（−11.7%），无 HFSS 仲裁前不下
    结论（铁律：HFSS 为对齐基准）。objectives 走谷深语义（#197：
    s11_db_min + max_below——辐射器件单谐振谷，带内 max 是常数陷阱）。
    """
    length_mm = 299.792458 / (2.0 * f0_ghz)
    params = {"dipole_len_mm": round(length_mm, 4),
              "dipole_w_mm": dipole_w_mm, "gap_mm": gap_mm,
              "f0_ghz": f0_ghz}
    recipe_draft = {
        "model": "dipole", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [f0_ghz * 0.85, f0_ghz * 1.15],
                  "points": 201},
        "objectives": [{"metric": "s11_db_min",
                        "band": [f0_ghz * 0.95, f0_ghz * 1.05],
                        "op": "max_below", "value": -10.0}],
    }
    notes = [f"dipole_len={length_mm:.4f}mm（目标 f0={f0_ghz}GHz，"
             f"λ/2 自由空间闭式）",
             "谷深判据 -10dB（s11_db_min 谷深语义，#197）"]
    return ModelSynthesisResult(
        model="dipole", goal={"f0_ghz": f0_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_wstep_model(
    z1_ohm: float = 50.0,
    z2_ohm: float = 35.0,
    freq_ghz: float = 2.5,
    line_len_mm: float = 40.0,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> ModelSynthesisResult:
    """微带宽度阶跃综合（WP2.2 不连续性基元首个增量）。

    两段目标阻抗各走 inverse_width（skrf HJ 精算，同 mline 手法）；
    阶跃在中点、两段各半长。锚判据=skrf 级联 HJ 闭式（两段理想 TL
    级联为确定性裁判，冒烟脚本 engine_benchmark 同型）。objectives 用
    worst-case s11_db（阶跃非谐振，理想 S11 地板=低频阻抗失配 Γ）。
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    w1_mm, z1_actual, _ = inverse_width(z1_ohm, freq_ghz, stackup)
    w2_mm, z2_actual, _ = inverse_width(z2_ohm, freq_ghz, stackup)
    _, er_eff1 = forward_z0(w1_mm, freq_ghz, stackup)
    _, er_eff2 = forward_z0(w2_mm, freq_ghz, stackup)
    gamma_db = 20 * np.log10(abs((z2_actual - z1_actual)
                                   / (z2_actual + z1_actual)))

    params = {"w1_mm": round(w1_mm, 4), "w2_mm": round(w2_mm, 4),
              "line_len_mm": line_len_mm, "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "wstep", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [{"metric": "s11_db",
                        "band": [freq_ghz * 0.95, freq_ghz * 1.05],
                        "op": "max_below",
                        "value": round(gamma_db + 3.0, 1)}],
    }
    notes = [f"w1={w1_mm:.4f}mm（{z1_actual:.2f}Ω）/ "
             f"w2={w2_mm:.4f}mm（{z2_actual:.2f}Ω）",
             f"理想低频 Γ={gamma_db:.1f}dB（阻抗失配地板）",
             f"εeff: {er_eff1:.4f} / {er_eff2:.4f}"]
    return ModelSynthesisResult(
        model="wstep",
        goal={"z1_ohm": z1_ohm, "z2_ohm": z2_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_tjunc_model(
    z_arm_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    through_len_mm: float = 25.0,
    branch_len_mm: float = 20.0,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> ModelSynthesisResult:
    """微带 T 接头综合（WP2.2 不连续性基元）：全臂统一线宽（inverse_width）。

    对称均分口径：三臂同宽同阻抗。理想无损互易三端口结点输入匹配
    地板 Sii=-1/3（-9.55dB）——objectives max_below 取地板+4.5dB 裕量
    （地板非零=非谐振 worst-case 语义，#195 统计量匹配）。
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    w_mm, z_actual, _ = inverse_width(z_arm_ohm, freq_ghz, stackup)
    _, er_eff = forward_z0(w_mm, freq_ghz, stackup)

    params = {"w_feed_mm": round(w_mm, 4), "w_branch_mm": round(w_mm, 4),
              "through_len_mm": through_len_mm,
              "branch_len_mm": branch_len_mm, "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "tjunc", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [{"metric": "s11_db",
                        "band": [freq_ghz * 0.95, freq_ghz * 1.05],
                        "op": "max_below", "value": -5.0}],
    }
    notes = [f"w={w_mm:.4f}mm（{z_actual:.2f}Ω 全臂，εeff={er_eff:.4f}）",
             "理想结点匹配地板 -9.55dB（Sii=-1/3，无损互易三端口极限）"]
    return ModelSynthesisResult(
        model="tjunc",
        goal={"z_arm_ohm": z_arm_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_bend_model(
    z0_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    arm_len_mm: float = 20.0,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> ModelSynthesisResult:
    """微带直角弯折综合（WP2.2 基元）：全臂统一线宽（inverse_width）。

    未切角直角弯折：|S11| 绝对门 -15dB（文献口径 @低 GHz，50Ω）；
    切角/mitered 为后续变体。
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    w_mm, z_actual, _ = inverse_width(z0_ohm, freq_ghz, stackup)
    _, er_eff = forward_z0(w_mm, freq_ghz, stackup)

    params = {"w_mm": round(w_mm, 4), "arm_len_mm": arm_len_mm,
              "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "bend", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [{"metric": "s11_db",
                        "band": [freq_ghz * 0.95, freq_ghz * 1.05],
                        "op": "max_below", "value": -15.0}],
    }
    notes = [f"w={w_mm:.4f}mm（{z_actual:.2f}Ω，εeff={er_eff:.4f}）",
             "未切角直角弯折 |S11| 门 -15dB（文献口径）"]
    return ModelSynthesisResult(
        model="bend", goal={"z0_ohm": z0_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_via_model(
    z0_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> ModelSynthesisResult:
    """过孔过渡综合（WP2.2 收官基元）：馈线统一 50Ω 线宽（inverse_width）。

    反焊盘同轴口径：Z_via ≈ (60/√εr)·ln(r_pad/r_via)，标称 r_pad=0.8、
    r_via=0.15 → ≈52.5Ω 近 50Ω（设计规则，非严格闭式）。
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    w_mm, z_actual, _ = inverse_width(z0_ohm, freq_ghz, stackup)
    _, er_eff = forward_z0(w_mm, freq_ghz, stackup)

    params = {"w_mm": round(w_mm, 4), "antipad_mm": 0.8,
              "r_via_mm": 0.15, "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "via", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [{"metric": "s11_db",
                        "band": [freq_ghz * 0.95, freq_ghz * 1.05],
                        "op": "max_below", "value": -10.0}],
    }
    notes = [f"w={w_mm:.4f}mm（{z_actual:.2f}Ω，εeff={er_eff:.4f}）",
             "反焊盘同轴口径 ≈52.5Ω（r_pad=0.8/r_via=0.15，近 50Ω）"]
    return ModelSynthesisResult(
        model="via", goal={"z0_ohm": z0_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_atten_pi_model(
    attenuation_db: float = 10.0,
    z0_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    shunt_off_mm: float = 6.0,
) -> ModelSynthesisResult:
    """π 型衰减器综合（WP2.3 首族）：目标衰减 → 三电阻（E4 闭式）。

    电阻值=E4 attenuator_pi 闭式（ABCD 校验）。objectives：
    |S21| mean_within ±0.5dB（平坦衰减，均值语义匹配响应形态）
    + |S11| max_below -20dB（按设计匹配）。
    """
    from rfauto.core.calculators import attenuator_pi

    res = attenuator_pi(attenuation_db=attenuation_db, z0_ohm=z0_ohm)
    r_ser = res["r_series_mid_ohm"]
    r_sh = res["r_shunt_end_ohm"]

    # w_mm 单源（XC-W）：随 freq_ghz 精算（缺省 2.5GHz 档逐位=旧字面量 1.1134）
    params = {"atten_db": attenuation_db,
              "w_mm": nominal_width_mm(50.0, float(freq_ghz),
                                       "rogers4350b_h0.508"),
              "shunt_off_mm": shunt_off_mm,
              "r_series_mid_ohm": r_ser, "r_shunt_end_ohm": r_sh,
              "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "atten_pi", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [
            {"metric": "s21_db", "band": [freq_ghz * 0.95, freq_ghz * 1.05],
             "op": "mean_within",
             "value": [attenuation_db - 0.5, -attenuation_db + 0.5]
             if False else [-attenuation_db - 0.5, -attenuation_db + 0.5]},
            {"metric": "s11_db", "band": [freq_ghz * 0.95, freq_ghz * 1.05],
             "op": "max_below", "value": -20.0},
        ],
    }
    notes = [f"π 型 {attenuation_db}dB@{z0_ohm}Ω：串 {r_ser}Ω + "
             f"两端对地 {r_sh}Ω（E4 闭式）",
             "|S21| mean_within ±0.5dB 平坦语义（#195 统计量匹配）"]
    return ModelSynthesisResult(
        model="atten_pi",
        goal={"attenuation_db": attenuation_db, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_atten_t_model(
    attenuation_db: float = 10.0,
    z0_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    shunt_off_mm: float = 6.0,
) -> ModelSynthesisResult:
    """T 型衰减器综合（WP2.3 横向变体）：目标衰减 → 三电阻（E4 闭式）。

    电阻值=E4 attenuator_t 闭式（ABCD 校验）：两臂各串 r_series_arm、
    中点对地 r_shunt_mid。objectives 同 atten_pi（平坦均值+匹配门）。
    """
    from rfauto.core.calculators import attenuator_t

    res = attenuator_t(attenuation_db=attenuation_db, z0_ohm=z0_ohm)
    r_ser = res["r_series_arm_ohm"]
    r_mid = res["r_shunt_mid_ohm"]

    # w_mm 单源（XC-W）：随 freq_ghz 精算（缺省 2.5GHz 档逐位=旧字面量 1.1134）
    params = {"atten_db": attenuation_db,
              "w_mm": nominal_width_mm(50.0, float(freq_ghz),
                                       "rogers4350b_h0.508"),
              "shunt_off_mm": shunt_off_mm,
              "r_series_arm_ohm": r_ser, "r_shunt_mid_ohm": r_mid,
              "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "atten_t", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [
            {"metric": "s21_db", "band": [freq_ghz * 0.95, freq_ghz * 1.05],
             "op": "mean_within",
             "value": [-attenuation_db - 0.5, -attenuation_db + 0.5]},
            {"metric": "s11_db", "band": [freq_ghz * 0.95, freq_ghz * 1.05],
             "op": "max_below", "value": -20.0},
        ],
    }
    notes = [f"T 型 {attenuation_db}dB@{z0_ohm}Ω：两臂各串 {r_ser}Ω + "
             f"中点对地 {r_mid}Ω（E4 闭式）"]
    return ModelSynthesisResult(
        model="atten_t",
        goal={"attenuation_db": attenuation_db, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_ratrace_model(
    z0_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> ModelSynthesisResult:
    """rat-race 环形电桥综合（WP2.3）：环阻抗 √2·Z0 → 环宽与半径（闭式）。

    环阻抗 = √2·Z0（70.7Ω@50Ω，多来源确证），周长 = 1.5λg(环线)，
    R = 周长/(2π)。环线宽 inverse_width 精算（同 wilkinson 臂手法）。
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    z_ring = np.sqrt(2.0) * z0_ohm
    w_ring_mm, _, _ = inverse_width(z_ring, freq_ghz, stackup)
    _, er_eff_ring = forward_z0(w_ring_mm, freq_ghz, stackup)
    lam_g_mm = (299792458.0 / (freq_ghz * 1e9)) / np.sqrt(er_eff_ring) * 1e3
    circumference_mm = 1.5 * lam_g_mm
    r_ring_mm = circumference_mm / (2.0 * np.pi)

    params = {"w_ring_mm": round(w_ring_mm, 4),
              "r_ring_mm": round(r_ring_mm, 3), "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "ratrace", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [
            {"metric": "s21_db", "band": [freq_ghz * 0.95, freq_ghz * 1.05],
             "op": "mean_within", "value": [-3.5, -2.5]},
            {"metric": "s11_db", "band": [freq_ghz * 0.95, freq_ghz * 1.05],
             "op": "max_below", "value": -10.0},
        ],
    }
    notes = [f"环线宽 {w_ring_mm:.4f}mm（{z_ring:.2f}Ω，εeff={er_eff_ring:.4f}）",
             f"环半径 {r_ring_mm:.3f}mm（周长 1.5λg）"]
    return ModelSynthesisResult(
        model="ratrace", goal={"z0_ohm": z0_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_gysel_model(
    z0_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> ModelSynthesisResult:
    """Gysel 功分器综合（WP2.3 横向变体）：臂 √2·Z0、隔离线 Z0（闭式）。

    六节 λ/4 环（#206 理论核验轮，对照 Microwaves101 Gysel even/odd
    口径）：臂阻抗 = √2·Z0（偶模 Σ 结点匹配条件），隔离线/桥带阻抗 =
    Z0（奇模匹配条件 √(Z0·Zdelta)，负载 Zdelta=Z0）。各线宽 inverse_width
    精算，臂/隔离线长度各用自身 εeff 的 λ/4（两者 εeff 差 ~4.5%，不可
    混用同一长度）。几何为 L-jog 等长变体（P2⑪ 2026-09-16）：桥带跨度
    2·iso_len=λ/2 精确、隔离线竖直 YJ+横移 jog（派生量见 notes，不入
    参数表——参数仍为 4 键，schema/缓存零波及）。
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    z_arm = np.sqrt(2.0) * z0_ohm
    w_arm_mm, _, _ = inverse_width(z_arm, freq_ghz, stackup)
    _, er_eff_arm = forward_z0(w_arm_mm, freq_ghz, stackup)
    w_iso_mm, _, _ = inverse_width(float(z0_ohm), freq_ghz, stackup)
    _, er_eff_iso = forward_z0(w_iso_mm, freq_ghz, stackup)
    lam_g_arm_mm = (299792458.0 / (freq_ghz * 1e9)) / np.sqrt(er_eff_arm) * 1e3
    lam_g_iso_mm = (299792458.0 / (freq_ghz * 1e9)) / np.sqrt(er_eff_iso) * 1e3
    arm_len_mm = lam_g_arm_mm / 4.0
    iso_len_mm = lam_g_iso_mm / 4.0

    params = {"w_arm_mm": round(w_arm_mm, 4), "w_feed_mm": round(w_iso_mm, 4),
              "arm_len_mm": round(arm_len_mm, 3),
              "iso_len_mm": round(iso_len_mm, 3), "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "gysel", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [
            {"metric": "s21_db", "band": [freq_ghz * 0.95, freq_ghz * 1.05],
             "op": "mean_within", "value": [-3.5, -2.5]},
            {"metric": "s11_db", "band": [freq_ghz * 0.95, freq_ghz * 1.05],
             "op": "max_below", "value": -10.0},
        ],
    }
    # P2⑪ L-jog 等长拓扑派生量（不入参数表，渲染层 _gysel_layout 同式）：
    # 桥带跨度=2·iso_len（50Ω λ/2 精确）；隔离线=竖直 YJ+顶端横移 jog，
    # jog=|arm_len−iso_len|、YJ=iso_len−jog（竖直+横移=iso_len 保 λ/4）
    jog_mm = abs(round(arm_len_mm, 3) - round(iso_len_mm, 3))
    yj_mm = round(iso_len_mm, 3) - jog_mm
    notes = [f"臂线宽 {w_arm_mm:.4f}mm（{z_arm:.2f}Ω，εeff={er_eff_arm:.4f}，"
             f"λ/4={arm_len_mm:.3f}mm）",
             f"隔离线/桥带宽 {w_iso_mm:.4f}mm（{z0_ohm}Ω，"
             f"εeff={er_eff_iso:.4f}，λ/4={iso_len_mm:.3f}mm）",
             "负载 Zdelta=Z0=50Ω（LumpedElement 端接）；λ/2 桥带是隔离"
             "必要环节（#206 判废锚：无桥带 S21=-6.5dB）",
             f"L-jog 等长拓扑（P2⑪）：桥带跨度 2·iso_len="
             f"{2 * round(iso_len_mm, 3):.3f}mm=λ/2 精确；隔离线竖直段 YJ="
             f"{yj_mm:.3f}mm + 顶端横移 jog={jog_mm:.3f}mm（矩形旧版桥带 "
             f"2·arm_len={2 * round(arm_len_mm, 3):.3f}mm 的 "
             f"{(arm_len_mm / iso_len_mm - 1) * 100:+.2f}% 二阶偏差已消除）"]
    if not yj_mm > 0.0:
        notes.append(f"守卫：YJ={yj_mm:.3f}mm ≤0（arm_len≥2·iso_len），渲染层将拒绝")
    return ModelSynthesisResult(
        model="gysel", goal={"z0_ohm": z0_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_stripline_model(
    z0_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    line_len_mm: float = 40.0,
    er: float = 3.66,
    b_mm: float = 1.016,
) -> ModelSynthesisResult:
    """对称带状线综合（WP2.1 锚族）：目标 Z0 → 中心带宽度（闭式反解）。

    零厚度对称共形映射闭式（core/calculators._stripline_z0，K/K' 椭圆
    积分）。TEM 模：εeff=εr 精确。b=两地面间距（双 0.508 板压合
    b=1.016mm 口径）。
    """
    from scipy.optimize import brentq

    from rfauto.core.calculators import _stripline_z0

    w_mm = brentq(lambda w: _stripline_z0(w, b_mm, er) - z0_ohm,
                  1e-4, 5.0 * b_mm, xtol=1e-7)
    z_actual = _stripline_z0(w_mm, b_mm, er)

    params = {"w_mm": round(w_mm, 4), "line_len_mm": line_len_mm,
              "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "stripline", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [{"metric": "s11_db",
                        "band": [freq_ghz * 0.95, freq_ghz * 1.05],
                        "op": "max_below", "value": -15.0}],
    }
    notes = [f"w={w_mm:.4f}mm（目标 {z0_ohm}Ω，实际 {z_actual:.2f}Ω，"
             f"b={b_mm}mm TEM εeff={er}）", f"line_len={line_len_mm}mm"]
    return ModelSynthesisResult(
        model="stripline", goal={"z0_ohm": z0_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_cps_model(
    z0_ohm: float = 120.0,
    gap_mm: float = 0.5,
    freq_ghz: float = 2.5,
    line_len_mm: float = 40.0,
    er: float = 3.66,
    h_mm: float = 0.508,
) -> ModelSynthesisResult:
    """共面带（CPS，双带无地）综合（C9 传输线族 II）：目标 Z0 → 单带宽度。

    闭式=core/calculators._cps_ri（Wadell p.83 均匀线 120π·K/K' + Gupta/
    Ghione 部分电容 tanh 板映射 + FD 定标有效厚度 γ(εr)，refs §11.1；裁判
    core/quasistatic_fd.py 族内 ≤1.4%）。印制 CPS 天然高阻：rogers4350b h=0.508
    上 50Ω 需亚 0.1mm 缝不可制造（可达域下限 ≈94Ω@gap=0.5），标称档取 120Ω
    （100~120Ω 档口径；定标口径下 w=2.4863，TEMPLATE_NOMINAL 几何 2.95 按真机
    配对保持=116.2Ω）。Z0 随 w 单调递减；brentq 反解后回代自洽，gap 固定
    （越界显式报错）。
    """
    from rfauto.core.calculators import _cps_ri, cps_synthesis

    syn = cps_synthesis(z0_ohm, gap_mm, freq_ghz, er, h_mm)  # 越界即 ValueError
    w_mm = float(syn["w_mm"])
    eps_eff, z_actual = _cps_ri(w_mm, gap_mm, h_mm, er)

    params = {"w_mm": round(w_mm, 4), "gap_mm": gap_mm,
              "line_len_mm": line_len_mm, "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "cps", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [{"metric": "s11_db",
                        "band": [freq_ghz * 0.95, freq_ghz * 1.05],
                        "op": "max_below", "value": -15.0}],
    }
    notes = [f"w={w_mm:.4f}mm（目标 {z0_ohm}Ω CPS 无地口径，gap={gap_mm}mm，"
             f"实际 {z_actual:.2f}Ω，εeff={eps_eff:.4f}）",
             f"line_len={line_len_mm}mm",
             "端口=LumpedPort 差分直馈×2（R=闭式 Z0）；εeff 锚走 S21 解缠相位"
             "斜率（LumpedPort 无 β 属性）"]
    return ModelSynthesisResult(
        model="cps", goal={"z0_ohm": z0_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_suspended_stripline_model(
    z0_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    line_len_mm: float = 40.0,
    er: float = 3.66,
    b_mm: float = 1.016,
    h_mm: float = 0.508,
) -> ModelSynthesisResult:
    """悬置带线综合（C9 传输线族 II）：目标 Z0 → 中心带宽度（闭式反解）。

    几何口径：腔高 b（两地面间距），厚 h 基板以带为中面对称填充
    z∈[b/2−h/2, b/2+h/2]，两侧空气隙各 (b−h)/2。闭式=core/calculators.
    _suspended_stripline_ri（两支精确极限锚 h→0/h→b 回到 _stripline_z0，
    中间 h 共形电容比填充因子，refs §11）。b 固定为参数（recipe 可调，
    扰动域守卫 h≤b 由闭式显式报错）。
    """
    from rfauto.core.calculators import (
        _suspended_stripline_ri,
        suspended_stripline_synthesis,
    )

    syn = suspended_stripline_synthesis(z0_ohm, b_mm, h_mm, er)
    w_mm = float(syn["w_mm"])
    eps_eff, z_actual = _suspended_stripline_ri(w_mm, b_mm, h_mm, er)

    params = {"w_mm": round(w_mm, 4), "b_mm": b_mm,
              "line_len_mm": line_len_mm, "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "suspended_stripline", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [{"metric": "s11_db",
                        "band": [freq_ghz * 0.95, freq_ghz * 1.05],
                        "op": "max_below", "value": -15.0}],
    }
    notes = [f"w={w_mm:.4f}mm（目标 {z0_ohm}Ω，实际 {z_actual:.2f}Ω，"
             f"b={b_mm}mm h={h_mm}mm 对称填充 εeff={eps_eff:.4f}）",
             f"line_len={line_len_mm}mm",
             "端口=StripLinePort×2（height=b/2）；β 金标准可用"]
    return ModelSynthesisResult(
        model="suspended_stripline",
        goal={"z0_ohm": z0_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_msl_cpw_model(
    z0_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    line_len_mm: float = 40.0,
    trans_len_mm: float = 10.0,
    gap_cpw_mm: float = 0.2,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> ModelSynthesisResult:
    """MSL↔CPWG 过渡综合（WP2.5 Tier 2 首增量）。

    微带侧 inverse_width（HJ）、CPWG 侧 _cpwg_ri 共形映射闭式 brentq 反解
    （同 synthesize_cpw_model 口径），两段阻抗同目标（过渡=同阻异模对接，
    理想级联地板≈0——引擎偏差即渐变/地缘/过孔栅栏寄生）。锚判据=双端口
    β 金标准 + skrf 两段理想 TL 级联裁判（openems_templates 段首口径）。
    objectives 用保守文献地板 -10dB（无谐振 worst-case 语义，#195）。
    """
    from scipy.optimize import brentq

    from rfauto.core.calculators import _cpwg_ri

    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    w_msl_mm, z_msl_actual, _ = inverse_width(z0_ohm, freq_ghz, stackup)
    _, er_eff1 = forward_z0(w_msl_mm, freq_ghz, stackup)

    def z0_of(w_mm: float) -> float:
        return _cpwg_ri(w_mm, gap_cpw_mm, stackup.thickness_mm,
                        stackup.epsilon_r)[1]

    w_cpw_mm = brentq(lambda w: z0_of(w) - z0_ohm, 1e-4, 10.0, xtol=1e-7)
    er_eff2 = _cpwg_ri(w_cpw_mm, gap_cpw_mm, stackup.thickness_mm,
                       stackup.epsilon_r)[0]

    params = {"w_msl_mm": round(w_msl_mm, 4), "w_cpw_mm": round(w_cpw_mm, 4),
              "gap_cpw_mm": gap_cpw_mm, "line_len_mm": line_len_mm,
              "trans_len_mm": trans_len_mm, "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "msl_cpw", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.9, freq_ghz * 1.1],
                  "points": 201},
        "objectives": [{"metric": "s11_db",
                        "band": [freq_ghz * 0.95, freq_ghz * 1.05],
                        "op": "max_below", "value": -10.0}],
    }
    notes = [f"w_msl={w_msl_mm:.4f}mm（{z_msl_actual:.2f}Ω HJ，εeff="
             f"{er_eff1:.4f}）",
             f"w_cpw={w_cpw_mm:.4f}mm @gap{gap_cpw_mm}（{z0_ohm}Ω CPWG，"
             f"εeff={er_eff2:.4f}）",
             "过渡区居中阶梯渐变+接地过孔栅栏；理想级联地板≈0（同阻异模对接）"]
    return ModelSynthesisResult(
        model="msl_cpw",
        goal={"z0_ohm": z0_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_siw_model(
    f0_ghz: float = 10.0,
    d_mm: float = 0.6,
    s_mm: float = 1.0,
    line_len_mm: float | None = None,
    er: float = 3.66,
    h_mm: float = 0.508,
) -> ModelSynthesisResult:
    """直 SIW 线段综合（siw-family 首族，2026-09-22 立项）：f0 + 过孔 d/s →
    fc10 目标=f0/1.5 → 两过孔列心距 w（Cassivi 2002 等效宽度反解；
    runs/siw_family/criteria.md §1 双源/§2 设计点）。line_len 缺省=3λg@f0
    （β 闭式）；过孔设计规则（s≤2d、d<λ_sub/5）违规显式报错（越界不外推，
    #1c/#122）。h 只进损耗不进 fc10/β（Microwaves101 SIW 条目口径），
    params 带出供渲染/meta 同源。"""
    import math

    from rfauto.core.calculators import (
        siw_beta_rad_m,
        siw_effective_width_mm,
        siw_synthesis,
    )

    fc10_target = float(f0_ghz) / 1.5
    syn = siw_synthesis(fc10_target, er, d_mm, s_mm)  # 设计规则违规 ValueError
    w_mm = float(syn["w_mm"])
    weff = siw_effective_width_mm(w_mm, d_mm, s_mm)
    beta, fc_actual = siw_beta_rad_m(weff, er, f0_ghz)
    lam_g_mm = 2.0 * math.pi / beta * 1e3
    if line_len_mm is None:
        line_len_mm = round(3.0 * lam_g_mm, 4)

    params = {"w_mm": w_mm, "d_mm": d_mm, "s_mm": s_mm,
              "line_len_mm": line_len_mm, "h_mm": h_mm}
    recipe_draft = {
        "model": "siw", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [max(0.1, fc10_target * 1.08),
                                     min(fc10_target * 2.0, f0_ghz * 1.3)],
                  "points": 201},
        "objectives": [{"metric": "s11_db",
                        "band": [f0_ghz * 0.9, f0_ghz * 1.1],
                        "op": "max_below", "value": -10.0}],
    }
    notes = [f"w={w_mm:.4f}mm（fc10 目标 {fc10_target:.4f}GHz → w_eff="
             f"{weff:.4f}mm，回代 fc10={fc_actual:.4f}GHz）",
             f"β@{f0_ghz}GHz={beta:.3f} rad/m、λg={lam_g_mm:.4f}mm → "
             f"line_len=3λg={line_len_mm}mm",
             "端口=LumpedPort z 桥×2（R=Z_PV=2b·Z_TE/w_eff 闭式）；β/εeff "
             "锚走 S21 解缠相位斜率（LumpedPort 无 β 属性，cps 同契约）"]
    return ModelSynthesisResult(
        model="siw",
        goal={"f0_ghz": f0_ghz, "fc10_ghz": fc10_target,
              "d_mm": d_mm, "s_mm": s_mm},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_msl_siw_taper_model(
    f0_ghz: float = 10.0,
    d_mm: float = 0.6,
    s_mm: float = 1.0,
    taper_len_mm: float | None = None,
    siw_len_mm: float | None = None,
    er: float = 3.66,
    h_mm: float = 0.508,
) -> ModelSynthesisResult:
    """MSL 锥形过渡+SIW 直段综合（SIW 族第二成员，df6 A2 立项）：w 沿
    siw_synthesis（fc10 目标=f0/1.5 反解 Cassivi 式）；锥长缺省=λg/2@f0
    （runs/df6_a2siwmsl/criteria.md §1.1 对称双锥确定性级联实测：λg/4 在本
    阻抗比 50/Z_PV=2.19 下带内 |S11| max −7.8dB 达不到 RL>15dB 预声明门，
    如实收档，λg/4 只作旋钮变体）；siw_len 缺省=3λg（与 siw 族 line_len
    同链）。w50/w_end（锥两端宽）不进 params：Z_PV 闭式链带心相关，渲染/
    fake 通道按本次带心同参精算（#368 同参纪律，#1c 禁抄毫米数）。过孔设计
    规则违规显式报错（越界不外推，#1c/#122）。"""
    import math

    from rfauto.core.calculators import (
        siw_beta_rad_m,
        siw_effective_width_mm,
        siw_synthesis,
    )

    fc10_target = float(f0_ghz) / 1.5
    syn = siw_synthesis(fc10_target, er, d_mm, s_mm)  # 设计规则违规 ValueError
    w_mm = float(syn["w_mm"])
    weff = siw_effective_width_mm(w_mm, d_mm, s_mm)
    beta, fc_actual = siw_beta_rad_m(weff, er, f0_ghz)
    lam_g_mm = 2.0 * math.pi / beta * 1e3
    if taper_len_mm is None:
        taper_len_mm = round(lam_g_mm / 2.0, 4)
    if siw_len_mm is None:
        siw_len_mm = round(3.0 * lam_g_mm, 4)

    params = {"w_mm": w_mm, "d_mm": d_mm, "s_mm": s_mm,
              "taper_len_mm": taper_len_mm, "siw_len_mm": siw_len_mm,
              "h_mm": h_mm}
    recipe_draft = {
        "model": "msl_siw_taper", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [max(0.1, fc10_target * 1.08),
                                     min(fc10_target * 2.0, f0_ghz * 1.3)],
                  "points": 201},
        "objectives": [{"metric": "s11_db",
                        "band": [f0_ghz * 0.9, f0_ghz * 1.1],
                        "op": "max_below", "value": -15.0},
                       {"metric": "s21_db",
                        "band": [f0_ghz * 0.9, f0_ghz * 1.1],
                        "op": "min_above", "value": -1.5}],
    }
    notes = [f"w={w_mm:.4f}mm（fc10 目标 {fc10_target:.4f}GHz → w_eff="
             f"{weff:.4f}mm，回代 fc10={fc_actual:.4f}GHz）",
             f"β@{f0_ghz}GHz={beta:.3f} rad/m、λg={lam_g_mm:.4f}mm → "
             f"taper_len=λg/2={taper_len_mm}mm、siw_len=3λg={siw_len_mm}mm",
             "锥=50Ω MSL→Z_PV 阻抗变换器（w50/w_end=inverse_width 通道内"
             "精算）+锥末-SIW 台阶；端口=双 MSLPort 线基（ref=50 主口径）；"
             "预声明门 runs/df6_a2siwmsl/criteria.md §4"]
    return ModelSynthesisResult(
        model="msl_siw_taper",
        goal={"f0_ghz": f0_ghz, "fc10_ghz": fc10_target,
              "d_mm": d_mm, "s_mm": s_mm},
        params=params, recipe_draft=recipe_draft, notes=notes)


def synthesize_sma_launcher_model(
    z0_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    r_i_mm: float = 0.635,
    er_fill: float = 2.1,
    shell_thick_mm: float = 0.25,
    shell_len_mm: float = 5.0,
    line_len_mm: float = 40.0,
    pin_lay_mm: float = 2.0,
    port_len_mm: float = 0.2,
    tan_d_fill: float = 0.0,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> ModelSynthesisResult:
    """SMA 边缘弹射综合（WP2.5 Tier 2，2026-09-16 edge-launch 夹具口径）。

    同轴 TEM 精确闭式 Z0=(60/√εr)·ln(r_o/r_i) → r_o 反解（PTFE 填充
    εr=2.1 → εeff=εr）；外导体外径 r_os=r_o+壁厚为派生量（不进 params，
    渲染由 shell_t_mm 派生）；MSL 侧 inverse_width（HJ）。
    port1=同轴截面集总桥（LumpedPort 50Ω，针顶→壳内壁顶；CoaxialPort 真机
    判废：0.4mm 阶梯网格下差分 TL 探针分解失真，见 openems_templates WP2.5
    段），β 金标准只锚 port2（HJ）。|S11| 验收对照文献曲线（edge-launch SMA
    带内回损常规 15-20dB，objectives 保守地板 -10dB——方案行"验收靠文献曲线"
    口径，docs/rf_template_references.md SMA 节）。针径/填充越界显式报错
    （先验模型后校准，铁律 1b）。
    """
    if not (0.05 < r_i_mm < 3.0):
        raise ValueError(f"r_i_mm={r_i_mm} 超出同轴针径合理域 (0.05, 3.0)")
    if er_fill <= 1.0:
        raise ValueError(f"er_fill={er_fill} 必须 >1（空气填充用 1.0001+）")
    if shell_thick_mm <= 0.0:
        raise ValueError(f"shell_thick_mm={shell_thick_mm} 必须 >0")
    if tan_d_fill < 0.0:
        raise ValueError(f"tan_d_fill={tan_d_fill} 必须 ≥0（PTFE tanδ，0=无耗）")
    r_o_mm = (float(r_i_mm)
              * math.exp(z0_ohm * math.sqrt(er_fill) / 60.0))
    r_os_mm = r_o_mm + shell_thick_mm
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    w_msl_mm, z_msl_actual, _ = inverse_width(z0_ohm, freq_ghz, stackup)
    _, er_eff_msl = forward_z0(w_msl_mm, freq_ghz, stackup)

    params = {"w_msl_mm": round(w_msl_mm, 4), "r_i_mm": r_i_mm,
              "r_o_mm": round(r_o_mm, 4), "shell_t_mm": shell_thick_mm,
              "er_fill": er_fill, "shell_len_mm": shell_len_mm,
              "pin_lay_mm": pin_lay_mm, "line_len_mm": line_len_mm,
              "port_len_mm": port_len_mm, "tan_d_fill": tan_d_fill,
              "f0_ghz": freq_ghz}
    recipe_draft = {
        "model": "sma_launcher", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"freq_range_ghz": [freq_ghz * 0.7, freq_ghz * 1.3],
                  "points": 401},
        "objectives": [{"metric": "s11_db",
                        "band": [freq_ghz * 0.95, freq_ghz * 1.05],
                        "op": "max_below", "value": -10.0}],
    }
    notes = [f"r_o={r_o_mm:.4f}mm（{z0_ohm}Ω PTFE εr={er_fill} 同轴闭式，"
             f"r_os={r_os_mm:.4f} 派生=r_o+壁厚 {shell_thick_mm}）",
             f"w_msl={w_msl_mm:.4f}mm（{z_msl_actual:.2f}Ω HJ，εeff="
             f"{er_eff_msl:.4f}）",
             "edge-launch 文献曲线门：带内回损常规 15-20dB、保守地板 -10dB；"
             "β 金标准锚 port2（HJ）；port1 同轴截面集总桥无 β"]
    return ModelSynthesisResult(
        model="sma_launcher",
        goal={"z0_ohm": z0_ohm, "freq_ghz": freq_ghz},
        params=params, recipe_draft=recipe_draft, notes=notes)


# ─── C13 带通滤波器综合（耦合矩阵口径，广义切比雪夫 → N+2 CM）─────────────────

def _cm_nominal_label(a: int, b: int) -> str:
    """nominal 标签（显式无歧义口径）：单数字下标 m{a}{b}（m01/m12/m25…），
    两位数下标 m{a}_{b}（如 m1_10 = 节点 1–10 耦合）。

    旧口径 f"m{a}{b}" 在 N≥9（N+2≥11，下标 10 出现）时歧义：m110 无法
    区分 (1,10) 与 (11,0)。新规则保证标签 ↔ (a, b) 一一对应且可正则
    解析（两位数形如 "m" + a + "_" + b，单数字形如 "m" + a + b）；
    a<b 由生成序（a<b 全对枚举）保证，0=源、N+1=载。
    """
    a, b = int(a), int(b)
    if b >= 10:
        return f"m{a}_{b}"
    return f"m{a}{b}"


def synthesize_bpf_model(order: int, f0_ghz: float, fbw: float,
                         rl_db: float,
                         transmission_zeros_ghz: list | None = None,
                         topology: str = "folded",
                         sign_mode: str = "mainline_positive"
                         ) -> dict[str, Any]:
    """BPF 综合草稿（C13）：广义切比雪夫 → N+2 耦合矩阵 → 拓扑约简。

    闭式链路（core/calculators._gcheb_* / _cm_*）：
    - 广义切比雪夫滤波函数 F_N（cosh 和构造，带边 F_N(1)=1），
      ε = 1/√(10^(RL/10)−1)；全极点（无 TZ）或准椭圆（±ω_z 成对 TZ）；
    - F/P/E 多项式（E 取 Hurwitz 半边，场等价 f~²+p~²/ε²=|E(jΩ)|²）；
    - Cameron N+2 横向矩阵（Y 留数法闭式精确，stage-2；LM 幅频精化仅作
      数值病态兜底）；
    - 拓扑约简（复正交合同旋转 RMRᵀ，频响与原矩阵逐点一致 ≤1e−9；folded
      走经典 palindromic 序列，交叉耦合族 cross_family 按 TZ 计数规则
      自适应：anti=i+j=N+1（偶 N）/ shifted=i+j=N+2（奇 N 偶数 TZ）/ none）。

    返回 dict（失败 {"ok": False, "errors": [...]}）：
    {"ok", "order", "f0_ghz", "fbw", "rl_db", "topology", "method",
     "cross_family",
     "coupling_matrix": (N+2)×(N+2) 嵌套 [re,im] 列表（归一化耦合系数）,
     "external_q": [1.0, 1.0]（本项目归一化：谐振器斜率归一，外部耦合
     信息在 m0i/miL 内）, "nominal": 平铺参数（m_ij + qe；标签规则见
     _cm_nominal_label，两位数下标 m{a}_{b} 无歧义）,
     "nominal_index": {标签: [a, b]}（机器可读下标对照）,
     "s21_phase_flipped_vs_input", "sign_mode",
     "response_max_err", "pattern_residual"(folded，正常应为 0), "notes"}。

    sign_mode：符号归一口径（core/calculators._cm_sign_normalize）——
    mainline_positive（默认）主线全正但 S21 相位可能对横向矩阵翻 180°；
    preserve_s21_phase 只翻谐振器节点、S21 相位保持（末端 m_{N,L} 可负）。
    口径：transmission_zeros_ghz 为绝对频率（GHz），内部换算为归一化
    低通 |Ω_z| = |(f_z/f0 − f0/f_z)/fbw|（须 >1，即阻带内）。
    """
    errors: list[str] = []
    if order < 1:
        errors.append(f"order={order} 须 ≥1")
    if not 0 < fbw <= 1:
        errors.append(f"fbw={fbw} 须在 (0,1]")
    if rl_db <= 0:
        errors.append(f"rl_db={rl_db} 须 >0")
    if topology not in ("folded", "arrow"):
        errors.append(f"topology={topology} 须为 folded|arrow")
    if sign_mode not in ("mainline_positive", "preserve_s21_phase"):
        errors.append(f"sign_mode={sign_mode} 须为 mainline_positive|"
                      "preserve_s21_phase")
    tz_norm: list[float] = []
    for fz in transmission_zeros_ghz or []:
        if fz <= 0 or abs(fz - f0_ghz) < 1e-12:
            errors.append(f"TZ 频率 {fz} GHz 非法")
            continue
        omega_z = abs((fz / f0_ghz - f0_ghz / fz) / fbw)
        if omega_z <= 1.0:
            errors.append(f"TZ {fz} GHz 归一化 |Ω|={omega_z:.3f} 落在通带内")
        else:
            tz_norm.append(round(omega_z, 9))
    if order >= 1 and len(tz_norm) > order // 2:
        errors.append(f"TZ 对数 {len(tz_norm)} 超出阶数 {order} 允许数 "
                      f"{order // 2}")
    if errors:
        return {"ok": False, "errors": errors}

    from rfauto.core.calculators import (
        _cm_folded_family,
        _cm_polish,
        _cm_poly_max_err,
        _cm_reduce_arrow,
        _cm_reduce_folded,
        _cm_response_raw,
        _cm_s21_phase_flipped,
        _cm_transversal_exact,
        _gcheb_prototype,
        _poly_response,
    )

    proto = _gcheb_prototype(order, rl_db, tuple(tz_norm))
    try:
        mt = _cm_transversal_exact(order, proto)
        fit_res = _cm_poly_max_err(mt, proto)
        method = "cameron_residue"
        if fit_res > 1e-8:  # 数值病态兜底（不保 y11=y22 结构，仅极端情形）
            mt, res = _cm_polish(order, proto, mt,
                                 np.linspace(-0.99, 0.99,
                                             min(41, 8 * order + 9)))
            fit_res = float(np.max(np.abs(res.fun)))
            method = "cameron_residue+lm"
    except Exception as exc:  # pragma: no cover - 数值兜底
        return {"ok": False, "errors": [f"横向矩阵构造失败: {exc}"]}
    cross_family = "n/a"
    s21_flipped = False
    if topology == "arrow":
        mred = _cm_reduce_arrow(mt)
        pattern_residual = 0.0
        s21_flipped = _cm_s21_phase_flipped(mt, mred)
    else:
        mred, bad = _cm_reduce_folded(
            mt, preserve_s21_phase=(sign_mode == "preserve_s21_phase"))
        pattern_residual = float(max((v for _, _, v in bad), default=0.0))
        cross_family = _cm_folded_family(mred)
        s21_flipped = _cm_s21_phase_flipped(mt, mred)
    dense = np.linspace(-1.0, 1.0, 241)
    err = 0.0
    for w_ in dense:
        _, s21c = _cm_response_raw(mred, 1.0, 1.0, w_)
        _, s21p = _poly_response(proto, np.array([w_]))
        err = max(err, abs(abs(s21c) - abs(s21p[0])))
    if not (err < 1e-5):
        errors.append(f"拓扑约简后频响偏差 {err:.2e} 超限（应 <1e−5）")
        return {"ok": False, "errors": errors,
                "response_max_err": float(err)}

    n2 = order + 2
    cm_list = [[[round(v.real, 12), round(v.imag, 12)] for v in row]
               for row in mred]
    nominal: dict[str, Any] = {}
    nominal_index: dict[str, list[int]] = {}
    idx = [(a, b) for a in range(n2) for b in range(a + 1, n2)]
    for a, b in idx:
        val = mred[a, b]
        lab = _cm_nominal_label(a, b)
        nominal[lab] = (round(float(abs(val)), 6) if abs(val.imag) < 1e-9
                        else [round(float(val.real), 6),
                              round(float(val.imag), 6)])
        nominal_index[lab] = [a, b]
    nominal["qe_in"] = 1.0
    nominal["qe_out"] = 1.0
    notes = [
        f"广义切比雪夫 {order} 阶，RL={rl_db}dB，fbw={fbw}，f0={f0_ghz}GHz",
        f"TZ(归一化 |Ω|) = {tz_norm or '全极点（无穷远）'}",
        f"横向矩阵 {method}：闭式残差 {fit_res:.2e}，"
        f"约简后频响最大偏差 {err:.2e}",
        "nominal 标签口径：单数字下标 m{a}{b}，两位数下标 m{a}_{b}"
        "（N≥9 出现，如 m1_10 = 节点 1–10 耦合；节点序号见 nominal_index，"
        "0=源、N+1=载）",
    ]
    if topology == "folded":
        fam_desc = {"anti": "反对角 i+j=N+1", "shifted": "移位反对角 i+j=N+2"
                    "（奇数阶+偶数 TZ，如 N=5 的 2-5 四元组）",
                    "none": "无交叉耦合（全极点）"}.get(cross_family, cross_family)
        notes.append(f"folded 交叉耦合族 {cross_family}：{fam_desc}")
        if pattern_residual > 1e-9:
            notes.append(f"folded 模式残留 {pattern_residual:.2e}"
                         "（非横向输入或数值病态；频响等价不受影响）")
    return {"ok": bool(err < 5e-5), "order": order,
            "f0_ghz": f0_ghz, "fbw": fbw,
            "rl_db": rl_db, "topology": topology,
            "epsilon": round(float(proto["eps"]), 9),
            "transmission_zeros_norm": tz_norm,
            "coupling_matrix": cm_list,
            "matrix_shape": [n2, n2],
            "external_q": [1.0, 1.0],
            "nominal": nominal,
            "nominal_index": nominal_index,
            "sign_mode": sign_mode,
            "s21_phase_flipped_vs_input": bool(s21_flipped),
            "method": method,
            # 数值兜底可见性（审查 P2-5）：闭式残差超 1e-8 走 LM 精化
            # （method=cameron_residue+lm）时产物显式标 needs_calibration
            # （同本文件 inverse_width 惯例④"超限标记而非静默通过"）；
            # 纯闭式路径恒 False。零数值变化。
            "needs_calibration": method == "cameron_residue+lm",
            "cross_family": cross_family,
            "response_max_err": float(err),
            "pattern_residual": (round(pattern_residual, 12)
                                 if topology == "folded" else 0.0),
            "notes": notes}


# ─── hairpin（发夹线 BPF）综合链（WP2.3 收口 ⑦ 升格 core，2026-09-16）──────────────
# 自 adapters/openems_templates.py WP2.3 hairpin 段原样下沉（adapters 再导出、零改动
# 消费；#116 不留遮蔽副本）：C13 矩阵综合（本文件 synthesize_bpf_model，folded）
# → k/Q_e 映射（Hong §5.2/§5.3：k_{i,i+1}=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²）
# → 几何（core/coupled_microstrip：KJ 反解缝、抽头闭式 τ、λg/2 臂长）。数值只在内核。

_HAIRPIN_PARAM_KEYS: tuple[str, ...] = (
    "order", "w_mm", "arm_len_mm", "arm_gap_mm", "gap_mm", "tap_frac")


def _fmt_list(values: list[float], ndigits: int) -> str:
    """数值列表 → 紧凑字符串（notes 用；避免 % 格式化触发 UP031）。"""
    return "[" + ", ".join(f"{v:.{ndigits}f}" for v in values) + "]"


def hairpin_design_from_order(
    order: int, f0_ghz: float = 2.5, fbw: float = 0.05,
    rl_db: float = 20.0, *, er: float = 3.66, h_mm: float = 0.508,
    w_mm: float | None = None, arm_gap_mm: float = 3.0,
    kgap_corrected: bool = False,
) -> dict[str, Any]:
    """C13 综合 → hairpin 几何（确定性映射；矩阵综合在本文件，本函数只做映射）。

    k_{i,i+1}=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²)（Hong §5.2/§5.3），
    再经 KJ 反解得缝、经抽头闭式得 τ（口径见 adapters/openems_templates 文末
    WP2.3 hairpin 段）。
    order=1（单谐振器双抽头探针，B1 Q 标定）无耦合缝：k_list=[]、gaps_mm=[]、
    gap_mm=None（不再 IndexError）。arm_gap_mm 默认 3.0（2026-09-16 名义定版：
    k_self(3.0)=0.0115 < 互耦 k=0.0515 < k_self(1.0)=0.0602，U 内两臂缝须使同臂
    自耦远小于互耦，旧默认 1.0 反超是四轮 FAIL 的结构性根因，pt1 实证）。

    kgap_corrected=True（W4④，2026-09-17）：缝反解改用 hairpin 结构经验修正映射
    c(gap)·k_KJ(gap)=k（core/coupled_microstrip.hairpin_gap_mm_from_k structural_
    correction；域外/不可达如实 ValueError），并附 gaps_mm_kj（纯 KJ 反解）供对照。
    默认 False 保持名义链（HAIRPIN_NOMINAL 冻结口径）逐位不变。
    """
    from rfauto.core.coupled_microstrip import (
        hairpin_arm_len_mm,
        hairpin_gap_mm_from_k,
        hairpin_tap_frac_from_qe,
    )

    n = int(order)
    if n < 1:
        raise ValueError("hairpin 阶数须 ≥1")
    # w 单源（XC-W）：无耗裸层叠 50Ω 原值（不舍入；链内 gap/τ 反解继续用原值，
    # 标称档 4 位舍入由调用方做）——与旧裸 Stackup+inverse_width 逐位同值
    # （同参同函数，仅加进程内缓存），单测 hairpin 名义链逐位钉。
    w = (lossless_width_mm(50.0, float(f0_ghz), float(er), float(h_mm),
                           digits=None)
         if w_mm is None else float(w_mm))
    synth = synthesize_bpf_model(order=n, f0_ghz=float(f0_ghz),
                                 fbw=float(fbw), rl_db=float(rl_db),
                                 topology="folded")
    if not synth.get("ok"):
        raise ValueError(f"C13 综合失败: {synth.get('errors')}")
    arr = np.asarray(synth["coupling_matrix"], dtype=float)
    if arr.ndim == 3:                       # [re, im] 对（复元素）
        arr = np.hypot(arr[..., 0], arr[..., 1])
    ks = [float(fbw) * abs(arr[i, i + 1]) for i in range(1, n)]
    qe = 1.0 / (float(fbw) * abs(arr[0, 1]) ** 2)
    gaps_kj = [hairpin_gap_mm_from_k(k, w, f0_ghz, er, h_mm) for k in ks]
    gaps = ([hairpin_gap_mm_from_k(k, w, f0_ghz, er, h_mm,
                                   structural_correction=True) for k in ks]
            if kgap_corrected else gaps_kj)
    uniform = bool(gaps) and all(abs(gap - gaps[0]) < 1e-6 for gap in gaps)
    arm_len = hairpin_arm_len_mm(f0_ghz, w, er, h_mm)
    tau = hairpin_tap_frac_from_qe(qe)
    return {
        "order": n, "f0_ghz": float(f0_ghz), "fbw": float(fbw),
        "rl_db": float(rl_db), "er": float(er), "h_mm": float(h_mm),
        "w_mm": w, "arm_len_mm": arm_len, "arm_gap_mm": float(arm_gap_mm),
        "k_list": ks, "qe": qe,
        "gaps_mm": gaps, "gap_mm": (gaps[0] if uniform else None),
        "gaps_mm_kj": gaps_kj, "kgap_corrected": bool(kgap_corrected),
        "tap_frac": tau,
        "coupling_matrix": synth["coupling_matrix"],
        "notes": [
            f"C13 folded N={n}：k={_fmt_list(ks, 5)}，Q_e={qe:.4f}",
            (f"hairpin 结构修正 c(gap) 反解缝={_fmt_list(gaps, 4)} mm（纯 KJ "
             f"{_fmt_list(gaps_kj, 4)}；等缝={uniform}）" if kgap_corrected else
             f"KJ 反解缝={_fmt_list(gaps, 4)} mm（等缝={uniform}）"),
            f"抽头 τ={tau:.4f}（自开路端计；Q_e 闭式）",
            "口径见 openems_templates 文末 WP2.3 hairpin 段（#206 理论核验轮）",
        ],
    }


def synthesize_hairpin_model(
    order: int = 3, f0_ghz: float = 2.5, fbw: float = 0.05,
    rl_db: float = 20.0, **_: Any,
) -> ModelSynthesisResult:
    """hairpin spec 综合入口（原 models/template_specs._register_hairpin 闭包下沉）：
    C13→几何映射包装为 spec 合同的 ModelSynthesisResult——只做组装，零数值。
    order=1 时 gap_mm=None 不进 params（无耦合缝）。"""
    design = hairpin_design_from_order(order, f0_ghz, fbw, rl_db)
    params = {key: design[key] for key in _HAIRPIN_PARAM_KEYS
              if design[key] is not None}
    # 带边 |S11| 按定义触 −RL（ε² 口径），目标带内收 5% 防浮点 fence
    band = (f0_ghz * (1.0 - fbw * 0.475), f0_ghz * (1.0 + fbw * 0.475))
    recipe_draft = {
        "model": "hairpin_bpf",
        "recipe_version": 1,
        "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"solver": "openEMS",
                  "freq_range_ghz": [f0_ghz * 0.7, f0_ghz * 1.3],
                  "points": 401},
        "objectives": [
            {"metric": "s11_db", "band": [band[0], band[1]],
             "op": "max_below", "value": -rl_db},
        ],
    }
    return ModelSynthesisResult(
        model="hairpin_bpf",
        goal={"f0_ghz": f0_ghz, "fbw": fbw, "rl_db": rl_db,
              "order": int(order)},
        params=params,
        recipe_draft=recipe_draft,
        notes=list(design["notes"]),
    )


# ─── TF-5 多节 λ/4 变换器 + N-way Wilkinson 综合（round5 r5-插①，2026-09-26）─────────
# 纯闭式阻抗级内核（#7：数值只在确定性内核，无 SDK/网络依赖）。物理长度仅在显式给
# f0_ghz 时经 HJ 链（inverse_width+forward_z0）精算，不给则留 None——禁虚构 εeff（#1c）。
# 口径与出处（按名称引用，不虚构页号）：
# - binomial 多节：Pozar《Microwave Engineering》4ed「Binomial Multisection Matching
#   Transformer」节，一阶小反射表驱动：结点对数增量 ln(Z_{i+1}/Z_i)=ln(ZL/Z0)·C(N,i)/2^N
#   （i=0..N）。N=2 锚（教科书值，独立双路径验证）：50→100 → Z1=50·2^(1/4)=59.4604Ω、
#   Z2=50·2^(3/4)=84.0896Ω（=任务书钉的 Pozar 二节例值）。
# - chebyshev 多节：同书「Chebyshev Multisection Matching Transformer」节，一阶口径
#   |Γ(θ)|=Γm·|T_N(secθ0·cosθ)|，结点权重由 T_N(secθ0·cosθ) 的
#   余弦展开匹配 W(θ)=2Γ0cos(Nθ)+2Γ1cos((N-2)θ)+...（偶 N 末项 Γ_{N/2} 不带 2）；
#   T_N(secθ0)=Γδ/Γm 反解 secθ0=cosh(acosh(Γδ/Γm)/N)。N≤4 权重表内嵌（本函数），
#   N>4 属精确综合（Riblet/Ozaki-Ishii 数值迭代，TF-5 标注"可选"，未实现，显式拒绝）。
#   TF-5 规格写的"低通原型 g 值映射"按原型参照实现（chebyshev_lpf_g_values 内嵌表），
#   阻抗分布走 T_N 展开路径——两者同为 Chebyshev 变换器近似族，差异已如实登记。
# - N-way Wilkinson：星形口径 Pon 1961：N 支 λ/4 臂各 Z=√N·Z0（N 臂并联于输入结=Z0）、
#   N 支隔离电阻各 R=Z0 星形接各输出口与公共浮点节点（N=2 时两支 Z0 串联=经典 2·Z0，
#   与本文件 synthesize_wilkinson 的 70.7Ω 臂 + 100Ω 隔离电阻同解）；树形=既有 2-way
#   单元级联（每级 √2·Z0 臂 + R=2·Z0），仅 2^k 可用。两拓扑端口阻抗口径等价（均 Z0），
#   N>2 时臂/隔离电阻口径不同（docstring 与返回 notes 已注明）。

_C_MM_GHZ = 299.792458  # mm·GHz（与既有综合函数同口径）

# Chebyshev 等纹波 LPF 原型 g 值表（内嵌常量，N≤4；主源 MYJ《Matthaei-Young-Jones
# Microwave Filters...》Table 4.05-1 同源的教科书通行值，Pozar 4ed Ch.5 原型表同值）。
# 键=通带纹波（dB，教科书正值口径 0.1/0.5/1.0）；值={n: [g1..gN]}。
# 偶 N 的端接 g_{N+1}≠1，未内嵌（需回原文逐位核对后才可入表，#118 纪律）。
# 偶 N g4 修正（2026-10-05 W4-E 锚批 #118 双源钉抓出）：旧表三档 N=4 g4 均
# 误转录为 g2 镜像（1.3062/1.1926/1.0644），经 Pozar §8.4 递推式独立复算
# （core/matching.chebyshev_g_values 同式互证）+教科书通行值回核改为
# 0.8181/0.8419/0.7892；该表唯一消费点=prototype_reference 参照字段
# （synthesis:2145，结点权重走 _chebyshev_junction_weights 不经本表）——
# 修正零设计链数值影响。
_CHEBYSHEV_LPF_G_TABLE: dict[float, dict[int, tuple[float, ...]]] = {
    0.1: {
        1: (0.3052,),
        2: (0.8430, 0.6220),
        3: (1.0316, 1.1474, 1.0316),
        4: (1.1088, 1.3062, 1.7704, 0.8181),
    },
    0.5: {
        1: (0.3473,),
        2: (1.4029, 0.7071),
        3: (1.5963, 1.0967, 1.5963),
        4: (1.6703, 1.1926, 2.3662, 0.8419),
    },
    1.0: {
        1: (0.5088,),
        2: (1.8219, 0.6850),
        3: (2.0236, 0.9941, 2.0236),
        4: (2.0991, 1.0644, 2.8311, 0.7892),
    },
}
_CHEBYSHEV_G_TABLE_SOURCE = (
    "MYJ Table 4.05-1 同源教科书通行值（Pozar 4ed Ch.5 等纹波 LPF 原型表同值）；"
    "键=通带纹波 dB（正值口径）；偶 N 端接 g_{N+1} 未内嵌（#118：未双源核对"
    "不入表）；偶 N g4 转录错修正见上注（2026-10-05 W4-E 锚批双源钉）"
)


def _s11_db_to_passband_ripple_db(ripple_db: float) -> float:
    """本模块 |S11| 上限口径（负 dB）→ Chebyshev 通带纹波（正 dB）。

    精确定义式代数（非近似）：带内 |S11|²max=ε²/(1+ε²)、通带纹波=10·log10(1+ε²)
    ⇒ r = -10·log10(1 - 10^(RL/10))，RL 为负 dB 回波损耗口径。
    例：RL=-20dB → r=0.0436dB；RL=-9dB → r=0.584dB。
    """
    return -10.0 * math.log10(1.0 - 10.0 ** (ripple_db / 10.0))


def _validate_positive_z(value: Any, name: str) -> float:
    """正实数校验（显式拒收 bool，float(True)=1.0 会静默污染统计——df7+⑯）。"""
    if isinstance(value, bool) or not isinstance(
            value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{name} 须为正实数，got {value!r}")
    v = float(value)
    if not (math.isfinite(v) and v > 0.0):
        raise ValueError(f"{name} 须为正有限实数，got {v}")
    return v


def _validate_int_param(value: Any, name: str, minimum: int) -> int:
    """正整数校验（bool 是 int 子类，显式拒收；浮点显式拒收不静默截断）。"""
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} 须为整数（拒绝 bool/浮点），got {value!r}")
    v = int(value)
    if v < minimum:
        raise ValueError(f"{name} 须 ≥{minimum}，got {v}")
    return v


def _validate_ripple_db(ripple_db: float | None, *, required: bool) -> float:
    """ripple_db 校验：带内 |S11| 上限（负 dB，如 -20.0）；越界显式 ValueError。

    binomial 轮廓下仅作带宽估计电平（缺省 -20dB，不进阻抗分布）；chebyshev
    轮廓下是设计参数（必填）。
    """
    if ripple_db is None:
        if required:
            raise ValueError(
                "chebyshev 轮廓必须显式给 ripple_db（带内 |S11| 上限，负 dB，如 -20.0）")
        return -20.0
    if isinstance(ripple_db, bool) or not isinstance(
            ripple_db, (int, float, np.integer, np.floating)):
        raise ValueError(f"ripple_db 须为负 dB 数值，got {ripple_db!r}")
    v = float(ripple_db)
    if not (-60.0 <= v <= -0.05):
        raise ValueError(
            f"ripple_db 越界：须在 [-60.0, -0.05] dB（带内 |S11| 上限，负值），got {v}")
    return v


def chebyshev_lpf_g_values(n_sections: int, ripple_db: float) -> dict[str, Any]:
    """Chebyshev 等纹波 LPF 原型 g 值（表驱动，N≤4，纹波取最近内嵌档）。

    出处见 _CHEBYSHEV_G_TABLE_SOURCE。入参 ripple_db 口径=带内 |S11| 上限
    （负 dB，与本模块 synthesize_multisection_quarter_wave 一致），内部经精确
    定义式换算为通带纹波 dB（正值，教科书口径）后选最近档；正落在两档正中间时
    取纹波更深一档（确定性 tie-break）。
    """
    n = _validate_int_param(n_sections, "n_sections", minimum=1)
    if n > 4:
        raise ValueError(
            f"g 值表仅内嵌 N≤4（MYJ Table 4.05-1 同源），got N={n}；"
            "N>5 需回原文补表（#118：未核对不入表）")
    ripple = _validate_ripple_db(ripple_db, required=True)
    passband_ripple_db = _s11_db_to_passband_ripple_db(ripple)
    table_ripple = min(_CHEBYSHEV_LPF_G_TABLE,
                       key=lambda k: (abs(k - passband_ripple_db), -k))
    row = _CHEBYSHEV_LPF_G_TABLE[table_ripple]
    if n not in row:
        raise ValueError(f"g 值表缺 N={n}（内嵌档：{sorted(row)}）")
    return {
        "n_sections": n,
        "ripple_db_requested": ripple,
        "passband_ripple_db": round(passband_ripple_db, 6),
        "ripple_table_db": table_ripple,
        "g_values": list(row[n]),
        "g_termination": 1.0 if n % 2 == 1 else None,
        "source": _CHEBYSHEV_G_TABLE_SOURCE,
    }


def _chebyshev_junction_weights(n_sections: int, sec_theta0: float) -> list[float]:
    """T_N(secθ0·cosθ) 余弦展开 → 归一化结点权重（N≤4 内嵌表；N+1 个结点）。

    展开（T_N 恒等式，逐节手推并经响应判据独立验证）：
    N=1: T_1 = s·cosθ                                  → 权重 ∝ [s]
    N=2: T_2 = (s²-1) + s²·cos2θ                       → [s², 2(s²-1), s²]
    N=3: T_3 = s³·cos3θ + 3s(s²-1)·cosθ                → [s³, 3s(s²-1), 3s(s²-1), s³]
    N=4: T_4 = s⁴·cos4θ + 4s²(s²-1)·cos2θ + (3s⁴-4s²+1)
                                              → [s⁴, 4s²(s²-1), 2(3s⁴-4s²+1), 4s²(s²-1), s⁴]
    其中 s=secθ0；W(θ)=2Γ0cos(Nθ)+2Γ1cos((N-2)θ)+...+Γ_{N/2}（偶 N 末项不带 2），
    权重=结点 Γ_i 的相对大小（公共因子 Γm/2 已消去）。
    """
    s = sec_theta0
    if n_sections == 1:
        raw = [s]
    elif n_sections == 2:
        raw = [s ** 2, 2.0 * (s ** 2 - 1.0), s ** 2]
    elif n_sections == 3:
        raw = [s ** 3, 3.0 * s * (s ** 2 - 1.0), 3.0 * s * (s ** 2 - 1.0), s ** 3]
    elif n_sections == 4:
        raw = [s ** 4, 4.0 * s ** 2 * (s ** 2 - 1.0),
               2.0 * (3.0 * s ** 4 - 4.0 * s ** 2 + 1.0),
               4.0 * s ** 2 * (s ** 2 - 1.0), s ** 4]
    else:
        raise ValueError(  # 调用方已守卫，防御式保留（表驱动范围外显式拒绝）
            f"chebyshev 权重表仅内嵌 N≤4，got N={n_sections}")
    total = sum(raw)
    return [w / total for w in raw]


def synthesize_multisection_quarter_wave(
    z0: float,
    zl: float,
    n_sections: int,
    profile: str = "binomial",
    ripple_db: float | None = None,
    f0_ghz: float | None = None,
    *,
    stackup_name: str = "rogers4350b_h0.508",
    materials_path: str | Path | None = None,
) -> dict[str, Any]:
    """多节 λ/4 阻抗变换器综合（binomial / chebyshev 表驱动闭式）。

    闭式公式（一阶小反射表驱动，对数域结点增量累积）：
    - 结点对数增量 δ_i（i=0..N，共 N+1 个结点）：
        binomial: δ_i = ln(ZL/Z0)·C(N,i)/2^N（Pozar 4ed binomial 节，N=2 锚
          50→100 → 59.4604/84.0896Ω）
        chebyshev: δ_i ∝ T_N(secθ0·cosθ) 展开结点权重（见 _chebyshev_junction_weights），
          secθ0 = cosh(acosh(Γδ/Γm)/N)，Γδ=|ZL-Z0|/(ZL+Z0)、Γm=10^(ripple_db/20)
    - 节阻抗 Z_i = Z0·exp(ln(ZL/Z0)·Σ_{k<i}δ_k)（i=1..N；全精度不取整，供下游 HJ 反解）
    - 谱系恒等式（表构造保证）：Z_i·Z_{N+1-i}=Z0·ZL（对称）；N 奇时中节=√(Z0·ZL)；
      中心频率精确匹配（全节 λ/4 级联 ABCD |S11(f0)|≈0——binomial 全 N 与 chebyshev 奇 N；chebyshev 偶 N 中心为纹波峰 |S11(f0)|≈Γm，测试以内嵌 ABCD 闭式对照）
    - 带宽估计（一阶口径）：
        binomial: |Γ(θ)|=Γδ·cos^N(θ)，θ_m=arccos((Γm/Γδ)^(1/N))，
          FBW=2-4θ_m/π，f2/f1=(π-θ_m)/θ_m（ripple_db 仅作估计电平，缺省 -20dB）
        chebyshev: 等纹波带边 θ0：FBW=2-4θ0/π（ripple_db 为设计参数，必填）

    Args:
        z0: 输入端阻抗 (Ω)，正实数
        zl: 负载端阻抗 (Ω)，正实数（zl<z0 亦支持，节阻抗降序）
        n_sections: 节数 N ≥ 1（chebyshev 仅 N≤4：权重表驱动范围，N>4 需 Riblet
          数值迭代——TF-5 标注"可选"，未实现，显式 ValueError）
        profile: "binomial"（最平）| "chebyshev"（等纹波）
        ripple_db: 带内 |S11| 上限 (dB，负值，[-60, -0.05])。chebyshev 必填；
          binomial 仅作带宽估计电平（缺省 -20.0）
        f0_ghz: 中心频率 (GHz)。给了才精算每节线宽/εeff/物理 λ/4 长度（HJ 链）；
          缺省 None → 长度留 None（禁虚构 εeff，#1c）
        stackup_name: 层叠（materials.yaml 键，仅 f0_ghz 给出时用；既有家族同缺省）
        materials_path: materials.yaml 路径（透传 Stackup.from_materials_yaml）

    Returns:
        dict（键名风格与既有综合家族一致）:
        {
          "n_sections", "profile", "z0_ohm", "zl_ohm", "ripple_db",
          "gamma_delta", "gamma_m",
          "sections": [{"index", "z_ohm", "element", "width_mm", "epsilon_eff",
                        "length_mm", "status"}, ...],
          "weights": 结点对数增量权重（N+1 个，和=1，出处链 provenance）,
          "bandwidth_estimate": {"fbw", "f2_over_f1", "theta_edge_rad",
                                 "level_rl_db", "gamma_m", "gamma_delta", "formula"},
          "prototype_reference": chebyshev 时为 chebyshev_lpf_g_values(...) 结果，
                                 binomial 时为 None,
          "notes": [...]
        }
    """
    z0_v = _validate_positive_z(z0, "z0")
    zl_v = _validate_positive_z(zl, "zl")
    n = _validate_int_param(n_sections, "n_sections", minimum=1)
    prof = str(profile).lower()
    if prof not in ("binomial", "chebyshev"):
        raise ValueError(
            f"profile 须为 'binomial' | 'chebyshev'，got {profile!r}")
    ripple = _validate_ripple_db(ripple_db, required=(prof == "chebyshev"))

    gamma_delta = abs(zl_v - z0_v) / (zl_v + z0_v)
    gamma_m = 10.0 ** (ripple / 20.0)
    if gamma_m >= gamma_delta:
        raise ValueError(
            f"ripple 电平（|S11|≤{gamma_m:.4f}）不低于原始失配 Γδ={gamma_delta:.4f}"
            f"（ZL/Z0={zl_v / z0_v:.4f}）：无需/无法综合该变换器")

    ln_ratio = math.log(zl_v / z0_v)
    prototype_reference: dict[str, Any] | None = None
    if prof == "binomial":
        weights = [math.comb(n, i) / (2 ** n) for i in range(n + 1)]
        theta_edge = math.acos((gamma_m / gamma_delta) ** (1.0 / n))
        bw_formula = (
            "|Γ(θ)|=Γδ·cos^N(θ)（一阶小反射口径，Pozar 4ed Binomial Multisection "
            "Matching Transformer 节）；θ_m=arccos((Γm/Γδ)^(1/N))；FBW=2-4θ_m/π")
    else:
        if n > 4:
            raise ValueError(
                f"chebyshev 权重表仅内嵌 N≤4（表驱动范围），got N={n}；N>4 属精确综合"
                "（Riblet/Ozaki-Ishii 数值迭代，TF-5 标注可选，未实现）")
        sec_theta0 = math.cosh(math.acosh(gamma_delta / gamma_m) / n)
        theta_edge = math.acos(1.0 / sec_theta0)
        weights = _chebyshev_junction_weights(n, sec_theta0)
        prototype_reference = chebyshev_lpf_g_values(n, ripple)
        bw_formula = (
            "T_N(secθ0)=Γδ/Γm → secθ0=cosh(acosh(Γδ/Γm)/N)；带边 θ0=arccos(1/secθ0)；"
            "FBW=2-4θ0/π（Pozar 4ed Chebyshev Multisection Matching Transformer 节）")

    total_w = sum(weights)
    weights = [w / total_w for w in weights]

    sections: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        z_i = z0_v * math.exp(ln_ratio * sum(weights[:i]))
        sections.append({
            "index": i,
            "z_ohm": z_i,
            "element": f"λ/4 均匀传输线节（Z={z_i:.2f}Ω，节 {i}/{n}）",
            "width_mm": None,
            "epsilon_eff": None,
            "length_mm": None,
            "status": None,
        })

    notes: list[str] = [
        f"{prof} N={n}：{z0_v:.2f}→{zl_v:.2f}Ω，结点权重（N+1 个）="
        + "[" + ", ".join(f"{w:.6f}" for w in weights) + "]",
        "一阶小反射表驱动近似；精确值（Riblet 数值迭代/教科书精确表）未实现，如实标注",
    ]

    if f0_ghz is not None:
        f0 = _validate_positive_z(f0_ghz, "f0_ghz")
        stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
        for sec in sections:
            width_mm, _z_act, status = inverse_width(sec["z_ohm"], f0, stackup)
            _, er_eff = forward_z0(width_mm, f0, stackup)
            sec["width_mm"] = round(width_mm, 3)
            sec["epsilon_eff"] = round(er_eff, 4)
            sec["length_mm"] = round(_C_MM_GHZ / (4.0 * f0 * math.sqrt(er_eff)), 3)
            sec["status"] = status
        notes.append(
            f"物理长度按节 HJ 链精算（f0={f0}GHz，层叠 {stackup.name}；"
            "λ/4 = c/(4·f0·√εeff)，εeff 取自 inverse_width→forward_z0，不虚构）")
    else:
        notes.append(
            "未给 f0_ghz：width_mm/epsilon_eff/length_mm/status 留 None"
            "（εeff 禁虚构，#1c）；需物理尺寸时给 f0_ghz 走 HJ 链")

    fbw = 2.0 - 4.0 * theta_edge / math.pi
    return {
        "n_sections": n,
        "profile": prof,
        "z0_ohm": z0_v,
        "zl_ohm": zl_v,
        "ripple_db": ripple,
        "gamma_delta": gamma_delta,
        "gamma_m": gamma_m,
        "sections": sections,
        "weights": weights,
        "bandwidth_estimate": {
            "fbw": round(fbw, 6),
            "f2_over_f1": round((math.pi - theta_edge) / theta_edge, 6),
            "theta_edge_rad": round(theta_edge, 6),
            "level_rl_db": round(-20.0 * math.log10(gamma_m), 4),
            "gamma_m": gamma_m,
            "gamma_delta": gamma_delta,
            "formula": bw_formula,
        },
        "prototype_reference": prototype_reference,
        "notes": notes,
    }


def synthesize_nway_wilkinson(
    n: int,
    z0: float = 50.0,
    topology: str = "star",
) -> dict[str, Any]:
    """N-way Wilkinson 功分器阻抗级综合（star / tree 闭式）。

    闭式公式：
    - star（Pon 1961 星形）：N 支 λ/4 臂各 Z_arm=√N·Z0（N 臂并联于输入结=Z0 闭式
      匹配）；N 支隔离电阻各 R=Z0，星形接各输出口与公共浮点节点。N=2 退化为经典
      2-way（臂 √2·Z0=70.71Ω、两支 Z0 串联=隔离 2·Z0=100Ω），与本文件
      synthesize_wilkinson 的 series 臂/隔离电阻口径同解。
    - tree（树形）：仅 n=2^k；每级为既有 2-way 单元（臂 √2·Z0、隔离 R=2·Z0，与
      synthesize_wilkinson 同口径），共 k=log2(n) 级、2n-2 支臂、n-1 支隔离电阻。

    口径差异（star vs tree，消费方必读）：两拓扑端口阻抗口径等价（输入/各输出均 Z0），
    但 N>2 时臂阻抗与隔离电阻不同（star N=4：臂 2·Z0=100Ω + R=Z0×4；tree N=4：
    臂 √2·Z0=70.71Ω 两级 + R=2·Z0×3）。且 N≥3 星形隔离为经典近似（Pon 1961 口径，
    非理想两两隔离、随 N 退化）——需理想两两隔离用 tree。

    Args:
        n: 输出端口数，整数 ≥2（拒绝 bool/浮点）
        z0: 系统阻抗 (Ω)，正实数
        topology: "star" | "tree"（tree 要求 n=2^k，否则显式 ValueError）

    Returns:
        dict（与 synthesize_wilkinson 返回的 ModelSynthesisResult 字段同族契约：
        model/goal/params/recipe_draft/notes 五键；阻抗级设计，无 f0 不产线宽/臂长）:
        {
          "model": "nway_wilkinson_power_divider",
          "goal": {"n_way", "z0_ohm", "topology"},
          "params": {"n_way", "topology", "z0_ohm", "arm_z_ohm", "arm_count",
                     "isolation_r_ohm", "n_isolation_r", "input_z_ohm",
                     "output_z_ohm"[, "stages"]},
          "recipe_draft": 同族结构（阻抗级；setup 注明需 f0_ghz+层叠方可产物理尺寸）,
          "notes": [...]
        }
    """
    n_v = _validate_int_param(n, "n", minimum=2)
    z0_v = _validate_positive_z(z0, "z0")
    topo = str(topology).lower()
    if topo not in ("star", "tree"):
        raise ValueError(f"topology 须为 'star' | 'tree'，got {topology!r}")

    if topo == "star":
        arm_z = z0_v * math.sqrt(n_v)
        params: dict[str, Any] = {
            "n_way": n_v,
            "topology": "star",
            "z0_ohm": z0_v,
            "arm_z_ohm": round(arm_z, 4),
            "arm_count": n_v,
            "isolation_r_ohm": round(z0_v, 4),
            "n_isolation_r": n_v,
            "input_z_ohm": z0_v,
            "output_z_ohm": z0_v,
        }
        notes = [
            f"Pon 1961 星形：{n_v} 支 λ/4 臂各 √N·Z0={arm_z:.4f}Ω"
            f"（N 臂并联于输入结=Z0={z0_v:.4f}Ω 闭式匹配）",
            f"隔离：{n_v} 支 R=Z0={z0_v:.4f}Ω 星形接各输出口与公共浮点节点",
        ]
        if n_v == 2:
            notes.append(
                f"N=2 退化为经典 2-way：两支 Z0 串联=隔离 2·Z0={2 * z0_v:.4f}Ω，"
                "与 synthesize_wilkinson（70.7Ω 臂 + 100Ω 隔离）同解")
        else:
            notes.append(
                "N≥3 星形隔离为经典近似（Pon 1961 口径，非理想两两隔离、随 N 退化）；"
                "需理想两两隔离用 topology='tree'")
    else:
        if n_v & (n_v - 1) != 0:
            raise ValueError(
                f"tree 拓扑要求 n 为 2 的幂（2^k），got n={n_v}；任意 N 用 topology='star'")
        stages = n_v.bit_length() - 1
        arm_z = z0_v * math.sqrt(2.0)
        params = {
            "n_way": n_v,
            "topology": "tree",
            "z0_ohm": z0_v,
            "stages": stages,
            "arm_z_ohm": round(arm_z, 4),
            "arm_count": 2 * n_v - 2,
            "isolation_r_ohm": round(2.0 * z0_v, 4),
            "n_isolation_r": n_v - 1,
            "input_z_ohm": z0_v,
            "output_z_ohm": z0_v,
        }
        notes = [
            f"树形：{stages} 级既有 2-way 单元级联，每级臂 √2·Z0={arm_z:.4f}Ω、"
            f"隔离 R=2·Z0={2 * z0_v:.4f}Ω（与 synthesize_wilkinson 同口径）",
            f"共 {2 * n_v - 2} 支臂、{n_v - 1} 支隔离电阻；两两理想隔离由级联结构保证",
            "与 star 口径差异：端口阻抗等价（均 Z0），N>2 时臂/隔离电阻不同"
            "（如 N=4：star 臂 2·Z0 vs tree 臂 √2·Z0 两级）",
        ]

    recipe_draft = {
        "model": "nway_wilkinson_power_divider",
        "recipe_version": 1,
        "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {
            "requires_f0_ghz": True,
            "note": "阻抗级闭式设计；λ/4 臂长与线宽需 f0_ghz+层叠经 HJ 链"
                    "（inverse_width/forward_z0/synthesize_mline）精算",
        },
        "objectives": [],
    }
    return {
        "model": "nway_wilkinson_power_divider",
        "goal": {"n_way": n_v, "z0_ohm": z0_v, "topology": topo},
        "params": params,
        "recipe_draft": recipe_draft,
        "notes": notes,
    }


# ─── QW-10 Schiffman 移相器（耦合段闭式综合，2026-09-26）─────────────────────

_SCHIFFMAN_C0_M_S = 299792458.0  # 真空光速 m/s（与 C_MM_GHZ 同源换算）


def _schiffman_invert_geometry(
    z0e: float, z0o: float, er: float, h_mm: float, f0_ghz: float,
) -> tuple[float, float, float, float]:
    """(Z0e, Z0o) → (w_mm, s_mm, εeff_even, εeff_odd)：KJ 准静态面嵌套反演。

    联动既有耦合线 HJ/KJ 分析面（core/coupled_microstrip.
    coupled_microstrip_even_odd_ohm，Kirschning-Jansen 1984 准静态闭式）：
    - 内层：固定 w，s ↦ Z0e(w,s) 单调（缝越小耦合越紧、Z0e 越高）→ brentq 解 s；
    - 外层：w ↦ Z0o(w, s*(w)) 扫描括号 → brentq 解 w（物理上 w 越宽阻抗越低）；
    - 反解后回代自洽断言（相对误差 ≤1e-9，与 inverse_width 同纪律）。

    Returns:
        (w_mm, s_mm, eps_eff_even, eps_eff_odd)。

    Raises:
        ValueError: (Z0e, Z0o) 组合在 KJ 零厚无盖口径可达域外（不外推）。
    """
    from scipy.optimize import brentq

    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    def z_pair(w: float, s: float) -> tuple[float, float]:
        z_e, z_o, _, _ = coupled_microstrip_even_odd_ohm(
            w, s, f0_ghz, er=er, h_mm=h_mm)
        return z_e, z_o

    def outer_residual(w: float) -> float | None:
        s_lo, s_hi = 1e-4 * h_mm, 100.0 * h_mm
        try:
            z_e_lo, _ = z_pair(w, s_lo)
            z_e_hi, _ = z_pair(w, s_hi)
        except (ValueError, OverflowError, ZeroDivisionError):
            return None
        # Z0e 随 s 增大而减小：目标须落在 (Z0e(s_hi), Z0e(s_lo)) 内才可达
        if not (z_e_hi < z0e < z_e_lo):
            return None
        s_star = brentq(
            lambda s: z_pair(w, s)[0] - z0e, s_lo, s_hi, xtol=1e-10 * h_mm)
        return z_pair(w, s_star)[1] - z0o

    w_grid = np.geomspace(1e-3 * h_mm, 50.0 * h_mm, 321)
    residuals = [outer_residual(w) for w in w_grid]
    bracket = None
    for i in range(len(w_grid) - 1):
        r0, r1 = residuals[i], residuals[i + 1]
        if r0 is None or r1 is None or r0 == 0.0:
            continue
        if r0 * r1 < 0.0:
            bracket = (w_grid[i], w_grid[i + 1], r0, r1)
            break
    if bracket is None:
        raise ValueError(
            f"(Z0e={z0e}Ω, Z0o={z0o}Ω)@h={h_mm}mm/εr={er} 在 KJ 零厚口径"
            "耦合微带可达域外（几何反解不可达，不外推）")
    w0, w1, r0, _r1 = bracket
    w_star = brentq(lambda w: outer_residual(w), w0, w1, xtol=1e-10 * h_mm)
    s_lo2, s_hi2 = 1e-4 * h_mm, 100.0 * h_mm
    s_star = brentq(
        lambda s: z_pair(w_star, s)[0] - z0e, s_lo2, s_hi2, xtol=1e-10 * h_mm)
    z_e_chk, z_o_chk, eps_e, eps_o = coupled_microstrip_even_odd_ohm(
        w_star, s_star, f0_ghz, er=er, h_mm=h_mm)
    if (abs(z_e_chk - z0e) > 1e-6 * z0e or abs(z_o_chk - z0o) > 1e-6 * z0o):
        raise ValueError(
            f"几何反解回代不自洽：Z0e {z_e_chk:.6f} vs {z0e}、"
            f"Z0o {z_o_chk:.6f} vs {z0o}")
    return float(w_star), float(s_star), float(eps_e), float(eps_o)


def _schiffman_section_insertion_rad(
    f_hz: np.ndarray, l_coupled_m: float, z0e: float, z0o: float,
    eps_e: float, eps_o: float, z0_ohm: float,
) -> np.ndarray:
    """Schiffman 耦合段（平行耦合 U 形全通段，远端桥接）连续插入相位 rad。

    模型（准静态、εeff 逐模常数化，不含色散）：
    - 远端桥接边界 ⟹ 偶模远端开路、奇模远端短路；两端口（两带条近端对地）
      导纳矩阵合成 2×2 网络，S21 = −j(a+b)/(1+ab+j(a−b))，
      a=(Z0/Z0e)·tanθ_e、b=(Z0/Z0o)/tanθ_o，θ_m = 2πf√εeff_m·L/c；
    - 均匀介质极限（εeff_e=εeff_o、Z0e·Z0o=Z0²）退化为 Schiffman 1958
      经典式 φ_c = arccos[(ρ−tan²θ)/(ρ+tan²θ)]（ρ=Z0e/Z0o，IRE Trans.
      MTT-6(2) 1958），单测以该极限锚定；
    - 插入相位 = −angle(S21)，经低频锚梯解缠取连续支（f→0 时插入相位→0）。
    """
    omega = 2.0 * np.pi * f_hz
    theta_e = omega * np.sqrt(eps_e) * l_coupled_m / _SCHIFFMAN_C0_M_S
    theta_o = omega * np.sqrt(eps_o) * l_coupled_m / _SCHIFFMAN_C0_M_S
    a = (z0_ohm / z0e) * np.tan(theta_e)
    b = (z0_ohm / z0o) / np.tan(theta_o)
    s21 = -1j * (a + b) / (1.0 + a * b + 1j * (a - b))
    if not bool(np.all(np.isfinite(s21))):
        raise ValueError(
            "Schiffman 耦合段 S21 出现非有限值（频率轴数值溢出/含非法值）")
    return -np.unwrap(np.angle(s21))


def _schiffman_eps_or_invert(
    z0e: float, z0o: float, er: float, h_m: float, f0_ghz: float,
    eps_eff_even: float | None, eps_eff_odd: float | None,
) -> tuple[float, float, float | None, float | None]:
    """εeff 对解析：显式常数旁路（均匀介质口径/测试锚用）或 KJ 反演联动。

    eps_eff_even/eps_eff_odd 须成对给出（只给一个显式报错）；缺省走
    (Z0e, Z0o)→(w,s) 几何反解并取 KJ 准静态 εeff 对。返回
    (eps_e, eps_o, w_mm, s_mm)，几何旁路时 w/s 为 None（如实 None 不虚构）。
    """
    if (eps_eff_even is None) != (eps_eff_odd is None):
        raise ValueError(
            "eps_eff_even/eps_eff_odd 须成对给出（显式常数化旁路）")
    if eps_eff_even is not None:
        eps_e = _validate_positive_z(eps_eff_even, "eps_eff_even")
        eps_o = _validate_positive_z(eps_eff_odd, "eps_eff_odd")
        if eps_e < eps_o:
            raise ValueError(
                "偶模 εeff 应不低于奇模（εeff_even ≥ εeff_odd，微带物理序；"
                "相等=均匀介质口径，显式声明后合法）")
        return eps_e, eps_o, None, None
    w_mm, s_mm, eps_e, eps_o = _schiffman_invert_geometry(
        z0e, z0o, er, h_m * 1e3, f0_ghz)
    return eps_e, eps_o, w_mm, s_mm


def schiffman_delta_phase(
    f_ghz: Any,
    l_coupled_m: float,
    z0e: float,
    z0o: float,
    er: float,
    h_m: float,
    *,
    z0_ohm: float = 50.0,
    l_reference_m: float | None = None,
    eps_eff_even: float | None = None,
    eps_eff_odd: float | None = None,
) -> np.ndarray:
    """Schiffman 移相器差分相移频扫 Δφ(f)（度）＝参考段相位−耦合段相位。

    器件=耦合段（长 L，远端桥接的平行耦合 U 形全通段）+ 参考直通段
    （长 L_ref，缺省 3L——Schiffman 1958 惯例）：Δφ(f) = β_ref·L_ref − Φ_c(f)。

    v1 闭式口径（显式声明）：
    - 准静态 εeff 逐模常数化（εeff_even/εeff_odd 不含色散）；缺省由
      (Z0e, Z0o) 经 KJ 面几何反解联动取得（h_m 必填——εeff 无基板厚度
      不可定，不做无厚度虚构近似），或成对显式旁路；
    - 参考段 εeff 取偶/奇模相速平均口径 ((√εeff_e+√εeff_o)/2)²（同宽
      直通线近似；严格设计应按 50Ω 独立布线宽度取 HJ εeff，留后续）。

    Args:
        f_ghz: 频率（标量或一维数组，GHz，全部 >0；乱序自动还原输出序）。
        l_coupled_m: 耦合段物理长度（m，>0）。
        z0e/z0o: 偶/奇模阻抗（Ω，Z0e > Z0o >0）。
        er: 基板相对介电常数（>1）。
        h_m: 基板厚度（m，>0）。
        z0_ohm: 系统阻抗（Ω，>0；全通匹配条件 Z0e·Z0o=Z0² 由设计侧保证）。
        l_reference_m: 参考段长度（m）；None 取 3·L（Schiffman 惯例）。
        eps_eff_even/eps_eff_odd: 显式 εeff 常数旁路（成对；缺省走反演）。

    Returns:
        np.ndarray（度，与 f_ghz 同形）：Δφ(f) = Φ_ref(f) − Φ_c(f)，
        经典设计（θ0=90°、L_ref=3L）在 f0 处 = +90°。

    Raises:
        ValueError: 频率 ≤0/非有限、参数越界、εeff 旁路不成对、
            S21 数值溢出等（显式拒绝，不静默）。
    """
    f_arr = np.atleast_1d(np.asarray(f_ghz, dtype=float))
    if f_arr.ndim != 1 or f_arr.size == 0:
        raise ValueError("f_ghz 须为非空标量或一维数组")
    if not bool(np.all(np.isfinite(f_arr))) or bool(np.any(f_arr <= 0.0)):
        raise ValueError("f_ghz 须全部为有限正数（f=0 显式拒绝）")
    l_c = _validate_positive_z(l_coupled_m, "l_coupled_m")
    z_e = _validate_positive_z(z0e, "z0e")
    z_o = _validate_positive_z(z0o, "z0o")
    if z_e <= z_o:
        raise ValueError("Z0e 须大于 Z0o（耦合线偶/奇模阻抗物理序）")
    if not (isinstance(er, (int, float)) and not isinstance(er, bool)
            and math.isfinite(float(er)) and float(er) > 1.0):
        raise ValueError(f"er 须为 >1 的有限数，got {er!r}")
    h_v = _validate_positive_z(h_m, "h_m")
    z0_v = _validate_positive_z(z0_ohm, "z0_ohm")
    l_ref = (3.0 * l_c if l_reference_m is None
             else _validate_positive_z(l_reference_m, "l_reference_m"))
    eps_e, eps_o, _, _ = _schiffman_eps_or_invert(
        z_e, z_o, float(er), h_v, float(np.max(f_arr)),
        eps_eff_even, eps_eff_odd)
    eps_ref = ((math.sqrt(eps_e) + math.sqrt(eps_o)) / 2.0) ** 2

    order = np.argsort(f_arr)
    f_sorted = f_arr[order]
    f_hz_sorted = f_sorted * 1e9  # GHz → Hz（内核相位链一律 Hz）
    f_min = float(f_hz_sorted[0])
    # 低频锚梯：geomspace 至 f_min·1e-3（该处插入相位→0），定解缠连续支
    ladder = np.geomspace(f_min * 1e-3, f_min, 129)
    f_full = np.concatenate([ladder, f_hz_sorted[1:]])
    insertion = _schiffman_section_insertion_rad(
        f_full, l_c, z_e, z_o, eps_e, eps_o, z0_v)
    delta_sorted = (2.0 * np.pi * f_hz_sorted * math.sqrt(eps_ref) * l_ref
                    / _SCHIFFMAN_C0_M_S) - insertion[128:]
    out = np.empty_like(delta_sorted)
    out[order] = np.degrees(delta_sorted)
    return out


def synthesize_schiffman(
    z0e: float,
    z0o: float,
    er: float,
    h_m: float,
    f0_ghz: float,
    delta_phase_deg: float = 90.0,
    coupling_length_ratio: float = 1.0,
    *,
    z0_ohm: float = 50.0,
    bw_frac: float = 0.25,
    n_band_points: int = 81,
) -> dict[str, Any]:
    """Schiffman 90° 定差移相器闭式综合：给 (Z0e, Z0o) 解耦合段/参考段长度。

    模型：耦合段=平行耦合 U 形全通段（远端桥接，Schiffman 1958 口径），
    参考直通段缺省 3L 惯例。耦合段长度取耦合长度比语义：f0 处偶/奇模
    平均电长度 θ0 = coupling_length_ratio·90°（1.0 = 经典 λ/4 耦合段）；
    参考段长度按目标差分相移闭式解出（Δφ 对 L_ref 线性，一步精确反解）：
        L_ref = (Φ_c(f0) + δ_rad)/β_ref(f0)。

    v1 闭式口径（显式声明，见 schiffman_delta_phase 同源注释）：
    - 准静态 εeff 逐模常数化（KJ 反演联动，不含色散）；
    - 参考段 εeff 取模平均相速口径；近场/色散/宽度渐变修正不做。

    Returns:
        dict（JSON 可序列化）：
        {
          "model": "schiffman_phase_shifter",
          "coupled_length_m", "reference_length_m": float（m）,
          "delta_phase_at_f0_deg": 正算回代值（与目标一致至浮点噪声）,
          "phase_flatness": {带宽窗 1±bw_frac 内 Δφ 偏差分析},
          "geometry_mm": {"w_mm", "s_mm"}（KJ 反演几何，联动 HJ/KJ 面）,
          "eps_eff": {"even", "odd", "reference"},
          "notes": [口径声明列表]
        }

    Raises:
        ValueError: 参数越界/bool、(Z0e,Z0o) 可达域外（不外推）、
            coupling_length_ratio 越域（(0, 2]）。
    """
    z_e = _validate_positive_z(z0e, "z0e")
    z_o = _validate_positive_z(z0o, "z0o")
    if z_e <= z_o:
        raise ValueError("Z0e 须大于 Z0o（耦合线偶/奇模阻抗物理序）")
    if not (isinstance(er, (int, float)) and not isinstance(er, bool)
            and math.isfinite(float(er)) and float(er) > 1.0):
        raise ValueError(f"er 须为 >1 的有限数，got {er!r}")
    h_v = _validate_positive_z(h_m, "h_m")
    f0_v = _validate_positive_z(f0_ghz, "f0_ghz")
    if isinstance(delta_phase_deg, bool) or not isinstance(
            delta_phase_deg, (int, float, np.integer, np.floating)):
        raise ValueError(f"delta_phase_deg 须为数值（拒绝 bool），got {delta_phase_deg!r}")
    delta_v = float(delta_phase_deg)
    if not math.isfinite(delta_v) or delta_v == 0.0:
        raise ValueError("delta_phase_deg 须为非零有限数")
    ratio_v = _validate_positive_z(coupling_length_ratio, "coupling_length_ratio")
    if ratio_v > 2.0:
        raise ValueError(
            f"coupling_length_ratio 须在 (0, 2]（θ0=ratio·90°，越域不外推），got {ratio_v}")
    z0_v = _validate_positive_z(z0_ohm, "z0_ohm")
    bw_v = _validate_positive_z(bw_frac, "bw_frac")
    if bw_v > 0.9:
        raise ValueError(f"bw_frac 须 ≤0.9（带宽窗 1±bw_frac），got {bw_v}")
    n_pts = _validate_int_param(n_band_points, "n_band_points", minimum=5)

    w_mm, s_mm, eps_e, eps_o = _schiffman_invert_geometry(
        z_e, z_o, float(er), h_v * 1e3, f0_v)
    eps_ref = ((math.sqrt(eps_e) + math.sqrt(eps_o)) / 2.0) ** 2

    # 耦合段长度：θ0 = ratio·90°（偶/奇模平均电长度口径）
    beta_sum = (2.0 * math.pi * f0_v * 1e9
                * (math.sqrt(eps_e) + math.sqrt(eps_o)) / _SCHIFFMAN_C0_M_S)
    l_coupled = ratio_v * math.pi / beta_sum
    # 耦合段在 f0 的插入相位（低频锚梯解缠；与 schiffman_delta_phase 同链）
    f_ladder = np.geomspace(f0_v * 1e9 * 1e-4, f0_v * 1e9, 257)
    phi_c_f0 = float(_schiffman_section_insertion_rad(
        f_ladder, l_coupled, z_e, z_o, eps_e, eps_o, z0_v)[-1])
    # Δφ = β_ref·L_ref − Φ_c 对 L_ref 线性 → 一步精确反解
    beta_ref = (2.0 * math.pi * f0_v * 1e9
                * math.sqrt(eps_ref) / _SCHIFFMAN_C0_M_S)
    l_reference = (phi_c_f0 + math.radians(delta_v)) / beta_ref

    # 带宽窗平坦度分析（1±bw_frac）
    f_band = np.linspace(f0_v * (1.0 - bw_v), f0_v * (1.0 + bw_v), n_pts)
    delta_band = schiffman_delta_phase(
        f_band, l_coupled, z_e, z_o, float(er), h_v, z0_ohm=z0_v,
        l_reference_m=l_reference)
    dev = delta_band - delta_v
    max_dev = float(np.max(np.abs(dev)))

    notes = [
        "准静态 εeff 逐模常数化口径（KJ 反演联动，不含色散；色散修正留后续）",
        "参考段 εeff 取偶/奇模相速平均 ((√εeff_e+√εeff_o)/2)²（同宽直通线近似）",
        f"参考段长度闭式解出 L_ref={l_reference * 1e3:.6f} mm"
        f"（Schiffman 惯例 3L={3.0 * l_coupled * 1e3:.6f} mm 作参照）",
        "耦合段=远端桥接平行耦合全通段；均匀介质极限下 φ_c=arccos[(ρ−tan²θ)/(ρ+tan²θ)]"
        "（Schiffman 1958），λ/4→λ/2 锚点处 L 翻倍⟹Δφ 翻倍（180°→360°）",
    ]
    return {
        "model": "schiffman_phase_shifter",
        "coupled_length_m": round(l_coupled, 12),
        "reference_length_m": round(l_reference, 12),
        "delta_phase_at_f0_deg": round(
            float(schiffman_delta_phase(
                np.array([f0_v]), l_coupled, z_e, z_o, float(er), h_v,
                z0_ohm=z0_v, l_reference_m=l_reference)[0]), 9),
        "phase_flatness": {
            "band_frac": bw_v,
            "band_ghz": [round(float(f_band[0]), 9), round(float(f_band[-1]), 9)],
            "n_points": n_pts,
            "delta_phase_min_deg": round(float(np.min(delta_band)), 9),
            "delta_phase_max_deg": round(float(np.max(delta_band)), 9),
            "max_abs_deviation_deg": round(max_dev, 9),
            "max_abs_deviation_frac": round(max_dev / abs(delta_v), 9),
        },
        "geometry_mm": {"w_mm": round(w_mm, 9), "s_mm": round(s_mm, 9)},
        "eps_eff": {"even": round(eps_e, 9), "odd": round(eps_o, 9),
                    "reference": round(eps_ref, 9)},
        "z0_ohm": z0_v,
        "coupling_length_ratio": ratio_v,
        "notes": notes,
    }
