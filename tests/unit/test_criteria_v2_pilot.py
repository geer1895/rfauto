"""df7 DP-12 双落盘试点：DP-10 J1c 门 v2 机器判据源 × launch_sweep --judge 单测。

三对象（判据预声明 runs/df6_dp12vv/criteria.md §四、runs/df6_dp10ms/
criteria.md §1c 冻结零改写）：
- knowledge/criteria/v2/df6_dp10_scan.yaml（本批新件，schema: criteria/v2，
  md 的机器判据源转写，逐值与 md 一致）；
- runs/df6_dp10ms/launch_sweep.py --judge 段（v2 YAML 消费：与内置值逐位
  互证，缺文件/不一致 fail-closed 拒判；--judge-offline-v1 调试逃生开关；
  判读 JSON 附 vv_* 附加字段，verdict 键零改动）；
- 行为零变化钉：改造前基线（合成 LUT fixture 跑改造前 judge() 采集，
  2026-09-25，verdict/coverage/stdout 判读行写死于 BASELINE_*）。

runs/ 资产（launch_sweep.py）缺在（干净检出）时 skip——本测试钉工作区
资产，不伪造数据（test_vv_recast 同款纪律）。
"""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import math
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rfauto.core.vv_mapping as vv

V2 = REPO / "knowledge" / "criteria" / "v2"
YAML_PATH = V2 / "df6_dp10_scan.yaml"
LAUNCH_PATH = REPO / "runs" / "df6_dp10ms" / "launch_sweep.py"

VV_STATUSES = {
    vv.VV_VALIDATED, vv.VV_NOT_VALIDATED, vv.VV_CONDITIONALLY_VALIDATED,
    vv.VV_VALIDATION_NOT_ATTEMPTED, vv.VV_OUT_OF_SCOPE, vv.VV_NOT_JUDGED,
    vv.VV_PREFLIGHT_INVALID,
}

# ── schema 合同必备键（runs/df6_dp12vv/criteria.md §四） ─────────────────────
REQUIRED_TOP = ("schema", "criteria_id", "title", "status", "runner_binding",
                "claim", "evidence_fields", "u_val", "decision_rule",
                "verdict_map", "provenance")
REQUIRED_CLAIM = ("quantity", "template", "f_ghz")
REQUIRED_U_VAL = ("u_num", "u_input", "u_D")
REQUIRED_PROVENANCE = ("commit", "devlog", "referee_run", "gate_db_legacy")

# ── 改造前基线（judge 行为零变化钉；采集口径见模块 docstring） ────────────────
# PASS fixture：px 2..13mm 10 点、f0=10GHz 处解缠相位 −170°..+170°（覆盖 340°）
BASELINE_PASS = {
    "phase_coverage_deg": 340.0,
    "threshold_deg": 300.0,
    "verdict": "PASS",
    "stdout_line": "[coarse] n_sweep=10 coverage=340.0° verdict=PASS validate=OK",
}
# FAIL fixture：同网格、相位 −100°..+100°（覆盖 200° <300° → FAIL 如实落档）
BASELINE_FAIL = {
    "phase_coverage_deg": 200.0,
    "threshold_deg": 300.0,
    "verdict": "FAIL",
    "stdout_line": "[coarse] n_sweep=10 coverage=200.0° verdict=FAIL validate=OK",
}
# 判读 JSON gate 块的 vv 附加键集合（vv_mapping 并列注入，verdict 键零改动）
VV_ADDED_KEYS = {"input_verdict", "vv_schema", "vv_status", "vv_basis",
                 "vv_evidence_fields", "vv_notes"}

_LAUNCH_MOD: Any = None


def _launch() -> Any:
    """按路径加载 runs/df6_dp10ms/launch_sweep.py（runs/ 不在包路径的惯例）。"""
    global _LAUNCH_MOD
    if not LAUNCH_PATH.exists():
        pytest.skip("runs/df6_dp10ms/launch_sweep.py 不在（干净检出）")
    if _LAUNCH_MOD is None:
        spec = importlib.util.spec_from_file_location("_dp10_launch_sweep",
                                                      LAUNCH_PATH)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _LAUNCH_MOD = mod
    return _LAUNCH_MOD


def _load_yaml() -> dict[str, Any]:
    import yaml

    with YAML_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict)
    return data


