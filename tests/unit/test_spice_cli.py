"""Q-X33（aurora_q T-Q22）——``rfauto spice parse`` CLI 叶单测（CLI 钉）。

覆盖面：
- CLI 信封正负例（tmp fixture 零 runs/ 湖写入零网络——#144 家法）；
- usage 错 exit 2（--flavor 词表外，_emit_usage_error #ge1㉙ 契约）vs
  service 信封失败 exit 1 分型；
- --topology/--no-topology 三态（#277 typer 陷阱家法——普通 bool flag
  会把缺省当显式 False 透传）；
- help 卫生（--help 构建成功 + 零裸 %，#305 家族）；
- click 树注册面（spice parse 叶在位 + --json 旗标——W2-C 棘轮对齐）；
- 计数链（#304 家法 grep 字面钉：CLI 311 live 口径——305 基线 + liberty
  2 + 本席 spice 1 + skill 3，五消费面同笔）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.cli.main import app

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_numbers.py"
_SPEC = importlib.util.spec_from_file_location("check_numbers_gate_spice",
                                               _SCRIPT)
check_numbers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_numbers)

FIVE_KEYS = ("elements", "subckts", "controls", "models", "topology")

_NGSPICE_RC = """RC lowpass divider
V1 in 0 DC 0 AC 1
R1 in out 1k
C1 out 0 1u
Rload out gnd 2meg
.end
"""


@pytest.fixture()
def netlist_path(tmp_path: Path) -> Path:
    p = tmp_path / "rc_lpf.cir"
    p.write_text(_NGSPICE_RC, encoding="ascii")
    return p


def _invoke(*args: str):
    return CliRunner().invoke(app, args)


class TestSpiceParseCli:
    def test_help_constructs_no_bare_percent(self):
        result = _invoke("spice", "parse", "--help")
        assert result.exit_code == 0, result.output
        assert "%" not in result.output  # #305 家族：裸 % 让 --help 炸

    def test_json_envelope_ok(self, netlist_path):
        result = _invoke("spice", "parse", str(netlist_path), "--json")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["flavor"] == "ngspice"
        assert set(FIVE_KEYS).issubset(payload.keys())
        assert payload["summary"]["n_elements"] == 4
        assert payload["topology"]["isolated_nodes"] == []

    def test_missing_file_json_envelope_exit_1(self, tmp_path):
        result = _invoke("spice", "parse", str(tmp_path / "gone.cir"), "--json")
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)
        assert "不存在" in payload["errors"][0]

    def test_bad_flavor_usage_error_exit_2(self, netlist_path):
        result = _invoke("spice", "parse", str(netlist_path),
                         "--flavor", "pads", "--json")
        assert result.exit_code == 2  # usage 错与 service 信封失败（1）分型
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert "不在词表" in payload["errors"][0]

    def test_no_topology_flag_summary_fields_null(self, netlist_path):
        result = _invoke("spice", "parse", str(netlist_path),
                         "--no-topology", "--json")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["topology"] is None
        assert payload["summary"]["mna_size"] is None  # 如实 null 非 0
        assert payload["summary"]["n_elements"] == 4

    def test_default_topology_on_and_human_branch(self, netlist_path):
        result = _invoke("spice", "parse", str(netlist_path))
        assert result.exit_code == 0, result.output
        assert "SPICE 网表解析" in result.output  # 人读摘要分支
        assert "MNA 维度" in result.output

    def test_flavor_explicit_spectre(self, tmp_path):
        p = tmp_path / "sp.sp"
        p.write_text(
            "simulator lang=spectre\nR1 (a b) resistor r=1k\n",
            encoding="ascii")
        result = _invoke("spice", "parse", str(p), "--flavor", "spectre",
                         "--json")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["flavor"] == "spectre"
        assert payload["flavor_detected"] is False
        assert payload["elements"][0]["value"] == 1000.0


class TestSpiceRegistrationAndCountChain:
    """注册面 + 计数链（#304 家法：新叶必须同笔钉全部消费面）。"""

    def test_spice_parse_leaf_in_click_tree(self):
        from typer.main import get_command

        cmd = get_command(app)
        spice_group = cmd.commands.get("spice")
        assert spice_group is not None, "spice 域未注册"
        assert "parse" in spice_group.commands
        # --json 旗标在位（W2-C 棘轮：新命令必须带 --json；typer 参数名
        # =json_output，旗标面 --json）
        parse_params = [p.name for p in spice_group.commands["parse"].params]
        assert "json_output" in parse_params
        assert "topology" in parse_params
        assert "flavor" in parse_params

    def test_spice_domain_exactly_one_leaf(self):
        from typer.main import get_command

        cmd = get_command(app)
        assert len(cmd.commands["spice"].commands) == 1

    def test_count_chain_cli_313(self):
        """CLI 313（live 口径：305 基线 + Q-X34 liberty 2 + 本席 Q-X33
        spice 1 + Q-X32 skill 3 + 并发席 citi/sdc 2——#304 家法 grep 字面
        钉，字面随并发席合流笔收敛（本席落树时点 live=313）；本席稳定
        断言=spice 域恰 1 叶 + sum 分型互证（不受后续席位数漂移影响）。"""
        assert check_numbers.count_cli() == 358  # aurora_r M-6 终合流 2026-11-10 统一重钉到终值（原 354；锚历史链见 test_cli/test_check_numbers 主锚）
        counts = check_numbers.cli_leaf_counts()
        assert counts["spice"] == 1
        assert sum(counts.values()) == check_numbers.count_cli()
