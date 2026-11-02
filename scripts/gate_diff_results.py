"""DP-6 守卫比对器：串行 vs 并行两份 junitxml 逐位比对。

规格：docs/plan_deepdive_specs_20260924.md §DP-6——测试 id 集合+失败/跳过
集合逐位比对，diff 为空才算守卫过；任一轮不一致 → 冻结并行、`-n0`
串行复现按 flake 流程取证。

收集期占位条目归一化（aurora_n 收口线席 2026-10-31 落地；aurora_m W4-8
两轮 diff 恒 1 条遗留的 followUp 清偿。预声明识别规则）：
- 占位形态：junitxml 中 **classname 为空**（id 以 ``::`` 开头，name=模块
  点路径，如 ``::tests.unit.test_a7_fdtd_engine``，message=
  "collection skipped"）且 **status=skipped** 的条目——xdist 控制器侧对
  "整模收集期 skip"（模块级 ``pytest.importorskip``，如 fdtdx 未装门）的
  物化占位；串行收集器不产该条目（runs/aurora_m/w4_8/ 两轮全量实测：
  唯一差异恒为此条，两臂 28828 个共同 id 状态逐位一致=报告形态差非
  结果差）。
- 归一化动作：比对前从**两臂** id 映射中同步剔除占位条目。占位条目 id
  以 ``::`` 开头（空 classname 段），真实测试 id 的 classname 恒为非空
  模块点路径——两者构造性不相交，剔除永不吞真实 id。
- 负例红线（#122 语义零变：failed/skipped **真实状态差**仍逐位比对）：
  ①真实 skip 差异（运行期 skip、xfail 旗标条目）classname 恒非空，不
  满足形态规则，保持红；②收集期**错误**（import 炸）classname 同为空但
  带 failure/error 子元素 → status=failed，不满足 status=skipped，保持红；
  ③占位所在模块若在另一臂有真实条目（如串行侧物化出逐测 skipped 行），
  剔除占位后该侧条目仍计 ids_only 差异保持红。
- 开关：缺省**开**（比对器报告噪声滤除=守卫语义升级，非门判定放宽——
  gate_diff_results 是比对工具不是门本身）；``--no-normalize`` 关闭供
  取证复算（关闭后应复现 aurora_m w4_8 形态差，证据钉
  tests/unit/test_gate_diff_results_normalize.py）。

用法：
    .venv/Scripts/python.exe scripts/gate_diff_results.py SERIAL.xml PARALLEL.xml
    .venv/Scripts/python.exe scripts/gate_diff_results.py --help

exit code：0=两份一致（占位归一化后；--no-normalize 时逐条目一致）
（守卫过）；1=存在差异；2=解析/用法错误（argparse 缺参/坏参亦走 2）。
比对维度：collected id 集合、failed 集合、skipped 集合、逐 id 状态变化。
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def load_cases(xml_path: Path) -> dict[str, str]:
    """解析 junitxml → {test_id: status}；status ∈ passed/failed/skipped。

    test_id = classname::name（pytest junitxml 口径，含参数化后缀，
    足以逐位区分收集项）。
    """
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        raise SystemExit(f"2: 无法解析 {xml_path}: {exc}") from exc
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    cases: dict[str, str] = {}
    for suite in suites:
        for tc in suite.iter("testcase"):
            cid = f"{tc.get('classname', '')}::{tc.get('name', '')}"
            if tc.find("failure") is not None or tc.find("error") is not None:
                status = "failed"
            elif tc.find("skipped") is not None:
                status = "skipped"
            else:
                status = "passed"
            cases[cid] = status
    return cases


def is_collection_placeholder(cid: str, status: str) -> bool:
    """收集期整模 skip 占位条目识别（预声明规则，见模块 docstring）。

    形态 = classname 为空（junitxml id 以 ``::`` 开头的空 classname 段）
    且 status=skipped。负例边界：
    - 真实测试条目（含运行期 skip / xfail 旗标）classname 恒非空 →
      id 不以 ``::`` 开头，永不误判（真实 skip 差异保持红）；
    - 收集期错误（import 炸）classname 同为空但 load_cases 因
      failure/error 子元素判 status="failed"，不满足 status=skipped，
      永不归一（真红保持红）。
    """
    return status == "skipped" and cid.startswith("::")


def strip_collection_placeholders(
        cases: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """剔除收集期占位条目；返回 (剩余映射, 被剔除 id 列表)。

    两臂同用本函数（对称剔除）——占位 id 与真实 id 构造性不相交
    （真实 id classname 非空），剔除永不改变真实条目的比对结果。
    """
    dropped = sorted(k for k, v in cases.items()
                     if is_collection_placeholder(k, v))
    dropped_set = set(dropped)
    return ({k: v for k, v in cases.items() if k not in dropped_set},
            dropped)


def _build_parser() -> argparse.ArgumentParser:
    """E-08（2026-10-04）：手动 argv 换 argparse——--help 可用（rc=0）、
    缺参/坏参错误信息标准库化（argparse error 退出码 2，与原用法错误口径同）。"""
    parser = argparse.ArgumentParser(
        prog="gate_diff_results.py",
        description="DP-6 守卫比对器：串行 vs 并行两份 junitxml 的 "
                    "id/failed/skipped 集合逐位比对；exit 0=一致 1=有差异 2=用法/解析错误")
    parser.add_argument(
        "serial_xml", type=Path,
        help="串行轮 junitxml（pytest -n0）")
    parser.add_argument(
        "parallel_xml", type=Path,
        help="并行轮 junitxml（pytest-xdist）")
    parser.add_argument(
        "--no-normalize", dest="normalize", action="store_false",
        help="关闭收集期占位条目归一化（取证复算用；缺省开——aurora_m "
             "W4-8 遗留的 xdist 整模 skip 占位条目不再计差异，规则见 "
             "模块 docstring）")
    parser.set_defaults(normalize=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    # E-08：sys.argv 手动 len 校验 → argparse（--help/-- 自动机能；错误 rc=2 同口径）
    args = _build_parser().parse_args(argv)
    serial_xml, parallel_xml = args.serial_xml, args.parallel_xml
    for p in (serial_xml, parallel_xml):
        if not p.is_file():
            print(f"2: 文件不存在: {p}")
            return 2

    serial = load_cases(serial_xml)
    parallel = load_cases(parallel_xml)

    # 收集期占位条目归一化（缺省开）：对称剔除两臂的整模 skip 物化占位
    # （规则与负例边界见模块 docstring / is_collection_placeholder）。
    dropped_by_arm: dict[str, list[str]] = {}
    if args.normalize:
        serial, dropped_s = strip_collection_placeholders(serial)
        parallel, dropped_p = strip_collection_placeholders(parallel)
        if dropped_s or dropped_p:  # 零剔除不打印归一化行（不属报告噪声）
            dropped_by_arm = {"serial": dropped_s, "parallel": dropped_p}

    serial_ids = set(serial)
    parallel_ids = set(parallel)
    serial_failed = {k for k, v in serial.items() if v == "failed"}
    parallel_failed = {k for k, v in parallel.items() if v == "failed"}
    serial_skipped = {k for k, v in serial.items() if v == "skipped"}
    parallel_skipped = {k for k, v in parallel.items() if v == "skipped"}
    status_changed = sorted(
        k for k in serial_ids & parallel_ids if serial[k] != parallel[k])

    diffs: list[str] = []
    for title, items in (
        ("ids_only_in_serial", sorted(serial_ids - parallel_ids)),
        ("ids_only_in_parallel", sorted(parallel_ids - serial_ids)),
        ("failed_only_in_serial", sorted(serial_failed - parallel_failed)),
        ("failed_only_in_parallel", sorted(parallel_failed - serial_failed)),
        ("skipped_only_in_serial", sorted(serial_skipped - parallel_skipped)),
        ("skipped_only_in_parallel", sorted(parallel_skipped - serial_skipped)),
    ):
        if items:
            diffs.append(f"{title} ({len(items)}):")
            diffs.extend(f"  {i}" for i in items)
    if status_changed:
        diffs.append(f"status_changed ({len(status_changed)}):")
        diffs.extend(f"  {k}: {serial[k]} -> {parallel[k]}"
                     for k in status_changed)

    print(f"serial:   collected={len(serial_ids)} "
          f"failed={len(serial_failed)} skipped={len(serial_skipped)}")
    print(f"parallel: collected={len(parallel_ids)} "
          f"failed={len(parallel_failed)} skipped={len(parallel_skipped)}")
    if dropped_by_arm:
        total = sum(len(v) for v in dropped_by_arm.values())
        print(f"normalized collection-skip placeholder entries: "
              f"total={total} (serial={len(dropped_by_arm['serial'])} "
              f"parallel={len(dropped_by_arm['parallel'])}; "
              f"report-form noise, not result difference)")
        for arm, dropped in dropped_by_arm.items():
            for i in dropped:
                print(f"  [{arm}] {i}")
    if diffs:
        print("\n".join(diffs))
        print("DIFF: DIFFERENCES FOUND")
        return 1
    verdict = "DIFF: EMPTY (identical id/failed/skipped sets)"
    if dropped_by_arm:
        verdict += " after collection-skip placeholder normalization"
    print(verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
