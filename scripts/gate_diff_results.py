"""DP-6 守卫比对器：串行 vs 并行两份 junitxml 逐位比对。

规格：规格深案 §DP-6——测试 id 集合+失败/跳过
集合逐位比对，diff 为空才算守卫过；任一轮不一致 → 冻结并行、`-n0`
串行复现按 flake 流程取证。

用法：
    .venv/Scripts/python.exe scripts/gate_diff_results.py SERIAL.xml PARALLEL.xml
    .venv/Scripts/python.exe scripts/gate_diff_results.py --help

exit code：0=两份完全一致（守卫过）；1=存在差异；2=解析/用法错误
（argparse 缺参/坏参亦走 2）。
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
    if diffs:
        print("\n".join(diffs))
        print("DIFF: DIFFERENCES FOUND")
        return 1
    print("DIFF: EMPTY (identical id/failed/skipped sets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
