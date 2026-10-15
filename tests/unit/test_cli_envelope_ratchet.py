"""CLI 裸 ``{"ok": ...}`` 字面棘轮门（review_aurora_next A5 P2-3 收编批，2026-10-13）。

ge9-R5-P2-③ 立案的纪律缺口：CLI 叶历史存量裸 dict 信封绕开
rfauto.service.envelope 构造器（AU-2 信封契约单源；棘轮门
test_w2_c_json_coverage 只扫 service/mcp 故门绿）。本测试把 CLI 域纳入
同一纪律：``src/rfauto/cli/`` 下 ``{"ok"`` 字面出现次数**只许减少不许
增加**（只收不放棘轮，#325 家法同式）。

棘轮帽（RATCHET_CAP）= F6 收编批后实测 72（收编前 87）。调整规则：
- 新 CLI 叶禁止再造裸 dict 信封——响应信封一律走 ok_envelope/
  error_envelope/skipped_envelope（cli→service 分层合法，构造器输出与
  同形字面逐字节一致，零行为变更）；
- 降低棘轮=同笔把站点改走构造器后调小本值；调大本值=违约（新叶带裸
  字面上来直接红）。

F6 批已收编（构造器化，输出逐字节不变，报告 P2-3 抽样站点）15 处：
fab_app（--vars/--project 缺失 usage 错误）、chain_study（even-odd
--list / study audit quality / 空表×2 / 清单）、calc_vna（vna calibrate
两参数错误 / oracle list / oracle check 未知键）、bands_uq（template-spec
draft 落盘信封）、jobs（status 清单 / cache clear / report pdf 信封）、
_core（_emit_usage_error 单源出口本身）。

ENGH 批再收编 54 处（2026-10-14，构造器化，输出逐字节不变）：
error_envelope 40（agent_kicad 3/chain_study 1/diagnose 3/env_reliability
9/jobs 4/lake 1/layout 1/pdn_aging 6/recipe 1/solvers 1/surrogate 6/
system 2/teaching 1/workflow 1）+ ok_envelope 13（agent_kicad 1/jobs 1/
scattered 4/solvers 1/surrogate 1/system 3/teaching 2）+
skipped_envelope 1（jobs link skipped；service run_link 的 reason 已恒
str，str() 恒等）。

AU-2C 批再收编 9 处（2026-10-14，AU-2 域升版三域，schema 1.1）：单数
error 遗留族全清——anchors 2（drift --history-file 两处，error_envelope+
ANCHORS_REPORT_SCHEMA_VERSION 1.1，消费渲染 _error_text 按序回退）+
firmware 4（beam/varactor/dpd/写盘失败，error_envelope+无戳域补戳
FIRMWARE_EXPORT_SCHEMA_VERSION="1.1"，成功信封同笔带戳 ok_envelope）+
stats 3（guardband/cpk/weibull，error_envelope+无戳域补戳
MANUFACTURING_STATS_SCHEMA_VERSION="1.1"，成功面薄拷贝补戳）。语义特
殊豁免两笔见下（dag 期刊/chain_study 动态归一）。

结构性豁免台账（A5 REPORT.md P2-3 同账，AU-2 信封构造器推广批并案消化）：
- cli/domains/dag.py 3 处=v1 subprocess 节点执行器内部记录
  （ok/outputs/wall_s/message 四键节点期刊 schema，非响应信封——构造器
  化会改 dag 期刊键形，驳）；
- cli/domains/chain_study.py 2 处=service status 口径→ok 口径薄壳归一
  （``{"ok": result.get("status") == "ok", **result}``——ok 为动态计算值
  非字面量，非构造器调用形态）；
- bench_app 1 处=bench 门族 FAIL 信封（reasons 列表承载，契约 §3.2
  reasons 族，非 errors 形，改形即破坏门消费方）；
- 代理误报 2 站 3 处（非信封站点，``{"ok"`` 文本计数假阳性）：
  surrogate.py meta_retrieval helper docstring 返回形态记载 2 处、
  system.py doctor 渲染状态→颜色映射表 1 处（"ok" 为状态键）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

src_dir = Path(__file__).resolve().parents[2] / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

CLI_DIR = src_dir / "rfauto" / "cli"

# 棘轮帽（2026-10-14 AU-2C 三域升版收编批后实测=9；ENGH 收编批 72→18、
# F6 收编批 72、收编前 87，只降不升）
RATCHET_CAP = 9


def _count_bare_ok_literals() -> tuple[int, list[str]]:
    """逐文件统计 src/rfauto/cli/ 下 ``{"ok"`` 字面出现次数（原文计数）。"""
    per_file: list[str] = []
    total = 0
    for path in sorted(CLI_DIR.rglob("*.py")):
        n = path.read_text(encoding="utf-8").count('{"ok"')
        if n:
            per_file.append(f"  {path.relative_to(CLI_DIR.parent)}: {n}")
            total += n
    return total, per_file


def test_cli_bare_ok_envelope_ratchet():
    """裸 ``{"ok"`` 字面计数 ≤ 棘轮帽（只收不放；明细随失败消息落出）。"""
    total, per_file = _count_bare_ok_literals()
    assert total <= RATCHET_CAP, (
        f'CLI 裸 {{"ok": ...}} 字面计数超棘轮帽（{total} > {RATCHET_CAP}）'
        "——新 CLI 叶响应信封必须走 rfauto.service.envelope 构造器"
        "（ok_envelope/error_envelope/skipped_envelope），禁止再造裸 dict "
        "信封（review_aurora_next A5 P2-3 / ge9-R5-P2-③ 纪律）。降低本棘轮="
        "同笔把站点改走构造器（输出逐字节不变）后调小 RATCHET_CAP；"
        "调大=违约。当前计数明细：\n" + "\n".join(per_file))


def test_ratchet_cap_matches_current_tree():
    """帽值与树面实测一致（防帽值漂移失真：改站点必须同笔调帽）。"""
    total, _ = _count_bare_ok_literals()
    assert total == RATCHET_CAP, (
        f"棘轮帽 {RATCHET_CAP} 与树面实测 {total} 不一致——收编/回潮后"
        "必须同笔校准 RATCHET_CAP（只许调小）")


# ── 收编站点信封形态回归钉（构造器化后输出契约不变；离线零仿真零写盘）───────

runner = CliRunner()


def _parse_json_envelope(output: str) -> dict:
    """CliRunner 输出 → JSON 信封（rich print_json 缩进格式容忍解析）。"""
    return json.loads(output)


def test_oracle_list_json_envelope_shape():
    """oracle list --json：ok_envelope 收编钉（ok/schema/n_oracles/oracles）。"""
    from rfauto.cli.main import app as root_app

    result = runner.invoke(root_app, ["oracle", "list", "--json"])
    assert result.exit_code == 0, result.output
    envelope = _parse_json_envelope(result.output)
    assert envelope["ok"] is True
    assert envelope["n_oracles"] == len(envelope["oracles"])
    assert isinstance(envelope["schema"], str)  # 口径标识串（非 schema 体）


def test_even_odd_list_json_envelope_shape():
    """even-odd --list --json：ok_envelope 收编钉（ok/templates 键集）。"""
    from rfauto.cli.main import app as root_app

    result = runner.invoke(root_app, ["even-odd", "--list", "--json"])
    assert result.exit_code == 0, result.output
    envelope = _parse_json_envelope(result.output)
    assert envelope["ok"] is True
    assert isinstance(envelope["templates"], list)
    for ent in envelope["templates"]:
        assert "template" in ent


# ── AU-2C 三域升版信封形态回归钉（2026-10-14；离线零仿真零写盘）───────────────
#
# 单数 error 遗留族 9 处（anchors 2/firmware 4/stats 3）按域升版统一：
# 失败形 error_envelope 单源（ok/errors/schema_version 键序），无戳域补戳
# 1.1、成功信封同笔带戳。


def test_anchors_drift_bad_history_file_error_envelope_shape(tmp_path):
    """anchors drift --history-file 非法两站点：error_envelope 迁移钉。

    CLI 失败面渲染沿既有行为（rich ✗ 文案行，--json 只作用于成功信封
    直出）；信封形状由 error_envelope 单源钉在服务面
    （test_anchors_store_service.test_service_envelopes_schema_version_1_1），
    此处钉两站点的消费渲染经 _error_text 回退链可达。
    """
    from rfauto.cli.domains.anchors import _error_text
    from rfauto.cli.main import app as root_app

    # 消费渲染回退链（消费同笔迁移钉）：新形 errors → 旧形 error → reason
    assert _error_text({"ok": False, "errors": ["a 错", "b 错"]}) == "a 错; b 错"
    assert _error_text({"ok": False, "error": "旧形"}) == "旧形"
    assert _error_text({"ok": False, "reason": "跳过形"}) == "跳过形"
    assert _error_text({"ok": False}) == "未知错误"

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    result = runner.invoke(
        root_app,
        ["anchors", "drift", "cps.gamma_er.fdref-v1",
         "--history-file", str(bad)])
    assert result.exit_code == 1, result.output
    assert "✗" in result.output and "history_file" in result.output

    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text(json.dumps({"other": [1]}), encoding="utf-8")
    result = runner.invoke(
        root_app,
        ["anchors", "drift", "cps.gamma_er.fdref-v1",
         "--history-file", str(wrong_shape)])
    assert result.exit_code == 1, result.output
    assert "序列/快照数组" in result.output


def test_firmware_beam_missing_key_error_envelope_shape(tmp_path):
    """firmware beam 载荷缺键：error_envelope 键序钉（无戳域补戳 1.1）。"""
    from rfauto.cli.domains.firmware import FIRMWARE_EXPORT_SCHEMA_VERSION
    from rfauto.cli.main import app as root_app

    assert FIRMWARE_EXPORT_SCHEMA_VERSION == "1.1"
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({"element_ids": ["e0"]}), encoding="utf-8")
    result = runner.invoke(
        root_app,
        ["firmware", "beam", "--bits", "2", "--file", str(payload)])
    assert result.exit_code == 1, result.output
    envelope = json.loads(result.output)
    assert envelope["ok"] is False
    assert list(envelope) == ["ok", "errors", "schema_version"]
    assert "波束码字表失败" in envelope["errors"][0]
    assert envelope["schema_version"] == "1.1"


def test_stats_cpk_missing_spec_error_envelope_shape():
    """stats cpk 缺规格限（内核 ValueError）：error_envelope 键序钉（补戳 1.1）。"""
    from rfauto.cli.domains.stats import MANUFACTURING_STATS_SCHEMA_VERSION
    from rfauto.cli.main import app as root_app

    assert MANUFACTURING_STATS_SCHEMA_VERSION == "1.1"
    result = runner.invoke(
        root_app,
        ["stats", "cpk", "--samples", "1.0,2.0,1.5"])
    assert result.exit_code == 1, result.output
    envelope = json.loads(result.output)
    assert envelope["ok"] is False
    assert list(envelope) == ["ok", "errors", "schema_version"]
    assert "lsl/usl 至少提供一个" in envelope["errors"][0]
    assert envelope["schema_version"] == "1.1"


def test_firmware_stats_success_envelopes_stamped(tmp_path):
    """成功信封同笔带戳钉：键序 ok → schema_version → 域字段。"""
    from rfauto.cli.main import app as root_app

    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({
        "element_ids": [0, 1],
        "x_mm": [0.0, 1.0], "y_mm": [0.0, 0.0],
        "phase_target_deg": [0.0, 90.0],
    }), encoding="utf-8")
    result = runner.invoke(
        root_app, ["firmware", "beam", "--bits", "2",
                   "--file", str(payload)])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["ok"] is True
    assert list(envelope)[:2] == ["ok", "schema_version"]
    assert envelope["schema_version"] == "1.1"

    result = runner.invoke(
        root_app, ["stats", "guardband", "1.0", "--u95", "0.1",
                   "--tu", "1.2", "--side", "upper"])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["ok"] is True
    assert list(envelope)[:2] == ["ok", "schema_version"]
    assert envelope["schema_version"] == "1.1"
