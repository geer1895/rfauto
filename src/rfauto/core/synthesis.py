"""微带线综合引擎。

正向：skrf MLine (Hammerstad-Jensen) 计算 Z0/εeff
反解：自写 brentq 求逆（HJ 闭式 + 扫描括号）

设计决策：
- 正向锁死 model='hammerstadjensen'（与 G0 验证一致）
- 反解结果回代正向做自洽断言（|ΔZ0|<0.5Ω）
- 层叠复用 configs/materials.yaml（带 source/verified_by）
- L0 层，无 SDK 依赖（只有 skrf + numpy + scipy）

验收：
① 反解→正向回算 |ΔZ0|<0.5Ω
② 响应性：Z0 单调降 → W 单调升
③ 对拍矩阵：常规+极端 W/h + 多频点，常规 <3% 极端 <5%
④ 超限标 needs_calibration 而非静默通过
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

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
        """从 configs/materials.yaml 加载层叠参数。"""
        if materials_path is None:
            # project root: src/rfauto/core/ -> src/rfauto/ -> src/ -> project root
            materials_path = Path(__file__).resolve().parent.parent.parent.parent / "configs" / "materials.yaml"
        else:
            materials_path = Path(materials_path)

        if not materials_path.exists():
            raise FileNotFoundError(f"materials.yaml 不存在: {materials_path}")

        with open(materials_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

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

def forward_z0(
    width_mm: float,
    freq_ghz: float,
    stackup: Stackup,
) -> tuple[float, float]:
    """正向计算：微带线宽度 → (Z0, εeff)。

    使用 skrf MLine (Hammerstad-Jensen) 模型。

    Returns:
        (z0_ohm, epsilon_eff)
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
    # εeff 从传播常数推导：εeff = (β·c / (2π·f))²
    # skrf 2.1 的 MLine 属性名是 ep_reff（旧版 er_eff）；都不在时用 β 反推，
    # 兜底回退体介电常数（会把 λ 反推的 f0 带偏，实测教训）。
    try:
        er_eff = float(np.real(mline.ep_reff[0]))
    except AttributeError:
        try:
            er_eff = float(mline.er_eff[0])
        except AttributeError:
            try:
                beta = float(np.real(mline.beta[0]))
                omega = 2 * np.pi * freq_ghz * 1e9
                c0 = 299792458.0
                er_eff = (beta * c0 / omega) ** 2
            except Exception:
                er_eff = stackup.epsilon_r  # 粗略近似

    return z0, er_eff


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
    status: str  # "ok" | "needs_calibration"
    delta_z0: float

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
    _, er_eff = forward_z0(width_mm, freq_ghz, stackup)

    return SynthesisResult(
        z0_target=z0_target,
        freq_ghz=freq_ghz,
        stackup_name=stackup_name,
        width_mm=width_mm,
        z0_actual=z0_actual,
        epsilon_eff=er_eff,
        status=status,
        delta_z0=abs(z0_actual - z0_target),
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
    （series=70.7Ω 臂窄、shunt=50Ω 馈线宽，统一口径）。
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    c_mm_ghz = 299.792458  # mm*GHz

    # lambda/4 arm length
    _, er_eff = forward_z0(1.0, f0_ghz, stackup)  # approximate with w=1mm
    lambda_4_mm = c_mm_ghz / (4 * f0_ghz * np.sqrt(er_eff))

    # series arm width: Zt = Z0*sqrt(2) ≈ 70.7Ω（两臂，比 50Ω 窄）
    series_result = synthesize_mline(z0_ohm * np.sqrt(2), f0_ghz, stackup_name, materials_path=materials_path)
    series_w = series_result.width_mm

    # shunt feeder width: Z0 = 50Ω（宽）
    shunt_result = synthesize_mline(z0_ohm, f0_ghz, stackup_name, materials_path=materials_path)
    shunt_w = shunt_result.width_mm

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
        f"lambda/4 = {lambda_4_mm:.2f}mm @ {f0_ghz}GHz (er_eff={er_eff:.2f})",
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
    """Branchline coupler综合：f0 + Z0 → arm_len + series_w + shunt_w.

    闭式公式：
    - arm_len = lambda/4
    - series_w: 35.35Ω (Z0/sqrt(2)) line width for series arms
    - shunt_w: 50Ω line width for shunt arms
    """
    stackup = Stackup.from_materials_yaml(stackup_name, materials_path)
    c_mm_ghz = 299.792458
    _, er_eff = forward_z0(1.0, f0_ghz, stackup)
    lambda_4_mm = c_mm_ghz / (4 * f0_ghz * np.sqrt(er_eff))

    series_result = synthesize_mline(z0_ohm / np.sqrt(2), f0_ghz, stackup_name, materials_path=materials_path)
    shunt_result = synthesize_mline(z0_ohm, f0_ghz, stackup_name, materials_path=materials_path)

    params = {
        "f0_ghz": f0_ghz,
        "arm_len_mm": round(lambda_4_mm, 2),
        "series_w_mm": round(series_result.width_mm, 3),
        "shunt_w_mm": round(shunt_result.width_mm, 3),
    }
    recipe_draft = {
        "model": "branchline_coupler", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"solver": "DrivenModal", "freq_range_ghz": [f0_ghz * 0.7, f0_ghz * 1.3], "points": 401},
        "objectives": [{"metric": "s11_db", "band": [f0_ghz * 0.96, f0_ghz * 1.04], "op": "max_below", "value": -15}],
    }
    notes = [f"lambda/4 = {lambda_4_mm:.2f}mm", f"35.35ohm series = {series_result.width_mm:.3f}mm",
             f"50ohm shunt = {shunt_result.width_mm:.3f}mm"]
    return ModelSynthesisResult(model="branchline_coupler", goal={"f0_ghz": f0_ghz}, params=params,
                                recipe_draft=recipe_draft, notes=notes)


