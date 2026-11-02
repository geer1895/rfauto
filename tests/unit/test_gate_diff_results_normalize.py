"""gate_diff_results 收集期占位条目归一化钉（aurora_n 收口线席 2026-10-31）。

aurora_m W4-8 遗留清偿载体：xdist 对整模收集期 skip（模块级
``pytest.importorskip``，如 tests/unit/test_a7_fdtd_engine 的 fdtdx 门）在
控制器侧 junitxml 物化为 classname 空的占位 skipped 条目，串行收集器不产
——两轮全量实测 diff 恒 1 条（runs/aurora_m/w4_8/）。比对器归一化（缺省
开）对称剔除该形态；本文件钉住识别规则边界——负例（真实差异）不得被误
归一（#122 语义零变：failed/skipped 真实状态差仍逐位红）：

1. 正例：并行臂独有占位条目（classname='' + skipped）归一化后 diff EMPTY
   且输出点名归一化条目（透明性）；
2. 负例①：真实测试运行期 skip 一臂独有（classname 非空）不归一，保持红；
3. 负例②：xfail 旗标条目（classname 非空 + ``<skipped type="pytest.xfail">``）
   一臂独有不归一，保持红；
4. 负例③：收集期错误（classname='' + ``<error>`` 子元素 → status=failed）
   不归一，保持红；
5. 负例④：共同 id 真实状态差（passed→failed）归一化开着仍逐位红；
6. 开关：``--no-normalize`` 关闭归一化 → 占位条目复归差异（取证形态，
   等价 runs/aurora_m/w4_8/ 实测 diff）；
7. 边界：占位所在模块另一臂有真实逐测条目 → 剔除占位后仍红（形态差如实
   显形，不吞）；
8. 识别函数单元钉：形态正/负例直断。

全部合成 junitxml（tmp_path 秒级），不触碰 runs/ 湖。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "gate_diff_results.py"

_spec = importlib.util.spec_from_file_location("gate_diff_results_mod", SCRIPT)
gate_diff = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("gate_diff_results_mod", gate_diff)
_spec.loader.exec_module(gate_diff)

# 占位条目形态（xdist 整模收集期 skip 物化：classname 空、name=模块点路径）
PLACEHOLDER = ("", "tests.unit.test_a7_fdtd_engine", "skipped")


def _write_xml(path: Path, cases: list[tuple[str, str, str]]) -> None:
    """合成 junitxml；cases 元素=(classname, name, kind)。

    kind ∈ passed/skipped/xfail/failed/error（xdiff/xfail 是真实条目的
    skipped 子元素变体，error 是收集期错误物化形态）。
    """
    tcs: list[str] = []
    for classname, name, kind in cases:
        if kind == "passed":
            tcs.append(f'<testcase classname="{classname}" name="{name}"/>')
        elif kind == "skipped":
            tcs.append(f'<testcase classname="{classname}" name="{name}">'
                       f'<skipped message="collection skipped"/></testcase>')
        elif kind == "xfail":
            tcs.append(f'<testcase classname="{classname}" name="{name}">'
                       f'<skipped message="xfail" type="pytest.xfail"/>'
                       f"</testcase>")
        elif kind == "failed":
            tcs.append(f'<testcase classname="{classname}" name="{name}">'
                       f'<failure message="boom"/></testcase>')
        elif kind == "error":
            tcs.append(f'<testcase classname="{classname}" name="{name}">'
                       f'<error message="import boom"/></testcase>')
        else:  # pragma: no cover - 防写错 kind 静默合成空条目
            raise ValueError(f"unknown kind: {kind}")
    xml = ('<testsuites><testsuite name="pytest" tests="{}" failures="0" '
           'skipped="0">{}</testsuite></testsuites>'.format(
               len(tcs), "".join(tcs)))
    path.write_text(xml, encoding="utf-8")


def _common_body() -> list[tuple[str, str, str]]:
    """三真实共同 id（passed），两臂基线。"""
    return [("tests.unit.test_x", "test_a", "passed"),
            ("tests.unit.test_x", "test_b", "passed"),
            ("tests.unit.test_y", "test_c", "passed")]


def test_placeholder_parallel_only_normalized_to_empty(tmp_path, capsys):
    """正例：并行臂独有占位条目归一化 → EMPTY 且输出点名（透明性）。"""
    ser = tmp_path / "serial.xml"
    par = tmp_path / "parallel.xml"
    _write_xml(ser, _common_body())
    _write_xml(par, [*_common_body(), PLACEHOLDER])
    rc = gate_diff.main([str(ser), str(par)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "DIFF: EMPTY" in out
    assert "after collection-skip placeholder normalization" in out
    assert "normalized collection-skip placeholder entries: total=1" in out
    assert "[parallel] ::tests.unit.test_a7_fdtd_engine" in out


def test_real_runtime_skip_parallel_only_stays_red(tmp_path, capsys):
    """负例①：真实测试运行期 skip（classname 非空）一臂独有 → 保持红。"""
    ser = tmp_path / "serial.xml"
    par = tmp_path / "parallel.xml"
    _write_xml(ser, _common_body())
    _write_xml(par, [*_common_body(),
                     ("tests.unit.test_z", "test_env_gate", "skipped")])
    rc = gate_diff.main([str(ser), str(par)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "skipped_only_in_parallel" in out
    assert "tests.unit.test_z::test_env_gate" in out
    assert "DIFF: DIFFERENCES FOUND" in out


def test_xfail_flag_parallel_only_stays_red(tmp_path, capsys):
    """负例②：xfail 旗标条目（skipped[type=pytest.xfail]）一臂独有 → 保持红。"""
    ser = tmp_path / "serial.xml"
    par = tmp_path / "parallel.xml"
    _write_xml(ser, _common_body())
    _write_xml(par, [*_common_body(),
                     ("tests.unit.test_w", "test_cond", "xfail")])
    rc = gate_diff.main([str(ser), str(par)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "skipped_only_in_parallel" in out
    assert "tests.unit.test_w::test_cond" in out


def test_collection_error_empty_classname_stays_red(tmp_path, capsys):
    """负例③：收集期错误（classname='' + error → status=failed）→ 保持红。"""
    ser = tmp_path / "serial.xml"
    par = tmp_path / "parallel.xml"
    _write_xml(ser, _common_body())
    _write_xml(par, [*_common_body(),
                     ("", "tests.unit.test_bad_import", "error")])
    rc = gate_diff.main([str(ser), str(par)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "failed_only_in_parallel" in out
    assert "::tests.unit.test_bad_import" in out
    # 归一化零剔除：占位归一化行不得出现
    assert "normalized collection-skip placeholder entries" not in out


def test_real_status_change_still_red_with_normalization(tmp_path, capsys):
    """负例④：共同 id 真实状态差（passed→failed）归一化开着仍逐位红（#122）。"""
    ser = tmp_path / "serial.xml"
    par = tmp_path / "parallel.xml"
    _write_xml(ser, _common_body())
    _write_xml(par, [("tests.unit.test_x", "test_a", "passed"),
                     ("tests.unit.test_x", "test_b", "failed"),
                     ("tests.unit.test_y", "test_c", "passed")])
    rc = gate_diff.main([str(ser), str(par)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "status_changed" in out
    assert "tests.unit.test_x::test_b: passed -> failed" in out


def test_no_normalize_flag_restores_placeholder_diff(tmp_path, capsys):
    """开关：--no-normalize 关闭归一化 → 占位条目复归差异（w4_8 取证形态）。"""
    ser = tmp_path / "serial.xml"
    par = tmp_path / "parallel.xml"
    _write_xml(ser, _common_body())
    _write_xml(par, [*_common_body(), PLACEHOLDER])
    rc = gate_diff.main(["--no-normalize", str(ser), str(par)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "ids_only_in_parallel" in out
    assert "::tests.unit.test_a7_fdtd_engine" in out
    assert "DIFF: DIFFERENCES FOUND" in out


def test_no_normalize_flag_defaults_on(tmp_path, capsys):
    """开关缺省态：不带旗标=归一化开（与正例钉同路径，防 store_false 反接）。"""
    ser = tmp_path / "serial.xml"
    par = tmp_path / "parallel.xml"
    _write_xml(ser, _common_body())
    _write_xml(par, [*_common_body(), PLACEHOLDER])
    args = gate_diff._build_parser().parse_args([str(ser), str(par)])
    assert args.normalize is True
    args_off = gate_diff._build_parser().parse_args(
        ["--no-normalize", str(ser), str(par)])
    assert args_off.normalize is False
    capsys.readouterr()  # 清掉 parse 阶段无用输出（无输出，防御性）


def test_placeholder_module_with_real_entries_other_arm_still_red(
        tmp_path, capsys):
    """边界：占位模块另一臂有真实逐测条目 → 剔占位后仍红（形态差如实显形）。"""
    ser = tmp_path / "serial.xml"
    par = tmp_path / "parallel.xml"
    _write_xml(ser, [*_common_body(),
                     ("tests.unit.test_a7_fdtd_engine", "test_one", "skipped"),
                     ("tests.unit.test_a7_fdtd_engine", "test_two", "skipped")])
    _write_xml(par, [*_common_body(), PLACEHOLDER])
    rc = gate_diff.main([str(ser), str(par)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "ids_only_in_serial" in out
    assert "tests.unit.test_a7_fdtd_engine::test_one" in out
    assert "tests.unit.test_a7_fdtd_engine::test_two" in out


def test_placeholder_in_both_arms_still_empty(tmp_path, capsys):
    """对称性：占位两臂同在 → 同 id 同状态本来就一致，归一化不破坏。"""
    ser = tmp_path / "serial.xml"
    par = tmp_path / "parallel.xml"
    _write_xml(ser, [*_common_body(), PLACEHOLDER])
    _write_xml(par, [*_common_body(), PLACEHOLDER])
    rc = gate_diff.main([str(ser), str(par)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "DIFF: EMPTY" in out


def test_is_collection_placeholder_unit_boundaries():
    """识别函数单元钉：形态正/负例直断（classname 空 + skipped 双条件）。"""
    assert gate_diff.is_collection_placeholder(
        "::tests.unit.test_a7_fdtd_engine", "skipped")
    # 真实 id：classname 非空（模块点路径）→ 永不匹配
    assert not gate_diff.is_collection_placeholder(
        "tests.unit.test_a7_fdtd_engine::test_one", "skipped")
    # 收集期错误：classname 空但 status=failed → 不匹配（真红保持红）
    assert not gate_diff.is_collection_placeholder(
        "::tests.unit.test_bad_import", "failed")
    # 空 classname 非 skipped（理论形态，防御）→ 不匹配
    assert not gate_diff.is_collection_placeholder(
        "::tests.unit.test_x", "passed")