def _build_wg_sim(root: Path, stage: str, phi_lo: float, phi_hi: float,
                  n_px: int = 10) -> None:
    """合成波导模拟器产物：phase(px) 线性 phi_lo..phi_hi（freq 无关），|S11|=0.95。"""
    freq = [float(v) for v in np.linspace(9.75e9, 10.25e9, 11)]
    for k in range(n_px):
        px = 2.0 + k * (13.0 - 2.0) / (n_px - 1)
        phi = phi_lo + k * (phi_hi - phi_lo) / (n_px - 1)
        run_dir = root / f"{stage}_px{px:.4f}"
        run_dir.mkdir(parents=True, exist_ok=True)
        z = 0.95 * complex(math.cos(math.radians(phi)),
                           math.sin(math.radians(phi)))
        lines = ["freq_hz,re_s11,im_s11"]
        lines += [f"{f!r},{z.real!r},{z.imag!r}" for f in freq]
        (run_dir / "sparams.csv").write_text("\n".join(lines) + "\n",
                                             encoding="utf-8")


def _run_judge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
               phi_lo: float = -170.0, phi_hi: float = 170.0) -> tuple[dict[str, Any], str]:
    """在 tmp RUN_ROOT 上跑 --judge 路径，返回 (lut_coarse.json 的 gate 块, stdout)。"""
    ls = _launch()
    root = tmp_path / "wg_sim"
    _build_wg_sim(root, "coarse", phi_lo, phi_hi)
    monkeypatch.setattr(ls, "RUN_ROOT", root)
    buf = io.StringIO()
    with redirect_stdout(buf):
        ls.judge()
    gate = json.loads((root / "lut_coarse.json").read_text(encoding="utf-8"))
    return gate["gate"], buf.getvalue()


# ── ① YAML schema 合同（全键齐备+值域合法，test_criteria_v2_schema_contract 模式）


def test_dp10_scan_yaml_schema_contract() -> None:
    data = _load_yaml()
    assert data["schema"] == "criteria/v2"
    for key in REQUIRED_TOP:
        assert key in data, f"缺顶层键 {key}"
    for key in REQUIRED_CLAIM:
        assert key in data["claim"], f"claim 缺键 {key}"
    for key in REQUIRED_U_VAL:
        assert key in data["u_val"], f"u_val 缺键 {key}"
        assert "source" in data["u_val"][key] and "rule" in data["u_val"][key]
    for key in REQUIRED_PROVENANCE:
        assert key in data["provenance"], f"provenance 缺键 {key}"
    assert data["evidence_fields"] and all(
        isinstance(e, str) for e in data["evidence_fields"])
    # verdict_map 值域 ⊆ vv_mapping 状态常量（防 schema 漂移）
    for verdict, status in data["verdict_map"].items():
        assert status in VV_STATUSES, f"verdict_map[{verdict}]={status} 非法"


def test_dp10_scan_yaml_values_match_md_bitwise() -> None:
    """转写与 md 逐值一致（runs/df6_dp10ms/criteria.md §1c 冻结值）。"""
    data = _load_yaml()
    claim = data["claim"]
    assert claim["quantity"] == "s11_phase_coverage_deg"  # J1c 判据量
    assert claim["template"] == "ms_patch"
    # f0=10.0 GHz（X 波段演示族；逐位口径=float.hex 同位型相等）
    assert float(claim["f_ghz"]).hex() == (10.0).hex()
    rule = data["decision_rule"]
    # J1c：覆盖 ≥300°（md §1c「≥300°」的机器名）
    assert float(rule["threshold"]).hex() == (300.0).hex()
    assert rule["comparison"] == ">="
    # J1c 无 ΔS 阶梯：u_num 不虚构（预声明 none_declared，不虚标 ladder）
    assert data["u_val"]["u_num"]["source"] == "none_declared"
    # 双落盘试点：runner 已接线（df6 批 followUp 预声明的落点，不再是 followUp）
    assert data["runner_binding"] == "launch_sweep_judge"
    assert data["provenance"]["referee_run"] == "runs/df6_dp10ms"
    # verdict_map 全覆盖 coverage_gate 两态
    assert set(data["verdict_map"]) == {"PASS", "FAIL"}


# ── ② YAML 门值 vs judge 内置值逐位互证（改 YAML → 互证红） ──────────────────


def test_crosscheck_real_yaml_vs_builtin_passes() -> None:
    ls = _launch()
    crit = _load_yaml()
    gate = {"phase_coverage_deg": 340.0, "threshold_deg": 300.0,
            "verdict": "PASS"}
    ls.crosscheck_criteria_v2(crit, gate, f0_ghz=10.0)  # 不抛=互证通过


def test_crosscheck_int_300_same_bits_as_300d0() -> None:
    # 逐位口径：int 300 与 float 300.0 同值同位（YAML 手写 300 不误伤）
    ls = _launch()
    crit = _load_yaml()
    crit["decision_rule"]["threshold"] = 300
    gate = {"phase_coverage_deg": 340.0, "threshold_deg": 300.0,
            "verdict": "PASS"}
    ls.crosscheck_criteria_v2(crit, gate, f0_ghz=10.0)