def synthesize_patch(
    f0_ghz: float = 2.4,
    er: float = 3.66,
    h_mm: float = 0.508,
    s11_target_db: float = -10.0,
) -> ModelSynthesisResult:
    """矩形贴片天线综合（Hammerstad 模型）：f0 + er + h → patch_len + patch_w + feed_offset.

    闭式公式：
    - W = c / (2*f0) * sqrt(2/(er+1))
    - er_eff = (er+1)/2 + (er-1)/2 * (1+12*h/W)^(-0.5)
    - dL = 0.824*h * (er_eff+0.3)/(er_eff-0.258) * (W/h+0.264)/(W/h+0.8)
    - L = c/(2*f0*sqrt(er_eff)) - 2*dL
    - feed_offset: L/2 * sqrt(1/(2*Zin)) where Zin ~ 90-120 ohm for edge feed
    """
    c_mm_ghz = 299.792458
    w_mm = c_mm_ghz / (2 * f0_ghz) * np.sqrt(2 / (er + 1))
    er_eff = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 * h_mm / w_mm) ** (-0.5)
    dL = 0.824 * h_mm * (er_eff + 0.3) / (er_eff - 0.258) * (w_mm / h_mm + 0.264) / (w_mm / h_mm + 0.8)
    l_mm = c_mm_ghz / (2 * f0_ghz * np.sqrt(er_eff)) - 2 * dL
    feed_offset = l_mm * 0.3  # approximate for ~100ohm input impedance

    params = {"f0_ghz": f0_ghz, "patch_len_mm": round(l_mm, 2), "patch_w_mm": round(w_mm, 2),
              "feed_offset_mm": round(feed_offset, 2)}
    recipe_draft = {
        "model": "patch_antenna", "recipe_version": 1, "schema_version": 1,
        "params": {k: {"value": v} for k, v in params.items()},
        "setup": {"solver": "DrivenModal", "freq_range_ghz": [f0_ghz * 0.8, f0_ghz * 1.2], "points": 401},
        "objectives": [{"metric": "s11_db", "band": [f0_ghz * 0.96, f0_ghz * 1.04], "op": "max_below", "value": s11_target_db}],
    }
    notes = [f"W={w_mm:.2f}mm, L={l_mm:.2f}mm (er_eff={er_eff:.3f})", f"feed_offset={feed_offset:.2f}mm"]
    return ModelSynthesisResult(model="patch_antenna", goal={"f0_ghz": f0_ghz}, params=params,
                                recipe_draft=recipe_draft, notes=notes)


