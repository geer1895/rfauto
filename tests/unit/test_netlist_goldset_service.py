"""AI-6 netlist_goldset_service 单测：网表回放对照面（全离线，通道 mock）。

#139 纪律：模拟器通道一律注入 mock/解析闭式通道，零网络零真机零 Qucsator。
gold 值与通道算术路径独立（硬编码 gold vs 通道现场公式），不互证同源。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import yaml

from rfauto.service.netlist_goldset_service import (
    DEFAULT_TOL,
    load_netlist_goldset,
    netlist_fingerprint,
    replay_case,
    replay_netlist_goldset,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

NETLIST_TEXT = """\
* RC lowpass  R=1k C=100n  fc=1/(2*pi*R*C)
V1 in 0 DC 0 AC 1
R1 in out 1k
C1 out 0 100n
.control
ac dec 100 1 1Meg
.endc
.end
"""


def _analytic_rc_channel(netlist: str, analysis: str) -> dict[str, float]:
    """解析 RC 低通通道（独立算术路径，非 gold 复写）：fc=1/(2πRC)。"""
    r, c = 1.0e3, 100.0e-9
    fc = 1.0 / (2.0 * math.pi * r * c)
    gain_db_dc = 0.0  # 一阶低通 DC 增益 0 dB
    return {"fc_hz": fc, "gain_db_dc": gain_db_dc, "n_points": float(100)}


def _case(**overrides) -> dict:
    case = {
        "id": "rc_lowpass_ac",
        "netlist": NETLIST_TEXT,
        "analysis": "ac dec 100 1 1Meg",
        "expected": {
            "fc_hz": {"value": 1591.5494, "tol": 0.01},
            "gain_db_dc": {"value": 0.0, "tol": 0.01, "tol_mode": "abs"},
            "n_points": 100,  # 裸数值简写：tol 缺省 rel 5%
        },
    }
    case.update(overrides)
    return case


# ---------------------------------------------------------------------------
# load_netlist_goldset 结构自检
# ---------------------------------------------------------------------------

def test_load_valid_goldset(tmp_path):
    p = tmp_path / "gold.yaml"
    p.write_text(yaml.safe_dump({"version": 1, "tasks": [_case()]},
                                allow_unicode=True), encoding="utf-8")
    gold = load_netlist_goldset(p)
    assert gold["ok"] is True
    assert gold["n_tasks"] == 1
    assert gold["tasks"][0]["id"] == "rc_lowpass_ac"


def test_load_goldset_missing_file(tmp_path):
    gold = load_netlist_goldset(tmp_path / "nope.yaml")
    assert gold["ok"] is False
    assert "不存在" in gold["errors"][0]


def test_load_goldset_schema_errors(tmp_path):
    bad = [
        {"id": "a", "netlist": "  ", "expected": {"m": 1.0}},        # 空网表
        {"id": "b", "netlist": NETLIST_TEXT, "expected": {}},        # 空 expected
        {"id": "b", "netlist": NETLIST_TEXT,
         "expected": {"m": {"value": 1.0, "tol": -1.0}}},            # tol 非正
        {"id": "b", "netlist": NETLIST_TEXT,
         "expected": {"m": {"value": 1.0, "tol_mode": "pct"}}},      # mode 非法
        {"id": "b", "netlist": NETLIST_TEXT,
         "expected": {"m": {"value": "x"}}},                          # value 非数值
        _case(), _case(),                                             # id 重复
    ]
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump({"tasks": bad}, allow_unicode=True),
                 encoding="utf-8")
    gold = load_netlist_goldset(p)
    assert gold["ok"] is False
    assert any("重复" in e for e in gold["errors"])
    assert any("netlist 为空" in e for e in gold["errors"])
    assert any("tol 必须为正" in e for e in gold["errors"])


def test_fingerprint_stability():
    fp1 = netlist_fingerprint(NETLIST_TEXT)
    fp2 = netlist_fingerprint(NETLIST_TEXT)
    fp3 = netlist_fingerprint(NETLIST_TEXT + "\n")
    assert fp1 == fp2
    assert fp1 != fp3
    assert len(fp1) == 64


# ---------------------------------------------------------------------------
# replay_case 逐任务判读
# ---------------------------------------------------------------------------

def test_replay_case_pass_with_independent_channel():
    rep = replay_case(_case(), _analytic_rc_channel)
    assert rep["verdict"] == "PASS"
    assert rep["reasons"] == ["全部指标在容差内"]
    assert set(rep["deviations"]) == {"fc_hz", "gain_db_dc", "n_points"}
    assert len(rep["netlist_sha256"]) == 64


def test_replay_case_fail_on_out_of_tolerance():
    def bad_channel(netlist, analysis):
        out = _analytic_rc_channel(netlist, analysis)
        out["fc_hz"] = 2000.0  # 偏 gold ~25.6%，tol 1%
        return out

    rep = replay_case(_case(), bad_channel)
    assert rep["verdict"] == "FAIL"
    assert any("fc_hz" in r and "> tol" in r for r in rep["reasons"])


def test_replay_case_missing_metric_is_fail_not_silent():
    def partial_channel(netlist, analysis):
        return {"fc_hz": 1591.55}  # 缺 gain_db_dc / n_points

    rep = replay_case(_case(), partial_channel)
    assert rep["verdict"] == "FAIL"
    assert any("通道未产出该指标" in r for r in rep["reasons"])


def test_replay_case_channel_exception_is_error_verdict():
    def boom(netlist, analysis):
        raise RuntimeError("ngspice not found")

    rep = replay_case(_case(), boom)
    assert rep["verdict"] == "ERROR"
    assert rep["verdict"] != "FAIL"  # 数据坏≠模型类不覆盖（#345 分界）
    assert "ngspice not found" in rep["reasons"][0]


def test_replay_case_non_mapping_return_is_error():
    rep = replay_case(_case(), lambda n, a: [1, 2, 3])
    assert rep["verdict"] == "ERROR"
    assert any("非映射" in r for r in rep["reasons"])


def test_replay_case_bare_value_expected_uses_default_rel_tol():
    case = {"id": "t", "netlist": NETLIST_TEXT, "analysis": "",
            "expected": {"m": 100.0}}  # tol 缺省 rel 5%
    rep = replay_case(case, lambda n, a: {"m": 103.0})   # 3% 内 → PASS
    assert rep["verdict"] == "PASS"
    rep2 = replay_case(case, lambda n, a: {"m": 110.0})  # 10% 外 → FAIL
    assert rep2["verdict"] == "FAIL"


def test_default_tol_constant_is_five_percent():
    assert DEFAULT_TOL == 0.05


# ---------------------------------------------------------------------------
# replay_netlist_goldset 回归门（防空转）
# ---------------------------------------------------------------------------

def test_gate_all_pass(tmp_path):
    p = tmp_path / "gold.yaml"
    p.write_text(yaml.safe_dump({"tasks": [_case()]}, allow_unicode=True),
                 encoding="utf-8")
    gate = replay_netlist_goldset(goldset_path=p,
                                  simulator=_analytic_rc_channel)
    assert gate["ok"] is True
    assert gate["gate"] == "PASS"
    assert gate["n_cases"] == 1 and gate["n_pass"] == 1


def test_gate_fail_records_failing_case(tmp_path):
    p = tmp_path / "gold.yaml"
    broken = _case(id="broken_rc")
    p.write_text(yaml.safe_dump({"tasks": [broken]}, allow_unicode=True),
                 encoding="utf-8")
    gate = replay_netlist_goldset(goldset_path=p,
                                  simulator=lambda n, a: {"fc_hz": 999.0})
    assert gate["ok"] is False
    assert gate["gate"] == "FAIL"
    assert gate["n_fail"] == 1
    assert any("broken_rc" in r for r in gate["reasons"])


def test_gate_counts_error_separately():
    def mixed_channel(netlist, analysis):
        if "V1 in 0" not in netlist:  # 破损网表（无激励源）→ 通道异常
            raise ValueError("simulation failed")
        return _analytic_rc_channel(netlist, analysis)

    broken = _case(id="boom", netlist=NETLIST_TEXT.replace("V1 in 0 DC 0 AC 1\n", ""))
    gate = replay_netlist_goldset(tasks=[_case(id="ok1"), broken],
                                  simulator=mixed_channel)
    assert gate["n_error"] == 1
    assert gate["n_pass"] == 1
    assert gate["gate"] == "FAIL"


def test_gate_rejects_empty_and_missing_channel():
    gate = replay_netlist_goldset(tasks=[], simulator=lambda n, a: {})
    assert gate["ok"] is False
    assert "拒绝空跑" in gate["reasons"][0]
    gate2 = replay_netlist_goldset(tasks=[_case()], simulator=None)
    assert gate2["ok"] is False
    assert "未注入模拟器通道" in gate2["reasons"][0]
    gate3 = replay_netlist_goldset()
    assert gate3["ok"] is False
