"""P3 尾程项 13：闭式预言机（QM-2）只读 CLI 出口接线测试。

锚树（消费链端到端，离线零仿真零写盘）：
- 注册面：oracle 子应用三命令在 click 树（list/check/check-all）；
- list：注册表只读视图（键/kind/覆盖/闭式源/域盒/网格点数），envelope
  与 CLOSED_FORM_ORACLES 注册面逐键一致（无幽灵行/无漏行）；
- check：单键生成式对拍信封直出（内核 cross_check_oracle 原样透出，
  grade/verdict/per_quantity 键面在位）；未知键 → 失败信封 + 退出码 1
  + known_keys 全集回显（--json 下失败路径不许非 JSON）；
- check-all：全注册总报告（n_keys ≥20 验收口径 + 分级统计 + flags）；
- 只读口径：A-11 裁定"不构成重开理由"=只读出口——命令只调内核既有
  纯函数，数值全部出自 core/closed_form_oracle 确定性内核（铁律 7）；
  D 级旗标不翻退出码（#122 测量与报告语义，裁决读信封字段）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from typer.testing import CliRunner

from rfauto.cli.main import app
from rfauto.core.closed_form_oracle import (
    CLOSED_FORM_ORACLE_SCHEMA,
    CLOSED_FORM_ORACLES,
)

runner = CliRunner()


# ─── 注册面（五钉之消费面钉）─────────────────────────────────────────────

def test_oracle_subapp_registered_with_three_commands() -> None:
    from typer.main import get_command

    cmd = get_command(app)
    oracle_cmd = cmd.commands["oracle"]
    assert set(oracle_cmd.commands) == {"list", "check", "check-all"}


# ─── list（注册表只读视图）────────────────────────────────────────────────

def test_oracle_list_json_envelope_matches_registry() -> None:
    result = runner.invoke(app, ["oracle", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["schema"] == CLOSED_FORM_ORACLE_SCHEMA
    assert payload["n_oracles"] == len(CLOSED_FORM_ORACLES)
    assert payload["n_oracles"] >= 18  # 当前 18 oracle（≥20 键由 check-all 口径钉）
    rows = {row["key"]: row for row in payload["oracles"]}
    assert set(rows) == set(CLOSED_FORM_ORACLES)  # 无幽灵行/无漏行
    for key, oc in CLOSED_FORM_ORACLES.items():
        row = rows[key]
        assert row["kind"] == oc.kind
        assert row["kind"] in {"independent_network", "formula_reimpl",
                               "roundtrip"}  # #118 诚实三档
        assert row["covers"] == list(oc.covers)
        assert row["reference"] == oc.reference and row["reference"]
        assert row["domain_box"] == oc.domain_box and row["domain_box"]
        assert row["n_grid_points"] > 0


def test_oracle_list_human_table() -> None:
    result = runner.invoke(app, ["oracle", "list"])
    assert result.exit_code == 0, result.output
    assert "闭式预言机注册表" in result.output
    assert "attenuator_pi" in result.output


# ─── check（单键对拍 + 负例）──────────────────────────────────────────────

def test_oracle_check_json_envelope_passes_through_kernel() -> None:
    result = runner.invoke(app, ["oracle", "check", "attenuator_pi", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["schema"] == CLOSED_FORM_ORACLE_SCHEMA
    assert payload["key"] == "attenuator_pi"
    assert payload["kind"] == "independent_network"
    assert payload["grade"] in {"A", "B", "C", "D"}
    assert payload["verdict"] in {"PASS", "FLAG"}
    assert payload["n_grid_points"] > 0
    assert payload["n_evaluated"] > 0
    assert set(payload["per_quantity"]) == {"attenuation_db", "mismatch_loss_db"}
    worst = payload["per_quantity"]["attenuation_db"]
    assert {"n_points", "worst_grade", "worst_rel_err"} <= set(worst)


def test_oracle_check_unknown_key_json_failure_envelope() -> None:
    result = runner.invoke(app, ["oracle", "check", "no_such_key", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)  # --json 失败路径仍须 JSON 信封
    assert payload["ok"] is False
    # AU-2 正形：errors 恒 list[str]（ge8e 审查批由单数 error 键改归）
    assert payload["errors"] == ["未知 oracle 键: no_such_key"]
    assert "no_such_key" in payload["errors"][0]
    assert "attenuator_pi" in payload["known_keys"]


def test_oracle_check_unknown_key_human_exit_1() -> None:
    result = runner.invoke(app, ["oracle", "check", "no_such_key"])
    assert result.exit_code == 1
    assert "no_such_key" in result.output


def test_oracle_check_deterministic_output() -> None:
    # 内核确定性（#118）：同键两次 --json 输出逐位一致。
    out1 = runner.invoke(app, ["oracle", "check", "vswr_convert", "--json"]).output
    out2 = runner.invoke(app, ["oracle", "check", "vswr_convert", "--json"]).output
    assert out1 == out2


# ─── check-all（全注册总报告）─────────────────────────────────────────────

def test_oracle_check_all_json_report() -> None:
    result = runner.invoke(app, ["oracle", "check-all", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == CLOSED_FORM_ORACLE_SCHEMA
    assert payload["n_keys"] >= 20  # ≥20 键覆盖验收口径（内核 docstring）
    assert payload["n_oracles"] == len(payload["rows"])
    assert len(payload["covered_keys"]) == payload["n_keys"]
    assert payload["covered_keys"] == sorted(payload["covered_keys"])
    assert sum(payload["by_grade"].values()) == payload["n_oracles"]
    assert isinstance(payload["ok"], bool)
    # flags 与 rows 的 verdict 互洽（报告面如实透出，不因旗标翻退出码）
    flagged = sorted(k for k, row in payload["rows"].items()
                     if row["verdict"] != "PASS")
    assert payload["flags"] == flagged


def test_oracle_check_all_human_report() -> None:
    result = runner.invoke(app, ["oracle", "check-all"])
    assert result.exit_code == 0, result.output
    assert "oracle 总报告" in result.output
    assert "grade" in result.output