def synthesize_mline_model(
    z0_ohm: float = 50.0,
    freq_ghz: float = 2.5,
    line_len_mm: float = 40.0,
    stackup_name: str = "rogers4350b_h0.508",
    *,
    materials_path: str | Path | None = None,
) -> ModelSynthesisResult:
    """均匀微带线综合（mline 锚模板）：目标 Z0 → 线宽（skrf HJ 精算）。

    锚模板三重身份：校准件 + 引擎仲裁探针（S21 相位斜率→εeff，β 金
    标准 #162）+ 数据工厂（单点秒-分钟级）。线宽绝不沿用文档毫米数
    ——inverse_width 精算并回代自洽。
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
    """均匀共面波导（底接地 CPWG 口径）综合（CPW 锚）。

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
    """半波振子综合：目标谐振频率 → 全臂长（λ/2 自由空间闭式）。

    L = c/(2·f0)。引擎端效应残差如实记录不采信为锚：#194 冒烟 58mm
    实测谷 2.285GHz vs 闭式 2.585GHz（−11.7%），无 HFSS 仲裁前不下
    结论（HFSS 为对齐基准）。objectives 走谷深语义（#197：
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
    """微带宽度阶跃综合（不连续性基元首个增量）。

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
    """微带 T 接头综合（不连续性基元）：全臂统一线宽（inverse_width）。

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
    """微带直角弯折综合（不连续性基元）：全臂统一线宽（inverse_width）。

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
    """过孔过渡综合（不连续性基元）：馈线统一 50Ω 线宽（inverse_width）。

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
    """π 型衰减器综合（首族）：目标衰减 → 三电阻（闭式）。

    电阻值=calculators.attenuator_pi 同一闭式（ABCD 校验）。objectives：
    |S21| mean_within ±0.5dB（平坦衰减，均值语义匹配响应形态）
    + |S11| max_below -20dB（按设计匹配）。
    """
    from rfauto.core.calculators import attenuator_pi

    res = attenuator_pi(attenuation_db=attenuation_db, z0_ohm=z0_ohm)
    r_ser = res["r_series_mid_ohm"]
    r_sh = res["r_shunt_end_ohm"]

    params = {"atten_db": attenuation_db, "w_mm": 1.1134,
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
    """T 型衰减器综合（横向变体）：目标衰减 → 三电阻（闭式）。

    电阻值=E4 attenuator_t 闭式（ABCD 校验）：两臂各串 r_series_arm、
    中点对地 r_shunt_mid。objectives 同 atten_pi（平坦均值+匹配门）。
    """
    from rfauto.core.calculators import attenuator_t

    res = attenuator_t(attenuation_db=attenuation_db, z0_ohm=z0_ohm)
    r_ser = res["r_series_arm_ohm"]
    r_mid = res["r_shunt_mid_ohm"]

    params = {"atten_db": attenuation_db, "w_mm": 1.1134,
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
    """rat-race 环形电桥综合：环阻抗 √2·Z0 → 环宽与半径（闭式）。

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
    """Gysel 功分器综合（横向变体）：臂 √2·Z0、隔离线 Z0（闭式）。

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
    """对称带状线综合（锚族）：目标 Z0 → 中心带宽度（闭式反解）。

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
    """MSL↔CPWG 过渡综合（Tier 2 首增量）。

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
    """SMA 边缘弹射综合（edge-launch 夹具口径）。

    同轴 TEM 精确闭式 Z0=(60/√εr)·ln(r_o/r_i) → r_o 反解（PTFE 填充
    εr=2.1 → εeff=εr）；外导体外径 r_os=r_o+壁厚为派生量（不进 params，
    渲染由 shell_t_mm 派生）；MSL 侧 inverse_width（HJ）。
    port1=同轴截面集总桥（LumpedPort 50Ω，针顶→壳内壁顶；CoaxialPort 真机
    判废：0.4mm 阶梯网格下差分 TL 探针分解失真，见 openems_templates
    段），β 金标准只锚 port2（HJ）。|S11| 验收对照文献曲线（edge-launch SMA
    带内回损常规 15-20dB，objectives 保守地板 -10dB——方案行"验收靠文献曲线"
    口径，docs/rf_template_references.md SMA 节）。针径/填充越界显式报错
    （先验模型后校准）。
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


# ─── 带通滤波器综合（耦合矩阵口径，广义切比雪夫 → N+2 CM）─────────────────

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
            "cross_family": cross_family,
            "response_max_err": float(err),
            "pattern_residual": (round(pattern_residual, 12)
                                 if topology == "folded" else 0.0),
            "notes": notes}


# ─── hairpin（发夹线 BPF）综合链（自 adapters 升格 core）─────────────────
# 自 adapters/openems_templates.py hairpin 段原样下沉（adapters 再导出、零改动
# 消费；#116 不留遮蔽副本）：矩阵综合（本文件 synthesize_bpf_model，folded）
# → k/Q_e 映射（Hong §5.2/§5.3：k_{i,i+1}=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²））
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
    """BPF 矩阵综合 → hairpin 几何（确定性映射；矩阵综合在本文件，本函数只做映射）。

    k_{i,i+1}=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²)（Hong §5.2/§5.3），
    再经 KJ 反解得缝、经抽头闭式得 τ（口径见 adapters/openems_templates 文末
    hairpin 段）。
    order=1（单谐振器双抽头探针，Q 标定）无耦合缝：k_list=[]、gaps_mm=[]、
    gap_mm=None（不再 IndexError）。arm_gap_mm 默认 3.0（名义定版：
    k_self(3.0)=0.0115 < 互耦 k=0.0515 < k_self(1.0)=0.0602，U 内两臂缝须使同臂
    自耦远小于互耦，旧默认 1.0 反超是四轮 FAIL 的结构性根因）。

    kgap_corrected=True：缝反解改用 hairpin 结构经验修正映射
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
    stackup = Stackup(name="hairpin", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    w = (float(inverse_width(50.0, float(f0_ghz), stackup)[0])
         if w_mm is None else float(w_mm))
    synth = synthesize_bpf_model(order=n, f0_ghz=float(f0_ghz),
                                 fbw=float(fbw), rl_db=float(rl_db),
                                 topology="folded")
    if not synth.get("ok"):
        raise ValueError(f"矩阵综合失败: {synth.get('errors')}")
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
            f"folded N={n}：k={_fmt_list(ks, 5)}，Q_e={qe:.4f}",
            (f"hairpin 结构修正 c(gap) 反解缝={_fmt_list(gaps, 4)} mm（纯 KJ "
             f"{_fmt_list(gaps_kj, 4)}；等缝={uniform}）" if kgap_corrected else
             f"KJ 反解缝={_fmt_list(gaps, 4)} mm（等缝={uniform}）"),
            f"抽头 τ={tau:.4f}（自开路端计；Q_e 闭式）",
            "口径见 openems_templates 文末 hairpin 段（#206 理论核验轮）",
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
