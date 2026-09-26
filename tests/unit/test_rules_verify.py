"""K1 活规则验证测试（DP-13）——knowledge/rules.yaml ``verify`` 字段指向的本体。

三件套=声明+正反例+收集器（specs §13.1）：
- test_r001_arm_formula_matches_synthesis：R001 λ/4 臂长公式 vs
  core/synthesis 闭式（正例逐点匹配 + λ/2 反例必不匹配）；
- test_r005_r007_linewidth_backsub_1ohm：R005/R007 线宽定案回代
  forward_z0 ±1Ω（正例过 + 旧值 2.20mm 反例必不匹配）；
- test_r006_fix_values_consistent_with_g0：R006 fix/根因文本与 R005/R007
  定案值一致，且 root_cause 的 "~31ohm" 结论机器复算自洽；
- test_rules_verify_declared_subset_exact：机器可验证子集声明双向防漂移；
- test_rules_verify_nodes_collectable：收集器——rules.yaml 每条 verify.test
  子进程 pytest --co 真实可收集（防声明漂移）。

数值锚（预声明 runs/df6_dp13/criteria.md §K1，venv 2026-09-24 实测）：
forward_z0(1.11mm, 2.4GHz, rogers4350b_h0.508)=50.094Ω；
forward_z0(1.87mm)=35.359Ω vs 35.3553Ω；forward_z0(2.20mm)=31.426Ω。
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RULES_PATH = _REPO_ROOT / "knowledge" / "rules.yaml"
_STACKUP = "rogers4350b_h0.508"
_FREQ_GHZ = 2.4  # G0 定案频率（scripts/g0_linewidth_verification.py FREQ_GHZ）
_C_MM_GHZ = 299.792458  # mm·GHz

#: 机器可验证子集（DP-13 K1 拍板）：恰好这四条，双向防漂移
MACHINE_VERIFIABLE = {"R001", "R005", "R006", "R007"}
#: 判"不可机器验证"显式省略（启发式诊断/战役结论，不凑绿）
NOT_MACHINE_VERIFIABLE = {"R002", "R003", "R004", "R008", "R009"}


def _load_rules() -> dict[str, dict]:
    data = yaml.safe_load(_RULES_PATH.read_text(encoding="utf-8"))
    return {r["id"]: r for r in data.get("rules", [])}


# ─── R001：λ/4 臂长公式 vs core/synthesis 闭式 ───────────────────────────────

def test_r001_arm_formula_matches_synthesis():
    from rfauto.core.synthesis import Stackup, forward_z0, synthesize_wilkinson

    stackup = Stackup.from_materials_yaml(_STACKUP)
    # 正例：R001 公式 arm = c/(4·f0·√εeff) 与 synthesize_wilkinson 闭式逐点一致
    # （引擎 arm_len 2 位舍入 → 容差 0.02mm；εeff 同源 forward_z0(w=1mm)）
    for f0 in (2.0, 2.4, 3.0, 5.8):
        _, eeff = forward_z0(1.0, f0, stackup)
        rule_arm = _C_MM_GHZ / (4.0 * f0 * math.sqrt(eeff))
        engine_arm = synthesize_wilkinson(f0_ghz=f0).params["arm_len_mm"]
        assert abs(rule_arm - float(engine_arm)) <= 0.02, (
            f"f0={f0}: R001 公式 {rule_arm:.4f} vs 引擎 {engine_arm}")

    # 规则自带例：f0=2.4, eeff≈2.33 → arm≈20.5mm（example 字段的数值自洽）
    example_arm = _C_MM_GHZ / (4.0 * 2.4 * math.sqrt(2.33))
    assert abs(example_arm - 20.5) <= 0.1

    # 反例：λ/2（×2）错误公式必不匹配（证明测试有牙，非恒真）
    _, eeff = forward_z0(1.0, 2.4, stackup)
    half_wave = 2.0 * _C_MM_GHZ / (4.0 * 2.4 * math.sqrt(eeff))
    engine_arm = float(synthesize_wilkinson(f0_ghz=2.4).params["arm_len_mm"])
    assert abs(half_wave - engine_arm) > 1.0


# ─── R005/R007：线宽定案 vs forward_z0 回代 ±1Ω ─────────────────────────────

def _r007_widths(r007_formula: str) -> tuple[float, float]:
    m_series = re.search(r"series_w_mm:\s*G0 定案\s*([\d.]+)\s*mm", r007_formula)
    m_shunt = re.search(r"shunt_w_mm:\s*G0 定案\s*([\d.]+)\s*mm", r007_formula)
    assert m_series and m_shunt, f"R007 formula 文本格式漂移: {r007_formula!r}"
    return float(m_series.group(1)), float(m_shunt.group(1))


def test_r005_r007_linewidth_backsub_1ohm():
    from rfauto.core.synthesis import Stackup, forward_z0

    rules = _load_rules()
    stackup = Stackup.from_materials_yaml(_STACKUP)
    z0_35 = 50.0 / math.sqrt(2.0)  # 35.3553Ω（branchline series 臂）

    checks: list[tuple[str, str, float, float]] = [
        ("R005", "values.z0_50ohm_mm",
         float(rules["R005"]["values"]["z0_50ohm_mm"]), 50.0),
        ("R005", "values.z0_35ohm_mm",
         float(rules["R005"]["values"]["z0_35ohm_mm"]), z0_35),
    ]
    w_series, w_shunt = _r007_widths(str(rules["R007"]["formula"]))
    checks.append(("R007", "formula.series_w_mm", w_series, z0_35))
    checks.append(("R007", "formula.shunt_w_mm", w_shunt, 50.0))

    # 正例：定案线宽回代正向 HJ 模型，|ΔZ0| ≤ 1Ω（预声明门）
    for rid, key, w_mm, z0_target in checks:
        z0, _ = forward_z0(w_mm, _FREQ_GHZ, stackup)
        assert abs(z0 - z0_target) <= 1.0, (
            f"{rid}.{key}={w_mm}mm 回代 {z0:.3f}Ω，偏离 {z0_target:.4f}Ω "
            f"{z0 - z0_target:+.3f} 超 ±1Ω（引擎漂移或定案值失真）")

    # 反例：旧值 2.20mm（R006 记录的错误定案）回代必超 ±1Ω
    z0_old, _ = forward_z0(2.20, _FREQ_GHZ, stackup)
    assert abs(z0_old - z0_35) > 1.0, "旧值 2.20mm 竟过 ±1Ω 门——测试失去判别力"


# ─── R006：fix 值一致性与 root_cause "~31ohm" 自洽 ───────────────────────────

def test_r006_fix_values_consistent_with_g0():
    from rfauto.core.synthesis import Stackup, forward_z0

    rules = _load_rules()
    stackup = Stackup.from_materials_yaml(_STACKUP)
    z0_35 = 50.0 / math.sqrt(2.0)

    fix_text = str(rules["R006"]["fix"])
    m_fix = re.search(r"series_w_mm\s*改为\s*([\d.]+)\s*mm", fix_text)
    assert m_fix, f"R006 fix 文本格式漂移: {fix_text!r}"
    series_fix = float(m_fix.group(1))

    # fix 值 == R005.values.z0_35ohm_mm == R007 formula series 值（三处定案一致）
    r005_35 = float(rules["R005"]["values"]["z0_35ohm_mm"])
    w_series, _ = _r007_widths(str(rules["R007"]["formula"]))
    assert series_fix == r005_35 == w_series

    # root_cause 数值结论机器复算：旧值 2.20mm → "~31ohm"（±1Ω 内自洽）
    root_cause = str(rules["R006"]["root_cause"])
    m_old = re.search(r"series_w_mm=([\d.]+)mm", root_cause)
    assert m_old, "R006 root_cause 缺旧值记录"
    z0_old, _ = forward_z0(float(m_old.group(1)), _FREQ_GHZ, stackup)
    assert abs(z0_old - 31.0) <= 1.0, (
        f"root_cause 声称 ~31ohm，实测回代 {z0_old:.3f}Ω 超门")
    # 正确定案值确在 root_cause 中出现且回代过 ±1Ω 门
    m_right = re.search(r"线宽为\s*([\d.]+)mm", root_cause)
    assert m_right and float(m_right.group(1)) == r005_35
    z0_right, _ = forward_z0(float(m_right.group(1)), _FREQ_GHZ, stackup)
    assert abs(z0_right - z0_35) <= 1.0


# ─── 声明防漂移：机器可验证子集恰为四条 ──────────────────────────────────────

def test_rules_verify_declared_subset_exact():
    rules = _load_rules()
    with_verify = {rid for rid, r in rules.items() if "verify" in r}
    assert with_verify == MACHINE_VERIFIABLE, (
        f"verify 登记集漂移: 多出 {with_verify - MACHINE_VERIFIABLE}, "
        f"缺 {MACHINE_VERIFIABLE - with_verify}")
    # 显式省略集不得登记（不凑绿）
    assert with_verify.isdisjoint(NOT_MACHINE_VERIFIABLE)
    for rid in sorted(MACHINE_VERIFIABLE):
        v = rules[rid]["verify"]
        assert v.get("runner") == "pytest", f"{rid} verify.runner 漂移"
        assert v["test"].startswith(
            "tests/unit/test_rules_verify.py::"), f"{rid} verify.test 出域"


# ─── 收集器：每条 verify.test 真实可收集（防声明漂移） ────────────────────────

def test_rules_verify_nodes_collectable():
    rules = _load_rules()
    nodes = [rules[rid]["verify"]["test"]
             for rid in sorted(MACHINE_VERIFIABLE)]
    assert nodes
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--co", "-q", *nodes],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, (
        f"收集失败:\n{proc.stdout[-2000:]}\n{proc.stderr[-1000:]}")
    for node in nodes:
        assert node in proc.stdout, f"verify.test 节点未收集到: {node}"