@pytest.mark.parametrize(
    ("mutate", "key"),
    [
        (lambda c: c["decision_rule"].__setitem__("threshold", 250.0),
         "decision_rule.threshold"),
        (lambda c: c["decision_rule"].__setitem__("comparison", ">"),
         "decision_rule.comparison"),
        (lambda c: c.__setitem__("schema", "criteria/v1"), "schema"),
        (lambda c: c["claim"].__setitem__("quantity", "s11_db"),
         "claim.quantity"),
        (lambda c: c["claim"].__setitem__("f_ghz", 9.5), "claim.f_ghz"),
        (lambda c: c["verdict_map"].__setitem__("FAIL", "validated"),
         "verdict_map.FAIL"),
        (lambda c: c["verdict_map"].pop("FAIL"), "verdict_map.FAIL"),
    ],
)
def test_yaml_mutation_fails_closed(mutate: Any, key: str) -> None:
    """改 YAML 任一门键 → 互证红且 fail-closed，报错写明哪键哪值不匹配。"""
    ls = _launch()
    crit = _load_yaml()
    mutate(crit)
    gate = {"phase_coverage_deg": 340.0, "threshold_deg": 300.0,
            "verdict": "PASS"}
    with pytest.raises(ValueError) as ei:
        ls.crosscheck_criteria_v2(crit, gate, f0_ghz=10.0)
    msg = str(ei.value)
    assert "[fail-closed]" in msg
    assert key in msg, f"报错未点名键 {key}：{msg}"
    assert "YAML=" in msg and "vs 内置=" in msg


def test_judge_missing_yaml_fails_closed(tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """YAML 缺文件=fail-closed（双落盘试点语义=机器源必须在场）。"""
    ls = _launch()
    monkeypatch.setattr(ls, "CRITERIA_V2_PATH", tmp_path / "nope.yaml")
    with pytest.raises(SystemExit) as ei:
        ls.judge()
    msg = str(ei.value)
    assert "[fail-closed]" in msg and "v2 判据源缺失" in msg
    assert "--judge-offline-v1" in msg  # 报错指路逃生开关


# ── ③ judge 行为零变化（verdict 与改造前基线一致） ────────────────────────────


@pytest.mark.parametrize(
    ("baseline", "phi_lo", "phi_hi"),
    [(BASELINE_PASS, -170.0, 170.0), (BASELINE_FAIL, -100.0, 100.0)],
    ids=["pass_340deg", "fail_200deg"],
)
def test_judge_behavior_unchanged(tmp_path: Path,
                                  monkeypatch: pytest.MonkeyPatch,
                                  baseline: dict[str, Any],
                                  phi_lo: float, phi_hi: float) -> None:
    ls = _launch()
    root = tmp_path / "wg_sim"
    _build_wg_sim(root, "coarse", phi_lo, phi_hi)
    monkeypatch.setattr(ls, "RUN_ROOT", root)
    ls.judge()
    gate = json.loads((root / "lut_coarse.json").read_text(encoding="utf-8"))["gate"]
    # ① 判读 JSON 落盘存在（双载体路径不变）且 gate 基线键值逐个一致
    assert (root / "lut_coarse.csv").exists()
    for k, v in baseline.items():
        if k == "stdout_line":
            continue
        assert gate[k] == v, f"基线键 {k} 漂移：{gate[k]!r} != {v!r}"
    # ② gate 键集合=基线三键+vv 附加六键（无其他漂移，verdict 键零改动）
    assert set(gate) == {"phase_coverage_deg", "threshold_deg", "verdict"
                         } | VV_ADDED_KEYS
    # ③ stdout 判读行核对在 test_judge_stdout_matches_baseline（capsys 版）


def test_judge_stdout_matches_baseline(tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    ls = _launch()
    root = tmp_path / "wg_sim"
    _build_wg_sim(root, "coarse", -170.0, 170.0)
    monkeypatch.setattr(ls, "RUN_ROOT", root)
    ls.judge()
    out = capsys.readouterr().out
    assert BASELINE_PASS["stdout_line"] in out      # 判读行逐字符一致
    assert "[fine] 无产物，跳过" in out
    assert out.rstrip().endswith(
        "判读纪律：verdict=FAIL 如实落档（覆盖 <300° 时 fallback=双谐振"
        "预登记，criteria §1c）；|S11|>1 先查 NrTS 截断（#262）再疑物理")
    # vv 附加行只增不改：判据源名出现在 [vv] 行
    assert "[vv] vv_status='validated'（判据源：df6_dp10_scan.yaml）" in out


# ── ④ vv_status 映射钉（verdict_map 消费 + verdict 键零改动） ─────────────────


@pytest.mark.parametrize(
    ("phi_lo", "phi_hi", "verdict", "expected_status"),
    [(-170.0, 170.0, "PASS", vv.VV_VALIDATED),
     (-100.0, 100.0, "FAIL", vv.VV_NOT_VALIDATED)],
    ids=["pass_validated", "fail_not_validated"],
)
def test_judge_vv_mapping_pins(tmp_path: Path,
                               monkeypatch: pytest.MonkeyPatch,
                               phi_lo: float, phi_hi: float,
                               verdict: str, expected_status: str) -> None:
    gate, _out = _run_judge(tmp_path, monkeypatch, phi_lo=phi_lo, phi_hi=phi_hi)
    assert gate["verdict"] == verdict              # 现行 verdict 原样
    assert gate["input_verdict"] == verdict        # 映射层不改名证据
    assert gate["vv_schema"] == vv.VV_SCHEMA
    assert gate["vv_status"] == expected_status    # verdict_map 映射
    assert gate["vv_notes"] and any(
        "criteria/v2 机器源已互证" in n for n in gate["vv_notes"])


def test_judge_vv_fail_note_carries_fallback(tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    gate, _out = _run_judge(tmp_path, monkeypatch, phi_lo=-100.0, phi_hi=100.0)
    assert gate["verdict"] == "FAIL"
    assert gate["vv_status"] == vv.VV_NOT_VALIDATED
    assert any("fallback" in n and "#122" in n for n in gate["vv_notes"])


def test_judge_offline_v1_escape_switch(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """逃生开关：YAML 不在场仍可用内置值判读；vv 注记写明仅调试用。"""
    ls = _launch()
    monkeypatch.setattr(ls, "CRITERIA_V2_PATH", tmp_path / "nope.yaml")
    root = tmp_path / "wg_sim"
    _build_wg_sim(root, "coarse", -170.0, 170.0)
    monkeypatch.setattr(ls, "RUN_ROOT", root)
    buf = io.StringIO()
    with redirect_stdout(buf):
        ls.judge(offline_v1=True)
    gate = json.loads((root / "lut_coarse.json").read_text(encoding="utf-8"))["gate"]
    assert gate["verdict"] == "PASS"               # 行为与正式判读一致
    assert gate["vv_status"] == vv.VV_VALIDATED
    assert any("--judge-offline-v1" in n and "仅调试" in n
               for n in gate["vv_notes"])
    assert "--judge-offline-v1" in buf.getvalue()


def test_vv_attach_is_best_effort(tmp_path: Path,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """vv 段故障不阻塞主判读（#105）：verdict 原样、vv_status=None 多报（#316）。

    patch 点=vv.apply_mapping（_attach_vv 专用入口）——不动 map_verdict，
    crosscheck 的 verdict_map 规范互证不受本钉干扰。
    """
    ls = _launch()

    def _boom(_obj: object, key: str = "verdict") -> dict[str, Any]:
        raise RuntimeError("synthetic vv failure")

    monkeypatch.setattr(ls.vv, "apply_mapping", _boom)
    root = tmp_path / "wg_sim"
    _build_wg_sim(root, "coarse", -170.0, 170.0)
    monkeypatch.setattr(ls, "RUN_ROOT", root)
    ls.judge()  # 不抛=主判读未被 vv 段拖垮
    gate = json.loads((root / "lut_coarse.json").read_text(encoding="utf-8"))["gate"]
    assert gate["verdict"] == "PASS"
    assert gate["vv_status"] is None
    assert any("vv 段附加失败" in n for n in gate["vv_notes"])


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / 'runs' / 'df6_dp10ms' / 'criteria.md').exists(),
    reason='runs/ evidence not distributed with git')
def test_v2_pilot_does_not_touch_frozen_md_or_index() -> None:
    # 冻结面存在性核对（内容零改写由 git status 抽查承担，这里钉机器源指向）
    assert (REPO / "runs" / "df6_dp10ms" / "criteria.md").exists()
    assert (REPO / "knowledge" / "criteria" / "index.yaml").exists()


def test_yaml_deepcopy_isolated_in_mutation_parametrize() -> None:
    # 防参数化共享态：_load_yaml 每次新读，mutation 不落盘（幂等性钉）
    data = _load_yaml()
    snapshot = copy.deepcopy(data)
    data["decision_rule"]["threshold"] = 1.0
    assert _load_yaml()["decision_rule"]["threshold"] != 1.0
    assert snapshot["decision_rule"]["threshold"] == 300.0
